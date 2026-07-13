#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""批量打印Stage1章节供AI阅读评分。
用法: python print_stage1_batch.py <book> <batch_num>
每批20章，每章前800字
"""
import json, sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

data = json.load(open(Path("scripts/stage1_10pct_chapters.json"), encoding="utf-8"))

book = sys.argv[1] if len(sys.argv) > 1 else "废土崛起"
batch_num = int(sys.argv[2]) if len(sys.argv) > 2 else 0
batch_size = 20

book_chs = [d for d in data if d["book"] == book]
total_batches = (len(book_chs) + batch_size - 1) // batch_size

start = batch_num * batch_size
end = min(start + batch_size, len(book_chs))

print(f"Book: {book} | Batch {batch_num+1}/{total_batches} | Chs {start+1}-{end}/{len(book_chs)}")

for d in book_chs[start:end]:
    print(f"\n[{d['ch_num']}|{d['stratum']}|{d['wc']}] {d['body'][:800]}")
