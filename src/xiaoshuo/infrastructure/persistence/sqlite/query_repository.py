"""B3 SQLite read adapters; no business write operation is exposed."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from xiaoshuo.application.creation.errors import QueryReadError
from xiaoshuo.application.creation.query_requests import (
    AuditHistoryRequest,
    ChapterTaskListRequest,
    audit_cursor_values,
    make_audit_cursor,
    make_task_cursor,
    task_cursor_values,
)
from xiaoshuo.application.creation.results import (
    ChapterTaskListItem,
    IntegrityCheckResult,
    IntegrityFailureKind,
)
from xiaoshuo.domain.creation import (
    AuditEvent,
    ChapterTaskStatus,
    SourceKind,
    SourceRef,
)

from .serialization import row_to_artifact_ref


class SqliteReadOnlyQueryRepository:
    """Read ChapterTask lists and task-scoped Audit history from one connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def list_by_project(self, request: ChapterTaskListRequest) -> tuple[tuple[ChapterTaskListItem, ...], str | None]:
        where = ["project_id = ?"]
        params: list[object] = [request.project_id]
        if request.status is not None:
            where.append("status = ?")
            params.append(request.status.value)
        if request.cursor is not None:
            chapter_number, task_id = task_cursor_values(request.cursor)
            where.append("(chapter_number > ? OR (chapter_number = ? AND task_id > ?))")
            params.extend((chapter_number, chapter_number, task_id))
        params.append(request.page_size + 1)
        sql = (
            "SELECT task_id, project_id, chapter_number, aggregate_revision, status, updated_at "
            "FROM chapter_task WHERE " + " AND ".join(where)
            + " ORDER BY chapter_number ASC, task_id ASC LIMIT ?"
        )
        try:
            rows = self._conn.execute(sql, params).fetchall()
            has_next = len(rows) > request.page_size
            visible_rows = rows[:request.page_size]
            tasks = tuple(
                ChapterTaskListItem(
                    task_id=row["task_id"], project_id=row["project_id"],
                    chapter_number=row["chapter_number"], aggregate_revision=row["aggregate_revision"],
                    status=ChapterTaskStatus(row["status"]), updated_at=row["updated_at"],
                )
                for row in visible_rows
            )
        except sqlite3.Error as exc:
            raise QueryReadError("chapter task list read failed") from exc
        cursor = None
        if has_next and tasks:
            last = tasks[-1]
            cursor = make_task_cursor(last.chapter_number, last.task_id)
        return tasks, cursor

    def history_for_task(self, request: AuditHistoryRequest) -> tuple[tuple[AuditEvent, ...], str | None]:
        where = ["task_id = ?"]
        params: list[object] = [request.task_id]
        if request.cursor is not None:
            revision, event_id = audit_cursor_values(request.cursor)
            where.append("(after_task_revision > ? OR (after_task_revision = ? AND event_id > ?))")
            params.extend((revision, revision, event_id))
        params.append(request.page_size + 1)
        sql = "SELECT * FROM creation_audit_event WHERE " + " AND ".join(where) + " ORDER BY after_task_revision ASC, event_id ASC LIMIT ?"
        try:
            rows = self._conn.execute(sql, params).fetchall()
            has_next = len(rows) > request.page_size
            visible_rows = rows[:request.page_size]
            events = tuple(self._audit_from_row(row) for row in visible_rows)
        except sqlite3.Error as exc:
            raise QueryReadError("audit history read failed") from exc
        cursor = None
        if has_next and events:
            last = events[-1]
            cursor = make_audit_cursor(last.after_task_revision, last.event_id)
        return events, cursor

    def _audit_from_row(self, row) -> AuditEvent:
        try:
            object_rows = self._conn.execute(
                "SELECT r.artifact_id, r.schema_version, r.content_hash "
                "FROM creation_audit_event_object_ref o "
                "JOIN creation_artifact_ref r ON r.artifact_id = o.artifact_id "
                "WHERE o.event_id = ? ORDER BY o.ordinal ASC",
                (row["event_id"],),
            ).fetchall()
            refs = tuple(row_to_artifact_ref(item["artifact_id"], item["schema_version"], item["content_hash"]) for item in object_rows)
            created_at_text = row["created_at"]
            if created_at_text.endswith("Z"):
                created_at_text = created_at_text[:-1] + "+00:00"
            return AuditEvent(
                event_id=row["event_id"], schema_version=row["schema_version"], task_id=row["task_id"],
                project_id=row["project_id"], event_type=row["event_type"],
                actor=SourceRef(kind=SourceKind(row["actor_kind"]), actor_id=row["actor_id"], model_run_id=row["model_run_id"]),
                before_task_revision=row["before_task_revision"], after_task_revision=row["after_task_revision"],
                object_refs=refs, operation_id=row["operation_id"], created_at=datetime.fromisoformat(created_at_text),
            )
        except (sqlite3.Error, TypeError, ValueError, KeyError) as exc:
            raise QueryReadError("audit history row deserialisation failed") from exc


class SqliteIntegrityCheckRepository:
    """Run only the two B3-approved read-only integrity checks."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def check(self) -> IntegrityCheckResult:
        try:
            result = self._conn.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_key_rows = self._conn.execute("PRAGMA foreign_key_check").fetchall()
        except sqlite3.Error as exc:
            raise QueryReadError("integrity check read failed") from exc
        integrity_ok = result == "ok"
        foreign_key_ok = not foreign_key_rows
        failure_kind = None
        if not integrity_ok and not foreign_key_ok:
            failure_kind = IntegrityFailureKind.BOTH
        elif not integrity_ok:
            failure_kind = IntegrityFailureKind.INTEGRITY
        elif not foreign_key_ok:
            failure_kind = IntegrityFailureKind.FOREIGN_KEY
        report = IntegrityCheckResult(
            integrity_ok=integrity_ok, foreign_key_ok=foreign_key_ok,
            foreign_key_violation_count=len(foreign_key_rows), failure_kind=failure_kind,
        )
        return report
