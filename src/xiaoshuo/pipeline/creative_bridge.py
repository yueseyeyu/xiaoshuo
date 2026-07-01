#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
creative_bridge.py v2 — 分析→创作桥接 (JSON+Markdown双输出)
===========================================================
v1→v2 改进:
  - P0-1: 精确 novel_index.json 映射 (不再用 [:8] 模糊匹配)
  - P0-2: 双格式输出 creative_guidance.json + creative_guidance.md
  - P1-4: 跨书分析按进度%分桶归一化
  - P1-1: rule_translator 指标→规则→动作翻译层
  - P1-3: 反套路模块 (KL散度 + 低频高完读特征)
  - P1-5: 置信度声明 + 相关/因果标注
  - QUARANTINE 感知: quarantined 书籍纳入分析做边缘案例参考

输出: data/reports/{genre}/creative_guidance/{genre}_创作指导.md
      data/reports/{genre}/creative_guidance/{genre}_创作指导.json

用法: python analysis/creative_bridge.py [--genre 末世]
"""
import csv
import json
import math
import re
import statistics
import sys
from pathlib import Path
from xiaoshuo import PROJECT_ROOT
from xiaoshuo.infra.logging_config import get_logger
from xiaoshuo.pipeline.paths import rhythm_dir as _rhythm_dir
from xiaoshuo.pipeline.metrics_schema import ChapterMetrics
logger = get_logger(__name__)
from collections import Counter
from datetime import datetime

# PROJECT_ROOT imported from src.xiaoshuo
INDEX_PATH = PROJECT_ROOT / "data" / "raw" / "novel_index.json"
CONFIG_PATH = PROJECT_ROOT / "config.yaml"




def _manifest_path(genre):
    return PROJECT_ROOT / "data" / "processed" / genre / "quality" / "quality_manifest.json"


def _output_dir(genre):
    return PROJECT_ROOT / "data" / "reports" / genre / "creative_guidance"


def _load_config():
    try:
        from xiaoshuo.infra.config_manager import get_config
        return get_config()
    except Exception as e:
        print(f"[WARN] 配置加载失败: {e}")
    return {}


def _get_default_genre():
    cfg = _load_config()
    genres = cfg.get("author", {}).get("genres", ["末世"])
    return genres[0] if genres else "末世"


def _build_csv_map(genre="末世"):
    """P0-1 fix: Build exact stem→csv_path map from novel_index.json."""
    mapping = {}
    if not INDEX_PATH.exists():
        return mapping
    with open(INDEX_PATH, 'r', encoding='utf-8') as f:
        idx = json.load(f)
    novels = idx.get("genres", {}).get(genre, {}).get("novels", [])
    for n in novels:
        stem = n.get("file", "").replace(".txt", "")
        csv_name = n.get("rhythm_csv")
        if csv_name:
            mapping[stem] = csv_name
    return mapping


def _load_manifest(genre="末世"):
    mp = _manifest_path(genre)
    if not mp.exists():
        return [], []
    try:
        with open(mp, 'r', encoding='utf-8') as f:
            m = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"[WARN] quality_manifest.json 读取失败: {e}")
        return [], []
    return m.get("approved", []), m.get("quarantined", [])


def _load_rhythm_data(csv_name, genre="末世"):
    """Load rhythm CSV rows as list[dict] using ChapterMetrics for type safety.

    Uses ChapterMetrics.from_csv_row() for safe type conversion,
    then returns plain dicts for downstream compatibility.
    """
    csv_path = _rhythm_dir(genre) / csv_name
    if not csv_path.exists():
        return None
    rows = []
    try:
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                metrics = ChapterMetrics.from_csv_row(r)
                rows.append(metrics.to_csv_row())
    except (csv.Error, UnicodeDecodeError, ValueError) as e:
        print(f"  [WARN] CSV读取失败 {csv_name}: {e}")
        return None
    return rows


def _mean(vals):
    return round(statistics.mean(vals), 3) if vals else 0


def _pct(d, key, total):
    return round(d.get(key, 0) / max(total, 1) * 100, 1)


def _kl_divergence(p_dist, q_dist):
    """KL divergence between two distributions (dict form)."""
    all_keys = set(p_dist.keys()) | set(q_dist.keys())
    kl = 0.0
    for k in all_keys:
        p = p_dist.get(k, 0.001)
        q = q_dist.get(k, 0.001)
        kl += p * math.log(p / q)
    return round(kl, 4)


# ── P1-4: progress-% bucket normalization ──

def _pct_buckets(rows, n_buckets=10):
    """Split rows into n_buckets by progress % (0-100%)."""
    total = len(rows)
    if total < n_buckets:
        return {f"{i*100//n_buckets}%": rows[i:i+1] if i < total else []
                for i in range(n_buckets)}
    step = max(1, total // n_buckets)
    return {f"{i*100//n_buckets}%": rows[i*step:(i+1)*step]
            for i in range(n_buckets)}


def _format_value(val, indent=0):
    """Convert Python dict/list to human-readable markdown string.

    Avoids raw `[{'type': '羁绊', 'pct': 47}]` in output.
    Nested dict-of-dict (e.g. pct_benchmarks) renders inline per key.
    """
    if val is None:
        return "(无数据)"
    if isinstance(val, dict):
        if not val:
            return "(empty)"
        lines = []
        for k, v in val.items():
            if isinstance(v, dict):
                # Nested dict: render sub-keys inline for compactness
                inner = ", ".join(f"{ik}: {iv}" for ik, iv in v.items())
                lines.append(f"- **{k}**: {inner}")
            elif isinstance(v, list):
                lines.append(f"- **{k}**: {_format_value(v, indent+1)}")
            else:
                lines.append(f"- **{k}**: {v}")
        return "\n".join(lines)
    elif isinstance(val, list):
        if not val:
            return "(empty)"
        if val and isinstance(val[0], dict):
            lines = []
            for item in val:
                parts = ", ".join(f"{k}: {v}" for k, v in item.items())
                lines.append(f"- {parts}")
            return "\n".join(lines)
        else:
            return ", ".join(str(v) for v in val)
    else:
        return str(val)


def _filter_pct_benchmarks(benchmarks, keep_keys=None):
    """Keep only key progress nodes from pct_benchmarks for readability."""
    if keep_keys is None:
        keep_keys = ["0%", "30%", "50%", "80%", "100%"]
    if not isinstance(benchmarks, dict):
        return benchmarks
    result = {}
    for k in keep_keys:
        if k in benchmarks:
            result[k] = benchmarks[k]
    # If none matched (different key format), return first 5
    if not result:
        keys = list(benchmarks.keys())[:5]
        result = {k: benchmarks[k] for k in keys}
    return result


# ── UX: Chinese field labels for human-readable report generation ──

FIELD_LABELS = {
    "sub_genre_distribution": "子类型分布",
    "top_performing": "最佳对标书",
    "top_books": "标杆书单",
    "dominant_conflict_types": "主流冲突类型",
    "arc_distribution": "弧线分布",
    "opening_hook_benchmark": "开篇钩子基准",
    "chapter_avg": "平均总章数",
    "pct_benchmarks": "关键进度节点",
    "arc_types": "弧线类型分布",
    "emotional_range": "情感摆动范围",
    "bond_ratio": "羁绊角色占比",
    "hook_type_distribution": "钩子类型分布",
    "pleasure_level_distribution": "爽点层级分布",
    "slap_frequency": "打脸频率",
    "zero_hook_limit": "零钩子红线",
    "conflict_escalation": "冲突升级曲线",
    "dialogue_ratio": "对话占比",
    "readability": "可读性",
    "chapter_variability": "章节变异度",
    "plot_waves": "情节波次",
    "turning_count": "转折点数量",
    "peak_interval": "爽点间隔",
    "kl_divergence": "KL散度(差异度)",
    "low_freq_opportunities": "低频差异化机会",
    "cliche_scan": "陈词滥调扫描",
    "progression_stages": "进阶阶段",
    "top_reference": "对标参考",
    "dominant_arc": "主力弧线",
    "hook_distribution": "钩子类型分布",
    "zero_hook_redline": "零钩子红线",
    "first_10_chapter_rule": "首秀要求",
}

# UX: pct_benchmarks nested key labels for Chinese output
PCT_BENCHMARK_LABELS = {
    "hook_mean": "钩子密度均值",
    "conflict_mean": "冲突密度均值",
    "pleasure_mean": "爽点强度均值",
    "dialogue_mean": "对话占比均值",
    "n_books": "样本数",
}


def _translate_pct_keys(benchmarks):
    """Translate nested pct_benchmarks keys to Chinese."""
    if not isinstance(benchmarks, dict):
        return benchmarks
    result = {}
    for k, v in benchmarks.items():
        if isinstance(v, dict):
            result[k] = {PCT_BENCHMARK_LABELS.get(ik, ik): iv for ik, iv in v.items()}
        else:
            result[k] = v
    return result


# ── P1-1: rule_translator ──

def _translate_to_rules(metric_name, value, pool_stats):
    """Translate metric→rule→action. Returns (rule, action, risk_level)."""
    rules = {
        "hook_density": lambda v, p: (
            f"每章≥1个钩子, 每4章1个强钩子(平台建议:每300字1爽点/每500字1钩子)",
            f"钩子密度低于{p:.2f}→在章末增加悬念或反转",
            "high" if v < 0.15 else ("medium" if v < 0.25 else "low")
        ),
        "zero_hook_streak": lambda v, p: (
            f"连续≤{int(p)}章无钩子是红线",
            f"连续{v}章零钩子→立即在第{v+1}章插入强钩子(情绪炸弹/悬念反转)",
            "high" if v > 3 else ("medium" if v > 2 else "low")
        ),
        "dialogue_ratio": lambda v, p: (
            f"对话占比{p:.2f}基准(±0.05)",
            f"对话比{v:.2f}→{'过高,减少流水账对话' if v > p+0.1 else ('过低,增加互动场景' if v < p-0.1 else '合理范围')}",
            "high" if abs(v - p) > 0.15 else ("medium" if abs(v - p) > 0.08 else "low")
        ),
        "pleasure_intensity": lambda v, p: (
            f"爽点强度≥{p:.1f}(精品均值)",
            f"强度{v:.1f}→{'需增加爆发式爽点' if v < p-1 else ('达标' if v >= p else '接近标杆')}",
            "high" if v < p - 2 else ("medium" if v < p else "low")
        ),
        "conflict_density": lambda v, p: (
            f"冲突密度{p:.2f}基准",
            f"密度{v:.2f}→{'冲突不足,需要增加对抗' if v < p-0.1 else ('冲突适中' if v < p+0.1 else '冲突过高,需插入缓气章')}",
            "high" if v < p - 0.1 else "low"
        ),
    }
    if metric_name in rules:
        return rules[metric_name](value, pool_stats)
    return (f"{metric_name}={value:.2f}", f"参照精品基准{p:.2f}", "medium")


# ── Main analysis ──

def analyze_for_guidance(genre="末世"):
    approved, quarantined = _load_manifest(genre)
    if not approved:
        print("[WARN] quality_manifest.json 无通过书籍")
        return None

    csv_map = _build_csv_map(genre)  # P0-1: exact mapping

    # P0: filter manifest to only include books with CSVs in this genre
    approved = [a for a in approved
                if any(stem[:12] in a.get("stem", "") or a.get("stem", "")[:12] in stem
                       for stem in csv_map)]
    quarantined = [q for q in quarantined
                   if any(stem[:12] in q.get("stem", "") or q.get("stem", "")[:12] in stem
                          for stem in csv_map)]

    sample_size = len(approved)
    confidence = "low" if sample_size < 30 else ("medium" if sample_size < 50 else "high")

    print(f"[LOAD] {sample_size}本通过 + {len(quarantined)}本待审 (置信度:{confidence})")

    # P0-3: sample size gate — <30禁用百分位, 降级为绝对阈值+专家经验
    if sample_size < 30:
        print(f"  [GATE] 样本量{sample_size}<30 — 禁用百分位排名, 输出绝对阈值区间+警告")
        confidence = "low"

    all_rows, book_data = [], []
    seg_pooled, sub_types_pool, hook_types_pool = {}, Counter(), Counter()
    arc_summaries, pct_pooled = [], {}

    for stem_entry in approved:
        stem = stem_entry["stem"] if isinstance(stem_entry, dict) else stem_entry
        # P0-1: exact match from csv_map
        csv_name = csv_map.get(stem)
        if not csv_name:
            # Fallback: try filename-based search as last resort
            candidates = list(_rhythm_dir(genre).glob(f"rhythm_*{stem[:10]}*.csv"))
            if candidates:
                csv_name = candidates[0].name

        if not csv_name:
            print(f"  [SKIP] {stem[:20]}: 无CSV映射")
            continue
        rows = _load_rhythm_data(csv_name, genre)
        if not rows or len(rows) < 10:
            continue

        all_rows.extend(rows)
        total = len(rows)

        hooks = [r["hook_density"] for r in rows]
        conflicts = [r["conflict_density"] for r in rows]
        pleasures = [r["pleasure_intensity"] for r in rows]
        dialogues = [r["dialogue_ratio"] for r in rows]
        readabilities = [r["readability"] for r in rows]
        ch_vars = [r["ch_variability"] for r in rows]

        zero_streak = cur = 0
        for h in hooks:
            cur = cur + 1 if h == 0 else 0
            zero_streak = max(zero_streak, cur)

        slap_total = sum(r["slap_count"] for r in rows)
        slap_rate = slap_total / max(total, 1)

        for r in rows:
            hook_types_pool[r["hook_type"]] += 1
            sub_types_pool[r["dominant_sub"]] += 1

        first_v = _mean([rows[i]["pos_density"] - rows[i]["neg_density"] for i in range(min(5, total))])
        last_v = _mean([rows[i]["pos_density"] - rows[i]["neg_density"] for i in range(max(0, total - 5), total)])
        arc_summaries.append({
            "name": stem[:20], "chapters": total,
            "V_start": round(first_v, 3), "V_end": round(last_v, 3),
            "arc_type": "上升弧" if last_v > first_v + 0.02 else ("下降弧" if first_v > last_v + 0.02 else "O型弧"),
        })

        # P1-4: % buckets instead of absolute chapter segmentation
        pct_buckets = _pct_buckets(rows)
        for pct_label, seg_rows in pct_buckets.items():
            if not seg_rows:
                continue
            if pct_label not in pct_pooled:
                pct_pooled[pct_label] = {"hooks": [], "conflicts": [], "pleasures": [], "dialogues": []}
            pct_pooled[pct_label]["hooks"].append(_mean([r["hook_density"] for r in seg_rows]))
            pct_pooled[pct_label]["conflicts"].append(_mean([r["conflict_density"] for r in seg_rows]))
            pct_pooled[pct_label]["pleasures"].append(_mean([r["pleasure_intensity"] for r in seg_rows]))
            pct_pooled[pct_label]["dialogues"].append(_mean([r["dialogue_ratio"] for r in seg_rows]))

        book_data.append({
            "name": stem[:20], "chapters": total,
            "avg_hook": _mean(hooks), "avg_conflict": _mean(conflicts),
            "avg_pleasure": _mean(pleasures), "avg_dialogue": _mean(dialogues),
            "avg_readability": _mean(readabilities),
            "avg_ch_variability": _mean(ch_vars),
            "zero_hook_streak": zero_streak,
            "slap_rate": round(slap_rate, 2),
        })

    if not book_data:
        print("[FAIL] 无有效书籍数据")
        return None

    total_ch_all = len(all_rows)
    guidance = {"genre": genre, "book_count": len(book_data),
                "total_chapters": total_ch_all,
                "sample_confidence": confidence,
                "generated": datetime.now().isoformat(),
                "disclaimer": "以下指标基于精品书统计关联(相关,非因果)。优先保证情节强度,量化指标仅作辅助检查。"}

    guidance["worldbuilding"] = _build_worldbuilding(book_data, sub_types_pool, arc_summaries, confidence)
    guidance["rough_outline"] = _build_rough_outline(book_data, pct_pooled, confidence)
    guidance["chapter_outline"] = _build_chapter_outline(all_rows, total_ch_all, hook_types_pool, book_data, confidence)
    guidance["writing_style"] = _build_writing_style(book_data, confidence)
    guidance["character"] = _build_character(book_data, arc_summaries, sub_types_pool, confidence)
    guidance["genre_selection"] = _build_genre_selection(genre, book_data, sub_types_pool)
    guidance["plot_progression"] = _build_plot_progression(book_data, arc_summaries, all_rows, total_ch_all, confidence)
    guidance["anti_homogenization"] = _build_anti_homogenization(book_data, sub_types_pool, hook_types_pool)  # P1-3
    guidance["progression_guide"] = _build_progression_guide(book_data, arc_summaries, confidence)  # v8.2: 三维进阶
    guidance["hook_guide"] = _build_hook_guide(all_rows, book_data, confidence)  # v8.2: 章末钩子
    
    return guidance


# ── Dimension builders (v2 with confidence + rule_translator) ──

def _build_worldbuilding(book_data, sub_types_pool, arc_summaries, confidence):
    books = sorted(book_data, key=lambda b: -b["avg_pleasure"])
    top3 = [b["name"] for b in books[:3]]
    top_subs = sub_types_pool.most_common(5)
    total_sub = sum(c for _, c in top_subs)
    arc_dist = dict(Counter(a["arc_type"] for a in arc_summaries))
    top_hook_mean = _mean([b["avg_hook"] for b in books[:3]])
    rule, action, _ = _translate_to_rules("hook_density", top_hook_mean, top_hook_mean)

    return {
        "summary": f"基于{len(book_data)}本精品书(置信度:{confidence})的世界观指导",
        "confidence": confidence,
        "top_books": top3,
        "dominant_conflict_types": [{"type": n, "pct": round(c/max(total_sub,1)*100)} for n, c in top_subs[:3]],
        "arc_distribution": arc_dist,
        "opening_hook_benchmark": top_hook_mean,
        "rule": rule, "action": action,
        "disclaimer": "⚠ 冲突类型分布为统计相关,非因果律",
        "guidance": [
            f"核心冲突: {top_subs[0][0]}({_pct(sub_types_pool,top_subs[0][0],total_sub)}%)——世界观从此类冲突切入",
            f"爽点高频: {', '.join(f'{n}({_pct(sub_types_pool,n,total_sub)}%)' for n,c in top_subs[:3])}——世界规则应能催生这3类爽点",
            f"弧线分布: {', '.join(f'{k}({v}本)' for k, v in arc_dist.items())}——选择主流弧型作主角轨迹",
            f"翻译规则: {rule} → {action}",
        ],
    }


def _build_rough_outline(book_data, pct_pooled, confidence):
    benchmarks = {}
    for label, pooled in sorted(pct_pooled.items()):
        benchmarks[label] = {
            "hook_mean": _mean(pooled["hooks"]),
            "conflict_mean": _mean(pooled["conflicts"]),
            "pleasure_mean": _mean(pooled["pleasures"]),
            "dialogue_mean": _mean(pooled["dialogues"]),
            "n_books": len(pooled["hooks"]),
        }
    avg_ch = int(statistics.mean([b["chapters"] for b in book_data]))
    early = benchmarks.get("10%", benchmarks.get("20%", {}))
    mid = benchmarks.get("40%", benchmarks.get("50%", {}))

    return {
        "summary": f"分段基准(进度%归一化, 置信度:{confidence})",
        "confidence": confidence,
        "chapter_avg": avg_ch,
        "pct_benchmarks": benchmarks,
        "disclaimer": "⚠ 分段基准为统计均值, 不同类型书籍节奏差异大",
        "guidance": [
            f"总章均{avg_ch}章——规划总纲参考",
            f"开篇(0-10%): hook≥{early.get('hook_mean','?')}, conflict≥{early.get('conflict_mean','?')}——黄金三章达标",
            f"中期(40-60%): conflict峰值{mid.get('conflict_mean','?')}, pleasure≥{mid.get('pleasure_mean','?')}——卷级高潮",
            "每卷20-50章→参照outline_builder.py",
        ],
    }


def _build_chapter_outline(all_rows, total_ch_all, hook_types_pool, book_data, confidence):
    total_hooks = sum(hook_types_pool.values())
    hook_breakdown = {k: round(v/max(total_hooks,1)*100, 1) for k, v in hook_types_pool.most_common(5)}
    pleasure_levels = dict(Counter(r["pleasure_level"] for r in all_rows))
    total_pl = len(all_rows)
    pl_breakdown = {k: round(v/max(total_pl,1)*100,1) for k, v in pleasure_levels.items()}
    slaps = [r["slap_count"] for r in all_rows]
    avg_slap = _mean(slaps)

    book_streaks = [b.get("zero_hook_streak", 0) for b in book_data if b.get("zero_hook_streak", 0) > 0]
    avg_zero = _mean(book_streaks) if book_streaks else 0

    rule, action, _ = _translate_to_rules("zero_hook_streak", avg_zero, 2)

    sorted_rows = sorted(all_rows, key=lambda r: r["ch_num"])
    chunk = max(1, len(sorted_rows) // 10)
    escalation = [{"from_ch": sorted_rows[i]["ch_num"],
                    "conflict_avg": _mean([r["conflict_density"] for r in sorted_rows[i:i+chunk]]),
                    "pleasure_avg": _mean([r["pleasure_intensity"] for r in sorted_rows[i:i+chunk]])}
                  for i in range(0, len(sorted_rows), chunk)][:10]

    return {
        "summary": "逐章节奏指导",
        "confidence": confidence,
        "hook_type_distribution": hook_breakdown,
        "pleasure_level_distribution": pl_breakdown,
        "slap_frequency": {"avg_per_chapter": avg_slap, "sweet_spot": "打脸流:0.25-0.50次/章"},
        "zero_hook_limit": {"avg_streak": avg_zero, "max_safe": 2, "red_line": "连续≥3章→读者弃书风险30%+"},
        "rule": rule, "action": action,
        "conflict_escalation": escalation,
        "disclaimer": "⚠ 钩子类型分布基于关键词正则(漏检率~30%),LLM标注可提升精度",
        "guidance": [
            f"钩子分布: {', '.join(f'{k}({v}%)' for k, v in sorted(hook_breakdown.items(), key=lambda x: -x[1]))}——每章结尾必选一种",
            f"爽点层级: {', '.join(f'{k}({v}%)' for k, v in sorted(pl_breakdown.items(), key=lambda x: -x[1]) if v > 0)}——large≥10%健康,中爽点每3-5章1个",
            f"打脸频率: 均值{avg_slap}次/章",
            f"红线: {rule} → {action}",
            "章模板(起承转爽):起500字→承800字→转300字→爽400字+钩子",
        ],
    }


def _build_writing_style(book_data, confidence):
    dialogues = [b["avg_dialogue"] for b in book_data]
    readabilities = [b["avg_readability"] for b in book_data]
    ch_vars = [b["avg_ch_variability"] for b in book_data]
    d_mean = _mean(dialogues)
    rule, action, _ = _translate_to_rules("dialogue_ratio", d_mean, d_mean)

    return {
        "summary": f"文笔基准(置信度:{confidence})",
        "confidence": confidence,
        "dialogue_ratio": {"mean": d_mean, "range": f"{min(dialogues):.2f}-{max(dialogues):.2f}"},
        "readability": {"mean": _mean(readabilities), "range": f"{min(readabilities):.2f}-{max(readabilities):.2f}"},
        "chapter_variability": {"mean": _mean(ch_vars)},
        "rule": rule, "action": action,
        "disclaimer": "⚠ 对话比与爆款是相关关系;优先保证情节强度,对话比作为辅助检查",
        "guidance": [
            f"对话比: {d_mean:.2f}(精品均值),保持±0.05",
            f"文笔定位: readability {_mean(readabilities):.2f}——末世文建议0.0附近(通俗不白)",
            f"章变异度: {_mean(ch_vars):.1f}——平稳中制造高峰",
            f"规则: {rule} → {action}",
        ],
    }


def _build_character(book_data, arc_summaries, sub_types_pool, confidence):
    arc_dist = dict(Counter(a["arc_type"] for a in arc_summaries))
    v_starts = [a["V_start"] for a in arc_summaries]
    v_ends = [a["V_end"] for a in arc_summaries]
    total_sub = sum(sub_types_pool.values())
    bond_pct = round(sub_types_pool.get("羁绊", 0) / max(total_sub, 1) * 100, 1)
    v_swing = round(abs(_mean(v_ends) - _mean(v_starts)), 3) if v_starts and v_ends else 0

    return {
        "summary": f"人物塑造指导(置信度:{confidence})",
        "confidence": confidence,
        "arc_types": arc_dist,
        "emotional_range": {"V_start_mean": _mean(v_starts), "V_end_mean": _mean(v_ends), "V_swing": v_swing},
        "bond_ratio": bond_pct,
        "disclaimer": "⚠ 人物弧线分布为统计相关;写作风格各有千秋",
        "guidance": [
            f"主流弧: {max(arc_dist,key=arc_dist.get) if arc_dist else '上升弧'}——弧型决定主角情感走向",
            f"V摆动: {v_swing}——摆动越大情感旅程越强烈",
            f"羁绊爽点: {bond_pct}%——末世中守护/并肩/牺牲是重要爽点源",
            "每卷≥1次身份揭示/关系重置,保持V波动",
        ],
    }


def _build_genre_selection(genre, book_data, sub_types_pool):
    all_genre_stats = {}
    if INDEX_PATH.exists():
        with open(INDEX_PATH, 'r', encoding='utf-8') as f:
            idx = json.load(f)
        for g_name, g_data in idx.get("genres", {}).items():
            sub_types = Counter()
            for n in g_data.get("novels", []):
                sub_types[n.get("sub_genre", "未知")] += 1
            all_genre_stats[g_name] = {"count": g_data.get("count", 0), "top_sub": sub_types.most_common(3)}

    total_sub = sum(sub_types_pool.values())
    top_subs = sub_types_pool.most_common(5)
    books_sorted = sorted(book_data, key=lambda b: -b["avg_pleasure"])
    top_book = books_sorted[0] if books_sorted else None

    return {
        "summary": f"题材选择指导",
        "current_genre": genre,
        "sub_genre_distribution": [{"type": n, "pct": round(c/max(total_sub,1)*100)} for n, c in top_subs],
        "multi_genre_overview": all_genre_stats,
        "top_performing": {"book": top_book["name"], "avg_pleasure": top_book["avg_pleasure"]} if top_book else {},
        "disclaimer": "⚠ 题材选择基于现有样本统计;市场趋势变化快",
        "guidance": [
            f"子类型: {', '.join(f'{n}({round(c/max(total_sub,1)*100)}%)' for n,c in top_subs[:3])}——高占比降低试错成本",
            f"最佳对标: {top_book['name'] if top_book else 'N/A'}(爽点{top_book['avg_pleasure'] if top_book else '?'})",
        ],
    }


def _build_plot_progression(book_data, arc_summaries, all_rows, total_ch, confidence):
    sorted_rows = sorted(all_rows, key=lambda r: r["ch_num"])
    chunk = max(1, len(sorted_rows) // 8)
    waves = []
    for i in range(0, len(sorted_rows), chunk):
        batch = sorted_rows[i:i + chunk]
        waves.append({
            "phase": i // chunk + 1, "conflict": _mean([r["conflict_density"] for r in batch]),
            "pleasure": _mean([r["pleasure_intensity"] for r in batch]),
            "hook_mean": _mean([r["hook_density"] for r in batch]),
        })
    turning = [i for i in range(1, len(waves))
               if waves[i-1]["conflict"] > 0 and waves[i]["conflict"] / max(waves[i-1]["conflict"], 0.01) > 1.3]
    peak_chapters = [r["ch_num"] for r in all_rows if r["pleasure_level"] == "large"]
    avg_peak = _mean([peak_chapters[i+1]-peak_chapters[i] for i in range(len(peak_chapters)-1)]) if len(peak_chapters) >= 2 else 0

    return {
        "summary": f"情节推动分析(置信度:{confidence})",
        "confidence": confidence,
        "plot_waves": [{"phase": w["phase"], "conflict": w["conflict"], "pleasure": w["pleasure"],
                         "hook": w["hook_mean"]} for w in waves[:8]],
        "turning_count": len(turning),
        "peak_interval": {"avg_chapters_between": avg_peak, "recommendation": "3-5章"},
        "disclaimer": "⚠ 波次分析基于章节混合,不同长度书节奏差异大;建议按篇幅分桶",
        "guidance": [
            f"波次: {len(waves)}段——冲突整体递增",
            f"转折: {len(turning)}处——读者情绪切换节点",
            f"爽点间隔: {avg_peak:.0f}章——太密审美疲劳,太疏流失",
            "推动公式:铺垫(低冲突)→激化(+30%)→高潮(大爽点)→释放→新钩子",
        ],
    }


# ── v8.2: 三维进阶指导 (身份/财富/麻烦) ──

def _build_progression_guide(book_data, arc_summaries, confidence):
    """Generate 3D progression guidance: identity/wealth/trouble escalation.
    
    Based on <一品布衣> methodology: protagonist progression should be
    identity + wealth + trouble escalation, not simple level-up.
    """
    arc_dist = dict(Counter(a["arc_type"] for a in arc_summaries))
    dominant_arc = max(arc_dist, key=arc_dist.get) if arc_dist else "上升弧"
    
    books = sorted(book_data, key=lambda b: -b["avg_pleasure"])
    top3 = [b["name"] for b in books[:3]]
    
    stages = [
        {
            "stage": 1,
            "label": "开局",
            "identity": "底层/边缘身份",
            "wealth": "极度匮乏",
            "trouble": "个人生存危机",
            "goal": "建立主角底线与反差",
        },
        {
            "stage": 2,
            "label": "崛起",
            "identity": "小势力/团队核心",
            "wealth": "初步积累",
            "trouble": "地方势力对抗",
            "goal": "身份升级 + 麻烦扩大",
        },
        {
            "stage": 3,
            "label": "扩张",
            "identity": "区域势力/组织领袖",
            "wealth": "资源掌控",
            "trouble": "跨区域冲突",
            "goal": "财富质变 + 对抗层级提升",
        },
        {
            "stage": 4,
            "label": "巅峰",
            "identity": "世界级/顶级身份",
            "wealth": "垄断/稀缺资源",
            "trouble": "世界级威胁/终极对抗",
            "goal": "身份顶点 + 麻烦终极化",
        },
    ]
    
    return {
        "summary": f"三维进阶指导 — 身份/财富/麻烦非纯数值升级 (置信度:{confidence})",
        "confidence": confidence,
        "dominant_arc": dominant_arc,
        "top_reference": top3,
        "progression_stages": stages,
        "disclaimer": "⚠ 进阶路径为推荐模板，实际创作中可根据世界观灵活调整",
        "guidance": [
            f"推荐弧线: {dominant_arc} — 主角从弱势到强势的情感轨迹",
            "拒绝纯数值升级: 每一阶段都伴随身份变化、财富质变、麻烦扩大",
            "阶段过渡: 前一阶段未解决的麻烦 → 下一阶段的核心冲突",
            f"参考对标: {', '.join(top3)} — 观察这些书的进阶路径",
        ],
    }


# ── v8.2: 章末钩子指导 ──

def _build_hook_guide(all_rows, book_data, confidence):
    """Generate chapter-end hook guidance based on rhythm data.
    
    Analyzes hook types and provides chapter-end hook templates.
    """
    hook_types = Counter(r.get("hook_type", "none") for r in all_rows)
    total_hooks = sum(hook_types.values())
    
    hook_templates = {
        "悬念": "在章末抛出一个未解之谜或疑问",
        "反转": "揭示一个意外真相或身份反转",
        "危机": "突然出现新的威胁或危险",
        "约定": "主角做出承诺或约定，留下期待",
        "登场": "关键人物突然出现或即将登场",
        "发现": "主角发现重要线索或秘密",
    }
    
    hook_dist = []
    for htype, count in hook_types.most_common(6):
        if htype == "none":
            continue
        pct = round(count / max(total_hooks, 1) * 100, 1)
        template = hook_templates.get(htype, "")
        hook_dist.append({
            "type": htype,
            "pct": pct,
            "template": template,
        })
    
    # Analyze zero-hook streaks
    zero_streaks = []
    for b in book_data:
        if b.get("zero_hook_streak", 0) > 0:
            zero_streaks.append(b["zero_hook_streak"])
    avg_zero = statistics.mean(zero_streaks) if zero_streaks else 0
    
    return {
        "summary": "章末钩子指导 — 每章结尾必备悬念 (基于拆书数据)",
        "confidence": confidence,
        "hook_distribution": hook_dist,
        "zero_hook_redline": {
            "avg_streak": round(avg_zero, 1),
            "max_safe": 2,
            "rule": "连续≥3章无钩子 = 读者弃书风险30%+",
        },
        "first_10_chapter_rule": "番茄首秀要求: 前10章每章结尾必须有钩子",
        "disclaimer": "⚠ 钩子类型基于关键词正则检测(漏检率~30%), 建议结合LLM语义分析",
        "guidance": [
            "每章结尾必选一种钩子类型 (悬念/反转/危机/约定/登场/发现)",
            "精品基准: " + ", ".join("%s(%.1f%%)" % (h["type"], h["pct"]) for h in hook_dist[:3]),
            f"零钩子红线: 连续{int(avg_zero)}章零钩子已是精品极限, 前10章必须每章有钩子",
            "钩子公式: 冲突结果 + 新悬念 = 读者不得不点下一章",
        ],
    }


# ── P1-3: Anti-homogenization ──

def _build_anti_homogenization(book_data, sub_types_pool, hook_types_pool):
    """Detect over-concentration and suggest differentiation."""
    total_books = len(book_data)
    if total_books < 3:
        return {"summary": "样本不足, 无法做反同质化分析", "suggestions": []}

    # KL divergence of each type distribution vs uniform
    total_sub = sum(sub_types_pool.values())
    sub_dist = {k: v/max(total_sub,1) for k, v in sub_types_pool.items()}
    uniform_sub = {k: 1/len(sub_dist) for k in sub_dist}
    sub_kl = _kl_divergence(sub_dist, uniform_sub)

    total_hk = sum(hook_types_pool.values())
    hk_dist = {k: v/max(total_hk,1) for k, v in hook_types_pool.items()}
    uniform_hk = {k: 1/len(hk_dist) for k in hk_dist}
    hk_kl = _kl_divergence(hk_dist, uniform_hk)

    # Low-frequency but potentially high-value patterns
    low_freq_subs = [(k, v) for k, v in sub_types_pool.most_common()
                     if v / max(total_sub, 1) < 0.05 and v > 0]
    low_freq_hooks = [(k, v) for k, v in hook_types_pool.most_common()
                      if v / max(total_hk, 1) < 0.05 and v > 0]

    suggestions = []
    if sub_kl > 0.5:
        suggestions.append(f"爽点类型高度集中(KL={sub_kl:.2f})——考虑引入低频类型差异化: {', '.join(k for k,v in low_freq_subs[:3])}")
    if hk_kl > 0.5:
        suggestions.append(f"钩子类型高度集中(KL={hk_kl:.2f})——尝试低频钩子: {', '.join(k for k,v in low_freq_hooks[:3])}")
    if not suggestions:
        suggestions.append("爽点+钩子分布合理(KL<0.5), 自然差异化已存在")

    # P0-2: 陈词滥调扫描 — 规则库第二层检测
    cliches = _scan_cliches(sub_types_pool, hook_types_pool, total_books)

    return {
        "summary": "反同质化分析——你的书跟爆款太像了吗？(差异度检测)",
        "kl_divergence": {"sub_types": sub_kl, "hook_types": hk_kl},
        "low_freq_opportunities": {"sub_types": low_freq_subs[:3], "hook_types": low_freq_hooks[:3]},
        "cliche_scan": cliches,
        "disclaimer": "⚠ 以上基于统计低频;爆款套路本身是经过市场验证的。是否偏离主流套路，需要你自己的创作判断",
        "suggestions": suggestions,
    }


# ── P0-2: 陈词滥调扫描 (PlotPilot规则库第二层, 零LLM成本) ──

CLICHE_PATTERNS = {
    "退婚流开场": re.compile(r"退婚|休书|一纸休书|三十年河东|莫欺少年穷"),
    "系统觉醒": re.compile(r"叮[！!].*系统.*激活|系统提示|\\[宿主\\]"),
    "拍卖会打脸": re.compile(r"拍卖.*包厢|天字.*包厢|出价.*震惊|全场.*哗然"),
    "跳崖得宝": re.compile(r"坠[落入].*悬崖|跳[下入].*悬崖|崖底.*洞府|传承"),
    "炼丹炸炉": re.compile(r"炸炉|丹炉.*爆炸|炼丹.*失败|炸丹"),
    "戒指老爷爷": re.compile(r"戒指.*声音|苍老.*声音|戒指.*灵魂|残魂|金手指"),
    "倒吸一口凉气": re.compile(r"倒吸.*凉气|倒吸.*冷气"),
    "恐怖如斯": re.compile(r"恐怖如斯|骇然|此子|竟恐怖"),
}


def _scan_cliches(sub_types_pool, hook_types_pool, total_books):
    """P0-2: 陈词滥调扫描 — 规则库检测高频套路表达.
    
    方法: 从 rhythm_analyzer 爽点/冲突正则库提取高频模式,
    与 PlotPilot 规则库+语义相似度方案不同, 这里只做正则匹配(零成本).
    """
    results = {}
    total_sub = sum(sub_types_pool.values())
    total_hk = sum(hook_types_pool.values())

    for label, pattern in CLICHE_PATTERNS.items():
        # Count pattern hits across sub-type names and hook-type names
        sub_hits = sum(1 for k in sub_types_pool if pattern.search(k))
        hook_hits = sum(1 for k in hook_types_pool if pattern.search(k))
        # Aggregated coverage (rough estimate based on pool coverage)
        coverage = (sub_hits + hook_hits) / max(total_books * 2, 1)
        if coverage > 0.1:
            results[label] = {
                "coverage": round(coverage, 2),
                "severity": "HIGH" if coverage > 0.4 else ("MED" if coverage > 0.2 else "LOW"),
            }

    return {
        "patterns_found": len(results),
        "details": results,
        "suggestion": "高频套路标记: 越高频的套路越容易被读者识别为'模板化'。KL散度告诉你分布集中度, 规则库告诉你具体是哪些套路过度使用。",
    }


# ── P0-2: JSON output ──

def generate_json_output(guidance, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(guidance, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"[OK] guidance JSON: {output_path}")


def generate_summary_md(guidance, output_path):
    """Generate a 1-page human-readable summary (no JSON, no jargon)."""
    g = guidance
    lines = [
        f"# {g['genre']}类网文创作分析摘要",
        f"\n> 基于{g['book_count']}本精品书分析 · 置信度: {g.get('sample_confidence','?')}",
        f"> {g.get('disclaimer','')}",
        "\n---",
    ]

    # Top 3 actionable insights
    lines.append("\n## 你最需要关注的三件事\n")

    # 1: Opening hook benchmark from worldbuilding
    wb = g.get("worldbuilding", {})
    if wb.get("opening_hook_benchmark"):
        lines.append(f"1. **开篇钩子**: {wb['opening_hook_benchmark']}")

    # 2: Zero-hook redline
    co = g.get("chapter_outline", {})
    zhl = co.get("zero_hook_limit", {})
    if zhl:
        lines.append(f"2. **节奏红线**: 连续≥{zhl.get('max_safe', '?')}章零钩子是红线 (精品最长{_format_value(zhl.get('avg_streak', '?'))})")

    # 3: Top conflict type
    dct = wb.get("dominant_conflict_types")
    if dct:
        top_ct = dct[0] if dct else {}
        lines.append(f"3. **核心冲突**: {top_ct.get('type','?')} ({top_ct.get('pct','?')}%)")

    # Quick reference table
    lines.append("\n## 各维度速查\n")
    lines.append("| 维度 | 关键数据 |")
    lines.append("|------|---------|")

    # Pacing
    ro = g.get("rough_outline", {})
    if ro:
        ch_avg = ro.get("chapter_avg", "?")
        lines.append(f"| 每章字数 | 约{ch_avg}字 |")

    # Hook types
    if co.get("hook_type_distribution"):
        hk_dist = co['hook_type_distribution']
        top_hooks = sorted(hk_dist.items(), key=lambda x: -x[1])[:3]
        lines.append(f"| 常用钩子 | {', '.join(f'{k}({v}%)' for k, v in top_hooks)} |")

    # Dialogue
    ws = g.get("writing_style", {})
    if ws.get("dialogue_ratio"):
        d = ws["dialogue_ratio"]
        d_mean = d.get('mean', 0)
        lines.append(f"| 对话占比 | {d_mean:.0%} (精品范围{d.get('range','?')}) |")

    # Emotional range
    chg = g.get("character", {})
    er = chg.get("emotional_range", {})
    if er:
        lines.append(f"| 情感摆动 | V_start={er.get('V_start_mean','?')}, V_end={er.get('V_end_mean','?')}, swing={er.get('V_swing','?')} |")

    # Genre hits
    gs = g.get("genre_selection", {})
    if gs.get("sub_genre_distribution"):
        top = gs["sub_genre_distribution"][0] if gs["sub_genre_distribution"] else {}
        lines.append(f"| 最火子类型 | {top.get('type','?')} ({top.get('pct',0)}%精品采用) |")

    # Anti-homogenization tip
    ah = g.get("anti_homogenization", {})
    if ah.get("suggestions"):
        sug = ah["suggestions"][0]
        lines.append(f"| 差异化建议 | {sug[:50]}... |")

    lines.append(f"\n---\n*完整报告见 {output_path.stem.replace('摘要','创作指导')}.md*")
    lines.append(f"*{g.get('generated','')[:19]}*")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding='utf-8')
    print(f"[OK] summary MD: {output_path}")


def generate_md_report(guidance, output_path):
    g = guidance
    conf = g.get('sample_confidence', '?')
    # P0-3: sample size gate warning
    gate_warning = ""
    if g.get("sample_confidence") == "low":
        gate_warning = (
            f"\n> ⚠️ **样本量门控**: 精品书仅{g['book_count']}本(<30)，"
            "百分位排名已禁用。以下输出基于绝对阈值+专家经验区间，仅供趋势参考，不可作为精确对标。"
            "\n> 扩至30本后自动切换为百分位排名。\n"
        )

    lines = [
        f"# {g['genre']}类网文创作指导 v2",
        f"\n> 数据源: {g['book_count']}本精品书(置信度:{conf}) · {g['total_chapters']}章",
        f"> {g.get('disclaimer','')}",
        f"> ⚠️ **AI声明**: 本指导由AI辅助统计分析生成，仅提供趋势参考和写作建议，不构成创作内容。AI生成正文须通过S3质量门禁。",
        gate_warning,
        "\n---\n",
        "## 全部概览 — 10维渐进式披露\n",
        "> 不是一次性看完所有维度，而是**按你的创作阶段逐步深入**。",
        "> 每个阶段只关注 2-3 维，完整 10 维随时可查。\n",
        "| 阶段 | 维度 | 何时看 |",
        "|------|------|--------|",
        "| 🟢 **准备期** | 题材选择 / 世界观 | 开书前 — 决定写什么类型、世界长什么样 |",
        "| 🟡 **规划期** | 粗纲 / 人物 | 动笔前 — 搭骨架、设计角色 |",
        "| 🔵 **执行期** | 细纲 / 文笔 / 情节推动 / 章末钩子 | 日更时 — 每章怎么写、节奏怎么控 |",
        "| 🔴 **审视期** | 反同质化 / 三维进阶 | 完本后 — 检查是否跟风太紧、升级路径是否合理 |",
        "\n---\n",
    ]

    # Reordered sections with stage annotations
    staged_sections = [
        # 🟢 阶段1: 准备期
        ("🟢 一、题材选择 [准备期]", "genre_selection",
         ["sub_genre_distribution", "top_performing", "guidance", "disclaimer"]),
        ("🟢 二、世界观 [准备期]", "worldbuilding",
         ["top_books", "dominant_conflict_types", "arc_distribution",
          "opening_hook_benchmark", "rule", "action", "guidance", "disclaimer"]),
        # 🟡 阶段2: 规划期
        ("🟡 三、粗纲(进度%归一化) [规划期]", "rough_outline",
         ["chapter_avg", "pct_benchmarks", "guidance", "disclaimer"]),
        ("🟡 四、人物塑造 [规划期]", "character",
         ["arc_types", "emotional_range", "bond_ratio", "guidance", "disclaimer"]),
        # 🔵 阶段3: 执行期
        ("🔵 五、细纲 [执行期]", "chapter_outline",
         ["hook_type_distribution", "pleasure_level_distribution",
          "slap_frequency", "zero_hook_limit", "rule", "action",
          "conflict_escalation", "guidance", "disclaimer"]),
        ("🔵 六、文笔 [执行期]", "writing_style",
         ["dialogue_ratio", "readability", "chapter_variability",
          "rule", "action", "guidance", "disclaimer"]),
        ("🔵 七、情节推动 [执行期]", "plot_progression",
         ["plot_waves", "turning_count", "peak_interval", "guidance", "disclaimer"]),
        ("🔵 八、章末钩子 [执行期]", "hook_guide",
         ["hook_distribution", "zero_hook_redline", "first_10_chapter_rule",
          "guidance", "disclaimer"]),
        # 🔴 阶段4: 审视期
        ("🔴 九、反同质化 [审视期]", "anti_homogenization",
         ["kl_divergence", "low_freq_opportunities", "suggestions", "disclaimer"]),
        ("🔴 十、三维进阶 [审视期]", "progression_guide",
         ["dominant_arc", "top_reference", "progression_stages",
          "guidance", "disclaimer"]),
    ]

    for title, key, fields in staged_sections:
        data = g.get(key, {})
        lines.extend([f"\n---\n", f"## {title}\n", data.get("summary", "")])
        for f in fields:
            if f in data and data[f]:
                val = data[f]
                # Skip raw "guidance" — rendered as "建议" below
                if f == "guidance":
                    continue
                label = FIELD_LABELS.get(f, f)
                if f == "pct_benchmarks":
                    val = _filter_pct_benchmarks(val)
                    val = _translate_pct_keys(val)
                    lines.append(f"\n### 关键进度节点\n{_format_value(val)}")
                else:
                    lines.append(f"\n### {label}\n{_format_value(val)}")
        if data.get("guidance"):
            lines.append("\n#### 建议\n")
            for item in data["guidance"]:
                lines.append(f"- {item}")

    lines.append(f"\n---\n*v2 · {g['generated'][:19]} · {g['book_count']}本 · 置信度:{conf}*")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding='utf-8')
    print(f"[OK] guidance MD: {output_path}")


def main():
    genre = _get_default_genre()
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--genre" and i < len(sys.argv) - 1:
            genre = sys.argv[i + 1]
            break
    print(f"[CREATIVE BRIDGE v2] genre={genre}")
    guidance = analyze_for_guidance(genre)
    if not guidance:
        print("[FAIL] 无可用的分析数据")
        return

    # Output: JSON + 完整报告 + 人类可读摘要
    base = _output_dir(genre)
    generate_json_output(guidance, base / f"{genre}_创作指导.json")
    generate_md_report(guidance, base / f"{genre}_创作指导.md")
    generate_summary_md(guidance, base / f"{genre}_分析摘要.md")

    print(f"\n[DONE] 创作指导(置信度:{guidance['sample_confidence']}):")
    readable_dims = [
        "对标分析: 同类精品长啥样",
        "骨架建议: 大纲节奏怎么排",
        "每章节奏: 钩子/爽点怎么埋",
        "文笔参考: 对话比/可读性对标",
        "人物设计: 弧型/情感指标",
        "选材方向: 哪个子类型更火",
        "故事推进: 波次/转折/爽点间隔",
        "章末钩子: 每章结尾怎么留悬念",
        "避免雷同: 跟爆款太像了吗",
        "三维进阶: 身份/财富/麻烦升级路径",
    ]
    for i, d in enumerate(readable_dims, 1):
        print(f"  {i}. {d}")


if __name__ == "__main__":
    main()
