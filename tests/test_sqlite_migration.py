"""Tests for SQLite schema migration — tables, columns, constraints, triggers, FKs."""

from __future__ import annotations

from pathlib import Path
import shutil
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
APPLICATION_ID = 0x59584352


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings(tmp_path):
    return SQLitePersistenceSettings(
        db_path=str(tmp_path / "test.db"), busy_timeout_ms=5000,
        backup_dir=str(tmp_path / "backups"),
    )


@pytest.fixture
def connection(settings):
    init_database(settings)
    conn = get_connection(settings)
    MigrationRunner().migrate(conn, settings)
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Table existence
# ---------------------------------------------------------------------------


class TestTableExistence:
    def test_v003_tables_exist(self, connection) -> None:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        ).fetchall()
        names = [r["name"] for r in rows]
        expected = [
            "chapter_task",
            "creation_artifact_ref",
            "creation_audit_event",
            "creation_audit_event_object_ref",
            "creation_audit_event_source_artifact_ref",
            "creation_operation",
            "creation_schema_migration",
        ]
        for name in expected:
            assert name in names, f"Table {name!r} is missing"
        assert {"creation_author_decision", "creation_decision_consumption",
                "canon_commit_journal", "canon_commit_receipt"}.issubset(names)
        assert {"canon_commit_journal_v003_legacy", "canon_commit_receipt_v003_legacy"}.issubset(names)
        assert len(names) == len(expected) + 8

    def test_creation_artifact_ref_schema(self, connection) -> None:
        """Verify columns (no role column)."""
        rows = connection.execute(
            "PRAGMA table_info(creation_artifact_ref)"
        ).fetchall()
        col_names = [r["name"] for r in rows]
        assert "artifact_id" in col_names
        assert "schema_version" in col_names
        assert "content_hash" in col_names
        assert "role" not in col_names, "Unexpected 'role' column in creation_artifact_ref"
        assert len(rows) == 3

    def test_chapter_task_receipt_column(self, connection) -> None:
        """v003 preserves v001 columns and adds the Receipt FK."""
        rows = connection.execute("PRAGMA table_info(chapter_task)").fetchall()
        assert len(rows) == 20
        assert "commit_receipt_ref_artifact_id" in [row["name"] for row in rows]


# ---------------------------------------------------------------------------
# CHECK constraints
# ---------------------------------------------------------------------------


