#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
交叉评审模块: Qwen3.5 主审 + DeepSeek-R1 补充标注

方法: LLM-PeerReview (北航, 2026.3) 的 Flipped-triple scoring 简化版
      模型A生成报告 → 模型B标注遗漏 → 合并输出

8GB约束: 两模型不能共存, 需顺序切换 (~40s 额外开销)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model_orchestrator import get_orchestrator

# DeepSeek-R1 专长的微观维度 (Naming/Quantity/CharKnowledge)
R1_SPECIALTY_DIMS = ["Naming", "Quantity", "CharKnowledge"]


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
    primary_sys = (
        "你是网文逻辑审查专家。对以下章节进行全面的逻辑一致性审查。"
        "覆盖: 时间线、因果关系、角色动机、世界观规则、信息一致性。"
        "直接输出审查报告，不要求总结。"
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
    print(f"  [SWAP] 切换到交叉模型 (DeepSeek-R1-0528-8B)...")
    swap_ok = orch.swap_to("logic_cop_candidate", timeout=120)
    if not swap_ok:
        print(f"  [WARN] 交叉模型不可用，仅返回主模型结果")
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
    print(f"  [SWAP] 切回主模型 (Qwen3.5-9B)...")
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


# S3 评审维度 (3 维度, 每个 1-10 分)
REVIEW_DIMENSIONS = {
    "structure": "结构节奏: 爽点分布、钩子位置、章节节奏是否合理",
    "character": "角色一致性: 人设、动机、对话标签是否前后一致",
    "style":    "文笔质量: 句长分布、描写密度、AI痕迹是否可接受",
}

# 维度评分通过阈值
DIMENSION_PASS_THRESHOLD = 7


def _score_dimensions(merged_report: str, chapter_num: int) -> dict:
    """Ask primary model to score the review on 3 dimensions (1-10).

    Args:
        merged_report: merged review report from cross_review()
        chapter_num: chapter number for context

    Returns:
        dict: {"structure": N, "character": N, "style": N, "_raw": raw_response}
    """
    orch = get_orchestrator()
    dim_desc = "\n".join(f"- {k}: {v}" for k, v in REVIEW_DIMENSIONS.items())
    scoring_prompt = (
        f"基于以下评审报告, 对第{chapter_num}章的3个维度打分(1-10分, 10=完美):\n\n"
        f"{dim_desc}\n\n"
        f"## 评审报告:\n{merged_report[:2000]}\n\n"
        f"请严格按以下格式输出 (每行一个维度, 仅输出数字):\n"
        f"structure: N\ncharacter: N\nstyle: N"
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
    lines.append("| 轮次 | structure | character | style | 新增发现 | 判定 |")
    lines.append("|------|-----------|-----------|-------|---------|------|")
    for i, r in enumerate(rounds, 1):
        scores = r.get("scores", {})
        struct = scores.get("structure", "?")
        char = scores.get("character", "?")
        style = scores.get("style", "?")
        has_new = "[OK]" if r.get("has_additions", False) else "无"
        # Determine pass/fail per round
        threshold = DIMENSION_PASS_THRESHOLD
        all_pass = all(
            scores.get(d, 0) >= threshold for d in REVIEW_DIMENSIONS
        )
        verdict = "[PASS]" if all_pass else "[FAIL]"
        lines.append(f"| {i} | {struct} | {char} | {style} | {has_new} | {verdict} |")

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
    print("[INFO] 使用: cross_review(chapter_text, chapter_num)")
    print("[INFO] 自适应循环: adaptive_review_loop(chapter_text, chapter_num)")
    print("[INFO] 8GB约束: 模型顺序切换 ~40s 额外开销")
    print("[DONE]")
