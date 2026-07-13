#!/usr/bin/env python3
"""调查 我 的 末 世 领 地 的章节覆盖问题"""
import json, os, glob, sys
sys.stdout.reconfigure(encoding='utf-8')

BATCH_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'processed', '末世', 'scores', 'ai_annotate_batches')
book_dir = os.path.join(BATCH_DIR, '我 的 末 世 领 地')

files = sorted(glob.glob(os.path.join(book_dir, 'scores_new_*.json')))
print(f"Total score files: {len(files)}")

total_entries = 0
all_ch = []
for f in files:
    try:
        with open(f, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
            n = len(data)
            total_entries += n
            for item in data:
                all_ch.append(item['ch_num'])
            if n != 2:
                print(f"  {os.path.basename(f)}: {n} entries (expected 2)")
    except Exception as e:
        print(f"  {os.path.basename(f)}: ERROR - {e}")

unique = set(all_ch)
print(f"\nTotal entries: {total_entries}")
print(f"Unique ch_num: {len(unique)}")
print(f"Dupes: {total_entries - len(unique)}")
print(f"Ch range: {min(all_ch)}-{max(all_ch)}")
print(f"Total chapters in book: 880")
print(f"Coverage: {len(unique)/880*100:.1f}%")

# Also check batch input files
batch_files = sorted(glob.glob(os.path.join(book_dir, 'new_*.json')))
batch_files = [f for f in batch_files if 'scores_' not in os.path.basename(f)]
print(f"\nBatch input files: {len(batch_files)}")
batch_ch = []
for f in batch_files:
    with open(f, 'r', encoding='utf-8') as fh:
        data = json.load(fh)
        for item in data:
            batch_ch.append(item['ch_num'])
batch_unique = set(batch_ch)
print(f"Batch total entries: {len(batch_ch)}")
print(f"Batch unique ch_num: {len(batch_unique)}")
print(f"Batch ch range: {min(batch_ch)}-{max(batch_ch)}")
print(f"Batch coverage: {len(batch_unique)/880*100:.1f}%")
