#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
rhythm_analyzer.py — 薄兼容层 (v3.0)
======================================
原 1123 行单体文件已拆分到 pipeline/rhythm/ 子包。
此文件保留为向后兼容入口，所有逻辑委托到子包模块。

迁移映射:
  rhythm_analyzer.extract_chapters  → rhythm.chapter_parser.extract_chapters
  rhythm_analyzer.rule_analyze      → rhythm.rule_analyzer.rule_analyze
  rhythm_analyzer.llm_verify        → rhythm.llm_verifier.llm_verify
  rhythm_analyzer.analyze_book      → rhythm.book_analyzer.analyze_book
  rhythm_analyzer.compare           → rhythm.book_analyzer.compare
  rhythm_analyzer.PLEASURE_*        → rhythm.patterns.PLEASURE_*
  rhythm_analyzer.CONFLICT_*        → rhythm.patterns.CONFLICT_*

CLI 入口保留不变: python -m xiaoshuo.pipeline.rhythm_analyzer --genre 末世
"""
from __future__ import annotations

import sys
from pathlib import Path

# ── 从子包 re-export 全部公开 API ──
from xiaoshuo.pipeline.rhythm.chapter_parser import extract_chapters, _build_chapters
from xiaoshuo.pipeline.rhythm.rule_analyzer import rule_analyze
from xiaoshuo.pipeline.rhythm.llm_verifier import llm_verify, _map_llm_response, _LLM_KEY_MAP
from xiaoshuo.pipeline.rhythm.cache_manager import (
    CACHE_VERSION as _CACHE_VERSION,
    load_cached_summary as _load_cached_summary,
    check_cache_version,
    save_cache_version,
)
from xiaoshuo.pipeline.rhythm.book_analyzer import analyze_book, compare, _percentile, _get_llm_parallel

# ── re-export 正则模式常量 (comparison_engine 等外部模块依赖) ──
from xiaoshuo.pipeline.rhythm.patterns import (
    PLEASURE_FACE_SLAP, PLEASURE_LEVEL_UP, PLEASURE_CRUSH,
    PLEASURE_COMEBACK, PLEASURE_HIDDEN, PLEASURE_GENERAL,
    PLEASURE_BOND, PLEASURE_COGNITIVE, PLEASURE_SACRIFICE,
    PHYSIO_REACTION,
    PLEASURE_STRATEGY, PLEASURE_RESOURCE, PLEASURE_SOCIAL,
    PLEASURE_BACKFIRE, PLEASURE_TRAP_MASTER, PLEASURE_KNOWLEDGE_GAP,
    PLEASURE_HIDDEN_VALUE, PLEASURE_IDENTITY_REVEAL, PLEASURE_FORESHADOW_PAYOFF,
    PLEASURE_TIMING, PLEASURE_WEIGHTS, PLEASURE_SUBTYPE_NAMES,
    CONFLICT_PSYCHOLOGICAL, CONFLICT_MORAL, CONFLICT_ENVIRONMENT,
    CONFLICT_SOCIAL, CONFLICT_SUSPENSE, CONFLICT_KW_ALL,
    DIALOGUE_PAT, EXCLAM_PAT, NEGATIVE, CLIFFHANGER,
    ANTI_TROPE, EMOTION_HIGH, EMOTION_LOW, EMOTION_BURNOUT,
    RICH_HOOK_PATTERNS, RICH_CONFLICT_PATTERNS, RICH_PLEASURE_PATTERNS,
    RICH_POS_KW, RICH_NEG_KW, RICH_PHYSIO_KW,
)

# ── 模块级常量 (保持向后兼容) ──
from xiaoshuo import PROJECT_ROOT
from xiaoshuo.pipeline.paths import novels_dir as _novels_dir
from xiaoshuo.infra.llm_client import get_llm_port

NOVELS_DIR = _novels_dir()
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
LLAMA_PORT = get_llm_port()
LLAMA_BASE = f"http://127.0.0.1:{LLAMA_PORT}"


# ── CLI 入口 ──
def main():
    """CLI 入口: python -m xiaoshuo.pipeline.rhythm_analyzer --genre 末世"""
    genre = None
    books_filter = None
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--genre" and i < len(sys.argv) - 1:
            genre = sys.argv[i + 1]
        elif arg == "--books" and i < len(sys.argv) - 1:
            books_filter = set(sys.argv[i + 1].split(","))

    if genre:
        genre_dir = NOVELS_DIR / genre
        files = sorted(genre_dir.glob("*.txt")) if genre_dir.exists() else []
    else:
        files = sorted(NOVELS_DIR.glob("**/*.txt"))
    if books_filter:
        files = [f for f in files if f.stem[:40] in books_filter]
    if not files:
        print(f"[FAIL] No .txt files in {'novels/' + genre if genre else NOVELS_DIR}")
        sys.exit(1)

    from xiaoshuo.infra.logging_config import get_logger
    logger = get_logger("rhythm_analyzer")
    logger.info("%d novels in %s, rule-first + LLM verify 5 ch/book",
                len(files), f"genre={genre}" if genre else f"{len(set(f.parent.name for f in files))} genres")
    summaries = []
    for fp in files:
        s = analyze_book(fp)
        summaries.append(s)

    compare(summaries)
    logger.info("[DONE]")


if __name__ == "__main__":
    main()
