"""番茄小说 AI 创作辅助系统 — 统一 API 服务 v8.4

唯一启动方式 (推荐):
    python -m xiaoshuo.api.server

端口/CORS 默认值来自 config.yaml::api_server；CLI 参数可覆盖 host/port:
    python -m xiaoshuo.api.server --port 8089 --host 0.0.0.0

静态文件由本服务统一挂载 (config.yaml::api_server.static_dir)。
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import subprocess
import sys
import time
import urllib.request
import psutil
from collections import OrderedDict
from pathlib import Path

import uvicorn

# Ensure HF offline mode before any imports
os.environ.setdefault("HF_HOME", str(Path(__file__).resolve().parents[3] / ".hf_cache"))
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from xiaoshuo import __version__ as APP_VERSION
from xiaoshuo.pipeline.scene_search import SceneSearch
from xiaoshuo.pipeline.canon.extractor import CanonExtractor
from xiaoshuo.agents.cross_review import scan_fingerprints, estimate_ai_rate
from xiaoshuo.agents.outline_builder import build_chapter_blueprint
from xiaoshuo.agents.model_orchestrator import get_orchestrator
from xiaoshuo.infra.config_manager import get_config_section, get_config
from xiaoshuo.infra.pipeline_state import clear_stage, mark_error

# v8.1: 模块化拆分 — 模型、工具函数、硬件服务
from xiaoshuo.api.models import (
    SceneResult, SearchResponse, IndexStats,
    StyleRuleItem, StyleCalibrateRequest, StyleCalibrateResponse,
    StyleRulesResponse, FingerprintHit, ComplianceScanResponse,
    TaskCreateRequest, TaskItem, TasksResponse,
)
from xiaoshuo.api.utils import (
    get_available_books, get_genre_counts, get_chapter_instructions,
    safe_read_json, safe_write_json,
)
from xiaoshuo.api.services.hardware import (
    hardware_state, hardware_lock,
    start_hardware_monitor, stop_hardware_monitor, get_hardware_snapshot,
)
from xiaoshuo.api.services.project_service import (
    list_projects, get_project, create_project, update_project, delete_project,
    get_skeleton, update_skeleton,
    get_world, update_world,
    get_characters, update_characters,
    get_factions, update_factions,
    get_chapters, get_chapter, update_chapter,
    get_demo_project, promote_project,
)
from xiaoshuo.api.app_state import app_state

# ── 从 config.yaml 读取 API 配置（SSOT） ──
_API_CFG = get_config_section("api_server", default={}) or {}
_CORS_CFG = _API_CFG.get("cors", {}) if isinstance(_API_CFG, dict) else {}
_DEFAULT_HOST = str(_API_CFG.get("host", "127.0.0.1")) if isinstance(_API_CFG, dict) else "127.0.0.1"
_DEFAULT_PORT = int(_API_CFG.get("port", 8089)) if isinstance(_API_CFG, dict) else 8089
_STATIC_DIR = str(_API_CFG.get("static_dir", "prototype")) if isinstance(_API_CFG, dict) else "prototype"
_STATIC_MOUNT = str(_API_CFG.get("static_mount", "/")) if isinstance(_API_CFG, dict) else "/"

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOG_DIR = PROJECT_ROOT / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ====================== 全局状态 ======================

_search_engines: dict[str, SceneSearch] = {}

# ── LLM 服务管理 ──

def _get_llm_port() -> int:
    cfg = get_config_section("model_orchestration", default={})
    models = cfg.get("models", {})
    main = models.get("main_model", {})
    port = main.get("port")
    if port:
        return int(port)
    rhythm_cfg = get_config_section("rhythm", default={})
    return int(rhythm_cfg.get("llm_port", 8000))


# LLM 健康状态缓存，避免每次请求都进行网络探测导致 4s 延迟
_llm_health_cache: dict[str, bool | float] = {"value": False, "at": 0.0}
_LLM_HEALTH_TTL = 10.0  # 秒


def _llm_server_healthy() -> bool:
    now = time.time()
    if now - _llm_health_cache["at"] < _LLM_HEALTH_TTL:
        return bool(_llm_health_cache["value"])
    # v8.4: 使用统一 llm_client，支持 thinking-tag 清理、重试、统一超时
    from xiaoshuo.infra.llm_client import get_main_model_base_url, check_llm_health
    url = get_main_model_base_url()
    healthy = check_llm_health(base_url=url, timeout=1)
    _llm_health_cache["value"] = healthy
    _llm_health_cache["at"] = now
    return healthy


def _get_engine(genre: str) -> SceneSearch:
    if genre not in _search_engines:
        _search_engines[genre] = SceneSearch(genre)
    return _search_engines[genre]


# ====================== FastAPI 生命周期 ======================

@asynccontextmanager
async def lifespan(app: FastAPI):
    start_hardware_monitor()
    from xiaoshuo.api.services import hardware as hw_mod
    logging.info("硬件监控已启动 hardware_running=%s", hw_mod.hardware_running)
    # 启动时预热 LLM 健康缓存，避免首次 /api/progress 请求被探测延迟阻塞
    import asyncio
    try:
        await asyncio.wait_for(asyncio.to_thread(_llm_server_healthy), timeout=5)
    except Exception:
        pass
    yield
    stop_hardware_monitor()
    logging.info("硬件监控已停止")


app = FastAPI(title="番茄小说 AI 创作辅助系统", version=APP_VERSION, lifespan=lifespan)

# ── API 限流中间件（v8.1） ──
_rate_limit_store: dict[str, list[float]] = {}
_RATE_LIMIT_WINDOW = 60  # 秒
_RATE_LIMIT_MAX = 120    # 每窗口最大请求数

@app.middleware("http")
async def rate_limit_middleware(request, call_next):
    from fastapi.responses import JSONResponse
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    window_start = now - _RATE_LIMIT_WINDOW
    # 清理过期记录
    _rate_limit_store[client_ip] = [t for t in _rate_limit_store.get(client_ip, []) if t > window_start]
    if len(_rate_limit_store.setdefault(client_ip, [])) >= _RATE_LIMIT_MAX:
        return JSONResponse(
            status_code=429,
            content={"detail": "Too Many Requests", "retry_after": _RATE_LIMIT_WINDOW},
        )
    _rate_limit_store[client_ip].append(now)
    return await call_next(request)


@app.middleware("http")
async def request_logging_middleware(request, call_next):
    """捕获所有 API 请求到日志记录器（供前端日志页面展示）"""
    t0 = time.time()
    response = await call_next(request)
    duration_ms = round((time.time() - t0) * 1000)
    # 跳过日志相关端点和静态文件，避免日志刷屏
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
    ]),
    allow_methods=_CORS_CFG.get("allow_methods", ["GET", "POST", "OPTIONS"]),
    allow_headers=_CORS_CFG.get("allow_headers", ["*"]),
)

# ====================== 核心 API 路由 ======================

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": APP_VERSION}


@app.get("/favicon.ico")
async def favicon():
    """返回透明 favicon，避免 404 噪音"""
    from fastapi.responses import Response
    # 1x1 透明 PNG
    return Response(content=b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x00\x00\x02\x00\x01\xe5\x27\xde\xfc\x00\x00\x00\x00IEND\xaeB`\x82', media_type="image/png")


@app.get("/api/config")
async def get_config_endpoint():
    """返回前端配置（非敏感字段）"""
    cfg = get_config()
    # 透传前端品牌色预设 (从 prototype.theme_presets 读)
    theme_presets = []
    try:
        prototype_cfg = cfg.get("prototype", {}) if isinstance(cfg, dict) else {}
        theme_presets = prototype_cfg.get("theme_presets", []) if isinstance(prototype_cfg, dict) else []
    except Exception:
        pass
    return {
        "version": APP_VERSION,
        "genre": cfg.get("default_genre", "末世"),
        "llm_port": _get_llm_port(),
        "mode": cfg.get("mode", "local"),
        "theme_presets": theme_presets,
    }


# ── 场景搜索 ──

@app.get("/api/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., description="搜索查询"),
    genre: str = Query("末世", description="题材名称"),
    top: int = Query(5, ge=1, le=20, description="返回结果数"),
):
    engine = _get_engine(genre)
    raw = engine.search(q, top_k=top)
    if not raw:
        return SearchResponse(query=q, genre=genre, total_scenes=0, results=[])
    if "error" in raw[0]:
        return SearchResponse(query=q, genre=genre, total_scenes=0, results=[])

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
    return SearchResponse(query=q, genre=genre, total_scenes=stats.get("total_scenes", 0), results=results)


@app.get("/api/stats", response_model=IndexStats)
async def stats(genre: str = Query("末世")):
    engine = _get_engine(genre)
    s = engine.index_stats()
    return IndexStats(genre=genre, total_scenes=s.get("total_scenes", 0), total_books=s.get("total_books", 0))


# ── 风格校准 ──

@app.post("/api/style/calibrate", response_model=StyleCalibrateResponse)
def style_calibrate(req: StyleCalibrateRequest):
    """从 S3 评审报告文本中提取风格规则并合并到 style_rules.md"""
    try:
        extractor = CanonExtractor()
        result = extractor.extract_style_rules_from_review(
            s3_review_text=req.text, chapter_num=req.chapter_id, genre="")
        rules = result["data"].get("s3_review_rules", [])
        return StyleCalibrateResponse(
            ok=True, rule_count=len(rules), rules=rules,
            new_findings=result.get("new_findings", 0), version=req.version)
    except Exception as e:
        return StyleCalibrateResponse(
            ok=False, rule_count=0, rules=[], new_findings=0, version=req.version, error=str(e))


@app.get("/api/style/rules", response_model=StyleRulesResponse)
def style_rules(version: str = Query("")):
    """获取已累积的 S3 风格规则列表"""
    try:
        extractor = CanonExtractor()
        data = extractor._load_style_rules()
        rules = data.get("s3_review_rules", [])
        return StyleRulesResponse(ok=True, rule_count=len(rules), rules=rules, version=version)
    except Exception as e:
        return StyleRulesResponse(ok=False, rule_count=0, rules=[], version=version, error=str(e))


# v8.0: 平台合规预检 (S6 AI指纹词扫描 + v8.1 AI率预估)
@app.get("/api/compliance/scan", response_model=ComplianceScanResponse)
def compliance_scan(text: str = Query(..., min_length=1)):
    """扫描文本中的 AI 指纹词，输出风险等级和详情。
    对话中的指纹词默认豁免 (exempt_dialogue=true)。
    v8.1: 新增 AI 率预估 (基于指纹词密度)，对标番茄 30% 红线。
    """
    try:
        fingerprint_result = scan_fingerprints(text, exempt_dialogue=True)
        ai_rate_result = estimate_ai_rate(text, fingerprint_result)
        return ComplianceScanResponse(
            ok=True,
            risk_level=fingerprint_result["risk_level"],
            total_count=fingerprint_result["total_count"],
            high_risk_count=fingerprint_result["high_risk_count"],
            by_category=fingerprint_result["by_category"],
            high_risk_hits=fingerprint_result["high_risk_hits"],
            # v8.1: AI 率预估
            ai_rate=ai_rate_result["ai_rate_pct"],
            ai_rate_level=ai_rate_result["risk_level"],
            ai_rate_passed=ai_rate_result["passed"],
            ai_rate_recommendation=ai_rate_result["recommendation"],
        )
    except Exception as e:
        return ComplianceScanResponse(
            ok=False, risk_level="error", total_count=0, high_risk_count=0,
            by_category={}, high_risk_hits=[], error=str(e),
        )


# ── 书籍列表 & 拆书数据 ──

@app.get("/api/books")
async def get_books(genre: str = Query("末世")):
    books = get_available_books(PROJECT_ROOT, genre)
    genres, counts = get_genre_counts(PROJECT_ROOT)
    return {
        "books": books,
        "count": len(books),
        "genre": genre,
        "genres": genres,
        "counts": counts,
    }


@app.get("/api/disassembly/books")
async def disassembly_books(genre: str = Query("末世")):
    books = get_available_books(PROJECT_ROOT, genre)
    return {
        "books": [
            {
                "key": b["file"].replace("rhythm_", "").replace(".csv", ""),
                "title": b["title"],
                "genre": b["genre"],
                "summary": {"chapters": 0, "total_words": 0},
            }
            for b in books
        ]
    }


@app.get("/api/disassembly/book")
async def disassembly_book(name: str = Query(...), genre: str = Query("末世")):
    safe_name = name.replace(" ", "_")
    csv_path = PROJECT_ROOT / "data" / "processed" / genre / "rhythm" / f"rhythm_{safe_name}.csv"
    if not csv_path.exists():
        raise HTTPException(404, f"Book not found: {name}")
    rows = []
    with open(csv_path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return {"book": name, "genre": genre, "chapters": rows, "total": len(rows)}


# ── 写作指令 ──

@app.get("/api/instructions")
async def instructions(book: str = Query(""), ch: int = Query(1), genre: str = Query("末世")):
    if not book:
        books = get_available_books(PROJECT_ROOT, genre)
        return {"books": [b.get("title", "") for b in books], "genre": genre}
    return get_chapter_instructions(PROJECT_ROOT, book, ch, genre)


@app.get("/api/reports/overview")
async def reports_overview(genre: str = Query("末世")):
    """聚合报告页所需的全量数据 — 从已有数据文件直接读取，不依赖管线生成。

    返回:
      - stats: 拆书总量统计 (books/chapters/words)
      - rhythm_audit: 节奏审计摘要
      - score_audit: 评分审计摘要
      - quality_manifest: 质量门控摘要
      - technique_cards: 技法卡片列表
      - distributions: 节奏/爽点/情绪分布 (从 rhythm CSV 聚合)
    """
    import csv as csv_mod  # kept for clarity; csv also available at module level
    base = PROJECT_ROOT / "data" / "processed" / genre
    result = {"genre": genre}

    # 1. technique_cards
    tc_path = base / "quality" / "technique_cards.json"
    if tc_path.exists():
        tc = safe_read_json(tc_path, {})
        result["technique_cards"] = tc.get("cards", [])
    else:
        result["technique_cards"] = []

    # 2. rhythm_audit
    ra_path = base / "quality" / "rhythm_audit.json"
    if ra_path.exists():
        ra = safe_read_json(ra_path, {})
        result["rhythm_audit"] = {
            "total_books": ra.get("total_books", 0),
            "passed": ra.get("passed", 0),
            "warnings": ra.get("warnings", 0),
            "failed": ra.get("failed", 0),
        }
    else:
        result["rhythm_audit"] = {"total_books": 0, "passed": 0, "warnings": 0, "failed": 0}

    # 3. score_audit
    sa_path = base / "quality" / "score_audit.json"
    if sa_path.exists():
        sa = safe_read_json(sa_path, {})
        result["score_audit"] = {
            "total_books": sa.get("total_books", 0),
            "status": sa.get("status", "N/A"),
            "summary": sa.get("summary", {}),
            "issues_count": len(sa.get("issues", [])),
            "outlier_count": len(sa.get("outlier_books", [])),
        }
    else:
        result["score_audit"] = {"total_books": 0, "status": "N/A"}

    # 4. quality_manifest
    qm_path = base / "quality" / "quality_manifest.json"
    if qm_path.exists():
        qm = safe_read_json(qm_path, {})
        result["quality_manifest"] = {
            "approved": len(qm.get("approved", [])),
            "quarantined": len(qm.get("quarantined", [])),
            "failed": len(qm.get("failed", [])),
        }
    else:
        result["quality_manifest"] = {"approved": 0, "quarantined": 0, "failed": 0}

    # 5. 聚合 rhythm CSV 统计
    rhythm_dir = base / "rhythm"
    total_chapters = 0
    total_words = 0
    book_count = 0
    pleasure_dist = {}
    pace_dist = {}
    emotion_dist = {}
    if rhythm_dir.exists():
        for f in rhythm_dir.glob("*.csv"):
            book_count += 1
            try:
                with open(f, encoding="utf-8-sig") as fh:
                    reader = csv_mod.DictReader(fh)
                    for row in reader:
                        total_chapters += 1
                        total_words += int(row.get("wc", 0) or 0)
                        pt = row.get("pleasure_type", "none")
                        pleasure_dist[pt] = pleasure_dist.get(pt, 0) + 1
                        pace = row.get("pace", "unknown")
                        pace_dist[pace] = pace_dist.get(pace, 0) + 1
                        emo = row.get("emotion", "unknown")
                        emotion_dist[emo] = emotion_dist.get(emo, 0) + 1
            except Exception:
                continue

    result["stats"] = {
        "books": book_count,
        "chapters": total_chapters,
        "words": total_words,
    }
    result["distributions"] = {
        "pleasure": pleasure_dist,
        "pace": pace_dist,
        "emotion": emotion_dist,
    }

    return result


@app.get("/api/guidance")
async def guidance(genre: str = Query("末世")):
    """返回综合写作指导"""
    guidance_path = PROJECT_ROOT / "data" / "processed" / genre / "writing_guidance.json"
    if guidance_path.exists():
        return safe_read_json(guidance_path, {"guidance": [], "genre": genre})
    return {"guidance": [], "genre": genre, "error": "no data"}


@app.get("/api/techniques")
async def techniques(genre: str = Query("末世")):
    """返回写作技法库"""
    techniques_path = PROJECT_ROOT / "data" / "processed" / "techniques.json"
    if techniques_path.exists():
        return safe_read_json(techniques_path, {"techniques": [], "genre": genre})
    # Fallback: 从 scene_search 提取
    return {"techniques": [], "genre": genre, "source": "fallback"}


@app.get("/api/skeleton")
async def skeleton(book: str = Query(""), genre: str = Query("末世")):
    """返回章节骨架/大纲"""
    outline_path = PROJECT_ROOT / "assets" / "outline"
    if book and outline_path.exists():
        for f in outline_path.glob("*.md"):
            if book.replace(" ", "_") in f.name:
                return {"book": book, "skeleton": f.read_text(encoding="utf-8"), "format": "markdown"}
    return {"book": book, "skeleton": "", "error": "not found"}


# v8.0: 章节施工单 (S4 大纲细纲打通方案)
@app.get("/api/blueprint")
async def chapter_blueprint(
    chapter: int = Query(..., ge=1),
    total_chapters: int = Query(..., ge=1),
    genre: str = Query("末世"),
    outline_summary: str = Query(""),
    canon_context: str = Query(""),
    previous_summary: str = Query(""),
):
    """为指定章节生成结构化施工单 (CHAPTER_BLUEPRINT_SCHEMA)。
    返回 JSON, 作者可直接用于 Part C 手写。
    """
    try:
        orch = get_orchestrator()
        blueprint = build_chapter_blueprint(
            orch, chapter, total_chapters, genre,
            outline_summary, canon_context, previous_summary,
        )
        return blueprint
    except Exception as e:
        return {"error": str(e), "chapter_num": chapter}


@app.get("/api/diagnosis")
async def diagnosis(book: str = Query(""), chapter: int = Query(1), genre: str = Query("末世")):
    """返回章节诊断信息"""
    if not book:
        return {"book": "", "chapter": 0, "diagnosis": [], "error": "no book specified"}
    return {"book": book, "chapter": chapter, "diagnosis": [], "error": "not implemented"}


# ── 任务管理 ──

@app.get("/api/tasks")
async def get_tasks():
    tasks_path = PROJECT_ROOT / "data" / "tasks.json"
    return safe_read_json(tasks_path, {"tasks": []})


@app.post("/api/tasks")
async def create_task(req: TaskCreateRequest):
    """创建新的拆书分析任务"""
    tasks_path = PROJECT_ROOT / "data" / "tasks.json"
    tasks = safe_read_json(tasks_path, {"tasks": []})
    new_task = TaskItem(
        id=str(int(time.time() * 1000)),
        name=req.name,
        type=req.type,
        genre=req.genre,
        books=req.books,
        status="pending",
        progress=0,
        created_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        updated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
    ).dict()
    tasks.setdefault("tasks", []).append(new_task)
    safe_write_json(tasks_path, tasks)
    return {"ok": True, "task": new_task}


@app.get("/api/task")
async def get_task(id: str = Query(...)):
    tasks_path = PROJECT_ROOT / "data" / "tasks.json"
    tasks = safe_read_json(tasks_path, {"tasks": []})
    for t in tasks.get("tasks", []):
        if str(t.get("id", "")) == id:
            return t
    raise HTTPException(404, f"Task not found: {id}")


# ── 进度监控（从 progress_server 合并） ──

@app.get("/api/progress")
async def get_progress():
    """获取当前拆书进度"""
    running = app_state.analyze_process is not None and app_state.analyze_process.poll() is None
    return {
        "running": running,
        "startup_state": app_state.get_startup_state(),
        "llm_healthy": _llm_server_healthy(),
    }


def safe_write_json(path: Path, data: dict):
    """安全写入 JSON 文件"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _format_hardware_response(state: dict) -> dict:
    """将扁平硬件状态转换为前端期望的嵌套百分比结构"""
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
        },
        "cpu": {"pct": state.get("cpu_percent", 0.0)},
        "ram": {"pct": round(min(sys_used / sys_total * 100, 100), 1) if sys_total else 0,
                "used_gb": sys_used, "total_gb": sys_total},
        "updated_at": state.get("updated_at", ""),
        "gpu_available": state.get("gpu_available", False),
    }


