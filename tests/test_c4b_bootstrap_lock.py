"""C4B-22..25: bootstrap lock and zero-write competition."""

from __future__ import annotations

import multiprocessing
import hashlib
import sqlite3
from pathlib import Path

import pytest

from xiaoshuo.infrastructure.canon.c4b_bootstrap_lock import (
    BootstrapLockConflict,
    BootstrapLockError,
    C4bBootstrapLock,
    preflight_activation_roots,
)
from xiaoshuo.application.creation.canon_activation import CanonActivationRequest
from xiaoshuo.infrastructure.canon.c4b_activation import C4bActivationService
from xiaoshuo.infrastructure.canon.legacy_seed_importer import LegacyWorldSeedImporter
from xiaoshuo.infrastructure.persistence.sqlite.connection import get_connection
from xiaoshuo.infrastructure.persistence.sqlite.maintenance import init_database
from xiaoshuo.infrastructure.persistence.sqlite.migration_runner import MigrationRunner
from xiaoshuo.infrastructure.persistence.sqlite.settings import SQLitePersistenceSettings


def child_competitor(payload: str, projection: str, lock_path: str, queue) -> None:
    try:
        lock = C4bBootstrapLock(
            payload,
            projection,
            lock_path=lock_path,
            enforce_persistent_d_drive=False,
        )
        lock.acquire()
    except Exception as exc:  # pragma: no cover - asserted through IPC
        queue.put(type(exc).__name__)
    else:  # pragma: no cover - should never win the occupied lease
        queue.put("ACQUIRED")
        lock.release()


class DiskPayloadStore:
    def __init__(self, root: str) -> None:
        self.root = Path(root)

    def put(self, data: bytes) -> str:
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / digest[7:]).write_bytes(data)
        return digest

    def read(self, digest: str) -> bytes:
        return (self.root / digest[7:]).read_bytes()


def child_service_competitor(
    db_path: str,
    seed_path: str,
    payload_root: str,
    projection_root: str,
    queue,
) -> None:
    settings = SQLitePersistenceSettings(db_path, 5000)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        service = C4bActivationService(
            conn,
            operator_identity="operator-child",
            payload_root=payload_root,
            projection_root=projection_root,
            payload_store=DiskPayloadStore(payload_root),
            seed_importer=LegacyWorldSeedImporter(
                seed_path, expected_sha256=hashlib.sha256(Path(seed_path).read_bytes()).hexdigest()
            ),
            workspace_root=Path(db_path).parent / "workspace",
            enforce_persistent_d_drive=False,
        )
        service.activate(CanonActivationRequest("project-competition", "key-competition", "sha256:" + "a" * 64))
    except Exception as exc:  # pragma: no cover - asserted through IPC
        queue.put(type(exc).__name__)
    else:  # pragma: no cover - the occupied lock must win
        queue.put("ACTIVATED")
    finally:
        conn.close()


def test_c4b_22_missing_roots_do_not_exist_before_lock(tmp_path: Path) -> None:
    parent = tmp_path / "c4b"
    parent.mkdir()
    payload = parent / "payloads"
    projection = parent / "projection"
    lock = C4bBootstrapLock(
        payload,
        projection,
        lock_path=parent / ".c4b-bootstrap.lock",
        enforce_persistent_d_drive=False,
    )
    assert not payload.exists()
    assert not projection.exists()
    lock.acquire()
    try:
        assert lock.held
        assert not payload.exists()
        assert not projection.exists()
    finally:
        lock.release()


def test_c4b_25_real_second_process_competitor_has_zero_root_writes(tmp_path: Path) -> None:
    parent = tmp_path / "competition"
    parent.mkdir()
    payload = parent / "payloads"
    projection = parent / "projection"
    lock_path = parent / ".c4b-bootstrap.lock"
    owner = C4bBootstrapLock(
        payload,
        projection,
        lock_path=lock_path,
        enforce_persistent_d_drive=False,
    )
    owner.acquire()
    try:
        context = multiprocessing.get_context("spawn")
        queue = context.Queue()
        process = context.Process(
            target=child_competitor,
            args=(str(payload), str(projection), str(lock_path), queue),
        )
        process.start()
        process.join(timeout=20)
        assert process.exitcode == 0
        assert queue.get(timeout=5) == "BootstrapLockConflict"
        assert not payload.exists()
        assert not projection.exists()
        assert not (parent / "current.pointer").exists()
        assert not (parent / "activation.marker").exists()
    finally:
        owner.release()


