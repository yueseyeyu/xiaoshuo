"""Canonical request digests and result envelopes for creation operations."""

from __future__ import annotations

import hashlib
import hmac
import json

from xiaoshuo.domain.creation import ChapterTaskStatus, DecisionType
from xiaoshuo.domain.creation.hashing import canonicalize_json_value

from .commands import (
    CreateChapterTaskCommand,
    CreateAuthorDecisionCommand,
    ConsumeAuthorDecisionCommand,
    SubmitAuthoringArtifactCommand,
    SubmitDraftForReviewCommand,
    TransitionChapterTaskCommand,
)
from .authoring_artifact import (
    AuthoringArtifactKind,
    AuthoringArtifactSubmissionResult,
)
from .canon_commands import ApproveCanonChangesetCommand, PrepareCanonChangesetCommand
from .canon_results import (
    CANON_RESULT_SCHEMA_VERSION,
    CanonApplyResult,
    CanonChangesetResult,
    CanonRecoveryResult,
)
from .errors import CreationApplicationError
from .operation_kind import OperationKind
from .results import (
    APPLICATION_RESULT_SCHEMA_VERSION,
    AuthorDecisionResult,
    CreateChapterTaskResult,
    TransitionChapterTaskResult,
)


def _canonical_json(value: object) -> str:
    canonical = canonicalize_json_value(value)
    return json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256_text(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def compute_adopted_draft_payload_content_hash(data: bytes) -> str:
    """Return the content-address identity for adopted draft bytes."""
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def compute_request_digest(
    command: CreateChapterTaskCommand,
    operation_kind: OperationKind,
) -> str:
    """Hash every business input while excluding delivery metadata."""
    payload = {
        "command_schema_version": command.command_schema_version,
        "operation_kind": operation_kind.value,
        "task_id": command.task_id,
        "project_id": command.project_id,
        "chapter_number": command.chapter_number,
        "initial_status": command.initial_status.value,
        "creative_intent_ref": command.creative_intent_ref,
    }
    return _sha256_text(_canonical_json(payload))


def create_result_envelope(
    result: CreateChapterTaskResult,
    *,
    operation_kind: OperationKind,
    original_operation_id: str,
    audit_event_ids: tuple[str, ...],
) -> str:
    """Build the canonical, versioned application result envelope."""
    return _canonical_json(
        {
            "result_schema_version": result.result_schema_version,
            "outcome": "CREATED",
            "task_id": result.task_id,
            "task_revision": result.aggregate_revision,
            "task_status": result.status.value,
            "audit_event_ids": audit_event_ids,
            "original_operation_id": original_operation_id,
            "operation_kind": operation_kind.value,
        }
    )


def compute_envelope_hash(envelope_json: str) -> str:
    """Hash the exact canonical envelope text stored in the operation ledger."""
    return _sha256_text(envelope_json)


def verify_envelope_hash(envelope_json: str, expected_hash: str) -> bool:
    """Compare an envelope hash without accepting a malformed representation."""
    actual_hash = compute_envelope_hash(envelope_json)
    return hmac.compare_digest(actual_hash, expected_hash)


def result_from_envelope(
    envelope_json: str, *, expected_task_id: str | None = None
) -> CreateChapterTaskResult:
    """Reconstruct a create result from a stored application envelope."""
    try:
        payload = json.loads(envelope_json)
        if not isinstance(payload, dict):
            raise ValueError("envelope root must be an object")
        if payload["outcome"] != "CREATED":
            raise ValueError("unsupported create outcome")
        if payload["operation_kind"] != OperationKind.CREATE_CHAPTER_TASK.value:
            raise ValueError("unexpected operation kind")
        if (
            type(payload["result_schema_version"]) is not int
            or payload["result_schema_version"] != APPLICATION_RESULT_SCHEMA_VERSION
        ):
            raise ValueError("unsupported result schema version")
        if type(payload["task_id"]) is not str or not payload["task_id"]:
            raise ValueError("task_id must be a non-empty string")
        if expected_task_id is not None and payload["task_id"] != expected_task_id:
            raise ValueError("envelope task_id does not match the request")
        if type(payload["task_revision"]) is not int or payload["task_revision"] < 0:
            raise ValueError("task_revision must be a non-negative integer")
        if type(payload["task_status"]) is not str:
            raise ValueError("task_status must be a string")
        if type(payload["original_operation_id"]) is not str or not payload[
            "original_operation_id"
        ]:
            raise ValueError("original_operation_id must be a non-empty string")
        audit_ids = payload["audit_event_ids"]
        if (
            not isinstance(audit_ids, list)
            or not audit_ids
            or any(type(value) is not str or not value for value in audit_ids)
        ):
            raise ValueError("audit_event_ids must contain non-empty strings")
        return CreateChapterTaskResult(
            task_id=payload["task_id"],
            aggregate_revision=payload["task_revision"],
            status=ChapterTaskStatus(payload["task_status"]),
            result_schema_version=payload["result_schema_version"],
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CreationApplicationError("invalid stored create result envelope") from exc


# ---------------------------------------------------------------------------
# Transition digest and envelope (B2a)
# ---------------------------------------------------------------------------


def compute_transition_request_digest(
    command: TransitionChapterTaskCommand,
    operation_kind: OperationKind,
) -> str:
    """Hash every business input while excluding delivery metadata.

    ``TransitionOperationContext`` is deliberately **not** included.
    """
    payload = {
        "command_schema_version": command.command_schema_version,
        "operation_kind": operation_kind.value,
        "task_id": command.task_id,
        "target_status": command.target_status.value,
        "expected_revision": command.expected_revision,
        "recovery": command.recovery,
    }
    return _sha256_text(_canonical_json(payload))


def create_transition_result_envelope(
    result: TransitionChapterTaskResult,
    *,
    operation_kind: OperationKind,
    original_operation_id: str,
    audit_event_ids: tuple[str, ...],
) -> str:
    """Build the canonical, versioned transition result envelope."""
    return _canonical_json(
        {
            "result_schema_version": result.result_schema_version,
            "outcome": "TRANSITIONED",
            "task_id": result.task_id,
            "task_revision": result.aggregate_revision,
            "task_status": result.status.value,
            "audit_event_ids": audit_event_ids,
            "original_operation_id": original_operation_id,
            "operation_kind": operation_kind.value,
        }
    )


def result_from_transition_envelope(
    envelope_json: str, *, expected_task_id: str | None = None
) -> TransitionChapterTaskResult:
    """Reconstruct a transition result from a stored application envelope."""
    try:
        payload = json.loads(envelope_json)
        if not isinstance(payload, dict):
            raise ValueError("envelope root must be an object")
        if payload["outcome"] != "TRANSITIONED":
            raise ValueError("unsupported transition outcome")
        if payload["operation_kind"] != OperationKind.TRANSITION_CHAPTER_TASK.value:
            raise ValueError("unexpected operation kind")
        if (
            type(payload["result_schema_version"]) is not int
            or payload["result_schema_version"] != APPLICATION_RESULT_SCHEMA_VERSION
        ):
            raise ValueError("unsupported result schema version")
        if type(payload["task_id"]) is not str or not payload["task_id"]:
            raise ValueError("task_id must be a non-empty string")
        if expected_task_id is not None and payload["task_id"] != expected_task_id:
            raise ValueError("envelope task_id does not match the request")
        if type(payload["task_revision"]) is not int or payload["task_revision"] < 0:
            raise ValueError("task_revision must be a non-negative integer")
        if type(payload["task_status"]) is not str:
            raise ValueError("task_status must be a string")
        if (
            type(payload["original_operation_id"]) is not str
            or not payload["original_operation_id"]
        ):
            raise ValueError("original_operation_id must be a non-empty string")
        audit_ids = payload["audit_event_ids"]
        if (
            not isinstance(audit_ids, list)
            or not audit_ids
            or any(type(value) is not str or not value for value in audit_ids)
        ):
            raise ValueError("audit_event_ids must contain non-empty strings")
        return TransitionChapterTaskResult(
            task_id=payload["task_id"],
            aggregate_revision=payload["task_revision"],
            status=ChapterTaskStatus(payload["task_status"]),
            result_schema_version=payload["result_schema_version"],
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CreationApplicationError(
            "invalid stored transition result envelope"
        ) from exc


# ---------------------------------------------------------------------------
# AuthorDecision creation digest and envelope (B2b)
# ---------------------------------------------------------------------------


def compute_decision_creation_request_digest(
    command: CreateAuthorDecisionCommand,
    operation_kind: OperationKind,
) -> str:
    """Hash every business input while excluding delivery metadata.

    ``DecisionCreationContext`` is deliberately **not** included.
    """
    payload = {
        "command_schema_version": command.command_schema_version,
        "operation_kind": operation_kind.value,
        "task_id": command.task_id,
        "decision_type": command.decision_type.value,
        "target_ref": {
            "artifact_id": command.target_ref.artifact_id,
            "schema_version": command.target_ref.schema_version,
            "content_hash": command.target_ref.content_hash,
        },
        "based_on_task_revision": command.based_on_task_revision,
        "reason": command.reason,
        "adopted_draft_payload_content_hash": (
            compute_adopted_draft_payload_content_hash(
                command.adopted_draft_payload
            )
            if command.decision_type is DecisionType.ADOPT_DRAFT
            and type(command.adopted_draft_payload) is bytes
            else None
        ),
    }
    return _sha256_text(_canonical_json(payload))


def create_decision_creation_result_envelope(
    result: AuthorDecisionResult,
    *,
    operation_kind: OperationKind,
    original_operation_id: str,
) -> str:
    """Build the canonical, versioned decision creation result envelope."""
    return _canonical_json(
        {
            "result_schema_version": result.result_schema_version,
            "outcome": "DECISION_CREATED",
            "decision_id": result.decision_id,
            "task_id": result.task_id,
            "original_operation_id": original_operation_id,
            "operation_kind": operation_kind.value,
        }
    )


def result_from_decision_creation_envelope(
    envelope_json: str, *, expected_decision_id: str | None = None
) -> AuthorDecisionResult:
    """Reconstruct a decision creation result from a stored application envelope."""
    try:
        payload = json.loads(envelope_json)
        if not isinstance(payload, dict):
            raise ValueError("envelope root must be an object")
        if payload["outcome"] != "DECISION_CREATED":
            raise ValueError("unsupported decision creation outcome")
        if payload["operation_kind"] != OperationKind.CREATE_AUTHOR_DECISION.value:
            raise ValueError("unexpected operation kind")
        if (
            type(payload["result_schema_version"]) is not int
            or payload["result_schema_version"] != APPLICATION_RESULT_SCHEMA_VERSION
        ):
            raise ValueError("unsupported result schema version")
        if type(payload["decision_id"]) is not str or not payload["decision_id"]:
            raise ValueError("decision_id must be a non-empty string")
        if (
            expected_decision_id is not None
            and payload["decision_id"] != expected_decision_id
        ):
            raise ValueError("envelope decision_id does not match the request")
        if type(payload["task_id"]) is not str or not payload["task_id"]:
            raise ValueError("task_id must be a non-empty string")
        if (
            type(payload["original_operation_id"]) is not str
            or not payload["original_operation_id"]
        ):
            raise ValueError("original_operation_id must be a non-empty string")
        return AuthorDecisionResult(
            decision_id=payload["decision_id"],
            task_id=payload["task_id"],
            result_schema_version=payload["result_schema_version"],
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CreationApplicationError(
            "invalid stored decision creation result envelope"
        ) from exc


# ---------------------------------------------------------------------------
# AuthorDecision consumption digest and envelope (B2b)
# ---------------------------------------------------------------------------


def compute_decision_consumption_request_digest(
    command: ConsumeAuthorDecisionCommand,
    operation_kind: OperationKind,
) -> str:
    """Hash every business input while excluding delivery metadata.

    ``TransitionOperationContext`` is deliberately **not** included.
    """
    payload = {
        "command_schema_version": command.command_schema_version,
        "operation_kind": operation_kind.value,
        "task_id": command.task_id,
        "decision_id": command.decision_id,
        "expected_revision": command.expected_revision,
    }
    return _sha256_text(_canonical_json(payload))


def create_decision_consumption_result_envelope(
    result: TransitionChapterTaskResult,
    *,
    operation_kind: OperationKind,
    original_operation_id: str,
    audit_event_ids: tuple[str, ...],
) -> str:
    """Build the canonical, versioned decision consumption result envelope."""
    return _canonical_json(
        {
            "result_schema_version": result.result_schema_version,
            "outcome": "TRANSITIONED",
            "task_id": result.task_id,
            "task_revision": result.aggregate_revision,
            "task_status": result.status.value,
            "audit_event_ids": audit_event_ids,
            "original_operation_id": original_operation_id,
            "operation_kind": operation_kind.value,
        }
    )


def result_from_decision_consumption_envelope(
    envelope_json: str, *, expected_task_id: str | None = None
) -> TransitionChapterTaskResult:
    """Reconstruct a decision consumption result from a stored application envelope."""
    try:
        payload = json.loads(envelope_json)
        if not isinstance(payload, dict):
            raise ValueError("envelope root must be an object")
        if payload["outcome"] != "TRANSITIONED":
            raise ValueError("unsupported consumption outcome")
        if payload["operation_kind"] != OperationKind.CONSUME_AUTHOR_DECISION.value:
            raise ValueError("unexpected operation kind")
        if (
            type(payload["result_schema_version"]) is not int
            or payload["result_schema_version"] != APPLICATION_RESULT_SCHEMA_VERSION
        ):
            raise ValueError("unsupported result schema version")
        if type(payload["task_id"]) is not str or not payload["task_id"]:
            raise ValueError("task_id must be a non-empty string")
        if (
            expected_task_id is not None
            and payload["task_id"] != expected_task_id
        ):
            raise ValueError("envelope task_id does not match the request")
        if type(payload["task_revision"]) is not int or payload["task_revision"] < 0:
            raise ValueError("task_revision must be a non-negative integer")
        if type(payload["task_status"]) is not str:
            raise ValueError("task_status must be a string")
        if (
            type(payload["original_operation_id"]) is not str
            or not payload["original_operation_id"]
        ):
            raise ValueError("original_operation_id must be a non-empty string")
        audit_ids = payload["audit_event_ids"]
        if (
            not isinstance(audit_ids, list)
            or not audit_ids
            or any(type(value) is not str or not value for value in audit_ids)
        ):
            raise ValueError("audit_event_ids must contain non-empty strings")
        return TransitionChapterTaskResult(
            task_id=payload["task_id"],
            aggregate_revision=payload["task_revision"],
            status=ChapterTaskStatus(payload["task_status"]),
            result_schema_version=payload["result_schema_version"],
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CreationApplicationError(
            "invalid stored decision consumption result envelope"
        ) from exc


# ---------------------------------------------------------------------------
# C5-G0 G0-B authoring artifact digests and envelopes
# ---------------------------------------------------------------------------


def compute_authoring_submission_request_digest(
    command: SubmitAuthoringArtifactCommand | SubmitDraftForReviewCommand,
    envelope_content_hash: str,
    operation_kind: OperationKind,
) -> str:
    """Hash business and command identity without retaining raw envelope bytes."""
    payload = {
        "command_schema_version": command.command_schema_version,
        "operation_kind": operation_kind.value,
        "task_id": command.task_id,
        "expected_revision": command.expected_revision,
        "envelope_content_hash": envelope_content_hash,
    }
    return _sha256_text(_canonical_json(payload))


def create_authoring_submission_result_envelope(
    result: AuthoringArtifactSubmissionResult,
    *,
    operation_kind: OperationKind,
) -> str:
    """Persist only stable scalar identities; operator-owned bytes stay external."""
    outcome = (
        "AUTHORING_DRAFT_SUBMITTED"
        if operation_kind is OperationKind.SUBMIT_AUTHORING_ARTIFACT
        else "DRAFT_REVIEW_SUBMITTED"
    )
    return _canonical_json(
        {
            "result_schema_version": result.result_schema_version,
            "outcome": outcome,
            "artifact_kind": result.artifact_kind.value,
            "artifact_ref": {
                "artifact_id": result.artifact_ref.artifact_id,
                "schema_version": result.artifact_ref.schema_version,
                "content_hash": result.artifact_ref.content_hash,
            },
            "task_id": result.task_id,
            "task_revision": result.aggregate_revision,
            "task_status": result.status.value,
            "audit_event_ids": result.audit_event_ids,
            "original_operation_id": result.operation_id,
            "operation_kind": operation_kind.value,
        }
    )


def result_from_authoring_submission_envelope(
    envelope_json: str,
    *,
    expected_task_id: str,
    expected_kind: OperationKind,
) -> AuthoringArtifactSubmissionResult:
    """Strictly rebuild the original G0-B result for ledger replay."""
    try:
        payload = json.loads(envelope_json, parse_constant=_reject_json_constant)
        expected_fields = {
            "result_schema_version",
            "outcome",
            "artifact_kind",
            "artifact_ref",
            "task_id",
            "task_revision",
            "task_status",
            "audit_event_ids",
            "original_operation_id",
            "operation_kind",
        }
        if (
            not isinstance(payload, dict)
            or set(payload) != expected_fields
            or _canonical_json(payload) != envelope_json
            or payload["operation_kind"] != expected_kind.value
        ):
            raise ValueError("unexpected authoring result envelope")
        if expected_kind is OperationKind.SUBMIT_AUTHORING_ARTIFACT:
            expected_outcome = "AUTHORING_DRAFT_SUBMITTED"
            expected_artifact_kind = AuthoringArtifactKind.DRAFT
            expected_status = ChapterTaskStatus.REVIEWING
        elif expected_kind is OperationKind.SUBMIT_DRAFT_FOR_REVIEW:
            expected_outcome = "DRAFT_REVIEW_SUBMITTED"
            expected_artifact_kind = AuthoringArtifactKind.REVIEW
            expected_status = ChapterTaskStatus.DRAFT_APPROVAL_PENDING
        else:
            raise ValueError("unsupported authoring operation kind")
        if (
            payload["outcome"] != expected_outcome
            or payload["artifact_kind"] != expected_artifact_kind.value
            or payload["task_id"] != expected_task_id
            or payload["task_status"] != expected_status.value
            or type(payload["result_schema_version"]) is not int
            or payload["result_schema_version"] != APPLICATION_RESULT_SCHEMA_VERSION
            or type(payload["task_revision"]) is not int
            or payload["task_revision"] < 1
            or not isinstance(payload["original_operation_id"], str)
            or not payload["original_operation_id"]
        ):
            raise ValueError("authoring result identity mismatch")
        audit_ids = payload["audit_event_ids"]
        if (
            not isinstance(audit_ids, list)
            or len(audit_ids) != 1
            or any(type(value) is not str or not value for value in audit_ids)
        ):
            raise ValueError("invalid authoring audit identity")
        return AuthoringArtifactSubmissionResult(
            artifact_kind=expected_artifact_kind,
            artifact_ref=_artifact_ref_from_envelope(payload["artifact_ref"]),
            task_id=payload["task_id"],
            aggregate_revision=payload["task_revision"],
            status=expected_status,
            operation_id=payload["original_operation_id"],
            audit_event_ids=tuple(audit_ids),
            result_schema_version=payload["result_schema_version"],
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CreationApplicationError(
            "invalid stored authoring result envelope"
        ) from exc


# ---------------------------------------------------------------------------
# C3 Canon ChangeSet digest and envelope
# ---------------------------------------------------------------------------


def compute_canon_prepare_request_digest(
    command: PrepareCanonChangesetCommand,
    bundle_content_hash: str,
    operation_kind: OperationKind,
) -> str:
    """Digest C3 business inputs, never delivery context metadata."""
    payload = {
        "command_schema_version": command.command_schema_version,
        "operation_kind": operation_kind.value,
        "task_id": command.task_id,
        "expected_revision": command.expected_revision,
        "bundle_content_hash": bundle_content_hash,
    }
    # v1 digests remain replayable exactly as originally persisted.  v2 never
    # includes caller-supplied base identity; the activation reader is the
    # sole authority for that fact.
    if command.command_schema_version == 1:
        payload["base_manifest_hash"] = command.base_manifest_hash
    return _sha256_text(_canonical_json(payload))


def compute_canon_approve_request_digest(
    command: ApproveCanonChangesetCommand,
    *,
    operation_kind: OperationKind,
) -> str:
    """Digest only the approval command identity, excluding delivery context."""
    return _sha256_text(_canonical_json({
        "command_schema_version": command.command_schema_version,
        "operation_kind": operation_kind.value,
        "task_id": command.task_id,
        "decision_id": command.decision_id,
        "expected_revision": command.expected_revision,
    }))


def create_canon_result_envelope(
    result: CanonChangesetResult,
    *,
    operation_kind: OperationKind,
    original_operation_id: str,
    audit_event_ids: tuple[str, ...],
) -> str:
    """Build a versioned C3 operation envelope persisted verbatim in the ledger."""
    return _canonical_json({
        "result_schema_version": result.result_schema_version,
        "outcome": "CANON_CHANGESET_PREPARED" if result.journal_id is None else "CANON_COMMIT_INTENDED",
        "task_id": result.task_id,
        "task_revision": result.aggregate_revision,
        "task_status": result.status.value,
        "changeset_ref": {
            "artifact_id": result.changeset_ref.artifact_id,
            "schema_version": result.changeset_ref.schema_version,
            "content_hash": result.changeset_ref.content_hash,
        },
        "target_bundle_ref": {
            "artifact_id": result.target_bundle_ref.artifact_id,
            "schema_version": result.target_bundle_ref.schema_version,
            "content_hash": result.target_bundle_ref.content_hash,
        },
        "base_manifest_hash": result.base_manifest_hash,
        "target_manifest_hash": result.target_manifest_hash,
        "journal_id": result.journal_id,
        "audit_event_ids": audit_event_ids,
        "original_operation_id": original_operation_id,
        "operation_kind": operation_kind.value,
    })


def result_from_canon_envelope(
    envelope_json: str,
    *,
    expected_task_id: str,
    expected_kind: OperationKind,
) -> CanonChangesetResult:
    """Rebuild a C3 result strictly from the original persisted envelope."""
    try:
        payload = json.loads(envelope_json)
        expected_keys = {
            "result_schema_version", "outcome", "task_id", "task_revision",
            "task_status", "changeset_ref", "target_bundle_ref", "base_manifest_hash",
            "target_manifest_hash", "journal_id", "audit_event_ids",
            "original_operation_id", "operation_kind",
        }
        if (
            not isinstance(payload, dict)
            or set(payload) != expected_keys
            or _canonical_json(payload) != envelope_json
            or payload["operation_kind"] != expected_kind.value
        ):
            raise ValueError("unexpected Canon envelope kind")
        expected_outcome = "CANON_CHANGESET_PREPARED" if expected_kind is OperationKind.PREPARE_CANON_CHANGESET else "CANON_COMMIT_INTENDED"
        if payload["outcome"] != expected_outcome or payload["task_id"] != expected_task_id:
            raise ValueError("Canon envelope identity mismatch")
        if type(payload["result_schema_version"]) is not int or payload["result_schema_version"] != CANON_RESULT_SCHEMA_VERSION:
            raise ValueError("unsupported Canon result schema")
        if type(payload["task_id"]) is not str or not payload["task_id"]:
            raise ValueError("invalid Canon task id")
        if type(payload["task_revision"]) is not int or payload["task_revision"] < 0:
            raise ValueError("invalid Canon revision")
        if not isinstance(payload["task_status"], str):
            raise ValueError("invalid Canon status")
        expected_status = (
            ChapterTaskStatus.CHANGESET_APPROVAL_PENDING
            if expected_kind is OperationKind.PREPARE_CANON_CHANGESET
            else ChapterTaskStatus.COMMITTING
        )
        if payload["task_status"] != expected_status.value:
            raise ValueError("unexpected Canon task status")
        if not _is_sha256(payload["base_manifest_hash"]) or not _is_sha256(payload["target_manifest_hash"]):
            raise ValueError("invalid Canon hash")
        if (
            not isinstance(payload["audit_event_ids"], list)
            or not payload["audit_event_ids"]
            or any(type(value) is not str or not value for value in payload["audit_event_ids"])
        ):
            raise ValueError("invalid Canon audit ids")
        if not isinstance(payload["original_operation_id"], str) or not payload["original_operation_id"]:
            raise ValueError("invalid Canon operation id")
        changeset = _artifact_ref_from_envelope(payload["changeset_ref"])
        bundle = _artifact_ref_from_envelope(payload["target_bundle_ref"])
        journal_id = payload["journal_id"]
        if expected_kind is OperationKind.PREPARE_CANON_CHANGESET:
            if journal_id is not None:
                raise ValueError("prepare envelope cannot have journal")
        elif not isinstance(journal_id, str) or not journal_id:
            raise ValueError("approve envelope requires journal")
        return CanonChangesetResult(
            task_id=payload["task_id"], aggregate_revision=payload["task_revision"],
            status=ChapterTaskStatus(payload["task_status"]), changeset_ref=changeset,
            target_bundle_ref=bundle, base_manifest_hash=payload["base_manifest_hash"],
            target_manifest_hash=payload["target_manifest_hash"], journal_id=journal_id,
            result_schema_version=payload["result_schema_version"],
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CreationApplicationError("invalid stored Canon result envelope") from exc


def compute_canon_apply_request_digest(command, *, operation_kind: OperationKind) -> str:
    payload = {
        "command_schema_version": command.command_schema_version,
        "operation_kind": operation_kind.value,
        "task_id": command.task_id,
        "journal_id": command.journal_id,
        "expected_revision": command.expected_revision,
    }
    return _sha256_text(_canonical_json(payload))


def compute_canon_recovery_request_digest(command, *, operation_kind: OperationKind) -> str:
    payload = {
        "command_schema_version": command.command_schema_version,
        "operation_kind": operation_kind.value,
        "task_id": command.task_id,
        "journal_id": command.journal_id,
        "expected_revision": command.expected_revision,
    }
    return _sha256_text(_canonical_json(payload))


def _artifact_payload(ref) -> dict[str, object]:
    return {
        "artifact_id": ref.artifact_id,
        "schema_version": ref.schema_version,
        "content_hash": ref.content_hash,
    }


def create_canon_apply_result_envelope(
    result: CanonApplyResult,
    *,
    operation_kind: OperationKind,
    original_operation_id: str,
    audit_event_ids: tuple[str, ...],
    outcome: str = "APPLIED",
) -> str:
    payload: dict[str, object] = {
        "result_schema_version": result.result_schema_version,
        "outcome": outcome,
        "task_id": result.task_id,
        "task_revision": result.aggregate_revision,
        "task_status": result.status.value,
        "journal_id": result.journal_id,
        "operation_id": result.operation_id,
        "receipt_id": result.receipt_id,
        "receipt_ref": _artifact_payload(result.receipt_ref) if result.receipt_ref else None,
        "audit_event_ids": audit_event_ids,
        "original_operation_id": original_operation_id,
        "operation_kind": operation_kind.value,
    }
    return _canonical_json(payload)


def result_from_canon_apply_envelope(
    envelope_json: str,
    *,
    expected_task_id: str | None = None,
    expected_kind: OperationKind = OperationKind.APPLY_CANON_COMMIT,
) -> CanonApplyResult:
    try:
        payload = json.loads(envelope_json)
        expected_fields = {
            "result_schema_version", "outcome", "task_id", "task_revision",
            "task_status", "journal_id", "operation_id", "receipt_id",
            "receipt_ref", "audit_event_ids", "original_operation_id",
            "operation_kind",
        }
        if not isinstance(payload, dict) or set(payload) != expected_fields:
            raise ValueError("invalid Canon Apply envelope fields")
        if envelope_json != _canonical_json(payload):
            raise ValueError("Canon Apply envelope is not canonical")
        if payload.get("operation_kind") != expected_kind.value:
            raise ValueError("unexpected Canon Apply operation kind")
        outcome = payload.get("outcome")
        if outcome not in {"APPLIED", "RECOVERY_REQUIRED"}:
            raise ValueError("unsupported Canon Apply outcome")
        if payload.get("result_schema_version") != CANON_RESULT_SCHEMA_VERSION:
            raise ValueError("unsupported Canon Apply result schema version")
        task_id = payload["task_id"]
        if not isinstance(task_id, str) or not task_id or (expected_task_id and task_id != expected_task_id):
            raise ValueError("invalid Canon Apply task_id")
        revision = payload["task_revision"]
        if type(revision) is not int or revision < 0:
            raise ValueError("invalid Canon Apply revision")
        journal_id = payload["journal_id"]
        operation_id = payload["operation_id"]
        original_operation_id = payload["original_operation_id"]
        if (
            not isinstance(journal_id, str) or not journal_id
            or not isinstance(operation_id, str) or not operation_id
            or original_operation_id != operation_id
        ):
            raise ValueError("invalid Canon Apply identity")
        receipt_ref_data = payload.get("receipt_ref")
        receipt_ref = None
        if receipt_ref_data is not None:
            from xiaoshuo.domain.creation import ArtifactRef
            if not isinstance(receipt_ref_data, dict) or set(receipt_ref_data) != {"artifact_id", "schema_version", "content_hash"}:
                raise ValueError("invalid receipt_ref")
            receipt_ref = ArtifactRef(**receipt_ref_data)
        receipt_id = payload["receipt_id"]
        if outcome == "APPLIED":
            if (
                payload.get("task_status") != ChapterTaskStatus.COMPLETED.value
                or not isinstance(receipt_id, str) or not receipt_id
                or receipt_ref is None
            ):
                raise ValueError("invalid completed Canon Apply receipt")
        elif (
            payload.get("task_status") != ChapterTaskStatus.RECOVERY_REQUIRED.value
            or receipt_id is not None
            or receipt_ref is not None
        ):
            raise ValueError("invalid Canon Apply recovery result")
        audit_ids = payload["audit_event_ids"]
        if not isinstance(audit_ids, list) or any(not isinstance(v, str) or not v for v in audit_ids):
            raise ValueError("invalid audit_event_ids")
        return CanonApplyResult(
            task_id=task_id,
            aggregate_revision=revision,
            status=ChapterTaskStatus(payload["task_status"]),
            journal_id=journal_id,
            operation_id=operation_id,
            receipt_id=receipt_id,
            receipt_ref=receipt_ref,
            audit_event_ids=tuple(audit_ids),
            result_schema_version=payload["result_schema_version"],
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CreationApplicationError("invalid stored Canon Apply result envelope") from exc


def create_canon_recovery_result_envelope(
    result: CanonRecoveryResult,
    *,
    operation_kind: OperationKind,
    original_operation_id: str,
    audit_event_ids: tuple[str, ...],
) -> str:
    return _canonical_json({
        "result_schema_version": result.result_schema_version,
        "outcome": "RECOVERED" if result.status is ChapterTaskStatus.COMMITTING else "RECOVERY_REQUIRED",
        "task_id": result.task_id,
        "task_revision": result.aggregate_revision,
        "task_status": result.status.value,
        "journal_id": result.journal_id,
        "operation_id": result.operation_id,
        "audit_event_ids": audit_event_ids,
        "original_operation_id": original_operation_id,
        "operation_kind": operation_kind.value,
    })


def result_from_canon_recovery_envelope(
    envelope_json: str,
    *,
    expected_task_id: str | None = None,
    expected_kind: OperationKind = OperationKind.RECOVER_CANON_COMMIT,
) -> CanonRecoveryResult:
    try:
        payload = json.loads(envelope_json)
        expected_fields = {
            "result_schema_version", "outcome", "task_id", "task_revision",
            "task_status", "journal_id", "operation_id", "audit_event_ids",
            "original_operation_id", "operation_kind",
        }
        if not isinstance(payload, dict) or set(payload) != expected_fields:
            raise ValueError("invalid Canon Recovery envelope fields")
        if envelope_json != _canonical_json(payload):
            raise ValueError("Canon Recovery envelope is not canonical")
        if payload.get("operation_kind") != expected_kind.value:
            raise ValueError("unexpected Canon Recovery operation kind")
        outcome = payload.get("outcome")
        if outcome not in {"RECOVERED", "RECOVERY_REQUIRED"}:
            raise ValueError("unsupported Canon Recovery outcome")
        if payload.get("result_schema_version") != CANON_RESULT_SCHEMA_VERSION:
            raise ValueError("unsupported Canon Recovery result schema version")
        task_id = payload["task_id"]
        if not isinstance(task_id, str) or not task_id or (expected_task_id and task_id != expected_task_id):
            raise ValueError("invalid Canon Recovery task_id")
        revision = payload["task_revision"]
        if type(revision) is not int or revision < 0:
            raise ValueError("invalid Canon Recovery revision")
        journal_id = payload["journal_id"]
        operation_id = payload["operation_id"]
        original_operation_id = payload["original_operation_id"]
        audit_ids = payload["audit_event_ids"]
        if (
            not isinstance(journal_id, str) or not journal_id
            or not isinstance(operation_id, str) or not operation_id
            or original_operation_id != operation_id
        ):
            raise ValueError("invalid Canon Recovery identity")
        if not isinstance(audit_ids, list) or any(not isinstance(v, str) or not v for v in audit_ids):
            raise ValueError("invalid audit_event_ids")
        status = ChapterTaskStatus(payload["task_status"])
        expected_status = (
            ChapterTaskStatus.COMMITTING
            if outcome == "RECOVERED"
            else ChapterTaskStatus.RECOVERY_REQUIRED
        )
        if status is not expected_status:
            raise ValueError("invalid Canon Recovery status")
        return CanonRecoveryResult(task_id, revision, status, journal_id, operation_id, tuple(audit_ids), payload["result_schema_version"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CreationApplicationError("invalid stored Canon Recovery result envelope") from exc


def _artifact_ref_from_envelope(value: object):
    from xiaoshuo.domain.creation import ArtifactRef
    if not isinstance(value, dict) or set(value) != {"artifact_id", "schema_version", "content_hash"}:
        raise ValueError("invalid artifact ref")
    return ArtifactRef(value["artifact_id"], value["schema_version"], value["content_hash"])


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(char in "0123456789abcdef" for char in value[7:])
    )


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"unsupported JSON constant {value}")