@app.get("/api/hardware")
async def get_hardware():
    with hardware_lock:
        return _format_hardware_response(hardware_state)


@app.get("/api/status")
async def get_status():
    running = app_state.analyze_process is not None and app_state.analyze_process.poll() is None
    with hardware_lock:
        hw = _format_hardware_response(hardware_state)
    return {
        "running": running,
        "state": app_state.get_startup_state(),
        "llm_healthy": _llm_server_healthy(),
        "hardware": hw,
    }


@app.get("/api/model-info")
async def get_model_info():
    """返回主模型详细信息（硬件页展示用）"""
    cfg = get_config_section("model_orchestration", default={})
    main_model = cfg.get("models", {}).get("main_model", {})
    return {
        "name": main_model.get("name", "Unknown"),
        "quant": main_model.get("quant", "unknown"),
        "port": main_model.get("port", 8000),
        "n_ctx": main_model.get("n_ctx", 8192),
        "status": "running" if _llm_server_healthy() else "offline",
    }


@app.get("/api/model/status")
async def get_model_status():
    """返回所有模型运行状态（替代旧 /api/model-info 的单模型视图）"""
    try:
        orch = get_orchestrator()
        return orch.status()
    except Exception as e:
        logging.exception("model/status failed")
        return {"error": str(e), "mode": "unknown", "models": {}}


