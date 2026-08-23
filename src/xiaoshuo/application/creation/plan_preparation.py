"""Application boundary for the G0-C PLAN prelude.

The PLAN envelope is operator-owned input, while every durable identity is
derived here from the real Task and the controlled application context.  This
module intentionally has no knowledge of SQLite, paths, configuration, or a
concrete payload adapter.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID, uuid4

from xiaoshuo.domain.creation import (
    SCHEMA_VERSION,
    ArtifactRef,
    AuditEvent,
    ChapterTaskStatus,
    SourceKind,
    transition_task,
)
from xiaoshuo.domain.creation.state_machine import RevisionConflict as DomainRevisionConflict

from .authoring_artifact import (
    AuthoringArtifactEnvelope,
    AuthoringArtifactKind,
    authoring_artifact_content_hash,
    parse_authoring_artifact_envelope,
)
from .errors import (
    CreationApplicationError,
    IdempotencyConflict,
    NotFound,
    RevisionConflict,
    UnsupportedPersistenceBoundary,
)
from .local_author_context import LocalAuthorContext
from .operation_kind import OperationKind
from .ports import ImmutablePayloadStorePort
from .repository import (
    CreationUnitOfWork,
    OperationCreateOutcome,
    OperationLogRecord,
    OperationResult,
)


PLAN_PREPARATION_SCHEMA_VERSION = 1
IdFactory = Callable[[], UUID | str]
UnitOfWorkFactory = Callable[[], CreationUnitOfWork]


@dataclass(frozen=True, slots=True)
class PreparePlanForApprovalCommand:
    """Business input for PLAN preparation.

    Delivery metadata is deliberately separate.  The command accepts no
    caller-supplied identity, reference, hash, root, or connection.
    """

    task_id: str
    expected_revision: int
    envelope_bytes: bytes
    command_schema_version: int = PLAN_PREPARATION_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class PlanPreparationDeliveryContext:
    """Caller-selected idempotency key, independent of business input."""

    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.idempotency_key, str) or not self.idempotency_key.strip():
            raise ValueError("idempotency_key must be a non-empty string")


@dataclass(frozen=True, slots=True)
class PlanPreparationResult:
    plan_ref: ArtifactRef
    task_id: str
    aggregate_revision: int
    status: ChapterTaskStatus
    operation_id: str
    audit_event_ids: tuple[str, ...]
    result_schema_version: int = PLAN_PREPARATION_SCHEMA_VERSION


class PreparePlanForApprovalUseCase:
    """Persist one canonical PLAN and advance the real Task approval gate."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        author_context: LocalAuthorContext,
        payload_store: ImmutablePayloadStorePort,
        *,
        id_factory: IdFactory = uuid4,
    ) -> None:
        self._uow_factory = uow_factory
        self._author_context = author_context
        self._payload_store = payload_store
        self._id_factory = id_factory

    def prepare(
        self,
        command: PreparePlanForApprovalCommand,
        context: PlanPreparationDeliveryContext,
    ) -> PlanPreparationResult:
        _guard_command(command, context)
        try:
            uow = self._uow_factory()
        except CreationApplicationError:
            raise
        except Exception as exc:
            raise CreationApplicationError("creation persistence read failed") from exc

        rollback_done = [False]
        commit_succeeded = [False]
        close_attempted = [False]
        try:
            request_digest = _request_digest(command)
            kind = OperationKind.PREPARE_PLAN_FOR_APPROVAL

            # The operation ledger is the first persistence/business read.
            # No Task, payload, or generated identity is touched before it.
            existing = uow.operations.get_by_idempotency_key(context.idempotency_key)
            if existing is not None:
                if existing.request_digest != request_digest:
                    raise IdempotencyConflict(
                        f"idempotency key {context.idempotency_key!r} has a different request digest"
                    )
                _rollback(uow, rollback_done)
                replay = _result_from_envelope(existing.result_envelope_json, command.task_id)
                _close_once(uow, close_attempted)
                return replay

            # Canonical parsing is pure in-memory validation and is NEW-only.
            envelope = _parse_plan(command.envelope_bytes)

            task = uow.tasks.get(command.task_id)
            if task is None:
                raise NotFound(f"task {command.task_id!r} not found")
            _validate_task_binding(task, command, envelope)

            operation_id = str(self._id_factory())
            plan_ref = ArtifactRef(
                artifact_id=str(self._id_factory()),
                schema_version=1,
                content_hash=authoring_artifact_content_hash(command.envelope_bytes),
            )
            audit_event_id = str(self._id_factory())
            anticipated = PlanPreparationResult(
                plan_ref=plan_ref,
                task_id=task.task_id,
                aggregate_revision=task.aggregate_revision + 1,
                status=ChapterTaskStatus.PLAN_APPROVAL_PENDING,
                operation_id=operation_id,
                audit_event_ids=(audit_event_id,),
            )
            result_envelope = _result_envelope(anticipated)
            record = OperationLogRecord(
                operation_id=operation_id,
                idempotency_key=context.idempotency_key,
                request_digest=request_digest,
                result_envelope_json=result_envelope,
                result_envelope_hash=_hash_text(result_envelope),
                created_at=_now_text(),
            )

            outcome = uow.operations.create_or_replay_complete(record)
            if outcome.status is OperationResult.REPLAY:
                _rollback(uow, rollback_done)
                replay = _result_from_envelope(
                    _require_replay_envelope(outcome), command.task_id
                )
                _close_once(uow, close_attempted)
                return replay
            if outcome.status is OperationResult.CONFLICT:
                raise IdempotencyConflict(
                    f"idempotency key {context.idempotency_key!r} has a different request digest"
                )
            if outcome.status is not OperationResult.NEW:
                raise CreationApplicationError("unsupported operation outcome")

            # External payload storage is immutable.  A failed later UoW does
            # not authorize deletion or rewriting of a possible orphan.
            _put_and_readback(self._payload_store, command.envelope_bytes, plan_ref.content_hash)
            transitioned = transition_task(
                task,
                ChapterTaskStatus.PLAN_APPROVAL_PENDING,
                expected_revision=command.expected_revision,
            )
            audit = AuditEvent(
                event_id=audit_event_id,
                schema_version=SCHEMA_VERSION,
                task_id=transitioned.task_id,
                project_id=transitioned.project_id,
                event_type="PLAN_PREPARED_FOR_APPROVAL",
                actor=self._author_context.author_source(),
                before_task_revision=task.aggregate_revision,
                after_task_revision=transitioned.aggregate_revision,
                # The PLAN ref is registered by the existing CONFIRM_PLAN
                # decision boundary.  Preparation must not pre-confirm or
                # pre-register it through the Task/audit path.
                object_refs=(task.creative_intent_ref,),
                operation_id=operation_id,
                created_at=_now(),
            )

            uow.tasks.replace(transitioned, expected_revision=command.expected_revision)
            uow.audit.add_event(audit)
            uow.commit()
            commit_succeeded[0] = True
            _close_once(uow, close_attempted)
            return anticipated
        except Exception as original_exc:
            # Once commit returned, the durable facts belong to the caller;
            # close failure is reported without rollback or a second close.
            if commit_succeeded[0]:
                raise
            if rollback_done[0]:
                if not close_attempted[0]:
                    _close_once(uow, close_attempted)
                raise
            try:
                _rollback(uow, rollback_done)
            except CreationApplicationError as rollback_exc:
                try:
                    _close_once(uow, close_attempted)
                except CreationApplicationError as close_exc:
                    raise rollback_exc from close_exc
                raise rollback_exc
            try:
                _close_once(uow, close_attempted)
            except CreationApplicationError as close_exc:
                raise original_exc from close_exc
            raise


