# -*- coding: utf-8 -*-
"""
xiaoshuo.infra.logging_config — 结构化日志系统
===============================================
v7.5: 替代全仓 print() 调用，提供统一的日志入口。
- 控制台: INFO 级别，简洁输出
- 文件: DEBUG 级别，完整上下文，轮转 7 天
- 用法: from xiaoshuo.infra.logging_config import get_logger
        logger = get_logger(__name__)
        logger.info("Processing book %s", book_name)
"""

import logging
import logging.handlers
import sys
from pathlib import Path
from datetime import datetime


_loggers: dict[str, logging.Logger] = {}
_initialized: bool = False


def _ensure_initialized():
    """延迟初始化，避免 import 时自动创建日志目录。"""
    global _initialized
    if _initialized:
        return

    from xiaoshuo import PROJECT_ROOT
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("xiaoshuo")
    root.setLevel(logging.DEBUG)

    # ── 控制台 handler: INFO+ ──
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(
        "[%(levelname)-5s] %(name)s: %(message)s"
    ))
    root.addHandler(console)

    # ── 文件 handler: DEBUG+, 轮转 7 天 ──
    today = datetime.now().strftime("%Y%m%d")
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=str(log_dir / f"xiaoshuo_{today}.log"),
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-5s] %(name)s:%(lineno)d: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root.addHandler(file_handler)

    _initialized = True


def get_logger(name: str) -> logging.Logger:
    """获取日志器。自动初始化（首次调用时创建日志目录）。"""
    _ensure_initialized()
    if name not in _loggers:
        _loggers[name] = logging.getLogger(f"xiaoshuo.{name}")
    return _loggers[name]