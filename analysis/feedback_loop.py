#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
feedback_loop.py v1 — 用户反馈最小闭环 (P0-2)
==============================================
功能: 追踪创作者作品与系统建议的互动，建立最小可行反馈回路。
      不做在线A/B测试，用"前后测"模式做离线对比。

流程:
  1. 用户将手写章节放入 my_work/ → 运行本脚本
  2. 运行 rhythm_analyzer 自动打分 (--auto) → 与精品基准对比
  3. 输出"差距报告": 你的指标 vs 精品均值，Top 3 改进建议
  4. 用户打标签 #采纳 / #不采纳 / #已修改
  5. 下次分析时自动对比采纳前后的指标变化

数据存储: data/processed/feedback.json
"""
import json
import statistics
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FEEDBACK_PATH = PROJECT_ROOT / "data" / "processed" / "feedback.json"
MANIFEST_PATH = PROJECT_ROOT / "data" / "processed" / "quality_manifest.json"


def _load_benchmark():
    if not MANIFEST_PATH.exists():
        return {"avg_hook": 0, "avg_pleasure": 0, "sample_n": 0}
    with open(MANIFEST_PATH, 'r', encoding='utf-8') as f:
        m = json.load(f)
    approved = m.get("approved", [])
    avg_hook = statistics.mean([a.get("avg_hook", 0) for a in approved]) if approved else 0
    avg_pleasure = statistics.mean([a.get("avg_pleasure", 0) for a in approved]) if approved else 0
    return {"avg_hook": round(avg_hook, 3), "avg_pleasure": round(avg_pleasure, 1),
            "sample_n": len(approved)}


def _load_feedback():
    if not FEEDBACK_PATH.exists():
        return {"entries": [], "adoption_rate": 0, "avg_improvement": 0}
    with open(FEEDBACK_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save_feedback(data):
    FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(FEEDBACK_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def submit_work(chapter_file, hook_density=0, pleasure_score=0, notes=""):
    """Submit a user-written chapter for feedback tracking."""
    fb = _load_feedback()
    benchmark = _load_benchmark()

    entry = {
        "chapter": chapter_file,
        "timestamp": datetime.now().isoformat(),
        "metrics": {"hook_density": hook_density, "pleasure_score": pleasure_score},
        "benchmark": benchmark,
        "gap": {
            "hook_gap": round(hook_density - benchmark["avg_hook"], 3),
            "pleasure_gap": round(pleasure_score - benchmark["avg_pleasure"], 1),
        },
        "status": "submitted",
        "notes": notes,
        "adopted": None,
        "post_metrics": None,
    }

    fb["entries"].append(entry)
    _save_feedback(fb)

    # Generate gap report
    print(f"[SUBMIT] {chapter_file}")
    print(f"  你的钩子密度: {hook_density} | 精品基准: {benchmark['avg_hook']} "
          f"(基于{benchmark['sample_n']}本)")
    print(f"  你的爽点评分: {pleasure_score} | 精品基准: {benchmark['avg_pleasure']}")
    gap = entry["gap"]
    suggestions = []
    if gap["hook_gap"] < -0.05:
        suggestions.append(f"钩子密度低{gap['hook_gap']:.2f}→章末加悬念或反转")
    if gap["pleasure_gap"] < -1:
        suggestions.append(f"爽点不足→至少1个打脸/突破场景")
    if not suggestions:
        suggestions.append("指标达标,可继续")

    print(f"  Top建议: {'; '.join(suggestions)}")
    print(f"  完成后用: python analysis/feedback_loop.py --adopt {len(fb['entries'])-1}")
    return entry


def adopt_suggestion(entry_index, post_hook=0, post_pleasure=0):
    """Mark a suggestion as adopted and record post-modification metrics."""
    fb = _load_feedback()
    if entry_index >= len(fb["entries"]):
        print(f"[FAIL] Invalid entry index {entry_index}")
        return

    entry = fb["entries"][entry_index]
    entry["adopted"] = True
    entry["status"] = "adopted"
    entry["post_metrics"] = {"hook_density": post_hook, "pleasure_score": post_pleasure}
    entry["improvement"] = {
        "hook_delta": round(post_hook - entry["metrics"]["hook_density"], 3),
        "pleasure_delta": round(post_pleasure - entry["metrics"]["pleasure_score"], 1),
    }

    # Update aggregate stats
    adopted = [e for e in fb["entries"] if e.get("adopted")]
    fb["adoption_rate"] = round(len(adopted) / max(len(fb["entries"]), 1), 2)
    improvements = [e["improvement"]["hook_delta"] for e in adopted
                    if e.get("improvement")]
    fb["avg_improvement"] = round(statistics.mean(improvements), 3) if improvements else 0

    _save_feedback(fb)

    imp = entry["improvement"]
    print(f"[ADOPT] {entry['chapter']}")
    print(f"  修改后钩子: {post_hook} ({imp['hook_delta']:+.3f})")
    print(f"  修改后爽点: {post_pleasure} ({imp['pleasure_delta']:+.1f})")
    print(f"  累计采纳率: {fb['adoption_rate']:.0%} | 均值改进: {fb['avg_improvement']:+.3f}")


def show_status():
    """Show current feedback loop status."""
    fb = _load_feedback()
    benchmark = _load_benchmark()
    print(f"[FEEDBACK] 总提交: {len(fb['entries'])} | 采纳率: {fb.get('adoption_rate',0):.0%}")
    print(f"[BENCHMARK] {benchmark['sample_n']}本精品书 | hook={benchmark['avg_hook']} pleasure={benchmark['avg_pleasure']}")
    for i, e in enumerate(fb["entries"][-5:]):
        status = "✅采纳" if e.get("adopted") else ("❌忽略" if e.get("adopted") is False else "⏳待处理")
        imp = e.get("improvement", {})
        imp_str = f" hook{imp.get('hook_delta','?'):+}" if imp else ""
        print(f"  [{i}] {e['chapter'][:30]} | {status} | gap={e.get('gap',{}).get('hook_gap','?')}{imp_str}")


def main():
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "status":
        show_status()
    elif cmd == "--submit":
        if len(sys.argv) < 4:
            print("Usage: python analysis/feedback_loop.py --submit <file> <hook> <pleasure>")
            return
        submit_work(sys.argv[2], float(sys.argv[3]), float(sys.argv[4]))
    elif cmd == "--adopt":
        if len(sys.argv) < 5:
            print("Usage: python analysis/feedback_loop.py --adopt <idx> <post_hook> <post_pleasure>")
            return
        adopt_suggestion(int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]))
    elif cmd == "--ignore":
        fb = _load_feedback()
        idx = int(sys.argv[2]) if len(sys.argv) > 2 else -1
        if 0 <= idx < len(fb["entries"]):
            fb["entries"][idx]["adopted"] = False
            fb["entries"][idx]["status"] = "ignored"
            _save_feedback(fb)
            print(f"[IGNORE] Entry {idx}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
