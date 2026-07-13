#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""估算Tier1 10%采样的工作量"""
import json
import sys
import math
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

PROJECT = Path(__file__).parent.parent
INDEX = PROJECT / "data" / "raw" / "novel_index.json"
RHYTHM_DIR = PROJECT / "data" / "processed" / "末世" / "rhythm"

# v8.8 quality tiers
S_BOOKS = ["地球游戏场", "末世大回炉", "异兽迷城", "黑暗血时代", "第一序列", "长夜余火", "末日乐园"]

with open(INDEX, 'r', encoding='utf-8') as f:
    idx = json.load(f)

novels = idx['genres']['末世']['novels']
print("=" * 70)
print("Tier1 10%分层采样工作量估算")
print("=" * 70)

total_sampled = 0
for n in novels:
    fname = n['file']
    # 从rhythm CSV获取章节数
    csv_name = n.get('rhythm_csv', '')
    csv_path = RHYTHM_DIR / csv_name
    total_ch = 0
    if csv_path.exists():
        import csv
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            total_ch = sum(1 for _ in csv.DictReader(f))
    
    # 10% stratified sampling
    sampled = max(5, math.ceil(total_ch * 0.10))  # 至少5章
    batches = math.ceil(sampled / 2)  # 每批2章
    
    # 短名
    short = fname.replace('.txt', '')
    if short.startswith('《'):
        import re
        m = re.search(r'《(.+?)》', short)
        short = m.group(1) if m else short
    
    tier = "S" if short in S_BOOKS else "?"
    
    print(f"  {short[:30]:30s} | {total_ch:5d}ch | 10%={sampled:3d}ch | {batches:3d}批 | {tier}")
    total_sampled += sampled

print(f"\n总计: {total_sampled}章待评分, {math.ceil(total_sampled/2)}批")
print(f"按S级优先: 7本S级约 {sum(max(5, math.ceil(790*0.1)) for _ in range(7))} 章")