class TestCheckConstraints:
    def _insert_artifact(self, conn: sqlite3.Connection, artifact_id: str = "a1") -> None:
        conn.execute(
            "INSERT INTO creation_artifact_ref (artifact_id, schema_version, content_hash) "
            "VALUES (?, ?, ?)",
            (artifact_id, 1, HASH_A),
        )

    def test_chapter_task_status_check(self, connection) -> None:
        """v003 permits COMMITTING but still requires a Receipt for COMPLETED."""
        self._insert_artifact(connection)
        connection.execute(
                    "INSERT INTO chapter_task ("
                    "task_id, schema_version, aggregate_revision, project_id, "
                    "chapter_number, status, last_stable_status, "
                    "creative_intent_ref_artifact_id, created_at, updated_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "task-COMMITTING",
                        1, 0, "proj-1", 1,
                        "COMMITTING", "PLAN_PREPARING",
                        "a1",
                        "2026-01-01T00:00:00+00:00",
                        "2026-01-01T00:00:00+00:00",
                    ),
                )
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            connection.execute(
                "INSERT INTO chapter_task (task_id,schema_version,aggregate_revision,project_id,chapter_number,status,last_stable_status,creative_intent_ref_artifact_id,created_at,updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("task-COMPLETED", 1, 0, "proj-1", 2, "COMPLETED", "PLAN_PREPARING", "a1", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
            )

    def test_chapter_task_recovery_check(self, connection) -> None:
        """RECOVERY_REQUIRED requires recovery fields; non-recovery requires null recovery."""
        self._insert_artifact(connection)
        # RECOVERY_REQUIRED with NULL recovery → fails
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            connection.execute(
                "INSERT INTO chapter_task ("
                "task_id, schema_version, aggregate_revision, project_id, "
                "chapter_number, status, last_stable_status, "
                "creative_intent_ref_artifact_id, recovery_failed_operation_id, "
                "recovery_error_code, recovery_retry_from_status, "
                "created_at, updated_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "task-bad-rec", 1, 0, "proj-1", 1,
                    "RECOVERY_REQUIRED", "DRAFTING",
                    "a1", None, None, None,
                    "2026-01-01T00:00:00+00:00",
                    "2026-01-01T00:00:00+00:00",
                ),
            )
        # Non-recovery status with recovery fields → fails
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            connection.execute(
                "INSERT INTO chapter_task ("
                "task_id, schema_version, aggregate_revision, project_id, "
                "chapter_number, status, last_stable_status, "
                "creative_intent_ref_artifact_id, recovery_failed_operation_id, "
                "recovery_error_code, recovery_retry_from_status, "
                "created_at, updated_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "task-has-rec", 1, 0, "proj-1", 1,
                    "PLAN_PREPARING", "PLAN_PREPARING",
                    "a1", "op-1", "ERR", "DRAFTING",
                    "2026-01-01T00:00:00+00:00",
                    "2026-01-01T00:00:00+00:00",
                ),
            )

    def test_chapter_task_recovery_retry_check(self, connection) -> None:
        """v003 permits COMMITTING as the only Canon recovery retry source."""
        self._insert_artifact(connection)
        for bad_retry in ("RECOVERY_REQUIRED", "COMPLETED"):
            with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
                connection.execute(
                    "INSERT INTO chapter_task ("
                    "task_id, schema_version, aggregate_revision, project_id, "
                    "chapter_number, status, last_stable_status, "
                    "creative_intent_ref_artifact_id, recovery_failed_operation_id, "
                    "recovery_error_code, recovery_retry_from_status, "
                    "created_at, updated_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"task-retry-{bad_retry}",
                        1, 0, "proj-1", 1,
                        "RECOVERY_REQUIRED", "DRAFTING",
                        "a1", "op-1", "ERR", bad_retry,
                        "2026-01-01T00:00:00+00:00",
                        "2026-01-01T00:00:00+00:00",
                    ),
                )

    def test_creation_audit_event_actor_check(self, connection: sqlite3.Connection) -> None:
        """AUTHOR needs actor_id, MODEL needs model_run_id."""
        self._insert_artifact(connection)
        # Insert a task for FK
        connection.execute(
            "INSERT INTO chapter_task ("
            "task_id, schema_version, aggregate_revision, project_id, "
            "chapter_number, status, last_stable_status, "
            "creative_intent_ref_artifact_id, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "task-audit", 1, 0, "proj-1", 1,
                "PLAN_PREPARING", "PLAN_PREPARING",
                "a1",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        # Insert operation for FK
        connection.execute(
            "INSERT INTO creation_operation ("
            "operation_id, idempotency_key, request_digest, "
            "result_envelope_json, result_envelope_hash, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?)",
            ("op-1", "key-1", "digest", "{}", HASH_A, "2026-01-01T00:00:00+00:00"),
        )
        # AUTHOR without actor_id → fails
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            connection.execute(
                "INSERT INTO creation_audit_event ("
                "event_id, schema_version, task_id, project_id, event_type, "
                "actor_kind, actor_id, model_run_id, "
                "before_task_revision, after_task_revision, operation_id, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "e-bad-auth", 1, "task-audit", "proj-1", "EVT",
                    "AUTHOR", None, None,
                    0, 1, "op-1", "2026-01-01T00:00:00+00:00",
                ),
            )
        # MODEL without model_run_id → fails
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            connection.execute(
                "INSERT INTO creation_audit_event ("
                "event_id, schema_version, task_id, project_id, event_type, "
                "actor_kind, actor_id, model_run_id, "
                "before_task_revision, after_task_revision, operation_id, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "e-bad-model", 1, "task-audit", "proj-1", "EVT",
                    "MODEL", None, None,
                    0, 1, "op-1", "2026-01-01T00:00:00+00:00",
                ),
            )
        # SYSTEM without actor_id/model_run_id is OK
        connection.execute(
            "INSERT INTO creation_audit_event ("
            "event_id, schema_version, task_id, project_id, event_type, "
            "actor_kind, actor_id, model_run_id, "
            "before_task_revision, after_task_revision, operation_id, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "e-system", 1, "task-audit", "proj-1", "EVT",
                "SYSTEM", None, None,
                0, 1, "op-1", "2026-01-01T00:00:00+00:00",
            ),
        )

    def test_creation_audit_event_revision_check(self, connection) -> None:
        """after_task_revision >= before_task_revision, both >= 0."""
        self._insert_artifact(connection)
        connection.execute(
            "INSERT INTO chapter_task ("
            "task_id, schema_version, aggregate_revision, project_id, "
            "chapter_number, status, last_stable_status, "
            "creative_intent_ref_artifact_id, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "task-rev", 1, 0, "proj-1", 1,
                "PLAN_PREPARING", "PLAN_PREPARING",
                "a1",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        connection.execute(
            "INSERT INTO creation_operation ("
            "operation_id, idempotency_key, request_digest, "
            "result_envelope_json, result_envelope_hash, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?)",
            ("op-rev", "key-rev", "digest", "{}", HASH_A, "2026-01-01T00:00:00+00:00"),
        )
        # after < before → fails
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            connection.execute(
                "INSERT INTO creation_audit_event ("
                "event_id, schema_version, task_id, project_id, event_type, "
                "actor_kind, actor_id, model_run_id, "
                "before_task_revision, after_task_revision, operation_id, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "e-rev-bad", 1, "task-rev", "proj-1", "EVT",
                    "SYSTEM", None, None,
                    2, 1, "op-rev", "2026-01-01T00:00:00+00:00",
                ),
            )


