# -*- coding: utf-8 -*-
"""routes/reports.py — 报告/指导/技法/骨架/施工单/诊断 路由。"""

from __future__ import annotations

import csv
import logging

from fastapi import APIRouter, Query

from xiaoshuo import PROJECT_ROOT
from xiaoshuo.agents.outline_builder import build_chapter_blueprint
from xiaoshuo.agents.model_orchestrator import get_orchestrator
from xiaoshuo.api.utils import get_available_books, safe_read_json

router = APIRouter()


@router.get("/api/reports/overview")
async def reports_overview(genre: str = Query("末世")):
    """聚合报告页所需的全量数据 — 从已有数据文件直接读取。"""
    base = PROJECT_ROOT / "data" / "processed" / genre
    result = {"genre": genre}

    # 1. technique_cards
    tc_path = base / "quality" / "technique_cards.json"
    if tc_path.exists():
        tc = safe_read_json(tc_path, {})
        result["technique_cards"] = tc.get("cards", [])
    else:
        result["technique_cards"] = []

    # 2. rhythm_audit
    ra_path = base / "quality" / "rhythm_audit.json"
    if ra_path.exists():
        ra = safe_read_json(ra_path, {})
        result["rhythm_audit"] = {
            "total_books": ra.get("total_books", 0),
            "passed": ra.get("passed", 0),
            "warnings": ra.get("warnings", 0),
            "failed": ra.get("failed", 0),
        }
    else:
        result["rhythm_audit"] = {"total_books": 0, "passed": 0, "warnings": 0, "failed": 0}

    # 3. score_audit
    sa_path = base / "quality" / "score_audit.json"
    if sa_path.exists():
        sa = safe_read_json(sa_path, {})
        result["score_audit"] = {
            "total_books": sa.get("total_books", 0),
            "status": sa.get("status", "N/A"),
            "summary": sa.get("summary", {}),
            "issues_count": len(sa.get("issues", [])),
            "outlier_count": len(sa.get("outlier_books", [])),
        }
    else:
        result["score_audit"] = {"total_books": 0, "status": "N/A"}

    # 4. quality_manifest
    qm_path = base / "quality" / "quality_manifest.json"
    if qm_path.exists():
        qm = safe_read_json(qm_path, {})
        result["quality_manifest"] = {
            "approved": len(qm.get("approved", [])),
            "quarantined": len(qm.get("quarantined", [])),
            "failed": len(qm.get("failed", [])),
        }
    else:
        result["quality_manifest"] = {"approved": 0, "quarantined": 0, "failed": 0}

    # 5. 聚合 rhythm CSV 统计
    rhythm_dir = base / "rhythm"
    total_chapters = 0
    total_words = 0
    book_count = 0
    pleasure_dist = {}
    pace_dist = {}
    emotion_dist = {}
    if rhythm_dir.exists():
        for f in rhythm_dir.glob("*.csv"):
            book_count += 1
            try:
                with open(f, encoding="utf-8-sig") as fh:
                    reader = csv.DictReader(fh)
                    for row in reader:
                        total_chapters += 1
                        total_words += int(row.get("wc", 0) or 0)
                        pt = row.get("pleasure_type", "none")
                        pleasure_dist[pt] = pleasure_dist.get(pt, 0) + 1
                        pace = row.get("pace", "unknown")
                        pace_dist[pace] = pace_dist.get(pace, 0) + 1
                        emo = row.get("emotion", "unknown")
                        emotion_dist[emo] = emotion_dist.get(emo, 0) + 1
            except Exception:
                continue

    result["stats"] = {
        "books": book_count,
        "chapters": total_chapters,
        "words": total_words,
    }
    result["distributions"] = {
        "pleasure": pleasure_dist,
        "pace": pace_dist,
        "emotion": emotion_dist,
    }

    return result


@router.get("/api/guidance")
async def guidance(genre: str = Query("末世")):
    """返回综合写作指导"""
    guidance_path = PROJECT_ROOT / "data" / "processed" / genre / "writing_guidance.json"
    if guidance_path.exists():
        return safe_read_json(guidance_path, {"guidance": [], "genre": genre})
    return {"guidance": [], "genre": genre, "error": "no data"}


@router.get("/api/techniques")
async def techniques(genre: str = Query("末世")):
    """返回写作技法库"""
    techniques_path = PROJECT_ROOT / "data" / "processed" / "techniques.json"
    if techniques_path.exists():
        return safe_read_json(techniques_path, {"techniques": [], "genre": genre})
    return {"techniques": [], "genre": genre, "source": "fallback"}


@router.get("/api/skeleton")
async def skeleton(book: str = Query(""), genre: str = Query("末世")):
    """返回章节骨架/大纲"""
    outline_path = PROJECT_ROOT / "assets" / "outline"
    if book and outline_path.exists():
        for f in outline_path.glob("*.md"):
            if book.replace(" ", "_") in f.name:
                return {"book": book, "skeleton": f.read_text(encoding="utf-8"), "format": "markdown"}
    return {"book": book, "skeleton": "", "error": "not found"}


@router.get("/api/blueprint")
async def chapter_blueprint(
    chapter: int = Query(..., ge=1),
    total_chapters: int = Query(..., ge=1),
    genre: str = Query("末世"),
    outline_summary: str = Query(""),
    canon_context: str = Query(""),
    previous_summary: str = Query(""),
    project_id: str = Query("", description="项目ID，传入后自动注入世界推演状态"),
):
    """为指定章节生成结构化施工单 (CHAPTER_BLUEPRINT_SCHEMA)。"""
    try:
        world_state_context = ""
        if project_id:
            from xiaoshuo.agents.creative_context import CreativeContext
            world_state_context = CreativeContext.build_world_simulation_context(
                project_id, chapter
            )

        orch = get_orchestrator()
        blueprint = build_chapter_blueprint(
            orch, chapter, total_chapters, genre,
            outline_summary, canon_context, previous_summary,
            world_state_context=world_state_context,
        )
        return blueprint
    except Exception as e:
        return {"error": str(e), "chapter_num": chapter}


@router.get("/api/diagnosis")
async def diagnosis(book: str = Query(""), chapter: int = Query(1), genre: str = Query("末世")):
    """返回章节诊断信息"""
    if not book:
        return {"book": "", "chapter": 0, "diagnosis": [], "error": "no book specified"}
    return {"book": book, "chapter": chapter, "diagnosis": [], "error": "not implemented"}
