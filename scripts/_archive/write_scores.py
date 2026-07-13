#!/usr/bin/env python3
"""Write scores JSON for a batch."""
import json, sys

scores_file = sys.argv[1]
scores_data = json.loads(sys.argv[2])

with open(scores_file, 'w', encoding='utf-8') as f:
    json.dump(scores_data, f, ensure_ascii=False, indent=2)

print(f"Written {len(scores_data)} chapter scores to {scores_file}")
