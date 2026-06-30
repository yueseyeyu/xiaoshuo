# -*- coding: utf-8 -*-
"""
style_consistency_lens.py — S3 风格一致性审查 (P2.2)
======================================================
来源: 建议文件 "女娲造人 → 说话方式检测 → S3 评审增加风格一致性维度"

核心功能:
  1. 基于 Style DNA (P1.3) 对比当前章节与基线的风格偏离
  2. 检测 AI 指纹词密度异常
  3. 检测对话/描写比例突变
  4. 检测句长分布偏移
  5. 生成 S3 可用的审查结果

与现有模块的关系:
  - style_dna.py (P1.3): 提供五维指纹提取和偏离检测
  - s3_extensions/five_dimension_check.py: D1-D5 五维审查
  - style_consistency_lens: 专注风格维度的 S3 扩展 (Part E 风格进化)

设计原则:
  - 零 LLM 依赖: 纯统计/规则检测
  - 与 five_dimension_check 同构: StyleConsistencyResult -> S3 注入

用法:
  from xiaoshuo.pipeline.s3_extensions.style_consistency_lens import (
      StyleConsistencyLens, check_style_consistency
  )
  from xiaoshuo.pipeline.style_dna import build_dna_baseline

  baseline = build_dna_baseline([ch1, ch2, ch3])
  result = check_style_consistency(chapter_text, baseline)
  if result.has_issues:
      print(result.summary)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from xiaoshuo.infra.logging_config import get_logger

logger = get_logger("style_consistency")


# ============================================================
# 数据结构
# ============================================================

@dataclass
class StyleIssue:
    """单条风格问题。"""
    dimension: str       # syntax / vocabulary / rhythm / perspective / ai_fingerprint
    severity: str        # ok / warning / serious
    metric: str          # 指标名 (如 "dialogue_ratio")
    current: float = 0.0
    baseline: float = 0.0
    deviation: float = 0.0  # 偏离百分比
    description: str = ""
    suggestion: str = ""


@dataclass
class StyleConsistencyResult:
    """风格一致性审查结果。"""
    consistency_score: float = 100.0   # 0-100, 越高越一致
    grade: str = "A"                   # A/B/C/D/F
    issues: list[StyleIssue] = field(default_factory=list)
    has_issues: bool = False
    has_serious: bool = False
    summary: str = ""
    top_issues: list[str] = field(default_factory=list)

    @property
    def issue_count(self) -> int:
        return len(self.issues)


# ============================================================
# 阈值常量
# ============================================================

# 各指标的偏离阈值 (超出则报问题)
THRESHOLDS = {
    "avg_sentence_length":   {"warning": 0.30, "serious": 0.50},  # ±30% / ±50%
    "dialogue_ratio":        {"warning": 0.35, "serious": 0.60},
    "description_density":   {"warning": 0.40, "serious": 0.70},
    "short_sentence_ratio":  {"warning": 0.30, "serious": 0.50},
    "ai_fingerprint_density":{"warning": 2.0,  "serious": 5.0},   # 绝对值: >2/千字 / >5/千字
    "vocab_richness":        {"warning": 0.30, "serious": 0.50},
    "avg_paragraph_length":  {"warning": 0.40, "serious": 0.70},
    "humor_total":           {"warning": 0.50, "serious": 0.80},
    "first_person_ratio":    {"warning": 0.30, "serious": 0.50},
    "inner_monologue_density":{"warning": 0.50, "serious": 0.80},
}


# ============================================================
# StyleConsistencyLens 主类
# ============================================================

class StyleConsistencyLens:
    """S3 风格一致性审查镜头。

    用法:
        lens = StyleConsistencyLens()
        result = lens.check(chapter_text, baseline_dna)
    """

    def check(
        self,
        chapter_text: str,
        baseline_dna=None,
    ) -> StyleConsistencyResult:
        """审查章节风格一致性。

        Args:
            chapter_text: 章节正文
            baseline_dna: StyleDNA 基线 (来自 build_dna_baseline)
                          None = 仅检测 AI 指纹

        Returns:
            StyleConsistencyResult
        """
        from xiaoshuo.pipeline.style_dna import extract_dna

        result = StyleConsistencyResult()

        if not chapter_text or len(chapter_text) < 50:
            result.summary = "文本过短, 跳过风格一致性检测"
            return result

        current_dna = extract_dna(chapter_text)

        # 无基线 → 仅检测 AI 指纹
        if baseline_dna is None:
            self._check_ai_fingerprint_only(current_dna, result)
        else:
            self._check_full(current_dna, baseline_dna, result)

        # 计算一致性分数和评级
        self._compute_grade(result)

        # 生成摘要
        self._build_summary(result)

        return result

    def _check_ai_fingerprint_only(self, dna, result: StyleConsistencyResult):
        """仅检测 AI 指纹 (无基线模式)。"""
        ai_density = dna.ai_fingerprint_density
        if ai_density >= THRESHOLDS["ai_fingerprint_density"]["serious"]:
            result.issues.append(StyleIssue(
                dimension="ai_fingerprint",
                severity="serious",
                metric="ai_fingerprint_density",
                current=ai_density,
                deviation=ai_density,
                description=f"AI指纹词密度 {ai_density:.1f}/千字 (严重超标)",
                suggestion="大幅减少AI高频心理描写词, 改用动作和对话推进",
            ))
            result.has_serious = True
        elif ai_density >= THRESHOLDS["ai_fingerprint_density"]["warning"]:
            result.issues.append(StyleIssue(
                dimension="ai_fingerprint",
                severity="warning",
                metric="ai_fingerprint_density",
                current=ai_density,
                deviation=ai_density,
                description=f"AI指纹词密度 {ai_density:.1f}/千字 (偏高)",
                suggestion="注意控制AI高频词使用频率",
            ))

        result.has_issues = len(result.issues) > 0

    def _check_full(self, current, baseline, result: StyleConsistencyResult):
        """全维度对比检测。"""
        # ── D1 句法 ──
        self._compare_metric(
            result, "syntax", "avg_sentence_length",
            current.avg_sentence_length, baseline.avg_sentence_length,
            "平均句长", "句长波动过大, 注意保持一致的叙事节奏",
        )
        self._compare_metric(
            result, "syntax", "dialogue_ratio",
            current.dialogue_ratio, baseline.dialogue_ratio,
            "对话占比", "对话占比突变, 可能影响阅读节奏",
        )
        self._compare_metric(
            result, "syntax", "description_density",
            current.description_density, baseline.description_density,
            "描写密度", "描写密度偏离基线, 注意环境/动作描写比例",
        )
        self._compare_metric(
            result, "syntax", "short_sentence_ratio",
            current.short_sentence_ratio, baseline.short_sentence_ratio,
            "短句占比", "短句占比变化大, 影响节奏感",
        )

        # ── D2 词汇 ──
        self._compare_metric(
            result, "vocabulary", "ai_fingerprint_density",
            current.ai_fingerprint_density, baseline.ai_fingerprint_density,
            "AI指纹词密度", "AI指纹词密度异常, 减少高频心理描写词",
            is_absolute=True,
        )
        self._compare_metric(
            result, "vocabulary", "vocab_richness",
            current.vocab_richness, baseline.vocab_richness,
            "词汇丰富度", "词汇丰富度下降, 避免重复用词",
        )

        # ── D3 节奏 ──
        self._compare_metric(
            result, "rhythm", "avg_paragraph_length",
            current.avg_paragraph_length, baseline.avg_paragraph_length,
            "平均段落长度", "段落长度分布变化, 影响阅读节奏",
        )

        # ── D4 幽默 ──
        if baseline.humor_total > 0 or current.humor_total > 0:
            self._compare_metric(
                result, "rhythm", "humor_total",
                current.humor_total, baseline.humor_total,
                "幽默密度", "幽默风格偏离, 注意保持一致的幽默感",
            )

        # ── D5 视角 ──
        self._compare_metric(
            result, "perspective", "first_person_ratio",
            current.first_person_ratio, baseline.first_person_ratio,
            "第一人称占比", "视角比例变化, 注意保持人称一致",
        )
        self._compare_metric(
            result, "perspective", "inner_monologue_density",
            current.inner_monologue_density, baseline.inner_monologue_density,
            "内心独白密度", "内心独白比例变化, 注意叙事视角一致",
        )

        result.has_issues = len(result.issues) > 0
        result.has_serious = any(i.severity == "serious" for i in result.issues)

    def _compare_metric(
        self,
        result: StyleConsistencyResult,
        dimension: str,
        metric: str,
        current: float,
        baseline: float,
        label: str,
        suggestion: str,
        is_absolute: bool = False,
    ):
        """对比单个指标。"""
        if baseline == 0 and current == 0:
            return

        if is_absolute:
            # 绝对值检测 (如 AI 指纹词密度)
            deviation = current
            thresholds = THRESHOLDS.get(metric, {"warning": 999, "serious": 999})
        else:
            # 百分比偏离
            if baseline == 0:
                deviation = 1.0 if current > 0 else 0.0
            else:
                deviation = abs(current - baseline) / baseline
            thresholds = THRESHOLDS.get(metric, {"warning": 0.30, "serious": 0.50})

        if deviation >= thresholds["serious"]:
            result.issues.append(StyleIssue(
                dimension=dimension,
                severity="serious",
                metric=metric,
                current=current,
                baseline=baseline,
                deviation=deviation,
                description=f"{label}: 当前 {current:.2f} vs 基线 {baseline:.2f} (严重偏离)",
                suggestion=suggestion,
            ))
        elif deviation >= thresholds["warning"]:
            result.issues.append(StyleIssue(
                dimension=dimension,
                severity="warning",
                metric=metric,
                current=current,
                baseline=baseline,
                deviation=deviation,
                description=f"{label}: 当前 {current:.2f} vs 基线 {baseline:.2f} (偏离)",
                suggestion=suggestion,
            ))

    def _compute_grade(self, result: StyleConsistencyResult):
        """计算一致性分数和评级。"""
        if not result.issues:
            result.consistency_score = 100.0
            result.grade = "A"
            return

        # 每条问题扣分
        penalty = 0
        for issue in result.issues:
            if issue.severity == "serious":
                penalty += 20
            elif issue.severity == "warning":
                penalty += 8

        result.consistency_score = max(0.0, 100.0 - penalty)

        if result.consistency_score >= 90:
            result.grade = "A"
        elif result.consistency_score >= 75:
            result.grade = "B"
        elif result.consistency_score >= 60:
            result.grade = "C"
        elif result.consistency_score >= 40:
            result.grade = "D"
        else:
            result.grade = "F"

    def _build_summary(self, result: StyleConsistencyResult):
        """生成摘要文本。"""
        if not result.issues:
            result.summary = f"✅ 风格一致性: {result.grade} ({result.consistency_score:.0f}分)"
            return

        parts = [f"风格一致性: {result.grade} ({result.consistency_score:.0f}分)"]
        for issue in result.issues[:3]:
            parts.append(f"  [{issue.severity}] {issue.description}")
            if issue.suggestion:
                parts.append(f"    → {issue.suggestion}")

        result.summary = "\n".join(parts)
        result.top_issues = [
            f"{i.description}: {i.suggestion}"
            for i in result.issues if i.severity == "serious"
        ][:3]


# ============================================================
# 便捷函数
# ============================================================

_lens_instance: StyleConsistencyLens | None = None


def get_style_consistency_lens() -> StyleConsistencyLens:
    """获取全局单例。"""
    global _lens_instance
    if _lens_instance is None:
        _lens_instance = StyleConsistencyLens()
    return _lens_instance


def check_style_consistency(
    chapter_text: str,
    baseline_dna=None,
) -> StyleConsistencyResult:
    """便捷函数: 风格一致性检测。"""
    return get_style_consistency_lens().check(chapter_text, baseline_dna)


def style_consistency_as_s3_check(
    chapter_text: str,
    baseline_dna=None,
) -> dict:
    """S3 集成接口: 返回 S3 兼容的 dict 格式。

    Returns:
        {
            "dimension": "style_consistency",
            "grade": str,
            "consistency_score": float,
            "has_issues": bool,
            "issue_count": int,
            "summary": str,
            "top_issues": list[str],
        }
    """
    result = check_style_consistency(chapter_text, baseline_dna)
    return {
        "dimension": "style_consistency",
        "grade": result.grade,
        "consistency_score": result.consistency_score,
        "has_issues": result.has_issues,
        "issue_count": result.issue_count,
        "summary": result.summary,
        "top_issues": result.top_issues,
    }
