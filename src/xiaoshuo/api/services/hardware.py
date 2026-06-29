"""硬件监控服务 — GPU 温度/显存/风扇 + 系统内存，线程安全"""

from __future__ import annotations
import atexit
import threading
import time
import psutil

from xiaoshuo.infra.hardware_guardian import (
    _init_nvml,
    _read_gpu_temp_pynvml,
    _read_vram_used_pynvml,
    _read_fan_speed_pynvml,
    _read_gpu_temp_smi,
    _read_vram_used_smi,
    _read_vram_total_smi,
    _read_gpu_util_smi,
    _read_fan_speed_smi,
)

# ── 全局状态 ──

hardware_state = {
    "gpu_temp": None, "vram_used_mb": None, "vram_total_mb": None,
    "fan_speed": None, "sys_memory_used_gb": None, "sys_memory_total_gb": None,
    "cpu_percent": 0.0,  # CPU 利用率缓存（由监控线程持续采样）
    "gpu_available": False, "updated_at": None,
}
hardware_lock = threading.Lock()
hardware_running = False

# NVML 缓存
_nvml_cached = None
_nvml_handle_cached = None
_nvml_init_attempted = False


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
    """读取一次硬件指标"""
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
        result["vram_total_mb"] = _read_vram_total_smi()
        result["fan_speed"] = _read_fan_speed_smi()
        result["gpu_util"] = _read_gpu_util_smi()
        result["gpu_available"] = (
            result["gpu_temp"] is not None
            or result["vram_used_mb"] is not None
            or result["fan_speed"] is not None
        )
    try:
        mem = psutil.virtual_memory()
        result["sys_memory_used_gb"] = round(mem.used / (1024 ** 3), 2)
        result["sys_memory_total_gb"] = round(mem.total / (1024 ** 3), 2)
        # 用 0.5 秒采样获取有意义的 CPU 利用率（首次调用 interval=None 返回 0）
        result["cpu_percent"] = round(psutil.cpu_percent(interval=0.5), 1)
    except Exception:
        pass
    return result


def hardware_monitor_loop():
    """硬件监控主循环（在后台线程中运行）"""
    global hardware_state, hardware_running
    print(f"[HW MON] loop start, hardware_running={hardware_running}", flush=True)
    while hardware_running:
        try:
            data = _read_hardware_once()
            data["updated_at"] = time.strftime("%H:%M:%S")
            with hardware_lock:
                # 原地更新 dict（保持引用一致），不要用 hardware_state = data
                hardware_state.clear()
                hardware_state.update(data)
        except Exception as e:
            import traceback
            print(f"[HARDWARE MONITOR ERROR] {e}", flush=True)
            traceback.print_exc()
        time.sleep(1)


def start_hardware_monitor():
    """启动硬件监控线程"""
    global hardware_running
    hardware_running = True
    t = threading.Thread(target=hardware_monitor_loop, daemon=True)
    t.start()
    return t


def stop_hardware_monitor():
    """停止硬件监控"""
    global hardware_running
    hardware_running = False
    _shutdown_cached_nvml()


def get_hardware_snapshot() -> dict:
    """获取硬件状态快照（线程安全）"""
    with hardware_lock:
        return dict(hardware_state)