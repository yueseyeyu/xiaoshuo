# -*- coding: utf-8 -*-
"""
outline_deviation.py — 大纲偏差检测 (P2.4)
============================================
来源: 建议文件 "P2 章节级节奏/爽点/情绪自动评审 → 大纲偏差检测"

核心功能:
  1. 对比章节正文与大纲/blueprint, 检测偏差
  2. 检测维度:
     - 事件覆盖: blueprint 中的事件是否在正文中出现
     - 人物出场: 预期人物是否出场
     - 情绪走向: 实际情绪是否与计划一致
     - 伏笔状态: 计划埋的伏笔是否埋下
     - 章末钩子: 计划的钩子是否在章末出现
  3. 生成偏差报告, 供 S3 评审和知识大脑使用

与现有模块的关系:
  - canon/schema.py: CHAPTER_BLUEPRINT_SCHEMA 定义了 blueprint 结构
  - canon/consistency_checker.py: 检查 canon 一致性 (事实层)
  - outline_deviation: 检查正文与计划的偏差 (执行层)
  - knowledge_brain: 偏差可记录为经验

设计原则:
  - 零 LLM 依赖: 纯关键词/规则匹配
  - 容错匹配: 不要求精确匹配, 关键词出现即可
  - 可配置: 检测维度可开关

用法:
  from xiaoshuo.pipeline.outline_deviation import OutlineDeviationChecker

  checker = OutlineDeviationChecker()
  result = checker.check(
      chapter_text="林凡握紧拳头，看向远处的魔王...",
      blueprint={
          "chapter_num": 15,
          "one_sentence": "主角挑战魔王",
          "characters": ["林凡", "魔王"],
          "conflict": "主角vs魔王",
          "cliffhanger": "魔王露出真面目",
          "foreshadowing_plant": "主角隐藏的能力",
      },
  )
  if result.has_deviations:
      print(result.summary)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from xiaoshuo.infra.logging_config import get_logger

logger = get_logger("outline_deviation")


# ============================================================
# 数据结构
# ============================================================

@dataclass
class DeviationItem:
    """单条偏差。"""
    dimension: str       # event / character / emotion / foreshadowing / cliffhanger
    severity: str        # ok / warning / serious
    expected: str = ""   # 预期内容
    found: str = ""      # 实际找到的内容
    matched: bool = False
    description: str = ""
    suggestion: str = ""


@dataclass
class DeviationResult:
    """大纲偏差检测结果。"""
    chapter_num: int = 0
    items: list[DeviationItem] = field(default_factory=list)
    coverage_score: float = 100.0  # 0-100, 越高越符合大纲
    has_deviations: bool = False
    has_serious: bool = False
    summary: str = ""
    top_issues: list[str] = field(default_factory=list)

    @property
    def deviation_count(self) -> int:
        return sum(1 for i in self.items if not i.matched)

    @property
    def matched_count(self) -> int:
        return sum(1 for i in self.items if i.matched)


# ============================================================
# OutlineDeviationChecker 主类
# ============================================================

class OutlineDeviationChecker:
    """大纲偏差检测器。

    用法:
        checker = OutlineDeviationChecker()
        result = checker.check(chapter_text="...", blueprint={...})
    """

    def check(
        self,
        chapter_text: str,
        blueprint: dict,
        chapter_num: int = 0,
    ) -> DeviationResult:
        """检测章节正文与 blueprint 的偏差。

        Args:
            chapter_text: 章节正文
            blueprint: 章节蓝图 dict (参见 CHAPTER_BLUEPRINT_SCHEMA)
            chapter_num: 章节号

        Returns:
            DeviationResult
        """
        result = DeviationResult(chapter_num=chapter_num or blueprint.get("chapter_num", 0))

        if not chapter_text:
            result.summary = "无正文, 跳过偏差检测"
            return result

        if not blueprint:
            result.summary = "无 blueprint, 跳过偏差检测"
            return result

        # ── 1. 事件覆盖检测 ──
        self._check_events(chapter_text, blueprint, result)

        # ── 2. 人物出场检测 ──
        self._check_characters(chapter_text, blueprint, result)

        # ── 3. 冲突检测 ──
        self._check_conflict(chapter_text, blueprint, result)

        # ── 4. 伏笔检测 ──
        self._check_foreshadowing(chapter_text, blueprint, result)

        # ── 5. 章末钩子检测 ──
        self._check_cliffhanger(chapter_text, blueprint, result)

        # ── 6. 情绪变化检测 ──
        self._check_emotion(chapter_text, blueprint, result)

        # 计算覆盖分数
        self._compute_score(result)
        self._build_summary(result)

        if result.has_deviations:
            logger.info("大纲偏差 ch%d: %d 项偏差, 覆盖率 %.0f%%",
                        result.chapter_num, result.deviation_count,
                        result.coverage_score)

        return result

    # ── 各维度检测 ──

    def _check_events(self, text: str, blueprint: dict, result: DeviationResult):
        """检测 blueprint 中的关键事件是否在正文中出现。"""
        # 从 one_sentence 和 purpose 提取关键词
        keywords = self._extract_keywords(blueprint.get("one_sentence", ""))
        keywords += self._extract_keywords(blueprint.get("purpose", ""))
        keywords += self._extract_keywords(blueprint.get("protagonist_action", ""))

        if not keywords:
            return

        matched_keywords = [kw for kw in keywords if kw in text]
        unmatched = [kw for kw in keywords if kw not in text]

        if unmatched and len(matched_keywords) < len(keywords) * 0.3:
            # 不到 30% 关键词出现 → 严重偏差
            result.items.append(DeviationItem(
                dimension="event",
                severity="serious",
                expected="、".join(keywords[:5]),
                found="、".join(matched_keywords[:5]) if matched_keywords else "(无)",
                matched=False,
                description=f"大纲关键事件未在正文中体现: 缺失 {', '.join(unmatched[:3])}",
                suggestion="检查本章是否偏离了大纲规划的核心事件",
            ))
        elif unmatched:
            result.items.append(DeviationItem(
                dimension="event",
                severity="warning",
                expected="、".join(keywords[:5]),
                found="、".join(matched_keywords[:5]),
                matched=len(matched_keywords) >= len(keywords) * 0.5,
                description=f"部分大纲事件未出现: {', '.join(unmatched[:3])}",
                suggestion="确认遗漏是有意为之还是疏忽",
            ))
        else:
            result.items.append(DeviationItem(
                dimension="event",
                severity="ok",
                expected="、".join(keywords[:3]),
                found="、".join(matched_keywords[:3]),
                matched=True,
            ))

    def _check_characters(self, text: str, blueprint: dict, result: DeviationResult):
        """检测预期人物是否出场。"""
        characters = blueprint.get("characters", [])
        if not characters:
            return

        missing = []
        for char in characters:
            if char and char not in text:
                missing.append(char)

        if missing:
            severity = "serious" if len(missing) == len(characters) else "warning"
            result.items.append(DeviationItem(
                dimension="character",
                severity=severity,
                expected="、".join(characters),
                found="、".join(c for c in characters if c in text) or "(无)",
                matched=False,
                description=f"预期人物未出场: {', '.join(missing)}",
                suggestion="确保所有 blueprint 中列出的人物在本章出现",
            ))
        else:
            result.items.append(DeviationItem(
                dimension="character",
                severity="ok",
                expected="、".join(characters),
                found="、".join(characters),
                matched=True,
            ))

    def _check_conflict(self, text: str, blueprint: dict, result: DeviationResult):
        """检测核心冲突是否体现。"""
        conflict = blueprint.get("conflict", "")
        if not conflict:
            return

        keywords = self._extract_keywords(conflict)
        if not keywords:
            return

        matched = [kw for kw in keywords if kw in text]
        if not matched:
            result.items.append(DeviationItem(
                dimension="conflict",
                severity="warning",
                expected=conflict,
                found="(未检测到冲突关键词)",
                matched=False,
                description=f"核心冲突未在正文中体现: {conflict}",
                suggestion="确保本章围绕 blueprint 中的核心冲突展开",
            ))
        else:
            result.items.append(DeviationItem(
                dimension="conflict",
                severity="ok",
                expected=conflict,
                found="、".join(matched),
                matched=True,
            ))

    def _check_foreshadowing(self, text: str, blueprint: dict, result: DeviationResult):
        """检测计划埋的伏笔是否埋下。"""
        foreshadow = blueprint.get("foreshadowing_plant", "")
        if not foreshadow:
            return  # 本章无伏笔计划

        keywords = self._extract_keywords(foreshadow)
        if not keywords:
            return

        matched = [kw for kw in keywords if kw in text]
        if not matched:
            result.items.append(DeviationItem(
                dimension="foreshadowing",
                severity="warning",
                expected=foreshadow,
                found="(未检测到伏笔)",
                matched=False,
                description=f"计划埋的伏笔未出现: {foreshadow}",
                suggestion="检查伏笔是否已埋下, 或调整 blueprint",
            ))
        else:
            result.items.append(DeviationItem(
                dimension="foreshadowing",
                severity="ok",
                expected=foreshadow,
                found="、".join(matched),
                matched=True,
            ))

    def _check_cliffhanger(self, text: str, blueprint: dict, result: DeviationResult):
        """检测章末钩子。"""
        cliffhanger = blueprint.get("cliffhanger", "")
        if not cliffhanger:
            return  # 无计划钩子

        # 只检测最后 500 字
        ending = text[-500:] if len(text) > 500 else text

        keywords = self._extract_keywords(cliffhanger)
        if not keywords:
            return

        matched = [kw for kw in keywords if kw in ending]
        if not matched:
            # 检查全文 (可能钩子提前了)
            full_matched = [kw for kw in keywords if kw in text]
            if full_matched:
                result.items.append(DeviationItem(
                    dimension="cliffhanger",
                    severity="warning",
                    expected=cliffhanger,
                    found=f"(在正文中出现但非章末)",
                    matched=False,
                    description=f"钩子内容未在章末出现: {cliffhanger}",
                    suggestion="将钩子内容调整到章末位置",
                ))
            else:
                result.items.append(DeviationItem(
                    dimension="cliffhanger",
                    severity="serious",
                    expected=cliffhanger,
                    found="(未检测到钩子)",
                    matched=False,
                    description=f"计划的章末钩子未出现: {cliffhanger}",
                    suggestion="在章末添加 blueprint 中计划的钩子",
                ))
        else:
            result.items.append(DeviationItem(
                dimension="cliffhanger",
                severity="ok",
                expected=cliffhanger,
                found="、".join(matched),
                matched=True,
            ))

    def _check_emotion(self, text: str, blueprint: dict, result: DeviationResult):
        """检测情绪变化方向。"""
        emotion_changes = blueprint.get("emotion_changes", {})
        protagonist_emotion = emotion_changes.get("protagonist", "") if isinstance(emotion_changes, dict) else ""

        if not protagonist_emotion:
            return

        # 提取情绪关键词 (如 "期待 → 疑虑 → 震惊 → 克制")
        emotions = re.split(r'→|->', protagonist_emotion)
        emotions = [e.strip() for e in emotions if e.strip()]

        if not emotions:
            return

        # 检查情绪词是否在文本中出现 (简化检测)
        emotion_keywords = {
            "期待": ["期待", "期盼", "等着", "希望"],
            "疑虑": ["疑虑", "怀疑", "不确定", "困惑", "疑惑"],
            "震惊": ["震惊", "惊讶", "不敢相信", "骇然", "震惊"],
            "克制": ["克制", "忍耐", "压制", "冷静", "镇定"],
            "愤怒": ["愤怒", "怒火", "暴怒", "气", "怒"],
            "恐惧": ["恐惧", "害怕", "畏惧", "惊恐", "骇"],
            "兴奋": ["兴奋", "激动", "振奋", "雀跃"],
            "绝望": ["绝望", "崩溃", "无望", "放弃"],
            "平静": ["平静", "冷静", "淡然", "沉默"],
        }

        missing_emotions = []
        for emotion in emotions:
            synonyms = emotion_keywords.get(emotion, [emotion])
            if not any(syn in text for syn in synonyms):
                missing_emotions.append(emotion)

        if missing_emotions and len(missing_emotions) > len(emotions) / 2:
            result.items.append(DeviationItem(
                dimension="emotion",
                severity="warning",
                expected=protagonist_emotion,
                found=f"缺失情绪: {', '.join(missing_emotions)}",
                matched=False,
                description=f"情绪变化方向与计划不符: 缺失 {', '.join(missing_emotions)}",
                suggestion="调整正文情绪节奏, 确保 blueprint 中的情绪变化得到体现",
            ))
        else:
            result.items.append(DeviationItem(
                dimension="emotion",
                severity="ok",
                expected=protagonist_emotion,
                found=protagonist_emotion,
                matched=True,
            ))

    # ── 辅助方法 ──

    def _extract_keywords(self, text: str) -> list[str]:
        """从文本中提取关键词 (简化: 提取 2-4 字中文词)。

        这是一个非常简化的关键词提取, 不依赖分词库。
        主要提取:
        1. 引号内的内容
        2. 2-4 字连续中文
        """
        if not text:
            return []

        keywords = []

        # 引号内容 (中文引号 + 英文引号)
        quote_pattern = re.compile(r'[\u201c\u201d\u2018\u2019"\'](.+?)[\u201c\u201d\u2018\u2019"\']')
        for m in quote_pattern.finditer(text):
            keywords.append(m.group(1))

        # 2-4 字连续中文词 (简化: 滑动窗口)
        # 跳过常见停用词
        stopwords = {"这是", "一个", "就是", "为了", "什么", "可以",
                     "他们", "自己", "不会", "没有", "如果", "已经",
                     "这个", "那个", "这种", "以及", "但是", "因为"}

        # 提取 2-4 字的中文片段
        chinese_words = re.findall(r'[\u4e00-\u9fff]{2,4}', text)
        seen = set()
        for word in chinese_words:
            if word not in stopwords and word not in seen and len(word) >= 2:
                keywords.append(word)
                seen.add(word)

        # 去重, 最多取 10 个
        seen2 = set()
        unique = []
        for kw in keywords:
            if kw not in seen2:
                unique.append(kw)
                seen2.add(kw)
            if len(unique) >= 10:
                break

        return unique

    def _compute_score(self, result: DeviationResult):
        """计算覆盖率分数。"""
        if not result.items:
            result.coverage_score = 100.0
            return

        matched = result.matched_count
        total = len(result.items)
        result.coverage_score = (matched / total) * 100.0

    def _build_summary(self, result: DeviationResult):
        """生成摘要。"""
        deviations = [i for i in result.items if not i.matched]
        result.has_deviations = len(deviations) > 0
        result.has_serious = any(i.severity == "serious" for i in deviations)

        if not deviations:
            result.summary = (
                f"✅ 大纲偏差检测: 通过 ({result.matched_count}/{len(result.items)} 项匹配, "
                f"覆盖率 {result.coverage_score:.0f}%)"
            )
            return

        parts = [
            f"大纲偏差检测: {result.deviation_count} 项偏差 "
            f"(覆盖率 {result.coverage_score:.0f}%)"
        ]
        for item in deviations:
            icon = {"serious": "[!!!]", "warning": "[!]"}.get(item.severity, "[?]")
            parts.append(f"  {icon} [{item.dimension}] {item.description}")
            if item.suggestion:
                parts.append(f"    → {item.suggestion}")

        result.summary = "\n".join(parts)
        result.top_issues = [
            f"{i.description}: {i.suggestion}"
            for i in deviations if i.severity == "serious"
        ][:3]


# ============================================================
# 便捷函数
# ============================================================

_checker_instance: OutlineDeviationChecker | None = None


def get_outline_deviation_checker() -> OutlineDeviationChecker:
    """获取全局单例。"""
    global _checker_instance
    if _checker_instance is None:
        _checker_instance = OutlineDeviationChecker()
    return _checker_instance


def check_outline_deviation(
    chapter_text: str,
    blueprint: dict,
    chapter_num: int = 0,
) -> DeviationResult:
    """便捷函数: 大纲偏差检测。"""
    return get_outline_deviation_checker().check(
        chapter_text, blueprint, chapter_num
    )


def outline_deviation_as_s3_check(
    chapter_text: str,
    blueprint: dict,
    chapter_num: int = 0,
) -> dict:
    """S3 集成接口。"""
    result = check_outline_deviation(chapter_text, blueprint, chapter_num)
    return {
        "dimension": "outline_deviation",
        "coverage_score": result.coverage_score,
        "has_deviations": result.has_deviations,
        "deviation_count": result.deviation_count,
        "summary": result.summary,
        "top_issues": result.top_issues,
    }
