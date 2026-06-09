"""
book_processor.py — 书籍入库流水线 v2

流程: books/in/*.txt → 编码检测/转码 → 类型检测 → 基础过滤
      → 通过: data/raw/novels/ (进入分析管线)
      → 未通过: books/review/ (待作者审查)
      → 后续: quality_gate.py 在分析后会再次审查，不达标→退回 review

阈值全部从 config.yaml analysis.book_filter 读取 (SSOT).

用法: python analysis/book_processor.py [--help]
"""
import re, shutil, yaml
from pathlib import Path

ROOT = Path(__file__).parent.parent
BOOKS_IN = ROOT / "books" / "in"
BOOKS_REVIEW = ROOT / "books" / "review"
NOVELS_RAW = ROOT / "data" / "raw" / "novels"
CONFIG_PATH = ROOT / "config.yaml"
NOVEL_INDEX = ROOT / "data" / "raw" / "novel_index.json"

# ── L2: Keywords with discriminative weight (high=strong genre signal, low=common word) ──
# Design: weight reflects P(genre|keyword). "丧尸"≈100%→末世, "进化"→multi-genre→0.1
GENRE_KEYWORDS = {
    "末世": {"丧尸": 1.0, "末日": 0.9, "废土": 0.8, "灾变": 0.7,
              "异兽": 0.5, "兽潮": 0.5, "变异": 0.4,
              "生存": 0.2, "进化": 0.1, "觉醒": 0.15, "末世": 0.9},
    "科幻": {"星舰": 1.0, "外星": 0.9, "银河": 0.8, "人工智能": 0.8,
              "太空": 0.7, "科幻": 0.9, "星际": 0.8, "飞船": 0.5,
              "光速": 0.4},
    "玄幻": {"练气": 0.8, "斗气": 0.8, "魔法": 0.7, "武魂": 0.7,
              "玄幻": 0.5, "异界": 0.6, "召唤": 0.6, "魂环": 0.8},
    "仙侠": {"金丹": 1.0, "元婴": 1.0, "修仙": 0.9, "飞升": 0.8,
              "渡劫": 0.8, "灵根": 0.7, "飞剑": 0.7, "仙侠": 0.9,
              "筑基": 0.8, "炼气": 0.7, "剑修": 0.7},
    "无限流": {"主神": 1.0, "轮回": 0.8, "副本": 0.7, "无限流": 0.9,
               "穿梭": 0.5, "诸天": 0.5, "位面": 0.5},
    "历史": {"大明": 1.0, "明朝": 1.0, "崇祯": 1.0, "唐朝": 1.0,
              "三国": 1.0, "穿越": 0.15, "古代": 0.5, "帝国": 0.5,
              "皇帝": 0.6, "朝廷": 0.7, "大宋": 1.0, "清朝": 1.0},
    "都市": {"都市": 0.9, "校花": 0.8, "总裁": 0.8, "重生": 0.15,
              "系统": 0.1, "上班": 0.7, "公司": 0.6, "现代": 0.6},
    "悬疑": {"恐怖": 0.8, "诡异": 0.8, "鬼": 0.7, "诅咒": 0.7,
              "悬疑": 0.9, "推理": 0.8, "凶杀": 0.8, "刑警": 0.7},
    "武侠": {"武功": 0.8, "内力": 0.9, "江湖": 0.8, "刀法": 0.7,
              "剑法": 0.7, "武林": 0.9, "轻功": 0.8, "武侠": 0.9},
    # P0: 新增词库 (Marvis审查)
    "洪荒": {"盘古": 1.0, "鸿钧": 1.0, "三清": 1.0, "通天": 0.9,
              "太上": 0.9, "原始": 0.9, "昆仑": 0.8, "洪荒": 0.9,
              "圣人": 0.7, "封神": 0.8, "准提": 0.9, "接引": 0.9,
              "女娲": 0.9, "东皇": 0.8, "巫族": 0.8, "妖族": 0.7},
    "游戏": {"网游": 1.0, "电竞": 0.9, "全息": 0.8, "副本": 0.5,
              "BOSS": 0.6, "NPC": 0.6, "等级": 0.3, "任务": 0.2},
    "奇幻": {"魔法": 1.0, "异世界": 0.9, "龙": 0.5, "精灵": 0.8,
              "矮人": 0.8, "魔兽": 0.7, "剑与魔法": 0.9},
}
# L1: Title rule — title keyword → direct genre mapping (overrides L2)
TITLE_RULES = {
    "大明": "历史", "三国": "历史", "唐朝": "历史", "大宋": "历史",
    "明朝": "历史", "清朝": "历史", "崇祯": "历史",
    "穿越到古代": "历史",
    "电影世界": "无限流", "位面": "无限流", "诸天": "无限流",
    "末世": "末世", "末日": "末世", "废土": "末世",
    "修仙": "仙侠", "飞升": "仙侠", "仙侠": "仙侠",
    "星际": "科幻", "星舰": "科幻", "赛博": "科幻", "机甲": "科幻", "银河": "科幻",
    "武侠": "武侠", "武林": "武侠",
    # P0: 扩充 — 游戏/奇幻/无限流/历史
    "网游": "游戏", "电竞": "游戏", "全息游戏": "游戏",
    "魔法": "奇幻", "异世界": "奇幻",
    "无限": "无限流", "轮回": "无限流",
    "南宋": "历史", "北宋": "历史", "春秋": "历史", "楚汉": "历史",
    # P0: Marvis审查补充
    "洪荒": "洪荒", "玩家": "无限流", "诡异": "悬疑",
    "终焉": "无限流", "星空": "科幻",
}
# L2 threshold: if weighted score < MIN_SCORE, fallback to "未知"
GENRE_MIN_SCORE = 2.0
# P0: confidence gate — low confidence = signal too dispersed
MIN_CONFIDENCE = 0.40


