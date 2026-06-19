#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
scoring/commercial_engine.py — 商业可行性引擎 + Bayesian BMA
=============================================================
从 genre_synthesizer.py 拆分。

方法: 笔灵拆书三件套(人物/情节/技巧) + VAD情感弧 + 结构模板 + Survival分段留存 + 跨题材竞争力
参考: MARCUS(arxiv 2510.18201) + 马良写作 + 笔灵AI + Bayesian LLM Eval(arxiv 2504.21303)

公开函数:
  - get_firebook_pool(genre, exclude_name) -> dict
  - percentile_score(value, pool, metric) -> int
  - compute_commercial_score(rows, genre, book_name) -> dict
  - compute_character_state_trajectory(rows) -> dict
  - compute_segment_retention(rows) -> dict
  - compute_cross_genre_competitiveness(rows, genre_pooled) -> dict | None
  - analyze_single_novel(name, csv_name, genre) -> dict | None
  - classify_all_sub_genres(genre, novels)
  - load_genre_novels(genre) -> list
  - load_rhythm_data(csv_name, genre) -> list | None
  - get_default_genre() -> str
"""
import csv
import json
import statistics
import math
import datetime
import re
import sys
import yaml
import http.client
from pathlib import Path
from collections import Counter

from xiaoshuo import PROJECT_ROOT
from xiaoshuo.infra.config_manager import get_config, get_config_section

# ── Sub-module imports (for analyze_single_novel) ──
from xiaoshuo.pipeline.scoring.vad_analyzer import compute_vad
from xiaoshuo.pipeline.scoring.structure_matcher import classify_structure
from xiaoshuo.pipeline.scoring.technique_tagger import compute_tags

# ── Genre-aware directory helpers ──

def _llm_dir(genre):
    """Genre-aware LLM scores dir: data/processed/{genre}/llm_scores/"""
    return PROJECT_ROOT / "data" / "processed" / genre / "llm_scores"


def _calib_dir(genre):
    """Genre-aware calibration dir: data/reports/{genre}/calibration/"""
    return PROJECT_ROOT / "data" / "reports" / genre / "calibration"


def _rhythm_dir(genre):
    """Genre-aware rhythm CSV dir: data/processed/{genre}/rhythm/"""
    return PROJECT_ROOT / "data" / "processed" / genre / "rhythm"


# ── Bayesian BMA weights (loaded once from calibrate_v2) ──
_bayesian_weights_cache = None


def _load_bayesian_weights(genre="末世"):
    """v8: Read calibrate_v2 feature importance, compute per-metric Bayesian blend weights.
    Based on arxiv 2504.21303 (Bayesian LLM Evaluation) + Self-Preference Bias mitigation.
    Returns {metric: {rule_weight, llm_weight, best_rule_feature}}"""
    global _bayesian_weights_cache
    if _bayesian_weights_cache is not None:
        return _bayesian_weights_cache

    fi_path = _calib_dir(genre) / "feature_importance.csv"
    if not fi_path.exists():
        # Fallback to default weights (r_min=0.2 -> w_rule~0.04)
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
        """Bayesian shrinkage: w_rule = r^2/(1+r^2), w_llm = 1/(1+r^2).
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
    """v7->v12: Load all LLM scores keyed by (book_stem, ch_num). Cached at module level.
    v12: expanded to load hook/pace/conflict for signing+retention scoring."""
    cache = getattr(_load_all_llm_scores, "_cache", None)
    if cache is not None:
        return cache
    # Convert categorical LLM outputs to numeric
    _hook_map = {"none": 0.0, "weak": 5.0, "strong": 10.0}
    _pace_map = {"slow": 3.0, "medium": 6.0, "fast": 9.0}
    _conflict_map = {"none": 0.0, "low": 3.0, "medium": 6.0, "high": 9.0}
    all_scores = {}
    for genre_sub in (PROJECT_ROOT / "data" / "processed").iterdir():
        llm_sub = genre_sub / "llm_scores"
        if not llm_sub.is_dir(): continue
        for fp in llm_sub.glob("*_llm.csv"):
            stem = fp.stem.replace("_llm", "")
            with open(fp, 'r', encoding='utf-8-sig') as f:
                for r in csv.DictReader(f):
                    try:
                        all_scores[(stem, int(r["ch_num"]))] = {
                            "intensity": float(r["llm_intensity"]),
                            "retention": float(r["llm_retention"]),
                            "hook": _hook_map.get(r.get("llm_hook", ""), 5.0),
                            "pace": _pace_map.get(r.get("llm_pace", ""), 6.0),
                            "conflict": _conflict_map.get(r.get("llm_conflict", ""), 5.0),
                        }
                    except (ValueError, KeyError):
                        continue  # skip malformed rows
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


