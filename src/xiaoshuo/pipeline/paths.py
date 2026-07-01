# -*- coding: utf-8 -*-
"""
paths.py — 路径管理 SSOT (Single Source of Truth)
===================================================
收敛 pipeline 中 10+ 个文件重复定义的路径函数。

用法:
  from xiaoshuo.pipeline.paths import (
      rhythm_dir, llm_score_dir, writing_manual_dir,
      quality_manifest_path, novels_dir, summaries_dir,
      commercial_scores_path, feedback_path, technique_dir,
  )
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from xiaoshuo import PROJECT_ROOT


# ============================================================
# 原始数据路径
# ============================================================

def novels_dir(genre: Optional[str] = None) -> Path:
    """原始小说目录。

    Args:
        genre: 题材名 (如 "末世")，None 返回根目录

    Returns:
        data/raw/novels/{genre} 或 data/raw/novels/
    """
    base = PROJECT_ROOT / "data" / "raw" / "novels"
    return base / genre if genre else base


def novel_index_path() -> Path:
    """小说索引文件路径。"""
    return PROJECT_ROOT / "data" / "raw" / "novel_index.json"


def books_review_dir() -> Path:
    """待审核书籍目录。"""
    return PROJECT_ROOT / "books" / "review"


# ============================================================
# 处理数据路径
# ============================================================

def rhythm_dir(genre: str) -> Path:
    """节奏分析 CSV 输出目录: data/processed/{genre}/rhythm/"""
    return PROJECT_ROOT / "data" / "processed" / genre / "rhythm"


def llm_score_dir(genre: str) -> Path:
    """LLM 评分输出目录: data/processed/{genre}/scores/"""
    return PROJECT_ROOT / "data" / "processed" / genre / "scores"


def summaries_dir(genre: str) -> Path:
    """递归摘要输出目录: data/processed/{genre}/summaries/"""
    return PROJECT_ROOT / "data" / "processed" / genre / "summaries"


def quality_dir(genre: str) -> Path:
    """品质关卡输出目录: data/processed/{genre}/quality/"""
    return PROJECT_ROOT / "data" / "processed" / genre / "quality"


def quality_manifest_path(genre: str) -> Path:
    """品质清单 JSON 路径。"""
    return quality_dir(genre) / "quality_manifest.json"


def feedback_path(genre: str) -> Path:
    """反馈数据 JSON 路径。"""
    return quality_dir(genre) / "feedback.json"


def commercial_scores_path(genre: str) -> Path:
    """商业评分 JSON 路径。"""
    return PROJECT_ROOT / "data" / "processed" / genre / "commercial_scores.json"


def style_profile_dir() -> Path:
    """风格画像输出目录。"""
    return PROJECT_ROOT / "data" / "processed" / "style_profile"


# ============================================================
# 报告路径
# ============================================================

def writing_manual_dir(genre: str) -> Path:
    """写作手册输出目录: data/reports/{genre}/writing_manuals/"""
    return PROJECT_ROOT / "data" / "reports" / genre / "writing_manuals"


def creative_guidance_dir(genre: str) -> Path:
    """创作指导输出目录: data/reports/{genre}/creative_guidance/"""
    return PROJECT_ROOT / "data" / "reports" / genre / "creative_guidance"


def deep_diagnosis_dir(genre: str) -> Path:
    """深度诊断输出目录: data/reports/{genre}/deep_diagnosis/"""
    return PROJECT_ROOT / "data" / "reports" / genre / "deep_diagnosis"


def evaluation_dir(genre: str) -> Path:
    """评估报告输出目录: data/reports/{genre}/evaluations/"""
    return PROJECT_ROOT / "data" / "reports" / genre / "evaluations"


def synthesis_dir(genre: str) -> Path:
    """合成报告输出目录: data/reports/{genre}/synthesis/"""
    return PROJECT_ROOT / "data" / "reports" / genre / "synthesis"


def structure_eval_dir(genre: str) -> Path:
    """结构评估输出目录: data/reports/{genre}/structure_eval/"""
    return PROJECT_ROOT / "data" / "reports" / genre / "structure_eval"


def calibration_dir(genre: str) -> Path:
    """校准报告输出目录: data/reports/{genre}/calibration/"""
    return PROJECT_ROOT / "data" / "reports" / genre / "calibration"


# ============================================================
# 资产路径
# ============================================================

def canon_dir() -> Path:
    """世界规则 (Canon) 目录: assets/canon/"""
    return PROJECT_ROOT / "assets" / "canon"


def contracts_dir() -> Path:
    """合同链数据目录: data/contracts/"""
    return PROJECT_ROOT / "data" / "contracts"


def prompts_dir() -> Path:
    """提示词模板目录: assets/prompts/"""
    return PROJECT_ROOT / "assets" / "prompts"
