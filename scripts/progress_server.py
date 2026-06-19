#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
progress_server.py — 拆书进度监控面板 v2
==========================================
启动: python scripts/progress_server.py
访问: http://localhost:8090

v2 新增:
  - /api/progress   : JSON 进度数据
  - /api/hardware   : 硬件状态 (GPU 温度/显存/风扇/系统内存)
  - /api/start      : 启动拆书流程
  - /api/stop       : 停止拆书流程
  - /api/logs       : 最近事件日志
  - /api/status     : 全局运行状态
"""
import atexit
import csv
import json
import logging
import logging.handlers
import signal
import subprocess
import sys
import threading
import time
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

import psutil

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from xiaoshuo import PROJECT_ROOT as XS_ROOT
from xiaoshuo.infra.config_manager import get_config_section
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
from xiaoshuo.pipeline.scoring.commercial_engine import analyze_single_novel


# P3: read main LLM server port from config.yaml (SSOT)
def _get_llm_port():
    cfg = get_config_section("model_orchestration", default={})
    models = cfg.get("models", {})
    main = models.get("main_model", {})
    port = main.get("port")
    if port:
        return int(port)
    # fallback to rhythm section
    rhythm_cfg = get_config_section("rhythm", default={})
    return int(rhythm_cfg.get("llm_port", 8000))

PORT = 8090

# ====================== 全局状态 ======================

analyze_process = None          # subprocess.Popen instance
analyze_lock = threading.Lock()
_llm_process = None             # auto-started llama-server subprocess
_llm_ready = False              # True once LLM health check passes
_startup_state = {              # async startup progress tracker
    "status": "idle",           # idle | starting_llm | waiting_llm | starting_analysis | running | error
    "message": "",
    "progress": 0,
    "error": "",
}
hardware_state = {
    "gpu_temp": None,
    "vram_used_mb": None,
    "vram_total_mb": None,
    "fan_speed": None,
    "sys_memory_used_gb": None,
    "sys_memory_total_gb": None,
    "gpu_available": False,
    "updated_at": None,
}
hardware_lock = threading.Lock()
hardware_thread = None
hardware_running = False

# 内存日志队列
MAX_LOGS = 500
log_records = []
log_lock = threading.Lock()


# ====================== 日志处理器 ======================

class MemoryLogHandler(logging.Handler):
    """将日志记录保留在内存中供前端 /api/logs 读取。"""

    def emit(self, record):
        try:
            msg = self.format(record)
        except Exception:
            msg = str(record)
        with log_lock:
            log_records.append({
                "time": time.strftime("%H:%M:%S"),
                "level": record.levelname,
                "message": msg,
            })
            if len(log_records) > MAX_LOGS:
                log_records.pop(0)


memory_handler = MemoryLogHandler()
memory_handler.setFormatter(logging.Formatter("%(message)s"))
logging.getLogger().addHandler(memory_handler)

# 持久化日志：滚动文件，最多保留 5 个备份，每个最大 10MB
LOG_DIR = XS_ROOT / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
file_handler = logging.handlers.RotatingFileHandler(
    LOG_DIR / "progress_server.log",
    maxBytes=10 * 1024 * 1024,  # 10MB
    backupCount=5,
    encoding="utf-8",
)
file_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
))
logging.getLogger().addHandler(file_handler)
logging.info("日志持久化已启用: %s", file_handler.baseFilename)


# ====================== 硬件监控线程 ======================

# P3: cache NVML init result so we do not init/shutdown every second
_nvml_cached = None
_nvml_handle_cached = None
_nvml_init_attempted = False


def _get_cached_nvml():
    """Return cached (pynvml, handle) or try init once."""
    global _nvml_cached, _nvml_handle_cached, _nvml_init_attempted
    if _nvml_cached is not None:
        return _nvml_cached, _nvml_handle_cached
    if _nvml_init_attempted:
        return None, None
    _nvml_init_attempted = True
    _nvml_cached, _nvml_handle_cached = _init_nvml()
    return _nvml_cached, _nvml_handle_cached


def _shutdown_cached_nvml():
    """Shutdown cached NVML handle on exit."""
    global _nvml_cached
    if _nvml_cached is not None:
        try:
            _nvml_cached.nvmlShutdown()
        except Exception:
            pass
        _nvml_cached = None


atexit.register(_shutdown_cached_nvml)


def _read_hardware_once():
    """单次读取硬件状态，返回 dict。"""
    result = {
        "gpu_temp": None,
        "vram_used_mb": None,
        "vram_total_mb": None,
        "fan_speed": None,
        "sys_memory_used_gb": None,
        "sys_memory_total_gb": None,
        "gpu_available": False,
    }

    # GPU 信息 (cached NVML)
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
        # nvidia-smi 降级
        result["gpu_temp"] = _read_gpu_temp_smi()
        result["vram_used_mb"] = _read_vram_used_smi()
        result["fan_speed"] = _read_fan_speed_smi()
        result["gpu_available"] = (
            result["gpu_temp"] is not None
            or result["vram_used_mb"] is not None
            or result["fan_speed"] is not None
        )

    # 系统内存
    try:
        mem = psutil.virtual_memory()
        result["sys_memory_used_gb"] = round(mem.used / (1024 ** 3), 2)
        result["sys_memory_total_gb"] = round(mem.total / (1024 ** 3), 2)
    except Exception:
        pass

    return result


def _hardware_loop():
    """后台线程：每秒刷新一次硬件状态。"""
    global hardware_state
    while hardware_running:
        data = _read_hardware_once()
        data["updated_at"] = time.strftime("%H:%M:%S")
        with hardware_lock:
            hardware_state = data
        time.sleep(1)


def start_hardware_monitor():
    """启动硬件监控线程。"""
    global hardware_thread, hardware_running
    if hardware_thread is not None and hardware_thread.is_alive():
        return
    hardware_running = True
    hardware_thread = threading.Thread(target=_hardware_loop, daemon=True)
    hardware_thread.start()


def _load_hardware_config():
    """从 config.yaml 读取 hardware_guard 配置（通过 config_manager SSOT 单例）。"""
    return get_config_section("hardware_guard", default={})


# ====================== 拆书进程管理 ======================

def get_analyze_script():
    """返回 analyze_all.py 的绝对路径。"""
    return XS_ROOT / "src" / "xiaoshuo" / "pipeline" / "analyze_all.py"


def _llm_server_healthy():
    """Check if the main LLM server is reachable."""
    import urllib.request
    port = _get_llm_port()
    try:
        urllib.request.urlopen(
            f"http://127.0.0.1:{port}/health",
            timeout=2,
        )
        return True
    except Exception:
        pass
    # llama.cpp server may use /v1/models or /health; try a generic endpoint
    try:
        urllib.request.urlopen(
            f"http://127.0.0.1:{port}/v1/models",
            timeout=2,
        )
        return True
    except Exception:
        return False


def _get_llm_exe_and_model():
    """Read llama-server.exe path and model GGUF from config.yaml (SSOT)."""
    cfg = get_config_section("model_orchestration", default={})
    exe = cfg.get("llama_server_exe", "")
    models = cfg.get("models", {})
    main = models.get("main_model", {})
    gguf = main.get("gguf", "")
    n_gpu = main.get("n_gpu_layers", 35)
    ctx_size = main.get("ctx_size", 8192)
    parallel = main.get("parallel", 2)
    return exe, gguf, n_gpu, ctx_size, parallel


def _start_llm_server():
    """Auto-start llama-server.exe as a background subprocess.
    Returns (pid, message) or (None, error_message)."""
    global _llm_process, _llm_ready
    exe, gguf, n_gpu, ctx_size, parallel = _get_llm_exe_and_model()
    if not exe or not Path(exe).exists():
        return None, f"llama-server.exe 未找到: {exe}"
    if not gguf or not Path(gguf).exists():
        return None, f"模型文件不存在: {gguf}"

    port = _get_llm_port()
    logging.info("自动启动 LLM 模型服务: %s (端口 %s)", gguf, port)
    try:
        _llm_process = subprocess.Popen(
            [
                exe,
                "--model", gguf,
                "--n-gpu-layers", str(n_gpu),
                "--ctx-size", str(ctx_size),
                "--port", str(port),
                "--host", "127.0.0.1",
                "--alias", "Qwen3.5-9B",
                "--reasoning", "off",
                "--flash-attn", "on",
                "--cache-type-k", "q8_0",
                "--cache-type-v", "q8_0",
                "--cache-prompt",
                "--parallel", str(parallel),
                "--ubatch-size", "512",
                "--batch-size", "1024",
                "--threads", "10",
                "--mlock",
                "--defrag-thold", "0.9",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return _llm_process.pid, f"已启动 LLM 模型服务 (PID {_llm_process.pid}, 端口 {port})"
    except Exception as e:
        _llm_process = None
        return None, f"启动 LLM 模型服务失败: {e}"


def _wait_llm_ready(timeout=120):
    """Poll LLM server health until ready or timeout. Returns (ready, message)."""
    import time as time_mod
    deadline = time_mod.time() + timeout
    while time_mod.time() < deadline:
        if _llm_server_healthy():
            return True, "LLM 模型服务已就绪"
        if _llm_process is not None and _llm_process.poll() is not None:
            return False, f"LLM 模型服务异常退出 (exit={_llm_process.returncode})"
        time_mod.sleep(2)
    return False, f"LLM 模型服务启动超时 ({timeout}s)"


def _cleanup_llm_process():
    """Terminate auto-started LLM server on exit."""
    global _llm_process
    if _llm_process is not None and _llm_process.poll() is None:
        logging.info("清理 LLM 模型服务 (PID %s)", _llm_process.pid)
        try:
            _llm_process.terminate()
            _llm_process.wait(timeout=10)
        except Exception:
            try:
                _llm_process.kill()
            except Exception:
                pass
        _llm_process = None


atexit.register(_cleanup_llm_process)


def _do_start_analysis(genre, books):
    """Background thread: start LLM (if needed), wait for ready, then start analysis."""
    global _startup_state, analyze_process, _llm_ready
    try:
        # Phase 1: check/start LLM
        if not _llm_server_healthy():
            _startup_state = {"status": "starting_llm", "message": "正在启动 LLM 模型服务...", "progress": 10, "error": ""}
            logging.info("LLM 模型服务未运行，尝试自动启动...")
            pid, msg = _start_llm_server()
            if pid is None:
                _startup_state = {"status": "error", "message": msg, "progress": 0, "error": msg}
                logging.error("LLM 自动启动失败: %s", msg)
                return
            logging.info("LLM 模型服务启动中 (PID %s), 等待就绪...", pid)

            # Phase 2: wait for LLM ready
            _startup_state = {"status": "waiting_llm", "message": "等待 LLM 模型加载...", "progress": 30, "error": ""}
            ready, ready_msg = _wait_llm_ready(timeout=120)
            if not ready:
                _cleanup_llm_process()
                _startup_state = {"status": "error", "message": f"LLM 启动失败: {ready_msg}", "progress": 0, "error": ready_msg}
                return
            _llm_ready = True
            logging.info("LLM 模型服务已就绪")

        # Phase 3: start analysis subprocess
        _startup_state = {"status": "starting_analysis", "message": "正在启动拆书流程...", "progress": 80, "error": ""}
        cmd = [sys.executable, str(get_analyze_script()), "--genre", genre]
        if books:
            cmd.extend(["--books", ",".join(books)])

        err_file = LOG_DIR / "analyze_all.err"
        try:
            err_file.unlink()
        except OSError:
            pass
        try:
            err_handle = open(err_file, "w", encoding="utf-8")
        except OSError:
            err_handle = subprocess.DEVNULL

        analyze_process = subprocess.Popen(
            cmd,
            cwd=str(XS_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=err_handle,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        selected = books or []
        logging.info(
            "拆书流程已启动: genre=%s selected=%s pid=%s",
            genre, len(selected), analyze_process.pid
        )
        msg = f"已启动拆书流程 (PID {analyze_process.pid}"
        if selected:
            msg += f", 选中 {len(selected)} 本"
        msg += ")"
        _startup_state = {"status": "running", "message": msg, "progress": 100, "error": ""}
    except Exception as e:
        _startup_state = {"status": "error", "message": f"启动异常: {e}", "progress": 0, "error": str(e)}
        logging.error("启动异常: %s", e)


def start_analysis(genre="末世", books=None):
    """启动拆书子进程（异步）。立即返回，后台线程处理 LLM 启动。返回 (ok, message)。"""
    global _startup_state
    with analyze_lock:
        if analyze_process is not None and analyze_process.poll() is None:
            return False, "拆书流程已在运行中"

        # Reset startup state
        _startup_state = {"status": "starting_llm", "message": "正在启动服务...", "progress": 5, "error": ""}

        # Start background thread
        t = threading.Thread(
            target=_do_start_analysis,
            args=(genre, books),
            daemon=True,
            name="startup-thread",
        )
        t.start()
        return True, "启动中，请稍候..."


def _log_analysis_exit():
    """Read captured stderr and mark pipeline error if analysis crashed."""
    global analyze_process
    if analyze_process is None:
        return
    returncode = analyze_process.poll()
    if returncode is None:
        return
    pid = analyze_process.pid
    err_file = LOG_DIR / "analyze_all.err"
    err_text = ""
    if err_file.exists():
        try:
            err_text = err_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    if returncode != 0:
        msg = f"拆书流程异常退出 (PID {pid}, exit={returncode})"
        if err_text:
            msg += f": {err_text[:500]}"
        logging.error(msg)
        mark_error("analyze_all", msg, stage_num=0, total=8)
    else:
        logging.info("拆书流程正常结束 (PID %s)", pid)
        clear_stage()
    analyze_process = None


def _kill_process_tree(pid):
    """Recursively kill a process and all its children using psutil."""
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        parent.terminate()
        # Wait for children
        gone, alive = psutil.wait_procs(children + [parent], timeout=10)
        for p in alive:
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass
        if alive:
            psutil.wait_procs(alive, timeout=5)
        return True
    except psutil.NoSuchProcess:
        return True
    except Exception as e:
        logging.warning("Process tree kill failed for pid=%s: %s", pid, e)
        return False


def stop_analysis():
    """停止拆书子进程及其所有子进程，同时释放 LLM 模型服务。返回 (ok, message)。"""
    global analyze_process, _llm_ready, _startup_state
    with analyze_lock:
        if analyze_process is None or analyze_process.poll() is not None:
            analyze_process = None
            clear_stage()
            # Also clean up LLM server even if no analysis running
            _cleanup_llm_process()
            _llm_ready = False
            _startup_state = {"status": "idle", "message": "", "progress": 0, "error": ""}
            return False, "没有运行中的拆书流程"

        pid = analyze_process.pid
        try:
            _kill_process_tree(pid)
            logging.info("拆书流程已停止: pid=%s", pid)
            clear_stage()
            # Stop LLM server to free VRAM
            _cleanup_llm_process()
            _llm_ready = False
            _startup_state = {"status": "idle", "message": "", "progress": 0, "error": ""}
            return True, f"已停止拆书流程 (PID {pid})，LLM 服务已释放"
        except Exception as e:
            return False, f"停止失败: {e}"
        finally:
            analyze_process = None


def analysis_is_running():
    """检查拆书进程是否在运行。"""
    with analyze_lock:
        if analyze_process is None:
            return False
        if analyze_process.poll() is not None:
            _log_analysis_exit()
            return False
        return True


# ====================== 进度扫描 ======================

def _chapter_count_from_rhythm(book_name, genre="末世"):
    """Read actual chapter count from pre-computed rhythm CSV."""
    rhythm_dir = XS_ROOT / "data" / "processed" / genre / "rhythm"
    for csv_path in sorted(rhythm_dir.glob("rhythm_*.csv")):
        stem = csv_path.stem.replace("rhythm_", "")
        if book_name[:15] in stem or stem[:15] in book_name:
            try:
                reader = csv.DictReader(open(csv_path, "r", encoding="utf-8-sig"))
                return sum(1 for _ in reader)
            except Exception:
                pass
            break
    return None


def _find_rhythm_csv(book_name, genre="末世"):
    """Find rhythm CSV filename for a book."""
    rhythm_dir = XS_ROOT / "data" / "processed" / genre / "rhythm"
    for csv_path in sorted(rhythm_dir.glob("rhythm_*.csv")):
        stem = csv_path.stem.replace("rhythm_", "")
        if book_name[:15] in stem or stem[:15] in book_name:
            return csv_path.name
    return None


def _load_book_recursive(book_name, genre="末世"):
    """Load cleaned recursive summary data for a completed book."""
    summaries_dir = XS_ROOT / "data" / "processed" / genre / "summaries"
    json_path = summaries_dir / f"{book_name}_recursive.json"
    if not json_path.exists():
        return None
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return None

    l1 = data.get("l1_summaries", []) or []
    l2 = data.get("l2_summaries", []) or []
    l3 = data.get("l3_analysis", {}) or {}

    # Sanitize L1: keep the most useful fields for authors
    clean_l1 = []
    for item in l1:
        if not isinstance(item, dict):
            continue
        clean_l1.append({
            "chapters": item.get("chapters") or item.get("c"),
            "word_count": item.get("word_count") or item.get("wc"),
            "hooks": item.get("hooks") or item.get("h") or [],
            "key_events": item.get("key_events") or item.get("ke") or [],
            "emotion_curve": item.get("emotion_curve") or item.get("ec") or [],
            "conflicts": item.get("conflicts") or item.get("cf") or [],
            "foreshadowing": item.get("foreshadowing") or item.get("fw") or [],
            "pacing_notes": item.get("pacing_notes") or item.get("pn"),
            "chapter_summaries": item.get("chapter_summaries") or item.get("cs") or [],
            "character_changes": item.get("character_changes") or item.get("cc") or [],
        })

    # Sanitize L2: volume-level synthesis
    clean_l2 = []
    for item in l2:
        if not isinstance(item, dict):
            continue
        clean_l2.append({
            "range": item.get("range"),
            "rhythm_pattern": item.get("rhythm_pattern"),
            "emotional_arc": item.get("emotional_arc"),
            "conflict_escalation": item.get("conflict_escalation"),
            "active_foreshadowing": item.get("active_foreshadowing") or [],
            "character_tracking": item.get("character_tracking") or [],
            "pleasure_landmarks": item.get("pleasure_landmarks") or [],
            "debt_register": item.get("debt_register") or [],
            "volume_summary": item.get("volume_summary"),
        })

    # Sanitize L3: book-level analysis
    clean_l3 = {
        "book_summary": l3.get("book_summary"),
        "total_chapters": l3.get("total_chapters"),
        "total_words": l3.get("total_words"),
        "structure_pattern": l3.get("structure_pattern"),
        "pleasure_distribution": l3.get("pleasure_distribution") or {},
        "character_arcs": l3.get("character_arcs") or [],
        "theme_evolution": l3.get("theme_evolution"),
        "narrative_rhythm": l3.get("narrative_rhythm") or {},
        "hook_system": l3.get("hook_system") or {},
        "commercial_assessment": l3.get("commercial_assessment") or {},
        "writing_insights": l3.get("writing_insights") or [],
    }

    return {
        "book": data.get("book", book_name),
        "total_chapters": data.get("total_chapters"),
        "generated": data.get("generated"),
        "quality_flags": data.get("quality_flags") or [],
        "l1_summaries": clean_l1,
        "l2_summaries": clean_l2,
        "l3_analysis": clean_l3,
    }


def scan_progress(genre="末世"):
    """Scan all books' checkpoint files and return progress data."""
    summaries_dir = XS_ROOT / "data" / "processed" / genre / "summaries"
    books = []

    for cp_path in sorted(summaries_dir.glob("*_checkpoint.json")):
        book_name = cp_path.stem.replace("_checkpoint", "")
        try:
            cp = json.loads(cp_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            continue

        l1_done = len(cp.get("l1_data", {}))
        l2_done = len(cp.get("l2_done", []))
        l3_done = cp.get("l3_done", False)

        l1_total = cp.get("l1_total", 0)
        if not l1_total:
            ch_count = _chapter_count_from_rhythm(book_name, genre)
            l1_total = max(1, (ch_count + 7) // 8) if ch_count else "?"

        # P2: derive L2 total from L1 total (5 L1 groups -> 1 L2 volume)
        l2_total = "?"
        if isinstance(l1_total, int):
            l2_total = max(1, (l1_total + 4) // 5)

        json_path = summaries_dir / f"{book_name}_recursive.json"
        has_output = json_path.exists()

        # P2: is_complete must reflect real parse progress, not just output file presence
        is_complete = False
        if isinstance(l1_total, int) and isinstance(l2_total, int) and has_output:
            output_valid = False
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                l3 = data.get("l3_analysis", {})
                output_valid = bool(
                    l3.get("book_summary")
                    and l3.get("structure_pattern")
                    and l3["book_summary"] not in ("(LLM unavailable)", "(checkpoint resume)", "")
                    and l3["structure_pattern"] != "N/A"
                )
            except (json.JSONDecodeError, IOError):
                pass
            is_complete = (l1_done >= l1_total) and (l2_done >= l2_total) and l3_done and output_valid

        if is_complete:
            status = "done"
            status_text = "已完成"
        elif l1_done > 0:
            status = "running"
            status_text = f"进行中 L1 {l1_done}/{l1_total}"
        else:
            status = "pending"
            status_text = "等待"

        books.append({
            "name": book_name[:40],
            "status": status,
            "status_text": status_text,
            "l1_done": l1_done,
            "l1_total": l1_total,
            "l2_done": l2_done,
            "l2_total": l2_total,
            "l3_done": l3_done,
            "is_complete": is_complete,
        })

    seen_names = {b["name"] for b in books}
    txt_dir = XS_ROOT / "data" / "raw" / "novels" / genre
    for txt in sorted(txt_dir.glob("*.txt")):
        name = txt.stem[:40]
        if name not in seen_names:
            books.append({
                "name": name,
                "status": "pending",
                "status_text": "等待",
                "l1_done": 0,
                "l1_total": "?",
                "l2_done": 0,
                "l3_done": False,
                "is_complete": False,
            })

    return books


# ====================== HTTP 处理器 ======================

def _send_json(handler, data, status=200):
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))


def _read_body(handler):
    length = int(handler.headers.get("Content-Length", 0))
    if length == 0:
        return {}
    body = handler.rfile.read(length).decode("utf-8")
    try:
        return json.loads(body)
    except Exception:
        return {}


class ProgressHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _send_static(self, safe_path, mime="text/html"):
        self.send_response(200)
        self.send_header("Content-Type", f"{mime}; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(safe_path.read_bytes())

    def _serve_static(self, path):
        safe_path = (XS_ROOT / "frontend" / path).resolve()
        if not str(safe_path).startswith(str(XS_ROOT / "frontend")):
            self.send_error(403)
            return
        if not safe_path.exists() or safe_path.is_dir():
            self.send_error(404)
            return
        mime = "text/html"
        if safe_path.suffix == ".css":
            mime = "text/css"
        elif safe_path.suffix == ".js":
            mime = "application/javascript"
        elif safe_path.suffix == ".svg":
            mime = "image/svg+xml"
        self._send_static(safe_path, mime)

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/" or path == "/index.html":
                self._serve_static("index.html")
                return
            elif path == "/api/progress":
                qs = parse_qs(parsed.query)
                genre = qs.get("genre", ["末世"])[0]
                books = scan_progress(genre)
                _send_json(self, {"ok": True, "data": books})
                return
            elif path == "/api/hardware":
                cfg = _load_hardware_config()
                with hardware_lock:
                    data = dict(hardware_state)
                data["thresholds"] = {
                    "temp_warn": cfg.get("temp_warn", 82),
                    "temp_stop": cfg.get("temp_stop", 87),
                    "vram_yellow": cfg.get("vram_yellow", 6000),
                    "vram_orange": cfg.get("vram_orange", 6800),
                    "vram_red": cfg.get("vram_red", 7400),
                    "fan_min_percent": cfg.get("fan_min_percent", 5),
                }
                _send_json(self, {"ok": True, "data": data})
                return
            elif path == "/api/status":
                # P1: Read pipeline stage from file
                stage_data = None
                stage_file = XS_ROOT / "data" / "pipeline_stage.json"
                if stage_file.exists():
                    try:
                        stage_data = json.loads(stage_file.read_text(encoding="utf-8"))
                    except (json.JSONDecodeError, OSError):
                        pass
                _send_json(self, {
                    "ok": True,
                    "data": {
                        "running": analysis_is_running(),
                        "hardware_monitor": hardware_running,
                        "pipeline_stage": stage_data,
                        "startup_state": _startup_state,
                    },
                })
                return
            elif path == "/api/startup-status":
                _send_json(self, {"ok": True, "data": _startup_state})
                return
            elif path == "/api/logs":
                with log_lock:
                    logs = list(log_records)
                _send_json(self, {"ok": True, "data": logs})
                return
            elif path.startswith("/api/book/"):
                book_name = path[len("/api/book/"):]
                try:
                    book_name = unquote(book_name)
                except Exception:
                    pass
                genre = parse_qs(parsed.query).get("genre", ["末世"])[0]
                data = _load_book_recursive(book_name, genre)
                if data is None:
                    _send_json(self, {"ok": False, "error": "书籍解析数据不存在"}, 404)
                else:
                    _send_json(self, {"ok": True, "data": data})
                return
            elif path.startswith("/api/score/"):
                book_name = path[len("/api/score/"):]
                try:
                    book_name = unquote(book_name)
                except Exception:
                    pass
                qs = parse_qs(parsed.query)
                genre = qs.get("genre", ["末世"])[0]
                csv_name = _find_rhythm_csv(book_name, genre)
                if not csv_name:
                    _send_json(self, {"ok": False, "error": "未找到节奏数据"}, 404)
                    return
                result = analyze_single_novel(book_name, csv_name, genre)
                if result is None:
                    _send_json(self, {"ok": False, "error": "商业化打分失败"}, 500)
                else:
                    _send_json(self, {"ok": True, "data": result})
                return
            elif path.startswith("/css/") or path.startswith("/js/") or path.startswith("/assets/"):
                self._serve_static(path.strip("/"))
                return
            else:
                self.send_error(404)
                return
        except Exception as e:
            traceback.print_exc()
            _send_json(self, {"ok": False, "error": str(e)}, 500)

    def do_POST(self):
        try:
            body = _read_body(self)
            genre = body.get("genre", "末世")

            if self.path == "/api/start":
                books = body.get("books", [])
                ok, message = start_analysis(genre, books)
                _send_json(self, {"ok": ok, "message": message}, 200 if ok else 409)
            elif self.path == "/api/stop":
                ok, message = stop_analysis()
                _send_json(self, {"ok": ok, "message": message}, 200 if ok else 409)
            else:
                self.send_error(404)
        except Exception as e:
            traceback.print_exc()
            _send_json(self, {"ok": False, "error": str(e)}, 500)

    def log_message(self, format, *args):
        pass


# ====================== 入口 ======================

def main():
    # 启动硬件监控
    start_hardware_monitor()

    print(f"[Progress Server] http://localhost:{PORT}")
    print(f"  API: /api/progress /api/hardware /api/start /api/stop /api/logs /api/status /api/startup-status")
    print(f"  Press Ctrl+C to stop")

    server = HTTPServer(("127.0.0.1", PORT), ProgressHandler)

    def _on_signal(signum, frame):
        print("\n[STOP] Server closed")
        server.server_close()
        sys.exit(0)

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _on_signal(None, None)


if __name__ == "__main__":
    main()