@app.post("/api/model/start")
async def start_model():
    """启动所有已配置模型"""
    orch = get_orchestrator()
    success = orch.start_all(wait=False)
    return {"success": success, "status": orch.status()}


@app.post("/api/model/stop")
async def stop_model():
    """停止所有运行中的模型"""
    orch = get_orchestrator()
    orch.stop_all()
    return {"success": True, "status": orch.status()}


@app.get("/api/startup-status")
async def get_startup_status():
    return app_state.get_startup_state()


@app.post("/api/start")
async def start_analysis(genre: str = "末世", books: str = ""):
    if app_state.analyze_process is not None and app_state.analyze_process.poll() is None:
        return {"ok": False, "message": "拆书流程已在运行中"}
    script = PROJECT_ROOT / "src" / "xiaoshuo" / "pipeline" / "analyze_all.py"
    cmd = [sys.executable, str(script), "--genre", genre]
    if books:
        cmd.extend(["--books", books])
    app_state.set_startup_state(status="running", message="启动中...", progress=0)
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(PROJECT_ROOT),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")},
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        app_state.analyze_process = proc
        return {"ok": True, "message": f"已启动 (PID {proc.pid})"}
    except Exception as e:
        app_state.set_startup_state(status="error", message=str(e), error=str(e))
        return {"ok": False, "message": str(e)}


