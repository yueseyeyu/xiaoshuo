# -*- coding: utf-8 -*-
"""
rule_analyzer.py — 零 LLM 规则分析模块
========================================
v11: 25+ 指标体系 (规则统计 + 钩子分类 + 可读性 + 反套路 + 情绪价值)
所有正则模式从 patterns.py 导入 (SSOT)。
"""
from __future__ import annotations

import hashlib
import re

from xiaoshuo.pipeline.rhythm.patterns import (
    PLEASURE_FACE_SLAP, PLEASURE_LEVEL_UP, PLEASURE_CRUSH,
    PLEASURE_COMEBACK, PLEASURE_HIDDEN, PLEASURE_GENERAL,
    PLEASURE_BOND, PLEASURE_COGNITIVE, PLEASURE_SACRIFICE,
    PHYSIO_REACTION,
    PLEASURE_STRATEGY, PLEASURE_RESOURCE, PLEASURE_SOCIAL,
    PLEASURE_BACKFIRE, PLEASURE_TRAP_MASTER, PLEASURE_KNOWLEDGE_GAP,
    PLEASURE_HIDDEN_VALUE, PLEASURE_IDENTITY_REVEAL, PLEASURE_FORESHADOW_PAYOFF,
    PLEASURE_TIMING, PLEASURE_WEIGHTS, PLEASURE_SUBTYPE_NAMES,
    CONFLICT_KW_ALL,
    DIALOGUE_PAT, EXCLAM_PAT, NEGATIVE, CLIFFHANGER,
    ANTI_TROPE, EMOTION_HIGH, EMOTION_LOW, EMOTION_BURNOUT,
)
from xiaoshuo.pipeline.text_utils import split_paragraphs as _split_paragraphs


