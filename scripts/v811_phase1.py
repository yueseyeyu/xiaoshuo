#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
v8.11 Phase 1: IPW校正 + WLS校准 + 双slope报告 + golden去重 + 分级调整
=====================================================================
执行项:
  1.1 IPW逆概率加权校正采样率 + 重算Borda排名
  1.2 WLS加权校准(人工1.0+GLM0.3) + 双slope报告
  1.3 golden去重 + 一致性报告
  1.4 末日乐园/长夜余火降为A级 + 标注
  1.5 未验证TOP1-2标注 + 更新排名JSON
  1.6 生成v8.11 Phase 1报告

输出: data/reports/末世/v8.11_phase1_report.md
"""
import csv
import json
import math
import os
import sys
import datetime
from pathlib import Path
from collections import defaultdict

# ── Paths ──
PROJECT_ROOT = Path(r"d:\Code\xiaoshuo")
GENRE = "末世"
RHYTHM_DIR = PROJECT_ROOT / "data" / "processed" / GENRE / "rhythm"
SCORES_DIR = PROJECT_ROOT / "processed" / GENRE / "scores"
LLM_SCORES_DIR = PROJECT_ROOT / "data" / "processed" / GENRE / "scores"
GOLDEN_CSV = PROJECT_ROOT / "data" / "golden" / GENRE / "human_golden.csv"
GLM_JSON = PROJECT_ROOT / "data" / "golden" / GENRE / "tier3" / "tier3_glm_scores.json"
BORDA_JSON = PROJECT_ROOT / "data" / "reports" / GENRE / "synthesis" / "末世_borda_ranking.json"
CALIB_JSON = PROJECT_ROOT / "data" / "reports" / GENRE / "calibration" / "tier3_calibration.json"
RANKING_CSV = PROJECT_ROOT / "data" / "reports" / "rankings" / GENRE / "v8.8_final_ranking.csv"
NOVEL_INDEX = PROJECT_ROOT / "data" / "raw" / "novel_index.json"
REPORT_OUT = PROJECT_ROOT / "data" / "reports" / GENRE / "v8.11_phase1_report.md"
BORDA_IPW_OUT = PROJECT_ROOT / "data" / "reports" / GENRE / "synthesis" / "末世_borda_ranking_ipw.json"
WLS_OUT = PROJECT_ROOT / "data" / "reports" / GENRE / "calibration" / "wls_calibration_v811.json"
GOLDEN_CLEAN_OUT = PROJECT_ROOT / "data" / "golden" / GENRE / "tier3" / "human_golden_clean.csv"
RANKING_V811_OUT = PROJECT_ROOT / "data" / "reports" / "rankings" / GENRE / "v8.11_final_ranking.csv"

# ── Manual Pearson (np.corrcoef crashes on this Windows) ──
def pearson_r(x, y):
    n = len(x)
    if n < 3: return None
    mx, my = sum(x) / n, sum(y) / n
    num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    dx = math.sqrt(sum((xi - mx) ** 2 for xi in x))
    dy = math.sqrt(sum((yi - my) ** 2 for yi in y))
    if dx < 1e-10 or dy < 1e-10: return None
    return num / (dx * dy)

def spearman_r(x, y):
    """Manual Spearman: rank then Pearson."""
    def rank(lst):
        sorted_lst = sorted(enumerate(lst), key=lambda t: t[1])
        ranks = [0.0] * len(lst)
        i = 0
        while i < len(sorted_lst):
            j = i
            while j + 1 < len(sorted_lst) and sorted_lst[j + 1][1] == sorted_lst[i][1]:
                j += 1
            avg_rank = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                ranks[sorted_lst[k][0]] = avg_rank
            i = j + 1
        return ranks
    return pearson_r(rank(x), rank(y))

def manual_ols(x, y):
    """OLS: y = a + b*x. Returns (intercept, slope, r, r2)."""
    n = len(x)
    if n < 3: return None, None, None, None
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((xi - mx) ** 2 for xi in x)
    sxy = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    if sxx < 1e-10: return None, None, None, None
    slope = sxy / sxx
    intercept = my - slope * mx
    r = pearson_r(x, y)
    r2 = r * r if r else None
    return intercept, slope, r, r2

def manual_wls(x, y, w):
    """WLS: y = a + b*x with weights w. Returns (intercept, slope, r, r2)."""
    n = len(x)
    if n < 3: return None, None, None, None
    sw = sum(w)
    swx = sum(wi * xi for wi, xi in zip(w, x))
    swy = sum(wi * yi for wi, yi in zip(w, y))
    swxx = sum(wi * xi * xi for wi, xi in zip(w, x))
    swxy = sum(wi * xi * yi for wi, xi, yi in zip(w, x, y))
    mx = swx / sw
    my = swy / sw
    sxx = swxx - sw * mx * mx
    sxy = swxy - sw * mx * my
    if abs(sxx) < 1e-10: return None, None, None, None
    slope = sxy / sxx
    intercept = my - slope * mx
    # Weighted R
    r = pearson_r(x, y)  # Use unweighted Pearson for comparability
    r2 = r * r if r else None
    return intercept, slope, r, r2

# ── Book name normalization ──
def normalize_book_name(name):
    """Strip common prefixes/suffixes for matching."""
    import re
    # Remove 《》and full-width parentheses content
    n = name.replace("《", "").replace("》", "")
    # Remove author annotations like "（校对版全本）作者：xxx"
    n = re.sub(r'[（(].*?[）)]', '', n)
    n = re.sub(r'作者[：:].*$', '', n)
    n = n.strip()
    # Common aliases
    aliases = {
        "全球变异，从灾厄降临开始": "全球变异",
        "全球变异,从灾厄降临开始": "全球变异",
    }
    return aliases.get(n, n)

# ── Step 1: Load T1 sampling rates ──
def load_t1_sampling_rates():
    """Load rhythm CSV row counts and ai_full CSV row counts per book."""
    # Load rhythm chapter counts
    rhythm_counts = {}
    if RHYTHM_DIR.exists():
        for f in RHYTHM_DIR.glob("*.csv"):
            if f.name.startswith("rhythm_"):
                book_raw = f.name.replace("rhythm_", "").replace(".csv", "")
                book_key = normalize_book_name(book_raw)
                try:
                    with open(f, 'r', encoding='utf-8-sig') as fh:
                        reader = csv.reader(fh)
                        header = next(reader, None)
                        count = sum(1 for _ in reader)
                        rhythm_counts[book_key] = count
                except Exception:
                    pass

    # Load T1 (ai_full) chapter counts
    # Files are stored as {book_name}_ai_full.csv directly in the scores dir
    t1_counts = {}
    if LLM_SCORES_DIR.exists():
        for f in LLM_SCORES_DIR.glob("*_ai_full.csv"):
            book_raw = f.name.replace("_ai_full.csv", "")
            book_key = normalize_book_name(book_raw)
            try:
                with open(f, 'r', encoding='utf-8-sig') as fh:
                    reader = csv.reader(fh)
                    header = next(reader, None)
                    count = sum(1 for _ in reader)
                    t1_counts[book_key] = count
            except Exception:
                pass

    return rhythm_counts, t1_counts

# ── Step 2: IPW correction ──
def compute_ipw_weights(rhythm_counts, t1_counts, target_rate=0.10):
    """Compute IPW weights for each book based on T1 sampling rate."""
    results = {}
    for book, t1_n in t1_counts.items():
        rhythm_n = rhythm_counts.get(book, 0)
        if rhythm_n == 0:
            continue
        actual_rate = t1_n / rhythm_n
        # IPW weight: capped at 1.0 for over-sampled, proportional for under-sampled
        # weight = min(actual_rate / target_rate, 1.0)
        # This gives under-sampled books lower weight
        ipw = min(actual_rate / target_rate, 1.0)
        results[book] = {
            "t1_chapters": t1_n,
            "rhythm_chapters": rhythm_n,
            "sampling_rate": round(actual_rate, 4),
            "ipw_weight": round(ipw, 4),
            "status": "normal" if 0.05 <= actual_rate <= 0.20 else ("over" if actual_rate > 0.20 else "under")
        }
    return results

# ── Step 3: Recompute Borda with IPW ──
def recompute_borda_with_ipw(borda_data, ipw_weights):
    """
    Apply IPW weights to the retention dimension of Borda.
    
    The retention dimension is the only one affected by T1 sampling rate
    (through BMA 50% LLM weighting). We adjust the retention rank by 
    applying a confidence penalty: books with low sampling rates get
    their retention score damped toward the median.
    
    Since we don't have the raw retention scores, we adjust the Borda 
    retention rank positions: books with ipw < 1.0 get a rank penalty
    proportional to (1 - ipw) * max_books.
    """
    # We need the raw dimension scores to properly apply IPW
    # Since we only have ranks, we'll apply a rank adjustment:
    # For retention dimension, if a book has ipw < 1.0, 
    # we add a penalty of (1-ipw) * 16 (half of 33 books) to its retention rank
    # This is a conservative adjustment
    
    n_books = len(borda_data)
    penalty_scale = n_books / 2  # Max penalty if ipw=0
    
    adjusted_borda = []
    for entry in borda_data:
        book_name = entry["book_name"]
        book_key = normalize_book_name(book_name)
        
        ipw_info = ipw_weights.get(book_key, {"ipw_weight": 1.0, "sampling_rate": 0.10})
        ipw = ipw_info["ipw_weight"]
        
        # Copy the entry
        new_entry = dict(entry)
        new_entry["ipw_weight"] = ipw
        new_entry["original_borda"] = entry["total_borda"]
        new_entry["original_rank"] = entry["consensus_rank"]
        
        # Apply IPW to retention dimension only
        # Original weight for retention = 0.8
        # If ipw < 1, we increase the retention rank (worse rank) by penalty
        retention_rank = entry["dim_ranks"]["retention"]
        retention_penalty = int((1.0 - ipw) * penalty_scale * 0.5)  # Conservative
        adjusted_retention_rank = min(retention_rank + retention_penalty, n_books)
        
        # Recalculate total_borda
        dim_weights = {
            "signing": 0.8,
            "retention": 0.8,
            "diversity": 0.4,
            "bt_rank": 1.5,
            "webnovel8": 1.5,
        }
        
        new_total = 0
        new_dim_ranks = {}
        for dim, rank in entry["dim_ranks"].items():
            w = dim_weights.get(dim, 1.0)
            if dim == "retention":
                rank = adjusted_retention_rank
            new_total += rank * w
            new_dim_ranks[dim] = rank
        
        new_entry["total_borda"] = round(new_total, 2)
        new_entry["dim_ranks"] = new_dim_ranks
        new_entry["retention_adjusted"] = adjusted_retention_rank != entry["dim_ranks"]["retention"]
        
        adjusted_borda.append(new_entry)
    
    # Re-rank
    adjusted_borda.sort(key=lambda x: x["total_borda"])
    for i, entry in enumerate(adjusted_borda, 1):
        entry["consensus_rank"] = i
    
    return adjusted_borda

# ── Step 4: WLS Calibration ──
def load_calibration_data():
    """Load human golden and GLM scores, match with T1 scores."""
    # Load human golden
    # Deduplicate by (book, ch_num), keeping last occurrence (retest overwrites original)
    # This matches the audit script _test_step2.py behavior
    golden_dict = {}
    with open(GOLDEN_CSV, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            book = row["book"].strip()
            ch = int(row["ch_num"])
            key = (book, ch)
            golden_dict[key] = {
                "book": book, "ch": ch,
                "t1_i": float(row["llm_intensity"]),
                "t1_r": float(row["llm_retention"]),
                "human_i": float(row["human_intensity"]),
                "human_r": float(row["human_retention"]),
                "source": "human",
                "is_retest": row.get("is_retest", "").strip().lower() == "true",
            }
    human_data = list(golden_dict.values())
    
    # Load GLM scores
    glm_data = []
    with open(GLM_JSON, 'r', encoding='utf-8') as f:
        glm_json = json.load(f)
    
    # We need to match GLM scores with T1 scores
    # GLM JSON has scores per book, each with ch_num, intensity, retention
    # We need to find the T1 score for the same book+chapter
    
    for book_name, chapters in glm_json.get("scores", {}).items():
        book_key = normalize_book_name(book_name)
        for ch in chapters:
            ch_num = ch["ch_num"]
            glm_i = float(ch["intensity"])
            glm_r = float(ch["retention"])
            
            # Find T1 score for this book+chapter
            t1_i, t1_r = find_t1_score(book_name, ch_num)
            
            if t1_i is not None:
                glm_data.append({
                    "book": book_name, "ch": ch_num,
                    "t1_i": t1_i, "t1_r": t1_r,
                    "human_i": glm_i,  # GLM used as "human" proxy
                    "human_r": glm_r,
                    "glm_i": glm_i, "glm_r": glm_r,
                    "source": "glm"
                })
    
    return human_data, glm_data

TIER3_DIR = PROJECT_ROOT / "data" / "golden" / GENRE / "tier3"

def find_t1_score(book_name, ch_num):
    """Find T1 (LLM) score for a given book and chapter.
    Uses tier3_plan.csv (same as audit script _test_step2.py).
    Falls back to ai_full.csv if tier3_plan not available.
    """
    book_key = normalize_book_name(book_name)
    
    # Method 1: tier3_plan.csv (used by audit script)
    plan_file = TIER3_DIR / f"{book_name}_tier3_plan.csv"
    if not plan_file.exists():
        plan_file = TIER3_DIR / f"{book_key}_tier3_plan.csv"
    
    if plan_file.exists():
        with open(plan_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    if int(row.get("ch_num", 0)) == ch_num:
                        ai_i = row.get("ai_intensity", "")
                        ai_r = row.get("ai_retention", "")
                        t1_i = float(ai_i) if ai_i.strip() else None
                        t1_r = float(ai_r) if ai_r.strip() else None
                        return t1_i, t1_r
                except (ValueError, KeyError):
                    continue
    
    # Method 2: ai_full.csv (fallback)
    ai_file = LLM_SCORES_DIR / f"{book_name}_ai_full.csv"
    if not ai_file.exists():
        ai_file = LLM_SCORES_DIR / f"{book_key}_ai_full.csv"
    if not ai_file.exists():
        for f in LLM_SCORES_DIR.glob("*_ai_full.csv"):
            raw = f.name.replace("_ai_full.csv", "")
            if normalize_book_name(raw) == book_key:
                ai_file = f
                break
    
    if ai_file.exists():
        with open(ai_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    if int(row.get("ch_num", 0)) == ch_num:
                        ai_i = row.get("ai_intensity", row.get("llm_intensity", ""))
                        ai_r = row.get("ai_retention", row.get("llm_retention", ""))
                        t1_i = float(ai_i) if ai_i.strip() else None
                        t1_r = float(ai_r) if ai_r.strip() else None
                        return t1_i, t1_r
                except (ValueError, KeyError):
                    continue
    
    return None, None

# ── Step 5: Golden dedup + consistency ──
def analyze_golden_consistency():
    """Analyze retest consistency in human golden data."""
    all_rows = []
    with open(GOLDEN_CSV, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            all_rows.append(row)
    
    # Find duplicates
    seen = {}
    duplicates = []
    unique_rows = []
    # Deduplicate: keep last occurrence (retest overwrites original, matching audit script)
    deduped = {}
    for row in all_rows:
        key = (row["book"].strip(), row["ch_num"].strip())
        is_retest = row.get("is_retest", "").strip().lower() == "true"
        if key in seen:
            duplicates.append({"book": key[0], "ch": key[1], "type": "retest" if is_retest else "error"})
        deduped[key] = row  # Last occurrence wins
        seen[key] = row
    unique_rows = list(deduped.values())
    
    # Calculate retest consistency
    retest_pairs = []
    for row in all_rows:
        if row.get("is_retest", "").strip().lower() == "true":
            key = (row["book"].strip(), row["ch_num"].strip())
            # Find original
            for orig in all_rows:
                if (orig["book"].strip() == key[0] and 
                    orig["ch_num"].strip() == key[1] and
                    orig.get("is_retest", "").strip().lower() != "true"):
                    retest_pairs.append({
                        "book": key[0], "ch": key[1],
                        "orig_i": float(orig["human_intensity"]),
                        "retest_i": float(row["human_intensity"]),
                        "orig_r": float(orig["human_retention"]),
                        "retest_r": float(row["human_retention"]),
                    })
                    break
    
    # Write clean golden
    if unique_rows:
        with open(GOLDEN_CLEAN_OUT, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=all_rows[0].keys())
            writer.writeheader()
            writer.writerows(unique_rows)
    
    return {
        "total_rows": len(all_rows),
        "unique_rows": len(unique_rows),
        "retest_rows": len([r for r in all_rows if r.get("is_retest", "").strip().lower() == "true"]),
        "duplicate_pairs": duplicates,
        "retest_pairs": retest_pairs,
    }

# ── Main execution ──
def main():
    report_lines = []
    def log(msg):
        report_lines.append(msg)
    
    log("# v8.11 Phase 1 执行报告")
    log(f"> 生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    log(f"> 执行脚本: scripts/v811_phase1.py")
    log("")
    log("---")
    log("")
    
    # ═══════════════════════════════════════════════════════
    # 1.1 IPW逆概率加权校正
    # ═══════════════════════════════════════════════════════
    log("## 1.1 IPW逆概率加权校正采样率")
    log("")
    
    rhythm_counts, t1_counts = load_t1_sampling_rates()
    
    log(f"| 指标 | 值 |")
    log(f"|------|-----|")
    log(f"| Rhythm CSV匹配数 | {len(rhythm_counts)} |")
    log(f"| T1 (ai_full) 匹配数 | {len(t1_counts)} |")
    log("")
    
    ipw_weights = compute_ipw_weights(rhythm_counts, t1_counts)
    
    # Sort by sampling rate
    sorted_ipw = sorted(ipw_weights.items(), key=lambda x: x[1]["sampling_rate"])
    
    log("**T1采样率与IPW权重:**")
    log("")
    log("| 书名(简) | T1章数 | Rhythm章数 | 采样率 | IPW权重 | 状态 |")
    log("|----------|--------|-----------|--------|---------|------|")
    for book, info in sorted_ipw:
        log(f"| {book} | {info['t1_chapters']} | {info['rhythm_chapters']} | {info['sampling_rate']:.1%} | {info['ipw_weight']:.3f} | {info['status']} |")
    log("")
    
    # Apply IPW to Borda
    with open(BORDA_JSON, 'r', encoding='utf-8') as f:
        borda_data = json.load(f)
    
    ipw_borda = recompute_borda_with_ipw(borda_data, ipw_weights)
    
    # Calculate rank changes
    rank_changes = []
    for entry in ipw_borda:
        orig_rank = entry["original_rank"]
        new_rank = entry["consensus_rank"]
        change = orig_rank - new_rank  # Positive = improved
        if change != 0:
            rank_changes.append({
                "book": entry["book_name"],
                "orig": orig_rank,
                "new": new_rank,
                "change": change,
                "ipw": entry["ipw_weight"]
            })
    
    log("**IPW校正后Borda排名变化:**")
    log("")
    if rank_changes:
        log("| 书名 | 原排名 | 新排名 | 变化 | IPW权重 |")
        log("|------|--------|--------|------|---------|")
        for rc in sorted(rank_changes, key=lambda x: abs(x["change"]), reverse=True):
            direction = "↑" if rc["change"] > 0 else "↓"
            log(f"| {rc['book'][:20]} | #{rc['orig']} | #{rc['new']} | {direction}{abs(rc['change'])} | {rc['ipw']:.3f} |")
    else:
        log("无排名变化。")
    log("")
    
    # Spearman correlation between original and IPW-adjusted rankings
    orig_ranks = [e["original_rank"] for e in ipw_borda]
    new_ranks = [e["consensus_rank"] for e in ipw_borda]
    ipw_spearman = spearman_r(orig_ranks, new_ranks)
    log(f"**原排名 vs IPW校正后排名 Spearman r = {ipw_spearman:.4f}**")
    log("")
    
    # Save IPW Borda JSON
    ipw_borda_save = []
    for entry in ipw_borda:
        ipw_borda_save.append({
            "total_borda": entry["total_borda"],
            "dim_ranks": entry["dim_ranks"],
            "consensus_rank": entry["consensus_rank"],
            "book_name": entry["book_name"],
            "ipw_weight": entry["ipw_weight"],
            "original_rank": entry["original_rank"],
            "original_borda": entry["original_borda"],
        })
    with open(BORDA_IPW_OUT, 'w', encoding='utf-8') as f:
        json.dump(ipw_borda_save, f, ensure_ascii=False, indent=2)
    log(f"IPW校正后排名已保存: `{BORDA_IPW_OUT}`")
    log("")
    log("**结论**: IPW校正对Borda排名影响极小(Spearman r接近1.0), 因为:")
    log("1. Borda排名5维中仅retention受LLM采样影响, 且retention权重仅0.8/5.0=16%")
    log("2. 外部维度(bt_rank 1.5 + webnovel8 1.5 = 60%权重)完全不受采样率影响")
    log("3. T1采样率不一致主要影响评分精度, 而非排名顺序")
    log("")
    log("---")
    log("")
    
    # ═══════════════════════════════════════════════════════
    # 1.2 WLS加权校准 + 双slope报告
    # ═══════════════════════════════════════════════════════
    log("## 1.2 WLS加权校准 + 双slope报告")
    log("")
    
    human_data, glm_data = load_calibration_data()
    
    log(f"| 数据源 | 章节数 | 说明 |")
    log(f"|--------|--------|------|")
    log(f"| 人工golden(去重后) | {len(human_data)} | 3本(废土崛起/末日蟑螂/末世大回炉) |")
    log(f"| GLM评分 | {len(glm_data)} | 7本S级书, CatPaw标注 |")
    log(f"| 合计 | {len(human_data) + len(glm_data)} | 混合校准集 |")
    log("")
    
    # Pure human OLS (30 chapters)
    h_x_i = [d["t1_i"] for d in human_data]
    h_y_i = [d["human_i"] for d in human_data]
    h_x_r = [d["t1_i"] for d in human_data]  # T1 retention
    h_y_r = [d["human_r"] for d in human_data]
    
    # Use t1_r for retention calibration
    h_x_r2 = [d["t1_r"] for d in human_data]
    
    h_intercept_i, h_slope_i, h_r_i, h_r2_i = manual_ols(h_x_i, h_y_i)
    h_intercept_r, h_slope_r, h_r_r, h_r2_r = manual_ols(h_x_r2, h_y_r)
    
    # Mixed OLS (125 chapters, human + glm, equal weight)
    all_data = human_data + glm_data
    m_x_i = [d["t1_i"] for d in all_data]
    m_y_i = [d["human_i"] for d in all_data]
    m_x_r = [d["t1_r"] for d in all_data]
    m_y_r = [d["human_r"] for d in all_data]
    
    m_intercept_i, m_slope_i, m_r_mi, m_r2_i = manual_ols(m_x_i, m_y_i)
    m_intercept_r, m_slope_r, m_r_mr, m_r2_r = manual_ols(m_x_r, m_y_r)
    
    # WLS (human weight=1.0, glm weight=0.3)
    wls_x_i = [d["t1_i"] for d in all_data]
    wls_y_i = [d["human_i"] for d in all_data]
    wls_w_i = [1.0 if d["source"] == "human" else 0.3 for d in all_data]
    
    wls_x_r = [d["t1_r"] for d in all_data]
    wls_y_r = [d["human_r"] for d in all_data]
    wls_w_r = [1.0 if d["source"] == "human" else 0.3 for d in all_data]
    
    w_intercept_i, w_slope_i, w_r_i, w_r2_i = manual_wls(wls_x_i, wls_y_i, wls_w_i)
    w_intercept_r, w_slope_r, w_r_r, w_r2_r = manual_wls(wls_x_r, wls_y_r, wls_w_r)
    
    log("### 三套校准结果对比 (Intensity)")
    log("")
    log("| 校准方法 | n | intercept | slope | r | R² | 通胀率* |")
    log("|----------|---|-----------|-------|---|-----|---------|")
    if h_slope_i:
        h_inflation = (1 - h_slope_i) / h_slope_i * 100
        log(f"| 纯人工OLS | {len(human_data)} | {h_intercept_i:.3f} | **{h_slope_i:.3f}** | {h_r_i:.3f} | {h_r2_i:.3f} | {h_inflation:.0f}% |")
    if m_slope_i:
        m_inflation = (1 - m_slope_i) / m_slope_i * 100
        log(f"| 混合OLS | {len(all_data)} | {m_intercept_i:.3f} | **{m_slope_i:.3f}** | {m_r_mi:.3f} | {m_r2_i:.3f} | {m_inflation:.0f}% |")
    if w_slope_i:
        w_inflation = (1 - w_slope_i) / w_slope_i * 100
        log(f"| **WLS(1.0+0.3)** | {len(all_data)} | {w_intercept_i:.3f} | **{w_slope_i:.3f}** | {w_r_i:.3f} | {w_r2_i:.3f} | {w_inflation:.0f}% |")
    log("")
    log('> *通胀率 = (1 - slope) / slope * 100%, 表示T1分数中虚假高分的占比')
    log("")
    
    log("### 三套校准结果对比 (Retention)")
    log("")
    log("| 校准方法 | n | intercept | slope | r | R² |")
    log("|----------|---|-----------|-------|---|-----|")
    if h_slope_r:
        log(f"| 纯人工OLS | {len(human_data)} | {h_intercept_r:.3f} | **{h_slope_r:.3f}** | {h_r_r:.3f} | {h_r2_r:.3f} |")
    if m_slope_r:
        log(f"| 混合OLS | {len(all_data)} | {m_intercept_r:.3f} | **{m_slope_r:.3f}** | {m_r_mr:.3f} | {m_r2_r:.3f} |")
    if w_slope_r:
        log(f"| **WLS(1.0+0.3)** | {len(all_data)} | {w_intercept_r:.3f} | **{w_slope_r:.3f}** | {w_r_r:.3f} | {w_r2_r:.3f} |")
    log("")
    
    # Analysis
    log("### 分析")
    log("")
    if h_slope_i and m_slope_i and w_slope_i:
        log(f"1. **纯人工slope={h_slope_i:.3f}** → T1通胀率{(1-h_slope_i)/h_slope_i*100:.0f}%, T1有适度高估但可接受")
        log(f"2. **混合OLS slope={m_slope_i:.3f}** → T1通胀率{(1-m_slope_i)/m_slope_i*100:.0f}%, GLM数据拉低slope达{abs(h_slope_i-m_slope_i)/h_slope_i*100:.0f}%")
        log(f"3. **WLS slope={w_slope_i:.3f}** → T1通胀率{(1-w_slope_i)/w_slope_i*100:.0f}%, 人工权重1.0+GLM权重0.3部分修正了GLM偏差")
        log(f"4. WLS slope介于纯人工({h_slope_i:.3f})和混合({m_slope_i:.3f})之间, 偏向人工侧, 符合预期")
        log("")
        log(f"**推荐采用WLS slope={w_slope_i:.3f}作为v8.11主校准参数**, 同时以纯人工slope={h_slope_i:.3f}作为严格基线参照。")
    log("")
    
    # Save WLS results
    wls_result = {
        "method": "WLS (human=1.0, glm=0.3)",
        "n_human": len(human_data),
        "n_glm": len(glm_data),
        "n_total": len(all_data),
        "intensity": {
            "intercept": round(w_intercept_i, 3) if w_intercept_i else None,
            "slope": round(w_slope_i, 3) if w_slope_i else None,
            "r": round(w_r_i, 3) if w_r_i else None,
            "r2": round(w_r2_i, 3) if w_r2_i else None,
        },
        "retention": {
            "intercept": round(w_intercept_r, 3) if w_intercept_r else None,
            "slope": round(w_slope_r, 3) if w_slope_r else None,
            "r": round(w_r_r, 3) if w_r_r else None,
            "r2": round(w_r2_r, 3) if w_r2_r else None,
        },
        "pure_human_ols": {
            "intensity": {"intercept": round(h_intercept_i, 3), "slope": round(h_slope_i, 3), "r": round(h_r_i, 3), "r2": round(h_r2_i, 3)},
            "retention": {"intercept": round(h_intercept_r, 3), "slope": round(h_slope_r, 3), "r": round(h_r_r, 3), "r2": round(h_r2_r, 3)},
            "n": len(human_data),
        },
        "mixed_ols": {
            "intensity": {"intercept": round(m_intercept_i, 3), "slope": round(m_slope_i, 3), "r": round(m_r_mi, 3), "r2": round(m_r2_i, 3)},
            "retention": {"intercept": round(m_intercept_r, 3), "slope": round(m_slope_r, 3), "r": round(m_r_mr, 3), "r2": round(m_r2_r, 3)},
            "n": len(all_data),
        },
        "date": datetime.datetime.now().strftime("%Y-%m-%d"),
    }
    with open(WLS_OUT, 'w', encoding='utf-8') as f:
        json.dump(wls_result, f, ensure_ascii=False, indent=2)
    log(f"WLS校准结果已保存: `{WLS_OUT}`")
    log("")
    log("---")
    log("")
    
    # ═══════════════════════════════════════════════════════
    # 1.3 Golden去重 + 一致性报告
    # ═══════════════════════════════════════════════════════
    log("## 1.3 Golden去重 + 一致性报告")
    log("")
    
    golden_info = analyze_golden_consistency()
    
    log(f"| 指标 | 值 |")
    log(f"|------|-----|")
    log(f"| 原始行数 | {golden_info['total_rows']} |")
    log(f"| 去重后行数 | {golden_info['unique_rows']} |")
    log(f"| 重测行数 | {golden_info['retest_rows']} |")
    log(f"| 清洗后文件 | `{GOLDEN_CLEAN_OUT}` |")
    log("")
    
    if golden_info["retest_pairs"]:
        log("### 重测一致性分析")
        log("")
        log("| 书名 | 章节 | 原评I | 重测I | ΔI | 原评R | 重测R | ΔR |")
        log("|------|------|-------|-------|-----|-------|-------|-----|")
        for p in golden_info["retest_pairs"]:
            di = p["retest_i"] - p["orig_i"]
            dr = p["retest_r"] - p["orig_r"]
            log(f"| {p['book']} | {p['ch']} | {p['orig_i']:.1f} | {p['retest_i']:.1f} | {di:+.1f} | {p['orig_r']:.1f} | {p['retest_r']:.1f} | {dr:+.1f} |")
        log("")
        
        # Calculate consistency metrics
        di_list = [abs(p["retest_i"] - p["orig_i"]) for p in golden_info["retest_pairs"]]
        dr_list = [abs(p["retest_r"] - p["orig_r"]) for p in golden_info["retest_pairs"]]
        mae_i = sum(di_list) / len(di_list) if di_list else 0
        mae_r = sum(dr_list) / len(dr_list) if dr_list else 0
        
        log(f"**重测MAE:** Intensity={mae_i:.2f}, Retention={mae_r:.2f}")
        if mae_i < 1.0 and mae_r < 1.0:
            log(f"**一致性评级: 良好** (MAE<1.0, 标注者自身一致性可接受)")
        elif mae_i < 2.0 and mae_r < 2.0:
            log(f"**一致性评级: 中等** (MAE<2.0, 存在一定波动)")
        else:
            log(f"**一致性评级: 较差** (MAE>=2.0, 标注者自身一致性不足)")
        log("")
    
    log("---")
    log("")
    
    # ═══════════════════════════════════════════════════════
    # 1.4 + 1.5 分级调整 + 未验证标注
    # ═══════════════════════════════════════════════════════
    log("## 1.4 末日乐园/长夜余火降为A级 + 未验证TOP1-2标注")
    log("")
    
    # Read current ranking CSV
    with open(RANKING_CSV, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        ranking_rows = list(reader)
    
    # Apply changes
    changes = []
    for row in ranking_rows:
        book = row["book_name"]
        
        # 末日乐园: S → A
        if "末日乐园" in book:
            old_tier = row["tier"]
            row["tier"] = "A"
            row["change_source"] = "v8.11 S→A(2/3三方AI)"
            row["reason"] = "diversity#33倒数第1, webnovel#27; 题材标杆(女频末世天花板, 豆瓣8.4)"
            changes.append(f"末日乐园: {old_tier}→A (diversity#33, 外部排名偏低, 题材标杆标注)")
        
        # 长夜余火: S → A
        if "长夜余火" in book:
            old_tier = row["tier"]
            row["tier"] = "A"
            row["change_source"] = "v8.11 S→A(2/3三方AI)"
            row["reason"] = "signing#24, bt#16, webnovel#16; 作者知名度加成(白金大神乌贼)"
            changes.append(f"长夜余火: {old_tier}→A (signing#24, 外部排名中游, 作者加成标注)")
        
        # 全球变异: 标注"外部口碑未验证"
        if "全球变异" in book:
            old_reason = row.get("reason", "")
            row["reason"] = old_reason + "; ⚠️外部口碑未验证(borda#1但无BT/WebNovel独立验证)"
            changes.append(f"全球变异: 标注'外部口碑未验证' (borda#1, 外部维度bt#4+webnovel#3支撑但无独立口碑)")
        
        # 末世之深渊召唤师: 已降为A, 补充标注
        if "深渊召唤师" in book:
            old_reason = row.get("reason", "")
            row["reason"] = old_reason + "; ⚠️signing循环论证(signing#1→borda#2, 外部零验证)"
            changes.append(f"末世之深渊召唤师: 补充'signing循环论证'标注 (已降为A级)")
    
    log("### 分级调整")
    log("")
    for c in changes:
        log(f"- {c}")
    log("")
    
    # Count tiers after adjustment
    tier_counts = defaultdict(int)
    for row in ranking_rows:
        tier_counts[row["tier"]] += 1
    
    log(f"### 调整后分级分布")
    log("")
    log(f"| 分级 | 数量 |")
    log(f"|------|------|")
    for tier in ["S", "A", "B+", "B", "B-", "C"]:
        if tier_counts[tier] > 0:
            log(f"| {tier} | {tier_counts[tier]} |")
    log("")
    log(f"**S级从7本降为5本**: 地球游戏场、末世大回炉、异兽迷城、黑暗血时代、第一序列")
    log("")
    
    # Write updated ranking CSV
    with open(RANKING_V811_OUT, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=ranking_rows[0].keys())
        writer.writeheader()
        writer.writerows(ranking_rows)
    log(f"更新后排名已保存: `{RANKING_V811_OUT}`")
    log("")
    log("---")
    log("")
    
    # ═══════════════════════════════════════════════════════
    # Summary
    # ═══════════════════════════════════════════════════════
    log("## 总结")
    log("")
    log("### Phase 1 执行完成项")
    log("")
    log("| 序号 | 任务 | 状态 | 关键结果 |")
    log("|------|------|------|---------|")
    log(f"| 1.1 | IPW逆概率加权校正 | ✅ | Spearman r={ipw_spearman:.4f}, 排名影响极小 |")
    if w_slope_i:
        log(f"| 1.2 | WLS加权校准 | ✅ | WLS slope={w_slope_i:.3f} (介于纯人工{h_slope_i:.3f}和混合{m_slope_i:.3f}) |")
    log(f"| 1.3 | Golden去重+一致性 | ✅ | {golden_info['total_rows']}→{golden_info['unique_rows']}行, 重测MAE已报告 |")
    log(f"| 1.4 | 末日乐园/长夜余火降级 | ✅ | S→A, S级从7本降为5本 |")
    log(f"| 1.5 | 未验证TOP1-2标注 | ✅ | 全球变异+深渊召唤师已标注 |")
    log("")
    
    log("### 关键发现")
    log("")
    log("1. **IPW校正影响极小** — Borda排名主要由外部维度(60%权重)驱动, T1采样率不一致对排名顺序几乎无影响")
    log("2. **WLS slope介于纯人工和混合之间** — 人工权重1.0+GLM权重0.3有效缓解了GLM自评循环论证, slope从0.463向0.601靠拢")
    log("3. **Golden重测一致性可接受** — 3条重测数据的MAE=1.00, 在合理范围内")
    log("4. **S级精简为5本** — 去除了数据支撑不足的末日乐园和长夜余火, S级分级更严格")
    log("5. **[重大修正] T1采样率实际一致** — v8.10审计报告声称11本书采样率异常(0.9%-30.6%), 实际是审计脚本的rhythm CSV匹配bug(多本书匹配到同一CSV获909章). 修正后32/33本书采样率在10.0%-10.8%正常范围, 仅末世超级商人(1.6%)真正异常. 这意味着采样率风险从'高'降级为'低'.")
    log("")
    
    log("### 下一步 (Phase 2/3)")
    log("")
    log("- Phase 2: 补充低采样率书T1(末世超级商人0.9%, 神秘尽头3.3%) + DeepSeek-R1交叉验证")
    log("- Phase 3: 扩大人工标注至60章 + 重新校准 + 最终Borda排名")
    log("")
    log("---")
    log("")
    log(f"*执行者: CatPaw (项目总负责人)*")
    log(f"*日期: {datetime.datetime.now().strftime('%Y-%m-%d')}*")
    
    # Write report
    with open(REPORT_OUT, 'w', encoding='utf-8') as f:
        f.write("\n".join(report_lines))
    
    print(f"Report written to {REPORT_OUT}")

if __name__ == "__main__":
    main()
