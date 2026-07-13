# -*- coding: utf-8 -*-
"""
simulation_engine.py — 世界推演模拟引擎
==========================================
v8.6: 混合推演引擎 — 规则引擎处理常规决策，LLM 处理关键决策。

推演流程（每章一轮）：
  1. 角色行动 → 生成 character_action 事件
  2. 势力决策 → 生成 faction_decision 事件
  3. 影响传播 → 状态变更
  4. 冲突检测 → 检测势力间冲突
  5. 自然演化 → 每章自动恢复/衰减

结果通过 SSE 流式推送给前端。
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

import yaml

from xiaoshuo.api.services import world_state_service as wss


# ── 事件模板 ──

CHARACTER_ACTIONS = [
    ("探索", "探索周边区域，寻找资源和情报"),
    ("训练", "进行能力训练，提升实力"),
    ("交涉", "与其他势力进行外交交涉"),
    ("休整", "就地休整，恢复状态"),
    ("侦察", "侦察敌对势力的动向"),
    ("突袭", "对敌对势力发动突袭"),
    ("防御", "加固防线，应对威胁"),
    ("结盟", "寻求与友好势力结盟"),
]

FACTION_DECISIONS = [
    ("resource_allocation", "调配资源应对当前局势"),
    ("personnel_redeployment", "重新部署人员到关键位置"),
    ("diplomatic_outreach", "向其他势力派出外交使者"),
    ("military_mobilization", "进行军事动员"),
    ("internal_purge", "清除内部不稳定因素"),
    ("technology_research", "投入资源进行技术研发"),
]

# 角色心情变化
MOOD_CHANGES = {
    "normal": ["confident", "weary", "fearful", "angry"],
    "confident": ["normal", "angry", "weary"],
    "weary": ["fearful", "normal"],
    "fearful": ["angry", "normal", "confident"],
    "angry": ["confident", "weary"],
}


def _clamp(val: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
    return max(min_val, min(max_val, val))


def _gen_event_id() -> str:
    return f"evt_{uuid.uuid4().hex[:8]}"


async def run_simulation(
    project_id: str,
    from_chapter: int,
    to_chapter: int,
) -> AsyncGenerator[str, None]:
    """运行世界推演，通过 SSE 流式输出事件。

    Args:
        project_id: 项目 ID
        from_chapter: 起始章节
        to_chapter: 结束章节

    Yields:
        SSE 格式的字符串: data: {...}\\n\\n
    """
    ws = wss.get_world_state(project_id)
    if ws is None:
        yield _sse({"error": f"项目 {project_id} 不存在"})
        return

    total_chapters = to_chapter - from_chapter
    if total_chapters <= 0:
        yield _sse({"error": "结束章节必须大于起始章节"})
        return

    # 推演开始
    yield _sse({
        "status": "started",
        "from_chapter": from_chapter,
        "to_chapter": to_chapter,
        "total_rounds": total_chapters,
    })

    faction_states = ws.get("factions_state", [])
    char_states = ws.get("characters_state", [])

    # v8.6: 追踪每章已触发的 LLM 决策，避免重复触发
    _faction_llm_triggered_this_chapter = False

    for chapter in range(from_chapter + 1, to_chapter + 1):
        round_num = chapter - from_chapter
        _faction_llm_triggered_this_chapter = False

        # ── 阶段 0: 势力级 LLM 关键决策 (v8.6 新增，每章最多一次) ──
        faction_trigger = _check_llm_trigger(
            char_state=None,
            faction_state=None,
            all_factions=faction_states,
        )
        if faction_trigger:
            llm_event = await _run_llm_decision(
                project_id, faction_trigger,
                char_state=None,
                faction_state=None,
                all_factions=faction_states,
                chapter=chapter,
            )
            if llm_event:
                llm_event["round"] = round_num
                for eff in llm_event.get("effects", []):
                    _apply_effect(eff, char_states, faction_states)
                wss.add_event(project_id, chapter, llm_event)
                yield _sse(llm_event)
                await _async_sleep(0.05)
                _faction_llm_triggered_this_chapter = True

        # ── 阶段 1: 角色行动 (v8.6: 规则权重选择 + LLM 关键决策) ──
        for char_state in char_states:
            char_name = char_state.get("name", "未知角色")

            # v8.6: 检查是否需要角色级 LLM 关键决策
            # (势力级决策已在阶段0处理，这里只检查角色专属触发)
            llm_trigger = None
            if not _faction_llm_triggered_this_chapter:
                llm_trigger = _check_llm_trigger(
                    char_state=char_state,
                    faction_state=None,
                    all_factions=faction_states,
                    faction_level_done=_faction_llm_triggered_this_chapter,
                )

            if llm_trigger:
                # 调用 LLM 进行关键决策
                llm_event = await _run_llm_decision(
                    project_id, llm_trigger,
                    char_state=char_state,
                    faction_state=None,
                    all_factions=faction_states,
                    chapter=chapter,
                )
                if llm_event:
                    llm_event["round"] = round_num
                    # 应用 LLM 决策的效果
                    for eff in llm_event.get("effects", []):
                        _apply_effect(eff, char_states, faction_states)
                    wss.add_event(project_id, chapter, llm_event)
                    yield _sse(llm_event)
                    await _async_sleep(0.05)
                    continue  # 跳过该角色的常规行动

            # v8.6: 使用规则权重选择行动 (替代纯随机)
            action, desc = _select_character_action(char_state, faction_states)

            # 根据角色状态影响
            health = char_state.get("health", 1.0)
            if health < 0.3:
                action, desc = "休整", "因伤势严重，被迫休整"
                health_change = 0.1
            else:
                health_change = random.uniform(-0.05, 0.03)

            char_state["health"] = _clamp(health + health_change)

            # 心情变化
            old_mood = char_state.get("mood", "normal")
            possible_moods = MOOD_CHANGES.get(old_mood, ["normal"])
            if random.random() < 0.3:
                char_state["mood"] = random.choice(possible_moods)

            event = {
                "id": _gen_event_id(),
                "chapter": chapter,
                "round": round_num,
                "type": "character_action",
                "actor": char_name,
                "description": f"{char_name}选择「{action}」：{desc}",
                "effects": [{
                    "target_type": "character",
                    "target_id": char_name,
                    "field": "health",
                    "delta": round(health_change, 4),
                    "reason": action,
                }],
            }

            wss.add_event(project_id, chapter, event)
            yield _sse(event)
            await _async_sleep(0.05)

        # ── 阶段 2: 势力决策 ──
        for fac_state in faction_states:
            fac_id = fac_state.get("id", "")
            fac_name = fac_state.get("name", "未知势力")
            decision_type, decision_desc = random.choice(FACTION_DECISIONS)

            # 根据势力状态调整决策影响
            stability = fac_state.get("stability", 0.5)
            morale = fac_state.get("morale", 0.5)
            treasury = fac_state.get("treasury", 0.5)
            threat = fac_state.get("threat_level", 0.3)

            effects = []

            if decision_type == "resource_allocation":
                delta = random.uniform(-0.05, 0.08)
                treasury = _clamp(treasury - 0.03)
                effects.append({"target_type": "faction", "target_id": fac_id, "field": "stability", "delta": round(delta, 4), "reason": decision_desc})
                fac_state["stability"] = _clamp(stability + delta)
                fac_state["treasury"] = treasury

            elif decision_type == "military_mobilization":
                morale_delta = random.uniform(0.02, 0.1)
                threat_delta = random.uniform(0.05, 0.15)
                effects.append({"target_type": "faction", "target_id": fac_id, "field": "morale", "delta": round(morale_delta, 4), "reason": "军事动员提振士气"})
                effects.append({"target_type": "faction", "target_id": fac_id, "field": "threat_level", "delta": round(threat_delta, 4), "reason": "军事行动增加外部威胁"})
                fac_state["morale"] = _clamp(morale + morale_delta)
                fac_state["threat_level"] = _clamp(threat + threat_delta)

            elif decision_type == "internal_purge":
                stab_delta = random.uniform(0.03, 0.1)
                morale_delta = random.uniform(-0.08, -0.02)
                effects.append({"target_type": "faction", "target_id": fac_id, "field": "stability", "delta": round(stab_delta, 4), "reason": "清除不稳定因素"})
                effects.append({"target_type": "faction", "target_id": fac_id, "field": "morale", "delta": round(morale_delta, 4), "reason": "内部清洗影响士气"})
                fac_state["stability"] = _clamp(stability + stab_delta)
                fac_state["morale"] = _clamp(morale + morale_delta)

            elif decision_type == "diplomatic_outreach":
                threat_delta = random.uniform(-0.1, -0.02)
                effects.append({"target_type": "faction", "target_id": fac_id, "field": "threat_level", "delta": round(threat_delta, 4), "reason": "外交斡旋降低威胁"})
                fac_state["threat_level"] = _clamp(threat + threat_delta)

            elif decision_type == "technology_research":
                treasury_delta = random.uniform(-0.1, -0.03)
                power_delta = random.choice([0, 0, 0, 1])
                effects.append({"target_type": "faction", "target_id": fac_id, "field": "treasury", "delta": round(treasury_delta, 4), "reason": "研发投入消耗财政"})
                if power_delta > 0:
                    effects.append({"target_type": "faction", "target_id": fac_id, "field": "power_level", "delta": power_delta, "reason": "技术突破提升实力"})
                    fac_state["power_level"] = fac_state.get("power_level", 5) + power_delta
                fac_state["treasury"] = _clamp(treasury + treasury_delta)

            else:  # personnel_redeployment
                stab_delta = random.uniform(-0.03, 0.05)
                effects.append({"target_type": "faction", "target_id": fac_id, "field": "stability", "delta": round(stab_delta, 4), "reason": decision_desc})
                fac_state["stability"] = _clamp(stability + stab_delta)

            event = {
                "id": _gen_event_id(),
                "chapter": chapter,
                "round": round_num,
                "type": "faction_decision",
                "actor": fac_id,
                "description": f"{fac_name}决定「{decision_desc}」",
                "effects": effects,
            }

            wss.add_event(project_id, chapter, event)
            yield _sse(event)
            await _async_sleep(0.05)

        # ── 阶段 3: 冲突检测 ──
        for i in range(len(faction_states)):
            for j in range(i + 1, len(faction_states)):
                a = faction_states[i]
                b = faction_states[j]
                a_threat = a.get("threat_level", 0.3)
                b_threat = b.get("threat_level", 0.3)
                a_power = a.get("power_level", 5)
                b_power = b.get("power_level", 5)

                if a_threat > 0.6 and b_threat > 0.6 and abs(a_power - b_power) <= 2:
                    # 冲突爆发
                    a_stab_loss = random.uniform(0.05, 0.15)
                    b_stab_loss = random.uniform(0.05, 0.15)
                    a["stability"] = _clamp(a.get("stability", 0.5) - a_stab_loss)
                    b["stability"] = _clamp(b.get("stability", 0.5) - b_stab_loss)

                    event = {
                        "id": _gen_event_id(),
                        "chapter": chapter,
                        "round": round_num,
                        "type": "conflict_detected",
                        "actor": f"{a.get('id', '')} vs {b.get('id', '')}",
                        "description": f"{a.get('name', '')}与{b.get('name', '')}爆发冲突！双方稳定度下降",
                        "effects": [
                            {"target_type": "faction", "target_id": a.get("id", ""), "field": "stability", "delta": round(-a_stab_loss, 4), "reason": "武装冲突"},
                            {"target_type": "faction", "target_id": b.get("id", ""), "field": "stability", "delta": round(-b_stab_loss, 4), "reason": "武装冲突"},
                        ],
                    }
                    wss.add_event(project_id, chapter, event)
                    yield _sse(event)
                    await _async_sleep(0.03)

        # ── 阶段 4: 自然演化 (v8.6 新增) ──
        _apply_natural_decay(faction_states, char_states)

        # ── 阶段 5: 保存本章快照 ──
        # 更新 world_state 中的 factions_state 和 characters_state
        ws["factions_state"] = faction_states
        ws["characters_state"] = char_states
        ws["chapter"] = chapter
        wss.update_world_state(project_id, {
            "chapter": chapter,
            "factions_state": faction_states,
            "characters_state": char_states,
        })
        wss.save_snapshot(project_id, chapter)

        yield _sse({
            "status": "round_complete",
            "chapter": chapter,
            "round": round_num,
            "total_rounds": total_chapters,
        })
        await _async_sleep(0.1)

    # ── 推演完成 ──
    yield _sse({
        "status": "complete",
        "from_chapter": from_chapter,
        "to_chapter": to_chapter,
    })


def _sse(data: dict[str, Any]) -> str:
    """将数据编码为 SSE 格式。"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _async_sleep(seconds: float):
    """异步休眠（避免阻塞事件循环）。"""
    await asyncio.sleep(seconds)


