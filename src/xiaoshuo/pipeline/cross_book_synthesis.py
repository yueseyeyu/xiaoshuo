#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
cross_book_synthesis.py — 跨书关联发现: 30本 → 模式白皮书
==========================================================
灵感: OpenClaw "REM 关联生成" (梦境系统的第三步)

输入: recursive_summarize.py 的 L3 全书分析 JSON
      genre_synthesizer.py 的商业评分 JSON
输出: 《品类写作模式白皮书》 — 跨书规律 + 验证过的写法

三阶段:
  REM Scan   → 30本 L3 摘要 → LLM 发现跨书规律
  Pattern Verify → 用 LLM 评分 + 商业分交叉验证规律
  Report     → Markdown 白皮书

用法: python analysis/cross_book_synthesis.py --genre 末世
"""

import json
import sys
import time
import urllib.error
import urllib.request
import yaml
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from xiaoshuo import PROJECT_ROOT
from xiaoshuo.infra.logging_config import get_logger
logger = get_logger(__name__)
# PROJECT_ROOT imported from src.xiaoshuo
OUTPUT_DIR = PROJECT_ROOT / "data" / "processed"
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def _llm_port():
    try:
        from xiaoshuo.infra.config_manager import get_config
        cfg = get_config()
        return cfg.get("analysis", {}).get("llm_port", 8000)
    except Exception:
        return 8000


def _llm_call(prompt, max_tokens=800, temperature=0.2, timeout=120):
    """Single LLM call."""
    data = json.dumps({
        "messages": [
            {"role": "system", "content": "你是网文品类研究专家。输出纯JSON，不要额外说明。"},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens, "temperature": temperature,
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
                time.sleep(3)
            else:
                print(f"  [WARN] LLM: {e}")
                return None


def _load_l3_summaries(genre):
    """Load all L3 recursive summary JSON files."""
    summary_dir = OUTPUT_DIR / genre / "summaries"
    if not summary_dir.exists():
        return []
    results = []
    for f in sorted(summary_dir.glob("*_recursive.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            l3 = data.get("l3_analysis", {})
            if l3:
                l3["_book"] = f.stem.replace("_recursive", "")[:30]
                results.append(l3)
        except (json.JSONDecodeError, KeyError):
            continue
    return results


def _load_commercial_scores(genre):
    """Load genre_synthesizer commercial scores."""
    score_path = OUTPUT_DIR / genre / "commercial_scores.json"
    if not score_path.exists():
        return {}
    try:
        data = json.loads(score_path.read_text(encoding="utf-8"))
        return {b.get("book", b.get("name", "")): b for b in data.get("books", data) if isinstance(b, dict)}
    except (json.JSONDecodeError, KeyError):
        return {}


def _load_llm_scores(genre):
    """Load llm_batch_score intensity averages per book."""
    llm_dir = OUTPUT_DIR / genre / "scores"
    if not llm_dir.exists():
        return {}
    import csv
    scores = {}
    for f in llm_dir.glob("*_llm.csv"):
        book = f.stem.replace("_llm", "")[:30]
        vals = []
        with open(f, encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                try:
                    vals.append(float(row["llm_intensity"]))
                except (KeyError, ValueError):
                    pass
        if vals:
            scores[book] = round(sum(vals) / len(vals), 1)
    return scores


# ── Phase 1: REM Scan ──

REM_PROMPT = """你是网文品类研究专家。以下30本末世小说的全书分析摘要，请发现跨书规律。

{all_summaries}

