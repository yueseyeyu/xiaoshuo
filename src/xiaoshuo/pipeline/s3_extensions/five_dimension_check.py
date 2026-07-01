# -*- coding: utf-8 -*-
"""
five_dimension_check.py — S3 评审五维审查 (D1-D5)
====================================================
来源: 建议文件 "五维审查 → 补充 S3 评审维度"

五维互补检测:
  D1 逻辑一致性 (Logic)          — 事件因果/时间线自洽
  D2 人物行为合理性 (Character)   — 动机匹配/压力反应/作者强推
  D3 细节准确性 (Detail)          — 外貌/场景/数字前后一致
  D4 世界观一致性 (Canon)         — 新规则冲突/废弃设定引用
  D5 叙事节奏 (Pacing)           — 起承转合/水字数/对话比例

设计原则:
  - 零 LLM 依赖: 全部规则/统计检测
  - 可选 LLM 增强: detect(text, canon, use_llm=True)
  - 与 StyleDetector 同构: DimensionResult -> DetectionReport
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from xiaoshuo.infra.logging_config import get_logger
from xiaoshuo.pipeline.text_utils import (
    count_chinese as _count_chinese,
    split_sentences as _split_sentences,
)

logger = get_logger("five_dim_check")


@dataclass
class DimensionResult:
    """单维检测结果。"""
    dimension: str       # D1-D5
    name: str
    passed: bool
    severity: str = "ok"  # ok / warning / fail
    issues: list[str] = field(default_factory=list)
    suggestion: str = ""


@dataclass
class FiveDimReport:
    """五维审查汇总报告。"""
    dimensions: list[DimensionResult] = field(default_factory=list)
    total_pass: int = 0
    total_fail: int = 0
    summary: str = ""

    def add(self, dim: DimensionResult):
        self.dimensions.append(dim)
        if dim.passed:
            self.total_pass += 1
        else:
            self.total_fail += 1


def _extract_dialogues(text: str) -> list[str]:
    return re.findall(r'["""]([^"""]+)["""]', text)


# ── D1: 逻辑一致性 ──

def check_d1_logic(text: str, canon: dict | None = None) -> DimensionResult:
    """D1: 事件因果一致性 + 时间线自洽。

    规则检测:
      - 因果标记词密度 (因此/所以/导致/因为 → 后续是否有对应事件)
      - 时间线矛盾标记 (突然/忽然/之前/之后 的滥用)
      - 闪回/倒叙标记是否明确
    """
    issues = []
    chinese = _count_chinese(text)
    if chinese < 100:
        return DimensionResult("D1", "逻辑一致性", True, "ok", [], "文本太短")

    # 因果标记密度
    cause_markers = re.findall(r'(?:因此|所以|导致|因为|由于|之所以|缘由)', text)
    effect_markers = re.findall(r'(?:结果|后果|于是|便|就|这才|这才)', text)
    if len(cause_markers) > 0 and len(effect_markers) < len(cause_markers) * 0.5:
        issues.append(f"因果标记失衡: 原因词{len(cause_markers)}个, 结果词仅{len(effect_markers)}个")

    # 时间线矛盾检测
    time_conflicts = re.findall(r'(?:昨天|今天|明天|刚才|之前|之后|三天前|一周前).*?(?:突然|忽然|却|但)', text[:2000])
    if len(time_conflicts) > 3:
        issues.append(f"时间线可能矛盾: 前2000字内有{len(time_conflicts)}处时间转折")

    # 闪回标记缺失
    flashback_words = re.findall(r'(?:回忆|记得|当年|曾经|那时|往事)', text)
    if flashback_words and not re.search(r'(?:闪回|倒叙|回忆杀|---)', text):
        issues.append("检测到回忆内容但无明确闪回标记")

    severity = "ok" if not issues else ("warning" if len(issues) <= 1 else "fail")
    return DimensionResult(
        "D1", "逻辑一致性", severity == "ok", severity, issues,
        "检查事件因果和时间线自洽" if not issues else "建议人工复查因果链和时间线"
    )


# ── D2: 人物行为合理性 ──

def check_d2_character(text: str, canon: dict | None = None) -> DimensionResult:
    """D2: 人物行为合理性 — 动机匹配 + 压力反应 + 作者强推检测。

    规则检测:
      - 角色行为是否与 Canon 核心动机匹配
      - 压力下反应是否符合性格标签
      - "作者强行推动剧情" 的行为标记
    """
    issues = []
    chinese = _count_chinese(text)
    if chinese < 100:
        return DimensionResult("D2", "人物行为合理性", True, "ok", [], "文本太短")

    # 从 Canon 加载角色设定
    characters = (canon or {}).get("characters", [])
    char_names = [c.get("name", "") for c in characters if c.get("name")]

    # 检测 "作者强推" 标记: 角色突然做出不合理行为
    forced_markers = [
        r'(?:不知为何|莫名其妙|鬼使神差|不由自主|不知怎么)',
        r'(?:突然决定|一反常态|破天荒|完全变了)',
        r'(?:为了.*?只好|不得不|被迫|无奈)',
    ]
    forced_hits = sum(len(re.findall(p, text)) for p in forced_markers)
    if forced_hits > 3:
        issues.append(f"'作者强推'标记过多: {forced_hits}处 (不知为何/莫名其妙/被迫等)")

    # 检测角色性格矛盾 (简化: 如果 Canon 有性格标签, 检查是否矛盾)
    for char in characters:
        name = char.get("name", "")
        traits = char.get("personality", [])
        if name and traits:
            # 检查角色是否做出与性格矛盾的行为
            if "冷静" in traits or "理智" in traits:
                rage_hits = len(re.findall(f'{name}.*?(?:暴怒|狂怒|失控|疯狂|歇斯底里)', text))
                if rage_hits > 0:
                    issues.append(f"'{name}'设定为冷静型, 但出现{rage_hits}处暴怒/失控描写")
            if "善良" in traits or "温柔" in traits:
                cruel_hits = len(re.findall(f'{name}.*?(?:残忍|冷酷|无情|屠戮|虐杀)', text))
                if cruel_hits > 0:
                    issues.append(f"'{name}'设定为善良型, 但出现{cruel_hits}处残忍描写")

    severity = "ok" if not issues else ("warning" if len(issues) <= 1 else "fail")
    return DimensionResult(
        "D2", "人物行为合理性", severity == "ok", severity, issues,
        "角色行为符合设定" if not issues else "建议检查角色行为是否符合人设"
    )


# ── D3: 细节准确性 ──

def check_d3_detail(text: str, canon: dict | None = None) -> DimensionResult:
    """D3: 细节准确性 — 外貌/场景/数字前后一致。

    规则检测:
      - 数字一致性 (同一对象出现不同数字)
      - 重复描述矛盾 (同一角色多种外貌描写)
      - 场景描写矛盾
    """
    issues = []
    chinese = _count_chinese(text)
    if chinese < 100:
        return DimensionResult("D3", "细节准确性", True, "ok", [], "文本太短")

    # 数字一致性: 检测 "X[量词]" 出现多次但数值不同
    number_patterns = re.findall(r'(\d+(?:万|千|百|十)?)(?:个|名|位|只|条|把|柄|颗|块|层|阶|级|年|岁|米|里|公里)', text)
    if number_patterns:
        from collections import Counter
        num_counts = Counter(number_patterns)
        # 同一数字出现5次以上可能是设定, 不报告
        # 不同数字描述同一对象需要人工检查
        unique_nums = len(set(number_patterns))
        if unique_nums > 10 and len(number_patterns) > 20:
            issues.append(f"数字密度较高: {len(number_patterns)}个数字, {unique_nums}个不同值, 建议核对一致性")

    # 外貌描写矛盾: 同一角色多种眼睛/头发颜色
    appearance_patterns = [
        (r'(\w+?).*?(?:一双|眼[睛瞳]).*?([^\s，。]{1,4})色', "眼睛颜色"),
        (r'(\w+?).*?(?:一头|头发|长发|短发).*?([^\s，。]{1,4})色', "头发颜色"),
    ]
    for pat, label in appearance_patterns:
        matches = re.findall(pat, text)
        char_colors = {}
        for name, color in matches:
            if name in char_colors and char_colors[name] != color:
                issues.append(f"'{name}'的{label}前后不一致: '{char_colors[name]}' vs '{color}'")
            char_colors[name] = color

    severity = "ok" if not issues else ("warning" if len(issues) <= 1 else "fail")
    return DimensionResult(
        "D3", "细节准确性", severity == "ok", severity, issues,
        "细节描述一致" if not issues else "建议核对数字和外貌描写的一致性"
    )


# ── D4: 世界观一致性 ──

def check_d4_canon(text: str, canon: dict | None = None) -> DimensionResult:
    """D4: 世界观一致性 — 新规则冲突 + 废弃设定引用。

    规则检测:
      - Canon 设定冲突词检测
      - 死亡角色复活检测
      - 废弃能力/物品引用
    """
    issues = []
    chinese = _count_chinese(text)
    if chinese < 100:
        return DimensionResult("D4", "世界观一致性", True, "ok", [], "文本太短")

    if not canon:
        return DimensionResult("D4", "世界观一致性", True, "ok", [], "无Canon数据, 跳过")

    # 死亡角色复活检测
    dead_chars = [c.get("name", "") for c in canon.get("characters", [])
                  if c.get("status") == "dead" or c.get("lifecycle_status") == "dead"]
    for name in dead_chars:
        if name and name in text:
            # 检查是否是回忆/闪回, 还是实际出场
            context = re.findall(f'.{{0,20}}{name}.{{0,20}}', text)
            for ctx in context:
                if not re.search(r'(?:回忆|记得|当年|曾经|往事|墓|碑|遗|亡|死|牺牲', ctx):
                    issues.append(f"死亡角色 '{name}' 可能被引用: '...{ctx}...'")
                    break

    # 废弃设定检测
    deprecated_rules = canon.get("deprecated_rules", [])
    for rule in deprecated_rules:
        if isinstance(rule, str) and rule in text:
            issues.append(f"废弃设定被引用: '{rule}'")

    # 世界观规则冲突
    world_rules = canon.get("world_rules", [])
    if world_rules:
        # 简化: 检测 "不可能/不应该" 等否定词与规则冲突
        impossible_hits = re.findall(r'(?:不可能|不应该|怎能|怎么会|不可能发生)', text)
        if len(impossible_hits) > 5:
            issues.append(f"否定/不可能标记过多: {len(impossible_hits)}处, 可能与世界观冲突")

    severity = "ok" if not issues else ("warning" if len(issues) <= 1 else "fail")
    return DimensionResult(
        "D4", "世界观一致性", severity == "ok", severity, issues,
        "世界观一致" if not issues else "建议检查是否与Canon设定冲突"
    )


# ── D5: 叙事节奏 ──

def check_d5_pacing(text: str, canon: dict | None = None) -> DimensionResult:
    """D5: 叙事节奏 — 起承转合 + 水字数 + 对话比例。

    规则检测:
      - 节拍是否符合 "起-承-转-合" 或 "压抑-爆发-余韵"
      - 连续3段无剧情推进的 "水字数"
      - 对话与叙述比例是否失衡
    """
    issues = []
    chinese = _count_chinese(text)
    if chinese < 100:
        return DimensionResult("D5", "叙事节奏", True, "ok", [], "文本太短")

    # 对话比例
    dialogues = _extract_dialogues(text)
    dialogue_chars = sum(len(d) for d in dialogues)
    dialogue_ratio = dialogue_chars / max(chinese, 1)
    if dialogue_ratio > 0.7:
        issues.append(f"对话占比过高: {dialogue_ratio:.0%} (>70%可能缺少叙述)")
    elif dialogue_ratio < 0.1 and chinese > 1000:
        issues.append(f"对话占比过低: {dialogue_ratio:.0%} (<10%可能缺少互动)")

    # 水字数检测: 连续3段无剧情推进
    paragraphs = [p.strip() for p in text.split('\n') if p.strip() and len(p.strip()) > 20]
    flat_count = 0
    max_flat = 0
    plot_markers = r'(?:战斗|冲突|发现|决定|改变|离开|到达|遇到|得知|明白|意识到|开始|结束|失败|成功)'
    for para in paragraphs:
        if not re.search(plot_markers, para):
            flat_count += 1
            max_flat = max(max_flat, flat_count)
        else:
            flat_count = 0
    if max_flat >= 3:
        issues.append(f"连续{max_flat}段无剧情推进 (水字数风险)")

    # 节拍检测: 将文本分4段, 检查情绪起伏
    if chinese > 500:
        seg_size = len(text) // 4
        segments = [text[i*seg_size:(i+1)*seg_size] for i in range(4)]
        intensities = []
        for seg in segments:
            excl = len(re.findall(r'[！!]', seg))
            action = len(re.findall(r'(?:战斗|杀|轰|冲|爆发|怒|吼|震)', seg))
            intensities.append(excl + action)
        # 检查是否有起伏
        if max(intensities) == min(intensities) and max(intensities) == 0:
            issues.append("四段情绪强度全为零, 缺乏起伏")
        elif max(intensities) > 0 and min(intensities) == max(intensities):
            issues.append("四段情绪强度一致, 缺乏起承转合变化")

    severity = "ok" if not issues else ("warning" if len(issues) <= 1 else "fail")
    return DimensionResult(
        "D5", "叙事节奏", severity == "ok", severity, issues,
        "节奏正常" if not issues else "建议调整对话比例和段落节奏"
    )


# ── 汇总入口 ──

def run_five_dimension_check(text: str, canon: dict | None = None) -> FiveDimReport:
    """执行完整五维审查。

    Args:
        text: 章节文本
        canon: Canon 设定字典 (characters, world_rules, deprecated_rules)

    Returns:
        FiveDimReport 汇总报告
    """
    report = FiveDimReport()
    report.add(check_d1_logic(text, canon))
    report.add(check_d2_character(text, canon))
    report.add(check_d3_detail(text, canon))
    report.add(check_d4_canon(text, canon))
    report.add(check_d5_pacing(text, canon))

    # 汇总
    lines = [f"\n{'=' * 50}", "  五维审查报告 (D1-D5)", f"{'=' * 50}"]
    for dim in report.dimensions:
        icon = {"ok": "[OK]", "warning": "[WARN]", "fail": "[FAIL]"}[dim.severity]
        lines.append(f"  {dim.dimension} {dim.name}: {icon}")
        for issue in dim.issues:
            lines.append(f"       - {issue}")
        if dim.suggestion and dim.severity != "ok":
            lines.append(f"       > {dim.suggestion}")
    lines.append(f"\n  总计: {report.total_pass}/5 通过, {report.total_fail}/5 异常")
    lines.append(f"{'=' * 50}")
    report.summary = "\n".join(lines)

    return report
