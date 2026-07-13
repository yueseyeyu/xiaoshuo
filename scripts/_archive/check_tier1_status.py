#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""检查Tier1 AI评分进度"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

PROJECT = Path(__file__).parent.parent
INDEX = PROJECT / "data" / "raw" / "novel_index.json"
SCORES_DIR = PROJECT / "data" / "processed" / "末世" / "scores"

with open(INDEX, 'r', encoding='utf-8') as f:
    idx = json.load(f)

novels = idx['genres']['末世']['novels']
print(f"末世类共 {len(novels)} 本")
print()

# 检查每本书的Tier1评分状态
for i, n in enumerate(novels, 1):
    fname = n['file']
    # 去掉.txt
    stem = fname.replace('.txt', '')
    
    # 检查 ai_full.csv
    ai_csv = SCORES_DIR / f"{stem}_ai_full.csv"
    # 检查 batch 目录
    batch_dir = SCORES_DIR / "ai_annotate_batches" / stem
    
    scored = 0
    if batch_dir.exists():
        for sf in batch_dir.glob("scores_*.json"):
            try:
                with open(sf, 'r', encoding='utf-8') as f:
                    scored += len(json.load(f))
            except:
                pass
    
    merged = 0
    if ai_csv.exists():
        import csv
        with open(ai_csv, 'r', encoding='utf-8-sig') as f:
            merged = sum(1 for _ in csv.DictReader(f))
    
    status = "✓完成" if merged > 0 else (f"部分({scored}章)" if scored > 0 else "✗未开始")
    print(f"  {i:2d}. {stem[:50]}")
    print(f"      Tier1: {status}  (batch={scored}, merged={merged})")
