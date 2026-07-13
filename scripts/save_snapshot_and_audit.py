#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""save_snapshot_and_audit.py — 保存快照 + 全量数据质量审计 + 目录架构检查"""
import sys, os, json, csv, re
from pathlib import Path
from datetime import datetime
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent.parent
TIER1_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "scores" / "ai_annotate_batches"
TIER2_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "scores" / "tier2_batches"
SCORES_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "scores"
RHYTHM_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "rhythm"
INDEX_PATH = PROJECT_ROOT / "data" / "raw" / "novel_index.json"
REPORTS_DIR = PROJECT_ROOT / "data" / "reports" / "末世" / "synthesis"
RANKINGS_DIR = PROJECT_ROOT / "data" / "reports" / "rankings" / "末世"

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

VALID_EMOTIONS = {"日常", "紧张", "爽快", "悬疑", "压抑", "感动", "热血", "悲壮", "温馨"}
VALID_CONFLICT = {"low", "medium", "high"}
VALID_PACE = {"slow", "medium", "fast"}
VALID_HOOK = {"weak", "medium", "strong"}

errors = []
warnings = []
stats = {
    "tier1": {"books": 0, "batches": 0, "chapters": 0, "errors": 0},
    "tier2": {"books": 0, "batches": 0, "chapters": 0, "errors": 0},
    "llm": {"books": 0, "chapters": 0, "errors": 0},
    "rhythm": {"books": 0, "errors": 0},
    "borda": {"books": 0, "errors": 0},
}

# ============================================================
# 1. Tier1 质检
# ============================================================
print("=" * 80)
print("1. Tier1 (ai_annotate_batches) 质检")
print("=" * 80)

for bdir in sorted(TIER1_DIR.iterdir()) if TIER1_DIR.exists() else []:
    if not bdir.is_dir():
        continue
    new_files = sorted(bdir.glob("new_*.json"))
    if not new_files:
        continue
    
    stats["tier1"]["books"] += 1
    stats["tier1"]["batches"] += len(new_files)
    book_scored = 0
    book_chapters = 0
    
    for nf in new_files:
        batch_num = int(nf.stem.split("_")[-1])
        sf = bdir / f"scores_new_{batch_num:02d}.json"
        
        try:
            with open(nf, 'r', encoding='utf-8') as f:
                new_data = json.load(f)
        except:
            errors.append(f"T1/{bdir.name}/{nf.name}: new JSON解析失败")
            continue
        
        book_chapters += len(new_data)
        stats["tier1"]["chapters"] += len(new_data)
        
        if not sf.exists():
            errors.append(f"T1/{bdir.name}/{nf.name}: 缺少scores文件")
            continue
        
        book_scored += 1
        
        try:
            with open(sf, 'r', encoding='utf-8') as f:
                scores = json.load(f)
        except:
            errors.append(f"T1/{bdir.name}/{sf.name}: scores JSON解析失败")
            stats["tier1"]["errors"] += 1
            continue
        
        if len(scores) != len(new_data):
            errors.append(f"T1/{bdir.name}/{sf.name}: 章节数不匹配")
            stats["tier1"]["errors"] += 1
            continue
        
        new_map = {d['ch_num']: d for d in new_data}
        for s in scores:
            ch = s.get('ch_num')
            prefix = f"T1/{bdir.name}/{sf.name} ch{ch}"
            
            if ch not in new_map:
                errors.append(f"{prefix}: ch_num不在new文件")
                stats["tier1"]["errors"] += 1
                continue
            
            n = new_map[ch]
            if s.get('stratum') != n.get('stratum'):
                errors.append(f"{prefix}: stratum不匹配")
                stats["tier1"]["errors"] += 1
            if s.get('wc') != n.get('wc'):
                errors.append(f"{prefix}: wc不匹配")
                stats["tier1"]["errors"] += 1
            
            for field, valid, label in [
                ("ai_intensity", None, "1-10"),
                ("ai_retention", None, "1-10"),
            ]:
                val = s.get(field)
                if not isinstance(val, int) or val < 1 or val > 10:
                    errors.append(f"{prefix}: {field}={val} 不在{label}")
                    stats["tier1"]["errors"] += 1
            
            for field, valid, label in [
                ("ai_conflict", VALID_CONFLICT, "low/medium/high"),
                ("ai_emotion", VALID_EMOTIONS, "9种情绪"),
                ("ai_pace", VALID_PACE, "slow/medium/fast"),
                ("ai_hook", VALID_HOOK, "weak/medium/strong"),
            ]:
                if s.get(field) not in valid:
                    errors.append(f"{prefix}: {field}={s.get(field)} 不在{label}")
                    stats["tier1"]["errors"] += 1
            
            analysis = s.get('ai_analysis', '')
            if not analysis or len(analysis.strip()) < 20:
                errors.append(f"{prefix}: ai_analysis过短")
                stats["tier1"]["errors"] += 1
            elif len(analysis) > 100:
                warnings.append(f"{prefix}: ai_analysis过长({len(analysis)}字)")
    
    coverage = book_scored / len(new_files) * 100 if new_files else 0
    status = "✅" if book_scored == len(new_files) else "❌"
    print(f"  {status} T1 {bdir.name[:26]:<28} {book_scored:>3}/{len(new_files):>3}批  {book_chapters:>4}章  {coverage:.0f}%")

