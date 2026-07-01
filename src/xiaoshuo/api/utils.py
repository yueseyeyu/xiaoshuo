"""API 工具函数 — 书籍元数据解析、标签/评分读取、数据加载"""

from __future__ import annotations
import csv
import json
import re
from pathlib import Path


def safe_read_json(path: Path, default=None) -> dict:
    """安全读取 JSON 文件"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else {}


def safe_write_json(path: Path, data: dict) -> None:
    """安全写入 JSON 文件（原子性写入）"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def parse_title_author(name: str, meta: dict | None = None) -> tuple[str, str]:
    """从文件名或元数据解析书名和作者"""
    author = ""
    title = name
    if meta:
        author = (meta.get("author") or "").strip()
        file_name = (meta.get("file") or "").strip()
        if file_name:
            title = file_name.replace(".txt", "").strip()
    # 统一从标题末尾提取作者
    m = re.search(r"作者[：:]\s*(.+)$", title)
    if m:
        author = author or m.group(1).strip()
        title = title[:m.start()].strip()
    # 去掉常见后缀与书名号
    title = re.sub(r"[（(](校对版|精校版|校对全本|全本|番外|完结)[^）)]*[）)]", "", title)
    title = title.strip("《》 ").strip()
    return title, author or "未知作者"


def estimate_word_count(size_kb: int) -> int:
    """按约 1.8 字节/字估算中文字数"""
    return max(0, round(size_kb * 1024 / 1.8))


def get_book_tags(project_root: Path, genre: str, name: str) -> list[str]:
    """构建标签列表：大类(题材) + 子类(LLM分类) + 内容标签(labels高频)
    
    返回格式: [题材, 子类, 内容标签1, 内容标签2]
    """
    tags = [genre] if genre else []
    
    # 子类标签：从 sub_genre_llm.json 读取
    sub_genre_path = project_root / "data" / "processed" / genre / "quality" / "sub_genre_llm.json"
    if sub_genre_path.exists():
        try:
            sub_data = json.loads(sub_genre_path.read_text(encoding="utf-8-sig"))
            sub_genre = sub_data.get(name)
            if sub_genre:
                tags.append(sub_genre)
        except Exception:
            pass
    
    # 内容标签：从 labels 文件读取高频标签
    labels_dir = project_root / "data" / "processed" / genre / "labels"
    candidate = labels_dir / f"{name}_labels.csv"
    if candidate.exists():
        try:
            counts: dict[str, float] = {}
            with open(candidate, encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    if (row.get("ch_num") or "").lower() == "summary":
                        continue
                    for k, v in row.items():
                        if k == "ch_num":
                            continue
                        try:
                            val = float(v or 0)
                        except ValueError:
                            continue
                        if val > 0:
                            tag = re.sub(r"^(regex_|llm_)", "", k)
                            counts[tag] = counts.get(tag, 0.0) + val
            content_tags = [tag for tag, _ in sorted(counts.items(), key=lambda x: x[1], reverse=True)[:2]]
            tags.extend(content_tags)
        except Exception:
            pass
    
    return tags[:4]  # 最多 4 个标签


def get_book_score(project_root: Path, genre: str, name: str) -> float | None:
    """从 scores 文件读取平均 hook/retention 评分"""
    scores_dir = project_root / "data" / "processed" / genre / "scores"
    candidate = scores_dir / f"{name}_llm.csv"
    if not candidate.exists():
        return None
    try:
        scores: list[float] = []
        with open(candidate, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                for key in ("llm_retention", "llm_hook"):
                    val = row.get(key)
                    if val:
                        try:
                            scores.append(float(val))
                        except ValueError:
                            pass
        if not scores:
            return None
        return round(sum(scores) / len(scores), 1)
    except Exception:
        return None


def load_novel_index(project_root: Path) -> dict[str, dict]:
    """读取 novel_index.json 并按题材建立 file->metadata 索引"""
    path = project_root / "data" / "raw" / "novel_index.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        result: dict[str, dict] = {}
        for g, info in (data.get("genres") or {}).items():
            result[g] = {}
            for novel in info.get("novels", []):
                result[g][novel.get("file", "")] = novel
        return result
    except Exception:
        return {}


def get_available_books(project_root: Path, genre: str = "末世") -> list[dict]:
    """从 data/processed/ 和 data/raw/novels/ 读取书列表
    
    已处理的书 status=analyzed，仅原始文件的书 status=pending
    """
    books = []
    index = load_novel_index(project_root)
    meta_by_file = index.get(genre, {})
    
    # 1. 已处理的书（有 rhythm CSV）
    processed = project_root / "data" / "processed" / genre
    analyzed_stems = set()
    if (processed / "rhythm").exists():
        for f in sorted((processed / "rhythm").glob("rhythm_*.csv")):
            stem = f.stem.replace("rhythm_", "")
            analyzed_stems.add(stem)
            meta = None
            for file_name, m in meta_by_file.items():
                if file_name.replace(".txt", "").strip() == stem:
                    meta = m
                    break
            title, author = parse_title_author(stem, meta)
            size_kb = meta.get("size_kb", 0) if meta else 0
            word_count = estimate_word_count(size_kb)
            tags = get_book_tags(project_root, genre, stem)
            score = get_book_score(project_root, genre, stem)
            books.append({
                "title": title,
                "author": author,
                "genre": genre,
                "wordCount": word_count,
                "size_kb": size_kb,
                "status": "analyzed",
                "file": f.name,
                "stem": stem,
                "tags": tags,
                "score": score,
            })
    
    # 2. 仅原始文件的书（在 data/raw/novels/ 中但未处理）
    raw_dir = project_root / "data" / "raw" / "novels" / genre
    if raw_dir.exists():
        for f in sorted(raw_dir.glob("*.txt")):
            stem = f.stem
            if stem in analyzed_stems:
                continue
            meta = meta_by_file.get(f.name)
            title, author = parse_title_author(stem, meta)
            size_kb = round(f.stat().st_size / 1024) if f.exists() else 0
            word_count = estimate_word_count(size_kb)
            books.append({
                "title": title,
                "author": author,
                "genre": genre,
                "wordCount": word_count,
                "size_kb": size_kb,
                "status": "pending",
                "file": f.name,
                "stem": stem,
                "tags": [genre],
                "score": None,
            })
    
    return books


def get_genre_counts(project_root: Path) -> tuple[list[str], list[list]]:
    """扫描 data/raw/novels/ 下所有题材及书籍数量"""
    raw_root = project_root / "data" / "raw" / "novels"
    counts = []
    genres = []
    if raw_root.exists():
        for genre_dir in sorted(d for d in raw_root.iterdir() if d.is_dir()):
            count = len(list(genre_dir.glob("*.txt")))
            if count > 0:
                genres.append(genre_dir.name)
                counts.append([genre_dir.name, count])
    return genres, counts


def get_chapter_instructions(project_root: Path, book: str, chapter: int, genre: str = "末世") -> dict:
    """从已有的 writing_instructions 数据中读取"""
    books_dir = project_root / "data" / "processed" / genre / "writing_instructions"
    if not books_dir.exists():
        return {"book": book, "chapter": chapter, "instructions": [], "error": "no data"}
    safe_name = book.replace(" ", "_")
    candidate = books_dir / f"{safe_name}_instructions.csv"
    if candidate.exists():
        rows = []
        with open(candidate, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                rows.append(r)
        return {"book": book, "chapter": chapter, "instructions": rows, "total": len(rows)}
    return {"book": book, "chapter": chapter, "instructions": [], "total": 0}