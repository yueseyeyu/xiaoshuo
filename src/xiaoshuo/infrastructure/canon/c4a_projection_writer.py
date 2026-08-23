"""Durable writer for a C4a follow-on Canon projection switch."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from xiaoshuo.domain.creation import ArtifactRef

from .canonical_bundle import CanonicalBundle
from .c4a_projection_commit_lock import C4aProjectionCommitLock


class C4aProjectionWriterError(RuntimeError):
    """A C4a version/pointer/marker write was not fully verified."""


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


@dataclass(frozen=True, slots=True)
class C4aProjectionIdentity:
    project_id: str
    version_id: str
    bundle_ref: ArtifactRef
    manifest_hash: str
    world_hash: str

    @property
    def bundle_schema_version(self) -> int:
        return self.bundle_ref.schema_version

    @property
    def bundle_ref_artifact_id(self) -> str:
        return self.bundle_ref.artifact_id

    @property
    def bundle_content_hash(self) -> str:
        return self.bundle_ref.content_hash

    def as_fields(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "version_id": self.version_id,
            "bundle_schema_version": self.bundle_schema_version,
            "bundle_ref_artifact_id": self.bundle_ref_artifact_id,
            "bundle_content_hash": self.bundle_content_hash,
            "manifest_hash": self.manifest_hash,
            "world_hash": self.world_hash,
        }


_IDENTITY_FIELDS = frozenset(
    {
        "project_id",
        "version_id",
        "bundle_schema_version",
        "bundle_ref_artifact_id",
        "bundle_content_hash",
        "manifest_hash",
        "world_hash",
    }
)


class C4aProjectionWriter:
    """Write only a new immutable version and the two switch files."""

    def __init__(self, root: Path | str, lock: C4aProjectionCommitLock) -> None:
        self.root = Path(root).resolve()
        self.lock = lock
        if self.root != lock.projection_root:
            raise C4aProjectionWriterError("writer root does not match C4a lock")

    def _require_lock(self) -> None:
        if not self.lock.held:
            raise C4aProjectionWriterError("C4a projection lock is required")

    @staticmethod
    def _safe_text(value: object, field: str) -> None:
        if (
            not isinstance(value, str)
            or not value.strip()
            or value in {".", ".."}
            or "\x00" in value
            or Path(value).name != value
            or any(char in '<>:/\\"|?*' for char in value)
            or value.endswith((" ", "."))
        ):
            raise C4aProjectionWriterError(f"invalid {field}")

    @classmethod
    def _validate_identity(cls, bundle: CanonicalBundle, identity: C4aProjectionIdentity) -> None:
        cls._safe_text(identity.project_id, "project_id")
        cls._safe_text(identity.version_id, "version_id")
        cls._safe_text(identity.bundle_ref_artifact_id, "bundle_ref_artifact_id")
        if identity.bundle_schema_version != bundle.schema_version:
            raise C4aProjectionWriterError("bundle schema identity mismatch")
        if identity.bundle_content_hash != bundle.content_hash():
            raise C4aProjectionWriterError("bundle content identity mismatch")
        if identity.manifest_hash != bundle.manifest_hash or identity.world_hash != bundle.world_hash:
            raise C4aProjectionWriterError("bundle component identity mismatch")

    @staticmethod
    def identity_bytes(identity: C4aProjectionIdentity) -> bytes:
        return _canonical(identity.as_fields())

    @staticmethod
    def pointer_bytes(identity: C4aProjectionIdentity) -> bytes:
        return _canonical({"pointer_schema_version": 1, **identity.as_fields()})

    @staticmethod
    def marker_bytes(identity: C4aProjectionIdentity, pointer_bytes: bytes) -> bytes:
        return _canonical(
            {
                "marker_schema_version": 1,
                "pointer_content_hash": _digest(pointer_bytes),
                "pointer_schema_version": 1,
                **identity.as_fields(),
            }
        )

    @staticmethod
    def _write_temp_and_replace(path: Path, data: bytes) -> None:
        temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
        try:
            with temporary.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            if temporary.read_bytes() != data:
                raise C4aProjectionWriterError("temporary file readback failed")
            os.replace(temporary, path)
            if path.read_bytes() != data:
                raise C4aProjectionWriterError("atomic replacement readback failed")
        except C4aProjectionWriterError:
            raise
        except OSError as exc:
            raise C4aProjectionWriterError("durable projection file write failed") from exc
        finally:
            if temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    pass

    def write_version(self, bundle: CanonicalBundle, identity: C4aProjectionIdentity) -> Path:
        self._require_lock()
        self._validate_identity(bundle, identity)
        if not self.root.is_dir() or self.root.is_symlink():
            raise C4aProjectionWriterError("C4a projection root is not an existing directory")
        versions = self.root / "versions"
        if not versions.is_dir() or versions.is_symlink():
            raise C4aProjectionWriterError("C4a version root is unsafe")
        version_dir = versions / identity.version_id
        if version_dir.exists():
            raise C4aProjectionWriterError("C4a version is immutable and already exists")
        try:
            version_dir.mkdir()
            self._write_temp_and_replace(version_dir / "bundle.identity.json", self.identity_bytes(identity))
            self._write_temp_and_replace(version_dir / "manifest.json", bundle.manifest)
            self._write_temp_and_replace(version_dir / "world.md", bundle.world_md)
        except OSError as exc:
            raise C4aProjectionWriterError("C4a version directory cannot be created") from exc
        return version_dir

    def write_pointer(self, identity: C4aProjectionIdentity) -> bytes:
        self._require_lock()
        if not (self.root / "versions" / identity.version_id).is_dir():
            raise C4aProjectionWriterError("C4a version directory is missing")
        data = self.pointer_bytes(identity)
        self._write_temp_and_replace(self.root / "current.pointer", data)
        return data

    def write_marker(self, identity: C4aProjectionIdentity) -> bytes:
        self._require_lock()
        pointer_path = self.root / "current.pointer"
        try:
            pointer = pointer_path.read_bytes()
        except OSError as exc:
            raise C4aProjectionWriterError("C4a pointer is missing") from exc
        expected = self.pointer_bytes(identity)
        if pointer != expected:
            raise C4aProjectionWriterError("C4a pointer identity mismatch")
        data = self.marker_bytes(identity, pointer)
        self._write_temp_and_replace(self.root / "activation.marker", data)
        return data

