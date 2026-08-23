"""Guard tests for application-layer creation persistence boundary.

Verifies that pure application guards correctly reject COMMITTING,
COMPLETED, non-null commit_receipt_ref, and out-of-boundary recovery
retry targets.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from xiaoshuo.domain.creation.models import (
    ArtifactRef,
    ChapterTask,
    ChapterTaskStatus,
    RecoveryInfo,
)

from xiaoshuo.application.creation.errors import UnsupportedPersistenceBoundary
from xiaoshuo.application.creation.guards import (
    guard_committing_not_completed,
    guard_persistence_target,
    guard_recovery_retry_boundary,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
HASH_A = "sha256:" + "a" * 64


# ---------------------------------------------------------------------------
# Helpers — minimal ChapterTask builders
# ---------------------------------------------------------------------------

def _ref(artifact_id: str = "artifact-1") -> ArtifactRef:
    return ArtifactRef(artifact_id, 1, HASH_A)


def _task(
    *,
    status: ChapterTaskStatus = ChapterTaskStatus.DRAFTING,
    commit_receipt_ref: ArtifactRef | None = None,
    recovery: RecoveryInfo | None = None,
    last_stable_status: ChapterTaskStatus | None = None,
) -> ChapterTask:
    return ChapterTask(
        task_id="task-1",
        schema_version=1,
        aggregate_revision=0,
        project_id="project-1",
        chapter_number=1,
        status=status,
        last_stable_status=last_stable_status or status,
        creative_intent_ref=_ref("intent-1"),
        confirmed_plan_ref=None,
        current_author_draft_ref=None,
        review_target_draft_ref=None,
        adopted_draft_ref=None,
        latest_review_ref=None,
        pending_changeset_ref=None,
        commit_receipt_ref=commit_receipt_ref,
        recovery=recovery,
        created_at=NOW,
        updated_at=NOW,
    )


def _recovery(retry_from_status: ChapterTaskStatus) -> RecoveryInfo:
    return RecoveryInfo(
        failed_operation_id="op-1",
        error_code="TEST_ERROR",
        retry_from_status=retry_from_status,
    )


# ---------------------------------------------------------------------------
# guard_persistence_target
# ---------------------------------------------------------------------------

class TestGuardPersistenceTarget:
    @pytest.mark.parametrize(
        "bad_status",
        [ChapterTaskStatus.COMMITTING, ChapterTaskStatus.COMPLETED],
        ids=["COMMITTING", "COMPLETED"],
    )
    def test_rejects_forbidden_targets(self, bad_status: ChapterTaskStatus) -> None:
        with pytest.raises(UnsupportedPersistenceBoundary):
            guard_persistence_target(bad_status)

    @pytest.mark.parametrize(
        "good_status",
        [
            ChapterTaskStatus.PLAN_PREPARING,
            ChapterTaskStatus.PLAN_APPROVAL_PENDING,
            ChapterTaskStatus.DRAFTING,
            ChapterTaskStatus.REVIEWING,
            ChapterTaskStatus.REVISION_REQUIRED,
            ChapterTaskStatus.DRAFT_APPROVAL_PENDING,
            ChapterTaskStatus.CHANGESET_PREPARING,
            ChapterTaskStatus.CHANGESET_APPROVAL_PENDING,
            ChapterTaskStatus.RECOVERY_REQUIRED,
            ChapterTaskStatus.CANCELLED,
        ],
    )
    def test_allows_non_forbidden_targets(self, good_status: ChapterTaskStatus) -> None:
        # Should not raise
        guard_persistence_target(good_status)

    def test_error_message_contains_status(self) -> None:
        with pytest.raises(UnsupportedPersistenceBoundary, match="COMMITTING"):
            guard_persistence_target(ChapterTaskStatus.COMMITTING)

    def test_error_is_non_retryable(self) -> None:
        """UnsupportedPersistenceBoundary is not a retryable error type."""
        with pytest.raises(UnsupportedPersistenceBoundary):
            guard_persistence_target(ChapterTaskStatus.COMPLETED)


# ---------------------------------------------------------------------------
# guard_committing_not_completed
# ---------------------------------------------------------------------------

class TestGuardCommittingNotCompleted:
    def test_raises_when_commit_receipt_ref_is_non_null(self) -> None:
        # Domain invariant: non-null commit_receipt_ref requires COMPLETED.
        task = _task(
            status=ChapterTaskStatus.COMPLETED,
            commit_receipt_ref=_ref("receipt-1"),
        )
        with pytest.raises(UnsupportedPersistenceBoundary):
            guard_committing_not_completed(task)

    def test_passes_when_commit_receipt_ref_is_none(self) -> None:
        task = _task(commit_receipt_ref=None)
        guard_committing_not_completed(task)  # must not raise

    def test_error_message_describes_boundary(self) -> None:
        task = _task(
            status=ChapterTaskStatus.COMPLETED,
            commit_receipt_ref=_ref("rcpt"),
        )
        with pytest.raises(UnsupportedPersistenceBoundary, match="commit_receipt_ref"):
            guard_committing_not_completed(task)


# ---------------------------------------------------------------------------
# guard_recovery_retry_boundary
# ---------------------------------------------------------------------------

class TestGuardRecoveryRetryBoundary:
    @pytest.mark.parametrize(
        "bad_retry",
        [ChapterTaskStatus.COMMITTING, ChapterTaskStatus.COMPLETED],
        ids=["retry=COMMITTING", "retry=COMPLETED"],
    )
    def test_rejects_forbidden_retry_target(self, bad_retry: ChapterTaskStatus) -> None:
        rec = _recovery(bad_retry)
        with pytest.raises(UnsupportedPersistenceBoundary):
            guard_recovery_retry_boundary(rec)

    @pytest.mark.parametrize(
        "good_retry",
        [
            ChapterTaskStatus.PLAN_PREPARING,
            ChapterTaskStatus.DRAFTING,
            ChapterTaskStatus.REVIEWING,
            ChapterTaskStatus.CHANGESET_APPROVAL_PENDING,
            ChapterTaskStatus.CANCELLED,
        ],
    )
    def test_allows_non_forbidden_retry_targets(self, good_retry: ChapterTaskStatus) -> None:
        rec = _recovery(good_retry)
        guard_recovery_retry_boundary(rec)  # must not raise

    def test_error_message_contains_retry_status(self) -> None:
        rec = _recovery(ChapterTaskStatus.COMPLETED)
        with pytest.raises(UnsupportedPersistenceBoundary, match="COMPLETED"):
            guard_recovery_retry_boundary(rec)
