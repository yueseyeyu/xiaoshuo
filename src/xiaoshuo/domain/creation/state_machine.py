"""Pure state transitions and author-decision validation for ChapterTask."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from .hashing import CreationDomainError
from .models import (
    ArtifactRef,
    AuthorDecision,
    ChapterTask,
    ChapterTaskStatus,
    DecisionOutcome,
    DecisionType,
    RecoveryInfo,
    SourceKind,
)


class InvalidStateTransition(CreationDomainError):
    """Raised when a ChapterTask transition is not permitted."""


class RevisionConflict(CreationDomainError):
    """Raised when optimistic concurrency detects a stale aggregate revision."""


class InvalidAuthorDecision(CreationDomainError):
    """Raised when an author decision does not match the expected approval gate."""


_DIRECT_TRANSITIONS: dict[ChapterTaskStatus, frozenset[ChapterTaskStatus]] = {
    ChapterTaskStatus.PLAN_PREPARING: frozenset({ChapterTaskStatus.PLAN_APPROVAL_PENDING}),
    ChapterTaskStatus.PLAN_APPROVAL_PENDING: frozenset({ChapterTaskStatus.DRAFTING}),
    ChapterTaskStatus.DRAFTING: frozenset({ChapterTaskStatus.REVIEWING}),
    ChapterTaskStatus.REVIEWING: frozenset(
        {ChapterTaskStatus.REVISION_REQUIRED, ChapterTaskStatus.DRAFT_APPROVAL_PENDING}
    ),
    ChapterTaskStatus.REVISION_REQUIRED: frozenset({ChapterTaskStatus.DRAFTING}),
    ChapterTaskStatus.DRAFT_APPROVAL_PENDING: frozenset(
        {ChapterTaskStatus.DRAFTING, ChapterTaskStatus.CHANGESET_PREPARING}
    ),
    ChapterTaskStatus.CHANGESET_PREPARING: frozenset(
        {ChapterTaskStatus.CHANGESET_APPROVAL_PENDING}
    ),
    ChapterTaskStatus.CHANGESET_APPROVAL_PENDING: frozenset(
        {ChapterTaskStatus.CHANGESET_PREPARING, ChapterTaskStatus.COMMITTING}
    ),
    ChapterTaskStatus.COMMITTING: frozenset({ChapterTaskStatus.COMPLETED}),
}

_TERMINAL_STATUSES = frozenset(
    {ChapterTaskStatus.COMPLETED, ChapterTaskStatus.CANCELLED}
)

_APPROVE_DECISIONS = frozenset(
    {
        DecisionType.CONFIRM_PLAN,
        DecisionType.ADOPT_DRAFT,
        DecisionType.APPROVE_CHANGESET,
        DecisionType.CONFIRM_NO_CANON_CHANGE,
    }
)
_REJECT_DECISIONS = frozenset(
    {
        DecisionType.REJECT_PLAN,
        DecisionType.REJECT_DRAFT,
        DecisionType.REJECT_CHANGESET,
        DecisionType.CANCEL_TASK,
    }
)


def can_transition(current_status: ChapterTaskStatus, target_status: ChapterTaskStatus) -> bool:
    """Return whether statuses can be adjacent, excluding recovery target identity checks."""
    if not isinstance(current_status, ChapterTaskStatus) or not isinstance(
        target_status, ChapterTaskStatus
    ):
        return False
    if current_status in _TERMINAL_STATUSES:
        return False
    if current_status is ChapterTaskStatus.RECOVERY_REQUIRED:
        return (
            target_status not in _TERMINAL_STATUSES
            and target_status is not ChapterTaskStatus.RECOVERY_REQUIRED
        )
    if target_status is ChapterTaskStatus.RECOVERY_REQUIRED:
        return True
    if target_status is ChapterTaskStatus.CANCELLED:
        return current_status is not ChapterTaskStatus.COMMITTING
    return target_status in _DIRECT_TRANSITIONS.get(current_status, frozenset())


def transition_task(
    task: ChapterTask,
    target_status: ChapterTaskStatus,
    expected_revision: int,
    recovery: RecoveryInfo | None = None,
) -> ChapterTask:
    """Return a new task after enforcing transition and recovery invariants."""
    if expected_revision != task.aggregate_revision:
        raise RevisionConflict(
            f"expected revision {expected_revision}, current revision {task.aggregate_revision}"
        )
    if task.status in _TERMINAL_STATUSES:
        raise InvalidStateTransition(f"terminal status {task.status.value} cannot transition")

    if task.status is ChapterTaskStatus.RECOVERY_REQUIRED:
        if task.recovery is None or target_status is not task.recovery.retry_from_status:
            raise InvalidStateTransition("recovery may only return to retry_from_status")
        if recovery is not None:
            raise InvalidStateTransition("recovery information must be cleared when recovering")
        return replace(
            task,
            status=target_status,
            last_stable_status=target_status,
            aggregate_revision=task.aggregate_revision + 1,
            recovery=None,
            updated_at=datetime.now(timezone.utc),
        )

    if target_status is ChapterTaskStatus.RECOVERY_REQUIRED:
        if recovery is None:
            raise InvalidStateTransition("entering RECOVERY_REQUIRED requires RecoveryInfo")
        if recovery.retry_from_status is not task.last_stable_status:
            raise InvalidStateTransition("retry_from_status must match last_stable_status")
        return replace(
            task,
            status=target_status,
            aggregate_revision=task.aggregate_revision + 1,
            recovery=recovery,
            updated_at=datetime.now(timezone.utc),
        )

    if recovery is not None:
        raise InvalidStateTransition("RecoveryInfo is only valid when entering recovery")
    if not can_transition(task.status, target_status):
        raise InvalidStateTransition(
            f"cannot transition from {task.status.value} to {target_status.value}"
        )
    if target_status is ChapterTaskStatus.COMPLETED and task.commit_receipt_ref is None:
        raise InvalidStateTransition("COMPLETED requires a pre-existing commit receipt reference")
    return replace(
        task,
        status=target_status,
        last_stable_status=target_status,
        aggregate_revision=task.aggregate_revision + 1,
        updated_at=datetime.now(timezone.utc),
    )


def complete_task_with_receipt(
    task: ChapterTask,
    receipt_ref: ArtifactRef,
    expected_revision: int,
) -> ChapterTask:
    """Complete a Canon commit in one domain construction.

    This is intentionally separate from :func:`transition_task`: the generic
    B2a/B2b transition path must never manufacture a temporary ``COMMITTING``
    task carrying a receipt.  The receipt reference and terminal status are
    therefore validated and constructed together.
    """
    if expected_revision != task.aggregate_revision:
        raise RevisionConflict(
            f"expected revision {expected_revision}, current revision {task.aggregate_revision}"
        )
    if task.status is not ChapterTaskStatus.COMMITTING:
        raise InvalidStateTransition("only COMMITTING tasks can be completed")
    if task.commit_receipt_ref is not None:
        raise InvalidStateTransition("COMMITTING task already carries a receipt")
    if task.recovery is not None:
        raise InvalidStateTransition("COMMITTING task cannot carry recovery information")
    if not isinstance(receipt_ref, ArtifactRef):
        raise InvalidStateTransition("completion requires an ArtifactRef receipt")
    return replace(
        task,
        status=ChapterTaskStatus.COMPLETED,
        last_stable_status=ChapterTaskStatus.COMPLETED,
        aggregate_revision=task.aggregate_revision + 1,
        commit_receipt_ref=receipt_ref,
        updated_at=datetime.now(timezone.utc),
    )


def enter_canon_recovery(
    task: ChapterTask,
    expected_revision: int,
    recovery: RecoveryInfo,
) -> ChapterTask:
    """Move a COMMITTING task to Canon-specific recovery."""
    if expected_revision != task.aggregate_revision:
        raise RevisionConflict(
            f"expected revision {expected_revision}, current revision {task.aggregate_revision}"
        )
    if task.status is not ChapterTaskStatus.COMMITTING:
        raise InvalidStateTransition("Canon recovery requires COMMITTING")
    if recovery.retry_from_status is not ChapterTaskStatus.COMMITTING:
        raise InvalidStateTransition("Canon recovery must retry COMMITTING")
    if task.commit_receipt_ref is not None or task.recovery is not None:
        raise InvalidStateTransition("Canon recovery task references are invalid")
    return replace(
        task,
        status=ChapterTaskStatus.RECOVERY_REQUIRED,
        aggregate_revision=task.aggregate_revision + 1,
        recovery=recovery,
        updated_at=datetime.now(timezone.utc),
    )


def resume_canon_recovery(task: ChapterTask, expected_revision: int) -> ChapterTask:
    """Return a Canon recovery task to COMMITTING, never to COMPLETED."""
    if expected_revision != task.aggregate_revision:
        raise RevisionConflict(
            f"expected revision {expected_revision}, current revision {task.aggregate_revision}"
        )
    if task.status is not ChapterTaskStatus.RECOVERY_REQUIRED or task.recovery is None:
        raise InvalidStateTransition("Canon recovery resume requires RECOVERY_REQUIRED")
    if task.recovery.retry_from_status is not ChapterTaskStatus.COMMITTING:
        raise InvalidStateTransition("Canon recovery must resume COMMITTING")
    if task.commit_receipt_ref is not None:
        raise InvalidStateTransition("recovery task cannot carry a receipt")
    return replace(
        task,
        status=ChapterTaskStatus.COMMITTING,
        last_stable_status=ChapterTaskStatus.COMMITTING,
        aggregate_revision=task.aggregate_revision + 1,
        recovery=None,
        updated_at=datetime.now(timezone.utc),
    )


def complete_verified_canon_recovery(
    task: ChapterTask,
    receipt_ref: ArtifactRef,
    expected_revision: int,
) -> ChapterTask:
    """Complete only a previously verified C4a recovery boundary.

    This transition is deliberately narrower than :func:`transition_task`:
    callers must have already verified the durable Apply facts, receipt
    payload, and target projection.  It accepts only a Canon task currently
    in ``RECOVERY_REQUIRED`` and never provides a generic Task completion
    capability.
    """
    if expected_revision != task.aggregate_revision:
        raise RevisionConflict(
            f"expected revision {expected_revision}, current revision {task.aggregate_revision}"
        )
    if task.status is not ChapterTaskStatus.RECOVERY_REQUIRED or task.recovery is None:
        raise InvalidStateTransition(
            "verified Canon recovery completion requires RECOVERY_REQUIRED"
        )
    if task.recovery.retry_from_status is not ChapterTaskStatus.COMMITTING:
        raise InvalidStateTransition("verified Canon recovery must resume from COMMITTING")
    if task.commit_receipt_ref is not None or not isinstance(receipt_ref, ArtifactRef):
        raise InvalidStateTransition("verified Canon recovery receipt identity is invalid")
    return replace(
        task,
        status=ChapterTaskStatus.COMPLETED,
        last_stable_status=ChapterTaskStatus.COMPLETED,
        aggregate_revision=task.aggregate_revision + 1,
        commit_receipt_ref=receipt_ref,
        recovery=None,
        updated_at=datetime.now(timezone.utc),
    )


# Explicit descriptive alias for callers that use the transaction language
# from ADR-019.  Both names remain the same narrow domain transition.
complete_canon_recovery_with_receipt = complete_verified_canon_recovery


def validate_author_decision(
    decision: AuthorDecision,
    expected_type: DecisionType,
    expected_target_ref: ArtifactRef,
    current_task_revision: int,
) -> None:
    """Validate an immutable author decision without changing task state."""
    if decision.source.kind is not SourceKind.AUTHOR:
        raise InvalidAuthorDecision("decision source must be AUTHOR")
    if decision.source.actor_id != decision.author_id:
        raise InvalidAuthorDecision("source actor_id must match author_id")
    if decision.decision_type is not expected_type:
        raise InvalidAuthorDecision("decision type does not match the expected gate")
    if decision.target_ref != expected_target_ref:
        raise InvalidAuthorDecision("decision target identity, schema, or hash does not match")
    if decision.based_on_task_revision != current_task_revision:
        raise InvalidAuthorDecision("decision is based on a stale task revision")
    expected_outcome = (
        DecisionOutcome.APPROVE if expected_type in _APPROVE_DECISIONS else DecisionOutcome.REJECT
    )
    if expected_type not in _APPROVE_DECISIONS | _REJECT_DECISIONS:
        raise InvalidAuthorDecision("decision type has no outcome semantics")
    if decision.outcome is not expected_outcome:
        raise InvalidAuthorDecision("decision outcome conflicts with decision type semantics")
