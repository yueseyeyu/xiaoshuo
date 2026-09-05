"""MPV-02B Windows spawn 索引构建 worker。"""

from __future__ import annotations

import json
import math
import multiprocessing as mp
import os
import re
import shutil
import time
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import psutil

from xiaoshuo import PROJECT_ROOT
from xiaoshuo.infra.hardware_guardian import (
    _read_gpu_temp_smi,
    _read_gpu_util_smi,
    _read_vram_used_smi,
)
from xiaoshuo.pipeline.index_build_events import EventWriter
from xiaoshuo.pipeline.index_build_events import utc_now_iso
from xiaoshuo.pipeline.index_build_persistence import (
    write_bootstrap_report,
    write_failure_artifact,
)
from xiaoshuo.pipeline.index_build_finalization import (
    CleanupOutcome,
    ExecutionOutcome,
    cleanup_event_type,
    decide_finalization,
    normalize_execution_outcome,
    persistence_failure,
    RunStatus,
)
from xiaoshuo.pipeline.scene_search import (
    BuildProgressAbort,
    CorpusContractError,
    IndexStagingCleanupError,
    IndexPublishRollbackError,
    IndexNotReadyError,
    EmbeddingModelError,
    SceneSearch,
)

WORKER_STAGE_ROOT = Path(r"D:\tmp\yeyu-ai-a3\mpv-02b-worker")
RUN_ID_RE = re.compile(r"^\d{8}-\d{6}-\d{6}$")
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
RESOURCE_LIMIT_KEYS = frozenset({
    "rss_mb", "disk_free_gb", "gpu_temp_c", "vram_mb", "sys_mem_available_gb",
})


def _validate_resource_limits(limits: Mapping[str, Any]) -> None:
    unknown_keys = set(limits) - RESOURCE_LIMIT_KEYS
    if unknown_keys:
        raise WorkerStop("WORKER_FAILED", f"资源阈值包含未知键：{','.join(sorted(unknown_keys))}")
    for key, value in limits.items():
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or value <= 0
        ):
            raise WorkerStop("WORKER_FAILED", f"资源阈值无效：{key}")


class WorkerStop(BuildProgressAbort):
    """worker 在安全边界主动停止。"""

    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code
        self.message = message


@dataclass(frozen=True)
class IndexBuildTaskSnapshot:
    task_id: str
    genre: str
    force: bool
    limit: int
    run_dir: str
    cache_dir: str
    model_local_path: str
    resource_limits: dict[str, Any]
    cancel_flag: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "IndexBuildTaskSnapshot":
        required = (
            "task_id", "genre", "force", "limit", "run_dir", "cache_dir",
            "model_local_path", "resource_limits", "cancel_flag",
        )
        if not isinstance(raw, Mapping) or any(field not in raw for field in required):
            raise WorkerStop("WORKER_FAILED", "worker 任务快照字段不完整")
        if not all(isinstance(raw[field], str) and raw[field] for field in (
            "task_id", "genre", "run_dir", "cache_dir", "model_local_path", "cancel_flag",
        )):
            raise WorkerStop("WORKER_FAILED", "worker 任务快照字符串字段无效")
        if not isinstance(raw["force"], bool):
            raise WorkerStop("WORKER_FAILED", "worker force 字段无效")
        if isinstance(raw["limit"], bool) or not isinstance(raw["limit"], int) or raw["limit"] < 0:
            raise WorkerStop("WORKER_FAILED", "worker limit 字段无效")
        if not isinstance(raw["resource_limits"], dict):
            raise WorkerStop("WORKER_FAILED", "worker resource_limits 字段无效")
        return cls(
            task_id=raw["task_id"],
            genre=raw["genre"],
            force=raw["force"],
            limit=raw["limit"],
            run_dir=raw["run_dir"],
            cache_dir=raw["cache_dir"],
            model_local_path=raw["model_local_path"],
            resource_limits=dict(raw["resource_limits"]),
            cancel_flag=raw["cancel_flag"],
        )


def _reject_reparse(path: Path) -> None:
    current = path.absolute()
    while True:
        try:
            if current.is_symlink():
                raise WorkerStop("PERMISSION_DENIED", f"路径包含符号链接：{current}")
            attrs = getattr(current.stat(follow_symlinks=False), "st_file_attributes", 0)
        except TypeError:  # pragma: no cover - 旧版 Python 回退
            attrs = getattr(os.lstat(current), "st_file_attributes", 0)
        except FileNotFoundError:
            attrs = 0
        if attrs & 0x400:
            raise WorkerStop("PERMISSION_DENIED", f"路径包含 Windows reparse point：{current}")
        parent = current.parent
        if parent == current:
            return
        current = parent


