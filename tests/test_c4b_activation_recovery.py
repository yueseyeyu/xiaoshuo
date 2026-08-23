"""C4B-31..36, C4B-44, and C4B-45: activation and recovery boundaries."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from xiaoshuo.application.creation.canon_activation import CanonActivationRequest
from xiaoshuo.application.creation.errors import (
    ActivationConflict,
    ActivationRecoveryRequired,
)
from xiaoshuo.domain.creation import ArtifactRef
from xiaoshuo.infrastructure.canon.c4b_activation import C4bActivationService
from xiaoshuo.infrastructure.canon.canonical_bundle import CanonicalBundle
from xiaoshuo.infrastructure.canon.legacy_seed_importer import LegacyWorldSeedImporter
from xiaoshuo.infrastructure.persistence.sqlite.connection import get_connection
from xiaoshuo.infrastructure.persistence.sqlite.maintenance import init_database
from xiaoshuo.infrastructure.persistence.sqlite.migration_runner import MigrationRunner
from xiaoshuo.infrastructure.persistence.sqlite.settings import SQLitePersistenceSettings


class CountingPayloadStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.put_calls = 0
        self.read_calls = 0

    def put(self, data: bytes) -> str:
        self.put_calls += 1
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        if digest in self.objects and self.objects[digest] != data:
            raise RuntimeError("payload collision")
        self.objects[digest] = data
        return digest

    def read(self, digest: str) -> bytes:
        self.read_calls += 1
        if digest not in self.objects:
            raise FileNotFoundError(digest)
        return self.objects[digest]


def open_db(tmp_path: Path) -> sqlite3.Connection:
    settings = SQLitePersistenceSettings(tmp_path / "activation.db", 5000, tmp_path / "backups")
    init_database(settings)
    conn = get_connection(settings)
    MigrationRunner().migrate(conn, settings)
    return conn


def build_service(tmp_path: Path, *, repo=None, seed_bytes: bytes = b"# world\n", **kwargs):
    conn = open_db(tmp_path)
    parent = tmp_path / "roots"
    parent.mkdir()
    payload_root = parent / "payloads"
    projection_root = parent / "projection"
    seed_path = tmp_path / "world.md"
    seed_path.write_bytes(seed_bytes)
    store = CountingPayloadStore()
    importer = LegacyWorldSeedImporter(seed_path, expected_sha256=hashlib.sha256(seed_bytes).hexdigest())
    service = C4bActivationService(
        conn,
        operator_identity="operator-local",
        payload_root=payload_root,
        projection_root=projection_root,
        payload_store=store,
        seed_importer=importer,
        workspace_root=tmp_path / "workspace",
        enforce_persistent_d_drive=False,
        repository=repo,
        **kwargs,
    )
    return conn, service, store, projection_root


def request(project: str = "project-activation", key: str = "activation-key", char: str = "1"):
    return CanonActivationRequest(project, key, "sha256:" + char * 64)


def cleanup_lock(projection_root: Path) -> None:
    lock_path = projection_root.parent / ".c4b-bootstrap.lock"
    if lock_path.exists():
        lock_path.unlink()


def business_counts(conn: sqlite3.Connection) -> tuple[int, int, int, int]:
    return tuple(
        conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in (
            "canon_activation_attempt",
            "canon_activation_event",
            "chapter_task",
            "canon_commit_journal",
        )
    )


def test_c4b_35_ready_is_before_marker_and_marker_is_final_file_fence(tmp_path: Path) -> None:
    conn, service, store, root = build_service(tmp_path)
    append_observations: list[tuple[str, bool]] = []
    real_repository = service.repository

    class ObservingRepository:
        def __getattr__(self, name):
            return getattr(real_repository, name)

        def create_prepared(self, attempt, event):
            append_observations.append((event.phase, (root / "activation.marker").exists()))
            return real_repository.create_prepared(attempt, event)

        def append_event(self, event):
            append_observations.append((event.phase, (root / "activation.marker").exists()))
            return real_repository.append_event(event)

    service.repository = ObservingRepository()
    try:
        result = service.activate(request())
        assert result.status == "ACTIVATED"
        assert (root / "activation.marker").is_file()
        assert append_observations == [("PREPARED", False), ("READY_FOR_MARKER", False)]
        assert [row[0] for row in conn.execute("SELECT phase FROM canon_activation_event ORDER BY created_at, event_id")] == [
            "PREPARED", "READY_FOR_MARKER"
        ]
        assert store.put_calls == 1
    finally:
        conn.close()


def test_c4b_33_complete_same_identity_replays_original_envelope_without_writes(tmp_path: Path) -> None:
    conn, service, store, root = build_service(tmp_path)
    try:
        first = service.activate(request())
        before = business_counts(conn)
        files_before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
        puts_before, reads_before = store.put_calls, store.read_calls
        second = service.activate(request())
        assert second.status == "REPLAY"
        assert second.replay_envelope_json == first.replay_envelope_json
        assert business_counts(conn) == before
        assert store.put_calls == puts_before
        assert {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()} == files_before
        assert reads_before < store.read_calls
    finally:
        conn.close()


def test_c4b_34_different_request_never_overwrites_existing_activation(tmp_path: Path) -> None:
    conn, service, store, root = build_service(tmp_path)
    try:
        service.activate(request())
        before = business_counts(conn)
        with pytest.raises(ActivationConflict):
            service.activate(request(key="other-key", char="2"))
        assert business_counts(conn) == before
        assert store.put_calls == 1
    finally:
        conn.close()


def test_c4b_31_partial_or_markerless_state_requires_manual_recovery(tmp_path: Path) -> None:
    conn, service, store, root = build_service(tmp_path)
    try:
        service.activate(request())
        marker = root / "activation.marker"
        marker.unlink()
        before = business_counts(conn)
        with pytest.raises(ActivationRecoveryRequired):
            service.activate(request())
        assert business_counts(conn) == before
        assert not marker.exists()
    finally:
        conn.close()


def test_payload_missing_on_replay_has_zero_automatic_repair(tmp_path: Path) -> None:
    conn, service, store, root = build_service(tmp_path)
    try:
        service.activate(request())
        attempt = conn.execute("SELECT bundle_content_hash FROM canon_activation_attempt").fetchone()[0]
        del store.objects[attempt]
        before = business_counts(conn)
        with pytest.raises(ActivationRecoveryRequired):
            service.activate(request())
        assert business_counts(conn) == before
        assert (root / "activation.marker").is_file()
    finally:
        conn.close()


def test_payload_tampering_on_replay_is_recovery_required(tmp_path: Path) -> None:
    conn, service, store, root = build_service(tmp_path)
    try:
        service.activate(request())
        attempt = conn.execute("SELECT bundle_content_hash FROM canon_activation_attempt").fetchone()[0]
        store.objects[attempt] = b"tampered"
        before = business_counts(conn)
        with pytest.raises(ActivationRecoveryRequired):
            service.activate(request())
        assert business_counts(conn) == before
    finally:
        conn.close()


@pytest.mark.parametrize(
    "tamper",
    [
        "marker_pointer_hash",
        "pointer_project",
        "version_project",
        "version_ref",
        "version_world_hash",
        "registry_ref",
    ],
)
def test_c4b_32_reader_identity_mismatches_are_fail_closed(
    tmp_path: Path, tamper: str
) -> None:
    conn, service, store, root = build_service(tmp_path)
    try:
        service.activate(request())
        if tamper == "marker_pointer_hash":
            path = root / "activation.marker"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["pointer_content_hash"] = "sha256:" + "0" * 64
            path.write_bytes(
                json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            )
        elif tamper == "pointer_project":
            path = root / "current.pointer"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["project_id"] = "tampered-project"
            path.write_bytes(
                json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            )
        else:
            version_id = conn.execute(
                "SELECT version_id FROM canon_activation_attempt"
            ).fetchone()[0]
            version_dir = root / "versions" / version_id
            if tamper in {"version_project", "version_ref"}:
                path = version_dir / "bundle.identity.json"
                value = json.loads(path.read_text(encoding="utf-8"))
                value["project_id" if tamper == "version_project" else "bundle_ref_artifact_id"] = (
                    "tampered-project" if tamper == "version_project" else "tampered-ref"
                )
                path.write_bytes(
                    json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
                )
            elif tamper == "version_world_hash":
                (version_dir / "world.md").write_bytes(b"tampered world\n")
            else:
                real_repository = service.repository

                class WrongRegistryRepository:
                    def __getattr__(self, name):
                        return getattr(real_repository, name)

                    def resolve_artifact_ref(self, artifact_id):
                        ref = real_repository.resolve_artifact_ref(artifact_id)
                        return ArtifactRef(ref.artifact_id, ref.schema_version, "sha256:" + "0" * 64)

                service.repository = WrongRegistryRepository()
        before = business_counts(conn)
        with pytest.raises(ActivationRecoveryRequired):
            service.activate(request())
        assert business_counts(conn) == before
    finally:
        conn.close()


def test_transaction_b_failure_leaves_prepared_and_no_marker(tmp_path: Path) -> None:
    conn, service, store, root = build_service(tmp_path)

    class FailingRepository:
        def __init__(self, real):
            self.real = real

        def __getattr__(self, name):
            return getattr(self.real, name)

        def append_event(self, event):
            if event.phase == "READY_FOR_MARKER":
                raise RuntimeError("forced transaction B failure")
            return self.real.append_event(event)

    service.repository = FailingRepository(service.repository)
    try:
        with pytest.raises(ActivationRecoveryRequired):
            service.activate(request())
        assert [row[0] for row in conn.execute("SELECT phase FROM canon_activation_event ORDER BY phase").fetchall()] == [
            "PREPARED"
        ]
        assert not (root / "activation.marker").exists()
        assert (root / "current.pointer").exists()
    finally:
        cleanup_lock(root)
        conn.close()


def test_marker_write_failure_keeps_ready_and_does_not_repair(monkeypatch, tmp_path: Path) -> None:
    import xiaoshuo.infrastructure.canon.c4b_activation as activation_module

    conn, service, store, root = build_service(tmp_path)
    real_writer = activation_module.ProjectionActivationWriter

    class FailingMarkerWriter(real_writer):
        def write_marker(self, identity):
            raise OSError("forced marker failure")

    monkeypatch.setattr(activation_module, "ProjectionActivationWriter", FailingMarkerWriter)
    try:
        with pytest.raises(ActivationRecoveryRequired):
            service.activate(request())
        assert [row[0] for row in conn.execute("SELECT phase FROM canon_activation_event ORDER BY phase")] == [
            "PREPARED", "READY_FOR_MARKER"
        ]
        assert not (root / "activation.marker").exists()
    finally:
        cleanup_lock(root)
        conn.close()


def test_marker_and_ready_are_not_followed_by_committed_event(tmp_path: Path) -> None:
    conn, service, store, root = build_service(tmp_path)
    try:
        service.activate(request())
        assert conn.execute("SELECT COUNT(*) FROM canon_activation_event WHERE phase='COMMITTED'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM canon_activation_event WHERE result='REPLAY'").fetchone()[0] == 0
        assert (root / "activation.marker").read_bytes()
    finally:
        conn.close()


def test_release_failure_returns_recovery_without_new_fact(monkeypatch, tmp_path: Path) -> None:
    import xiaoshuo.infrastructure.canon.c4b_activation as activation_module
    from xiaoshuo.infrastructure.canon.c4b_bootstrap_lock import BootstrapLockError

    conn, service, store, root = build_service(tmp_path)
    original = activation_module.C4bBootstrapLock.release

    def failing_release(lock):
        raise BootstrapLockError("forced release failure")

    monkeypatch.setattr(activation_module.C4bBootstrapLock, "release", failing_release)
    try:
        with pytest.raises(ActivationRecoveryRequired):
            service.activate(request())
        assert (root / "activation.marker").is_file()
        assert [row[0] for row in conn.execute("SELECT phase FROM canon_activation_event ORDER BY phase")] == [
            "PREPARED", "READY_FOR_MARKER"
        ]
    finally:
        monkeypatch.setattr(activation_module.C4bBootstrapLock, "release", original)
        cleanup_lock(root)
        conn.close()


def test_c4b_36_completed_replay_requires_payload_registry_and_ready_event(tmp_path: Path) -> None:
    conn, service, store, root = build_service(tmp_path)
    real_repository = service.repository

    class NoReadyRepository:
        def __getattr__(self, name):
            return getattr(real_repository, name)

        def append_event(self, event):
            if event.phase == "READY_FOR_MARKER":
                raise RuntimeError("no ready event")
            return real_repository.append_event(event)

    service.repository = NoReadyRepository()
    try:
        with pytest.raises(ActivationRecoveryRequired):
            service.activate(request())
        assert conn.execute("SELECT COUNT(*) FROM canon_activation_event WHERE phase='READY_FOR_MARKER'").fetchone()[0] == 0
        assert not (root / "activation.marker").exists()
    finally:
        cleanup_lock(root)
        conn.close()


@pytest.mark.parametrize("tamper_mode", ["missing", "tampered"])
def test_c4b_44_completed_replay_payload_hash_must_match(
    tmp_path: Path, tamper_mode: str
) -> None:
    conn, service, store, root = build_service(tmp_path)
    try:
        service.activate(request())
        digest = conn.execute("SELECT bundle_content_hash FROM canon_activation_attempt").fetchone()[0]
        if tamper_mode == "missing":
            del store.objects[digest]
        else:
            store.objects[digest] = CanonicalBundle(
                1, b'{"x":1}', b"different\n"
            ).to_bytes()
        with pytest.raises(ActivationRecoveryRequired):
            service.activate(request())
    finally:
        conn.close()


@pytest.mark.parametrize(
    "failure_mode", ["marker_absent", "marker_write_failure", "marker_readback_failure"]
)
def test_c4b_45_ready_without_marker_reader_path_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure_mode: str
) -> None:
    if failure_mode in {"marker_write_failure", "marker_readback_failure"}:
        import xiaoshuo.infrastructure.canon.c4b_activation as activation_module

        real_write_marker = activation_module.ProjectionActivationWriter.write_marker

        def fail_marker(writer, identity):
            if failure_mode == "marker_readback_failure":
                real_write_marker(writer, identity)
                (writer.root / "activation.marker").unlink()
                raise OSError("forced marker readback failure")
            raise OSError("forced marker write failure")

        monkeypatch.setattr(activation_module.ProjectionActivationWriter, "write_marker", fail_marker)
    conn, service, store, root = build_service(tmp_path)
    try:
        if failure_mode == "marker_absent":
            service.activate(request())
            marker = root / "activation.marker"
            marker.unlink()
        else:
            with pytest.raises(ActivationRecoveryRequired):
                service.activate(request())
        before = business_counts(conn)
        with pytest.raises(ActivationRecoveryRequired):
            service.activate(request())
        assert business_counts(conn) == before
        assert not (root / "activation.marker").exists()
        assert store.put_calls == 1
    finally:
        cleanup_lock(root)
        conn.close()


def test_projection_residue_is_rejected_before_payload_or_sqlite_writes(tmp_path: Path) -> None:
    conn, service, store, root = build_service(tmp_path)
    root.mkdir()
    (root / "partial.marker").write_bytes(b"partial")
    try:
        with pytest.raises(ActivationRecoveryRequired):
            service.activate(request())
        assert store.put_calls == 0
        assert business_counts(conn) == (0, 0, 0, 0)
        assert (root / "partial.marker").read_bytes() == b"partial"
    finally:
        conn.close()
