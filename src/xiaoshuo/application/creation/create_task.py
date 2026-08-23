"""Application use case for idempotently creating a ChapterTask."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable
from uuid import UUID, uuid4

from xiaoshuo.domain.creation import (
    SCHEMA_VERSION,
    AuditEvent,
    ChapterTask,
    ChapterTaskStatus,
    SourceKind,
    SourceRef,
)

from .commands import CreateChapterTaskCommand
from .digest import (
    compute_envelope_hash,
    compute_request_digest,
    create_result_envelope,
    result_from_envelope,
)
from .errors import (
    CreationApplicationError,
    IdempotencyConflict,
    OperationIdConflict,
    UnsupportedPersistenceBoundary,
)
from .operation_kind import OperationKind
from .repository import (
    CreationUnitOfWork,
    OperationCreateOutcome,
    OperationLogRecord,
    OperationResult,
)
from .results import CreateChapterTaskResult

IdFactory = Callable[[], UUID | str]
UnitOfWorkFactory = Callable[[], CreationUnitOfWork]


class CreateChapterTaskUseCase:
    """Create a PLAN_PREPARING task with operation and audit facts atomically."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        id_factory: IdFactory = uuid4,
    ) -> None:
        self._uow_factory = uow_factory
        self._id_factory = id_factory

    def create(self, command: CreateChapterTaskCommand) -> CreateChapterTaskResult:
        if command.initial_status is not ChapterTaskStatus.PLAN_PREPARING:
            raise UnsupportedPersistenceBoundary(
                "CreateChapterTask only supports PLAN_PREPARING"
            )
        try:
            uow = self._uow_factory()
        except CreationApplicationError:
            raise
        except Exception as exc:
            raise CreationApplicationError("creation persistence read failed") from exc
        try:
            result = self._create_with_uow(command, uow)
        except Exception as original_exc:
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
        command: CreateChapterTaskCommand,
        uow: CreationUnitOfWork,
    ) -> CreateChapterTaskResult:
        kind = OperationKind.CREATE_CHAPTER_TASK
        request_digest = compute_request_digest(command, kind)
        try:
            existing = uow.operations.get_by_idempotency_key(command.task_id)
        except CreationApplicationError:
            raise
        except Exception as exc:
            raise CreationApplicationError("creation persistence read failed") from exc
        if existing is not None:
            if existing.request_digest != request_digest:
                raise IdempotencyConflict(
                    f"idempotency key {command.task_id!r} has a different request digest"
                )
            return result_from_envelope(
                existing.result_envelope_json, expected_task_id=command.task_id
            )

        try:
            existing_task = uow.tasks.get(command.task_id)
        except CreationApplicationError:
            raise
        except Exception as exc:
            raise CreationApplicationError("creation persistence read failed") from exc
        if existing_task is not None:
            raise OperationIdConflict(
                "task already exists without a matching idempotency record"
            )

        operation_id = str(self._id_factory())
        event_id = str(self._id_factory())
        now = datetime.now(timezone.utc)
        timestamp = now.isoformat(timespec="microseconds").replace("+00:00", "Z")

        task = ChapterTask(
            task_id=command.task_id,
            schema_version=SCHEMA_VERSION,
            aggregate_revision=0,
            project_id=command.project_id,
            chapter_number=command.chapter_number,
            status=ChapterTaskStatus.PLAN_PREPARING,
            last_stable_status=ChapterTaskStatus.PLAN_PREPARING,
            creative_intent_ref=command.creative_intent_ref,
            confirmed_plan_ref=None,
            current_author_draft_ref=None,
            review_target_draft_ref=None,
            adopted_draft_ref=None,
            latest_review_ref=None,
            pending_changeset_ref=None,
            commit_receipt_ref=None,
            recovery=None,
            created_at=now,
            updated_at=now,
        )
        result = CreateChapterTaskResult(
            task_id=task.task_id,
            aggregate_revision=task.aggregate_revision,
            status=task.status,
        )
        envelope_json = create_result_envelope(
            result,
            operation_kind=kind,
            original_operation_id=operation_id,
            audit_event_ids=(event_id,),
        )
        record = OperationLogRecord(
            operation_id=operation_id,
            idempotency_key=command.task_id,
            request_digest=request_digest,
            result_envelope_json=envelope_json,
            result_envelope_hash=compute_envelope_hash(envelope_json),
            created_at=timestamp,
        )
        audit_event = AuditEvent(
            event_id=event_id,
            schema_version=SCHEMA_VERSION,
            task_id=task.task_id,
            project_id=task.project_id,
            event_type="TASK_CREATED",
            actor=SourceRef(kind=SourceKind.SYSTEM),
            before_task_revision=0,
            after_task_revision=0,
            object_refs=(task.creative_intent_ref,),
            operation_id=operation_id,
            created_at=now,
        )

        try:
            outcome = uow.operations.create_or_replay_complete(record)
        except CreationApplicationError:
            _rollback_or_raise(uow)
            raise
        except Exception as exc:
            _rollback_or_raise(uow)
            raise CreationApplicationError("creation persistence failed") from exc

        if outcome.status is OperationResult.REPLAY:
            _rollback_or_raise(uow)
            return result_from_envelope(
                _require_replay_envelope(outcome), expected_task_id=command.task_id
            )
        if outcome.status is OperationResult.CONFLICT:
            _rollback_or_raise(uow)
            raise IdempotencyConflict(
                f"idempotency key {command.task_id!r} has a different request digest"
            )

        try:
            uow.tasks.add(task)
            uow.audit.add_event(audit_event)
            uow.commit()
        except CreationApplicationError:
            _rollback_or_raise(uow)
            raise
        except Exception as exc:
            _rollback_or_raise(uow)
            raise CreationApplicationError("creation persistence failed") from exc

        return result


def _require_replay_envelope(outcome: OperationCreateOutcome) -> str:
    if outcome.replay_envelope_json is None:
        raise CreationApplicationError("REPLAY outcome did not include the original envelope")
    return outcome.replay_envelope_json


def _rollback_or_raise(uow: CreationUnitOfWork) -> None:
    try:
        uow.rollback()
    except Exception as exc:
        raise CreationApplicationError("creation rollback failed") from exc
