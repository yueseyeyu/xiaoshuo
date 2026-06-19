#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
style_detection_loop.py — S4 反检测循环: 检测→报告→(人工修改)→复检→对比
========================================================================
v7.5: Loop模式 (检测循环, 不禁 AI 改写)
原则: 正文100%手写 — 本模块只检测, 不生成任何改写建议或替换文本

四层检测 (来自 config.yaml detection.layers):
  L1 PPL (困惑度)         — PPL < 阈值 → 疑似 AI 生成
  L2 Burstiness (突发性)   — 句长变异系数低 → 文本过于规整
  L3 AI词共现             — 常见 AI 词汇密度过高
  L4 句长分布变异          — 连读多章后句长模式变平 → 风格漂移

循环模式:
  检测第N章 → 输出指标 → 人修改 → 检测第N章(rev2) → 对比 → ...

用法:
  python analysis/style_detection_loop.py --text "章节内容"
  python analysis/style_detection_loop.py --file path/to/chapter.txt
  python analysis/style_detection_loop.py --book 异兽迷城 --ch 5
"""

import math
import re
import sys
import yaml
from collections import Counter
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"

# v7.5: AI 指纹词表 (静态, 来自 config 中的 l3_ai_word_cooccurrence)
_AI_FINGERPRINT = {
    "此外", "总而言之", "综上所述", "值得注意的是", "不可否认",
    "与此同时", "另一方面", "显而易见", "由此可见", "事实上",
    "从根本上说", "本质上", "某种意义上", "在某种程度上",
    "不但", "而且", "然而", "因此", "从而", "进而",
    "首先", "其次", "最后", "一方面", "值得注意的是",
}


def _load_cfg():
    """Load detection thresholds from config.yaml."""
    defaults = {
        "l1_ppl": {"safe": 50, "warn": 40},
        "l2_burstiness": {"safe": 0.6},
        "l3_ai_word": {"window": 100, "max_words": 2},
        "l4_variation": {"warning": 0.20},
    }
    try:
        cfg = yaml.safe_load(open(CONFIG_PATH, encoding="utf-8"))
        det = cfg.get("detection", {}).get("layers", {})
        return {
            "l1": det.get("l1_ppl", defaults["l1_ppl"]),
            "l2": det.get("l2_burstiness", defaults["l2_burstiness"]),
            "l3": det.get("l3_ai_word_cooccurrence", defaults["l3_ai_word"]),
            "l4": det.get("l4_sentence_length_variation", defaults["l4_variation"]),
        }
    except Exception:
        return defaults


def _sentences(text):
    """Split text into sentences (Chinese-aware)."""
    return re.split(r'[。！？；\n]+', text)


def _words(text):
    """Tokenize Chinese text into words (2-char sliding + single char)."""
    chinese = re.findall(r'[\u4e00-\u9fff]+', text)
    tokens = []
    for segment in chinese:
        for i in range(len(segment)):
            if i + 1 < len(segment):
                tokens.append(segment[i:i + 2])
        tokens.append(segment[-1])
    return tokens


# ── L1: 困惑度估算 ──

def _ppl_estimate(text):
    """Heuristic PPL proxy: entropy-based. Lower = more predictable = AI-like.
    Real PPL needs LLM scoring; this is a fast proxy for loop mode."""
    sents = _sections(text)
    if len(sents) < 3:
        return 100.0
    # Sentence length entropy
    lens = [len(s) for s in sents if len(s) > 5]
    if not lens:
        return 100.0
    mean_len = sum(lens) / len(lens)
    if mean_len < 1:
        return 100.0
    entropy = 0.0
    for l in lens:
        p = l / sum(lens) if sum(lens) > 0 else 1 / len(lens)
        if p > 0:
            entropy -= p * math.log2(p)
    # Normalize: high entropy → high PPL proxy; low entropy → low PPL → AI-like
    normalized = max(10, 100 - entropy * 15)
    return round(normalized, 1)


def _sections(text):
    """Split text into content sections (paragraph-level)."""
    return [p.strip() for p in re.split(r'\n{2,}', text) if p.strip() and len(p.strip()) > 10]


# ── L2: 突发性 ──

def _burstiness(text):
    """Burstiness = stdev(sentence_lengths) / mean(sentence_lengths).
    Higher = more human-like variation. < 0.6 = warning."""
    sents = _sentences(text)
    lens = [len(s) for s in sents if len(s) > 3]
    if len(lens) < 5:
        return 1.0
    mean_len = sum(lens) / len(lens)
    if mean_len < 2:
        return 1.0
    variance = sum((l - mean_len) ** 2 for l in lens) / len(lens)
    return round(math.sqrt(variance) / mean_len, 3)


# ── L3: AI 词共现 ──

def _ai_word_density(text):
    """Count AI fingerprint words per 100-character sliding window."""
    if not text:
        return 0.0
    chinese_only = ''.join(re.findall(r'[\u4e00-\u9fff]', text))
    if len(chinese_only) < 100:
        return 0.0

    max_density = 0.0
    for i in range(0, len(chinese_only) - 100, 50):
        window = chinese_only[i:i + 100]
        hits = sum(1 for w in _AI_FINGERPRINT if w in window)
        density = hits / 100
        if density > max_density:
            max_density = density
    return round(max_density, 4)


# ── L4: 句长变异 ──

def _sentence_variation(text_a, text_b=None):
    """Compute sentence length variation coefficient.
    If text_b provided: compare two versions (delta > threshold → warning)."""
    sents_a = [len(s) for s in _sentences(text_a) if len(s) > 3]
    if not sents_a or len(sents_a) < 5:
        return 0.0
    cv_a = math.sqrt(sum((l - sum(sents_a) / len(sents_a)) ** 2
                         for l in sents_a) / len(sents_a)) / (sum(sents_a) / len(sents_a))

    if text_b is None:
        return round(cv_a, 3)

    sents_b = [len(s) for s in _sentences(text_b) if len(s) > 3]
    if not sents_b or len(sents_b) < 5:
        return 0.0
    cv_b = math.sqrt(sum((l - sum(sents_b) / len(sents_b)) ** 2
                         for l in sents_b) / len(sents_b)) / (sum(sents_b) / len(sents_b))

    return round(abs(cv_a - cv_b), 3)


# ── 主检测管道 ──

def detect_style(text, previous_text=None):
    """Run 4-layer style detection on text.
    
    Args:
        text: current chapter text
        previous_text: optional previous version for L4 comparison
        
    Returns:
        dict with per-layer results and overall verdict
    """
    cfg = _load_cfg()
    results = {}

    # L1: PPL proxy
    ppl = _ppl_estimate(text)
    l1_cfg = cfg.get("l1", {})
    results["l1_ppl"] = {
        "value": ppl,
        "safe_threshold": l1_cfg.get("safe", 50),
        "warn_threshold": l1_cfg.get("warn", 40),
        "status": "pass" if ppl > l1_cfg.get("safe", 50)
                  else ("warn" if ppl > l1_cfg.get("warn", 40)
                        else "fail"),
    }

    # L2: Burstiness
    burst = _burstiness(text)
    l2_cfg = cfg.get("l2", {})
    results["l2_burstiness"] = {
        "value": burst,
        "safe_threshold": l2_cfg.get("safe", 0.6),
        "status": "pass" if burst > l2_cfg.get("safe", 0.6) else "fail",
    }

    # L3: AI word co-occurrence
    density = _ai_word_density(text)
    l3_cfg = cfg.get("l3", {})
    max_words = l3_cfg.get("max_words", 2)
    results["l3_ai_words"] = {
        "value": density,
        "max_per_100": max_words,
        "status": "pass" if density * 100 <= max_words else "fail",
    }

    # L4: Sentence variation
    if previous_text:
        delta = _sentence_variation(text, previous_text)
        l4_cfg = cfg.get("l4", {})
        results["l4_variation"] = {
            "delta": delta,
            "warning_threshold": l4_cfg.get("warning", 0.20),
            "status": "pass" if delta < l4_cfg.get("warning", 0.20) else "fail",
        }
    else:
        cv = _sentence_variation(text)
        results["l4_variation"] = {
            "cv": cv,
            "status": "info",
            "note": "无前版对照, 仅报告变异系数",
        }

    # Overall verdict
    failures = sum(1 for r in results.values() if r["status"] == "fail")
    warns = sum(1 for r in results.values() if r["status"] == "warn")
    if failures > 0:
        verdict = f"[FAIL] {failures} 层超标"
    elif warns > 0:
        verdict = f"[WARN] {warns} 层预警"
    else:
        verdict = "[PASS] 全层通过"

    results["_verdict"] = verdict
    results["_timestamp"] = datetime.now().isoformat()
    return results


# ── 循环模式 ──

def detection_loop(text, max_iterations=5, previous_text=None):
    """Run detection loop: detect → (manual edit externally) → re-detect → compare.
    
    This is the outer loop controller. Each iteration runs detect_style().
    Between iterations: the user edits the text externally, then calls again.
    
    Args:
        text: current chapter text
        max_iterations: max detection rounds (prevents infinite loop)
        previous_text: original text for comparison (L4 baseline)
        
    Returns:
        list of per-round detection results
    """
    rounds = []
    current = text
    baseline = previous_text or text

    for r in range(max_iterations):
        result = detect_style(current, baseline)
        rounds.append(result)

        verdict = result["_verdict"]
        failures = [k for k, v in result.items()
                    if isinstance(v, dict) and v.get("status") == "fail"]
        if not failures:
            print(f"  Round {r + 1}: [PASS] All layers pass")
            break
        else:
            print(f"  Round {r + 1}: [FAIL] {failures}")

        # After each round, user edits. In automated mode we break.
        if r < max_iterations - 1:
            print(f"  → 请人工修改后重新检测, 或按 Ctrl+C 退出")
        break  # Single iteration per call; user re-runs for next round

    return rounds


def format_report(results):
    """Format detection results as readable report."""
    lines = ["# S4 风格检测报告",
             f"时间: {results.get('_timestamp', '')}",
             f"判定: {results.get('_verdict', 'N/A')}",
             "", "## 逐层结果", ""]
    for layer, data in results.items():
        if layer.startswith("_"):
            continue
        status = data.get("status", "?")
        icon = {"pass": "[OK]", "warn": "[WARN]", "fail": "[FAIL]", "info": "[INFO]"}.get(status, "[?]")
        lines.append(f"### {icon} {layer}")
        for k, v in data.items():
            if k != "status":
                lines.append(f"  - {k}: {v}")
        lines.append("")
    return lines


# ── CLI ──

def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        return

    text = None
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--text" and i < len(sys.argv) - 1:
            text = sys.argv[i + 1]
        elif arg == "--file" and i < len(sys.argv) - 1:
            path = Path(sys.argv[i + 1])
            if path.exists():
                text = path.read_text(encoding="utf-8", errors="replace")
            else:
                print(f"[FAIL] File not found: {path}")
                return

    if not text:
        print("[USAGE] python analysis/style_detection_loop.py --text '章节内容'")
        print("[USAGE] python analysis/style_detection_loop.py --file chapter.txt")
        return

    result = detect_style(text)
    for line in format_report(result):
        print(line)
    print(f"\n裁判: {result['_verdict']}")


if __name__ == "__main__":
    main()
