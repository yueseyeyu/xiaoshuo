# -*- coding: utf-8 -*-
"""
writing_craft_lens.py — S3 评审写作技法审查
=============================================
来源: 建议文件 "Chinese Novel Writer Skill 的写作指南融入 S3 评审"

检测维度:
  1. 开头技巧 (首章/首段) — 3秒法则/黄金三章/信息密度
  2. 十三种结尾钩子 — 悬念/期待/情绪/反转/共情等
  3. 人物塑造技法 — 动机行为匹配/弧光一致性/对话即人物/缺陷即魅力

设计原则:
  - 零 LLM 依赖: 全部规则/统计检测
  - 与 five_dimension_check 互补: D1-D5 查"对不对", 本模块查"好不好"
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from xiaoshuo.infra.logging_config import get_logger
from xiaoshuo.pipeline.text_utils import count_chinese as _count_chinese

logger = get_logger("writing_craft")


@dataclass
class CraftReport:
    """写作技法审查报告。"""
    opening_score: float = 0.0        # 开头技巧 0-10
    ending_hook_type: str = ""        # 检测到的钩子类型
    ending_hook_score: float = 0.0    # 结尾钩子 0-10
    character_score: float = 0.0      # 人物塑造 0-10
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    summary: str = ""


# ── 十三种结尾钩子类型 ──

HOOK_TYPES = {
    "悬念": r'(?:究竟|到底|为什么|怎么会|难道|莫非|谁|什么|答案|秘密)',
    "期待": r'(?:明天|即将|马上|等着|一定|约定|誓言|明天就是)',
    "情绪": r'(?:笑了|流泪|颤抖|崩溃|沉默|叹息|凝视|心碎|热血)',
    "反转": r'(?:竟然|原来|却|然而|不料|谁知|哪知|偏偏|谁知)',
    "共情": r'(?:守护|牺牲|为了|只为|不惜|拼尽|以命|舍身)',
    "危机": r'(?:危险|危机|威胁|杀机|陷阱|包围|逼近|来袭)',
    "登场": r'(?:出现|来了|到了|降临|登场|现身|走来)',
    "发现": r'(?:发现|找到|揭示|浮现|终于|知道|明白|意识到)',
    "约定": r'(?:约定|承诺|誓言|一定会|等着|说好了|不见不散)',
    "威胁": r'(?:警告|威胁|最后通牒|限你|否则|后果自负)',
    "离别": r'(?:离开|告别|再见|走了|消失|转身|远去)',
    "决意": r'(?:决定|决心|一定要|绝不|必须|誓要|无论如何)',
    "震撼": r'(?:震惊|不可思议|难以置信|怎么可能|怎么会|匪夷所思)',
}


def check_opening_technique(text: str) -> tuple[float, list[str], list[str]]:
    """检查开头技巧: 3秒法则 + 黄金三章 + 信息密度。"""
    issues = []
    suggestions = []
    opening = text[:500]
    chinese = _count_chinese(opening)

    if chinese < 50:
        return 2.0, ["开头文本太短"], []

    score = 5.0

    # 3秒法则: 前100字是否有冲突/悬念/强情绪
    first_100 = text[:100]
    if re.search(r'(?:战斗|对峙|冲突|危险|杀|逃|追|困|陷|究竟|到底)', first_100):
        score += 2.0
    else:
        issues.append("前100字无冲突/悬念 (违反3秒法则)")
        suggestions.append("建议: 开头直接切入冲突或悬念, 不要铺垫环境")

    # 信息密度: 首段每100字是否有1个信息增量
    info_markers = re.findall(r'(?:发现|揭示|得知|明白|意识到|原来|真相|秘密|新|突然|意外)', opening)
    info_per_100 = len(info_markers) / max(chinese / 100, 1)
    if info_per_100 >= 1:
        score += 1.5
    elif info_per_100 < 0.3:
        score -= 1.0
        issues.append(f"首段信息密度低: {info_per_100:.1f}个/百字")
        suggestions.append("建议: 每100字至少1个新信息, 避免设定堆砌")

    # 环境描写开头扣分
    if re.match(r'^(?:天|阳光|月光|风|雨|雪|山|河|城|街道|房间|空气中)', text[:10]):
        score -= 2.0
        issues.append("开头为环境描写")
        suggestions.append("建议: 从动作或对话开头, 环境信息融入叙事中")

    return max(0, min(10, score)), issues, suggestions


def check_ending_hook(text: str) -> tuple[str, float, list[str], list[str]]:
    """检测章末钩子类型并评分。"""
    issues = []
    suggestions = []
    ending = text[-300:] if len(text) > 300 else text

    detected_types = []
    total_score = 0.0

    for hook_type, pattern in HOOK_TYPES.items():
        if re.search(pattern, ending):
            detected_types.append(hook_type)
            # 不同钩子类型有不同的分数权重
            weights = {
                "悬念": 3.0, "期待": 3.0, "情绪": 2.5, "反转": 2.5,
                "共情": 2.0, "危机": 2.0, "发现": 2.0, "震撼": 2.0,
                "登场": 1.5, "约定": 1.5, "威胁": 1.5, "离别": 1.5, "决意": 1.5,
            }
            total_score += weights.get(hook_type, 1.0)

    if not detected_types:
        issues.append("章末无明确钩子类型")
        suggestions.append("建议: 使用以下一种钩子 — 悬念/期待/反转/危机/共情")
        return "无", 0.0, issues, suggestions

    # 多种钩子叠加有上限
    total_score = min(10, total_score)
    hook_str = " + ".join(detected_types)

    return hook_str, total_score, issues, suggestions


def check_character_craft(text: str, canon: dict | None = None) -> tuple[float, list[str], list[str]]:
    """检查人物塑造技法: 动机-行为匹配 + 弧光一致性 + 对话即人物 + 缺陷即魅力。"""
    issues = []
    suggestions = []
    chinese = _count_chinese(text)

    if chinese < 500:
        return 5.0, [], []

    score = 5.0
    dialogues = re.findall(r'["""]([^"""]+)["""]', text)

    # 对话即人物: 台词是否能区分角色身份
    if dialogues:
        short_lines = sum(1 for d in dialogues if len(d) <= 15)
        if short_lines / max(len(dialogues), 1) > 0.7:
            score += 1.0  # 短句多 = 更口语化
        else:
            issues.append("对话偏长, 可能缺乏角色辨识度")
            suggestions.append("建议: 不同角色的台词风格应有明显差异")

        # 去掉"XX说"能否认出是谁 (简化: 检查语气词多样性)
        interjections = re.findall(r'[啊吧呢吗嘛呀哦嗯哎喂哈嘿]', " ".join(dialogues))
        if len(interjections) < len(dialogues) * 0.2:
            score -= 0.5
            issues.append("对话缺少语气词, 可能不够口语化")

    # 缺陷即魅力: 主角是否有可共鸣的缺陷
    flaw_markers = re.findall(r'(?:失误|犯错|搞砸|失手|判断错误|后悔|愧疚|自责|犹豫|迟疑|弱点|软肋|心魔)', text)
    if flaw_markers:
        score += 1.5  # 有缺陷描写 = 更真实
    else:
        issues.append("未检测到主角缺陷/犹豫描写 (完美人设风险)")
        suggestions.append("建议: 给主角一个可共鸣的缺陷, 避免完美人设")

    # 弧光推进: 本章是否有微小的成长/变化标记
    growth_markers = re.findall(r'(?:突破|领悟|觉醒|改变|成长|明白|意识到|终于|第一次)', text)
    if growth_markers:
        score += 1.0
    else:
        issues.append("未检测到角色弧光推进标记")
        suggestions.append("建议: 每章至少一个微小的角色成长或变化")

    return max(0, min(10, score)), issues, suggestions


def run_writing_craft_lens(text: str, canon: dict | None = None) -> CraftReport:
    """执行写作技法审查。"""
    report = CraftReport()

    report.opening_score, open_issues, open_sugg = check_opening_technique(text)
    report.ending_hook_type, report.ending_hook_score, end_issues, end_sugg = check_ending_hook(text)
    report.character_score, char_issues, char_sugg = check_character_craft(text, canon)

    report.issues = open_issues + end_issues + char_issues
    report.suggestions = open_sugg + end_sugg + char_sugg

    # 汇总
    lines = [f"\n{'=' * 50}", "  写作技法审查报告 (Writing Craft Lens)", f"{'=' * 50}"]
    lines.append(f"  开头技巧:     {report.opening_score:.1f}/10")
    lines.append(f"  结尾钩子:     {report.ending_hook_score:.1f}/10 (类型: {report.ending_hook_type})")
    lines.append(f"  人物塑造:     {report.character_score:.1f}/10")
    if report.issues:
        lines.append("\n  [问题清单]")
        for issue in report.issues:
            lines.append(f"    - {issue}")
    if report.suggestions:
        lines.append("\n  [修改建议]")
        for sugg in report.suggestions:
            lines.append(f"    > {sugg}")
    lines.append(f"{'=' * 50}")
    report.summary = "\n".join(lines)

    return report
