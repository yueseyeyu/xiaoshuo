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

    # ── 世界推演上下文构建 (v8.6 WSE 深化) ──

    @staticmethod
    def build_world_simulation_context(
        project_id: str,
        chapter: int | None = None,
    ) -> str:
        """从世界推演状态构建写作上下文，注入章节蓝图/大纲生成。

        读取项目的 world_state（势力状态、角色运行时状态、推演事件），
        将其格式化为结构化文本，让 LLM 生成的大纲基于推演结果。

        Args:
            project_id: 项目 ID
            chapter: 指定章节号；None 则用 world_state 当前章节

        Returns:
            结构化文本，可直接拼入 outline/blueprint 的 user prompt
        """
        try:
            from xiaoshuo.api.services import world_state_service as wss
        except ImportError:
            logger.warning("world_state_service 不可用，跳过推演上下文")
            return ""

        ws = wss.get_world_state(project_id)
        if ws is None:
            logger.debug("项目 %s 无 world_state", project_id)
            return ""

        target_chapter = chapter if chapter is not None else ws.get("chapter", 0)

        parts: list[str] = []
        parts.append(f"## 世界推演状态 (第{target_chapter}章快照)")

        # ── 势力状态 ──
        factions_state = ws.get("factions_state", [])
        if factions_state:
            parts.append(f"\n### 势力动态 ({len(factions_state)} 个势力)")
            for fs in factions_state:
                name = fs.get("name", fs.get("id", "未知"))
                stability = fs.get("stability", 0.5)
                morale = fs.get("morale", 0.5)
                treasury = fs.get("treasury", 0.5)
                threat = fs.get("threat_level", 0.3)
                power = fs.get("power_level", 5)

                # 状态摘要
                status_tags: list[str] = []
                if stability < 0.3:
                    status_tags.append("⚠️内部不稳")
                if morale < 0.3:
                    status_tags.append("士气低落")
                if threat > 0.7:
                    status_tags.append("⚠️外部威胁严重")
                if treasury < 0.2:
                    status_tags.append("财政枯竭")
                tag_str = f" [{', '.join(status_tags)}]" if status_tags else ""

                parts.append(
                    f"- **{name}** (实力Lv.{power}){tag_str}: "
                    f"稳定{stability:.0%} 士气{morale:.0%} "
                    f"财政{treasury:.0%} 威胁{threat:.0%}"
                )

        # ── 角色运行时状态 ──
        chars_state = ws.get("characters_state", [])
        if chars_state:
            parts.append(f"\n### 角色运行时状态 ({len(chars_state)} 人)")
            for cs in chars_state:
                name = cs.get("name", "未知角色")
                health = cs.get("health", 1.0)
                mood = cs.get("mood", "normal")
                location = cs.get("location", "未知")
                fac_id = cs.get("faction_id", "")

                mood_map = {
                    "normal": "平静", "confident": "自信", "weary": "疲惫",
                    "fearful": "恐惧", "angry": "愤怒",
                }
                mood_cn = mood_map.get(mood, mood)
                health_str = f"{health:.0%}" if health < 1.0 else "健康"
                fac_str = f" (属{fac_id})" if fac_id else ""

                state_tags: list[str] = []
                if health < 0.3:
                    state_tags.append("重伤")
                if mood in ("fearful", "angry"):
                    state_tags.append(mood_cn)
                tag_str = f" [{', '.join(state_tags)}]" if state_tags else ""

                parts.append(
                    f"- **{name}**{fac_str}: {health_str}, 心情{mood_cn}, "
                    f"位于{location}{tag_str}"
                )

        # ── 近期推演事件 (取最近 10 条) ──
        all_events: list[dict] = []
        for snap in ws.get("snapshots", []):
            snap_ch = snap.get("chapter", 0)
            if chapter is not None and snap_ch > chapter:
                continue
            for ev in snap.get("events", []):
                all_events.append(ev)

        # 按章节排序，取最近 10 条
        all_events.sort(key=lambda e: (e.get("chapter", 0), e.get("round", 0)))
        recent_events = all_events[-10:] if all_events else []

        if recent_events:
            parts.append(f"\n### 近期推演事件 (最近 {len(recent_events)} 条)")
            type_map = {
                "character_action": "角色行动",
                "faction_decision": "势力决策",
                "impact_propagation": "影响传播",
                "conflict_detected": "冲突爆发",
            }
            for ev in recent_events:
                ev_ch = ev.get("chapter", 0)
                ev_type = type_map.get(ev.get("type", ""), ev.get("type", ""))
                ev_actor = ev.get("actor", "")
                ev_desc = ev.get("description", "")

                # 提取关键效果
                effects = ev.get("effects", [])
                effect_summary = ""
                if effects:
                    effect_parts = []
                    for eff in effects[:3]:
                        field = eff.get("field", "")
                        delta = eff.get("delta", 0)
                        target = eff.get("target_id", "")
                        sign = "+" if delta >= 0 else ""
                        effect_parts.append(f"{target}.{field}{sign}{delta:.2f}")
                    effect_summary = f" → [{', '.join(effect_parts)}]"

                parts.append(f"- [第{ev_ch}章 {ev_type}] {ev_actor}: {ev_desc}{effect_summary}")

        # ── 写作指导建议 ──
        if factions_state or chars_state:
            parts.append("\n### 写作指导 (基于推演状态)")
            suggestions: list[str] = []

            # 检测高危势力
            critical_factions = [
                fs for fs in factions_state
                if fs.get("stability", 1) < 0.3 or fs.get("threat_level", 0) > 0.7
            ]
            if critical_factions:
                names = [fs.get("name", fs.get("id", "")) for fs in critical_factions]
                suggestions.append(
                    f"⚠️ {', '.join(names)} 处于危机状态，"
                    f"本章可安排相关势力冲突或角色被迫卷入"
                )

            # 检测受伤角色
            injured_chars = [
                cs for cs in chars_state if cs.get("health", 1.0) < 0.3
            ]
            if injured_chars:
                names = [cs.get("name", "") for cs in injured_chars]
                suggestions.append(
                    f"⚠️ {', '.join(names)} 重伤未愈，"
                    f"相关场景应体现伤势影响，不宜安排高强度战斗"
                )

            # 检测情绪异常
            emotional_chars = [
                cs for cs in chars_state
                if cs.get("mood") in ("angry", "fearful")
            ]
            if emotional_chars:
                for cs in emotional_chars:
                    name = cs.get("name", "")
                    mood = cs.get("mood", "")
                    mood_cn = {"angry": "愤怒", "fearful": "恐惧"}.get(mood, mood)
                    suggestions.append(
                        f"💡 {name} 当前情绪「{mood_cn}」，"
                        f"对话和行为应体现该情绪倾向"
                    )

            # 检测近期冲突事件
            recent_conflicts = [
                ev for ev in recent_events
                if ev.get("type") == "conflict_detected"
            ]
            if recent_conflicts:
                suggestions.append(
                    f"📌 近期有 {len(recent_conflicts)} 次势力冲突，"
                    f"本章应处理冲突后果或推动冲突升级"
                )

            if not suggestions:
                suggestions.append("当前世界状态稳定，可安排日常推进或伏笔章节")

            for s in suggestions:
                parts.append(f"- {s}")

        result = "\n".join(parts)
        logger.info(
            "build_world_simulation_context: project=%s, chapter=%s, "
            "factions=%d, chars=%d, events=%d, output=%d chars",
            project_id, target_chapter, len(factions_state),
            len(chars_state), len(recent_events), len(result),
        )
        return result

    @property
    def is_available(self) -> bool:
        """是否有可用的 Part A 分析数据。"""
        return self._loaded and (bool(self.guidance) or bool(self.rhythm_benchmarks))