def _validate_run_dir(run_dir: Path, *, require_fresh: bool = True) -> None:
    run_dir = run_dir.absolute()
    if run_dir.drive.upper() != "D:":
        raise WorkerStop("PERMISSION_DENIED", "worker run 目录必须位于 D 盘")
    try:
        relative = run_dir.relative_to(WORKER_STAGE_ROOT.absolute())
    except ValueError as exc:
        raise WorkerStop("PERMISSION_DENIED", "worker run 目录越出批准 stage") from exc
    if len(relative.parts) != 1 or not RUN_ID_RE.fullmatch(relative.name):
        raise WorkerStop("WORKER_FAILED", "worker run-id 格式无效")
    _reject_reparse(WORKER_STAGE_ROOT)
    _reject_reparse(run_dir)
    if require_fresh and run_dir.exists():
        raise WorkerStop("WORKER_FAILED", "worker run 目录必须是 fresh")


def _create_run_dir(run_dir: Path) -> None:
    """创建 fresh run，并在创建前后复核 stage/run 的路径边界。"""

    stage_root = WORKER_STAGE_ROOT.absolute()
    _reject_reparse(stage_root)
    stage_root.mkdir(parents=True, exist_ok=True)
    _reject_reparse(stage_root)
    _validate_run_dir(run_dir)
    run_dir.mkdir(parents=False, exist_ok=False)
    _validate_run_dir(run_dir, require_fresh=False)


def _validate_snapshot_paths(snapshot: IndexBuildTaskSnapshot) -> tuple[Path, Path, Path, Path]:
    run_dir = Path(snapshot.run_dir).absolute()
    cache_dir = Path(snapshot.cache_dir).absolute()
    model_dir = Path(snapshot.model_local_path).absolute()
    cancel_flag = Path(snapshot.cancel_flag).absolute()
    _validate_run_dir(run_dir)
    if cancel_flag.parent != run_dir or cancel_flag.name != "cancel.flag":
        raise WorkerStop("WORKER_FAILED", "cancel.flag 必须位于当前 run 目录")
    _reject_reparse(cancel_flag.parent)
    _reject_reparse(cancel_flag)
    _reject_reparse(model_dir)
    if model_dir.drive.upper() != "D:" or not model_dir.is_dir():
        raise WorkerStop("MODEL_ERROR", "本地模型目录无效")
    _reject_reparse(cache_dir)
    if cache_dir.drive.upper() != "D:":
        raise WorkerStop("PERMISSION_DENIED", "索引缓存必须位于 D 盘")
    expected_cache = run_dir / "output" / (
        "scene_index" if snapshot.limit == 0 else "scene_index.sample"
    )
    try:
        cache_dir.resolve(strict=False).relative_to(run_dir.resolve(strict=False))
    except (OSError, ValueError) as exc:
        raise WorkerStop("PERMISSION_DENIED", "索引缓存必须位于当前 run/output 内") from exc
    if cache_dir != expected_cache.absolute():
        raise WorkerStop("WORKER_FAILED", "索引缓存必须绑定当前 run 的固定 output 目录")
    _validate_resource_limits(snapshot.resource_limits)
    return run_dir, cache_dir, model_dir, cancel_flag


