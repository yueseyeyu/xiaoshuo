#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""v22.1 P2: 用Golden Set数据验证5段分层比例是否接近Neyman最优分配。

Neyman最优分配: n_h ∝ N_h × S_h
  - N_h = 该层章节数（由全书总章数×层占比决定）
  - S_h = 该层内human_intensity的标准差

如果某层的S_h显著高于其他层，说明该层质量波动大，应该多采样。

输出: 各层实际S_h → Neyman理论最优比例 vs 当前设定比例 → 调整建议
"""
import csv
import statistics
import math
import io
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Force UTF-8 output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 3本Golden Set书籍的总章数
BOOK_TOTAL_CH = {
    "废土崛起": 1929,
    "末日蟑螂": 2404,
    "末世大回炉": 1937,
}

# 当前5段分层设定
STRATA = [
    ("黄金开篇",  0.00, 0.03, 0.10),
    ("上升期",    0.03, 0.30, 0.30),
    ("中段稳定",  0.30, 0.60, 0.25),
    ("高潮密集",  0.60, 0.90, 0.25),
    ("结尾",      0.90, 1.00, 0.10),
]

def get_stratum(ch_num, total_ch):
    """根据章节号和总章数，返回该章所属的层名。"""
    pct = ch_num / total_ch
    for name, start, end, _ in STRATA:
        if start <= pct < end:
            return name
    return "结尾"  # 最后一个

def main():
    # 读取Golden Set（排除重测样本）
    rows = []
    golden_path = PROJECT_ROOT / "data" / "processed" / "末世" / "scores" / "human_golden.csv"
    with open(golden_path, "r", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r.get("is_retest", "").lower() == "true":
                continue
            rows.append(r)

    print("=" * 70)
    print("v22.1 P2: 分层比例Neyman最优分配验证")
    print("=" * 70)
    print(f"Golden Set: {len(rows)} 条标注（3本书×10章，排除重测）")
    print()

    # 按层分组
    stratum_data = defaultdict(list)  # {层名: [human_intensity, ...]}
    stratum_by_book = defaultdict(lambda: defaultdict(list))  # {层名: {书名: [scores]}}

    for r in rows:
        book = r["book"]
        ch_num = int(r["ch_num"])
        hi = float(r["human_intensity"])
        total = BOOK_TOTAL_CH.get(book, 2000)
        stratum = get_stratum(ch_num, total)
        stratum_data[stratum].append(hi)
        stratum_by_book[stratum][book].append(hi)

    # 计算各层统计量
    print(f"{'层名':<10} {'N章数':>6} {'当前比例':>8} {'样本数':>6} {'均值':>6} {'标准差':>8} {'S_h×N_h':>10} {'Neyman比例':>10}")
    print("-" * 80)

    neyman_weights = []
    total_n_chapters = sum(BOOK_TOTAL_CH.values())

    for name, start, end, current_pct in STRATA:
        scores = stratum_data[name]
        n_samples = len(scores)

        # N_h = 3本书在该层的平均章节数
        avg_total = statistics.mean(BOOK_TOTAL_CH.values())
        N_h = avg_total * (end - start)

        if n_samples >= 2:
            S_h = statistics.stdev(scores)
            mean_h = statistics.mean(scores)
        else:
            S_h = 0
            mean_h = scores[0] if scores else 0

        # Neyman weight: N_h × S_h
        neyman_w = N_h * S_h
        neyman_weights.append(neyman_w)

        print(f"{name:<10} {N_h:>6.0f} {current_pct:>7.0%} {n_samples:>6} {mean_h:>6.1f} {S_h:>8.2f} {neyman_w:>10.1f} ", end="")
        print(f"{'待算':>10}")

    # 计算Neyman最优比例
    total_neyman = sum(neyman_weights)
    print("-" * 80)
    print(f"{'Neyman最优':<10} {'':>6} {'':>8} {'':>6} {'':>6} {'':>8} {total_neyman:>10.1f} {'':>10}")
    print()

    print(f"{'层名':<10} {'当前比例':>8} {'Neyman比例':>10} {'差异':>8} {'建议':>20}")
    print("-" * 65)
    for i, (name, _, _, current_pct) in enumerate(STRATA):
        neyman_pct = neyman_weights[i] / total_neyman if total_neyman > 0 else 0
        diff = neyman_pct - current_pct
        if abs(diff) < 0.03:
            advice = "[OK] 保持不变"
        elif diff > 0:
            advice = f"[!] 建议提升到{neyman_pct:.0%}"
        else:
            advice = f"[!] 建议降低到{neyman_pct:.0%}"
        print(f"{name:<10} {current_pct:>7.0%} {neyman_pct:>9.0%} {diff:>+7.0%} {advice:>20}")

    # 按书明细
    print()
    print("=" * 70)
    print("按书明细：各层human_intensity分布")
    print("=" * 70)
    for name, _, _, _ in STRATA:
        book_scores = stratum_by_book[name]
        if not book_scores:
            continue
        print(f"\n【{name}】")
        for book, scores in sorted(book_scores.items()):
            if len(scores) >= 2:
                print(f"  {book}: n={len(scores)}, mean={statistics.mean(scores):.1f}, std={statistics.stdev(scores):.2f}, scores={scores}")
            else:
                print(f"  {book}: n={len(scores)}, scores={scores}")

    # 结论
    print()
    print("=" * 70)
    print("结论")
    print("=" * 70)
    # 找出差异最大的层
    max_diff = 0
    max_diff_name = ""
    for i, (name, _, _, current_pct) in enumerate(STRATA):
        neyman_pct = neyman_weights[i] / total_neyman if total_neyman > 0 else 0
        diff = abs(neyman_pct - current_pct)
        if diff > max_diff:
            max_diff = diff
            max_diff_name = name

    if max_diff < 0.05:
        print(f"[OK] 当前比例与Neyman最优分配基本一致（最大差异{max_diff:.0%}，在{max_diff_name}层）。")
        print("   不需要调整分层比例。")
    else:
        print(f"[!] 最大差异在【{max_diff_name}】层，差异{max_diff:.0%}。")
        print(f"   但Golden Set仅30章样本，统计效力有限，建议作为参考而非立即调整。")
    print()
    print("注意: Golden Set每层只有3-9个样本，S_h估计不稳定。")
    print("      此分析结论仅作为方向性参考，不建议直接修改硬编码比例。")
    print("      如果未来Golden Set扩展到50+章，可重新运行此分析获得更可靠的Neyman比例。")

if __name__ == "__main__":
    main()
