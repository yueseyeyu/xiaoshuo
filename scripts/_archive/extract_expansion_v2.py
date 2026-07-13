#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""提取Golden Set扩展章节原文v2 — 使用rhythm_analyzer的extract_chapters。"""
import json, sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "novels" / "末世"

from xiaoshuo.pipeline.rhythm_analyzer import extract_chapters

EXPANSION_PLAN = [
    {"book": "废土崛起", "file": "《废土崛起》（校对版全本）作者：通吃道人.txt", "chapters": [1833, 1890]},
    {"book": "末日蟑螂", "file": "《末日蟑螂》作者：伟岸蟑螂.txt", "chapters": [2284, 2356]},
    {"book": "末世大回炉", "file": "《末世大回炉》（校对版全本）作者：二十二刀流.txt", "chapters": [1840, 1898]},
    {"book": "末世魔神游戏", "file": "《末世魔神游戏》（校对版全本）作者：石闻.txt", "chapters": [1, 198, 495, 990, 1485, 1782, 1940]},
    {"book": "黑暗血时代", "file": "黑暗血时代.txt", "chapters": [1, 186, 464, 928, 1391, 1670, 1818]},
]

def main():
    all_chapters = []
    for plan in EXPANSION_PLAN:
        txt_path = RAW_DIR / plan["file"]
        if not txt_path.exists():
            print(f"[SKIP] {plan['file']} not found")
            continue
        print(f"Loading {plan['book']}...")
        chapters = extract_chapters(str(txt_path))
        print(f"  Extracted {len(chapters)} chapters total")
        ch_map = {ch["num"]: ch for ch in chapters}
        available = sorted(ch_map.keys())

        for ch_num in plan["chapters"]:
            if ch_num in ch_map:
                ch = ch_map[ch_num]
            else:
                closest = min(available, key=lambda x: abs(x - ch_num))
                if abs(closest - ch_num) > 10:
                    print(f"  [WARN] ch{ch_num} not found, closest is ch{closest} (delta={abs(closest-ch_num)})")
                    continue
                ch_num = closest
                ch = ch_map[ch_num]

            body = ch["raw_body"]
            wc = len(body)
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
