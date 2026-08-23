"""G0-B two-phase DRAFT and REVIEW application use cases.

The module is deliberately application-only.  Payload bytes are kept behind
``ImmutablePayloadStorePort`` and all SQLite facts are written through the
existing CreationUnitOfWork protocols.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from xiaoshuo.domain.creation import (
    SCHEMA_VERSION,
    ArtifactRef,
    AuditEvent,
    ChapterTaskStatus,
    SourceKind,
    SourceRef,
    transition_task,
)

from .authoring_artifact import (
    AuthoringArtifactEnvelope,
    AuthoringArtifactKind,
    AuthoringArtifactSubmissionResult,
    authoring_artifact_content_hash,
    parse_authoring_artifact_envelope,
)
from .authoring_artifact_context import (
    AuthoringArtifactSubmissionContext,
    DraftReviewSubmissionContext,
)
from .commands import SubmitAuthoringArtifactCommand, SubmitDraftForReviewCommand
from .digest import (
    compute_authoring_submission_request_digest,
    compute_envelope_hash,
    create_authoring_submission_result_envelope,
    result_from_authoring_submission_envelope,
)
from .errors import (
    AuthoringArtifactBindingRejected,
    AuthoringArtifactInputRejected,
    AuthoringArtifactPayloadPersistenceFailed,
    CreationApplicationError,
    IdempotencyConflict,
    NotFound,
)
from .local_author_context import LocalAuthorContext
from .operation_kind import OperationKind
from .ports import ImmutablePayloadStorePort
from .repository import (
    CreationUnitOfWork,
    OperationLogRecord,
    OperationResult,
)

IdFactory = Callable[[], object]
UnitOfWorkFactory = Callable[[], CreationUnitOfWork]


class SubmitAuthoringArtifactUseCase:
    """Persist a trusted DRAFT and move ``DRAFTING`` to ``REVIEWING``."""

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

    def submit(
        self,
        command: SubmitAuthoringArtifactCommand,
        context: AuthoringArtifactSubmissionContext,
    ) -> AuthoringArtifactSubmissionResult:
        if not isinstance(command, SubmitAuthoringArtifactCommand) or not isinstance(
            context, AuthoringArtifactSubmissionContext
        ):
            raise AuthoringArtifactInputRejected(
                "DRAFT use case requires the DRAFT command and context"
            )
        return _submit(
            uow_factory=self._uow_factory,
            author_context=self._author_context,
            payload_store=self._payload_store,
            id_factory=self._id_factory,
            command=command,
            idempotency_key=context.idempotency_key,
            operation_kind=OperationKind.SUBMIT_AUTHORING_ARTIFACT,
        )


class SubmitDraftForReviewUseCase:
    """Persist a trusted REVIEW bound to the Task's durable DRAFT ref."""

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

    def submit(
        self,
        command: SubmitDraftForReviewCommand,
        context: DraftReviewSubmissionContext,
    ) -> AuthoringArtifactSubmissionResult:
        if not isinstance(command, SubmitDraftForReviewCommand) or not isinstance(
            context, DraftReviewSubmissionContext
        ):
            raise AuthoringArtifactInputRejected(
                "REVIEW use case requires the REVIEW command and context"
            )
        return _submit(
            uow_factory=self._uow_factory,
            author_context=self._author_context,
            payload_store=self._payload_store,
            id_factory=self._id_factory,
            command=command,
            idempotency_key=context.idempotency_key,
            operation_kind=OperationKind.SUBMIT_DRAFT_FOR_REVIEW,
        )


