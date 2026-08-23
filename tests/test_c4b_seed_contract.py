"""C4B-01..07 and C4B-41: deterministic seed and payload contracts."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from xiaoshuo.infrastructure.canon.canonical_bundle import CanonicalBundle
from xiaoshuo.application.creation.errors import ActivationInputRejected
from xiaoshuo.infrastructure.canon.c4b_activation import C4bActivationService
from xiaoshuo.infrastructure.canon.immutable_payload_store import ImmutablePayloadStore
from xiaoshuo.infrastructure.canon.legacy_seed_importer import (
    WORLD_SEED_SHA256,
    LegacySeedImportError,
    LegacyWorldSeedImporter,
)
from xiaoshuo.infrastructure.persistence.sqlite.canon_activation_repository import (
    SqliteCanonActivationRepository,
)


WORLD_PATH = Path(__file__).resolve().parents[1] / "assets" / "canon" / "world.md"


class MemoryPayloadStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, data: bytes) -> str:
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        existing = self.objects.get(digest)
        if existing is not None and existing != data:
            raise AssertionError("payload collision")
        self.objects[digest] = data
        return digest

    def read(self, digest: str) -> bytes:
        return self.objects[digest]


def test_c4b_01_reads_only_explicit_world_path() -> None:
    importer = LegacyWorldSeedImporter(WORLD_PATH, expected_sha256=WORLD_SEED_SHA256)
    assert importer.seed_path == WORLD_PATH
    assert importer.read_world_bytes() == WORLD_PATH.read_bytes()


def test_c4b_02_world_bytes_are_not_normalized(tmp_path: Path) -> None:
    raw = b"# world\r\n\r\nkeep trailing bytes\r\n"
    path = tmp_path / "world.md"
    path.write_bytes(raw)
    importer = LegacyWorldSeedImporter(path, expected_sha256=hashlib.sha256(raw).hexdigest())
    result = importer.build_bundle("project-raw")
    assert result.bundle.world_md == raw
    assert result.bundle.world_hash == "sha256:" + hashlib.sha256(raw).hexdigest()


def test_c4b_03_world_hash_is_the_seed_digest() -> None:
    result = LegacyWorldSeedImporter(WORLD_PATH).build_bundle("project-world")
    assert result.seed_digest == "sha256:" + WORLD_SEED_SHA256
    assert result.bundle.world_hash == result.seed_digest


def test_c4b_04_manifest_has_exact_top_level_and_seed_fields(tmp_path: Path) -> None:
    raw = b"world\n"
    path = tmp_path / "world.md"
    path.write_bytes(raw)
    result = LegacyWorldSeedImporter(path, expected_sha256=hashlib.sha256(raw).hexdigest()).build_bundle(
        "project-manifest"
    )
    manifest = json.loads(result.bundle.manifest.decode("utf-8"))
    assert set(manifest) == {"manifest_schema_version", "project_id", "seed"}
    assert set(manifest["seed"]) == {"kind", "world_sha256"}
    assert manifest["seed"]["kind"] == "LEGACY_WORLD_MD"
    assert manifest["seed"]["world_sha256"] == result.seed_digest


def test_c4b_05_seed_manifest_is_canonical_utf8_json(tmp_path: Path) -> None:
    raw = "世界\n".encode("utf-8")
    path = tmp_path / "world.md"
    path.write_bytes(raw)
    result = LegacyWorldSeedImporter(path, expected_sha256=hashlib.sha256(raw).hexdigest()).build_bundle(
        "project-utf8"
    )
    assert result.bundle.manifest == json.dumps(
        json.loads(result.bundle.manifest.decode("utf-8")),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert result.bundle.to_bytes() == CanonicalBundle.from_bytes(result.bundle.to_bytes()).to_bytes()


@pytest.mark.parametrize(
    "raw,expected",
    [
        (b"not the approved seed", WORLD_SEED_SHA256),
        (b"\xff\xfe", hashlib.sha256(b"\xff\xfe").hexdigest()),
    ],
)
def test_c4b_06_seed_invalid_digest_or_encoding_is_fail_closed(
    tmp_path: Path, raw: bytes, expected: str
) -> None:
    path = tmp_path / "world.md"
    path.write_bytes(raw)
    with pytest.raises(LegacySeedImportError):
        LegacyWorldSeedImporter(path, expected_sha256=expected).build_bundle("project-invalid")


def test_c4b_07_seed_project_id_is_explicit_and_safe(tmp_path: Path) -> None:
    raw = b"world"
    path = tmp_path / "world.md"
    path.write_bytes(raw)
    importer = LegacyWorldSeedImporter(path, expected_sha256=hashlib.sha256(raw).hexdigest())
    for bad in ("", "..", "project/name", "project\x00name"):
        with pytest.raises(LegacySeedImportError):
            importer.build_bundle(bad)


def test_c4b_41_payload_bytes_and_digest_bind_to_bundle() -> None:
    raw = b"payload world"
    path = Path(__file__).parent / "_c4b_temp_world_never_written.md"
    # Use an in-memory explicit seed path without creating a project file.
    importer = LegacyWorldSeedImporter.__new__(LegacyWorldSeedImporter)
    importer.seed_path = path
    importer.expected_sha256 = hashlib.sha256(raw).hexdigest()
    importer.read_world_bytes = lambda: raw  # type: ignore[method-assign]
    result = importer.build_bundle("payload-project")
    store = MemoryPayloadStore()
    payload = result.bundle.to_bytes()
    digest = store.put(payload)
    assert digest == result.bundle.content_hash()
    assert store.read(digest) == payload


@pytest.mark.parametrize("adapter_name", ["seed_importer", "payload_store", "repository"])
def test_production_rejects_injected_adapters_before_any_write(
    tmp_path: Path, adapter_name: str
) -> None:
    injected = object()
    connection = sqlite3.connect(":memory:")
    try:
        with pytest.raises(ActivationInputRejected, match="injected adapters"):
            C4bActivationService(
                connection,
                operator_identity="operator",
                **{adapter_name: injected},
                enforce_persistent_d_drive=True,
            )
        assert connection.total_changes == 0
        assert list(tmp_path.iterdir()) == []
    finally:
        connection.close()


def test_production_constructs_only_approved_adapters() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        service = C4bActivationService(
            connection,
            operator_identity="operator",
            enforce_persistent_d_drive=True,
        )
        assert type(service.seed_importer) is LegacyWorldSeedImporter
        assert type(service.payload_store) is ImmutablePayloadStore
        assert type(service.repository) is SqliteCanonActivationRepository
    finally:
        connection.close()
