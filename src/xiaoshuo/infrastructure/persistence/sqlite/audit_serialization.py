"""Serialize immutable creation AuditEvent values into SQLite rows."""

from __future__ import annotations

from datetime import timezone

from xiaoshuo.domain.creation import AuditEvent


def audit_event_to_row(event: AuditEvent) -> tuple[object, ...]:
    """Return values for the twelve scalar ``creation_audit_event`` columns."""
    created_at = (
        event.created_at.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    return (
        event.event_id,
        event.schema_version,
        event.task_id,
        event.project_id,
        event.event_type,
        event.actor.kind.value,
        event.actor.actor_id,
        event.actor.model_run_id,
        event.before_task_revision,
        event.after_task_revision,
        event.operation_id,
        created_at,
    )


def source_artifact_ref_rows(event: AuditEvent) -> tuple[tuple[str, int, str], ...]:
    return tuple(
        (event.event_id, ordinal, ref.artifact_id)
        for ordinal, ref in enumerate(event.actor.source_artifact_refs)
    )


def object_ref_rows(event: AuditEvent) -> tuple[tuple[str, int, str], ...]:
    return tuple(
        (event.event_id, ordinal, ref.artifact_id)
        for ordinal, ref in enumerate(event.object_refs)
    )
