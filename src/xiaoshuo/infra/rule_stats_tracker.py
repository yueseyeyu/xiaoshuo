# -*- coding: utf-8 -*-
"""
rule_stats_tracker.py — 检测规则误报统计 + 自动降级建议
=====================================================
v8.8: 借鉴 second-brain-kit v2.0 的"四档输出 + 自动降级"机制，
但不集中化检测逻辑。各检测模块（ai_flavor_detector / golden3_analyzer /
s3_extensions 等）按需调用此模块记录统计、查询降级建议。

设计原则:
- 轻量: 仅 stdlib，无新依赖
- 非侵入: 检测模块可以选择性调用，不调用也不影响功能
- 持久化: 统计数据持久化到 data/checkpoints/rule_stats.json
- 线程安全: 文件读写加锁

用法:
    from xiaoshuo.infra.rule_stats_tracker import get_tracker

    tracker = get_tracker()

    # 记录一次检测结果
    tracker.record("ai_flavor.mental_prefix", "WARNING", user_feedback="false_positive")

    # 查询是否应该降级
    if tracker.should_demote("ai_flavor.mental_prefix"):
        severity = tracker.demote_severity("WARNING")  # WARNING -> LOW

    # 获取校准后的阈值
    threshold = tracker.get_calibrated_threshold("ai_flavor.mental_prefix", default=0.05)
"""

import json
import threading
import time
from pathlib import Path
from typing import Optional

from xiaoshuo import PROJECT_ROOT
from xiaoshuo.infra.logging_config import get_logger

_logger = get_logger(__name__)

# 统计数据持久化路径
STATS_PATH = PROJECT_ROOT / "data" / "checkpoints" / "rule_stats.json"

# 降级阈值配置
DEMOTION_CONFIG = {
    "min_samples": 20,         # 至少检测 20 次后才考虑降级
    "fp_rate_threshold": 0.70, # 误报率 > 70% 触发降级
    "recent_window": 10,       # 最近 10 次检测窗口
    "recent_fp_threshold": 0.50,  # 最近 10 次中误报率 > 50% 也触发
}

# 严重级别降级映射
_SEVERITY_DEMOTION = {
    "HIGH": "MEDIUM",
    "MEDIUM": "LOW",
    "LOW": "SILENT",
    "BLOCK": "WARNING",
    "WARNING": "PASS",
    # ok/info 级别不降级
}


