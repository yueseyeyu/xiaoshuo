#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Tier3 calibration - writes output to file only, no print"""
import csv, json, statistics
from pathlib import Path
from collections import defaultdict
import numpy as np

PROJECT = Path("d:/Code/xiaoshuo")
TIER3_DIR = PROJECT / "data" / "golden" / "M-shi" / "tier3"  # avoid Chinese in path
TIER3_DIR_REAL = PROJECT / "data" / "golden" / "\u672b\u4e16" / "tier3"
GOLDEN_CSV = PROJECT / "data" / "golden" / "\u672b\u4e16" / "human_golden.csv"
GLM_JSON = TIER3_DIR_REAL / "tier3_glm_scores.json"
OUT_TXT = PROJECT / "scripts" / "calib_result.txt"
OUT_JSON = PROJECT / "data" / "reports" / "\u672b\u4e16" / "calibration" / "tier3_calibration.json"

L = []
def w(msg):
    L.append(str(msg))

def sf(v):
    try: return float(v)
    except: return None

# 1. Load golden
golden_data = []
with open(GOLDEN_CSV, 'r', encoding='utf-8-sig') as f:
    for row in csv.DictReader(f):
        golden_data.append({
            "book": row.get("book", ""),
            "ch_num": int(row.get("ch_num", 0)),
            "t1_intensity": sf(row.get("llm_intensity")),
            "t1_retention": sf(row.get("llm_retention")),
            "human_intensity": sf(row.get("human_intensity")),
            "human_retention": sf(row.get("human_retention")),
            "source": "human_golden",
        })

gd = {}
for d in golden_data:
    gd[(d["book"], d["ch_num"])] = d
golden_data = list(gd.values())
w(f"Human golden: {len(golden_data)} chapters")

# 2. Load GLM Tier3
with open(GLM_JSON, 'r', encoding='utf-8') as f:
    gdata = json.load(f)

