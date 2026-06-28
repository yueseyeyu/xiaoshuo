"""番茄小说 AI 创作辅助系统 — 统一 API 服务 v8.0

合并了原 progress_server.py 的进度监控 + 场景搜索 + 风格校准 + 补齐 14 个 API 端点。

启动方式:
    python -m xiaoshuo.api.server --port 8089
    # 端口/CORS 默认值来自 config.yaml::api_server；CLI 参数可覆盖 host/port
    # 前端原型服务运行在 config.yaml::prototype.port (8088)，通过 CORS 跨域调用本服务
"""

from __future__ import annotations

import argparse
import atexit
import csv
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from collections import OrderedDict
from pathlib import Path
from typing import Optional

import uvicorn

# Ensure HF offline mode before any imports
os.environ.setdefault("HF_HOME", str(Path(__file__).resolve().parents[3] / ".hf_cache"))
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from contextlib import asynccontextmanager
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import psutil

from xiaoshuo import __version__ as APP_VERSION
from xiaoshuo.pipeline.scene_search import SceneSearch
from xiaoshuo.pipeline.canon.extractor import CanonExtractor
from xiaoshuo.agents.cross_review import scan_fingerprints
from xiaoshuo.agents.outline_builder import build_chapter_blueprint
from xiaoshuo.agents.model_orchestrator import get_orchestrator
from xiaoshuo.infra.config_manager import get_config_section, get_config
from xiaoshuo.infra.hardware_guardian import (
    _init_nvml,
    _read_gpu_temp_pynvml,
    _read_vram_used_pynvml,
    _read_fan_speed_pynvml,
    _read_gpu_temp_smi,
    _read_vram_used_smi,
    _read_fan_speed_smi,
)
from xiaoshuo.infra.pipeline_state import clear_stage, mark_error

# ── 从 config.yaml 读取 API 配置（SSOT） ──
_API_CFG = get_config_section("api_server", default={}) or {}
_CORS_CFG = _API_CFG.get("cors", {}) if isinstance(_API_CFG, dict) else {}
_DEFAULT_HOST = str(_API_CFG.get("host", "127.0.0.1")) if isinstance(_API_CFG, dict) else "127.0.0.1"
_DEFAULT_PORT = int(_API_CFG.get("port", 8088)) if isinstance(_API_CFG, dict) else 8088
_STATIC_DIR = str(_API_CFG.get("static_dir", "prototype")) if isinstance(_API_CFG, dict) else "prototype"
_STATIC_MOUNT = str(_API_CFG.get("static_mount", "/")) if isinstance(_API_CFG, dict) else "/"

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOG_DIR = PROJECT_ROOT / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ====================== 全局状态 ======================

_search_engines: dict[str, SceneSearch] = {}

# 硬件监控状态
hardware_state = {
    "gpu_temp": None, "vram_used_mb": None, "vram_total_mb": None,
    "fan_speed": None, "sys_memory_used_gb": None, "sys_memory_total_gb": None,
    "gpu_available": False, "updated_at": None,
}
hardware_lock = threading.Lock()
hardware_running = False

# 内存日志队列
MAX_LOGS = 500
log_records: list[dict] = []
log_lock = threading.Lock()

# 拆书进程管理
analyze_process: Optional[subprocess.Popen] = None
analyze_lock = threading.Lock()
_startup_state = {
    "status": "idle", "message": "", "progress": 0, "error": "",
}

# NVML 缓存
_nvml_cached = None
_nvml_handle_cached = None
_nvml_init_attempted = False

# novel_index.json 缓存
_novel_index_cache: dict[str, dict] = {}
_novel_index_mtime: float = 0


# ====================== 硬件监控 ======================

def _get_cached_nvml():
    global _nvml_cached, _nvml_handle_cached, _nvml_init_attempted
    if _nvml_cached is not None:
        return _nvml_cached, _nvml_handle_cached
    if _nvml_init_attempted:
        return None, None
    _nvml_init_attempted = True
    _nvml_cached, _nvml_handle_cached = _init_nvml()
    return _nvml_cached, _nvml_handle_cached


