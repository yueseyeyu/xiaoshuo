#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
分析DeepSeek V4 Pro交叉验证结果
================================
对比 DeepSeek vs GLM vs T1 vs Human 四方评分一致性。
"""
import csv
import json
import math
import os
from pathlib import Path
from collections import defaultdict

PROJECT = Path(r"d:\Code\xiaoshuo")
TIER3 = PROJECT / "data" / "golden" / "末世" / "tier3"
GLM_JSON = TIER3 / "tier3_glm_scores.json"
GOLDEN_CSV = PROJECT / "data" / "golden" / "末世" / "human_golden.csv"
DEEPSEEK_DIR = TIER3 / "deepseek_xval_prompts"
REPORT_OUT = PROJECT / "data" / "reports" / "末世" / "deepseek_xval_report.md"

def pearson_r(x, y):
    n = len(x)
    if n < 3: return None
    mx, my = sum(x) / n, sum(y) / n
    num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    dx = math.sqrt(sum((xi - mx) ** 2 for xi in x))
    dy = math.sqrt(sum((yi - my) ** 2 for yi in y))
    if dx < 1e-10 or dy < 1e-10: return None
    return num / (dx * dy)

def load_deepseek_results():
    """Load all DeepSeek result JSONs."""
    results = {}
    for f in DEEPSEEK_DIR.glob("*_deepseek_result.json"):
        book_name = f.name.replace("_deepseek_result.json", "")
        try:
            with open(f, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
                results[book_name] = {ch["ch_num"]: ch for ch in data}
        except Exception as e:
            print(f"Error loading {f.name}: {e}")
    return results

def load_glm_scores():
    with open(GLM_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)
    results = {}
    for book, chapters in data.get("scores", {}).items():
        results[book] = {ch["ch_num"]: ch for ch in chapters}
    return results

def load_t1_scores():
    """Load T1 scores from tier3_plan.csv files."""
    results = {}
    for f in TIER3.glob("*_tier3_plan.csv"):
        book = f.name.replace("_tier3_plan.csv", "")
        with open(f, 'r', encoding='utf-8-sig') as fh:
            reader = csv.DictReader(fh)
            results[book] = {}
            for row in reader:
                try:
                    ch = int(row["ch_num"])
                    ai_i = row.get("ai_intensity", "")
                    ai_r = row.get("ai_retention", "")
                    results[book][ch] = {
                        "intensity": float(ai_i) if ai_i.strip() else None,
                        "retention": float(ai_r) if ai_r.strip() else None,
                    }
                except (ValueError, KeyError):
                    continue
    return results

def load_human_scores():
    """Load human golden scores (deduplicated)."""
    results = {}
    dedup = {}
    with open(GOLDEN_CSV, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            book = row["book"].strip()
            ch = int(row["ch_num"])
            dedup[(book, ch)] = {
                "intensity": float(row["human_intensity"]),
                "retention": float(row["human_retention"]),
            }
    for (book, ch), scores in dedup.items():
        if book not in results:
            results[book] = {}
        results[book][ch] = scores
    return results

def main():
    report = []
    def log(msg):
        report.append(msg)
    
    log("# DeepSeek V4 Pro 交叉验证分析报告")
    log(f"> 生成时间: 2026-07-13")
    log("")
    log("---")
    log("")
    
    deepseek = load_deepseek_results()
    glm = load_glm_scores()
    t1 = load_t1_scores()
    human = load_human_scores()
    
    log("## 一、数据概览")
    log("")
    log(f"| 评分方 | 书籍数 | 总章节数 |")
    log(f"|--------|--------|---------|")
    log(f"| DeepSeek V4 Pro | {len(deepseek)} | {sum(len(v) for v in deepseek.values())} |")
    log(f"| GLM (CatPaw) | {len(glm)} | {sum(len(v) for v in glm.values())} |")
    log(f"| T1 (AI全读) | {len(t1)} | {sum(len(v) for v in t1.values())} |")
    log(f"| Human (人工golden) | {len(human)} | {sum(len(v) for v in human.values())} |")
    log("")
    
    if not deepseek:
        log("**⚠️ 未找到DeepSeek结果文件。**")
        log("")
        log("请将DeepSeek返回的JSON保存为:")
        log("`data/golden/末世/tier3/deepseek_xval_prompts/{书名}_deepseek_result.json`")
        log("")
        log("然后重新运行此脚本。")
        with open(REPORT_OUT, 'w', encoding='utf-8') as f:
            f.write("\n".join(report))
        print("No DeepSeek results found. Report written with instructions.")
        return
    
    # ── Build comparison dataset ──
    log("## 二、四方评分对比 (Intensity)")
    log("")
    
    # Match: book + ch_num across all 4 sources
    matched = []
    for book in glm:
        for ch_num in glm[book]:
            entry = {"book": book, "ch_num": ch_num}
            glm_ch = glm[book].get(ch_num, {})
            entry["glm_i"] = float(glm_ch.get("intensity", 0)) if glm_ch else None
            entry["glm_r"] = float(glm_ch.get("retention", 0)) if glm_ch else None
            
            ds_ch = deepseek.get(book, {}).get(ch_num, {})
            entry["ds_i"] = float(ds_ch.get("intensity", 0)) if ds_ch else None
            entry["ds_r"] = float(ds_ch.get("retention", 0)) if ds_ch else None
            
            t1_ch = t1.get(book, {}).get(ch_num, {})
            entry["t1_i"] = t1_ch.get("intensity") if t1_ch else None
            entry["t1_r"] = t1_ch.get("retention") if t1_ch else None
            
            human_ch = human.get(book, {}).get(ch_num, {})
            entry["human_i"] = human_ch.get("intensity") if human_ch else None
            entry["human_r"] = human_ch.get("retention") if human_ch else None
            
            matched.append(entry)
    
    log(f"匹配章节总数: {len(matched)}")
    log("")
    
    # ── Pairwise correlations ──
    log("## 三、Pearson相关系数矩阵 (Intensity)")
    log("")
    
    pairs = {
        "DeepSeek vs GLM": ("ds_i", "glm_i"),
        "DeepSeek vs T1": ("ds_i", "t1_i"),
        "DeepSeek vs Human": ("ds_i", "human_i"),
        "GLM vs T1": ("glm_i", "t1_i"),
        "GLM vs Human": ("glm_i", "human_i"),
        "T1 vs Human": ("t1_i", "human_i"),
    }
    
    log(f"| 对比 | n | Pearson r | 评级 |")
    log(f"|------|---|-----------|------|")
    
    correlations = {}
    for name, (k1, k2) in pairs.items():
        x = [e[k1] for e in matched if e.get(k1) is not None and e.get(k2) is not None]
        y = [e[k2] for e in matched if e.get(k1) is not None and e.get(k2) is not None]
        n = len(x)
        r = pearson_r(x, y) if n >= 3 else None
        correlations[name] = r
        
        if r is None:
            log(f"| {name} | {n} | N/A | 数据不足 |")
        elif r >= 0.7:
            log(f"| {name} | {n} | **{r:.3f}** | ✅ 高一致 |")
        elif r >= 0.5:
            log(f"| {name} | {n} | **{r:.3f}** | ⚠️ 中等一致 |")
        elif r >= 0.3:
            log(f"| {name} | {n} | **{r:.3f}** | ⚠️ 弱一致 |")
        else:
            log(f"| {name} | {n} | **{r:.3f}** | ❌ 不一致 |")
    
    log("")
    
    # ── Retention correlations ──
    log("## 四、Pearson相关系数矩阵 (Retention)")
    log("")
    
    pairs_r = {
        "DeepSeek vs GLM": ("ds_r", "glm_r"),
        "DeepSeek vs T1": ("ds_r", "t1_r"),
        "DeepSeek vs Human": ("ds_r", "human_r"),
        "GLM vs T1": ("glm_r", "t1_r"),
        "GLM vs Human": ("glm_r", "human_r"),
        "T1 vs Human": ("t1_r", "human_r"),
    }
    
    log(f"| 对比 | n | Pearson r | 评级 |")
    log(f"|------|---|-----------|------|")
    
    for name, (k1, k2) in pairs_r.items():
        x = [e[k1] for e in matched if e.get(k1) is not None and e.get(k2) is not None]
        y = [e[k2] for e in matched if e.get(k1) is not None and e.get(k2) is not None]
        n = len(x)
        r = pearson_r(x, y) if n >= 3 else None
        
        if r is None:
            log(f"| {name} | {n} | N/A | 数据不足 |")
        elif r >= 0.7:
            log(f"| {name} | {n} | **{r:.3f}** | ✅ 高一致 |")
        elif r >= 0.5:
            log(f"| {name} | {n} | **{r:.3f}** | ⚠️ 中等一致 |")
        elif r >= 0.3:
            log(f"| {name} | {n} | **{r:.3f}** | ⚠️ 弱一致 |")
        else:
            log(f"| {name} | {n} | **{r:.3f}** | ❌ 不一致 |")
    
    log("")
    
    # ── Bias analysis ──
    log("## 五、偏差分析 (Bias vs Human)")
    log("")
    
    for name, (k1, k2) in [("DeepSeek", ("ds_i", "human_i")), ("GLM", ("glm_i", "human_i")), ("T1", ("t1_i", "human_i"))]:
        diffs = [e[k1] - e[k2] for e in matched if e.get(k1) is not None and e.get(k2) is not None]
        if diffs:
            bias = sum(diffs) / len(diffs)
            mae = sum(abs(d) for d in diffs) / len(diffs)
            log(f"| {name} | n={len(diffs)} | Bias={bias:+.2f} | MAE={mae:.2f} |")
    
    log("")
    
    # ── Key analysis ──
    log("## 六、关键分析")
    log("")
    
    ds_glm_r = correlations.get("DeepSeek vs GLM")
    ds_human_r = correlations.get("DeepSeek vs Human")
    glm_human_r = correlations.get("GLM vs Human")
    
    if ds_glm_r is not None:
        log(f"### 1. AI间一致性: DeepSeek vs GLM r={ds_glm_r:.3f}")
        log("")
        if ds_glm_r >= 0.7:
            log("✅ **AI评分有较强客观性** — 两个独立AI对相同章节的评分高度一致，说明AI评分并非纯粹主观。")
            log("   这支持将GLM评分作为校准锚点的做法。")
        elif ds_glm_r >= 0.5:
            log("⚠️ **AI评分有中等一致性** — 两个AI有一定共识但分歧不小。")
            log("   GLM评分作为校准锚点有一定合理性，但不应完全依赖。")
        else:
            log("❌ **AI评分一致性低** — 两个AI对相同章节的评分差异大。")
            log("   这意味着AI评分高度主观，GLM评分不应作为校准锚点。")
        log("")
    
    if ds_human_r is not None and glm_human_r is not None:
        log(f"### 2. AI vs 人工一致性")
        log("")
        log(f"- DeepSeek vs Human: r={ds_human_r:.3f}")
        log(f"- GLM vs Human: r={glm_human_r:.3f}")
        log("")
        if ds_human_r > glm_human_r:
            log("✅ DeepSeek比GLM更接近人工评分 — DeepSeek评分质量更高，可考虑替换GLM作为校准锚点。")
        elif ds_human_r < glm_human_r:
            log("GLM比DeepSeek更接近人工评分 — GLM评分质量更高，维持现有校准。")
        else:
            log("两个AI与人工评分的一致性相当。")
        log("")
    
    if ds_glm_r is not None and ds_glm_r >= 0.7:
        log("### 3. 对v8.11校准的影响")
        log("")
        log("DeepSeek-GLM高一致性的情况下:")
        log("- GLM评分作为校准锚点的合理性得到独立验证")
        log("- 但高一致性也意味着两个AI可能共享相同的偏差模式(同源LLM偏见)")
        log("- 仍需扩大人工标注至60章来解决根本问题")
        log("")
    elif ds_glm_r is not None and ds_glm_r < 0.5:
        log("### 3. 对v8.11校准的影响")
        log("")
        log("DeepSeek-GLM低一致性的情况下:")
        log("- GLM评分作为校准锚点的可靠性受到质疑")
        log("- 建议用DeepSeek替换GLM或采用三方平均(GLM+DeepSeek+Human)")
        log("- 迫切需要扩大人工标注")
        log("")
    
    # ── Per-book analysis ──
    log("## 七、逐书分析")
    log("")
    log("| 书名 | DS-GLM r | DS-T1 r | DS均值 | GLM均值 | T1均值 |")
    log("|------|----------|---------|--------|---------|--------|")
    
    for book in sorted(glm.keys()):
        book_data = [e for e in matched if e["book"] == book]
        ds_vals = [e["ds_i"] for e in book_data if e.get("ds_i") is not None]
        glm_vals = [e["glm_i"] for e in book_data if e.get("glm_i") is not None]
        t1_vals = [e["t1_i"] for e in book_data if e.get("t1_i") is not None]
        
        ds_glm = pearson_r(
            [e["ds_i"] for e in book_data if e.get("ds_i") is not None and e.get("glm_i") is not None],
            [e["glm_i"] for e in book_data if e.get("ds_i") is not None and e.get("glm_i") is not None]
        ) if len(book_data) >= 3 else None
        
        ds_t1 = pearson_r(
            [e["ds_i"] for e in book_data if e.get("ds_i") is not None and e.get("t1_i") is not None],
            [e["t1_i"] for e in book_data if e.get("ds_i") is not None and e.get("t1_i") is not None]
        ) if len(book_data) >= 3 else None
        
        ds_mean = sum(ds_vals) / len(ds_vals) if ds_vals else 0
        glm_mean = sum(glm_vals) / len(glm_vals) if glm_vals else 0
        t1_mean = sum(t1_vals) / len(t1_vals) if t1_vals else 0
        
        ds_glm_str = f"{ds_glm:.3f}" if ds_glm else "N/A"
        ds_t1_str = f"{ds_t1:.3f}" if ds_t1 else "N/A"
        log(f"| {book} | {ds_glm_str} | {ds_t1_str} | {ds_mean:.1f} | {glm_mean:.1f} | {t1_mean:.1f} |")
    
    log("")
    log("---")
    log("")
    log(f"*分析脚本: scripts/analyze_deepseek_xval.py*")
    
    with open(REPORT_OUT, 'w', encoding='utf-8') as f:
        f.write("\n".join(report))
    
    print(f"Report written to {REPORT_OUT}")

if __name__ == "__main__":
    main()
