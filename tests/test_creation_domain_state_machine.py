from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from xiaoshuo.domain.creation.hashing import InvalidDomainValue, compute_content_hash
from xiaoshuo.domain.creation.models import (
    ArtifactRef,
    AuthorDecision,
    ChapterTask,
    ChapterTaskStatus,
    DecisionOutcome,
    DecisionType,
    RecoveryInfo,
    SourceKind,
    SourceRef,
)
from xiaoshuo.domain.creation.state_machine import (
    InvalidAuthorDecision,
    InvalidStateTransition,
    RevisionConflict,
    can_transition,
    complete_task_with_receipt,
    enter_canon_recovery,
    resume_canon_recovery,
    transition_task,
    validate_author_decision,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def ref(artifact_id: str = "artifact-1", content_hash: str = HASH_A) -> ArtifactRef:
    return ArtifactRef(artifact_id, 1, content_hash)


def task(status: ChapterTaskStatus, revision: int = 0, **overrides: object) -> ChapterTask:
    values: dict[str, object] = {
        "task_id": "task-1",
        "schema_version": 1,
        "aggregate_revision": revision,
        "project_id": "project-1",
        "chapter_number": 1,
        "status": status,
        "last_stable_status": status,
        "creative_intent_ref": ref("intent-1"),
        "confirmed_plan_ref": None,
        "current_author_draft_ref": None,
        "review_target_draft_ref": None,
        "adopted_draft_ref": None,
        "latest_review_ref": None,
        "pending_changeset_ref": None,
        "commit_receipt_ref": None,
        "recovery": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return ChapterTask(**values)  # type: ignore[arg-type]


DIRECT_TRANSITIONS = [
    (ChapterTaskStatus.PLAN_PREPARING, ChapterTaskStatus.PLAN_APPROVAL_PENDING),
    (ChapterTaskStatus.PLAN_APPROVAL_PENDING, ChapterTaskStatus.DRAFTING),
    (ChapterTaskStatus.DRAFTING, ChapterTaskStatus.REVIEWING),
    (ChapterTaskStatus.REVIEWING, ChapterTaskStatus.REVISION_REQUIRED),
    (ChapterTaskStatus.REVIEWING, ChapterTaskStatus.DRAFT_APPROVAL_PENDING),
    (ChapterTaskStatus.REVISION_REQUIRED, ChapterTaskStatus.DRAFTING),
    (ChapterTaskStatus.DRAFT_APPROVAL_PENDING, ChapterTaskStatus.DRAFTING),
    (ChapterTaskStatus.DRAFT_APPROVAL_PENDING, ChapterTaskStatus.CHANGESET_PREPARING),
    (ChapterTaskStatus.CHANGESET_PREPARING, ChapterTaskStatus.CHANGESET_APPROVAL_PENDING),
    (ChapterTaskStatus.CHANGESET_APPROVAL_PENDING, ChapterTaskStatus.CHANGESET_PREPARING),
    (ChapterTaskStatus.CHANGESET_APPROVAL_PENDING, ChapterTaskStatus.COMMITTING),
]


@pytest.mark.parametrize(("current", "target"), DIRECT_TRANSITIONS)
def test_each_direct_transition_returns_new_revision(
    current: ChapterTaskStatus, target: ChapterTaskStatus
) -> None:
    original = task(current, revision=4)
    transitioned = transition_task(original, target, expected_revision=4)
    assert transitioned is not original
    assert transitioned.status is target
    assert transitioned.aggregate_revision == 5
    assert transitioned.last_stable_status is target
    assert transitioned.updated_at >= original.updated_at
    assert original.status is current
    assert original.aggregate_revision == 4


def test_committing_to_completed_is_a_legal_adjacency() -> None:
    assert can_transition(ChapterTaskStatus.COMMITTING, ChapterTaskStatus.COMPLETED)


def test_committing_to_completed_requires_atomic_receipt_attachment() -> None:
    with pytest.raises(InvalidStateTransition):
        transition_task(
            task(ChapterTaskStatus.COMMITTING),
            ChapterTaskStatus.COMPLETED,
            expected_revision=0,
        )


def test_p37_complete_task_with_receipt_constructs_terminal_task_once() -> None:
    completed = complete_task_with_receipt(task(ChapterTaskStatus.COMMITTING), ref("receipt"), 0)
    assert completed.status is ChapterTaskStatus.COMPLETED
    assert completed.commit_receipt_ref == ref("receipt")
    assert completed.aggregate_revision == 1


def test_p38_completion_rejects_wrong_status_revision_or_existing_receipt() -> None:
    with pytest.raises(RevisionConflict):
        complete_task_with_receipt(task(ChapterTaskStatus.COMMITTING, revision=2), ref("receipt"), 1)
    with pytest.raises(InvalidStateTransition):
        complete_task_with_receipt(task(ChapterTaskStatus.DRAFTING), ref("receipt"), 0)


def test_p39_canon_recovery_only_round_trips_committing() -> None:
    failed = enter_canon_recovery(
        task(ChapterTaskStatus.COMMITTING),
        0,
        RecoveryInfo("failed", "CANON_APPLY_FAILED", ChapterTaskStatus.COMMITTING),
    )
    assert failed.status is ChapterTaskStatus.RECOVERY_REQUIRED
    resumed = resume_canon_recovery(failed, 1)
    assert resumed.status is ChapterTaskStatus.COMMITTING
    assert resumed.recovery is None
    with pytest.raises(InvalidStateTransition):
        complete_task_with_receipt(failed, ref("receipt"), 1)


def test_recovery_adjacency_excludes_terminal_and_recovery_targets() -> None:
    assert can_transition(ChapterTaskStatus.RECOVERY_REQUIRED, ChapterTaskStatus.DRAFTING)
    assert not can_transition(ChapterTaskStatus.RECOVERY_REQUIRED, ChapterTaskStatus.COMPLETED)
    assert not can_transition(ChapterTaskStatus.RECOVERY_REQUIRED, ChapterTaskStatus.CANCELLED)
    assert not can_transition(
        ChapterTaskStatus.RECOVERY_REQUIRED, ChapterTaskStatus.RECOVERY_REQUIRED
    )


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ChapterTaskStatus.PLAN_PREPARING, ChapterTaskStatus.REVIEWING),
        (ChapterTaskStatus.DRAFTING, ChapterTaskStatus.COMMITTING),
        (ChapterTaskStatus.REVIEWING, ChapterTaskStatus.CHANGESET_PREPARING),
    ],
)
def test_representative_illegal_jumps_fail(
    current: ChapterTaskStatus, target: ChapterTaskStatus
) -> None:
    with pytest.raises(InvalidStateTransition):
        transition_task(task(current), target, expected_revision=0)


