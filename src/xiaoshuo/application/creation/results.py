"""Immutable, versioned application result DTOs for the creation pipeline.

These are application-layer contracts.  The result_schema_version is
independent of both the command_schema_version and the domain
SCHEMA_VERSION.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from xiaoshuo.domain.creation import ArtifactRef, ChapterTaskStatus, SourceKind

APPLICATION_RESULT_SCHEMA_VERSION = 1


class IntegrityFailureKind(str, Enum):
    INTEGRITY = "INTEGRITY"
    FOREIGN_KEY = "FOREIGN_KEY"
    BOTH = "BOTH"


@dataclass(frozen=True, slots=True)
class CreateChapterTaskResult:
    task_id: str
    aggregate_revision: int
    status: ChapterTaskStatus
    result_schema_version: int = APPLICATION_RESULT_SCHEMA_VERSION

    def __repr__(self) -> str:
        return (
            f"CreateChapterTaskResult(task_id={self.task_id!r}, "
            f"aggregate_revision={self.aggregate_revision}, "
            f"status={self.status.value!r}, "
            f"result_schema_version={self.result_schema_version})"
        )


@dataclass(frozen=True, slots=True)
class TransitionChapterTaskResult:
    task_id: str
    aggregate_revision: int
    status: ChapterTaskStatus
    result_schema_version: int = APPLICATION_RESULT_SCHEMA_VERSION

    def __repr__(self) -> str:
        return (
            f"TransitionChapterTaskResult(task_id={self.task_id!r}, "
            f"aggregate_revision={self.aggregate_revision}, "
            f"status={self.status.value!r}, "
            f"result_schema_version={self.result_schema_version})"
        )


@dataclass(frozen=True, slots=True)
class AuthorDecisionResult:
    """Result of creating an AuthorDecision (B2b)."""

    decision_id: str
    task_id: str
    result_schema_version: int = APPLICATION_RESULT_SCHEMA_VERSION

    def __repr__(self) -> str:
        return (
            f"AuthorDecisionResult(decision_id={self.decision_id!r}, "
            f"task_id={self.task_id!r}, "
            f"result_schema_version={self.result_schema_version})"
        )


@dataclass(frozen=True, slots=True)
class ChapterTaskListItem:
    """Minimal internal read model for a ChapterTask list page."""

    task_id: str
    project_id: str
    chapter_number: int
    aggregate_revision: int
    status: ChapterTaskStatus
    updated_at: str


@dataclass(frozen=True, slots=True)
class ChapterTaskListResult:
    items: tuple[ChapterTaskListItem, ...]
    next_cursor: str | None
    result_schema_version: int = APPLICATION_RESULT_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class AuditEventView:
    """Internal audit projection; intentionally excludes actor source refs."""

    event_id: str
    task_id: str
    project_id: str
    event_type: str
    actor_kind: SourceKind
    actor_id: str | None
    model_run_id: str | None
    before_task_revision: int
    after_task_revision: int
    object_refs: tuple[ArtifactRef, ...]
    operation_id: str
    created_at: str


@dataclass(frozen=True, slots=True)
class AuditHistoryResult:
    items: tuple[AuditEventView, ...]
    next_cursor: str | None
    result_schema_version: int = APPLICATION_RESULT_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class IntegrityCheckResult:
    """Minimal, read-only health report without raw SQLite diagnostics."""

    integrity_ok: bool
    foreign_key_ok: bool
    foreign_key_violation_count: int
    failure_kind: IntegrityFailureKind | None = None
    result_schema_version: int = APPLICATION_RESULT_SCHEMA_VERSION
