#!/usr/bin/env python3
"""检查Tier1已完成书籍的覆盖率和重复情况 (修复后重新检查)"""
import json, os, glob, sys
sys.stdout.reconfigure(encoding='utf-8')

BATCH_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'processed', '末世', 'scores', 'ai_annotate_batches')
BATCH_DIR = os.path.abspath(BATCH_DIR)

TOTAL_CH = {
    '废土崛起': 1929, '神秘尽头': 292, '限制级末日症候': 2271,
    '末日蟑螂': 2404, '末日拼图游戏': 631, '末世超级商人': 509,
    '狩魔手记_烟雨江南': 568, '我的女友是丧尸': 1361,
    '末世之深渊召唤师': 1560, '全球变异，从灾厄降临开始': 1500,
    '蹉跎': 341, '我 的 末 世 领 地': 880,
}

books = list(TOTAL_CH.keys())

print(f"{'Book':<25} {'Total':>5} {'Unique':>6} {'Dupes':>5} {'Rate':>6} {'Target':>6} {'Gap':>5} {'Status':>6}")
print('-' * 75)

issues = []
for book in books:
    if book == '废土崛起':
        files = sorted(glob.glob(os.path.join(BATCH_DIR, 'scores_new_*.json')))
    else:
        files = sorted(glob.glob(os.path.join(BATCH_DIR, book, 'scores_new_*.json')))

    all_ch = []
    json_errors = []
    for f in files:
        try:
            with open(f, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
                for item in data:
                    all_ch.append(item['ch_num'])
        except json.JSONDecodeError as e:
            json_errors.append(os.path.basename(f))

    unique = set(all_ch)
    dupes = len(all_ch) - len(unique)
    tc = TOTAL_CH[book]
    rate = len(unique) / tc * 100
    target = round(tc * 0.1)
    gap = target - len(unique)

    if rate >= 9.5:
        status = 'OK'
    elif rate >= 7:
        status = 'LOW'
        issues.append(f"  {book}: rate={rate:.1f}% (target 10%), only {len(unique)}/{tc}")
    else:
        status = 'FAIL'
        issues.append(f"  {book}: rate={rate:.1f}% -- CRITICAL! only {len(unique)}/{tc}")

    if dupes > 0:
        issues.append(f"  {book}: {dupes} duplicate ch_num ({len(all_ch)} total, {len(unique)} unique)")

    if json_errors:
        issues.append(f"  {book}: JSON parse error in {len(json_errors)} files: {', '.join(json_errors)}")

    print(f"{book:<25} {tc:>5} {len(unique):>6} {dupes:>5} {rate:>5.1f}% {target:>6} {gap:>+5} {status:>6}")

print()
if issues:
    print("=" * 75)
    print("ISSUES FOUND:")
    for iss in issues:
        print(iss)
else:
    print("All checks passed.")
