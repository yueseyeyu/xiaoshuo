# -*- coding: utf-8 -*-
"""canon — 设定管理管线：提取 + 填充 + 一致性检查 + RP推演 + 分层记忆"""
from .schema import CANON_SCHEMAS, validate_canon
from .extractor import CanonExtractor
from .rp_simulator import RPSimulator, LayeredMemory
from .consistency_checker import ConsistencyChecker