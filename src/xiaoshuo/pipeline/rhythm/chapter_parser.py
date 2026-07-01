# -*- coding: utf-8 -*-
"""
chapter_parser.py — 章节提取模块
==================================
从小说文本中提取章节，支持多种格式:
  - 第X章 (标准格式, 95%)
  - 序章 + 章X (混合格式)
  - 纯数字分章 (独立数字行)
"""
from __future__ import annotations

import re
from pathlib import Path

from xiaoshuo.pipeline.text_utils import (
    split_paragraphs as _split_paragraphs,
    parse_cn_num as _parse_cn_num,
    read_file_multi_encoding,
)


def extract_chapters(filepath):
    """Extract chapters. Supports: 第X章 / 序章+章X / 纯数字分章.
    Returns [{num, title, text, wc, paragraphs}]"""
    text = read_file_multi_encoding(filepath)

    cn_nums = r"[一二三四五六七八九十百千零\d]+"

    # Try standard 第X章 format first (95% of novels)
    pattern1 = r"(第" + cn_nums + r"章\s*[^\n]*)"
    parts = re.split(pattern1, text)
    if len(parts) >= 5:
        return _build_chapters(parts)
    # Fallback: mixed format (序章 + 章X, e.g. 狩魔手记)
    pattern2 = r"(序章\s*[^\n]*|章" + cn_nums + r"\s*[^\n]*)"
    parts = re.split(pattern2, text)
    if len(parts) >= 5:
        return _build_chapters(parts)
    # Fallback: standalone number headers (e.g. 限制级末日症候)
    pattern3 = r"(^[ \t]*\d{1,4}[ \t]+[^\d][^\n]*)"
    parts = re.split(pattern3, text, flags=re.MULTILINE)
    if len(parts) >= 5:
        return _build_chapters(parts)
    # Fallback: bare number-only lines — validate with surrounding context
    pattern4 = r"(^[ \t]*\d{1,4}[ \t]*$)"
    candidates = list(re.finditer(pattern4, text, flags=re.MULTILINE))
    valid = []
    for m in candidates:
        line = m.group(0).strip()
        if line.isdigit() and 1900 <= int(line) <= 2099:
            continue
        start, end = m.start(), m.end()
        before = text[max(0, start-50):start].strip()
        after = text[end:min(len(text), end+50)].strip()
        if len(after) < 20:
            continue
        valid.append(m)
    if len(valid) >= 3:
        parts = []
        last = 0
        for m in valid:
            parts.append(text[last:m.start()])
            parts.append(m.group(0))
            last = m.end()
        parts.append(text[last:])
        return _build_chapters(parts)

    return []


def _build_chapters(parts):
    """Convert re.split() parts into chapter dicts."""
    chapters = []
    for i in range(1, len(parts), 2):
        header = parts[i].strip()
        body = parts[i+1].strip() if i+1 < len(parts) else ""
        pure_text = body.replace("\n", "").replace(" ", "")
        if len(pure_text) < 50:
            continue

        ch_num = 0
        for regex in [
            r"第([一二三四五六七八九十百千零\d]+)章",
            r"序章",
            r"章([一二三四五六七八九十百千零\d]+)",
            r"^\s*(\d{1,4})\s",
            r"^\s*(\d{1,4})\s*$",
        ]:
            m = re.search(regex, header)
            if m:
                if "序章" in m.group():
                    ch_num = 0
                else:
                    num_str = m.group(1).strip()
                    try:
                        ch_num = int(num_str)
                    except (ValueError, TypeError):
                        ch_num = _parse_cn_num(num_str)
                break

        paragraphs = _split_paragraphs(body, len(pure_text))
        chapters.append({
            "num": ch_num, "title": header, "text": body[:3000],
            "wc": len(pure_text), "para_count": len(paragraphs),
            "raw_body": body,
        })

    # Fix zero-numbered chapters (prologues get sequential numbers)
    offset = 0
    for ch in chapters:
        if ch["num"] == 0:
            offset += 1
            ch["num"] = offset
    return chapters
