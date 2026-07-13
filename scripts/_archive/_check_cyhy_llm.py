#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Check 长夜余火 LLM scores to find the actual chapter numbering used"""
import csv, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

path = "data/processed/末世/scores/长夜余火_llm.csv"
with open(path, "r", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    rows = list(reader)

print(f"Total rows: {len(rows)}")
print(f"Columns: {list(rows[0].keys())}")

# Show first and last 5
print("\nFirst 5:")
for r in rows[:5]:
    print(f"  ch{r.get('ch_num','?')}: intensity={r.get('llm_intensity','?')}")

print("\nLast 5:")
for r in rows[-5:]:
    print(f"  ch{r.get('ch_num','?')}: intensity={r.get('llm_intensity','?')}")

# Check max ch_num
ch_nums = [int(r.get('ch_num', 0)) for r in rows if r.get('ch_num','').isdigit()]
print(f"\nMax ch_num: {max(ch_nums)}")
print(f"Min ch_num: {min(ch_nums)}")
print(f"Total unique chs: {len(set(ch_nums))}")
