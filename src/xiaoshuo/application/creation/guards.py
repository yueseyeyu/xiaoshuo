"""Pure application-level guard functions for the creation pipeline.

These guards enforce the persistence boundary without calling into
databases, use cases, or infrastructure.  All rejected paths raise
UnsupportedPersistenceBoundary.
"""

from __future__ import annotations

from xiaoshuo.domain.creation import ChapterTask, ChapterTaskStatus, RecoveryInfo

from .errors import UnsupportedPersistenceBoundary

_FORBIDDEN_PERSISTENCE_TARGETS: frozenset[ChapterTaskStatus] = frozenset(
    {ChapterTaskStatus.COMMITTING, ChapterTaskStatus.COMPLETED}
)


def guard_persistence_target(target_status: ChapterTaskStatus) -> None:
    """Reject COMMITTING or COMPLETED as a persistence or migration destination.

    Raises:
        UnsupportedPersistenceBoundary: if *target_status* is outside the
            currently supported persistence boundary.
    """
    if target_status in _FORBIDDEN_PERSISTENCE_TARGETS:
        raise UnsupportedPersistenceBoundary(
            f"ordinary entry points cannot target {target_status.value}"
        )


def guard_committing_not_completed(task: ChapterTask) -> None:
    """Reject any write to a task whose commit_receipt_ref is already set.

    Once a commit receipt is assigned the task is considered committed
    or in the process of being committed; ordinary write paths must not
    touch it.

    Raises:
        UnsupportedPersistenceBoundary: if *task.commit_receipt_ref* is not None.
    """
    if task.commit_receipt_ref is not None:
        raise UnsupportedPersistenceBoundary(
            "cannot write to a task with a non-null commit_receipt_ref"
        )


def guard_recovery_retry_boundary(recovery: RecoveryInfo) -> None:
    """Reject a recovery whose retry_from_status lies outside the persistence boundary.

    Args:
        recovery: The RecoveryInfo attached to a RECOVERY_REQUIRED task.

    Raises:
        UnsupportedPersistenceBoundary: if *recovery.retry_from_status* is
            COMMITTING or COMPLETED.
    """
    if recovery.retry_from_status in _FORBIDDEN_PERSISTENCE_TARGETS:
        raise UnsupportedPersistenceBoundary(
            f"recovery retry_from_status {recovery.retry_from_status.value} "
            f"is outside the persistence boundary"
        )
