#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
生成盲评版人工标注材料（不暴露任何AI评分）
=============================================
7本S级书 × 8-10章 = ~65章
关键设计: 标注者看不到任何AI/T2/GLM分数，确保独立判断
"""
import json
import os
from pathlib import Path

PROJECT = Path(r"d:\Code\xiaoshuo")
TIER3 = PROJECT / "data" / "golden" / "末世" / "tier3"
GLM_JSON = TIER3 / "tier3_glm_scores.json"
OUT_DIR = TIER3 / "human_annotate_materials"

# S级5本 + 补充2本(已有golden的书保留)
S_BOOKS = ["地球游戏场", "异兽迷城", "末世大回炉", "黑暗血时代", "第一序列"]
# 末日乐园和长夜余火已降为A级，但仍可标注作为补充数据
EXTRA_BOOKS = ["末日乐园", "长夜余火"]

CRITERIA = """# 评分标准

请阅读每个章节的正文，然后给出以下评分:

## intensity (爽感强度 1-10整数)
- 1-2: 极度无聊，读者想跳过
- 3-4: 略有乏味，缺乏吸引力
- 5-6: 中等水平，可读但不兴奋
- 7-8: 较强吸引力，有明确爽点或悬念
- 9-10: 极致体验，让人欲罢不能

## retention (追读意愿 1-10整数)
- 1-2: 立刻弃书
- 3-4: 可能跳过，不太关心后续
- 5-6: 一般好奇，会继续看
- 7-8: 比较期待下一章
- 9-10: 迫不及待必须看下一章

## 评分要点
- 以"我作为读者阅读这一章的真实感受"为准
- 不要因为文笔好就给高分 — 关键是"这一章让我想继续看下去吗"
- 大多数章节应该在4-7分区间，8分以上应该是少数
- 3分以下也不应太多 — 只有真正无聊到想跳过的才给低分
- 前后章节的评分要有相对差异，不要全部给5-6分
"""

def read_chapter_text(book_name, ch_num):
    """Read chapter text from the chapter files."""
    padded = f"ch{ch_num:04d}.txt"
    ch_file = TIER3 / f"{book_name}_chapters" / padded
    if ch_file.exists():
        with open(ch_file, 'r', encoding='utf-8') as f:
            return f.read()
    ch_file = TIER3 / f"{book_name}_chapters" / f"ch{ch_num}.txt"
    if ch_file.exists():
        with open(ch_file, 'r', encoding='utf-8') as f:
            return f.read()
    return None

def generate_for_book(book_name, chapters):
    """Generate blind annotation material for one book."""
    lines = []
    lines.append(f"# {book_name} — 人工盲评标注")
    lines.append(f"")
    lines.append(f"待标注章节数: {len(chapters)}")
    lines.append(f"")
    lines.append(f"**重要: 以下章节不含任何AI预评分，请完全基于你的阅读体验独立评分。**")
    lines.append(f"")
    lines.append(CRITERIA)
    lines.append(f"---")
    lines.append(f"")
    
    found = 0
    for ch in chapters:
        ch_num = ch["ch_num"]
        text = read_chapter_text(book_name, ch_num)
        
        if text is None:
            lines.append(f"## 第{ch_num}章")
            lines.append(f"[章节文本缺失，跳过]")
            lines.append(f"")
            continue
        
        found += 1
        lines.append(f"## 第{ch_num}章")
        lines.append(f"")
        lines.append(text.strip())
        lines.append(f"")
        lines.append(f"### 你的评分")
        lines.append(f"- intensity: ___ (1-10)")
        lines.append(f"- retention: ___ (1-10)")
        lines.append(f"- 备注(可选): ___")
        lines.append(f"")
        lines.append(f"---")
        lines.append(f"")
    
    safe_name = book_name.replace("/", "_").replace("\\", "_")
    out_file = OUT_DIR / f"{safe_name}_human_blind.md"
    with open(out_file, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))
    
    return found, out_file

def main():
    with open(GLM_JSON, 'r', encoding='utf-8') as f:
        glm_data = json.load(f)
    
    all_books = S_BOOKS + EXTRA_BOOKS
    
    # Also generate for books that already have golden but need more chapters
    # (废土崛起, 末日蟑螂 already have 10 chapters each)
    
    print("Generating blind annotation materials...")
    print()
    
    total = 0
    for book_name in all_books:
        chapters = glm_data.get("scores", {}).get(book_name, [])
        if not chapters:
            print(f"  [SKIP] {book_name}: no chapter data in GLM JSON")
            continue
        
        found, out_file = generate_for_book(book_name, chapters)
        total += found
        print(f"  [OK] {book_name}: {found} chapters -> {out_file.name}")
    
    # Write master README
    readme = []
    readme.append("# 人工盲评标注材料 — 使用说明")
    readme.append("")
    readme.append("## 目标")
    readme.append("扩大人工标注从30章→60+章，覆盖7本S/A级书，人工占比提升至48%+。")
    readme.append("")
    readme.append("## 文件清单")
    readme.append("")
    readme.append("| 书名 | 章节数 | 文件 | 状态 |")
    readme.append("|------|--------|------|------|")
    
    for book_name in all_books:
        chapters = glm_data.get("scores", {}).get(book_name, [])
        safe = book_name.replace("/", "_").replace("\\", "_")
        n = len(chapters)
        existing = "已有golden" if book_name in ["末世大回炉"] else "新增"
        readme.append(f"| {book_name} | {n} | {safe}_human_blind.md | {existing} |")
    
    readme.append("")
    readme.append("## 操作步骤")
    readme.append("")
    readme.append("1. 逐个打开 `{书名}_human_blind.md`")
    readme.append("2. 阅读每章正文，独立给出 intensity 和 retention 评分")
    readme.append("3. 将评分汇总到CSV格式:")
    readme.append("   ```")
    readme.append("   book,ch_num,human_intensity,human_retention,note")
    readme.append("   地球游戏场,1,5,6,经典开局但套路")
    readme.append("   ...")
    readme.append("   ```")
    readme.append("4. 保存为 `data/golden/末世/human_golden_v2.csv`")
    readme.append("")
    readme.append("## 关键设计")
    readme.append("- **盲评**: 标注材料中不含任何AI/T2/GLM分数，避免锚定偏差")
    readme.append("- **相同章节**: 使用与GLM/DeepSeek评分相同的章节，便于四方对比")
    readme.append("- **独立进行**: 与DeepSeek交叉验证完全独立，互不影响")
    readme.append("")
    readme.append("## 现有golden数据 (已标注，保留)")
    readme.append("- 废土崛起: 10章")
    readme.append("- 末日蟑螂: 10章")  
    readme.append("- 末世大回炉: 10章")
    readme.append(f"- 本次新增: ~{total}章")
    readme.append(f"- 合计预期: ~{30 + total}章")
    
    readme_file = OUT_DIR / "_盲评使用说明.md"
    with open(readme_file, 'w', encoding='utf-8') as f:
        f.write("\n".join(readme))
    
    print()
    print(f"Total: {total} chapters across {len(all_books)} books")
    print(f"After completion: {30 + total} total human golden chapters")
    print(f"Master README: {readme_file}")

if __name__ == "__main__":
    main()
