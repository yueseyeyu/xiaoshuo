# -*- coding: utf-8 -*-
"""
narrative_schedule_lens.py — S3 评审叙事调度检查
===================================================
来源: 建议文件 "从控制台借鉴角色叙事调度字段"

检查规则:
  NS1 主角在场检查   — 主角每章必须有至少 1 次出场或提及
  NS2 主要角色冷却   — 连续出场 ≤3 章后, 建议冷却 ≥2 章
  NS3 配角台词占比   — 单章台词量不得超过主角的 50%
  NS4 龙套限制       — 禁止有内心独白或视角转换
  NS5 生命周期一致性 — dead 不可行动/说话, unintroduced 不可被"老朋友"称呼
  NS6 休眠唤醒检查   — dormant 角色重新登场必须有唤醒事件
  NS7 关联角色同步   — 敌对关系同场需冲突, 亲密关系需解释缺席

设计原则:
  - 零 LLM 依赖: 全部规则/统计检测
  - 可选 novel_index: 有索引时做跨章检查, 无索引时做单章检查
  - 与 FiveDimReport 同构: ScheduleResult -> ScheduleReport
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from xiaoshuo.infra.logging_config import get_logger
from xiaoshuo.pipeline.text_utils import count_chinese as _count_chinese

logger = get_logger("narrative_schedule")


@dataclass
class ScheduleResult:
    """单条调度检查结果。"""
    rule: str           # NS1-NS7
    name: str
    passed: bool
    severity: str = "ok"  # ok / info / warning / fail
    issues: list[str] = field(default_factory=list)
    suggestion: str = ""


@dataclass
class ScheduleReport:
    """叙事调度汇总报告。"""
    checks: list[ScheduleResult] = field(default_factory=list)
    total_pass: int = 0
    total_fail: int = 0
    summary: str = ""

    def add(self, result: ScheduleResult):
        self.checks.append(result)
        if result.passed:
            self.total_pass += 1
        else:
            self.total_fail += 1


# ── 辅助函数 ──

def _extract_dialogues(text: str) -> list[dict]:
    """提取对话及其归属角色 (简化版: 匹配 "角色说：" 模式)。

    Returns:
        [{"speaker": str, "content": str, "length": int}]
    """
    dialogues = []
    # 模式 1: "XXX说道：" / "XXX道：" / "XXX说："
    patterns = [
        r'([\u4e00-\u9fff]{2,6})\s*(?:说道?|道|喊道?|叫道?|冷声道?|笑道?|怒道|沉声道?|低声道?|高声道?)\s*[""""]([^""""]+)["""]',
        r'([\u4e00-\u9fff]{2,6})\s*(?:说道?|道|喊道?|叫道?|冷声道?|笑道?|怒道|沉声道?|低声道?|高声道?)\s*[:：]\s*(.+?)(?:[。！？\n])',
    ]
    for pat in patterns:
        for m in re.finditer(pat, text):
            speaker = m.group(1).strip()
            content = m.group(2).strip()
            if speaker and content:
                dialogues.append({
                    "speaker": speaker,
                    "content": content,
                    "length": _count_chinese(content),
                })
    return dialogues


def _detect_pov_switch(text: str) -> list[str]:
    """检测视角转换标记。"""
    pov_markers = [
        r'(?:从.*?的角度来看|在.*?眼中|.*?心想|.*?暗想|.*?内心深处)',
        r'(?:视角转换|POV切换|---.*?视角)',
        r'(?: meanwhile |与此同时.*?那边)',
    ]
    hits = []
    for pat in pov_markers:
        hits.extend(re.findall(pat, text))
    return hits


def _detect_inner_monologue(text: str, char_name: str) -> bool:
    """检测角色是否有内心独白。"""
    # "XXX心想" / "XXX暗想" / "XXX内心" / "XXX觉得"
    patterns = [
        f'{char_name}.*?(?:心想|暗想|内心|觉得|暗忖|思忖|暗道)',
        f'(?:心想|暗想|内心|觉得|暗忖|思忖|暗道).*?{char_name}',
    ]
    for pat in patterns:
        if re.search(pat, text):
            return True
    return False


# ── NS1: 主角在场检查 ──

