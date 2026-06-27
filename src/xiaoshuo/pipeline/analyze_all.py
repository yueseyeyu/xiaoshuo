#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
analyze_all.py -- 一键全量分析管线 v7
=====================================
v7: 并发阶段执行 (ThreadPoolExecutor) + PipelineTimer 计时

流程: book_processor (1)
       → parallel: rhythm_analyzer (2) | llm_batch_score (3) | recursive_summarize (6)
       → sequential: genre_synthesizer (4) → quality_gate (5) → creative_bridge (7)
                     → cross_book_synthesis (8) → writing_instructions (9)

用法: python analyze_all.py [--genre 末世] [--skip-gate] [--skip-bridge]
      --with-llm:     启用 LLM标注 + LLM批量评分 (需模型运行,约10min)
      --parallel:     并发执行 (默认)
      --sequential:   强制顺序执行 (旧行为)
      --skip-gate:    跳过品质关卡
      --skip-bridge:  跳过创作指导
"""
import argparse
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from xiaoshuo import PROJECT_ROOT
from xiaoshuo.infra import HardwareGuardian
from xiaoshuo.infra.logging_config import get_logger
from xiaoshuo.infra.performance import PipelineTimer
from xiaoshuo.infra.pipeline_state import clear_stage, mark_error, write_stage

# PROJECT_ROOT imported from src.xiaoshuo
ANALYSIS_DIR = Path(__file__).resolve().parent

logger = get_logger("pipeline.analyze_all")

# P0-3: Checkpoint support (v8.0 path fix)
try:
    from xiaoshuo.pipeline.checkpoint import is_done, mark_done
    CHECKPOINT_AVAILABLE = True
except ImportError:
    CHECKPOINT_AVAILABLE = False

# P3: Stage key -> (stage_num, total, display_name)
# Total is the number of major stages shown in the frontend progress bar.
STAGE_INFO = {
    "book_processor": (1, 9, "入库处理"),
    "rhythm_analyzer": (2, 9, "拆书节奏分析"),
    "llm_batch_score": (3, 9, "LLM批量评分"),
    "genre_synthesizer": (3, 9, "题材评分合成"),
    "quality_gate": (4, 9, "品质关卡"),
    "creative_bridge": (5, 9, "创作桥接"),
    "recursive_summarize": (6, 9, "递归摘要"),
    "cross_book_synthesis": (7, 9, "跨书合成"),
    "technique_store": (8, 9, "技法卡片"),
    "writing_instructions": (9, 9, "写作指令"),
}


def run_step(name, script, args=None, timer=None):
    """Run a single pipeline step. Returns True on success.

    timer: optional PipelineTimer instance for stage-level timing.
    """
    # P0-3: derive checkpoint key from script name (matches checkpoint.py PIPELINE_STEPS)
    ckpt_key = script.replace(".py", "")
    stage_num, total, _ = STAGE_INFO.get(ckpt_key, (0, 0, ckpt_key))

    # Checkpoint skip
    if CHECKPOINT_AVAILABLE and is_done(ckpt_key):
        print(f"\n{'='*60}")
        print(f"  [SKIP] {name} (checkpoint: already done)")
        print(f"{'='*60}")
        if timer is not None:
            timer.start()
            timer.stop()
        return True

    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")

    # P3: Write current stage for frontend progress display
    write_stage(
        stage=ckpt_key,
        stage_num=stage_num,
        total=total,
        percent=0,
        current_task=f"启动 {name}",
    )

    if timer is not None:
        timer.start()

    cmd = [sys.executable, str(ANALYSIS_DIR / script)]
    if args:
        cmd.extend(args)

    try:
        result = subprocess.run(cmd, cwd=str(PROJECT_ROOT), timeout=3600)
    except subprocess.TimeoutExpired as e:
        msg = f"{name} 执行超时 (3600s)"
        print(f"[FAIL] {msg}")
        logger.error(msg)
        mark_error(ckpt_key, msg, stage_num=stage_num, total=total)
        if timer is not None:
            timer.stop()
        return False
    except Exception as e:
        msg = f"{name} 执行异常: {e}"
        print(f"[FAIL] {msg}")
        logger.exception("Step %s failed", name)
        mark_error(ckpt_key, str(e), stage_num=stage_num, total=total)
        if timer is not None:
            timer.stop()
        return False

    if timer is not None:
        timer.stop()

    if result.returncode != 0:
        msg = f"{name} 退出码 {result.returncode}"
        print(f"[FAIL] {msg}")
        logger.error(msg)
        mark_error(ckpt_key, msg, stage_num=stage_num, total=total)
        return False

    # Mark step done on success
    if CHECKPOINT_AVAILABLE:
        mark_done(ckpt_key)
    return True


def run_optional(name, script, args=None):
    """Run a step that may fail without blocking the pipeline."""
    ok = run_step(name, script, args)
    if not ok:
        print(f"[WARN] {script} failed, continuing (non-blocking)")
    return ok


def _run_parallel_group(steps):
    """Run multiple steps in parallel using ThreadPoolExecutor.

    steps: list of (name, script, args) tuples
    Returns: True if all steps succeeded, False otherwise.

    Each step gets its own PipelineTimer and checkpoint file.
    """
    if not steps:
        return True

    all_ok = True
    with ThreadPoolExecutor(max_workers=len(steps)) as executor:
        futures = {}
        for name, script, args in steps:
            timer = PipelineTimer(name)
            future = executor.submit(run_step, name, script, args, timer)
            futures[future] = name

        for future in as_completed(futures):
            name = futures[future]
            try:
                result = future.result()
                if not result:
                    logger.warning("[WARN] %s failed in parallel group", name)
                    all_ok = False
            except Exception as e:
                logger.error("[FAIL] %s raised exception: %s", name, e)
                all_ok = False

    return all_ok


def _run_technique_store(genre):
    """Run technique card extraction (in-process, no subprocess)."""
    try:
        from xiaoshuo.pipeline.technique_store import process_genre
        ckpt_key = "technique_store"
        stage_num, total, name = STAGE_INFO.get(ckpt_key, (9, 9, "技法卡片"))
        write_stage(stage=ckpt_key, stage_num=stage_num, total=total, percent=0,
                    current_task=f"提取{genre}技法卡片")
        count = process_genre(genre)
        if CHECKPOINT_AVAILABLE:
            mark_done(ckpt_key)
        msg = f"技法卡片提取完成: {count} 条"
        print(f"[OK] {msg}")
        logger.info(msg)
        return True
    except Exception as e:
        msg = f"技法卡片提取失败: {e}"
        print(f"[FAIL] {msg}")
        logger.exception("technique_store failed")
        return False


def _run_parallel(genre_arg, books_arg, skip_gate, skip_bridge, with_llm):
    """v7: 并发管线执行。

    Group 1: book_processor [+ optional llm_labeler]
    Group 2 (parallel): rhythm_analyzer | llm_batch_score | recursive_summarize
    Group 3 (sequential): rhythm_auditor → genre_synthesizer → score_auditor
                          → quality_gate → creative_bridge
                          → cross_book_synthesis → writing_instructions
    """
    # ── Group 1: book_processor (stage 1) ──
    bp_args = books_arg if books_arg else []
    if not run_step("Stage 1/9: Book Processor", "book_processor.py", bp_args,
                    timer=PipelineTimer("book_processor")):
        logger.warning("book_processor failed, continuing with existing novels/")

    # Optional: llm_labeler (runs before parallel group, after book_processor)
    if with_llm:
        labeler_args = ["--book=all", "--sample-rate=0.1"]
        if genre_arg:
            labeler_args.append(f"--genre={genre_arg[1]}")
        run_optional("LLM Labeler (regex校准)", "llm_labeler.py", labeler_args)

    # ── Group 2: Parallel execution ──
    parallel_steps = []

    # Stage 2: rhythm_analyzer
    ra_args = genre_arg + books_arg if genre_arg else books_arg
    parallel_steps.append(("Stage 2/9: Rhythm Analyzer", "rhythm_analyzer.py", ra_args if ra_args else None))

    # Stage 3: llm_batch_score (only with --with-llm)
    if with_llm:
        batch_args = ["--book", "all"]
        if genre_arg:
            batch_args.extend(genre_arg)
        parallel_steps.append(("Stage 3/9: LLM Batch Score", "llm_batch_score.py", batch_args))

    # Stage 6: recursive_summarize
    rs_args = genre_arg + books_arg if genre_arg else books_arg
    parallel_steps.append(("Stage 6/9: Recursive Summarize", "recursive_summarize.py",
                           rs_args if rs_args else None))

    logger.info("Starting parallel group: %d stages", len(parallel_steps))
    _run_parallel_group(parallel_steps)

    # ── Group 3: Sequential execution ──
    # Optional: rhythm_auditor (after rhythm_analyzer, before genre_synthesizer)
    audit_args = genre_arg if genre_arg else []
    run_optional("Rhythm Audit (拆书数据质检)", "rhythm_auditor.py", audit_args)

    # Stage 4: genre_synthesizer
    gs_args = genre_arg + books_arg if genre_arg else books_arg
    if not run_step("Stage 4/9: Genre Synthesizer", "genre_synthesizer.py", gs_args,
                    timer=PipelineTimer("genre_synthesizer")):
        logger.error("genre_synthesizer failed, aborting")
        return

    # Optional: score_auditor (after genre_synthesizer, before quality_gate)
    score_audit_args = genre_arg if genre_arg else []
    run_optional("Score Audit (商业评分质检)", "score_auditor.py", score_audit_args)

    # Stage 5: quality_gate
    if not skip_gate:
        gate_args = genre_arg if genre_arg else []
        if not run_step("Stage 5/9: Quality Gate", "quality_gate.py", gate_args,
                        timer=PipelineTimer("quality_gate")):
            logger.warning("Quality gate failed but pipeline continues")
    else:
        print(f"\n[SKIP] Quality gate skipped (--skip-gate)")

    # Stage 7: creative_bridge
    if not skip_bridge:
        if not run_step("Stage 7/9: Creative Bridge", "creative_bridge.py", genre_arg,
                        timer=PipelineTimer("creative_bridge")):
            logger.warning("Creative bridge failed but pipeline continues")
    else:
        print(f"\n[SKIP] Creative bridge skipped (--skip-bridge)")

    # Stage 8: cross_book_synthesis
    run_optional("Stage 8/9: Cross-Book Synthesis", "cross_book_synthesis.py",
                 genre_arg if genre_arg else None)

    # Stage 9: technique_store (auto-extract technique cards from synthesis)
    gen = genre_arg[1] if genre_arg else "末世"
    _run_technique_store(gen)

    # Stage 9: writing_instructions
    wi_args = books_arg if books_arg else []
    run_optional("Stage 9/9: Writing Instructions", "writing_instructions.py", wi_args)

    clear_stage()
    print(f"\n[DONE] Full pipeline complete ({'LLM enhanced' if with_llm else 'rule-only'}).")
    print(f"  Reports:     data/reports/")
    print(f"  Guidance:    data/reports/{{genre}}/creative_guidance/")
    print(f"  Manifest:    data/processed/{{genre}}/quality/quality_manifest.json")
    print(f"  Review:      books/review/ (退回审查的书)")
    if not with_llm:
        print(f"\n  Tip: --with-llm 启用 LLM 增强分析 (评分更精准,需约 10min)")


def _run_sequential(genre_arg, books_arg, skip_gate, skip_bridge, with_llm):
    """v6: 原有顺序管线 (--sequential fallback).

    Preserves the original 7-step (or 9-step with --with-llm) sequential flow
    with PipelineTimer added for each major stage.
    """
    total = 9 if with_llm else 7
    step_n = 0

    # Step 0: Book processor
    step_n += 1
    bp_args = books_arg if books_arg else []
    if not run_step(f"Step {step_n}/{total}: Book Processor", "book_processor.py", bp_args,
                    timer=PipelineTimer("book_processor")):
        print("[WARN] book_processor failed, continuing with existing novels/")

    # Step 0.5 (optional): LLM labeler — verify regex annotations
    if with_llm:
        step_n += 1
        labeler_args = ["--book=all", "--sample-rate=0.1"]
        if genre_arg:
            labeler_args.append(f"--genre={genre_arg[1]}")
        run_optional(f"Step {step_n}/{total}: LLM Labeler (regex校准)", "llm_labeler.py", labeler_args)

    # Step 1: Rhythm analysis
    step_n += 1
    rhythm_args = genre_arg + books_arg if genre_arg else books_arg
    if not run_step(f"Step {step_n}/{total}: Rhythm Analysis", "rhythm_analyzer.py", rhythm_args if rhythm_args else None,
                    timer=PipelineTimer("rhythm_analyzer")):
        return

    # Step 1.5: Rhythm data audit (quality check on split data)
    step_n += 1
    audit_args = genre_arg if genre_arg else []
    run_optional(f"Step {step_n}/{total}: Rhythm Audit (拆书数据质检)", "rhythm_auditor.py", audit_args)

    # Step 1.5 (optional): LLM batch score — rubric-based chapter scoring
    if with_llm:
        step_n += 1
        batch_args = ["--book", "all"]
        if genre_arg:
            batch_args.extend(genre_arg)
        run_optional(f"Step {step_n}/{total}: LLM Batch Score", "llm_batch_score.py", batch_args)

    # Step 2: Genre synthesis FIRST (so quality_gate can read real scores)
    step_n += 1
    gs_args = genre_arg + books_arg if genre_arg else books_arg
    if not run_step(f"Step {step_n}/{total}: Genre Synthesis", "genre_synthesizer.py", gs_args if gs_args else None,
                    timer=PipelineTimer("genre_synthesizer")):
        return

    # Step 2.5: Score audit (quality check on commercial scores + Borda ranking)
    step_n += 1
    score_audit_args = genre_arg if genre_arg else []
    run_optional(f"Step {step_n}/{total}: Score Audit (商业评分质检)", "score_auditor.py", score_audit_args)

    # Step 3: Quality gate AFTER synthesis (reads real commercial scores, not proxy)
    if not skip_gate:
        step_n += 1
        gate_args = genre_arg if genre_arg else []  # ["--genre", "末世"] or []
        if not run_step(f"Step {step_n}/{total}: Quality Gate", "quality_gate.py", gate_args,
                        timer=PipelineTimer("quality_gate")):
            print("[WARN] Quality gate failed but pipeline continues")
    else:
        print(f"\n[SKIP] Quality gate skipped (--skip-gate)")

    # Step 4: Creative bridge
    if not skip_bridge:
        step_n += 1
        if not run_step(f"Step {step_n}/{total}: Creative Bridge", "creative_bridge.py", genre_arg,
                        timer=PipelineTimer("creative_bridge")):
            print("[WARN] Creative bridge failed but pipeline continues")
    else:
        print(f"\n[SKIP] Creative bridge skipped (--skip-bridge)")

    clear_stage()
    print(f"\n[DONE] Full pipeline complete ({'LLM enhanced' if with_llm else 'rule-only'}).")
    print(f"  Reports:     data/reports/")
    print(f"  Guidance:    data/reports/{{genre}}/creative_guidance/")
    print(f"  Manifest:    data/processed/{{genre}}/quality/quality_manifest.json")
    print(f"  Review:      books/review/ (退回审查的书)")
    if not with_llm:
        print(f"\n  Tip: --with-llm 启用 LLM 增强分析 (评分更精准,需约 10min)")


def main():
    parser = argparse.ArgumentParser(
        description="一键全量分析管线 v7 — 并发阶段执行 + 管线计时"
    )
    parser.add_argument("--genre", type=str, default=None, help="题材过滤")
    parser.add_argument("--books", type=str, default=None,
                        help="选中书籍列表（逗号分隔，如 'book1,book2'）")
    parser.add_argument("--skip-gate", action="store_true", help="跳过品质关卡")
    parser.add_argument("--skip-bridge", action="store_true", help="跳过创作指导")
    parser.add_argument("--with-llm", action="store_true", help="启用 LLM 增强分析")
    parser.add_argument("--parallel", action="store_true", default=True,
                        help="并发执行 (默认)")
    parser.add_argument("--sequential", action="store_true",
                        help="强制顺序执行 (旧行为)")
    args = parser.parse_args()

    use_parallel = args.parallel and not args.sequential

    genre_arg = ["--genre", args.genre] if args.genre else []
    books_arg = ["--books", args.books] if args.books else []
    skip_gate = args.skip_gate
    skip_bridge = args.skip_bridge
    with_llm = args.with_llm

    logger.info("Pipeline starting: parallel=%s, with_llm=%s, genre=%s, books=%s",
                use_parallel, with_llm, args.genre or "all", args.books or "all")
    PipelineTimer.reset()

    if use_parallel:
        _run_parallel(genre_arg, books_arg, skip_gate, skip_bridge, with_llm)
    else:
        _run_sequential(genre_arg, books_arg, skip_gate, skip_bridge, with_llm)

    PipelineTimer.report()
    logger.info("Pipeline complete.")


if __name__ == "__main__":
    guardian = HardwareGuardian(
        on_warn=lambda temp: print(f"[WARN] GPU temp {temp}C >= 82C, consider pausing"),
        on_stop=lambda msg: print(f"[CRITICAL] {msg}, emergency stop"),
        on_fan_alert=lambda speed: print(f"[CRITICAL] GPU fan {speed}% < 5%, check fan"),
    )
    with guardian:
        main()