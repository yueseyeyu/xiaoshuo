#!/usr/bin/env python3
"""Print chapter texts for batches new_23 to new_27 for AI scoring."""
import json, os

base = "data/processed/末世/scores/ai_annotate_batches"
for i in range(23, 28):
    fname = f"new_{i:02d}.json"
    fpath = os.path.join(base, fname)
    with open(fpath, "r", encoding="utf-8") as f:
        chapters = json.load(f)
    for c in chapters:
        print(f"\n{'='*80}")
        print(f"BATCH: new_{i:02d} | CH: {c['ch_num']} | STRATUM: {c['stratum']} | WC: {c['wc']}")
        print(f"{'='*80}")
        text = c.get("text", "")
        # Print full text
        print(text)
