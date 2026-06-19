"""Deduplicate novel_index.json. Run from any directory."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = ROOT / "data" / "raw" / "novel_index.json"

idx = json.loads(INDEX_PATH.read_text(encoding='utf-8'))
novels = idx["genres"]["末世"]["novels"]
seen = set()
unique = []
for n in novels:
    key = n["file"]
    if key not in seen:
        seen.add(key)
        unique.append(n)
dup = len(novels) - len(unique)
idx["genres"]["末世"]["novels"] = unique
idx["genres"]["末世"]["count"] = len(unique)
idx["total"] = sum(v["count"] for v in idx["genres"].values())
INDEX_PATH.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding='utf-8')
print(f"Removed {dup} duplicates. Now: {len(unique)} books")
