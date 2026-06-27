#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Scan data/raw/novels and generate library_data.json for frontend prototype."""
import json
import os
import re
from pathlib import Path

ROOT = Path("data/raw/novels")
OUT = Path("prototype/library_data.json")

tag_pool = {
    "末世": ["末世", "系统", "囤货", "种田", "进化", "生存", "无敌", "打脸", "丧尸", "废土"],
    "无限流": ["无限流", "悬疑", "智斗", "副本", "推理", "惊悚", "生存", "轮回"],
    "科幻": ["科幻", "星际", "进化", "文明", "生存", "机甲", "未来"],
    "悬疑": ["悬疑", "惊悚", "灵异", "推理", "破案", "智斗", "反转"],
    "仙侠": ["仙侠", "修仙", "东方玄幻", "升级", "奇遇", "宗门", "长生"],
    "历史": ["历史", "架空", "权谋", "种田", "穿越", "争霸"],
    "奇幻": ["奇幻", "魔法", "异世界", "冒险", "升级", "种族"],
    "洪荒": ["洪荒", "神话", "东方玄幻", "封神", "西游", "圣人"],
    "都市": ["都市", "异能", "职场", "系统", "重生", "日常"],
    "同人": ["同人", "衍生", "综漫", "穿越", "爽文", "魔改"],
}

books = []

def clean_title(filename):
    # Remove 《》, parenthesis, author suffix, _and suffix, .txt
    title = re.sub(r"[《》]|（.*?）|\(.*?\)|作者[：:][^\.]+|_and[^\.]*|\.txt$", "", filename)
    return title.strip() or filename.replace(".txt", "")

def extract_author(filename):
    m = re.search(r"作者[：:]([^_（\.]+)", filename)
    if m:
        return m.group(1).strip()
    return "佚名"

for genre_dir in sorted(ROOT.iterdir()):
    if not genre_dir.is_dir():
        continue
    genre = genre_dir.name
    for fpath in sorted(genre_dir.iterdir()):
        if fpath.suffix != ".txt":
            continue
        size = fpath.stat().st_size
        title = clean_title(fpath.name)
        author = extract_author(fpath.name)
        books.append({
            "title": title,
            "author": author,
            "genre": genre,
            "size_kb": round(size / 1024),
            "wordCount": round(size / 3.3),
            "file": fpath.name,
            "rhythm_csv": f"rhythm_{fpath.stem}.csv",
        })

genres = sorted({b["genre"] for b in books})

OUT.write_text(json.dumps({"genres": genres, "books": books}, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"[OK] Generated {OUT}: {len(books)} books across {len(genres)} genres")
