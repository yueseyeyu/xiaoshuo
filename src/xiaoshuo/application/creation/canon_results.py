"""Versioned internal result DTOs for Canon operations."""

from __future__ import annotations

from dataclasses import dataclass

from xiaoshuo.domain.creation import ArtifactRef, ChapterTaskStatus


CANON_RESULT_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class CanonChangesetResult:
    task_id: str
    aggregate_revision: int
    status: ChapterTaskStatus
    changeset_ref: ArtifactRef
    target_bundle_ref: ArtifactRef
    base_manifest_hash: str
    target_manifest_hash: str
    journal_id: str | None = None
    result_schema_version: int = CANON_RESULT_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class CanonApplyResult:
    task_id: str
    aggregate_revision: int
    status: ChapterTaskStatus
    journal_id: str
    operation_id: str
    receipt_id: str | None = None
    receipt_ref: ArtifactRef | None = None
    audit_event_ids: tuple[str, ...] = ()
    result_schema_version: int = CANON_RESULT_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class CanonRecoveryResult:
    task_id: str
    aggregate_revision: int
    status: ChapterTaskStatus
    journal_id: str
    operation_id: str
    audit_event_ids: tuple[str, ...] = ()
    result_schema_version: int = CANON_RESULT_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class CanonCompletedGraphEvidence:
    """Read-only evidence for one complete C4 logical event graph.

    The DTO deliberately records the observed logical order and all durable
    identities without implying that ``created_at`` or ``event_id`` prove
    physical insertion order.
    """

    apply_attempt_id: str
    project_id: str
    task_id: str
    operator_identity: str
    apply_key: str
    request_digest: str
    task_revision: int
    phases: tuple[str, ...]
    operation_id: str
    decision_id: str
    journal_id: str
    receipt_id: str
    receipt_ref: ArtifactRef
    base_bundle_ref: ArtifactRef
    target_bundle_ref: ArtifactRef
    target_version_id: str
    target_pointer_content_hash: str
    target_marker_content_hash: str
    target_manifest_hash: str
    target_world_hash: str
    audit_event_ids: tuple[str, ...]
    envelope_hash: str
    recovery_marker: bool = False
    read_only: bool = True
    physical_order_proven: bool = False
    result_schema_version: int = CANON_RESULT_SCHEMA_VERSION


# Stable descriptive alias for callers that use the accepted design name.
CompletedCanonApplyEvidence = CanonCompletedGraphEvidence


@dataclass(frozen=True, slots=True)
class CanonRecoveryGraphEvidence:
    """Evidence accepted only by the explicit C4 recovery boundary."""

    completed: CanonCompletedGraphEvidence
    recovery_event_id: str
    read_only: bool = True
    result_schema_version: int = CANON_RESULT_SCHEMA_VERSION
