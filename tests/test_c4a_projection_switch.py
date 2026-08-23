"""C4A-16..24: independent lock and durable follow-on writer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from xiaoshuo.infrastructure.canon.c4a_projection_commit_lock import (
    C4aProjectionCommitLock,
    C4aProjectionLockConflict,
    C4aProjectionLockError,
)
from xiaoshuo.infrastructure.canon.c4a_projection_writer import (
    C4aProjectionIdentity,
    C4aProjectionWriter,
    C4aProjectionWriterError,
)
from xiaoshuo.infrastructure.canon.projection_activation import ProjectionActivationError

from test_c4a_apply import _case, _digest, _write_activation


def _target(case):
    identity = C4aProjectionIdentity(
        "project",
        "target-v1",
        case["target_ref"],
        case["target"].manifest_hash,
        case["target"].world_hash,
    )
    return identity


def test_c4a_commit_lock_requires_existing_valid_activation(tmp_path: Path) -> None:
    root = tmp_path / "missing"
    with pytest.raises(C4aProjectionLockError):
        C4aProjectionCommitLock(root, enforce_persistent_d_drive=False)


def test_c4a_lock_is_distinct_from_c4b_bootstrap_and_c4pre_lock(tmp_path: Path) -> None:
    case = _case(tmp_path)
    lock = C4aProjectionCommitLock(case["root"], enforce_persistent_d_drive=False)
    assert lock.lock_path == case["root"].parent / ".c4a-commit.lock"
    assert lock.lock_path.name not in {".c4b-bootstrap.lock", ".canon.lock"}


def test_competing_apply_loser_has_zero_file_and_sqlite_writes(tmp_path: Path) -> None:
    case = _case(tmp_path)
    first = C4aProjectionCommitLock(case["root"], enforce_persistent_d_drive=False)
    second = C4aProjectionCommitLock(case["root"], enforce_persistent_d_drive=False)
    first.acquire()
    before = {path.name: path.read_bytes() for path in case["root"].iterdir() if path.is_file()}
    try:
        with pytest.raises(C4aProjectionLockConflict):
            second.acquire()
        after = {path.name: path.read_bytes() for path in case["root"].iterdir() if path.is_file()}
        assert after == before
        assert case["conn"].execute("SELECT COUNT(*) FROM canon_apply_attempt").fetchone()[0] == 0
    finally:
        first.release()


def test_follow_on_writer_never_creates_root_or_overwrites_version(tmp_path: Path) -> None:
    case = _case(tmp_path)
    lock = C4aProjectionCommitLock(case["root"], enforce_persistent_d_drive=False)
    identity = _target(case)
    writer = C4aProjectionWriter(case["root"], lock)
    lock.acquire()
    try:
        writer.write_version(case["target"], identity)
        with pytest.raises(C4aProjectionWriterError):
            writer.write_version(case["target"], identity)
        assert (case["root"] / "versions" / "base-v1").is_dir()
        assert (case["root"] / "versions" / identity.version_id).is_dir()
    finally:
        lock.release()


def test_new_version_is_immutable_and_full_identity_verified(tmp_path: Path) -> None:
    case = _case(tmp_path)
    lock = C4aProjectionCommitLock(case["root"], enforce_persistent_d_drive=False)
    writer = C4aProjectionWriter(case["root"], lock)
    identity = _target(case)
    lock.acquire()
    try:
        version = writer.write_version(case["target"], identity)
        assert json.loads((version / "bundle.identity.json").read_text(encoding="utf-8")) == identity.as_fields()
        with pytest.raises(C4aProjectionWriterError):
            writer.write_version(case["target"], identity)
    finally:
        lock.release()


def test_pointer_replace_is_flush_fsync_readback_atomic(tmp_path: Path) -> None:
    case = _case(tmp_path)
    lock = C4aProjectionCommitLock(case["root"], enforce_persistent_d_drive=False)
    writer = C4aProjectionWriter(case["root"], lock)
    identity = _target(case)
    lock.acquire()
    try:
        writer.write_version(case["target"], identity)
        pointer = writer.write_pointer(identity)
        assert (case["root"] / "current.pointer").read_bytes() == pointer
        assert _digest(pointer) == _digest((case["root"] / "current.pointer").read_bytes())
    finally:
        lock.release()


def test_pointer_before_marker_transient_state_is_reader_fail_closed(tmp_path: Path) -> None:
    case = _case(tmp_path)
    lock = C4aProjectionCommitLock(case["root"], enforce_persistent_d_drive=False)
    writer = C4aProjectionWriter(case["root"], lock)
    identity = _target(case)
    lock.acquire()
    try:
        writer.write_version(case["target"], identity)
        writer.write_pointer(identity)
        with pytest.raises(RuntimeError):
            case["reader"].read_for_project("project")
        writer.write_marker(identity)
        assert case["reader"].read_for_project("project").version_id == "target-v1"
    finally:
        lock.release()


def test_marker_binds_exact_pointer_hash_and_identity(tmp_path: Path) -> None:
    case = _case(tmp_path)
    lock = C4aProjectionCommitLock(case["root"], enforce_persistent_d_drive=False)
    writer = C4aProjectionWriter(case["root"], lock)
    identity = _target(case)
    lock.acquire()
    try:
        writer.write_version(case["target"], identity)
        pointer = writer.write_pointer(identity)
        marker = writer.write_marker(identity)
        fields = json.loads(marker.decode("utf-8"))
        assert fields["pointer_content_hash"] == _digest(pointer)
        assert fields["version_id"] == identity.version_id
    finally:
        lock.release()


def test_version_pointer_marker_replacement_failure_is_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _case(tmp_path)
    lock = C4aProjectionCommitLock(case["root"], enforce_persistent_d_drive=False)
    writer = C4aProjectionWriter(case["root"], lock)
    identity = _target(case)
    old_pointer = (case["root"] / "current.pointer").read_bytes()
    lock.acquire()
    try:
        writer.write_version(case["target"], identity)
        monkeypatch.setattr("xiaoshuo.infrastructure.canon.c4a_projection_writer.os.replace", lambda *_args: (_ for _ in ()).throw(OSError("replace")))
        with pytest.raises(C4aProjectionWriterError):
            writer.write_pointer(identity)
        assert (case["root"] / "current.pointer").read_bytes() == old_pointer
    finally:
        lock.release()
