#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Tier3分歧分析: 找出Tier1 vs Tier2评分差异最大的章节

策略:
1. 对每本书, 找到T1和T2重叠的章节
2. 比较 intensity(数值差), retention(数值差), hook(级别跳变), pace(级别跳变)
3. 分歧阈值: intensity_diff>=3 或 retention_diff>=3 或 hook跳变(如weak→strong)
4. 按分歧程度排序, 优先S/A级
5. 每本书取top-N分歧章节作为Tier3校准目标
"""
import io, sys, csv, json, os, re
from pathlib import Path
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PROJECT = Path(__file__).parent.parent
SCORES_DIR = PROJECT / "data" / "processed" / "末世" / "scores"
INDEX_PATH = PROJECT / "data" / "raw" / "novel_index.json"
RANKING_CSV = PROJECT / "data" / "reports" / "rankings" / "末世" / "v8.8_final_ranking.csv"

# 加载分级
book_tiers = {}
with open(RANKING_CSV, 'r', encoding='utf-8-sig') as f:
    for row in csv.DictReader(f):
        book_tiers[row["book_name"]] = row["tier"]

# 加载书名列表
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

# hook级别映射
HOOK_LEVEL = {"weak": 0, "medium": 1, "strong": 2}
PACE_LEVEL = {"slow": 0, "medium": 1, "fast": 2}
CONFLICT_LEVEL = {"low": 0, "medium": 1, "high": 2}

def safe_int(val):
    try:
        return int(val)
    except:
        return None

def level_diff(a, b, mapping):
    va = mapping.get(str(a).strip().lower(), 0)
    vb = mapping.get(str(b).strip().lower(), 0)
    return abs(va - vb)

def analyze_book(book_name):
    """分析单本书的T1 vs T2分歧"""
    ai_path = SCORES_DIR / f"{book_name}_ai_full.csv"
    t2_path = SCORES_DIR / f"{book_name}_t2_full.csv"
    
    if not ai_path.exists() or not t2_path.exists():
        return []
    
    # 加载T1
    t1_data = {}
    with open(ai_path, 'r', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            ch = safe_int(row.get("ch_num"))
            if ch is not None:
                t1_data[ch] = row
    
    # 加载T2
    t2_data = {}
    with open(t2_path, 'r', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            ch = safe_int(row.get("ch_num"))
            if ch is not None:
                t2_data[ch] = row
    
    # 找重叠章节
    overlap = set(t1_data.keys()) & set(t2_data.keys())
    if not overlap:
        return []
    
    disagreements = []
    for ch in overlap:
        t1 = t1_data[ch]
        t2 = t2_data[ch]
        
        t1_int = safe_int(t1.get("ai_intensity"))
        t2_int = safe_int(t2.get("t2_intensity"))
        t1_ret = safe_int(t1.get("ai_retention"))
        t2_ret = safe_int(t2.get("t2_retention"))
        
        int_diff = abs(t1_int - t2_int) if t1_int is not None and t2_int is not None else 0
        ret_diff = abs(t1_ret - t2_ret) if t1_ret is not None and t2_ret is not None else 0
        hook_d = level_diff(t1.get("ai_hook"), t2.get("t2_hook"), HOOK_LEVEL)
        pace_d = level_diff(t1.get("ai_pace"), t2.get("t2_pace"), PACE_LEVEL)
        conflict_d = level_diff(t1.get("ai_conflict"), t2.get("t2_conflict"), CONFLICT_LEVEL)
        
        # 分歧分数: 数值差权重高, 级别跳变权重中
        disagreement_score = int_diff * 2 + ret_diff * 2 + hook_d * 3 + pace_d * 1 + conflict_d * 1
        
        # 标记是否为高分歧
        is_high = (int_diff >= 3 or ret_diff >= 3 or hook_d >= 2 or 
                   (int_diff >= 2 and ret_diff >= 2))
        
        if disagreement_score > 0:
            disagreements.append({
                "ch_num": ch,
                "t1_intensity": t1_int,
                "t2_intensity": t2_int,
                "int_diff": int_diff,
                "t1_retention": t1_ret,
                "t2_retention": t2_ret,
                "ret_diff": ret_diff,
                "hook_diff": hook_d,
                "pace_diff": pace_d,
                "conflict_diff": conflict_d,
                "disagreement_score": disagreement_score,
                "is_high": is_high,
                "t1_analysis": t1.get("ai_analysis", "")[:60],
                "t2_analysis": t2.get("t2_analysis", "")[:60],
            })
    
    # 按分歧分数降序
    disagreements.sort(key=lambda x: x["disagreement_score"], reverse=True)
    return disagreements


# 分析所有书籍
print(f"{'='*80}")
print(f"Tier3分歧分析: Tier1 vs Tier2")
print(f"{'='*80}")

all_disagreements = {}
sa_high_count = 0
sa_total_disagree = 0

for book in sorted(ALL_BOOKS):
    tier = book_tiers.get(book, "?")
    dis = analyze_book(book)
    if not dis:
        continue
    
    high_dis = [d for d in dis if d["is_high"]]
    all_disagreements[book] = dis
    
    if tier in ("S", "A"):
        sa_high_count += len(high_dis)
        sa_total_disagree += len(dis)
    
    # 打印前5个分歧最大的
    top5 = dis[:5]
    print(f"\n[{tier}] {book}: {len(dis)}个分歧章节, 其中高分歧{len(high_dis)}个")
    for d in top5:
        flag = "⚠️" if d["is_high"] else "  "
        print(f"  {flag} ch{d['ch_num']:>4d}: I={d['t1_intensity']}↔{d['t2_intensity']}(Δ{d['int_diff']}) "
              f"R={d['t1_retention']}↔{d['t2_retention']}(Δ{d['ret_diff']}) "
              f"hookΔ={d['hook_diff']} score={d['disagreement_score']}")

# 汇总
print(f"\n{'='*80}")
print(f"汇总")
print(f"{'='*80}")

# 按级别统计
for tier in ["S", "A", "B+", "B", "B-", "C"]:
    books_in_tier = [b for b, t in book_tiers.items() if t == tier]
    total_dis = sum(len(all_disagreements.get(b, [])) for b in books_in_tier)
    high_dis = sum(1 for b in books_in_tier for d in all_disagreements.get(b, []) if d["is_high"])
    print(f"  [{tier}] {len(books_in_tier)}本: {total_dis}分歧章节, 高分歧{high_dis}个")

print(f"\nS/A级高分歧章节总数: {sa_high_count}")

# 为每本书选择Tier3校准目标章节
# 策略: S级取top-15, A级取top-12, B+取top-8, B取top-5, 其余top-3
tier_limits = {"S": 15, "A": 12, "B+": 8, "B": 5, "B-": 3, "C": 3}

tier3_targets = {}
for book, dis in all_disagreements.items():
    tier = book_tiers.get(book, "?")
    limit = tier_limits.get(tier, 3)
    # 优先高分歧, 然后按分数
    targets = [d for d in dis if d["is_high"]][:limit]
    if len(targets) < limit:
        # 补充非高分歧
        remaining = [d for d in dis if not d["is_high"]]
        targets.extend(remaining[:limit - len(targets)])
    tier3_targets[book] = [d["ch_num"] for d in targets]

# 统计
total_targets = sum(len(v) for v in tier3_targets.values())
sa_targets = sum(len(v) for b, v in tier3_targets.items() if book_tiers.get(b) in ("S", "A"))

print(f"\nTier3校准目标章节:")
print(f"  总计: {total_targets}章")
print(f"  S/A级: {sa_targets}章")

# 保存
output = {
    "summary": {
        "total_disagreement_chapters": sum(len(v) for v in all_disagreements.values()),
        "sa_high_disagreements": sa_high_count,
        "tier3_target_chapters": total_targets,
        "sa_target_chapters": sa_targets,
    },
    "tier3_targets": {book: chs for book, chs in tier3_targets.items()},
    "disagreements": {
        book: [{"ch_num": d["ch_num"], "int_diff": d["int_diff"], "ret_diff": d["ret_diff"],
                "hook_diff": d["hook_diff"], "score": d["disagreement_score"], "is_high": d["is_high"],
                "t1": {"i": d["t1_intensity"], "r": d["t1_retention"], "analysis": d["t1_analysis"]},
                "t2": {"i": d["t2_intensity"], "r": d["t2_retention"], "analysis": d["t2_analysis"]},
               } for d in dis[:20]]
        for book, dis in all_disagreements.items()
    },
}

out_path = PROJECT / "data" / "golden" / "末世" / "tier3" / "tier3_disagreement_analysis.json"
out_path.parent.mkdir(parents=True, exist_ok=True)
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
print(f"\n已保存: {out_path}")
