#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""检查所有未完成书籍的批次提取状态，并清理残留数据"""
import sys, os, json, shutil
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "novels" / "末世"
SCORES_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "scores"
BATCH_DIR = SCORES_DIR / "ai_annotate_batches"

import re, math

# 加载书籍列表
INDEX_PATH = PROJECT_ROOT / "data" / "raw" / "novel_index.json"
with open(INDEX_PATH, 'r', encoding='utf-8') as f:
    idx = json.load(f)

BOOKS = {}
for n in idx.get('genres', {}).get('末世', {}).get('novels', []):
    fname = n['file']
    short = fname.replace('.txt', '')
    if short.startswith('《'):
        m = re.search(r'《(.+?)》', short)
        short = m.group(1) if m else short
    BOOKS[short] = fname

STRATA = [
    {"name": "Opening", "start": 0.00, "end": 0.03},
    {"name": "Rising",  "start": 0.03, "end": 0.30},
    {"name": "Mid",     "start": 0.30, "end": 0.60},
    {"name": "Climax",  "start": 0.60, "end": 0.90},
    {"name": "Ending",  "start": 0.90, "end": 1.00},
]
SAMPLE_RATE = 0.10

from xiaoshuo.pipeline.rhythm.chapter_parser import extract_chapters

def get_book_dir(book_name):
    if book_name == "废土崛起":
        return BATCH_DIR
    return BATCH_DIR / book_name

def count_scored(book_name):
    bdir = get_book_dir(book_name)
    if not bdir.exists():
        return 0, set()
    scored = set()
    for sf in sorted(bdir.glob("scores_*.json")):
        try:
            with open(sf, 'r', encoding='utf-8') as f:
                for row in json.load(f):
                    if 'ch_num' in row:
                        scored.add(int(row['ch_num']))
        except:
            pass
    return len(scored), scored

def count_batches(book_name):
    bdir = get_book_dir(book_name)
    if not bdir.exists():
        return 0, 0, set()
    batches = sorted(bdir.glob("new_*.json"))
    batch_chs = set()
    for bf in batches:
        try:
            with open(bf, 'r', encoding='utf-8') as f:
                for row in json.load(f):
                    if 'ch_num' in row:
                        batch_chs.add(int(row['ch_num']))
        except:
            pass
    return len(batches), len(batch_chs), batch_chs

# 先清理狩魔手记和恐慌沸腾的残留评分（章节解析已修复，旧评分无效）
for book in ["狩魔手记_烟雨江南", "恐慌沸腾"]:
    bdir = get_book_dir(book)
    if bdir.exists():
        old_scores = list(bdir.glob("scores_*.json"))
        if old_scores:
            print(f"[清理] {book}: 删除 {len(old_scores)} 个残留评分文件")
            for sf in old_scores:
                sf.unlink()

print("\n=== 未完成书籍清单 ===")
print(f"{'书名':<28} {'总章':>6} {'10%':>5} {'批次':>5} {'批次章':>6} {'已评':>5} {'待评':>5} {'状态':<8}")
print("-" * 85)

unfinished = []
for book_name, txt_file in sorted(BOOKS.items()):
    txt_path = RAW_DIR / txt_file
    if not txt_path.exists():
        continue

    chapters = extract_chapters(str(txt_path))
    total = len(chapters)
    if total == 0:
        continue

    # 计算预期采样数
    expected = 0
    for s in STRATA:
        si = int(total * s["start"])
        ei = int(total * s["end"])
        if ei <= si:
            continue
        n = max(1, math.ceil((ei - si) * SAMPLE_RATE))
        expected += min(n, ei - si)

    n_batches, n_batch_chs, batch_chs = count_batches(book_name)
    n_scored, scored_chs = count_scored(book_name)

    missing = n_batch_chs - n_scored if n_batch_chs > 0 else expected
    coverage = (n_scored / expected * 100) if expected > 0 else 0

    # 判断状态
    if n_scored == 0 and n_batches == 0:
        status = "未提取"
    elif n_scored == 0:
        status = "未评分"
    elif coverage >= 99:
        status = "✅完成"
        continue  # 跳过已完成的
    elif coverage >= 50:
        status = "进行中"
    else:
        status = "刚开始"

    unfinished.append({
        "book": book_name,
        "total": total,
        "expected": expected,
        "batches": n_batches,
        "batch_chs": n_batch_chs,
        "scored": n_scored,
        "missing": missing,
        "status": status,
        "needs_extract": n_batches == 0,
    })

    disp = book_name[:26]
    print(f"{disp:<28} {total:>6} {expected:>5} {n_batches:>5} {n_batch_chs:>6} {n_scored:>5} {missing:>5} {status:<8}")

print(f"\n未完成书籍: {len(unfinished)}本")
print(f"需要提取批次: {sum(1 for u in unfinished if u['needs_extract'])}本")
print(f"需要评分章节: {sum(u['missing'] for u in unfinished)}章")

# 输出需要提取的书名
needs_extract = [u["book"] for u in unfinished if u["needs_extract"]]
if needs_extract:
    print(f"\n需要提取批次的书籍: {needs_extract}")
