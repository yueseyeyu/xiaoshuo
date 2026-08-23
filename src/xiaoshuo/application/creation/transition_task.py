"""Application use case for idempotently transitioning a ChapterTask (B2a).

Implements the B2a safe-migration subset: only
``REVISION_REQUIRED -> DRAFTING`` and
``RECOVERY_REQUIRED -> task.recovery.retry_from_status`` are allowed.
All other transitions are fail-closed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable
from uuid import UUID, uuid4

from xiaoshuo.domain.creation import (
    SCHEMA_VERSION,
    ArtifactRef,
    AuditEvent,
    ChapterTask,
    ChapterTaskStatus,
    SourceKind,
    SourceRef,
)
from xiaoshuo.domain.creation.state_machine import (
    RevisionConflict as DomainRevisionConflict,
)
from xiaoshuo.domain.creation.state_machine import transition_task

from .commands import TransitionChapterTaskCommand
from .digest import (
    compute_envelope_hash,
    compute_transition_request_digest,
    create_transition_result_envelope,
    result_from_transition_envelope,
)
from .errors import (
    CreationApplicationError,
    IdempotencyConflict,
    NotFound,
    UnsupportedPersistenceBoundary,
)
from .guards import guard_persistence_target
from .guards import guard_recovery_retry_boundary
from .operation_kind import OperationKind
from .repository import (
    CreationUnitOfWork,
    OperationCreateOutcome,
    OperationLogRecord,
    OperationResult,
)
from .results import TransitionChapterTaskResult
from .transition_context import TransitionOperationContext
from .transition_guards import guard_b2a_allowed_transition

IdFactory = Callable[[], UUID | str]
UnitOfWorkFactory = Callable[[], CreationUnitOfWork]


class TransitionChapterTaskUseCase:
    """Transition an existing ChapterTask with operation and audit facts.

    B2a allows only:
    - ``REVISION_REQUIRED -> DRAFTING``
    - ``RECOVERY_REQUIRED -> task.recovery.retry_from_status``

    The ``TransitionOperationContext`` carries the idempotency key
    independently from the business command.
    """

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        id_factory: IdFactory = uuid4,
    ) -> None:
        self._uow_factory = uow_factory
        self._id_factory = id_factory

    def transition(
        self,
        command: TransitionChapterTaskCommand,
        context: TransitionOperationContext,
    ) -> TransitionChapterTaskResult:
        # ── Static target boundary guard (before UoW creation) ───
        # Illegal COMMITTING/COMPLETED requests must not create a UoW.
        guard_persistence_target(command.target_status)

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
            result = self._transition_with_uow(command, context, uow, rb_marker)
        except Exception as original_exc:
            if rb_marker[0]:
                # Rollback was already attempted inside (REPLAY paths).
                # Do not roll back again; just close.
                try:
                    uow.close()
                except Exception as close_exc:
                    if isinstance(original_exc, CreationApplicationError):
                        raise original_exc from close_exc
                    raise CreationApplicationError(
                        "creation persistence failed"
                    ) from close_exc
                raise
            # Centralized rollback: every exception path rolls back
            # exactly once, then closes. Rollback failure is reported
            # as a stable CreationApplicationError with the rollback
            # exception as __cause__. Close failure follows B1
            # Close-Error Repair: the original exception is preserved
            # and the close exception becomes its __cause__.
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
            # Success path: commit already done inside
            # _transition_with_uow (or fast/competing REPLAY already
            # rolled back via rb_marker). Only close remains.
            try:
                uow.close()
            except Exception as close_exc:
                raise CreationApplicationError(
                    "creation persistence close failed"
                ) from close_exc
            return result

    def _transition_with_uow(
        self,
        command: TransitionChapterTaskCommand,
        context: TransitionOperationContext,
        uow: CreationUnitOfWork,
        rb_marker: list[bool],
    ) -> TransitionChapterTaskResult:
        # ── Phase 1: Idempotent fast path (zero writes) ───────────
        kind = OperationKind.TRANSITION_CHAPTER_TASK
        request_digest = compute_transition_request_digest(command, kind)

        # Context-key idempotent fast path (zero writes)
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
            # Fast REPLAY: rollback the UoW (no writes to persist),
            # then return the original stored envelope. This is a
            # success-return path — the outer transition() will only
            # close the UoW. rb_marker signals that rollback was
            # attempted so the outer handler won't roll back again.
            _do_rollback(uow, rb_marker)
            return result_from_transition_envelope(
                existing.result_envelope_json,
                expected_task_id=command.task_id,
            )

        # ── Phase 2: Read real Task (zero writes) ─────────────────
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

        # Recovery validation: use task.recovery, not command.recovery
        if task.status is ChapterTaskStatus.RECOVERY_REQUIRED:
            if task.recovery is None:
                raise UnsupportedPersistenceBoundary(
                    "RECOVERY_REQUIRED task has no recovery info"
                )
            if command.recovery is not None:
                raise UnsupportedPersistenceBoundary(
                    "command.recovery must be None for recovery transition"
                )
            guard_recovery_retry_boundary(task.recovery)
        else:
            if command.recovery is not None:
                raise UnsupportedPersistenceBoundary(
                    "command.recovery must be None for non-recovery transition"
                )

        # ── Phase 3: B2a allowlist guard (zero writes) ────────────
        guard_b2a_allowed_transition(
            task.status,
            command.target_status,
            task.recovery,
        )

        # ── Phase 4: Domain transition (zero writes) ──────────────
        try:
            transitioned_task = transition_task(
                task,
                command.target_status,
                command.expected_revision,
            )
        except DomainRevisionConflict:
            raise
        except Exception as exc:
            raise CreationApplicationError(
                "creation persistence failed"
            ) from exc

        # ── Phase 5: NEW path writes ──────────────────────────────
        operation_id = str(self._id_factory())
        event_id = str(self._id_factory())
        now = datetime.now(timezone.utc)
        timestamp = now.isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        )

        result = TransitionChapterTaskResult(
            task_id=transitioned_task.task_id,
            aggregate_revision=transitioned_task.aggregate_revision,
            status=transitioned_task.status,
        )
        envelope_json = create_transition_result_envelope(
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
            actor=SourceRef(kind=SourceKind.SYSTEM),
            before_task_revision=task.aggregate_revision,
            after_task_revision=transitioned_task.aggregate_revision,
            object_refs=_collect_object_refs(transitioned_task),
            operation_id=operation_id,
            created_at=now,
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
            return result_from_transition_envelope(
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
            uow.commit()
        except CreationApplicationError:
            raise
        except Exception as exc:
            raise CreationApplicationError(
                "creation persistence failed"
            ) from exc

        return result


def _do_rollback(uow: CreationUnitOfWork, rb_marker: list[bool]) -> None:
    """Rollback the UoW and mark it as done so the outer handler
    won't roll back again. If rollback fails, raise a stable
    CreationApplicationError preserving the cause chain.
    """
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
