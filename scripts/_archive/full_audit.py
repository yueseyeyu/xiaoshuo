#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""full_audit.py — 章节解析器修复后的全面数据审计

检查每本书:
1. 用修复后的解析器重新提取章节
2. 对比批次文件中的ch_num是否在新章节列表中
3. 识别失效数据（旧解析器产生的错误章节号）
4. 识别需要重新提取的书籍
"""
import sys, os, json, math, re
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "novels" / "末世"
SCORES_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "scores"
BATCH_DIR = SCORES_DIR / "ai_annotate_batches"

from xiaoshuo.pipeline.rhythm.chapter_parser import extract_chapters

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

def get_book_dir(book_name):
    if book_name == "废土崛起":
        return BATCH_DIR
    return BATCH_DIR / book_name

def compute_expected_sample(total):
    if total == 0:
        return 0
    expected = 0
    for s in STRATA:
        si = int(total * s["start"])
        ei = int(total * s["end"])
        if ei <= si:
            continue
        n = max(1, math.ceil((ei - si) * SAMPLE_RATE))
        expected += min(n, ei - si)
    return expected

def compute_sampled_chs(chapters):
    """返回采样的ch_num集合 + stratum映射"""
    total = len(chapters)
    if total == 0:
        return {}, {}
    sorted_chs = sorted(chapters, key=lambda c: c["num"])
    all_nums = [c["num"] for c in sorted_chs]
    sampled = {}
    stratum_map = {}
    for stratum in STRATA:
        start_idx = int(total * stratum["start"])
        end_idx = int(total * stratum["end"])
        if end_idx <= start_idx:
            continue
        stratum_chs = all_nums[start_idx:end_idx]
        n_sample = max(1, math.ceil(len(stratum_chs) * SAMPLE_RATE))
        if len(stratum_chs) <= n_sample:
            selected = stratum_chs
        else:
            step = len(stratum_chs) / n_sample
            indices = [int(i * step) for i in range(n_sample)]
            indices = sorted(set(min(i, len(stratum_chs)-1) for i in indices))
            selected = [stratum_chs[i] for i in indices]
        for ch_num in selected:
            sampled[ch_num] = True
            stratum_map[ch_num] = stratum["name"]
    return sampled, stratum_map

print("=" * 100)
print("全面数据审计 — 章节解析器修复后")
print("=" * 100)

audit_results = []

for book_name, txt_file in sorted(BOOKS.items()):
    txt_path = RAW_DIR / txt_file
    if not txt_path.exists():
        continue

    # 用修复后的解析器提取
    chapters = extract_chapters(str(txt_path))
    total_new = len(chapters)
    expected = compute_expected_sample(total_new)

    # 新解析器的采样章节
    sampled_chs, stratum_map = compute_sampled_chs(chapters)
    new_sample_set = set(sampled_chs.keys())

    # 检查批次文件
    bdir = get_book_dir(book_name)
    batch_chs = set()
    scored_chs = set()
    n_batches = 0
    n_scores = 0

    if bdir.exists():
        for bf in sorted(bdir.glob("new_*.json")):
            n_batches += 1
            try:
                with open(bf, 'r', encoding='utf-8') as f:
                    for row in json.load(f):
                        if 'ch_num' in row:
                            batch_chs.add(int(row['ch_num']))
            except:
                pass

        for sf in sorted(bdir.glob("scores_*.json")):
            n_scores += 1
            try:
                with open(sf, 'r', encoding='utf-8') as f:
                    for row in json.load(f):
                        if 'ch_num' in row:
                            scored_chs.add(int(row['ch_num']))
            except:
                pass

    # 检查CSV
    csv_chs = set()
    csv_path = SCORES_DIR / f"{book_name}_ai_full.csv"
    if csv_path.exists():
        import csv as csv_mod
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            for row in csv_mod.DictReader(f):
                if 'ch_num' in row:
                    csv_chs.add(int(row['ch_num']))

    # 关键检查：批次ch_num是否在新采样集中
    batch_in_sample = batch_chs & new_sample_set
    batch_not_in_sample = batch_chs - new_sample_set  # 批次中有但新采样没有的
    sample_not_in_batch = new_sample_set - batch_chs  # 新采样有但批次没有的

    # 评分ch_num是否在新采样集中
    scored_in_sample = scored_chs & new_sample_set
    scored_not_in_sample = scored_chs - new_sample_set  # 评分了但不在新采样中（无效评分）

    # 判定数据有效性
    if total_new == 0:
        validity = "❌解析失败"
        action = "需排查"
    elif len(batch_not_in_sample) > len(batch_in_sample) * 0.3:
        validity = "❌数据失效"
        action = "需重新提取+重评"
    elif len(batch_not_in_sample) > 0 and len(batch_in_sample) > 0:
        validity = "⚠️部分失效"
        action = "需部分修复"
    elif len(sample_not_in_batch) > 0 and len(batch_chs) > 0:
        validity = "⚠️批次不完整"
        action = "需补提取"
    elif len(batch_chs) == 0 and expected > 0:
        validity = "⬜未提取"
        action = "需提取"
    elif len(scored_not_in_sample) > len(scored_in_sample) * 0.3:
        validity = "❌评分失效"
        action = "需重评"
    else:
        validity = "✅有效"
        action = ""

    # 计算实际覆盖率（基于新采样）
    real_coverage = len(scored_in_sample) / len(new_sample_set) * 100 if new_sample_set else 0

    result = {
        "book": book_name,
        "total_new": total_new,
        "expected": expected,
        "n_batches": n_batches,
        "batch_chs": len(batch_chs),
        "batch_in_sample": len(batch_in_sample),
        "batch_not_in_sample": len(batch_not_in_sample),
        "sample_not_in_batch": len(sample_not_in_batch),
        "scored": len(scored_chs),
        "scored_in_sample": len(scored_in_sample),
        "scored_not_in_sample": len(scored_not_in_sample),
        "csv_chs": len(csv_chs),
        "real_coverage": real_coverage,
        "validity": validity,
        "action": action,
    }
    audit_results.append(result)

    disp = book_name[:24]
    print(f"{disp:<26} 总{total_new:>5} 采样{expected:>4} 批{n_batches:>3} "
          f"批章{len(batch_chs):>4} 评分{len(scored_chs):>4} "
          f"有效评分{len(scored_in_sample):>4}/{expected:>4}={real_coverage:>5.1f}% "
          f"CSV{len(csv_chs):>4} {validity} {action}")

print("\n" + "=" * 100)
print("汇总")
print("=" * 100)

# 分类统计
valid = [r for r in audit_results if r["validity"] == "✅有效"]
invalid = [r for r in audit_results if r["validity"] in ("❌数据失效", "❌评分失效")]
partial = [r for r in audit_results if r["validity"] in ("⚠️部分失效", "⚠️批次不完整")]
not_extracted = [r for r in audit_results if r["validity"] == "⬜未提取"]
parse_fail = [r for r in audit_results if r["validity"] == "❌解析失败"]

print(f"✅有效: {len(valid)}本")
print(f"❌失效(需重做): {len(invalid)}本 — {[r['book'] for r in invalid]}")
print(f"⚠️部分失效: {len(partial)}本 — {[r['book'] for r in partial]}")
print(f"⬜未提取: {len(not_extracted)}本 — {[r['book'] for r in not_extracted]}")
print(f"❌解析失败: {len(parse_fail)}本 — {[r['book'] for r in parse_fail]}")

# 详细列出需要操作的书籍
print("\n" + "=" * 100)
print("需要操作的书籍详情")
print("=" * 100)

for r in audit_results:
    if r["validity"] in ("❌数据失效", "❌评分失效", "⚠️部分失效", "⚠️批次不完整", "⬜未提取", "❌解析失败"):
        print(f"\n{r['book']}:")
        print(f"  总章节(新): {r['total_new']}, 10%采样: {r['expected']}")
        print(f"  批次: {r['n_batches']}个, 批次章数: {r['batch_chs']}")
        print(f"  批次中有效章节: {r['batch_in_sample']}, 无效章节: {r['batch_not_in_sample']}")
        print(f"  新采样中未提取: {r['sample_not_in_batch']}章")
        print(f"  评分总数: {r['scored']}, 有效评分: {r['scored_in_sample']}, 无效评分: {r['scored_not_in_sample']}")
        print(f"  CSV: {r['csv_chs']}章")
        print(f"  真实覆盖率: {r['real_coverage']:.1f}%")
        print(f"  判定: {r['validity']} → {r['action']}")
