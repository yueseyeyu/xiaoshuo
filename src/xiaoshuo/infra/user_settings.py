# -*- coding: utf-8 -*-
"""
xiaoshuo.infra.user_settings — 前端用户设置持久化
========================================
- 存储位置：PROJECT_ROOT/data/user_settings.json
- 后端不校验字段，仅做 JSON 持久化，保持前端自由度。
"""
from __future__ import annotations

import json
from pathlib import Path

from xiaoshuo import PROJECT_ROOT


_SETTINGS_PATH: Path = PROJECT_ROOT / "data" / "user_settings.json"


def _ensure_dir() -> None:
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict:
    """加载用户设置，文件不存在或损坏时返回空字典。"""
    if not _SETTINGS_PATH.exists():
        return {}
    try:
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_settings(settings: dict) -> None:
    """保存用户设置。"""
    _ensure_dir()
    with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


def get_setting(key: str, default=None):
    """读取单个设置项。"""
    return load_settings().get(key, default)


def set_setting(key: str, value) -> None:
    """设置单个设置项。"""
    settings = load_settings()
    settings[key] = value
    save_settings(settings)
