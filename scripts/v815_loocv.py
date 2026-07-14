#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
v815_loocv.py — Leave-One-Out Cross-Validation for OLS
=======================================================
N=47太小，5-fold每折只有9-10章。LOOCV用46章训练+1章测试×47次，
更稳定地评估OLS泛化性。

用法:
  $env:PYTHONUTF8=1
  D:\miniconda3\envs\llm-shared\python.exe scripts/v815_loocv.py
"""
import sys, os
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
os.environ["PYTHONUTF8"] = "1"

import json, statistics
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

def _pearson_r(xs, ys):
    n = len(xs)
    if n < 3: return 0.0
    mx, my = sum(xs)/n, sum(ys)/n
    cov = sum((xs[i]-mx)*(ys[i]-my) for i in range(n))
    sx = (sum((x-mx)**2 for x in xs))**0.5
    sy = (sum((y-my)**2 for y in ys))**0.5
    return cov/(sx*sy) if sx > 0 and sy > 0 else 0.0

def _ols_fit(xs, ys):
    n = len(xs)
    if n < 3: return (0.0, 1.0)
    mx, my = sum(xs)/n, sum(ys)/n
    cov = sum((xs[i]-mx)*(ys[i]-my) for i in range(n))
    var = sum((x-mx)**2 for x in xs)
    if var == 0: return (my, 0.0)
    slope = cov / var
    return (round(my - slope*mx, 3), round(slope, 3))

def main():
    data_path = PROJECT_ROOT / "data" / "reports" / "末世" / "v8.15_verify_full_47.json"
    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    results = data["results"]
    llm_i = [r["new_i"] for r in results]
    hum_i = [r["human_i"] for r in results]
    llm_r = [r["new_r"] for r in results]
    hum_r = [r["human_r"] for r in results]
    n = len(results)

    print(f"LOOCV: N={n} chapters (temp=0.0+prev_context)", flush=True)

    # Full-sample OLS (in-sample baseline)
    full_ols_i = _ols_fit(llm_i, hum_i)
    full_ols_r = _ols_fit(llm_r, hum_r)
    full_cal_i = [full_ols_i[0] + full_ols_i[1] * x for x in llm_i]
    full_cal_r = [full_ols_r[0] + full_ols_r[1] * x for x in llm_r]
    full_mae_i = sum(abs(hum_i[j] - full_cal_i[j]) for j in range(n)) / n
    full_mae_r = sum(abs(hum_r[j] - full_cal_r[j]) for j in range(n)) / n
    print(f"\nFull-sample OLS: I={full_ols_i[0]}+{full_ols_i[1]}x (MAE={full_mae_i:.3f})", flush=True)
    print(f"                  R={full_ols_r[0]}+{full_ols_r[1]}x (MAE={full_mae_r:.3f})", flush=True)

    # LOOCV
    loocv_errors_i = []
    loocv_errors_r = []
    loocv_slopes_i = []
    loocv_intercepts_i = []
    loocv_slopes_r = []
    loocv_intercepts_r = []

    for leave_out in range(n):
        # Training set: all except leave_out
        tr_llm_i = [llm_i[j] for j in range(n) if j != leave_out]
        tr_hum_i = [hum_i[j] for j in range(n) if j != leave_out]
        tr_llm_r = [llm_r[j] for j in range(n) if j != leave_out]
        tr_hum_r = [hum_r[j] for j in range(n) if j != leave_out]

        # Fit OLS on training
        ti_int, ti_slope = _ols_fit(tr_llm_i, tr_hum_i)
        tr_int, tr_slope = _ols_fit(tr_llm_r, tr_hum_r)

        loocv_intercepts_i.append(ti_int)
        loocv_slopes_i.append(ti_slope)
        loocv_intercepts_r.append(tr_int)
        loocv_slopes_r.append(tr_slope)

        # Predict on left-out chapter
        pred_i = ti_int + ti_slope * llm_i[leave_out]
        pred_r = tr_int + tr_slope * llm_r[leave_out]

        loocv_errors_i.append(abs(hum_i[leave_out] - pred_i))
        loocv_errors_r.append(abs(hum_r[leave_out] - pred_r))

    mae_loocv_i = sum(loocv_errors_i) / n
    mae_loocv_r = sum(loocv_errors_r) / n

    # Also compute LOOCV r (correlation between predicted and actual human)
    loocv_preds_i = []
    loocv_preds_r = []
    for leave_out in range(n):
        tr_llm_i = [llm_i[j] for j in range(n) if j != leave_out]
        tr_hum_i = [hum_i[j] for j in range(n) if j != leave_out]
        tr_llm_r = [llm_r[j] for j in range(n) if j != leave_out]
        tr_hum_r = [hum_r[j] for j in range(n) if j != leave_out]
        ti_int, ti_slope = _ols_fit(tr_llm_i, tr_hum_i)
        tr_int, tr_slope = _ols_fit(tr_llm_r, tr_hum_r)
        loocv_preds_i.append(ti_int + ti_slope * llm_i[leave_out])
        loocv_preds_r.append(tr_int + tr_slope * llm_r[leave_out])

    r_loocv_i = _pearson_r(hum_i, loocv_preds_i)
    r_loocv_r = _pearson_r(hum_r, loocv_preds_r)

    print(f"\n{'='*60}", flush=True)
    print(f"  LOOCV Results (Leave-One-Out, N={n})", flush=True)
    print(f"{'='*60}", flush=True)
    print(f"  Intensity:", flush=True)
    print(f"    In-sample  MAE = {full_mae_i:.3f}", flush=True)
    print(f"    LOOCV      MAE = {mae_loocv_i:.3f} (delta = {mae_loocv_i - full_mae_i:+.3f})", flush=True)
    print(f"    LOOCV      r   = {r_loocv_i:.4f}", flush=True)
    print(f"    Slope range: {min(loocv_slopes_i):.3f}-{max(loocv_slopes_i):.3f} (range={max(loocv_slopes_i)-min(loocv_slopes_i):.3f})", flush=True)
    print(f"    Intercept range: {min(loocv_intercepts_i):.3f}-{max(loocv_intercepts_i):.3f}", flush=True)
    print(f"  Retention:", flush=True)
    print(f"    In-sample  MAE = {full_mae_r:.3f}", flush=True)
    print(f"    LOOCV      MAE = {mae_loocv_r:.3f} (delta = {mae_loocv_r - full_mae_r:+.3f})", flush=True)
    print(f"    LOOCV      r   = {r_loocv_r:.4f}", flush=True)
    print(f"    Slope range: {min(loocv_slopes_r):.3f}-{max(loocv_slopes_r):.3f}", flush=True)

    print(f"\n  Comparison with 5-fold CV:", flush=True)
    print(f"    5-fold  MAE_I = 1.550 +/- 0.322", flush=True)
    print(f"    LOOCV   MAE_I = {mae_loocv_i:.3f} (no variance, deterministic)", flush=True)

    # Save
    out = {
        "method": "LOOCV (Leave-One-Out Cross-Validation)",
        "n": n,
        "data_source": "v8.15_verify_full_47.json (temp=0.0+prev_context, fresh)",
        "intensity": {
            "in_sample_mae": round(full_mae_i, 3),
            "loocv_mae": round(mae_loocv_i, 3),
            "delta": round(mae_loocv_i - full_mae_i, 3),
            "loocv_r": round(r_loocv_i, 4),
            "slope_range": [round(min(loocv_slopes_i), 3), round(max(loocv_slopes_i), 3)],
            "intercept_range": [round(min(loocv_intercepts_i), 3), round(max(loocv_intercepts_i), 3)],
            "full_ols": {"intercept": full_ols_i[0], "slope": full_ols_i[1]},
        },
        "retention": {
            "in_sample_mae": round(full_mae_r, 3),
            "loocv_mae": round(mae_loocv_r, 3),
            "delta": round(mae_loocv_r - full_mae_r, 3),
            "loocv_r": round(r_loocv_r, 4),
            "slope_range": [round(min(loocv_slopes_r), 3), round(max(loocv_slopes_r), 3)],
            "full_ols": {"intercept": full_ols_r[0], "slope": full_ols_r[1]},
        },
    }
    out_path = PROJECT_ROOT / "data" / "reports" / "末世" / "v8.15_loocv_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n  Saved: {out_path}", flush=True)

if __name__ == "__main__":
    main()
