#!/usr/bin/env python3
"""Check which batches need scoring."""
import json, os

base = "data/processed/末世/scores/ai_annotate_batches"

# Check batch files
print("=== Batch files (new_23 to new_32) ===")
for i in range(23, 33):
    fname = f"new_{i:02d}.json"
    fpath = os.path.join(base, fname)
    if not os.path.exists(fpath):
        print(f"  {fname}: NOT FOUND")
        continue
    with open(fpath, "r", encoding="utf-8") as f:
        chapters = json.load(f)
    chs = [(c["ch_num"], c["stratum"], c.get("wc", len(c.get("body", "")))) for c in chapters]
    print(f"  {fname}: {len(chapters)} chapters: {chs}")

# Check existing score files
print("\n=== Existing score files ===")
for f in sorted(os.listdir(base)):
    if f.startswith("scores_new_") and f.endswith(".json"):
        fpath = os.path.join(base, f)
        with open(fpath, "r", encoding="utf-8") as fh:
            scores = json.load(fh)
        chs = [s["ch_num"] for s in scores]
        print(f"  {f}: {len(scores)} scores, chapters: {chs}")

# Check which scores are missing
print("\n=== Missing scores (new_23 to new_32) ===")
for i in range(23, 33):
    sf = f"scores_new_{i:02d}.json"
    sfpath = os.path.join(base, sf)
    bf = f"new_{i:02d}.json"
    bfpath = os.path.join(base, bf)
    if not os.path.exists(sfpath):
        if os.path.exists(bfpath):
            with open(bfpath, "r", encoding="utf-8") as f:
                chapters = json.load(f)
            print(f"  {sf}: MISSING (batch has {len(chapters)} chapters)")
        else:
            print(f"  {sf}: MISSING (batch file also missing)")
    else:
        print(f"  {sf}: EXISTS")
