# -*- coding: utf-8 -*-
"""
metrics_schema.py — 节奏指标数据模型 (类型安全层)
====================================================
用 dataclass 替代裸 dict 传递章节指标，提供:
  - 编译期字段名检查 (拼写错误立即暴露)
  - CSV 序列化/反序列化
  - 与 rhythm_analyzer 输出 100% 兼容

用法:
  from xiaoshuo.pipeline.metrics_schema import ChapterMetrics

  # 从 rule_analyze 结果创建
  metrics = ChapterMetrics.from_dict(rule_result)

  # 写入 CSV
  csv_row = metrics.to_csv_row()

  # 从 CSV 行重建
  metrics = ChapterMetrics.from_csv_row(csv_dict_row)
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class ChapterMetrics:
    """单章节奏指标 (rhythm_analyzer.rule_analyze 输出)。

    字段顺序与 rhythm CSV 列顺序一致，确保向后兼容。
    """

    # ── 基础信息 ──
    ch_num: int = 0
    ch_hash: str = ""
    wc: int = 0
    para_count: int = 0
    avg_para_len: int = 0

    # ── 密度指标 ──
    dialogue_ratio: float = 0.0
    excl_density: float = 0.0
    pos_density: float = 0.0
    neg_density: float = 0.0
    conflict_density: float = 0.0
    hook_density: float = 0.0

    # ── 爽点子类型 (显式 6 + 隐式 6 + 反转 6 = 18) ──
    slap_count: int = 0
    level_count: int = 0
    crush_count: int = 0
    comeback_count: int = 0
    hidden_count: int = 0
    bond_count: int = 0
    cognitive_count: int = 0
    sacrifice_count: int = 0
    physio_count: int = 0
    strategy_count: int = 0
    resource_count: int = 0
    social_count: int = 0
    backfire_count: int = 0
    trap_master_count: int = 0
    knowledge_gap_count: int = 0
    hidden_value_count: int = 0
    identity_reveal_count: int = 0
    foreshadow_payoff_count: int = 0

    # ── 派生指标 ──
    dominant_sub: str = "none"
    pleasure_type: str = "none"
    pleasure_intensity: float = 0.0
    pleasure_level: str = "none"
    pleasure_timing: str = "instant"
    hook_type: str = "none"
    readability: float = 0.0
    avg_sentence_len: float = 0.0
    vocab_diversity: float = 0.0
    conflict: str = "false"
    conflict_level: str = "none"
    emotion: str = "日常"
    pace: str = "medium"
    ch_variability: float = 0.0

    # ── v11 新增: 反套路 + 情绪价值 ──
    anti_trope: bool = False
    anti_trope_count: int = 0
    emotion_valence: float = 0.0
    emotion_burnout: bool = False
    high_emotion_count: int = 0
    burnout_count: int = 0

    # ── 冗余标记 ──
    slap_noise: bool = False

    # ── 序列化 ──

    def to_csv_row(self) -> dict[str, Any]:
        """转换为 CSV DictWriter 兼容的 dict。

        布尔值转为 "true"/"false" 字符串以兼容现有 CSV 格式。
        """
        row = {}
        for key, val in asdict(self).items():
            if isinstance(val, bool):
                row[key] = "true" if val else "false"
            else:
                row[key] = val
        return row

    @classmethod
    def from_csv_row(cls, row: dict[str, str]) -> ChapterMetrics:
        """从 CSV DictReader 行重建 ChapterMetrics。

        自动处理类型转换和布尔值反序列化。
        """
        # 字段类型映射
        int_fields = {
            "ch_num", "wc", "para_count", "avg_para_len",
            "slap_count", "level_count", "crush_count", "comeback_count",
            "hidden_count", "bond_count", "cognitive_count", "sacrifice_count",
            "physio_count", "strategy_count", "resource_count", "social_count",
            "backfire_count", "trap_master_count", "knowledge_gap_count",
            "hidden_value_count", "identity_reveal_count", "foreshadow_payoff_count",
            "anti_trope_count", "high_emotion_count", "burnout_count",
        }
        float_fields = {
            "dialogue_ratio", "excl_density", "pos_density", "neg_density",
            "conflict_density", "hook_density", "pleasure_intensity",
            "readability", "avg_sentence_len", "vocab_diversity",
            "ch_variability", "emotion_valence",
        }
        bool_fields = {"anti_trope", "emotion_burnout", "slap_noise"}

        kwargs = {}
        for f in cls.__dataclass_fields__:
            if f not in row:
                continue
            raw = row[f]
            if f in int_fields:
                try:
                    kwargs[f] = int(float(raw))
                except (ValueError, TypeError):
                    kwargs[f] = 0
            elif f in float_fields:
                try:
                    kwargs[f] = float(raw)
                except (ValueError, TypeError):
                    kwargs[f] = 0.0
            elif f in bool_fields:
                kwargs[f] = str(raw).lower() in ("true", "1", "yes")
            else:
                kwargs[f] = raw
        return cls(**kwargs)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ChapterMetrics:
        """从 rule_analyze 返回的 dict 创建 ChapterMetrics。

        与 to_csv_row 不同，布尔值保持原生类型。
        """
        kwargs = {}
        for f in cls.__dataclass_fields__:
            if f in d:
                kwargs[f] = d[f]
        return cls(**kwargs)

    # ── CSV 列名 (与 rhythm_analyzer.fields 列表完全一致) ──

    CSV_FIELDS: list[str] = field(default_factory=lambda: [
        "ch_num", "ch_hash", "wc", "para_count", "avg_para_len", "dialogue_ratio",
        "excl_density", "pos_density", "neg_density", "conflict_density", "hook_density",
        "slap_count", "level_count", "crush_count", "comeback_count", "hidden_count",
        "bond_count", "cognitive_count", "sacrifice_count", "physio_count",
        "strategy_count", "resource_count", "social_count",
        "backfire_count", "trap_master_count", "knowledge_gap_count",
        "hidden_value_count", "identity_reveal_count", "foreshadow_payoff_count",
        "dominant_sub",
        "pleasure_type", "pleasure_intensity", "pleasure_level", "pleasure_timing",
        "hook_type", "readability", "avg_sentence_len", "vocab_diversity",
        "conflict", "conflict_level", "emotion", "pace",
        "ch_variability",
        "anti_trope", "anti_trope_count", "emotion_valence", "emotion_burnout",
        "high_emotion_count", "burnout_count",
    ], repr=False)


# ============================================================
# 书籍摘要 (analyze_book 返回值)
# ============================================================

@dataclass
class BookSummary:
    """单本书的节奏分析摘要 (analyze_book 返回值)。"""

    name: str = ""
    total_chaps: int = 0
    total_words: int = 0
    avg_wc: int = 0
    pleasure_density: float = 0.0
    conflict_rate: float = 0.0
    avg_intensity: float = 0.0
    avg_hook: float = 0.0
    sub_dist: dict[str, int] = field(default_factory=dict)
    llm_correlation: float | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BookSummary:
        kwargs = {}
        for f in cls.__dataclass_fields__:
            if f in d:
                kwargs[f] = d[f]
        return cls(**kwargs)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
