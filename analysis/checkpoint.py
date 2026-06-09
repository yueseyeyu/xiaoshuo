#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
checkpoint.py — P0-3: 管线检查点快照 (PlotPilot设计借鉴)
=========================================================
方法: 文件系统 JSON — 每步完成后写 {step}.json, 启动时检查跳过已完步骤.
参考: AI Agent持久化checkpoint模式 / PySpark Pipeline Checkpoint 模式

用法: 由 analyze_all.py 自动调用, 无需手动运行.
"""
import json
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHECKPOINT_DIR = PROJECT_ROOT / "data" / "checkpoints"

# Step order (must match analyze_all.py pipeline)
PIPELINE_STEPS = [
    "book_processor",
    "rhythm_analyzer",
    "rhythm_auditor",
    "genre_synthesizer",
    "score_auditor",
    "quality_gate",
    "creative_bridge",
    "writing_instructions",
]


def _get_checkpoint_path(step_name):
    """Get checkpoint file path for a given step."""
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    return CHECKPOINT_DIR / f"{step_name}.json"


def mark_done(step_name):
    """Mark a pipeline step as completed. Writes timestamp + status."""
    path = _get_checkpoint_path(step_name)
    data = {
        "step": step_name,
        "status": "done",
        "timestamp": datetime.now().isoformat(),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def is_done(step_name):
    """Check if a pipeline step has been completed."""
    path = _get_checkpoint_path(step_name)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data.get("status") == "done"
    except (json.JSONDecodeError, KeyError):
        return False


def get_next_step():
    """Return the first incomplete step, or None if all done."""
    for step in PIPELINE_STEPS:
        if not is_done(step):
            return step
    return None


def reset_all():
    """Clear all checkpoints (for full pipeline re-run)."""
    for step in PIPELINE_STEPS:
        path = _get_checkpoint_path(step)
        if path.exists():
            path.unlink()


def reset_from(step_name):
    """Clear checkpoints from a given step onward (partial re-run)."""
    found = False
    for step in PIPELINE_STEPS:
        if step == step_name:
            found = True
        if found:
            path = _get_checkpoint_path(step)
            if path.exists():
                path.unlink()


def status():
    """Print checkpoint status for all steps."""
    print(f"[CHECKPOINT] {CHECKPOINT_DIR}")
    for step in PIPELINE_STEPS:
        done = is_done(step)
        tag = "[OK]" if done else "[...]"
        print(f"  {tag} {step}")


if __name__ == "__main__":
    import sys
    if "--reset" in sys.argv:
        reset_all()
        print("[CHECKPOINT] All cleared.")
    elif "--status" in sys.argv or len(sys.argv) == 1:
        status()
    else:
        print("Usage: python checkpoint.py [--status|--reset]")
