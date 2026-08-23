"""Immutable, versioned application command DTOs for the creation pipeline.

These are application-layer contracts, not domain objects.  The
command_schema_version is independent of the domain SCHEMA_VERSION.
"""

from __future__ import annotations

from dataclasses import dataclass

from xiaoshuo.domain.creation import (
    ArtifactRef,
    ChapterTaskStatus,
    DecisionOutcome,
    DecisionType,
    RecoveryInfo,
)

APPLICATION_COMMAND_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class CreateChapterTaskCommand:
    task_id: str
    project_id: str
    chapter_number: int
    initial_status: ChapterTaskStatus
    creative_intent_ref: ArtifactRef
    command_schema_version: int = APPLICATION_COMMAND_SCHEMA_VERSION

    def __repr__(self) -> str:
        return (
            f"CreateChapterTaskCommand(task_id={self.task_id!r}, "
            f"project_id={self.project_id!r}, "
            f"chapter_number={self.chapter_number}, "
            f"initial_status={self.initial_status.value!r}, "
            f"command_schema_version={self.command_schema_version})"
        )


@dataclass(frozen=True, slots=True)
class TransitionChapterTaskCommand:
    task_id: str
    target_status: ChapterTaskStatus
    expected_revision: int
    recovery: RecoveryInfo | None = None
    command_schema_version: int = APPLICATION_COMMAND_SCHEMA_VERSION

    def __repr__(self) -> str:
        return (
            f"TransitionChapterTaskCommand(task_id={self.task_id!r}, "
            f"target_status={self.target_status.value!r}, "
            f"expected_revision={self.expected_revision}, "
            f"command_schema_version={self.command_schema_version})"
        )


@dataclass(frozen=True, slots=True)
class CreateAuthorDecisionCommand:
    """Command for creating an append-only AuthorDecision.

    The caller supplies only business decision data.  Trusted identity
    (author_id, SourceRef), decision_id, operation_id and timestamps are
    NOT accepted from the caller — they are generated internally by
    the use case via a controlled LocalAuthorContext.
    """

    task_id: str
    decision_type: DecisionType
    target_ref: ArtifactRef
    based_on_task_revision: int
    reason: str | None = None
    adopted_draft_payload: bytes | None = None
    command_schema_version: int = APPLICATION_COMMAND_SCHEMA_VERSION

    def __repr__(self) -> str:
        return (
            f"CreateAuthorDecisionCommand(task_id={self.task_id!r}, "
            f"decision_type={self.decision_type.value!r}, "
            f"based_on_task_revision={self.based_on_task_revision}, "
            f"command_schema_version={self.command_schema_version})"
        )


@dataclass(frozen=True, slots=True)
class ConsumeAuthorDecisionCommand:
    """Command for consuming (executing) a persisted AuthorDecision.

    The caller supplies only task_id, the persisted decision_id and the
    expected task revision.  Target status, outcome and target ArtifactRef
    are derived from the real persisted decision — not from this command.
    """

    task_id: str
    decision_id: str
    expected_revision: int
    command_schema_version: int = APPLICATION_COMMAND_SCHEMA_VERSION

    def __repr__(self) -> str:
        return (
            f"ConsumeAuthorDecisionCommand(task_id={self.task_id!r}, "
            f"decision_id={self.decision_id!r}, "
            f"expected_revision={self.expected_revision}, "
            f"command_schema_version={self.command_schema_version})"
        )


@dataclass(frozen=True, slots=True)
class SubmitAuthoringArtifactCommand:
    """Submit one operator-owned canonical DRAFT envelope.

    The command deliberately carries no actor identity, ArtifactRef,
    artifact id, content hash, project id, or chapter number.  Those
    identities are derived from the canonical envelope and the trusted Task.
    """

    task_id: str
    expected_revision: int
    envelope_bytes: bytes
    command_schema_version: int = APPLICATION_COMMAND_SCHEMA_VERSION

    def __repr__(self) -> str:
        return (
            f"SubmitAuthoringArtifactCommand(task_id={self.task_id!r}, "
            f"expected_revision={self.expected_revision}, "
            f"command_schema_version={self.command_schema_version})"
        )


@dataclass(frozen=True, slots=True)
class SubmitDraftForReviewCommand:
    """Submit a canonical REVIEW after a trusted DRAFT has been persisted.

    ``reviewed_draft_ref`` exists only inside ``envelope_bytes`` as an
    operator-owned claim.  It is never accepted as a separate command field
    and must be checked against the trusted Task and payload.
    """

    task_id: str
    expected_revision: int
    envelope_bytes: bytes
    command_schema_version: int = APPLICATION_COMMAND_SCHEMA_VERSION

    def __repr__(self) -> str:
        return (
            f"SubmitDraftForReviewCommand(task_id={self.task_id!r}, "
            f"expected_revision={self.expected_revision}, "
            f"command_schema_version={self.command_schema_version})"
        )