# ── Module-level constants ──
INDEX_PATH = PROJECT_ROOT / "data" / "raw" / "novel_index.json"


def get_default_genre():
    """Read default genre from config.yaml author section."""
    try:
        cfg = get_config()
        genres = cfg.get("author", {}).get("genres", ["末世"])
        return genres[0] if genres else "末世"
    except Exception as e:
        print(f"[WARN] Failed to parse config genres: {e}, using default '末世'", file=sys.stderr)
    return "末世"


def load_genre_novels(genre):
    if not INDEX_PATH.exists():
        print(f"[FAIL] novel_index.json not found at {INDEX_PATH}")
        return []
    with open(INDEX_PATH, 'r', encoding='utf-8') as f:
        index = json.load(f)
    return index["genres"].get(genre, {}).get("novels", [])


def load_rhythm_data(csv_name, genre="末世"):
    csv_path = _rhythm_dir(genre) / csv_name
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


# ── Fire book pool ──
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
    manifest_path = PROJECT_ROOT / "data" / "processed" / genre / "quality_manifest.json"
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
        # P1 pool isolation: only filter when approved pool is large enough (P0: >=3 books)
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
        rows = load_rhythm_data(csv_name, genre)
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
        llm_csv = _llm_dir(genre) / f"{Path(csv_name).stem.replace('rhythm_', '')}_llm.csv"
        if llm_csv.exists():
            with open(llm_csv, 'r', encoding='utf-8-sig') as f:
                llm_rows = list(csv.DictReader(f))
            if llm_rows:
                all_retentions.append(statistics.mean([float(r["llm_retention"]) for r in llm_rows]))

    # P0: fallback -- if pool empty after isolation, rebuild with full genre pool
    if not all_hooks and pass_stems:
        print(f"[WARN] Isolation filter produced empty pool -- falling back to full {genre} pool")
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
            rows = load_rhythm_data(csv_name, genre)
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
            llm_csv = _llm_dir(genre) / f"{Path(csv_name).stem.replace('rhythm_', '')}_llm.csv"
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


# ── Cached grade thresholds ──
_grade_thresholds_cache = None


def _grade(overall):
    """v7.5: Calibrated grade from scoring.grades in config."""
    global _grade_thresholds_cache
    if _grade_thresholds_cache is None:
        try:
            g = get_config_section("model_orchestration", "scoring", "grades", default={})
            _grade_thresholds_cache = (
                g.get("s_plus", 80), g.get("a", 70),
                g.get("b", 60), g.get("c", 50), g.get("d", 0),
            )
        except Exception:
            _grade_thresholds_cache = (80, 70, 60, 50, 0)
    sp, a, b, c, d = _grade_thresholds_cache
    if overall >= sp:  return "S+ 神作"
    elif overall >= a: return "A 精品"
    elif overall >= b: return "B 普通需优化"
    elif overall >= c: return "C 扑街风险"
    else:              return "D 不建议发"


def percentile_score(value, pool, metric):
    """v7.5: Bayesian shrinkage instead of hard cutoff.
    When n < 30, raw percentile is shrunk toward 50 proportionally.
    shrinkage = min(1, n/30) -> n=9 gives 30% signal, n=20 gives 67% signal."""
    p_data = pool.get(metric, {})
    sorted_vals = p_data.get("_sorted", [])
    if not sorted_vals or len(sorted_vals) < 3:
        return 50
    n = len(sorted_vals)
    rank = sum(1 for v in sorted_vals if v <= value)
    raw_pct = round((rank - 0.5) / n * 100) if n > 0 else 50
    if n < 30:
        shrinkage = n / 30.0  # 0.1(min) -> 0.97(max)
        return round(50 + (raw_pct - 50) * shrinkage)
    return raw_pct


# ── v12: LLM sub-genre classification ──
_llm_sub_genre_cache = {}

_SUB_GENRE_PROMPT = (
    "你是专业网文编辑。根据以下前3章摘要，判断这本书的子类型。\n"
    "可选类型: 打脸流 | 智斗流 | 羁绊流 | 恐怖悬疑流 | 升级流 | 通用\n\n"
    "类型说明:\n"
    "- 打脸流: 主角频繁打脸对手、装逼反转、碾压敌人\n"
    "- 智斗流: 烧脑博弈、信息差、心理战、谋略对决\n"
    "- 羁绊流: 伙伴情感、牺牲、成长羁绊、团队情深\n"
    "- 恐怖悬疑流: 诡异氛围、心理恐怖、未知恐惧、解谜\n"
    "- 升级流: 实力提升、碾压、等级突破、修炼进化\n"
    "- 通用: 以上都不突出，多种元素混合\n\n"
    "只输出类型名称，不要其他文字。\n\n"
    "前3章摘要:\n{text}"
)


