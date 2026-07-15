#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Check stratum info for the chapters needing T2 scores."""
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
    if not os.path.exists(bdir):
        print(f"{book}: NO DIR")
        continue
    
    # Check new_XX.json for stratum info
    for fname in sorted(os.listdir(bdir)):
        if fname.startswith("new_") and fname.endswith(".json"):
            fpath = os.path.join(bdir, fname)
            try:
                data = json.load(open(fpath, encoding="utf-8"))
                for item in data:
                    ch = item.get("ch_num")
                    if ch in needed:
                        print(f"  {book} ch{ch}: stratum={item.get('stratum','?')}, wc={item.get('wc','?')}")
            except Exception as e:
                pass
