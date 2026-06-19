#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
recursive_summarize.py — 递归摘要: L1章→L2卷→L3全书
=====================================================
灵感: Map-Reduce + webnovel-writer 递归分析模式
适配: 本地 Qwen3.5-9B, ctx=8192, KV q8_0

三层级:
  L1 章节组摘要 (3-5章 → 结构化JSON, 保留伏笔/角色/情绪)
  L2 卷级合成   (5组 L1 → 节奏曲线 + 伏笔推进 + 冲突模式)
  L3 全书分析   (所有 L2 → 结构模式 + 爽点分布 + 角色弧光)

关键设计:
  - 每层输出强制包含"保留字段"(伏笔清单/角色状态) → 防信息丢失
  - 单次 LLM 输入控制在 3000 中文/次 (ctx=8192 舒适区)
  - 可独立运行，不与 rhythm/llm_batch 耦合

用法:
  python analysis/recursive_summarize.py --book <name>
  python analysis/recursive_summarize.py --book all --genre 末世
"""

import csv
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import yaml
from collections import defaultdict
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from analysis.rhythm_analyzer import extract_chapters
try:
    from scripts.progress_server import ProgressHandler
    _HAS_PROGRESS = True
except ImportError:
    _HAS_PROGRESS = False
OUTPUT_DIR = PROJECT_ROOT / "data" / "processed"
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


# ── LLM helpers (matching rhythm_analyzer pattern) ──

def _llm_port():
    try:
        if CONFIG_PATH.exists():
            cfg = yaml.safe_load(open(CONFIG_PATH, encoding="utf-8"))
            return cfg.get("analysis", {}).get("llm_port", 8000)
    except Exception:
        pass
    return 8000


def _llm_call(prompt, max_tokens=600, temperature=0.1, timeout=90):
    """Single LLM call with retry. Returns text or None."""
    data = json.dumps({
        "messages": [
            {"role": "system", "content": "你是专业网文分析助手。输出纯JSON，不要任何额外说明。"},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }).encode("utf-8")

    for attempt in range(3):
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{_llm_port()}/v1/chat/completions",
                data, {"Content-Type": "application/json"}
            )
            resp = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
            return resp["choices"][0]["message"].get("content", "")
        except Exception as e:
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
            else:
                print(f"  [WARN] LLM call failed: {e}")
                return None


def _parse_json(text):
    """Extract JSON from LLM response, handling truncated output."""
    if not text:
        return None
    # Try code block
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # Try raw JSON (including truncated — repair missing braces/quotes)
    m = re.search(r'\{.*', text, re.DOTALL)
    if m:
        raw = m.group()
        # Repair truncated JSON: close unclosed strings and braces
        repaired = _repair_json(raw)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            try:
                return json.loads(raw)  # try original
            except json.JSONDecodeError:
                pass
    return None


def _repair_json(raw):
    """Attempt to repair truncated JSON by closing unclosed structures."""
    # Close unclosed strings (odd number of quotes at end)
    if raw.count('"') % 2 != 0:
        raw = raw + '"'
    # Count braces
    open_braces = raw.count('{') - raw.count('}')
    open_brackets = raw.count('[') - raw.count(']')
    # Add missing closing brackets/braces
    # First, trim to last comma or complete value
    last_comma = raw.rfind(',')
    last_brace = raw.rfind('}')
    last_bracket = raw.rfind(']')
    last_good = max(last_comma, last_brace, last_bracket)
    if last_good > 0:
        raw = raw[:last_good]
        # Recalculate
        open_braces = raw.count('{') - raw.count('}')
        open_brackets = raw.count('[') - raw.count(']')
    raw += ']' * open_brackets
    raw += '}' * open_braces
    return raw


def _safe_truncate(text, max_chars):
    """Truncate text without corrupting JSON structure.

    Strategy:
    1. If text fits, return as-is.
    2. Otherwise, try compact JSON (indent=None) to gain headroom.
    3. If still too long, cut at a safe boundary (between top-level array
       elements) so the LLM sees complete objects, then repair braces.
    """
    if not text or len(text) <= max_chars:
        return text

    # Attempt 1: compact re-serialize from original python obj if caller passed JSON
    # (caller already serialized, so we only have string here; compact via reparse)
    try:
        obj = json.loads(text)
        compact = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        if len(compact) <= max_chars:
            return compact
    except json.JSONDecodeError:
        pass

    # Attempt 2: cut at last safe boundary — a complete top-level element.
    # We look for the last '", "' or '"}, {"' before the limit to avoid
    # slicing an object in half.
    cut = text[:max_chars]
    # Prefer boundaries that end a complete element
    for sep in ('", "', '"}, {', '"},', '"],'):
        idx = cut.rfind(sep)
        if idx > max_chars * 0.5:  # don't throw away more than half
            cut = text[:idx]
            break
    # Repair: close any unclosed structures so the LLM sees valid JSON-ish text
    cut = _repair_json(cut)
    return cut


# ── L1: 章节组摘要 ──

L1_PROMPT = """分析以下 {n_chapters} 章 ({start}-{end}章)，提取结构化信息：