class ResourceSampler:
    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.process = psutil.Process(os.getpid())
        self.peak_rss_mb: float | None = None
        self.peak_vram_mb: float | None = None

    def snapshot(self) -> dict[str, float | None]:
        try:
            rss_mb = self.process.memory_info().rss / (1024 * 1024)
        except (OSError, psutil.Error):
            rss_mb = None
        try:
            available_gb = psutil.virtual_memory().available / (1024 ** 3)
        except (OSError, psutil.Error):
            available_gb = None
        try:
            disk_free_gb = shutil.disk_usage(self.run_dir.drive + "\\").free / (1024 ** 3)
        except OSError:
            disk_free_gb = None
        try:
            gpu_temp = _read_gpu_temp_smi()
        except Exception:
            gpu_temp = None
        try:
            gpu_util = _read_gpu_util_smi()
        except Exception:
            gpu_util = None
        try:
            vram_used_mb = _read_vram_used_smi()
        except Exception:
            vram_used_mb = None
        if rss_mb is not None:
            self.peak_rss_mb = max(self.peak_rss_mb or 0, rss_mb)
        if vram_used_mb is not None:
            self.peak_vram_mb = max(self.peak_vram_mb or 0, vram_used_mb)
        return {
            "rss_mb": rss_mb,
            "sys_mem_available_gb": available_gb,
            "disk_free_gb": disk_free_gb,
            "gpu_temp": gpu_temp,
            "gpu_util": gpu_util,
            "vram_used_mb": vram_used_mb,
        }

    def check(self, limits: Mapping[str, Any], resources: Mapping[str, Any]) -> None:
        checks = (
            ("rss_mb", "rss_mb", lambda actual, limit: actual >= limit),
            ("disk_free_gb", "disk_free_gb", lambda actual, limit: actual <= limit),
            ("gpu_temp", "gpu_temp_c", lambda actual, limit: actual >= limit),
            ("vram_used_mb", "vram_mb", lambda actual, limit: actual >= limit),
            ("sys_mem_available_gb", "sys_mem_available_gb", lambda actual, limit: actual <= limit),
        )
        for actual_key, limit_key, exceeded in checks:
            actual = resources.get(actual_key)
            limit = limits.get(limit_key)
            if limit is not None and actual is None:
                raise WorkerStop(
                    "RESOURCE_EXCEEDED",
                    f"资源指标不可用，无法证明安全：{actual_key}",
                )
            if actual is not None and limit is not None and exceeded(actual, limit):
                raise WorkerStop(
                    "RESOURCE_EXCEEDED",
                    f"资源阈值触发：{actual_key}={actual}，limit={limit}",
                )


class WorkerSession:
    def __init__(self, snapshot: IndexBuildTaskSnapshot, writer: EventWriter):
        self.snapshot = snapshot
        self.writer = writer
        self.sampler = ResourceSampler(Path(snapshot.run_dir))
        self.completed_phases: set[str] = set()
        self.current_phase = "preflight"
        self.cleanup_errors: list[str] = []

    def _cancelled(self) -> bool:
        cancel_flag = Path(self.snapshot.cancel_flag)
        _reject_reparse(cancel_flag)
        return cancel_flag.is_file()

    def on_progress(self, phase: str, n_done: int, n_total: int) -> None:
        self.current_phase = phase
        if phase in self.completed_phases and n_total > 0 and n_done >= n_total:
            return
        if phase in {"collect", "tokenize", "encode"} or (phase == "publish" and n_done == 0):
            if self._cancelled():
                raise WorkerStop("CANCELLED", "收到取消标记")
        should_emit = (
            phase == "publish"
            or n_done == 0
            or n_done == n_total
            or (phase == "collect" and n_done % 5 == 0)
            or (phase in {"tokenize", "encode"} and n_done % 100 == 0)
        )
        if not should_emit:
            return
        resources = self.sampler.snapshot()
        if phase in {"collect", "tokenize", "encode"} or (phase == "publish" and n_done == 0):
            self.sampler.check(self.snapshot.resource_limits, resources)
        event_type = "progress"
        if n_done == 0:
            event_type = "started"
        elif n_total > 0 and n_done >= n_total:
            event_type = "completed"
        if phase == "cleanup" and event_type in {"cancelled", "failed", "completed"}:
            # SceneSearch 已通过回调报告 cleanup 进度；终态只允许收尾层写入。
            return
        try:
            self.writer.write_event(
                phase,
                event_type,
                n_done=n_done,
                n_total=n_total,
                resources=resources,
            )
        except Exception as exc:
            if phase == "cleanup":
                self.cleanup_errors.append(f"事件写入失败：{exc}")
                return
            raise WorkerStop("WORKER_FAILED", f"事件写入失败：{exc}") from exc
        if n_done >= n_total and phase in {"collect", "tokenize", "encode", "publish"}:
            self.completed_phases.add(phase)


