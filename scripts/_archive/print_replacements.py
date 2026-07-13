#!/usr/bin/env python
# -*- coding: utf-8 -*-
import json, sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
data = json.load(open('scripts/expansion_chapters.json', 'r', encoding='utf-8'))
for idx in [13, 17]:
    d = data[idx]
    print(f"=== {d['book']} ch{d['ch_num']} ({d['wc']}chars) ===")
    print(d['body'][:2500])
    print()
