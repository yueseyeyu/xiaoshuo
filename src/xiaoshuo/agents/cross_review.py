#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
交叉评审模块: Qwen3.5 主审 + DeepSeek-R1 补充标注

方法: LLM-PeerReview (北航, 2026.3) 的 Flipped-triple scoring 简化版
      模型A生成报告 → 模型B标注遗漏 → 合并输出

v8.0: MoA 多视角评审 (S5) + 情绪直白度判据 (S1) + AI指纹词检测 (S6)
      - 单模型内模拟多视角: 逻辑/情绪/读者三视角 → 聚合
      - 新增 "情绪直白度" 维度, 检测是否用强情绪写法
      - 平台级 AI 指纹词库 (50+词) 交叉检测

8GB约束: 两模型不能共存, 需顺序切换 (~40s 额外开销)
"""

import sys
import re
from pathlib import Path

from xiaoshuo.agents.model_orchestrator import get_orchestrator
from xiaoshuo.infra.logging_config import get_logger
logger = get_logger(__name__)

# DeepSeek-R1 专长的微观维度 (Naming/Quantity/CharKnowledge)
R1_SPECIALTY_DIMS = ["Naming", "Quantity", "CharKnowledge"]

# v8.0: 平台级 AI 指纹词库 (S6, 来源: 番茄小说审核实战经验)
# 分类: 过度程度词 / 眼神表情类 / 身体反应类
# 高危词 (AI 降智高频) 单独标注, 触发更高权重
AI_FINGERPRINT_WORDS = {
    "过度程度词": [
        "死死", "紧紧", "轰然", "极其", "无比", "异常", "格外", "分外",
        "尤为", "万分", "彻底", "完全", "瞬间", "骤然", "猛然", "陡然",
        "顷刻间", "刹那间", "几乎", "仿佛", "宛若", "犹如", "好似", "像是",
        "隐隐", "微微", "淡淡", "一丝", "一抹", "一缕", "一股", "一阵",
    ],
    "眼神表情类": [
        "眼神复杂", "眼中闪过一丝", "眸中掠过", "瞳孔骤缩", "眼底泛起",
        "目光冰冷", "目光森然", "目光灼灼", "眼神变得凝重", "眼中满是震撼",
        "眼中透着难以置信", "脸色骤变", "脸色惨白", "脸色铁青", "神色复杂",
        "神情凝重", "嘴角抽搐", "嘴角微微上扬", "嘴角勾起一抹弧度",
    ],
    "身体反应类": [
        "指尖发白", "指节泛白", "拳头攥紧", "浑身一颤", "身体僵住",
        "后背发凉", "头皮发麻", "喉结滚动", "呼吸一滞", "呼吸急促",
        "心跳漏了一拍", "心中一沉", "心头狂震", "脑海轰鸣", "如遭雷击",
        "双腿发软", "脚步踉跄", "冷汗直冒", "额头青筋暴起", "手心全是汗",
        "后背猛然拔直",
    ],
}

# 高危词: AI 在降智状态下尤其高频的词
HIGH_RISK_FINGERPRINTS = [
    "极其", "无比", "瞬间", "猛然", "一丝", "一抹", "仿佛", "骤然",
]


def cross_review(
    chapter_text: str,
    chapter_num: int,
    primary_model: str = "main_model",
    secondary_model: str = "logic_cop_candidate",
    r1_specialty_only: bool = True,
    previous_findings: str = "",
) -> dict:
    """主模型全面审查 + 辅助模型对专长维度做补充标注。
    
    v7.5: 新增 previous_findings 参数 — 传入前次评审摘要，
    当前评审员会先读已知问题，避免重复检查，聚焦新发现。

    Args:
        chapter_text: 章节全文
        chapter_num: 章节编号
        primary_model: 主模型 key (默认 main_model = Qwen3.5-9B)
        secondary_model: 辅助模型 key (默认 logic_cop_candidate = DeepSeek-R1-7B)
        r1_specialty_only: 是否只让辅助模型审查其专长维度 (默认 True, 省 token)
        previous_findings: 前次评审摘要文本 (用于记忆积累, 避免重复)

    Returns:
        {"primary": 主模型报告, "secondary_patches": 辅助模型补充标注, 
         "merged": 合并报告, "findings_summary": 可传下一次的摘要}
    """
    orch = get_orchestrator()
    word_count = len(chapter_text.replace("\n", "").replace(" ", ""))
    if len(chapter_text) > 3000:
        chapter_text = chapter_text[:3000] + "\n[...章节过长, 仅分析前3000字符...]"

    # ── Phase 1: 主模型全面审查 (Qwen3.5, thinking=OFF) ──
    # v8.0 MoA 多视角 (S5): 单次推理模拟逻辑/情绪/读者三视角 → 聚合
    # v8.0 AI指纹词 (S6): 嵌入词库, 交叉检测 + 豁免规则
    # v8.0 强情绪判据 (S1): 检测是否使用外在动作/被迫承受/冰冷克制写法
    fp_categories = []
    for cat, words in AI_FINGERPRINT_WORDS.items():
        fp_categories.append(f"  - {cat}: {' / '.join(words[:10])}... (共{len(words)}个)")
    fp_list = "\n".join(fp_categories)
    high_risk = "、".join(HIGH_RISK_FINGERPRINTS)
    primary_sys = (
        "你是网文质量控制专家。请从以下三个视角审查本章，分别输出发现，最后综合评分。\n\n"
        "## 视角A: 逻辑审查\n"
        "覆盖: 时间线、因果关系、角色动机、世界观规则、信息一致性。\n\n"
        "## 视角B: 情绪表达质量\n"
        "检查作者的写法是否\u201c强情绪\u201d而非\u201c直白情绪\u201d。\n"
        "- 优秀写法 (加分): 通过外在动作、被迫承受苦难、冰冷克制的动作来传递情绪\n"
        "  (如: 将剑从泥中捡起擦干净; 摘下对方送的手表放入抽屉; 上前摆正遗像抚摸镜框后退鞠躬)\n"
        "- 直白写法 (扣分): 直接写\u201c他很愤怒\u201d\u201c她非常悲伤\u201d\u201c他心中一紧\u201d\n"
        "- 如果使用了身体反应类词汇 (如心跳加速、浑身一颤) 但缺少外部动作铺垫, 标记为\u201c情绪直白\u201d\n\n"
        "## 视角C: 读者体验\n"
        "检查: 钩子位置、节奏起伏、爽点/虐点分布、章末悬念。\n\n"
        "## AI 指纹词检测\n"
        "逐句扫描以下平台级 AI 指纹词, 标记出现频率和位置:\n"
        f"{fp_list}\n"
        f"特别注意高危词 (AI降智高频): {high_risk}\n"
        "豁免规则: 如果指纹词出现在对话中、角色口癖、或梦境/发疯/醉酒等非理性场景, 标注但豁免。\n\n"
        "## 综合输出\n"
        "先分别输出视角A/B/C的发现, 再输出指纹词检测, 最后给出综合评分。"
    )
    memory_hint = ""
    if previous_findings:
        memory_hint = (
            f"\n\n[前次已知问题, 勿重复报告]"
            f"\n{previous_findings[:800]}"
            f"\n[以上已知, 请聚焦本章新增或未解决的新问题]"
        )
    primary_user = (
        f"## 第{chapter_num}章 逻辑审查\n"
        f"## 章节 ({word_count}字):\n\n{chapter_text}"
        f"{memory_hint}\n\n"
        f"请逐条列出发现的所有逻辑问题。仅列新问题或已有问题在本章的新证据。"
    )
    primary_messages = [
        {"role": "system", "content": primary_sys},
        {"role": "user", "content": primary_user},
    ]
    primary_result = orch.chat("S3_logic_cop", primary_messages, max_tokens=2048, temperature=0.3, timeout=180)

    if "error" in primary_result:
        return {"error": f"主模型审查失败: {primary_result['error']}", "primary": primary_result}

    # ── Phase 2: 辅助模型交叉标注 (DeepSeek-R1-0528, 只查专长维度) ──
    # v7.5: 单GPU串行切换 — 先停 Qwen3.5, 启动 DeepSeek-R1-0528
    logger.info(f"  [SWAP] 切换到交叉模型 (DeepSeek-R1-0528-8B)...")
    swap_ok = orch.swap_to("logic_cop_candidate", timeout=120)
    if not swap_ok:
        logger.warning(f"  [WARN] 交叉模型不可用，仅返回主模型结果")
        return {"primary": primary_result["content"], "secondary_patches": "",
                "merged": f"## 主审查 (Qwen3.5-9B)\n\n{primary_result['content']}\n\n---\n## 交叉标注\n[交叉模型不可用，跳过]",
                "has_additions": False, "primary_usage": primary_result.get("usage", {}), "secondary_usage": None,
                "findings_summary": _extract_findings_summary(primary_result["content"], "")}

    if r1_specialty_only:
        specialty_desc = "、".join(R1_SPECIALTY_DIMS)
        secondary_user = (
            f"## 交叉标注: 只检查遗漏的微观问题\n"
            f"主模型已完成全面逻辑审查。你的任务是**只补充主模型可能遗漏的微观细节问题**，"
            f"包括: {specialty_desc}。\n\n"
            f"## 章节 ({word_count}字):\n\n{chapter_text}\n\n"
            f"## 主模型审查报告:\n{primary_result['content'][:2000]}\n\n"
            f"请标注主模型遗漏的具体问题。如果没有遗漏,回复[无遗漏]。"
        )
    else:
        secondary_user = (
            f"## 交叉审查\n"
            f"请独立审查以下章节，标注所有逻辑问题。\n\n"
            f"## 章节 ({word_count}字):\n\n{chapter_text}"
        )

    secondary_sys = (
        "你是网文逻辑审查专家。你的任务是找出主模型审查中可能遗漏的微观细节问题。"
        "重点关注: 命名不一致、数量矛盾、角色知识矛盾。直接输出发现的问题。"
    )
    secondary_messages = [
        {"role": "system", "content": secondary_sys},
        {"role": "user", "content": secondary_user},
    ]
    secondary_result = orch.chat("S3_cross_check", secondary_messages, max_tokens=2048, temperature=0.6, timeout=180)

    # ── 切回主模型 ──
    logger.info(f"  [SWAP] 切回主模型 (Qwen3.5-9B)...")
    orch.swap_to("main_model", timeout=120)

    # ── Phase 3: 合并 ──
    secondary_patch = ""
    if "error" not in secondary_result:
        secondary_patch = secondary_result["content"]

    has_additions = secondary_patch.strip() and "[无遗漏]" not in secondary_patch

    merged = (
        f"## 主审查 (Qwen3.5-9B)\n\n{primary_result['content']}\n\n"
        f"---\n"
        f"## 交叉标注 (DeepSeek-R1-7B)"
    )
    if has_additions:
        merged += f"\n\n{secondary_patch}"
    else:
        merged += "\n\n[交叉审查确认无遗漏问题]"

    # v7.5: findings summary for next iteration
    findings_summary = _extract_findings_summary(primary_result["content"], secondary_patch)

    return {
        "primary": primary_result["content"],
        "secondary_patches": secondary_patch,
        "has_additions": has_additions,
        "merged": merged,
        "findings_summary": findings_summary,
        "primary_usage": primary_result.get("usage", {}),
        "secondary_usage": secondary_result.get("usage", {}) if "error" not in secondary_result else None,
    }


def cross_review_iterative(
    chapter_text: str,
    chapter_num: int,
    max_rounds: int = 3,
    primary_model: str = "main_model",
) -> list:
    """v7.5: 迭代交叉评审 — 每轮累积记忆，直到无新发现或达到上限。
    
    适用于对同一章做深度审查。每轮评审员会收到上一轮的发现摘要，
    聚焦新增问题，避免冗余。
    
    Args:
        chapter_text: 章节全文
        chapter_num: 章节编号
        max_rounds: 最大迭代轮次 (默认3, 防无限循环)
        
    Returns:
        list of per-round review dicts, each with findings_summary
    """
    rounds = []
    previous = ""
    no_new_rounds = 0

    for r in range(max_rounds):
        result = cross_review(
            chapter_text, chapter_num,
            primary_model=primary_model,
            r1_specialty_only=(r > 0),  # 首轮交叉, 后续只专长
            previous_findings=previous,
        )
        if "error" in result:
            rounds.append(result)
            break

        rounds.append(result)
        previous = result.get("findings_summary", "")

        # Stop early if no additions in two consecutive rounds
        if not result.get("has_additions", True):
            no_new_rounds += 1
        else:
            no_new_rounds = 0
        if no_new_rounds >= 2:
            break

    return rounds


# S3 评审维度 (4 维度, 每个 1-10 分)
# v8.0: 新增 emotion 维度 (S1 强情绪写法)
REVIEW_DIMENSIONS = {
    "structure": "结构节奏: 爽点分布、钩子位置、章节节奏是否合理",
    "character": "角色一致性: 人设、动机、对话标签是否前后一致",
    "style":    "文笔质量: 句长分布、描写密度、AI痕迹是否可接受",
    "emotion":  "情绪表达: 是否使用强情绪写法 (外在动作/被迫承受/冰冷克制), 是否避免直白情绪词",
    # v8.1: 新增维度 (基于肘子方法论 + 视角管理 + 爽感奖励)
    "opening":    "开头质量: 前三章人物精简度(≤3人)、背景篇幅占比(≤30%)、黄金一句功能",
    "perspective": "视角一致性: 是否同段双视角穿帮、高潮是否频繁切视角、配角视角是否过长",
    "reward":     "奖励多样性: 本章是否包含数值型/权限型/关系型/未来型奖励, 是否立刻且可感知",
}

# 维度评分通过阈值
DIMENSION_PASS_THRESHOLD = 7


def _score_dimensions(merged_report: str, chapter_num: int) -> dict:
    """Ask primary model to score the review on 4 dimensions (1-10).

    Args:
        merged_report: merged review report from cross_review()
        chapter_num: chapter number for context

    Returns:
        dict: {"structure": N, "character": N, "style": N, "emotion": N, "_raw": raw_response}
    """
    orch = get_orchestrator()
    dim_desc = "\n".join(f"- {k}: {v}" for k, v in REVIEW_DIMENSIONS.items())
    dim_names = " ".join(f"{k}: N" for k in REVIEW_DIMENSIONS)
    scoring_prompt = (
        f"基于以下评审报告, 对第{chapter_num}章的{len(REVIEW_DIMENSIONS)}个维度打分(1-10分, 10=完美):\n\n"
        f"{dim_desc}\n\n"
        f"## 评审报告:\n{merged_report[:2000]}\n\n"
        f"请严格按以下格式输出 (每行一个维度, 仅输出数字):\n"
        f"{dim_names}"
    )
    messages = [
        {"role": "system", "content": "你是网文质量控制专家。仅输出评分, 无额外文字。"},
        {"role": "user", "content": scoring_prompt},
    ]
    result = orch.chat("S3_logic_cop", messages, max_tokens=128, temperature=0.0, timeout=60)

    scores = {}
    raw = result.get("content", "") if "error" not in result else ""
    if not raw:
        return {"error": "LLM scoring call failed, cannot evaluate dimensions", "_raw": ""}
    for line in raw.splitlines():
        for dim in REVIEW_DIMENSIONS:
            if dim in line.lower():
                try:
                    val = int("".join(c for c in line if c.isdigit()))
                    scores[dim] = min(10, max(1, val))
                except ValueError:
                    pass
    # Fill missing dimensions with default
    for dim in REVIEW_DIMENSIONS:
        if dim not in scores:
            scores[dim] = 5  # neutral default if parsing fails
    scores["_raw"] = raw
    return scores


def adaptive_review_loop(
    chapter_text: str,
    chapter_num: int,
    max_rounds: int = 5,
    min_score: int = DIMENSION_PASS_THRESHOLD,
    primary_model: str = "main_model",
) -> list:
    """v7.6: 自适应评审循环 — 维度评分 + 目标驱动终止。

    核心逻辑:
    - 每轮评审后对 3 维度打分 (structure/character/style)
    - 全部维度 >= min_score → 终止 (简单章节 1-2 轮)
    - 某维度连续 3 轮未达标 → 标记需人工介入, 终止
    - 最多 max_rounds 轮, 防无限循环

    Args:
        chapter_text: 章节全文
        chapter_num: 章节编号
        max_rounds: 最大迭代轮次 (默认5, 防死循环)
        min_score: 维度通过阈值 (默认7, 即 7/10 分)
        primary_model: 主模型 key

    Returns:
        list of per-round dicts, each with "scores", "findings_summary", etc.
        Last round may have "_stuck_dim" if a dimension is stuck.
    """
    rounds = []
    previous = ""
    dim_history = {d: [] for d in REVIEW_DIMENSIONS}

    for r in range(max_rounds):
        # ── 确定本轮聚焦维度 (上轮未通过的那些) ──
        focus_dims = []
        if r > 0:
            focus_dims = [d for d in REVIEW_DIMENSIONS
                          if dim_history[d] and dim_history[d][-1] < min_score]

        # ── 构建聚焦提示 ──
        focus_hint = ""
        if focus_dims:
            dim_names = "、".join(f"{d}({dim_history[d][-1]}分)" for d in focus_dims)
            focus_hint = (
                f"\n\n[本轮聚焦维度: {dim_names} — 上轮未达标, 请重点审查这些方面]"
            )

        # ── 执行评审 ──
        combined_previous = previous + focus_hint if previous else focus_hint
        result = cross_review(
            chapter_text, chapter_num,
            primary_model=primary_model,
            r1_specialty_only=(r > 0),  # 首轮全量交叉, 后续只专长
            previous_findings=combined_previous if combined_previous else "",
        )
        if "error" in result:
            rounds.append(result)
            break

        # ── 维度评分 ──
        scores = _score_dimensions(result["merged"], chapter_num)
        result["scores"] = scores
        for d in REVIEW_DIMENSIONS:
            dim_history[d].append(scores.get(d, 0))

        rounds.append(result)
        previous = result.get("findings_summary", "")

        # ── 终止条件 1: 全部维度通过 ──
        all_pass = all(scores.get(d, 0) >= min_score for d in REVIEW_DIMENSIONS)
        if all_pass:
            result["_termination"] = f"all_pass_round_{r + 1}"
            break

        # ── 终止条件 2: 某维度连续 3 轮停滞 ──
        stuck = None
        for d, history in dim_history.items():
            if len(history) >= 3 and all(s < min_score for s in history[-3:]):
                stuck = d
                break
        if stuck:
            result["_stuck_dim"] = stuck
            result["_stuck_history"] = dim_history[stuck][-3:]
            result["_termination"] = f"stuck_{stuck}"
            break

        # ── 终止条件 3: 无新发现 + 非首轮 ──
        if r > 0 and not result.get("has_additions", True):
            no_new_count = 1
            # Check if previous round also had no additions
            if len(rounds) >= 2 and not rounds[-2].get("has_additions", True):
                no_new_count = 2
            if no_new_count >= 2:
                result["_termination"] = "no_new_findings"
                break

    return rounds


def format_loop_summary(rounds: list) -> str:
    """Format adaptive review loop results as readable summary."""
    if not rounds:
        return "[FAIL] No rounds completed"

    lines = ["# S3 自适应评审总结", ""]
    final = rounds[-1]

    # Per-round overview
    lines.append("## 逐轮结果")
    lines.append("| 轮次 | structure | character | style | emotion | 新增发现 | 判定 |")
    lines.append("|------|-----------|-----------|-------|---------|---------|------|")
    for i, r in enumerate(rounds, 1):
        scores = r.get("scores", {})
        struct = scores.get("structure", "?")
        char = scores.get("character", "?")
        style = scores.get("style", "?")
        emotion = scores.get("emotion", "?")
        has_new = "[OK]" if r.get("has_additions", False) else "无"
        # Determine pass/fail per round
        threshold = DIMENSION_PASS_THRESHOLD
        all_pass = all(
            scores.get(d, 0) >= threshold for d in REVIEW_DIMENSIONS
        )
        verdict = "[PASS]" if all_pass else "[FAIL]"
        lines.append(f"| {i} | {struct} | {char} | {style} | {emotion} | {has_new} | {verdict} |")

    lines.append("")

    # Termination reason
    term = final.get("_termination", "unknown")
    term_map = {
        "all_pass_round_1": "第1轮全部通过 (简单章节)",
        "all_pass_round_2": "第2轮全部通过",
        "all_pass_round_3": "第3轮全部通过",
        "all_pass_round_4": "第4轮全部通过",
        "all_pass_round_5": "第5轮全部通过",
        "no_new_findings": "无新发现, 自然收敛",
    }
    if term.startswith("stuck_"):
        dim = term.replace("stuck_", "")
        history = final.get("_stuck_history", [])
        term_map[term] = f"[WARN] 维度 {dim} 连续 {len(history)} 轮未达标 ({history}), 需人工介入"
    lines.append(f"## 终止原因: {term_map.get(term, term)}")

    # Final scores
    lines.append("")
    lines.append("## 最终评分")
    final_scores = final.get("scores", {})
    for d in REVIEW_DIMENSIONS:
        score = final_scores.get(d, "?")
        icon = "[OK]" if isinstance(score, int) and score >= DIMENSION_PASS_THRESHOLD else "[FAIL]"
        lines.append(f"  {icon} {d}: {score}/10")

    total_llm_calls = sum(
        (1 if r.get("primary_usage") else 0) +
        (1 if r.get("secondary_usage") else 0) +
        1  # scoring call per round
        for r in rounds
    )
    lines.append(f"\n总 LLM 调用: {total_llm_calls} 次 | 总轮次: {len(rounds)}")

    return "\n".join(lines)


def _extract_findings_summary(primary_report, secondary_patch):
    """Extract a concise summary from review reports for memory passing."""
    # Take first 3 lines from primary + secondary as context summary
    primary_lines = [l.strip("- ") for l in primary_report.splitlines()
                     if l.strip().startswith(("- ", "* ", "1.", "2.", "3."))][:5]
    secondary_lines = [l.strip("- ") for l in (secondary_patch or "").splitlines()
                       if l.strip().startswith(("- ", "* "))][:3]
    summary = "; ".join(primary_lines + secondary_lines)
    return summary[:600] if summary else ""


# v8.0: AI 指纹词扫描工具 (S6 平台合规预检)
def scan_fingerprints(text: str, exempt_dialogue: bool = True) -> dict:
    """扫描文本中的 AI 指纹词，返回风险报告。

    Args:
        text: 要扫描的章节全文
        exempt_dialogue: 是否豁免对话中的指纹词 (默认 True)

    Returns:
        {
            "total_count": int,
            "high_risk_count": int,
            "by_category": {category: [{"word": str, "count": int}]},
            "high_risk_hits": [{"word": str, "count": int}],
            "risk_level": "low|medium|high|critical",
        }
    """
    result = {
        "total_count": 0,
        "high_risk_count": 0,
        "by_category": {},
        "high_risk_hits": [],
        "risk_level": "low",
    }

    # 简单对话豁免: 如果 exempt_dialogue=True, 移除引号内的内容
    scan_text = text
    if exempt_dialogue:
        scan_text = re.sub(r'"[^"]*"', '', scan_text)
        scan_text = re.sub(r'"[^"]*"', '', scan_text)
        scan_text = re.sub(r'"[^"]*"', '', scan_text)

    for category, words in AI_FINGERPRINT_WORDS.items():
        cat_hits = []
        for word in words:
            count = scan_text.count(word)
            if count > 0:
                cat_hits.append({"word": word, "count": count})
                result["total_count"] += count
                if word in HIGH_RISK_FINGERPRINTS:
                    result["high_risk_count"] += count
                    result["high_risk_hits"].append({"word": word, "count": count})
        if cat_hits:
            result["by_category"][category] = cat_hits

    # 风险分级
    if result["total_count"] == 0:
        result["risk_level"] = "low"
    elif result["total_count"] <= 5 and result["high_risk_count"] <= 2:
        result["risk_level"] = "medium"
    elif result["total_count"] <= 15 and result["high_risk_count"] <= 5:
        result["risk_level"] = "high"
    else:
        result["risk_level"] = "critical"

    return result


# v8.1: AI 率预估 (基于指纹词密度 + 经验系数)
# 番茄小说平台阈值: 30% AI 率为红线，超过则审核不通过
# 参考: 番茄小说"评估期"机制 — 前 10 章 AI 查重 + 20 万字书测触发
# 阈值配置从 config.yaml compliance 段读取 (SSOT)


def _load_compliance_config() -> dict:
    """从 config.yaml 加载合规预检配置 (含默认降级)"""
    try:
        from xiaoshuo.infra.config_manager import get_config_section
        cfg = get_config_section("compliance")
        if cfg:
            return cfg
    except Exception:
        pass
    return {
        "ai_rate_threshold": 0.30,
        "ai_rate_warning": 0.20,
        "ai_rate_safe": 0.10,
        "fingerprint_density_coeff": 0.01,
    }


def estimate_ai_rate(text: str, fingerprint_result: dict | None = None) -> dict:
    """估算文本的 AI 生成率 (基于指纹词密度).

    Args:
        text: 待检测文本
        fingerprint_result: scan_fingerprints() 的结果 (可选，不传则自动扫描)

    Returns:
        {
            "estimated_ai_rate": float,     # 0.0-1.0
            "ai_rate_pct": float,           # 百分比表示
            "risk_level": str,              # "safe"|"warning"|"danger"|"blocked"
            "passed": bool,                 # 是否通过 30% 红线
            "fingerprint_count": int,       # 指纹词总数
            "text_length": int,             # 文本长度 (字符)
            "threshold": float,             # 阈值 (30%)
            "recommendation": str,          # 建议
        }
    """
    cfg = _load_compliance_config()
    threshold = cfg.get("ai_rate_threshold", 0.30)
    warning = cfg.get("ai_rate_warning", 0.20)
    safe = cfg.get("ai_rate_safe", 0.10)
    coeff = cfg.get("fingerprint_density_coeff", 0.01)

    if fingerprint_result is None:
        fingerprint_result = scan_fingerprints(text, exempt_dialogue=True)

    text_len = len(text.replace("\n", "").replace(" ", ""))
    fp_count = fingerprint_result.get("total_count", 0)

    if text_len == 0:
        return {
            "estimated_ai_rate": 0.0,
            "ai_rate_pct": 0.0,
            "risk_level": "safe",
            "passed": True,
            "fingerprint_count": 0,
            "text_length": 0,
            "threshold": threshold,
            "recommendation": "文本为空",
        }

    # 指纹词密度 → AI 率估算
    density = fp_count / text_len
    estimated_rate = min(1.0, density / coeff)

    # 风险分级
    if estimated_rate <= safe:
        level = "safe"
        recommendation = "AI 率在安全范围内，可正常提交"
    elif estimated_rate <= warning:
        level = "warning"
        recommendation = "AI 率接近警告线，建议人工润色指纹词密集段落"
    elif estimated_rate <= threshold:
        level = "danger"
        recommendation = "AI 率接近红线 (30%)，建议大幅改写，降低指纹词密度"
    else:
        level = "blocked"
        recommendation = "AI 率超过 30% 红线，禁止提交！需全面改写，降低至 20% 以下"

    return {
        "estimated_ai_rate": round(estimated_rate, 4),
        "ai_rate_pct": round(estimated_rate * 100, 1),
        "risk_level": level,
        "passed": estimated_rate <= threshold,
        "fingerprint_count": fp_count,
        "text_length": text_len,
        "threshold": threshold,
        "recommendation": recommendation,
    }


# ============================================================
# v8.1: 开头诊断 (肘子方法论: 黄金一句 + 前三章人物精简 + 背景篇幅)
# ============================================================

# 中文人物名检测模式 (姓+名, 2-3字)
_RE_NAME_PATTERN = re.compile(
    r'(?:[李王张刘陈杨赵黄周吴徐孙胡朱高林何郭马罗]'
    r'|[郑梁宋谢唐韩冯于董萧程曹袁邓许傅沈曾彭吕苏卢蒋蔡贾丁魏薛叶阎余潘杜戴夏钟汪田任姜范方石姚谭廖邹熊金陆郝孔白崔康毛邱秦江史顾侯邵孟龙万段雷钱汤尹黎易常武乔贺赖龚文]'
    r')(?:[^\s，。！？、；：""''（）《》\n]{1,2})'
)

# 内心活动关键词 (用于视角检测)
_MENTAL_VERBS = [
    "心想", "暗道", "觉得", "感到", "暗想", "思忖", "琢磨",
    "意识到", "想起", "回忆起", "想到", "思考", "暗忖", "琢磨着",
]

# 背景/回忆关键词 (用于开头背景篇幅检测)
_BACKGROUND_KEYWORDS = [
    "曾经", "以前", "从前", "过去", "记得", "那年", "前世",
    "穿越前", "重生前", "穿越之前", "重生之前", "上辈子",
    "那一年", "记忆中", "回忆", "回想", "那时候", "当时",
]

# 感官关键词 (用于感官丰富度检测)
_SENSORY_WORDS = {
    "视觉": ["看", "见", "望", "瞪", "盯", "瞥", "瞅", "瞧", "目睹", "看见", "看到",
             "目击", "观望", "凝视", "注视", "眺望", "张望", "映入眼帘"],
    "听觉": ["听", "听见", "听到", "闻", "声", "响", "音", "喊", "叫", "吼", "轰鸣",
             "金鸣", "破空", "呼啸", "炸响", "嘶喊", "尖叫", "低语", "耳语", "嘈杂"],
    "触觉": ["触", "碰", "摸", "热", "冷", "凉", "烫", "麻", "痒", "振动",
             "擦过", "拂过", "刺骨", "灼热", "冰寒", "发抖", "麻痒"],
    "嗅觉": ["闻", "嗅", "香", "臭", "腥", "焦", "腐", "气味", "刺鼻", "浓郁", "清新"],
    "痛觉": ["痛", "疼", "酸", "麻", "灼", "撕裂", "刺痛", "剧痛", "绞痛", "酸痛"],
}

# 奖励类型关键词 (用于爽感奖励检测)
_REWARD_KEYWORDS = {
    "数值型": ["突破", "升级", "获得", "提升", "增加", "增长", "解锁", "觉醒",
              "涨", "升", "翻倍", "暴涨", "飙升", "突破到"],
    "权限型": ["成为", "晋升", "获得资格", "进入", "认证", "认可", "授予",
              "从.*变为", "成为.*弟子", "晋升为"],
    "关系型": ["认可", "依赖", "感激", "感谢", "信任", "依赖", "崇拜", "追随",
              "交心", "认主", "受.*尊敬", "被.*认可"],
    "未来型": ["伏笔", "线索", "预兆", "预示", "暗示", "秘密", "隐藏",
              "潜力", "契机", "机缘", "预知", "征兆"],
}

# 转折词 (用于简介反转检测)
_BLURB_TWIST_WORDS = ["却", "但", "然而", "不过", "可是", "不料", "谁知", "哪知",
                      "偏偏", "竟然", "居然", "看似", "实则", "表面", "背地"]


def scan_opening_diagnosis(text: str, chapter_num: int) -> dict:
    """前三章开头诊断 (基于肘子方法论).

    Args:
        text: 章节全文
        chapter_num: 章节编号 (1-based)

    Returns:
        {
            "character_names": [str],
            "character_count": int,
            "character_warning": str|null,
            "background_ratio": float,
            "background_warning": str|null,
            "golden_sentence": str,
            "golden_sentence_type": str,  # 需LLM分类
            "applicable": bool,  # 是否适用 (前三章才适用)
        }
    """
    result = {
        "character_names": [],
        "character_count": 0,
        "character_warning": None,
        "background_ratio": 0.0,
        "background_warning": None,
        "golden_sentence": "",
        "golden_sentence_type": "",
        "applicable": chapter_num <= 3,
    }

    if chapter_num > 3:
        return result

    # 1. 黄金一句: 提取第一段第一个非空句
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if lines:
        first_line = lines[0]
        # 取第一个句号之前的句子, 或整行(≤30字)
        first_sentence = first_line.split("。")[0].strip()
        if not first_sentence:
            first_sentence = first_line.split("，")[0].strip()
        result["golden_sentence"] = first_sentence[:50]

    # 2. 人物出场计数: 正则匹配中文姓名
    names = set()
    for m in _RE_NAME_PATTERN.finditer(text):
        name = m.group()
        if 2 <= len(name) <= 3:
            names.add(name)
    result["character_names"] = sorted(names)[:20]
    result["character_count"] = len(names)
    if result["character_count"] > 3:
        result["character_warning"] = (
            f"[WARN] 前三章出场人物 {result['character_count']} 人, "
            f"建议≤3人 (肘子: 除主角外最多保留2个重要人物)"
        )

    # 3. 背景/回忆篇幅占比: 统计包含回忆关键词的句子
    total_chars = len(text.replace("\n", "").replace(" ", ""))
    if total_chars > 0:
        bg_chars = 0
        paragraphs = text.split("\n")
        for para in paragraphs:
            if any(kw in para for kw in _BACKGROUND_KEYWORDS):
                bg_chars += len(para.replace("\n", "").replace(" ", ""))
        result["background_ratio"] = round(bg_chars / total_chars * 100, 1)
        if result["background_ratio"] > 30:
            result["background_warning"] = (
                f"[WARN] 背景/回忆篇幅占比 {result['background_ratio']}%, "
                f"建议≤30% (肘子: 新人切忌大篇幅交代背景)"
            )

    return result


def scan_blurb_quality(blurb: str) -> dict:
    """简介质量分析 (基于肘子方法论).

    Args:
        blurb: 简介文本

    Returns:
        {
            "has_core_selling_point": bool,  # 是否有核心卖点
            "core_selling_point_hint": str,  # 核心卖点关键词
            "element_focus": str,  # 专注要素
            "has_twist": bool,  # 是否有反转
            "twist_hints": [str],  # 转折词/反差点
            "element_conflict": bool,  # 是否要素杂糅
            "element_conflict_detail": str,
            "score": int,  # 0-100
        }
    """
    result = {
        "has_core_selling_point": False,
        "core_selling_point_hint": "",
        "element_focus": "",
        "has_twist": False,
        "twist_hints": [],
        "element_conflict": False,
        "element_conflict_detail": "",
        "score": 50,
    }

    if not blurb or len(blurb) < 20:
        result["score"] = 0
        return result

    score = 50

    # 1. 核心卖点检测: 简介是否包含"系统/金手指/技能/能力"等关键词
    core_keywords = ["系统", "金手指", "能力", "技能", "天赋", "觉醒", "获得",
                     "穿越", "重生", "回到", "唯一", "最强", "无敌", "末日",
                     "生存", "进化", "变异", "基因", "战斗", "力量"]
    core_hits = [kw for kw in core_keywords if kw in blurb]
    if core_hits:
        result["has_core_selling_point"] = True
        result["core_selling_point_hint"] = "、".join(core_hits[:5])
        score += 20

    # 2. 要素专注度检测: 是否杂糅多条线
    element_signals = {
        "悬疑": ["悬疑", "谜", "真相", "秘密", "调查", "解谜", "线索"],
        "升级": ["升级", "变强", "突破", "修炼", "等级", "实力", "突破"],
        "情感": ["感情", "爱情", "恋爱", "情感", "心动", "暧昧", "关系"],
        "生存": ["生存", "活下去", "末日", "废土", "灾难", "逃", "活着"],
        "复仇": ["复仇", "报仇", "血债", "仇恨", "血仇", "清算"],
    }
    detected_elements = []
    for elem, kw_list in element_signals.items():
        if any(kw in blurb for kw in kw_list):
            detected_elements.append(elem)

    if len(detected_elements) == 1:
        result["element_focus"] = detected_elements[0]
        score += 10
    elif len(detected_elements) >= 3:
        result["element_conflict"] = True
        result["element_conflict_detail"] = (
            f"[WARN] 简介同时涉及 {', '.join(detected_elements)} 条线, "
            f"建议专注一个要素 (肘子: 悬疑文就写悬疑, 爽文就写爽)"
        )
        score -= 10
    elif len(detected_elements) == 2:
        result["element_focus"] = "、".join(detected_elements)
        # 两条线可以接受, 不加不减

    # 3. 反转检测: 是否有转折词
    twist_hits = [w for w in _BLURB_TWIST_WORDS if w in blurb]
    if twist_hits:
        result["has_twist"] = True
        result["twist_hints"] = twist_hits[:5]
        score += 10

    # 4. 长度检查
    if len(blurb) < 50:
        score -= 5
    elif len(blurb) > 500:
        score -= 5

    result["score"] = min(100, max(0, score))
    return result


def scan_perspective(text: str) -> dict:
    """视角一致性检测: 同段双视角穿帮 (基于视角管理方法论).

    核心铁律: 同一个自然段, 只允许存在一个感知主体。
    你站谁的视角, 就只能写谁看见、听见、摸到、想到的东西。

    Args:
        text: 章节全文

    Returns:
        {
            "violations": [{"paragraph": str, "perspectives": [str], "evidence": str}],
            "violation_count": int,
            "risk_level": "low|medium|high|critical",
        }
    """
    result = {
        "violations": [],
        "violation_count": 0,
        "risk_level": "low",
    }

    # 分段落
    paragraphs = [p.strip() for p in text.split("\n") if p.strip() and len(p.strip()) > 20]

    for para in paragraphs:
        # 检测段落中的人物名
        names_in_para = set()
        for m in _RE_NAME_PATTERN.finditer(para):
            name = m.group()
            if 2 <= len(name) <= 3:
                names_in_para.add(name)

        # 检测段落中的内心活动
        mental_owners = []
        for verb in _MENTAL_VERBS:
            for m in re.finditer(re.escape(verb), para):
                # 向前查找最近的人物名 (最多前20字)
                prefix = para[max(0, m.start() - 20):m.start()]
                found_name = None
                for name in sorted(names_in_para, key=len, reverse=True):
                    if name in prefix:
                        found_name = name
                        break
                if found_name:
                    mental_owners.append(found_name)

        # 如果同一段落中出现 2+ 不同人物的内心活动 → 穿帮
        unique_owners = list(dict.fromkeys(mental_owners))  # 去重保序
        if len(unique_owners) >= 2:
            evidence = " ".join([f"{o}的内心活动" for o in unique_owners])
            result["violations"].append({
                "paragraph": para[:120] + ("..." if len(para) > 120 else ""),
                "perspectives": unique_owners,
                "evidence": f"[同段双视角] 段落中同时出现 {evidence}",
            })
            result["violation_count"] += 1

    # 风险分级
    if result["violation_count"] == 0:
        result["risk_level"] = "low"
    elif result["violation_count"] <= 2:
        result["risk_level"] = "medium"
    elif result["violation_count"] <= 5:
        result["risk_level"] = "high"
    else:
        result["risk_level"] = "critical"

    return result


def scan_sensory_richness(text: str) -> dict:
    """感官丰富度检测: 统计打斗/动作场景中的感官维度分布.

    检测视觉/听觉/触觉/嗅觉/痛觉五种感官的关键词密度,
    输出雷达图数据和丰富度评分。

    Args:
        text: 章节全文

    Returns:
        {
            "sensory_counts": {sense: int},
            "total_sensory_hits": int,
            "richness_score": float,  # 0.0-1.0
            "radar_data": [{label: str, value: int}],
            "missing_senses": [str],
            "warning": str|null,
            "text_length": int,
        }
    """
    result = {
        "sensory_counts": {},
        "total_sensory_hits": 0,
        "richness_score": 0.0,
        "radar_data": [],
        "missing_senses": [],
        "warning": None,
        "text_length": len(text),
    }

    total_chars = len(text.replace("\n", "").replace(" ", ""))
    if total_chars == 0:
        return result

    for sense, words in _SENSORY_WORDS.items():
        count = 0
        for word in words:
            count += text.count(word)
        result["sensory_counts"][sense] = count
        result["total_sensory_hits"] += count
        result["radar_data"].append({"label": sense, "value": count})

    # 丰富度评分: 有多少种感官被使用
    senses_with_hits = sum(1 for c in result["sensory_counts"].values() if c > 0)
    total_senses = len(_SENSORY_WORDS)
    result["richness_score"] = round(senses_with_hits / total_senses, 2)

    # 缺失的感官
    result["missing_senses"] = [
        s for s, c in result["sensory_counts"].items() if c == 0
    ]

    # 警告: 只有视觉, 缺少其他感官
    if senses_with_hits <= 1 and result["sensory_counts"].get("视觉", 0) > 0:
        result["warning"] = (
            "[WARN] 描写仅含视觉感官, 缺少听觉/触觉/嗅觉/痛觉。"
            "建议增加动作细节(指节/脚尖/衣袂)和气势渲染(环境/气氛)"
        )

    return result


def scan_reward_diversity(text: str) -> dict:
    """奖励多样性检测: 统计本章是否包含多种奖励类型.

    基于七步正反馈循环的四类奖励模型:
    - 数值型: 直观的数值变化 (等级突破/力量提升)
    - 权限型: 身份转变 (从弟子到亲传/获得资格)
    - 关系型: 情感满足 (被认可/被依赖/建立羁绊)
    - 未来型: 激发期待 (伏笔/契机/潜力)

    Args:
        text: 章节全文

    Returns:
        {
            "reward_types_found": [str],
            "reward_count": int,
            "diversity_score": float,  # 0.0-1.0
            "by_type": {type: str|null},  # 每类找到的原文片段
            "warning": str|null,
        }
    """
    result = {
        "reward_types_found": [],
        "reward_count": 0,
        "diversity_score": 0.0,
        "by_type": {},
        "warning": None,
    }

    for reward_type, keywords in _REWARD_KEYWORDS.items():
        hit = None
        for kw in keywords:
            # 使用 re.search 支持正则模式 (如 "从.*变为")
            if re.search(kw, text):
                # 找包含关键词的句子作为证据
                for sentence in re.split(r'[。！？]', text):
                    if re.search(kw, sentence):
                        hit = sentence.strip()[:80]
                        break
                if hit:
                    break
        result["by_type"][reward_type] = hit
        if hit:
            result["reward_types_found"].append(reward_type)
            result["reward_count"] += 1

    result["diversity_score"] = round(result["reward_count"] / 4, 2)

    if result["reward_count"] == 0:
        result["warning"] = (
            "[WARN] 本章未检测到奖励类型。"
            "建议每章至少包含一种奖励 (数值/权限/关系/未来), 立刻且可感知"
        )
    elif result["reward_count"] == 1:
        result["warning"] = (
            f"[INFO] 本章仅含 {result['reward_types_found'][0]} 奖励, "
            f"建议丰富奖励类型 (数值/权限/关系/未来)"
        )

    return result


# ═══════════════════════════════════════════════════════════════
# 爽点四象限关键词 (微观爽点单元: 装逼→打脸→震惊→收获)
# 与正反馈七步循环 (宏观) 形成分层分析
# ═══════════════════════════════════════════════════════════════
_PLEASURE_QUADRANT_KEYWORDS = {
    "装逼": {
        "pattern": r"(展示|亮出|释放|显露|不再隐藏|真正实力|真实身份|隐藏修为|低调出手|露出|展现|使出|不再掩饰|隐藏的|真正.*力量|底牌)",
        "description": "主角优势展示 (语言/动作/心理)",
    },
    "打脸": {
        "pattern": r"(怎么可能|不可能|不敢相信|难以置信|目瞪口呆|瞠目结舌|竟然|居然|反转|逆袭|碾压|出乎意料|没想到|无法.*相信|震惊.*说不出)",
        "description": "预期违背 (嘲讽→成功, 反差)",
    },
    "震惊": {
        "pattern": r"(震惊|震撼|惊讶|惊恐|呆住|愣住|傻眼|倒吸.*凉气|一片哗然|鸦雀无声|齐刷刷|纷纷.*看向|全场.*寂静|众人.*反应|所有人.*目光)",
        "description": "旁人反应 (敌人/队友/路人/围观群众)",
    },
    "收获": {
        "pattern": r"(获得|得到|收获|突破|晋升|升级|解锁|奖励|功法|资源|认可|重视|收服|提升|变强|进化|觉醒|新.*能力|从.*变为|成为.*弟子)",
        "description": "实际利益 (数值/权限/关系/未来型)",
    },
}


def scan_pleasure_quadrant(text: str) -> dict:
    """爽点四象限检测: 装逼→打脸→震惊→收获 链式结构分析.

    基于网文爽点设计理论, 将每章正文按时间轴标注四象限:
    - 装逼(铺垫): 主角优势展示
    - 打脸(核心): 预期违背, 反转
    - 震惊(反响): 旁人反应衬托
    - 收获(实际): 主角获得实际利益

    四缺一检测: 只有装逼无打脸=空洞, 只有打脸无震惊=爽感减半.

    Args:
        text: 章节全文

    Returns:
        {
            "quadrants_found": [str],      # 检测到的象限列表
            "quadrant_count": int,          # 0-4
            "completeness": str,            # "完整"|"四缺一"|"四缺二"|"四缺三"|"无爽点"
            "completeness_score": float,    # 0.0-1.0
            "by_quadrant": {str: list},     # 每个象限的原文片段 (最多3条)
            "timeline": [dict],             # 按段落顺序的象限标注 (用于可视化)
            "warnings": [str],              # 结构完整性警告
            "missing_quadrants": [str],     # 缺失的象限
        }
    """
    result = {
        "quadrants_found": [],
        "quadrant_count": 0,
        "completeness": "无爽点",
        "completeness_score": 0.0,
        "by_quadrant": {},
        "timeline": [],
        "warnings": [],
        "missing_quadrants": [],
    }

    # 分段落扫描
    paragraphs = [p.strip() for p in text.split("\n") if p.strip() and len(p.strip()) > 15]
    if not paragraphs:
        return result

    quadrant_hits = {q: [] for q in _PLEASURE_QUADRANT_KEYWORDS}
    quadrant_set = set()

    for i, para in enumerate(paragraphs):
        para_labels = []
        for q_name, q_info in _PLEASURE_QUADRANT_KEYWORDS.items():
            if re.search(q_info["pattern"], para):
                para_labels.append(q_name)
                quadrant_set.add(q_name)
                # 保存证据 (最多3条)
                if len(quadrant_hits[q_name]) < 3:
                    quadrant_hits[q_name].append(para[:120] + ("..." if len(para) > 120 else ""))

        if para_labels:
            result["timeline"].append({
                "para_index": i,
                "labels": para_labels,
                "text_preview": para[:80] + ("..." if len(para) > 80 else ""),
            })

    result["by_quadrant"] = {q: hits for q, hits in quadrant_hits.items() if hits}
    result["quadrants_found"] = sorted(quadrant_set)
    result["quadrant_count"] = len(quadrant_set)
    result["completeness_score"] = round(result["quadrant_count"] / 4, 2)
    result["missing_quadrants"] = sorted(set(_PLEASURE_QUADRANT_KEYWORDS.keys()) - quadrant_set)

    # 完整性判定
    if result["quadrant_count"] == 4:
        result["completeness"] = "完整"
    elif result["quadrant_count"] == 3:
        result["completeness"] = "四缺一"
        result["warnings"].append(
            f"[四缺一] 缺失象限: {', '.join(result['missing_quadrants'])}。"
            "爽点结构不完整, 爽感减半"
        )
    elif result["quadrant_count"] == 2:
        result["completeness"] = "四缺二"
        result["warnings"].append(
            f"[四缺二] 缺失象限: {', '.join(result['missing_quadrants'])}。"
            "爽点仅有骨架, 缺乏血肉"
        )
    elif result["quadrant_count"] == 1:
        result["completeness"] = "四缺三"
        result["warnings"].append(
            f"[四缺三] 仅检测到 {result['quadrants_found'][0]}, "
            "单象限爽点空洞无力, 读者耐心即将耗尽"
        )
    else:
        result["completeness"] = "无爽点"
        result["warnings"].append(
            "[无爽点] 本章未检测到爽点结构, 如非过渡章节, 建议增加爽点单元"
        )

    # 专项警告: 装逼+打脸+震惊 但无收获 → 爽点不兑现
    has_show = "装逼" in quadrant_set
    has_slap = "打脸" in quadrant_set
    has_shock = "震惊" in quadrant_set
    has_reward = "收获" in quadrant_set

    if has_show and has_slap and not has_reward:
        result["warnings"].append(
            "[WARN] 爽点只打脸不兑现: 有装逼+打脸+震惊但无收获, "
            "读者爽感不完整, 建议增加实际获得 (数值/权限/关系/信息)"
        )
    if has_show and not has_slap:
        result["warnings"].append(
            "[WARN] 爽点只铺垫不兑现: 有装逼但无打脸, "
            "装逼没有后续打脸是不完整不过瘾的 (建议: 装逼→打脸→震惊→收获)"
        )
    if has_slap and not has_shock:
        result["warnings"].append(
            "[WARN] 爽点无反响: 有打脸但无震惊, "
            "打脸后缺少旁人反应, 爽感减半。\"总得有人看你打脸\""
        )

    return result


# ============================================================
# 自检
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("  cross_review.py — 自检")
    print("=" * 60)
    print("[OK] module loaded")
    print("[OK] R1_SPECIALTY_DIMS:", R1_SPECIALTY_DIMS)
    print("[OK] REVIEW_DIMENSIONS:", list(REVIEW_DIMENSIONS.keys()))
    print("[OK] DIMENSION_PASS_THRESHOLD:", DIMENSION_PASS_THRESHOLD)
    print("[OK] cross_review() defined")
    print("[OK] cross_review_iterative() defined (v7.5)")
    print("[OK] adaptive_review_loop() defined (v7.6)")
    print("[OK] _score_dimensions() defined")
    print("[OK] format_loop_summary() defined")
    print("[OK] scan_fingerprints() defined (v8.0)")
    print("[OK] scan_opening_diagnosis() defined (v8.1)")
    print("[OK] scan_blurb_quality() defined (v8.1)")
    print("[OK] scan_pleasure_quadrant() defined (v8.2)")
    print("[OK] scan_perspective() defined (v8.1)")
    print("[OK] scan_sensory_richness() defined (v8.1)")
    print("[OK] scan_reward_diversity() defined (v8.1)")

    # ── v8.1: 新函数自检 ──
    test_text = (
        "林风站在废墟上，望着远处的地平线。\n"
        "他心里暗道：这片区域已经没有活人了。\n"
        "另一边，陈默也心想：这些丧尸的速度比昨天更快了。\n"
        "他握紧拳头，指节捏得发白，拳风擦过破烂的墙壁，发出刺耳的金鸣。\n"
        "一阵腐臭的气味飘来，他咬紧牙关。"
    )

    # 视角检测
    persp_result = scan_perspective(test_text)
    print("[TEST] scan_perspective:", persp_result["risk_level"],
          "violations:", persp_result["violation_count"])

    # 感官丰富度
    sensory_result = scan_sensory_richness(test_text)
    print("[TEST] scan_sensory_richness: score:", sensory_result["richness_score"],
          "missing:", sensory_result["missing_senses"])

    # 奖励多样性
    reward_result = scan_reward_diversity(test_text)
    print("[TEST] scan_reward_diversity: types:", reward_result["reward_types_found"],
          "score:", reward_result["diversity_score"])

    # 开头诊断
    opening_result = scan_opening_diagnosis(test_text, 1)
    print("[TEST] scan_opening_diagnosis(ch1): chars:", opening_result["character_count"],
          "bg_ratio:", opening_result["background_ratio"])

    # 简介质量
    blurb_result = scan_blurb_quality("末世降临，废土生存，唯一的能力觉醒者，却要面对最残酷的真相。")
    print("[TEST] scan_blurb_quality: score:", blurb_result["score"],
          "core:", blurb_result["has_core_selling_point"],
          "focus:", blurb_result["element_focus"])

    print("[INFO] 使用: cross_review(chapter_text, chapter_num)")
    print("[INFO] 自适应循环: adaptive_review_loop(chapter_text, chapter_num)")
    print("[INFO] 8GB约束: 模型顺序切换 ~40s 额外开销")
    print("[DONE]")
