# -*- coding: utf-8 -*-
"""
llm_verifier.py — LLM-as-Judge 章节验证模块
=============================================
对关键章节使用 LLM 验证规则分析结果。
走统一 llm_client (P0-BUG04 修复)。
"""
from __future__ import annotations

import json
import re

from xiaoshuo.infra.logging_config import get_logger

logger = get_logger("rhythm.llm_verifier")

# ── Compact LLM key mapping (t/i/c/e/p → full keys) ──
_LLM_KEY_MAP = {
    "t": "pleasure_type",
    "i": "pleasure_intensity",
    "c": "conflict_level",
    "e": "emotion",
    "p": "pace",
}


def _map_llm_response(llm: dict) -> dict:
    """Map compact LLM keys back to full keys (backward compatible)."""
    return {_LLM_KEY_MAP.get(k, k): v for k, v in llm.items()}


def llm_verify(ch, rule_result):
    """LLM verification for key chapters only. Returns dict or None on failure.

    P0-BUG04 修复: 使用统一 llm_client.llm_chat() 替代裸 urllib.request。
    """
    from xiaoshuo.infra.llm_client import llm_chat

    prompt = (
        "你是网文节奏分析专家。验证以下章节的自动分析结果:\n"
        f"第{ch['num']}章: {ch['title']}  ({ch['wc']}字)\n\n"
        f"{ch['text'][:1500]}\n\n"
        "自动分析:\n"
        f"爽点类型={rule_result['pleasure_type']}, 强度={rule_result['pleasure_intensity']}, "
        f"冲突={rule_result['conflict_level']}, 情绪={rule_result['emotion']}, 节奏={rule_result['pace']}\n\n"
        "输出JSON修正(若自动分析正确则原样输出):\n"
        '{"t":"none/minor/major/climax","i":0-10,'
        '"c":"none/low/medium/high","e":"紧张/轻松/悲壮/爽快/日常/悬疑","p":"fast/slow/medium"}'
    )
    raw = llm_chat(
        prompt,
        max_tokens=200,
        temperature=0.1,
        timeout=60,
    )
    if not raw:
        return None
    m = re.search(r'\{[^}]+\}', raw)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return None
