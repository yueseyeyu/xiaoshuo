#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""
gen_rescore_prompts.py — 为S/A级书失败章节生成GLM评分指令(单文件版)

输出:
  data/golden/末世/tier3/rescore_prompts/
    └── {书名}_GLM评分指令.md   (评分标准+全部章节原文，一条指令搞定)

用法: D:\miniconda3\envs\llm-shared\python.exe scripts\gen_rescore_prompts.py
"""
import csv
import json
import re
import sys
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PROJECT_ROOT = Path(__file__).parent.parent
SCORES_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "scores"
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "novels" / "末世"
SNAPSHOT_PATH = PROJECT_ROOT / "data" / "reports" / "rankings" / "末世" / "v8.8_borda_snapshot_33books.json"
OUTPUT_DIR = PROJECT_ROOT / "data" / "golden" / "末世" / "tier3" / "rescore_prompts"

# S/A级书单
with open(SNAPSHOT_PATH, "r", encoding="utf-8") as f:
    _snapshot = json.load(f)
SA_BOOKS = [r["book"] for r in _snapshot["ranking"] if r["quality_tier"] in ("S", "A")]


def _cn2num(cn_str):
    """中文数字转阿拉伯数字，支持1-9999"""
    cn_map = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}
    if cn_str.isdigit():
        return int(cn_str)
    result = 0
    current = 0
    for ch in cn_str:
        if ch in cn_map:
            current = cn_map[ch]
        elif ch == "十":
            result += (current if current > 0 else 1) * 10
            current = 0
        elif ch == "百":
            result += (current if current > 0 else 1) * 100
            current = 0
        elif ch == "千":
            result += (current if current > 0 else 1) * 1000
            current = 0
    result += current
    return result if result > 0 else 0


def extract_chapters(raw_text):
    """从原始txt提取章节"""
    cn_nums = r"[一二三四五六七八九十百千零\d]+"
    pattern = r"(第" + cn_nums + r"章\s*[^\n]*)"
    parts = re.split(pattern, raw_text)
    chapters = {}
    if len(parts) < 5:
        return chapters
    for i in range(1, len(parts) - 1, 2):
        header = parts[i].strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        m = re.search(r"第(\d+)章", header)
        if m:
            ch_num = int(m.group(1))
        else:
            m2 = re.search(r"第([一二三四五六七八九十百千零]+)章", header)
            if m2:
                ch_num = _cn2num(m2.group(1))
            else:
                continue
        if ch_num > 0 and body:
            chapters[ch_num] = {"header": header, "body": body}
    return chapters


def read_raw_text(book_name):
    """读取原始小说txt"""
    raw_files = list(RAW_DIR.glob(f"*{book_name}*.txt"))
    if not raw_files:
        return ""
    for enc in ["utf-8", "gbk", "gb18030", "utf-16"]:
        try:
            return raw_files[0].read_text(encoding=enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return ""


def find_failed_chapters(book_name):
    """在_llm.csv中查找LLM解析/评分失败的章节"""
    llm_path = SCORES_DIR / f"{book_name}_llm.csv"
    if not llm_path.exists():
        return []
    failed = []
    fail_patterns = ["LLM解析失败", "LLM评分失败", "解析失败，使用默认值", "评分失败，使用默认值"]
    with open(llm_path, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            analysis = row.get("llm_analysis", "")
            if any(p in analysis for p in fail_patterns):
                ch = int(row.get("ch_num", 0))
                failed.append(ch)
    return sorted(failed)


def truncate_body(body, max_chars=3000):
    """截取章节正文，保留开头和结尾"""
    if len(body) <= max_chars:
        return body
    head = body[:max_chars // 2]
    tail = body[-max_chars // 2:]
    return head + "\n\n...(中间内容省略)...\n\n" + tail


def build_single_prompt(book_name, chapters, failed_chs):
    """构建单文件指令：评分标准 + 全部章节原文 + 输出要求"""

    available = [ch for ch in failed_chs if ch in chapters and len(chapters[ch].get("body", "")) >= 100]
    missing = [ch for ch in failed_chs if ch not in available]

    parts = []
    # ===== 评分标准 =====
    parts.append(f"""# {book_name} — LLM重评指令

你是网文评分专家。以下{len(available)}章因LLM评分失败需要重新打分。请逐章阅读全文，按下方标准评分。

## 评分维度

| 维度 | 取值 | 说明 |
|------|------|------|
| intensity | 1-10整数 | 爽感强度。1-2=平淡铺垫, 3-4=小爽, 5-6=明显爽感, 7-8=强烈高光, 9-10=巅峰体验 |
| retention | 1-10整数 | 读者留存。1-2=弃书, 3-4=跳读, 5-6=普通, 7-8=想追, 9-10=熬夜看 |
| hook | weak/medium/strong | 章末钩子强度。weak=无悬念, medium=有悬念, strong=强烈期待下一章 |
| pace | slow/medium/fast | 叙事节奏。slow=舒缓铺垫, medium=适中, fast=紧凑高潮 |
| conflict | low/medium/high | 冲突激烈程度。low=无冲突, medium=一般冲突, high=激烈对抗 |
| emotion | 以下之一 | 主导情绪: 日常/紧张/爽快/悬疑/压抑/感动/悲壮/温馨/热血 |
| analysis | 20-80字中文 | 评分理由，概括本章核心爽点/问题 |

