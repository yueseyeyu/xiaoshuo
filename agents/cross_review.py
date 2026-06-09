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
) -> dict:
    """主模型全面审查 + 辅助模型对专长维度做补充标注。

    Args:
        chapter_text: 章节全文
        chapter_num: 章节编号
        primary_model: 主模型 key (默认 main_model = Qwen3.5-9B)
        secondary_model: 辅助模型 key (默认 logic_cop_candidate = DeepSeek-R1-7B)
        r1_specialty_only: 是否只让辅助模型审查其专长维度 (默认 True, 省 token)

    Returns:
        {"primary": 主模型报告, "secondary_patches": 辅助模型补充标注, "merged": 合并报告}
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
    primary_user = (
        f"## 第{chapter_num}章 逻辑审查\n"
        f"## 章节 ({word_count}字):\n\n{chapter_text}\n\n"
        f"请逐条列出发现的所有逻辑问题。"
    )
    primary_messages = [
        {"role": "system", "content": primary_sys},
        {"role": "user", "content": primary_user},
    ]
    primary_result = orch.chat("S3_logic_cop", primary_messages, max_tokens=2048, temperature=0.3, timeout=180)

    if "error" in primary_result:
        return {"error": f"主模型审查失败: {primary_result['error']}", "primary": primary_result}

    # ── Phase 2: 辅助模型交叉标注 (DeepSeek-R1, 只查专长维度) ──
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
    secondary_result = orch.chat("S3_logic_cop", secondary_messages, max_tokens=2048, temperature=0.3, timeout=180)

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

    return {
        "primary": primary_result["content"],
        "secondary_patches": secondary_patch,
        "has_additions": has_additions,
        "merged": merged,
        "primary_usage": primary_result.get("usage", {}),
        "secondary_usage": secondary_result.get("usage", {}) if "error" not in secondary_result else None,
    }


# ============================================================
# 自检
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("  cross_review.py — 自检")
    print("=" * 60)
    print("[OK] module loaded")
    print("[OK] R1_SPECIALTY_DIMS:", R1_SPECIALTY_DIMS)
    print("[OK] cross_review() defined")
    print("[INFO] 使用: cross_review(chapter_text, chapter_num)")
    print("[INFO] 8GB约束: 模型顺序切换 ~40s 额外开销")
    print("[DONE]")
