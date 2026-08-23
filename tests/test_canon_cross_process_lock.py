from __future__ import annotations

import hashlib
import json
import multiprocessing
from pathlib import Path

import pytest

from xiaoshuo.infrastructure.canon.projection_lock import ProjectionLock, ProjectionLockError
from xiaoshuo.infrastructure.canon import projection_activation
from xiaoshuo.infrastructure.canon.canonical_bundle import CanonicalBundle


def _canon(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _write_activation(root: Path) -> tuple[CanonicalBundle, object]:
    bundle = CanonicalBundle(1, b'{"revision":1}', b"# world")
    version = root / "versions" / bundle.content_hash().removeprefix("sha256:")
    version.mkdir(parents=True)
    (version / "manifest.json").write_bytes(bundle.manifest)
    (version / "world.md").write_bytes(bundle.world_md)
    identity = {
        "project_id": "project-1", "version_id": version.name,
        "bundle_schema_version": 1, "bundle_ref_artifact_id": "bundle-ref",
        "bundle_content_hash": bundle.content_hash(), "manifest_hash": bundle.manifest_hash,
        "world_hash": bundle.world_hash,
    }
    pointer = {"pointer_schema_version": 1, **identity}
    pointer_bytes = _canon(pointer)
    marker = {
        "marker_schema_version": 1,
        "pointer_content_hash": "sha256:" + hashlib.sha256(pointer_bytes).hexdigest(),
        **pointer,
    }
    (version / "bundle.identity.json").write_bytes(_canon(identity))
    (root / "current.pointer").write_bytes(pointer_bytes)
    (root / "activation.marker").write_bytes(_canon(marker))

    def resolver(artifact_id: str):
        return projection_activation.ActivationIdentity(
            "project-1", version.name, 1, artifact_id,
            bundle.content_hash(), bundle.manifest_hash, bundle.world_hash,
        ).bundle_ref

    return bundle, resolver


def _child_competes(root_text: str, result_queue) -> None:
    root = Path(root_text)
    projection_activation._production_root = lambda: root
    bundle = CanonicalBundle(1, b'{"revision":1}', b"# world")

    def resolver(artifact_id: str):
        return projection_activation.ActivationIdentity(
            "project-1", bundle.content_hash().removeprefix("sha256:"), 1, artifact_id,
            bundle.content_hash(), bundle.manifest_hash, bundle.world_hash,
        ).bundle_ref

    try:
        ProjectionLock(root, artifact_ref_resolver=resolver).acquire()
    except ProjectionLockError:
        result_queue.put("rejected")
    else:
        result_queue.put("acquired")


def _snapshot(root: Path) -> dict[str, bytes | None]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes() if path.is_file() else None
        for path in root.rglob("*")
    }


def test_lock_does_not_create_missing_root(tmp_path: Path) -> None:
    root = tmp_path / "missing"
    with pytest.raises(ProjectionLockError):
        ProjectionLock(root).acquire()
    assert not root.exists()


def test_stale_or_occupied_lock_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "projection"
    root.mkdir()
    (root / "current.pointer").write_text("{}", encoding="utf-8")
    (root / ".projection.lock").write_text("stale", encoding="ascii")
    with pytest.raises(ProjectionLockError):
        ProjectionLock(root).acquire()


def test_lock_name_is_fixed_and_cannot_escape_root(tmp_path: Path) -> None:
    with pytest.raises(ProjectionLockError, match="fixed"):
        ProjectionLock(tmp_path / "projection", "../outside.lock")


def test_valid_lock_lease_and_real_second_process_competition_are_zero_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "projection"
    root.mkdir()
    bundle, resolver = _write_activation(root)
    monkeypatch.setattr(projection_activation, "_production_root", lambda: root)
    holder = ProjectionLock(root, artifact_ref_resolver=resolver).acquire()
    before = _snapshot(root)
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    competitor = context.Process(target=_child_competes, args=(str(root), result_queue))
    competitor.start()
    competitor.join(15)
    assert competitor.exitcode == 0
    assert result_queue.get(timeout=5) == "rejected"
    assert _snapshot(root) == before
    assert (root / ".projection.lock").exists()
    holder.release()
    assert not (root / ".projection.lock").exists()


def test_lock_pointer_and_release_decode_errors_are_stable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "projection"
    root.mkdir()
    (root / "current.pointer").write_bytes(b"\xff")
    monkeypatch.setattr(projection_activation, "_production_root", lambda: root)
    with pytest.raises(ProjectionLockError, match="trusted"):
        ProjectionLock(root).acquire()

    bundle, resolver = _write_activation(root)
    lock = ProjectionLock(root, artifact_ref_resolver=resolver).acquire()
    (root / ".projection.lock").write_bytes(b"\xff")
    with pytest.raises(ProjectionLockError, match="release"):
        lock.release()
    assert (root / ".projection.lock").exists()
