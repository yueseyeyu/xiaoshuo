#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
switch_model.py — 单GPU多模型串行切换工具
用法: python scripts/switch_model.py qwen3   (切换到Qwen3.5)
      python scripts/switch_model.py r1       (切换到DeepSeek-R1)
      python scripts/switch_model.py status   (查看当前运行模型)

设计: 同一时间只跑一个llama-server实例。切换时:
  1. 检测当前进程 (通过端口占用判断)
  2. 发送 /v1/shutdown 优雅停止 (或 kill)
  3. 启动目标模型 llama-server
  4. 轮询 /health 直到就绪
  5. 报告状态

显存约束: RTX 5060 8GB, Qwen3.5-9B≈6.2GB + DeepSeek-7B≈4.3GB
不可同时GPU加载, 串行切换是最优解。
"""
import subprocess
import urllib.request
import time
import sys
import json
from pathlib import Path

try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── 模型配置 (从 config.yaml 动态读取, 此处为硬编码快照) ──
# 实际运行时优先读 config.yaml
MODELS = {
    "qwen3": {
        "name": "Qwen3.5-9B-Instruct",
        "gguf": "D:/DaMoXing/Qwen3.5-9B-Q4_K_M.gguf",
        "port": 8000,
        "n_ctx": 4096,
        "n_gpu_layers": 35,
        "chat_format": "chatml",
    },
    "r1": {
        "name": "DeepSeek-R1-0528-Qwen3-8B",
        "gguf": "D:/DaMoXing/DeepSeek-R1-0528-Qwen3-8B-Q4_K_M.gguf",
        "port": 8002,
        "n_ctx": 4096,
        "n_gpu_layers": 24,
        "chat_format": "chatml",
    },
}

LLAMA_SERVER = "D:/miniconda3/envs/llm-shared/Library/bin/llama-server.exe"


def _load_config_models():
    """Read model configs from config.yaml if available."""
    if not _HAS_YAML:
        return MODELS
    try:
        cfg_path = PROJECT_ROOT / "config.yaml"
        if cfg_path.exists():
            with open(cfg_path, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f)
            models_cfg = cfg.get("model_orchestration", {}).get("models", {})
            result = {}
            for key, mc in models_cfg.items():
                gguf = mc.get("gguf", "")
                if not gguf or not Path(gguf).exists():
                    continue
                short = "qwen3" if "Qwen3.5" in mc.get("name", "") else \
                        "r1" if "DeepSeek" in mc.get("name", "") else key
                result[short] = {
                    "name": mc.get("name", key),
                    "gguf": gguf,
                    "port": mc.get("port", 8000),
                    "n_ctx": mc.get("n_ctx", 4096),
                    "n_gpu_layers": mc.get("n_gpu_layers", 35),
                    "chat_format": mc.get("chat_format", "chatml"),
                }
            if result:
                return result
    except Exception as e:
        print(f"[WARN] Failed to load config.yaml: {e}, using built-in models", file=sys.stderr)
    return MODELS  # fallback to built-in


def _check_port(port):
    """Check if a server is responding on given port."""
    try:
        r = urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3)
        return r.read().decode() == '{"status":"ok"}'
    except Exception:
        return False


def _kill_server(port):
    """Gracefully stop server on given port."""
    # Try graceful shutdown API first
    try:
        urllib.request.urlopen(
            f"http://127.0.0.1:{port}/v1/shutdown",
            timeout=5,
        )
        time.sleep(2)
        if not _check_port(port):
            return True
    except Exception:
        pass

    # Fallback: kill by port (Windows)
    try:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.split("\n"):
            if f":{port}" in line and "LISTENING" in line:
                pid = line.strip().split()[-1]
                subprocess.run(["taskkill", "/F", "/PID", pid],
                             capture_output=True, timeout=10)
                time.sleep(1)
                break
    except Exception:
        print(f"  [WARN] Could not kill process on port {port}")

    return not _check_port(port)


def _start_server(model_cfg):
    """Start llama-server with given model config."""
    port = model_cfg["port"]
    cmd = [
        LLAMA_SERVER,
        "--model", model_cfg["gguf"],
        "--port", str(port),
        "--n-gpu-layers", str(model_cfg["n_gpu_layers"]),
        "--ctx-size", str(model_cfg["n_ctx"]),
        "--chat-template", model_cfg.get("chat_format", "chatml"),
        "--host", "127.0.0.1",
    ]

    # Detach process (no console window on Windows)
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        startupinfo=startupinfo,
    )

    # Wait for server to be ready (poll /health up to 60s)
    for _ in range(60):
        time.sleep(1)
        if _check_port(port):
            return proc
    return None


def switch(target_name):
    """Switch to target model. Returns True if successful."""
    models = _load_config_models()

    if target_name not in models:
        print(f"[FAIL] Unknown model: {target_name}")
        print(f"  Available: {', '.join(models.keys())}")
        return False

    target_cfg = models[target_name]
    target_port = target_cfg["port"]

    # ── Step 1: Check if target is already running ──
    if _check_port(target_port):
        # Check which model is on this port
        try:
            r = urllib.request.urlopen(f"http://127.0.0.1:{target_port}/v1/models", timeout=5)
            data = json.loads(r.read())
            current_name = data.get("data", [{}])[0].get("id", "unknown")
            if target_cfg["name"] in current_name or current_name == target_cfg["name"]:
                print(f"[OK] {target_name} ({target_cfg['name']}) already running on :{target_port}")
                return True
        except Exception:
            pass

    # ── Step 2: Kill old server on target port ──
    if _check_port(target_port):
        print(f"  Stopping existing server on :{target_port}...")
        if not _kill_server(target_port):
            print(f"[FAIL] Could not stop server on :{target_port}")
            return False

    # ── Step 3: Also kill other model servers to free GPU VRAM ──
    for key, cfg in models.items():
        if key == target_name:
            continue
        if _check_port(cfg["port"]):
            print(f"  Freeing VRAM: stopping {key} on :{cfg['port']}...")
            _kill_server(cfg["port"])

    # ── Step 4: Start target model ──
    print(f"  Starting {target_cfg['name']} on :{target_port}...")
    proc = _start_server(target_cfg)
    if proc is None:
        print(f"[FAIL] {target_name} failed to start within 60s")
        return False

    # ── Step 5: Verify ──
    try:
        r = urllib.request.urlopen(f"http://127.0.0.1:{target_port}/v1/models", timeout=5)
        data = json.loads(r.read())
        name = data.get("data", [{}])[0].get("id", "unknown")
        print(f"[OK] {target_name} ({name}) ready on :{target_port}")
        return True
    except Exception:
        print(f"[WARN] Server started but /v1/models check failed")
        return True  # Health check passed, models API might be slow


def show_status():
    """Display status of all configured models."""
    models = _load_config_models()
    print("Model Status:")
    print(f"{'Alias':10s} {'Name':35s} {'Port':>6s} {'Status':>10s}")
    print("-" * 65)
    for key, cfg in models.items():
        running = _check_port(cfg["port"])
        print(f"{key:10s} {cfg['name']:35s} {cfg['port']:6d} "
              f"{'[RUNNING]' if running else '[STOPPED]':>10s}")


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("status", "--status"):
        show_status()
        return

    target = sys.argv[1].lower()
    if target == "list":
        models = _load_config_models()
        for k, v in models.items():
            print(f"  {k:10s} -> {v['name']}  (:{v['port']}, {Path(v['gguf']).stat().st_size/1e9:.1f}GB)")
        return

    ok = switch(target)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