## 硬性规则
- intensity和retention必须是1-10的**整数**
- emotion只能从9个选项中选: 日常/紧张/爽快/悬疑/压抑/感动/悲壮/温馨/热血
- hook/pace/conflict只能从 weak/medium/strong 或 slow/medium/fast 或 low/medium/high 中选
- analysis必须20字以上
- 每章独立评分

## 输出格式

**只输出一个JSON数组，不要输出任何其他文字。** 格式:

```json
[
  {{
    "ch_num": {available[0]},
    "ai_intensity": 7,
    "ai_retention": 8,
    "ai_hook": "strong",
    "ai_pace": "medium",
    "ai_conflict": "high",
    "ai_emotion": "热血",
    "ai_analysis": "末日开篇场景震撼，主角获得金手指后首次战斗爽感十足，章末悬念强烈"
  }}
]
```

共{len(available)}章，JSON数组中必须有{len(available)}个元素，每个元素的ch_num对应下方章节号。""")

    if missing:
        parts.append(f"\n> 注意：另有{len(missing)}章原文缺失(ch{missing})，无法重评，请忽略。")

    # ===== 章节正文 =====
    parts.append(f"\n---\n\n## 待评章节（共{len(available)}章）\n")

    for ch_num in available:
        ch_data = chapters.get(ch_num, {})
        body = truncate_body(ch_data.get("body", ""))
        wc = len(body)
        parts.append(f"### 第{ch_num}章（{wc}字）\n")
        parts.append(body)
        parts.append("")

    # ===== 结尾提醒 =====
    parts.append("---")
    parts.append(f"\n请对以上{len(available)}章逐章评分，输出一个包含{len(available)}个元素的JSON数组。")
    parts.append("章节号: " + ", ".join(str(ch) for ch in available))

    return "\n".join(parts), available, missing


def main():
    print("=" * 70)
    print("GLM重评指令生成器（单文件版）")
    print(f"S/A级书: {len(SA_BOOKS)} 本")
    print("=" * 70)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 清理旧文件
    for old in OUTPUT_DIR.glob("*.md"):
        old.unlink()
    for old in OUTPUT_DIR.glob("*.json"):
        if old.name.endswith("_result.json"):
            old.unlink()

    # 收集所有失败章节
    all_failed = {}
    for book in SA_BOOKS:
        failed = find_failed_chapters(book)
        if failed:
            all_failed[book] = failed
            print(f"  {book}: {len(failed)}章失败 → {failed}")

    if not all_failed:
        print("\n✅ 没有发现失败章节!")
        return

    total = sum(len(v) for v in all_failed.values())
    print(f"\n总计: {total} 章需要重评")

    # 逐书生成单文件指令
    for book, failed_chs in all_failed.items():
        print(f"\n{'=' * 70}")
        print(f"[{book}] {len(failed_chs)} 章")
        print(f"{'=' * 70}")

        raw_text = read_raw_text(book)
        if not raw_text:
            print(f"  [ERROR] 原始txt未找到")
            continue
        chapters = extract_chapters(raw_text)
        print(f"  原文提取: {len(chapters)} 章")

        prompt_text, available, missing = build_single_prompt(book, chapters, failed_chs)
        if missing:
            print(f"  [WARN] {len(missing)}章原文未找到(超出txt范围): {missing}")
        print(f"  可重评: {len(available)} 章")

        out_path = OUTPUT_DIR / f"{book}_GLM评分指令.md"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(prompt_text)

        print(f"  → {out_path.name} ({len(prompt_text):,}字)")

    # 写使用说明
    readme = OUTPUT_DIR / "_使用说明.md"
    readme.write_text(f"""# GLM重评使用说明

## 步骤（3步搞定）

### 第1步：发送指令
打开 `{{书名}}_GLM评分指令.md`，**全选复制**，粘贴到GLM对话框，发送。

### 第2步：保存结果
GLM返回的JSON，**全选复制**，保存为同目录下 `{{书名}}_result.json`。
（即与指令文件同名，后缀改为 `_result.json`）

### 第3步：自动回填
```bash
D:\\miniconda3\\envs\\llm-shared\\python.exe scripts\\apply_rescore.py
```
脚本会自动读取所有 `_result.json`，校验格式，更新 `_ai_full.csv` 和 `_llm.csv`。

## 文件清单
""", encoding="utf-8")

    for book in all_failed:
        readme.open("a", encoding="utf-8").write(
            f"- `{book}_GLM评分指令.md` → GLM返回JSON → 保存为 `{book}_result.json`\n"
        )

    print(f"\n{'=' * 70}")
    print(f"完成! 目录: {OUTPUT_DIR}")
    print(f"\n使用流程:")
    print(f"  1. 打开 {{书名}}_GLM评分指令.md → 全选复制 → 发给GLM")
    print(f"  2. GLM返回JSON → 保存为 {{书名}}_result.json")
    print(f"  3. 运行 apply_rescore.py 自动回填")


if __name__ == "__main__":
    main()
