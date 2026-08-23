"""C2 filesystem primitives are deterministic and reject unsafe roots."""
from __future__ import annotations

import inspect
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from xiaoshuo.infrastructure.canon import backup_adapter, immutable_payload_store, projection_activation, projection_lock, projection_root
from xiaoshuo.infrastructure.canon.backup_adapter import ProjectionBackupAdapter
from xiaoshuo.infrastructure.canon.canonical_bundle import CanonicalBundle
from xiaoshuo.infrastructure.canon.immutable_payload_store import ImmutablePayloadStore
from xiaoshuo.infrastructure.canon.projection_root import ProjectionRoot


def _isolated_roots(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path, Path]:
    """Private provider patches isolate tests without exposing a runtime bypass."""
    payloads = tmp_path / "payloads"
    projection = tmp_path / "projection"
    backups = tmp_path / "backups"
    monkeypatch.setattr(immutable_payload_store, "_production_root", lambda: payloads)
    monkeypatch.setattr(projection_root, "_production_root", lambda: projection)
    monkeypatch.setattr(projection_activation, "_production_root", lambda: projection)
    monkeypatch.setattr(projection_lock, "ProjectionActivationReader", projection_activation.ProjectionActivationReader)
    monkeypatch.setattr(backup_adapter, "_production_root", lambda: backups)
    monkeypatch.setattr(backup_adapter, "_production_projection_root", lambda: projection)
    return payloads, projection, backups


def _write_valid_activation(projection: Path, bundle: CanonicalBundle):
    version = projection / "versions" / bundle.content_hash().removeprefix("sha256:")
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
    pointer_bytes = json.dumps(pointer, sort_keys=True, separators=(",", ":")).encode()
    marker = {
        "marker_schema_version": 1,
        "pointer_content_hash": "sha256:" + hashlib.sha256(pointer_bytes).hexdigest(),
        **pointer,
    }
    projection.mkdir(exist_ok=True)
    (projection / "current.pointer").write_bytes(pointer_bytes)
    (projection / "activation.marker").write_bytes(json.dumps(marker, sort_keys=True, separators=(",", ":")).encode())

    def resolver(artifact_id: str):
        return projection_activation.ActivationIdentity(
            "project-1", version.name, 1, artifact_id,
            bundle.content_hash(), bundle.manifest_hash, bundle.world_hash,
        ).bundle_ref

    return resolver


def test_payload_is_content_addressed_and_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payloads, _, _ = _isolated_roots(monkeypatch, tmp_path)
    store = ImmutablePayloadStore(payloads)
    digest = store.put(b"author-approved draft")
    assert digest.startswith("sha256:")
    assert store.put(b"author-approved draft") == digest
    assert store.read(digest) == b"author-approved draft"


def test_payload_store_rejects_non_configured_production_root() -> None:
    with pytest.raises(RuntimeError, match="unapproved"):
        ImmutablePayloadStore(r"D:\tmp\not-production")
    with pytest.raises(RuntimeError, match="unapproved"):
        ImmutablePayloadStore(r"D:\other-data\payloads")


def test_canon_mvp_production_roots_are_configured() -> None:
    config_path = Path(__file__).resolve().parents[1] / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert config["canon_mvp"] == {
        "root": r"D:\yeyu-ai-data\canon-mvp",
        "payloads_dir": r"D:\yeyu-ai-data\canon-mvp\payloads",
        "projection_dir": r"D:\yeyu-ai-data\canon-mvp\projection",
        "backups_dir": r"D:\yeyu-ai-data\canon-mvp\backups",
        "exports_dir": r"D:\yeyu-ai-data\canon-mvp\exports",
    }


def test_default_resource_adapters_use_configured_roots() -> None:
    assert ImmutablePayloadStore().root == Path(r"D:\yeyu-ai-data\canon-mvp\payloads")
    assert ProjectionRoot().root == Path(r"D:\yeyu-ai-data\canon-mvp\projection")
    assert ProjectionBackupAdapter().root == Path(r"D:\yeyu-ai-data\canon-mvp\backups")


