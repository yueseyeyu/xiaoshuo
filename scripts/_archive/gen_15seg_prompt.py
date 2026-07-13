#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成15段分段GLM指令，每段含质检步骤"""
import sys, os, json, re, math
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.dirname(__file__))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

import ai_annotate
ai_annotate.BATCH_SIZE = 2
from ai_annotate import get_book_batch_dir

PROJECT_ROOT = Path(__file__).parent.parent

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

# 收集每本书的待处理批次
book_list = []
total_pending = 0
total_done = 0
total_batches = 0

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
        batch_num = int(nf.stem.split("_")[-1])
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

book_list.sort(key=lambda x: x["pending"], reverse=True)  # 大的在前，方便分配

print(f"总批次: {total_batches}, 已完成: {total_done}, 待处理: {total_pending}")
print(f"已有评分的书: {[b['name'] for b in book_list if b['done'] > 0]}")

# 分15段：按待处理量均匀分配
# 贪心算法：按pending降序，依次分到当前最小的段
N_SEGMENTS = 15
segments = [[] for _ in range(N_SEGMENTS)]
segment_sizes = [0] * N_SEGMENTS

for book in book_list:
    if book["pending"] == 0:
        continue
    # 找当前最小的段
    min_idx = segment_sizes.index(min(segment_sizes))
    segments[min_idx].append(book)
    segment_sizes[min_idx] += book["pending"]

print(f"\n15段分配:")
for i, (seg, size) in enumerate(zip(segments, segment_sizes), 1):
    books_str = ", ".join(f"{b['name']}({b['pending']})" for b in seg)
    print(f"  段{i:>2}: {size:>4}批 — {books_str}")

# 生成指令
lines = []
lines.append("# GLM Tier1 AI评分任务（15段分段版）")
lines.append("")
lines.append("你是一个网文评分专家。你需要阅读末世小说章节全文，逐章评分，并将结果写入JSON文件。")
lines.append("")
lines.append("## 项目根目录")
lines.append("d:\\Code\\xiaoshuo")
lines.append("")
lines.append(f"## 任务总览")
lines.append(f"- 总书数: {len(book_list)}本")
lines.append(f"- 总批次: {total_batches}批")
lines.append(f"- 已完成: {total_done}批（4本书有历史有效评分）")
lines.append(f"- 待处理: {total_pending}批")
lines.append(f"- 分段: {N_SEGMENTS}段，每段约{total_pending//N_SEGMENTS}批")
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
lines.append("## 评分JSON格式")
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
lines.append("  }")
lines.append("]")
lines.append("```")
lines.append("")
lines.append("**重要**：ch_num、stratum、wc 必须和 new_XX.json 中的原始数据完全一致。")
lines.append("")
lines.append("## 操作流程（每本书）")
lines.append("1. 读取该书目录下的 `new_XX.json`，检查是否已有 `scores_new_XX.json`，跳过已完成的")
lines.append("2. 逐批阅读章节全文并评分")
lines.append("3. 将评分写入 `scores_new_XX.json`（UTF-8编码，无BOM）")
lines.append("4. 最后一个批次可能只有1章，正常评分")
lines.append("")
lines.append("## ⚠️ 每段完成后的质检步骤（必做）")
lines.append("每完成一段后，运行以下Python脚本质检：")
lines.append("```")
lines.append("cd d:\\Code\\xiaoshuo")
lines.append("python scripts/quality_check.py")
lines.append("```")
lines.append("质检脚本会检查：")
lines.append("- 每个scores_new_XX.json是否为合法JSON")
lines.append("- ch_num/stratum/wc是否与new_XX.json一致")
lines.append("- 评分值是否在合法范围内（intensity 1-10, retention 1-10等）")
lines.append("- ai_analysis是否为非空中文")
lines.append("")
lines.append("如果质检报错，修复后再开始下一段。")
lines.append("")
lines.append("---")
lines.append("")

# 每段详细内容
for seg_idx, seg_books in enumerate(segments, 1):
    seg_pending = sum(b["pending"] for b in seg_books)
    lines.append(f"## 第{seg_idx}段（{seg_pending}批，{len(seg_books)}本）")
    lines.append("")

    # 按pending升序列出（先做小的）
    seg_books_sorted = sorted(seg_books, key=lambda x: x["pending"])
    for b in seg_books_sorted:
        lines.append(f"### {b['name']}（{b['pending']}批待处理 / {b['total']}总批次 / 已完成{b['done']}批）")
        lines.append(f"目录: `{b['batch_dir']}`")
        nums = [str(n) for n in b["pending_nums"]]
        if len(nums) > 30:
            lines.append(f"待处理批次号: {', '.join(nums[:30])}, ...共{len(nums)}批")
        elif nums:
            lines.append(f"待处理批次号: {', '.join(nums)}")
        else:
            lines.append("（此书已完成，跳过）")
        lines.append("")

    lines.append(f"**第{seg_idx}段完成后**：运行 `python scripts/quality_check.py` 质检，确认无错后继续下一段。")
    lines.append("")
    lines.append("---")
    lines.append("")

# 生成质检脚本
lines.append("现在请开始第1段。")

output = "\n".join(lines)
out_path = PROJECT_ROOT / "trae_tier1" / "PROMPT_GLM_UNFINISHED.md"
with open(out_path, "w", encoding="utf-8") as f:
    f.write(output)

print(f"\n已生成: {out_path}")
print(f"总行数: {len(output.splitlines())}")
print(f"文件大小: {len(output.encode('utf-8'))} bytes")
