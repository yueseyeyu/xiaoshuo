#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Debug CSV parsing"""
import csv

CSV_PATH = r"d:\Code\xiaoshuo\data\processed\末世\scores\human_golden.csv"

with open(CSV_PATH, "r", encoding="utf-8") as f:
    content = f.read()

print(f"File length: {len(content)} chars")
print(f"First 200 chars repr: {repr(content[:200])}")
print(f"Line count: {content.count(chr(10))}")

# Try different encodings
for enc in ["utf-8", "utf-8-sig", "gbk", "gb2312"]:
    try:
        with open(CSV_PATH, "r", encoding=enc) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        print(f"\nEncoding {enc}: {len(rows)} rows")
        if rows:
            print(f"  First row keys: {list(rows[0].keys())[:5]}")
            print(f"  First row book: '{rows[0].get('book','')}'")
    except Exception as e:
        print(f"\nEncoding {enc}: ERROR - {e}")
