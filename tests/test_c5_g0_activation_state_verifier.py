"""G0C-01..06 and G0C-24..30: read-only activation census boundary."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import hashlib
from pathlib import Path
import shutil
import sqlite3
from types import SimpleNamespace
from uuid import uuid4

import pytest

from xiaoshuo.infrastructure.persistence.sqlite.c5_g0_activation_state_verifier import (
    C5G0ActivationCleanEvidence,
    C5G0CompletedGraphSnapshot,
    C5G0ActivationStateVerificationError,
    C5G0ActivationStateVerifier,
)
from xiaoshuo.application.creation.canon_activation import CanonActivationRequest
from xiaoshuo.application.creation.commands import CreateChapterTaskCommand
from xiaoshuo.application.creation.create_task import CreateChapterTaskUseCase
from xiaoshuo.application.creation.local_author_context import LocalAuthorContextImpl
from xiaoshuo.application.creation.authoring_artifact import (
    AuthoringArtifactEnvelope,
    AuthoringArtifactKind,
    serialize_authoring_artifact_envelope,
)
from xiaoshuo.domain.creation import ArtifactRef, ChapterTaskStatus
from xiaoshuo.infrastructure.canon.c4b_activation import C4bActivationService
from xiaoshuo.infrastructure.canon.canonical_bundle import CanonicalBundle
from xiaoshuo.infrastructure.canon.legacy_seed_importer import LegacyWorldSeedImporter
from xiaoshuo.infrastructure.canon.c5_g0_composition import C5G0ApplicationScope
from xiaoshuo.infrastructure.persistence.sqlite.canon_activation_repository import (
    SqliteCanonActivationRepository,
)
from xiaoshuo.infrastructure.persistence.sqlite.repository import SqliteChapterTaskRepository
from xiaoshuo.infrastructure.persistence.sqlite.connection import get_connection
from xiaoshuo.infrastructure.persistence.sqlite.maintenance import init_database
from xiaoshuo.infrastructure.persistence.sqlite.migration_runner import MigrationRunner
from xiaoshuo.infrastructure.persistence.sqlite.settings import SQLitePersistenceSettings
from xiaoshuo.infrastructure.persistence.sqlite.uow import SqliteCreationUnitOfWork
from xiaoshuo.infrastructure.persistence.sqlite.c5_g0_activation_state_verifier import (
    _require_digest,
)
from xiaoshuo.infrastructure.persistence.sqlite.c5_g0_activation_state_verifier import (
    C5G0RuntimeCensusStatus,
)
from xiaoshuo.infrastructure.persistence.sqlite.c5_g0_activation_state_verifier import (
    _is_reparse_point,
    _sha256,
    _verify_completed_graph_snapshot,
    _verify_event_contract,
    _verify_authoring_payload,
)
import xiaoshuo.infrastructure.persistence.sqlite.c5_g0_activation_state_verifier as verifier_module
import xiaoshuo.infrastructure.canon.projection_activation as projection_module
import xiaoshuo.infrastructure.canon.c5_g0_composition as composition_module
from scripts.c5_g0_witness import C5G0WitnessRunner, G0CInput, G0CKeys, derive_activation_identity


_TEST_ROOT = Path(
    r"D:\tmp\yeyu-ai-a3\c5-g0-g0c-backup-family-corrective\20260810-000001-003"
)


class _Context:
    author_id = "local-author"


class _Runtime:
    root = _TEST_ROOT / "verifier"
    payloads_dir = root / "payloads"
    projection_dir = root / "projection"
    exports_dir = root / "exports"
    operator_context = _Context()
    settings = object()

    def __init__(self):
        self.root.mkdir(parents=True, exist_ok=True)
        self.payloads_dir.mkdir(parents=True, exist_ok=True)
        self.projection_dir.mkdir(parents=True, exist_ok=True)


def test_verifier_rejects_unsafe_runtime_root_before_opening_connection():
    runtime = _Runtime()
    runtime.root = Path(r"C:\unsafe")
    opened = []

    def connection_factory(*args, **kwargs):
        opened.append(True)
        raise AssertionError("unsafe roots must fail before SQLite open")

    with pytest.raises(C5G0ActivationStateVerificationError):
        C5G0ActivationStateVerifier(runtime, connection_factory=connection_factory).verify(
            project_id="project-1",
            attempt_key="attempt-1",
            request_digest="sha256:" + "1" * 64,
        )
    assert opened == []


def test_verifier_rejects_non_query_only_connection():
    runtime = _Runtime()
    runtime.exports_dir = Path(r"D:\tmp\c5-g0-verifier-missing-exports")
    conn = sqlite3.connect(":memory:")

    with pytest.raises(C5G0ActivationStateVerificationError):
        C5G0ActivationStateVerifier(
            runtime,
            connection_factory=lambda *args, **kwargs: conn,
        ).verify(
            project_id="project-1",
            attempt_key="attempt-1",
            request_digest="sha256:" + "1" * 64,
        )
    conn.close()


def test_verifier_rejects_schema_without_mutating_connection():
    runtime = _Runtime()
    class _TrackedConnection(sqlite3.Connection):
        closed = False

        def close(self):
            self.closed = True
            super().close()

    conn = sqlite3.connect(":memory:", factory=_TrackedConnection)
    conn.execute("PRAGMA query_only = ON")
    with pytest.raises(C5G0ActivationStateVerificationError):
        C5G0ActivationStateVerifier(
            runtime,
            connection_factory=lambda *args, **kwargs: conn,
        ).verify(
            project_id="project-1",
            attempt_key="attempt-1",
            request_digest="sha256:" + "1" * 64,
        )
    assert conn.closed is True


def test_verifier_digest_guard_is_strict():
    with pytest.raises(C5G0ActivationStateVerificationError):
        _require_digest("sha256:not-a-digest", "request_digest")


def test_clean_evidence_is_immutable_and_has_explicit_c4b_state():
    from xiaoshuo.domain.creation import ArtifactRef

    evidence = C5G0ActivationCleanEvidence(
        status="C4B_ACTIVATED_CLEAN",
        project_id="project-1",
        attempt_id="attempt-1",
        attempt_key="attempt-key",
        request_digest="sha256:" + "1" * 64,
        operator_identity="local-author",
        bundle_ref=ArtifactRef("bundle-1", 1, "sha256:" + "2" * 64),
        version_id="v1",
        pointer_content_hash="sha256:" + "3" * 64,
        event_phases=("PREPARED", "READY_FOR_MARKER"),
        reader_project_id="project-1",
        reader_version_id="v1",
        reader_bundle_ref=ArtifactRef("bundle-1", 1, "sha256:" + "2" * 64),
        reader_bundle_content_hash="sha256:" + "2" * 64,
        reader_manifest_hash="sha256:" + "4" * 64,
        reader_world_hash="sha256:" + "5" * 64,
    )
    assert evidence.status == "C4B_ACTIVATED_CLEAN"
    assert evidence.event_phases == ("PREPARED", "READY_FOR_MARKER")
    with pytest.raises(FrozenInstanceError):
        evidence.status = "BROKEN"  # type: ignore[misc]


def test_verifier_checks_c4b_event_result_envelope_and_hash():
    prepared = SimpleNamespace(
        phase="PREPARED",
        result="PREPARED",
        error_code=None,
        replay_envelope_json=None,
        replay_envelope_hash=None,
    )
    envelope = '{"attempt_id":"attempt-1","status":"ACTIVATED"}'
    ready = SimpleNamespace(
        phase="READY_FOR_MARKER",
        result="READY_FOR_MARKER",
        error_code=None,
        replay_envelope_json=envelope,
        replay_envelope_hash=_sha256(envelope.encode("utf-8")),
    )
    _verify_event_contract((prepared, ready))
    ready.result = "BROKEN"
    with pytest.raises(C5G0ActivationStateVerificationError):
        _verify_event_contract((prepared, ready))


def _completed_snapshot(**changes):
    envelope = '{"operation_kind":"CREATE_CHAPTER_TASK","task_id":"task-1"}'
    values = dict(
        project_id="project-1",
        task_id="task-1",
        task_status="COMPLETED",
        last_stable_status="COMPLETED",
        task_revision=12,
        recovery_error_code=None,
        durable_envelopes=(envelope,),
        payload_content_hashes=("sha256:" + "1" * 64,),
        operation_count=1,
        audit_count=8,
        decision_count=3,
        consumption_count=3,
        c3_journal_count=1,
        c4a_attempt_count=1,
        c4a_event_count=8,
        c4a_completed_event_count=1,
        receipt_count=1,
        activation_attempt_id="attempt-1",
        activation_replay_envelope_json="{\"activation\":\"C4B_FIRST_PROJECTION\"}",
        projection_identity_bound=True,
    )
    values.update(changes)
    return C5G0CompletedGraphSnapshot(**values)


def test_completed_graph_snapshot_is_read_only_and_returns_durable_shape():
    snapshot = _completed_snapshot()
    _verify_completed_graph_snapshot(snapshot)
    assert snapshot.payload_put_count == 0
    assert snapshot.sqlite_write_count == 0
    assert snapshot.lock_observed is False
    assert snapshot.durable_envelopes[0].startswith("{")


@pytest.mark.parametrize(
    "changes",
    [
        {"graph_state": "PARTIAL"},
        {"graph_state": "CONFLICT"},
        {"graph_state": "RECOVERY_REQUIRED"},
        {"graph_state": "UNKNOWN"},
        {"c4a_recovery_event_count": 1},
        {"c4a_unknown_event_count": 1},
    ],
)
def test_completed_graph_snapshot_rejects_partial_conflict_recovery_and_unknown(changes):
    with pytest.raises(C5G0ActivationStateVerificationError):
        _verify_completed_graph_snapshot(_completed_snapshot(**changes))


def test_completed_graph_payload_boundary_allows_read_but_has_no_put():
    payload = b"durable-payload"
    digest = _sha256(payload)

    class _CountingStore:
        puts = 0
        reads = 0

        def read(self, requested):
            type(self).reads += 1
            assert requested == digest
            return payload

        def put(self, _data):
            type(self).puts += 1
            raise AssertionError("completed graph verification must not put payloads")

    store = _CountingStore()
    assert verifier_module._read_payload(store, digest) == payload
    assert store.reads == 1
    assert store.puts == 0


@pytest.mark.parametrize(
    "payload, expected_kind, expected_review_ref",
    [
        (
            b'{"artifact_kind":"PLAN","artifact_schema_version":1,"body":"draft","chapter_number":1,"project_id":"project-1","task_id":"task-1"}',
            AuthoringArtifactKind.DRAFT,
            None,
        ),
        (
            b'{"artifact_kind":"DRAFT","artifact_schema_version":1,"body":"x\\u0000","chapter_number":1,"project_id":"project-1","task_id":"task-1"}',
            AuthoringArtifactKind.DRAFT,
            None,
        ),
        (
            b'{"artifact_kind":"DRAFT","artifact_schema_version":1,"body":"x\x00","chapter_number":1,"project_id":"project-1","task_id":"task-1"}',
            AuthoringArtifactKind.DRAFT,
            None,
        ),
        (b"\xff", AuthoringArtifactKind.DRAFT, None),
        (
            b"{\"artifact_kind\":\"DRAFT\",\"artifact_schema_version\":1,\"body\":\"x\",\"chapter_number\":1,\"project_id\":\"project-1\",\"task_id\":\"task-2\"}",
            AuthoringArtifactKind.DRAFT,
            None,
        ),
    ],
)
def test_completed_graph_authoring_payload_rejects_noncanonical_or_wrong_identity(
    payload, expected_kind, expected_review_ref
):
    digest = _sha256(payload)
    ref = ArtifactRef("draft-1", 1, digest)

    class _Store:
        def read(self, requested):
            assert requested == digest
            return payload

    with pytest.raises(C5G0ActivationStateVerificationError):
        _verify_authoring_payload(
            _Store(),
            ref,
            expected_kind=expected_kind,
            project_id="project-1",
            task_id="task-1",
            chapter_number=1,
            reviewed_draft_ref=expected_review_ref,
        )


def test_completed_graph_authoring_payload_rejects_wrong_review_target_and_hash_mismatch():
    draft_ref = ArtifactRef("draft-1", 1, "sha256:" + "1" * 64)
    wrong_ref = ArtifactRef("draft-2", 1, "sha256:" + "2" * 64)
    review = serialize_authoring_artifact_envelope(
        AuthoringArtifactEnvelope(
            AuthoringArtifactKind.REVIEW,
            1,
            "project-1",
            1,
            "task-1",
            "review",
            reviewed_draft_ref=wrong_ref,
            verdict="PASS",
        )
    )
    review_ref = ArtifactRef("review-1", 1, _sha256(review))

    class _Store:
        def read(self, requested):
            if requested == review_ref.content_hash:
                return review
            return b"different"

    with pytest.raises(C5G0ActivationStateVerificationError):
        _verify_authoring_payload(
            _Store(),
            review_ref,
            expected_kind=AuthoringArtifactKind.REVIEW,
            project_id="project-1",
            task_id="task-1",
            chapter_number=1,
            reviewed_draft_ref=draft_ref,
        )
    with pytest.raises(C5G0ActivationStateVerificationError):
        _verify_authoring_payload(
            _Store(),
            draft_ref,
            expected_kind=AuthoringArtifactKind.DRAFT,
            project_id="project-1",
            task_id="task-1",
            chapter_number=1,
        )


def test_ready_envelope_binds_every_identity_field_to_attempt():
    attempt = SimpleNamespace(
        attempt_id="attempt-1",
        attempt_key="attempt-key",
        bundle_content_hash="sha256:" + "2" * 64,
        bundle_ref_artifact_id="bundle-1",
        manifest_hash="sha256:" + "3" * 64,
        pointer_content_hash="sha256:" + "4" * 64,
        seed_digest="sha256:" + "5" * 64,
        version_id="v1",
        world_hash="sha256:" + "6" * 64,
    )
    expected = {
        "activation": "C4B_FIRST_PROJECTION",
        "attempt_id": attempt.attempt_id,
        "attempt_key": attempt.attempt_key,
        "bundle_content_hash": attempt.bundle_content_hash,
        "bundle_ref_artifact_id": attempt.bundle_ref_artifact_id,
        "manifest_hash": attempt.manifest_hash,
        "pointer_content_hash": attempt.pointer_content_hash,
        "project_id": "project-1",
        "request_digest": "sha256:" + "7" * 64,
        "seed_digest": attempt.seed_digest,
        "version_id": attempt.version_id,
        "world_hash": attempt.world_hash,
    }
    envelope = verifier_module.json.dumps(
        expected, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    prepared = SimpleNamespace(
        phase="PREPARED", result="PREPARED", error_code=None,
        replay_envelope_json=None, replay_envelope_hash=None,
    )
    ready = SimpleNamespace(
        phase="READY_FOR_MARKER", result="READY_FOR_MARKER", error_code=None,
        replay_envelope_json=envelope, replay_envelope_hash=_sha256(envelope.encode()),
    )
    _verify_event_contract(
        (prepared, ready),
        attempt=attempt,
        project_id="project-1",
        attempt_key=attempt.attempt_key,
        request_digest=expected["request_digest"],
    )
    expected["version_id"] = "wrong-version"
    ready.replay_envelope_json = verifier_module.json.dumps(
        expected, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    ready.replay_envelope_hash = _sha256(ready.replay_envelope_json.encode())
    with pytest.raises(C5G0ActivationStateVerificationError):
        _verify_event_contract(
            (prepared, ready),
            attempt=attempt,
            project_id="project-1",
            attempt_key=attempt.attempt_key,
            request_digest="sha256:" + "7" * 64,
        )


def test_ready_envelope_rejects_noncanonical_json_even_when_hash_matches():
    prepared = SimpleNamespace(
        phase="PREPARED", result="PREPARED", error_code=None,
        replay_envelope_json=None, replay_envelope_hash=None,
    )
    ready = SimpleNamespace(
        phase="READY_FOR_MARKER", result="READY_FOR_MARKER", error_code=None,
        replay_envelope_json='{"b":2,"a":1} ',
        replay_envelope_hash=_sha256(b'{"b":2,"a":1} '),
    )
    with pytest.raises(C5G0ActivationStateVerificationError):
        _verify_event_contract((prepared, ready))


def test_verifier_rejects_reparse_attribute_even_when_not_a_symlink(monkeypatch, tmp_path):
    path = tmp_path / "junction-like-entry"
    path.write_bytes(b"x")
    original_lstat = __import__("os").lstat
    monkeypatch.setattr(verifier_module, "_is_reparse_point", lambda _: True)
    with pytest.raises(C5G0ActivationStateVerificationError):
        verifier_module._verify_no_reparse_tree(path)
    assert original_lstat(path).st_size == 1


class _MemoryPayloadStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.put_count = 0

    def put(self, data: bytes) -> str:
        self.put_count += 1
        digest = _sha256(data)
        self.objects[digest] = data
        return digest

    def read(self, digest: str) -> bytes:
        return self.objects[digest]


def _activated_runtime_for_graph_probe(
    *, project_id: str = "project-1", attempt_key: str = "activation-key", request_digest: str = "sha256:" + "a" * 64
) -> tuple[object, sqlite3.Connection, _MemoryPayloadStore]:
    root = (
        _TEST_ROOT / "graph"
        / ("probe-" + uuid4().hex)
    )
    root.mkdir(parents=True, exist_ok=False)
    payloads = root / "payloads"
    projection = root / "projection"
    payloads.mkdir()
    projection.mkdir()
    settings = SQLitePersistenceSettings(root / "activation.db", 5000, root / "backups")
    init_database(settings)
    conn = get_connection(settings)
    MigrationRunner().migrate(conn, settings)
    seed = b"# graph probe\n"
    seed_path = _TEST_ROOT / "seed-inputs" / ("world-" + uuid4().hex + ".md")
    seed_path.parent.mkdir(parents=True, exist_ok=True)
    seed_path.write_bytes(seed)
    store = _MemoryPayloadStore()
    service = C4bActivationService(
        conn,
        operator_identity="local-author",
        payload_root=payloads,
        projection_root=projection,
        payload_store=store,
        seed_importer=LegacyWorldSeedImporter(
            seed_path, expected_sha256=hashlib.sha256(seed).hexdigest()
        ),
        workspace_root=root / "workspace",
        enforce_persistent_d_drive=False,
    )
    service.activate(
        CanonActivationRequest(
            project_id, attempt_key, request_digest
        )
    )
    runtime = SimpleNamespace(
        root=root,
        payloads_dir=payloads,
        projection_dir=projection,
        exports_dir=root / "exports",
        settings=settings,
        operator_context=SimpleNamespace(author_id="local-author"),
        author_context=LocalAuthorContextImpl("local-author"),
    )
    return runtime, conn, store


def _census_runtime(root: Path):
    settings = SQLitePersistenceSettings(root / "creation.db", 5000, root / "backups")
    return SimpleNamespace(
        root=root,
        db_path=settings.db_path,
        payloads_dir=root / "payloads",
        projection_dir=root / "projection",
        backups_dir=root / "backups",
        exports_dir=root / "exports",
        settings=settings,
        operator_context=SimpleNamespace(author_id="local-author"),
    )


def _new_census_root(name: str) -> Path:
    root = _TEST_ROOT / name / uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    return root


def _provision_empty_census_runtime() -> object:
    root = _new_census_root("initialized-empty")
    runtime = _census_runtime(root)
    init_database(runtime.settings)
    conn = get_connection(runtime.settings)
    try:
        MigrationRunner().migrate(conn, runtime.settings)
    finally:
        conn.close()
    return runtime


def _recovery_compatible_census_runtime() -> object:
    source = _provision_empty_census_runtime()
    root = _new_census_root("recovery-compatible")
    runtime = _census_runtime(root)
    shutil.copyfile(source.db_path, runtime.db_path)
    runtime.backups_dir.mkdir()
    for version in range(2, 7):
        candidates = sorted(
            source.backups_dir.glob(f"pre_migration_v{version:03d}_*.db")
        )
        assert candidates
        main = runtime.backups_dir / f"pre_migration_v{version:03d}_accepted.db"
        shutil.copyfile(candidates[-1], main)
        (runtime.backups_dir / (main.name + "-wal")).write_bytes(b"wal-sidecar")
        (runtime.backups_dir / (main.name + "-shm")).write_bytes(b"shm-sidecar")
    return runtime


def test_runtime_census_unprovisioned_has_no_executable_branch():
    runtime = _census_runtime(_TEST_ROOT / "unprovisioned" / uuid4().hex)
    census = C5G0ActivationStateVerifier(runtime).classify_runtime(
        project_id="project-1",
        attempt_key="attempt-1",
        request_digest="sha256:" + "1" * 64,
    )
    assert census.status is C5G0RuntimeCensusStatus.UNPROVISIONED_NO_RUNTIME
    assert census.clean_evidence is None
    assert census.completed_graph_evidence is None


def test_runtime_census_initialized_empty_is_fresh_only_and_read_only():
    runtime = _provision_empty_census_runtime()
    census = C5G0ActivationStateVerifier(runtime).classify_runtime(
        project_id="project-1",
        attempt_key="attempt-1",
        request_digest="sha256:" + "1" * 64,
    )
    assert census.status is C5G0RuntimeCensusStatus.INITIALIZED_EMPTY
    assert census.business_fact_counts
    assert not runtime.payloads_dir.exists()
    assert not runtime.projection_dir.exists()


def test_runtime_census_initialized_empty_with_unexpected_root_file_is_residue():
    runtime = _provision_empty_census_runtime()
    (runtime.root / "unexpected-root-file").write_bytes(b"residue")
    census = C5G0ActivationStateVerifier(runtime).classify_runtime(
        project_id="project-1",
        attempt_key="attempt-1",
        request_digest="sha256:" + "1" * 64,
    )
    assert census.status is C5G0RuntimeCensusStatus.RESIDUE


def test_runtime_census_initialized_empty_with_invalid_backup_is_residue():
    runtime = _provision_empty_census_runtime()
    runtime.backups_dir.mkdir(exist_ok=True)
    (runtime.backups_dir / "not-a-valid-backup.tmp").write_bytes(b"residue")
    census = C5G0ActivationStateVerifier(runtime).classify_runtime(
        project_id="project-1",
        attempt_key="attempt-1",
        request_digest="sha256:" + "1" * 64,
    )
    assert census.status is C5G0RuntimeCensusStatus.RESIDUE


def test_initialized_empty_missing_backups_is_partial_and_fresh_gate_rejects():
    runtime = _provision_empty_census_runtime()
    for path in runtime.backups_dir.iterdir():
        path.unlink()
    runtime.backups_dir.rmdir()
    verifier = C5G0ActivationStateVerifier(runtime)
    census = verifier.classify_runtime(
        project_id="project-1",
        attempt_key="attempt-1",
        request_digest="sha256:" + "1" * 64,
    )
    assert census.status is C5G0RuntimeCensusStatus.PARTIAL
    with pytest.raises(C5G0ActivationStateVerificationError):
        verifier.verify_fresh_gate(
            project_id="project-1",
            attempt_key="attempt-1",
            request_digest="sha256:" + "1" * 64,
        )


def test_initialized_empty_empty_backups_is_residue():
    runtime = _provision_empty_census_runtime()
    for path in runtime.backups_dir.iterdir():
        path.unlink()
    census = C5G0ActivationStateVerifier(runtime).classify_runtime(
        project_id="project-1",
        attempt_key="attempt-1",
        request_digest="sha256:" + "1" * 64,
    )
    assert census.status is C5G0RuntimeCensusStatus.RESIDUE


def test_initialized_empty_missing_backup_family_member_is_residue():
    runtime = _recovery_compatible_census_runtime()
    next(runtime.backups_dir.glob("pre_migration_v004_*.db")).unlink()
    census = C5G0ActivationStateVerifier(runtime).classify_runtime(
        project_id="project-1",
        attempt_key="attempt-1",
        request_digest="sha256:" + "1" * 64,
    )
    assert census.status is C5G0RuntimeCensusStatus.RESIDUE


@pytest.mark.parametrize("mutation", ["hash", "schema"])
def test_initialized_empty_backup_identity_or_schema_mismatch_is_residue(mutation):
    runtime = _recovery_compatible_census_runtime()
    if mutation == "hash":
        main = next(runtime.backups_dir.glob("pre_migration_v003_*.db"))
        main.write_bytes(b"not-a-sqlite-backup")
    else:
        source = next(runtime.backups_dir.glob("pre_migration_v002_*.db"))
        target = next(runtime.backups_dir.glob("pre_migration_v003_*.db"))
        shutil.copyfile(source, target)
    census = C5G0ActivationStateVerifier(runtime).classify_runtime(
        project_id="project-1",
        attempt_key="attempt-1",
        request_digest="sha256:" + "1" * 64,
    )
    assert census.status is C5G0RuntimeCensusStatus.RESIDUE


@pytest.mark.parametrize("mutation", ["schema", "ledger"])
def test_backup_pre_migration_schema_and_ledger_tampering_is_residue(mutation):
    runtime = _recovery_compatible_census_runtime()
    main = next(runtime.backups_dir.glob("pre_migration_v004_*.db"))
    connection = sqlite3.connect(main)
    try:
        if mutation == "schema":
            connection.execute("ALTER TABLE chapter_task ADD COLUMN tampered TEXT")
        else:
            connection.execute(
                "UPDATE creation_schema_migration SET sha256 = ? WHERE version = ?",
                ("tampered-ledger-hash", 3),
            )
        connection.commit()
    finally:
        connection.close()
    census = C5G0ActivationStateVerifier(runtime).classify_runtime(
        project_id="project-1",
        attempt_key="attempt-1",
        request_digest="sha256:" + "1" * 64,
    )
    assert census.status is C5G0RuntimeCensusStatus.RESIDUE


def test_recovery_compatible_runtime_uses_immutable_fresh_gate_and_accepts_sidecars():
    runtime = _recovery_compatible_census_runtime()
    before = {
        path.name: (path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in runtime.backups_dir.iterdir()
    }
    verifier = C5G0ActivationStateVerifier(runtime)
    census = verifier.classify_runtime(
        project_id="project-1",
        attempt_key="attempt-1",
        request_digest="sha256:" + "1" * 64,
    )
    assert census.status is C5G0RuntimeCensusStatus.RECOVERY_ASSESSED_INITIALIZED_EMPTY_COMPATIBLE
    evidence = verifier.verify_fresh_gate(
        project_id="project-1",
        attempt_key="attempt-1",
        request_digest="sha256:" + "1" * 64,
    )
    assert evidence.status is C5G0RuntimeCensusStatus.RECOVERY_ASSESSED_INITIALIZED_EMPTY_COMPATIBLE
    assert evidence.zero_write is True
    assert evidence.immutable_connection_closed is True
    assert evidence.zero_business_facts is True
    assert all(value == 0 for _, value in evidence.business_fact_counts)
    assert evidence.integrity_check == "ok"
    assert evidence.foreign_key_check == ()
    assert len(evidence.backup_files) == 15
    after = {
        path.name: (path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in runtime.backups_dir.iterdir()
    }
    assert after == before


@pytest.mark.parametrize("mutation", ["residue", "sidecar", "fact"])
def test_fresh_gate_rejects_changes_between_census_passes(monkeypatch, mutation):
    runtime = _recovery_compatible_census_runtime()
    verifier = C5G0ActivationStateVerifier(runtime)
    original = verifier.classify_runtime
    calls = 0

    def classify_with_change(**kwargs):
        nonlocal calls
        result = original(**kwargs)
        calls += 1
        if calls == 1 and mutation == "residue":
            (runtime.root / "late-residue").write_bytes(b"residue")
        elif calls == 1 and mutation == "sidecar":
            Path(str(runtime.db_path) + "-journal").write_bytes(b"sidecar")
        elif calls == 2 and mutation == "fact":
            result = replace(
                result,
                business_fact_counts=(("chapter_task", 1),),
            )
        return result

    monkeypatch.setattr(verifier, "classify_runtime", classify_with_change)
    with pytest.raises(C5G0ActivationStateVerificationError):
        verifier.verify_fresh_gate(
            project_id="project-1",
            attempt_key="attempt-1",
            request_digest="sha256:" + "1" * 64,
        )
    assert calls >= 2


def test_recovery_compatible_runtime_rejects_orphan_sidecar():
    runtime = _recovery_compatible_census_runtime()
    (runtime.backups_dir / "pre_migration_v999_orphan.db-wal").write_bytes(b"orphan")
    census = C5G0ActivationStateVerifier(runtime).classify_runtime(
        project_id="project-1",
        attempt_key="attempt-1",
        request_digest="sha256:" + "1" * 64,
    )
    assert census.status is C5G0RuntimeCensusStatus.RESIDUE


def test_runtime_census_database_without_root_is_partial():
    runtime = _provision_empty_census_runtime()
    missing_root = runtime.root / "missing-root"
    runtime.root = missing_root
    runtime.payloads_dir = missing_root / "payloads"
    runtime.projection_dir = missing_root / "projection"
    runtime.backups_dir = missing_root / "backups"
    runtime.exports_dir = missing_root / "exports"
    census = C5G0ActivationStateVerifier(runtime).classify_runtime(
        project_id="project-1",
        attempt_key="attempt-1",
        request_digest="sha256:" + "1" * 64,
    )
    assert census.status is C5G0RuntimeCensusStatus.PARTIAL


def test_runtime_census_c4b_clean_is_bootstrap_replay_only(monkeypatch):
    runtime, conn, store = _activated_runtime_for_graph_probe()
    try:
        conn.close()
        monkeypatch.setattr(projection_module, "_production_root", lambda: runtime.projection_dir)
        verifier = C5G0ActivationStateVerifier(
            runtime,
            payload_store_factory=lambda _root: store,
        )
        census = verifier.classify_runtime(
            project_id="project-1",
            attempt_key="activation-key",
            request_digest="sha256:" + "a" * 64,
        )
        assert census.status is C5G0RuntimeCensusStatus.C4B_ACTIVATED_CLEAN, census.reason
        assert census.clean_evidence is not None
    finally:
        conn.close()


def test_runtime_census_c4b_residue_precedes_clean_verifier(monkeypatch):
    runtime, conn, store = _activated_runtime_for_graph_probe()
    try:
        conn.close()
        monkeypatch.setattr(projection_module, "_production_root", lambda: runtime.projection_dir)
        runtime.backups_dir = runtime.root / "backups"
        runtime.backups_dir.mkdir(exist_ok=True)
        (runtime.backups_dir / "invalid-backup.tmp").write_bytes(b"residue")
        verifier = C5G0ActivationStateVerifier(
            runtime,
            payload_store_factory=lambda _root: store,
        )
        monkeypatch.setattr(
            verifier,
            "verify",
            lambda **kwargs: pytest.fail("clean verifier must not run for residue"),
        )
        census = verifier.classify_runtime(
            project_id="project-1",
            attempt_key="activation-key",
            request_digest="sha256:" + "a" * 64,
        )
        assert census.status is C5G0RuntimeCensusStatus.RESIDUE
    finally:
        conn.close()


def test_runtime_census_completed_graph_is_not_c4b_clean(monkeypatch):
    runtime, conn, store, project_id, task_id, attempt_key, request_digest = (
        _build_completed_graph_for_failure_probe(monkeypatch)
    )
    try:
        conn.close()
        verifier = C5G0ActivationStateVerifier(
            runtime,
            payload_store_factory=lambda _root: store,
        )
        census = verifier.classify_runtime(
            project_id=project_id,
            attempt_key=attempt_key,
            request_digest=request_digest,
        )
        assert census.status is C5G0RuntimeCensusStatus.COMPLETED_GRAPH
        assert census.completed_task_ids == (task_id,)
        assert census.clean_evidence is None
    finally:
        conn.close()


def test_runtime_census_completed_graph_residue_precedes_graph_verifier(monkeypatch):
    runtime, conn, store, project_id, task_id, attempt_key, request_digest = (
        _build_completed_graph_for_failure_probe(monkeypatch)
    )
    try:
        runtime.backups_dir = runtime.root / "backups"
        runtime.backups_dir.mkdir(exist_ok=True)
        (runtime.backups_dir / "invalid-backup.tmp").write_bytes(b"residue")
        verifier = C5G0ActivationStateVerifier(
            runtime,
            payload_store_factory=lambda _root: store,
        )
        monkeypatch.setattr(
            verifier,
            "verify_completed_graph",
            lambda **kwargs: pytest.fail("completed graph verifier must not run for residue"),
        )
        census = verifier.classify_runtime(
            project_id=project_id,
            attempt_key=attempt_key,
            request_digest=request_digest,
        )
        assert census.status is C5G0RuntimeCensusStatus.RESIDUE
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("partial", C5G0RuntimeCensusStatus.PARTIAL),
        ("residue", C5G0RuntimeCensusStatus.RESIDUE),
        ("unknown", C5G0RuntimeCensusStatus.UNKNOWN),
    ],
)
def test_runtime_census_rejects_partial_residue_and_unknown(state, expected):
    root = _new_census_root("rejected-" + state)
    runtime = _census_runtime(root)
    if state == "partial":
        runtime.payloads_dir.mkdir()
    elif state == "residue":
        runtime.exports_dir.mkdir()
    else:
        runtime.db_path.write_bytes(b"not-a-sqlite-database")
    census = C5G0ActivationStateVerifier(runtime).classify_runtime(
        project_id="project-1",
        attempt_key="attempt-1",
        request_digest="sha256:" + "1" * 64,
    )
    assert census.status is expected


def test_runtime_census_reparse_and_lock_have_priority(monkeypatch):
    reparse_root = _new_census_root("reparse")
    reparse_runtime = _census_runtime(reparse_root)
    monkeypatch.setattr(verifier_module, "_is_reparse_point", lambda path: Path(path) == reparse_root)
    reparse = C5G0ActivationStateVerifier(reparse_runtime).classify_runtime(
        project_id="project-1", attempt_key="attempt-1", request_digest="sha256:" + "1" * 64
    )
    assert reparse.status is C5G0RuntimeCensusStatus.REPARSE_OR_JUNCTION

    lock_root = _new_census_root("lock")
    (lock_root / ".c4b-bootstrap.lock").write_text("held", encoding="utf-8")
    lock = C5G0ActivationStateVerifier(_census_runtime(lock_root)).classify_runtime(
        project_id="project-1", attempt_key="attempt-1", request_digest="sha256:" + "1" * 64
    )
    assert lock.status is C5G0RuntimeCensusStatus.LOCK_OR_CLOSE_UNCERTAIN


def test_runtime_census_recovery_precedes_partial_and_residue(monkeypatch):
    runtime = _provision_empty_census_runtime()
    runtime.payloads_dir.mkdir()
    runtime.exports_dir.mkdir()
    counts = {
        table: 0
        for table in verifier_module._EXPECTED_TABLES
        if table != "creation_schema_migration"
    }
    monkeypatch.setattr(
        verifier_module,
        "_read_runtime_business_census",
        lambda _conn: {
            "counts": counts,
            "fact_count": 1,
            "task_ids": [],
            "completed_task_ids": [],
            "recovery": True,
            "activation_attempt_count": 0,
            "activation_event_count": 0,
            "artifact_ref_count": 0,
        },
    )
    census = C5G0ActivationStateVerifier(runtime).classify_runtime(
        project_id="project-1", attempt_key="attempt-1", request_digest="sha256:" + "1" * 64
    )
    assert census.status is C5G0RuntimeCensusStatus.RECOVERY_REQUIRED


def test_runtime_census_unknown_mixture_returns_typed_status_without_unbound_evidence():
    runtime = _provision_empty_census_runtime()
    runtime.payloads_dir.mkdir()
    runtime.projection_dir.mkdir()
    census = C5G0ActivationStateVerifier(runtime).classify_runtime(
        project_id="project-1", attempt_key="attempt-1", request_digest="sha256:" + "1" * 64
    )
    assert census.status is C5G0RuntimeCensusStatus.UNKNOWN
    assert census.clean_evidence is None


def test_runtime_census_close_failure_is_lock_or_close_uncertain():
    runtime = _provision_empty_census_runtime()

    class _CloseFails(sqlite3.Connection):
        def close(self):
            raise RuntimeError("close failed")

    def connection_factory(*args, **kwargs):
        return sqlite3.connect(":memory:", factory=_CloseFails)

    census = C5G0ActivationStateVerifier(
        runtime,
        connection_factory=connection_factory,
    ).classify_runtime(
        project_id="project-1", attempt_key="attempt-1", request_digest="sha256:" + "1" * 64
    )
    assert census.status is C5G0RuntimeCensusStatus.LOCK_OR_CLOSE_UNCERTAIN


def test_completed_graph_calls_production_verifier_and_rejects_missing_graph(monkeypatch):
    runtime, conn, store = _activated_runtime_for_graph_probe()
    try:
        conn.close()
        monkeypatch.setattr(projection_module, "_production_root", lambda: runtime.projection_dir)
        verifier = C5G0ActivationStateVerifier(
            runtime,
            payload_store_factory=lambda _root: store,
        )
        with pytest.raises(C5G0ActivationStateVerificationError) as caught:
            verifier.verify_completed_graph(
                project_id="project-1",
                task_id="task-1",
                attempt_key="activation-key",
                request_digest="sha256:" + "a" * 64,
            )
        assert "Task" in str(caught.value)
    finally:
        conn.close()


def test_completed_graph_rejects_extra_tasks_created_through_application_boundary(monkeypatch):
    runtime, conn, store = _activated_runtime_for_graph_probe()
    try:
        monkeypatch.setattr(projection_module, "_production_root", lambda: runtime.projection_dir)
        attempt = SqliteCanonActivationRepository(conn).get_attempt_by_project("project-1")
        assert attempt is not None
        create_task = CreateChapterTaskUseCase(
            lambda: SqliteCreationUnitOfWork(get_connection(runtime.settings))
        )
        for task_id, chapter in (("task-1", 1), ("task-2", 2)):
            create_task.create(
                CreateChapterTaskCommand(
                    task_id=task_id,
                    project_id="project-1",
                    chapter_number=chapter,
                    initial_status=ChapterTaskStatus.PLAN_PREPARING,
                    creative_intent_ref=attempt.bundle_ref,
                )
            )
        conn.close()
        verifier = C5G0ActivationStateVerifier(
            runtime,
            payload_store_factory=lambda _root: store,
        )
        with pytest.raises(C5G0ActivationStateVerificationError) as caught:
            verifier.verify_completed_graph(
                project_id="project-1",
                task_id="task-1",
                attempt_key="activation-key",
                request_digest="sha256:" + "a" * 64,
            )
        assert "exactly one Task" in str(caught.value)
    finally:
        conn.close()


def test_completed_graph_success_uses_real_phase_a_b_c3_c4a_boundaries(monkeypatch):
    project_id = "project-completed"
    activation_key = "activation-key-completed"
    attempt_key, request_digest = derive_activation_identity(project_id, activation_key)
    runtime, conn, store = _activated_runtime_for_graph_probe(
        project_id=project_id, attempt_key=attempt_key, request_digest=request_digest
    )
    monkeypatch.setattr(projection_module, "_production_root", lambda: runtime.projection_dir)
    monkeypatch.setattr(composition_module, "ImmutablePayloadStore", lambda _root: store)
    real_c4a_service = composition_module.C4aApplyService

    def c4a_factory(connection, operator_identity):
        repository = SqliteCanonActivationRepository(connection)
        reader = composition_module.ProjectionActivationReader(
            runtime.projection_dir,
            artifact_ref_resolver=repository.resolve_artifact_ref,
        )
        return real_c4a_service(
            connection,
            operator_identity=operator_identity,
            payload_store=store,
            projection_root=runtime.projection_dir,
            activation_reader=reader,
            workspace_root=runtime.root / "workspace",
            enforce_persistent_d_drive=False,
        )

    monkeypatch.setattr(composition_module, "C4aApplyService", c4a_factory)

    class _Composition:
        def __init__(self):
            self.runtime = runtime

        def verify_c4b_clean(self, **kwargs):
            return C5G0ActivationStateVerifier(
                runtime,
                payload_store_factory=lambda _root: store,
            ).verify(**kwargs)

        def open_application_scope(self):
            return C5G0ApplicationScope(runtime)

    runner = C5G0WitnessRunner(_Composition())
    conn.close()
    keys = G0CKeys(
        activation_key,
        "plan-key-completed",
        "confirm-key-completed",
        "draft-key-completed",
        "review-key-completed",
        "adopt-key-completed",
        "prepare-changeset-key-completed",
        "approve-changeset-key-completed",
        "apply-key-completed",
    )
    creative_intent = serialize_authoring_artifact_envelope(
        AuthoringArtifactEnvelope(
            AuthoringArtifactKind.CREATIVE_INTENT, 1, project_id, 1, "task-completed", "intent"
        )
    )
    plan = serialize_authoring_artifact_envelope(
        AuthoringArtifactEnvelope(
            AuthoringArtifactKind.PLAN, 1, project_id, 1, "task-completed", "plan"
        )
    )
    draft = serialize_authoring_artifact_envelope(
        AuthoringArtifactEnvelope(
            AuthoringArtifactKind.DRAFT, 1, project_id, 1, "task-completed", "draft"
        )
    )
    phase_a = runner.run_phase_a(
        G0CInput(
            project_id, "task-completed", 1, keys, creative_intent, plan, draft
        )
    )
    target_bundle = CanonicalBundle(1, b'{"chapter":1}', b"# target\n").to_bytes()
    phase_b = runner.run_phase_b(
        G0CInput(
            project_id,
            "task-completed",
            1,
            keys,
            creative_intent,
            plan,
            draft,
            review_template_bytes=b"review",
            target_bundle_bytes=target_bundle,
        ),
        phase_a=phase_a,
    )
    assert phase_b.status is ChapterTaskStatus.COMPLETED
    conn.close()
    try:
        evidence = C5G0ActivationStateVerifier(
            runtime,
            payload_store_factory=lambda _root: store,
        ).verify_completed_graph(
            project_id=project_id,
            task_id="task-completed",
            attempt_key=attempt_key,
            request_digest=request_digest,
        )
        assert evidence.status == "COMPLETED_GRAPH_VERIFIED"
        assert len(evidence.task_facts) == 1
        assert len(evidence.apply_event_facts) == 8
    finally:
        conn.close()


def _build_completed_graph_for_failure_probe(monkeypatch):
    """Construct the graph through the same Phase A/B/C3/C4a boundaries."""

    project_id = "project-semantic-probe"
    task_id = "task-semantic-probe"
    activation_key = "activation-key-semantic-probe"
    attempt_key, request_digest = derive_activation_identity(project_id, activation_key)
    runtime, conn, store = _activated_runtime_for_graph_probe(
        project_id=project_id, attempt_key=attempt_key, request_digest=request_digest
    )
    monkeypatch.setattr(projection_module, "_production_root", lambda: runtime.projection_dir)
    monkeypatch.setattr(composition_module, "ImmutablePayloadStore", lambda _root: store)
    real_c4a_service = composition_module.C4aApplyService

    def c4a_factory(connection, operator_identity):
        repository = SqliteCanonActivationRepository(connection)
        reader = composition_module.ProjectionActivationReader(
            runtime.projection_dir,
            artifact_ref_resolver=repository.resolve_artifact_ref,
        )
        return real_c4a_service(
            connection,
            operator_identity=operator_identity,
            payload_store=store,
            projection_root=runtime.projection_dir,
            activation_reader=reader,
            workspace_root=runtime.root / "workspace",
            enforce_persistent_d_drive=False,
        )

    monkeypatch.setattr(composition_module, "C4aApplyService", c4a_factory)

    class _Composition:
        def __init__(self):
            self.runtime = runtime

        def verify_c4b_clean(self, **kwargs):
            return C5G0ActivationStateVerifier(
                runtime,
                payload_store_factory=lambda _root: store,
            ).verify(**kwargs)

        def open_application_scope(self):
            return C5G0ApplicationScope(runtime)

    keys = G0CKeys(
        activation_key,
        "plan-key-semantic-probe",
        "confirm-key-semantic-probe",
        "draft-key-semantic-probe",
        "review-key-semantic-probe",
        "adopt-key-semantic-probe",
        "prepare-changeset-key-semantic-probe",
        "approve-changeset-key-semantic-probe",
        "apply-key-semantic-probe",
    )
    creative_intent = serialize_authoring_artifact_envelope(
        AuthoringArtifactEnvelope(
            AuthoringArtifactKind.CREATIVE_INTENT, 1, project_id, 1, task_id, "intent"
        )
    )
    plan = serialize_authoring_artifact_envelope(
        AuthoringArtifactEnvelope(
            AuthoringArtifactKind.PLAN, 1, project_id, 1, task_id, "plan"
        )
    )
    draft = serialize_authoring_artifact_envelope(
        AuthoringArtifactEnvelope(
            AuthoringArtifactKind.DRAFT, 1, project_id, 1, task_id, "draft"
        )
    )
    runner = C5G0WitnessRunner(_Composition())
    conn.close()
    phase_a = runner.run_phase_a(
        G0CInput(project_id, task_id, 1, keys, creative_intent, plan, draft)
    )
    target_bundle = CanonicalBundle(1, b'{"chapter":1}', b"# target\n").to_bytes()
    phase_b = runner.run_phase_b(
        G0CInput(
            project_id,
            task_id,
            1,
            keys,
            creative_intent,
            plan,
            draft,
            review_template_bytes=b"review",
            target_bundle_bytes=target_bundle,
        ),
        phase_a=phase_a,
    )
    assert phase_b.status is ChapterTaskStatus.COMPLETED
    conn = get_connection(runtime.settings)
    return runtime, conn, store, project_id, task_id, attempt_key, request_digest


class _ReplacementRow:
    def __init__(self, row, replacements):
        self._row = row
        self._replacements = replacements

    def __getitem__(self, key):
        if isinstance(key, str) and key in self._replacements:
            return self._replacements[key]
        return self._row[key]

    def keys(self):
        return self._row.keys()


def test_completed_graph_production_verifier_rejects_authoring_payload_mutation(monkeypatch):
    runtime, conn, store, project_id, task_id, attempt_key, request_digest = (
        _build_completed_graph_for_failure_probe(monkeypatch)
    )
    try:
        task = SqliteChapterTaskRepository(conn).get(task_id)
        assert task is not None and task.adopted_draft_ref is not None
        adopted_hash = task.adopted_draft_ref.content_hash
        store.objects[adopted_hash] = store.objects[adopted_hash] + b"\x00"
        conn.close()
        verifier = C5G0ActivationStateVerifier(
            runtime,
            payload_store_factory=lambda _root: store,
        )
        with pytest.raises(C5G0ActivationStateVerificationError):
            verifier.verify_completed_graph(
                project_id=project_id,
                task_id=task_id,
                attempt_key=attempt_key,
                request_digest=request_digest,
            )
    finally:
        conn.close()


def test_completed_graph_production_verifier_rejects_operation_envelope_mutation(monkeypatch):
    runtime, conn, store, project_id, task_id, attempt_key, request_digest = (
        _build_completed_graph_for_failure_probe(monkeypatch)
    )
    try:
        def mutated_operation_reader(connection):
            rows = list(verifier_module._read_operation_rows(connection))
            original = rows[1]["result_envelope_json"]
            payload = __import__("json").loads(original)
            payload["plan_ref"]["content_hash"] = "sha256:" + "f" * 64
            changed = __import__("json").dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            rows[1] = _ReplacementRow(
                rows[1],
                {
                    "result_envelope_json": changed,
                    "result_envelope_hash": _sha256(changed.encode("utf-8")),
                },
            )
            return tuple(rows)

        verifier = C5G0ActivationStateVerifier(
            runtime,
            payload_store_factory=lambda _root: store,
            operation_reader=mutated_operation_reader,
        )
        conn.close()
        with pytest.raises(C5G0ActivationStateVerificationError):
            verifier.verify_completed_graph(
                project_id=project_id,
                task_id=task_id,
                attempt_key=attempt_key,
                request_digest=request_digest,
            )
    finally:
        conn.close()
