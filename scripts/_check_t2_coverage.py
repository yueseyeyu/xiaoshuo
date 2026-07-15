#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Check which chapters have T2 scores and which are missing."""
import json, os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

NEED_T2 = {
    "地球游戏场": [1, 198, 384, 443, 561, 581, 749, 769],
    "末世大回炉": [975, 1556, 1606, 1625, 1704],
    "异兽迷城": [1, 316, 643, 663, 762, 900, 959, 1276],
    "黑暗血时代": [1, 216, 256, 466, 665, 922, 1388, 1537, 1841],
    "第一序列": [1, 310, 627, 747, 896, 946, 955, 1251],
    "末日乐园": [1, 610, 979, 1218, 1817, 1866, 2016, 2419],
    "长夜余火": [536, 934],
}

base = "data/processed/末世/scores/tier2_batches"

for book, needed in NEED_T2.items():
    bdir = os.path.join(base, book)
    scored = set()
    if os.path.exists(bdir):
        for fname in sorted(os.listdir(bdir)):
            if fname.startswith("scores_new_") and fname.endswith(".json"):
                fpath = os.path.join(bdir, fname)
                try:
                    data = json.load(open(fpath, encoding="utf-8"))
                    for item in data:
                        scored.add(item["ch_num"])
                except:
                    pass
    missing = [ch for ch in needed if ch not in scored]
    have = [ch for ch in needed if ch in scored]
    print(f"{book}: needed={needed}")
    print(f"  have={have}")
    print(f"  missing={missing}")
    print()