def _error_from_exception(exc: BaseException) -> tuple[str, int]:
    if isinstance(exc, WorkerStop):
        return exc.error_code, EXIT_CODES.get(exc.error_code, EXIT_CODES["WORKER_FAILED"])
    if isinstance(exc, PermissionError):
        return "PERMISSION_DENIED", EXIT_CODES["PERMISSION_DENIED"]
    if isinstance(exc, EmbeddingModelError):
        return "MODEL_ERROR", EXIT_CODES["MODEL_ERROR"]
    if isinstance(exc, IndexPublishRollbackError):
        return "PUBLISH_ROLLBACK_FAILED", EXIT_CODES["PUBLISH_ROLLBACK_FAILED"]
    if isinstance(exc, CorpusContractError):
        return "CORPUS_CONTRACT_INVALID", EXIT_CODES["CORPUS_ERROR"]
    if isinstance(exc, IndexStagingCleanupError):
        return "WORKER_FAILED", EXIT_CODES["WORKER_FAILED"]
    if isinstance(exc, IndexNotReadyError):
        if any(keyword in str(exc) for keyword in ("模型", "BGE", "tokenizer", "embedding")):
            return "MODEL_ERROR", EXIT_CODES["MODEL_ERROR"]
        return "INDEX_CORRUPT", EXIT_CODES["INDEX_CORRUPT"]
    return "WORKER_FAILED", EXIT_CODES["WORKER_FAILED"]


def _diagnostic_text(exc: BaseException) -> str:
    """把异常转换为合同要求的非空诊断文本。"""
    message = str(exc).strip()
    return message or type(exc).__name__


def _join_errors(*errors: str | None) -> str | None:
    """保留多个独立失败来源，避免后续错误覆盖先前诊断。"""
    values = [error.strip() for error in errors if isinstance(error, str) and error.strip()]
    return "; ".join(values) or None


