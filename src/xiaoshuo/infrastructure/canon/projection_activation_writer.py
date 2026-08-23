"""C4b-only writer for the first immutable projection activation."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from xiaoshuo.domain.creation import ArtifactRef

from .canonical_bundle import CanonicalBundle
from .c4b_bootstrap_lock import C4bBootstrapLock, BootstrapLockError


class ProjectionActivationWriterError(RuntimeError):
    """The initial projection write is unsafe or cannot be verified."""


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
_POINTER_FIELDS = frozenset(
    {
        "pointer_schema_version",
        "project_id",
        "bundle_schema_version",
        "version_id",
        "bundle_ref_artifact_id",
        "bundle_content_hash",
        "manifest_hash",
        "world_hash",
    }
)
_MARKER_FIELDS = frozenset(
    {
        "marker_schema_version",
        "project_id",
        "pointer_content_hash",
        "pointer_schema_version",
        "bundle_schema_version",
        "version_id",
        "bundle_ref_artifact_id",
        "bundle_content_hash",
        "manifest_hash",
        "world_hash",
    }
)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _hash(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _safe_text(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value in {".", ".."}
        or "\x00" in value
        or Path(value).name != value
        or any(char in '<>:/\\"|?*' for char in value)
        or value.endswith((" ", "."))
    ):
        raise ProjectionActivationWriterError(f"invalid {field}")
    return value


@dataclass(frozen=True, slots=True)
class C4bProjectionIdentity:
    project_id: str
    version_id: str
    bundle_ref: ArtifactRef
    manifest_hash: str
    world_hash: str

    @property
    def bundle_schema_version(self) -> int:
        return self.bundle_ref.schema_version

    @property
    def bundle_content_hash(self) -> str:
        return self.bundle_ref.content_hash

    @property
    def bundle_ref_artifact_id(self) -> str:
        return self.bundle_ref.artifact_id

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


class ProjectionActivationWriter:
    """Write only a new, previously unactivated projection under C4b lock."""

    def __init__(self, root: Path | str, lock: C4bBootstrapLock) -> None:
        self.root = Path(root).resolve()
        self.lock = lock
        if self.root != lock.projection_root:
            raise ProjectionActivationWriterError("writer root does not match bootstrap lock")

    def _require_lock(self) -> None:
        if not self.lock.held:
            raise ProjectionActivationWriterError("C4b bootstrap lock is required")

    def _require_initial_state(self) -> None:
        if self.root.exists():
            if not self.root.is_dir() or self.root.is_symlink():
                raise ProjectionActivationWriterError("projection root is unsafe")
            if any(self.root.iterdir()):
                raise ProjectionActivationWriterError("projection root is not empty")
        elif not self.root.parent.is_dir():
            raise ProjectionActivationWriterError("projection root parent is missing")

    @staticmethod
    def _validate_identity(bundle: CanonicalBundle, identity: C4bProjectionIdentity) -> None:
        if identity.bundle_schema_version != bundle.schema_version:
            raise ProjectionActivationWriterError("bundle schema identity mismatch")
        if identity.bundle_content_hash != bundle.content_hash():
            raise ProjectionActivationWriterError("bundle content identity mismatch")
        if identity.manifest_hash != bundle.manifest_hash or identity.world_hash != bundle.world_hash:
            raise ProjectionActivationWriterError("bundle component identity mismatch")
        for field, value in (
            ("project_id", identity.project_id),
            ("version_id", identity.version_id),
            ("bundle_ref_artifact_id", identity.bundle_ref_artifact_id),
        ):
            _safe_text(value, field)
        if identity.bundle_schema_version != 1:
            raise ProjectionActivationWriterError("unsupported bundle schema version")

    @staticmethod
    def identity_fields(identity: C4bProjectionIdentity) -> dict[str, object]:
        return identity.as_fields()

    @staticmethod
    def pointer_bytes(identity: C4bProjectionIdentity) -> bytes:
        fields = {
            "pointer_schema_version": 1,
            **identity.as_fields(),
        }
        return _canonical_bytes(fields)

    @staticmethod
    def marker_bytes(identity: C4bProjectionIdentity, pointer_bytes: bytes) -> bytes:
        fields = {
            "marker_schema_version": 1,
            "pointer_content_hash": _hash(pointer_bytes),
            "pointer_schema_version": 1,
            **identity.as_fields(),
        }
        return _canonical_bytes(fields)

    @staticmethod
    def _create_file(path: Path, data: bytes) -> None:
        if path.exists():
            raise ProjectionActivationWriterError(f"activation file already exists: {path.name}")
        temporary = path.parent / (f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            if temporary.read_bytes() != data:
                raise ProjectionActivationWriterError("activation file write verification failed")
            if path.exists():
                raise ProjectionActivationWriterError(f"activation file already exists: {path.name}")
            os.replace(temporary, path)
        except OSError as exc:
            raise ProjectionActivationWriterError("activation file write failed") from exc
        finally:
            if temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    pass

    def write_version(self, bundle: CanonicalBundle, identity: C4bProjectionIdentity) -> Path:
        self._require_lock()
        self._require_initial_state()
        self._validate_identity(bundle, identity)
        self.root.mkdir(parents=True, exist_ok=True)
        versions = self.root / "versions"
        version_dir = versions / identity.version_id
        try:
            versions.mkdir()
            version_dir.mkdir()
        except FileExistsError as exc:
            raise ProjectionActivationWriterError("projection version residue exists") from exc
        self._create_file(version_dir / "bundle.identity.json", _canonical_bytes(identity.as_fields()))
        self._create_file(version_dir / "manifest.json", bundle.manifest)
        self._create_file(version_dir / "world.md", bundle.world_md)
        return version_dir

    def write_pointer(self, identity: C4bProjectionIdentity) -> bytes:
        self._require_lock()
        pointer = self.root / "current.pointer"
        if not (self.root / "versions" / identity.version_id).is_dir():
            raise ProjectionActivationWriterError("version directory is missing")
        data = self.pointer_bytes(identity)
        self._create_file(pointer, data)
        if pointer.read_bytes() != data:
            raise ProjectionActivationWriterError("pointer readback failed")
        return data

    def write_pre_marker(self, bundle: CanonicalBundle, identity: C4bProjectionIdentity) -> bytes:
        """Write version and pointer, deliberately leaving marker absent."""
        self.write_version(bundle, identity)
        return self.write_pointer(identity)

    def write_marker(self, identity: C4bProjectionIdentity) -> bytes:
        self._require_lock()
        marker = self.root / "activation.marker"
        pointer = self.root / "current.pointer"
        if marker.exists():
            raise ProjectionActivationWriterError("activation marker already exists")
        try:
            pointer_bytes = pointer.read_bytes()
        except OSError as exc:
            raise ProjectionActivationWriterError("pointer is missing") from exc
        expected_pointer = self.pointer_bytes(identity)
        if pointer_bytes != expected_pointer:
            raise ProjectionActivationWriterError("pointer identity mismatch")
        data = self.marker_bytes(identity, pointer_bytes)
        self._create_file(marker, data)
        if marker.read_bytes() != data:
            raise ProjectionActivationWriterError("marker readback failed")
        return data

    def write(self, bundle: CanonicalBundle, identity: C4bProjectionIdentity) -> bytes:
        self.write_pre_marker(bundle, identity)
        return self.write_marker(identity)


C4bProjectionWriter = ProjectionActivationWriter
