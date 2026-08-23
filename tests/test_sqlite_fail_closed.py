"""Fail-closed tests — operations that must reject invalid state or detect tampering."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import shutil
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from xiaoshuo.domain.creation import (
    SCHEMA_VERSION,
    ArtifactRef,
    ChapterTask,
    ChapterTaskStatus,
)
from xiaoshuo.application.creation.errors import (
    RevisionConflict,
    UnsupportedPersistenceBoundary,
)
from xiaoshuo.infrastructure.persistence.sqlite.settings import (
    SQLitePersistenceSettings,
)
from xiaoshuo.infrastructure.persistence.sqlite.connection import get_connection
from xiaoshuo.infrastructure.persistence.sqlite.maintenance import (
    init_database,
)
from xiaoshuo.infrastructure.persistence.sqlite.migration_runner import (
    MigrationRunner,
)
from xiaoshuo.infrastructure.persistence.sqlite.repository import (
    SqliteChapterTaskRepository,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
HASH_A = "sha256:" + "a" * 64


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def ref(artifact_id: str = "a1") -> ArtifactRef:
    return ArtifactRef(artifact_id, SCHEMA_VERSION, HASH_A)


def make_task(**overrides: object) -> ChapterTask:
    values: dict[str, object] = {
        "task_id": "task-1",
        "schema_version": SCHEMA_VERSION,
        "aggregate_revision": 0,
        "project_id": "proj-1",
        "chapter_number": 1,
        "status": ChapterTaskStatus.PLAN_PREPARING,
        "last_stable_status": ChapterTaskStatus.PLAN_PREPARING,
        "creative_intent_ref": ref("ci-1"),
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings(tmp_path):
    return SQLitePersistenceSettings(
        db_path=str(tmp_path / "test.db"), busy_timeout_ms=5000
    )


@pytest.fixture
def repo(settings):
    init_database(settings)
    conn = get_connection(settings)
    MigrationRunner().migrate(conn, settings)
    yield SqliteChapterTaskRepository(conn)
    conn.close()


# ---------------------------------------------------------------------------
# Fail-closed tests
# ---------------------------------------------------------------------------


class TestFailClosed:
    def test_init_rejects_existing_db(self, tmp_path) -> None:
        """init_database raises FileExistsError if DB already exists."""
        settings = SQLitePersistenceSettings(
            db_path=str(tmp_path / "exists.db"), busy_timeout_ms=5000
        )
        init_database(settings)
        with pytest.raises(FileExistsError, match="already exists"):
            init_database(settings)

    def test_committing_add_rejected(self, repo) -> None:
        task = make_task(status=ChapterTaskStatus.COMMITTING)
        with pytest.raises(UnsupportedPersistenceBoundary):
            repo.add(task)

    def test_completed_add_rejected(self, repo) -> None:
        task = make_task(
            status=ChapterTaskStatus.COMPLETED,
            commit_receipt_ref=ref("receipt-1"),
        )
        with pytest.raises(UnsupportedPersistenceBoundary):
            repo.add(task)

    def test_committing_replace_rejected(self, repo) -> None:
        task = make_task(aggregate_revision=0)
        repo.add(task)
        updated = make_task(
            task_id=task.task_id,
            aggregate_revision=1,
            status=ChapterTaskStatus.COMMITTING,
        )
        with pytest.raises(UnsupportedPersistenceBoundary):
            repo.replace(updated, expected_revision=0)

    def test_replace_with_wrong_revision(self, repo) -> None:
        task = make_task(aggregate_revision=0)
        repo.add(task)
        updated = make_task(
            task_id=task.task_id,
            aggregate_revision=1,
        )
        with pytest.raises(RevisionConflict):
            repo.replace(updated, expected_revision=1)

    def test_migration_sql_sha256_mismatch(self, tmp_path, monkeypatch) -> None:
        """Detect SHA-256 mismatch after file modification."""
        import xiaoshuo.infrastructure.persistence.sqlite.migration_runner as mr

        orig_dir = Path(mr.__file__).resolve().parent / "migrations"
        temp_migrations = tmp_path / "migrations"
        shutil.copytree(orig_dir, temp_migrations)

        monkeypatch.setattr(mr, "_MIGRATIONS_DIR", temp_migrations)

        settings = SQLitePersistenceSettings(
            db_path=str(tmp_path / "sha_test.db"), busy_timeout_ms=5000
        )
        init_database(settings)
        conn = get_connection(settings)
        MigrationRunner().migrate(conn, settings)
        conn.close()

        # Tamper with the migration file
        sql_file = temp_migrations / "v001_initial_schema.sql"
        sql_file.write_text(sql_file.read_text() + "\n-- tampered\n")

        conn2 = get_connection(settings)
        with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
            MigrationRunner().migrate(conn2, settings)
        conn2.close()

    def test_migration_failure_rolls_back(self, tmp_path, monkeypatch) -> None:
        """Failed migration doesn't leave partial state."""
        import xiaoshuo.infrastructure.persistence.sqlite.migration_runner as mr

        orig_dir = Path(mr.__file__).resolve().parent / "migrations"
        temp_migrations = tmp_path / "migrations2"
        shutil.copytree(orig_dir, temp_migrations)

        # Add a broken v002 migration
        (temp_migrations / "v002_broken.sql").write_text("THIS IS NOT VALID SQL")

        monkeypatch.setattr(mr, "_MIGRATIONS_DIR", temp_migrations)

        settings = SQLitePersistenceSettings(
            db_path=str(tmp_path / "rollback_test.db"),
            busy_timeout_ms=5000,
            backup_dir=str(tmp_path / "backups"),
        )
        init_database(settings)
        conn = get_connection(settings)

        with pytest.raises(sqlite3.DatabaseError):
            MigrationRunner().migrate(conn, settings)

        # Verify v001 is applied but v002 is not
        rows = conn.execute(
            "SELECT version FROM creation_schema_migration ORDER BY version"
        ).fetchall()
        versions = [r["version"] for r in rows]
        assert versions == [1]
        conn.close()

    def test_auto_backup_requires_backup_dir(self, tmp_path, monkeypatch) -> None:
        """Non-empty DB migration fails without explicit backup_dir."""
        import xiaoshuo.infrastructure.persistence.sqlite.migration_runner as mr

        orig_dir = Path(mr.__file__).resolve().parent / "migrations"
        temp_migrations = tmp_path / "migrations_bkp"
        shutil.copytree(orig_dir, temp_migrations)

        monkeypatch.setattr(mr, "_MIGRATIONS_DIR", temp_migrations)

        settings = SQLitePersistenceSettings(
            db_path=str(tmp_path / "no_bkp.db"),
            busy_timeout_ms=5000,
        )
        init_database(settings)

        # Phase 1: migrate v001 (empty DB, no auto-backup needed)
        conn = get_connection(settings)
        MigrationRunner().migrate(conn, settings)
        conn.close()

        # Phase 2: add v002 — now DB is non-empty, auto-backup must fail
        (temp_migrations / "v002_dummy.sql").write_text(
            "CREATE TABLE dummy_v002 (x INT) STRICT;"
        )

        # Re-open and try v002 — should fail because backup_dir is None
        conn2 = get_connection(settings)
        with pytest.raises(ValueError, match="backup_dir"):
            MigrationRunner().migrate(conn2, settings)
        conn2.close()
