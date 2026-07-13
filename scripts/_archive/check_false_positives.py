#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""检查误匹配的章节标记"""
import sys, os, re
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

RAW_DIR = Path(__file__).parent.parent / "data" / "raw" / "novels" / "末世"

# 检查恐慌沸腾
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
    print(f"\n=== 前20个匹配 ===")
    for idx, (ln, line) in enumerate(matches[:20]):
        print(f"  行{ln:5d} (len={len(line):3d}): {line[:80]}")

    print(f"\n=== 长度>30的匹配 (可能是误匹配) ===")
    long_matches = [(ln, line) for ln, line in matches if len(line) > 30]
    print(f"数量: {len(long_matches)}/{len(matches)}")
    for ln, line in long_matches[:10]:
        print(f"  行{ln:5d} (len={len(line):3d}): {line[:80]}")

    print(f"\n=== 长度<=30的匹配 (可能是真章节) ===")
    short_matches = [(ln, line) for ln, line in matches if len(line) <= 30]
    print(f"数量: {len(short_matches)}/{len(matches)}")
    for ln, line in short_matches[:10]:
        print(f"  行{ln:5d} (len={len(line):3d}): {line[:80]}")
    break

# 检查狩魔手记
print("\n" + "="*60)
for f in RAW_DIR.glob("*狩魔*"):
    text = f.read_text(encoding='utf-8')
    lines = text.split('\n')

    cn_nums = r"[一二三四五六七八九十百千零\d]+"
    pattern = r"^[ \t]*(?:序章\s*[^\n]*|章" + cn_nums + r"\s+[^\n]*)"

    matches = []
    for i, line in enumerate(lines):
        m = re.match(pattern, line)
        if m:
            matches.append((i, line.strip()))

    print(f"文件: {f.name}")
    print(f"匹配行数: {len(matches)}")
    print(f"\n=== 前20个匹配 ===")
    for idx, (ln, line) in enumerate(matches[:20]):
        print(f"  行{ln:5d} (len={len(line):3d}): {line[:80]}")

    print(f"\n=== 长度>30的匹配 ===")
    long_matches = [(ln, line) for ln, line in matches if len(line) > 30]
    print(f"数量: {len(long_matches)}/{len(matches)}")
    for ln, line in long_matches[:5]:
        print(f"  行{ln:5d} (len={len(line):3d}): {line[:80]}")

    print(f"\n=== 长度<=30的匹配 ===")
    short_matches = [(ln, line) for ln, line in matches if len(line) <= 30]
    print(f"数量: {len(short_matches)}/{len(matches)}")
    break
