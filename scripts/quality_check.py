#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""quality_check.py — 每段完成后的数据质量检查"""
import sys, os, json, re
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.dirname(__file__))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

import ai_annotate
ai_annotate.BATCH_SIZE = 2
from ai_annotate import get_book_batch_dir

PROJECT_ROOT = Path(__file__).parent.parent

INDEX_PATH = PROJECT_ROOT / "data" / "raw" / "novel_index.json"
with open(INDEX_PATH, 'r', encoding='utf-8') as f:
    idx = json.load(f)

ALL_BOOKS = {}
for n in idx.get('genres', {}).get('末世', {}).get('novels', []):
    fname = n['file']
    short = fname.replace('.txt', '')
    if short.startswith('《'):
        m = re.search(r'《(.+?)》', short)
        short = m.group(1) if m else short
    ALL_BOOKS[short] = fname

VALID_EMOTIONS = {"日常", "紧张", "爽快", "悬疑", "压抑", "感动", "热血", "悲壮", "温馨"}
VALID_CONFLICT = {"low", "medium", "high"}
VALID_PACE = {"slow", "medium", "fast"}
VALID_HOOK = {"weak", "medium", "strong"}

errors = []
warnings = []
stats = {"total_batches": 0, "scored_batches": 0, "total_chapters": 0, "scored_chapters": 0}

print("=" * 80)
print("数据质量检查")
print("=" * 80)

for book in sorted(ALL_BOOKS.keys()):
    bdir = get_book_batch_dir(book)
    if not bdir.exists():
        continue

    new_files = sorted(bdir.glob("new_*.json"))
    if not new_files:
        continue

    stats["total_batches"] += len(new_files)
    book_scored = 0
    book_chapters = 0
    book_scored_chapters = 0

    for nf in new_files:
        batch_num = int(nf.stem.split("_")[-1])
        sf = bdir / f"scores_new_{batch_num:02d}.json"

        try:
            with open(nf, 'r', encoding='utf-8') as f:
                new_data = json.load(f)
        except Exception as e:
            errors.append(f"{book}/{nf.name}: new文件JSON解析失败: {e}")
            continue

        book_chapters += len(new_data)
        stats["total_chapters"] += len(new_data)

        if not sf.exists():
            continue

        book_scored += 1
        stats["scored_batches"] += 1

        try:
            with open(sf, 'r', encoding='utf-8') as f:
                score_data = json.load(f)
        except Exception as e:
            errors.append(f"{book}/{sf.name}: scores文件JSON解析失败: {e}")
            continue

        if len(score_data) != len(new_data):
            errors.append(f"{book}/{sf.name}: 章节数不匹配 (new={len(new_data)}, scores={len(score_data)})")
            continue

        book_scored_chapters += len(score_data)
        stats["scored_chapters"] += len(score_data)

        new_map = {d['ch_num']: d for d in new_data}
        for score in score_data:
            ch_num = score.get('ch_num')
            prefix = f"{book}/{sf.name} ch{ch_num}"

            if ch_num not in new_map:
                errors.append(f"{prefix}: ch_num不在new文件中")
                continue

            new_entry = new_map[ch_num]

            if score.get('stratum') != new_entry.get('stratum'):
                errors.append(f"{prefix}: stratum不匹配 (score={score.get('stratum')}, new={new_entry.get('stratum')})")

            if score.get('wc') != new_entry.get('wc'):
                errors.append(f"{prefix}: wc不匹配 (score={score.get('wc')}, new={new_entry.get('wc')})")

            intensity = score.get('ai_intensity')
            if not isinstance(intensity, int) or intensity < 1 or intensity > 10:
                errors.append(f"{prefix}: ai_intensity={intensity} 不在1-10范围")

            retention = score.get('ai_retention')
            if not isinstance(retention, int) or retention < 1 or retention > 10:
                errors.append(f"{prefix}: ai_retention={retention} 不在1-10范围")

            if score.get('ai_conflict') not in VALID_CONFLICT:
                errors.append(f"{prefix}: ai_conflict={score.get('ai_conflict')} 不在{VALID_CONFLICT}")

            if score.get('ai_emotion') not in VALID_EMOTIONS:
                errors.append(f"{prefix}: ai_emotion={score.get('ai_emotion')} 不在{VALID_EMOTIONS}")

            if score.get('ai_pace') not in VALID_PACE:
                errors.append(f"{prefix}: ai_pace={score.get('ai_pace')} 不在{VALID_PACE}")

            if score.get('ai_hook') not in VALID_HOOK:
                errors.append(f"{prefix}: ai_hook={score.get('ai_hook')} 不在{VALID_HOOK}")

            analysis = score.get('ai_analysis', '')
            if not analysis or len(analysis.strip()) < 10:
                errors.append(f"{prefix}: ai_analysis过短或为空: '{analysis}'")
            elif len(analysis) > 100:
                warnings.append(f"{prefix}: ai_analysis过长({len(analysis)}字)")

    coverage = book_scored_chapters / book_chapters * 100 if book_chapters > 0 else 0
    status = "✅" if book_scored == len(new_files) else ("⚠️" if book_scored > 0 else "⬜")
    disp = book[:24]
    print(f"  {status} {disp:<26} {book_scored:>3}/{len(new_files):>3}批  {book_scored_chapters:>4}/{book_chapters:>4}章  {coverage:>5.1f}%")

print(f"\n{'='*80}")
print(f"汇总: {stats['scored_batches']}/{stats['total_batches']}批, {stats['scored_chapters']}/{stats['total_chapters']}章")
print(f"错误: {len(errors)}个, 警告: {len(warnings)}个")

if errors:
    print(f"\n❌ 错误详情 (前20条):")
    for e in errors[:20]:
        print(f"  {e}")
    if len(errors) > 20:
        print(f"  ... 还有{len(errors)-20}个错误")

if warnings:
    print(f"\n⚠️ 警告详情 (前10条):")
    for w in warnings[:10]:
        print(f"  {w}")

if not errors:
    print("\n✅ 质检通过，无错误。可以继续下一段。")
else:
    print(f"\n❌ 质检失败，有{len(errors)}个错误需要修复。")
