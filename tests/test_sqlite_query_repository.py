"""B3 read repository ordering, pagination and Audit projection tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from xiaoshuo.application.creation.query_requests import AuditHistoryRequest, ChapterTaskListRequest
from xiaoshuo.application.creation.results import ChapterTaskListItem
from xiaoshuo.domain.creation import ArtifactRef, ChapterTask, ChapterTaskStatus
from xiaoshuo.infrastructure.persistence.sqlite.connection import get_connection
from xiaoshuo.infrastructure.persistence.sqlite.maintenance import init_database
from xiaoshuo.infrastructure.persistence.sqlite.migration_runner import MigrationRunner
from xiaoshuo.infrastructure.persistence.sqlite.query_repository import SqliteReadOnlyQueryRepository
from xiaoshuo.infrastructure.persistence.sqlite.repository import SqliteChapterTaskRepository
from xiaoshuo.infrastructure.persistence.sqlite.settings import SQLitePersistenceSettings

HASH = "sha256:" + "a" * 64
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _task(task_id: str, chapter: int) -> ChapterTask:
    return ChapterTask(task_id, 1, 0, "project-1", chapter, ChapterTaskStatus.PLAN_PREPARING,
        ChapterTaskStatus.PLAN_PREPARING, ArtifactRef("intent-" + task_id, 1, HASH),
        None, None, None, None, None, None, None, None, NOW, NOW)


def _repo(tmp_path):
    settings = SQLitePersistenceSettings(
        db_path=str(tmp_path / "b3.db"), busy_timeout_ms=1000,
        backup_dir=str(tmp_path / "backups"),
    )
    init_database(settings)
    write = get_connection(settings)
    MigrationRunner().migrate(write, settings)
    for task in (_task("task-c", 2), _task("task-a", 1), _task("task-b", 2)):
        SqliteChapterTaskRepository(write).add(task)
    write.execute(
        "INSERT INTO creation_operation (operation_id, idempotency_key, request_digest, result_envelope_json, result_envelope_hash, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("op-1", "key-1", "digest", "{}", "hash", "2026-01-01T00:00:00Z"),
    )
    write.execute(
        "INSERT INTO creation_audit_event (event_id, schema_version, task_id, project_id, event_type, actor_kind, actor_id, model_run_id, before_task_revision, after_task_revision, operation_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("event-1", 1, "task-a", "project-1", "TEST", "AUTHOR", "author-1", None, 0, 1, "op-1", "2026-01-01T00:00:00Z"),
    )
    write.execute(
        "INSERT INTO creation_audit_event_object_ref (event_id, ordinal, artifact_id) VALUES (?, ?, ?), (?, ?, ?)",
        ("event-1", 0, "intent-task-a", "event-1", 1, "intent-task-b"),
    )
    write.commit()
    write.close()
    conn = get_connection(settings, read_only=True)
    return SqliteReadOnlyQueryRepository(conn), conn


def test_q03_q04_stable_task_sort_and_cursor_without_duplicates(tmp_path) -> None:
    repo, conn = _repo(tmp_path)
    try:
        first, cursor = repo.list_by_project(ChapterTaskListRequest("project-1", page_size=2))
        second, final_cursor = repo.list_by_project(ChapterTaskListRequest("project-1", page_size=2, cursor=cursor))
        assert [item.task_id for item in first + second] == ["task-a", "task-b", "task-c"]
        assert final_cursor is None
        assert isinstance(first[0], ChapterTaskListItem)
        assert not hasattr(first[0], "creative_intent_ref")
        assert not hasattr(first[0], "result_envelope_json")
    finally:
        conn.close()


def test_q07_q08_q09_audit_history_is_scoped_and_rebuilds_object_refs(tmp_path) -> None:
    repo, conn = _repo(tmp_path)
    try:
        events, cursor = repo.history_for_task(AuditHistoryRequest("task-a"))
        assert [event.event_id for event in events] == ["event-1"]
        assert [ref.artifact_id for ref in events[0].object_refs] == ["intent-task-a", "intent-task-b"]
        assert events[0].actor.source_artifact_refs == ()
        assert cursor is None
        other_events, _ = repo.history_for_task(AuditHistoryRequest("task-b"))
        assert other_events == ()
    finally:
        conn.close()
