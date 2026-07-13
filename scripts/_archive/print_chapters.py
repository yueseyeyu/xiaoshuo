#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""逐章输出正文到UTF-8文件供GLM盲评"""
import json, sys
from pathlib import Path

data = json.load(open("scripts/glm_chapters.json", "r", encoding="utf-8"))
start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
count = int(sys.argv[2]) if len(sys.argv) > 2 else 5
batch = int(sys.argv[3]) if len(sys.argv) > 3 else 1

out = Path(f"scripts/glm_batch_{batch}.txt")
with open(out, "w", encoding="utf-8") as f:
    for c in data[start:start+count]:
        f.write(f"=== {c['book']} ch{c['ch_num']} ===\n")
        f.write(c["body"])
        f.write("\n\n")
print(f"Written {out} ({start}..{start+count-1})")
