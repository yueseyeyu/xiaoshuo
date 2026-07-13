#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""run_scoring.py — 批量LLM评分脚本 (避免PowerShell编码问题)

顺序评分多本书籍, 每本限制批次数防止超时。
"""
import sys
import os

# 设置UTF-8环境
os.environ['PYTHONIOENCODING'] = 'utf-8'

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.dirname(__file__))

# 设置全局BATCH_SIZE
import ai_annotate
ai_annotate.BATCH_SIZE = 2

from ai_annotate import score_book, merge_csv

# 要评分的书籍列表 (书名, max_batches)
# 狩魔手记: 29批, 恐慌沸腾: 76批
BOOKS_TO_SCORE = [
    ("狩魔手记_烟雨江南", 30),
    ("恐慌沸腾", 80),
]

for book_name, max_batches in BOOKS_TO_SCORE:
    print(f"\n{'='*60}")
    print(f"开始评分: {book_name} (max_batches={max_batches})")
    print(f"{'='*60}")
    sys.stdout.flush()

    count = score_book(
        book_name=book_name,
        api_base="",
        api_key="",
        api_model="",
        batch_size=2,
        max_chapters=0,
        dry_run=False,
        max_batches=max_batches,
        chapter_list_csv="",
        tier2_mode=False,
    )

    print(f"\n{book_name} 评分完成: 新评分 {count} 章")
    sys.stdout.flush()

    # 自动合并CSV
    print(f"\n合并 {book_name} CSV...")
    sys.stdout.flush()
    merge_csv(book_name)

print(f"\n{'='*60}")
print(f"全部评分完成!")
print(f"{'='*60}")
