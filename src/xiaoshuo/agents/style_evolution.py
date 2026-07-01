# -*- coding: utf-8 -*-
"""
style_evolution.py — Part E: 作者风格涌现引擎
================================================================
从章节决策数据 + 章节节奏指标中提取作者风格画像,
逐步生成可注入 System Prompt 的风格提示。

数据流:
  chapter_decisions.json (作者每章3个决策)
  + assets/chapters/chapter_*.md (节奏指标扫描)
    ↓
  generate_style_profile()
    ↓
  author_style_profile.json (风格画像)
    ↓
  get_style_hints() → 注入 _run_prewrite_combined

设计原则:
  - 零 LLM 成本: 纯规则统计 + 模板 NLG
  - 渐进式: 3章开始构建, 10章初步画像, 50章成熟画像
  - 可解释: 每条风格提示都有数据来源标注

用法:
  from xiaoshuo.agents.style_evolution import generate_style_profile, get_style_hints
  profile = generate_style_profile()  # 生成/更新风格画像
  hints = get_style_hints()           # 获取风格提示列表
"""

from __future__ import annotations

import json
import re
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional

from xiaoshuo import PROJECT_ROOT
from xiaoshuo.infra.logging_config import get_logger

logger = get_logger("style_evolution")

# ============================================================
# 常量 & 路径
# ============================================================

PROFILE_DIR = PROJECT_ROOT / "data" / "processed" / "style_profile"
PROFILE_PATH = PROFILE_DIR / "author_style_profile.json"
DECISIONS_PATH = PROJECT_ROOT / "data" / "processed" / "chapter_decisions" / "all_decisions.json"
CHAPTERS_DIR = PROJECT_ROOT / "assets" / "chapters"

# 风格画像成熟度阈值
MATURITY_THRESHOLDS = {
    "seed": 3,      # 3章: 种子阶段, 初步信号
    "building": 10, # 10章: 构建阶段, 初步画像
    "mature": 30,   # 30章: 成熟画像
    "rich": 50,     # 50章: 丰富画像, 可深度注入
}


# ============================================================
# 1. 风格画像生成
# ============================================================

def generate_style_profile() -> dict:
    """从决策数据 + 章节指标生成作者风格画像。

    Returns:
        风格画像 dict, 同时持久化到 author_style_profile.json
    """
    decisions = _load_decisions()
    chapter_count = len(decisions)

    profile = {
        "version": "1.0",
        "generated_at": datetime.now().isoformat(),
        "chapter_count": chapter_count,
        "maturity": _calc_maturity(chapter_count),
    }

    if chapter_count < MATURITY_THRESHOLDS["seed"]:
        profile["status"] = "insufficient_data"
        profile["message"] = f"仅{chapter_count}章数据, 需≥{MATURITY_THRESHOLDS['seed']}章开始构建"
        _save_profile(profile)
        return profile

    # ── 1. 决策信号提取 ──
    profile["decision_signals"] = _extract_decision_signals(decisions)

    # ── 2. 节奏指标统计 ──
    rhythm_stats = _extract_rhythm_stats(decisions)
    profile["rhythm_stats"] = rhythm_stats

    # ── 3. 风格偏好提取 ──
    profile["style_preferences"] = _extract_style_preferences(decisions, rhythm_stats)

    # ── 4. 风格提示生成 ──
    profile["style_hints"] = _generate_hints(profile)

    # ── 5. 漂移检测 ──
    if chapter_count >= MATURITY_THRESHOLDS["building"]:
        profile["drift_detection"] = _detect_style_drift(decisions, rhythm_stats)

    profile["status"] = "active"
    _save_profile(profile)
    logger.info("Style profile generated: %d chapters, maturity=%s", chapter_count, profile["maturity"])
    return profile


# ============================================================
# 2. 风格提示获取 (供 _run_prewrite_combined 调用)
# ============================================================

def get_style_hints() -> list[str]:
    """获取当前作者风格提示列表。

    如画像不存在或过期(>5章未更新), 自动重新生成。
    Returns:
        风格提示字符串列表, 每条可直接显示给作者
    """
    profile = _load_profile()

    # 画像不存在或过期则重新生成
    if not profile or _is_stale(profile):
        profile = generate_style_profile()

    if profile.get("status") != "active":
        return []

    return profile.get("style_hints", [])


