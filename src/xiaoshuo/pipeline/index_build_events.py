"""MPV-02B 索引构建事件与回执合同。"""

from __future__ import annotations

import json
import math
import msvcrt
import os
import re
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

EVENT_PHASES = frozenset({
    "preflight", "collect", "tokenize", "encode", "publish", "cleanup",
})
EVENT_TYPES = frozenset({
    "started", "progress", "warning", "cancelled", "failed", "completed",
})
TERMINAL_EVENT_TYPES = frozenset({"cancelled", "failed", "completed"})
EVENT_STAGE_ROOT = Path(r"D:\tmp\yeyu-ai-a3\mpv-02b-worker")
RUN_ID_RE = re.compile(r"^\d{8}-\d{6}-\d{6}$")
REPORT_STATUSES = frozenset({"COMPLETED", "FAILED", "CANCELLED"})
REPORT_EXIT_CODES = frozenset({0, 2, 3, 4, 5, 6, 7, 8, 9, 10})
REPORT_ERROR_EXIT_CODES = {
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
REPORT_FAILED_ERROR_CODES = frozenset(REPORT_ERROR_EXIT_CODES) - frozenset({
    "COMPLETED", "CANCELLED",
})
MANIFEST_SCHEMA_VERSION = 1
EVENT_FSYNC_EVERY = 8
EVENT_FIELDS = (
    "task_id", "timestamp", "phase", "event_type", "n_done", "n_total",
    "progress", "rss_mb", "sys_mem_available_gb", "disk_free_gb", "gpu_temp",
    "gpu_util", "vram_used_mb", "message", "error_code",
)
REPORT_FIELDS = (
    "task_id", "status", "error_code", "started_at", "finished_at",
    "duration_seconds", "n_books", "n_scenes", "peak_rss_mb", "peak_vram_mb",
    "manifest_path", "events_path", "worker_exit_code", "cleanup_error",
    "original_error_code", "original_exit_code", "report_write_error",
    "report_recovery_error",
)


class EventContractError(ValueError):
    """事件或回执不符合固定合同。"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_utc_iso(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed)


def _reject_reparse(path: Path) -> None:
    current = path.absolute()
    while True:
        try:
            if current.is_symlink():
                raise EventContractError(f"路径包含符号链接：{current}")
            try:
                attrs = getattr(current.stat(follow_symlinks=False), "st_file_attributes", 0)
            except TypeError:  # pragma: no cover - 旧版 Python 回退
                attrs = getattr(os.lstat(current), "st_file_attributes", 0)
            if attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
                raise EventContractError(f"路径包含 reparse point：{current}")
        except FileNotFoundError:
            pass
        parent = current.parent
        if parent == current:
            return
        current = parent


def _contained_file(path: Path, run_dir: Path, name: str) -> Path:
    path = path.absolute()
    run_dir = run_dir.absolute()
    if path.name != name or path.parent != run_dir:
        raise EventContractError(f"工件不在当前任务目录：{path}")
    _reject_reparse(run_dir)
    _reject_reparse(path)
    return path


def _validate_run_dir(run_dir: Path) -> Path:
    run_dir = run_dir.absolute()
    if run_dir.drive.upper() != "D:":
        raise EventContractError("worker run 目录必须位于 D 盘")
    try:
        relative = run_dir.relative_to(EVENT_STAGE_ROOT.absolute())
    except ValueError as exc:
        raise EventContractError("worker run 目录越出批准 stage") from exc
    if len(relative.parts) != 1 or not RUN_ID_RE.fullmatch(relative.name):
        raise EventContractError("worker run-id 无效")
    _reject_reparse(EVENT_STAGE_ROOT)
    _reject_reparse(run_dir)
    if not run_dir.is_dir():
        raise EventContractError("worker run 目录不存在")
    return run_dir


def _strict_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _strict_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_run_artifact_path(
    value: Any, run_dir: Path, field_name: str, file_name: str
) -> None:
    if not isinstance(value, str) or not value:
        raise EventContractError(f"report {field_name} 无效")
    expected = os.path.normcase(os.path.abspath(os.fspath(run_dir / file_name)))
    actual = os.path.normcase(os.path.abspath(value))
    if actual != expected:
        raise EventContractError(f"report {field_name} 必须绑定当前 run")
    _reject_reparse(run_dir)
    _reject_reparse(Path(value))


def _validate_report(
    report: Mapping[str, Any],
    task_id: str | None = None,
    run_dir: Path | None = None,
    *,
    require_cleanup_terminal: bool = True,
) -> dict[str, Any]:
    if not isinstance(report, Mapping):
        raise EventContractError("report 根节点必须是对象")
    if set(report) != set(REPORT_FIELDS):
        raise EventContractError("report 字段集合不匹配")
    if not isinstance(report["task_id"], str) or not report["task_id"]:
        raise EventContractError("report task_id 无效")
    if task_id is not None and report["task_id"] != task_id:
        raise EventContractError("report task_id 不匹配")
    if report["status"] not in REPORT_STATUSES:
        raise EventContractError("report status 无效")
    if not _strict_int(report["worker_exit_code"]) or report["worker_exit_code"] not in REPORT_EXIT_CODES:
        raise EventContractError("report worker_exit_code 无效")
    if report["status"] == "COMPLETED" and (
        report["worker_exit_code"] != 0 or report["error_code"] is not None
    ):
        raise EventContractError("COMPLETED report 的退出码或错误码不一致")
    if report["status"] == "CANCELLED" and (
        report["worker_exit_code"] != 2 or report["error_code"] != "CANCELLED"
    ):
        raise EventContractError("CANCELLED report 的退出码或错误码不一致")
    if report["status"] == "FAILED":
        error_code = report["error_code"]
        if error_code not in REPORT_FAILED_ERROR_CODES:
            raise EventContractError("FAILED report 的错误码无效")
        if report["worker_exit_code"] != REPORT_ERROR_EXIT_CODES[error_code]:
            raise EventContractError("FAILED report 的退出码或错误码不一致")
        if error_code == "REPORT_WRITE_FAILED":
            if not isinstance(report["original_error_code"], str):
                raise EventContractError("REPORT_WRITE_FAILED 缺少 original_error_code")
            if report["original_error_code"] not in REPORT_ERROR_EXIT_CODES:
                raise EventContractError("REPORT_WRITE_FAILED 原始错误码无效")
            if report["original_exit_code"] != REPORT_ERROR_EXIT_CODES[report["original_error_code"]]:
                raise EventContractError("REPORT_WRITE_FAILED 原始退出码不一致")
            if not isinstance(report["report_write_error"], str) or not report["report_write_error"]:
                raise EventContractError("REPORT_WRITE_FAILED 缺少 report_write_error")
            recovery_error = report["report_recovery_error"]
            if recovery_error is not None and (
                not isinstance(recovery_error, str) or not recovery_error
            ):
                raise EventContractError("REPORT_WRITE_FAILED 的 report_recovery_error 无效")
    if report["status"] == "COMPLETED" and report["cleanup_error"] is not None:
        raise EventContractError("COMPLETED report 不得包含 cleanup_error")
    for field in ("n_books", "n_scenes"):
        value = report[field]
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            raise EventContractError(f"report {field} 无效")
    if not _strict_number(report["duration_seconds"]) or report["duration_seconds"] < 0:
        raise EventContractError("report duration_seconds 无效")
    for field in ("peak_rss_mb", "peak_vram_mb"):
        value = report[field]
        if value is not None and (not _strict_number(value) or value < 0):
            raise EventContractError(f"report {field} 无效")
    for field in ("started_at", "finished_at"):
        if not _is_utc_iso(report[field]):
            raise EventContractError(f"report {field} 必须是 UTC ISO-8601")
    if not isinstance(report["manifest_path"], str) or not report["manifest_path"]:
        raise EventContractError("report manifest_path 无效")
    if report["cleanup_error"] is not None and not isinstance(report["cleanup_error"], str):
        raise EventContractError("report cleanup_error 无效")
    if report["original_error_code"] is not None and not isinstance(report["original_error_code"], str):
        raise EventContractError("report original_error_code 无效")
    if report["original_exit_code"] is not None and (
        not _strict_int(report["original_exit_code"])
        or report["original_exit_code"] not in REPORT_EXIT_CODES
    ):
        raise EventContractError("report original_exit_code 无效")
    for field in ("report_write_error", "report_recovery_error"):
        if report[field] is not None and not isinstance(report[field], str):
            raise EventContractError(f"report {field} 无效")
    if report["status"] == "COMPLETED" and any(
        report[field] is not None
        for field in ("original_error_code", "original_exit_code", "report_write_error", "report_recovery_error")
    ):
        raise EventContractError("COMPLETED report 不得包含失败恢复元数据")
    if run_dir is not None:
        _validate_run_artifact_path(report["events_path"], run_dir, "events_path", "events.jsonl")
        _validate_run_artifact_path(report["manifest_path"], run_dir, "manifest_path", "manifest.json")
        manifest_path = Path(report["manifest_path"])
        cleanup_contract_valid = False
        events_path = Path(report["events_path"])
        if events_path.is_file() and report["error_code"] == "REPORT_WRITE_FAILED":
            try:
                _validate_cleanup_event_contract(events_path, report["task_id"], report)
                cleanup_contract_valid = True
            except EventContractError:
                if require_cleanup_terminal:
                    raise
        if not manifest_path.is_file():
            if require_cleanup_terminal:
                raise EventContractError("report manifest.json 不存在")
        else:
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise EventContractError("report manifest.json 无法读取") from exc
            manifest = _validate_manifest(manifest, report["task_id"], run_dir)
            if report["error_code"] == "REPORT_WRITE_FAILED":
                expected_original_error = (
                    "COMPLETED" if manifest["status"] == "COMPLETED"
                    else "CANCELLED" if manifest["status"] == "CANCELLED"
                    else manifest["error_code"]
                )
                stale_manifest_allowed = (
                    not require_cleanup_terminal
                    and not cleanup_contract_valid
                    and isinstance(report["report_write_error"], str)
                    and bool(report["report_write_error"].strip())
                )
                if report["original_error_code"] != expected_original_error and not stale_manifest_allowed:
                    raise EventContractError("REPORT_WRITE_FAILED 的 manifest 原始结果不一致")
            else:
                if manifest["status"] != report["status"]:
                    raise EventContractError("report 与 manifest status 不一致")
                if manifest.get("error_code") != report["error_code"]:
                    raise EventContractError("report 与 manifest error_code 不一致")
        if require_cleanup_terminal and not cleanup_contract_valid:
            _validate_cleanup_event_contract(events_path, report["task_id"], report)
    elif not isinstance(report["events_path"], str) or not report["events_path"]:
        raise EventContractError("report events_path 无效")
    return dict(report)


def _validate_manifest(
    manifest: Mapping[str, Any],
    task_id: str | None = None,
    run_dir: Path | None = None,
) -> dict[str, Any]:
    if not isinstance(manifest, Mapping):
        raise EventContractError("manifest 根节点必须是对象")
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise EventContractError("manifest schema_version 无效")
    manifest_task_id = manifest.get("task_id")
    if not isinstance(manifest_task_id, str) or not manifest_task_id:
        raise EventContractError("manifest task_id 无效")
    if task_id is not None and manifest_task_id != task_id:
        raise EventContractError("manifest task_id 不匹配")
    if manifest.get("status") not in REPORT_STATUSES:
        raise EventContractError("manifest status 无效")
    manifest_error_code = manifest.get("error_code")
    if "error_code" not in manifest:
        raise EventContractError("manifest 缺少 error_code")
    if manifest["status"] == "COMPLETED":
        if manifest_error_code is not None:
            raise EventContractError("COMPLETED manifest 的 error_code 必须为空")
    elif manifest["status"] == "CANCELLED":
        if manifest_error_code != "CANCELLED":
            raise EventContractError("CANCELLED manifest 的 error_code 无效")
    elif manifest_error_code not in REPORT_FAILED_ERROR_CODES:
        raise EventContractError("FAILED manifest 的 error_code 无效")
    events_path = manifest.get("events_path")
    if not isinstance(events_path, str) or not events_path:
        raise EventContractError("manifest events_path 无效")
    if run_dir is not None:
        _validate_run_artifact_path(events_path, run_dir, "events_path", "events.jsonl")
        events_file = Path(events_path)
        if not events_file.is_file():
            raise EventContractError("manifest events.jsonl 不存在")
        try:
            events_file.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise EventContractError("manifest events.jsonl 无法读取") from exc
    return dict(manifest)


def _validate_event(event: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(event, Mapping):
        raise EventContractError("事件根节点必须是对象")
    if set(event) != set(EVENT_FIELDS):
        raise EventContractError("事件字段集合不匹配")
    if not isinstance(event["task_id"], str) or not event["task_id"]:
        raise EventContractError("事件 task_id 无效")
    if event["phase"] not in EVENT_PHASES or event["event_type"] not in EVENT_TYPES:
        raise EventContractError("事件 phase 或 event_type 无效")
    for field in ("n_done", "n_total"):
        if not isinstance(event[field], int) or isinstance(event[field], bool) or event[field] < 0:
            raise EventContractError(f"事件 {field} 无效")
    progress = event["progress"]
    if progress is not None and (not _strict_number(progress) or not 0 <= progress <= 1):
        raise EventContractError("事件 progress 无效")
    for field in (
        "rss_mb", "sys_mem_available_gb", "disk_free_gb", "gpu_temp",
        "gpu_util", "vram_used_mb",
    ):
        if event[field] is not None and not _strict_number(event[field]):
            raise EventContractError(f"事件 {field} 无效")
    if not _is_utc_iso(event["timestamp"]) or not isinstance(event["message"], str):
        raise EventContractError("事件 timestamp/message 无效")
    if event["error_code"] is not None and not isinstance(event["error_code"], str):
        raise EventContractError("事件 error_code 无效")
    return dict(event)


def _read_events_records(path: Path, expected_task_id: str) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise EventContractError("events.jsonl 无法读取") from exc
    events: list[dict[str, Any]] = []
    for line_no, line in enumerate(lines, start=1):
        try:
            event = _validate_event(json.loads(line))
        except (json.JSONDecodeError, EventContractError) as exc:
            raise EventContractError(f"events.jsonl 第 {line_no} 行无效") from exc
        if event["task_id"] != expected_task_id:
            raise EventContractError("事件 task_id 不匹配")
        events.append(event)
    return events


def _validate_cleanup_event_contract(
    events_path: Path, task_id: str, report: Mapping[str, Any]
) -> None:
    events = _read_events_records(events_path, task_id)
    cleanup_events = [event for event in events if event["phase"] == "cleanup"]
    terminal_events = [
        event for event in cleanup_events if event["event_type"] in TERMINAL_EVENT_TYPES
    ]
    if len(terminal_events) != 1 or terminal_events[0] is not events[-1]:
        raise EventContractError("cleanup 终态事件数量或顺序无效")
    expected_status = report["status"]
    if report["error_code"] == "REPORT_WRITE_FAILED":
        expected_status = {
            "COMPLETED": "COMPLETED",
            "CANCELLED": "CANCELLED",
        }.get(report["original_error_code"], "FAILED")
    expected_type = {
        "COMPLETED": "completed",
        "CANCELLED": "cancelled",
        "FAILED": "failed",
    }[expected_status]
    if terminal_events[0]["event_type"] != expected_type:
        raise EventContractError("cleanup 终态事件与 report status 不一致")
    expected_error_code = {
        "COMPLETED": None,
        "CANCELLED": "CANCELLED",
        "FAILED": (
            report["original_error_code"]
            if report["error_code"] == "REPORT_WRITE_FAILED"
            else report["error_code"]
        ),
    }[expected_status]
    if terminal_events[0]["error_code"] != expected_error_code:
        raise EventContractError("cleanup 终态事件 error_code 与 report 原始结果不一致")


class EventWriter:
    """向单一 run 目录原子写入完整事件日志和最终 report。"""

    def __init__(self, run_dir: Path, task_id: str):
        self.run_dir = _validate_run_dir(run_dir)
        self.task_id = task_id
        self.events_path = _contained_file(self.run_dir / "events.jsonl", self.run_dir, "events.jsonl")
        self.report_path = _contained_file(self.run_dir / "report.json", self.run_dir, "report.json")
        self.manifest_path = _contained_file(self.run_dir / "manifest.json", self.run_dir, "manifest.json")
        self.lock_path = _contained_file(self.run_dir / "events.lock", self.run_dir, "events.lock")
        self._lock_handle = self._acquire_writer_lease()
        self._terminal_written = False
        self._event_count = 0
        try:
            if self.events_path.is_file():
                records = _read_events_records(self.events_path, self.task_id)
                terminal_indexes = [
                    index
                    for index, event in enumerate(records)
                    if event["phase"] == "cleanup"
                    and event["event_type"] in TERMINAL_EVENT_TYPES
                ]
                if terminal_indexes and (
                    len(terminal_indexes) != 1
                    or terminal_indexes[0] != len(records) - 1
                ):
                    raise EventContractError("历史事件中的 cleanup 终态非法或未封口")
                self._terminal_written = bool(terminal_indexes)
                self._event_count = len(records)
        except BaseException:
            self.close()
            raise

    def _acquire_writer_lease(self):
        _reject_reparse(self.run_dir)
        _reject_reparse(self.lock_path)
        handle = self.lock_path.open("a+b")
        try:
            handle.seek(0)
            handle.write(b"0")
            handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except (OSError, PermissionError):
            handle.close()
            raise EventContractError("当前 run 已被其他 EventWriter 占用")
        return handle

    def close(self) -> None:
        handle = self._lock_handle
        if handle is None:
            return
        self._lock_handle = None
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        handle.close()

    def __del__(self):  # pragma: no cover - 解释器回收路径
        try:
            self.close()
        except Exception:
            pass

    def validate_events(self) -> list[dict[str, Any]]:
        """在收尾阶段一次性完整校验当前事件日志。"""

        if not self.events_path.is_file():
            raise EventContractError("events.jsonl 不存在")
        records = _read_events_records(self.events_path, self.task_id)
        self._event_count = len(records)
        return records

    def write_event(
        self,
        phase: str,
        event_type: str,
        *,
        n_done: int = 0,
        n_total: int = 0,
        message: str = "",
        error_code: str | None = None,
        resources: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        resources = resources or {}
        progress = None if n_total <= 0 else min(max(n_done / n_total, 0), 1)
        event = {
            "task_id": self.task_id,
            "timestamp": utc_now_iso(),
            "phase": phase,
            "event_type": event_type,
            "n_done": n_done,
            "n_total": n_total,
            "progress": progress,
            "rss_mb": resources.get("rss_mb"),
            "sys_mem_available_gb": resources.get("sys_mem_available_gb"),
            "disk_free_gb": resources.get("disk_free_gb"),
            "gpu_temp": resources.get("gpu_temp"),
            "gpu_util": resources.get("gpu_util"),
            "vram_used_mb": resources.get("vram_used_mb"),
            "message": message,
            "error_code": error_code,
        }
        event = _validate_event(event)
        if self._terminal_written:
            raise EventContractError("cleanup 终态事件已写入，禁止继续追加事件")
        _reject_reparse(self.run_dir)
        _reject_reparse(self.events_path)
        next_count = self._event_count + 1
        force_sync = phase == "cleanup" or event_type in {"completed", "failed", "cancelled"}
        with self.events_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            if force_sync or next_count % EVENT_FSYNC_EVERY == 0:
                os.fsync(handle.fileno())
        self._event_count = next_count
        if phase == "cleanup" and event_type in TERMINAL_EVENT_TYPES:
            self._terminal_written = True
        return event

    def write_report(self, report: Mapping[str, Any]) -> None:
        self.validate_events()
        report = _validate_report(report, self.task_id, self.run_dir)
        missing = [field for field in REPORT_FIELDS if field not in report]
        if missing:
            raise EventContractError(f"report 缺少字段：{','.join(missing)}")
        temp = self.run_dir / f".report-{uuid.uuid4().hex}.tmp"
        _reject_reparse(temp)
        try:
            if not self.manifest_path.is_file():
                raise EventContractError("report manifest.json 不存在")
            with temp.open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(dict(report), handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
                _reject_reparse(self.run_dir)
                _reject_reparse(temp)
                _reject_reparse(self.report_path)
            os.replace(temp, self.report_path)
            _reject_reparse(self.run_dir)
            _reject_reparse(self.report_path)
        finally:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass

    def write_report_recovery(self, report: Mapping[str, Any]) -> bool:
        """在主写入路径失败后再次按相同合同原子写入 report。"""
        report = _validate_report(
            report, self.task_id, self.run_dir, require_cleanup_terminal=False
        )
        temp = self.run_dir / f".report-recovery-{uuid.uuid4().hex}.tmp"
        _reject_reparse(temp)
        try:
            with temp.open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(dict(report), handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
                _reject_reparse(self.run_dir)
                _reject_reparse(temp)
                _reject_reparse(self.report_path)
            os.replace(temp, self.report_path)
            _reject_reparse(self.run_dir)
            _reject_reparse(self.report_path)
            return True
        finally:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass

    def write_manifest(self, manifest: Mapping[str, Any]) -> None:
        """原子写入当前 worker run 的摘要 manifest。"""
        manifest = _validate_manifest(manifest, self.task_id, self.run_dir)
        temp = self.run_dir / f".manifest-{uuid.uuid4().hex}.tmp"
        _reject_reparse(temp)
        try:
            with temp.open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(manifest, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
                _reject_reparse(self.run_dir)
                _reject_reparse(temp)
                _reject_reparse(self.manifest_path)
            os.replace(temp, self.manifest_path)
            _reject_reparse(self.run_dir)
            _reject_reparse(self.manifest_path)
        finally:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass


def _require_expected_task_id(expected_task_id: str) -> str:
    if not isinstance(expected_task_id, str) or not expected_task_id:
        raise EventContractError("expected_task_id 必须是非空字符串")
    return expected_task_id


def read_events(run_dir: Path, expected_task_id: str) -> list[dict[str, Any]]:
    expected_task_id = _require_expected_task_id(expected_task_id)
    run_dir = _validate_run_dir(run_dir)
    path = _contained_file(run_dir / "events.jsonl", run_dir, "events.jsonl")
    if not path.is_file():
        raise EventContractError("events.jsonl 不存在")
    return _read_events_records(path, expected_task_id)


def read_report(run_dir: Path, expected_task_id: str) -> dict[str, Any]:
    expected_task_id = _require_expected_task_id(expected_task_id)
    run_dir = _validate_run_dir(run_dir)
    path = _contained_file(run_dir / "report.json", run_dir, "report.json")
    if not path.is_file():
        raise EventContractError("report.json 不存在")
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EventContractError("report.json 无法读取") from exc
    if not isinstance(report, Mapping):
        raise EventContractError("report 根节点必须是对象")
    return _validate_report(
        report,
        expected_task_id,
        run_dir,
        require_cleanup_terminal=report.get("error_code") != "REPORT_WRITE_FAILED",
    )


def read_failure(run_dir: Path, expected_task_id: str) -> dict[str, Any]:
    """读取 report 双写失败时生成的同 run 失败工件。"""
    expected_task_id = _require_expected_task_id(expected_task_id)
    run_dir = _validate_run_dir(run_dir)
    path = _contained_file(run_dir / "failure.json", run_dir, "failure.json")
    if not path.is_file():
        raise EventContractError("failure.json 不存在")
    try:
        failure = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EventContractError("failure.json 无法读取") from exc
    return _validate_report(
        failure, expected_task_id, run_dir, require_cleanup_terminal=False
    )
