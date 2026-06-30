# -*- coding: utf-8 -*-
"""
novel_index — 全书级记忆索引 (v8.4)
=====================================
为 AI 辅助写作提供跨章节上下文检索。解决"AI 记忆不可靠"问题：
  - 写第 N 章时，自动检索前 K 章摘要 + 未回收伏笔 + 角色状态
  - 基于 rhythm CSV 构建，零额外依赖 (Python 内置 sqlite3)

v8.4 新增 (P0.2):
  - ForeshadowingTracker: 跨章节伏笔追踪 + 记忆衰减检测 + 自动休眠
  - 角色叙事调度字段: narrative_weight / lifecycle_status / last_appearance / appearance_cooldown
  - narrative_schedule_check(): S3 评审用的角色出场调度检查

与 memory_store.py 的区别：
  - memory_store: Agent 任务级记忆（Goal/Solution/Result/PainPoint）
  - novel_index:  小说级记忆（章节/事件/伏笔/角色/情感曲线）

设计参考：
  - oh-story-claudecode 的"跨书召回"机制 → 改编为"跨章召回"
  - webnovel-writer 的 RAG+长期记忆 → 改编为 SQLite 结构化索引
  - "控制台"角色管理 → 改编为叙事调度字段 (narrative scheduling)
"""

import csv
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from xiaoshuo.infra.config_manager import get_config
from xiaoshuo.infra.logging_config import get_logger

logger = get_logger("novel_index")


# ── 索引数据库路径 ──
def _index_dir() -> Path:
    cfg = get_config()
    data_root = Path(cfg.get("data_root", "data"))
    return data_root / "processed" / "index"


# ── 章节摘要模板 ──
CHAPTER_SUMMARY_TEMPLATE = (
    "[第{ch}章] wc={wc} 主导爽点={sub}({timing}) "
    "冲突={conflict}({conflict_level}) 情绪={emotion} 节奏={pace} "
    "爽点密度={pos_density:.1f} 钩子密度={hook_density:.1f}"
)


# ── 叙事调度常量 ──
NARRATIVE_WEIGHTS = ("protagonist", "major", "supporting", "cameo")
LIFECYCLE_STATUSES = ("active", "dead", "dormant", "unintroduced")

# 伏笔衰减阈值
FORESHADOW_WARN_CHAPTERS = 20   # 超过 20 章未回收 → 警告
FORESHADOW_ARCHIVE_CHAPTERS = 50  # 超过 50 章未回收 → 自动休眠

# 人物弧光检测阈值 (P1.2)
ARC_EMOTION_MONOTONY = 3      # 连续 3 章同一情绪 → 警告
ARC_GROWTH_STAGNATION = 10    # 10 章无成长标记 → 警告

# 情绪分类 (用于弧光追踪)
EMOTION_CATEGORIES = {
    "愤怒": ["愤怒", "暴怒", "狂怒", "震怒", "怒火", "激怒"],
    "恐惧": ["恐惧", "惊恐", "骇然", "胆寒", "害怕", "畏惧"],
    "绝望": ["绝望", "崩溃", "歇斯底里", "万念俱灰", "心如死灰"],
    "震惊": ["震惊", "震撼", "不可思议", "难以置信", "吃惊"],
    "悲伤": ["悲伤", "悲痛", "心碎", "哀伤", "凄凉", "悲凉"],
    "兴奋": ["兴奋", "激动", "振奋", "狂喜", "热血沸腾"],
    "平静": ["平静", "淡然", "释然", "坦然", "从容", "波澜不惊"],
    "犹豫": ["犹豫", "迟疑", "纠结", "矛盾", "动摇"],
    "坚定": ["坚定", "决意", "决心", "毅然", "毫不犹豫"],
    "疲惫": ["疲惫", "乏力", "无力", "疲倦", "精疲力竭"],
}

# 动机-行为矛盾检测词表
MOTIVATION_BEHAVIOR_MAP = {
    "复仇": {"expected": ["战斗", "杀", "追查", "调查", "寻找", "追踪"],
             "contradictory": ["恋爱", "约会", "逛街", "赏花", "游玩", "闲聊"]},
    "变强": {"expected": ["修炼", "训练", "突破", "挑战", "战斗", "历练"],
              "contradictory": ["休息", "偷懒", "放弃", "逃避", "享乐"]},
    "保护": {"expected": ["守护", "防御", "挡", "护", "守", "陪伴"],
              "contradictory": ["离开", "抛弃", "独自", "远去"]},
    "探索": {"expected": ["探索", "调查", "寻找", "发现", "冒险", "深入"],
              "contradictory": ["退缩", "返回", "放弃", "安于现状"]},
}


# ============================================================================
# 伏笔追踪器 — 跨章节伏笔状态管理 + 记忆衰减检测
# ============================================================================

@dataclass
class ForeshadowDecayReport:
    """伏笔衰减检测报告。"""
    warnings: list[str] = field(default_factory=list)
    archived: list[str] = field(default_factory=list)
    total_active: int = 0
    total_resolved: int = 0
    total_archived: int = 0

    @property
    def has_issues(self) -> bool:
        return bool(self.warnings or self.archived)


