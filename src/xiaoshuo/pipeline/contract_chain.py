#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
contract_chain.py — 合同链模块: 合同种子→运行时合同→章节提交→事件审计
=========================================================================
灵感: webnovel-writer Story System (lingfengQAQ, v5.4.2)
适配: 本地 Qwen + 质量门禁 + 七真相文件

四阶段流程:
  1. 合同种子 (ContractSeed): 从 assets/canon/ 加载世界规则, 不可变
  2. 运行时合同 (RuntimeContract): 每章写前 — 哪些设定生效 + 债务提醒
  3. 章节提交 (ChapterCommit): 每章写后 — 本章建立了什么事实
  4. 事件审计 (EventAudit): 跨章追踪 — 未兑现债务 + 一致性违规
"""

import csv
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from xiaoshuo import PROJECT_ROOT
# PROJECT_ROOT imported from src.xiaoshuo
CANON_DIR = PROJECT_ROOT / "assets" / "canon"
CONTRACTS_DIR = PROJECT_ROOT / "data" / "contracts"


# ============================================================================
# 1. 合同种子 — 从 canon/ 加载不可变世界规则
# ============================================================================

class ContractSeed:
    """Immutable world rules loaded from canon/ markdown files.
    Each seed is a single fact: character trait, world rule, power constraint.
    Seeds can be tagged with chapters where they're relevant."""

    def __init__(self, book_name=""):
        self.book_name = book_name
        self.seeds = []          # list of dicts: {source, fact, tags, chapter_range}
        self.canon_files = {}    # filename → raw content
        self.loaded = False
        self._load_canon()

    def _load_canon(self):
        """Load all canon/ markdown files as seeds."""
        if not CANON_DIR.exists():
            self.loaded = False
            return
        for md in sorted(CANON_DIR.glob("*.md")):
            content = md.read_text(encoding="utf-8", errors="replace")
            self.canon_files[md.stem] = content
            if "待填写" in content[:100] and len(content) < 50:
                continue  # placeholder, skip
            self._extract_seeds(md.stem, content)
        self.loaded = len(self.seeds) > 0

    def _extract_seeds(self, source, content):
        """Extract structured facts from markdown. Simple line-by-line heuristic.
        Expected format: one fact per bullet (- or *) or numbered (1.) line.
        Each fact is tagged with its source file."""
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            # Bullet points and numbered lists
            if stripped.startswith(("- ", "* ", "+ ")):
                fact = stripped[2:].strip()
            elif len(stripped) > 2 and stripped[0].isdigit() and stripped[1] in (".", ")"):
                fact = stripped[2:].strip()
            elif stripped.startswith("#"):
                continue  # skip headers
            else:
                continue  # skip prose/empty
            if not fact or len(fact) < 5:
                continue
            self.seeds.append({
                "source": source,
                "fact": fact,
                "tags": [],
                "chapter_range": None,  # (start, end) or None = global
            })

    def relevant_seeds(self, chapter_num, tags=None):
        """Return seeds that apply to this chapter.
        A seed applies if chapter_num falls in its range or it's global (None)."""
        relevant = []
        for s in self.seeds:
            cr = s["chapter_range"]
            if cr is None:
                relevant.append(s)
            elif cr[0] <= chapter_num <= cr[1]:
                relevant.append(s)
            elif tags and any(t in s["tags"] for t in tags):
                relevant.append(s)
        return relevant

    def summary(self):
        """Human-readable summary of seed coverage."""
        by_source = defaultdict(int)
        for s in self.seeds:
            by_source[s["source"]] += 1
        parts = []
        for src in sorted(by_source):
            parts.append(f"{src}({by_source[src]})")
        if not parts:
            return "合同种子: [空] — 请填入 assets/canon/*.md"
        return f"合同种子: {', '.join(parts)} ({len(self.seeds)} 条)"


# ============================================================================
# 2. 运行时合同 — 每章写前激活
# ============================================================================

