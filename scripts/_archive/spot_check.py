#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""抽查GLM评分内容质量"""
import sys, os, json
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.dirname(__file__))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

import ai_annotate; ai_annotate.BATCH_SIZE = 2
from ai_annotate import get_book_batch_dir

PROJECT_ROOT = Path(__file__).parent.parent

# 抽查第九特区前3批和最新3批
book = "第九特区"
bdir = get_book_batch_dir(book)
score_files = sorted(bdir.glob("scores_*.json"))
print(f"第九特区: {len(score_files)}个评分文件")
print(f"批次范围: {score_files[0].name} ~ {score_files[-1].name}")
print()

# 抽查第1批、中间批、最后批
check_indices = [0, 1, len(score_files)//2, -2, -1]
for idx in check_indices:
    sf = score_files[idx]
    with open(sf, 'r', encoding='utf-8') as f:
        scores = json.load(f)
    # 读取对应的new文件
    batch_num = int(sf.stem.split("_")[-1])
    nf = bdir / f"new_{batch_num:02d}.json"
    with open(nf, 'r', encoding='utf-8') as f:
        new_data = json.load(f)

    print(f"--- {sf.name} ---")
    for i, (s, n) in enumerate(zip(scores, new_data)):
        text_preview = n.get('text', '')[:80]
        print(f"  ch{s['ch_num']} [{s['stratum']}] {s['wc']}字")
        print(f"    intensity={s['ai_intensity']} conflict={s['ai_conflict']} emotion={s['ai_emotion']} pace={s['ai_pace']} hook={s['ai_hook']} retention={s['ai_retention']}")
        print(f"    analysis: {s['ai_analysis']}")
        print(f"    原文开头: {text_preview}...")
        print()

# 统计评分分布
all_scores = []
for sf in score_files:
    with open(sf, 'r', encoding='utf-8') as f:
        all_scores.extend(json.load(f))

intensities = [s['ai_intensity'] for s in all_scores]
retentions = [s['ai_retention'] for s in all_scores]
emotions = [s['ai_emotion'] for s in all_scores]

print(f"\n=== 第九特区评分分布 ({len(all_scores)}章) ===")
print(f"intensity: min={min(intensities)} max={max(intensities)} avg={sum(intensities)/len(intensities):.1f}")
print(f"retention: min={min(retentions)} max={max(retentions)} avg={sum(retentions)/len(retentions):.1f}")
from collections import Counter
print(f"emotion分布: {dict(Counter(emotions))}")
print(f"intensity分布: {dict(sorted(Counter(intensities).items()))}")
