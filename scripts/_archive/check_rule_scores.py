#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Check rule scores for expansion chapters."""
import csv, sys, json
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

scores_dir = Path("data/processed/末世/scores")
# Find CSVs for our target books
targets = ["末世魔神游戏", "黑暗血时代", "废土崛起", "末日蟑螂", "末世大回炉"]

for f in sorted(scores_dir.glob("*_llm.csv")):
    fname = f.name
    matched = False
    for t in targets:
        if t in fname:
            matched = True
            break
    if not matched:
        continue
    rows = list(csv.DictReader(open(f, encoding='utf-8')))
    if not rows:
        continue
    cols = list(rows[0].keys())
    print(f"\n=== {fname} ({len(rows)} rows) ===")
    print(f"Columns: {cols}")
    # Show first row
    print(f"Sample: {rows[0]}")
    break  # Just show one for format check