def _submit(
    *,
    uow_factory: UnitOfWorkFactory,
    author_context: LocalAuthorContext,
    payload_store: ImmutablePayloadStorePort,
    id_factory: IdFactory,
    command: SubmitAuthoringArtifactCommand | SubmitDraftForReviewCommand,
    idempotency_key: str,
    operation_kind: OperationKind,
) -> AuthoringArtifactSubmissionResult:
    _guard_command(command)
    envelope_hash = authoring_artifact_content_hash(command.envelope_bytes)
    request_digest = compute_authoring_submission_request_digest(
        command, envelope_hash, operation_kind
    )

    try:
        uow = uow_factory()
    except CreationApplicationError:
        raise
    except Exception as exc:
        raise CreationApplicationError("creation persistence read failed") from exc

    rollback_done = [False]
    commit_succeeded = [False]
    close_attempted = [False]
    try:
        existing = uow.operations.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            if existing.request_digest != request_digest:
                raise IdempotencyConflict(
                    f"idempotency key {idempotency_key!r} has a different request digest"
                )
            _rollback(uow, rollback_done)
            replay = result_from_authoring_submission_envelope(
                existing.result_envelope_json,
                expected_task_id=command.task_id,
                expected_kind=operation_kind,
            )
            _close_once(uow, close_attempted)
            return replay

        # Parsing is local validation only.  No Task, payload, or business
        # fact is read before the operation ledger declares NEW.
        envelope = parse_authoring_artifact_envelope(command.envelope_bytes)
        _guard_envelope_kind(envelope, operation_kind)

        # These are candidate values.  A REPLAY/CONFLICT race discards them
        # before payload I/O or any business fact is touched.
        operation_id = str(id_factory())
        artifact_ref = ArtifactRef(
            artifact_id=str(id_factory()),
            schema_version=1,
            content_hash=envelope_hash,
        )
        audit_event_id = str(id_factory())
        expected_status = _target_status(operation_kind)
        anticipated_result = AuthoringArtifactSubmissionResult(
            artifact_kind=envelope.artifact_kind,
            artifact_ref=artifact_ref,
            task_id=command.task_id,
            aggregate_revision=command.expected_revision + 1,
            status=expected_status,
            operation_id=operation_id,
            audit_event_ids=(audit_event_id,),
        )
        result_envelope = create_authoring_submission_result_envelope(
            anticipated_result, operation_kind=operation_kind
        )
        record = OperationLogRecord(
            operation_id=operation_id,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            result_envelope_json=result_envelope,
            result_envelope_hash=compute_envelope_hash(result_envelope),
            created_at=_now().isoformat(timespec="microseconds"),
        )

        outcome = uow.operations.create_or_replay_complete(record)
        if outcome.status is OperationResult.REPLAY:
            _rollback(uow, rollback_done)
            if outcome.replay_envelope_json is None:
                raise CreationApplicationError(
                    "REPLAY outcome did not include the original envelope"
                )
            replay = result_from_authoring_submission_envelope(
                outcome.replay_envelope_json,
                expected_task_id=command.task_id,
                expected_kind=operation_kind,
            )
            _close_once(uow, close_attempted)
            return replay
        if outcome.status is OperationResult.CONFLICT:
            raise IdempotencyConflict(
                f"idempotency key {idempotency_key!r} has a different request digest"
            )
        if outcome.status is not OperationResult.NEW:
            raise CreationApplicationError("unsupported operation outcome")

        task = uow.tasks.get(command.task_id)
        if task is None:
            raise NotFound(f"task {command.task_id!r} not found")
        _validate_task_binding(task, envelope, command, operation_kind)

        if operation_kind is OperationKind.SUBMIT_DRAFT_FOR_REVIEW:
            assert envelope.reviewed_draft_ref is not None
            _verify_trusted_draft_payload(
                payload_store, task, envelope.reviewed_draft_ref
            )

        _persist_payload(payload_store, command.envelope_bytes, envelope_hash)
        transitioned = transition_task(
            task,
            expected_status,
            expected_revision=command.expected_revision,
        )
        if operation_kind is OperationKind.SUBMIT_AUTHORING_ARTIFACT:
            transitioned = _replace_task_ref(
                transitioned,
                current_author_draft_ref=artifact_ref,
                review_target_draft_ref=artifact_ref,
            )
        else:
            transitioned = _replace_task_ref(transitioned, latest_review_ref=artifact_ref)

        audit = AuditEvent(
            event_id=audit_event_id,
            schema_version=SCHEMA_VERSION,
            task_id=transitioned.task_id,
            project_id=transitioned.project_id,
            event_type=(
                "AUTHORING_DRAFT_SUBMITTED"
                if operation_kind is OperationKind.SUBMIT_AUTHORING_ARTIFACT
                else "DRAFT_REVIEW_SUBMITTED"
            ),
            actor=author_context.author_source(),
            before_task_revision=task.aggregate_revision,
            after_task_revision=transitioned.aggregate_revision,
            object_refs=_collect_object_refs(transitioned),
            operation_id=operation_id,
            created_at=_now(),
        )

        try:
            uow.tasks.replace(transitioned, expected_revision=command.expected_revision)
            uow.audit.add_event(audit)
            uow.commit()
        except AuthoringArtifactPayloadPersistenceFailed:
            raise
        except Exception as exc:
            raise AuthoringArtifactPayloadPersistenceFailed(
                "authoring operation persistence failed after payload write"
            ) from exc
        commit_succeeded[0] = True
        _close_once(uow, close_attempted)
        return anticipated_result
    except Exception as original_exc:
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
    command: SubmitAuthoringArtifactCommand | SubmitDraftForReviewCommand,
) -> None:
    if not isinstance(command, (SubmitAuthoringArtifactCommand, SubmitDraftForReviewCommand)):
        raise AuthoringArtifactInputRejected("unsupported G0-B command")
    if command.command_schema_version != 1:
        raise AuthoringArtifactInputRejected("unsupported G0-B command schema")
    if type(command.envelope_bytes) is not bytes:
        raise AuthoringArtifactInputRejected("authoring envelope must be bytes")
    if not isinstance(command.task_id, str) or not command.task_id.strip():
        raise AuthoringArtifactInputRejected("task_id must be non-empty")
    if type(command.expected_revision) is not int or command.expected_revision < 0:
        raise AuthoringArtifactInputRejected("expected_revision must be non-negative")


