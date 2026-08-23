"""C3 ChangeSet/Intent contracts on the real v003 SQLite path."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pytest

from xiaoshuo.application.creation.author_decision import CreateAuthorDecisionUseCase
from xiaoshuo.application.creation.canon_changeset import (
    BundleDescriptor,
    ChangeSetProposal,
    PrepareCanonChangesetUseCase,
)
from xiaoshuo.application.creation.canon_commands import (
    ApproveCanonChangesetCommand,
    PrepareCanonChangesetCommand,
)
from xiaoshuo.application.creation.canon_decision_context import (
    CanonApproveDeliveryContext,
    CanonPrepareDeliveryContext,
)
from xiaoshuo.application.creation.approve_canon_changeset import ApproveCanonChangesetUseCase
from xiaoshuo.application.creation.commands import CreateAuthorDecisionCommand
from xiaoshuo.application.creation.decision_creation_context import DecisionCreationContext
from xiaoshuo.application.creation.digest import compute_canon_prepare_request_digest, compute_envelope_hash, create_canon_result_envelope, result_from_canon_envelope
from xiaoshuo.application.creation.errors import IdempotencyConflict, LegacyChangesetUnbound, UnsupportedPersistenceBoundary
from xiaoshuo.application.creation.local_author_context import LocalAuthorContextImpl
from xiaoshuo.application.creation.operation_kind import OperationKind
from xiaoshuo.application.creation.ports import CanonBundleIdentity
from xiaoshuo.application.creation.canon_results import CanonChangesetResult
from xiaoshuo.application.creation.repository import OperationLogRecord
from xiaoshuo.domain.creation import ArtifactRef, ChapterTask, ChapterTaskStatus, DecisionType
from xiaoshuo.infrastructure.canon.canonical_bundle import CanonicalBundle
from xiaoshuo.infrastructure.persistence.sqlite.connection import get_connection
from xiaoshuo.infrastructure.persistence.sqlite.maintenance import init_database
from xiaoshuo.infrastructure.persistence.sqlite.migration_runner import MigrationRunner
from xiaoshuo.infrastructure.persistence.sqlite.settings import SQLitePersistenceSettings
from xiaoshuo.infrastructure.persistence.sqlite.uow import SqliteCreationUnitOfWork


def _hash(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class _MemoryPayloadStore:
    def __init__(self) -> None:
        self.items: dict[str, bytes] = {}

    def put(self, data: bytes) -> str:
        digest = _hash(data)
        self.items.setdefault(digest, data)
        if self.items[digest] != data:
            raise RuntimeError("hash collision")
        return digest

    def read(self, digest: str) -> bytes:
        return self.items[digest]


class _UnreadablePayloadStore(_MemoryPayloadStore):
    def read(self, digest: str) -> bytes:
        raise AssertionError(f"payload store read must not occur during replay: {digest}")


class _BundleInspector:
    def inspect(self, data: bytes) -> BundleDescriptor:
        bundle = CanonicalBundle.from_bytes(data)
        return BundleDescriptor(bundle.content_hash(), bundle.manifest_hash, bundle.world_hash)


class _WorldTamperingInspector(_BundleInspector):
    def inspect(self, data: bytes) -> BundleDescriptor:
        descriptor = super().inspect(data)
        return BundleDescriptor(descriptor.content_hash, descriptor.manifest_hash, "sha256:" + "f" * 64)


class _ManifestTamperingInspector(_BundleInspector):
    def inspect(self, data: bytes) -> BundleDescriptor:
        descriptor = super().inspect(data)
        return BundleDescriptor(descriptor.content_hash, "sha256:" + "e" * 64, descriptor.world_hash)


def _ids(*values: str) -> Callable[[], str]:
    iterator = iter(values)
    return lambda: next(iterator)


def _settings(tmp_path: Path) -> SQLitePersistenceSettings:
    return SQLitePersistenceSettings(str(tmp_path / "c3.db"), 5000, str(tmp_path / "backups"))


def _factory(settings: SQLitePersistenceSettings):
    def factory() -> SqliteCreationUnitOfWork:
        return SqliteCreationUnitOfWork(get_connection(settings))
    return factory


class _FailureProxy:
    def __init__(self, delegate, failure_name: str | None) -> None:
        self._delegate = delegate
        self._failure_name = failure_name

    def __getattr__(self, name):
        value = getattr(self._delegate, name)
        if name != self._failure_name:
            return value

        def fail(*_args, **_kwargs):
            raise RuntimeError(f"forced {name} failure")

        return fail


class _ObservedUnitOfWork:
    def __init__(self, settings: SQLitePersistenceSettings, failure: str | None) -> None:
        inner = SqliteCreationUnitOfWork(get_connection(settings))
        self._inner = inner
        self.rollback_calls = 0
        self.close_calls = 0
        self.tasks = inner.tasks
        self.operations = _FailureProxy(
            inner.operations, "create_or_replay_complete" if failure == "operation" else None
        )
        self.audit = _FailureProxy(inner.audit, "add_event" if failure == "audit" else None)
        self.decisions = _FailureProxy(
            inner.decisions, "add_consumption" if failure == "consumption" else None
        )
        self.canon = _FailureProxy(inner.canon, "create_intent" if failure == "intent" else None)
        self._failure = failure

    def commit(self) -> None:
        if self._failure == "commit":
            raise RuntimeError("forced commit failure")
        self._inner.commit()

    def rollback(self) -> None:
        self.rollback_calls += 1
        self._inner.rollback()

    def close(self) -> None:
        self.close_calls += 1
        self._inner.close()


class _ObservedFactory:
    def __init__(self, settings: SQLitePersistenceSettings, failure: str | None) -> None:
        self._settings = settings
        self._failure = failure
        self.last: _ObservedUnitOfWork | None = None

    def __call__(self) -> _ObservedUnitOfWork:
        self.last = _ObservedUnitOfWork(self._settings, self._failure)
        return self.last


def _ref(name: str) -> ArtifactRef:
    return ArtifactRef(name, 1, "sha256:" + name.encode().hex().ljust(64, "0")[:64])


def _seed_task(settings: SQLitePersistenceSettings) -> None:
    now = datetime.now(timezone.utc)
    task = ChapterTask(
        task_id="task-c3", schema_version=1, aggregate_revision=4,
        project_id="project-c3", chapter_number=1,
        status=ChapterTaskStatus.CHANGESET_PREPARING,
        last_stable_status=ChapterTaskStatus.CHANGESET_PREPARING,
        creative_intent_ref=_ref("intent"), confirmed_plan_ref=_ref("plan"),
        current_author_draft_ref=_ref("draft"), review_target_draft_ref=_ref("review-target"),
        adopted_draft_ref=_ref("adopted"), latest_review_ref=_ref("review"),
        pending_changeset_ref=None, commit_receipt_ref=None, recovery=None,
        created_at=now, updated_at=now,
    )
    conn = get_connection(settings)
    conn.execute(
        "INSERT INTO creation_artifact_ref (artifact_id, schema_version, content_hash) VALUES (?, ?, ?)",
        ("base-bundle", 1, CanonicalBundle(1, b'{\"revision\":0}', b"# base\n").content_hash()),
    )
    conn.commit()
    conn.close()
    uow = SqliteCreationUnitOfWork(get_connection(settings))
    try:
        uow.tasks.add(task)
        uow.commit()
    finally:
        uow.close()


def _count(settings: SQLitePersistenceSettings) -> dict[str, int]:
    conn = get_connection(settings)
    try:
        return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in (
            "chapter_task", "creation_operation", "creation_audit_event",
            "creation_decision_consumption", "canon_commit_journal", "creation_artifact_ref",
        )}
    finally:
        conn.close()


def _bundle() -> bytes:
    return CanonicalBundle(1, b'{"revision":1}', b"# world\n").to_bytes()


class _ActivationReader:
    def __init__(self) -> None:
        bundle = CanonicalBundle(1, b'{"revision":0}', b"# base\n")
        self.identity = CanonBundleIdentity(
            project_id="project-c3", version_id="base-v1", bundle_ref=ArtifactRef("base-bundle", 1, bundle.content_hash()),
            bundle_content_hash=bundle.content_hash(), manifest_hash=bundle.manifest_hash,
            world_hash=bundle.world_hash,
        )

    def read_for_project(self, project_id: str) -> CanonBundleIdentity:
        assert project_id == self.identity.project_id
        return self.identity


def _prepare(settings, store, *, ids=("bundle-1", "changeset-1", "prepare-op", "prepare-event")):
    return PrepareCanonChangesetUseCase(
        _factory(settings), LocalAuthorContextImpl("author-c3"), store, _BundleInspector(), id_factory=_ids(*ids), activation_reader=_ActivationReader()
    ).prepare(
        PrepareCanonChangesetCommand("task-c3", 4, _bundle()),
        CanonPrepareDeliveryContext("prepare-delivery-key"),
    )


def _decision(settings, ref):
    return CreateAuthorDecisionUseCase(
        _factory(settings), LocalAuthorContextImpl("author-c3"), id_factory=_ids("decision-1", "decision-create-op")
    ).create(
        CreateAuthorDecisionCommand("task-c3", DecisionType.APPROVE_CHANGESET, ref, 5),
        DecisionCreationContext("decision-delivery-key"),
    )


def _approve(settings, store, *, key="approve-delivery-key", revision=5, ids=("approve-op", "intent-event", "consumption", "journal")):
    return ApproveCanonChangesetUseCase(
        _factory(settings), LocalAuthorContextImpl("author-c3"), store, _BundleInspector(), id_factory=_ids(*ids), activation_reader=_ActivationReader()
    ).approve(ApproveCanonChangesetCommand("task-c3", "decision-1", revision), CanonApproveDeliveryContext(key))


def _raw_envelope(settings: SQLitePersistenceSettings, key: str) -> str:
    conn = get_connection(settings)
    try:
        row = conn.execute(
            "SELECT result_envelope_json FROM creation_operation WHERE idempotency_key = ?",
            (key,),
        ).fetchone()
        assert row is not None
        return row["result_envelope_json"]
    finally:
        conn.close()


def _seed_historical_v1_operation(settings: SQLitePersistenceSettings, key: str) -> str:
    command = PrepareCanonChangesetCommand("task-c3", 4, _bundle(), 1, "sha256:" + "a" * 64)
    changeset_ref = _ref("legacy-changeset")
    target_ref = _ref("legacy-bundle")
    result = CanonChangesetResult(
        "task-c3", 5, ChapterTaskStatus.CHANGESET_APPROVAL_PENDING,
        changeset_ref, target_ref, "sha256:" + "a" * 64, "sha256:" + "b" * 64,
    )
    envelope = create_canon_result_envelope(
        result,
        operation_kind=OperationKind.PREPARE_CANON_CHANGESET,
        original_operation_id="legacy-operation",
        audit_event_ids=("legacy-event",),
    )
    digest = compute_canon_prepare_request_digest(
        command, _hash(command.target_bundle_bytes), OperationKind.PREPARE_CANON_CHANGESET
    )
    conn = get_connection(settings)
    try:
        conn.execute(
            "INSERT INTO creation_operation (operation_id,idempotency_key,request_digest,result_envelope_json,result_envelope_hash,created_at) VALUES (?,?,?,?,?,?)",
            ("legacy-operation", key, digest, envelope, compute_envelope_hash(envelope), "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()
    finally:
        conn.close()
    return envelope


@pytest.fixture
def prepared(tmp_path: Path):
    settings = _settings(tmp_path)
    init_database(settings)
    conn = get_connection(settings)
    try:
        MigrationRunner().migrate(conn, settings)
    finally:
        conn.close()
    _seed_task(settings)
    store = _MemoryPayloadStore()
    result = _prepare(settings, store)
    return settings, store, result


def test_prepare_creates_only_proposal_task_operation_and_audit(prepared) -> None:
    settings, _store, result = prepared
    assert result.status is ChapterTaskStatus.CHANGESET_APPROVAL_PENDING
    assert result.journal_id is None
    counts = _count(settings)
    assert counts["creation_operation"] == 1
    assert counts["creation_audit_event"] == 1
    assert counts["creation_decision_consumption"] == 0
    assert counts["canon_commit_journal"] == 0
    conn = get_connection(settings)
    try:
        row = conn.execute("SELECT status, pending_changeset_ref_artifact_id FROM chapter_task WHERE task_id='task-c3'").fetchone()
        assert tuple(row) == ("CHANGESET_APPROVAL_PENDING", result.changeset_ref.artifact_id)
    finally:
        conn.close()


def test_approve_creates_atomic_intent_and_preserves_all_seven_role_refs(prepared) -> None:
    settings, store, prepared_result = prepared
    _decision(settings, prepared_result.changeset_ref)
    before = _count(settings)
    result = _approve(settings, store)
    assert result.status is ChapterTaskStatus.COMMITTING
    assert result.journal_id == "journal"
    conn = get_connection(settings)
    try:
        task = conn.execute("SELECT * FROM chapter_task WHERE task_id='task-c3'").fetchone()
        assert task["status"] == "COMMITTING" and task["aggregate_revision"] == 6
        assert [task[name] for name in (
            "creative_intent_ref_artifact_id", "confirmed_plan_ref_artifact_id", "current_author_draft_ref_artifact_id",
            "review_target_draft_ref_artifact_id", "adopted_draft_ref_artifact_id", "latest_review_ref_artifact_id", "pending_changeset_ref_artifact_id",
        )] == ["intent", "plan", "draft", "review-target", "adopted", "review", "changeset-1"]
        audit = conn.execute("SELECT actor_kind, actor_id, event_type FROM creation_audit_event WHERE event_type='CANON_COMMIT_INTENT_CREATED'").fetchone()
        assert tuple(audit) == ("AUTHOR", "author-c3", "CANON_COMMIT_INTENT_CREATED")
        assert conn.execute("SELECT COUNT(*) FROM creation_audit_event_object_ref WHERE event_id='intent-event'").fetchone()[0] == 7
        journal = conn.execute("SELECT decision_id, changeset_ref_artifact_id, target_bundle_ref_artifact_id FROM canon_commit_journal").fetchone()
        assert tuple(journal) == ("decision-1", "changeset-1", "bundle-1")
    finally:
        conn.close()
    after = _count(settings)
    assert after["creation_operation"] == before["creation_operation"] + 1
    assert after["creation_audit_event"] == before["creation_audit_event"] + 1
    assert after["creation_decision_consumption"] == 1 and after["canon_commit_journal"] == 1


def test_invalid_decision_or_stale_revision_leaves_intent_facts_at_zero(prepared) -> None:
    settings, store, prepared_result = prepared
    _decision(settings, prepared_result.changeset_ref)
    before = _count(settings)
    with pytest.raises(Exception):
        _approve(settings, store, revision=4)
    assert _count(settings) == before


def test_approve_replay_is_original_envelope_and_conflict_has_no_new_facts(prepared) -> None:
    settings, store, prepared_result = prepared
    _decision(settings, prepared_result.changeset_ref)
    first = _approve(settings, store)
    counts = _count(settings)
    replay = _approve(settings, store, ids=("should-not", "be-called", "on-replay", "x"))
    assert replay == first
    assert _count(settings) == counts
    with pytest.raises(IdempotencyConflict):
        _approve(settings, store, revision=6)
    assert _count(settings) == counts


def test_prepare_replay_is_ledger_first_when_payload_store_is_unreadable(prepared) -> None:
    settings, store, first = prepared
    counts = _count(settings)
    unreadable = _UnreadablePayloadStore()
    replay = PrepareCanonChangesetUseCase(
        _factory(settings), LocalAuthorContextImpl("author-c3"), unreadable, _BundleInspector(),
        id_factory=lambda: (_ for _ in ()).throw(AssertionError("id factory must not run on replay")),
        activation_reader=_ActivationReader(),
    ).prepare(
        PrepareCanonChangesetCommand("task-c3", 4, _bundle()),
        CanonPrepareDeliveryContext("prepare-delivery-key"),
    )
    assert replay == first
    assert _count(settings) == counts


def test_v1_historical_replay_returns_original_envelope_without_reads_or_new_facts(prepared) -> None:
    settings, _store, _first = prepared
    raw = _seed_historical_v1_operation(settings, "legacy-replay-key")
    counts = _count(settings)
    use_case = PrepareCanonChangesetUseCase(
        _factory(settings),
        LocalAuthorContextImpl("author-c3"),
        _UnreadablePayloadStore(),
        _BundleInspector(),
        id_factory=lambda: (_ for _ in ()).throw(AssertionError("id factory must not run during v1 replay")),
        activation_reader=lambda: (_ for _ in ()).throw(AssertionError("activation must not be read during v1 replay")),
    )
    command = PrepareCanonChangesetCommand("task-c3", 4, _bundle(), 1, "sha256:" + "a" * 64)
    replay = use_case.prepare(command, CanonPrepareDeliveryContext("legacy-replay-key"))
    assert replay == result_from_canon_envelope(
        raw, expected_task_id="task-c3", expected_kind=OperationKind.PREPARE_CANON_CHANGESET
    )
    assert _raw_envelope(settings, "legacy-replay-key") == raw
    assert _count(settings) == counts


def test_v1_pending_fails_closed_before_task_payload_or_identity_access(prepared) -> None:
    settings, _store, _first = prepared
    counts = _count(settings)
    use_case = PrepareCanonChangesetUseCase(
        _factory(settings),
        LocalAuthorContextImpl("author-c3"),
        _UnreadablePayloadStore(),
        _BundleInspector(),
        id_factory=lambda: (_ for _ in ()).throw(AssertionError("id factory must not run for pending v1")),
        activation_reader=lambda: (_ for _ in ()).throw(AssertionError("activation must not be read for pending v1")),
    )
    with pytest.raises(LegacyChangesetUnbound, match="historical operation"):
        use_case.prepare(
            PrepareCanonChangesetCommand("task-c3", 4, _bundle(), 1, "sha256:" + "a" * 64),
            CanonPrepareDeliveryContext("legacy-pending-key"),
        )
    assert _count(settings) == counts


def test_v1_and_v2_same_key_are_idempotency_conflicts(prepared) -> None:
    settings, _store, _first = prepared
    _seed_historical_v1_operation(settings, "version-conflict-key")
    counts = _count(settings)
    with pytest.raises(IdempotencyConflict):
        PrepareCanonChangesetUseCase(
            _factory(settings),
            LocalAuthorContextImpl("author-c3"),
            _UnreadablePayloadStore(),
            _BundleInspector(),
            id_factory=lambda: (_ for _ in ()).throw(AssertionError("id factory must not run on conflict")),
            activation_reader=lambda: (_ for _ in ()).throw(AssertionError("activation must not be read on conflict")),
        ).prepare(
            PrepareCanonChangesetCommand("task-c3", 4, _bundle()),
            CanonPrepareDeliveryContext("version-conflict-key"),
        )
    assert _count(settings) == counts


def test_v2_missing_target_world_hash_fails_closed_without_residue(prepared) -> None:
    settings, _store, _first = prepared

    class MissingWorldInspector(_BundleInspector):
        def inspect(self, data: bytes) -> BundleDescriptor:
            descriptor = super().inspect(data)
            return BundleDescriptor(descriptor.content_hash, descriptor.manifest_hash, None)

    before = _count(settings)
    with pytest.raises(UnsupportedPersistenceBoundary, match="identity"):
        PrepareCanonChangesetUseCase(
            _factory(settings), LocalAuthorContextImpl("author-c3"), _MemoryPayloadStore(), MissingWorldInspector(),
            activation_reader=_ActivationReader(),
        ).prepare(
            PrepareCanonChangesetCommand("task-c3", 4, _bundle()),
            CanonPrepareDeliveryContext("missing-world-key"),
        )
    assert _count(settings) == before


@pytest.mark.parametrize("field,value", [("base_world_hash", None), ("target_world_hash", None), ("bundle_schema_version", True), ("bundle_schema_version", 2)])
def test_v2_changeset_deserialization_rejects_incomplete_or_unsupported_identity(field: str, value) -> None:
    base = _ActivationReader().identity
    proposal = ChangeSetProposal(
        task_id="task-c3", prepared_task_revision=5, adopted_draft_ref=_ref("adopted"),
        target_bundle_ref=_ref("target"), base_manifest_hash=base.manifest_hash,
        target_manifest_hash=base.manifest_hash, schema_version=2,
        base_bundle_ref=base.bundle_ref, base_bundle_content_hash=base.bundle_content_hash,
        base_world_hash=base.world_hash, base_project_id=base.project_id,
        base_version_id=base.version_id, bundle_schema_version=1,
        target_world_hash=base.world_hash,
    )
    payload = json.loads(proposal.to_bytes())
    payload[field] = value
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(UnsupportedPersistenceBoundary):
        ChangeSetProposal.from_bytes(data)


def test_approve_rejects_world_only_and_manifest_only_target_identity_tamper(prepared) -> None:
    settings, store, prepared_result = prepared
    _decision(settings, prepared_result.changeset_ref)
    before = _count(settings)
    for inspector in (_WorldTamperingInspector(), _ManifestTamperingInspector()):
        with pytest.raises(UnsupportedPersistenceBoundary, match="revalidate"):
            ApproveCanonChangesetUseCase(
                _factory(settings), LocalAuthorContextImpl("author-c3"), store, inspector,
                activation_reader=_ActivationReader(),
            ).approve(
                ApproveCanonChangesetCommand("task-c3", "decision-1", 5),
                CanonApproveDeliveryContext("tamper-" + inspector.__class__.__name__),
            )
        assert _count(settings) == before


def test_approve_replay_and_conflict_are_ledger_first_when_store_is_unreadable(prepared) -> None:
    settings, store, prepared_result = prepared
    _decision(settings, prepared_result.changeset_ref)
    first = _approve(settings, store)
    counts = _count(settings)
    unreadable = _UnreadablePayloadStore()
    replay = ApproveCanonChangesetUseCase(
        _factory(settings), LocalAuthorContextImpl("author-c3"), unreadable, _BundleInspector(),
        id_factory=lambda: (_ for _ in ()).throw(AssertionError("id factory must not run on replay")),
    ).approve(ApproveCanonChangesetCommand("task-c3", "decision-1", 5), CanonApproveDeliveryContext("approve-delivery-key"))
    assert replay == first and _count(settings) == counts
    with pytest.raises(IdempotencyConflict):
        ApproveCanonChangesetUseCase(
            _factory(settings), LocalAuthorContextImpl("author-c3"), unreadable, _BundleInspector(),
            activation_reader=_ActivationReader(),
        ).approve(ApproveCanonChangesetCommand("task-c3", "decision-1", 6), CanonApproveDeliveryContext("approve-delivery-key"))
    assert _count(settings) == counts


def test_prepare_replay_preserves_raw_database_envelope_and_uow_lifecycle(prepared) -> None:
    settings, _store, first = prepared
    raw = _raw_envelope(settings, "prepare-delivery-key")
    counts = _count(settings)
    factory = _ObservedFactory(settings, None)
    result = PrepareCanonChangesetUseCase(
        factory,
        LocalAuthorContextImpl("author-c3"),
        _UnreadablePayloadStore(),
        _BundleInspector(),
        id_factory=lambda: (_ for _ in ()).throw(AssertionError("id factory must not run")),
        activation_reader=_ActivationReader(),
    ).prepare(
        PrepareCanonChangesetCommand("task-c3", 4, _bundle()),
        CanonPrepareDeliveryContext("prepare-delivery-key"),
    )
    assert result == result_from_canon_envelope(
        raw, expected_task_id="task-c3", expected_kind=OperationKind.PREPARE_CANON_CHANGESET
    )
    assert result == first
    assert _raw_envelope(settings, "prepare-delivery-key") == raw
    assert _count(settings) == counts
    assert factory.last is not None
    assert factory.last.rollback_calls == 1
    assert factory.last.close_calls == 1


def test_prepare_conflict_is_ledger_first_and_has_exactly_one_rollback_close(prepared) -> None:
    settings, _store, _first = prepared
    counts = _count(settings)
    factory = _ObservedFactory(settings, None)
    with pytest.raises(IdempotencyConflict):
        PrepareCanonChangesetUseCase(
            factory,
            LocalAuthorContextImpl("author-c3"),
            _UnreadablePayloadStore(),
            _BundleInspector(),
            id_factory=lambda: (_ for _ in ()).throw(AssertionError("id factory must not run")),
            activation_reader=_ActivationReader(),
        ).prepare(
            PrepareCanonChangesetCommand("task-c3", 4, CanonicalBundle(1, b'{"revision":2}', b"# world\n").to_bytes()),
            CanonPrepareDeliveryContext("prepare-delivery-key"),
        )
    assert _count(settings) == counts
    assert factory.last is not None
    assert factory.last.rollback_calls == 1
    assert factory.last.close_calls == 1


def test_approve_replay_preserves_raw_database_envelope_and_uow_lifecycle(prepared) -> None:
    settings, store, prepared_result = prepared
    _decision(settings, prepared_result.changeset_ref)
    first = _approve(settings, store)
    raw = _raw_envelope(settings, "approve-delivery-key")
    counts = _count(settings)
    factory = _ObservedFactory(settings, None)
    result = ApproveCanonChangesetUseCase(
        factory,
        LocalAuthorContextImpl("author-c3"),
        _UnreadablePayloadStore(),
        _BundleInspector(),
        id_factory=lambda: (_ for _ in ()).throw(AssertionError("id factory must not run")),
    ).approve(
        ApproveCanonChangesetCommand("task-c3", "decision-1", 5),
        CanonApproveDeliveryContext("approve-delivery-key"),
    )
    assert result == result_from_canon_envelope(
        raw, expected_task_id="task-c3", expected_kind=OperationKind.APPROVE_CANON_CHANGESET
    )
    assert result == first
    assert _raw_envelope(settings, "approve-delivery-key") == raw
    assert _count(settings) == counts
    assert factory.last is not None
    assert factory.last.rollback_calls == 1
    assert factory.last.close_calls == 1


def test_approve_conflict_is_ledger_first_and_has_exactly_one_rollback_close(prepared) -> None:
    settings, store, prepared_result = prepared
    _decision(settings, prepared_result.changeset_ref)
    _approve(settings, store)
    counts = _count(settings)
    factory = _ObservedFactory(settings, None)
    with pytest.raises(IdempotencyConflict):
        ApproveCanonChangesetUseCase(
            factory,
            LocalAuthorContextImpl("author-c3"),
            _UnreadablePayloadStore(),
            _BundleInspector(),
            id_factory=lambda: (_ for _ in ()).throw(AssertionError("id factory must not run")),
        ).approve(
            ApproveCanonChangesetCommand("task-c3", "decision-1", 6),
            CanonApproveDeliveryContext("approve-delivery-key"),
        )
    assert _count(settings) == counts
    assert factory.last is not None
    assert factory.last.rollback_calls == 1
    assert factory.last.close_calls == 1


@pytest.mark.parametrize("failure", ["operation", "audit", "consumption", "intent", "commit"])
def test_approve_failure_points_rollback_and_close_once_without_business_residue(prepared, failure: str) -> None:
    settings, store, prepared_result = prepared
    _decision(settings, prepared_result.changeset_ref)
    before = _count(settings)
    factory = _ObservedFactory(settings, failure)
    with pytest.raises(RuntimeError, match="forced"):
        ApproveCanonChangesetUseCase(
            factory, LocalAuthorContextImpl("author-c3"), store, _BundleInspector(), id_factory=_ids(
                f"{failure}-operation", f"{failure}-event", f"{failure}-consumption", f"{failure}-journal"
            ), activation_reader=_ActivationReader()
        ).approve(
            ApproveCanonChangesetCommand("task-c3", "decision-1", 5),
            CanonApproveDeliveryContext(f"{failure}-delivery-key"),
        )
    assert _count(settings) == before
    assert factory.last is not None
    assert factory.last.rollback_calls == 1
    assert factory.last.close_calls == 1


def test_author_decision_creation_rejects_wrong_target_and_caller_identity_is_not_an_input(prepared) -> None:
    settings, _store, _prepared_result = prepared
    wrong = _ref("wrong")
    with pytest.raises(UnsupportedPersistenceBoundary):
        CreateAuthorDecisionUseCase(_factory(settings), LocalAuthorContextImpl("author-c3"), id_factory=_ids("d", "o")).create(
            CreateAuthorDecisionCommand("task-c3", DecisionType.APPROVE_CHANGESET, wrong, 5),
            DecisionCreationContext("new-decision-key"),
        )
