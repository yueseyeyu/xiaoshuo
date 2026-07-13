#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""提取末世大回炉第1735-1742章原文"""
import re

RAW_PATH = r"d:\Code\xiaoshuo\data\raw\novels\末世\《末世大回炉》（校对版全本）作者：二十二刀流.txt"

with open(RAW_PATH, "r", encoding="utf-8") as f:
    text = f.read()

cn_nums = r"[一二三四五六七八九十百千零\d]+"
pattern = r"(第" + cn_nums + r"章\s*[^\n]*)"
parts = re.split(pattern, text)

chapters = {}
for i in range(1, len(parts) - 1, 2):
    header = parts[i].strip()
    body = parts[i + 1].strip() if i + 1 < len(parts) else ""
    m = re.search(r"第(\d+)章", header)
    if m:
        ch_num = int(m.group(1))
        if ch_num > 0 and body:
            chapters[ch_num] = {"header": header, "body": body}

# 写到UTF-8文件
out = []
for ch_num in range(1735, 1743):
    if ch_num in chapters:
        ch = chapters[ch_num]
        out.append(f"\n{'='*60}")
        out.append(f"第{ch_num}章 | {ch['header']}")
        out.append(f"字数: {len(ch['body'])}")
        out.append(f"{'='*60}")
        body = ch['body']
        if len(body) > 2500:
            out.append(body[:1200])
            out.append(f"\n... [省略 {len(body)-2400} 字] ...\n")
            out.append(body[-1200:])
        else:
            out.append(body)
    else:
        out.append(f"\n第{ch_num}章: 未找到")

with open(r"d:\Code\xiaoshuo\scripts\ch1738_context.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("Done: ch1738_context.txt")
