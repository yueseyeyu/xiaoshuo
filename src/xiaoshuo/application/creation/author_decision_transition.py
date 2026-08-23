"""Application use case for consuming a persisted AuthorDecision (B2b).

This use case reads a real, immutable AuthorDecision and a real ChapterTask,
re-validates the decision, performs the allowed state transition, writes
the Task, operation ledger, AuditEvent, and decision-consumption association
in the same UoW, and returns the result.

Only four decision-gated edges (E1–E4) are allowed.  All other transitions
are fail-closed.  The caller cannot supply target status, outcome, target
ArtifactRef, or trusted author identity — these are derived from the real
persisted decision.
"""

from __future__ import annotations

from dataclasses import replace as dc_replace
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID, uuid4

from xiaoshuo.domain.creation import (
    SCHEMA_VERSION,
    ArtifactRef,
    AuditEvent,
    AuthorDecision,
    ChapterTask,
    ChapterTaskStatus,
    DecisionType,
    SourceRef,
)
from xiaoshuo.domain.creation.state_machine import (
    RevisionConflict as DomainRevisionConflict,
)
from xiaoshuo.domain.creation.state_machine import (
    transition_task,
    validate_author_decision,
)

from .commands import ConsumeAuthorDecisionCommand
from .digest import (
    compute_decision_consumption_request_digest,
    compute_envelope_hash,
    create_decision_consumption_result_envelope,
    result_from_decision_consumption_envelope,
)
from .errors import (
    CreationApplicationError,
    IdempotencyConflict,
    NotFound,
    UnsupportedPersistenceBoundary,
)
from .local_author_context import LocalAuthorContext
from .operation_kind import OperationKind
from .repository import (
    CreationUnitOfWork,
    DecisionConsumptionRecord,
    OperationCreateOutcome,
    OperationLogRecord,
    OperationResult,
)
from .results import TransitionChapterTaskResult
from .transition_context import TransitionOperationContext

IdFactory = Callable[[], UUID | str]
UnitOfWorkFactory = Callable[[], CreationUnitOfWork]

# E1–E4 edge map: DecisionType → (source_status, target_status, ref_to_write)
# ref_to_write is the ChapterTask field name to set to decision.target_ref,
# or None for E3/E4 (no ref changes).
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
}


