#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""merge_tier2_and_update.py — 合并Tier2评分 + 更新_llm.csv + 重跑Borda

流程:
1. 合并Tier2 batch scores → _t2_full.csv (每本书)
2. 合并Tier1 _ai_full.csv + Tier2 _t2_full.csv → _llm.csv (Tier2补充)
3. 重跑 commercial_engine + borda_ranker
"""
import csv, json, sys, os, re
from pathlib import Path
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent.parent
TIER2_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "scores" / "tier2_batches"
SCORES_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "scores"
INDEX_PATH = PROJECT_ROOT / "data" / "raw" / "novel_index.json"

with open(INDEX_PATH, 'r', encoding='utf-8') as f:
    idx = json.load(f)

ALL_BOOKS = []
for n in idx.get('genres', {}).get('末世', {}).get('novels', []):
    fname = n['file']
    short = fname.replace('.txt', '')
    if short.startswith('《'):
        m = re.search(r'《(.+?)》', short)
        short = m.group(1) if m else short
    ALL_BOOKS.append(short)

T2_FIELDS = ["ch_num", "stratum", "wc", "t2_intensity", "t2_conflict", "t2_emotion", "t2_pace", "t2_hook", "t2_retention", "t2_analysis"]
# v8.9修复: 补回llm_emotion和llm_analysis字段
LLM_FIELDS = ["ch_num", "llm_intensity", "llm_retention", "llm_hook", "llm_pace", "llm_conflict", "llm_emotion", "llm_analysis"]

# ============================================================
# Step 1: 合并 Tier2 batch scores → _t2_full.csv
# ============================================================
print("=" * 80)
print("Step 1: 合并 Tier2 batch scores → _t2_full.csv")
print("=" * 80)

t2_success = 0
t2_total_chapters = 0

for book in sorted(ALL_BOOKS):
    bdir = TIER2_DIR / book
    if not bdir.exists():
        print(f"  ⬜ {book}: 无Tier2目录")
        continue

    scores = {}
    for sf in sorted(bdir.glob("scores_new_*.json")):
        with open(sf, 'r', encoding='utf-8') as f:
            for row in json.load(f):
                ch_num = int(row["ch_num"])
                if ch_num not in scores:
                    scores[ch_num] = row

    if not scores:
        print(f"  ⬜ {book}: 无Tier2评分")
        continue

    out_csv = SCORES_DIR / f"{book}_t2_full.csv"
    with open(out_csv, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=T2_FIELDS)
        writer.writeheader()
        for ch_num in sorted(scores.keys()):
            row = scores[ch_num]
            writer.writerow({k: row.get(k, "") for k in T2_FIELDS})

    t2_success += 1
    t2_total_chapters += len(scores)
    print(f"  ✅ {book}: {len(scores)}章 → {out_csv.name}")

print(f"\nTier2合并: {t2_success}本, {t2_total_chapters}章")

# ============================================================
# Step 2: 合并 Tier1 + Tier2 → _llm.csv
# ============================================================
print(f"\n{'=' * 80}")
print("Step 2: 合并 Tier1 _ai_full.csv + Tier2 _t2_full.csv → _llm.csv")
print("=" * 80)

llm_success = 0
llm_total_rows = 0

for book in sorted(ALL_BOOKS):
    ai_csv = SCORES_DIR / f"{book}_ai_full.csv"
    t2_csv = SCORES_DIR / f"{book}_t2_full.csv"
    llm_csv = SCORES_DIR / f"{book}_llm.csv"

    # 加载Tier1
    t1_data = {}
    if ai_csv.exists():
        with open(ai_csv, 'r', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                ch_num = int(row["ch_num"])
                t1_data[ch_num] = row

    # 加载Tier2
    t2_data = {}
    if t2_csv.exists():
        with open(t2_csv, 'r', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                ch_num = int(row["ch_num"])
                t2_data[ch_num] = row

    # 合并: Tier1为主, Tier2补充(无重叠)
    merged = {}
    for ch_num, row in t1_data.items():
        merged[ch_num] = {
            "ch_num": ch_num,
            "llm_intensity": row.get("ai_intensity", ""),
            "llm_retention": row.get("ai_retention", ""),
            "llm_hook": row.get("ai_hook", ""),
            "llm_pace": row.get("ai_pace", ""),
            "llm_conflict": row.get("ai_conflict", ""),
            "llm_emotion": row.get("ai_emotion", ""),
            "llm_analysis": row.get("ai_analysis", ""),
        }
    
    t2_added = 0
    for ch_num, row in t2_data.items():
        if ch_num not in merged:
            merged[ch_num] = {
                "ch_num": ch_num,
                "llm_intensity": row.get("t2_intensity", ""),
                "llm_retention": row.get("t2_retention", ""),
                "llm_hook": row.get("t2_hook", ""),
                "llm_pace": row.get("t2_pace", ""),
                "llm_conflict": row.get("t2_conflict", ""),
                "llm_emotion": row.get("t2_emotion", ""),
                "llm_analysis": row.get("t2_analysis", ""),
            }
            t2_added += 1
        else:
            # 有重叠时: Tier2覆盖Tier1 (Tier2更精准)
            merged[ch_num] = {
                "ch_num": ch_num,
                "llm_intensity": row.get("t2_intensity", merged[ch_num]["llm_intensity"]),
                "llm_retention": row.get("t2_retention", merged[ch_num]["llm_retention"]),
                "llm_hook": row.get("t2_hook", merged[ch_num]["llm_hook"]),
                "llm_pace": row.get("t2_pace", merged[ch_num]["llm_pace"]),
                "llm_conflict": row.get("t2_conflict", merged[ch_num]["llm_conflict"]),
                "llm_emotion": row.get("t2_emotion", merged[ch_num].get("llm_emotion", "")),
                "llm_analysis": row.get("t2_analysis", merged[ch_num].get("llm_analysis", "")),
            }

    if not merged:
        print(f"  ⬜ {book}: 无数据")
        continue

    with open(llm_csv, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=LLM_FIELDS)
        writer.writeheader()
        for ch_num in sorted(merged.keys()):
            writer.writerow(merged[ch_num])

    llm_success += 1
    llm_total_rows += len(merged)
    print(f"  ✅ {book}: T1={len(t1_data)} + T2={len(t2_data)}(新增{t2_added}) → {len(merged)}章 → {llm_csv.name}")

print(f"\nLLM合并: {llm_success}本, {llm_total_rows}章")

# ============================================================
# Step 3: 重跑 Borda 排名
# ============================================================
print(f"\n{'=' * 80}")
print("Step 3: 重跑 commercial_engine + borda_ranker")
print("=" * 80)

sys.path.insert(0, str(PROJECT_ROOT / "src"))
from xiaoshuo.pipeline.scoring.commercial_engine import compute_commercial_score, _load_all_llm_scores, _find_book_stem
from xiaoshuo.pipeline.scoring.borda_ranker import rank_books

# 加载所有rhythm CSV
RHYTHM_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "rhythm"

# 清除缓存
if hasattr(_load_all_llm_scores, "_cache"):
    delattr(_load_all_llm_scores, "_cache")

llm_ch = _load_all_llm_scores()
print(f"LLM评分已加载: {len(llm_ch)}条 (T1+T2合并)")

# 为每本书计算商业评分
book_scores = []
for book in sorted(ALL_BOOKS):
    # 找rhythm csv
    rhythm_csv_name = None
    for n in idx.get('genres', {}).get('末世', {}).get('novels', []):
        fname = n['file']
        short = fname.replace('.txt', '')
        if short.startswith('《'):
            m = re.search(r'《(.+?)》', short)
            short = m.group(1) if m else short
        if short == book:
            rhythm_csv_name = n.get('rhythm_csv', '')
            break
    
    if not rhythm_csv_name:
        print(f"  ⬜ {book}: 无rhythm_csv")
        continue
    
    rhythm_path = RHYTHM_DIR / rhythm_csv_name
    if not rhythm_path.exists():
        print(f"  ⬜ {book}: rhythm文件不存在")
        continue
    
    with open(rhythm_path, 'r', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    
    if not rows:
        print(f"  ⬜ {book}: rhythm数据为空")
        continue
    
    # 找book_stem
    book_stem = _find_book_stem(rows, llm_ch)
    
    # 计算商业评分
    try:
        result = compute_commercial_score(rows, "末世", book_name=book)
        book_scores.append({
            "book": book,
            "commercial": result,
        })
        # 统计LLM覆盖
        t1_count = len([k for k in llm_ch if k[0] == book and k[1] in [int(r["ch_num"]) for r in rows]])
        print(f"  ✅ {book}: commercial={result:.1f}, LLM覆盖={t1_count}章")
    except Exception as e:
        print(f"  ❌ {book}: {e}")

print(f"\n商业评分完成: {len(book_scores)}本")

# Borda排名
if book_scores:
    print(f"\n{'=' * 80}")
    print("Borda排名")
    print("=" * 80)
    
    ranking = rank_books(book_scores)
    
    # 保存结果
    borda_json = PROJECT_ROOT / "data" / "reports" / "末世" / "synthesis" / "末世_borda_ranking.json"
    borda_json.parent.mkdir(parents=True, exist_ok=True)
    
    with open(borda_json, 'w', encoding='utf-8') as f:
        json.dump(ranking, f, ensure_ascii=False, indent=2)
    
    print("\n排名结果:")
    for i, item in enumerate(ranking, 1):
        print(f"  #{i:2d} {item['book']:<30s} borda={item.get('borda_score', 0):.1f}")
    
    print(f"\n保存: {borda_json}")

    # CSV
    borda_csv = PROJECT_ROOT / "data" / "reports" / "rankings" / "末世" / "v8.8_borda_ranking_33_t2.csv"
    borda_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(borda_csv, 'w', encoding='utf-8-sig', newline='') as f:
        if ranking:
            writer = csv.DictWriter(f, fieldnames=ranking[0].keys())
            writer.writeheader()
            writer.writerows(ranking)
    print(f"保存: {borda_csv}")

print(f"\n{'=' * 80}")
print("全部完成!")
