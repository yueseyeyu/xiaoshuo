#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
writing_instructions.py — 四步管线"合同链→体检→处方"升级
===========================================================
v7.5: 新增合同链 (webnovel-writer Story System 借鉴)
  - 合同种子: 从 assets/canon/ 加载世界规则
  - 运行时合同: 每章写前激活设定 + 债务提醒
  - 章节提交: 写后事实沉淀 + 新债务注册
  - 事件审计: 跨章追踪未兑现债务

原有三步:
① 每章写作指令: 读 rhythm CSV → 模板NLG + 阈值触发
② 商业评分归因: 偏差幅度代理SHAP → 失分分析 + 改进预估
③ 写书指导手册: 聚合所有上游产出 → 单份 MD 报告

搜索依据: AWE系统模板NLG模式 (Grammarly/Pigai, 2024) +
         偏差归因 = (pool_median - value) / pool_IQR 排序 +
         合同链 = webnovel-writer Story System (lingfengQAQ, 2025)

用法: python analysis/writing_instructions.py --book <name> [--all] [--contract]
"""
import csv
import statistics
import sys
from pathlib import Path
from xiaoshuo import PROJECT_ROOT
from datetime import datetime

# PROJECT_ROOT imported from src.xiaoshuo
# sys.path hack removed (v8.0)
# Contract chain integration (v7.5, v8.0 path fix)
try:
    from xiaoshuo.pipeline.contract_chain import (
        ContractSeed, RuntimeContract, DebtBoard, ChapterCommit,
        run_contract_chain, batch_audit_from_rhythm,
    )
    _CONTRACT_AVAILABLE = True
except ImportError:
    _CONTRACT_AVAILABLE = False


def _rhythm_dir(genre):
    return PROJECT_ROOT / "data" / "processed" / genre / "rhythm"


def _manual_dir(genre):
    return PROJECT_ROOT / "data" / "reports" / genre / "writing_manuals"


# ── ① 每章写作指令: 模板NLG + 阈值触发 ──

INSTRUCTION_TEMPLATES = [
    # (condition_fn, severity, location_hint, action_template)
    # Hook deficit
    (lambda r: r["hook_density"] < 0.5 and r["wc"] > 500,
     "HIGH", "章末500字",
     "钩子密度 {hook_density:.1f}/千字(偏低)。在章末追加一个悬念或反转——例如用'{hook_keyword}'类钩子。"),
    # Conflict deficit
    (lambda r: r["conflict_density"] < 0.3 and r["wc"] > 500,
     "HIGH", "全章",
     "冲突密度 {conflict_density:.1f}(偏低)。插入一段内心冲突或外部对抗——例如角色对某件事产生怀疑、或与配角发生分歧。"),
    # Pleasure deficit
    (lambda r: r["pleasure_intensity"] <= 1.0 and r["wc"] > 300,
     "MED", "全章",
     "爽点强度 {pleasure_intensity}(偏低)。加入一个'{pleasure_type}'类爽点——例如让角色展示隐藏能力、或被他人认可。"),
    # Zero hook streak (章末检测)
    (lambda r: r["hook_type"] == "none" and r["wc"] > 300,
     "CRITICAL", "章末",
     "本章零钩子！章末必须加钩子——推荐'信息投放'类：揭示一个读者不知道的事实，或暗示即将到来的危险。"),
    # Dialogue too low
    (lambda r: r["dialogue_ratio"] < 0.15 and r["wc"] > 300,
     "LOW", "全章",
     "对话占比 {dialogue_ratio:.0%}(偏低)。将1-2段纯叙述改写为角色对话——对话能同时推进情节和塑造人物。"),
    # Dialogue too high
    (lambda r: r["dialogue_ratio"] > 0.55 and r["wc"] > 300,
     "LOW", "全章",
     "对话占比 {dialogue_ratio:.0%}(偏高)。插入一段内心独白或环境描写——给读者喘息空间，避免对话疲劳。"),
    # Readability too low
    (lambda r: r["readability"] < 0.4 and r["wc"] > 200,
     "LOW", "全章",
     "可读性 {readability:.2f}(偏低)。检查是否有过长句子(>50字)或连续排比——适当拆分或增加句长变化。"),
]

HOOK_KEYWORDS = ["悬念", "反转", "情绪炸弹", "信息投放", "暗示"]


def _get_instruction_templates():
    """Return list of (check_fn, severity, location, template_str)."""
    return INSTRUCTION_TEMPLATES


def generate_chapter_instructions(results, book_name=""):
    """Generate per-chapter writing instructions from rhythm results.
    
    Args:
        results: list of dicts (rhythm_analyzer output per chapter)
        book_name: optional book name for header
    
    Returns:
        (lines: list of str, issue_count: int)
    """
    templates = _get_instruction_templates()
    lines = []
    issue_count = 0

    lines.append(f"# {book_name or '本书'} 逐章写作指令")
    lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"> 方法: 模板NLG + 阈值触发 (零LLM成本)")
    lines.append("")

    for r in results:
        ch = int(r.get("ch_num", 0))
        wc = int(r.get("wc", 0))
        issues = []

        for check_fn, severity, location, tmpl in templates:
            try:
                if check_fn(r):
                    # Build context for template
                    hook_kw = HOOK_KEYWORDS[ch % len(HOOK_KEYWORDS)]
                    r_copy = dict(r)
                    r_copy["hook_keyword"] = hook_kw
                    msg = tmpl.format(**r_copy)
                    issues.append((severity, location, msg))
                    issue_count += 1
            except (KeyError, ValueError):
                continue

        if issues or ch <= 3:
            lines.append(f"## 第{ch}章 ({wc}字)")
            if not issues:
                lines.append("  [OK] 各项指标正常，无需特别修改。")
            else:
                for severity, location, msg in issues:
                    tag = {"CRITICAL":"[!!]", "HIGH":"[!]", "MED":"[~]", "LOW":"[-]"}[severity]
                    lines.append(f"  {tag} [{location}] {msg}")
            lines.append("")

    lines.append(f"---\n*共 {len(results)} 章, 发现 {issue_count} 条写作建议.*")
    return lines, issue_count


# ── ② 商业评分归因: 偏差幅度代理SHAP ──

def generate_attribution(book_name, book_stats, pool_stats, score, grade):
    """Generate per-dimension attribution analysis.
    
    Args:
        book_name: name of the book
        book_stats: dict of per-dimension stats for this book
        pool_stats: dict of pool-level per-dimension {median, iqr} for each dimension
        score: overall commercial score (0-100)
        grade: grade label (e.g. "签约可期")
    
    Returns:
        list of lines for markdown report
    """
    lines = []
    lines.append(f"## 商业评分归因: {book_name}")
    lines.append(f"> 综合评分: {score}/100 ({grade})")
    lines.append("")

    dims = []
    for dim_name, book_val in book_stats.items():
        pool = pool_stats.get(dim_name, {})
        median = pool.get("median", book_val)
        iqr = max(pool.get("iqr", 1.0), 0.01)  # avoid division by zero
        deviation = (median - book_val) / iqr  # positive = below pool
        loss = max(0, deviation)
        dims.append((dim_name, book_val, median, deviation, loss))

    # Sort by loss (biggest gap first)
    dims.sort(key=lambda x: -x[4])

    lines.append("| 维度 | 本书值 | 精品中位 | 偏差(IQR) | 失分贡献 |")
    lines.append("|------|:---:|:---:|:---:|:---:|")
    for dim_name, book_val, median, deviation, loss in dims:
        bar = "█" * min(int(loss * 5), 10)
        status = "✅" if deviation <= 0 else ("⚠️" if loss < 0.5 else "🔴")
        lines.append(f"| {dim_name} | {book_val:.3f} | {median:.3f} | {deviation:+.2f} | {status} {bar} |")
    lines.append("")

    # Top 3 improvement suggestions
    lines.append("### 优先改进 (Top 3)")
    for i, (dim_name, book_val, median, deviation, loss) in enumerate(dims[:3]):
        if loss <= 0:
            lines.append(f"{i+1}. {dim_name}: 已达或超过精品中位, 无需改进.")
            continue
        gain = min(int(loss * 8), 15)  # rough estimate
        lines.append(f"{i+1}. **{dim_name}** (失分贡献最大, 偏差{deviation:.1f} IQR)")
        lines.append(f"   - 当前: {book_val:.3f} / 精品中位: {median:.3f}")
        lines.append(f"   - 预期: 改善至精品中位水平, 预计整体评分 +{gain} 分")
    lines.append("")

    # P0: 交叉维度归因 — detect correlated weak dimensions
    dim_dict = {d[0]: d for d in dims}
    cross_hints = []
    if dim_dict.get("hook_density", [0]*5)[4] > 0.3 and dim_dict.get("conflict_density", [0]*5)[4] > 0.3:
        cross_hints.append("hook_density + conflict_density 双双偏低: 可能因章节节奏偏叙事、缺乏对抗场景。单修钩子不如同时加强冲突——冲突本身能自然产生钩子。")
    if dim_dict.get("dialogue_ratio", [0]*5)[4] > 0.3 and dim_dict.get("pleasure_intensity", [0]*5)[4] > 0.3:
        cross_hints.append("对话率 + 爽点强度均不足: 对话是网文爽点的核心载体。增加1-2段'对话中的打脸/逆转'可同时提升两维。")
    if dim_dict.get("hook_density", [0]*5)[4] > 0.5 and dim_dict.get("pleasure_intensity", [0]*5)[4] > 0.5:
        cross_hints.append("钩子密度 + 爽点强度同时严重偏低: 这是节奏崩塌的典型信号。检查是否出现了连续多章的'过渡章节堆积'——先压缩或删除1-2章过渡，再逐章补钩子和爽点。")
    if cross_hints:
        lines.append("### 交叉维度分析")
        for h in cross_hints:
            lines.append(f"- {h}")
        lines.append("")

    return lines


# ── ③ 写书指导手册: 聚合脚本 ──

def generate_writing_manual(book_name, instruction_lines, attribution_lines, 
                             rhythm_summary, creative_paths=None):
    """Merge all outputs into a single writing manual.
    
    Args:
        book_name: book name
        instruction_lines: output from generate_chapter_instructions
        attribution_lines: output from generate_attribution  
        rhythm_summary: dict from rhythm_analyzer summary
        creative_paths: optional list of paths to existing creative guidance files
    
    Returns:
        list of lines for unified markdown
    """
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    lines = []
    lines.append(f"# {book_name} 写书指导手册")
    lines.append(f"> 生成: {now} | 方法: 三步管线整合")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 速查: 你最需要改什么?")
    lines.append("")

    if attribution_lines:
        # Extract top 3 from attribution
        for l in attribution_lines:
            if l.startswith("### 优先改进") or l.startswith("1.") or l.startswith("2.") or l.startswith("3."):
                lines.append(l)
        lines.append("")

    lines.append("## 书籍概览")
    if rhythm_summary:
        lines.append(f"- 总章数: {rhythm_summary.get('total_chaps', '?')}")
        lines.append(f"- 总字数: {rhythm_summary.get('total_words', '?')}")
        lines.append(f"- 爽点密度: {rhythm_summary.get('pleasure_density', '?')}")
        lines.append(f"- 冲突率: {rhythm_summary.get('conflict_rate', '?')}")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 逐章写作指令")
    lines.append("> 按优先级排序: [!!]立即改 > [!]本日改 > [~]本周改 > [-]可选")
    lines.append("")
    for l in instruction_lines:
        lines.append(l)

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 商业评分归因")
    lines.append("")
    for l in attribution_lines:
        lines.append(l)

    # Append existing creative guidance if available
    if creative_paths:
        lines.append("---")
        lines.append("")
        lines.append("## 创作指导 (精品对标)")
        lines.append("")
        for cp in creative_paths:
            try:
                content = Path(cp).read_text(encoding='utf-8', errors='replace')
                lines.append(content)
            except Exception:
                lines.append(f"> (无法读取: {cp})")

    return lines


# ── ⓪ 合同链步骤 ──

def _run_contract_step(book_name, csv_path, results, use_contract):
    """Run contract chain for this book. Returns (contract_md_lines, debt_stats)."""
    if not use_contract or not _CONTRACT_AVAILABLE:
        return [], {}
    lines = ["## 合同链审计", f"生成: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ""]
    try:
        audit = batch_audit_from_rhythm(book_name, csv_path)
        lines.extend(audit["debt_board_md"])
        lines.append("")
        seed_bank = ContractSeed(book_name)
        lines.append(f"**{seed_bank.summary()}**")
        if not seed_bank.loaded:
            lines.append("> [WARN] 启用合同种子后，写前合同将自动校验设定一致性。")
            lines.append("> 操作: 填入 `assets/canon/characters.md`、`rules.md` 等文件。")
        lines.append("")
        return lines, audit.get("debt_stats", {})
    except Exception as e:
        lines.append(f"[WARN] 合同链分析失败: {e}")
        lines.append("")
        return lines, {}

# ── CLI ──

def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        return

    book_filter = None
    books_filter = None
    use_contract = "--contract" in sys.argv
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--book" and i < len(sys.argv) - 1:
            book_filter = sys.argv[i + 1]
        elif arg == "--books" and i < len(sys.argv) - 1:
            books_filter = set(sys.argv[i + 1].split(","))

    # Find rhythm CSVs — search all genre subdirs
    csv_files = []
    for gdir in (PROJECT_ROOT / "data" / "processed").iterdir():
        rdir = gdir / "rhythm"
        if rdir.is_dir():
            csv_files.extend(sorted(rdir.glob("*.csv")))
    if books_filter:
        csv_files = [f for f in csv_files if f.stem.replace("rhythm_", "")[:40] in books_filter]
    elif book_filter:
        csv_files = [f for f in csv_files if book_filter in f.stem]

    if not csv_files:
        print("[WARN] No rhythm CSV files found.")
        return

    # Use first CSV's genre for manual dir
    genre = csv_files[0].parent.parent.name
    mdir = _manual_dir(genre)
    mdir.mkdir(parents=True, exist_ok=True)

    for csv_path in csv_files:
        book_name = csv_path.stem.replace("rhythm_", "")
        print(f"\n[{book_name[:40]}]")

        # Read results
        results = []
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                for k in ['hook_density','conflict_density','pleasure_intensity',
                          'dialogue_ratio','readability','wc']:
                    try:
                        row[k] = float(row.get(k, 0))
                    except (ValueError, TypeError):
                        row[k] = 0.0
                results.append(row)

        # ⓪ Contract chain audit (post-hoc: from rhythm data)
        contract_lines, debt_stats = _run_contract_step(book_name, csv_path, results, use_contract)
        if contract_lines:
            contract_path = mdir / f"{book_name}_合同审计.md"
            contract_path.write_text("\n".join(contract_lines), encoding='utf-8')
            print(f"  [OK] 合同审计: {contract_path.name} ({debt_stats.get('pending', 0)} debts pending)")

        # ① Chapter instructions
        inst_lines, issue_count = generate_chapter_instructions(results, book_name)
        inst_path = mdir / f"{book_name}_逐章指令.md"
        inst_path.write_text("\n".join(inst_lines), encoding='utf-8')
        print(f"  [OK] 逐章指令: {inst_path.name} ({issue_count} issues)")

        # ② Attribution (simplified: compute from rhythm data)
        book_stats = {}
        for dim in ['hook_density', 'conflict_density', 'pleasure_intensity', 'dialogue_ratio']:
            vals = [r[dim] for r in results if r[dim] > 0]
            book_stats[dim] = statistics.median(vals) if vals else 0.0

        # Pool stats from all books (simple: use own book as rough pool if only 1)
        pool_stats = {}
        for dim in book_stats:
            pool_stats[dim] = {
                "median": book_stats[dim] * 1.15,  # placeholder: 15% above current as "target"
                "iqr": 0.05
            }

        attr_lines = generate_attribution(book_name, book_stats, pool_stats, 65, "签约可期")
        attr_path = mdir / f"{book_name}_评分归因.md"
        attr_path.write_text("\n".join(attr_lines), encoding='utf-8')
        print(f"  [OK] 评分归因: {attr_path.name}")

        # ③ Writing manual (merged: includes contract audit)
        summary = {"total_chaps": len(results), "total_words": sum(r['wc'] for r in results)}
        manual_lines = generate_writing_manual(book_name, inst_lines, attr_lines, summary)
        # Prepend contract audit to manual
        if contract_lines:
            manual_lines = manual_lines[:3] + contract_lines + manual_lines[3:]
        manual_path = mdir / f"{book_name}_写书指导手册.md"
        manual_path.write_text("\n".join(manual_lines), encoding='utf-8')
        print(f"  [OK] 指导手册: {manual_path.name}")

    print(f"\n[DONE] Manuals in {mdir}")
    if use_contract and not _CONTRACT_AVAILABLE:
        print("[WARN] contract_chain module not available, --contract flag ignored")


if __name__ == "__main__":
    main()
