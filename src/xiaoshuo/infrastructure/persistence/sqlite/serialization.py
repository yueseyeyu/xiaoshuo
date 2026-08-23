"""Bi-directional mapping between domain ChapterTask and SQLite ``chapter_task`` rows."""

from __future__ import annotations

from datetime import datetime

from xiaoshuo.domain.creation import (
    ArtifactRef,
    ChapterTask,
    ChapterTaskStatus,
    RecoveryInfo,
)


def artifact_ref_to_row(ref: ArtifactRef) -> tuple[str, int, str]:
    """Serialize *ArtifactRef* to row values ``(artifact_id, schema_version, content_hash)``."""
    return (ref.artifact_id, ref.schema_version, ref.content_hash)


def row_to_artifact_ref(artifact_id: str, schema_version: int, content_hash: str) -> ArtifactRef:
    """Deserialize row values back to *ArtifactRef*."""
    return ArtifactRef(
        artifact_id=artifact_id,
        schema_version=schema_version,
        content_hash=content_hash,
    )


def recovery_info_to_row(rec: RecoveryInfo) -> tuple[str, str, str]:
    """Serialize *RecoveryInfo* to row values."""
    return (rec.failed_operation_id, rec.error_code, rec.retry_from_status.value)


def row_to_recovery_info(row) -> RecoveryInfo | None:
    """Deserialize recovery columns back to *RecoveryInfo*.

    Returns ``None`` when no recovery information is present.
    """
    fid = row["recovery_failed_operation_id"]
    if fid is None:
        return None
    return RecoveryInfo(
        failed_operation_id=fid,
        error_code=row["recovery_error_code"],
        retry_from_status=ChapterTaskStatus(row["recovery_retry_from_status"]),
    )


def chapter_task_to_row(task: ChapterTask) -> dict[str, object]:
    """Convert domain *ChapterTask* to a dict suitable for SQLite INSERT/REPLACE.

    All :class:`ArtifactRef` fields are flattened to their ``artifact_id``
    FK columns.  :class:`RecoveryInfo` is flattened to three nullable
    columns.  Datetime objects are serialized to ISO-8601 strings.
    """
    return {
        "task_id": task.task_id,
        "schema_version": task.schema_version,
        "aggregate_revision": task.aggregate_revision,
        "project_id": task.project_id,
        "chapter_number": task.chapter_number,
        "status": task.status.value,
        "last_stable_status": task.last_stable_status.value,
        "creative_intent_ref_artifact_id": task.creative_intent_ref.artifact_id,
        "confirmed_plan_ref_artifact_id": task.confirmed_plan_ref.artifact_id
        if task.confirmed_plan_ref
        else None,
        "current_author_draft_ref_artifact_id": task.current_author_draft_ref.artifact_id
        if task.current_author_draft_ref
        else None,
        "review_target_draft_ref_artifact_id": task.review_target_draft_ref.artifact_id
        if task.review_target_draft_ref
        else None,
        "adopted_draft_ref_artifact_id": task.adopted_draft_ref.artifact_id
        if task.adopted_draft_ref
        else None,
        "latest_review_ref_artifact_id": task.latest_review_ref.artifact_id
        if task.latest_review_ref
        else None,
        "pending_changeset_ref_artifact_id": task.pending_changeset_ref.artifact_id
        if task.pending_changeset_ref
        else None,
        "recovery_failed_operation_id": task.recovery.failed_operation_id
        if task.recovery
        else None,
        "recovery_error_code": task.recovery.error_code if task.recovery else None,
        "recovery_retry_from_status": task.recovery.retry_from_status.value
        if task.recovery
        else None,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
    }


def row_to_chapter_task(row, all_refs: dict[str, ArtifactRef]) -> ChapterTask:
    """Reconstruct a *ChapterTask* from a ``sqlite3.Row`` and a dict of all referenced *ArtifactRef*\\ s.

    Args:
        row: A ``sqlite3.Row`` from the ``chapter_task`` table.
        all_refs: Mapping of ``artifact_id`` → :class:`ArtifactRef`.  Must
            contain every artifact referenced by the row's FK columns.

    Returns:
        A fully reconstructed :class:`ChapterTask`.
    """

    def _ref(column: str) -> ArtifactRef | None:
        aid = row[column]
        return all_refs.get(aid) if aid is not None else None

    return ChapterTask(
        task_id=row["task_id"],
        schema_version=row["schema_version"],
        aggregate_revision=row["aggregate_revision"],
        project_id=row["project_id"],
        chapter_number=row["chapter_number"],
        status=ChapterTaskStatus(row["status"]),
        last_stable_status=ChapterTaskStatus(row["last_stable_status"]),
        creative_intent_ref=all_refs[row["creative_intent_ref_artifact_id"]],
        confirmed_plan_ref=_ref("confirmed_plan_ref_artifact_id"),
        current_author_draft_ref=_ref("current_author_draft_ref_artifact_id"),
        review_target_draft_ref=_ref("review_target_draft_ref_artifact_id"),
        adopted_draft_ref=_ref("adopted_draft_ref_artifact_id"),
        latest_review_ref=_ref("latest_review_ref_artifact_id"),
        pending_changeset_ref=_ref("pending_changeset_ref_artifact_id"),
        commit_receipt_ref=_ref("commit_receipt_ref_artifact_id"),
        recovery=row_to_recovery_info(row),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
