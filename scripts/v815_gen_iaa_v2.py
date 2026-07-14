#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
v815_gen_iaa_v2.py — 用已有annotate_tool.html模板生成20章IAA标注材料
====================================================================
选章策略: S级10章(多本) + A级7章(废土崛起) + B级3章(末日蟑螂低分端)
复用已有工具的HTML/CSS/JS，仅替换章节JSON数据

用法:
  $env:PYTHONUTF8=1
  D:\miniconda3\envs\llm-shared\python.exe scripts/v815_gen_iaa_v2.py
"""
import sys, os
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
os.environ["PYTHONUTF8"] = "1"

import csv, json, re
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
GENRE = "末世"

def main():
    from xiaoshuo.pipeline.llm_batch_score import extract_chapters, INDEX_PATH, NOVELS_DIR

    # Tier mapping
    tier_map = {
        "地球游戏场": "S", "末世大回炉": "S", "异兽迷城": "S",
        "黑暗血时代": "S", "第一序列": "S", "长夜余火": "S", "末日乐园": "S",
        "废土崛起": "A",
        "末日蟑螂": "B",
    }

    # Load golden
    golden_csv = PROJECT_ROOT / "data" / "golden" / GENRE / "tier3" / "human_golden_merged.csv"
    with open(golden_csv, "r", encoding="utf-8-sig") as f:
        golden_rows = list(csv.DictReader(f))

    # Load v8.15 fresh scores
    v815_path = PROJECT_ROOT / "data" / "reports" / GENRE / "v8.15_verify_full_47.json"
    with open(v815_path, "r", encoding="utf-8") as f:
        v815 = json.load(f)
    v815_lookup = {(r["book"], r["ch_num"]): r for r in v815["results"]}

    # Build book -> txt mapping
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        index = json.load(f)
    novels = index.get("genres", {}).get(GENRE, {}).get("novels", [])
    book_to_txt = {}
    for novel in novels:
        txt_file = novel.get("file", "")
        for fp in NOVELS_DIR.glob(f"{GENRE}/*.txt"):
            if fp.name == txt_file:
                short_name = txt_file.replace(".txt", "").replace("《", "").replace("》", "")
                m = re.match(r"([^（(]+)", short_name)
                if m:
                    short_name = m.group(1).strip()
                book_to_txt[short_name] = fp
                break

    # Group by tier
    by_tier = {"S": [], "A": [], "B": []}
    for row in golden_rows:
        book = row.get("book", "").strip()
        ch_num = int(row.get("ch_num", 0))
        human_i = float(row.get("human_intensity", 5))
        human_r = float(row.get("human_retention", 5))
        tier = tier_map.get(book, "?")
        if tier not in by_tier:
            continue
        key = (book, ch_num)
        v = v815_lookup.get(key)
        llm_i = v["new_i"] if v else 0
        by_tier[tier].append({
            "book": book, "ch_num": ch_num,
            "human_i": human_i, "human_r": human_r,
            "llm_i": llm_i,
            "diff": abs(llm_i - human_i) if v else 0,
        })

    # Selection: S=10, A=7, B=3 = 20 total
    # For S: spread across multiple books (max 3 per book, prioritize high diff)
    # For A: all from 废土崛起 (only 1 A book)
    # For B: 3 from 末日蟑螂 (pick low/mid scores for low-end coverage)
    
    selected = []
    
    # S级: 10 chapters, max 3 per book, prioritize high LLM-human diff
    s_books = {}
    for e in sorted(by_tier["S"], key=lambda x: -x["diff"]):
        b = e["book"]
        if b not in s_books:
            s_books[b] = 0
        if s_books[b] < 3:
            selected.append(e)
            s_books[b] += 1
        if len(selected) >= 10:
            break
    
    # A级: 7 chapters from 废土崛起, spread across score range
    a_pool = sorted(by_tier["A"], key=lambda x: x["human_i"])
    # Pick spread: 2 low + 3 mid + 2 high
    a_low = [e for e in a_pool if e["human_i"] <= 3.5][:2]
    a_mid = [e for e in a_pool if 3.5 < e["human_i"] <= 6.5][:3]
    a_high = [e for e in a_pool if e["human_i"] > 6.5][:2]
    selected.extend(a_low + a_mid + a_high)
    
    # B级: 3 chapters from 末日蟑螂, pick low scores for low-end coverage
    b_low = sorted([e for e in by_tier["B"] if e["human_i"] <= 4], key=lambda x: x["human_i"])
    selected.extend(b_low[:3])

    selected.sort(key=lambda x: (x["book"], x["ch_num"]))
    
    # Count by tier
    from collections import Counter
    tier_counts = Counter(tier_map.get(s["book"], "?") for s in selected)
    book_counts = Counter(s["book"] for s in selected)
    print(f"Selected {len(selected)} chapters:", flush=True)
    print(f"  Tiers: {dict(tier_counts)}", flush=True)
    print(f"  Books: {dict(book_counts)}", flush=True)

    # Extract chapter texts
    _cache = {}
    chapters_json = []
    for s in selected:
        book = s["book"]
        ch_num = s["ch_num"]
        txt_path = None
        for sn, fp in book_to_txt.items():
            if sn in book or book in sn:
                txt_path = fp
                break
        if not txt_path:
            continue
        if str(txt_path) not in _cache:
            _cache[str(txt_path)] = extract_chapters(txt_path)
        chapters = _cache[str(txt_path)]
        chapter = None
        for ch in chapters:
            if ch.get("num") == ch_num:
                chapter = ch
                break
        if not chapter:
            continue
        text = chapter.get("raw_body", "")[:2000]
        chapters_json.append({
            "book": book,
            "ch_num": ch_num,
            "wc": len(text),
            "tier": tier_map.get(book, "?"),
            "body": text,
        })
        print(f"  {tier_map.get(book,'?')} {book} ch{ch_num} ({len(text)}字, h_i={s['human_i']})", flush=True)

    # Read existing annotate_tool.html template
    template_path = PROJECT_ROOT / "data" / "golden" / GENRE / "tier3" / "annotate_tool.html"
    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()

    # Replace the chapters JSON line
    # The existing line starts with "const chapters = [{..."
    # Find it and replace everything up to the next line that starts with non-JSON
    import re as _re
    # Find "const chapters = " and replace the entire array
    pattern = r'const chapters = \[.*?\];\s*\n'
    match = _re.search(pattern, template, _re.DOTALL)
    if not match:
        # Try without semicolon
        pattern = r'const chapters = \[.*?\]\s*\n'
        match = _re.search(pattern, template, _re.DOTALL)
    if match:
        new_chapters_line = "const chapters = " + json.dumps(chapters_json, ensure_ascii=False) + ";\n"
        html = template[:match.start()] + new_chapters_line + template[match.end():]
    else:
        print("WARNING: Could not find chapters line in template, using simple HTML", flush=True)
        # Fallback: generate simple HTML
        html = "<html><body><p>ERROR: Could not find chapters in template</p></body></html>"

    # Update title
    html = html.replace("网文评分标注工具 — 54章Tier3校准", "网文评分标注工具 — 20章IAA(朋友标注)")
    html = html.replace("54章Tier3校准", "20章IAA朋友标注")

    out_path = PROJECT_ROOT / "data" / "golden" / GENRE / "tier3" / "iaa_annotation_tool.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nHTML tool: {out_path}", flush=True)
    print(f"Send this file to your friend. He opens it in a browser.", flush=True)


if __name__ == "__main__":
    main()