def _manifest_counts(path: Path) -> tuple[int | None, int | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("n_books"), data.get("n_scenes")
    except (OSError, json.JSONDecodeError, TypeError):
        return None, None


def _write_bootstrap_report(
    run_dir: Path, task_id: str, error_code: str, message: str
) -> bool:
    return write_bootstrap_report(
        run_dir, task_id, error_code, message, reject_reparse=_reject_reparse
    )


def _write_failure_artifact(
    run_dir: Path, payload: Mapping[str, Any], expected_task_id: str
) -> bool:
    return write_failure_artifact(
        run_dir, payload, expected_task_id, reject_reparse=_reject_reparse
    )


def _run_worker(snapshot: IndexBuildTaskSnapshot, run_dir: Path) -> int:
    """统一拥有 worker 生命周期，包括 EventWriter 不可用时的 bootstrap。"""

    try:
        return _run_worker_impl(snapshot, run_dir)
    except BaseException as exc:
        error_code, exit_code = _error_from_exception(exc)
        recovered = _write_bootstrap_report(run_dir, snapshot.task_id, error_code, str(exc))
        print(json.dumps({
            "status": "FAILED",
            "error_code": error_code,
            "message": str(exc),
            "report_recovered": recovered,
        }, ensure_ascii=False, separators=(",", ":")))
        return exit_code


def _run_worker_impl(snapshot: IndexBuildTaskSnapshot, run_dir: Path) -> int:
    writer = EventWriter(run_dir, snapshot.task_id)
    session = WorkerSession(snapshot, writer)
    started_at = time.monotonic()
    started_iso = utc_now_iso()
    status = "FAILED"
    error_code: str | None = None
    cleanup_error: str | None = None
    message = ""
    exit_code = EXIT_CODES["WORKER_FAILED"]
    n_books = n_scenes = None
    manifest_path: str | None = None
    event_write_error: str | None = None
    try:
        started_iso = writer.write_event("preflight", "started").get("timestamp", started_iso)
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        writer.write_event("preflight", "completed", message="worker preflight 通过")
        writer.write_event("collect", "started")
        def guard_resources() -> None:
            resources = session.sampler.snapshot()
            session.sampler.check(snapshot.resource_limits, resources)

        cache_dir = Path(snapshot.cache_dir).absolute()
        engine = SceneSearch(
            snapshot.genre,
            resource_guard=guard_resources,
            cache_dir=cache_dir,
            cache_root=run_dir,
        )
        actual_model = Path(engine.embedding_model_path).absolute()
        if actual_model.resolve(strict=False) != Path(snapshot.model_local_path).absolute().resolve(strict=True):
            raise WorkerStop("MODEL_ERROR", "SceneSearch 实际模型目录与任务快照不一致")
        actual_cache = Path(getattr(engine, "_cache", cache_dir)).absolute()
        if actual_cache != Path(snapshot.cache_dir).absolute():
            raise WorkerStop("WORKER_FAILED", "SceneSearch 实际缓存目录与任务快照不一致")
        count = engine.build_index(
            force=snapshot.force,
            limit=snapshot.limit,
            on_progress=session.on_progress,
            publish_backup_dir=run_dir / "backup",
            staging_dir=run_dir / "staging",
        )
        if count == 0:
            raise WorkerStop("CORPUS_EMPTY", "当前题材没有可构建语料")
        manifest = actual_cache / "manifest.json"
        n_books, n_scenes = _manifest_counts(manifest)
        if n_scenes is None:
            n_scenes = count
        writer.write_manifest({
            "schema_version": 1,
            "task_id": snapshot.task_id,
            "status": "COMPLETED",
            "genre": snapshot.genre,
            "build_scope": "full" if snapshot.limit == 0 else "sample",
            "build_limit": snapshot.limit,
            "cache_manifest_path": manifest.as_posix(),
            "events_path": writer.events_path.as_posix(),
            "error_code": None,
        })
        manifest_path = writer.manifest_path.as_posix()
        status = "COMPLETED"
        exit_code = EXIT_CODES[status]
        message = f"索引构建完成：{count} 个场景"
    except BaseException as exc:
        error_code, exit_code = _error_from_exception(exc)
        status = "CANCELLED" if error_code == "CANCELLED" else "FAILED"
        message = str(exc)
        cleanup_error = getattr(exc, "cleanup_error", None)
        if session.cleanup_errors:
            cleanup_error = _join_errors(cleanup_error, *session.cleanup_errors)
        phase = session.current_phase
        if phase == "cleanup":
            cleanup_error = _join_errors(cleanup_error, f"cleanup 异常：{message}")
        else:
            try:
                writer.write_event(
                    phase,
                    "cancelled" if error_code == "CANCELLED" else "failed",
                    message=message,
                    error_code=error_code,
                    resources=session.sampler.snapshot(),
                )
            except Exception as event_exc:
                event_write_error = f"失败事件写入失败：{event_exc}"
    finally:
        manifest_persistence_error: str | None = None
        report_original_error_code: str | None = None
        report_original_exit_code: int | None = None
        report_write_error: str | None = None
        if session.cleanup_errors:
            cleanup_error = _join_errors(cleanup_error, *session.cleanup_errors)
        business_execution = ExecutionOutcome(RunStatus(status), error_code, exit_code)
        cleanup = CleanupOutcome(
            error_text=cleanup_error,
            event_write_error=event_write_error,
        )
        decision = decide_finalization(business_execution, cleanup, None, EXIT_CODES)
        status = decision.status.value
        error_code = decision.error_code
        exit_code = decision.exit_code
        effective_execution = ExecutionOutcome(
            decision.status, decision.error_code, decision.exit_code, decision.cleanup_error
        )
        cleanup_error = decision.cleanup_error
        persistence = None
        pre_sync_error_code = error_code or (
            "COMPLETED" if status == "COMPLETED"
            else "CANCELLED" if status == "CANCELLED"
            else "WORKER_FAILED"
        )
        pre_sync_exit_code = EXIT_CODES[pre_sync_error_code]
        if writer.manifest_path.is_file():
            try:
                manifest = json.loads(writer.manifest_path.read_text(encoding="utf-8"))
                if not isinstance(manifest, dict):
                    raise ValueError("manifest 根节点必须是对象")
                manifest.update(status=status, error_code=error_code)
                writer.write_manifest(manifest)
            except Exception as manifest_sync_exc:
                manifest_persistence_error = _diagnostic_text(manifest_sync_exc)
                persistence = persistence_failure(
                    effective_execution, manifest_persistence_error, EXIT_CODES
                )
                report_original_error_code = persistence.original_error_code
                report_original_exit_code = persistence.original_exit_code
                report_write_error = manifest_persistence_error
                decision = decide_finalization(
                    effective_execution,
                    CleanupOutcome(error_text=cleanup_error),
                    persistence,
                    EXIT_CODES,
                )
                status = decision.status.value
                error_code = decision.error_code
                exit_code = decision.exit_code
        else:
            try:
                writer.write_manifest({
                    "schema_version": 1,
                    "task_id": snapshot.task_id,
                    "status": status,
                    "genre": snapshot.genre,
                    "build_scope": "full" if snapshot.limit == 0 else "sample",
                    "build_limit": snapshot.limit,
                    "cache_manifest_path": (
                        (Path(snapshot.cache_dir) / "manifest.json").as_posix()
                        if (Path(snapshot.cache_dir) / "manifest.json").is_file()
                        else None
                    ),
                    "events_path": writer.events_path.as_posix(),
                    "error_code": error_code,
                })
                manifest_path = writer.manifest_path.as_posix()
            except Exception as manifest_exc:
                manifest_persistence_error = _diagnostic_text(manifest_exc)
                persistence = persistence_failure(
                    effective_execution, manifest_persistence_error, EXIT_CODES
                )
                report_original_error_code = persistence.original_error_code
                report_original_exit_code = persistence.original_exit_code
                report_write_error = manifest_persistence_error
                decision = decide_finalization(
                    effective_execution,
                    CleanupOutcome(error_text=cleanup_error),
                    persistence,
                    EXIT_CODES,
                )
                status = decision.status.value
                error_code = decision.error_code
                exit_code = decision.exit_code
        cleanup_type = decision.cleanup_event_type.value
        cleanup_event_error_code = (
            None
            if cleanup_type == "completed"
            else "CANCELLED"
            if cleanup_type == "cancelled"
            else (
                decision.original_error_code
                if decision.error_code == "REPORT_WRITE_FAILED"
                else decision.error_code
            )
        )
        try:
            finished_iso = writer.write_event(
                "cleanup",
                cleanup_type,
                message="worker 收尾",
                error_code=cleanup_event_error_code,
                resources=session.sampler.snapshot(),
            ).get("timestamp")
        except Exception as cleanup_event_exc:
            finished_iso = utc_now_iso()
            cleanup_error = _join_errors(cleanup_error, f"收尾事件写入失败：{cleanup_event_exc}")
            decision = decide_finalization(
                business_execution,
                CleanupOutcome(error_text=cleanup_error),
                None,
                EXIT_CODES,
            )
            status = decision.status.value
            error_code = decision.error_code
            exit_code = decision.exit_code
            effective_execution = ExecutionOutcome(
                decision.status, decision.error_code, decision.exit_code, decision.cleanup_error
            )
            if persistence is not None:
                persistence = persistence_failure(
                    effective_execution,
                    _join_errors(
                        manifest_persistence_error,
                        report_write_error,
                        "cleanup 终态事件写入失败",
                    ) or "持久化失败",
                    EXIT_CODES,
                )
                report_original_error_code = persistence.original_error_code
                report_original_exit_code = persistence.original_exit_code
                report_write_error = persistence.error_text
                decision = decide_finalization(
                    effective_execution,
                    CleanupOutcome(error_text=cleanup_error),
                    persistence,
                    EXIT_CODES,
                )
                status = decision.status.value
                error_code = decision.error_code
                exit_code = decision.exit_code
            else:
                try:
                    manifest = json.loads(writer.manifest_path.read_text(encoding="utf-8"))
                    if not isinstance(manifest, dict):
                        raise ValueError("manifest 根节点必须是对象")
                    manifest.update(status=status, error_code=error_code)
                    writer.write_manifest(manifest)
                except Exception as manifest_sync_exc:
                    manifest_persistence_error = _diagnostic_text(manifest_sync_exc)
                    persistence = persistence_failure(
                        effective_execution, manifest_persistence_error, EXIT_CODES
                    )
                    report_original_error_code = persistence.original_error_code
                    report_original_exit_code = persistence.original_exit_code
                    report_write_error = manifest_persistence_error
                    decision = decide_finalization(
                        effective_execution,
                        CleanupOutcome(error_text=cleanup_error),
                        persistence,
                        EXIT_CODES,
                    )
                    status = decision.status.value
                    error_code = decision.error_code
                    exit_code = decision.exit_code
        report = {
            "task_id": snapshot.task_id,
            "status": status,
            "error_code": error_code,
            "started_at": started_iso,
            "finished_at": finished_iso,
            "duration_seconds": round(time.monotonic() - started_at, 3),
            "n_books": n_books,
            "n_scenes": n_scenes,
            "peak_rss_mb": session.sampler.peak_rss_mb,
            "peak_vram_mb": session.sampler.peak_vram_mb,
            "manifest_path": manifest_path or writer.manifest_path.as_posix(),
            "events_path": writer.events_path.as_posix(),
            "worker_exit_code": exit_code,
            "cleanup_error": cleanup_error,
            "original_error_code": report_original_error_code,
            "original_exit_code": report_original_exit_code,
            "report_write_error": report_write_error,
            "report_recovery_error": None,
        }
        try:
            writer.validate_events()
            writer.write_report(report)
        except Exception as report_exc:
            # report recovery 要保留原始业务结果；清理和持久化错误分别由
            # cleanup_error、REPORT_WRITE_FAILED 及 original_* 字段表达。
            report_outcome = effective_execution
            persistence = persistence_failure(
                report_outcome, _diagnostic_text(report_exc), EXIT_CODES
            )
            original_error_code = persistence.original_error_code
            original_exit_code = persistence.original_exit_code
            recovery_error: str | None = None
            recovered = False
            recovery_report = dict(report)
            recovery_report.update(
                status=persistence.status.value,
                error_code=persistence.error_code,
                worker_exit_code=persistence.exit_code,
                original_error_code=original_error_code,
                original_exit_code=original_exit_code,
                report_write_error=_join_errors(
                    report_write_error,
                    _diagnostic_text(report_exc),
                ),
                report_recovery_error=None,
            )
            try:
                recovered = writer.write_report_recovery(recovery_report)
            except Exception as fallback_exc:
                recovery_error = _diagnostic_text(fallback_exc)
            if not recovered and recovery_error is None:
                recovery_error = "report recovery 未写入"
            recovery_report["report_recovery_error"] = recovery_error
            failure_artifact_written = False
            if not recovered:
                failure_artifact_written = _write_failure_artifact(
                    run_dir, recovery_report, snapshot.task_id
                )
            error_code = "REPORT_WRITE_FAILED"
            exit_code = EXIT_CODES[error_code]
            print(json.dumps({
                "status": "RECOVERED" if recovered else "FAILED",
                "error_code": error_code,
                "original_error_code": original_error_code,
                "original_exit_code": original_exit_code,
                "worker_exit_code": exit_code,
                "message": f"结构化 report 写入失败：{_diagnostic_text(report_exc)}",
                "report_recovery_error": recovery_error,
                "failure_artifact_written": failure_artifact_written,
                "persistence_status": (
                    "RECOVERED" if recovered
                    else "FAILURE_ARTIFACT_WRITTEN" if failure_artifact_written
                    else "UNPERSISTED"
                ),
            }, ensure_ascii=False, separators=(",", ":")))
    return exit_code


def run_index_build_worker(snapshot: Mapping[str, Any]) -> int:
    """校验并执行一个 fresh worker run，返回固定退出码。"""
    try:
        task = IndexBuildTaskSnapshot.from_mapping(snapshot)
        run_dir, _, _, _ = _validate_snapshot_paths(task)
    except (WorkerStop, PermissionError) as exc:
        error_code, exit_code = _error_from_exception(exc)
        print(json.dumps({
            "status": "FAILED",
            "error_code": error_code,
            "message": str(exc),
        }, ensure_ascii=False, separators=(",", ":")))
        return exit_code
    try:
        _create_run_dir(run_dir)
    except FileExistsError as exc:
        print(json.dumps({
            "status": "FAILED",
            "error_code": "WORKER_FAILED",
            "message": f"worker run 已被占用：{exc}",
        }, ensure_ascii=False, separators=(",", ":")))
        return EXIT_CODES["WORKER_FAILED"]
    except PermissionError as exc:
        print(json.dumps({
            "status": "FAILED",
            "error_code": "PERMISSION_DENIED",
            "message": str(exc),
        }, ensure_ascii=False, separators=(",", ":")))
        return EXIT_CODES["PERMISSION_DENIED"]
    log_path = run_dir / "worker.log"
    try:
        log_handle = log_path.open("a", encoding="utf-8", newline="\n")
    except OSError:
        # 日志文件不是构建证据；日志权限失败时仍让 worker 写入标准 run 工件。
        return _run_worker(task, run_dir)
    with log_handle:
        with redirect_stdout(log_handle), redirect_stderr(log_handle):
            return _run_worker(task, run_dir)


def _process_entry(snapshot: dict[str, Any]) -> None:
    raise SystemExit(run_index_build_worker(snapshot))


def start_index_build_worker(snapshot: Mapping[str, Any]) -> mp.Process:
    """使用 Windows spawn 启动 worker；父进程不传递模型对象。"""
    task = IndexBuildTaskSnapshot.from_mapping(snapshot)
    _validate_snapshot_paths(task)
    context = mp.get_context("spawn")
    process = context.Process(target=_process_entry, args=(dict(snapshot),), daemon=False)
    process.start()
    return process
