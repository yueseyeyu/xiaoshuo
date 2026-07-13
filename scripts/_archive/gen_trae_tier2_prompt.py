#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成Trae Tier2评分指令（分段版）v2 — 修复所有问题"""
import sys, os, json
from pathlib import Path
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent.parent
TIER2_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "scores" / "tier2_batches"

# 加载采样计划
plan = json.load(open(TIER2_DIR / "_sampling_plan.json", 'r', encoding='utf-8'))
books = plan["books"]

# 按质量分级排序: S→A→B→C
TIER_ORDER = {"S": 0, "A": 1, "B": 2, "C": 3}
books.sort(key=lambda x: (TIER_ORDER.get(x["tier"], 9), x["book"]))

# 分段: 每段约43批, 共13段
SEG_SIZE = 43
total_batches = sum(b["batches"] for b in books)
n_segs = (total_batches + SEG_SIZE - 1) // SEG_SIZE

lines = []
lines.append(f"# Trae Tier2 评分任务（{n_segs}段分段版）")
lines.append("")
lines.append("你是一个网文评分专家。你需要阅读末世小说章节全文，逐章评分，并将结果写入JSON文件。")
lines.append("")
lines.append("## 项目根目录")
lines.append("d:\\Code\\xiaoshuo")
lines.append("")
lines.append("## 任务总览")
lines.append(f"- 总书数: {len(books)}本")
lines.append(f"- 总批次: {total_batches}批")
lines.append(f"- 总章节: {sum(b['sampled'] for b in books)}章")
lines.append(f"- 分段: {n_segs}段，每段约{SEG_SIZE}批")
lines.append("")
lines.append("## 评分维度")
lines.append("- t2_intensity: 1-10 爽感强度 (1=极度无聊, 10=极致爽感)")
lines.append("- t2_conflict: low/medium/high 冲突激烈程度")
lines.append("- t2_emotion: 日常/紧张/爽快/悬疑/压抑/感动/热血/悲壮/温馨 主要情绪基调")
lines.append("- t2_pace: slow/medium/fast 叙事节奏")
lines.append("- t2_hook: weak/medium/strong 章末悬念")
lines.append("- t2_retention: 1-10 读者追读下一章意愿")
lines.append("- t2_analysis: 20-100字中文评分理由")
lines.append("")
lines.append("## 评分JSON格式")
lines.append("```json")
lines.append("[")
lines.append("  {")
lines.append('    "ch_num": 9,')
lines.append('    "stratum": "Opening",')
lines.append('    "wc": 3326,')
lines.append('    "t2_intensity": 7,')
lines.append('    "t2_conflict": "medium",')
lines.append('    "t2_emotion": "悬疑",')
lines.append('    "t2_pace": "medium",')
lines.append('    "t2_hook": "strong",')
lines.append('    "t2_retention": 8,')
lines.append('    "t2_analysis": "开篇悬疑氛围浓厚，城市虚假设定引人入胜，结尾恶鬼揭示悬念强烈"')
lines.append("  }")
lines.append("]")
lines.append("```")
lines.append("")
lines.append("## ⚠️ 重要规则")
lines.append("1. **ch_num、stratum、wc** 必须和 `new_XX.json` 中的原始数据完全一致，不要修改")
lines.append("2. **scores_new_XX.json 中不要包含 text 字段**，只包含评分结果（避免文件过大）")
lines.append("3. **t2_intensity 和 t2_retention 是整数** (1-10)，不是字符串")
lines.append("4. **t2_conflict/t2_emotion/t2_pace/t2_hook 是字符串**，必须用上述指定的值")
lines.append("5. **t2_analysis 是中文**，20-100字，简短点评即可")
lines.append("6. 文件编码 UTF-8 无 BOM")
lines.append("")
lines.append("## 操作流程（每本书）")
lines.append("1. 读取该书目录下的 `new_XX.json`，检查是否已有 `scores_new_XX.json`，跳过已完成的")
lines.append("2. 逐批阅读章节全文（`text` 字段是章节正文）并评分")
lines.append("3. 将评分写入 `scores_new_XX.json`（UTF-8编码，无BOM）")
lines.append("4. **不要在 scores 文件中包含 text 字段**")
lines.append("5. 最后一个批次可能只有1章，正常评分")
lines.append("")
lines.append("## ⚠️ 每段完成后的质检步骤（必做）")
lines.append("每完成一段后，运行以下Python脚本质检：")
lines.append("```")
lines.append("cd d:\\Code\\xiaoshuo")
lines.append("python scripts/quality_check_tier2.py")
lines.append("```")
lines.append("质检脚本会检查：")
lines.append("- 每个scores_new_XX.json是否为合法JSON")
lines.append("- ch_num/stratum/wc是否与new_XX.json一致")
lines.append("- 评分值是否在合法范围内（t2_intensity 1-10, t2_retention 1-10等）")
lines.append("- t2_analysis是否为20-100字中文")
lines.append("- 是否包含text字段（不应该包含）")
lines.append("")
lines.append("如果质检报错，修复后再开始下一段。")
lines.append("")
lines.append("---")
lines.append("")

