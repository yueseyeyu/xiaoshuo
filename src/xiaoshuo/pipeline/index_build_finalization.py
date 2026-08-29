"""Pure finalization decisions for the MPV-02B index worker."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class RunStatus(str, Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CleanupEventType(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PersistenceStatus(str, Enum):
    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    RECOVERED = "RECOVERED"
    FAILURE_ARTIFACT_WRITTEN = "FAILURE_ARTIFACT_WRITTEN"
    UNPERSISTED = "UNPERSISTED"


@dataclass(frozen=True)
class ExecutionOutcome:
    """业务运行结果；不包含任何工件写入状态。"""

    status: RunStatus
    error_code: str | None
    exit_code: int
    cleanup_error: str | None = None


@dataclass(frozen=True)
class CleanupOutcome:
    """清理和清理终态事件结果；不得改写原始业务失败。"""

    error_text: str | None = None
    event_write_error: str | None = None

    @property
    def combined_error(self) -> str | None:
        errors = [item for item in (self.error_text, self.event_write_error) if item]
        return "; ".join(errors) or None


@dataclass(frozen=True)
class PersistenceOutcome:
    """manifest/report/failure 工件的持久化结果。"""

    persistence_status: PersistenceStatus
    status: RunStatus
    error_code: str
    exit_code: int
    original_error_code: str
    original_exit_code: int
    error_text: str


def validate_persistence_outcome(
    persistence: PersistenceOutcome,
    execution: ExecutionOutcome,
    exit_codes: Mapping[str, int],
) -> PersistenceOutcome:
    """验证持久化失败结果仍准确引用原始业务结果。"""
    if persistence.persistence_status in {
        PersistenceStatus.NOT_ATTEMPTED,
        PersistenceStatus.COMPLETE,
    }:
        raise ValueError("持久化失败结果的状态无效")
    if persistence.status is not RunStatus.FAILED:
        raise ValueError("持久化失败结果必须是 FAILED")
    if persistence.error_code != "REPORT_WRITE_FAILED":
        raise ValueError("持久化失败结果的错误码无效")
    if persistence.exit_code != exit_codes.get("REPORT_WRITE_FAILED"):
        raise ValueError("持久化失败结果的退出码不一致")
    if not isinstance(persistence.original_error_code, str) or not persistence.original_error_code:
        raise ValueError("持久化失败结果缺少原始错误码")
    expected_exit = exit_codes.get(persistence.original_error_code)
    if expected_exit is None or persistence.original_exit_code != expected_exit:
        raise ValueError("持久化失败结果的原始退出码不一致")
    if persistence.original_error_code == "COMPLETED":
        if persistence.original_exit_code != 0:
            raise ValueError("COMPLETED 原始结果的退出码无效")
    elif persistence.original_error_code == "CANCELLED":
        if persistence.original_exit_code != 2:
            raise ValueError("CANCELLED 原始结果的退出码无效")
    elif persistence.original_exit_code == 0:
        raise ValueError("失败原始结果不得使用成功退出码")
    if not isinstance(persistence.error_text, str) or not persistence.error_text.strip():
        raise ValueError("持久化失败结果缺少错误文本")
    expected_original = execution.error_code or execution.status.value
    if persistence.original_error_code != expected_original:
        raise ValueError("持久化失败结果未引用当前业务结果")
    if persistence.original_exit_code != execution.exit_code:
        raise ValueError("持久化失败结果未引用当前业务退出码")
    return persistence


@dataclass(frozen=True)
class FinalizationDecision:
    """由纯函数生成的最终对外状态和终态事件决策。"""

    status: RunStatus
    error_code: str | None
    exit_code: int
    cleanup_event_type: CleanupEventType
    cleanup_error: str | None
    original_error_code: str | None = None
    original_exit_code: int | None = None
    persistence_status: PersistenceStatus = PersistenceStatus.NOT_ATTEMPTED


def _normalize_execution(
    execution: ExecutionOutcome,
    cleanup: CleanupOutcome,
    exit_codes: Mapping[str, int],
) -> ExecutionOutcome:
    """只应用一条清理规则：成功遇到清理错误时降级为 worker 失败。"""

    if execution.status is RunStatus.COMPLETED and cleanup.combined_error:
        return ExecutionOutcome(
            status=RunStatus.FAILED,
            error_code="WORKER_FAILED",
            exit_code=exit_codes["WORKER_FAILED"],
            cleanup_error=cleanup.combined_error,
        )
    if execution.cleanup_error == cleanup.combined_error:
        return execution
    return ExecutionOutcome(
        status=execution.status,
        error_code=execution.error_code,
        exit_code=execution.exit_code,
        cleanup_error=cleanup.combined_error,
    )


def decide_finalization(
    execution: ExecutionOutcome,
    cleanup: CleanupOutcome,
    persistence: PersistenceOutcome | None,
    exit_codes: Mapping[str, int],
) -> FinalizationDecision:
    """根据业务、清理和持久化结果一次性决定最终状态。"""

    normalized = _normalize_execution(execution, cleanup, exit_codes)
    if persistence is not None:
        validate_persistence_outcome(persistence, normalized, exit_codes)
        cleanup_status = {
            RunStatus.COMPLETED.value: RunStatus.COMPLETED,
            RunStatus.CANCELLED.value: RunStatus.CANCELLED,
        }.get(persistence.original_error_code, RunStatus.FAILED)
        return FinalizationDecision(
            status=persistence.status,
            error_code=persistence.error_code,
            exit_code=persistence.exit_code,
            cleanup_event_type=cleanup_event_type(cleanup_status),
            cleanup_error=cleanup.combined_error,
            original_error_code=persistence.original_error_code,
            original_exit_code=persistence.original_exit_code,
            persistence_status=persistence.persistence_status,
        )
    return FinalizationDecision(
        status=normalized.status,
        error_code=normalized.error_code,
        exit_code=normalized.exit_code,
        cleanup_event_type=cleanup_event_type(normalized.status),
        cleanup_error=cleanup.combined_error,
    )


def normalize_execution_outcome(
    status: str,
    error_code: str | None,
    exit_code: int,
    cleanup_error: str | None,
    exit_codes: Mapping[str, int],
) -> ExecutionOutcome:
    """兼容旧调用点，将业务和清理结果转换为不可变结果对象。"""

    return _normalize_execution(
        ExecutionOutcome(RunStatus(status), error_code, exit_code, cleanup_error),
        CleanupOutcome(error_text=cleanup_error),
        exit_codes,
    )


def cleanup_event_type(status: RunStatus) -> CleanupEventType:
    return {
        RunStatus.COMPLETED: CleanupEventType.COMPLETED,
        RunStatus.FAILED: CleanupEventType.FAILED,
        RunStatus.CANCELLED: CleanupEventType.CANCELLED,
    }[status]


def persistence_failure(
    outcome: ExecutionOutcome,
    error_text: str,
    exit_codes: Mapping[str, int],
    *,
    persistence_status: PersistenceStatus = PersistenceStatus.FAILED,
) -> PersistenceOutcome:
    """表示持久化失败，同时保留原始业务结果。"""

    return PersistenceOutcome(
        persistence_status=persistence_status,
        status=RunStatus.FAILED,
        error_code="REPORT_WRITE_FAILED",
        exit_code=exit_codes["REPORT_WRITE_FAILED"],
        original_error_code=outcome.error_code or outcome.status.value,
        original_exit_code=outcome.exit_code,
        error_text=error_text,
    )
