#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""查看商业评分JSON结构"""
import json, sys
from pathlib import Path
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent.parent
scores = json.load(open(PROJECT_ROOT / "data" / "processed" / "末世" / "quality" / "commercial_scores.json", 'r', encoding='utf-8'))

if isinstance(scores, dict):
    # 可能是 {book_name: {...}}
    for i, (k, v) in enumerate(scores.items()):
        if i < 2:
            print(f"Key: {k}")
            print(json.dumps(v, ensure_ascii=False, indent=2)[:500])
            print("---")
    print(f"\n总书数: {len(scores)}")
elif isinstance(scores, list):
    for i, v in enumerate(scores[:2]):
        print(json.dumps(v, ensure_ascii=False, indent=2)[:500])
        print("---")
    print(f"\n总书数: {len(scores)}")
