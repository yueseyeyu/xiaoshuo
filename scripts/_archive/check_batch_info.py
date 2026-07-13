#!/usr/bin/env python3
"""Check batch files new_23 to new_32: chapter list, word counts, strata."""
import json, os

base = "data/processed/末世/scores/ai_annotate_batches"
total_chapters = 0
for i in range(23, 33):
    fname = f"new_{i:02d}.json"
    fpath = os.path.join(base, fname)
    with open(fpath, "r", encoding="utf-8") as f:
        chapters = json.load(f)
    total_chapters += len(chapters)
    ch_list = [(c["ch_num"], c["stratum"], c["wc"]) for c in chapters]
    print(f"\n=== {fname} ({len(chapters)} chapters) ===")
    for ch_num, stratum, wc in ch_list:
        print(f"  ch={ch_num}, stratum={stratum}, wc={wc}")

print(f"\nTotal chapters to score: {total_chapters}")
