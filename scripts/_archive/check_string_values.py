#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""检查GLM评分中字符串值的具体分布"""
import sys, os, json
from pathlib import Path
from collections import Counter
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.dirname(__file__))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

import ai_annotate; ai_annotate.BATCH_SIZE = 2
from ai_annotate import get_book_batch_dir

PROJECT_ROOT = Path(__file__).parent.parent
SCORES_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "scores" / "ai_annotate_batches"

DIMS = ["ai_intensity", "ai_conflict", "ai_emotion", "ai_pace", "ai_hook", "ai_retention"]

type_counter = {dim: Counter() for dim in DIMS}
sample_files = {}

for book in sorted(SCORES_DIR.iterdir()):
    if not book.is_dir() or book.name == "single":
        continue
    bdir = get_book_batch_dir(book.name)
    for sf in sorted(bdir.glob("scores_new_*.json")):
        with open(sf, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for row in data:
            for dim in DIMS:
                v = row.get(dim)
                t = type(v).__name__
                type_counter[dim][t] += 1
                if isinstance(v, str):
                    type_counter[dim][f"str_value:{v}"] += 1
                    key = f"{dim}={v}"
                    if key not in sample_files:
                        sample_files[key] = f"{book.name}/{sf.name} ch{row.get('ch_num')}"

print("=" * 80)
print("各维度数据类型统计")
print("=" * 80)
for dim in DIMS:
    print(f"\n  {dim}:")
    for k, v in sorted(type_counter[dim].items(), key=lambda x: -x[1]):
        if k.startswith("str_value:"):
            print(f"    '{k[11:]}' x{v}")
        else:
            print(f"    {k} x{v}")

print("\n" + "=" * 80)
print("字符串值样例")
print("=" * 80)
for key, loc in sorted(sample_files.items()):
    print(f"  {key:40s} -> {loc}")
