"""索引 worker 的启动兜底与失败工件持久化。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping

from xiaoshuo.pipeline.index_build_events import (
    _validate_event,
    _validate_report,
    utc_now_iso,
)

EXIT_CODES = {
    "COMPLETED": 0,
    "CANCELLED": 2,
    "RESOURCE_EXCEEDED": 3,
    "PERMISSION_DENIED": 4,
    "MODEL_ERROR": 5,
    "CORPUS_ERROR": 6,
    "CORPUS_CONTRACT_INVALID": 6,
    "CORPUS_EMPTY": 6,
    "INDEX_CORRUPT": 7,
    "WORKER_FAILED": 8,
    "PUBLISH_ROLLBACK_FAILED": 9,
    "REPORT_WRITE_FAILED": 10,
}
ReparseChecker = Callable[[Path], None]


class PersistenceWriteError(OSError):
    """持久化边界统一处理的路径或工件写入异常。"""


def _check_path(path: Path, reject_reparse: ReparseChecker) -> None:
    try:
        reject_reparse(path)
    except Exception as exc:
        raise PersistenceWriteError(f"持久化路径校验失败：{path}") from exc


def _write_json_exclusive(
    target: Path,
    payload: str,
    reject_reparse: ReparseChecker,
) -> None:
    """只创建目标文件；目标在任何时刻存在都拒绝覆盖。"""

    _check_path(target, reject_reparse)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    descriptor = os.open(target, flags)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _check_path(target, reject_reparse)
    finally:
        if descriptor != -1:
            os.close(descriptor)


def _ensure_bootstrap_targets_absent(
    run_dir: Path,
    reject_reparse: ReparseChecker,
) -> tuple[Path, Path, Path]:
    """在 bootstrap 首次写入前确认三个正式工件都不存在。"""

    _check_path(run_dir, reject_reparse)
    targets = tuple(
        run_dir / name for name in ("events.jsonl", "manifest.json", "report.json")
    )
    for target in targets:
        _check_path(target, reject_reparse)
        if target.exists():
            raise PersistenceWriteError(f"bootstrap 工件已存在：{target.name}")
    return targets  # type: ignore[return-value]


def write_bootstrap_report(
    run_dir: Path,
    task_id: str,
    error_code: str,
    message: str,
    *,
    reject_reparse: ReparseChecker,
) -> bool:
    """在 EventWriter 不可用时，以拒绝覆盖方式写入最小失败闭环。"""

    if error_code not in EXIT_CODES:
        error_code = "WORKER_FAILED"
    exit_code = EXIT_CODES[error_code]
    now = utc_now_iso()
    events_path = run_dir / "events.jsonl"
    manifest_path = run_dir / "manifest.json"
    report_path = run_dir / "report.json"
    report = {
        "task_id": task_id,
        "status": "FAILED",
        "error_code": error_code,
        "started_at": now,
        "finished_at": now,
        "duration_seconds": 0.0,
        "n_books": None,
        "n_scenes": None,
        "peak_rss_mb": None,
        "peak_vram_mb": None,
        "manifest_path": manifest_path.as_posix(),
        "events_path": events_path.as_posix(),
        "worker_exit_code": exit_code,
        "cleanup_error": message,
        "original_error_code": None,
        "original_exit_code": None,
        "report_write_error": None,
        "report_recovery_error": None,
    }
    event_records = []
    for phase, event_type in (("preflight", "failed"), ("cleanup", "failed")):
        event_records.append({
            "task_id": task_id,
            "timestamp": now,
            "phase": phase,
            "event_type": event_type,
            "n_done": 0,
            "n_total": 0,
            "progress": None,
            "rss_mb": None,
            "sys_mem_available_gb": None,
            "disk_free_gb": None,
            "gpu_temp": None,
            "gpu_util": None,
            "vram_used_mb": None,
            "message": message,
            "error_code": error_code,
        })
    manifest = {
        "schema_version": 1,
        "task_id": task_id,
        "status": "FAILED",
        "error_code": error_code,
        "events_path": events_path.as_posix(),
    }
    try:
        events_path, manifest_path, report_path = _ensure_bootstrap_targets_absent(
            run_dir, reject_reparse
        )
        for event in event_records:
            _validate_event(event)
        _validate_report(report, task_id, None)
        _write_json_exclusive(
            events_path,
            "".join(
                json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
                for event in event_records
            ),
            reject_reparse,
        )
        _write_json_exclusive(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            reject_reparse,
        )
        _validate_report(report, task_id, run_dir)
        _write_json_exclusive(
            report_path,
            json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            reject_reparse,
        )
        return True
    except (OSError, TypeError, ValueError):
        return False


def write_failure_artifact(
    run_dir: Path,
    payload: Mapping[str, Any],
    expected_task_id: str,
    *,
    reject_reparse: ReparseChecker,
) -> bool:
    """report 双写失败时写入拒绝覆盖的独立结构化诊断工件。"""

    target = run_dir / "failure.json"
    try:
        _check_path(run_dir, reject_reparse)
        _check_path(target, reject_reparse)
        failure = _validate_report(
            payload,
            expected_task_id,
            run_dir,
            require_cleanup_terminal=False,
        )
        _write_json_exclusive(
            target,
            json.dumps(failure, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            reject_reparse,
        )
        return True
    except (OSError, TypeError, ValueError):
        return False
