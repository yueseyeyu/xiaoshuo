#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
rhythm_auditor.py v1 — 节奏拆书数据质量评审
=============================================
在 Rhythm Analysis 之后运行，对每本书的 rhythm CSV 做异常检测。
检查项:
  1. 零值检测: hook_density=0 或 conflict_density=0 → 正则可能失效
  2. 极端值检测: 任一指标偏离 genre 均值 >3 sigma
  3. 钩子分布异常: "none" 类型占比 >95% → 钩子正则覆盖不足
  4. 爽点覆盖异常: pleasure_density <0.05 → 几乎没有爽点
  5. 章节/字数一致性: 平均章节字数 <500 或 >10000 → 切分可能出错
  6. 可读性异常: readability 极端值 (>2.0 或 <-1.0)

输出: data/processed/{genre}/rhythm_audit.json
用法: python analysis/rhythm_auditor.py [--genre 末世]
"""
import csv
import json
import statistics
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _rhythm_dir(genre):
    return PROJECT_ROOT / "data" / "processed" / genre / "rhythm"


def _load_rhythm_csv(csv_path):
    """Load rhythm CSV rows as list of dicts."""
    rows = []
    try:
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                rows.append(r)
    except Exception:
        return None
    return rows


def _safe_float(val, default=0.0):
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _safe_int(val, default=0):
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def audit_book(name, rows, genre_stats):
    """Audit a single book's rhythm data. Returns (status, checks, issues)."""
    checks = {}
    issues = []
    n = len(rows)
    if not rows or n < 5:
        return "FAIL", checks, ["章节数不足5章，数据不可用"]

    # ── Metric extraction ──
    hook_densities = [_safe_float(r.get("hook_density", 0)) for r in rows]
    conflict_densities = [_safe_float(r.get("conflict_density", 0)) for r in rows]
    pleasure_intensities = [_safe_float(r.get("pleasure_intensity", 0)) for r in rows]
    readability_scores = [_safe_float(r.get("readability", 0)) for r in rows]
    dialogue_ratios = [_safe_float(r.get("dialogue_ratio", 0)) for r in rows]
    word_counts = [_safe_int(r.get("wc", 0)) for r in rows]
    hook_types = [r.get("hook_type", "none") for r in rows]
    pleasure_types = [r.get("pleasure_type", "none") for r in rows]

    avg_hook = statistics.mean(hook_densities) if hook_densities else 0
    avg_conflict = statistics.mean(conflict_densities) if conflict_densities else 0
    avg_intensity = statistics.mean(pleasure_intensities) if pleasure_intensities else 0
    avg_readability = statistics.mean(readability_scores) if readability_scores else 0
    avg_dialogue = statistics.mean(dialogue_ratios) if dialogue_ratios else 0
    avg_wc = statistics.mean(word_counts) if word_counts else 0

    p_density = sum(1 for p in pleasure_types if p != "none") / n
    none_hook_pct = sum(1 for h in hook_types if h == "none") / n

    # ── Check 1: Zero value detection ──
    zero_hook = avg_hook < 0.01
    zero_conflict = avg_conflict < 0.01
    checks["zero_values"] = {
        "avg_hook": round(avg_hook, 4),
        "avg_conflict": round(avg_conflict, 4),
        "pass": not (zero_hook or zero_conflict),
    }
    if zero_hook:
        issues.append("hook_density 均值接近0，钩子正则可能失效")
    if zero_conflict:
        issues.append("conflict_density 均值接近0，冲突正则可能失效")

    # ── Check 2: Extreme value detection (>3 sigma from genre mean) ──
    extreme_dims = []
    for dim_name, val, genre_key in [
        ("hook_density", avg_hook, "hook_density"),
        ("conflict_density", avg_conflict, "conflict_density"),
        ("pleasure_intensity", avg_intensity, "pleasure_intensity"),
        ("readability", avg_readability, "readability"),
    ]:
        g_mean = genre_stats.get(genre_key, {}).get("mean", 0)
        g_std = genre_stats.get(genre_key, {}).get("std", 1)
        if g_std > 0 and abs(val - g_mean) > 3 * g_std:
            extreme_dims.append(f"{dim_name}={val:.3f} (genre μ={g_mean:.3f} σ={g_std:.3f})")
    checks["extreme_values"] = {"pass": len(extreme_dims) == 0, "outliers": extreme_dims}
    if extreme_dims:
        issues.append(f"极端值: {'; '.join(extreme_dims)}")

    # ── Check 3: Hook distribution anomaly ──
    checks["hook_distribution"] = {
        "none_pct": round(none_hook_pct, 3),
        "pass": none_hook_pct <= 0.95,
    }
    if none_hook_pct > 0.95:
        issues.append(f"钩子'none'占比{none_hook_pct:.0%}>95%，钩子正则覆盖严重不足")

    # ── Check 4: Pleasure coverage ──
    checks["pleasure_coverage"] = {
        "density": round(p_density, 3),
        "pass": p_density >= 0.05,
    }
    if p_density < 0.05:
        issues.append(f"爽点覆盖率{p_density:.1%}<5%，几乎没有爽点被检测到")

    # ── Check 5: Chapter/word count consistency ──
    checks["chapter_consistency"] = {
        "avg_wc": round(avg_wc, 0),
        "pass": 500 <= avg_wc <= 10000,
    }
    if avg_wc < 500:
        issues.append(f"平均章节字数{avg_wc:.0f}<500，章节切分可能过碎")
    elif avg_wc > 10000:
        issues.append(f"平均章节字数{avg_wc:.0f}>10000，章节切分可能合并了多章")

    # ── Check 6: Readability extremes ──
    checks["readability"] = {
        "avg": round(avg_readability, 4),
        "pass": -1.0 <= avg_readability <= 2.0,
    }
    if avg_readability > 2.0:
        issues.append(f"可读性{avg_readability:.3f}>2.0，异常偏高")
    elif avg_readability < -1.0:
        issues.append(f"可读性{avg_readability:.3f}<-1.0，异常偏低")

    # ── Overall status ──
    fail_count = sum(1 for c in checks.values() if not c.get("pass", True))
    if fail_count >= 3:
        status = "FAIL"
    elif fail_count >= 1:
        status = "WARN"
    else:
        status = "PASS"

    return status, checks, issues


