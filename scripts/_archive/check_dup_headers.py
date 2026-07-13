#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""检查恐慌沸腾的匹配分布"""
import sys, os, re
from pathlib import Path
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

RAW_DIR = Path(__file__).parent.parent / "data" / "raw" / "novels" / "末世"

for f in RAW_DIR.glob("*恐慌沸腾*"):
    text = f.read_text(encoding='utf-8')
    lines = text.split('\n')

    cn_nums = r"[一二三四五六七八九十百千零\d]+"
    pattern = r"^[ \t]*第" + cn_nums + r"章\s*[^\n]*"

    matches = []
    for i, line in enumerate(lines):
        m = re.match(pattern, line)
        if m:
            matches.append((i, line.strip()))

    print(f"文件: {f.name}")
    print(f"匹配行数: {len(matches)}")

    # 检查重复的行内容
    line_counts = Counter(line for _, line in matches)
    dups = {k: v for k, v in line_counts.items() if v > 1}
    print(f"\n重复行内容: {len(dups)}种")
    for line, count in sorted(dups.items(), key=lambda x: -x[1])[:10]:
        print(f"  {count}x: {line[:60]}")

    # 检查匹配行号分布
    print(f"\n=== 匹配行号分布 ===")
    if matches:
        gaps = []
        for i in range(1, len(matches)):
            gap = matches[i][0] - matches[i-1][0]
            gaps.append(gap)
        if gaps:
            print(f"  行号间隔: min={min(gaps)}, max={max(gaps)}, avg={sum(gaps)/len(gaps):.1f}")
            small_gaps = [g for g in gaps if g < 5]
            if small_gaps:
                print(f"  间隔<5行的: {len(small_gaps)}个 (可能是目录或连续标题)")

    # 显示最后20个匹配
    print(f"\n=== 最后20个匹配 ===")
    for ln, line in matches[-20:]:
        print(f"  行{ln:5d}: {line[:60]}")

    # 显示中间一些匹配 (行500-520)
    print(f"\n=== 行号500-600附近的匹配 ===")
    for ln, line in matches:
        if 500 <= ln <= 600:
            print(f"  行{ln:5d}: {line[:60]}")
    break
