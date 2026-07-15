#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
v815_verify_data_source.py — 验证v8.14数据是否真的是temp=0.0
=============================================================
对5章重新评分(temp=0.0 + prev_context)，与v8.14数据文件对比。
如果分数完全一致 → v8.14数据是temp=0.0生成的(GLM错了)
如果分数不同 → 需要进一步调查

用法:
  $env:PYTHONUTF8=1
  D:\miniconda3\envs\llm-shared\python.exe scripts/v815_verify_data_source.py
"""
import sys, os
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
os.environ["PYTHONUTF8"] = "1"

import json, csv, re
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

GENRE = "末世"

def main():
    from xiaoshuo.pipeline.llm_batch_score import llm_score_rubric, extract_chapters, INDEX_PATH, NOVELS_DIR

    # Load v8.14 data
    v814_path = PROJECT_ROOT / "data" / "reports" / "末世" / "v8.14_reference_scoring_data.json"
    with open(v814_path, "r", encoding="utf-8") as f:
        v814 = json.load(f)
    v814_results = v814.get("results", [])

    # Build lookup: (book, ch_num) -> v8.14 abs scores
    v814_lookup = {}
    for r in v814_results:
        key = (r.get("book", ""), r.get("ch_num", 0))
        v814_lookup[key] = {
            "abs_i": r.get("fresh_abs_intensity"),
            "abs_r": r.get("fresh_abs_retention"),
        }

    # Load golden CSV for book/ch_num
    golden_csv = PROJECT_ROOT / "data" / "golden" / GENRE / "tier3" / "human_golden_merged.csv"
    with open(golden_csv, "r", encoding="utf-8-sig") as f:
        golden_rows = list(csv.DictReader(f))

    # Build book -> txt_path mapping
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

    # Pick 5 chapters from different books
    test_chapters = []
    seen_books = set()
    for row in golden_rows:
        book = row.get("book", "").strip()
        if book in seen_books or len(test_chapters) >= 5:
            continue
        ch_num = int(row.get("ch_num", 0))
        key = (book, ch_num)
        if key in v814_lookup and v814_lookup[key]["abs_i"] is not None:
            test_chapters.append((book, ch_num, row))
            seen_books.add(book)

    print(f"Verifying {len(test_chapters)} chapters (temp=0.0 + prev_context)", flush=True)
    print(f"Current llm_score_rubric default temperature: ", end="", flush=True)
    import inspect
    sig = inspect.signature(llm_score_rubric)
    print(f"{sig.parameters['temperature'].default}", flush=True)
    print(flush=True)

    # Build chapter cache
    _cache = {}
    matches = 0
    total = 0

    for book, ch_num, row in test_chapters:
        # Find txt
        txt_path = None
        for sn, fp in book_to_txt.items():
            if sn in book or book in sn:
                txt_path = fp
                break
        if txt_path is None:
            print(f"  {book} ch{ch_num}: TXT not found, skip", flush=True)
            continue

        if str(txt_path) not in _cache:
            _cache[str(txt_path)] = extract_chapters(txt_path)
        chapters = _cache[str(txt_path)]

        # Find chapter
        chapter = None
        ch_idx = None
        for i, ch in enumerate(chapters):
            if ch.get("num") == ch_num:
                chapter = ch
                ch_idx = i
                break
        if chapter is None:
            print(f"  {book} ch{ch_num}: chapter not found, skip", flush=True)
            continue

        text = chapter.get("raw_body", "")[:1200]

        # Build prev_context (same as v8.14 script)
        prev_context = ""
        if ch_idx > 0:
            prev_body = chapters[ch_idx - 1].get("raw_body", "")
            if prev_body:
                prev_context = prev_body[-200:].replace("\n", " ").strip()

        # Run with temp=0.0 + prev_context (same as v8.14 script)
        result = llm_score_rubric(text, ch_num, prev_context=prev_context, temperature=0.0)

        v814_abs = v814_lookup[(book, ch_num)]
        new_i = float(result["intensity"]) if result else None
        new_r = float(result["retention"]) if result else None
        old_i = v814_abs["abs_i"]
        old_r = v814_abs["abs_r"]

        match_i = new_i == old_i if new_i and old_i else False
        match_r = new_r == old_r if new_r and old_r else False
        match = match_i and match_r
        total += 1
        if match:
            matches += 1

        print(f"  {book} ch{ch_num}: v8.14(i={old_i},r={old_r}) vs new(i={new_i},r={new_r}) -> {'MATCH' if match else 'DIFF'}", flush=True)

    print(f"\n{'='*60}", flush=True)
    print(f"  Result: {matches}/{total} chapters match exactly", flush=True)
    if matches == total:
        print(f"  --> CONFIRMED: v8.14 data was generated with temp=0.0", flush=True)
        print(f"  --> GLM's claim that 'Bootstrap uses temp=0.1 data' is INCORRECT", flush=True)
        print(f"  --> The data difference (+0.904 vs -0.181) is due to prev_context, not temperature", flush=True)
    elif matches == 0:
        print(f"  --> MISMATCH: v8.14 data may NOT be temp=0.0. Need investigation.", flush=True)
    else:
        print(f"  --> PARTIAL MATCH: Some chapters match, some don't. Need investigation.", flush=True)


if __name__ == "__main__":
    main()
