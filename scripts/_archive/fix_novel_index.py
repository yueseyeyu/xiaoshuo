#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""修复novel_index.json中3本S级新书缺少rhythm_csv字段的问题"""
import json, sys
from pathlib import Path
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent.parent
idx_path = PROJECT_ROOT / "data" / "raw" / "novel_index.json"
idx = json.load(open(idx_path, 'r', encoding='utf-8'))

# 3本缺少rhythm_csv的书 → 对应的rhythm CSV文件名
FIXES = {
    "《第一序列》（校对版全本）作者：会说话的肘子.txt": "rhythm_《第一序列》（校对版全本）作者：会说话的肘子.csv",
    "《长夜余火》（校对版全本）作者：爱潜水的乌贼.txt": "rhythm_《长夜余火》（校对版全本）作者：爱潜水的乌贼.csv",
    "末日乐园.txt": "rhythm_末日乐园.csv",
}

novels = idx['genres']['末世']['novels']
fixed = 0
for n in novels:
    fname = n['file']
    if fname in FIXES and not n.get('rhythm_csv'):
        n['rhythm_csv'] = FIXES[fname]
        fixed += 1
        print(f"  ✅ {fname[:50]} → {FIXES[fname]}")

print(f"\n修复了 {fixed} 本书的rhythm_csv字段")

# 保存
with open(idx_path, 'w', encoding='utf-8') as f:
    json.dump(idx, f, ensure_ascii=False, indent=2)
print(f"已保存到 {idx_path}")
