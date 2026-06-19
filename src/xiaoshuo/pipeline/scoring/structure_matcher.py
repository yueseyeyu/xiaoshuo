#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
scoring/structure_matcher.py — 结构模板匹配
============================================
从 genre_synthesizer.py 拆分。

方法: 马良写作叙事结构分类 (起/承/转/爽/紧张/缓气/线索/推翻)

公开函数:
  - classify_structure(rows) -> (distribution: dict, template_match_count: int)
"""
from collections import Counter


def classify_structure(rows):
    """Classify each chapter into narrative phase (起/承/转/爽/紧张/缓气/线索/推翻)."""
    labels = []
    for i, r in enumerate(rows):
        cd, pi, cv, ht = r["conflict_density"], r["pleasure_intensity"], r["ch_variability"], r["hook_type"]
        if cd < 0.3 and pi < 3:
            labels.append("起")
        elif 0.3 <= cd < 1.0:
            labels.append("承")
        elif cv > 0.5 or (i > 0 and abs(pi - rows[i-1]["pleasure_intensity"]) > 2.5):
            labels.append("转")
        elif pi >= 5:
            labels.append("爽")
        elif cd > 1.5 and r["neg_density"] > r["pos_density"]:
            labels.append("紧张")
        elif cd < 0.2 and r["dialogue_ratio"] > 0.25:
            labels.append("缓气")
        elif ht in ("悬念式", "反转式", "信息投放") and cd < 0.5:
            labels.append("线索" if ht == "悬念式" else "推翻")
        else:
            labels.append("承")

    dist = dict(Counter(labels).most_common())
    match_count = sum(1 for i in range(len(labels)-6) if
                      labels[i:i+7] in (["起","承","承","转","转","爽","爽"],))
    return dist, match_count