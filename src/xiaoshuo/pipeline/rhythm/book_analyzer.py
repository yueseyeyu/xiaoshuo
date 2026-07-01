# -*- coding: utf-8 -*-
"""
book_analyzer.py — 全书分析编排 + 对比排名
============================================
analyze_book(): 全书分析 (规则分析 + LLM验证 + CSV写入 + 缓存)
compare(): 多书百分位排名 (WebNovelBench PCA method)

P2.7: 所有 print() 已替换为 logger 调用。
"""
from __future__ import annotations

import csv
import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from xiaoshuo import PROJECT_ROOT
from xiaoshuo.infra.logging_config import get_logger
from xiaoshuo.infra.llm_client import check_llm_health
from xiaoshuo.pipeline.paths import rhythm_dir as _rhythm_dir, novels_dir as _novels_dir
from xiaoshuo.pipeline.rhythm.chapter_parser import extract_chapters
from xiaoshuo.pipeline.rhythm.rule_analyzer import rule_analyze
from xiaoshuo.pipeline.rhythm.llm_verifier import llm_verify, _map_llm_response
from xiaoshuo.pipeline.rhythm.cache_manager import (
    CACHE_VERSION, load_cached_summary, check_cache_version, save_cache_version,
)
from xiaoshuo.pipeline.metrics_schema import ChapterMetrics, BookSummary

logger = get_logger("rhythm.book_analyzer")

NOVELS_DIR = _novels_dir()

# bridge to writing_instructions for per-chapter diagnostics
try:
    from xiaoshuo.pipeline.writing_instructions import generate_chapter_instructions
    _instructions_available = True
except ImportError:
    _instructions_available = False


def _get_llm_parallel():
    """Read LLM parallelism from config.yaml. Falls back to 2."""
    try:
        from xiaoshuo.infra.config_manager import get_config
        cfg = get_config()
        return cfg.get("analysis", {}).get("llm_parallel", 2)
    except Exception:
        return 2


def _write_chapter_instructions(name, results, csv_path):
    """Bridge — generate & write per-chapter writing instructions."""
    if not _instructions_available:
        logger.debug("writing_instructions unavailable, skipping")
        return
    lines, issue_count = generate_chapter_instructions(results, name)
    genre = csv_path.parent.parent.name
    out_dir = PROJECT_ROOT / "data" / "reports" / genre / "writing_manuals"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{name}_逐章指令.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("逐章指令: %s (%d issues)", out_path.name, issue_count)


