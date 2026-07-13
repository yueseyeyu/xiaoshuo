#!/usr/bin/env python3
"""检查Tier1已完成书籍的覆盖率和重复情况"""
import json, os, glob

BATCH_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'processed', '末世', 'scores', 'ai_annotate_batches')

# 总章节数 (from rhythm CSV)
TOTAL_CH = {
    '废土崛起': 1929, '神秘尽头': 292, '限制级末日症候': 2271,
    '末日蟑螂': 2404, '末日拼图游戏': 631, '末世超级商人': 509,
    '狩魔手记_烟雨江南': 568, '我的女友是丧尸': 1361,
    '末世之深渊召唤师': 1560, '全球变异，从灾厄降临开始': 1500,
    '蹉跎': 341, '我 的 末 世 领 地': 880,
}

books = list(TOTAL_CH.keys())

print(f"{'书名':<22} {'总章':>5} {'唯一ch':>6} {'重复':>4} {'采样率':>7} {'10%目标':>6} {'差距':>5} {'状态':>6}")
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
        issues.append(f"  {book}: 采样率 {rate:.1f}% (目标10%), 仅 {len(unique)}/{tc} 章")
    else:
        status = 'FAIL'
        issues.append(f"  {book}: 采样率 {rate:.1f}% — 严重不足! 仅 {len(unique)}/{tc} 章")

    if dupes > 0:
        issues.append(f"  {book}: {dupes} 个重复ch_num (总计{len(all_ch)}条, 唯一{len(unique)}条)")

    if json_errors:
        issues.append(f"  {book}: JSON解析失败 {len(json_errors)} 个文件: {', '.join(json_errors)}")

    print(f"{book:<22} {tc:>5} {len(unique):>6} {dupes:>4} {rate:>6.1f}% {target:>6} {gap:>+5} {status:>6}")

print()
if issues:
    print("=" * 75)
    print("发现问题:")
    for iss in issues:
        print(iss)
else:
    print("全部检查通过，无问题。")
