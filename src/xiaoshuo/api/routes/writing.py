# -*- coding: utf-8 -*-
"""routes/writing.py — 写作辅助路由（指令/风格/合规/任务）。"""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from xiaoshuo import PROJECT_ROOT
from xiaoshuo.agents.cross_review import scan_fingerprints, estimate_ai_rate
from xiaoshuo.api.utils import get_available_books, get_chapter_instructions
from xiaoshuo.api.shared import safe_write_json
from xiaoshuo.api.models import (
    StyleCalibrateRequest, StyleCalibrateResponse,
    StyleRulesResponse, ComplianceScanResponse,
    TaskCreateRequest, TaskItem,
)
from xiaoshuo.api.utils import safe_read_json

router = APIRouter()


# ── 写作指令 ──

@router.get("/api/instructions")
async def instructions(book: str = Query(""), ch: int = Query(1), genre: str = Query("末世")):
    if not book:
        books = get_available_books(PROJECT_ROOT, genre)
        return {"books": [b.get("title", "") for b in books], "genre": genre}
    return get_chapter_instructions(PROJECT_ROOT, book, ch, genre)


# ── 风格校准 ──

@router.post("/api/style/calibrate", response_model=StyleCalibrateResponse)
def style_calibrate(req: StyleCalibrateRequest):
    """Temporary compatibility freeze for the unsafe direct Canon write path."""
    raise HTTPException(
        status_code=409,
        detail={
            "code": "DIRECT_CANON_WRITE_DISABLED",
            "message": "待安全变更提案流程接入",
        },
    )


@router.get("/api/style/rules", response_model=StyleRulesResponse)
def style_rules(version: str = Query("")):
    """获取已累积的 S3 风格规则列表"""
    # Kept local so the frozen POST path never constructs the Canon adapter.
    from xiaoshuo.pipeline.canon.extractor import CanonExtractor

    try:
        extractor = CanonExtractor()
        data = extractor._load_style_rules()
        rules = data.get("s3_review_rules", [])
        return StyleRulesResponse(ok=True, rule_count=len(rules), rules=rules, version=version)
    except Exception as e:
        return StyleRulesResponse(ok=False, rule_count=0, rules=[], version=version, error=str(e))


# ── 平台合规预检 ──

@router.get("/api/compliance/scan", response_model=ComplianceScanResponse)
def compliance_scan(text: str = Query(..., min_length=1)):
    """扫描文本中的 AI 指纹词，输出风险等级和详情。"""
    try:
        fingerprint_result = scan_fingerprints(text, exempt_dialogue=True)
        ai_rate_result = estimate_ai_rate(text, fingerprint_result)
        return ComplianceScanResponse(
            ok=True,
            risk_level=fingerprint_result["risk_level"],
            total_count=fingerprint_result["total_count"],
            high_risk_count=fingerprint_result["high_risk_count"],
            by_category=fingerprint_result["by_category"],
            high_risk_hits=fingerprint_result["high_risk_hits"],
            ai_rate=ai_rate_result["ai_rate_pct"],
            ai_rate_level=ai_rate_result["risk_level"],
            ai_rate_passed=ai_rate_result["passed"],
            ai_rate_recommendation=ai_rate_result["recommendation"],
        )
    except Exception as e:
        return ComplianceScanResponse(
            ok=False, risk_level="error", total_count=0, high_risk_count=0,
            by_category={}, high_risk_hits=[], error=str(e),
        )


# ── 任务管理 ──

@router.get("/api/tasks")
async def get_tasks():
    tasks_path = PROJECT_ROOT / "data" / "tasks.json"
    return safe_read_json(tasks_path, {"tasks": []})


@router.post("/api/tasks")
async def create_task(req: TaskCreateRequest):
    """创建新的拆书分析任务"""
    tasks_path = PROJECT_ROOT / "data" / "tasks.json"
    tasks = safe_read_json(tasks_path, {"tasks": []})
    new_task = TaskItem(
        id=str(int(time.time() * 1000)),
        name=req.name,
        type=req.type,
        genre=req.genre,
        books=req.books,
        status="pending",
        progress=0,
        created_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        updated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
    ).dict()
    tasks.setdefault("tasks", []).append(new_task)
    safe_write_json(tasks_path, tasks)
    return {"ok": True, "task": new_task}


@router.get("/api/task")
async def get_task(id: str = Query(...)):
    tasks_path = PROJECT_ROOT / "data" / "tasks.json"
    tasks = safe_read_json(tasks_path, {"tasks": []})
    for t in tasks.get("tasks", []):
        if str(t.get("id", "")) == id:
            return t
    raise HTTPException(404, f"Task not found: {id}")