@pytest.mark.parametrize("terminal", [ChapterTaskStatus.COMPLETED, ChapterTaskStatus.CANCELLED])
def test_terminal_statuses_cannot_transition(terminal: ChapterTaskStatus) -> None:
    current = (
        task(terminal, commit_receipt_ref=ref("receipt-1"))
        if terminal is ChapterTaskStatus.COMPLETED
        else task(terminal)
    )
    with pytest.raises(InvalidStateTransition):
        transition_task(current, ChapterTaskStatus.DRAFTING, expected_revision=0)


def test_cancellation_rules() -> None:
    cancelled = transition_task(
        task(ChapterTaskStatus.DRAFTING), ChapterTaskStatus.CANCELLED, expected_revision=0
    )
    assert cancelled.status is ChapterTaskStatus.CANCELLED
    with pytest.raises(InvalidStateTransition):
        transition_task(
            task(ChapterTaskStatus.COMMITTING),
            ChapterTaskStatus.CANCELLED,
            expected_revision=0,
        )


def test_revision_conflict_prevents_transition() -> None:
    with pytest.raises(RevisionConflict):
        transition_task(
            task(ChapterTaskStatus.DRAFTING, revision=2),
            ChapterTaskStatus.REVIEWING,
            expected_revision=1,
        )


def test_entering_recovery_requires_matching_recovery_information() -> None:
    current = task(ChapterTaskStatus.DRAFTING)
    with pytest.raises(InvalidStateTransition):
        transition_task(current, ChapterTaskStatus.RECOVERY_REQUIRED, expected_revision=0)
    with pytest.raises(InvalidStateTransition):
        transition_task(
            current,
            ChapterTaskStatus.RECOVERY_REQUIRED,
            expected_revision=0,
            recovery=RecoveryInfo(
                "operation-1", "TIMEOUT", ChapterTaskStatus.PLAN_PREPARING
            ),
        )
    recovery = RecoveryInfo("operation-1", "TIMEOUT", ChapterTaskStatus.DRAFTING)
    failed = transition_task(
        current,
        ChapterTaskStatus.RECOVERY_REQUIRED,
        expected_revision=0,
        recovery=recovery,
    )
    assert failed.status is ChapterTaskStatus.RECOVERY_REQUIRED
    assert failed.recovery is recovery
    assert failed.last_stable_status is ChapterTaskStatus.DRAFTING