class RuntimeContract:
    """Per-chapter contract: which seeds are active, what debts are pending.
    Generated before the author writes a chapter.
    Output format: markdown + JSON both."""

    def __init__(self, book_name, chapter_num, seed_bank, debt_board):
        self.book_name = book_name
        self.chapter_num = chapter_num
        self.seed_bank = seed_bank
        self.debt_board = debt_board
        self.active_seeds = []
        self.pending_debts = []
        self.contract = {}

    def build(self, chapter_tags=None):
        """Assemble the runtime contract for this chapter."""
        self.active_seeds = self.seed_bank.relevant_seeds(
            self.chapter_num, chapter_tags)
        self.pending_debts = self.debt_board.get_pending(self.chapter_num)

        self.contract = {
            "book": self.book_name,
            "chapter": self.chapter_num,
            "timestamp": datetime.now().isoformat(),
            "active_rules": len(self.active_seeds),
            "pending_debts": len(self.pending_debts),
            "top_debts": [d["summary"] for d in self.pending_debts[:5]],
            "seeds_loaded": self.seed_bank.loaded,
        }
        return self.contract

    def to_markdown(self):
        """Generate pre-write checklist as markdown."""
        lines = [f"## 第{self.chapter_num}章 运行时合同",
                 f"生成: {datetime.now().strftime('%H:%M')}",
                 ""]
        if not self.seed_bank.loaded:
            lines.append("> [WARN] 合同种子未加载 — assets/canon/ 为空或待填写")
            lines.append("> 建议: 填入至少 characters.md 和 rules.md 后再生成合同")
            lines.append("")
            return lines

        lines.append(f"### 生效设定 ({len(self.active_seeds)} 条)")
        if not self.active_seeds:
            lines.append("  (无章节特定设定, 所有全局设定生效)")
        for s in self.active_seeds[:10]:
            lines.append(f"  - [{s['source']}] {s['fact']}")
        if len(self.active_seeds) > 10:
            lines.append(f"  ... 另有 {len(self.active_seeds) - 10} 条")
        lines.append("")

        lines.append(f"### 待兑现债务 ({len(self.pending_debts)} 条)")
        if not self.pending_debts:
            lines.append("  [OK] 无待兑现债务")
        for d in self.pending_debts[:8]:
            lines.append(f"  - [ch{d['origin_ch']}] {d['summary']} (严重度: {d['severity']})")
        lines.append("")
        return lines


# ============================================================================
# 3. 章节提交 — 写后事实沉淀
# ============================================================================