def get_evolution_status() -> dict:
    """获取风格进化状态摘要。"""
    profile = _load_profile()

    if not profile:
        return {"status": "not_started", "message": "尚未生成风格画像"}

    return {
        "status": profile.get("status", "unknown"),
        "maturity": profile.get("maturity", "unknown"),
        "chapter_count": profile.get("chapter_count", 0),
        "hint_count": len(profile.get("style_hints", [])),
        "generated_at": profile.get("generated_at", ""),
        "drift": profile.get("drift_detection", {}).get("detected", False),
    }


# ============================================================
# 3. 内部实现
# ============================================================

def _load_decisions() -> list:
    """加载章节决策记录。"""
    if not DECISIONS_PATH.exists():
        return []
    try:
        return json.loads(DECISIONS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _load_profile() -> Optional[dict]:
    """加载已有风格画像。"""
    if not PROFILE_PATH.exists():
        return None
    try:
        return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _save_profile(profile: dict) -> None:
    """持久化风格画像。"""
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def _is_stale(profile: dict) -> bool:
    """画像是否过期 (决策章节数 vs 画像记录的章节数差异≥5)。"""
    decisions = _load_decisions()
    current_count = len(decisions)
    profile_count = profile.get("chapter_count", 0)
    return current_count - profile_count >= 5


def _calc_maturity(chapter_count: int) -> str:
    """计算风格画像成熟度。"""
    if chapter_count >= MATURITY_THRESHOLDS["rich"]:
        return "rich"
    elif chapter_count >= MATURITY_THRESHOLDS["mature"]:
        return "mature"
    elif chapter_count >= MATURITY_THRESHOLDS["building"]:
        return "building"
    elif chapter_count >= MATURITY_THRESHOLDS["seed"]:
        return "seed"
    return "none"


def _extract_decision_signals(decisions: list) -> dict:
    """从决策记录中提取风格信号。"""
    signals = {
        "positive_style": [],    # 正面风格样本
        "style_intent": [],      # 风格意图信号
        "preference_boundary": [], # 偏好边界信号
        "skip_rate": 0.0,
        "active_rate": 0.0,
    }

    total_answers = 0
    skipped = 0

    for record in decisions:
        for q_id, ans in record.get("answers", {}).items():
            total_answers += 1
            answer_text = ans.get("answer", "")
            category = ans.get("category", "unknown")

            if answer_text == "(skipped)":
                skipped += 1
                continue

            signals[category].append({
                "chapter": record.get("chapter", 0),
                "signal": answer_text[:300],
            })

    signals["skip_rate"] = round(skipped / max(total_answers, 1), 2)
    signals["active_rate"] = round(1 - signals["skip_rate"], 2)

    return signals


def _extract_rhythm_stats(decisions: list) -> dict:
    """从已写章节中提取节奏指标统计。

    扫描 assets/chapters/ 中对应章节的文本,
    使用 comparison_engine.rich_scan 获取节奏指标。
    """
    stats = {
        "chapters_scanned": 0,
        "hook_density": {"mean": 0, "std": 0, "trend": "stable"},
        "conflict_density": {"mean": 0, "std": 0, "trend": "stable"},
        "pleasure_intensity": {"mean": 0, "std": 0, "trend": "stable"},
        "dialogue_ratio": {"mean": 0, "std": 0, "trend": "stable"},
    }

    try:
        from xiaoshuo.pipeline.comparison_engine import rich_scan
    except ImportError:
        logger.debug("comparison_engine not available, skipping rhythm stats")
        return stats

    chapters_scanned = []
    for record in decisions:
        ch = record.get("chapter", 0)
        if ch <= 0:
            continue
        ch_path = CHAPTERS_DIR / f"chapter_{ch}.md"
        if not ch_path.exists():
            continue
        try:
            text = ch_path.read_text(encoding="utf-8")
            metrics = rich_scan(text)
            chapters_scanned.append({
                "chapter": ch,
                "hook_density": metrics.get("hook_density", 0),
                "conflict_density": metrics.get("conflict_density", 0),
                "pleasure_intensity": metrics.get("pleasure_intensity", 0),
                "dialogue_ratio": metrics.get("dialogue_ratio", 0),
            })
        except Exception as e:
            logger.debug("Failed to scan chapter %d: %s", ch, e)

    if not chapters_scanned:
        return stats

    stats["chapters_scanned"] = len(chapters_scanned)

    for metric in ["hook_density", "conflict_density", "pleasure_intensity", "dialogue_ratio"]:
        values = [c[metric] for c in chapters_scanned]
        stats[metric]["mean"] = round(statistics.mean(values), 3)
        stats[metric]["std"] = round(statistics.stdev(values), 3) if len(values) > 1 else 0

        # 趋势检测: 比较前半段和后半段均值
        if len(values) >= 6:
            mid = len(values) // 2
            first_half = statistics.mean(values[:mid])
            second_half = statistics.mean(values[mid:])
            diff_pct = (second_half - first_half) / max(abs(first_half), 0.001) * 100
            if diff_pct > 15:
                stats[metric]["trend"] = "increasing"
            elif diff_pct < -15:
                stats[metric]["trend"] = "decreasing"

    return stats


def _extract_style_preferences(decisions: list, rhythm_stats: dict) -> dict:
    """从决策信号 + 节奏统计中提取风格偏好。"""
    prefs = {}

    # 1. 对话偏好
    dialogue_mean = rhythm_stats.get("dialogue_ratio", {}).get("mean", 0)
    if dialogue_mean > 0:
        if dialogue_mean > 0.4:
            prefs["dialogue"] = "high — 偏好对话驱动叙事"
        elif dialogue_mean < 0.2:
            prefs["dialogue"] = "low — 偏好叙述驱动叙事"
        else:
            prefs["dialogue"] = "balanced — 对话叙述均衡"

    # 2. 节奏偏好
    hook_mean = rhythm_stats.get("hook_density", {}).get("mean", 0)
    conflict_mean = rhythm_stats.get("conflict_density", {}).get("mean", 0)
    if hook_mean > 0:
        if hook_mean > 1.5:
            prefs["pacing"] = "fast — 高钩子密度, 快节奏"
        elif hook_mean < 0.5:
            prefs["pacing"] = "slow — 低钩子密度, 慢节奏"
        else:
            prefs["pacing"] = "medium — 中等节奏"

    # 3. 爽点偏好
    pleasure_mean = rhythm_stats.get("pleasure_intensity", {}).get("mean", 0)
    if pleasure_mean > 0:
        if pleasure_mean > 5:
            prefs["pleasure"] = "high — 高爽点密度, 强爽感驱动"
        elif pleasure_mean < 2:
            prefs["pleasure"] = "low — 低爽点密度, 情感/剧情驱动"
        else:
            prefs["pleasure"] = "medium — 适中爽点密度"

    # 4. 打破常规的意图分析
    break_conventions = []
    for record in decisions:
        ans = record.get("answers", {}).get("break_convention", {})
        text = ans.get("answer", "")
        if text and text != "(skipped)":
            break_conventions.append(text.lower())

    if break_conventions:
        # 关键词频率分析
        convention_keywords = Counter()
        keyword_map = {
            "短句": ["短句", "短", "简洁"],
            "长句": ["长句", "长", "绵长"],
            "对话": ["对话", "对白"],
            "描写": ["描写", "环境", "细节"],
            "反转": ["反转", "颠覆", "意外"],
            "留白": ["留白", "省略", "暗示"],
            "节奏": ["节奏", "快", "慢"],
        }
        for text in break_conventions:
            for label, kws in keyword_map.items():
                if any(kw in text for kw in kws):
                    convention_keywords[label] += 1

        if convention_keywords:
            top = convention_keywords.most_common(3)
            prefs["convention_breaks"] = [f"{label}({count}次)" for label, count in top]

    # 5. 拒绝的AI建议分析
    rejected = []
    for record in decisions:
        ans = record.get("answers", {}).get("rejected_advice", {})
        text = ans.get("answer", "")
        if text and text != "(skipped)":
            rejected.append(text.lower())

    if rejected:
        rejection_keywords = Counter()
        keyword_map = {
            "节奏太快": ["快", "加速", "节奏快"],
            "节奏太慢": ["慢", "减速", "拖"],
            "爽点不足": ["爽点", "不够爽"],
            "对话过多": ["对话多", "流水账"],
            "描写过多": ["描写多", "环境多"],
        }
        for text in rejected:
            for label, kws in keyword_map.items():
                if any(kw in text for kw in kws):
                    rejection_keywords[label] += 1

        if rejection_keywords:
            prefs["rejected_patterns"] = [f"{label}({count}次)" for label, count in rejection_keywords.most_common(3)]

    return prefs


def _generate_hints(profile: dict) -> list[str]:
    """从风格画像生成可注入的风格提示。"""
    hints = []
    prefs = profile.get("style_preferences", {})
    rhythm = profile.get("rhythm_stats", {})
    maturity = profile.get("maturity", "none")

    # 对话偏好提示
    dialogue_pref = prefs.get("dialogue", "")
    if dialogue_pref:
        hints.append(f"作者对话偏好: {dialogue_pref}")

    # 节奏偏好提示
    pacing_pref = prefs.get("pacing", "")
    if pacing_pref:
        hints.append(f"作者节奏偏好: {pacing_pref}")

    # 爽点偏好提示
    pleasure_pref = prefs.get("pleasure", "")
    if pleasure_pref:
        hints.append(f"作者爽点偏好: {pleasure_pref}")

    # 打破常规提示
    conventions = prefs.get("convention_breaks", [])
    if conventions:
        hints.append(f"作者常打破常规: {', '.join(conventions)}")

    # 拒绝模式提示
    rejected = prefs.get("rejected_patterns", [])
    if rejected:
        hints.append(f"作者常拒绝: {', '.join(rejected)}")

    # 趋势提示 (仅 mature 以上)
    if maturity in ("mature", "rich"):
        for metric in ["hook_density", "conflict_density", "pleasure_intensity"]:
            trend = rhythm.get(metric, {}).get("trend", "stable")
            if trend != "stable":
                label_map = {
                    "hook_density": "钩子密度",
                    "conflict_density": "冲突密度",
                    "pleasure_intensity": "爽点强度",
                }
                trend_map = {
                    "increasing": "上升中",
                    "decreasing": "下降中",
                }
                hints.append(f"趋势: {label_map.get(metric, metric)} {trend_map.get(trend, trend)}")

    return hints


def _detect_style_drift(decisions: list, rhythm_stats: dict) -> dict:
    """检测风格漂移 (最近5章 vs 之前均值)。"""
    try:
        from xiaoshuo.pipeline.comparison_engine import rich_scan
    except ImportError:
        return {"detected": False, "reason": "comparison_engine 不可用"}

    recent_chapters = sorted(decisions, key=lambda r: r.get("chapter", 0))[-5:]
    if len(recent_chapters) < 3:
        return {"detected": False, "reason": "近期章节数据不足"}

    # 扫描最近5章
    recent_metrics = []
    for record in recent_chapters:
        ch = record.get("chapter", 0)
        ch_path = CHAPTERS_DIR / f"chapter_{ch}.md"
        if not ch_path.exists():
            continue
        try:
            text = ch_path.read_text(encoding="utf-8")
            metrics = rich_scan(text)
            recent_metrics.append(metrics)
        except Exception:
            continue

    if len(recent_metrics) < 3:
        return {"detected": False, "reason": "近期章节扫描不足"}

    # 比较最近均值 vs 整体均值
    drifts = []
    for metric in ["hook_density", "conflict_density", "pleasure_intensity", "dialogue_ratio"]:
        overall_mean = rhythm_stats.get(metric, {}).get("mean", 0)
        if overall_mean <= 0:
            continue
        recent_mean = statistics.mean([m.get(metric, 0) for m in recent_metrics])
        diff_pct = abs(recent_mean - overall_mean) / max(abs(overall_mean), 0.001) * 100

        if diff_pct > 30:  # 30% 以上偏差视为漂移
            direction = "上升" if recent_mean > overall_mean else "下降"
            drifts.append({
                "metric": metric,
                "overall_mean": round(overall_mean, 3),
                "recent_mean": round(recent_mean, 3),
                "diff_pct": round(diff_pct, 1),
                "direction": direction,
            })

    return {
        "detected": len(drifts) > 0,
        "drifts": drifts,
        "advice": "注意保持风格一致性" if drifts else "风格稳定",
    }