glm_scores = []
for book, chapters in gdata["scores"].items():
    pcsv = TIER3_DIR_REAL / f"{book}_tier3_plan.csv"
    plan = {}
    if pcsv.exists():
        with open(pcsv, 'r', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                plan[int(row["ch_num"])] = row
    for ch in chapters:
        cn = ch["ch_num"]
        pr = plan.get(cn, {})
        glm_scores.append({
            "book": book, "ch_num": cn,
            "t1_intensity": sf(pr.get("ai_intensity")),
            "t1_retention": sf(pr.get("ai_retention")),
            "t2_intensity": sf(pr.get("t2_intensity")),
            "t2_retention": sf(pr.get("t2_retention")),
            "human_intensity": float(ch["intensity"]),
            "human_retention": float(ch["retention"]),
            "source": "glm_tier3",
        })

w(f"GLM Tier3: {len(glm_scores)} chapters")

all_data = golden_data + glm_scores
w(f"Total: {len(all_data)} chapters")

bc = defaultdict(int)
for d in all_data:
    bc[d["book"]] += 1
for book, count in sorted(bc.items()):
    w(f"  {book}: {count}")

# 3. Bias analysis
def cb(data, mk, mt):
    diffs = []
    for d in data:
        mv = d.get(f"{mk}_{mt}")
        hv = d.get(f"human_{mt}")
        if mv is not None and hv is not None:
            diffs.append(mv - hv)
    if not diffs:
        return None, None, 0
    return statistics.mean([abs(x) for x in diffs]), statistics.mean(diffs), len(diffs)

w(f"\n{'='*60}")
w("Bias Analysis")
w(f"{'='*60}")
for metric in ["intensity", "retention"]:
    w(f"\n--- {metric} ---")
    for model in ["t1", "t2"]:
        mae, bias, n = cb(all_data, model, metric)
        if mae is not None:
            w(f"  {model.upper()}: MAE={mae:.2f}, Bias={bias:+.2f}, n={n}")

w(f"\n--- Per-Book T1 ---")
for book in sorted(bc.keys()):
    bd = [d for d in all_data if d["book"] == book]
    mi, bi, ni = cb(bd, "t1", "intensity")
    mr, br, nr = cb(bd, "t1", "retention")
    if mi:
        w(f"  {book}: I(MAE={mi:.1f},Bias={bi:+.1f}) R(MAE={mr:.1f},Bias={br:+.1f}) n={ni}")

# 4. OLS
w(f"\n{'='*60}")
w("OLS Calibration")
w(f"{'='*60}")

cd = []
for d in all_data:
    ti = d.get("t1_intensity")
    tr = d.get("t1_retention")
    hi = d.get("human_intensity")
    hr = d.get("human_retention")
    if ti is not None and hi is not None:
        cd.append((ti, hi, "intensity"))
    if tr is not None and hr is not None:
        cd.append((tr, hr, "retention"))

ols = {}
for mn in ["intensity", "retention"]:
    pairs = [(x[0], x[1]) for x in cd if x[2] == mn]
    if len(pairs) < 5:
        continue
    x = np.array([p[0] for p in pairs])
    y = np.array([p[1] for p in pairs])
    n = len(pairs)
    xm = np.mean(x)
    ym = np.mean(y)
    sxx = np.sum((x - xm) ** 2)
    sxy = np.sum((x - xm) * (y - ym))
    if sxx == 0:
        continue
    b = sxy / sxx
    a = ym - b * xm
    yp = a + b * x
    sr = np.sum((y - yp) ** 2)
    st = np.sum((y - ym) ** 2)
    r2 = 1 - sr / st if st > 0 else 0
    r = np.corrcoef(x, y)[0, 1] if n > 2 else 0
    w(f"\n  {mn}: human = {a:.2f} + {b:.3f} * T1")
    w(f"    n={n}, R2={r2:.3f}, r={r:.3f}")
    w(f"    T1=5 -> {a+b*5:.1f}, T1=8 -> {a+b*8:.1f}, T1=10 -> {a+b*10:.1f}")
    ols[mn] = {"a": a, "b": b, "r2": r2, "r": r, "n": n}

# 5. LOOCV
w(f"\n{'='*60}")
w("LOOCV (Chapter-Level)")
w(f"{'='*60}")

loo = {}
for mn in ["intensity", "retention"]:
    pairs = [(d["t1_" + mn], d["human_" + mn])
             for d in all_data
             if d.get("t1_" + mn) is not None and d.get("human_" + mn) is not None]
    if len(pairs) < 10:
        continue
    x = np.array([p[0] for p in pairs])
    y = np.array([p[1] for p in pairs])
    n = len(pairs)
    preds = []
    for i in range(n):
        xt = np.delete(x, i)
        yt = np.delete(y, i)
        xm = np.mean(xt)
        ym = np.mean(yt)
        sxx = np.sum((xt - xm) ** 2)
        sxy = np.sum((xt - xm) * (yt - ym))
        if sxx == 0:
            preds.append(ym)
        else:
            preds.append(ym + (sxy / sxx) * (x[i] - xm))
    preds = np.array(preds)
    if np.std(preds) > 0 and np.std(y) > 0:
        r = np.corrcoef(preds, y)[0, 1]
    else:
        r = 0
    mae = np.mean(np.abs(preds - y))
    w(f"  {mn}: n={n}, r={r:.3f}, MAE={mae:.2f}")
    loo[mn] = {"n": n, "r": round(r, 3), "mae": round(mae, 2)}

# 6. Save JSON
cal = {
    "timestamp": "2026-07-13T16:00:00",
    "total_chapters": len(all_data),
    "books": dict(bc),
    "t1_bias": {},
    "t2_bias": {},
    "ols_params": {},
    "loocv": {},
}
for metric in ["intensity", "retention"]:
    mae, bias, n = cb(all_data, "t1", metric)
    if mae:
        cal["t1_bias"][metric] = {"mae": round(mae, 2), "bias": round(bias, 2), "n": n}
    mae, bias, n = cb(all_data, "t2", metric)
    if mae:
        cal["t2_bias"][metric] = {"mae": round(mae, 2), "bias": round(bias, 2), "n": n}

for mn in ["intensity", "retention"]:
    if mn in ols:
        r = ols[mn]
        cal["ols_params"][mn] = {
            "intercept": round(r["a"], 3), "slope": round(r["b"], 3),
            "r2": round(r["r2"], 3), "r": round(r["r"], 3), "n": r["n"],
        }

for mn in ["intensity", "retention"]:
    if mn in loo:
        cal["loocv"][mn] = {
            "n": loo[mn]["n"], "r": loo[mn]["r"], "mae": loo[mn]["mae"],
            "method": "Chapter-level LOOCV, T1 score vs human(Tier3) score",
        }

OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
with open(OUT_JSON, 'w', encoding='utf-8') as f:
    json.dump(cal, f, ensure_ascii=False, indent=2)

# 7. Summary
w(f"\n{'='*60}")
w("SUMMARY")
w(f"{'='*60}")
w(f"Total: {len(all_data)} chapters, {len(bc)} books")
for metric in ["intensity", "retention"]:
    t1 = cal["t1_bias"].get(metric, {})
    t2 = cal["t2_bias"].get(metric, {})
    o = cal["ols_params"].get(metric, {})
    lc = cal["loocv"].get(metric, {})
    w(f"\n  {metric}:")
    if t1:
        w(f"    T1: MAE={t1['mae']}, Bias={t1['bias']:+}")
    if t2:
        w(f"    T2: MAE={t2['mae']}, Bias={t2['bias']:+}")
    if o:
        w(f"    OLS: human = {o['intercept']} + {o['slope']} * T1 (R2={o['r2']}, r={o['r']})")
    if lc:
        w(f"    LOOCV: r={lc['r']}, MAE={lc['mae']} (n={lc['n']})")

# Write output file
with open(OUT_TXT, 'w', encoding='utf-8') as f:
    f.write("\n".join(L))