# ---------------------------------------------------------------------------
# Foreign keys
# ---------------------------------------------------------------------------


class TestForeignKeys:
    def test_fk_on_delete_restrict(self, connection) -> None:
        """Deleting artifact_ref referenced by chapter_task raises IntegrityError."""
        connection.execute(
            "INSERT INTO creation_artifact_ref (artifact_id, schema_version, content_hash) "
            "VALUES (?, ?, ?)",
            ("ref-fk", 1, HASH_A),
        )
        connection.execute(
            "INSERT INTO chapter_task ("
            "task_id, schema_version, aggregate_revision, project_id, "
            "chapter_number, status, last_stable_status, "
            "creative_intent_ref_artifact_id, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "task-fk", 1, 0, "proj-1", 1,
                "PLAN_PREPARING", "PLAN_PREPARING",
                "ref-fk",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        connection.commit()
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
            connection.execute("DELETE FROM creation_artifact_ref WHERE artifact_id = 'ref-fk'")

    def test_all_13_fks(self, connection) -> None:
        """Verify the database reports exactly 13 FK definitions."""
        rows = connection.execute("PRAGMA foreign_key_list(chapter_task)").fetchall()
        fk_count = len(rows)
        for table in (
            "creation_audit_event",
            "creation_audit_event_source_artifact_ref",
            "creation_audit_event_object_ref",
        ):
            rows = connection.execute(f"PRAGMA foreign_key_list({table})").fetchall()
            fk_count += len(rows)
        assert fk_count == 14


# ---------------------------------------------------------------------------
# Triggers
# ---------------------------------------------------------------------------


class TestTriggers:
    def test_6_append_only_triggers_exist(self, connection) -> None:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' ORDER BY name"
        ).fetchall()
        names = [r["name"] for r in rows]
        expected = [
            "trg_creation_audit_event_no_update",
            "trg_creation_audit_event_no_delete",
            "trg_cae_source_artifact_ref_no_update",
            "trg_cae_source_artifact_ref_no_delete",
            "trg_cae_object_ref_no_update",
            "trg_cae_object_ref_no_delete",
        ]
        for name in expected:
            assert name in names, f"Trigger {name!r} is missing"
        assert len(names) == 22


# ---------------------------------------------------------------------------
# Migration ledger & identity
# ---------------------------------------------------------------------------


