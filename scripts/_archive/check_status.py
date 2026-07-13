#!/usr/bin/env python
"""检查各书籍的批量提取和评分状态"""
import pathlib, json, csv

base = pathlib.Path('data/processed/末世/scores/ai_annotate_batches')

for book in ['狩魔手记_烟雨江南', '恐慌沸腾', '我 的 末 世 领 地', '末日蟑螂', '废土崛起']:
    bdir = base / book
    if not bdir.exists():
        print(f'{book}: 目录不存在')
        continue
    batches = sorted(bdir.glob('batch_*.json'))
    scores = sorted(bdir.glob('scores_*.json'))
    new_batches = sorted(bdir.glob('new_*.json'))
    new_scores = sorted(bdir.glob('new_scores_*.json'))

    # Count unique ch_num in batches
    batch_chs = set()
    for bf in batches + new_batches:
        try:
            with open(bf, 'r', encoding='utf-8') as f:
                for row in json.load(f):
                    batch_chs.add(int(row['ch_num']))
        except Exception as e:
            print(f'  WARN: {bf.name} parse error: {e}')

    # Count unique ch_num in scores
    score_chs = set()
    for sf in scores + new_scores:
        try:
            with open(sf, 'r', encoding='utf-8') as f:
                for row in json.load(f):
                    score_chs.add(int(row['ch_num']))
        except Exception as e:
            print(f'  WARN: {sf.name} parse error: {e}')

    # Check merged CSV
    csv_file = bdir / 'ai_scores.csv'
    csv_count = 0
    csv_chs = set()
    if csv_file.exists():
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                csv_count += 1
                if 'ch_num' in row:
                    csv_chs.add(int(row['ch_num']))

    missing = batch_chs - score_chs
    extra = score_chs - batch_chs

    print(f'{book}:')
    print(f'  batches={len(batches)+len(new_batches)}, batch_chs={len(batch_chs)}')
    print(f'  scores={len(scores)+len(new_scores)}, score_chs={len(score_chs)}')
    print(f'  csv_rows={csv_count}, csv_unique_chs={len(csv_chs)}')
    if missing:
        print(f'  MISSING scores for {len(missing)} chs: {sorted(missing)[:20]}...')
    if extra:
        print(f'  EXTRA scores (no batch): {len(extra)} chs')
    print()