def _shutdown_cached_nvml():
    global _nvml_cached
    if _nvml_cached is not None:
        try:
            _nvml_cached.nvmlShutdown()
        except Exception:
            pass
        _nvml_cached = None


atexit.register(_shutdown_cached_nvml)


def _read_hardware_once() -> dict:
    result = {
        "gpu_temp": None, "vram_used_mb": None, "vram_total_mb": None,
        "fan_speed": None, "sys_memory_used_gb": None, "sys_memory_total_gb": None,
        "gpu_available": False,
    }
    pynvml, handle = _get_cached_nvml()
    if pynvml is not None and handle is not None:
        result["gpu_available"] = True
        result["gpu_temp"] = _read_gpu_temp_pynvml(pynvml, handle)
        result["vram_used_mb"] = _read_vram_used_pynvml(pynvml, handle)
        result["fan_speed"] = _read_fan_speed_pynvml(pynvml, handle)
        try:
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            result["vram_total_mb"] = mem.total // (1024 * 1024)
        except Exception:
            pass
    else:
        result["gpu_temp"] = _read_gpu_temp_smi()
        result["vram_used_mb"] = _read_vram_used_smi()
        result["fan_speed"] = _read_fan_speed_smi()
        result["gpu_available"] = (
            result["gpu_temp"] is not None
            or result["vram_used_mb"] is not None
            or result["fan_speed"] is not None
        )
    try:
        mem = psutil.virtual_memory()
        result["sys_memory_used_gb"] = round(mem.used / (1024 ** 3), 2)
        result["sys_memory_total_gb"] = round(mem.total / (1024 ** 3), 2)
    except Exception:
        pass
    return result


def _hardware_loop():
    global hardware_state
    while hardware_running:
        data = _read_hardware_once()
        data["updated_at"] = time.strftime("%H:%M:%S")
        with hardware_lock:
            hardware_state = data
        time.sleep(1)


# ====================== LLM 服务管理 ======================

def _get_llm_port() -> int:
    cfg = get_config_section("model_orchestration", default={})
    models = cfg.get("models", {})
    main = models.get("main_model", {})
    port = main.get("port")
    if port:
        return int(port)
    rhythm_cfg = get_config_section("rhythm", default={})
    return int(rhythm_cfg.get("llm_port", 8000))


def _llm_server_healthy() -> bool:
    port = _get_llm_port()
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2)
        return True
    except Exception:
        pass
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=2)
        return True
    except Exception:
        return False


# ====================== 辅助函数 ======================

def _get_engine(genre: str) -> SceneSearch:
    if genre not in _search_engines:
        _search_engines[genre] = SceneSearch(genre)
    return _search_engines[genre]


def _safe_read_json(path: Path, default=None) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else {}


def _load_novel_index() -> dict[str, dict]:
    """读取 novel_index.json 并按题材建立 file->metadata 索引"""
    global _novel_index_cache, _novel_index_mtime
    path = PROJECT_ROOT / "data" / "raw" / "novel_index.json"
    try:
        mtime = path.stat().st_mtime
        if _novel_index_cache and mtime == _novel_index_mtime:
            return _novel_index_cache
        data = json.loads(path.read_text(encoding="utf-8"))
        result: dict[str, dict] = {}
        for g, info in (data.get("genres") or {}).items():
            result[g] = {}
            for novel in info.get("novels", []):
                result[g][novel.get("file", "")] = novel
        _novel_index_cache = result
        _novel_index_mtime = mtime
        return result
    except Exception:
        return {}