class ForeshadowingTracker:
    """追踪全书伏笔状态，防止 200 万字后遗忘。

    状态流转:
        active (未回收) → resolved (已回收) / abandoned (自动休眠)

    衰减规则 (来自 Webnovel Writer 借鉴):
        - 超过 20 章未回收 → 警告: 读者可能已遗忘, 回收时需前情提要
        - 超过 50 章未回收 → 自动休眠: 建议废弃或强制回收

    用法:
        tracker = ForeshadowingTracker(index)
        tracker.register(ch_num=5, name="神秘信件", description="...")
        report = tracker.check_decay(current_ch=30)
        tracker.auto_archive(current_ch=60)
    """

    def __init__(self, index: "NovelIndex"):
        self.index = index

    def register(self, ch_num: int, name: str,
                 description: str = "",
                 importance: str = "normal") -> int:
        """注册新伏笔。返回事件 ID。

        Args:
            ch_num: 埋设章节号
            name: 伏笔名称 (如 "神秘信件来源")
            description: 伏笔描述
            importance: normal / critical (关键伏笔不自动休眠)
        """
        conn = self.index._get_conn()
        cursor = conn.execute(
            "INSERT INTO foreshadows "
            "(planted_ch, name, description, status, importance) "
            "VALUES (?, ?, ?, 'active', ?)",
            (ch_num, name, description, importance)
        )
        conn.commit()
        logger.info("伏笔注册: '%s' @ch%d (importance=%s)", name, ch_num, importance)
        return cursor.lastrowid

    def resolve(self, foreshadow_id: int, resolved_ch: int):
        """标记伏笔已回收。"""
        conn = self.index._get_conn()
        conn.execute(
            "UPDATE foreshadows SET status='resolved', resolved_ch=? WHERE id=?",
            (resolved_ch, foreshadow_id)
        )
        conn.commit()
        logger.info("伏笔回收: id=%d @ch%d", foreshadow_id, resolved_ch)

    def abandon(self, foreshadow_id: int, reason: str = ""):
        """手动废弃伏笔。"""
        conn = self.index._get_conn()
        conn.execute(
            "UPDATE foreshadows SET status='abandoned', note=? WHERE id=?",
            (reason, foreshadow_id)
        )
        conn.commit()
        logger.info("伏笔废弃: id=%d reason=%s", foreshadow_id, reason)

    def list_active(self) -> list[dict]:
        """获取所有未回收的伏笔。"""
        conn = self.index._get_conn()
        rows = conn.execute(
            "SELECT * FROM foreshadows WHERE status='active' ORDER BY planted_ch"
        ).fetchall()
        return [dict(r) for r in rows]

    def list_resolved(self) -> list[dict]:
        """获取所有已回收的伏笔。"""
        conn = self.index._get_conn()
        rows = conn.execute(
            "SELECT * FROM foreshadows WHERE status='resolved' ORDER BY planted_ch"
        ).fetchall()
        return [dict(r) for r in rows]

    def list_abandoned(self) -> list[dict]:
        """获取所有已废弃的伏笔。"""
        conn = self.index._get_conn()
        rows = conn.execute(
            "SELECT * FROM foreshadows WHERE status='abandoned' ORDER BY planted_ch"
        ).fetchall()
        return [dict(r) for r in rows]

    def check_decay(self, current_ch: int) -> ForeshadowDecayReport:
        """检查伏笔记忆衰减。

        - 超过 20 章未回收 → 警告读者可能已遗忘
        - 超过 50 章未回收 → 建议废弃或强制回收

        Args:
            current_ch: 当前章节号

        Returns:
            ForeshadowDecayReport 包含 warnings 和 archived 列表
        """
        report = ForeshadowDecayReport()
        active = self.list_active()
        report.total_active = len(active)

        for hook in active:
            planted_at = hook["planted_ch"]
            distance = current_ch - planted_at
            name = hook["name"]
            importance = hook.get("importance", "normal")

            # 关键伏笔不自动休眠, 但仍警告
            if distance > FORESHADOW_ARCHIVE_CHAPTERS:
                if importance == "critical":
                    report.warnings.append(
                        f"关键伏笔 '{name}' 已埋 {distance} 章 (ch{planted_at}→ch{current_ch}), "
                        f"超过 {FORESHADOW_ARCHIVE_CHAPTERS} 章阈值, 强烈建议尽快回收"
                    )
                else:
                    report.archived.append(
                        f"伏笔 '{name}' 已埋 {distance} 章 (ch{planted_at}→ch{current_ch}), "
                        f"超过 {FORESHADOW_ARCHIVE_CHAPTERS} 章阈值, 建议废弃或强制回收"
                    )
            elif distance > FORESHADOW_WARN_CHAPTERS:
                report.warnings.append(
                    f"伏笔 '{name}' 已埋 {distance} 章 (ch{planted_at}→ch{current_ch}), "
                    f"回收时需前情提要"
                )

        # 统计
        report.total_resolved = len(self.list_resolved())
        report.total_archived = len(self.list_abandoned())
        return report

    def auto_archive(self, current_ch: int) -> int:
        """自动休眠超过阈值且非关键的伏笔。

        Returns:
            被自动休眠的伏笔数量
        """
        conn = self.index._get_conn()
        threshold_ch = current_ch - FORESHADOW_ARCHIVE_CHAPTERS
        cursor = conn.execute(
            "UPDATE foreshadows SET status='abandoned', "
            "note=? WHERE status='active' AND importance != 'critical' "
            "AND planted_ch < ?",
            (f"自动休眠: 超过{FORESHADOW_ARCHIVE_CHAPTERS}章未回收 (@ch{current_ch})",
             threshold_ch)
        )
        conn.commit()
        archived_count = cursor.rowcount
        if archived_count > 0:
            logger.info("自动休眠 %d 个伏笔 (阈值: %d章)", archived_count, FORESHADOW_ARCHIVE_CHAPTERS)
        return archived_count

    def summary(self) -> dict:
        """伏笔追踪汇总统计。"""
        return {
            "active": len(self.list_active()),
            "resolved": len(self.list_resolved()),
            "abandoned": len(self.list_abandoned()),
        }


# ============================================================================
# 人物弧光追踪器 — 动态追踪角色情绪/动机/成长 (P1.2)
# ============================================================================

@dataclass
class ArcReport:
    """人物弧光检测报告。"""
    character: str = ""
    total_chapters: int = 0           # 该角色出现的总章节数
    emotion_variety: int = 0           # 情绪类型种类数
    growth_count: int = 0              # 成长标记总数
    motivation_changes: int = 0        # 动机变更次数
    warnings: list[str] = field(default_factory=list)
    emotion_timeline: list[dict] = field(default_factory=list)   # 情绪时间线
    growth_timeline: list[dict] = field(default_factory=list)    # 成长时间线
    motivation_timeline: list[dict] = field(default_factory=list) # 动机时间线

    @property
    def has_issues(self) -> bool:
        return bool(self.warnings)


