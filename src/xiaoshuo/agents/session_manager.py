#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
session_manager.py -- 写作会话上下文管理器
============================================================
-- 文件定位 --
agents/ 核心模块之一。管理一次完整的写作会话:
  当前书/当前章/当前阶段/章节历史/决策记录。
  将 state_machine (阶段流转) + skill_loader (Prompt 构建)
  + model_orchestrator (模型路由) 组合为统一的会话 API。

-- 设计原则 --
- 轻量: 不引入新依赖, 仅 stdlib + pyyaml + 已有 agents 模块
- 有状态: 会话上下文持久化到 state.json, 断点可续
- 可组合: session_manager 的 API 被 novel.py session/write/review 命令调用

-- 对外接口 --
from session_manager import SessionManager
sm = SessionManager()
ctx = sm.chapter_context(5)   # 第5章的完整上下文
sm.advance_stage("S1")       # 推进到 S1
sm.log_decision(chapter=5, question="best_segment", answer="第3段...")

-- 开发者指引 --
- 新增会话字段: 在 _ensure_session_keys() 中添加
- 新增阶段命令: 在 get_available_commands() 中添加映射
"""

import json
from datetime import datetime
from pathlib import Path
from xiaoshuo import PROJECT_ROOT
from typing import Optional


# ============================================================
# 常量
# ============================================================
PROJECT_ROOT = PROJECT_ROOT
STATE_PATH = PROJECT_ROOT / "state.json"
CONFIG_PATH = PROJECT_ROOT / "config.yaml"

# 阶段名称 -> 中文描述 (ASCII 安全)
STAGE_LABELS = {
    "INIT": "初始化",
    "S0": "世界观/大纲",
    "S1": "创意引导",
    "S2a": "手写初稿",
    "S2b": "AI参考(卡文时)",
    "S2c": "对比分析",
    "S2d": "精修",
    "S3": "AI评审",
    "S4": "风格检测",
    "PUBLISH": "发布",
}

# 阶段 -> 可用命令映射
STAGE_COMMANDS = {
    "INIT": ["worldbuild", "outline"],
    "S0": ["worldbuild", "outline", "characters", "next"],
    "S1": ["s1", "next"],
    "S2a": ["write", "next"],
    "S2b": ["next"],
    "S2c": ["next"],
    "S2d": ["write", "next"],
    "S3": ["review", "next", "rewrite"],
    "S4": ["next", "rewrite"],
    "PUBLISH": ["decisions", "next"],
}


# ============================================================
# SessionManager
# ============================================================
class SessionManager:
    """写作会话管理器。管理当前书/章/阶段的上下文。"""

    def __init__(self):
        self._state = self._load_state()
        self._ensure_session_keys()

    # ── 状态 I/O ──

    def _load_state(self) -> dict:
        """加载 state.json。不存在则返回最小骨架。"""
        if STATE_PATH.exists():
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"version": "7.4", "current_stage": "INIT"}

    def _save(self) -> None:
        """原子写入 state.json。"""
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(self._state, f, ensure_ascii=False, indent=2)

    def _ensure_session_keys(self) -> None:
        """确保 session 所需的顶层 key 存在。"""
        defaults = {
            "session": {
                "book": "",
                "genre": "",
                "current_chapter": 1,
                "current_stage": "INIT",
                "chapter_history": {},
                "decisions": [],
                "started_at": "",
            }
        }
        if "session" not in self._state:
            self._state["session"] = defaults["session"]
            self._save()
        else:
            changed = False
            for k, v in defaults["session"].items():
                if k not in self._state["session"]:
                    self._state["session"][k] = v
                    changed = True
            if changed:
                self._save()

    # ── 会话属性 ──

    @property
    def book(self) -> str:
        return self._state["session"].get("book", "")

    @property
    def genre(self) -> str:
        return self._state["session"].get("genre", "")

    @property
    def current_chapter(self) -> int:
        return self._state["session"].get("current_chapter", 1)

    @property
    def current_stage(self) -> str:
        return self._state["session"].get("current_stage", "INIT")

    @property
    def chapter_history(self) -> dict:
        return self._state["session"].get("chapter_history", {})

    # ── 会话操作 ──

    def start(self, book: str = "", genre: str = "") -> None:
        """开始新会话或恢复已有会话。"""
        sess = self._state["session"]
        if book:
            sess["book"] = book
        if genre:
            sess["genre"] = genre
        if not sess.get("started_at"):
            sess["started_at"] = datetime.now().isoformat()
        self._save()

    def set_chapter(self, chapter: int) -> None:
        """切换到指定章节。"""
        self._state["session"]["current_chapter"] = chapter
        # 如果章节没有历史记录, 初始化为 INIT
        history = self._state["session"]["chapter_history"]
        key = str(chapter)
        if key not in history:
            history[key] = {
                "stage": "S1",
                "word_count": 0,
                "created_at": datetime.now().isoformat(),
                "review_count": 0,
            }
        self._state["session"]["current_stage"] = history[key]["stage"]
        self._save()

    def advance_stage(self, new_stage: str) -> bool:
        """推进到下一阶段。返回是否成功。"""
        sess = self._state["session"]
        ch_key = str(sess["current_chapter"])
        history = sess["chapter_history"]

        if ch_key not in history:
            history[ch_key] = {"stage": "INIT", "word_count": 0}

        old_stage = history[ch_key]["stage"]

        # 特殊: "next" 自动推进到下一阶段
        if new_stage == "next":
            order = ["INIT", "S0", "S1", "S2a", "S2c", "S2d", "S3", "S4", "PUBLISH"]
            try:
                idx = order.index(old_stage)
                new_stage = order[idx + 1] if idx + 1 < len(order) else old_stage
            except ValueError:
                new_stage = "S1"

        # 特殊: "rewrite" 回退到 S2d
        if new_stage == "rewrite":
            new_stage = "S2d"

        history[ch_key]["stage"] = new_stage
        sess["current_stage"] = new_stage

        # PUBLISH -> 自动推进到下一章
        if new_stage == "PUBLISH":
            next_ch = sess["current_chapter"] + 1
            sess["current_chapter"] = next_ch
            self.set_chapter(next_ch)

        self._save()
        return True

    # ── 章节上下文 ──

    def chapter_context(self, chapter: Optional[int] = None) -> dict:
        """获取指定章节的完整上下文(文本/大纲/角色/决策)。"""
        ch = chapter or self.current_chapter
        ctx = {
            "chapter": ch,
            "stage": self.current_stage,
            "book": self.book,
            "genre": self.genre,
            "chapter_text": self._load_chapter_text(ch),
            "outline": self._load_outline(),
            "characters": self._load_characters(),
            "world": self._load_world(),
            "decisions": self._load_decisions(ch),
        }
        return ctx

    def _load_chapter_text(self, chapter: int) -> str:
        """加载章节文本。"""
        paths = [
            PROJECT_ROOT / "assets" / "chapters" / f"chapter_{chapter}.md",
            PROJECT_ROOT / "chapters" / f"chapter_{chapter}.md",
        ]
        for p in paths:
            if p.exists():
                return p.read_text(encoding="utf-8")
        return ""

    def _load_outline(self) -> str:
        """加载大纲。"""
        p = PROJECT_ROOT / "assets" / "outline" / "rough_outline.md"
        if p.exists():
            text = p.read_text(encoding="utf-8")
            if "待填写" not in text:
                return text
        return ""

    def _load_characters(self) -> str:
        """加载角色设定。"""
        p = PROJECT_ROOT / "assets" / "canon" / "characters.md"
        if p.exists():
            text = p.read_text(encoding="utf-8")
            if "待填写" not in text:
                return text
        return ""

    def _load_world(self) -> str:
        """加载世界观。"""
        p = PROJECT_ROOT / "assets" / "canon" / "world.md"
        if p.exists():
            text = p.read_text(encoding="utf-8")
            if "待填写" not in text:
                return text
        return ""

    def _load_decisions(self, chapter: int) -> list:
        """加载指定章节的决策记录。"""
        return [
            d for d in self._state["session"].get("decisions", [])
            if d.get("chapter") == chapter
        ]

    # ── 决策记录 (§10 风格涌现的数据源) ──

    def log_decision(self, chapter: int, question: str, answer: str,
                     category: str = "general") -> None:
        """记录一条作者决策。这是未来风格涌现的原始数据。"""
        decisions = self._state["session"].setdefault("decisions", [])
        decisions.append({
            "chapter": chapter,
            "question": question,
            "answer": answer,
            "category": category,
            "timestamp": datetime.now().isoformat(),
        })
        self._save()

    # ── 章节提交 ──

    def submit_chapter(self, chapter: int, text: str) -> Path:
        """保存章节文本并更新历史。返回保存路径。"""
        # 保存到 assets/chapters/ (创作资产)
        chapter_dir = PROJECT_ROOT / "assets" / "chapters"
        chapter_dir.mkdir(parents=True, exist_ok=True)
        path = chapter_dir / f"chapter_{chapter}.md"
        path.write_text(text, encoding="utf-8")

        # 更新历史
        history = self._state["session"]["chapter_history"]
        key = str(chapter)
        if key not in history:
            history[key] = {"stage": "S2a", "created_at": datetime.now().isoformat()}
        word_count = len(text.replace("\n", "").replace(" ", ""))
        history[key]["word_count"] = word_count
        history[key]["updated_at"] = datetime.now().isoformat()
        self._save()

        return path

    # ── 状态展示 ──

    def get_status_lines(self) -> list:
        """返回格式化的状态行, 供 REPL 显示。"""
        sess = self._state["session"]
        ch = sess["current_chapter"]
        stage = sess["current_stage"]
        label = STAGE_LABELS.get(stage, stage)
        history = sess.get("chapter_history", {})
        ch_info = history.get(str(ch), {})
        wc = ch_info.get("word_count", 0)
        rc = ch_info.get("review_count", 0)

        lines = [
            f"  Book:    {sess.get('book', '(not set)')}",
            f"  Genre:   {sess.get('genre', '(not set)')}",
            f"  Chapter: {ch}  ({wc} chars, {rc} reviews)",
            f"  Stage:   [{stage}] {label}",
        ]
        return lines

    def get_available_commands(self) -> list:
        """根据当前阶段返回可用命令列表。"""
        stage = self.current_stage
        return STAGE_COMMANDS.get(stage, ["status", "help", "quit"])
