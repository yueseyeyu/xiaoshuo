"""C4A-25..30 and C4A-45..48/C4A-52: controlled Apply contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from xiaoshuo.application.creation.canon_apply import CanonApplyCommand
from xiaoshuo.application.creation.canon_apply import compute_canon_apply_request_digest
from xiaoshuo.application.creation.canon_apply_context import CanonApplyDeliveryContext
from xiaoshuo.application.creation.errors import (
    CanonApplyCommittedLeaseReleaseUncertain,
    CanonApplyConflict,
    CanonApplyRecoveryRequired,
    IdempotencyConflict,
)
from xiaoshuo.domain.creation import ArtifactRef, ChapterTaskStatus
from xiaoshuo.infrastructure.canon.c4a_apply import C4aApplyService
from xiaoshuo.infrastructure.canon.c4a_recovery import C4aRecoveryService
from xiaoshuo.infrastructure.canon.canon_mvp_c4_composition import CanonMvpC4ApplicationScope
from xiaoshuo.infrastructure.canon.c4a_projection_commit_lock import (
    C4aProjectionCommitLock,
)
from xiaoshuo.infrastructure.canon.c4a_projection_writer import (
    C4aProjectionIdentity,
    C4aProjectionWriter,
    C4aProjectionWriterError,
)
from xiaoshuo.infrastructure.canon.canonical_bundle import CanonicalBundle
from xiaoshuo.infrastructure.persistence.sqlite.c4a_apply_repository import (
    C4aApplyAttempt,
    SqliteC4aApplyRepository,
)
from xiaoshuo.infrastructure.persistence.sqlite.connection import get_connection
from xiaoshuo.infrastructure.persistence.sqlite.maintenance import init_database
from xiaoshuo.infrastructure.persistence.sqlite.migration_runner import MigrationRunner
from xiaoshuo.infrastructure.persistence.sqlite.settings import SQLitePersistenceSettings


HASH = "sha256:" + "a" * 64


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


class MemoryPayloadStore:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.put_calls = 0
        self.read_calls = 0

    def put(self, data: bytes) -> str:
        self.put_calls += 1
        digest = _digest(data)
        self.values[digest] = data
        return digest

    def read(self, digest: str) -> bytes:
        self.read_calls += 1
        return self.values[digest]


class FileActivationReader:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.read_calls = 0

    def read_for_project(self, project_id: str):
        self.read_calls += 1
        pointer_path = self.root / "current.pointer"
        marker_path = self.root / "activation.marker"
        pointer_bytes = pointer_path.read_bytes()
        pointer = json.loads(pointer_bytes.decode("utf-8"))
        marker = json.loads(marker_path.read_bytes().decode("utf-8"))
        if marker["pointer_content_hash"] != _digest(pointer_bytes):
            raise RuntimeError("marker/pointer mismatch")
        if pointer["project_id"] != project_id or marker["project_id"] != project_id:
            raise RuntimeError("project mismatch")
        version_dir = self.root / "versions" / pointer["version_id"]
        identity = json.loads((version_dir / "bundle.identity.json").read_text(encoding="utf-8"))
        if identity != {key: pointer[key] for key in identity}:
            raise RuntimeError("version identity mismatch")
        from xiaoshuo.infrastructure.canon.projection_activation import ActivationIdentity

        return ActivationIdentity(
            project_id=pointer["project_id"],
            version_id=pointer["version_id"],
            bundle_schema_version=pointer["bundle_schema_version"],
            bundle_ref_artifact_id=pointer["bundle_ref_artifact_id"],
            bundle_content_hash=pointer["bundle_content_hash"],
            manifest_hash=pointer["manifest_hash"],
            world_hash=pointer["world_hash"],
        )


def _write_activation(root: Path, bundle: CanonicalBundle, identity: C4aProjectionIdentity) -> None:
    root.mkdir(parents=True)
    versions = root / "versions"
    versions.mkdir()
    version = versions / identity.version_id
    version.mkdir()
    (version / "bundle.identity.json").write_bytes(C4aProjectionWriter.identity_bytes(identity))
    (version / "manifest.json").write_bytes(bundle.manifest)
    (version / "world.md").write_bytes(bundle.world_md)
    pointer = C4aProjectionWriter.pointer_bytes(identity)
    (root / "current.pointer").write_bytes(pointer)
    (root / "activation.marker").write_bytes(C4aProjectionWriter.marker_bytes(identity, pointer))


def _case(tmp_path: Path):
    settings = SQLitePersistenceSettings(tmp_path / "c4a.db", 5000, tmp_path / "backups")
    init_database(settings)
    conn = get_connection(settings)
    MigrationRunner().migrate(conn, settings)

    manifest_base = _json({"manifest_schema_version": 1, "project_id": "project", "revision": "base"})
    world_base = b"base world\n"
    manifest_target = _json({"manifest_schema_version": 1, "project_id": "project", "revision": "target"})
    world_target = b"target world\n"
    base_bundle = CanonicalBundle(1, manifest_base, world_base)
    target_bundle = CanonicalBundle(1, manifest_target, world_target)
    base_ref = ArtifactRef("base-bundle", 1, base_bundle.content_hash())
    target_ref = ArtifactRef("target-bundle", 1, target_bundle.content_hash())
    base_identity = C4aProjectionIdentity("project", "base-v1", base_ref, base_bundle.manifest_hash, base_bundle.world_hash)
    root = tmp_path / "projection"
    _write_activation(root, base_bundle, base_identity)
    payload = MemoryPayloadStore()
    payload.values[target_bundle.content_hash()] = target_bundle.to_bytes()

    refs = [
        ("creative", 1, HASH),
        ("changeset", 1, HASH),
        (base_ref.artifact_id, base_ref.schema_version, base_ref.content_hash),
        (target_ref.artifact_id, target_ref.schema_version, target_ref.content_hash),
    ]
    conn.executemany("INSERT INTO creation_artifact_ref VALUES (?, ?, ?)", refs)
    conn.execute(
        "INSERT INTO creation_operation VALUES (?, ?, ?, ?, ?, ?)",
        ("op", "op-key", HASH, "{}", _digest(b"{}"), "2026-08-04T00:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO chapter_task (task_id, schema_version, aggregate_revision, project_id, chapter_number, status, last_stable_status, creative_intent_ref_artifact_id, confirmed_plan_ref_artifact_id, current_author_draft_ref_artifact_id, review_target_draft_ref_artifact_id, adopted_draft_ref_artifact_id, latest_review_ref_artifact_id, pending_changeset_ref_artifact_id, commit_receipt_ref_artifact_id, recovery_failed_operation_id, recovery_error_code, recovery_retry_from_status, created_at, updated_at) VALUES (?,1,5,'project',1,'COMMITTING','COMMITTING','creative',NULL,NULL,NULL,NULL,NULL,'changeset',NULL,NULL,NULL,NULL,?,?)",
        ("task", "2026-08-04T00:00:00+00:00", "2026-08-04T00:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO creation_author_decision (decision_id, schema_version, task_id, decision_type, target_ref_artifact_id, outcome, based_on_task_revision, author_id, reason, actor_kind, actor_id, content_hash, created_at) VALUES (?,1,?,'APPROVE_CHANGESET',?,'APPROVE',5,'author',NULL,'AUTHOR','author',?,?)",
        ("decision", "task", "changeset", HASH, "2026-08-04T00:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO canon_commit_journal (journal_id,task_id,operation_id,decision_id,changeset_ref_artifact_id,base_bundle_ref_artifact_id,target_bundle_ref_artifact_id,base_bundle_content_hash,target_bundle_content_hash,base_manifest_hash,base_world_hash,target_manifest_hash,target_world_hash,canonical_bundle_schema_version,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("journal", "task", "op", "decision", "changeset", "base-bundle", "target-bundle", base_ref.content_hash, target_ref.content_hash, base_bundle.manifest_hash, base_bundle.world_hash, target_bundle.manifest_hash, target_bundle.world_hash, 1, "2026-08-04T00:00:00+00:00"),
    )
    conn.commit()
    reader = FileActivationReader(root)
    repo = SqliteC4aApplyRepository(conn)
    return {
        "conn": conn,
        "settings": settings,
        "root": root,
        "reader": reader,
        "repo": repo,
        "payload": payload,
        "base": base_bundle,
        "target": target_bundle,
        "base_ref": base_ref,
        "target_ref": target_ref,
    }


def _service(case, operator_identity: str = "maintenance-operator", **kwargs):
    return C4aApplyService(
        case["conn"],
        operator_identity=operator_identity,
        projection_root=case["root"],
        payload_store=case["payload"],
        repository=case["repo"],
        activation_reader=case["reader"],
        enforce_persistent_d_drive=False,
        **kwargs,
    )


def _command(key: str = "apply-key", journal: str = "journal") -> CanonApplyCommand:
    return CanonApplyCommand("task", journal, 5, apply_key=key)


def _context(key: str = "apply-key") -> CanonApplyDeliveryContext:
    return CanonApplyDeliveryContext(key)


def test_apply_records_prepared_version_pointer_marker_projection_order(tmp_path: Path) -> None:
    case = _case(tmp_path)
    result = _service(case).apply(_command(), _context())
    phases = [row[0] for row in case["conn"].execute("SELECT phase FROM canon_apply_event ORDER BY rowid")]
    assert phases == ["PREPARED", "VERSION_READY", "POINTER_WRITE_INTENDED", "POINTER_INSTALLED", "MARKER_WRITE_INTENDED", "PROJECTION_COMMITTED", "RECEIPT_PAYLOAD_READY", "COMPLETED"]
    observations = {
        row[0]: (row[1], row[2])
        for row in case["conn"].execute(
            "SELECT phase, observed_pointer_content_hash, observed_marker_content_hash "
            "FROM canon_apply_event"
        )
    }
    assert observations["PREPARED"] == (None, None)
    assert observations["VERSION_READY"] == (None, None)
    assert observations["POINTER_WRITE_INTENDED"] == (None, None)
    assert observations["POINTER_INSTALLED"] == (None, None)
    assert observations["MARKER_WRITE_INTENDED"] == (None, None)
    target_hashes = (
        _digest((case["root"] / "current.pointer").read_bytes()),
        _digest((case["root"] / "activation.marker").read_bytes()),
    )
    assert observations["PROJECTION_COMMITTED"] == target_hashes
    assert observations["RECEIPT_PAYLOAD_READY"] == target_hashes
    assert observations["COMPLETED"] == target_hashes
    assert result.status is ChapterTaskStatus.COMPLETED


def test_completed_graph_evidence_is_typed_logical_read_only_binding(tmp_path: Path) -> None:
    case = _case(tmp_path)
    service = _service(case)
    service.apply(_command(), _context())
    evidence = case["repo"].verify_completed_graph(
        project_id="project",
        task_id="task",
        apply_key="apply-key",
        request_digest=compute_canon_apply_request_digest(_command()),
    )
    assert evidence.phases == (
        "PREPARED",
        "VERSION_READY",
        "POINTER_WRITE_INTENDED",
        "POINTER_INSTALLED",
        "MARKER_WRITE_INTENDED",
        "PROJECTION_COMMITTED",
        "RECEIPT_PAYLOAD_READY",
        "COMPLETED",
    )
    assert evidence.read_only is True
    assert evidence.physical_order_proven is False
    assert evidence.project_id == "project"
    assert evidence.operator_identity == "maintenance-operator"
    assert evidence.task_id == "task"
    assert evidence.receipt_ref.content_hash == evidence.envelope_hash


def test_composition_verifier_rechecks_projection_after_completion(tmp_path: Path) -> None:
    case = _case(tmp_path)
    _service(case, operator_identity="local-author").apply(_command(), _context())
    scope = object.__new__(CanonMvpC4ApplicationScope)
    scope.binding = SimpleNamespace(operator_identity="local-author")
    scope.uow = SimpleNamespace(repository=case["repo"])
    scope.payload_store = case["payload"]
    scope._recovery = C4aRecoveryService(
        case["conn"],
        projection_root=case["root"],
        payload_store=case["payload"],
        repository=case["repo"],
        activation_reader=case["reader"],
        enforce_persistent_d_drive=False,
    )
    before_events = case["conn"].execute("SELECT COUNT(*) FROM canon_apply_event").fetchone()[0]
    before_puts = case["payload"].put_calls
    pointer_before = (case["root"] / "current.pointer").read_bytes()
    marker_before = (case["root"] / "activation.marker").read_bytes()
    scope.verify_completed_graph(
        project_id="project", task_id="task", apply_key="apply-key",
        request_digest=compute_canon_apply_request_digest(_command()),
    )
    (case["root"] / "current.pointer").write_bytes(b"tampered")
    with pytest.raises(CanonApplyRecoveryRequired):
        scope.verify_completed_graph(
            project_id="project", task_id="task", apply_key="apply-key",
            request_digest=compute_canon_apply_request_digest(_command()),
        )
    (case["root"] / "current.pointer").write_bytes(pointer_before)
    (case["root"] / "activation.marker").write_bytes(b"tampered")
    with pytest.raises(CanonApplyRecoveryRequired):
        scope.verify_completed_graph(
            project_id="project", task_id="task", apply_key="apply-key",
            request_digest=compute_canon_apply_request_digest(_command()),
        )
    (case["root"] / "activation.marker").write_bytes(marker_before)
    assert case["conn"].execute("SELECT COUNT(*) FROM canon_apply_event").fetchone()[0] == before_events
    assert case["payload"].put_calls == before_puts


def test_apply_persists_receipt_payload_only_after_projection_verification(tmp_path: Path) -> None:
    case = _case(tmp_path)
    result = _service(case).apply(_command(), _context())
    assert case["payload"].put_calls == 1
    assert case["conn"].execute("SELECT phase FROM canon_apply_event WHERE phase='PROJECTION_COMMITTED'").fetchone()
    assert result.receipt_ref is not None


def test_apply_completion_transaction_binds_receipt_task_and_audit(tmp_path: Path) -> None:
    case = _case(tmp_path)
    _service(case).apply(_command(), _context())
    task = case["conn"].execute("SELECT status, commit_receipt_ref_artifact_id FROM chapter_task WHERE task_id='task'").fetchone()
    receipt = case["conn"].execute("SELECT journal_id, receipt_ref_artifact_id FROM canon_commit_receipt").fetchone()
    audit = case["conn"].execute("SELECT event_type FROM creation_audit_event WHERE event_type='CANON_APPLY_COMPLETED'").fetchone()
    assert task["status"] == "COMPLETED" and task["commit_receipt_ref_artifact_id"] == receipt["receipt_ref_artifact_id"]
    assert receipt["journal_id"] == "journal" and audit is not None


def test_apply_success_requires_completed_task_and_receipt(tmp_path: Path) -> None:
    case = _case(tmp_path)
    result = _service(case).apply(_command(), _context())
    assert result.receipt_id is not None
    assert case["conn"].execute("SELECT COUNT(*) FROM canon_commit_receipt").fetchone()[0] == 1


def test_apply_same_identity_replays_without_writes(tmp_path: Path) -> None:
    case = _case(tmp_path)
    service = _service(case)
    first = service.apply(_command(), _context())
    before = case["conn"].execute("SELECT COUNT(*) FROM canon_apply_event").fetchone()[0]
    puts = case["payload"].put_calls
    second = service.apply(_command(), _context())
    assert second.receipt_id == first.receipt_id and second.receipt_ref == first.receipt_ref
    assert case["conn"].execute("SELECT COUNT(*) FROM canon_apply_event").fetchone()[0] == before
    assert case["payload"].put_calls == puts


def test_apply_different_identity_returns_conflict_without_overwrite(tmp_path: Path) -> None:
    case = _case(tmp_path)
    service = _service(case)
    service.apply(_command(), _context())
    with pytest.raises(Exception):
        service.apply(_command("apply-two"), _context("apply-two"))
    assert case["conn"].execute("SELECT COUNT(*) FROM canon_commit_receipt").fetchone()[0] == 1


def test_pointer_failure_preserves_old_complete_activation_or_requires_recovery(tmp_path: Path) -> None:
    case = _case(tmp_path)

    class BrokenWriter(C4aProjectionWriter):
        def write_pointer(self, identity):
            raise C4aProjectionWriterError("pointer failure")

    with pytest.raises(CanonApplyRecoveryRequired) as error:
        _service(case, writer_factory=BrokenWriter).apply(_command(), _context())
    assert case["conn"].execute("SELECT status FROM chapter_task").fetchone()[0] == "RECOVERY_REQUIRED"
    assert case["conn"].execute(
        "SELECT recovery_failed_operation_id FROM chapter_task"
    ).fetchone()[0] == "op"
    recovery_fact = case["conn"].execute(
        "SELECT recovery_failed_operation_id, error_code FROM canon_apply_event "
        "WHERE phase='RECOVERY_REQUIRED'"
    ).fetchone()
    assert recovery_fact[0] == "op" and recovery_fact[1] == "C4A_PROJECTION_WRITE_FAILURE"
    assert isinstance(error.value.__cause__, C4aProjectionWriterError)


def test_marker_failure_leaves_reader_fail_closed_without_automatic_repair(tmp_path: Path) -> None:
    case = _case(tmp_path)
    old_marker = (case["root"] / "activation.marker").read_bytes()

    class BrokenWriter(C4aProjectionWriter):
        def write_marker(self, identity):
            raise C4aProjectionWriterError("marker failure")

    with pytest.raises(CanonApplyRecoveryRequired):
        _service(case, writer_factory=BrokenWriter).apply(_command(), _context())
    assert (case["root"] / "activation.marker").read_bytes() == old_marker
    assert case["conn"].execute("SELECT COUNT(*) FROM canon_commit_receipt").fetchone()[0] == 0


def test_receipt_payload_readback_or_artifact_identity_failure_blocks_completion(tmp_path: Path) -> None:
    case = _case(tmp_path)

    class BrokenPayload(MemoryPayloadStore):
        def read(self, digest: str) -> bytes:
            if self.put_calls:
                return b"tampered"
            return super().read(digest)

    broken = BrokenPayload()
    broken.values.update(case["payload"].values)
    case["payload"] = broken
    with pytest.raises(CanonApplyRecoveryRequired):
        _service(case).apply(_command(), _context())
    assert case["conn"].execute("SELECT COUNT(*) FROM canon_commit_receipt").fetchone()[0] == 0


def test_db_completion_failure_after_marker_keeps_durable_recovery_boundary(tmp_path: Path) -> None:
    case = _case(tmp_path)

    class BrokenRepository(SqliteC4aApplyRepository):
        def complete(self, *args, **kwargs):
            raise RuntimeError("simulated Tx B failure")

    repo = BrokenRepository(case["conn"])
    case["repo"] = repo
    with pytest.raises(CanonApplyRecoveryRequired):
        _service(case).apply(_command(), _context())
    assert case["conn"].execute("SELECT status FROM chapter_task").fetchone()[0] == "RECOVERY_REQUIRED"
    assert case["conn"].execute("SELECT COUNT(*) FROM canon_apply_event WHERE phase='RECOVERY_REQUIRED'").fetchone()[0] == 1


def test_same_key_different_digest_conflicts_before_business_or_projection_read(tmp_path: Path) -> None:
    case = _case(tmp_path)
    service = _service(case)
    service.apply(_command(), _context())
    reads = case["reader"].read_calls
    with pytest.raises(IdempotencyConflict):
        service.apply(_command("apply-key", "different-journal"), _context("apply-key"))
    assert case["reader"].read_calls == reads


def test_same_key_same_digest_pending_or_recovery_returns_without_writes(tmp_path: Path) -> None:
    case = _case(tmp_path)
    repo = case["repo"]
    request_digest = compute_canon_apply_request_digest(_command())
    attempt = C4aApplyAttempt(
        "pending-attempt", "project", "apply-key", request_digest, "journal", "task", "op", "decision",
        case["base_ref"], "base-v1", _digest((case["root"] / "current.pointer").read_bytes()),
        case["target_ref"], "target-v1", "sha256:" + "f" * 64, "sha256:" + "1" * 64,
        case["target"].manifest_hash, case["target"].world_hash,
        "maintenance-operator", "2026-08-04T00:00:00+00:00",
    )
    from xiaoshuo.infrastructure.persistence.sqlite.c4a_apply_repository import C4aApplyEvent

    repo.create_prepared(attempt, C4aApplyEvent("pending-attempt:prepared", "pending-attempt", "project", "PREPARED", "PREPARED", None, None, None, None, None, "2026-08-04T00:00:00+00:00"))
    case["conn"].commit()
    with pytest.raises(CanonApplyRecoveryRequired):
        _service(case).apply(_command(), _context())
    assert case["reader"].read_calls == 0


def test_concurrent_attempt_unique_key_loser_has_zero_projection_writes(tmp_path: Path) -> None:
    case = _case(tmp_path)
    lock = C4aProjectionCommitLock(case["root"], enforce_persistent_d_drive=False)
    lock.acquire()
    try:
        with pytest.raises(CanonApplyConflict):
            _service(case).apply(_command(), _context())
        assert case["repo"].get_attempt_by_key("apply-key") is None
        assert case["payload"].put_calls == 0
    finally:
        lock.release()


def test_completed_replay_fully_validates_and_returns_original_envelope(tmp_path: Path) -> None:
    case = _case(tmp_path)
    service = _service(case)
    first = service.apply(_command(), _context())
    before_events = case["conn"].execute("SELECT COUNT(*) FROM canon_apply_event").fetchone()[0]
    before_puts = case["payload"].put_calls
    replay = service.apply(_command(), _context())
    assert replay.receipt_id == first.receipt_id
    assert case["conn"].execute("SELECT COUNT(*) FROM canon_apply_event").fetchone()[0] == before_events
    assert case["payload"].put_calls == before_puts

    base_identity = C4aProjectionWriter.pointer_bytes(
        C4aProjectionIdentity(
            "project", "base-v1", case["base_ref"], case["base"].manifest_hash,
            case["base"].world_hash,
        )
    )
    base_marker = C4aProjectionWriter.marker_bytes(
        C4aProjectionIdentity(
            "project", "base-v1", case["base_ref"], case["base"].manifest_hash,
            case["base"].world_hash,
        ),
        base_identity,
    )
    (case["root"] / "current.pointer").write_bytes(base_identity)
    (case["root"] / "activation.marker").write_bytes(base_marker)
    after_tamper_events = case["conn"].execute("SELECT COUNT(*) FROM canon_apply_event").fetchone()[0]
    with pytest.raises(CanonApplyRecoveryRequired):
        service.apply(_command(), _context())
    assert case["conn"].execute("SELECT COUNT(*) FROM canon_apply_event").fetchone()[0] == after_tamper_events
    assert case["payload"].put_calls == before_puts


def test_tx_b_complete_then_lock_release_uncertain_returns_stable_result_and_replays(tmp_path: Path) -> None:
    case = _case(tmp_path)
    real_lock = C4aProjectionCommitLock(case["root"], enforce_persistent_d_drive=False)

    class ReleaseUncertain:
        def __init__(self, delegate):
            self.delegate = delegate

        @property
        def projection_root(self):
            return self.delegate.projection_root

        @property
        def held(self):
            return self.delegate.held

        def acquire(self):
            return self.delegate.acquire()

        def release(self):
            raise C4aProjectionLockError("release uncertain")

    from xiaoshuo.infrastructure.canon.c4a_projection_commit_lock import C4aProjectionLockError

    with pytest.raises(CanonApplyCommittedLeaseReleaseUncertain) as error:
        _service(case, lock_factory=lambda *args, **kwargs: ReleaseUncertain(real_lock)).apply(_command(), _context())
    assert error.value.replay_envelope
    replay = _service(case).apply(_command(), _context())
    assert replay.receipt_id is not None
