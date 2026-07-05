# -*- coding: utf-8 -*-
"""
style_detector.py — S4+++ 七层 AI 风格检测引擎
=================================================
v8.2: 从 novel.py cmd_s4() 的基础版升级为完整七层检测。

七层互补检测 (config.yaml detection.layers):
  L1 PPL (困惑度)              — 字符级 unigram 困惑度
  L2 Burstiness (突发性)       — 句长变异系数
  L3 AI词共现 (指纹词)         — 滑动窗口内 AI 指纹词密度
  L4 句长变化 (纵向漂移)       — 句长变异系数变化趋势
  L5 句法变异 (模式重复)       — 句式开头/结构重复率
  L6 语义连贯 (相邻句)         — 相邻句子词汇重叠度
  L7 N-gram PPL (二元/三元)    — bigram 困惑度 vs 基线

设计原则:
  - 零 LLM 依赖: 全部规则/统计检测, 不调用 LLM
  - 配置驱动: 阈值从 config.yaml 读取 (SSOT)
  - 增量检测: 支持单章检测 + 多章基线积累
  - 复用已有: scan_fingerprints() from cross_review.py

用法:
  from xiaoshuo.agents.style_detector import StyleDetector

  detector = StyleDetector()
  result = detector.detect(text, chapter_num=5)
  print(result.summary)
  print(result.verdict)  # PASS / WARNING / FATAL
"""

from __future__ import annotations

import re
import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from xiaoshuo.infra.config_manager import get_config
from xiaoshuo.infra.logging_config import get_logger

logger = get_logger("style_detector")


@dataclass
class LayerResult:
    """单层检测结果。"""
    layer: str
    name: str
    value: float
    threshold: float
    passed: bool
    detail: str = ""


@dataclass
class DetectionResult:
    """七层检测结果汇总。"""
    layers: list[LayerResult] = field(default_factory=list)
    verdict: str = "PASS"  # PASS / WARNING / FATAL
    flags: int = 0  # 异常层数
    summary: str = ""

    def add(self, layer: LayerResult):
        self.layers.append(layer)
        if not layer.passed:
            self.flags += 1


# ── v9.0: L8 心理前缀模式 (用于作者指纹偏离度检测) ──
_MENTAL_PREFIX_PATS = [
    re.compile(r'[他她]心里想[：，:]?'),
    re.compile(r'[他她]不禁感到'),
    re.compile(r'[他她]不由得'),
    re.compile(r'[他她]暗自'),
    re.compile(r'[他她]默默'),
    re.compile(r'[他她]突然意识到'),
    re.compile(r'[他她]这才明白'),
    re.compile(r'[他她]猛然惊觉'),
    re.compile(r'[他她]暗想[：，:]?'),
    re.compile(r'[他她]心想[：，:]?'),
]

# 对话引号模式 (用于作者指纹偏离度检测)
_DIALOGUE_CHARS = re.compile(r'[「『"\u201c\u300c\u300e]([^」』"\u201d\u300d\u300f]+)')


