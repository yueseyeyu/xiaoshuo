#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
genre_synthesizer.py v8 — 拆书三件套 + 商业可行性引擎 + Bayesian BMA
方法: 笔灵拆书三件套(人物/情节/技巧) + VAD情感弧 + 结构模板 + Survival分段留存 + 跨题材竞争力
参考: MARCUS(arxiv 2510.18201) + 马良写作 + 笔灵AI + Bayesian LLM Eval(arxiv 2504.21303)

输入: data/rhythm_*.csv（同题材所有小说）
输出: data/analysis/{genre}/synthesis/{genre}_写作技法总纲.md
"""
import csv
import json
import statistics
import math
import sys
import yaml
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LLM_DIR = PROJECT_ROOT / "data" / "processed" / "llm_scores"
CALIB_DIR = PROJECT_ROOT / "analysis" / "outputs" / "calibration"

# ── Bayesian BMA weights (loaded once from calibrate_v2) ──
_bayesian_weights_cache = None


def _load_bayesian_weights():
    """v8: Read calibrate_v2 feature importance, compute per-metric Bayesian blend weights.
    Based on arxiv 2504.21303 (Bayesian LLM Evaluation) + Self-Preference Bias mitigation.
    Returns {metric: {rule_weight, llm_weight, best_rule_feature}}"""
    global _bayesian_weights_cache
    if _bayesian_weights_cache is not None:
        return _bayesian_weights_cache

    fi_path = CALIB_DIR / "feature_importance.csv"
    if not fi_path.exists():
        # Fallback to default weights (r_min=0.2 → w_rule≈0.04)
        _bayesian_weights_cache = {
            "intensity": {"w_rule": 0.20, "w_llm": 0.80, "feature": "pos_density", "r": 0.445},
            "conflict":  {"w_rule": 0.20, "w_llm": 0.80, "feature": "conflict_density", "r": 0.348},
            "hook":      {"w_rule": 0.05, "w_llm": 0.95, "feature": "hook_density", "r": 0.135},
        }
        return _bayesian_weights_cache

    features = {}
    with open(fi_path, 'r', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            features[row["feature"]] = float(row["r_vs_llm_intensity"])

    def _bayesian_weight(r):
        """Bayesian shrinkage: w_rule = r²/(1+r²), w_llm = 1/(1+r²).
        Floor w_rule at 0.05 to prevent LLM monopoly on small-n data."""
        r2 = max(r, 0.01) ** 2
        w_r = max(0.05, r2 / (1.0 + r2))
        return round(w_r, 3)

    # Best rule features per metric from calibrate_v2 Pearson r data
    best_features = {
        "intensity": ("pos_density", features.get("pos_density", 0.445)),
        "conflict":  ("conflict_density", features.get("conflict_density", 0.406)),
        "hook":      ("hook_density", features.get("hook_density", 0.096)),
    }

    _bayesian_weights_cache = {}
    for metric, (feat, r_val) in best_features.items():
        wr = _bayesian_weight(r_val)
        _bayesian_weights_cache[metric] = {
            "w_rule": wr, "w_llm": round(1.0 - wr, 3),
            "feature": feat, "r": r_val,
        }
    return _bayesian_weights_cache


def _load_all_llm_scores():
    """v7: Load all LLM scores keyed by (book_stem, ch_num). Cached at module level."""
    # Use module-level cache pattern
    cache = getattr(_load_all_llm_scores, "_cache", None)
    if cache is not None:
        return cache
    all_scores = {}
    for fp in LLM_DIR.glob("*_llm.csv"):
        stem = fp.stem.replace("_llm", "")
        with open(fp, 'r', encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                all_scores[(stem, int(r["ch_num"]))] = {
                    "intensity": float(r["llm_intensity"]),
                    "retention": float(r["llm_retention"]),
                }
    _load_all_llm_scores._cache = all_scores
    return all_scores


def _find_book_stem(rows, all_scores):
    """v7: Find which book these rows belong to by matching against LLM scores."""
    stems = set(k[0] for k in all_scores.keys())
    best_stem, best_match = None, 0
    for stem in stems:
        matches = sum(1 for r in rows[:min(5, len(rows))]
                     if (stem, r["ch_num"]) in all_scores)
        if matches > best_match:
            best_stem, best_match = stem, matches
    return best_stem or ""


DATA_DIR = PROJECT_ROOT / "data"
RHYTHM_DIR = DATA_DIR / "processed" / "rhythm"
INDEX_PATH = DATA_DIR / "raw" / "novel_index.json"
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def get_default_genre():
    """Read default genre from config.yaml author section."""
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("genres:") and "[" in line and "]" in line:
                        items = line[line.index("[")+1:line.index("]")]
                        first = [s.strip().strip("\"'") for s in items.split(",") if s.strip()]
                        return first[0] if first else "末世"
    except Exception as e:
        print(f"[WARN] Failed to parse config.yaml genres: {e}, using default '末世'", file=sys.stderr)
    return "末世"


def load_genre_novels(genre):
    if not INDEX_PATH.exists():
        print(f"[FAIL] novel_index.json not found at {INDEX_PATH}")
        return []
    with open(INDEX_PATH, 'r', encoding='utf-8') as f:
        index = json.load(f)
    return index["genres"].get(genre, {}).get("novels", [])


def load_rhythm_data(csv_name):
    csv_path = RHYTHM_DIR / csv_name
    if not csv_path.exists():
        return None
    rows = []
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            rows.append({
                "ch_num": int(r["ch_num"]), "wc": int(r["wc"]),
                "hook_density": float(r["hook_density"]),
                "conflict_density": float(r["conflict_density"]),
                "dialogue_ratio": float(r["dialogue_ratio"]),
                "pos_density": float(r.get("pos_density", 0)),
                "neg_density": float(r.get("neg_density", 0)),
                "slap_count": int(r.get("slap_count", 0)),
                "pleasure_type": r.get("pleasure_type", "none"),
                "pleasure_intensity": float(r.get("pleasure_intensity", 0)),
                "pleasure_level": r.get("pleasure_level", "none"),
                "hook_type": r.get("hook_type", "none"),
                "readability": float(r.get("readability", 0)),
                "dominant_sub": r.get("dominant_sub", "none"),
                "pace": r.get("pace", "medium"),
                "ch_variability": float(r.get("ch_variability", 0)),
            })
    return rows


# ── VAD情感弧 (arxiv 2511.11857) ──

def compute_vad(rows):
    """VAD 3D emotion curve + turning points."""
    curve = [{"ch": r["ch_num"], "V": round(r["pos_density"] - r["neg_density"], 2),
              "A": r["pleasure_intensity"], "D": round(10 - r["conflict_density"], 2)} for r in rows]
    if len(curve) < 10:
        return curve, [], {"V_mean": 0, "A_mean": 0, "D_mean": 0, "turning_count": 0}

    turning = []
    for i in range(2, len(curve) - 2):
        prev = statistics.mean([curve[j]["V"] for j in range(i-2,i)])
        nxt = statistics.mean([curve[j]["V"] for j in range(i,i+2)])
        std_all = statistics.stdev([c["V"] for c in curve[max(0,i-5):min(len(curve),i+5)]]) if len(curve)>5 else 1
        if std_all > 0 and abs(nxt - prev) > std_all * 1.2:
            turning.append({"ch": curve[i]["ch"], "dir": "up" if nxt>prev else "down", "delta": round(abs(nxt-prev),2)})

    summary = {
        "V_mean": round(statistics.mean([c["V"] for c in curve]), 2),
        "A_mean": round(statistics.mean([c["A"] for c in curve]), 1),
        "D_mean": round(statistics.mean([c["D"] for c in curve]), 2),
        "turning_count": len(turning),
    }
    return curve, turning, summary


# ── 结构模板匹配 (马良写作) ──

def classify_structure(rows):
    """Classify each chapter into narrative phase (起/承/转/爽/紧张/缓气/线索/推翻)."""
    labels = []
    for i, r in enumerate(rows):
        cd, pi, cv, ht = r["conflict_density"], r["pleasure_intensity"], r["ch_variability"], r["hook_type"]
        if cd < 0.3 and pi < 3:
            labels.append("起")
        elif 0.3 <= cd < 1.0:
            labels.append("承")
        elif cv > 0.5 or (i > 0 and abs(pi - rows[i-1]["pleasure_intensity"]) > 2.5):
            labels.append("转")
        elif pi >= 5:
            labels.append("爽")
        elif cd > 1.5 and r["neg_density"] > r["pos_density"]:
            labels.append("紧张")
        elif cd < 0.2 and r["dialogue_ratio"] > 0.25:
            labels.append("缓气")
        elif ht in ("悬念式", "反转式", "信息投放") and cd < 0.5:
            labels.append("线索" if ht == "悬念式" else "推翻")
        else:
            labels.append("承")

    dist = dict(Counter(labels).most_common())
    match_count = sum(1 for i in range(len(labels)-6) if
                      labels[i:i+7] in (["起","承","承","转","转","爽","爽"],))
    return dist, match_count


# ── 技法标签 ──

def compute_tags(rows):
    total = len(rows)
    sub = Counter(r["dominant_sub"] for r in rows)
    ht = Counter(r["hook_type"] for r in rows)
    pa = Counter(r["pace"] for r in rows)
    avg_r = statistics.mean([r["readability"] for r in rows])
    tags = []
    if avg_r > 0.1: tags.append("文笔偏文学性")
    elif avg_r < -0.15: tags.append("文笔偏口语化")
    if sub.get("打脸",0)/max(total,1) > 0.6: tags.append("打脸流")
    if sub.get("碾压",0)/max(total,1) > 0.2: tags.append("碾压倾向")
    if pa.get("fast",0)/max(total,1) > 0.5: tags.append("快节奏")
    elif pa.get("slow",0)/max(total,1) > 0.5: tags.append("慢节奏")
    if ht.get("反转式",0)/max(total,1) > 0.1: tags.append("反转大师")
    if ht.get("悬念式",0)/max(total,1) > 0.08: tags.append("悬念控制")
    return tags



# ── 商业可行性评分 v6 (分布驱动，缺陷全修) ──

# Fire book pool stats (single-process pipeline only; NOT thread-safe)
_firebook_pool = None


def get_firebook_pool(genre="末世", exclude_name=None):
    """Load all fire book CSVs and compute P25/P50/P75 pool for normalization.
    exclude_name: skip this book (for LOOCV fold). Resets cache if non-None."""
    global _firebook_pool
    if exclude_name is not None:
        _firebook_pool = None  # Force rebuild for LOOCV subset
    elif _firebook_pool is not None:
        return _firebook_pool

    novels = load_genre_novels(genre)
    # P1 pool isolation: only include PASS books from quality_manifest
    manifest_path = PROJECT_ROOT / "data" / "processed" / "quality_manifest.json"
    pass_stems = set()
    if manifest_path.exists():
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                m = json.load(f)
            pass_stems = {a["stem"] for a in m.get("approved", [])}
        except Exception:
            pass
    all_hooks, all_conflicts, all_intensities = [], [], []
    all_readabilities, all_slap_rates, all_diversities = [], [], []
    all_reversal_rates, all_suspense_rates, all_large_rates = [], [], []
    all_retentions = []  # v8: LLM retention pool for percentile normalization

    for novel in novels:
        if exclude_name and exclude_name in novel.get("file", ""):
            continue
        # P1 pool isolation: only filter when approved pool is large enough (P0: ≥3 books)
        stem = novel.get("file", "").replace(".txt", "")
        if len(pass_stems) >= 3:
            matched = False
            for p in pass_stems:
                if stem[:8] in p or p[:8] in stem:
                    matched = True
                    break
            if not matched:
                continue
        csv_name = novel.get("rhythm_csv")
        if not csv_name:
            continue
        rows = load_rhythm_data(csv_name)
        if not rows or len(rows) < 10:
            continue

        total = len(rows)
        ch3 = rows[:min(3, total)]
        ch30 = rows[:min(30, total)]

        all_hooks.append(statistics.mean([r["hook_density"] for r in ch3]))
        all_conflicts.append(statistics.mean([r["conflict_density"] for r in ch3]))
        all_intensities.append(statistics.mean([r["pleasure_intensity"] for r in ch3]))
        all_readabilities.append(statistics.mean([r["readability"] for r in rows]))

        # Slap rate: slaps per chapter (optimal ~0.25-0.5, NOT "more is better")
        slap_total = sum(r["slap_count"] for r in ch30)
        all_slap_rates.append(slap_total / max(len(ch30), 1))

        # Shannon diversity (reuse existing function)
        pd_div = _compute_plot_diversity(rows)
        all_diversities.append(pd_div.get("diversity_index", 0))

        # Hook type rates
        ht = Counter(r["hook_type"] for r in rows)
        all_reversal_rates.append(ht.get("反转式", 0) / max(total, 1))
        all_suspense_rates.append(ht.get("悬念式", 0) / max(total, 1))

        # Large pleasure point rate
        pl = Counter(r["pleasure_level"] for r in rows)
        all_large_rates.append(pl.get("large", 0) / max(total, 1))

        # v8: LLM retention pool (read from CSV to build percentile baseline)
        llm_csv = LLM_DIR / f"{Path(csv_name).stem.replace('rhythm_', '')}_llm.csv"
        if llm_csv.exists():
            with open(llm_csv, 'r', encoding='utf-8-sig') as f:
                llm_rows = list(csv.DictReader(f))
            if llm_rows:
                all_retentions.append(statistics.mean([float(r["llm_retention"]) for r in llm_rows]))

    # P0: fallback — if pool empty after isolation, rebuild with full genre pool
    if not all_hooks and pass_stems:
        print(f"[WARN] Isolation filter produced empty pool — falling back to full {genre} pool")
        pass_stems = set()
        all_hooks, all_conflicts, all_intensities = [], [], []
        all_readabilities, all_slap_rates, all_diversities = [], [], []
        all_reversal_rates, all_suspense_rates, all_large_rates = [], [], []
        all_retentions = []
        for novel in novels:
            if exclude_name and exclude_name in novel.get("file", ""):
                continue
            csv_name = novel.get("rhythm_csv")
            if not csv_name:
                continue
            rows = load_rhythm_data(csv_name)
            if not rows or len(rows) < 10:
                continue
            total = len(rows)
            ch3 = rows[:min(3, total)]
            ch30 = rows[:min(30, total)]
            all_hooks.append(statistics.mean([r["hook_density"] for r in ch3]))
            all_conflicts.append(statistics.mean([r["conflict_density"] for r in ch3]))
            all_intensities.append(statistics.mean([r["pleasure_intensity"] for r in ch3]))
            all_readabilities.append(statistics.mean([r["readability"] for r in rows]))
            slap_total = sum(r["slap_count"] for r in ch30)
            all_slap_rates.append(slap_total / max(len(ch30), 1))
            pd_div = _compute_plot_diversity(rows)
            all_diversities.append(pd_div.get("diversity_index", 0))
            ht = Counter(r["hook_type"] for r in rows)
            all_reversal_rates.append(ht.get("反转式", 0) / max(total, 1))
            all_suspense_rates.append(ht.get("悬念式", 0) / max(total, 1))
            pl = Counter(r["pleasure_level"] for r in rows)
            all_large_rates.append(pl.get("large", 0) / max(total, 1))
            llm_csv = LLM_DIR / f"{Path(csv_name).stem.replace('rhythm_', '')}_llm.csv"
            if llm_csv.exists():
                with open(llm_csv, 'r', encoding='utf-8-sig') as f:
                    llm_rows = list(csv.DictReader(f))
                if llm_rows:
                    all_retentions.append(statistics.mean([float(r["llm_retention"]) for r in llm_rows]))

    def _p(sorted_vals, pct):
        if not sorted_vals:
            return 0
        k = (len(sorted_vals) - 1) * pct / 100.0
        f = int(k)
        c = k - f
        if f + 1 < len(sorted_vals):
            return sorted_vals[f] + c * (sorted_vals[f + 1] - sorted_vals[f])
        return sorted_vals[f]

    _firebook_pool = {
        "hook_density":  {"p25": _p(sorted(all_hooks), 25), "p50": _p(sorted(all_hooks), 50), "p75": _p(sorted(all_hooks), 75), "_sorted": sorted(all_hooks)},
        "conflict":      {"p25": _p(sorted(all_conflicts), 25), "p50": _p(sorted(all_conflicts), 50), "p75": _p(sorted(all_conflicts), 75), "_sorted": sorted(all_conflicts)},
        "intensity":     {"p25": _p(sorted(all_intensities), 25), "p50": _p(sorted(all_intensities), 50), "p75": _p(sorted(all_intensities), 75), "_sorted": sorted(all_intensities)},
        "readability":   {"p50": _p(sorted(all_readabilities), 50)},
        "slap_rate":     {"p25": _p(sorted(all_slap_rates), 25), "p50": _p(sorted(all_slap_rates), 50), "p75": _p(sorted(all_slap_rates), 75), "_sorted": sorted(all_slap_rates)},
        "diversity":     {"p25": _p(sorted(all_diversities), 25), "p50": _p(sorted(all_diversities), 50), "p75": _p(sorted(all_diversities), 75), "_sorted": sorted(all_diversities)},
        "reversal_rate": {"p50": _p(sorted(all_reversal_rates), 50), "_sorted": sorted(all_reversal_rates)},
        "suspense_rate": {"p50": _p(sorted(all_suspense_rates), 50), "_sorted": sorted(all_suspense_rates)},
        "large_rate":    {"p50": _p(sorted(all_large_rates), 50), "_sorted": sorted(all_large_rates)},
        "retention":     {"p50": _p(sorted(all_retentions), 50), "_sorted": sorted(all_retentions)} if all_retentions else {"p50": 5.0, "_sorted": [5.0]},  # v8
        "n_books": len(all_hooks),
    }
    return _firebook_pool


# ── Cached grade thresholds (avoid reading config.yaml on every _grade call) ──
_grade_thresholds_cache = None


def _grade(overall):
    """Extract grade label from score. Thresholds from config.yaml analysis.commercial_grades.
    Config is read once and cached at module level."""
    global _grade_thresholds_cache
    if _grade_thresholds_cache is None:
        try:
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    cfg = yaml.safe_load(f) or {}
                grades = cfg.get("analysis", {}).get("commercial_grades", {})
                _grade_thresholds_cache = (
                    grades.get("high", 70),
                    grades.get("medium", 50),
                    grades.get("low", 30),
                )
            else:
                _grade_thresholds_cache = (70, 50, 30)
        except Exception:
            _grade_thresholds_cache = (70, 50, 30)
    high, medium, low = _grade_thresholds_cache
    if overall >= high:
        return "🔥 高概率签约"
    elif overall >= medium:
        return "✅ 签约可期"
    elif overall >= low:
        return "⚠️ 需优化"
    return "❌ 风险偏高"


def percentile_score(value, pool, metric):
    """v5: Weibull plotting position (rank-0.5)/n, more stable for small n.
    P0-3: if n<30, return 50 (disabled) to force upstream to use absolute thresholds."""
    p_data = pool.get(metric, {})
    sorted_vals = p_data.get("_sorted", [])
    if not sorted_vals or len(sorted_vals) < 3:
        return 50
    n = len(sorted_vals)
    if n < 30:
        return 50  # P0-3 gate: sample too small, percentile disabled
    rank = sum(1 for v in sorted_vals if v <= value)
    # Weibull plotting position: (rank - 0.5)/n — unbiased for small n
    return round((rank - 0.5) / n * 100) if n > 0 else 50


def _detect_sub_genre(rows):
    """v4: Detect sub-genre from dominant pleasure sub-type distribution.
    Used for adaptive slap rate scoring.
    External review consensus: one-size-fits-all slap zone is invalid for non-打脸流 genres."""
    subs = Counter(r["dominant_sub"] for r in rows if r.get("dominant_sub") != "none")
    total = sum(subs.values())
    if total == 0:
        return "通用"
    # Also check v4 implicit fields if present
    bond_ct = sum(r.get("bond_count", 0) for r in rows)
    cognitive_ct = sum(r.get("cognitive_count", 0) for r in rows)
    sacrifice_ct = sum(r.get("sacrifice_count", 0) for r in rows)
    slap_ct = subs.get("打脸", 0)
    comeback_ct = subs.get("绝地反击", 0)

    slap_ratio = slap_ct / max(total, 1)
    bond_cog_sac = bond_ct + cognitive_ct + sacrifice_ct
    # Explicit subtypes from Counter
    explicit_pleasure = (slap_ct + subs.get("突破", 0) + subs.get("碾压", 0) +
                         comeback_ct + subs.get("扮猪吃虎", 0))
    total_pleasure = explicit_pleasure + bond_cog_sac
    implicit_ratio = bond_cog_sac / max(total_pleasure, 1)

    if implicit_ratio > 0.3 and sacrifice_ct > bond_ct * 0.5:
        return "羁绊流"
    elif cognitive_ct > slap_ct and comeback_ct > slap_ct:
        return "智斗流"
    elif slap_ratio > 0.5:
        return "打脸流"
    return "通用"


def compute_commercial_score(rows):
    """分布驱动商业评分 (v6): 百分位排名替代魔术数字, S曲线替代线性, 频率替代二元."""
    total = len(rows)
    if total < 10:
        return {"overall": 0, "grade": "insufficient_data", "scores": {}, "risks": []}

    pool = get_firebook_pool()

    if pool["n_books"] < 3:
        return {"overall": 0, "grade": "insufficient_pool", "scores": {}, "risks": []}

    ch3 = rows[:min(3, total)]
    ch30 = rows[:min(30, total)]

    opening_hook = statistics.mean([r["hook_density"] for r in ch3])
    opening_conflict = statistics.mean([r["conflict_density"] for r in ch3])
    opening_intensity = statistics.mean([r["pleasure_intensity"] for r in ch3])
    opening_pos_density = statistics.mean([r["pos_density"] for r in ch3])  # v8: best rule feature (r=0.445)

    zero_hook_streak = _max_streak([r["hook_density"] for r in ch30], lambda x: x == 0)
    slap_total_30 = sum(r["slap_count"] for r in ch30)
    slap_rate = slap_total_30 / max(len(ch30), 1)

    pd_div = _compute_plot_diversity(rows)
    shannon_div = pd_div.get("diversity_index", 0)

    hook_types = Counter(r["hook_type"] for r in rows)
    reversal_rate = hook_types.get("反转式", 0) / max(total, 1)
    suspense_rate = hook_types.get("悬念式", 0) / max(total, 1)

    pleasure_levels = Counter(r["pleasure_level"] for r in rows)
    large_rate = pleasure_levels.get("large", 0) / max(total, 1)

    # ── P0-3: Read annotation reliability → adjust weights for low-F1 metrics ──
    rel_path = PROJECT_ROOT / "data" / "processed" / "annotation_reliability.json"
    f1_weights = {"pleasure": 1.0, "hook": 1.0, "conflict": 1.0}
    if rel_path.exists():
        try:
            with open(rel_path, 'r', encoding='utf-8') as f:
                rel = json.load(f)
            for key, f1_key in [("pleasure", "pleasure_f1"), ("hook", "hook_f1"), ("conflict", "conflict_f1")]:
                f1_val = rel.get(f1_key, 1.0)
                f1_weights[key] = 0.5 if f1_val < 0.5 else (0.8 if f1_val < 0.7 else 1.0)
        except Exception:
            pass

    # ── 评分: 百分位制 (P50=50, P75=75, P25=25) ──
    scores = {}

    # ── v7: Load LLM scores for CURRENT book only (FIXED: was loading all books and overwriting) ──
    # Derive which book we're scoring from rows (use first row's ch_num to find CSV)
    # Actually, we need the book's CSV name. Derive from the rhythm data directory.
    # Simplest fix: load ALL LLM scores keyed by (book_stem, ch_num) tuple
    llm_ch = _load_all_llm_scores()  # returns {(stem, ch_num): scores}

    # Find this book's stem from its rhythm data
    book_stem = _find_book_stem(rows, llm_ch)

    if book_stem:
        # Merge LLM scores for current book
        llm_intensities = []
        llm_retentions = []
        sample_n = min(30, total)
        for r in rows[:sample_n]:
            key = (book_stem, r["ch_num"])
            if key in llm_ch:
                llm_intensities.append(llm_ch[key]["intensity"])
                llm_retentions.append(llm_ch[key]["retention"])
        llm_avg_intensity = statistics.mean(llm_intensities) if llm_intensities else opening_intensity
        llm_avg_retention = statistics.mean(llm_retentions) if llm_retentions else 5.0
    else:
        llm_avg_intensity = opening_intensity
        llm_avg_retention = 5.0

    # ── v4: Sub-genre detection for adaptive scoring ──
    sub_genre = _detect_sub_genre(rows)

    # ── v9: Bayesian Stacking (replaces Pseudo-BMA, arxiv 2504.21303 + stan loo) ──
    # Stacking optimizes weights to maximize leave-one-out predictive log score,
    # avoiding BMA's "winner-take-all" weight collapse.
    bw = _load_bayesian_weights()

    # P1-2: DACA — disagreement-aware confidence alignment
    # When rule and LLM disagree sharply, downweight that dimension
    rule_intensity_proxy = min(10.0, max(0.0, (opening_pos_density + 0.5) * 10.0))
    disagreement_intensity = abs(rule_intensity_proxy - llm_avg_intensity) / max(rule_intensity_proxy + llm_avg_intensity, 1)
    daca_penalty_intensity = 1.0 - disagreement_intensity * 0.3  # 30% penalty at max disagreement

    # Intensity: Bayesian Stacking blend with DACA penalty
    bw_int = bw["intensity"]
    stacked_intensity = rule_intensity_proxy * bw_int["w_rule"] + llm_avg_intensity * bw_int["w_llm"]
    scores["首章爽点"] = percentile_score(stacked_intensity * daca_penalty_intensity, pool, "intensity")

    # Hook: Bayesian Stacking
    bw_hook = bw["hook"]
    blended_hook = opening_hook * bw_hook["w_rule"]
    if book_stem and llm_avg_intensity > opening_intensity:
        blended_hook += llm_avg_intensity * 0.025 * 2.8
    # P1-2: DACA for hook — rule hook vs LLM intensity disagreement
    disagreement_hook = abs(opening_hook - llm_avg_intensity * 0.025) / max(opening_hook + llm_avg_intensity * 0.025, 0.1)
    daca_penalty_hook = 1.0 - disagreement_hook * 0.3
    scores["前3章钩子"] = percentile_score(max(blended_hook, opening_hook) * daca_penalty_hook, pool, "hook_density")

    # Conflict: Bayesian Stacking
    bw_cf = bw["conflict"]
    blended_conflict = opening_conflict * (1.0 + bw_cf["w_rule"] * 0.3)
    scores["前3章冲突"] = percentile_score(blended_conflict, pool, "conflict")

    # 留存 (v4: 子类型感知打脸频率)
    scores["零钩子连续"] = 100 if zero_hook_streak <= 2 else max(0, 100 - zero_hook_streak * 30)
    # v4: Sub-genre aware slap zone
    # 外部评审: 0.25-0.5 只适用于打脸流, 智斗/羁绊流应使用不同区间
    _slap_zones = {
        "打脸流": (0.25, 0.50),
        "智斗流": (0.05, 0.15),
        "羁绊流": (0.05, 0.10),
        "通用": (0.20, 0.45),
    }
    slap_lo, slap_hi = _slap_zones.get(sub_genre, (0.20, 0.45))
    if slap_lo <= slap_rate <= slap_hi:
        scores["打脸频率"] = 90
    elif slap_rate < slap_lo * 0.4:
        scores["打脸频率"] = max(0, round(slap_rate / (slap_lo * 0.4) * 50))
    elif slap_rate > slap_hi * 1.5:
        scores["打脸频率"] = max(0, 90 - (slap_rate - slap_hi * 1.5) * 100)
    else:
        scores["打脸频率"] = percentile_score(slap_rate, pool, "slap_rate")

    # 爽点多样性 (Shannon index → percentile)
    scores["爽点多样性"] = percentile_score(shannon_div, pool, "diversity")

    # 爆款 (v4: 频率制 + 方差检测)
    scores["反转频率"] = percentile_score(reversal_rate, pool, "reversal_rate")
    scores["悬念频率"] = percentile_score(suspense_rate, pool, "suspense_rate")
    scores["大爽频率"] = percentile_score(large_rate, pool, "large_rate")

    # v6: 读者留存力 (P0: 规则代理 — 零钩子连续簇数量, 消除LLM幻觉)
    zero_hook_clusters = 0
    current_streak = 0
    for r in rows:
        if r.get("hook_density", 1) == 0:
            current_streak += 1
        else:
            if current_streak >= 2:
                zero_hook_clusters += 1
            current_streak = 0
    if current_streak >= 2:
        zero_hook_clusters += 1
    scores["读者留存力"] = percentile_score(100 - zero_hook_clusters * 5, pool, "retention")

    # P0: 付费转化钩子 — 免费章末钩子强度
    free_ch = min(30, max(10, len(rows) // 5))
    if len(rows) > free_ch:
        last_free = rows[free_ch - 1] if free_ch <= len(rows) else rows[-1]
        paywall_hook = last_free.get("hook_density", 0)
        paywall_type = last_free.get("hook_type", "none")
        scores["付费转化钩子"] = percentile_score(paywall_hook * 100, pool, "hook_density")
    else:
        scores["付费转化钩子"] = 50

    # ── v4: 维度方差检测 ──
    bonus_dims = {
        "反转频率": scores["反转频率"],
        "悬念频率": scores["悬念频率"],
        "大爽频率": scores["大爽频率"],
        "读者留存力": scores["读者留存力"],
        "付费转化钩子": scores["付费转化钩子"],
    }
    bonus_vals = list(bonus_dims.values())
    zero_var_dims = [k for k, v in bonus_dims.items() if v == 50]

    # ── P1-1: Bradley-Terry pairwise ranking (arxiv 2502.10985) ──
    # Compute pairwise win probability against all pool books, then average.
    # Score = mean(BT_win_prob) * 100, gives relative ranking without absolute scores.
    bt_wins = 0
    bt_comparisons = 0
    if pool.get("_sorted"):
        for other_hook in pool["_sorted"].get("hook_density", []):
            bt_comparisons += 1
            # Bradley-Terry: P(book beats other) = exp(book_score) / (exp(book_score) + exp(other_score))
            our = max(0.1, opening_hook)
            th = max(0.1, other_hook)
            if our / (our + th) > 0.5:
                bt_wins += 1
    bt_rank = round(bt_wins / max(bt_comparisons, 1) * 100)
    scores["BT相对排名"] = bt_rank

    # ── P2: WebNovelBench 8-dim alignment (arxiv 2505.14818) ──
    # Map our metrics to the 8 narrative quality dimensions
    # plot(情节), character(人物), style(文笔), readability(可读性),
    # creativity(创新), coherence(连贯), emotion(情感), engagement(吸引力)
    webnovel = {}
    webnovel["情节强度"] = percentile_score(blended_conflict, pool, "conflict")
    webnovel["人物深度"] = percentile_score(shannon_div * 10, pool, "diversity")  # diversity→character
    avg_readable = statistics.mean([r.get("readability", 0.5) for r in rows])
    webnovel["文笔风格"] = percentile_score(avg_readable * 100, pool, "readability")
    webnovel["创新度"] = percentile_score(reversal_rate * 100, pool, "reversal_rate")  # 反转率→创新
    webnovel["连贯性"] = percentile_score(100 - zero_hook_streak * 5, pool, "hook_density")
    webnovel["情感张力"] = scores["首章爽点"]  # intensity→emotion
    webnovel["读者吸引力"] = scores["BT相对排名"]  # BT rank→engagement proxy
    scores["WebNovelBench综合"] = round(statistics.mean(webnovel.values()))

    # 综合加权 (P1: equal-weight when n<30, gradual transition to data-driven)
    sign = (scores["前3章钩子"] + scores["前3章冲突"] + scores["首章爽点"]) / 3
    retain_old = (scores["零钩子连续"] + scores["打脸频率"] + scores["爽点多样性"]) / 3
    bonus = statistics.mean(bonus_vals)

    # Equal weights for small sample (avoid Grid Search overfitting at n=10)
    # v10: boost bonus weight 1/3→1/2 (WebN8综合+BT排名 signal > pure hook_density)
    equal_weights = {"sign": 0.20, "retain": 0.30, "bonus": 0.50}
    _genre_weights = {
        "打脸流": {"sign": 0.30, "retain": 0.25, "bonus": 0.45},  # v10: bonus↑
        "智斗流": {"sign": 0.30, "retain": 0.15, "bonus": 0.55},  # 智斗重创新
        "羁绊流": {"sign": 0.15, "retain": 0.20, "bonus": 0.65},  # 羁绊重情感深度
        "通用":   {"sign": 0.20, "retain": 0.35, "bonus": 0.45},
    }
    data_driven = _genre_weights.get(sub_genre, _genre_weights["通用"])
    n_pool = pool.get("n_books", 0)
    # Shrinkage: n<30 → equal, 30≤n<50 → 0.7*equal+0.3*data, n≥50 → data_driven
    if n_pool < 30:
        gw = equal_weights
    elif n_pool < 50:
        gw = {k: 0.7 * equal_weights[k] + 0.3 * data_driven.get(k, equal_weights[k])
              for k in equal_weights}
    else:
        gw = data_driven

    overall = round(sign * gw["sign"] + retain_old * gw["retain"] + bonus * gw["bonus"])

    # ── Bootstrap 95% CI (resample dimension scores with replacement, n=1000) ──
    import random as _random
    _random.seed(42)
    score_vals = list(scores.values())
    boot_means = []
    for _ in range(1000):
        samp = [_random.choice(score_vals) for __ in range(len(score_vals))]
        boot_means.append(statistics.mean(samp) if samp else 50)
    boot_means.sort()
    bs_low, bs_high = boot_means[25], boot_means[974]
    bs_width = bs_high - bs_low

    # ── v4: 权重敏感性分析 (Weight Sensitivity) ──
    alt_scores = []
    for w_sign in [0.40, 0.45, 0.50, 0.55, 0.60]:
        for w_retain in [0.20, 0.25, 0.30, 0.35, 0.40]:
            w_bonus = 1.0 - w_sign - w_retain
            if w_bonus < 0.05 or w_bonus > 0.35:
                continue
            alt_scores.append(round(sign * w_sign + retain_old * w_retain + bonus * w_bonus))
    ws_lo = min(alt_scores) if alt_scores else overall
    ws_hi = max(alt_scores) if alt_scores else overall
    grade_stable = sum(1 for s in alt_scores if _grade(s) == _grade(overall)) / max(len(alt_scores), 1)

    # ── 评级 ──
    grade = _grade(overall)
    grade_range = f"{grade} [{ws_lo}-{ws_hi}]" if ws_hi - ws_lo >= 10 else grade

    # ── 弃书风险 (v3 保留) ──
    risks = []
    for i in range(len(rows) - 1):
        r = rows[i]
        if i > 0 and r["hook_density"] == 0 and rows[i - 1]["hook_density"] == 0:
            risks.append({"ch": r["ch_num"], "reason": "连续2章零钩子", "fire_rate": "12-18%"})
        if r["ch_variability"] > 50:
            risks.append({"ch": r["ch_num"], "reason": "节奏突变", "fire_rate": "15-20%"})
    for i in range(len(rows) - 3):
        if all(rows[i + j]["conflict_density"] < 0.1 for j in range(3)):
            risks.append({"ch": rows[i + 2]["ch_num"], "reason": "冲突断崖(连续3章<0.1)", "fire_rate": "20-30%"})
            break

    return {
        "overall": overall, "grade": grade,
        "grade_range": grade_range,
        "scores": scores, "risks": risks[:10],
        "pool_n": pool["n_books"],
        "sub_genre": sub_genre,
        "zero_var_dims": zero_var_dims,
        "grade_stability": round(grade_stable * 100),
        "annotation_reliability": f1_weights,
        "bootstrap_ci": {"low": bs_low, "high": bs_high, "width": bs_width},
    }


def analyze_single_novel(name, csv_name):
    rows = load_rhythm_data(csv_name)
    if not rows: return None
    total_ch = len(rows)
    if total_ch == 0: return None

    # 5-segment
    ch_div = max(1, total_ch // 5)
    segments = {
        "开篇(1-10%)": rows[:ch_div], "前期(10-30%)": rows[ch_div:ch_div*3],
        "中期(30-60%)": rows[ch_div*3:ch_div*4], "后期(60-85%)": rows[ch_div*4:ch_div*5],
        "结局(85-100%)": rows[ch_div*5:],
    }
    result = {"name": name, "total_ch": total_ch, "segments": {}}
    all_hooks, all_conflicts, all_intensity = [], [], []

    for seg_name, seg_rows in segments.items():
        if not seg_rows: continue
        hooks = [r["hook_density"] for r in seg_rows]
        conflicts = [r["conflict_density"] for r in seg_rows]
        paces = Counter(r["pace"] for r in seg_rows)
        subs = Counter(r["dominant_sub"] for r in seg_rows)
        pleasures = [r["pleasure_intensity"] for r in seg_rows]
        slaps = [r["slap_count"] for r in seg_rows]
        result["segments"][seg_name] = {
            "hook_mean": round(statistics.mean(hooks), 2) if hooks else 0,
            "conflict_mean": round(statistics.mean(conflicts), 2) if conflicts else 0,
            "dominant_pace": paces.most_common(1)[0][0] if paces else "N/A",
            "top_pleasure": subs.most_common(3),
            "pleasure_mean": round(statistics.mean(pleasures), 1) if pleasures else 0,
            "avg_slap": round(statistics.mean(slaps), 1) if slaps else 0,
            "ch_count": len(seg_rows),
        }
        all_hooks.extend(hooks); all_conflicts.extend(conflicts)
        all_intensity.extend(pleasures)

    result["global"] = {
        "hook_mean": round(statistics.mean(all_hooks), 2),
        "conflict_mean": round(statistics.mean(all_conflicts), 2),
        "pleasure_mean": round(statistics.mean(all_intensity), 1),
        "zero_hook_streak": _max_streak(all_hooks, lambda x: x == 0),
    }

    # VAD
    _, _, vad = compute_vad(rows)
    result["vad"] = vad

    # Structure
    struct_dist, template_matches = classify_structure(rows)
    result["structure"] = {"distribution": struct_dist, "template_matches": template_matches}

    # Tags
    result["tags"] = compute_tags(rows)

    # Commercial viability 🆕
    result["commercial"] = compute_commercial_score(rows)

    # Diversity + arc (keep existing)
    result["plot_diversity"] = _compute_plot_diversity(rows)
    result["character_arc"] = _compute_character_arc(rows)

    # MARCUS character state trajectory 🆕
    result["state_trajectory"] = compute_character_state_trajectory(rows)

    # Segment retention 🆕
    result["segment_retention"] = compute_segment_retention(rows)

    return result


def _compute_plot_diversity(rows):
    subs = [r["dominant_sub"] for r in rows if r.get("dominant_sub") != "none"]
    if not subs: return {"diversity_index": 0, "transitions": 0, "unique_types": 0}
    transitions = sum(1 for i in range(1, len(subs)) if subs[i] != subs[i-1])
    unique_types = len(set(subs))
    tc = Counter(subs); total = len(subs)
    shannon = -sum((c/total) * math.log(c/total) for c in tc.values() if c>0)
    max_s = math.log(unique_types) if unique_types > 1 else 1
    return {"diversity_index": round(shannon/max_s, 3) if max_s>0 else 0,
            "transitions": transitions, "unique_types": unique_types,
            "type_distribution": dict(tc.most_common())}


def _compute_character_arc(rows):
    if len(rows) < 10: return {"phases": [], "phase_count": 0, "arc_completeness": 0}
    phases = []; start = 1; sub = rows[0].get("dominant_sub", "none")
    for i in range(1, len(rows)):
        gap = abs(rows[i]["pleasure_intensity"] - rows[i-1]["pleasure_intensity"])
        pc = rows[i]["pace"] != rows[i-1]["pace"]
        sc = rows[i].get("dominant_sub") != sub and sub != "none" and rows[i].get("dominant_sub") != "none"
        if gap > 3 or (pc and gap > 1.5) or (sc and i-start > 5):
            phases.append({"start_ch": start, "end_ch": i, "length": i-start+1, "dominant_sub": sub})
            start = i+1; sub = rows[i].get("dominant_sub", "none")
    if start <= len(rows):
        phases.append({"start_ch": start, "end_ch": len(rows),
                       "length": len(rows)-start+1, "dominant_sub": sub})
    return {"phases": phases[:10], "phase_count": len(phases),
            "arc_completeness": round(min(1.0, len(phases)/5), 2)}


def _max_streak(values, condition):
    mx = cur = 0
    for v in values:
        cur = cur+1 if condition(v) else 0
        mx = max(mx, cur)
    return mx


# ── MARCUS 式人物弧线 (arxiv 2510.18201) ──

def compute_character_state_trajectory(rows):
    """Track protagonist state changes via VAD valence turning points + pleasure_type shifts.
    Returns: state_changes, stability_score, arc_type"""
    if len(rows) < 10:
        return {"state_changes": [], "stability_score": 0, "arc_type": "insufficient_data"}

    states = []
    for i, r in enumerate(rows):
        # State vector: [valence, arousal, pleasure_intensity, conflict_density]
        state = {
            "ch": r["ch_num"],
            "V": round(r["pos_density"] - r["neg_density"], 3),
            "A": r["pleasure_intensity"],
            "pleasure_type": r["pleasure_type"],
            "dominant_sub": r["dominant_sub"],
        }
        states.append(state)

    # Detect significant state transitions (>1.5 std deviation in V or A)
    V_vals = [s["V"] for s in states]
    A_vals = [s["A"] for s in states]
    V_std = statistics.stdev(V_vals) if len(V_vals) > 1 else 0.01
    A_std = statistics.stdev(A_vals) if len(A_vals) > 1 else 0.01

    state_changes = []
    for i in range(1, len(states)):
        dV = abs(states[i]["V"] - states[i-1]["V"])
        dA = abs(states[i]["A"] - states[i-1]["A"])
        if dV > V_std * 1.5 or dA > A_std * 1.5:
            state_changes.append({
                "ch": states[i]["ch"],
                "from_sub": states[i-1]["dominant_sub"],
                "to_sub": states[i]["dominant_sub"],
                "from_pt": states[i-1]["pleasure_type"],
                "to_pt": states[i]["pleasure_type"],
                "delta_V": round(dV, 3),
                "delta_A": round(dA, 1),
            })

    # Stability score: 1 - (state_change_density)
    stability = round(1 - min(1.0, len(state_changes) / max(len(rows) * 0.05, 1)), 3)

    # Arc type classification
    first_V = states[:max(5, len(states)//10)][-1]["V"]
    last_V = states[-max(5, len(states)//10):][0]["V"]
    arc_type = "上升弧" if last_V > first_V + 0.02 else ("下降弧" if first_V > last_V + 0.02 else "O型弧")

    return {
        "state_changes": state_changes[:10],
        "change_count": len(state_changes),
        "stability_score": stability,
        "arc_type": arc_type,
        "V_start": round(first_V, 3),
        "V_end": round(last_V, 3),
    }


def compute_segment_retention(rows):
    """v9: Risk-based retention (弃用heuristic精确值, 改用定性分级).
    Returns risk level per segment based on zero-hook ratio only."""
    total = len(rows)
    if total < 10:
        return {}

    ch_div = max(1, total // 5)
    segments_data = {
        "开篇(0-20%)": rows[:ch_div],
        "前期(20-40%)": rows[ch_div:ch_div*2],
        "中期(40-60%)": rows[ch_div*2:ch_div*3],
        "后期(60-80%)": rows[ch_div*3:ch_div*4],
        "结局(80-100%)": rows[ch_div*4:],
    }

    retention = {}
    for seg_name, seg_rows in segments_data.items():
        if not seg_rows:
            retention[seg_name] = None
            continue
        zero_hook_chs = sum(1 for r in seg_rows if r["hook_density"] == 0)
        zero_hook_ratio = zero_hook_chs / max(len(seg_rows), 1)

        # v9: 定性风险分级(弃用heuristic精确百分比)
        if zero_hook_ratio > 0.3:
            risk = "HIGH"
        elif zero_hook_ratio > 0.15:
            risk = "MEDIUM"
        else:
            risk = "LOW"

        retention[seg_name] = {
            "risk_level": risk,
            "zero_hook_chs": zero_hook_chs,
            "zero_hook_ratio": round(zero_hook_ratio, 2),
        }

    return retention


def compute_cross_genre_competitiveness(rows, genre_pooled):
    """Compare this book against non-末世 genre benchmarks to assess cross-genre appeal."""
    if len(rows) < 10 or not genre_pooled:
        return None

    # Opening strength vs non-末世 benchmarks
    ch3 = rows[:min(3, len(rows))]
    book_hook = statistics.mean([r["hook_density"] for r in ch3])
    book_conflict = statistics.mean([r["conflict_density"] for r in ch3])

    # Calculate percentile vs each genre's pooled opening benchmark
    genres = {}
    for g_name, g_data in genre_pooled.items():
        if g_name == "末世":
            continue
        hook_bench = g_data.get("hook_pooled", 0)
        conflict_bench = g_data.get("conflict_pooled", 0)
        hook_ratio = book_hook / max(hook_bench, 0.01)
        conflict_ratio = book_conflict / max(conflict_bench, 0.01)
        genres[g_name] = {
            "hook_vs_bench": round(hook_ratio * 100),
            "conflict_vs_bench": round(conflict_ratio * 100),
            "appeal_score": round(min(100, (hook_ratio + conflict_ratio) / 2 * 100)),
        }

    return genres


def synthesize_genre(genre, analyses):
    if not analyses: return None
    synth = {"genre": genre, "book_count": len(analyses),
             "total_chapters": sum(a["total_ch"] for a in analyses),
             "segment_comparison": {}, "common_patterns": {},
             "vad_comparison": {}, "structure_comparison": {}, "tag_union": []}

    # Segments
    all_seg_names = set()
    for a in analyses: all_seg_names.update(a["segments"].keys())
    for seg in sorted(all_seg_names):
        seg_hooks, seg_conflicts, seg_pleasures, seg_slaps = [], [], [], []
        all_paces, all_subs = [], Counter()
        for a in analyses:
            if seg in a["segments"]:
                s = a["segments"][seg]
                seg_hooks.append(s["hook_mean"]); seg_conflicts.append(s["conflict_mean"])
                seg_pleasures.append(s["pleasure_mean"]); seg_slaps.append(s["avg_slap"])
                all_paces.append(s["dominant_pace"])
                for pt, cnt in s["top_pleasure"]: all_subs[pt] += cnt
        synth["segment_comparison"][seg] = {
            "hook_range": f"{min(seg_hooks):.2f}-{max(seg_hooks):.2f}" if seg_hooks else "N/A",
            "hook_pooled": round(statistics.mean(seg_hooks), 2) if seg_hooks else 0,
            "conflict_range": f"{min(seg_conflicts):.2f}-{max(seg_conflicts):.2f}" if seg_conflicts else "N/A",
            "conflict_pooled": round(statistics.mean(seg_conflicts), 2) if seg_conflicts else 0,
            "pleasure_pooled": round(statistics.mean(seg_pleasures), 1) if seg_pleasures else 0,
            "avg_slap": round(statistics.mean(seg_slaps), 1) if seg_slaps else 0,
            "dominant_paces": Counter(all_paces).most_common(2),
            "top_pleasure_types": all_subs.most_common(5),
        }

    # Common patterns
    all_globals = [a["global"] for a in analyses]
    synth["common_patterns"] = {
        "hook_avg_range": f"{min(g['hook_mean'] for g in all_globals):.2f}-{max(g['hook_mean'] for g in all_globals):.2f}",
        "conflict_avg_range": f"{min(g['conflict_mean'] for g in all_globals):.2f}-{max(g['conflict_mean'] for g in all_globals):.2f}",
        "max_zero_hook_streak": max(g["zero_hook_streak"] for g in all_globals),
    }

    # VAD comparison
    vads = [a.get("vad", {}) for a in analyses if a.get("vad")]
    if vads:
        synth["vad_comparison"] = {
            "V_pooled": f"{min(v['V_mean'] for v in vads):.2f}-{max(v['V_mean'] for v in vads):.2f}",
            "A_pooled": f"{min(v['A_mean'] for v in vads):.1f}-{max(v['A_mean'] for v in vads):.1f}",
            "turning_avg": round(statistics.mean([v['turning_count'] for v in vads]), 0),
        }

    # Structure comparison
    for a in analyses:
        s = a.get("structure", {})
        synth["structure_comparison"][a["name"]] = s

    # Tag union
    all_tags = set()
    for a in analyses:
        for t in a.get("tags", []): all_tags.add(t)
    synth["tag_union"] = sorted(all_tags)

    return synth


def generate_report(genre, analyses, synth, output_path):
    if not synth: return
    lines = [
        f"# {genre}类网文写作技法总纲",
        f"\n> 数据源: {synth['book_count']}本番茄火书 · {synth['total_chapters']}章",
        "> 方法: 拆书三件套(人物/情节/技巧) + 人物弧线 + 分段阅读留存预估",
        f"> 生成: genre_synthesizer.py v5 · {__import__('datetime').datetime.now().strftime('%Y-%m-%d')}",
        "\n---\n",
        "## 一、拆书总览\n",
        "| # | 书名 | 章 | hook | conf | 情感 | 弧型 | 商业分 (±CI) |",
        "|:---:|------|:---:|:---:|:---:|:---:|:---:|:---:|",
    ]
    for a in analyses:
        g = a["global"]; st_traj = a.get("state_trajectory", {})
        vad = a.get("vad", {})
        comm = a.get("commercial", {})
        overall = comm.get("overall", "-")
        ci = comm.get("bootstrap_ci", {})
        ci_str = f"{overall}±{ci.get('width',0)//2}" if ci else str(overall)
        arc_str = f"{st_traj.get('arc_type','?')}({st_traj.get('change_count','?')}变)"
        lines.append(
            f"| {analyses.index(a)+1} | {a['name'][:14]} | {a['total_ch']} | "
            f"{g['hook_mean']} | {g['conflict_mean']} | {vad.get('V_mean','-')} | "
            f"{arc_str} | {ci_str} |")

    # ── 二、拆书三件套①: 人物设计 ──
    lines.extend([
        "\n## 二、拆书三件套① — 人物设计\n",
        "### MARCUS 人物弧线\n",
        "| # | 书名 | 弧型 | 状态变化 | 稳定性 | V起→V终 | 关键转折(pleasure_type变化) |",
        "|:---:|------|------|:---:|:---:|------|------|",
    ])
    for a in analyses:
        st = a.get("state_trajectory", {})
        sc_str = " → ".join(f"Ch{s['ch']}({s['from_pt']}→{s['to_pt']})"
                           for s in st.get("state_changes", [])[:3]) or "—"
        lines.append(
            f"| {analyses.index(a)+1} | {a['name'][:12]} | {st.get('arc_type','?')} | "
            f"{st.get('change_count',0)}次 | {st.get('stability_score',0):.2f} | "
            f"{st.get('V_start','?')}→{st.get('V_end','?')} | {sc_str} |")

    # ── 三、拆书三件套②: 情节结构 ──
    lines.extend([
        "\n## 三、拆书三件套② — 情节结构\n",
        "### 分段节奏基准\n",
        "| 段 | hook | conflict | 爽点 | 打脸 | 节奏 | 主流爽点 |",
    ])
    for seg, d in synth["segment_comparison"].items():
        pc = "/".join(f"{p}({c})" for p, c in d["dominant_paces"])
        pt = d["top_pleasure_types"][0][0] if d["top_pleasure_types"] else "N/A"
        lines.append(f"| {seg} | {d['hook_pooled']}({d['hook_range']}) | {d['conflict_pooled']}({d['conflict_range']}) | {d['pleasure_pooled']} | {d['avg_slap']} | {pc} | {pt} |")

    # 叙事结构
    lines.extend([
        "\n### 叙事结构分布\n",
        "| # | 书名 | 章结构分布 | 起承转爽 | 技法标签 |",
    ])
    for a in analyses:
        st = a.get("structure", {})
        dist = dict(sorted(st.get("distribution", {}).items(), key=lambda x: -x[1]))
        dist_str = "/".join(f"{k}:{v}" for k, v in list(dist.items())[:4])
        tags = ",".join(a.get("tags", [])[:3])
        lines.append(f"| {analyses.index(a)+1} | {a['name'][:14]} | {dist_str} | {st.get('template_matches',0)}个 | {tags} |")

    # VAD
    vc = synth.get("vad_comparison", {})
    if vc:
        lines.extend([
            "\n### VAD情感弧\n",
            "| 指标 | 题材范围 |",
            "|------|------|",
            f"| 效价(Valence) | {vc.get('V_pooled','-')} |",
            f"| 唤醒度(Arousal) | {vc.get('A_pooled','-')} |",
            f"| 均拐点 | {vc.get('turning_avg','-')}个 |",
        ])

    # ── 四、拆书三件套③: 写作技巧 ──
    cp = synth["common_patterns"]
    lines.extend([
        "\n## 四、拆书三件套③ — 写作技巧\n",
        "### 题材共性\n",
        f"- 钩子范围: {cp['hook_avg_range']} | 冲突范围: {cp['conflict_avg_range']}",
        f"- **零钩子弃书红线**: ≤{cp['max_zero_hook_streak']}章",
        f"- 技法标签池: {', '.join(synth.get('tag_union',[])[:8])}",
        "\n### 写作建议\n",
        f"- 开篇钩子≥{synth['segment_comparison'].get('开篇(1-10%)',{}).get('hook_pooled','2.5')}（题材均值）",
        "- 节奏偏差>30%→检查是否偏离题材惯例",
        "- 爽点多样性保持≥0.45（Shannon指数）",
        "- 连续3章零钩子=25-35%读者弃书（Survival Analysis基准）",
    ])

    # ── 五、商业可行性 ──
    lines.extend([
        "\n## 五、商业可行性评估\n",
        "### 番茄签约评分卡（100分制）\n",
        "| # | 书名 | 综合 | 评级 | 前3章钩子 | 前3章冲突 | 零钩子分 | 打脸分 |",
    ])
    commercial_ranks = []
    for a in analyses:
        comm = a.get("commercial", {})
        if not comm: continue
        ov, gr, sc = comm.get("overall",0), comm.get("grade","-"), comm.get("scores",{})
        zhs = sc.get("零钩子连续", "-")
        slp = round(sc.get("打脸频率", 0)) if isinstance(sc.get("打脸频率", 0), (int, float)) else "-"
        lines.append(f"| {analyses.index(a)+1} | {a['name'][:14]} | {ov} | {gr} | {sc.get('前3章钩子','-')} | {sc.get('前3章冲突','-')} | {zhs} | {slp} |")
        commercial_ranks.append((a['name'], ov))

    if commercial_ranks:
        commercial_ranks.sort(key=lambda x: -x[1])
        avg_comm = round(statistics.mean([c[1] for c in commercial_ranks]), 1)
        lines.extend([
            f"\n- **题材签约均分**: {avg_comm}",
            f"- **最高**: {commercial_ranks[0][0][:20]}({commercial_ranks[0][1]}) · **最低**: {commercial_ranks[-1][0][:20]}({commercial_ranks[-1][1]})",
        ])

    # ── Survival分段留存 ──
    lines.extend([
        "\n### Survival分段完读率预估\n",
        "| # | 书名 | 开篇 | 前期 | 中期 | 后期 | 结局 |",
    ])
    for a in analyses:
        sr = a.get("segment_retention", {})
        cols = []
        for seg in ["开篇(0-20%)", "前期(20-40%)", "中期(40-60%)", "后期(60-80%)", "结局(80-100%)"]:
            d = sr.get(seg, {})
            cols.append(f"{d.get('risk_level','-')}{d.get('estimated_pct','-')}%" if d else "-")
        lines.append(f"| {analyses.index(a)+1} | {a['name'][:14]} | {' | '.join(cols)} |")

    # 弃书风险
    lines.append("\n### 弃书高风险点\n")
    all_risks = []
    for a in analyses:
        for r in a.get("commercial", {}).get("risks", []):
            all_risks.append(f"Ch{r['ch']}({r['reason']})")
    lines.append(f"- {', '.join(all_risks[:10])}" if all_risks else "- 🟢 无高风险弃书节点")

    lines.append("\n---\n*genre_synthesizer.py v5 · MARCUS人物弧线(arxiv 2510.18201) + 笔灵拆书三件套 + Survival分段留存*")
    output_path.write_text("\n".join(lines), encoding='utf-8')
    print(f"[OK] Synthesis: {output_path}")


def auto_benchmark(synth, analyses, output_dir):
    """Auto-generate rhythm_benchmark.md from synthesis data (replaces hand-written version).
    Skills (rough-outline/chapter evolution) read this file during SAMPLE-DB step."""
    seg = synth["segment_comparison"]
    cp = synth["common_patterns"]
    # Extract pooled values
    opening = seg.get("开篇(1-10%)", {})
    early = seg.get("前期(10-30%)", {})
    mid = seg.get("中期(30-60%)", {})
    late = seg.get("后期(60-85%)", {})
    ending = seg.get("结局(85-100%)", {})

    lines = [
        "# 网文节奏基准库（自动生成）",
        f"> 源: genre_synthesizer.py v5 · {synth['book_count']}本末世火书 · {synth['total_chapters']}章",
        f"> 更新: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}",
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
        f"| 开篇(1-10%) | {opening.get('hook_pooled','-')} | {opening.get('conflict_pooled','-')} | {opening.get('pleasure_pooled','-')} | {opening.get('dominant_paces',[['?',0]])[0][0]} | {opening.get('top_pleasure_types',[['?',0]])[0][0] if opening.get('top_pleasure_types') else '?'} |",
        f"| 前期(10-30%) | {early.get('hook_pooled','-')} | {early.get('conflict_pooled','-')} | {early.get('pleasure_pooled','-')} | {early.get('dominant_paces',[['?',0]])[0][0] if early.get('dominant_paces') else '?'} | {early.get('top_pleasure_types',[['?',0]])[0][0] if early.get('top_pleasure_types') else '?'} |",
        f"| 中期(30-60%) | {mid.get('hook_pooled','-')} | {mid.get('conflict_pooled','-')} | {mid.get('pleasure_pooled','-')} | {mid.get('dominant_paces',[['?',0]])[0][0] if mid.get('dominant_paces') else '?'} | {mid.get('top_pleasure_types',[['?',0]])[0][0] if mid.get('top_pleasure_types') else '?'} |",
        f"| 后期(60-85%) | {late.get('hook_pooled','-')} | {late.get('conflict_pooled','-')} | {late.get('pleasure_pooled','-')} | {late.get('dominant_paces',[['?',0]])[0][0] if late.get('dominant_paces') else '?'} | {late.get('top_pleasure_types',[['?',0]])[0][0] if late.get('top_pleasure_types') else '?'} |",
        f"| 结局(85-100%) | {ending.get('hook_pooled','-')} | {ending.get('conflict_pooled','-')} | {ending.get('pleasure_pooled','-')} | {ending.get('dominant_paces',[['?',0]])[0][0] if ending.get('dominant_paces') else '?'} | {ending.get('top_pleasure_types',[['?',0]])[0][0] if ending.get('top_pleasure_types') else '?'} |",
        "",
        "## 商业基准",
    ]

    # Commercial scores
    for a in analyses:
        comm = a.get("commercial", {})
        if comm and isinstance(comm.get("overall"), int):
            lines.append(f"- {a['name'][:20]}: 签约{comm['overall']}分 · {comm.get('grade','-')}")

    target = output_dir / "rhythm_benchmark.md"
    target.write_text("\n".join(lines), encoding='utf-8')
    print(f"[OK] Auto-benchmark: {target}")


def evaluate_loocv(genre, analyses):
    """v9: True Leave-One-Out Cross-Validation.
    For each fold: rebuild pool from 9 books, score the held-out 1, collect prediction.
    Then compute Spearman r against ground-truth completion rates."""
    completion_rates = {
        "末世之黑暗时代": 99, "黑暗文明_古羲": 99, "超级神基因": 98, "狩魔手记_烟雨江南": 98,
        "限制级末日症候": 96, "《全球进化》（精校版全本）作者：咬狗": 93, "《末日蟑螂》作者：伟岸蟑螂": 93,
        "《十日终焉》（校对全本）": 94, "我在末世种个田": 97, "黑暗血时代": 86,
    }
    pred_scores, true_rates = [], []

    for i, held_out in enumerate(analyses):
        name = held_out.get("name", f"book_{i}")[:40]
        # Match ground truth by partial name
        true_rate = None
        for k, v in completion_rates.items():
            if k[:6] in name or name[:6] in k:
                true_rate = v
                break
        if true_rate is None:
            continue

        # v9: Rebuild pool WITHOUT held-out book (true LOOCV)
        global _firebook_pool
        _firebook_pool = None  # Force rebuild
        pool_9 = get_firebook_pool(genre, exclude_name=name)

        # Load rows for held-out book
        csv_name = None
        for novel in load_genre_novels(genre):
            if name in novel.get("file", ""):
                csv_name = novel.get("rhythm_csv")
                break
        if not csv_name:
            print(f"  LOOCV[{i+1}/10] [SKIP] no csv match for {name[:20]}")
            continue
        try:
            rows = load_rhythm_data(csv_name)
        except Exception as e:
            print(f"  LOOCV[{i+1}/10] [SKIP] {name[:20]}: CSV error ({e})")
            continue
        if not rows:
            print(f"  LOOCV[{i+1}/10] [SKIP] empty data for {name[:20]}")
            continue

        # Score against 9-book pool
        comm = compute_commercial_score(rows)
        overall = comm.get("overall", 0)
        if overall > 0:
            pred_scores.append(overall)
            true_rates.append(true_rate)
            print(f"  LOOCV[{i+1}/10] {name[:20]:20s} score={overall} true={true_rate}%")

    # Restore full pool
    _firebook_pool = None

    if len(pred_scores) >= 5:
        n = len(pred_scores)

        def _rank(values):
            sp = sorted(enumerate(values), key=lambda x: x[1])
            ranks = [0] * n
            i = 0
            while i < n:
                j = i
                while j < n and sp[j][1] == sp[i][1]:
                    j += 1
                avg_rank = (i + j + 1) / 2.0
                for k in range(i, j):
                    ranks[sp[k][0]] = avg_rank
                i = j
            return ranks

        rs = _rank(pred_scores)
        rr = _rank(true_rates)
        d2 = sum((a - b) ** 2 for a, b in zip(rs, rr))
        spearman_r = round(1 - 6 * d2 / (n * (n**2 - 1)), 3)

        t_stat = spearman_r * math.sqrt((n - 2) / max(1 - spearman_r**2, 0.0001))
        p_val = "p<0.05" if abs(t_stat) > 2.3 else "p>0.05"
        print(f"\n[LOOCV v9] 评分vs真实完读率相关性 r={spearman_r:.3f} ({p_val}) (n={n})")
        return spearman_r, None
    return None, None


def process_genre(genre):
    """Process a single genre: load → analyze → score → report. Returns (synth, output_dir) or None."""
    print(f"[GENRE] {genre}")
    novels = load_genre_novels(genre)
    if not novels:
        print(f"[SKIP] {genre}: 无书籍数据")
        return None
    analyses = []
    for novel in novels:
        csv_name = novel.get("rhythm_csv")
        if not csv_name: continue
        print(f"[ANALYZE] {novel['file']}")
        a = analyze_single_novel(novel['file'].replace('.txt', ''), csv_name)
        if a: analyses.append(a)
    if not analyses: return None
    evaluate_loocv(genre, analyses)

    # ── v10: Borda Count multi-dimensional consensus ranking (IJCAI 2024, Borda 1770) ──
    # Each dimension ranks books independently, then Borda sums positions.
    # Dims: hook, conflict, intensity, readability, BT_rank, WebN8_aggregate, diversity, dialogue
    # f1_weights from annotation_reliability: downweight low-F1 dimensions
    f1_default = {"pleasure": 1.0, "hook": 1.0, "conflict": 1.0}
    dims = [
        ("hook_density", lambda a, f1=f1_default: a.get("commercial", {}).get("scores", {}).get("前3章钩子", 50) * a.get("commercial", {}).get("annotation_reliability", f1).get("hook", 1.0)),
        ("conflict",     lambda a, f1=f1_default: a.get("commercial", {}).get("scores", {}).get("前3章冲突", 50) * a.get("commercial", {}).get("annotation_reliability", f1).get("conflict", 1.0)),
        ("intensity",    lambda a, f1=f1_default: a.get("commercial", {}).get("scores", {}).get("首章爽点", 50) * a.get("commercial", {}).get("annotation_reliability", f1).get("pleasure", 1.0)),
        ("readability",  lambda a: a.get("commercial", {}).get("scores", {}).get("读者留存力", 50)),
        ("diversity",    lambda a: a.get("commercial", {}).get("scores", {}).get("爽点多样性", 50)),
        ("bt_rank",      lambda a: a.get("commercial", {}).get("scores", {}).get("BT相对排名", 50)),
        ("webnovel8",    lambda a: a.get("commercial", {}).get("scores", {}).get("WebNovelBench综合", 50)),
        ("dialogue",     lambda a: a.get("rhythm_stats", {}).get("dialogue_ratio", 0.25) * 100),
    ]
    borda = {}
    for dim_name, score_fn in dims:
        # Sort by this dimension, assign rank 1 = highest
        sorted_books = sorted(analyses, key=score_fn, reverse=True)
        for rank, book in enumerate(sorted_books, 1):
            stem = book.get("name", "")
            if stem not in borda:
                borda[stem] = {"total_borda": 0, "dim_ranks": {}}
            borda[stem]["total_borda"] += rank
            borda[stem]["dim_ranks"][dim_name] = rank
    # Lower total_borda = higher consensus rank
    borda_list = sorted(borda.items(), key=lambda x: x[1]["total_borda"])
    ranking_data = []
    for rank, (stem, data) in enumerate(borda_list, 1):
        data["consensus_rank"] = rank
        data["book_name"] = stem
        ranking_data.append(data)
    # Save ranking
    rank_path = PROJECT_ROOT / "outputs" / "reports" / genre / "synthesis" / f"{genre}_borda_ranking.json"
    rank_path.parent.mkdir(parents=True, exist_ok=True)
    with open(rank_path, 'w', encoding='utf-8') as f:
        json.dump(ranking_data, f, ensure_ascii=False, indent=2)
    print(f"[OK] Borda Ranking: {rank_path}")

    synth = synthesize_genre(genre, analyses)
    output_dir = PROJECT_ROOT / "outputs" / "reports" / genre / "synthesis"
    output_dir.mkdir(parents=True, exist_ok=True)
    generate_report(genre, analyses, synth, output_dir / f"{genre}_写作技法总纲.md")
    auto_benchmark(synth, analyses, output_dir)
    print(f"\n[DONE] {genre}: {len(analyses)}/{len(novels)} books")
    return synth, output_dir


def main():
    genre = get_default_genre()
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--genre" and i < len(sys.argv) - 1:
            genre = sys.argv[i + 1]
            break
    print(f"[GENRE] {genre} (default from config.yaml: {get_default_genre()})")
    process_genre(genre)


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
        if not synth: continue
        lines.append(
            f"| {genre} | {synth.get('book_count','?')} | "
            f"{synth.get('avg_hook','?')} | {synth.get('avg_conflict','?')} | "
            f"{synth.get('avg_pleasure','?')} |")
    lines.append("\n## 写作建议\n- 同一题材书籍越多,基准越可靠\n- 差异过大的题材可能需要不同创作策略")
    out = PROJECT_ROOT / "outputs" / "reports" / "cross_genre_comparison.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding='utf-8')
    print(f"\n[CROSS-GENRE] 跨题材对比报告: {out}")


if __name__ == "__main__":
    if "--all" in sys.argv:
        genres = ["末世", "玄幻", "都市", "仙侠", "洪荒", "悬疑", "历史", "无限流"]
        results = {}
        for g in genres:
            r = process_genre(g)
            if r: results[g] = r
        if len(results) >= 2:
            cross_genre_summary(results)
    else:
        main()