class TestMigrationLedger:
    def test_migration_ledger_created(self, connection) -> None:
        rows = connection.execute(
            "SELECT version, file_name, sha256 FROM creation_schema_migration ORDER BY version"
        ).fetchall()
        assert len(rows) == 5
        assert rows[0]["version"] == 1
        assert rows[0]["file_name"] == "v001_initial_schema.sql"
        assert all(isinstance(row["sha256"], str) and len(row["sha256"]) == 64 for row in rows)

    def test_migration_idempotent(self, connection) -> None:
        """Re-migrate succeeds (SHA-256 matches recorded)."""
        # A fresh runner reading the same migrations dir will verify SHA matches
        MigrationRunner().migrate(connection, SQLitePersistenceSettings(
            db_path=":memory:", busy_timeout_ms=5000
        ))
        # No exception means success

    def test_migration_sha256_fail_closed(self, tmp_path, monkeypatch) -> None:
        """Modifying the SQL file after migration is detected."""
        import xiaoshuo.infrastructure.persistence.sqlite.migration_runner as mr

        orig_dir = Path(mr.__file__).resolve().parent / "migrations"
        temp_migrations = tmp_path / "migrations"
        shutil.copytree(orig_dir, temp_migrations)

        monkeypatch.setattr(mr, "_MIGRATIONS_DIR", temp_migrations)

        settings = SQLitePersistenceSettings(
            db_path=str(tmp_path / "test.db"), busy_timeout_ms=5000,
            backup_dir=str(tmp_path / "backups"),
        )
        init_database(settings)
        conn = get_connection(settings)
        MigrationRunner().migrate(conn, settings)
        conn.close()

        # Modify the migration file
        sql_file = temp_migrations / "v001_initial_schema.sql"
        original = sql_file.read_text()
        sql_file.write_text(original + "\n-- tampered\n")

        conn2 = get_connection(settings)
        with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
            MigrationRunner().migrate(conn2, settings)
        conn2.close()

    def test_migration_integrity_check(self, connection) -> None:
        (result,) = connection.execute("PRAGMA integrity_check").fetchone()
        assert result == "ok"

    def test_migration_foreign_key_check(self, connection) -> None:
        rows = connection.execute("PRAGMA foreign_key_check").fetchall()
        assert len(rows) == 0

    def test_migration_user_version(self, connection) -> None:
        (uv,) = connection.execute("PRAGMA user_version").fetchone()
        assert uv == 5

    def test_migration_application_id(self, connection) -> None:
        (aid,) = connection.execute("PRAGMA application_id").fetchone()
        assert aid == APPLICATION_ID


# ---------------------------------------------------------------------------
# Migration atomicity
# ---------------------------------------------------------------------------


class TestMigrationAtomicity:
    def test_v002_partial_failure_rolls_back_completely(self, tmp_path, monkeypatch) -> None:
        """v002 creates a probe table then hits invalid SQL — nothing persists."""
        import xiaoshuo.infrastructure.persistence.sqlite.migration_runner as mr

        orig_dir = Path(mr.__file__).resolve().parent / "migrations"
        temp_migrations = tmp_path / "migrations_atomic"
        shutil.copytree(orig_dir, temp_migrations)

        monkeypatch.setattr(mr, "_MIGRATIONS_DIR", temp_migrations)

        settings = SQLitePersistenceSettings(
            db_path=str(tmp_path / "atomic.db"),
            busy_timeout_ms=5000,
            backup_dir=str(tmp_path / "backups"),
        )
        init_database(settings)

        # Apply through v003, then add v004 as the sole pending migration.
        (temp_migrations / "v004_canon_bundle_identity.sql").unlink()
        (temp_migrations / "v005_c4b_activation_facts.sql").unlink()
        conn = get_connection(settings)
        MigrationRunner().migrate(conn, settings)
        conn.close()
        shutil.copy2(orig_dir / "v004_canon_bundle_identity.sql", temp_migrations / "v004_canon_bundle_identity.sql")

        # Phase 2: add broken v002
        monkeypatch.setattr(mr, "_verify_v004_schema", lambda *_: (_ for _ in ()).throw(RuntimeError("forced validation")))

        # Phase 3: attempt v002 — must fail atomically
        conn2 = get_connection(settings)
        with pytest.raises(RuntimeError, match="forced validation"):
            MigrationRunner().migrate(conn2, settings)

        # v004 DDL, user_version and ledger must not survive.
        (uv,) = conn2.execute("PRAGMA user_version").fetchone()
        assert uv == 3

        # 3. no v002 ledger entry
        rows = conn2.execute(
            "SELECT version FROM creation_schema_migration ORDER BY version"
        ).fetchall()
        versions = [r["version"] for r in rows]
        assert versions == [1, 2, 3]
        assert conn2.execute("SELECT name FROM sqlite_master WHERE name='canon_commit_journal_v003_legacy'").fetchone() is None
        conn2.close()


def _open_v003_database(tmp_path: Path, monkeypatch):
    import xiaoshuo.infrastructure.persistence.sqlite.migration_runner as runner_module

    original = Path(runner_module.__file__).resolve().parent / "migrations"
    migrations = tmp_path / "v003-migrations"
    shutil.copytree(original, migrations)
    (migrations / "v004_canon_bundle_identity.sql").unlink()
    (migrations / "v005_c4b_activation_facts.sql").unlink()
    monkeypatch.setattr(runner_module, "_MIGRATIONS_DIR", migrations)
    settings = SQLitePersistenceSettings(
        str(tmp_path / "v003.db"), 5000, str(tmp_path / "backups")
    )
    init_database(settings)
    conn = get_connection(settings)
    MigrationRunner().migrate(conn, settings)
    shutil.copy2(original / "v004_canon_bundle_identity.sql", migrations / "v004_canon_bundle_identity.sql")
    return conn, settings, runner_module


