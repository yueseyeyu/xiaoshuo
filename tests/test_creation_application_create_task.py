"""CreateChapterTask orchestration, idempotency, and atomicity tests."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from xiaoshuo.application.creation.commands import CreateChapterTaskCommand
from xiaoshuo.application.creation.create_task import CreateChapterTaskUseCase
from xiaoshuo.application.creation.digest import (
    compute_envelope_hash,
    compute_request_digest,
    create_result_envelope,
)
from xiaoshuo.application.creation.errors import (
    CreationApplicationError,
    IdempotencyConflict,
    OperationIdConflict,
    UnsupportedPersistenceBoundary,
)
from xiaoshuo.application.creation.operation_kind import OperationKind
from xiaoshuo.application.creation.repository import (
    OperationCreateOutcome,
    OperationLogRecord,
    OperationResult,
)
from xiaoshuo.application.creation.results import CreateChapterTaskResult
from xiaoshuo.domain.creation import ArtifactRef, ChapterTaskStatus
from xiaoshuo.infrastructure.persistence.sqlite.connection import get_connection
from xiaoshuo.infrastructure.persistence.sqlite.maintenance import init_database
from xiaoshuo.infrastructure.persistence.sqlite.migration_runner import MigrationRunner
from xiaoshuo.infrastructure.persistence.sqlite.settings import SQLitePersistenceSettings
from xiaoshuo.infrastructure.persistence.sqlite.uow import SqliteCreationUnitOfWork

HASH_A = "sha256:" + "a" * 64


def command(task_id: str = "task-1", *, chapter_number: int = 1) -> CreateChapterTaskCommand:
    return CreateChapterTaskCommand(
        task_id=task_id,
        project_id="project-1",
        chapter_number=chapter_number,
        initial_status=ChapterTaskStatus.PLAN_PREPARING,
        creative_intent_ref=ArtifactRef(f"intent-{task_id}", 1, HASH_A),
    )


class FakeTasks:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        self.added: list[object] = []

    def get(self, task_id: str):
        return self.values.get(task_id)

    def add(self, value: object) -> None:
        self.added.append(value)
        self.values[value.task_id] = value


class FakeAudit:
    def __init__(self, error: Exception | None = None) -> None:
        self.events: list[object] = []
        self.error = error

    def add_event(self, event: object) -> None:
        if self.error is not None:
            raise self.error
        self.events.append(event)


class FakeOperations:
    def __init__(self) -> None:
        self.existing: OperationLogRecord | None = None
        self.outcome = OperationCreateOutcome(OperationResult.NEW)
        self.records: list[OperationLogRecord] = []

    def get_by_idempotency_key(self, key: str) -> OperationLogRecord | None:
        return self.existing

    def create_or_replay_complete(self, record: OperationLogRecord) -> OperationCreateOutcome:
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
        self.closes = 0

    def commit(self) -> None:
        if self.commit_error is not None:
            raise self.commit_error
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closes += 1
        if self.close_error is not None:
            raise self.close_error


def ids(*values: str):
    iterator: Iterator[str] = iter(values)
    return lambda: next(iterator)


def original_envelope(cmd: CreateChapterTaskCommand, *, revision: int = 0) -> str:
    result = CreateChapterTaskResult(
        task_id=cmd.task_id,
        aggregate_revision=revision,
        status=ChapterTaskStatus.PLAN_PREPARING,
    )
    return create_result_envelope(
        result,
        operation_kind=OperationKind.CREATE_CHAPTER_TASK,
        original_operation_id="original-op",
        audit_event_ids=("original-event",),
    )


def record_for(cmd: CreateChapterTaskCommand, envelope: str) -> OperationLogRecord:
    return OperationLogRecord(
        operation_id="original-op",
        idempotency_key=cmd.task_id,
        request_digest=compute_request_digest(cmd, OperationKind.CREATE_CHAPTER_TASK),
        result_envelope_json=envelope,
        result_envelope_hash=compute_envelope_hash(envelope),
        created_at="2026-01-01T00:00:00.000000Z",
    )


def test_success_creates_task_operation_and_one_audit_event() -> None:
    uow = FakeUow()
    result = CreateChapterTaskUseCase(
        lambda: uow, id_factory=ids("op-1", "event-1")
    ).create(command())
    assert result.aggregate_revision == 0
    assert result.status is ChapterTaskStatus.PLAN_PREPARING
    assert len(uow.operations.records) == 1
    assert len(uow.tasks.added) == 1
    assert len(uow.audit.events) == 1
    event = uow.audit.events[0]
    assert event.event_type == "TASK_CREATED"
    assert event.object_refs == (command().creative_intent_ref,)
    assert event.actor.source_artifact_refs == ()
    assert uow.commits == 1
    assert uow.rollbacks == 0
    assert uow.closes == 1


def test_fast_replay_returns_original_database_envelope_without_writes() -> None:
    cmd = command()
    uow = FakeUow()
    envelope = original_envelope(cmd, revision=7)
    uow.operations.existing = record_for(cmd, envelope)
    result = CreateChapterTaskUseCase(lambda: uow, id_factory=ids()).create(cmd)
    assert result.aggregate_revision == 7
    assert uow.operations.records == []
    assert uow.tasks.added == []
    assert uow.audit.events == []


def test_competing_replay_uses_outcome_original_envelope() -> None:
    cmd = command()
    uow = FakeUow()
    original = original_envelope(cmd, revision=9)
    uow.operations.outcome = OperationCreateOutcome(
        OperationResult.REPLAY, replay_envelope_json=original
    )
    result = CreateChapterTaskUseCase(
        lambda: uow, id_factory=ids("new-op", "new-event")
    ).create(cmd)
    assert result.aggregate_revision == 9
    assert uow.tasks.added == []
    assert uow.audit.events == []
    assert uow.rollbacks == 1
    assert uow.closes == 1


def test_idempotency_digest_conflict_is_fail_closed() -> None:
    cmd = command()
    uow = FakeUow()
    envelope = original_envelope(cmd)
    existing = record_for(cmd, envelope)
    uow.operations.existing = replace(
        existing, request_digest="sha256:" + "b" * 64
    )
    with pytest.raises(IdempotencyConflict):
        CreateChapterTaskUseCase(lambda: uow).create(cmd)
    assert uow.tasks.added == []


def test_conflicting_outcome_rolls_back_exactly_once() -> None:
    uow = FakeUow()
    uow.operations.outcome = OperationCreateOutcome(OperationResult.CONFLICT)
    with pytest.raises(IdempotencyConflict):
        CreateChapterTaskUseCase(
            lambda: uow, id_factory=ids("op-1", "event-1")
        ).create(command())
    assert uow.rollbacks == 1
    assert uow.closes == 1


def test_original_error_preserved_when_close_also_fails() -> None:
    """When both the main operation and close() fail, the original error
    type must be preserved and the close error must be its __cause__."""
    uow = FakeUow()
    uow.operations.outcome = OperationCreateOutcome(OperationResult.CONFLICT)
    uow.close_error = RuntimeError("close failed")
    with pytest.raises(IdempotencyConflict) as caught:
        CreateChapterTaskUseCase(
            lambda: uow, id_factory=ids("op-1", "event-1")
        ).create(command())
    assert uow.rollbacks == 1
    assert uow.closes == 1
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert str(caught.value.__cause__) == "close failed"


def test_persistence_error_preserved_when_close_also_fails() -> None:
    """When a persistence error and close() both fail, the original
    CreationApplicationError type must be preserved and the close error
    must be its __cause__."""
    uow = FakeUow()
    uow.commit_error = RuntimeError("commit failed")
    uow.close_error = RuntimeError("close failed")
    with pytest.raises(CreationApplicationError, match="persistence failed") as caught:
        CreateChapterTaskUseCase(
            lambda: uow, id_factory=ids("op-1", "event-1")
        ).create(command())
    assert uow.rollbacks == 1
    assert uow.closes == 1
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert str(caught.value.__cause__) == "close failed"


def test_success_path_close_failure_raises_application_error() -> None:
    """When the main operation succeeds but close() fails, a
    CreationApplicationError must be raised with the close error as cause."""
    uow = FakeUow()
    uow.close_error = RuntimeError("close failed")
    with pytest.raises(CreationApplicationError, match="close failed") as caught:
        CreateChapterTaskUseCase(
            lambda: uow, id_factory=ids("op-1", "event-1")
        ).create(command())
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert str(caught.value.__cause__) == "close failed"


@pytest.mark.parametrize("boundary", ["factory", "operation-read", "task-read"])
def test_prewrite_storage_failures_are_stable_application_errors(boundary) -> None:
    uow = FakeUow()
    if boundary == "factory":
        factory = lambda: (_ for _ in ()).throw(sqlite3.OperationalError("closed"))
    elif boundary == "operation-read":
        uow.operations.get_by_idempotency_key = lambda key: (_ for _ in ()).throw(
            sqlite3.OperationalError("closed")
        )
        factory = lambda: uow
    else:
        uow.tasks.get = lambda key: (_ for _ in ()).throw(
            sqlite3.OperationalError("closed")
        )
        factory = lambda: uow
    with pytest.raises(CreationApplicationError) as caught:
        CreateChapterTaskUseCase(factory).create(command())
    assert isinstance(caught.value.__cause__, sqlite3.OperationalError)


def test_existing_task_without_operation_is_operation_conflict() -> None:
    cmd = command()
    uow = FakeUow()
    uow.tasks.values[cmd.task_id] = object()
    with pytest.raises(OperationIdConflict, match="without a matching"):
        CreateChapterTaskUseCase(lambda: uow).create(cmd)
    assert uow.operations.records == []


def test_non_plan_preparing_rejected_before_uow_creation() -> None:
    called = False

    def factory():
        nonlocal called
        called = True
        return FakeUow()

    cmd = command()
    bad = CreateChapterTaskCommand(
        task_id=cmd.task_id,
        project_id=cmd.project_id,
        chapter_number=cmd.chapter_number,
        initial_status=ChapterTaskStatus.DRAFTING,
        creative_intent_ref=cmd.creative_intent_ref,
    )
    with pytest.raises(UnsupportedPersistenceBoundary):
        CreateChapterTaskUseCase(factory).create(bad)
    assert not called


def test_commit_failure_calls_rollback_and_raises_stable_error() -> None:
    uow = FakeUow()
    uow.commit_error = RuntimeError("commit failed")
    with pytest.raises(CreationApplicationError, match="persistence failed"):
        CreateChapterTaskUseCase(
            lambda: uow, id_factory=ids("op-1", "event-1")
        ).create(command())
    assert uow.rollbacks == 1
    assert uow.closes == 1


def test_real_sqlite_audit_pk_failure_rolls_back_task_operation_and_refs(tmp_path) -> None:
    settings = SQLitePersistenceSettings(tmp_path / "b1.db", 5000, backup_dir=tmp_path / "backup")
    init_database(settings)
    setup = get_connection(settings)
    MigrationRunner().migrate(setup, settings)
    setup.close()

    def factory() -> SqliteCreationUnitOfWork:
        return SqliteCreationUnitOfWork(get_connection(settings))

    CreateChapterTaskUseCase(
        factory, id_factory=ids("op-preexist", "evt-preexist")
    ).create(command("task-preexist"))

    with pytest.raises(CreationApplicationError) as caught:
        CreateChapterTaskUseCase(
            factory, id_factory=ids("op-new", "evt-preexist")
        ).create(command("task-conflict-test"))
    assert isinstance(caught.value.__cause__, sqlite3.IntegrityError)

    verify = get_connection(settings, read_only=True)
    try:
        assert verify.execute(
            "SELECT COUNT(*) FROM chapter_task WHERE task_id = ?",
            ("task-conflict-test",),
        ).fetchone()[0] == 0
        assert verify.execute(
            "SELECT COUNT(*) FROM creation_operation WHERE idempotency_key = ?",
            ("task-conflict-test",),
        ).fetchone()[0] == 0
        assert verify.execute(
            "SELECT COUNT(*) FROM creation_audit_event WHERE task_id = ?",
            ("task-conflict-test",),
        ).fetchone()[0] == 0
        assert verify.execute(
            "SELECT COUNT(*) FROM creation_audit_event_source_artifact_ref "
            "WHERE event_id = ?",
            ("evt-preexist",),
        ).fetchone()[0] == 0
        assert verify.execute(
            "SELECT COUNT(*) FROM creation_audit_event_object_ref "
            "WHERE event_id = ?",
            ("evt-preexist",),
        ).fetchone()[0] == 1
        assert verify.execute(
            "SELECT COUNT(*) FROM creation_artifact_ref WHERE artifact_id = ?",
            ("intent-task-conflict-test",),
        ).fetchone()[0] == 0
        assert verify.execute(
            "SELECT COUNT(*) FROM chapter_task WHERE task_id = ?",
            ("task-preexist",),
        ).fetchone()[0] == 1
        assert verify.execute(
            "SELECT COUNT(*) FROM creation_audit_event WHERE event_id = ?",
            ("evt-preexist",),
        ).fetchone()[0] == 1
    finally:
        verify.close()
