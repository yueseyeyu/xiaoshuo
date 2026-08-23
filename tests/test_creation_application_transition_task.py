"""TransitionChapterTask use case tests (B2a).

Covers the full 26-item test matrix:
T01-T26 including success, replay, conflict, revision conflict zero
residue, illegal transitions, AuthorDecision bypass rejection, recovery
boundary, object_refs order, UoW close, real SQLite PK/replace conflicts,
ledger key verification, and role artifact ref invariance.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from xiaoshuo.application.creation.commands import (
    CreateChapterTaskCommand,
    TransitionChapterTaskCommand,
)
from xiaoshuo.application.creation.create_task import CreateChapterTaskUseCase
from xiaoshuo.application.creation.digest import (
    compute_envelope_hash,
    compute_transition_request_digest,
    create_transition_result_envelope,
    result_from_transition_envelope,
)
from xiaoshuo.application.creation.errors import (
    CreationApplicationError,
    IdempotencyConflict,
    NotFound,
    UnsupportedPersistenceBoundary,
)
from xiaoshuo.application.creation.operation_kind import OperationKind
from xiaoshuo.application.creation.repository import (
    OperationCreateOutcome,
    OperationLogRecord,
    OperationResult,
)
from xiaoshuo.application.creation.results import TransitionChapterTaskResult
from xiaoshuo.application.creation.transition_context import TransitionOperationContext
from xiaoshuo.application.creation.transition_task import TransitionChapterTaskUseCase
from xiaoshuo.domain.creation import (
    ArtifactRef,
    ChapterTask,
    ChapterTaskStatus,
    RecoveryInfo,
    SCHEMA_VERSION,
    SourceKind,
    SourceRef,
)
from xiaoshuo.domain.creation.state_machine import (
    RevisionConflict as DomainRevisionConflict,
)
from xiaoshuo.infrastructure.persistence.sqlite.connection import get_connection
from xiaoshuo.infrastructure.persistence.sqlite.maintenance import init_database
from xiaoshuo.infrastructure.persistence.sqlite.migration_runner import MigrationRunner
from xiaoshuo.infrastructure.persistence.sqlite.settings import SQLitePersistenceSettings
from xiaoshuo.infrastructure.persistence.sqlite.uow import SqliteCreationUnitOfWork

HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ref(artifact_id: str = "artifact-1") -> ArtifactRef:
    return ArtifactRef(artifact_id, 1, HASH_A)


def _make_revision_required_task(
    task_id: str = "task-1",
    *,
    project_id: str = "project-1",
    chapter_number: int = 1,
    creative_intent: ArtifactRef | None = None,
    confirmed_plan: ArtifactRef | None = None,
    author_draft: ArtifactRef | None = None,
    review_target: ArtifactRef | None = None,
    adopted: ArtifactRef | None = None,
    latest_review: ArtifactRef | None = None,
    pending_changeset: ArtifactRef | None = None,
    revision: int = 3,
) -> ChapterTask:
    ci = creative_intent or _ref(f"intent-{task_id}")
    now = datetime.now(timezone.utc)
    return ChapterTask(
        task_id=task_id,
        schema_version=SCHEMA_VERSION,
        aggregate_revision=revision,
        project_id=project_id,
        chapter_number=chapter_number,
        status=ChapterTaskStatus.REVISION_REQUIRED,
        last_stable_status=ChapterTaskStatus.DRAFTING,
        creative_intent_ref=ci,
        confirmed_plan_ref=confirmed_plan,
        current_author_draft_ref=author_draft,
        review_target_draft_ref=review_target,
        adopted_draft_ref=adopted,
        latest_review_ref=latest_review,
        pending_changeset_ref=pending_changeset,
        commit_receipt_ref=None,
        recovery=None,
        created_at=now,
        updated_at=now,
    )


def _make_recovery_task(
    task_id: str = "task-1",
    *,
    retry_from_status: ChapterTaskStatus = ChapterTaskStatus.DRAFTING,
    revision: int = 2,
) -> ChapterTask:
    now = datetime.now(timezone.utc)
    return ChapterTask(
        task_id=task_id,
        schema_version=SCHEMA_VERSION,
        aggregate_revision=revision,
        project_id="project-1",
        chapter_number=1,
        status=ChapterTaskStatus.RECOVERY_REQUIRED,
        last_stable_status=retry_from_status,
        creative_intent_ref=_ref(f"intent-{task_id}"),
        confirmed_plan_ref=None,
        current_author_draft_ref=None,
        review_target_draft_ref=None,
        adopted_draft_ref=None,
        latest_review_ref=None,
        pending_changeset_ref=None,
        commit_receipt_ref=None,
        recovery=RecoveryInfo(
            failed_operation_id="op-fail-1",
            error_code="TEST_ERROR",
            retry_from_status=retry_from_status,
        ),
        created_at=now,
        updated_at=now,
    )


def _transition_cmd(
    task_id: str = "task-1",
    *,
    target: ChapterTaskStatus = ChapterTaskStatus.DRAFTING,
    expected_revision: int = 3,
    recovery: RecoveryInfo | None = None,
) -> TransitionChapterTaskCommand:
    return TransitionChapterTaskCommand(
        task_id=task_id,
        target_status=target,
        expected_revision=expected_revision,
        recovery=recovery,
    )


def _ctx(key: str = "ctx-key-1") -> TransitionOperationContext:
    return TransitionOperationContext(idempotency_key=key)


def ids(*values: str):
    iterator: Iterator[str] = iter(values)
    return lambda: next(iterator)


# ---------------------------------------------------------------------------
# Fake UoW (for mock-based tests)
# ---------------------------------------------------------------------------

class FakeTasks:
    def __init__(self) -> None:
        self.values: dict[str, ChapterTask] = {}
        self.replaced: list[tuple[ChapterTask, int]] = []
        self.replace_error: Exception | None = None

    def get(self, task_id: str) -> ChapterTask | None:
        return self.values.get(task_id)

    def replace(self, task: ChapterTask, *, expected_revision: int) -> None:
        if self.replace_error is not None:
            raise self.replace_error
        self.replaced.append((task, expected_revision))
        self.values[task.task_id] = task


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[object] = []
        self.error: Exception | None = None

    def add_event(self, event: object) -> None:
        if self.error is not None:
            raise self.error
        self.events.append(event)


class FakeOperations:
    def __init__(self) -> None:
        self.existing: OperationLogRecord | None = None
        self.outcome = OperationCreateOutcome(OperationResult.NEW)
        self.records: list[OperationLogRecord] = []
        self.error: Exception | None = None
        self.read_error: Exception | None = None

    def get_by_idempotency_key(self, key: str) -> OperationLogRecord | None:
        if self.read_error is not None:
            raise self.read_error
        return self.existing

    def create_or_replay_complete(self, record: OperationLogRecord) -> OperationCreateOutcome:
        if self.error is not None:
            raise self.error
        self.records.append(record)
        return self.outcome


class FakeUow:
    def __init__(self) -> None:
        self.tasks = FakeTasks()
        self.audit = FakeAudit()
        self.operations = FakeOperations()
        self.commits = 0
        self.rollbacks = 0
        self.commit_error: Exception | None = None
        self.close_error: Exception | None = None
        self.rollback_error: Exception | None = None
        self.closes = 0

    def commit(self) -> None:
        if self.commit_error is not None:
            raise self.commit_error
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1
        if self.rollback_error is not None:
            raise self.rollback_error

    def close(self) -> None:
        self.closes += 1
        if self.close_error is not None:
            raise self.close_error


def _transition_envelope(
    cmd: TransitionChapterTaskCommand,
    *,
    revision: int = 4,
    status: ChapterTaskStatus = ChapterTaskStatus.DRAFTING,
) -> str:
    result = TransitionChapterTaskResult(
        task_id=cmd.task_id,
        aggregate_revision=revision,
        status=status,
    )
    return create_transition_result_envelope(
        result,
        operation_kind=OperationKind.TRANSITION_CHAPTER_TASK,
        original_operation_id="original-op",
        audit_event_ids=("original-event",),
    )


def _transition_record(
    cmd: TransitionChapterTaskCommand,
    ctx: TransitionOperationContext,
    envelope: str,
) -> OperationLogRecord:
    return OperationLogRecord(
        operation_id="original-op",
        idempotency_key=ctx.idempotency_key,
        request_digest=compute_transition_request_digest(
            cmd, OperationKind.TRANSITION_CHAPTER_TASK
        ),
        result_envelope_json=envelope,
        result_envelope_hash=compute_envelope_hash(envelope),
        created_at="2026-01-01T00:00:00.000000Z",
    )


# ---------------------------------------------------------------------------
# T01: REVISION_REQUIRED -> DRAFTING success
# ---------------------------------------------------------------------------

def test_revision_required_to_drafting_succeeds() -> None:
    uow = FakeUow()
    task = _make_revision_required_task()
    uow.tasks.values[task.task_id] = task
    cmd = _transition_cmd(task.task_id, target=ChapterTaskStatus.DRAFTING,
                          expected_revision=task.aggregate_revision)
    ctx = _ctx("ctx-rev-1")
    result = TransitionChapterTaskUseCase(
        lambda: uow, id_factory=ids("op-1", "event-1")
    ).transition(cmd, ctx)
    assert result.status is ChapterTaskStatus.DRAFTING
    assert result.aggregate_revision == task.aggregate_revision + 1
    assert len(uow.operations.records) == 1
    assert uow.commits == 1
    assert uow.rollbacks == 0
    assert uow.closes == 1
    event = uow.audit.events[0]
    assert event.event_type == "TASK_TRANSITIONED"
    assert event.actor.kind is SourceKind.SYSTEM
    assert event.before_task_revision == task.aggregate_revision
    assert event.after_task_revision == task.aggregate_revision + 1
    assert event.object_refs == (task.creative_intent_ref,)


# ---------------------------------------------------------------------------
# T02: RECOVERY_REQUIRED -> retry_from_status success
# ---------------------------------------------------------------------------

def test_recovery_required_to_retry_from_status_succeeds() -> None:
    uow = FakeUow()
    task = _make_recovery_task(retry_from_status=ChapterTaskStatus.DRAFTING)
    uow.tasks.values[task.task_id] = task
    cmd = _transition_cmd(
        task.task_id,
        target=ChapterTaskStatus.DRAFTING,
        expected_revision=task.aggregate_revision,
    )
    ctx = _ctx("ctx-recovery-1")
    result = TransitionChapterTaskUseCase(
        lambda: uow, id_factory=ids("op-2", "event-2")
    ).transition(cmd, ctx)
    assert result.status is ChapterTaskStatus.DRAFTING
    assert result.aggregate_revision == task.aggregate_revision + 1
    assert len(uow.audit.events) == 1
    assert uow.commits == 1


# ---------------------------------------------------------------------------
# T03: Fast replay returns original database envelope
# ---------------------------------------------------------------------------

def test_fast_replay_returns_original_database_envelope() -> None:
    uow = FakeUow()
    task = _make_revision_required_task()
    uow.tasks.values[task.task_id] = task
    cmd = _transition_cmd(task.task_id, target=ChapterTaskStatus.DRAFTING,
                          expected_revision=task.aggregate_revision)
    ctx = _ctx("ctx-replay-1")
    envelope = _transition_envelope(cmd, revision=4)
    uow.operations.existing = _transition_record(cmd, ctx, envelope)
    id_calls: list[str] = []
    def tracking_id() -> str:
        id_calls.append("called")
        return "should-not-be-used"
    result = TransitionChapterTaskUseCase(
        lambda: uow, id_factory=tracking_id
    ).transition(cmd, ctx)
    assert result.aggregate_revision == 4
    assert uow.operations.records == []
    assert uow.tasks.replaced == []
    assert uow.audit.events == []
    assert uow.rollbacks == 1
    assert uow.closes == 1
    assert id_calls == []  # fast REPLAY must not call id_factory


# ---------------------------------------------------------------------------
# T04: Competing replay uses outcome original envelope
# ---------------------------------------------------------------------------

def test_competing_replay_uses_outcome_original_envelope() -> None:
    uow = FakeUow()
    task = _make_revision_required_task()
    uow.tasks.values[task.task_id] = task
    cmd = _transition_cmd(task.task_id, target=ChapterTaskStatus.DRAFTING,
                          expected_revision=task.aggregate_revision)
    ctx = _ctx("ctx-replay-2")
    envelope = _transition_envelope(cmd, revision=5)
    uow.operations.outcome = OperationCreateOutcome(
        OperationResult.REPLAY, replay_envelope_json=envelope
    )
    result = TransitionChapterTaskUseCase(
        lambda: uow, id_factory=ids("new-op", "new-event")
    ).transition(cmd, ctx)
    assert result.aggregate_revision == 5
    assert uow.tasks.replaced == []
    assert uow.audit.events == []
    assert uow.rollbacks == 1
    assert uow.closes == 1


# ---------------------------------------------------------------------------
# T05: Idempotency digest conflict is fail-closed
# ---------------------------------------------------------------------------

def test_idempotency_digest_conflict_is_fail_closed() -> None:
    uow = FakeUow()
    task = _make_revision_required_task()
    uow.tasks.values[task.task_id] = task
    cmd = _transition_cmd(task.task_id, target=ChapterTaskStatus.DRAFTING,
                          expected_revision=task.aggregate_revision)
    ctx = _ctx("ctx-conflict-1")
    envelope = _transition_envelope(cmd, revision=4)
    existing = _transition_record(cmd, ctx, envelope)
    uow.operations.existing = replace(
        existing, request_digest="sha256:" + "z" * 64
    )
    with pytest.raises(IdempotencyConflict):
        TransitionChapterTaskUseCase(lambda: uow).transition(cmd, ctx)
    assert uow.tasks.replaced == []
    assert uow.rollbacks == 1
    assert uow.closes == 1


# ---------------------------------------------------------------------------
# T06: RevisionConflict zero residue (SQLite replace affects zero rows)
# ---------------------------------------------------------------------------

def test_revision_conflict_zero_residue() -> None:
    uow = FakeUow()
    task = _make_revision_required_task()
    uow.tasks.values[task.task_id] = task
    cmd = _transition_cmd(task.task_id, target=ChapterTaskStatus.DRAFTING,
                          expected_revision=task.aggregate_revision)
    ctx = _ctx("ctx-rev-conflict-1")
    from xiaoshuo.application.creation.errors import RevisionConflict
    uow.tasks.replace_error = RevisionConflict("revision mismatch")
    with pytest.raises(RevisionConflict):
        TransitionChapterTaskUseCase(
            lambda: uow, id_factory=ids("op-1", "event-1")
        ).transition(cmd, ctx)
    assert uow.rollbacks == 1
    assert uow.audit.events == []
    assert uow.closes == 1


# ---------------------------------------------------------------------------
# T07: Domain RevisionConflict zero residue
# ---------------------------------------------------------------------------

def test_revision_conflict_from_domain_zero_residue() -> None:
    uow = FakeUow()
    task = _make_revision_required_task(revision=3)
    uow.tasks.values[task.task_id] = task
    cmd = _transition_cmd(task.task_id, target=ChapterTaskStatus.DRAFTING,
                          expected_revision=999)  # wrong revision
    ctx = _ctx("ctx-domain-conflict-1")
    with pytest.raises(DomainRevisionConflict):
        TransitionChapterTaskUseCase(
            lambda: uow, id_factory=ids("op-1", "event-1")
        ).transition(cmd, ctx)
    assert uow.rollbacks == 1
    assert uow.operations.records == []


# ---------------------------------------------------------------------------
# T08-T12: Illegal transitions
# ---------------------------------------------------------------------------

def test_illegal_transition_plan_preparing_to_plan_approval_rejected() -> None:
    uow = FakeUow()
    task = _make_revision_required_task()
    task = replace(task, status=ChapterTaskStatus.PLAN_PREPARING)
    uow.tasks.values[task.task_id] = task
    cmd = _transition_cmd(task.task_id,
                          target=ChapterTaskStatus.PLAN_APPROVAL_PENDING,
                          expected_revision=task.aggregate_revision)
    ctx = _ctx("ctx-illegal-1")
    with pytest.raises(UnsupportedPersistenceBoundary):
        TransitionChapterTaskUseCase(lambda: uow).transition(cmd, ctx)


def test_illegal_transition_drafting_to_reviewing_rejected() -> None:
    uow = FakeUow()
    task = _make_revision_required_task()
    task = replace(task, status=ChapterTaskStatus.DRAFTING)
    uow.tasks.values[task.task_id] = task
    cmd = _transition_cmd(task.task_id,
                          target=ChapterTaskStatus.REVIEWING,
                          expected_revision=task.aggregate_revision)
    ctx = _ctx("ctx-illegal-2")
    with pytest.raises(UnsupportedPersistenceBoundary):
        TransitionChapterTaskUseCase(lambda: uow).transition(cmd, ctx)


def test_illegal_transition_to_committing_rejected() -> None:
    factory_called: list[bool] = []
    def tracking_factory() -> FakeUow:
        factory_called.append(True)
        uow = FakeUow()
        task = _make_revision_required_task()
        uow.tasks.values[task.task_id] = task
        return uow
    cmd = _transition_cmd("task-1",
                          target=ChapterTaskStatus.COMMITTING,
                          expected_revision=3)
    ctx = _ctx("ctx-illegal-3")
    with pytest.raises(UnsupportedPersistenceBoundary):
        TransitionChapterTaskUseCase(tracking_factory).transition(cmd, ctx)
    assert factory_called == []  # UoW must not be created for illegal target


def test_illegal_transition_to_completed_rejected() -> None:
    uow = FakeUow()
    task = _make_revision_required_task()
    uow.tasks.values[task.task_id] = task
    cmd = _transition_cmd(task.task_id,
                          target=ChapterTaskStatus.COMPLETED,
                          expected_revision=task.aggregate_revision)
    ctx = _ctx("ctx-illegal-4")
    with pytest.raises(UnsupportedPersistenceBoundary):
        TransitionChapterTaskUseCase(lambda: uow).transition(cmd, ctx)


def test_illegal_transition_to_cancelled_rejected() -> None:
    uow = FakeUow()
    task = _make_revision_required_task()
    uow.tasks.values[task.task_id] = task
    cmd = _transition_cmd(task.task_id,
                          target=ChapterTaskStatus.CANCELLED,
                          expected_revision=task.aggregate_revision)
    ctx = _ctx("ctx-illegal-5")
    with pytest.raises(UnsupportedPersistenceBoundary):
        TransitionChapterTaskUseCase(lambda: uow).transition(cmd, ctx)


# ---------------------------------------------------------------------------
# T13-T14: Illegal recovery targets
# ---------------------------------------------------------------------------

def test_illegal_recovery_to_committing_rejected() -> None:
    uow = FakeUow()
    task = _make_recovery_task()
    uow.tasks.values[task.task_id] = task
    cmd = _transition_cmd(task.task_id,
                          target=ChapterTaskStatus.COMMITTING,
                          expected_revision=task.aggregate_revision)
    ctx = _ctx("ctx-illegal-6")
    with pytest.raises(UnsupportedPersistenceBoundary):
        TransitionChapterTaskUseCase(lambda: uow).transition(cmd, ctx)


def test_illegal_recovery_to_completed_rejected() -> None:
    uow = FakeUow()
    task = _make_recovery_task()
    uow.tasks.values[task.task_id] = task
    cmd = _transition_cmd(task.task_id,
                          target=ChapterTaskStatus.COMPLETED,
                          expected_revision=task.aggregate_revision)
    ctx = _ctx("ctx-illegal-7")
    with pytest.raises(UnsupportedPersistenceBoundary):
        TransitionChapterTaskUseCase(lambda: uow).transition(cmd, ctx)


# ---------------------------------------------------------------------------
# T15: AuthorDecision bypass rejected
# ---------------------------------------------------------------------------

def test_author_decision_bypass_rejected() -> None:
    uow = FakeUow()
    task = _make_revision_required_task()
    task = replace(task, status=ChapterTaskStatus.DRAFT_APPROVAL_PENDING)
    uow.tasks.values[task.task_id] = task
    cmd = _transition_cmd(task.task_id,
                          target=ChapterTaskStatus.DRAFTING,
                          expected_revision=task.aggregate_revision)
    ctx = _ctx("ctx-bypass-1")
    with pytest.raises(UnsupportedPersistenceBoundary):
        TransitionChapterTaskUseCase(lambda: uow).transition(cmd, ctx)


# ---------------------------------------------------------------------------
# T16: Recovery retry mismatch — only UnsupportedPersistenceBoundary
# ---------------------------------------------------------------------------

def test_recovery_retry_mismatch_rejected() -> None:
    uow = FakeUow()
    task = _make_recovery_task(retry_from_status=ChapterTaskStatus.DRAFTING)
    uow.tasks.values[task.task_id] = task
    # Target is REVIEWING, but retry_from_status is DRAFTING
    cmd = _transition_cmd(task.task_id,
                          target=ChapterTaskStatus.REVIEWING,
                          expected_revision=task.aggregate_revision)
    ctx = _ctx("ctx-mismatch-1")
    with pytest.raises(UnsupportedPersistenceBoundary):
        TransitionChapterTaskUseCase(lambda: uow).transition(cmd, ctx)
    assert uow.rollbacks == 1
    assert uow.closes == 1


# ---------------------------------------------------------------------------
# T17: object_refs fixed order
# ---------------------------------------------------------------------------

def test_object_refs_fixed_order() -> None:
    uow = FakeUow()
    ci = _ref("ci")
    plan = _ref("plan")
    draft = _ref("draft")
    review_target = _ref("rt")
    adopted = _ref("adopted")
    review = _ref("review")
    changeset = _ref("changeset")
    task = _make_revision_required_task(
        creative_intent=ci,
        confirmed_plan=plan,
        author_draft=draft,
        review_target=review_target,
        adopted=adopted,
        latest_review=review,
        pending_changeset=changeset,
    )
    uow.tasks.values[task.task_id] = task
    cmd = _transition_cmd(task.task_id, target=ChapterTaskStatus.DRAFTING,
                          expected_revision=task.aggregate_revision)
    ctx = _ctx("ctx-refs-1")
    result = TransitionChapterTaskUseCase(
        lambda: uow, id_factory=ids("op-1", "event-1")
    ).transition(cmd, ctx)
    assert result.status is ChapterTaskStatus.DRAFTING
    event = uow.audit.events[0]
    assert event.object_refs == (ci, plan, draft, review_target, adopted, review, changeset)


# ---------------------------------------------------------------------------
# T18: object_refs only non-null
# ---------------------------------------------------------------------------

def test_object_refs_only_non_null() -> None:
    uow = FakeUow()
    ci = _ref("ci")
    plan = _ref("plan")
    task = _make_revision_required_task(
        creative_intent=ci,
        confirmed_plan=plan,
        # other refs are None
    )
    uow.tasks.values[task.task_id] = task
    cmd = _transition_cmd(task.task_id, target=ChapterTaskStatus.DRAFTING,
                          expected_revision=task.aggregate_revision)
    ctx = _ctx("ctx-refs-2")
    result = TransitionChapterTaskUseCase(
        lambda: uow, id_factory=ids("op-1", "event-1")
    ).transition(cmd, ctx)
    assert result.status is ChapterTaskStatus.DRAFTING
    event = uow.audit.events[0]
    assert event.object_refs == (ci, plan)


# ---------------------------------------------------------------------------
# T19: Commit failure calls rollback
# ---------------------------------------------------------------------------

def test_commit_failure_calls_rollback_and_raises_stable_error() -> None:
    uow = FakeUow()
    task = _make_revision_required_task()
    uow.tasks.values[task.task_id] = task
    uow.commit_error = RuntimeError("commit failed")
    cmd = _transition_cmd(task.task_id, target=ChapterTaskStatus.DRAFTING,
                          expected_revision=task.aggregate_revision)
    ctx = _ctx("ctx-commit-fail-1")
    with pytest.raises(CreationApplicationError, match="persistence failed"):
        TransitionChapterTaskUseCase(
            lambda: uow, id_factory=ids("op-1", "event-1")
        ).transition(cmd, ctx)
    assert uow.rollbacks == 1
    assert uow.closes == 1


# ---------------------------------------------------------------------------
# T20: Original error preserved when close also fails
# ---------------------------------------------------------------------------

def test_original_error_preserved_when_close_also_fails() -> None:
    uow = FakeUow()
    task = _make_revision_required_task()
    uow.tasks.values[task.task_id] = task
    from xiaoshuo.application.creation.errors import RevisionConflict
    uow.tasks.replace_error = RevisionConflict("mismatch")
    uow.close_error = RuntimeError("close failed")
    cmd = _transition_cmd(task.task_id, target=ChapterTaskStatus.DRAFTING,
                          expected_revision=task.aggregate_revision)
    ctx = _ctx("ctx-close-fail-1")
    with pytest.raises(RevisionConflict) as caught:
        TransitionChapterTaskUseCase(
            lambda: uow, id_factory=ids("op-1", "event-1")
        ).transition(cmd, ctx)
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert str(caught.value.__cause__) == "close failed"


# ---------------------------------------------------------------------------
# T21: Success path close failure raises application error
# ---------------------------------------------------------------------------

def test_success_path_close_failure_raises_application_error() -> None:
    uow = FakeUow()
    task = _make_revision_required_task()
    uow.tasks.values[task.task_id] = task
    uow.close_error = RuntimeError("close failed")
    cmd = _transition_cmd(task.task_id, target=ChapterTaskStatus.DRAFTING,
                          expected_revision=task.aggregate_revision)
    ctx = _ctx("ctx-close-fail-2")
    with pytest.raises(CreationApplicationError, match="close failed") as caught:
        TransitionChapterTaskUseCase(
            lambda: uow, id_factory=ids("op-1", "event-1")
        ).transition(cmd, ctx)
    assert isinstance(caught.value.__cause__, RuntimeError)


# ---------------------------------------------------------------------------
# T22: Task not found + read failure coverage + rollback failure
# ---------------------------------------------------------------------------

def test_task_not_found_rejected() -> None:
    uow = FakeUow()
    cmd = _transition_cmd("nonexistent", target=ChapterTaskStatus.DRAFTING,
                          expected_revision=0)
    ctx = _ctx("ctx-notfound-1")
    with pytest.raises(NotFound):
        TransitionChapterTaskUseCase(lambda: uow).transition(cmd, ctx)
    assert uow.rollbacks == 1
    assert uow.closes == 1

    # Operation ledger read failure — rollback=1, close=1
    uow2 = FakeUow()
    uow2.operations.read_error = RuntimeError("db closed")
    cmd2 = _transition_cmd("task-1", target=ChapterTaskStatus.DRAFTING,
                           expected_revision=3)
    ctx2 = _ctx("ctx-op-read-fail")
    with pytest.raises(CreationApplicationError, match="persistence read failed") as caught2:
        TransitionChapterTaskUseCase(lambda: uow2).transition(cmd2, ctx2)
    assert isinstance(caught2.value.__cause__, RuntimeError)
    assert str(caught2.value.__cause__) == "db closed"
    assert uow2.rollbacks == 1
    assert uow2.closes == 1

    # Task read failure — rollback=1, close=1
    uow3 = FakeUow()
    uow3.tasks.get = lambda task_id: (_ for _ in ()).throw(RuntimeError("db closed"))
    cmd3 = _transition_cmd("task-1", target=ChapterTaskStatus.DRAFTING,
                           expected_revision=3)
    ctx3 = _ctx("ctx-task-read-fail")
    with pytest.raises(CreationApplicationError):
        TransitionChapterTaskUseCase(lambda: uow3).transition(cmd3, ctx3)
    assert uow3.rollbacks == 1
    assert uow3.closes == 1

    # Normal failure path: rollback raises — error not swallowed
    uow4 = FakeUow()
    task4 = _make_revision_required_task()
    uow4.tasks.values[task4.task_id] = task4
    uow4.tasks.replace_error = RuntimeError("replace failed")
    uow4.rollback_error = RuntimeError("rollback failed")
    cmd4 = _transition_cmd(task4.task_id, target=ChapterTaskStatus.DRAFTING,
                           expected_revision=task4.aggregate_revision)
    ctx4 = _ctx("ctx-rollback-fail-normal")
    with pytest.raises(CreationApplicationError, match="rollback failed") as caught4:
        TransitionChapterTaskUseCase(
            lambda: uow4, id_factory=ids("op-4", "evt-4")
        ).transition(cmd4, ctx4)
    assert uow4.rollbacks == 1  # rollback called exactly once
    assert uow4.closes == 1
    assert isinstance(caught4.value.__cause__, RuntimeError)
    assert str(caught4.value.__cause__) == "rollback failed"

    # REPLAY path: rollback raises — error not swallowed
    uow5 = FakeUow()
    task5 = _make_revision_required_task()
    uow5.tasks.values[task5.task_id] = task5
    cmd5 = _transition_cmd(task5.task_id, target=ChapterTaskStatus.DRAFTING,
                           expected_revision=task5.aggregate_revision)
    ctx5 = _ctx("ctx-replay-rollback-fail")
    envelope5 = _transition_envelope(cmd5, revision=4)
    uow5.operations.existing = _transition_record(cmd5, ctx5, envelope5)
    uow5.rollback_error = RuntimeError("rollback failed")
    with pytest.raises(CreationApplicationError, match="rollback failed") as caught5:
        TransitionChapterTaskUseCase(lambda: uow5).transition(cmd5, ctx5)
    assert uow5.rollbacks == 1  # rollback called exactly once
    assert uow5.closes == 1
    assert isinstance(caught5.value.__cause__, RuntimeError)
    assert str(caught5.value.__cause__) == "rollback failed"


# ---------------------------------------------------------------------------
# Real SQLite tests (T23-T26)
# ---------------------------------------------------------------------------

def _sqlite_factory(settings: SQLitePersistenceSettings):
    def factory() -> SqliteCreationUnitOfWork:
        return SqliteCreationUnitOfWork(get_connection(settings))
    return factory


def _init_sqlite(tmp_path: Path) -> SQLitePersistenceSettings:
    settings = SQLitePersistenceSettings(tmp_path / "b2a.db", 5000, backup_dir=tmp_path / "backup")
    init_database(settings)
    setup = get_connection(settings)
    MigrationRunner().migrate(setup, settings)
    setup.close()
    return settings


def _create_task_in_db(
    settings: SQLitePersistenceSettings,
    task_id: str,
    *,
    status: ChapterTaskStatus = ChapterTaskStatus.REVISION_REQUIRED,
    last_stable_status: ChapterTaskStatus = ChapterTaskStatus.DRAFTING,
    creative_intent: ArtifactRef | None = None,
    recovery: RecoveryInfo | None = None,
) -> ChapterTask:
    """Create a task via CreateChapterTaskUseCase, then manually set its
    status in the DB to REVISION_REQUIRED or RECOVERY_REQUIRED."""
    ci = creative_intent or _ref(f"intent-{task_id}")
    cmd = CreateChapterTaskCommand(
        task_id=task_id,
        project_id="project-1",
        chapter_number=1,
        initial_status=ChapterTaskStatus.PLAN_PREPARING,
        creative_intent_ref=ci,
    )
    factory = _sqlite_factory(settings)
    CreateChapterTaskUseCase(
        factory, id_factory=ids("op-create", "evt-create")
    ).create(cmd)

    # Now manually update the status to desired state
    conn = get_connection(settings)
    try:
        conn.execute(
            "UPDATE chapter_task SET status = ?, last_stable_status = ?, "
            "aggregate_revision = 3 "
            "WHERE task_id = ?",
            (status.value, last_stable_status.value, task_id),
        )
        if recovery is not None:
            conn.execute(
                "UPDATE chapter_task SET recovery_failed_operation_id = ?, "
                "recovery_error_code = ?, recovery_retry_from_status = ? "
                "WHERE task_id = ?",
                (recovery.failed_operation_id,
                 recovery.error_code,
                 recovery.retry_from_status.value,
                 task_id),
            )
        conn.commit()
    finally:
        conn.close()

    # Return the task as it now exists in the DB
    conn = get_connection(settings, read_only=True)
    try:
        from xiaoshuo.infrastructure.persistence.sqlite.repository import (
            SqliteChapterTaskRepository,
        )
        repo = SqliteChapterTaskRepository(conn)
        task = repo.get(task_id)
        assert task is not None
        return task
    finally:
        conn.close()


# T23: Real SQLite event_id PK conflict

def test_real_sqlite_transition_pk_failure_zero_residue(tmp_path) -> None:
    """Use a deterministic id_factory to force the event_id to collide
    with a pre-existing event from a successful transition."""
    settings = _init_sqlite(tmp_path)
    task = _create_task_in_db(settings, "task-pk-test")

    # First, do a successful transition that creates event_id "evt-preexist"
    factory = _sqlite_factory(settings)
    cmd_initial = _transition_cmd(
        "task-pk-test",
        target=ChapterTaskStatus.DRAFTING,
        expected_revision=task.aggregate_revision,
    )
    ctx_initial = _ctx("ctx-initial")
    result_initial = TransitionChapterTaskUseCase(
        factory,
        id_factory=ids("op-initial", "evt-preexist"),
    ).transition(cmd_initial, ctx_initial)
    assert result_initial.status is ChapterTaskStatus.DRAFTING

    # Now set the task back to REVISION_REQUIRED
    conn = get_connection(settings)
    try:
        conn.execute(
            "UPDATE chapter_task SET status = 'REVISION_REQUIRED' "
            "WHERE task_id = 'task-pk-test'"
        )
        conn.commit()
    finally:
        conn.close()

    # Now try another transition with the same event_id "evt-preexist"
    # This will cause a real SQLite PK conflict on creation_audit_event
    cmd = _transition_cmd(
        "task-pk-test",
        target=ChapterTaskStatus.DRAFTING,
        expected_revision=result_initial.aggregate_revision,
    )
    ctx = _ctx("ctx-pk-conflict")
    with pytest.raises(CreationApplicationError):
        TransitionChapterTaskUseCase(
            factory,
            id_factory=ids("op-new", "evt-preexist"),  # PK conflict
        ).transition(cmd, ctx)

    # Verify zero residue
    verify = get_connection(settings, read_only=True)
    try:
        assert verify.execute(
            "SELECT COUNT(*) FROM creation_operation "
            "WHERE idempotency_key = ?", ("ctx-pk-conflict",)
        ).fetchone()[0] == 0
        # The pre-existing event should still be there
        assert verify.execute(
            "SELECT COUNT(*) FROM creation_audit_event "
            "WHERE event_id = ?", ("evt-preexist",)
        ).fetchone()[0] == 1
        # Task should still be at the post-initial revision
        assert verify.execute(
            "SELECT COUNT(*) FROM chapter_task WHERE task_id = ? "
            "AND aggregate_revision = ?",
            ("task-pk-test", result_initial.aggregate_revision),
        ).fetchone()[0] == 1
    finally:
        verify.close()


# T24: Real SQLite replace conflict zero residue

def test_real_sqlite_replace_conflict_zero_residue(tmp_path) -> None:
    """Test real SQLite conditional replace conflict where the operation INSERT
    has already been staged but the task revision in DB doesn't match.

    Strategy: use a real SQLite UoW with a wrapper Task repository that
    returns a stale-revision Task, so the real SQLite conditional replace
    affects zero rows after the operation INSERT is staged.
    """
    settings = _init_sqlite(tmp_path)
    _create_task_in_db(settings, "task-replace-test")

    # Read the real task from DB to get its actual revision
    conn_read = get_connection(settings, read_only=True)
    try:
        from xiaoshuo.infrastructure.persistence.sqlite.repository import (
            SqliteChapterTaskRepository,
        )
        real_repo = SqliteChapterTaskRepository(conn_read)
        real_task = real_repo.get("task-replace-test")
        assert real_task is not None
    finally:
        conn_read.close()

    # Bump the revision in DB after the read so the stale task's
    # expected_revision won't match the actual DB revision.
    conn_bump = get_connection(settings)
    try:
        conn_bump.execute(
            "UPDATE chapter_task SET aggregate_revision = aggregate_revision + 1 "
            "WHERE task_id = 'task-replace-test'"
        )
        conn_bump.commit()
    finally:
        conn_bump.close()

    # Build a UoW with a wrapper that returns the stale task
    class StaleTaskWrapper:
        """Wraps the real SQLite task repo but returns a stale-revision task."""
        def __init__(self, real_repo, stale_task):
            self._real = real_repo
            self._stale = stale_task
            self.replace_calls: list = []

        def get(self, task_id: str):
            if task_id == "task-replace-test":
                return self._stale
            return self._real.get(task_id)

        def replace(self, task, *, expected_revision: int):
            self.replace_calls.append((task, expected_revision))
            # Delegate to real repo — this will trigger the actual SQLite
            # conditional UPDATE affecting zero rows
            self._real.replace(task, expected_revision=expected_revision)

    class WrappedUoW:
        def __init__(self, real_uow, stale_task):
            self._real = real_uow
            self.tasks = StaleTaskWrapper(real_uow.tasks, stale_task)
            self.audit = real_uow.audit
            self.operations = real_uow.operations
            self.commits = 0
            self.rollbacks = 0
            self.closes = 0

        def commit(self):
            self._real.commit()
            self.commits += 1

        def rollback(self):
            self._real.rollback()
            self.rollbacks += 1

        def close(self):
            self._real.close()
            self.closes += 1

    stale_task_for_transition = replace(
        real_task, aggregate_revision=real_task.aggregate_revision
    )

    conn_uow = get_connection(settings)
    real_uow = SqliteCreationUnitOfWork(conn_uow)
    wrapped_uow = WrappedUoW(real_uow, stale_task_for_transition)

    cmd = _transition_cmd(
        "task-replace-test",
        target=ChapterTaskStatus.DRAFTING,
        expected_revision=real_task.aggregate_revision,  # stale
    )
    ctx = _ctx("ctx-replace-conflict")
    from xiaoshuo.application.creation.errors import RevisionConflict
    with pytest.raises(RevisionConflict):
        TransitionChapterTaskUseCase(
            lambda: wrapped_uow,
            id_factory=ids("op-replace", "evt-replace"),
        ).transition(cmd, ctx)

    # Assert wrapper replace was called once (real SQLite replace attempted)
    assert len(wrapped_uow.tasks.replace_calls) == 1
    # Assert rollback=1, close=1
    assert wrapped_uow.rollbacks == 1
    assert wrapped_uow.closes == 1

    # Verify zero residue in the real SQLite database
    verify = get_connection(settings, read_only=True)
    try:
        assert verify.execute(
            "SELECT COUNT(*) FROM creation_operation "
            "WHERE idempotency_key = ?", ("ctx-replace-conflict",)
        ).fetchone()[0] == 0
        assert verify.execute(
            "SELECT COUNT(*) FROM creation_audit_event "
            "WHERE event_id = ?", ("evt-replace",)
        ).fetchone()[0] == 0
        # Task unchanged — should still be at the bumped revision
        assert verify.execute(
            "SELECT COUNT(*) FROM chapter_task WHERE task_id = ? "
            "AND aggregate_revision = ?",
            ("task-replace-test", real_task.aggregate_revision + 1),
        ).fetchone()[0] == 1
    finally:
        verify.close()


# T25: Ledger key must equal context key, not task_id

def test_ledger_key_must_equal_context_key_not_task_id(tmp_path) -> None:
    settings = _init_sqlite(tmp_path)
    task = _create_task_in_db(settings, "task-ledger-key")

    factory = _sqlite_factory(settings)
    cmd = _transition_cmd(
        "task-ledger-key",
        target=ChapterTaskStatus.DRAFTING,
        expected_revision=task.aggregate_revision,
    )
    # Context key is explicitly different from task_id
    ctx = _ctx("unique-context-key-not-task-id")
    result = TransitionChapterTaskUseCase(
        factory,
        id_factory=ids("op-ledger", "evt-ledger"),
    ).transition(cmd, ctx)
    assert result.status is ChapterTaskStatus.DRAFTING

    # Read the original stored envelope directly from the database
    verify = get_connection(settings, read_only=True)
    try:
        row = verify.execute(
            "SELECT idempotency_key, result_envelope_json FROM creation_operation "
            "WHERE operation_id = ?", ("op-ledger",)
        ).fetchone()
        assert row is not None
        assert row["idempotency_key"] == "unique-context-key-not-task-id"
        assert row["idempotency_key"] != "task-ledger-key"
        original_envelope = row["result_envelope_json"]
    finally:
        verify.close()

    # Parse the original stored envelope to compare field-by-field later
    expected_from_db = result_from_transition_envelope(
        original_envelope, expected_task_id="task-ledger-key"
    )

    # Now replay with same context key + same digest using a new UoW
    conn2 = get_connection(settings)
    try:
        uow2 = SqliteCreationUnitOfWork(conn2)
        try:
            id_calls: list[str] = []
            def tracking_id() -> str:
                id_calls.append("called")
                return "should-not-be-used"
            result2 = TransitionChapterTaskUseCase(
                lambda: uow2,
                id_factory=tracking_id,
            ).transition(cmd, ctx)
            # The replayed result must come from the original stored envelope,
            # not a newly constructed one. Compare field-by-field.
            assert result2.task_id == expected_from_db.task_id
            assert result2.aggregate_revision == expected_from_db.aggregate_revision
            assert result2.status == expected_from_db.status
            assert result2.result_schema_version == expected_from_db.result_schema_version
            # id_factory must not be called during REPLAY
            assert id_calls == []
        finally:
            uow2.close()
    finally:
        conn2.close()

    # Verify no new operation, audit, or task writes occurred
    verify2 = get_connection(settings, read_only=True)
    try:
        assert verify2.execute(
            "SELECT COUNT(*) FROM creation_operation "
            "WHERE idempotency_key = ?", ("unique-context-key-not-task-id",)
        ).fetchone()[0] == 1
        assert verify2.execute(
            "SELECT COUNT(*) FROM creation_audit_event "
            "WHERE event_type = 'TASK_TRANSITIONED' AND task_id = ?",
            ("task-ledger-key",)
        ).fetchone()[0] == 1  # only the original event
    finally:
        verify2.close()


# T26: Role artifact refs unchanged + registry no new entries

def test_role_artifact_refs_unchanged_and_registry_no_new_entries(tmp_path) -> None:
    settings = _init_sqlite(tmp_path)
    ci = _ref("ci-invariance")
    plan = _ref("plan-invariance")
    draft = _ref("draft-invariance")
    task = _create_task_in_db(
        settings, "task-invariance",
        creative_intent=ci,
    )
    # Manually add plan and draft refs to the task
    conn = get_connection(settings)
    try:
        from xiaoshuo.infrastructure.persistence.sqlite.repository import (
            SqliteChapterTaskRepository,
        )
        repo = SqliteChapterTaskRepository(conn)
        # Register the artifact refs first
        repo._ensure_artifact_ref(plan)
        repo._ensure_artifact_ref(draft)
        conn.execute(
            "UPDATE chapter_task SET confirmed_plan_ref_artifact_id = ?, "
            "current_author_draft_ref_artifact_id = ? "
            "WHERE task_id = ?",
            (plan.artifact_id, draft.artifact_id, task.task_id),
        )
        conn.commit()
    finally:
        conn.close()

    # Count artifact refs before transition
    verify_before = get_connection(settings, read_only=True)
    try:
        count_before = verify_before.execute(
            "SELECT COUNT(*) FROM creation_artifact_ref"
        ).fetchone()[0]
    finally:
        verify_before.close()

    # Read task before transition
    conn_r = get_connection(settings, read_only=True)
    try:
        from xiaoshuo.infrastructure.persistence.sqlite.repository import (
            SqliteChapterTaskRepository,
        )
        repo_r = SqliteChapterTaskRepository(conn_r)
        task_before = repo_r.get("task-invariance")
        assert task_before is not None
    finally:
        conn_r.close()

    factory = _sqlite_factory(settings)
    cmd = _transition_cmd(
        "task-invariance",
        target=ChapterTaskStatus.DRAFTING,
        expected_revision=task_before.aggregate_revision,
    )
    ctx = _ctx("ctx-invariance")
    result = TransitionChapterTaskUseCase(
        factory,
        id_factory=ids("op-inv", "evt-inv"),
    ).transition(cmd, ctx)
    assert result.status is ChapterTaskStatus.DRAFTING

    # Verify artifact refs unchanged
    verify = get_connection(settings, read_only=True)
    try:
        from xiaoshuo.infrastructure.persistence.sqlite.repository import (
            SqliteChapterTaskRepository,
        )
        repo_v = SqliteChapterTaskRepository(verify)
        task_after = repo_v.get("task-invariance")
        assert task_after is not None

        # Seven role refs unchanged
        assert task_after.creative_intent_ref == task_before.creative_intent_ref
        assert task_after.confirmed_plan_ref == task_before.confirmed_plan_ref
        assert task_after.current_author_draft_ref == task_before.current_author_draft_ref
        assert task_after.review_target_draft_ref == task_before.review_target_draft_ref
        assert task_after.adopted_draft_ref == task_before.adopted_draft_ref
        assert task_after.latest_review_ref == task_before.latest_review_ref
        assert task_after.pending_changeset_ref == task_before.pending_changeset_ref
        # commit_receipt_ref not written
        assert task_after.commit_receipt_ref is None

        # Registry no new entries
        count_after = verify.execute(
            "SELECT COUNT(*) FROM creation_artifact_ref"
        ).fetchone()[0]
        assert count_after == count_before

        # object_refs includes ci, plan, draft (the non-null ones)
        events = verify.execute(
            "SELECT * FROM creation_audit_event WHERE event_id = ?",
            ("evt-inv",),
        ).fetchall()
        assert len(events) == 1
        obj_refs = verify.execute(
            "SELECT artifact_id FROM creation_audit_event_object_ref "
            "WHERE event_id = ? ORDER BY ordinal",
            ("evt-inv",),
        ).fetchall()
        ref_ids = [r["artifact_id"] for r in obj_refs]
        assert ref_ids == [
            ci.artifact_id,
            plan.artifact_id,
            draft.artifact_id,
        ]
    finally:
        verify.close()
