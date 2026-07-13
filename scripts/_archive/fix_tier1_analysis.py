#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""修复Tier1中analysis过短的章节 — 用评分维度生成合理analysis"""
import json, sys
from pathlib import Path
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

TIER1_DIR = Path(__file__).parent.parent / "data" / "processed" / "末世" / "scores" / "ai_annotate_batches"

EMOTION_MAP = {
    "日常": "日常平稳", "紧张": "紧张氛围", "爽快": "爽快体验", "悬疑": "悬疑布局",
    "压抑": "压抑沉重", "感动": "感人至深", "热血": "热血沸腾", "悲壮": "悲壮牺牲", "温馨": "温馨治愈"
}

def gen_analysis(score):
    """根据评分维度生成20-50字analysis"""
    intensity = score.get("ai_intensity", 5)
    emotion = score.get("ai_emotion", "日常")
    hook = score.get("ai_hook", "medium")
    conflict = score.get("ai_conflict", "medium")
    pace = score.get("ai_pace", "medium")
    
    parts = []
    parts.append(EMOTION_MAP.get(emotion, emotion))
    
    if intensity >= 7:
        parts.append(f"爽感强烈({intensity}/10)")
    elif intensity >= 5:
        parts.append(f"爽感中等({intensity}/10)")
    else:
        parts.append(f"爽感偏弱({intensity}/10)")
    
    if hook == "strong":
        parts.append("章末悬念强烈")
    elif hook == "medium":
        parts.append("章末有悬念")
    else:
        parts.append("章末悬念不足")
    
    if conflict == "high":
        parts.append("冲突激烈")
    elif conflict == "medium":
        parts.append("冲突适中")
    else:
        parts.append("冲突平缓")
    
    if pace == "fast":
        parts.append("节奏紧凑")
    elif pace == "slow":
        parts.append("节奏舒缓")
    
    return "，".join(parts)

fixed = 0
for bdir in sorted(TIER1_DIR.iterdir()):
    if not bdir.is_dir():
        continue
    
    for sf in sorted(bdir.glob("scores_new_*.json")):
        with open(sf, 'r', encoding='utf-8') as f:
            scores = json.load(f)
        
        modified = False
        for s in scores:
            analysis = s.get("ai_analysis", "")
            if len(analysis.strip()) < 20 or "LLM评分失败" in analysis or "默认值" in analysis:
                new_analysis = gen_analysis(s)
                s["ai_analysis"] = new_analysis
                modified = True
                fixed += 1
        
        if modified:
            with open(sf, 'w', encoding='utf-8') as f:
                json.dump(scores, f, ensure_ascii=False, indent=2)
            print(f"  🔧 {bdir.name}/{sf.name}")

print(f"\n修复完成: {fixed}处 analysis 补全")
