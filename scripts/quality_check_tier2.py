#!/usr/bin/env python3
"""
quality_check_tier2.py - Tier2 评分质检脚本
检查 scores_new_XX.json 是否合法、字段是否一致、评分值是否在范围内。
用法: python scripts/quality_check_tier2.py
"""
import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
TIER2_DIR = BASE_DIR / "data" / "processed" / "末世" / "scores" / "tier2_batches"

VALID_EMOTIONS = {"日常", "紧张", "爽快", "悬疑", "压抑", "感动", "热血", "悲壮", "温馨"}
VALID_CONFLICTS = {"low", "medium", "high"}
VALID_PACES = {"slow", "medium", "fast"}
VALID_HOOKS = {"weak", "medium", "strong"}

errors = []
checked = 0
book_dirs = []

if TIER2_DIR.exists():
    for d in sorted(TIER2_DIR.iterdir()):
        if d.is_dir():
            book_dirs.append(d)
else:
    print(f"[FAIL] Directory not found: {TIER2_DIR}")
    sys.exit(1)

for book_dir in book_dirs:
    book_name = book_dir.name
    new_files = sorted(book_dir.glob("new_*.json"))
    score_count = 0
    total_chapters = 0
    for new_file in new_files:
        batch_num = new_file.stem.replace("new_", "")
        score_file = book_dir / f"scores_new_{batch_num}.json"
        if not score_file.exists():
            continue
        score_count += 1
        try:
            with open(new_file, "r", encoding="utf-8") as f:
                new_data = json.load(f)
            with open(score_file, "r", encoding="utf-8") as f:
                score_data = json.load(f)
        except json.JSONDecodeError as e:
            errors.append(f"[JSON ERROR] {book_name}/scores_new_{batch_num}.json: {e}")
            continue
        except Exception as e:
            errors.append(f"[READ ERROR] {book_name}/scores_new_{batch_num}.json: {e}")
            continue

        if len(new_data) != len(score_data):
            errors.append(f"[COUNT MISMATCH] {book_name}/batch_{batch_num}: new={len(new_data)} scores={len(score_data)}")
            continue

        for i, (new_ch, score_ch) in enumerate(zip(new_data, score_data)):
            checked += 1
            # Check ch_num
            if new_ch.get("ch_num") != score_ch.get("ch_num"):
                errors.append(f"[CH_NUM MISMATCH] {book_name}/batch_{batch_num} idx={i}: new={new_ch.get('ch_num')} scores={score_ch.get('ch_num')}")
            # Check stratum
            if new_ch.get("stratum") != score_ch.get("stratum"):
                errors.append(f"[STRATUM MISMATCH] {book_name}/batch_{batch_num} idx={i}: new={new_ch.get('stratum')} scores={score_ch.get('stratum')}")
            # Check wc
            if new_ch.get("wc") != score_ch.get("wc"):
                errors.append(f"[WC MISMATCH] {book_name}/batch_{batch_num} idx={i}: new={new_ch.get('wc')} scores={score_ch.get('wc')}")
            # Check t2_intensity
            ti = score_ch.get("t2_intensity")
            if not isinstance(ti, int) or ti < 1 or ti > 10:
                errors.append(f"[INTENSITY RANGE] {book_name}/batch_{batch_num} idx={i}: {ti}")
            # Check t2_conflict
            if score_ch.get("t2_conflict") not in VALID_CONFLICTS:
                errors.append(f"[CONFLICT INVALID] {book_name}/batch_{batch_num} idx={i}: {score_ch.get('t2_conflict')}")
            # Check t2_emotion
            if score_ch.get("t2_emotion") not in VALID_EMOTIONS:
                errors.append(f"[EMOTION INVALID] {book_name}/batch_{batch_num} idx={i}: {score_ch.get('t2_emotion')}")
            # Check t2_pace
            if score_ch.get("t2_pace") not in VALID_PACES:
                errors.append(f"[PACE INVALID] {book_name}/batch_{batch_num} idx={i}: {score_ch.get('t2_pace')}")
            # Check t2_hook
            if score_ch.get("t2_hook") not in VALID_HOOKS:
                errors.append(f"[HOOK INVALID] {book_name}/batch_{batch_num} idx={i}: {score_ch.get('t2_hook')}")
            # Check t2_retention
            tr = score_ch.get("t2_retention")
            if not isinstance(tr, int) or tr < 1 or tr > 10:
                errors.append(f"[RETENTION RANGE] {book_name}/batch_{batch_num} idx={i}: {tr}")
            # Check t2_analysis
            ta = score_ch.get("t2_analysis", "")
            if not isinstance(ta, str) or len(ta.strip()) < 20 or len(ta.strip()) > 100:
                errors.append(f"[ANALYSIS LEN] {book_name}/batch_{batch_num} idx={i}: len={len(ta) if isinstance(ta, str) else 0}")
            # Check no text field
            if "text" in score_ch:
                errors.append(f"[TEXT FIELD] {book_name}/batch_{batch_num} idx={i}: should not contain text field")

# Print summary
print(f"\n{'='*60}")
print(f"Tier2 Quality Check Report")
print(f"{'='*60}")

# Per-book status
for book_dir in book_dirs:
    book_name = book_dir.name
    new_files = sorted(book_dir.glob("new_*.json"))
    total = len(new_files)
    score_files = sum(1 for f in new_files if (book_dir / f"scores_new_{f.stem.replace('new_', '')}.json").exists())
    total_ch = 0
    for nf in new_files:
        sf = book_dir / f"scores_new_{nf.stem.replace('new_', '')}.json"
        if sf.exists():
            try:
                with open(sf, 'r', encoding='utf-8') as f:
                    total_ch += len(json.load(f))
            except:
                pass
    status = "[OK]" if score_files == total else "[!!]"
    print(f"  {status} {book_name:30s} {score_count}/{total} batches, {total_ch} chapters, {100.0*score_files/max(total,1):.1f}%")

print(f"\n{'='*60}")
print(f"Total checked: {checked} chapters")
print(f"Errors: {len(errors)}")
if errors:
    print(f"\n--- Errors (first 20) ---")
    for e in errors[:20]:
        print(f"  {e}")
    if len(errors) > 20:
        print(f"  ... and {len(errors)-20} more")
    print(f"\n[FAIL] {len(errors)} errors found.")
    sys.exit(1)
else:
    print(f"\n[OK] All checks passed.")
    sys.exit(0)