def check_ns1_protagonist_presence(
    text: str,
    character_schedule: list[dict] | None = None,
    protagonist_name: str = ""
) -> ScheduleResult:
    """NS1: 主角每章必须有至少 1 次出场或提及。

    检查逻辑:
      - 如果有 character_schedule, 从中找到 protagonist
      - 如果没有, 尝试从文本中检测主角名
      - 检查主角名是否在文本中出现
    """
    issues = []
    chinese = _count_chinese(text)
    if chinese < 100:
        return ScheduleResult("NS1", "主角在场检查", True, "ok", [], "文本太短")

    # 确定主角名
    protag_name = protagonist_name
    if character_schedule:
        for char in character_schedule:
            if char.get("narrative_weight") == "protagonist":
                protag_name = char.get("character_name", "")
                break

    if not protag_name:
        return ScheduleResult("NS1", "主角在场检查", True, "ok", [],
                              "未指定主角, 跳过")

    # 检查主角是否在文本中出现
    if protag_name not in text:
        # 检查是否有代词替代 (他/她/它)
        pronoun_count = len(re.findall(r'(?:他|她)', text[:500]))
        if pronoun_count < 2:
            issues.append(f"主角 '{protag_name}' 在本章未出现且无明显代词替代")

    severity = "ok" if not issues else "warning"
    return ScheduleResult(
        "NS1", "主角在场检查", severity == "ok", severity, issues,
        "主角每章出场" if not issues else "建议确保主角每章有出场或被提及"
    )


# ── NS2: 主要角色冷却 ──

def check_ns2_major_cooldown(
    text: str,
    character_schedule: list[dict] | None = None,
    ch_num: int = 0
) -> ScheduleResult:
    """NS2: 主要角色连续出场 ≤3 章后, 建议冷却 ≥2 章。

    检查逻辑:
      - 从 character_schedule 获取 major 角色的冷却状态
      - 检查是否在冷却期内出场
    """
    issues = []
    if not character_schedule:
        return ScheduleResult("NS2", "主要角色冷却", True, "ok", [], "无调度数据, 跳过")

    for char in character_schedule:
        if char.get("narrative_weight") != "major":
            continue
        name = char.get("character_name", "")
        cooldown = char.get("appearance_cooldown", 0)
        since = char.get("chapters_since_appearance", 0)
        last_app = char.get("last_appearance", 0)

        if cooldown > 0 and since < cooldown and name in text:
            issues.append(
                f"主要角色 '{name}' 冷却期未满: 建议 {cooldown} 章间隔, "
                f"当前仅 {since} 章 (最后出场 ch{last_app})"
            )

    severity = "ok" if not issues else "info"
    return ScheduleResult(
        "NS2", "主要角色冷却", severity == "ok", severity, issues,
        "主要角色冷却正常" if not issues else "建议给主要角色适当休息"
    )


# ── NS3: 配角台词占比 ──

def check_ns3_supporting_dialogue(
    text: str,
    character_schedule: list[dict] | None = None,
    protagonist_name: str = ""
) -> ScheduleResult:
    """NS3: 配角单章台词量不得超过主角的 50%。

    检查逻辑:
      - 提取所有对话及其归属角色
      - 统计主角和配角的台词量
      - 检查配角台词是否超过主角的 50%
    """
    issues = []
    chinese = _count_chinese(text)
    if chinese < 200:
        return ScheduleResult("NS3", "配角台词占比", True, "ok", [], "文本太短")

    dialogues = _extract_dialogues(text)
    if not dialogues:
        return ScheduleResult("NS3", "配角台词占比", True, "ok", [], "无对话, 跳过")

    # 统计各角色台词量
    from collections import defaultdict
    dialogue_chars = defaultdict(int)
    for d in dialogues:
        dialogue_chars[d["speaker"]] += d["length"]

    # 确定主角名
    protag_name = protagonist_name
    if character_schedule:
        for char in character_schedule:
            if char.get("narrative_weight") == "protagonist":
                protag_name = char.get("character_name", "")
                break

    # 获取配角名
    supporting_names = set()
    if character_schedule:
        for char in character_schedule:
            if char.get("narrative_weight") == "supporting":
                supporting_names.add(char.get("character_name", ""))

    protag_chars = dialogue_chars.get(protag_name, 0)
    if protag_chars == 0:
        # 主角没有台词, 可能是叙述为主
        return ScheduleResult("NS3", "配角台词占比", True, "ok", [],
                              "主角无台词, 跳过占比检查")

    # 检查配角台词占比
    for name, chars in dialogue_chars.items():
        if name == protag_name:
            continue
        # 如果有调度数据, 只检查标记为 supporting 的角色
        # 如果没有调度数据, 检查所有非主角角色
        if character_schedule and name not in supporting_names:
            continue
        ratio = chars / protag_chars
        if ratio > 0.5:
            issues.append(
                f"配角 '{name}' 台词量 {chars} 字, 为主角的 {ratio:.0%} (>50%)"
            )

    severity = "ok" if not issues else "warning"
    return ScheduleResult(
        "NS3", "配角台词占比", severity == "ok", severity, issues,
        "配角台词占比正常" if not issues else "建议控制配角台词量"
    )


