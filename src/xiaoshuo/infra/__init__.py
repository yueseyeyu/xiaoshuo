# -*- coding: utf-8 -*-
"""
xiaoshuo.infra — 基础设施层
===========================
硬件监控、系统守护、日志、配置管理、性能监控、数据校验。
"""
from xiaoshuo.infra.hardware_guardian import HardwareGuardian
from xiaoshuo.infra.logging_config import get_logger
from xiaoshuo.infra.config_manager import get_config, reload_config, get_config_section
from xiaoshuo.infra.performance import timed, PipelineTimer
from xiaoshuo.infra.schemas import (
    validate_state, validate_novel_index, safe_load_json,
    STATE_SCHEMA, NOVEL_INDEX_SCHEMA,
)

__all__ = [
    "HardwareGuardian",
    "get_logger",
    "get_config", "reload_config", "get_config_section",
    "timed", "PipelineTimer",
    "validate_state", "validate_novel_index", "safe_load_json",
    "STATE_SCHEMA", "NOVEL_INDEX_SCHEMA",
]