class RuleStatsTracker:
    """检测规则误报统计 + 自动降级建议。

    线程安全单例。统计数据持久化到 JSON 文件。
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self._stats: dict[str, dict] = {}
        self._file_lock = threading.Lock()
        self._load()

    # ── 持久化 ──

    def _load(self) -> None:
        """从 JSON 文件加载统计数据。"""
        if not STATS_PATH.exists():
            self._stats = {}
            return
        try:
            with open(STATS_PATH, "r", encoding="utf-8") as f:
                self._stats = json.load(f) or {}
        except (json.JSONDecodeError, OSError) as e:
            _logger.warning("rule_stats 加载失败，使用空统计: %s", e)
            self._stats = {}

    def _save(self) -> None:
        """保存统计数据到 JSON 文件（原子写入）。"""
        try:
            STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = STATS_PATH.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._stats, f, ensure_ascii=False, indent=2)
            tmp_path.replace(STATS_PATH)
        except OSError as e:
            _logger.warning("rule_stats 保存失败: %s", e)

    # ── 核心API ──

    def record(
        self,
        rule_id: str,
        severity: str,
        user_feedback: str = "",
        chapter_num: Optional[int] = None,
    ) -> None:
        """记录一次检测结果。

        Args:
            rule_id: 规则唯一标识，如 "ai_flavor.mental_prefix"
            severity: 检测严重级别 (HIGH/MEDIUM/LOW/BLOCK/WARNING/PASS 等)
            user_feedback: 用户反馈
                - "false_positive": 误报（作者标记"这不是问题"）
                - "confirmed": 确认（作者认可检测结果）
                - "": 无反馈
            chapter_num: 章节号（可选，用于追踪）
        """
        with self._file_lock:
            if rule_id not in self._stats:
                self._stats[rule_id] = {
                    "total": 0,
                    "false_positives": 0,
                    "confirmed": 0,
                    "no_feedback": 0,
                    "recent": [],  # 最近 N 次记录 [(severity, feedback, timestamp)]
                    "last_updated": 0.0,
                }

            stat = self._stats[rule_id]
            stat["total"] += 1
            stat["last_updated"] = time.time()

            if user_feedback == "false_positive":
                stat["false_positives"] += 1
            elif user_feedback == "confirmed":
                stat["confirmed"] += 1
            else:
                stat["no_feedback"] += 1

            # 维护最近记录窗口
            recent = stat["recent"]
            recent.append({
                "severity": severity,
                "feedback": user_feedback,
                "ts": stat["last_updated"],
                "chapter": chapter_num,
            })
            # 只保留最近 recent_window * 2 条（多保留一些用于分析）
            max_recent = DEMOTION_CONFIG["recent_window"] * 2
            if len(recent) > max_recent:
                stat["recent"] = recent[-max_recent:]

            self._save()

    # ── 降级判断 ──

    def should_demote(self, rule_id: str) -> bool:
        """基于历史误报率，判断该规则是否应该降级。

        降级条件（满足任一）:
        1. 总误报率 > 70% 且总检测次数 >= 20
        2. 最近 10 次中误报率 > 50%
        """
        stat = self._stats.get(rule_id)
        if stat is None or stat["total"] < DEMOTION_CONFIG["min_samples"]:
            return False

        # 条件1: 总误报率
        fp_rate = stat["false_positives"] / stat["total"]
        if fp_rate > DEMOTION_CONFIG["fp_rate_threshold"]:
            return True

        # 条件2: 最近窗口误报率
        recent = stat["recent"][-DEMOTION_CONFIG["recent_window"]:]
        if recent:
            recent_fp = sum(1 for r in recent if r.get("feedback") == "false_positive") / len(recent)
            if recent_fp > DEMOTION_CONFIG["recent_fp_threshold"]:
                return True

        return False

    def demote_severity(self, severity: str) -> str:
        """返回降级后的严重级别。

        HIGH -> MEDIUM -> LOW -> SILENT
        BLOCK -> WARNING -> PASS
        """
        return _SEVERITY_DEMOTION.get(severity, severity)

    def get_calibrated_threshold(self, rule_id: str, default: float) -> float:
        """基于历史误报率返回校准后的阈值。

        误报率高的规则，阈值自动提高（更难触发）。
        误报率低的规则，保持默认阈值。
        """
        stat = self._stats.get(rule_id)
        if stat is None or stat["total"] < DEMOTION_CONFIG["min_samples"]:
            return default

        fp_rate = stat["false_positives"] / stat["total"]
        if fp_rate <= 0.30:
            return default  # 误报率正常，不调整

        # 误报率越高，阈值越高
        # fp_rate=0.3 → factor=1.0（不变）
        # fp_rate=0.5 → factor=1.1
        # fp_rate=0.7 → factor=1.2
        # fp_rate=0.9 → factor=1.3
        factor = 1.0 + (fp_rate - 0.3) * 0.5
        return default * factor

    # ── 查询 ──

    def get_stats(self, rule_id: str) -> dict | None:
        """获取某条规则的完整统计数据。"""
        return self._stats.get(rule_id)

    def get_all_stats(self) -> dict:
        """获取所有规则的统计数据（用于前端展示）。"""
        return dict(self._stats)

    def get_demotion_report(self) -> list[dict]:
        """获取所有建议降级的规则列表。

        返回格式:
        [{"rule_id": "...", "fp_rate": 0.75, "total": 30, "recommendation": "MEDIUM->LOW"}, ...]
        """
        report = []
        for rule_id, stat in self._stats.items():
            if self.should_demote(rule_id):
                fp_rate = stat["false_positives"] / stat["total"] if stat["total"] > 0 else 0
                report.append({
                    "rule_id": rule_id,
                    "fp_rate": round(fp_rate, 2),
                    "total": stat["total"],
                    "false_positives": stat["false_positives"],
                    "recommendation": "建议降级（误报率过高）",
                })
        return report

    def reset(self, rule_id: str | None = None) -> None:
        """重置统计数据。

        Args:
            rule_id: 指定规则ID则只重置该规则，None 则重置全部。
        """
        with self._file_lock:
            if rule_id is None:
                self._stats = {}
            else:
                self._stats.pop(rule_id, None)
            self._save()


# ── 模块级单例 ──

_tracker: RuleStatsTracker | None = None
_tracker_lock = threading.Lock()


def get_tracker() -> RuleStatsTracker:
    """获取全局 RuleStatsTracker 单例。"""
    global _tracker
    if _tracker is not None:
        return _tracker
    with _tracker_lock:
        if _tracker is not None:
            return _tracker
        _tracker = RuleStatsTracker()
        return _tracker


# ── 模块自检 ──

if __name__ == "__main__":
    print("=" * 60)
    print("  rule_stats_tracker.py — 自检")
    print("=" * 60)

    tracker = get_tracker()

    # 1. 记录测试数据
    print("\n[TEST] 记录 25 次检测（18次误报, 7次确认）...")
    test_rule = "_test_rule_for_selfcheck"
    tracker.reset(test_rule)
    for i in range(18):
        tracker.record(test_rule, "WARNING", user_feedback="false_positive")
    for i in range(7):
        tracker.record(test_rule, "WARNING", user_feedback="confirmed")

    # 2. 检查降级建议
    should = tracker.should_demote(test_rule)
    print(f"[TEST] should_demote({test_rule}): {should}")

    stats = tracker.get_stats(test_rule)
    print(f"[TEST] stats: total={stats['total']}, fp={stats['false_positives']}, confirmed={stats['confirmed']}")

    # 3. 检查阈值校准
    calibrated = tracker.get_calibrated_threshold(test_rule, default=0.05)
    print(f"[TEST] calibrated_threshold: default=0.05 -> {calibrated:.4f}")

    # 4. 检查降级映射
    print(f"[TEST] demote_severity('HIGH') -> '{tracker.demote_severity('HIGH')}'")
    print(f"[TEST] demote_severity('WARNING') -> '{tracker.demote_severity('WARNING')}'")

    # 5. 降级报告
    report = tracker.get_demotion_report()
    print(f"[TEST] demotion_report: {len(report)} 条规则建议降级")

    # 清理
    tracker.reset(test_rule)
    print(f"\n[TEST] 清理测试数据")

    print("\n[DONE] rule_stats_tracker.py 自检完成")