def _load_filter_config():
    """Load book_filter thresholds from config.yaml. Returns dict with defaults."""
    defaults = {
        "min_size_kb": 200, "min_chapters": 5,
        "min_chinese_density": 0.40, "known_quality_list": [],
        "known_genre_map": {},
    }
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f) or {}
            bf = cfg.get("analysis", {}).get("book_filter", {})
            result = dict(defaults)
            for key in result:
                if key in bf:
                    result[key] = bf[key]
            return result
    except Exception:
        pass
    return defaults


def detect_encoding(filepath: Path) -> str:
    """Detect text file encoding."""
    raw = filepath.read_bytes()
    if raw[:3] == b'\xef\xbb\xbf':
        return "UTF-8-BOM"
    if raw[:2] == b'\xff\xfe':
        return "UTF-16-LE"
    if raw[:2] == b'\xfe\xff':
        return "UTF-16-BE"
    try:
        raw.decode('utf-8')
        return "UTF-8"
    except:
        pass
    try:
        raw.decode('gbk')
        return "GBK"
    except:
        pass
    return "UNKNOWN"


def convert_to_utf8(filepath: Path) -> bool:
    """Convert GBK to UTF-8 in-place. Returns True if converted."""
    raw = filepath.read_bytes()
    try:
        raw.decode('utf-8')
        return False  # Already UTF-8
    except:
        pass
    try:
        text = raw.decode('gbk')
        filepath.write_text(text, encoding='utf-8')
        return True
    except:
        pass
    try:
        text = raw.decode('gb18030')
        filepath.write_text(text, encoding='utf-8')
        return True
    except:
        pass
    return False


def detect_genre(filepath: Path) -> str:
    """Three-tier genre detection: L1 title → L2 weighted keywords → L3 fallback.
    Returns single best-match genre string, or '未知' if ambiguous."""
    filename = filepath.stem
    text_head = filepath.read_text(encoding='utf-8', errors='replace')[:50000]

    # ── L1: Title rules (highest priority) ──
    # P0: L1 仅匹配书名, 不扫描 text_head (避免简介/首段误触发)
    for keyword, genre in sorted(TITLE_RULES.items(),
                                  key=lambda x: -len(x[0])):  # longer match first
        if keyword in filename:
            return genre

    # ── L2: Weighted keyword scoring ──
    scores = {}
    for genre, kws in GENRE_KEYWORDS.items():
        total = sum(text_head.count(kw) * weight for kw, weight in kws.items())
        if total > 0:
            scores[genre] = total
    if not scores:
        return "未知"

    top_genre = max(scores, key=scores.get)
    top_score = scores[top_genre]
    if top_score < GENRE_MIN_SCORE:
        return "未知"

    # ── L2a: Ambiguity check — if 2nd place is within 30% of 1st, mark as 未知
    if len(scores) >= 2:
        sorted_g = sorted(scores.items(), key=lambda x: -x[1])
        if sorted_g[1][1] > top_score * 0.7:
            return "未知"

    return top_genre


