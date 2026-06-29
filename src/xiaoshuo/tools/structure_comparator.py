#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
structure_comparator.py v1 — 新人结构层 vs 精品基准对比引擎
============================================================
解决P0-1缺口: 对比新人作者的"世界观/粗纲/细纲/角色"与30本精品数据。

模式:
  --mode worldbuild  : 世界观对比
  --mode outline      : 粗纲/细纲对比
  --mode characters   : 角色对比
  --mode all          : 全部三项 (默认)

输入: 作者内容文件 (--file, markdown/纯文本)
基准: creative_bridge JSON + rhythm CSV池
输出: 差距分析报告 + JSON结果

用法:
  python analysis/structure_comparator.py --file my_world.md --mode worldbuild
  python analysis/structure_comparator.py --file my_outline.md --mode outline
  python analysis/structure_comparator.py --file my_chars.md --mode characters
  python analysis/structure_comparator.py --file my_all.md --mode all
"""
import csv
import json
import re
import statistics
import sys
from pathlib import Path
from collections import Counter
from datetime import datetime
from xiaoshuo.infra.config_manager import get_config
from xiaoshuo.infra.logging_config import get_logger
logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
OUTPUT_DIR = PROJECT_ROOT / "data" / "reports"


def _load_cfg():
    """Load structure_comparator section from config.yaml. Returns defaults on failure."""
    defaults = {
        "score_gap_thresholds": {"small": 90, "medium": 70},
        "max_input_bytes": 5 * 1024 * 1024,
        "elite_factions_floor": 3,
    }
    if not CONFIG_PATH.exists():
        return defaults
    try:
        cfg = get_config()
        sc = cfg.get("structure_comparator", {})
        return {
            "score_gap_thresholds": sc.get("score_gap_thresholds", defaults["score_gap_thresholds"]),
            "max_input_bytes": sc.get("max_input_bytes", defaults["max_input_bytes"]),
            "elite_factions_floor": sc.get("elite_factions_floor", defaults["elite_factions_floor"]),
        }
    except Exception as e:
        logger.warning(f"[WARN] config.yaml 读取失败, 使用默认值: {e}")
        return defaults


_SC_CFG = _load_cfg()


def _get_default_genre():
    try:
        cfg = get_config()
        genres = cfg.get("author", {}).get("genres", ["末世"])
        return genres[0] if genres else "末世"
    except Exception as e:
        print(f"[WARN] 配置加载失败(使用默认末世): {e}")
    return "末世"


# ── Keyword dictionaries for qualitative feature extraction ──

CONFLICT_TYPE_KW = {
    "羁绊": ["羁绊", "守护", "并肩", "牺牲", "同伴", "队友", "兄弟", "家人", "羁", "牵绊"],
    "打脸": ["打脸", "碾压", "装逼", "逆袭", "扮猪吃虎", "低调", "震惊", "打脸流"],
    "突破": ["突破", "升级", "进化", "觉醒", "晋升", "变强", "瓶颈"],
    "认知突破": ["顿悟", "领悟", "明悟", "发现真相", "揭密", "秘密", "认知"],
    "牺牲": ["牺牲", "舍身", "献祭", "付出代价", "代价"],
    "复仇": ["复仇", "报仇", "血债", "恨", "仇人"],
}

ARC_TYPE_KW = {
    "上升弧": ["上升", "成长", "变强", "崛起", "升级", "进阶"],
    "下降弧": ["堕落", "黑化", "沉沦", "悲剧", "下行"],
    "O型弧": ["回归", "归来", "重返", "原点", "循环", "周而复始"],
}

CHARACTER_TYPE_KW = {
    "主角": ["主角", "主人公", "男主", "女主"],
    "对手": ["反派", "对手", "敌人", "宿敌", "boss"],
    "盟友": ["盟友", "同伴", "伙伴", "队友", "兄弟", "朋友"],
    "导师": ["导师", "师傅", "师父", "老师", "前辈", "引路人"],
    "羁绊角色": ["羁绊角色", "重要关系", "老婆", "老公", "恋人", "亲情"],
}

PLEASURE_TYPE_KW = {
    "羁绊": ["羁绊", "守护", "并肩", "牺牲", "羁"],
    "打脸": ["打脸", "碾压", "装逼", "扮猪", "低调出手"],
    "突破": ["突破", "升级", "进化", "觉醒", "晋升"],
    "认知突破": ["顿悟", "领悟", "发现真相", "揭密"],
    "牺牲": ["牺牲", "舍身", "献祭", "代价"],
    "复仇": ["复仇", "报仇"],
}


# ── Benchmark loading ──

def _score_to_gap(score):
    """Convert numeric score to gap label using config thresholds."""
    t = _SC_CFG["score_gap_thresholds"]
    if score >= t["small"]:
        return "small"
    elif score >= t["medium"]:
        return "medium"
    else:
        return "large"


def _load_guidance_json(genre="末世"):
    # Prefer fresh output from creative_bridge (directly under genre/),
    # fall back to creative_guidance/ subdir
    fresh_path = OUTPUT_DIR / genre / f"{genre}_创作指导.json"
    legacy_path = OUTPUT_DIR / genre / "creative_guidance" / f"{genre}_创作指导.json"
    for path in [fresh_path, legacy_path]:
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
    return None


def _load_rhythm_pool(genre="末世"):
    rhythm_dir = PROJECT_ROOT / "data" / "processed" / genre / "rhythm"
    if not rhythm_dir.exists():
        return None
    all_rows = []
    for csv_path in sorted(rhythm_dir.glob("rhythm_*.csv")):
        try:
            with open(csv_path, 'r', encoding='utf-8-sig') as f:
                all_rows.extend(list(csv.DictReader(f)))
        except (csv.Error, UnicodeDecodeError) as e:
            print(f"[WARN] CSV读取失败 {csv_path.name}: {e}")
    return all_rows


# ── Feature extraction ──

def _count_keywords(text, kw_dict):
    """Count occurrences of each category in text."""
    result = {}
    text_lower = text.lower()
    for category, keywords in kw_dict.items():
        count = 0
        for kw in keywords:
            count += len(re.findall(re.escape(kw), text))
        result[category] = count
    return result


def _extract_numbers(text, patterns):
    """Extract first matching number for each named pattern."""
    result = {}
    for name, pat in patterns.items():
        m = re.search(pat, text)
        if m:
            try:
                result[name] = float(m.group(1))
            except (ValueError, IndexError):
                pass
    return result


def _extract_text_sections(text):
    """Split text into labelled sections (## Section Title)."""
    sections = {}
    current_title = "_header"
    current_content = []
    for line in text.split('\n'):
        if line.startswith('## '):
            if current_content:
                sections[current_title] = '\n'.join(current_content).strip()
            current_title = line[3:].strip()
            current_content = []
        else:
            current_content.append(line)
    if current_content:
        sections[current_title] = '\n'.join(current_content).strip()
    return sections


# ── Mode 1: Worldbuilding comparison ──

def compare_worldbuilding(text, guidance, rhythm_pool):
    """Compare author's worldbuilding against elite benchmarks."""
    g = guidance or {}
    wb = g.get("worldbuilding", {})
    results = []

    # 1.1 Conflict type coverage
    author_conflicts = _count_keywords(text, CONFLICT_TYPE_KW)
    dominant_conflicts = wb.get("dominant_conflict_types", [])
    elite_types = {item["type"]: item["pct"] for item in dominant_conflicts}

    author_active = {k for k, v in author_conflicts.items() if v > 0}
    top_elite = set(k for k, _ in sorted(elite_types.items(), key=lambda x: -x[1])[:3])
    covered = author_active & top_elite
    coverage_score = min(100, int(len(covered) / max(len(top_elite), 1) * 100))

    results.append({
        "dim": "冲突类型覆盖",
        "author": f"涉及: {', '.join(sorted(author_active)) if author_active else '(未检测到)'}",
        "elite": f"精品Top3: {', '.join(sorted(top_elite))}",
        "score": coverage_score,
        "gap": _score_to_gap(coverage_score),
        "suggestion": (
            f"精品主流冲突为{', '.join(sorted(top_elite))}, "
            f"你的世界观只覆盖了{len(covered)}/{len(top_elite)}种。"
            f"建议补充{'、'.join(top_elite - covered)}相关的世界规则"
        ) if covered != top_elite else "冲突类型全覆盖, 世界规则健全",
    })

    # 1.2 Power system / faction count
    faction_count = len(re.findall(r'势力|阵营|组织|宗门|基地|避难所|国家', text))
    # TODO: Replace heuristic with LLM-based faction extraction from text.
    # quality_manifest.json lacks faction_count field; rhythm CSVs only tag
    # dominant_sub (爽点子类型) not faction names. Until faction-extraction
    # pass is added, estimate from conflict types (each type ≈ 1.5 factions).
    conflict_types = wb.get("dominant_conflict_types", [])
    elite_factions = max(_SC_CFG["elite_factions_floor"], round(len(conflict_types) * 1.5))
    faction_score = min(100, int(faction_count / max(elite_factions, 1) * 100)) if faction_count <= elite_factions else 100
    results.append({
        "dim": "势力丰富度",
        "author": f"检测到约{faction_count}个势力/阵营",
        "elite": f"精品均值约{elite_factions}个(基于{len(conflict_types)}种冲突类型估算)",
        "score": faction_score,
        "gap": "large" if faction_count < 2 else ("medium" if faction_count < 4 else "small"),
        "suggestion": (
            "势力过少, 冲突维度单一" if faction_count < 2
            else "势力数量合理" if faction_count >= 4
            else f"建议增至{elite_factions}个左右, 引入更多利益冲突"
        ),
    })

    # 1.3 Arc type alignment
    arc_counts = _count_keywords(text, ARC_TYPE_KW)
    max_arc = max(arc_counts, key=arc_counts.get) if any(arc_counts.values()) else "未知"
    arc_dist = wb.get("arc_distribution", {})
    elite_main_arc = max(arc_dist, key=arc_dist.get) if arc_dist else "上升弧"
    arc_score = 100 if max_arc == elite_main_arc else (70 if any(arc_counts.values()) else 30)
    results.append({
        "dim": "弧线类型对齐",
        "author": f"主要弧线: {max_arc}",
        "elite": f"精品主流: {elite_main_arc}({arc_dist.get(elite_main_arc, '?')}本)",
        "score": arc_score,
        "gap": _score_to_gap(arc_score),
        "suggestion": (
            f"你的弧线({max_arc})与精品主流({elite_main_arc})一致" if max_arc == elite_main_arc
            else f"建议考虑{elite_main_arc}为主弧线(精品{arc_dist.get(elite_main_arc, '?')}本采用)"
        ),
    })

    # 1.4 Opening hook benchmark
    hook_bench = wb.get("opening_hook_benchmark", 2.0)
    hook_nums = _extract_numbers(text, {"钩子密度": r'钩子密度[：:]\s*([\d.]+)'})
    author_hook = hook_nums.get("钩子密度")
    if author_hook:
        hook_score = min(100, int(author_hook / max(hook_bench, 0.01) * 100))
        results.append({
            "dim": "开篇钩子密度",
            "author": f"声明: {author_hook:.2f}",
            "elite": f"精品基准: {hook_bench:.2f}",
            "score": hook_score,
            "gap": _score_to_gap(hook_score),
            "suggestion": (
                "钩子密度达标" if hook_score >= 80
                else f"钩子密度偏低, 精品均值{hook_bench:.2f}, 建议每章结尾增设悬念/反转"
            ),
        })

    return results


# ── Mode 2: Outline comparison ──

def compare_outline(text, guidance, rhythm_pool):
    """Compare author's outline against elite rhythm benchmarks.

    Note: rhythm_pool is currently unused (outline comparison uses guidance JSON's
    pct_benchmarks). Reserved for future rhythm-based chapter-level comparison.
    """
    _ = rhythm_pool  # explicitly unused for now
    g = guidance or {}
    ro = g.get("rough_outline", {})
    co = g.get("chapter_outline", {})
    pp = g.get("plot_progression", {})
    results = []

    # 2.1 Chapter count
    nums = _extract_numbers(text, {
        "总章数": r'总章数[：:]\s*(\d+)',
        "计划章数": r'(?:计划|预计|目标).*?(\d+)\s*章',
        "章节数": r'章节[数总][：:]\s*(\d+)',
    })
    author_ch = nums.get("总章数") or nums.get("计划章数") or nums.get("章节数")
    elite_ch = ro.get("chapter_avg", 1291)
    if author_ch:
        ch_ratio = author_ch / max(elite_ch, 1)
        ch_score = 100 if 0.5 < ch_ratio < 2.0 else (70 if 0.3 < ch_ratio < 3.0 else 40)
        results.append({
            "dim": "总章数",
            "author": f"计划{int(author_ch)}章",
            "elite": f"精品均值{elite_ch}章",
            "score": ch_score,
            "gap": _score_to_gap(ch_score),
            "suggestion": (
                "章数在精品范围" if ch_score >= 80
                else f"章数({'偏少' if author_ch < elite_ch else '偏多'}), 精品均值{elite_ch}章"
            ),
        })

    # 2.2 Opening strength (0-10% benchmarks)
    pct_bm = ro.get("pct_benchmarks", {})
    opening = pct_bm.get("10%") or pct_bm.get("20%") or {}
    if opening and rhythm_pool:
        opening_hook = opening.get("hook_mean", 2.0)
        opening_conflict = opening.get("conflict_mean", 1.0)

        author_nums = _extract_numbers(text, {
            "开篇钩子": r'开篇.*?钩子[：:]\s*([\d.]+)',
            "开篇冲突": r'开篇.*?冲突[：:]\s*([\d.]+)',
        })
        if author_nums.get("开篇钩子"):
            opening_hook_score = min(100, int(author_nums["开篇钩子"] / max(opening_hook, 0.01) * 100))
            results.append({
                "dim": "黄金三章-钩子",
                "author": f"钩子密度: {author_nums['开篇钩子']}",
                "elite": f"精品均值: {opening_hook}",
                "score": opening_hook_score,
                "gap": _score_to_gap(opening_hook_score),
                "suggestion": "开篇钩子密度达标" if author_nums["开篇钩子"] >= opening_hook
                else f"开篇钩子偏低(精品{opening_hook}), 黄金三章需强化悬念",
            })

    # 2.3 Midpoint crisis (40-60%)
    midpoint = pct_bm.get("50%") or pct_bm.get("40%") or {}
    if midpoint:
        mid_conflict = midpoint.get("conflict_mean", 1.0)
        mid_pleasure = midpoint.get("pleasure_mean", 2.0)

        author_nums = _extract_numbers(text, {
            "中期冲突": r'中期.*?冲突[：:]\s*([\d.]+)',
            "中期爽点": r'中期.*?爽点[：:]\s*([\d.]+)',
        })
        if author_nums.get("中期冲突"):
            mid_score = min(100, int(author_nums["中期冲突"] / max(mid_conflict, 0.01) * 100))
            results.append({
                "dim": "中期冲突峰值",
                "author": f"冲突密度: {author_nums['中期冲突']}",
                "elite": f"精品均值: {mid_conflict}",
                "score": mid_score,
                "gap": _score_to_gap(mid_score),
                "suggestion": "中期冲突达标" if author_nums["中期冲突"] >= mid_conflict
                else f"中期冲突不足(精品{mid_conflict}), 建议增设卷级高潮",
            })

    # 2.4 Pacing curve match
    total_ch = author_ch if author_ch else 1000
    pace_hint = re.search(r'节奏[：:]\s*(.{1,20})', text)
    pace_type = pace_hint.group(1).strip() if pace_hint else "未声明"
    pace_score = 70  # neutral baseline
    results.append({
        "dim": "节奏规划",
        "author": f"节奏类型: {pace_type}",
        "elite": f"精品节奏: conflict递增, 80%达峰值{_s(midpoint.get('conflict_mean', '?'))}",
        "score": pace_score,
        "gap": _score_to_gap(pace_score),
        "suggestion": "建议在进度80%处设置冲突峰值(参照精品数据)",
    })

    return results


# ── Mode 3: Character comparison ──

def compare_characters(text, guidance, rhythm_pool):
    """Compare author's character design against elite benchmarks."""
    g = guidance or {}
    chg = g.get("character", {})
    results = []

    # 3.1 Arc type coverage
    arc_counts = _count_keywords(text, ARC_TYPE_KW)
    author_arcs = [k for k, v in arc_counts.items() if v > 0]
    elite_arcs = list(chg.get("arc_types", {}).keys())
    arc_overlap = set(author_arcs) & set(elite_arcs) if elite_arcs else set()
    arc_score = min(100, int(len(arc_overlap) / max(len(elite_arcs), 1) * 100)) if elite_arcs else 70

    results.append({
        "dim": "角色弧线多样性",
        "author": f"涉及弧线: {', '.join(author_arcs) if author_arcs else '(未检测到)'}",
        "elite": f"精品分布: {', '.join(f'{k}({v}本)' for k, v in chg.get('arc_types', {}).items())}",
        "score": arc_score,
        "gap": _score_to_gap(arc_score),
        "suggestion": (
            "弧线类型覆盖良好" if arc_score >= 70
            else "建议增加多种弧线类型(上升/下降/O型)丰富角色层次"
        ),
    })

    # 3.2 Emotional range
    er = chg.get("emotional_range", {})
    v_swing = er.get("V_swing", 0.05)
    author_nums = _extract_numbers(text, {
        "情感摆动": r'(?:情感|情绪|V).*?(?:摆动|swing|幅度)[：:]\s*([\d.]+)',
    })
    if author_nums.get("情感摆动"):
        swing_val = author_nums["情感摆动"]
        swing_score = min(100, int(swing_val / max(v_swing, 0.01) * 100))
        results.append({
            "dim": "情感摆动幅度",
            "author": f"V摆动: {swing_val}",
            "elite": f"精品均值: {v_swing}",
            "score": swing_score,
            "gap": _score_to_gap(swing_score),
            "suggestion": (
                "情感摆动达标, 角色旅程有张力" if swing_score >= 70
                else f"情感摆动不足(精品{v_swing}), 建议增加更多情感起伏"
            ),
        })

    # 3.3 Bond character ratio
    bond_pct = chg.get("bond_ratio", 40)
    bond_count = _count_keywords(text, CHARACTER_TYPE_KW).get("羁绊角色", 0)
    char_counts = _count_keywords(text, CHARACTER_TYPE_KW)
    total_char_refs = sum(char_counts.values())
    if total_char_refs > 0:
        author_bond_rate = round(bond_count / total_char_refs * 100, 1)
        bond_score = min(100, int(author_bond_rate / max(bond_pct, 1) * 100)) if author_bond_rate <= bond_pct else 100
        results.append({
            "dim": "羁绊角色占比",
            "author": f"羁绊提及率: {author_bond_rate}%",
            "elite": f"精品羁绊爽点: 约{bond_pct}%",
            "score": bond_score,
            "gap": _score_to_gap(bond_score),
            "suggestion": (
                "羁绊角色比例合理" if bond_score >= 60
                else f"建议增加羁绊角色(精品{bond_pct}%), 末世中守护/并肩是重要爽点源"
            ),
        })

    # 3.4 Role diversity
    role_counts = {k: v for k, v in char_counts.items() if k in ["主角", "对手", "导师", "盟友"]}
    roles_present = [k for k, v in role_counts.items() if v > 0]
    min_roles = 3
    role_score = min(100, int(len(roles_present) / min_roles * 100))
    results.append({
        "dim": "角色类型覆盖",
        "author": f"检测到: {', '.join(roles_present) if roles_present else '(未检测到)'}",
        "elite": "精品标配: 主角+对手+导师+盟友",
        "score": role_score,
        "gap": _score_to_gap(role_score),
        "suggestion": (
            "核心角色类型齐全" if role_score >= 80
            else f"缺少{'、'.join(set(['主角', '对手', '导师', '盟友']) - set(roles_present))}等核心角色类型"
        ),
    })

    return results


# ── Report generation ──

def _s(v):
    """Safe str conversion."""
    return str(v) if v is not None else "?"


def generate_report(mode, results, genre):
    """Generate gap analysis report (markdown + JSON)."""
    if not results:
        return None

    total = len(results)
    avg_score = round(statistics.mean([r["score"] for r in results]), 1)
    large_gaps = [r for r in results if r["gap"] == "large"]
    medium_gaps = [r for r in results if r["gap"] == "medium"]

    # Priority: large gaps first, then medium, by score ascending
    prioritized = sorted(results, key=lambda r: (0 if r["gap"] == "large" else (1 if r["gap"] == "medium" else 2), r["score"]))

    mode_labels = {
        "worldbuild": "世界观",
        "outline": "大纲",
        "characters": "角色",
        "all": "全维度",
    }
    label = mode_labels.get(mode, mode)

    report = {
        "mode": mode,
        "genre": genre,
        "generated": datetime.now().isoformat(),
        "total_gaps": total,
        "large_gaps": len(large_gaps),
        "medium_gaps": len(medium_gaps),
        "avg_score": avg_score,
        "verdict": (
            "结构良好, 与精品基准高度一致" if avg_score >= 80
            else "基本合格, 部分维度需要调整" if avg_score >= 60
            else "存在较大差距, 建议重点修改"
        ),
        "results": results,
    }

    # Markdown
    md = [
        f"# {genre}类 {label}对比评估报告",
        f"\n> 生成时间: {report['generated'][:19]} | 总分: {avg_score}/100 | {report['verdict']}",
        f"> {len(large_gaps)}个严重差距 | {len(medium_gaps)}个中等差距\n",
    ]

    # Summary table
    md.append("## 维度得分总览\n")
    md.append("| 优先级 | 维度 | 得分 | 差距 |")
    md.append("|--------|------|------|------|")
    for i, r in enumerate(prioritized):
        gap_icon = "[FAIL]" if r["gap"] == "large" else ("[WARN]" if r["gap"] == "medium" else "[OK]")
        md.append(f"| {i+1} | {r['dim']} | {r['score']} | {gap_icon} |")

    md.append("\n---\n")

    # Detailed gaps
    if large_gaps or medium_gaps:
        md.append("## 需要修改的维度\n")
        for r in prioritized:
            if r["gap"] in ("large", "medium"):
                gap_tag = "**严重**" if r["gap"] == "large" else "中等"
                md.append(f"### {r['dim']} [{gap_tag}] — 得分 {r['score']}/100\n")
                md.append(f"- **你的情况**: {r['author']}")
                md.append(f"- **精品基准**: {r['elite']}")
                md.append(f"- **建议**: {r['suggestion']}\n")

    # Good dimensions
    good = [r for r in results if r["gap"] == "small"]
    if good:
        md.append("## 达标维度\n")
        for r in good:
            md.append(f"- **{r['dim']}** (得分{r['score']}): {r['suggestion']}")

    md.append(f"\n---\n*v1 · {report['generated'][:19]}*")

    md_text = "\n".join(md)
    return {"json": report, "md": md_text}


# ── Main CLI ──

def main():
    import argparse
    parser = argparse.ArgumentParser(description="结构层对比引擎 v1")
    parser.add_argument("--file", required=True, help="作者内容文件路径 (.md/.txt)")
    parser.add_argument("--mode", default="all",
                        choices=["worldbuild", "outline", "characters", "all"],
                        help="对比模式 (default: all)")
    parser.add_argument("--genre", default=None, help="题材 (default: config.yaml author.genres[0])")
    parser.add_argument("--output", default=None, help="输出文件前缀 (default: 自动生成)")
    args = parser.parse_args()

    genre = args.genre or _get_default_genre()
    file_path = Path(args.file)
    if not file_path.exists():
        print(f"[FAIL] 文件不存在: {file_path}")
        sys.exit(1)
    # Guard: reject oversized inputs (max from config.yaml)
    max_input = _SC_CFG["max_input_bytes"]
    try:
        st_size = file_path.stat().st_size
    except OSError as e:
        print(f"[FAIL] 无法读取文件信息: {file_path} — {e}")
        sys.exit(1)
    if st_size > max_input:
        print(f"[FAIL] 文件过大({st_size}字节 > {max_input}), 请拆分为多个文件提交")
        sys.exit(1)

    try:
        text = file_path.read_text(encoding='utf-8')
    except UnicodeDecodeError as e:
        print(f"[FAIL] 文件编码错误(需UTF-8): {file_path} — {e}")
        sys.exit(1)
    guidance = _load_guidance_json(genre)
    rhythm_pool = _load_rhythm_pool(genre)

    if not guidance:
        print(f"[WARN] 未找到{genre}类创作指导JSON, 部分对比将降级")
    if not rhythm_pool:
        print(f"[WARN] 未找到{genre}类rhythm数据, 部分对比将降级")

    modes_to_run = ["worldbuild", "outline", "characters"] if args.mode == "all" else [args.mode]

    all_results = []
    for mode in modes_to_run:
        if mode == "worldbuild":
            all_results.extend(compare_worldbuilding(text, guidance, rhythm_pool))
        elif mode == "outline":
            all_results.extend(compare_outline(text, guidance, rhythm_pool))
        elif mode == "characters":
            all_results.extend(compare_characters(text, guidance, rhythm_pool))

    report = generate_report(args.mode, all_results, genre)
    if not report:
        print("[FAIL] 无可输出的对比结果")
        return

    # Output
    out_prefix = args.output or f"{genre}_结构对比_{args.mode}"
    # Sanitize: strip path separators to prevent directory traversal
    safe_prefix = Path(out_prefix).name or out_prefix.replace("/", "_").replace("\\", "_")
    out_dir = OUTPUT_DIR / genre / "structure_eval"
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / f"{safe_prefix}.json"
    md_path = out_dir / f"{safe_prefix}.md"

    json_path.write_text(json.dumps(report["json"], ensure_ascii=False, indent=2), encoding='utf-8')
    md_path.write_text(report["md"], encoding='utf-8')
    print(f"[OK] JSON: {json_path}")
    print(f"[OK] MD: {md_path}")

    # Console summary
    print(f"\n{'='*50}")
    print(f"  {genre}类 {args.mode} 对比评估")
    print(f"  总分: {report['json']['avg_score']}/100")
    print(f"  严重差距: {report['json']['large_gaps']} | 中等差距: {report['json']['medium_gaps']}")
    print(f"  {report['json']['verdict']}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()