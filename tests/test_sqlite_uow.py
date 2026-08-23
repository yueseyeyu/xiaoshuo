"""Tests for SqliteCreationUnitOfWork — commit, rollback, isolation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from xiaoshuo.domain.creation import (
    SCHEMA_VERSION,
    ArtifactRef,
    ChapterTask,
    ChapterTaskStatus,
)
from xiaoshuo.infrastructure.persistence.sqlite.settings import (
    SQLitePersistenceSettings,
)
from xiaoshuo.infrastructure.persistence.sqlite.connection import get_connection
from xiaoshuo.infrastructure.persistence.sqlite.maintenance import init_database
from xiaoshuo.infrastructure.persistence.sqlite.migration_runner import (
    MigrationRunner,
)
from xiaoshuo.infrastructure.persistence.sqlite.uow import (
    SqliteCreationUnitOfWork,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
HASH_A = "sha256:" + "a" * 64


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def ref(artifact_id: str = "a1") -> ArtifactRef:
    return ArtifactRef(artifact_id, 1, HASH_A)


def make_task(task_id: str = "task-1", **overrides: object) -> ChapterTask:
    values: dict[str, object] = {
        "task_id": task_id,
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
def db_conn(settings):
    init_database(settings)
    conn = get_connection(settings)
    MigrationRunner().migrate(conn, settings)
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# UoW tests
# ---------------------------------------------------------------------------


class TestUnitOfWork:
    def test_commit_persists(self, db_conn, settings) -> None:
        """Add via UoW, commit, load via new UoW sees it."""
        uow1 = SqliteCreationUnitOfWork(db_conn)
        uow1.tasks.add(make_task("task-commit"))
        uow1.commit()

        # Read with a fresh connection to verify persistence
        conn2 = get_connection(settings, read_only=True)
        try:
            uow2 = SqliteCreationUnitOfWork(conn2)
            loaded = uow2.tasks.get("task-commit")
            assert loaded is not None
            assert loaded.task_id == "task-commit"
        finally:
            conn2.close()

    def test_rollback_discards(self, db_conn, settings) -> None:
        """Add via UoW, rollback, load via new UoW returns None."""
        uow1 = SqliteCreationUnitOfWork(db_conn)
        uow1.tasks.add(make_task("task-rollback"))
        uow1.rollback()

        conn2 = get_connection(settings, read_only=True)
        try:
            uow2 = SqliteCreationUnitOfWork(conn2)
            loaded = uow2.tasks.get("task-rollback")
            assert loaded is None
        finally:
            conn2.close()

    def test_same_transaction_visible(self, db_conn) -> None:
        """Add then get in same UoW sees the task (uncommitted visibility)."""
        uow = SqliteCreationUnitOfWork(db_conn)
        uow.tasks.add(make_task("task-same-tx"))
        loaded = uow.tasks.get("task-same-tx")
        assert loaded is not None
        assert loaded.task_id == "task-same-tx"

    def test_cross_uow_isolation(self, db_conn, settings) -> None:
        """Add in UoW1 without commit, UoW2 doesn't see it."""
        uow1 = SqliteCreationUnitOfWork(db_conn)
        uow1.tasks.add(make_task("task-uncommitted"))

        conn2 = get_connection(settings)
        try:
            uow2 = SqliteCreationUnitOfWork(conn2)
            loaded = uow2.tasks.get("task-uncommitted")
            assert loaded is None
        finally:
            conn2.close()
