#!/usr/bin/env python3
"""检查JSON文件的编码和解析问题"""
import json

files = [
    'data/processed/末世/scores/ai_annotate_batches/末世超级商人/scores_new_00.json',
    'data/processed/末世/scores/ai_annotate_batches/末世超级商人/scores_new_01.json',
]

for fpath in files:
    print(f"\n=== {fpath} ===")
    # Check BOM
    with open(fpath, 'rb') as f:
        raw = f.read()
    print(f"文件大小: {len(raw)} bytes")
    print(f"前10字节(hex): {raw[:10].hex()}")
    if raw[:3] == b'\xef\xbb\xbf':
        print("⚠️ 检测到UTF-8 BOM!")
    else:
        print("无BOM")
    
    # Try different encodings
    for enc in ['utf-8', 'utf-8-sig', 'gbk', 'gb2312', 'gb18030']:
        try:
            with open(fpath, 'r', encoding=enc) as f:
                content = f.read()
            data = json.loads(content)
            print(f"✅ {enc}: 解析成功! {len(data)} 章节")
            for item in data:
                print(f"   ch={item['ch_num']}, intensity={item['ai_intensity']}, analysis={item['ai_analysis'][:40]}")
            break
        except json.JSONDecodeError as e:
            print(f"❌ {enc}: JSON错误 - {e}")
        except UnicodeDecodeError as e:
            print(f"❌ {enc}: 编码错误 - {e}")
