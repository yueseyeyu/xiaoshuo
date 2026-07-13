#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""extract_all_batches.py — 一键提取所有末世小说的10%分层采样批次文件。

用法:
  D:\\miniconda3\\envs\\llm-shared\\python.exe scripts/extract_all_batches.py
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

import ai_annotate as aa

# 确保BATCH_SIZE有值
aa.BATCH_SIZE = aa.DEFAULT_BATCH_SIZE

books = list(aa.BOOKS.keys())
print(f"共 {len(books)} 本书待提取")
print("=" * 60)

done = []
failed = []
skipped = []

for i, book_name in enumerate(books):
    txt_path = aa.RAW_DIR / aa.BOOKS[book_name]
    if not txt_path.exists():
        print(f"[{i+1}/{len(books)}] {book_name}: 文件不存在, 跳过")
        skipped.append(book_name)
        continue

    batch_dir = aa.get_book_batch_dir(book_name)
    # 检查是否已有批次文件
    existing = list(batch_dir.glob("new_*.json")) if batch_dir.exists() else []
    if existing:
        print(f"[{i+1}/{len(books)}] {book_name}: 已有 {len(existing)} 个批次, 跳过提取")
        skipped.append(book_name)
        continue

    print(f"[{i+1}/{len(books)}] {book_name}: 提取中...")
    try:
        chapters = aa.extract_full_chapters(book_name)
        if chapters:
            paths = aa.write_batches(chapters, book_name, prefix="new")
            print(f"  → {len(chapters)}章, {len(paths)}个批次")
            done.append(book_name)
        else:
            print(f"  → 提取失败")
            failed.append(book_name)
    except Exception as e:
        print(f"  → 错误: {e}")
        failed.append(book_name)

print("\n" + "=" * 60)
print(f"完成: {len(done)} 本 | 跳过(已有): {len(skipped)} 本 | 失败: {len(failed)} 本")
if failed:
    print(f"失败列表: {failed}")
