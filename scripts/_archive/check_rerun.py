#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Check which RERUN_CHAPTERS are in the 10% sample."""
import json, sys, math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from xiaoshuo.pipeline.rhythm_analyzer import extract_chapters

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

RERUN = [1, 193, 385, 577, 648, 769, 788, 868, 961, 1008, 1153, 1297, 1345, 1367, 1729, 1794, 1862]

# Check stage1 JSON
stage1 = json.load(open("scripts/stage1_10pct_chapters.json", "r", encoding="utf-8"))
ft_stage1 = {d["ch_num"] for d in stage1 if d["book"] == "废土崛起"}
print(f"stage1 JSON: {len(ft_stage1)} 废土崛起 chapters")

in_stage1 = [ch for ch in RERUN if ch in ft_stage1]
not_in_stage1 = [ch for ch in RERUN if ch not in ft_stage1]
print(f"RERUN in stage1: {len(in_stage1)} — {in_stage1}")
print(f"RERUN NOT in stage1: {len(not_in_stage1)} — {not_in_stage1}")

# Check new 10% sample
txt_path = "data/raw/novels/末世/《废土崛起》（校对版全本）作者：通吃道人.txt"
chapters = extract_chapters(txt_path)
total = len(chapters)
sorted_chs = sorted(chapters, key=lambda c: c["num"])
all_nums = [c["num"] for c in sorted_chs]

STRATA = [
    {"name": "Opening", "start": 0.00, "end": 0.03},
    {"name": "Rising",  "start": 0.03, "end": 0.30},
    {"name": "Mid",     "start": 0.30, "end": 0.60},
    {"name": "Climax",  "start": 0.60, "end": 0.90},
    {"name": "Ending",  "start": 0.90, "end": 1.00},
]

sampled_nums = set()
for s in STRATA:
    start_idx = int(total * s["start"])
    end_idx = int(total * s["end"])
    stratum_chs = all_nums[start_idx:end_idx]
    n_sample = max(1, math.ceil(len(stratum_chs) * 0.10))
    if len(stratum_chs) <= n_sample:
        selected = stratum_chs
    else:
        step = len(stratum_chs) / n_sample
        indices = [int(i * step) for i in range(n_sample)]
        indices = sorted(set(min(i, len(stratum_chs)-1) for i in indices))
        selected = [stratum_chs[i] for i in indices]
    sampled_nums.update(selected)

in_new = [ch for ch in RERUN if ch in sampled_nums]
not_in_new = [ch for ch in RERUN if ch not in sampled_nums]
print(f"\nNew 10% sample: {len(sampled_nums)} chapters")
print(f"RERUN in new sample: {len(in_new)} — {in_new}")
print(f"RERUN NOT in new sample: {len(not_in_new)} — {not_in_new}")

# The golden chapters not in sample need to be extracted separately
print(f"\n=== 需要额外提取的golden章节 ===")
ch_map = {ch["num"]: ch for ch in chapters}
for ch_num in not_in_new:
    ch = ch_map.get(ch_num)
    if ch:
        body = ch.get("raw_body", "")
        print(f"  ch{ch_num}: {len(body)}字")
    else:
        print(f"  ch{ch_num}: NOT FOUND in chapters!")
