"""C5G0-11--21, 23 and 32: G0-B envelope and DRAFT intake contracts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Callable

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from xiaoshuo.application.creation.authoring_artifact import (
    AuthoringArtifactEnvelope,
    AuthoringArtifactInputRejected,
    AuthoringArtifactKind,
    AuthoringArtifactSubmissionResult,
    authoring_artifact_content_hash,
    parse_authoring_artifact_envelope,
    serialize_authoring_artifact_envelope,
)
from xiaoshuo.application.creation.authoring_artifact_context import (
    AuthoringArtifactSubmissionContext,
    DraftReviewSubmissionContext,
)
from xiaoshuo.application.creation.commands import (
    CreateChapterTaskCommand,
    SubmitDraftForReviewCommand,
    SubmitAuthoringArtifactCommand,
)
from xiaoshuo.application.creation.create_task import CreateChapterTaskUseCase
from xiaoshuo.application.creation.digest import (
    compute_envelope_hash,
    create_authoring_submission_result_envelope,
)
from xiaoshuo.application.creation.draft_review_submission import (
    SubmitAuthoringArtifactUseCase,
)
from xiaoshuo.application.creation.errors import (
    AuthoringArtifactBindingRejected,
    AuthoringArtifactPayloadPersistenceFailed,
    IdempotencyConflict,
)
from xiaoshuo.application.creation.local_author_context import LocalAuthorContextImpl
from xiaoshuo.application.creation.operation_kind import OperationKind
from xiaoshuo.domain.creation import ArtifactRef, ChapterTask, ChapterTaskStatus
from xiaoshuo.infrastructure.persistence.sqlite.connection import get_connection
from xiaoshuo.infrastructure.persistence.sqlite.maintenance import init_database
from xiaoshuo.infrastructure.persistence.sqlite.migration_runner import MigrationRunner
from xiaoshuo.infrastructure.persistence.sqlite.settings import SQLitePersistenceSettings
from xiaoshuo.infrastructure.persistence.sqlite.uow import SqliteCreationUnitOfWork
from xiaoshuo.application.creation.repository import (
    OperationCreateOutcome,
    OperationResult,
)


HASH = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


class MemoryPayloadStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.put_calls: list[bytes] = []
        self.read_calls: list[str] = []

    def put(self, data: bytes) -> str:
        self.put_calls.append(data)
        digest = authoring_artifact_content_hash(data)
        self.objects[digest] = data
        return digest

    def read(self, digest: str) -> bytes:
        self.read_calls.append(digest)
        return self.objects[digest]


class NoCallsPayloadStore(MemoryPayloadStore):
    def put(self, data: bytes) -> str:
        raise AssertionError("payload put must not be called")

    def read(self, digest: str) -> bytes:
        raise AssertionError("payload read must not be called")


@dataclass(frozen=True, slots=True)
class TaskFixture:
    task_id: str
    aggregate_revision: int
    status: ChapterTaskStatus
    creative_intent_ref: ArtifactRef
    confirmed_plan_ref: ArtifactRef | None


def _ids(*values: str) -> Callable[[], str]:
    iterator = iter(values)

    def next_id() -> str:
        try:
            return next(iterator)
        except StopIteration as exc:
            raise AssertionError("unexpected identity factory call") from exc

    return next_id


def _init_sqlite(tmp_path: Path) -> SQLitePersistenceSettings:
    settings = SQLitePersistenceSettings(
        tmp_path / "creation.db", 5000, backup_dir=tmp_path / "backup"
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


def _persist_task_fixture(
    settings: SQLitePersistenceSettings,
    *,
    task_id: str = "task-1",
    status: ChapterTaskStatus,
    revision: int,
    confirmed_plan_ref: ArtifactRef | None,
) -> TaskFixture:
    creative_intent_bytes = _envelope(
        AuthoringArtifactKind.CREATIVE_INTENT, body="creative intent"
    )
    creative_intent_ref = ArtifactRef(
        "intent-1", 1, authoring_artifact_content_hash(creative_intent_bytes)
    )
    now = datetime.now(timezone.utc)
    task = ChapterTask(
        task_id=task_id,
        schema_version=1,
        aggregate_revision=revision,
        project_id="project-1",
        chapter_number=1,
        status=status,
        last_stable_status=(
            ChapterTaskStatus.PLAN_PREPARING
            if status is ChapterTaskStatus.PLAN_APPROVAL_PENDING
            else status
        ),
        creative_intent_ref=creative_intent_ref,
        confirmed_plan_ref=confirmed_plan_ref,
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
    conn = get_connection(settings)
    uow = SqliteCreationUnitOfWork(conn)
    try:
        uow.tasks.add(task)
        uow.commit()
    except Exception:
        uow.rollback()
        raise
    finally:
        uow.close()
    return TaskFixture(
        task_id=task.task_id,
        aggregate_revision=task.aggregate_revision,
        status=task.status,
        creative_intent_ref=task.creative_intent_ref,
        confirmed_plan_ref=task.confirmed_plan_ref,
    )


def _create_plan_preparing_task(
    settings: SQLitePersistenceSettings, *, task_id: str = "task-1"
) -> TaskFixture:
    creative_intent_bytes = _envelope(
        AuthoringArtifactKind.CREATIVE_INTENT, body="creative intent"
    )
    creative_intent_ref = ArtifactRef(
        "intent-1", 1, authoring_artifact_content_hash(creative_intent_bytes)
    )
    result = CreateChapterTaskUseCase(
        _factory(settings), id_factory=_ids("task-operation", "task-event")
    ).create(
        CreateChapterTaskCommand(
            task_id=task_id,
            project_id="project-1",
            chapter_number=1,
            initial_status=ChapterTaskStatus.PLAN_PREPARING,
            creative_intent_ref=creative_intent_ref,
        )
    )
    return TaskFixture(
        task_id=result.task_id,
        aggregate_revision=result.aggregate_revision,
        status=result.status,
        creative_intent_ref=creative_intent_ref,
        confirmed_plan_ref=None,
    )


def _create_plan_pending_task(
    settings: SQLitePersistenceSettings, *, task_id: str = "task-1"
) -> TaskFixture:
    return _persist_task_fixture(
        settings,
        task_id=task_id,
        status=ChapterTaskStatus.PLAN_APPROVAL_PENDING,
        revision=1,
        confirmed_plan_ref=None,
    )


def _create_task(
    settings: SQLitePersistenceSettings,
    *,
    task_id: str = "task-1",
    with_confirmed_plan: bool = True,
) -> TaskFixture:
    plan_bytes = _envelope(AuthoringArtifactKind.PLAN, body="confirmed plan")
    plan_ref = (
        ArtifactRef("plan-1", 1, authoring_artifact_content_hash(plan_bytes))
        if with_confirmed_plan
        else None
    )
    return _persist_task_fixture(
        settings,
        task_id=task_id,
        status=ChapterTaskStatus.DRAFTING,
        revision=2,
        confirmed_plan_ref=plan_ref,
    )


def _envelope(
    kind: AuthoringArtifactKind = AuthoringArtifactKind.DRAFT,
    *,
    body: str = "draft body",
    ref: ArtifactRef | None = None,
) -> bytes:
    return serialize_authoring_artifact_envelope(
        AuthoringArtifactEnvelope(
            artifact_kind=kind,
            artifact_schema_version=1,
            project_id="project-1",
            chapter_number=1,
            task_id="task-1",
            body=body,
            reviewed_draft_ref=ref,
            verdict="PASS" if kind is AuthoringArtifactKind.REVIEW else None,
        )
    )


def _submit(
    settings: SQLitePersistenceSettings,
    payload_store: MemoryPayloadStore,
    envelope: bytes,
    key: str,
    *,
    expected_revision: int,
    id_factory: Callable[[], str] | None = None,
    uow_factory=None,
):
    return SubmitAuthoringArtifactUseCase(
        uow_factory or _factory(settings),
        LocalAuthorContextImpl("author-local"),
        payload_store,
        id_factory=id_factory or _ids("operation-1", "draft-1", "audit-1"),
    ).submit(
        SubmitAuthoringArtifactCommand("task-1", expected_revision, envelope),
        AuthoringArtifactSubmissionContext(key),
    )


class _RaceOperations:
    def __init__(self, replay_envelope: str) -> None:
        self.replay_envelope = replay_envelope
        self.create_calls = 0
        self.candidate_record = None

    def get_by_idempotency_key(self, _key: str):
        return None

    def create_or_replay_complete(self, record):
        self.create_calls += 1
        self.candidate_record = record
        return OperationCreateOutcome(OperationResult.REPLAY, self.replay_envelope)


class _RaceTasks:
    def __init__(self) -> None:
        self.get_calls = 0
        self.replace_calls = 0

    def get(self, _task_id: str):
        self.get_calls += 1
        raise AssertionError("race REPLAY must not read Task")

    def replace(self, *_args, **_kwargs):
        self.replace_calls += 1
        raise AssertionError("race REPLAY must not replace Task")


class _RaceAudit:
    def __init__(self) -> None:
        self.add_calls = 0

    def add_event(self, _event) -> None:
        self.add_calls += 1
        raise AssertionError("race REPLAY must not write Audit")


class _RaceUow:
    def __init__(self, replay_envelope: str) -> None:
        self.operations = _RaceOperations(replay_envelope)
        self.tasks = _RaceTasks()
        self.audit = _RaceAudit()
        self.rollback_calls = 0
        self.close_calls = 0
        self.commit_calls = 0
        self.persisted_business_facts: list[object] = []

    def rollback(self) -> None:
        self.rollback_calls += 1

    def close(self) -> None:
        self.close_calls += 1

    def commit(self) -> None:
        self.commit_calls += 1
        raise AssertionError("race REPLAY must not commit")


def _race_replay_envelope(
    *, artifact_kind: AuthoringArtifactKind, artifact_id: str, revision: int, status: ChapterTaskStatus, operation_kind: OperationKind
) -> str:
    result = AuthoringArtifactSubmissionResult(
        artifact_kind=artifact_kind,
        artifact_ref=ArtifactRef(artifact_id, 1, HASH),
        task_id="task-1",
        aggregate_revision=revision,
        status=status,
        operation_id="winner-operation",
        audit_event_ids=("winner-audit",),
    )
    return create_authoring_submission_result_envelope(
        result, operation_kind=operation_kind
    )


def _counts(settings: SQLitePersistenceSettings) -> dict[str, int]:
    conn = get_connection(settings, read_only=True)
    try:
        return {
            name: conn.execute("SELECT COUNT(*) FROM " + name).fetchone()[0]
            for name in (
                "creation_operation",
                "creation_audit_event",
                "creation_artifact_ref",
            )
        }
    finally:
        conn.close()


def test_c5g0_11_creative_intent_envelope_is_canonical_and_fixed() -> None:
    data = _envelope(AuthoringArtifactKind.CREATIVE_INTENT)
    parsed = parse_authoring_artifact_envelope(data)
    assert parsed.artifact_kind is AuthoringArtifactKind.CREATIVE_INTENT
    assert data == json.dumps(json.loads(data), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def test_c5g0_12_plan_envelope_is_canonical_and_fixed() -> None:
    parsed = parse_authoring_artifact_envelope(_envelope(AuthoringArtifactKind.PLAN))
    assert parsed.artifact_kind is AuthoringArtifactKind.PLAN
    assert parsed.body == "draft body"


def test_c5g0_13_draft_envelope_is_canonical_bytes() -> None:
    data = _envelope()
    assert parse_authoring_artifact_envelope(data).artifact_kind is AuthoringArtifactKind.DRAFT
    assert authoring_artifact_content_hash(data).startswith("sha256:")


def test_c5g0_14_review_envelope_has_only_bound_ref_and_pass() -> None:
    ref = ArtifactRef("draft-1", 1, HASH)
    parsed = parse_authoring_artifact_envelope(
        _envelope(AuthoringArtifactKind.REVIEW, ref=ref)
    )
    assert parsed.reviewed_draft_ref == ref
    assert parsed.verdict == "PASS"


def test_c5g0_15_invalid_encoding_body_bom_nul_and_plain_text_rejected() -> None:
    for data in (b"plain text", b"\xef\xbb\xbf{}", b"{\"body\":\"\x00\"}", b"\xff"):
        with pytest.raises(AuthoringArtifactInputRejected):
            parse_authoring_artifact_envelope(data)


@pytest.mark.parametrize("field", ("project_id", "task_id", "body"))
def test_g0b_corr_10_decoded_nul_is_rejected_for_business_strings(field: str) -> None:
    payload = json.loads(_envelope())
    payload[field] = "value\x00suffix"
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert b"\\u0000" in data
    with pytest.raises(AuthoringArtifactInputRejected):
        parse_authoring_artifact_envelope(data)


def test_g0b_corr_11_review_ref_nul_and_serializer_dto_nul_are_rejected() -> None:
    payload = json.loads(
        _envelope(AuthoringArtifactKind.REVIEW, ref=ArtifactRef("draft-1", 1, HASH))
    )
    payload["reviewed_draft_ref"]["artifact_id"] = "draft\x00suffix"
    escaped = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert b"\\u0000" in escaped
    with pytest.raises(AuthoringArtifactInputRejected):
        parse_authoring_artifact_envelope(escaped)
    raw = escaped.replace(b"\\u0000", b"\x00")
    with pytest.raises(AuthoringArtifactInputRejected):
        parse_authoring_artifact_envelope(raw)

    with pytest.raises(AuthoringArtifactInputRejected):
        serialize_authoring_artifact_envelope(
            AuthoringArtifactEnvelope(
                AuthoringArtifactKind.REVIEW,
                1,
                "project-1",
                1,
                "task-1",
                "review body",
                reviewed_draft_ref=ArtifactRef("draft\x00suffix", 1, HASH),
                verdict="PASS",
            )
        )


def test_c5g0_16_schema_order_extra_field_and_noncanonical_json_rejected() -> None:
    data = json.loads(_envelope())
    data["extra"] = True
    with pytest.raises(AuthoringArtifactInputRejected):
        parse_authoring_artifact_envelope(json.dumps(data).encode())
    noncanonical = b'{"task_id":"task-1","project_id":"project-1","artifact_kind":"DRAFT","artifact_schema_version":1,"chapter_number":1,"body":"draft body"}'
    with pytest.raises(AuthoringArtifactInputRejected):
        parse_authoring_artifact_envelope(noncanonical)


def test_c5g0_17_new_draft_binds_ref_to_exact_envelope_bytes(tmp_path: Path) -> None:
    settings = _init_sqlite(tmp_path)
    fixture = _create_task(settings)
    store = MemoryPayloadStore()
    data = _envelope()
    result = _submit(settings, store, data, "g0b-17", expected_revision=fixture.aggregate_revision)
    assert result.artifact_ref.content_hash == authoring_artifact_content_hash(data)
    assert result.artifact_ref.schema_version == 1
    assert store.objects[result.artifact_ref.content_hash] == data


def test_c5g0_18_caller_ref_hash_and_raw_business_fields_are_rejected() -> None:
    data = json.loads(_envelope())
    data["artifact_ref"] = {"artifact_id": "caller", "schema_version": 1, "content_hash": HASH}
    with pytest.raises(AuthoringArtifactInputRejected):
        parse_authoring_artifact_envelope(json.dumps(data, sort_keys=True, separators=(",", ":")).encode())
    with pytest.raises(AuthoringArtifactInputRejected):
        SubmitAuthoringArtifactUseCase(
            lambda: (_ for _ in ()).throw(AssertionError("DRAFT UoW must not open")),
            object(),  # type: ignore[arg-type]
            MemoryPayloadStore(),
        ).submit(
            SubmitDraftForReviewCommand("task-1", 0, _envelope()),
            DraftReviewSubmissionContext("wrong-stage"),
        )


def test_c5g0_19_draft_ledger_fast_path_replay_and_conflict(tmp_path: Path) -> None:
    settings = _init_sqlite(tmp_path)
    fixture = _create_task(settings)
    first_store = MemoryPayloadStore()
    data = _envelope()
    first = _submit(settings, first_store, data, "g0b-19", expected_revision=fixture.aggregate_revision)
    replay = _submit(settings, NoCallsPayloadStore(), data, "g0b-19", expected_revision=fixture.aggregate_revision, id_factory=_ids())
    assert replay == first
    different = _envelope(body="different")
    with pytest.raises(IdempotencyConflict):
        _submit(settings, NoCallsPayloadStore(), different, "g0b-19", expected_revision=fixture.aggregate_revision, id_factory=_ids())


def test_c5g0_20_only_new_draft_path_puts_and_reads_payload(tmp_path: Path) -> None:
    settings = _init_sqlite(tmp_path)
    fixture = _create_task(settings)
    data = _envelope()
    store = MemoryPayloadStore()
    _submit(settings, store, data, "g0b-20", expected_revision=fixture.aggregate_revision)
    assert store.put_calls == [data]
    assert store.read_calls == [authoring_artifact_content_hash(data)]
    _submit(settings, NoCallsPayloadStore(), data, "g0b-20", expected_revision=fixture.aggregate_revision, id_factory=_ids())


def test_c5g0_21_payload_success_sqlite_failure_leaves_lazy_orphan(tmp_path: Path) -> None:
    settings = _init_sqlite(tmp_path)
    fixture = _create_task(settings)
    baseline = _counts(settings)
    store = MemoryPayloadStore()
    uow = SqliteCreationUnitOfWork(get_connection(settings))
    original_commit = uow.commit
    del original_commit

    def fail_commit() -> None:
        raise OSError("sqlite commit failed")

    uow.commit = fail_commit  # type: ignore[method-assign]
    with pytest.raises(AuthoringArtifactPayloadPersistenceFailed):
        _submit(
            settings,
            store,
            _envelope(),
            "g0b-21",
            expected_revision=fixture.aggregate_revision,
            uow_factory=lambda: uow,
        )
    assert _counts(settings) == baseline
    assert len(store.objects) == 1


def test_c5g0_23_creative_intent_and_task_creation_have_explicit_boundary(tmp_path: Path) -> None:
    settings = _init_sqlite(tmp_path)
    fixture = _create_plan_preparing_task(settings)
    conn = get_connection(settings, read_only=True)
    try:
        row = conn.execute(
            "SELECT status, creative_intent_ref_artifact_id FROM chapter_task WHERE task_id = ?",
            ("task-1",),
        ).fetchone()
    finally:
        conn.close()
    assert row["status"] == ChapterTaskStatus.PLAN_PREPARING.value
    assert row["creative_intent_ref_artifact_id"] == "intent-1"
    assert fixture.creative_intent_ref.content_hash == authoring_artifact_content_hash(
        _envelope(AuthoringArtifactKind.CREATIVE_INTENT, body="creative intent")
    )


def test_c5g0_32_same_draft_request_has_zero_duplicate_facts(tmp_path: Path) -> None:
    settings = _init_sqlite(tmp_path)
    fixture = _create_task(settings)
    data = _envelope()
    store = MemoryPayloadStore()
    first = _submit(settings, store, data, "g0b-32", expected_revision=fixture.aggregate_revision)
    counts = _counts(settings)
    replay = _submit(settings, NoCallsPayloadStore(), data, "g0b-32", expected_revision=fixture.aggregate_revision, id_factory=_ids())
    assert replay.artifact_ref == first.artifact_ref
    assert _counts(settings) == counts


def test_c5g0_32_draft_atomic_race_loser_replay_has_zero_side_effects(
    tmp_path: Path,
) -> None:
    settings = _init_sqlite(tmp_path)
    replay_envelope = _race_replay_envelope(
        artifact_kind=AuthoringArtifactKind.DRAFT,
        artifact_id="winner-draft",
        revision=3,
        status=ChapterTaskStatus.REVIEWING,
        operation_kind=OperationKind.SUBMIT_AUTHORING_ARTIFACT,
    )
    uow = _RaceUow(replay_envelope)
    result = _submit(
        settings,
        NoCallsPayloadStore(),
        _envelope(),
        "g0b-32-draft-race",
        expected_revision=2,
        id_factory=_ids("candidate-operation", "candidate-ref", "candidate-audit"),
        uow_factory=lambda: uow,
    )
    assert result.artifact_ref.artifact_id == "winner-draft"
    assert uow.operations.create_calls == 1
    assert uow.tasks.get_calls == 0
    assert uow.tasks.replace_calls == 0
    assert uow.audit.add_calls == 0
    assert uow.commit_calls == 0
    assert uow.rollback_calls == 1
    assert uow.close_calls == 1
    assert uow.persisted_business_facts == []
