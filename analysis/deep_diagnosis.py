#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
deep_diagnosis.py — Two-Stage Hierarchical Deep Analysis (v7.4)
================================================================
Stage 1 (0s):   Rule-based chapter selection via adaptive_keyframe()
                → Reuses existing rhythm CSVs to locate 30 key chapters
Stage 2 (~8min): LLM rubric scoring on key chapters only (Top-3 books)
                → Bottom-3 books: rule-only (zero LLM cost)
================================================================
Theory: NexusSum ACL 2025 (coarse-to-fine) + Hybrid LLM-Rule 2024 +
        Adaptive Keyframe CVPR 2025 + Two-Stage Clinical NLP 2026
"""
import csv
import json
import statistics
import time
import urllib.request
import urllib.parse
import re
from pathlib import Path
from collections import Counter
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RHYTHM_DIR = PROJECT_ROOT / "data" / "processed" / "rhythm"
NOVELS_DIR = PROJECT_ROOT / "data" / "raw" / "novels"
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "reports"

# LLM server config
def _load_llama_base():
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f)
        port = cfg.get("model_orchestration", {}).get("models", {}).get("main_model", {}).get("port", 8000)
        return f"http://127.0.0.1:{port}"
    except Exception:
        return "http://127.0.0.1:8000"

LLAMA_BASE = _load_llama_base()
LLAMA_HOST = urllib.parse.urlparse(LLAMA_BASE).netloc


# ---- Chapter Extraction (lean, local to avoid circular imports) ----

def _extract_chapters(filepath):
    """Extract chapters from TXT. Lean copy of rhythm_analyzer.extract_chapters()."""
    text = None
    for enc in ["utf-8", "gbk", "utf-16-le", "utf-16-be"]:
        try:
            text = Path(filepath).read_text(encoding=enc)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    if text is None:
        return []

    cn_nums = r"[一二三四五六七八九十百千零\d]+"
    pattern1 = r"(第" + cn_nums + r"章\s*[^\n]*)"
    parts = re.split(pattern1, text)
    if len(parts) < 5:
        return []

    chapters = []
    for i in range(1, len(parts) - 1, 2):
        header = parts[i]
        body = parts[i + 1]
        if len(body.strip()) < 50:
            continue
        ch_num = 0
        for regex in [r"第([一二三四五六七八九十百千零\d]+)章"]:
            m = re.search(regex, header)
            if m:
                num_str = m.group(1).strip()
                try:
                    ch_num = int(num_str)
                except ValueError:
                    cn_map = dict(zip("一二三四五六七八九十百千零", [1,2,3,4,5,6,7,8,9,10,100,1000,0]))
                    v = 0
                    for c in num_str:
                        v = v * 10 + cn_map.get(c, 0) if v < 100 else v + cn_map.get(c, 0)
                    ch_num = v
                break
        wc = len(body)
        chapters.append({"num": ch_num, "wc": wc, "raw_body": body})
    return chapters


# ---- adaptive_keyframe: rule-based smart chapter selection ----
def adaptive_keyframe(rows, n_key=30):
    """Select ~30 key chapters from rhythm CSV rows.
    
    Dimensions:
    - 前3章 (黄金三章)
    - conflict_density 峰值5章
    - hook_density = 0 的前5章 (钩子断裂点)
    - hook_type 切换章 (节奏转折)
    - 每10%进度1章 (均匀覆盖)
    - 情感峰值章 (慢热高潮防遗漏, R5反模式)
    
    Returns sorted list of 0-based chapter indices.
    """
    key = set()
    total = len(rows)
    if total == 0:
        return []

    # 1. 黄金三章
    for i in range(min(3, total)):
        key.add(i)

    # 2. 冲突峰值5章
    conflict_sorted = sorted(range(total),
                             key=lambda i: float(rows[i].get("conflict_density", 0)),
                             reverse=True)
    for i in conflict_sorted[:5]:
        key.add(i)

    # 3. 钩子断裂前5章
    broken = [i for i in range(total) if float(rows[i].get("hook_density", 1)) < 0.1]
    for i in broken[:5]:
        key.add(i)

    # 4. 钩子类型切换章
    prev_type = None
    for i, r in enumerate(rows):
        ht = r.get("hook_type", "")
        if ht and ht != "none" and prev_type and ht != prev_type:
            key.add(i)
        if ht and ht != "none":
            prev_type = ht

    # 5. 每10%进度1章 (均匀覆盖)
    for pct in range(10, 100, 10):
        idx = min(total - 1, total * pct // 100)
        key.add(idx)

    # 6. 情感峰值章 (pleasure_intensity top 3, 防遗漏慢热型)
    pleasure_sorted = sorted(range(total),
                             key=lambda i: float(rows[i].get("pleasure_intensity", 0)),
                             reverse=True)
    for i in pleasure_sorted[:3]:
        key.add(i)

    # 7. 末尾章
    key.add(total - 1)

    result = sorted(key)[:n_key]
    # 8. Dedup by ch_num — overlapping selection rules may pick same chapter
    seen = set()
    deduped = []
    for i in result:
        ch = rows[i].get("ch_num", str(i))
        if ch not in seen:
            seen.add(ch)
            deduped.append(i)
    return deduped


# ---- LLM scoring (reusing llm_batch_score rubric) ----
_RUBRIC_TEMPLATE = (
    "### 评分量规 (Rubric) ###\n"
    "章节号: {ch_num}\n"
    "章节内容:\n{chapter_text}\n\n"
    "1. 爽点强度 (1-10):\n"
    "   1-2: 纯铺垫/日常 3-4: 微爽感 5-6: 明显爽感 7-8: 强烈爽感 9-10: 巅峰爽感\n"
    "2. 冲突等级: none/low/medium/high\n"
    "3. 情绪氛围: 爽快/紧张/悲壮/悬疑/日常/温情/压抑\n"
    "4. 节奏: fast/medium/slow\n"
    "5. 钩子质量: none/weak/strong\n"
    "6. 读者留存力 (1-10): 这章读完后读者有多大动力继续看?\n\n"
    "输出纯JSON:\n"
    '{"intensity":5,"conflict":"medium","emotion":"日常","pace":"medium","hook":"weak","retention":5}'
)


def _build_rubric_prompt(chapter_text, ch_num):
    text = chapter_text
    if len(text) > 1200:
        text = text[:400] + "\n...[中段省略]...\n" + text[-800:]
    else:
        text = text[:1200]
    return (_RUBRIC_TEMPLATE
            .replace("{ch_num}", str(ch_num))
            .replace("{chapter_text}", text))


def _llm_score(chapter_text, ch_num):
    """Single-chapter LLM rubric score with retry."""
    prompt = _build_rubric_prompt(chapter_text, ch_num)
    data = json.dumps({
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 180, "temperature": 0.1,
    }).encode("utf-8")

    retry_delays = [2, 5, 10, 20]  # increased: 5 total attempts with backoff
    for attempt, delay in enumerate([0] + retry_delays):
        if attempt > 0:
            time.sleep(delay)
        try:
            req = urllib.request.Request(
                f"{LLAMA_BASE}/v1/chat/completions",
                data, {"Content-Type": "application/json"}
            )
            resp = json.loads(urllib.request.urlopen(req, timeout=90).read())
            raw = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
            if raw:
                break
        except (urllib.error.URLError, TimeoutError, ConnectionError,
                json.JSONDecodeError, KeyError):
            if attempt >= len(retry_delays):
                return None
    else:
        return None

    # Parse JSON
    for pat in [r'\{[^{}]*?"intensity"[^{}]*?\}', r'\{[^{]*"intensity"[^}]*\}']:
        m = re.search(pat, raw)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                continue
    return None


# ---- Book-level deep analyze ----
def deep_analyze_book(txt_path, csv_path, do_llm=True, n_key=30):
    """Two-stage deep analysis of a single book.
    
    Stage 1: rule data from existing rhythm CSV → adaptive_keyframe()
    Stage 2: LLM rubric on key chapters (only if do_llm=True)
    
    Returns dict with diagnosis data.
    """
    name = Path(txt_path).stem

    # Stage 1: Load rule data
    rows = []
    if csv_path and csv_path.exists():
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            rows = list(csv.DictReader(f))
    if not rows:
        print(f"  [SKIP] {name[:40]}: no rhythm data")
        return None

    total_ch = len(rows)
    key_idx = adaptive_keyframe(rows, n_key)

    # Extract chapters
    chapters = _extract_chapters(txt_path)
    if not chapters:
        print(f"  [SKIP] {name[:40]}: cannot extract chapters")
        return None

    # Build lookup: ch_num → chapter dict
    ch_by_num = {ch["num"]: ch for ch in chapters}

    # Stage 1 stats from full rule data
    hooks = [float(r.get("hook_density", 0)) for r in rows]
    conflicts = [float(r.get("conflict_density", 0)) for r in rows]
    pleasures = [float(r.get("pleasure_intensity", 0)) for r in rows]
    dialogue_ratios = [float(r.get("dialogue_ratio", 0)) for r in rows]

    zero_hook_streak = 0
    cur = 0
    for r in rows:
        if float(r.get("hook_density", 0)) < 0.1:
            cur += 1
        else:
            zero_hook_streak = max(zero_hook_streak, cur)
            cur = 0
    zero_hook_streak = max(zero_hook_streak, cur)

    hook_types = Counter(r.get("hook_type", "none") for r in rows)
    conflict_levels = Counter(r.get("conflict_level", "none") for r in rows)

    diagnosis = {
        "book": name,
        "total_chapters": total_ch,
        "avg_hook": round(statistics.mean(hooks), 2),
        "avg_conflict": round(statistics.mean(conflicts), 2),
        "avg_pleasure": round(statistics.mean(pleasures), 1),
        "avg_dialogue_ratio": round(statistics.mean(dialogue_ratios) * 100, 1),
        "max_zero_hook_streak": zero_hook_streak,
        "hook_type_dist": dict(hook_types),
        "conflict_level_dist": dict(conflict_levels),
        "key_chapters": [],
    }

    # Stage 2: LLM on key chapters
    print(f"  {name[:40]}: {total_ch}ch → {len(key_idx)} key ({'LLM' if do_llm else '规则 only'})")

    llm_ok = 0
    for idx in key_idx:
        r = rows[idx]
        ch_num = int(r.get("ch_num", idx + 1))

        ch_data = {
            "ch_num": ch_num,
            "wc": int(r.get("wc", 0)),
            "hook_density": float(r.get("hook_density", 0)),
            "conflict_density": float(r.get("conflict_density", 0)),
            "pleasure_intensity": float(r.get("pleasure_intensity", 0)),
            "dialogue_ratio": float(r.get("dialogue_ratio", 0)),
            "hook_type": r.get("hook_type", "none"),
            "conflict_level": r.get("conflict_level", "none"),
            "emotion": r.get("emotion", "none"),
            "pace": r.get("pace", "medium"),
        }

        if do_llm and ch_num in ch_by_num:
            llm_result = _llm_score(ch_by_num[ch_num]["raw_body"], ch_num)
            if llm_result:
                ch_data["llm_intensity"] = llm_result.get("intensity", 0)
                ch_data["llm_conflict"] = llm_result.get("conflict", "none")
                ch_data["llm_emotion"] = llm_result.get("emotion", "none")
                ch_data["llm_pace"] = llm_result.get("pace", "medium")
                ch_data["llm_hook"] = llm_result.get("hook", "none")
                ch_data["llm_retention"] = llm_result.get("retention", 0)
                llm_ok += 1

        diagnosis["key_chapters"].append(ch_data)

    # P0: final retry pass — serial retry any chapters that failed LLM
    if do_llm and llm_ok < len(diagnosis["key_chapters"]):
        failed = [c for c in diagnosis["key_chapters"]
                  if "llm_retention" not in c and c["ch_num"] in ch_by_num]
        if failed:
            print(f"    [RETRY] {len(failed)} LLM chapters failed, serial retry...")
            for c in failed:
                time.sleep(1.5)
                llm_result = _llm_score(ch_by_num[c["ch_num"]]["raw_body"], c["ch_num"])
                if llm_result:
                    c["llm_intensity"] = llm_result.get("intensity", 0)
                    c["llm_conflict"] = llm_result.get("conflict", "none")
                    c["llm_emotion"] = llm_result.get("emotion", "none")
                    c["llm_pace"] = llm_result.get("pace", "medium")
                    c["llm_hook"] = llm_result.get("hook", "none")
                    c["llm_retention"] = llm_result.get("retention", 0)
                    llm_ok += 1
    if do_llm:
        print(f"    LLM: {llm_ok}/{len(diagnosis['key_chapters'])} chapters scored")

    return diagnosis


def _detect_simple_subgenre(diag):
    """Simple sub-genre classification from rhythm stats (no LLM needed).
    Returns one of: 基地种田, 纯爽文, 智斗慢热, 羁绊情感, 标准末世, None"""
    hook = diag.get("avg_hook", 0)
    conflict = diag.get("avg_conflict", 0)
    dialogue = diag.get("avg_dialogue_ratio", 0)
    # High dialogue → 基地种田/日常流
    if dialogue > 35:
        return "基地种田"
    # Low conflict + high hook → 纯爽文 (技巧驱动)
    if conflict < 0.8 and hook > 1.8:
        return "纯爽文"
    # Low hook + high conflict → 智斗/慢热
    if hook < 1.2 and conflict > 1.0:
        return "智斗慢热"
    # Medium hook + high pleasure diversity → 羁绊/人物
    if 1.2 <= hook <= 2.5 and conflict > 0.8:
        return "羁绊情感"
    return "标准末世"


# ---- Comparison report ----
def _write_comparison(top_diags, bottom_diags, genre, out_dir, borda_map=None):
    """Write side-by-side comparison between Top and Bottom books."""
    lines = []
    lines.append(f"# {genre} · Top vs Bottom 对比诊断")
    lines.append(f"\n> 基于 Borda 共识排名，二阶段分层分析（全章规则 + 关键章LLM）")
    lines.append(f"> Top-3 = 怎么写好的 | Bottom-3 = 什么导致坏的")
    lines.append("")

    # Summary table
    lines.append("## 一、整体对比")
    lines.append("")
    lines.append("| 维度 | Top-3 均值 | Bottom-3 均值 | 差距 |")
    lines.append("|------|:---:|:---:|:---:|")

    metrics = [
        ("avg_hook", "钩子密度"),
        ("avg_conflict", "冲突密度"),
        ("avg_pleasure", "爽点强度"),
        ("avg_dialogue_ratio", "对话率(%)"),
        ("max_zero_hook_streak", "最长零钩子连章"),
    ]
    for key, label in metrics:
        top_val = statistics.mean([d[key] for d in top_diags if d])
        bot_val = statistics.mean([d[key] for d in bottom_diags if d])
        gap = round(abs(top_val - bot_val), 2)
        lines.append(f"| {label} | {top_val:.2f} | {bot_val:.2f} | {gap} |")

    lines.append("")
    lines.append("## 二、逐书诊断")
    lines.append("")

    for label, diags in [("Top-3 (精品)", top_diags), ("Bottom-3 (对照)", bottom_diags)]:
        lines.append(f"### {label}")
        lines.append("")
        for d in diags:
            if not d:
                continue
            lines.append(f"#### {d['book']}")
            lines.append(f"- 总章数: {d['total_chapters']} | 零钩子最长: {d['max_zero_hook_streak']}章")
            lines.append(f"- 钩子密度: {d['avg_hook']} | 冲突: {d['avg_conflict']} | 爽点: {d['avg_pleasure']} | 对话率: {d['avg_dialogue_ratio']}%")
            lines.append(f"- 钩子类型分布: {d.get('hook_type_dist', {})}")
            lines.append(f"- 冲突等级分布: {d.get('conflict_level_dist', {})}")
            lines.append("")

            # Key chapter details (first 5 and any "broken" chapters)
            key_chs = d.get("key_chapters", [])
            broken = [c for c in key_chs if c["hook_density"] < 0.1]
            peaks = sorted(key_chs, key=lambda c: c["conflict_density"], reverse=True)[:3]

            if broken:
                lines.append("- **钩子断裂章**:")
                for c in broken[:5]:
                    lines.append(f"  - Ch{c['ch_num']}: hook={c['hook_density']:.2f} conflict={c['conflict_density']:.2f}")

            if peaks:
                lines.append("- **冲突高峰章**:")
                for c in peaks:
                    lines.append(f"  - Ch{c['ch_num']}: conflict={c['conflict_density']:.2f} hook={c['hook_density']:.2f}")
            lines.append("")

    lines.append("## 三、关键发现")
    lines.append("")
    lines.append("| 差异点 | Top-3 | Bottom-3 | 建议 |")
    lines.append("|------|------|------|------|")
    top_avg_hook = statistics.mean([d["avg_hook"] for d in top_diags if d])
    bot_avg_hook = statistics.mean([d["avg_hook"] for d in bottom_diags if d])
    lines.append(f"| 前3章吸力 | {top_avg_hook:.2f} | {bot_avg_hook:.2f} | 开篇必须每章收钩 |")

    top_streak = max((d.get("max_zero_hook_streak", 0) for d in top_diags if d), default=0)
    bot_streak = max((d.get("max_zero_hook_streak", 0) for d in bottom_diags if d), default=0)
    lines.append(f"| 读者流失风险 | 最大{top_streak}章连续零钩 | 最大{bot_streak}章连续零钩 | 连续2章零钩→弃书 |")

    top_dialogue = statistics.mean([d["avg_dialogue_ratio"] for d in top_diags if d])
    bot_dialogue = statistics.mean([d["avg_dialogue_ratio"] for d in bottom_diags if d])
    # Sub-genre aware dialogue advice — 基地种田文高对话率为特征非缺陷
    is_base_farming = any(_detect_simple_subgenre(d) == "基地种田" for d in top_diags + bottom_diags)
    dialogue_advice = "基地种田文高对话=子类型特征" if is_base_farming else "对话率>20%=读者不易疲劳"
    lines.append(f"| 节奏多样性 | 对话率{top_dialogue:.0f}% | 对话率{bot_dialogue:.0f}% | {dialogue_advice} |")

    # P0: Sub-genre context — prevent misjudging genre traits
    lines.append("")
    lines.append("### ⚠️ 子类型差异说明")
    lines.append("")
    lines.append("不同子类型的'好'标准不同，不能直接跨类型对比：")
    lines.append("")
    for d in top_diags + bottom_diags:
        sg = _detect_simple_subgenre(d)
        lines.append(f"- **{d['book'][:30]}**: {sg}")
    lines.append("")
    lines.append("> 例如：基地种田文高对话率(60%)是类型特征非水字数；智斗文慢热(低钩子高冲突)是叙事需求非节奏缺陷。")

    report_path = out_dir / f"{genre}_对比诊断.md"
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))
    print(f"  [OK] 对比报告: {report_path}")
    return report_path


# ---- Main entry ----
def run_deep(genre="末世", top_n=3, bottom_n=3, n_key=30):
    """Run two-stage deep analysis on Top-N and Bottom-N books.
    
    Args:
        genre: genre name
        top_n: number of top books to deep-analyze with LLM
        bottom_n: number of bottom books to deep-analyze (rule-only)
        n_key: key chapters per book (default 30)
    """
    # Load Borda ranking
    borda_path = PROJECT_ROOT / "outputs" / "reports" / genre / "synthesis" / f"{genre}_borda_ranking.json"
    if not borda_path.exists():
        print(f"[FAIL] Borda ranking not found: {borda_path}")
        print("  Run first: python analysis/genre_synthesizer.py --genre", genre)
        return None

    with open(borda_path, 'r', encoding='utf-8') as f:
        ranking = json.load(f)

    if len(ranking) < top_n + bottom_n:
        print(f"[FAIL] Only {len(ranking)} books, need at least {top_n + bottom_n}")
        return None

    # Build borda lookup map for per-book dimension display
    borda_map = {b["book_name"]: b for b in ranking}

    # Select books: Top-N by Borda (rank 1 = best)
    top_books = ranking[:top_n]
    bottom_books = ranking[-bottom_n:]  # worst N

    print("=" * 60)
    print(f"  Deep Diagnosis v7.4 | genre={genre} | {len(ranking)} books")
    print(f"  Top-{top_n} (LLM + 规则):")
    for b in top_books:
        print(f"    #{b['consensus_rank']}. {b['book_name'][:40]}")
    print(f"  Bottom-{bottom_n} (规则 only):")
    for b in bottom_books:
        print(f"    #{b['consensus_rank']}. {b['book_name'][:40]}")
    print(f"  Key chapters/book: {n_key}")
    print("=" * 60)

    # Load manifest for stem→file mapping
    manifest_path = PROJECT_ROOT / "data" / "processed" / "quality_manifest.json"
    stem_map = {}
    if manifest_path.exists():
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
        for a in manifest.get("approved", []):
            stem_map[a.get("stem", "")] = a.get("file", "")

    genre_dir = NOVELS_DIR / genre
    if not genre_dir.exists():
        print(f"[FAIL] Genre dir not found: {genre_dir}")
        return None

    # Find TXT and CSV for each book
    def _find_book(book_name):
        """Match book_name to file in genre dir and rhythm CSV."""
        # Try stem_map first
        for stem, filepath in stem_map.items():
            if book_name[:8] in stem or stem[:8] in book_name:
                txt_path = Path(filepath) if Path(filepath).exists() else None
                if not txt_path:
                    txt_path = genre_dir / filepath
                csv_path = RHYTHM_DIR / f"rhythm_{Path(filepath).stem}.csv"
                if csv_path.exists() and (txt_path and txt_path.exists()):
                    return txt_path, csv_path

        # Fallback: scan directory
        for txt in sorted(genre_dir.glob("*.txt")):
            if book_name[:6] in txt.stem or txt.stem[:6] in book_name:
                csv_path = RHYTHM_DIR / f"rhythm_{txt.stem}.csv"
                if csv_path.exists():
                    return txt, csv_path

        # Last fallback: try any CSV
        for csv_f in sorted(RHYTHM_DIR.glob("rhythm_*.csv")):
            stem = csv_f.stem.replace("rhythm_", "")
            if book_name[:6] in stem or stem[:6] in book_name:
                for txt in sorted(genre_dir.glob("*.txt")):
                    if txt.stem == stem:
                        return txt, csv_f

        return None, None

    # Check LLM server
    server_ok = False
    try:
        urllib.request.urlopen(f"{LLAMA_BASE}/health", timeout=3)
        server_ok = True
    except Exception:
        pass

    out_dir = OUTPUT_DIR / genre / "deep_diagnosis"
    out_dir.mkdir(parents=True, exist_ok=True)

    top_diags = []
    bottom_diags = []

    # Stage 2: Top-N with LLM
    for book in top_books:
        name = book["book_name"]
        txt_path, csv_path = _find_book(name)
        if not txt_path:
            print(f"  [SKIP] {name[:40]}: TXT/CSV not found")
            continue
        do_llm = server_ok
        if not server_ok:
            print("  [WARN] LLM server offline — rule-only mode")
        diag = deep_analyze_book(txt_path, csv_path, do_llm=do_llm, n_key=n_key)
        if diag:
            top_diags.append(diag)
            # Write per-book report with Borda dimensions
            _write_book_report(diag, out_dir, is_top=True,
                              borda_data=borda_map.get(name, {}))
        time.sleep(0.5)  # slight gap between books

    # Bottom-N: rule-only (zero LLM)
    for book in bottom_books:
        name = book["book_name"]
        txt_path, csv_path = _find_book(name)
        if not txt_path:
            print(f"  [SKIP] {name[:40]}: TXT/CSV not found")
            continue
        diag = deep_analyze_book(txt_path, csv_path, do_llm=False, n_key=n_key)
        if diag:
            bottom_diags.append(diag)
            _write_book_report(diag, out_dir, is_top=False,
                              borda_data=borda_map.get(name, {}))
        time.sleep(0.5)

    # Write comparison report
    if top_diags and bottom_diags:
        _write_comparison(top_diags, bottom_diags, genre, out_dir, borda_map=borda_map)

    # Save full JSON for downstream
    full_data = {
        "genre": genre,
        "top": [{"book": d["book"], **{k: d[k] for k in d if k != "key_chapters"}} for d in top_diags],
        "bottom": [{"book": d["book"], **{k: d[k] for k in d if k != "key_chapters"}} for d in bottom_diags],
        "top_key_chapters": {d["book"]: d["key_chapters"] for d in top_diags},
        "bottom_key_chapters": {d["book"]: d["key_chapters"] for d in bottom_diags},
    }
    json_path = out_dir / f"{genre}_deep_diagnosis.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(full_data, f, ensure_ascii=False, indent=2)

    print(f"\n[DONE] Deep diagnosis complete")
    print(f"  Reports: {out_dir}")
    print(f"  Books analyzed: {len(top_diags)} Top + {len(bottom_diags)} Bottom")
    print(f"  LLM chapters: ~{len(top_diags) * n_key} (Top only) | Rule chapters: ~{(len(top_diags) + len(bottom_diags)) * total_ch_template(n_key)}")
    return out_dir


def _write_book_report(diag, out_dir, is_top=True, borda_data=None):
    """Write per-book Markdown diagnosis."""
    prefix = "Top" if is_top else "Bottom"
    lines = []
    lines.append(f"# {diag['book']} · 逐章诊断")
    lines.append(f"\n> {'精品标杆' if is_top else '对照分析'} | {diag['total_chapters']}章")
    lines.append(f"> 钩子: {diag['avg_hook']} | 冲突: {diag['avg_conflict']} | 爽点: {diag['avg_pleasure']} | 对话率: {diag['avg_dialogue_ratio']}%")
    lines.append(f"> 最长零钩子连续: {diag['max_zero_hook_streak']}章")

    # P0: Show Borda dimension ranks for multi-dimensional transparency
    if borda_data:
        dims = borda_data.get("dim_ranks", {})
        if dims:
            lines.append(f"> Borda共识排名: #{borda_data.get('consensus_rank', '?')} | 维度分解:")
            dim_labels = {
                "hook_density": "钩子", "conflict": "冲突", "intensity": "爽点",
                "readability": "留存力", "diversity": "多样性", "bt_rank": "BT排名",
                "webnovel8": "WebN8", "dialogue": "对话"
            }
            parts = [f"{dim_labels.get(k, k)}:#{v}" for k, v in dims.items()]
            lines.append(f"> {' · '.join(parts)}")

    # P0: Sub-genre context — avoid mislabeling genre traits as defects
    sub_genre = _detect_simple_subgenre(diag)
    if sub_genre:
        notes = {
            "基地种田": "高对话率(>30%)为该子类型特征，非质量缺陷",
            "纯爽文": "低冲突+高钩子=技巧型爽文，重节奏轻深度",
            "智斗慢热": "低钩子率+高冲突=智斗/权谋型，重长线布局",
            "羁绊情感": "中钩子+高多样性=人物驱动型",
            "标准末世": "",
        }
        note = notes.get(sub_genre, "")
        if note:
            lines.append(f"> ⚠️ 子类型: {sub_genre} — {note}")
    lines.append("")

    hook_dist = diag.get("hook_type_dist", {})
    lines.append("## 钩子类型分布")
    for t, c in sorted(hook_dist.items(), key=lambda x: -x[1]):
        pct = round(c / max(diag['total_chapters'], 1) * 100)
        lines.append(f"- {t}: {c}章 ({pct}%)")
    lines.append("")

    lines.append("## 关键章节详情")
    lines.append("")
    lines.append("| 章号 | 字数 | 钩子密度 | 冲突密度 | 爽点 | 对话率 | 钩子类型 | LLM停留力 |")
    lines.append("|:---:|:---:|:---:|:---:|:---:|:---:|------|:---:|")
    for ch in diag.get("key_chapters", []):
        retention = ch.get("llm_retention", "-")
        lines.append(
            f"| {ch['ch_num']} | {ch['wc']} | {ch['hook_density']:.2f} | "
            f"{ch['conflict_density']:.2f} | {ch['pleasure_intensity']:.1f} | "
            f"{ch['dialogue_ratio']:.0%} | {ch['hook_type']} | {retention} |"
        )
    lines.append("")

    # Flag problem chapters
    broken = [c for c in diag.get("key_chapters", []) if c["hook_density"] < 0.1]
    if broken:
        lines.append("## ⚠️ 钩子断裂章")
        for c in broken:
            lines.append(f"- **Ch{c['ch_num']}**: 钩子密度={c['hook_density']:.2f}, 此处读者可能流失")
        lines.append("")

    report_path = out_dir / f"{prefix}_{diag['book'][:40]}_诊断.md"
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))


def total_ch_template(n_key):
    """Placeholder for per-book total_ch display."""
    return n_key


if __name__ == "__main__":
    import sys
    genre = "末世"
    top_n = 3
    bottom_n = 3
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--genre" and i < len(sys.argv) - 1:
            genre = sys.argv[i + 1]
        if arg == "--top" and i < len(sys.argv) - 1:
            top_n = int(sys.argv[i + 1])
        if arg == "--bottom" and i < len(sys.argv) - 1:
            bottom_n = int(sys.argv[i + 1])
    run_deep(genre=genre, top_n=top_n, bottom_n=bottom_n)
