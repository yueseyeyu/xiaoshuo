"""SQLite append-only AuditEvent repository adapter."""

from __future__ import annotations

import sqlite3

from xiaoshuo.domain.creation import AuditEvent
from xiaoshuo.application.creation.errors import (
    ArtifactIdentityConflict,
    CreationApplicationError,
)

from .audit_serialization import (
    audit_event_to_row,
    object_ref_rows,
    source_artifact_ref_rows,
)


class SqliteAuditEventRepository:
    """Append AuditEvent and ordered reference rows in the current UoW."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add_event(self, event: AuditEvent) -> None:
        try:
            self._verify_artifact_refs(event)
            self._conn.execute(
                "INSERT INTO creation_audit_event ("
                "event_id, schema_version, task_id, project_id, event_type, "
                "actor_kind, actor_id, model_run_id, before_task_revision, "
                "after_task_revision, operation_id, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                audit_event_to_row(event),
            )
            self._conn.executemany(
                "INSERT INTO creation_audit_event_source_artifact_ref "
                "(event_id, ordinal, artifact_id) VALUES (?, ?, ?)",
                source_artifact_ref_rows(event),
            )
            self._conn.executemany(
                "INSERT INTO creation_audit_event_object_ref "
                "(event_id, ordinal, artifact_id) VALUES (?, ?, ?)",
                object_ref_rows(event),
            )
        except sqlite3.Error as exc:
            raise CreationApplicationError("audit event write failed") from exc

    def _verify_artifact_refs(self, event: AuditEvent) -> None:
        refs = event.actor.source_artifact_refs + event.object_refs
        for ref in refs:
            row = self._conn.execute(
                "SELECT schema_version, content_hash "
                "FROM creation_artifact_ref WHERE artifact_id = ?",
                (ref.artifact_id,),
            ).fetchone()
            if row is None:
                raise ArtifactIdentityConflict(
                    f"audit artifact_id {ref.artifact_id!r} is not registered"
                )
            if (
                row["schema_version"] != ref.schema_version
                or row["content_hash"] != ref.content_hash
            ):
                raise ArtifactIdentityConflict(
                    f"audit artifact_id {ref.artifact_id!r} identity mismatch"
                )