class StyleDetector:
    """S4+++ 八层 AI 风格检测器。

    用法:
        detector = StyleDetector()
        result = detector.detect(chapter_text)
        # 带作者指纹 (v9.0):
        result = detector.detect(text, author_fingerprint={"avg_sentence_length": 35, ...})
    """

    def __init__(self):
        cfg = get_config().get("detection", {}).get("layers", {})
        self._cfg = cfg

    def detect(self, text: str, chapter_num: int = 0, baseline: dict | None = None,
               author_fingerprint: dict | None = None) -> DetectionResult:
        """执行完整八层检测。

        Args:
            text: 章节文本
            chapter_num: 章节号 (用于报告)
            baseline: 历史基线数据 (多章积累后传入, 用于 L4 纵向对比)
            author_fingerprint: 作者风格指纹 (v9.0, 用于 L8 偏离度检测)
                {"avg_sentence_length": float, "dialogue_ratio": float, "mental_prefix_density": float}

        Returns:
            DetectionResult 汇总结果
        """
        result = DetectionResult()

        # L1: PPL
        result.add(self._l1_ppl(text))
        # L2: Burstiness
        result.add(self._l2_burstiness(text))
        # L3: AI词共现
        result.add(self._l3_ai_word_cooccurrence(text))
        # L4: 句长变化 (需要基线)
        result.add(self._l4_sentence_length_variation(text, baseline))
        # L5: 句法变异
        result.add(self._l5_syntax_variation(text))
        # L6: 语义连贯
        result.add(self._l6_semantic_continuity(text))
        # L7: N-gram PPL
        result.add(self._l7_ngram_ppl(text, baseline))
        # L8: 作者指纹偏离度 (v9.0, 需要作者指纹)
        result.add(self._l8_author_fingerprint_deviation(text, author_fingerprint))

        # 综合判定
        if result.flags == 0:
            result.verdict = "PASS"
        elif result.flags <= 2:
            result.verdict = "WARNING"
        else:
            result.verdict = "FATAL"

        result.summary = self._build_summary(result, chapter_num)
        return result

    # ── L1: Perplexity ──

    def _l1_ppl(self, text: str) -> LayerResult:
        """L1: 字符级 unigram 困惑度。"""
        cfg = self._cfg.get("l1_ppl", {})
        safe = cfg.get("safe_threshold", 50)
        warn = cfg.get("warn_threshold", 40)

        chars = [c for c in text if c.strip()]
        total = len(chars)
        if total < 10:
            return LayerResult("L1", "PPL", 0, safe, True, "文本太短")

        freq = Counter(chars)
        entropy = -sum((f / total) * math.log2(f / total) for f in freq.values())
        ppl = 2 ** entropy

        passed = ppl > warn  # 高于警告阈值才算通过
        status = "人类风格" if ppl > safe else ("警告" if ppl > warn else "AI嫌疑")
        return LayerResult("L1", "PPL", round(ppl, 2), safe, passed,
                          f"{status} (安全>{safe}, 警告>{warn})")

    # ── L2: Burstiness ──

    def _l2_burstiness(self, text: str) -> LayerResult:
        """L2: 句长变异系数 (Burstiness)。"""
        cfg = self._cfg.get("l2_burstiness", {})
        safe = cfg.get("safe_threshold", 0.6)

        sentences = re.split(r'[。！？!?\n]+', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        if len(sentences) < 3:
            return LayerResult("L2", "Burstiness", 0, safe, True, "句子太少")

        sent_lens = [len(s) for s in sentences]
        mean_len = sum(sent_lens) / len(sent_lens)
        if mean_len < 1:
            return LayerResult("L2", "Burstiness", 0, safe, True, "句长为零")

        var = math.sqrt(sum((x - mean_len) ** 2 for x in sent_lens) / len(sent_lens))
        burstiness = var / mean_len

        passed = burstiness > safe
        status = "人类风格" if passed else "AI嫌疑"
        return LayerResult("L2", "Burstiness", round(burstiness, 4), safe, passed,
                          f"{status} (句数={len(sentences)}, 均长={mean_len:.1f})")

    # ── L3: AI词共现 ──

    def _l3_ai_word_cooccurrence(self, text: str) -> LayerResult:
        """L3: AI 指纹词滑动窗口共现检测。"""
        cfg = self._cfg.get("l3_ai_word_cooccurrence", {})
        window_size = cfg.get("window_size", 100)
        max_ai_words = cfg.get("max_ai_words", 2)

        # 复用 cross_review 的指纹词库
        try:
            from xiaoshuo.agents.cross_review import scan_fingerprints, AI_FINGERPRINT_WORDS
            fp_result = scan_fingerprints(text)
            total_hits = fp_result.get("total_count", 0)
            high_risk = fp_result.get("high_risk_count", 0)
            text_len = len(text.replace("\n", "").replace(" ", ""))
            density = total_hits / max(text_len / 1000, 1)

            # 滑动窗口检测: 找出密集出现的窗口
            all_fp_words = []
            for words in AI_FINGERPRINT_WORDS.values():
                all_fp_words.extend(words)
            fp_pattern = re.compile("|".join(re.escape(w) for w in all_fp_words))

            # 简化: 用密度代替窗口检测
            passed = density <= max_ai_words
            status = "安全" if passed else "AI指纹词密集"
            return LayerResult("L3", "AI词共现", round(density, 2), max_ai_words, passed,
                              f"{status} (总命中={total_hits}, 高危={high_risk}, 密度={density:.1f}/千字)")
        except ImportError:
            return LayerResult("L3", "AI词共现", 0, max_ai_words, True, "指纹词库不可用")

    # ── L4: 句长变化 (纵向漂移) ──

    def _l4_sentence_length_variation(self, text: str, baseline: dict | None = None) -> LayerResult:
        """L4: 句长变异系数与历史基线对比。"""
        cfg = self._cfg.get("l4_sentence_length_variation", {})
        warn_threshold = cfg.get("warning_threshold", 0.20)

        sentences = re.split(r'[。！？!?\n]+', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        if len(sentences) < 3:
            return LayerResult("L4", "句长变化", 0, warn_threshold, True, "句子太少")

        sent_lens = [len(s) for s in sentences]
        mean_len = sum(sent_lens) / len(sent_lens)
        var = math.sqrt(sum((x - mean_len) ** 2 for x in sent_lens) / len(sent_lens)) if mean_len > 0 else 0
        cv = var / mean_len if mean_len > 0 else 0

        if baseline and "l2_burstiness" in baseline:
            baseline_cv = baseline["l2_burstiness"]
            if baseline_cv > 0:
                drop = (baseline_cv - cv) / baseline_cv
                passed = drop < warn_threshold
                return LayerResult("L4", "句长变化", round(drop, 4), warn_threshold, passed,
                                  f"变异系数={cv:.4f}, 基线={baseline_cv:.4f}, 下降={drop:.1%}")
        else:
            # 无基线时，检查当前章节内部的句长分布是否过于均匀
            passed = cv > 0.3  # 低于0.3说明过于均匀
            return LayerResult("L4", "句长变化", round(cv, 4), 0.3, passed,
                              f"变异系数={cv:.4f} ({'均匀' if cv < 0.3 else '正常'})")

    # ── L5: 句法变异 (模式重复) ──

    def _l5_syntax_variation(self, text: str) -> LayerResult:
        """L5: 句式开头/结构重复率检测。"""
        cfg = self._cfg.get("l5_syntax_variation", {})
        safe = cfg.get("safe_threshold", 0.30)
        fatal = cfg.get("fatal_threshold", 0.40)

        sentences = re.split(r'[。！？!?\n]+', text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 2]
        if len(sentences) < 5:
            return LayerResult("L5", "句法变异", 0, safe, True, "句子太少")

        # 提取句式开头 (前2-4个字)
        prefixes = [s[:3] for s in sentences if len(s) >= 3]
        if not prefixes:
            return LayerResult("L5", "句法变异", 0, safe, True, "无有效句子")

        prefix_counts = Counter(prefixes)
        most_common = prefix_counts.most_common(1)[0]
        max_repeat = most_common[1]
        repeat_rate = max_repeat / len(sentences)

        # 检测重复句式模式
        passed = repeat_rate < fatal
        status = "安全" if repeat_rate < safe else ("警告" if repeat_rate < fatal else "致命")
        top_prefix = most_common[0]
        return LayerResult("L5", "句法变异", round(repeat_rate, 4), safe, passed,
                          f"{status} (最高重复='{top_prefix}' ×{max_repeat}, 率={repeat_rate:.1%})")

    # ── L6: 语义连贯 (相邻句) ──

    def _l6_semantic_continuity(self, text: str) -> LayerResult:
        """L6: 相邻句子词汇重叠度 (代理语义连贯性)。"""
        cfg = self._cfg.get("l6_semantic_continuity", {})
        safe = cfg.get("safe_threshold", 0.7)

        sentences = re.split(r'[。！？!?\n]+', text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 5]
        if len(sentences) < 3:
            return LayerResult("L6", "语义连贯", 0, safe, True, "句子太少")

        # 计算相邻句子的字符重叠率
        overlaps = []
        for i in range(len(sentences) - 1):
            s1_chars = set(sentences[i])
            s2_chars = set(sentences[i + 1])
            if s1_chars and s2_chars:
                overlap = len(s1_chars & s2_chars) / len(s1_chars | s2_chars)
                overlaps.append(overlap)

        if not overlaps:
            return LayerResult("L6", "语义连贯", 0, safe, True, "无相邻句对")

        avg_overlap = sum(overlaps) / len(overlaps)
        # 过高重叠 = 重复啰嗦, 过低 = 跳跃断裂
        # 理想区间 0.3-0.7
        passed = 0.2 < avg_overlap < 0.85
        status = "正常" if passed else ("重复" if avg_overlap >= 0.85 else "跳跃")
        return LayerResult("L6", "语义连贯", round(avg_overlap, 4), safe, passed,
                          f"{status} (平均重叠={avg_overlap:.2%}, 句对={len(overlaps)})")

    # ── L7: N-gram PPL ──

    def _l7_ngram_ppl(self, text: str, baseline: dict | None = None) -> LayerResult:
        """L7: Bigram 困惑度 (二元模型)。"""
        cfg = self._cfg.get("l7_ngram_ppl", {})
        fatal_ratio = cfg.get("fatal_threshold_ratio", 0.6)

        chars = [c for c in text if c.strip()]
        if len(chars) < 20:
            return LayerResult("L7", "N-gram PPL", 0, fatal_ratio, True, "文本太短")

        # Bigram 频率
        bigrams = [(chars[i], chars[i + 1]) for i in range(len(chars) - 1)]
        bg_freq = Counter(bigrams)
        unigram_freq = Counter(chars)
        total = len(chars)

        # Bigram PPL: -log P(w_i | w_{i-1}) 的平均值
        log_probs = []
        for bg, count in bg_freq.items():
            w1, w2 = bg
            p_bg = count / (total - 1)
            p_w1 = unigram_freq[w1] / total
            if p_w1 > 0:
                cond_p = p_bg / p_w1
                if cond_p > 0:
                    log_probs.append(-math.log2(cond_p) * count)

        if not log_probs:
            return LayerResult("L7", "N-gram PPL", 0, fatal_ratio, True, "无法计算")

        avg_log_prob = sum(log_probs) / (total - 1)
        bg_ppl = 2 ** avg_log_prob

        # 与基线对比 (如果有)
        if baseline and "l7_ngram_ppl" in baseline:
            baseline_ppl = baseline["l7_ngram_ppl"]
            ratio = bg_ppl / baseline_ppl if baseline_ppl > 0 else 1.0
            passed = ratio >= fatal_ratio
            status = "正常" if passed else "过于可预测"
            return LayerResult("L7", "N-gram PPL", round(bg_ppl, 2), fatal_ratio, passed,
                              f"{status} (PPL={bg_ppl:.2f}, 基线={baseline_ppl:.2f}, 比值={ratio:.2f})")
        else:
            # 无基线时，用绝对值判断 (经验阈值)
            passed = bg_ppl > 5.0  # bigram PPL < 5 说明过于可预测
            status = "正常" if passed else "可能过于可预测"
            return LayerResult("L7", "N-gram PPL", round(bg_ppl, 2), 5.0, passed,
                              f"{status} (Bigram PPL={bg_ppl:.2f}, 需基线积累提高精度)")

    # ── 汇总报告 ──

    def _build_summary(self, result: DetectionResult, chapter_num: int) -> str:
        """构建汇总报告文本。"""
        lines = [
            f"\n{'=' * 60}",
            f"  S4+++ 八层检测报告" + (f" — 第{chapter_num}章" if chapter_num else ""),
            f"{'=' * 60}",
        ]
        for lr in result.layers:
            icon = "[OK]" if lr.passed else ("[WARN]" if result.verdict != "FATAL" else "[FAIL]")
            lines.append(f"  {lr.layer} {lr.name:<12s}: {lr.value:>10.4f}  {icon} {lr.detail}")

        lines.append(f"{'=' * 60}")
        verdict_icon = {"PASS": "[OK]", "WARNING": "[WARN]", "FATAL": "[FAIL]"}[result.verdict]
        total_layers = len(result.layers)
        lines.append(f"  综合: {verdict_icon} {result.verdict} ({result.flags}/{total_layers} 层异常)")
        lines.append(f"{'=' * 60}")
        return "\n".join(lines)

    # ── L8: 作者指纹偏离度 (v9.0) ──

    def _l8_author_fingerprint_deviation(self, text: str,
                                          author_fp: dict | None = None) -> LayerResult:
        """L8: 作者指纹偏离度 — 生成稿与作者风格指纹的量化对比。

        检测维度:
          1. 句长偏离度 (avg_sentence_length)
          2. 对话占比偏离度 (dialogue_ratio)
          3. 心理前缀密度偏离度 (mental_prefix_density)

        无作者指纹时跳过 (返回 PASS)。
        """
        if not author_fp or not author_fp.get("avg_sentence_length"):
            return LayerResult("L8", "作者指纹", 0, 0.3, True, "无作者指纹, 跳过")

        # 提取生成稿指纹
        draft_fp = self._extract_fingerprint(text)

        deviations = []
        details = []

        # 1. 句长偏离度
        author_sl = author_fp.get("avg_sentence_length", 0)
        draft_sl = draft_fp["avg_sentence_length"]
        if author_sl > 0:
            sl_dev = abs(draft_sl - author_sl) / author_sl
            deviations.append(sl_dev)
            details.append(f"句长: 稿{draft_sl:.0f} vs 作者{author_sl:.0f} (偏离{sl_dev:.0%})")

        # 2. 对话占比偏离度
        author_dr = author_fp.get("dialogue_ratio", 0)
        draft_dr = draft_fp["dialogue_ratio"]
        if author_dr > 0:
            dr_dev = abs(draft_dr - author_dr) / author_dr
            deviations.append(dr_dev)
            details.append(f"对话比: 稿{draft_dr:.0%} vs 作者{author_dr:.0%} (偏离{dr_dev:.0%})")

        # 3. 心理前缀密度偏离度
        author_mp = author_fp.get("mental_prefix_density", 0)
        draft_mp = draft_fp["mental_prefix_density"]
        if author_mp > 0:
            mp_dev = abs(draft_mp - author_mp) / author_mp
            deviations.append(mp_dev)
            details.append(f"心理前缀: 稿{draft_mp:.1f}/千字 vs 作者{author_mp:.1f}/千字 (偏离{mp_dev:.0%})")

        if not deviations:
            return LayerResult("L8", "作者指纹", 0, 0.3, True, "作者指纹数据不完整")

        overall = sum(deviations) / len(deviations)
        cfg = self._cfg.get("l8_author_fingerprint", {})
        warn_threshold = cfg.get("warning_threshold", 0.3)
        fatal_threshold = cfg.get("fatal_threshold", 0.5)

        passed = overall < fatal_threshold
        status = "一致" if overall < warn_threshold else ("偏离" if overall < fatal_threshold else "严重偏离")

        return LayerResult("L8", "作者指纹", round(overall, 4), fatal_threshold, passed,
                          f"{status} ({'; '.join(details)})")

    def _extract_fingerprint(self, text: str) -> dict:
        """从文本提取风格指纹。"""
        # 句长
        sentences = re.split(r'[。！？!?\n]+', text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 2]
        if sentences:
            avg_sl = sum(len(s) for s in sentences) / len(sentences)
        else:
            avg_sl = 0

        # 对话占比
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        dialogue_chars = sum(len(m.group(1)) for m in _DIALOGUE_CHARS.finditer(text))
        dialogue_ratio = dialogue_chars / max(chinese_chars, 1)

        # 心理前缀密度 (每千字)
        mp_count = sum(len(pat.findall(text)) for pat in _MENTAL_PREFIX_PATS)
        mental_prefix_density = mp_count / max(chinese_chars / 1000, 1)

        return {
            "avg_sentence_length": avg_sl,
            "dialogue_ratio": dialogue_ratio,
            "mental_prefix_density": mental_prefix_density,
        }

    def get_baseline(self, text: str) -> dict:
        """从文本提取基线数据 (用于多章积累后的纵向对比)。

        Returns:
            {"l2_burstiness": float, "l7_ngram_ppl": float}
        """
        l2 = self._l2_burstiness(text)
        l7 = self._l7_ngram_ppl(text)
        return {
            "l2_burstiness": l2.value,
            "l7_ngram_ppl": l7.value,
        }
