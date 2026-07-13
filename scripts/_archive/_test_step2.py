#!/usr/bin/env python
# -*- coding: utf-8 -*-
import csv, json, statistics
from pathlib import Path
from collections import defaultdict
import numpy as np

PROJECT = Path("d:/Code/xiaoshuo")
TIER3 = PROJECT / "data" / "golden" / "\u672b\u4e16" / "tier3"
GCSV = PROJECT / "data" / "golden" / "\u672b\u4e16" / "human_golden.csv"
GJSON = TIER3 / "tier3_glm_scores.json"
OUT = PROJECT / "scripts" / "_test_step2_out.txt"

L = []
def w(m): L.append(str(m))

def sf(v):
    try: return float(v)
    except: return None

# Load golden
gd = []
with open(GCSV, 'r', encoding='utf-8-sig') as f:
    for r in csv.DictReader(f):
        gd.append({"book": r.get("book",""), "ch_num": int(r.get("ch_num",0)),
            "t1i": sf(r.get("llm_intensity")), "t1r": sf(r.get("llm_retention")),
            "hi": sf(r.get("human_intensity")), "hr": sf(r.get("human_retention"))})

dd = {}
for d in gd:
    dd[(d["book"], d["ch_num"])] = d
gd = list(dd.values())
w(f"Golden: {len(gd)}")

# Load GLM
with open(GJSON, 'r', encoding='utf-8') as f:
    gj = json.load(f)