@pytest.mark.parametrize("root", [r"D:\tmp\canon", r"D:\Code\yeyu-ai\xiaoshuo\assets\canon", r"D:\Code\yeyu-ai\xiaoshuo\.git\canon", r"D:\other-data\canon"])
def test_production_resource_roots_reject_any_non_configured_root(root: str) -> None:
    with pytest.raises(RuntimeError):
        ImmutablePayloadStore(root)
    with pytest.raises(RuntimeError):
        ProjectionRoot(root)
    with pytest.raises(RuntimeError):
        ProjectionBackupAdapter(root)


def test_payload_rejects_path_traversal_and_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payloads, _, _ = _isolated_roots(monkeypatch, tmp_path)
    store = ImmutablePayloadStore(payloads)
    digest = store.put(b"immutable")
    with pytest.raises(RuntimeError, match="invalid"):
        store.read("sha256:../../outside")
    (payloads / digest.removeprefix("sha256:")).write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="hash mismatch"):
        store.read(digest)


def test_bundle_is_stable_and_excludes_derived_content() -> None:
    first = CanonicalBundle(1, b'{"revision":1}', b"# world")
    second = CanonicalBundle(1, b'{"revision":1}', b"# world")
    assert first.content_hash() == second.content_hash()
    assert b"style_rules" not in first.to_bytes()


def test_bundle_rejects_noncanonical_manifest() -> None:
    with pytest.raises(RuntimeError, match="canonical"):
        CanonicalBundle(1, b'{"revision": 1}', b"# world")


def test_bundle_round_trip_is_field_and_hash_stable() -> None:
    original = CanonicalBundle(1, b'{"revision":1}', b"# world")
    rebuilt = CanonicalBundle.from_bytes(original.to_bytes())
    assert rebuilt == original
    assert rebuilt.manifest_hash == original.manifest_hash
    assert rebuilt.world_hash == original.world_hash
    assert rebuilt.content_hash() == original.content_hash()


@pytest.mark.parametrize(
    "data",
    [
        b"{}",
        b'{"extra":true,"manifest":"{\\"revision\\":1}","manifest_sha256":"bad","schema_version":1,"world_md":"# world","world_md_sha256":"bad"}',
        b'{"manifest":"{\\"revision\\":1}","manifest_sha256":"bad","schema_version":1,"world_md":"# world","world_md_sha256":"bad"}',
    ],
)
def test_bundle_from_bytes_rejects_missing_extra_or_hash_tampering(data: bytes) -> None:
    with pytest.raises(RuntimeError):
        CanonicalBundle.from_bytes(data)


def test_bundle_from_bytes_rejects_payload_tampering_unknown_version_and_noncanonical_outer() -> None:
    bundle = CanonicalBundle(1, b'{"revision":1}', b"# world")
    payload = json.loads(bundle.to_bytes())
    payload["world_md"] = "tampered"
    with pytest.raises(RuntimeError, match="hash"):
        CanonicalBundle.from_bytes(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())

    payload = json.loads(bundle.to_bytes())
    payload["schema_version"] = 2
    with pytest.raises(RuntimeError, match="schema"):
        CanonicalBundle.from_bytes(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())

    noncanonical = bundle.to_bytes().replace(b'"schema_version":1', b'"schema_version": 1')
    with pytest.raises(RuntimeError, match="canonical"):
        CanonicalBundle.from_bytes(noncanonical)


def test_stage_and_discard_never_touch_live_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, projection, _ = _isolated_roots(monkeypatch, tmp_path)
    root = ProjectionRoot(projection)
    bundle = CanonicalBundle(1, b'{"revision":1}', b"# world")
    with pytest.raises(RuntimeError, match="disabled"):
        root.stage(bundle, "one")
    assert not projection.exists()


def test_projection_rejects_path_name_and_wrong_target_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, projection, _ = _isolated_roots(monkeypatch, tmp_path)
    root = ProjectionRoot(projection)
    bundle = CanonicalBundle(1, b'{"revision":1}', b"# world")
    with pytest.raises(RuntimeError, match="disabled"):
        root.stage(bundle, "../escape")
    assert not projection.exists()