# 生成分段
seg_idx = 0
current_books = []
current_batches = 0

for book in books:
    current_books.append(book)
    current_batches += book["batches"]

    if current_batches >= SEG_SIZE or book == books[-1]:
        seg_idx += 1
        seg_batches = current_batches
        seg_chapters = sum(b["sampled"] for b in current_books)

        lines.append(f"## 第{seg_idx}段（{seg_batches}批，{len(current_books)}本）")
        lines.append("")

        for b in current_books:
            bdir = TIER2_DIR / b["book"]
            new_files = sorted(bdir.glob("new_*.json"))
            batch_nums = [int(f.stem.split("_")[-1]) for f in new_files]

            # 找出未完成的批次
            pending = []
            for bn in batch_nums:
                sf = bdir / f"scores_new_{bn:02d}.json"
                if not sf.exists():
                    pending.append(bn)

            if not pending:
                lines.append(f"### {b['book']}（{b['tier']}级 / {b['batches']}批 / 已全部完成）")
                lines.append(f"目录: `data/processed/末世/scores/tier2_batches/{b['book']}`")
                lines.append("✅ 跳过，已完成")
                lines.append("")
                continue

            lines.append(f"### {b['book']}（{b['tier']}级 / {b['batches']}总批次 / 待处理{len(pending)}批）")
            lines.append(f"目录: `data/processed/末世/scores/tier2_batches/{b['book']}`")
            pending_str = ", ".join(str(x) for x in pending[:30])
            if len(pending) > 30:
                pending_str += f", ...共{len(pending)}批"
            lines.append(f"待处理批次号: {pending_str}")
            lines.append("")

        lines.append(f"**第{seg_idx}段完成后**：运行 `python scripts/quality_check_tier2.py` 质检，确认无错后继续下一段。")
        lines.append("")
        lines.append("---")
        lines.append("")

        current_books = []
        current_batches = 0

lines.append(f"现在请开始第1段。")
lines.append("")
lines.append("## ⚠️ 重要提醒")
lines.append("- 评分字段用 `t2_` 前缀（不是 `ai_`），区分Tier1和Tier2")
lines.append("- 目录是 `tier2_batches/`（不是 `ai_annotate_batches/`）")
lines.append("- 质检脚本是 `quality_check_tier2.py`（不是 `quality_check.py`）")
lines.append("- scores文件中 **不要包含 text 字段**，只写评分结果")
lines.append("- t2_intensity 和 t2_retention 是 **整数**，不是字符串")

prompt_path = PROJECT_ROOT / "trae_tier1" / "PROMPT_TIER2_TRAE.md"
with open(prompt_path, 'w', encoding='utf-8') as f:
    f.write("\n".join(lines))
print(f"✅ Trae Tier2评分指令已保存: {prompt_path}")
print(f"总段数: {seg_idx}, 总批次: {total_batches}")
