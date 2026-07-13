#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""检查novel_index.json中缺少rhythm_csv的书籍"""
import json, sys
from pathlib import Path
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent.parent
idx = json.load(open(PROJECT_ROOT / "data" / "raw" / "novel_index.json", 'r', encoding='utf-8'))
novels = idx['genres']['末世']['novels']

rhythm_dir = PROJECT_ROOT / "data" / "processed" / "末世" / "rhythm"
existing_csvs = set(f.name for f in rhythm_dir.glob("*.csv"))

print(f"共{len(novels)}本小说")
print("=" * 100)
for n in novels:
    fname = n['file']
    csv_name = n.get('rhythm_csv', '')
    has_csv = bool(csv_name)
    csv_exists = csv_name in existing_csvs if csv_name else False
    status = "✅" if has_csv and csv_exists else ("⚠️" if has_csv else "❌")
    print(f"  {status} {fname[:50]:52s} rhythm_csv={csv_name or 'MISSING'}")
    if not csv_exists and csv_name:
        # 尝试模糊匹配
        for ec in sorted(existing_csvs):
            stem = fname.replace('.txt', '')
            if stem[:10] in ec:
                print(f"      → 可能匹配: {ec}")

# 列出未被引用的rhythm CSV
referenced = set(n.get('rhythm_csv', '') for n in novels)
unreferenced = existing_csvs - referenced
if unreferenced:
    print(f"\n未被引用的rhythm CSV ({len(unreferenced)}个):")
    for u in sorted(unreferenced):
        print(f"  {u}")
