# -*- coding: utf-8 -*-
"""
chapter_goal_gate.py — 章节完成标准 + 独立 Judge 验证 (P2)
=============================================================
来源: 建议文件 "MiMo Code → Goal / Stop Condition → 你的章节完成标准"

核心理念:
  防止 Agent 的"乐观提前停止" — Agent 说"写完了"，但实际质量不达标。
  引入显式完成标准 + 独立 judge model 验证。

工作流程:
  1. 为每章设置 /goal 条件 (5条硬性标准)
  2. 写作完成后，独立 judge model 逐条验证
  3. 全部满足 → 真正完成 (PASS)
  4. 有未满足 → 返回具体缺失项，继续迭代 (RETRY)

与现有模块的关系:
  - quality_gate.py: 管线级品质关卡 (Gate A/B, 整本书级别)
  - chapter_goal_gate.py: 章节级完成标准 (单章级别, 更精细)
  - cross_review.py: 双模型交叉审查 (发现质量问题)
  - chapter_goal_gate.py: 双模型 Goal 验证 (验证完成标准)
  - context_budget.py: Context 预算管理 (Goal 验证的上下文来源)

设计原则:
  - 独立 judge: 验证模型 ≠ 写作模型，避免"自评自赞"
  - 显式标准: 5条硬性条件，不靠模型主观判断
  - 可配置: 每章的 goal 条件可自定义
  - 可追溯: 验证结果记录，供后续分析

用法:
  from xiaoshuo.pipeline.chapter_goal_gate import ChapterGoalGate, GoalCondition

  # 设置章节完成标准
  goal = GoalCondition(
      chapter_num=15,
      target_chars=(3000, 5000),
      min_pleasure_points=1,
      emotion_curve_template="rising",
      require_canon_check=True,
      min_s3_score=70,
  )

  # 独立 judge 验证
  gate = ChapterGoalGate()
  result = gate.verify(chapter_text, goal, context={
      "canon_rules": {...},
      "prev_chapter_summary": "...",
  })

  if result.passed:
      print("章节完成!")
  else:
      print(f"未通过: {result.failed_conditions}")
      # → ["字数不足 (2500 < 3000)", "S3评分偏低 (65 < 70)"]
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from xiaoshuo import PROJECT_ROOT
from xiaoshuo.infra.logging_config import get_logger
from xiaoshuo.pipeline.text_utils import (
    count_chinese as _count_chinese,
    split_paragraphs as _split_paragraphs,
    split_sentences as _split_sentences,
    count_exclamations as _count_exclamations,
    extract_dialogues as _extract_dialogues,
)

logger = get_logger("chapter_goal_gate")


# ============================================================
# 路径常量
# ============================================================

_GOAL_LOG_DIR = PROJECT_ROOT / "data" / "checkpoints" / "goal_gate"


# ============================================================
# 枚举
# ============================================================

class GoalResult(Enum):
    """验证结果。"""
    PASS = "pass"          # 全部满足 → 真正完成
    RETRY = "retry"        # 有未满足 → 返回具体缺失项，继续迭代
    FAIL = "fail"          # 严重问题 → 无法通过迭代解决


# ============================================================
# Goal 条件定义
# ============================================================

@dataclass
class GoalCondition:
    """章节完成标准 (/goal 条件)。

    每章的 5 条硬性完成标准。
    """
    chapter_num: int                        # 章节号
    target_chars: tuple[int, int] = (3000, 5000)  # 字数目标区间
    min_pleasure_points: int = 1            # 最少即时/延迟爽点数
    emotion_curve_template: str = "rising"  # 情绪曲线模板 (rising/wave/peak/valley)
    require_canon_check: bool = True        # 是否要求 Canon 一致性检查通过
    min_s3_score: float = 70.0              # S3 评审最低得分
    # 可选: 自定义额外条件
    custom_conditions: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "chapter_num": self.chapter_num,
            "target_chars": list(self.target_chars),
            "min_pleasure_points": self.min_pleasure_points,
            "emotion_curve_template": self.emotion_curve_template,
            "require_canon_check": self.require_canon_check,
            "min_s3_score": self.min_s3_score,
            "custom_conditions": self.custom_conditions,
        }


# ============================================================
# 验证结果
# ============================================================

@dataclass
class ConditionResult:
    """单条条件的验证结果。"""
    name: str               # 条件名称
    passed: bool            # 是否通过
    detail: str             # 详细信息
    actual_value: object = None  # 实际值
    target_value: object = None  # 目标值


@dataclass
class GoalVerificationResult:
    """章节 Goal 验证结果。"""
    chapter_num: int
    result: GoalResult                     # PASS / RETRY / FAIL
    conditions: list[ConditionResult]      # 各条件验证结果
    failed_conditions: list[str]           # 未通过的条件名称列表
    suggestions: list[str]                 # 改进建议
    verified_at: str = ""                  # 验证时间
    judge_model: str = ""                  # 验证模型名
    iteration: int = 0                     # 第几次迭代

    def __post_init__(self):
        if not self.verified_at:
            self.verified_at = datetime.now().isoformat()

    @property
    def passed(self) -> bool:
        """是否通过。"""
        return self.result == GoalResult.PASS

    def to_dict(self) -> dict:
        return {
            "chapter_num": self.chapter_num,
            "result": self.result.value,
            "conditions": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "detail": c.detail,
                    "actual_value": c.actual_value,
                    "target_value": c.target_value,
                }
                for c in self.conditions
            ],
            "failed_conditions": self.failed_conditions,
            "suggestions": self.suggestions,
            "verified_at": self.verified_at,
            "judge_model": self.judge_model,
            "iteration": self.iteration,
        }


# ============================================================
# 情绪曲线模板
# ============================================================

_EMOTION_TEMPLATES = {
    "rising": {
        "desc": "上升曲线 (渐入佳境)",
        "check": lambda intensities: intensities[-1] > intensities[0] * 1.2 if len(intensities) >= 2 else False,
    },
    "wave": {
        "desc": "波浪曲线 (高低交替)",
        "check": lambda intensities: _check_wave(intensities),
    },
    "peak": {
        "desc": "高峰曲线 (中段爆发)",
        "check": lambda intensities: _check_peak(intensities),
    },
    "valley": {
        "desc": "低谷曲线 (先抑后扬)",
        "check": lambda intensities: intensities[-1] > intensities[0] and min(intensities) < 0.3 if len(intensities) >= 3 else False,
    },
    "any": {
        "desc": "任意曲线 (不检查)",
        "check": lambda intensities: True,
    },
}


def _check_wave(intensities: list[float]) -> bool:
    """检查是否为波浪曲线 (至少2个峰)。"""
    if len(intensities) < 4:
        return False
    peaks = 0
    for i in range(1, len(intensities) - 1):
        if intensities[i] > intensities[i - 1] and intensities[i] > intensities[i + 1]:
            peaks += 1
    return peaks >= 2


def _check_peak(intensities: list[float]) -> bool:
    """检查是否为高峰曲线 (中段最高)。"""
    if len(intensities) < 3:
        return False
    mid = len(intensities) // 2
    mid_max = max(intensities[mid - 1:mid + 2]) if mid > 0 else intensities[mid]
    return mid_max == max(intensities) and mid_max > 0.5


# ============================================================
# 爽点检测
# ============================================================

# 即时爽点关键词
_INSTANT_PLEASURE_PAT = re.compile(
    r'打脸|震惊|倒吸.*凉气|不敢相信|瞪大.*眼|轰然|炸裂|颠覆|秒杀|碾压|一拳|一脚|瞬间'
)
# 延迟爽点关键词
_DELAYED_PLEASURE_PAT = re.compile(
    r'原来.*如此|真相.*大白|伏笔.*回收|难怪|终于明白|恍然大悟|之前.*铺垫|一切.*计划'
)


def _count_pleasure_points(text: str) -> tuple[int, int]:
    """统计爽点数量。

    Returns:
        (即时爽点数, 延迟爽点数)
    """
    instant = len(_INSTANT_PLEASURE_PAT.findall(text))
    delayed = len(_DELAYED_PLEASURE_PAT.findall(text))
    return instant, delayed


# ============================================================
# 章节 Goal Gate 主类
# ============================================================

class ChapterGoalGate:
    """章节完成标准 + 独立 Judge 验证。

    工作流程:
      1. 设置 Goal 条件 (5条硬性标准)
      2. 写作完成后，独立 judge 逐条验证
      3. 全部满足 → PASS
      4. 有未满足 → RETRY (返回具体缺失项)
      5. 严重问题 → FAIL

    用法:
      gate = ChapterGoalGate()
      result = gate.verify(chapter_text, goal, context={...})
    """

    def __init__(self, judge_model: str = "independent_judge"):
        """
        Args:
            judge_model: 验证模型名 (标识是哪个模型做的验证)
        """
        self.judge_model = judge_model
        self._log_dir = _GOAL_LOG_DIR
        self._log_dir.mkdir(parents=True, exist_ok=True)

    def verify(
        self,
        chapter_text: str,
        goal: GoalCondition,
        context: Optional[dict] = None,
        iteration: int = 0,
    ) -> GoalVerificationResult:
        """验证章节是否满足 Goal 条件。

        Args:
            chapter_text: 章节正文
            goal: 完成标准
            context: 上下文信息 (canon_rules, prev_summary, s3_score 等)
            iteration: 第几次迭代验证 (第1次=0)

        Returns:
            GoalVerificationResult
        """
        context = context or {}
        conditions: list[ConditionResult] = []
        suggestions: list[str] = []

        # ── 条件1: 字数检查 ──
        char_count = _count_chinese(chapter_text)
        min_chars, max_chars = goal.target_chars
        char_passed = min_chars <= char_count <= max_chars
        if char_count < min_chars:
            char_detail = f"字数不足 ({char_count} < {min_chars})"
            suggestions.append(f"需增加约 {min_chars - char_count} 字")
        elif char_count > max_chars:
            char_detail = f"字数超标 ({char_count} > {max_chars})"
            suggestions.append(f"需删减约 {char_count - max_chars} 字")
        else:
            char_detail = f"字数达标 ({char_count} 字)"
        conditions.append(ConditionResult(
            name="字数检查",
            passed=char_passed,
            detail=char_detail,
            actual_value=char_count,
            target_value=list(goal.target_chars),
        ))

        # ── 条件2: 爽点检查 ──
        instant, delayed = _count_pleasure_points(chapter_text)
        total_pleasure = instant + delayed
        pleasure_passed = total_pleasure >= goal.min_pleasure_points
        if not pleasure_passed:
            pleasure_detail = f"爽点不足 ({total_pleasure} < {goal.min_pleasure_points}, 即时{instant}/延迟{delayed})"
            suggestions.append("增加即时爽点(打脸/震惊/碾压)或延迟爽点(伏笔回收/真相揭示)")
        else:
            pleasure_detail = f"爽点达标 ({total_pleasure}个, 即时{instant}/延迟{delayed})"
        conditions.append(ConditionResult(
            name="爽点检查",
            passed=pleasure_passed,
            detail=pleasure_detail,
            actual_value=total_pleasure,
            target_value=goal.min_pleasure_points,
        ))

        # ── 条件3: 情绪曲线检查 ──
        # 将章节分为5段，计算每段情绪强度
        paras = _split_paragraphs(chapter_text)
        if len(paras) >= 5:
            segment_size = len(paras) // 5
            intensities = []
            for i in range(5):
                segment_text = "\n".join(paras[i * segment_size:(i + 1) * segment_size])
                exclam = _count_exclamations(segment_text)
                segment_chars = _count_chinese(segment_text)
                intensity = min(1.0, exclam / max(segment_chars / 500, 0.1))
                intensities.append(intensity)
        else:
            # 段落太少，用整体情绪强度
            exclam = _count_exclamations(chapter_text)
            intensities = [min(1.0, exclam / max(char_count / 500, 0.1))]

        template = _EMOTION_TEMPLATES.get(goal.emotion_curve_template, _EMOTION_TEMPLATES["any"])
        emotion_passed = template["check"](intensities)
        if not emotion_passed:
            emotion_detail = f"情绪曲线不符 (模板: {template['desc']}, 实际: {[round(i, 2) for i in intensities]})"
            suggestions.append(f"调整情绪节奏以匹配'{template['desc']}'模板")
        else:
            emotion_detail = f"情绪曲线达标 (模板: {template['desc']})"
        conditions.append(ConditionResult(
            name="情绪曲线",
            passed=emotion_passed,
            detail=emotion_detail,
            actual_value=[round(i, 3) for i in intensities],
            target_value=goal.emotion_curve_template,
        ))

        # ── 条件4: Canon 一致性检查 ──
        if goal.require_canon_check:
            canon_result = context.get("canon_check_result")
            if canon_result is not None:
                canon_passed = canon_result.get("passed", False)
                canon_violations = canon_result.get("violations", [])
                if canon_passed:
                    canon_detail = "Canon 一致性检查通过"
                else:
                    canon_detail = f"Canon 一致性检查未通过 ({len(canon_violations)}处违规)"
                    suggestions.append(f"修复 Canon 违规: {', '.join(canon_violations[:3])}")
            else:
                # 没有提供 canon 检查结果 → 标记为未检查
                canon_passed = False
                canon_detail = "Canon 一致性检查未执行 (缺少 context.canon_check_result)"
                suggestions.append("执行 Canon 一致性检查并传入结果")
            conditions.append(ConditionResult(
                name="Canon一致性",
                passed=canon_passed,
                detail=canon_detail,
                actual_value=canon_result,
                target_value="passed=True",
            ))

        # ── 条件5: S3 评审得分 ──
        s3_score = context.get("s3_score")
        if s3_score is not None:
            s3_passed = s3_score >= goal.min_s3_score
            if s3_passed:
                s3_detail = f"S3 评审达标 ({s3_score} >= {goal.min_s3_score})"
            else:
                s3_detail = f"S3 评审偏低 ({s3_score} < {goal.min_s3_score})"
                suggestions.append(f"提升 S3 评审得分 (需+{goal.min_s3_score - s3_score:.1f}分)")
            conditions.append(ConditionResult(
                name="S3评审",
                passed=s3_passed,
                detail=s3_detail,
                actual_value=s3_score,
                target_value=goal.min_s3_score,
            ))
        else:
            # S3 评审未执行 → 降级为不检查
            conditions.append(ConditionResult(
                name="S3评审",
                passed=True,
                detail="S3 评审未执行 (已跳过)",
                actual_value=None,
                target_value=goal.min_s3_score,
            ))

        # ── 自定义条件检查 ──
        for custom in goal.custom_conditions:
            name = custom.get("name", "自定义条件")
            check_fn = custom.get("check_fn")
            if check_fn and callable(check_fn):
                try:
                    custom_passed = check_fn(chapter_text, context)
                except Exception as e:
                    custom_passed = False
                    logger.warning(f"自定义条件 '{name}' 执行失败: {e}")
            else:
                custom_passed = True
            conditions.append(ConditionResult(
                name=name,
                passed=custom_passed,
                detail=f"自定义条件 {'通过' if custom_passed else '未通过'}",
            ))

        # ── 汇总结果 ──
        failed = [c.name for c in conditions if not c.passed]

        if not failed:
            result = GoalResult.PASS
        elif len(failed) <= 2:
            result = GoalResult.RETRY
        else:
            result = GoalResult.FAIL

        verification = GoalVerificationResult(
            chapter_num=goal.chapter_num,
            result=result,
            conditions=conditions,
            failed_conditions=failed,
            suggestions=suggestions,
            judge_model=self.judge_model,
            iteration=iteration,
        )

        # 记录日志
        self._log(verification)

        logger.info(
            f"章节{goal.chapter_num} Goal验证: {result.value} "
            f"(迭代{iteration}, 失败条件: {failed or '无'})"
        )
        return verification

    def _log(self, result: GoalVerificationResult) -> None:
        """记录验证结果到日志文件。"""
        log_file = self._log_dir / f"ch{result.chapter_num}_goal.json"

        # 追加模式 (同一章节可能有多次迭代)
        logs: list = []
        if log_file.exists():
            try:
                logs = json.loads(log_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                logs = []

        logs.append(result.to_dict())
        log_file.write_text(
            json.dumps(logs, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_history(self, chapter_num: int) -> list[dict]:
        """获取某章的 Goal 验证历史。

        Args:
            chapter_num: 章节号

        Returns:
            验证记录列表 (按时间排序)
        """
        log_file = self._log_dir / f"ch{chapter_num}_goal.json"
        if not log_file.exists():
            return []
        try:
            return json.loads(log_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            return []

    def format_result_for_prompt(self, result: GoalVerificationResult) -> str:
        """将验证结果格式化为 prompt 上下文 (供迭代时使用)。"""
        lines = [f"=== 章节{result.chapter_num} Goal 验证结果 (第{result.iteration + 1}轮) ==="]
        lines.append(f"总体: {'✅ 通过' if result.passed else '❌ 未通过'}")
        lines.append("")
        lines.append("条件明细:")
        for c in result.conditions:
            icon = "✅" if c.passed else "❌"
            lines.append(f"  {icon} {c.name}: {c.detail}")

        if result.suggestions:
            lines.append("\n改进建议:")
            for s in result.suggestions:
                lines.append(f"  → {s}")

        if not result.passed:
            lines.append(f"\n请根据以上建议修改后重新提交 (当前失败: {', '.join(result.failed_conditions)})")

        return "\n".join(lines)


# ============================================================
# 便捷函数
# ============================================================

def create_default_goal(chapter_num: int, genre: str = "玄幻") -> GoalCondition:
    """创建默认的章节完成标准。

    Args:
        chapter_num: 章节号
        genre: 题材 (不同题材的默认标准不同)

    Returns:
        GoalCondition
    """
    # 题材特定的默认配置
    genre_defaults = {
        "玄幻": {"target_chars": (3000, 5000), "min_pleasure_points": 1, "emotion_curve": "rising"},
        "都市": {"target_chars": (2500, 4000), "min_pleasure_points": 1, "emotion_curve": "wave"},
        "悬疑": {"target_chars": (3000, 5000), "min_pleasure_points": 0, "emotion_curve": "peak"},
        "科幻": {"target_chars": (3000, 6000), "min_pleasure_points": 1, "emotion_curve": "rising"},
        "末世": {"target_chars": (3000, 5000), "min_pleasure_points": 1, "emotion_curve": "valley"},
    }

    defaults = genre_defaults.get(genre, genre_defaults["玄幻"])

    # 黄金三章 (前3章) 特殊处理: 要求更高的爽点密度
    if chapter_num <= 3:
        defaults["min_pleasure_points"] = max(defaults["min_pleasure_points"], 2)
        defaults["emotion_curve"] = "rising"

    return GoalCondition(
        chapter_num=chapter_num,
        target_chars=defaults["target_chars"],
        min_pleasure_points=defaults["min_pleasure_points"],
        emotion_curve_template=defaults["emotion_curve"],
        require_canon_check=True,
        min_s3_score=70.0,
    )
