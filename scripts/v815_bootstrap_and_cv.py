#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
v815_bootstrap_and_cv.py — Bootstrap CI + k-fold CV
====================================================
1. Bootstrap 1000次重采样: 给MAE/Bias/r加95%置信区间
2. 5-fold CV: 验证OLS校准参数的泛化性

用法:
  $env:PYTHONUTF8=1
  D:\miniconda3\envs\llm-shared\python.exe scripts/v815_bootstrap_and_cv.py

输出:
  data/reports/末世/v8.15_bootstrap_cv_results.json
"""
import sys
import os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

os.environ["PYTHONUTF8"] = "1"

import json
import random
import statistics
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def _pearson_r(xs, ys):
    n = len(xs)
    if n < 3:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    sx = (sum((x - mx) ** 2 for x in xs)) ** 0.5
    sy = (sum((y - my) ** 2 for y in ys)) ** 0.5
    if sx == 0 or sy == 0:
        return 0.0
    return cov / (sx * sy)


def _metrics(human, predicted):
    n = len(human)
    if n < 3:
        return {"mae": None, "bias": None, "r": None, "n": n}
    mae = sum(abs(human[i] - predicted[i]) for i in range(n)) / n
    bias = sum(predicted[i] - human[i] for i in range(n)) / n
    r = _pearson_r(human, predicted)
    return {"mae": round(mae, 3), "bias": round(bias, 3), "r": round(r, 4), "n": n}


def _ols_fit(xs, ys):
    """Simple OLS: y = a + b*x. Returns (intercept, slope)."""
    n = len(xs)
    if n < 3:
        return (0.0, 1.0)
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    var_x = sum((x - mx) ** 2 for x in xs)
    if var_x == 0:
        return (my, 0.0)
    slope = cov / var_x
    intercept = my - slope * mx
    return (round(intercept, 3), round(slope, 3))


def main():
    # Load v8.14 data (temp=0.0 + prev_context, 47 chapters)
    data_path = PROJECT_ROOT / "data" / "reports" / "末世" / "v8.14_reference_scoring_data.json"
    with open(data_path, "r", encoding="utf-8") as f:
        v814_data = json.load(f)

    results = v814_data.get("results", [])
    # Extract (llm_abs, human) pairs
    pairs_i = []  # (llm_intensity, human_intensity)
    pairs_r = []  # (llm_retention, human_retention)
    for r in results:
        llm_i = r.get("fresh_abs_intensity")
        hum_i = r.get("human_intensity")
        llm_r = r.get("fresh_abs_retention")
        hum_r = r.get("human_retention")
        if llm_i is not None and hum_i is not None:
            pairs_i.append((float(llm_i), float(hum_i)))
        if llm_r is not None and hum_r is not None:
            pairs_r.append((float(llm_r), float(hum_r)))

    n = len(pairs_i)
    print(f"Loaded {n} paired chapters (temp=0.0 + prev_context)", flush=True)
    print(f"  Intensity: {len(pairs_i)} pairs", flush=True)
    print(f"  Retention: {len(pairs_r)} pairs", flush=True)

    # === Baseline metrics (raw LLM vs human) ===
    llm_i = [p[0] for p in pairs_i]
    hum_i = [p[1] for p in pairs_i]
    llm_r = [p[0] for p in pairs_r]
    hum_r = [p[1] for p in pairs_r]

    base_i = _metrics(hum_i, llm_i)
    base_r = _metrics(hum_r, llm_r)

    print(f"\n=== Baseline (raw LLM vs Human, temp=0.0) ===", flush=True)
    print(f"  Intensity: MAE={base_i['mae']} Bias={base_i['bias']:+.3f} r={base_i['r']}", flush=True)
    print(f"  Retention:  MAE={base_r['mae']} Bias={base_r['bias']:+.3f} r={base_r['r']}", flush=True)

    # === OLS calibration (in-sample) ===
    ols_i = _ols_fit(llm_i, hum_i)
    ols_r = _ols_fit(llm_r, hum_r)
    cal_i = [ols_i[0] + ols_i[1] * x for x in llm_i]
    cal_r = [ols_r[0] + ols_r[1] * x for x in llm_r]
    ols_metrics_i = _metrics(hum_i, cal_i)
    ols_metrics_r = _metrics(hum_r, cal_r)

    print(f"\n=== OLS Calibration (in-sample, 47ch) ===", flush=True)
    print(f"  Intensity: human = {ols_i[0]:.3f} + {ols_i[1]:.3f} * LLM", flush=True)
    print(f"    MAE={ols_metrics_i['mae']} Bias={ols_metrics_i['bias']:+.3f} r={ols_metrics_i['r']}", flush=True)
    print(f"  Retention:  human = {ols_r[0]:.3f} + {ols_r[1]:.3f} * LLM", flush=True)
    print(f"    MAE={ols_metrics_r['mae']} Bias={ols_metrics_r['bias']:+.3f} r={ols_metrics_r['r']}", flush=True)

    # === Bootstrap CI (1000 resamples) ===
    N_BOOT = 1000
    random.seed(42)
    print(f"\n=== Bootstrap CI ({N_BOOT} resamples) ===", flush=True)

    boot_base_i = {"mae": [], "bias": [], "r": []}
    boot_base_r = {"mae": [], "bias": [], "r": []}
    boot_ols_i = {"mae": [], "bias": [], "r": [], "intercept": [], "slope": []}
    boot_ols_r = {"mae": [], "bias": [], "r": [], "intercept": [], "slope": []}

    for b in range(N_BOOT):
        # Resample with replacement
        idx = [random.randint(0, n - 1) for _ in range(n)]
        b_hum_i = [hum_i[j] for j in idx]
        b_llm_i = [llm_i[j] for j in idx]
        b_hum_r = [hum_r[j] for j in idx]
        b_llm_r = [llm_r[j] for j in idx]

        # Baseline
        m = _metrics(b_hum_i, b_llm_i)
        if m["mae"] is not None:
            boot_base_i["mae"].append(m["mae"])
            boot_base_i["bias"].append(m["bias"])
            boot_base_i["r"].append(m["r"])

        m = _metrics(b_hum_r, b_llm_r)
        if m["mae"] is not None:
            boot_base_r["mae"].append(m["mae"])
            boot_base_r["bias"].append(m["bias"])
            boot_base_r["r"].append(m["r"])

        # OLS fit on bootstrap sample
        bi_intercept, bi_slope = _ols_fit(b_llm_i, b_hum_i)
        boot_ols_i["intercept"].append(bi_intercept)
        boot_ols_i["slope"].append(bi_slope)
        b_cal_i = [bi_intercept + bi_slope * x for x in b_llm_i]
        m = _metrics(b_hum_i, b_cal_i)
        if m["mae"] is not None:
            boot_ols_i["mae"].append(m["mae"])
            boot_ols_i["bias"].append(m["bias"])
            boot_ols_i["r"].append(m["r"])

        br_intercept, br_slope = _ols_fit(b_llm_r, b_hum_r)
        boot_ols_r["intercept"].append(br_intercept)
        boot_ols_r["slope"].append(br_slope)
        b_cal_r = [br_intercept + br_slope * x for x in b_llm_r]
        m = _metrics(b_hum_r, b_cal_r)
        if m["mae"] is not None:
            boot_ols_r["mae"].append(m["mae"])
            boot_ols_r["bias"].append(m["bias"])
            boot_ols_r["r"].append(m["r"])

    def _ci(vals, pct=95):
        vals = sorted(vals)
        n = len(vals)
        lo = vals[int(n * (1 - pct / 100) / 2)]
        hi = vals[int(n * (1 + pct / 100) / 2) - 1]
        return round(lo, 3), round(hi, 3)

    print(f"\n  Baseline (raw LLM):", flush=True)
    lo, hi = _ci(boot_base_i["mae"])
    print(f"    Intensity MAE:  {base_i['mae']} [{lo}, {hi}] 95% CI", flush=True)
    lo, hi = _ci(boot_base_i["bias"])
    print(f"    Intensity Bias: {base_i['bias']:+.3f} [{lo:+.3f}, {hi:+.3f}] 95% CI", flush=True)
    lo, hi = _ci(boot_base_i["r"])
    print(f"    Intensity r:    {base_i['r']} [{lo}, {hi}] 95% CI", flush=True)
    lo, hi = _ci(boot_base_r["mae"])
    print(f"    Retention MAE:  {base_r['mae']} [{lo}, {hi}] 95% CI", flush=True)
    lo, hi = _ci(boot_base_r["bias"])
    print(f"    Retention Bias: {base_r['bias']:+.3f} [{lo:+.3f}, {hi:+.3f}] 95% CI", flush=True)
    lo, hi = _ci(boot_base_r["r"])
    print(f"    Retention r:    {base_r['r']} [{lo}, {hi}] 95% CI", flush=True)

    print(f"\n  OLS Calibrated:", flush=True)
    lo, hi = _ci(boot_ols_i["mae"])
    print(f"    Intensity MAE:  {ols_metrics_i['mae']} [{lo}, {hi}] 95% CI", flush=True)
    lo, hi = _ci(boot_ols_i["bias"])
    print(f"    Intensity Bias: {ols_metrics_i['bias']:+.3f} [{lo:+.3f}, {hi:+.3f}] 95% CI", flush=True)
    lo, hi = _ci(boot_ols_i["r"])
    print(f"    Intensity r:    {ols_metrics_i['r']} [{lo}, {hi}] 95% CI", flush=True)
    lo, hi = _ci(boot_ols_i["intercept"])
    print(f"    Intensity intercept: {ols_i[0]:.3f} [{lo}, {hi}] 95% CI", flush=True)
    lo, hi = _ci(boot_ols_i["slope"])
    print(f"    Intensity slope:    {ols_i[1]:.3f} [{lo}, {hi}] 95% CI", flush=True)
    lo, hi = _ci(boot_ols_r["mae"])
    print(f"    Retention MAE:  {ols_metrics_r['mae']} [{lo}, {hi}] 95% CI", flush=True)
    lo, hi = _ci(boot_ols_r["intercept"])
    print(f"    Retention intercept: {ols_r[0]:.3f} [{lo}, {hi}] 95% CI", flush=True)
    lo, hi = _ci(boot_ols_r["slope"])
    print(f"    Retention slope:    {ols_r[1]:.3f} [{lo}, {hi}] 95% CI", flush=True)

    # === k-fold CV (5-fold) ===
    K = 5
    print(f"\n=== {K}-fold Cross-Validation (OLS generalization) ===", flush=True)

    indices = list(range(n))
    random.seed(42)
    random.shuffle(indices)
    fold_size = n // K
    folds = [indices[i * fold_size:(i + 1) * fold_size] for i in range(K)]
    # Handle remainder
    for i in range(n % K):
        folds[i].append(indices[K * fold_size + i])

    cv_results_i = []
    cv_results_r = []
    fold_params_i = []
    fold_params_r = []

    for k in range(K):
        test_idx = set(folds[k])
        train_idx = [i for i in range(n) if i not in test_idx]

        # Train: fit OLS on train
        tr_llm_i = [llm_i[j] for j in train_idx]
        tr_hum_i = [hum_i[j] for j in train_idx]
        tr_llm_r = [llm_r[j] for j in train_idx]
        tr_hum_r = [hum_r[j] for j in train_idx]

        ti_intercept, ti_slope = _ols_fit(tr_llm_i, tr_hum_i)
        tr_intercept, tr_slope = _ols_fit(tr_llm_r, tr_hum_r)
        fold_params_i.append({"fold": k + 1, "intercept": ti_intercept, "slope": ti_slope, "train_n": len(train_idx)})
        fold_params_r.append({"fold": k + 1, "intercept": tr_intercept, "slope": tr_slope, "train_n": len(train_idx)})

        # Test: apply trained OLS to test
        te_llm_i = [llm_i[j] for j in folds[k]]
        te_hum_i = [hum_i[j] for j in folds[k]]
        te_llm_r = [llm_r[j] for j in folds[k]]
        te_hum_r = [hum_r[j] for j in folds[k]]

        te_cal_i = [ti_intercept + ti_slope * x for x in te_llm_i]
        te_cal_r = [tr_intercept + tr_slope * x for x in te_llm_r]

        m_i = _metrics(te_hum_i, te_cal_i)
        m_r = _metrics(te_hum_r, te_cal_r)
        cv_results_i.append({"fold": k + 1, "test_n": len(folds[k]), **m_i})
        cv_results_r.append({"fold": k + 1, "test_n": len(folds[k]), **m_r})

        print(f"  Fold {k+1}: train={len(train_idx)} test={len(folds[k])} | "
              f"I: MAE={m_i['mae']} Bias={m_i['bias']:+.3f} r={m_i['r']} (a={ti_intercept:.3f} b={ti_slope:.3f}) | "
              f"R: MAE={m_r['mae']} Bias={m_r['bias']:+.3f} r={m_r['r']}", flush=True)

    # Aggregate CV results
    cv_maes_i = [r["mae"] for r in cv_results_i if r["mae"] is not None]
    cv_biases_i = [r["bias"] for r in cv_results_i if r["bias"] is not None]
    cv_rs_i = [r["r"] for r in cv_results_i if r["r"] is not None]
    cv_maes_r = [r["mae"] for r in cv_results_r if r["mae"] is not None]
    cv_biases_r = [r["bias"] for r in cv_results_r if r["bias"] is not None]
    cv_rs_r = [r["r"] for r in cv_results_r if r["r"] is not None]

    print(f"\n  CV Summary (out-of-sample):", flush=True)
    print(f"    Intensity: MAE={statistics.mean(cv_maes_i):.3f}±{statistics.stdev(cv_maes_i):.3f} "
          f"Bias={statistics.mean(cv_biases_i):+.3f}±{statistics.stdev(cv_biases_i):.3f} "
          f"r={statistics.mean(cv_rs_i):.4f}±{statistics.stdev(cv_rs_i):.4f}", flush=True)
    print(f"    Retention:  MAE={statistics.mean(cv_maes_r):.3f}±{statistics.stdev(cv_maes_r):.3f} "
          f"Bias={statistics.mean(cv_biases_r):+.3f}±{statistics.stdev(cv_biases_r):.3f} "
          f"r={statistics.mean(cv_rs_r):.4f}±{statistics.stdev(cv_rs_r):.4f}", flush=True)

    print(f"\n  In-sample vs Out-of-sample (Intensity):", flush=True)
    print(f"    In-sample  MAE={ols_metrics_i['mae']} → Out-of-sample MAE={statistics.mean(cv_maes_i):.3f} "
          f"(delta={statistics.mean(cv_maes_i) - ols_metrics_i['mae']:+.3f})", flush=True)

    # Intercept/slope stability across folds
    slopes_i = [f["slope"] for f in fold_params_i]
    intercepts_i = [f["intercept"] for f in fold_params_i]
    print(f"\n  OLS parameter stability across {K} folds:", flush=True)
    print(f"    Intensity intercept: {min(intercepts_i):.3f}-{max(intercepts_i):.3f} (range={max(intercepts_i)-min(intercepts_i):.3f})", flush=True)
    print(f"    Intensity slope:     {min(slopes_i):.3f}-{max(slopes_i):.3f} (range={max(slopes_i)-min(slopes_i):.3f})", flush=True)

    # === Save results ===
    out = {
        "n_chapters": n,
        "n_bootstrap": N_BOOT,
        "k_folds": K,
        "baseline": {
            "intensity": {**base_i, "mae_ci": list(_ci(boot_base_i["mae"])), "bias_ci": list(_ci(boot_base_i["bias"])), "r_ci": list(_ci(boot_base_i["r"]))},
            "retention": {**base_r, "mae_ci": list(_ci(boot_base_r["mae"])), "bias_ci": list(_ci(boot_base_r["bias"])), "r_ci": list(_ci(boot_base_r["r"]))},
        },
        "ols_in_sample": {
            "intensity": {"intercept": ols_i[0], "slope": ols_i[1], **ols_metrics_i,
                          "mae_ci": list(_ci(boot_ols_i["mae"])), "bias_ci": list(_ci(boot_ols_i["bias"])),
                          "r_ci": list(_ci(boot_ols_i["r"])),
                          "intercept_ci": list(_ci(boot_ols_i["intercept"])), "slope_ci": list(_ci(boot_ols_i["slope"]))},
            "retention": {"intercept": ols_r[0], "slope": ols_r[1], **ols_metrics_r,
                          "mae_ci": list(_ci(boot_ols_r["mae"])), "bias_ci": list(_ci(boot_ols_r["bias"])),
                          "r_ci": list(_ci(boot_ols_r["r"])),
                          "intercept_ci": list(_ci(boot_ols_r["intercept"])), "slope_ci": list(_ci(boot_ols_r["slope"]))},
        },
        "k_fold_cv": {
            "intensity": {
                "mean_mae": round(statistics.mean(cv_maes_i), 3), "std_mae": round(statistics.stdev(cv_maes_i), 3),
                "mean_bias": round(statistics.mean(cv_biases_i), 3), "std_bias": round(statistics.stdev(cv_biases_i), 3),
                "mean_r": round(statistics.mean(cv_rs_i), 4), "std_r": round(statistics.stdev(cv_rs_i), 4),
                "folds": cv_results_i, "fold_params": fold_params_i,
            },
            "retention": {
                "mean_mae": round(statistics.mean(cv_maes_r), 3), "std_mae": round(statistics.stdev(cv_maes_r), 3),
                "mean_bias": round(statistics.mean(cv_biases_r), 3), "std_bias": round(statistics.stdev(cv_biases_r), 3),
                "mean_r": round(statistics.mean(cv_rs_r), 4), "std_r": round(statistics.stdev(cv_rs_r), 4),
                "folds": cv_results_r, "fold_params": fold_params_r,
            },
        },
    }

    out_path = PROJECT_ROOT / "data" / "reports" / "末世" / "v8.15_bootstrap_cv_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n  Saved: {out_path}", flush=True)


if __name__ == "__main__":
    main()
