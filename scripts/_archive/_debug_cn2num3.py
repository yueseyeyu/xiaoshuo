#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""List all chapter numbers near 536 and 934"""
import re, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

digit_map = {'零':0,'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}

def cn2num(s):
    if s.isdigit():
        return int(s)
    result = 0
    current = 0
    for ch in s:
        if ch in digit_map:
            current = digit_map[ch]
        elif ch == '十':
            result += (current if current else 1) * 10
            current = 0
        elif ch == '百':
            result += current * 100
            current = 0
        elif ch == '千':
            result += current * 1000
            current = 0
    result += current
    return result

text = open("data/raw/novels/末世/《长夜余火》（校对版全本）作者：爱潜水的乌贼.txt", encoding="utf-8").read()

cn_nums = r"[一二三四五六七八九十百千零\d]+"
pattern = r"(第" + cn_nums + r"章\s*[^\n]*)"
parts = re.split(pattern, text)

# List ALL chapters
all_chs = []
for i in range(1, len(parts)-1, 2):
    header = parts[i].strip()
    m = re.search(r"第([一二三四五六七八九十百千零\d]+)章", header)
    if m:
        parsed = cn2num(m.group(1))
        all_chs.append((parsed, header[:50]))

print(f"Total chapters parsed: {len(all_chs)}")
print(f"First 5: {all_chs[:5]}")
print(f"Last 5: {all_chs[-5:]}")

# Find max
max_ch = max(all_chs, key=lambda x: x[0])
print(f"Max chapter: {max_ch}")

# Check for 536
found_536 = [c for c in all_chs if c[0] == 536]
print(f"Chapter 536: {found_536}")

# Check around 536
around_536 = [c for c in all_chs if 533 <= c[0] <= 540]
print(f"Around 536: {around_536}")

# Check if there are duplicate or missing numbers
nums = [c[0] for c in all_chs]
from collections import Counter
dups = {k:v for k,v in Counter(nums).items() if v > 1}
if dups:
    print(f"Duplicate chapter numbers: {dups}")

# Check gaps
sorted_nums = sorted(set(nums))
for i in range(1, len(sorted_nums)):
    if sorted_nums[i] - sorted_nums[i-1] > 1:
        gap = sorted_nums[i] - sorted_nums[i-1]
        if gap > 3 and sorted_nums[i-1] > 100:
            print(f"Gap: {sorted_nums[i-1]} -> {sorted_nums[i]} (gap={gap})")