def _guard_envelope_kind(
    envelope: AuthoringArtifactEnvelope, operation_kind: OperationKind
) -> None:
    expected = (
        AuthoringArtifactKind.DRAFT
        if operation_kind is OperationKind.SUBMIT_AUTHORING_ARTIFACT
        else AuthoringArtifactKind.REVIEW
    )
    if envelope.artifact_kind is not expected:
        raise AuthoringArtifactInputRejected(
            f"{operation_kind.value} requires {expected.value} envelope"
        )


def _target_status(operation_kind: OperationKind) -> ChapterTaskStatus:
    if operation_kind is OperationKind.SUBMIT_AUTHORING_ARTIFACT:
        return ChapterTaskStatus.REVIEWING
    return ChapterTaskStatus.DRAFT_APPROVAL_PENDING


def _validate_task_binding(
    task,
    envelope: AuthoringArtifactEnvelope,
    command: SubmitAuthoringArtifactCommand | SubmitDraftForReviewCommand,
    operation_kind: OperationKind,
) -> None:
    if task.status is not _source_status(operation_kind):
        raise AuthoringArtifactBindingRejected(
            f"task status {task.status.value!r} is not valid for {operation_kind.value}"
        )
    if task.aggregate_revision != command.expected_revision:
        raise AuthoringArtifactBindingRejected("task revision does not match command")
    if (
        envelope.project_id != task.project_id
        or envelope.task_id != task.task_id
        or envelope.chapter_number != task.chapter_number
    ):
        raise AuthoringArtifactBindingRejected("authoring envelope Task identity mismatch")
    if (
        operation_kind is OperationKind.SUBMIT_AUTHORING_ARTIFACT
        and task.confirmed_plan_ref is None
    ):
        raise AuthoringArtifactBindingRejected(
            "DRAFT submission requires a trusted confirmed plan ref"
        )
    if operation_kind is OperationKind.SUBMIT_DRAFT_FOR_REVIEW:
        if (
            task.current_author_draft_ref is None
            or task.review_target_draft_ref is None
            or envelope.reviewed_draft_ref is None
        ):
            raise AuthoringArtifactBindingRejected("trusted DRAFT ref is required")
        if (
            task.current_author_draft_ref != task.review_target_draft_ref
            or envelope.reviewed_draft_ref != task.current_author_draft_ref
        ):
            raise AuthoringArtifactBindingRejected(
                "REVIEW ref does not match the trusted Task DRAFT ref"
            )


