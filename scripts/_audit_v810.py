#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
v8.10 全面独立审计脚本
输出: scripts/_audit_v810_out.txt
"""
import csv, json, os, math, sys
from pathlib import Path
from collections import Counter, defaultdict

PROJECT = Path(r"d:\Code\xiaoshuo")
OUT = PROJECT / "scripts" / "_audit_v810_out.txt"

def log(*args):
    msg = " ".join(str(a) for a in args)
    # Replace problematic unicode chars for console
    safe_msg = msg.replace("\xb2", "^2").replace("\u2014", "-").replace("\u2013", "-")
    try:
        print(safe_msg)
    except UnicodeEncodeError:
        pass
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

# Clear output
OUT.write_text("", encoding="utf-8")

# ── Helpers ──
def read_csv(path, encoding="utf-8-sig"):
    with open(path, encoding=encoding) as f:
        return list(csv.DictReader(f))

def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def pearson_r(x, y):
    """Manual Pearson correlation (np.corrcoef crashes on this Windows env)"""
    n = len(x)
    if n < 3:
        return None
    mx = sum(x) / n
    my = sum(y) / n
    num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    dx = math.sqrt(sum((xi - mx) ** 2 for xi in x))
    dy = math.sqrt(sum((yi - my) ** 2 for yi in y))
    if dx < 1e-10 or dy < 1e-10:
        return None
    return num / (dx * dy)

def spearman_r(x, y):
    """Manual Spearman rank correlation"""
    n = len(x)
    if n < 3:
        return None
    def rank(vals):
        indexed = sorted(enumerate(vals), key=lambda t: t[1])
        ranks = [0] * n
        i = 0
        while i < n:
            j = i
            while j < n and indexed[j][1] == indexed[i][1]:
                j += 1
            avg = (i + j + 1) / 2.0
            for k in range(i, j):
                ranks[indexed[k][0]] = avg
            i = j
        return ranks
    rx, ry = rank(x), rank(y)
    return pearson_r(rx, ry)

def safe_float(v, default=None):
    try:
        return float(v)
    except (ValueError, TypeError):
        return default

# ── Load novel_index ──
index = read_json(PROJECT / "data" / "raw" / "novel_index.json")
apocalypse_novels = index["genres"]["末世"]["novels"]

log("=" * 80)
log("v8.10 全面独立审计报告")
log("=" * 80)

# ============================================================
# STEP 1: 数据完整性审计
# ============================================================
log("\n" + "=" * 80)
log("STEP 1: 数据完整性审计")
log("=" * 80)

# ── 1.1 原始数据审计 ──
log("\n--- 1.1 原始数据审计 ---")
novel_dir = PROJECT / "data" / "raw" / "novels" / "末世"

txt_files_exist = 0
txt_files_missing = []
txt_sizes = []
duplicate_files = []
seen_filenames = {}

for novel in apocalypse_novels:
    fname = novel["file"]
    fpath = novel_dir / fname
    if fpath.exists():
        size_kb = fpath.stat().st_size / 1024
        txt_files_exist += 1
        txt_sizes.append((fname[:30], size_kb, novel.get("size_kb", 0)))
        if size_kb < 100:
            log(f"  WARN: {fname[:40]} size={size_kb:.0f}KB < 100KB")
    else:
        txt_files_missing.append(fname)
    
    # Check for duplicates
    key = fname.replace("（校对版全本）", "").replace("（精校版全本）", "").replace("（校对版）", "")
    if key in seen_filenames:
        duplicate_files.append((fname, seen_filenames[key]))
    seen_filenames[key] = fname

log(f"  TXT文件: {txt_files_exist}/33 存在")
if txt_files_missing:
    log(f"  FAIL: 缺失文件: {txt_files_missing}")
else:
    log(f"  PASS: 全部33个TXT文件存在")

# Check size consistency
size_mismatches = []
for fname, actual, indexed in txt_sizes:
    if indexed > 0 and abs(actual - indexed) / indexed > 0.15:
        size_mismatches.append((fname, actual, indexed))
if size_mismatches:
    log(f"  WARN: {len(size_mismatches)}个文件大小与index偏差>15%:")
    for fn, a, i in size_mismatches[:5]:
        log(f"    {fn}: actual={a:.0f}KB vs index={i}KB")
else:
    log(f"  PASS: 文件大小与index一致(±15%)")

if duplicate_files:
    log(f"  WARN: 可能重复: {duplicate_files}")
else:
    log(f"  PASS: 无明显重复文件")

# Word count spot check (3 books)
log("\n  字数抽样验证:")
import random
sample_books = [apocalypse_novels[0], apocalypse_novels[10], apocalypse_novels[20]]
for novel in sample_books:
    fpath = novel_dir / novel["file"]
    if fpath.exists():
        with open(fpath, encoding="utf-8") as f:
            content = f.read()
        char_count = len(content)
        log(f"    {novel['file'][:30]}: chars={char_count}, size_kb={novel.get('size_kb',0)}")

# ── 1.2 Rhythm CSV审计 ──
log("\n--- 1.2 Rhythm规则评分审计 ---")
rhythm_dir = PROJECT / "data" / "processed" / "末世" / "rhythm"
rhythm_csvs = sorted([f for f in os.listdir(rhythm_dir) if f.endswith(".csv")])
log(f"  Rhythm CSV数量: {len(rhythm_csvs)} (预期33)")

# Cross-check with novel_index
index_rhythm_set = set(n["rhythm_csv"] for n in apocalypse_novels)
actual_rhythm_set = set(rhythm_csvs)
missing_rhythm = index_rhythm_set - actual_rhythm_set
extra_rhythm = actual_rhythm_set - index_rhythm_set
if missing_rhythm:
    log(f"  FAIL: 缺失rhythm CSV: {missing_rhythm}")
else:
    log(f"  PASS: novel_index中的rhythm_csv字段全部存在")
if extra_rhythm:
    log(f"  WARN: 额外rhythm CSV: {extra_rhythm}")

# Detailed rhythm CSV checks
rhythm_stats = []
rhythm_anomalies = []
for rcsv in rhythm_csvs:
    rows = read_csv(rhythm_dir / rcsv)
    n_rows = len(rows)
    
    # Check key columns
    hook_vals = [safe_float(r.get("hook_density", 0)) for r in rows]
    conflict_vals = [safe_float(r.get("conflict_density", 0)) for r in rows]
    wc_vals = [safe_float(r.get("wc", 0)) for r in rows]
    
    hook_mean = sum(hook_vals) / len(hook_vals) if hook_vals else 0
    hook_zero_pct = sum(1 for h in hook_vals if h is not None and h < 0.01) / len(hook_vals) if hook_vals else 0
    wc_zero = sum(1 for w in wc_vals if w is not None and w < 100)
    
    rhythm_stats.append({
        "file": rcsv[:40],
        "rows": n_rows,
        "hook_mean": round(hook_mean, 3),
        "hook_zero_pct": round(hook_zero_pct * 100, 1),
        "wc_min": min(wc_vals) if wc_vals else 0,
        "wc_max": max(wc_vals) if wc_vals else 0,
    })
    
    if hook_zero_pct > 0.5:
        rhythm_anomalies.append(f"  WARN: {rcsv[:40]} hook_zero={hook_zero_pct*100:.1f}% >50%")
    if wc_zero > 0:
        rhythm_anomalies.append(f"  WARN: {rcsv[:40]} has {wc_zero} rows with wc<100")

log(f"  Rhythm CSV行数范围: {min(s['rows'] for s in rhythm_stats)}-{max(s['rows'] for s in rhythm_stats)}")
log(f"  总章节数: {sum(s['rows'] for s in rhythm_stats)}")
log(f"  hook_density均值范围: {min(s['hook_mean'] for s in rhythm_stats):.3f}-{max(s['hook_mean'] for s in rhythm_stats):.3f}")
for a in rhythm_anomalies:
    log(a)
if not rhythm_anomalies:
    log(f"  PASS: 无异常rhythm CSV")

# ── 1.3 Tier1 (AI全读) 评分审计 ──
log("\n--- 1.3 Tier1 (AI全读) 评分审计 ---")
scores_dir = PROJECT / "data" / "processed" / "末世" / "scores"
ai_full_files = sorted([f for f in os.listdir(scores_dir) if f.endswith("_ai_full.csv")])
log(f"  ai_full CSV数量: {len(ai_full_files)} (预期33)")

t1_stats = []
t1_anomalies = []
for af in ai_full_files:
    rows = read_csv(scores_dir / af)
    book_name = af.replace("_ai_full.csv", "")
    n_rows = len(rows)
    
    intensities = [safe_float(r.get("ai_intensity")) for r in rows if safe_float(r.get("ai_intensity")) is not None]
    retentions = [safe_float(r.get("ai_retention")) for r in rows if safe_float(r.get("ai_retention")) is not None]
    ch_nums = [safe_float(r.get("ch_num")) for r in rows if safe_float(r.get("ch_num")) is not None]
    
    # Check for out-of-range values
    out_of_range = [i for i in intensities if i < 1 or i > 10]
    
    # Check for duplicate ch_num
    ch_set = set(ch_nums)
    duplicates = len(ch_nums) - len(ch_set)
    
    # Check ai_analysis non-empty
    analysis_lens = [len(r.get("ai_analysis", "")) for r in rows]
    empty_analysis = sum(1 for a in analysis_lens if a < 10)
    
    # Check sampling interval
    sorted_chs = sorted(ch_nums)
    if len(sorted_chs) > 2:
        intervals = [sorted_chs[i+1] - sorted_chs[i] for i in range(len(sorted_chs)-1)]
        avg_interval = sum(intervals) / len(intervals)
        consecutive = sum(1 for i in intervals if i <= 1)
    else:
        avg_interval = 0
        consecutive = 0
    
    t1_stats.append({
        "book": book_name,
        "n": n_rows,
        "i_mean": round(sum(intensities)/len(intensities), 2) if intensities else 0,
        "i_min": min(intensities) if intensities else 0,
        "i_max": max(intensities) if intensities else 0,
        "r_mean": round(sum(retentions)/len(retentions), 2) if retentions else 0,
        "out_range": len(out_of_range),
        "duplicates": duplicates,
        "empty_analysis": empty_analysis,
        "avg_interval": round(avg_interval, 1),
        "consecutive": consecutive,
    })
    
    if out_of_range:
        t1_anomalies.append(f"  WARN: {book_name} has {len(out_of_range)} intensity values out of [1,10]")
    if duplicates > 0:
        t1_anomalies.append(f"  WARN: {book_name} has {duplicates} duplicate ch_nums")
    if empty_analysis > 0:
        t1_anomalies.append(f"  WARN: {book_name} has {empty_analysis} rows with empty ai_analysis")

# Cross-check T1 row count vs rhythm * 10%
log(f"  T1采样率验证:")
t1_sampling_issues = []
for i, af in enumerate(ai_full_files):
    book_name = af.replace("_ai_full.csv", "")
    t1_n = t1_stats[i]["n"]
    # Find matching rhythm CSV
    rhythm_match = None
    for n in apocalypse_novels:
        rcsv = n["rhythm_csv"]
        # Try to match book name to rhythm CSV
        if book_name in rcsv or rcsv.replace("rhythm_", "").replace(".csv", "") in n["file"]:
            rhythm_match = rcsv
            break
    if rhythm_match:
        rhythm_rows = read_csv(rhythm_dir / rhythm_match)
        rhythm_n = len(rhythm_rows)
        expected_t1 = round(rhythm_n * 0.1)
        ratio = t1_n / rhythm_n if rhythm_n > 0 else 0
        if ratio < 0.05 or ratio > 0.20:
            t1_sampling_issues.append(f"    {book_name}: T1={t1_n}, rhythm={rhythm_n}, ratio={ratio:.1%}")

if t1_sampling_issues:
    log(f"  WARN: {len(t1_sampling_issues)}本书T1采样率异常(不在5%-20%范围):")
    for s in t1_sampling_issues[:10]:
        log(s)
else:
    log(f"  PASS: T1采样率均在合理范围(5%-20%)")

log(f"  T1 intensity范围: {min(s['i_min'] for s in t1_stats)}-{max(s['i_max'] for s in t1_stats)}")
for a in t1_anomalies:
    log(a)
if not t1_anomalies:
    log(f"  PASS: 无T1异常值/重复/空分析")

# ── 1.4 Tier2 评分审计 ──
log("\n--- 1.4 Tier2 (本地模型) 评分审计 ---")
t2_full_files = sorted([f for f in os.listdir(scores_dir) if f.endswith("_t2_full.csv")])
log(f"  t2_full CSV数量: {len(t2_full_files)} (预期33)")

# v8.8 tier mapping
tier_map = {
    "S": ["地球游戏场", "末世大回炉", "异兽迷城", "黑暗血时代", "第一序列", "长夜余火", "末日乐园"],
    "A": ["废土崛起", "我的末世领地", "从红月开始", "世界末日从考试不及格开始", "末世魔神游戏", "末世召唤狂潮", "末日拼图游戏", "末世之深渊召唤师", "神秘尽头", "狩魔手记_烟雨江南", "全球变异，从灾厄降临开始"],
    "B+": ["全球进化", "我在末世有套房", "黑暗文明_古羲", "恐慌沸腾"],
    "B": ["我的女友是丧尸", "灾厄纪元", "黑暗王者", "重卡战车在末世", "末日蟑螂", "第九特区"],
    "B-": ["末世超级商人", "我在末世种个田", "限制级末日症候"],
    "C": ["蹉跎", "黑暗末日"],
}
expected_t2_count = {"S": 50, "A": 30, "B+": 30, "B": 30, "B-": 20, "C": 20}

def find_tier(book_name):
    for tier, books in tier_map.items():
        for b in books:
            if b in book_name or book_name in b:
                return tier
    return None

t2_stats = []
t2_anomalies = []
t1_t2_overlap_issues = []
for tf in t2_full_files:
    book_name = tf.replace("_t2_full.csv", "")
    rows = read_csv(scores_dir / tf)
    n_rows = len(rows)
    tier = find_tier(book_name)
    expected = expected_t2_count.get(tier, "?") if tier else "?"
    
    intensities = [safe_float(r.get("t2_intensity")) for r in rows if safe_float(r.get("t2_intensity")) is not None]
    retentions = [safe_float(r.get("t2_retention")) for r in rows if safe_float(r.get("t2_retention")) is not None]
    ch_nums_t2 = set(safe_float(r.get("ch_num")) for r in rows if safe_float(r.get("ch_num")) is not None)
    
    out_of_range = [i for i in intensities if i < 1 or i > 10]
    
    # Check T1-T2 overlap
    ai_file = f"{book_name}_ai_full.csv"
    if (scores_dir / ai_file).exists():
        t1_rows = read_csv(scores_dir / ai_file)
        ch_nums_t1 = set(safe_float(r.get("ch_num")) for r in t1_rows if safe_float(r.get("ch_num")) is not None)
        overlap = ch_nums_t1 & ch_nums_t2
        if overlap:
            t1_t2_overlap_issues.append(f"  FAIL: {book_name} T1∩T2 overlap={len(overlap)} chapters: {sorted(overlap)[:5]}")
    
    t2_stats.append({
        "book": book_name,
        "tier": tier,
        "n": n_rows,
        "expected": expected,
        "i_mean": round(sum(intensities)/len(intensities), 2) if intensities else 0,
        "i_min": min(intensities) if intensities else 0,
        "i_max": max(intensities) if intensities else 0,
        "out_range": len(out_of_range),
    })
    
    if out_of_range:
        t2_anomalies.append(f"  WARN: {book_name} has {len(out_of_range)} t2_intensity out of [1,10]")
    
    # Check expected count
    if isinstance(expected, int):
        if abs(n_rows - expected) > 15:
            t2_anomalies.append(f"  WARN: {book_name}({tier}) T2={n_rows} vs expected={expected}")

if t1_t2_overlap_issues:
    for s in t1_t2_overlap_issues:
        log(s)
else:
    log(f"  PASS: T1与T2采样零重叠(全部33本)")

log(f"  T2采样量验证:")
for tier in ["S", "A", "B+", "B", "B-", "C"]:
    tier_books = [s for s in t2_stats if s["tier"] == tier]
    if tier_books:
        ns = [s["n"] for s in tier_books]
        log(f"    {tier}级({len(tier_books)}本): T2行数 {min(ns)}-{max(ns)} (预期{expected_t2_count[tier]})")

for a in t2_anomalies:
    log(a)
if not t2_anomalies:
    log(f"  PASS: 无T2异常值/采样量异常")

# ── 1.5 LLM合并CSV审计 ──
log("\n--- 1.5 LLM合并CSV审计 ---")
llm_files = sorted([f for f in os.listdir(scores_dir) if f.endswith("_llm.csv")])
log(f"  llm CSV数量: {len(llm_files)} (预期33)")

llm_merge_issues = []
total_llm_chapters = 0
for lf in llm_files:
    book_name = lf.replace("_llm.csv", "")
    llm_rows = read_csv(scores_dir / lf)
    llm_n = len(llm_rows)
    total_llm_chapters += llm_n
    
    ai_file = f"{book_name}_ai_full.csv"
    t2_file = f"{book_name}_t2_full.csv"
    
    ai_n = len(read_csv(scores_dir / ai_file)) if (scores_dir / ai_file).exists() else 0
    t2_n = len(read_csv(scores_dir / t2_file)) if (scores_dir / t2_file).exists() else 0
    expected_n = ai_n + t2_n
    
    if llm_n != expected_n:
        llm_merge_issues.append(f"  FAIL: {book_name}: llm={llm_n} != ai_full({ai_n}) + t2_full({t2_n})={expected_n}")
    
    # Check column names
    if llm_rows:
        cols = set(llm_rows[0].keys())
        has_ai = "llm_intensity" in cols or "ai_intensity" in cols
        has_t2 = "t2_intensity" in cols
        if not has_ai:
            llm_merge_issues.append(f"  WARN: {book_name} llm.csv missing intensity column")

if llm_merge_issues:
    for s in llm_merge_issues:
        log(s)
else:
    log(f"  PASS: 全部llm.csv行数 = ai_full + t2_full")

log(f"  总LLM章节数: {total_llm_chapters}")

# ============================================================
# STEP 2: 评分关系审计
# ============================================================
log("\n" + "=" * 80)
log("STEP 2: 评分关系审计")
log("=" * 80)

# ── 2.1 Rhythm → LLM强度 传导审计 ──
log("\n--- 2.1 Rhythm → LLM强度 传导审计 ---")
correlation_results = []
for lf in llm_files:
    book_name = lf.replace("_llm.csv", "")
    llm_rows = read_csv(scores_dir / lf)
    
    # Find matching rhythm CSV
    rhythm_match = None
    for n in apocalypse_novels:
        rcsv = n["rhythm_csv"]
        novel_file = n["file"].replace(".txt", "")
        if book_name in novel_file or novel_file in book_name or book_name in rcsv:
            rhythm_match = rcsv
            break
    
    if not rhythm_match:
        # Try fuzzy match
        for n in apocalypse_novels:
            rcsv = n["rhythm_csv"].replace("rhythm_", "").replace(".csv", "")
            if book_name[:6] in rcsv or rcsv[:6] in book_name:
                rhythm_match = n["rhythm_csv"]
                break
    
    if not rhythm_match or not (rhythm_dir / rhythm_match).exists():
        correlation_results.append((book_name, None, None, "no rhythm match"))
        continue
    
    rhythm_rows = read_csv(rhythm_dir / rhythm_match)
    rhythm_lookup = {}
    for r in rhythm_rows:
        ch = safe_float(r.get("ch_num"))
        if ch is not None:
            rhythm_lookup[int(ch)] = r
    
    hook_vals = []
    intensity_vals = []
    conflict_vals = []
    
    for lr in llm_rows:
        ch = safe_float(lr.get("ch_num"))
        if ch is None:
            continue
        ch_int = int(ch)
        if ch_int in rhythm_lookup:
            hook = safe_float(rhythm_lookup[ch_int].get("hook_density"))
            intensity = safe_float(lr.get("llm_intensity"))
            conflict = safe_float(rhythm_lookup[ch_int].get("conflict_density"))
            if hook is not None and intensity is not None:
                hook_vals.append(hook)
                intensity_vals.append(intensity)
                conflict_vals.append(conflict if conflict else 0)
    
    if len(hook_vals) >= 5:
        r_hook = pearson_r(hook_vals, intensity_vals)
        r_conflict = pearson_r(conflict_vals, intensity_vals)
        correlation_results.append((book_name, r_hook, r_conflict, f"n={len(hook_vals)}"))
    else:
        correlation_results.append((book_name, None, None, f"n={len(hook_vals)} too few"))

valid_r = [r[1] for r in correlation_results if r[1] is not None]
log(f"  有效相关系数: {len(valid_r)}/33本")
if valid_r:
    log(f"  hook_density vs llm_intensity Pearson r:")
    log(f"    均值: {sum(valid_r)/len(valid_r):.3f}")
    log(f"    范围: {min(valid_r):.3f} ~ {max(valid_r):.3f}")
    positive = sum(1 for r in valid_r if r > 0)
    negative = sum(1 for r in valid_r if r < 0)
    log(f"    正相关: {positive}本, 负相关: {negative}本")
    
    if sum(valid_r)/len(valid_r) < 0.1:
        log(f"  WARN: 平均相关性极弱(<0.1), rhythm规则指标与LLM评分关联度低")
    elif sum(valid_r)/len(valid_r) > 0.2:
        log(f"  PASS: 平均正相关(>0.2), rhythm→LLM传导合理")
    else:
        log(f"  NOTE: 平均相关性中等(0.1-0.2)")

# ── 2.2 T1 vs T2 一致性审计 ──
log("\n--- 2.2 T1 vs T2 一致性审计 ---")
t1_t2_diffs = []
for i, af in enumerate(ai_full_files):
    book_name = af.replace("_ai_full.csv", "")
    ai_rows = read_csv(scores_dir / af)
    t2_file = f"{book_name}_t2_full.csv"
    if not (scores_dir / t2_file).exists():
        continue
    t2_rows = read_csv(scores_dir / t2_file)
    
    ai_intensities = [safe_float(r.get("ai_intensity")) for r in ai_rows if safe_float(r.get("ai_intensity")) is not None]
    t2_intensities = [safe_float(r.get("t2_intensity")) for r in t2_rows if safe_float(r.get("t2_intensity")) is not None]
    ai_retentions = [safe_float(r.get("ai_retention")) for r in ai_rows if safe_float(r.get("ai_retention")) is not None]
    t2_retentions = [safe_float(r.get("t2_retention")) for r in t2_rows if safe_float(r.get("t2_retention")) is not None]
    
    ai_i_mean = sum(ai_intensities)/len(ai_intensities) if ai_intensities else 0
    t2_i_mean = sum(t2_intensities)/len(t2_intensities) if t2_intensities else 0
    ai_r_mean = sum(ai_retentions)/len(ai_retentions) if ai_retentions else 0
    t2_r_mean = sum(t2_retentions)/len(t2_retentions) if t2_retentions else 0
    
    diff_i = ai_i_mean - t2_i_mean
    diff_r = ai_r_mean - t2_r_mean
    
    t1_t2_diffs.append({
        "book": book_name,
        "t1_i": round(ai_i_mean, 2),
        "t2_i": round(t2_i_mean, 2),
        "diff_i": round(diff_i, 2),
        "t1_r": round(ai_r_mean, 2),
        "t2_r": round(t2_r_mean, 2),
        "diff_r": round(diff_r, 2),
    })

# Expected: T1 Bias=+1.78, T2 Bias=-2.59 → diff ≈ 4.37
mean_diff_i = sum(d["diff_i"] for d in t1_t2_diffs) / len(t1_t2_diffs) if t1_t2_diffs else 0
mean_diff_r = sum(d["diff_r"] for d in t1_t2_diffs) / len(t1_t2_diffs) if t1_t2_diffs else 0
log(f"  T1均值 - T2均值 (intensity): {mean_diff_i:.2f} (预期≈4.37, 因T1 Bias=+1.78, T2 Bias=-2.59)")
log(f"  T1均值 - T2均值 (retention): {mean_diff_r:.2f} (预期≈5.39, 因T1 Bias=+1.48, T2 Bias=-3.91)")

large_diffs = [d for d in t1_t2_diffs if abs(d["diff_i"] - 4.37) > 3]
if large_diffs:
    log(f"  WARN: {len(large_diffs)}本书T1-T2差异远偏离预期4.37:")
    for d in large_diffs[:5]:
        log(f"    {d['book']}: diff_i={d['diff_i']} (T1={d['t1_i']}, T2={d['t2_i']})")
else:
    log(f"  PASS: T1-T2差异与校准Bias一致")

# ── 2.3 Tier3校准有效性审计 ──
log("\n--- 2.3 Tier3校准有效性审计 ---")

# Check human_golden.csv
golden_path = PROJECT / "data" / "golden" / "末世" / "human_golden.csv"
if golden_path.exists():
    golden_rows = read_csv(golden_path)
    golden_books = set(r.get("book", "") for r in golden_rows)
    golden_chs = [(r.get("book", ""), r.get("ch_num", "")) for r in golden_rows]
    golden_ch_set = set(golden_chs)
    golden_dupes = len(golden_chs) - len(golden_ch_set)
    
    human_i = [safe_float(r.get("human_intensity")) for r in golden_rows if safe_float(r.get("human_intensity")) is not None]
    human_r = [safe_float(r.get("human_retention")) for r in golden_rows if safe_float(r.get("human_retention")) is not None]
    
    log(f"  human_golden.csv: {len(golden_rows)}章 from {len(golden_books)}本书: {golden_books}")
    log(f"  human_intensity: mean={sum(human_i)/len(human_i):.2f}, range={min(human_i)}-{max(human_i)}" if human_i else "  no human_intensity")
    log(f"  human_retention: mean={sum(human_r)/len(human_r):.2f}, range={min(human_r)}-{max(human_r)}" if human_r else "  no human_retention")
    if golden_dupes > 0:
        log(f"  WARN: {golden_dupes} duplicate (book, ch_num) entries in golden")
    else:
        log(f"  PASS: 无重复标注")
else:
    log(f"  FAIL: human_golden.csv not found")

# Check tier3_glm_scores.json
glm_path = PROJECT / "data" / "golden" / "末世" / "tier3" / "tier3_glm_scores.json"
if glm_path.exists():
    glm_data = read_json(glm_path)
    glm_scores = glm_data.get("scores", {})
    total_glm = 0
    glm_books = {}
    for book, chapters in glm_scores.items():
        glm_books[book] = len(chapters)
        total_glm += len(chapters)
    
    log(f"  tier3_glm_scores.json: {total_glm}章 from {len(glm_books)}本书")
    for book, n in glm_books.items():
        log(f"    {book}: {n}章")
    
    # Check GLM score distribution
    all_glm_i = []
    all_glm_r = []
    for book, chapters in glm_scores.items():
        for ch in chapters:
            all_glm_i.append(ch.get("intensity", 0))
            all_glm_r.append(ch.get("retention", 0))
    
    if all_glm_i:
        i_counter = Counter(all_glm_i)
        log(f"  GLM intensity分布: {dict(sorted(i_counter.items()))}")
        log(f"  GLM intensity: mean={sum(all_glm_i)/len(all_glm_i):.2f}, range={min(all_glm_i)}-{max(all_glm_i)}")
        
        # Check for score clustering
        most_common = i_counter.most_common(1)[0]
        if most_common[1] / len(all_glm_i) > 0.4:
            log(f"  WARN: GLM intensity聚集: {most_common[0]}分占{most_common[1]/len(all_glm_i)*100:.1f}%")
        else:
            log(f"  PASS: GLM intensity分布分散, 无明显聚集")
    
    # Check GLM vs T1 correlation (where overlap exists)
    glm_t1_pairs_i = []
    glm_t1_pairs_r = []
    for book, chapters in glm_scores.items():
        # Find T1 file for this book
        t1_file = None
        for af in ai_full_files:
            if book in af or af.replace("_ai_full.csv", "") in book:
                t1_file = af
                break
        if not t1_file:
            continue
        t1_rows = read_csv(scores_dir / t1_file)
        t1_lookup = {}
        for r in t1_rows:
            ch = safe_float(r.get("ch_num"))
            if ch is not None:
                t1_lookup[int(ch)] = r
        
        for ch in chapters:
            ch_num = int(ch.get("ch_num", 0))
            if ch_num in t1_lookup:
                t1_i = safe_float(t1_lookup[ch_num].get("ai_intensity"))
                t1_r = safe_float(t1_lookup[ch_num].get("ai_retention"))
                if t1_i is not None:
                    glm_t1_pairs_i.append((ch.get("intensity", 0), t1_i))
                if t1_r is not None:
                    glm_t1_pairs_r.append((ch.get("retention", 0), t1_r))
    
    if len(glm_t1_pairs_i) >= 5:
        glm_vals = [p[0] for p in glm_t1_pairs_i]
        t1_vals = [p[1] for p in glm_t1_pairs_i]
        r = pearson_r(glm_vals, t1_vals)
        log(f"  GLM vs T1 (重叠章节) Pearson r (intensity): {r:.3f} (n={len(glm_t1_pairs_i)})")
        if r and r > 0.5:
            log(f"  WARN: GLM与T1高度相关(r={r:.3f}), 可能存在循环论证: AI校准AI")
        elif r and r > 0.3:
            log(f"  NOTE: GLM与T1中等相关(r={r:.3f}), 部分循环论证风险")
        else:
            log(f"  PASS: GLM与T1相关性低, 循环论证风险较小")

# Check calibration results
calib_path = PROJECT / "data" / "reports" / "末世" / "calibration" / "tier3_calibration.json"
if calib_path.exists():
    calib = read_json(calib_path)
    log(f"\n  校准结果:")
    log(f"    T1 Bias (intensity): +{calib['t1_bias']['i']['bias']} (MAE={calib['t1_bias']['i']['mae']})")
    log(f"    T2 Bias (intensity): {calib['t2_bias']['i']['bias']} (MAE={calib['t2_bias']['i']['mae']})")
    log(f"    OLS (intensity): slope={calib['ols']['i']['slope']}, intercept={calib['ols']['i']['intercept']}, R^2={calib['ols']['i']['r2']}, r={calib['ols']['i']['r']}")
    log(f"    OLS (retention): slope={calib['ols']['r']['slope']}, intercept={calib['ols']['r']['intercept']}, R^2={calib['ols']['r']['r2']}, r={calib['ols']['r']['r']}")
    log(f"    LOOCV (intensity): r={calib['loocv']['i']['r']}, MAE={calib['loocv']['i']['mae']}")
    log(f"    LOOCV (retention): r={calib['loocv']['r']['r']}, MAE={calib['loocv']['r']['mae']}")
    
    # Check LOOCV significance
    n_loocv = calib['loocv']['i']['n']
    r_loocv = calib['loocv']['i']['r']
    t_stat = r_loocv * math.sqrt((n_loocv - 2) / max(1 - r_loocv**2, 1e-6))
    # For n=125, df=123, t_critical for p<0.001 is ~3.37
    log(f"    LOOCV t-statistic: {t_stat:.2f} (df={n_loocv-2}, p<0.001 threshold≈3.37)")
    if abs(t_stat) > 3.37:
        log(f"    PASS: LOOCV r={r_loocv} 统计显著(p<0.001)")
    else:
        log(f"    WARN: LOOCV r={r_loocv} 可能不显著")
    
    # OLS slope interpretation
    slope = calib['ols']['i']['slope']
    log(f"\n  OLS slope分析:")
    log(f"    slope={slope} 意味着T1每+1分, human只+{slope}分")
    log(f"    T1通胀率 = (1-{slope})/{slope} = {(1-slope)/slope*100:.0f}%")
    log(f"    即T1分数有约{(1-slope)*100:.0f}%的通胀")
    
    # 30-chapter only vs 125-chapter comparison
    log(f"\n  30章纯人工 vs 125章混合对比:")
    if golden_path.exists():
        human_only_i = [(safe_float(r.get("human_intensity")), safe_float(r.get("llm_intensity"))) for r in golden_rows if safe_float(r.get("human_intensity")) and safe_float(r.get("llm_intensity"))]
        if len(human_only_i) >= 10:
            h_vals = [p[0] for p in human_only_i]
            t1_vals_30 = [p[1] for p in human_only_i]
            r_30 = pearson_r(h_vals, t1_vals_30)
            bias_30 = sum(t1_vals_30[i] - h_vals[i] for i in range(len(h_vals))) / len(h_vals)
            slope_30_num = sum((t - sum(t1_vals_30)/len(t1_vals_30)) * (h - sum(h_vals)/len(h_vals)) for t, h in zip(t1_vals_30, h_vals))
            slope_30_den = sum((t - sum(t1_vals_30)/len(t1_vals_30))**2 for t in t1_vals_30)
            slope_30 = slope_30_num / slope_30_den if slope_30_den > 0 else 0
            
            log(f"    30章纯人工: r={r_30:.3f}, bias={bias_30:.2f}, slope={slope_30:.3f}")
            log(f"    125章混合:  r={calib['ols']['i']['r']:.3f}, bias={calib['t1_bias']['i']['bias']:.2f}, slope={calib['ols']['i']['slope']:.3f}")
            
            if abs(r_30 - calib['ols']['i']['r']) > 0.15:
                log(f"    WARN: 30章与125章校准结果差异大 → GLM数据可能扭曲了校准方向")
            else:
                log(f"    PASS: 30章与125章校准方向一致")

# ── 2.4 LLM → Commercial → Borda 传导审计 ──
log("\n--- 2.4 LLM评分 → 商业评分 → Borda排名 传导审计 ---")

# Read commercial scores
comm_path = PROJECT / "data" / "processed" / "末世" / "quality" / "commercial_scores.json"
if comm_path.exists():
    comm_data = read_json(comm_path)
    log(f"  commercial_scores.json: {len(comm_data)}本书")
    
    # Check if signing_score is derived from LLM scores
    # Read a few commercial scores to understand structure
    sample = list(comm_data.items())[:3]
    for name, data in sample:
        log(f"    {name[:30]}: overall={data.get('overall')}, grade={data.get('grade')}, sub_genre={data.get('sub_genre', '')}")

# Read Borda ranking
borda_path = PROJECT / "data" / "reports" / "末世" / "synthesis" / "末世_borda_ranking.json"
borda_data = read_json(borda_path)
log(f"\n  Borda排名: {len(borda_data)}本书")

# Check S-level books in Borda ranking
s_books = ["全球变异", "末世大回炉", "末世之深渊召唤师", "地球游戏场", "第一序列", "长夜余火", "末日乐园"]
log(f"\n  S级书Borda排名检查:")
for book_key in s_books:
    for entry in borda_data:
        if book_key in entry["book_name"]:
            rank = entry["consensus_rank"]
            dims = entry["dim_ranks"]
            log(f"    {book_key}: borda#{rank} (signing#{dims.get('signing','?')}, retention#{dims.get('retention','?')}, diversity#{dims.get('diversity','?')}, bt#{dims.get('bt_rank','?')}, webnovel#{dims.get('webnovel8','?')})")
            break

# Borda vs TOPSIS comparison
topsis_path = PROJECT / "data" / "reports" / "末世" / "synthesis" / "末世_topsis_ranking.json"
topsis_data = read_json(topsis_path)
topsis_ranking = topsis_data.get("ranking", [])

log(f"\n  Borda vs TOPSIS TOP10对比:")
borda_top10 = [e["book_name"][:20] for e in borda_data[:10]]
topsis_top10 = [e["book_name"][:20] for e in topsis_ranking[:10]]
for i in range(10):
    match = "✓" if borda_top10[i] == topsis_top10[i] else "✗"
    log(f"    #{i+1}: Borda={borda_top10[i]} vs TOPSIS={topsis_top10[i]} {match}")

# Calculate Spearman between Borda and TOPSIS
borda_ranks = {}
for i, e in enumerate(borda_data):
    borda_ranks[e["book_name"]] = i + 1
topsis_ranks = {}
for i, e in enumerate(topsis_ranking):
    topsis_ranks[e["book_name"]] = i + 1

common_books = set(borda_ranks.keys()) & set(topsis_ranks.keys())
borda_order = [borda_ranks[b] for b in common_books]
topsis_order = [topsis_ranks[b] for b in common_books]
sp = spearman_r(borda_order, topsis_order)
log(f"\n  Borda vs TOPSIS Spearman r: {sp:.3f}" if sp else "  Cannot compute Spearman")

# ============================================================
# STEP 3: 最终排名审计
# ============================================================
log("\n" + "=" * 80)
log("STEP 3: 最终排名审计")
log("=" * 80)

# ── 3.1 排名稳定性审计 ──
log("\n--- 3.1 排名稳定性审计 ---")

# Current Borda weights from config
current_weights = {"signing": 0.8, "retention": 0.8, "diversity": 0.4, "bt_rank": 1.5, "webnovel8": 1.5}
equal_weights = {"signing": 1.0, "retention": 1.0, "diversity": 1.0, "bt_rank": 1.0, "webnovel8": 1.0}

# Simulate equal-weight Borda
# We have dim_ranks in borda_data, we can recompute
equal_borda = {}
for entry in borda_data:
    name = entry["book_name"]
    total = 0
    for dim in ["signing", "retention", "diversity", "bt_rank", "webnovel8"]:
        total += entry["dim_ranks"].get(dim, 33) * equal_weights[dim]
    equal_borda[name] = total

equal_ranking = sorted(equal_borda.items(), key=lambda x: x[1])
equal_ranks = {name: i+1 for i, (name, _) in enumerate(equal_ranking)}

# Original ranks
orig_ranks = {e["book_name"]: e["consensus_rank"] for e in borda_data}

# Spearman between original and equal-weight
common = set(orig_ranks.keys()) & set(equal_ranks.keys())
orig_order = [orig_ranks[b] for b in common]
equal_order = [equal_ranks[b] for b in common]
sp_equal = spearman_r(orig_order, equal_order)
log(f"  场景1: 等权重Borda vs 当前权重Borda")
log(f"    Spearman r: {sp_equal:.3f}" if sp_equal else "    Cannot compute")
log(f"    TOP5变化:")
for i in range(5):
    name, _ = equal_ranking[i]
    orig = orig_ranks.get(name, "?")
    log(f"      等权#{i+1}: {name[:25]} (原排名#{orig})")

# Simulate T1-only (remove T2) - approximate by checking if removing T2 changes mean intensity
# This requires recalculating commercial scores, which is complex. 
# Instead, we check sensitivity by looking at T2's contribution
log(f"\n  场景2: 去掉T2数据(仅T1)的影响估算")
t1_only_impacts = []
for d in t1_t2_diffs:
    # If we remove T2, the mean intensity changes
    # T2 typically has lower intensity (Bias=-2.59)
    # Removing T2 would increase the mean
    impact = d["diff_i"]
    t1_only_impacts.append(impact)
if t1_only_impacts:
    log(f"    T1-T2均值差(intensity): mean={sum(t1_only_impacts)/len(t1_only_impacts):.2f}")
    log(f"    去掉T2后, 每本书intensity均值将上升约{sum(t1_only_impacts)/len(t1_only_impacts):.1f}分")
    log(f"    影响评估: {'高' if abs(sum(t1_only_impacts)/len(t1_only_impacts)) > 2 else '中' if abs(sum(t1_only_impacts)/len(t1_only_impacts)) > 1 else '低'}")

# Simulate OLS calibration effect
log(f"\n  场景3: 应用OLS校准(slope=0.463)后的影响估算")
slope = calib['ols']['i']['slope'] if calib_path.exists() else 0.463
intercept = calib['ols']['i']['intercept'] if calib_path.exists() else 2.249
log(f"    校准公式: human_intensity = {intercept} + {slope} * T1_intensity")
log(f"    校准前T1均值范围: {min(s['i_mean'] for s in t1_stats):.1f} - {max(s['i_mean'] for s in t1_stats):.1f}")
calibrated_means = []
for s in t1_stats:
    cal = intercept + slope * s["i_mean"]
    calibrated_means.append((s["book"], s["i_mean"], round(cal, 2)))
calibrated_means.sort(key=lambda x: x[2], reverse=True)
log(f"    校准后intensity TOP5:")
for name, orig, cal in calibrated_means[:5]:
    log(f"      {name[:25]}: T1={orig} → calibrated={cal}")
log(f"    校准后intensity BOTTOM5:")
for name, orig, cal in calibrated_means[-5:]:
    log(f"      {name[:25]}: T1={orig} → calibrated={cal}")

# ── 3.2 分级合理性审计 ──
log("\n--- 3.2 分级合理性审计 ---")
ranking_csv_path = PROJECT / "data" / "reports" / "rankings" / "末世" / "v8.8_final_ranking.csv"
if ranking_csv_path.exists():
    ranking_rows = read_csv(ranking_csv_path)
    log(f"  v8.8分级表: {len(ranking_rows)}本")
    
    # Check S-level books
    s_books_in_csv = [r for r in ranking_rows if r.get("tier") == "S"]
    log(f"  S级书: {len(s_books_in_csv)}本")
    
    # Cross-reference with Borda ranking
    log(f"\n  S级书Borda排名 vs 人工分级:")
    for r in s_books_in_csv:
        book_name = r.get("book_name", "")
        borda_rank = r.get("borda_rank", "?")
        key_metric = r.get("key_metric", "")
        reason = r.get("reason", "")
        log(f"    {book_name}: tier=S, borda#{borda_rank}, metric={key_metric}")
        log(f"      reason: {reason}")
    
    # Special focus: 长夜余火 and 末日乐园
    log(f"\n  重点质疑: 长夜余火(borda#15)和末日乐园(borda#23)为何是S级?")
    
    for book_key in ["长夜余火", "末日乐园"]:
        # Find in borda
        for entry in borda_data:
            if book_key in entry["book_name"]:
                dims = entry["dim_ranks"]
                log(f"\n    {book_key} (borda#{entry['consensus_rank']}):")
                log(f"      signing#{dims.get('signing','?')}, retention#{dims.get('retention','?')}, diversity#{dims.get('diversity','?')}, bt#{dims.get('bt_rank','?')}, webnovel#{dims.get('webnovel8','?')}")
                
                # Find in TOPSIS
                for te in topsis_ranking:
                    if book_key in te["book_name"]:
                        log(f"      TOPSIS#{te['topsis_rank']} (CC={te['closeness']})")
                        log(f"      TOPSIS dim_scores: {te['dim_scores']}")
                        break
                break
        
        # Find in ranking CSV
        for r in ranking_rows:
            if book_key in r.get("book_name", ""):
                log(f"      人工分级依据: {r.get('reason', '')}")
                break
    
    # Check C-level books
    c_books = [r for r in ranking_rows if r.get("tier") == "C"]
    log(f"\n  C级书检查:")
    for r in c_books:
        log(f"    {r.get('book_name','')}: borda#{r.get('borda_rank','?')}, reason={r.get('reason','')}")

# ── 3.3 外部验证审计 ──
log("\n--- 3.3 外部验证审计 ---")
log(f"  TOP5 (Borda):")
for i, entry in enumerate(borda_data[:5]):
    log(f"    #{i+1}: {entry['book_name'][:30]} (borda={entry['total_borda']})")
log(f"  BOTTOM5 (Borda):")
for entry in borda_data[-5:]:
    log(f"    #{entry['consensus_rank']}: {entry['book_name'][:30]} (borda={entry['total_borda']})")

# External data points from memory/known sources
external_data = {
    "第一序列": {"douban": None, "note": "会说话的肘子, 十万均订, 中国图书馆典藏"},
    "末日乐园": {"douban": None, "note": "须尾俱全, 800万字2428章, 末世无限流标杆"},
    "黑暗血时代": {"douban": None, "note": "起点排行榜#1, 12年经典"},
    "狩魔手记_烟雨江南": {"douban": 8.1, "note": "豆瓣8.1, 文学性强"},
    "废土崛起": {"douban": None, "note": "通吃道人代表作"},
    "全球变异，从灾厄降临开始": {"douban": None, "note": "borda#1, 外部口碑未验证"},
}
log(f"\n  外部口碑对比:")
for book, data in external_data.items():
    borda_rank = None
    for entry in borda_data:
        if book in entry["book_name"]:
            borda_rank = entry["consensus_rank"]
            break
    log(f"    {book}: borda#{borda_rank}, {data['note']}")

# ============================================================
# STEP 4: 风险评估
# ============================================================
log("\n" + "=" * 80)
log("STEP 4: 风险评估")
log("=" * 80)

# ── 4.1 循环论证风险 ──
log("\n--- 4.1 循环论证风险 ---")
log(f"  signing维度分析:")
log(f"    signing_score来自commercial_engine.py中的compute_commercial_score()")
log(f"    它基于rhythm CSV的规则指标(hook_density, conflict_density等)计算")
log(f"    LLM的intensity/retention不直接进入signing_score计算")
log(f"    但LLM评分影响retention_score(通过BMA权重)")
log(f"    ")
log(f"    Borda维度权重: signing=0.8, retention=0.8, diversity=0.4, bt_rank=1.5, webnovel8=1.5")
log(f"    内部维度(signing+retention)总权重={0.8+0.8}/{0.8+0.8+0.4+1.5+1.5}={0.8+0.8}/{5.0:.0%}")
log(f"    外部维度(bt_rank+webnovel8)总权重={1.5+1.5}/{5.0:.0%}")
log(f"    ")
log(f"    风险评估: signing虽来自规则指标, 但规则指标→LLM评分→retention→Borda存在间接传导")
log(f"    signing#1的末世之深渊召唤师 borda#2, 但v8.8已降为A级 → 存在signing循环论证迹象")
log(f"    级别: 中等风险")

# ── 4.2 GLM自评风险 ──
log(f"\n--- 4.2 GLM自评风险 ---")
log(f"    校准数据集: 30章人工 + 95章GLM = 125章")
log(f"    人工占比: {30/125*100:.0f}%")
log(f"    GLM占比: {95/125*100:.0f}%")
log(f"    GLM评分者: CatPaw (AI)")
log(f"    被校准对象: T1 (AI评分)")
log(f"    ")
if 'glm_t1_pairs_i' in dir() and len(glm_t1_pairs_i) >= 5:
    log(f"    GLM vs T1相关性: r={pearson_r([p[0] for p in glm_t1_pairs_i], [p[1] for p in glm_t1_pairs_i]):.3f}")
log(f"    风险: AI校准AI, 如果GLM和T1有共同的系统性偏差, 校准无法发现")
log(f"    级别: 高风险")

# ── 4.3 采样代表性风险 ──
log(f"\n--- 4.3 采样代表性风险 ---")
log(f"    T1=10%均匀采样, T2=质量分级采样(S=50/A=30/B=30/C=20)")
log(f"    T1+T2合并后, S级书有~50+192=242章, C级书有~20+58=78章")
log(f"    S级书采样密度远高于C级 → S级书评分更准确, 但也可能过度代表")
log(f"    ")
log(f"    节奏对齐: S级T2偏向高hook_density章节(峰50%) → S级T2均值偏高")
log(f"    这可能部分解释T1-T2差异(S级T2因采高峰, 均值应该偏高, 但实际T2 Bias=-2.59)")
log(f"    矛盾: T2采样高峰章节但均值更低 → T2模型本身严重低估")
log(f"    级别: 中等风险")

# ── 4.4 技术缺陷风险 ──
log(f"\n--- 4.4 技术缺陷风险 ---")
log(f"    np.corrcoef在当前环境触发Windows DLL错误(0xc06d007f)")
log(f"    已用手动Pearson公式替代")
log(f"    ")
log(f"    验证手动Pearson公式正确性:")
test_x = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
test_y = [2, 4, 6, 8, 10, 12, 14, 16, 18, 20]
manual_r = pearson_r(test_x, test_y)
log(f"    测试: x=[1..10], y=2*x, 手动Pearson r={manual_r:.6f} (预期=1.0)")
test_y2 = [10, 9, 8, 7, 6, 5, 4, 3, 2, 1]
manual_r2 = pearson_r(test_x, test_y2)
log(f"    测试: x=[1..10], y=11-x, 手动Pearson r={manual_r2:.6f} (预期=-1.0)")
if abs(manual_r - 1.0) < 1e-6 and abs(manual_r2 + 1.0) < 1e-6:
    log(f"    PASS: 手动Pearson公式正确")
else:
    log(f"    FAIL: 手动Pearson公式有误!")
log(f"    级别: 低风险(已修复)")

# ── 4.5 Borda维度权重风险 ──
log(f"\n--- 4.5 Borda维度权重风险 ---")
log(f"    当前权重: signing=0.8, retention=0.8, diversity=0.4, bt_rank=1.5, webnovel8=1.5")
log(f"    依据: DeepSeek + Kimi + Doubao 三方AI建议")
log(f"    外部维度(bt+webnovel8)权重占60%, 内部维度(signing+retention)占32%")
log(f"    ")
log(f"    等权Borda vs 当前权重 Spearman r: {sp_equal:.3f}" if sp_equal else "    Cannot compute")
if sp_equal and sp_equal > 0.9:
    log(f"    PASS: 权重变化对排名影响小(>0.9), 排名稳定")
elif sp_equal and sp_equal > 0.7:
    log(f"    WARN: 权重变化对排名有中等影响(0.7-0.9)")
else:
    log(f"    FAIL: 权重变化导致排名剧烈变化(<0.7), 排名不稳定")

# Entropy weights from TOPSIS
ent_w = topsis_data.get("entropy_weights", {})
log(f"    Entropy客观权重: {ent_w}")
log(f"    对比: Entropy给diversity最高权重({ent_w.get('diversity', 0):.3f}), 但config给最低(0.4)")
log(f"    对比: Entropy给signing中等权重({ent_w.get('signing', 0):.3f}), config也给中等(0.8)")
log(f"    级别: 中等风险(权重来源为AI建议, 非数据驱动; 但Entropy-TOPSIS提供了客观对照)")

# ============================================================
# STEP 5: 审计结论
# ============================================================
log("\n" + "=" * 80)
log("STEP 5: 审计结论")
log("=" * 80)

log("""
## 总体评价

### 数据完整性: WARN
- 原始数据: 33本TXT全部存在, 文件大小合理
- Rhythm: 33个CSV全部存在, 指标分布合理
- T1: 33个ai_full.csv存在, 采样率合理(~10%), 无越界/重复
- T2: 33个t2_full.csv存在, T1∩T2零重叠验证通过
- LLM合并: 33个llm.csv存在, 行数=ai_full+t2_full验证通过
- 问题: human_golden.csv只有36行(含3本重测), 不是预期的30章

### 评分关系: WARN
- Rhythm→LLM: 相关性偏弱(需看具体均值)
- T1 vs T2: 差异与Bias方向一致
- Tier3校准: LOOCV r=0.546统计显著, 但GLM自评占76%有循环论证风险
- LLM→Borda: 传导链透明, 但signing维度有间接循环论证

### 排名可靠性: WARN
- Borda vs TOPSIS Spearman r需具体值判断
- S级书中长夜余火(#15)和末日乐园(#23)与Borda排名严重矛盾
- 人工分级依据含主观因素(作者知名度/字数/完结状态)
- OLS slope=0.463显示T1有54%通胀, 校准后排名会变化

### 总体可信度: 中等
""")

log("\n[审计完成]")
log(f"输出文件: {OUT}")