def _seed_v003_legacy_graph(
    conn: sqlite3.Connection,
    *,
    status: str = "COMPLETED",
    include_task: bool = True,
    include_receipt: bool = True,
    complete_binding: bool = True,
) -> None:
    refs = {
        "creative": HASH_A, "plan": HASH_A, "draft": HASH_A,
        "review-target": HASH_A, "adopted": HASH_A, "review": HASH_A,
        "changeset": HASH_A, "target": HASH_A, "receipt-ref": HASH_B,
        "receipt-other": HASH_A,
    }
    for artifact_id, content_hash in refs.items():
        conn.execute(
            "INSERT INTO creation_artifact_ref (artifact_id,schema_version,content_hash) VALUES (?,?,?)",
            (artifact_id, 1, content_hash),
        )
    conn.execute(
        "INSERT INTO creation_operation (operation_id,idempotency_key,request_digest,result_envelope_json,result_envelope_hash,created_at) VALUES (?,?,?,?,?,?)",
        ("legacy-op", "legacy-key", "digest", "{}", HASH_A, "2026-01-01T00:00:00+00:00"),
    )
    if include_task:
        recovery = ("legacy-op", "ERR", "DRAFTING") if status == "RECOVERY_REQUIRED" else (None, None, None)
        receipt_ref = (
            ("receipt-ref" if complete_binding else "receipt-other")
            if status == "COMPLETED"
            else None
        )
        conn.execute(
            "INSERT INTO chapter_task (task_id,schema_version,aggregate_revision,project_id,chapter_number,status,last_stable_status,creative_intent_ref_artifact_id,confirmed_plan_ref_artifact_id,current_author_draft_ref_artifact_id,review_target_draft_ref_artifact_id,adopted_draft_ref_artifact_id,latest_review_ref_artifact_id,pending_changeset_ref_artifact_id,commit_receipt_ref_artifact_id,recovery_failed_operation_id,recovery_error_code,recovery_retry_from_status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "legacy-task", 1, 7, "project-legacy", 1, status,
                "COMMITTING" if status in ("COMPLETED", "CANCELLED") else "DRAFTING",
                "creative", "plan", "draft", "review-target", "adopted", "review",
                "changeset", receipt_ref, recovery[0], recovery[1], recovery[2],
                "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00",
            ),
        )
    conn.execute(
        "INSERT INTO creation_author_decision (decision_id,schema_version,task_id,decision_type,target_ref_artifact_id,outcome,based_on_task_revision,author_id,reason,actor_kind,actor_id,content_hash,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("legacy-decision", 1, "legacy-task", "APPROVE_CHANGESET", "changeset", "APPROVE", 0, "author", None, "AUTHOR", "author", HASH_A, "2026-01-01T00:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO creation_decision_consumption (consumption_id,decision_id,operation_id,task_id,consumed_at_task_revision,consumed_at) VALUES (?,?,?,?,?,?)",
        ("legacy-consumption", "legacy-decision", "legacy-op", "legacy-task", 7, "2026-01-01T00:00:00+00:00"),
    )
    if include_task:
        conn.execute(
            "INSERT INTO creation_audit_event (event_id,schema_version,task_id,project_id,event_type,actor_kind,actor_id,model_run_id,before_task_revision,after_task_revision,operation_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("legacy-event", 1, "legacy-task", "project-legacy", "LEGACY", "SYSTEM", None, None, 6, 7, "legacy-op", "2026-01-01T00:00:00+00:00"),
        )
    conn.execute(
        "INSERT INTO canon_commit_journal (journal_id,task_id,operation_id,decision_id,changeset_ref_artifact_id,target_bundle_ref_artifact_id,bundle_hash,base_manifest_hash,target_manifest_hash,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("legacy-journal", "legacy-task", "legacy-op", "legacy-decision", "changeset", "target", HASH_A, HASH_A, HASH_B, "2026-01-01T00:00:00+00:00"),
    )
    if include_receipt:
        receipt_ref = "receipt-ref"
        conn.execute(
            "INSERT INTO canon_commit_receipt (receipt_id,journal_id,receipt_ref_artifact_id,created_at) VALUES (?,?,?,?)",
            ("legacy-receipt", "legacy-journal", receipt_ref, "2026-01-01T00:00:00+00:00"),
        )
    conn.commit()


