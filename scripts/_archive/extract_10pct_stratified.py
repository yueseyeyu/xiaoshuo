#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Stage 1: 从3本书中按黄金分层比例抽取10%章节，供AI盲评。

分层比例: Opening 3% / Rising 27% / Mid 30% / Climax 30% / Ending 10%
采样率: 10% (每层内部按等间隔抽取)
"""
import json, sys, math, random
from pathlib import Path
from xiaoshuo.pipeline.rhythm_analyzer import extract_chapters

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

RAW_DIR = Path("data/raw/novels/末世")

BOOKS = [
    {"book": "废土崛起", "file": "《废土崛起》（校对版全本）作者：通吃道人.txt"},
    {"book": "末日蟑螂", "file": "《末日蟑螂》作者：伟岸蟑螂.txt"},
    {"book": "末世大回炉", "file": "《末世大回炉》（校对版全本）作者：二十二刀流.txt"},
]

# 黄金分层比例
STRATA = [
    {"name": "Opening", "start": 0.00, "end": 0.03, "ratio": 0.03},
    {"name": "Rising",  "start": 0.03, "end": 0.30, "ratio": 0.27},
    {"name": "Mid",     "start": 0.30, "end": 0.60, "ratio": 0.30},
    {"name": "Climax",  "start": 0.60, "end": 0.90, "ratio": 0.30},
    {"name": "Ending",  "start": 0.90, "end": 1.00, "ratio": 0.10},
]

SAMPLE_RATE = 0.10  # 10%采样

def stratified_sample(chapters, sample_rate=0.10):
    """按黄金分层比例从章节列表中分层采样。
    
    chapters: list of dicts with 'num' key, sorted by num
    returns: list of (ch_num, stratum_name) tuples
    """
    total = len(chapters)
    if total == 0:
        return []
    
    sorted_chs = sorted(chapters, key=lambda c: c["num"])
    all_nums = [c["num"] for c in sorted_chs]
    
    sampled = []
    for stratum in STRATA:
        start_idx = int(total * stratum["start"])
        end_idx = int(total * stratum["end"])
        if end_idx <= start_idx:
            continue
        
        stratum_chs = all_nums[start_idx:end_idx]
        n_sample = max(1, math.ceil(len(stratum_chs) * sample_rate))
        
        # 等间隔采样
        if len(stratum_chs) <= n_sample:
            selected = stratum_chs
        else:
            step = len(stratum_chs) / n_sample
            indices = [int(i * step) for i in range(n_sample)]
            # 去重并保证不超范围
            indices = sorted(set(min(i, len(stratum_chs)-1) for i in indices))
            selected = [stratum_chs[i] for i in indices]
        
        for ch_num in selected:
            sampled.append((ch_num, stratum["name"]))
        
        print(f"  {stratum['name']}: {len(stratum_chs)}ch → sampled {len(selected)}")
    
    return sampled

def main():
    all_results = {}
    
    for book_info in BOOKS:
        book = book_info["book"]
        txt_path = RAW_DIR / book_info["file"]
        
        if not txt_path.exists():
            print(f"[SKIP] {book_info['file']} not found")
            continue
        
        print(f"\n=== {book} ===")
        chapters = extract_chapters(str(txt_path))
        print(f"Total chapters: {len(chapters)}")
        
        sampled = stratified_sample(chapters, SAMPLE_RATE)
        print(f"Total sampled: {len(sampled)} chapters")
        
        # 构建章节内容
        ch_map = {ch["num"]: ch for ch in chapters}
        scored_chapters = []
        for ch_num, stratum in sampled:
            ch = ch_map.get(ch_num)
            if not ch:
                continue
            body = ch["raw_body"]
            wc = len(body)
            # 截取前3000字（与LLM评分一致）
            if len(body) > 3000:
                body = body[:3000]
            scored_chapters.append({
                "book": book,
                "ch_num": ch_num,
                "stratum": stratum,
                "wc": wc,
                "body": body,
            })
        
        all_results[book] = scored_chapters
        print(f"Prepared: {len(scored_chapters)} chapters with text")
    
    # 保存
    output = Path("scripts/stage1_10pct_chapters.json")
    flat = []
    for book, chs in all_results.items():
        flat.extend(chs)
    
    with open(output, "w", encoding="utf-8") as f:
        json.dump(flat, f, ensure_ascii=False, indent=2)
    
    print(f"\n=== Summary ===")
    print(f"Total chapters extracted: {len(flat)}")
    for book, chs in all_results.items():
        strata_count = {}
        for ch in chs:
            strata_count[ch["stratum"]] = strata_count.get(ch["stratum"], 0) + 1
        print(f"  {book}: {len(chs)}ch | {strata_count}")
    print(f"Saved to: {output}")

if __name__ == "__main__":
    main()