@app.post("/api/stop")
async def stop_analysis():
    proc = app_state.analyze_process
    if proc is None or proc.poll() is not None:
        app_state.analyze_process = None
        clear_stage()
        app_state.set_startup_state(status="idle")
        return {"ok": False, "message": "没有运行中的拆书流程"}
    pid = proc.pid
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except Exception:
            pass
    except Exception:
        pass
    app_state.analyze_process = None
    clear_stage()
    app_state.set_startup_state(status="idle")
    return {"ok": True, "message": f"已停止拆书流程 (PID {pid})"}


# ── 日志 ──

@app.get("/api/logs")
async def get_logs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    date: str = Query(""),
    level: str = Query(""),
    search: str = Query(""),
    category: str = Query("access"),
):
    records = list(reversed(app_state.log_records))
    if date:
        records = [r for r in records if r.get("time", "").startswith(date)]
    if level:
        records = [r for r in records if (r.get("level") or "").upper() == level.upper()]
    if search:
        records = [r for r in records if search.lower() in (r.get("message") or "").lower()]
    total = len(records)
    entries = records[offset:offset + limit]
    return {"entries": entries, "total": total, "limit": limit, "offset": offset}


@app.get("/api/logs/dates")
async def get_log_dates():
    dates = OrderedDict()
    for r in app_state.log_records:
        d = r.get("time", "")[:10] or "unknown"
        dates[d] = dates.get(d, 0) + 1
    date_list = list(dates.keys())
    return {"dates": date_list, "access": date_list, "operation": date_list}


