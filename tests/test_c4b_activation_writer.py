"""C4B-26..30: first projection version, pointer, marker, and durable writes."""

from __future__ import annotations

import json
import hashlib
import sqlite3
from pathlib import Path

import pytest

from xiaoshuo.domain.creation import ArtifactRef
from xiaoshuo.application.creation.canon_activation import CanonActivationRequest
from xiaoshuo.infrastructure.canon.c4b_bootstrap_lock import C4bBootstrapLock
from xiaoshuo.infrastructure.canon.c4b_activation import C4bActivationService
from xiaoshuo.infrastructure.canon.canonical_bundle import CanonicalBundle
from xiaoshuo.infrastructure.canon.legacy_seed_importer import LegacyWorldSeedImporter
from xiaoshuo.infrastructure.canon.projection_activation_writer import (
    C4bProjectionIdentity,
    ProjectionActivationWriter,
    ProjectionActivationWriterError,
)
from xiaoshuo.infrastructure.persistence.sqlite.connection import get_connection
from xiaoshuo.infrastructure.persistence.sqlite.maintenance import init_database
from xiaoshuo.infrastructure.persistence.sqlite.migration_runner import MigrationRunner
from xiaoshuo.infrastructure.persistence.sqlite.settings import SQLitePersistenceSettings


def bundle_and_identity(project: str = "project-writer") -> tuple[CanonicalBundle, C4bProjectionIdentity]:
    bundle = CanonicalBundle(
        1,
        b'{"manifest_schema_version":1,"project_id":"' + project.encode() + b'","seed":{"kind":"TEST","world_sha256":"sha256:' + b"a" * 64 + b'"}}',
        b"# test world\n",
    )
    suffix = bundle.content_hash().removeprefix("sha256:")
    identity = C4bProjectionIdentity(
        project_id=project,
        version_id="version-" + suffix,
        bundle_ref=ArtifactRef("bundle-" + suffix, 1, bundle.content_hash()),
        manifest_hash=bundle.manifest_hash,
        world_hash=bundle.world_hash,
    )
    return bundle, identity


def lock_and_writer(tmp_path: Path) -> tuple[C4bBootstrapLock, Path, ProjectionActivationWriter]:
    parent = tmp_path / "projection-parent"
    parent.mkdir()
    root = parent / "projection"
    lock = C4bBootstrapLock(
        parent / "payloads",
        root,
        lock_path=parent / ".c4b-bootstrap.lock",
        enforce_persistent_d_drive=False,
    )
    lock.acquire()
    return lock, root, ProjectionActivationWriter(root, lock)


class RecordingPayloadStore:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.objects: dict[str, bytes] = {}

    def put(self, data: bytes) -> str:
        self.order.append("payload.put")
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        self.objects[digest] = data
        return digest

    def read(self, digest: str) -> bytes:
        self.order.append("payload.read")
        return self.objects[digest]


def test_c4b_26_full_activation_order_keeps_ready_before_marker(tmp_path: Path, monkeypatch) -> None:
    settings = SQLitePersistenceSettings(tmp_path / "activation.db", 5000, tmp_path / "backups")
    init_database(settings)
    connection = get_connection(settings)
    MigrationRunner().migrate(connection, settings)
    parent = tmp_path / "roots"
    parent.mkdir()
    seed_path = tmp_path / "world.md"
    seed_bytes = b"# writer order world\n"
    seed_path.write_bytes(seed_bytes)
    order: list[str] = []
    store = RecordingPayloadStore(order)
    service = C4bActivationService(
        connection,
        operator_identity="operator-writer",
        payload_root=parent / "payloads",
        projection_root=parent / "projection",
        payload_store=store,
        seed_importer=LegacyWorldSeedImporter(
            seed_path, expected_sha256=hashlib.sha256(seed_bytes).hexdigest()
        ),
        workspace_root=tmp_path / "workspace",
        enforce_persistent_d_drive=False,
    )
    real_repository = service.repository
    real_writer = ProjectionActivationWriter
    original_version = real_writer.write_version
    original_pointer = real_writer.write_pointer
    original_marker = real_writer.write_marker

    class OrderedRepository:
        def __getattr__(self, name):
            return getattr(real_repository, name)

        def create_prepared(self, attempt, event):
            order.append(event.phase)
            return real_repository.create_prepared(attempt, event)

        def append_event(self, event):
            order.append(event.phase)
            return real_repository.append_event(event)

    def version(writer, bundle, identity):
        order.append("version")
        return original_version(writer, bundle, identity)

    def pointer(writer, identity):
        order.append("pointer")
        return original_pointer(writer, identity)

    def marker(writer, identity):
        order.append("marker")
        return original_marker(writer, identity)

    service.repository = OrderedRepository()
    monkeypatch.setattr(real_writer, "write_version", version)
    monkeypatch.setattr(real_writer, "write_pointer", pointer)
    monkeypatch.setattr(real_writer, "write_marker", marker)
    try:
        result = service.activate(
            CanonActivationRequest("project-writer-order", "writer-key", "sha256:" + "1" * 64)
        )
        assert result.status == "ACTIVATED"
        assert order == [
            "payload.put", "payload.read", "PREPARED", "version", "pointer",
            "READY_FOR_MARKER", "marker",
        ]
        assert (parent / "projection" / "activation.marker").is_file()
        assert [row[0] for row in connection.execute(
            "SELECT phase FROM canon_activation_event ORDER BY created_at, event_id"
        )] == ["PREPARED", "READY_FOR_MARKER"]
    finally:
        connection.close()


