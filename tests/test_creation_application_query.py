"""B3 application contracts for the internal read-only query facade."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from xiaoshuo.application.creation.errors import NotFound, QueryReadError, QueryValidationError
from xiaoshuo.application.creation.get_task import GetChapterTaskUseCase
from xiaoshuo.application.creation.query import CreationQueryUseCase
from xiaoshuo.application.creation.query_requests import AuditHistoryRequest, ChapterTaskListRequest
from xiaoshuo.application.creation.results import ChapterTaskListItem
from xiaoshuo.domain.creation import ArtifactRef, AuditEvent, ChapterTask, ChapterTaskStatus, SourceKind, SourceRef

HASH = "sha256:" + "a" * 64
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _task(task_id: str = "task-1", chapter: int = 1) -> ChapterTask:
    return ChapterTask(
        task_id=task_id, schema_version=1, aggregate_revision=0, project_id="project-1",
        chapter_number=chapter, status=ChapterTaskStatus.PLAN_PREPARING,
        last_stable_status=ChapterTaskStatus.PLAN_PREPARING,
        creative_intent_ref=ArtifactRef("intent-" + task_id, 1, HASH),
        confirmed_plan_ref=None, current_author_draft_ref=None, review_target_draft_ref=None,
        adopted_draft_ref=None, latest_review_ref=None, pending_changeset_ref=None,
        commit_receipt_ref=None, recovery=None, created_at=NOW, updated_at=NOW,
    )


class _Tasks:
    def __init__(self, values: tuple[ChapterTask, ...]) -> None:
        self.values = values

    def get(self, task_id: str):
        return next((item for item in self.values if item.task_id == task_id), None)

    def list_by_project(self, request):
        values = tuple(item for item in self.values if item.project_id == request.project_id)
        return tuple(
            ChapterTaskListItem(item.task_id, item.project_id, item.chapter_number, item.aggregate_revision, item.status, item.updated_at.isoformat())
            for item in values[:request.page_size]
        ), None


class _Audit:
    def __init__(self, events=()) -> None:
        self.events = events

    def history_for_task(self, request):
        return tuple(event for event in self.events if event.task_id == request.task_id), None


class _Integrity:
    def check(self):
        raise AssertionError("not used by this test")


class _Session:
    def __init__(self, tasks: _Tasks, events=()) -> None:
        self.tasks, self.audit, self.integrity = tasks, _Audit(events), _Integrity()
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


def test_q01_and_q15_exact_get_delegates_to_b1_use_case() -> None:
    session = _Session(_Tasks((_task(),)))
    b1 = GetChapterTaskUseCase(lambda: session)
    facade = CreationQueryUseCase(b1, lambda: session)
    assert facade.get_task("task-1").task_id == "task-1"
    assert session.closed == 1


def test_q02_minimal_task_list_view_and_empty_page() -> None:
    session = _Session(_Tasks((_task("task-b", 2), _task("task-a", 1))))
    result = CreationQueryUseCase(GetChapterTaskUseCase(lambda: session), lambda: session).list_tasks(
        ChapterTaskListRequest(project_id="project-1")
    )
    assert [item.task_id for item in result.items] == ["task-b", "task-a"]
    assert not hasattr(result.items[0], "creative_intent_ref")
    assert result.result_schema_version == 1


def test_q05_and_q09_invalid_query_inputs_fail_closed() -> None:
    with pytest.raises(QueryValidationError):
        ChapterTaskListRequest(project_id="project-1", page_size=0)
    with pytest.raises(QueryValidationError):
        ChapterTaskListRequest(project_id="project-1", status=ChapterTaskStatus.COMMITTING)
    with pytest.raises(QueryValidationError):
        ChapterTaskListRequest.from_filters({"project_id": "project-1", "unknown": True})
    with pytest.raises(QueryValidationError):
        AuditHistoryRequest.from_filters({"task_id": "task-1", "project_id": "project-1"})
    for cursor in ("eyJ2IjoxLCJraW5kIjoidGFzayJ9", "eyJ2IjoxLCJraW5kIjoidGFzayIsImNoYXB0ZXJfbnVtYmVyIjowLCJ0YXNrX2lkIjoieCJ9"):
        with pytest.raises(QueryValidationError):
            ChapterTaskListRequest(project_id="project-1", cursor=cursor)


def test_q06_exact_missing_retains_b1_not_found() -> None:
    session = _Session(_Tasks(()))
    facade = CreationQueryUseCase(GetChapterTaskUseCase(lambda: session), lambda: session)
    with pytest.raises(NotFound):
        facade.get_task("missing")


def test_q11_query_session_open_error_is_stable_application_error() -> None:
    facade = CreationQueryUseCase(GetChapterTaskUseCase(lambda: _Session(_Tasks(()))), lambda: (_ for _ in ()).throw(OSError("closed")))
    with pytest.raises(QueryReadError):
        facade.list_tasks(ChapterTaskListRequest(project_id="project-1"))


def test_q11_query_read_error_closes_session_and_hides_sqlite_detail() -> None:
    class BrokenTasks(_Tasks):
        def list_by_project(self, request):
            raise sqlite3.OperationalError("raw sqlite detail")

    session = _Session(BrokenTasks((_task(),)))
    facade = CreationQueryUseCase(GetChapterTaskUseCase(lambda: session), lambda: session)
    with pytest.raises(QueryReadError) as caught:
        facade.list_tasks(ChapterTaskListRequest(project_id="project-1"))
    assert "raw sqlite detail" not in str(caught.value)
    assert session.closed == 1


def test_q08_facade_exposes_object_refs_but_not_actor_source_refs() -> None:
    ref_a = ArtifactRef("object-a", 1, HASH)
    ref_b = ArtifactRef("object-b", 1, HASH)
    event = AuditEvent("event-1", 1, "task-1", "project-1", "TEST",
        SourceRef(SourceKind.AUTHOR, actor_id="author-1", source_artifact_refs=(ref_b,)),
        0, 1, (ref_a, ref_b), "operation-1", NOW)
    session = _Session(_Tasks((_task(),)), (event,))
    result = CreationQueryUseCase(GetChapterTaskUseCase(lambda: session), lambda: session).audit_history(AuditHistoryRequest("task-1"))
    assert [ref.artifact_id for ref in result.items[0].object_refs] == ["object-a", "object-b"]
    assert not hasattr(result.items[0], "source_artifact_refs")


def test_q01_facade_exposes_no_write_capabilities() -> None:
    """The B3 CreationQueryUseCase facade must not expose add, replace,
    commit, or rollback — it is strictly read-only."""
    session = _Session(_Tasks((_task(),)))
    facade = CreationQueryUseCase(GetChapterTaskUseCase(lambda: session), lambda: session)
    for method in ("add", "replace", "commit", "rollback"):
        assert not hasattr(facade, method), f"facade must not expose {method}"
