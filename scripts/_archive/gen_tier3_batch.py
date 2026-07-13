#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""gen_tier3_batch.py — Tier3 annotation plan generator for 7 S-tier books

Output:
  data/golden/末世/tier3/
    ├── {book}_tier3_plan.csv
    ├── {book}_chapters/
    └── annotation_template.csv
"""
import csv
import json
import sys
import os
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

from three_tier_eval import (
    load_ai_scores, load_local_scores, load_rhythm_csv,
    tier3_disagreement_sampling, save_tier3_plan,
    get_stratum, STRATA, SCORES_DIR, RHYTHM_DIR, GOLDEN_DIR
)

# From ai_annotate.py
from ai_annotate import extract_full_chapters

PROJECT_ROOT = Path(__file__).parent.parent

# 7本S级书
S_BOOKS = [
    "地球游戏场",
    "末世大回炉",
    "异兽迷城",
    "黑暗血时代",
    "第一序列",
    "长夜余火",
    "末日乐园",
]

OUTPUT_DIR = GOLDEN_DIR / "tier3"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# 章节文本提取
# ============================================================

def save_chapter_text(book_name: str, ch_nums: set):
    """提取指定章节的原文文本, 保存到 tier3/{book}_chapters/"""
    ch_dir = OUTPUT_DIR / f"{book_name}_chapters"
    ch_dir.mkdir(exist_ok=True)

    chapters = extract_full_chapters(book_name)
    if not chapters:
        print(f"  [WARN] 无法提取章节: {book_name}")
        return

    saved = 0
    for ch in chapters:
        if ch["ch_num"] in ch_nums:
            fp = ch_dir / f"ch{ch['ch_num']:04d}.txt"
            fp.write_text(ch["body"], encoding="utf-8")
            saved += 1

    print(f"  章节文本: {saved}/{len(ch_nums)}章 → {ch_dir}")


# ============================================================
# 标注模板生成
# ============================================================

ANNOTATION_FIELDS = [
    "book", "ch_num", "stratum", "source",
    "ai_intensity", "ai_retention", "ai_hook", "ai_emotion", "ai_analysis",
    "t2_intensity", "t2_retention", "t2_hook", "t2_emotion", "t2_analysis",
    "human_intensity", "human_retention", "human_hook", "human_conflict",
    "human_emotion", "human_analysis",
    "disagreement", "notes"
]

VALID_HOOKS = {"weak", "medium", "strong"}
VALID_CONFLICTS = {"low", "medium", "high"}
VALID_EMOTIONS = {"日常", "紧张", "爽快", "悬疑", "压抑", "感动", "悲壮", "温馨", "感慨", "振奋", "热血"}


def load_t2_full_scores(book_name: str) -> dict:
    """加载Tier2完整评分"""
    t2_csv = SCORES_DIR / f"{book_name}_t2_full.csv"
    if not t2_csv.exists():
        return {}

    result = {}
    with open(t2_csv, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            ch = int(row["ch_num"])
            result[ch] = row
    return result


def load_ai_full_scores(book_name: str) -> dict:
    """加载Tier1完整评分(含所有字段)"""
    ai_csv = SCORES_DIR / f"{book_name}_ai_full.csv"
    if not ai_csv.exists():
        return {}

    result = {}
    with open(ai_csv, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            ch = int(row["ch_num"])
            result[ch] = row
    return result


def generate_annotation_template(book_name: str, tier3_samples: list):
    """为单本书生成标注模板行"""
    ai_full = load_ai_full_scores(book_name)
    t2_full = load_t2_full_scores(book_name)

    rows = []
    for sample in tier3_samples:
        ch = sample.ch_num
        ai = ai_full.get(ch, {})
        t2 = t2_full.get(ch, {})

        rows.append({
            "book": book_name,
            "ch_num": ch,
            "stratum": sample.stratum,
            "source": sample.source,
            "ai_intensity": ai.get("ai_intensity", ""),
            "ai_retention": ai.get("ai_retention", ""),
            "ai_hook": ai.get("ai_hook", ""),
            "ai_emotion": ai.get("ai_emotion", ""),
            "ai_analysis": ai.get("ai_analysis", ""),
            "t2_intensity": t2.get("t2_intensity", ""),
            "t2_retention": t2.get("t2_retention", ""),
            "t2_hook": t2.get("t2_hook", ""),
            "t2_emotion": t2.get("t2_emotion", ""),
            "t2_analysis": t2.get("t2_analysis", ""),
            # 人工标注列(留空)
            "human_intensity": "",
            "human_retention": "",
            "human_hook": "",
            "human_conflict": "",
            "human_emotion": "",
            "human_analysis": "",
            "disagreement": round(sample.disagreement, 2),
            "notes": "",
        })

    return rows


# ============================================================
# 主流程
# ============================================================

def main():
    print("=" * 70)
    print("Tier3 人工标注计划生成 — 7本S级书")
    print("=" * 70)

    all_template_rows = []
    summary_stats = []

    for book_name in S_BOOKS:
        print(f"\n{'─' * 50}")
        print(f"📖 {book_name}")
        print(f"{'─' * 50}")

        # 1. 加载AI评分 (Tier1)
        ai_scores = load_ai_scores(book_name)
        if not ai_scores:
            print(f"  [SKIP] 无Tier1 AI评分")
            continue

        # 2. 加载本地评分 (Tier2 as local)
        t2_csv = SCORES_DIR / f"{book_name}_t2_full.csv"
        local_scores = load_local_scores(str(t2_csv))

        # 3. 如果Tier2没有覆盖到所有AI章节, 用rhythm代理补充
        if len(local_scores) < len(ai_scores):
            rhythm_data = load_rhythm_csv(book_name)
            for r in rhythm_data:
                if r["ch_num"] not in local_scores:
                    local_scores[r["ch_num"]] = {
                        "intensity": r["pleasure_intensity"],
                        "retention": r["pleasure_intensity"] * 0.8,
                    }

        total_chapters = max(max(ai_scores.keys()) if ai_scores else 0,
                           max(local_scores.keys()) if local_scores else 0)

        print(f"  Tier1章节数: {len(ai_scores)}")
        print(f"  Tier2章节数: {len(load_t2_full_scores(book_name))}")
        print(f"  总章数(估算): {total_chapters}")

        # 4. 生成Tier3采样计划
        samples = tier3_disagreement_sampling(
            ai_scores=ai_scores,
            local_scores=local_scores,
            total_chapters=total_chapters,
            n_anchors=5,
            n_disagreement=8,
            n_supplement=2,
        )

        if not samples:
            print(f"  [SKIP] 采样失败")
            continue

        # 5. 保存采样计划CSV
        save_tier3_plan(book_name, samples)

        # 同时保存到tier3目录
        plan_path = OUTPUT_DIR / f"{book_name}_tier3_plan.csv"
        with open(plan_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "ch_num", "source", "stratum", "disagreement",
                "ai_intensity", "ai_retention",
                "t2_intensity", "t2_retention"
            ])
            writer.writeheader()
            for s in samples:
                writer.writerow({
                    "ch_num": s.ch_num,
                    "source": s.source,
                    "stratum": s.stratum,
                    "disagreement": round(s.disagreement, 2),
                    "ai_intensity": s.ai_intensity,
                    "ai_retention": s.ai_retention,
                    "t2_intensity": s.local_intensity,
                    "t2_retention": s.local_retention,
                })
        print(f"  采样计划: {plan_path}")

        # 6. 提取章节原文
        ch_nums = set(s.ch_num for s in samples)
        save_chapter_text(book_name, ch_nums)

        # 7. 生成标注模板行
        template_rows = generate_annotation_template(book_name, samples)
        all_template_rows.extend(template_rows)

        # 统计
        n_anchor = sum(1 for s in samples if s.source == "anchor")
        n_disagree = sum(1 for s in samples if s.source == "disagreement")
        n_supp = sum(1 for s in samples if s.source == "supplement")
        max_d = max(s.disagreement for s in samples) if samples else 0
        summary_stats.append({
            "book": book_name,
            "total": len(samples),
            "anchor": n_anchor,
            "disagreement": n_disagree,
            "supplement": n_supp,
            "max_disagreement": round(max_d, 2),
        })

    # ============================================================
    # 保存统一标注模板
    # ============================================================

    template_path = OUTPUT_DIR / "annotation_template.csv"
    with open(template_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ANNOTATION_FIELDS)
        writer.writeheader()
        writer.writerows(all_template_rows)

    print(f"\n{'=' * 70}")
    print(f"✅ 标注模板: {template_path}")
    print(f"   总章节: {len(all_template_rows)}章 (7本S级书)")
    print(f"{'=' * 70}")

    # 汇总表
    print(f"\n{'📖':>4s} {'书名':<16s} {'总章':>4s} {'锚点':>4s} {'分歧':>4s} {'补充':>4s} {'最大分歧':>8s}")
    print(f"{'───':>4s} {'───':<16s} {'───':>4s} {'───':>4s} {'───':>4s} {'───':>4s} {'───':>8s}")
    for s in summary_stats:
        print(f"  {s['book']:<18s} {s['total']:4d} {s['anchor']:4d} {s['disagreement']:4d} {s['supplement']:4d} {s['max_disagreement']:8.2f}")
    total_ch = sum(s['total'] for s in summary_stats)
    print(f"\n  总计: {total_ch}章待人工标注")
    print(f"  预估时间: {total_ch * 5}分钟 ({total_ch * 5 / 60:.1f}小时)")

    # 标注说明
    guide_path = OUTPUT_DIR / "ANNOTATION_GUIDE.md"
    guide_path.write_text(ANNOTATION_GUIDE, encoding="utf-8")
    print(f"\n  标注指南: {guide_path}")


ANNOTATION_GUIDE = r"""# Tier3 人工标注指南

