#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证修复后所有书籍的章节提取"""
import sys, os, re, time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

from xiaoshuo.pipeline.rhythm.chapter_parser import extract_chapters

PROJECT_ROOT = Path(__file__).parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "novels" / "末世"

INDEX_PATH = PROJECT_ROOT / "data" / "raw" / "novel_index.json"
import json
with open(INDEX_PATH, 'r', encoding='utf-8') as f:
    idx = json.load(f)

BOOKS = {}
for n in idx.get('genres', {}).get('末世', {}).get('novels', []):
    fname = n['file']
    short = fname.replace('.txt', '')
    if short.startswith('《'):
        m = re.search(r'《(.+?)》', short)
        short = m.group(1) if m else short
    BOOKS[short] = fname

print(f"{'书名':<28} {'章节':>6} {'num范围':>12} {'unique':>7} {'耗时':>6}")
print("-" * 70)

total_chapters = 0
zero_books = []

for book_name, txt_file in sorted(BOOKS.items()):
    txt_path = RAW_DIR / txt_file
    if not txt_path.exists():
        print(f"{book_name:<28} 文件缺失")
        continue

    t0 = time.time()
    chapters = extract_chapters(str(txt_path))
    t1 = time.time()

    if chapters:
        nums = [c["num"] for c in chapters]
        unique = len(set(nums))
        has_dup = len(nums) != unique
        total_chapters += len(chapters)
        disp = book_name[:26]
        range_str = f"{min(nums)}-{max(nums)}"
        dup_str = "重编" if has_dup else ""
        print(f"{disp:<28} {len(chapters):>6} {range_str:>12} {unique:>7} {t1-t0:>5.2f}s {dup_str}")
    else:
        print(f"{book_name:<28}      0           0      0  ❌失败")
        zero_books.append(book_name)

print(f"\n总计: {total_chapters}章, {len(BOOKS)}本")
if zero_books:
    print(f"❌解析失败: {zero_books}")
else:
    print("✅全部解析成功")
