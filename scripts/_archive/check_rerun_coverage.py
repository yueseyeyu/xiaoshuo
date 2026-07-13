"""Check if rerun_02 and rerun_03 chapters are already covered by existing scores."""
import json
from pathlib import Path

BATCH_DIR = Path("data/processed/末世/scores/ai_annotate_batches")

# Load all rerun batch files
rerun_batches = {}
for i in range(4):
    f = BATCH_DIR / f"rerun_{i:02d}.json"
    if f.exists():
        data = json.load(open(f, encoding="utf-8"))
        chs = [d["ch_num"] for d in data]
        rerun_batches[f"rerun_{i:02d}"] = chs
        print(f"rerun_{i:02d}.json: {len(chs)} chapters: {chs}")

# Load all rerun score files
print()
rerun_scores = {}
for i in range(4):
    f = BATCH_DIR / f"scores_rerun_{i:02d}.json"
    if f.exists():
        data = json.load(open(f, encoding="utf-8"))
        chs = [d["ch_num"] for d in data]
        rerun_scores[f"scores_rerun_{i:02d}"] = chs
        print(f"scores_rerun_{i:02d}.json: {len(chs)} chapters: {chs}")

# Check which chapters are already scored
all_rerun_chs = set()
for chs in rerun_batches.values():
    all_rerun_chs.update(chs)

all_scored_chs = set()
for chs in rerun_scores.values():
    all_scored_chs.update(chs)

print(f"\nAll rerun chapters: {sorted(all_rerun_chs)}")
print(f"All scored chapters: {sorted(all_scored_chs)}")
print(f"Missing: {sorted(all_rerun_chs - all_scored_chs)}")
print(f"Extra in scores: {sorted(all_scored_chs - all_rerun_chs)}")

# Specifically check rerun_02 and rerun_03
for batch_name in ["rerun_02", "rerun_03"]:
    if batch_name in rerun_batches:
        chs = rerun_batches[batch_name]
        covered = [ch for ch in chs if ch in all_scored_chs]
        not_covered = [ch for ch in chs if ch not in all_scored_chs]
        print(f"\n{batch_name}: chapters={chs}")
        print(f"  Already scored: {covered}")
        print(f"  Need scoring: {not_covered}")
