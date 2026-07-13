#!/usr/bin/env python3
"""Check AI annotation status for handoff document."""
import json
import os

BATCHES_DIR = r"d:\Code\xiaoshuo\data\processed\末世\scores\ai_annotate_batches"

# Check all batch files
new_batches = sorted([f for f in os.listdir(BATCHES_DIR) if f.startswith("new_") and f.endswith(".json")])
rerun_batches = sorted([f for f in os.listdir(BATCHES_DIR) if f.startswith("rerun_") and f.endswith(".json")])
score_files = sorted([f for f in os.listdir(BATCHES_DIR) if f.startswith("scores_") and f.endswith(".json")])

print("=" * 60)
print("AI标注进度总览")
print("=" * 60)

# New chapters
print("\n--- 新章节批次 (new_*.json) ---")
total_new_ch = 0
scored_new_ch = 0
missing_new = []
for bf in new_batches:
    batch_path = os.path.join(BATCHES_DIR, bf)
    score_name = "scores_" + bf  # e.g., new_00.json -> scores_new_00.json
    score_path = os.path.join(BATCHES_DIR, score_name)
    
    with open(batch_path, encoding="utf-8") as f:
        chapters = json.load(f)
    ch_count = len(chapters)
    total_new_ch += ch_count
    
    if os.path.exists(score_path):
        with open(score_path, encoding="utf-8") as f:
            scored = json.load(f)
        scored_new_ch += len(scored)
        print(f"  {bf}: {ch_count} chapters -> {score_name} ({len(scored)} scored) [OK]")
    else:
        missing_new.append(bf)
        print(f"  {bf}: {ch_count} chapters -> MISSING SCORES [MISSING]")

print(f"\n  New batches: {len(new_batches)}, Total chapters: {total_new_ch}")
print(f"  Scored: {scored_new_ch}, Missing: {total_new_ch - scored_new_ch}")
print(f"  Missing batches: {missing_new}")

# Rerun chapters
print("\n--- 重跑批次 (rerun_*.json) ---")
total_rerun_ch = 0
scored_rerun_ch = 0
missing_rerun = []
for bf in rerun_batches:
    batch_path = os.path.join(BATCHES_DIR, bf)
    score_name = "scores_" + bf
    score_path = os.path.join(BATCHES_DIR, score_name)
    
    with open(batch_path, encoding="utf-8") as f:
        chapters = json.load(f)
    ch_count = len(chapters)
    total_rerun_ch += ch_count
    
    if os.path.exists(score_path):
        with open(score_path, encoding="utf-8") as f:
            scored = json.load(f)
        scored_rerun_ch += len(scored)
        print(f"  {bf}: {ch_count} chapters -> {score_name} ({len(scored)} scored) [OK]")
    else:
        missing_rerun.append(bf)
        print(f"  {bf}: {ch_count} chapters -> MISSING SCORES [MISSING]")

print(f"\n  Rerun batches: {len(rerun_batches)}, Total chapters: {total_rerun_ch}")
print(f"  Scored: {scored_rerun_ch}, Missing: {total_rerun_ch - scored_rerun_ch}")
print(f"  Missing batches: {missing_rerun}")

# Summary
print("\n" + "=" * 60)
print("总结")
print("=" * 60)
total_ch = total_new_ch + total_rerun_ch
total_scored = scored_new_ch + scored_rerun_ch
print(f"  总章节: {total_ch}")
print(f"  已评分: {total_scored}")
print(f"  待评分: {total_ch - total_scored}")
print(f"  进度: {total_scored}/{total_ch} ({total_scored/total_ch*100:.1f}%)")
print(f"  缺失评分批次: {missing_new + missing_rerun}")

# Check pilot CSV
pilot_csv = os.path.join(BATCHES_DIR, "..", "废土崛起_ai.csv")
if os.path.exists(pilot_csv):
    import csv
    with open(pilot_csv, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        pilot_count = sum(1 for _ in reader)
    print(f"\n  Pilot CSV (截断版): 废土崛起_ai.csv = {pilot_count} chapters")

# Check golden set
golden_csv = os.path.join(BATCHES_DIR, "..", "human_golden.csv")
if os.path.exists(golden_csv):
    import csv
    with open(golden_csv, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        golden_count = sum(1 for _ in reader)
    print(f"  Golden Set: human_golden.csv = {golden_count} chapters")

# Show a sample score format
if score_files:
    sample_path = os.path.join(BATCHES_DIR, score_files[0])
    with open(sample_path, encoding="utf-8") as f:
        sample = json.load(f)
    if sample:
        print(f"\n--- 评分文件格式示例 ({score_files[0]}) ---")
        print(json.dumps(sample[0], ensure_ascii=False, indent=2))
