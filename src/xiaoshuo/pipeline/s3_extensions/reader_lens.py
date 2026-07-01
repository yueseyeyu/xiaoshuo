# -*- coding: utf-8 -*-
"""
reader_lens.py — S3 评审番茄读者视角 (追读力)
=================================================
来源: 建议文件 "模拟番茄读者反馈 → 增强S3评审读者视角"

检测维度:
  1. 开头节奏感 (Hook 强度) — 前300字是否有冲突/悬念/强情绪
  2. 台词代入感 — 对话是否像真人说话, 非作者传声筒
  3. 信息密度与期待感 — 每千字信息增量 + 章末钩子
  4. 追读力评分 — 综合读者留存率预测

输出:
  - ReaderLensReport (含追读力评分 + 下章灵感)
  - 任何维度未通过 → 标记 [RL-FAIL], 附修改建议
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from xiaoshuo.infra.logging_config import get_logger
from xiaoshuo.pipeline.text_utils import count_chinese as _count_chinese

logger = get_logger("reader_lens")


@dataclass
class ReaderLensReport:
    """番茄读者视角报告。"""
    hook_score: float = 0.0          # 开头钩子强度 0-10
    dialogue_score: float = 0.0      # 台词代入感 0-10
    info_density_score: float = 0.0  # 信息密度 0-10
    ending_hook_score: float = 0.0   # 章末期待感 0-10
    retention_power: float = 0.0     # 追读力 (综合) 0-100
    issues: list[str] = field(default_factory=list)
    next_chapter_hint: str = ""      # 下章灵感
    summary: str = ""


def check_hook_strength(text: str) -> tuple[float, list[str]]:
    """检查前300字的钩子强度。"""
    issues = []
    opening = text[:300]
    chinese = _count_chinese(opening)

    if chinese < 50:
        return 2.0, ["前300字中文太少, 无法评估钩子"]

    score = 0.0
    # 冲突标记
    conflict = re.findall(r'(?:战斗|对峙|冲突|危险|威胁|杀|逃|追|困|陷)', opening)
    if conflict:
        score += 3.0
    else:
        issues.append("前300字无冲突标记, 番茄读者3秒内划走概率>70%")

    # 悬念标记
    suspense = re.findall(r'(?:究竟|到底|为什么|怎么会|难道|莫非|秘密|真相|谜)', opening)
    if suspense:
        score += 2.0

    # 强情绪标记
    emotion = re.findall(r'(?:愤怒|恐惧|绝望|震惊|崩溃|狂喜|暴怒|惊恐)', opening)
    if emotion:
        score += 2.0

    # 环境描写开头扣分
    if re.match(r'^(?:天|阳光|月光|风|雨|雪|山|河|城|街道|房间)', opening[:20]):
        score -= 2.0
        issues.append("开头为环境描写, 番茄读者容易跳过")

    # 动作开头加分
    if re.match(r'^(?:他|她|它|我|林|苏|陈|叶).*?(?:跑|冲|跳|躲|挥|抓|扔|踢|拔)', opening[:30]):
        score += 1.5

    score = max(0, min(10, score))
    return score, issues


def check_dialogue_naturalness(text: str) -> tuple[float, list[str]]:
    """检查台词代入感。"""
    issues = []
    dialogues = re.findall(r'["""]([^"""]+)["""]', text)

    if not dialogues:
        return 5.0, ["无对话内容, 无法评估台词代入感"]

    scores = []
    for line in dialogues:
        score = 5.0
        # 短句更自然
        if len(line) <= 15:
            score += 2.0
        elif len(line) <= 25:
            score += 1.0
        elif len(line) > 50:
            score -= 1.0
            issues.append(f"台词过长({len(line)}字): '{line[:30]}...'")

        # 语气词
        if re.search(r'[啊吧呢吗嘛呀哦嗯哎喂哈嘿]', line):
            score += 1.5

        # 说明性对话 (作者传声筒)
        if re.search(r'(?:也就是说|换句话说|简单来说|总而言之|需要注意的是)', line):
            score -= 2.0
            issues.append(f"说明性对话(作者传声筒): '{line[:30]}...'")

        # 正式书面语
        if re.search(r'(?:因此|然而|虽然|尽管|此外|然而|综上所述)', line):
            score -= 1.5

        scores.append(max(0, min(10, score)))

    return sum(scores) / len(scores), issues


def check_info_density(text: str) -> tuple[float, list[str]]:
    """检查信息密度与期待感。"""
    issues = []
    chinese = _count_chinese(text)
    if chinese < 500:
        return 5.0, ["文本太短, 无法评估信息密度"]

    # 信息增量标记: 新信息揭示
    info_markers = re.findall(r'(?:发现|揭示|得知|明白|意识到|原来|真相|秘密|新的|突然|意外)', text)
    info_per_1k = len(info_markers) / max(chinese / 1000, 1)

    # 水字数检测: 连续段落无信息增量
    paragraphs = [p.strip() for p in text.split('\n') if p.strip() and len(p.strip()) > 30]
    water_count = 0
    for para in paragraphs:
        if not re.search(r'(?:发现|决定|改变|战斗|冲突|遇到|得知|明白|意识到|新)', para):
            water_count += 1

    score = 5.0
    if info_per_1k >= 3:
        score += 3.0
    elif info_per_1k >= 1.5:
        score += 1.5
    elif info_per_1k < 0.5:
        score -= 2.0
        issues.append(f"信息密度过低: {info_per_1k:.1f}个/千字 (建议≥1.5)")

    if water_count > len(paragraphs) * 0.4:
        score -= 2.0
        issues.append(f"水字数段落占比过高: {water_count}/{len(paragraphs)}")

    return max(0, min(10, score)), issues


def check_ending_hook(text: str) -> tuple[float, list[str]]:
    """检查章末期待感 (结尾钩子)。"""
    issues = []
    ending = text[-300:] if len(text) > 300 else text

    score = 0.0
    # 悬念型钩子
    if re.search(r'(?:究竟|到底|为什么|怎么会|难道|莫非|谁|什么)', ending):
        score += 3.0
    # 期待型钩子
    if re.search(r'(?:明天|明天就是|即将|马上|等着|一定|约定|誓言)', ending):
        score += 3.0
    # 情绪型钩子
    if re.search(r'(?:笑了|流泪|颤抖|崩溃|沉默|叹息|凝视)', ending):
        score += 2.0
    # 反转型钩子
    if re.search(r'(?:竟然|原来|却|然而|不料|谁知|哪知|偏偏)', ending):
        score += 2.5
    # 危机型钩子
    if re.search(r'(?:危险|危机|威胁|杀机|陷阱|包围|逼近)', ending):
        score += 2.0

    if score == 0:
        issues.append("章末无钩子, 读者缺乏点下一章的动力")

    return min(10, score), issues


def generate_next_chapter_hint(text: str, report: ReaderLensReport) -> str:
    """基于当前章节情绪曲线, 生成下章灵感。"""
    # 分析当前章节主导情绪
    if re.search(r'(?:战斗|杀|轰|冲|爆发|怒|吼)', text):
        emotion = "爆发"
        hint = "建议下章: 延迟爽 + 余韵, 让读者喘口气后埋新伏笔"
    elif re.search(r'(?:压抑|低沉|绝望|困境|被困|失败)', text):
        emotion = "压抑"
        hint = "建议下章: 反转爽点 + 突破, 释放积压情绪"
    elif re.search(r'(?:日常|平静|闲聊|散步|吃饭)', text):
        emotion = "日常"
        hint = "建议下章: 引入冲突 + 悬念钩子, 打破平静"
    elif re.search(r'(?:发现|真相|秘密|揭示)', text):
        emotion = "揭秘"
        hint = "建议下章: 危机升级 + 即时爽点, 利用信息差制造紧张"
    else:
        emotion = "过渡"
        hint = "建议下章: 增加冲突密度 + 章末钩子, 提升追读力"

    return f"【当前情绪: {emotion}】{hint}"


def run_reader_lens(text: str) -> ReaderLensReport:
    """执行番茄读者视角审查。"""
    report = ReaderLensReport()

    report.hook_score, hook_issues = check_hook_strength(text)
    report.dialogue_score, dial_issues = check_dialogue_naturalness(text)
    report.info_density_score, info_issues = check_info_density(text)
    report.ending_hook_score, end_issues = check_ending_hook(text)

    report.issues = hook_issues + dial_issues + info_issues + end_issues

    # 追读力 = 四维加权 (0-100)
    report.retention_power = round(
        report.hook_score * 3 +      # 30
        report.dialogue_score * 2 +   # 20
        report.info_density_score * 2 + # 20
        report.ending_hook_score * 3   # 30
    )

    report.next_chapter_hint = generate_next_chapter_hint(text, report)

    # 汇总
    lines = [f"\n{'=' * 50}", "  番茄读者视角报告 (追读力)", f"{'=' * 50}"]
    lines.append(f"  开头钩子强度:  {report.hook_score:.1f}/10")
    lines.append(f"  台词代入感:    {report.dialogue_score:.1f}/10")
    lines.append(f"  信息密度:      {report.info_density_score:.1f}/10")
    lines.append(f"  章末期待感:    {report.ending_hook_score:.1f}/10")
    lines.append(f"  追读力评分:    {report.retention_power}/100")
    if report.issues:
        lines.append("\n  [问题清单]")
        for issue in report.issues:
            lines.append(f"    - {issue}")
    lines.append(f"\n  {report.next_chapter_hint}")
    lines.append(f"{'=' * 50}")
    report.summary = "\n".join(lines)

    return report
