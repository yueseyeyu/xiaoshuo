# -*- coding: utf-8 -*-
"""
cache_manager.py — 章节级缓存管理
===================================
CSV 缓存命中检测 + 章节哈希比对 + 版本号管理。
"""
from __future__ import annotations

import csv
from pathlib import Path

from xiaoshuo.infra.logging_config import get_logger

logger = get_logger("rhythm.cache_manager")

# v11: 章节级缓存版本 (rule_analyze 逻辑变更时递增, 触发全量重分析)
CACHE_VERSION = 13


def load_cached_summary(csv_path, name):
    """Reconstruct summary dict from existing rhythm CSV (cache hit path)."""
    rows = []
    try:
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                rows.append(r)
    except Exception:
        return None
    if not rows:
        return None
    total = len(rows)
    total_wc = sum(int(r.get("wc", 0)) for r in rows)
    p_density = sum(1 for r in rows if r.get("pleasure_type", "none") != "none") / max(total, 1)
    c_rate = sum(1 for r in rows if r.get("conflict", "")) / max(total, 1)
    avg_int = sum(float(r.get("pleasure_intensity", 0)) for r in rows) / max(total, 1)
    avg_hk = sum(float(r.get("hook_density", 0)) for r in rows) / max(total, 1)
    sub_dist = {}
    for r in rows:
        s = r.get("dominant_sub", "none")
        sub_dist[s] = sub_dist.get(s, 0) + 1
    return {
        "name": name, "total_chaps": total, "total_words": total_wc,
        "avg_wc": total_wc // max(total, 1),
        "pleasure_density": round(p_density, 2),
        "conflict_rate": round(c_rate, 2),
        "avg_intensity": round(avg_int, 1),
        "avg_hook": round(avg_hk, 1),
        "sub_dist": {k: v for k, v in sorted(sub_dist.items(), key=lambda x: -x[1])},
        "llm_correlation": None,
    }


def check_cache_version(version_path):
    """检查缓存版本是否匹配当前 CACHE_VERSION。"""
    if not version_path.exists():
        return False
    try:
        stored = int(version_path.read_text(encoding="utf-8").strip())
        return stored == CACHE_VERSION
    except (ValueError, OSError):
        return False


def save_cache_version(version_path):
    """保存当前缓存版本号。"""
    version_path.write_text(str(CACHE_VERSION), encoding="utf-8")