def _guard_command(
    command: PreparePlanForApprovalCommand,
    context: PlanPreparationDeliveryContext,
) -> None:
    if not isinstance(command, PreparePlanForApprovalCommand):
        raise UnsupportedPersistenceBoundary("PLAN preparation command is required")
    if not isinstance(context, PlanPreparationDeliveryContext):
        raise UnsupportedPersistenceBoundary("PLAN preparation context is required")
    if command.command_schema_version != PLAN_PREPARATION_SCHEMA_VERSION:
        raise UnsupportedPersistenceBoundary("unsupported PLAN preparation command schema")
    if type(command.task_id) is not str or not command.task_id.strip():
        raise UnsupportedPersistenceBoundary("task_id must be a non-empty string")
    if type(command.expected_revision) is not int or command.expected_revision < 0:
        raise UnsupportedPersistenceBoundary("expected_revision must be non-negative")
    if type(command.envelope_bytes) is not bytes:
        raise UnsupportedPersistenceBoundary("PLAN envelope must be bytes")


def _request_digest(command: PreparePlanForApprovalCommand) -> str:
    payload = {
        "command_schema_version": command.command_schema_version,
        "operation_kind": OperationKind.PREPARE_PLAN_FOR_APPROVAL.value,
        "task_id": command.task_id,
        "expected_revision": command.expected_revision,
        "envelope_hash": authoring_artifact_content_hash(command.envelope_bytes),
    }
    return _hash_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _parse_plan(data: bytes) -> AuthoringArtifactEnvelope:
    try:
        envelope = parse_authoring_artifact_envelope(data)
    except Exception as exc:
        raise UnsupportedPersistenceBoundary("PLAN envelope is not canonical") from exc
    if envelope.artifact_kind is not AuthoringArtifactKind.PLAN:
        raise UnsupportedPersistenceBoundary("PLAN preparation requires a PLAN envelope")
    return envelope


def _validate_task_binding(task, command: PreparePlanForApprovalCommand, envelope) -> None:
    if task.status is not ChapterTaskStatus.PLAN_PREPARING:
        raise UnsupportedPersistenceBoundary("Task is not in PLAN_PREPARING")
    if task.aggregate_revision != command.expected_revision:
        raise RevisionConflict("PLAN preparation expected revision does not match Task")
    if (
        envelope.project_id != task.project_id
        or envelope.task_id != task.task_id
        or envelope.chapter_number != task.chapter_number
    ):
        raise UnsupportedPersistenceBoundary("PLAN envelope Task identity mismatch")
    if not isinstance(task.creative_intent_ref, ArtifactRef):
        raise UnsupportedPersistenceBoundary("Task creative intent reference is not trusted")


