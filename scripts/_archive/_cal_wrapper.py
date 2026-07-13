#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Wrapper to catch all errors"""
import sys, traceback, os

os.chdir("d:/Code/xiaoshuo")

output_lines = []
def log(msg):
    output_lines.append(str(msg))

try:
    log("Step 1: imports")
    import csv, json, statistics
    from pathlib import Path
    from collections import defaultdict
    import numpy as np
    log("Step 2: paths")
    PROJECT = Path("d:/Code/xiaoshuo")
    TIER3_DIR = PROJECT / "data" / "golden" / "末世" / "tier3"
    GOLDEN_CSV = PROJECT / "data" / "golden" / "末世" / "human_golden.csv"
    GLM_JSON = TIER3_DIR / "tier3_glm_scores.json"
    log(f"  GOLDEN_CSV exists: {GOLDEN_CSV.exists()}")
    log(f"  GLM_JSON exists: {GLM_JSON.exists()}")
    
    log("Step 3: load golden")
    def _safe_float(v):
        try: return float(v)
        except: return None
    
    golden_data = []
    with open(GOLDEN_CSV, 'r', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            golden_data.append({
                "book": row.get("book", ""),
                "ch_num": int(row.get("ch_num", 0)),
                "t1_intensity": _safe_float(row.get("llm_intensity")),
                "t1_retention": _safe_float(row.get("llm_retention")),
                "human_intensity": _safe_float(row.get("human_intensity")),
                "human_retention": _safe_float(row.get("human_retention")),
                "source": "human_golden",
            })
    log(f"  Golden rows: {len(golden_data)}")
    
    golden_dedup = {}
    for d in golden_data:
        key = (d["book"], d["ch_num"])
        golden_dedup[key] = d
    golden_data = list(golden_dedup.values())
    log(f"  Golden deduped: {len(golden_data)}")
    
    log("Step 4: load GLM")
    with open(GLM_JSON, 'r', encoding='utf-8') as f:
        glm_data = json.load(f)
    log(f"  GLM chapters: {glm_data['metadata']['total_chapters']}")
    
    glm_scores = []
    for book, chapters in glm_data["scores"].items():
        plan_csv = TIER3_DIR / f"{book}_tier3_plan.csv"
        plan = {}
        if plan_csv.exists():
            with open(plan_csv, 'r', encoding='utf-8-sig') as f:
                for row in csv.DictReader(f):
                    plan[int(row["ch_num"])] = row
        for ch in chapters:
            ch_num = ch["ch_num"]
            plan_row = plan.get(ch_num, {})
            glm_scores.append({
                "book": book,
                "ch_num": ch_num,
                "t1_intensity": _safe_float(plan_row.get("ai_intensity")),
                "t1_retention": _safe_float(plan_row.get("ai_retention")),
                "t2_intensity": _safe_float(plan_row.get("t2_intensity")),
                "t2_retention": _safe_float(plan_row.get("t2_retention")),
                "human_intensity": float(ch["intensity"]),
                "human_retention": float(ch["retention"]),
                "source": "glm_tier3",
            })
    log(f"  GLM scores: {len(glm_scores)}")
    
    all_data = golden_data + glm_scores
    log(f"  Total: {len(all_data)}")
    
    book_counts = defaultdict(int)
    for d in all_data:
        book_counts[d["book"]] += 1
    
    log("Step 5: bias analysis")
    def calc_bias(data, model_key, metric):
        diffs = []
        for d in data:
            model_val = d.get(f"{model_key}_{metric}")
            human_val = d.get(f"human_{metric}")
            if model_val is not None and human_val is not None:
                diffs.append(model_val - human_val)
        if not diffs:
            return None, None, 0
        mae = statistics.mean([abs(x) for x in diffs])
        bias = statistics.mean(diffs)
        return mae, bias, len(diffs)
    
    for metric in ["intensity", "retention"]:
        log(f"\n--- {metric} ---")
        for model in ["t1", "t2"]:
            mae, bias, n = calc_bias(all_data, model, metric)
            if mae is not None:
                log(f"  {model.upper()}: MAE={mae:.2f}, Bias={bias:+.2f}, n={n}")
    
    log("Step 6: per-book")
    for book in sorted(book_counts.keys()):
        book_data = [d for d in all_data if d["book"] == book]
        mae_i, bias_i, n_i = calc_bias(book_data, "t1", "intensity")
        mae_r, bias_r, n_r = calc_bias(book_data, "t1", "retention")
        if mae_i:
            log(f"  {book}: I(MAE={mae_i:.1f},Bias={bias_i:+.1f}) R(MAE={mae_r:.1f},Bias={bias_r:+.1f}) n={n_i}")
    
    log("Step 7: OLS")
    cal_data = []
    for d in all_data:
        t1_i = d.get("t1_intensity")
        t1_r = d.get("t1_retention")
        h_i = d.get("human_intensity")
        h_r = d.get("human_retention")
        if t1_i is not None and h_i is not None:
            cal_data.append((t1_i, h_i, "intensity"))
        if t1_r is not None and h_r is not None:
            cal_data.append((t1_r, h_r, "retention"))
    
    ols_results = {}
    for metric_name in ["intensity", "retention"]:
        pairs = [(x[0], x[1]) for x in cal_data if x[2] == metric_name]
        if len(pairs) < 5:
            continue
        x = np.array([pp[0] for pp in pairs])
        y = np.array([pp[1] for pp in pairs])
        n = len(pairs)
        x_mean = np.mean(x)
        y_mean = np.mean(y)
        ss_xx = np.sum((x - x_mean) ** 2)
        ss_xy = np.sum((x - x_mean) * (y - y_mean))
        if ss_xx == 0:
            continue
        b = ss_xy / ss_xx
        a = y_mean - b * x_mean
        y_pred = a + b * x
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - y_mean) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
        r = np.corrcoef(x, y)[0, 1] if n > 2 else 0
        log(f"\n  {metric_name}: human = {a:.2f} + {b:.3f} * T1")
        log(f"    n={n}, R2={r2:.3f}, r={r:.3f}")
        log(f"    T1=5 -> human={a+b*5:.1f}, T1=8 -> human={a+b*8:.1f}, T1=10 -> human={a+b*10:.1f}")
        ols_results[metric_name] = {"a": a, "b": b, "r2": r2, "r": r, "n": n}
    
    log("Step 8: LOOCV")
    loocv_results = {}
    for metric_name in ["intensity", "retention"]:
        pairs = [(d["t1_" + metric_name], d["human_" + metric_name])
                 for d in all_data
                 if d.get("t1_" + metric_name) is not None and d.get("human_" + metric_name) is not None]
        if len(pairs) < 10:
            continue
        x = np.array([pp[0] for pp in pairs])
        y = np.array([pp[1] for pp in pairs])
        n = len(pairs)
        preds = []
        for i in range(n):
            x_train = np.delete(x, i)
            y_train = np.delete(y, i)
            x_mean = np.mean(x_train)
            y_mean = np.mean(y_train)
            ss_xx = np.sum((x_train - x_mean) ** 2)
            ss_xy = np.sum((x_train - x_mean) * (y_train - y_mean))
            if ss_xx == 0:
                preds.append(y_mean)
            else:
                b = ss_xy / ss_xx
                a = y_mean - b * x_mean
                preds.append(a + b * x[i])
        preds = np.array(preds)
        if np.std(preds) > 0 and np.std(y) > 0:
            r = np.corrcoef(preds, y)[0, 1]
        else:
            r = 0
        mae = np.mean(np.abs(preds - y))
        log(f"  {metric_name}: n={n}, r={r:.3f}, MAE={mae:.2f}")
        loocv_results[metric_name] = {"n": n, "r": round(r, 3), "mae": round(mae, 2)}
    
    log("Step 9: save JSON")
    calibration = {
        "timestamp": "2026-07-13T15:30:00",
        "total_chapters": len(all_data),
        "books": dict(book_counts),
        "t1_bias": {},
        "t2_bias": {},
        "ols_params": {},
        "loocv": {},
    }
    for metric in ["intensity", "retention"]:
        mae, bias, n = calc_bias(all_data, "t1", metric)
        if mae:
            calibration["t1_bias"][metric] = {"mae": round(mae, 2), "bias": round(bias, 2), "n": n}
        mae, bias, n = calc_bias(all_data, "t2", metric)
        if mae:
            calibration["t2_bias"][metric] = {"mae": round(mae, 2), "bias": round(bias, 2), "n": n}
    
    for metric_name in ["intensity", "retention"]:
        if metric_name in ols_results:
            r = ols_results[metric_name]
            calibration["ols_params"][metric_name] = {
                "intercept": round(r["a"], 3), "slope": round(r["b"], 3),
                "r2": round(r["r2"], 3), "r": round(r["r"], 3), "n": r["n"],
            }
    
    for metric_name in ["intensity", "retention"]:
        if metric_name in loocv_results:
            calibration["loocv"][metric_name] = {
                "n": loocv_results[metric_name]["n"],
                "r": loocv_results[metric_name]["r"],
                "mae": loocv_results[metric_name]["mae"],
                "method": "Chapter-level LOOCV, T1 score vs human(Tier3) score",
            }
    
    out_path = PROJECT / "data" / "reports" / "末世" / "calibration" / "tier3_calibration.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(calibration, f, ensure_ascii=False, indent=2)
    log(f"  Saved to: {out_path}")
    
    log("\n=== SUMMARY ===")
    log(f"Total: {len(all_data)} chapters, {len(book_counts)} books")
    for metric in ["intensity", "retention"]:
        t1 = calibration["t1_bias"].get(metric, {})
        t2 = calibration["t2_bias"].get(metric, {})
        ols = calibration["ols_params"].get(metric, {})
        loocv = calibration["loocv"].get(metric, {})
        log(f"\n  {metric}:")
        if t1:
            log(f"    T1: MAE={t1['mae']}, Bias={t1['bias']:+}")
        if t2:
            log(f"    T2: MAE={t2['mae']}, Bias={t2['bias']:+}")
        if ols:
            log(f"    OLS: human = {ols['intercept']} + {ols['slope']} * T1 (R2={ols['r2']}, r={ols['r']})")
        if loocv:
            log(f"    LOOCV: r={loocv['r']}, MAE={loocv['mae']} (n={loocv['n']})")
    
    log("\nDONE!")
    
except Exception as e:
    log(f"ERROR: {e}")
    log(traceback.format_exc())

finally:
    with open(PROJECT / "scripts" / "calib_result.txt", 'w', encoding='utf-8') as f:
        f.write("\n".join(output_lines))