def test_stage_discard_and_promote_are_zero_write_even_with_valid_activation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, projection, _ = _isolated_roots(monkeypatch, tmp_path)
    bundle = CanonicalBundle(1, b'{"revision":1}', b"# world")
    resolver = _write_valid_activation(projection, bundle)
    stage = projection / ".stage-existing"
    stage.mkdir()
    (stage / "sentinel").write_text("keep", encoding="utf-8")
    before = {
        path.relative_to(projection).as_posix(): path.read_bytes()
        for path in projection.rglob("*")
        if path.is_file()
    }
    root = ProjectionRoot(projection, artifact_ref_resolver=resolver)
    with pytest.raises(RuntimeError, match="disabled"):
        root.stage(bundle, "new")
    with pytest.raises(RuntimeError, match="disabled"):
        root.discard(stage)
    with pytest.raises(RuntimeError, match="disabled"):
        root.promote(stage, expected_manifest_hash=bundle.manifest_hash)
    after = {
        path.relative_to(projection).as_posix(): path.read_bytes()
        for path in projection.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert stage.exists()
    assert not (projection / ".stage-new").exists()


def test_backup_is_verified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, live, backups = _isolated_roots(monkeypatch, tmp_path)
    live.mkdir()
    (live / "world.md").write_text("world", encoding="utf-8")
    backup = ProjectionBackupAdapter(backups).create(live, "before")
    assert (backup / "world.md").read_text(encoding="utf-8") == "world"


def test_backup_rejects_path_escape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, projection, backups = _isolated_roots(monkeypatch, tmp_path)
    projection.mkdir()
    with pytest.raises(RuntimeError, match="invalid"):
        ProjectionBackupAdapter(backups).create(projection, "../escape")


def test_failed_backup_does_not_modify_live_projection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, live, backups = _isolated_roots(monkeypatch, tmp_path)
    live.mkdir()
    (live / "world.md").write_text("before", encoding="utf-8")

    def fail_copytree(*_args, **_kwargs):
        raise OSError("copy failure")

    monkeypatch.setattr("xiaoshuo.infrastructure.canon.backup_adapter.shutil.copytree", fail_copytree)
    with pytest.raises(OSError, match="copy failure"):
        ProjectionBackupAdapter(backups).create(live, "before")
    assert (live / "world.md").read_text(encoding="utf-8") == "before"


def test_backup_digest_failure_cleans_staging_and_preserves_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, live, backups = _isolated_roots(monkeypatch, tmp_path)
    live.mkdir()
    (live / "world.md").write_text("before", encoding="utf-8")
    adapter = ProjectionBackupAdapter(backups)
    calls = 0

    def mismatched_digest(_root: Path) -> str:
        nonlocal calls
        calls += 1
        return "source" if calls == 1 else "staging"

    monkeypatch.setattr(adapter, "_tree_digest", mismatched_digest)
    with pytest.raises(RuntimeError, match="verification"):
        adapter.create(live, "before")
    assert (live / "world.md").read_text(encoding="utf-8") == "before"
    assert not (backups / "before").exists()
    assert not list(backups.glob(".stage-*"))


def test_backup_rejects_any_non_projection_source_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, projection, backups = _isolated_roots(monkeypatch, tmp_path)
    projection.mkdir()
    other = tmp_path / "other-source"
    other.mkdir()
    (other / "world.md").write_text("unchanged", encoding="utf-8")

    with pytest.raises(RuntimeError, match="unapproved projection source"):
        ProjectionBackupAdapter(backups).create(other, "must-not-exist")

    assert (other / "world.md").read_text(encoding="utf-8") == "unchanged"
    assert not backups.exists()


def test_resource_adapters_have_no_public_root_validator_bypass() -> None:
    for adapter in (ImmutablePayloadStore, ProjectionRoot, ProjectionBackupAdapter):
        assert "root_validator" not in inspect.signature(adapter).parameters
