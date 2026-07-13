#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Print expansion chapters for AI reading and scoring."""
import json, sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

data = json.load(open(Path(__file__).parent / "expansion_chapters.json", "r", encoding="utf-8"))

batch = int(sys.argv[1]) if len(sys.argv) > 1 else 0
batch_size = 4
start = batch * batch_size
end = min(start + batch_size, len(data))

for d in data[start:end]:
    print(f"=== {d['book']} ch{d['ch_num']} ({d['wc']}chars) ===")
    print(d['body'][:2500])
    print()
