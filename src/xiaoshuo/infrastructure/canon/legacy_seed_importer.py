"""Deterministic, single-file C4b legacy-world seed import."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from xiaoshuo import PROJECT_ROOT

from .canonical_bundle import CanonicalBundle, CanonicalBundleError


WORLD_SEED_SHA256 = "8c0fb4c7c2294ce25ff399e01ed340a3616124ab6096d2a8f622973c4883f85e"


class LegacySeedImportError(RuntimeError):
    """The explicit legacy world input is missing, unsafe, or inconsistent."""


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _project_id(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value in {".", ".."}
        or "\x00" in value
        or Path(value).name != value
        or any(char in '<>:/\\"|?*' for char in value)
        or value.endswith((" ", "."))
    ):
        raise LegacySeedImportError("project_id must be an explicit safe identifier")
    return value


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class LegacySeedBundle:
    """The raw seed digest and deterministic bundle produced from it."""

    seed_digest: str
    bundle: CanonicalBundle


class LegacyWorldSeedImporter:
    """Read exactly one explicitly configured ``world.md`` file."""

    def __init__(
        self,
        seed_path: Path | str | None = None,
        *,
        expected_sha256: str = WORLD_SEED_SHA256,
    ) -> None:
        self.seed_path = Path(seed_path) if seed_path is not None else PROJECT_ROOT / "assets" / "canon" / "world.md"
        if (
            not isinstance(expected_sha256, str)
            or len(expected_sha256) != 64
            or any(char not in "0123456789abcdef" for char in expected_sha256)
        ):
            raise LegacySeedImportError("expected seed digest is invalid")
        self.expected_sha256 = expected_sha256

    def read_world_bytes(self) -> bytes:
        """Read raw bytes without normalization or directory discovery."""
        try:
            path = self.seed_path
            if not path.is_file() or path.is_symlink():
                raise LegacySeedImportError("explicit world.md seed is not a regular file")
            if getattr(path.stat(), "st_file_attributes", 0) & 0x400:
                raise LegacySeedImportError("explicit world.md seed is a reparse point")
            data = path.read_bytes()
        except LegacySeedImportError:
            raise
        except OSError as exc:
            raise LegacySeedImportError("explicit world.md seed cannot be read") from exc
        if _digest(data) != self.expected_sha256:
            raise LegacySeedImportError("world.md seed digest mismatch")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LegacySeedImportError("world.md seed must be UTF-8") from exc
        return data

    def build_bundle(self, project_id: str) -> LegacySeedBundle:
        project_id = _project_id(project_id)
        world_bytes = self.read_world_bytes()
        seed_digest = "sha256:" + _digest(world_bytes)
        manifest = _canonical_json(
            {
                "manifest_schema_version": 1,
                "project_id": project_id,
                "seed": {
                    "kind": "LEGACY_WORLD_MD",
                    "world_sha256": seed_digest,
                },
            }
        )
        try:
            bundle = CanonicalBundle(1, manifest, world_bytes)
        except CanonicalBundleError as exc:
            raise LegacySeedImportError("deterministic CanonicalBundle is invalid") from exc
        if bundle.world_hash != seed_digest:
            raise LegacySeedImportError("bundle world identity does not match seed")
        return LegacySeedBundle(seed_digest=seed_digest, bundle=bundle)

    def import_bundle(self, project_id: str) -> LegacySeedBundle:
        """Compatibility spelling for the explicit seed-to-bundle operation."""
        return self.build_bundle(project_id)

    def import_seed(self, project_id: str) -> LegacySeedBundle:
        return self.build_bundle(project_id)
