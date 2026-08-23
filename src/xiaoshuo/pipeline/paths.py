# -*- coding: utf-8 -*-
"""Context-bound pipeline paths.

Legacy path helpers remain available by name, but they no longer infer a
project, genre, current book, config, or ``PROJECT_ROOT``.  Every returned
path is derived from an explicit activated ExecutionContext and its approved
D-drive stage/run root.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from xiaoshuo.pipeline.provenance import (
    ExecutionContext,
    ProvenanceError,
    execution_root,
    get_execution_context,
)


def stage_run_root(context: ExecutionContext | None = None) -> Path:
    context = context or get_execution_context(True)
    return execution_root(context, create=False)


def _context_path(*parts: str, context: ExecutionContext | None = None) -> Path:
    root = stage_run_root(context)
    path = root.joinpath(*parts)
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ProvenanceError("PATH_ESCAPE", "path escaped the approved stage root") from exc
    return path


def _genre(context: ExecutionContext, genre: Optional[str]) -> str:
    selected = genre if genre is not None else context.genre_identity
    if selected != context.genre_identity:
        raise ProvenanceError("PROFILE_MISMATCH", "genre is profile metadata and must match context")
    return selected


def novels_dir(
    genre: Optional[str] = None,
    *,
    context: ExecutionContext | None = None,
) -> Path:
    context = context or get_execution_context(True)
    return _context_path("data", "raw", "novels", _genre(context, genre), context=context)


def novel_index_path(*, context: ExecutionContext | None = None) -> Path:
    return _context_path("data", "raw", "novel_index.json", context=context)


def books_review_dir(*, context: ExecutionContext | None = None) -> Path:
    return _context_path("books", "review", context=context)


def rhythm_dir(genre: Optional[str] = None, *, context: ExecutionContext | None = None) -> Path:
    context = context or get_execution_context(True)
    return _context_path("data", "processed", _genre(context, genre), "rhythm", context=context)


def llm_score_dir(genre: Optional[str] = None, *, context: ExecutionContext | None = None) -> Path:
    context = context or get_execution_context(True)
    return _context_path("data", "processed", _genre(context, genre), "scores", context=context)


def golden_set_path(genre: Optional[str] = None, *, context: ExecutionContext | None = None) -> Path:
    return llm_score_dir(genre, context=context) / "golden_set.json"


def summaries_dir(genre: Optional[str] = None, *, context: ExecutionContext | None = None) -> Path:
    context = context or get_execution_context(True)
    return _context_path("data", "processed", _genre(context, genre), "summaries", context=context)


def quality_dir(genre: Optional[str] = None, *, context: ExecutionContext | None = None) -> Path:
    context = context or get_execution_context(True)
    return _context_path("data", "processed", _genre(context, genre), "quality", context=context)


def quality_manifest_path(genre: Optional[str] = None, *, context: ExecutionContext | None = None) -> Path:
    return quality_dir(genre, context=context) / "quality_manifest.json"


def feedback_path(genre: Optional[str] = None, *, context: ExecutionContext | None = None) -> Path:
    return quality_dir(genre, context=context) / "feedback.json"


def commercial_scores_path(genre: Optional[str] = None, *, context: ExecutionContext | None = None) -> Path:
    context = context or get_execution_context(True)
    return _context_path(
        "data", "processed", _genre(context, genre), "commercial_scores.json", context=context
    )


def style_profile_dir(*, context: ExecutionContext | None = None) -> Path:
    return _context_path("data", "processed", "style_profile", context=context)


def writing_manual_dir(genre: Optional[str] = None, *, context: ExecutionContext | None = None) -> Path:
    context = context or get_execution_context(True)
    return _context_path(
        "data", "reports", _genre(context, genre), "writing_manuals", context=context
    )


def creative_guidance_dir(genre: Optional[str] = None, *, context: ExecutionContext | None = None) -> Path:
    context = context or get_execution_context(True)
    return _context_path(
        "data", "reports", _genre(context, genre), "creative_guidance", context=context
    )


def deep_diagnosis_dir(genre: Optional[str] = None, *, context: ExecutionContext | None = None) -> Path:
    context = context or get_execution_context(True)
    return _context_path(
        "data", "reports", _genre(context, genre), "deep_diagnosis", context=context
    )


def evaluation_dir(genre: Optional[str] = None, *, context: ExecutionContext | None = None) -> Path:
    context = context or get_execution_context(True)
    return _context_path("data", "reports", _genre(context, genre), "evaluations", context=context)


def synthesis_dir(genre: Optional[str] = None, *, context: ExecutionContext | None = None) -> Path:
    context = context or get_execution_context(True)
    return _context_path("data", "reports", _genre(context, genre), "synthesis", context=context)


def structure_eval_dir(genre: Optional[str] = None, *, context: ExecutionContext | None = None) -> Path:
    context = context or get_execution_context(True)
    return _context_path("data", "reports", _genre(context, genre), "structure_eval", context=context)


def calibration_dir(genre: Optional[str] = None, *, context: ExecutionContext | None = None) -> Path:
    context = context or get_execution_context(True)
    return _context_path("data", "reports", _genre(context, genre), "calibration", context=context)


def canon_dir(*, context: ExecutionContext | None = None) -> Path:
    return _context_path("assets", "canon", context=context)


def contracts_dir(*, context: ExecutionContext | None = None) -> Path:
    return _context_path("data", "contracts", context=context)


def prompts_dir(*, context: ExecutionContext | None = None) -> Path:
    return _context_path("assets", "prompts", context=context)


__all__ = [name for name in globals() if not name.startswith("_")]
