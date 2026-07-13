#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Tier1全量完成后内容抽查 - 检查评分分布和合理性"""
import sys, os, json, random
from pathlib import Path
from collections import defaultdict
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.dirname(__file__))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

import ai_annotate; ai_annotate.BATCH_SIZE = 2
from ai_annotate import get_book_batch_dir

PROJECT_ROOT = Path(__file__).parent.parent
SCORES_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "scores" / "ai_annotate_batches"

DIMS = ["ai_intensity", "ai_conflict", "ai_emotion", "ai_pace", "ai_hook", "ai_retention"]

def safe_float(v, default=0.0):
    try:
        return float(v)
    except (ValueError, TypeError):
        return default

all_scores = []
per_book_stats = []
type_issues = []

for book in sorted(SCORES_DIR.iterdir()):
    if not book.is_dir() or book.name == "single":
        continue
    
    bdir = get_book_batch_dir(book.name)
    book_scores = []
    
    for sf in sorted(bdir.glob("scores_new_*.json")):
        with open(sf, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for row in data:
            # 检查类型问题
            for dim in DIMS:
                v = row.get(dim)
                if v is not None and not isinstance(v, (int, float)):
                    type_issues.append(f"{book.name}/{sf.name} ch{row.get('ch_num')} {dim}={v!r} (type={type(v).__name__})")
            book_scores.append(row)
            all_scores.append(row)
    
    if book_scores:
        means = {}
        for dim in DIMS:
            vals = [safe_float(r.get(dim, 0)) for r in book_scores]
            means[dim] = round(sum(vals) / len(vals), 2)
        per_book_stats.append((book.name, len(book_scores), means))

# 0. 类型问题
print("=" * 80)
print("数据类型检查")
print("=" * 80)
if type_issues:
    print(f"  ⚠️ 发现 {len(type_issues)} 个类型问题:")
    for t in type_issues[:20]:
        print(f"    {t}")
else:
    print("  ✅ 所有评分维度均为数值类型")

# 1. 全局分布
print("\n" + "=" * 80)
print(f"全局评分分布 ({len(all_scores)}章)")
print("=" * 80)
for dim in DIMS:
    vals = [safe_float(r.get(dim, 0)) for r in all_scores]
    avg = sum(vals) / len(vals)
    mn = min(vals)
    mx = max(vals)
    bins = [0, 0]
    for v in vals:
        if v < 4: bins[0] += 1
        if v >= 7: bins[1] += 1
    print(f"  {dim:20s}: avg={avg:.2f}  min={mn:.1f}  max={mx:.1f}  低分(<4)={bins[0]}  高分(≥7)={bins[1]}")

# 2. 每本书的均值
print("\n" + "=" * 80)
print("每本书评分均值 (按强度降序)")
print("=" * 80)
print(f"  {'书名':30s} {'章数':>5s}  {'强度':>6s} {'冲突':>6s} {'情感':>6s} {'节奏':>6s} {'悬念':>6s} {'留存':>6s}")
print("-" * 95)
for name, n, means in sorted(per_book_stats, key=lambda x: x[2]['ai_intensity'], reverse=True):
    print(f"  {name:30s} {n:>5d}  {means['ai_intensity']:>6.2f} {means['ai_conflict']:>6.2f} {means['ai_emotion']:>6.2f} {means['ai_pace']:>6.2f} {means['ai_hook']:>6.2f} {means['ai_retention']:>6.2f}")

# 3. 随机抽5个章节看ai_analysis内容
print("\n" + "=" * 80)
print("随机抽查5个章节的ai_analysis内容")
print("=" * 80)
random.seed(42)
samples = random.sample(all_scores, 5)
for s in samples:
    analysis = str(s.get('ai_analysis', ''))
    print(f"\n  ch{s.get('ch_num')}: intensity={s.get('ai_intensity')} hook={s.get('ai_hook')} retention={s.get('ai_retention')}")
    print(f"  分析: {analysis[:200]}...")

# 4. 检查是否有空analysis
empty = sum(1 for r in all_scores if not str(r.get('ai_analysis', '')).strip())
print(f"\n空ai_analysis数量: {empty}/{len(all_scores)}")

# 5. 检查所有分数在1-10范围
out_of_range = 0
for r in all_scores:
    for dim in DIMS:
        v = safe_float(r.get(dim, 0))
        if v < 1 or v > 10:
            out_of_range += 1
print(f"超出[1,10]范围的分数: {out_of_range}")