class ChapterCommit:
    """Post-write: what was established in this chapter.
    Extracts new facts, character appearances, rule applications.
    Input: chapter text + rhythm analysis results."""

    def __init__(self, book_name, chapter_num, chapter_text, rhythm_row):
        self.book_name = book_name
        self.chapter_num = chapter_num
        self.text = chapter_text
        self.rhythm = rhythm_row  # from rhythm CSV row
        self.new_facts = []       # strings: facts established
        self.new_debts = []       # dicts: {summary, type, severity}
        self.resolved_debts = []  # ints: debt IDs resolved
        # v8.6: 势力状态变更
        self.faction_changes = []  # list of {faction_id, field, delta, reason}

    def audit(self):
        """Extract facts and debts from chapter data.

        Note: This method appends to self.new_facts/new_debts. If called
        multiple times, results will accumulate. Use _audit_done flag to
        ensure idempotency.
        """
        if getattr(self, "_audit_done", False):
            return self._cached_audit
        self._audit_done = True
        # Fact extraction from rhythm metrics
        r = self.rhythm
        wc = int(r.get("wc", 0))
        hook_type = r.get("hook_type", "none")
        conflict = r.get("conflict_density", 0)
        emotion = r.get("emotion", "日常")

        # Automated fact extraction
        self.new_facts.append(f"字数: {wc}")
        if hook_type != "none":
            self.new_facts.append(f"章末钩子: {hook_type}")
        if float(conflict) > 0.5:
            self.new_facts.append(f"冲突密度: {conflict}")

        # New debt: chapter ended on cliffhanger
        if hook_type in ("strong", "weak") and wc > 300:
            self.new_debts.append({
                "type": "hook",
                "summary": f"章末钩子({hook_type}): 需要后文章节兑现",
                "severity": "HIGH" if hook_type == "strong" else "MED",
            })

        # New debt: emotional apex unreleased
        if emotion in ("悲壮", "紧张", "压抑") and float(r.get("pleasure_intensity", 0)) < 1.5:
            self.new_debts.append({
                "type": "emotion_release",
                "summary": f"情绪{emotion}未释放 — 建议后文安排爽点或温情转折",
                "severity": "MED",
            })

        # Mark debts resolved by this chapter's content
        if float(r.get("pleasure_intensity", 0)) > 3.0:
            self.resolved_debts.append("previous_emotion_buildup")

        # v8.6: 从章节文本提取势力状态变更
        self._extract_faction_changes()

        # v8.6: 根据势力变更生成势力债务 (统一入口，避免重复)
        for change in self.faction_changes:
            fac_id = change.get("faction_id", "")
            field = change.get("field", "")
            delta = change.get("delta", 0)
            reason = change.get("reason", "")
            debt_type = change.get("debt_type")

            # 优先使用规则定义的 debt_type
            if debt_type:
                self.new_debts.append({
                    "type": debt_type,
                    "summary": f"{fac_id} — {reason} (第{self.chapter_num}章)",
                    "severity": "HIGH" if delta < -0.15 else "MED",
                    "faction_id": fac_id,
                })
            # 补充：基于变更幅度生成额外债务
            elif field == "stability" and delta < -0.15:
                self.new_debts.append({
                    "type": "faction_internal_crisis",
                    "summary": f"势力{fac_id}稳定度骤降({delta:+.2f}) — 后续需处理内部危机后果",
                    "severity": "HIGH",
                    "faction_id": fac_id,
                })
            elif field == "threat_level" and delta > 0.15:
                self.new_debts.append({
                    "type": "faction_external_threat",
                    "summary": f"势力{fac_id}面临严重外部威胁(+{delta:.2f}) — 后续需应对入侵或冲突",
                    "severity": "HIGH",
                    "faction_id": fac_id,
                })
            elif field == "power_level" and delta < 0:
                self.new_debts.append({
                    "type": "faction_decline",
                    "summary": f"势力{fac_id}实力下降({delta}) — 后续需处理衰弱后果",
                    "severity": "MED",
                    "faction_id": fac_id,
                })

        result = {
            "chapter": self.chapter_num,
            "wc": wc,
            "new_facts": self.new_facts,
            "new_debts": self.new_debts,
            "resolved": self.resolved_debts,
            # v8.6: 势力状态变更
            "faction_changes": self.faction_changes,
        }
        self._cached_audit = result
        return result

    def to_markdown(self):
        """Generate post-write audit as markdown."""
        data = self.audit()
        lines = [f"### 第{self.chapter_num}章 提交审计",
                 f"字数: {data['wc']}",
                 ""]
        if data["new_facts"]:
            lines.append("**新事实:**")
            for f in data["new_facts"]:
                lines.append(f"  - {f}")
            lines.append("")
        if data["new_debts"]:
            lines.append("**新债务:**")
            for d in data["new_debts"]:
                lines.append(f"  - [{d['severity']}] {d['summary']}")
            lines.append("")
        if data["resolved"]:
            lines.append(f"**已兑现:** {', '.join(data['resolved'])}")
            lines.append("")
        # v8.6: 势力状态变更
        if data.get("faction_changes"):
            lines.append("**势力状态变更:**")
            for fc in data["faction_changes"]:
                fac = fc.get("faction_id", "?")
                field = fc.get("field", "")
                delta = fc.get("delta", 0)
                reason = fc.get("reason", "")
                sign = "+" if delta >= 0 else ""
                lines.append(f"  - {fac}.{field} {sign}{delta:.2f} ({reason})")
            lines.append("")
        return lines

    # ── v8.6: 势力状态变更提取 ──

    def _extract_faction_changes(self):
        """v8.6: 从章节文本中启发式提取势力状态变更。

        通过关键词匹配检测章节中描述的势力状态变化，
        生成结构化的 faction_changes 记录。

        检测模式:
        - 战争/冲突 → stability 下降, threat 上升
        - 结盟/合作 → threat 下降, treasury 上升
        - 内乱/政变 → stability 大幅下降
        - 资源发现 → treasury 上升
        - 首领死亡 → stability/morale 下降
        """
        if not self.text:
            return

        text = self.text

        # 势力名称候选 (从文本中提取常见模式)
        # 简化版：检测"XX势力"、"XX族"、"XX军"等模式
        import re
        faction_pattern = re.compile(
            r'([\u4e00-\u9fff]{2,6}(?:势力|族|军|盟|帮|派|教|国|城|营|会))'
        )
        factions_found = set(faction_pattern.findall(text))

        # 关键词 → 效果映射
        change_rules = [
            {
                "keywords": ["开战", "宣战", "进攻", "入侵", "攻打", "出兵", "战争爆发"],
                "field": "stability",
                "delta": -0.15,
                "reason": "战争爆发",
                "debt_type": "faction_war",
            },
            {
                "keywords": ["结盟", "联盟", "合作", "签订条约", "议和", "停战"],
                "field": "threat_level",
                "delta": -0.10,
                "reason": "结盟/议和",
                "debt_type": "faction_alliance",
            },
            {
                "keywords": ["叛乱", "政变", "内战", "哗变", "造反", "兵变"],
                "field": "stability",
                "delta": -0.25,
                "reason": "内部叛乱",
                "debt_type": "faction_internal_crisis",
            },
            {
                "keywords": ["首领死亡", "首领被杀", "族长陨落", "城主战死", "掌门身亡",
                            "首领遇刺", "被斩杀"],
                "field": "morale",
                "delta": -0.20,
                "reason": "首领死亡",
                "debt_type": "faction_leadership_crisis",
            },
            {
                "keywords": ["发现矿脉", "获得资源", "意外收获", "宝藏", "资源丰富"],
                "field": "treasury",
                "delta": 0.15,
                "reason": "资源发现",
                "debt_type": None,
            },
            {
                "keywords": ["溃败", "惨败", "全军覆没", "大败", "惨遭屠杀"],
                "field": "power_level",
                "delta": -1,
                "reason": "惨败",
                "debt_type": "faction_decline",
            },
        ]

        for rule in change_rules:
            matched_kw = ""
            for kw in rule["keywords"]:
                if kw in text:
                    matched_kw = kw
                    break

            if matched_kw:
                # 对所有检测到的势力应用变更
                for fac_name in factions_found:
                    self.faction_changes.append({
                        "faction_id": fac_name,
                        "field": rule["field"],
                        "delta": rule["delta"],
                        "reason": rule["reason"],
                        "keyword_matched": matched_kw,
                        "debt_type": rule.get("debt_type"),
                    })

        # 注意：债务生成由 audit() 统一处理，这里只记录变更


