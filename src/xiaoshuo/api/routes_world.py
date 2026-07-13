# -*- coding: utf-8 -*-
"""
routes_world.py — 世界推演状态 API 路由
==========================================
为前端世界推演页提供以下端点:

  GET  /api/projects/{pid}/world_state          获取世界状态
  PUT  /api/projects/{pid}/world_state          更新世界状态
  POST /api/projects/{pid}/world_state/snapshot  保存快照
  GET  /api/projects/{pid}/world_state/diff      对比快照差异
  GET  /api/projects/{pid}/world_state/events    获取推演事件
  POST /api/projects/{pid}/world_state/events    添加推演事件
  GET  /api/projects/{pid}/factions/{fid}/state  获取势力状态
  PUT  /api/projects/{pid}/factions/{fid}/state  更新势力状态
  GET  /api/projects/{pid}/characters/{name}/state  获取角色状态
  PUT  /api/projects/{pid}/characters/{name}/state  更新角色状态

所有路由挂载到 /api 前缀下（与 server.py 中 /api/projects 路由同前缀）。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from xiaoshuo.api.services import world_state_service as wss
from xiaoshuo.api.services.simulation_engine import run_simulation

router = APIRouter(prefix="/api", tags=["world-simulation"])
logger = logging.getLogger("routes_world")


# ============================================================
# Pydantic 请求模型
# ============================================================

class WorldStateUpdate(BaseModel):
    chapter: int | None = None
    regions: list[dict] | None = None
    factions_state: list[dict] | None = None
    characters_state: list[dict] | None = None
    snapshots: list[dict] | None = None


class FactionStateUpdate(BaseModel):
    stability: float | None = None
    morale: float | None = None
    treasury: float | None = None
    threat_level: float | None = None
    power_level: float | None = None


class CharacterStateUpdate(BaseModel):
    faction_id: str | None = None
    health: float | None = None
    mood: str | None = None
    location: str | None = None
    recent_actions: list[str] | None = None


class SnapshotRequest(BaseModel):
    chapter: int


class EventRequest(BaseModel):
    round: int = 1
    type: str = "character_action"
    actor: str = ""
    description: str = ""
    effects: list[dict] = []


# ============================================================
# 世界状态 — 整体读写
# ============================================================

@router.get("/projects/{project_id}/world_state")
async def get_world_state(project_id: str):
    """获取项目的世界状态。

    首次访问时自动从 factions/characters 推导初始状态。
    """
    ws = wss.get_world_state(project_id)
    if ws is None:
        raise HTTPException(status_code=404, detail=f"项目 {project_id} 不存在")
    return ws


@router.put("/projects/{project_id}/world_state")
async def update_world_state(project_id: str, body: WorldStateUpdate):
    """更新世界状态（增量合并，仅更新提供的字段）。"""
    ws = wss.update_world_state(project_id, body.model_dump(exclude_none=True))
    if ws is None:
        raise HTTPException(status_code=404, detail=f"项目 {project_id} 不存在")
    return {"ok": True, "world_state": ws}


# ============================================================
# 快照管理
# ============================================================

@router.post("/projects/{project_id}/world_state/snapshot")
async def save_snapshot(project_id: str, body: SnapshotRequest):
    """保存当前世界状态的快照到指定章节。"""
    snap = wss.save_snapshot(project_id, body.chapter)
    if snap is None:
        raise HTTPException(status_code=404, detail=f"项目 {project_id} 不存在")
    return {"ok": True, "snapshot": snap}


@router.get("/projects/{project_id}/world_state/diff")
async def get_diff(
    project_id: str,
    from_chapter: int = Query(..., alias="from"),
    to_chapter: int = Query(..., alias="to"),
):
    """对比两个章节的世界状态差异。"""
    result = wss.get_diff(project_id, from_chapter, to_chapter)
    if result is None:
        raise HTTPException(status_code=404, detail=f"项目 {project_id} 不存在")
    return result


# ============================================================
# 推演事件
# ============================================================

@router.get("/projects/{project_id}/world_state/events")
async def get_events(
    project_id: str,
    chapter: int | None = Query(None, description="过滤指定章节，不传则返回全部"),
):
    """获取推演事件列表。"""
    events = wss.get_events(project_id, chapter)
    if events is None:
        raise HTTPException(status_code=404, detail=f"项目 {project_id} 不存在")
    return {"events": events}


@router.post("/projects/{project_id}/world_state/events")
async def add_event(project_id: str, body: EventRequest):
    """添加一条推演事件到当前章节快照。"""
    # 从 world_state 获取当前章节
    ws = wss.get_world_state(project_id)
    if ws is None:
        raise HTTPException(status_code=404, detail=f"项目 {project_id} 不存在")
    chapter = ws.get("chapter", 0)

    event = wss.add_event(project_id, chapter, body.model_dump())
    if event is None:
        raise HTTPException(status_code=500, detail="添加事件失败")
    return {"ok": True, "event": event}


# ============================================================
# 势力状态 — 单个读写
# ============================================================

@router.get("/projects/{project_id}/factions/{faction_id}/state")
async def get_faction_state(project_id: str, faction_id: str):
    """获取单个势力的运行时状态。"""
    state = wss.get_faction_state(project_id, faction_id)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail=f"项目 {project_id} 或势力 {faction_id} 状态不存在",
        )
    return state


@router.put("/projects/{project_id}/factions/{faction_id}/state")
async def update_faction_state(
    project_id: str, faction_id: str, body: FactionStateUpdate
):
    """更新单个势力的运行时状态。"""
    state = wss.update_faction_state(
        project_id, faction_id, body.model_dump(exclude_none=True)
    )
    if state is None:
        raise HTTPException(status_code=404, detail=f"项目 {project_id} 不存在")
    return {"ok": True, "state": state}


# ============================================================
# 角色状态 — 单个读写
# ============================================================

@router.get("/projects/{project_id}/characters/{character_name}/state")
async def get_character_state(project_id: str, character_name: str):
    """获取单个角色的运行时状态。"""
    state = wss.get_character_state(project_id, character_name)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail=f"项目 {project_id} 或角色 {character_name} 状态不存在",
        )
    return state


@router.put("/projects/{project_id}/characters/{character_name}/state")
async def update_character_state(
    project_id: str, character_name: str, body: CharacterStateUpdate
):
    """更新单个角色的运行时状态。"""
    state = wss.update_character_state(
        project_id, character_name, body.model_dump(exclude_none=True)
    )
    if state is None:
        raise HTTPException(status_code=404, detail=f"项目 {project_id} 不存在")
    return {"ok": True, "state": state}


# ============================================================
# 世界推演 — SSE 流式推演
# ============================================================

class SimulationRequest(BaseModel):
    from_chapter: int = 0
    to_chapter: int = 5


@router.post("/projects/{project_id}/simulate")
async def start_simulation(project_id: str, body: SimulationRequest):
    """启动世界推演，返回 SSE 流。

    前端使用 fetch + ReadableStream 监听推演事件。
    """
    # 验证项目存在
    ws = wss.get_world_state(project_id)
    if ws is None:
        raise HTTPException(status_code=404, detail=f"项目 {project_id} 不存在")

    async def event_stream():
        async for chunk in run_simulation(
            project_id, body.from_chapter, body.to_chapter
        ):
            yield chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================
# 推演 → 大纲导出 (v8.6 WSE 深化)
# ============================================================

class ExportOutlineRequest(BaseModel):
    from_chapter: int = 0
    to_chapter: int = 5
    genre: str = "末世"


@router.post("/projects/{project_id}/world_state/export_outline")
async def export_outline(project_id: str, body: ExportOutlineRequest):
    """将推演事件转化为结构化章节大纲草稿。

    读取指定章节范围内的推演事件 + 世界状态快照，
    通过 CreativeContext 构建推演上下文，生成大纲草稿。

    返回:
        {
            "project_id": str,
            "from_chapter": int,
            "to_chapter": int,
            "world_context": str,           # 推演状态文本
            "chapter_drafts": [             # 每章大纲草稿
                {
                    "chapter": int,
                    "events": [...],        # 该章推演事件
                    "faction_summary": str,  # 势力状态摘要
                    "character_summary": str,# 角色状态摘要
                    "suggested_outline": str # 建议的大纲要点
                }
            ]
        }
    """
    ws = wss.get_world_state(project_id)
    if ws is None:
        raise HTTPException(status_code=404, detail=f"项目 {project_id} 不存在")

    # 构建 world_state 上下文
    from xiaoshuo.agents.creative_context import CreativeContext
    world_context = CreativeContext.build_world_simulation_context(
        project_id, body.to_chapter
    )

    # 按章节聚合推演事件
    chapter_drafts: list[dict] = []
    for ch in range(body.from_chapter + 1, body.to_chapter + 1):
        # 获取该章事件
        events = wss.get_events(project_id, ch) or []

        # 从快照提取势力/角色状态
        snap = wss.get_snapshot(project_id, ch)
        fac_summary = ""
        char_summary = ""
        if snap:
            fac_states = snap.get("factions_state", [])
            char_states = snap.get("characters_state", [])
            if fac_states:
                fac_parts = []
                for fs in fac_states:
                    name = fs.get("name", fs.get("id", ""))
                    stab = fs.get("stability", 0.5)
                    threat = fs.get("threat_level", 0.3)
                    fac_parts.append(f"{name}(稳定{stab:.0%}/威胁{threat:.0%})")
                fac_summary = "; ".join(fac_parts)
            if char_states:
                char_parts = []
                for cs in char_states:
                    name = cs.get("name", "")
                    health = cs.get("health", 1.0)
                    mood = cs.get("mood", "normal")
                    char_parts.append(f"{name}(HP{health:.0%}/{mood})")
                char_summary = "; ".join(char_parts)

        # 生成建议大纲要点 (基于事件类型)
        suggested_points: list[str] = []
        for ev in events:
            ev_type = ev.get("type", "")
            ev_desc = ev.get("description", "")
            if ev_type == "conflict_detected":
                suggested_points.append(f"【冲突】{ev_desc}")
            elif ev_type == "faction_decision":
                suggested_points.append(f"【势力动态】{ev_desc}")
            elif ev_type == "character_action":
                suggested_points.append(f"【角色行动】{ev_desc}")
        if not suggested_points:
            suggested_points.append("【日常推进】本章无重大推演事件，可安排伏笔或角色发展")

        chapter_drafts.append({
            "chapter": ch,
            "events": events,
            "faction_summary": fac_summary,
            "character_summary": char_summary,
            "suggested_outline": "\n".join(suggested_points),
        })

    return {
        "project_id": project_id,
        "from_chapter": body.from_chapter,
        "to_chapter": body.to_chapter,
        "world_context": world_context,
        "chapter_drafts": chapter_drafts,
    }
