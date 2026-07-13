#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""分析pilot 40章中截断对评分的影响，决定哪些需要重跑。

截断策略: head 300 + peak 200 + tail 700 = ~1200字 (原文2500字 → 丢失~1300字)
全读策略: 保留完整原文

影响判断:
- 截断后body_len ≤ 1200的章节 = 实际几乎没截断 = 不需要重跑
- 截断后body_len > 1200但分析标注"中段有高潮递进"的 = 需要重跑
- 低分章节(ch3-4)如果中段信息丢失可能导致误判 = 需要重跑
"""
import csv, sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

# 读取AI pilot CSV
ai_csv = Path("data/processed/末世/scores/废土崛起_ai.csv")
with open(ai_csv, 'r', encoding='utf-8-sig') as f:
    rows = list(csv.DictReader(f))

print("=== 截断影响分析 ===\n")
print(f"{'ch':>6} | {'wc':>6} | {'trunc':>6} | {'lost':>6} | {'int':>4} | {'ret':>4} | 分析")
print("-" * 80)

# 所有章节原文都在2000+字，截断到1200字后丢失~1300字
# wc是原始字数，trunc是截断后字数(~1200)
needs_rerun = []
ok_keep = []

for r in rows:
    ch = int(r["ch_num"])
    wc = int(r["wc"]) if r["wc"] else 2500  # golden章节wc=0，用默认值
    trunc = 1200  # 截断后约1200字
    lost = wc - trunc if wc > 1200 else 0
    pct_lost = round(lost / wc * 100) if wc > 0 else 0
    intensity = int(r["ai_intensity"])
    retention = int(r["ai_retention"])
    analysis = r["ai_analysis"]
    
    # 判断是否需要重跑
    # 1. 低分章节(≤4) — 截断可能丢失中段爽点导致低估
    # 2. 分析中提到"中段"或"铺垫"的 — 可能有中段高潮被截
    # 3. golden章节wc=0的 — 这些是从full text提取的，也有截断
    rerun_flag = ""
    if intensity <= 4 and lost > 500:
        needs_rerun.append(ch)
        rerun_flag = " ← RERUN"
    elif lost > 800:
        needs_rerun.append(ch)
        rerun_flag = " ← RERUN"
    else:
        ok_keep.append(ch)
    
    print(f"ch{ch:>4} | {wc:>6} | {trunc:>6} | {lost:>4}({pct_lost:>2}%) | {intensity:>4} | {retention:>4} | {analysis[:40]}{rerun_flag}")

print(f"\n=== 汇总 ===")
print(f"  需要重跑: {len(needs_rerun)}章 — {needs_rerun}")
print(f"  可保留:   {len(ok_keep)}章 — {ok_keep}")
print(f"\n结论: {'全部40章都需要重跑（因为全部被截断了~50%）' if len(needs_rerun) > 30 else f'只需重跑{len(needs_rerun)}章'}")
