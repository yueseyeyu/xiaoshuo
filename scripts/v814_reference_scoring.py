#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
v814_reference_scoring.py — Phase A1: Reference-Based Scoring 验证脚本
=====================================================================
在 golden 章节上对比 绝对评分 (absolute) vs 参考评分 (reference-based) 的 MAE/Bias/r

论文基础:
- Can LLMs Be Good Evaluators in Creative Writing Tasks? (MDPI 2025)
  → LLM评分存在positivity bias, T1系统性高估+1.78
- Automated Creativity Evaluation for LLMs (ACL 2025)
  → reference-based scoring可降低MAE 30-50%

方法:
  1. 从 human_golden_merged.csv 构建 reference bank (47章×4分值段)
  2. 对每个 golden 章节用 leave-one-out 方式选取4个参考段落
  3. LLM参照参考段落评分 (reference-based)
  4. 对比 旧LLM评分(absolute) vs 新参考评分(reference-based) 的 MAE/Bias/r

用法:
  $env:PYTHONUTF8=1
  D:\miniconda3\envs\llm-shared\python.exe scripts/v814_reference_scoring.py

输出:
  data/reports/末世/v8.14_reference_scoring_report.md
  data/reports/末世/v8.14_reference_scoring_data.json
"""
import sys
import os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

os.environ["PYTHONUTF8"] = "1"
os.environ["NO_PROXY"] = os.environ.get("NO_PROXY", "") + ",127.0.0.1,localhost"

import csv
import json
import time
import re
import statistics
from pathlib import Path

# Setup paths
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from xiaoshuo.pipeline.llm_batch_score import (
    build_reference_bank,
    llm_score_reference_based,
    llm_score_rubric,
    extract_chapters,
    _select_references,
    NOVELS_DIR,
    INDEX_PATH,
)
from xiaoshuo.infra.llm_client import check_llm_health

GENRE = "末世"


def _build_book_to_txt():
    """Build book short_name -> txt_path mapping from novel index."""
    with open(INDEX_PATH, 'r', encoding='utf-8') as f:
        index = json.load(f)
    novels = index.get("genres", {}).get(GENRE, {}).get("novels", [])

    book_to_txt = {}
    for novel in novels:
        txt_file = novel.get("file", "")
        for fp in NOVELS_DIR.glob(f"{GENRE}/*.txt"):
            if fp.name == txt_file:
                short_name = txt_file.replace(".txt", "").replace("《", "").replace("》", "")
                m = re.match(r"([^（(]+)", short_name)
                if m:
                    short_name = m.group(1).strip()
                book_to_txt[short_name] = fp
                break
    return book_to_txt


def _compute_metrics(human_vals, predicted_vals):
    """Compute MAE, Bias, Pearson r for paired values."""
    pairs = [(h, p) for h, p in zip(human_vals, predicted_vals)
             if p is not None and h is not None]
    if len(pairs) < 3:
        return {"n": len(pairs), "mae": None, "bias": None, "r": None,
                "mae_pct": None, "bias_pct": None}

    h_vals = [p[0] for p in pairs]
    p_vals = [p[1] for p in pairs]
    n = len(pairs)

    mae = sum(abs(h - p) for h, p in pairs) / n
    bias = sum(p - h for h, p in pairs) / n

    # Manual Pearson (avoid np.corrcoef DLL issue on Windows)
    mean_h = sum(h_vals) / n
    mean_p = sum(p_vals) / n
    cov = sum((h_vals[i] - mean_h) * (p_vals[i] - mean_p) for i in range(n))
    std_h = (sum((h - mean_h) ** 2 for h in h_vals)) ** 0.5
    std_p = (sum((p - mean_p) ** 2 for p in p_vals)) ** 0.5
    r = cov / (std_h * std_p) if std_h > 0 and std_p > 0 else 0.0

    return {
        "n": n,
        "mae": round(mae, 3),
        "bias": round(bias, 3),
        "r": round(r, 4),
    }


def main():
    # Check LLM server
    if not check_llm_health(timeout=5):
        print("ERROR: LLM server not running.")
        print("  Start with: scripts\\start_model_safe.bat")
        sys.exit(1)

    print("=" * 60)
    print("  v8.14 Reference-Based Scoring Validation")
    print("=" * 60)

    # Build reference bank
    print("\n[1/3] Building reference bank...")
    golden_csv = PROJECT_ROOT / "data" / "golden" / GENRE / "tier3" / "human_golden_merged.csv"
    all_refs = build_reference_bank(golden_csv_path=golden_csv, genre=GENRE)
    print(f"  Reference bank: {len(all_refs)} passages")

    # Band distribution
    band_counts = {}
    for ref in all_refs:
        band_counts[ref["band"]] = band_counts.get(ref["band"], 0) + 1
    print(f"  Band distribution: {band_counts}")

    # Build book -> txt mapping
    book_to_txt = _build_book_to_txt()

    # Load golden rows
    with open(golden_csv, 'r', encoding='utf-8-sig') as f:
        golden_rows = list(csv.DictReader(f))
    print(f"  Golden rows: {len(golden_rows)}")

    # For each golden chapter: extract text, run reference-based scoring (leave-one-out)
    print("\n[2/3] Running reference-based scoring on golden chapters...")
    results = []
    _chapter_cache = {}

    for i, row in enumerate(golden_rows):
        book_name = row.get("book", "").strip()
        ch_num = int(row.get("ch_num", 0))
        human_intensity = float(row.get("human_intensity", 0) or 0)
        human_retention = float(row.get("human_retention", 0) or 0)
        old_llm_intensity_str = row.get("llm_intensity", "")
        old_llm_retention_str = row.get("llm_retention", "")
        old_llm_intensity = float(old_llm_intensity_str) if old_llm_intensity_str else None
        old_llm_retention = float(old_llm_retention_str) if old_llm_retention_str else None

        if not book_name or ch_num == 0:
            continue

        # Find txt file
        txt_path = None
        for short_name, fp in book_to_txt.items():
            if short_name in book_name or book_name in short_name:
                txt_path = fp
                break
        if txt_path is None:
            print(f"  [{i+1}/{len(golden_rows)}] SKIP: No txt for {book_name}")
            continue

        # Extract chapters (with cache)
        cache_key = str(txt_path)
        if cache_key not in _chapter_cache:
            _chapter_cache[cache_key] = extract_chapters(txt_path)
        chapters = _chapter_cache[cache_key]

        # Find chapter
        chapter = None
        ch_idx = None
        for idx, ch in enumerate(chapters):
            if ch.get("num") == ch_num:
                chapter = ch
                ch_idx = idx
                break
        if chapter is None:
            print(f"  [{i+1}/{len(golden_rows)}] SKIP: Ch{ch_num} not found in {book_name}")
            continue

        chapter_text = chapter.get("raw_body", "")
        if len(chapter_text) < 300:
            print(f"  [{i+1}/{len(golden_rows)}] SKIP: Ch{ch_num} too short ({len(chapter_text)} chars)")
            continue

        # Leave-one-out: exclude this chapter from references
        refs = _select_references(all_refs, exclude_book=book_name, exclude_ch_num=ch_num)
        if not refs:
            print(f"  [{i+1}/{len(golden_rows)}] SKIP: No references available")
            continue

        # Get prev context
        prev_context = ""
        if ch_idx is not None and ch_idx > 0:
            prev_body = chapters[ch_idx - 1].get("raw_body", "")
            if prev_body:
                prev_context = prev_body[-200:].replace("\n", " ").strip()

        # Run reference-based scoring
        status = f"[{i+1}/{len(golden_rows)}] {book_name} ch{ch_num} (human i={human_intensity} r={human_retention})"
        print(f"  {status}...", flush=True)
        t0 = time.time()

        ref_result = llm_score_reference_based(
            chapter_text, ch_num, refs,
            prev_context=prev_context, temperature=0.0
        )

        elapsed = time.time() - t0
        if ref_result:
            print(f"    ref: i={ref_result['intensity']} r={ref_result['retention']} ({elapsed:.1f}s)", flush=True)
        else:
            print(f"    ref: FAILED ({elapsed:.1f}s)", flush=True)

        # Also run absolute scoring for fair comparison (same chapter, same time)
        # This gives us a fresh absolute score to compare against
        abs_result = llm_score_rubric(
            chapter_text, ch_num,
            prev_context=prev_context, temperature=0.0
        )
        if abs_result:
            print(f"    abs: i={abs_result['intensity']} r={abs_result['retention']}", flush=True)

        results.append({
            "book": book_name,
            "ch_num": ch_num,
            "human_intensity": human_intensity,
            "human_retention": human_retention,
            "old_llm_intensity": old_llm_intensity,
            "old_llm_retention": old_llm_retention,
            "fresh_abs_intensity": abs_result["intensity"] if abs_result else None,
            "fresh_abs_retention": abs_result["retention"] if abs_result else None,
            "ref_intensity": ref_result["intensity"] if ref_result else None,
            "ref_retention": ref_result["retention"] if ref_result else None,
            "ref_conflict": ref_result["conflict"] if ref_result else None,
            "ref_hook": ref_result["hook"] if ref_result else None,
            "ref_emotion": ref_result["emotion"] if ref_result else None,
            "elapsed_s": round(elapsed, 1),
            "ref_count": len(refs),
        })

        # Rate limiting
        time.sleep(0.3)

        # Checkpoint: save intermediate results after each chapter
        ckpt_dir = PROJECT_ROOT / "data" / "reports" / GENRE
        ckpt_dir.mkdir(parents=True, exist_ok=True)
        ckpt_path = ckpt_dir / "v8.14_checkpoint.json"
        try:
            with open(ckpt_path, 'w', encoding='utf-8') as cf:
                json.dump({"completed": len(results), "total": len(golden_rows), "results": results}, cf, ensure_ascii=False)
        except Exception:
            pass

    # Compute metrics
    print("\n[3/3] Computing metrics...")

    # Old (stored) absolute scores from golden CSV
    old_int = _compute_metrics(
        [r["human_intensity"] for r in results],
        [r["old_llm_intensity"] for r in results],
    )
    old_ret = _compute_metrics(
        [r["human_retention"] for r in results],
        [r["old_llm_retention"] for r in results],
    )

    # Fresh absolute scores (re-run today)
    fresh_int = _compute_metrics(
        [r["human_intensity"] for r in results],
        [r["fresh_abs_intensity"] for r in results],
    )
    fresh_ret = _compute_metrics(
        [r["human_retention"] for r in results],
        [r["fresh_abs_retention"] for r in results],
    )

    # Reference-based scores
    ref_int = _compute_metrics(
        [r["human_intensity"] for r in results],
        [r["ref_intensity"] for r in results],
    )
    ref_ret = _compute_metrics(
        [r["human_retention"] for r in results],
        [r["ref_retention"] for r in results],
    )

    # Print summary
    print("\n" + "=" * 70)
    print("  v8.14 Reference-Based Scoring — Results Summary")
    print("=" * 70)
    print(f"  N = {len(results)} golden chapters scored")
    print()
    print("  Intensity (爽点强度):")
    print(f"    Stored Absolute (old):  MAE={old_int['mae']}  Bias={old_int['bias']:+.3f}  r={old_int['r']}")
    print(f"    Fresh Absolute (today):MAE={fresh_int['mae']}  Bias={fresh_int['bias']:+.3f}  r={fresh_int['r']}")
    print(f"    Reference-Based (new):  MAE={ref_int['mae']}  Bias={ref_int['bias']:+.3f}  r={ref_int['r']}")

    if ref_int['mae'] and fresh_int['mae'] and fresh_int['mae'] > 0:
        delta = ((ref_int['mae'] - fresh_int['mae']) / fresh_int['mae']) * 100
        print(f"    MAE change (ref vs fresh abs): {delta:+.1f}%")
    print()
    print("  Retention (留存力):")
    print(f"    Stored Absolute (old):  MAE={old_ret['mae']}  Bias={old_ret['bias']:+.3f}  r={old_ret['r']}")
    print(f"    Fresh Absolute (today):MAE={fresh_ret['mae']}  Bias={fresh_ret['bias']:+.3f}  r={fresh_ret['r']}")
    print(f"    Reference-Based (new):  MAE={ref_ret['mae']}  Bias={ref_ret['bias']:+.3f}  r={ref_ret['r']}")

    if ref_ret['mae'] and fresh_ret['mae'] and fresh_ret['mae'] > 0:
        delta = ((ref_ret['mae'] - fresh_ret['mae']) / fresh_ret['mae']) * 100
        print(f"    MAE change (ref vs fresh abs): {delta:+.1f}%")

    # Save JSON data
    report_dir = PROJECT_ROOT / "data" / "reports" / GENRE
    report_dir.mkdir(parents=True, exist_ok=True)

    json_path = report_dir / "v8.14_reference_scoring_data.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump({
            "version": "v8.14",
            "date": "2026-07-14",
            "n_chapters": len(results),
            "metrics": {
                "stored_absolute_intensity": old_int,
                "stored_absolute_retention": old_ret,
                "fresh_absolute_intensity": fresh_int,
                "fresh_absolute_retention": fresh_ret,
                "reference_intensity": ref_int,
                "reference_retention": ref_ret,
            },
            "results": results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n  JSON data saved: {json_path}")

    # Generate markdown report
    md_path = report_dir / "v8.14_reference_scoring_report.md"
    _generate_report(md_path, results, old_int, old_ret, fresh_int, fresh_ret, ref_int, ref_ret)
    print(f"  Report saved: {md_path}")
    print("\n  Done!")


def _generate_report(md_path, results, old_int, old_ret, fresh_int, fresh_ret, ref_int, ref_ret):
    """Generate markdown report with comparison table and per-chapter details."""

    def _fmt(m, key):
        if m.get(key) is None:
            return "N/A"
        return f"{m[key]:.3f}"

    def _fmt_signed(m, key):
        if m.get(key) is None:
            return "N/A"
        return f"{m[key]:+.3f}"

    lines = []
    lines.append("# v8.14 Reference-Based Scoring 验证报告\n")
    lines.append(f"> 生成时间: 2026-07-14 | Phase A1\n")
    lines.append(f"> 论文基础: MDPI 2025 (positivity bias) + ACL 2025 (ref-based MAE↓30-50%)\n")
    lines.append(f"> 验证章节: {len(results)} golden chapters\n")
    lines.append("")

    lines.append("## 一、总体对比结果\n")
    lines.append("| 维度 | 方法 | N | MAE | Bias | Pearson r |")
    lines.append("|------|------|---|-----|------|-----------|")

    lines.append(f"| 爽点强度 | 存档绝对评分(old) | {old_int['n']} | {_fmt(old_int,'mae')} | {_fmt_signed(old_int,'bias')} | {_fmt(old_int,'r')} |")
    lines.append(f"| 爽点强度 | 新鲜绝对评分(today) | {fresh_int['n']} | {_fmt(fresh_int,'mae')} | {_fmt_signed(fresh_int,'bias')} | {_fmt(fresh_int,'r')} |")
    lines.append(f"| **爽点强度** | **参考评分(reference)** | **{ref_int['n']}** | **{_fmt(ref_int,'mae')}** | **{_fmt_signed(ref_int,'bias')}** | **{_fmt(ref_int,'r')}** |")
    lines.append(f"| 留存力 | 存档绝对评分(old) | {old_ret['n']} | {_fmt(old_ret,'mae')} | {_fmt_signed(old_ret,'bias')} | {_fmt(old_ret,'r')} |")
    lines.append(f"| 留存力 | 新鲜绝对评分(today) | {fresh_ret['n']} | {_fmt(fresh_ret,'mae')} | {_fmt_signed(fresh_ret,'bias')} | {_fmt(fresh_ret,'r')} |")
    lines.append(f"| **留存力** | **参考评分(reference)** | **{ref_ret['n']}** | **{_fmt(ref_ret,'mae')}** | **{_fmt_signed(ref_ret,'bias')}** | **{_fmt(ref_ret,'r')}** |")
    lines.append("")

    # MAE change analysis
    lines.append("## 二、MAE 改善分析\n")
    if ref_int['mae'] and fresh_int['mae'] and fresh_int['mae'] > 0:
        delta_i = ((ref_int['mae'] - fresh_int['mae']) / fresh_int['mae']) * 100
        lines.append(f"- 爽点强度 MAE 变化: {delta_i:+.1f}% (参考评分 vs 新鲜绝对评分)")
    if ref_ret['mae'] and fresh_ret['mae'] and fresh_ret['mae'] > 0:
        delta_r = ((ref_ret['mae'] - fresh_ret['mae']) / fresh_ret['mae']) * 100
        lines.append(f"- 留存力 MAE 变化: {delta_r:+.1f}% (参考评分 vs 新鲜绝对评分)")
    lines.append("")

    # Bias change analysis
    lines.append("## 三、Bias 改善分析\n")
    if ref_int.get('bias') is not None and fresh_int.get('bias') is not None:
        bias_change_i = ref_int['bias'] - fresh_int['bias']
        lines.append(f"- 爽点强度 Bias: 绝对评分={_fmt_signed(fresh_int,'bias')} → 参考评分={_fmt_signed(ref_int,'bias')} (变化{bias_change_i:+.3f})")
    if ref_ret.get('bias') is not None and fresh_ret.get('bias') is not None:
        bias_change_r = ref_ret['bias'] - fresh_ret['bias']
        lines.append(f"- 留存力 Bias: 绝对评分={_fmt_signed(fresh_ret,'bias')} → 参考评分={_fmt_signed(ref_ret,'bias')} (变化{bias_change_r:+.3f})")
    lines.append("")

    # Per-chapter details
    lines.append("## 四、逐章详情\n")
    lines.append("| # | 书名 | 章号 | 人工I | 人工R | 旧LLM I | 旧LLM R | 新鲜I | 新鲜R | 参考I | 参考R | 耗时(s) |")
    lines.append("|---|------|------|-------|-------|---------|---------|-------|-------|-------|-------|---------|")
    for i, r in enumerate(results, 1):
        def _v(val):
            return f"{val:.1f}" if val is not None else "—"
        lines.append(
            f"| {i} | {r['book']} | {r['ch_num']} | "
            f"{_v(r['human_intensity'])} | {_v(r['human_retention'])} | "
            f"{_v(r['old_llm_intensity'])} | {_v(r['old_llm_retention'])} | "
            f"{_v(r['fresh_abs_intensity'])} | {_v(r['fresh_abs_retention'])} | "
            f"{_v(r['ref_intensity'])} | {_v(r['ref_retention'])} | "
            f"{r['elapsed_s']} |"
        )
    lines.append("")

    # Method description
    lines.append("## 五、方法说明\n")
    lines.append("### Reference-Based Scoring 方法\n")
    lines.append("1. **参考库构建**: 从 `human_golden_merged.csv` 的47章golden数据中，按human_intensity分4个分值段(low≤3.5, medium_low≤5.5, medium_high≤7.5, high>7.5)\n")
    lines.append("2. **参考段落选取**: 每段选1个最接近段中心的章节，提取~400字摘录(head150+tail250)\n")
    lines.append("3. **Leave-one-out**: 评分章节X时从参考库中排除X，防止数据泄露\n")
    lines.append("4. **Prompt注入**: 在system message中注入4个参考段落+已知人工评分，要求LLM先与参考对比再评分\n")
    lines.append("5. **公平对比**: 同一章节同时跑absolute评分(fresh)和reference评分，消除时间漂移\n")
    lines.append("")
    lines.append("### 论文依据\n")
    lines.append("- **MDPI 2025**: *Can LLMs Be Good Evaluators in Creative Writing Tasks?* — LLM评分存在positivity bias\n")
    lines.append("- **ACL 2025**: *Automated Creativity Evaluation for LLMs* — reference-based scoring MAE降低30-50%\n")
    lines.append("- **ACM 2025**: *Rubric Is All You Need* — Rubric-based评分方法论\n")
    lines.append("")

    # Conclusion
    lines.append("## 六、结论\n")
    lines.append("### Bias 改善 (核心指标)\n")
    if ref_int.get('bias') is not None and fresh_int.get('bias') is not None and fresh_int.get('bias', 0) != 0:
        bias_red_i = (fresh_int['bias'] - ref_int['bias']) / abs(fresh_int['bias']) * 100
        lines.append(f"- 爽点强度 Bias: {fresh_int['bias']:+.3f}(abs) -> {ref_int['bias']:+.3f}(ref) = **{bias_red_i:+.0f}%**\n")
    if ref_ret.get('bias') is not None and fresh_ret.get('bias') is not None and fresh_ret.get('bias', 0) != 0:
        bias_red_r = (fresh_ret['bias'] - ref_ret['bias']) / abs(fresh_ret['bias']) * 100
        lines.append(f"- 留存力 Bias: {fresh_ret['bias']:+.3f}(abs) -> {ref_ret['bias']:+.3f}(ref) = **{bias_red_r:+.0f}%**\n")
    lines.append("")
    lines.append("### MAE & r\n")
    if ref_int.get('mae') and fresh_int.get('mae'):
        if ref_int['mae'] < fresh_int['mae']:
            lines.append(f"- ✅ 爽点强度 MAE: {fresh_int['mae']}->{ref_int['mae']} ({((fresh_int['mae']-ref_int['mae'])/fresh_int['mae']*100):.1f}%)\n")
        else:
            lines.append(f"- ⚠️ 爽点强度 MAE: {fresh_int['mae']}->{ref_int['mae']}\n")
    if ref_ret.get('mae') and fresh_ret.get('mae'):
        if ref_ret['mae'] < fresh_ret['mae']:
            lines.append(f"- ✅ 留存力 MAE: {fresh_ret['mae']}->{ref_ret['mae']} ({((fresh_ret['mae']-ref_ret['mae'])/fresh_ret['mae']*100):.1f}%)\n")
        else:
            lines.append(f"- ⚠️ 留存力 MAE: {fresh_ret['mae']}->{ref_ret['mae']}\n")
    if ref_int.get('r') and fresh_int.get('r'):
        lines.append(f"- 爽点强度 r: {fresh_int['r']}(abs) -> {ref_int['r']}(ref)\n")
    lines.append("")
    lines.append(f"### 说明 (N_ref={ref_int.get('n','?')}/47, N_abs={fresh_int.get('n','?')}/47)\n")
    lines.append("- ref max_tokens=600 (含参考分析), abs max_tokens=300 (生产)\n")
    lines.append("- Leave-one-out + JSON解析失败重试\n")
    lines.append("")

    with open(md_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
