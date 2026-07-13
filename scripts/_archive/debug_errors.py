#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""诊断末日乐园的错误评分文件"""
import sys, os, json
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.dirname(__file__))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

import ai_annotate; ai_annotate.BATCH_SIZE = 2
from ai_annotate import get_book_batch_dir

PROJECT_ROOT = Path(__file__).parent.parent
book = "末日乐园"
bdir = get_book_batch_dir(book)

# 检查有错误的批次
error_batches = [82, 102, 103, 104, 112, 113, 114, 116]

for batch_num in error_batches:
    nf = bdir / f"new_{batch_num:02d}.json"
    sf = bdir / f"scores_new_{batch_num:02d}.json"

    if not sf.exists():
        print(f"批次{batch_num}: 评分文件不存在")
        continue

    with open(nf, 'r', encoding='utf-8') as f:
        new_data = json.load(f)
    with open(sf, 'r', encoding='utf-8') as f:
        score_data = json.load(f)

    print(f"\n=== 批次{batch_num} ===")
    print(f"new文件: {len(new_data)}章, score文件: {len(score_data)}章")
    for n, s in zip(new_data, score_data):
        match_ch = n['ch_num'] == s.get('ch_num')
        match_wc = n['wc'] == s.get('wc')
        ch_mark = "✅" if match_ch else "❌"
        wc_mark = "✅" if match_wc else "❌"
        print(f"  new: ch{n['ch_num']} wc={n['wc']} stratum={n['stratum']}  |  score: ch{s.get('ch_num')} wc={s.get('wc')}  {ch_mark}{wc_mark}")
