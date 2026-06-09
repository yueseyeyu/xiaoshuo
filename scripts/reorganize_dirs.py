#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
reorganize_dirs.py -- 目录重构: 统一按题材组织数据
运行: python scripts/reorganize_dirs.py
"""
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENRE = "末世"


def move_file(src, dst):
    """移动文件, 目标目录不存在则创建。"""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        print(f"  [SKIP] 已存在: {dst}")
        return
    shutil.move(str(src), str(dst))
    print(f"  [MOVE] {src} -> {dst}")


def move_dir(src, dst):
    """移动整个目录。"""
    src, dst = Path(src), Path(dst)
    if not src.exists():
        print(f"  [SKIP] 不存在: {src}")
        return
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        if f.is_file():
            move_file(f, dst / f.name)
    # 递归处理子目录
    for d in src.iterdir():
        if d.is_dir():
            move_dir(d, dst / d.name)
    # 删除空源目录
    try:
        src.rmdir()
    except OSError:
        pass


def step1_processed_by_genre():
    """将 data/processed/ 的扁平文件移入 末世/ 子目录。"""
    print("\n=== Step 1: data/processed/ 按题材分组 ===")
    base = ROOT / "data" / "processed"
    target = base / GENRE

    # rhythm CSVs
    rhythm_src = base / "rhythm"
    if rhythm_src.exists():
        move_dir(rhythm_src, target / "rhythm")

    # llm_scores
    scores_src = base / "llm_scores"
    if scores_src.exists():
        move_dir(scores_src, target / "llm_scores")

    # llm_labels
    labels_src = base / "llm_labels"
    if labels_src.exists():
        move_dir(labels_src, target / "llm_labels")

    # manifest + annotation
    for f in ["quality_manifest.json", "annotation_reliability.json"]:
        src = base / f
        if src.exists():
            move_file(src, target / f)


def step2_reports_consolidate():
    """合并 outputs/ + analysis/outputs/ 到 data/reports/"""
    print("\n=== Step 2: 报告合并到 data/reports/ ===")
    reports = ROOT / "data" / "reports"

    # 1. outputs/reports/{genre}/ → data/reports/{genre}/
    src_reports = ROOT / "outputs" / "reports"
    if src_reports.exists():
        # Move genre subdirs (末世/synthesis, 末世/deep_diagnosis)
        for d in src_reports.iterdir():
            if d.is_dir():
                move_dir(d, reports / d.name)
            elif d.is_file():
                move_file(d, reports / d.name)

    # 2. outputs/reports/creative_guidance/ → data/reports/末世/creative_guidance/
    cg_src = ROOT / "outputs" / "reports" / "creative_guidance"
    if cg_src.exists():
        move_dir(cg_src, reports / GENRE / "creative_guidance")

    # 3. analysis/outputs/calibration/ → data/reports/末世/calibration/
    cal_src = ROOT / "analysis" / "outputs" / "calibration"
    if cal_src.exists():
        move_dir(cal_src, reports / GENRE / "calibration")

    # 4. analysis/outputs/reports/creative_guidance/ (older dupes) → merge
    old_cg = ROOT / "analysis" / "outputs" / "reports" / "creative_guidance"
    if old_cg.exists():
        move_dir(old_cg, reports / GENRE / "creative_guidance")

    # 5. analysis/outputs/reports/references/ → data/reports/references/
    ref_src = ROOT / "analysis" / "outputs" / "reports" / "references"
    if ref_src.exists():
        move_dir(ref_src, reports / "references")

    # 6. analysis/outputs/reports/末世/synthesis/ (older files) → merge
    old_synth = ROOT / "analysis" / "outputs" / "reports" / GENRE / "synthesis"
    if old_synth.exists():
        move_dir(old_synth, reports / GENRE / "synthesis")

    # 7. analysis/outputs/reports/末世/deep_diagnosis/ → merge if exists
    old_deep = ROOT / "analysis" / "outputs" / "reports" / GENRE / "deep_diagnosis"
    if old_deep.exists():
        move_dir(old_deep, reports / GENRE / "deep_diagnosis")


def step3_archive_prompts():
    """将 prompts/ 归档到 .archive/prompts/"""
    print("\n=== Step 3: prompts/ 归档 ===")
    src = ROOT / "prompts"
    dst = ROOT / ".archive" / "prompts"
    if src.exists():
        move_dir(src, dst)


def step4_cleanup():
    """清理空目录。"""
    print("\n=== Step 4: 清理空目录 ===")
    empties = [
        ROOT / "analysis" / "outputs",
        ROOT / "outputs" / "reports",
        ROOT / "outputs",
        ROOT / "review",
    ]
    for d in empties:
        if d.exists():
            try:
                # Try to remove empty dirs recursively
                for sub in sorted(d.rglob("*"), reverse=True):
                    if sub.is_dir():
                        try:
                            sub.rmdir()
                            print(f"  [DEL] empty dir: {sub}")
                        except OSError:
                            pass
                d.rmdir()
                print(f"  [DEL] empty dir: {d}")
            except OSError:
                print(f"  [KEEP] not empty: {d}")


def main():
    print(f"Project root: {ROOT}")
    print(f"Genre: {GENRE}")
    print("This script reorganizes directories. Existing files are NEVER overwritten.")

    step1_processed_by_genre()
    step2_reports_consolidate()
    step3_archive_prompts()
    step4_cleanup()

    print("\n[DONE] Reorganization complete.")
    print("  Next: update code paths, then run `python novel.py analyze --genre 末世` to verify.")


if __name__ == "__main__":
    main()
