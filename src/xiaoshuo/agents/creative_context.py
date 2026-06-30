# -*- coding: utf-8 -*-
"""
creative_context.py — Part A → Part B 桥接: 分析结果驱动骨架生成
================================================================
v8.2: 打通分析管线 → 创作管线的最后一公里。

功能:
  1. 加载 Part A 产出 (creative_guidance.json, technique_cards.json, rhythm benchmarks)
  2. 提取结构化创作上下文 (题材模式、节奏目标、技法卡片、角色原型)
  3. 注入 world_builder / outline_builder / character_designer 的提示词

数据流:
  data/reports/{genre}/creative_guidance/{genre}_创作指导.json
  data/processed/{genre}/quality/technique_cards.json
  data/processed/{genre}/rhythm/rhythm_*.csv (benchmark percentiles)
    ↓
  CreativeContext.load(genre)
    ↓
  world_builder / outline_builder / character_designer
    ↓
  assets/canon/ + assets/outline/

用法:
  from xiaoshuo.agents.creative_context import CreativeContext

  ctx = CreativeContext.load("末世")
  world_prompt_extra = ctx.build_world_context()
  outline_targets = ctx.get_rhythm_targets()
  character_archetypes = ctx.get_character_archetypes()
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Optional

from xiaoshuo import PROJECT_ROOT
from xiaoshuo.infra.logging_config import get_logger

logger = get_logger("creative_context")


class CreativeContext:
    """Part A → Part B 创作上下文桥接器。

    加载分析管线产出，为骨架生成提供数据驱动的创作指导。
    """

    def __init__(self, genre: str = "末世"):
        self.genre = genre
        self.guidance: dict = {}
        self.technique_cards: list[dict] = []
        self.rhythm_benchmarks: dict = {}
        self._loaded = False

    @classmethod
    def load(cls, genre: str = "末世") -> "CreativeContext":
        """加载指定题材的创作上下文。"""
        ctx = cls(genre)
        ctx._load_all()
        return ctx

    def _load_all(self):
        """加载所有 Part A 产出。"""
        self._load_guidance()
        self._load_technique_cards()
        self._load_rhythm_benchmarks()
        self._loaded = True
        logger.info("CreativeContext loaded for '%s': guidance=%s, cards=%d, benchmarks=%d",
                     self.genre, bool(self.guidance), len(self.technique_cards),
                     len(self.rhythm_benchmarks))

    def _load_guidance(self):
        """加载创作指导 JSON。"""
        path = (PROJECT_ROOT / "data" / "reports" / self.genre /
                "creative_guidance" / f"{self.genre}_创作指导.json")
        if not path.exists():
            logger.debug("Creative guidance not found: %s", path)
            return
        try:
            self.guidance = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load creative guidance: %s", e)

    def _load_technique_cards(self):
        """加载技法卡片。"""
        path = (PROJECT_ROOT / "data" / "processed" / self.genre /
                "quality" / "technique_cards.json")
        if not path.exists():
            logger.debug("Technique cards not found: %s", path)
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.technique_cards = data if isinstance(data, list) else data.get("cards", [])
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load technique cards: %s", e)

    def _load_rhythm_benchmarks(self):
        """加载节奏基准 (从 rhythm CSV 计算百分位)。"""
        rhythm_dir = PROJECT_ROOT / "data" / "processed" / self.genre / "rhythm"
        if not rhythm_dir.exists():
            return

        hooks, conflicts, pleasures = [], [], []
        for csv_file in sorted(rhythm_dir.glob("rhythm_*.csv")):
            try:
                import csv
                with open(csv_file, "r", encoding="utf-8-sig") as f:
                    for row in csv.DictReader(f):
                        hooks.append(float(row.get("hook_density", 0)))
                        conflicts.append(float(row.get("conflict_density", 0)))
                        pleasures.append(float(row.get("pleasure_intensity", 0)))
            except Exception:
                continue

        if not hooks:
            return

        def _pct(data, p):
            if not data:
                return 0
            sorted_data = sorted(data)
            idx = int(len(sorted_data) * p / 100)
            return sorted_data[min(idx, len(sorted_data) - 1)]

        self.rhythm_benchmarks = {
            "hook_density": {
                "p25": round(_pct(hooks, 25), 2),
                "p50": round(_pct(hooks, 50), 2),
                "p75": round(_pct(hooks, 75), 2),
                "mean": round(statistics.mean(hooks), 2),
            },
            "conflict_density": {
                "p25": round(_pct(conflicts, 25), 2),
                "p50": round(_pct(conflicts, 50), 2),
                "p75": round(_pct(conflicts, 75), 2),
                "mean": round(statistics.mean(conflicts), 2),
            },
            "pleasure_intensity": {
                "p25": round(_pct(pleasures, 25), 2),
                "p50": round(_pct(pleasures, 50), 2),
                "p75": round(_pct(pleasures, 75), 2),
                "mean": round(statistics.mean(pleasures), 2),
            },
            "sample_count": len(hooks),
        }

    # ── 上下文构建方法 ──

    def build_world_context(self) -> str:
        """构建世界观生成的附加上下文。"""
        parts = []
        if self.guidance:
            # 提取题材特征
            genre_insights = self.guidance.get("genre_insights", {})
            if genre_insights:
                parts.append("## 题材分析洞察 (来自精品书拆书)")
                for key, val in genre_insights.items():
                    if isinstance(val, str) and len(val) < 500:
                        parts.append(f"- {key}: {val}")
                    elif isinstance(val, dict):
                        parts.append(f"- {key}:")
                        for k2, v2 in list(val.items())[:5]:
                            parts.append(f"  - {k2}: {v2}")

            # 提取反套路建议
            anti_tropes = self.guidance.get("anti_tropes", [])
            if anti_tropes:
                parts.append("\n## 反套路提醒 (避免同质化)")
                for t in anti_tropes[:5]:
                    parts.append(f"- {t}")

        if self.rhythm_benchmarks:
            parts.append("\n## 精品节奏基准 (目标值)")
            for metric, vals in self.rhythm_benchmarks.items():
                if isinstance(vals, dict):
                    parts.append(f"- {metric}: 中位线 {vals.get('p50', 'N/A')}, "
                                 f"目标 ≥ P75 ({vals.get('p75', 'N/A')})")

        return "\n".join(parts) if parts else ""

    def get_rhythm_targets(self) -> dict:
        """获取节奏目标 (用于大纲生成时注入章纲)。"""
        if not self.rhythm_benchmarks:
            return {}
        return {
            "hook_density_target": self.rhythm_benchmarks.get("hook_density", {}).get("p75", 1.0),
            "conflict_density_target": self.rhythm_benchmarks.get("conflict_density", {}).get("p75", 0.5),
            "pleasure_intensity_target": self.rhythm_benchmarks.get("pleasure_intensity", {}).get("p50", 5.0),
            "sample_count": self.rhythm_benchmarks.get("sample_count", 0),
        }

    def get_character_archetypes(self) -> list[dict]:
        """获取角色原型建议 (从技法卡片和创作指导提取)。"""
        archetypes = []

        # 从创作指导提取
        if self.guidance:
            char_patterns = self.guidance.get("character_patterns", {})
            if char_patterns:
                for role, pattern in char_patterns.items():
                    if isinstance(pattern, dict):
                        archetypes.append({
                            "role": role,
                            "flaw": pattern.get("flaw", ""),
                            "ability": pattern.get("ability", ""),
                            "arc": pattern.get("arc", ""),
                            "source": "creative_guidance",
                        })

        # 从技法卡片提取角色相关卡片
        for card in self.technique_cards:
            if card.get("category") == "character":
                archetypes.append({
                    "role": card.get("title", ""),
                    "flaw": "",
                    "ability": card.get("description", "")[:200],
                    "arc": "",
                    "source": "technique_card",
                })

        return archetypes[:10]  # 限制数量

    def get_technique_cards(self, category: str = "", position: str = "", top_k: int = 5) -> list[dict]:
        """获取技法卡片 (按类别/位置过滤)。"""
        results = self.technique_cards
        if category:
            results = [c for c in results if c.get("category") == category]
        if position:
            results = [c for c in results if c.get("position") == position]
        return results[:top_k]

    def build_outline_context(self, total_chapters: int = 300) -> str:
        """构建大纲生成的附加上下文。"""
        parts = []

        # 节奏目标
        targets = self.get_rhythm_targets()
        if targets:
            parts.append("## 量化节奏目标 (来自精品书基准)")
            parts.append(f"- 钩子密度目标: ≥ {targets.get('hook_density_target', 1.0)}/千字")
            parts.append(f"- 冲突密度目标: ≥ {targets.get('conflict_density_target', 0.5)}/千字")
            parts.append(f"- 爽点强度目标: ≥ {targets.get('pleasure_intensity_target', 5.0)}/10")
            parts.append(f"- 样本量: {targets.get('sample_count', 0)} 本精品书")

        # 技法卡片 (结构类)
        struct_cards = self.get_technique_cards(category="structure", top_k=3)
        if struct_cards:
            parts.append("\n## 推荐结构技法")
            for card in struct_cards:
                parts.append(f"- {card.get('title', '')}: {card.get('description', '')[:100]}")

        # 反套路
        if self.guidance:
            anti_tropes = self.guidance.get("anti_tropes", [])
            if anti_tropes:
                parts.append("\n## 大纲反套路提醒")
                for t in anti_tropes[:3]:
                    parts.append(f"- {t}")

        return "\n".join(parts) if parts else ""

    @property
    def is_available(self) -> bool:
        """是否有可用的 Part A 分析数据。"""
        return self._loaded and (bool(self.guidance) or bool(self.rhythm_benchmarks))