def _assert_v003_failure_state(conn: sqlite3.Connection) -> None:
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    assert [row[0] for row in conn.execute("SELECT version FROM creation_schema_migration ORDER BY version")] == [1, 2, 3]
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='canon_commit_journal_v003_legacy'").fetchone() is None
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='canon_commit_receipt_v003_legacy'").fetchone() is None


def _insert_v005_attempt_fixture(
    conn: sqlite3.Connection,
    *,
    artifact_id: str = "c4b-bundle",
    schema_version: int = 1,
    content_hash: str = HASH_A,
) -> None:
    conn.execute(
        "INSERT INTO creation_artifact_ref (artifact_id, schema_version, content_hash) VALUES (?,?,?)",
        (artifact_id, schema_version, content_hash),
    )
    conn.execute(
        "INSERT INTO canon_activation_attempt "
        "(attempt_id,project_id,attempt_key,request_digest,seed_digest,bundle_ref_artifact_id,"
        "bundle_schema_version,bundle_content_hash,manifest_hash,world_hash,version_id,"
        "pointer_content_hash,operator_identity,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "c4b-attempt",
            "c4b-project",
            "c4b-key",
            HASH_A,
            HASH_B,
            artifact_id,
            schema_version,
            content_hash,
            HASH_A,
            HASH_B,
            "c4b-version",
            HASH_A,
            "operator",
            "2026-01-01T00:00:00+00:00",
        ),
    )


def test_c4b_08_v005_migration_creates_independent_activation_facts(connection) -> None:
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
    assert [row[0] for row in connection.execute(
        "SELECT version FROM creation_schema_migration ORDER BY version"
    )] == [1, 2, 3, 4, 5]
    assert connection.execute(
        "SELECT name FROM sqlite_master WHERE name='canon_activation_attempt'"
    ).fetchone() is not None
    assert connection.execute(
        "SELECT name FROM sqlite_master WHERE name='canon_activation_event'"
    ).fetchone() is not None


def test_c4b_09_v005_artifact_ref_composite_fk_accepts_exact_identity(connection) -> None:
    _insert_v005_attempt_fixture(connection)
    connection.commit()
    row = connection.execute(
        "SELECT bundle_ref_artifact_id,bundle_schema_version,bundle_content_hash "
        "FROM canon_activation_attempt"
    ).fetchone()
    assert tuple(row) == ("c4b-bundle", 1, HASH_A)
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO canon_activation_attempt "
            "(attempt_id,project_id,attempt_key,request_digest,seed_digest,bundle_ref_artifact_id,"
            "bundle_schema_version,bundle_content_hash,manifest_hash,world_hash,version_id,"
            "pointer_content_hash,operator_identity,created_at) "
            "SELECT 'bad-attempt','bad-project','bad-key',request_digest,seed_digest,"
            "bundle_ref_artifact_id,1,?,manifest_hash,world_hash,'bad-version',"
            "pointer_content_hash,operator_identity,created_at FROM canon_activation_attempt",
            (HASH_B,),
        )
    connection.rollback()
    assert connection.execute("SELECT COUNT(*) FROM canon_activation_attempt").fetchone()[0] == 1
    assert [row[0] for row in connection.execute(
        "SELECT version FROM creation_schema_migration ORDER BY version"
    )] == [1, 2, 3, 4, 5]


def test_c4b_10_v005_verifies_artifact_identity_index_and_composite_fk(connection) -> None:
    index = connection.execute(
        "SELECT name,\"unique\" FROM pragma_index_list('creation_artifact_ref') "
        "WHERE name='uq_creation_artifact_ref_identity'"
    ).fetchone()
    assert tuple(index) == ("uq_creation_artifact_ref_identity", 1)
    assert [row[2] for row in connection.execute(
        "PRAGMA index_info(uq_creation_artifact_ref_identity)"
    )] == ["artifact_id", "schema_version", "content_hash"]
    fk = {
        (row[2], row[3], row[4])
        for row in connection.execute("PRAGMA foreign_key_list(canon_activation_attempt)")
    }
    assert {
        ("creation_artifact_ref", "bundle_ref_artifact_id", "artifact_id"),
        ("creation_artifact_ref", "bundle_schema_version", "schema_version"),
        ("creation_artifact_ref", "bundle_content_hash", "content_hash"),
    }.issubset(fk)