def test_missing_root_is_only_created_after_lock(tmp_path: Path) -> None:
    lock, root, writer = lock_and_writer(tmp_path)
    bundle, identity = bundle_and_identity()
    try:
        assert not root.exists()
        version = writer.write_version(bundle, identity)
        assert version.is_dir()
    finally:
        lock.release()


def test_existing_empty_root_is_allowed(tmp_path: Path) -> None:
    lock, root, writer = lock_and_writer(tmp_path)
    root.mkdir()
    bundle, identity = bundle_and_identity("project-empty")
    try:
        writer.write_version(bundle, identity)
        assert (root / "versions" / identity.version_id).is_dir()
    finally:
        lock.release()


def test_nonempty_root_is_not_overwritten(tmp_path: Path) -> None:
    lock, root, writer = lock_and_writer(tmp_path)
    root.mkdir()
    sentinel = root / "unknown.txt"
    sentinel.write_bytes(b"keep")
    bundle, identity = bundle_and_identity("project-nonempty")
    try:
        with pytest.raises(ProjectionActivationWriterError):
            writer.write_version(bundle, identity)
        assert sentinel.read_bytes() == b"keep"
        assert list(root.iterdir()) == [sentinel]
    finally:
        lock.release()


def test_partial_projection_is_not_repaired(tmp_path: Path) -> None:
    lock, root, writer = lock_and_writer(tmp_path)
    root.mkdir()
    (root / "current.pointer").write_bytes(b"partial")
    bundle, identity = bundle_and_identity("project-partial")
    try:
        with pytest.raises(ProjectionActivationWriterError):
            writer.write_version(bundle, identity)
        assert (root / "current.pointer").read_bytes() == b"partial"
    finally:
        lock.release()


def test_pre_marker_order_leaves_marker_absent(tmp_path: Path) -> None:
    lock, root, writer = lock_and_writer(tmp_path)
    bundle, identity = bundle_and_identity("project-order")
    try:
        pointer = writer.write_pre_marker(bundle, identity)
        assert pointer == ProjectionActivationWriter.pointer_bytes(identity)
        assert (root / "versions" / identity.version_id).is_dir()
        assert (root / "current.pointer").is_file()
        assert not (root / "activation.marker").exists()
    finally:
        lock.release()


def test_c4b_27_version_identity_fields_are_exact_and_canonical(tmp_path: Path) -> None:
    lock, root, writer = lock_and_writer(tmp_path)
    bundle, identity = bundle_and_identity("project-identity")
    try:
        version = writer.write_version(bundle, identity)
        data = (version / "bundle.identity.json").read_bytes()
        value = json.loads(data.decode("utf-8"))
        assert set(value) == {
            "project_id", "version_id", "bundle_schema_version",
            "bundle_ref_artifact_id", "bundle_content_hash", "manifest_hash", "world_hash",
        }
        assert json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode() == data
        assert value == identity.as_fields()
    finally:
        lock.release()


