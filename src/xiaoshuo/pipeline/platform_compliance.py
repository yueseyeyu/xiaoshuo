#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
platform_compliance.py v1 — 番茄小说平台合规检测
===================================================
检测作者创作内容是否符合番茄小说"三次评估"规则：
  - 8万字门槛 + 8-15万安全窗口 + 三次机会
  - 前10章节奏/冲突/钩子检测
  - 首秀通过概率预估
  - 字数追踪 + 风险评估

配置: config.yaml analysis.platform_compliance
用法: python analysis/platform_compliance.py --text <file> [--json]
"""

import json
import re
import sys
from pathlib import Path
from xiaoshuo.infra.logging_config import get_logger

logger = get_logger(__name__)


def _load_config():
    try:
        from xiaoshuo.infra.config_manager import get_config
        cfg = get_config()
        return cfg.get("analysis", {}).get("platform_compliance", {})
    except Exception:
        return {}


def split_chapters(text):
    """Split text into chapters by common chapter markers."""
    pattern = r'(?:第[零一二三四五六七八九十百千\d]+[章节卷]|Chapter\s*\d+|CH\d+)'
    parts = re.split(f'({pattern})', text)
    chapters = []
    for i in range(1, len(parts), 2):
        title = parts[i].strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        chapters.append({"title": title, "body": body, "wc": len(body)})
    if not chapters and text.strip():
        chapters.append({"title": "全文", "body": text.strip(), "wc": len(text.strip())})
    return chapters


def _count_chinese(text):
    return sum(1 for c in text if '\u4e00' <= c <= '\u9fff')


def _detect_hooks(text):
    """Detect chapter-end hooks: suspense, reveal, threat, promise."""
    hook_patterns = [
        r'(?:突然|忽然|就在这时|正当|却(?:不料|没想到)|谁知|哪知)',
        r'(?:难道|莫非|怎么会|为什么|到底是什么)',
        r'(?:危机|危险|威胁|陷阱|阴谋|杀机)',
        r'(?:秘密|真相|隐情|内幕|背后)',
        r'(?:约定|承诺|誓言|一定会|等着)',
        r'(?:出现|登场|来了|到了|降临)',
    ]
    tail = text[-300:] if len(text) > 300 else text
    hits = 0
    for pat in hook_patterns:
        if re.search(pat, tail):
            hits += 1
    return hits > 0


def _detect_conflict_density(text):
    """Estimate conflict density from confrontation markers."""
    conflict_markers = [
        r'(?:对峙|对抗|冲突|战斗|厮杀|搏斗|激战)',
        r'(?:争执|争吵|争论|辩驳|质问|反驳)',
        r'(?:威胁|恐吓|压迫|逼迫|强迫)',
        r'(?:仇恨|怨恨|愤怒|怒火|杀意)',
        r'(?:陷阱|圈套|暗算|算计|阴谋)',
    ]
    chinese_count = _count_chinese(text)
    if chinese_count < 100:
        return 0.0
    hits = sum(len(re.findall(pat, text)) for pat in conflict_markers)
    return round(min(hits / (chinese_count / 100), 1.0), 3)


def assess_platform_compliance(text, config=None):
    """
    Evaluate text against Tomato platform debut rules.
    Returns dict with overall assessment, risk factors, and suggestions.
    """
    if config is None:
        config = _load_config()

    tomato = config.get("tomato", {})
    word_threshold = tomato.get("word_threshold", 80000)
    safe_window = tomato.get("safe_window", [80000, 140000])
    auto_trigger = tomato.get("auto_trigger_at", 150000)
    f10 = tomato.get("first_10_chapters", {})
    warn = tomato.get("warning_thresholds", {})

    chapters = split_chapters(text)
    total_wc = sum(ch["wc"] for ch in chapters)
    total_chinese = _count_chinese(text)

    result = {
        "total_chapters": len(chapters),
        "total_chinese_chars": total_chinese,
        "total_bytes": len(text.encode("utf-8")),
        "platform": "番茄小说",
        "checks": {},
        "risk_factors": [],
        "suggestions": [],
        "pass_probability": 100,
    }

    # ── 字数检查 ──
    if total_chinese < word_threshold:
        remaining = word_threshold - total_chinese
        result["checks"]["word_count"] = {
            "status": "pending",
            "message": f"未达8万字门槛(还需{remaining}字)",
            "current": total_chinese, "threshold": word_threshold
        }
        result["risk_factors"].append(f"字数不足: {total_chinese}/{word_threshold}")
        result["suggestions"].append(f"继续打磨至{word_threshold}字再提交，建议写到{safe_window[1] // 10000}万字左右")
        result["pass_probability"] -= 30
    elif total_chinese >= auto_trigger:
        result["checks"]["word_count"] = {
            "status": "danger",
            "message": f"已超过15万字自动审核红线({total_chinese}字)",
            "current": total_chinese, "threshold": auto_trigger
        }
        result["risk_factors"].append(f"字数超限: {total_chinese} >= {auto_trigger}(自动触发审核)")
        result["suggestions"].append("已触发自动审核，请确认是否已手动提交过评估")
        result["pass_probability"] -= 20
    elif total_chinese > safe_window[1]:
        result["checks"]["word_count"] = {
            "status": "warning",
            "message": f"已过14万安全窗口({total_chinese}字)，请尽快手动提交",
            "current": total_chinese, "threshold": safe_window[1]
        }
        result["risk_factors"].append(f"接近15万字红线: {total_chinese}字")
        result["suggestions"].append("尽快在8-14万窗口内手动提交评估")
        result["pass_probability"] -= 10
    else:
        result["checks"]["word_count"] = {
            "status": "ok",
            "message": f"字数在安全窗口内({total_chinese}字)",
            "current": total_chinese, "threshold": safe_window
        }

    # ── 前10章检测 ──
    if len(chapters) >= 10:
        first_10 = chapters[:10]
        hooks = [_detect_hooks(ch["body"]) for ch in first_10]
        conflicts = [_detect_conflict_density(ch["body"]) for ch in first_10]
        hook_rate = sum(hooks) / len(hooks)
        avg_conflict = sum(conflicts) / len(conflicts)

        min_hook = f10.get("min_hook_density", 0.6)
        min_conflict = f10.get("min_conflict_density", 0.4)

        result["checks"]["first_10_hooks"] = {
            "status": "ok" if hook_rate >= min_hook else "warning",
            "message": f"前10章钩子覆盖率: {hook_rate:.0%} (要求≥{min_hook:.0%})",
            "hook_count": sum(hooks), "total": len(hooks),
            "details": [f"第{i+1}章: {'有钩子' if h else '无钩子'}" for i, h in enumerate(hooks)]
        }

        result["checks"]["first_10_conflict"] = {
            "status": "ok" if avg_conflict >= min_conflict else "warning",
            "message": f"前10章冲突密度: {avg_conflict:.3f} (要求≥{min_conflict})",
            "avg_conflict": avg_conflict, "threshold": min_conflict,
            "per_chapter": [round(c, 3) for c in conflicts]
        }

        if hook_rate < min_hook:
            result["risk_factors"].append(f"前10章钩子不足: {hook_rate:.0%} < {min_hook:.0%}")
            result["suggestions"].append("前10章每章结尾需增加悬念或反转，确保读者有追读动力")
            result["pass_probability"] -= 15

        if avg_conflict < min_conflict:
            result["risk_factors"].append(f"前10章冲突不足: {avg_conflict:.3f} < {min_conflict}")
            result["suggestions"].append("前10章需要增加对抗性冲突，避免平铺直叙的铺垫")
            result["pass_probability"] -= 15

        # 流水账检测: 连续2章以上冲突密度为0
        zero_streak = cur = 0
        for c in conflicts:
            if c == 0:
                cur += 1
                zero_streak = max(zero_streak, cur)
            else:
                cur = 0
        if zero_streak >= 2:
            result["risk_factors"].append(f"前10章存在连续{zero_streak}章零冲突(流水账风险)")
            result["suggestions"].append(f"第{zero_streak}章连续无冲突，建议压缩铺垫或插入小冲突")

    elif len(chapters) > 0:
        result["checks"]["first_10_chapters"] = {
            "status": "pending",
            "message": f"仅有{len(chapters)}章，无法进行前10章检测"
        }
        result["suggestions"].append("章节数不足，完成10章后可进行前10章节奏检测")

    # ── 概率计算与等级 ──
    result["pass_probability"] = max(0, min(100, result["pass_probability"]))
    low_thresh = warn.get("pass_probability_low", 40)
    mid_thresh = warn.get("pass_probability_medium", 60)

    if result["pass_probability"] >= mid_thresh:
        result["risk_level"] = "green"
        result["risk_label"] = "通过概率较高"
    elif result["pass_probability"] >= low_thresh:
        result["risk_level"] = "yellow"
        result["risk_label"] = "需优化后提交"
    else:
        result["risk_level"] = "red"
        result["risk_label"] = "通过概率低，建议大幅重构"

    result["attempts_remaining"] = 3
    result["safe_window"] = f"{safe_window[0] // 10000}-{safe_window[1] // 10000}万字"

    return result


def format_report(result):
    """Format assessment result as human-readable text."""
    lines = [
        "=" * 50,
        "  番茄小说首秀风险评估",
        "=" * 50,
        "",
        f"  总字数: {result['total_chinese_chars']:,} / 80,000",
        f"  总章节: {result['total_chapters']}",
        f"  安全窗口: {result['safe_window']}",
        f"  评估机会: {result['attempts_remaining']} / 3",
        f"  通过概率: {result['pass_probability']}% ({result['risk_label']})",
        "",
    ]

    if result["risk_factors"]:
        lines.append("  [风险因素]")
        for rf in result["risk_factors"]:
            lines.append(f"    - {rf}")
        lines.append("")

    if result["suggestions"]:
        lines.append("  [建议操作]")
        for sg in result["suggestions"]:
            lines.append(f"    > {sg}")
        lines.append("")

    # Per-check details
    for key, check in result["checks"].items():
        icon = {"ok": "[OK]", "warning": "[WARN]", "danger": "[FAIL]", "pending": "[...]"}.get(check["status"], "[?]")
        lines.append(f"  {icon} {check['message']}")

    lines.append("")
    lines.append("=" * 50)
    return "\n".join(lines)


def main():
    config = _load_config()
    if not config.get("enabled", True):
        print("[SKIP] platform_compliance 未启用")
        return

    json_mode = "--json" in sys.argv
    text = None

    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--text" and i < len(sys.argv) - 1:
            text_path = sys.argv[i + 1]
            if Path(text_path).exists():
                text = Path(text_path).read_text(encoding="utf-8")
        elif arg == "--stdin":
            text = sys.stdin.read()

    if not text:
        print("用法: python analysis/platform_compliance.py --text <file> [--json]")
        print("      python analysis/platform_compliance.py --stdin [--json]")
        return

    result = assess_platform_compliance(text, config)

    if json_mode:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_report(result))


if __name__ == "__main__":
    main()