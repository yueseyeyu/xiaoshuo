# -*- coding: utf-8 -*-
"""
xiaoshuo.infra.config_manager — 配置管理器（单一事实源缓存）
==========================================================
v7.5: 替代各模块独立 yaml.safe_load() 调用，提供线程安全的全局单例。
v8.8: 自动 mtime 热重载 — config.yaml 修改后无需手动 reload_config()，
      下次 get_config() 自动检测文件变更并重载（零新依赖）。
- 首次调用时读 config.yaml，后续调用返回缓存
- 支持热重载（reload() 手动 / mtime 自动）
- 线程安全（double-checked locking）

用法: from xiaoshuo.infra.config_manager import get_config
      cfg = get_config()
      port = cfg["model_orchestration"]["models"]["main_model"]["port"]
"""

import threading
import yaml
from pathlib import Path


_config: dict | None = None
_config_mtime: float = 0.0  # v8.8: 记录上次加载时的文件 mtime
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
    """获取全局配置（单例，线程安全）。

    v8.8: 自动检测 config.yaml 文件修改（mtime），变更时自动重载。
    无需手动调用 reload_config()，改完 config.yaml 下次调用即生效。
    """
    global _config, _config_mtime
    path = _get_config_path()

    # 快速路径: 检查 mtime 是否变化（无锁，仅读浮点数）
    try:
        current_mtime = path.stat().st_mtime
    except OSError:
        current_mtime = 0.0

    if _config is not None and current_mtime == _config_mtime:
        return _config

    with _lock:
        # double-check: 可能在等锁期间已被其他线程重载
        try:
            current_mtime = path.stat().st_mtime
        except OSError:
            current_mtime = 0.0
        if _config is not None and current_mtime == _config_mtime:
            return _config

        with open(path, "r", encoding="utf-8") as f:
            _config = yaml.safe_load(f) or {}
        _config_mtime = current_mtime
        return _config


def reload_config() -> dict:
    """强制热重载配置（修改 config.yaml 后调用）。

    v8.8: 通常无需手动调用 — get_config() 已自动检测 mtime 变更。
    保留此函数用于: 需要立即重载但不想等待下次 get_config() 的场景。
    """
    global _config, _config_mtime
    with _lock:
        path = _get_config_path()
        with open(path, "r", encoding="utf-8") as f:
            _config = yaml.safe_load(f) or {}
        try:
            _config_mtime = path.stat().st_mtime
        except OSError:
            _config_mtime = 0.0
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


def get_deepseek_config() -> dict | None:
    """Read DeepSeek API config from config.yaml + secrets.yaml (SSOT).
    Returns merged dict with api_key injected, or None if disabled/key missing.
    v11: 提取为公共函数，避免 commercial_engine / pro_genre_guide 重复实现。
    """
    try:
        cfg = get_config()
        apis = cfg.get("model_orchestration", {}).get("models", {}).get("external_api", {})
        ds = apis.get("deepseek", {})
        if not ds.get("enabled"):
            return None
        from xiaoshuo import PROJECT_ROOT
        secrets_path = PROJECT_ROOT / "secrets.yaml"
        api_key = None
        if secrets_path.exists():
            with open(secrets_path, "r", encoding="utf-8") as f:
                secrets = yaml.safe_load(f) or {}
            api_key = secrets.get("deepseek", {}).get("api_key")
        if not api_key:
            return None
        ds = dict(ds)  # shallow copy to avoid mutating cache
        ds["api_key"] = api_key
        # Merge siliconflow backup config
        sf = apis.get("siliconflow", {})
        if sf.get("enabled"):
            sf_key = secrets.get("siliconflow", {}).get("api_key") if secrets_path.exists() else None
            if sf_key and "PLACEHOLDER" not in sf_key:
                sf = dict(sf)
                sf["api_key"] = sf_key
                ds["siliconflow"] = sf
        return ds
    except Exception:
        return None