#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""
convert_golden.py — 人工标注CSV → golden_set.json + 重测一致性报告
====================================================================
读取 data/processed/末世/scores/human_golden.csv（标注工具导出），
分离原始标注和重测标注，输出：
  1. golden_set.json — 供 apply_golden_set_calibration() 使用（仅非重测数据）
  2. 重测一致性报告 — Test-Retest Reliability 分析

用法:
  D:\miniconda3\envs\llm-shared\python.exe scripts/convert_golden.py

输入: data/processed/末世/scores/human_golden.csv
输出:
  - data/processed/末世/scores/golden_set.json
  - 控制台打印重测一致性报告
"""
import csv
import json
import sys
import statistics
from pathlib import Path
from collections import defaultdict

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent.parent
INPUT_CSV = PROJECT_ROOT / "data" / "golden" / "末世" / "human_golden.csv"  # v8.8: 保护目录
OUTPUT_JSON = PROJECT_ROOT / "data" / "processed" / "末世" / "scores" / "golden_set.json"


def main():
    if not INPUT_CSV.exists():
        print(f"[ERROR] 找不到 {INPUT_CSV}")
        print("  请先在标注工具中导出 human_golden.csv")
        return

    # 读取CSV
    with open(INPUT_CSV, "r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    print(f"读取到 {len(rows)} 条标注记录")

    # 分离原始标注和重测标注
    originals = []
    retests = []
    for r in rows:
        is_retest = r.get("is_retest", "false").strip().lower() == "true"
        if is_retest:
            retests.append(r)
        else:
            originals.append(r)

    print(f"  原始标注: {len(originals)} 条")
    print(f"  重测标注: {len(retests)} 条")

    # ── 构建 golden_set.json ──
    # 只用原始标注，不用重测标注（重测用于一致性验证，不用于校准）
    golden_set = []
    seen_keys = set()
    for r in originals:
        try:
            book = r["book"]
            ch_num = int(r["ch_num"])
            # 去重：同一(book, ch_num)只保留最后一条
            dedup_key = (book, ch_num)
            if dedup_key in seen_keys:
                golden_set = [g for g in golden_set if (g["book"], g["ch_num"]) != dedup_key]
            seen_keys.add(dedup_key)
            # 范围验证
            hi = float(r["human_intensity"])
            hr = float(r["human_retention"])
            if not (1 <= hi <= 10) or not (1 <= hr <= 10):
                print(f"  [WARN] 分数超出1-10范围: {book}_ch{ch_num}: intensity={hi}, retention={hr}")
                continue
            entry = {
                "book": book,
                "ch_num": ch_num,
                "human_intensity": hi,
                "human_retention": hr,
            }
            # 附加元数据（可选，不影响校准逻辑）
            if r.get("pacing"):
                entry["pacing"] = float(r["pacing"])
            if r.get("immersion"):
                entry["immersion"] = float(r["immersion"])
            if r.get("emotion"):
                entry["emotion"] = float(r["emotion"])
            if r.get("tags"):
                entry["tags"] = r["tags"]
            if r.get("gap_reasons"):
                entry["gap_reasons"] = r["gap_reasons"]
            if r.get("confidence"):
                entry["confidence"] = r["confidence"]
            if r.get("timestamp"):
                entry["timestamp"] = r["timestamp"]
            golden_set.append(entry)
        except (ValueError, KeyError) as e:
            print(f"  [WARN] 跳过无效行: {r.get('book','?')}_ch{r.get('ch_num','?')}: {e}")

    # 保存 golden_set.json
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(golden_set, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] golden_set.json 已保存: {OUTPUT_JSON}")
    print(f"  包含 {len(golden_set)} 条非重测标注")

    # ── 重测一致性报告 ──
    if not retests:
        print("\n[INFO] 没有重测标注，跳过一致性分析")
        print("  （标注满15章后系统会自动插入3章重测）")
        return

    print(f"\n{'='*70}")
    print("  重测一致性报告 (Test-Retest Reliability)")
    print(f"{'='*70}")

    # 构建 (book, ch_num) → original 标注的映射
    orig_map = {}
    for r in originals:
        key = (r["book"], int(r["ch_num"]))
        orig_map[key] = r

    # 匹配重测对
    pairs = []
    unmatched = []
    for rt in retests:
        key = (rt["book"], int(rt["ch_num"]))
        if key in orig_map:
            pairs.append((orig_map[key], rt))
        else:
            unmatched.append(rt)

    if unmatched:
        print(f"  [WARN] {len(unmatched)} 条重测标注找不到对应的原始标注:")
        for rt in unmatched:
            print(f"    {rt['book']} ch{rt['ch_num']}")

    if not pairs:
        print("  [WARN] 没有有效的重测对，无法计算一致性")
        return

    print(f"  有效重测对: {len(pairs)} 对\n")

    # 计算一致性指标
    int_diffs = []
    ret_diffs = []
    print(f"  {'book':<12} {'ch':>5} {'orig_i':>6} {'retest_i':>7} {'Δi':>5} {'orig_r':>6} {'retest_r':>7} {'Δr':>5} {'flag':>6}")
    print(f"  {'-'*12} {'-'*5} {'-'*6} {'-'*7} {'-'*5} {'-'*6} {'-'*7} {'-'*5} {'-'*6}")

    for orig, rt in pairs:
        oi = float(orig["human_intensity"])
        ri = float(rt["human_intensity"])
        orr = float(orig["human_retention"])
        rr = float(rt["human_retention"])
        di = ri - oi
        dr = rr - orr
        int_diffs.append(abs(di))
        ret_diffs.append(abs(dr))

        # 一致性判定阈值: 差异 > 1.5 分为不一致
        flag = ""
        if abs(di) > 1.5 or abs(dr) > 1.5:
            flag = "⚠ 不一致"
        elif abs(di) > 1.0 or abs(dr) > 1.0:
            flag = "~ 边界"

        print(f"  {orig['book']:<12} {orig['ch_num']:>5} {oi:>6.1f} {ri:>7.1f} {di:>+5.1f} {orr:>6.1f} {rr:>7.1f} {dr:>+5.1f} {flag:>6}")

    # 统计摘要
    print(f"\n  {'='*50}")
    print(f"  统计摘要 (N={len(pairs)})")
    print(f"  {'='*50}")

    mae_i = statistics.mean(int_diffs)
    mae_r = statistics.mean(ret_diffs)
    max_i = max(int_diffs)
    max_r = max(ret_diffs)

    print(f"  爽点强度 MAE: {mae_i:.2f} (最大 {max_i:.1f})")
    print(f"  读者留存 MAE: {mae_r:.2f} (最大 {max_r:.1f})")

    # ICC简化版: 1 - (误差方差 / 总方差)
    if len(pairs) >= 3:
        orig_ints = [float(o["human_intensity"]) for o, _ in pairs]
        retest_ints = [float(r["human_intensity"]) for _, r in pairs]
        orig_rets = [float(o["human_retention"]) for o, _ in pairs]
        retest_rets = [float(r["human_retention"]) for _, r in pairs]

        var_total_i = statistics.pvariance(orig_ints + retest_ints) if len(orig_ints + retest_ints) > 1 else 0
        var_error_i = statistics.mean([d**2 for d in int_diffs]) / 2
        icc_i = max(0, 1 - var_error_i / var_total_i) if var_total_i > 0 else 0

        var_total_r = statistics.pvariance(orig_rets + retest_rets) if len(orig_rets + retest_rets) > 1 else 0
        var_error_r = statistics.mean([d**2 for d in ret_diffs]) / 2
        icc_r = max(0, 1 - var_error_r / var_total_r) if var_total_r > 0 else 0

        print(f"  爽点强度 ICC(简化): {icc_i:.3f}")
        print(f"  读者留存 ICC(简化): {icc_r:.3f}")

    # 质量评级
    overall_mae = (mae_i + mae_r) / 2
    if overall_mae < 0.5:
        grade = "优秀 (一致性极高)"
    elif overall_mae < 1.0:
        grade = "良好 (一致性可接受)"
    elif overall_mae < 1.5:
        grade = "一般 (存在边界模糊章节)"
    else:
        grade = "较差 (建议复核不一致章节)"

    print(f"\n  总体一致性: {grade}")
    print(f"  (MAE < 1.0=良好, 1.0-1.5=一般, >1.5=需复核)")

    # 建议
    inconsistent = [p for p in pairs if abs(float(p[1]["human_intensity"]) - float(p[0]["human_intensity"])) > 1.5]
    if inconsistent:
        print(f"\n  [建议] {len(inconsistent)} 章重测差异>1.5分，建议:")
        for orig, rt in inconsistent:
            print(f"    {orig['book']} ch{orig['ch_num']}: {orig['human_intensity']}→{rt['human_intensity']} "
                  f"(Δ{float(rt['human_intensity'])-float(orig['human_intensity']):+.1f})")
        print("    → 复核这些章节，确认是评分标准不明确还是疲劳导致")

    print(f"\n{'='*70}")
    print("  注: golden_set.json 仅包含原始标注，重测数据不参与校准。")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