class ConsumeAuthorDecisionUseCase:
    """Consume a persisted AuthorDecision and transition a ChapterTask.

    The caller supplies task_id, the persisted decision_id, the expected
    task revision, and a TransitionOperationContext carrying the
    idempotency key.  Target status, outcome and target ArtifactRef are
    derived from the real persisted decision.
    """

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        author_context: LocalAuthorContext,
        *,
        id_factory: IdFactory = uuid4,
    ) -> None:
        self._uow_factory = uow_factory
        self._author_context = author_context
        self._id_factory = id_factory

    def consume(
        self,
        command: ConsumeAuthorDecisionCommand,
        context: TransitionOperationContext,
    ) -> TransitionChapterTaskResult:
        # ── Phase 1: Static guard (before UoW creation) ───────────
        # Verify command does not carry caller-supplied identity.
        # (The command only has task_id, decision_id, expected_revision —
        # there are no identity fields to check, but we verify decision_id
        # is non-empty as a structural check.)
        if not command.decision_id or not command.decision_id.strip():
            raise UnsupportedPersistenceBoundary(
                "decision_id must be a non-empty string"
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
            result = self._consume_with_uow(command, context, uow, rb_marker)
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

    def _consume_with_uow(
        self,
        command: ConsumeAuthorDecisionCommand,
        context: TransitionOperationContext,
        uow: CreationUnitOfWork,
        rb_marker: list[bool],
    ) -> TransitionChapterTaskResult:
        # ── Phase 2: Idempotent fast path (zero writes) ───────────
        kind = OperationKind.CONSUME_AUTHOR_DECISION
        request_digest = compute_decision_consumption_request_digest(command, kind)

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
            return result_from_decision_consumption_envelope(
                existing.result_envelope_json,
                expected_task_id=command.task_id,
            )

        # ── Phase 3: Read real Task and real AuthorDecision ──────
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

        try:
            decision = uow.decisions.get(command.decision_id)
        except CreationApplicationError:
            raise
        except Exception as exc:
            raise CreationApplicationError(
                "creation persistence read failed"
            ) from exc
        if decision is None:
            raise NotFound(
                f"decision {command.decision_id!r} not found"
            )

        # ── Phase 3b: Verify decision identity against controlled local author ─
        local_source = self._author_context.author_source()
        local_author_id = self._author_context.author_id
        if decision.author_id != local_author_id:
            raise UnsupportedPersistenceBoundary(
                f"decision author_id {decision.author_id!r} does not match "
                f"controlled local author {local_author_id!r}"
            )
        if decision.source != local_source:
            raise UnsupportedPersistenceBoundary(
                "decision source does not match controlled local author source"
            )

        # Check if decision was already consumed
        try:
            existing_consumption = uow.decisions.get_consumption_by_decision_id(
                command.decision_id
            )
        except CreationApplicationError:
            raise
        except Exception as exc:
            raise CreationApplicationError(
                "creation persistence read failed"
            ) from exc
        if existing_consumption is not None:
            raise UnsupportedPersistenceBoundary(
                f"decision {command.decision_id!r} has already been consumed"
            )

        # ── Phase 4: Re-validate decision (zero writes) ──────────
        edge = _EDGE_MAP.get(decision.decision_type)
        if edge is None:
            raise UnsupportedPersistenceBoundary(
                f"decision type {decision.decision_type.value!r} is not in the B2b MVP allowlist"
            )

        source_status, target_status, ref_field = edge

        if task.status is not source_status:
            raise UnsupportedPersistenceBoundary(
                f"task status {task.status.value!r} does not match "
                f"expected source {source_status.value!r} for "
                f"decision type {decision.decision_type.value!r}"
            )

        if decision.decision_type is DecisionType.ADOPT_DRAFT:
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
            if decision.target_ref != task.review_target_draft_ref:
                raise UnsupportedPersistenceBoundary(
                    "ADOPT_DRAFT target_ref must match task.review_target_draft_ref"
                )

        # Determine expected_target_ref for validate_author_decision
        if ref_field is not None:
            # E1/E2: the decision.target_ref is the artifact to write
            expected_target_ref = decision.target_ref
        elif decision.decision_type is DecisionType.REJECT_DRAFT:
            # E3: decision.target_ref must match existing review_target_draft_ref
            expected_target_ref = task.review_target_draft_ref
        elif decision.decision_type is DecisionType.REJECT_CHANGESET:
            # E4: decision.target_ref must match existing pending_changeset_ref
            expected_target_ref = task.pending_changeset_ref
        else:
            expected_target_ref = None

        if expected_target_ref is None:
            raise UnsupportedPersistenceBoundary(
                f"expected target ref for {decision.decision_type.value!r} is None"
            )

        # Validate the decision using the domain validator
        try:
            validate_author_decision(
                decision,
                expected_type=decision.decision_type,
                expected_target_ref=expected_target_ref,
                current_task_revision=task.aggregate_revision,
            )
        except CreationApplicationError:
            raise
        except Exception as exc:
            raise UnsupportedPersistenceBoundary(
                f"decision validation failed: {exc}"
            ) from exc

        # ── Phase 5: Domain transition (zero writes) ─────────────
        try:
            transitioned_task = transition_task(
                task,
                target_status,
                command.expected_revision,
            )
        except DomainRevisionConflict:
            raise
        except Exception as exc:
            raise CreationApplicationError(
                "creation persistence failed"
            ) from exc

        # Apply role ArtifactRef write for E1/E2
        if ref_field is not None:
            transitioned_task = dc_replace(
                transitioned_task,
                **{ref_field: decision.target_ref},
            )

        # ── Phase 6: NEW path writes ──────────────────────────────
        operation_id = str(self._id_factory())
        event_id = str(self._id_factory())
        consumption_id = str(self._id_factory())
        now = datetime.now(timezone.utc)
        timestamp = now.isoformat(timespec="microseconds")

        result = TransitionChapterTaskResult(
            task_id=transitioned_task.task_id,
            aggregate_revision=transitioned_task.aggregate_revision,
            status=transitioned_task.status,
        )
        envelope_json = create_decision_consumption_result_envelope(
            result,
            operation_kind=kind,
            original_operation_id=operation_id,
            audit_event_ids=(event_id,),
        )
        record = OperationLogRecord(
            operation_id=operation_id,
            idempotency_key=context.idempotency_key,
            request_digest=request_digest,
            result_envelope_json=envelope_json,
            result_envelope_hash=compute_envelope_hash(envelope_json),
            created_at=timestamp,
        )
        audit_event = AuditEvent(
            event_id=event_id,
            schema_version=SCHEMA_VERSION,
            task_id=transitioned_task.task_id,
            project_id=transitioned_task.project_id,
            event_type="TASK_TRANSITIONED",
            actor=local_source,
            before_task_revision=task.aggregate_revision,
            after_task_revision=transitioned_task.aggregate_revision,
            object_refs=_collect_object_refs(transitioned_task),
            operation_id=operation_id,
            created_at=now,
        )
        consumption_record = DecisionConsumptionRecord(
            consumption_id=consumption_id,
            decision_id=command.decision_id,
            operation_id=operation_id,
            task_id=transitioned_task.task_id,
            consumed_at_task_revision=transitioned_task.aggregate_revision,
            consumed_at=timestamp,
        )

        try:
            outcome = uow.operations.create_or_replay_complete(record)
        except CreationApplicationError:
            raise
        except Exception as exc:
            raise CreationApplicationError(
                "creation persistence failed"
            ) from exc

        if outcome.status is OperationResult.REPLAY:
            _do_rollback(uow, rb_marker)
            return result_from_decision_consumption_envelope(
                _require_replay_envelope(outcome),
                expected_task_id=command.task_id,
            )
        if outcome.status is OperationResult.CONFLICT:
            raise IdempotencyConflict(
                f"idempotency key {context.idempotency_key!r} "
                f"has a different request digest"
            )

        try:
            uow.tasks.replace(
                transitioned_task,
                expected_revision=command.expected_revision,
            )
            uow.audit.add_event(audit_event)
            uow.decisions.add_consumption(consumption_record)
            uow.commit()
        except CreationApplicationError:
            raise
        except Exception as exc:
            raise CreationApplicationError(
                "creation persistence failed"
            ) from exc

        return result


def _do_rollback(uow: CreationUnitOfWork, rb_marker: list[bool]) -> None:
    rb_marker[0] = True
    try:
        uow.rollback()
    except Exception as exc:
        raise CreationApplicationError(
            "creation rollback failed"
        ) from exc


def _collect_object_refs(task: ChapterTask) -> tuple[ArtifactRef, ...]:
    """Collect all non-null role ArtifactRefs in fixed 7-role order."""
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


def _require_replay_envelope(outcome: OperationCreateOutcome) -> str:
    if outcome.replay_envelope_json is None:
        raise CreationApplicationError(
            "REPLAY outcome did not include the original envelope"
        )
    return outcome.replay_envelope_json
