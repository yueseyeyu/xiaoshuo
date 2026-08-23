"""C5G0-24--29, 31 and 33: trusted two-phase REVIEW contracts."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Callable

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_creation_application_authoring_artifact import (
    HASH,
    MemoryPayloadStore,
    NoCallsPayloadStore,
    _RaceUow,
    _create_plan_pending_task,
    _create_task,
    _envelope,
    _factory,
    _ids,
    _init_sqlite,
    _race_replay_envelope,
    _submit,
)
from xiaoshuo.application.creation.author_decision import (
    CreateAuthorDecisionUseCase,
)
from xiaoshuo.application.creation.author_decision_transition import (
    ConsumeAuthorDecisionUseCase,
)
from xiaoshuo.application.creation.authoring_artifact import (
    AuthoringArtifactEnvelope,
    AuthoringArtifactInputRejected,
    AuthoringArtifactKind,
    authoring_artifact_content_hash,
    serialize_authoring_artifact_envelope,
)
from xiaoshuo.application.creation.authoring_artifact_context import (
    DraftReviewSubmissionContext,
)
from xiaoshuo.application.creation.commands import (
    ConsumeAuthorDecisionCommand,
    CreateAuthorDecisionCommand,
    SubmitAuthoringArtifactCommand,
    SubmitDraftForReviewCommand,
    TransitionChapterTaskCommand,
)
from xiaoshuo.application.creation.draft_review_submission import (
    SubmitAuthoringArtifactUseCase,
    SubmitDraftForReviewUseCase,
)
from xiaoshuo.application.creation.errors import (
    AuthoringArtifactBindingRejected,
    AuthoringArtifactPayloadPersistenceFailed,
    CreationApplicationError,
    IdempotencyConflict,
)
from xiaoshuo.application.creation.local_author_context import LocalAuthorContextImpl
from xiaoshuo.application.creation.decision_creation_context import DecisionCreationContext
from xiaoshuo.application.creation.operation_kind import OperationKind
from xiaoshuo.application.creation.transition_context import TransitionOperationContext
from xiaoshuo.domain.creation import (
    ArtifactRef,
    ChapterTaskStatus,
    DecisionType,
)
from xiaoshuo.infrastructure.persistence.sqlite.connection import get_connection
from xiaoshuo.infrastructure.persistence.sqlite.uow import SqliteCreationUnitOfWork


def _draft_then_review(
    tmp_path: Path,
    *,
    review_store: MemoryPayloadStore | None = None,
):
    settings = _init_sqlite(tmp_path)
    fixture = _create_task(settings)
    store = review_store or MemoryPayloadStore()
    draft_bytes = _envelope()
    draft_result = SubmitAuthoringArtifactUseCase(
        _factory(settings),
        LocalAuthorContextImpl("author-local"),
        store,
        id_factory=_ids("draft-operation", "draft-artifact", "draft-audit"),
    ).submit(
        SubmitAuthoringArtifactCommand(
            "task-1", fixture.aggregate_revision, draft_bytes
        ),
        # Delivery metadata belongs to the context, not the command.
        __import__(
            "xiaoshuo.application.creation.authoring_artifact_context",
            fromlist=["AuthoringArtifactSubmissionContext"],
        ).AuthoringArtifactSubmissionContext("g0b-draft"),
    )
    review_bytes = serialize_authoring_artifact_envelope(
        AuthoringArtifactEnvelope(
            artifact_kind=AuthoringArtifactKind.REVIEW,
            artifact_schema_version=1,
            project_id="project-1",
            chapter_number=1,
            task_id="task-1",
            body="review body",
            reviewed_draft_ref=draft_result.artifact_ref,
            verdict="PASS",
        )
    )
    review_result = SubmitDraftForReviewUseCase(
        _factory(settings),
        LocalAuthorContextImpl("author-local"),
        store,
        id_factory=_ids("review-operation", "review-artifact", "review-audit"),
    ).submit(
        SubmitDraftForReviewCommand(
            "task-1", draft_result.aggregate_revision, review_bytes
        ),
        DraftReviewSubmissionContext("g0b-review"),
    )
    return settings, store, draft_result, review_result, review_bytes


def _task_row(settings):
    conn = get_connection(settings, read_only=True)
    try:
        return conn.execute("SELECT * FROM chapter_task WHERE task_id = 'task-1'").fetchone()
    finally:
        conn.close()


def _counts(settings) -> dict[str, int]:
    conn = get_connection(settings, read_only=True)
    try:
        return {
            name: conn.execute("SELECT COUNT(*) FROM " + name).fetchone()[0]
            for name in (
                "creation_operation",
                "creation_author_decision",
                "creation_audit_event",
                "creation_artifact_ref",
            )
        }
    finally:
        conn.close()


def test_c5g0_24_plan_gate_uses_existing_state_and_decision_path(tmp_path: Path) -> None:
    settings = _init_sqlite(tmp_path)
    fixture = _create_plan_pending_task(settings)
    plan_bytes = _envelope(AuthoringArtifactKind.PLAN, body="confirmed plan")
    plan_ref = ArtifactRef("plan-1", 1, authoring_artifact_content_hash(plan_bytes))
    decision = CreateAuthorDecisionUseCase(
        _factory(settings),
        LocalAuthorContextImpl("author-local"),
        id_factory=_ids("plan-operation", "plan-decision"),
    ).create(
        CreateAuthorDecisionCommand(
            "task-1", DecisionType.CONFIRM_PLAN, plan_ref, fixture.aggregate_revision
        ),
        DecisionCreationContext("g0b-plan-decision"),
    )
    consumed = ConsumeAuthorDecisionUseCase(
        _factory(settings),
        LocalAuthorContextImpl("author-local"),
        id_factory=_ids("consume-operation", "consume-event", "consume-record"),
    ).consume(
        ConsumeAuthorDecisionCommand(
            "task-1", decision.decision_id, fixture.aggregate_revision
        ),
        TransitionOperationContext("g0b-plan-consume"),
    )
    assert consumed.status is ChapterTaskStatus.DRAFTING
    assert consumed.aggregate_revision == 2


def test_c5g0_25_confirmed_plan_is_task_bound_before_draft(tmp_path: Path) -> None:
    settings = _init_sqlite(tmp_path)
    fixture = _create_plan_pending_task(settings)
    plan_bytes = _envelope(AuthoringArtifactKind.PLAN, body="confirmed plan")
    plan_ref = ArtifactRef("plan-1", 1, authoring_artifact_content_hash(plan_bytes))
    decision = CreateAuthorDecisionUseCase(
        _factory(settings), LocalAuthorContextImpl("author-local"), id_factory=_ids("op", "decision")
    ).create(
        CreateAuthorDecisionCommand(
            "task-1", DecisionType.CONFIRM_PLAN, plan_ref, fixture.aggregate_revision
        ),
        DecisionCreationContext("g0b-plan-bound"),
    )
    ConsumeAuthorDecisionUseCase(
        _factory(settings), LocalAuthorContextImpl("author-local"), id_factory=_ids("cop", "cev", "crec")
    ).consume(
        ConsumeAuthorDecisionCommand(
            "task-1", decision.decision_id, fixture.aggregate_revision
        ),
        TransitionOperationContext("g0b-plan-bound-consume"),
    )
    row = _task_row(settings)
    assert row["status"] == ChapterTaskStatus.DRAFTING.value
    assert row["confirmed_plan_ref_artifact_id"] == "plan-1"
    assert row["aggregate_revision"] == 2

    missing_root = tmp_path / "missing-confirmed-plan"
    missing_root.mkdir()
    missing_settings = _init_sqlite(missing_root)
    missing_fixture = _create_task(missing_settings, with_confirmed_plan=False)
    missing_store = MemoryPayloadStore()
    baseline = _counts(missing_settings)
    with pytest.raises(AuthoringArtifactBindingRejected):
        SubmitAuthoringArtifactUseCase(
            _factory(missing_settings),
            LocalAuthorContextImpl("author-local"),
            missing_store,
            id_factory=_ids("missing-op", "missing-ref", "missing-audit"),
        ).submit(
            SubmitAuthoringArtifactCommand(
                "task-1", missing_fixture.aggregate_revision, _envelope()
            ),
            __import__(
                "xiaoshuo.application.creation.authoring_artifact_context",
                fromlist=["AuthoringArtifactSubmissionContext"],
            ).AuthoringArtifactSubmissionContext("g0b-25-missing-plan"),
        )
    assert missing_store.put_calls == []
    assert missing_store.read_calls == []
    assert _counts(missing_settings) == baseline
    missing_row = _task_row(missing_settings)
    assert missing_row["status"] == ChapterTaskStatus.DRAFTING.value
    assert missing_row["aggregate_revision"] == 2
    assert missing_row["confirmed_plan_ref_artifact_id"] is None


def test_c5g0_26_draft_uow_writes_both_role_refs_audit_and_reviewing(tmp_path: Path) -> None:
    settings = _init_sqlite(tmp_path)
    fixture = _create_task(settings)
    store = MemoryPayloadStore()
    result = SubmitAuthoringArtifactUseCase(
        _factory(settings), LocalAuthorContextImpl("author-local"), store,
        id_factory=_ids("draft-op", "draft-ref", "draft-audit"),
    ).submit(
        SubmitAuthoringArtifactCommand("task-1", fixture.aggregate_revision, _envelope()),
        __import__(
            "xiaoshuo.application.creation.authoring_artifact_context",
            fromlist=["AuthoringArtifactSubmissionContext"],
        ).AuthoringArtifactSubmissionContext("g0b-26"),
    )
    row = _task_row(settings)
    assert row["status"] == ChapterTaskStatus.REVIEWING.value
    assert row["current_author_draft_ref_artifact_id"] == result.artifact_ref.artifact_id
    assert row["review_target_draft_ref_artifact_id"] == result.artifact_ref.artifact_id
    conn = get_connection(settings, read_only=True)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM creation_audit_event WHERE event_type = ?",
            ("AUTHORING_DRAFT_SUBMITTED",),
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_c5g0_27_review_pass_uow_writes_latest_ref_audit_and_gate(tmp_path: Path) -> None:
    settings, store, _draft, review, _review_bytes = _draft_then_review(tmp_path)
    row = _task_row(settings)
    assert row["status"] == ChapterTaskStatus.DRAFT_APPROVAL_PENDING.value
    assert row["latest_review_ref_artifact_id"] == review.artifact_ref.artifact_id
    conn = get_connection(settings, read_only=True)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM creation_audit_event WHERE event_type = ?",
            ("DRAFT_REVIEW_SUBMITTED",),
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_c5g0_28_review_cross_checks_both_trusted_refs_and_payload(tmp_path: Path) -> None:
    settings = _init_sqlite(tmp_path)
    fixture = _create_task(settings)
    store = MemoryPayloadStore()
    draft = SubmitAuthoringArtifactUseCase(
        _factory(settings), LocalAuthorContextImpl("author-local"), store,
        id_factory=_ids("dop", "dref", "daudit"),
    ).submit(
        SubmitAuthoringArtifactCommand("task-1", fixture.aggregate_revision, _envelope()),
        __import__(
            "xiaoshuo.application.creation.authoring_artifact_context",
            fromlist=["AuthoringArtifactSubmissionContext"],
        ).AuthoringArtifactSubmissionContext("g0b-28-draft"),
    )
    wrong = ArtifactRef("wrong", 1, HASH)
    review = serialize_authoring_artifact_envelope(
        AuthoringArtifactEnvelope(
            AuthoringArtifactKind.REVIEW, 1, "project-1", 1, "task-1", "review",
            reviewed_draft_ref=wrong, verdict="PASS",
        )
    )
    baseline = _counts(settings)
    with pytest.raises(AuthoringArtifactBindingRejected):
        SubmitDraftForReviewUseCase(
            _factory(settings), LocalAuthorContextImpl("author-local"), store,
            id_factory=_ids("rop", "rref", "raudit"),
        ).submit(
            SubmitDraftForReviewCommand("task-1", 3, review),
            DraftReviewSubmissionContext("g0b-28-wrong-ref"),
        )
    assert _counts(settings) == baseline
    store.objects[draft.artifact_ref.content_hash] = b"tampered"
    trusted_review = serialize_authoring_artifact_envelope(
        AuthoringArtifactEnvelope(
            AuthoringArtifactKind.REVIEW, 1, "project-1", 1, "task-1", "review",
            reviewed_draft_ref=draft.artifact_ref, verdict="PASS",
        )
    )
    with pytest.raises((AuthoringArtifactBindingRejected, AuthoringArtifactPayloadPersistenceFailed)):
        SubmitDraftForReviewUseCase(
            _factory(settings), LocalAuthorContextImpl("author-local"), store,
            id_factory=_ids("rop2", "rref2", "raudit2"),
        ).submit(
            SubmitDraftForReviewCommand("task-1", 3, trusted_review),
            DraftReviewSubmissionContext("g0b-28-tampered"),
        )
    assert _counts(settings) == baseline


def test_c5g0_29_only_trusted_review_target_is_available_for_future_adoption(tmp_path: Path) -> None:
    settings, _store, draft, review, _review_bytes = _draft_then_review(tmp_path)
    row = _task_row(settings)
    assert row["review_target_draft_ref_artifact_id"] == draft.artifact_ref.artifact_id
    assert row["latest_review_ref_artifact_id"] == review.artifact_ref.artifact_id
    source = Path(__file__).resolve().parents[1] / "src" / "xiaoshuo" / "application" / "creation" / "draft_review_submission.py"
    assert "ADOPT_DRAFT" not in source.read_text(encoding="utf-8")


def test_c5g0_31_review_failures_are_fail_closed_without_cleanup_or_sql_bypass(tmp_path: Path) -> None:
    settings, store, draft, _review, _review_bytes = _draft_then_review(tmp_path)
    # A second request with a syntactically valid but non-PASS REVIEW fails in
    # the application parser before Task/payload/business writes.
    non_pass = serialize_authoring_artifact_envelope.__name__
    del non_pass
    data = {
        "artifact_kind": "REVIEW",
        "artifact_schema_version": 1,
        "project_id": "project-1",
        "chapter_number": 1,
        "task_id": "task-1",
        "body": "review",
        "reviewed_draft_ref": {
            "artifact_id": draft.artifact_ref.artifact_id,
            "schema_version": 1,
            "content_hash": draft.artifact_ref.content_hash,
        },
        "verdict": "REVISE",
    }
    import json

    baseline = _counts(settings)
    with pytest.raises(AuthoringArtifactInputRejected):
        SubmitDraftForReviewUseCase(
            _factory(settings), LocalAuthorContextImpl("author-local"), store,
            id_factory=_ids("never", "never", "never"),
        ).submit(
            SubmitDraftForReviewCommand("task-1", 3, json.dumps(data, sort_keys=True, separators=(",", ":")).encode()),
            DraftReviewSubmissionContext("g0b-31-invalid"),
        )
    assert _counts(settings) == baseline


def test_c5g0_32_review_replay_and_conflict_do_not_duplicate_facts(tmp_path: Path) -> None:
    settings, store, draft, _review, _review_bytes = _draft_then_review(tmp_path)
    baseline = _counts(settings)
    # REVIEW replay is checked with a fresh store that cannot perform I/O; the
    # original operation is already committed and is returned from the ledger.
    review_bytes = _review_bytes
    replay_store = MemoryPayloadStore()
    replay_store.put = lambda data: (_ for _ in ()).throw(AssertionError("replay put"))  # type: ignore[method-assign]
    replay_store.read = lambda digest: (_ for _ in ()).throw(AssertionError("replay read"))  # type: ignore[method-assign]
    result = SubmitDraftForReviewUseCase(
        _factory(settings), LocalAuthorContextImpl("author-local"), replay_store,
        id_factory=_ids(),
    ).submit(
        SubmitDraftForReviewCommand("task-1", 3, review_bytes),
        DraftReviewSubmissionContext("g0b-review"),
    )
    assert result.artifact_ref.artifact_id == "review-artifact"
    assert _counts(settings) == baseline
    with pytest.raises(IdempotencyConflict):
        SubmitDraftForReviewUseCase(
            _factory(settings), LocalAuthorContextImpl("author-local"), replay_store,
            id_factory=_ids(),
        ).submit(
            SubmitDraftForReviewCommand("task-1", 3, review_bytes.replace(b"review body", b"other body")),
            DraftReviewSubmissionContext("g0b-review"),
        )


def test_c5g0_32_review_atomic_race_loser_replay_has_zero_side_effects(
    tmp_path: Path,
) -> None:
    settings = _init_sqlite(tmp_path)
    replay_envelope = _race_replay_envelope(
        artifact_kind=AuthoringArtifactKind.REVIEW,
        artifact_id="winner-review",
        revision=4,
        status=ChapterTaskStatus.DRAFT_APPROVAL_PENDING,
        operation_kind=OperationKind.SUBMIT_DRAFT_FOR_REVIEW,
    )
    uow = _RaceUow(replay_envelope)
    review_bytes = _envelope(
        AuthoringArtifactKind.REVIEW,
        ref=ArtifactRef("winner-draft", 1, HASH),
    )
    result = SubmitDraftForReviewUseCase(
        lambda: uow,
        LocalAuthorContextImpl("author-local"),
        NoCallsPayloadStore(),
        id_factory=_ids("candidate-operation", "candidate-ref", "candidate-audit"),
    ).submit(
        SubmitDraftForReviewCommand("task-1", 3, review_bytes),
        DraftReviewSubmissionContext("g0b-review-race"),
    )
    assert result.artifact_ref.artifact_id == "winner-review"
    assert uow.operations.create_calls == 1
    assert uow.tasks.get_calls == 0
    assert uow.tasks.replace_calls == 0
    assert uow.audit.add_calls == 0
    assert uow.commit_calls == 0
    assert uow.rollback_calls == 1
    assert uow.close_calls == 1
    assert uow.persisted_business_facts == []


def test_c5g0_33_raw_bytes_are_external_to_operation_audit_and_business_columns(tmp_path: Path) -> None:
    settings, _store, _draft, _review, review_bytes = _draft_then_review(tmp_path)
    raw = "review body"
    conn = get_connection(settings, read_only=True)
    try:
        for table in (
            "creation_operation",
            "creation_audit_event",
            "chapter_task",
            "creation_author_decision",
        ):
            rows = conn.execute("SELECT * FROM " + table).fetchall()
            assert raw not in repr(rows)
        assert review_bytes.decode("utf-8") not in repr(
            conn.execute("SELECT * FROM creation_operation").fetchall()
        )
    finally:
        conn.close()


def test_g0b_corr_12_draft_commit_success_close_failure_is_not_rolled_back(
    tmp_path: Path,
) -> None:
    settings = _init_sqlite(tmp_path)
    fixture = _create_task(settings)
    envelope = _envelope()
    store = MemoryPayloadStore()
    uow = SqliteCreationUnitOfWork(get_connection(settings))
    close_error = OSError("draft close failed")
    close_calls = [0]
    rollback_calls = [0]

    def fail_close() -> None:
        close_calls[0] += 1
        raise close_error

    original_rollback = uow.rollback

    def counted_rollback() -> None:
        rollback_calls[0] += 1
        original_rollback()

    uow.close = fail_close  # type: ignore[method-assign]
    uow.rollback = counted_rollback  # type: ignore[method-assign]
    with pytest.raises(CreationApplicationError) as exc_info:
        _submit(
            settings,
            store,
            envelope,
            "g0b-corr-12",
            expected_revision=fixture.aggregate_revision,
            uow_factory=lambda: uow,
        )
    assert exc_info.value.__cause__ is close_error
    assert close_calls == [1]
    assert rollback_calls == [0]

    replay = _submit(
        settings,
        NoCallsPayloadStore(),
        envelope,
        "g0b-corr-12",
        expected_revision=fixture.aggregate_revision,
        id_factory=_ids(),
    )
    assert replay.artifact_ref.artifact_id == "draft-1"


def test_g0b_corr_13_review_commit_success_close_failure_is_not_rolled_back(
    tmp_path: Path,
) -> None:
    settings = _init_sqlite(tmp_path)
    fixture = _create_task(settings)
    store = MemoryPayloadStore()
    draft = _submit(
        settings,
        store,
        _envelope(),
        "g0b-corr-13-draft",
        expected_revision=fixture.aggregate_revision,
        id_factory=_ids("draft-operation", "draft-artifact", "draft-audit"),
    )
    review = _envelope(
        AuthoringArtifactKind.REVIEW,
        ref=draft.artifact_ref,
    )
    uow = SqliteCreationUnitOfWork(get_connection(settings))
    close_error = OSError("review close failed")
    close_calls = [0]
    rollback_calls = [0]

    def fail_close() -> None:
        close_calls[0] += 1
        raise close_error

    original_rollback = uow.rollback

    def counted_rollback() -> None:
        rollback_calls[0] += 1
        original_rollback()

    uow.close = fail_close  # type: ignore[method-assign]
    uow.rollback = counted_rollback  # type: ignore[method-assign]
    with pytest.raises(CreationApplicationError) as exc_info:
        SubmitDraftForReviewUseCase(
            lambda: uow,
            LocalAuthorContextImpl("author-local"),
            store,
            id_factory=_ids("review-operation", "review-artifact", "review-audit"),
        ).submit(
            SubmitDraftForReviewCommand("task-1", 3, review),
            DraftReviewSubmissionContext("g0b-corr-13"),
        )
    assert exc_info.value.__cause__ is close_error
    assert close_calls == [1]
    assert rollback_calls == [0]

    replay = SubmitDraftForReviewUseCase(
        _factory(settings),
        LocalAuthorContextImpl("author-local"),
        NoCallsPayloadStore(),
        id_factory=_ids(),
    ).submit(
        SubmitDraftForReviewCommand("task-1", 3, review),
        DraftReviewSubmissionContext("g0b-corr-13"),
    )
    assert replay.artifact_ref.artifact_id == "review-artifact"
