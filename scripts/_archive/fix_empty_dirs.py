#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""修复空目录 + 重新生成GLM指令"""
import sys, os, json, re
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.dirname(__file__))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

import ai_annotate
ai_annotate.BATCH_SIZE = 2
from ai_annotate import extract_full_chapters, write_batches, get_book_batch_dir

PROJECT_ROOT = Path(__file__).parent.parent
BATCH_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "scores" / "ai_annotate_batches"
SCORES_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "scores"

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

# 检查所有书的new_文件数
print("=== 检查所有书的批次文件 ===")
need_reextract = []
for book in sorted(ALL_BOOKS.keys()):
    bdir = get_book_batch_dir(book)
    if not bdir.exists():
        print(f"  ❌ {book}: 目录不存在")
        need_reextract.append(book)
        continue
    new_files = list(bdir.glob("new_*.json"))
    if len(new_files) == 0:
        print(f"  ⚠️ {book}: 0个new_文件, 需重新提取")
        need_reextract.append(book)
    else:
        score_files = list(bdir.glob("scores_*.json"))
        print(f"  ✅ {book}: {len(new_files)}批, {len(score_files)}评分")

# 重新提取空目录的书
if need_reextract:
    print(f"\n=== 重新提取 {len(need_reextract)} 本 ===")
    for book in need_reextract:
        print(f"\n{book}:")
        chapters = extract_full_chapters(book)
        if chapters:
            paths = write_batches(chapters, book, prefix="new")
            print(f"  提取完成: {len(chapters)}章 → {len(paths)}批")
        else:
            print(f"  ❌提取失败!")

# 最终状态汇总
print("\n" + "=" * 70)
print("最终状态汇总")
print("=" * 70)

total_batches = 0
total_pending = 0
total_done = 0
book_list = []

for book in sorted(ALL_BOOKS.keys()):
    bdir = get_book_batch_dir(book)
    if not bdir.exists():
        continue
    new_files = sorted(bdir.glob("new_*.json"))
    n_total = len(new_files)
    if n_total == 0:
        continue

    n_done = 0
    pending_nums = []
    for nf in new_files:
        batch_num = int(nf.stem.split("_")[1])
        sf = bdir / f"scores_new_{batch_num:02d}.json"
        if sf.exists():
            n_done += 1
        else:
            pending_nums.append(batch_num)

    n_pending = n_total - n_done
    total_batches += n_total
    total_done += n_done
    total_pending += n_pending

    rel_dir = str(bdir.relative_to(PROJECT_ROOT)).replace("\\", "/")
    book_list.append({
        "name": book,
        "total": n_total,
        "done": n_done,
        "pending": n_pending,
        "batch_dir": rel_dir,
        "pending_nums": pending_nums,
    })

print(f"总批次: {total_batches}, 已完成: {total_done}, 待处理: {total_pending}")
print(f"需评分书籍: {len(book_list)}本")

# 生成GLM指令
book_list.sort(key=lambda x: x["pending"])

lines = []
lines.append("# GLM Tier1 AI评分任务")
lines.append("")
lines.append("你是一个网文评分专家。你需要阅读末世小说章节全文，逐章评分，并将结果写入JSON文件。")
lines.append("")
lines.append("## 项目根目录")
lines.append("d:\\Code\\xiaoshuo")
lines.append("")
lines.append(f"## 任务总览：{len(book_list)}本书，共{total_pending}批待处理")
lines.append("")
lines.append("| # | 书名 | 批次目录 | 总批次 | 已完成 | 待处理 |")
lines.append("|---|------|----------|--------|--------|--------|")
for i, b in enumerate(book_list, 1):
    lines.append(f"| {i} | {b['name']} | {b['batch_dir']} | {b['total']} | {b['done']} | {b['pending']} |")