def analyze_book(filepath):
    """Full analysis. Rule-based + LLM verify 5 key chapters. Saves CSV immediately.
    v6: CSV cache — skip re-analysis if CSV exists and is newer than txt.
    v11: +章节级版本化缓存 (per-chapter hash comparison + cache version)"""
    name = Path(filepath).stem
    logger.info("[BOOK] %s", name)
    t0 = time.time()

    genre = Path(filepath).parent.name
    csv_path = _rhythm_dir(genre) / f"rhythm_{name}.csv"
    version_path = csv_path.with_suffix(".version")
    cache_version_match = check_cache_version(version_path)
    if not cache_version_match and csv_path.exists():
        logger.info("  [CACHE] Cache version mismatch (expected %d), force full re-analysis", CACHE_VERSION)

    chapters = extract_chapters(filepath)
    if csv_path.exists() and cache_version_match:
        txt_mtime = Path(filepath).stat().st_mtime
        csv_mtime = csv_path.stat().st_mtime
        if csv_mtime > txt_mtime:
            new_hashes = [
                hashlib.sha256(ch["raw_body"].encode("utf-8")).hexdigest()[:16]
                for ch in chapters
            ]
            cached_hashes = []
            try:
                with open(csv_path, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        cached_hashes.append(row.get("ch_hash", ""))
            except Exception:
                cached_hashes = []

            if len(new_hashes) == len(cached_hashes) and new_hashes == cached_hashes:
                cached = load_cached_summary(csv_path, name)
                if cached:
                    dt = time.time() - t0
                    logger.info("  [CACHE] All chapters unchanged, full cache hit (%.1fs)", dt)
                    logger.info("  P-density=%.2f  Conflict=%.2f  Intensity=%.1f  Hook=%.1f/k",
                                cached['pleasure_density'], cached['conflict_rate'],
                                cached['avg_intensity'], cached['avg_hook'])
                    return cached
            elif len(new_hashes) == len(cached_hashes):
                changed = [i for i, (n, c) in enumerate(zip(new_hashes, cached_hashes)) if n != c]
                logger.info("  [CACHE] %d/%d chapters changed (v11 partial)", len(changed), len(new_hashes))
            else:
                logger.info("  [CACHE] Chapter count mismatch, re-analyze")

    total = len(chapters)
    total_wc = sum(c["wc"] for c in chapters)
    logger.info("  Chaps: %d  Words: %s  Avg: %s", total, f"{total_wc:,}", f"{total_wc//max(total,1):,}")

    # ── Phase 1: Rule-based all chapters (parallel, ThreadPool) ──
    workers = min(4, os.cpu_count() or 4)
    logger.info("  Analyzing %d chapters (rule-based, %d threads)...", total, workers)
    t1 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(rule_analyze, chapters))
    dt = time.time() - t1
    logger.info("  Phase 1 done: %.1fs (%.1fms/ch)", dt, dt/total*1000 if total else 0)

    # ── Phase 1b: Chapter-to-chapter variability ──
    for i, r in enumerate(results):
        if i == 0 or i == len(results) - 1:
            continue
        prev = results[i-1]
        diff = (
            abs(r["wc"] - prev["wc"]) / max(prev["wc"], 1) +
            abs(r["dialogue_ratio"] - prev["dialogue_ratio"]) / max(prev["dialogue_ratio"], 0.001) +
            abs(r["pos_density"] - prev["pos_density"]) / max(prev["pos_density"], 0.001) +
            abs(r["conflict_density"] - prev["conflict_density"]) / max(prev["conflict_density"], 0.001)
        ) / 4
        r["ch_variability"] = round(diff, 3)
    if results:
        results[0]["ch_variability"] = 0.0
        results[-1]["ch_variability"] = 0.0

    # ── 马良三级爽点递进: small/medium/large (3-ch sliding window) ──
    for i, r in enumerate(results):
        window = results[max(0,i-1):min(len(results),i+2)]
        intensities = [x["pleasure_intensity"] for x in window]
        avg_intensity = sum(intensities) / len(intensities)
        has_climax = any(x["pleasure_type"] == "climax" for x in window)
        has_major = any(x["pleasure_type"] == "major" for x in window)
        slap_total = sum(x["slap_count"] for x in window)

        if has_climax and avg_intensity >= 6:
            r["pleasure_level"] = "large"
        elif has_major and avg_intensity >= 4 and slap_total >= 3:
            r["pleasure_level"] = "medium"
        elif slap_total >= 1 or r["pleasure_intensity"] >= 2:
            r["pleasure_level"] = "small"
        else:
            r["pleasure_level"] = "none"

    # ── Phase 2: LLM-as-Judge sampling ──
    step = max(1, total // 10)
    verify_indices = set()
    for i in range(0, total, step):
        verify_indices.add(i)
    verify_indices.add(0)
    verify_indices.add(total - 1)
    sorted_by_intensity = sorted(results, key=lambda r: r["pleasure_intensity"], reverse=True)
    sorted_by_conflict = sorted(results, key=lambda r: r["conflict_density"], reverse=True)
    verify_indices.add(sorted_by_intensity[0]["ch_num"] - 1)
    verify_indices.add(sorted_by_conflict[0]["ch_num"] - 1)
    verify_indices = sorted(verify_indices)[:15]

    server_ok = check_llm_health(timeout=2)

    llm_correlation = None
    if server_ok:
        logger.info("  LLM-as-Judge sampling %d chapters (~%d%% coverage)...",
                     len(verify_indices), total//10 if total>10 else 1)
        llm_parallel = _get_llm_parallel()
        valid_indices = [vi for vi in verify_indices if vi < len(results)]

        def _verify_one(vi):
            return vi, llm_verify(chapters[vi], results[vi])

        rule_labels = []
        llm_labels = []
        verified = 0
        with ThreadPoolExecutor(max_workers=llm_parallel) as ex:
            futures = {ex.submit(_verify_one, vi): vi for vi in valid_indices}
            for future in as_completed(futures):
                vi, llm = future.result()
                r = results[vi]
                rule_labels.append(r["pleasure_intensity"])
                if llm:
                    llm = _map_llm_response(llm)
                    r["pleasure_type"] = llm.get("pleasure_type", r["pleasure_type"])
                    r["pleasure_intensity"] = llm.get("pleasure_intensity", r["pleasure_intensity"])
                    r["conflict_level"] = llm.get("conflict_level", r["conflict_level"])
                    r["emotion"] = llm.get("emotion", r["emotion"])
                    r["pace"] = llm.get("pace", r["pace"])
                    llm_labels.append(r["pleasure_intensity"])
                    verified += 1

        if len(rule_labels) > 5 and len(rule_labels) == len(llm_labels):
            n = len(rule_labels)
            mean_r = sum(rule_labels) / n
            mean_l = sum(llm_labels) / n
            cov = sum((rule_labels[i] - mean_r) * (llm_labels[i] - mean_l) for i in range(n))
            std_r = (sum((x - mean_r)**2 for x in rule_labels) / n) ** 0.5
            std_l = (sum((x - mean_l)**2 for x in llm_labels) / n) ** 0.5
            if std_r > 0 and std_l > 0:
                llm_correlation = round(cov / (std_r * std_l * n), 3)
                logger.info("  LLM-rule correlation r=%s (%d verified, %s)",
                            llm_correlation, verified,
                            'strong' if abs(llm_correlation)>0.7 else 'moderate' if abs(llm_correlation)>0.4 else 'weak')
    else:
        logger.debug("  [SKIP] No LLM server, pure rule-based")

    # ── Save CSV immediately (P2: 使用 ChapterMetrics 序列化，类型安全) ──
    genre = Path(filepath).parent.name
    csv_path = _rhythm_dir(genre) / f"rhythm_{name}.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fields = ChapterMetrics.CSV_FIELDS
    validated_rows = [ChapterMetrics.from_dict(r).to_csv_row() for r in results]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(validated_rows)

    save_cache_version(version_path)
    _write_chapter_instructions(name, results, csv_path)

    # ── Summary ──
    pleasure_density = sum(1 for r in results if r["pleasure_type"] != "none") / max(total, 1)
    conflict_rate = sum(1 for r in results if r["conflict"]) / max(total, 1)
    avg_intensity = sum(r["pleasure_intensity"] for r in results) / max(total, 1)
    avg_hook = sum(r.get("hook_density", 0) for r in results) / max(total, 1)
    sub_dist = {}
    for r in results:
        sub = r.get("dominant_sub", "none")
        sub_dist[sub] = sub_dist.get(sub, 0) + 1

    dt = time.time() - t0
    hook_dist = {}
    for r in results:
        ht = r.get("hook_type", "none")
        hook_dist[ht] = hook_dist.get(ht, 0) + 1
    level_dist = {}
    for r in results:
        pl = r.get("pleasure_level", "none")
        level_dist[pl] = level_dist.get(pl, 0) + 1
    avg_readability = sum(r.get("readability", 0) for r in results) / max(total, 1)

    timing_dist = {}
    for r in results:
        pt = r.get("pleasure_timing", "instant")
        timing_dist[pt] = timing_dist.get(pt, 0) + 1
    instant_ratio = timing_dist.get("instant", 0) / max(total, 1)

    logger.info("  [SAVED] %s  (%.0fs)", csv_path.name, dt)
    logger.info("  P-density=%.2f  Conflict=%.2f  Intensity=%.1f  Hook=%.1f/k  Readability=%.3f",
                pleasure_density, conflict_rate, avg_intensity, avg_hook, avg_readability)
    logger.info("  Subs: %s", dict(sorted(sub_dist.items(), key=lambda x:-x[1])))
    logger.info("  HookTypes: %s", dict(sorted(hook_dist.items(), key=lambda x:-x[1])))
    logger.info("  Levels: %s", dict(sorted(level_dist.items(), key=lambda x:-x[1])))
    logger.info("  Timing: instant=%d delayed=%d (ratio=%.1f%%)",
                timing_dist.get('instant',0), timing_dist.get('delayed',0), instant_ratio*100)

    return BookSummary.from_dict({
        "name": name, "total_chaps": total, "total_words": total_wc,
        "avg_wc": total_wc // max(total, 1),
        "pleasure_density": round(pleasure_density, 2),
        "conflict_rate": round(conflict_rate, 2),
        "avg_intensity": round(avg_intensity, 1),
        "avg_hook": round(avg_hook, 1),
        "sub_dist": {k: v for k, v in sorted(sub_dist.items(), key=lambda x: -x[1])},
        "llm_correlation": llm_correlation,
    }).to_dict()


def _percentile(values, p):
    """Compute p-th percentile (0-100) from sorted values."""
    if not values:
        return 0
    k = (len(values) - 1) * p / 100.0
    f = int(k)
    c = k - f
    if f + 1 < len(values):
        return values[f] + c * (values[f+1] - values[f])
    return values[f]


def compare(summaries):
    """Compare all books using percentile-based ranking (WebNovelBench PCA method)."""
    n = len(summaries)
    if n < 3:
        logger.info("  [SKIP] Need >=3 books for percentile ranking, got %d", n)
        return

    p_densities = sorted([s["pleasure_density"] for s in summaries])
    conflicts = sorted([s["conflict_rate"] for s in summaries])
    intensities = sorted([s["avg_intensity"] for s in summaries])
    hooks = sorted([s.get("avg_hook", 0) for s in summaries])

    p25 = lambda arr: _percentile(arr, 25)
    p50 = lambda arr: _percentile(arr, 50)
    p75 = lambda arr: _percentile(arr, 75)

    logger.info("=" * 70)
    logger.info("  ANALYSIS SYSTEM v3: PERCENTILE-BASED RANKING (WebNovelBench method)")
    logger.info("=" * 70)
    logger.info("  Thresholds (pooled from %d books):", n)
    logger.info("    P-density: P25=%.2f  P50=%.2f  P75=%.2f", p25(p_densities), p50(p_densities), p75(p_densities))
    logger.info("    Conflict:  P25=%.2f  P50=%.2f  P75=%.2f", p25(conflicts), p50(conflicts), p75(conflicts))
    logger.info("    Intensity: P25=%.1f  P50=%.1f  P75=%.1f", p25(intensities), p50(intensities), p75(intensities))
    logger.info("    Hook:      P25=%.1f  P50=%.1f  P75=%.1f", p25(hooks), p50(hooks), p75(hooks))

    pct_scores = []
    for s in summaries:
        def rank_pct(arr, val):
            if not arr or max(arr) == min(arr):
                return 50
            return round((sum(1 for x in arr if x <= val) / len(arr)) * 100)

        p_pct = rank_pct(p_densities, s["pleasure_density"])
        c_pct = rank_pct(conflicts, s["conflict_rate"])
        i_pct = rank_pct(intensities, s["avg_intensity"])
        h_pct = rank_pct(hooks, s.get("avg_hook", 0))
        r2 = s.get("llm_correlation", "-")
        r2_str = f"{r2:.2f}" if isinstance(r2, float) else "-"

        n_short = s["name"][:34]
        logger.info("  %-35s %5d  %4d%%  %4d%%  %4d%%  %4d%%  %6s",
                     n_short, s['total_chaps'], p_pct, c_pct, i_pct, h_pct, r2_str)

        composite = (p_pct + c_pct + i_pct + h_pct) / 4
        pct_scores.append((s["name"], composite))

    pct_scores.sort(key=lambda x: -x[1])
    logger.info("  Top 3 by composite percentile:")
    for i, (name, score) in enumerate(pct_scores[:3]):
        logger.info("    #%d %s: %.0f%%", i+1, name[:40], score)
