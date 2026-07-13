#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全面审计所有S/A级书籍的LLM评分数据质量"""
import io, sys, csv, json, os, re
from pathlib import Path
from collections import Counter
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PROJECT = Path(__file__).parent.parent
SCORES_DIR = PROJECT / "data" / "processed" / "末世" / "scores"
RANKING_CSV = PROJECT / "data" / "reports" / "rankings" / "末世" / "v8.8_final_ranking.csv"

# 从ranking CSV读取分级
book_tiers = {}
with open(RANKING_CSV, 'r', encoding='utf-8-sig') as f:
    for row in csv.DictReader(f):
        book_tiers[row["book_name"]] = row["tier"]

# S/A级书名
sa_books = [b for b, t in book_tiers.items() if t in ('S', 'A')]
sa_books.sort(key=lambda b: (book_tiers[b], b))

print(f"{'='*80}")
print(f"S/A级书籍数据质量审计")
print(f"{'='*80}")
print(f"S级: {len([b for b,t in book_tiers.items() if t=='S'])}本")
print(f"A级: {len([b for b,t in book_tiers.items() if t=='A'])}本")
print(f"总计: {len(sa_books)}本\n")

failed_patterns = ["LLM解析失败", "LLM评分失败", "解析失败", "评分失败", "LLM_FAILED", "PARSE_ERROR"]

all_results = []

for book in sa_books:
    tier = book_tiers[book]
    ai_path = SCORES_DIR / f"{book}_ai_full.csv"
    llm_path = SCORES_DIR / f"{book}_llm.csv"
    t2_path = SCORES_DIR / f"{book}_t2_full.csv"
    
    # 检查_ai_full.csv
    ai_rows = []
    if ai_path.exists():
        with open(ai_path, 'r', encoding='utf-8-sig') as f:
            ai_rows = list(csv.DictReader(f))
    
    ai_failed = []
    for r in ai_rows:
        val = str(r.get("ai_intensity", ""))
        analysis = str(r.get("ai_analysis", ""))
        emotion = str(r.get("ai_emotion", ""))
        if val in ("", "0", "LLM解析失败") or any(p in analysis for p in failed_patterns) or any(p in emotion for p in failed_patterns):
            try:
                ai_failed.append(int(r.get("ch_num", 0)))
            except:
                pass
    
    # 检查_llm.csv
    llm_rows = []
    if llm_path.exists():
        with open(llm_path, 'r', encoding='utf-8-sig') as f:
            llm_rows = list(csv.DictReader(f))
    
    llm_failed = []
    for r in llm_rows:
        val = str(r.get("llm_intensity", ""))
        analysis = str(r.get("llm_analysis", ""))
        emotion = str(r.get("llm_emotion", ""))
        if val in ("", "0", "LLM解析失败") or any(p in analysis for p in failed_patterns) or any(p in emotion for p in failed_patterns):
            try:
                llm_failed.append(int(r.get("ch_num", 0)))
            except:
                pass
    
    # 检查t2
    t2_count = 0
    if t2_path.exists():
        with open(t2_path, 'r', encoding='utf-8-sig') as f:
            t2_count = len(list(csv.DictReader(f)))
    
    status = "✅" if not ai_failed and not llm_failed else "❌"
    
    print(f"{status} [{tier}] {book}")
    print(f"   ai_full: {len(ai_rows)}章, 失败{len(ai_failed)}章")
    print(f"   llm:     {len(llm_rows)}章, 失败{len(llm_failed)}章")
    print(f"   t2_full: {t2_count}章")
    
    if ai_failed:
        print(f"   ⚠️ AI失败章节: {ai_failed[:20]}{'...' if len(ai_failed)>20 else ''}")
    if llm_failed:
        print(f"   ⚠️ LLM失败章节: {llm_failed[:20]}{'...' if len(llm_failed)>20 else ''}")
    
    # ai_intensity分布
    if ai_rows:
        intensities = [r.get("ai_intensity", "") for r in ai_rows]
        dist = Counter(intensities)
        print(f"   intensity分布: {dict(sorted(dist.items()))}")
    
    all_results.append({
        "book": book,
        "tier": tier,
        "ai_total": len(ai_rows),
        "ai_failed": len(ai_failed),
        "ai_failed_chs": ai_failed,
        "llm_total": len(llm_rows),
        "llm_failed": len(llm_failed),
        "llm_failed_chs": llm_failed,
        "t2_count": t2_count,
    })
    print()

# 汇总
print(f"\n{'='*80}")
print(f"汇总")
print(f"{'='*80}")
total_ai_failed = sum(r["ai_failed"] for r in all_results)
total_llm_failed = sum(r["llm_failed"] for r in all_results)
print(f"AI失败章节总数: {total_ai_failed}")
print(f"LLM失败章节总数: {total_llm_failed}")

if total_ai_failed > 0 or total_llm_failed > 0:
    print(f"\n⚠️ 需要修复的书籍:")
    for r in all_results:
        if r["ai_failed"] > 0 or r["llm_failed"] > 0:
            print(f"  [{r['tier']}] {r['book']}: AI失败{r['ai_failed']}章, LLM失败{r['llm_failed']}章")
            if r["ai_failed_chs"]:
                print(f"         AI失败章节: {r['ai_failed_chs'][:30]}")
else:
    print("\n🎉 所有S/A级书籍数据质量全部达标！")

# 保存审计结果
audit_path = PROJECT / "data" / "reports" / "末世" / "sa_quality_audit.json"
audit_path.parent.mkdir(parents=True, exist_ok=True)
with open(audit_path, 'w', encoding='utf-8') as f:
    json.dump(all_results, f, ensure_ascii=False, indent=2)
print(f"\n审计结果已保存: {audit_path}")
