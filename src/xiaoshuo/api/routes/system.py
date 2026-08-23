# -*- coding: utf-8 -*-
"""routes/system.py — 系统/健康/模型/硬件/配置 路由。"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Query, Body
from fastapi.responses import Response

from xiaoshuo import __version__ as APP_VERSION
from xiaoshuo.infra.config_manager import get_config, get_config_section
from xiaoshuo.infra.user_settings import load_settings, save_settings
from xiaoshuo.agents.model_orchestrator import get_orchestrator
from xiaoshuo.infra.pipeline_state import read_stage
from xiaoshuo.api.app_state import app_state
from xiaoshuo.api.shared import (
    get_engine, get_llm_port, llm_server_healthy, get_hardware_snapshot,
)
from xiaoshuo.api.models import SceneResult, SearchResponse, IndexStats

router = APIRouter()


@router.get("/api/health")
async def health():
    return {"status": "ok", "version": APP_VERSION}


@router.get("/favicon.ico")
async def favicon():
    """返回透明 favicon，避免 404 噪音"""
    return Response(
        content=b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x00\x00\x02\x00\x01\xe5\x27\xde\xfc\x00\x00\x00\x00IEND\xaeB`\x82',
        media_type="image/png",
    )


@router.get("/api/config")
async def get_config_endpoint():
    """返回前端配置（非敏感字段）"""
    cfg = get_config()
    theme_presets = []
    try:
        prototype_cfg = cfg.get("prototype", {}) if isinstance(cfg, dict) else {}
        theme_presets = prototype_cfg.get("theme_presets", []) if isinstance(prototype_cfg, dict) else []
    except Exception:
        pass
    model_cfg = cfg.get("model_orchestration", {}) if isinstance(cfg, dict) else {}
    models = model_cfg.get("models", {}) if isinstance(model_cfg, dict) else {}
    main_model = models.get("main_model", {}) if isinstance(models, dict) else {}
    cloud_model = models.get("cloud_model", {}) if isinstance(models, dict) else {}
    return {
        "version": APP_VERSION,
        "genre": cfg.get("default_genre", "末世"),
        "llm_port": get_llm_port(),
        "mode": cfg.get("mode", "local"),
        "theme_presets": theme_presets,
        "local_model": main_model.get("name", ""),
        "cloud_model": cloud_model.get("name", ""),
        "cloud_provider": cloud_model.get("provider", ""),
    }


@router.get("/api/settings")
async def get_settings_endpoint():
    """返回前端用户设置（JSON 文件持久化）。"""
    return load_settings()


@router.post("/api/settings")
async def save_settings_endpoint(settings: dict = Body(...)):
    """保存前端用户设置。"""
    try:
        save_settings(settings)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/search", response_model=SearchResponse)
def search(
    q: str = Query(..., description="搜索查询"),
    genre: str = Query("末世", description="题材名称"),
    top: int = Query(5, ge=1, le=20, description="返回结果数"),
):
    engine = get_engine(genre)
    raw = engine.search(q, top_k=top)
    if not raw:
        return SearchResponse(query=q, genre=genre, total_scenes=0, results=[], ready=True)
    if "error" in raw[0]:
        return SearchResponse(
            query=q,
            genre=genre,
            total_scenes=0,
            results=[],
            ready=False,
            index_not_ready=raw[0].get("message", "索引未就绪"),
        )

    results = []
    for i, r in enumerate(raw, 1):
        results.append(SceneResult(
            rank=i, similarity=round(r["similarity"], 4),
            book_name=r["book_name"], chapter=r["chapter"],
            scene_index=r["scene_index"], char_count=r["char_count"],
            text_preview=r["text_preview"], emotion=r["emotion"],
            pace=r["pace"], conflict_level=r["conflict_level"],
            pleasure_type=r.get("pleasure_type", ""),
            dominant_sub=r.get("dominant_sub", ""),
            technique_summary=r["technique_summary"],
        ))
    stats = engine.index_stats()
    if stats.get("status") != "ready":
        return SearchResponse(
            query=q,
            genre=genre,
            total_scenes=0,
            results=[],
            ready=False,
            index_not_ready=stats.get("index_not_ready", "索引未就绪"),
        )
    return SearchResponse(
        query=q,
        genre=genre,
        total_scenes=stats.get("total_scenes", 0),
        results=results,
        ready=True,
    )


@router.get("/api/stats", response_model=IndexStats)
def stats(genre: str = Query("末世")):
    engine = get_engine(genre)
    s = engine.index_stats()
    if s.get("status") == "index_not_ready":
        return IndexStats(
            genre=genre,
            total_scenes=0,
            total_books=0,
            ready=False,
            index_not_ready=s.get("index_not_ready", "索引未就绪"),
        )
    return IndexStats(
        genre=genre,
        total_scenes=s.get("total_scenes", 0),
        total_books=s.get("total_books", 0),
        ready=True,
    )


@router.get("/api/progress")
async def get_progress():
    """获取当前拆书进度"""
    running = app_state.analyze_process is not None and app_state.analyze_process.poll() is None
    return {
        "running": running,
        "startup_state": app_state.get_startup_state(),
        "pipeline_stage": read_stage(),
        "llm_healthy": llm_server_healthy(),
    }


@router.get("/api/hardware")
async def get_hardware():
    return get_hardware_snapshot()


@router.get("/api/status")
async def get_status():
    running = app_state.analyze_process is not None and app_state.analyze_process.poll() is None
    hw = get_hardware_snapshot()
    return {
        "running": running,
        "state": app_state.get_startup_state(),
        "llm_healthy": llm_server_healthy(),
        "hardware": hw,
    }


@router.get("/api/model-info")
async def get_model_info():
    """返回主模型详细信息（硬件页展示用）"""
    cfg = get_config_section("model_orchestration", default={})
    main_model = cfg.get("models", {}).get("main_model", {})
    return {
        "name": main_model.get("name", "Unknown"),
        "quant": main_model.get("quant", "unknown"),
        "port": main_model.get("port", 8000),
        "n_ctx": main_model.get("n_ctx", 8192),
        "status": "running" if llm_server_healthy() else "offline",
    }


@router.get("/api/model/status")
async def get_model_status():
    """返回所有模型运行状态"""
    try:
        orch = get_orchestrator()
        return orch.status()
    except Exception as e:
        logging.exception("model/status failed")
        return {"error": str(e), "mode": "unknown", "models": {}}


@router.post("/api/model/start")
async def start_model():
    """启动所有已配置模型"""
    orch = get_orchestrator()
    success = orch.start_all(wait=False)
    return {"success": success, "status": orch.status()}


@router.post("/api/model/stop")
async def stop_model():
    """停止所有运行中的模型"""
    orch = get_orchestrator()
    orch.stop_all()
    return {"success": True, "status": orch.status()}


@router.get("/api/startup-status")
async def get_startup_status():
    return app_state.get_startup_state()
