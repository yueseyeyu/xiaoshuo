#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""快速修复wc不匹配问题"""
import sys, os, json
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.dirname(__file__))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

import ai_annotate; ai_annotate.BATCH_SIZE = 2
from ai_annotate import get_book_batch_dir

PROJECT_ROOT = Path(__file__).parent.parent

# 修复第九特区 scores_new_13.json ch261 wc
book = "第九特区"
bdir = get_book_batch_dir(book)

# 读取new_13
with open(bdir / "new_13.json", 'r', encoding='utf-8') as f:
    new_data = json.load(f)

# 读取scores_new_13
sf = bdir / "scores_new_13.json"
with open(sf, 'r', encoding='utf-8') as f:
    scores = json.load(f)

print("修复前:")
for s in scores:
    ch = s['ch_num']
    new_entry = next(d for d in new_data if d['ch_num'] == ch)
    match = "✅" if s['wc'] == new_entry['wc'] else "❌"
    print(f"  {match} ch{ch}: score wc={s['wc']}, new wc={new_entry['wc']}")

# 修复wc
for s in scores:
    ch = s['ch_num']
    new_entry = next(d for d in new_data if d['ch_num'] == ch)
    if s['wc'] != new_entry['wc']:
        s['wc'] = new_entry['wc']
        print(f"  → 修复 ch{ch}: wc {s['wc']} ← {new_entry['wc']}")

# 写回
with open(sf, 'w', encoding='utf-8') as f:
    json.dump(scores, f, ensure_ascii=False, indent=2)

print("已修复")
