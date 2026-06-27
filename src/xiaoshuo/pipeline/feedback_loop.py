#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
feedback_loop.py v2 — 用户反馈闭环 + 签约评估集成
=========================================================
功能: 追踪创作者作品与系统建议的互动，建立最小可行反馈回路。
      不做在线A/B测试，用"前后测"模式做离线对比。

流程:
  1. 用户将手写章节放入 my_work/ → 运行本脚本
  2. --auto 模式: 自动扫描节奏指标 + 精品百分位对标 + 签约概率
  3. 输出"差距报告": 你的指标 vs 精品基准，Top 3 改进建议
  4. 用户打标签 #采纳 / #不采纳 / #已修改
  5. 下次分析时自动对比采纳前后的指标变化

数据存储: data/processed/{genre}/feedback.json
"""
import json
import statistics
import sys
from pathlib import Path
from xiaoshuo import PROJECT_ROOT
from datetime import datetime

# PROJECT_ROOT imported from src.xiaoshuo
# v2: Import comparison_engine for full metrics + benchmark
try:
    # Try package import first, then sys.path fallback
    from analysis.comparison_engine import (
        _rich_scan,
        compute_benchmark_percentiles,
        estimate_signing_probability,
    )
    _ce_available = True
except ImportError:
    try:
        import sys as _sys
        _sys.path.insert(0, str(PROJECT_ROOT))
        from analysis.comparison_engine import (
            _rich_scan,
            compute_benchmark_percentiles,
            estimate_signing_probability,
        )
        _ce_available = True
    except ImportError:
        _ce_available = False

MANIFEST_PATH = PROJECT_ROOT / "data" / "processed" / "末世" / "quality" / "quality_manifest.json"


def _feedback_path(genre="末世"):
    return PROJECT_ROOT / "data" / "processed" / genre / "quality" / "feedback.json"


def _load_benchmark_legacy():
    """Legacy benchmark from quality_manifest (hook+pleasure only)."""
    if not MANIFEST_PATH.exists():
        return {"avg_hook": 0, "avg_pleasure": 0, "sample_n": 0}
    with open(MANIFEST_PATH, 'r', encoding='utf-8') as f:
        m = json.load(f)
    approved = m.get("approved", [])
    avg_hook = statistics.mean([a.get("avg_hook", 0) for a in approved]) if approved else 0
    avg_pleasure = statistics.mean([a.get("avg_pleasure", 0) for a in approved]) if approved else 0
    return {"avg_hook": round(avg_hook, 3), "avg_pleasure": round(avg_pleasure, 1),
            "sample_n": len(approved)}


def _load_feedback(genre="末世"):
    fb_path = _feedback_path(genre)
    if not fb_path.exists():
        return {"entries": [], "adoption_rate": 0, "avg_improvement": 0}
    with open(fb_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save_feedback(data, genre="末世"):
    fb_path = _feedback_path(genre)
    fb_path.parent.mkdir(parents=True, exist_ok=True)
    with open(fb_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def submit_work(chapter_file, hook_density=0, pleasure_score=0, notes="", genre="末世"):
    """Submit a user-written chapter for feedback tracking (manual metrics)."""
    fb = _load_feedback(genre)
    benchmark = _load_benchmark_legacy()

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
    _save_feedback(fb, genre)

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


def submit_work_auto(chapter_file, genre="末世", notes=""):
    """Auto-scan chapter + benchmark comparison + signing probability.

    v2: Uses comparison_engine._rich_scan for full 30+ metrics,
    compute_benchmark_percentiles for percentile-based comparison,
    and estimate_signing_probability for signing assessment.
    """
    if not _ce_available:
        print("[FAIL] comparison_engine 不可用，请确保 analysis/comparison_engine.py 存在")
        return None

    path = Path(chapter_file)
    if not path.exists():
        print(f"[FAIL] 文件不存在: {path}")
        return None

    text = path.read_text(encoding='utf-8', errors='replace')

    # Step 1: Scan
    print(f"[AUTO] 扫描 {path.name}...")
    metrics = _rich_scan(text)

    # Step 2: Benchmark
    percentiles = compute_benchmark_percentiles(genre)
    if not percentiles:
        print(f"[FAIL] 无法加载{genre}精品基准")
        return None

    # Step 3: Signing probability
    signing = estimate_signing_probability(metrics, percentiles)

    # Step 4: Save to feedback
    fb = _load_feedback(genre)
    entry = {
        "chapter": str(path.name),
        "timestamp": datetime.now().isoformat(),
        "mode": "auto",
        "metrics": {
            "hook_density": metrics["hook_density"],
            "conflict_density": metrics["conflict_density"],
            "pleasure_intensity": metrics.get("pleasure_intensity", 0),
            "dialogue_ratio": metrics["dialogue_ratio"],
            "readability": metrics.get("readability", 0),
            "avg_sentence_len": metrics.get("avg_sentence_len", 0),
            "chars": metrics["chars"],
        },
        "signing_probability": signing,
        "status": "submitted",
        "notes": notes,
        "adopted": None,
        "post_metrics": None,
    }
    fb["entries"].append(entry)
    _save_feedback(fb, genre)

    # Print report
    n = percentiles.get("hook_density", {}).get("n", 0)
    print(f"\n  [OK] {metrics['chars']}字 | hook={metrics['hook_density']:.2f} "
          f"conflict={metrics['conflict_density']:.2f} "
          f"pleasure={metrics.get('pleasure_intensity', 0):.1f}")
    if signing:
        print(f"  [OK] 签约概率: {signing['probability']}% | {signing['label']}")
        print(f"       (基于{n}本精品百分位对标)")
        for a in signing.get("advice", []):
            print(f"  [{a['priority']}] {a['dim']}: {a['suggestion']}")

    print(f"\n  完成后用: python analysis/feedback_loop.py --adopt {len(fb['entries'])-1}")
    return entry


def adopt_suggestion(entry_index, genre="末世", post_hook=0, post_pleasure=0):
    """Mark a suggestion as adopted and record post-modification metrics."""
    fb = _load_feedback(genre)
    if entry_index >= len(fb["entries"]):
        print(f"[FAIL] Invalid entry index {entry_index}")
        return

    entry = fb["entries"][entry_index]
    entry["adopted"] = True
    entry["status"] = "adopted"

    # Auto-scan post-modification if file exists
    if entry.get("mode") == "auto" and _ce_available:
        chapter_file = entry.get("chapter", "")
        # Try common locations
        for loc in [Path(chapter_file), PROJECT_ROOT / "my_work" / chapter_file]:
            if loc.exists():
                post_text = loc.read_text(encoding='utf-8', errors='replace')
                post_metrics = _rich_scan(post_text)
                entry["post_metrics"] = {
                    "hook_density": post_metrics["hook_density"],
                    "conflict_density": post_metrics["conflict_density"],
                    "pleasure_intensity": post_metrics.get("pleasure_intensity", 0),
                }
                pre = entry["metrics"]
                entry["improvement"] = {
                    "hook_delta": round(post_metrics["hook_density"] - pre.get("hook_density", 0), 3),
                    "conflict_delta": round(post_metrics["conflict_density"] - pre.get("conflict_density", 0), 3),
                    "pleasure_delta": round(post_metrics.get("pleasure_intensity", 0) - pre.get("pleasure_intensity", 0), 1),
                }
                break

    if not entry.get("post_metrics"):
        entry["post_metrics"] = {"hook_density": post_hook, "pleasure_score": post_pleasure}
        entry["improvement"] = {
            "hook_delta": round(post_hook - entry["metrics"].get("hook_density", 0), 3),
            "pleasure_delta": round(post_pleasure - entry["metrics"].get("pleasure_score", 0), 1),
        }

    # Update aggregate stats
    adopted = [e for e in fb["entries"] if e.get("adopted")]
    fb["adoption_rate"] = round(len(adopted) / max(len(fb["entries"]), 1), 2)
    improvements = [e["improvement"]["hook_delta"] for e in adopted
                    if e.get("improvement")]
    fb["avg_improvement"] = round(statistics.mean(improvements), 3) if improvements else 0

    _save_feedback(fb, genre)

    imp = entry["improvement"]
    print(f"[ADOPT] {entry['chapter']}")
    for key, val in imp.items():
        print(f"  {key}: {val:+}")
    print(f"  累计采纳率: {fb['adoption_rate']:.0%} | 均值改进: {fb['avg_improvement']:+.3f}")


def show_status(genre="末世"):
    """Show current feedback loop status."""
    fb = _load_feedback(genre)
    benchmark = _load_benchmark_legacy()
    print(f"[FEEDBACK] genre={genre} | 总提交: {len(fb['entries'])} | 采纳率: {fb.get('adoption_rate',0):.0%}")
    print(f"[BENCHMARK] {benchmark['sample_n']}本精品书 | hook={benchmark['avg_hook']} pleasure={benchmark['avg_pleasure']}")
    for i, e in enumerate(fb["entries"][-5:]):
        status = "✅采纳" if e.get("adopted") else ("❌忽略" if e.get("adopted") is False else "⏳待处理")
        mode = e.get("mode", "manual")
        imp = e.get("improvement", {})
        imp_str = f" hook{imp.get('hook_delta','?'):+}" if imp else ""
        # Show signing probability if available
        sp = e.get("signing_probability", {})
        sp_str = f" | 签约{sp['probability']}%" if sp else ""
        print(f"  [{i}] {e['chapter'][:30]} | {mode} | {status}{sp_str}{imp_str}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    # Parse genre
    genre = "末世"
    if "--genre" in sys.argv:
        idx = sys.argv.index("--genre")
        if idx + 1 < len(sys.argv):
            genre = sys.argv[idx + 1]

    if cmd == "status":
        show_status(genre)
    elif cmd == "--auto":
        # v2: Auto-scan mode
        if len(sys.argv) < 3 or sys.argv[2].startswith("--"):
            print("Usage: python analysis/feedback_loop.py --auto <file> [--genre 末世]")
            return
        submit_work_auto(sys.argv[2], genre)
    elif cmd == "--submit":
        if len(sys.argv) < 4:
            print("Usage: python analysis/feedback_loop.py --submit <file> <hook> <pleasure>")
            return
        submit_work(sys.argv[2], float(sys.argv[3]), float(sys.argv[4]), genre=genre)
    elif cmd == "--adopt":
        if len(sys.argv) < 3:
            print("Usage: python analysis/feedback_loop.py --adopt <idx> [post_hook post_pleasure]")
            return
        idx = int(sys.argv[2])
        post_h = float(sys.argv[3]) if len(sys.argv) > 3 else 0
        post_p = float(sys.argv[4]) if len(sys.argv) > 4 else 0
        adopt_suggestion(idx, genre, post_h, post_p)
    elif cmd == "--ignore":
        fb = _load_feedback(genre)
        idx = int(sys.argv[2]) if len(sys.argv) > 2 else -1
        if 0 <= idx < len(fb["entries"]):
            fb["entries"][idx]["adopted"] = False
            fb["entries"][idx]["status"] = "ignored"
            _save_feedback(fb, genre)
            print(f"[IGNORE] Entry {idx}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
