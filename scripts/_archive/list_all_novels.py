#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""列出全部末世小说及其质量分级"""
import json, sys, yaml
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent.parent

# 从 novel_index.json 获取全部末世小说
idx_path = PROJECT_ROOT / "data" / "raw" / "novel_index.json"
with open(idx_path, 'r', encoding='utf-8') as f:
    idx = json.load(f)

novels = idx.get("genres", {}).get("末世", {}).get("novels", [])
print(f"novel_index.json: {len(novels)} 本末世小说\n")

# 从 config.yaml 获取质量分级
cfg_path = PROJECT_ROOT / "config.yaml"
with open(cfg_path, 'r', encoding='utf-8') as f:
    cfg = yaml.safe_load(f)

tiers = cfg.get("analysis", {}).get("book_filter", {}).get("quality_tiers", {})

# 建立书名→分级映射
book_tier = {}
for tier_name, tier_data in tiers.items():
    for bn in tier_data.get("books", []):
        book_tier[bn] = tier_name

# 输出全部小说
for n in novels:
    fname = n.get("file", "")
    # 从文件名提取书名
    name = fname.replace("《", "").replace("》", "")
    # 去掉作者等后缀
    if "（校对版" in name:
        name = name.split("（校对版")[0]
    if "（精校版" in name:
        name = name.split("（精校版")[0]
    if "作者" in name:
        name = name.split("作者")[0].strip("：").strip(":").strip()

    tier = "?"
    for bn, tn in book_tier.items():
        bn_clean = bn.replace("《", "").replace("》", "")
        if bn_clean in name or name in bn_clean:
            tier = tn
            break

    print(f"[{tier:>8}] {name}")

print(f"\n分级统计:")
tier_count = {}
for n in novels:
    fname = n.get("file", "")
    name = fname.replace("《", "").replace("》", "")
    if "（校对版" in name: name = name.split("（校对版")[0]
    if "（精校版" in name: name = name.split("（精校版")[0]
    if "作者" in name: name = name.split("作者")[0].strip("：").strip(":").strip()
    tier = "?"
    for bn, tn in book_tier.items():
        bn_clean = bn.replace("《", "").replace("》", "")
        if bn_clean in name or name in bn_clean:
            tier = tn
            break
    tier_count[tier] = tier_count.get(tier, 0) + 1

for t in ["S", "A", "B_plus", "B", "B_minus", "C", "?"]:
    if t in tier_count:
        print(f"  {t}: {tier_count[t]}本")
print(f"  总计: {len(novels)}本")
