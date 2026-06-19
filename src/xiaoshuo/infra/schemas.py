# -*- coding: utf-8 -*-
"""
xiaoshuo.infra.schemas — 数据格式校验（Pydantic）
=================================================
v7.5: state.json 和 novel_index.json 的 Schema 校验。
防止手工编辑或写入中断导致的数据损坏。

用法:
    from xiaoshuo.infra.schemas import validate_state, validate_novel_index
    data = json.loads(path.read_text())
    validate_state(data)  # 抛出 ValidationError 如果格式不对
"""

from pathlib import Path
from typing import Any


# ── 轻量校验（不依赖 Pydantic，避免 pip install 负担）───

STATE_SCHEMA = {
    "current_chapter": int,
    "current_stage": str,
    "history": list,
    "total_chapters": int,
}

NOVEL_INDEX_SCHEMA = {
    # novel_index 是 list of dict
    "_list_item": {
        "title": str,
        "genre": str,
        "path": str,
        "size_kb": (int, float),
        "chapters": int,
        "quality": str,
        "added": str,
    }
}


def _validate_type(value: Any, expected_type, path: str = "$") -> list[str]:
    """验证值的类型，返回错误列表。"""
    errors = []
    if isinstance(expected_type, tuple):
        if not isinstance(value, expected_type):
            errors.append(f"{path}: expected {expected_type}, got {type(value).__name__}")
    elif isinstance(expected_type, type):
        if not isinstance(value, expected_type):
            errors.append(f"{path}: expected {expected_type.__name__}, got {type(value).__name__}")
    elif isinstance(expected_type, dict):
        if not isinstance(value, dict):
            errors.append(f"{path}: expected dict, got {type(value).__name__}")
        else:
            for key, vtype in expected_type.items():
                if key.startswith("_"):
                    continue
                if key not in value:
                    errors.append(f"{path}.{key}: missing required field")
                else:
                    errors.extend(_validate_type(value[key], vtype, f"{path}.{key}"))
    return errors


def validate_state(data: dict) -> None:
    """校验 state.json 格式。抛出 ValueError 如果格式不正确。"""
    errors = _validate_type(data, STATE_SCHEMA, "state")
    if errors:
        raise ValueError("state.json 格式错误:\n  " + "\n  ".join(errors))


def validate_novel_index(data: list) -> None:
    """校验 novel_index.json 格式。抛出 ValueError 如果格式不正确。"""
    if not isinstance(data, list):
        raise ValueError(f"novel_index.json: expected list, got {type(data).__name__}")
    schema = NOVEL_INDEX_SCHEMA["_list_item"]
    errors = []
    for i, item in enumerate(data):
        errors.extend(_validate_type(item, schema, f"novel_index[{i}]"))
    if errors:
        raise ValueError("novel_index.json 格式错误:\n  " + "\n  ".join(errors))


def safe_load_json(path: Path, schema: str = "auto") -> dict | list:
    """安全加载 JSON 文件，自动校验格式。

    Args:
        path: JSON 文件路径
        schema: "state" / "novel_index" / "auto"（从文件名推断）

    Returns:
        解析后的 dict 或 list

    Raises:
        ValueError: JSON 解析失败或格式校验失败
    """
    import json
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if schema == "auto":
        name = path.name.lower()
        if "state" in name:
            schema = "state"
        elif "novel_index" in name or "index" in name:
            schema = "novel_index"
        else:
            return data  # 未知 schema，跳过校验

    if schema == "state":
        validate_state(data)
    elif schema == "novel_index":
        validate_novel_index(data)

    return data