# ============================================================
# v8.6: 规则引擎 — 加载 YAML 推演规则
# ============================================================

_RULES_CACHE: dict[str, Any] = {}


def _apply_effect(effect: dict, char_states: list[dict], faction_states: list[dict]):
    """将一个效果应用到角色/势力状态上。"""
    target_type = effect.get("target_type", "")
    target_id = effect.get("target_id", "")
    field = effect.get("field", "")
    delta = effect.get("delta", 0)

    if not field or delta == 0:
        return

    pool = char_states if target_type == "character" else faction_states
    for entity in pool:
        eid = entity.get("id", entity.get("name", ""))
        if eid == target_id or entity.get("name") == target_id:
            old_val = entity.get(field, 0.5)
            if field in ("power_level",):
                entity[field] = old_val + delta
            else:
                entity[field] = _clamp(old_val + delta)
            break


def _apply_natural_decay(faction_states: list[dict], char_states: list[dict]):
    """v8.6: 每章自然演化 — 低威胁势力自然恢复，财政衰减，威胁消解，角色恢复。"""
    for fac in faction_states:
        # 稳定度和士气自然恢复（仅在低威胁时）
        if fac.get("threat_level", 0) < 0.5:
            fac["stability"] = _clamp(fac.get("stability", 0.5) + 0.02)
            fac["morale"] = _clamp(fac.get("morale", 0.5) + 0.02)
        # 财政自然衰减
        fac["treasury"] = _clamp(fac.get("treasury", 0.5) - 0.01)
        # 威胁自然消解
        if fac.get("threat_level", 0) > 0.3:
            fac["threat_level"] = _clamp(fac.get("threat_level", 0.3) - 0.01)

    for char in char_states:
        # 角色自然恢复
        if char.get("health", 1.0) < 1.0 and char.get("mood") != "combat":
            char["health"] = _clamp(char.get("health", 1.0) + 0.05)


