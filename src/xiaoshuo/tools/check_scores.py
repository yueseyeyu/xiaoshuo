"""Check LLM score quality — permanent utility script."""
import csv, glob
from collections import Counter
from statistics import mean, stdev
from pathlib import Path

llm_dir = Path("data/processed/末世/scores")
files = sorted(llm_dir.glob("*_llm.csv"))
if not files:
    print("No CSV files found")
    exit(1)

all_ints = []
hook_dist = Counter()
book_stats = []

for f in files:
    book = f.stem.replace("_llm", "")[:25]
    with open(f, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    ints = [float(r["llm_intensity"]) for r in rows]
    hooks = [r["llm_hook"] for r in rows]
    all_ints.extend(ints)
    hook_dist.update(hooks)
    book_stats.append((book, len(ints), min(ints), max(ints), round(mean(ints), 1)))

print("=== Hook Distribution ===")
for k, v in hook_dist.most_common():
    print(f"  {k}: {v}")

print(f"\n=== Intensity (all {len(all_ints)} chapters) ===")
bins = Counter(int(i) for i in all_ints)
for i in sorted(bins):
    bar = "#" * bins[i]
    print(f"  {i}: {bins[i]:3d} {bar}")
print(f"  range={min(all_ints):.0f}-{max(all_ints):.0f}  mean={mean(all_ints):.1f}  std={stdev(all_ints):.1f}")

print(f"\n=== Top 10 (by intensity) ===")
for b, n, lo, hi, m in sorted(book_stats, key=lambda x: x[4], reverse=True)[:10]:
    print(f"  {m:.1f}  [{lo}-{hi}]  {b}")

print(f"\n=== Bottom 5 ===")
for b, n, lo, hi, m in sorted(book_stats, key=lambda x: x[4])[:5]:
    print(f"  {m:.1f}  [{lo}-{hi}]  {b}")
