#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""提取Golden Set扩展章节原文，供AI盲评标注。"""
import re, json, sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "novels" / "末世"

# 扩展方案: 6章结尾(现有3书) + 14章(2本新书) = 20章 → 总计50章
EXPANSION_PLAN = [
    # 现有3书 - 补结尾层(95%, 98%)
    {"book": "废土崛起", "file": "《废土崛起》（校对版全本）作者：通吃道人.txt", "chapters": [1833, 1890]},
    {"book": "末日蟑螂", "file": "《末日蟑螂》作者：伟岸蟑螂.txt", "chapters": [2284, 2356]},
    {"book": "末世大回炉", "file": "《末世大回炉》（校对版全本）作者：二十二刀流.txt", "chapters": [1840, 1898]},
    # 新书1: 末世魔神游戏 (1980ch, A级, 游戏系统流)
    {"book": "末世魔神游戏", "file": "《末世魔神游戏》（校对版全本）作者：石闻.txt", "chapters": [1, 198, 495, 990, 1485, 1782, 1940]},
    # 新书2: 黑暗血时代 (1855ch, A级, 暗黑系)
    {"book": "黑暗血时代", "file": "黑暗血时代.txt", "chapters": [1, 186, 464, 928, 1391, 1670, 1818]},
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
            chapters[ch_num] = {"header": header, "body": body}
    return chapters

def main():
    all_chapters = []
    for plan in EXPANSION_PLAN:
        txt_path = RAW_DIR / plan["file"]
        if not txt_path.exists():
            print(f"[SKIP] {plan['file']} not found")
            continue
        print(f"Loading {plan['book']}...")
        raw_text = read_text(txt_path)
        chapters = extract_chapters(raw_text)
        print(f"  Extracted {len(chapters)} chapters total")

        for ch_num in plan["chapters"]:
            # 尝试精确匹配，找不到就找最近的
            if ch_num in chapters:
                ch = chapters[ch_num]
            else:
                # 找最近的章节
                available = sorted(chapters.keys())
                closest = min(available, key=lambda x: abs(x - ch_num))
                if abs(closest - ch_num) > 10:
                    print(f"  [WARN] ch{ch_num} not found, closest is ch{closest} (delta={abs(closest-ch_num)})")
                    continue
                ch = chapters[closest]
                ch_num = closest
                print(f"  [ADJUST] ch{plan['chapters'][plan['chapters'].index(ch_num)]} → ch{ch_num}")

            body = ch["body"]
            wc = len(body)
            # 截取前3000字（如果太长）
            if len(body) > 3000:
                body = body[:3000]
            all_chapters.append({
                "book": plan["book"],
                "ch_num": ch_num,
                "wc": wc,
                "body": body,
            })
            print(f"  ch{ch_num}: {wc} chars")

    output = Path(__file__).parent / "expansion_chapters.json"
    with open(output, "w", encoding="utf-8") as f:
        json.dump(all_chapters, f, ensure_ascii=False, indent=2)
    print(f"\n共 {len(all_chapters)} 章，已保存到 {output}")

if __name__ == "__main__":
    main()