# ============================================================================
# 4. 债务看板 — 跨章追踪
# ============================================================================

class DebtBoard:
    """Cross-chapter tracker: unresolved hooks, foreshadowing, character arcs.
    Persists to JSON for survival across runs."""

    MAX_DEBTS = 200

    def __init__(self, book_name):
        self.book_name = book_name
        self.debts = []     # list of {id, origin_ch, type, summary, severity, status, resolved_at}
        self._next_id = 1
        self._storage = CONTRACTS_DIR / book_name / "debt_board.json"
        self._load()

    def _load(self):
        if self._storage.exists():
            try:
                data = json.loads(self._storage.read_text(encoding="utf-8"))
                self.debts = data.get("debts", [])
                self._next_id = max((d.get("id", 0) for d in self.debts), default=0) + 1
            except (json.JSONDecodeError, KeyError):
                self.debts = []
                self._next_id = 1

    def _save(self):
        self._storage.parent.mkdir(parents=True, exist_ok=True)
        self._storage.write_text(json.dumps({
            "book": self.book_name,
            "updated": datetime.now().isoformat(),
            "total": len(self.debts),
            "pending": sum(1 for d in self.debts if d["status"] == "pending"),
            "debts": self.debts,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    def add_debt(self, chapter_num, debt_type, summary, severity="MED",
                 faction_id=None, target_faction_id=None):
        """Add a new debt to the board.

        v8.6: 新增势力债务支持。当 debt_type 以 'faction_' 开头时，
        该债务关联到势力而非角色，用于追踪势力间的动态关系。

        Args:
            chapter_num: 产生债务的章节
            debt_type: 债务类型（如 '伏笔', '角色弧' 或 'faction_war', 'faction_alliance'）
            summary: 债务摘要
            severity: 严重度 (LOW/MED/HIGH/CRITICAL)
            faction_id: v8.6 新增 — 关联势力ID
            target_faction_id: v8.6 新增 — 目标势力ID（用于势力间债务）
        """
        debt = {
            "id": self._next_id,
            "origin_ch": chapter_num,
            "type": debt_type,
            "summary": summary,
            "severity": severity,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "resolved_at": None,
            # v8.6: 势力债务扩展字段
            "faction_id": faction_id,
            "target_faction_id": target_faction_id,
            "is_faction_debt": debt_type.startswith("faction_") if debt_type else False,
        }
        self.debts.append(debt)
        self._next_id += 1
        self._trim()
        self._save()
        return debt["id"]

    def resolve_debt(self, debt_id, chapter_num):
        """Mark a debt as resolved at given chapter."""
        for d in self.debts:
            if d["id"] == debt_id and d["status"] == "pending":
                d["status"] = "resolved"
                d["resolved_at"] = chapter_num
                self._save()
                return True
        return False

    def get_pending(self, chapter_num=None):
        """Return all pending debts, optionally filtered by chapter."""
        pending = [d for d in self.debts if d["status"] == "pending"]
        if chapter_num:
            pending = [d for d in pending if d["origin_ch"] <= chapter_num]
        return pending

    def overdue_debts(self, current_chapter, overdue_gap=10):
        """Return debts that are overdue (created > overdue_gap chapters ago)."""
        return [d for d in self.get_pending()
                if current_chapter - d["origin_ch"] > overdue_gap]

    # v8.6: 势力债务专用方法

    def get_faction_debts(self, faction_id=None, current_chapter=None):
        """v8.6: 获取势力相关的债务。

        Args:
            faction_id: 筛选特定势力的债务；None 返回所有势力债务
            current_chapter: 只返回该章之前的债务

        Returns:
            势力债务列表
        """
        result = [d for d in self.debts if d.get("is_faction_debt")]
        if faction_id:
            result = [d for d in result
                      if d.get("faction_id") == faction_id
                      or d.get("target_faction_id") == faction_id]
        if current_chapter:
            result = [d for d in result if d["origin_ch"] <= current_chapter]
        return result

    def add_faction_debt(self, chapter_num, debt_type, summary,
                         faction_id, target_faction_id=None,
                         severity="HIGH"):
        """v8.6: 添加势力间债务（便捷方法）。

        常用势力债务类型:
        - faction_war: 战争状态（需后续章节处理战争后果）
        - faction_alliance: 结盟承诺（需后续章节体现盟友互动）
        - faction_debt: 资源/人情债务（需后续章节偿还）
        - faction_betrayal: 背叛事件（需后续章节处理报复）
        - faction_refugee: 难民问题（需后续章节处理安置）

        Args:
            chapter_num: 章节
            debt_type: 必须以 'faction_' 开头
            summary: 债务摘要
            faction_id: 源势力ID
            target_faction_id: 目标势力ID
            severity: 默认 HIGH
        """
        if not debt_type.startswith("faction_"):
            debt_type = f"faction_{debt_type}"
        return self.add_debt(
            chapter_num, debt_type, summary, severity,
            faction_id=faction_id,
            target_faction_id=target_faction_id,
        )

    def _trim(self):
        """Prevent unlimited growth: archive old resolved debts."""
        resolved_old = [d for d in self.debts
                        if d["status"] == "resolved" and d.get("resolved_at", 0) < 999]
        if len(self.debts) > self.MAX_DEBTS:
            cutoff = sorted(resolved_old, key=lambda d: d["resolved_at"])[0]
            self.debts = [d for d in self.debts if d != cutoff]

    def stats(self):
        """Return summary statistics."""
        pending = len([d for d in self.debts if d["status"] == "pending"])
        resolved = len([d for d in self.debts if d["status"] == "resolved"])
        by_type = defaultdict(int)
        for d in self.debts:
            by_type[d["type"]] += 1
        # v8.6: 势力债务统计
        faction_debts = [d for d in self.debts if d.get("is_faction_debt")]
        faction_pending = [d for d in faction_debts if d["status"] == "pending"]
        return {
            "total": len(self.debts),
            "pending": pending,
            "resolved": resolved,
            "by_type": dict(by_type),
            "overdue_count": 0,
            # v8.6: 势力债务统计
            "faction_debts_total": len(faction_debts),
            "faction_debts_pending": len(faction_pending),
        }

    def to_markdown(self, current_chapter=0):
        """Generate debt board summary as markdown."""
        s = self.stats()
        overdue = self.overdue_debts(current_chapter) if current_chapter else []
        lines = ["### 债务看板",
                 f"总计:{s['total']} | 待兑现:{s['pending']} | " f"已兑现:{s['resolved']} | 逾期:{len(overdue)}",
                 ""]
        if overdue:
            lines.append("**[逾期债务]**")
            for d in overdue:
                lines.append(f"  - [ch{d['origin_ch']}, +{current_chapter - d['origin_ch']}章] {d['summary']}")
            lines.append("")
        if s["pending"] > 0:
            lines.append("**[待兑现]**")
            for d in self.get_pending()[:10]:
                # v8.6: 标记势力债务
                faction_tag = ""
                if d.get("is_faction_debt"):
                    fac = d.get("faction_id", "?")
                    tgt = d.get("target_faction_id", "")
                    faction_tag = f" [{fac}→{tgt}]" if tgt else f" [{fac}]"
                lines.append(f"  - [{d['severity']}] ch{d['origin_ch']}{faction_tag}: {d['summary'][:60]}")
            lines.append("")

        # v8.6: 势力债务单独分区
        faction_pending = [d for d in self.get_pending() if d.get("is_faction_debt")]
        if faction_pending:
            lines.append("**[势力动态债务]**")
            for d in faction_pending[:10]:
                fac = d.get("faction_id", "?")
                tgt = d.get("target_faction_id", "")
                arrow = f" → {tgt}" if tgt else ""
                lines.append(f"  - [{d['severity']}] ch{d['origin_ch']} {fac}{arrow}: {d['summary'][:60]}")
            lines.append("")
        return lines


# ============================================================================
# 5. 合同链管道 — 整合四阶段
# ============================================================================

def run_contract_chain(book_name, chapter_num, rhythm_row=None, chapter_text="",
                       pre_write=False, post_write=False, chapter_tags=None):
    """Main pipeline: run contract chain for one chapter.

    Args:
        book_name: book identifier
        chapter_num: current chapter number
        rhythm_row: dict from rhythm CSV (post-write only)
        chapter_text: chapter body text (post-write only)
        pre_write: generate runtime contract for the author
        post_write: audit the chapter after writing
        chapter_tags: optional tags for seed filtering (e.g. ['战斗', '转折'])

    Returns:
        dict with pre_contract and/or post_audit keys
    """
    # Load seeds (once per book via ContractSeed singleton)
    seed_bank = ContractSeed(book_name)
    debt_board = DebtBoard(book_name)
    result = {}

    # Pre-write: build runtime contract
    if pre_write:
        contract = RuntimeContract(book_name, chapter_num, seed_bank, debt_board)
        contract.build(chapter_tags)
        result["pre_contract"] = {
            "contract": contract.contract,
            "markdown": contract.to_markdown(),
            "seeds_loaded": seed_bank.loaded,
        }

    # Post-write: audit the chapter
    if post_write and rhythm_row:
        commit = ChapterCommit(book_name, chapter_num, chapter_text, rhythm_row)
        audit_data = commit.audit()

        # Register new debts
        for d in audit_data["new_debts"]:
            debt_board.add_debt(chapter_num, d["type"], d["summary"], d["severity"])

        result["post_audit"] = {
            "audit": audit_data,
            "markdown": commit.to_markdown(),
            "debt_board_md": debt_board.to_markdown(chapter_num),
            "debt_stats": debt_board.stats(),
        }

        # [WARN] Canon empty detection
        if not seed_bank.loaded:
            result["warning"] = (
                "合同种子未加载 — assets/canon/ 文件为占位状态。"
                "合同链仅启用了债务追踪。要启用完整合同检查，请填入 canon/*.md。"
            )

    return result


# ============================================================================
# 6. 批量审计 — 从 rhythm CSV 反向分析
# ============================================================================

def batch_audit_from_rhythm(book_name, rhythm_csv_path, max_chapters=None):
    """Post-hoc audit: feed rhythm CSV rows through contract chain.
    Useful for analyzing existing reference books and detecting pattern debts.

    Returns:
        dict with debt_stats and per-chapter audit entries.
    """
    rows = []
    with open(rhythm_csv_path, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            for k in ["hook_density", "conflict_density", "pleasure_intensity",
                       "dialogue_ratio", "readability", "wc"]:
                try:
                    row[k] = float(row.get(k, 0))
                except (ValueError, TypeError):
                    row[k] = 0.0
            rows.append(row)

    if max_chapters:
        rows = rows[:max_chapters]

    debt_board = DebtBoard(book_name)
    audits = []

    for row in rows:
        ch_num = int(row.get("ch_num", 0))
        commit = ChapterCommit(book_name, ch_num, "", row)
        audit_data = commit.audit()
        for d in audit_data["new_debts"]:
            debt_board.add_debt(ch_num, d["type"], d["summary"], d["severity"])
        audits.append(audit_data)

    return {
        "book": book_name,
        "chapters_audited": len(audits),
        "debt_stats": debt_board.stats(),
        "debt_board_md": debt_board.to_markdown(),
        "audits": audits,
    }


# ============================================================================
# CLI
# ============================================================================

def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        return

    book_name = "末日模拟器"
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--book" and i < len(sys.argv) - 1:
            book_name = sys.argv[i + 1]

    # Demo: pre-write contract
    result = run_contract_chain(book_name, 1, pre_write=True)
    if "warning" in result:
        print(f"[WARN] {result['warning']}")
        print("")
    if "pre_contract" in result:
        for line in result["pre_contract"]["markdown"]:
            print(line)

    # Demo: seed summary
    seed_bank = ContractSeed(book_name)
    print(seed_bank.summary())
    print(f"  canon/ 文件: {list(seed_bank.canon_files.keys())}")
    placeholders = [k for k, v in seed_bank.canon_files.items() if "待填写" in v[:50]]
    if placeholders:
        print(f"  待填写: {placeholders}")
    print("\n[DONE] Contract chain initialized. Fill assets/canon/*.md to enable seeds.")


if __name__ == "__main__":
    main()
