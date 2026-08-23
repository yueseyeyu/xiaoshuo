"""Tests for SqliteChapterTaskRepository — CRUD, revision, status gates, artifact ref registry."""

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
from xiaoshuo.application.creation.errors import (
    ArtifactIdentityConflict,
    RevisionConflict,
    UnsupportedPersistenceBoundary,
)
from xiaoshuo.infrastructure.persistence.sqlite.settings import (
    SQLitePersistenceSettings,
)
from xiaoshuo.infrastructure.persistence.sqlite.connection import get_connection
from xiaoshuo.infrastructure.persistence.sqlite.maintenance import init_database
from xiaoshuo.infrastructure.persistence.sqlite.migration_runner import (
    MigrationRunner,
)
from xiaoshuo.infrastructure.persistence.sqlite.repository import (
    SqliteChapterTaskRepository,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def ref(artifact_id: str = "a1", content_hash: str = HASH_A) -> ArtifactRef:
    return ArtifactRef(artifact_id, SCHEMA_VERSION, content_hash)


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
# CRUD
# ---------------------------------------------------------------------------


class TestCrud:
    def test_add_then_get(self, repo) -> None:
        task = make_task()
        repo.add(task)
        loaded = repo.get(task.task_id)
        assert loaded is not None
        assert loaded.task_id == task.task_id
        assert loaded.status == task.status
        assert loaded.creative_intent_ref == task.creative_intent_ref

    def test_get_not_found(self, repo) -> None:
        assert repo.get("nonexistent") is None

    def test_replace_with_correct_revision(self, repo) -> None:
        task = make_task(aggregate_revision=0)
        repo.add(task)
        updated = make_task(
            task_id=task.task_id,
            aggregate_revision=1,
            status=ChapterTaskStatus.DRAFTING,
            last_stable_status=ChapterTaskStatus.PLAN_PREPARING,
        )
        repo.replace(updated, expected_revision=0)
        loaded = repo.get(task.task_id)
        assert loaded is not None
        assert loaded.status == ChapterTaskStatus.DRAFTING
        assert loaded.aggregate_revision == 1

    def test_replace_with_wrong_revision(self, repo) -> None:
        task = make_task(aggregate_revision=0)
        repo.add(task)
        updated = make_task(
            task_id=task.task_id,
            aggregate_revision=1,
        )
        with pytest.raises(RevisionConflict):
            repo.replace(updated, expected_revision=1)

    def test_replace_nonexistent(self, repo) -> None:
        task = make_task(task_id="ghost")
        with pytest.raises(RevisionConflict, match="not found"):
            repo.replace(task, expected_revision=0)


# ---------------------------------------------------------------------------
# Status gates
# ---------------------------------------------------------------------------


class TestStatusGates:
    def test_add_committing_rejected(self, repo) -> None:
        task = make_task(status=ChapterTaskStatus.COMMITTING)
        with pytest.raises(UnsupportedPersistenceBoundary, match="COMMITTING"):
            repo.add(task)

    def test_add_completed_rejected(self, repo) -> None:
        task = make_task(
            status=ChapterTaskStatus.COMPLETED,
            commit_receipt_ref=ref("receipt-1"),
        )
        with pytest.raises(UnsupportedPersistenceBoundary, match="commit_receipt_ref"):
            repo.add(task)

    def test_replace_committing_rejected(self, repo) -> None:
        task = make_task(aggregate_revision=0)
        repo.add(task)
        updated = make_task(
            task_id=task.task_id,
            aggregate_revision=1,
            status=ChapterTaskStatus.COMMITTING,
        )
        with pytest.raises(UnsupportedPersistenceBoundary, match="COMMITTING"):
            repo.replace(updated, expected_revision=0)


# ---------------------------------------------------------------------------
# Artifact ref registry
# ---------------------------------------------------------------------------


class TestArtifactRefRegistry:
    def test_artifact_ref_registered_on_add(self, repo) -> None:
        task = make_task(creative_intent_ref=ref("ci-reg"))
        repo.add(task)
        # Read from the artifact ref table directly
        row = repo._conn.execute(
            "SELECT * FROM creation_artifact_ref WHERE artifact_id = ?",
            ("ci-reg",),
        ).fetchone()
        assert row is not None
        assert row["artifact_id"] == "ci-reg"

    def test_artifact_ref_conflict(self, repo) -> None:
        """Same artifact_id with different hash raises ArtifactIdentityConflict."""
        task_a = make_task(creative_intent_ref=ref("ci-conflict"))
        repo.add(task_a)
        task_b = make_task(
            task_id="task-2",
            creative_intent_ref=ref("ci-conflict", HASH_B),
        )
        with pytest.raises(ArtifactIdentityConflict, match="already registered"):
            repo.add(task_b)

    def test_artifact_ref_verify_matching(self, repo) -> None:
        """Same artifact_id with same hash is OK."""
        task_a = make_task(creative_intent_ref=ref("ci-match"))
        repo.add(task_a)
        task_b = make_task(
            task_id="task-2b",
            creative_intent_ref=ref("ci-match"),
        )
        # Should not raise
        repo.add(task_b)


# ---------------------------------------------------------------------------
# Receipt boundary
# ---------------------------------------------------------------------------


class TestReceiptBoundary:
    def test_add_rejects_non_null_commit_receipt_ref(self, repo) -> None:
        """Task with non-null commit_receipt_ref rejected even if status is allowed."""
        task = make_task(
            status=ChapterTaskStatus.COMPLETED,
            commit_receipt_ref=ref("receipt-x"),
        )
        with pytest.raises(UnsupportedPersistenceBoundary, match="commit_receipt_ref"):
            repo.add(task)

    def test_replace_rejects_non_null_commit_receipt_ref(self, repo) -> None:
        """replace with non-null commit_receipt_ref rejected."""
        task = make_task(aggregate_revision=0)
        repo.add(task)
        updated = make_task(
            task_id=task.task_id,
            aggregate_revision=1,
            status=ChapterTaskStatus.COMPLETED,
            commit_receipt_ref=ref("receipt-y"),
        )
        with pytest.raises(UnsupportedPersistenceBoundary, match="commit_receipt_ref"):
            repo.replace(updated, expected_revision=0)


# ---------------------------------------------------------------------------
# Conditional replace (single UPDATE with revision WHERE clause)
# ---------------------------------------------------------------------------


class TestConditionalReplace:
    def test_replace_with_stale_revision_rowcount_zero(self, repo, settings) -> None:
        """Conditional UPDATE detects concurrent modification from another connection."""
        task = make_task(task_id="race-task", aggregate_revision=0)
        repo.add(task)
        repo._conn.commit()  # finalize so another connection can write

        # Simulate concurrent write by another connection
        conn2 = get_connection(settings)
        try:
            conn2.execute(
                "UPDATE chapter_task SET aggregate_revision = 99 WHERE task_id = ?",
                ("race-task",),
            )
            conn2.commit()
        finally:
            conn2.close()

        # Now try replace with stale expected_revision=0
        updated = make_task(
            task_id="race-task",
            aggregate_revision=1,
        )
        with pytest.raises(RevisionConflict, match="changed"):
            repo.replace(updated, expected_revision=0)

        # Verify the concurrent write was NOT overwritten
        loaded = repo.get("race-task")
        assert loaded is not None
        assert loaded.aggregate_revision == 99, (
            f"concurrent write was overwritten: {loaded.aggregate_revision}"
        )

    def test_failed_replace_does_not_leak_artifact_ref(self, repo, settings) -> None:
        """Failed replace with new artifact refs leaves no side effects in registry."""
        task = make_task(task_id="leak-task", aggregate_revision=0)
        repo.add(task)
        repo._conn.commit()

        # Concurrent write by another connection
        conn2 = get_connection(settings)
        try:
            conn2.execute(
                "UPDATE chapter_task SET aggregate_revision = 99 WHERE task_id = ?",
                ("leak-task",),
            )
            conn2.commit()
        finally:
            conn2.close()

        # Replace with a NEW creative_intent_ref (never-before-seen artifact_id)
        new_ref_id = "ci-should-not-leak"
        updated = make_task(
            task_id="leak-task",
            aggregate_revision=1,
            creative_intent_ref=ref(new_ref_id),
        )
        with pytest.raises(RevisionConflict, match="changed"):
            repo.replace(updated, expected_revision=0)

        # Verify the new artifact ref was NOT registered
        row = repo._conn.execute(
            "SELECT 1 FROM creation_artifact_ref WHERE artifact_id = ?",
            (new_ref_id,),
        ).fetchone()
        assert row is None, (
            f"Artifact ref {new_ref_id} leaked despite failed replace"
        )
