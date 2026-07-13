#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""fix_tier2_errors.py — 修复 Tier2 质检错误"""
import sys, os, json
from pathlib import Path
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent.parent
TIER2_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "scores" / "tier2_batches"

fixed_count = 0

# ============================================================
# 1. 修复 ANALYSIS LEN — 截断到100字以内
# ============================================================
print("=" * 60)
print("1. 修复 t2_analysis 超长 (>100字)")
print("=" * 60)

for bdir in sorted(TIER2_DIR.iterdir()):
    if not bdir.is_dir():
        continue
    
    for sf in sorted(bdir.glob("scores_new_*.json")):
        with open(sf, 'r', encoding='utf-8') as f:
            scores = json.load(f)
        
        modified = False
        for s in scores:
            analysis = s.get('t2_analysis', '')
            if len(analysis) > 100:
                # 截断到100字，在最后一个完整句子结束
                truncated = analysis[:100]
                # 尝试在最后一个句号/逗号处截断
                for sep in ['。', '，', '；', '、']:
                    last_sep = truncated.rfind(sep)
                    if last_sep > 50:
                        truncated = truncated[:last_sep + 1]
                        break
                s['t2_analysis'] = truncated
                modified = True
                print(f"  ✂️ {bdir.name}/{sf.name}: {len(analysis)}→{len(truncated)}字")
                fixed_count += 1
        
        if modified:
            with open(sf, 'w', encoding='utf-8') as f:
                json.dump(scores, f, ensure_ascii=False, indent=2)

# ============================================================
# 2. 修复 CH_NUM/WC MISMATCH — 从 new 文件同步正确值
# ============================================================
print(f"\n{'=' * 60}")
print("2. 修复 ch_num/wc 不匹配 (从 new 文件同步)")
print("=" * 60)

for bdir in sorted(TIER2_DIR.iterdir()):
    if not bdir.is_dir():
        continue
    
    for sf in sorted(bdir.glob("scores_new_*.json")):
        batch_num = int(sf.stem.split("_")[-1])
        nf = bdir / f"new_{batch_num:02d}.json"
        if not nf.exists():
            continue
        
        with open(nf, 'r', encoding='utf-8') as f:
            new_data = json.load(f)
        with open(sf, 'r', encoding='utf-8') as f:
            scores = json.load(f)
        
        if len(new_data) != len(scores):
            print(f"  ⚠️ {bdir.name}/{sf.name}: 章节数不匹配，跳过")
            continue
        
        modified = False
        for i, (n, s) in enumerate(zip(new_data, scores)):
            if s.get('ch_num') != n.get('ch_num'):
                print(f"  🔧 {bdir.name}/{sf.name} idx={i}: ch_num {s['ch_num']}→{n['ch_num']}")
                s['ch_num'] = n['ch_num']
                modified = True
                fixed_count += 1
            if s.get('wc') != n.get('wc'):
                print(f"  🔧 {bdir.name}/{sf.name} idx={i}: wc {s['wc']}→{n['wc']}")
                s['wc'] = n['wc']
                modified = True
                fixed_count += 1
        
        if modified:
            with open(sf, 'w', encoding='utf-8') as f:
                json.dump(scores, f, ensure_ascii=False, indent=2)

print(f"\n{'=' * 60}")
print(f"修复完成: 共修复 {fixed_count} 处")
