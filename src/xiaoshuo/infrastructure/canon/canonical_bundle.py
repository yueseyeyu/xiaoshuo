"""Stable v1 Canon bundle: canonical manifest and authoritative world source."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


class CanonicalBundleError(RuntimeError):
    """A bundle violates the stable, authoritative-only C2 contract."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_manifest(manifest: bytes) -> bytes:
    try:
        value = json.loads(manifest.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CanonicalBundleError("manifest must be canonical UTF-8 JSON") from exc
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if canonical != manifest:
        raise CanonicalBundleError("manifest is not canonical JSON")
    return canonical


_SERIALIZED_FIELDS = frozenset(
    {
        "manifest",
        "manifest_sha256",
        "schema_version",
        "world_md",
        "world_md_sha256",
    }
)


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True)
class CanonicalBundle:
    schema_version: int
    manifest: bytes
    world_md: bytes

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not self.manifest or not self.world_md:
            raise CanonicalBundleError("v1 bundle requires a manifest and world.md")
        _canonical_manifest(self.manifest)
        try:
            self.world_md.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CanonicalBundleError("world.md must be UTF-8") from exc

    @property
    def manifest_hash(self) -> str:
        return "sha256:" + _sha256(self.manifest)

    @property
    def world_hash(self) -> str:
        return "sha256:" + _sha256(self.world_md)

    def to_bytes(self) -> bytes:
        payload = {
            "manifest": self.manifest.decode("utf-8"),
            "manifest_sha256": _sha256(self.manifest),
            "schema_version": self.schema_version,
            "world_md": self.world_md.decode("utf-8"),
            "world_md_sha256": _sha256(self.world_md),
        }
        return _canonical_json_bytes(payload)

    @classmethod
    def from_bytes(cls, data: bytes) -> "CanonicalBundle":
        """Rebuild a v1 bundle only from its canonical serialized form."""
        if not isinstance(data, bytes):
            raise CanonicalBundleError("bundle must be bytes")
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CanonicalBundleError("bundle must be canonical UTF-8 JSON") from exc
        if not isinstance(payload, dict) or set(payload) != _SERIALIZED_FIELDS:
            raise CanonicalBundleError("bundle fields are invalid")
        if _canonical_json_bytes(payload) != data:
            raise CanonicalBundleError("bundle outer JSON is not canonical")

        schema_version = payload["schema_version"]
        manifest = payload["manifest"]
        manifest_hash = payload["manifest_sha256"]
        world_md = payload["world_md"]
        world_hash = payload["world_md_sha256"]
        if type(schema_version) is not int or schema_version != 1:
            raise CanonicalBundleError("unsupported bundle schema version")
        if not all(isinstance(value, str) for value in (manifest, manifest_hash, world_md, world_hash)):
            raise CanonicalBundleError("bundle field types are invalid")

        manifest_bytes = manifest.encode("utf-8")
        world_bytes = world_md.encode("utf-8")
        if manifest_hash != _sha256(manifest_bytes) or world_hash != _sha256(world_bytes):
            raise CanonicalBundleError("bundle embedded hash mismatch")
        return cls(schema_version, manifest_bytes, world_bytes)

    def content_hash(self) -> str:
        return "sha256:" + _sha256(self.to_bytes())
