#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
sycophancy_detector.py — AI谄媚检测器 (v7.5新增)
================================================
检测 AI 输出是否存在谄媚信号（模糊套话、先扬后抑、无证据断言），
自动标记或拦截，确保 S3 评审团和 S4++ 检测层的批判性。

核心理念 (来自李开复反谄媚提示词):
- 顶级专家。准确胜过讨好。直接，敢于争辩。
- 没有证据时说"我不知道"。
- 先讲反方观点。没有新证据，不要轻易让步。

证据标签系统:
  [KNOWN]    — 训练事实 / 已拆书验证的规律 (HIGH)
  [COMPUTED] — 计算得出 (HIGH)
  [INFERRED] — 推论 (MED)
  [COMMON]   — 通用领域知识 (MED)
  [FRAME]    — 符号体系/分析框架 (LOW)
  [GUESS]    — 没有根据的直觉 (VERY LOW)

用法:
  from src.xiaoshuo.tools.sycophancy_detector import SycophancyDetector
  detector = SycophancyDetector()
  result = detector.check(ai_output)
"""

import re
from typing import List, Dict, Optional


# ── 红旗信号模式 ──

_RED_FLAG_PATTERNS = [
    # 恭维句式
    (r"您的.*(?:非常|很|特别|十分).*(?:独特|优秀|出色|棒|精彩|厉害)", "恭维", "HIGH"),
    # 模糊正面
    (r"在.*方面表现良好", "模糊正面", "HIGH"),
    # 模糊负面
    (r"在.*方面存在一定不足", "模糊负面", "MED"),
    # 八股总结
    (r"综上所述.*总而言之", "八股总结", "MED"),
    (r"综上所述", "八股总结", "LOW"),
    # 过度简化
    (r"一个(?:模式|原因|解释).*(?:一切|所有|全部)", "过度简化", "HIGH"),
    # 免责声明开头
    (r"^(?:当然|需要注意的是|值得.*的是|不可否认)", "免责声明", "LOW"),
    # 虚假权威
    (r"细节.*(?:过多|丰富).*权威", "虚假权威", "HIGH"),
    # 轻易让步
    (r"(?:您说得对|您是对的|确实如此).*(?:但是|不过)", "轻易让步", "MED"),
]

# 证据标签
_EVIDENCE_TAGS = {"KNOWN", "COMPUTED", "INFERRED", "COMMON", "FRAME", "GUESS"}

# 判断词（如果出现但没有标签 → 无标签断言）
_JUDGMENT_WORDS = re.compile(r"(?:是|会|应该|必须|肯定|一定|绝[对非]|显然|明显|无疑)")


class SycophancyDetector:
    """检测 AI 输出中的谄媚信号。

    用法:
        detector = SycophancyDetector()
        result = detector.check(s3_output_text)
        if not result["passed"]:
            print(f"[WARN] {result['issue_count']} 个谄媚信号需要修复")
    """

    def __init__(self):
        self.patterns = [(re.compile(p), label, severity) for p, label, severity in _RED_FLAG_PATTERNS]

    def check(self, text: str) -> Dict:
        """检测文本中的谄媚信号。

        Args:
            text: AI 输出的文本

        Returns:
            dict with:
            - passed: bool, 是否通过
            - flags: list of dict, 红旗信号列表
            - untagged_claims: list of str, 无标签断言
            - issue_count: int, 总问题数
            - suggestion: str or None, 修复建议
        """
        flags = []
        for pattern, label, severity in self.patterns:
            for match in pattern.finditer(text):
                flags.append({
                    "label": label,
                    "severity": severity,
                    "match": match.group(0).strip(),
                    "position": match.start(),
                })

        untagged = self._find_untagged_claims(text)

        issue_count = len(flags) + len(untagged)
        passed = issue_count == 0

        suggestion = None
        if not passed:
            suggestion = self._generate_suggestion(flags, untagged)

        return {
            "passed": passed,
            "flags": flags,
            "untagged_claims": untagged,
            "issue_count": issue_count,
            "suggestion": suggestion,
        }

    def _find_untagged_claims(self, text: str) -> List[str]:
        """找出没有证据标签的断言句。

        规则：如果句子包含判断词，且前面没有 [KNOWN]/[COMPUTED] 等标签，
        则认为是无标签断言。
        """
        sentences = re.split(r"[。！？；\n]+", text)
        untagged = []
        for s in sentences:
            s = s.strip()
            if len(s) < 10:
                continue
            # 检查是否有判断词
            if not _JUDGMENT_WORDS.search(s):
                continue
            # 检查是否已有证据标签
            tag_pattern = r"\[(?:" + "|".join(_EVIDENCE_TAGS) + r")\]"
            if re.search(tag_pattern, s):
                continue
            # 检查是否是输出格式行（如"综合判定:"开头）
            if re.match(r"^(?:综合判定|优先修复|红旗信号|无标签断言)", s):
                continue
            untagged.append(s)
        return untagged

    @staticmethod
    def _generate_suggestion(flags: List[Dict], untagged: List[str]) -> str:
        """生成修复建议。"""
        parts = []
        if flags:
            high_flags = [f for f in flags if f["severity"] == "HIGH"]
            if high_flags:
                parts.append(f"[HIGH] {len(high_flags)} 个高危红旗信号，优先修复")
            med_flags = [f for f in flags if f["severity"] == "MED"]
            if med_flags:
                parts.append(f"[MED] {len(med_flags)} 个中危红旗信号")
        if untagged:
            parts.append(f"[UNTAGGED] {len(untagged)} 条无标签断言，需添加 [KNOWN]/[COMPUTED]/[INFERRED] 等标签")
        return " | ".join(parts) if parts else ""


# ── CLI ──

def main():
    import sys
    from pathlib import Path

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
        print("[USAGE] python sycophancy_detector.py --text 'AI输出文本'")
        print("[USAGE] python sycophancy_detector.py --file output.txt")
        return

    detector = SycophancyDetector()
    result = detector.check(text)

    print(f"[{'OK' if result['passed'] else 'FAIL'}] 谄媚检测: {result['issue_count']} 个问题")
    if result["flags"]:
        print("\n红旗信号:")
        for f in result["flags"]:
            print(f"  [{f['severity']}] {f['label']}: \"{f['match']}\"")
    if result["untagged_claims"]:
        print("\n无标签断言:")
        for c in result["untagged_claims"]:
            print(f"  - {c[:80]}...")
    if result["suggestion"]:
        print(f"\n修复建议: {result['suggestion']}")


if __name__ == "__main__":
    main()