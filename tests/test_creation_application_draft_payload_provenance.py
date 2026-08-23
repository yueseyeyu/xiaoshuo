"""DPP-01--DPP-23: forward ADOPT_DRAFT payload provenance contracts."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Callable

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from xiaoshuo.application.creation.author_decision import (
    CreateAuthorDecisionUseCase,
)
from xiaoshuo.application.creation.author_decision_transition import (
    ConsumeAuthorDecisionUseCase,
)
from xiaoshuo.application.creation.commands import (
    ConsumeAuthorDecisionCommand,
    CreateAuthorDecisionCommand,
    CreateChapterTaskCommand,
)
from xiaoshuo.application.creation.create_task import CreateChapterTaskUseCase
from xiaoshuo.application.creation.decision_creation_context import (
    DecisionCreationContext,
)
from xiaoshuo.application.creation.digest import (
    compute_adopted_draft_payload_content_hash,
    compute_decision_creation_request_digest,
    create_decision_creation_result_envelope,
)
from xiaoshuo.application.creation.errors import (
    AdoptedDraftPayloadPersistenceFailed,
    AdoptedDraftPayloadRejected,
    CreationApplicationError,
    IdempotencyConflict,
    NotFound,
    UnsupportedPersistenceBoundary,
)
from xiaoshuo.application.creation.local_author_context import LocalAuthorContextImpl
from xiaoshuo.application.creation.operation_kind import OperationKind
from xiaoshuo.application.creation.repository import (
    OperationCreateOutcome,
    OperationResult,
)
from xiaoshuo.application.creation.results import AuthorDecisionResult
from xiaoshuo.application.creation.transition_context import TransitionOperationContext
from xiaoshuo.domain.creation import ArtifactRef, ChapterTaskStatus, DecisionType
from xiaoshuo.infrastructure.persistence.sqlite.connection import get_connection
from xiaoshuo.infrastructure.persistence.sqlite.maintenance import init_database
from xiaoshuo.infrastructure.persistence.sqlite.migration_runner import MigrationRunner
from xiaoshuo.infrastructure.persistence.sqlite.settings import SQLitePersistenceSettings
from xiaoshuo.infrastructure.persistence.sqlite.uow import SqliteCreationUnitOfWork


PAYLOAD = b"adopted draft payload"
PAYLOAD_B = b"another adopted draft payload"
PAYLOAD_HASH = compute_adopted_draft_payload_content_hash(PAYLOAD)
PAYLOAD_HASH_B = compute_adopted_draft_payload_content_hash(PAYLOAD_B)
HASH_OTHER = "sha256:" + "f" * 64


class _MemoryPayloadStore:
    def __init__(
        self,
        data: bytes = PAYLOAD,
        *,
        put_digest: str | None = None,
        read_data: bytes | None = None,
        put_error: Exception | None = None,
        read_error: Exception | None = None,
    ) -> None:
        self.data = data
        self.put_digest = put_digest
        self.read_data = data if read_data is None else read_data
        self.put_error = put_error
        self.read_error = read_error
        self.put_calls: list[bytes] = []
        self.read_calls: list[str] = []
        self.objects: dict[str, bytes] = {}

    def put(self, data: bytes) -> str:
        self.put_calls.append(data)
        if self.put_error is not None:
            raise self.put_error
        digest = self.put_digest or compute_adopted_draft_payload_content_hash(data)
        self.objects[digest] = data
        return digest

    def read(self, digest: str) -> bytes:
        self.read_calls.append(digest)
        if self.read_error is not None:
            raise self.read_error
        return self.read_data


class _NoCallsPayloadStore(_MemoryPayloadStore):
    def put(self, data: bytes) -> str:
        raise AssertionError("payload store put must not be called")

    def read(self, digest: str) -> bytes:
        raise AssertionError("payload store read must not be called")


def _ids(*names: str) -> Callable[[], str]:
    values = iter(names)

    def factory() -> str:
        try:
            return next(values)
        except StopIteration:
            raise AssertionError("unexpected identity factory call")

    return factory


def _ref(artifact_id: str = "draft-1", content_hash: str = PAYLOAD_HASH) -> ArtifactRef:
    return ArtifactRef(artifact_id, 1, content_hash)


def _init_sqlite(tmp_path: Path) -> SQLitePersistenceSettings:
    tmp_path.mkdir(parents=True, exist_ok=True)
    settings = SQLitePersistenceSettings(
        tmp_path / "dpp.db", 5000, backup_dir=tmp_path / "backup"
    )
    init_database(settings)
    conn = get_connection(settings)
    try:
        MigrationRunner().migrate(conn, settings)
    finally:
        conn.close()
    return settings


def _factory(settings: SQLitePersistenceSettings):
    def create_uow() -> SqliteCreationUnitOfWork:
        return SqliteCreationUnitOfWork(get_connection(settings))

    return create_uow


def _author_context() -> LocalAuthorContextImpl:
    return LocalAuthorContextImpl(_author_id="author-local-1")


def _create_base_task(settings: SQLitePersistenceSettings, task_id: str = "task-1") -> None:
    intent = _ref("intent-" + task_id, HASH_OTHER)
    command = CreateChapterTaskCommand(
        task_id=task_id,
        project_id="project-1",
        chapter_number=1,
        initial_status=ChapterTaskStatus.PLAN_PREPARING,
        creative_intent_ref=intent,
    )
    CreateChapterTaskUseCase(_factory(settings), id_factory=_ids("task-op", "task-event")).create(command)


def _prepare_task(
    settings: SQLitePersistenceSettings,
    *,
    status: ChapterTaskStatus = ChapterTaskStatus.DRAFT_APPROVAL_PENDING,
    revision: int = 1,
    task_id: str = "task-1",
    include_current_ref: bool = True,
    include_review_target_ref: bool = True,
    include_latest_review_ref: bool = True,
) -> None:
    _create_base_task(settings, task_id)
    plan = _ref("plan-" + task_id, HASH_OTHER)
    current = _ref(
        "draft-1" if task_id == "task-1" else "draft-" + task_id,
        PAYLOAD_HASH,
    )
    latest_review = _ref("review-" + task_id, HASH_OTHER)
    conn = get_connection(settings)
    try:
        for ref in (plan, current, latest_review):
            conn.execute(
                "INSERT OR IGNORE INTO creation_artifact_ref "
                "(artifact_id, schema_version, content_hash) VALUES (?, ?, ?)",
                (ref.artifact_id, ref.schema_version, ref.content_hash),
            )
        conn.execute(
            "UPDATE chapter_task SET status = ?, last_stable_status = ?, "
            "aggregate_revision = ?, confirmed_plan_ref_artifact_id = ?, "
            "current_author_draft_ref_artifact_id = ?, "
            "review_target_draft_ref_artifact_id = ?, "
            "latest_review_ref_artifact_id = ? "
            "WHERE task_id = ?",
            (
                status.value,
                ChapterTaskStatus.DRAFTING.value
                if status is ChapterTaskStatus.DRAFT_APPROVAL_PENDING
                else ChapterTaskStatus.PLAN_PREPARING.value,
                revision,
                plan.artifact_id,
                current.artifact_id if include_current_ref else None,
                current.artifact_id if include_review_target_ref else None,
                latest_review.artifact_id if include_latest_review_ref else None,
                task_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _adopt_command(
    *,
    task_id: str = "task-1",
    target_ref: ArtifactRef | None = None,
    revision: int = 1,
    payload: object = PAYLOAD,
    reason: str | None = None,
) -> CreateAuthorDecisionCommand:
    return CreateAuthorDecisionCommand(
        task_id=task_id,
        decision_type=DecisionType.ADOPT_DRAFT,
        target_ref=target_ref or _ref(),
        based_on_task_revision=revision,
        reason=reason,
        adopted_draft_payload=payload,  # type: ignore[arg-type]
    )


def _confirm_command(task_id: str = "task-1") -> CreateAuthorDecisionCommand:
    return CreateAuthorDecisionCommand(
        task_id=task_id,
        decision_type=DecisionType.CONFIRM_PLAN,
        target_ref=_ref("plan-" + task_id, HASH_OTHER),
        based_on_task_revision=0,
    )


def _create(
    settings: SQLitePersistenceSettings,
    command: CreateAuthorDecisionCommand,
    key: str,
    store: object | None,
    *,
    id_factory: Callable[[], str] | None = None,
    uow_factory=None,
):
    return CreateAuthorDecisionUseCase(
        uow_factory or _factory(settings),
        _author_context(),
        id_factory=id_factory or _ids("operation-1", "decision-1"),
        payload_store=store,
    ).create(command, DecisionCreationContext(idempotency_key=key))


def _counts(settings: SQLitePersistenceSettings) -> dict[str, int]:
    conn = get_connection(settings, read_only=True)
    try:
        return {
            table: conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
            for table in (
                "creation_operation",
                "creation_author_decision",
                "creation_audit_event",
                "creation_artifact_ref",
            )
        }
    finally:
        conn.close()


def _operation(settings: SQLitePersistenceSettings, key: str):
    conn = get_connection(settings, read_only=True)
    try:
        return conn.execute(
            "SELECT request_digest, result_envelope_json FROM creation_operation "
            "WHERE idempotency_key = ?",
            (key,),
        ).fetchone()
    finally:
        conn.close()


def _task_state(settings: SQLitePersistenceSettings, task_id: str = "task-1"):
    conn = get_connection(settings, read_only=True)
    try:
        return conn.execute(
            "SELECT status, aggregate_revision FROM chapter_task WHERE task_id = ?",
            (task_id,),
        ).fetchone()
    finally:
        conn.close()


def test_dpp_01_adopt_payload_is_required() -> None:
    command = _adopt_command(payload=None)
    with pytest.raises(AdoptedDraftPayloadRejected):
        _create(
            None,  # type: ignore[arg-type]
            command,
            "dpp-01",
            None,
            uow_factory=lambda: (_ for _ in ()).throw(AssertionError("UoW read")),
        )


def test_dpp_02_non_adopt_payload_is_forbidden() -> None:
    command = _confirm_command()
    command = CreateAuthorDecisionCommand(
        task_id=command.task_id,
        decision_type=command.decision_type,
        target_ref=command.target_ref,
        based_on_task_revision=command.based_on_task_revision,
        adopted_draft_payload=PAYLOAD,
    )
    with pytest.raises(AdoptedDraftPayloadRejected):
        _create(
            None,  # type: ignore[arg-type]
            command,
            "dpp-02",
            None,
            uow_factory=lambda: (_ for _ in ()).throw(AssertionError("UoW read")),
        )


def test_dpp_03_adopt_payload_must_be_bytes() -> None:
    with pytest.raises(AdoptedDraftPayloadRejected):
        _create(
            None,  # type: ignore[arg-type]
            _adopt_command(payload=bytearray(PAYLOAD)),
            "dpp-03",
            None,
            uow_factory=lambda: (_ for _ in ()).throw(AssertionError("UoW read")),
        )


def test_dpp_04_empty_payload_is_rejected_without_residue(tmp_path: Path) -> None:
    settings = _init_sqlite(tmp_path)
    baseline = _counts(settings)
    with pytest.raises(AdoptedDraftPayloadRejected):
        _create(settings, _adopt_command(payload=b""), "dpp-04", _NoCallsPayloadStore())
    assert _counts(settings) == baseline


def test_dpp_05_non_utf8_payload_is_rejected(tmp_path: Path) -> None:
    settings = _init_sqlite(tmp_path)
    with pytest.raises(AdoptedDraftPayloadRejected):
        _create(settings, _adopt_command(payload=b"\xff"), "dpp-05", _NoCallsPayloadStore())
    assert _counts(settings)["creation_operation"] == 0


def test_dpp_06_nul_payload_is_rejected(tmp_path: Path) -> None:
    settings = _init_sqlite(tmp_path)
    with pytest.raises(AdoptedDraftPayloadRejected):
        _create(settings, _adopt_command(payload=b"draft\x00body"), "dpp-06", _NoCallsPayloadStore())
    assert _counts(settings)["creation_operation"] == 0


def test_dpp_07_payload_hash_must_match_target_ref(tmp_path: Path) -> None:
    settings = _init_sqlite(tmp_path)
    command = _adopt_command(target_ref=_ref(content_hash=HASH_OTHER))
    store = _NoCallsPayloadStore()
    with pytest.raises(AdoptedDraftPayloadRejected):
        _create(settings, command, "dpp-07", store)
    assert store.put_calls == []
    assert _counts(settings)["creation_operation"] == 0


def test_g0b_corr_05_wrong_trusted_target_fails_before_payload_io_and_sqlite_write(
    tmp_path: Path,
) -> None:
    settings = _init_sqlite(tmp_path)
    _prepare_task(settings)
    store = _NoCallsPayloadStore()
    baseline = _counts(settings)
    wrong_target = _ref("wrong-target", PAYLOAD_HASH)
    with pytest.raises(UnsupportedPersistenceBoundary):
        _create(settings, _adopt_command(target_ref=wrong_target), "g0b-corr-05", store)
    assert store.put_calls == []
    assert store.read_calls == []
    assert _counts(settings) == baseline


def test_dpp_08_raw_payload_does_not_enter_business_facts(tmp_path: Path) -> None:
    settings = _init_sqlite(tmp_path)
    _prepare_task(settings)
    command = _adopt_command()
    store = _MemoryPayloadStore()
    _create(settings, command, "dpp-08", store)
    raw_text = PAYLOAD.decode("utf-8")
    assert raw_text not in repr(command)
    conn = get_connection(settings, read_only=True)
    try:
        for table in (
            "creation_operation",
            "creation_author_decision",
            "creation_audit_event",
        ):
            rows = conn.execute("SELECT * FROM " + table).fetchall()
            assert raw_text not in repr(rows)
    finally:
        conn.close()


def test_dpp_09_request_digest_uses_payload_hash_not_raw_or_context(tmp_path: Path) -> None:
    settings = _init_sqlite(tmp_path)
    _prepare_task(settings)
    command = _adopt_command()
    key = "dpp-09-context"
    _create(settings, command, key, _MemoryPayloadStore())
    operation = _operation(settings, key)
    assert operation is not None
    expected = compute_decision_creation_request_digest(
        command, OperationKind.CREATE_AUTHOR_DECISION
    )
    assert operation["request_digest"] == expected
    assert PAYLOAD.decode("utf-8") not in operation["request_digest"]
    assert key not in operation["request_digest"]
    other = _adopt_command(target_ref=_ref(content_hash=PAYLOAD_HASH_B), payload=PAYLOAD_B)
    assert expected != compute_decision_creation_request_digest(
        other, OperationKind.CREATE_AUTHOR_DECISION
    )


def _guarded_replay_factory(settings: SQLitePersistenceSettings):
    def factory():
        uow = SqliteCreationUnitOfWork(get_connection(settings))

        class ExplodingTasks:
            def get(self, task_id: str):
                raise AssertionError("Task read must not occur on ledger fast path")

        uow.tasks = ExplodingTasks()
        return uow

    return factory


def test_dpp_10_existing_same_digest_replay_is_before_identity_and_task(tmp_path: Path) -> None:
    settings = _init_sqlite(tmp_path)
    _prepare_task(settings)
    command = _adopt_command()
    _create(settings, command, "dpp-10", _MemoryPayloadStore())
    result = _create(
        settings,
        command,
        "dpp-10",
        _NoCallsPayloadStore(),
        id_factory=_ids(),
        uow_factory=_guarded_replay_factory(settings),
    )
    assert result.task_id == "task-1"


def test_dpp_11_existing_different_payload_hash_conflicts_first(tmp_path: Path) -> None:
    settings = _init_sqlite(tmp_path)
    _prepare_task(settings)
    _create(settings, _adopt_command(), "dpp-11", _MemoryPayloadStore())
    invalid = _adopt_command(
        target_ref=_ref(content_hash=HASH_OTHER), payload=b"\xff"
    )
    with pytest.raises(IdempotencyConflict):
        _create(
            settings,
            invalid,
            "dpp-11",
            _NoCallsPayloadStore(),
            id_factory=_ids(),
            uow_factory=_guarded_replay_factory(settings),
        )


def test_dpp_12_existing_different_business_input_conflicts_first(tmp_path: Path) -> None:
    settings = _init_sqlite(tmp_path)
    _prepare_task(settings)
    _create(settings, _adopt_command(), "dpp-12", _MemoryPayloadStore())
    different = _adopt_command(target_ref=_ref("different-draft"), reason="different")
    with pytest.raises(IdempotencyConflict):
        _create(
            settings,
            different,
            "dpp-12",
            _NoCallsPayloadStore(),
            id_factory=_ids(),
            uow_factory=_guarded_replay_factory(settings),
        )


def test_dpp_13_new_path_rejects_missing_status_or_revision_without_payload_io(
    tmp_path: Path,
) -> None:
    settings = _init_sqlite(tmp_path / "missing")
    with pytest.raises(NotFound):
        _create(settings, _adopt_command(), "dpp-13-missing", _NoCallsPayloadStore())

    for suffix, status, revision, expected in (
        (
            "status",
            ChapterTaskStatus.DRAFTING,
            1,
            UnsupportedPersistenceBoundary,
        ),
        (
            "revision",
            ChapterTaskStatus.DRAFT_APPROVAL_PENDING,
            2,
            UnsupportedPersistenceBoundary,
        ),
    ):
        local = _init_sqlite(tmp_path / suffix)
        _prepare_task(local, status=status, revision=revision)
        store = _NoCallsPayloadStore()
        with pytest.raises(expected):
            _create(local, _adopt_command(revision=1), "dpp-13-" + suffix, store)


class _FakeOperations:
    def __init__(self, status: OperationResult, envelope: str | None = None) -> None:
        self.status = status
        self.envelope = envelope
        self.create_calls = 0

    def get_by_idempotency_key(self, key: str):
        return None

    def create_or_replay_complete(self, record):
        self.create_calls += 1
        return OperationCreateOutcome(self.status, self.envelope)


class _FakeDecisions:
    def __init__(self) -> None:
        self.add_calls = 0

    def add(self, decision) -> None:
        self.add_calls += 1


class _FakeUow:
    def __init__(self, outcome: OperationResult, envelope: str | None = None) -> None:
        self.tasks = SimpleNamespace(
            get=lambda task_id: SimpleNamespace(
                status=ChapterTaskStatus.DRAFT_APPROVAL_PENDING,
                aggregate_revision=1,
                current_author_draft_ref=_ref(),
                review_target_draft_ref=_ref(),
                latest_review_ref=_ref("review-1", HASH_OTHER),
            )
        )
        self.operations = _FakeOperations(outcome, envelope)
        self.decisions = _FakeDecisions()
        self.audit = SimpleNamespace()
        self.canon = SimpleNamespace()
        self.rollback_calls = 0
        self.commit_calls = 0

    def commit(self) -> None:
        self.commit_calls += 1

    def rollback(self) -> None:
        self.rollback_calls += 1

    def close(self) -> None:
        pass


def test_dpp_14_only_new_can_put_and_competition_discards_candidate_ids(
    tmp_path: Path,
) -> None:
    envelope = create_decision_creation_result_envelope(
        AuthorDecisionResult("winner-decision", "task-1"),
        operation_kind=OperationKind.CREATE_AUTHOR_DECISION,
        original_operation_id="winner-operation",
    )
    for outcome in (OperationResult.REPLAY, OperationResult.CONFLICT):
        uow = _FakeUow(outcome, envelope if outcome is OperationResult.REPLAY else None)
        store = _MemoryPayloadStore()
        use_case = CreateAuthorDecisionUseCase(
            lambda: uow,
            _author_context(),
            id_factory=_ids("candidate-operation", "candidate-decision"),
            payload_store=store,
        )
        command = _adopt_command()
        if outcome is OperationResult.REPLAY:
            result = use_case.create(command, DecisionCreationContext(idempotency_key="dpp-14"))
            assert result.decision_id == "winner-decision"
        else:
            with pytest.raises(IdempotencyConflict):
                use_case.create(command, DecisionCreationContext(idempotency_key="dpp-14"))
        assert uow.operations.create_calls == 1
        assert uow.decisions.add_calls == 0
        assert uow.commit_calls == 0
        assert uow.rollback_calls >= 1
        assert store.put_calls == []
        assert store.read_calls == []

    settings = _init_sqlite(tmp_path / "unknown")
    _prepare_task(settings)
    baseline = _counts(settings)
    uow = SqliteCreationUnitOfWork(get_connection(settings))
    unknown_status = object()
    uow.operations.create_or_replay_complete = (  # type: ignore[method-assign]
        lambda record: SimpleNamespace(status=unknown_status, envelope=None)
    )
    add_calls = [0]
    commit_calls = [0]
    rollback_calls = [0]
    uow.decisions.add = (  # type: ignore[method-assign]
        lambda decision: add_calls.__setitem__(0, add_calls[0] + 1)
    )
    uow.commit = lambda: commit_calls.__setitem__(  # type: ignore[method-assign]
        0, commit_calls[0] + 1
    )
    original_rollback = uow.rollback

    def counted_rollback() -> None:
        rollback_calls[0] += 1
        original_rollback()

    uow.rollback = counted_rollback  # type: ignore[method-assign]
    store = _MemoryPayloadStore()
    with pytest.raises(CreationApplicationError, match="unsupported operation outcome"):
        _create(
            settings,
            _adopt_command(),
            "dpp-14-unknown",
            store,
            id_factory=_ids("unknown-operation", "unknown-decision"),
            uow_factory=lambda: uow,
        )
    assert store.put_calls == []
    assert store.read_calls == []
    assert add_calls == [0]
    assert commit_calls == [0]
    assert rollback_calls == [1]
    assert _counts(settings) == baseline
    assert _operation(settings, "dpp-14-unknown") is None


def test_dpp_15_wrong_put_digest_leaves_zero_sqlite_residue(tmp_path: Path) -> None:
    settings = _init_sqlite(tmp_path)
    _prepare_task(settings)
    baseline = _counts(settings)
    store = _MemoryPayloadStore(put_digest=HASH_OTHER)
    with pytest.raises(AdoptedDraftPayloadPersistenceFailed):
        _create(settings, _adopt_command(), "dpp-15", store)
    assert _counts(settings) == baseline


def test_dpp_16_readback_mismatch_leaves_zero_sqlite_residue(tmp_path: Path) -> None:
    settings = _init_sqlite(tmp_path)
    _prepare_task(settings)
    baseline = _counts(settings)
    store = _MemoryPayloadStore(read_data=b"different")
    with pytest.raises(AdoptedDraftPayloadPersistenceFailed):
        _create(settings, _adopt_command(), "dpp-16", store)
    assert _counts(settings) == baseline


def test_dpp_17_payload_store_exception_leaves_zero_sqlite_residue(tmp_path: Path) -> None:
    settings = _init_sqlite(tmp_path)
    _prepare_task(settings)
    baseline = _counts(settings)
    store = _MemoryPayloadStore(put_error=OSError("put failed"))
    with pytest.raises(AdoptedDraftPayloadPersistenceFailed):
        _create(settings, _adopt_command(), "dpp-17", store)
    assert _counts(settings) == baseline


def test_dpp_18_commit_failure_leaves_only_lazy_orphan(tmp_path: Path) -> None:
    settings = _init_sqlite(tmp_path)
    _prepare_task(settings)
    baseline = _counts(settings)
    store = _MemoryPayloadStore()
    uow = SqliteCreationUnitOfWork(get_connection(settings))

    commit_error = OSError("commit failed")

    def fail_commit() -> None:
        raise commit_error

    uow.commit = fail_commit  # type: ignore[method-assign]
    with pytest.raises(AdoptedDraftPayloadPersistenceFailed) as exc_info:
        _create(
            settings,
            _adopt_command(),
            "dpp-18",
            store,
            uow_factory=lambda: uow,
        )
    assert exc_info.value.__cause__ is commit_error
    assert store.put_calls == [PAYLOAD]
    assert store.read_calls == [PAYLOAD_HASH]
    assert _counts(settings) == baseline
    assert store.objects[PAYLOAD_HASH] == PAYLOAD
    assert store.read(PAYLOAD_HASH) == PAYLOAD


def test_dpp_19_success_binds_bytes_digest_and_target_ref(tmp_path: Path) -> None:
    settings = _init_sqlite(tmp_path)
    _prepare_task(settings)
    store = _MemoryPayloadStore()
    result = _create(settings, _adopt_command(), "dpp-19", store)
    assert result.task_id == "task-1"
    assert store.put_calls == [PAYLOAD]
    assert store.read_calls == [PAYLOAD_HASH]
    conn = get_connection(settings, read_only=True)
    try:
        row = conn.execute(
            "SELECT target_ref_artifact_id FROM creation_author_decision "
            "WHERE decision_id = ?",
            (result.decision_id,),
        ).fetchone()
        assert row["target_ref_artifact_id"] == "draft-1"
    finally:
        conn.close()


def test_dpp_20_consume_adopt_does_not_write_payload_again(tmp_path: Path) -> None:
    settings = _init_sqlite(tmp_path)
    _prepare_task(settings)
    store = _MemoryPayloadStore()
    result = _create(settings, _adopt_command(), "dpp-20-create", store)
    consume = ConsumeAuthorDecisionUseCase(
        _factory(settings),
        _author_context(),
        id_factory=_ids("consume-operation", "consume-event", "consume-audit"),
    )
    consumed = consume.consume(
        ConsumeAuthorDecisionCommand(
            task_id="task-1",
            decision_id=result.decision_id,
            expected_revision=1,
        ),
        TransitionOperationContext(idempotency_key="dpp-20-consume"),
    )
    assert consumed.status is ChapterTaskStatus.CHANGESET_PREPARING
    assert store.put_calls == [PAYLOAD]
    assert store.read_calls == [PAYLOAD_HASH]


def test_dpp_21_non_adopt_preserves_behavior_without_payload_write(tmp_path: Path) -> None:
    settings = _init_sqlite(tmp_path)
    _prepare_task(settings, status=ChapterTaskStatus.PLAN_APPROVAL_PENDING, revision=0)
    result = _create(settings, _confirm_command(), "dpp-21", None)
    assert result.task_id == "task-1"
    assert _counts(settings)["creation_author_decision"] == 1


def test_dpp_22_application_boundary_has_no_infrastructure_dependency() -> None:
    source_path = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "xiaoshuo"
        / "application"
        / "creation"
        / "author_decision.py"
    )
    source = source_path.read_text(encoding="utf-8")
    assert "xiaoshuo.infrastructure" not in source
    assert "config.yaml" not in source
    assert "filesystem" not in source


def test_dpp_23_does_not_backfill_history_or_lift_c5_g0(tmp_path: Path) -> None:
    settings = _init_sqlite(tmp_path)
    source_path = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "xiaoshuo"
        / "application"
        / "creation"
        / "author_decision.py"
    )
    source = source_path.read_text(encoding="utf-8")
    assert "assets/canon" not in source
    assert "UPDATE chapter_task" not in source
    assert "migration" not in source.lower()
    assert _counts(settings)["creation_author_decision"] == 0