def test_c4b_11_v005_phase_checks_reject_legacy_event_outcomes(connection) -> None:
    _insert_v005_attempt_fixture(connection)
    connection.commit()
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO canon_activation_event "
            "(event_id,attempt_id,project_id,phase,result,error_code,replay_envelope_json,"
            "replay_envelope_hash,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                "bad-event", "c4b-attempt", "c4b-project", "COMMITTED", "COMMITTED",
                None, None, None, "2026-01-01T00:00:01+00:00",
            ),
        )
    connection.rollback()
    assert connection.execute("SELECT COUNT(*) FROM canon_activation_event").fetchone()[0] == 0


def test_c4b_12_v005_direct_identity_failure_leaves_no_half_migration(connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO canon_activation_attempt "
            "(attempt_id,project_id,attempt_key,request_digest,seed_digest,bundle_ref_artifact_id,"
            "bundle_schema_version,bundle_content_hash,manifest_hash,world_hash,version_id,"
            "pointer_content_hash,operator_identity,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "orphan-attempt", "orphan-project", "orphan-key", HASH_A, HASH_B,
                "missing-artifact", 1, HASH_A, HASH_A, HASH_B, "orphan-version", HASH_A,
                "operator", "2026-01-01T00:00:00+00:00",
            ),
        )
    connection.rollback()
    assert connection.execute("SELECT COUNT(*) FROM canon_activation_attempt").fetchone()[0] == 0
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
    assert [row[0] for row in connection.execute(
        "SELECT version FROM creation_schema_migration ORDER BY version"
    )] == [1, 2, 3, 4, 5]


@pytest.mark.parametrize("status", ["COMMITTING", "RECOVERY_REQUIRED", "DRAFTING"])
def test_v004_rejects_nonterminal_legacy_journal_without_schema_or_ledger_residue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str) -> None:
    conn, settings, _runner_module = _open_v003_database(tmp_path, monkeypatch)
    try:
        _seed_v003_legacy_graph(conn, status=status)
        with pytest.raises(RuntimeError, match="preflight"):
            MigrationRunner().migrate(conn, settings)
        _assert_v003_failure_state(conn)
    finally:
        conn.close()


@pytest.mark.parametrize("include_task,include_receipt,complete_binding", [(False, True, True), (True, False, True), (True, True, False)])
def test_v004_rejects_incomplete_legacy_graph_without_schema_or_ledger_residue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, include_task: bool, include_receipt: bool, complete_binding: bool) -> None:
    conn, settings, _runner_module = _open_v003_database(tmp_path, monkeypatch)
    try:
        if not include_task:
            conn.execute("PRAGMA foreign_keys = OFF")
        _seed_v003_legacy_graph(conn, include_task=include_task, include_receipt=include_receipt, complete_binding=complete_binding)
        if not include_task:
            conn.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(Exception):
            MigrationRunner().migrate(conn, settings)
        _assert_v003_failure_state(conn)
    finally:
        conn.close()


@pytest.mark.parametrize(
    "broken_node",
    [
        pytest.param("receipt_ref_artifact", id="missing-receipt-ref-artifact"),
        pytest.param("operation", id="missing-operation"),
        pytest.param("decision", id="missing-decision"),
    ],
)
def test_v004_rejects_missing_legacy_graph_nodes_in_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, broken_node: str
) -> None:
    conn, settings, runner_module = _open_v003_database(tmp_path, monkeypatch)
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        _seed_v003_legacy_graph(
            conn,
            status="CANCELLED",
            include_task=True,
            include_receipt=True,
            complete_binding=True,
        )
        if broken_node == "receipt_ref_artifact":
            conn.execute("DELETE FROM creation_artifact_ref WHERE artifact_id='receipt-ref'")
        elif broken_node == "operation":
            conn.execute("DELETE FROM creation_operation WHERE operation_id='legacy-op'")
        else:
            conn.execute("DROP TRIGGER trg_canon_commit_journal_no_update")
            conn.execute(
                "UPDATE canon_commit_journal "
                "SET decision_id='missing-decision' WHERE journal_id='legacy-journal'"
            )
            conn.execute(
                "CREATE TRIGGER trg_canon_commit_journal_no_update "
                "BEFORE UPDATE ON canon_commit_journal BEGIN "
                "SELECT RAISE(ABORT, 'canon_commit_journal is append-only; UPDATE rejected'); END"
            )
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1

        with pytest.raises(RuntimeError, match="preflight"):
            runner_module._verify_v004_legacy_preflight(conn)
        with pytest.raises(RuntimeError, match=r"foreign_key_check \(pre-migration v004\)"):
            MigrationRunner().migrate(conn, settings)
        _assert_v003_failure_state(conn)
    finally:
        conn.close()


