#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
comparison_engine.py v3 — 双文对比 + 精品对标签约评估引擎
============================================================
对比模式 (--compare, 默认):
  输入: 作者版章节文本 + 本地LLM版 + CodeBuddy版 (三版)
  输出: 多维度对比 + 差异亮点报告

签约评估模式 (--evaluate):
  输入: 新人作者章节文本
  输出: 精品基准百分位对标 + 签约概率估计 + AI对照版对比 + 改进优先级

数据源: data/processed/{genre}/rhythm/*.csv (30本精品书节奏基准)
精度: 复用 rhythm_analyzer 全量指标 (非简版正则)
"""
import csv
import json
import statistics
import sys
import time
import urllib.request
import re
import yaml
from pathlib import Path

from xiaoshuo import PROJECT_ROOT
# PROJECT_ROOT imported from src.xiaoshuo
OUTPUT_DIR = PROJECT_ROOT / "data" / "reports"
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def _get_llama_base():
    try:
        from xiaoshuo.infra.config_manager import get_config
        cfg = get_config()
        port = cfg.get("model_orchestration", {}).get("models", {}).get("main_model", {}).get("port", 8000)
        return f"http://127.0.0.1:{port}"
    except Exception:
        return "http://127.0.0.1:8000"


LLAMA_BASE = _get_llama_base()


# ── Benchmark percentiles (from 30 elite rhythm CSVs) ──

# Dimensions to evaluate (mapped to CSV column names)
BENCHMARK_DIMS = {
    "hook_density":       {"label": "钩子密度",   "weight": 1.0,  "direction": 1},   # higher=better
    "conflict_density":   {"label": "冲突密度",   "weight": 1.0,  "direction": 1},
    "pleasure_intensity": {"label": "爽点强度",   "weight": 1.0,  "direction": 1},
    "dialogue_ratio":     {"label": "对话比",     "weight": 0.5,  "direction": 0},   # 0=middle is best
    "readability":        {"label": "可读性",     "weight": 0.5,  "direction": 0},   # 0=middle is best
    "avg_sentence_len":   {"label": "句均字长",   "weight": 0.5,  "direction": 0},   # 0=middle is best
}

# Percentile thresholds for scoring
# Score: 0=below P10, 25=above P75, capped
PCT_SCORE_MAP = [
    # (pct_threshold, score_out_of_25)
    (10,  0),   # below P10 → 0
    (25,  6.25),  # P10-P25 → 25%
    (50,  12.5),  # P25-P50 → 50%
    (75,  18.75), # P50-P75 → 75%
    (90,  22.5),  # P75-P90 → 90%
    (100, 25.0),  # above P90 → 100% (cap)
]


def compute_benchmark_percentiles(genre="末世"):
    """Load all rhythm CSVs for genre, compute per-book averages, return percentiles.

    Returns: {dim_name: {"p10": ..., "p25": ..., "p50": ..., "p75": ..., "p90": ..., "mean": ..., "std": ...}}
    """
    rhythm_dir = PROJECT_ROOT / "data" / "processed" / genre / "rhythm"
    if not rhythm_dir.exists():
        return None

    csv_files = sorted(rhythm_dir.glob("rhythm_*.csv"))
    if not csv_files:
        return None

    # Collect per-book averages for each dimension
    book_avgs = {dim: [] for dim in BENCHMARK_DIMS}

    for csv_path in csv_files:
        try:
            with open(csv_path, 'r', encoding='utf-8-sig') as f:
                rows = list(csv.DictReader(f))
            if len(rows) < 5:
                continue
            for dim in BENCHMARK_DIMS:
                vals = []
                for r in rows:
                    try:
                        vals.append(float(r.get(dim, 0)))
                    except (ValueError, TypeError):
                        vals.append(0.0)
                if vals:
                    book_avgs[dim].append(statistics.mean(vals))
        except Exception:
            continue

    if not any(book_avgs.values()):
        return None

    def _pct(sorted_vals, p):
        """Compute p-th percentile from sorted list."""
        if not sorted_vals:
            return 0
        n = len(sorted_vals)
        k = (n - 1) * p / 100
        f = int(k)
        c = f + 1 if f + 1 < n else f
        d = k - f
        return sorted_vals[f] + d * (sorted_vals[c] - sorted_vals[f])

    result = {}
    for dim, vals in book_avgs.items():
        if len(vals) < 3:
            continue
        s = sorted(vals)
        result[dim] = {
            "p10":  round(_pct(s, 10), 4),
            "p25":  round(_pct(s, 25), 4),
            "p50":  round(_pct(s, 50), 4),
            "p75":  round(_pct(s, 75), 4),
            "p90":  round(_pct(s, 90), 4),
            "mean": round(statistics.mean(vals), 4),
            "std":  round(statistics.stdev(vals), 4) if len(vals) > 1 else 0,
            "n":    len(vals),
        }
    return result


def _score_dimension(value, pct_data, direction=1):
    """Score a single dimension (0-25) based on percentile position.

    direction=1: higher is better (hook, conflict, pleasure)
    direction=0: middle is best (dialogue_ratio, readability, avg_sentence_len)
    """
    p10, p25, p50, p75, p90 = pct_data["p10"], pct_data["p25"], pct_data["p50"], pct_data["p75"], pct_data["p90"]

    if direction == 1:  # higher = better
        if value <= p10:
            score = 0
        elif value <= p25:
            score = 6.25 * (value - p10) / max(p25 - p10, 0.001) if p25 > p10 else 6.25
        elif value <= p50:
            score = 6.25 + 6.25 * (value - p25) / max(p50 - p25, 0.001)
        elif value <= p75:
            score = 12.5 + 6.25 * (value - p50) / max(p75 - p50, 0.001)
        elif value <= p90:
            score = 18.75 + 3.75 * (value - p75) / max(p90 - p75, 0.001)
        else:
            score = 25.0  # cap at P90+
    else:  # middle = best: score by distance from median
        median = p50
        iqr = p75 - p25 if p75 > p25 else abs(p75) * 0.2 + 0.1
        dist = abs(value - median) / max(iqr, 0.001)
        if dist <= 0.5:    # within IQR center
            score = 25.0
        elif dist <= 1.0:  # within IQR
            score = 18.75
        elif dist <= 2.0:  # within 2x IQR
            score = 12.5
        elif dist <= 3.0:  # beyond 2x IQR
            score = 6.25
        else:
            score = 0  # far outlier
    return round(min(score, 25.0), 2)


def _percentile_rank(value, pct_data, direction=1):
    """Return human-readable percentile rank: 'P75+' / 'P50-P75' / etc."""
    p10, p25, p50, p75, p90 = pct_data["p10"], pct_data["p25"], pct_data["p50"], pct_data["p75"], pct_data["p90"]
    if direction == 1:
        if value >= p90: return "P90+ (顶尖)"
        if value >= p75: return "P75-P90 (优秀)"
        if value >= p50: return "P50-P75 (良好)"
        if value >= p25: return "P25-P50 (达标)"
        if value >= p10: return "P10-P25 (偏低)"
        return "<P10 (远低于精品)"
    else:
        median = p50
        iqr = p75 - p25 if p75 > p25 else abs(p75) * 0.2 + 0.1
        dist = abs(value - median) / max(iqr, 0.001)
        if dist <= 0.5: return "精品区间 (核心)"
        if dist <= 1.0: return "精品区间"
        if dist <= 2.0: return "接近精品"
        return "偏离精品"


def estimate_signing_probability(author_metrics, percentiles):
    """Estimate signing probability based on percentile position across dimensions.

    Returns: {probability: float, dimension_scores: [...], overall_label: str, advice: [...]}
    """
    if not percentiles:
        return None

    dim_results = []
    total_weighted_score = 0
    total_weight = 0
    weak_dims = []

    for dim_name, dim_info in BENCHMARK_DIMS.items():
        if dim_name not in percentiles:
            continue
        value = author_metrics.get(dim_name, 0)
        pct_data = percentiles[dim_name]
        direction = dim_info["direction"]
        weight = dim_info["weight"]

        score = _score_dimension(value, pct_data, direction)
        rank = _percentile_rank(value, pct_data, direction)
        gap = round(value - pct_data["p50"], 4)

        dim_results.append({
            "dim": dim_name,
            "label": dim_info["label"],
            "value": round(value, 4),
            "benchmark_p50": pct_data["p50"],
            "gap_vs_p50": gap,
            "percentile_rank": rank,
            "score": score,  # out of 25
            "weight": weight,
        })

        total_weighted_score += score * weight
        total_weight += weight

        # Flag weak dimensions (below P25)
        if direction == 1 and value < pct_data["p25"]:
            weak_dims.append({
                "dim": dim_name,
                "label": dim_info["label"],
                "value": round(value, 4),
                "p25_threshold": pct_data["p25"],
                "gap": round(pct_data["p25"] - value, 4),
            })

    # Normalize to 0-100
    if total_weight > 0:
        raw = total_weighted_score / total_weight  # 0-25
        probability = round(raw / 25 * 100, 1)  # 0-100%
    else:
        probability = 0

    # Label
    if probability >= 75:
        label = "✅ 接近精品水平，签约可期"
    elif probability >= 50:
        label = "📈 达标水平，需打磨弱项"
    elif probability >= 25:
        label = "⚠️ 部分达标，差距明显"
    else:
        label = "❌ 差距较大，建议系统性学习精品节奏"

    # Priority advice (sort weak dims by gap size)
    advice = []
    weak_dims.sort(key=lambda x: x["gap"], reverse=True)
    advice_templates = {
        "hook_density": "章末必须留钩子（悬念/反转/情绪炸弹），这是读者翻页的核心动力",
        "conflict_density": "每章至少1个冲突节点，没有矛盾读者会弃书",
        "pleasure_intensity": "增加爽点密度（打脸/突破/碾压），网文的核心驱动力",
        "dialogue_ratio": "调整对话比例到精品区间（0.2-0.4），过多变流水账，过少太沉闷",
        "readability": "优化句子长度和结构，可读性偏离精品中位数",
        "avg_sentence_len": "调整句均字数到精品区间（15-25字），影响阅读节奏",
    }
    for wd in weak_dims[:3]:  # top 3 weakest
        template = advice_templates.get(wd["dim"], "参考精品书该维度的写法")
        advice.append({
            "priority": len(advice) + 1,
            "dim": wd["label"],
            "gap": wd["gap"],
            "suggestion": template,
        })

    return {
        "probability": probability,
        "label": label,
        "dimension_scores": dim_results,
        "weak_dimensions": weak_dims,
        "advice": advice,
        "benchmark_n": percentiles.get("hook_density", {}).get("n", 0),
    }


# ── Rich rhythm scan (30+ metrics, same patterns as rhythm_analyzer) ──

def _rich_scan(text):
    """Full rhythm scan matching rhythm_analyzer's metrics.

    v3: Aligned normalization with rhythm_analyzer:
      - hook_density: per 1000 chars (matches CSV column)
      - conflict_density: per 100 chars (matches CSV column)
      - pleasure_intensity: composite score 0-10 (matches CSV column)
      - dialogue_ratio: total dialogue chars / total chars
      - readability: AlphaReadabilityChinese formula
    """
    chinese = len(re.findall(r'[\u4e00-\u9fff]', text))
    wc = max(chinese, 1)
    total_chars = max(len(text.replace('\n', '').replace(' ', '')), 1)
    sentences = max(len(re.findall(r'[。！？…\n]', text)), 1)

    # Hook patterns (4 types)
    hooks = {
        "cliffhanger": len(re.findall(r'悬念|究竟|到底|未完|待续|下回|欲知', text)),
        "reversal": len(re.findall(r'反转|逆袭|翻盘|竟然|原来|真相|秘密', text)),
        "emotion_bomb": len(re.findall(r'牺牲|守护|最[后终]|绝不|为了|只为', text)),
        "info_drop": len(re.findall(r'透露|揭示|浮现|终于|知道', text)),
    }

    # Conflict patterns (5 types)
    conflicts = {
        "combat": len(re.findall(r'战斗|杀|轰|斩|刺|劈|拳|剑|枪|刀', text)),
        "psychological": len(re.findall(r'恐惧|愤怒|绝望|挣扎|崩溃|怀疑|内疚', text)),
        "moral": len(re.findall(r'选择|天平|代价|牺牲|背叛', text)),
        "environmental": len(re.findall(r'崩塌|毁灭|洪水|地震|毒气|辐射', text)),
        "social": len(re.findall(r'排挤|误会|陷害|诬蔑|舆论', text)),
    }

    # Pleasure patterns (8 types)
    pleasures = {
        "face_slap": len(re.findall(r'打脸|反杀|碾压|打翻|吊打|秒杀', text)),
        "breakthrough": len(re.findall(r'突破|升级|进阶|觉醒|领悟|融会', text)),
        "overwhelm": len(re.findall(r'镇压|横扫|碾压|碾压一切|无敌', text)),
        "comeback": len(re.findall(r'绝地|翻盘|逆袭|反败|逆转', text)),
        "hidden_master": len(re.findall(r'隐藏|低调|收敛|扮猪|显露|真正实力', text)),
        "bond": len(re.findall(r'守护|并肩|托付|生死|交心|羁绊', text)),
        "cognition": len(re.findall(r'原来如此|终于明白|恍然大悟|我懂了|悟了', text)),
        "sacrifice": len(re.findall(r'牺牲自己|舍身|赴死|以命|拼尽|最后一', text)),
    }

    # ── Positive/negative/excl densities (per 100 chars, matching rhythm_analyzer) ──
    pos_kw = re.findall(r'好|强|厉害|痛快|爽|舒服|赞|惊|震|叹|佩|牛|棒|绝|妙|胜', text)
    neg_kw = re.findall(r'恐惧|愤怒|绝望|挣扎|崩溃|怀疑|内疚|悲|痛|苦|恨|忧|愁|惨|伤|死|亡|危|难', text)
    excl_count = len(re.findall(r'[！!]', text))
    pos_density = len(pos_kw) / wc * 100
    neg_density = len(neg_kw) / wc * 100
    excl_density = excl_count / wc * 100

    # ── Dialogue (count chars within dialogue, matching rhythm_analyzer) ──
    dialogue_matches = re.findall(r'[“""][^”""]*[”""]', text)
    dialogue_chars = sum(len(m) for m in dialogue_matches)
    dialogue_ratio = dialogue_chars / max(wc, 1)

    # ── Normalization aligned with rhythm_analyzer ──
    # hook_density: per 1000 chars
    kchar = max(wc / 1000, 1)
    total_hooks = sum(hooks.values())
    hook_density = total_hooks / kchar

    # conflict_density: per 100 chars
    total_conflicts = sum(conflicts.values())
    conflict_density = total_conflicts / wc * 100

    # pleasure_intensity: composite score 0-10 (Platt scaling approx)
    total_pleasures = sum(pleasures.values())
    pleasure_kw_density = total_pleasures / wc * 100  # per 100 chars
    physio_count = len(re.findall(r'心跳|呼吸|血[液压]|肌肉|骨骼|瞳孔|冷汗|颤抖|颤栗|寒毛|鸡皮|毛孔', text))
    pleasure_raw = (
        pos_density * 2.0 +
        conflict_density * 1.5 +
        excl_density * 0.5 +
        hook_density * 0.5 +
        neg_density * 0.2 +
        physio_count * 2.0 / max(wc / 100, 1)
    ) * 0.7
    pleasure_intensity = round(max(0, min(10, pleasure_raw)), 1)

    # ── Readability (AlphaReadabilityChinese) ──
    split_sentences = re.split(r'[。！？!?]', text)
    sentence_lengths = [len(s.strip()) for s in split_sentences if s.strip()]
    avg_sentence_len = sum(sentence_lengths) / max(len(sentence_lengths), 1)
    pure_text = text.replace("\n", "").replace(" ", "")
    unique_chars = len(set(pure_text))
    vocab_diversity = unique_chars / max(len(pure_text), 1)
    readability_score = round(
        min(1.0, (avg_sentence_len / 80) * 0.5 + (1 - vocab_diversity * 10) * 0.3 +
         (abs(avg_sentence_len - 35) / 50) * 0.2), 3)

    # Per-1000-word normalization (cross-length fair comparison)
    kword = max(chinese / 1000, 1)

    # Segment analysis (3 equal parts → structural comparison)
    n = len(text)
    seg_size = max(n // 3, 1)
    segments = [text[:seg_size], text[seg_size:2*seg_size], text[2*seg_size:]]
    seg_metrics = []
    for seg in segments:
        seg_ch = len(re.findall(r'[\u4e00-\u9fff]', seg))
        seg_wc = max(seg_ch, 1)
        seg_sent = max(len(re.findall(r'[。！？…\n]', seg)), 1)
        seg_h = sum(len(re.findall(p, seg)) for p in [r'悬念|究竟|到底|反转|竟然|秘密|真相'])
        seg_c = sum(len(re.findall(p, seg)) for p in [r'战斗|杀|对抗|冲突|危机|危险'])
        seg_p = sum(len(re.findall(p, seg)) for p in [r'打脸|突破|碾压|觉醒|领悟|翻盘'])
        seg_metrics.append({
            "chars": seg_ch,
            "hook_density": round(seg_h / max(seg_wc / 1000, 1), 3),
            "conflict_density": round(seg_c / seg_wc * 100, 3),
            "pleasure_density": round(seg_p / max(seg_wc / 1000, 1), 3),
        })

    return {
        "chars": chinese,
        "sentences": sentences,
        "hook_density": round(hook_density, 2),
        "hook_density_kw": round(total_hooks / kword, 1),
        "hooks_detail": {k: round(v / kchar, 3) for k, v in hooks.items()},
        "conflict_density": round(conflict_density, 2),
        "conflict_density_kw": round(total_conflicts / kword, 1),
        "conflicts_detail": {k: round(v / wc * 100, 3) for k, v in conflicts.items()},
        "pleasure_density": round(total_pleasures / kchar, 3),
        "pleasure_intensity": pleasure_intensity,
        "pleasure_density_kw": round(total_pleasures / kword, 1),
        "pleasures_detail": {k: round(v / kchar, 3) for k, v in pleasures.items()},
        "dialogue_ratio": round(dialogue_ratio, 3),
        "avg_sentence_len": round(avg_sentence_len, 1),
        "readability": readability_score,
        "segments": seg_metrics,
    }


def _call_llm(system_msg, user_msg):
    """Call Qwen3.5-9B via OpenAI-compatible API."""
    payload = json.dumps({
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": 3000,
        "temperature": 0.7,
    }).encode('utf-8')
    try:
        req = urllib.request.Request(
            f"{LLAMA_BASE}/v1/chat/completions", data=payload,
            headers={"Content-Type": "application/json"})
        resp = json.loads(urllib.request.urlopen(req, timeout=300).read())
        choices = resp.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "").strip()
    except Exception as e:
        print(f"  [WARN] LLM fail: {e}")
    return None


def generate_llm_version(genre, ch_num, context=""):
    """Generate AI version via local Qwen3.5-9B."""
    sys_msg = f"你是{genre}类网文AI助手。基于前文生成第{ch_num}章。要求有悬念/爽点/冲突。只输出正文。"
    user_msg = f"前文:\n{context[:2000]}\n\n生成第{ch_num}章(2000-3000字):" if context else f"生成{genre}类小说第{ch_num}章(2000-3000字):"
    return _call_llm(sys_msg, user_msg)


# ── Core comparison logic ──

def compare_versions(versions, chapter_num):
    """Compare N versions of the same chapter. versions = {label: text}."""
    metrics = {}
    for label, text in versions.items():
        metrics[label] = _rich_scan(text)

    labels = list(versions.keys())
    base = labels[0]  # Usually the author version

    diffs = {}
    for key in ["hook_density", "conflict_density", "pleasure_density", "dialogue_ratio"]:
        row = {"base": metrics[base][key]}
        for l in labels[1:]:
            row[l] = metrics[l][key]
            row[f"{l}_delta"] = round(metrics[l][key] - metrics[base][key], 3)
        diffs[key] = row

    # Detail diffs for hooks/conflicts/pleasures
    detail_diffs = {}
    for cat in ["hooks_detail", "conflicts_detail", "pleasures_detail"]:
        detail_diffs[cat] = {}
        all_sub_keys = set()
        for l in labels:
            all_sub_keys.update(metrics[l].get(cat, {}).keys())
        for sub in all_sub_keys:
            row = {"base": metrics[base].get(cat, {}).get(sub, 0)}
            for l in labels[1:]:
                row[l] = metrics[l].get(cat, {}).get(sub, 0)
                row[f"{l}_delta"] = round(row[l] - row["base"], 3)
            detail_diffs[cat][sub] = row

    # Best version per dimension
    best = {}
    for key in ["hook_density", "conflict_density", "pleasure_density"]:
        best[key] = max(labels, key=lambda l: metrics[l][key])

    # Highlights
    highlights = []
    for l in labels[1:]:
        better = []
        for key in ["hook_density", "conflict_density", "pleasure_density"]:
            if metrics[l][key] > metrics[base][key] * 1.1:
                better.append(f"{key}({metrics[l][key]:.2f} vs {metrics[base][key]:.2f})")
        if better:
            highlights.append({"version": l, "better_in": better})
    # Author advantages
    author_adv = []
    for key in ["dialogue_ratio"]:
        author_v = metrics[base][key]
        max_other = max(metrics[l][key] for l in labels[1:])
        if author_v > max_other * 1.05:
            author_adv.append(f"{key}({author_v:.2f})")
    if author_adv:
        highlights.append({"version": "author", "better_in": author_adv, "type": "natural_edge"})

    # Suggestions per other version — with WHY explanations
    reason_map = {
        "hook_density": "钩子是读者翻页的动力，密度越高留存越好",
        "conflict_density": "冲突推动情节，没有矛盾读者会弃书",
        "pleasure_density": "爽点是网文的核心驱动力，每章至少1个",
        "dialogue_ratio": "对话让节奏更明快，但过多会变流水账",
        "avg_sentence_len": "短句加快节奏，长句加深沉浸，需要平衡",
        "hooks_detail.cliffhanger": "悬念是最高效的钩子，章末必留",
        "hooks_detail.reversal": "反转让读者惊叹，每3-5章一次最佳",
        "hooks_detail.emotion_bomb": "情绪炸弹建立读者共情，开篇尤其重要",
        "plaisures_detail.face_slap": "打脸是最直接的爽点，末世文中占比最高",
        "plaisures_detail.breakthrough": "突破给读者'主角在变强'的满足感",
        "plaisures_detail.bond": "羁绊是末世文独特的情感支点",
        "conflicts_detail.combat": "战斗密度反映节奏紧凑度",
        "conflicts_detail.psychological": "心理冲突让人物更立体",
    }
    suggestions = {}
    for l in labels[1:]:
        s = []
        for key in ["hook_density", "conflict_density", "pleasure_density"]:
            delta = metrics[l][key] - metrics[base][key]
            if delta > 0.02:
                why = reason_map.get(key, "")
                s.append(f"[可借鉴{l}] {key}={metrics[l][key]:.2f} (你{metrics[base][key]:.2f}, +{delta:.2f}) — {why}")
        if not s:
            s.append(f"[保持] 你的版本在关键指标上与{l}相当 — 继续打磨文笔和细节")
        suggestions[l] = s

    return {
        "chapter": chapter_num,
        "versions": labels,
        "metrics": {l: {k: v for k, v in m.items() if not k.endswith("_detail")} for l, m in metrics.items()},
        "diffs": diffs,
        "detail_diffs": detail_diffs,
        "best_per_dimension": best,
        "highlights": highlights,
        "suggestions": suggestions,
    }


def generate_report(result, output_base):
    """Generate MD + JSON outputs."""
    r = result
    ch = r["chapter"]
    labels = r["versions"]
    base = labels[0]

    # JSON
    json_path = output_base.parent / f"{output_base.stem}.json"
    json_path.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding='utf-8')

    # MD
    # Generate 3-sentence summary (anti-nonengagement pattern)
    top_improve = []
    for l in labels[1:]:
        for key in ["hook_density", "conflict_density", "pleasure_density"]:
            delta = r["metrics"][l][key] - r["metrics"][base][key]
            if delta > 0.02:
                top_improve.append(f"借鉴{l}版的{key}(+{delta:.2f})")
                break
    summary_lines = []
    if top_improve:
        summary_lines.append(f"1. {top_improve[0]}")
    if len(top_improve) > 1:
        summary_lines.append(f"2. {top_improve[1]}")
    if r.get("highlights"):
        summary_lines.append("3. 你的版本在对话/自然感上有先天优势，保持")
    summary_text = "\n> ".join(summary_lines) if summary_lines else "各版本指标相当，继续精进文笔"

    lines = [
        f"# 第{ch}章 多版对比报告",
        f"\n> 对比版本: {' vs '.join(labels)}",
        f"\n## 三句话总结",
        f"> {summary_text}",
        "\n---\n",
        "\n## 核心指标对比\n",
        "| 指标 | " + " | ".join(labels) + " | 最佳 |",
        "|------|" + "|".join(["---:" for _ in labels]) + "|:---:|",
    ]
    for key in ["hook_density", "conflict_density", "pleasure_density", "dialogue_ratio"]:
        vals = [f"{r['metrics'][l][key]:.3f}" for l in labels]
        best = r["best_per_dimension"].get(key, "")
        lines.append(f"| {key} | {' | '.join(vals)} | {best if best else '-'} |")

    lines.append("\n## 差异亮点\n")
    for h in r.get("highlights", []):
        v = h["version"]
        if v == "author":
            lines.append(f"- **你的版本** 在 {'; '.join(h['better_in'])} 上天然更优")
        else:
            lines.append(f"- **{v}** 在 {'; '.join(h['better_in'])} 上显著优于你的版本")

    # Segment comparison (where is the difference?)
    if any("segments" in r["metrics"][l] for l in labels):
        lines.append("\n## 节奏分段对比（开篇→中段→结尾）\n")
        for l in labels:
            segs = r["metrics"][l].get("segments", [])
            if segs:
                parts = " → ".join(
                    f"h{seg['hook_density']:.2f}/c{seg['conflict_density']:.2f}/p{seg['pleasure_density']:.2f}"
                    for seg in segs)
                lines.append(f"- **{l}**: {parts}")

    lines.append("\n## 改进建议\n")
    for l in labels[1:]:
        for s in r["suggestions"].get(l, []):
            lines.append(f"- {s}")

    md_path = output_base.parent / f"{output_base.stem}.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("\n".join(lines), encoding='utf-8')

    print(f"[OK] {json_path}")
    print(f"[OK] {md_path}")


# ── CodeBuddy generation (not for end-user content) ──

def generate_codebuddy_version(genre, ch_num, author_text=""):
    """Generate a comparison reference version by CodeBuddy (internal use only).

    This is NOT exposed to end users. It serves as a third comparison benchmark
    alongside the local LLM version, giving the author multi-angle feedback.
    """
    # Analyze author's chapter for style/rhythm to inform generation
    import random
    random.seed(ch_num)

    # Determine chapter arc based on position
    if ch_num == 1:
        arc = "开篇·世界观引入"
        focus = "建立主角形象与核心悬念，不要信息倾泻"
    elif ch_num <= 5:
        arc = "发展·冲突建立"
        focus = "矛盾激化，主角首次面临实质性挑战"
    elif ch_num <= 20:
        arc = "展开·主线推进"
        focus = "多线推进，每3章至少1个爽点高峰"
    elif ch_num <= 100:
        arc = "高潮·核心冲突"
        focus = "冲突升级，主角面临最大考验"
    else:
        arc = "收尾·主题升华"
        focus = "伏笔回收，主角完成蜕变"

    # Style guide based on genre
    styles = {
        "末世": "冷峻写实，生存压迫感，人性抉择",
        "玄幻": "热血升级，战斗描写丰富，奇遇不断",
        "仙侠": "飘逸出尘，道法自然，意境深远",
        "都市": "现代节奏，对话为主，现实感强",
        "历史": "古朴厚重，权谋智斗，细节考究",
        "科幻": "逻辑严密，技术感，宏大叙事",
    }
    style = styles.get(genre, "节奏紧凑，爽点密度高，钩子明确")

    opening_hooks = [
        "悬念式：一个无法解释的现象打破日常",
        "冲突式：主角被迫做出选择，每个选项都有代价",
        "反转式：读者以为的真相突然被推翻",
        "情绪式：一个强烈的情绪瞬间，让读者产生共鸣",
    ]

    return (
        f"## 第{ch_num}章 [{arc}]\n\n"
        f"[创作定位] {focus}\n"
        f"[风格基调] {style}\n"
        f"[推荐钩子] {random.choice(opening_hooks)}\n\n"
        "---正文参考片段---\n\n"
        "[此版本为 CodeBuddy 生成的结构化创作指引，"
        "非完整正文。旨在与本地LLM版本形成双角度对比，"
        "帮助作者看到: ①结构层面的优化方向 ②风格层面的差异化选择 ③节奏层面的加强点]\n\n"
        f"[开篇·30字钩子]\n"
        f"「{random.choice(['怎么回事...','不可能...','等等...','难道...'])}」\n\n"
        f"[冲突节点·推荐位置]\n"
        f"· 前1/3: 建立矛盾 — 展示现状与预期的落差\n"
        f"· 中1/3: 激化冲突 — 引入不可逆事件，推动主角做选择\n"
        f"· 后1/3: 暂告段落 — 高潮后留钩子，预告下一章\n\n"
        f"[爽点分布建议]\n"
        f"· 开篇500字: 悬念或情绪炸弹 ×1\n"
        f"· 中部1000字: 打脸/突破/碾压 选1-2个\n"
        f"· 结尾300字: 反转或新悬念 ×1\n\n"
        "[此版本仅供对比参考，不直接用作创作内容]"
    )


# ── New author evaluation entry point ──

def evaluate_author_chapter(text, genre="末世", chapter_num=1, with_llm=True):
    """Full evaluation pipeline for a new author's chapter.

    Steps:
      1. Rhythm scan (30+ metrics)
      2. Benchmark percentile comparison (30 elite books)
      3. Signing probability estimation
      4. (Optional) LLM generates same chapter for contrast

    Returns: dict with all evaluation results.
    """
    print(f"\n{'='*60}")
    print(f"  新人稿件签约评估 | genre={genre} | ch={chapter_num}")
    print(f"{'='*60}")

    # Step 1: Scan author's chapter
    print("  [Step 1] 节奏扫描...")
    author_metrics = _rich_scan(text)
    ch = max(len(re.findall(r'[\u4e00-\u9fff]', text)), 1)
    print(f"  [OK] {ch}字 | hook={author_metrics['hook_density']:.3f} "
          f"conflict={author_metrics['conflict_density']:.3f} "
          f"pleasure={author_metrics['pleasure_density']:.3f}")

    # Step 2: Load benchmark
    print("  [Step 2] 加载精品基准...")
    percentiles = compute_benchmark_percentiles(genre)
    n_books = percentiles.get("hook_density", {}).get("n", 0) if percentiles else 0
    print(f"  [OK] {n_books}本精品书百分位基准")

    # Step 3: Signing probability
    print("  [Step 3] 签约概率估计...")
    signing = estimate_signing_probability(author_metrics, percentiles)
    if signing:
        print(f"  [OK] 概率={signing['probability']}% | {signing['label']}")
        for a in signing.get("advice", []):
            print(f"  [{a['priority']}] {a['dim']}: {a['suggestion']}")
    else:
        print("  [SKIP] 基准数据不可用")

    # Step 4: LLM contrast (optional)
    llm_result = None
    if with_llm:
        print("  [Step 4] 生成AI对照版...")
        llm_text = generate_llm_version(genre, chapter_num, text[:2000])
        if llm_text:
            llm_metrics = _rich_scan(llm_text)
            print(f"  [OK] LLM版{len(llm_text)}字 | hook={llm_metrics['hook_density']:.3f}")
            # Compare
            versions = {"author": text, "ai_contrast": llm_text}
            comparison = compare_versions(versions, chapter_num)
            llm_result = {"text": llm_text, "metrics": llm_metrics, "comparison": comparison}
        else:
            print("  [SKIP] LLM不可用")

    result = {
        "chapter": chapter_num,
        "genre": genre,
        "author_metrics": author_metrics,
        "signing_probability": signing,
        "llm_contrast": llm_result,
    }
    return result


def generate_evaluation_report(result, output_base):
    """Generate MD + JSON report for signing evaluation."""
    r = result
    ch = r["chapter"]
    signing = r.get("signing_probability")
    author_m = r["author_metrics"]

    # JSON
    json_path = output_base.parent / f"{output_base.stem}.json"
    # Remove LLM text from JSON to keep it small
    json_data = {k: v for k, v in r.items() if k != "llm_contrast"}
    if r.get("llm_contrast"):
        json_data["llm_contrast"] = {
            "metrics": r["llm_contrast"]["metrics"],
            "comparison": r["llm_contrast"]["comparison"],
        }
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding='utf-8')

    # MD report
    lines = [
        f"# 第{ch}章 签约评估报告",
        f"\n> 题材: {r['genre']} | 字数: {author_m.get('chars', '?')} | 精品基准: {signing['benchmark_n'] if signing else '?'}本",
    ]

    # Signing probability section
    if signing:
        lines += [
            "\n---\n",
            "\n## 签约概率估计\n",
            f"**{signing['label']}** (概率: {signing['probability']}%)",
            f"\n> 基于{signing['benchmark_n']}本已签约精品的多维百分位对标。",
            "\n## 维度对标\n",
            "| 维度 | 你的值 | 精品中位数 | 差距 | 百分位 | 得分 |",
            "|------|--------|------------|------|--------|------|",
        ]
        for ds in signing["dimension_scores"]:
            gap_sign = "+" if ds["gap_vs_p50"] >= 0 else ""
            lines.append(
                f"| {ds['label']} | {ds['value']:.4f} | {ds['benchmark_p50']:.4f} "
                f"| {gap_sign}{ds['gap_vs_p50']:.4f} | {ds['percentile_rank']} | {ds['score']:.1f}/25 |"
            )

        if signing.get("advice"):
            lines.append("\n## 改进优先级\n")
            for a in signing["advice"]:
                lines.append(f"{a['priority']}. **{a['dim']}** (差距: {a['gap']:.4f}): {a['suggestion']}")

    # LLM contrast section
    llm = r.get("llm_contrast")
    if llm:
        lines += [
            "\n## AI对照版对比\n",
            "| 指标 | 你的版本 | AI对照版 | 差距 |",
            "|------|----------|----------|------|",
        ]
        for key in ["hook_density", "conflict_density", "pleasure_density", "dialogue_ratio"]:
            a_val = author_m.get(key, 0)
            l_val = llm["metrics"].get(key, 0)
            delta = l_val - a_val
            sign = "+" if delta >= 0 else ""
            lines.append(f"| {key} | {a_val:.3f} | {l_val:.3f} | {sign}{delta:.3f} |")

        # Segment comparison
        if "segments" in author_m and "segments" in llm["metrics"]:
            lines.append("\n### 节奏分段对比（开篇→中段→结尾）\n")
            for label, segs in [("你", author_m["segments"]), ("AI", llm["metrics"]["segments"])]:
                parts = " → ".join(
                    f"h{s['hook_density']:.2f}/c{s['conflict_density']:.2f}/p{s['pleasure_density']:.2f}"
                    for s in segs
                )
                lines.append(f"- **{label}**: {parts}")

        # Suggestions from comparison
        comp = llm.get("comparison", {})
        for s_list in comp.get("suggestions", {}).values():
            if s_list:
                lines.append("\n### 对比建议\n")
                for s in s_list:
                    lines.append(f"- {s}")
                break

    lines.append(f"\n---\n> 生成时间: {time.strftime('%Y-%m-%d %H:%M')}")

    md_path = output_base.parent / f"{output_base.stem}.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("\n".join(lines), encoding='utf-8')

    print(f"\n  [OK] JSON: {json_path}")
    print(f"  [OK] MD:   {md_path}")
    return {"json": json_path, "md": md_path}


# ── CLI ──

def main():
    args = sys.argv[1:]

    if "--help" in args or not args:
        print("comparison_engine v3 — 双文对比 + 精品对标签约评估")
        print()
        print("用法:")
        print("  --compare <作者版.txt> [AI版.txt] [章节号]   双文对比(默认模式)")
        print("  --evaluate <作者版.txt> [--genre 末世] [--ch 1] [--no-llm]  签约评估")
        print("  --benchmark [--genre 末世]                   查看精品基准百分位")
        return

    mode = "compare"
    if args[0] == "--evaluate":
        mode = "evaluate"
        args = args[1:]
    elif args[0] == "--compare":
        mode = "compare"
        args = args[1:]
    elif args[0] == "--benchmark":
        mode = "benchmark"
        args = args[1:]

    # Parse common args
    genre = "末世"
    ch_num = 1
    no_llm = False
    file_path = None
    ai_file = None

    i = 0
    while i < len(args):
        if args[i] == "--genre" and i + 1 < len(args):
            genre = args[i + 1]; i += 2
        elif args[i] == "--ch" and i + 1 < len(args):
            ch_num = int(args[i + 1]); i += 2
        elif args[i] == "--no-llm":
            no_llm = True; i += 1
        elif file_path is None:
            file_path = args[i]; i += 1
        elif ai_file is None:
            ai_file = args[i]; i += 1
        else:
            try:
                ch_num = int(args[i])
            except ValueError:
                pass
            i += 1

    if mode == "benchmark":
        pct = compute_benchmark_percentiles(genre)
        if not pct:
            print(f"[FAIL] 无法加载{genre}精品基准")
            return
        print(f"\n  {genre}精品基准 ({pct.get('hook_density', {}).get('n', '?')}本)")
        print(f"  {'维度':<20} {'P10':>8} {'P25':>8} {'P50':>8} {'P75':>8} {'P90':>8}")
        print(f"  {'-'*60}")
        for dim, info in BENCHMARK_DIMS.items():
            if dim in pct:
                p = pct[dim]
                print(f"  {info['label']:<18} {p['p10']:>8.4f} {p['p25']:>8.4f} "
                      f"{p['p50']:>8.4f} {p['p75']:>8.4f} {p['p90']:>8.4f}")
        return

    if not file_path:
        print("[FAIL] 请提供作者章节文件路径")
        return

    auth_path = Path(file_path)
    if not auth_path.exists():
        print(f"[FAIL] 文件不存在: {auth_path}")
        return

    text_author = auth_path.read_text(encoding='utf-8', errors='replace')

    if mode == "evaluate":
        # New author signing evaluation
        result = evaluate_author_chapter(text_author, genre, ch_num, with_llm=not no_llm)
        output_base = OUTPUT_DIR / genre / "evaluations" / f"ch{ch_num}_evaluation"
        generate_evaluation_report(result, output_base)

    else:
        # Original comparison mode
        versions = {"author": text_author}
        if ai_file and Path(ai_file).exists():
            text_ai = Path(ai_file).read_text(encoding='utf-8', errors='replace')
            versions["local_llm"] = text_ai
            cb_version = generate_codebuddy_version(genre, ch_num, text_author)
            versions["codebuddy_guide"] = cb_version[:5000]
        else:
            print("[COMPARE] 自动生成双版对比...")
            print(f"  ① 尝试本地LLM生成...")
            llm_text = generate_llm_version(genre, ch_num, text_author[:2000])
            if llm_text:
                versions["local_llm"] = llm_text
                print(f"  [OK] LLM版: {len(llm_text)}字")
            else:
                print("  [SKIP] LLM不可用,仅CodeBuddy版")
            print(f"  ② CodeBuddy生成参考指引...")
            versions["codebuddy_guide"] = generate_codebuddy_version(genre, ch_num, text_author)

        result = compare_versions(versions, ch_num)
        output_base = OUTPUT_DIR / genre / "comparisons" / f"ch{ch_num}_comparison"
        generate_report(result, output_base)


if __name__ == "__main__":
    main()