# ============================================================
# 2. Tier2 质检
# ============================================================
print(f"\n{'=' * 80}")
print("2. Tier2 (tier2_batches) 质检")
print("=" * 80)

for bdir in sorted(TIER2_DIR.iterdir()) if TIER2_DIR.exists() else []:
    if not bdir.is_dir():
        continue
    new_files = sorted(bdir.glob("new_*.json"))
    if not new_files:
        continue
    
    stats["tier2"]["books"] += 1
    stats["tier2"]["batches"] += len(new_files)
    book_scored = 0
    book_chapters = 0
    
    for nf in new_files:
        batch_num = int(nf.stem.split("_")[-1])
        sf = bdir / f"scores_new_{batch_num:02d}.json"
        
        try:
            with open(nf, 'r', encoding='utf-8') as f:
                new_data = json.load(f)
        except:
            errors.append(f"T2/{bdir.name}/{nf.name}: new JSON解析失败")
            continue
        
        book_chapters += len(new_data)
        stats["tier2"]["chapters"] += len(new_data)
        
        if not sf.exists():
            errors.append(f"T2/{bdir.name}/{nf.name}: 缺少scores文件")
            continue
        
        book_scored += 1
        
        try:
            with open(sf, 'r', encoding='utf-8') as f:
                scores = json.load(f)
        except:
            errors.append(f"T2/{bdir.name}/{sf.name}: scores JSON解析失败")
            stats["tier2"]["errors"] += 1
            continue
        
        if len(scores) != len(new_data):
            errors.append(f"T2/{bdir.name}/{sf.name}: 章节数不匹配")
            stats["tier2"]["errors"] += 1
            continue
        
        new_map = {d['ch_num']: d for d in new_data}
        for s in scores:
            ch = s.get('ch_num')
            prefix = f"T2/{bdir.name}/{sf.name} ch{ch}"
            
            if ch not in new_map:
                errors.append(f"{prefix}: ch_num不在new文件")
                stats["tier2"]["errors"] += 1
                continue
            
            n = new_map[ch]
            if s.get('stratum') != n.get('stratum'):
                errors.append(f"{prefix}: stratum不匹配")
                stats["tier2"]["errors"] += 1
            if s.get('wc') != n.get('wc'):
                errors.append(f"{prefix}: wc不匹配")
                stats["tier2"]["errors"] += 1
            
            for field, valid, label in [
                ("t2_intensity", None, "1-10"),
                ("t2_retention", None, "1-10"),
            ]:
                val = s.get(field)
                if not isinstance(val, int) or val < 1 or val > 10:
                    errors.append(f"{prefix}: {field}={val} 不在{label}")
                    stats["tier2"]["errors"] += 1
            
            for field, valid, label in [
                ("t2_conflict", VALID_CONFLICT, "low/medium/high"),
                ("t2_emotion", VALID_EMOTIONS, "9种情绪"),
                ("t2_pace", VALID_PACE, "slow/medium/fast"),
                ("t2_hook", VALID_HOOK, "weak/medium/strong"),
            ]:
                if s.get(field) not in valid:
                    errors.append(f"{prefix}: {field}={s.get(field)} 不在{label}")
                    stats["tier2"]["errors"] += 1
            
            analysis = s.get('t2_analysis', '')
            if not analysis or len(analysis.strip()) < 20:
                errors.append(f"{prefix}: t2_analysis过短")
                stats["tier2"]["errors"] += 1
            elif len(analysis) > 100:
                warnings.append(f"{prefix}: t2_analysis过长({len(analysis)}字)")
            
            if 'text' in s:
                errors.append(f"{prefix}: scores不应包含text字段")
                stats["tier2"]["errors"] += 1
    
    coverage = book_scored / len(new_files) * 100 if new_files else 0
    status = "✅" if book_scored == len(new_files) else "❌"
    print(f"  {status} T2 {bdir.name[:26]:<28} {book_scored:>3}/{len(new_files):>3}批  {book_chapters:>4}章  {coverage:.0f}%")

