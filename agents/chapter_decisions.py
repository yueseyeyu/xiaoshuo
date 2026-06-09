#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
chapter_decisions.py -- 章节决策采集 (Part E 风格涌现的数据源)
============================================================
-- 设计蓝本 --
每章发布后, 用 3 个结构化问题采集作者的:
  1. 正面风格样本: 最满意的段落 -> 提取风格指纹
  2. 风格意图信号: 故意打破常规的地方 -> 提取风格偏好
  3. 偏好边界信号: 拒绝的AI建议 -> 提取决策模式

这些数据积累到 50 章后, 由风格涌现引擎统计分析,
生成 author_style_profile.json, 注入 AI 引导使其越来越贴合作者风格。

-- 数据流 --
章节发布 -> collect_decisions() -> chapter_decisions.json
                                      |
                                      v (50章后)
                              author_style_profile.json
                                      |
                                      v
                              skill_loader 注入 System Prompt

-- 对外接口 --
from chapter_decisions import collect_decisions, load_decisions, get_style_summary
collect_decisions(chapter=5)  # 交互式采集
decisions = load_decisions()  # 加载全部
summary = get_style_summary() # 50章后的风格摘要

-- 开发者指引 --
- 新增问题: 在 DECISION_QUESTIONS 中添加
- 修改存储路径: 改 DECISIONS_PATH 常量
- 分析模块: 后续由 author_style_emergence.py 消费
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional


# ============================================================
# 常量
# ============================================================
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DECISIONS_DIR = PROJECT_ROOT / "data" / "processed" / "chapter_decisions"
DECISIONS_PATH = DECISIONS_DIR / "all_decisions.json"

# 3 个核心问题 -- 每章发布后采集
DECISION_QUESTIONS = [
    {
        "id": "best_segment",
        "category": "positive_style",
        "question": "This chapter: which paragraph are you most proud of? (paste it)",
        "prompt": "  This chapter: which paragraph are you most proud of?",
        "hint": "  (paste the original text, or describe what you like about it)",
    },
    {
        "id": "break_convention",
        "category": "style_intent",
        "question": "Did you deliberately break any convention in this chapter? Why?",
        "prompt": "  Did you deliberately break any writing convention in this chapter?",
        "hint": "  (e.g., used short sentences intentionally, skipped description, reversed trope)",
    },
    {
        "id": "rejected_advice",
        "category": "preference_boundary",
        "question": "Which AI suggestions did you reject? Why?",
        "prompt": "  Which AI suggestions did you reject or ignore?",
        "hint": "  (e.g., 'AI said speed up pacing but I wanted slow burn')",
    },
]


# ============================================================
# 采集
# ============================================================
def collect_decisions(chapter: int) -> dict:
    """
    交互式采集本章的 3 个决策问题。
    返回采集结果 dict, 同时持久化到 all_decisions.json。
    """
    print("=" * 60)
    print(f"  Chapter {chapter} -- Decision Collection")
    print("  3 quick questions to help the system learn your style.")
    print("  (press Enter to skip any question)")
    print("=" * 60)

    record = {
        "chapter": chapter,
        "timestamp": datetime.now().isoformat(),
        "answers": {},
    }

    for q in DECISION_QUESTIONS:
        print(f"\n{q['prompt']}")
        print(f"{q['hint']}")
        answer = input("  > ").strip()

        record["answers"][q["id"]] = {
            "category": q["category"],
            "answer": answer if answer else "(skipped)",
        }

    # 持久化
    _append_record(record)

    print(f"\n{'=' * 60}")
    answered = sum(1 for a in record["answers"].values() if a["answer"] != "(skipped)")
    print(f"  [OK] {answered}/3 answers saved for chapter {chapter}")
    print(f"{'=' * 60}")

    return record


# ============================================================
# 读取
# ============================================================
def load_decisions(chapter: Optional[int] = None) -> list:
    """
    加载决策记录。
    chapter=None: 返回全部; chapter=N: 返回该章记录。
    """
    if not DECISIONS_PATH.exists():
        return []

    with open(DECISIONS_PATH, "r", encoding="utf-8") as f:
        all_records = json.load(f)

    if chapter is not None:
        return [r for r in all_records if r.get("chapter") == chapter]
    return all_records


def get_style_summary() -> dict:
    """
    从积累的决策记录中提取风格摘要。
    需要 10+ 章数据才有统计意义。

    返回:
    {
        "total_chapters": int,
        "skip_rate": float,  # 跳过率 (越低越积极参与)
        "top_categories": [...],  # 最常提到的偏好类型
        "style_signals": [...],  # 风格信号列表
    }
    """
    records = load_decisions()
    if len(records) < 3:
        return {"total_chapters": len(records), "status": "insufficient_data"}

    # 统计跳过率
    total_answers = 0
    skipped = 0
    category_counts = {}
    style_signals = []

    for r in records:
        for q_id, ans in r.get("answers", {}).items():
            total_answers += 1
            if ans.get("answer") == "(skipped)":
                skipped += 1
            else:
                cat = ans.get("category", "unknown")
                category_counts[cat] = category_counts.get(cat, 0) + 1
                # 非跳过的回答本身就是风格信号
                if ans["answer"]:
                    style_signals.append({
                        "chapter": r["chapter"],
                        "category": cat,
                        "signal": ans["answer"][:200],
                    })

    skip_rate = skipped / max(total_answers, 1)

    # 排序类别
    top_cats = sorted(
        category_counts.items(),
        key=lambda x: x[1],
        reverse=True
    )

    return {
        "total_chapters": len(records),
        "skip_rate": round(skip_rate, 2),
        "top_categories": [{"category": c, "count": n} for c, n in top_cats],
        "style_signals": style_signals[-20:],  # 最近 20 条信号
        "status": "sufficient" if len(records) >= 10 else "building",
    }


# ============================================================
# 内部工具
# ============================================================
def _append_record(record: dict) -> None:
    """追加一条记录到 all_decisions.json。"""
    DECISIONS_DIR.mkdir(parents=True, exist_ok=True)

    if DECISIONS_PATH.exists():
        with open(DECISIONS_PATH, "r", encoding="utf-8") as f:
            all_records = json.load(f)
    else:
        all_records = []

    # 去重: 如果本章已有记录, 替换
    all_records = [r for r in all_records if r.get("chapter") != record["chapter"]]
    all_records.append(record)

    # 按章节号排序
    all_records.sort(key=lambda r: r.get("chapter", 0))

    with open(DECISIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(all_records, f, ensure_ascii=False, indent=2)
