#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Convert all novel txt files to UTF-8. Also check CSV encoding."""
import os, sys
from pathlib import Path

PROJECT = Path("d:/Code/xiaoshuo")
RAW = PROJECT / "data" / "raw" / "novels"
OUT = PROJECT / "scripts" / "encoding_convert_result.txt"

L = []
def w(m): L.append(str(m))

def detect_encoding(filepath):
    """Detect encoding by trying UTF-8 first, then GB18030"""
    raw = open(filepath, 'rb').read(4096)
    # Check BOM
    if raw[:3] == b'\xef\xbb\xbf':
        return 'utf-8-sig'
    if raw[:2] == b'\xff\xfe':
        return 'utf-16-le'
    if raw[:2] == b'\xfe\xff':
        return 'utf-16-be'
    # Try UTF-8
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
    return 'unknown'

def convert_file(filepath):
    """Convert a single file to UTF-8 if needed"""
    enc = detect_encoding(filepath)
    if enc in ('utf-8', 'utf-8-sig'):
        return enc, False, 0
    if enc in ('utf-16-le', 'utf-16-be'):
        text = open(filepath, 'r', encoding=enc).read()
        size = len(text)
        open(filepath, 'w', encoding='utf-8').write(text)
        return enc, True, size
    if enc == 'gb18030':
        text = open(filepath, 'r', encoding='gb18030', errors='replace').read()
        size = len(text)
        open(filepath, 'w', encoding='utf-8').write(text)
        return enc, True, size
    return enc, False, 0

# 1. Convert all txt files in raw/novels
w("=" * 60)
w("Step 1: Convert novel txt files")
w("=" * 60)

converted = 0
already_utf8 = 0
failed = 0

for root, dirs, files in os.walk(RAW):
    for fname in files:
        if not fname.endswith('.txt'):
            continue
        fpath = Path(root) / fname
        rel = fpath.relative_to(RAW)
        enc, was_converted, size = convert_file(fpath)
        if was_converted:
            converted += 1
            w(f"  CONVERTED: {rel} ({enc} -> utf-8, {size} chars)")
        elif enc in ('utf-8', 'utf-8-sig'):
            already_utf8 += 1
        else:
            failed += 1
            w(f"  FAILED: {rel} (encoding: {enc})")

w(f"\n  Total: {converted} converted, {already_utf8} already UTF-8, {failed} failed")

# 2. Check CSV files in data/processed and data/golden
w(f"\n{'='*60}")
w("Step 2: Check CSV encoding (data/processed + data/golden)")
w("=" * 60)

csv_dirs = [
    PROJECT / "data" / "processed",
    PROJECT / "data" / "golden",
]

csv_converted = 0
csv_ok = 0
csv_failed = 0

for base in csv_dirs:
    if not base.exists():
        continue
    for root, dirs, files in os.walk(base):
        for fname in files:
            if not fname.endswith('.csv'):
                continue
            fpath = Path(root) / fname
            enc = detect_encoding(fpath)
            if enc in ('utf-8', 'utf-8-sig'):
                csv_ok += 1
            elif enc in ('gb18030', 'utf-16-le', 'utf-16-be'):
                try:
                    text = open(fpath, 'r', encoding=enc, errors='replace').read()
                    open(fpath, 'w', encoding='utf-8-sig').write(text)
                    csv_converted += 1
                    rel = fpath.relative_to(PROJECT)
                    w(f"  CONVERTED: {rel} ({enc} -> utf-8-sig)")
                except Exception as e:
                    csv_failed += 1
                    w(f"  FAILED: {fname} ({enc}): {e}")
            else:
                csv_failed += 1

w(f"\n  Total: {csv_converted} converted, {csv_ok} already UTF-8, {csv_failed} failed")

# 3. Check JSON files
w(f"\n{'='*60}")
w("Step 3: Check JSON encoding")
w("=" * 60)

json_dirs = [
    PROJECT / "data" / "reports",
    PROJECT / "data" / "processed",
    PROJECT / "data" / "golden",
    PROJECT / "data" / "raw",
]

json_ok = 0
json_converted = 0
json_failed = 0

for base in json_dirs:
    if not base.exists():
        continue
    for root, dirs, files in os.walk(base):
        for fname in files:
            if not fname.endswith('.json'):
                continue
            fpath = Path(root) / fname
            enc = detect_encoding(fpath)
            if enc in ('utf-8', 'utf-8-sig'):
                json_ok += 1
            elif enc in ('gb18030', 'utf-16-le', 'utf-16-be'):
                try:
                    text = open(fpath, 'r', encoding=enc, errors='replace').read()
                    open(fpath, 'w', encoding='utf-8').write(text)
                    json_converted += 1
                except:
                    json_failed += 1
            else:
                json_failed += 1

w(f"\n  Total: {json_converted} converted, {json_ok} already UTF-8, {json_failed} failed")

# Summary
w(f"\n{'='*60}")
w("SUMMARY")
w("=" * 60)
w(f"Novel txt: {converted} converted, {already_utf8} ok, {failed} failed")
w(f"CSV files: {csv_converted} converted, {csv_ok} ok, {csv_failed} failed")
w(f"JSON files: {json_converted} converted, {json_ok} ok, {json_failed} failed")

with open(OUT, 'w', encoding='utf-8') as f:
    f.write("\n".join(L))