def _parse_title_author(name: str, meta: dict | None = None) -> tuple[str, str]:
    """从文件名或元数据解析书名和作者"""
    author = ""
    title = name
    if meta:
        author = (meta.get("author") or "").strip()
        file_name = (meta.get("file") or "").strip()
        if file_name:
            title = file_name.replace(".txt", "").strip()
    # 统一从标题末尾提取作者
    m = re.search(r"作者[：:]\s*(.+)$", title)
    if m:
        author = author or m.group(1).strip()
        title = title[:m.start()].strip()
    # 去掉常见后缀与书名号
    title = re.sub(r"[（(](校对版|精校版|校对全本|全本|番外|完结)[^）)]*[）)]", "", title)
    title = title.strip("《》 ").strip()
    return title, author or "未知作者"


def _estimate_word_count(size_kb: int) -> int:
    """按约 1.8 字节/字估算中文字数"""
    return max(0, round(size_kb * 1024 / 1.8))


def _get_book_tags(genre: str, name: str) -> list[str]:
    """从 labels 文件读取高频标签"""
    labels_dir = PROJECT_ROOT / "data" / "processed" / genre / "labels"
    candidate = labels_dir / f"{name}_labels.csv"
    if not candidate.exists():
        return []
    try:
        counts: dict[str, float] = {}
        with open(candidate, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                if (row.get("ch_num") or "").lower() == "summary":
                    continue
                for k, v in row.items():
                    if k == "ch_num":
                        continue
                    try:
                        val = float(v or 0)
                    except ValueError:
                        continue
                    if val > 0:
                        tag = re.sub(r"^(regex_|llm_)", "", k)
                        counts[tag] = counts.get(tag, 0.0) + val
        return [tag for tag, _ in sorted(counts.items(), key=lambda x: x[1], reverse=True)[:3]]
    except Exception:
        return []


def _get_book_score(genre: str, name: str) -> float | None:
    """从 scores 文件读取平均 hook/retention 评分"""
    scores_dir = PROJECT_ROOT / "data" / "processed" / genre / "scores"
    candidate = scores_dir / f"{name}_llm.csv"
    if not candidate.exists():
        return None
    try:
        scores: list[float] = []
        with open(candidate, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                for key in ("llm_retention", "llm_hook"):
                    val = row.get(key)
                    if val:
                        try:
                            scores.append(float(val))
                        except ValueError:
                            pass
        if not scores:
            return None
        return round(sum(scores) / len(scores), 1)
    except Exception:
        return None


def _get_available_books(genre: str = "末世") -> list[dict]:
    """从 data/processed/ 读取已处理的书列表"""
    processed = PROJECT_ROOT / "data" / "processed" / genre
    books = []
    index = _load_novel_index()
    meta_by_file = index.get(genre, {})
    if (processed / "rhythm").exists():
        for f in sorted((processed / "rhythm").glob("rhythm_*.csv")):
            stem = f.stem.replace("rhythm_", "")
            meta = None
            for file_name, m in meta_by_file.items():
                if file_name.replace(".txt", "").strip() == stem:
                    meta = m
                    break
            title, author = _parse_title_author(stem, meta)
            size_kb = meta.get("size_kb", 0) if meta else 0
            word_count = _estimate_word_count(size_kb)
            tags = _get_book_tags(genre, stem)
            score = _get_book_score(genre, stem)
            books.append({
                "title": title,
                "author": author,
                "genre": genre,
                "wordCount": word_count,
                "size_kb": size_kb,
                "status": "analyzed",
                "file": f.name,
                "tags": tags,
                "score": score,
            })
    return books


def _get_genre_counts() -> tuple[list[str], list[list]]:
    """扫描 data/processed/ 下所有题材及书籍数量"""
    processed_root = PROJECT_ROOT / "data" / "processed"
    counts = []
    genres = []
    if processed_root.exists():
        for genre_dir in sorted(d for d in processed_root.iterdir() if d.is_dir()):
            rhythm_dir = genre_dir / "rhythm"
            if rhythm_dir.exists():
                count = len(list(rhythm_dir.glob("rhythm_*.csv")))
                if count > 0:
                    genres.append(genre_dir.name)
                    counts.append([genre_dir.name, count])
    return genres, counts


def _get_chapter_instructions(book: str, chapter: int, genre: str = "末世") -> dict:
    """从已有的 writing_instructions 数据中读取"""
    books_dir = PROJECT_ROOT / "data" / "processed" / genre / "writing_instructions"
    if not books_dir.exists():
        return {"book": book, "chapter": chapter, "instructions": [], "error": "no data"}
    # 尝试找到匹配的指令文件
    safe_name = book.replace(" ", "_")
    candidate = books_dir / f"{safe_name}_instructions.csv"
    if candidate.exists():
        rows = []
        with open(candidate, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                rows.append(r)
        return {"book": book, "chapter": chapter, "instructions": rows, "total": len(rows)}
    return {"book": book, "chapter": chapter, "instructions": [], "total": 0}


# ====================== FastAPI 生命周期 ======================

@asynccontextmanager
async def lifespan(app: FastAPI):
    global hardware_running
    hardware_running = True
    t = threading.Thread(target=_hardware_loop, daemon=True)
    t.start()
    logging.info("硬件监控已启动")
    yield
    hardware_running = False
    _shutdown_cached_nvml()
    logging.info("硬件监控已停止")


app = FastAPI(title="番茄小说 AI 创作辅助系统", version=APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_CFG.get("allow_origins", [
        "http://localhost:8088",
        "http://127.0.0.1:8088",
        "http://localhost:3000",
    ]),
    allow_methods=_CORS_CFG.get("allow_methods", ["GET", "POST", "OPTIONS"]),
    allow_headers=_CORS_CFG.get("allow_headers", ["*"]),
)

# ====================== 响应模型 ======================

class SceneResult(BaseModel):
    rank: int
    similarity: float
    book_name: str
    chapter: int
    scene_index: int
    char_count: int
    text_preview: str
    emotion: str
    pace: str
    conflict_level: str
    pleasure_type: str
    dominant_sub: str
    technique_summary: str


class SearchResponse(BaseModel):
    query: str
    genre: str
    total_scenes: int
    results: list[SceneResult]


class IndexStats(BaseModel):
    genre: str
    total_scenes: int
    total_books: int


class StyleRuleItem(BaseModel):
    dimension: str
    rule: str
    weight: float
    source: str
    evidence: str


class StyleCalibrateRequest(BaseModel):
    chapter_id: int = 0
    text: str
    version: str = ""


class StyleCalibrateResponse(BaseModel):
    ok: bool
    rule_count: int
    rules: list[StyleRuleItem]
    new_findings: int
    version: str = ""
    error: Optional[str] = None


class StyleRulesResponse(BaseModel):
    ok: bool
    rule_count: int
    rules: list[StyleRuleItem]
    version: str = ""
    error: Optional[str] = None


# v8.0: 平台合规预检 (S6 AI指纹词扫描)
class FingerprintHit(BaseModel):
    word: str
    count: int

class ComplianceScanResponse(BaseModel):
    ok: bool
    risk_level: str
    total_count: int
    high_risk_count: int
    by_category: dict[str, list[FingerprintHit]]
    high_risk_hits: list[FingerprintHit]
    error: Optional[str] = None


# ====================== 核心 API 路由 ======================

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": APP_VERSION}


@app.get("/api/config")
async def get_config_endpoint():
    """返回前端配置（非敏感字段）"""
    cfg = get_config()
    return {
        "version": APP_VERSION,
        "genre": cfg.get("default_genre", "末世"),
        "llm_port": _get_llm_port(),
        "mode": cfg.get("mode", "local"),
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


# v8.0: 平台合规预检 (S6 AI指纹词扫描)
@app.get("/api/compliance/scan", response_model=ComplianceScanResponse)
def compliance_scan(text: str = Query(..., min_length=1)):
    """扫描文本中的 AI 指纹词，输出风险等级和详情。
    对话中的指纹词默认豁免 (exempt_dialogue=true)。
    """
    try:
        result = scan_fingerprints(text, exempt_dialogue=True)
        return ComplianceScanResponse(
            ok=True,
            risk_level=result["risk_level"],
            total_count=result["total_count"],
            high_risk_count=result["high_risk_count"],
            by_category=result["by_category"],
            high_risk_hits=result["high_risk_hits"],
        )
    except Exception as e:
        return ComplianceScanResponse(
            ok=False, risk_level="error", total_count=0, high_risk_count=0,
            by_category={}, high_risk_hits=[], error=str(e),
        )


# ── 书籍列表 & 拆书数据 ──

@app.get("/api/books")
async def get_books(genre: str = Query("末世")):
    books = _get_available_books(genre)
    genres, counts = _get_genre_counts()
    return {
        "books": books,
        "count": len(books),
        "genre": genre,
        "genres": genres,
        "counts": counts,
    }


@app.get("/api/disassembly/books")
async def disassembly_books(genre: str = Query("末世")):
    books = _get_available_books(genre)
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
async def instructions(book: str = Query(...), ch: int = Query(1), genre: str = Query("末世")):
    return _get_chapter_instructions(book, ch, genre)


@app.get("/api/guidance")
async def guidance(genre: str = Query("末世")):
    """返回综合写作指导"""
    guidance_path = PROJECT_ROOT / "data" / "processed" / genre / "writing_guidance.json"
    if guidance_path.exists():
        return _safe_read_json(guidance_path, {"guidance": [], "genre": genre})
    return {"guidance": [], "genre": genre, "error": "no data"}


@app.get("/api/techniques")
async def techniques(genre: str = Query("末世")):
    """返回写作技法库"""
    techniques_path = PROJECT_ROOT / "data" / "processed" / "techniques.json"
    if techniques_path.exists():
        return _safe_read_json(techniques_path, {"techniques": [], "genre": genre})
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
async def diagnosis(book: str = Query(...), chapter: int = Query(1), genre: str = Query("末世")):
    """返回章节诊断信息"""
    return {"book": book, "chapter": chapter, "diagnosis": [], "error": "not implemented"}


# ── 任务管理 ──

@app.get("/api/tasks")
async def get_tasks():
    tasks_path = PROJECT_ROOT / "data" / "tasks.json"
    return _safe_read_json(tasks_path, {"tasks": []})


@app.get("/api/task")
async def get_task(id: str = Query(...)):
    tasks_path = PROJECT_ROOT / "data" / "tasks.json"
    tasks = _safe_read_json(tasks_path, {"tasks": []})
    for t in tasks.get("tasks", []):
        if str(t.get("id", "")) == id:
            return t
    raise HTTPException(404, f"Task not found: {id}")


# ── 进度监控（从 progress_server 合并） ──

@app.get("/api/progress")
async def get_progress():
    """获取当前拆书进度"""
    with analyze_lock:
        running = analyze_process is not None and analyze_process.poll() is None
    return {
        "running": running,
        "startup_state": _startup_state,
        "llm_healthy": _llm_server_healthy(),
    }


def _format_hardware_response(state: dict) -> dict:
    """将扁平硬件状态转换为前端期望的嵌套百分比结构"""
    gpu_temp = state.get("gpu_temp") or 0
    vram_used = state.get("vram_used_mb") or 0
    vram_total = state.get("vram_total_mb") or 1
    sys_used = state.get("sys_memory_used_gb") or 0
    sys_total = state.get("sys_memory_total_gb") or 1
    fan_speed = state.get("fan_speed") or 0
    return {
        "gpu": {
            "temp": gpu_temp,
            "util": fan_speed,
            "vram_pct": round(min(vram_used / vram_total * 100, 100), 1) if vram_total else 0,
        },
        "cpu": {"pct": 0},
        "ram": {"pct": round(min(sys_used / sys_total * 100, 100), 1) if sys_total else 0},
        "updated_at": state.get("updated_at", ""),
    }


@app.get("/api/hardware")
async def get_hardware():
    with hardware_lock:
        return _format_hardware_response(hardware_state)


@app.get("/api/status")
async def get_status():
    with analyze_lock:
        running = analyze_process is not None and analyze_process.poll() is None
    with hardware_lock:
        hw = _format_hardware_response(hardware_state)
    return {
        "running": running,
        "state": _startup_state,
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


@app.get("/api/startup-status")
async def get_startup_status():
    return dict(_startup_state)


@app.post("/api/start")
async def start_analysis(genre: str = "末世", books: str = ""):
    global analyze_process, _startup_state
    with analyze_lock:
        if analyze_process is not None and analyze_process.poll() is None:
            return {"ok": False, "message": "拆书流程已在运行中"}
        script = PROJECT_ROOT / "src" / "xiaoshuo" / "pipeline" / "analyze_all.py"
        cmd = [sys.executable, str(script), "--genre", genre]
        if books:
            cmd.extend(["--books", books])
        _startup_state = {"status": "running", "message": "启动中...", "progress": 0, "error": ""}
        try:
            analyze_process = subprocess.Popen(
                cmd, cwd=str(PROJECT_ROOT),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")},
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return {"ok": True, "message": f"已启动 (PID {analyze_process.pid})"}
        except Exception as e:
            _startup_state = {"status": "error", "message": str(e), "progress": 0, "error": str(e)}
            return {"ok": False, "message": str(e)}


@app.post("/api/stop")
async def stop_analysis():
    global analyze_process, _startup_state
    with analyze_lock:
        if analyze_process is None or analyze_process.poll() is not None:
            analyze_process = None
            clear_stage()
            _startup_state = {"status": "idle", "message": "", "progress": 0, "error": ""}
            return {"ok": False, "message": "没有运行中的拆书流程"}
        pid = analyze_process.pid
        try:
            analyze_process.terminate()
            analyze_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                analyze_process.kill()
            except Exception:
                pass
        except Exception:
            pass
        analyze_process = None
        clear_stage()
        _startup_state = {"status": "idle", "message": "", "progress": 0, "error": ""}
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
    with log_lock:
        records = list(log_records)
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
    with log_lock:
        for r in log_records:
            d = r.get("time", "")[:10] or "unknown"
            dates[d] = dates.get(d, 0) + 1
    return {"access": list(dates.keys()), "operation": list(dates.keys())}


@app.get("/api/logs/operations")
async def get_log_operations():
    with log_lock:
        ops = [r for r in log_records if "operation" in r.get("message", "").lower()]
        return {"operations": ops[-50:]}


class OperationLogRequest(BaseModel):
    action: str = ""
    detail: str = ""


@app.post("/api/logs/operations")
async def post_log_operations(req: OperationLogRequest):
    with log_lock:
        log_records.append({
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "level": "INFO",
            "message": f"operation: {req.action} - {req.detail}",
        })
        if len(log_records) > MAX_LOGS:
            log_records.pop(0)
    return {"ok": True}


# ====================== 静态文件服务 ======================

_FRONTEND_DIR = PROJECT_ROOT / _STATIC_DIR
if _FRONTEND_DIR.exists():
    app.mount(_STATIC_MOUNT, StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")


# ====================== 启动入口 ======================

def main():
    parser = argparse.ArgumentParser(description="番茄小说 AI 创作辅助系统 — 统一 API 服务")
    parser.add_argument("--port", type=int, default=_DEFAULT_PORT, help=f"端口 (default: {_DEFAULT_PORT})")
    parser.add_argument("--host", default=_DEFAULT_HOST, help=f"监听地址 (default: {_DEFAULT_HOST})")
    args = parser.parse_args()

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()