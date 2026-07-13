#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""检查缺失目录的真正原因"""
import sys, os, json, re, unicodedata
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

BATCH_DIR = Path(__file__).parent.parent / "data" / "processed" / "末世" / "scores" / "ai_annotate_batches"

# 列出实际存在的目录
actual_dirs = {}
for d in BATCH_DIR.iterdir():
    if d.is_dir():
        actual_dirs[d.name] = d

print(f"实际目录数: {len(actual_dirs)}")
for name in sorted(actual_dirs.keys()):
    new_count = len(list((BATCH_DIR / name).glob("new_*.json")))
    print(f"  [{name!r}] new={new_count}")

# 检查缺失的书
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

print(f"\n期望书数: {len(ALL_BOOKS)}")

# 对比
missing = []
for book in sorted(ALL_BOOKS.keys()):
    if book == "废土崛起":
        root_new = list(BATCH_DIR.glob("new_*.json"))
        print(f"  废土崛起 (根目录): new={len(root_new)}")
        continue

    # 检查精确匹配
    if book in actual_dirs:
        new_count = len(list((BATCH_DIR / book).glob("new_*.json")))
        print(f"  ✅ {book}: new={new_count}")
    else:
        # 检查Unicode规范化
        found = False
        book_nfc = unicodedata.normalize('NFC', book)
        for actual_name in actual_dirs:
            actual_nfc = unicodedata.normalize('NFC', actual_name)
            if book_nfc == actual_nfc:
                print(f"  ⚠️ {book}: 名称Unicode不一致, 实际={actual_name!r}")
                found = True
                break
        if not found:
            print(f"  ❌ {book}: 目录不存在!")
            missing.append(book)

print(f"\n缺失: {len(missing)}本 — {missing}")

# 尝试创建缺失目录并重新提取
if missing:
    print("\n=== 重新提取缺失书籍 ===")
    sys.path.insert(0, os.path.dirname(__file__))
    import ai_annotate
    ai_annotate.BATCH_SIZE = 2
    from ai_annotate import extract_full_chapters, write_batches

    for book in missing:
        print(f"\n{book}:")
        chapters = extract_full_chapters(book)
        if chapters:
            paths = write_batches(chapters, book, prefix="new")
            print(f"  提取完成: {len(chapters)}章 → {len(paths)}批")
        else:
            print(f"  ❌提取失败!")
