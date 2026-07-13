# -*- coding: utf-8 -*-
"""canon — 设定管理管线：提取 + 填充 + 一致性检查 + RP推演 + 分层记忆 + 风格规则"""
from .schema import (
    CANON_SCHEMAS,
    STYLE_RULES_SCHEMA,
    validate_canon,
    CanonEntry,        # v8.8: 双时间机制
    CanonVersionStore, # v8.8: 设定版本存储
)
from .extractor import CanonExtractor
from .rp_simulator import RPSimulator, LayeredMemory
from .consistency_checker import ConsistencyChecker
