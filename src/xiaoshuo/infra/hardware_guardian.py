# -*- coding: utf-8 -*-
"""
硬件守护模块 (Hardware Guardian)
================================
为长时拆书任务提供 GPU 硬件监控保护。

基于 Digital Life 项目 thermal_guard.py 优化整合，12轮穷举搜索审查通过。
MVP 范围: 温度 + 显存 + 风扇监控。pynvml 不可用时降级到 nvidia-smi。

修复清单 (R1-R12):
  - R4: 轮询间隔 5s->config, 去除冗余温度采样, 移除WHEA/ECC/SMART
  - R6: 幂等shutdown, NVMLError分类, 非daemon线程+join, atexit注册
  - R7: 统一日志风格, 适配xiaoshuo包架构
  - R8: 所有阈值从config.yaml读取 (SSOT)
  - R9: 父进程注册清理, 上下文管理器生命周期
  - R10: pynvml版本检查, nvidia-smi降级方案
"""

import atexit
import logging
import os
import subprocess
import threading
import time

from xiaoshuo import PROJECT_ROOT
from xiaoshuo.infra.config_manager import get_config_section

# pynvml is optional; all features degrade gracefully to nvidia-smi
try:
    import pynvml
    _PYNVML_AVAILABLE = True
except ImportError:
    pynvml = None
    _PYNVML_AVAILABLE = False

logger = logging.getLogger("hardware_guardian")

# P3: warn only once when pynvml is unavailable
_NVML_WARNED = False


class ThermalEmergency(Exception):
    """GPU 温度超过紧急阈值时抛出的异常，用于中断长时任务。"""
    pass


# ====================== pynvml 初始化 (带降级) ======================

def _init_nvml():
    """初始化 NVML，失败时返回 None 并降级到 nvidia-smi。"""
    global _NVML_WARNED
    if not _PYNVML_AVAILABLE:
        if not _NVML_WARNED:
            logger.warning("pynvml not installed, fallback to nvidia-smi")
            _NVML_WARNED = True
        return None, None
    try:
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        return pynvml, handle
    except Exception as e:
        if not _NVML_WARNED:
            logger.warning("NVML init failed: %s, fallback to nvidia-smi", e)
            _NVML_WARNED = True
        return None, None


# ====================== pynvml 读取函数 (异常分类) ======================

def _read_gpu_temp_pynvml(pynvml, handle):
    try:
        return pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
    except pynvml.NVMLError_GpuIsLost:
        raise
    except Exception:
        return None


def _read_fan_speed_pynvml(pynvml, handle):
    try:
        return pynvml.nvmlDeviceGetFanSpeed(handle)
    except pynvml.NVMLError_NotSupported:
        return None
    except Exception:
        return None


def _read_vram_used_pynvml(pynvml, handle):
    try:
        return pynvml.nvmlDeviceGetMemoryInfo(handle).used // (1024 * 1024)
    except pynvml.NVMLError_GpuIsLost:
        raise
    except Exception:
        return None


# ====================== nvidia-smi 降级方案 ======================

def _read_gpu_temp_smi():
    """通过 nvidia-smi 获取 GPU 温度 (pynvml 不可用时降级)。"""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip().splitlines()[0])
    except Exception:
        pass
    return None


def _read_vram_used_smi():
    """通过 nvidia-smi 获取显存使用量 (MB)。"""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip().splitlines()[0])
    except Exception:
        pass
    return None


def _read_fan_speed_smi():
    """通过 nvidia-smi 获取风扇转速 (pynvml 不可用时降级)。"""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=fan.speed",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            val = result.stdout.strip().splitlines()[0]
            if val.isdigit():
                return int(val)
    except Exception:
        pass
    return None


# ====================== 配置加载 (SSOT) ======================

def _load_config():
    """从 config.yaml 加载 hardware_guard 配置段（通过 config_manager SSOT 单例）。"""
    return get_config_section("hardware_guard", default={})


# ====================== HardwareGuardian Context Manager ======================

