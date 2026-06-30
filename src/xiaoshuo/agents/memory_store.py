#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
memory_store.py — 结构化"行为回溯备忘录"系统
=================================================
基于视频"Agent记忆做减法"核心理念: 用 SQLite + 精准Tag 替代复杂 RAG/知识图谱。

核心四维模型 (Goal / Solution / Result / Pain Point):
  - goal:      本次任务的具体目标是什么？
  - solution:  最终采用的正确解决方案是什么？
  - result:    任务执行的最终结果如何？
  - pain_point:过程中遇到了什么错误或难点？

v7.5 新增 (hallucination_pattern):
  - hallucination_pattern: LLM 本次出现的幻觉模式 (如"过度解读爽点"/"编造数值"/"遗漏钩子")
    用于系统学习自身的幻觉模式，后续遇到类似情况自动提高警惕。

设计原则:
  1. 零额外依赖 — Python 内置 sqlite3
  2. 轻量 — 单表, 无 ORM, 无向量嵌入
  3. 可审计 — 每条记录有时间戳和版本号
  4. 可导出 — Markdown 格式供 Obsidian/human 阅读
  5. 精准检索 — Tag 精确匹配, 不做语义模糊搜索

用法:
  from xiaoshuo.agents.memory_store import MemoryStore

  store = MemoryStore()
  store.add(
      goal="拆书《诡秘之主》, 提取12类爽点",
      solution="rhythm_analyzer.py v10 Phase 1+2, 爽点识别率87%",
      result="拆书报告1.2MB, S1指导3份",
      pain_point="第800-900章爽点骤降, 规则漏检'信息差爽点'",
      tags=["拆书", "诡秘之主", "爽点漏检", "规则优化"]
  )

  cards = store.query_by_tags(["拆书", "爽点漏检"])
  for c in cards:
      print(c["goal"], c["pain_point"])
