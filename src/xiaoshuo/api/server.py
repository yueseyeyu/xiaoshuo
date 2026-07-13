"""番茄小说 AI 创作辅助系统 — 统一 API 服务 v8.6

唯一启动方式 (推荐):
    python -m xiaoshuo.api.server

端口/CORS 默认值来自 config.yaml::api_server；CLI 参数可覆盖 host/port:
    python -m xiaoshuo.api.server --port 8089 --host 0.0.0.0

静态文件由本服务统一挂载 (config.yaml::api_server.static_dir)。
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from pathlib import Path

import uvicorn

# Ensure HF offline mode before any imports
os.environ.setdefault("HF_HOME", str(Path(__file__).resolve().parents[3] / ".hf_cache"))
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from xiaoshuo import __version__ as APP_VERSION, PROJECT_ROOT
from xiaoshuo.infra.config_manager import get_config_section
from xiaoshuo.api.services.hardware import start_hardware_monitor, stop_hardware_monitor
from xiaoshuo.api.app_state import app_state
from xiaoshuo.api.shared import llm_server_healthy

# ── 从 config.yaml 读取 API 配置（SSOT） ──
_API_CFG = get_config_section("api_server", default={}) or {}
_CORS_CFG = _API_CFG.get("cors", {}) if isinstance(_API_CFG, dict) else {}
_DEFAULT_HOST = str(_API_CFG.get("host", "127.0.0.1")) if isinstance(_API_CFG, dict) else "127.0.0.1"
_DEFAULT_PORT = int(_API_CFG.get("port", 8089)) if isinstance(_API_CFG, dict) else 8089
_STATIC_DIR = str(_API_CFG.get("static_dir", "frontend/dist")) if isinstance(_API_CFG, dict) else "frontend/dist"
_STATIC_MOUNT = str(_API_CFG.get("static_mount", "/")) if isinstance(_API_CFG, dict) else "/"

LOG_DIR = PROJECT_ROOT / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


# ====================== FastAPI 生命周期 ======================

@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    start_hardware_monitor()
    from xiaoshuo.api.services import hardware as hw_mod
    logging.info("硬件监控已启动 hardware_running=%s", hw_mod.hardware_running)
    # 启动时预热 LLM 健康缓存
    try:
        await asyncio.wait_for(asyncio.to_thread(llm_server_healthy), timeout=5)
    except Exception:
        pass
    yield
    stop_hardware_monitor()
    logging.info("硬件监控已停止")


app = FastAPI(title="番茄小说 AI 创作辅助系统", version=APP_VERSION, lifespan=lifespan)


# ── 中间件 ──

@app.middleware("http")
async def rate_limit_middleware(request, call_next):
    """本地开发工具，不做限流（保留结构以备将来需要）。"""
    return await call_next(request)


@app.middleware("http")
async def request_logging_middleware(request, call_next):
    """捕获所有 API 请求到日志记录器（供前端日志页面展示）"""
    t0 = time.time()
    response = await call_next(request)
    duration_ms = round((time.time() - t0) * 1000)
    skip_paths = ("/api/logs", "/api/logs/", "/favicon.ico")
    if not any(request.url.path.startswith(p) for p in skip_paths):
        app_state.add_log({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "method": request.method,
            "path": request.url.path + ("?" + request.url.query if request.url.query else ""),
            "status": response.status_code,
            "duration_ms": duration_ms,
            "client_ip": request.client.host if request.client else "unknown",
            "params": dict(request.query_params) if request.query_params else {},
        })
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_CFG.get("allow_origins", [
        "http://localhost:8089",
        "http://127.0.0.1:8089",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]),
    allow_methods=_CORS_CFG.get("allow_methods", ["GET", "POST", "PUT", "DELETE", "OPTIONS"]),
    allow_headers=_CORS_CFG.get("allow_headers", ["*"]),
)


# ====================== 路由挂载 ======================

from xiaoshuo.api.routes.system import router as system_router
from xiaoshuo.api.routes.books import router as books_router
from xiaoshuo.api.routes.reports import router as reports_router
from xiaoshuo.api.routes.writing import router as writing_router
from xiaoshuo.api.routes.projects import router as projects_router
from xiaoshuo.api.routes.logs import router as logs_router
from xiaoshuo.api.routes_creative import router as creative_router
from xiaoshuo.api.routes_world import router as world_router

app.include_router(system_router)
app.include_router(books_router)
app.include_router(reports_router)
app.include_router(writing_router)
app.include_router(projects_router)
app.include_router(logs_router)
app.include_router(creative_router)
app.include_router(world_router)


# ====================== 静态文件服务 ======================

class NoCacheStaticFiles(StaticFiles):
    """禁用浏览器缓存的静态文件服务，确保前端修改能立即生效。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


_FRONTEND_DIR = PROJECT_ROOT / _STATIC_DIR
if _FRONTEND_DIR.exists():
    app.mount(_STATIC_MOUNT, NoCacheStaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")

# /legacy — 旧版 prototype 页面，供 Vue 前端 iframe 代理使用
_LEGACY_DIR = PROJECT_ROOT / "prototype"
if _LEGACY_DIR.exists():
    app.mount("/legacy", NoCacheStaticFiles(directory=str(_LEGACY_DIR), html=True), name="legacy")


# ====================== 启动入口 ======================

def main():
    parser = argparse.ArgumentParser(description="番茄小说 AI 创作辅助系统 — 统一 API 服务")
    parser.add_argument("--port", type=int, default=_DEFAULT_PORT, help=f"端口 (default: {_DEFAULT_PORT})")
    parser.add_argument("--host", default=_DEFAULT_HOST, help=f"监听地址 (default: {_DEFAULT_HOST})")
    parser.add_argument("--reload", action="store_true", help="热重载模式 (开发用)")
    args = parser.parse_args()

    uvicorn.run(
        "xiaoshuo.api.server:app",
        host=args.host,
        port=args.port,
        log_level="info",
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
