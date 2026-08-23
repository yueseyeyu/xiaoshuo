# -*- coding: utf-8 -*-
"""Lazy, explicit logging configuration for governed pipeline execution."""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from datetime import datetime

from xiaoshuo.pipeline.provenance import (
    ExecutionContext,
    execution_root,
    get_execution_context,
    record_call,
    _validate_root_path,
)


_loggers: dict[str, logging.Logger] = {}
_configured_contexts: set[str] = set()


def get_logger(name: str) -> logging.Logger:
    """Return a logger without creating a directory or file.

    This function is safe for module-level logger declarations.  A file
    handler can only be installed by the explicit ``configure_logging`` call
    after project/profile/stage/run validation.
    """
    if name not in _loggers:
        logger = logging.getLogger(f"xiaoshuo.{name}")
        _loggers[name] = logger
    return _loggers[name]


def configure_logging(
    context: ExecutionContext | None = None,
    *,
    level: int = logging.DEBUG,
) -> Path:
    """Install a D-drive rotating file handler for an explicit context."""
    context = context or get_execution_context(True)
    preflight_root = execution_root(context, create=False)
    preflight_log_dir = _validate_root_path(preflight_root / "logs", preflight_root)
    today = datetime.now().strftime("%Y%m%d")
    _validate_root_path(preflight_log_dir / f"xiaoshuo_{today}.log", preflight_root)
    root_dir = execution_root(context, create=True)
    log_dir = _validate_root_path(root_dir / "logs", root_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_dir = _validate_root_path(log_dir, root_dir)
    key = str(root_dir.resolve())
    root = logging.getLogger("xiaoshuo")
    root.setLevel(level)
    if key not in _configured_contexts:
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(logging.INFO)
        console.setFormatter(logging.Formatter("[%(levelname)-5s] %(name)s: %(message)s"))
        root.addHandler(console)
        log_file = _validate_root_path(log_dir / f"xiaoshuo_{today}.log", root_dir)
        file_handler = logging.handlers.TimedRotatingFileHandler(
            filename=str(log_file),
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
        _configured_contexts.add(key)
        record_call("logger")
    return log_dir


def close_logging() -> None:
    """Close only handlers owned by the xiaoshuo logger."""
    root = logging.getLogger("xiaoshuo")
    for handler in list(root.handlers):
        root.removeHandler(handler)
        try:
            handler.close()
        except OSError:
            pass
    _configured_contexts.clear()


__all__ = ["close_logging", "configure_logging", "get_logger"]