def detect_genre_multi(filepath: Path) -> dict:
    """Multi-label genre detection (R3: replaces single-genre + '未知' with vector).

    Returns:
        {"primary": str,           # highest-score genre
         "secondary": [str],       # genres within 30% of primary
         "scores": {str: float},   # full weighted score vector
         "confidence": float,      # primary / sum(all scores), 0-1
         "method": str}            # "L1_title" | "L2_keywords" | "unknown"
    """
    filename = filepath.stem
    text_head = filepath.read_text(encoding='utf-8', errors='replace')[:50000]

    # ── L1: Title rules (longest match first) ──
    # Collect all L1 title matches (support multi-title keyword hits)
    # P0: L1 仅匹配书名
    l1_matches = []
    for keyword, genre in sorted(TITLE_RULES.items(), key=lambda x: -len(x[0])):
        if keyword in filename:
            l1_matches.append(genre)
    if l1_matches:
        primary = l1_matches[0]
        secondary = [g for g in l1_matches[1:] if g != primary]
        # Also compute L2 scores for reference
        scores = {}
        for genre, kws in GENRE_KEYWORDS.items():
            total = sum(text_head.count(kw) * weight for kw, weight in kws.items())
            if total > 0:
                scores[genre] = round(total, 2)
        return {
            "primary": primary,
            "secondary": secondary,
            "scores": scores,
            "confidence": 0.95,  # L1 title = highest confidence
            "method": "L1_title"
        }

    # ── L2: Weighted keyword scoring ──
    scores = {}
    for genre, kws in GENRE_KEYWORDS.items():
        total = sum(text_head.count(kw) * weight for kw, weight in kws.items())
        if total > 0:
            scores[genre] = round(total, 2)
    if not scores:
        return {
            "primary": "未知", "secondary": [], "scores": {},
            "confidence": 0.0, "method": "unknown"
        }

    sorted_g = sorted(scores.items(), key=lambda x: -x[1])
    top_genre, top_score = sorted_g[0]

    if top_score < GENRE_MIN_SCORE:
        return {
            "primary": "未知", "secondary": [], "scores": scores,
            "confidence": 0.0, "method": "L2_keywords"
        }

    # L2a: Multi-label — genres within 30% of primary become secondary (not "未知")
    secondary = []
    if len(sorted_g) >= 2:
        for genre, score in sorted_g[1:]:
            if score > top_score * 0.7:
                secondary.append(genre)

    score_sum = sum(v for v in scores.values())
    confidence = round(top_score / max(score_sum, 1), 3)

    # P0: MIN_CONFIDENCE gate — low confidence = signal too dispersed
    if confidence < MIN_CONFIDENCE:
        return {
            "primary": top_genre,
            "secondary": secondary,
            "scores": scores,
            "confidence": confidence,
            "method": "L2_keywords_low_confidence",
        }

    return {
        "primary": top_genre,
        "secondary": secondary,
        "scores": scores,
        "confidence": min(confidence, 1.0),
        "method": "L2_keywords"
    }


