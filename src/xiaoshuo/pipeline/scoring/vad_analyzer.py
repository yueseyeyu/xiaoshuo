#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
scoring/vad_analyzer.py — VAD情感弧分析
========================================
从 genre_synthesizer.py 拆分。

方法: VAD 3D emotion curve (效价/唤醒度/优势度) + 转折点检测
参考: arxiv 2511.11857

v3 增强 (基于160万字AI文vs人工文对比分析):
  - volatility: V值标准差，AI文 < 0.3（过于平滑），人工文 > 0.5
  - monotony_segments: 连续同方向情绪变化段，AI文常有长单调段
  - jump_count: 相邻段落V值变化 > 0.5 的跳跃次数

公开函数:
  - compute_vad(rows) -> (curve, turning_points, summary)
"""
import statistics


def compute_vad(rows):
    """VAD 3D emotion curve + turning points.

    Args:
        rows: list of dict, 每行需包含:
            - ch_num: 章节号
            - pos_density: 正面密度
            - neg_density: 负面密度
            - pleasure_intensity: 愉悦强度
            - conflict_density: 冲突密度

    Returns:
        (curve, turning_points, summary)
        curve: list of {"ch", "V", "A", "D"}
        turning_points: list of {"ch", "dir", "delta"}
        summary: dict, v3 新增 volatility/monotony_segments/jump_count
    """
    curve = [{"ch": r["ch_num"], "V": round(r["pos_density"] - r["neg_density"], 2),
              "A": r["pleasure_intensity"], "D": round(10 - r["conflict_density"], 2)} for r in rows]
    if len(curve) < 10:
        return curve, [], {
            "V_mean": 0, "A_mean": 0, "D_mean": 0, "turning_count": 0,
            "volatility": 0, "monotony_segments": [], "jump_count": 0,
            "emotion_flat": False,
        }

    turning = []
    for i in range(2, len(curve) - 2):
        prev = statistics.mean([curve[j]["V"] for j in range(i-2,i)])
        nxt = statistics.mean([curve[j]["V"] for j in range(i,i+2)])
        std_all = statistics.stdev([c["V"] for c in curve[max(0,i-5):min(len(curve),i+5)]]) if len(curve)>5 else 1
        if std_all > 0 and abs(nxt - prev) > std_all * 1.2:
            turning.append({"ch": curve[i]["ch"], "dir": "up" if nxt>prev else "down", "delta": round(abs(nxt-prev),2)})

    # ── v3: 情感波动率量化 ──
    v_values = [c["V"] for c in curve]
    volatility = round(statistics.stdev(v_values), 4) if len(v_values) > 1 else 0

    # ── v3: 情感跳跃次数（相邻章 V 值变化 > 0.5）──
    jump_count = sum(
        1 for i in range(len(v_values) - 1)
        if abs(v_values[i + 1] - v_values[i]) > 0.5
    )

    # ── v3: 单调段检测（连续3+章同方向变化）──
    monotony_segments = _detect_monotony_segments(v_values, curve)

    summary = {
        "V_mean": round(statistics.mean(v_values), 2),
        "A_mean": round(statistics.mean([c["A"] for c in curve]), 1),
        "D_mean": round(statistics.mean([c["D"] for c in curve]), 2),
        "turning_count": len(turning),
        # v3 新增: AI文情感平滑度量化
        "volatility": volatility,
        "monotony_segments": monotony_segments,
        "jump_count": jump_count,
        # AI文特征判定: volatility < 0.3 且 jump_count < 总章数10%
        "emotion_flat": volatility < 0.3 and jump_count < len(curve) * 0.1,
    }
    return curve, turning, summary


def _detect_monotony_segments(v_values, curve):
    """v3: 检测连续同方向情绪变化的段落。

    AI文特征: 常有5+章连续同方向变化（情绪如一潭死水）。
    人工文特征: 每3-4章至少有一次情绪方向反转。

    Returns:
        list of {"start_ch", "end_ch", "length", "direction"}
    """
    if len(v_values) < 3:
        return []

    segments = []
    seg_start = 0
    seg_dir = 0  # 1=上升, -1=下降, 0=初始

    for i in range(1, len(v_values)):
        diff = v_values[i] - v_values[i - 1]
        cur_dir = 1 if diff > 0 else (-1 if diff < 0 else 0)

        if cur_dir == 0:
            continue

        if seg_dir == 0:
            seg_dir = cur_dir
            seg_start = i - 1
        elif cur_dir != seg_dir:
            # 方向反转，记录前一段
            length = i - seg_start
            if length >= 3:
                segments.append({
                    "start_ch": curve[seg_start]["ch"],
                    "end_ch": curve[i - 1]["ch"],
                    "length": length,
                    "direction": "上升" if seg_dir > 0 else "下降",
                })
            seg_dir = cur_dir
            seg_start = i - 1

    # 收尾: 最后一段
    if seg_dir != 0:
        length = len(v_values) - seg_start
        if length >= 3:
            segments.append({
                "start_ch": curve[seg_start]["ch"],
                "end_ch": curve[-1]["ch"],
                "length": length,
                "direction": "上升" if seg_dir > 0 else "下降",
            })

    return segments
