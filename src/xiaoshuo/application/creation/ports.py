"""Application-layer use-case and query port protocols.

Defines stable contracts for what the application layer offers to
callers.  No concrete implementations live here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from xiaoshuo.domain.creation import ArtifactRef

from .commands import (
    ConsumeAuthorDecisionCommand,
    CreateAuthorDecisionCommand,
    CreateChapterTaskCommand,
    SubmitAuthoringArtifactCommand,
    SubmitDraftForReviewCommand,
    TransitionChapterTaskCommand,
)
from .authoring_artifact import AuthoringArtifactSubmissionResult
from .authoring_artifact_context import (
    AuthoringArtifactSubmissionContext,
    DraftReviewSubmissionContext,
)
from .results import (
    AuditHistoryResult,
    AuthorDecisionResult,
    ChapterTaskListResult,
    CreateChapterTaskResult,
    IntegrityCheckResult,
    TransitionChapterTaskResult,
)
from .query_requests import AuditHistoryRequest, ChapterTaskListRequest
from .transition_context import TransitionOperationContext
from .decision_creation_context import DecisionCreationContext
from .canon_commands import ApproveCanonChangesetCommand, PrepareCanonChangesetCommand
from .canon_decision_context import CanonApproveDeliveryContext, CanonPrepareDeliveryContext
from .canon_results import CanonApplyResult, CanonChangesetResult, CanonRecoveryResult
from .canon_apply_context import CanonApplyDeliveryContext
from .canon_recovery_context import CanonRecoveryDeliveryContext


class CreateChapterTaskUseCase(Protocol):
    """Write port for creating a new ChapterTask.

    The concrete use case is responsible for command validation, guard
    enforcement, UoW management, domain invocation, and result
    assembly.  B0a only defines the contract — implementation is
    deferred to B1.
    """

    def create(
        self, command: CreateChapterTaskCommand
    ) -> CreateChapterTaskResult:
        ...


class TransitionChapterTaskUseCase(Protocol):
    """Write port for transitioning an existing ChapterTask.

    Schema v1 excludes COMMITTING and COMPLETED as target states
    through this port.  The concrete use case enforces guards,
    revision-based optimistic concurrency, and UoW boundaries.
    The ``TransitionOperationContext`` carries the caller-supplied
    idempotency key independently from the business command.
    Implementation deferred to B2a.
    """

    def transition(
        self,
        command: TransitionChapterTaskCommand,
        context: TransitionOperationContext,
    ) -> TransitionChapterTaskResult:
        ...


class CreationQueryPort(Protocol):
    """Read-only query port for the creation pipeline.

    Internal B3 read-only query port.  It is not an HTTP contract.
    """

    def list_tasks(self, request: ChapterTaskListRequest) -> ChapterTaskListResult:
        ...

    def audit_history(self, request: AuditHistoryRequest) -> AuditHistoryResult:
        ...

    def check_integrity(self) -> IntegrityCheckResult:
        ...


class CreateAuthorDecisionUseCase(Protocol):
    """Write port for creating an append-only AuthorDecision (B2b).

    The caller supplies only business decision data and a
    DecisionCreationContext carrying the idempotency key.  The
    trusted author identity is produced by the controlled
    LocalAuthorContext — not by the caller.
    """

    def create(
        self,
        command: CreateAuthorDecisionCommand,
        context: DecisionCreationContext,
    ) -> AuthorDecisionResult:
        ...


class ConsumeAuthorDecisionUseCase(Protocol):
    """Write port for consuming a persisted AuthorDecision (B2b).

    The caller supplies task_id, the persisted decision_id, the
    expected task revision, and a TransitionOperationContext carrying
    the idempotency key.  Target status, outcome and target ArtifactRef
    are derived from the real persisted decision — not from the command.
    """

    def consume(
        self,
        command: ConsumeAuthorDecisionCommand,
        context: TransitionOperationContext,
    ) -> TransitionChapterTaskResult:
        ...


class SubmitAuthoringArtifactPort(Protocol):
    """First-stage G0-B DRAFT intake; identity comes from composition."""

    def submit(
        self,
        command: SubmitAuthoringArtifactCommand,
        context: AuthoringArtifactSubmissionContext,
    ) -> AuthoringArtifactSubmissionResult:
        ...


class SubmitDraftForReviewPort(Protocol):
    """Second-stage G0-B REVIEW intake bound to a trusted Task DRAFT."""

    def submit(
        self,
        command: SubmitDraftForReviewCommand,
        context: DraftReviewSubmissionContext,
    ) -> AuthoringArtifactSubmissionResult:
        ...


class ImmutablePayloadStorePort(Protocol):
    """C2 byte-payload boundary; not a Canon commit or Task write port."""

    def put(self, data: bytes) -> str:
        ...

    def read(self, digest: str) -> bytes:
        ...


@dataclass(frozen=True, slots=True)
class CanonBundleDescriptor:
    """Minimal application description of a validated target bundle."""

    content_hash: str
    manifest_hash: str
    world_hash: str | None = None


class CanonBundleInspectorPort(Protocol):
    """Inspect a bundle without exposing an infrastructure implementation."""

    def inspect(self, data: bytes) -> CanonBundleDescriptor:
        ...


@dataclass(frozen=True, slots=True)
class CanonBundleIdentity:
    """Complete, project-bound identity supplied by an activation reader."""

    project_id: str
    version_id: str
    bundle_ref: ArtifactRef
    bundle_content_hash: str
    manifest_hash: str
    world_hash: str
    schema_version: int = 1


class ProjectionActivationReaderPort(Protocol):
    """Read-only activation identity boundary for v2 Prepare."""

    def read_for_project(self, project_id: str) -> CanonBundleIdentity:
        ...


class PrepareCanonChangesetPort(Protocol):
    """Internal C3 proposal port; it is not an HTTP contract."""

    def prepare(
        self,
        command: PrepareCanonChangesetCommand,
        context: CanonPrepareDeliveryContext,
    ) -> CanonChangesetResult:
        ...


class ApproveCanonChangesetPort(Protocol):
    """Internal C3 decision-consumption/Intent port; it cannot apply files."""

    def approve(
        self,
        command: ApproveCanonChangesetCommand,
        context: CanonApproveDeliveryContext,
    ) -> CanonChangesetResult:
        ...


class ApplyCanonCommitPort(Protocol):
    """Bundle-only Canon Apply; Completion is internal to this use case."""

    def apply(self, command: object, context: CanonApplyDeliveryContext) -> CanonApplyResult:
        ...


class RecoverCanonCommitPort(Protocol):
    """Controlled recovery; it never creates a Receipt or completes a task."""

    def recover(self, command: object, context: CanonRecoveryDeliveryContext) -> CanonRecoveryResult:
        ...


class C4aApplyPort(Protocol):
    """C4a Apply boundary; the concrete adapter is a composition-root concern."""

    def apply(self, command: object, context: CanonApplyDeliveryContext) -> CanonApplyResult:
        ...


class C4aRecoveryPort(Protocol):
    """C4a durable-fact-only Recovery boundary."""

    def recover(self, command: object, context: CanonRecoveryDeliveryContext) -> CanonRecoveryResult:
        ...


@dataclass(frozen=True, slots=True)
class CanonActivationResult:
    """Application result for the C4b first-activation boundary."""

    status: str
    attempt_id: str
    project_id: str
    version_id: str
    replay_envelope_json: str


class CanonActivationPort(Protocol):
    """C4b activation boundary; callers cannot supply operator identity."""

    def activate(self, request: object) -> CanonActivationResult:
        ...
