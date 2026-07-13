#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""提取所有Tier3章节的关键信息，供GLM批量评分"""
import io, sys, csv, json, os, re
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PROJECT = Path(__file__).parent.parent
TIER3_DIR = PROJECT / "data" / "golden" / "末世" / "tier3"
GOLDEN_CSV = PROJECT / "data" / "golden" / "末世" / "human_golden.csv"

# 已有golden标注
existing_golden = set()
if GOLDEN_CSV.exists():
    with open(GOLDEN_CSV, 'r', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            book = row.get("book", "")
            ch = int(row.get("ch_num", 0))
            existing_golden.add((book, ch))

books = ["地球游戏场", "异兽迷城", "末日乐园", "第一序列", "长夜余火", "黑暗血时代", "末世大回炉"]
all_chapters = []

for book in books:
    ch_dir = TIER3_DIR / f"{book}_chapters"
    plan_csv = TIER3_DIR / f"{book}_tier3_plan.csv"
    
    if not ch_dir.exists() or not plan_csv.exists():
        continue
    
    # 读取计划
    plan = {}
    with open(plan_csv, 'r', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            plan[int(row["ch_num"])] = row
    
    for ch_num, row in sorted(plan.items()):
        if (book, ch_num) in existing_golden:
            continue
        
        ch_file = ch_dir / f"ch{ch_num:04d}.txt"
        if not ch_file.exists():
            continue
        
        text = ch_file.read_text(encoding="utf-8", errors="replace")
        wc = len(text)
        
        # 提取关键信息
        # 去除多余空白
        text_clean = re.sub(r'\s+', ' ', text).strip()
        
        # 开头300字
        head = text_clean[:300]
        # 结尾200字
        tail = text_clean[-200:] if len(text_clean) > 300 else ""
        # 中间片段200字 (取25%-45%位置)
        mid_start = int(len(text_clean) * 0.25)
        mid = text_clean[mid_start:mid_start+200]
        
        all_chapters.append({
            "book": book,
            "ch_num": ch_num,
            "wc": wc,
            "source": row.get("source", ""),
            "stratum": row.get("stratum", ""),
            "ai_i": row.get("ai_intensity", ""),
            "ai_r": row.get("ai_retention", ""),
            "t2_i": row.get("t2_intensity", ""),
            "t2_r": row.get("t2_retention", ""),
            "disagree": row.get("disagreement", ""),
            "head": head,
            "mid": mid,
            "tail": tail,
        })

print(f"总计: {len(all_chapters)}章需要评分")

# 按书分组输出
for book in books:
    chs = [c for c in all_chapters if c["book"] == book]
    if not chs:
        continue
    
    print(f"\n{'='*60}")
    print(f"### {book} ({len(chs)}章)")
    print(f"{'='*60}")
    
    for ch in chs:
        print(f"\n--- ch{ch['ch_num']} ({ch['wc']}字) [{ch['source']}/{ch['stratum']}] ---")
        print(f"AI: I={ch['ai_i']} R={ch['ai_r']} | T2: I={ch['t2_i']} R={ch['t2_r']} | Δ={ch['disagree']}")
        print(f"[开头] {ch['head']}")
        print(f"[中段] {ch['mid']}")
        print(f"[结尾] {ch['tail']}")
