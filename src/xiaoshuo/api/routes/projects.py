# -*- coding: utf-8 -*-
"""routes/projects.py — 创作项目 CRUD 路由（一书一档）。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from xiaoshuo.api.services.project_service import (
    list_projects, get_project, create_project, update_project, delete_project,
    get_skeleton, update_skeleton,
    get_world, update_world,
    get_characters, update_characters,
    get_factions, update_factions,
    get_chapters, get_chapter, update_chapter,
    get_demo_project, promote_project,
)

router = APIRouter()


@router.get("/api/projects")
async def api_list_projects(include_demo: bool = Query(True)):
    """列出所有创作项目（仅 meta 摘要）。include_demo=false 可过滤示例项目。"""
    return list_projects(include_demo=include_demo)


@router.get("/api/projects/demo")
async def api_get_demo_project():
    """获取示例项目模板（只读，不创建文件）"""
    return get_demo_project()


@router.post("/api/projects")
async def api_create_project(body: dict):
    """创建新项目。body: { meta: { title, genre, ... }, from_demo: bool }"""
    try:
        project = create_project(body)
        return {"ok": True, "project": project}
    except Exception as e:
        raise HTTPException(500, f"Failed to create project: {e}")


@router.get("/api/projects/{project_id}")
async def api_get_project(project_id: str):
    """获取完整项目数据"""
    project = get_project(project_id)
    if project is None:
        raise HTTPException(404, f"Project not found: {project_id}")
    return project


@router.put("/api/projects/{project_id}")
async def api_update_project(project_id: str, body: dict):
    """更新项目元数据"""
    project = update_project(project_id, body)
    if project is None:
        raise HTTPException(404, f"Project not found: {project_id}")
    return {"ok": True, "project": project}


@router.delete("/api/projects/{project_id}")
async def api_delete_project(project_id: str):
    """删除项目"""
    if not delete_project(project_id):
        raise HTTPException(404, f"Project not found: {project_id}")
    return {"ok": True}


@router.post("/api/projects/{project_id}/promote")
async def api_promote_project(project_id: str):
    """将示例项目转为正式项目（清除 is_demo 标记）"""
    project = promote_project(project_id)
    if project is None:
        raise HTTPException(404, f"Project not found or not a demo: {project_id}")
    return {"ok": True, "project": project}


@router.get("/api/projects/{project_id}/skeleton")
async def api_get_skeleton(project_id: str):
    """获取项目粗纲/细纲"""
    skeleton = get_skeleton(project_id)
    if skeleton is None:
        raise HTTPException(404, f"Project not found: {project_id}")
    return skeleton


@router.put("/api/projects/{project_id}/skeleton")
async def api_update_skeleton(project_id: str, body: dict):
    """更新项目粗纲/细纲"""
    skeleton = update_skeleton(project_id, body)
    if skeleton is None:
        raise HTTPException(404, f"Project not found: {project_id}")
    return {"ok": True, "skeleton": skeleton}


@router.get("/api/projects/{project_id}/world")
async def api_get_world(project_id: str):
    """获取项目世界观"""
    world = get_world(project_id)
    if world is None:
        raise HTTPException(404, f"Project not found: {project_id}")
    return world


@router.put("/api/projects/{project_id}/world")
async def api_update_world(project_id: str, body: dict):
    """更新项目世界观"""
    world = update_world(project_id, body)
    if world is None:
        raise HTTPException(404, f"Project not found: {project_id}")
    return {"ok": True, "world": world}


@router.get("/api/projects/{project_id}/characters")
async def api_get_characters(project_id: str):
    """获取项目角色列表"""
    chars = get_characters(project_id)
    if chars is None:
        raise HTTPException(404, f"Project not found: {project_id}")
    return chars


@router.put("/api/projects/{project_id}/characters")
async def api_update_characters(project_id: str, body: dict):
    """更新项目角色列表"""
    chars = update_characters(project_id, body)
    if chars is None:
        raise HTTPException(404, f"Project not found: {project_id}")
    return {"ok": True, "characters": chars}


@router.get("/api/projects/{project_id}/factions")
async def api_get_factions(project_id: str):
    """获取项目势力列表"""
    factions = get_factions(project_id)
    if factions is None:
        raise HTTPException(404, f"Project not found: {project_id}")
    return factions


@router.put("/api/projects/{project_id}/factions")
async def api_update_factions(project_id: str, body: dict):
    """更新项目势力列表"""
    factions = update_factions(project_id, body)
    if factions is None:
        raise HTTPException(404, f"Project not found: {project_id}")
    return {"ok": True, "factions": factions}


@router.get("/api/projects/{project_id}/chapters")
async def api_get_chapters(project_id: str):
    """获取项目章节列表"""
    chapters = get_chapters(project_id)
    if chapters is None:
        raise HTTPException(404, f"Project not found: {project_id}")
    return chapters


@router.get("/api/projects/{project_id}/chapters/{chapter_num}")
async def api_get_chapter(project_id: str, chapter_num: int):
    """获取单章详情"""
    chapter = get_chapter(project_id, chapter_num)
    if chapter is None:
        raise HTTPException(404, f"Chapter not found: {chapter_num}")
    return chapter


@router.put("/api/projects/{project_id}/chapters/{chapter_num}")
async def api_update_chapter(project_id: str, chapter_num: int, body: dict):
    """更新单章"""
    chapter = update_chapter(project_id, chapter_num, body)
    if chapter is None:
        raise HTTPException(404, f"Project not found: {project_id}")
    return {"ok": True, "chapter": chapter}
