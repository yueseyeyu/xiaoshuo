#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
intent_translator.py — 创作意图→结构化指令翻译 (规则映射为主, LLM兜底)
=================================================================
作者说"这段太拖了" → 系统翻译为"定位节奏低谷,建议压缩+加冲突"

用法: python analysis/intent_translator.py "这章主角太被动了"
      python novel.py intent "高潮不够爽"
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── 规则映射表: 意图关键词 → 维度 + 动作 ──
INTENT_MAP = {
    "压迫感": ("tension", [
        "当前章张力评分应≥7，不足则增加紧迫事件",
        "反派出场频率检查：确保每5章至少1次直接对抗",
        "每个事件附带明确后果，不轻易放过主角",
    ]),
    "节奏拖": ("pacing", [
        "定位低谷段落: 冲突密度<0.2的连续3段→建议压缩或加冲突",
        "检查钩子密度是否低于题材中位数→章末加悬念或反转",
        "缩短过渡段: 环境描写不超过200字, 直接推进剧情",
    ]),
    "对话干瘪": ("dialogue", [
        "对话占比检查: 应达35-55%, 不足时减少叙事转对话",
        "每段对话必须推进情节或揭示冲突, 删除纯寒暄",
        "角色声线区分: 不同角色的用词/句长应有明显差异",
    ]),
    "主角被动": ("agency", [
        "减少主角被动回应段落, 每5段至少1段主动决策",
        "对话中主角句占比从当前值提升至50-60%",
        "检查主角是否在关键转折点有主动选择(而非被事件推着走)",
    ]),
    "高潮不够爽": ("climax", [
        "高潮章爽点密度检查: 应≥0.4, 不足时叠加2种爽点类型",
        "高潮前铺垫: 至少3章的紧张累积(冲突密度持续上升)",
        "高潮后释放: 不宜立即高潮结束, 留0.5-1章释放+新钩子",
    ]),
    "设定单薄": ("worldbuilding", [
        "世界观暴露密度: 每3章至少揭示1个新规则或背景",
        "冲突→世界规则映射: 每次战斗/矛盾应体现独特的世界设定",
        "从 creative_guidance 中该题材的核心冲突分布寻找灵感",
    ]),
    "情感平淡": ("emotion", [
        "情感V值波动检测: 每5章应有≥1次显著V值变化(>0.3)",
        "情感锚点检查: 前3章应建立主角情感基线(VAD三元组)",
        "借鉴该题材引爆情感共鸣的桥段: 牺牲/守护/背叛/绝境",
    ]),
    "开头劝退": ("opening", [
        "前3章钩子密度: 应≥0.35, 不足时在第2章加情绪炸弹",
        "首章300字内必须出现冲突或悬念(检查开篇冲突密度)",
        "避免信息倾泻: 世界观设定分散在1-5章, 不集中堆砌",
    ]),
    "收尾崩": ("ending", [
        "结局预测: 前文伏笔回收率应向100%靠拢",
        "结局情绪: 检查VAD曲线是否在高潮后提供情感释放",
        "开放式结局风险: 如留悬念, 确保有明确的主题收束",
    ]),
}


def translate(intent_text):
    """Match intent text against rules, return structured actions. Fallback: generic advice."""
    # Normalize
    text = intent_text.strip().lower()

    # Try exact keyword match
    for keyword, (dimension, actions) in INTENT_MAP.items():
        if keyword in text:
            return {"matched": True, "intent": keyword, "dimension": dimension,
                    "actions": actions, "source": "rule_map"}

    # Partial match: check individual chars for overlap
    best_score = 0
    best_match = None
    for keyword, (dimension, actions) in INTENT_MAP.items():
        score = sum(1 for c in keyword if c in text)
        if score >= 2 and score > best_score:
            best_score = score
            best_match = (keyword, dimension, actions)

    if best_match:
        keyword, dimension, actions = best_match
        return {"matched": True, "intent": keyword, "dimension": dimension,
                "actions": actions, "source": "partial_match", "confidence": "medium"}

    # Fallback: generic advice
    return {
        "matched": False,
        "source": "fallback",
        "actions": [
            "未匹配到具体意图，请尝试: 压迫感/节奏拖/对话干瘪/主角被动/高潮不够爽/设定单薄/情感平淡/开头劝退/收尾崩",
            "或使用 `python novel.py analyze --genre 末世` 生成完整创作指导",
        ],
    }


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("--help", "-h"):
        print("用法: python novel.py intent \"这章太拖了\"")
        print(f"支持意图: {', '.join(INTENT_MAP.keys())}")
        return

    intent = sys.argv[1]
    result = translate(intent)
    print(f"\n[INTENT] \"{intent}\"")
    if result.get("matched"):
        print(f"  匹配: {result['intent']} (维度: {result['dimension']}, 来源: {result.get('source','?')})")
    else:
        print(f"  [FALLBACK] 未精确匹配 → 通用建议")
    print()
    for i, a in enumerate(result["actions"], 1):
        print(f"  {i}. {a}")


if __name__ == "__main__":
    main()
