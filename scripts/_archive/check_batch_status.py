#!/usr/bin/env python3
"""Check the status of AI annotation batches."""
import json
import os
import glob

BATCH_DIR = "data/processed/末世/scores/ai_annotate_batches"

# New chapters
new_batches = sorted(glob.glob(os.path.join(BATCH_DIR, "new_*.json")))
new_scores = sorted(glob.glob(os.path.join(BATCH_DIR, "scores_new_*.json")))

# Rerun chapters
rerun_batches = sorted(glob.glob(os.path.join(BATCH_DIR, "rerun_*.json")))
rerun_scores = sorted(glob.glob(os.path.join(BATCH_DIR, "scores_rerun_*.json")))

total_new_ch = 0
print("=== New Chapter Batches ===")
for b in new_batches:
    data = json.load(open(b, encoding="utf-8"))
    n = len(data)
    total_new_ch += n
    bn = os.path.basename(b)
    sn = bn.replace("new_", "scores_new_")
    done = os.path.exists(os.path.join(BATCH_DIR, sn))
    print(f"  {bn}: {n} chapters  {'[DONE]' if done else '[PENDING]'}")

print(f"\nTotal new chapters: {total_new_ch}")
print(f"New batches: {len(new_batches)}, Scores done: {len(new_scores)}")

total_rerun_ch = 0
print("\n=== Rerun Chapter Batches ===")
for b in rerun_batches:
    data = json.load(open(b, encoding="utf-8"))
    n = len(data)
    total_rerun_ch += n
    bn = os.path.basename(b)
    sn = bn.replace("rerun_", "scores_rerun_")
    done = os.path.exists(os.path.join(BATCH_DIR, sn))
    print(f"  {bn}: {n} chapters  {'[DONE]' if done else '[PENDING]'}")

print(f"\nTotal rerun chapters: {total_rerun_ch}")
print(f"Rerun batches: {len(rerun_batches)}, Rerun scores done: {len(rerun_scores)}")

# Check existing pilot annotations
pilot_csv = "data/processed/末世/scores/废土崛起_ai.csv"
if os.path.exists(pilot_csv):
    import csv
    with open(pilot_csv, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        pilot_count = sum(1 for _ in reader)
    print(f"\nPilot CSV: {pilot_csv} ({pilot_count} rows)")
else:
    print(f"\nPilot CSV not found: {pilot_csv}")

print(f"\n=== Summary ===")
print(f"Total to annotate: {total_new_ch + total_rerun_ch} chapters")
print(f"Already done: {len(new_scores) + len(rerun_scores)} batch score files")
print(f"Remaining: {len(new_batches) - len(new_scores) + len(rerun_batches) - len(rerun_scores)} batches")
