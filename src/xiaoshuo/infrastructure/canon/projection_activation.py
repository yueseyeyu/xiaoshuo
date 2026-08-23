"""Read-only verification of the Canon activation marker and pointer.

This module intentionally has no writer.  C4-PRE can observe an already
activated projection, while C4b owns the first production activation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from xiaoshuo.domain.creation import ArtifactRef

from .canonical_bundle import CanonicalBundle
from xiaoshuo.infra.config_manager import get_config


class ProjectionActivationError(RuntimeError):
    """Activation state is missing, malformed, or internally inconsistent."""


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


def _production_root() -> Path:
    try:
        return Path(get_config()["canon_mvp"]["projection_dir"])
    except (KeyError, TypeError) as exc:
        raise ProjectionActivationError("canon_mvp.projection_dir is required") from exc


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) != 71 or not value.startswith("sha256:"):
        raise ProjectionActivationError(f"invalid {field}")
    if any(c not in "0123456789abcdef" for c in value[7:]):
        raise ProjectionActivationError(f"invalid {field}")
    return value


def _text(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value in {".", ".."}
        or "\x00" in value
        or any(char in '<>:"|?*' for char in value)
        or value.endswith((" ", "."))
        or Path(value).name != value
    ):
        raise ProjectionActivationError(f"invalid {field}")
    return value


@dataclass(frozen=True, slots=True)
class ActivationIdentity:
    project_id: str
    version_id: str
    bundle_schema_version: int
    bundle_ref_artifact_id: str
    bundle_content_hash: str
    manifest_hash: str
    world_hash: str

    @property
    def bundle_ref(self) -> ArtifactRef:
        return ArtifactRef(artifact_id=self.bundle_ref_artifact_id, schema_version=self.bundle_schema_version, content_hash=self.bundle_content_hash)

    @property
    def schema_version(self) -> int:
        """Application-port compatible name for the bundle schema version."""
        return self.bundle_schema_version


ArtifactRefResolver = Callable[[str], ArtifactRef | None]


class ProjectionActivationReader:
    """Verify an existing activation without creating or replacing files."""

    def __init__(
        self,
        root: Path | str | None = None,
        *,
        artifact_ref_resolver: ArtifactRefResolver | None = None,
    ) -> None:
        self.root = Path(root) if root is not None else _production_root()
        if self.root.resolve() != _production_root().resolve():
            raise ProjectionActivationError("unapproved projection root")
        if artifact_ref_resolver is None:
            raise ProjectionActivationError("ArtifactRef registry verifier is required")
        self._artifact_ref_resolver = artifact_ref_resolver

    def read_for_project(self, project_id: str) -> ActivationIdentity:
        if not isinstance(project_id, str) or not project_id.strip():
            raise ProjectionActivationError("project_id is required")
        marker_path = self.root / "activation.marker"
        pointer_path = self.root / "current.pointer"
        if not self.root.is_dir() or not marker_path.is_file() or not pointer_path.is_file():
            raise ProjectionActivationError("projection activation is missing")
        pointer_bytes = self._read_canonical(pointer_path, _POINTER_FIELDS, "pointer")
        marker = self._read_canonical(marker_path, _MARKER_FIELDS, "marker")
        pointer = pointer_bytes[0]
        if marker["pointer_content_hash"] != "sha256:" + _sha256(pointer_bytes[1]):
            raise ProjectionActivationError("activation marker does not bind pointer")
        self._validate_versions(pointer, marker)
        if pointer["project_id"] != project_id or marker["project_id"] != project_id:
            raise ProjectionActivationError("activation project binding mismatch")
        identity = self._identity(pointer)
        version_dir = self.root / "versions" / identity.version_id
        if not version_dir.is_dir():
            raise ProjectionActivationError("activation version directory is missing")
        versions_root = self.root / "versions"
        try:
            resolved_version = version_dir.resolve()
            resolved_versions_root = versions_root.resolve()
            resolved_version.relative_to(resolved_versions_root)
        except (OSError, ValueError) as exc:
            raise ProjectionActivationError("activation version directory escapes versions root") from exc
        if version_dir.is_symlink():
            raise ProjectionActivationError("activation version directory must not be a symlink")
        identity_path = version_dir / "bundle.identity.json"
        version_identity = self._read_canonical(identity_path, _IDENTITY_FIELDS, "bundle identity")
        if any(version_identity[k] != pointer[k] for k in _IDENTITY_FIELDS):
            raise ProjectionActivationError("version directory identity mismatch")
        try:
            manifest = (version_dir / "manifest.json").read_bytes()
            world = (version_dir / "world.md").read_bytes()
            bundle = CanonicalBundle(1, manifest, world)
        except (OSError, RuntimeError) as exc:
            raise ProjectionActivationError("version directory bundle is invalid") from exc
        if (
            bundle.content_hash() != identity.bundle_content_hash
            or bundle.manifest_hash != identity.manifest_hash
            or bundle.world_hash != identity.world_hash
        ):
            raise ProjectionActivationError("complete bundle identity mismatch")
        if self._artifact_ref_resolver is not None:
            try:
                ref = self._artifact_ref_resolver(identity.bundle_ref_artifact_id)
            except Exception as exc:
                raise ProjectionActivationError("ArtifactRef registry identity mismatch") from exc
            if (
                ref is None
                or ref.artifact_id != identity.bundle_ref_artifact_id
                or ref.schema_version != identity.bundle_schema_version
                or ref.content_hash != identity.bundle_content_hash
            ):
                raise ProjectionActivationError("ArtifactRef registry identity mismatch")
        return identity

    @staticmethod
    def _read_canonical(path: Path, fields: frozenset[str], label: str) -> tuple[dict[str, object], bytes] | dict[str, object]:
        try:
            data = path.read_bytes()
            value = json.loads(data.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProjectionActivationError(f"{label} is invalid") from exc
        if not isinstance(value, dict) or set(value) != fields or _canonical_bytes(value) != data:
            raise ProjectionActivationError(f"{label} is not canonical")
        for key, item in value.items():
            if key.endswith("hash") or key == "pointer_content_hash":
                _hash(item, key)
            elif key.endswith("_version"):
                if type(item) is not int or item != 1:
                    raise ProjectionActivationError(f"invalid {key}")
            elif key not in {"bundle_ref_artifact_id", "project_id", "version_id"}:
                raise ProjectionActivationError(f"invalid {key}")
        for key in ("project_id", "version_id", "bundle_ref_artifact_id"):
            _text(value[key], key)
        return (value, data) if label == "pointer" else value

    @staticmethod
    def _validate_versions(pointer: dict[str, object], marker: dict[str, object]) -> None:
        for key in _POINTER_FIELDS:
            marker_key = key if key != "project_id" else "project_id"
            if marker.get(marker_key) != pointer.get(key):
                raise ProjectionActivationError("marker/pointer identity mismatch")

    @staticmethod
    def _identity(pointer: dict[str, object]) -> ActivationIdentity:
        return ActivationIdentity(
            project_id=pointer["project_id"],
            version_id=pointer["version_id"],
            bundle_schema_version=pointer["bundle_schema_version"],
            bundle_ref_artifact_id=pointer["bundle_ref_artifact_id"],
            bundle_content_hash=pointer["bundle_content_hash"],
            manifest_hash=pointer["manifest_hash"],
            world_hash=pointer["world_hash"],
        )


# Explicit alias for composition code and tests; no writer is exposed.
ProjectionActivationReaderPort = ProjectionActivationReader
