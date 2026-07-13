#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""
loocv_calibrate.py — LOOCV交叉验证校准效果
==============================================
Phase C的测试存在in-sample bias: 用30章构建映射，又用同样30章评估。
本脚本执行Leave-One-Out Cross-Validation (LOOCV)：
  1. 每次留出1章作为测试
  2. 用剩余29章构建校准映射
  3. 对留出的1章应用校准
  4. 重复30次，计算真实泛化MAE

同时执行统计显著性检验（配对t检验 / Wilcoxon符号秩检验）。

用法:
  D:\miniconda3\envs\llm-shared\python.exe scripts/loocv_calibrate.py
"""
import csv
import json
import math
import sys
import statistics
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent.parent


def mae(xs, ys):
    return sum(abs(x - y) for x, y in zip(xs, ys)) / len(xs)


def bias(xs, ys):
    return sum(x - y for x, y in zip(xs, ys)) / len(xs)


def pearson_r(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs) / n)
    sy = math.sqrt(sum((y - my) ** 2 for y in ys) / n)
    if sx == 0 or sy == 0:
        return 0.0
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / n
    return cov / (sx * sy)


def stdev(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    return math.sqrt(sum((x - mx) ** 2 for x in xs) / n)


def wilcoxon_signed_rank(diffs):
    """Wilcoxon signed-rank test (simplified, no ties handling)."""
    nonzero = [(d, abs(d)) for d in diffs if d != 0]
    if len(nonzero) < 5:
        return float("nan"), "n太小"
    nonzero.sort(key=lambda x: x[1])
    ranks = list(range(1, len(nonzero) + 1))
    w_pos = sum(r for (d, _), r in zip(nonzero, ranks) if d > 0)
    w_neg = sum(r for (d, _), r in zip(nonzero, ranks) if d < 0)
    w = min(w_pos, w_neg)
    n = len(nonzero)
    # 正态近似
    mu = n * (n + 1) / 4
    sigma = math.sqrt(n * (n + 1) * (2 * n + 1) / 24)
    if sigma == 0:
        return float("nan"), "sigma=0"
    z = (w - mu) / sigma
    # 双侧p值近似
    import math as m
    p = 2 * (1 - 0.5 * (1 + m.erf(abs(z) / m.sqrt(2))))
    return z, p


def build_quantile_map_loocv(paired_train):
    """Build quantile mapping from training set only."""
    if len(paired_train) < 3:
        return lambda x: x
    llm_sorted = sorted(p[0] for p in paired_train)
    human_sorted = sorted(p[1] for p in paired_train)
    def mapping(x):
        if x <= llm_sorted[0]:
            return human_sorted[0]
        if x >= llm_sorted[-1]:
            return human_sorted[-1]
        for i in range(len(llm_sorted) - 1):
            if llm_sorted[i] <= x <= llm_sorted[i + 1]:
                t = (x - llm_sorted[i]) / max(llm_sorted[i + 1] - llm_sorted[i], 0.001)
                return human_sorted[i] + t * (human_sorted[i + 1] - human_sorted[i])
        return x
    return mapping


def main():
    # 加载 Phase B 结果
    pb_path = PROJECT_ROOT / "data" / "reports" / "末世" / "e2e_verify_phaseB.json"
    with open(pb_path, encoding="utf-8") as f:
        pb = json.load(f)
    data = pb["details"]

    n = len(data)
    print(f"{'='*70}")
    print(f"  LOOCV交叉验证 — 校准效果真实泛化性能")
    print(f"  样本数: {n}")
    print(f"{'='*70}")

    # 提取配对数据
    raw_i = [r["new_llm_i"] for r in data]
    raw_r = [r["new_llm_r"] for r in data]
    human_i = [r["human_i"] for r in data]
    human_r = [r["human_r"] for r in data]

    paired_int = list(zip(raw_i, human_i))
    paired_ret = list(zip(raw_r, human_r))

    SHRINKAGE = 0.6
    SKIP_THRESHOLD = 0.5

    # ── 方法0: 无校准 (baseline) ──
    raw_mae_i = mae(raw_i, human_i)
    raw_mae_r = mae(raw_r, human_r)
    raw_bias_i = bias(raw_i, human_i)
    raw_bias_r = bias(raw_r, human_r)

    # ── 方法1: In-sample median offset + shrinkage (Phase C报告值) ──
    in_sample_offsets_i = [h - l for l, h in paired_int]
    in_sample_offsets_r = [h - l for l, h in paired_ret]
    in_sample_median_i = statistics.median(in_sample_offsets_i)
    in_sample_median_r = statistics.median(in_sample_offsets_r)
    in_sample_mo_i = [max(1.0, min(10.0, round(v + SHRINKAGE * in_sample_median_i, 1))) for v in raw_i]
    in_sample_mo_r = [max(1.0, min(10.0, round(v + SHRINKAGE * in_sample_median_r, 1))) for v in raw_r]
    in_sample_mae_i = mae(in_sample_mo_i, human_i)
    in_sample_mae_r = mae(in_sample_mo_r, human_r)

    # ── 方法2: LOOCV median offset + shrinkage ──
    loocv_mo_i = []
    loocv_mo_r = []
    for i in range(n):
        train_int = [paired_int[j] for j in range(n) if j != i]
        train_ret = [paired_ret[j] for j in range(n) if j != i]
        med_i = statistics.median([h - l for l, h in train_int])
        med_r = statistics.median([h - l for l, h in train_ret])
        # smart-skip check (用train的median)
        if abs(med_i) < SKIP_THRESHOLD:
            loocv_mo_i.append(raw_i[i])
        else:
            loocv_mo_i.append(max(1.0, min(10.0, round(raw_i[i] + SHRINKAGE * med_i, 1))))
        if abs(med_r) < SKIP_THRESHOLD:
            loocv_mo_r.append(raw_r[i])
        else:
            loocv_mo_r.append(max(1.0, min(10.0, round(raw_r[i] + SHRINKAGE * med_r, 1))))

    loocv_mae_i = mae(loocv_mo_i, human_i)
    loocv_mae_r = mae(loocv_mo_r, human_r)
    loocv_bias_i = bias(loocv_mo_i, human_i)
    loocv_bias_r = bias(loocv_mo_r, human_r)

    # ── 方法3: LOOCV 纯分位数映射 ──
    loocv_qm_i = []
    loocv_qm_r = []
    for i in range(n):
        train_int = [paired_int[j] for j in range(n) if j != i]
        train_ret = [paired_ret[j] for j in range(n) if j != i]
        qm_map_i = build_quantile_map_loocv(train_int)
        qm_map_r = build_quantile_map_loocv(train_ret)
        loocv_qm_i.append(round(qm_map_i(raw_i[i]), 1))
        loocv_qm_r.append(round(qm_map_r(raw_r[i]), 1))

    loocv_qm_mae_i = mae(loocv_qm_i, human_i)
    loocv_qm_mae_r = mae(loocv_qm_r, human_r)
    loocv_qm_bias_i = bias(loocv_qm_i, human_i)

    # ── 方法4: LOOCV 分位数+shrinkage ──
    loocv_blend_i = []
    loocv_blend_r = []
    for i in range(n):
        train_int = [paired_int[j] for j in range(n) if j != i]
        train_ret = [paired_ret[j] for j in range(n) if j != i]
        med_i = statistics.median([h - l for l, h in train_int])
        med_r = statistics.median([h - l for l, h in train_ret])
        qm_map_i = build_quantile_map_loocv(train_int)
        qm_map_r = build_quantile_map_loocv(train_ret)
        if abs(med_i) < SKIP_THRESHOLD:
            loocv_blend_i.append(raw_i[i])
        else:
            loocv_blend_i.append(round((1 - SHRINKAGE) * raw_i[i] + SHRINKAGE * qm_map_i(raw_i[i]), 1))
        if abs(med_r) < SKIP_THRESHOLD:
            loocv_blend_r.append(raw_r[i])
        else:
            loocv_blend_r.append(round((1 - SHRINKAGE) * raw_r[i] + SHRINKAGE * qm_map_r(raw_r[i]), 1))

    loocv_blend_mae_i = mae(loocv_blend_i, human_i)
    loocv_blend_mae_r = mae(loocv_blend_r, human_r)

    # ── 统计显著性: 配对差异检验 ──
    # 对每个章节，计算 |raw_error| - |calibrated_error|
    # 如果 >0，说明校准改善了这个章节
    raw_errors_i = [abs(r - h) for r, h in zip(raw_i, human_i)]
    mo_errors_i = [abs(c - h) for c, h in zip(loocv_mo_i, human_i)]
    diffs_i = [re - ce for re, ce in zip(raw_errors_i, mo_errors_i)]  # >0 = 校准改善

    z_stat, p_val = wilcoxon_signed_rank(diffs_i)

    # ── 输出对比表 ──
    print(f"\n  +----------------------------------------------------------------------+")
    print(f"  |  Intensity MAE 对比 (LOOCV vs In-Sample)                             |")
    print(f"  +----------------------------------------------------------------------+")
    print(f"  |  无校准 (baseline):              MAE = {raw_mae_i:.3f}  bias = {raw_bias_i:+.3f}                  |")
    print(f"  |  In-sample MO+shrink (Phase C):  MAE = {in_sample_mae_i:.3f}  bias = {bias(in_sample_mo_i, human_i):+.3f}                  |")
    print(f"  |  LOOCV MO+shrink:                MAE = {loocv_mae_i:.3f}  bias = {loocv_bias_i:+.3f}                  |")
    print(f"  |  LOOCV 纯分位数映射:             MAE = {loocv_qm_mae_i:.3f}  bias = {loocv_qm_bias_i:+.3f}                  |")
    print(f"  |  LOOCV 分位数+shrinkage:         MAE = {loocv_blend_mae_i:.3f}  bias = {bias(loocv_blend_i, human_i):+.3f}                  |")
    print(f"  +----------------------------------------------------------------------+")

    print(f"\n  +----------------------------------------------------------------------+")
    print(f"  |  Retention MAE 对比                                                  |")
    print(f"  +----------------------------------------------------------------------+")
    print(f"  |  无校准 (baseline):              MAE = {raw_mae_r:.3f}  bias = {raw_bias_r:+.3f}                  |")
    print(f"  |  In-sample MO+shrink (Phase C):  MAE = {in_sample_mae_r:.3f}  bias = {bias(in_sample_mo_r, human_r):+.3f}                  |")
    print(f"  |  LOOCV MO+shrink:                MAE = {loocv_mae_r:.3f}  bias = {loocv_bias_r:+.3f}                  |")
    print(f"  |  LOOCV 纯分位数映射:             MAE = {loocv_qm_mae_r:.3f}  bias = {bias(loocv_qm_r, human_r):+.3f}                  |")
    print(f"  |  LOOCV 分位数+shrinkage:         MAE = {loocv_blend_mae_r:.3f}  bias = {bias(loocv_blend_r, human_r):+.3f}                  |")
    print(f"  +----------------------------------------------------------------------+")

    # ── In-sample bias 量化 ──
    bias_gap_i = in_sample_mae_i - loocv_mae_i
    bias_gap_r = in_sample_mae_r - loocv_mae_r
    print(f"\n  In-sample bias (In-sample MAE - LOOCV MAE):")
    print(f"    Intensity: {bias_gap_i:+.3f} ({'In-sample更乐观' if bias_gap_i < 0 else 'LOOCV更乐观'})")
    print(f"    Retention: {bias_gap_r:+.3f} ({'In-sample更乐观' if bias_gap_r < 0 else 'LOOCV更乐观'})")

    # ── 统计显著性 ──
    print(f"\n  统计显著性检验 (Wilcoxon signed-rank, MO+shrinkage vs 无校准):")
    print(f"    Intensity: z = {z_stat:.3f}, p = {p_val:.4f} {'(显著)' if p_val < 0.05 else '(不显著)'}")
    improved = sum(1 for d in diffs_i if d > 0)
    worsened = sum(1 for d in diffs_i if d < 0)
    unchanged = sum(1 for d in diffs_i if d == 0)
    print(f"    改善: {improved}/{n} 章, 恶化: {worsened}/{n} 章, 不变: {unchanged}/{n} 章")

    # ── 逐章对比 (LOOCV) ──
    print(f"\n  逐章LOOCV对比 (Intensity):")
    print(f"  {'book':<12} {'ch':>5} {'raw':>5} {'mo_loocv':>8} {'qm_loocv':>8} {'human':>5} {'raw_err':>7} {'mo_err':>7} {'qm_err':>7}")
    print(f"  {'-'*12} {'-'*5} {'-'*5} {'-'*8} {'-'*8} {'-'*5} {'-'*7} {'-'*7} {'-'*7}")
    for i, r in enumerate(data):
        raw_err = abs(raw_i[i] - human_i[i])
        mo_err = abs(loocv_mo_i[i] - human_i[i])
        qm_err = abs(loocv_qm_i[i] - human_i[i])
        flag = ""
        if mo_err < raw_err:
            flag = "[OK]"
        elif mo_err > raw_err:
            flag = "[X]"
        print(f"  {r['book']:<12} {r['ch_num']:>5} {raw_i[i]:>5.1f} {loocv_mo_i[i]:>8.1f} {loocv_qm_i[i]:>8.1f} {human_i[i]:>5.1f} {raw_err:>7.2f} {mo_err:>7.2f} {qm_err:>7.2f} {flag}")

    # ── ch1738 特别关注 ──
    ch1738_idx = next((i for i, r in enumerate(data) if r["ch_num"] == 1738 and r["book"] == "末世大回炉"), None)
    if ch1738_idx is not None:
        print(f"\n  [FOCUS] ch1738 (信息高潮 vs 爽感不足):")
        print(f"    raw={raw_i[ch1738_idx]:.1f} -> mo_loocv={loocv_mo_i[ch1738_idx]:.1f} -> qm_loocv={loocv_qm_i[ch1738_idx]:.1f} (human={human_i[ch1738_idx]:.1f})")
        print(f"    误差: raw={abs(raw_i[ch1738_idx]-human_i[ch1738_idx]):.1f} -> mo={abs(loocv_mo_i[ch1738_idx]-human_i[ch1738_idx]):.1f} -> qm={abs(loocv_qm_i[ch1738_idx]-human_i[ch1738_idx]):.1f}")

    # ── 最终判定 ──
    print(f"\n  {'='*70}")
    print(f"  最终判定")
    print(f"  {'='*70}")
    improvement_i = (raw_mae_i - loocv_mae_i) / raw_mae_i * 100
    improvement_r = (raw_mae_r - loocv_mae_r) / raw_mae_r * 100
    print(f"  Intensity: MAE {raw_mae_i:.3f} -> {loocv_mae_i:.3f} (LOOCV), 改善 {improvement_i:+.1f}%")
    print(f"  Retention:  MAE {raw_mae_r:.3f} -> {loocv_mae_r:.3f} (LOOCV), 改善 {improvement_r:+.1f}%")
    print(f"  统计显著性: p = {p_val:.4f} ({'显著' if p_val < 0.05 else '不显著'})")
    if loocv_mae_i < raw_mae_i and p_val < 0.05:
        print(f"  [PASS] 校准在LOOCV下有效且统计显著")
    elif loocv_mae_i < raw_mae_i:
        print(f"  [MARGINAL] 校准在LOOCV下有改善但不统计显著 (n={n}太小)")
    else:
        print(f"  [FAIL] 校准在LOOCV下无效或恶化")

    # 保存结果
    out_path = PROJECT_ROOT / "data" / "reports" / "末世" / "loocv_calibrate.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "n_samples": n,
            "shrinkage": SHRINKAGE,
            "in_sample_median_offset_i": in_sample_median_i,
            "in_sample_median_offset_r": in_sample_median_r,
            "raw_mae_i": raw_mae_i,
            "in_sample_mae_i": in_sample_mae_i,
            "loocv_mae_i": loocv_mae_i,
            "loocv_qm_mae_i": loocv_qm_mae_i,
            "loocv_blend_mae_i": loocv_blend_mae_i,
            "raw_mae_r": raw_mae_r,
            "in_sample_mae_r": in_sample_mae_r,
            "loocv_mae_r": loocv_mae_r,
            "loocv_qm_mae_r": loocv_qm_mae_r,
            "loocv_blend_mae_r": loocv_blend_mae_r,
            "wilcoxon_z": z_stat,
            "wilcoxon_p": p_val,
            "improved_chapters": improved,
            "worsened_chapters": worsened,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n  结果已保存: {out_path}")


if __name__ == "__main__":
    main()
