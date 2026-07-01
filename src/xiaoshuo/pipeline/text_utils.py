# -*- coding: utf-8 -*-
"""
text_utils.py — 文本处理公共库 (SSOT)
=====================================
收敛 pipeline 中 8+ 个文件重复定义的文本处理函数。
所有管线模块的文本切分/计数/清洗统一走这里。

用法:
  from xiaoshuo.pipeline.text_utils import (
      count_chinese, split_paragraphs, split_sentences,
      read_file_multi_encoding, parse_cn_num,
  )
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Union


# ============================================================
# 中文字符统计 (原 8 个文件各自定义的 _count_chinese)
# ============================================================

def count_chinese(text: str) -> int:
    """统计中文字符数。

    Returns:
        text 中 \\u4e00-\\u9fff 范围内的字符数。
    """
    return sum(1 for c in text if '\u4e00' <= c <= '\u9fff')


# ============================================================
# 段落分割 (原 rhythm_analyzer._split_paragraphs + style_dna._split_paragraphs)
# ============================================================

# 双换行分割 (标准格式)
_PARA_SPLIT_DOUBLE = re.compile(r'\n\s*\n')
# 单换行分割 (回退模式)
_PARA_SPLIT_SINGLE = re.compile(r'\n')


def split_paragraphs(text: str, wc_hint: int = 0) -> list[str]:
    """双模式段落分割。

    优先使用双换行 (\\n\\n) 分割。如果结果段落数过少 (相对于字数提示)，
    回退到单换行分割，兼容单换行格式的文件。

    Args:
        text: 待分割文本
        wc_hint: 字数提示 (用于判断是否回退到单换行)，0 表示不回退

    Returns:
        非空段落列表 (已 strip)
    """
    paras = [p.strip() for p in _PARA_SPLIT_DOUBLE.split(text) if p.strip()]
    if wc_hint and len(paras) < max(1, wc_hint / 200):
        paras = [p.strip() for p in _PARA_SPLIT_SINGLE.split(text) if p.strip()]
    return paras


# ============================================================
# 句子分割 (原 style_dna._split_sentences + five_dimension_check._split_sentences)
# ============================================================

def split_sentences(text: str, min_len: int = 2) -> list[str]:
    """中文分句 (按。！？；…!? 分割)。

    Args:
        text: 待分割文本
        min_len: 最小句子长度 (过滤过短碎片)，默认 2

    Returns:
        非空句子列表 (已 strip)
    """
    # 去除多余空白行
    text = re.sub(r'\n+', '\n', text).strip()
    # 按句末标点分割
    parts = re.split(r'[。！？；…!?\n]+', text)
    return [s.strip() for s in parts if s.strip() and len(s.strip()) >= min_len]


# ============================================================
# 多编码文件读取 (原 rhythm_analyzer.extract_chapters 中的内联逻辑)
# ============================================================

def read_file_multi_encoding(filepath: Union[str, Path]) -> str:
    """多编码读取文件 (utf-8 → gbk → utf-16-le → utf-16-be)。

    Args:
        filepath: 文件路径

    Returns:
        文件文本内容

    Raises:
        ValueError: 所有编码均无法解码
    """
    for enc in ["utf-8", "gbk", "utf-16-le", "utf-16-be"]:
        try:
            return Path(filepath).read_text(encoding=enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError(f"Cannot decode {filepath}")


# ============================================================
# 中文数字解析 (原 rhythm_analyzer._parse_cn_num)
# ============================================================

_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "两": 2}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}


def parse_cn_num(s: str) -> int:
    """解析中文数字 (如 "一百二十三" → 123)。

    支持纯数字字符串、中文数字、混合写法。

    Args:
        s: 数字字符串

    Returns:
        解析后的整数
    """
    if not s:
        return 0
    # 纯数字直接返回
    try:
        return int(s)
    except ValueError:
        pass
    # 中文数字解析
    result = 0
    current = 0
    for ch in s:
        if ch in _CN_DIGITS:
            current = _CN_DIGITS[ch]
        elif ch in _CN_UNITS:
            unit = _CN_UNITS[ch]
            current = (current or 1) * unit
            result += current
            current = 0
    result += current
    return result if result > 0 else len(s)  # fallback


# ============================================================
# 感叹号密度计算 (原 rhythm_analyzer 内联逻辑)
# ============================================================

_EXCLAM_PAT = re.compile(r'[！!？?]')


def count_exclamations(text: str) -> int:
    """统计感叹号和问号数量 (情绪强度信号)。"""
    return len(_EXCLAM_PAT.findall(text))


# ============================================================
# 对话提取 (原 rhythm_analyzer.DIALOGUE_PAT)
# ============================================================

_DIALOGUE_PAT = re.compile(
    r'[「『"\u201c\u300c\u300e](.+?)[」』"\u201d\u300d\u300f]|'
    r'[^\n]*[:：]["\u201c].+["\u201d]'
)


def extract_dialogues(text: str) -> list[str]:
    """提取对话内容 (中文引号 + 西文引号 + 角色:格式)。"""
    return [m.group() for m in _DIALOGUE_PAT.finditer(text)]


def dialogue_char_count(text: str) -> int:
    """统计对话字符总数。"""
    return sum(len(m.group()) for m in _DIALOGUE_PAT.finditer(text))