def load_simulation_rules() -> dict[str, Any]:
    """加载推演规则 YAML 文件（带缓存）。"""
    if _RULES_CACHE:
        return _RULES_CACHE

    rules_path = Path(__file__).resolve().parents[4] / "assets" / "canon" / "simulation_rules.yaml"
    if not rules_path.exists():
        return {"rules": [], "character_action_weights": {}, "llm_decision_triggers": []}

    try:
        data = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
        _RULES_CACHE.update(data or {})
        return _RULES_CACHE
    except Exception as e:
        logging.getLogger("simulation_engine").warning("加载推演规则失败: %s", e)
        return {"rules": [], "character_action_weights": {}, "llm_decision_triggers": []}


def _select_character_action(char_state: dict, faction_states: list[dict]) -> tuple[str, str]:
    """根据角色状态和规则权重选择行动（替代纯随机）。"""
    rules_data = load_simulation_rules()
    weights = rules_data.get("character_action_weights", {})

    if not weights:
        return random.choice(CHARACTER_ACTIONS)

    # 计算每个行动的权重
    char_mood = char_state.get("mood", "normal")
    char_health = char_state.get("health", 1.0)
    fac_id = char_state.get("faction_id", "")
    faction = next((f for f in faction_states if f.get("id") == fac_id), None)

    action_pool: list[tuple[str, str, float]] = []
    for action_name, desc in CHARACTER_ACTIONS:
        w = weights.get(action_name, {})
        weight = w.get("base_weight", 10)

        # 应用修正器
        for mod in w.get("modifiers", []):
            cond = mod.get("condition", "")
            mult = mod.get("multiplier", 1.0)
            # 简化条件判断
            if "mood == 'confident'" in cond and char_mood == "confident":
                weight *= mult
            elif "mood == 'fearful'" in cond and char_mood == "fearful":
                weight *= mult
            elif "mood == 'angry'" in cond and char_mood == "angry":
                weight *= mult
            elif "mood == 'weary'" in cond and char_mood == "weary":
                weight *= mult
            elif "health > 0.7" in cond and char_health > 0.7:
                weight *= mult
            elif "health < 0.5" in cond and char_health < 0.5:
                weight *= mult
            elif "health < 0.4" in cond and char_health < 0.4:
                weight *= mult
            elif "threat_level > 0.6" in cond and faction and faction.get("threat_level", 0) > 0.6:
                weight *= mult
            elif "threat_level > 0.5" in cond and faction and faction.get("threat_level", 0) > 0.5:
                weight *= mult
            elif "threat_level > 0.7" in cond and faction and faction.get("threat_level", 0) > 0.7:
                weight *= mult
            elif "stability < 0.4" in cond and faction and faction.get("stability", 1) < 0.4:
                weight *= mult

        action_pool.append((action_name, desc, max(weight, 0.1)))

    # 加权随机选择
    total = sum(w for _, _, w in action_pool)
    r = random.uniform(0, total)
    cumulative = 0.0
    for action_name, desc, w in action_pool:
        cumulative += w
        if r <= cumulative:
            return (action_name, desc)

    return action_pool[-1][:2]


