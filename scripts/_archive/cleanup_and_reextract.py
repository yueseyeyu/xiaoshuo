#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""清理旧数据并重新提取狩魔手记和恐慌沸腾的批次"""
import sys, os, shutil
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.dirname(__file__))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

import ai_annotate
ai_annotate.BATCH_SIZE = 2  # 设置全局BATCH_SIZE
from ai_annotate import extract_full_chapters, write_batches, get_book_batch_dir

PROJECT_ROOT = Path(__file__).parent.parent
BATCH_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "scores" / "ai_annotate_batches"

books = ["狩魔手记_烟雨江南", "恐慌沸腾"]

for book in books:
    bdir = get_book_batch_dir(book)
    print(f"\n=== {book} ===")
    print(f"目录: {bdir}")

    if bdir.exists():
        # 统计旧文件
        old_batches = list(bdir.glob("*.json"))
        old_csv = bdir.parent / f"{book}_ai_full.csv"
        print(f"旧文件: {len(old_batches)}个JSON, CSV={'存在' if old_csv.exists() else '不存在'}")

        # 删除整个目录
        shutil.rmtree(bdir)
        print(f"已删除目录: {bdir}")

        # 删除旧CSV
        if old_csv.exists():
            old_csv.unlink()
            print(f"已删除CSV: {old_csv.name}")

    # 重新提取
    print(f"\n重新提取 {book}...")
    chapters = extract_full_chapters(book)
    if chapters:
        paths = write_batches(chapters, book, prefix="new")
        print(f"提取完成: {len(chapters)}章 → {len(paths)}个批次")
        print(f"批次目录: {get_book_batch_dir(book)}")
    else:
        print(f"提取失败!")

print(f"\n=== 完成 ===")
