#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""提取48章缺失T2的章节文本，输出为JSON供盲评。"""
import csv, json, sys, io, re
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TIER3_DIR = PROJECT_ROOT / "data" / "golden" / "末世" / "tier3"
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "novels" / "末世"
OUTPUT = TIER3_DIR / "_t2_missing_chapters.json"

NEED_T2 = {
    "地球游戏场": [1, 198, 384, 443, 561, 581, 749, 769],
    "末世大回炉": [975, 1556, 1606, 1625, 1704],
    "异兽迷城": [1, 316, 643, 663, 762, 900, 959, 1276],
    "黑暗血时代": [1, 216, 256, 466, 665, 922, 1388, 1537, 1841],
    "第一序列": [1, 310, 627, 747, 896, 946, 955, 1251],
    "末日乐园": [1, 610, 979, 1218, 1817, 1866, 2016, 2419],
    "长夜余火": [536, 934],
}

def cn2num(s):
    digit_map = {'零':0,'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
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

def read_chapter_text(book_name, ch_num):
    ch_path = TIER3_DIR / f"{book_name}_chapters" / f"ch{ch_num:04d}.txt"
    if ch_path.exists():
        for enc in ["utf-8", "gbk", "gb18030"]:
            try:
                return ch_path.read_text(encoding=enc)
            except (UnicodeDecodeError, UnicodeError):
                continue
    raw_files = list(RAW_DIR.glob(f"*{book_name}*.txt"))
    if not raw_files:
        clean = book_name.replace("《", "").replace("》", "")
        raw_files = list(RAW_DIR.glob(f"*{clean}*.txt"))
    if not raw_files:
        return ""
    raw_path = raw_files[0]
    for enc in ["utf-8", "gbk", "gb18030", "utf-16"]:
        try:
            raw_text = raw_path.read_text(encoding=enc)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    else:
        return ""
    cn_nums = r"[一二三四五六七八九十百千零\d]+"
    pattern = r"(第" + cn_nums + r"章\s*[^\n]*)"
    parts = re.split(pattern, raw_text)
    if len(parts) < 5:
        return ""
    for i in range(1, len(parts) - 1, 2):
        header = parts[i].strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        m = re.search(r"第(\d+)章", header)
        if m and int(m.group(1)) == ch_num:
            return body
        m = re.search(r"第([一二三四五六七八九十百千零\d]+)章", header)
        if m:
            parsed = cn2num(m.group(1))
            if parsed == ch_num:
                return body
    cumulative = 0
    for i in range(1, len(parts) - 1, 2):
        header = parts[i].strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        cumulative += 1
        if cumulative == ch_num:
            return body
    return ""

chapters = []
for book, chs in NEED_T2.items():
    for ch_num in chs:
        body = read_chapter_text(book, ch_num)
        if not body:
            print(f"[WARN] {book} ch{ch_num}: 原文未找到")
            continue
        chapters.append({
            "book": book,
            "ch_num": ch_num,
            "wc": len(body.strip()),
            "body": body.strip()[:5000],  # 限制5000字
        })
        print(f"  {book} ch{ch_num}: {len(body.strip())}字")

with open(OUTPUT, "w", encoding="utf-8") as f:
    json.dump(chapters, f, ensure_ascii=False, indent=2)

print(f"\n共提取 {len(chapters)} 章")
print(f"输出: {OUTPUT}")
