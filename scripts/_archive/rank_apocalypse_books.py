"""从零开始对末世小说库进行客观专业打分排名。

方法说明
========
本脚本不依赖原有 S/A/B/C 人工分级，而是基于以下四类指标重新构建综合评分：

1. 市场共识排名 (25%): signing/retention/bt_rank/webnovel8 四维排名
   - 剔除 diversity 作为质量维度（diversity 更适合作为采样约束而非质量指标）
   - 对排名做百分位转换：score = (N - rank + 1) / N * 100

2. 开篇节奏 (25%): hook3/conflict3/pleasure3
   - 基于实际数值做 min-max 归一化到 0-100

3. 全书持续性 (25%): hook_all/pleasure_all/zero_hook_10_inv
   - zero_hook_10 取反（越低越好）

4. 商业评分 (25%): 商业评分 0-100 直接归一化

最终综合分 = 0.25*市场 + 0.25*开篇 + 0.25*持续 + 0.25*商业

分级阈值（基于数据分布）：
- S: 综合分 >= 80
- A: 70 <= 综合分 < 80
- B: 55 <= 综合分 < 70
- C: 综合分 < 55

输出：
- rank_apocalypse_books.csv
- rank_apocalypse_books.md
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT


BOOKS: list[dict[str, Any]] = [
    # 书名, signing_rank, retention_rank, diversity_rank, bt_rank, webnovel8_rank,
    # hook3, conflict3, pleasure3, hook_all, pleasure_all, zero_hook_10, 商业评分
    {"name": "地球游戏场", "signing": 1, "retention": 8, "diversity": 3, "bt_rank": 4, "webnovel8": 4,
     "hook3": 1.63, "conflict3": 0.83, "pleasure3": 2.80, "hook_all": 2.06, "pleasure_all": 3.05, "zero_hook_10": 0, "commercial": 71},
    {"name": "末世之深渊召唤师", "signing": 6, "retention": 2, "diversity": 4, "bt_rank": 11, "webnovel8": 11,
     "hook3": 1.61, "conflict3": 1.04, "pleasure3": 2.93, "hook_all": 2.30, "pleasure_all": 3.10, "zero_hook_10": 1, "commercial": 74},
    {"name": "末世大回炉", "signing": 2, "retention": 6, "diversity": 6, "bt_rank": 13, "webnovel8": 13,
     "hook3": 2.44, "conflict3": 0.56, "pleasure3": 4.57, "hook_all": 3.34, "pleasure_all": 5.53, "zero_hook_10": 0, "commercial": 74},
    {"name": "异兽迷城", "signing": 11, "retention": 11, "diversity": 9, "bt_rank": 6, "webnovel8": 6,
     "hook3": 1.85, "conflict3": 0.40, "pleasure3": 2.53, "hook_all": 1.59, "pleasure_all": 2.42, "zero_hook_10": 0, "commercial": 62},
    {"name": "末世魔神游戏", "signing": 14, "retention": 3, "diversity": 2, "bt_rank": 14, "webnovel8": 14,
     "hook3": 1.10, "conflict3": 0.45, "pleasure3": 2.60, "hook_all": 1.77, "pleasure_all": 2.76, "zero_hook_10": 2, "commercial": 65},
    {"name": "神秘尽头", "signing": 7, "retention": 1, "diversity": 5, "bt_rank": 18, "webnovel8": 18,
     "hook3": 4.12, "conflict3": 0.39, "pleasure3": 2.83, "hook_all": 3.53, "pleasure_all": 2.99, "zero_hook_10": 0, "commercial": 75},
    {"name": "我的末世领地", "signing": 9, "retention": 7, "diversity": 17, "bt_rank": 8, "webnovel8": 8,
     "hook3": 1.42, "conflict3": 0.65, "pleasure3": 5.40, "hook_all": 1.17, "pleasure_all": 3.69, "zero_hook_10": 0, "commercial": 63},
    {"name": "从红月开始", "signing": 10, "retention": 15, "diversity": 21, "bt_rank": 2, "webnovel8": 2,
     "hook3": 2.88, "conflict3": 0.48, "pleasure3": 2.30, "hook_all": 2.62, "pleasure_all": 2.33, "zero_hook_10": 0, "commercial": 62},
    {"name": "世界末日从考试不及格开始", "signing": 12, "retention": 16, "diversity": 22, "bt_rank": 1, "webnovel8": 1,
     "hook3": 2.42, "conflict3": 0.49, "pleasure3": 2.23, "hook_all": 1.70, "pleasure_all": 2.13, "zero_hook_10": 0, "commercial": 60},
    {"name": "全球进化", "signing": 16, "retention": 24, "diversity": 20, "bt_rank": 3, "webnovel8": 3,
     "hook3": 0.99, "conflict3": 0.51, "pleasure3": 2.40, "hook_all": 0.84, "pleasure_all": 1.84, "zero_hook_10": 2, "commercial": 60},
    {"name": "末世召唤狂潮", "signing": 20, "retention": 12, "diversity": 10, "bt_rank": 12, "webnovel8": 12,
     "hook3": 0.91, "conflict3": 0.88, "pleasure3": 2.73, "hook_all": 0.75, "pleasure_all": 1.89, "zero_hook_10": 3, "commercial": 60},
    {"name": "末日拼图游戏", "signing": 4, "retention": 13, "diversity": 23, "bt_rank": 15, "webnovel8": 15,
     "hook3": 2.21, "conflict3": 0.94, "pleasure3": 3.13, "hook_all": 1.93, "pleasure_all": 2.59, "zero_hook_10": 0, "commercial": 65},
    {"name": "废土崛起", "signing": 25, "retention": 17, "diversity": 18, "bt_rank": 5, "webnovel8": 5,
     "hook3": 1.11, "conflict3": 0.30, "pleasure3": 2.87, "hook_all": 1.49, "pleasure_all": 2.95, "zero_hook_10": 0, "commercial": 60},
    {"name": "全球变异", "signing": 5, "retention": 10, "diversity": 14, "bt_rank": 24, "webnovel8": 24,
     "hook3": 2.49, "conflict3": 0.68, "pleasure3": 2.53, "hook_all": 2.84, "pleasure_all": 2.76, "zero_hook_10": 0, "commercial": 68},
    {"name": "狩魔手记", "signing": 8, "retention": 4, "diversity": 11, "bt_rank": 27, "webnovel8": 27,
     "hook3": 1.35, "conflict3": 0.63, "pleasure3": 2.70, "hook_all": 1.96, "pleasure_all": 2.58, "zero_hook_10": 0, "commercial": 67},
    {"name": "黑暗血时代", "signing": 3, "retention": 9, "diversity": 7, "bt_rank": 30, "webnovel8": 30,
     "hook3": 2.46, "conflict3": 0.83, "pleasure3": 2.77, "hook_all": 0.92, "pleasure_all": 1.99, "zero_hook_10": 2, "commercial": 72},
    {"name": "我在末世有套房", "signing": 17, "retention": 20, "diversity": 24, "bt_rank": 9, "webnovel8": 9,
     "hook3": 0.55, "conflict3": 0.68, "pleasure3": 1.90, "hook_all": 1.01, "pleasure_all": 1.47, "zero_hook_10": 0, "commercial": 60},
    {"name": "黑暗文明", "signing": 21, "retention": 5, "diversity": 1, "bt_rank": 29, "webnovel8": 29,
     "hook3": 0.95, "conflict3": 0.50, "pleasure3": 2.20, "hook_all": 2.32, "pleasure_all": 2.80, "zero_hook_10": 0, "commercial": 60},
    {"name": "恐慌沸腾", "signing": 23, "retention": 29, "diversity": 25, "bt_rank": 7, "webnovel8": 7,
     "hook3": 1.07, "conflict3": 0.36, "pleasure3": 1.33, "hook_all": 1.27, "pleasure_all": 1.99, "zero_hook_10": 0, "commercial": 60},
    {"name": "我的女友是丧尸", "signing": 18, "retention": 25, "diversity": 30, "bt_rank": 10, "webnovel8": 10,
     "hook3": 0.66, "conflict3": 0.73, "pleasure3": 1.83, "hook_all": 2.07, "pleasure_all": 2.68, "zero_hook_10": 1, "commercial": 60},
    {"name": "灾厄纪元", "signing": 13, "retention": 21, "diversity": 26, "bt_rank": 17, "webnovel8": 17,
     "hook3": 2.18, "conflict3": 0.23, "pleasure3": 1.63, "hook_all": 1.76, "pleasure_all": 2.44, "zero_hook_10": 0, "commercial": 60},
    {"name": "黑暗王者", "signing": 19, "retention": 18, "diversity": 13, "bt_rank": 23, "webnovel8": 23,
     "hook3": 1.79, "conflict3": 0.22, "pleasure3": 1.30, "hook_all": 2.30, "pleasure_all": 2.46, "zero_hook_10": 0, "commercial": 60},
    {"name": "重卡战车在末世", "signing": 28, "retention": 19, "diversity": 8, "bt_rank": 21, "webnovel8": 21,
     "hook3": 0.98, "conflict3": 0.34, "pleasure3": 1.30, "hook_all": 0.93, "pleasure_all": 2.96, "zero_hook_10": 0, "commercial": 60},
    {"name": "末日蟑螂", "signing": 30, "retention": 27, "diversity": 16, "bt_rank": 16, "webnovel8": 16,
     "hook3": 0.31, "conflict3": 0.45, "pleasure3": 1.43, "hook_all": 1.06, "pleasure_all": 4.26, "zero_hook_10": 5, "commercial": 60},
    {"name": "第九特区", "signing": 29, "retention": 30, "diversity": 12, "bt_rank": 19, "webnovel8": 19,
     "hook3": 0.56, "conflict3": 0.17, "pleasure3": 1.00, "hook_all": 0.68, "pleasure_all": 1.50, "zero_hook_10": 2, "commercial": 60},
    {"name": "末世超级商人", "signing": 27, "retention": 14, "diversity": 19, "bt_rank": 26, "webnovel8": 26,
     "hook3": 0.86, "conflict3": 0.38, "pleasure3": 1.73, "hook_all": 0.99, "pleasure_all": 1.91, "zero_hook_10": 0, "commercial": 60},
    {"name": "蹉跎", "signing": 22, "retention": 22, "diversity": 29, "bt_rank": 20, "webnovel8": 20,
     "hook3": 1.05, "conflict3": 0.32, "pleasure3": 1.60, "hook_all": 0.90, "pleasure_all": 1.96, "zero_hook_10": 0, "commercial": 46},
    {"name": "我在末世种个田", "signing": 26, "retention": 26, "diversity": 15, "bt_rank": 25, "webnovel8": 25,
     "hook3": 0.80, "conflict3": 0.24, "pleasure3": 1.67, "hook_all": 1.82, "pleasure_all": 2.26, "zero_hook_10": 0, "commercial": 60},
    {"name": "限制级末日症候", "signing": 15, "retention": 23, "diversity": 28, "bt_rank": 28, "webnovel8": 28,
     "hook3": 1.15, "conflict3": 0.70, "pleasure3": 1.93, "hook_all": 1.12, "pleasure_all": 1.94, "zero_hook_10": 0, "commercial": 60},
    {"name": "黑暗末日", "signing": 24, "retention": 28, "diversity": 27, "bt_rank": 22, "webnovel8": 22,
     "hook3": 1.74, "conflict3": 0.30, "pleasure3": 1.87, "hook_all": 1.63, "pleasure_all": 2.80, "zero_hook_10": 0, "commercial": 43},
]


def rank_to_percentile(rank: int, n: int) -> float:
    """将排名转换为百分位分数，越低排名得分越高。"""
    return (n - rank + 1) / n * 100.0


def min_max_normalize(values: list[float]) -> list[float]:
    """Min-max 归一化到 0-100。"""
    min_v = min(values)
    max_v = max(values)
    rng = max_v - min_v if max_v != min_v else 1.0
    return [(v - min_v) / rng * 100.0 for v in values]


def assign_tier(score: float) -> str:
    # 基于数据分布的自然断点：
    # S >= 75 (顶尖标杆), A >= 65 (优秀), B >= 45 (合格/中等), C < 45 (偏低)
    if score >= 75.0:
        return "S"
    if score >= 65.0:
        return "A"
    if score >= 45.0:
        return "B"
    return "C"


def compute_scores(books: list[dict[str, Any]]) -> list[dict[str, Any]]:
    n = len(books)

    # 市场共识排名分 (25%): signing/retention 各 8%, bt/webnovel8 各 4.5%
    signing_scores = [rank_to_percentile(b["signing"], n) for b in books]
    retention_scores = [rank_to_percentile(b["retention"], n) for b in books]
    bt_scores = [rank_to_percentile(b["bt_rank"], n) for b in books]
    w8_scores = [rank_to_percentile(b["webnovel8"], n) for b in books]

    # 开篇节奏 (25%): hook3/conflict3/pleasure3
    hook3_scores = min_max_normalize([b["hook3"] for b in books])
    conflict3_scores = min_max_normalize([b["conflict3"] for b in books])
    pleasure3_scores = min_max_normalize([b["pleasure3"] for b in books])

    # 全书持续性 (25%): hook_all/pleasure_all/zero_hook_10_inv
    hook_all_scores = min_max_normalize([b["hook_all"] for b in books])
    pleasure_all_scores = min_max_normalize([b["pleasure_all"] for b in books])
    zh_max = max(b["zero_hook_10"] for b in books)
    zh_min = min(b["zero_hook_10"] for b in books)
    zh_range = zh_max - zh_min if zh_max != zh_min else 1.0
    zero_hook_inv_scores = [(zh_max - b["zero_hook_10"]) / zh_range * 100.0 for b in books]

    # 商业评分 (25%)
    commercial_scores = [b["commercial"] for b in books]

    results = []
    for i, b in enumerate(books):
        market = (
            signing_scores[i] * 0.10
            + retention_scores[i] * 0.10
            + bt_scores[i] * 0.05
            + w8_scores[i] * 0.05
        )
        opening = (
            hook3_scores[i] * 0.10
            + conflict3_scores[i] * 0.075
            + pleasure3_scores[i] * 0.075
        )
        sustainability = (
            hook_all_scores[i] * 0.10
            + pleasure_all_scores[i] * 0.10
            + zero_hook_inv_scores[i] * 0.05
        )
        commercial = commercial_scores[i] * 0.25

        total = market + opening + sustainability + commercial
        results.append({
            **b,
            "market_score": round(market, 2),
            "opening_score": round(opening, 2),
            "sustainability_score": round(sustainability, 2),
            "commercial_score": round(commercial, 2),
            "total_score": round(total, 2),
            "tier": assign_tier(total),
        })

    results.sort(key=lambda x: x["total_score"], reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1
    return results


def write_csv(results: list[dict[str, Any]], path: Path) -> None:
    fieldnames = [
        "rank", "tier", "name", "total_score",
        "market_score", "opening_score", "sustainability_score", "commercial_score",
        "signing", "retention", "bt_rank", "webnovel8",
        "hook3", "conflict3", "pleasure3",
        "hook_all", "pleasure_all", "zero_hook_10", "commercial",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow({k: r[k] for k in fieldnames})


def write_markdown(results: list[dict[str, Any]], path: Path) -> None:
    lines = [
        "# 末世小说客观综合评分排名（从零开始）",
        "",
        "> 评分方法：市场共识(25%) + 开篇节奏(25%) + 全书持续性(25%) + 商业评分(25%)",
        "> 排名转换：Borda 各维度排名按百分位转换；节奏指标按 min-max 归一化；zero_hook_10 取反",
        "",
        "| 排名 | 等级 | 书名 | 综合分 | 市场 | 开篇 | 持续 | 商业 |",
        "|:---:|:---:|:---|:---:|:---:|:---:|:---:|:---:|",
    ]
    for r in results:
        lines.append(
            f"| {r['rank']} | {r['tier']} | {r['name']} | {r['total_score']} | "
            f"{r['market_score']} | {r['opening_score']} | {r['sustainability_score']} | {r['commercial_score']} |"
        )
    lines.extend([
        "",
        "## 分级说明",
        "",
        "- S: 综合分 >= 75",
        "- A: 65 <= 综合分 < 75",
        "- B: 45 <= 综合分 < 65",
        "- C: 综合分 < 45",
        "",
        "## 维度权重",
        "",
        "### 市场共识 (25%)",
        "- signing 排名分: 10%",
        "- retention 排名分: 10%",
        "- bt_rank 排名分: 5%",
        "- webnovel8 排名分: 5%",
        "",
        "### 开篇节奏 (25%)",
        "- hook3: 10%",
        "- conflict3: 7.5%",
        "- pleasure3: 7.5%",
        "",
        "### 全书持续性 (25%)",
        "- hook_all: 10%",
        "- pleasure_all: 10%",
        "- zero_hook_10_inv: 5%",
        "",
        "### 商业评分 (25%)",
        "- 商业评分直接归一化: 25%",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    print("[OK] Start ranking apocalypse books")
    results = compute_scores(BOOKS)

    csv_path = OUTPUT_DIR / "rank_apocalypse_books.csv"
    md_path = OUTPUT_DIR / "rank_apocalypse_books.md"
    write_csv(results, csv_path)
    write_markdown(results, md_path)

    tier_counts: dict[str, int] = {}
    for r in results:
        tier_counts[r["tier"]] = tier_counts.get(r["tier"], 0) + 1

    print(f"[OK] Total books: {len(results)}")
    print(f"[OK] Tier distribution: {tier_counts}")
    print(f"[OK] CSV saved: {csv_path}")
    print(f"[OK] Markdown saved: {md_path}")

    print("\n[OK] Top 10:")
    for r in results[:10]:
        print(f"  #{r['rank']:2d} [{r['tier']}] {r['name']:20s} {r['total_score']:.2f}")

    print("\n[OK] Bottom 5:")
    for r in results[-5:]:
        print(f"  #{r['rank']:2d} [{r['tier']}] {r['name']:20s} {r['total_score']:.2f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