{chunk_text}

输出JSON (只输出JSON):
{{
  "book": "{book_name}",
  "chapters": "{start}-{end}",
  "word_count": "预估总字数",
  
  "hooks": [
    {{"ch": 章号, "type": "悬念/冲突/情感/信息", "desc": "钩子描述", "resolved": false}}
  ],
  "character_changes": [
    {{"name": "角色名", "ch": 章号, "event": "事件", "arc": "上升/下降/转折/出场"}}
  ],
  "key_events": ["事件1", "事件2"],
  "emotion_curve": [
    {{"ch": 章号, "emotion": "爽/抑/平/转/悲/燃", "intensity": 1-10}}
  ],
  "conflicts": [
    {{"ch": 章号, "type": "人物/势力/内部/环境", "desc": "冲突描述", "intensity": 1-10}}
  ],
  "foreshadowing": [
    {{"id": "唯一ID", "ch": 章号, "desc": "伏笔描述", "status": "埋设/推进/回收"}}
  ],
  "pacing_notes": "这段的节奏特点: 快/慢/交替, 爽点密度高/低",
  "chapter_summaries": [
    {{"ch": 章号, "summary": "1-2句话摘要"}}
  ]
}}"""


# ── L2: 卷级合成 ──

L2_PROMPT = """基于以下 {n_groups} 组章节摘要，做卷级分析：

{merged_text}

输出JSON (只输出JSON):
{{
  "book": "{book_name}",
  "range": "{start}-{end}章",
  "rhythm_pattern": "节奏模式描述 (如: 慢热铺垫→中段爬升→末段爆发)",
  "hook_chain": [
    {{"from_ch": 起始章, "to_ch": 兑现章, "type": "钩子类型", "desc": "钩子链条描述"}}
  ],
  "emotional_arc": "这卷的情绪曲线总结",
  "conflict_escalation": "冲突升级路径 (如: 个人冲突→团队冲突→世界冲突)",
  "active_foreshadowing": [
    {{"id": "伏笔ID", "ch": 埋设章, "desc": "描述", "resolution_eta": "预估兑现区间"}}
  ],
  "character_tracking": [
    {{"name": "角色名", "arc_summary": "本卷角色弧光", "power_change": "+/0/-"}}
  ],
  "pleasure_landmarks": [
    {{"ch": 章号, "type": "打脸/突破/反杀/神转折", "intensity": 1-10}}
  ],
  "debt_register": [
    {{"type": "hook/emotion/character", "desc": "未兑现的叙事债务", "severity": "HIGH/MED/LOW"}}
  ],
  "volume_summary": "本卷200字摘要"
}}"""


# ── L3: 全书分析 ──

L3_PROMPT = """基于以下 {n_volumes} 卷的摘要，做全书级分析：

{merged_text}

