#!/usr/bin/env python3
"""修复末世超级商人JSON文件中的未转义双引号"""
import json, re, sys
sys.stdout.reconfigure(encoding='utf-8')

files = [
    'data/processed/末世/scores/ai_annotate_batches/末世超级商人/scores_new_00.json',
    'data/processed/末世/scores/ai_annotate_batches/末世超级商人/scores_new_01.json',
]

for fpath in files:
    print(f"\n=== 修复 {fpath} ===")
    with open(fpath, 'r', encoding='utf-8') as f:
        raw = f.read()
    
    # 策略: 在ai_analysis的值中，将未转义的ASCII双引号替换为全角双引号
    # 匹配模式: "ai_analysis": "...内容包含"未转义引号"..."
    # 我们需要找到ai_analysis的值范围，然后修复其中的未转义引号
    
    # 更简单的方法: 手动解析每行，找到ai_analysis行，修复其中的引号
    lines = raw.split('\n')
    fixed_lines = []
    for line in lines:
        if '"ai_analysis"' in line:
            # 找到 "ai_analysis": " 的位置
            # 值从第一个 " 后的 " 开始，到最后一个 " 结束
            # 中间的 " 需要替换为 \"
            # 找到 key 后的第一个 " (值开始) 和最后一个 " (值结束)
            match = re.match(r'^(\s*"ai_analysis":\s*")(.*)("\s*,?\s*)$', line)
            if match:
                prefix = match.group(1)
                value = match.group(2)
                suffix = match.group(3)
                # 将值中的未转义 " 替换为全角 ""
                fixed_value = value.replace('"', '\u201c').replace('"', '\u201d')
                # Actually just replace all unescaped " with full-width
                fixed_value = value.replace('"', '\u201d')  # close quote for all
                # Better: replace pairs
                # Count unescaped quotes
                count = value.count('"')
                if count > 0:
                    print(f"  发现 {count} 个未转义双引号")
                    # Replace odd-positioned with left quote, even with right
                    result = []
                    quote_count = 0
                    for ch in value:
                        if ch == '"':
                            if quote_count % 2 == 0:
                                result.append('\u201c')  # left double quote
                            else:
                                result.append('\u201d')  # right double quote
                            quote_count += 1
                        else:
                            result.append(ch)
                    fixed_value = ''.join(result)
                line = prefix + fixed_value + suffix
        fixed_lines.append(line)
    
    fixed = '\n'.join(fixed_lines)
    
    # Verify the fix
    try:
        data = json.loads(fixed)
        print(f"  修复成功! {len(data)} 章节")
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(fixed)
        print(f"  已保存到原文件")
        for item in data:
            print(f"  ch={item['ch_num']}, intensity={item['ai_intensity']}, analysis={item['ai_analysis'][:50]}")
    except json.JSONDecodeError as e:
        print(f"  修复失败: {e}")
        print(f"  修复后内容:\n{fixed[:500]}")
