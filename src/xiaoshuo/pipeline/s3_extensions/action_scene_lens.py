# -*- coding: utf-8 -*-
"""
action_scene_lens.py — S3 评审动作戏画面感检测
=================================================
来源: 建议文件 "动作戏三技巧 → 新增动作戏质量检测模块"

检测维度 (三维度量化"电影感"):
  1. 动词降维 — 概括性动词(打/杀) vs 具体动词(偏/拧/碾)
  2. 环境互动 — 招式威力的侧面烘托 (落叶搅粉/地板龟裂)
  3. 视线牵引 — 镜头切换流 (远景→中景→近景→特写→主观)

设计原则:
  - 零 LLM 依赖: 全部规则/统计检测
  - 仅在检测到战斗信号的段落中触发, 避免日常场景误报
  - 与 writing_craft_lens 互补: 后者查"技法", 本模块查"画面感"
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from xiaoshuo.infra.logging_config import get_logger
from xiaoshuo.pipeline.text_utils import count_chinese as _count_chinese

logger = get_logger("action_scene")


@dataclass
class ActionSceneReport:
    """动作戏画面感检测报告。"""
    has_action_scene: bool = False       # 是否检测到动作戏段落
    verb_ratio: float = 0.0             # 具体动词占比 (0-1, 越高越好)
    env_density: float = 0.0            # 环境互动密度 (每句环境描写数)
    shot_flow: list[str] = field(default_factory=list)  # 镜头序列
    has_full_flow: bool = False         # 是否有完整镜头流 (远→中→近/特写)
    monotony_score: float = 0.0         # 镜头单调度 (0=多样, 1=完全重复)
    overall_score: float = 0.0          # 综合评分 0-10
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    summary: str = ""


# ── 战斗段落识别 ──
# 只有包含这些信号的段落才触发动作戏检测
COMBAT_SIGNALS = re.compile(
    r"战斗|厮杀|搏杀|血战|激战|大战|对决|决斗|"
    r"杀意|杀气|杀机|出手|进攻|攻击|反击|偷袭|暗算|围杀|"
    r"拳头|掌风|剑气|刀光|灵力|法术|功法|"
    r"闪避|格挡|冲锋|突击|爆炸|碰撞"
)

# ── 1. 动词降维词表 ──
# 概括性动词 (HIGH_LEVEL): 读者无法形成画面
HIGH_LEVEL_VERBS = [
    "打", "杀", "躲", "闪", "攻", "防", "战", "斗",
    "身手敏捷", "惊天动地", "力大无穷", "快如闪电",
    "猛烈攻击", "疯狂输出", "全力一击", "拼命抵抗",
    "迅速反击", "强大力量", "不可思议",
]

# 具体动词 (LOW_LEVEL): 读者能"看到"动作
LOW_LEVEL_VERBS = [
    "偏", "拧", "扭", "转", "缩", "探", "扣", "抓",
    "碾", "压", "蹭", "刮", "擦", "撞", "弹", "震",
    "渗", "滑", "滴", "裂", "碎", "塌", "陷", "崩",
    "劈", "刺", "挑", "撩", "扫", "砸", "摔", "掷",
]

# ── 2. 环境互动信号 ──
ENVIRONMENT_SIGNALS = [
    re.compile(r'落叶.*(?:粉末|碎屑|飞舞)|粉末.*落叶'),
    re.compile(r'(?:地板|地面|石板).*(?:龟裂|裂开|碎裂|塌陷)'),
    re.compile(r'(?:碎石|碎片|瓦砾).*(?:刮|飞|溅|射)'),
    re.compile(r'(?:桌子|椅子|墙壁|柱子).*(?:碎|裂|塌|倒)'),
    re.compile(r'(?:空气|气流|气浪).*(?:震|颤|扭曲|撕裂)'),
    re.compile(r'(?:风声|呼啸|轰鸣|爆炸声).*(?:耳膜|耳鸣|震耳)'),
    re.compile(r'(?:血|汗水|泪水).*(?:滴|流|溅|飞洒)'),
    re.compile(r'(?:灰尘|烟尘|沙石).*(?:扬起|弥漫|飞散)'),
]

# ── 3. 视线牵引 (镜头类型) ──
SHOT_TYPES = {
    "远景": re.compile(r'(?:月黑风高|夜幕降临|天际|地平线|群山|树林|城池|荒野|天空|大漠)'),
    "中景": re.compile(r'(?:两条黑影|两人|交锋|对峙|追逐|穿梭|相撞|缠斗|并肩)'),
    "近景": re.compile(r'(?:额头|眼角|嘴角|手指|手腕|肩膀|胸口|腰间|脖颈)'),
    "特写": re.compile(r'(?:瞳孔|汗珠|血丝|青筋|颤抖|收缩|放大|紧绷|暴起)'),
    "主观": re.compile(r'(?:在他眼中|在他瞳孔|他看见|他注意到|他盯着|他只看到|映入眼帘)'),
}


def _extract_action_scenes(text: str) -> list[str]:
    """从文本中提取包含战斗信号的段落。"""
    paragraphs = re.split(r'\n+', text)
    action_paragraphs = []
    for para in paragraphs:
        para = para.strip()
        if len(para) < 20:
            continue
        if COMBAT_SIGNALS.search(para):
            action_paragraphs.append(para)
    return action_paragraphs


def _detect_shot_flow(shot_flow: list[str]) -> bool:
    """检测是否有完整的镜头流 (远→中→近/特写 或 包含主观视角)。"""
    if not shot_flow:
        return False
    # 检查是否有至少3种不同镜头类型
    unique_shots = set(shot_flow)
    if len(unique_shots) < 3:
        return False
    # 检查是否有"远景→中景→近景/特写"的递进趋势
    has_wide = "远景" in unique_shots
    has_mid = "中景" in unique_shots
    has_close = "近景" in unique_shots or "特写" in unique_shots
    has_subjective = "主观" in unique_shots
    # 远→中→近 或 任意3种+含主观
    return (has_wide and has_mid and has_close) or (len(unique_shots) >= 3 and has_subjective)


def _detect_monotony(shot_flow: list[str]) -> float:
    """检测镜头单调度。返回 0-1, 1=完全重复。"""
    if not shot_flow:
        return 0.0
    unique = len(set(shot_flow))
    total = len(shot_flow)
    if total <= 1:
        return 0.0
    # 连续相同镜头的比例
    repeats = sum(1 for i in range(1, len(shot_flow)) if shot_flow[i] == shot_flow[i-1])
    repeat_ratio = repeats / (total - 1) if total > 1 else 0.0
    # 单调度 = 重复率 * (1 - 多样性比)
    diversity_ratio = unique / total
    return round(repeat_ratio * (1 - diversity_ratio), 2)


def analyze_action_scene(text: str) -> ActionSceneReport:
    """分析文本中动作戏的画面感质量。

    Args:
        text: 正文文本 (单章或多章)

    Returns:
        ActionSceneReport 包含三维度评分和修改建议
    """
    report = ActionSceneReport()

    chinese = _count_chinese(text)
    if chinese < 100:
        report.summary = "文本太短, 无法分析动作戏"
        return report

    # 提取动作戏段落
    action_paragraphs = _extract_action_scenes(text)
    if not action_paragraphs:
        report.summary = "未检测到动作戏段落"
        return report

    report.has_action_scene = True
    scene_text = "\n".join(action_paragraphs)

    # 1. 动词降维评分
    high_level_count = sum(1 for v in HIGH_LEVEL_VERBS if v in scene_text)
    low_level_count = sum(1 for v in LOW_LEVEL_VERBS if v in scene_text)
    total_verbs = high_level_count + low_level_count
    report.verb_ratio = low_level_count / (total_verbs + 1)

    # 2. 环境互动评分
    env_matches = sum(1 for p in ENVIRONMENT_SIGNALS if p.search(scene_text))
    sentences = len(re.findall(r'[。！？]', scene_text))
    report.env_density = env_matches / max(sentences, 1)

    # 3. 视线牵引评分
    shot_sequence = []
    for shot_type, pattern in SHOT_TYPES.items():
        for m in pattern.finditer(scene_text):
            shot_sequence.append((m.start(), shot_type))
    shot_sequence.sort()
    report.shot_flow = [s[1] for s in shot_sequence]
    report.has_full_flow = _detect_shot_flow(report.shot_flow)
    report.monotony_score = _detect_monotony(report.shot_flow)

    # 综合评分 (0-10)
    score = 0.0
    score += min(report.verb_ratio * 40, 4.0)           # 动词降维 4分
    score += min(report.env_density * 100, 3.0)          # 环境互动 3分
    score += 2.0 if report.has_full_flow else 0.0        # 完整镜头流 2分
    score += max(0, 1.0 - report.monotony_score)         # 镜头多样性 1分
    report.overall_score = round(score, 1)

    # 生成问题和建议
    if report.verb_ratio < 0.5:
        report.issues.append(f"动词降维不足: 具体动词占比仅 {report.verb_ratio:.0%} (概括性动词 {high_level_count} vs 具体动词 {low_level_count})")
        report.suggestions.append(
            "建议: 将'躲过'改为'头猛地往左偏了三公分', "
            "将'打飞'改为'拳头砸中下巴, 骨头碎裂声混着惨叫, 整个人向后撞碎了三张桌子'"
        )

    if report.env_density < 0.15:
        report.issues.append(f"环境互动缺失: 每句环境描写仅 {report.env_density:.2f}")
        report.suggestions.append(
            "建议: 加入'落叶被搅成粉末'、'地板如蜘蛛网般龟裂'、'碎石刮过脸颊'等环境破坏描写"
        )

    if not report.has_full_flow:
        report.issues.append("视线牵引断裂: 镜头切换不完整, 缺乏电影感")
        report.suggestions.append(
            "建议: 按'远景→中景→近景→特写→主观'顺序切换镜头, "
            "如: '月黑风高, 树林里惊起飞鸟(远景)→两条黑影在林间穿梭(中景)"
            "→额头渗出冷汗(近景)→盯着对方喉咙的破绽(特写)→对方的剑在瞳孔中急速放大(主观)'"
        )

    if report.monotony_score > 0.5:
        report.issues.append(f"镜头单调: 重复度 {report.monotony_score:.0%}")
        report.suggestions.append("建议: 避免连续使用同一种镜头类型, 增加视角切换")

    # 生成摘要
    lines = [f"\n{'=' * 50}", "  动作戏画面感检测报告 (Action Scene Lens)", f"{'=' * 50}"]
    lines.append(f"  检测到动作戏段落: {'是' if report.has_action_scene else '否'}")
    if report.has_action_scene:
        lines.append(f"  动词降维:     具体动词占比 {report.verb_ratio:.0%}")
        lines.append(f"  环境互动:     密度 {report.env_density:.2f}/句")
        lines.append(f"  视线牵引:     {'完整' if report.has_full_flow else '断裂'} (镜头: {' → '.join(report.shot_flow[:8])})")
        lines.append(f"  镜头单调度:   {report.monotony_score:.0%}")
        lines.append(f"  综合评分:     {report.overall_score:.1f}/10")
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


if __name__ == "__main__":
    import sys
    from pathlib import Path

    if len(sys.argv) > 1:
        text_path = sys.argv[1]
        if Path(text_path).exists():
            text = Path(text_path).read_text(encoding="utf-8")
            report = analyze_action_scene(text)
            print(report.summary)
        else:
            print(f"文件不存在: {text_path}")
    else:
        print("用法: python -m xiaoshuo.pipeline.s3_extensions.action_scene_lens <file>")
