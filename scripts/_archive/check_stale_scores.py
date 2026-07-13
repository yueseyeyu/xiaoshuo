#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""检查残留评分是否与新批次匹配"""
import sys, os, json
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.dirname(__file__))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

import ai_annotate
ai_annotate.BATCH_SIZE = 2
from ai_annotate import get_book_batch_dir

PROJECT_ROOT = Path(__file__).parent.parent

# 4本有残留评分的书
BOOKS_TO_CHECK = [
    "全球变异，从灾厄降临开始",
    "我在末世种个田",
    "重卡战车在末世",
    "长夜余火",
]

for book in BOOKS_TO_CHECK:
    bdir = get_book_batch_dir(book)
    print(f"\n{'='*60}")
    print(f"{book}")
    print(f"{'='*60}")
    
    new_files = sorted(bdir.glob("new_*.json"))
    score_files = sorted(bdir.glob("scores_*.json"))
    
    print(f"批次文件: {len(new_files)}个, 评分文件: {len(score_files)}个")
    
    # 构建 new_ 文件的 ch_num 映射
    new_ch_map = {}  # batch_num -> [(ch_num, stratum, wc), ...]
    for nf in new_files:
        batch_num = int(nf.stem.split("_")[1])
        with open(nf, 'r', encoding='utf-8') as f:
            data = json.load(f)
        new_ch_map[batch_num] = [(d['ch_num'], d.get('stratum',''), d.get('wc',0)) for d in data]
    
    # 检查每个评分文件
    valid_scores = 0
    invalid_scores = 0
    invalid_details = []
    
    for sf in score_files:
        # scores_new_XX.json -> 取最后一段数字
        batch_num = int(sf.stem.split("_")[-1])
        with open(sf, 'r', encoding='utf-8') as f:
            scores = json.load(f)
        
        if batch_num not in new_ch_map:
            print(f"  ❌ {sf.name}: 批次{batch_num}在新文件中不存在!")
            invalid_scores += len(scores)
            continue
        
        new_chs = new_ch_map[batch_num]
        new_ch_nums = set(ch[0] for ch in new_chs)
        
        for score in scores:
            ch_num = score.get('ch_num')
            if ch_num in new_ch_nums:
                # 检查stratum和wc是否匹配
                new_entry = next(ch for ch in new_chs if ch[0] == ch_num)
                if score.get('stratum') == new_entry[1] and score.get('wc') == new_entry[2]:
                    valid_scores += 1
                else:
                    invalid_scores += 1
                    invalid_details.append(f"    {sf.name} ch{ch_num}: stratum/wc不匹配 (score={score.get('stratum')}/{score.get('wc')} vs new={new_entry[1]}/{new_entry[2]})")
            else:
                invalid_scores += 1
                invalid_details.append(f"    {sf.name} ch{ch_num}: 不在新批次中 (新批次ch_nums={sorted(new_ch_nums)})")
    
    print(f"  有效评分: {valid_scores}")
    print(f"  无效评分: {invalid_scores}")
    if invalid_details:
        print(f"  无效详情 (前5条):")
        for d in invalid_details[:5]:
            print(d)
    
    if invalid_scores > 0:
        print(f"  → 需要清理全部{len(score_files)}个评分文件")
    else:
        print(f"  → 全部有效，保留")
