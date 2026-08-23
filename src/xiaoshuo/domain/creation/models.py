"""Immutable objects for the single-chapter creation protocol."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .hashing import (
    InvalidContentHash,
    InvalidDomainValue,
    validate_content_hash_format,
    verify_content_hash,
)

SCHEMA_VERSION = 1


class _StringEnum(str, Enum):
    pass


class SourceKind(_StringEnum):
    AUTHOR = "AUTHOR"
    MODEL = "MODEL"
    SYSTEM = "SYSTEM"
    ANALYSIS_IMPORT = "ANALYSIS_IMPORT"


class ChapterTaskStatus(_StringEnum):
    PLAN_PREPARING = "PLAN_PREPARING"
    PLAN_APPROVAL_PENDING = "PLAN_APPROVAL_PENDING"
    DRAFTING = "DRAFTING"
    REVIEWING = "REVIEWING"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    DRAFT_APPROVAL_PENDING = "DRAFT_APPROVAL_PENDING"
    CHANGESET_PREPARING = "CHANGESET_PREPARING"
    CHANGESET_APPROVAL_PENDING = "CHANGESET_APPROVAL_PENDING"
    COMMITTING = "COMMITTING"
    COMPLETED = "COMPLETED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    CANCELLED = "CANCELLED"


class DecisionType(_StringEnum):
    CONFIRM_PLAN = "CONFIRM_PLAN"
    REJECT_PLAN = "REJECT_PLAN"
    ADOPT_DRAFT = "ADOPT_DRAFT"
    REJECT_DRAFT = "REJECT_DRAFT"
    APPROVE_CHANGESET = "APPROVE_CHANGESET"
    REJECT_CHANGESET = "REJECT_CHANGESET"
    CONFIRM_NO_CANON_CHANGE = "CONFIRM_NO_CANON_CHANGE"
    CANCEL_TASK = "CANCEL_TASK"


class DecisionOutcome(_StringEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class ReviewVerdict(_StringEnum):
    PASS = "PASS"
    REVISE = "REVISE"
    BLOCK = "BLOCK"


class ReviewSeverity(_StringEnum):
    BLOCKING = "BLOCKING"
    MAJOR = "MAJOR"
    MINOR = "MINOR"
    INFO = "INFO"


class DraftKind(_StringEnum):
    AUTHOR_REVISION = "AUTHOR_REVISION"
    MODEL_CANDIDATE = "MODEL_CANDIDATE"


def _require_non_empty(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise InvalidDomainValue(f"{field_name} must be non-empty")


def _require_positive(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise InvalidDomainValue(f"{field_name} must be a positive integer")


def _require_non_negative(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise InvalidDomainValue(f"{field_name} must be a non-negative integer")


def _require_aware_datetime(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise InvalidDomainValue(f"{field_name} must be timezone-aware")


def _require_tuple(value: object, field_name: str) -> None:
    if not isinstance(value, tuple):
        raise InvalidDomainValue(f"{field_name} must be a tuple")


def _require_tuple_of_strings(value: tuple[str, ...], field_name: str) -> None:
    _require_tuple(value, field_name)
    if any(not isinstance(item, str) for item in value):
        raise InvalidDomainValue(f"{field_name} must contain only strings")


def _verify_payload(payload: dict[str, object], content_hash: str) -> None:
    validate_content_hash_format(content_hash)
    if not verify_content_hash(payload, content_hash):
        raise InvalidContentHash("content hash does not match the explicit payload")


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    artifact_id: str
    schema_version: int
    content_hash: str

    def __post_init__(self) -> None:
        _require_non_empty(self.artifact_id, "artifact_id")
        _require_positive(self.schema_version, "schema_version")
        validate_content_hash_format(self.content_hash)


@dataclass(frozen=True, slots=True)
class SourceRef:
    kind: SourceKind
    actor_id: str | None = None
    model_run_id: str | None = None
    source_artifact_refs: tuple[ArtifactRef, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SourceKind):
            raise InvalidDomainValue("kind must be SourceKind")
        _require_tuple(self.source_artifact_refs, "source_artifact_refs")
        if any(not isinstance(ref, ArtifactRef) for ref in self.source_artifact_refs):
            raise InvalidDomainValue("source_artifact_refs must contain ArtifactRef values")
        if self.kind is SourceKind.AUTHOR:
            _require_non_empty(self.actor_id or "", "actor_id")
        if self.kind is SourceKind.MODEL:
            _require_non_empty(self.model_run_id or "", "model_run_id")


@dataclass(frozen=True, slots=True)
class CreativeIntent:
    intent_id: str
    schema_version: int
    task_id: str
    objective: str
    required_elements: tuple[str, ...]
    constraints: tuple[str, ...]
    source: SourceRef
    created_at: datetime
    content_hash: str

    def __post_init__(self) -> None:
        _require_non_empty(self.intent_id, "intent_id")
        _require_positive(self.schema_version, "schema_version")
        _require_non_empty(self.task_id, "task_id")
        _require_non_empty(self.objective, "objective")
        _require_tuple_of_strings(self.required_elements, "required_elements")
        _require_tuple_of_strings(self.constraints, "constraints")
        if not isinstance(self.source, SourceRef):
            raise InvalidDomainValue("source must be SourceRef")
        _require_aware_datetime(self.created_at, "created_at")
        _verify_payload(self.content_payload(), self.content_hash)

    def content_payload(self) -> dict[str, object]:
        return {
            "intent_id": self.intent_id,
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "objective": self.objective,
            "required_elements": self.required_elements,
            "constraints": self.constraints,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class ChapterBeat:
    order: int
    description: str

    def __post_init__(self) -> None:
        _require_positive(self.order, "order")
        _require_non_empty(self.description, "description")


@dataclass(frozen=True, slots=True)
class ChapterPlan:
    plan_id: str
    schema_version: int
    revision_number: int
    task_id: str
    creative_intent_ref: ArtifactRef
    title: str | None
    chapter_goal: str
    beats: tuple[ChapterBeat, ...]
    ending_hook: str | None
    based_on_canon_revision: int
    based_on_canon_hash: str
    source: SourceRef
    created_at: datetime
    content_hash: str

    def __post_init__(self) -> None:
        _require_non_empty(self.plan_id, "plan_id")
        _require_positive(self.schema_version, "schema_version")
        _require_positive(self.revision_number, "revision_number")
        _require_non_empty(self.task_id, "task_id")
        if not isinstance(self.creative_intent_ref, ArtifactRef):
            raise InvalidDomainValue("creative_intent_ref must be ArtifactRef")
        _require_non_empty(self.chapter_goal, "chapter_goal")
        _require_tuple(self.beats, "beats")
        if any(not isinstance(beat, ChapterBeat) for beat in self.beats):
            raise InvalidDomainValue("beats must contain ChapterBeat values")
        orders = [beat.order for beat in self.beats]
        if len(orders) != len(set(orders)):
            raise InvalidDomainValue("beat order values must be unique")
        _require_non_negative(self.based_on_canon_revision, "based_on_canon_revision")
        validate_content_hash_format(self.based_on_canon_hash)
        if not isinstance(self.source, SourceRef):
            raise InvalidDomainValue("source must be SourceRef")
        _require_aware_datetime(self.created_at, "created_at")
        _verify_payload(self.content_payload(), self.content_hash)

    def content_payload(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "schema_version": self.schema_version,
            "revision_number": self.revision_number,
            "task_id": self.task_id,
            "creative_intent_ref": self.creative_intent_ref,
            "title": self.title,
            "chapter_goal": self.chapter_goal,
            "beats": self.beats,
            "ending_hook": self.ending_hook,
            "based_on_canon_revision": self.based_on_canon_revision,
            "based_on_canon_hash": self.based_on_canon_hash,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class DraftRevision:
    draft_id: str
    schema_version: int
    revision_number: int
    task_id: str
    parent_draft_ref: ArtifactRef | None
    kind: DraftKind
    content: str
    based_on_plan_ref: ArtifactRef
    working_snapshot_ref: ArtifactRef | None
    source: SourceRef
    created_at: datetime
    content_hash: str

    def __post_init__(self) -> None:
        _require_non_empty(self.draft_id, "draft_id")
        _require_positive(self.schema_version, "schema_version")
        _require_positive(self.revision_number, "revision_number")
        _require_non_empty(self.task_id, "task_id")
        if self.parent_draft_ref is not None and not isinstance(self.parent_draft_ref, ArtifactRef):
            raise InvalidDomainValue("parent_draft_ref must be ArtifactRef")
        if not isinstance(self.kind, DraftKind):
            raise InvalidDomainValue("kind must be DraftKind")
        _require_non_empty(self.content, "content")
        if not isinstance(self.based_on_plan_ref, ArtifactRef):
            raise InvalidDomainValue("based_on_plan_ref must be ArtifactRef")
        if self.working_snapshot_ref is not None and not isinstance(
            self.working_snapshot_ref, ArtifactRef
        ):
            raise InvalidDomainValue("working_snapshot_ref must be ArtifactRef")
        if not isinstance(self.source, SourceRef):
            raise InvalidDomainValue("source must be SourceRef")
        if self.kind is DraftKind.AUTHOR_REVISION and self.source.kind is not SourceKind.AUTHOR:
            raise InvalidDomainValue("author revisions require an AUTHOR source")
        if self.kind is DraftKind.MODEL_CANDIDATE and self.source.kind is not SourceKind.MODEL:
            raise InvalidDomainValue("model candidates require a MODEL source")
        _require_aware_datetime(self.created_at, "created_at")
        _verify_payload(self.content_payload(), self.content_hash)

    def content_payload(self) -> dict[str, object]:
        return {
            "draft_id": self.draft_id,
            "schema_version": self.schema_version,
            "revision_number": self.revision_number,
            "task_id": self.task_id,
            "parent_draft_ref": self.parent_draft_ref,
            "kind": self.kind,
            "content": self.content,
            "based_on_plan_ref": self.based_on_plan_ref,
            "working_snapshot_ref": self.working_snapshot_ref,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class ReviewFinding:
    finding_id: str
    category: str
    severity: ReviewSeverity
    message: str
    evidence_draft_hash: str
    suggestion: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.finding_id, "finding_id")
        _require_non_empty(self.category, "category")
        if not isinstance(self.severity, ReviewSeverity):
            raise InvalidDomainValue("severity must be ReviewSeverity")
        _require_non_empty(self.message, "message")
        validate_content_hash_format(self.evidence_draft_hash)


@dataclass(frozen=True, slots=True)
class ReviewReport:
    review_id: str
    schema_version: int
    task_id: str
    draft_ref: ArtifactRef
    review_policy_id: str
    review_policy_version: int
    verdict: ReviewVerdict
    findings: tuple[ReviewFinding, ...]
    summary: str
    source: SourceRef
    created_at: datetime
    content_hash: str

    def __post_init__(self) -> None:
        _require_non_empty(self.review_id, "review_id")
        _require_positive(self.schema_version, "schema_version")
        _require_non_empty(self.task_id, "task_id")
        if not isinstance(self.draft_ref, ArtifactRef):
            raise InvalidDomainValue("draft_ref must be ArtifactRef")
        _require_non_empty(self.review_policy_id, "review_policy_id")
        _require_positive(self.review_policy_version, "review_policy_version")
        if not isinstance(self.verdict, ReviewVerdict):
            raise InvalidDomainValue("verdict must be ReviewVerdict")
        _require_tuple(self.findings, "findings")
        if any(not isinstance(finding, ReviewFinding) for finding in self.findings):
            raise InvalidDomainValue("findings must contain ReviewFinding values")
        if any(
            finding.evidence_draft_hash != self.draft_ref.content_hash
            for finding in self.findings
        ):
            raise InvalidDomainValue("all findings must bind to the exact reviewed draft hash")
        if not isinstance(self.source, SourceRef) or self.source.kind not in {
            SourceKind.MODEL,
            SourceKind.SYSTEM,
        }:
            raise InvalidDomainValue("review source must be MODEL or SYSTEM")
        _require_aware_datetime(self.created_at, "created_at")
        _verify_payload(self.content_payload(), self.content_hash)

    def content_payload(self) -> dict[str, object]:
        return {
            "review_id": self.review_id,
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "draft_ref": self.draft_ref,
            "review_policy_id": self.review_policy_id,
            "review_policy_version": self.review_policy_version,
            "verdict": self.verdict,
            "findings": self.findings,
            "summary": self.summary,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class AuthorDecision:
    decision_id: str
    schema_version: int
    task_id: str
    decision_type: DecisionType
    target_ref: ArtifactRef
    outcome: DecisionOutcome
    based_on_task_revision: int
    author_id: str
    reason: str | None
    source: SourceRef
    created_at: datetime
    content_hash: str

    def __post_init__(self) -> None:
        _require_non_empty(self.decision_id, "decision_id")
        _require_positive(self.schema_version, "schema_version")
        _require_non_empty(self.task_id, "task_id")
        if not isinstance(self.decision_type, DecisionType):
            raise InvalidDomainValue("decision_type must be DecisionType")
        if not isinstance(self.target_ref, ArtifactRef):
            raise InvalidDomainValue("target_ref must be ArtifactRef")
        if not isinstance(self.outcome, DecisionOutcome):
            raise InvalidDomainValue("outcome must be DecisionOutcome")
        _require_non_negative(self.based_on_task_revision, "based_on_task_revision")
        _require_non_empty(self.author_id, "author_id")
        if not isinstance(self.source, SourceRef) or self.source.kind is not SourceKind.AUTHOR:
            raise InvalidDomainValue("author decisions require an AUTHOR source")
        if self.source.actor_id != self.author_id:
            raise InvalidDomainValue("source actor_id must match author_id")
        _require_aware_datetime(self.created_at, "created_at")
        _verify_payload(self.content_payload(), self.content_hash)

    def content_payload(self) -> dict[str, object]:
        return {
            "decision_id": self.decision_id,
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "decision_type": self.decision_type,
            "target_ref": self.target_ref,
            "outcome": self.outcome,
            "based_on_task_revision": self.based_on_task_revision,
            "author_id": self.author_id,
            "reason": self.reason,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_id: str
    schema_version: int
    task_id: str
    project_id: str
    event_type: str
    actor: SourceRef
    before_task_revision: int
    after_task_revision: int
    object_refs: tuple[ArtifactRef, ...]
    operation_id: str
    created_at: datetime

    def __post_init__(self) -> None:
        _require_non_empty(self.event_id, "event_id")
        _require_positive(self.schema_version, "schema_version")
        _require_non_empty(self.task_id, "task_id")
        _require_non_empty(self.project_id, "project_id")
        _require_non_empty(self.event_type, "event_type")
        if not isinstance(self.actor, SourceRef):
            raise InvalidDomainValue("actor must be SourceRef")
        _require_non_negative(self.before_task_revision, "before_task_revision")
        _require_non_negative(self.after_task_revision, "after_task_revision")
        if self.after_task_revision < self.before_task_revision:
            raise InvalidDomainValue("after_task_revision cannot be less than before_task_revision")
        _require_tuple(self.object_refs, "object_refs")
        if any(not isinstance(ref, ArtifactRef) for ref in self.object_refs):
            raise InvalidDomainValue("object_refs must contain ArtifactRef values")
        _require_non_empty(self.operation_id, "operation_id")
        _require_aware_datetime(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class RecoveryInfo:
    failed_operation_id: str
    error_code: str
    retry_from_status: ChapterTaskStatus

    def __post_init__(self) -> None:
        _require_non_empty(self.failed_operation_id, "failed_operation_id")
        _require_non_empty(self.error_code, "error_code")
        if not isinstance(self.retry_from_status, ChapterTaskStatus):
            raise InvalidDomainValue("retry_from_status must be ChapterTaskStatus")
        if self.retry_from_status is ChapterTaskStatus.RECOVERY_REQUIRED:
            raise InvalidDomainValue("retry_from_status cannot be RECOVERY_REQUIRED")


@dataclass(frozen=True, slots=True)
class ChapterTask:
    task_id: str
    schema_version: int
    aggregate_revision: int
    project_id: str
    chapter_number: int
    status: ChapterTaskStatus
    last_stable_status: ChapterTaskStatus
    creative_intent_ref: ArtifactRef
    confirmed_plan_ref: ArtifactRef | None
    current_author_draft_ref: ArtifactRef | None
    review_target_draft_ref: ArtifactRef | None
    adopted_draft_ref: ArtifactRef | None
    latest_review_ref: ArtifactRef | None
    pending_changeset_ref: ArtifactRef | None
    commit_receipt_ref: ArtifactRef | None
    recovery: RecoveryInfo | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _require_non_empty(self.task_id, "task_id")
        _require_positive(self.schema_version, "schema_version")
        _require_non_negative(self.aggregate_revision, "aggregate_revision")
        _require_non_empty(self.project_id, "project_id")
        _require_positive(self.chapter_number, "chapter_number")
        if not isinstance(self.status, ChapterTaskStatus):
            raise InvalidDomainValue("status must be ChapterTaskStatus")
        if not isinstance(self.last_stable_status, ChapterTaskStatus):
            raise InvalidDomainValue("last_stable_status must be ChapterTaskStatus")
        if self.last_stable_status is ChapterTaskStatus.RECOVERY_REQUIRED:
            raise InvalidDomainValue("last_stable_status cannot be RECOVERY_REQUIRED")
        if not isinstance(self.creative_intent_ref, ArtifactRef):
            raise InvalidDomainValue("creative_intent_ref must be ArtifactRef")
        reference_fields = (
            self.confirmed_plan_ref,
            self.current_author_draft_ref,
            self.review_target_draft_ref,
            self.adopted_draft_ref,
            self.latest_review_ref,
            self.pending_changeset_ref,
            self.commit_receipt_ref,
        )
        if any(ref is not None and not isinstance(ref, ArtifactRef) for ref in reference_fields):
            raise InvalidDomainValue("task references must be ArtifactRef values")
        if self.status is ChapterTaskStatus.RECOVERY_REQUIRED and self.recovery is None:
            raise InvalidDomainValue("RECOVERY_REQUIRED tasks must include recovery information")
        if self.status is not ChapterTaskStatus.RECOVERY_REQUIRED and self.recovery is not None:
            raise InvalidDomainValue("only RECOVERY_REQUIRED tasks may include recovery information")
        if self.commit_receipt_ref is not None and self.status is not ChapterTaskStatus.COMPLETED:
            raise InvalidDomainValue("commit receipt requires COMPLETED status")
        if self.status is ChapterTaskStatus.COMPLETED and self.commit_receipt_ref is None:
            raise InvalidDomainValue("COMPLETED tasks require a commit receipt")
        _require_aware_datetime(self.created_at, "created_at")
        _require_aware_datetime(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise InvalidDomainValue("updated_at cannot be earlier than created_at")

