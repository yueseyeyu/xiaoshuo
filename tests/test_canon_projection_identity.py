from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from xiaoshuo.infrastructure.canon import projection_activation
from xiaoshuo.infrastructure.canon.canonical_bundle import CanonicalBundle


def _canon(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _activated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, CanonicalBundle]:
    root = tmp_path / "projection"
    monkeypatch.setattr(projection_activation, "_production_root", lambda: root)
    bundle = CanonicalBundle(1, b'{"revision":1}', b"# world")
    version = root / "versions" / bundle.content_hash().removeprefix("sha256:")
    version.mkdir(parents=True)
    (version / "manifest.json").write_bytes(bundle.manifest)
    (version / "world.md").write_bytes(bundle.world_md)
    identity = {
        "project_id": "project-1", "version_id": version.name,
        "bundle_schema_version": 1, "bundle_ref_artifact_id": "bundle-ref",
        "bundle_content_hash": bundle.content_hash(),
        "manifest_hash": bundle.manifest_hash, "world_hash": bundle.world_hash,
    }
    (version / "bundle.identity.json").write_bytes(_canon(identity))
    pointer = {"pointer_schema_version": 1, **identity}
    pointer_bytes = _canon(pointer)
    marker = {"marker_schema_version": 1, "pointer_content_hash": _sha(pointer_bytes), "pointer_schema_version": 1, **identity}
    root.mkdir(exist_ok=True)
    (root / "current.pointer").write_bytes(pointer_bytes)
    (root / "activation.marker").write_bytes(_canon(marker))
    return root, bundle


def test_reader_validates_complete_project_bound_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, bundle = _activated(tmp_path, monkeypatch)
    resolver = lambda artifact_id: projection_activation.ActivationIdentity(
        "project-1", next((root / "versions").iterdir()).name, 1, artifact_id,
        bundle.content_hash(), bundle.manifest_hash, bundle.world_hash
    ).bundle_ref
    identity = projection_activation.ProjectionActivationReader(root, artifact_ref_resolver=resolver).read_for_project("project-1")
    assert identity.bundle_content_hash == bundle.content_hash()
    assert identity.manifest_hash == bundle.manifest_hash


def test_reader_rejects_world_only_tamper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, _ = _activated(tmp_path, monkeypatch)
    (root / "versions").glob("*")
    version = next((root / "versions").iterdir())
    (version / "world.md").write_bytes(b"tampered")
    with pytest.raises(projection_activation.ProjectionActivationError):
        projection_activation.ProjectionActivationReader(root, artifact_ref_resolver=lambda _id: None).read_for_project("project-1")


def test_reader_rejects_manifest_only_tamper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, _ = _activated(tmp_path, monkeypatch)
    version = next((root / "versions").iterdir())
    (version / "manifest.json").write_bytes(b'{"revision":2}')
    with pytest.raises(projection_activation.ProjectionActivationError):
        projection_activation.ProjectionActivationReader(root, artifact_ref_resolver=lambda _id: None).read_for_project("project-1")


def test_reader_rejects_marker_pointer_hash_tamper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, _ = _activated(tmp_path, monkeypatch)
    marker = json.loads((root / "activation.marker").read_bytes())
    marker["pointer_content_hash"] = _sha(b"different-pointer")
    (root / "activation.marker").write_bytes(_canon(marker))
    with pytest.raises(projection_activation.ProjectionActivationError):
        projection_activation.ProjectionActivationReader(root, artifact_ref_resolver=lambda _id: None).read_for_project("project-1")


def test_reader_rejects_registry_artifact_id_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, bundle = _activated(tmp_path, monkeypatch)
    version_id = next((root / "versions").iterdir()).name

    def resolver(_artifact_id):
        return projection_activation.ActivationIdentity(
            "project-1", version_id, 1, "different-ref", bundle.content_hash(),
            bundle.manifest_hash, bundle.world_hash,
        ).bundle_ref

    with pytest.raises(projection_activation.ProjectionActivationError, match="registry"):
        projection_activation.ProjectionActivationReader(root, artifact_ref_resolver=resolver).read_for_project("project-1")


def test_reader_rejects_dot_version_path_component(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, _ = _activated(tmp_path, monkeypatch)
    pointer = json.loads((root / "current.pointer").read_bytes())
    pointer["version_id"] = "."
    pointer_bytes = _canon(pointer)
    marker = json.loads((root / "activation.marker").read_bytes())
    marker["version_id"] = "."
    marker["pointer_content_hash"] = _sha(pointer_bytes)
    (root / "current.pointer").write_bytes(pointer_bytes)
    (root / "activation.marker").write_bytes(_canon(marker))
    with pytest.raises(projection_activation.ProjectionActivationError, match="version_id"):
        projection_activation.ProjectionActivationReader(root, artifact_ref_resolver=lambda _id: None).read_for_project("project-1")


def test_reader_rejects_symlink_version_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, _ = _activated(tmp_path, monkeypatch)
    version = next((root / "versions").iterdir())
    outside = tmp_path / "outside-version"
    shutil.copytree(version, outside)
    shutil.rmtree(version)
    try:
        version.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Windows symlink creation is unavailable")
    with pytest.raises(projection_activation.ProjectionActivationError, match="escapes|symlink"):
        projection_activation.ProjectionActivationReader(root, artifact_ref_resolver=lambda _id: None).read_for_project("project-1")


def test_reader_rejects_cross_project_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, _ = _activated(tmp_path, monkeypatch)
    marker = json.loads((root / "activation.marker").read_bytes())
    marker["project_id"] = "other"
    (root / "activation.marker").write_bytes(_canon(marker))
    with pytest.raises(projection_activation.ProjectionActivationError):
        projection_activation.ProjectionActivationReader(root, artifact_ref_resolver=lambda _id: None).read_for_project("project-1")
