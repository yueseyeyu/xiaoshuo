#!/usr/bin/env python3
"""Inspect batch file structure to find text field."""
import json

fpath = "data/processed/末世/scores/ai_annotate_batches/new_23.json"
with open(fpath, "r", encoding="utf-8") as f:
    chapters = json.load(f)

for c in chapters:
    print(f"\nch_num={c['ch_num']}, stratum={c['stratum']}, wc={c['wc']}")
    print(f"  keys: {list(c.keys())}")
    for k, v in c.items():
        if k == "text":
            print(f"  text length: {len(v)}")
            print(f"  text preview: {v[:200]}")
        elif k not in ("ch_num", "stratum", "wc"):
            print(f"  {k}: {str(v)[:200]}")
