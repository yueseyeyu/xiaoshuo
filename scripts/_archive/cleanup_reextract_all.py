#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""cleanup_reextract_all.py — 清理所有失效数据并重新提取批次

对19本❌失效 + 4本⚠️部分失效的书:
1. 删除旧批次文件和评分文件
2. 用修复后的解析器重新提取
3. 统计最终状态

对10本✅有效的书: 保持不动
"""
import sys, os, json, math, re, shutil
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.dirname(__file__))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

import ai_annotate
ai_annotate.BATCH_SIZE = 2
from ai_annotate import extract_full_chapters, write_batches, get_book_batch_dir

PROJECT_ROOT = Path(__file__).parent.parent
SCORES_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "scores"

# 需要完全清理+重新提取的书籍 (19本❌ + 4本⚠️ = 23本)
# 排除10本✅有效的: 世界末日, 异兽迷城, 恐慌沸腾, 末世之深渊召唤师, 末世大回炉,
#                   末世魔神游戏, 灾厄纪元, 狩魔手记, 第一序列, 重卡战车在末世
NEEDS_REBUILD = [
    "从红月开始",
    "全球进化",
    "地球游戏场",
    "废土崛起",
    "我 的 末 世 领 地",
    "我在末世有套房",
    "我在末世种个田",
    "我的女友是丧尸",
    "末世召唤狂潮",
    "末世超级商人",
    "末日乐园",
    "末日拼图游戏",
    "末日蟑螂",
    "神秘尽头",
    "第九特区",
    "蹉跎",
    "长夜余火",
    "限制级末日症候",
    "黑暗文明_古羲",
    "黑暗末日",
    "黑暗王者",
    "黑暗血时代",
    "全球变异，从灾厄降临开始",
]

print(f"需要清理+重新提取: {len(NEEDS_REBUILD)}本")
print("=" * 70)

results = []

for book in NEEDS_REBUILD:
    bdir = get_book_batch_dir(book)
    csv_path = SCORES_DIR / f"{book}_ai_full.csv"
    pilot_csv = SCORES_DIR / f"{book}_ai.csv"

    # 统计旧数据
    old_batches = len(list(bdir.glob("new_*.json"))) if bdir.exists() else 0
    old_scores = len(list(bdir.glob("scores_*.json"))) if bdir.exists() else 0
    old_csv = csv_path.exists()

    print(f"\n{book}:")
    print(f"  旧数据: {old_batches}批, {old_scores}评分, CSV={'有' if old_csv else '无'}")

    # 清理
    if bdir.exists():
        shutil.rmtree(bdir)
    if old_csv:
        csv_path.unlink()
    if pilot_csv.exists():
        pilot_csv.unlink()

    # 重新提取
    chapters = extract_full_chapters(book)
    if chapters:
        paths = write_batches(chapters, book, prefix="new")
        n_batches = len(paths)
        n_chs = len(chapters)
        print(f"  新数据: {n_chs}章 → {n_batches}批")
        results.append({"book": book, "chapters": n_chs, "batches": n_batches, "status": "OK"})
    else:
        print(f"  ❌提取失败!")
        results.append({"book": book, "chapters": 0, "batches": 0, "status": "FAIL"})

print("\n" + "=" * 70)
print(f"完成: {len(results)}本")
total_chs = sum(r["chapters"] for r in results)
total_batches = sum(r["batches"] for r in results)
print(f"总章节: {total_chs}, 总批次: {total_batches}")
fails = [r for r in results if r["status"] == "FAIL"]
if fails:
    print(f"❌失败: {[r['book'] for r in fails]}")
else:
    print("✅全部成功")
