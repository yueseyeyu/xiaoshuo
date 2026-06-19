# -*- coding: utf-8 -*-
"""
xiaoshuo.infra.config_manager — 配置管理器（单一事实源缓存）
==========================================================
v7.5: 替代各模块独立 yaml.safe_load() 调用，提供线程安全的全局单例。
- 首次调用时读 config.yaml，后续调用返回缓存
- 支持热重载（reload()）
- 线程安全（double-checked locking）

用法: from xiaoshuo.infra.config_manager import get_config
      cfg = get_config()
      port = cfg["model_orchestration"]["models"]["main_model"]["port"]
"""

import threading
import yaml
from pathlib import Path


_config: dict | None = None
_lock = threading.Lock()
_config_path: Path | None = None


def _get_config_path() -> Path:
    global _config_path
    if _config_path is not None:
        return _config_path
    from xiaoshuo import PROJECT_ROOT
    _config_path = PROJECT_ROOT / "config.yaml"
    return _config_path


def get_config() -> dict:
    """获取全局配置（单例，线程安全）。首次调用自动加载。"""
    global _config
    if _config is not None:
        return _config

    with _lock:
        if _config is not None:
            return _config
        path = _get_config_path()
        with open(path, "r", encoding="utf-8") as f:
            _config = yaml.safe_load(f) or {}
        return _config


def reload_config() -> dict:
    """强制热重载配置（修改 config.yaml 后调用）。"""
    global _config
    with _lock:
        path = _get_config_path()
        with open(path, "r", encoding="utf-8") as f:
            _config = yaml.safe_load(f) or {}
        return _config


def get_config_section(*keys: str, default=None):
    """安全获取嵌套配置段。例如 get_config_section("model_orchestration", "models")。
    如果任何中间 key 不存在，返回 default。
    """
    cfg = get_config()
    for key in keys:
        if not isinstance(cfg, dict):
            return default
        cfg = cfg.get(key)
        if cfg is None:
            return default
    return cfg