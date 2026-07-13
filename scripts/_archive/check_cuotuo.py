#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""检查蹉跎的章节格式"""
import sys, os, re
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

RAW_DIR = Path(__file__).parent.parent / "data" / "raw" / "novels" / "末世"

for f in RAW_DIR.glob("*蹉跎*"):
    text = f.read_text(encoding='utf-8')
    lines = text.split('\n')
    print(f"文件: {f.name} ({f.stat().st_size/1024/1024:.1f}MB, {len(lines)}行)")

    print("\n=== 前40行 ===")
    for i, line in enumerate(lines[:40]):
        print(f"  {i:4d}: {line[:80]}")

    # 查找章节标记
    cn_nums = r"[一二三四五六七八九十百千零\d]+"

    # 尝试各种pattern
    for name, pat in [
        ("第X章(行首)", r"^[ \t]*第" + cn_nums + r"章"),
        ("第X章(任意)", r"第" + cn_nums + r"章"),
        ("章X(行首)", r"^[ \t]*章" + cn_nums),
        ("Chapter", r"^[ \t]*Chapter"),
        ("数字行", r"^[ \t]*\d{1,4}[ \t]+"),
        ("纯数字行", r"^[ \t]*\d{1,4}[ \t]*$"),
    ]:
        matches = re.findall(pat, text, flags=re.MULTILINE)
        if matches:
            print(f"\n  {name}: {len(matches)}个匹配")
            if len(matches) <= 5:
                for m in matches:
                    print(f"    {m[:60]}")
            else:
                for m in matches[:3]:
                    print(f"    {m[:60]}")
                print(f"    ... 还有{len(matches)-3}个")
    break