请输出JSON (只输出JSON):
{{
  "genre": "末世",
  "discoveries": [
    {{
      "id": "DISCOVERY_001",
      "pattern": "规律描述 (一句话)",
      "books": ["涉及的书名"],
      "confidence": "HIGH/MEDIUM/LOW",
      "evidence": "证据：这N本书在X维度上都呈现Y特征"
    }}
  ],
  "golden_formulas": [
    {{
      "name": "公式名 (如：铁四步开篇)",
      "description": "具体做法",
      "books_using": ["书1", "书2"],
      "avg_commercial_score": 70,
      "risk": "如果照搬的潜在风险"
    }}
  ],
  "anti_patterns": [
    {{
      "name": "反面模式名",
      "description": "为什么不行",
      "books_suffering": ["书1"]
    }}
  ],
  "grade_correlations": {{
    "top_factor": "与商业分最相关的单一维度",
    "surprise": "反直觉发现 (如：某维度高分反而商业分低)"
  }},
  "synthesis": "300字摘要：末世品类的核心写好规律"
}}"""


def rem_scan(books, genre="末世"):
    """Phase 1: LLM cross-book pattern discovery."""
    if len(books) < 5:
        return {"error": f"Need >=5 L3 summaries, got {len(books)}. Run recursive_summarize first."}

    # Build compact summaries for prompt
    parts = []
    for b in books:
        name = b.get("_book", "?")
        structure = b.get("structure_pattern", "")
        comm = b.get("commercial_assessment", {})
        score = comm.get("score_estimate", "?") if isinstance(comm, dict) else "?"
        hooks = b.get("hook_system", {})
        unresolved = hooks.get("unresolved", []) if isinstance(hooks, dict) else []
        summary = b.get("book_summary", "")[:100]
        parts.append(f"[{name}] 结构:{structure} 商业分:{score} "
                     f"未兑现伏笔:{len(unresolved) if isinstance(unresolved, list) else 0} "
                     f"摘要:{summary}")

    all_text = "\n".join(parts)
    if len(all_text) > 8000:
        all_text = all_text[:8000]

    prompt = REM_PROMPT.format(all_summaries=all_text)
    raw = _llm_call(prompt, max_tokens=1500)
    if not raw:
        return {"error": "LLM call failed"}

    import re
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return {"error": "JSON parse failed", "raw": raw[:200]}


# ── Phase 2: Pattern Verify ──

def verify_patterns(discoveries, llm_scores, commercial_scores):
    """Cross-validate REM discoveries against LLM scores and commercial scores."""
    verified = []
    for d in discoveries:
        books = d.get("books", [])
        if not books:
            d["verification"] = "no_books_referenced"
            verified.append(d)
            continue

        # Check: books cited have LLM scores?
        matched_scores = []
        for b in books:
            for k, v in llm_scores.items():
                if b[:8] in k or k[:8] in b:
                    matched_scores.append(v)
                    break
            for k, v in commercial_scores.items():
                if b[:8] in k or k[:8] in b:
                    if isinstance(v, dict):
                        matched_scores.append(v.get("score", v.get("commercial_score", 0)))

        if matched_scores:
            avg = sum(float(s) for s in matched_scores if s) / max(len(matched_scores), 1)
            d["verification"] = f"matched_books_avg_score={avg:.1f}"
        else:
            d["verification"] = "unverified"

        verified.append(d)
    return verified


# ── Phase 3: Report ──

def generate_report(data, genre, llm_scores, commercial_scores):
    """Generate Markdown white paper."""
    discoveries = data.get("discoveries", [])
    formulas = data.get("golden_formulas", [])
    anti_patterns = data.get("anti_patterns", [])
    correlations = data.get("grade_correlations", {})
    synthesis = data.get("synthesis", "")

    lines = [
        f"# 《{genre}品类写作模式白皮书》",
        f"生成: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"方法: REM跨书关联发现 + 商业分交叉验证",
        f"数据: {len(llm_scores)} 本LLM评分 + {len(commercial_scores)} 本商业评分",
        "", "---", "",
        f"## 核心洞察",
        f"{synthesis}",
        "", "---", "",
        "## 已验证的写好公式",
    ]

    if not formulas:
        lines.append("  (暂无 — 运行 recursive_summarize 后生成)")
    for f in formulas:
        lines.append(f"### {f.get('name', '?')}")
        lines.append(f"- **描述**: {f.get('description', '')}")
        lines.append(f"- **采用该书**: {', '.join(f.get('books_using', []))}")
        lines.append(f"- **平均商业分**: {f.get('avg_commercial_score', '?')}")
        lines.append(f"- **风险**: {f.get('risk', '')}")
        lines.append("")

    lines.extend(["---", "", "## 避坑：反面模式"])
    if not anti_patterns:
        lines.append("  (暂无)")
    for ap in anti_patterns:
        lines.append(f"- **{ap.get('name', '?')}**: {ap.get('description', '')}")
    lines.append("")

    lines.extend(["---", "", "## 所有发现"])
    for d in discoveries:
        conf = d.get("confidence", "?")
        icon = {"HIGH": "[STRONG]", "MEDIUM": "[OK]", "LOW": "[WEAK]"}.get(conf, "[?]")
        lines.append(f"### {icon} {d.get('pattern', '?')}")
        lines.append(f"- 涉及: {', '.join(d.get('books', []))}")
        lines.append(f"- 验证: {d.get('verification', 'N/A')}")
        lines.append(f"- 证据: {d.get('evidence', '')}")
        lines.append("")

    lines.extend(["---", "", "## 评分关联"])
    if correlations:
        lines.append(f"- **最强相关维度**: {correlations.get('top_factor', '?')}")
        lines.append(f"- **反直觉发现**: {correlations.get('surprise', '?')}")

    return lines


# ── Main ──

def run(genre="末世"):
    """Run full cross-book synthesis pipeline."""
    print(f"[CROSS-BOOK] {genre} 跨书关联发现")

    # Load data
    l3s = _load_l3_summaries(genre)
    llm_scores = _load_llm_scores(genre)
    commercial_scores = _load_commercial_scores(genre)

    print(f"  L3 summaries: {len(l3s)} books")
    print(f"  LLM scores:   {len(llm_scores)} books")
    print(f"  Commercial:   {len(commercial_scores)} books")

    if len(l3s) < 5:
        print(f"  [BLOCKED] Need >=5 L3 summaries. Run recursive_summarize.py first.")
        print(f"  python analysis/recursive_summarize.py --book all --genre {genre}")
        return {
            "error": "insufficient_data",
            "l3_count": len(l3s),
            "required": 5,
            "next_step": f"python analysis/recursive_summarize.py --book all --genre {genre}",
        }

    # Phase 1: REM scan
    print("  [Phase 1] REM Scan: discovering cross-book patterns...")
    data = rem_scan(l3s, genre)
    if "error" in data:
        print(f"  [FAIL] {data['error']}")
        return data

    discoveries = data.get("discoveries", [])
    print(f"  [Phase 1] Found {len(discoveries)} patterns")

    # Phase 2: Verify
    print("  [Phase 2] Pattern verification...")
    verified = verify_patterns(discoveries, llm_scores, commercial_scores)
    data["discoveries"] = verified
    strong = sum(1 for d in verified if d.get("verification", "").startswith("matched"))
    print(f"  [Phase 2] {strong}/{len(verified)} patterns verified against scores")

    # Phase 3: Report
    print("  [Phase 3] Generating white paper...")
    report = generate_report(data, genre, llm_scores, commercial_scores)

    report_dir = OUTPUT_DIR / genre / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{genre}_writing_patterns_whitepaper.md"
    report_path.write_text("\n".join(report), encoding="utf-8")

    json_path = report_dir / f"{genre}_cross_book_discoveries.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"  [OK] White paper: {report_path.name}")
    print(f"  [OK] JSON: {json_path.name}")
    print(f"\n[DONE] {len(discoveries)} patterns found")
    return data


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        return

    genre = "末世"
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--genre" and i < len(sys.argv) - 1:
            genre = sys.argv[i + 1]

    run(genre)


if __name__ == "__main__":
    main()
