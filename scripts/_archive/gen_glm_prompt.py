#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成GLM评分指令文件"""
import sys, os, json, math, re
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "novels" / "末世"
SCORES_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "scores"
BATCH_DIR = SCORES_DIR / "ai_annotate_batches"

from xiaoshuo.pipeline.rhythm.chapter_parser import extract_chapters

# 加载书籍列表
INDEX_PATH = PROJECT_ROOT / "data" / "raw" / "novel_index.json"
with open(INDEX_PATH, 'r', encoding='utf-8') as f:
    idx = json.load(f)

BOOKS = {}
for n in idx.get('genres', {}).get('末世', {}).get('novels', []):
    fname = n['file']
    short = fname.replace('.txt', '')
    if short.startswith('《'):
        m = re.search(r'《(.+?)》', short)
        short = m.group(1) if m else short
    BOOKS[short] = fname

STRATA = [
    {"name": "Opening", "start": 0.00, "end": 0.03},
    {"name": "Rising",  "start": 0.03, "end": 0.30},
    {"name": "Mid",     "start": 0.30, "end": 0.60},
    {"name": "Climax",  "start": 0.60, "end": 0.90},
    {"name": "Ending",  "start": 0.90, "end": 1.00},
]
SAMPLE_RATE = 0.10

def get_book_dir(book_name):
    if book_name == "废土崛起":
        return BATCH_DIR
    return BATCH_DIR / book_name

def get_batch_info(book_name):
    """获取书籍的批次和评分状态"""
    bdir = get_book_dir(book_name)
    if not bdir.exists():
        return [], set()

    batches = sorted(bdir.glob("new_*.json"))
    scored_chs = set()

    for sf in sorted(bdir.glob("scores_*.json")):
        try:
            with open(sf, 'r', encoding='utf-8') as f:
                for row in json.load(f):
                    if 'ch_num' in row:
                        scored_chs.add(int(row['ch_num']))
        except:
            pass

    # 确定哪些批次需要评分
    pending = []
    for bf in batches:
        batch_num = int(bf.stem.split("_")[1])
        score_file = bdir / f"scores_new_{batch_num:02d}.json"
        if score_file.exists():
            continue  # 已有评分文件，跳过

        # 读取批次内容获取ch_num
        try:
            with open(bf, 'r', encoding='utf-8') as f:
                batch_data = json.load(f)
            chs = [r["ch_num"] for r in batch_data]
            # 检查是否所有章节都已评分
            if all(ch in scored_chs for ch in chs):
                continue
            pending.append((batch_num, chs))
        except:
            pass

    return pending, scored_chs


# 跳过已完成的书籍
SKIP_BOOKS = {"废土崛起", "末世超级商人", "我的女友是丧尸", "末世之深渊召唤师",
              "末世召唤狂潮", "末世大回炉", "末世魔神游戏", "末日乐园",
              "末日拼图游戏", "末日蟑螂", "我 的 末 世 领 地", "神秘尽头",
              "蹉跎", "重卡战车在末世", "长夜余火", "限制级末日症候",
              "黑暗血时代", "全球变异，从灾厄降临开始"}

# 收集未完成书籍
books_info = []
for book_name, txt_file in sorted(BOOKS.items()):
    if book_name in SKIP_BOOKS:
        continue

    txt_path = RAW_DIR / txt_file
    if not txt_path.exists():
        continue

    chapters = extract_chapters(str(txt_path))
    total = len(chapters)
    if total == 0:
        continue

    expected = 0
    for s in STRATA:
        si = int(total * s["start"])
        ei = int(total * s["end"])
        if ei <= si:
            continue
        n = max(1, math.ceil((ei - si) * SAMPLE_RATE))
        expected += min(n, ei - si)

    pending, scored_chs = get_batch_info(book_name)
    if not pending:
        continue

    bdir = get_book_dir(book_name)
    rel_dir = str(bdir.relative_to(PROJECT_ROOT)).replace("\\", "/")

    books_info.append({
        "name": book_name,
        "total_chapters": total,
        "expected_sample": expected,
        "scored": len(scored_chs),
        "pending_batches": len(pending),
        "pending_list": pending,
        "batch_dir": rel_dir,
        "total_batches": len(list(bdir.glob("new_*.json"))),
    })

# 按待评批量排序（少的先做，快速完成）
books_info.sort(key=lambda x: x["pending_batches"])

# 生成指令文件
lines = []
lines.append("你是一个网文评分专家。你需要阅读末世小说章节全文，逐章评分，并将结果写入JSON文件。")
lines.append("")
lines.append("## 项目根目录")
lines.append("d:\\Code\\xiaoshuo")
lines.append("")
lines.append(f"## 你负责的书（{len(books_info)}本，共{sum(b['pending_batches'] for b in books_info)}批待处理）")
lines.append("")
lines.append("| # | 书名 | 批次目录 | 总批次 | 已完成 | 待处理 |")
lines.append("|---|------|----------|--------|--------|--------|")
for i, b in enumerate(books_info, 1):
    lines.append(f"| {i} | {b['name']} | {b['batch_dir']} | {b['total_batches']} | {b['total_batches'] - b['pending_batches']} | {b['pending_batches']} |")
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

for i, b in enumerate(books_info, 1):
    lines.append(f"### {i}. {b['name']}（{b['pending_batches']}批待处理）")
    lines.append(f"目录: `{b['batch_dir']}`")
    lines.append(f"总章节: {b['total_chapters']}, 10%采样: {b['expected_sample']}章, 已评分: {b['scored']}章")
    if b["pending_list"]:
        batch_nums = [str(p[0]) for p in b["pending_list"]]
        # 如果批次太多，分行显示
        if len(batch_nums) > 20:
            lines.append(f"待处理批次号: {', '.join(batch_nums[:20])}, ...共{len(batch_nums)}批")
        else:
            lines.append(f"待处理批次号: {', '.join(batch_nums)}")
    lines.append("")

lines.append(f"现在请开始处理第一本书「{books_info[0]['name']}」。")

# 写入文件
output = "\n".join(lines)
out_path = PROJECT_ROOT / "trae_tier1" / "PROMPT_GLM_UNFINISHED.md"
with open(out_path, "w", encoding="utf-8") as f:
    f.write(output)

print(f"已生成: {out_path}")
print(f"书籍数: {len(books_info)}")
print(f"待处理批次: {sum(b['pending_batches'] for b in books_info)}")
print(f"\n书籍清单:")
for b in books_info:
    print(f"  {b['name']:<28} 待处理{b['pending_batches']:>3}批 ({b['scored']}/{b['expected_sample']}章已评)")
