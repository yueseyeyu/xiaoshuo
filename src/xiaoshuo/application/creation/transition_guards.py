"""B2a-specific transition guards.

These guards enforce that only the two B2a-allowed transitions are
permitted.  They do **not** replace the existing ``guards.py`` — they
add an additional allowlist layer on top of the domain state machine.
"""

from __future__ import annotations

from xiaoshuo.domain.creation import ChapterTask, ChapterTaskStatus, RecoveryInfo

from .errors import UnsupportedPersistenceBoundary


def guard_b2a_allowed_transition(
    current_status: ChapterTaskStatus,
    target_status: ChapterTaskStatus,
    recovery: RecoveryInfo | None,
) -> None:
    """Reject any transition that is not in the B2a safe-migration subset.

    B2a allows exactly two transitions:

    1. ``REVISION_REQUIRED -> DRAFTING``
    2. ``RECOVERY_REQUIRED -> task.recovery.retry_from_status``

    All other transitions — including forward progress, approval,
    rejection, cancellation, and entering ``COMMITTING``/``COMPLETED``
    — are fail-closed.

    Args:
        current_status: The task's current status.
        target_status: The requested target status.
        recovery: The *task's* ``RecoveryInfo`` (not the command's).
            Must be non-None when ``current_status`` is
            ``RECOVERY_REQUIRED``.

    Raises:
        UnsupportedPersistenceBoundary: for any transition outside
            the B2a subset.
    """
    if current_status is ChapterTaskStatus.REVISION_REQUIRED:
        if target_status is ChapterTaskStatus.DRAFTING:
            return
        raise UnsupportedPersistenceBoundary(
            f"B2a only allows REVISION_REQUIRED -> DRAFTING, not "
            f"-> {target_status.value}"
        )

    if current_status is ChapterTaskStatus.RECOVERY_REQUIRED:
        if recovery is None:
            raise UnsupportedPersistenceBoundary(
                "RECOVERY_REQUIRED task has no recovery info"
            )
        if target_status is recovery.retry_from_status:
            return
        raise UnsupportedPersistenceBoundary(
            f"B2a recovery only allows retry to "
            f"{recovery.retry_from_status.value}, not "
            f"-> {target_status.value}"
        )

    raise UnsupportedPersistenceBoundary(
        f"B2a does not allow transition from {current_status.value} "
        f"to {target_status.value}"
    )