@app.get("/api/logs/operations")
async def get_log_operations():
    ops = app_state.get_logs_filtered("operation")
    return {"operations": ops[-50:]}


class OperationLogRequest(BaseModel):
    action: str = ""
    detail: str | dict = ""


@app.post("/api/logs/operations")
async def post_log_operations(req: OperationLogRequest):
    app_state.add_log({
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "level": "INFO",
        "message": f"operation: {req.action} - {req.detail}",
    })
    return {"ok": True}


# ====================== Project CRUD（一书一档） ======================

@app.get("/api/projects")
async def api_list_projects(include_demo: bool = Query(True)):
    """列出所有创作项目（仅 meta 摘要）。include_demo=false 可过滤示例项目。"""
    return list_projects(include_demo=include_demo)


@app.get("/api/projects/demo")
async def api_get_demo_project():
    """获取示例项目模板（只读，不创建文件）"""
    return get_demo_project()


@app.post("/api/projects")
async def api_create_project(body: dict):
    """创建新项目。body: { meta: { title, genre, ... }, from_demo: bool }"""
    try:
        project = create_project(body)
        return {"ok": True, "project": project}
    except Exception as e:
        raise HTTPException(500, f"Failed to create project: {e}")


@app.get("/api/projects/{project_id}")
async def api_get_project(project_id: str):
    """获取完整项目数据"""
    project = get_project(project_id)
    if project is None:
        raise HTTPException(404, f"Project not found: {project_id}")
    return project


