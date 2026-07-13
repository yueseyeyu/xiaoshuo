#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""
[已废弃] 人工标注工具 — 30章Ground Truth标注
==============================================
此脚本为旧版CLI标注工具，已被HTML标注工具取代。
请使用: D:\miniconda3\envs\llm-shared\python.exe scripts\gen_annotate_html.py
生成HTML标注工具后，在浏览器中标注并导出CSV。

旧版说明（仅供参考）:
从3本书各选10章（3低+4中+3高），展示章节文本和现有评分，人工打分。
用法: D:\miniconda3\envs\llm-shared\python.exe scripts\annotate_golden.py
输出: data/processed/末世/scores/human_golden.csv
"""
import csv
import os
import re
import sys
import json
from pathlib import Path
from collections import defaultdict

# ── 配置 ──
PROJECT_ROOT = Path(__file__).parent.parent
RHYTHM_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "rhythm"
LLM_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "scores"
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "novels" / "末世"
OUTPUT = LLM_DIR / "human_golden.csv"

BOOKS = [
    {
        "name": "废土崛起",
        "rhythm": RHYTHM_DIR / "rhythm_《废土崛起》（校对版全本）作者：通吃道人.csv",
        "llm": LLM_DIR / "《废土崛起》（校对版全本）作者：通吃道人_llm.csv",
        "raw": RAW_DIR / "《废土崛起》（校对版全本）作者：通吃道人.txt",
    },
    {
        "name": "末日蟑螂",
        "rhythm": RHYTHM_DIR / "rhythm_《末日蟑螂》作者：伟岸蟑螂.csv",
        "llm": LLM_DIR / "《末日蟑螂》作者：伟岸蟑螂_llm.csv",
        "raw": RAW_DIR / "《末日蟑螂》作者：伟岸蟑螂.txt",
    },
    {
        "name": "末世大回炉",
        "rhythm": RHYTHM_DIR / "rhythm_《末世大回炉》（校对版全本）作者：二十二刀流.csv",
        "llm": LLM_DIR / "《末世大回炉》（校对版全本）作者：二十二刀流_llm.csv",
        "raw": RAW_DIR / "《末世大回炉》（校对版全本）作者：二十二刀流.txt",
    },
]

# ── 章节提取 (简化版, 复用 chapter_parser 逻辑) ──
def read_text(path):
    for enc in ["utf-8", "gbk", "gb18030", "utf-16"]:
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    return ""

def extract_chapters(raw_text):
    """提取章节, 返回 {ch_num: text}"""
    cn_nums = r"[一二三四五六七八九十百千零\d]+"
    pattern = r"(第" + cn_nums + r"章\s*[^\n]*)"
    parts = re.split(pattern, raw_text)
    chapters = {}
    if len(parts) < 5:
        return chapters
    # parts: [pre, header1, body1, header2, body2, ...]
    for i in range(1, len(parts) - 1, 2):
        header = parts[i].strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        # 提取章节号
        m = re.search(r"第(\d+)章", header)
        if m:
            ch_num = int(m.group(1))
        else:
            m2 = re.search(r"第([一二三四五六七八九十百千零]+)章", header)
            if m2:
                # 简单中文数字转换
                cn_map = {"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9,"十":10}
                cn_str = m2.group(1)
                if len(cn_str) == 1:
                    ch_num = cn_map.get(cn_str, 0)
                elif cn_str == "十":
                    ch_num = 10
                elif cn_str.startswith("十"):
                    ch_num = 10 + cn_map.get(cn_str[1], 0)
                elif cn_str.endswith("十"):
                    ch_num = cn_map.get(cn_str[0], 1) * 10
                else:
                    ch_num = 0
            else:
                continue
        if ch_num > 0 and body:
            chapters[ch_num] = body
    return chapters

# ── 选章 ──
def select_chapters(rhythm_csv, llm_csv):
    """从rhythm CSV选10章: 3低(rule<2) + 4中(2-6) + 3高(rule>6)"""
    rows = []
    with open(rhythm_csv, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for r in reader:
            try:
                pi = float(r.get("pleasure_intensity", 0) or 0)
                ch = int(r.get("ch_num", 0) or r.get("\ufeffch_num", 0) or 0)
                if ch > 0:
                    rows.append({"ch_num": ch, "pleasure_intensity": pi, "wc": int(r.get("wc", 0) or 0)})
            except (ValueError, TypeError):
                continue

    # 加载LLM分数
    llm_scores = {}
    if llm_csv and llm_csv.exists():
        with open(llm_csv, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for r in reader:
                try:
                    ch = int(r.get("ch_num", 0) or r.get("\ufeffch_num", 0) or 0)
                    if ch > 0:
                        llm_scores[ch] = {
                            "intensity": float(r.get("intensity", 0) or 0),
                            "retention": float(r.get("retention", 0) or 0),
                        }
                except (ValueError, TypeError):
                    continue

    # 分三档
    low = [r for r in rows if r["pleasure_intensity"] < 2.0 and r["wc"] > 500]
    mid = [r for r in rows if 2.0 <= r["pleasure_intensity"] <= 6.0 and r["wc"] > 500]
    high = [r for r in rows if r["pleasure_intensity"] > 6.0 and r["wc"] > 500]

    # 均匀采样
    import random
    random.seed(42)  # 可复现
    def sample_n(lst, n):
        if len(lst) <= n:
            return lst
        step = len(lst) // n
        return [lst[i * step] for i in range(n)]

    selected = sample_n(low, 3) + sample_n(mid, 4) + sample_n(high, 3)

    # 合并LLM分数
    for r in selected:
        r["llm_intensity"] = llm_scores.get(r["ch_num"], {}).get("intensity", None)
        r["llm_retention"] = llm_scores.get(r["ch_num"], {}).get("retention", None)

    return selected

# ── 标注界面 ──
def annotate(book_info, chapters_raw, selected):
    """交互式标注"""
    book_name = book_info["name"]
    results = []

    print(f"\n{'='*60}")
    print(f"  开始标注: {book_name}")
    print(f"  共 {len(selected)} 章待标注")
    print(f"{'='*60}")

    for idx, ch in enumerate(selected, 1):
        ch_num = ch["ch_num"]
        body = chapters_raw.get(ch_num, "")

        if not body:
            print(f"\n[跳过] 第{ch_num}章 未找到原文")
            continue

        # 显示章节信息
        print(f"\n{'─'*60}")
        print(f"  [{book_name}] 第{idx}/{len(selected)}章 | 章节号: {ch_num} | 字数: {ch['wc']}")
        print(f"  规则评分: pleasure_intensity={ch['pleasure_intensity']}")
        if ch["llm_intensity"] is not None:
            print(f"  LLM评分:  intensity={ch['llm_intensity']}, retention={ch['llm_retention']}")
        else:
            print(f"  LLM评分:  (无)")
        print(f"{'─'*60}")

        # 显示章节文本 (前800字 + 后400字)
        if len(body) > 1200:
            display = body[:800] + "\n\n...[中段省略]...\n\n" + body[-400:]
        else:
            display = body
        print(display)
        print(f"{'─'*60}")

        # 输入标注
        while True:
            try:
                intensity = float(input("  爽点强度 (1-10): ").strip())
                if 1 <= intensity <= 10:
                    break
                print("  请输入1-10之间的数字")
            except ValueError:
                print("  请输入有效数字")

        while True:
            try:
                retention = float(input("  读者留存 (1-10): ").strip())
                if 1 <= retention <= 10:
                    break
                print("  请输入1-10之间的数字")
            except ValueError:
                print("  请输入有效数字")

        review = input("  一句话评语 (可选, 回车跳过): ").strip()

        results.append({
            "book": book_name,
            "ch_num": ch_num,
            "wc": ch["wc"],
            "rule_intensity": ch["pleasure_intensity"],
            "llm_intensity": ch["llm_intensity"],
            "llm_retention": ch["llm_retention"],
            "human_intensity": intensity,
            "human_retention": retention,
            "review": review,
        })
        print(f"  ✓ 已记录: intensity={intensity}, retention={retention}")

    return results

# ── 主流程 ──
def main():
    all_results = []

    # 加载已有进度
    existing_chapters = set()
    if OUTPUT.exists():
        with open(OUTPUT, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for r in reader:
                existing_chapters.add((r.get("book"), int(r.get("ch_num", 0))))
        print(f"发现已有标注 {len(existing_chapters)} 章，将跳过已标注章节。")

    for book in BOOKS:
        print(f"\n加载 {book['name']} 数据...")
        raw_text = read_text(book["raw"])
        chapters_raw = extract_chapters(raw_text)
        print(f"  提取到 {len(chapters_raw)} 章")

        selected = select_chapters(book["rhythm"], book["llm"])
        print(f"  选中 {len(selected)} 章待标注")

        # 过滤已标注
        selected = [s for s in selected if (book["name"], s["ch_num"]) not in existing_chapters]
        if not selected:
            print(f"  {book['name']} 已全部标注完毕，跳过。")
            continue

        results = annotate(book, chapters_raw, selected)
        all_results.extend(results)

        # 每本书标注完立即保存
        save_results(all_results)
        print(f"\n✓ {book['name']} 标注完成，已保存到 {OUTPUT}")

    if all_results:
        print(f"\n{'='*60}")
        print(f"  全部标注完成！共 {len(all_results)} 章")
        print(f"  保存到: {OUTPUT}")
        print(f"{'='*60}")
    else:
        print("\n没有需要标注的章节。")

def save_results(results):
    """保存/追加到CSV"""
    fieldnames = [
        "book", "ch_num", "wc",
        "rule_intensity", "llm_intensity", "llm_retention",
        "human_intensity", "human_retention", "review",
    ]

    # 合并已有数据
    all_data = []
    if OUTPUT.exists():
        with open(OUTPUT, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            all_data = list(reader)

    # 添加新数据 (去重)
    existing_keys = {(r.get("book"), int(r.get("ch_num", 0))) for r in all_data}
    for r in results:
        key = (r["book"], r["ch_num"])
        if key not in existing_keys:
            all_data.append(r)
            existing_keys.add(key)

    # 按书+章节号排序
    all_data.sort(key=lambda r: (r.get("book", ""), int(r.get("ch_num", 0))))

    with open(OUTPUT, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in all_data:
            writer.writerow({k: r.get(k, "") for k in fieldnames})

if __name__ == "__main__":
    main()