def rule_analyze(ch):
    """Zero-LLM chapter analysis v11. Returns dict with 25+ metrics.

    v11: +反套路信号 +情绪价值检测 +ch_hash章节级缓存
    """
    body = ch["raw_body"]
    wc = ch["wc"]

    # ── 章节级内容哈希 ──
    ch_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]

    # ── Basic metrics ──
    dialogue_chars = sum(len(m.group()) for m in DIALOGUE_PAT.finditer(body))
    dialogue_ratio = dialogue_chars / max(wc, 1)

    excl_count = len(EXCLAM_PAT.findall(body))
    excl_density = excl_count / max(wc, 1) * 100

    # ── Pleasure sub-types (18 subtypes) ──
    slap_count = len(PLEASURE_FACE_SLAP.findall(body))
    level_count = len(PLEASURE_LEVEL_UP.findall(body))
    crush_count = len(PLEASURE_CRUSH.findall(body))
    comeback_count = len(PLEASURE_COMEBACK.findall(body))
    hidden_count = len(PLEASURE_HIDDEN.findall(body))
    general_count = len(PLEASURE_GENERAL.findall(body))
    cognitive_count = len(PLEASURE_COGNITIVE.findall(body))
    sacrifice_count = len(PLEASURE_SACRIFICE.findall(body))
    physio_count = len(PHYSIO_REACTION.findall(body))
    strategy_count = len(PLEASURE_STRATEGY.findall(body))
    resource_count = len(PLEASURE_RESOURCE.findall(body))
    social_count = len(PLEASURE_SOCIAL.findall(body))
    backfire_count = len(PLEASURE_BACKFIRE.findall(body))
    trap_master_count = len(PLEASURE_TRAP_MASTER.findall(body))
    knowledge_gap_count = len(PLEASURE_KNOWLEDGE_GAP.findall(body))
    hidden_value_count = len(PLEASURE_HIDDEN_VALUE.findall(body))
    identity_reveal_count = len(PLEASURE_IDENTITY_REVEAL.findall(body))
    foreshadow_payoff_count = len(PLEASURE_FORESHADOW_PAYOFF.findall(body))

    # v5: 羁绊消歧 — 上下文30字共现约束
    bond_count = 0
    for m in PLEASURE_BOND.finditer(body):
        start = max(0, m.start() - 30)
        end = min(len(body), m.end() + 30)
        ctx = body[start:end]
        if re.search(r"你|我|他|她|眼中|心里|轻声|沉默|握住|凝视", ctx):
            bond_count += 1

    # ── 加权聚合 (CCMMW方法) ──
    w = PLEASURE_WEIGHTS
    weighted_pleasure = (
        slap_count * w["slap"] + level_count * w["level"] + crush_count * w["crush"] +
        comeback_count * w["comeback"] + hidden_count * w["hidden"] + general_count * w["general"] +
        bond_count * w["bond"] + cognitive_count * w["cognitive"] + sacrifice_count * w["sacrifice"] +
        physio_count * w["physio"] +
        strategy_count * w["strategy"] + resource_count * w["resource"] + social_count * w["social"] +
        backfire_count * w["backfire"] + trap_master_count * w["trap_master"] +
        knowledge_gap_count * w["knowledge_gap"] + hidden_value_count * w["hidden_value"] +
        identity_reveal_count * w["identity_reveal"] + foreshadow_payoff_count * w["foreshadow_payoff"]
    )
    total_pleasure = weighted_pleasure
    pos_density = total_pleasure / max(wc, 1) * 100

    # Dominant pleasure sub-type
    counts_map = {
        "打脸": slap_count, "突破": level_count, "碾压": crush_count,
        "绝地反击": comeback_count, "扮猪吃虎": hidden_count,
        "羁绊": bond_count, "认知突破": cognitive_count,
        "牺牲": sacrifice_count,
        "策略": strategy_count, "资源": resource_count, "社交": social_count,
        "反派反噬": backfire_count, "反陷阱": trap_master_count,
        "认知碾压": knowledge_gap_count, "隐藏价值": hidden_value_count,
        "身份反转": identity_reveal_count, "伏笔回收": foreshadow_payoff_count,
    }
    subtypes = list(counts_map.items())
    dominant_sub = max(subtypes, key=lambda x: x[1])

    # 爽点时序标签
    pleasure_timing = PLEASURE_TIMING.get(dominant_sub[0], "instant")
    if dominant_sub[1] == 0:
        for name, count in sorted(subtypes, key=lambda x: x[1], reverse=True):
            if count > 0:
                pleasure_timing = PLEASURE_TIMING.get(name, "instant")
                break

    # ── Negative emotion density ──
    neg_count = len(NEGATIVE.findall(body))
    neg_density = neg_count / max(wc, 1) * 100

    # ── 5+1类冲突合并 ──
    conflict_count = sum(len(kw.findall(body)) for kw in CONFLICT_KW_ALL)
    conflict_density = conflict_count / max(wc, 1) * 100

    # ── Cliffhanger hook density (per 1000 chars) ──
    hook_count = len(CLIFFHANGER.findall(body))
    hook_density = hook_count / max(wc/1000, 1)

    # ── Hook type classification (8类, 窗口 500字) ──
    ending = body[-500:] if len(body) > 500 else body
    ending_paras = _split_paragraphs(ending, len(ending))
    last_para = ending_paras[-1] if ending_paras else ending
    last2_para = ending_paras[-2] if len(ending_paras) >= 2 else ""

    hook_suspense = bool(re.search(r"竟然|居然|不可能|怎么可能|但[是那]|然而|只不过|不料|谁知[道]?|没想[到过]", ending[-300:]))
    hook_reversal_para = (len(last_para) < 30 and len(last2_para) > 80) if last2_para else False
    hook_reversal_sent = bool(re.search(r"([^。！？\n]{5,}。\s*)([^。！？\n]{2,15})$", ending[-400:]))
    hook_reversal = hook_reversal_para or hook_reversal_sent
    hook_emotion = bool(re.search(r"(从[来没]|再也[不没]|永远|终于|最后[一]?)[^。！？]{3,25}$", ending[-300:]))
    hook_info_dump = bool(re.search(r"(翻开|打开|看到|发现|显示|弹出|浮现|亮起|闪烁|跳[出动]|面板|提示|解锁)[^。！？]{3,25}$", ending[-300:]))
    hook_threat = bool(re.search(r"(危险|危机|威胁|杀[机意]|死亡|毁灭|不详|不[妙对]|糟糕|完[了蛋])[^。！？]{0,20}$", ending[-250:]))
    hook_question = bool(re.search(r"[？?][ \n]*$", ending[-200:]) or re.search(r"(难道|莫非|为[什]?么|怎么[会可])[^。！？]{3,30}$", ending[-250:]))
    hook_promise = bool(re.search(r"(一定|必将|必定|来日|改日|下次|等着|走着瞧|不[会能]放[过弃])[^。！？]{2,20}$", ending[-200:]))
    hook_system = bool(re.search(r"(叮[!！]|系统提示|任务完成|奖励|升级|进化|觉醒|解锁|新[的个]技能)", ending[-250:]))

    hook_type = "none"
    if hook_suspense:
        hook_type = "悬念式"
    elif hook_emotion:
        hook_type = "情绪炸弹"
    elif hook_reversal:
        hook_type = "反转式"
    elif hook_info_dump:
        hook_type = "信息投放"
    elif hook_threat:
        hook_type = "威胁式"
    elif hook_question:
        hook_type = "疑问式"
    elif hook_promise:
        hook_type = "承诺式"
    elif hook_system:
        hook_type = "系统提示"

    # ── Readability score (AlphaReadabilityChinese method) ──
    sentences = re.split(r'[。！？!?]', body)
    sentence_lengths = [len(s.strip()) for s in sentences if s.strip()]
    avg_sentence_len = sum(sentence_lengths) / max(len(sentence_lengths), 1)
    pure_text = body.replace("\n", "").replace(" ", "")
    unique_chars = len(set(pure_text))
    vocab_diversity = unique_chars / max(len(pure_text), 1)
    readability_score = round(
        max(0.0, min(1.0, (avg_sentence_len / 80) * 0.5 + (1 - vocab_diversity * 3) * 0.3 +
         (abs(avg_sentence_len - 35) / 50) * 0.2)), 3)

    # ── pleasure_intensity (v8: Platt Scaling) ──
    pleasure_raw = (
        pos_density * 2.0 +
        conflict_density * 1.5 +
        excl_density * 0.5 +
        hook_density * 0.5 +
        neg_density * 0.2 +
        physio_count * 2.0 / max(wc/100, 1)
    )
    pleasure_raw = pleasure_raw * 0.7
    pleasure_intensity = round(max(0, min(10, pleasure_raw)), 1)

    if pleasure_intensity >= 6:
        pleasure_type = "climax"
    elif pleasure_intensity >= 4:
        pleasure_type = "major"
    elif pleasure_intensity >= 2:
        pleasure_type = "minor"
    else:
        pleasure_type = "none"

    # ── Conflict level ──
    if conflict_density > 2.5:
        conflict_level = "high"
    elif conflict_density > 1.0:
        conflict_level = "medium"
    elif conflict_density > 0.3:
        conflict_level = "low"
    else:
        conflict_level = "none"

    # ── Emotion classification ──
    if pos_density > neg_density * 2:
        emotion = "爽快"
    elif conflict_density > 2 and neg_density > pos_density:
        emotion = "紧张"
    elif sacrifice_count >= 2 and bond_count >= 2:
        emotion = "悲壮"
    elif conflict_density > 1.5:
        emotion = "悲壮"
    elif comeback_count > slap_count:
        emotion = "悬疑"
    elif dialogue_ratio > 0.35:
        emotion = "日常"
    else:
        emotion = "日常"

    # ── Pace ──
    avg_para_len = wc / max(ch["para_count"], 1)
    if avg_para_len < 45 or (avg_para_len < 80 and excl_density > 0.5):
        pace = "fast"
    elif avg_para_len > 250:
        pace = "slow"
    else:
        pace = "medium"

    # ── 反套路信号检测 ──
    anti_trope_count = len(ANTI_TROPE.findall(body))
    is_anti_trope = anti_trope_count >= 1

    # ── 情绪价值检测 ──
    high_emotion_count = len(EMOTION_HIGH.findall(body))
    low_emotion_count = len(EMOTION_LOW.findall(body))
    burnout_count = len(EMOTION_BURNOUT.findall(body))
    emotion_burnout = high_emotion_count >= 2 and burnout_count >= 1
    emotion_valence = round(
        min(10, max(-10,
            (high_emotion_count * 3 + physio_count * 2) -
            (low_emotion_count * 2 + burnout_count * 4)
        )), 1)

    return {
        "ch_num": ch["num"],
        "ch_hash": ch_hash,
        "wc": wc,
        "para_count": ch["para_count"],
        "avg_para_len": int(avg_para_len),
        "dialogue_ratio": round(dialogue_ratio, 3),
        "excl_density": round(excl_density, 2),
        "pos_density": round(pos_density, 2),
        "neg_density": round(neg_density, 2),
        "conflict_density": round(conflict_density, 2),
        "hook_density": round(hook_density, 2),
        "slap_count": slap_count,
        "level_count": level_count,
        "crush_count": crush_count,
        "comeback_count": comeback_count,
        "hidden_count": hidden_count,
        "bond_count": bond_count,
        "cognitive_count": cognitive_count,
        "sacrifice_count": sacrifice_count,
        "physio_count": physio_count,
        "strategy_count": strategy_count,
        "resource_count": resource_count,
        "social_count": social_count,
        "backfire_count": backfire_count,
        "trap_master_count": trap_master_count,
        "knowledge_gap_count": knowledge_gap_count,
        "hidden_value_count": hidden_value_count,
        "identity_reveal_count": identity_reveal_count,
        "foreshadow_payoff_count": foreshadow_payoff_count,
        "dominant_sub": dominant_sub[0],
        "pleasure_type": pleasure_type,
        "pleasure_intensity": pleasure_intensity,
        "pleasure_level": "small",
        "pleasure_timing": pleasure_timing,
        "hook_type": hook_type,
        "readability": readability_score,
        "avg_sentence_len": round(avg_sentence_len, 1),
        "vocab_diversity": round(vocab_diversity, 3),
        "conflict": "true" if conflict_density > 0.3 else "false",
        "conflict_level": conflict_level,
        "emotion": emotion,
        "pace": pace,
        "slap_noise": (slap_count > 5 and pleasure_intensity < 3),
        "anti_trope": is_anti_trope,
        "anti_trope_count": anti_trope_count,
        "emotion_valence": emotion_valence,
        "emotion_burnout": emotion_burnout,
        "high_emotion_count": high_emotion_count,
        "burnout_count": burnout_count,
    }
