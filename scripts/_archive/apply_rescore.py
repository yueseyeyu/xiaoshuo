#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""
apply_rescore.py — 将GLM重评结果回填到 _ai_full.csv 和 _llm.csv

使用前:
  1. 已运行 gen_rescore_prompts.py 生成指令
  2. 已将指令发给GLM并获得JSON输出
  3. 将JSON保存为 {书名}_result.json (与指令文件同目录)

用法: D:\miniconda3\envs\llm-shared\python.exe scripts\apply_rescore.py
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
RESCORE_DIR = PROJECT_ROOT / "data" / "golden" / "末世" / "tier3" / "rescore_prompts"

VALID_HOOKS = {"weak", "medium", "strong"}
VALID_PACES = {"slow", "medium", "fast"}
VALID_CONFLICTS = {"low", "medium", "high"}
VALID_EMOTIONS = {"日常", "紧张", "爽快", "悬疑", "压抑", "感动", "悲壮", "温馨", "热血",
                   "感慨", "振奋", "震惊", "恐惧"}


def validate_score(score):
    """验证并修正单条评分"""
    if not score or not isinstance(score, dict):
        return None
    try:
        ch_num = int(score.get("ch_num", 0))
        intensity = int(score.get("ai_intensity", 0))
        retention = int(score.get("ai_retention", 0))
        if ch_num <= 0 or not (1 <= intensity <= 10) or not (1 <= retention <= 10):
            return None
    except (ValueError, TypeError):
        return None

    hook = str(score.get("ai_hook", "medium")).lower().strip()
    if hook not in VALID_HOOKS:
        hook = "medium"

    pace = str(score.get("ai_pace", "medium")).lower().strip()
    if pace not in VALID_PACES:
        pace = "medium"

    conflict = str(score.get("ai_conflict", "medium")).lower().strip()
    if conflict not in VALID_CONFLICTS:
        conflict = "medium"

    emotion = str(score.get("ai_emotion", "日常")).strip()
    if emotion not in VALID_EMOTIONS:
        emotion = "日常"

    analysis = str(score.get("ai_analysis", "")).strip()
    if len(analysis) < 10:
        analysis = f"intensity={intensity}, retention={retention}, hook={hook}, emotion={emotion}"

    return {
        "ch_num": ch_num,
        "ai_intensity": intensity,
        "ai_retention": retention,
        "ai_hook": hook,
        "ai_pace": pace,
        "ai_conflict": conflict,
        "ai_emotion": emotion,
        "ai_analysis": analysis,
    }


def extract_json(raw_text):
    """从文本中提取JSON数组，支持markdown代码块包裹"""
    raw_text = raw_text.strip()

    # 尝试直接解析
    try:
        data = json.loads(raw_text)
        if isinstance(data, list):
            return data
        return [data]
    except json.JSONDecodeError:
        pass

    # 尝试提取 ```json ... ``` 代码块
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw_text)
    if m:
        try:
            data = json.loads(m.group(1))
            if isinstance(data, list):
                return data
            return [data]
        except json.JSONDecodeError:
            pass

    # 尝试提取最外层 [ ... ]
    start = raw_text.find("[")
    end = raw_text.rfind("]")
    if start >= 0 and end > start:
        try:
            data = json.loads(raw_text[start:end + 1])
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

    return None


def load_result_files():
    """加载所有 _result.json 文件"""
    results = {}  # book -> {ch_num -> score}
    result_files = sorted(RESCORE_DIR.glob("*_result.json"))
    if not result_files:
        print("[ERROR] 未找到任何 *_result.json 文件")
        print(f"  请将GLM输出的JSON保存到: {RESCORE_DIR}")
        print(f"  文件名格式: {{书名}}_result.json")
        return results

    print(f"找到 {len(result_files)} 个结果文件:")
    for f in result_files:
        print(f"  {f.name}")

    for f in result_files:
        # 从文件名提取书名: 长夜余火_result.json → 长夜余火
        book_name = f.name.replace("_result.json", "")
        # 兼容旧格式: 长夜余火_batch1_result.json → 长夜余火
        if "_batch" in book_name:
            book_name = book_name.rsplit("_batch", 1)[0]

        # 读取文件内容
        try:
            raw = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raw = f.read_text(encoding="gbk")

        # 尝试JSON解析
        data = extract_json(raw)
        if data is None:
            print(f"  [ERROR] JSON解析失败 {f.name}")
            continue

        if book_name not in results:
            results[book_name] = {}

        valid_count = 0
        for score in data:
            validated = validate_score(score)
            if validated:
                results[book_name][validated["ch_num"]] = validated
                valid_count += 1

        print(f"  {book_name}: {valid_count} 条有效评分")

    return results


