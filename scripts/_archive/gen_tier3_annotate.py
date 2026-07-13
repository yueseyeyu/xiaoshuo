#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""
Tier3 校准标注工具生成器
========================
复用已有的 HTML 标注工具 (annotate_template.html)，注入精简后的 Tier3 数据。

精简策略:
  - 末世大回炉: 已有10章golden → 仅补5章新高分歧章节
  - 其余6本: 每本 5锚点 + 3高分歧 = 8章
  - 黑暗血时代: 额外保留 ch216(2/2分) 作为低分锚点
  - 长夜余火: 原tier3计划选中的10章全是AI解析失败章节，
    重新从112章AI成功章节中精选8章(覆盖低/中/高分)
  总计: 54章 (原计划97章，减少44%)

用法: D:\miniconda3\envs\llm-shared\python.exe scripts\gen_tier3_annotate.py
输出: data/golden/末世/tier3/annotate_tool.html
"""
import csv
import json
import re
import sys
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PROJECT_ROOT = Path(__file__).parent.parent
TIER3_DIR = PROJECT_ROOT / "data" / "golden" / "末世" / "tier3"
LLM_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "scores"
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "novels" / "末世"
TEMPLATE_PATH = PROJECT_ROOT / "scripts" / "_archive" / "annotate_template.html"
OUTPUT_HTML = TIER3_DIR / "annotate_tool.html"
GOLDEN_CSV = PROJECT_ROOT / "data" / "golden" / "末世" / "human_golden.csv"

# ── 精简采样计划 ──
# 每本书: anchors(5个故事节点) + disagreement(高分歧Top-N) + supplement(特殊补充)
REDUCED_PLAN = {
    "地球游戏场": {
        "anchors": [1, 198, 384, 581, 769],
        "disagreement": [749, 561, 443],
        "supplement": [],
    },
    "末世大回炉": {
        # 已有golden: [1,194,387,580,773,966,1159,1352,1545,1738]
        # 只补5章新高分歧
        "anchors": [],
        "disagreement": [975, 1606, 1704, 1556, 1625],
        "supplement": [],
    },
    "异兽迷城": {
        "anchors": [1, 316, 643, 959, 1276],
        "disagreement": [900, 663, 762],
        "supplement": [],
    },
    "黑暗血时代": {
        "anchors": [1, 466, 922, 1388, 1841],
        "disagreement": [1537, 256, 665],
        "supplement": [216],  # score 2/2, 低分锚点不可少
    },
    "第一序列": {
        "anchors": [1, 310, 627, 946, 1251],
        "disagreement": [955, 896, 747],
        "supplement": [],
    },
    "末日乐园": {
        "anchors": [1, 610, 1218, 1817, 2419],
        "disagreement": [979, 1866, 2016],
        "supplement": [],
    },
    "长夜余火": {
        # 原tier3计划选中的10章全是AI解析失败("LLM解析失败，使用默认值")
        # 从112章AI成功章节中重新精选8章，覆盖低/中/高分
        "anchors": [8, 96, 211, 536, 934],
        "disagreement": [45, 108, 161],
        "supplement": [],
    },
}


def cn2num(s):
    """Convert Chinese numeral string to int. e.g. '一百二十三' -> 123, '十' -> 10"""
    digit_map = {'零':0,'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
    if s.isdigit():
        return int(s)
    result = 0
    current = 0
    for ch in s:
        if ch in digit_map:
            current = digit_map[ch]
        elif ch == '十':
            result += (current if current else 1) * 10
            current = 0
        elif ch == '百':
            result += current * 100
            current = 0
        elif ch == '千':
            result += current * 1000
            current = 0
    result += current
    return result


def load_tier3_plan(book_name):
    """从 tier3_plan CSV 加载每章的 AI/T2 分数。"""
    csv_path = TIER3_DIR / f"{book_name}_tier3_plan.csv"
    if not csv_path.exists():
        print(f"  [警告] 未找到 {csv_path}")
        return {}
    rows = {}
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for r in reader:
            ch = int(r.get("ch_num", 0) or 0)
            if ch > 0:
                rows[ch] = r
    return rows


def load_llm_extras(book_name):
    """从 _llm.csv 加载 ai_analysis, ai_emotion, ai_hook 等文本字段。"""
    llm_path = LLM_DIR / f"{book_name}_llm.csv"
    if not llm_path.exists():
        print(f"  [警告] 未找到 {llm_path}")
        return {}
    rows = {}
    with open(llm_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for r in reader:
            ch = int(r.get("ch_num", 0) or 0)
            if ch > 0:
                rows[ch] = r
    return rows


def read_chapter_text(book_name, ch_num):
    """读取章节文本：优先从tier3_chapters目录，找不到则从原始小说文件提取。"""
    # 方式1: 从已提取的tier3章节目录读取
    ch_path = TIER3_DIR / f"{book_name}_chapters" / f"ch{ch_num:04d}.txt"
    if ch_path.exists():
        for enc in ["utf-8", "gbk", "gb18030"]:
            try:
                return ch_path.read_text(encoding=enc)
            except (UnicodeDecodeError, UnicodeError):
                continue

    # 方式2: 从原始小说txt文件提取
    raw_files = list(RAW_DIR.glob(f"*{book_name}*.txt"))
    if not raw_files:
        return ""
    raw_path = raw_files[0]
    for enc in ["utf-8", "gbk", "gb18030", "utf-16"]:
        try:
            raw_text = raw_path.read_text(encoding=enc)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    else:
        return ""

    # 按章节标题分割（支持多卷重编号：按出现顺序累计计数）
    cn_nums = r"[一二三四五六七八九十百千零\d]+"
    pattern = r"(第" + cn_nums + r"章\s*[^\n]*)"
    parts = re.split(pattern, raw_text)
    if len(parts) < 5:
        return ""

    # 策略1: 先尝试直接匹配章节号（适用于单卷编号）
    for i in range(1, len(parts) - 1, 2):
        header = parts[i].strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        # Try Arabic digits first
        m = re.search(r"第(\d+)章", header)
        if m and int(m.group(1)) == ch_num:
            return body
        # Try Chinese numerals
        m = re.search(r"第([一二三四五六七八九十百千零\d]+)章", header)
        if m:
            parsed = cn2num(m.group(1))
            if parsed == ch_num:
                return body

    # 策略2: 按出现顺序累计计数（适用于多卷重编号）
    cumulative = 0
    for i in range(1, len(parts) - 1, 2):
        header = parts[i].strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        cumulative += 1
        if cumulative == ch_num:
            return body

    return ""


def load_existing_golden_chapters():
    """加载已有 golden 标注的章节列表。"""
    if not GOLDEN_CSV.exists():
        return set()
    existing = set()
    with open(GOLDEN_CSV, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for r in reader:
            book = r.get("book", "")
            ch = int(r.get("ch_num", 0) or 0)
            if ch > 0:
                existing.add((book, ch))
    return existing


def safe_float(val, default=0.0):
    try:
        return float(val) if val else default
    except (ValueError, TypeError):
        return default


def build_chapters():
    """构建标注工具用的章节列表。"""
    existing_golden = load_existing_golden_chapters()
    all_chapters = []

    for book_name, plan in REDUCED_PLAN.items():
        print(f"\n加载 {book_name}...")
        tier3_data = load_tier3_plan(book_name)
        llm_extras = load_llm_extras(book_name)

        # 合并所有选中章节
        selected = []
        for ch in plan["anchors"]:
            selected.append((ch, "anchor"))
        for ch in plan["disagreement"]:
            selected.append((ch, "disagreement"))
        for ch in plan["supplement"]:
            selected.append((ch, "supplement"))

        # 按章节号排序
        selected.sort(key=lambda x: x[0])

        book_count = 0
        for ch_num, source in selected:
            # 跳过已在 golden 中的章节
            if (book_name, ch_num) in existing_golden:
                print(f"  跳过 第{ch_num}章 (已在golden中)")
                continue

            plan_data = tier3_data.get(ch_num, {})
            llm_data = llm_extras.get(ch_num, {})
            body = read_chapter_text(book_name, ch_num)
            if not body:
                print(f"  [警告] 第{ch_num}章 原文未找到")
                continue

            # AI 分数 (CatPaw Tier1)
            ai_intensity = safe_float(plan_data.get("ai_intensity"))
            ai_retention = safe_float(plan_data.get("ai_retention"))

            # T2 分数 (本地Qwen Tier2)
            t2_raw = plan_data.get("t2_intensity", "")
            t2_intensity = safe_float(t2_raw) if t2_raw else None
            t2_raw_r = plan_data.get("t2_retention", "")
            t2_retention = safe_float(t2_raw_r) if t2_raw_r else None

            # AI 分析文本
            ai_hook = llm_data.get("llm_hook", "")
            ai_emotion = llm_data.get("llm_emotion", "")
            ai_analysis = llm_data.get("llm_analysis", "")

            wc = len(body.strip())

            all_chapters.append({
                "book": book_name,
                "ch_num": ch_num,
                "wc": wc,
                "rule_intensity": 0,  # tier3计划中无规则分
                "llm_intensity": ai_intensity,
                "llm_retention": ai_retention,
                # 映射到模板的 glm_* 字段
                "glm_intensity": t2_intensity,
                "glm_retention": t2_retention,
                # 额外字段 (模板不直接使用，但导出时保留)
                "ai_hook": ai_hook,
                "ai_emotion": ai_emotion,
                "ai_analysis": ai_analysis,
                "source": source,
                "body": body,
            })
            book_count += 1
            print(f"  + 第{ch_num}章 [{source}] AI={ai_intensity}/{ai_retention} "
                  f"T2={t2_intensity}/{t2_retention} {ai_emotion}")

        print(f"  小计: {book_count} 章")

    return all_chapters


def build_html(all_chapters):
    """构建 HTML 标注工具。"""
    chapters_json = json.dumps(all_chapters, ensure_ascii=False)
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    # 注入章节数据
    html = html.replace("__CHAPTERS_JSON__", chapters_json)

    # 标题替换
    total = len(all_chapters)
    html = html.replace(
        "30章Ground Truth",
        f"{total}章Tier3校准"
    )
    html = html.replace(
        "Ground Truth 标注",
        "Tier3 校准标注"
    )
    html = html.replace("0 / 30", f"0 / {total}")

    # GLM → T2 标签替换
    replacements = [
        ("GLM爽度", "T2爽度"),
        ("GLM留存", "T2留存"),
        ('"color:var(--green);font-weight:600;">GLM',
         '"color:var(--green);font-weight:600;">T2'),
        ("glm_bias_high", "t2_bias_high"),
        ("glm_bias_low", "t2_bias_low"),
        ("GLM偏高", "T2偏高"),
        ("GLM偏低", "T2偏低"),
        ("GLM评分明显高于人工", "T2评分明显高于人工"),
        ("GLM评分明显低于人工", "T2评分明显低于人工"),
        ("GLM看到打脸关键词给7分", "T2看到打脸关键词给7分"),
        ("GLM未理解末世生存压力", "T2未理解末世生存压力"),
    ]
    for old, new in replacements:
        html = html.replace(old, new)

    # 重测阈值: 15 → 20
    html = html.replace("doneCount < 15", "doneCount < 20")
    html = html.replace("已完成15章标注", "已完成20章标注")

    # 导出文件名
    html = html.replace("human_golden.csv", "tier3_golden.csv")
    html = html.replace(
        "data/processed/末世/scores/",
        "data/golden/末世/tier3/"
    )

    return html


def main():
    print("=" * 60)
    print("Tier3 校准标注工具生成器")
    print("精简策略: 6本书 × 8章/本 + 末世大回炉仅补5章 + 长夜余火8章 = 54章")
    print("(原计划97章，减少44%)")
    print("=" * 60)

    all_chapters = build_chapters()
    print(f"\n{'=' * 60}")
    print(f"总计: {len(all_chapters)} 章待标注")
    print(f"{'=' * 60}")

    # 统计
    books = {}
    for ch in all_chapters:
        books.setdefault(ch["book"], []).append(ch)
    for b, chs in sorted(books.items()):
        print(f"  {b}: {len(chs)} 章")

    html = build_html(all_chapters)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n[OK] HTML标注工具已生成:")
    print(f"  {OUTPUT_HTML}")
    print(f"\n使用方法:")
    print(f"  1. 在浏览器中打开上述HTML文件")
    print(f"  2. 逐章阅读 → 打分 → 保存并下一章")
    print(f"  3. 全部完成后点击'导出CSV'")
    print(f"  4. 将导出的 tier3_golden.csv 放到 data/golden/末世/tier3/")
    print(f"\n快捷键:")
    print(f"  Alt+←/→ 上一章/保存下一章")
    print(f"  1-9,0 快速设置爽点强度")
    print(f"  B 切换盲评模式")


if __name__ == "__main__":
    main()