## 目标
对7本S级书的共约105章进行人工评分，作为校准锚点修正AI评分的系统性偏差。

## 评分维度

| 维度 | 取值 | 说明 |
|------|------|------|
| human_intensity | 1-10整数 | 爽感强度：1=极度无聊, 10=极致爽感 |
| human_retention | 1-10整数 | 追读意愿：1=立刻弃书, 10=迫不及待看下一章 |
| human_hook | weak/medium/strong | 章末悬念：weak=无悬念, medium=有些好奇, strong=必须看下一章 |
| human_conflict | low/medium/high | 冲突程度：low=平淡, medium=有矛盾, high=激烈对抗 |
| human_emotion | 见下表 | 主要情绪基调（选1个） |
| human_analysis | 20-50字中文 | 评分理由（简述为什么给这个分） |

### 情绪分类
日常 / 紧张 / 爽快 / 悬疑 / 压抑 / 感动 / 悲壮 / 温馨 / 感慨 / 振奋 / 热血

## 标注流程

1. 打开 `annotation_template.csv`（Excel或文本编辑器）
2. 找到对应书的章节行
3. 阅读章节原文（在 `{book}_chapters/ch{num}.txt`）
4. 填写 `human_*` 列
5. 可选：在 `notes` 列记录观察到的AI偏差模式

## 对照说明

每行已预填AI(Tier1)和T2(Tier2)的评分供参考：
- `ai_*` 列 = DeepSeek API评分（高质量但可能有低估偏差）
- `t2_*` 列 = 本地Qwen评分（可能有高估偏差）
- `disagreement` = AI与T2的分歧程度（越大越值得关注）

## 采样来源说明

| source | 含义 | 关注点 |
|--------|------|--------|
| anchor | 校准锚点（固定位置） | 提供跨书可比的基准线 |
| disagreement | 分歧驱动（AI与T2差异大） | 判断哪个模型更准确 |
| supplement | 补充采样（两模型一致的极端值） | 确认极端值是否合理 |

## 完成后

标注完成后，运行校准脚本：
```bash
D:\\miniconda3\\envs\\llm-shared\\python.exe scripts\\calibrate_with_tier3.py
```
这将：
1. 计算AI/T2与人工分的MAE和Bias
2. 生成OLS回归校准参数
3. 重跑Borda/TOPSIS排名
4. 重新计算LOOCV相关性
"""


if __name__ == "__main__":
    main()
