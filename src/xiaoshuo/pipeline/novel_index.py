# -*- coding: utf-8 -*-
"""
novel_index — 全书级记忆索引 (v7.7)
=====================================
为 AI 辅助写作提供跨章节上下文检索。解决"AI 记忆不可靠"问题：
  - 写第 N 章时，自动检索前 K 章摘要 + 未回收伏笔 + 角色状态
  - 基于 rhythm CSV 构建，零额外依赖 (Python 内置 sqlite3)

与 memory_store.py 的区别：
  - memory_store: Agent 任务级记忆（Goal/Solution/Result/PainPoint）
  - novel_index:  小说级记忆（章节/事件/伏笔/角色/情感曲线）

设计参考：
  - oh-story-claudecode 的"跨书召回"机制 → 改编为"跨章召回"
  - webnovel-writer 的 RAG+长期记忆 → 改编为 SQLite 结构化索引
"""

import csv
import json
import sqlite3
from pathlib import Path
from typing import Optional

from xiaoshuo.infra.config_manager import get_config


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

            CREATE TABLE IF NOT EXISTS character_states (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ch_num INTEGER NOT NULL,
                character_name TEXT NOT NULL,
                status_summary TEXT,
                power_level TEXT,
                location TEXT,
                updated_at TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_char_ch ON character_states(ch_num);
            CREATE INDEX IF NOT EXISTS idx_char_name ON character_states(character_name);
        """)
        conn.commit()

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
        """获取未回收的伏笔/事件。"""
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
        """更新角色在某章的状态。"""
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO character_states (ch_num, character_name, status_summary, "
            "power_level, location) VALUES (?, ?, ?, ?, ?)",
            (ch_num, name, status_summary, power_level, location)
        )
        conn.commit()

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

        返回 AI 写作辅助所需的全部上下文：
          - 前 k 章摘要
          - 未回收伏笔
          - 情感曲线片段
          - 即时爽/延迟爽分布
        """
        return {
            "current_chapter": ch_num,
            "recent_chapters": self.context_window(ch_num, k),
            "unresolved_foreshadowing": self.unresolved_events("foreshadow"),
            "emotion_curve": self.emotion_curve()[max(0, ch_num - k - 5):ch_num],
            "pleasure_distribution": self.pleasure_distribution(),
            "active_characters": self.active_characters(ch_num, k),
        }

    def summary_report(self) -> str:
        """生成全书摘要报告 (Markdown 格式)。"""
        dist = self.pleasure_distribution()
        peaks = self.conflict_peaks(5)
        hooks = self.hook_streak()

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