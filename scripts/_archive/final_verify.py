#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""final_verify.py — 彻底验证：是否有遗漏的评分文件，确认清理范围正确

检查:
1. ai_annotate_batches/ 下所有子目录+根目录的 scores_*.json
2. single/ 目录
3. data/processed/末世/scores/ 下的 CSV 文件
4. data/golden/ 下的评分
5. 任何其他可能的评分文件位置
"""
import sys, os, json, re
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent.parent
SCORES_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "scores"
BATCH_DIR = SCORES_DIR / "ai_annotate_batches"

print("=" * 80)
print("彻底验证：搜索所有可能的评分文件")
print("=" * 80)

# 1. 搜索 ai_annotate_batches/ 下所有 scores_*.json
print("\n[1] ai_annotate_batches/ 下的 scores_*.json")
all_score_files = list(BATCH_DIR.rglob("scores_*.json"))
print(f"  总数: {len(all_score_files)}")
if all_score_files:
    for sf in sorted(all_score_files):
        rel = sf.relative_to(BATCH_DIR)
        print(f"  {rel}")
else:
    print("  ✅ 无残留评分文件")

# 2. 检查 single/ 目录
print("\n[2] ai_annotate_batches/single/ 目录")
single_dir = BATCH_DIR / "single"
if single_dir.exists():
    files = list(single_dir.glob("*"))
    print(f"  文件数: {len(files)}")
    for f in sorted(files)[:10]:
        print(f"    {f.name}")
else:
    print("  目录不存在")

# 3. 检查 CSV 文件
print("\n[3] data/processed/末世/scores/ 下的 CSV 文件")
csv_files = list(SCORES_DIR.glob("*.csv"))
print(f"  CSV 文件数: {len(csv_files)}")
for f in sorted(csv_files):
    print(f"    {f.name} ({f.stat().st_size} bytes)")

# 4. 检查 golden 评分
print("\n[4] data/golden/ 下的评分文件")
golden_dir = PROJECT_ROOT / "data" / "golden" / "末世"
if golden_dir.exists():
    golden_files = list(golden_dir.rglob("*"))
    print(f"  文件数: {len([f for f in golden_files if f.is_file()])}")
    for f in sorted(golden_files):
        if f.is_file():
            print(f"    {f.relative_to(golden_dir)} ({f.stat().st_size} bytes)")
else:
    print("  目录不存在")

# 5. 搜索整个 data/processed/ 下所有 .json 和 .csv
print("\n[5] data/processed/末世/ 下所有 scores 相关文件")
processed_dir = PROJECT_ROOT / "data" / "processed" / "末世"
for pattern in ["**/scores_*.json", "**/*_scores.json", "**/*ai*.json"]:
    files = list(processed_dir.glob(pattern))
    if files:
        print(f"  pattern={pattern}: {len(files)}个")
        for f in sorted(files)[:5]:
            print(f"    {f.relative_to(processed_dir)}")

# 6. 检查旧评分可能存放的其他位置
print("\n[6] 搜索 qwen_scores / llm_scores / deepseek 等关键词")
for keyword in ["qwen_score", "llm_score", "deepseek", "score_comparison"]:
    files = list(PROJECT_ROOT.rglob(f"*{keyword}*"))
    files = [f for f in files if f.is_file() and ".git" not in str(f)]
    if files:
        print(f"  '{keyword}': {len(files)}个")
        for f in sorted(files)[:5]:
            print(f"    {f.relative_to(PROJECT_ROOT)}")

# 7. 确认 new_*.json 批次文件的状态
print("\n[7] new_*.json 批次文件最终状态")
INDEX_PATH = PROJECT_ROOT / "data" / "raw" / "novel_index.json"
with open(INDEX_PATH, 'r', encoding='utf-8') as f:
    idx = json.load(f)

ALL_BOOKS = {}
for n in idx.get('genres', {}).get('末世', {}).get('novels', []):
    fname = n['file']
    short = fname.replace('.txt', '')
    if short.startswith('《'):
        m = re.search(r'《(.+?)》', short)
        short = m.group(1) if m else short
    ALL_BOOKS[short] = fname

sys.path.insert(0, os.path.dirname(__file__))
import ai_annotate
ai_annotate.BATCH_SIZE = 2
from ai_annotate import get_book_batch_dir

total_new = 0
total_scores = 0
missing_books = []

for book in sorted(ALL_BOOKS.keys()):
    bdir = get_book_batch_dir(book)
    if not bdir.exists():
        missing_books.append(book)
        continue
    new_files = list(bdir.glob("new_*.json"))
    score_files = list(bdir.glob("scores_*.json"))
    total_new += len(new_files)
    total_scores += len(score_files)
    
    if not new_files:
        print(f"  ❌ {book}: 0个new_文件!")
    elif score_files:
        print(f"  ⚠️ {book}: {len(new_files)}批, {len(score_files)}评分(残留!)")

print(f"\n  总计: {total_new}个new_文件, {total_scores}个scores_文件")
if missing_books:
    print(f"  ❌ 缺失目录: {missing_books}")
else:
    print(f"  ✅ 33本全部有批次文件")

# 8. 抽查几个批次文件的内容质量
print("\n[8] 抽查批次文件内容质量")
import random
check_books = ["废土崛起", "末日乐园", "第九特区", "蹉跎", "狩魔手记_烟雨江南"]
for book in check_books:
    bdir = get_book_batch_dir(book)
    new_files = sorted(bdir.glob("new_*.json"))
    if not new_files:
        continue
    # 检查第1批和最后1批
    for nf in [new_files[0], new_files[-1]]:
        with open(nf, 'r', encoding='utf-8') as f:
            data = json.load(f)
        ch_count = len(data)
        total_wc = sum(d.get('wc', 0) for d in data)
        ch_nums = [d.get('ch_num') for d in data]
        strata = [d.get('stratum') for d in data]
        # 检查文本是否真实（不是碎片）
        sample_text = data[0].get('text', '')[:100] if data else ''
        print(f"  {book}/{nf.name}: {ch_count}章 ch_num={ch_nums} stratum={strata} 总{total_wc}字")
        print(f"    文本开头: {sample_text}...")

print("\n" + "=" * 80)
print("验证完成")
print("=" * 80)
