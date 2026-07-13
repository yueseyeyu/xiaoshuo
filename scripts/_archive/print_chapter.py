#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""逐章打印批次内容供AI标注。"""
import json, sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

BATCH_DIR = Path("data/processed/末世/scores/ai_annotate_batches")

prefix = sys.argv[1] if len(sys.argv) > 1 else "rerun"
batch_num = int(sys.argv[2]) if len(sys.argv) > 2 else 0
chapter_idx = int(sys.argv[3]) if len(sys.argv) > 3 else -1  # -1 = list all

fpath = BATCH_DIR / f"{prefix}_{batch_num:02d}.json"
if not fpath.exists():
    print(f"File not found: {fpath}")
    sys.exit(1)

data = json.load(open(fpath, "r", encoding="utf-8"))

if chapter_idx == -1:
    print(f"=== {fpath.name}: {len(data)} chapters ===")
    for i, d in enumerate(data):
        print(f"  [{i}] {d['book']} ch{d['ch_num']} [{d['stratum']}] {d['wc']}chars")
else:
    d = data[chapter_idx]
    print(f"=== {d['book']} ch{d['ch_num']} [{d['stratum']}] | {d['wc']}chars ===")
    print(d['body'])