def passes_basic_filter(filepath: Path) -> tuple:
    """Basic quality filter (入库门槛, NOT final quality judgment).
    Reads thresholds from config.yaml analysis.book_filter.
    Returns (passed, reason, name_guess, known_genre_or_None, is_known_quality)."""
    filename = filepath.stem
    cfg = _load_filter_config()

    # 0. Size check (fast, no I/O for big files)
    size_kb = filepath.stat().st_size // 1024
    min_size = cfg.get("min_size_kb", 200)

    # 1. Check against known quality list (author-confirmed 精品)
    quality_list = cfg.get("known_quality_list", [])
    known_genre_map = cfg.get("known_genre_map", {})
    for qname in quality_list:
        if qname in filename:
            override_genre = known_genre_map.get(qname)
            return True, f"已知精品: {qname}", qname, override_genre, True
    # Also check file content for quality name
    text_head = filepath.read_text(encoding='utf-8', errors='replace')[:10000]
    for qname in quality_list:
        if qname in text_head[:500]:
            override_genre = known_genre_map.get(qname)
            return True, f"已知精品: {qname}", qname, override_genre, True

    # 2. Size: too small
    if size_kb < min_size:
        return False, f"文件太小 ({size_kb}KB < {min_size}KB)", filename, None, False

    # 3. Chapter structure — adaptive: big file = skip check
    min_ch = cfg.get("min_chapters", 5)
    if size_kb > 5000:  # >5MB: large file, skip chapter count
        chapter_count = min_ch  # pretend it passed
    else:
        chapter_count = len(re.findall(r'第[零一二三四五六七八九十百千0-9]+[章节回]|Chapter\s*\d+', text_head, re.IGNORECASE))
    if chapter_count < min_ch:
        return False, f"章节不足 (仅{chapter_count}章, 需≥{min_ch})", filename, None, False

    # 4. Content density (纯文字比例)
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text_head))
    total_chars = len(text_head.replace('\n', '').replace(' ', ''))
    density = chinese_chars / max(total_chars, 1)
    min_density = cfg.get("min_chinese_density", 0.40)
    if density < min_density:
        return False, f"文字密度过低 ({density:.1%} < {min_density:.0%})", filename, None, False

    # 4a. (Zero-cost) Dialogue ratio check — zero dialogue = likely outline/notes, not novel
    dialogue_lines = len(re.findall(
        r'["\u201c\u300c\u300e][^\n]*?["\u201d\u300d\u300f]'  # Chinese quotes
        r'|[:"\u201c\u300c]',  # Colon-quote dialogue markers
        text_head))
    total_lines = max(text_head.count('\n'), 1)
    dialogue_ratio = dialogue_lines / total_lines
    zero_dialogue_warn = False
    if dialogue_ratio < 0.01 and chapter_count >= 5:
        zero_dialogue_warn = True
        print(f"  [WARN] {filename[:30]}: 对话率极低 ({dialogue_lines}行/{total_lines}行={dialogue_ratio:.1%}) — 可能非小说文体")

    # 4b. (Zero-cost) Chinese name density — <2 unique name candidates = single-char monologue
    name_candidates = set(re.findall(r'[\u4e00-\u9fff]{2,3}', text_head[:5000]))
    # Filter noise: remove common non-name bigrams (的,是,了,在,等)
    noise = {'不是','没有','已经','可以','自己','他们','我们','什么','一个',
             '这个','那个','就是','还是','因为','所以','不过','但是','如果',
             '虽然','而且','然后','之后','之前','以后','现在','怎么','这么',
             '知道','觉得','看到','听到','想到','出来','起来','下来','上来',
             '不能','不会','不要','不敢','一点','一下','一样','有些','很多'}
    names = name_candidates - noise
    if len(names) < 2 and chapter_count >= 3:
        print(f"  [WARN] {filename[:30]}: 角色名候选过少 ({len(names)}个) — 可能单角色流水账")

    # 4c. (Zero-cost) Word/chapter ratio — extreme outliers = non-novel format
    # Skip for big files (>5MB) since chapter count is unreliable there
    if size_kb <= 5000:
        total_text = filepath.read_text(encoding='utf-8', errors='replace')
        total_cjk = len(re.findall(r'[\u4e00-\u9fff]', total_text[:500000]))
        chars_per_ch = total_cjk / max(chapter_count, 1)
        if chars_per_ch > 50000 or (chars_per_ch < 200 and chapter_count >= 10):
            return False, f"字数/章比异常 ({chars_per_ch:.0f}字/章) — 可能非小说文体", filename, None, False

    # 5. Passes all heuristics but not on known list → staging (待质量关卡验证)
    reason_str = f"通过基础过滤 ({size_kb}KB/{chapter_count}章, 对话率{dialogue_ratio:.0%})"
    return True, reason_str, filename, None, False


