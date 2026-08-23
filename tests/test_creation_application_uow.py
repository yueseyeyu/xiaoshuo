"""Unit-of-Work contract tests using fake/in-memory implementations.

Verifies the CreationUnitOfWork protocol contract: write visibility
within the same UoW, rollback semantics, commit semantics, conditional
replace with expected_revision, and repository protocol boundaries.
No sqlite3, SQL, or database calls.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from xiaoshuo.domain.creation.models import (
    ArtifactRef,
    ChapterTask,
    ChapterTaskStatus,
)

from xiaoshuo.application.creation.errors import RevisionConflict
from xiaoshuo.application.creation.repository import (
    ChapterTaskRepository,
    CreationUnitOfWork,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
HASH_A = "sha256:" + "a" * 64


# ---------------------------------------------------------------------------
# Fake / in-memory implementations
# ---------------------------------------------------------------------------

def _ref(artifact_id: str = "artifact-1") -> ArtifactRef:
    return ArtifactRef(artifact_id, 1, HASH_A)


def _new_task(task_id: str, revision: int = 0) -> ChapterTask:
    return ChapterTask(
        task_id=task_id,
        schema_version=1,
        aggregate_revision=revision,
        project_id="project-1",
        chapter_number=1,
        status=ChapterTaskStatus.PLAN_PREPARING,
        last_stable_status=ChapterTaskStatus.PLAN_PREPARING,
        creative_intent_ref=_ref("intent-1"),
        confirmed_plan_ref=None,
        current_author_draft_ref=None,
        review_target_draft_ref=None,
        adopted_draft_ref=None,
        latest_review_ref=None,
        pending_changeset_ref=None,
        commit_receipt_ref=None,
        recovery=None,
        created_at=NOW,
        updated_at=NOW,
    )


class FakeChapterTaskRepository:
    """In-memory ChapterTaskRepository that satisfies the protocol."""

    def __init__(self) -> None:
        self._store: dict[str, ChapterTask] = {}

    def get(self, task_id: str) -> ChapterTask | None:
        return self._store.get(task_id)

    def add(self, task: ChapterTask) -> None:
        self._store[task.task_id] = task

    def replace(self, task: ChapterTask, *, expected_revision: int) -> None:
        existing = self._store.get(task.task_id)
        if existing is None:
            raise RevisionConflict(
                f"cannot replace missing task {task.task_id}"
            )
        if existing.aggregate_revision != expected_revision:
            raise RevisionConflict(
                f"expected revision {expected_revision}, "
                f"current revision {existing.aggregate_revision}"
            )
        self._store[task.task_id] = task


class FakeCreationUnitOfWork:
    """In-memory CreationUnitOfWork that satisfies the protocol.

    Uses a two-phase approach: writes go to a staging area during the
    active transaction and are promoted to the committed store on
    commit.  Rollback discards the staging area.
    """

    def __init__(self) -> None:
        self._committed: dict[str, ChapterTask] = {}
        self._staging: dict[str, ChapterTask] | None = None
        self._active = False
        self.tasks = FakeChapterTaskRepository()
        self.audit = _NullRepository()
        self.operations = _NullRepository()

    # -- transaction lifecycle --------------------------------------------

    def _begin(self) -> None:
        assert not self._active, "nested transaction not supported"
        self._staging = dict(self._committed)
        self._active = True
        self.tasks._store = self._staging  # type: ignore[attr-defined]

    def commit(self) -> None:
        assert self._active, "no active transaction"
        self._committed = dict(self._staging)  # type: ignore[arg-type]
        self._staging = None
        self._active = False
        self.tasks._store = self._committed  # type: ignore[attr-defined]

    def rollback(self) -> None:
        assert self._active, "no active transaction"
        self._staging = None
        self._active = False
        self.tasks._store = self._committed  # type: ignore[attr-defined]

    def __enter__(self) -> FakeCreationUnitOfWork:
        self._begin()
        return self

    def __exit__(self, *args: object) -> None:
        if self._active:
            self.rollback()


class _NullRepository:
    """Placeholder satisfying AuditEventRepository / OperationLogRepository."""


# ---------------------------------------------------------------------------
# Tests — add / get
# ---------------------------------------------------------------------------

class TestFakeCreationUnitOfWork:
    """Verify the UoW protocol contract through the fake implementation."""

    def test_add_then_read_within_same_uow(self) -> None:
        uow = FakeCreationUnitOfWork()
        with uow:
            task = _new_task("task-1")
            uow.tasks.add(task)
            found = uow.tasks.get("task-1")
            assert found is task, "add should make task readable within same UoW"

    def test_rollback_discards_uncommitted_add(self) -> None:
        uow = FakeCreationUnitOfWork()
        with uow:
            uow.tasks.add(_new_task("task-1"))
            uow.rollback()
        assert uow.tasks.get("task-1") is None, (
            "rollback should discard uncommitted writes"
        )

    def test_commit_persists_add(self) -> None:
        uow = FakeCreationUnitOfWork()
        with uow:
            task = _new_task("task-1")
            uow.tasks.add(task)
            uow.commit()
        found = uow.tasks.get("task-1")
        assert found is task, "commit should persist writes"

    def test_multiple_adds_visible_after_commit(self) -> None:
        uow = FakeCreationUnitOfWork()
        with uow:
            uow.tasks.add(_new_task("task-a"))
            uow.tasks.add(_new_task("task-b"))
            uow.commit()
        assert uow.tasks.get("task-a") is not None
        assert uow.tasks.get("task-b") is not None

    def test_uncommitted_adds_not_visible_outside_uow(self) -> None:
        uow = FakeCreationUnitOfWork()
        with uow:
            uow.tasks.add(_new_task("task-1"))
        assert uow.tasks.get("task-1") is None, (
            "uncommitted writes must not be visible outside the UoW"
        )

    def test_repository_returns_none_for_missing(self) -> None:
        uow = FakeCreationUnitOfWork()
        with uow:
            assert uow.tasks.get("nonexistent") is None

    def test_no_sqlite3_in_fake(self) -> None:
        import inspect

        source = inspect.getsource(FakeCreationUnitOfWork)
        assert "sqlite3" not in source
        assert "sqlite" not in source.lower()
        assert "PRAGMA" not in source


# ---------------------------------------------------------------------------
# Tests — replace with expected_revision
# ---------------------------------------------------------------------------

class TestFakeReplaceWithExpectedRevision:
    """Verify conditional replace contract with expected_revision."""

    def test_replace_with_correct_revision_succeeds(self) -> None:
        uow = FakeCreationUnitOfWork()
        with uow:
            uow.tasks.add(_new_task("task-1", revision=0))
            v2 = _new_task("task-1", revision=1)
            uow.tasks.replace(v2, expected_revision=0)
            found = uow.tasks.get("task-1")
            assert found is v2
            assert found.aggregate_revision == 1

    def test_replace_with_stale_revision_raises_conflict(self) -> None:
        uow = FakeCreationUnitOfWork()
        with uow:
            uow.tasks.add(_new_task("task-1", revision=5))
            v2 = _new_task("task-1", revision=6)
            with pytest.raises(RevisionConflict):
                uow.tasks.replace(v2, expected_revision=0)

    def test_replace_missing_task_raises_conflict(self) -> None:
        uow = FakeCreationUnitOfWork()
        with uow:
            v1 = _new_task("task-1", revision=1)
            with pytest.raises(RevisionConflict):
                uow.tasks.replace(v1, expected_revision=0)

    def test_replace_committed(self) -> None:
        uow = FakeCreationUnitOfWork()
        with uow:
            uow.tasks.add(_new_task("task-1", revision=0))
            uow.commit()
        with uow:
            v2 = _new_task("task-1", revision=1)
            uow.tasks.replace(v2, expected_revision=0)
            uow.commit()
        assert uow.tasks.get("task-1").aggregate_revision == 1

    def test_replace_rollback_discards(self) -> None:
        uow = FakeCreationUnitOfWork()
        with uow:
            uow.tasks.add(_new_task("task-1", revision=0))
            uow.commit()
        with uow:
            v2 = _new_task("task-1", revision=1)
            uow.tasks.replace(v2, expected_revision=0)
            uow.rollback()
        assert uow.tasks.get("task-1").aggregate_revision == 0


class TestFakeRepositorySatisfiesProtocol:
    """Verify the fake repository satisfies the ChapterTaskRepository protocol."""

    def test_add_and_get(self) -> None:
        repo: ChapterTaskRepository = FakeChapterTaskRepository()
        task = _new_task("task-1")
        repo.add(task)
        found = repo.get("task-1")
        assert found is task

    def test_get_missing(self) -> None:
        repo: ChapterTaskRepository = FakeChapterTaskRepository()
        assert repo.get("no-such-id") is None
