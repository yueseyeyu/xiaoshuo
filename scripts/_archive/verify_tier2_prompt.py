#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证Tier2指令的准确性"""
import sys, os, json
from pathlib import Path
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent.parent
TIER2_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "scores" / "tier2_batches"

print("=" * 80)
print("Tier2 指令验证报告")
print("=" * 80)

# 1. 检查目录数
dirs = sorted([x for x in TIER2_DIR.iterdir() if x.is_dir()])
print(f"\n1. 目录数: {len(dirs)}")

# 2. 检查每本书的批次文件命名
print(f"\n2. 批次文件命名检查:")
total_batches = 0
total_chapters = 0
all_ok = True
for d in dirs:
    new_files = sorted(d.glob("new_*.json"))
    if not new_files:
        print(f"  ❌ {d.name}: 无new_*.json文件")
        all_ok = False
        continue

    first = new_files[0].name
    last = new_files[-1].name

    # 检查命名格式是否一致
    expected_first = "new_00.json"
    if first != expected_first:
        print(f"  ⚠️ {d.name}: 首文件={first}, 期望={expected_first}")

    # 检查new文件内容
    with open(new_files[0], 'r', encoding='utf-8') as f:
        data = json.load(f)
    ch_count = len(data)

    # 检查字段
    sample = data[0]
    required_fields = {"ch_num", "stratum", "wc", "text"}
    missing = required_fields - set(sample.keys())
    if missing:
        print(f"  ❌ {d.name}: new文件缺少字段: {missing}")
        all_ok = False

    total_batches += len(new_files)
    total_chapters += sum(len(json.load(open(f, 'r', encoding='utf-8'))) for f in new_files)

print(f"  总批次: {total_batches}, 总章节: {total_chapters}")

# 3. 检查指令中引用的目录名是否与实际一致
print(f"\n3. 指令目录名 vs 实际目录名:")
prompt_path = PROJECT_ROOT / "trae_tier1" / "PROMPT_TIER2_TRAE.md"
with open(prompt_path, 'r', encoding='utf-8') as f:
    prompt = f.read()

import re
# 提取指令中的目录路径
prompt_dirs = re.findall(r'tier2_batches/(.+?)`', prompt)
prompt_dirs_unique = sorted(set(prompt_dirs))
actual_names = sorted([d.name for d in dirs])

# 对比
missing_in_actual = []
for pd in prompt_dirs_unique:
    found = False
    for an in actual_names:
        if pd == an or pd in an or an in pd:
            found = True
            break
    if not found:
        missing_in_actual.append(pd)

if missing_in_actual:
    print(f"  ❌ 指令中引用但实际不存在的目录: {missing_in_actual}")
else:
    print(f"  ✅ 指令中所有目录名都与实际匹配 ({len(prompt_dirs_unique)}个)")

# 4. 检查指令中的段数
seg_count = prompt.count("## 第") 
print(f"\n4. 指令段数: {seg_count}段 (标题写的是15段)")

# 5. 检查质检脚本字段名
print(f"\n5. 质检脚本字段检查:")
qc_path = PROJECT_ROOT / "scripts" / "quality_check_tier2.py"
with open(qc_path, 'r', encoding='utf-8') as f:
    qc = f.read()

t2_fields = ["t2_intensity", "t2_conflict", "t2_emotion", "t2_pace", "t2_hook", "t2_retention", "t2_analysis"]
for field in t2_fields:
    if field not in qc:
        print(f"  ❌ 质检脚本缺少字段: {field}")
    else:
        print(f"  ✅ {field}")

# 6. 检查analysis长度要求一致性
print(f"\n6. analysis长度要求:")
print(f"  指令: 20-50字")
import re
ma = re.search(r'len\(analysis\.strip\(\)\) < (\d+)', qc)
if ma:
    print(f"  质检: 最低{ma.group(1)}字")
ma2 = re.search(r'len\(analysis\) > (\d+)', qc)
if ma2:
    print(f"  质检: 最高{ma2.group(1)}字 (警告)")

# 7. 检查指令是否提到输出文件不应包含text字段
print(f"\n7. 是否提醒不要在scores中包含text字段:")
if "不要包含text" in prompt or "不包含text" in prompt or "去掉text" in prompt:
    print(f"  ✅ 已提醒")
else:
    print(f"  ⚠️ 未提醒 — Trae可能会把text也写进scores文件")

# 8. 验证第一批次文件内容
print(f"\n8. 首批次文件抽样检查:")
first_book = dirs[0]
first_batch = first_book / "new_00.json"
with open(first_batch, 'r', encoding='utf-8') as f:
    data = json.load(f)
print(f"  书名: {first_book.name}")
print(f"  文件: {first_batch.name}")
print(f"  章节数: {len(data)}")
for d in data:
    text_preview = d['text'][:80].replace('\n', ' ')
    print(f"  ch{d['ch_num']} [{d['stratum']}] wc={d['wc']} | {text_preview}...")

print(f"\n{'='*80}")
issues = []
if seg_count != 15 and "15段" in prompt:
    issues.append(f"标题写15段但实际只有{seg_count}段")
if missing_in_actual:
    issues.append(f"指令引用了不存在的目录")
if "不要包含text" not in prompt and "不包含text" not in prompt:
    issues.append("未提醒Trae不要在scores中包含text字段")

if issues:
    print(f"发现问题 ({len(issues)}个):")
    for i, issue in enumerate(issues, 1):
        print(f"  {i}. {issue}")
else:
    print("✅ 无问题")
