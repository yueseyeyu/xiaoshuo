#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
contract_chain.py — 合同链模块: 合同种子→运行时合同→章节提交→事件审计
=========================================================================
灵感: webnovel-writer Story System (lingfengQAQ, v5.4.2)
适配: 本地 Qwen + 正文 100% 手写 + 七真相文件

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

PROJECT_ROOT = Path(__file__).resolve().parent.parent
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

    def audit(self):
        """Extract facts and debts from chapter data."""
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

        return {
            "chapter": self.chapter_num,
            "wc": wc,
            "new_facts": self.new_facts,
            "new_debts": self.new_debts,
            "resolved": self.resolved_debts,
        }

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
        return lines


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

    def add_debt(self, chapter_num, debt_type, summary, severity="MED"):
        """Add a new debt to the board."""
        debt = {
            "id": self._next_id,
            "origin_ch": chapter_num,
            "type": debt_type,
            "summary": summary,
            "severity": severity,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "resolved_at": None,
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
        return {
            "total": len(self.debts),
            "pending": pending,
            "resolved": resolved,
            "by_type": dict(by_type),
            "overdue_count": 0,
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
                lines.append(f"  - [{d['severity']}] ch{d['origin_ch']}: {d['summary'][:60]}")
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