def test_c4b_24_real_service_competitor_has_zero_payload_sqlite_projection_writes(tmp_path: Path) -> None:
    parent = tmp_path / "service-competition"
    parent.mkdir()
    db_settings = SQLitePersistenceSettings(parent / "activation.db", 5000, parent / "backups")
    init_database(db_settings)
    conn = get_connection(db_settings)
    MigrationRunner().migrate(conn, db_settings)
    seed_path = parent / "world.md"
    seed_path.write_bytes(b"competition world\n")
    payload = parent / "payloads"
    projection = parent / "projection"
    owner = C4bBootstrapLock(
        payload,
        projection,
        lock_path=parent / ".c4b-bootstrap.lock",
        enforce_persistent_d_drive=False,
    )
    owner.acquire()
    try:
        before_facts = [
            conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("canon_activation_attempt", "canon_activation_event", "chapter_task", "canon_commit_journal")
        ]
        context = multiprocessing.get_context("spawn")
        queue = context.Queue()
        process = context.Process(
            target=child_service_competitor,
            args=(str(parent / "activation.db"), str(seed_path), str(payload), str(projection), queue),
        )
        process.start()
        process.join(timeout=20)
        assert process.exitcode == 0
        assert queue.get(timeout=5) == "ActivationConflict"
        after_facts = [
            conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("canon_activation_attempt", "canon_activation_event", "chapter_task", "canon_commit_journal")
        ]
        assert after_facts == before_facts == [0, 0, 0, 0]
        assert not payload.exists()
        assert not projection.exists()
    finally:
        owner.release()
        conn.close()


def test_stale_lock_is_not_reclaimed(tmp_path: Path) -> None:
    parent = tmp_path / "stale"
    parent.mkdir()
    payload = parent / "payloads"
    projection = parent / "projection"
    lock_path = parent / ".c4b-bootstrap.lock"
    lock_path.write_text("unknown-owner", encoding="ascii")
    lock = C4bBootstrapLock(
        payload,
        projection,
        lock_path=lock_path,
        enforce_persistent_d_drive=False,
    )
    with pytest.raises(BootstrapLockConflict):
        lock.acquire()
    assert lock_path.read_text(encoding="ascii") == "unknown-owner"
    assert not payload.exists()
    assert not projection.exists()


def test_release_failure_is_fail_closed(tmp_path: Path) -> None:
    parent = tmp_path / "release"
    parent.mkdir()
    lock = C4bBootstrapLock(
        parent / "payloads",
        parent / "projection",
        lock_path=parent / ".c4b-bootstrap.lock",
        enforce_persistent_d_drive=False,
    )
    lock.acquire()
    lock.path.unlink()
    with pytest.raises(BootstrapLockError):
        lock.release()
    assert not lock.held


@pytest.mark.parametrize(
    "payload,projection",
    [
        (r"D:\tmp\c4b-payload", r"D:\persist\c4b-projection"),
        (r"D:\persist\same", r"D:\persist\same"),
        (r"D:\persist\parent", r"D:\persist\parent\child"),
    ],
)
def test_lock_unsafe_or_overlapping_roots_are_rejected(payload: str, projection: str) -> None:
    with pytest.raises(BootstrapLockError):
        preflight_activation_roots(payload, projection, enforce_persistent_d_drive=True)


def test_c4b_23_raw_reparse_is_checked_before_resolve_and_production_lock_path_is_fixed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import xiaoshuo.infrastructure.canon.c4b_bootstrap_lock as lock_module

    payload = tmp_path / "payload"
    projection = tmp_path / "projection"
    payload.mkdir()
    original_resolved = lock_module._resolved
    monkeypatch.setattr(lock_module, "_is_reparse", lambda path: path == payload)
    monkeypatch.setattr(
        lock_module,
        "_resolved",
        lambda _path: pytest.fail("raw reparse inspection must precede resolve"),
    )
    with pytest.raises(BootstrapLockError, match="reparse"):
        preflight_activation_roots(payload, projection, enforce_persistent_d_drive=False)

    projection.mkdir()
    monkeypatch.setattr(lock_module, "_is_reparse", lambda _path: False)
    monkeypatch.setattr(lock_module, "_resolved", original_resolved)
    monkeypatch.setattr(
        lock_module,
        "preflight_activation_roots",
        lambda *_args, **_kwargs: lock_module.ActivationRootPreflight(payload, projection),
    )
    escaped_parent = tmp_path / "escaped-lock-parent"
    escaped_parent.mkdir()
    with pytest.raises(BootstrapLockError, match="fixed"):
        C4bBootstrapLock(
            payload,
            projection,
            lock_path=escaped_parent / ".c4b-bootstrap.lock",
            enforce_persistent_d_drive=True,
        )
    assert not (escaped_parent / ".c4b-bootstrap.lock").exists()
