#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成最终准确的GLM评分指令 — 基于修复后的审计结果"""
import sys, os, json, re
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent.parent
BATCH_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "scores" / "ai_annotate_batches"

def get_book_dir(book_name):
    if book_name == "废土崛起":
        return BATCH_DIR
    return BATCH_DIR / book_name

def get_pending_batches(book_name):
    """获取需要评分的批次号列表"""
    bdir = get_book_dir(book_name)
    if not bdir.exists():
        return [], 0
    all_batches = sorted(bdir.glob("new_*.json"))
    pending = []
    total = len(all_batches)
    for bf in all_batches:
        batch_num = int(bf.stem.split("_")[1])
        score_file = bdir / f"scores_new_{batch_num:02d}.json"
        if not score_file.exists():
            pending.append(batch_num)
    return pending, total

# 所有33本书
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

# 收集所有需要评分的书籍
books_to_score = []
books_complete = []

for book_name in sorted(ALL_BOOKS.keys()):
    pending, total = get_pending_batches(book_name)
    if not pending:
        if total > 0:
            books_complete.append(book_name)
        continue
    bdir = get_book_dir(book_name)
    rel_dir = str(bdir.relative_to(PROJECT_ROOT)).replace("\\", "/")
    books_to_score.append({
        "name": book_name,
        "pending": len(pending),
        "total": total,
        "done": total - len(pending),
        "batch_dir": rel_dir,
        "pending_nums": pending,
    })

# 按待处理量排序
books_to_score.sort(key=lambda x: x["pending"])

# 生成指令
lines = []
lines.append("你是一个网文评分专家。你需要阅读末世小说章节全文，逐章评分，并将结果写入JSON文件。")
lines.append("")
lines.append("## 项目根目录")
lines.append("d:\\Code\\xiaoshuo")
lines.append("")
lines.append(f"## 你负责的书（{len(books_to_score)}本，共{sum(b['pending'] for b in books_to_score)}批待处理）")
lines.append("")
lines.append("| # | 书名 | 批次目录 | 总批次 | 已完成 | 待处理 |")
lines.append("|---|------|----------|--------|--------|--------|")
for i, b in enumerate(books_to_score, 1):
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

for i, b in enumerate(books_to_score, 1):
    lines.append(f"### {i}. {b['name']}（{b['pending']}批待处理）")
    lines.append(f"目录: `{b['batch_dir']}`")
    lines.append(f"总批次: {b['total']}, 已完成: {b['done']}, 待处理: {b['pending']}")
    nums = [str(n) for n in b["pending_nums"]]
    if len(nums) > 20:
        lines.append(f"待处理批次号: {', '.join(nums[:20])}, ...共{len(nums)}批")
    else:
        lines.append(f"待处理批次号: {', '.join(nums)}")
    lines.append("")

lines.append(f"现在请开始处理第一本书「{books_to_score[0]['name']}」。")

# 写入文件
output = "\n".join(lines)
out_path = PROJECT_ROOT / "trae_tier1" / "PROMPT_GLM_UNFINISHED.md"
with open(out_path, "w", encoding="utf-8") as f:
    f.write(output)

print(f"已生成: {out_path}")
print(f"需评分书籍: {len(books_to_score)}本")
print(f"已完成书籍(仅需合并CSV): {len(books_complete)}本 — {books_complete}")
print(f"待处理批次: {sum(b['pending'] for b in books_to_score)}批")
print(f"\n书籍清单:")
for b in books_to_score:
    print(f"  {b['name']:<28} 待处理{b['pending']:>4}批 (已完成{b['done']}/{b['total']})")
