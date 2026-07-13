#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Check chapter header format in 长夜余火"""
import re
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

text = open("data/raw/novels/末世/《长夜余火》（校对版全本）作者：爱潜水的乌贼.txt", encoding="utf-8").read()

# Find first 20 chapter headers
matches = re.findall(r'第[一二三四五六七八九十百千零\d]+章[^\n]{0,30}', text[:100000])
for m in matches[:20]:
    print(repr(m))

print("---")
# Check line-based pattern
lines = text[:5000].split('\n')
for i, line in enumerate(lines[:30]):
    print(f"L{i}: {repr(line[:80])}")
