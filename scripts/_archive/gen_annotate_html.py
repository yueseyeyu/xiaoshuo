#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""
生成HTML标注工具 — 30章Ground Truth标注
=========================================
生成一个本地HTML文件，用户在浏览器中阅读章节、打分、导出CSV。
用法: D:\miniconda3\envs\llm-shared\python.exe scripts\gen_annotate_html.py
输出: scripts/annotate_tool.html
      用户标注后点击"导出CSV"下载 human_golden.csv
"""
import csv
import re
import json
import random
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
RHYTHM_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "rhythm"
LLM_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "scores"
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "novels" / "末世"
OUTPUT_HTML = Path(__file__).parent / "annotate_tool.html"
GLM_SCORES_PATH = Path(__file__).parent / "glm_scores.json"

BOOKS = [
    {
        "name": "废土崛起",
        "rhythm": RHYTHM_DIR / "rhythm_《废土崛起》（校对版全本）作者：通吃道人.csv",
        "llm": LLM_DIR / "《废土崛起》（校对版全本）作者：通吃道人_llm.csv",
        "raw": RAW_DIR / "《废土崛起》（校对版全本）作者：通吃道人.txt",
    },
    {
        "name": "末日蟑螂",
        "rhythm": RHYTHM_DIR / "rhythm_《末日蟑螂》作者：伟岸蟑螂.csv",
        "llm": LLM_DIR / "《末日蟑螂》作者：伟岸蟑螂_llm.csv",
        "raw": RAW_DIR / "《末日蟑螂》作者：伟岸蟑螂.txt",
    },
    {
        "name": "末世大回炉",
        "rhythm": RHYTHM_DIR / "rhythm_《末世大回炉》（校对版全本）作者：二十二刀流.csv",
        "llm": LLM_DIR / "《末世大回炉》（校对版全本）作者：二十二刀流_llm.csv",
        "raw": RAW_DIR / "《末世大回炉》（校对版全本）作者：二十二刀流.txt",
    },
]


def read_text(path):
    for enc in ["utf-8", "gbk", "gb18030", "utf-16"]:
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    return ""


def extract_chapters(raw_text):
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
                cn_map = {"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9,"十":10}
                cn_str = m2.group(1)
                if len(cn_str) == 1:
                    ch_num = cn_map.get(cn_str, 0)
                elif cn_str == "十":
                    ch_num = 10
                elif cn_str.startswith("十"):
                    ch_num = 10 + cn_map.get(cn_str[1], 0)
                elif cn_str.endswith("十"):
                    ch_num = cn_map.get(cn_str[0], 1) * 10
                else:
                    ch_num = 0
            else:
                continue
        if ch_num > 0 and body:
            chapters[ch_num] = {"header": header, "body": body}
    return chapters


def select_chapters(llm_csv):
    """直接从LLM CSV选章——每本书的LLM CSV已有10章且包含rule_intensity"""
    if not llm_csv or not llm_csv.exists():
        return []

    rows = []
    with open(llm_csv, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for r in reader:
            try:
                ch = int(r.get("ch_num", 0) or r.get("\ufeffch_num", 0) or 0)
                if ch <= 0:
                    continue
                rows.append({
                    "ch_num": ch,
                    "pleasure_intensity": float(r.get("rule_intensity", 0) or 0),
                    "wc": int(r.get("wc", 0) or 0),
                    "llm_intensity": float(r.get("llm_intensity", 0) or 0),
                    "llm_retention": float(r.get("llm_retention", 0) or 0),
                })
            except (ValueError, TypeError):
                continue

    return rows


def build_html(all_chapters):
    """构建HTML标注工具 v5 — 模板文件注入模式
    HTML/CSS/JS 全部在 annotate_template.html 中维护，
    此函数只负责数据注入，消除 f-string 转义问题。

    UX改进 (v5):
    - 主评分置顶 + 突出显示
    - Rubric锚点/参照面板可折叠
    - 章节列表按书分组 + 显示已标注分数
    - 段落首行缩进 + 衬线字体
    - 阅读位置记忆
    - 进度条加粗 + 章节号显示
    - 跳过按钮
    - 滑块+点击编辑合并
    """
    chapters_json = json.dumps(all_chapters, ensure_ascii=False)
    template_path = Path(__file__).parent / "annotate_template.html"
    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()
    html = html.replace("__CHAPTERS_JSON__", chapters_json)
    return html

def load_glm_scores():
    """加载GLM盲评分数"""
    if not GLM_SCORES_PATH.exists():
        print(f"  [警告] GLM分数文件不存在: {GLM_SCORES_PATH}")
        return {}
    with open(GLM_SCORES_PATH, "r", encoding="utf-8") as f:
        scores = json.load(f)
    result = {}
    for s in scores:
        key = s["book"] + "_" + str(s["ch_num"])
        result[key] = s
    print(f"  加载GLM分数: {len(result)} 章")
    return result


def main():
    all_chapters = []
    glm_scores = load_glm_scores()

    for book in BOOKS:
        print(f"加载 {book['name']}...")
        raw_text = read_text(book["raw"])
        chapters_raw = extract_chapters(raw_text)
        print(f"  提取到 {len(chapters_raw)} 章")

        selected = select_chapters(book["llm"])
        print(f"  选中 {len(selected)} 章")

        for s in selected:
            ch_data = chapters_raw.get(s["ch_num"], {})
            body = ch_data.get("body", "")
            if not body:
                print(f"  [跳过] 第{s['ch_num']}章 未找到原文")
                continue

            # 保留全文，不截断

            glm_key = book["name"] + "_" + str(s["ch_num"])
            glm = glm_scores.get(glm_key, {})

            all_chapters.append({
                "book": book["name"],
                "ch_num": s["ch_num"],
                "wc": s["wc"],
                "rule_intensity": s["pleasure_intensity"],
                "llm_intensity": s["llm_intensity"],
                "llm_retention": s["llm_retention"],
                "glm_intensity": glm.get("glm_intensity", None),
                "glm_retention": glm.get("glm_retention", None),
                "glm_note": glm.get("glm_note", ""),
                "body": body,
            })

    print(f"\n共 {len(all_chapters)} 章待标注")

    html = build_html(all_chapters)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n[OK] HTML标注工具已生成: {OUTPUT_HTML}")
    print(f"  在浏览器中打开此文件即可开始标注")
    print(f"  标注完成后点击'导出CSV'，将文件放到 data/processed/末世/scores/")


if __name__ == "__main__":
    main()