@app.put("/api/projects/{project_id}")
async def api_update_project(project_id: str, body: dict):
    """更新项目元数据"""
    project = update_project(project_id, body)
    if project is None:
        raise HTTPException(404, f"Project not found: {project_id}")
    return {"ok": True, "project": project}


@app.delete("/api/projects/{project_id}")
async def api_delete_project(project_id: str):
    """删除项目"""
    if not delete_project(project_id):
        raise HTTPException(404, f"Project not found: {project_id}")
    return {"ok": True}


@app.post("/api/projects/{project_id}/promote")
async def api_promote_project(project_id: str):
    """将示例项目转为正式项目（清除 is_demo 标记）"""
    project = promote_project(project_id)
    if project is None:
        raise HTTPException(404, f"Project not found or not a demo: {project_id}")
    return {"ok": True, "project": project}


@app.get("/api/projects/{project_id}/skeleton")
async def api_get_skeleton(project_id: str):
    """获取项目粗纲/细纲"""
    skeleton = get_skeleton(project_id)
    if skeleton is None:
        raise HTTPException(404, f"Project not found: {project_id}")
    return skeleton


@app.put("/api/projects/{project_id}/skeleton")
async def api_update_skeleton(project_id: str, body: dict):
    """更新项目粗纲/细纲"""
    skeleton = update_skeleton(project_id, body)
    if skeleton is None:
        raise HTTPException(404, f"Project not found: {project_id}")
    return {"ok": True, "skeleton": skeleton}


