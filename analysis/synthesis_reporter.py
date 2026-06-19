#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
synthesis_reporter.py — 合成报告生成器
========================================
从 genre_synthesizer.py 中提取的报告生成函数。
生成: rhythm_benchmark.md (自动基准) + cross_genre_comparison.md (跨题材对比)
"""
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def auto_benchmark(synth, analyses, output_dir):
    """Auto-generate rhythm_benchmark.md from synthesis data.
    Skills (rough-outline/chapter evolution) read this file during SAMPLE-DB step."""
    seg = synth["segment_comparison"]
    cp = synth["common_patterns"]
    opening = seg.get("开篇(1-10%)", {})
    early = seg.get("前期(10-30%)", {})
    mid = seg.get("中期(30-60%)", {})
    late = seg.get("后期(60-85%)", {})
    ending = seg.get("结局(85-100%)", {})

    lines = [
        "# 网文节奏基准库（自动生成）",
        f"> 源: genre_synthesizer.py v8 · {synth['book_count']}本末世火书 · {synth['total_chapters']}章",
        f"> 更新: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "> ⚠️ 本文件由 genre_synthesizer.py 自动生成，勿手动编辑",
        "",
        "## 题材: 末世",
        f"- 火书数: {synth['book_count']} · 总章节: {synth['total_chapters']}",
        f"- 钩子范围: {cp['hook_avg_range']} | 冲突范围: {cp['conflict_avg_range']}",
        f"- **零钩子弃书红线**: ≤{cp['max_zero_hook_streak']}章",
        "",
        "## 按章节位置索引",
        "| 位置 | hook_pooled | conflict_pooled | 爽点均值 | pace主流 | 主流爽点 |",
        "|------|:---:|:---:|:---:|------|------|",
        f"| 开篇(1-10%) | {opening.get('hook_pooled','-')} | {opening.get('conflict_pooled','-')} | {opening.get('pleasure_pooled','-')} | {_safe_pace(opening)} | {_safe_pleasure(opening)} |",
        f"| 前期(10-30%) | {early.get('hook_pooled','-')} | {early.get('conflict_pooled','-')} | {early.get('pleasure_pooled','-')} | {_safe_pace(early)} | {_safe_pleasure(early)} |",
        f"| 中期(30-60%) | {mid.get('hook_pooled','-')} | {mid.get('conflict_pooled','-')} | {mid.get('pleasure_pooled','-')} | {_safe_pace(mid)} | {_safe_pleasure(mid)} |",
        f"| 后期(60-85%) | {late.get('hook_pooled','-')} | {late.get('conflict_pooled','-')} | {late.get('pleasure_pooled','-')} | {_safe_pace(late)} | {_safe_pleasure(late)} |",
        f"| 结局(85-100%) | {ending.get('hook_pooled','-')} | {ending.get('conflict_pooled','-')} | {ending.get('pleasure_pooled','-')} | {_safe_pace(ending)} | {_safe_pleasure(ending)} |",
        "",
        "## 商业基准",
    ]

    for a in analyses:
        comm = a.get("commercial", {})
        if comm and isinstance(comm.get("overall"), int):
            lines.append(f"- {a['name'][:20]}: 签约{comm['overall']}分 · {comm.get('grade','-')}")

    target = output_dir / "rhythm_benchmark.md"
    target.write_text("\n".join(lines), encoding='utf-8')
    print(f"[OK] Auto-benchmark: {target}")


def cross_genre_summary(genre_results):
    """Generate cross-genre comparison report from dict of {genre: (synth, output_dir)}."""
    lines = [
        "# 跨题材对比报告",
        f"\n> 自动生成 · {datetime.now().strftime('%Y-%m-%d')} · {len(genre_results)}个题材",
        "\n## 各题材商业评分对比\n",
        "| 题材 | 书籍数 | 平均hook | 平均冲突 | 平均爽点 |",
        "|------|:---:|:---:|:---:|:---:|",
    ]
    for genre, (synth, _) in genre_results.items():
        if not synth:
            continue
        lines.append(
            f"| {genre} | {synth.get('book_count','?')} | "
            f"{synth.get('avg_hook','?')} | {synth.get('avg_conflict','?')} | "
            f"{synth.get('avg_pleasure','?')} |")
    lines.append("\n## 写作建议\n- 同一题材书籍越多,基准越可靠\n- 差异过大的题材可能需要不同创作策略")
    out = PROJECT_ROOT / "data" / "reports" / "cross_genre_comparison.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding='utf-8')
    print(f"\n[CROSS-GENRE] 跨题材对比报告: {out}")


def _safe_pace(segment):
    """Safely extract dominant pace from segment dict."""
    paces = segment.get("dominant_paces", [["?", 0]])
    return paces[0][0] if paces else "?"


def _safe_pleasure(segment):
    """Safely extract top pleasure type from segment dict."""
    pts = segment.get("top_pleasure_types", [["?", 0]])
    return pts[0][0] if pts else "?"