#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从零审计 human_golden.csv v2 (30章修正版)"""
import csv
import json
import math
from pathlib import Path
from collections import defaultdict

CSV_PATH = Path(r"d:\Code\xiaoshuo\data\processed\末世\scores\human_golden.csv")
OUT_PATH = Path(r"d:\Code\xiaoshuo\scripts\audit_v2_output.txt")

rows = []
with open(CSV_PATH, "r", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    for r in reader:
        if not r.get("book"):
            continue
        for k in ["wc","rule_intensity","llm_intensity","llm_retention","glm_intensity","glm_retention",
                   "human_intensity","human_retention","pacing","immersion","emotion","time_spent"]:
            try:
                if r.get(k):
                    r[k] = float(r[k])
            except (ValueError, TypeError):
                pass
        r["is_retest"] = r.get("is_retest","").strip().lower() == "true"
        rows.append(r)

out = []
def p(s=""):
    out.append(str(s))

p(f"总行数: {len(rows)} (含重测: {sum(1 for r in rows if r['is_retest'])})")
non_retest = [r for r in rows if not r["is_retest"]]
retest = [r for r in rows if r["is_retest"]]
p(f"非重测: {len(non_retest)}, 重测: {len(retest)}")

# === 1. 基础统计 ===
p("\n" + "="*60)
p("1. 基础统计 (非重测)")
p("="*60)

for dim in ["human_intensity", "human_retention", "llm_intensity", "glm_intensity", "rule_intensity"]:
    vals = [r[dim] for r in non_retest if dim in r and isinstance(r[dim], (int,float))]
    if vals:
        avg = sum(vals)/len(vals)
        mn, mx = min(vals), max(vals)
        p(f"  {dim:20s}: avg={avg:.2f} min={mn:.1f} max={mx:.1f} n={len(vals)}")

# === 2. 人机分歧分析 ===
p("\n" + "="*60)
p("2. 人机分歧分析 (非重测, |Δ|>=3.0)")
p("="*60)

for r in non_retest:
    hi = r.get("human_intensity", 0)
    li = r.get("llm_intensity", 0)
    gi = r.get("glm_intensity", 0)
    ri = r.get("rule_intensity", 0)
    if not all(isinstance(x, (int,float)) for x in [hi,li,gi,ri]):
        continue
    delta_llm = li - hi
    delta_glm = gi - hi
    max_delta = max(abs(delta_llm), abs(delta_glm))
    
    if max_delta >= 3.0:
        flag = "⚠️" if max_delta >= 4.0 else "·"
        p(f"  {flag} {r['book'][:4]} ch{r['ch_num']:>5} | H={hi:.1f} L={li:.1f} G={gi:.1f} R={ri:.1f} | dL={delta_llm:+.1f} dG={delta_glm:+.1f} | tags={r.get('tags','')}")

# === 3. 内部一致性检查 ===
p("\n" + "="*60)
p("3. 内部一致性检查 (非重测)")
p("="*60)

for r in non_retest:
    hi = r.get("human_intensity", 0)
    hr = r.get("human_retention", 0)
    pac = r.get("pacing", 0)
    imm = r.get("immersion", 0)
    emo = r.get("emotion", 0)
    tags = r.get("tags", "")
    gap = r.get("gap_reasons", "")
    cons = r.get("cons", "")
    
    if not all(isinstance(x, (int,float)) for x in [hi,hr,pac,imm,emo]):
        continue
    
    issues = []
    
    # 3a. 爽度与情绪极度不匹配
    if hi <= 3 and emo >= 6:
        issues.append(f"低爽({hi:.1f})但高情绪({emo:.1f})")
    if hi >= 7 and emo <= 2:
        issues.append(f"高爽({hi:.1f})但低情绪({emo:.1f})")
    
    # 3b. 爽度与留存严重倒挂
    if hi <= 3 and hr >= 7:
        issues.append(f"低爽({hi:.1f})但高留存({hr:.1f}) — 过渡章?")
    if hi >= 8 and hr <= 3:
        issues.append(f"高爽({hi:.1f})但低留存({hr:.1f}) — 可能读不下去?")
    
    # 3c. 代入与爽度差距过大
    if hi >= 7 and imm <= 3:
        issues.append(f"高爽({hi:.1f})但低代入({imm:.1f})")
    
    # 3d. 无爽点标签但给了中高分
    if "无爽点" in tags and hi >= 4:
        issues.append(f"标'无爽点'但爽度={hi:.1f}")
    
    # 3e. pros/cons与分数矛盾
    if cons and hi >= 7:
        issues.append(f"高爽({hi:.1f})但有cons: {cons[:30]}")
    
    # 3f. time_spent异常
    ts = r.get("time_spent", 0)
    if isinstance(ts, (int,float)):
        if ts < 30 and hi >= 6:
            issues.append(f"高分但仅{ts:.0f}秒 — 可能跳读")
        if ts > 800 and hi <= 3:
            issues.append(f"低分但{ts:.0f}秒 — 可能纠结/重读")
    
    if issues:
        p(f"  · {r['book'][:4]} ch{r['ch_num']:>5} | H={hi:.1f}/{hr:.1f} P={pac:.1f} I={imm:.1f} E={emo:.1f} | {'; '.join(issues)}")

# === 4. 书间对比 ===
p("\n" + "="*60)
p("4. 书间对比 (非重测)")
p("="*60)

books = defaultdict(list)
for r in non_retest:
    books[r["book"]].append(r)

for book, brs in books.items():
    hi_avg = sum(r["human_intensity"] for r in brs if isinstance(r.get("human_intensity"),(int,float))) / len(brs)
    hr_avg = sum(r["human_retention"] for r in brs if isinstance(r.get("human_retention"),(int,float))) / len(brs)
    li_avg = sum(r["llm_intensity"] for r in brs if isinstance(r.get("llm_intensity"),(int,float))) / len(brs)
    gi_avg = sum(r["glm_intensity"] for r in brs if isinstance(r.get("glm_intensity"),(int,float))) / len(brs)
    ri_avg = sum(r["rule_intensity"] for r in brs if isinstance(r.get("rule_intensity"),(int,float))) / len(brs)
    p(f"  {book} ({len(brs)}章): H_i={hi_avg:.2f} H_r={hr_avg:.2f} | L={li_avg:.2f} G={gi_avg:.2f} R={ri_avg:.2f}")

# === 5. 重测一致性 ===
p("\n" + "="*60)
p("5. 重测一致性")
p("="*60)

for rt in retest:
    book = rt["book"]
    ch_num = rt["ch_num"]
    orig = None
    for r in non_retest:
        if r["book"] == book and r["ch_num"] == ch_num:
            orig = r
            break
    
    if orig:
        hi_diff = abs(rt["human_intensity"] - orig["human_intensity"])
        hr_diff = abs(rt["human_retention"] - orig["human_retention"])
        status = "⚠️ 大差异" if (hi_diff > 2 or hr_diff > 2) else ("· 中等差异" if (hi_diff > 1 or hr_diff > 1) else "✓ 一致")
        p(f"  {book[:4]} ch{ch_num:>5} | Orig: {orig['human_intensity']:.1f}/{orig['human_retention']:.1f} -> Retest: {rt['human_intensity']:.1f}/{rt['human_retention']:.1f} | d={hi_diff:.1f}/{hr_diff:.1f} {status}")

# === 6. 规则引擎覆盖率 ===
p("\n" + "="*60)
p("6. 规则引擎覆盖率")
p("="*60)

total = len(non_retest)
if total > 0:
    rule_miss = sum(1 for r in non_retest if "rule_miss" in r.get("gap_reasons",""))
    rule_false = sum(1 for r in non_retest if "rule_false" in r.get("gap_reasons",""))
    p(f"  rule_miss: {rule_miss}/{total} ({rule_miss/total*100:.0f}%)")
    p(f"  rule_false: {rule_false}/{total} ({rule_false/total*100:.0f}%)")
    p(f"  规则正确命中(非miss非false): {total - rule_miss - rule_false}/{total}")

# === 7. LLM/GLM偏差方向 ===
p("\n" + "="*60)
p("7. LLM/GLM 偏差方向")
p("="*60)

llm_deltas = [r["llm_intensity"] - r["human_intensity"] for r in non_retest if isinstance(r.get("llm_intensity"),(int,float)) and isinstance(r.get("human_intensity"),(int,float))]
glm_deltas = [r["glm_intensity"] - r["human_intensity"] for r in non_retest if isinstance(r.get("glm_intensity"),(int,float)) and isinstance(r.get("human_intensity"),(int,float))]

if llm_deltas:
    llm_avg = sum(llm_deltas)/len(llm_deltas)
    llm_mae = sum(abs(d) for d in llm_deltas)/len(llm_deltas)
    p(f"  LLM: avg_bias={llm_avg:+.2f} MAE={llm_mae:.2f} n={len(llm_deltas)}")
if glm_deltas:
    glm_avg = sum(glm_deltas)/len(glm_deltas)
    glm_mae = sum(abs(d) for d in glm_deltas)/len(glm_deltas)
    p(f"  GLM: avg_bias={glm_avg:+.2f} MAE={glm_mae:.2f} n={len(glm_deltas)}")

# === 8. 离群值检测 ===
p("\n" + "="*60)
p("8. 离群值检测 (Z-score > 1.5)")
p("="*60)

all_hi = [r["human_intensity"] for r in non_retest if isinstance(r.get("human_intensity"),(int,float))]
if all_hi:
    mean_hi = sum(all_hi)/len(all_hi)
    std_hi = math.sqrt(sum((x - mean_hi)**2 for x in all_hi) / len(all_hi))
    p(f"  全局: mean={mean_hi:.2f} std={std_hi:.2f}")
    
    for r in non_retest:
        hi = r.get("human_intensity",0)
        if not isinstance(hi, (int,float)):
            continue
        z = (hi - mean_hi) / std_hi if std_hi > 0 else 0
        if abs(z) > 1.5:
            direction = "异常高" if z > 0 else "异常低"
            p(f"  · {r['book'][:4]} ch{r['ch_num']:>5} | H={hi:.1f} Z={z:+.2f} ({direction}) | tags={r.get('tags','')}")

p("\n" + "="*60)
p("审计完成")
p("="*60)

with open(OUT_PATH, "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print(f"Done: {OUT_PATH}")
