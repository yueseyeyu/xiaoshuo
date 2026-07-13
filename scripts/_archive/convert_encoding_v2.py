#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Convert all novel txt files to UTF-8 - v2 with full file detection"""
import os
from pathlib import Path

PROJECT = Path("d:/Code/xiaoshuo")
RAW = PROJECT / "data" / "raw" / "novels"
OUT = PROJECT / "scripts" / "encoding_convert_v2_result.txt"

L = []
def w(m): L.append(str(m))

def detect_encoding(filepath):
    """Detect encoding by reading entire file"""
    raw = open(filepath, 'rb').read()
    # Check BOM
    if raw[:3] == b'\xef\xbb\xbf':
        return 'utf-8-sig'
    if raw[:2] == b'\xff\xfe':
        return 'utf-16-le'
    if raw[:2] == b'\xfe\xff':
        return 'utf-16-be'
    # Try UTF-8 (strict)
    try:
        raw.decode('utf-8')
        return 'utf-8'
    except:
        pass
    # Try GB18030
    try:
        raw.decode('gb18030')
        return 'gb18030'
    except:
        pass
    # Try GBK
    try:
        raw.decode('gbk')
        return 'gbk'
    except:
        pass
    # Try Big5
    try:
        raw.decode('big5')
        return 'big5'
    except:
        pass
    # Try Latin-1 (always works but wrong for CJK)
    # Last resort: GB18030 with errors=replace
    try:
        raw.decode('gb18030', errors='replace')
        return 'gb18030-replace'
    except:
        return 'unknown'

def convert_file(filepath):
    """Convert a single file to UTF-8"""
    enc = detect_encoding(filepath)
    if enc in ('utf-8', 'utf-8-sig'):
        return enc, False, 0
    # Read with detected encoding
    if enc in ('utf-16-le', 'utf-16-be'):
        text = open(filepath, 'r', encoding=enc).read()
    elif enc in ('gb18030', 'gbk', 'big5'):
        text = open(filepath, 'r', encoding=enc).read()
    elif enc == 'gb18030-replace':
        text = open(filepath, 'r', encoding='gb18030', errors='replace').read()
    else:
        return enc, False, 0
    
    size = len(text)
    open(filepath, 'w', encoding='utf-8').write(text)
    return enc, True, size

# Convert all txt files
w("=" * 60)
w("Converting all novel txt files to UTF-8")
w("=" * 60)

converted = 0
already = 0
failed = 0

for root, dirs, files in os.walk(RAW):
    for fname in sorted(files):
        if not fname.endswith('.txt'):
            continue
        fpath = Path(root) / fname
        rel = fpath.relative_to(RAW)
        enc, was_converted, size = convert_file(fpath)
        if was_converted:
            converted += 1
            w(f"  CONVERTED: {rel} ({enc} -> utf-8, {size:,} chars)")
        elif enc in ('utf-8', 'utf-8-sig'):
            already += 1
        else:
            failed += 1
            w(f"  FAILED: {rel} (encoding: {enc})")

w(f"\n  Total: {converted} converted, {already} already UTF-8, {failed} failed")

# Verify: try reading all as UTF-8
w(f"\n{'='*60}")
w("Verification: read all as UTF-8")
w("=" * 60)

verify_ok = 0
verify_fail = 0
for root, dirs, files in os.walk(RAW):
    for fname in files:
        if not fname.endswith('.txt'):
            continue
        fpath = Path(root) / fname
        try:
            open(fpath, 'r', encoding='utf-8').read(1000)
            verify_ok += 1
        except:
            verify_fail += 1
            rel = fpath.relative_to(RAW)
            w(f"  STILL FAILS: {rel}")

w(f"\n  Verification: {verify_ok} ok, {verify_fail} failed")

with open(OUT, 'w', encoding='utf-8') as f:
    f.write("\n".join(L))