lines.append("")
lines.append("## 评分维度")
lines.append("- ai_intensity: 1-10 爽感强度 (1=极度无聊, 10=极致爽感)")
lines.append("- ai_conflict: low/medium/high 冲突激烈程度")
lines.append("- ai_emotion: 日常/紧张/爽快/悬疑/压抑/感动/热血/悲壮/温馨 主要情绪基调")
lines.append("- ai_pace: slow/medium/fast 叙事节奏")
lines.append("- ai_hook: weak/medium/strong 章末悬念")
lines.append("- ai_retention: 1-10 读者追读下一章意愿")
lines.append("- ai_analysis: 20-50字中文评分理由")
lines.append("")
lines.append("## 操作流程（每本书重复以下步骤）")
lines.append("")
lines.append("### 第1步：列出待处理批次")
lines.append("读取该书目录下的所有 `new_XX.json` 文件名，检查同目录下是否已有 `scores_new_XX.json`。")
lines.append("已有 scores_new_XX.json 的批次直接跳过，只处理缺失的。")
lines.append("")
lines.append("### 第2步：逐批评分")
lines.append("对每个待处理批次：")
lines.append("1. 读取 `new_XX.json`（包含2章全文）")
lines.append("2. 仔细阅读每章全文")
lines.append("3. 按评分维度打分")
lines.append("4. 将评分写入 `scores_new_XX.json`")
lines.append("")
lines.append("### 第3步：输出JSON格式")
lines.append("```json")
lines.append("[")
lines.append("  {")
lines.append('    "ch_num": 1,')
lines.append('    "stratum": "Opening",')
lines.append('    "wc": 3502,')
lines.append('    "ai_intensity": 7,')
lines.append('    "ai_conflict": "medium",')
lines.append('    "ai_emotion": "悬疑",')
lines.append('    "ai_pace": "medium",')
lines.append('    "ai_hook": "strong",')
lines.append('    "ai_retention": 8,')
lines.append('    "ai_analysis": "开篇悬疑氛围浓厚，城市虚假设定引人入胜，结尾恶鬼揭示悬念强烈"')
lines.append("  },")
lines.append("  {")
lines.append('    "ch_num": 9,')
lines.append('    "stratum": "Rising",')
lines.append('    "wc": 3144,')
lines.append('    "ai_intensity": 4,')
lines.append('    "ai_conflict": "low",')
lines.append('    "ai_emotion": "悬疑",')
lines.append('    "ai_pace": "slow",')
lines.append('    "ai_hook": "medium",')
lines.append('    "ai_retention": 6,')
lines.append('    "ai_analysis": "信息揭示章节，调查线推进，妈妈善意反转为温情"')
lines.append("  }")
lines.append("]")
lines.append("```")
lines.append("")
lines.append("**重要**：ch_num、stratum、wc 必须和 new_XX.json 中的原始数据完全一致。")
lines.append("")
lines.append("## 注意事项")
lines.append("- 已有 scores_new_XX.json 的批次直接跳过")
lines.append("- 最后一个批次可能只有1章，正常评分")
lines.append("- 每完成一本书报告进度，再开始下一本")
lines.append("")
lines.append("## 各书待处理批次明细")
lines.append("")

for i, b in enumerate(book_list, 1):
    lines.append(f"### {i}. {b['name']}（{b['pending']}批待处理 / {b['total']}总批次）")
    lines.append(f"目录: `{b['batch_dir']}`")
    nums = [str(n) for n in b["pending_nums"]]
    if len(nums) > 30:
        lines.append(f"待处理批次号: {', '.join(nums[:30])}, ...共{len(nums)}批")
    elif nums:
        lines.append(f"待处理批次号: {', '.join(nums)}")
    else:
        lines.append("（无待处理批次，此书已完成）")
    lines.append("")

if book_list:
    lines.append(f"现在请开始处理第一本书「{book_list[0]['name']}」。")

output = "\n".join(lines)
out_path = PROJECT_ROOT / "trae_tier1" / "PROMPT_GLM_UNFINISHED.md"
with open(out_path, "w", encoding="utf-8") as f:
    f.write(output)

print(f"\n已生成: {out_path}")
print(f"总批次: {total_batches}, 已完成: {total_done}, 待处理: {total_pending}")
print(f"\n书籍清单:")
for b in book_list:
    print(f"  {b['name']:<28} 待处理{b['pending']:>4}批 (已完成{b['done']}/{b['total']})")
