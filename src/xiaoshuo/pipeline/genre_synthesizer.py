#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
genre_synthesizer.py — 向后兼容薄包装
======================================
v8.1: 原有逻辑已拆分至 src/xiaoshuo/pipeline/scoring/ 子模块。
此文件保留作为向后兼容的入口点，所有函数从 scoring/ 重新导出。

拆分结构:
  scoring/vad_analyzer.py       — VAD情感弧 (compute_vad)
  scoring/structure_matcher.py  — 结构模板匹配 (classify_structure)
  scoring/technique_tagger.py   — 技法标签 (compute_tags)
  scoring/commercial_engine.py  — 商业可行性引擎 + Bayesian BMA
  scoring/borda_ranker.py       — Borda排名 + 跨题材竞争力 + 报告生成
"""
from xiaoshuo.pipeline.scoring import (
    # vad_analyzer
    compute_vad,
    # structure_matcher
    classify_structure,
    # technique_tagger
    compute_tags,
    # commercial_engine
    get_default_genre,
    load_genre_novels,
    load_rhythm_data,
    get_firebook_pool,
    percentile_score,
    compute_commercial_score,
    classify_all_sub_genres,
    compute_character_state_trajectory,
    compute_segment_retention,
    compute_cross_genre_competitiveness,
    analyze_single_novel,
    # borda_ranker
    synthesize_genre,
    generate_report,
    evaluate_loocv,
    process_genre,
    main,
)

# 保持原有 __name__ == "__main__" 行为
if __name__ == "__main__":
    main()