"""

import json
import sqlite3
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from xiaoshuo import PROJECT_ROOT


# 默认数据库路径 (相对于项目根)
DEFAULT_DB_DIR = PROJECT_ROOT / "memory"
DEFAULT_DB_PATH = DEFAULT_DB_DIR / "memory.db"


class MemoryStore:
    """结构化行为回溯备忘录存储。

    单例友好: 可在 pipeline 各阶段共享同一实例。
    线程安全: 每个操作独立连接, 不共享连接状态。
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        # 确保父目录存在
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_table()

    # ── 建表 ──

    def _init_table(self):
        """初始化 SQLite 表结构。幂等: IF NOT EXISTS."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_cards (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    goal        TEXT NOT NULL,
                    solution    TEXT DEFAULT '',
                    result      TEXT DEFAULT '',
                    pain_point  TEXT DEFAULT '',
                    tags        TEXT DEFAULT '[]',      -- JSON array: ["tag1","tag2"]
                    date        TEXT NOT NULL,
                    project_version TEXT DEFAULT 'v7.5',
                    source      TEXT DEFAULT '',          -- 触发来源: quality_gate|s4_detection|manual|book_complete
                    hallucination_pattern TEXT DEFAULT '', -- 幻觉模式记录 (v7.5新增)
                    category    TEXT DEFAULT 'general'    -- 记忆分类: fact|episodic|skill|general (v7.8新增)
                )
            """)
            # v7.8 迁移：为已有数据库添加 category 列
            try:
                conn.execute("ALTER TABLE memory_cards ADD COLUMN category TEXT DEFAULT 'general'")
            except sqlite3.OperationalError:
                pass  # 列已存在
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_memory_tags
                ON memory_cards(tags)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_memory_date
                ON memory_cards(date DESC)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_memory_category
                ON memory_cards(category)
            """)
            conn.commit()
        finally:
            conn.close()

    # ── 写入 ──

    def add(self, goal: str, solution: str = "", result: str = "",
            pain_point: str = "", tags: Optional[List[str]] = None,
            source: str = "manual", hallucination_pattern: str = "",
            category: str = "general") -> int:
        """添加一张记忆卡片。

        Args:
            goal: 任务目标
            solution: 采用的解决方案
            result: 执行结果
            pain_point: 遇到的困难/错误
            tags: 标签列表 (3-5 个推荐)
            source: 触发来源标识
            hallucination_pattern: LLM幻觉模式记录 (v7.5新增)
            category: 记忆分类 (v7.8新增): fact|episodic|skill|general

        Returns:
            新卡片 ID
        """
        tags = tags or []
        conn = sqlite3.connect(str(self.db_path))
        try:
            cur = conn.execute("""
                INSERT INTO memory_cards (goal, solution, result, pain_point, tags, date, project_version, source, hallucination_pattern, category)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                goal,
                solution,
                result,
                pain_point,
                json.dumps(tags, ensure_ascii=False),
                datetime.now().isoformat(timespec="seconds"),
                "v7.8",
                source,
                hallucination_pattern,
                category,
            ))
            conn.commit()
            return cur.lastrowid or 0
        finally:
            conn.close()

    def add_from_pipeline(self, goal: str, solution: str = "", result: str = "",
                          pain_point: str = "", tags: Optional[List[str]] = None,
                          s4_verdict: str = "", human_confirmed: bool = False,
                          hallucination_pattern: str = "",
                          category: str = "general") -> int:
        """管线触发写入, 自动分类成功/失败经验。

        规则:
          - S4 SAFE + human_confirmed → tags 自动追加 "成功经验"
          - S4 FATAL → tags 自动追加 "失败案例", "待复盘"
        """
        tags = tags or []
        source = "pipeline"

        if s4_verdict == "SAFE" and human_confirmed:
            if "成功经验" not in tags:
                tags.append("成功经验")
            source = "s4_pass"
        elif s4_verdict == "FATAL":
            if "失败案例" not in tags:
                tags.append("失败案例")
            if "待复盘" not in tags:
                tags.append("待复盘")
            source = "s4_fail"

        return self.add(goal=goal, solution=solution, result=result,
                        pain_point=pain_point, tags=tags, source=source,
                        hallucination_pattern=hallucination_pattern,
                        category=category)

    # ── 检索 ──

    def query_by_tags(self, tags: List[str], match_all: bool = False,
                      limit: int = 20) -> List[dict]:
        """按标签检索记忆卡片。

        Args:
            tags: 目标标签列表
            match_all: True → 必须包含所有标签; False → 包含任一即可
            limit: 最大返回条数

        Returns:
            卡片字典列表, 按日期降序
        """
        if not tags:
            return []

        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            if match_all:
                # 必须全部匹配: 每个tag都要 LIKE
                conditions = " AND ".join(["tags LIKE ?" for _ in tags])
                params = [f'%"{t}"%' for t in tags]
            else:
                # 任一匹配: OR
                conditions = " OR ".join(["tags LIKE ?" for _ in tags])
                params = [f'%"{t}"%' for t in tags]

            rows = conn.execute(
                f"SELECT * FROM memory_cards WHERE ({conditions}) ORDER BY date DESC LIMIT ?",
                [*params, limit]
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def query_by_source(self, source: str, limit: int = 20) -> List[dict]:
        """按来源检索 (pipeline/manual/s4_pass/s4_fail)."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM memory_cards WHERE source = ? ORDER BY date DESC LIMIT ?",
                (source, limit)
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def query_by_category(self, category: str, limit: int = 20) -> List[dict]:
        """按分类检索记忆卡片 (v7.8新增).

        Args:
            category: fact|episodic|skill|general
            limit: 最大返回条数
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM memory_cards WHERE category = ? ORDER BY date DESC LIMIT ?",
                (category, limit)
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def search_text(self, keyword: str, limit: int = 20) -> List[dict]:
        """全文模糊搜索 (goal/solution/result/pain_point)."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            pattern = f"%{keyword}%"
            rows = conn.execute("""
                SELECT * FROM memory_cards
                WHERE goal LIKE ? OR solution LIKE ? OR result LIKE ? OR pain_point LIKE ?
                ORDER BY date DESC LIMIT ?
            """, (pattern, pattern, pattern, pattern, limit)).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def list_recent(self, limit: int = 10) -> List[dict]:
        """最近 N 条卡片."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM memory_cards ORDER BY date DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def get_by_id(self, card_id: int) -> Optional[dict]:
        """按 ID 获取单张卡片."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM memory_cards WHERE id = ?", (card_id,)
            ).fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            conn.close()

    def count(self) -> int:
        """总卡片数."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            return conn.execute("SELECT COUNT(*) FROM memory_cards").fetchone()[0]
        finally:
            conn.close()

    def count_by_source(self, source: str) -> int:
        """按来源统计卡片数."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            return conn.execute(
                "SELECT COUNT(*) FROM memory_cards WHERE source = ?", (source,)
            ).fetchone()[0]
        finally:
            conn.close()

    # ── 导出 ──

    def export_markdown(self, card_id: Optional[int] = None,
                        out_dir: Optional[Path] = None) -> List[Path]:
        """导出记忆卡片为独立 Markdown 文件 (Obsidian 友好格式).

        Args:
            card_id: 指定导出某张; None → 导出全部
            out_dir: 输出目录; None → 默认 memory/memory_export/

        Returns:
            导出的文件路径列表
        """
        out_dir = out_dir or (self.db_path.parent / "memory_export")
        out_dir.mkdir(parents=True, exist_ok=True)

        if card_id:
            card = self.get_by_id(card_id)
            cards = [card] if card else []
        else:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute("SELECT * FROM memory_cards ORDER BY date DESC").fetchall()
                cards = [self._row_to_dict(r) for r in rows]
            finally:
                conn.close()

        exported = []
        for c in cards:
            safe_title = c["goal"][:40].replace("/", "_").replace("\\", "_").strip()
            filename = f"{c['date'][:10]}_{c['id']:04d}_{safe_title}.md"
            filepath = out_dir / filename
            content = self._format_card_markdown(c)
            filepath.write_text(content, encoding="utf-8")
            exported.append(filepath)

        return exported

    # ── 内部工具 ──

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "goal": row["goal"],
            "solution": row["solution"],
            "result": row["result"],
            "pain_point": row["pain_point"],
            "tags": json.loads(row["tags"]) if row["tags"] else [],
            "date": row["date"],
            "version": row["project_version"],
            "source": row["source"],
            "hallucination_pattern": row["hallucination_pattern"] if "hallucination_pattern" in row.keys() else "",
            "category": row["category"] if "category" in row.keys() else "general",
        }

    @staticmethod
    def _format_card_markdown(c: dict) -> str:
        tags_str = " ".join(f"#{t}" for t in c.get("tags", []))
        return f"""---
id: {c['id']}
date: {c['date']}
version: {c.get('version', 'v7.5')}
source: {c.get('source', 'manual')}
tags: {tags_str}
---

# 记忆卡片 #{c['id']}

## 🎯 目标 (Goal)
{c['goal']}

## 💡 方案 (Solution)
{c['solution']}

## 📊 结果 (Result)
{c['result']}

## ⚠️ 痛点 (Pain Point)
{c['pain_point']}

## 🌀 幻觉模式 (Hallucination Pattern)
{c.get('hallucination_pattern', '') or '(未记录)'}

---
*自动生成于 {datetime.now().isoformat(timespec="seconds")}*
"""

    def __repr__(self) -> str:
        return f"<MemoryStore db={self.db_path} cards={self.count()}>"


# ============================================================================
# 自检
# ============================================================================

def self_test():
    """运行模块自检。"""
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test_memory.db"
    store = MemoryStore(db_path)

    # 1. 空库
    assert store.count() == 0, f"[FAIL] 空库 count={store.count()}"
    print("  [OK] 空库初始化")

    # 2. 写入
    cid = store.add(
        goal="测试拆书",
        solution="测试方案",
        result="成功",
        pain_point="无",
        tags=["test", "拆书"],
        source="self_test",
        hallucination_pattern="过度解读爽点",
    )
    assert cid > 0, f"[FAIL] 写入返回 {cid}"
    assert store.count() == 1, f"[FAIL] count={store.count()}"
    print("  [OK] 写入卡片")

    # 3. 按 ID 读取
    card = store.get_by_id(cid)
    assert card is not None
    assert card["goal"] == "测试拆书"
    assert "test" in card["tags"]
    assert card["hallucination_pattern"] == "过度解读爽点"
    print("  [OK] get_by_id")

    # 4. 标签检索
    results = store.query_by_tags(["拆书"])
    assert len(results) == 1
    results = store.query_by_tags(["不存在的标签"])
    assert len(results) == 0
    print("  [OK] query_by_tags")

    # 5. 来源检索
    results = store.query_by_source("self_test")
    assert len(results) == 1
    print("  [OK] query_by_source")

    # 6. 全文搜索
    results = store.search_text("测试")
    assert len(results) >= 1
    results = store.search_text("不存在的内容")
    assert len(results) == 0
    print("  [OK] search_text")

    # 7. 最近列表
    results = store.list_recent(5)
    assert len(results) >= 1
    print("  [OK] list_recent")

    # 8. 管线写入 (成功)
    cid2 = store.add_from_pipeline(
        goal="测试管线通过",
        solution="S4全通过",
        result="发布",
        pain_point="无",
        tags=["test", "pipeline"],
        s4_verdict="SAFE",
        human_confirmed=True,
    )
    card2 = store.get_by_id(cid2)
    assert "成功经验" in card2["tags"]
    assert card2["source"] == "s4_pass"
    print("  [OK] add_from_pipeline (SAFE)")

    # 9. 管线写入 (失败)
    cid3 = store.add_from_pipeline(
        goal="测试管线失败",
        solution="退回重写",
        result="FATAL",
        pain_point="逻辑矛盾",
        tags=["test", "pipeline"],
        s4_verdict="FATAL",
        human_confirmed=False,
    )
    card3 = store.get_by_id(cid3)
    assert "失败案例" in card3["tags"]
    assert "待复盘" in card3["tags"]
    assert card3["source"] == "s4_fail"
    print("  [OK] add_from_pipeline (FATAL)")

    # 10. Markdown 导出
    exported = store.export_markdown(out_dir=Path(tmp) / "export")
    assert len(exported) >= 1
    content = exported[0].read_text(encoding="utf-8")
    assert "##" in content
    print("  [OK] export_markdown")

    # 统计 (清理前)
    total = store.count()
    print(f"  [OK] 总计 {total} 张卡片")

    # 清理
    shutil.rmtree(tmp)

    print(f"  [DONE] memory_store.py 自检完成")


if __name__ == "__main__":
    self_test()