gs = []
for book, chs in gj["scores"].items():
    pc = TIER3 / f"{book}_tier3_plan.csv"
    plan = {}
    if pc.exists():
        with open(pc, 'r', encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                plan[int(r["ch_num"])] = r
    for ch in chs:
        cn = ch["ch_num"]
        pr = plan.get(cn, {})
        gs.append({"book": book, "ch_num": cn,
            "t1i": sf(pr.get("ai_intensity")), "t1r": sf(pr.get("ai_retention")),
            "t2i": sf(pr.get("t2_intensity")), "t2r": sf(pr.get("t2_retention")),
            "hi": float(ch["intensity"]), "hr": float(ch["retention"])})

w(f"GLM: {len(gs)}")

ad = gd + gs
w(f"Total: {len(ad)}")

# Bias
def cb(data, mk, mt):
    diffs = []
    for d in data:
        mv = d.get(f"{mk}{mt}")
        hv = d.get(f"h{mt}")
        if mv is not None and hv is not None:
            diffs.append(mv - hv)
    if not diffs:
        return None, None, 0
    return statistics.mean([abs(x) for x in diffs]), statistics.mean(diffs), len(diffs)

w(f"\nBias:")
for mt in ["i", "r"]:
    for mk in ["t1", "t2"]:
        mae, bias, n = cb(ad, mk, mt)
        if mae is not None:
            w(f"  {mk}.{mt}: MAE={mae:.2f}, Bias={bias:+.2f}, n={n}")

# OLS
w(f"\nOLS:")
cd = []
for d in ad:
    if d.get("t1i") is not None and d.get("hi") is not None:
        cd.append((d["t1i"], d["hi"], "i"))
    if d.get("t1r") is not None and d.get("hr") is not None:
        cd.append((d["t1r"], d["hr"], "r"))

for mn in ["i", "r"]:
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
    syy = np.sum((y - ym) ** 2)
    r = (sxy / np.sqrt(sxx * syy)) if (sxx > 0 and syy > 0) else 0
    w(f"  {mn}: a={a:.2f}, b={b:.3f}, R2={r2:.3f}, r={r:.3f}, n={n}")

# LOOCV
w(f"\nLOOCV:")
for mn in ["i", "r"]:
    pairs = [(d[f"t1{mn}"], d[f"h{mn}"]) for d in ad
             if d.get(f"t1{mn}") is not None and d.get(f"h{mn}") is not None]
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
    sp = np.sum((preds - np.mean(preds)) ** 2)
    sy = np.sum((y - np.mean(y)) ** 2)
    spxy = np.sum((preds - np.mean(preds)) * (y - np.mean(y)))
    if sp > 0 and sy > 0:
        r = spxy / np.sqrt(sp * sy)
    else:
        r = 0
    mae = np.mean(np.abs(preds - y))
    w(f"  {mn}: n={n}, r={r:.3f}, MAE={mae:.2f}")

# Save
cal = {
    "total": len(ad),
    "t1_bias": {},
    "t2_bias": {},
    "ols": {},
    "loocv": {},
}
for mt in ["i", "r"]:
    for mk in ["t1", "t2"]:
        mae, bias, n = cb(ad, mk, mt)
        if mae:
            cal[f"{mk}_bias"][mt] = {"mae": round(mae,2), "bias": round(bias,2), "n": n}

# Add OLS results
for mn in ["i", "r"]:
    pairs = [(x[0], x[1]) for x in cd if x[2] == mn]
    if len(pairs) < 5:
        continue
    x2 = np.array([p[0] for p in pairs])
    y2 = np.array([p[1] for p in pairs])
    n2 = len(pairs)
    xm2 = np.mean(x2)
    ym2 = np.mean(y2)
    sxx2 = np.sum((x2 - xm2) ** 2)
    sxy2 = np.sum((x2 - xm2) * (y2 - ym2))
    if sxx2 == 0:
        continue
    b2 = sxy2 / sxx2
    a2 = ym2 - b2 * xm2
    syy2 = np.sum((y2 - ym2) ** 2)
    r2_val = 1 - np.sum((y2 - (a2 + b2 * x2)) ** 2) / syy2 if syy2 > 0 else 0
    r_val = (sxy2 / np.sqrt(sxx2 * syy2)) if (sxx2 > 0 and syy2 > 0) else 0
    cal["ols"][mn] = {"intercept": round(a2,3), "slope": round(b2,3), "r2": round(r2_val,3), "r": round(r_val,3), "n": n2}

# Add LOOCV results
for mn in ["i", "r"]:
    pairs2 = [(d[f"t1{mn}"], d[f"h{mn}"]) for d in ad
              if d.get(f"t1{mn}") is not None and d.get(f"h{mn}") is not None]
    if len(pairs2) < 10:
        continue
    x3 = np.array([p[0] for p in pairs2])
    y3 = np.array([p[1] for p in pairs2])
    n3 = len(pairs2)
    preds3 = []
    for i in range(n3):
        xt = np.delete(x3, i)
        yt = np.delete(y3, i)
        xm3 = np.mean(xt)
        ym3 = np.mean(yt)
        sxx3 = np.sum((xt - xm3) ** 2)
        sxy3 = np.sum((xt - xm3) * (yt - ym3))
        if sxx3 == 0:
            preds3.append(ym3)
        else:
            preds3.append(ym3 + (sxy3 / sxx3) * (x3[i] - xm3))
    preds3 = np.array(preds3)
    sp3 = np.sum((preds3 - np.mean(preds3)) ** 2)
    sy3 = np.sum((y3 - np.mean(y3)) ** 2)
    spxy3 = np.sum((preds3 - np.mean(preds3)) * (y3 - np.mean(y3)))
    r3 = spxy3 / np.sqrt(sp3 * sy3) if (sp3 > 0 and sy3 > 0) else 0
    mae3 = np.mean(np.abs(preds3 - y3))
    cal["loocv"][mn] = {"n": n3, "r": round(r3,3), "mae": round(mae3,2)}

jp = PROJECT / "data" / "reports" / "\u672b\u4e16" / "calibration" / "tier3_calibration.json"
jp.parent.mkdir(parents=True, exist_ok=True)
with open(jp, 'w', encoding='utf-8') as f:
    json.dump(cal, f, ensure_ascii=False, indent=2)

w(f"\nJSON saved: {jp}")
w("DONE!")

with open(OUT, 'w', encoding='utf-8') as f:
    f.write("\n".join(L))
