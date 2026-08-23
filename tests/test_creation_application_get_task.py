"""Exact GetChapterTask B1 use-case tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from xiaoshuo.application.creation.errors import CreationApplicationError, NotFound
from xiaoshuo.application.creation.get_task import GetChapterTaskUseCase
from xiaoshuo.domain.creation import ArtifactRef, ChapterTask, ChapterTaskStatus

HASH_A = "sha256:" + "a" * 64
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def task() -> ChapterTask:
    return ChapterTask(
        task_id="task-1",
        schema_version=1,
        aggregate_revision=0,
        project_id="project-1",
        chapter_number=1,
        status=ChapterTaskStatus.PLAN_PREPARING,
        last_stable_status=ChapterTaskStatus.PLAN_PREPARING,
        creative_intent_ref=ArtifactRef("intent-1", 1, HASH_A),
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


class Tasks:
    def __init__(self, value: ChapterTask | None) -> None:
        self.value = value
        self.requested: list[str] = []

    def get(self, task_id: str) -> ChapterTask | None:
        self.requested.append(task_id)
        return self.value


class Uow:
    def __init__(self, value: ChapterTask | None) -> None:
        self.tasks = Tasks(value)
        self.closes = 0

    def close(self) -> None:
        self.closes += 1


def test_get_returns_exact_task() -> None:
    expected = task()
    uow = Uow(expected)
    assert GetChapterTaskUseCase(lambda: uow).get("task-1") is expected
    assert uow.tasks.requested == ["task-1"]
    assert uow.closes == 1


def test_get_missing_raises_stable_not_found() -> None:
    uow = Uow(None)
    with pytest.raises(NotFound, match="missing"):
        GetChapterTaskUseCase(lambda: uow).get("missing")
    assert uow.closes == 1


def test_get_storage_failure_does_not_leak_sqlite_error() -> None:
    def factory():
        raise sqlite3.OperationalError("database unavailable")

    with pytest.raises(CreationApplicationError) as caught:
        GetChapterTaskUseCase(factory).get("task-1")
    assert isinstance(caught.value.__cause__, sqlite3.OperationalError)
