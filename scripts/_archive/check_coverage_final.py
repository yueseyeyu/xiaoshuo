#!/usr/bin/env python3
"""全面检查15本已完成书籍的覆盖率、重复和JSON问题"""
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
    '恐慌沸腾': 1488, '末世魔神游戏': 1980, '末日乐园': 2435,
    '重卡战车在末世': 914,
}

books = list(TOTAL_CH.keys())

print(f"{'Book':<25} {'Total':>5} {'Uniq':>5} {'Dup':>4} {'Rate':>6} {'Tgt':>4} {'Gap':>5} {'JSON':>4} {'Status':>6}")
print('-' * 80)

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
        except json.JSONDecodeError:
            json_errors.append(os.path.basename(f))
        except Exception as e:
            json_errors.append(f"{os.path.basename(f)}({type(e).__name__})")

    unique = set(all_ch)
    dupes = len(all_ch) - len(unique)
    tc = TOTAL_CH[book]
    rate = len(unique) / tc * 100
    target = round(tc * 0.1)
    gap = target - len(unique)
    jerr = len(json_errors)

    if rate >= 9.5:
        status = 'OK'
    elif rate >= 7:
        status = 'LOW'
        issues.append(f"  [LOW] {book}: rate={rate:.1f}%, {len(unique)}/{tc} ch, gap={gap}")
    else:
        status = 'FAIL'
        issues.append(f"  [FAIL] {book}: rate={rate:.1f}%, {len(unique)}/{tc} ch, gap={gap}")

    if dupes > 0:
        issues.append(f"  [DUP] {book}: {dupes} duplicates ({len(all_ch)} total -> {len(unique)} unique)")

    if json_errors:
        issues.append(f"  [JSON] {book}: {len(json_errors)} parse errors: {', '.join(json_errors[:3])}")

    print(f"{book:<25} {tc:>5} {len(unique):>5} {dupes:>4} {rate:>5.1f}% {target:>4} {gap:>+5} {jerr:>4} {status:>6}")

print()
if issues:
    print("=" * 80)
    print("ISSUES SUMMARY:")
    for iss in issues:
        print(iss)
else:
    print("All checks passed.")
