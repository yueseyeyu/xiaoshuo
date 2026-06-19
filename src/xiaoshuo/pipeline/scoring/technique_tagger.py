#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
scoring/technique_tagger.py — 技法标签
=======================================
从 genre_synthesizer.py 拆分。

方法: 基于节奏统计特征的写作技法标签自动检测

公开函数:
  - compute_tags(rows) -> list[str]
"""
import statistics
from collections import Counter


def compute_tags(rows):
    total = len(rows)
    sub = Counter(r["dominant_sub"] for r in rows)
    ht = Counter(r["hook_type"] for r in rows)
    pa = Counter(r["pace"] for r in rows)
    avg_r = statistics.mean([r["readability"] for r in rows])
    tags = []
    if avg_r > 0.1: tags.append("文笔偏文学性")
    elif avg_r < -0.15: tags.append("文笔偏口语化")
    if sub.get("打脸",0)/max(total,1) > 0.6: tags.append("打脸流")
    if sub.get("碾压",0)/max(total,1) > 0.2: tags.append("碾压倾向")
    if pa.get("fast",0)/max(total,1) > 0.5: tags.append("快节奏")
    elif pa.get("slow",0)/max(total,1) > 0.5: tags.append("慢节奏")
    if ht.get("反转式",0)/max(total,1) > 0.1: tags.append("反转大师")
    if ht.get("悬念式",0)/max(total,1) > 0.08: tags.append("悬念控制")
    return tags