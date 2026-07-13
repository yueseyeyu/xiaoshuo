#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""为全部33本书运行merge_csv，生成_ai_full.csv"""
import sys, os, json, re
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.dirname(__file__))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

import ai_annotate
ai_annotate.BATCH_SIZE = 2
from ai_annotate import merge_csv, get_book_batch_dir

PROJECT_ROOT = Path(__file__).parent.parent
INDEX_PATH = PROJECT_ROOT / "data" / "raw" / "novel_index.json"
with open(INDEX_PATH, 'r', encoding='utf-8') as f:
    idx = json.load(f)

ALL_BOOKS = []
for n in idx.get('genres', {}).get('末世', {}).get('novels', []):
    fname = n['file']
    short = fname.replace('.txt', '')
    if short.startswith('《'):
        m = re.search(r'《(.+?)》', short)
        short = m.group(1) if m else short
    ALL_BOOKS.append(short)

print(f"共{len(ALL_BOOKS)}本书待合并")
print("=" * 80)

success = 0
fail = 0
for i, book in enumerate(sorted(ALL_BOOKS), 1):
    bdir = get_book_batch_dir(book)
    if not bdir.exists():
        print(f"[{i:02d}/{len(ALL_BOOKS)}] ⬜ {book}: 批次目录不存在, 跳过")
        fail += 1
        continue

    new_count = len(list(bdir.glob("new_*.json")))
    score_count = len(list(bdir.glob("scores_new_*.json")))

    if score_count == 0:
        # 也检查旧格式 scores_XX.json (废土崛起根目录)
        score_count = len(list(bdir.glob("scores_[0-9]*.json")))

    if score_count == 0:
        print(f"[{i:02d}/{len(ALL_BOOKS)}] ⬜ {book}: 无评分文件, 跳过")
        fail += 1
        continue

    try:
        out = merge_csv(book)
        print(f"[{i:02d}/{len(ALL_BOOKS)}] ✅ {book}: {new_count}批 → {out.name}")
        success += 1
    except Exception as e:
        print(f"[{i:02d}/{len(ALL_BOOKS)}] ❌ {book}: {e}")
        fail += 1

print(f"\n{'=' * 80}")
print(f"完成: {success}成功, {fail}失败")