def test_recovery_only_returns_to_retry_status_and_clears_information() -> None:
    recovery = RecoveryInfo("operation-1", "TIMEOUT", ChapterTaskStatus.DRAFTING)
    failed = task(
        ChapterTaskStatus.RECOVERY_REQUIRED,
        revision=3,
        last_stable_status=ChapterTaskStatus.DRAFTING,
        recovery=recovery,
    )
    with pytest.raises(InvalidStateTransition):
        transition_task(failed, ChapterTaskStatus.REVIEWING, expected_revision=3)
    recovered = transition_task(failed, ChapterTaskStatus.DRAFTING, expected_revision=3)
    assert recovered.recovery is None
    assert recovered.aggregate_revision == 4
    assert recovered.status is ChapterTaskStatus.DRAFTING


def test_business_revision_is_not_encoded_as_recovery() -> None:
    reviewed = transition_task(
        task(ChapterTaskStatus.REVIEWING),
        ChapterTaskStatus.REVISION_REQUIRED,
        expected_revision=0,
    )
    assert reviewed.status is ChapterTaskStatus.REVISION_REQUIRED
    assert reviewed.recovery is None


def decision(
    decision_type: DecisionType = DecisionType.CONFIRM_PLAN,
    outcome: DecisionOutcome = DecisionOutcome.APPROVE,
    target: ArtifactRef | None = None,
    revision: int = 2,
) -> AuthorDecision:
    source = SourceRef(SourceKind.AUTHOR, actor_id="author-1")
    values: dict[str, object] = {
        "decision_id": "decision-1",
        "schema_version": 1,
        "task_id": "task-1",
        "decision_type": decision_type,
        "target_ref": target or ref("plan-1"),
        "outcome": outcome,
        "based_on_task_revision": revision,
        "author_id": "author-1",
        "reason": None,
        "source": source,
        "created_at": NOW,
    }
    values["content_hash"] = compute_content_hash(
        {key: value for key, value in values.items() if key != "created_at"}
    )
    return AuthorDecision(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("decision_type", "outcome"),
    [
        (DecisionType.CONFIRM_PLAN, DecisionOutcome.APPROVE),
        (DecisionType.ADOPT_DRAFT, DecisionOutcome.APPROVE),
        (DecisionType.APPROVE_CHANGESET, DecisionOutcome.APPROVE),
        (DecisionType.CONFIRM_NO_CANON_CHANGE, DecisionOutcome.APPROVE),
        (DecisionType.REJECT_PLAN, DecisionOutcome.REJECT),
        (DecisionType.REJECT_DRAFT, DecisionOutcome.REJECT),
        (DecisionType.REJECT_CHANGESET, DecisionOutcome.REJECT),
        (DecisionType.CANCEL_TASK, DecisionOutcome.REJECT),
    ],
)
def test_valid_author_decision_semantics(
    decision_type: DecisionType, outcome: DecisionOutcome
) -> None:
    expected = ref("target-1")
    validate_author_decision(
        decision(decision_type, outcome, expected),
        decision_type,
        expected,
        current_task_revision=2,
    )


def test_author_decision_type_target_hash_and_revision_must_match() -> None:
    expected = ref("plan-1", HASH_A)
    with pytest.raises(InvalidAuthorDecision):
        validate_author_decision(
            decision(), DecisionType.ADOPT_DRAFT, expected, current_task_revision=2
        )
    with pytest.raises(InvalidAuthorDecision):
        validate_author_decision(
            decision(target=ref("other", HASH_A)),
            DecisionType.CONFIRM_PLAN,
            expected,
            current_task_revision=2,
        )
    with pytest.raises(InvalidAuthorDecision):
        validate_author_decision(
            decision(target=ref("plan-1", HASH_B)),
            DecisionType.CONFIRM_PLAN,
            expected,
            current_task_revision=2,
        )
    with pytest.raises(InvalidAuthorDecision):
        validate_author_decision(
            decision(revision=1),
            DecisionType.CONFIRM_PLAN,
            expected,
            current_task_revision=2,
        )


@pytest.mark.parametrize(
    ("decision_type", "wrong_outcome"),
    [
        (DecisionType.CONFIRM_PLAN, DecisionOutcome.REJECT),
        (DecisionType.REJECT_DRAFT, DecisionOutcome.APPROVE),
    ],
)
def test_author_decision_outcome_must_match_semantics(
    decision_type: DecisionType, wrong_outcome: DecisionOutcome
) -> None:
    expected = ref("target-1")
    with pytest.raises(InvalidAuthorDecision):
        validate_author_decision(
            decision(decision_type, wrong_outcome, expected),
            decision_type,
            expected,
            current_task_revision=2,
        )


def test_invalid_author_provenance_is_rejected_at_object_boundary() -> None:
    valid = decision()
    with pytest.raises(InvalidDomainValue):
        replace(valid, source=SourceRef(SourceKind.MODEL, model_run_id="run-1"))
    with pytest.raises(InvalidDomainValue):
        replace(valid, author_id="author-2")
