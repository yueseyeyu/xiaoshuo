#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
scoring/__init__.py — 商业评分子模块集合
==========================================
从 genre_synthesizer.py 拆分为6个子模块。

重新导出所有公开函数，保持向后兼容:
  from xiaoshuo.pipeline.scoring import compute_vad
  from xiaoshuo.pipeline.scoring import compute_commercial_score
  etc.
"""

# ── vad_analyzer ──
from xiaoshuo.pipeline.scoring.vad_analyzer import compute_vad

# ── structure_matcher ──
from xiaoshuo.pipeline.scoring.structure_matcher import classify_structure

# ── technique_tagger ──
from xiaoshuo.pipeline.scoring.technique_tagger import compute_tags

# ── commercial_engine ──
from xiaoshuo.pipeline.scoring.commercial_engine import (
    # Data loading
    get_default_genre,
    load_genre_novels,
    load_rhythm_data,
    # Fire book pool
    get_firebook_pool,
    # Scoring
    percentile_score,
    compute_commercial_score,
    # Sub-genre
    classify_all_sub_genres,
    # Character & segment analysis
    compute_character_state_trajectory,
    compute_segment_retention,
    compute_cross_genre_competitiveness,
    # Single novel analysis
    analyze_single_novel,
)

# ── borda_ranker ──
from xiaoshuo.pipeline.scoring.borda_ranker import (
    synthesize_genre,
    generate_report,
    evaluate_loocv,
    process_genre,
    main,
)

# ── pro_genre_guide (v11) ──
from xiaoshuo.pipeline.scoring.pro_genre_guide import (
    generate_genre_guide,
    generate_all_genres,
)

__all__ = [
    # vad_analyzer
    "compute_vad",
    # structure_matcher
    "classify_structure",
    # technique_tagger
    "compute_tags",
    # commercial_engine
    "get_default_genre",
    "load_genre_novels",
    "load_rhythm_data",
    "get_firebook_pool",
    "percentile_score",
    "compute_commercial_score",
    "classify_all_sub_genres",
    "compute_character_state_trajectory",
    "compute_segment_retention",
    "compute_cross_genre_competitiveness",
    "analyze_single_novel",
    # borda_ranker
    "synthesize_genre",
    "generate_report",
    "evaluate_loocv",
    "process_genre",
    "main",
    # pro_genre_guide (v11)
    "generate_genre_guide",
    "generate_all_genres",
]