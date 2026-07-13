#!/usr/bin/env python
# -*- coding: utf-8 -*-
import csv, json, sys
from pathlib import Path

PROJECT = Path("d:/Code/xiaoshuo")
TIER3_DIR = PROJECT / "data" / "golden" / "末世" / "tier3"
GOLDEN_CSV = PROJECT / "data" / "golden" / "末世" / "human_golden.csv"
GLM_JSON = TIER3_DIR / "tier3_glm_scores.json"

# Test 1: Load golden CSV
try:
    with open(GOLDEN_CSV, 'r', encoding='utf-8-sig') as f:
        golden_rows = list(csv.DictReader(f))
    with open(PROJECT / "scripts" / "_test_out.txt", 'w', encoding='utf-8') as out:
        out.write(f"Golden CSV: {len(golden_rows)} rows\n")
        out.write(f"Keys: {list(golden_rows[0].keys())}\n\n")
        
        # Test 2: Load GLM JSON
        with open(GLM_JSON, 'r', encoding='utf-8') as f:
            glm_data = json.load(f)
        out.write(f"GLM JSON: {glm_data['metadata']['total_chapters']} chapters\n")
        out.write(f"Books: {list(glm_data['scores'].keys())}\n\n")
        
        # Test 3: Load tier3 plan
        for book in glm_data['scores'].keys():
            plan_csv = TIER3_DIR / f"{book}_tier3_plan.csv"
            out.write(f"Plan for {book}: exists={plan_csv.exists()}\n")
            if plan_csv.exists():
                with open(plan_csv, 'r', encoding='utf-8-sig') as f:
                    plan_rows = list(csv.DictReader(f))
                out.write(f"  Rows: {len(plan_rows)}\n")
                if plan_rows:
                    out.write(f"  Keys: {list(plan_rows[0].keys())}\n")
        
        out.write("\nTest passed!\n")
        
except Exception as e:
    import traceback
    with open(PROJECT / "scripts" / "_test_out.txt", 'w', encoding='utf-8') as out:
        out.write(f"ERROR: {e}\n\n{traceback.format_exc()}\n")
