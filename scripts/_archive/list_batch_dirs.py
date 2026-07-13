#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys, os
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

BATCH_DIR = Path(__file__).parent.parent / "data" / "processed" / "末世" / "scores" / "ai_annotate_batches"

print("=== BATCH_DIR 子目录 ===")
dirs = sorted([d.name for d in BATCH_DIR.iterdir() if d.is_dir()])
for d in dirs:
    new_files = list((BATCH_DIR / d).glob("new_*.json"))
    score_files = list((BATCH_DIR / d).glob("scores_*.json"))
    print(f"  {d:<40} new={len(new_files):>3} scores={len(score_files):>3}")

print(f"\n子目录数: {len(dirs)}")

# 根目录的new_文件
root_new = list(BATCH_DIR.glob("new_*.json"))
root_scores = list(BATCH_DIR.glob("scores_*.json"))
print(f"根目录: new={len(root_new)}, scores={len(root_scores)}")

# 对比期望的书名
import json, re
INDEX_PATH = Path(__file__).parent.parent / "data" / "raw" / "novel_index.json"
with open(INDEX_PATH, 'r', encoding='utf-8') as f:
    idx = json.load(f)

ALL_BOOKS = {}
for n in idx.get('genres', {}).get('末世', {}).get('novels', []):
    fname = n['file']
    short = fname.replace('.txt', '')
    if short.startswith('《'):
        m = re.search(r'《(.+?)》', short)
        short = m.group(1) if m else short
    ALL_BOOKS[short] = fname

print(f"\n=== 对比 ===")
print(f"期望书数: {len(ALL_BOOKS)}")
print(f"实际目录数: {len(dirs)}")

dir_set = set(dirs)
for book in sorted(ALL_BOOKS.keys()):
    if book == "废土崛起":
        has = len(root_new) > 0
        print(f"  {'✅' if has else '❌'} {book:<30} (根目录) new={len(root_new)}")
    elif book in dir_set:
        new_count = len(list((BATCH_DIR / book).glob("new_*.json")))
        score_count = len(list((BATCH_DIR / book).glob("scores_*.json")))
        status = "✅" if new_count > 0 else "❌"
        print(f"  {status} {book:<30} new={new_count:>3} scores={score_count:>3}")
    else:
        print(f"  ❌ {book:<30} 目录不存在!")
