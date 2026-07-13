#!/usr/bin/env python
"""Identify the 3 trash novels by analyzing rhythm metrics."""
import csv
import statistics
import json
from pathlib import Path

rhythm_dir = Path("data/processed/末世/rhythm")
results = []
for f in sorted(rhythm_dir.glob("*.csv")):
    rows = []
    with open(f, "r", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            rows.append(r)
    if not rows or len(rows) < 5:
        continue
    name = f.stem.replace("rhythm_", "")[:30]
    hook3 = statistics.mean([float(r.get("hook_density", 0)) for r in rows[:3]])
    conflict3 = statistics.mean([float(r.get("conflict_density", 0)) for r in rows[:3]])
    pleasure3 = statistics.mean([float(r.get("pleasure_intensity", 0)) for r in rows[:3]])
    zero_hook_10 = sum(1 for r in rows[:10] if float(r.get("hook_density", 0)) == 0)
    hook_all = statistics.mean([float(r.get("hook_density", 0)) for r in rows])
    pleasure_all = statistics.mean([float(r.get("pleasure_intensity", 0)) for r in rows])
    results.append({
        "name": name,
        "chapters": len(rows),
        "hook3": round(hook3, 2),
        "conflict3": round(conflict3, 2),
        "pleasure3": round(pleasure3, 2),
        "zero_hook_10": zero_hook_10,
        "hook_all": round(hook_all, 2),
        "pleasure_all": round(pleasure_all, 2),
    })

# Sort by hook3 ascending (worst first)
results.sort(key=lambda x: x["hook3"])

# Write to JSON for reliable encoding
out = Path("scripts/trash_analysis.json")
out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Written {len(results)} books to {out}")
