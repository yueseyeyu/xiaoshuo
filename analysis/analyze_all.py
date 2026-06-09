#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
analyze_all.py — 一键全量分析管线 v5
=====================================
流程: book_processor → rhythm → genre_synthesizer → quality_gate → creative_bridge
     ↑ Step0          ↑ Step1   ↑ Step2              ↑ Step3        ↑ Step4
     (--with-llm 开启 llm_labeler → llm_batch_score 注入LLM增强)

fixes (R3): ① 纳入 llm_labeler + llm_batch_score (--with-llm)
           ② quality_gate 移到 genre_synthesizer 之后，读取真实商业分
           ③ 对应 novel.py CLI `novel analyze`

用法: python analysis/analyze_all.py [--genre 末世] [--skip-gate] [--skip-bridge]
      --with-llm:  启用 LLM标注 + LLM批量评分 (需模型运行,约10min)
      --skip-gate:  跳过品质关卡
      --skip-bridge: 跳过创作指导
"""
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ANALYSIS_DIR = Path(__file__).resolve().parent

# P0-3: Checkpoint support
try:
    from analysis.checkpoint import is_done, mark_done
    CHECKPOINT_AVAILABLE = True
except ImportError:
    CHECKPOINT_AVAILABLE = False


def run_step(name, script, args=None):
    # P0-3: derive checkpoint key from script name (matches checkpoint.py PIPELINE_STEPS)
    ckpt_key = script.replace(".py", "")

    # Checkpoint skip
    if CHECKPOINT_AVAILABLE and is_done(ckpt_key):
        print(f"\n{'='*60}")
        print(f"  [SKIP] {name} (checkpoint: already done)")
        print(f"{'='*60}")
        return True

    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    cmd = [sys.executable, str(ANALYSIS_DIR / script)]
    if args:
        cmd.extend(args)
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT), timeout=3600)
    if result.returncode != 0:
        print(f"[FAIL] {name} exited with code {result.returncode}")
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


def main():
    genre_arg = []
    skip_gate = False
    skip_bridge = False
    with_llm = False
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--genre" and i < len(sys.argv) - 1:
            genre_arg = ["--genre", sys.argv[i + 1]]
        if arg == "--skip-gate":
            skip_gate = True
        if arg == "--skip-bridge":
            skip_bridge = True
        if arg == "--with-llm":
            with_llm = True

    total = 7 if with_llm else 5
    step_n = 0

    # Step 0: Book processor
    step_n += 1
    if not run_step(f"Step {step_n}/{total}: Book Processor", "book_processor.py"):
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
    rhythm_args = genre_arg  # ["--genre", "末世"]
    if not run_step(f"Step {step_n}/{total}: Rhythm Analysis", "rhythm_analyzer.py", rhythm_args):
        return

    # Step 1.5 (optional): LLM batch score — rubric-based chapter scoring
    if with_llm:
        step_n += 1
        batch_args = ["--book", "all"]
        if genre_arg:
            batch_args.extend(genre_arg)
        run_optional(f"Step {step_n}/{total}: LLM Batch Score", "llm_batch_score.py", batch_args)

    # Step 2: Genre synthesis FIRST (so quality_gate can read real scores)
    step_n += 1
    if not run_step(f"Step {step_n}/{total}: Genre Synthesis", "genre_synthesizer.py", genre_arg):
        return

    # Step 3: Quality gate AFTER synthesis (reads real commercial scores, not proxy)
    if not skip_gate:
        step_n += 1
        gate_args = genre_arg if genre_arg else []  # ["--genre", "末世"] or []
        if not run_step(f"Step {step_n}/{total}: Quality Gate", "quality_gate.py", gate_args):
            print("[WARN] Quality gate failed but pipeline continues")
    else:
        print(f"\n[SKIP] Quality gate skipped (--skip-gate)")

    # Step 4: Creative bridge
    if not skip_bridge:
        step_n += 1
        if not run_step(f"Step {step_n}/{total}: Creative Bridge", "creative_bridge.py", genre_arg):
            print("[WARN] Creative bridge failed but pipeline continues")
    else:
        print(f"\n[SKIP] Creative bridge skipped (--skip-bridge)")

    print(f"\n[DONE] Full pipeline complete ({'LLM enhanced' if with_llm else 'rule-only'}).")
    print(f"  Reports:     outputs/reports/")
    print(f"  Guidance:    outputs/reports/creative_guidance/")
    print(f"  Manifest:    data/processed/quality_manifest.json")
    print(f"  Review:      books/review/ (退回审查的书)")
    if not with_llm:
        print(f"\n  Tip: --with-llm 启用 LLM 增强分析 (评分更精准,需约 10min)")


if __name__ == "__main__":
    main()