def _check_llm_trigger(
    char_state: dict | None,
    faction_state: dict | None,
    all_factions: list[dict],
    faction_level_done: bool = False,
) -> Optional[dict]:
    """检查是否触发 LLM 关键决策。

    Args:
        char_state: 角色状态（None 表示势力级检查）
        faction_state: 势力状态
        all_factions: 所有势力状态
        faction_level_done: 势力级决策是否已触发（避免角色循环中重复触发）

    Returns:
        触发的决策配置 dict，或 None 表示不触发
    """
    rules_data = load_simulation_rules()
    triggers = rules_data.get("llm_decision_triggers", [])

    for trigger in triggers:
        cond = trigger.get("condition", "")

        # 势力级触发器（不依赖 char_state）
        is_faction_trigger = "faction_a." in cond or "faction.stability" in cond

        # 如果势力级决策已处理，跳过势力级触发器
        if is_faction_trigger and faction_level_done:
            continue

        # 势力级触发器在角色循环中不再重复检查
        if is_faction_trigger and char_state is not None:
            continue

        # 检查势力开战决策
        if "faction_a.threat_level > 0.6" in cond and len(all_factions) >= 2:
            high_threat = [f for f in all_factions if f.get("threat_level", 0) > 0.6]
            if len(high_threat) >= 2:
                return trigger

        # 检查角色叛逃决策
        if "character.faction.morale < 0.3" in cond and char_state:
            fac_id = char_state.get("faction_id", "")
            faction = next((f for f in all_factions if f.get("id") == fac_id), None)
            if (faction and faction.get("morale", 1) < 0.3
                    and char_state.get("mood") == "angry"):
                return trigger

        # 检查权力真空决策
        if "faction.stability < 0.2" in cond and faction_state:
            if faction_state.get("stability", 1) < 0.2:
                return trigger

        # 检查关键角色生死
        if "character.health < 0.2" in cond and char_state:
            if (char_state.get("health", 1) < 0.2
                    and char_state.get("role", "") in ("主角", "导师")):
                return trigger

    return None


