#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Debug cn2num for 536 and 934"""
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

# Test
for test in ['一','八','四十五','九十六','一百六十一','二百一十一','五百三十六','九百三十四']:
    print(f"  {test} -> {cn2num(test)}")

# Check the novel file for these chapters
text = open("data/raw/novels/末世/《长夜余火》（校对版全本）作者：爱潜水的乌贼.txt", encoding="utf-8").read()

# Search for chapter 536 and 934
cn_nums = r"[一二三四五六七八九十百千零\d]+"
pattern = r"(第" + cn_nums + r"章\s*[^\n]*)"
parts = re.split(pattern, text)

print(f"\nTotal parts: {len(parts)}")
print(f"Total chapters found: {len(parts)//2}")

# Find chapters around 536 and 934
for i in range(1, len(parts)-1, 2):
    header = parts[i].strip()
    m = re.search(r"第([一二三四五六七八九十百千零\d]+)章", header)
    if m:
        parsed = cn2num(m.group(1))
        if 530 <= parsed <= 540 or 930 <= parsed <= 940:
            print(f"  Found ch{parsed}: {header[:50]}")