@app.get("/api/projects/{project_id}/world")
async def api_get_world(project_id: str):
    """获取项目世界观"""
    world = get_world(project_id)
    if world is None:
        raise HTTPException(404, f"Project not found: {project_id}")
    return world


@app.put("/api/projects/{project_id}/world")
async def api_update_world(project_id: str, body: dict):
    """更新项目世界观"""
    world = update_world(project_id, body)
    if world is None:
        raise HTTPException(404, f"Project not found: {project_id}")
    return {"ok": True, "world": world}


@app.get("/api/projects/{project_id}/characters")
async def api_get_characters(project_id: str):
    """获取项目角色列表"""
    chars = get_characters(project_id)
    if chars is None:
        raise HTTPException(404, f"Project not found: {project_id}")
    return chars


@app.put("/api/projects/{project_id}/characters")
async def api_update_characters(project_id: str, body: dict):
    """更新项目角色列表"""
    chars = update_characters(project_id, body)
    if chars is None:
        raise HTTPException(404, f"Project not found: {project_id}")
    return {"ok": True, "characters": chars}


@app.get("/api/projects/{project_id}/factions")
async def api_get_factions(project_id: str):
    """获取项目势力列表"""
    factions = get_factions(project_id)
    if factions is None:
        raise HTTPException(404, f"Project not found: {project_id}")
    return factions