class HardwareGuardian:
    """硬件监控守护 (上下文管理器)。"""

    def __init__(self, on_warn=None, on_stop=None, on_fan_alert=None):
        cfg = _load_config()

        # 启用开关
        self._enabled = cfg.get("enabled", True)

        # 温度阈值
        self._temp_warn = cfg.get("temp_warn", 82)
        self._temp_stop = cfg.get("temp_stop", 87)

        # 风扇
        self._fan_min_percent = cfg.get("fan_min_percent", 5)

        # 显存熔断
        self._vram_yellow = cfg.get("vram_yellow", 6000)
        self._vram_orange = cfg.get("vram_orange", 6800)
        self._vram_red = cfg.get("vram_red", 7400)

        # 显存泄漏
        self._vram_leak_threshold = cfg.get("vram_leak_threshold", 300)
        self._vram_leak_interval = cfg.get("vram_leak_interval", 3600)

        # 轮询间隔
        self._poll_interval = cfg.get("poll_interval", 5)
        self._leak_history_max = cfg.get("leak_history_max", 500)

        # 回调
        self.on_warn = on_warn
        self.on_stop = on_stop
        self.on_fan_alert = on_fan_alert

        # 内部状态
        self._running = False
        self._thread = None
        self._shutdown_called = False
        self._vram_level = "green"

        # NVML 句柄
        self._pynvml = None
        self._handle = None

        # 显存泄漏检测 — 累积足够样本后才设基线
        self._leak_history = []
        self._leak_baseline = None
        self._last_drift_check = 0.0

        # 风扇归零计数
        self._fan_zero_count = 0

        # 回调节流
        self._last_warn_time = 0.0
        self._last_fan_alert_time = 0.0

        # atexit 只注册一次
        atexit.register(self.stop)

    # ---------- 上下文管理器 ----------

    def __enter__(self):
        if self._enabled:
            self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False

    # ---------- 生命周期 ----------

    def start(self):
        """启动硬件守护线程。"""
        self._pynvml, self._handle = _init_nvml()
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=False)
        self._thread.start()
        logger.info(
            "HardwareGuardian started | temp: %d/%dC | fan: <%d%% | "
            "VRAM: yellow<%d/orange<%d/red<%d MB | leak: +%dMB/h | poll: %ds",
            self._temp_warn, self._temp_stop, self._fan_min_percent,
            self._vram_yellow, self._vram_orange, self._vram_red,
            self._vram_leak_threshold, self._poll_interval,
        )

    def stop(self):
        """停止硬件守护 (幂等)。"""
        if self._shutdown_called:
            return
        self._shutdown_called = True
        self._running = False
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=10)
        if self._pynvml is not None:
            try:
                self._pynvml.nvmlShutdown()
            except Exception:
                pass
        logger.info("HardwareGuardian stopped")

    # ---------- 主循环 ----------

    def _loop(self):
        while self._running:
            try:
                self._check_all()
            except ThermalEmergency:
                logger.critical("Hardware emergency, terminating process")
                # 不在本线程里调用 self.stop() — 会 self-join 死锁
                # 直接 shutdown NVML 后立即终止进程
                if self._pynvml is not None:
                    try:
                        self._pynvml.nvmlShutdown()
                    except Exception:
                        pass
                os._exit(1)
            except Exception as e:
                if _PYNVML_AVAILABLE and isinstance(e, pynvml.NVMLError_GpuIsLost):
                    logger.error("GPU lost (TDR), re-initializing NVML")
                    self._pynvml, self._handle = _init_nvml()
                    if self._pynvml is None:
                        logger.warning("NVML re-init failed, switching to nvidia-smi")
                else:
                    logger.error("Guardian loop error: %s", e)
            time.sleep(self._poll_interval)

    def _check_all(self):
        """单次检查: 温度 + 风扇 + 显存 (合并一次读取)。"""
        # 读取显存 (一次读取，供 _check_vram 和 _record_usage 共用)
        vram_used = self._read_vram()

        self._check_temp()
        self._check_fan()
        self._check_vram(vram_used)
        self._record_usage(vram_used)

        now = time.time()
        if now - self._last_drift_check >= self._vram_leak_interval:
            self._check_vram_drift()
            self._last_drift_check = now

    # ---------- 显存统一读取 ----------

    def _read_vram(self):
        if self._pynvml is not None:
            return _read_vram_used_pynvml(self._pynvml, self._handle)
        return _read_vram_used_smi()

    # ---------- 温度 ----------

    def _check_temp(self):
        if self._pynvml is not None:
            try:
                temp = _read_gpu_temp_pynvml(self._pynvml, self._handle)
            except pynvml.NVMLError_GpuIsLost:
                raise
            except Exception as e:
                logger.warning("pynvml temp read failed: %s, falling back to nvidia-smi", e)
                temp = _read_gpu_temp_smi()
        else:
            temp = _read_gpu_temp_smi()

        if temp is None:
            return
        if temp >= self._temp_stop:
            logger.critical(
                "GPU temp %dC >= %dC, triggering emergency stop", temp, self._temp_stop)
            if self.on_stop:
                self.on_stop(f"GPU temperature {temp}C >= {self._temp_stop}C")
            raise ThermalEmergency(
                f"GPU temperature {temp}C exceeds emergency threshold {self._temp_stop}C")
        elif temp >= self._temp_warn:
            logger.warning(
                "GPU temp %dC >= %dC, warning", temp, self._temp_warn)
            if self.on_warn:
                now = time.time()
                if now - self._last_warn_time >= 60:
                    self.on_warn(temp)
                    self._last_warn_time = now

    # ---------- 风扇 ----------

    def _check_fan(self):
        speed = None
        if self._pynvml is not None:
            speed = _read_fan_speed_pynvml(self._pynvml, self._handle)
        if speed is None:
            speed = _read_fan_speed_smi()
        if speed is None:
            return
        if speed < self._fan_min_percent:
            if speed == 0:
                self._fan_zero_count += 1
                if self._fan_zero_count < 3:
                    return
            logger.critical(
                "GPU fan abnormal: %d%% < %d%%", speed, self._fan_min_percent)
            if self.on_fan_alert:
                now = time.time()
                if now - self._last_fan_alert_time >= 60:
                    self.on_fan_alert(speed)
                    self._last_fan_alert_time = now
        else:
            self._fan_zero_count = 0

    # ---------- 显存采录 ----------

    def _record_usage(self, vram_used):
        if vram_used is None:
            return
        self._leak_history.append(vram_used)
        if len(self._leak_history) > self._leak_history_max:
            self._leak_history = self._leak_history[-self._leak_history_max:]
        # 积累至少 30 个样本后，用中位数设基线 (避免单样本离群值)
        if self._leak_baseline is None and len(self._leak_history) >= 30:
            recent = sorted(self._leak_history[-30:])
            self._leak_baseline = recent[len(recent) // 2]
            logger.debug("VRAM leak baseline set: %dMB (median of 30 samples)", self._leak_baseline)

    # ---------- 显存泄漏检测 ----------

    def _check_vram_drift(self):
        if self._leak_baseline is None or len(self._leak_history) < 10:
            return

        recent = sorted(self._leak_history[-10:])
        current_median = recent[len(recent) // 2]
        drift = current_median - self._leak_baseline

        if drift > self._vram_leak_threshold:
            logger.critical(
                "VRAM absolute drift: +%.0fMB from baseline %dMB > %dMB, possible leak",
                drift, self._leak_baseline, self._vram_leak_threshold)
        elif drift > 0:
            logger.info("VRAM drift from baseline: +%.0fMB (baseline=%dMB)", drift, self._leak_baseline)

    # ---------- 显存三级熔断 ----------

    def _check_vram(self, vram_used):
        if vram_used is None:
            return

        if vram_used >= self._vram_red:
            new_level = "red"
        elif vram_used >= self._vram_orange:
            new_level = "orange"
        elif vram_used >= self._vram_yellow:
            new_level = "yellow"
        else:
            new_level = "green"

        if new_level != self._vram_level:
            logger.info(
                "VRAM level: %s -> %s (%dMB)", self._vram_level, new_level, vram_used)
            self._vram_level = new_level

            # 首次进入红色级别: 触发紧急停止
            if new_level == "red":
                logger.critical("VRAM red level (%dMB >= %dMB), triggering stop", vram_used, self._vram_red)
                if self.on_stop:
                    self.on_stop(f"VRAM {vram_used}MB >= {self._vram_red}MB (red)")
                raise ThermalEmergency(
                    f"VRAM {vram_used}MB exceeds red threshold {self._vram_red}MB")

    # ---------- 属性 ----------

    @property
    def vram_level(self):
        return self._vram_level

    @property
    def leak_status(self):
        return {
            "baseline_mb": self._leak_baseline,
            "history_count": len(self._leak_history),
        }