#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
llm_batch_score.py — LLM rubric-based batch chapter scoring (v6 core upgrade)
Method: Rubric Is All You Need (ACM 2025) + Distilling Step-by-Step (ACL 2023)
Replaces: rule-based pleasure_intensity/conflict_level/emotion/pace with LLM scores
Usage: python scripts/llm_batch_score.py --book all  (or --book 末世之黑暗时代)
Output: data/processed/llm_scores/{book}_llm.csv
"""
import csv
import json
import re
import sys
import statistics
import urllib.request
import urllib.parse
import http.client
import time
import threading
import concurrent.futures  # v3: max_workers=4 for RTX 5060 8GB with KV q8_0 (L0-3 optimization)
import yaml
from pathlib import Path

# L1-1: LLMLingua-2 lazy init (thread-safe, ~10-15% prompt processing speedup)
_lingua_lock = threading.Lock()
_lingua = None  # None=not tried, False=failed, obj=ready

def _init_lingua():
    """Thread-safe lazy init; first call downloads ~110MB, subsequent calls instant."""
    global _lingua
    if _lingua is False:
        return False  # already failed
    if _lingua:
        return True   # already loaded
    with _lingua_lock:
        if _lingua:
            return True
        if _lingua is False:
            return False
        try:
            from llmlingua import PromptCompressor
            _lingua = PromptCompressor(model_name="microsoft/llmlingua-2-bert-base", device_map="cpu")
            return True
        except Exception:
            _lingua = False
            return False
from collections import Counter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
NOVELS_DIR = PROJECT_ROOT / "data" / "raw" / "novels"
INDEX_PATH = PROJECT_ROOT / "data" / "raw" / "novel_index.json"


def _rhythm_dir(genre):
    return PROJECT_ROOT / "data" / "processed" / genre / "rhythm"


def _llm_dir(genre):
    return PROJECT_ROOT / "data" / "processed" / genre / "llm_scores"
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def _load_llama_base():
    """Read LLM server base URL from config.yaml, fallback to default."""
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f)
        port = cfg.get("model_orchestration", {}).get("models", {}).get("main_model", {}).get("port", 8000)
        return f"http://127.0.0.1:{port}"
    except Exception:
        return "http://127.0.0.1:8000"


LLAMA_BASE = _load_llama_base()
LLAMA_HOST = urllib.parse.urlparse(LLAMA_BASE).netloc  # e.g. "127.0.0.1:8000"


def _get_server_parallel():
    """Read LLM server parallel setting from config.yaml for optimal worker count."""
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f)
        return cfg.get("analysis", {}).get("llm_parallel", 2)
    except Exception:
        return 2


LLM_PARALLEL = _get_server_parallel()

sys.path.insert(0, str(PROJECT_ROOT / "analysis"))
from rhythm_analyzer import extract_chapters


def check_server():
    try:
        urllib.request.urlopen(f"{LLAMA_BASE}/health", timeout=3)
        return True
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return False


# ── Rubric template (DRY: shared by single-pass and self-consistency scoring) ──
_RUBRIC_TEMPLATE = (
    "=== 你是专业网文编辑，对章节阅读体验独立评分 ===\n\n"
    "第{ch_num}章:\n{chapter_text}\n\n"
    "### 评分量规 (Rubric) ###\n"
    "1. 爽点强度 (1-10):\n"
    "   1-2: 纯铺垫/日常，无任何情绪起伏\n"
    "   3-4: 有微爽感（小收获/小反转）\n"
    "   5-6: 明显爽感（打脸成功/突破/反杀）\n"
    "   7-8: 强烈爽感（碾压对手/绝境翻盘/关键角色高光）\n"
    "   9-10: 巅峰爽感（全书高潮/神级反转/读者拍案）\n\n"
    "2. 冲突等级: none/low/medium/high\n"
    "   none=零冲突 low=微小摩擦 medium=明显对抗 high=生死/极端冲突\n\n"
    "3. 情绪氛围: 爽快/紧张/悲壮/悬疑/日常/温情/压抑\n\n"
    "4. 节奏: fast/medium/slow\n\n"
    "5. 钩子质量: none/weak/strong\n"
    "   none=章末无悬念 weak=微悬念 strong=强悬念(读者必须看下一章)\n\n"
    "6. 读者留存力 (1-10): 这章读完后读者有多大动力继续看?\n"
    "   1-3=可能弃书 5=普通 7=想追 10=熬夜也要看\n\n"
    "输出纯JSON(只输出JSON，不要任何其他文字):\n"
    '{"intensity":5,"conflict":"medium","emotion":"日常","pace":"medium","hook":"weak","retention":5}'
)


def _build_rubric_prompts(chapter_text, ch_num):
    """Build system+user message pair for rubric scoring.
    v9: Prefix Caching — rubric in system (fixed), chapter in user (variable).
    llama-server --cache-prompt reuses KV for system prefix across all calls."""
    text = chapter_text
    if len(text) > 1200:
        text = text[:400] + "\n...[中段省略...\n" + text[-800:]
    else:
        text = text[:1200]

    # System message: fixed rubric template (KV cache reusable)
    system_msg = _RUBRIC_TEMPLATE
    if not getattr(_build_rubric_prompts, "_rubric_cached", False) and _init_lingua():
        try:
            system_msg = _lingua.compress_prompt(
                _RUBRIC_TEMPLATE, rate=0.5, force_tokens=["intensity", "conflict", "emotion", "pace", "hook", "retention", "JSON"]
            )["compressed_prompt"]
            _build_rubric_prompts._rubric_cached = True
        except Exception:
            pass

    # User message: only chapter-specific content (varies per call)
    user_msg = f"第{ch_num}章:\n{text}"
    return system_msg, user_msg


def llm_score_rubric(chapter_text, ch_num, conn=None):
    """Rubric-based scoring (Rubric Is All You Need, ACM 2025).
    v9: system/user separation for prefix caching."""
    system_msg, user_msg = _build_rubric_prompts(chapter_text, ch_num)
    data = json.dumps({
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ],
        "max_tokens": 180, "temperature": 0.1,
    }).encode("utf-8")

    # P0-2: retry with exponential backoff (slot contention → transient failure)
    retry_delays = [2, 5]
    for attempt, delay in enumerate([0] + retry_delays):
        if attempt > 0:
            time.sleep(delay)
        try:
            if conn:
                conn.request("POST", "/v1/chat/completions", body=data,
                            headers={"Content-Type": "application/json"})
                resp = json.loads(conn.getresponse().read())
            else:
                req = urllib.request.Request(
                    f"{LLAMA_BASE}/v1/chat/completions",
                    data, {"Content-Type": "application/json"}
                )
                resp = json.loads(urllib.request.urlopen(req, timeout=60).read())
            raw = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not raw and attempt < len(retry_delays):
                continue  # empty response → retry
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError,
                http.client.HTTPException, json.JSONDecodeError, KeyError):
            if attempt >= len(retry_delays):
                raise  # all retries exhausted
    else:
        return None  # all attempts failed

    # JSON extraction
    try:
        for pat in [r'\{[^{}]*?"intensity"[^{}]*?\}', r'\{[^{]*"intensity"[^}]*\}']:
            m = re.search(pat, raw)
            if m:
                try:
                    res = json.loads(m.group())
                    if "intensity" in res:
                        return res
                except:
                    continue
        # Fallback: field extraction
        pi = re.search(r'"intensity"\s*:\s*(\d+(?:\.\d+)?)', raw)
        cl = re.search(r'"conflict"\s*:\s*"([^"]+)"', raw)
        em = re.search(r'"emotion"\s*:\s*"([^"]+)"', raw)
        pa = re.search(r'"pace"\s*:\s*"([^"]+)"', raw)
        hq = re.search(r'"hook"\s*:\s*"([^"]+)"', raw)
        rt = re.search(r'"retention"\s*:\s*(\d+(?:\.\d+)?)', raw)
        if pi:
            return {
                "intensity": float(pi.group(1)),
                "conflict": cl.group(1) if cl else "medium",
                "emotion": em.group(1) if em else "日常",
                "pace": pa.group(1) if pa else "medium",
                "hook": hq.group(1) if hq else "none",
                "retention": float(rt.group(1)) if rt else 5,
            }
        return None
    except (json.JSONDecodeError, KeyError, ValueError, urllib.error.URLError, TimeoutError,
            http.client.HTTPException, ConnectionError) as e:
        print(f"  [WARN] LLM评分解析失败(ch{ch_num}): {e}")
        return None


def llm_score_self_consistency(chapter_text, ch_num, n_samples=3, conn=None):
    """v8: Self-Consistency multi-sample scoring (Wang et al. 2022 + TURN arxiv 2502.05234).
    Calls LLM n_samples times with diverse temperatures (0.1, 0.2, 0.3), then aggregates:
    - numeric fields: median → robust to outliers
    - categorical fields: mode (most common) → consensus
    Falls back to single sample if >=50% calls fail."""
    temps = [0.1, 0.2, 0.3][:n_samples]  # Diverse temperature sampling
    results = []
    for t in temps:
        # Multiple temperature samples for self-consistency
        try:
            system_msg, user_msg = _build_rubric_prompts(chapter_text, ch_num)
            data = json.dumps({
                "messages": [
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg}
                ],
                "max_tokens": 180, "temperature": t,
            }).encode("utf-8")
            if conn:
                conn.request("POST", "/v1/chat/completions", body=data,
                            headers={"Content-Type": "application/json"})
                resp = json.loads(conn.getresponse().read())
            else:
                req = urllib.request.Request(
                    f"{LLAMA_BASE}/v1/chat/completions",
                    data, {"Content-Type": "application/json"}
                )
                resp = json.loads(urllib.request.urlopen(req, timeout=45).read())
            raw = resp["choices"][0]["message"].get("content", "")
            for pat in [r'\{[^{}]*?"intensity"[^{}]*?\}', r'\{[^{]*"intensity"[^}]*\}']:
                m = re.search(pat, raw)
                if m:
                    try:
                        res = json.loads(m.group())
                        if "intensity" in res:
                            results.append(res)
                            break
                    except:
                        continue
            else:
                # Fallback: field extraction
                pi = re.search(r'"intensity"\s*:\s*(\d+(?:\.\d+)?)', raw)
                cl = re.search(r'"conflict"\s*:\s*"([^"]+)"', raw)
                em = re.search(r'"emotion"\s*:\s*"([^"]+)"', raw)
                pa = re.search(r'"pace"\s*:\s*"([^"]+)"', raw)
                hq = re.search(r'"hook"\s*:\s*"([^"]+)"', raw)
                rt = re.search(r'"retention"\s*:\s*(\d+(?:\.\d+)?)', raw)
                if pi:
                    results.append({
                        "intensity": float(pi.group(1)),
                        "conflict": cl.group(1) if cl else "medium",
                        "emotion": em.group(1) if em else "日常",
                        "pace": pa.group(1) if pa else "medium",
                        "hook": hq.group(1) if hq else "none",
                        "retention": float(rt.group(1)) if rt else 5,
                    })
        except:
            continue
        time.sleep(0.1)  # Minimal gap between SC samples

    if len(results) < n_samples * 0.5:
        return None  # Too many failures, fall back

    # Aggregate: median for numeric, mode for categorical
    return {
        "intensity": round(statistics.median([r["intensity"] for r in results]), 1),
        "conflict": Counter(r["conflict"] for r in results).most_common(1)[0][0],
        "emotion": Counter(r["emotion"] for r in results).most_common(1)[0][0],
        "pace": Counter(r["pace"] for r in results).most_common(1)[0][0],
        "hook": Counter(r["hook"] for r in results).most_common(1)[0][0],
        "retention": round(statistics.median([r["retention"] for r in results]), 1),
    }


def batch_book(txt_path, csv_path, max_chapters=None, sc_samples=1):
    """Batch-score all chapters in a book, merge with existing rhythm CSV.
    sc_samples: Self-Consistency samples (1=single pass, 3=multi-sample median/mode aggregation)
    Saves: data/llm_scores/{book}_llm.csv"""
    chapters = extract_chapters(txt_path)
    if not chapters:
        return None

    # Load existing rule CSV for base info
    rule_rows = {}
    if csv_path and csv_path.exists():
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                rule_rows[int(r["ch_num"])] = r

    # Determine sample rate: all chapters if max=None, else evenly spaced
    if max_chapters and len(chapters) > max_chapters:
        step = max(1, len(chapters) // max_chapters)
        idx_to_score = list(range(0, len(chapters), step))[:max_chapters]
    else:
        idx_to_score = list(range(len(chapters)))

    name = Path(txt_path).stem
    n = len(idx_to_score)
    print(f"  Scoring {n}/{len(chapters)} chapters (parallel x2)...")

    # v8: Parallel scoring with ThreadPoolExecutor (uses server --parallel 2)
    def _score_chapter(packed):
        i, idx = packed
        ch = chapters[idx]
        ch_num = ch.get("num", i + 1)
        # Each thread gets its own HTTP connection (not thread-safe shared)
        t_conn = http.client.HTTPConnection(LLAMA_HOST, timeout=45)
        try:
            if sc_samples > 1:
                llm = llm_score_self_consistency(ch["raw_body"], ch_num, sc_samples, t_conn)
            else:
                llm = llm_score_rubric(ch["raw_body"], ch_num, t_conn)
        finally:
            t_conn.close()
        rule = rule_rows.get(ch_num, {})
        if llm is None:
            return (i, ch_num, None)
        return (i, ch_num, llm, rule, ch["wc"])

    # Submit all, collect in order (v9: max_workers matches server --parallel)
    ordered = [None] * n
    with concurrent.futures.ThreadPoolExecutor(max_workers=LLM_PARALLEL) as executor:
        futures = {}
        for packed in enumerate(idx_to_score):
            fut = executor.submit(_score_chapter, packed)
            futures[fut] = packed[0]

        completed = 0
        for fut in concurrent.futures.as_completed(futures):
            try:
                i, ch_num, *rest = fut.result(timeout=60)
                ordered[i] = (ch_num, rest)
            except Exception as e:
                i = futures[fut]
                ch_num = idx_to_score[i] + 1
                print(f"    Ch{ch_num} [FAIL] {type(e).__name__}", flush=True)
                ordered[i] = (ch_num, [None])
            completed += 1
            pct = round(completed / n * 100)
            status = f"Ch{ch_num} ({pct}%)" if rest[0] is not None else f"Ch{ch_num} [FAIL]"
            print(f"    {status}", flush=True)

    # P1-4: collect failed chapters → serial retry (avoids slot contention)
    failed = [(i, ordered[i]) for i in range(n)
              if ordered[i] is not None and ordered[i][1][0] is None]
    if failed:
        print(f"  [RETRY] {len(failed)} failed chapters, serial retry...")
        retry_success = 0
        for i, (ch_num, _) in failed:
            idx = idx_to_score[i]
            ch = chapters[idx]
            ch_num_actual = ch.get("num", idx + 1)
            rule = rule_rows.get(ch_num_actual, {})
            # Serial: no ThreadPool, direct call with fresh connection
            conn = http.client.HTTPConnection(LLAMA_HOST, timeout=60)
            try:
                if sc_samples > 1:
                    llm = llm_score_self_consistency(ch["raw_body"], ch_num_actual, sc_samples, conn)
                else:
                    llm = llm_score_rubric(ch["raw_body"], ch_num_actual, conn)
            finally:
                conn.close()
            if llm is not None:
                ordered[i] = (ch_num_actual, [llm, rule, ch["wc"]])
                retry_success += 1
                print(f"    Ch{ch_num_actual} [OK retry]", flush=True)
            else:
                print(f"    Ch{ch_num_actual} [retry FAIL]", flush=True)
        print(f"  [RETRY] recovered {retry_success}/{len(failed)} chapters", flush=True)

    # Build results in original order
    results = []
    for i in range(n):
        item = ordered[i]
        if item is None or item[1][0] is None:
            continue
        ch_num, (llm, rule, ch_wc) = item
        row = {
            "ch_num": ch_num,
            "wc": int(rule.get("wc", ch_wc)),
            # LLM scores (primary)
            "llm_intensity": float(llm["intensity"]),
            "llm_conflict": llm["conflict"],
            "llm_emotion": llm["emotion"],
            "llm_pace": llm["pace"],
            "llm_hook": llm["hook"],
            "llm_retention": float(llm["retention"]),
            # Rule scores (reference)
            "rule_intensity": float(rule.get("pleasure_intensity", 0)),
            "rule_hook": rule.get("hook_type", "none"),
            "rule_emotion": rule.get("emotion", "日常"),
            "rule_pace": rule.get("pace", "medium"),
        }
        results.append(row)
        print(f"L:{llm['intensity']:.0f}R:{row['rule_intensity']:.1f}H:{llm['hook']}")

    if not results:
        return None

    # Save
    genre = Path(txt_path).parent.name
    llm_out = _llm_dir(genre)
    llm_out.mkdir(parents=True, exist_ok=True)
    out_path = llm_out / f"{name}_llm.csv"
    fields = ["ch_num", "wc",
              "llm_intensity", "llm_conflict", "llm_emotion", "llm_pace", "llm_hook", "llm_retention",
              "rule_intensity", "rule_hook", "rule_emotion", "rule_pace"]
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(results)

    # Stats
    intens = [r["llm_intensity"] for r in results]
    print(f"  [OK] N={len(results)} | intensity {min(intens):.0f}-{max(intens):.0f} mean={statistics.mean(intens):.1f} | {out_path}")
    return out_path


def main():
    if not check_server():
        print(f"[FAIL] LLM server not running at {LLAMA_BASE}")
        print("  Start with: scripts\\start_model.bat")
        return

    # Parse args
    book_filter = None
    max_ch = 30  # default: 30 chapters per book for speed
    genre = "末世"  # default from config convention
    sc_samples = 1  # v8: Self-Consistency samples (1=single, 3=recommended)
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--book" and i < len(sys.argv) - 1:
            book_filter = sys.argv[i + 1]
        if arg == "--max" and i < len(sys.argv) - 1:
            max_ch = int(sys.argv[i + 1])
        if arg == "--genre" and i < len(sys.argv) - 1:
            genre = sys.argv[i + 1]
        if arg == "--sc" and i < len(sys.argv) - 1:
            sc_samples = int(sys.argv[i + 1])

    with open(INDEX_PATH, 'r', encoding='utf-8') as f:
        index = json.load(f)
    novels = index["genres"].get(genre, {}).get("novels", [])
    if not novels:
        print(f"[FAIL] No {genre} novels in index")
        return

    for novel in novels:
        txt_file = novel.get("file", "")
        if book_filter and book_filter not in txt_file:
            continue
        txt_path = None
        for fp in NOVELS_DIR.glob("**/*.txt"):
            if fp.name == txt_file:
                txt_path = fp
                break
        if not txt_path:
            print(f"[SKIP] TXT not found: {txt_file} (searched in {NOVELS_DIR})")
            continue

        csv_name = novel.get("rhythm_csv", "")
        csv_path = _rhythm_dir(genre) / csv_name if csv_name else None

        print(f"\n[BOOK] {txt_file[:40]}")
        batch_book(txt_path, csv_path, max_ch, sc_samples)

    print(f"\n[DONE] LLM scores saved to {_llm_dir(genre)}")


if __name__ == "__main__":
    main()
