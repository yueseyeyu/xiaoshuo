#!/usr/bin/env python3
"""用Python精确统计所有书籍的Tier1进度（避免PowerShell编码问题）"""
import json, os, glob, sys
sys.stdout.reconfigure(encoding='utf-8')

BATCH_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'processed', '末世', 'scores', 'ai_annotate_batches')
BATCH_DIR = os.path.abspath(BATCH_DIR)

# Get all book directories
all_entries = os.listdir(BATCH_DIR)

results = []
total_batches = 0
total_scores = 0

for entry in sorted(all_entries):
    full_path = os.path.join(BATCH_DIR, entry)
    if not os.path.isdir(full_path):
        continue
    if entry == 'single':
        continue
    
    # Count batch files (new_XX.json but not scores_new_XX.json)
    all_new_files = [f for f in os.listdir(full_path) if f.startswith('new_') and f.endswith('.json')]
    batch_files = [f for f in all_new_files if not f.startswith('scores_')]
    score_files = [f for f in os.listdir(full_path) if f.startswith('scores_new_') and f.endswith('.json')]
    
    b_count = len(batch_files)
    s_count = len(score_files)
    pct = round(s_count / b_count * 100, 1) if b_count > 0 else 0
    
    total_batches += b_count
    total_scores += s_count
    
    # Check for missing scores
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
    
    missing = batch_nums - score_nums
    
    status = ''
    if pct == 100:
        status = 'DONE'
    elif pct > 0:
        status = 'WIP'
    else:
        status = 'TODO'
    
    missing_info = f' missing:{len(missing)}' if missing and pct < 100 else ''
    results.append((entry, b_count, s_count, pct, status, missing_info))

# Also check root directory (废土崛起)
root_new_files = [f for f in os.listdir(BATCH_DIR) if f.startswith('new_') and f.endswith('.json') and not f.startswith('scores_')]
root_score_files = [f for f in os.listdir(BATCH_DIR) if f.startswith('scores_new_') and f.endswith('.json')]
root_b = len(root_new_files)
root_s = len(root_score_files)
root_pct = round(root_s / root_b * 100, 1) if root_b > 0 else 0
total_batches += root_b
total_scores += root_s
results.append(('废土崛起(root)', root_b, root_s, root_pct, 'DONE' if root_pct == 100 else 'WIP', ''))

# Sort by pct descending
results.sort(key=lambda x: -x[3])

print(f"{'Book':<25} {'Batch':>5} {'Score':>5} {'Pct':>6} {'Status':>6} {'Missing':>8}")
print('-' * 65)
for name, b, s, p, st, mi in results:
    print(f"{name:<25} {b:>5} {s:>5} {p:>5.1f}% {st:>6}{mi}")

total_pct = round(total_scores / total_batches * 100, 1)
print(f"\n{'TOTAL':<25} {total_batches:>5} {total_scores:>5} {total_pct:>5.1f}%")

# Count completed books
done = [r for r in results if r[3] == 100]
print(f"\n100% completed: {len(done)} books")
for d in done:
    print(f"  {d[0]}")