# ── NS4: 龙套限制 ──

def check_ns4_cameo_restriction(
    text: str,
    character_schedule: list[dict] | None = None
) -> ScheduleResult:
    """NS4: 龙套 (cameo) 禁止有内心独白或视角转换。

    检查逻辑:
      - 从 character_schedule 获取 cameo 角色列表
      - 检查每个 cameo 角色是否有内心独白
      - 检查是否有围绕 cameo 的视角转换
    """
    issues = []
    if not character_schedule:
        return ScheduleResult("NS4", "龙套限制", True, "ok", [], "无调度数据, 跳过")

    cameo_names = [
        char.get("character_name", "")
        for char in character_schedule
        if char.get("narrative_weight") == "cameo"
    ]

    if not cameo_names:
        return ScheduleResult("NS4", "龙套限制", True, "ok", [], "无龙套角色, 跳过")

    for name in cameo_names:
        if not name:
            continue
        # 检查内心独白
        if _detect_inner_monologue(text, name):
            issues.append(f"龙套角色 '{name}' 有内心独白, 龙套不应有内心描写")

        # 检查视角转换
        pov_switches = _detect_pov_switch(text)
        for switch in pov_switches:
            if name in switch:
                issues.append(f"龙套角色 '{name}' 涉及视角转换, 龙套不应有独立视角")
                break

    severity = "ok" if not issues else "warning"
    return ScheduleResult(
        "NS4", "龙套限制", severity == "ok", severity, issues,
        "龙套角色使用规范" if not issues else "龙套不应有内心独白或视角转换"
    )


# ── NS5: 生命周期一致性 ──

def check_ns5_lifecycle_consistency(
    text: str,
    character_schedule: list[dict] | None = None,
    canon: dict | None = None
) -> ScheduleResult:
    """NS5: 生命周期一致性检查。

    检查规则:
      - lifecycle_status=dead 的角色: 禁止说话、行动
      - lifecycle_status=unintroduced 的角色: 禁止被"老朋友"口吻称呼
      - lifecycle_status=dormant 的角色: 重新登场需有唤醒事件
    """
    issues = []

    # 合并 character_schedule 和 canon 中的角色信息
    all_chars = []
    if character_schedule:
        all_chars.extend(character_schedule)
    if canon:
        for c in canon.get("characters", []):
            if isinstance(c, dict):
                all_chars.append(c)

    if not all_chars:
        return ScheduleResult("NS5", "生命周期一致性", True, "ok", [], "无角色数据, 跳过")

    for char in all_chars:
        name = char.get("character_name", "") or char.get("name", "")
        lifecycle = char.get("lifecycle_status", "") or char.get("status", "")

        if not name or not lifecycle:
            continue

        if name not in text:
            continue

        # 死亡角色检测
        if lifecycle == "dead":
            # 检查是否是回忆/闪回引用
            context_matches = re.findall(f'.{{0,30}}{re.escape(name)}.{{0,30}}', text)
            for ctx in context_matches:
                # 如果不是回忆/闪回/墓碑等语境, 则可能是实际出场
                if not re.search(r'(?:回忆|记得|当年|曾经|往事|墓|碑|遗|亡|死|牺牲|缅怀|怀念|思念)', ctx):
                    # 检查是否说话
                    if re.search(f'{re.escape(name)}.*?(?:说道?|道|喊道?|笑道?|怒道)', ctx):
                        issues.append(f"死亡角色 '{name}' 在本章有对话, 死亡角色不应说话")
                        break
                    # 检查是否行动
                    if re.search(f'{re.escape(name)}.*?(?:走|跑|跳|挥|打|抓|推|拉|站|坐)', ctx):
                        issues.append(f"死亡角色 '{name}' 在本章有行动描写, 死亡角色不应行动")
                        break

        # 未登场角色检测
        if lifecycle == "unintroduced":
            # 检查是否被"老朋友"口吻称呼
            familiar_patterns = [
                f'(?:老朋友|老搭档|老相识|旧友|故人).*?{re.escape(name)}',
                f'{re.escape(name)}.*?(?:老朋友|老搭档|老相识|旧友|故人)',
                f'(?:多年不见|好久不见|别来无恙).*?{re.escape(name)}',
            ]
            for pat in familiar_patterns:
                if re.search(pat, text):
                    issues.append(f"未登场角色 '{name}' 被'老朋友'口吻称呼, 可能设定矛盾")
                    break

        # 休眠角色检测
        if lifecycle == "dormant":
            # 检查是否有唤醒事件
            context_matches = re.findall(f'.{{0,50}}{re.escape(name)}.{{0,50}}', text)
            for ctx in context_matches:
                # 检查是否有唤醒/重新出现/苏醒等标记
                if not re.search(r'(?:唤醒|苏醒|重新|再次|回归|复出|出现|登场|醒来)', ctx):
                    issues.append(f"休眠角色 '{name}' 重新登场但无明确唤醒事件")
                    break

    severity = "ok" if not issues else ("warning" if len(issues) <= 2 else "fail")
    return ScheduleResult(
        "NS5", "生命周期一致性", severity == "ok", severity, issues,
        "生命周期一致" if not issues else "建议检查角色生命周期是否矛盾"
    )


