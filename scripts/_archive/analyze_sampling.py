#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Analyze golden set data for sampling sufficiency."""
import csv, statistics, math
from collections import defaultdict

rows = []
with open('data/processed/末世/scores/human_golden.csv', 'r', encoding='utf-8-sig') as f:
    for r in csv.DictReader(f):
        if r.get('is_retest', '') == 'true':
            continue
        rows.append(r)

books = defaultdict(list)
for r in rows:
    books[r['book']].append(r)

print('=== Golden Set 统计分析 ===')
print(f'总标注数(非重测): {len(rows)}')
print()

for book, book_rows in books.items():
    human_int = [float(r['human_intensity']) for r in book_rows if r.get('human_intensity', '').strip()]
    llm_int = [float(r['llm_intensity']) for r in book_rows if r.get('llm_intensity', '').strip()]
    rule_int = [float(r['rule_intensity']) for r in book_rows if r.get('rule_intensity', '').strip()]
    glm_int = [float(r['glm_intensity']) for r in book_rows if r.get('glm_intensity', '').strip()]

    n = len(human_int)
    h_mean = statistics.mean(human_int)
    h_std = statistics.stdev(human_int) if n > 1 else 0
    h_ci = 1.96 * h_std / math.sqrt(n) if n > 1 else 0

    l_mean = statistics.mean(llm_int) if llm_int else 0
    l_std = statistics.stdev(llm_int) if len(llm_int) > 1 else 0
    l_ci = 1.96 * l_std / math.sqrt(len(llm_int)) if len(llm_int) > 1 else 0

    r_mean = statistics.mean(rule_int) if rule_int else 0
    r_std = statistics.stdev(rule_int) if len(rule_int) > 1 else 0

    g_mean = statistics.mean(glm_int) if glm_int else 0
    g_std = statistics.stdev(glm_int) if len(glm_int) > 1 else 0

    l_bias = l_mean - h_mean if l_mean and h_mean else 0
    g_bias = g_mean - h_mean if g_mean and h_mean else 0

    print(f'--- {book} (n={n}) ---')
    print(f'  Human:  mean={h_mean:.2f}, std={h_std:.2f}, 95%CI=+/-{h_ci:.2f}, range=[{min(human_int):.1f}, {max(human_int):.1f}]')
    print(f'  LLM:    mean={l_mean:.2f}, std={l_std:.2f}, 95%CI=+/-{l_ci:.2f}, bias={l_bias:+.2f}')
    print(f'  GLM:    mean={g_mean:.2f}, std={g_std:.2f}, bias={g_bias:+.2f}')
    print(f'  Rule:   mean={r_mean:.2f}, std={r_std:.2f}')

    l_mae = statistics.mean([abs(l - h) for l, h in zip(llm_int, human_int)]) if llm_int else 0
    g_mae = statistics.mean([abs(g - h) for g, h in zip(glm_int, human_int)]) if glm_int else 0
    r_mae = statistics.mean([abs(r - h) for r, h in zip(rule_int, human_int)]) if rule_int else 0
    print(f'  MAE:    LLM={l_mae:.2f}, GLM={g_mae:.2f}, Rule={r_mae:.2f}')
    print()

all_human = [float(r['human_intensity']) for r in rows if r.get('human_intensity', '').strip()]
all_llm = [float(r['llm_intensity']) for r in rows if r.get('llm_intensity', '').strip()]
all_glm = [float(r['glm_intensity']) for r in rows if r.get('glm_intensity', '').strip()]
all_rule = [float(r['rule_intensity']) for r in rows if r.get('rule_intensity', '').strip()]

print('=== 总体统计 ===')
print(f'Human: mean={statistics.mean(all_human):.2f}, std={statistics.stdev(all_human):.2f}')
print(f'LLM:   mean={statistics.mean(all_llm):.2f}, std={statistics.stdev(all_llm):.2f}')
print(f'GLM:   mean={statistics.mean(all_glm):.2f}, std={statistics.stdev(all_glm):.2f}')
print(f'Rule:  mean={statistics.mean(all_rule):.2f}, std={statistics.stdev(all_rule):.2f}')

sigma = statistics.stdev(all_human)
print()
print('=== Power Analysis (alpha=0.05, power=0.80) ===')
for delta in [0.5, 1.0, 1.5]:
    n_needed = math.ceil((1.96 + 0.84) ** 2 * sigma ** 2 / delta ** 2)
    print(f'  Detect delta={delta}: need n>={n_needed} per book (sigma={sigma:.2f})')

print()
print('=== 95%CI Width by Sample Size ===')
for n in [10, 20, 30, 50, 80, 100]:
    ci = 1.96 * sigma / math.sqrt(n)
    print(f'  n={n:3d}: 95%CI=+/-{ci:.2f} (width={2*ci:.2f})')
