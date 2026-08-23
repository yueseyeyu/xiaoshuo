"""Application-layer Repository and UnitOfWork protocol definitions.

These define the contracts that any persistence adapter must satisfy.
No SQLite, SQL, WAL, or database-specific detail appears in these
protocols.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from xiaoshuo.domain.creation import ArtifactRef, AuditEvent, AuthorDecision, ChapterTask

from .query_requests import AuditHistoryRequest, ChapterTaskListRequest
from .results import ChapterTaskListItem, IntegrityCheckResult


class OperationResult(str, Enum):
    """Outcome of atomically registering an idempotent operation."""

    NEW = "NEW"
    REPLAY = "REPLAY"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True, slots=True)
class OperationCreateOutcome:
    """Result returned by ``create_or_replay_complete``.

    ``replay_envelope_json`` is populated only for REPLAY and must be the
    original envelope already stored by the winning operation.
    """

    status: OperationResult
    replay_envelope_json: str | None = None


@dataclass(frozen=True, slots=True)
class OperationLogRecord:
    """Immutable application contract for the operation/idempotency ledger."""

    operation_id: str
    idempotency_key: str
    request_digest: str
    result_envelope_json: str
    result_envelope_hash: str
    created_at: str


class ChapterTaskRepository(Protocol):
    """Repository for ChapterTask aggregate persistence.

    Provides read, add, and conditional-replace contracts.  Callers
    own transaction boundaries via CreationUnitOfWork.
    """

    def get(self, task_id: str) -> ChapterTask | None:
        """Return the current ChapterTask or None if not found."""
        ...

    def add(self, task: ChapterTask) -> None:
        """Persist a new ChapterTask that does not yet exist."""
        ...

    def replace(self, task: ChapterTask, *, expected_revision: int) -> None:
        """Atomically replace an existing task.

        Implementations must write only when the current aggregate
        revision in the underlying store matches *expected_revision*.
        If the revisions do not match the implementation must report
        an application-layer RevisionConflict to the caller.
        """
        ...


class AuditEventRepository(Protocol):
    """Append-only repository for creation audit events.

    Events are append-only and share the surrounding UnitOfWork transaction.
    """

    def add_event(self, event: AuditEvent) -> None:
        """Append *event* within the current UnitOfWork."""
        ...


class OperationLogRepository(Protocol):
    """Repository for operation and idempotency accounting.

    The adapter atomically distinguishes NEW, REPLAY, and CONFLICT without
    exposing database-specific exceptions to application callers.
    """

    def get_by_idempotency_key(
        self, idempotency_key: str
    ) -> OperationLogRecord | None:
        """Return the original operation record for *idempotency_key*."""
        ...

    def create_or_replay_complete(
        self, record: OperationLogRecord
    ) -> OperationCreateOutcome:
        """Register *record* or report replay/conflict atomically."""
        ...


@dataclass(frozen=True, slots=True)
class DecisionConsumptionRecord:
    """Immutable record linking a decision to its consuming operation."""

    consumption_id: str
    decision_id: str
    operation_id: str
    task_id: str
    consumed_at_task_revision: int
    consumed_at: str


class AuthorDecisionRepository(Protocol):
    """Repository for append-only AuthorDecision and consumption records.

    Decisions are immutable and append-only.  A decision may be consumed
    at most once — the consumption association is also append-only.
    """

    def get(self, decision_id: str) -> AuthorDecision | None:
        """Return the immutable AuthorDecision or None if not found."""
        ...

    def add(self, decision: AuthorDecision) -> None:
        """Persist a new immutable AuthorDecision (append-only)."""
        ...

    def add_consumption(self, record: DecisionConsumptionRecord) -> None:
        """Record a decision consumption (append-only, unique decision_id)."""
        ...

    def get_consumption_by_decision_id(
        self, decision_id: str
    ) -> DecisionConsumptionRecord | None:
        """Return the consumption record for *decision_id*, or None."""
        ...


@dataclass(frozen=True, slots=True)
class CanonCommitIntentRecord:
    """Append-only durable intent bound to one approved ChangeSet."""

    journal_id: str
    task_id: str
    operation_id: str
    decision_id: str
    changeset_ref: ArtifactRef
    target_bundle_ref: ArtifactRef
    base_manifest_hash: str
    target_manifest_hash: str
    created_at: str
    base_bundle_ref: ArtifactRef | None = None
    base_bundle_content_hash: str | None = None
    target_bundle_content_hash: str | None = None
    base_world_hash: str | None = None
    target_world_hash: str | None = None
    canonical_bundle_schema_version: int = 1


@dataclass(frozen=True, slots=True)
class CanonCommitJournalView:
    journal_id: str
    task_id: str
    operation_id: str
    decision_id: str
    changeset_ref: ArtifactRef
    target_bundle_ref: ArtifactRef
    base_manifest_hash: str
    target_manifest_hash: str
    created_at: str
    base_bundle_ref: ArtifactRef | None = None
    base_bundle_content_hash: str | None = None
    target_bundle_content_hash: str | None = None
    base_world_hash: str | None = None
    target_world_hash: str | None = None
    canonical_bundle_schema_version: int = 1


class CanonCommitIntentRepository(Protocol):
    """Specialized C3 write boundary; generic Task repositories never implement it."""

    def create_intent(
        self,
        record: CanonCommitIntentRecord,
        transitioned_task: ChapterTask,
        *,
        expected_revision: int,
    ) -> None:
        """Atomically append intent and conditionally move a task to COMMITTING."""
        ...


class CanonCommitLifecycleRepository(CanonCommitIntentRepository, Protocol):
    """Narrow C4a boundary; generic Task repositories remain write-blocked."""

    def get_journal(self, journal_id: str) -> CanonCommitJournalView | None:
        ...

    def complete_apply(self, *args: object, **kwargs: object) -> None:
        ...

    def mark_recovery(self, *args: object, **kwargs: object) -> None:
        ...

    def resume_recovery(self, *args: object, **kwargs: object) -> None:
        ...


class CreationUnitOfWork(Protocol):
    """Transactional boundary shared by all creation repositories.

    Task, AuditEvent, OperationLog, AuthorDecision and the specialized Canon
    Intent repository share the same underlying resource and transaction
    scope.  The application use case owns the UnitOfWork lifecycle —
    repositories do not commit or rollback independently.
    """

    tasks: ChapterTaskRepository
    audit: AuditEventRepository
    operations: OperationLogRepository
    decisions: AuthorDecisionRepository
    canon: CanonCommitLifecycleRepository

    def commit(self) -> None:
        """Commit the current transaction."""
        ...

    def rollback(self) -> None:
        """Rollback the current transaction."""
        ...

    def close(self) -> None:
        """Release the UnitOfWork resource deterministically."""
        ...


class ExactTaskReader(Protocol):
    """Minimal exact-read capability retained by B1."""

    def get(self, task_id: str) -> ChapterTask | None:
        ...


class ReadOnlyChapterTaskRepository(ExactTaskReader, Protocol):
    """Read-only B3 task contract; no add/replace capability is exposed."""

    def list_by_project(
        self, request: ChapterTaskListRequest
    ) -> tuple[tuple[ChapterTaskListItem, ...], str | None]:
        ...


class ReadOnlyAuditEventRepository(Protocol):
    """Read-only, task-scoped AuditEvent history contract."""

    def history_for_task(
        self, request: AuditHistoryRequest
    ) -> tuple[tuple[AuditEvent, ...], str | None]:
        ...


class IntegrityCheckRepository(Protocol):
    """Limited read-only SQLite integrity report contract."""

    def check(self) -> IntegrityCheckResult:
        ...


class CreationQuerySession(Protocol):
    """Read-only session boundary; deliberately has no commit or rollback."""

    tasks: ReadOnlyChapterTaskRepository
    audit: ReadOnlyAuditEventRepository
    integrity: IntegrityCheckRepository

    def close(self) -> None:
        ...