# ============================================================
# 3. _llm.csv 质检
# ============================================================
print(f"\n{'=' * 80}")
print("3. _llm.csv (合并后) 质检")
print("=" * 80)

for book in sorted(ALL_BOOKS):
    llm_csv = SCORES_DIR / f"{book}_llm.csv"
    if not llm_csv.exists():
        errors.append(f"LLM/{book}: _llm.csv不存在")
        continue
    
    stats["llm"]["books"] += 1
    rows = []
    with open(llm_csv, 'r', encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            rows.append(r)
    
    stats["llm"]["chapters"] += len(rows)
    
    for r in rows:
        ch = r.get('ch_num', '')
        prefix = f"LLM/{book} ch{ch}"
        
        try:
            intensity = float(r.get('llm_intensity', 0))
            if intensity < 1 or intensity > 10:
                errors.append(f"{prefix}: llm_intensity={intensity} 不在1-10")
                stats["llm"]["errors"] += 1
        except:
            errors.append(f"{prefix}: llm_intensity非数值")
            stats["llm"]["errors"] += 1
        
        try:
            retention = float(r.get('llm_retention', 0))
            if retention < 1 or retention > 10:
                errors.append(f"{prefix}: llm_retention={retention} 不在1-10")
                stats["llm"]["errors"] += 1
        except:
            errors.append(f"{prefix}: llm_retention非数值")
            stats["llm"]["errors"] += 1
        
        if r.get('llm_hook') not in VALID_HOOK:
            errors.append(f"{prefix}: llm_hook={r.get('llm_hook')} 不合法")
            stats["llm"]["errors"] += 1
        
        if r.get('llm_pace') not in VALID_PACE:
            errors.append(f"{prefix}: llm_pace={r.get('llm_pace')} 不合法")
            stats["llm"]["errors"] += 1
        
        if r.get('llm_conflict') not in VALID_CONFLICT:
            errors.append(f"{prefix}: llm_conflict={r.get('llm_conflict')} 不合法")
            stats["llm"]["errors"] += 1
    
    print(f"  ✅ {book[:28]:<30} {len(rows):>4}章")

# ============================================================
# 4. rhythm CSV 质检
# ============================================================
print(f"\n{'=' * 80}")
print("4. rhythm CSV 质检")
print("=" * 80)

for book in sorted(ALL_BOOKS):
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
        errors.append(f"RHYTHM/{book}: novel_index中无rhythm_csv")
        continue
    
    rhythm_path = RHYTHM_DIR / rhythm_csv_name
    if not rhythm_path.exists():
        errors.append(f"RHYTHM/{book}: rhythm文件不存在 ({rhythm_csv_name})")
        continue
    
    stats["rhythm"]["books"] += 1
    with open(rhythm_path, 'r', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    
    if len(rows) < 10:
        warnings.append(f"RHYTHM/{book}: rhythm行数过少 ({len(rows)}行)")

print(f"  ✅ {stats['rhythm']['books']}本 rhythm CSV 检查完毕")

# ============================================================
# 5. Borda 排名质检
# ============================================================
print(f"\n{'=' * 80}")
print("5. Borda 排名质检")
print("=" * 80)

borda_path = REPORTS_DIR / "末世_borda_ranking.json"
if borda_path.exists():
    with open(borda_path, 'r', encoding='utf-8') as f:
        ranking = json.load(f)
    stats["borda"]["books"] = len(ranking)
    
    if len(ranking) != 33:
        errors.append(f"BORDA: 书数={len(ranking)}, 期望33")
        stats["borda"]["errors"] += 1
    
    for i, item in enumerate(ranking):
        if item.get("consensus_rank") != i + 1:
            errors.append(f"BORDA: rank顺序错误 idx={i}")
            stats["borda"]["errors"] += 1
    
    print(f"  ✅ Borda: {len(ranking)}本, 排名顺序正确")
    
    # 保存快照
    snapshot = {
        "timestamp": datetime.now().isoformat(),
        "description": "T1+T2合并后Borda排名快照",
        "total_books": len(ranking),
        "total_llm_chapters": stats["llm"]["chapters"],
        "tier1_chapters": stats["tier1"]["chapters"],
        "tier2_chapters": stats["tier2"]["chapters"],
        "ranking": ranking,
    }
    snapshot_path = RANKINGS_DIR / "v8.8_borda_snapshot_t1t2.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    with open(snapshot_path, 'w', encoding='utf-8') as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    print(f"  ✅ 快照已保存: {snapshot_path}")
else:
    errors.append("BORDA: 末世_borda_ranking.json不存在")

# ============================================================
# 6. 目录架构检查
# ============================================================
print(f"\n{'=' * 80}")
print("6. 目录架构检查")
print("=" * 80)

dir_checks = [
    (TIER1_DIR, "Tier1批次目录", True),
    (TIER2_DIR, "Tier2批次目录", True),
    (SCORES_DIR, "scores目录", True),
    (RHYTHM_DIR, "rhythm目录", True),
    (REPORTS_DIR, "reports/末世/synthesis", True),
    (RANKINGS_DIR, "rankings/末世", True),
    (PROJECT_ROOT / "data" / "raw" / "novels" / "末世", "raw/novels/末世", True),
    (PROJECT_ROOT / "trae_tier1", "trae_tier1", True),
    (PROJECT_ROOT / "scripts" / "_archive", "scripts/_archive(归档)", True),
    (PROJECT_ROOT / "_archive", "_archive(根目录归档)", True),
]

for path, name, required in dir_checks:
    exists = path.exists()
    status = "✅" if exists else "❌"
    print(f"  {status} {name:<35} {path.relative_to(PROJECT_ROOT)}")

# 检查scripts目录是否有残留过多文件
scripts_count = len(list((PROJECT_ROOT / "scripts").glob("*.py")))
bat_count = len(list((PROJECT_ROOT / "scripts").glob("*.bat")))
json_count = len(list((PROJECT_ROOT / "scripts").glob("*.json")))
print(f"\n  scripts/ 根目录: {scripts_count}个py + {bat_count}个bat + {json_count}个json = {scripts_count+bat_count+json_count}个文件")

# 检查根目录是否有残留
root_files = [f for f in PROJECT_ROOT.iterdir() if f.is_file() and not f.name.startswith('.')]
print(f"  根目录文件: {len(root_files)}个")
for f in sorted(root_files):
    print(f"    {f.name}")

# ============================================================
# 汇总
# ============================================================
print(f"\n{'=' * 80}")
print("全量数据质量审计汇总")
print("=" * 80)

print(f"\n数据统计:")
print(f"  Tier1: {stats['tier1']['books']}本 / {stats['tier1']['batches']}批 / {stats['tier1']['chapters']}章 / {stats['tier1']['errors']}个错误")
print(f"  Tier2: {stats['tier2']['books']}本 / {stats['tier2']['batches']}批 / {stats['tier2']['chapters']}章 / {stats['tier2']['errors']}个错误")
print(f"  LLM合并: {stats['llm']['books']}本 / {stats['llm']['chapters']}章 / {stats['llm']['errors']}个错误")
print(f"  Rhythm: {stats['rhythm']['books']}本 / {stats['rhythm']['errors']}个错误")
print(f"  Borda: {stats['borda']['books']}本 / {stats['borda']['errors']}个错误")

total_errors = len(errors)
total_warnings = len(warnings)
print(f"\n总错误: {total_errors}个")
print(f"总警告: {total_warnings}个")

if errors:
    print(f"\n错误详情 (前30条):")
    for e in errors[:30]:
        print(f"  ❌ {e}")
    if len(errors) > 30:
        print(f"  ... 还有{len(errors)-30}个错误")

if warnings:
    print(f"\n警告详情 (前10条):")
    for w in warnings[:10]:
        print(f"  ⚠️ {w}")

if total_errors == 0:
    print("\n✅ 全量数据质量审计通过，0错误。")
else:
    print(f"\n❌ 有{total_errors}个错误需要修复。")

# 保存审计报告
audit_path = PROJECT_ROOT / "data" / "reports" / "末世" / "full_audit_t1t2.json"
audit_path.parent.mkdir(parents=True, exist_ok=True)
with open(audit_path, 'w', encoding='utf-8') as f:
    json.dump({
        "timestamp": datetime.now().isoformat(),
        "stats": stats,
        "errors": errors,
        "warnings": warnings,
    }, f, ensure_ascii=False, indent=2)
print(f"\n审计报告: {audit_path}")