class CharacterArcTracker:
    """动态追踪角色弧光: 情绪/动机/成长标记的跨章变化。

    来源: 建议文件 "深化角色与情感 -> 人物弧光追踪系统"

    跨章检测:
      - 情绪单调: 连续 3 章同一情绪 -> 警告
      - 成长停滞: 10 章无 growth_marker -> 警告
      - 动机-行为矛盾: 说想复仇却一直在谈恋爱 -> 警告

    用法:
        tracker = CharacterArcTracker(index)
        tracker.record(ch_num=5, character="林凡",
                       emotion_state="愤怒", motivation="复仇",
                       growth_marker="觉醒异能")
        report = tracker.check_arc("林凡", current_ch=30)
    """

    def __init__(self, index: "NovelIndex"):
        self.index = index

    def record(self, ch_num: int, character: str,
               emotion_state: str = "",
               motivation: str = "",
               conflict: str = "",
               growth_marker: str = "",
               power_level: str = "",
               notes: str = "") -> int:
        """记录角色在某章的弧光状态。返回记录 ID。

        Args:
            ch_num: 章节号
            character: 角色名
            emotion_state: 情绪状态 (如 "愤怒", "恐惧", "平静")
            motivation: 当前动机 (如 "复仇", "保护", "探索")
            conflict: 当前冲突 (如 "vs 反派", "内心挣扎")
            growth_marker: 成长标记 (如 "克服恐惧", "获得新能力", "")
            power_level: 实力等级 (如 "筑基期", "LV3")
            notes: 附加备注
        """
        conn = self.index._get_conn()
        cursor = conn.execute(
            "INSERT INTO character_arc "
            "(ch_num, character_name, emotion_state, motivation, conflict, "
            " growth_marker, power_level, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ch_num, character, emotion_state, motivation, conflict,
             growth_marker, power_level, notes)
        )
        conn.commit()
        logger.info("弧光记录: '%s' @ch%d emotion=%s motivation=%s growth=%s",
                     character, ch_num, emotion_state, motivation,
                     growth_marker or "(none)")
        return cursor.lastrowid

    def get_arc(self, character: str) -> list[dict]:
        """获取角色完整弧光时间线 (按章节排序)。"""
        conn = self.index._get_conn()
        rows = conn.execute(
            "SELECT * FROM character_arc WHERE character_name = ? ORDER BY ch_num",
            (character,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_latest(self, character: str) -> dict | None:
        """获取角色最新的弧光状态。"""
        conn = self.index._get_conn()
        row = conn.execute(
            "SELECT * FROM character_arc WHERE character_name = ? "
            "ORDER BY ch_num DESC LIMIT 1",
            (character,)
        ).fetchone()
        return dict(row) if row else None

    def list_characters(self) -> list[str]:
        """获取所有有弧光记录的角色名。"""
        conn = self.index._get_conn()
        rows = conn.execute(
            "SELECT DISTINCT character_name FROM character_arc ORDER BY character_name"
        ).fetchall()
        return [r[0] for r in rows]

    def check_arc(self, character: str, current_ch: int = 0) -> ArcReport:
        """检查角色弧光健康度。

        检测项:
          1. 情绪单调: 连续 ARC_EMOTION_MONOTONY 章同一情绪 -> 警告
          2. 成长停滞: ARC_GROWTH_STAGNATION 章无 growth_marker -> 警告
          3. 动机-行为矛盾: 动机与行为不符 -> 警告

        Args:
            character: 角色名
            current_ch: 当前章节号 (0=自动取最新)

        Returns:
            ArcReport 包含警告和时间线数据
        """
        report = ArcReport(character=character)
        arc = self.get_arc(character)
        if not arc:
            report.warnings.append(f"角色 '{character}' 无弧光记录")
            return report

        report.total_chapters = len(arc)
        if current_ch == 0:
            current_ch = arc[-1]["ch_num"]

        # ── 1. 情绪单调检测 ──
        emotions = [e["emotion_state"] for e in arc if e.get("emotion_state")]
        report.emotion_timeline = [
            {"ch": e["ch_num"], "emotion": e["emotion_state"]}
            for e in arc if e.get("emotion_state")
        ]
        unique_emotions = set(emotions)
        report.emotion_variety = len(unique_emotions)

        if emotions:
            streak = 1
            for i in range(1, len(emotions)):
                if emotions[i] == emotions[i - 1]:
                    streak += 1
                    if streak >= ARC_EMOTION_MONOTONY:
                        report.warnings.append(
                            f"情绪单调: '{character}' 连续 {streak} 章为'{emotions[i]}' "
                            f"(ch{arc[i - streak + 1]['ch_num']}-ch{arc[i]['ch_num']}), "
                            f"建议增加情绪变化"
                        )
                else:
                    streak = 1

        # ── 2. 成长停滞检测 ──
        growth_entries = [e for e in arc if e.get("growth_marker")]
        report.growth_timeline = [
            {"ch": e["ch_num"], "marker": e["growth_marker"]}
            for e in growth_entries
        ]
        report.growth_count = len(growth_entries)

        if growth_entries:
            last_growth_ch = growth_entries[-1]["ch_num"]
            chapters_since_growth = current_ch - last_growth_ch
            if chapters_since_growth >= ARC_GROWTH_STAGNATION:
                report.warnings.append(
                    f"成长停滞: '{character}' 已 {chapters_since_growth} 章无成长标记 "
                    f"(最后: ch{last_growth_ch}), 建议安排角色成长事件"
                )
        elif report.total_chapters >= ARC_GROWTH_STAGNATION:
            report.warnings.append(
                f"成长停滞: '{character}' 已有 {report.total_chapters} 章记录但无任何成长标记, "
                f"建议安排角色成长事件"
            )

        # ── 3. 动机-行为矛盾检测 ──
        motivations = [e for e in arc if e.get("motivation")]
        report.motivation_timeline = [
            {"ch": e["ch_num"], "motivation": e["motivation"]}
            for e in motivations
        ]
        # 统计动机变更次数
        if len(motivations) >= 2:
            for i in range(1, len(motivations)):
                if motivations[i]["motivation"] != motivations[i - 1]["motivation"]:
                    report.motivation_changes += 1

        # 检查动机-行为矛盾
        for entry in arc:
            mot = entry.get("motivation", "")
            notes = entry.get("notes", "")
            conflict = entry.get("conflict", "")
            combined_text = notes + conflict

            for motive_key, mappings in MOTIVATION_BEHAVIOR_MAP.items():
                if motive_key in mot:
                    contradictory_hits = [
                        w for w in mappings["contradictory"] if w in combined_text
                    ]
                    if contradictory_hits:
                        report.warnings.append(
                            f"动机-行为矛盾: '{character}' @ch{entry['ch_num']} "
                            f"动机为'{mot}'但行为涉及{contradictory_hits}, "
                            f"建议确保行为与动机一致"
                        )
                    break

        return report

    def check_all(self, current_ch: int = 0) -> list[ArcReport]:
        """检查所有有弧光记录的角色。"""
        characters = self.list_characters()
        return [self.check_arc(c, current_ch) for c in characters]

    def summary(self) -> dict:
        """弧光追踪汇总统计。"""
        characters = self.list_characters()
        total_records = 0
        total_growth = 0
        total_warnings = 0
        for c in characters:
            arc = self.get_arc(c)
            total_records += len(arc)
            total_growth += sum(1 for e in arc if e.get("growth_marker"))
            report = self.check_arc(c)
            total_warnings += len(report.warnings)
        return {
            "characters_tracked": len(characters),
            "total_records": total_records,
            "total_growth_markers": total_growth,
            "total_warnings": total_warnings,
        }

    def visualize_data(self, character: str) -> dict:
        """生成角色弧光可视化数据 (供前端图表使用)。

        Returns:
            dict 包含:
              - emotion_curve: 情绪曲线数据点
              - growth_markers: 成长标记位置
              - motivation_changes: 动机变更点
              - chapter_range: 章节范围
        """
        arc = self.get_arc(character)
        if not arc:
            return {"error": f"角色 '{character}' 无弧光记录"}

        return {
            "character": character,
            "chapter_range": [arc[0]["ch_num"], arc[-1]["ch_num"]],
            "total_chapters": len(arc),
            "emotion_curve": [
                {"x": e["ch_num"], "y": self._emotion_to_score(e.get("emotion_state", "")),
                 "label": e.get("emotion_state", "")}
                for e in arc
            ],
            "growth_markers": [
                {"ch": e["ch_num"], "label": e["growth_marker"]}
                for e in arc if e.get("growth_marker")
            ],
            "motivation_changes": [
                {"ch": e["ch_num"], "motivation": e["motivation"]}
                for e in arc if e.get("motivation")
            ],
            "power_progression": [
                {"ch": e["ch_num"], "level": e.get("power_level", "")}
                for e in arc if e.get("power_level")
            ],
        }

    @staticmethod
    def _emotion_to_score(emotion: str) -> int:
        """将情绪文本映射为数值分数 (1-10) 用于可视化。

        低分=消极, 高分=积极
        """
        for category, score in [
            (["绝望", "崩溃", "万念俱灰", "心如死灰"], 1),
            (["恐惧", "惊恐", "骇然", "胆寒", "害怕"], 2),
            (["悲伤", "悲痛", "心碎", "哀伤", "凄凉"], 3),
            (["疲惫", "乏力", "无力", "疲倦"], 4),
            (["犹豫", "迟疑", "纠结", "矛盾", "动摇"], 5),
            (["平静", "淡然", "释然", "坦然", "从容"], 6),
            (["震惊", "震撼", "不可思议", "难以置信"], 7),
            (["愤怒", "暴怒", "狂怒", "震怒", "怒火"], 7),
            (["坚定", "决意", "决心", "毅然"], 8),
            (["兴奋", "激动", "振奋", "狂喜"], 9),
            (["热血沸腾"], 10),
        ]:
            if any(kw in emotion for kw in category):
                return score
        return 5  # 未知情绪 -> 中性


class NovelIndex:
    """全书级记忆索引。

    从 rhythm CSV 构建 SQLite 索引，支持：
      - context_window(n, k) → 写作第 n 章时检索前 k 章上下文
      - unresolved_hooks()    → 未回收伏笔列表
      - emotion_curve()       → 全书情感曲线
      - pleasure_timeline()   → 即时爽/延迟爽分布
      - search_chapters(q)    → 关键词搜索章节
    """

    def __init__(self, genre: str, book_name: str):
        self.genre = genre
        self.book_name = book_name
        self.db_path = _index_dir() / genre / f"{book_name}.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None

    # ── 连接管理 ──

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── 建表 ──

    def _create_tables(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS chapters (
                ch_num INTEGER PRIMARY KEY,
                ch_hash TEXT,
                wc INTEGER,
                para_count INTEGER,
                avg_para_len REAL,
                dialogue_ratio REAL,
                excl_density REAL,
                pos_density REAL,
                neg_density REAL,
                conflict_density REAL,
                hook_density REAL,
                dominant_sub TEXT,
                pleasure_type TEXT,
                pleasure_intensity TEXT,
                pleasure_level TEXT,
                pleasure_timing TEXT,
                hook_type TEXT,
                readability REAL,
                avg_sentence_len REAL,
                vocab_diversity REAL,
                conflict TEXT,
                conflict_level TEXT,
                emotion TEXT,
                pace TEXT,
                ch_variability REAL,
                anti_trope TEXT,
                anti_trope_count INTEGER,
                emotion_valence TEXT,
                emotion_burnout TEXT,
                high_emotion_count INTEGER,
                burnout_count INTEGER,
                -- 爽点细分计数
                slap_count INTEGER DEFAULT 0,
                level_count INTEGER DEFAULT 0,
                crush_count INTEGER DEFAULT 0,
                comeback_count INTEGER DEFAULT 0,
                hidden_count INTEGER DEFAULT 0,
                bond_count INTEGER DEFAULT 0,
                cognitive_count INTEGER DEFAULT 0,
                sacrifice_count INTEGER DEFAULT 0,
                strategy_count INTEGER DEFAULT 0,
                resource_count INTEGER DEFAULT 0,
                social_count INTEGER DEFAULT 0,
                backfire_count INTEGER DEFAULT 0,
                trap_master_count INTEGER DEFAULT 0,
                knowledge_gap_count INTEGER DEFAULT 0,
                hidden_value_count INTEGER DEFAULT 0,
                identity_reveal_count INTEGER DEFAULT 0,
                foreshadow_payoff_count INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS timeline_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ch_num INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                description TEXT,
                resolved_ch INTEGER,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_events_ch ON timeline_events(ch_num);
            CREATE INDEX IF NOT EXISTS idx_events_type ON timeline_events(event_type);

            -- v8.4: 伏笔追踪表 (ForeshadowingTracker)
            CREATE TABLE IF NOT EXISTS foreshadows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                planted_ch INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                status TEXT DEFAULT 'active',   -- active / resolved / abandoned
                importance TEXT DEFAULT 'normal', -- normal / critical
                resolved_ch INTEGER,
                note TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_foreshadow_status ON foreshadows(status);
            CREATE INDEX IF NOT EXISTS idx_foreshadow_planted ON foreshadows(planted_ch);

            -- v8.4: 角色叙事调度表 (替换旧 character_states, 兼容迁移)
            CREATE TABLE IF NOT EXISTS character_states (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ch_num INTEGER NOT NULL,
                character_name TEXT NOT NULL,
                status_summary TEXT,
                power_level TEXT,
                location TEXT,
                updated_at TEXT DEFAULT (datetime('now')),
                -- v8.4 叙事调度字段 (从"控制台"借鉴)
                narrative_weight TEXT DEFAULT 'supporting',
                    -- protagonist / major / supporting / cameo
                lifecycle_status TEXT DEFAULT 'active',
                    -- active / dead / dormant / unintroduced
                last_appearance INTEGER DEFAULT 0,
                    -- 最后出场章节号
                appearance_cooldown INTEGER DEFAULT 0,
                    -- 建议冷却章节数 (配角建议间隔 ≥3 章)
                relationships TEXT DEFAULT '{}'
                    -- JSON: 关联角色 {"name": "relation_type"}
            );
            CREATE INDEX IF NOT EXISTS idx_char_ch ON character_states(ch_num);
            CREATE INDEX IF NOT EXISTS idx_char_name ON character_states(character_name);
            CREATE INDEX IF NOT EXISTS idx_char_weight ON character_states(narrative_weight);
            CREATE INDEX IF NOT EXISTS idx_char_lifecycle ON character_states(lifecycle_status);

            -- v8.5: 人物弧光追踪表 (CharacterArcTracker, P1.2)
            CREATE TABLE IF NOT EXISTS character_arc (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ch_num INTEGER NOT NULL,
                character_name TEXT NOT NULL,
                emotion_state TEXT DEFAULT '',
                motivation TEXT DEFAULT '',
                conflict TEXT DEFAULT '',
                growth_marker TEXT DEFAULT '',
                power_level TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_arc_ch ON character_arc(ch_num);
            CREATE INDEX IF NOT EXISTS idx_arc_name ON character_arc(character_name);
        """)

        # ── v8.4 迁移: 为旧库添加新列 (ALTER TABLE 幂等) ──
        self._migrate_add_columns(conn)

        conn.commit()

    def _migrate_add_columns(self, conn: sqlite3.Connection):
        """为旧版数据库幂等添加 v8.4 新列。"""
        # 检查 character_states 是否缺少新列
        cols = {row[1] for row in conn.execute("PRAGMA table_info(character_states)")}
        new_cols = {
            "narrative_weight": "TEXT DEFAULT 'supporting'",
            "lifecycle_status": "TEXT DEFAULT 'active'",
            "last_appearance": "INTEGER DEFAULT 0",
            "appearance_cooldown": "INTEGER DEFAULT 0",
            "relationships": "TEXT DEFAULT '{}'",
        }
        for col_name, col_def in new_cols.items():
            if col_name not in cols:
                conn.execute(f"ALTER TABLE character_states ADD COLUMN {col_name} {col_def}")
                logger.info("迁移: character_states 添加列 %s", col_name)

        # 检查 foreshadows 表是否存在
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        if "foreshadows" not in tables:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS foreshadows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    planted_ch INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    status TEXT DEFAULT 'active',
                    importance TEXT DEFAULT 'normal',
                    resolved_ch INTEGER,
                    note TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_foreshadow_status ON foreshadows(status);
                CREATE INDEX IF NOT EXISTS idx_foreshadow_planted ON foreshadows(planted_ch);
            """)
            logger.info("迁移: 创建 foreshadows 表")

        # 为 character_states 添加索引 (幂等)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_char_weight ON character_states(narrative_weight)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_char_lifecycle ON character_states(lifecycle_status)"
        )

    @property
    def foreshadow_tracker(self) -> ForeshadowingTracker:
        """获取伏笔追踪器实例 (惰性创建)。"""
        if not hasattr(self, '_foreshadow_tracker'):
            self._foreshadow_tracker = ForeshadowingTracker(self)
        return self._foreshadow_tracker

    @property
    def arc_tracker(self) -> CharacterArcTracker:
        """获取人物弧光追踪器实例 (惰性创建, P1.2)。"""
        if not hasattr(self, '_arc_tracker'):
            self._arc_tracker = CharacterArcTracker(self)
        return self._arc_tracker

    # ── 伏笔管理 (v8.4) ──

    def register_foreshadow(self, ch_num: int, name: str,
                            description: str = "",
                            importance: str = "normal") -> int:
        """注册新伏笔到追踪器。返回伏笔 ID。"""
        return self.foreshadow_tracker.register(ch_num, name, description, importance)

    def resolve_foreshadow(self, foreshadow_id: int, resolved_ch: int):
        """标记伏笔已回收。"""
        self.foreshadow_tracker.resolve(foreshadow_id, resolved_ch)

    def check_foreshadow_decay(self, current_ch: int) -> ForeshadowDecayReport:
        """检查伏笔记忆衰减。"""
        return self.foreshadow_tracker.check_decay(current_ch)

    def auto_archive_foreshadows(self, current_ch: int) -> int:
        """自动休眠超期伏笔。返回休眠数量。"""
        return self.foreshadow_tracker.auto_archive(current_ch)

    def list_foreshadows(self, status: str = "active") -> list[dict]:
        """获取指定状态的伏笔列表。"""
        if status == "active":
            return self.foreshadow_tracker.list_active()
        elif status == "resolved":
            return self.foreshadow_tracker.list_resolved()
        elif status == "abandoned":
            return self.foreshadow_tracker.list_abandoned()
        else:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM foreshadows ORDER BY planted_ch"
            ).fetchall()
            return [dict(r) for r in rows]

    # ── 人物弧光管理 (v8.5, P1.2) ──

    def record_character_arc(self, ch_num: int, character: str,
                             emotion_state: str = "",
                             motivation: str = "",
                             conflict: str = "",
                             growth_marker: str = "",
                             power_level: str = "",
                             notes: str = "") -> int:
        """记录角色弧光状态 (便捷入口)。返回记录 ID。"""
        return self.arc_tracker.record(
            ch_num, character, emotion_state, motivation, conflict,
            growth_marker, power_level, notes
        )

    def check_character_arc(self, character: str,
                            current_ch: int = 0) -> ArcReport:
        """检查角色弧光健康度 (便捷入口)。"""
        return self.arc_tracker.check_arc(character, current_ch)

    def check_all_arcs(self, current_ch: int = 0) -> list[ArcReport]:
        """检查所有角色的弧光 (便捷入口)。"""
        return self.arc_tracker.check_all(current_ch)

    def character_arc_visualize(self, character: str) -> dict:
        """获取角色弧光可视化数据 (便捷入口)。"""
        return self.arc_tracker.visualize_data(character)

    # ── 角色叙事调度管理 (v8.4) ──

    def set_character_narrative(self, name: str,
                                narrative_weight: str = "supporting",
                                lifecycle_status: str = "active",
                                appearance_cooldown: int = 0,
                                relationships: dict | None = None,
                                ch_num: int = 0):
        """设置角色的叙事调度属性。

        Args:
            name: 角色名
            narrative_weight: protagonist / major / supporting / cameo
            lifecycle_status: active / dead / dormant / unintroduced
            appearance_cooldown: 建议冷却章节数
            relationships: 关联角色 {"name": "relation_type"}
            ch_num: 当前章节号 (用于 last_appearance)
        """
        if narrative_weight not in NARRATIVE_WEIGHTS:
            raise ValueError(f"narrative_weight 必须是 {NARRATIVE_WEIGHTS} 之一")
        if lifecycle_status not in LIFECYCLE_STATUSES:
            raise ValueError(f"lifecycle_status 必须是 {LIFECYCLE_STATUSES} 之一")

        conn = self._get_conn()
        rel_json = json.dumps(relationships or {}, ensure_ascii=False)

        existing = conn.execute(
            "SELECT id FROM character_states WHERE character_name = ? "
            "ORDER BY ch_num DESC LIMIT 1",
            (name,)
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE character_states SET narrative_weight=?, lifecycle_status=?, "
                "appearance_cooldown=?, relationships=?, last_appearance=?, "
                "updated_at=datetime('now') WHERE id=?",
                (narrative_weight, lifecycle_status, appearance_cooldown,
                 rel_json, ch_num, existing["id"])
            )
        else:
            conn.execute(
                "INSERT INTO character_states "
                "(ch_num, character_name, narrative_weight, lifecycle_status, "
                " appearance_cooldown, relationships, last_appearance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ch_num, name, narrative_weight, lifecycle_status,
                 appearance_cooldown, rel_json, ch_num)
            )
        conn.commit()
        logger.info("角色调度设置: '%s' weight=%s lifecycle=%s cooldown=%d",
                     name, narrative_weight, lifecycle_status, appearance_cooldown)

    def update_character_lifecycle(self, name: str, lifecycle_status: str,
                                   ch_num: int = 0, note: str = ""):
        """更新角色生命周期状态 (如角色死亡/休眠/重新登场)。"""
        if lifecycle_status not in LIFECYCLE_STATUSES:
            raise ValueError(f"lifecycle_status 必须是 {LIFECYCLE_STATUSES} 之一")

        conn = self._get_conn()
        existing = conn.execute(
            "SELECT id FROM character_states WHERE character_name = ? "
            "ORDER BY ch_num DESC LIMIT 1",
            (name,)
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE character_states SET lifecycle_status=?, last_appearance=?, "
                "status_summary=COALESCE(NULLIF(?, ''), status_summary), "
                "updated_at=datetime('now') WHERE id=?",
                (lifecycle_status, ch_num, note, existing["id"])
            )
        else:
            conn.execute(
                "INSERT INTO character_states "
                "(ch_num, character_name, lifecycle_status, last_appearance, status_summary) "
                "VALUES (?, ?, ?, ?, ?)",
                (ch_num, name, lifecycle_status, ch_num, note)
            )
        conn.commit()
        logger.info("角色生命周期更新: '%s' → %s @ch%d", name, lifecycle_status, ch_num)

    def record_character_appearance(self, name: str, ch_num: int,
                                    status_summary: str = "",
                                    power_level: str = "",
                                    location: str = ""):
        """记录角色出场 (更新 last_appearance + 插入状态快照)。"""
        conn = self._get_conn()
        existing = conn.execute(
            "SELECT id, narrative_weight, lifecycle_status, appearance_cooldown, relationships "
            "FROM character_states WHERE character_name = ? ORDER BY ch_num DESC LIMIT 1",
            (name,)
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE character_states SET last_appearance=?, "
                "updated_at=datetime('now') WHERE id=?",
                (ch_num, existing["id"])
            )
            conn.execute(
                "INSERT INTO character_states "
                "(ch_num, character_name, status_summary, power_level, location, "
                " narrative_weight, lifecycle_status, appearance_cooldown, "
                " relationships, last_appearance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ch_num, name, status_summary, power_level, location,
                 existing["narrative_weight"], existing["lifecycle_status"],
                 existing["appearance_cooldown"], existing["relationships"], ch_num)
            )
        else:
            conn.execute(
                "INSERT INTO character_states "
                "(ch_num, character_name, status_summary, power_level, location, "
                " last_appearance) VALUES (?, ?, ?, ?, ?, ?)",
                (ch_num, name, status_summary, power_level, location, ch_num)
            )
        conn.commit()

    def get_character_schedule(self, ch_num: int = 0) -> list[dict]:
        """获取所有角色的叙事调度信息 (每个角色取最新记录)。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT cs.* FROM character_states cs "
            "INNER JOIN ("
            "  SELECT character_name, MAX(id) as max_id FROM character_states "
            "  GROUP BY character_name"
            ") latest ON cs.id = latest.max_id "
            "ORDER BY CASE cs.narrative_weight "
            "  WHEN 'protagonist' THEN 0 "
            "  WHEN 'major' THEN 1 "
            "  WHEN 'supporting' THEN 2 "
            "  WHEN 'cameo' THEN 3 END, cs.character_name"
        ).fetchall()

        result = []
        for r in rows:
            d = dict(r)
            d["chapters_since_appearance"] = (
                ch_num - d.get("last_appearance", 0) if ch_num else 0
            )
            d["cooldown_remaining"] = max(
                0, d.get("appearance_cooldown", 0) - d["chapters_since_appearance"]
            )
            try:
                d["relationships"] = json.loads(d.get("relationships", "{}"))
            except (json.JSONDecodeError, TypeError):
                d["relationships"] = {}
            result.append(d)
        return result

    def narrative_schedule_check(self, ch_num: int) -> list[dict]:
        """检查角色出场调度规则 (S3 评审用)。

        检查规则:
          1. 主角不应连续消失超过 3 章
          2. 主要角色冷却期检查
          3. 配角冷却期检查
          4. 死亡角色不应有新出场
          5. 未登场角色不应被引用
          6. 休眠角色重新登场需有唤醒事件
        """
        issues = []
        schedule = self.get_character_schedule(ch_num)

        for char in schedule:
            name = char["character_name"]
            weight = char.get("narrative_weight", "supporting")
            lifecycle = char.get("lifecycle_status", "active")
            since = char.get("chapters_since_appearance", 0)
            cooldown = char.get("appearance_cooldown", 0)
            last_app = char.get("last_appearance", 0)

            if weight == "protagonist" and since > 3 and ch_num > 0:
                issues.append({
                    "rule": "protagonist_absence",
                    "character": name,
                    "severity": "warning",
                    "message": f"主角 '{name}' 已 {since} 章未出场 "
                               f"(最后: ch{last_app}), 不应连续消失超过 3 章"
                })

            if weight == "major" and cooldown > 0 and since < cooldown:
                issues.append({
                    "rule": "major_cooldown",
                    "character": name,
                    "severity": "info",
                    "message": f"主要角色 '{name}' 冷却期未满: 建议 {cooldown} 章间隔, "
                               f"当前仅 {since} 章"
                })

            if weight == "supporting" and cooldown > 0 and since < cooldown:
                issues.append({
                    "rule": "supporting_cooldown",
                    "character": name,
                    "severity": "info",
                    "message": f"配角 '{name}' 冷却期未满: 建议 {cooldown} 章间隔, "
                               f"当前仅 {since} 章"
                })

            if lifecycle == "dead" and last_app > 0 and since <= 1:
                issues.append({
                    "rule": "dead_character_appearance",
                    "character": name,
                    "severity": "fail",
                    "message": f"死亡角色 '{name}' 在 ch{last_app} 有出场记录"
                })

            if lifecycle == "unintroduced" and last_app > 0:
                issues.append({
                    "rule": "unintroduced_referenced",
                    "character": name,
                    "severity": "warning",
                    "message": f"未登场角色 '{name}' 有出场记录 (ch{last_app})"
                })

            if lifecycle == "dormant" and since <= 1 and last_app > 0:
                issues.append({
                    "rule": "dormant_reappearance",
                    "character": name,
                    "severity": "warning",
                    "message": f"休眠角色 '{name}' 重新登场 (ch{last_app}), 需确认有唤醒事件"
                })

        return issues

    # ── 从 CSV 构建索引 ──

    def build_from_csv(self, csv_path: Path) -> int:
        """从 rhythm CSV 构建 SQLite 索引。返回索引章节数。"""
        self._create_tables()
        conn = self._get_conn()

        # 清空旧数据
        conn.execute("DELETE FROM chapters")
        conn.commit()

        count = 0
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ch_num = int(row.get("ch_num", 0))
                if ch_num == 0:
                    continue

                conn.execute("""
                    INSERT OR REPLACE INTO chapters (
                        ch_num, ch_hash, wc, para_count, avg_para_len,
                        dialogue_ratio, excl_density, pos_density, neg_density,
                        conflict_density, hook_density,
                        dominant_sub, pleasure_type, pleasure_intensity,
                        pleasure_level, pleasure_timing,
                        hook_type, readability, avg_sentence_len, vocab_diversity,
                        conflict, conflict_level, emotion, pace,
                        ch_variability, anti_trope, anti_trope_count,
                        emotion_valence, emotion_burnout,
                        high_emotion_count, burnout_count,
                        slap_count, level_count, crush_count, comeback_count,
                        hidden_count, bond_count, cognitive_count, sacrifice_count,
                        strategy_count, resource_count, social_count,
                        backfire_count, trap_master_count, knowledge_gap_count,
                        hidden_value_count, identity_reveal_count, foreshadow_payoff_count
                    ) VALUES (?,?,?,?,?, ?,?,?,?,?, ?,?,?,?,?, ?,?,?,?,?, ?,?,?,?, ?,?,?,?,?, ?,?, ?,?,?,?,?, ?,?,?,?,?, ?,?,?,?,?, ?,?)
                """, (
                    ch_num,
                    row.get("ch_hash", ""),
                    int(row.get("wc", 0)),
                    int(row.get("para_count", 0)),
                    float(row.get("avg_para_len", 0)),
                    float(row.get("dialogue_ratio", 0)),
                    float(row.get("excl_density", 0)),
                    float(row.get("pos_density", 0)),
                    float(row.get("neg_density", 0)),
                    float(row.get("conflict_density", 0)),
                    float(row.get("hook_density", 0)),
                    row.get("dominant_sub", ""),
                    row.get("pleasure_type", ""),
                    row.get("pleasure_intensity", ""),
                    row.get("pleasure_level", ""),
                    row.get("pleasure_timing", ""),
                    row.get("hook_type", ""),
                    float(row.get("readability", 0)),
                    float(row.get("avg_sentence_len", 0)),
                    float(row.get("vocab_diversity", 0)),
                    row.get("conflict", ""),
                    row.get("conflict_level", ""),
                    row.get("emotion", ""),
                    row.get("pace", ""),
                    float(row.get("ch_variability", 0)),
                    row.get("anti_trope", ""),
                    int(row.get("anti_trope_count", 0)),
                    row.get("emotion_valence", ""),
                    row.get("emotion_burnout", ""),
                    int(row.get("high_emotion_count", 0)),
                    int(row.get("burnout_count", 0)),
                    int(row.get("slap_count", 0)),
                    int(row.get("level_count", 0)),
                    int(row.get("crush_count", 0)),
                    int(row.get("comeback_count", 0)),
                    int(row.get("hidden_count", 0)),
                    int(row.get("bond_count", 0)),
                    int(row.get("cognitive_count", 0)),
                    int(row.get("sacrifice_count", 0)),
                    int(row.get("strategy_count", 0)),
                    int(row.get("resource_count", 0)),
                    int(row.get("social_count", 0)),
                    int(row.get("backfire_count", 0)),
                    int(row.get("trap_master_count", 0)),
                    int(row.get("knowledge_gap_count", 0)),
                    int(row.get("hidden_value_count", 0)),
                    int(row.get("identity_reveal_count", 0)),
                    int(row.get("foreshadow_payoff_count", 0)),
                ))
                count += 1

        conn.commit()
        return count

    # ── 查询接口 ──

    def context_window(self, ch_num: int, k: int = 5) -> list[dict]:
        """获取第 ch_num 章前 k 章的上下文摘要。

        用于 AI 写作辅助：写第 N 章时注入前 K 章摘要到 prompt。
        """
        conn = self._get_conn()
        start = max(1, ch_num - k)
        rows = conn.execute(
            "SELECT * FROM chapters WHERE ch_num >= ? AND ch_num < ? ORDER BY ch_num",
            (start, ch_num)
        ).fetchall()

        result = []
        for r in rows:
            d = dict(r)
            d["summary"] = CHAPTER_SUMMARY_TEMPLATE.format(
                ch=d["ch_num"], wc=d["wc"],
                sub=d["dominant_sub"], timing=d["pleasure_timing"],
                conflict=d["conflict"], conflict_level=d["conflict_level"],
                emotion=d["emotion"], pace=d["pace"],
                pos_density=d["pos_density"], hook_density=d["hook_density"],
            )
            result.append(d)
        return result

    def get_chapter(self, ch_num: int) -> Optional[dict]:
        """获取单章完整数据。"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM chapters WHERE ch_num = ?", (ch_num,)
        ).fetchone()
        return dict(row) if row else None

    def emotion_curve(self) -> list[dict]:
        """获取全书情感曲线 (ch_num, emotion, emotion_valence, emotion_burnout)。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT ch_num, emotion, emotion_valence, emotion_burnout, "
            "pos_density, neg_density, conflict_density "
            "FROM chapters ORDER BY ch_num"
        ).fetchall()
        return [dict(r) for r in rows]

    def pleasure_timeline(self) -> list[dict]:
        """获取全书爽点时序分布 (即时爽 vs 延迟爽)。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT ch_num, dominant_sub, pleasure_timing, pleasure_intensity, "
            "pos_density, hook_density FROM chapters ORDER BY ch_num"
        ).fetchall()
        return [dict(r) for r in rows]

    def pleasure_distribution(self) -> dict:
        """汇总全书爽点类型分布。"""
        conn = self._get_conn()
        row = conn.execute("""
            SELECT
                COUNT(*) as total_chapters,
                SUM(CASE WHEN pleasure_timing = 'instant' THEN 1 ELSE 0 END) as instant_count,
                SUM(CASE WHEN pleasure_timing = 'delayed' THEN 1 ELSE 0 END) as delayed_count,
                ROUND(AVG(pos_density), 2) as avg_pos_density,
                ROUND(AVG(hook_density), 2) as avg_hook_density
            FROM chapters
        """).fetchone()
        d = dict(row)
        total = d["total_chapters"] or 1
        d["instant_count"] = d["instant_count"] or 0
        d["delayed_count"] = d["delayed_count"] or 0
        d["avg_pos_density"] = d["avg_pos_density"] or 0
        d["avg_hook_density"] = d["avg_hook_density"] or 0
        d["instant_pct"] = round(d["instant_count"] / total * 100, 1)
        d["delayed_pct"] = round(d["delayed_count"] / total * 100, 1)
        return d

    def hook_streak(self, max_zero: int = 3) -> list[dict]:
        """检测连续零钩子章节 (读者流失高风险区)。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT ch_num, hook_density, hook_type, dominant_sub "
            "FROM chapters WHERE hook_density = 0 ORDER BY ch_num"
        ).fetchall()
        return [dict(r) for r in rows]

    def conflict_peaks(self, top_n: int = 10) -> list[dict]:
        """获取冲突密度最高的 N 章。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT ch_num, conflict_density, conflict, conflict_level, "
            "dominant_sub, emotion "
            "FROM chapters ORDER BY conflict_density DESC LIMIT ?",
            (top_n,)
        ).fetchall()
        return [dict(r) for r in rows]

    def search_chapters(self, keyword: str) -> list[dict]:
        """在章节数据中搜索关键词 (匹配 dominant_sub / conflict / emotion / pace)。"""
        conn = self._get_conn()
        pattern = f"%{keyword}%"
        rows = conn.execute(
            "SELECT ch_num, dominant_sub, conflict, conflict_level, emotion, pace, "
            "pleasure_timing, pos_density, hook_density "
            "FROM chapters WHERE "
            "dominant_sub LIKE ? OR conflict LIKE ? OR emotion LIKE ? OR pace LIKE ? "
            "ORDER BY ch_num",
            (pattern, pattern, pattern, pattern)
        ).fetchall()
        return [dict(r) for r in rows]

    # ── 伏笔/事件管理 ──

    def add_event(self, ch_num: int, event_type: str,
                  description: str = "", resolved_ch: Optional[int] = None):
        """添加时间线事件 (伏笔/转折/高潮等)。"""
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO timeline_events (ch_num, event_type, description, resolved_ch) "
            "VALUES (?, ?, ?, ?)",
            (ch_num, event_type, description, resolved_ch)
        )
        conn.commit()

    def unresolved_events(self, event_type: str = "foreshadow") -> list[dict]:
        """获取未回收的伏笔/事件。

        v8.4: 对于 foreshadow 类型, 优先返回 foreshadows 表中的活跃伏笔。
        """
        if event_type == "foreshadow":
            return self.foreshadow_tracker.list_active()

        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM timeline_events "
            "WHERE event_type = ? AND resolved_ch IS NULL "
            "ORDER BY ch_num",
            (event_type,)
        ).fetchall()
        return [dict(r) for r in rows]

    def resolve_event(self, event_id: int, resolved_ch: int):
        """标记事件/伏笔已回收。"""
        conn = self._get_conn()
        conn.execute(
            "UPDATE timeline_events SET resolved_ch = ? WHERE id = ?",
            (resolved_ch, event_id)
        )
        conn.commit()

    # ── 角色状态管理 ──

    def update_character(self, ch_num: int, name: str,
                         status_summary: str = "",
                         power_level: str = "",
                         location: str = ""):
        """更新角色在某章的状态 (v8.4: 内部调用 record_character_appearance)。"""
        self.record_character_appearance(name, ch_num, status_summary, power_level, location)

    def character_timeline(self, name: str) -> list[dict]:
        """获取角色出场时间线。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM character_states WHERE character_name = ? ORDER BY ch_num",
            (name,)
        ).fetchall()
        return [dict(r) for r in rows]

    def active_characters(self, ch_num: int, window: int = 10) -> list[dict]:
        """获取最近 N 章活跃的角色列表。"""
        conn = self._get_conn()
        start = max(1, ch_num - window)
        rows = conn.execute(
            "SELECT DISTINCT character_name, "
            "MAX(ch_num) as last_seen, "
            "GROUP_CONCAT(status_summary, ' | ') as statuses "
            "FROM character_states "
            "WHERE ch_num >= ? AND ch_num <= ? "
            "GROUP BY character_name "
            "ORDER BY last_seen DESC",
            (start, ch_num)
        ).fetchall()
        return [dict(r) for r in rows]

    # ── 综合报告 ──

    def writing_context(self, ch_num: int, k: int = 5) -> dict:
        """为写作第 ch_num 章提供综合上下文。

        v8.4 增强: 返回伏笔衰减报告 + 角色调度信息 + 调度问题。
        """
        decay_report = self.check_foreshadow_decay(ch_num)
        schedule_issues = self.narrative_schedule_check(ch_num)

        return {
            "current_chapter": ch_num,
            "recent_chapters": self.context_window(ch_num, k),
            "unresolved_foreshadowing": self.foreshadow_tracker.list_active(),
            "foreshadow_decay": {
                "warnings": decay_report.warnings,
                "archived": decay_report.archived,
                "summary": self.foreshadow_tracker.summary(),
            },
            "emotion_curve": self.emotion_curve()[max(0, ch_num - k - 5):ch_num],
            "pleasure_distribution": self.pleasure_distribution(),
            "active_characters": self.active_characters(ch_num, k),
            "character_schedule": self.get_character_schedule(ch_num),
            "narrative_schedule_issues": schedule_issues,
            # v8.5: 人物弧光追踪 (P1.2)
            "character_arc_warnings": [
                w for arc in self.check_all_arcs(ch_num) for w in arc.warnings
            ],
            "character_arc_summary": self.arc_tracker.summary(),
        }

    def summary_report(self) -> str:
        """生成全书摘要报告 (Markdown 格式, v8.4 含伏笔追踪)。"""
        dist = self.pleasure_distribution()
        peaks = self.conflict_peaks(5)
        hooks = self.hook_streak()
        fs_summary = self.foreshadow_tracker.summary()

        lines = [
            f"# {self.book_name} 全书索引报告",
            "",
            "## 基础统计",
            f"- 总章节数: {dist['total_chapters']}",
            f"- 平均爽点密度: {dist['avg_pos_density']}",
            f"- 平均钩子密度: {dist['avg_hook_density']}",
            "",
            "## 爽点时序分布",
            f"- 即时爽: {dist['instant_count']} 章 ({dist['instant_pct']}%)",
            f"- 延迟爽: {dist['delayed_count']} 章 ({dist['delayed_pct']}%)",
            "",
            "## 伏笔追踪",
            f"- 活跃伏笔: {fs_summary['active']}",
            f"- 已回收伏笔: {fs_summary['resolved']}",
            f"- 已废弃伏笔: {fs_summary['abandoned']}",
            "",
            "## 冲突高峰 Top 5",
            "| 章节 | 冲突密度 | 冲突类型 | 冲突等级 | 主导爽点 | 情绪 |",
            "|------|----------|----------|----------|----------|------|",
        ]
        for p in peaks:
            lines.append(
                f"| {p['ch_num']} | {p['conflict_density']:.2f} "
                f"| {p['conflict']} | {p['conflict_level']} "
                f"| {p['dominant_sub']} | {p['emotion']} |"
            )

        if hooks:
            lines.append("")
            lines.append("## 零钩子章节 (读者流失风险)")
            lines.append(f"共 {len(hooks)} 章钩子密度为 0")
            lines.append("| 章节 | 主导爽点 | 钩子类型 |")
            lines.append("|------|----------|----------|")
            for h in hooks[:10]:
                lines.append(
                    f"| {h['ch_num']} | {h['dominant_sub']} | {h['hook_type']} |"
                )

        return "\n".join(lines)


# ── 便捷函数 ──

def build_index(genre: str, book_name: str) -> NovelIndex:
    """从 rhythm CSV 构建索引 (便捷入口)。"""
    from xiaoshuo.pipeline.rhythm_analyzer import _rhythm_dir
    csv_path = _rhythm_dir(genre) / f"rhythm_{book_name}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"Rhythm CSV not found: {csv_path}")

    idx = NovelIndex(genre, book_name)
    n = idx.build_from_csv(csv_path)
    print(f"[OK] NovelIndex built: {n} chapters -> {idx.db_path}")
    return idx


def get_index(genre: str, book_name: str) -> NovelIndex:
    """获取已有索引 (不重建)。"""
    idx = NovelIndex(genre, book_name)
    if not idx.db_path.exists():
        raise FileNotFoundError(
            f"Index not found: {idx.db_path}. Run build_index() first."
        )
    return idx