@app.put("/api/projects/{project_id}/factions")
async def api_update_factions(project_id: str, body: dict):
    """更新项目势力列表"""
    factions = update_factions(project_id, body)
    if factions is None:
        raise HTTPException(404, f"Project not found: {project_id}")
    return {"ok": True, "factions": factions}


@app.get("/api/projects/{project_id}/chapters")
async def api_get_chapters(project_id: str):
    """获取项目章节列表"""
    chapters = get_chapters(project_id)
    if chapters is None:
        raise HTTPException(404, f"Project not found: {project_id}")
    return chapters


@app.get("/api/projects/{project_id}/chapters/{chapter_num}")
async def api_get_chapter(project_id: str, chapter_num: int):
    """获取单章详情"""
    chapter = get_chapter(project_id, chapter_num)
    if chapter is None:
        raise HTTPException(404, f"Chapter not found: {chapter_num}")
    return chapter


@app.put("/api/projects/{project_id}/chapters/{chapter_num}")
async def api_update_chapter(project_id: str, chapter_num: int, body: dict):
    """更新单章"""
    chapter = update_chapter(project_id, chapter_num, body)
    if chapter is None:
        raise HTTPException(404, f"Project not found: {project_id}")
    return {"ok": True, "chapter": chapter}


# ====================== 创作辅助 API (v8.4) ======================
# 挂载解构/心智模型/目标门控/提示词模板路由
from xiaoshuo.api.routes_creative import router as creative_router
app.include_router(creative_router)


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


# ====================== 启动入口 ======================
# 唯一启动方式: python -m xiaoshuo.api.server
# (pyproject.toml 已配置 console_scripts: xiaoshuo-server)

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