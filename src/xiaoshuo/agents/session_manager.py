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
    "S2c": ["compare", "next"],
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

    def get_chapter_path(self, chapter: int) -> Optional[Path]:
        """获取章节文件路径 (用于 S4 检测等)。"""
        path = PROJECT_ROOT / "assets" / "chapters" / f"chapter_{chapter}.md"
        if path.exists():
            return path
        return None

    # ── v8.2: 合同链集成 (Part C → D 一致性保障) ──

    def check_contract_before_write(self, chapter: int) -> dict:
        """写前检查: 运行时合同 — 哪些设定生效 + 债务提醒。

        Returns:
            {"active_seeds": int, "pending_debts": list, "warnings": list}
        """
        try:
            from xiaoshuo.pipeline.contract_chain import ContractSeed, DebtBoard
            seed = ContractSeed()
            if not seed.loaded:
                return {"active_seeds": 0, "pending_debts": [], "warnings": ["合同种子未加载"]}
            active = seed.relevant_seeds(chapter)
            debts = DebtBoard(self.book or "default")
            debts._load()
            pending = debts.get_pending(chapter)
            overdue = debts.overdue_debts(chapter)
            warnings = []
            if overdue:
                warnings.append(f"过期债务: {len(overdue)} 条")
            if pending:
                warnings.append(f"待兑现债务: {len(pending)} 条")
            return {
                "active_seeds": len(active),
                "pending_debts": [{"desc": d.get("summary", "")} for d in pending[:5]],
                "warnings": warnings,
            }
        except Exception as e:
            return {"active_seeds": 0, "pending_debts": [], "warnings": [f"合同链不可用: {e}"]}

    def commit_chapter_to_contract(self, chapter: int, text: str) -> dict:
        """写后提交: 章节事实沉淀 + 新债务注册。

        v8.3: 使用 comparison_engine._rich_scan 生成 rhythm_row,
        使 ChapterCommit 能正确提取钩子/冲突/爽点等事实。

        Returns:
            {"committed_facts": int, "new_debts": int, "audit_issues": list}
        """
        try:
            from xiaoshuo.pipeline.contract_chain import ChapterCommit, DebtBoard

            # v8.3: 从章节文本生成 rhythm_row (钩子/冲突/爽点指标)
            rhythm_row = {}
            try:
                from xiaoshuo.pipeline.comparison_engine import rich_scan
                metrics = rich_scan(text)
                rhythm_row = {
                    "wc": metrics.get("chars", 0),
                    "hook_density": metrics.get("hook_density", 0),
                    "hook_type": "strong" if metrics.get("hook_density", 0) > 1.0
                                 else ("weak" if metrics.get("hook_density", 0) > 0.3 else "none"),
                    "conflict_density": metrics.get("conflict_density", 0),
                    "pleasure_intensity": metrics.get("pleasure_intensity", 0),
                    "dialogue_ratio": metrics.get("dialogue_ratio", 0),
                    "readability": metrics.get("readability", 0),
                    "emotion": "日常",  # 默认值, 后续可由 LLM 标注
                }
            except ImportError:
                pass  # comparison_engine 不可用则 rhythm_row 为空

            book_name = self.book or "default"
            commit = ChapterCommit(book_name, chapter, text, rhythm_row)
            audit_result = commit.audit()

            # v8.3: 将新债务注册到债务看板
            debts = DebtBoard(book_name)
            for debt in audit_result.get("new_debts", []):
                debts.add_debt(
                    chapter,
                    debt.get("type", "general"),
                    debt.get("summary", ""),
                    debt.get("severity", "MED"),
                )

            return {
                "committed_facts": len(audit_result.get("new_facts", [])),
                "new_debts": len(audit_result.get("new_debts", [])),
                "audit_issues": [],  # 审计正常无 issue
            }
        except Exception as e:
            return {"committed_facts": 0, "new_debts": 0, "audit_issues": [f"提交失败: {e}"]}

    # ── v8.2: S4 风格检测快捷方法 ──

    def detect_style(self, chapter: int) -> dict:
        """对指定章节执行 S4+++ 风格检测。

        Returns:
            {"verdict": "PASS"|"WARNING"|"FATAL", "flags": int, "summary": str}
        """
        try:
            from xiaoshuo.agents.style_detector import StyleDetector
            path = self.get_chapter_path(chapter)
            if not path:
                return {"verdict": "SKIP", "flags": 0, "summary": "章节文件不存在"}
            text = path.read_text(encoding="utf-8")
            detector = StyleDetector()
            result = detector.detect(text, chapter_num=chapter)
            return {
                "verdict": result.verdict,
                "flags": result.flags,
                "summary": result.summary,
            }
        except Exception as e:
            return {"verdict": "ERROR", "flags": 0, "summary": f"检测失败: {e}"}

    # ── v8.5: P1/P2 模块集成 ──

    def check_golden3(self) -> dict:
        """P1.1: 黄金三章五维分析。

        自动加载前 3 章文本并执行 G1-G5 检测。
        仅在章节 >= 3 时有意义。

        Returns:
            {"dimensions": dict, "summary": str, "grade": str, "issues": list}
        """
        try:
            from xiaoshuo.pipeline.golden3_analyzer import analyze_golden3
            chapters = []
            for ch in range(1, 4):
                text = self._load_chapter_text(ch)
                if text:
                    chapters.append(text)
            if len(chapters) < 1:
                return {"dimensions": {}, "summary": "无章节文本", "grade": "N/A", "issues": []}
            report = analyze_golden3(chapters)
            dims = {}
            for d in report.dimensions:
                dims[d.dimension] = {
                    "score": d.score,
                    "grade": d.grade,
                    "issues": d.issues,
                }
            return {
                "dimensions": dims,
                "summary": report.summary,
                "grade": report.grade,
                "issues": [i for d in report.dimensions for i in d.issues],
            }
        except Exception as e:
            return {"dimensions": {}, "summary": f"分析失败: {e}", "grade": "ERROR", "issues": []}

    def check_red_lines(self, chapter: int) -> dict:
        """P2.1: 红线原则检测。

        对指定章节执行红线原则检测, 返回违反项列表。

        Returns:
            {"passed": bool, "violations": list, "summary": str}
        """
        try:
            from xiaoshuo.pipeline.red_line_principles import check_red_lines
            path = self.get_chapter_path(chapter)
            if not path:
                return {"passed": True, "violations": [], "summary": "章节文件不存在, 跳过"}
            text = path.read_text(encoding="utf-8")
            result = check_red_lines(text, chapter)
            return {
                "passed": result.passed,
                "violations": [
                    {"category": v.category, "rule": v.rule, "severity": v.severity,
                     "detail": v.detail}
                    for v in result.violations
                ],
                "summary": result.summary,
            }
        except Exception as e:
            return {"passed": True, "violations": [], "summary": f"检测失败: {e}"}

    def check_outline_deviation(self, chapter: int, blueprint: dict | None = None) -> dict:
        """P2.4: 大纲偏差检测。

        将章节内容与章节计划 (blueprint) 对比, 检测多维偏差。

        Args:
            chapter: 章节号
            blueprint: 章节计划 dict (events/characters/conflict 等)
                      如为 None 则尝试从 outline 加载

        Returns:
            {"score": float, "grade": str, "items": list, "summary": str}
        """
        try:
            from xiaoshuo.pipeline.outline_deviation import check_outline_deviation
            path = self.get_chapter_path(chapter)
            if not path:
                return {"score": 0, "grade": "N/A", "items": [], "summary": "章节文件不存在"}
            text = path.read_text(encoding="utf-8")
            if blueprint is None:
                blueprint = self._load_chapter_plan(chapter)
            if not blueprint:
                return {"score": 0, "grade": "SKIP", "items": [],
                        "summary": "无章节计划, 跳过偏差检测"}
            result = check_outline_deviation(text, blueprint, chapter)
            # 根据 coverage_score 计算等级
            score = result.coverage_score
            if score >= 80:
                grade = "PASS"
            elif score >= 60:
                grade = "WARNING"
            else:
                grade = "FATAL"
            return {
                "score": score,
                "grade": grade,
                "items": [
                    {"dimension": i.dimension, "status": "matched" if i.matched else "deviation",
                     "detail": i.description, "severity": i.severity}
                    for i in result.items
                ],
                "summary": result.summary,
            }
        except Exception as e:
            return {"score": 0, "grade": "ERROR", "items": [], "summary": f"检测失败: {e}"}

    def check_style_consistency(self, chapter: int) -> dict:
        """P2.2: 风格一致性检测 (基于 Style DNA 基线)。

        提取当前章节的 Style DNA, 与历史基线对比, 检测偏离。

        Returns:
            {"verdict": str, "issues": list, "summary": str}
        """
        try:
            from xiaoshuo.pipeline.style_dna import extract_dna, build_dna_baseline, compare_dna
            from xiaoshuo.pipeline.s3_extensions.style_consistency_lens import check_style_consistency
            path = self.get_chapter_path(chapter)
            if not path:
                return {"verdict": "SKIP", "issues": [], "summary": "章节文件不存在"}
            text = path.read_text(encoding="utf-8")

            # 尝试加载基线
            baseline = self._load_style_dna_baseline()
            if baseline is None:
                # 基线不存在, 仅提取 DNA 不比较
                return {"verdict": "SKIP", "issues": [],
                        "summary": "风格基线尚未建立 (需 ≥ 5 章样本)"}

            result = check_style_consistency(text, baseline)
            # 根据 grade 计算 verdict
            if result.has_serious:
                verdict = "FATAL"
            elif result.has_issues:
                verdict = "WARNING"
            else:
                verdict = "PASS"
            return {
                "verdict": verdict,
                "issues": [
                    {"dimension": i.dimension, "deviation": i.deviation,
                     "severity": i.severity, "detail": i.description}
                    for i in result.issues
                ],
                "summary": result.summary,
            }
        except Exception as e:
            return {"verdict": "ERROR", "issues": [], "summary": f"检测失败: {e}"}

    def check_knowledge_brain(self, chapter_type: str = "",
                               context: dict | None = None) -> dict:
        """P1.4: 写前知识库查表。

        根据章节类型和上下文, 检索相关经验提醒。

        Returns:
            {"has_warnings": bool, "experiences": list, "prompt_text": str}
        """
        try:
            from xiaoshuo.pipeline.knowledge_brain import check_before_write
            result = check_before_write(chapter_type, context or {})
            return {
                "has_warnings": result.has_warnings,
                "experiences": [
                    {"symptom": e.symptom, "root_cause": e.root_cause,
                     "solution": e.solution, "severity": e.severity,
                     "hit_count": e.hit_count}
                    for e in result.matched
                ],
                "prompt_text": "\n".join(result.warnings) if result.warnings else "",
            }
        except Exception as e:
            return {"has_warnings": False, "experiences": [],
                    "prompt_text": ""}

    def get_red_line_reminder(self) -> str:
        """P2.1: 获取红线原则提醒文本 (注入写前 Prompt)。

        Returns:
            红线原则提醒文本, 如无则返回空字符串
        """
        try:
            from xiaoshuo.pipeline.red_line_principles import get_red_line_checker
            checker = get_red_line_checker()
            return checker.format_for_prompt()
        except Exception:
            return ""

    def get_knowledge_brain_prompt(self) -> str:
        """P1.4: 获取知识库经验提醒文本 (注入写前 Prompt)。

        Returns:
            经验提醒文本, 如无则返回空字符串
        """
        try:
            from xiaoshuo.pipeline.knowledge_brain import get_knowledge_brain
            kb = get_knowledge_brain()
            return kb.format_for_prompt()
        except Exception:
            return ""

    def _load_style_dna_baseline(self):
        """加载风格 DNA 基线 (从历史章节构建)。

        尝试从已保存的基线文件加载, 如不存在则返回 None。
        """
        try:
            import json
            baseline_path = PROJECT_ROOT / "data" / "style_dna_baseline.json"
            if baseline_path.exists():
                from xiaoshuo.pipeline.style_dna import StyleDNA
                data = json.loads(baseline_path.read_text(encoding="utf-8"))
                return StyleDNA.from_dict(data)
        except Exception:
            pass
        return None

    def _load_chapter_plan(self, chapter: int) -> dict:
        """从 outline/chapter_plans/ 加载章节计划。

        Returns:
            章节计划 dict, 如不存在返回空 dict
        """
        try:
            import json
            plan_path = PROJECT_ROOT / "assets" / "outline" / "chapter_plans" / f"chapter_{chapter}.json"
            if plan_path.exists():
                return json.loads(plan_path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

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
