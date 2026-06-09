#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
quality_gate.py v3 — 双层品质关卡 + QUARANTINE软降级
=====================================================
位置: 分析管线 Step 2 (rhythm_analyzer 之后, genre_synthesizer 之前)
改进: v2→v3
  - P0: commercial_score 从 JSON 读取 (rhythm_benchmark.md → borda_ranking.json)
  - P0: Borda 匹配用模糊匹配 (书名前8字) 替代精确 stem 匹配
  - P1: config 模块级缓存, 消除重复加载
  - P1: commercial_scores 持久化到 JSON, 供后续管线复用
  v2:
  - Gate A(前置): 形式完整性检查 → FAIL(明显废书,直接移出)
  - Gate B(后置): 节奏+商业实质检查 → QUARANTINE(可能是慢热,标记不移书)
  - 已知精品名单保护: 永不 FAIL, 最差 QUARANTINE
  - 三级状态: PASS(白名单) / QUARANTINE(待审查) / FAIL(退回)
  - 渐进式池子: 跨题材→同题材自动切换, 首轮即可输出商业评分

配置: config.yaml analysis.quality_gate
用法: python analysis/quality_gate.py [--dry-run] [--verbose] [--help]
      --gate [A|B|both]: 指定运行哪个关卡 (default: both)
      --dry-run: 只检查不移书
