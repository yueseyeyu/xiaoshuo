"""Tests for append-only triggers — UPDATE/DELETE rejected, INSERT allowed."""

from __future__ import annotations

from pathlib import Path
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from xiaoshuo.infrastructure.persistence.sqlite.settings import (
    SQLitePersistenceSettings,
)
from xiaoshuo.infrastructure.persistence.sqlite.connection import get_connection
from xiaoshuo.infrastructure.persistence.sqlite.maintenance import init_database
from xiaoshuo.infrastructure.persistence.sqlite.migration_runner import (
    MigrationRunner,
)

HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings(tmp_path):
    return SQLitePersistenceSettings(
        db_path=str(tmp_path / "test.db"), busy_timeout_ms=5000
    )


@pytest.fixture
def conn(settings):
    init_database(settings)
    c = get_connection(settings)
    MigrationRunner().migrate(c, settings)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_prerequisites(c: sqlite3.Connection) -> str:
    """Insert minimal prerequisites and return an event_id for use in tests."""
    c.execute(
        "INSERT INTO creation_artifact_ref (artifact_id, schema_version, content_hash) "
        "VALUES (?, ?, ?)",
        ("a1", 1, HASH_A),
    )
    c.execute(
        "INSERT INTO creation_artifact_ref (artifact_id, schema_version, content_hash) "
        "VALUES (?, ?, ?)",
        ("a2", 1, HASH_B),
    )
    c.execute(
        "INSERT INTO chapter_task ("
        "task_id, schema_version, aggregate_revision, project_id, "
        "chapter_number, status, last_stable_status, "
        "creative_intent_ref_artifact_id, created_at, updated_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "t-ao", 1, 0, "proj-1", 1,
            "PLAN_PREPARING", "PLAN_PREPARING",
            "a1",
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:00:00+00:00",
        ),
    )
    c.execute(
        "INSERT INTO creation_operation ("
        "operation_id, idempotency_key, request_digest, "
        "result_envelope_json, result_envelope_hash, created_at"
        ") VALUES (?, ?, ?, ?, ?, ?)",
        ("op-ao", "key-ao", "digest", "{}", HASH_A, "2026-01-01T00:00:00+00:00"),
    )
    c.execute(
        "INSERT INTO creation_audit_event ("
        "event_id, schema_version, task_id, project_id, event_type, "
        "actor_kind, actor_id, model_run_id, "
        "before_task_revision, after_task_revision, operation_id, created_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "e-ao", 1, "t-ao", "proj-1", "TEST_EVENT",
            "SYSTEM", None, None,
            0, 1, "op-ao", "2026-01-01T00:00:00+00:00",
        ),
    )
    c.execute(
        "INSERT INTO creation_audit_event_source_artifact_ref "
        "(event_id, ordinal, artifact_id) VALUES (?, ?, ?)",
        ("e-ao", 0, "a1"),
    )
    c.execute(
        "INSERT INTO creation_audit_event_object_ref "
        "(event_id, ordinal, artifact_id) VALUES (?, ?, ?)",
        ("e-ao", 0, "a2"),
    )
    c.commit()
    return "e-ao"


# ---------------------------------------------------------------------------
# creation_audit_event
# ---------------------------------------------------------------------------


class TestAuditEventAppendOnly:
    def test_audit_event_insert_ok(self, conn) -> None:
        _insert_prerequisites(conn)
        # Insert is allowed (already done in prerequisites)

    def test_audit_event_no_update(self, conn) -> None:
        _insert_prerequisites(conn)
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                "UPDATE creation_audit_event SET event_type = ? WHERE event_id = ?",
                ("CHANGED", "e-ao"),
            )

    def test_audit_event_no_delete(self, conn) -> None:
        _insert_prerequisites(conn)
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM creation_audit_event WHERE event_id = ?", ("e-ao",))


# ---------------------------------------------------------------------------
# creation_audit_event_source_artifact_ref
# ---------------------------------------------------------------------------


class TestSourceArtifactRefAppendOnly:
    def test_source_ref_no_update(self, conn) -> None:
        _insert_prerequisites(conn)
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                "UPDATE creation_audit_event_source_artifact_ref SET ordinal = ? "
                "WHERE event_id = ? AND ordinal = ?",
                (1, "e-ao", 0),
            )

    def test_source_ref_no_delete(self, conn) -> None:
        _insert_prerequisites(conn)
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                "DELETE FROM creation_audit_event_source_artifact_ref "
                "WHERE event_id = ? AND ordinal = ?",
                ("e-ao", 0),
            )


# ---------------------------------------------------------------------------
# creation_audit_event_object_ref
# ---------------------------------------------------------------------------


class TestObjectRefAppendOnly:
    def test_object_ref_no_update(self, conn) -> None:
        _insert_prerequisites(conn)
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                "UPDATE creation_audit_event_object_ref SET ordinal = ? "
                "WHERE event_id = ? AND ordinal = ?",
                (1, "e-ao", 0),
            )

    def test_object_ref_no_delete(self, conn) -> None:
        _insert_prerequisites(conn)
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                "DELETE FROM creation_audit_event_object_ref "
                "WHERE event_id = ? AND ordinal = ?",
                ("e-ao", 0),
            )
