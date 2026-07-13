#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证chapter_parser修复不影响其他书籍"""
import sys, os, time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

from xiaoshuo.pipeline.rhythm.chapter_parser import extract_chapters

RAW_DIR = Path(__file__).parent.parent / "data" / "raw" / "novels" / "末世"

# 检查几本代表性书籍
test_books = ["废土崛起", "末日蟑螂", "黑暗血时代", "第一序列", "末日乐园", "长夜余火"]

for pattern in test_books:
    files = list(RAW_DIR.glob(f"*{pattern}*"))
    if not files:
        print(f"{pattern}: 文件未找到")
        continue
    f = files[0]
    t0 = time.time()
    chapters = extract_chapters(str(f))
    t1 = time.time()

    if chapters:
        nums = [c["num"] for c in chapters]
        unique_nums = set(nums)
        has_dup = len(nums) != len(unique_nums)
        print(f"{pattern}: {len(chapters)}章, num范围={min(nums)}-{max(nums)}, "
              f"unique={len(unique_nums)}, {'有重复→已重编号' if has_dup else '无重复'}, "
              f"耗时={t1-t0:.2f}s")
    else:
        print(f"{pattern}: 提取失败 (0章)")
