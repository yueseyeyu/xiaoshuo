#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
提取30章正文供GLM盲评标注。
输出: scripts/glm_chapters.json
"""
import csv, re, json
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
RHYTHM_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "rhythm"
LLM_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "scores"
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "novels" / "末世"

BOOKS = [
    {"name": "废土崛起", "llm": LLM_DIR / "《废土崛起》（校对版全本）作者：通吃道人_llm.csv",
     "raw": RAW_DIR / "《废土崛起》（校对版全本）作者：通吃道人.txt"},
    {"name": "末日蟑螂", "llm": LLM_DIR / "《末日蟑螂》作者：伟岸蟑螂_llm.csv",
     "raw": RAW_DIR / "《末日蟑螂》作者：伟岸蟑螂.txt"},
    {"name": "末世大回炉", "llm": LLM_DIR / "《末世大回炉》（校对版全本）作者：二十二刀流_llm.csv",
     "raw": RAW_DIR / "《末世大回炉》（校对版全本）作者：二十二刀流.txt"},
]

def read_text(path):
    for enc in ["utf-8", "gbk", "gb18030", "utf-16"]:
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    return ""

def extract_chapters(raw_text):
    cn_nums = r"[一二三四五六七八九十百千零\d]+"
    pattern = r"(第" + cn_nums + r"章\s*[^\n]*)"
    parts = re.split(pattern, raw_text)
    chapters = {}
    if len(parts) < 5:
        return chapters
    for i in range(1, len(parts) - 1, 2):
        header = parts[i].strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        m = re.search(r"第(\d+)章", header)
        if m:
            ch_num = int(m.group(1))
        else:
            m2 = re.search(r"第([一二三四五六七八九十百千零]+)章", header)
            if m2:
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

def main():
    all_chapters = []
    for book in BOOKS:
        print(f"加载 {book['name']}...")
        raw_text = read_text(book["raw"])
        chapters_raw = extract_chapters(raw_text)
        print(f"  提取到 {len(chapters_raw)} 章")

        with open(book["llm"], "r", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                ch = int(r.get("ch_num", 0) or r.get("\ufeffch_num", 0) or 0)
                if ch <= 0:
                    continue
                body = chapters_raw.get(ch, "")
                if not body:
                    print(f"  [跳过] 第{ch}章 未找到原文")
                    continue
                all_chapters.append({
                    "book": book["name"],
                    "ch_num": ch,
                    "body": body,
                })

    output = Path(__file__).parent / "glm_chapters.json"
    with open(output, "w", encoding="utf-8") as f:
        json.dump(all_chapters, f, ensure_ascii=False)
    print(f"\n共 {len(all_chapters)} 章，已保存到 {output}")

if __name__ == "__main__":
    main()
