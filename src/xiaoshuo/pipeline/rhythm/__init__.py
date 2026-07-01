# -*- coding: utf-8 -*-
"""
rhythm — 拆书节奏分析子包 (SSOT)
================================
将原 rhythm_analyzer.py (1167 行单体文件) 拆分为 6 个职责单一的模块:
  - chapter_parser:  章节提取 (extract_chapters)
  - patterns:        所有正则模式定义 (SSOT, comparison_engine 也引用)
  - rule_analyzer:   零 LLM 规则分析 (rule_analyze)
  - llm_verifier:    LLM-as-Judge 验证 (llm_verify)
  - cache_manager:   章节级缓存逻辑
  - book_analyzer:   全书编排 + 对比排名 (analyze_book, compare)

公开 API:
  from xiaoshuo.pipeline.rhythm import (
      analyze_book, compare, extract_chapters,
      rule_analyze, llm_verify, _map_llm_response,
  )

向后兼容:
  from xiaoshuo.pipeline.rhythm_analyzer import analyze_book  # 仍可用 (薄 shim)
"""
from __future__ import annotations

# ── 公开 API (与旧 rhythm_analyzer.py 接口完全一致) ──
from xiaoshuo.pipeline.rhythm.chapter_parser import extract_chapters
from xiaoshuo.pipeline.rhythm.rule_analyzer import rule_analyze
from xiaoshuo.pipeline.rhythm.llm_verifier import llm_verify, _map_llm_response
from xiaoshuo.pipeline.rhythm.cache_manager import (
    CACHE_VERSION,
    load_cached_summary,
    check_cache_version,
    save_cache_version,
)
from xiaoshuo.pipeline.rhythm.book_analyzer import analyze_book, compare

__all__ = [
    "analyze_book",
    "compare",
    "extract_chapters",
    "rule_analyze",
    "llm_verify",
    "_map_llm_response",
    "CACHE_VERSION",
    "load_cached_summary",
    "check_cache_version",
    "save_cache_version",
]

__version__ = "3.0.0"
