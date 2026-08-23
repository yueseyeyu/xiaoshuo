"""Project service — 创作作品（一书一档）数据管理。

每个项目存为 data/projects/{id}.json，包含：
  - meta: 标题/作者/题材/卷数/章节数等元数据
  - skeleton: 粗纲/细纲
  - world: 世界观
  - characters: 角色列表
  - factions: 势力列表
  - chapters: 章节列表
"""

import json
import os
import time
import uuid
from pathlib import Path
from typing import Optional

from xiaoshuo import PROJECT_ROOT
from xiaoshuo.infra.config_manager import get_config

CURRENT_SCHEMA_VERSION = "1.2.0"


class ProjectStorageError(RuntimeError):
    '''Raised when an existing project cannot be persisted.'''

    code = "PROJECT_STORAGE_WRITE_FAILED"

    def __init__(self, project_id: str, operation: str):
        self.project_id = project_id
        self.operation = operation
        super().__init__(f'Project storage write failed: {operation} ({project_id})')


class ProjectStorageReadError(RuntimeError):
    """已有项目文件无法读取或解析时抛出。"""

    code = "PROJECT_STORAGE_READ_FAILED"

    def __init__(self, path: Path, reason: str):
        self.path = path
        self.reason = reason
        super().__init__(f"Project storage read failed: {path.name} ({reason})")

_cfg = get_config()
_projects_dir = _cfg.get("paths", {}).get("projects_dir", "data/projects")
_PROJECT_DIR = PROJECT_ROOT / _projects_dir if not Path(_projects_dir).is_absolute() else Path(_projects_dir)
_PROJECT_DIR.mkdir(parents=True, exist_ok=True)


def _generate_id() -> str:
    """生成项目唯一 ID：uuid 短码 + 时间戳后缀，避免毫秒碰撞。"""
    return uuid.uuid4().hex[:8] + str(int(time.time() * 1000))[-8:]


def _project_path(project_id: str) -> Path:
    return _PROJECT_DIR / f"{project_id}.json"


