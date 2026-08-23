"""G0C-01..12: PLAN preparation application boundary tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from xiaoshuo.application.creation.authoring_artifact import (
    AuthoringArtifactKind,
    AuthoringArtifactEnvelope,
    serialize_authoring_artifact_envelope,
)
from xiaoshuo.application.creation.errors import (
    CreationApplicationError,
    IdempotencyConflict,
    UnsupportedPersistenceBoundary,
)
from xiaoshuo.application.creation.local_author_context import LocalAuthorContextImpl
from xiaoshuo.application.creation.operation_kind import OperationKind
from xiaoshuo.application.creation.plan_preparation import (
    PlanPreparationDeliveryContext,
    PreparePlanForApprovalCommand,
    PreparePlanForApprovalUseCase,
)
from xiaoshuo.application.creation.repository import (
    OperationCreateOutcome,
    OperationLogRecord,
    OperationResult,
)
from xiaoshuo.domain.creation import ArtifactRef, ChapterTask, ChapterTaskStatus


def _ref(name: str = "intent") -> ArtifactRef:
    return ArtifactRef(name, 1, "sha256:" + "1" * 64)


def _task(status: ChapterTaskStatus = ChapterTaskStatus.PLAN_PREPARING, revision: int = 0):
    now = datetime.now(timezone.utc)
    return ChapterTask(
        task_id="task-1",
        schema_version=1,
        aggregate_revision=revision,
        project_id="project-1",
        chapter_number=1,
        status=status,
        last_stable_status=status,
        creative_intent_ref=_ref(),
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


def _plan_bytes(body: str = "goal") -> bytes:
    return serialize_authoring_artifact_envelope(
        AuthoringArtifactEnvelope(
            artifact_kind=AuthoringArtifactKind.PLAN,
            artifact_schema_version=1,
            project_id="project-1",
            chapter_number=1,
            task_id="task-1",
            body=body,
        )
    )


@dataclass
class _PayloadStore:
    values: dict[str, bytes]
    put_calls: int = 0
    read_calls: int = 0

    def put(self, data: bytes) -> str:
        import hashlib

        self.put_calls += 1
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        self.values[digest] = data
        return digest

    def read(self, digest: str) -> bytes:
        self.read_calls += 1
        return self.values[digest]


class _Operations:
    def __init__(self) -> None:
        self.records: dict[str, OperationLogRecord] = {}

    def get_by_idempotency_key(self, key: str):
        return self.records.get(key)

    def create_or_replay_complete(self, record: OperationLogRecord):
        existing = self.records.get(record.idempotency_key)
        if existing is None:
            self.records[record.idempotency_key] = record
            return OperationCreateOutcome(OperationResult.NEW)
        if existing.request_digest == record.request_digest:
            return OperationCreateOutcome(OperationResult.REPLAY, existing.result_envelope_json)
        return OperationCreateOutcome(OperationResult.CONFLICT)


class _Tasks:
    def __init__(self, task):
        self.task = task
        self.replaced = None

    def get(self, task_id):
        return self.task if task_id == self.task.task_id else None

    def replace(self, task, *, expected_revision):
        self.replaced = task
        self.task = task


class _Audit:
    def __init__(self):
        self.events = []

    def add_event(self, event):
        self.events.append(event)


class _Uow:
    def __init__(self, task, *, close_error: Exception | None = None):
        self.tasks = _Tasks(task)
        self.operations = _Operations()
        self.audit = _Audit()
        self.decisions = None
        self.canon = None
        self.commit_calls = 0
        self.rollback_calls = 0
        self.close_calls = 0
        self.close_error = close_error

    def commit(self):
        self.commit_calls += 1

    def rollback(self):
        self.rollback_calls += 1

    def close(self):
        self.close_calls += 1
        if self.close_error:
            raise self.close_error


def _use_case(uow, store, *, ids=None):
    values = iter(ids or ["op-1", "plan-1", "audit-1"])
    return PreparePlanForApprovalUseCase(
        lambda: uow,
        LocalAuthorContextImpl("local-author"),
        store,
        id_factory=lambda: next(values),
    )


def _command(data: bytes | None = None):
    return PreparePlanForApprovalCommand("task-1", 0, data or _plan_bytes())


def test_plan_new_persists_payload_and_transitions_task_without_confirmation_ref():
    uow = _Uow(_task())
    store = _PayloadStore({})
    result = _use_case(uow, store).prepare(_command(), PlanPreparationDeliveryContext("plan-key"))
    assert result.plan_ref.artifact_id == "plan-1"
    assert result.status is ChapterTaskStatus.PLAN_APPROVAL_PENDING
    assert uow.tasks.task.confirmed_plan_ref is None
    assert uow.tasks.task.status is ChapterTaskStatus.PLAN_APPROVAL_PENDING
    assert len(uow.audit.events) == 1
    assert store.put_calls == 1
    assert store.read_calls == 1
    assert uow.commit_calls == 1
    assert uow.rollback_calls == 0
    assert uow.close_calls == 1


def test_plan_same_key_replays_before_task_and_payload_io():
    uow = _Uow(_task())
    store = _PayloadStore({})
    use_case = _use_case(uow, store)
    first = use_case.prepare(_command(), PlanPreparationDeliveryContext("plan-key"))
    uow.tasks.task = _task(ChapterTaskStatus.PLAN_APPROVAL_PENDING, 1)
    replay = use_case.prepare(_command(), PlanPreparationDeliveryContext("plan-key"))
    assert replay == first
    assert store.put_calls == 1
    assert store.read_calls == 1
    assert len(uow.audit.events) == 1


def test_plan_same_key_different_digest_is_conflict():
    uow = _Uow(_task())
    store = _PayloadStore({})
    use_case = _use_case(uow, store)
    use_case.prepare(_command(), PlanPreparationDeliveryContext("plan-key"))
    with pytest.raises(IdempotencyConflict):
        use_case.prepare(_command(_plan_bytes("changed")), PlanPreparationDeliveryContext("plan-key"))
    assert store.put_calls == 1


@pytest.mark.parametrize(
    "data",
    [
        b'{"artifact_kind":"PLAN","artifact_schema_version":1,"body":"x\\u0000","chapter_number":1,"project_id":"project-1","task_id":"task-1"}',
        b'{"artifact_kind":"PLAN","artifact_schema_version":1,"body":"x","chapter_number":1,"project_id":"project-1\\u0000","task_id":"task-1"}',
        b'{"artifact_kind":"DRAFT","artifact_schema_version":1,"body":"x","chapter_number":1,"project_id":"project-1","task_id":"task-1"}',
    ],
)
def test_plan_rejects_noncanonical_or_decoded_nul_before_payload_io(data):
    uow = _Uow(_task())
    store = _PayloadStore({})
    with pytest.raises(UnsupportedPersistenceBoundary):
        _use_case(uow, store).prepare(_command(data), PlanPreparationDeliveryContext("plan-key"))
    assert store.put_calls == 0
    assert uow.commit_calls == 0


def test_plan_wrong_state_has_no_payload_or_commit():
    uow = _Uow(_task(ChapterTaskStatus.DRAFTING))
    store = _PayloadStore({})
    with pytest.raises(UnsupportedPersistenceBoundary):
        _use_case(uow, store).prepare(_command(), PlanPreparationDeliveryContext("plan-key"))
    assert store.put_calls == 0
    assert uow.commit_calls == 0


def test_plan_close_failure_after_commit_does_not_rollback_or_close_again():
    uow = _Uow(_task(), close_error=OSError("close failed"))
    store = _PayloadStore({})
    with pytest.raises(CreationApplicationError) as error:
        _use_case(uow, store).prepare(_command(), PlanPreparationDeliveryContext("plan-key"))
    assert isinstance(error.value.__cause__, OSError)
    assert uow.commit_calls == 1
    assert uow.rollback_calls == 0
    assert uow.close_calls == 1


def test_new_operation_kind_is_dedicated():
    assert OperationKind.PREPARE_PLAN_FOR_APPROVAL.value == "PREPARE_PLAN_FOR_APPROVAL"
