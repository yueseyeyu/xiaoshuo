#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""将批次JSON拆分为单章文件，便于AI逐章阅读标注。"""
import json, sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

BATCH_DIR = Path("data/processed/末世/scores/ai_annotate_batches")
SINGLE_DIR = BATCH_DIR / "single"
SINGLE_DIR.mkdir(parents=True, exist_ok=True)

prefix = sys.argv[1] if len(sys.argv) > 1 else "rerun"

count = 0
for f in sorted(BATCH_DIR.glob(f"{prefix}_*.json")):
    data = json.load(open(f, "r", encoding="utf-8"))
    for ch in data:
        fname = f"{prefix}_ch{ch['ch_num']:04d}.txt"
        fpath = SINGLE_DIR / fname
        header = f"书: {ch['book']} | 章节: 第{ch['ch_num']}章 | 分层: {ch['stratum']} | 字数: {ch['wc']}\n{'='*60}\n"
        with open(fpath, "w", encoding="utf-8") as out:
            out.write(header + ch["body"])
        count += 1
        print(f"  {fname} ({ch['wc']}字)")

print(f"\n共生成 {count} 个单章文件 → {SINGLE_DIR}")