def compute_genre_stats(all_books_data):
    """Compute per-dimension mean/std across all books for outlier detection."""
    dims = {}
    for dim_name in ["hook_density", "conflict_density", "pleasure_intensity", "readability"]:
        values = []
        for book_data in all_books_data:
            for row in book_data:
                values.append(_safe_float(row.get(dim_name, 0)))
        if values:
            dims[dim_name] = {
                "mean": round(statistics.mean(values), 4),
                "std": round(statistics.stdev(values), 4) if len(values) > 1 else 1.0,
            }
        else:
            dims[dim_name] = {"mean": 0, "std": 1}
    return dims


def run_audit(genre="末世"):
    """Main audit entry point."""
    rhythm_dir = _rhythm_dir(genre)
    if not rhythm_dir.exists():
        print(f"[FAIL] Rhythm dir not found: {rhythm_dir}")
        return None

    csv_files = sorted(rhythm_dir.glob("rhythm_*.csv"))
    if not csv_files:
        print(f"[FAIL] No rhythm CSVs in {rhythm_dir}")
        return None

    print(f"\n{'='*60}")
    print(f"  Rhythm Data Audit | genre={genre} | {len(csv_files)} books")
    print(f"{'='*60}")

    # Phase 1: Load all data for genre stats
    all_books_data = []
    for csv_path in csv_files:
        rows = _load_rhythm_csv(csv_path)
        if rows:
            all_books_data.append(rows)

    genre_stats = compute_genre_stats(all_books_data)

    # Phase 2: Audit each book
    results = []
    passed = warned = failed = 0

    for csv_path in csv_files:
        name = csv_path.stem.replace("rhythm_", "")
        rows = _load_rhythm_csv(csv_path)
        if not rows:
            results.append({"name": name, "status": "FAIL", "checks": {},
                            "issues": ["CSV读取失败"]})
            failed += 1
            continue

        status, checks, issues = audit_book(name, rows, genre_stats)
        results.append({
            "name": name[:50],
            "status": status,
            "checks": checks,
            "issues": issues,
        })
        if status == "PASS":
            passed += 1
        elif status == "WARN":
            warned += 1
            print(f"  [WARN] {name[:40]}: {'; '.join(issues)}")
        else:
            failed += 1
            print(f"  [FAIL] {name[:40]}: {'; '.join(issues)}")

    # Phase 3: Output report
    report = {
        "genre": genre,
        "total_books": len(csv_files),
        "passed": passed,
        "warnings": warned,
        "failed": failed,
        "genre_stats": genre_stats,
        "books": results,
    }

    out_path = PROJECT_ROOT / "data" / "processed" / genre / "rhythm_audit.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f"\n  [RESULT] PASS:{passed} | WARN:{warned} | FAIL:{failed}")
    print(f"  Report: {out_path}")
    return report


def main():
    genre = "末世"
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--genre" and i < len(sys.argv) - 1:
            genre = sys.argv[i + 1]
    run_audit(genre)


if __name__ == "__main__":
    main()
