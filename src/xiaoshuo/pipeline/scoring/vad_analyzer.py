#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
scoring/vad_analyzer.py — VAD情感弧分析
========================================
从 genre_synthesizer.py 拆分。

方法: VAD 3D emotion curve (效价/唤醒度/优势度) + 转折点检测
参考: arxiv 2511.11857

公开函数:
  - compute_vad(rows) -> (curve, turning_points, summary)
"""
import statistics


def compute_vad(rows):
    """VAD 3D emotion curve + turning points."""
    curve = [{"ch": r["ch_num"], "V": round(r["pos_density"] - r["neg_density"], 2),
              "A": r["pleasure_intensity"], "D": round(10 - r["conflict_density"], 2)} for r in rows]
    if len(curve) < 10:
        return curve, [], {"V_mean": 0, "A_mean": 0, "D_mean": 0, "turning_count": 0}

    turning = []
    for i in range(2, len(curve) - 2):
        prev = statistics.mean([curve[j]["V"] for j in range(i-2,i)])
        nxt = statistics.mean([curve[j]["V"] for j in range(i,i+2)])
        std_all = statistics.stdev([c["V"] for c in curve[max(0,i-5):min(len(curve),i+5)]]) if len(curve)>5 else 1
        if std_all > 0 and abs(nxt - prev) > std_all * 1.2:
            turning.append({"ch": curve[i]["ch"], "dir": "up" if nxt>prev else "down", "delta": round(abs(nxt-prev),2)})

    summary = {
        "V_mean": round(statistics.mean([c["V"] for c in curve]), 2),
        "A_mean": round(statistics.mean([c["A"] for c in curve]), 1),
        "D_mean": round(statistics.mean([c["D"] for c in curve]), 2),
        "turning_count": len(turning),
    }
    return curve, turning, summary