def _source_status(operation_kind: OperationKind) -> ChapterTaskStatus:
    if operation_kind is OperationKind.SUBMIT_AUTHORING_ARTIFACT:
        return ChapterTaskStatus.DRAFTING
    return ChapterTaskStatus.REVIEWING


def _verify_trusted_draft_payload(
    payload_store: ImmutablePayloadStorePort,
    task,
    expected_ref: ArtifactRef,
) -> None:
    try:
        payload = payload_store.read(expected_ref.content_hash)
    except Exception as exc:
        raise AuthoringArtifactPayloadPersistenceFailed(
            "trusted DRAFT payload read failed"
        ) from exc
    if type(payload) is not bytes:
        raise AuthoringArtifactPayloadPersistenceFailed(
            "trusted DRAFT payload readback is not bytes"
        )
    if authoring_artifact_content_hash(payload) != expected_ref.content_hash:
        raise AuthoringArtifactBindingRejected("trusted DRAFT payload hash mismatch")
    try:
        draft = parse_authoring_artifact_envelope(payload)
    except AuthoringArtifactInputRejected as exc:
        raise AuthoringArtifactBindingRejected(
            "trusted DRAFT payload is not a valid canonical envelope"
        ) from exc
    if (
        draft.artifact_kind is not AuthoringArtifactKind.DRAFT
        or draft.project_id != task.project_id
        or draft.task_id != task.task_id
        or draft.chapter_number != task.chapter_number
    ):
        raise AuthoringArtifactBindingRejected("trusted DRAFT payload identity mismatch")


def _persist_payload(
    payload_store: ImmutablePayloadStorePort, payload: bytes, expected_hash: str
) -> None:
    try:
        stored = payload_store.put(payload)
        if stored != expected_hash:
            raise AuthoringArtifactPayloadPersistenceFailed(
                "authoring payload put returned a different digest"
            )
        readback = payload_store.read(stored)
    except AuthoringArtifactPayloadPersistenceFailed:
        raise
    except Exception as exc:
        raise AuthoringArtifactPayloadPersistenceFailed(
            "authoring payload persistence failed"
        ) from exc
    if (
        type(readback) is not bytes
        or readback != payload
        or authoring_artifact_content_hash(readback) != expected_hash
    ):
        raise AuthoringArtifactPayloadPersistenceFailed(
            "authoring payload readback identity mismatch"
        )


def _replace_task_ref(task, **changes):
    from dataclasses import replace

    return replace(task, **changes)


def _collect_object_refs(task) -> tuple[ArtifactRef, ...]:
    refs: list[ArtifactRef] = [task.creative_intent_ref]
    for ref in (
        task.confirmed_plan_ref,
        task.current_author_draft_ref,
        task.review_target_draft_ref,
        task.adopted_draft_ref,
        task.latest_review_ref,
        task.pending_changeset_ref,
    ):
        if ref is not None:
            refs.append(ref)
    return tuple(refs)


def _rollback(uow: CreationUnitOfWork, marker: list[bool]) -> None:
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


def _now() -> datetime:
    return datetime.now(timezone.utc)


# Descriptive aliases keep the application boundary discoverable without
# introducing another implementation or dependency direction.
CreateAuthoringArtifactUseCase = SubmitAuthoringArtifactUseCase
DraftReviewSubmissionUseCase = SubmitDraftForReviewUseCase