# ── NS6: 休眠唤醒检查 ──

def check_ns6_dormant_awakening(
    text: str,
    character_schedule: list[dict] | None = None
) -> ScheduleResult:
    """NS6: 休眠角色重新登场必须有唤醒事件 (不能凭空出现)。

    检查逻辑:
      - 从 character_schedule 获取 dormant 角色
      - 如果 dormant 角色在文本中出现, 检查是否有唤醒事件
    """
    issues = []
    if not character_schedule:
        return ScheduleResult("NS6", "休眠唤醒检查", True, "ok", [], "无调度数据, 跳过")

    dormant_names = [
        char.get("character_name", "")
        for char in character_schedule
        if char.get("lifecycle_status") == "dormant"
    ]

    if not dormant_names:
        return ScheduleResult("NS6", "休眠唤醒检查", True, "ok", [], "无休眠角色, 跳过")

    awakening_markers = r'(?:唤醒|苏醒|重新|再次|回归|复出|出现|登场|醒来|解除封印|破封|出关)'

    for name in dormant_names:
        if not name:
            continue
        if name in text:
            # 检查是否有唤醒标记
            context = text[max(0, text.index(name) - 100):text.index(name) + 100]
            if not re.search(awakening_markers, context):
                issues.append(f"休眠角色 '{name}' 重新登场但无明确唤醒事件, 不能凭空出现")

    severity = "ok" if not issues else "warning"
    return ScheduleResult(
        "NS6", "休眠唤醒检查", severity == "ok", severity, issues,
        "休眠角色唤醒正常" if not issues else "休眠角色重新登场需有唤醒事件"
    )


# ── NS7: 关联角色同步 ──

