#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tier1_progress.py — Tier 1 AI标注进度追踪脚本

替代PowerShell方案, 用Python准确统计各书籍标注进度。

用法:
  python scripts/tier1_progress.py                    # 概览所有书籍(精确)
  python scripts/tier1_progress.py --fast             # 快速模式(不提取全文)
  python scripts/tier1_progress.py --book 狩魔手记_烟雨江南  # 单书详情
  python scripts/tier1_progress.py --csv              # 输出CSV格式
  python scripts/tier1_progress.py --json             # 输出JSON格式
  python scripts/tier1_progress.py --watch            # 持续监控(每30秒刷新)
"""
import json
import csv as csv_mod
import sys
import time
import re
import math
import argparse
from pathlib import Path
from datetime import datetime

# 项目路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

# 配置
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "novels" / "末世"
SCORES_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "scores"
BATCH_DIR = SCORES_DIR / "ai_annotate_batches"
INDEX_PATH = PROJECT_ROOT / "data" / "raw" / "novel_index.json"

# 分层比例 (与ai_annotate.py一致)
STRATA = [
    {"name": "Opening", "start": 0.00, "end": 0.03, "ratio": 0.03},
    {"name": "Rising",  "start": 0.03, "end": 0.30, "ratio": 0.27},
    {"name": "Mid",     "start": 0.30, "end": 0.60, "ratio": 0.30},
    {"name": "Climax",  "start": 0.60, "end": 0.90, "ratio": 0.30},
    {"name": "Ending",  "start": 0.90, "end": 1.00, "ratio": 0.10},
]
SAMPLE_RATE = 0.10


def load_books():
    """从novel_index.json加载所有末世书籍"""
    if not INDEX_PATH.exists():
        print(f"[ERROR] novel_index.json 不存在: {INDEX_PATH}")
        return {}
    with open(INDEX_PATH, 'r', encoding='utf-8') as f:
        idx = json.load(f)
    books = {}
    for n in idx.get('genres', {}).get('末世', {}).get('novels', []):
        fname = n['file']
        short = fname.replace('.txt', '')
        if short.startswith('《'):
            m = re.search(r'《(.+?)》', short)
            short = m.group(1) if m else short
        books[short] = fname
    return books


def count_chapters_fast(txt_path):
    """快速统计章节数 (用extract_chapters精确提取)"""
    try:
        from xiaoshuo.pipeline.rhythm.chapter_parser import extract_chapters
        chapters = extract_chapters(str(txt_path))
        return len(chapters)
    except Exception as e:
        # 最终fallback: 简单行计数
        count = 0
        try:
            with open(txt_path, 'r', encoding='utf-8') as f:
                for line in f:
                    s = line.strip()
                    if s.startswith('第') and ('章' in s or '节' in s):
                        count += 1
                    elif s.startswith('章') and len(s) < 30:
                        count += 1
                    elif s.startswith('序章'):
                        count += 1
        except Exception:
            pass
        return count


def estimate_sample_count(total_chapters):
    """估算10%分层采样的章节数 (不实际提取)"""
    if total_chapters == 0:
        return 0
    total = 0
    for stratum in STRATA:
        start_idx = int(total_chapters * stratum["start"])
        end_idx = int(total_chapters * stratum["end"])
        if end_idx <= start_idx:
            continue
        stratum_chs = end_idx - start_idx
        n_sample = max(1, math.ceil(stratum_chs * SAMPLE_RATE))
        total += min(n_sample, stratum_chs)
    return total


def get_book_dir(book_name):
    """获取书籍的批次目录"""
    if book_name == "废土崛起":
        return BATCH_DIR
    return BATCH_DIR / book_name


def count_scored_chapters(book_name):
    """统计已评分的章节数 (从scores_*.json文件)"""
    bdir = get_book_dir(book_name)
    if not bdir.exists():
        return 0, set()

    scored_chs = set()
    for sf in sorted(bdir.glob("scores_*.json")):
        try:
            with open(sf, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    for row in data:
                        if 'ch_num' in row:
                            scored_chs.add(int(row['ch_num']))
        except (json.JSONDecodeError, IOError):
            pass
    return len(scored_chs), scored_chs


def count_merged_csv(book_name):
    """统计合并CSV中的章节数"""
    csv_path = SCORES_DIR / f"{book_name}_ai_full.csv"
    if not csv_path.exists():
        return 0
    count = 0
    try:
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            count = sum(1 for _ in csv_mod.DictReader(f))
    except Exception:
        pass
    return count


def get_book_status(book_name, txt_file, fast=True):
    """获取单本书的标注状态"""
    txt_path = RAW_DIR / txt_file
    result = {
        "book": book_name,
        "file": txt_file,
        "exists": txt_path.exists(),
        "total_chapters": 0,
        "expected_sample": 0,
        "scored": 0,
        "merged_csv": 0,
        "coverage_pct": 0.0,
        "status": "未知",
    }

    if not txt_path.exists():
        result["status"] = "文件缺失"
        return result

    # 统计章节
    if fast:
        result["total_chapters"] = count_chapters_fast(txt_path)
    else:
        from xiaoshuo.pipeline.rhythm_analyzer import extract_chapters
        chapters = extract_chapters(str(txt_path))
        result["total_chapters"] = len(chapters)

    result["expected_sample"] = estimate_sample_count(result["total_chapters"])

    # 统计评分
    scored_count, scored_chs = count_scored_chapters(book_name)
    result["scored"] = scored_count

    # 统计合并CSV
    result["merged_csv"] = count_merged_csv(book_name)

    # 覆盖率
    if result["expected_sample"] > 0:
        result["coverage_pct"] = scored_count / result["expected_sample"] * 100
    elif scored_count > 0:
        result["coverage_pct"] = 100.0

    # 状态判定
    if scored_count == 0 and result["merged_csv"] == 0:
        result["status"] = "未开始"
    elif result["coverage_pct"] >= 99:
        result["status"] = "✅完成" if result["merged_csv"] > 0 else "待合并"
    elif result["coverage_pct"] >= 50:
        result["status"] = "进行中"
    else:
        result["status"] = "刚开始"

    return result


def print_overview(books, fast=True):
    """打印所有书籍的进度概览"""
    print("=" * 90)
    print(f"Tier 1 AI标注进度 (扫描时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
    print("=" * 90)
    print(f"{'书名':<28} {'总章':>6} {'10%':>5} {'已评':>5} {'覆盖率':>7} {'CSV':>5} {'状态':<8}")
    print("-" * 90)

    total_expected = 0
    total_scored = 0
    total_merged = 0
    completed = 0
    in_progress = 0
    not_started = 0

    for book_name, txt_file in sorted(books.items()):
        status = get_book_status(book_name, txt_file, fast=fast)
        total_expected += status["expected_sample"]
        total_scored += status["scored"]
        total_merged += status["merged_csv"]

        if status["status"] == "✅完成":
            completed += 1
        elif status["status"] == "未开始":
            not_started += 1
        else:
            in_progress += 1

        # 截断书名
        disp_name = book_name[:26] if len(book_name) > 26 else book_name
        print(f"{disp_name:<28} {status['total_chapters']:>6} {status['expected_sample']:>5} "
              f"{status['scored']:>5} {status['coverage_pct']:>6.1f}% {status['merged_csv']:>5} {status['status']:<8}")

    print("-" * 90)
    print(f"{'合计':<28} {'':>6} {total_expected:>5} {total_scored:>5} "
          f"{total_scored/total_expected*100 if total_expected else 0:>6.1f}% {total_merged:>5}")
    print(f"\n书籍统计: {len(books)}本 | ✅完成: {completed} | 进行中: {in_progress} | 未开始: {not_started}")
    print(f"总进度: {total_scored}/{total_expected}章 ({total_scored/total_expected*100 if total_expected else 0:.1f}%)")


def print_book_detail(book_name, txt_file):
    """打印单本书的详细信息"""
    status = get_book_status(book_name, txt_file, fast=False)

    print("=" * 60)
    print(f"书籍详情: {book_name}")
    print("=" * 60)
    print(f"  文件: {txt_file}")
    print(f"  总章节: {status['total_chapters']}")
    print(f"  10%采样预期: {status['expected_sample']}")
    print(f"  已评分: {status['scored']}")
    print(f"  合并CSV: {status['merged_csv']}")
    print(f"  覆盖率: {status['coverage_pct']:.1f}%")
    print(f"  状态: {status['status']}")

    # 显示缺失章节
    if status["scored"] < status["expected_sample"]:
        bdir = get_book_dir(book_name)
        if bdir.exists():
            scored_chs = set()
            for sf in sorted(bdir.glob("scores_*.json")):
                try:
                    with open(sf, 'r', encoding='utf-8') as f:
                        for row in json.load(f):
                            if 'ch_num' in row:
                                scored_chs.add(int(row['ch_num']))
                except:
                    pass
            print(f"\n  缺失评分章节 ({status['expected_sample'] - len(scored_chs)}章):")

            # 重新提取采样章节列表
            from xiaoshuo.pipeline.rhythm_analyzer import extract_chapters
            txt_path = RAW_DIR / txt_file
            if txt_path.exists():
                chapters = extract_chapters(str(txt_path))
                sorted_chs = sorted(chapters, key=lambda c: c["num"])
                all_nums = [c["num"] for c in sorted_chs]
                sampled = []
                for stratum in STRATA:
                    start_idx = int(len(chapters) * stratum["start"])
                    end_idx = int(len(chapters) * stratum["end"])
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
                        sampled.append((ch_num, stratum["name"]))

                missing = [(ch, s) for ch, s in sampled if ch not in scored_chs]
                if missing:
                    for ch, s in missing[:30]:
                        print(f"    ch{ch:>5} [{s}]")
                    if len(missing) > 30:
                        print(f"    ... 还有 {len(missing)-30} 章")
                else:
                    print("    (无缺失)")


def output_csv(books, fast=True):
    """输出CSV格式"""
    writer = csv_mod.writer(sys.stdout)
    writer.writerow(["book", "file", "total_chapters", "expected_sample",
                     "scored", "merged_csv", "coverage_pct", "status"])
    for book_name, txt_file in sorted(books.items()):
        s = get_book_status(book_name, txt_file, fast=fast)
        writer.writerow([s["book"], s["file"], s["total_chapters"],
                         s["expected_sample"], s["scored"], s["merged_csv"],
                         f"{s['coverage_pct']:.1f}", s["status"]])


def output_json(books, fast=True):
    """输出JSON格式"""
    results = []
    for book_name, txt_file in sorted(books.items()):
        results.append(get_book_status(book_name, txt_file, fast=fast))
    print(json.dumps(results, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Tier 1 AI标注进度追踪")
    parser.add_argument("--book", type=str, help="查看指定书籍的详细信息")
    parser.add_argument("--csv", action="store_true", help="输出CSV格式")
    parser.add_argument("--json", action="store_true", help="输出JSON格式")
    parser.add_argument("--watch", action="store_true", help="持续监控(每30秒刷新)")
    parser.add_argument("--fast", action="store_true", help="快速模式(跳过全文提取)")
    args = parser.parse_args()

    books = load_books()
    if not books:
        print("[ERROR] 未找到任何书籍")
        return

    if args.book:
        if args.book not in books:
            print(f"[ERROR] 未知书籍: {args.book}")
            print(f"可选: {', '.join(sorted(books.keys()))}")
            return
        print_book_detail(args.book, books[args.book])
        return

    if args.csv:
        output_csv(books, fast=args.fast)
        return

    if args.json:
        output_json(books, fast=args.fast)
        return

    if args.watch:
        try:
            while True:
                print("\033[2J\033[H", end="")  # 清屏
                print_overview(books, fast=args.fast)
                print(f"\n下次刷新: 30秒后 (Ctrl+C退出)")
                time.sleep(30)
        except KeyboardInterrupt:
            print("\n退出监控")
        return

    print_overview(books, fast=args.fast)


if __name__ == "__main__":
    main()
