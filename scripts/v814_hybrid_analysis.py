#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
v814_hybrid_analysis.py — 混合策略对比分析
==========================================
在 v8.14 已有数据(absolute + reference 47章)上，测试多种混合策略：
  1. Simple Average: (abs + ref) / 2
  2. Weighted: w*abs + (1-w)*ref  (w=0.3/0.5/0.7)
  3. Bias-Corrected: abs - population_bias_diff
  4. Per-Chapter Correction: abs - alpha*(abs - ref)  (alpha=0.3/0.5/0.7)

纯计算，不需要 LLM 调用。

用法:
  $env:PYTHONUTF8=1
  D:\miniconda3\envs\llm-shared\python.exe scripts/v814_hybrid_analysis.py

输出:
  data/reports/末世/v8.14_hybrid_analysis_report.md
"""
import sys
import os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

os.environ["PYTHONUTF8"] = "1"

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def _compute_metrics(human_vals, predicted_vals):
    """Compute MAE, Bias, Pearson r for paired values."""
    pairs = [(h, p) for h, p in zip(human_vals, predicted_vals)
             if p is not None and h is not None]
    if len(pairs) < 3:
        return {"n": len(pairs), "mae": None, "bias": None, "r": None}

    h_vals = [p[0] for p in pairs]
    p_vals = [p[1] for p in pairs]
    n = len(pairs)

    mae = sum(abs(h - p) for h, p in pairs) / n
    bias = sum(p - h for h, p in pairs) / n

    mean_h = sum(h_vals) / n
    mean_p = sum(p_vals) / n
    cov = sum((h_vals[i] - mean_h) * (p_vals[i] - mean_p) for i in range(n))
    std_h = (sum((h - mean_h) ** 2 for h in h_vals)) ** 0.5
    std_p = (sum((p - mean_p) ** 2 for p in p_vals)) ** 0.5
    r = cov / (std_h * std_p) if std_h > 0 and std_p > 0 else 0.0

    return {"n": n, "mae": round(mae, 3), "bias": round(bias, 3), "r": round(r, 4)}


def main():
    # Load v8.14 data
    data_path = PROJECT_ROOT / "data" / "reports" / "末世" / "v8.14_reference_scoring_data.json"
    if not data_path.exists():
        print("ERROR: v8.14 data not found. Run v814_reference_scoring.py first.")
        sys.exit(1)

    with open(data_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    results = data["results"]
    print(f"Loaded {len(results)} chapters from v8.14 data")

    # Extract arrays
    human_i = [r["human_intensity"] for r in results]
    human_r = [r["human_retention"] for r in results]
    abs_i = [r["fresh_abs_intensity"] for r in results]
    abs_r = [r["fresh_abs_retention"] for r in results]
    ref_i = [r["ref_intensity"] for r in results]
    ref_r = [r["ref_retention"] for r in results]

    # Compute baseline metrics
    abs_int_m = _compute_metrics(human_i, abs_i)
    abs_ret_m = _compute_metrics(human_r, abs_r)
    ref_int_m = _compute_metrics(human_i, ref_i)
    ref_ret_m = _compute_metrics(human_r, ref_r)

    print(f"\nBaseline:")
    print(f"  Absolute:  MAE_I={abs_int_m['mae']} Bias_I={abs_int_m['bias']:+.3f} r_I={abs_int_m['r']}")
    print(f"             MAE_R={abs_ret_m['mae']} Bias_R={abs_ret_m['bias']:+.3f} r_R={abs_ret_m['r']}")
    print(f"  Reference: MAE_I={ref_int_m['mae']} Bias_I={ref_int_m['bias']:+.3f} r_I={ref_int_m['r']}")
    print(f"             MAE_R={ref_ret_m['mae']} Bias_R={ref_ret_m['bias']:+.3f} r_R={ref_ret_m['r']}")

    # === Strategy definitions ===
    strategies = []

    # 1. Simple Average
    strategies.append(("Simple Avg (50/50)", 0.5, 0.5, None))

    # 2. Weighted combinations
    for w_abs in [0.3, 0.4, 0.6, 0.7]:
        strategies.append((f"Weighted ({w_abs:.1f}/{1-w_abs:.1f})", w_abs, 1-w_abs, None))

    # 3. Bias-Corrected (population level)
    # hybrid = abs - (abs_bias - ref_bias) = abs - bias_diff
    bias_diff_i = abs_int_m["bias"] - ref_int_m["bias"]  # 0.904 - 0.415 = 0.489
    bias_diff_r = abs_ret_m["bias"] - ref_ret_m["bias"]  # 0.670 - 0.181 = 0.489
    bc_i = [a - bias_diff_i if a is not None else None for a in abs_i]
    bc_r = [a - bias_diff_r if a is not None else None for a in abs_r]
    bc_int_m = _compute_metrics(human_i, bc_i)
    bc_ret_m = _compute_metrics(human_r, bc_r)
    strategies.append(("Bias-Corrected (pop)", None, None, (bc_int_m, bc_ret_m, bc_i, bc_r)))

    # 4. Per-Chapter Correction: abs - alpha*(abs - ref)
    for alpha in [0.3, 0.5, 0.7]:
        hi = []
        hr = []
        for ai, ri in zip(abs_i, ref_i):
            if ai is not None and ri is not None:
                hi.append(ai - alpha * (ai - ri))
            else:
                hi.append(ai)
        for ar, rr in zip(abs_r, ref_r):
            if ar is not None and rr is not None:
                hr.append(ar - alpha * (ar - rr))
            else:
                hr.append(ar)
        hi = [round(v, 1) if v is not None else None for v in hi]
        hr = [round(v, 1) if v is not None else None for v in hr]
        strategies.append((f"Per-Chapter α={alpha}", None, None,
                          (_compute_metrics(human_i, hi), _compute_metrics(human_r, hr), hi, hr)))

    # === Compute metrics for weighted strategies ===
    all_metrics = []
    for name, w_abs, w_ref, special in strategies:
        if special is not None:
            int_m, ret_m, _, _ = special
        else:
            # Weighted combination
            hi = []
            hr = []
            for ai, ri in zip(abs_i, ref_i):
                if ai is not None and ri is not None:
                    hi.append(round(w_abs * ai + w_ref * ri, 1))
                elif ai is not None:
                    hi.append(ai)
                elif ri is not None:
                    hi.append(ri)
                else:
                    hi.append(None)
            for ar, rr in zip(abs_r, ref_r):
                if ar is not None and rr is not None:
                    hr.append(round(w_abs * ar + w_ref * rr, 1))
                elif ar is not None:
                    hr.append(ar)
                elif rr is not None:
                    hr.append(rr)
                else:
                    hr.append(None)
            int_m = _compute_metrics(human_i, hi)
            ret_m = _compute_metrics(human_r, hr)
        all_metrics.append((name, int_m, ret_m))

    # === Print comparison table ===
    print(f"\n{'='*90}")
    print(f"  Hybrid Strategy Comparison (N=47)")
    print(f"{'='*90}")
    print(f"{'Strategy':<30} {'MAE_I':>7} {'Bias_I':>8} {'r_I':>7} {'MAE_R':>7} {'Bias_R':>8} {'r_R':>7}")
    print(f"{'-'*30} {'-'*7} {'-'*8} {'-'*7} {'-'*7} {'-'*8} {'-'*7}")
    print(f"{'Absolute (baseline)':<30} {abs_int_m['mae']:>7} {abs_int_m['bias']:>+8.3f} {abs_int_m['r']:>7} {abs_ret_m['mae']:>7} {abs_ret_m['bias']:>+8.3f} {abs_ret_m['r']:>7}")
    print(f"{'Reference (baseline)':<30} {ref_int_m['mae']:>7} {ref_int_m['bias']:>+8.3f} {ref_int_m['r']:>7} {ref_ret_m['mae']:>7} {ref_ret_m['bias']:>+8.3f} {ref_ret_m['r']:>7}")
    print(f"{'-'*30} {'-'*7} {'-'*8} {'-'*7} {'-'*7} {'-'*8} {'-'*7}")
    for name, int_m, ret_m in all_metrics:
        print(f"{name:<30} {int_m['mae']:>7} {int_m['bias']:>+8.3f} {int_m['r']:>7} {ret_m['mae']:>7} {ret_m['bias']:>+8.3f} {ret_m['r']:>7}")

    # === Find best strategies ===
    best_mae_i = min(all_metrics, key=lambda x: x[1]['mae'] if x[1]['mae'] else 999)
    best_mae_r = min(all_metrics, key=lambda x: x[2]['mae'] if x[2]['mae'] else 999)
    best_bias_i = min(all_metrics, key=lambda x: abs(x[1]['bias']) if x[1]['bias'] is not None else 999)
    best_r_i = max(all_metrics, key=lambda x: x[1]['r'] if x[1]['r'] is not None else 0)

    print(f"\n{'='*90}")
    print(f"  Best Strategies:")
    print(f"    Best MAE_I:  {best_mae_i[0]}  (MAE={best_mae_i[1]['mae']}, Bias={best_mae_i[1]['bias']:+.3f})")
    print(f"    Best MAE_R:  {best_mae_r[0]}  (MAE={best_mae_r[2]['mae']}, Bias={best_mae_r[2]['bias']:+.3f})")
    print(f"    Best Bias_I: {best_bias_i[0]}  (Bias={best_bias_i[1]['bias']:+.3f}, MAE={best_bias_i[1]['mae']})")
    print(f"    Best r_I:    {best_r_i[0]}     (r={best_r_i[1]['r']}, MAE={best_r_i[1]['mae']})")
    print(f"{'='*90}")

    # === Generate markdown report ===
    report_dir = PROJECT_ROOT / "data" / "reports" / "末世"
    report_dir.mkdir(parents=True, exist_ok=True)
    md_path = report_dir / "v8.14_hybrid_analysis_report.md"

    lines = []
    lines.append("# v8.14 混合策略对比分析报告\n")
    lines.append("> 生成时间: 2026-07-14 | Phase A1 补充分析\n")
    lines.append("> 数据来源: v8.14_reference_scoring_data.json (N=47, 100%成功率)\n")
    lines.append("> 目标: 找到同时改善 Bias 和 MAE/r 的混合策略\n")
    lines.append("")

    lines.append("## 一、基线对比\n")
    lines.append("| 方法 | MAE_I | Bias_I | r_I | MAE_R | Bias_R | r_R |")
    lines.append("|------|-------|--------|-----|-------|--------|-----|")
    lines.append(f"| 绝对评分 (absolute) | {abs_int_m['mae']} | {abs_int_m['bias']:+.3f} | {abs_int_m['r']} | {abs_ret_m['mae']} | {abs_ret_m['bias']:+.3f} | {abs_ret_m['r']} |")
    lines.append(f"| 参考评分 (reference) | {ref_int_m['mae']} | {ref_int_m['bias']:+.3f} | {ref_int_m['r']} | {ref_ret_m['mae']} | {ref_ret_m['bias']:+.3f} | {ref_ret_m['r']} |")
    lines.append("")
    lines.append("**核心矛盾**: absolute 的 MAE/r 更好但 Bias 高; reference 的 Bias 低但 MAE/r 差。\n")
    lines.append("")

    lines.append("## 二、混合策略定义\n")
    lines.append("### 1. 加权平均\n")
    lines.append("`hybrid = w * absolute + (1-w) * reference`\n")
    lines.append("- w=1.0: 纯绝对评分 (高Bias, 好MAE/r)")
    lines.append("- w=0.0: 纯参考评分 (低Bias, 差MAE/r)")
    lines.append("- w=0.5: 简单平均\n")
    lines.append("")
    lines.append("### 2. 群体Bias校正\n")
    lines.append("`hybrid = absolute - (Bias_abs - Bias_ref)`\n")
    lines.append(f"- Bias差值: intensity={bias_diff_i:.3f}, retention={bias_diff_r:.3f}")
    lines.append("- 仅平移，不改变方差/排序，理论上保留r\n")
    lines.append("")
    lines.append("### 3. 逐章校正\n")
    lines.append("`hybrid = absolute - α * (absolute - reference)`\n")
    lines.append("- α=0: 纯绝对, α=1: 纯参考")
    lines.append("- α=0.5: 当 absolute > reference 时下调(减Bias), 当 absolute < reference 时上调(增精度)\n")
    lines.append("")

    lines.append("## 三、对比结果\n")
    lines.append("| 策略 | MAE_I | Bias_I | r_I | MAE_R | Bias_R | r_R |")
    lines.append("|------|-------|--------|-----|-------|--------|-----|")
    lines.append(f"| **绝对评分(baseline)** | **{abs_int_m['mae']}** | **{abs_int_m['bias']:+.3f}** | **{abs_int_m['r']}** | **{abs_ret_m['mae']}** | **{abs_ret_m['bias']:+.3f}** | **{abs_ret_m['r']}** |")
    lines.append(f"| **参考评分(baseline)** | **{ref_int_m['mae']}** | **{ref_int_m['bias']:+.3f}** | **{ref_int_m['r']}** | **{ref_ret_m['mae']}** | **{ref_ret_m['bias']:+.3f}** | **{ref_ret_m['r']}** |")
    lines.append("|---|---|---|---|---|---|---|")
    for name, int_m, ret_m in all_metrics:
        lines.append(f"| {name} | {int_m['mae']} | {int_m['bias']:+.3f} | {int_m['r']} | {ret_m['mae']} | {ret_m['bias']:+.3f} | {ret_m['r']} |")
    lines.append("")

    lines.append("## 四、最佳策略\n")
    lines.append(f"- **最佳MAE_I**: {best_mae_i[0]} (MAE={best_mae_i[1]['mae']}, Bias={best_mae_i[1]['bias']:+.3f})\n")
    lines.append(f"- **最佳MAE_R**: {best_mae_r[0]} (MAE={best_mae_r[2]['mae']}, Bias={best_mae_r[2]['bias']:+.3f})\n")
    lines.append(f"- **最佳Bias_I**: {best_bias_i[0]} (Bias={best_bias_i[1]['bias']:+.3f}, MAE={best_bias_i[1]['mae']})\n")
    lines.append(f"- **最佳r_I**: {best_r_i[0]} (r={best_r_i[1]['r']}, MAE={best_r_i[1]['mae']})\n")
    lines.append("")

    # === Conclusion ===
    lines.append("## 五、结论\n")

    # Find the strategy with best overall balance (lowest MAE with |Bias| < 0.5)
    balanced = [(name, im, rm) for name, im, rm in all_metrics
                if im.get('bias') is not None and abs(im['bias']) < 0.5 and im.get('mae') is not None]
    if balanced:
        best_balanced = min(balanced, key=lambda x: x[1]['mae'] + x[2]['mae'])
        lines.append(f"### 最佳平衡策略 (|Bias_I| < 0.5)\n")
        lines.append(f"**{best_balanced[0]}**:\n")
        lines.append(f"- Intensity: MAE={best_balanced[1]['mae']}, Bias={best_balanced[1]['bias']:+.3f}, r={best_balanced[1]['r']}")
        lines.append(f"- Retention:  MAE={best_balanced[2]['mae']}, Bias={best_balanced[2]['bias']:+.3f}, r={best_balanced[2]['r']}\n")

        # Compare with baselines
        lines.append("### 与基线对比\n")
        lines.append(f"| 指标 | 绝对评分 | 参考评分 | **{best_balanced[0]}** |")
        lines.append(f"|------|---------|---------|------|")
        lines.append(f"| MAE_I | {abs_int_m['mae']} | {ref_int_m['mae']} | **{best_balanced[1]['mae']}** |")
        lines.append(f"| Bias_I | {abs_int_m['bias']:+.3f} | {ref_int_m['bias']:+.3f} | **{best_balanced[1]['bias']:+.3f}** |")
        lines.append(f"| r_I | {abs_int_m['r']} | {ref_int_m['r']} | **{best_balanced[1]['r']}** |")
        lines.append(f"| MAE_R | {abs_ret_m['mae']} | {ref_ret_m['mae']} | **{best_balanced[2]['mae']}** |")
        lines.append(f"| Bias_R | {abs_ret_m['bias']:+.3f} | {ref_ret_m['bias']:+.3f} | **{best_balanced[2]['bias']:+.3f}** |")
        lines.append(f"| r_R | {abs_ret_m['r']} | {ref_ret_m['r']} | **{best_balanced[2]['r']}** |")
        lines.append("")
    else:
        lines.append("### 无策略同时满足 |Bias| < 0.5 和 MAE 改善\n")

    lines.append("### 推荐\n")
    lines.append("1. **生产使用**: 群体Bias校正 — 仅平移absolute分数，保留r/排序，Bias接近reference\n")
    lines.append("2. **精度优先**: 逐章校正α=0.3 — 轻度参考校正，MAE/r接近absolute，Bias改善\n")
    lines.append("3. **平衡选择**: 加权0.7/0.3 — 70%绝对+30%参考\n")
    lines.append("")

    with open(md_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))
    print(f"\n  Report saved: {md_path}")


if __name__ == "__main__":
    main()
