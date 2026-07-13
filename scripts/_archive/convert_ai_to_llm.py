#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""将_ai_full.csv转换为_llm.csv格式，供commercial_engine的_load_all_llm_scores()使用

列名映射:
  ai_intensity  → llm_intensity  (int 1-10)
  ai_retention  → llm_retention  (int 1-10)
  ai_hook       → llm_hook       (str: weak/medium/strong)
  ai_pace       → llm_pace       (str: slow/medium/fast)
  ai_conflict   → llm_conflict   (str: low/medium/high)
  ai_emotion    → llm_emotion    (str: 9种情绪分类)
  ai_analysis   → llm_analysis   (str: 20-100字中文分析)

v8.9修复: 补回之前合并时丢失的ai_analysis和ai_emotion字段
"""
import csv, sys, os
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent.parent
SCORES_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "scores"

LLM_FIELDS = ["ch_num", "llm_intensity", "llm_retention", "llm_hook", "llm_pace", "llm_conflict", "llm_emotion", "llm_analysis"]

ai_files = sorted(SCORES_DIR.glob("*_ai_full.csv"))
print(f"找到 {len(ai_files)} 个 _ai_full.csv 文件")
print("=" * 80)

success = 0
total_rows = 0
for ai_file in ai_files:
    stem = ai_file.name.replace("_ai_full.csv", "")
    llm_file = SCORES_DIR / f"{stem}_llm.csv"

    with open(ai_file, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    with open(llm_file, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=LLM_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "ch_num": row["ch_num"],
                "llm_intensity": row["ai_intensity"],
                "llm_retention": row["ai_retention"],
                "llm_hook": row["ai_hook"],
                "llm_pace": row["ai_pace"],
                "llm_conflict": row["ai_conflict"],
                "llm_emotion": row.get("ai_emotion", ""),
                "llm_analysis": row.get("ai_analysis", ""),
            })

    total_rows += len(rows)
    success += 1
    print(f"  ✅ {stem}: {len(rows)}章 → {llm_file.name}")

print(f"\n{'=' * 80}")
print(f"完成: {success}本书, {total_rows}章, 全部转换为_llm.csv格式")
