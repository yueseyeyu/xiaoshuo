#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""rerun_borda_t2.py — 重跑完整Borda排名(含Tier1+Tier2 LLM数据)"""
import sys, os, json
from pathlib import Path
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from xiaoshuo.pipeline.scoring.borda_ranker import process_genre

print("=" * 80)
print("重跑 Borda 排名 (Tier1 + Tier2 合并数据)")
print("=" * 80)

result = process_genre("末世")

if result:
    synth, output_dir = result
    print(f"\n✅ 完成!")
    print(f"输出: {output_dir}")
    
    # 读取排名结果
    borda_path = PROJECT_ROOT / "data" / "reports" / "末世" / "synthesis" / "末世_borda_ranking.json"
    if borda_path.exists():
        with open(borda_path, 'r', encoding='utf-8') as f:
            ranking = json.load(f)
        print(f"\n排名结果 ({len(ranking)}本):")
        for item in ranking:
            rank = item.get("consensus_rank", 0)
            name = item.get("book_name", "")[:30]
            score = item.get("total_borda", 0)
            dims = item.get("dim_ranks", {})
            print(f"  #{rank:2d} {name:<32s} borda={score:.1f}  dims={dims}")
else:
    print("❌ 失败")
