# -*- coding: utf-8 -*-
"""
world_state_service.py — 世界推演状态管理服务
================================================
管理项目的世界状态 (WorldState)，包括：
  - 势力动态状态 (FactionState)
  - 角色运行时状态 (CharacterState)
  - 地域信息 (Region)
  - 推演快照 (WorldSnapshot)

数据存储在 project JSON 的 `world_state` 字段中，
与 `factions`/`characters` 字段互补——前者是静态设定，后者是运行时状态。

相关 API 路由见 routes_world.py
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Optional

# 复用 project_service 的路径与读写工具
from xiaoshuo.api.services.project_service import (
    _project_path,
    _safe_read,
    _safe_write,
    get_project,
)


# ── 默认世界状态模板 ──

def _default_world_state() -> dict[str, Any]:
    """生成空白世界状态。"""
    return {
        "chapter": 0,
        "regions": [],
        "factions_state": [],
        "characters_state": [],
        "snapshots": [],
    }


def _now_iso() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _gen_id(prefix: str = "evt") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ── 世界状态 CRUD ──

def get_world_state(project_id: str) -> Optional[dict[str, Any]]:
    """Return persisted world state or a derived read-only compatibility view.

    A derived view remains in memory and is not promoted to formal project state.
    """
    project = get_project(project_id)
    if project is None:
        return None

    ws = project.get("world_state")
    if ws is None:
        # 首次访问：从 factions/characters 推导初始状态
        # Compatibility view only: GET must not promote it to persisted state.
        ws = _init_world_state_from_project(project)
    return ws


def update_world_state(project_id: str, body: dict[str, Any]) -> Optional[dict[str, Any]]:
    """更新世界状态（整体覆盖）。"""
    path = _project_path(project_id)
    if not path.exists():
        return None
    data = _safe_read(path)
    if not data or not data.get("meta"):
        return None

    ws = data.get("world_state", _default_world_state())
    # 增量更新允许的字段
    for key in ("chapter", "regions", "factions_state", "characters_state", "snapshots"):
        if key in body:
            ws[key] = body[key]
    data["world_state"] = ws
    data["meta"]["updated_at"] = _now_iso()
    _safe_write(path, data)
    return ws


# ── 快照管理 ──

def save_snapshot(project_id: str, chapter: int) -> Optional[dict[str, Any]]:
    """保存当前世界状态的快照到 snapshots 列表。

    快照包含：chapter, timestamp, factions_state, characters_state
    """
    ws = get_world_state(project_id)
    if ws is None:
        return None

    snapshots = ws.setdefault("snapshots", [])
    # 保留已有快照中的事件（add_event 在 save_snapshot 之前调用）
    existing_events: list[dict[str, Any]] = []
    for s in snapshots:
        if s.get("chapter") == chapter:
            existing_events = s.get("events", [])
            break

    snapshot = {
        "chapter": chapter,
        "timestamp": _now_iso(),
        "factions_state": json.loads(json.dumps(ws.get("factions_state", []))),
        "characters_state": json.loads(json.dumps(ws.get("characters_state", []))),
        "events": existing_events,
    }

    # 如果已有同章节快照，覆盖它（但保留事件）
    snapshots = [s for s in snapshots if s.get("chapter") != chapter]
    snapshots.append(snapshot)
    snapshots.sort(key=lambda s: s.get("chapter", 0))
    ws["snapshots"] = snapshots
    ws["chapter"] = chapter

    _save_world_state(project_id, ws)
    return snapshot


def get_snapshot(project_id: str, chapter: int) -> Optional[dict[str, Any]]:
    """获取指定章节的快照。"""
    ws = get_world_state(project_id)
    if ws is None:
        return None
    for s in ws.get("snapshots", []):
        if s.get("chapter") == chapter:
            return s
    return None


def get_diff(
    project_id: str, from_chapter: int, to_chapter: int
) -> Optional[dict[str, Any]]:
    """对比两个章节的世界状态差异。

    返回: { from: snapshot, to: snapshot, changes: [...] }
    """
    ws = get_world_state(project_id)
    if ws is None:
        return None

    from_snap = get_snapshot(project_id, from_chapter)
    to_snap = get_snapshot(project_id, to_chapter)

    if from_snap is None or to_snap is None:
        return {
            "from": from_snap,
            "to": to_snap,
            "changes": [],
            "error": f"快照不完整: from={from_chapter}({'有' if from_snap else '无'}), to={to_chapter}({'有' if to_snap else '无'})",
        }

    changes = _compute_diff(from_snap, to_snap)
    return {"from": from_snap, "to": to_snap, "changes": changes}


# ── 势力状态操作 ──

def update_faction_state(
    project_id: str, faction_id: str, updates: dict[str, Any]
) -> Optional[dict[str, Any]]:
    """更新单个势力的运行时状态。"""
    ws = get_world_state(project_id)
    if ws is None:
        return None

    factions_state = ws.setdefault("factions_state", [])
    for fs in factions_state:
        if fs.get("id") == faction_id:
            fs.update(updates)
            _save_world_state(project_id, ws)
            return fs
    # 未找到，创建新条目
    new_state = {"id": faction_id, **updates}
    factions_state.append(new_state)
    _save_world_state(project_id, ws)
    return new_state


def get_faction_state(project_id: str, faction_id: str) -> Optional[dict[str, Any]]:
    """获取单个势力的运行时状态。"""
    ws = get_world_state(project_id)
    if ws is None:
        return None
    for fs in ws.get("factions_state", []):
        if fs.get("id") == faction_id:
            return fs
    return None


# ── 角色状态操作 ──

def update_character_state(
    project_id: str, character_name: str, updates: dict[str, Any]
) -> Optional[dict[str, Any]]:
    """更新单个角色的运行时状态。"""
    ws = get_world_state(project_id)
    if ws is None:
        return None

    chars_state = ws.setdefault("characters_state", [])
    for cs in chars_state:
        if cs.get("name") == character_name:
            cs.update(updates)
            _save_world_state(project_id, ws)
            return cs
    # 未找到，创建新条目
    new_state = {"name": character_name, **updates}
    chars_state.append(new_state)
    _save_world_state(project_id, ws)
    return new_state


def get_character_state(project_id: str, character_name: str) -> Optional[dict[str, Any]]:
    """获取单个角色的运行时状态。"""
    ws = get_world_state(project_id)
    if ws is None:
        return None
    for cs in ws.get("characters_state", []):
        if cs.get("name") == character_name:
            return cs
    return None


# ── 事件记录 ──

def add_event(
    project_id: str, chapter: int, event: dict[str, Any]
) -> Optional[dict[str, Any]]:
    """向当前章节的快照添加推演事件。"""
    ws = get_world_state(project_id)
    if ws is None:
        return None

    snapshots = ws.setdefault("snapshots", [])
    # 找到当前章节的快照，如果没有就创建
    target = None
    for s in snapshots:
        if s.get("chapter") == chapter:
            target = s
            break
    if target is None:
        target = {
            "chapter": chapter,
            "timestamp": _now_iso(),
            "factions_state": json.loads(json.dumps(ws.get("factions_state", []))),
            "characters_state": json.loads(json.dumps(ws.get("characters_state", []))),
            "events": [],
        }
        snapshots.append(target)
        snapshots.sort(key=lambda s: s.get("chapter", 0))

    event_with_id = {
        "id": event.get("id", _gen_id()),
        "chapter": chapter,
        "round": event.get("round", 1),
        "type": event.get("type", "character_action"),
        "actor": event.get("actor", ""),
        "description": event.get("description", ""),
        "effects": event.get("effects", []),
    }
    target.setdefault("events", []).append(event_with_id)
    _save_world_state(project_id, ws)
    return event_with_id


def get_events(project_id: str, chapter: Optional[int] = None) -> Optional[list[dict]]:
    """获取推演事件列表。chapter=None 返回所有章节的事件。"""
    ws = get_world_state(project_id)
    if ws is None:
        return None

    all_events = []
    for snap in ws.get("snapshots", []):
        if chapter is not None and snap.get("chapter") != chapter:
            continue
        all_events.extend(snap.get("events", []))
    return all_events


# ── 内部工具 ──

def _save_world_state(project_id: str, ws: dict[str, Any]) -> bool:
    """将世界状态写回项目 JSON。"""
    path = _project_path(project_id)
    if not path.exists():
        return False
    data = _safe_read(path)
    if not data:
        return False
    data["world_state"] = ws
    data["meta"]["updated_at"] = _now_iso()
    return _safe_write(path, data)


def _init_world_state_from_project(project: dict) -> dict[str, Any]:
    """从项目的 factions/characters 静态数据推导初始世界状态。"""
    ws = _default_world_state()

    # 从 factions 推导初始势力状态
    for fac in project.get("factions", []):
        fac_id = fac.get("id") or fac.get("name", "")
        ws["factions_state"].append({
            "id": fac_id,
            "name": fac.get("name", ""),
            "stability": fac.get("state", {}).get("stability", 0.5),
            "morale": fac.get("state", {}).get("morale", 0.5),
            "treasury": fac.get("state", {}).get("treasury", 0.5),
            "threat_level": fac.get("state", {}).get("threat_level", 0.3),
            "power_level": fac.get("state", {}).get("power_level", 5),
        })

    # 从 characters 推导初始角色状态
    for char in project.get("characters", []):
        ws["characters_state"].append({
            "name": char.get("name", ""),
            "faction_id": char.get("dynamic_state", {}).get("faction_id", ""),
            "health": char.get("dynamic_state", {}).get("health", 1.0),
            "mood": char.get("dynamic_state", {}).get("mood", "normal"),
            "location": char.get("dynamic_state", {}).get("location", "未知"),
            "recent_actions": char.get("dynamic_state", {}).get("recent_actions", []),
        })

    return ws


def _compute_diff(from_snap: dict, to_snap: dict) -> list[dict[str, Any]]:
    """计算两个快照之间的状态变化。"""
    changes: list[dict[str, Any]] = []

    # 对比势力状态
    from_factions = {f["id"]: f for f in from_snap.get("factions_state", []) if "id" in f}
    to_factions = {f["id"]: f for f in to_snap.get("factions_state", []) if "id" in f}

    for fac_id in set(from_factions.keys()) | set(to_factions.keys()):
        f_from = from_factions.get(fac_id, {})
        f_to = to_factions.get(fac_id, {})
        for field in ("stability", "morale", "treasury", "threat_level", "power_level"):
            val_from = f_from.get(field)
            val_to = f_to.get(field)
            if val_from is not None and val_to is not None and val_from != val_to:
                changes.append({
                    "target_type": "faction",
                    "target_id": fac_id,
                    "field": field,
                    "from": val_from,
                    "to": val_to,
                    "delta": round(val_to - val_from, 4),
                })

    # 对比角色状态
    from_chars = {c["name"]: c for c in from_snap.get("characters_state", []) if "name" in c}
    to_chars = {c["name"]: c for c in to_snap.get("characters_state", []) if "name" in c}

    for char_name in set(from_chars.keys()) | set(to_chars.keys()):
        c_from = from_chars.get(char_name, {})
        c_to = to_chars.get(char_name, {})
        for field in ("health",):
            val_from = c_from.get(field)
            val_to = c_to.get(field)
            if val_from is not None and val_to is not None and val_from != val_to:
                changes.append({
                    "target_type": "character",
                    "target_id": char_name,
                    "field": field,
                    "from": val_from,
                    "to": val_to,
                    "delta": round(val_to - val_from, 4),
                })
        # mood/location 变化
        for field in ("mood", "location"):
            val_from = c_from.get(field)
            val_to = c_to.get(field)
            if val_from is not None and val_to is not None and val_from != val_to:
                changes.append({
                    "target_type": "character",
                    "target_id": char_name,
                    "field": field,
                    "from": val_from,
                    "to": val_to,
                    "delta": 0,
                })

    return changes