def _llm_classify_sub_genre(txt_path):
    """v12: Use LLM to classify sub-genre from first 3 chapters. Falls back to None on error."""
    try:
        import http.client
        with open(txt_path, 'r', encoding='utf-8', errors='ignore') as f:
            full_text = f.read(15000)  # first ~15k chars (roughly 3 chapters)
        # Build summary: first 1500 chars + chapter markers
        text = full_text[:1500] if len(full_text) > 1500 else full_text
        prompt = _SUB_GENRE_PROMPT.format(text=text)
        data = json.dumps({
            "messages": [
                {"role": "system", "content": "你是网文分类专家，只输出类型名称。"},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 20, "temperature": 0.0,
        }).encode("utf-8")
        port = _get_llm_port() if '_get_llm_port' in dir() else 8000
        conn = http.client.HTTPConnection(f"127.0.0.1:{port}", timeout=30)
        conn.request("POST", "/v1/chat/completions", body=data,
                     headers={"Content-Type": "application/json"})
        resp = json.loads(conn.getresponse().read())
        conn.close()
        raw = resp.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        # Map response to known labels
        for label in ["打脸流", "智斗流", "羁绊流", "恐怖悬疑流", "升级流", "通用"]:
            if label in raw:
                return label
        return None
    except Exception:
        return None


def classify_all_sub_genres(genre, novels):
    """v12: Classify sub-genre for all novels in a genre using LLM. Stores in module cache."""
    global _llm_sub_genre_cache
    # Check if LLM is available
    try:
        import http.client
        port = 8000
        try:
            cfg = get_config()
            port = cfg.get("analysis", {}).get("llm_port", 8000)
        except Exception:
            pass
        conn = http.client.HTTPConnection(f"127.0.0.1:{port}", timeout=5)
        conn.request("GET", "/v1/models")
        conn.getresponse().read()
        conn.close()
        llm_available = True
    except Exception:
        llm_available = False

    classified = 0
    for novel in novels:
        name = novel.get("file", "").replace(".txt", "")
        if name in _llm_sub_genre_cache:
            continue
        if not llm_available:
            break
        txt_path = PROJECT_ROOT / "data" / "raw" / "novels" / genre / novel.get("file", "")
        if not txt_path.exists():
            continue
        label = _llm_classify_sub_genre(str(txt_path))
        if label:
            _llm_sub_genre_cache[name] = label
            classified += 1
    if classified > 0:
        print(f"[OK] LLM sub-genre: {classified} books classified")
    # Save cache to JSON for inspection
    cache_path = PROJECT_ROOT / "data" / "processed" / genre / "sub_genre_llm.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(_llm_sub_genre_cache, ensure_ascii=False, indent=2), encoding='utf-8')


def _detect_sub_genre(rows, book_name=None):
    """v4->v12: Detect sub-genre. LLM classification takes priority (from cache), regex fallback."""
    # v12: Check LLM cache first by book_name
    if book_name and _llm_sub_genre_cache:
        for cached_name, label in _llm_sub_genre_cache.items():
            if cached_name in book_name or book_name in cached_name:
                return label
    # Regex fallback (v4 original)
    subs = Counter(r["dominant_sub"] for r in rows if r.get("dominant_sub") != "none")
    total = sum(subs.values())
    if total == 0:
        return "通用"
    bond_ct = sum(r.get("bond_count", 0) for r in rows)
    cognitive_ct = sum(r.get("cognitive_count", 0) for r in rows)
    sacrifice_ct = sum(r.get("sacrifice_count", 0) for r in rows)
    slap_ct = subs.get("打脸", 0)
    comeback_ct = subs.get("绝地反击", 0)

    slap_ratio = slap_ct / max(total, 1)
    bond_cog_sac = bond_ct + cognitive_ct + sacrifice_ct
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


# ── v7.5: DeepSeek API independent scoring (self-eval bias mitigation) ──

def _load_scoring_config():
    """Read scoring section from config.yaml. Returns dict."""
    try:
        return get_config_section("model_orchestration", "scoring", default={})
    except Exception:
        return {}


def _load_deepseek_config():
    """Read DeepSeek API config from config.yaml + secrets.yaml (gitignored).
    Returns dict or None if disabled or key missing."""
    try:
        cfg = get_config()
        apis = cfg.get("model_orchestration", {}).get("models", {}).get("external_api", {})
        ds = apis.get("deepseek", {})
        if not ds.get("enabled"):
            return None
        secrets_path = PROJECT_ROOT / "secrets.yaml"
        api_key = None
        if secrets_path.exists():
            with open(secrets_path, 'r', encoding='utf-8') as f:
                secrets = yaml.safe_load(f) or {}
            api_key = secrets.get("deepseek", {}).get("api_key")
        if not api_key:
            return None
        ds["api_key"] = api_key
        # Merge siliconflow backup config
        sf = apis.get("siliconflow", {})
        if sf.get("enabled"):
            sf_key = secrets.get("siliconflow", {}).get("api_key") if secrets_path.exists() else None
            if sf_key and "PLACEHOLDER" not in sf_key:
                sf["api_key"] = sf_key
                ds["siliconflow"] = sf
        return ds
    except Exception:
        return None


# ── v7.5: DeepSeek score cache ──
_DS_CACHE = None


def _load_ds_cache():
    """Load DeepSeek score cache from data/deepseek_cache.json."""
    global _DS_CACHE
    if _DS_CACHE is not None:
        return _DS_CACHE
    cache_path = PROJECT_ROOT / "data" / "deepseek_cache.json"
    if cache_path.exists():
        try:
            _DS_CACHE = json.loads(cache_path.read_text("utf-8"))
        except Exception:
            _DS_CACHE = {}
    else:
        _DS_CACHE = {}
    return _DS_CACHE


def _save_ds_cache():
    """Persist DeepSeek score cache."""
    global _DS_CACHE
    cache_path = PROJECT_ROOT / "data" / "deepseek_cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(_DS_CACHE, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_ds_cached(book_stem):
    """Get cached DeepSeek score if fresh (<7 days)."""
    cache = _load_ds_cache()
    scoring_cfg = _load_scoring_config()
    ttl = scoring_cfg.get("cache_ttl_days", 7) * 86400
    entry = cache.get(book_stem)
    if entry and entry.get("timestamp"):
        try:
            ts = datetime.datetime.fromisoformat(entry["timestamp"]).timestamp()
            if time.time() - ts < ttl:
                return entry
        except Exception:
            pass
    return None


def _set_ds_cached(book_stem, ds_data):
    """Save DeepSeek score to cache."""
    global _DS_CACHE
    cache = _load_ds_cache()
    cache[book_stem] = {
        "timestamp": datetime.datetime.now().isoformat(),
        **ds_data,
    }
    _DS_CACHE = cache
    _save_ds_cache()


_DS_SCORING_PROMPT = (
    "你是网文商业评估专家。请对以下末世题材网文章节进行评分。\n\n"
    "评分维度（0-10分，允许小数点后1位）：\n"
    "1. 爽感强度：读者感到'爽'的程度\n"
    "2. 留存吸引力：读完想继续追读的意愿\n"
    "3. 钩子质量：章末悬念/反转/期待感\n"
    "4. 节奏合理性：情节推进速度是否恰当\n"
    "5. 冲突强度：本章冲突的激烈程度\n"
    "6. 人物塑造：角色行为是否立体、有记忆点\n"
    "7. 文笔流畅度：阅读体验是否顺畅、无卡顿\n\n"
    "评分要求：\n"
    "- 先简要分析本章优缺点（1-2句话）\n"
    "- 再给出分数，格式：爽感,留存,钩子,节奏,冲突,人物,文笔\n"
    "- 示例：7.5,6.0,8.0,7.0,5.5,4.0,6.5\n\n"
    "章节内容：\n{text}"
)


def _deepseek_call_scoring(text, config):
    """Call DeepSeek API with siliconflow fallback."""
    results = _call_ds_api(text, config)
    if results is None and config.get("siliconflow"):
        results = _call_ds_api(text, config["siliconflow"])
    return results


def _call_ds_api(text, cfg):
    """Call a single API endpoint for scoring."""
    prompt = _DS_SCORING_PROMPT.format(text=text[:5000])
    base = cfg.get("base_url", "https://api.deepseek.com").rstrip("/")
    host = base.replace("https://", "").replace("http://", "")
    data = json.dumps({
        "model": cfg.get("model", "deepseek-chat"),
        "messages": [
            {"role": "system", "content": "你是网文评估专家。先分析再输出7个逗号分隔的数字。"},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": cfg.get("max_tokens", 80),
        "temperature": cfg.get("temperature", 0.0),
    }).encode("utf-8")

    try:
        timeout = cfg.get("timeout", 30)
        conn = http.client.HTTPSConnection(host, timeout=timeout)
        conn.request("POST", "/v1/chat/completions", body=data,
                     headers={
                         "Content-Type": "application/json",
                         "Authorization": f"Bearer {cfg['api_key']}",
                     })
        resp = json.loads(conn.getresponse().read())
        conn.close()
        raw = resp.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        nums = [float(n) for n in re.findall(r"\d+\.?\d*", raw)]
        if len(nums) >= 7:
            return nums[:7]
        elif len(nums) >= 5:
            return nums[:5] + [5.0, 5.0]
        return None
    except Exception:
        return None


def _load_chapter_texts(book_stem, indices):
    """Load actual chapter text from raw novel file for LLM scoring.
    Returns {idx: text} dict."""
    if not book_stem or not indices:
        return {}
    try:
        from analysis.rhythm_analyzer import extract_chapters
        scoring_cfg = _load_scoring_config()
        novel_base = scoring_cfg.get("novel_source_dir", "data/raw/novels")
        novel_dir = PROJECT_ROOT / novel_base / "末世"
        for txt_file in novel_dir.glob("*.txt"):
            if book_stem[:6] in txt_file.stem or txt_file.stem[:6] in book_stem:
                chapters = extract_chapters(str(txt_file))
                result = {}
                for i, ch in enumerate(chapters):
                    if i in indices:
                        result[i] = ch.get("raw_body", "")
                return result
        return {}
    except Exception:
        return {}


def _score_book_with_deepseek(rows, ds_config, sample_n=None, book_stem=""):
    """Score with DeepSeek, with cache check. Returns dims dict or None."""
    if not ds_config or not rows:
        return None

    # Check cache first
    if book_stem:
        cached = _get_ds_cached(book_stem)
        if cached and cached.get("overall"):
            return cached

    scoring_cfg = _load_scoring_config()
    if sample_n is None:
        sample_n = scoring_cfg.get("llm_sample_chapters", 5)
    max_chars = scoring_cfg.get("llm_text_max_chars", 4000)

    total = len(rows)
    step = max(1, total // sample_n)
    indices = list(range(0, min(total, step * sample_n), step))[:sample_n]

    dims = ["intensity", "retention", "hook", "pace", "conflict", "character", "prose"]
    all_scores = {d: [] for d in dims}

    # -- v7.5 fix: pass actual chapter text, not metadata --
    chapter_texts = _load_chapter_texts(book_stem, indices) if book_stem else {}

    for idx in indices:
        ch = rows[idx]
        ch_text = chapter_texts.get(idx)
        if ch_text:
            text = f"章节{ch.get('ch_num','?')}\n{ch_text[:max_chars]}"
        else:
            text = f"章节{ch.get('ch_num','?')} ({ch.get('wc','?')}字)\n"
            text += f"钩子密度={ch.get('hook_density','?')} 冲突密度={ch.get('conflict_density','?')} 爽点={ch.get('pleasure_intensity','?')}"
        scores = _deepseek_call_scoring(text, ds_config)
        if scores:
            for i, dim in enumerate(dims):
                all_scores[dim].append(scores[i])

    if not all_scores["intensity"]:
        return None

    result = {}
    for dim in dims:
        result[dim] = round(statistics.mean(all_scores[dim]), 1) if all_scores[dim] else 5.0

    # Cache result
    if book_stem:
        _set_ds_cached(book_stem, result)
    return result


# ── v7.5: OLS Linear Regression Calibration ──
# Fitted from Qwen vs DeepSeek paired scores. Expandable as more DS data arrives.

def _ols_fit(pairs):
    """Fit linear regression DS = a * Qwen + b using OLS (pure Python, no dependencies).
    Returns (a, b)."""
    n = len(pairs)
    sx = sum(p[0] for p in pairs)
    sy = sum(p[1] for p in pairs)
    sxy = sum(p[0] * p[1] for p in pairs)
    sx2 = sum(p[0] * p[0] for p in pairs)
    denom = n * sx2 - sx * sx
    if abs(denom) < 0.001:
        return 1.0, -22.0  # fallback to simple offset
    a = (n * sxy - sx * sy) / denom
    b = (sy - a * sx) / n
    return round(a, 4), round(b, 1)


def _loocv_mae(pairs):
    """Leave-One-Out Cross-Validation Mean Absolute Error."""
    errors = []
    n = len(pairs)
    for i in range(n):
        train = pairs[:i] + pairs[i + 1:]
        a, b = _ols_fit(train)
        pred = a * pairs[i][0] + b
        actual = pairs[i][1]
        errors.append(abs(pred - actual))
    return round(sum(errors) / n, 1) if errors else 0


# Calibration pairs: (Qwen_score, DeepSeek_score) from 10-book validation
_CALIB_PAIRS = [
    (88, 69), (88, 68), (76, 59), (96, 72), (84, 65),
    (88, 63), (87, 62), (88, 62), (82, 55), (76, 59),
]
_CALIB_A, _CALIB_B = _ols_fit(_CALIB_PAIRS)


def _ols_calibrate(qwen_score):
    """Calibrate Qwen score to DeepSeek scale."""
    return _CALIB_A * qwen_score + _CALIB_B


# ── Helper: plot diversity, character arc, max streak ──

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


# ── MARCUS character state trajectory ──

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


# ── Segment retention ──

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


# ── Cross-genre competitiveness ──

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


# ══════════════════════════════════════════════════════════════
# compute_commercial_score — 商业可行性评分 v12
# ══════════════════════════════════════════════════════════════

def compute_commercial_score(rows, genre="末世", book_name=None):
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

    # -- P0-3: Read annotation reliability -> adjust weights for low-F1 metrics --
    rel_path = PROJECT_ROOT / "data" / "processed" / genre / "annotation_reliability.json"
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

    # -- 评分: 百分位制 (P50=50, P75=75, P25=25) --
    scores = {}

    # -- v7.5: DS-priority LLM scoring with cache --
    scoring_cfg = _load_scoring_config()
    ds_config = _load_deepseek_config()

    # Find book stem
    llm_ch = _load_all_llm_scores()
    book_stem = _find_book_stem(rows, llm_ch)

    # Try DeepSeek first (cache -> API), fallback Qwen
    llm_source = "rule"
    ds_data = None
    if ds_config and book_stem:
        ds_data = _score_book_with_deepseek(rows, ds_config, book_stem=book_stem)
        if ds_data:
            llm_source = "deepseek"

    # Load Qwen LLM scores as fallback/comparison
    llm_data = {"intensity": [], "retention": [], "hook": [], "pace": [], "conflict": []}
    if book_stem:
        sample_n_llm = min(30, total)
        for r in rows[:sample_n_llm]:
            key = (book_stem, r["ch_num"])
            if key in llm_ch:
                for dim in llm_data:
                    llm_data[dim].append(llm_ch[key][dim])
        if llm_data["intensity"] and llm_source == "rule":
            llm_source = "qwen"

    # Use DS if available, else Qwen, else rule fallback
    if ds_data:
        llm_avg_intensity = ds_data.get("intensity", opening_intensity)
        llm_avg_retention = ds_data.get("retention", 5.0)
        llm_avg_hook = ds_data.get("hook", opening_hook * 10)
        llm_avg_pace = ds_data.get("pace", 6.0)
        llm_avg_conflict = ds_data.get("conflict", opening_conflict * 10)
    elif llm_data["intensity"]:
        llm_avg_intensity = statistics.mean(llm_data["intensity"])
        llm_avg_retention = statistics.mean(llm_data["retention"]) if llm_data["retention"] else 5.0
        llm_avg_hook = statistics.mean(llm_data["hook"]) if llm_data["hook"] else (opening_hook * 10)
        llm_avg_pace = statistics.mean(llm_data["pace"]) if llm_data["pace"] else 6.0
        llm_avg_conflict = statistics.mean(llm_data["conflict"]) if llm_data["conflict"] else (opening_conflict * 10)
    else:
        # Compute LLM averages (v7.5: fallback to rule-based weighted mean, not fixed 5.0/6.0)
        llm_avg_intensity = opening_intensity
    # retention fallback: weighted mean of hook + conflict + pleasure (rule-based signals)
    rule_retention_est = (opening_hook * 3 + opening_conflict * 3 + opening_pos_density * 2) / 8 * 10
    llm_avg_retention = statistics.mean(llm_data["retention"]) if llm_data["retention"] else min(10, max(1, round(rule_retention_est, 1)))
    llm_avg_hook = statistics.mean(llm_data["hook"]) if llm_data["hook"] else (opening_hook * 10)
    # pace fallback: based on para_len (fast=7, medium=5, slow=3)
    avg_para_len = statistics.mean([r.get("avg_para_len", 80) for r in rows[:min(30, total)]])
    rule_pace = 7 if avg_para_len < 60 else (5 if avg_para_len < 200 else 3)
    llm_avg_pace = statistics.mean(llm_data["pace"]) if llm_data["pace"] else rule_pace
    llm_avg_conflict = statistics.mean(llm_data["conflict"]) if llm_data["conflict"] else (opening_conflict * 10)
    # Opening-specific LLM scores (first 3 chapters)
    llm_opening_int = llm_data["intensity"][:3] if len(llm_data["intensity"]) >= 3 else llm_data["intensity"]
    llm_opening_hook = llm_data["hook"][:3] if len(llm_data["hook"]) >= 3 else llm_data["hook"]
    llm_opening_ret = llm_data["retention"][:3] if len(llm_data["retention"]) >= 3 else llm_data["retention"]
    llm_opening_intensity = statistics.mean(llm_opening_int) if llm_opening_int else llm_avg_intensity
    llm_opening_hook_val = statistics.mean(llm_opening_hook) if llm_opening_hook else llm_avg_hook
    llm_opening_retention = statistics.mean(llm_opening_ret) if llm_opening_ret else llm_avg_retention

    # -- v7.5: DeepSeek independent scoring (self-eval bias mitigation) --
    ds_config = _load_deepseek_config()
    ds_data = _score_book_with_deepseek(rows, ds_config) if ds_config else None
    # Paywall hook: LLM retention at ~20% mark (free chapter boundary)
    paywall_idx = max(0, min(len(llm_data["retention"]) - 1, len(llm_data["retention"]) // 5))
    llm_paywall_ret = llm_data["retention"][paywall_idx] if llm_data["retention"] else 5.0

    # -- v4: Sub-genre detection for adaptive scoring --
    sub_genre = _detect_sub_genre(rows, book_name=book_name)

    # -- v9: Bayesian Stacking (replaces Pseudo-BMA, arxiv 2504.21303 + stan loo) --
    bw = _load_bayesian_weights(genre)

    # ══════════════════════════════════════════════════════════════
    # v12: LLM-DOMINANT SCORING
    # ══════════════════════════════════════════════════════════════

    # -- Score 1: 签约概率 (Signing Probability) --
    signing_intensity = percentile_score(llm_opening_intensity, pool, "intensity")
    signing_hook = percentile_score(llm_opening_hook_val, pool, "hook_density")
    signing_paywall = percentile_score(llm_paywall_ret, pool, "retention")
    rule_conflict_pct = percentile_score(opening_conflict, pool, "conflict")
    signing_score = round(
        signing_intensity * 0.35 +
        signing_hook * 0.30 +
        signing_paywall * 0.10 +
        rule_conflict_pct * 0.25
    )

    # -- Score 2: 留存预测 (Retention Prediction) --
    retention_llm = percentile_score(llm_avg_retention, pool, "retention")
    intensity_llm = percentile_score(llm_avg_intensity, pool, "intensity")
    pace_vals = llm_data["pace"] if llm_data["pace"] else [6.0]
    pace_std = statistics.stdev(pace_vals) if len(pace_vals) > 1 else 0
    pace_consistency = max(0, 100 - pace_std * 15)
    retention_pace = percentile_score(pace_consistency, pool, "hook_density")
    hook_coverage = sum(1 for r in rows if r.get("hook_density", 0) > 0) / max(total, 1) * 100
    retention_rule = percentile_score(hook_coverage, pool, "hook_density")
    retention_score = round(
        retention_llm * 0.40 +
        intensity_llm * 0.25 +
        retention_pace * 0.20 +
        retention_rule * 0.15
    )

    # -- Backward-compatible sub-scores (for Borda ranking dims) --
    scores["前3章钩子"] = signing_hook
    scores["前3章冲突"] = rule_conflict_pct
    scores["首章爽点"] = signing_intensity
    scores["读者留存力"] = retention_llm
    scores["爽点多样性"] = percentile_score(shannon_div, pool, "diversity")
    scores["付费转化钩子"] = signing_paywall
    # BT ranking
    bt_wins = 0
    bt_comparisons = 0
    if pool.get("_sorted"):
        for other_hook in pool["_sorted"].get("hook_density", []):
            bt_comparisons += 1
            our = max(0.1, llm_opening_hook_val / 10.0)
            th = max(0.1, other_hook)
            if our / (our + th) > 0.5:
                bt_wins += 1
    bt_rank = round(bt_wins / max(bt_comparisons, 1) * 100)
    scores["BT相对排名"] = bt_rank
    # WebNovelBench (simplified -- LLM-based)
    webnovel = {
        "情节强度": rule_conflict_pct,
        "人物深度": percentile_score(shannon_div * 10, pool, "diversity"),
        "文笔风格": percentile_score(statistics.mean([r.get("readability", 0.5) for r in rows]) * 100, pool, "readability"),
        "情感张力": signing_intensity,
        "读者吸引力": bt_rank,
    }
    scores["WebNovelBench综合"] = round(statistics.mean(webnovel.values()))

    # -- v7.5: Adaptive signing/retention weights --
    avg_dialogue = statistics.mean([r.get("dialogue_ratio", 0) for r in rows[:min(30, total)]])
    vd_vals = [r.get("vocab_diversity", 0) for r in rows if r.get("vocab_diversity", 0) > 0]
    avg_vd_all = statistics.mean(vd_vals) if vd_vals else 0.2
    is_slow_burn = (avg_dialogue > 0.40) and (opening_hook < 1.5) and (avg_vd_all > 0.20)
    if is_slow_burn:
        w_sign, w_retain = 0.40, 0.60
    else:
        w_sign, w_retain = 0.50, 0.50
    sign = signing_score
    retain_old = retention_score
    bonus = retention_score
    overall = round(signing_score * w_sign + retention_score * w_retain)

    # -- v13: Anti-template penalty --
    vocab_diversities = [r.get("vocab_diversity", 0) for r in rows if r.get("vocab_diversity", 0) > 0]
    avg_vocab_div = statistics.mean(vocab_diversities) if vocab_diversities else 0.2

    sub_counter = Counter(r.get("dominant_sub", "none") for r in rows)
    total_subs = sum(sub_counter.values())
    top2_concentration = sum(v for _, v in sub_counter.most_common(2)) / max(total_subs, 1)

    ch_vars = [r.get("ch_variability", 0) for r in rows if r.get("ch_variability", 0) > 0]
    avg_ch_var = statistics.mean(ch_vars) if ch_vars else 0

    anti_template_penalty = 1.0
    if avg_vocab_div < 0.18 and overall < 85:
        anti_template_penalty -= 0.05
    if top2_concentration > 0.55 and opening_hook < 1.5 and not is_slow_burn:
        anti_template_penalty -= 0.05
    if avg_ch_var < 0.1 and len(rows) > 50:
        anti_template_penalty -= 0.05
    anti_template_penalty = max(0.70, anti_template_penalty)

    overall_raw = round(overall * anti_template_penalty)

    # -- v7.5: OLS linear regression calibration --
    calib_enabled = scoring_cfg.get("calibration_enabled", False)
    if calib_enabled:
        overall = max(0, min(100, round(_ols_calibrate(overall_raw))))
    else:
        overall = overall_raw

    zero_var_dims = []
    gw = {"sign": 0.5, "retain": 0.5, "bonus": 0.0}

    # -- Bootstrap 95% CI --
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

    # -- v4: 权重敏感性分析 (Weight Sensitivity) --
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

    # -- 评级 --
    grade = _grade(overall)
    grade_range = f"{grade} [{ws_lo}-{ws_hi}]" if ws_hi - ws_lo >= 10 else grade

    # -- 弃书风险 (v3 保留) --
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

    # -- v7.5: DeepSeek vs Qwen comparison --
    ds_score = None
    self_eval_bias = None
    if ds_data and ds_config:
        ds_signing = round(
            ds_data["intensity"] / 10 * 100 * 0.35 +
            ds_data["hook"] / 10 * 100 * 0.30 +
            ds_data["retention"] / 10 * 100 * 0.10 +
            rule_conflict_pct * 0.25
        )
        char_prose_bonus = (ds_data.get("character", 5.0) + ds_data.get("prose", 5.0)) / 20 * 10
        ds_retention = round(
            ds_data["retention"] / 10 * 100 * 0.40 +
            ds_data["intensity"] / 10 * 100 * 0.25 +
            (100 - ds_data["pace"] * 10) * 0.20 +
            retention_rule * 0.15 +
            char_prose_bonus * 0.05
        )
        ds_overall = round((ds_signing * 0.5 + ds_retention * 0.5) * anti_template_penalty)
        ds_score = {
            "overall": ds_overall,
            "signing": ds_signing, "retention": ds_retention,
            "raw": ds_data,
        }
        gap = abs(overall - ds_overall)
        if gap > 20:
            bias_level = "CRITICAL"
            bias_note = "Severe self-evaluation bias (>20pts) -- manual review required"
        elif gap > 10:
            bias_level = "WARNING"
            bias_note = "Moderate bias (>10pts) -- trust with caution"
        elif gap > 5:
            bias_level = "NOTICE"
            bias_note = "Mild divergence (>5pts) -- record for trend analysis"
        else:
            bias_level = "OK"
            bias_note = "Within acceptable range (<=5pts)"
        self_eval_bias = {
            "qwen_score": overall, "deepseek_score": ds_overall,
            "gap": gap, "level": bias_level,
            "note": bias_note,
        }

    return {
        "overall": overall, "overall_raw": overall_raw, "grade": grade,
        "llm_source": llm_source,
        "calibrated": calib_enabled,
        "slow_burn": is_slow_burn,
        "literary_bonus": 0,
        "grade_range": grade_range,
        "scores": scores, "risks": risks[:10],
        "pool_n": pool["n_books"],
        "sub_genre": sub_genre,
        "signing_score": signing_score,
        "retention_score": retention_score,
        "llm_coverage": len(llm_data["intensity"]) > 0,
        "zero_var_dims": zero_var_dims,
        "grade_stability": round(grade_stable * 100),
        "annotation_reliability": f1_weights,
        "bootstrap_ci": {"low": bs_low, "high": bs_high, "width": bs_width},
        "ds_score": ds_score,
        "self_eval_bias": self_eval_bias,
    }


# ══════════════════════════════════════════════════════════════
# analyze_single_novel — 单书分析
# ══════════════════════════════════════════════════════════════

def analyze_single_novel(name, csv_name, genre="末世"):
    rows = load_rhythm_data(csv_name, genre)
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

    # Commercial viability
    result["commercial"] = compute_commercial_score(rows, genre, book_name=name)

    # Diversity + arc
    result["plot_diversity"] = _compute_plot_diversity(rows)
    result["character_arc"] = _compute_character_arc(rows)

    # MARCUS character state trajectory
    result["state_trajectory"] = compute_character_state_trajectory(rows)

    # Segment retention
    result["segment_retention"] = compute_segment_retention(rows)

    return result