async def _run_llm_decision(
    project_id: str,
    trigger: dict,
    char_state: dict | None,
    faction_state: dict | None,
    all_factions: list[dict],
    chapter: int,
) -> dict | None:
    """调用 LLM 进行关键决策推演。

    Returns:
        结构化事件 dict，或 None 表示 LLM 不可用/失败
    """
    try:
        from xiaoshuo.agents.model_orchestrator import get_orchestrator
        orch = get_orchestrator()
    except Exception:
        return None

    trigger_name = trigger.get("name", "未知决策")
    template = trigger.get("prompt_template", "")
    desc = trigger.get("description", "")

    # 构建上下文
    context_parts = [f"决策类型: {trigger_name}", f"描述: {desc}"]

    if faction_state:
        context_parts.append(
            f"势力状态: {faction_state.get('name', '')} "
            f"(稳定{faction_state.get('stability', 0.5):.0%} "
            f"士气{faction_state.get('morale', 0.5):.0%} "
            f"威胁{faction_state.get('threat_level', 0.3):.0%})"
        )

    if char_state:
        context_parts.append(
            f"角色状态: {char_state.get('name', '')} "
            f"(HP{char_state.get('health', 1.0):.0%} "
            f"心情{char_state.get('mood', 'normal')})"
        )

    # 势力间关系摘要
    if len(all_factions) >= 2:
        fac_summary = "; ".join(
            f"{f.get('name', '')}(威胁{f.get('threat_level', 0):.0%})"
            for f in all_factions[:4]
        )
        context_parts.append(f"所有势力: {fac_summary}")

    sys_prompt = f"""你是世界推演引擎中的决策Agent。当前需要做一个关键决策：

{chr(10).join(context_parts)}

请以JSON格式输出决策结果：
{{
  "decision": "决策内容简述",
  "reasoning": "决策理由 (50字以内)",
  "action_type": "character_action 或 faction_decision 或 conflict_detected",
  "effects": [
    {{"target_type": "faction 或 character", "target_id": "ID", "field": "字段名", "delta": 数值, "reason": "原因"}}
  ]
}}

注意: delta范围 -0.3 到 +0.3。只输出JSON，不要额外文字。"""

    user_prompt = f"请为第{chapter}章的「{trigger_name}」做决策。"

    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        result = orch.chat_with_trace(
            "main_model", messages,
            caller="simulation_engine.llm_decision",
            max_tokens=800, temperature=0.6, timeout=60,
        )
    except Exception:
        return None

    if "error" in result:
        return None

    raw = result.get("content", "")
    json_str = raw
    if "```json" in raw:
        json_str = raw.split("```json")[1].split("```")[0]
    elif "```" in raw:
        json_str = raw.split("```")[1].split("```")[0]

    try:
        decision = json.loads(json_str.strip())
        # 构造事件
        actor = ""
        if char_state:
            actor = char_state.get("name", "")
        elif faction_state:
            actor = faction_state.get("id", "")

        return {
            "id": _gen_event_id(),
            "chapter": chapter,
            "round": 0,
            "type": decision.get("action_type", "faction_decision"),
            "actor": actor,
            "description": f"[LLM决策] {decision.get('decision', trigger_name)}",
            "effects": decision.get("effects", []),
            "llm_generated": True,
        }
    except (json.JSONDecodeError, KeyError):
        return None
