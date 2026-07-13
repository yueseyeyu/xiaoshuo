#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""检查废土崛起的评分缺口"""
import sys, os, json, csv, math, re
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "novels" / "末世"
SCORES_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "scores"
BATCH_DIR = SCORES_DIR / "ai_annotate_batches"

STRATA = [
    {"name": "Opening", "start": 0.00, "end": 0.03, "ratio": 0.03},
    {"name": "Rising",  "start": 0.03, "end": 0.30, "ratio": 0.27},
    {"name": "Mid",     "start": 0.30, "end": 0.60, "ratio": 0.30},
    {"name": "Climax",  "start": 0.60, "end": 0.90, "ratio": 0.30},
    {"name": "Ending",  "start": 0.90, "end": 1.00, "ratio": 0.10},
]
SAMPLE_RATE = 0.10

RERUN_CHAPTERS = [1, 193, 385, 577, 648, 769, 788, 868, 961, 1008, 1153, 1297, 1345, 1367, 1729, 1794, 1862]
KEEP_CHAPTERS = [20, 39, 58, 107, 166, 225, 284, 343, 402, 461, 520, 579, 718, 938, 1078, 1158, 1227, 1447, 1517, 1537, 1587, 1657, 1737]

# 提取章节
from xiaoshuo.pipeline.rhythm.chapter_parser import extract_chapters

txt_path = RAW_DIR / "废土崛起.txt"
if not txt_path.exists():
    # 尝试其他文件名
    for f in RAW_DIR.glob("*废土*"):
        print(f"找到文件: {f.name}")
        txt_path = f
        break

print(f"文件: {txt_path}")
chapters = extract_chapters(str(txt_path))
print(f"总章节: {len(chapters)}")

# 分层采样
sorted_chs = sorted(chapters, key=lambda c: c["num"])
all_nums = [c["num"] for c in sorted_chs]

sampled = []
for stratum in STRATA:
    start_idx = int(len(chapters) * stratum["start"])
    end_idx = int(len(chapters) * stratum["end"])
    if end_idx <= start_idx:
        continue
    stratum_chs = all_nums[start_idx:end_idx]
    n_sample = max(1, math.ceil(len(stratum_chs) * SAMPLE_RATE))
    if len(stratum_chs) <= n_sample:
        selected = stratum_chs
    else:
        step = len(stratum_chs) / n_sample
        indices = [int(i * step) for i in range(n_sample)]
        indices = sorted(set(min(i, len(stratum_chs)-1) for i in indices))
        selected = [stratum_chs[i] for i in indices]
    for ch_num in selected:
        sampled.append((ch_num, stratum["name"]))
    print(f"  {stratum['name']}: {len(stratum_chs)}ch → sampled {len(selected)}")

sampled_chs = set(ch for ch, _ in sampled)
print(f"\n10%采样: {len(sampled_chs)}章")

# 检查已评分
batch_dir = BATCH_DIR  # 废土崛起用根目录
scored_chs = set()
for sf in sorted(batch_dir.glob("scores_*.json")):
    try:
        with open(sf, 'r', encoding='utf-8') as f:
            for row in json.load(f):
                if 'ch_num' in row:
                    scored_chs.add(int(row['ch_num']))
    except:
        pass

print(f"已评分(scores_*.json): {len(scored_chs)}章")

# 检查CSV
csv_path = SCORES_DIR / "废土崛起_ai_full.csv"
csv_chs = set()
if csv_path.exists():
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            csv_chs.add(int(row['ch_num']))
    print(f"CSV合并: {len(csv_chs)}章")

# 检查pilot CSV
pilot_csv = SCORES_DIR / "废土崛起_ai.csv"
pilot_chs = set()
if pilot_csv.exists():
    with open(pilot_csv, 'r', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            pilot_chs.add(int(row["ch_num"]))
    print(f"Pilot CSV: {len(pilot_chs)}章")

# 分析缺口
missing_from_sample = sampled_chs - scored_chs
missing_from_csv = sampled_chs - csv_chs
extra_in_scores = scored_chs - sampled_chs

print(f"\n=== 缺口分析 ===")
print(f"10%采样需要: {len(sampled_chs)}章")
print(f"已评分: {len(scored_chs)}章")
print(f"CSV合并: {len(csv_chs)}章")
print(f"采样中未评分: {len(missing_from_sample)}章")
print(f"采样中未进CSV: {len(missing_from_csv)}章")
print(f"评分中非采样: {len(extra_in_scores)}章")

if missing_from_sample:
    print(f"\n缺失章节({len(missing_from_sample)}):")
    stratum_map = {ch: s for ch, s in sampled}
    for ch in sorted(missing_from_sample):
        in_pilot = "pilot" if ch in pilot_chs else ""
        in_keep = "KEEP" if ch in KEEP_CHAPTERS else ""
        in_rerun = "RERUN" if ch in RERUN_CHAPTERS else ""
        print(f"  ch{ch:>5} [{stratum_map.get(ch, '?')}] {in_pilot} {in_keep} {in_rerun}")

# 检查KEEP_CHAPTERS是否都在采样中
keep_not_in_sample = set(KEEP_CHAPTERS) - sampled_chs
if keep_not_in_sample:
    print(f"\nKEEP_CHAPTERS不在10%采样中: {sorted(keep_not_in_sample)}")

# 检查RERUN_CHAPTERS是否都已评分
rerun_not_scored = set(RERUN_CHAPTERS) - scored_chs
if rerun_not_scored:
    print(f"\nRERUN_CHAPTERS未评分: {sorted(rerun_not_scored)}")
else:
    print(f"\nRERUN_CHAPTERS: 全部已评分 ✓")
