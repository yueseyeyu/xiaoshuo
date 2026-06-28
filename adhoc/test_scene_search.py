#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Quick smoke test for scene_search module."""
import sys
sys.path.insert(0, ".")

from xiaoshuo.pipeline.scene_search import (
    _split_scenes, _load_rhythm_data, _analyze_scene_technique,
)
from xiaoshuo.pipeline.rhythm_analyzer import extract_chapters

# Test 1: scene splitting
text = "第一段内容。\n\n第二段内容。\n\n第三段内容很长" + "x" * 300
scenes = _split_scenes(text)
print(f"[OK] 场景切分: {len(scenes)} scenes")
for i, s in enumerate(scenes):
    print(f"  scene {i}: {len(s)} chars, preview={s[:50]}...")

# Test 2: rhythm data loading
rhythm = _load_rhythm_data("末世", "《异兽迷城》（校对版全本）")
print(f"[OK] 节奏数据: {len(rhythm)} chapters loaded, keys={list(rhythm.keys())[:5]}")
if rhythm:
    first_key = list(rhythm.keys())[0]
    ch1 = rhythm[first_key]
    print(f"  ch{first_key}: emotion={ch1['emotion']}, pace={ch1['pace']}, conflict={ch1['conflict_level']}")

# Test 3: technique analysis
if rhythm:
    tech = _analyze_scene_technique(rhythm[first_key])
    print(f"[OK] 技法分析: {tech}")

# Test 4: chapter extraction
chapters = extract_chapters("data/raw/novels/末世/《异兽迷城》（校对版全本）.txt")
print(f"[OK] 章节提取: {len(chapters)} chapters")
if chapters:
    ch = chapters[0]
    print(f"  ch0: num={ch['num']}, wc={ch['wc']}, text_preview={ch['text'][:80]}...")
    scenes = _split_scenes(ch["text"])
    print(f"  scenes from ch0: {len(scenes)}")

print("\n[OK] 全部测试通过")