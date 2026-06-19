# -*- coding: utf-8 -*-
"""
xiaoshuo.infra.performance — 性能监控工具
=========================================
v7.5: @timed 装饰器 + 管线阶段计时。

用法:
    from xiaoshuo.infra.performance import timed, PipelineTimer

    @timed
    def my_slow_function():
        ...

    pt = PipelineTimer("genre_synthesis")
    pt.start()
    ...
    pt.stop()  # 自动记录到日志
"""

import time
import functools
from xiaoshuo.infra.logging_config import get_logger

_logger = get_logger("performance")


def timed(func=None, *, label: str = ""):
    """装饰器：记录函数执行耗时。

    用法:
        @timed
        def foo(): ...

        @timed(label="custom_name")
        def bar(): ...
    """
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            name = label or f"{f.__module__}.{f.__qualname__}"
            start = time.perf_counter()
            try:
                return f(*args, **kwargs)
            finally:
                elapsed = time.perf_counter() - start
                _logger.debug("[timed] %s: %.3f s", name, elapsed)
        return wrapper

    if func is not None:
        return decorator(func)
    return decorator


class PipelineTimer:
    """管线阶段计时器。记录阶段名称 + 耗时，汇总输出。

    用法:
        pt = PipelineTimer("genre_synthesis")
        pt.start()
        # ... work ...
        pt.stop()
        pt.report()  # 可选：打印汇总
    """

    _stages: list[dict] = []

    def __init__(self, name: str):
        self.name = name
        self._start: float = 0.0
        self._elapsed: float = 0.0

    def start(self):
        self._start = time.perf_counter()

    def stop(self):
        self._elapsed = time.perf_counter() - self._start
        _logger.info("[timer] %s: %.1f s", self.name, self._elapsed)
        PipelineTimer._stages.append({
            "name": self.name,
            "elapsed_s": round(self._elapsed, 2),
        })

    @property
    def elapsed(self) -> float:
        return self._elapsed

    @classmethod
    def report(cls):
        """打印所有阶段耗时汇总。"""
        if not cls._stages:
            return
        _logger.info("=" * 50)
        _logger.info("  Pipeline Timing Summary")
        _logger.info("=" * 50)
        total = 0.0
        for s in cls._stages:
            _logger.info("  %-35s %7.1f s", s["name"], s["elapsed_s"])
            total += s["elapsed_s"]
        _logger.info("  %-35s %7.1f s", "TOTAL", total)
        _logger.info("=" * 50)

    @classmethod
    def reset(cls):
        cls._stages.clear()