def update_csvs(book_name, new_scores):
    """更新 _ai_full.csv 和 _llm.csv"""
    ai_path = SCORES_DIR / f"{book_name}_ai_full.csv"
    llm_path = SCORES_DIR / f"{book_name}_llm.csv"

    updated_count = 0

    # 更新 _ai_full.csv
    if ai_path.exists():
        with open(ai_path, "r", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
            fields = list(rows[0].keys()) if rows else []

        for row in rows:
            ch = int(row.get("ch_num", 0))
            if ch in new_scores:
                ns = new_scores[ch]
                row["ai_intensity"] = ns["ai_intensity"]
                row["ai_retention"] = ns["ai_retention"]
                row["ai_hook"] = ns["ai_hook"]
                row["ai_pace"] = ns["ai_pace"]
                row["ai_conflict"] = ns["ai_conflict"]
                row["ai_emotion"] = ns["ai_emotion"]
                row["ai_analysis"] = ns["ai_analysis"]
                updated_count += 1

        with open(ai_path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
            w.writeheader()
            w.writerows(rows)
        print(f"  _ai_full.csv: 更新{updated_count}章 ✅")

    # 更新 _llm.csv
    if llm_path.exists():
        with open(llm_path, "r", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
            fields = list(rows[0].keys()) if rows else []

        llm_updated = 0
        for row in rows:
            ch = int(row.get("ch_num", 0))
            if ch in new_scores:
                ns = new_scores[ch]
                row["llm_intensity"] = ns["ai_intensity"]
                row["llm_retention"] = ns["ai_retention"]
                row["llm_hook"] = ns["ai_hook"]
                row["llm_pace"] = ns["ai_pace"]
                row["llm_conflict"] = ns["ai_conflict"]
                row["llm_emotion"] = ns["ai_emotion"]
                row["llm_analysis"] = ns["ai_analysis"]
                llm_updated += 1

        with open(llm_path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
            w.writeheader()
            w.writerows(rows)
        print(f"  _llm.csv: 更新{llm_updated}章 ✅")

    return updated_count


def verify_no_failures(book_name):
    """验证更新后是否还有失败章节"""
    llm_path = SCORES_DIR / f"{book_name}_llm.csv"
    if not llm_path.exists():
        return -1

    fail_patterns = ["LLM解析失败", "LLM评分失败", "解析失败，使用默认值", "评分失败，使用默认值"]
    remaining = 0
    with open(llm_path, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            analysis = row.get("llm_analysis", "")
            if any(p in analysis for p in fail_patterns):
                remaining += 1
    return remaining


def main():
    print("=" * 60)
    print("GLM重评结果回填工具")
    print("=" * 60)

    results = load_result_files()
    if not results:
        return

    print(f"\n涉及书籍: {len(results)} 本")
    total_updated = 0

    for book_name, scores in results.items():
        print(f"\n[{book_name}] {len(scores)} 章新评分")
        for ch_num, score in sorted(scores.items()):
            print(f"  ch{ch_num}: I={score['ai_intensity']} R={score['ai_retention']} "
                  f"{score['ai_emotion']}/{score['ai_hook']}")

        updated = update_csvs(book_name, scores)
        total_updated += updated

        remaining = verify_no_failures(book_name)
        if remaining == 0:
            print(f"  验证: ✅ 无失败章节")
        else:
            print(f"  验证: ⚠️ 仍有{remaining}章失败(可能原文缺失无法重评)")

    print(f"\n{'=' * 60}")
    print(f"完成! 总更新: {total_updated} 章")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
