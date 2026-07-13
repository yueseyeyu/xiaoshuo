#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""检查哪些有效评分被误清了"""
import sys, os
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent.parent
BATCH_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "scores" / "ai_annotate_batches"

# 审计结果中"✅有效"且有评分的书
valid_with_scores = {
    "末世之深渊召唤师": {"total": 1560, "expected": 158, "scored": 158, "valid": 158, "coverage": "100%"},
    "末世大回炉": {"total": 1937, "expected": 197, "scored": 197, "valid": 197, "coverage": "100%"},
    "末世魔神游戏": {"total": 1980, "expected": 200, "scored": 200, "valid": 200, "coverage": "100%"},
    "第一序列": {"total": 1260, "expected": 128, "scored": 44, "valid": 44, "coverage": "34.4%"},
    "重卡战车在末世": {"total": 914, "expected": 94, "scored": 50, "valid": 50, "coverage": "53.2%"},
    "恐慌沸腾": {"total": 1487, "expected": 151, "scored": 46, "valid": 46, "coverage": "30.5%"},
}

print("审计中判定为✅有效且有评分的书籍:")
print("=" * 80)
for book, info in valid_with_scores.items():
    bdir = BATCH_DIR / book if book != "废土崛起" else BATCH_DIR
    new_files = list(bdir.glob("new_*.json")) if bdir.exists() else []
    score_files = list(bdir.glob("scores_*.json")) if bdir.exists() else []

    # 检查batch文件是否被重新提取过（对比总数）
    batch_chs = set()
    for nf in new_files:
        import json
        try:
            with open(nf, 'r', encoding='utf-8') as f:
                for row in json.load(f):
                    if 'ch_num' in row:
                        batch_chs.add(int(row['ch_num']))
        except:
            pass

    print(f"\n{book}:")
    print(f"  审计: 总{info['total']}章, 采样{info['expected']}章, 旧评分{info['scored']}章({info['valid']}有效), 覆盖率{info['coverage']}")
    print(f"  当前: {len(new_files)}批, {len(score_files)}评分, 批次ch_num范围={min(batch_chs) if batch_chs else 'N/A'}-{max(batch_chs) if batch_chs else 'N/A'}")
    print(f"  批次ch_num数: {len(batch_chs)}")

    if len(score_files) == 0 and info['scored'] > 0:
        print(f"  ⚠️ 旧评分{info['scored']}章已被清理!")
    elif len(score_files) > 0:
        print(f"  评分文件仍在: {len(score_files)}个")
