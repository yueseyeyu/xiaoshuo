#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试章节提取"""
import sys, os, time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

from xiaoshuo.pipeline.rhythm.chapter_parser import extract_chapters

# 找到狩魔手记文件
RAW_DIR = Path(__file__).parent.parent / "data" / "raw" / "novels" / "末世"
for f in RAW_DIR.glob("*狩魔*"):
    print(f"文件: {f.name} ({f.stat().st_size/1024/1024:.1f}MB)")
    t0 = time.time()
    chapters = extract_chapters(str(f))
    t1 = time.time()
    print(f"章节: {len(chapters)} (耗时 {t1-t0:.2f}s)")
    if chapters:
        print(f"  第1章: num={chapters[0]['num']}, title={chapters[0]['title'][:30]}, wc={chapters[0]['wc']}")
        print(f"  最后章: num={chapters[-1]['num']}, title={chapters[-1]['title'][:30]}, wc={chapters[-1]['wc']}")
    break

# 测试恐慌沸腾
for f in RAW_DIR.glob("*恐慌沸腾*"):
    print(f"\n文件: {f.name} ({f.stat().st_size/1024/1024:.1f}MB)")
    t0 = time.time()
    chapters = extract_chapters(str(f))
    t1 = time.time()
    print(f"章节: {len(chapters)} (耗时 {t1-t0:.2f}s)")
    if chapters:
        print(f"  第1章: num={chapters[0]['num']}, title={chapters[0]['title'][:30]}, wc={chapters[0]['wc']}")
        print(f"  最后章: num={chapters[-1]['num']}, title={chapters[-1]['title'][:30]}, wc={chapters[-1]['wc']}")
    break
