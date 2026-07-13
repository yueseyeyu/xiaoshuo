#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Extract chapters for human annotation - 4 books x 10 chapters = 40 chapters"""
import csv, json, re
from pathlib import Path

PROJECT = Path("d:/Code/xiaoshuo")
TIER3 = PROJECT / "data" / "golden" / "\u672b\u4e16" / "tier3"
RAW = PROJECT / "data" / "raw" / "novels" / "\u672b\u4e16"
OUT = PROJECT / "data" / "golden" / "\u672b\u4e16" / "tier3" / "human_annotate_materials"
OUT.mkdir(parents=True, exist_ok=True)

books = ["\u672b\u65e5\u4e50\u56ed", "\u7b2c\u4e00\u5e8f\u5217", "\u957f\u591c\u4f59\u706b", "\u9ed1\u6697\u8840\u65f6\u4ee3"]

def extract_chapters(txt_path, ch_nums):
    """Extract specified chapters from novel txt"""
    try:
        with open(txt_path, 'r', encoding='utf-8') as f:
            text = f.read()
    except UnicodeDecodeError:
        with open(txt_path, 'r', encoding='gb18030', errors='replace') as f:
            text = f.read()
    
    # Split by chapter marker - common patterns
    # Pattern: 第X章 or 第一章 etc
    pattern = r'(\u7b2c[\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\u5343\u96f6\u0030-\u0039]+\u7ae0)'
    parts = re.split(pattern, text)
    
    chapters = {}
    current_ch = 0
    current_title = ""
    
    for i, part in enumerate(parts):
        m = re.match(r'\u7b2c([\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\u5343\u96f6\u0030-\u0039]+)\u7ae0', part)
        if m:
            # Convert Chinese number to int
            cn = m.group(1)
            try:
                num = int(cn)
            except:
                # Try Chinese number conversion
                cn_map = {"\u4e00":1,"\u4e8c":2,"\u4e09":3,"\u56db":4,"\u4e94":5,"\u516d":6,"\u4e03":7,"\u516b":8,"\u4e5d":9,"\u5341":10}
                if cn == "\u5341":
                    num = 10
                elif cn.startswith("\u5341") and len(cn) == 2:
                    num = 10 + cn_map.get(cn[1], 0)
                elif len(cn) == 2 and cn[1] == "\u5341":
                    num = cn_map.get(cn[0], 1) * 10
                elif len(cn) == 3 and cn[1] == "\u5341":
                    num = cn_map.get(cn[0], 1) * 10 + cn_map.get(cn[2], 0)
                elif len(cn) == 2:
                    num = cn_map.get(cn[0], 1) * 10 + cn_map.get(cn[1], 0)
                else:
                    num = 0
            current_ch = num
            current_title = part
        elif current_ch > 0:
            if current_ch in ch_nums:
                chapters[current_ch] = {
                    "title": current_title,
                    "text": part.strip()[:5000]  # cap at 5000 chars
                }
    
    return chapters

# Process each book
for book in books:
    plan_csv = TIER3 / f"{book}_tier3_plan.csv"
    if not plan_csv.exists():
        continue
    
    # Read plan
    plan = []
    with open(plan_csv, 'r', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            plan.append(row)
    
    # Select 10 chapters: all anchors + top disagreements
    anchors = [r for r in plan if r["source"] == "anchor"]
    disagreements = sorted([r for r in plan if r["source"] == "disagreement"], 
                          key=lambda x: float(x.get("disagreement", 0)), reverse=True)
    
    selected = anchors[:5] + disagreements[:5]
    ch_nums = set(int(r["ch_num"]) for r in selected)
    
    # Find txt file
    txt_candidates = list(RAW.glob(f"*{book[:4]}*.txt"))
    if not txt_candidates:
        txt_candidates = list(RAW.glob(f"*{book[:2]}*.txt"))
    
    if not txt_candidates:
        # Try exact match
        for f in RAW.glob("*.txt"):
            if book in f.name:
                txt_candidates = [f]
                break
    
    if not txt_candidates:
        continue
    
    txt_path = txt_candidates[0]
    
    # Extract chapters
    chapters = extract_chapters(txt_path, ch_nums)
    
    # Write output file
    out_file = OUT / f"{book}_human_annotate.md"
    lines = []
    lines.append(f"# {book} - 人工标注材料\n")
    lines.append(f"源文件: {txt_path.name}\n")
    lines.append(f"待标注章节: {len(selected)}\n\n")
    lines.append("---\n\n")
    
    for row in selected:
        cn = int(row["ch_num"])
        lines.append(f"## 第{cn}章 ({row['source']}/{row['stratum']})\n")
        lines.append(f"**AI评分**: intensity={row['ai_intensity']}, retention={row['ai_retention']}\n")
        lines.append(f"**T2评分**: intensity={row['t2_intensity']}, retention={row['t2_retention']}\n")
        lines.append(f"**分歧度**: {row['disagreement']}\n\n")
        
        ch = chapters.get(cn)
        if ch:
            lines.append(f"### 章节标题: {ch['title']}\n\n")
            lines.append(ch['text'][:3000])
            if len(ch['text']) > 3000:
                lines.append("\n\n[...章节过长，已截断...]")
        else:
            lines.append("[章节提取失败]")
        
        lines.append("\n\n---\n")
        lines.append("**你的评分**:\n")
        lines.append("- human_intensity (1-10, 爽感强度): \n")
        lines.append("- human_retention (1-10, 追读意愿): \n")
        lines.append("- 备注(可选): \n")
        lines.append("\n---\n\n")
    
    with open(out_file, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))

# Write summary
summary = []
summary.append("# 人工标注材料总览\n\n")
summary.append("| 书名 | 章节数 | 文件 |\n")
summary.append("|------|--------|------|\n")
for book in books:
    out_file = OUT / f"{book}_human_annotate.md"
    if out_file.exists():
        plan_csv = TIER3 / f"{book}_tier3_plan.csv"
        with open(plan_csv, 'r', encoding='utf-8-sig') as f:
            n = sum(1 for _ in csv.DictReader(f))
        selected_n = min(10, n)
        summary.append(f"| {book} | {selected_n} | {out_file.name} |\n")

summary.append(f"\n输出目录: {OUT}\n")
summary.append("\n## 评分说明\n\n")
summary.append("每个章节后填写:\n")
summary.append("- **human_intensity** (1-10整数): 爽感强度, 1=极度无聊, 10=极致爽感\n")
summary.append("- **human_retention** (1-10整数): 追读意愿, 1=立刻弃书, 10=迫不及待看下一章\n")
summary.append("- **备注**(可选): 评分理由\n")

with open(OUT / "_README.md", 'w', encoding='utf-8') as f:
    f.write("".join(summary))
