#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Tier3 calibration with error handling"""
import csv, json, statistics, sys, traceback
from pathlib import Path
from collections import defaultdict
import numpy as np

PROJECT = Path("d:/Code/xiaoshuo")
TIER3_DIR = PROJECT / "data" / "golden" / "末世" / "tier3"
GOLDEN_CSV = PROJECT / "data" / "golden" / "末世" / "human_golden.csv"
GLM_JSON = TIER3_DIR / "tier3_glm_scores.json"
OUTPUT_FILE = PROJECT / "scripts" / "calib_result.txt"
ERROR_FILE = PROJECT / "scripts" / "calib_error.txt"

def _safe_float(v):
    try: return float(v)
    except: return None

try:
    lines = []
    def p(msg):
        lines.append(str(msg))

    # === Load Data ===
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

    golden_dedup = {}
    for d in golden_data:
        key = (d["book"], d["ch_num"])
        golden_dedup[key] = d
    golden_data = list(golden_dedup.values())
    p(f"Human golden: {len(golden_data)} chapters (deduped)")

    with open(GLM_JSON, 'r', encoding='utf-8') as f:
        glm_data = json.load(f)

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

    p(f"GLM Tier3: {len(glm_scores)} chapters")

    all_data = golden_data + glm_scores
    p(f"Total: {len(all_data)} chapters")

    book_counts = defaultdict(int)
    for d in all_data:
        book_counts[d["book"]] += 1
    for book, count in sorted(book_counts.items()):
        p(f"  {book}: {count}")

    # === Bias Analysis ===
    p(f"\n{'='*60}")
    p("Bias Analysis (T1 vs T2)")
    p(f"{'='*60}")

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
        p(f"\n--- {metric} ---")
        for model in ["t1", "t2"]:
            mae, bias, n = calc_bias(all_data, model, metric)
            if mae is not None:
                p(f"  {model.upper()}: MAE={mae:.2f}, Bias={bias:+.2f}, n={n}")

    # === Per-Book ===
    p(f"\n{'='*60}")
    p("Per-Book T1 Bias")
    p(f"{'='*60}")
    for book in sorted(book_counts.keys()):
        book_data = [d for d in all_data if d["book"] == book]
        mae_i, bias_i, n_i = calc_bias(book_data, "t1", "intensity")
        mae_r, bias_r, n_r = calc_bias(book_data, "t1", "retention")
        if mae_i:
            p(f"  {book}: I(MAE={mae_i:.1f},Bias={bias_i:+.1f}) R(MAE={mae_r:.1f},Bias={bias_r:+.1f}) n={n_i}")

    # === OLS ===
    p(f"\n{'='*60}")
    p("OLS Calibration")
    p(f"{'='*60}")

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
        p(f"\n  {metric_name}: human = {a:.2f} + {b:.3f} * T1")
        p(f"    n={n}, R2={r2:.3f}, r={r:.3f}")
        p(f"    T1=5 -> human={a+b*5:.1f}, T1=8 -> human={a+b*8:.1f}, T1=10 -> human={a+b*10:.1f}")

    # === LOOCV ===
    p(f"\n{'='*60}")
    p("LOOCV (Chapter-Level)")
    p(f"{'='*60}")

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
        p(f"  {metric_name}: n={n}, r={r:.3f}, MAE={mae:.2f}")

    # === Save calibration JSON ===
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
        pairs = [(d["t1_" + metric_name], d["human_" + metric_name])
                 for d in all_data
                 if d.get("t1_" + metric_name) is not None and d.get("human_" + metric_name) is not None]
        if len(pairs) >= 5:
            x = np.array([pp[0] for pp in pairs])
            y = np.array([pp[1] for pp in pairs])
            n = len(pairs)
            x_mean = np.mean(x)
            y_mean = np.mean(y)
            ss_xx = np.sum((x - x_mean) ** 2)
            ss_xy = np.sum((x - x_mean) * (y - y_mean))
            if ss_xx > 0:
                b = ss_xy / ss_xx
                a = y_mean - b * x_mean
                y_pred = a + b * x
                ss_res = np.sum((y - y_pred) ** 2)
                ss_tot = np.sum((y - y_mean) ** 2)
                r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
                r = np.corrcoef(x, y)[0, 1] if n > 2 else 0
                calibration["ols_params"][metric_name] = {
                    "intercept": round(a, 3), "slope": round(b, 3),
                    "r2": round(r2, 3), "r": round(r, 3), "n": n,
                }

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
        calibration["loocv"][metric_name] = {
            "n": n, "r": round(r, 3), "mae": round(mae, 2),
            "method": "Chapter-level LOOCV, T1 score vs human(Tier3) score",
        }

    out_path = PROJECT / "data" / "reports" / "末世" / "calibration" / "tier3_calibration.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(calibration, f, ensure_ascii=False, indent=2)

    # Summary
    p(f"\n{'='*60}")
    p("Summary")
    p(f"{'='*60}")
    p(f"Total calibration chapters: {len(all_data)} ({len(book_counts)} books)")
    for metric in ["intensity", "retention"]:
        t1 = calibration["t1_bias"].get(metric, {})
        t2 = calibration["t2_bias"].get(metric, {})
        ols = calibration["ols_params"].get(metric, {})
        loocv = calibration["loocv"].get(metric, {})
        p(f"\n  {metric}:")
        if t1:
            p(f"    T1: MAE={t1['mae']}, Bias={t1['bias']:+}")
        if t2:
            p(f"    T2: MAE={t2['mae']}, Bias={t2['bias']:+}")
        if ols:
            p(f"    OLS: human = {ols['intercept']} + {ols['slope']} * T1 (R2={ols['r2']}, r={ols['r']})")
        if loocv:
            p(f"    LOOCV: r={loocv['r']}, MAE={loocv['mae']} (n={loocv['n']})")

    # Write output
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))

except Exception as e:
    err = f"ERROR: {e}\n\n{traceback.format_exc()}"
    with open(ERROR_FILE, 'w', encoding='utf-8') as f:
        f.write(err)
