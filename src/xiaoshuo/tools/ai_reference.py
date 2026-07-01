#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ai_reference.py — AI版本生成器 (Phase ⑥)
==========================================
调用本地 Qwen3.5-9B 按 Story Bible + 前文上下文生成同一章节(AI版)，
用于后续双文对比。
PlotPilot 接入后可作为备选生成器。

用法: python analysis/ai_reference.py --chapter 5 --genre 末世
"""
import sys
from pathlib import Path
from xiaoshuo import PROJECT_ROOT
from xiaoshuo.infra.llm_client import (
    get_main_model_base_url,
    check_llm_health,
    llm_chat,
)

LLAMA_BASE = get_main_model_base_url()


def generate_ai_version(genre, ch_num, context_text="", story_bible=""):
    """Call LLM to generate an AI version of a chapter for comparison.

    Uses unified llm_chat() from llm_client (SSOT).
    """
    system_msg = (
        f"你是{genre}类网文AI写作助手。任务：基于给定的前文和设定，生成第{ch_num}章的AI版本。"
        "风格要求：有悬念、有爽点、有冲突。注重节奏感和钩子。"
    )
    user_msg = (
        f"前文上下文:\n{context_text[:2000]}\n\n" if context_text else ""
        f"故事设定:\n{story_bible[:1000]}\n\n" if story_bible else ""
        f"请生成第{ch_num}章的内容(约2000-3000字)。只输出正文，不要章节标题和注释。"
    )
    result = llm_chat(
        user_msg,
        system=system_msg,
        max_tokens=3000,
        temperature=0.7,
        timeout=300,
        base_url=LLAMA_BASE,
    )
    return result.strip() if result else None


def main():
    ch_num = 1
    genre = "末世"
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--chapter" and i < len(sys.argv) - 1:
            ch_num = int(sys.argv[i + 1])
        elif arg == "--genre" and i < len(sys.argv) - 1:
            genre = sys.argv[i + 1]

    # Check server via unified client
    if not check_llm_health(LLAMA_BASE):
        print("[FAIL] LLM server not running. Start with: scripts\\start_model.bat")
        return

    print(f"[AI-GEN] 生成{genre}类第{ch_num}章AI版本...")
    result = generate_ai_version(genre, ch_num)
    if result:
        output = PROJECT_ROOT / "outputs" / f"ai_chapter_{ch_num}.txt"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(result, encoding='utf-8')
        print(f"[OK] AI版本: {output} ({len(result)}字)")
    else:
        print("[FAIL] 生成失败")


if __name__ == "__main__":
    main()
