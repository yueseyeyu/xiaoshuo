# -*- coding: utf-8 -*-
"""
context_budget.py — 分层 Context Budget (P2.3)
================================================
来源: 建议文件 "MiMo Code → Context 预算管理 → 分层 Context Budget"

核心功能:
  1. 四层 Context 分级 (Tier 1-4), 按重要性分配 token 预算
  2. 根据章节类型动态调整各层权重
  3. 自动裁剪超预算内容
  4. 输出结构化 context dict 供 Prompt 构建

分层设计:
  Tier 1 (必载, 20%): 本章 specs、关键 Canon 条目、红线原则
  Tier 2 (高优, 30%): 前 3 章摘要、相关人物设定、弧光状态
  Tier 3 (中优, 30%): 全书梗概、世界观框架、伏笔状态
  Tier 4 (低优, 20%): 历史章节摘要、非相关设定、知识大脑经验

动态调整:
  - 战斗场景 → Tier 1 增加战斗系统设定
  - 感情戏   → Tier 1 增加人物关系设定
  - 过渡章节 → Tier 3 增加全书梗概权重

设计原则:
  - 零 LLM 依赖: 纯规则/统计
  - 可组合: 接受各种数据源, 统一裁剪输出
  - 可配置: 预算比例和裁剪策略可调

用法:
  from xiaoshuo.pipeline.context_budget import ContextBudget

  budget = ContextBudget(total_tokens=8000)
  budget.set_tier1("chapter_spec", "本章是战斗场景, 主角对决魔王")
  budget.set_tier1("red_lines", checker.format_for_prompt())
  budget.set_tier2("prev_summary", "上一章: 主角获得新武器")
  budget.set_tier3("worldview", "末世背景下的人类据点")
  budget.set_tier4("history", "...")

  context = budget.build(chapter_type="战斗")
  prompt = context["prompt_text"]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from xiaoshuo.infra.logging_config import get_logger

logger = get_logger("context_budget")


# ============================================================
# 常量
# ============================================================

# 默认预算分配 (百分比)
DEFAULT_BUDGET_RATIOS = {
    1: 0.20,  # Tier 1: 必载
    2: 0.30,  # Tier 2: 高优
    3: 0.30,  # Tier 3: 中优
    4: 0.20,  # Tier 4: 低优
}

# 章节类型 → 预算调整
CHAPTER_TYPE_ADJUSTMENTS = {
    "战斗": {1: 0.10, 2: -0.05, 3: -0.05, 4: 0.00},
    "对话": {1: 0.05, 2: 0.05, 3: -0.05, 4: -0.05},
    "感情": {1: 0.05, 2: 0.10, 3: -0.10, 4: -0.05},
    "过渡": {1: -0.05, 2: -0.05, 3: 0.10, 4: 0.00},
    "高潮": {1: 0.15, 2: 0.05, 3: -0.10, 4: -0.10},
    "日常": {1: -0.05, 2: 0.00, 3: 0.00, 4: 0.05},
}

TIER_LABELS = {
    1: "Tier1-必载",
    2: "Tier2-高优",
    3: "Tier3-中优",
    4: "Tier4-低优",
}

# 中文 token 估算: ~1.5 字符 = 1 token
CHARS_PER_TOKEN = 1.5


# ============================================================
# 数据结构
# ============================================================

@dataclass
class ContextEntry:
    """一条 context 条目。"""
    key: str          # 条目键 (如 "chapter_spec", "prev_summary")
    content: str      # 内容文本
    priority: int = 0 # 同层内优先级 (高优先保留)
    source: str = ""  # 来源标签


@dataclass
class TierBudget:
    """单层预算。"""
    tier: int
    label: str
    entries: list[ContextEntry] = field(default_factory=list)
    token_limit: int = 0
    used_tokens: int = 0
    truncated: bool = False

    def add(self, key: str, content: str, priority: int = 0, source: str = ""):
        self.entries.append(ContextEntry(
            key=key, content=content, priority=priority, source=source
        ))

    @property
    def entry_count(self) -> int:
        return len(self.entries)


@dataclass
class ContextBuildResult:
    """Context 构建结果。"""
    prompt_text: str = ""
    tier_details: dict = field(default_factory=dict)
    total_tokens: int = 0
    total_used: int = 0
    truncated_tiers: list[int] = field(default_factory=list)
    skipped_entries: list[str] = field(default_factory=list)

    @property
    def utilization(self) -> float:
        if self.total_tokens == 0:
            return 0.0
        return self.total_used / self.total_tokens

    def summary(self) -> str:
        parts = [f"Context Budget: {self.total_used}/{self.total_tokens} tokens "
                 f"({self.utilization:.0%})"]
        for tier, detail in sorted(self.tier_details.items()):
            icon = "⚠️" if detail["truncated"] else "✅"
            parts.append(f"  {icon} {detail['label']}: "
                        f"{detail['used']}/{detail['limit']} tokens "
                        f"({detail['entries']} 条)")
        if self.skipped_entries:
            parts.append(f"  跳过: {', '.join(self.skipped_entries)}")
        return "\n".join(parts)


# ============================================================
# ContextBudget 主类
# ============================================================

class ContextBudget:
    """分层 Context Budget 管理器。

    用法:
        budget = ContextBudget(total_tokens=8000)
        budget.set_tier1("spec", "本章战斗场景")
        budget.set_tier2("prev", "上章摘要")
        result = budget.build(chapter_type="战斗")
    """

    def __init__(self, total_tokens: int = 8000):
        self.total_tokens = total_tokens
        self._tiers: dict[int, TierBudget] = {
            1: TierBudget(tier=1, label=TIER_LABELS[1]),
            2: TierBudget(tier=2, label=TIER_LABELS[2]),
            3: TierBudget(tier=3, label=TIER_LABELS[3]),
            4: TierBudget(tier=4, label=TIER_LABELS[4]),
        }
        self._ratios = dict(DEFAULT_BUDGET_RATIOS)

    # ── 设置条目 ──

    def set_tier1(self, key: str, content: str, priority: int = 0, source: str = ""):
        """Tier 1 必载: 本章 specs、Canon 关键条目、红线原则。"""
        self._tiers[1].add(key, content, priority, source or "tier1")

    def set_tier2(self, key: str, content: str, priority: int = 0, source: str = ""):
        """Tier 2 高优: 前3章摘要、人物设定、弧光状态。"""
        self._tiers[2].add(key, content, priority, source or "tier2")

    def set_tier3(self, key: str, content: str, priority: int = 0, source: str = ""):
        """Tier 3 中优: 全书梗概、世界观、伏笔状态。"""
        self._tiers[3].add(key, content, priority, source or "tier3")

    def set_tier4(self, key: str, content: str, priority: int = 0, source: str = ""):
        """Tier 4 低优: 历史摘要、非相关设定、知识大脑经验。"""
        self._tiers[4].add(key, content, priority, source or "tier4")

    def set_tier(self, tier: int, key: str, content: str,
                priority: int = 0, source: str = ""):
        """通用设置接口。"""
        if tier not in self._tiers:
            raise ValueError(f"无效层级: {tier}, 应为 1-4")
        self._tiers[tier].add(key, content, priority, source or f"tier{tier}")

    # ── 构建 ──

    def build(self, chapter_type: str = "") -> ContextBuildResult:
        """构建最终 context, 返回裁剪后的 prompt 文本。

        Args:
            chapter_type: 章节类型 (用于动态调整预算)

        Returns:
            ContextBuildResult
        """
        result = ContextBuildResult(total_tokens=self.total_tokens)

        # 动态调整预算比例
        ratios = self._compute_ratios(chapter_type)

        # 计算各层 token 限制
        for tier, ratio in ratios.items():
            self._tiers[tier].token_limit = int(self.total_tokens * ratio)

        # 逐层构建 (Tier 1 优先, 低层可被裁剪)
        all_parts = []
        for tier_num in sorted(self._tiers.keys()):
            tier = self._tiers[tier_num]
            tier_text, used, truncated, skipped = self._build_tier(tier)

            all_parts.append(tier_text)
            tier.used_tokens = used
            tier.truncated = truncated

            result.tier_details[tier_num] = {
                "label": tier.label,
                "entries": tier.entry_count,
                "used": used,
                "limit": tier.token_limit,
                "truncated": truncated,
            }
            result.total_used += used
            if truncated:
                result.truncated_tiers.append(tier_num)
            result.skipped_entries.extend(skipped)

        result.prompt_text = "\n\n".join(p for p in all_parts if p)

        logger.debug("Context 构建完成: %d/%d tokens (%.0f%%)",
                     result.total_used, result.total_tokens, result.utilization * 100)

        return result

    def _compute_ratios(self, chapter_type: str) -> dict[int, float]:
        """根据章节类型计算调整后的预算比例。"""
        ratios = dict(self._ratios)
        if chapter_type in CHAPTER_TYPE_ADJUSTMENTS:
            adj = CHAPTER_TYPE_ADJUSTMENTS[chapter_type]
            for tier, delta in adj.items():
                ratios[tier] = max(0.05, ratios.get(tier, 0.25) + delta)

        # 归一化 (确保总和 = 1.0)
        total = sum(ratios.values())
        if total > 0:
            ratios = {k: v / total for k, v in ratios.items()}

        return ratios

    def _build_tier(self, tier: TierBudget) -> tuple[str, int, bool, list[str]]:
        """构建单层, 返回 (文本, 用量, 是否裁剪, 跳过列表)。"""
        if not tier.entries:
            return "", 0, False, []

        # 按优先级排序 (高优先)
        sorted_entries = sorted(tier.entries, key=lambda e: e.priority, reverse=True)

        parts = []
        used_tokens = 0
        truncated = False
        skipped = []

        for entry in sorted_entries:
            entry_tokens = self._estimate_tokens(entry.content)

            if used_tokens + entry_tokens <= tier.token_limit:
                # 完整放入
                parts.append(self._format_entry(entry))
                used_tokens += entry_tokens
            elif used_tokens < tier.token_limit:
                # 部分放入 (裁剪)
                remaining = tier.token_limit - used_tokens
                if remaining > 50:  # 至少 50 token 才值得裁剪放入
                    truncated_content = self._truncate(entry.content, remaining)
                    parts.append(self._format_entry(entry, truncated_content))
                    used_tokens += self._estimate_tokens(truncated_content)
                    truncated = True
                    skipped.append(f"{entry.key}(部分裁剪)")
                else:
                    skipped.append(entry.key)
                    truncated = True
            else:
                skipped.append(entry.key)
                truncated = True

        text = "\n".join(parts)
        return text, used_tokens, truncated, skipped

    def _format_entry(self, entry: ContextEntry, content: str = None) -> str:
        """格式化单条条目。"""
        text = content if content is not None else entry.content
        if entry.source:
            return f"[{entry.source}] {entry.key}:\n{text}"
        return f"{entry.key}:\n{text}"

    def _estimate_tokens(self, text: str) -> int:
        """估算 token 数 (中文 ~1.5 字符/token)。"""
        return max(1, int(len(text) / CHARS_PER_TOKEN))

    def _truncate(self, text: str, max_tokens: int) -> str:
        """裁剪文本到指定 token 数。"""
        max_chars = int(max_tokens * CHARS_PER_TOKEN)
        if len(text) <= max_chars:
            return text
        # 保留开头部分
        return text[:max_chars - 3] + "..."

    # ── 便捷批量设置 ──

    def load_from_writing_context(
        self,
        writing_context: dict,
        chapter_type: str = "",
    ) -> "ContextBudget":
        """从 writing_context dict 批量加载。

        支持的 key:
          - chapter_spec / blueprint → Tier 1
          - canon_rules / red_lines → Tier 1
          - prev_summaries / character_arcs → Tier 2
          - novel_synopsis / worldview / foreshadowing → Tier 3
          - history / knowledge_brain / style_dna_hints → Tier 4
        """
        tier1_keys = {"chapter_spec", "blueprint", "canon_rules", "red_lines",
                      "chapter_blueprint"}
        tier2_keys = {"prev_summaries", "character_arcs", "arc_status",
                      "prev_chapter_summary"}
        tier3_keys = {"novel_synopsis", "worldview", "foreshadowing",
                      "novel_outline", "timeline"}
        tier4_keys = {"history", "knowledge_brain", "style_dna_hints",
                      "style_profile", "technique_cards"}

        for key, value in writing_context.items():
            if not isinstance(value, str):
                continue
            if not value:
                continue

            if key in tier1_keys:
                self.set_tier1(key, value)
            elif key in tier2_keys:
                self.set_tier2(key, value)
            elif key in tier3_keys:
                self.set_tier3(key, value)
            elif key in tier4_keys:
                self.set_tier4(key, value)
            else:
                # 未知 key → 放 Tier 3
                self.set_tier3(key, value)

        return self

    # ── 统计 ──

    def stats(self) -> dict:
        """返回当前 budget 统计。"""
        return {
            "total_tokens": self.total_tokens,
            "tier_entries": {
                t: self._tiers[t].entry_count for t in sorted(self._tiers.keys())
            },
            "ratios": self._ratios,
        }


# ============================================================
# 便捷函数
# ============================================================

def build_context(
    writing_context: dict,
    total_tokens: int = 8000,
    chapter_type: str = "",
) -> ContextBuildResult:
    """便捷函数: 从 writing_context 构建 context。"""
    budget = ContextBudget(total_tokens=total_tokens)
    budget.load_from_writing_context(writing_context, chapter_type)
    return budget.build(chapter_type)
