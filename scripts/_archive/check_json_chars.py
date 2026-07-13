#!/usr/bin/env python3
"""检查JSON文件中导致解析失败的具体字符"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

fpath = 'data/processed/末世/scores/ai_annotate_batches/末世超级商人/scores_new_00.json'

with open(fpath, 'rb') as f:
    raw = f.read()

# Find the error location (char 267)
print(f"File size: {len(raw)} bytes")
print(f"Bytes around char 267:")
# Show bytes around position 267
start = max(0, 260)
end = min(len(raw), 280)
for i in range(start, end):
    b = raw[i]
    ch = chr(b) if 32 <= b < 127 else f'\\x{b:02x}'
    print(f"  pos {i}: byte=0x{b:02x} char={ch}")

# Try to decode as UTF-8 and check what's at the error position
text = raw.decode('utf-8')
print(f"\nText around error (chars 260-275):")
for i in range(260, min(len(text), 275)):
    ch = text[i]
    print(f"  char {i}: U+{ord(ch):04X} = '{ch}'")

# Check if there are unescaped ASCII double quotes inside string values
print(f"\nLine 12 content:")
lines = text.split('\n')
line12 = lines[11] if len(lines) > 11 else ""
print(f"  {line12}")
print(f"\n  Hex of each char in line 12:")
for i, ch in enumerate(line12):
    if ord(ch) > 127 or ch == '"':
        print(f"    pos {i}: U+{ord(ch):04X} = '{ch}'")