输出JSON (只输出JSON):
{{
  "book": "{book_name}",
  "total_chapters": "总章数",
  "total_words": "总字数(万)",
  
  "structure_pattern": "全书结构模式 (如: 三幕式/四段升级/螺旋上升)",
  "pleasure_distribution": {{
    "early": "前期爽点密度(1-100章)",
    "middle": "中期爽点密度",
    "late": "后期爽点密度",
    "landmarks": "关键爽点位置"
  }},
  "character_arcs": [
    {{"name": "主角", "full_arc": "成长弧线总结", "power_curve": "实力增长曲线"}}
  ],
  "theme_evolution": "主题如何逐步深化",
  "narrative_rhythm": {{
    "pattern": "节奏模式",
    "avg_hook_gap": "平均钩子间隔(章)",
    "climax_chapters": "高潮章节位置"
  }},
  "hook_system": {{
    "long_term": "长线伏笔数量和回收率",
    "short_term": "短线钩子密度",
    "unresolved": "未兑现伏笔清单"
  }},
  "commercial_assessment": {{
    "readability": "可读性评估",
    "retention_risk_chapters": "可能流失的章节区间",
    "best_chapters": "全书最佳章节",
    "score_estimate": "预估商业分(1-100)"
  }},
  "writing_insights": [
    "对作者有价值的发现1",
    "发现2"
  ],
  "book_summary": "全书300字摘要"
}}"""


# ── Main Recursive Summarizer ──

class RecursiveSummarizer:
    """3-level recursive chapter summarization."""

    def __init__(self, book_name, genre="末世", chapters_per_group=8, volumes_per_level=5):
        self.book_name = book_name
        self.genre = genre
        self.chapters_per_group = chapters_per_group
        self.volumes_per_level = volumes_per_level
        self.out_dir = OUTPUT_DIR / genre / "summaries"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.chapters = []
        self._checkpoint_path = self.out_dir / f"{book_name}_checkpoint.json"
        self._failed_path = self.out_dir / f"{book_name}_failed.jsonl"
        self._partial_path = self.out_dir / f"{book_name}_partial.json"
        self._checkpoint = {"l1_done": [], "l1_data": {}, "l2_done": [], "l3_done": False}
        self.was_skipped = False  # set True when idempotent skip triggers
        self._load_checkpoint()

    def load_chapters(self, chapters):
        """Load chapter dicts from rhythm_analyzer.extract_chapters() output."""
        self.chapters = chapters  # list of {num, title, raw_body}

    def _load_checkpoint(self):
        """Load checkpoint from disk if exists."""
        if self._checkpoint_path.exists():
            try:
                data = json.loads(self._checkpoint_path.read_text(encoding="utf-8"))
                self._checkpoint = data
                # Ensure backward compat: add missing keys
                for key in ["l1_done", "l1_data", "l2_done", "l3_done"]:
                    if key not in self._checkpoint:
                        self._checkpoint[key] = [] if "done" in key else {} if key == "l1_data" else False
            except (json.JSONDecodeError, IOError):
                self._checkpoint = {"l1_done": [], "l1_data": {}, "l2_done": [], "l3_done": False}

    def _save_checkpoint(self):
        """Atomic checkpoint write."""
        tmp = self._checkpoint_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._checkpoint, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(self._checkpoint_path)

    def _is_output_valid(self):
        """Check if complete output JSON exists and has real content (not stub)."""
        json_path = self.out_dir / f"{self.book_name}_recursive.json"
        if not json_path.exists():
            return False
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            l3 = data.get("l3_analysis", {})
            # Must have real book summary (not LLM-unavailable stub)
            if not l3.get("book_summary") or l3["book_summary"] in (
                "(LLM unavailable)", "(checkpoint resume)", ""):
                return False
            # Must have real structure analysis
            if not l3.get("structure_pattern") or l3["structure_pattern"] == "N/A":
                return False
            # Must have at least some L1 content (not all empty)
            l1 = data.get("l1_summaries", [])
            if not l1:
                return False
            # At least 50% of L1 summaries must have hooks or events
            filled = sum(1 for s in l1 if s.get("hooks") or s.get("key_events"))
            if filled < len(l1) * 0.5:
                return False
            return True
        except (json.JSONDecodeError, IOError, KeyError):
            return False

    def _quality_report(self, l1_summaries, l2_summaries, l3):
        """Check output quality: count empty fields, warn on low quality."""
        issues = []
        empty_l1 = sum(1 for s in l1_summaries
                       if not s.get("hooks") and not s.get("key_events"))
        if empty_l1 > 0:
            issues.append(f"{empty_l1}/{len(l1_summaries)} L1 groups empty (LLM failures)")
        if l3 and not l3.get("structure_pattern"):
            issues.append("L3 missing structure_pattern")
        if l3 and not l3.get("book_summary"):
            issues.append("L3 missing book_summary")
        return issues

    def _log_failed(self, chunk_label, error_msg):
        """Append failed chunk to dead-letter queue."""
        with open(self._failed_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "book": self.book_name,
                "chunk": chunk_label,
                "error": str(error_msg),
                "ts": datetime.now().isoformat(),
            }, ensure_ascii=False) + "\n")

    def _run_l1_if_needed(self):
        """L1 with checkpoint resume: load saved data for done chunks."""
        results = []
        chunks = self._chunk_list(self.chapters, self.chapters_per_group)
        n_total = len(chunks)
        done_set = set(self._checkpoint.get("l1_done", []))
        l1_data = self._checkpoint.get("l1_data", {})
        # Store total in checkpoint for progress panel accuracy
        self._checkpoint["l1_total"] = n_total
        chunk_times = []  # rolling timing for ETA
        t0 = time.time()

        for ci, chunk in enumerate(chunks):
            chunk_label = str(ci)
            if chunk_label in done_set and chunk_label in l1_data:
                results.append(l1_data[chunk_label])
                self._progress_bar(ci + 1, n_total, chunk_times, t0)
                continue
            elif chunk_label in done_set:
                pass  # backward compat: re-run

            t_chunk = time.time()
            parsed = self._process_l1_chunk(chunk, ci)
            dt = time.time() - t_chunk
            if dt > 0.1:
                chunk_times.append(dt)

            if parsed:
                results.append(parsed)
                self._checkpoint.setdefault("l1_data", {})[chunk_label] = parsed
                if chunk_label not in self._checkpoint["l1_done"]:
                    self._checkpoint["l1_done"].append(chunk_label)
                self._save_checkpoint()
                self._save_partial(results)
            else:
                self._log_failed(chunk_label, "LLM returned None after retries")
                results.append(self._fallback_l1(chunk, ci))

            self._progress_bar(ci + 1, n_total, chunk_times, t0)
        return results

    def _progress_bar(self, done, total, chunk_times, t0):
        """Print single-line progress with ETA."""
        pct = done / total * 100 if total else 0
        bar_len = 20
        filled = int(bar_len * done / total) if total else 0
        bar = "#" * filled + "-" * (bar_len - filled)

        # ETA from rolling average
        if chunk_times:
            avg = sum(chunk_times) / len(chunk_times)
            eta_s = avg * (total - done)
            if eta_s > 60:
                eta_str = f"ETA {eta_s/60:.1f}m"
            else:
                eta_str = f"ETA {eta_s:.0f}s"
        else:
            avg = 0
            eta_str = "ETA ..."

        elapsed = time.time() - t0
        spd = f"{avg:.1f}s/ch" if avg else "..."
        line = f"  L1 [{bar}] {done}/{total} ({pct:.0f}%) | {spd} | {eta_str} | {elapsed:.0f}s elapsed"
        # Use \r to overwrite, print to stderr for real-time visibility
        print("\r" + line + "   ", end="", flush=True)
        if done >= total:
            print()  # final newline

    def _fallback_l1(self, chunk, ci):
        """Minimal fallback when LLM call fails (not stored in checkpoint)."""
        start = chunk[0].get("num", ci * self.chapters_per_group + 1)
        end = chunk[-1].get("num", start + len(chunk) - 1)
        return {
            "book": self.book_name,
            "chapters": f"{start}-{end}",
            "hooks": [], "character_changes": [],
            "key_events": [], "emotion_curve": [],
            "conflicts": [], "foreshadowing": [],
            "pacing_notes": "(LLM failed after retries)",
            "chapter_summaries": [
                {"ch": ch.get("num", "?"), "summary": ""}
                for ch in chunk
            ],
        }

    def _save_partial(self, l1_results):
        """Incrementally save partial results (survives crash without checkpoint)."""
        partial = {
            "book": self.book_name,
            "l1_count": len(l1_results),
            "total_chapters": len(self.chapters),
            "l1_summaries": l1_results,
            "checkpoint": self._checkpoint,
        }
        tmp = self._partial_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(partial, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(self._partial_path)

    def _process_l1_chunk(self, chunk, ci):
        """Process a single L1 chunk with retry."""
        start = chunk[0].get("num", ci * self.chapters_per_group + 1)
        end = chunk[-1].get("num", start + len(chunk) - 1)
        text = "\n\n".join(
            f"第{ch.get('num', '?')}章:\n{ch.get('raw_body', '')[:800]}"
            for ch in chunk
        )
        if len(text) > 4000:
            text = text[:4000]

        prompt = L1_PROMPT.format(
            n_chapters=len(chunk), start=start, end=end,
            chunk_text=text, book_name=self.book_name,
        )
        raw = _llm_call(prompt, max_tokens=1500)
        parsed = _parse_json(raw)
        if parsed:
            return parsed
        return None  # callback handles fallback

    def run(self, save=True):
        """Run full 3-level recursive summarization with checkpoint resume."""
        if not self.chapters:
            print(f"[WARN] No chapters loaded for {self.book_name}")
            return None

        # P0-1: Idempotent skip — already-done books cost zero LLM calls
        if self._is_output_valid():
            print(f"[{self.book_name}] [SKIP] Already complete (idempotent)")
            self.was_skipped = True
            json_path = self.out_dir / f"{self.book_name}_recursive.json"
            return json.loads(json_path.read_text(encoding="utf-8"))

        n_expected_chunks = len(self._chunk_list(self.chapters, self.chapters_per_group))
        n_done = len(self._checkpoint.get("l1_done", []))
        if n_done > 0:
            print(f"[{self.book_name}] Resume from checkpoint: {n_done}/{n_expected_chunks} L1 chunks done")
        print(f"[{self.book_name}] Recursive summarize: {len(self.chapters)} chapters ({n_expected_chunks} L1 chunks)")
        ts = time.time()

        # P0-4: L1 with checkpoint resume + dead-letter queue
        print("  L1: Chapter group summaries...")
        l1_summaries = self._run_l1_if_needed()
        if not l1_summaries:
            return None
        print(f"  L1: {len(l1_summaries)} groups ({time.time()-ts:.0f}s)")

        # P1-4: L2 pipeline overlap — trigger as 5 groups accumulate
        l2_summaries = []
        if len(l1_summaries) >= 3:
            print("  L2: Volume synthesis...")
            l2_summaries = self._level2(l1_summaries)
            print(f"  L2: {len(l2_summaries)} volumes")
        else:
            l2_summaries = l1_summaries

        # L3: Book-level analysis
        if not self._checkpoint.get("l3_done"):
            print("  L3: Book-level analysis...")
            source = l2_summaries if l2_summaries else l1_summaries
            l3_result = self._level3(source)
            self._checkpoint["l3_done"] = True
            self._save_checkpoint()
        else:
            l3_result = self._load_l3_from_disk()

        print(f"  L3: done ({time.time()-ts:.0f}s total)")

        # Quality gate: warn if output has too many empty chunks
        q_issues = self._quality_report(l1_summaries, l2_summaries, l3_result)
        if q_issues:
            for issue in q_issues:
                print(f"  [Q-WARN] {issue}")

        result = {
            "book": self.book_name,
            "total_chapters": len(self.chapters),
            "generated": datetime.now().isoformat(),
            "l1_summaries": l1_summaries,
            "l2_summaries": l2_summaries,
            "l3_analysis": l3_result,
            "quality_flags": q_issues,
        }

        if save:
            self._save(result)
        return result

    def _load_l3_from_disk(self):
        """Fallback: load L3 from existing output if checkpoint says done."""
        json_path = self.out_dir / f"{self.book_name}_recursive.json"
        if json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                return data.get("l3_analysis", {})
            except (json.JSONDecodeError, IOError):
                pass
        return {"book": self.book_name, "book_summary": "(checkpoint resume)"}

    def _level2(self, l1_summaries):
        """L2: Merge L1 summaries into volume-level analysis."""
        results = []
        groups = self._chunk_list(l1_summaries, self.volumes_per_level)
        n_total = len(groups)
        t0 = time.time()
        for gi, group in enumerate(groups):
            ranges = [s.get("chapters", "?") for s in group]
            start = ranges[0].split("-")[0] if ranges else "?"
            end = ranges[-1].split("-")[-1] if ranges else "?"

            merged = json.dumps(group, ensure_ascii=False, indent=2)
            merged = _safe_truncate(merged, 3000)

            prompt = L2_PROMPT.format(
                n_groups=len(group), merged_text=merged,
                book_name=self.book_name, start=start, end=end,
            )
            raw = _llm_call(prompt, max_tokens=1200)
            parsed = _parse_json(raw)
            if parsed:
                results.append(parsed)
            else:
                results.append({
                    "book": self.book_name,
                    "range": f"{start}-{end}章",
                    "rhythm_pattern": "(LLM unavailable)",
                    "volume_summary": f"第{start}-{end}章 (分析未完成)",
                })
            # Overwritable L2 progress (single line)
            pct = (gi + 1) / n_total * 100
            dt = time.time() - t0
            print(f"\r  L2 {gi+1}/{n_total} ({pct:.0f}%) | {dt:.0f}s   ", end="", flush=True)
        print()
        return results

    def _level3(self, source_summaries):
        """L3: Book-level analysis from volume summaries."""
        merged = json.dumps(source_summaries, ensure_ascii=False, indent=2)
        merged = _safe_truncate(merged, 4000)

        prompt = L3_PROMPT.format(
            n_volumes=len(source_summaries), merged_text=merged,
            book_name=self.book_name,
        )
        raw = _llm_call(prompt, max_tokens=1800)
        parsed = _parse_json(raw)
        if parsed:
            return parsed
        return {
            "book": self.book_name,
            "total_chapters": str(len(self.chapters)),
            "book_summary": "(LLM unavailable)",
        }

    def _save(self, result):
        """Persist to JSON + markdown report."""
        json_path = self.out_dir / f"{self.book_name}_recursive.json"
        json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                             encoding="utf-8")

        md_path = self.out_dir / f"{self.book_name}_recursive_report.md"
        md = self._to_markdown(result)
        md_path.write_text("\n".join(md), encoding="utf-8")

        print(f"  [OK] JSON: {json_path.name}")
        print(f"  [OK] Report: {md_path.name}")

    def _to_markdown(self, result):
        """Convert result to markdown report."""
        l3 = result.get("l3_analysis", {})
        lines = [f"# {self.book_name} 递归摘要报告",
                 f"生成: {result.get('generated', '')}",
                 f"章数: {result['total_chapters']} | "
                 f"L1组数: {len(result['l1_summaries'])} | "
                 f"L2卷数: {len(result['l2_summaries'])}",
                 "", "---", ""]

        if l3:
            lines.append("## 全书分析")
            lines.append(f"**结构模式**: {l3.get('structure_pattern', 'N/A')}")
            lines.append(f"**主题**: {l3.get('theme_evolution', '')}")
            lines.append(f"**全书摘要**: {l3.get('book_summary', '')[:200]}")
            lines.append("")

            comm = l3.get("commercial_assessment", {})
            if comm:
                lines.append(f"**商业分预估**: {comm.get('score_estimate', 'N/A')}")
                lines.append(f"**最佳章节**: {comm.get('best_chapters', 'N/A')}")
                lines.append("")

            hook_sys = l3.get("hook_system", {})
            if hook_sys:
                lines.append(f"**长线伏笔**: {hook_sys.get('long_term', 'N/A')}")
                lines.append(f"**未兑现**: {hook_sys.get('unresolved', [])}")
                lines.append("")

            insights = l3.get("writing_insights", [])
            if insights:
                lines.append("**写作洞察**:")
                for ins in insights:
                    lines.append(f"  - {ins}")
                lines.append("")

        return lines

    @staticmethod
    def _chunk_list(lst, n):
        """Split list into chunks of size n."""
        return [lst[i:i + n] for i in range(0, len(lst), n)]


# ── Integration: run from rhythm CSV (reuses existing analysis data) ──

def summarize_from_rhythm_csv(book_name, rhythm_csv_path, genre="末世",
                              chapters_per_group=8):
    """Run recursive summarization using rhythm CSV data + chapter text.
    Falls back to text-only if LLM server is unavailable."""
    from analysis.rhythm_analyzer import extract_chapters

    # Infer txt path from csv path
    csv_path = Path(rhythm_csv_path)
    txt_name = csv_path.stem.replace("rhythm_", "") + ".txt"
    novels_dir = PROJECT_ROOT / "data" / "raw" / "novels" / genre
    txt_path = None
    for candidate in novels_dir.glob("*.txt"):
        if txt_name in candidate.name or candidate.stem[:15] in csv_path.stem:
            txt_path = candidate
            break

    if not txt_path:
        print(f"[WARN] Cannot find source txt for {book_name}")
        return None

    chapters = extract_chapters(txt_path)
    if not chapters:
        print(f"[WARN] No chapters extracted from {txt_path}")
        return None

    summarizer = RecursiveSummarizer(book_name, genre, chapters_per_group)
    summarizer.load_chapters(chapters)
    return summarizer.run()


# ── CLI ──

def _load_chapters_from_txt(txt_path):
    """Load chapters from a novel TXT file."""
    return extract_chapters(Path(txt_path))


def _check_server():
    """Verify LLM server is reachable before starting long batch."""
    try:
        port = _llm_port()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/health",
            headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=5)
        return True
    except Exception as e:
        print(f"[FAIL] LLM server unreachable (port {_llm_port()}): {e}")
        return False


def _start_progress_panel(port=8090):
    """Start progress web panel in background thread (skip if port already in use)."""
    if not _HAS_PROGRESS:
        print("[WARN] progress_server.py not found, progress panel unavailable")
        return None

    # Probe: if something already serves :port (e.g. a standalone
    # progress_server.py started earlier), reuse it instead of double-binding.
    import socket
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.3)
    try:
        probe.connect(("127.0.0.1", port))
        probe.close()
        print(f"[Progress Panel] :{port} already running, reusing")
        return None
    except OSError:
        pass  # port free → we start it

    from http.server import HTTPServer

    def serve():
        server = HTTPServer(("127.0.0.1", port), ProgressHandler)
        server.serve_forever()

    t = threading.Thread(target=serve, daemon=True)
    t.start()

    print(f"[Progress Panel] http://localhost:{port}")
    return t


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        return

    book_filter = None
    genre = "末世"
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--book" and i < len(sys.argv) - 1:
            book_filter = sys.argv[i + 1]
        elif arg == "--genre" and i < len(sys.argv) - 1:
            genre = sys.argv[i + 1]

    # Server health check before batch
    if not _check_server():
        print("Start LLM server first: scripts\\start_model.bat")
        sys.exit(1)
    print(f"[OK] LLM server online (:8000)")

    # Start progress panel (background thread + browser auto-open)
    _start_progress_panel()
    time.sleep(1)  # let server bind

    # Find books
    novels_dir = PROJECT_ROOT / "data" / "raw" / "novels" / genre
    txt_files = sorted(novels_dir.glob("*.txt")) if novels_dir.exists() else []
    if book_filter and book_filter != "all":
        txt_files = [f for f in txt_files if book_filter in f.stem]

    if not txt_files:
        print(f"[WARN] No books found in {novels_dir}")
        return

    n_total = len(txt_files)
    t_all_start = time.time()
    skipped = 0
    failed = 0
    print(f"\nRecursive summarize: {n_total} book(s) in {genre}")
    print("=" * 55)

    for bi, txt_path in enumerate(txt_files, 1):
        book_name = txt_path.stem[:35]
        print(f"\n[Book {bi}/{n_total}] {book_name} ({txt_path.stat().st_size/1024/1024:.1f}MB)")

        chapters = _load_chapters_from_txt(txt_path)
        if not chapters:
            print(f"  [SKIP] No chapters extracted")
            failed += 1
            continue

        summarizer = RecursiveSummarizer(book_name, genre)
        summarizer.load_chapters(chapters)
        result = summarizer.run()

        if result is None:
            failed += 1
        elif summarizer.was_skipped:
            # Idempotent skip: book was already complete before this run
            skipped += 1

        # Book-level ETA
        elapsed = time.time() - t_all_start
        done = bi
        avg_per_book = elapsed / done if done else 0
        eta_remaining = avg_per_book * (n_total - done)
        print(f"  [{bi}/{n_total}] done | {elapsed:.0f}s elapsed | "
              f"avg {avg_per_book:.0f}s/book | ETA {eta_remaining/60:.0f}m remaining")

    total_t = time.time() - t_all_start
    print(f"\n{'='*55}")
    print(f"[DONE] {n_total} books, {total_t/60:.1f}min total, "
          f"{skipped} skipped, {failed} failed")
    print(f"Reports: {OUTPUT_DIR / genre / 'summaries'}")


if __name__ == "__main__":
    main()
