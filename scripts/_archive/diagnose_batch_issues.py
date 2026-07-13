#!/usr/bin/env python3
"""诊断三本问题书的batch输入文件覆盖情况"""
import json, os, glob, sys
sys.stdout.reconfigure(encoding='utf-8')

BATCH_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'processed', '末世', 'scores', 'ai_annotate_batches')
BATCH_DIR = os.path.abspath(BATCH_DIR)

TOTAL_CH = {
    '狩魔手记_烟雨江南': 568,
    '恐慌沸腾': 1488,
    '我 的 末 世 领 地': 880,
}

for book in TOTAL_CH:
    book_dir = os.path.join(BATCH_DIR, book)
    
    # Batch input files
    batch_files = sorted([f for f in os.listdir(book_dir) if f.startswith('new_') and f.endswith('.json') and not f.startswith('scores_')])
    score_files = sorted([f for f in os.listdir(book_dir) if f.startswith('scores_new_') and f.endswith('.json')])
    
    # Extract ch_num from batch files
    batch_ch = []
    batch_detail = {}
    for f in batch_files:
        fpath = os.path.join(book_dir, f)
        try:
            with open(fpath, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
                chs = [item['ch_num'] for item in data]
                batch_ch.extend(chs)
                batch_detail[f] = chs
        except Exception as e:
            batch_detail[f] = f"ERROR: {e}"
    
    # Extract ch_num from score files
    score_ch = []
    for f in score_files:
        fpath = os.path.join(book_dir, f)
        try:
            with open(fpath, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
                score_ch.extend([item['ch_num'] for item in data])
        except:
            pass
    
    batch_unique = set(batch_ch)
    score_unique = set(score_ch)
    missing_scores = batch_unique - score_unique
    
    tc = TOTAL_CH[book]
    
    print(f"\n{'='*70}")
    print(f"Book: {book} (total={tc}ch, target 10%={round(tc*0.1)})")
    print(f"{'='*70}")
    print(f"Batch files: {len(batch_files)} | Score files: {len(score_files)}")
    print(f"Batch ch_num: {len(batch_ch)} entries, {len(batch_unique)} unique, range {min(batch_ch)}-{max(batch_ch)}")
    print(f"Batch coverage: {len(batch_unique)/tc*100:.1f}%")
    print(f"Score ch_num: {len(score_ch)} entries, {len(score_unique)} unique")
    print(f"Score coverage: {len(score_unique)/tc*100:.1f}%")
    print(f"Missing scores: {len(missing_scores)} batches")
    
    if len(batch_ch) > len(batch_unique):
        # Find duplicates in batch
        from collections import Counter
        counts = Counter(batch_ch)
        dups = {k: v for k, v in counts.items() if v > 1}
        print(f"Batch duplicates: {len(dups)} ch_num appear multiple times")
        if len(dups) <= 10:
            for ch, cnt in sorted(dups.items()):
                print(f"  ch{ch}: appears {cnt} times")
    
    # Check which batch files are missing scores
    batch_nums = set()
    for f in batch_files:
        try:
            num = int(f.replace('new_', '').replace('.json', ''))
            batch_nums.add(num)
        except:
            pass
    score_nums = set()
    for f in score_files:
        try:
            num = int(f.replace('scores_new_', '').replace('.json', ''))
            score_nums.add(num)
        except:
            pass
    missing_batch_nums = sorted(batch_nums - score_nums)
    if missing_batch_nums:
        print(f"Missing batch numbers: {missing_batch_nums}")
    
    # Show first 5 and last 5 batch details
    print(f"\nBatch details (first 5 + last 5):")
    for f in batch_files[:5]:
        print(f"  {f}: ch={batch_detail[f]}")
    print("  ...")
    for f in batch_files[-5:]:
        print(f"  {f}: ch={batch_detail[f]}")
