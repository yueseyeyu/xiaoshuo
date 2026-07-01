# -*- coding: utf-8 -*-
"""
novel_sag.py — 小说版 SAG: SQL-Retrieval Augmented Generation (P3.1)
=====================================================================
来源: 建议文件 "SAG (SQL-Retrieval Augmented Generation) -> 小说版事件-实体索引"

核心思想:
  传统 RAG 用向量相似度检索, SAG 用 SQL 动态关联"事件-实体"。
  对小说项目而言, novel_index 是"全书级视图", SAG 负责查询时动态构建局部上下文。

核心功能:
  1. 事件-实体索引: 将章节拆分为事件, 实体作为索引关键词
  2. 动态局部上下文: 为 S3 评审只加载当前章节 ±radius 的相关事件, 而非全书
  3. 多跳推理: 通过实体关联进行跨章节查询 (人物弧光、伏笔回收)
  4. 跨章节一致性检查: 检测实体在不同章节中的状态矛盾

与现有模块的关系:
  - novel_index.py: 全书级记忆索引 (章节/伏笔/角色/弧光) — SSOT
  - novel_sag.py: 查询时动态局部构建 — 在 novel_index 之上增加事件-实体关联层
  - context_budget.py: 分层 Context Budget — SAG 的 build_local_context 可作为 Tier 2/3 数据源
  - scene_search.py: 语义检索 (BM25+BGE) — SAG 是结构化检索, 两者互补

设计原则:
  - 零 LLM 依赖: 纯 SQL 查询
  - 增量更新: 新章节只需插入事件-实体, 无需重建
  - 与 novel_index 共享 SQLite: 不新建数据库, 在同一 db 中增加 sag_ 开头的表

用法:
  from xiaoshuo.pipeline.novel_sag import NovelSAG

  sag = NovelSAG()  # 自动连接 novel_index 的 SQLite

  # 添加事件 (从章节分析结果中提取)
  sag.add_event(
      chapter_id=42,
      event_type="plot",
      content="主角与魔王决战, 获胜但身受重伤",
      entities=["主角", "魔王"],
      emotional_valence=0.8,
      importance=9,
  )

  # 为 S3 评审构建局部上下文 (只加载相关事件, 不是全书)
  local_ctx = sag.build_local_context_for_chapter(chapter_id=42, radius=3)
  # → {"current_events": [...], "context_events": [...], "relevant_entities": [...]}

  # 查询人物弧光 (SQL JOIN 动态构建事件链)
  arc = sag.query_character_arc("主角", from_chapter=1, to_chapter=50)

  # 查询伏笔状态 (多跳: hook事件 → 相关事件 → 是否回收)
  status = sag.query_foreshadowing_status("伏笔001")
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from xiaoshuo.infra.logging_config import get_logger

logger = get_logger("novel_sag")


# ============================================================
# 枚举 & 数据结构
# ============================================================

class EventType(Enum):
    """事件类型。"""
    PLOT = "plot"            # 剧情事件 (战斗、对话、决策)
    CHARACTER_ARC = "arc"    # 人物弧光事件 (成长、堕落、觉醒)
    FORESHADOWING = "hook"   # 伏笔事件 (埋钩、回收、废弃)
    EMOTION = "emotion"      # 情绪事件 (高潮、低谷、转折)
    SETTING = "setting"      # 设定事件 (世界观揭示、规则变更)


@dataclass
class SagEvent:
    """SAG 事件: 小说的语义单元。"""
    id: str = ""
    chapter_id: int = 0
    event_type: str = "plot"
    content: str = ""           # 事件摘要 (200字以内)
    entities: list[str] = field(default_factory=list)  # 关联实体名列表
    emotional_valence: float = 0.0  # 情绪值 -1.0 ~ 1.0
    importance: int = 5         # 1-10, 叙事权重
    related_events: list[str] = field(default_factory=list)  # 显式关联事件 ID
    created_at: str = ""


@dataclass
class LocalContext:
    """局部上下文: 为 S3 评审构建的精简上下文。"""
    current_events: list[SagEvent] = field(default_factory=list)
    context_events: list[SagEvent] = field(default_factory=list)
    relevant_entities: list[str] = field(default_factory=list)
    context_radius: int = 3
    total_events_loaded: int = 0

    @property
    def is_empty(self) -> bool:
        return self.total_events_loaded == 0


@dataclass
class ForeshadowStatus:
    """伏笔状态查询结果。"""
    hook_id: str = ""
    planted_at: int = 0
    status: str = "active"      # active / resolved / abandoned / not_found
    resolver_chapter: int | None = None
    chapters_since_planted: int = 0
    candidate_events: list[SagEvent] = field(default_factory=list)


# ============================================================
# NovelSAG 主类
# ============================================================

class NovelSAG:
    """小说版 SAG: 事件-实体索引与动态局部上下文构建。

    在 novel_index 的 SQLite 数据库中增加 sag_ 开头的表,
    不破坏现有表结构, 支持增量更新。
    """

    def __init__(self, db_path: Path | str | None = None):
        """初始化 SAG, 连接到 novel_index 的 SQLite 数据库。

        Args:
            db_path: SQLite 数据库路径。None 则自动定位 novel_index 的 db。
        """
        if db_path is None:
            db_path = self._find_novel_index_db()
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
        logger.debug("NovelSAG 初始化: db=%s", self.db_path)

    @staticmethod
    def _find_novel_index_db() -> Path:
        """自动定位 novel_index 的 SQLite 数据库。"""
        from xiaoshuo.infra.config_manager import get_config
        cfg = get_config()
        data_root = Path(cfg.get("data_root", "data"))
        index_dir = data_root / "processed" / "index"
        index_dir.mkdir(parents=True, exist_ok=True)
        return index_dir / "novel_index.db"

    def _init_schema(self):
        """初始化 SAG 表结构 (sag_ 前缀, 不影响现有表)。"""
        self.conn.executescript("""
            -- SAG 事件表
            CREATE TABLE IF NOT EXISTS sag_events (
                id TEXT PRIMARY KEY,
                chapter_id INTEGER NOT NULL,
                event_type TEXT NOT NULL DEFAULT 'plot',
                content TEXT NOT NULL,
                entities TEXT DEFAULT '[]',       -- JSON array of entity names
                emotional_valence REAL DEFAULT 0.0,
                importance INTEGER DEFAULT 5,
                related_events TEXT DEFAULT '[]',  -- JSON array of event IDs
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_sag_evt_ch ON sag_events(chapter_id);
            CREATE INDEX IF NOT EXISTS idx_sag_evt_type ON sag_events(event_type);
            CREATE INDEX IF NOT EXISTS idx_sag_evt_imp ON sag_events(importance);

            -- SAG 实体表 (去重, 支持别名)
            CREATE TABLE IF NOT EXISTS sag_entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                entity_type TEXT DEFAULT 'character',  -- character / location / organization / item / concept
                aliases TEXT DEFAULT '[]',              -- JSON array
                first_appearance INTEGER DEFAULT 0,
                last_appearance INTEGER DEFAULT 0,
                mention_count INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_sag_ent_name ON sag_entities(name);
            CREATE INDEX IF NOT EXISTS idx_sag_ent_type ON sag_entities(entity_type);

            -- SAG 实体-事件反向索引 (多对多)
            CREATE TABLE IF NOT EXISTS sag_entity_event (
                entity_name TEXT NOT NULL,
                event_id TEXT NOT NULL,
                chapter_id INTEGER NOT NULL,
                role_in_event TEXT DEFAULT 'mentioned',  -- protagonist / antagonist / witness / mentioned
                PRIMARY KEY (entity_name, event_id)
            );
            CREATE INDEX IF NOT EXISTS idx_sag_ee_entity ON sag_entity_event(entity_name);
            CREATE INDEX IF NOT EXISTS idx_sag_ee_event ON sag_entity_event(event_id);
            CREATE INDEX IF NOT EXISTS idx_sag_ee_ch ON sag_entity_event(chapter_id);
        """)
        self.conn.commit()

    # ── 事件管理 ──

    def add_event(
        self,
        chapter_id: int,
        event_type: str | EventType = "plot",
        content: str = "",
        entities: list[str] | None = None,
        emotional_valence: float = 0.0,
        importance: int = 5,
        related_events: list[str] | None = None,
        event_id: str = "",
    ) -> str:
        """添加事件, 自动维护实体-事件索引。

        Args:
            chapter_id: 章节号
            event_type: 事件类型 (plot/arc/hook/emotion/setting)
            content: 事件摘要 (建议 200 字以内)
            entities: 关联实体名列表 (人物名、地点名等)
            emotional_valence: 情绪值 -1.0 ~ 1.0
            importance: 叙事权重 1-10
            related_events: 显式关联事件 ID (如伏笔回收关联埋钩事件)
            event_id: 自定义事件 ID, 空则自动生成

        Returns:
            事件 ID
        """
        entities = entities or []
        related_events = related_events or []

        if isinstance(event_type, EventType):
            event_type = event_type.value

        if not event_id:
            event_id = f"evt-{chapter_id:04d}-{len(self._get_events_for_chapter(chapter_id)) + 1:02d}"

        now = datetime.now().isoformat(timespec="seconds")

        # 插入事件
        self.conn.execute("""
            INSERT OR REPLACE INTO sag_events
            (id, chapter_id, event_type, content, entities,
             emotional_valence, importance, related_events, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event_id, chapter_id, event_type, content,
            json.dumps(entities, ensure_ascii=False),
            emotional_valence, importance,
            json.dumps(related_events, ensure_ascii=False),
            now,
        ))

        # 维护实体表 + 实体-事件索引
        for entity_name in entities:
            # upsert 实体
            self.conn.execute("""
                INSERT INTO sag_entities (name, first_appearance, last_appearance, mention_count)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(name) DO UPDATE SET
                    last_appearance = MAX(last_appearance, ?),
                    mention_count = mention_count + 1
            """, (entity_name, chapter_id, chapter_id, chapter_id))

            # 插入实体-事件索引
            role = self._infer_role(entity_name, content)
            self.conn.execute("""
                INSERT OR REPLACE INTO sag_entity_event
                (entity_name, event_id, chapter_id, role_in_event)
                VALUES (?, ?, ?, ?)
            """, (entity_name, event_id, chapter_id, role))

        self.conn.commit()
        logger.debug("SAG 事件添加: id=%s ch=%d type=%s entities=%s",
                      event_id, chapter_id, event_type, entities)
        return event_id

    def _get_events_for_chapter(self, chapter_id: int) -> list[sqlite3.Row]:
        """获取某章的所有事件 (内部用)。"""
        return self.conn.execute(
            "SELECT * FROM sag_events WHERE chapter_id = ?", (chapter_id,)
        ).fetchall()

    @staticmethod
    def _infer_role(entity_name: str, content: str) -> str:
        """根据实体在事件内容中的位置推断角色 (简化版)。"""
        if not content:
            return "mentioned"
        if content.startswith(entity_name):
            return "protagonist"
        if "对抗" in content or "战斗" in content or " vs " in content:
            if entity_name in content:
                return "antagonist"
        return "mentioned"

    # ── 核心查询: 局部上下文构建 ──

    def build_local_context_for_chapter(
        self,
        chapter_id: int,
        radius: int = 3,
    ) -> LocalContext:
        """为 S3 评审构建局部上下文: 只加载相关事件, 不是全书。

        SAG 的核心查询:
          1. 获取当前章节的所有事件
          2. 提取当前章节涉及的实体
          3. 通过实体-事件索引, 查找这些实体在 ±radius 章内的事件
          4. 返回精简的局部上下文

        Args:
            chapter_id: 当前章节号
            radius: 向前/向后查找多少章 (默认 3)

        Returns:
            LocalContext 包含当前事件 + 上下文事件 + 相关实体
        """
        # 1. 获取当前章节事件
        current_rows = self.conn.execute(
            "SELECT * FROM sag_events WHERE chapter_id = ? ORDER BY importance DESC",
            (chapter_id,)
        ).fetchall()
        current_events = [self._row_to_event(r) for r in current_rows]

        # 2. 提取当前章节的实体
        current_entities: set[str] = set()
        for evt in current_events:
            current_entities.update(evt.entities)

        if not current_entities:
            return LocalContext(
                current_events=current_events,
                relevant_entities=[],
                context_radius=radius,
                total_events_loaded=len(current_events),
            )

        # 3. 动态超边: 通过共享实体查找 ±radius 章内的事件
        placeholders = ",".join("?" * len(current_entities))
        ch_min = chapter_id - radius
        ch_max = chapter_id + radius

        context_rows = self.conn.execute(f"""
            SELECT DISTINCT e.* FROM sag_events e
            JOIN sag_entity_event ee ON e.id = ee.event_id
            WHERE ee.entity_name IN ({placeholders})
            AND e.chapter_id BETWEEN ? AND ?
            AND e.chapter_id != ?
            ORDER BY e.chapter_id, e.importance DESC
        """, (*current_entities, ch_min, ch_max, chapter_id)).fetchall()

        context_events = [self._row_to_event(r) for r in context_rows]

        return LocalContext(
            current_events=current_events,
            context_events=context_events,
            relevant_entities=sorted(current_entities),
            context_radius=radius,
            total_events_loaded=len(current_events) + len(context_events),
        )

    # ── 多跳查询: 人物弧光 ──

    def query_character_arc(
        self,
        character_name: str,
        from_chapter: int = 0,
        to_chapter: int = 999999,
    ) -> list[SagEvent]:
        """查询人物弧光: SQL JOIN 动态构建人物的事件链。

        SAG 多跳推理的基础查询:
          通过实体-事件索引, 一次性获取某角色在指定章节范围内的所有事件。

        Args:
            character_name: 角色名
            from_chapter: 起始章节 (含)
            to_chapter: 结束章节 (含)

        Returns:
            按章节排序的事件列表
        """
        rows = self.conn.execute("""
            SELECT e.* FROM sag_events e
            JOIN sag_entity_event ee ON e.id = ee.event_id
            WHERE ee.entity_name = ?
            AND e.chapter_id BETWEEN ? AND ?
            AND e.event_type IN ('arc', 'plot', 'emotion')
            ORDER BY e.chapter_id, e.importance DESC
        """, (character_name, from_chapter, to_chapter)).fetchall()

        return [self._row_to_event(r) for r in rows]

    # ── 多跳查询: 伏笔状态 ──

    def query_foreshadowing_status(self, hook_event_id: str) -> ForeshadowStatus:
        """查询伏笔状态: 多跳推理。

        SAG 多跳:
          第一跳: 找到伏笔事件
          第二跳: 通过共享实体找到可能回收伏笔的事件
          第三跳: 检查是否有事件显式标记为回收

        Args:
            hook_event_id: 伏笔事件 ID

        Returns:
            ForeshadowStatus 包含状态和候选回收事件
        """
        # 第一跳: 找到伏笔事件
        row = self.conn.execute(
            "SELECT * FROM sag_events WHERE id = ? AND event_type = 'hook'",
            (hook_event_id,)
        ).fetchone()

        if not row:
            return ForeshadowStatus(hook_id=hook_event_id, status="not_found")

        hook_event = self._row_to_event(row)
        planted_ch = hook_event.chapter_id

        # 第二跳: 通过共享实体找到后续相关事件
        if not hook_event.entities:
            return ForeshadowStatus(
                hook_id=hook_event_id,
                planted_at=planted_ch,
                status="active",
                chapters_since_planted=0,
            )

        placeholders = ",".join("?" * len(hook_event.entities))
        candidate_rows = self.conn.execute(f"""
            SELECT DISTINCT e.* FROM sag_events e
            JOIN sag_entity_event ee ON e.id = ee.event_id
            WHERE ee.entity_name IN ({placeholders})
            AND e.chapter_id > ?
            AND e.importance >= 6
            ORDER BY e.chapter_id
        """, (*hook_event.entities, planted_ch)).fetchall()

        candidates = [self._row_to_event(r) for r in candidate_rows]

        # 第三跳: 检查是否有事件显式标记为回收
        for evt in candidates:
            if hook_event_id in evt.related_events:
                return ForeshadowStatus(
                    hook_id=hook_event_id,
                    planted_at=planted_ch,
                    status="resolved",
                    resolver_chapter=evt.chapter_id,
                    chapters_since_planted=evt.chapter_id - planted_ch,
                    candidate_events=candidates[:5],
                )

        # 未回收: 计算距今章节数
        latest_ch = max((e.chapter_id for e in candidates), default=planted_ch)
        return ForeshadowStatus(
            hook_id=hook_event_id,
            planted_at=planted_ch,
            status="active",
            chapters_since_planted=latest_ch - planted_ch,
            candidate_events=candidates[:5],
        )

    # ── 跨章节一致性检查 ──

    def query_cross_chapter_consistency(
        self,
        entity_name: str,
    ) -> list[dict]:
        """跨章节一致性检查: 检测实体在不同章节中的状态矛盾。

        SAG 动态超边的核心应用:
          获取该实体的所有事件, 按章节排序,
          检查生命周期状态转换是否合法。

        Args:
            entity_name: 实体名

        Returns:
            不一致列表, 每项包含 chapter_from, chapter_to, invalid_transition
        """
        events = self.query_character_arc(entity_name)
        if len(events) < 2:
            return []

        inconsistencies: list[dict] = []
        prev_status: str | None = None
        prev_ch: int | None = None

        for evt in events:
            inferred_status = self._infer_lifecycle_from_event(evt.content)

            if prev_status and inferred_status:
                if not self._is_valid_transition(prev_status, inferred_status):
                    inconsistencies.append({
                        "chapter_from": prev_ch,
                        "chapter_to": evt.chapter_id,
                        "entity": entity_name,
                        "invalid_transition": f"{prev_status} -> {inferred_status}",
                        "event_content": evt.content,
                    })

            if inferred_status:
                prev_status = inferred_status
                prev_ch = evt.chapter_id

        return inconsistencies

    @staticmethod
    def _infer_lifecycle_from_event(content: str) -> str | None:
        """从事件内容推断生命周期状态 (简化版, 纯关键词)。"""
        if not content:
            return None
        content_lower = content.lower()
        if any(w in content for w in ("死亡", "牺牲", "阵亡", "陨落")):
            return "dead"
        if any(w in content for w in ("登场", "出现", "回归", "苏醒")):
            return "active"
        if any(w in content for w in ("离开", "沉睡", "封印", "退场")):
            return "dormant"
        return None

    @staticmethod
    def _is_valid_transition(from_status: str, to_status: str) -> bool:
        """检查生命周期状态转换是否合法。"""
        valid = {
            "active": {"dead", "dormant", "active"},
            "dead": {"dead"},  # 已死不能复活 (除非有设定)
            "dormant": {"active", "dead", "dormant"},
            "unintroduced": {"active", "unintroduced"},
        }
        return to_status in valid.get(from_status, {to_status})

    # ── 实体查询 ──

    def list_entities(self, entity_type: str = "") -> list[dict]:
        """列出所有实体 (可按类型过滤)。"""
        if entity_type:
            rows = self.conn.execute(
                "SELECT * FROM sag_entities WHERE entity_type = ? ORDER BY mention_count DESC",
                (entity_type,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM sag_entities ORDER BY mention_count DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_entity_mention_count(self, entity_name: str) -> int:
        """获取实体被提及次数。"""
        row = self.conn.execute(
            "SELECT mention_count FROM sag_entities WHERE name = ?",
            (entity_name,)
        ).fetchone()
        return row["mention_count"] if row else 0

    # ── 统计 ──

    def stats(self) -> dict:
        """返回 SAG 索引统计信息。"""
        event_count = self.conn.execute(
            "SELECT COUNT(*) as c FROM sag_events"
        ).fetchone()["c"]
        entity_count = self.conn.execute(
            "SELECT COUNT(*) as c FROM sag_entities"
        ).fetchone()["c"]
        index_count = self.conn.execute(
            "SELECT COUNT(*) as c FROM sag_entity_event"
        ).fetchone()["c"]
        ch_range = self.conn.execute(
            "SELECT MIN(chapter_id) as min_ch, MAX(chapter_id) as max_ch FROM sag_events"
        ).fetchone()

        type_dist = {}
        for row in self.conn.execute(
            "SELECT event_type, COUNT(*) as c FROM sag_events GROUP BY event_type"
        ).fetchall():
            type_dist[row["event_type"]] = row["c"]

        return {
            "total_events": event_count,
            "total_entities": entity_count,
            "total_index_entries": index_count,
            "chapter_range": f"{ch_range['min_ch']}-{ch_range['max_ch']}" if ch_range["min_ch"] else "empty",
            "event_type_distribution": type_dist,
        }

    # ── 同步: 从 novel_index 导入 ──

    def sync_from_novel_index(self, book_name: str = "") -> int:
        """从 novel_index 的现有数据同步事件到 SAG。

        将 novel_index 中的 timeline_events + character_arc
        转换为 SAG 事件-实体格式。

        Args:
            book_name: 书名 (可选, 用于过滤)

        Returns:
            同步的事件数量
        """
        count = 0

        # 1. 同步 timeline_events
        try:
            rows = self.conn.execute(
                "SELECT * FROM timeline_events"
            ).fetchall()
            for row in rows:
                ch = row["ch_num"]
                evt_type = row["event_type"]
                desc = row["description"] or ""

                if not desc:
                    continue

                # 从描述中提取实体 (简化版: 取已知实体名)
                entities = self._extract_entities_from_text(desc)

                self.add_event(
                    chapter_id=ch,
                    event_type=evt_type if evt_type in EventType._value2member_map_ else "plot",
                    content=desc,
                    entities=entities,
                    importance=7 if "critical" in str(row.get("importance", "")) else 5,
                )
                count += 1
        except sqlite3.OperationalError:
            logger.debug("timeline_events 表不存在, 跳过")

        # 2. 同步 character_arc (作为 arc 类型事件)
        try:
            rows = self.conn.execute(
                "SELECT * FROM character_arc"
            ).fetchall()
            for row in rows:
                ch = row["ch_num"]
                char_name = row["character_name"]
                parts = []
                for field_name in ("emotion_state", "motivation", "conflict", "growth_marker"):
                    val = row[field_name]
                    if val:
                        parts.append(f"{field_name}: {val}")

                if not parts:
                    continue

                self.add_event(
                    chapter_id=ch,
                    event_type="arc",
                    content=f"{char_name} - {'; '.join(parts)}",
                    entities=[char_name],
                    importance=6,
                )
                count += 1
        except sqlite3.OperationalError:
            logger.debug("character_arc 表不存在, 跳过")

        # 3. 同步 foreshadows (作为 hook 类型事件)
        try:
            rows = self.conn.execute(
                "SELECT * FROM foreshadows"
            ).fetchall()
            for row in rows:
                ch = row["planted_ch"]
                name = row["name"]
                desc = row["description"] or name

                entities = self._extract_entities_from_text(desc)
                related = []
                if row["status"] == "resolved" and row["resolved_ch"]:
                    related.append(f"evt-{row['resolved_ch']:04d}-01")

                self.add_event(
                    chapter_id=ch,
                    event_type="hook",
                    content=desc,
                    entities=entities,
                    importance=8 if row["importance"] == "critical" else 5,
                    related_events=related,
                )
                count += 1
        except sqlite3.OperationalError:
            logger.debug("foreshadows 表不存在, 跳过")

        logger.info("SAG 同步完成: 从 novel_index 导入 %d 个事件", count)
        return count

    def _extract_entities_from_text(self, text: str) -> list[str]:
        """从文本中提取已知实体名 (简化版)。

        实际使用时可以接入更复杂的 NER,
        这里先做已知实体匹配。
        """
        if not text:
            return []

        # 获取所有已知实体名
        rows = self.conn.execute(
            "SELECT name, aliases FROM sag_entities"
        ).fetchall()

        found = []
        for row in rows:
            name = row["name"]
            aliases = json.loads(row["aliases"]) if row["aliases"] else []

            if name in text:
                found.append(name)
                continue
            for alias in aliases:
                if alias in text:
                    found.append(name)
                    break

        return found

    # ── Prompt 集成 ──

    def format_local_context_for_prompt(
        self,
        chapter_id: int,
        radius: int = 3,
        max_events: int = 20,
    ) -> str:
        """为 S3 评审生成可注入 Prompt 的局部上下文文本。

        替代全书 novel_index 加载, 只提供相关事件的精简摘要。

        Args:
            chapter_id: 当前章节号
            radius: 上下文半径 (±多少章)
            max_events: 最多返回事件数 (避免 Prompt 膨胀)

        Returns:
            Markdown 格式的上下文文本
        """
        ctx = self.build_local_context_for_chapter(chapter_id, radius)

        if ctx.is_empty:
            return ""

        lines = [f"## SAG 局部上下文 (第{chapter_id}章 ±{radius}章)"]
        lines.append(f"相关实体: {', '.join(ctx.relevant_entities[:10])}")
        lines.append("")

        if ctx.current_events:
            lines.append("### 当前章节事件:")
            for evt in ctx.current_events[:max_events // 2]:
                lines.append(f"- [{evt.event_type}] {evt.content}")
            lines.append("")

        if ctx.context_events:
            lines.append("### 上下文事件 (近期相关):")
            for evt in ctx.context_events[:max_events // 2]:
                lines.append(f"- [ch{evt.chapter_id}] {evt.content}")

        return "\n".join(lines)

    # ── 内部工具 ──

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> SagEvent:
        """将数据库行转换为 SagEvent。"""
        return SagEvent(
            id=row["id"],
            chapter_id=row["chapter_id"],
            event_type=row["event_type"],
            content=row["content"],
            entities=json.loads(row["entities"]) if row["entities"] else [],
            emotional_valence=row["emotional_valence"],
            importance=row["importance"],
            related_events=json.loads(row["related_events"]) if row["related_events"] else [],
            created_at=row["created_at"],
        )

    def close(self):
        """关闭数据库连接。"""
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# ============================================================
# 便捷函数
# ============================================================

_sag_instance: NovelSAG | None = None


def get_sag() -> NovelSAG:
    """获取全局 NovelSAG 单例。"""
    global _sag_instance
    if _sag_instance is None:
        _sag_instance = NovelSAG()
    return _sag_instance


def build_local_context(chapter_id: int, radius: int = 3) -> LocalContext:
    """便捷函数: 构建局部上下文。"""
    return get_sag().build_local_context_for_chapter(chapter_id, radius)


def format_sag_context_for_prompt(chapter_id: int, radius: int = 3) -> str:
    """便捷函数: 生成可注入 Prompt 的 SAG 上下文。"""
    return get_sag().format_local_context_for_prompt(chapter_id, radius)
