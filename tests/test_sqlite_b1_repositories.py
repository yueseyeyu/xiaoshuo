"""Integration tests for B1 operation and append-only audit adapters."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from queue import Queue
import sqlite3
import sys
from threading import Event, Thread

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from xiaoshuo.application.creation.digest import compute_envelope_hash
from xiaoshuo.application.creation.errors import (
    ArtifactIdentityConflict,
    CreationApplicationError,
    OperationIdConflict,
)
from xiaoshuo.application.creation.repository import (
    OperationLogRecord,
    OperationResult,
)
from xiaoshuo.domain.creation import (
    ArtifactRef,
    AuditEvent,
    SourceKind,
    SourceRef,
)
from xiaoshuo.infrastructure.persistence.sqlite.audit_repository import (
    SqliteAuditEventRepository,
)
from xiaoshuo.infrastructure.persistence.sqlite.connection import get_connection
from xiaoshuo.infrastructure.persistence.sqlite.maintenance import init_database
from xiaoshuo.infrastructure.persistence.sqlite.migration_runner import MigrationRunner
from xiaoshuo.infrastructure.persistence.sqlite.operation_repository import (
    SqliteOperationLogRepository,
)
from xiaoshuo.infrastructure.persistence.sqlite.settings import SQLitePersistenceSettings
from xiaoshuo.infrastructure.persistence.sqlite.uow import SqliteCreationUnitOfWork

HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


@pytest.fixture
def conn(tmp_path):
    settings = SQLitePersistenceSettings(tmp_path / "b1-repositories.db", 5000, backup_dir=tmp_path / "backup")
    init_database(settings)
    connection = get_connection(settings)
    MigrationRunner().migrate(connection, settings)
    yield connection
    connection.close()


def record(
    operation_id: str = "op-1",
    key: str = "key-1",
    digest: str = "sha256:" + "1" * 64,
    envelope: str = '{"original":true}',
) -> OperationLogRecord:
    return OperationLogRecord(
        operation_id=operation_id,
        idempotency_key=key,
        request_digest=digest,
        result_envelope_json=envelope,
        result_envelope_hash=compute_envelope_hash(envelope),
        created_at="2026-01-01T00:00:00.000000Z",
    )


def test_operation_repository_new_and_get(conn) -> None:
    repo = SqliteOperationLogRepository(conn)
    proposed = record()
    assert repo.create_or_replay_complete(proposed).status is OperationResult.NEW
    assert repo.get_by_idempotency_key("key-1") == proposed


def test_operation_repository_replay_returns_database_original_envelope(conn) -> None:
    repo = SqliteOperationLogRepository(conn)
    original = record(envelope='{"winner":"database"}')
    repo.create_or_replay_complete(original)
    proposed = record(operation_id="op-2", envelope='{"loser":"new"}')
    outcome = repo.create_or_replay_complete(proposed)
    assert outcome.status is OperationResult.REPLAY
    assert outcome.replay_envelope_json == original.result_envelope_json


def test_operation_repository_digest_conflict(conn) -> None:
    repo = SqliteOperationLogRepository(conn)
    repo.create_or_replay_complete(record())
    outcome = repo.create_or_replay_complete(
        record(operation_id="op-2", digest="sha256:" + "2" * 64)
    )
    assert outcome.status is OperationResult.CONFLICT
    assert outcome.replay_envelope_json is None


def test_two_connections_race_replays_database_winner_envelope(tmp_path) -> None:
    settings = SQLitePersistenceSettings(tmp_path / "operation-race.db", 5000, backup_dir=tmp_path / "backup")
    init_database(settings)
    winner_conn = get_connection(settings)
    MigrationRunner().migrate(winner_conn, settings)
    winner = record(envelope='{"winner":"database"}')
    SqliteOperationLogRepository(winner_conn).create_or_replay_complete(winner)

    insert_reached = Event()
    result_queue = Queue()

    def compete() -> None:
        competing_conn = get_connection(settings)
        competing_conn.set_trace_callback(
            lambda statement: insert_reached.set()
            if statement.startswith("INSERT INTO creation_operation")
            else None
        )
        try:
            proposed = record(operation_id="op-loser", envelope='{"loser":"new"}')
            result_queue.put(
                SqliteOperationLogRepository(competing_conn)
                .create_or_replay_complete(proposed)
            )
        except Exception as exc:  # surfaced in the asserting thread
            result_queue.put(exc)
        finally:
            competing_conn.close()

    thread = Thread(target=compete)
    thread.start()
    assert insert_reached.wait(5), "competing INSERT did not reach SQLite"
    winner_conn.commit()
    thread.join(5)
    winner_conn.close()
    assert not thread.is_alive()
    outcome = result_queue.get_nowait()
    if isinstance(outcome, Exception):
        raise outcome
    assert outcome.status is OperationResult.REPLAY
    assert outcome.replay_envelope_json == winner.result_envelope_json


def test_operation_id_conflict_does_not_leak_integrity_error(conn) -> None:
    repo = SqliteOperationLogRepository(conn)
    repo.create_or_replay_complete(record())
    with pytest.raises(OperationIdConflict):
        repo.create_or_replay_complete(record(key="different-key"))


def test_operation_conflict_diagnostic_read_does_not_leak_sqlite_error() -> None:
    class EmptyCursor:
        def fetchone(self):
            return None

    class FailingDiagnosticConnection:
        def execute(self, statement, parameters=()):
            if statement.startswith("INSERT INTO creation_operation"):
                raise sqlite3.IntegrityError("conflict")
            if "WHERE operation_id" in statement:
                raise sqlite3.OperationalError("diagnostic read failed")
            return EmptyCursor()

    repo = SqliteOperationLogRepository(FailingDiagnosticConnection())
    with pytest.raises(
        CreationApplicationError, match="conflict diagnosis failed"
    ) as caught:
        repo.create_or_replay_complete(record())
    assert isinstance(caught.value.__cause__, sqlite3.OperationalError)


def test_tampered_envelope_hash_fails_closed(conn) -> None:
    repo = SqliteOperationLogRepository(conn)
    repo.create_or_replay_complete(record())
    conn.execute(
        "UPDATE creation_operation SET result_envelope_json = ? WHERE operation_id = ?",
        ('{"tampered":true}', "op-1"),
    )
    with pytest.raises(CreationApplicationError, match="hash mismatch"):
        repo.get_by_idempotency_key("key-1")


def test_proposed_envelope_hash_mismatch_fails_before_insert(conn) -> None:
    repo = SqliteOperationLogRepository(conn)
    proposed = record()
    proposed = OperationLogRecord(
        operation_id=proposed.operation_id,
        idempotency_key=proposed.idempotency_key,
        request_digest=proposed.request_digest,
        result_envelope_json=proposed.result_envelope_json,
        result_envelope_hash="sha256:" + "0" * 64,
        created_at=proposed.created_at,
    )
    with pytest.raises(CreationApplicationError, match="proposed.*hash mismatch"):
        repo.create_or_replay_complete(proposed)
    assert conn.execute("SELECT COUNT(*) FROM creation_operation").fetchone()[0] == 0


def _insert_task_and_operation(conn) -> None:
    conn.execute(
        "INSERT INTO creation_artifact_ref VALUES (?, ?, ?)",
        ("source-1", 1, HASH_A),
    )
    conn.execute(
        "INSERT INTO creation_artifact_ref VALUES (?, ?, ?)",
        ("object-1", 1, HASH_B),
    )
    conn.execute(
        "INSERT INTO chapter_task (task_id, schema_version, aggregate_revision, "
        "project_id, chapter_number, status, last_stable_status, "
        "creative_intent_ref_artifact_id, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "task-1", 1, 0, "project-1", 1, "PLAN_PREPARING",
            "PLAN_PREPARING", "object-1", "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:00:00+00:00",
        ),
    )
    SqliteOperationLogRepository(conn).create_or_replay_complete(record())


def test_audit_repository_writes_scalar_and_ordered_reference_rows(conn) -> None:
    _insert_task_and_operation(conn)
    source = ArtifactRef("source-1", 1, HASH_A)
    obj = ArtifactRef("object-1", 1, HASH_B)
    event = AuditEvent(
        event_id="event-1",
        schema_version=1,
        task_id="task-1",
        project_id="project-1",
        event_type="TASK_CREATED",
        actor=SourceRef(kind=SourceKind.SYSTEM, source_artifact_refs=(source,)),
        before_task_revision=0,
        after_task_revision=0,
        object_refs=(obj,),
        operation_id="op-1",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    SqliteAuditEventRepository(conn).add_event(event)
    scalar = conn.execute(
        "SELECT event_type, actor_kind, before_task_revision, after_task_revision "
        "FROM creation_audit_event WHERE event_id = ?",
        ("event-1",),
    ).fetchone()
    assert tuple(scalar) == ("TASK_CREATED", "SYSTEM", 0, 0)
    assert tuple(conn.execute(
        "SELECT ordinal, artifact_id FROM creation_audit_event_source_artifact_ref"
    ).fetchone()) == (0, "source-1")
    assert tuple(conn.execute(
        "SELECT ordinal, artifact_id FROM creation_audit_event_object_ref"
    ).fetchone()) == (0, "object-1")


def test_audit_repository_rejects_artifact_identity_mismatch(conn) -> None:
    _insert_task_and_operation(conn)
    bad_object = ArtifactRef("object-1", 1, HASH_A)
    event = AuditEvent(
        event_id="event-bad",
        schema_version=1,
        task_id="task-1",
        project_id="project-1",
        event_type="TASK_CREATED",
        actor=SourceRef(kind=SourceKind.SYSTEM),
        before_task_revision=0,
        after_task_revision=0,
        object_refs=(bad_object,),
        operation_id="op-1",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    with pytest.raises(ArtifactIdentityConflict):
        SqliteAuditEventRepository(conn).add_event(event)
    assert conn.execute(
        "SELECT COUNT(*) FROM creation_audit_event WHERE event_id = ?",
        ("event-bad",),
    ).fetchone()[0] == 0


def test_uow_uses_real_operation_and_audit_adapters(conn) -> None:
    uow = SqliteCreationUnitOfWork(conn)
    assert isinstance(uow.operations, SqliteOperationLogRepository)
    assert isinstance(uow.audit, SqliteAuditEventRepository)
