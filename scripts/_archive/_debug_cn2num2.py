#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Check if ch536 and ch934 exist in 长夜余火"""
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

# List chapters around 530-540 and 930-940
for i in range(1, len(parts)-1, 2):
    header = parts[i].strip()
    m = re.search(r"第([一二三四五六七八九十百千零\d]+)章", header)
    if m:
        parsed = cn2num(m.group(1))
        if 533 <= parsed <= 540:
            print(f"ch{parsed}: {header[:60]}")
        if 930 <= parsed <= 945:
            print(f"ch{parsed}: {header[:60]}")
