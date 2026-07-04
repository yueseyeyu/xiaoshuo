# -*- coding: utf-8 -*-
"""routes/logs.py — 日志路由。"""

from __future__ import annotations

import time
from collections import OrderedDict

from fastapi import APIRouter, Query
from pydantic import BaseModel

from xiaoshuo.api.app_state import app_state

router = APIRouter()


@router.get("/api/logs")
async def get_logs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    date: str = Query(""),
    level: str = Query(""),
    search: str = Query(""),
    category: str = Query("access"),
):
    records = list(reversed(app_state.log_records))
    if date:
        records = [r for r in records if r.get("time", "").startswith(date)]
    if level:
        records = [r for r in records if (r.get("level") or "").upper() == level.upper()]
    if search:
        records = [r for r in records if search.lower() in (r.get("message") or "").lower()]
    total = len(records)
    entries = records[offset:offset + limit]
    return {"entries": entries, "total": total, "limit": limit, "offset": offset}


@router.get("/api/logs/dates")
async def get_log_dates():
    dates = OrderedDict()
    for r in app_state.log_records:
        d = r.get("time", "")[:10] or "unknown"
        dates[d] = dates.get(d, 0) + 1
    date_list = list(dates.keys())
    return {"dates": date_list, "access": date_list, "operation": date_list}


@router.get("/api/logs/operations")
async def get_log_operations():
    ops = app_state.get_logs_filtered("operation")
    return {"operations": ops[-50:]}


class OperationLogRequest(BaseModel):
    action: str = ""
    detail: str | dict = ""


@router.post("/api/logs/operations")
async def post_log_operations(req: OperationLogRequest):
    app_state.add_log({
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "level": "INFO",
        "message": f"operation: {req.action} - {req.detail}",
    })
    return {"ok": True}
