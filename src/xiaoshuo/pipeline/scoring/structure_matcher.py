#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
scoring/structure_matcher.py — 结构模板匹配 (v3)
==================================================
从 genre_synthesizer.py 拆分。

方法: 马良写作叙事结构分类 (起/承/转/爽/紧张/缓气/线索/推翻)

v3 改进:
  1. 爽阈值 5→3: 10本书数据显示 avg_intensity 1.0-2.4，原阈值5导致几乎无"爽"章
  2. 慢热感知: 生存/压力密集章(fate_change≥40 + obstacle≥3)归类为"紧张"而非"承"
  3. 爽判定复合条件: intensity≥3 OR (slap≥2 OR comeback≥1) AND hook>0
  4. 承判定收紧: 纯承需要 intensity<2 AND conflict<0.8，防止高活力章被吞

公开函数:
  - classify_structure(rows) -> (distribution: dict, template_match_count: int)
"""

from collections import Counter

# ══════════════════════════════════════════════════════════════
# 可配置阈值 (v3: 基于10本末世精品数据校准)
# ══════════════════════════════════════════════════════════════
THRESHOLDS = {
    "起": {"conflict_max": 0.3, "intensity_max": 3},
    "承": {"conflict_min": 0.3, "conflict_max": 0.8, "intensity_max": 2},
    "转": {"variability_min": 0.3, "intensity_delta": 2.0},
    "爽": {"intensity_min": 3, "slap_min": 2, "comeback_min": 1},
    "紧张": {"conflict_min": 1.0, "fate_min": 40, "obstacle_min": 3},
    "缓气": {"conflict_max": 0.2, "dialogue_min": 0.25},
    "线索": {"hook_types": ("悬念式",)},
    "推翻": {"hook_types": ("反转式", "信息投放"), "conflict_max": 0.5},
}

# 叙事模板 (可匹配的7章窗口模式)
NARRATIVE_TEMPLATES = [
    ["起", "承", "承", "转", "转", "爽", "爽"],  # 标准起承转合
    ["起", "承", "转", "爽", "承", "转", "爽"],  # 交替推进
    ["起", "承", "承", "爽", "转", "承", "爽"],  # 早期爆发
    ["起", "紧张", "承", "转", "爽", "缓气", "爽"],  # 紧张-释放
    ["起", "承", "转", "紧张", "爽", "缓气", "爽"],  # 危机-反转
    ["起", "承", "紧张", "转", "爽", "承", "爽"],  # 压力-反转
    ["起", "承", "承", "承", "转", "爽", "缓气"],  # 慢热-后期爆发
]


def _classify_single(r, prev_label, i, total, thresholds):
    """Classify a single chapter with context awareness (v3)."""
    cd = r["conflict_density"]
    pi = r["pleasure_intensity"]
    cv = r.get("ch_variability", 0)
    ht = r.get("hook_type", "none")
    slap = r.get("slap_count", 0)
    comeback = r.get("comeback_count", 0)
    hook_d = r.get("hook_density", 0)
    fate = r.get("fate_change_score", 0)
    obstacle = r.get("obstacle_total", 0)
    neg_d = r.get("neg_density", 0)
    pos_d = r.get("pos_density", 0)

    t = thresholds

    # Position-aware: first 3 chapters favor "起"
    if i < 3 and cd < 0.5 and pi < 4:
        return "起"

    # Position-aware: last 3 chapters favor "爽" or "转"
    if i >= total - 3 and pi >= 3:
        return "爽"

    # ── "转": 高变异性 或 强度突变 ──
    prev_pi = r.get("_prev_pi", 0)
    if cv > t["转"]["variability_min"] or abs(pi - prev_pi) > t["转"]["intensity_delta"]:
        return "转"

    # ── "爽": 复合条件 (v3: 阈值3 + 多维判定) ──
    # 条件1: intensity≥3 (原5，基于实际数据校准)
    # 条件2: slap≥2 OR comeback≥1, 且 hook>0 (打脸/反击+钩子=爽章)
    if pi >= t["爽"]["intensity_min"]:
        return "爽"
    if (slap >= t["爽"]["slap_min"] or comeback >= t["爽"]["comeback_min"]) and hook_d > 0.5:
        return "爽"

    # ── "起": 低冲突+低强度 ──
    if cd < t["起"]["conflict_max"] and pi < t["起"]["intensity_max"]:
        return "起"

    # ── "紧张" (v3: 慢热感知 — fate_change≥40 + obstacle≥3 = 生存压力章) ──
    # 原v2: 仅 cd>1.5 AND neg>pos → 太严格，漏掉大量生存压力章
    # v3: 三选一
    #   a) 高冲突 + 负面情绪优势 (原逻辑，阈值从1.5降到1.0)
    #   b) fate_change≥40 + obstacle≥3 (命运推动+阻碍密集 = 生存压力)
    #   c) neg_density > 2*pos_density AND conflict > 0.5 (压抑章)
    if cd > t["紧张"]["conflict_min"] and neg_d > pos_d:
        return "紧张"
    if fate >= t["紧张"]["fate_min"] and obstacle >= t["紧张"]["obstacle_min"]:
        return "紧张"
    if neg_d > pos_d * 2 and cd > 0.5:
        return "紧张"

    # ── "承": 中等冲突+低强度 (v3: 加 intensity<2 约束) ──
    if t["承"]["conflict_min"] <= cd < t["承"]["conflict_max"] and pi < t["承"]["intensity_max"]:
        return "承"

    # ── "缓气": 低冲突+高对话 ──
    if cd < t["缓气"]["conflict_max"] and r.get("dialogue_ratio", 0) > t["缓气"]["dialogue_min"]:
        return "缓气"

    # ── Hook type based ──
    if ht in t["线索"]["hook_types"] and cd < 0.5:
        return "线索"
    if ht in t["推翻"]["hook_types"] and cd < t["推翻"]["conflict_max"]:
        return "推翻"

    # ── Default: context-aware fallback ──
    # 如果冲突高但没到"紧张"阈值，仍归"承"
    # 如果前一章是"爽"或"紧张"，当前章可能是过渡"承"
    return "承"


def classify_structure(rows, thresholds=None):
    """Classify each chapter into narrative phase (v3: context-aware + slow-burn).

    Args:
        rows: list of chapter metric dicts
        thresholds: optional dict overriding THRESHOLDS

    Returns:
        (distribution: dict, template_match_count: int)
    """
    if thresholds is None:
        thresholds = THRESHOLDS

    total = len(rows)
    labels = []
    prev_pi = 0

    for i, r in enumerate(rows):
        # Inject previous pleasure_intensity for delta calculation
        r["_prev_pi"] = prev_pi
        prev_label = labels[-1] if labels else "起"
        label = _classify_single(r, prev_label, i, total, thresholds)
        labels.append(label)
        prev_pi = r.get("pleasure_intensity", 0)

    dist = dict(Counter(labels).most_common())

    # Multi-template matching
    match_count = 0
    for i in range(len(labels) - 6):
        window = labels[i:i + 7]
        for template in NARRATIVE_TEMPLATES:
            if window == template:
                match_count += 1
                break

    return dist, match_count


# Backward compatibility alias
classify_structure_v2 = classify_structure
