#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
calibrate_v2.py — 100-chapter full calibration: per-feature Pearson r + bias curve + Platt mapping
Run after: scripts\\start_model.bat
Usage: python scripts\\calibrate_v2.py
Output: data/calibration/feature_importance.csv + calibration_curve.json
"""
import csv, json, re, sys, statistics, urllib.request, time, yaml
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# RHYTHM_DIR deprecated: actual rhythm CSVs at data/processed/rhythm/
NOVELS_DIR = PROJECT_ROOT / "data" / "raw" / "novels"
INDEX_PATH = PROJECT_ROOT / "data" / "raw" / "novel_index.json"
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def _load_llama_base():
    """Read LLM server base URL from config.yaml, fallback to default."""
    try:
        import yaml
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f)
        port = cfg.get("model_orchestration", {}).get("models", {}).get("main_model", {}).get("port", 8000)
        return f"http://127.0.0.1:{port}"
    except Exception:
        return "http://127.0.0.1:8000"


LLAMA_BASE = _load_llama_base()

from xiaoshuo.pipeline.rhythm_analyzer import extract_chapters, rule_analyze


def check_server():
    try:
        urllib.request.urlopen(f"{LLAMA_BASE}/health", timeout=3)
        return True
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return False


def llm_score_independent(chapter_text, ch_num):
    """Improved prompt: rubric-based scoring with explicit anchors."""
    prompt = (
        "你是专业网文编辑。对以下章节的阅读体验独立评分（不受任何系统影响）。\n\n"
        f"第{ch_num}章:\n{chapter_text[:1500]}\n\n"
        "评分标准:\n"
        "- 爽点强度(0-10): 0=催眠平淡, 2=微提神, 5=明显爽感, 8=拍案叫好, 10=肾上腺素飙升\n"
        "- 冲突等级: none(无) low(轻微) medium(明显) high(剧烈)\n"
        "- 情绪氛围: 爽快/紧张/悲壮/悬疑/日常/温情/压抑\n"
        "- 节奏: fast(快) medium(中) slow(慢)\n"
        "- 钩子质量: none(无悬念) weak(微悬念) strong(强悬念)\n"
        "- 羁绊深度(0-5): 0=无人物关系张力, 5=极强羁绊共鸣\n\n"
        "输出纯JSON(只输出JSON):\n"
        '{"pleasure_intensity":0,"conflict_level":"none","emotion":"日常","pace":"medium","hook_quality":"none","bond_depth":0}'
    )
    data = json.dumps({
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 200, "temperature": 0.1,
    }).encode("utf-8")
    try:
        req = urllib.request.Request(
            f"{LLAMA_BASE}/v1/chat/completions",
            data, {"Content-Type": "application/json"}
        )
        resp = json.loads(urllib.request.urlopen(req, timeout=120).read())
        raw = resp["choices"][0]["message"].get("content", "")
        for pat in [
            r'\{[^{}]*?"pleasure_intensity"[^{}]*?\}',
            r'\{[^{]*"pleasure_intensity"[^}]*\}',
        ]:
            m = re.search(pat, raw)
            if m:
                try:
                    res = json.loads(m.group())
                    if "pleasure_intensity" in res:
                        return res
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
        # Fallback: extract fields individually
        pi = re.search(r'"pleasure_intensity"\s*:\s*(\d+(?:\.\d+)?)', raw)
        cl = re.search(r'"conflict_level"\s*:\s*"([^"]+)"', raw)
        em = re.search(r'"emotion"\s*:\s*"([^"]+)"', raw)
        pa = re.search(r'"pace"\s*:\s*"([^"]+)"', raw)
        hq = re.search(r'"hook_quality"\s*:\s*"([^"]+)"', raw)
        bd = re.search(r'"bond_depth"\s*:\s*(\d+(?:\.\d+)?)', raw)
        if pi:
            return {
                "pleasure_intensity": float(pi.group(1)),
                "conflict_level": cl.group(1) if cl else "none",
                "emotion": em.group(1) if em else "日常",
                "pace": pa.group(1) if pa else "medium",
                "hook_quality": hq.group(1) if hq else "none",
                "bond_depth": float(bd.group(1)) if bd else 0,
            }
        return None
    except (json.JSONDecodeError, KeyError, ValueError, urllib.error.URLError, TimeoutError,
            ConnectionError) as e:
        print(f"  [WARN] LLM评分解析失败: {e}")
        return None


def load_novels(genre="末世"):
    with open(INDEX_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)["genres"].get(genre, {}).get("novels", [])


def pearson_r(xs, ys):
    n = len(xs)
    if n < 3: return 0
    mx, my = statistics.mean(xs), statistics.mean(ys)
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    sx = (sum((x - mx) ** 2 for x in xs) / n) ** 0.5
    sy = (sum((y - my) ** 2 for y in ys) / n) ** 0.5
    if sx == 0 or sy == 0: return 0
    return round(cov / (sx * sy * n), 3)


def main():
    if not check_server():
        print(f"[FAIL] LLM server not running at {LLAMA_BASE}")
        print("  Start with: scripts\\start_model.bat")
        return

    novels = load_novels()
    conflict_map = {"none": 0, "low": 1, "medium": 2, "high": 3}

    # Collect all feature vectors + LLM scores
    all_data = []
    samples_per_book = 10
    print(f"[CALIBRATE v2] Sampling {samples_per_book} chapters from {len(novels)} books...")

    for novel in novels:
        txt_file = novel.get("file")
        if not txt_file: continue

        txt_path = None
        for fp in NOVELS_DIR.glob("**/*.txt"):
            if fp.name == txt_file:
                txt_path = fp; break
        if not txt_path: continue

        try:
            chapters = extract_chapters(txt_path)
        except Exception as e:
            print(f"  [SKIP] Failed to extract chapters from {txt_file}: {e}")
            continue
        if len(chapters) < 10: continue

        # Evenly spaced sampling
        step = max(1, len(chapters) // samples_per_book)
        sampled = [chapters[i] for i in range(0, len(chapters), step)][:samples_per_book]
        name = txt_file[:20]

        for ch in sampled:
            rule = rule_analyze(ch)
            ch_num = ch["num"]
            print(f"  [{name}] Ch{ch_num} ", end="", flush=True)
            llm = llm_score_independent(ch["raw_body"], ch_num)

            if llm is None:
                print("[FAIL] LLM parse error or timeout")
                continue

            # Feature vector: all rule metrics + derived features
            features = {
                "pos_density":       rule["pos_density"],
                "neg_density":       rule["neg_density"],
                "conflict_density":  rule["conflict_density"],
                "hook_density":      rule["hook_density"],
                "excl_density":      rule["excl_density"],
                "dialogue_ratio":    rule["dialogue_ratio"],
                "slap_count":        rule["slap_count"],
                "bond_count":        rule.get("bond_count", 0),
                "cognitive_count":   rule.get("cognitive_count", 0),
                "sacrifice_count":   rule.get("sacrifice_count", 0),
                "physio_count":      rule.get("physio_count", 0),
                "crush_count":       rule["crush_count"],
                "comeback_count":    rule["comeback_count"],
                "level_count":       rule["level_count"],
                "rule_intensity":    rule["pleasure_intensity"],
                "rule_conflict":     rule["conflict_level"],
            }

            # LLM targets
            targets = {
                "llm_intensity":     float(llm.get("pleasure_intensity", 0)),
                "llm_conflict_num":  conflict_map.get(llm.get("conflict_level", "none"), 0),
                "llm_hook":          llm.get("hook_quality", "none"),
                "llm_bond":          float(llm.get("bond_depth", 0)),
            }

            all_data.append({"features": features, "targets": targets})
            print(f"R:{features['rule_intensity']:.1f} L:{targets['llm_intensity']:.1f}")
            time.sleep(0.8)

    if len(all_data) < 20:
        print(f"[FAIL] Only {len(all_data)} samples, need >=20")
        return

    print(f"\n[DATA] {len(all_data)} samples collected")

    # ── Per-feature Pearson r ──
    feature_names = [
        "pos_density", "neg_density", "conflict_density", "hook_density",
        "excl_density", "dialogue_ratio", "slap_count", "bond_count",
        "cognitive_count", "sacrifice_count", "physio_count",
        "crush_count", "comeback_count", "level_count", "rule_intensity",
    ]
    results_rows = []
    for fname in feature_names:
        fvals = [d["features"][fname] for d in all_data]
        lintens = [d["targets"]["llm_intensity"] for d in all_data]
        lconf = [d["targets"]["llm_conflict_num"] for d in all_data]
        lbond = [d["targets"]["llm_bond"] for d in all_data]

        r_intens = pearson_r(fvals, lintens)
        r_conflict = pearson_r(fvals, lconf)
        r_bond = pearson_r(fvals, lbond)
        results_rows.append({
            "feature": fname,
            "r_vs_llm_intensity": r_intens,
            "r_vs_llm_conflict": r_conflict,
            "r_vs_llm_bond": r_bond,
            "keep": "yes" if abs(r_intens) > 0.1 or abs(r_conflict) > 0.1 else "no",
        })

    # ── Platt calibration (simple linear scaling for intensity) ──
    rule_vals = [d["features"]["rule_intensity"] for d in all_data]
    llm_vals = [d["targets"]["llm_intensity"] for d in all_data]
    # Linear regression: llm = a * rule + b
    n = len(rule_vals)
    mx, my = statistics.mean(rule_vals), statistics.mean(llm_vals)
    cov = sum((rule_vals[i] - mx) * (llm_vals[i] - my) for i in range(n))
    var = sum((x - mx) ** 2 for x in rule_vals)
    a = round(cov / max(var, 0.001), 3)
    b = round(my - a * mx, 1)
    rule_llm_r = pearson_r(rule_vals, llm_vals)

    # ── Bias per sub-genre ──
    # Estimate from bond vs slap ratio in rules
    for d in all_data:
        f = d["features"]
        bond_slap_ratio = f["bond_count"] / max(f["slap_count"], 1)
        if bond_slap_ratio > 2.0:
            d["_sub_genre"] = "bond"
        elif f["cognitive_count"] > f["slap_count"]:
            d["_sub_genre"] = "smart"
        elif f["slap_count"] > f["bond_count"] * 2:
            d["_sub_genre"] = "slap"
        else:
            d["_sub_genre"] = "general"

    genre_bias = {}
    for g in ["slap", "smart", "bond", "general"]:
        gdata = [d for d in all_data if d["_sub_genre"] == g]
        if len(gdata) < 5: continue
        gr = [d["features"]["rule_intensity"] for d in gdata]
        gl = [d["targets"]["llm_intensity"] for d in gdata]
        bias = round(statistics.mean([gl[i] - gr[i] for i in range(len(gr))]), 2)
        genre_bias[g] = {"bias": bias, "n": len(gdata)}

    # ── Save outputs ──
    genre = "末世"  # default, matches load_novels
    out_dir = PROJECT_ROOT / "data" / "reports" / genre / "calibration"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Feature importance CSV
    csv_path = out_dir / "feature_importance.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["feature", "r_vs_llm_intensity", "r_vs_llm_conflict", "r_vs_llm_bond", "keep"])
        w.writeheader()
        w.writerows(results_rows)

    # Calibration curve JSON
    curve_path = out_dir / "calibration_curve.json"
    json.dump({
        "n_samples": len(all_data),
        "rule_llm_r": rule_llm_r,
        "linear_model": {"a": a, "b": b, "formula": f"llm = {a}*rule + {b}"},
        "per_subgenre_bias": genre_bias,
        "feature_importance_file": str(csv_path),
    }, open(curve_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # Report
    report = [
        "# 规则校准报告 v2 (100章全特征)",
        f"> 样本: {len(all_data)} chapters | r(rule vs LLM) = {rule_llm_r}",
        f"> 校准公式: LLM = {a} × Rule + {b}",
        "",
        "## 特征重要性 (Pearson r vs LLM 爽点强度)",
        "| 特征 | r_intensity | r_conflict | r_bond | 保留 |",
        "|------|:---:|:---:|:---:|:---:|",
    ]
    for row in sorted(results_rows, key=lambda r: -abs(r["r_vs_llm_intensity"])):
        keep = "✅" if row["keep"] == "yes" else "❌ 剔除"
        report.append(
            f"| {row['feature']} | {row['r_vs_llm_intensity']} | "
            f"{row['r_vs_llm_conflict']} | {row['r_vs_llm_bond']} | {keep} |"
        )
    report.extend([
        "",
        "## 子类型偏置",
        "| 子类型 | 偏置 | 样本数 |",
        "|------|:---:|:---:|",
    ])
    for g, info in sorted(genre_bias.items()):
        report.append(f"| {g} | {info['bias']} | {info['n']} |")
    report.append(f"\n---\n*calibrate_v2.py · Platt Scaling + per-feature r*")

    report_path = out_dir / "calibration_report_v2.md"
    report_path.write_text("\n".join(report), encoding="utf-8")
    print(f"\n[OK] Feature importance: {csv_path}")
    print(f"[OK] Calibration curve: {curve_path}")
    print(f"[OK] Report: {report_path}")


if __name__ == "__main__":
    main()