def _safe_read(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProjectStorageReadError(path, str(exc)) from exc


def _safe_write(path: Path, data: dict) -> bool:
    try:
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.replace(path)
        return True
    except Exception:
        return False


def _write_or_raise(path: Path, data: dict, project_id: str, operation: str) -> None:
    if not _safe_write(path, data):
        raise ProjectStorageError(project_id, operation)


def _new_project_stub(meta: dict) -> dict:
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    return {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "is_demo": False,
        "meta": {
            "title": meta.get("title", "未命名作品"),
            "author": meta.get("author", "作者"),
            "genre": meta.get("genre", "末世"),
            "volumes_count": meta.get("volumes_count", 5),
            "total_chapters": meta.get("total_chapters", 300),
            "written_chapters": meta.get("written_chapters", 0),
            "summary": meta.get("summary", ""),
            "created_at": now,
            "updated_at": now,
        },
        "skeleton": {"volumes": [], "chapters": []},
        "world": {"core": "", "powers": ""},
        "characters": [],
        "factions": [],
        "chapters": [],
        "world_state": None,
    }


DEMO_PROJECT = {
    "schema_version": CURRENT_SCHEMA_VERSION,
    "is_demo": True,
    "meta": {
        "title": "《末日模拟器》",
        "author": "作者",
        "genre": "末世",
        "volumes_count": 5,
        "total_chapters": 300,
        "written_chapters": 127,
        "summary": "主角在高考考场遭遇末日降临，觉醒模拟器能力，在72小时轮回中带领团队生存。",
    },
    "skeleton": {
        "volumes": [
            {"title": "第一卷", "range": "1-60章", "subtitle": "灾变初临",
             "summary": "主角在高考考场遭遇末日降临，被迫在混乱中保护同学并觉醒模拟器能力。",
             "tags": ["觉醒", "逃亡", "校园"]},
            {"title": "第二卷", "range": "61-120章", "subtitle": "废墟秩序",
             "summary": "幸存者小队在废弃商场建立据点，主角通过模拟预判危险，逐步确立领导地位。",
             "tags": ["据点", "团体", "资源"]},
            {"title": "第三卷", "range": "121-180章", "subtitle": "暗流涌动",
             "summary": "外界势力觊觎据点资源，内部出现分歧，主角面临信任与利益的考验。",
             "tags": ["内讧", "权谋", "冲突"]},
            {"title": "第四卷", "range": "181-240章", "subtitle": "进化之路",
             "summary": "病毒二次变异，人类与怪物同步进化，主角团队被迫向更危险的城市核心进发。",
             "tags": ["进化", "副本", "Boss"]},
            {"title": "第五卷", "range": "241-300章", "subtitle": "新纪元",
             "summary": "真相揭露，末日竟是高等文明的筛选试验，主角必须做出拯救还是逃离的抉择。",
             "tags": ["真相", "决战", "终章"]},
        ],
        "chapters": [
            {"title": "第一章", "goal": "建立末日氛围", "conflict": "主角与监考老师对峙",
             "result": "觉醒模拟器，逃离考场", "scenes": ["考场混乱", "首次模拟", "能力觉醒"]},
            {"title": "第二章", "goal": "展示世界规则", "conflict": "如何保护同学突围",
             "result": "组建临时小队", "scenes": ["丧尸出现", "路线选择", "救人"]},
            {"title": "第三章", "goal": "引入外部压力", "conflict": "食物与信任危机",
             "result": "占领小卖部作为据点", "scenes": ["物资搜寻", "冲突爆发", "决策"]},
        ],
    },
    "world": {
        "core": "末日模拟器：全球进入72小时轮回，每次死亡保留记忆碎片。",
        "powers": "模拟点、天赋树、死亡惩罚、情报熵。",
    },
    "characters": [
        {"name": "林默", "role": "主角", "identity": "前高考生，觉醒模拟器能力",
         "personality": "冷静果断，有强烈的责任感",
         "ability": "末日模拟器 · 4小时预演",
         "desc": "冷静果断，拥有末日模拟器，能在梦中预演未来4小时。",
         "dynamic_state": {"health": 0.9, "mood": "confident", "location": "废弃商场据点", "recent_actions": ["击退尸潮", "建立据点"]}},
        {"name": "苏婉", "role": "女主", "identity": "医学生",
         "personality": "理性温和，在绝境中仍坚持人道主义",
         "ability": "急救 · 毒理分析",
         "desc": "医学生，擅长急救与毒理分析，团队医疗核心。",
         "dynamic_state": {"health": 1.0, "mood": "normal", "location": "据点医疗室", "recent_actions": ["研发抗体", "救治伤员"]}},
        {"name": "老K", "role": "导师", "identity": "退役特种兵",
         "personality": "沉稳老练，寡言少语",
         "ability": "战术指挥 · 精准射击",
         "desc": "退役特种兵，传授生存技巧，是主角初期的武力依靠。",
         "dynamic_state": {"health": 0.7, "mood": "weary", "location": "据点哨塔", "recent_actions": ["巡逻侦察", "训练新人"]}},
    ],
    "factions": [
        {"id": "fac_heit", "name": "黑塔", "type": "神秘组织", "desc": "神秘组织，掌控轮回核心。",
         "state": {"stability": 0.9, "morale": 0.8, "treasury": 0.85, "threat_level": 0.4, "power_level": 9}},
        {"id": "fac_ref", "name": "避难所", "type": "官方组织", "desc": "官方幸存者聚集地。",
         "state": {"stability": 0.6, "morale": 0.55, "treasury": 0.5, "threat_level": 0.6, "power_level": 6}},
        {"id": "fac_scav", "name": "拾荒者", "type": "帮派", "desc": "游离于秩序之外的幸存者。",
         "state": {"stability": 0.35, "morale": 0.45, "treasury": 0.2, "threat_level": 0.8, "power_level": 3}},
        {"id": "fac_clean", "name": "清理人", "type": "军事组织", "desc": "黑塔下属的执行部队。",
         "state": {"stability": 0.75, "morale": 0.7, "treasury": 0.6, "threat_level": 0.5, "power_level": 7}},
    ],
    "chapters": [
        {"num": 1, "title": "考场异变", "status": "written", "word_count": 2100},
        {"num": 2, "title": "模拟觉醒", "status": "written", "word_count": 1850},
        {"num": 3, "title": "临时小队", "status": "written", "word_count": 2300},
        {"num": 127, "title": "暴雨前的寂静", "status": "writing", "word_count": 1240},
    ],
}


# ── CRUD ──

def list_projects(include_demo: bool = True) -> dict:
    """列出所有项目（仅返回 meta 摘要）。"""
    projects = []
    for p in _PROJECT_DIR.glob("*.json"):
        data = _safe_read(p)
        if not data or not data.get("meta"):
            continue
        if not include_demo and data.get("is_demo"):
            continue
        meta = data["meta"]
        projects.append({
            "id": data.get("id", p.stem),
            "title": meta.get("title", "未命名作品"),
            "author": meta.get("author", ""),
            "genre": meta.get("genre", ""),
            "volumes_count": meta.get("volumes_count", 0),
            "total_chapters": meta.get("total_chapters", 0),
            "written_chapters": meta.get("written_chapters", 0),
            "is_demo": data.get("is_demo", False),
            "updated_at": meta.get("updated_at", ""),
        })
    projects.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return {"projects": projects}


def get_project(project_id: str) -> Optional[dict]:
    """获取完整项目数据。"""
    path = _project_path(project_id)
    return _safe_read(path)


def create_project(body: dict) -> Optional[dict]:
    """创建新项目。支持 from_demo: true 从示例模板复制。"""
    project_id = _generate_id()
    if body.get("from_demo"):
        data = json.loads(json.dumps(DEMO_PROJECT))
        data["is_demo"] = True
        data["id"] = project_id
        if body.get("meta"):
            for k, v in body["meta"].items():
                data["meta"][k] = v
    else:
        data = _new_project_stub(body.get("meta", {}))
        data["id"] = project_id

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    data["meta"]["created_at"] = now
    data["meta"]["updated_at"] = now

    if not _safe_write(_project_path(project_id), data):
        return None
    data["id"] = project_id
    return data


def update_project(project_id: str, body: dict) -> Optional[dict]:
    """更新项目元数据。"""
    path = _project_path(project_id)
    data = _safe_read(path)
    if not data or not data.get("meta"):
        return None
    updates = body.get("meta", {})
    for k, v in updates.items():
        data["meta"][k] = v
    data["meta"]["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if not _safe_write(path, data):
        return None
    return data


def delete_project(project_id: str) -> bool:
    """删除项目。"""
    path = _project_path(project_id)
    if not path.exists():
        return False
    try:
        path.unlink()
        return True
    except Exception:
        return False


def promote_project(project_id: str) -> Optional[dict]:
    """将 demo 项目转为正式项目。"""
    path = _project_path(project_id)
    data = _safe_read(path)
    if not data:
        return None
    data["is_demo"] = False
    data["meta"]["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if not _safe_write(path, data):
        return None
    return data


# ── 粗纲/细纲 ──

def get_skeleton(project_id: str) -> Optional[dict]:
    """获取粗纲/细纲。"""
    project = get_project(project_id)
    if project is None:
        return None
    return project.get("skeleton", {"volumes": [], "chapters": []})


def update_skeleton(project_id: str, body: dict) -> Optional[dict]:
    """更新粗纲/细纲。"""
    path = _project_path(project_id)
    data = _safe_read(path)
    if not data or not data.get("meta"):
        return None
    data["skeleton"] = {
        "volumes": body.get("volumes", []),
        "chapters": body.get("chapters", []),
    }
    data["meta"]["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _write_or_raise(path, data, project_id, "update_skeleton")
    return data["skeleton"]


# ── 世界观 ──

def get_world(project_id: str) -> Optional[dict]:
    """获取世界观。"""
    project = get_project(project_id)
    if project is None:
        return None
    return project.get("world", {"core": "", "powers": ""})


def update_world(project_id: str, body: dict) -> Optional[dict]:
    """更新世界观。"""
    path = _project_path(project_id)
    data = _safe_read(path)
    if not data or not data.get("meta"):
        return None
    data["world"] = {
        "core": body.get("core", ""),
        "powers": body.get("powers", ""),
    }
    data["meta"]["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _write_or_raise(path, data, project_id, "update_world")
    return data["world"]


# ── 角色 ──

def get_characters(project_id: str) -> Optional[dict]:
    """获取角色列表。"""
    project = get_project(project_id)
    if project is None:
        return None
    return {"characters": project.get("characters", [])}


def update_characters(project_id: str, body: dict) -> Optional[dict]:
    """更新角色列表。"""
    path = _project_path(project_id)
    data = _safe_read(path)
    if not data or not data.get("meta"):
        return None
    data["characters"] = body.get("characters", [])
    data["meta"]["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _write_or_raise(path, data, project_id, "update_characters")
    return {"characters": data["characters"]}


# ── 势力 ──

def get_factions(project_id: str) -> Optional[dict]:
    """获取势力列表。"""
    project = get_project(project_id)
    if project is None:
        return None
    return {"factions": project.get("factions", [])}


def update_factions(project_id: str, body: dict) -> Optional[dict]:
    """更新势力列表。"""
    path = _project_path(project_id)
    data = _safe_read(path)
    if not data or not data.get("meta"):
        return None
    data["factions"] = body.get("factions", [])
    data["meta"]["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _write_or_raise(path, data, project_id, "update_factions")
    return {"factions": data["factions"]}


# ── 章节 ──

def get_chapters(project_id: str) -> Optional[dict]:
    """获取章节列表（仅 meta，不含正文）。"""
    project = get_project(project_id)
    if project is None:
        return None
    return {"chapters": project.get("chapters", [])}


def get_chapter(project_id: str, chapter_num: int) -> Optional[dict]:
    """获取单章详情。"""
    project = get_project(project_id)
    if project is None:
        return None
    for ch in project.get("chapters", []):
        if ch.get("num") == chapter_num:
            return ch
    return None


def update_chapter(project_id: str, chapter_num: int, body: dict) -> Optional[dict]:
    """更新单章（如果不存在则追加）。"""
    path = _project_path(project_id)
    data = _safe_read(path)
    if not data or not data.get("meta"):
        return None
    chapters = data.setdefault("chapters", [])
    found = False
    for ch in chapters:
        if ch.get("num") == chapter_num:
            ch.update(body)
            found = True
            break
    if not found:
        new_ch = {"num": chapter_num}
        new_ch.update(body)
        chapters.append(new_ch)
        chapters.sort(key=lambda x: x.get("num", 0))
    data["meta"]["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _write_or_raise(path, data, project_id, "update_chapter")
    return get_chapter(project_id, chapter_num)


def get_demo_project() -> dict:
    """获取示例项目模板（只读，不创建文件）。"""
    return json.loads(json.dumps(DEMO_PROJECT))
