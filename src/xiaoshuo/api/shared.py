# -*- coding: utf-8 -*-
"""shared.py — 路由模块共享的工具函数和全局状态。

从 server.py 抽取，避免路由文件之间循环依赖。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, TYPE_CHECKING

from xiaoshuo import PROJECT_ROOT
from xiaoshuo.infra.config_manager import get_config_section, get_config
from xiaoshuo.api.services.hardware import hardware_state, hardware_lock

if TYPE_CHECKING:
    from xiaoshuo.pipeline.scene_search import SceneSearch
else:
    # 运行时只提供轻量类型占位，避免 get_type_hints 触发重量级导入。
    SceneSearch = Any

# ── 场景搜索引擎缓存 ──

_search_engines: dict[str, SceneSearch] = {}
_search_engines_lock = threading.Lock()


def get_engine(genre: str) -> SceneSearch:
    """获取（或创建）指定题材的场景搜索引擎。"""
    engine = _search_engines.get(genre)
    if engine is not None:
        return engine

    with _search_engines_lock:
        engine = _search_engines.get(genre)
        if engine is None:
            from xiaoshuo.pipeline.scene_search import SceneSearch

            engine = SceneSearch(genre)
            _search_engines[genre] = engine
        return engine


# ── LLM 健康检查 ──

def get_llm_port() -> int:
    """从 config.yaml 读取 LLM 服务端口。"""
    cfg = get_config_section("model_orchestration", default={})
    models = cfg.get("models", {})
    main = models.get("main_model", {})
    port = main.get("port")
    if port:
        return int(port)
    rhythm_cfg = get_config_section("rhythm", default={})
    return int(rhythm_cfg.get("llm_port", 8000))


# LLM 健康状态缓存，避免每次请求都进行网络探测
_llm_health_cache: dict[str, bool | float] = {"value": False, "at": 0.0}
_LLM_HEALTH_TTL = 10.0  # 秒


def llm_server_healthy() -> bool:
    """检查 LLM 服务是否在线（带 10 秒 TTL 缓存）。"""
    now = time.time()
    if now - _llm_health_cache["at"] < _LLM_HEALTH_TTL:
        return bool(_llm_health_cache["value"])
    from xiaoshuo.infra.llm_client import get_main_model_base_url, check_llm_health
    url = get_main_model_base_url()
    healthy = check_llm_health(base_url=url, timeout=1)
    _llm_health_cache["value"] = healthy
    _llm_health_cache["at"] = now
    return healthy


# ── 硬件状态格式化 ──

def format_hardware_response(state: dict) -> dict:
    """将扁平硬件状态转换为前端期望的嵌套百分比结构。"""
    gpu_temp = state.get("gpu_temp") or 0
    gpu_util = state.get("gpu_util") or 0
    vram_used = state.get("vram_used_mb") or 0
    vram_total = state.get("vram_total_mb") or 1
    sys_used = state.get("sys_memory_used_gb") or 0
    sys_total = state.get("sys_memory_total_gb") or 1
    fan_speed = state.get("fan_speed") or 0
    return {
        "gpu": {
            "temp": gpu_temp,
            "util": gpu_util,
            "vram_pct": round(min(vram_used / vram_total * 100, 100), 1) if vram_total else 0,
            "vram_used_mb": vram_used,
            "vram_total_mb": vram_total,
            "fan_speed": fan_speed,
            "vram_processes": state.get("vram_processes", []),
        },
        "cpu": {"pct": state.get("cpu_percent", 0.0)},
        "ram": {"pct": round(min(sys_used / sys_total * 100, 100), 1) if sys_total else 0,
                "used_gb": sys_used, "total_gb": sys_total},
        "updated_at": state.get("updated_at", ""),
        "gpu_available": state.get("gpu_available", False),
    }


def get_hardware_snapshot() -> dict:
    """获取当前硬件快照（线程安全）。"""
    with hardware_lock:
        return format_hardware_response(hardware_state)


# ── JSON 读写工具 ──

def safe_write_json(path: Path, data: dict):
    """安全写入 JSON 文件（原子写入）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)