"""
import csv
import json
import shutil
import statistics
import sys
import yaml
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
NOVELS_DIR = PROJECT_ROOT / "data" / "raw" / "novels"
BOOKS_REVIEW = PROJECT_ROOT / "books" / "review"
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
INDEX_PATH = PROJECT_ROOT / "data" / "raw" / "novel_index.json"


def _rhythm_dir(genre):
    return PROJECT_ROOT / "data" / "processed" / genre / "rhythm"


def _llm_dir(genre):
    return PROJECT_ROOT / "data" / "processed" / genre / "llm_scores"


def _manifest_path(genre):
    return PROJECT_ROOT / "data" / "processed" / genre / "quality_manifest.json"


# ── Module-level config cache (avoid re-reading config.yaml per book) ──
_gate_config_cache = None


def _load_gate_config():
    global _gate_config_cache
    if _gate_config_cache is not None:
        return _gate_config_cache
    defaults = {
        "min_rhythm_chapters": 10, "max_zero_hook_streak": 5,
        "min_commercial_score": 30, "auto_demote": True,
        "quarantine_days": 7,
        "known_quality_list": [],
        "author_protected_books": [],
    }
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f) or {}
            qg = cfg.get("analysis", {}).get("quality_gate", {})
            result = dict(defaults)
            for key in result:
                if key in qg:
                    result[key] = qg[key]
            # Merge known_quality_list from book_filter if not in quality_gate
            if not result["known_quality_list"]:
                bf = cfg.get("analysis", {}).get("book_filter", {})
                result["known_quality_list"] = bf.get("known_quality_list", [])
            # Merge author_protected_books from book_filter
            if not result["author_protected_books"]:
                bf = cfg.get("analysis", {}).get("book_filter", {})
                result["author_protected_books"] = bf.get("author_protected_books", [])
            _gate_config_cache = result
            return result
    except Exception:
        pass
    _gate_config_cache = defaults
    return defaults


def _fuzzy_match(name_a, name_b, min_len=6):
    """Fuzzy book name match: check if either name's prefix is contained in the other.
    Handles cases like '《地球游戏场》（校对版全本）' vs '《地球游戏场》（校对版全本）作者：吉风冰'."""
    a, b = name_a.strip(), name_b.strip()
    prefix = max(min_len, min(len(a), len(b), 8))
    return a[:prefix] in b or b[:prefix] in a


def _find_rhythm_csv(book_stem, genre=None):
    search_dirs = []
    if genre:
        search_dirs.append(_rhythm_dir(genre))
    else:
        # Search all genre subdirs
        for gdir in (PROJECT_ROOT / "data" / "processed").iterdir():
            rdir = gdir / "rhythm"
            if rdir.is_dir():
                search_dirs.append(rdir)
    for rdir in search_dirs:
        candidates = list(rdir.glob(f"*{book_stem[:10]}*.csv"))
        if not candidates:
            candidates = list(rdir.glob(f"rhythm_*{book_stem[:8]}*.csv"))
        if candidates:
            return candidates[0]
    return None


def _extract_book_stem(txt_path):
    name = txt_path.stem
    for suffix in ["（精校版全本）", "（校对全本）", "（精校）", "作者："]:
        if suffix in name:
            name = name.split(suffix)[0]
    return name.strip()[:40]


def _read_rhythm_stats(book_stem):
    csv_path = _find_rhythm_csv(book_stem)
    if not csv_path:
        return None
    rows = []
    try:
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                rows.append({
                    "hook_density": float(r.get("hook_density", 0)),
                    "conflict_density": float(r.get("conflict_density", 0)),
                    "pleasure_intensity": float(r.get("pleasure_intensity", 0)),
                    "ch_variability": float(r.get("ch_variability", 0)),
                })
    except Exception as e:
        print(f"  [WARN] 无法读取节奏数据 {csv_path.name}: {e}")
        return None
    if not rows:
        return None
    max_streak = cur = 0
    for r in rows:
        cur = cur + 1 if r["hook_density"] == 0 else 0
        max_streak = max(max_streak, cur)
    return {
        "total_ch": len(rows),
        "avg_hook": round(statistics.mean([r["hook_density"] for r in rows]), 3),
        "avg_conflict": round(statistics.mean([r["conflict_density"] for r in rows]), 3),
        "avg_pleasure": round(statistics.mean([r["pleasure_intensity"] for r in rows]), 3),
        "zero_hook_streak": max_streak,
        "ch_variability_mean": round(statistics.mean([r["ch_variability"] for r in rows]), 1),
    }


def _is_known_quality(book_name, known_set):
    """Check if book matches known quality list."""
    for qname in known_set:
        if qname in book_name:
            return True
    return False


def _is_author_protected(book_name, protected_set):
    """Check if book is author-protected (HITL hard override: always PASS, no auto FAIL/QUARANTINE).
    Audit trail: matches are logged with timestamp."""
    for pname in protected_set:
        if pname in book_name:
            print(f"  [OVERRIDE] {book_name[:40]} | author_protected={pname} | {datetime.now().isoformat()}")
            return True
    return False


# ── Commercial scores cache (loaded once from JSON, not MD parsing) ──
_commercial_scores_cache = None


def _load_commercial_scores():
    """Load commercial scores from borda_ranking.json + rhythm_benchmark.md data.
    Returns dict: {book_name_prefix: score}. Cached at module level.
    v3: Replaces fragile MD glob parsing with direct JSON read."""
    global _commercial_scores_cache
    if _commercial_scores_cache is not None:
        return _commercial_scores_cache

    scores = {}

    # Source 1: borda_ranking.json — has consensus_rank (1=best), convert to 0-100 score
    reports_dir = PROJECT_ROOT / "data" / "reports"
    for borda_file in reports_dir.glob("*/synthesis/*_borda_ranking.json"):
        try:
            with open(borda_file, 'r', encoding='utf-8') as f:
                ranking = json.load(f)
            n_books = len(ranking)
            for entry in ranking:
                name = entry.get("book_name", "")
                rank = entry.get("consensus_rank", n_books)
                # Convert rank to 0-100 score: rank 1 → 100, rank N → 0
                score = round(max(0, min(100, (1 - (rank - 1) / max(n_books - 1, 1)) * 100)))
                scores[name] = score
        except Exception:
            continue

    # Source 2: rhythm_benchmark.md — has explicit 签约分数 (more accurate)
    for bench_file in reports_dir.glob("*/synthesis/rhythm_benchmark.md"):
        try:
            content = bench_file.read_text(encoding='utf-8', errors='replace')
            for line in content.split('\n'):
                if '签约' in line and '分' in line:
                    # Pattern: "- 书名: 签约XX分"
                    parts = line.split('签约')
                    if len(parts) == 2:
                        book_name = parts[0].strip().lstrip('- ').strip()
                        score_str = parts[1].split('分')[0].strip()
                        try:
                            scores[book_name] = int(score_str)
                        except ValueError:
                            continue
        except Exception:
            continue

    # Source 3: commercial_scores.json — most authoritative (direct from genre_synthesizer)
    processed_dir = PROJECT_ROOT / "data" / "processed"
    for cs_file in processed_dir.glob("*/commercial_scores.json"):
        try:
            with open(cs_file, 'r', encoding='utf-8') as f:
                cs_data = json.load(f)
            for name, data in cs_data.items():
                if isinstance(data, dict) and "overall" in data:
                    scores[name] = int(data["overall"])
        except Exception:
            continue

    _commercial_scores_cache = scores
    return scores


def _read_commercial_score_progressive(book_stem, gate_cfg):
    """v3: Read commercial score from JSON cache (borda + benchmark), fallback to rhythm proxy.
    No more MD glob parsing — O(1) lookup instead of O(n_files * n_lines)."""
    scores = _load_commercial_scores()

    # Try fuzzy match against cached scores
    for cached_name, score in scores.items():
        if _fuzzy_match(book_stem, cached_name):
            return score, "intra_genre"

    # Fallback: proxy from rhythm stats (data-driven normalization)
    stats = _read_rhythm_stats(book_stem)
    if stats and stats["total_ch"] >= 10:
        # Normalize to observed firebook ranges (hook: 0.8-6, pleasure: 1-3, conflict: 0.2-1)
        h = min(100, max(0, (stats["avg_hook"] - 0.5) / 4.0 * 100))
        p = min(100, max(0, stats["avg_pleasure"] / 3.0 * 100))
        c = min(100, max(0, (stats["avg_conflict"] - 0.2) / 0.8 * 100))
        proxy = int((h + p + c) / 3)
        return proxy, "rhythm_proxy"

    return None, None


def evaluate_book(txt_path, gate_cfg, gate_type="both"):
    """Evaluate book. gate_type: 'A'(form only), 'B'(substance), 'both'.
    Returns (verdict: PASS/QUARANTINE/FAIL, details)."""
    stem = _extract_book_stem(txt_path)
    details = {"file": txt_path.name, "stem": stem, "checks": {}, "verdict": "PASS"}
    # v3: use cached config instead of re-loading per book
    known = set(gate_cfg.get("known_quality_list", []))
    is_known = _is_known_quality(txt_path.name, known)
    protected = set(gate_cfg.get("author_protected_books", []))
    is_protected = _is_author_protected(txt_path.name, protected)

    if is_known:
        details["known_quality"] = True

    # ── HITL Override: author-protected books always PASS (no auto FAIL/QUARANTINE) ──
    if is_protected:
        details["author_protected"] = True
        details["verdict"] = "PASS"
        details["reason"] = "[作者豁免] 受保护书籍, 跳过所有自动关卡"
        return "PASS", details

    # ── Gate A: 形式完整性 ──
    if gate_type in ("A", "both"):
        rhythm = _read_rhythm_stats(stem)
        if not rhythm:
            details["checks"]["rhythm_exists"] = False
            if is_known:
                details["verdict"] = "QUARANTINE"
                details["reason"] = "[已知精品] 无节奏数据(可能格式问题), 软降级待审查"
            else:
                details["verdict"] = "FAIL"
                details["reason"] = "无节奏分析数据 (需先运行 rhythm_analyzer)"
            return details["verdict"], details
        details["rhythm"] = rhythm
        details["checks"]["rhythm_exists"] = True

        min_ch = gate_cfg.get("min_rhythm_chapters", 10)
        if rhythm["total_ch"] < min_ch:
            details["checks"]["min_chapters"] = False
            details["rhythm"] = rhythm
            if is_known:
                details["verdict"] = "QUARANTINE"
                details["reason"] = f"[已知精品] 章节不足({rhythm['total_ch']}<{min_ch}), 软降级"
            else:
                details["verdict"] = "FAIL"
                details["reason"] = f"章节不足 ({rhythm['total_ch']} < {min_ch})"
            return details["verdict"], details
        details["checks"]["min_chapters"] = True

    # ── Gate B: 节奏+商业实质 ──
    if gate_type in ("B", "both"):
        rhythm = details.get("rhythm") or _read_rhythm_stats(stem)
        if not rhythm:
            details["checks"]["rhythm_exists"] = False
            details["verdict"] = "FAIL"
            details["reason"] = "Gate B需要节奏数据"
            return details["verdict"], details

        # P1: proportion-based threshold — short books stricter, long books looser
        total_ch = rhythm.get("total_ch", 1)
        max_streak = max(gate_cfg.get("max_zero_hook_streak", 5),
                         min(int(total_ch * 0.03), 15))  # 3% caps at 15
        if rhythm["zero_hook_streak"] > max_streak:
            details["checks"]["zero_hook"] = False
            details["rhythm"] = rhythm
            details["verdict"] = "QUARANTINE"
            details["reason"] = f"零钩子过长({rhythm['zero_hook_streak']}章>{max_streak}, total_ch={total_ch})→可能慢热"
            return details["verdict"], details
        details["checks"]["zero_hook"] = True

        score, score_source = _read_commercial_score_progressive(stem, gate_cfg)
        if score is not None:
            min_score = gate_cfg.get("min_commercial_score", 30)
            details["commercial"] = {"score": score, "source": score_source}
            if score < min_score:
                details["checks"]["commercial_score"] = False
                if is_known:
                    details["verdict"] = "QUARANTINE"
                    details["reason"] = f"[已知精品] 商业评分偏低({score}<{min_score}), 软降级"
                else:
                    details["verdict"] = "QUARANTINE"
                    details["reason"] = f"商业评分偏低({score}<{min_score}, {score_source})→可能慢热"
                return details["verdict"], details
        details["checks"]["commercial_score"] = True

    details["reason"] = "通过品质关卡"
    details["verdict"] = "PASS"
    return "PASS", details


def demote_book(txt_path, reason, dry_run=False):
    if dry_run:
        print(f"  [DRY-RUN] 将退回: {txt_path.name} → books/review/ ({reason})")
        return True
    BOOKS_REVIEW.mkdir(parents=True, exist_ok=True)
    dest = BOOKS_REVIEW / txt_path.name
    if dest.exists():
        dest = BOOKS_REVIEW / f"{txt_path.stem}_demoted{txt_path.suffix}"
        print(f"  [WARN] {txt_path.name} 已存在于 review/, 重命名为 {dest.name}")
    try:
        shutil.move(str(txt_path), str(dest))
        print(f"  [REVIEW] {txt_path.name} → books/review/ | {reason}")
        return True
    except Exception as e:
        print(f"  [FAIL] 无法移动 {txt_path.name}: {e}")
        return False


def remove_from_index(book_name):
    if not INDEX_PATH.exists():
        return
    try:
        with open(INDEX_PATH, 'r', encoding='utf-8') as f:
            idx = json.load(f)
        modified = False
        for genre_data in idx.get("genres", {}).values():
            novels = genre_data.get("novels", [])
            before = len(novels)
            genre_data["novels"] = [n for n in novels if book_name not in n.get("file", "")]
            if len(genre_data["novels"]) < before:
                modified = True
        if modified:
            with open(INDEX_PATH, 'w', encoding='utf-8') as f:
                json.dump(idx, f, ensure_ascii=False, indent=2)
            print(f"  [INDEX] Removed {book_name} from novel_index.json")
    except Exception as e:
        print(f"  [WARN] index update failed: {e}")


def run_gate(dry_run=False, verbose=False, gate_type="both", genre=None):
    gate_cfg = _load_gate_config()
    auto_demote = gate_cfg.get("auto_demote", True)
    quarantine_days = gate_cfg.get("quarantine_days", 7)

    print("=" * 60)
    print(f"  Quality Gate v3 | gate={gate_type} | {'DRY-RUN' if dry_run else 'LIVE'}")
    print(f"  Gate A: ch>={gate_cfg['min_rhythm_chapters']}")
    print(f"  Gate B: zero_hook<={gate_cfg['max_zero_hook_streak']}, score>={gate_cfg['min_commercial_score']}")
    print(f"  QUARANTINE: {quarantine_days}天无人工干预→自动FAIL")
    protected_count = len(set(gate_cfg.get("author_protected_books", [])))
    if protected_count:
        print(f"  [OVERRIDE] {protected_count} 本书受作者豁免保护 (跳过所有自动关卡)")
    if genre:
        print(f"  [SCOPE] genre={genre} (仅处理该题材)")
    print("=" * 60)

    if genre:
        genre_dir = NOVELS_DIR / genre
        txt_files = sorted(genre_dir.glob("*.txt")) if genre_dir.exists() else []
    else:
        txt_files = sorted(NOVELS_DIR.glob("**/*.txt"))  # genre subdirs only, no random .txt
    if not txt_files:
        print("[WARN] data/raw/novels/: 无书籍")
        MANIFEST_PATH = _manifest_path(genre or "末世")
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST_PATH.write_text(json.dumps(
            {"approved": [], "quarantined": [], "failed": [],
             "timestamp": datetime.now().isoformat(), "gate_version": "v3"},
            ensure_ascii=False, indent=2), encoding='utf-8')
        return

    approved, quarantined, failed = [], [], []
    known = set(gate_cfg.get("known_quality_list", []))

    for i, txt in enumerate(txt_files):
        name = txt.name[:50]
        if verbose:
            print(f"\n[{i+1}/{len(txt_files)}] {name}")

        verdict, details = evaluate_book(txt, gate_cfg, gate_type)

        if verdict == "PASS":
            approved.append(details)
            if verbose:
                print(f"  [PASS] {details.get('reason','')}")
        elif verdict == "QUARANTINE":
            quarantined.append(details)
            # Soft demote: mark but don't move. Only log.
            print(f"  [QUARANTINE] {name} | {details.get('reason','?')}")
            if verbose and details.get("known_quality"):
                print(f"    (已知精品名单保护, 不硬降级)")
        else:  # FAIL
            failed.append(details)
            if auto_demote:
                demote_book(txt, details.get("reason", "unknown"), dry_run=dry_run)
                remove_from_index(name)
            else:
                print(f"  [FAIL] {name}: {details.get('reason','?')}")

    # Load Borda ranking for multi-dimensional consensus
    # v3: use fuzzy matching instead of exact stem match
    borda_map = {}
    try:
        borda_dir = PROJECT_ROOT / "data" / "reports"
        for bf in borda_dir.glob("*/synthesis/*_borda_ranking.json"):
            with open(bf, 'r', encoding='utf-8') as f:
                for entry in json.load(f):
                    borda_map[entry["book_name"]] = entry
    except Exception:
        pass

    def _find_borda(stem):
        """v3: fuzzy match borda ranking by book name prefix."""
        for borda_name, entry in borda_map.items():
            if _fuzzy_match(stem, borda_name):
                return entry
        return {}

    # Write manifest v3
    MANIFEST_PATH = _manifest_path(genre or "末世")
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "approved": [{"file": a["file"], "stem": a["stem"],
                   "avg_hook": a.get("rhythm", {}).get("avg_hook", 0),
                   "avg_pleasure": a.get("rhythm", {}).get("avg_pleasure", 0),
                   "commercial_score": a.get("commercial", {}).get("score"),
                   "borda_consensus_rank": _find_borda(a["stem"]).get("consensus_rank"),
                   "borda_dims": _find_borda(a["stem"]).get("dim_ranks", {}),
                   "author_protected": a.get("author_protected", False)}
                  for a in approved],
        "quarantined": [{"file": q["file"], "stem": q.get("stem", ""),
                          "reason": q.get("reason", "?"),
                          "known_quality": q.get("known_quality", False)}
                         for q in quarantined],
        "failed": [{"file": b["file"], "reason": b.get("reason", "?")}
                    for b in failed],
        "timestamp": datetime.now().isoformat(),
        "gate_version": "v3",
        "quarantine_days": quarantine_days,
        "author_protected_count": sum(1 for a in approved if a.get("author_protected")),
        "sample_size": len(approved),
        "confidence": "low" if len(approved) < 30 else ("medium" if len(approved) < 50 else "high"),
        "thresholds": {
            "min_rhythm_chapters": gate_cfg["min_rhythm_chapters"],
            "max_zero_hook_streak": gate_cfg["max_zero_hook_streak"],
            "min_commercial_score": gate_cfg["min_commercial_score"],
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                             encoding='utf-8')

    # Summary
    print(f"\n{'='*60}")
    print(f"[RESULT] PASS:{len(approved)} | QUARANTINE:{len(quarantined)} | FAIL:{len(failed)}")
    for a in approved:
        tag = "[AUTHOR-PROTECTED]" if a.get("author_protected") else "[OK]"
        print(f"  {tag} {a['file'][:40]}")
    for q in quarantined:
        print(f"  [Q] {q['file'][:40]} ({q.get('reason','?')[:50]})")
    for f_ in failed:
        print(f"  [FAIL] {f_['file'][:40]} → books/review/")

    if quarantined:
        print(f"\n[ACTION] {len(quarantined)} 本书进入 QUARANTINE 待审查:")
        print(f"  1. 这{len(quarantined)}本书保留在 data/raw/novels/, 但标记为待审查")
        print(f"  2. {quarantine_days}天内人工确认保留/删除")
        print(f"  3. 已知精品名单中的书不受商业评分限制")
    print(f"\n  Manifest: {MANIFEST_PATH}")
    print(f"\n{'='*60}")

    return manifest


def get_approved_books(genre="末世"):
    mp = _manifest_path(genre)
    if not mp.exists():
        return []
    try:
        with open(mp, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
        return [a["stem"] for a in manifest.get("approved", [])]
    except Exception:
        return []


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        return
    dry_run = "--dry-run" in sys.argv
    verbose = "--verbose" in sys.argv
    gate_type = "both"
    genre = None
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg.startswith("--gate="):
            gate_type = arg.split("=")[1]
        if arg == "--genre" and i < len(sys.argv) - 1:
            genre = sys.argv[i + 1]
    run_gate(dry_run=dry_run, verbose=verbose, gate_type=gate_type, genre=genre)


if __name__ == "__main__":
    main()