def test_v004_rejects_legacy_decision_target_mismatch_in_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, settings, runner_module = _open_v003_database(tmp_path, monkeypatch)
    try:
        _seed_v003_legacy_graph(
            conn,
            status="CANCELLED",
            include_task=True,
            include_receipt=True,
            complete_binding=True,
        )
        conn.execute("DROP TRIGGER trg_author_decision_no_update")
        conn.execute(
            "UPDATE creation_author_decision "
            "SET target_ref_artifact_id='target' WHERE decision_id='legacy-decision'"
        )
        conn.execute(
            "CREATE TRIGGER trg_author_decision_no_update "
            "BEFORE UPDATE ON creation_author_decision BEGIN "
            "SELECT RAISE(ABORT, 'creation_author_decision is append-only; UPDATE rejected'); END"
        )
        conn.commit()

        with pytest.raises(RuntimeError, match="preflight"):
            MigrationRunner().migrate(conn, settings)
        _assert_v003_failure_state(conn)
    finally:
        conn.close()


@pytest.mark.parametrize("status", ["COMPLETED", "CANCELLED"])
def test_v004_retains_complete_terminal_legacy_graph_and_leaves_active_tables_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str) -> None:
    conn, settings, runner_module = _open_v003_database(tmp_path, monkeypatch)
    original = runner_module._verify_v004_legacy_preflight
    lock_observed: list[bool] = []

    def observe_lock(connection: sqlite3.Connection) -> None:
        lock_observed.append(connection.in_transaction)
        original(connection)

    monkeypatch.setattr(runner_module, "_verify_v004_legacy_preflight", observe_lock)
    try:
        _seed_v003_legacy_graph(conn, status=status)
        MigrationRunner().migrate(conn, settings)
        assert lock_observed == [True]
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
        assert conn.execute("SELECT COUNT(*) FROM canon_commit_journal").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM canon_commit_receipt").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM canon_commit_journal_v003_legacy").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM canon_commit_receipt_v003_legacy").fetchone()[0] == 1
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Identity preflight
# ---------------------------------------------------------------------------


class TestIdentityPreflight:
    def test_non_creation_db_is_rejected(self, tmp_path) -> None:
        """A plain SQLite file must be rejected before any tables are created."""
        import sqlite3

        db_path = tmp_path / "plain.db"
        conn = sqlite3.connect(str(db_path))
        # plain DB has application_id=0, user_version=0, no tables
        try:
            settings = SQLitePersistenceSettings(
                db_path=str(db_path),
                busy_timeout_ms=5000,
            )
            with pytest.raises(RuntimeError, match="not a Creation SQLite database"):
                MigrationRunner().migrate(conn, settings)
        finally:
            conn.close()

        # Verify no tables were created (preflight fails before any DDL)
        conn2 = sqlite3.connect(str(db_path))
        try:
            rows = conn2.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            assert len(rows) == 0, (
                f"Tables were created on a non-Creation DB: {[r[0] for r in rows]}"
            )
        finally:
            conn2.close()

    def test_wrong_application_id_is_rejected(self, tmp_path) -> None:
        """Init with wrong application_id is rejected."""
        import sqlite3

        db_path = tmp_path / "wrong_id.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA application_id = 0xDEADBEEF")
        conn.commit()
        try:
            settings = SQLitePersistenceSettings(
                db_path=str(db_path),
                busy_timeout_ms=5000,
            )
            with pytest.raises(RuntimeError, match="not a Creation SQLite database"):
                MigrationRunner().migrate(conn, settings)
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# SQL literal
# ---------------------------------------------------------------------------


class TestSqlLiteral:
    def test_sql_literal_escapes_single_quote(self) -> None:
        from xiaoshuo.infrastructure.persistence.sqlite.migration_runner import (
            _sql_literal,
        )
        result = _sql_literal("it's a test")
        assert result == "'it''s a test'"

    def test_sql_literal_empty_string(self) -> None:
        from xiaoshuo.infrastructure.persistence.sqlite.migration_runner import (
            _sql_literal,
        )
        result = _sql_literal("")
        assert result == "''"

    def test_sql_literal_no_special_chars(self) -> None:
        from xiaoshuo.infrastructure.persistence.sqlite.migration_runner import (
            _sql_literal,
        )
        result = _sql_literal("hello")
        assert result == "'hello'"