def _put_and_readback(
    payload_store: ImmutablePayloadStorePort, data: bytes, expected_hash: str
) -> None:
    try:
        stored = payload_store.put(data)
        if stored != expected_hash:
            raise CreationApplicationError("PLAN payload digest does not match bytes")
        readback = payload_store.read(stored)
    except CreationApplicationError:
        raise
    except Exception as exc:
        raise CreationApplicationError("PLAN payload persistence failed") from exc
    if type(readback) is not bytes or readback != data or _sha256(readback) != expected_hash:
        raise CreationApplicationError("PLAN payload readback identity mismatch")


def _result_envelope(result: PlanPreparationResult) -> str:
    payload = {
        "audit_event_ids": list(result.audit_event_ids),
        "operation_id": result.operation_id,
        "operation_kind": OperationKind.PREPARE_PLAN_FOR_APPROVAL.value,
        "outcome": "PLAN_PREPARED",
        "plan_ref": _ref_payload(result.plan_ref),
        "result_schema_version": result.result_schema_version,
        "status": result.status.value,
        "task_id": result.task_id,
        "task_revision": result.aggregate_revision,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _result_from_envelope(data: str, expected_task_id: str) -> PlanPreparationResult:
    try:
        payload = json.loads(data)
        expected = {
            "audit_event_ids", "operation_id", "operation_kind", "outcome", "plan_ref",
            "result_schema_version", "status", "task_id", "task_revision",
        }
        if not isinstance(payload, dict) or set(payload) != expected:
            raise ValueError
        if payload["operation_kind"] != OperationKind.PREPARE_PLAN_FOR_APPROVAL.value:
            raise ValueError
        if payload["outcome"] != "PLAN_PREPARED" or payload["task_id"] != expected_task_id:
            raise ValueError
        if type(payload["result_schema_version"]) is not int or payload["result_schema_version"] != 1:
            raise ValueError
        if type(payload["task_revision"]) is not int or payload["task_revision"] < 0:
            raise ValueError
        if payload["status"] != ChapterTaskStatus.PLAN_APPROVAL_PENDING.value:
            raise ValueError
        if type(payload["operation_id"]) is not str or not payload["operation_id"]:
            raise ValueError
        audit_ids = payload["audit_event_ids"]
        if not isinstance(audit_ids, list) or not audit_ids or any(
            type(item) is not str or not item for item in audit_ids
        ):
            raise ValueError
        ref = _ref_from_payload(payload["plan_ref"])
        return PlanPreparationResult(
            plan_ref=ref,
            task_id=payload["task_id"],
            aggregate_revision=payload["task_revision"],
            status=ChapterTaskStatus.PLAN_APPROVAL_PENDING,
            operation_id=payload["operation_id"],
            audit_event_ids=tuple(audit_ids),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CreationApplicationError("invalid stored PLAN preparation envelope") from exc


def _ref_payload(ref: ArtifactRef) -> dict[str, object]:
    return {
        "artifact_id": ref.artifact_id,
        "schema_version": ref.schema_version,
        "content_hash": ref.content_hash,
    }


def _ref_from_payload(value: object) -> ArtifactRef:
    if not isinstance(value, dict) or set(value) != {"artifact_id", "schema_version", "content_hash"}:
        raise ValueError
    if type(value["artifact_id"]) is not str or not value["artifact_id"]:
        raise ValueError
    if type(value["schema_version"]) is not int:
        raise ValueError
    return ArtifactRef(value["artifact_id"], value["schema_version"], value["content_hash"])


def _require_replay_envelope(outcome: OperationCreateOutcome) -> str:
    if outcome.replay_envelope_json is None:
        raise CreationApplicationError("REPLAY outcome did not include the original envelope")
    return outcome.replay_envelope_json


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _hash_text(data: str) -> str:
    return _sha256(data.encode("utf-8"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_text() -> str:
    return _now().isoformat(timespec="microseconds").replace("+00:00", "Z")


def _rollback(uow: CreationUnitOfWork, marker: list[bool]) -> None:
    if marker[0]:
        return
    marker[0] = True
    try:
        uow.rollback()
    except Exception as exc:
        raise CreationApplicationError("creation rollback failed") from exc


def _close_once(uow: CreationUnitOfWork, marker: list[bool]) -> None:
    if marker[0]:
        return
    marker[0] = True
    try:
        uow.close()
    except Exception as exc:
        raise CreationApplicationError("creation persistence close failed") from exc


# Descriptive aliases keep the boundary discoverable without adding another
# application module or a second command contract.
PlanPreparationCommand = PreparePlanForApprovalCommand
PreparePlanForApprovalContext = PlanPreparationDeliveryContext
PreparePlanForApprovalResult = PlanPreparationResult
