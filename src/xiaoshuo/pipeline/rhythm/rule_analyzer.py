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
    PLEASURE_GENRE_APOCALYPSE,
    CONFLICT_KW_ALL,
    DIALOGUE_PAT, EXCLAM_PAT, NEGATIVE, CLIFFHANGER,
    ANTI_TROPE, EMOTION_HIGH, EMOTION_LOW, EMOTION_BURNOUT,
    OBSTACLE_KW_ALL, OBSTACLE_TYPE_NAMES,
    FATE_SIGNALS,
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

    # ── v3: 慢热生存流隐式爽点检测 ──
    # 末世生存文(末日蟑螂/全球进化)的爽点是隐性的: 活下来=爽, 获得物资=爽
    # 当前正则只检测显性爽点关键词，对这类文系统性低估
    # 解决: 检测生存成就信号，作为 implicit_pleasure 补充到 weighted_pleasure
    w = PLEASURE_WEIGHTS
    # v11: 题材专属爽点正则从 patterns.py 导入 (SSOT)
    # 未来扩展其他类型时，在 patterns.py 添加 PLEASURE_GENRE_<TYPE> 并在此条件加载
    survival_gain_count = len(PLEASURE_GENRE_APOCALYPSE.findall(body))
    # 隐式爽点权重: 约为 strategy 的 60% (不让隐式爽点压过显式爽点)
    implicit_pleasure = survival_gain_count * w.get("strategy", 0.108) * 0.6

    # ── 加权聚合 (CCMMW方法 + v3隐式爽点) ──
    weighted_pleasure = (
        slap_count * w["slap"] + level_count * w["level"] + crush_count * w["crush"] +
        comeback_count * w["comeback"] + hidden_count * w["hidden"] + general_count * w["general"] +
        bond_count * w["bond"] + cognitive_count * w["cognitive"] + sacrifice_count * w["sacrifice"] +
        physio_count * w["physio"] +
        strategy_count * w["strategy"] + resource_count * w["resource"] + social_count * w["social"] +
        backfire_count * w["backfire"] + trap_master_count * w["trap_master"] +
        knowledge_gap_count * w["knowledge_gap"] + hidden_value_count * w["hidden_value"] +
        identity_reveal_count * w["identity_reveal"] + foreshadow_payoff_count * w["foreshadow_payoff"] +
        implicit_pleasure  # v3: 慢热生存流隐式爽点
    )
    total_pleasure = weighted_pleasure
    # v12: BM25风格归一化 + 次线性TF缩放 (来源: Doubao建议, IR领域30年验证)
    # 替代简单线性 total_pleasure/wc*100，解决:
    #   (1) 长章节被过度惩罚 (字数多→密度被稀释)
    #   (2) 爽点数量边际递减 (10个爽点 ≠ 5个爽点的2倍爽感)
    # 设计约束: 保持与旧公式相同的量级(0.01-0.5)，避免下游pleasure_raw系数失效
    import math as _bm25
    _AVG_CHAPTER_WC = 2500  # 网文章节平均字数 (可从语料统计更新)
    _B = 0.75  # BM25长度惩罚强度
    if total_pleasure > 0:
        # 次线性TF: tf>=1时用1+log(tf)实现边际递减, tf<1时不缩放(避免低爽点章被放大)
        if total_pleasure >= 1.0:
            tf_scaled = 1 + _bm25.log(total_pleasure)
        else:
            tf_scaled = total_pleasure
        # BM25长度归一化: 1/(1-b+b*wc/avg) 替代 1/wc
        # wc=avg时: norm=1 (无变化), wc=2*avg时: norm=0.57 (比旧公式1/2=0.5更温和)
        length_norm = 1.0 / (1 - _B + _B * wc / _AVG_CHAPTER_WC)
        pos_density = tf_scaled * length_norm / _AVG_CHAPTER_WC * 100
    else:
        pos_density = 0.0

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

    # ── Readability score (v2: calibrated formula) ──
    # v1 issues: vocab_diversity*3 coefficient uncalibrated, /80 and /35 magic numbers.
    # v2: use sigmoid-based normalization with empirically calibrated midpoints.
    #     Chinese web novels: avg_sentence 15-60 chars, vocab_diversity 0.15-0.45.
    #     Optimal readability ~0.5-0.7 for commercial fiction.
    sentences = re.split(r'[。！？!?]', body)
    sentence_lengths = [len(s.strip()) for s in sentences if s.strip()]
    avg_sentence_len = sum(sentence_lengths) / max(len(sentence_lengths), 1)
    pure_text = body.replace("\n", "").replace(" ", "")
    unique_chars = len(set(pure_text))
    vocab_diversity = unique_chars / max(len(pure_text), 1)
    # Sigmoid: maps sentence length to 0-1, peak at 30 chars (ideal for web novels)
    import math as _math
    sent_component = 1.0 / (1.0 + _math.exp(-0.08 * (avg_sentence_len - 30)))
    # Vocab diversity: 0.3 is ideal (balanced repetition), deviations reduce readability
    vocab_component = 1.0 - abs(vocab_diversity - 0.30) * 2.5
    vocab_component = max(0.0, min(1.0, vocab_component))
    # Sentence length variance: low variance = monotonous, too high = chaotic
    if len(sentence_lengths) > 3:
        sl_std = _math.sqrt(sum((l - avg_sentence_len) ** 2 for l in sentence_lengths) / len(sentence_lengths))
        variance_component = 1.0 - min(1.0, abs(sl_std - 15) / 30)  # ideal std ~15
    else:
        variance_component = 0.5
    readability_score = round(
        max(0.0, min(1.0,
            sent_component * 0.40 +
            vocab_component * 0.35 +
            variance_component * 0.25
        )), 3)

    # ── pleasure_intensity (v10: 放宽压缩+情绪极性校验) ──
    # v8: *0.7 压缩太狠, 导致10本书 intensity 全部 1.0-2.4, 几乎无章能到"爽"阈值
    # v9: *0.9 放宽 + 生存成就额外加分
    # v10: 两项优化 —
    #   (1) ×0.9→×1.5 放宽压缩，让高潮章能到5-7分
    #   (2) 情绪极性校验: neg_density>1.5时×0.7，避免悲壮/惨烈场景误判为高爽
    pleasure_raw = (
        pos_density * 2.0 +
        conflict_density * 1.5 +
        excl_density * 0.5 +
        hook_density * 0.5 +
        neg_density * 0.2 +
        physio_count * 2.0 / max(wc/100, 1) +
        survival_gain_count * 0.3  # v9: 生存成就贡献
    )
    pleasure_raw = pleasure_raw * 1.5  # v10: 0.9→1.5 放宽压缩

    # v11: 情绪极性校验 — V维度连续衰减替代二元阈值
    # v10问题: neg_density>1.5时×0.7是断崖式降权，且只看负面不看正面
    # v11改进: 用V= pos_density - neg_density (效价平衡) 连续衰减
    #   V > 0 (正面为主): 不降权
    #   V = 0 (正负平衡，如"压抑→爆发"铺垫): 轻微降权
    #   V < 0 (纯负面，如惨烈/悲壮): 按比例降权，最低×0.3
    # 参考VAD模型Valence维度 (vad_analyzer.py), 但只用V避免A维度循环
    valence = pos_density - neg_density
    if valence < 0:
        penalty = max(0.3, 1.0 + valence * 0.15)
        pleasure_raw *= penalty
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

    # ── v2: 6类阻碍检测 (与18爽点对偶) ──
    obstacle_counts = {}
    for i, (cn_name, en_key) in enumerate(OBSTACLE_TYPE_NAMES):
        obstacle_counts[en_key] = len(OBSTACLE_KW_ALL[i].findall(body))
    total_obstacles = sum(obstacle_counts.values())
    obstacle_density = total_obstacles / max(wc, 1) * 100
    # 主导阻碍类型
    if total_obstacles > 0:
        dominant_obstacle = max(obstacle_counts.items(), key=lambda x: x[1])
        dominant_obstacle_name = next(
            (cn for cn, en in OBSTACLE_TYPE_NAMES if en == dominant_obstacle[0]),
            "无"
        )
    else:
        dominant_obstacle_name = "无"

    # ── v2: 命运变化评分 (量化"每章是否推动主角命运轨迹") ──
    fate_signals_found = {}
    for signal_name, signal_pat in FATE_SIGNALS:
        fate_signals_found[signal_name] = len(signal_pat.findall(body))
    total_fate_signals = sum(fate_signals_found.values())
    # 评分: 0-100, >70=强推动, <30=日常水文
    if wc > 0:
        fate_raw = total_fate_signals / (wc / 1000) * 15
    else:
        fate_raw = 0
    fate_change_score = round(min(100, max(0, fate_raw)), 1)
    if fate_change_score >= 70:
        fate_change_level = "strong"   # 强推动
    elif fate_change_score >= 40:
        fate_change_level = "moderate"  # 中等推动
    elif fate_change_score >= 20:
        fate_change_level = "weak"      # 弱推动
    else:
        fate_change_level = "stagnant"  # 剧情停滞 (水文风险)

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
        # v2: 阻碍检测
        "obstacle_enemy": obstacle_counts.get("enemy", 0),
        "obstacle_rule": obstacle_counts.get("rule", 0),
        "obstacle_resource": obstacle_counts.get("resource", 0),
        "obstacle_identity": obstacle_counts.get("identity", 0),
        "obstacle_time": obstacle_counts.get("time", 0),
        "obstacle_inner": obstacle_counts.get("inner", 0),
        "obstacle_total": total_obstacles,
        "obstacle_density": round(obstacle_density, 2),
        "dominant_obstacle": dominant_obstacle_name,
        # v2: 命运变化
        "fate_change_score": fate_change_score,
        "fate_change_level": fate_change_level,
        "fate_goal_progress": fate_signals_found.get("goal_progress", 0),
        "fate_setback": fate_signals_found.get("setback", 0),
        "fate_revelation": fate_signals_found.get("revelation", 0),
        "fate_relationship_shift": fate_signals_found.get("relationship_shift", 0),
        # v3: 生存流隐式爽点
        "survival_gain_count": survival_gain_count,
    }
