#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
pipeline_state.py — 管线阶段状态持久化（前端实时进度用）
============================================================
SSOT: 所有脚本通过本模块读写 data/pipeline_stage.json，禁止直接操作文件。
"""
import json
import threading
from datetime import datetime
from pathlib import Path

from xiaoshuo import PROJECT_ROOT

PIPELINE_STAGE_FILE = PROJECT_ROOT / "data" / "pipeline_stage.json"
_lock = threading.Lock()


def write_stage(
    stage,
    stage_num=0,
    total=0,
    percent=0,
    eta_seconds=None,
    current_book=None,
    current_task=None,
    completed_books=None,
    status="running",
):
    """Write current pipeline stage with fine-grained progress info.

    Args:
        stage: stage key (e.g. "recursive_summarize")
        stage_num: 1-based stage index
        total: total stage count
        percent: 0-100 intra-stage progress
        eta_seconds: estimated seconds remaining
        current_book: book currently being processed
        current_task: human-readable sub-task (e.g. "L1 章节组 14/33")
        completed_books: list of books finished so far
        status: "running" | "error" | "done"
    """
    data = {
        "stage": stage,
        "stage_num": stage_num,
        "total": total,
        "percent": max(0, min(100, int(percent))),
        "eta_seconds": int(eta_seconds) if eta_seconds is not None else None,
        "current_book": current_book,
        "current_task": current_task,
        "completed_books": list(completed_books or []),
        "status": status,
        "started_at": None,
        "updated_at": datetime.now().isoformat(),
    }

    # Preserve original started_at if present
    with _lock:
        PIPELINE_STAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        if PIPELINE_STAGE_FILE.exists():
            try:
                old = json.loads(PIPELINE_STAGE_FILE.read_text(encoding="utf-8"))
                data["started_at"] = old.get("started_at") or data["updated_at"]
            except (json.JSONDecodeError, OSError):
                data["started_at"] = data["updated_at"]
        else:
            data["started_at"] = data["updated_at"]

        tmp = PIPELINE_STAGE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(PIPELINE_STAGE_FILE)


def mark_error(stage, error_message, stage_num=0, total=0):
    """Mark pipeline as failed with an error message."""
    write_stage(
        stage=stage,
        stage_num=stage_num,
        total=total,
        status="error",
        current_task=f"异常: {error_message}",
    )


def clear_stage():
    """Clear the pipeline stage file (pipeline finished or idle)."""
    with _lock:
        if PIPELINE_STAGE_FILE.exists():
            try:
                PIPELINE_STAGE_FILE.unlink()
            except OSError:
                pass


def read_stage() -> dict | None:
    """Read current pipeline stage, or None if idle/missing."""
    with _lock:
        if not PIPELINE_STAGE_FILE.exists():
            return None
        try:
            return json.loads(PIPELINE_STAGE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