def check_ns7_relationship_sync(
    text: str,
    character_schedule: list[dict] | None = None
) -> ScheduleResult:
    """NS7: 关联角色同步检查。

    检查规则:
      - 敌对关系: 两人同场出场却无冲突 → 需解释"和平共处"
      - 亲密关系: A 出场时 B 被合理忽略 → 需有"为何 B 不在场"的暗示
    """
    issues = []
    if not character_schedule:
        return ScheduleResult("NS7", "关联角色同步", True, "ok", [], "无调度数据, 跳过")

    # 收集角色和关系
    char_rels = {}
    present_names = []
    for char in character_schedule:
        name = char.get("character_name", "")
        if not name:
            continue
        rels = char.get("relationships", {})
        if isinstance(rels, str):
            try:
                import json
                rels = json.loads(rels)
            except (json.JSONDecodeError, TypeError):
                rels = {}
        char_rels[name] = rels
        if name in text:
            present_names.append(name)

    if len(present_names) < 2:
        return ScheduleResult("NS7", "关联角色同步", True, "ok", [], "出场角色不足, 跳过")

    # 检查敌对关系
    for name_a in present_names:
        rels_a = char_rels.get(name_a, {})
        for name_b, rel_type in rels_a.items():
            if name_b not in present_names:
                continue
            # 敌对关系
            if any(kw in str(rel_type) for kw in ["敌", "仇", "对立", "宿敌", "敌人"]):
                # 检查是否有冲突描写
                conflict_markers = r'(?:战斗|冲突|对峙|怒视|冷哼|拔剑|出手|攻击|杀意|敌意)'
                # 找到两人同时出现的段落
                for i in range(len(text)):
                    if text[i:i+len(name_a)] == name_a and name_b in text[i:i+500]:
                        context = text[i:i+500]
                        if not re.search(conflict_markers, context):
                            issues.append(
                                f"敌对关系 '{name_a}'-'{name_b}' 同场出场但无冲突描写, "
                                f"需解释'和平共处'原因"
                            )
                            break
                        break

            # 亲密关系
            if any(kw in str(rel_type) for kw in ["亲", "恋", "爱", "夫妻", "情侣", "兄弟", "姐妹"]):
                # A 出场时 B 不在场, 检查是否有解释
                if name_b not in present_names:
                    # 检查是否有"为何 B 不在场"的暗示
                    absence_markers = r'(?:不在|离开|去了|出差|外出|留守|看家|等候|独自)'
                    name_a_context = text[max(0, text.index(name_a) - 100):text.index(name_a) + 200]
                    if not re.search(absence_markers, name_a_context):
                        issues.append(
                            f"亲密关系 '{name_a}'-'{name_b}': {name_a} 出场但 {name_b} 不在场, "
                            f"需有'为何不在'的暗示"
                        )

    severity = "ok" if not issues else ("warning" if len(issues) <= 2 else "fail")
    return ScheduleResult(
        "NS7", "关联角色同步", severity == "ok", severity, issues,
        "关联角色同步正常" if not issues else "建议检查角色关系是否自洽"
    )


# ── 汇总入口 ──

def run_narrative_schedule_check(
    text: str,
    character_schedule: list[dict] | None = None,
    canon: dict | None = None,
    ch_num: int = 0,
    protagonist_name: str = ""
) -> ScheduleReport:
    """执行完整叙事调度检查。

    Args:
        text: 章节文本
        character_schedule: 角色调度列表 (从 NovelIndex.get_character_schedule() 获取)
        canon: Canon 设定字典 (可选, 补充角色信息)
        ch_num: 当前章节号
        protagonist_name: 主角名 (可选, 优先从 character_schedule 获取)

    Returns:
        ScheduleReport 汇总报告
    """
    report = ScheduleReport()
    report.add(check_ns1_protagonist_presence(text, character_schedule, protagonist_name))
    report.add(check_ns2_major_cooldown(text, character_schedule, ch_num))
    report.add(check_ns3_supporting_dialogue(text, character_schedule, protagonist_name))
    report.add(check_ns4_cameo_restriction(text, character_schedule))
    report.add(check_ns5_lifecycle_consistency(text, character_schedule, canon))
    report.add(check_ns6_dormant_awakening(text, character_schedule))
    report.add(check_ns7_relationship_sync(text, character_schedule))

    # 汇总
    lines = [f"\n{'=' * 50}", "  叙事调度检查报告 (NS1-NS7)", f"{'=' * 50}"]
    for check in report.checks:
        icon = {"ok": "[OK]", "info": "[INFO]", "warning": "[WARN]", "fail": "[FAIL]"}[check.severity]
        lines.append(f"  {check.rule} {check.name}: {icon}")
        for issue in check.issues:
            lines.append(f"       - {issue}")
        if check.suggestion and check.severity not in ("ok", "info"):
            lines.append(f"       > {check.suggestion}")
    lines.append(f"\n  总计: {report.total_pass}/7 通过, {report.total_fail}/7 异常")
    lines.append(f"{'=' * 50}")
    report.summary = "\n".join(lines)

    return report
