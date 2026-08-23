"""B3 SQLite read-only boundary and integrity-report tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from xiaoshuo.application.creation.get_task import GetChapterTaskUseCase
from xiaoshuo.application.creation.query import CreationQueryUseCase
from xiaoshuo.application.creation.query_requests import (
    AuditHistoryRequest,
    ChapterTaskListRequest,
)
from xiaoshuo.domain.creation import (
    ArtifactRef,
    ChapterTask,
    ChapterTaskStatus,
)
from xiaoshuo.infrastructure.persistence.sqlite.connection import get_connection
from xiaoshuo.infrastructure.persistence.sqlite.maintenance import init_database
from xiaoshuo.infrastructure.persistence.sqlite.migration_runner import MigrationRunner
from xiaoshuo.infrastructure.persistence.sqlite.query_repository import (
    SqliteIntegrityCheckRepository,
    SqliteReadOnlyQueryRepository,
)
from xiaoshuo.infrastructure.persistence.sqlite.query_uow import (
    SqliteCreationQuerySession,
)
from xiaoshuo.infrastructure.persistence.sqlite.repository import (
    SqliteChapterTaskRepository,
)
from xiaoshuo.infrastructure.persistence.sqlite.settings import (
    SQLitePersistenceSettings,
)
from xiaoshuo.application.creation.results import IntegrityFailureKind

HASH = "sha256:" + "a" * 64
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

_TABLES = (
    "chapter_task",
    "creation_audit_event",
    "creation_operation",
    "creation_author_decision",
    "creation_decision_consumption",
    "creation_artifact_ref",
)


def _settings(tmp_path):
    settings = SQLitePersistenceSettings(
        db_path=str(tmp_path / "readonly.db"), busy_timeout_ms=1000,
        backup_dir=str(tmp_path / "backups"),
    )
    init_database(settings)
    conn = get_connection(settings)
    MigrationRunner().migrate(conn, settings)
    conn.close()
    return settings


def _seed_database(settings):
    """Seed a minimal dataset for Q10 zero-write verification."""
    write = get_connection(settings)
    try:
        task = ChapterTask(
            task_id="task-q10", schema_version=1, aggregate_revision=0,
            project_id="project-1", chapter_number=1,
            status=ChapterTaskStatus.PLAN_PREPARING,
            last_stable_status=ChapterTaskStatus.PLAN_PREPARING,
            creative_intent_ref=ArtifactRef("intent-q10", 1, HASH),
            confirmed_plan_ref=None, current_author_draft_ref=None,
            review_target_draft_ref=None, adopted_draft_ref=None,
            latest_review_ref=None, pending_changeset_ref=None,
            commit_receipt_ref=None, recovery=None, created_at=NOW, updated_at=NOW,
        )
        SqliteChapterTaskRepository(write).add(task)
        write.execute(
            "INSERT INTO creation_operation (operation_id, idempotency_key, request_digest, "
            "result_envelope_json, result_envelope_hash, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("op-q10", "key-q10", "digest", "{}", "hash", "2026-01-01T00:00:00Z"),
        )
        write.execute(
            "INSERT INTO creation_audit_event (event_id, schema_version, task_id, project_id, "
            "event_type, actor_kind, actor_id, model_run_id, before_task_revision, "
            "after_task_revision, operation_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("event-q10", 1, "task-q10", "project-1", "TEST", "AUTHOR", "author-1",
             None, 0, 1, "op-q10", "2026-01-01T00:00:00Z"),
        )
        write.commit()
    finally:
        write.close()


def _table_counts(conn):
    return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in _TABLES}


# ---------------------------------------------------------------------------
# Q10 — zero business writes across all B3 queries
# ---------------------------------------------------------------------------

def test_q10_all_b3_queries_preserve_six_table_row_counts(tmp_path) -> None:
    """Every B3 query (Task list, Audit history, integrity check) executed
    via the real readonly session and facade must leave the row counts of
    all six business tables unchanged."""
    settings = _settings(tmp_path)
    _seed_database(settings)
    conn = get_connection(settings, read_only=True)
    try:
        assert conn.execute("PRAGMA query_only").fetchone()[0] == 1
        session = SqliteCreationQuerySession(conn)

        # --- Task list via session ---
        before = _table_counts(conn)
        session.tasks.list_by_project(ChapterTaskListRequest("project-1"))
        assert _table_counts(conn) == before

        # --- Audit history via session ---
        before = _table_counts(conn)
        session.audit.history_for_task(AuditHistoryRequest("task-q10"))
        assert _table_counts(conn) == before

        # --- Integrity check via session ---
        before = _table_counts(conn)
        session.integrity.check()
        assert _table_counts(conn) == before

        # --- All three via facade ---
        b1 = GetChapterTaskUseCase(lambda: SqliteCreationQuerySession(get_connection(settings, read_only=True)))
        facade = CreationQueryUseCase(b1, lambda: SqliteCreationQuerySession(get_connection(settings, read_only=True)))
        before = _table_counts(conn)
        facade.list_tasks(ChapterTaskListRequest("project-1"))
        facade.audit_history(AuditHistoryRequest("task-q10"))
        facade.check_integrity()
        assert _table_counts(conn) == before

        # --- Write rejection on readonly connection ---
        with pytest.raises(sqlite3.Error):
            conn.execute("INSERT INTO chapter_task (task_id) VALUES ('never')")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Q11 — readonly connection error
# ---------------------------------------------------------------------------

def test_q11_readonly_connection_rejects_writes(tmp_path) -> None:
    settings = _settings(tmp_path)
    conn = get_connection(settings, read_only=True)
    try:
        assert conn.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.Error):
            conn.execute("INSERT INTO chapter_task (task_id) VALUES ('never')")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Q12 — integrity success
# ---------------------------------------------------------------------------

def test_q12_integrity_success_is_readonly_report(tmp_path) -> None:
    settings = _settings(tmp_path)
    conn = get_connection(settings, read_only=True)
    try:
        report = SqliteIntegrityCheckRepository(conn).check()
        assert report.integrity_ok and report.foreign_key_ok and report.foreign_key_violation_count == 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Q13 — integrity failure kinds: INTEGRITY, FOREIGN_KEY, BOTH
# ---------------------------------------------------------------------------

class _FakeFetchOne:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row

    def fetchall(self):
        return [self._row] if self._row else []


class _FakeFetchAll:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeIntegrityConnection:
    """Controlled fake readonly connection for integrity failure testing.

    No real database file, schema, or migration is modified to simulate
    corruption.  The fake returns deterministic PRAGMA results.
    """

    def __init__(self, integrity_result: str, foreign_key_rows: tuple) -> None:
        self._integrity_result = integrity_result
        self._foreign_key_rows = foreign_key_rows

    def execute(self, sql, params=()):
        if "integrity_check" in sql:
            return _FakeFetchOne((self._integrity_result,))
        if "foreign_key_check" in sql:
            return _FakeFetchAll(self._foreign_key_rows)
        raise sqlite3.OperationalError("unexpected query in fake connection")

    def close(self) -> None:
        pass


def _assert_report_does_not_leak_internals(report) -> None:
    """The integrity report must not expose raw SQL, database paths, or
    SQLite exception messages."""
    text = repr(report)
    assert "SELECT" not in text
    assert "PRAGMA" not in text
    assert ".db" not in text
    assert "sqlite3" not in text.lower()


def test_q13_integrity_failure_kind_integrity() -> None:
    """PRAGMA integrity_check fails, foreign_key_check passes."""
    conn = _FakeIntegrityConnection(integrity_result="row 3 missing", foreign_key_rows=())
    try:
        report = SqliteIntegrityCheckRepository(conn).check()
        assert not report.integrity_ok
        assert report.foreign_key_ok
        assert report.failure_kind is IntegrityFailureKind.INTEGRITY
        _assert_report_does_not_leak_internals(report)
    finally:
        conn.close()


def test_q13_integrity_failure_kind_foreign_key(tmp_path) -> None:
    """PRAGMA integrity_check passes, foreign_key_check fails."""
    settings = _settings(tmp_path)
    write = get_connection(settings)
    try:
        write.execute("PRAGMA foreign_keys = OFF")
        write.execute(
            "INSERT INTO creation_audit_event (event_id, schema_version, task_id, project_id, "
            "event_type, actor_kind, actor_id, model_run_id, before_task_revision, "
            "after_task_revision, operation_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("bad", 1, "missing-task", "project-1", "TEST", "SYSTEM", None, None,
             0, 0, "missing-op", "2026-01-01T00:00:00Z"),
        )
        write.commit()
    finally:
        write.close()
    conn = get_connection(settings, read_only=True)
    try:
        report = SqliteIntegrityCheckRepository(conn).check()
        assert report.integrity_ok
        assert not report.foreign_key_ok
        assert report.foreign_key_violation_count > 0
        assert report.failure_kind is IntegrityFailureKind.FOREIGN_KEY
        _assert_report_does_not_leak_internals(report)
    finally:
        conn.close()


def test_q13_integrity_failure_kind_both() -> None:
    """Both PRAGMA integrity_check and foreign_key_check fail."""
    fake_rows = ({"table": "creation_audit_event", "rowid": 1, "refs": "chapter_task"},)
    conn = _FakeIntegrityConnection(
        integrity_result="row 3 missing", foreign_key_rows=fake_rows,
    )
    try:
        report = SqliteIntegrityCheckRepository(conn).check()
        assert not report.integrity_ok
        assert not report.foreign_key_ok
        assert report.failure_kind is IntegrityFailureKind.BOTH
        _assert_report_does_not_leak_internals(report)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Q01 strengthening — B3 exact get delegates to existing B1 repository
# ---------------------------------------------------------------------------

def test_q01_no_second_exact_id_sql_path_in_b3_query_repository() -> None:
    """SqliteReadOnlyQueryRepository must not define a get() method;
    the only exact-id SQL path is the existing SqliteChapterTaskRepository."""
    assert not hasattr(SqliteReadOnlyQueryRepository, "get")


def test_q01_b3_exact_get_via_b1_returns_complete_task(tmp_path) -> None:
    """B3 exact get via the B1 use case returns the existing complete
    ChapterTask with all fields and ArtifactRef identity reconstructed
    by the existing SqliteChapterTaskRepository.get()."""
    settings = _settings(tmp_path)
    original = ChapterTask(
        task_id="task-q01", schema_version=1, aggregate_revision=0,
        project_id="project-1", chapter_number=42,
        status=ChapterTaskStatus.PLAN_PREPARING,
        last_stable_status=ChapterTaskStatus.PLAN_PREPARING,
        creative_intent_ref=ArtifactRef("intent-q01", 1, HASH),
        confirmed_plan_ref=ArtifactRef("plan-q01", 1, HASH),
        current_author_draft_ref=None, review_target_draft_ref=None,
        adopted_draft_ref=None, latest_review_ref=None,
        pending_changeset_ref=None, commit_receipt_ref=None,
        recovery=None, created_at=NOW, updated_at=NOW,
    )
    write = get_connection(settings)
    try:
        SqliteChapterTaskRepository(write).add(original)
        write.commit()
    finally:
        write.close()

    conn = get_connection(settings, read_only=True)
    try:
        session = SqliteCreationQuerySession(conn)
        # B3 session.tasks.get delegates to SqliteChapterTaskRepository.get
        result = session.tasks.get("task-q01")
        assert result is not None
        assert result.task_id == "task-q01"
        assert result.chapter_number == 42
        assert result.project_id == "project-1"
        assert result.status == ChapterTaskStatus.PLAN_PREPARING
        assert result.creative_intent_ref.artifact_id == "intent-q01"
        assert result.creative_intent_ref.content_hash == HASH
        assert result.confirmed_plan_ref is not None
        assert result.confirmed_plan_ref.artifact_id == "plan-q01"

        # Missing task returns None (B1 semantics, not a B3 SQL path)
        assert session.tasks.get("nonexistent") is None
    finally:
        conn.close()


def test_q01_b3_facade_get_task_delegates_to_b1_use_case(tmp_path) -> None:
    """The B3 facade get_task delegates to GetChapterTaskUseCase which
    uses the session's tasks.get — itself delegating to the existing
    SqliteChapterTaskRepository."""
    settings = _settings(tmp_path)
    original = ChapterTask(
        task_id="task-facade", schema_version=1, aggregate_revision=0,
        project_id="project-1", chapter_number=1,
        status=ChapterTaskStatus.PLAN_PREPARING,
        last_stable_status=ChapterTaskStatus.PLAN_PREPARING,
        creative_intent_ref=ArtifactRef("intent-facade", 1, HASH),
        confirmed_plan_ref=None, current_author_draft_ref=None,
        review_target_draft_ref=None, adopted_draft_ref=None,
        latest_review_ref=None, pending_changeset_ref=None,
        commit_receipt_ref=None, recovery=None, created_at=NOW, updated_at=NOW,
    )
    write = get_connection(settings)
    try:
        SqliteChapterTaskRepository(write).add(original)
        write.commit()
    finally:
        write.close()

    def _session_factory():
        return SqliteCreationQuerySession(get_connection(settings, read_only=True))

    b1 = GetChapterTaskUseCase(_session_factory)
    facade = CreationQueryUseCase(b1, _session_factory)
    result = facade.get_task("task-facade")
    assert result.task_id == "task-facade"
    assert result.creative_intent_ref.artifact_id == "intent-facade"