def process_book(filepath: Path) -> dict:
    """Process a single book through the pipeline."""
    name = filepath.stem
    result = {"file": name, "path": str(filepath)}

    # Step 1: Encoding
    enc = detect_encoding(filepath)
    result["encoding"] = enc
    if enc == "UNKNOWN":
        result["status"] = "encoding_fail"
        return result
    if enc in ("GBK", "UTF-16-LE", "UTF-16-BE"):
        if convert_to_utf8(filepath):
            result["encoding"] = f"{enc}→UTF-8"

    # Step 2-3: Genre (auto-detect, overridden if known quality)
    # P0: unify routing to genre_multi primary (eliminate split-brain)
    genre_multi = detect_genre_multi(filepath)
    passed, reason, name_guess, known_genre, _is_known = passes_basic_filter(filepath)
    if known_genre:
        genre_multi["primary"] = known_genre
        genre_multi["method"] = "known_quality"
    genre = genre_multi["primary"]  # routing uses multi primary
    # P0: WARN when confidence is low (signal too dispersed, classification near random)
    if genre_multi.get("method") == "L2_keywords_low_confidence":
        print(f"  [WARN] {name[:30]}: 题材低置信度({genre_multi.get('confidence',0):.2f}) → 归类为'{genre}'可能不准, 建议人工复核")
    result["genre"] = genre
    result["genre_multi"] = genre_multi
    result["quality"] = "已知精品" if _is_known else ("通过基础过滤" if passed else "未通过")
    result["reason"] = reason

    # Step 4: Route — genre subdirectory (correct classification = no cross-contamination)
    if passed:
        genre_dir = NOVELS_RAW / genre if genre != "未知" else NOVELS_RAW
        genre_dir.mkdir(parents=True, exist_ok=True)
        dest = genre_dir / filepath.name
        shutil.move(str(filepath), str(dest))
        result["routed_to"] = f"data/raw/novels/{genre}" if genre != "未知" else "data/raw/novels"
    else:
        BOOKS_REVIEW.mkdir(parents=True, exist_ok=True)
        dest = BOOKS_REVIEW / filepath.name
        shutil.move(str(filepath), str(dest))
        result["routed_to"] = "books/review"
        result["path"] = str(dest)

    result["status"] = "processed"
    return result


def main():
    txt_files = sorted(BOOKS_IN.glob("*.txt"))
    if not txt_files:
        print("books_in/: 无书籍待处理。")
        return

    results = []
    good, review = [], []

    for i, f in enumerate(txt_files):
        print(f"\n[{i+1}/{len(txt_files)}] {f.name[:50]}")
        r = process_book(f)
        results.append(r)

        status = r["status"]
        quality = r.get("quality", "?")
        genre = r.get("genre", "?")
        reason = r.get("reason", "")

        if status == "processed":
            multi = r.get("genre_multi", {})
            sec = multi.get("secondary", [])
            genre_tag = f"{genre} +{','.join(sec)}" if sec else genre
            if quality == "已知精品":
                print(f"  [OK] {r['encoding']} | {genre_tag} | 精品 → novels/")
                print(f"       理由: {reason}")
                good.append(r)
            elif quality == "通过基础过滤":
                print(f"  [OK] {r['encoding']} | {genre_tag} | 通过 → novels/")
                print(f"       理由: {reason}")
                good.append(r)
            else:
                print(f"  [?] {r['encoding']} | {genre} | 未通过 → books/review/")
                print(f"       理由: {reason}")
                review.append(r)
        else:
            print(f"  [FAIL] {status}")

    # Summary
    print(f"\n{'='*50}")
    print(f"[DONE] 入库: {len(good)} | 退回审查: {len(review)}")
    for g in good:
        print(f"  novels/{g.get('genre','?')}: {g['file'][:40]}")
    for rv in review:
        print(f"  review/: {rv['file'][:40]} ({rv.get('reason','')[:40]})")

    if good:
        print(f"\n入库书籍可运行分析管线:")
        print(f"  python analysis/analyze_all.py")

    # Register in novel_index.json
    # (existing index update logic can be added here if needed)


if __name__ == "__main__":
    main()
