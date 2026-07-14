#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
v815_run_to_run_variance.py — 量化LLM评分的run-to-run方差
===========================================================
对47章golden逐章跑absolute评分3次，计算Bias/MAE/r的均值±标准差。

用法:
  $env:PYTHONUTF8=1
  D:\miniconda3\envs\llm-shared\python.exe scripts/v815_run_to_run_variance.py

输出:
  data/reports/末世/v8.15_run_to_run_variance.json
"""
import sys
import os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

os.environ["PYTHONUTF8"] = "1"

import csv
import json
import time
import statistics
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

GENRE = "末世"
N_RUNS = 3


def _compute_metrics(human_vals, predicted_vals):
    """Compute MAE, Bias, Pearson r."""
    pairs = [(h, p) for h, p in zip(human_vals, predicted_vals) if p is not None]
    if len(pairs) < 3:
        return {"n": len(pairs), "mae": None, "bias": None, "r": None}
    h_vals = [p[0] for p in pairs]
    p_vals = [p[1] for p in pairs]
    n = len(pairs)
    mae = sum(abs(h - p) for h, p in pairs) / n
    bias = sum(p - h for h, p in pairs) / n
    mean_h = sum(h_vals) / n
    mean_p = sum(p_vals) / n
    cov = sum((h_vals[i] - mean_h) * (p_vals[i] - mean_p) for i in range(n))
    std_h = (sum((h - mean_h) ** 2 for h in h_vals)) ** 0.5
    std_p = (sum((p - mean_p) ** 2 for p in p_vals)) ** 0.5
    r = cov / (std_h * std_p) if std_h > 0 and std_p > 0 else 0.0
    return {"n": n, "mae": round(mae, 3), "bias": round(bias, 3), "r": round(r, 4)}


def main():
    from xiaoshuo.pipeline.llm_batch_score import (
        extract_chapters, build_reference_bank, llm_score_rubric, INDEX_PATH, NOVELS_DIR
    )

    # Load golden
    golden_csv = PROJECT_ROOT / "data" / "golden" / GENRE / "tier3" / "human_golden_merged.csv"
    with open(golden_csv, 'r', encoding='utf-8-sig') as f:
        golden_rows = list(csv.DictReader(f))

    print(f"Golden: {len(golden_rows)} chapters from {len(set(r['book'] for r in golden_rows))} books")
    print(f"Running {N_RUNS} independent absolute scoring passes...")

    # Build chapter text cache
    with open(INDEX_PATH, 'r', encoding='utf-8') as f:
        index = json.load(f)
    novels = index.get("genres", {}).get(GENRE, {}).get("novels", [])
    book_to_txt = {}
    for novel in novels:
        txt_file = novel.get("file", "")
        for fp in NOVELS_DIR.glob(f"{GENRE}/*.txt"):
            if fp.name == txt_file:
                short_name = txt_file.replace(".txt", "").replace("《", "").replace("》", "")
                import re
                m = re.match(r"([^（(]+)", short_name)
                if m:
                    short_name = m.group(1).strip()
                book_to_txt[short_name] = fp
                break

    _chapter_cache = {}
    all_runs = []

    for run_idx in range(N_RUNS):
        print(f"\n--- Run {run_idx+1}/{N_RUNS} ---", flush=True)
        results = []
        t0 = time.time()

        for i, row in enumerate(golden_rows):
            book_name = row.get("book", "").strip()
            ch_num = int(row.get("ch_num", 0))
            human_i = float(row.get("human_intensity", 0) or 0)
            human_r = float(row.get("human_retention", 0) or 0)

            if not book_name or ch_num == 0:
                continue

            # Find chapter text
            txt_path = None
            for sn, fp in book_to_txt.items():
                if sn in book_name or book_name in sn:
                    txt_path = fp
                    break
            if txt_path is None:
                continue

            cache_key = str(txt_path)
            if cache_key not in _chapter_cache:
                _chapter_cache[cache_key] = extract_chapters(txt_path)
            chapters = _chapter_cache[cache_key]

            chapter = None
            for ch in chapters:
                if ch.get("num") == ch_num:
                    chapter = ch
                    break
            if chapter is None:
                continue

            text = chapter.get("raw_body", "")[:1200]
            result = llm_score_rubric(text, ch_num, temperature=0.0)

            if result:
                results.append({
                    "book": book_name, "ch_num": ch_num,
                    "human_i": human_i, "human_r": human_r,
                    "llm_i": float(result["intensity"]),
                    "llm_r": float(result["retention"]),
                })
                print(f"  [{i+1}/{len(golden_rows)}] {book_name} ch{ch_num}: i={result['intensity']} r={result['retention']}", flush=True)

            time.sleep(0.3)

        elapsed = time.time() - t0
        print(f"Run {run_idx+1} done: {len(results)}/{len(golden_rows)} chapters in {elapsed:.0f}s", flush=True)

        # Compute metrics
        human_i = [r["human_i"] for r in results]
        llm_i = [r["llm_i"] for r in results]
        human_r = [r["human_r"] for r in results]
        llm_r = [r["llm_r"] for r in results]

        int_m = _compute_metrics(human_i, llm_i)
        ret_m = _compute_metrics(human_r, llm_r)

        print(f"  Intensity: MAE={int_m['mae']} Bias={int_m['bias']:+.3f} r={int_m['r']}", flush=True)
        print(f"  Retention:  MAE={ret_m['mae']} Bias={ret_m['bias']:+.3f} r={ret_m['r']}", flush=True)

        all_runs.append({
            "run": run_idx + 1,
            "n": len(results),
            "intensity": int_m,
            "retention": ret_m,
            "results": results,
        })

    # === Summary ===
    print(f"\n{'='*70}", flush=True)
    print(f"  Run-to-Run Variance Summary ({N_RUNS} runs, N=47)", flush=True)
    print(f"{'='*70}", flush=True)

    int_maes = [r["intensity"]["mae"] for r in all_runs if r["intensity"]["mae"]]
    int_biases = [r["intensity"]["bias"] for r in all_runs if r["intensity"]["bias"] is not None]
    int_rs = [r["intensity"]["r"] for r in all_runs if r["intensity"]["r"]]
    ret_maes = [r["retention"]["mae"] for r in all_runs if r["retention"]["mae"]]
    ret_biases = [r["retention"]["bias"] for r in all_runs if r["retention"]["bias"] is not None]
    ret_rs = [r["retention"]["r"] for r in all_runs if r["retention"]["r"]]

    print(f"  Intensity:", flush=True)
    print(f"    MAE:  {statistics.mean(int_maes):.3f} +/- {statistics.stdev(int_maes):.3f} (range {min(int_maes):.3f}-{max(int_maes):.3f})", flush=True)
    print(f"    Bias: {statistics.mean(int_biases):+.3f} +/- {statistics.stdev(int_biases):.3f} (range {min(int_biases):+.3f}-{max(int_biases):+.3f})", flush=True)
    print(f"    r:    {statistics.mean(int_rs):.4f} +/- {statistics.stdev(int_rs):.4f} (range {min(int_rs):.4f}-{max(int_rs):.4f})", flush=True)
    print(f"  Retention:", flush=True)
    print(f"    MAE:  {statistics.mean(ret_maes):.3f} +/- {statistics.stdev(ret_maes):.3f} (range {min(ret_maes):.3f}-{max(ret_maes):.3f})", flush=True)
    print(f"    Bias: {statistics.mean(ret_biases):+.3f} +/- {statistics.stdev(ret_biases):.3f} (range {min(ret_biases):+.3f}-{max(ret_biases):+.3f})", flush=True)
    print(f"    r:    {statistics.mean(ret_rs):.4f} +/- {statistics.stdev(ret_rs):.4f} (range {min(ret_rs):.4f}-{max(ret_rs):.4f})", flush=True)

    print(f"\n  Key question: Is Bias std > Reference improvement (0.489)?", flush=True)
    if int_biases:
        bias_std = statistics.stdev(int_biases)
        print(f"    Intensity Bias std = {bias_std:.3f} vs Reference improvement = 0.489", flush=True)
        if bias_std > 0.489:
            print(f"    --> YES: run-to-run variance ({bias_std:.3f}) > improvement (0.489) -- improvement may be noise", flush=True)
        else:
            print(f"    --> NO: run-to-run variance ({bias_std:.3f}) < improvement (0.489) -- improvement is real", flush=True)

    # Save
    out_dir = PROJECT_ROOT / "data" / "reports" / GENRE
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "v8.15_run_to_run_variance.json"
    summary = {
        "n_runs": N_RUNS,
        "n_chapters": len(golden_rows),
        "intensity": {
            "mae_mean": round(statistics.mean(int_maes), 3), "mae_std": round(statistics.stdev(int_maes), 3),
            "bias_mean": round(statistics.mean(int_biases), 3), "bias_std": round(statistics.stdev(int_biases), 3),
            "r_mean": round(statistics.mean(int_rs), 4), "r_std": round(statistics.stdev(int_rs), 4),
        },
        "retention": {
            "mae_mean": round(statistics.mean(ret_maes), 3), "mae_std": round(statistics.stdev(ret_maes), 3),
            "bias_mean": round(statistics.mean(ret_biases), 3), "bias_std": round(statistics.stdev(ret_biases), 3),
            "r_mean": round(statistics.mean(ret_rs), 4), "r_std": round(statistics.stdev(ret_rs), 4),
        },
        "runs": all_runs,
    }
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n  Saved: {out_path}", flush=True)


if __name__ == "__main__":
    main()
