#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
calibrate_rules.py — DEPRECATED (v7.3), superseded by calibrate_v2.py.
Kept for reference only. Use `python analysis/calibrate_v2.py` instead.

Method: LLM-as-Judge rule calibration: Pearson r + bias correction
"""
import csv, json, re, sys, statistics, urllib.request, time, yaml
from pathlib import Path
from collections import defaultdict, Counter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RHYTHM_DIR = PROJECT_ROOT / "data" / "rhythm"
NOVELS_DIR = PROJECT_ROOT / "data" / "raw" / "novels"
INDEX_PATH = PROJECT_ROOT / "data" / "raw" / "novel_index.json"
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def _get_llama_base():
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}
        port = cfg.get("model_orchestration", {}).get("models", {}).get("main_model", {}).get("port", 8000)
        return f"http://127.0.0.1:{port}"
    except Exception:
        return "http://127.0.0.1:8000"


LLAMA_BASE = _get_llama_base()

# Import chapter extraction from rhythm_analyzer
sys.path.insert(0, str(PROJECT_ROOT / "analysis"))
from rhythm_analyzer import extract_chapters


def check_server():
    try:
        urllib.request.urlopen(f"{LLAMA_BASE}/health", timeout=3)
        return True
    except:
        return False


def load_novels(genre="末世"):
    with open(INDEX_PATH, 'r', encoding='utf-8') as f:
        index = json.load(f)
    return index["genres"].get(genre, {}).get("novels", [])


def llm_score_chapter(chapter_text, ch_num):
    """Send chapter text to LLM for scoring. Returns dict or None."""
    prompt = (
        f"你是网文分析专家。对以下章节独立评分。\n\n"
        f"第{ch_num}章:\n{chapter_text[:1800]}\n\n"
        "输出纯JSON(只输出JSON，不要任何其他文字):\n"
        '{"pleasure_intensity":0,"conflict_level":"none","emotion":"日常","pace":"medium","hook_quality":"none"}\n'
        "pleasure_intensity: 0-10 (0=平淡,10=极爽)\n"
        "conflict_level: none/low/medium/high\n"
        "emotion: 爽快/紧张/悲壮/悬疑/日常\n"
        "pace: fast/slow/medium\n"
        "hook_quality: none/weak/strong"
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
        # Multiple JSON extraction attempts
        for pattern in [
            r'\{[^{}]*?"pleasure_intensity"[^{}]*?\}',  # simple flat JSON
            r'\{[^{]*"pleasure_intensity"[^}]*\}',       # looser
        ]:
            m = re.search(pattern, raw)
            if m:
                try:
                    result = json.loads(m.group())
                    if "pleasure_intensity" in result:
                        return result
                except:
                    continue
        # Last resort: extract fields individually
        pi = re.search(r'"pleasure_intensity"\s*:\s*(\d+(?:\.\d+)?)', raw)
        cl = re.search(r'"conflict_level"\s*:\s*"([^"]+)"', raw)
        em = re.search(r'"emotion"\s*:\s*"([^"]+)"', raw)
        pa = re.search(r'"pace"\s*:\s*"([^"]+)"', raw)
        hq = re.search(r'"hook_quality"\s*:\s*"([^"]+)"', raw)
        if pi:
            return {
                "pleasure_intensity": float(pi.group(1)),
                "conflict_level": cl.group(1) if cl else "none",
                "emotion": em.group(1) if em else "日常",
                "pace": pa.group(1) if pa else "medium",
                "hook_quality": hq.group(1) if hq else "none",
            }
        return None
    except Exception as e:
        return None


def load_csv_sampled_indices(book_csv, n=5):
    """Load N evenly-spaced chapter indices + rule results from CSV."""
    csv_path = RHYTHM_DIR / book_csv
    if not csv_path.exists():
        return []
    rows = []
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            rows.append(r)
    if len(rows) < n:
        return rows
    step = len(rows) // n
    return [rows[i] for i in range(0, len(rows), step)][:n]


def calibrate(genre="末世", samples_per_book=5):
    if not check_server():
        print("[FAIL] LLM server not running at http://127.0.0.1:8000/health")
        return None

    novels = load_novels(genre)
    if not novels:
        print(f"[FAIL] No novels for genre '{genre}'")
        return None

    pairs = {"pleasure_intensity": [], "conflict_numeric": [],
             "emotion_match": [], "pace_match": [], "hook_match": []}

    conflict_map = {"none": 0, "low": 1, "medium": 2, "high": 3}
    print(f"[CALIBRATE] Sampling {samples_per_book} chapters from {len(novels)} books...")

    for novel in novels:
        csv_name = novel.get("rhythm_csv")
        txt_file = novel.get("file")
        if not csv_name or not txt_file:
            continue

        # Find TXT file
        txt_path = None
        for fp in NOVELS_DIR.glob("**/*.txt"):
            if fp.name == txt_file:
                txt_path = fp
                break
        if not txt_path:
            print(f"  [SKIP] TXT not found: {txt_file}")
            continue

        # Extract chapters from TXT
        try:
            chapters = extract_chapters(txt_path)
        except Exception as e:
            print(f"  [SKIP] Extract failed: {txt_file} — {e}")
            continue

        # Load sampled CSV indices
        samples = load_csv_sampled_indices(csv_name, samples_per_book)
        name = novel["file"][:20]

        for i, row in enumerate(samples):
            ch_num = int(row["ch_num"]) - 1  # 0-indexed
            if ch_num < 0 or ch_num >= len(chapters):
                continue
            chapter = chapters[ch_num]
            chapter_text = chapter["raw_body"]

            rule_intensity = float(row["pleasure_intensity"])
            rule_conflict = row.get("conflict_level", "none")
            rule_emotion = row.get("emotion", "日常")
            rule_pace = row.get("pace", "medium")
            rule_hook = row.get("hook_type", "none")

            print(f"  [{name}] Ch{ch_num+1} ({i+1}/{len(samples)})", end=" ")
            llm = llm_score_chapter(chapter_text, ch_num + 1)

            if llm is None:
                print("[FAIL]")
                continue

            llm_intensity = float(llm.get("pleasure_intensity", 0))
            llm_conflict = llm.get("conflict_level", "none")
            llm_emotion = llm.get("emotion", "日常")
            llm_pace = llm.get("pace", "medium")
            llm_hook = llm.get("hook_quality", "none")

            pairs["pleasure_intensity"].append((rule_intensity, llm_intensity))
            pairs["conflict_numeric"].append(
                (conflict_map.get(rule_conflict, 0),
                 conflict_map.get(llm_conflict, 0))
            )
            pairs["emotion_match"].append(1 if rule_emotion == llm_emotion else 0)
            pairs["pace_match"].append(1 if rule_pace == llm_pace else 0)
            pairs["hook_match"].append(1 if rule_hook != "none" and llm_hook == "strong" else 0)

            print(f"R:{rule_intensity:.1f} L:{llm_intensity:.1f}")
            time.sleep(1.0)

    if not pairs["pleasure_intensity"]:
        print("[FAIL] No valid samples collected")
        return None

    def pearson_r(xs, ys):
        n = len(xs)
        mx, my = statistics.mean(xs), statistics.mean(ys)
        cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
        sx = (sum((x - mx) ** 2 for x in xs) / n) ** 0.5
        sy = (sum((y - my) ** 2 for y in ys) / n) ** 0.5
        if sx == 0 or sy == 0:
            return 0
        return round(cov / (sx * sy * n), 3)

    def mean_bias(xs, ys):
        return round(statistics.mean([ys[i] - xs[i] for i in range(len(xs))]), 2)

    results = {}
    ri = pairs["pleasure_intensity"]
    r_vals, l_vals = [x[0] for x in ri], [x[1] for x in ri]
    results["pearson_r"] = pearson_r(r_vals, l_vals)
    results["bias_pleasure"] = mean_bias(r_vals, l_vals)
    rc = pairs["conflict_numeric"]
    results["conflict_r"] = pearson_r([x[0] for x in rc], [x[1] for x in rc])
    results["conflict_bias"] = mean_bias([x[0] for x in rc], [x[1] for x in rc])
    results["emotion_accuracy"] = round(statistics.mean(pairs["emotion_match"]) * 100)
    results["pace_accuracy"] = round(statistics.mean(pairs["pace_match"]) * 100)
    results["hook_accuracy"] = round(statistics.mean(pairs["hook_match"]) * 100)
    results["n_samples"] = len(ri)

    output_dir = PROJECT_ROOT / "data" / "analysis" / genre / "synthesis"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "calibration_report.md"

    rhs = results
    lines = [
        "# 规则校准报告 (LLM-as-Judge)",
        f"> 方法: AutoCalibrate inspired (LREC-COLING 2024) + Pearson r",
        f"> 样本: {rhs['n_samples']} chapters from {len(novels)} books",
        f"> 模型: Qwen3.5-9B @ {LLAMA_BASE}",
        "",
        "## 相关性 (Pearson r)",
        f"| 维度 | r | 强度 | 偏置 | 判断 |",
        f"|------|:---:|------|:---:|------|",
    ]
    for r_val, bias, name in [
        (rhs["pearson_r"], rhs["bias_pleasure"], "爽点强度"),
        (rhs["conflict_r"], rhs["conflict_bias"], "冲突等级"),
    ]:
        strength = "强" if abs(r_val) > 0.7 else ("中" if abs(r_val) > 0.4 else "弱")
        bias_str = f"+{bias:.1f}" if bias > 0 else f"{bias:.1f}"
        verdict = "✅ 可靠" if abs(r_val) > 0.7 else ("⚠️ 需校准" if abs(r_val) > 0.4 else "❌ 不可靠")
        lines.append(f"| {name} | {r_val} | {strength} | {bias_str} | {verdict} |")

    lines.extend([
        "",
        "## 分类一致率",
        f"| 维度 | 准确率 | 判断 |",
        f"|------|:---:|------|",
        f"| 情绪分类 | {rhs['emotion_accuracy']}% | {'✅' if rhs['emotion_accuracy']>=70 else '⚠️'} |",
        f"| 节奏分类 | {rhs['pace_accuracy']}% | {'✅' if rhs['pace_accuracy']>=70 else '⚠️'} |",
        f"| 钩子检测 | {rhs['hook_accuracy']}% | {'✅' if rhs['hook_accuracy']>=70 else '⚠️'} |",
        "",
        "## 校准建议",
    ])

    if abs(rhs["pearson_r"]) < 0.7:
        lines.append(f"- **爽点强度**: r={rhs['pearson_r']} < 0.7 → 建议校准。偏置={rhs['bias_pleasure']} → 规则{'高估' if rhs['bias_pleasure'] < 0 else '低估'}")
    else:
        lines.append("- 爽点强度: r >= 0.7 → 可信任")

    lines.append(f"\n---\n*calibrate_rules.py · AutoCalibrate (LREC-COLING 2024)*")
    report_path.write_text("\n".join(lines), encoding='utf-8')
    print(f"\n[OK] Calibration report: {report_path}")
    return results


if __name__ == "__main__":
    genre = "末世"
    samples = 5
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--genre" and i < len(sys.argv) - 1:
            genre = sys.argv[i + 1]
        if arg == "--samples" and i < len(sys.argv) - 1:
            samples = int(sys.argv[i + 1])
    print(f"[CALIBRATE] genre={genre} samples_per_book={samples}")
    calibrate(genre, samples)
