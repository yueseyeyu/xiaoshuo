#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Check 长夜余火 multi-volume structure"""
import re, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

text = open("data/raw/novels/末世/《长夜余火》（校对版全本）作者：爱潜水的乌贼.txt", encoding="utf-8").read()

# Find volume markers
vol_pattern = r'(第[一二三四五六七八九十\d]+部[^\n]*)'
vol_matches = list(re.finditer(vol_pattern, text))
print(f"Volume markers found: {len(vol_matches)}")
for m in vol_matches:
    print(f"  pos={m.start()}: {m.group()[:50]}")

# Count chapters per volume
digit_map = {'零':0,'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
def cn2num(s):
    if s.isdigit(): return int(s)
    result = 0; current = 0
    for ch in s:
        if ch in digit_map: current = digit_map[ch]
        elif ch == '十': result += (current if current else 1) * 10; current = 0
        elif ch == '百': result += current * 100; current = 0
        elif ch == '千': result += current * 1000; current = 0
    result += current
    return result

cn_nums = r"[一二三四五六七八九十百千零\d]+"
pattern = r"(第" + cn_nums + r"章\s*[^\n]*)"
parts = re.split(pattern, text)

# Group by volume
vol_positions = [(m.start(), m.group()[:50]) for m in vol_matches]

current_vol = 0
vol_offset = 0
vol_chapters = {}

for i in range(1, len(parts)-1, 2):
    header = parts[i].strip()
    header_pos = text.find(header)
    
    # Check if we entered a new volume
    while current_vol < len(vol_positions) and header_pos > vol_positions[current_vol][0]:
        if current_vol > 0:
            # Count chapters in previous volume
            pass
        current_vol += 1
        if current_vol < len(vol_positions):
            vol_offset = sum(vol_chapters.get(v+1, 0) for v in range(current_vol-1))
    
    m = re.search(r"第([一二三四五六七八九十百千零\d]+)章", header)
    if m:
        parsed = cn2num(m.group(1))
        vol_chapters[current_vol] = vol_chapters.get(current_vol, 0) + 1

print(f"\nChapters per volume:")
for v, count in sorted(vol_chapters.items()):
    print(f"  Vol {v}: {count} chapters, cumulative offset = {sum(vol_chapters.get(k,0) for k in range(1,v))}")

# So ch536 would be in which volume?
cum = 0
for v in sorted(vol_chapters.keys()):
    count = vol_chapters[v]
    print(f"  Vol {v}: ch {cum+1} ~ {cum+count}")
    cum += count
print(f"\nTotal cumulative chapters: {cum}")
