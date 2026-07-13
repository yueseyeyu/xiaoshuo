#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Save stage1 AI blind scores to JSON file.
Usage: python save_stage1_scores.py <scores_json>
Scores are appended to scripts/stage1_ai_scores.json
"""
import json, sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

scores_file = Path("scripts/stage1_ai_scores.json")

# Read new scores from stdin or argument
if len(sys.argv) > 1:
    new_scores = json.loads(sys.argv[1])
else:
    new_scores = json.load(sys.stdin)

# Load existing
if scores_file.exists():
    existing = json.load(open(scores_file, encoding="utf-8"))
else:
    existing = []

# Merge (dedupe by book+ch_num)
existing_keys = {(s["book"], s["ch_num"]) for s in existing}
for s in new_scores:
    key = (s["book"], s["ch_num"])
    if key in existing_keys:
        # Update existing
        for i, e in enumerate(existing):
            if (e["book"], e["ch_num"]) == key:
                existing[i] = s
                break
    else:
        existing.append(s)

# Sort by book then ch_num
book_order = {"废土崛起": 0, "末日蟑螂": 1, "末世大回炉": 2}
existing.sort(key=lambda s: (book_order.get(s["book"], 99), s["ch_num"]))

with open(scores_file, "w", encoding="utf-8") as f:
    json.dump(existing, f, ensure_ascii=False, indent=2)

print(f"Saved {len(new_scores)} scores. Total: {len(existing)}")
