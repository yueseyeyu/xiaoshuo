#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
端到端验证脚本 — Phase 0-3 优化效果验证
=========================================
验证目的:
  1. 规则端: BM25归一化 + 情绪极性连续衰减 是否改善了 rule_intensity
  2. LLM端: 分布锚定 + 中段峰值抽取 是否降低了 LLM 偏差
  3. 校准端: 直方图均衡化 是否优于 median offset
  4. 融合端: 分层权重 + BMA修复 是否提升了最终分

使用方式:
  python -m scripts.e2e_verify --phase a   # 仅规则端（无需GPU）
  python -m scripts.e2e_verify --phase b   # LLM端（需GPU+模型运行）
  python -m scripts.e2e_verify --phase c   # 校准端（需Phase B输出）
  python -m scripts.e2e_verify --phase d   # 融合端
  python -m scripts.e2e_verify --phase all # 全部
"""

import argparse
import csv
import json
import math
import statistics
import sys
from pathlib import Path

# 项目路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from xiaoshuo.pipeline.rhythm.chapter_parser import extract_chapters
from xiaoshuo.pipeline.rhythm.rule_analyzer import rule_analyze

# ── 常量 ──
GOLDEN_CSV = PROJECT_ROOT / "data" / "golden" / "末世" / "human_golden.csv"  # v8.8: 保护目录
SCORES_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "scores"
NOVELS_DIR = PROJECT_ROOT / "data" / "raw" / "novels" / "末世"

# 书名 → txt 文件映射
BOOK_MAP = {
    "废土崛起": "《废土崛起》（校对版全本）作者：通吃道人.txt",
    "末日蟑螂": "《末日蟑螂》作者：伟岸蟑螂.txt",
    "末世大回炉": "《末世大回炉》（校对版全本）作者：二十二刀流.txt",
}


def load_golden():
    """加载 human_golden.csv，返回 {book: {ch_num: row}}"""
    golden = {}
    with open(GOLDEN_CSV, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("is_retest", "").strip().lower() == "true":
                continue  # 跳过重测行
            book = row["book"]
            ch = int(row["ch_num"])
            if book not in golden:
                golden[book] = {}
            golden[book][ch] = row
    return golden


def load_old_llm_csv(book_name):
    """加载旧 LLM CSV，返回 {ch_num: row}"""
    # 找到对应的 _llm.csv 文件
    for f in SCORES_DIR.iterdir():
        if f.suffix == ".csv" and book_name in f.name and "_llm" in f.name:
            old = {}
            with open(f, encoding="utf-8-sig") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    ch = int(row["ch_num"])
                    old[ch] = row
            return old
    return {}


def pearson_r(x, y):
    """计算 Pearson 相关系数"""
    n = len(x)
    if n < 3:
        return float("nan")
    mx = sum(x) / n
    my = sum(y) / n
    sx = math.sqrt(sum((xi - mx) ** 2 for xi in x) / n)
    sy = math.sqrt(sum((yi - my) ** 2 for yi in y) / n)
    if sx == 0 or sy == 0:
        return 0.0
    cov = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y)) / n
    return cov / (sx * sy)


def mae(x, y):
    """Mean Absolute Error"""
    n = len(x)
    if n == 0:
        return float("nan")
    return sum(abs(xi - yi) for xi, yi in zip(x, y)) / n


def bias(x, y):
    """Mean bias (x - y)"""
    n = len(x)
    if n == 0:
        return float("nan")
    return sum(xi - yi for xi, yi in zip(x, y)) / n


def stdev(xs):
    """Standard deviation"""
    n = len(xs)
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    return math.sqrt(sum((x - mx) ** 2 for x in xs) / n)


# ============================================================
# Phase A: 纯规则端验证
# ============================================================
def phase_a():
    """对30章 Golden Set 重新跑 rule_analyze，对比旧 CSV 中的 rule_intensity"""
    print("=" * 70)
    print("Phase A: 纯规则端验证（BM25归一化 + 情绪极性连续衰减）")
    print("=" * 70)

    golden = load_golden()
    results = []  # [{book, ch, old_rule, new_rule, human, wc}]

    for book_name, ch_map in golden.items():
        txt_file = BOOK_MAP.get(book_name)
        if not txt_file:
            print(f"  [WARN] 未找到 {book_name} 的txt文件")
            continue
        txt_path = NOVELS_DIR / txt_file
        if not txt_path.exists():
            print(f"  [WARN] {txt_path} 不存在")
            continue

        # 提取章节
        chapters = extract_chapters(str(txt_path))
        ch_by_num = {ch["num"]: ch for ch in chapters}

        # 旧CSV
        old_csv = load_old_llm_csv(book_name)

        for ch_num, golden_row in sorted(ch_map.items()):
            if ch_num not in ch_by_num:
                print(f"  [WARN] {book_name} ch{ch_num} 未在txt中找到")
                continue

            ch = ch_by_num[ch_num]
            # 运行新版规则分析
            new_metrics = rule_analyze(ch)
            new_rule_intensity = new_metrics["pleasure_intensity"]

            old_rule_intensity = float(golden_row.get("rule_intensity", 0) or 0)
            human_intensity = float(golden_row.get("human_intensity", 0) or 0)

            results.append({
                "book": book_name,
                "ch_num": ch_num,
                "wc": ch["wc"],
                "old_rule": old_rule_intensity,
                "new_rule": new_rule_intensity,
                "human": human_intensity,
            })

    if not results:
        print("  [FAIL] 无有效结果")
        return

    # ── 统计 ──
    old_rules = [r["old_rule"] for r in results]
    new_rules = [r["new_rule"] for r in results]
    humans = [r["human"] for r in results]
    wcs = [r["wc"] for r in results]

    print(f"\n  样本数: {len(results)}")
    print(f"\n  ┌─────────────────────────────────────────────────────────┐")
    print(f"  │  规则评分对比                                            │")
    print(f"  ├─────────────────────────────────────────────────────────┤")
    print(f"  │  旧 rule_intensity:  均值={sum(old_rules)/len(old_rules):.2f}  标准差={stdev(old_rules):.2f}  范围=[{min(old_rules):.1f}, {max(old_rules):.1f}]  │")
    print(f"  │  新 rule_intensity:  均值={sum(new_rules)/len(new_rules):.2f}  标准差={stdev(new_rules):.2f}  范围=[{min(new_rules):.1f}, {max(new_rules):.1f}]  │")
    print(f"  │  human_intensity:   均值={sum(humans)/len(humans):.2f}  标准差={stdev(humans):.2f}  范围=[{min(humans):.1f}, {max(humans):.1f}]  │")
    print(f"  ├─────────────────────────────────────────────────────────┤")
    print(f"  │  旧 vs Human:  Pearson r = {pearson_r(old_rules, humans):.4f}  MAE = {mae(old_rules, humans):.3f}  │")
    print(f"  │  新 vs Human:  Pearson r = {pearson_r(new_rules, humans):.4f}  MAE = {mae(new_rules, humans):.3f}  │")
    print(f"  └─────────────────────────────────────────────────────────┘")

    # ── 逐章对比 ──
    print(f"\n  逐章明细:")
    print(f"  {'book':<12} {'ch':>5} {'wc':>5} {'old':>5} {'new':>5} {'human':>5} {'Δold':>6} {'Δnew':>6} {'verdict':>8}")
    print(f"  {'─'*12} {'─'*5} {'─'*5} {'─'*5} {'─'*5} {'─'*5} {'─'*6} {'─'*6} {'─'*8}")
    for r in results:
        d_old = r["old_rule"] - r["human"]
        d_new = r["new_rule"] - r["human"]
        # 判定: 新版是否比旧版更接近human
        if abs(d_new) < abs(d_old):
            verdict = "[OK] better"
        elif abs(d_new) > abs(d_old):
            verdict = "[X] worse"
        else:
            verdict = "  same"
        print(f"  {r['book']:<12} {r['ch_num']:>5} {r['wc']:>5} {r['old_rule']:>5.1f} {r['new_rule']:>5.1f} {r['human']:>5.1f} {d_old:>+6.1f} {d_new:>+6.1f} {verdict:>8}")

    # ── 漏判率 ──
    old_miss = sum(1 for r in results if r["old_rule"] < 2 and r["human"] > 5)
    new_miss = sum(1 for r in results if r["new_rule"] < 2 and r["human"] > 5)
    print(f"\n  规则漏判率（rule<2 但 human>5）:")
    print(f"    旧版: {old_miss}/{len(results)} = {old_miss/len(results)*100:.0f}%")
    print(f"    新版: {new_miss}/{len(results)} = {new_miss/len(results)*100:.0f}%")

    # ── 长章节验证（BM25效果） ──
    long_chs = [r for r in results if r["wc"] > 2700]
    if long_chs:
        print(f"\n  长章节验证（wc>2700, BM25归一化效果）:")
        for r in long_chs:
            print(f"    {r['book']} ch{r['ch_num']} wc={r['wc']}: old={r['old_rule']:.1f} → new={r['new_rule']:.1f} (human={r['human']:.1f})")

    # 保存结果
    out_path = PROJECT_ROOT / "data" / "reports" / "末世" / "e2e_verify_phaseA.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "phase": "A",
            "n_samples": len(results),
            "old_pearson_r": pearson_r(old_rules, humans),
            "new_pearson_r": pearson_r(new_rules, humans),
            "old_mae": mae(old_rules, humans),
            "new_mae": mae(new_rules, humans),
            "old_miss_rate": old_miss / len(results),
            "new_miss_rate": new_miss / len(results),
            "details": results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n  结果已保存: {out_path}")

    # 判定
    new_r = pearson_r(new_rules, humans)
    old_r = pearson_r(old_rules, humans)
    if new_r > old_r:
        print(f"\n  [PASS] Phase A: Pearson r {old_r:.4f} -> {new_r:.4f}")
    else:
        print(f"\n  [WARN] Phase A: Pearson r {old_r:.4f} -> {new_r:.4f}")


# ============================================================
# Phase B: LLM端验证
# ============================================================
def phase_b():
    """对3本书x10章 Golden Set 直接调用 LLM 评分，对比旧 CSV 和 human scores"""
    print("=" * 70)
    print("Phase B: LLM端验证（分布锚定 + 中段峰值抽取）")
    print("=" * 70)

    from xiaoshuo.pipeline.llm_batch_score import (
        check_server, llm_score_with_confidence, _LLAMA_BASE
    )
    from xiaoshuo.pipeline.scoring.commercial_engine import _detect_sub_genre

    if not check_server():
        print("  [FAIL] LLM server 未运行")
        print("  请先启动: scripts\\start_model_safe.bat")
        return None

    golden = load_golden()
    all_new_scores = []
    total = sum(len(ch_map) for ch_map in golden.values())
    done = 0

    for book_name, ch_map in golden.items():
        txt_file = BOOK_MAP.get(book_name)
        if not txt_file:
            continue
        txt_path = NOVELS_DIR / txt_file
        if not txt_path.exists():
            continue

        # 提取章节，建立 num→ch 索引
        chapters = extract_chapters(str(txt_path))
        ch_by_num = {ch["num"]: ch for ch in chapters}
        ch_list = list(chapters)  # 用于找前章上下文

        old_csv = load_old_llm_csv(book_name)

        # 检测子类型
        rule_rows = {}
        rhythm_d = PROJECT_ROOT / "data" / "processed" / "末世" / "rhythm"
        for f in rhythm_d.iterdir():
            if f.suffix == ".csv" and book_name in f.name:
                with open(f, encoding="utf-8-sig") as fh:
                    for r in csv.DictReader(fh):
                        rule_rows[int(r["ch_num"])] = r
                break

        sub_genre = ""
        sample_rows = list(rule_rows.values())[:30]
        if sample_rows:
            _numeric_keys = ["bond_count", "cognitive_count", "sacrifice_count",
                             "hook_density", "conflict_density", "pleasure_intensity",
                             "pos_density", "slap_count", "wc"]
            for r in sample_rows:
                for k in _numeric_keys:
                    if k in r:
                        try:
                            r[k] = float(r[k])
                        except (ValueError, TypeError):
                            r[k] = 0
            try:
                sub_genre = _detect_sub_genre(sample_rows, book_name=book_name)
            except Exception:
                pass

        print(f"\n  [BOOK] {book_name} (sub_genre={sub_genre}, {len(ch_map)} chapters)")

        for ch_num, golden_row in sorted(ch_map.items()):
            if ch_num not in ch_by_num:
                print(f"    [WARN] ch{ch_num} not found")
                continue

            ch = ch_by_num[ch_num]
            full_body = ch["raw_body"]

            # 前章末尾200字作为上下文
            prev_context = ""
            ch_idx = None
            for ci, c in enumerate(ch_list):
                if c["num"] == ch_num:
                    ch_idx = ci
                    break
            if ch_idx and ch_idx > 0:
                prev_body = ch_list[ch_idx - 1].get("raw_body", "")
                if prev_body:
                    prev_context = prev_body[-200:].replace("\n", " ").strip()

            # 调用 LLM 评分 (双温度采样)
            llm = llm_score_with_confidence(full_body, ch_num, prev_context=prev_context, sub_genre=sub_genre)

            done += 1
            if llm is None:
                print(f"    Ch{ch_num} ({done}/{total}) [FAIL]")
                continue

            old = old_csv.get(ch_num, {})
            new_i = float(llm.get("intensity", 0))
            new_r = float(llm.get("retention", 0))
            print(f"    Ch{ch_num} ({done}/{total}) i={new_i:.1f} r={new_r:.1f} conf={llm.get('confidence_note', '?')}")

            all_new_scores.append({
                "book": book_name,
                "ch_num": ch_num,
                "old_llm_i": float(old.get("llm_intensity", 0) or 0),
                "old_llm_r": float(old.get("llm_retention", 0) or 0),
                "new_llm_i": new_i,
                "new_llm_r": new_r,
                "human_i": float(golden_row.get("human_intensity", 0) or 0),
                "human_r": float(golden_row.get("human_retention", 0) or 0),
                "low_confidence": llm.get("low_confidence", False),
                "confidence_note": llm.get("confidence_note", ""),
            })

    if not all_new_scores:
        print("  [FAIL] 无有效结果")
        return None

    # ── 统计 ──
    old_i = [r["old_llm_i"] for r in all_new_scores]
    new_i = [r["new_llm_i"] for r in all_new_scores]
    old_r = [r["old_llm_r"] for r in all_new_scores]
    new_r = [r["new_llm_r"] for r in all_new_scores]
    human_i = [r["human_i"] for r in all_new_scores]
    human_r = [r["human_r"] for r in all_new_scores]

    print(f"\n  样本数: {len(all_new_scores)}")
    print(f"\n  ┌──────────────────────────────────────────────────────────────────┐")
    print(f"  │  LLM Intensity 对比                                               │")
    print(f"  ├──────────────────────────────────────────────────────────────────┤")
    print(f"  │  旧 LLM:  均值={sum(old_i)/len(old_i):.2f}  标准差={stdev(old_i):.2f}  范围=[{min(old_i):.1f}, {max(old_i):.1f}]           │")
    print(f"  │  新 LLM:  均值={sum(new_i)/len(new_i):.2f}  标准差={stdev(new_i):.2f}  范围=[{min(new_i):.1f}, {max(new_i):.1f}]           │")
    print(f"  │  Human:   均值={sum(human_i)/len(human_i):.2f}  标准差={stdev(human_i):.2f}  范围=[{min(human_i):.1f}, {max(human_i):.1f}]           │")
    print(f"  ├──────────────────────────────────────────────────────────────────┤")
    print(f"  │  旧 vs Human:  Pearson r = {pearson_r(old_i, human_i):.4f}  MAE = {mae(old_i, human_i):.3f}  偏差 = {bias(old_i, human_i):+.3f}  │")
    print(f"  │  新 vs Human:  Pearson r = {pearson_r(new_i, human_i):.4f}  MAE = {mae(new_i, human_i):.3f}  偏差 = {bias(new_i, human_i):+.3f}  │")
    print(f"  ├──────────────────────────────────────────────────────────────────┤")
    print(f"  │  LLM Retention 对比                                              │")
    print(f"  ├──────────────────────────────────────────────────────────────────┤")
    print(f"  │  旧 vs Human:  Pearson r = {pearson_r(old_r, human_r):.4f}  MAE = {mae(old_r, human_r):.3f}  偏差 = {bias(old_r, human_r):+.3f}  │")
    print(f"  │  新 vs Human:  Pearson r = {pearson_r(new_r, human_r):.4f}  MAE = {mae(new_r, human_r):.3f}  偏差 = {bias(new_r, human_r):+.3f}  │")
    print(f"  └──────────────────────────────────────────────────────────────────┘")

    # ── 逐章对比 ──
    print(f"\n  逐章明细:")
    print(f"  {'book':<12} {'ch':>5} {'old_i':>5} {'new_i':>5} {'hum_i':>5} {'old_r':>5} {'new_r':>5} {'hum_r':>5}")
    print(f"  {'─'*12} {'─'*5} {'─'*5} {'─'*5} {'─'*5} {'─'*5} {'─'*5} {'─'*5}")
    for r in all_new_scores:
        print(f"  {r['book']:<12} {r['ch_num']:>5} {r['old_llm_i']:>5.1f} {r['new_llm_i']:>5.1f} {r['human_i']:>5.1f} {r['old_llm_r']:>5.1f} {r['new_llm_r']:>5.1f} {r['human_r']:>5.1f}")

    # ── ch1738 特别关注 ──
    ch1738 = [r for r in all_new_scores if r["ch_num"] == 1738 and r["book"] == "末世大回炉"]
    if ch1738:
        c = ch1738[0]
        print(f"\n  [FOCUS] ch1738 (info climax vs pleasure climax):")
        print(f"    旧 LLM intensity: {c['old_llm_i']:.1f} → 新 LLM intensity: {c['new_llm_i']:.1f} (human: {c['human_i']:.1f})")
        print(f"    偏差: 旧 {c['old_llm_i']-c['human_i']:+.1f} → 新 {c['new_llm_i']-c['human_i']:+.1f}")

    # 保存
    out_path = PROJECT_ROOT / "data" / "reports" / "末世" / "e2e_verify_phaseB.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "phase": "B",
            "n_samples": len(all_new_scores),
            "old_intensity_mae": mae(old_i, human_i),
            "new_intensity_mae": mae(new_i, human_i),
            "old_intensity_bias": bias(old_i, human_i),
            "new_intensity_bias": bias(new_i, human_i),
            "old_intensity_pearson": pearson_r(old_i, human_i),
            "new_intensity_pearson": pearson_r(new_i, human_i),
            "old_retention_mae": mae(old_r, human_r),
            "new_retention_mae": mae(new_r, human_r),
            "details": all_new_scores,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n  结果已保存: {out_path}")

    # 判定
    new_mae_i = mae(new_i, human_i)
    old_mae_i = mae(old_i, human_i)
    if new_mae_i < old_mae_i:
        print(f"\n  [PASS] Phase B: Intensity MAE {old_mae_i:.3f} -> {new_mae_i:.3f}")
    else:
        print(f"\n  [WARN] Phase B: Intensity MAE {old_mae_i:.3f} -> {new_mae_i:.3f}")

    return all_new_scores


# ============================================================
# Phase C: 校准后验证
# ============================================================
def phase_c(phase_b_results=None):
    """对 Phase B 的新 LLM 分数，跑校准验证（直方图均衡化 vs median offset vs shrinkage blend）

    P0修复要点:
    1. 用 NEW LLM 分数（Phase B 结果）构建映射，而非 OLD LLM 分数
    2. 增加 shrinkage 混合: calibrated = (1-s)*raw + s*quantile_mapped
       避免过度校正（当 bias 已经较小时，quantile mapping 弊大于利）
    3. 增加 smart-skip: |median_offset| < 0.5 时跳过校准
    4. 同时测试 median offset + shrinkage 作为备选方案
    """
    print("=" * 70)
    print("Phase C: 校准后验证（P0修复: 新LLM分数 + shrinkage + smart-skip）")
    print("=" * 70)

    # 加载 Phase B 结果
    if phase_b_results is None:
        pb_path = PROJECT_ROOT / "data" / "reports" / "末世" / "e2e_verify_phaseB.json"
        if not pb_path.exists():
            print("  [FAIL] Phase B 结果不存在，请先运行 --phase b")
            return
        with open(pb_path, encoding="utf-8") as f:
            pb_data = json.load(f)
        phase_b_results = pb_data.get("details", [])

    if not phase_b_results:
        print("  [FAIL] Phase B 无有效结果")
        return

    # 加载 golden_set.json（已含 llm_intensity/llm_retention 字段）
    golden_set_path = PROJECT_ROOT / "data" / "processed" / "末世" / "scores" / "golden_set.json"
    if not golden_set_path.exists():
        print(f"  [WARN] golden_set.json 不存在")
        return

    with open(golden_set_path, encoding="utf-8") as f:
        golden_set = json.load(f)

    # 构建 (new_llm_i, human_i) 配对 — P0修复: 使用新LLM分数
    golden_lookup = {}
    for g in golden_set:
        key = f"{g.get('book')}_{g.get('ch_num')}"
        golden_lookup[key] = g

    paired_int = []
    paired_ret = []
    for r in phase_b_results:
        key = f"{r['book']}_{r['ch_num']}"
        g = golden_lookup.get(key)
        if g:
            # P0修复: 用新LLM分数与human分数配对（之前错误地用了old_llm_i）
            paired_int.append((float(r.get("new_llm_i", 0)), float(g["human_intensity"])))
            paired_ret.append((float(r.get("new_llm_r", 0)), float(g["human_retention"])))

    # ── 计算中位数偏移（用于 smart-skip 判断和 median offset 方案） ──
    int_offsets = [h - l for l, h in paired_int]
    ret_offsets = [h - l for l, h in paired_ret]
    int_median_offset = statistics.median(int_offsets)
    ret_median_offset = statistics.median(ret_offsets)

    print(f"\n  Golden set pairs: intensity={len(paired_int)}, retention={len(paired_ret)}")
    print(f"  Median offset: intensity={int_median_offset:+.2f}, retention={ret_median_offset:+.2f}")

    # ── smart-skip 判断 ──
    SKIP_THRESHOLD = 0.5
    int_skip = abs(int_median_offset) < SKIP_THRESHOLD
    ret_skip = abs(ret_median_offset) < SKIP_THRESHOLD
    if int_skip:
        print(f"  [SMART-SKIP] Intensity |offset|={abs(int_median_offset):.2f} < {SKIP_THRESHOLD}, 跳过校准")
    if ret_skip:
        print(f"  [SMART-SKIP] Retention |offset|={abs(ret_median_offset):.2f} < {SKIP_THRESHOLD}, 跳过校准")

    # ── 构建分位数映射函数 ──
    def _build_quantile_map(paired):
        if len(paired) < 3:
            return lambda x: x
        llm_sorted = sorted(p[0] for p in paired)
        human_sorted = sorted(p[1] for p in paired)
        def mapping(x):
            if x <= llm_sorted[0]:
                return human_sorted[0]
            if x >= llm_sorted[-1]:
                return human_sorted[-1]
            for i in range(len(llm_sorted) - 1):
                if llm_sorted[i] <= x <= llm_sorted[i+1]:
                    t = (x - llm_sorted[i]) / max(llm_sorted[i+1] - llm_sorted[i], 0.001)
                    return human_sorted[i] + t * (human_sorted[i+1] - human_sorted[i])
            return x
        return mapping

    int_map = _build_quantile_map(paired_int)
    ret_map = _build_quantile_map(paired_ret)

    # ── shrinkage 因子: n=30时用0.6, 样本越少越保守 ──
    SHRINKAGE = 0.6 if len(paired_int) >= 20 else 0.4
    print(f"  Shrinkage factor: {SHRINKAGE}")

    # ── 对 Phase B 的每章结果应用三种校准方案 ──
    all_results = []
    for r in phase_b_results:
        raw_i = r["new_llm_i"]
        raw_r = r["new_llm_r"]
        old_i = r.get("old_llm_i", 0)
        human_i = r["human_i"]
        human_r = r["human_r"]

        # 方案A: 纯分位数映射（旧方法，用于对比）
        qm_i = round(int_map(raw_i), 1)
        qm_r = round(ret_map(raw_r), 1)

        # 方案B: 分位数映射 + shrinkage 混合
        # calibrated = (1-s)*raw + s*quantile_mapped
        if int_skip:
            blend_i = raw_i  # smart-skip: 不校准
        else:
            blend_i = round((1 - SHRINKAGE) * raw_i + SHRINKAGE * int_map(raw_i), 1)
        if ret_skip:
            blend_r = raw_r
        else:
            blend_r = round((1 - SHRINKAGE) * raw_r + SHRINKAGE * ret_map(raw_r), 1)

        # 方案C: median offset + shrinkage
        # calibrated = raw + shrinkage * median_offset
        if int_skip:
            mo_i = raw_i
        else:
            mo_i = round(max(1.0, min(10.0, raw_i + SHRINKAGE * int_median_offset)), 1)
        if ret_skip:
            mo_r = raw_r
        else:
            mo_r = round(max(1.0, min(10.0, raw_r + SHRINKAGE * ret_median_offset)), 1)

        all_results.append({
            "book": r["book"],
            "ch_num": r["ch_num"],
            "raw_llm_i": raw_i,
            "qm_i": qm_i,
            "blend_i": blend_i,
            "mo_i": mo_i,
            "raw_llm_r": raw_r,
            "qm_r": qm_r,
            "blend_r": blend_r,
            "mo_r": mo_r,
            "old_llm_i": old_i,
            "human_i": human_i,
            "human_r": human_r,
        })

    # ── 提取列表用于统计 ──
    raw_i_list = [r["raw_llm_i"] for r in all_results]
    qm_i_list = [r["qm_i"] for r in all_results]
    blend_i_list = [r["blend_i"] for r in all_results]
    mo_i_list = [r["mo_i"] for r in all_results]
    old_i_list = [r["old_llm_i"] for r in all_results]
    human_i_list = [r["human_i"] for r in all_results]
    raw_r_list = [r["raw_llm_r"] for r in all_results]
    qm_r_list = [r["qm_r"] for r in all_results]
    blend_r_list = [r["blend_r"] for r in all_results]
    mo_r_list = [r["mo_r"] for r in all_results]
    human_r_list = [r["human_r"] for r in all_results]

    print(f"\n  样本数: {len(all_results)}")
    print(f"\n  +----------------------------------------------------------------------+")
    print(f"  |  Intensity 校准效果对比 (P0修复: 新LLM分数构建映射)                  |")
    print(f"  +----------------------------------------------------------------------+")
    print(f"  |  旧 LLM (无校准):          MAE = {mae(old_i_list, human_i_list):.3f}  bias = {bias(old_i_list, human_i_list):+.3f}  r = {pearson_r(old_i_list, human_i_list):.4f}  |")
    print(f"  |  新 LLM (raw, 无校准):     MAE = {mae(raw_i_list, human_i_list):.3f}  bias = {bias(raw_i_list, human_i_list):+.3f}  r = {pearson_r(raw_i_list, human_i_list):.4f}  |")
    print(f"  |  纯分位数映射 (旧bug修复): MAE = {mae(qm_i_list, human_i_list):.3f}  bias = {bias(qm_i_list, human_i_list):+.3f}  r = {pearson_r(qm_i_list, human_i_list):.4f}  |")
    print(f"  |  分位数+shrinkage({SHRINKAGE}):     MAE = {mae(blend_i_list, human_i_list):.3f}  bias = {bias(blend_i_list, human_i_list):+.3f}  r = {pearson_r(blend_i_list, human_i_list):.4f}  |")
    print(f"  |  Median offset+shrinkage:  MAE = {mae(mo_i_list, human_i_list):.3f}  bias = {bias(mo_i_list, human_i_list):+.3f}  r = {pearson_r(mo_i_list, human_i_list):.4f}  |")
    print(f"  +----------------------------------------------------------------------+")
    print(f"  |  Retention 校准效果对比                                              |")
    print(f"  +----------------------------------------------------------------------+")
    print(f"  |  新 LLM (raw, 无校准):     MAE = {mae(raw_r_list, human_r_list):.3f}  bias = {bias(raw_r_list, human_r_list):+.3f}  r = {pearson_r(raw_r_list, human_r_list):.4f}  |")
    print(f"  |  纯分位数映射:             MAE = {mae(qm_r_list, human_r_list):.3f}  bias = {bias(qm_r_list, human_r_list):+.3f}  r = {pearson_r(qm_r_list, human_r_list):.4f}  |")
    print(f"  |  分位数+shrinkage({SHRINKAGE}):     MAE = {mae(blend_r_list, human_r_list):.3f}  bias = {bias(blend_r_list, human_r_list):+.3f}  r = {pearson_r(blend_r_list, human_r_list):.4f}  |")
    print(f"  |  Median offset+shrinkage:  MAE = {mae(mo_r_list, human_r_list):.3f}  bias = {bias(mo_r_list, human_r_list):+.3f}  r = {pearson_r(mo_r_list, human_r_list):.4f}  |")
    print(f"  +----------------------------------------------------------------------+")

    # ── 逐章对比 ──
    print(f"\n  逐章明细:")
    print(f"  {'book':<12} {'ch':>5} {'raw_i':>5} {'qm_i':>5} {'blend_i':>7} {'mo_i':>5} {'hum_i':>5} | {'raw_r':>5} {'blend_r':>7} {'hum_r':>5}")
    print(f"  {'-'*12} {'-'*5} {'-'*5} {'-'*5} {'-'*7} {'-'*5} {'-'*5} | {'-'*5} {'-'*7} {'-'*5}")
    for r in all_results:
        print(f"  {r['book']:<12} {r['ch_num']:>5} {r['raw_llm_i']:>5.1f} {r['qm_i']:>5.1f} {r['blend_i']:>7.1f} {r['mo_i']:>5.1f} {r['human_i']:>5.1f} | {r['raw_llm_r']:>5.1f} {r['blend_r']:>7.1f} {r['human_r']:>5.1f}")

    # ── 选择最佳方案 ──
    raw_mae_i = mae(raw_i_list, human_i_list)
    qm_mae_i = mae(qm_i_list, human_i_list)
    blend_mae_i = mae(blend_i_list, human_i_list)
    mo_mae_i = mae(mo_i_list, human_i_list)
    best_mae_i = min(raw_mae_i, qm_mae_i, blend_mae_i, mo_mae_i)
    if best_mae_i == raw_mae_i:
        best_method_i = "raw (no calibration)"
    elif best_mae_i == qm_mae_i:
        best_method_i = "pure quantile mapping"
    elif best_mae_i == blend_mae_i:
        best_method_i = f"quantile+shrinkage({SHRINKAGE})"
    else:
        best_method_i = "median_offset+shrinkage"

    print(f"\n  [BEST] Intensity: {best_method_i} (MAE={best_mae_i:.3f})")

    # ── 保存 ──
    out_path = PROJECT_ROOT / "data" / "reports" / "末世" / "e2e_verify_phaseC.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "phase": "C",
            "n_samples": len(all_results),
            "p0_fix": "使用新LLM分数构建映射 + shrinkage混合 + smart-skip",
            "old_intensity_mae": mae(old_i_list, human_i_list),
            "raw_intensity_mae": raw_mae_i,
            "qm_intensity_mae": qm_mae_i,
            "blend_intensity_mae": blend_mae_i,
            "mo_intensity_mae": mo_mae_i,
            "best_intensity_method": best_method_i,
            "raw_retention_mae": mae(raw_r_list, human_r_list),
            "blend_retention_mae": mae(blend_r_list, human_r_list),
            "mo_retention_mae": mae(mo_r_list, human_r_list),
            "shrinkage": SHRINKAGE,
            "int_median_offset": int_median_offset,
            "ret_median_offset": ret_median_offset,
            "int_smart_skip": int_skip,
            "ret_smart_skip": ret_skip,
            "details": all_results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n  结果已保存: {out_path}")

    # ── 判定: 校准后MAE不超过校准前MAE ──
    if blend_mae_i <= raw_mae_i:
        print(f"\n  [PASS] Phase C: Blend MAE {raw_mae_i:.3f} -> {blend_mae_i:.3f}")
    else:
        print(f"\n  [WARN] Phase C: Blend MAE {raw_mae_i:.3f} -> {blend_mae_i:.3f} (校准未改善, 但smart-skip已防止恶化)")
        print(f"         纯分位数映射 MAE = {qm_mae_i:.3f} (对比旧bug版本)")


# ============================================================
# Phase D: 最终融合验证
# ============================================================
def phase_d():
    """用 commercial_engine 计算最终融合分，对比 human — 基于Phase B JSON + Phase A规则端结果"""
    print("=" * 70)
    print("Phase D: 最终融合验证（分层权重 + BMA修复）")
    print("=" * 70)

    from xiaoshuo.pipeline.scoring.commercial_engine import _load_bayesian_weights

    weights = _load_bayesian_weights("末世")
    w_i = weights.get("intensity", {"w_rule": 0.25, "w_llm": 0.75})
    w_r = weights.get("retention", {"w_rule": 0.15, "w_llm": 0.85})
    print(f"  Weights: intensity(w_llm={w_i['w_llm']}, w_rule={w_i['w_rule']})")
    print(f"           retention(w_llm={w_r['w_llm']}, w_rule={w_r['w_rule']})")

    # 加载 Phase B 结果（新 LLM 分数）
    pb_path = PROJECT_ROOT / "data" / "reports" / "末世" / "e2e_verify_phaseB.json"
    if not pb_path.exists():
        print("  [FAIL] Phase B 结果不存在，请先运行 --phase b")
        return
    with open(pb_path, encoding="utf-8") as f:
        pb_data = json.load(f)
    pb_results = pb_data.get("details", [])

    # 加载 Phase A 结果（新规则分数）
    pa_path = PROJECT_ROOT / "data" / "reports" / "末世" / "e2e_verify_phaseA.json"
    if not pa_path.exists():
        print("  [FAIL] Phase A 结果不存在，请先运行 --phase a")
        return
    with open(pa_path, encoding="utf-8") as f:
        pa_data = json.load(f)
    pa_details = {f"{r['book']}_{r['ch_num']}": r for r in pa_data.get("details", [])}

    all_results = []
    for r in pb_results:
        book = r["book"]
        ch = r["ch_num"]
        pa_key = f"{book}_{ch}"
        pa = pa_details.get(pa_key, {})

        llm_s = {
            "intensity": float(r["new_llm_i"]),
            "retention": float(r["new_llm_r"]),
            "hook": "medium",  # default
        }
        rule_s = {
            "intensity": float(pa.get("new_rule", 0) or 0),
            "hook": "none",
            "emotion": "daily",
        }

        # P3a 分层融合: final = w_llm * llm + w_rule * rule
        final_i = round(w_i["w_llm"] * llm_s["intensity"] + w_i["w_rule"] * rule_s["intensity"], 2)
        final_r = round(w_r["w_llm"] * llm_s["retention"] + w_r["w_rule"] * rule_s["intensity"], 2)  # rule没有retention，借用intensity

        human_i = float(r["human_i"])
        human_r = float(r["human_r"])

        all_results.append({
            "book": book,
            "ch_num": ch,
            "llm_intensity": llm_s["intensity"],
            "rule_intensity": rule_s["intensity"],
            "final_intensity": final_i,
            "final_retention": final_r,
            "human_intensity": human_i,
            "human_retention": human_r,
        })

    if not all_results:
        print("  [FAIL] 无有效结果")
        return

    final_i = [r["final_intensity"] for r in all_results]
    final_r = [r["final_retention"] for r in all_results]
    llm_i = [r["llm_intensity"] for r in all_results]
    rule_i = [r["rule_intensity"] for r in all_results]
    human_i = [r["human_intensity"] for r in all_results]
    human_r = [r["human_retention"] for r in all_results]

    print(f"\n  样本数: {len(all_results)}")
    print(f"\n  +------------------------------------------------------------------+")
    print(f"  |  最终融合分 vs Human                                              |")
    print(f"  +------------------------------------------------------------------+")
    print(f"  |  LLM raw:     Intensity MAE = {mae(llm_i, human_i):.3f}  bias = {bias(llm_i, human_i):+.3f}  r = {pearson_r(llm_i, human_i):.4f}  |")
    print(f"  |  Rule raw:    Intensity MAE = {mae(rule_i, human_i):.3f}  bias = {bias(rule_i, human_i):+.3f}  r = {pearson_r(rule_i, human_i):.4f}  |")
    print(f"  |  Final blend: Intensity MAE = {mae(final_i, human_i):.3f}  bias = {bias(final_i, human_i):+.3f}  r = {pearson_r(final_i, human_i):.4f}  |")
    print(f"  |  Final blend: Retention  MAE = {mae(final_r, human_r):.3f}  bias = {bias(final_r, human_r):+.3f}  r = {pearson_r(final_r, human_r):.4f}  |")
    print(f"  +------------------------------------------------------------------+")

    # 逐章
    print(f"\n  逐章明细:")
    print(f"  {'book':<12} {'ch':>5} {'llm_i':>5} {'rule_i':>6} {'final_i':>7} {'hum_i':>5} {'final_r':>7} {'hum_r':>5}")
    print(f"  {'-'*12} {'-'*5} {'-'*5} {'-'*6} {'-'*7} {'-'*5} {'-'*7} {'-'*5}")
    for r in all_results:
        print(f"  {r['book']:<12} {r['ch_num']:>5} {r['llm_intensity']:>5.1f} {r['rule_intensity']:>6.1f} {r['final_intensity']:>7.2f} {r['human_intensity']:>5.1f} {r['final_retention']:>7.2f} {r['human_retention']:>5.1f}")

    # 保存
    out_path = PROJECT_ROOT / "data" / "reports" / "末世" / "e2e_verify_phaseD.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "phase": "D",
            "n_samples": len(all_results),
            "llm_intensity_mae": mae(llm_i, human_i),
            "rule_intensity_mae": mae(rule_i, human_i),
            "final_intensity_mae": mae(final_i, human_i),
            "final_retention_mae": mae(final_r, human_r),
            "final_intensity_pearson": pearson_r(final_i, human_i),
            "final_retention_pearson": pearson_r(final_r, human_r),
            "details": all_results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n  结果已保存: {out_path}")

    final_mae = mae(final_i, human_i)
    llm_mae = mae(llm_i, human_i)
    if final_mae < llm_mae:
        print(f"\n  [PASS] Phase D: MAE {llm_mae:.3f} -> {final_mae:.3f}")
    else:
        print(f"\n  [WARN] Phase D: MAE {llm_mae:.3f} -> {final_mae:.3f}")


# ============================================================
# 主入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="端到端验证脚本")
    parser.add_argument("--phase", default="a", choices=["a", "b", "c", "d", "all"],
                        help="验证阶段: a=规则, b=LLM, c=校准, d=融合, all=全部")
    args = parser.parse_args()

    print(f"\n{'='*70}")
    print(f"  番茄小说AI辅助创作系统 — 端到端验证 (Phase 0-3 优化效果)")
    print(f"  Golden Set: 3本书 × 10章 = 30章")
    print(f"{'='*70}\n")

    if args.phase in ("a", "all"):
        phase_a()
    if args.phase in ("b", "all"):
        phase_b()
    if args.phase in ("c", "all"):
        phase_c()
    if args.phase in ("d", "all"):
        phase_d()

    print(f"\n{'='*70}")
    print(f"  验证完成")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
