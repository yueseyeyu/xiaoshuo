"""Application use case for creating an append-only AuthorDecision (B2b).

This use case creates an immutable AuthorDecision fact using a controlled
local author identity.  It does NOT consume the decision or transition any
task — that is the responsibility of ``ConsumeAuthorDecisionUseCase``.

The caller supplies only business decision data and a
``DecisionCreationContext`` carrying the idempotency key.  The trusted
author identity is produced by the controlled ``LocalAuthorContext``
injected at construction time.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable
from uuid import UUID, uuid4

from xiaoshuo.domain.creation import (
    SCHEMA_VERSION,
    AuthorDecision,
    ChapterTaskStatus,
    DecisionType,
    compute_content_hash,
)
from xiaoshuo.domain.creation.hashing import canonicalize_json_value

from .commands import CreateAuthorDecisionCommand
from .decision_creation_context import DecisionCreationContext
from .digest import (
    compute_adopted_draft_payload_content_hash,
    compute_decision_creation_request_digest,
    compute_envelope_hash,
    create_decision_creation_result_envelope,
    result_from_decision_creation_envelope,
)
from .errors import (
    AdoptedDraftPayloadPersistenceFailed,
    AdoptedDraftPayloadRejected,
    CreationApplicationError,
    IdempotencyConflict,
    NotFound,
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
from .results import AuthorDecisionResult

IdFactory = Callable[[], UUID | str]
UnitOfWorkFactory = Callable[[], CreationUnitOfWork]

_ALLOWED_DECISION_TYPES: frozenset[DecisionType] = frozenset(
    {
        DecisionType.CONFIRM_PLAN,
        DecisionType.ADOPT_DRAFT,
        DecisionType.REJECT_DRAFT,
        DecisionType.REJECT_CHANGESET,
        DecisionType.APPROVE_CHANGESET,
    }
)

_EDGE_MAP: dict[DecisionType, tuple[ChapterTaskStatus, ChapterTaskStatus, str | None]] = {
    DecisionType.CONFIRM_PLAN: (
        ChapterTaskStatus.PLAN_APPROVAL_PENDING,
        ChapterTaskStatus.DRAFTING,
        "confirmed_plan_ref",
    ),
    DecisionType.ADOPT_DRAFT: (
        ChapterTaskStatus.DRAFT_APPROVAL_PENDING,
        ChapterTaskStatus.CHANGESET_PREPARING,
        "adopted_draft_ref",
    ),
    DecisionType.REJECT_DRAFT: (
        ChapterTaskStatus.DRAFT_APPROVAL_PENDING,
        ChapterTaskStatus.DRAFTING,
        None,
    ),
    DecisionType.REJECT_CHANGESET: (
        ChapterTaskStatus.CHANGESET_APPROVAL_PENDING,
        ChapterTaskStatus.CHANGESET_PREPARING,
        None,
    ),
    DecisionType.APPROVE_CHANGESET: (
        ChapterTaskStatus.CHANGESET_APPROVAL_PENDING,
        ChapterTaskStatus.COMMITTING,
        None,
    ),
}


class CreateAuthorDecisionUseCase:
    """Create an append-only AuthorDecision with operation ledger.

    The caller cannot supply author_id, SourceRef, decision_id,
    operation_id or timestamps — these are generated internally.
    """

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        author_context: LocalAuthorContext,
        *,
        id_factory: IdFactory = uuid4,
        payload_store: ImmutablePayloadStorePort | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._author_context = author_context
        self._id_factory = id_factory
        self._payload_store = payload_store

    def create(
        self,
        command: CreateAuthorDecisionCommand,
        context: DecisionCreationContext,
    ) -> AuthorDecisionResult:
        # ── Phase 1: Static allowlist guard (before UoW creation) ───
        _guard_adopted_draft_payload_shape(command)
        if command.decision_type not in _ALLOWED_DECISION_TYPES:
            raise UnsupportedPersistenceBoundary(
                f"decision type {command.decision_type.value!r} is not in the B2b MVP allowlist"
            )

        try:
            uow = self._uow_factory()
        except CreationApplicationError:
            raise
        except Exception as exc:
            raise CreationApplicationError(
                "creation persistence read failed"
            ) from exc

        rb_marker = [False]
        try:
            result = self._create_with_uow(command, context, uow, rb_marker)
        except Exception as original_exc:
            if rb_marker[0]:
                try:
                    uow.close()
                except Exception as close_exc:
                    if isinstance(original_exc, CreationApplicationError):
                        raise original_exc from close_exc
                    raise CreationApplicationError(
                        "creation persistence failed"
                    ) from close_exc
                raise
            try:
                uow.rollback()
            except Exception as rollback_exc:
                rollback_error = CreationApplicationError(
                    "creation rollback failed"
                )
                rollback_error.__cause__ = rollback_exc
                try:
                    uow.close()
                except Exception as close_exc:
                    raise rollback_error from close_exc
                raise rollback_error
            try:
                uow.close()
            except Exception as close_exc:
                raise original_exc from close_exc
            raise
        else:
            try:
                uow.close()
            except Exception as close_exc:
                raise CreationApplicationError(
                    "creation persistence close failed"
                ) from close_exc
            return result

    def _create_with_uow(
        self,
        command: CreateAuthorDecisionCommand,
        context: DecisionCreationContext,
        uow: CreationUnitOfWork,
        rb_marker: list[bool],
    ) -> AuthorDecisionResult:
        # ── Phase 2: Idempotent fast path (zero writes) ───────────
        kind = OperationKind.CREATE_AUTHOR_DECISION
        payload_content_hash = _payload_hash_for_command(command)
        request_digest = compute_decision_creation_request_digest(command, kind)

        try:
            existing = uow.operations.get_by_idempotency_key(
                context.idempotency_key
            )
        except CreationApplicationError:
            raise
        except Exception as exc:
            raise CreationApplicationError(
                "creation persistence read failed"
            ) from exc
        if existing is not None:
            if existing.request_digest != request_digest:
                raise IdempotencyConflict(
                    f"idempotency key {context.idempotency_key!r} "
                    f"has a different request digest"
                )
            _do_rollback(uow, rb_marker)
            return result_from_decision_creation_envelope(
                existing.result_envelope_json,
            )

        if command.decision_type is DecisionType.ADOPT_DRAFT:
            _validate_adopted_draft_payload(command, payload_content_hash)

        # ── Phase 3: Read real Task (zero writes) ─────────────────
        try:
            task = uow.tasks.get(command.task_id)
        except CreationApplicationError:
            raise
        except Exception as exc:
            raise CreationApplicationError(
                "creation persistence read failed"
            ) from exc
        if task is None:
            raise NotFound(
                f"task {command.task_id!r} not found"
            )

        # ── Phase 3b: Validate Task state for E1–E4 before identity generation ─
        edge = _EDGE_MAP.get(command.decision_type)
        if edge is None:
            raise UnsupportedPersistenceBoundary(
                f"decision type {command.decision_type.value!r} is not in the B2b MVP allowlist"
            )
        source_status, _target_status, ref_field = edge
        if task.status is not source_status:
            raise UnsupportedPersistenceBoundary(
                f"task status {task.status.value!r} does not match "
                f"expected source {source_status.value!r} for "
                f"decision type {command.decision_type.value!r}"
            )
        if command.based_on_task_revision != task.aggregate_revision:
            raise UnsupportedPersistenceBoundary(
                f"command based_on_task_revision {command.based_on_task_revision} "
                f"does not match current task revision {task.aggregate_revision}"
            )
        if command.decision_type is DecisionType.ADOPT_DRAFT:
            if task.current_author_draft_ref is None:
                raise UnsupportedPersistenceBoundary(
                    "ADOPT_DRAFT requires task.current_author_draft_ref to be set"
                )
            if task.review_target_draft_ref is None:
                raise UnsupportedPersistenceBoundary(
                    "ADOPT_DRAFT requires task.review_target_draft_ref to be set"
                )
            if task.latest_review_ref is None:
                raise UnsupportedPersistenceBoundary(
                    "ADOPT_DRAFT requires task.latest_review_ref to be set"
                )
            if task.current_author_draft_ref != task.review_target_draft_ref:
                raise UnsupportedPersistenceBoundary(
                    "ADOPT_DRAFT requires current_author_draft_ref to equal "
                    "review_target_draft_ref"
                )
            if command.target_ref != task.review_target_draft_ref:
                raise UnsupportedPersistenceBoundary(
                    "ADOPT_DRAFT target_ref must match task.review_target_draft_ref"
                )
        # For reject edges, verify target matches the real role ref
        if ref_field is None:
            if command.decision_type is DecisionType.REJECT_DRAFT:
                if task.review_target_draft_ref is None:
                    raise UnsupportedPersistenceBoundary(
                        "REJECT_DRAFT requires task.review_target_draft_ref to be set"
                    )
                if command.target_ref != task.review_target_draft_ref:
                    raise UnsupportedPersistenceBoundary(
                        "REJECT_DRAFT target_ref must match task.review_target_draft_ref"
                    )
            elif command.decision_type is DecisionType.REJECT_CHANGESET:
                if task.pending_changeset_ref is None:
                    raise UnsupportedPersistenceBoundary(
                        "REJECT_CHANGESET requires task.pending_changeset_ref to be set"
                    )
                if command.target_ref != task.pending_changeset_ref:
                    raise UnsupportedPersistenceBoundary(
                        "REJECT_CHANGESET target_ref must match task.pending_changeset_ref"
                    )
            elif command.decision_type is DecisionType.APPROVE_CHANGESET:
                if task.pending_changeset_ref is None:
                    raise UnsupportedPersistenceBoundary(
                        "APPROVE_CHANGESET requires task.pending_changeset_ref to be set"
                    )
                if command.target_ref != task.pending_changeset_ref:
                    raise UnsupportedPersistenceBoundary(
                        "APPROVE_CHANGESET target_ref must match task.pending_changeset_ref"
                    )

        # ── Phase 4: Construct candidate operation/decision identity ──
        decision_id = str(self._id_factory())
        operation_id = str(self._id_factory())
        now = datetime.now(timezone.utc)
        timestamp = now.isoformat(timespec="microseconds")

        author_source = self._author_context.author_source()
        author_id = self._author_context.author_id

        result = AuthorDecisionResult(
            decision_id=decision_id,
            task_id=command.task_id,
        )
        envelope_json = create_decision_creation_result_envelope(
            result,
            operation_kind=kind,
            original_operation_id=operation_id,
        )
        record = OperationLogRecord(
            operation_id=operation_id,
            idempotency_key=context.idempotency_key,
            request_digest=request_digest,
            result_envelope_json=envelope_json,
            result_envelope_hash=compute_envelope_hash(envelope_json),
            created_at=timestamp,
        )

        # ── Phase 5: NEW path writes ──────────────────────────────
        try:
            outcome = uow.operations.create_or_replay_complete(record)
        except CreationApplicationError:
            raise
        except Exception as exc:
            raise CreationApplicationError(
                "creation persistence failed"
            ) from exc

        outcome_status = getattr(outcome, "status", None)
        if outcome_status is OperationResult.REPLAY:
            _do_rollback(uow, rb_marker)
            return result_from_decision_creation_envelope(
                _require_replay_envelope(outcome),
            )
        if outcome_status is OperationResult.CONFLICT:
            raise IdempotencyConflict(
                f"idempotency key {context.idempotency_key!r} "
                f"has a different request digest"
            )
        if outcome_status is not OperationResult.NEW:
            raise CreationApplicationError("unsupported operation outcome")

        if command.decision_type is DecisionType.ADOPT_DRAFT:
            _persist_adopted_draft_payload(
                self._payload_store,
                command,
                payload_content_hash,
            )

        # ── Phase 6: Construct and persist AuthorDecision ─────────
        decision = AuthorDecision(
            decision_id=decision_id,
            schema_version=SCHEMA_VERSION,
            task_id=command.task_id,
            decision_type=command.decision_type,
            target_ref=command.target_ref,
            outcome=_outcome_for_type(command.decision_type),
            based_on_task_revision=command.based_on_task_revision,
            author_id=author_id,
            reason=command.reason,
            source=author_source,
            created_at=now,
            content_hash=compute_content_hash(
                canonicalize_json_value(decision_payload(
                    decision_id=decision_id,
                    schema_version=SCHEMA_VERSION,
                    task_id=command.task_id,
                    decision_type=command.decision_type,
                    target_ref=command.target_ref,
                    outcome=_outcome_for_type(command.decision_type),
                    based_on_task_revision=command.based_on_task_revision,
                    author_id=author_id,
                    reason=command.reason,
                    source=author_source,
                ))
            ),
        )

        try:
            uow.decisions.add(decision)
            uow.commit()
        except Exception as exc:
            if command.decision_type is DecisionType.ADOPT_DRAFT:
                raise AdoptedDraftPayloadPersistenceFailed(
                    "adopted draft decision persistence failed"
                ) from exc
            if isinstance(exc, CreationApplicationError):
                raise
            raise CreationApplicationError(
                "creation persistence failed"
            ) from exc

        return result


def _guard_adopted_draft_payload_shape(
    command: CreateAuthorDecisionCommand,
) -> None:
    payload = command.adopted_draft_payload
    if command.decision_type is DecisionType.ADOPT_DRAFT:
        if type(payload) is not bytes:
            raise AdoptedDraftPayloadRejected(
                "ADOPT_DRAFT adopted_draft_payload must be bytes"
            )
        return
    if payload is not None:
        raise AdoptedDraftPayloadRejected(
            "non-ADOPT decision cannot carry adopted_draft_payload"
        )


def _payload_hash_for_command(
    command: CreateAuthorDecisionCommand,
) -> str | None:
    if command.decision_type is not DecisionType.ADOPT_DRAFT:
        return None
    assert type(command.adopted_draft_payload) is bytes
    return compute_adopted_draft_payload_content_hash(
        command.adopted_draft_payload
    )


def _validate_adopted_draft_payload(
    command: CreateAuthorDecisionCommand,
    payload_content_hash: str | None,
) -> None:
    payload = command.adopted_draft_payload
    if type(payload) is not bytes or not payload:
        raise AdoptedDraftPayloadRejected(
            "ADOPT_DRAFT adopted_draft_payload must be non-empty bytes"
        )
    try:
        decoded = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise AdoptedDraftPayloadRejected(
            "ADOPT_DRAFT adopted_draft_payload must be strict UTF-8"
        ) from exc
    if "\x00" in decoded:
        raise AdoptedDraftPayloadRejected(
            "ADOPT_DRAFT adopted_draft_payload must not contain NUL"
        )
    if (
        payload_content_hash is None
        or payload_content_hash != command.target_ref.content_hash
    ):
        raise AdoptedDraftPayloadRejected(
            "ADOPT_DRAFT payload hash must match target_ref.content_hash"
        )


def _persist_adopted_draft_payload(
    payload_store: ImmutablePayloadStorePort | None,
    command: CreateAuthorDecisionCommand,
    payload_content_hash: str | None,
) -> None:
    if payload_store is None:
        raise AdoptedDraftPayloadPersistenceFailed(
            "ADOPT_DRAFT payload store is required"
        )
    payload = command.adopted_draft_payload
    assert type(payload) is bytes
    assert payload_content_hash is not None
    try:
        stored_digest = payload_store.put(payload)
        if stored_digest != payload_content_hash:
            raise AdoptedDraftPayloadPersistenceFailed(
                "adopted draft payload put returned a different digest"
            )
        readback = payload_store.read(stored_digest)
        if (
            type(readback) is not bytes
            or readback != payload
            or compute_adopted_draft_payload_content_hash(readback)
            != payload_content_hash
            or payload_content_hash != command.target_ref.content_hash
        ):
            raise AdoptedDraftPayloadPersistenceFailed(
                "adopted draft payload readback identity mismatch"
            )
    except AdoptedDraftPayloadPersistenceFailed:
        raise
    except Exception as exc:
        raise AdoptedDraftPayloadPersistenceFailed(
            "adopted draft payload persistence failed"
        ) from exc


def _outcome_for_type(decision_type: DecisionType):
    from xiaoshuo.domain.creation import DecisionOutcome
    _APPROVE = frozenset({
        DecisionType.CONFIRM_PLAN,
        DecisionType.ADOPT_DRAFT,
        DecisionType.APPROVE_CHANGESET,
    })
    if decision_type in _APPROVE:
        return DecisionOutcome.APPROVE
    return DecisionOutcome.REJECT


def decision_payload(
    *,
    decision_id: str,
    schema_version: int,
    task_id: str,
    decision_type,
    target_ref,
    outcome,
    based_on_task_revision: int,
    author_id: str,
    reason: str | None,
    source,
) -> dict[str, object]:
    """Build the canonical payload for content_hash computation.

    Must match AuthorDecision.content_payload().
    """
    return {
        "decision_id": decision_id,
        "schema_version": schema_version,
        "task_id": task_id,
        "decision_type": decision_type,
        "target_ref": target_ref,
        "outcome": outcome,
        "based_on_task_revision": based_on_task_revision,
        "author_id": author_id,
        "reason": reason,
        "source": source,
    }


def _do_rollback(uow: CreationUnitOfWork, rb_marker: list[bool]) -> None:
    rb_marker[0] = True
    try:
        uow.rollback()
    except Exception as exc:
        raise CreationApplicationError(
            "creation rollback failed"
        ) from exc


def _require_replay_envelope(outcome: OperationCreateOutcome) -> str:
    if outcome.replay_envelope_json is None:
        raise CreationApplicationError(
            "REPLAY outcome did not include the original envelope"
        )
    return outcome.replay_envelope_json
