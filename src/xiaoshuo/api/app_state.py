"""应用全局状态管理 v8.1 — 线程安全的集中式状态容器"""

from __future__ import annotations
import subprocess
import threading
import time
from typing import Optional


class AppState:
    """应用全局状态（线程安全）"""

    def __init__(self):
        self._lock = threading.Lock()

        # 日志队列
        self._max_logs = 500
        self._log_records: list[dict] = []

        # 拆书进程管理
        self._analyze_process: Optional[subprocess.Popen] = None

        # 启动状态
        self._startup_status = "idle"
        self._startup_message = ""
        self._startup_progress = 0
        self._startup_error = ""

    # ── 日志管理 ──

    @property
    def log_records(self) -> list[dict]:
        with self._lock:
            return list(self._log_records)

    @property
    def log_count(self) -> int:
        with self._lock:
            return len(self._log_records)

    def add_log(self, record: dict):
        with self._lock:
            self._log_records.append(record)
            if len(self._log_records) > self._max_logs:
                self._log_records = self._log_records[-self._max_logs:]

    def clear_logs(self):
        with self._lock:
            self._log_records.clear()

    def get_logs_filtered(self, keyword: str) -> list[dict]:
        with self._lock:
            return [r for r in self._log_records if keyword in r.get("message", "").lower()]

    # ── 拆书进程 ──

    @property
    def analyze_process(self) -> Optional[subprocess.Popen]:
        with self._lock:
            return self._analyze_process

    @analyze_process.setter
    def analyze_process(self, proc: Optional[subprocess.Popen]):
        with self._lock:
            self._analyze_process = proc

    # ── 启动状态 ──

    def get_startup_state(self) -> dict:
        with self._lock:
            return {
                "status": self._startup_status,
                "message": self._startup_message,
                "progress": self._startup_progress,
                "error": self._startup_error,
            }

    def set_startup_state(self, status: str = "", message: str = "",
                          progress: int = -1, error: str = ""):
        with self._lock:
            if status:
                self._startup_status = status
            if message:
                self._startup_message = message
            if progress >= 0:
                self._startup_progress = progress
            if error:
                self._startup_error = error


# 全局单例
app_state = AppState()