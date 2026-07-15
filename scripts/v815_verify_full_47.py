#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
v815_verify_full_47.py — 完整47章重跑验证
==========================================
用temp=0.0+prev_context重跑全部47章，与v8.14数据对比整体指标。
如果Bias≈+0.904 → v8.14数据确认是temp=0.0(GLM错了)
如果Bias不同 → 模型状态变了，需重新拟合OLS

用法:
  $env:PYTHONUTF8=1
  D:\miniconda3\envs\llm-shared\python.exe scripts/v815_verify_full_47.py
"""
import sys, os
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
os.environ["PYTHONUTF8"] = "1"

import json, csv, re, time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

GENRE = "末世"

def _pearson_r(xs, ys):
    n = len(xs)
    if n < 3: return 0.0
    mx, my = sum(xs)/n, sum(ys)/n
    cov = sum((xs[i]-mx)*(ys[i]-my) for i in range(n))
    sx = (sum((x-mx)**2 for x in xs))**0.5
    sy = (sum((y-my)**2 for y in ys))**0.5
    return cov/(sx*sy) if sx > 0 and sy > 0 else 0.0

def main():
    from xiaoshuo.pipeline.llm_batch_score import llm_score_rubric, extract_chapters, INDEX_PATH, NOVELS_DIR

    # Load v8.14 data
    v814_path = PROJECT_ROOT / "data" / "reports" / "末世" / "v8.14_reference_scoring_data.json"
    with open(v814_path, "r", encoding="utf-8") as f:
        v814 = json.load(f)
    v814_results = v814.get("results", [])
    v814_lookup = {(r.get("book",""), r.get("ch_num",0)): r for r in v814_results}

    # Load golden CSV
    golden_csv = PROJECT_ROOT / "data" / "golden" / GENRE / "tier3" / "human_golden_merged.csv"
    with open(golden_csv, "r", encoding="utf-8-sig") as f:
        golden_rows = list(csv.DictReader(f))

    # Build book -> txt mapping
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        index = json.load(f)
    novels = index.get("genres", {}).get(GENRE, {}).get("novels", [])
    book_to_txt = {}
    for novel in novels:
        txt_file = novel.get("file", "")
        for fp in NOVELS_DIR.glob(f"{GENRE}/*.txt"):
            if fp.name == txt_file:
                short_name = txt_file.replace(".txt","").replace("《","").replace("》","")
                m = re.match(r"([^（(]+)", short_name)
                if m: short_name = m.group(1).strip()
                book_to_txt[short_name] = fp
                break

    _cache = {}
    results = []
    matches = 0
    total = 0
    t0 = time.time()

    for i, row in enumerate(golden_rows):
        book = row.get("book", "").strip()
        ch_num = int(row.get("ch_num", 0))
        human_i = float(row.get("human_intensity", 0) or 0)
        human_r = float(row.get("human_retention", 0) or 0)

        txt_path = None
        for sn, fp in book_to_txt.items():
            if sn in book or book in sn:
                txt_path = fp
                break
        if txt_path is None:
            continue

        if str(txt_path) not in _cache:
            _cache[str(txt_path)] = extract_chapters(txt_path)
        chapters = _cache[str(txt_path)]

        chapter = None
        ch_idx = None
        for ci, ch in enumerate(chapters):
            if ch.get("num") == ch_num:
                chapter = ch
                ch_idx = ci
                break
        if chapter is None:
            continue

        text = chapter.get("raw_body", "")[:1200]

        prev_context = ""
        if ch_idx > 0:
            prev_body = chapters[ch_idx - 1].get("raw_body", "")
            if prev_body:
                prev_context = prev_body[-200:].replace("\n", " ").strip()

        result = llm_score_rubric(text, ch_num, prev_context=prev_context, temperature=0.0)

        if result:
            new_i = float(result["intensity"])
            new_r = float(result["retention"])
            results.append({"book": book, "ch_num": ch_num, "human_i": human_i, "human_r": human_r, "new_i": new_i, "new_r": new_r})

            # Compare with v8.14
            v814_entry = v814_lookup.get((book, ch_num))
            if v814_entry:
                old_i = v814_entry.get("fresh_abs_intensity")
                old_r = v814_entry.get("fresh_abs_retention")
                if old_i is not None:
                    total += 1
                    if new_i == float(old_i) and new_r == float(old_r):
                        matches += 1

            print(f"  [{i+1}/47] {book} ch{ch_num}: i={new_i} r={new_r}", flush=True)

        time.sleep(0.2)

    elapsed = time.time() - t0

    # Compute metrics
    hum_i = [r["human_i"] for r in results]
    new_i = [r["new_i"] for r in results]
    hum_r = [r["human_r"] for r in results]
    new_r = [r["new_r"] for r in results]
    n = len(results)

    mae_i = sum(abs(hum_i[j]-new_i[j]) for j in range(n))/n
    bias_i = sum(new_i[j]-hum_i[j] for j in range(n))/n
    r_i = _pearson_r(hum_i, new_i)
    mae_r = sum(abs(hum_r[j]-new_r[j]) for j in range(n))/n
    bias_r = sum(new_r[j]-hum_r[j] for j in range(n))/n
    r_r = _pearson_r(hum_r, new_r)

    print(f"\n{'='*60}", flush=True)
    print(f"  Full 47-chapter re-run (temp=0.0 + prev_context)", flush=True)
    print(f"  Time: {elapsed:.0f}s | N={n}", flush=True)
    print(f"  Chapter-level match with v8.14: {matches}/{total}", flush=True)
    print(f"{'='*60}", flush=True)
    print(f"  Intensity: MAE={mae_i:.3f} Bias={bias_i:+.3f} r={r_i:.4f}", flush=True)
    print(f"  Retention:  MAE={mae_r:.3f} Bias={bias_r:+.3f} r={r_r:.4f}", flush=True)
    print(f"\n  v8.14 baseline was: MAE=1.862 Bias=+0.904 r=0.3806", flush=True)
    print(f"  v8.15 (no ctx) was: MAE=1.628 Bias=-0.181 r=0.4937", flush=True)

    if abs(bias_i - 0.904) < 0.15:
        print(f"\n  --> CONFIRMED: Bias={bias_i:+.3f} ≈ v8.14's +0.904", flush=True)
        print(f"  --> v8.14 data IS temp=0.0 + prev_context (GLM was WRONG)", flush=True)
    elif abs(bias_i - (-0.181)) < 0.15:
        print(f"\n  --> INTERESTING: Bias={bias_i:+.3f} ≈ v8.15's -0.181 (no ctx result)", flush=True)
        print(f"  --> prev_context might not be working as expected", flush=True)
    else:
        print(f"\n  --> NEW RESULT: Bias={bias_i:+.3f} differs from both v8.14(+0.904) and v8.15(-0.181)", flush=True)
        print(f"  --> Model state may have changed. Need to re-fit OLS with this data.", flush=True)

    # Save
    out = {
        "n": n, "elapsed_s": round(elapsed), "matches_with_v814": f"{matches}/{total}",
        "intensity": {"mae": round(mae_i,3), "bias": round(bias_i,3), "r": round(r_i,4)},
        "retention": {"mae": round(mae_r,3), "bias": round(bias_r,3), "r": round(r_r,4)},
        "results": results,
    }
    out_path = PROJECT_ROOT / "data" / "reports" / GENRE / "v8.15_verify_full_47.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n  Saved: {out_path}", flush=True)

if __name__ == "__main__":
    main()