def test_c4b_28_pointer_is_canonical_and_atomically_replaced(tmp_path: Path, monkeypatch) -> None:
    lock, root, writer = lock_and_writer(tmp_path)
    bundle, identity = bundle_and_identity("project-pointer")
    try:
        writer.write_version(bundle, identity)
        import xiaoshuo.infrastructure.canon.projection_activation_writer as writer_module

        replaced: list[tuple[Path, Path]] = []
        original_replace = writer_module.os.replace

        def record_replace(source, target):
            replaced.append((Path(source), Path(target)))
            return original_replace(source, target)

        monkeypatch.setattr(writer_module.os, "replace", record_replace)
        data = writer.write_pointer(identity)
        assert data == ProjectionActivationWriter.pointer_bytes(identity)
        marker = writer.write_marker(identity)
        marker_value = json.loads(marker.decode("utf-8"))
        assert marker_value["pointer_content_hash"] == "sha256:" + hashlib.sha256(data).hexdigest()
        assert any(target == root / "current.pointer" and source.name.endswith(".tmp") for source, target in replaced)
        with pytest.raises(ProjectionActivationWriterError):
            writer.write_pointer(identity)
    finally:
        lock.release()


def test_c4b_29_marker_is_last_fence_and_binds_pointer_hash(tmp_path: Path) -> None:
    lock, root, writer = lock_and_writer(tmp_path)
    bundle, identity = bundle_and_identity("project-marker")
    try:
        writer.write_pre_marker(bundle, identity)
        marker = writer.write_marker(identity)
        assert marker == ProjectionActivationWriter.marker_bytes(
            identity, (root / "current.pointer").read_bytes()
        )
        value = json.loads(marker.decode("utf-8"))
        assert value["pointer_content_hash"].startswith("sha256:")
        with pytest.raises(ProjectionActivationWriterError):
            writer.write_marker(identity)
    finally:
        lock.release()


@pytest.mark.parametrize("stage", ["version", "pointer", "marker"])
@pytest.mark.parametrize("failure", ["flush", "fsync", "readback", "replace"])
def test_c4b_30_durable_file_failures_are_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str, failure: str
) -> None:
    import xiaoshuo.infrastructure.canon.projection_activation_writer as writer_module

    lock, root, writer = lock_and_writer(tmp_path)
    bundle, identity = bundle_and_identity("project-durable-" + stage + "-" + failure)
    if stage == "pointer":
        writer.write_version(bundle, identity)
    elif stage == "marker":
        writer.write_pre_marker(bundle, identity)

    if failure == "flush":
        original_open = writer_module.Path.open

        class FlushFailingFile:
            def __init__(self, real_file):
                self.real_file = real_file

            def __enter__(self):
                self.real_file.__enter__()
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return self.real_file.__exit__(exc_type, exc_value, traceback)

            def write(self, data):
                return self.real_file.write(data)

            def __getattr__(self, name):
                return getattr(self.real_file, name)

            def flush(self):
                raise OSError("forced flush failure")

            def fileno(self):
                return self.real_file.fileno()

        def fail_flush(path, *args, **kwargs):
            mode = kwargs.get("mode") or (args[0] if args else "r")
            if path.name.endswith(".tmp") and "w" in mode:
                return FlushFailingFile(original_open(path, *args, **kwargs))
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(writer_module.Path, "open", fail_flush)
    elif failure == "fsync":
        def fail_fsync(_fd: int) -> None:
            raise OSError("forced fsync failure")

        monkeypatch.setattr(writer_module.os, "fsync", fail_fsync)
    elif failure == "readback":
        original_read_bytes = writer_module.Path.read_bytes

        def fail_readback(path):
            if path.name.startswith(".") and path.name.endswith(".tmp"):
                return b"tampered"
            return original_read_bytes(path)

        monkeypatch.setattr(writer_module.Path, "read_bytes", fail_readback)
    else:
        monkeypatch.setattr(
            writer_module.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("forced replace failure"))
        )

    try:
        with pytest.raises(ProjectionActivationWriterError):
            if stage == "version":
                writer.write_version(bundle, identity)
            elif stage == "pointer":
                writer.write_pointer(identity)
            else:
                writer.write_marker(identity)
        target = {
            "version": root / "versions" / identity.version_id,
            "pointer": root / "current.pointer",
            "marker": root / "activation.marker",
        }[stage]
        if stage == "version":
            assert target.is_dir()
            assert list(target.rglob("*")) == []
        else:
            assert not target.exists()
            assert (root / "versions" / identity.version_id).is_dir()
            if stage == "marker":
                assert (root / "current.pointer").is_file()
        assert list(root.rglob(".*.tmp")) == []
    finally:
        monkeypatch.undo()
        lock.release()
