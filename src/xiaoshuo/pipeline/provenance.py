"""P0 provenance contracts and fail-closed pipeline boundaries.

This module deliberately has no project discovery, configuration discovery,
legacy imports, subprocess calls, or filesystem writes at import time.  A
governed owner must inject an immutable registry snapshot and an explicit D
drive stage-root alias before any execution context can be created.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import stat
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterator, Mapping, Sequence


RUN_ID_PATTERN = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9]{3}$")
HEX64_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
ALIAS_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

UNKNOWN_PROJECT = "UNKNOWN_PROJECT"
UNKNOWN_PROFILE = "UNKNOWN_PROFILE"
MISSING_PROJECT_CONTEXT = "MISSING_PROJECT_CONTEXT"
REGISTRY_SOURCE_MISMATCH = "REGISTRY_SOURCE_MISMATCH"
REGISTRY_SNAPSHOT_MISMATCH = "REGISTRY_SNAPSHOT_MISMATCH"
PROFILE_MISMATCH = "PROFILE_MISMATCH"
NAMESPACE_DIGEST_MISMATCH = "NAMESPACE_DIGEST_MISMATCH"
OLD_NAMESPACE_ARTIFACT = "OLD_NAMESPACE_ARTIFACT"
UNKNOWN_STAGE_ALIAS = "UNKNOWN_STAGE_ALIAS"
INVALID_RUN_ID = "INVALID_RUN_ID"
PATH_ESCAPE = "PATH_ESCAPE"
REPARSE_OR_JUNCTION = "REPARSE_OR_JUNCTION"
LEGACY_CAPABILITY_DENIED = "LEGACY_CAPABILITY_DENIED"
UNKNOWN_DYNAMIC_IMPORT = "UNKNOWN_DYNAMIC_IMPORT"
UNRESOLVED_TRANSITIVE_DEPENDENCY = "UNRESOLVED_TRANSITIVE_DEPENDENCY"
IMPORT_SIDE_EFFECT_UNCERTAIN = "IMPORT_SIDE_EFFECT_UNCERTAIN"
UNMIGRATED_WRITER = "UNMIGRATED_WRITER"
SELF_REFERENTIAL_HASH_PREIMAGE = "SELF_REFERENTIAL_HASH_PREIMAGE"
BATCH_ENVELOPE_BINDING_MISMATCH = "BATCH_ENVELOPE_BINDING_MISMATCH"
EXECUTION_BATCH_ID_MISMATCH = "EXECUTION_BATCH_ID_MISMATCH"
BATCH_NAMESPACE_MISMATCH = "BATCH_NAMESPACE_MISMATCH"
BATCH_STAGE_ALIAS_MISMATCH = "BATCH_STAGE_ALIAS_MISMATCH"
BATCH_ROOT_ALIAS_MISMATCH = "BATCH_ROOT_ALIAS_MISMATCH"
BATCH_RUN_ID_MISMATCH = "BATCH_RUN_ID_MISMATCH"
BATCH_PRODUCER_VERSION_MISMATCH = "BATCH_PRODUCER_VERSION_MISMATCH"
BATCH_FAILURE_CHAIN_MISMATCH = "BATCH_FAILURE_CHAIN_MISMATCH"
BATCH_DIGEST_MISMATCH = "BATCH_DIGEST_MISMATCH"
PARENT_MISSING = "PARENT_MISSING"
PARENT_MISMATCH = "PARENT_MISMATCH"
PARENT_STORE_MISMATCH = "PARENT_STORE_MISMATCH"
HASH_MISMATCH = "HASH_MISMATCH"
REPLAY_CONFLICT = "REPLAY_CONFLICT"
WRITE_BOUNDARY_UNCERTAIN = "WRITE_BOUNDARY_UNCERTAIN"
ENTRY_PROVENANCE_MISSING = "ENTRY_PROVENANCE_MISSING"
ENTRY_PROVENANCE_UNRESOLVED = "ENTRY_PROVENANCE_UNRESOLVED"
ENTRY_PROVENANCE_HASH_MISMATCH = "ENTRY_PROVENANCE_HASH_MISMATCH"
ARTIFACT_NOT_VERIFIED = "ARTIFACT_NOT_VERIFIED"
BOM_FORBIDDEN = "BOM_FORBIDDEN"
PREREQUISITE_VALIDATION_FAILED = "PREREQUISITE_VALIDATION_FAILED"
INPUT_VALIDATION_FAILED = "INPUT_VALIDATION_FAILED"
OUTPUT_VALIDATION_FAILED = "OUTPUT_VALIDATION_FAILED"
CHECKPOINT_CAPABILITY_UNAVAILABLE = "CHECKPOINT_CAPABILITY_UNAVAILABLE"

PROFILE_DEFINITION_FIELDS = (
    "profile_schema_version",
    "profile_id",
    "profile_version",
    "genre_identity",
    "profile_parameters",
    "profile_policy",
)
NAMESPACE_FIELDS = (
    "namespace_schema_version",
    "project_id",
    "profile_id",
    "profile_version",
    "profile_definition_hash",
    "project_revision",
)
PROJECT_ENTRY_FIELDS = (
    "project_entry_schema_version",
    "project_id",
    "project_revision",
    "profile_id",
    "profile_version",
    "profile_definition_hash",
    "genre_identity",
    "entry_status",
    "entry_provenance_ref",
    "entry_provenance_hash",
)
REGISTRY_SNAPSHOT_FIELDS = (
    "registry_schema_version",
    "registry_id",
    "owner_id",
    "authoritative_source_ref",
    "snapshot_id",
    "read_only",
    "project_entries",
)
EXECUTION_BATCH_PREIMAGE_FIELDS = (
    "batch_schema_version",
    "batch_id",
    "attempt_id",
    "namespace_digest",
    "stage_alias",
    "root_alias",
    "run_id",
    "producer_version",
    "started_at_utc",
    "finished_at_utc",
    "config_hash",
    "failure_chain",
)
EVIDENCE_ENVELOPE_PREIMAGE_FIELDS = (
    "envelope_schema_version",
    "execution_batch_id",
    "namespace_digest",
    "stage_alias",
    "root_alias",
    "run_id",
    "producer_version",
    "failure_chain",
    "batch_digest",
    "input_artifact_refs",
    "output_artifact_refs",
    "source_refs",
    "parent_refs",
    "artifact_lengths",
    "artifact_sha256",
    "canonical_flags",
    "tool_boundary",
)
ARTIFACT_INTEGRITY_FIELDS = (
    "project_id",
    "profile_id",
    "profile_version",
    "profile_definition_hash",
    "project_revision",
    "namespace_digest",
    "root_alias",
    "relative_path",
    "source_ref",
    "producer_version",
    "batch_id",
    "parent_refs",
    "length",
    "sha256",
)
PARENT_RECORD_FIELDS = (
    "parent_ref",
    "project_id",
    "profile_id",
    "profile_version",
    "profile_definition_hash",
    "project_revision",
    "namespace_digest",
    "root_alias",
    "source_ref",
    "producer_version",
    "batch_id",
    "content_length",
    "content_sha256",
)
PARENT_STORE_FIELDS = (
    "owner_id",
    "authoritative_source_ref",
    "parent_records",
)


class ProvenanceError(ValueError):
    """Stable, machine-readable fail-closed error."""

    def __init__(self, code: str, message: str | None = None, **details: Any):
        self.code = code
        self.details = details
        super().__init__(message or code)


def _normalise(value: Any, depth: int = 0) -> Any:
    """Validate and normalise values without changing top-level field order."""
    if isinstance(value, Path):
        raise ProvenanceError(PATH_ESCAPE, "Path objects are not canonical preimage values")
    if isinstance(value, str):
        if "\x00" in value:
            raise ProvenanceError("INVALID_CANONICAL_VALUE", "NUL is not allowed")
        return value
    if isinstance(value, bool) or value is None or isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ProvenanceError("INVALID_CANONICAL_VALUE", "NaN and Infinity are not allowed")
        return value
    if isinstance(value, Mapping):
        items = value.items() if depth == 0 else sorted(value.items(), key=lambda item: item[0])
        result: dict[str, Any] = {}
        for key, item in items:
            if not isinstance(key, str):
                raise ProvenanceError("INVALID_CANONICAL_VALUE", "mapping keys must be strings")
            result[key] = _normalise(item, depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_normalise(item, depth + 1) for item in value]
    raise ProvenanceError("INVALID_CANONICAL_VALUE", f"unsupported value: {type(value)!r}")


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    """Return canonical UTF-8 bytes with the declared object order preserved."""
    try:
        payload = json.dumps(
            _normalise(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=False,
            separators=(",", ":"),
        )
    except UnicodeEncodeError as exc:
        raise ProvenanceError("INVALID_UTF8", str(exc)) from exc
    return payload.encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_sha256(value: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def _copy_json(value: Any) -> Any:
    return copy.deepcopy(value)


def _check_hash(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not HEX64_PATTERN.fullmatch(value):
        raise ProvenanceError("INVALID_HASH", f"{field_name} must be a SHA-256 hex digest")


def _check_nonempty(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ProvenanceError("INVALID_IDENTITY", f"{field_name} must be a non-empty string")


@dataclass(frozen=True)
class ProfileDefinitionV1:
    profile_schema_version: str
    profile_id: str
    profile_version: str
    genre_identity: str
    profile_parameters: Mapping[str, Any]
    profile_policy: Mapping[str, Any]

    def __post_init__(self) -> None:
        for name, value in (
            ("profile_schema_version", self.profile_schema_version),
            ("profile_id", self.profile_id),
            ("profile_version", self.profile_version),
            ("genre_identity", self.genre_identity),
        ):
            _check_nonempty(value, name)

    def to_preimage(self) -> dict[str, Any]:
        return {
            "profile_schema_version": self.profile_schema_version,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "genre_identity": self.genre_identity,
            "profile_parameters": _copy_json(dict(self.profile_parameters)),
            "profile_policy": _copy_json(dict(self.profile_policy)),
        }

    @property
    def definition_hash(self) -> str:
        return canonical_sha256(self.to_preimage())


@dataclass(frozen=True)
class ProjectIdentity:
    project_id: str

    def __post_init__(self) -> None:
        _check_nonempty(self.project_id, "project_id")


@dataclass(frozen=True)
class ProfileIdentity:
    profile_id: str
    profile_version: str
    profile_definition_hash: str

    def __post_init__(self) -> None:
        _check_nonempty(self.profile_id, "profile_id")
        _check_nonempty(self.profile_version, "profile_version")
        _check_hash(self.profile_definition_hash, "profile_definition_hash")

    @classmethod
    def from_definition(cls, definition: ProfileDefinitionV1) -> "ProfileIdentity":
        return cls(definition.profile_id, definition.profile_version, definition.definition_hash)


@dataclass(frozen=True)
class NamespaceIdentity:
    namespace_schema_version: str
    project_id: str
    profile_id: str
    profile_version: str
    profile_definition_hash: str
    project_revision: str
    namespace_digest: str

    def __post_init__(self) -> None:
        for name, value in (
            ("namespace_schema_version", self.namespace_schema_version),
            ("project_id", self.project_id),
            ("profile_id", self.profile_id),
            ("profile_version", self.profile_version),
            ("project_revision", self.project_revision),
        ):
            _check_nonempty(value, name)
        _check_hash(self.profile_definition_hash, "profile_definition_hash")
        _check_hash(self.namespace_digest, "namespace_digest")

    def to_preimage(self) -> dict[str, Any]:
        return {
            "namespace_schema_version": self.namespace_schema_version,
            "project_id": self.project_id,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "profile_definition_hash": self.profile_definition_hash,
            "project_revision": self.project_revision,
        }


def make_namespace(
    project: ProjectIdentity,
    profile: ProfileIdentity,
    project_revision: str,
    namespace_schema_version: str = "namespace-v1",
) -> NamespaceIdentity:
    preimage = {
        "namespace_schema_version": namespace_schema_version,
        "project_id": project.project_id,
        "profile_id": profile.profile_id,
        "profile_version": profile.profile_version,
        "profile_definition_hash": profile.profile_definition_hash,
        "project_revision": project_revision,
    }
    return NamespaceIdentity(
        **preimage,
        namespace_digest=canonical_sha256(preimage),
    )


ProjectNamespaceV1 = NamespaceIdentity


@dataclass(frozen=True)
class ProjectEntryV1:
    project_entry_schema_version: str
    project_id: str
    project_revision: str
    profile_id: str
    profile_version: str
    profile_definition_hash: str
    genre_identity: str
    entry_status: str
    entry_provenance_ref: str
    entry_provenance_hash: str

    def __post_init__(self) -> None:
        for name, value in (
            ("project_entry_schema_version", self.project_entry_schema_version),
            ("project_id", self.project_id),
            ("project_revision", self.project_revision),
            ("profile_id", self.profile_id),
            ("profile_version", self.profile_version),
            ("genre_identity", self.genre_identity),
            ("entry_status", self.entry_status),
            ("entry_provenance_ref", self.entry_provenance_ref),
        ):
            _check_nonempty(value, name)
        _check_hash(self.profile_definition_hash, "profile_definition_hash")
        _check_hash(self.entry_provenance_hash, "entry_provenance_hash")

    def to_preimage(self) -> dict[str, Any]:
        return {
            "project_entry_schema_version": self.project_entry_schema_version,
            "project_id": self.project_id,
            "project_revision": self.project_revision,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "profile_definition_hash": self.profile_definition_hash,
            "genre_identity": self.genre_identity,
            "entry_status": self.entry_status,
            "entry_provenance_ref": self.entry_provenance_ref,
            "entry_provenance_hash": self.entry_provenance_hash,
        }

    def verify_provenance(self, provenance_bytes: bytes) -> bool:
        if not isinstance(provenance_bytes, bytes):
            raise ProvenanceError(
                ENTRY_PROVENANCE_UNRESOLVED,
                "entry provenance bytes are not resolvable bytes",
                entry_provenance_ref=self.entry_provenance_ref,
            )
        actual = sha256_bytes(provenance_bytes)
        if actual != self.entry_provenance_hash:
            raise ProvenanceError(
                HASH_MISMATCH,
                "entry provenance hash mismatch",
                entry_provenance_ref=self.entry_provenance_ref,
            )
        return True


@dataclass(frozen=True)
class ProjectRegistryOwner:
    owner_id: str
    authoritative_source_ref: str

    def __post_init__(self) -> None:
        _check_nonempty(self.owner_id, "owner_id")
        _check_nonempty(self.authoritative_source_ref, "authoritative_source_ref")
        if ":\\" in self.authoritative_source_ref or "/" in self.authoritative_source_ref:
            raise ProvenanceError(REGISTRY_SOURCE_MISMATCH, "source reference must be opaque")


@dataclass(frozen=True)
class ProjectRegistryV1:
    registry_schema_version: str
    registry_id: str
    owner_id: str
    authoritative_source_ref: str
    snapshot_id: str
    read_only: bool
    project_entries: tuple[ProjectEntryV1, ...]
    registry_snapshot_hash: str
    owner_provenance_bytes: Mapping[str, bytes] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        _check_nonempty(self.registry_schema_version, "registry_schema_version")
        _check_nonempty(self.registry_id, "registry_id")
        _check_nonempty(self.owner_id, "owner_id")
        _check_nonempty(self.authoritative_source_ref, "authoritative_source_ref")
        _check_nonempty(self.snapshot_id, "snapshot_id")
        if self.read_only is not True:
            raise ProvenanceError(REGISTRY_SNAPSHOT_MISMATCH, "registry snapshot must be read-only")
        object.__setattr__(self, "project_entries", tuple(self.project_entries))
        provenance_map: dict[str, bytes] = {}
        try:
            provenance_map = dict(self.owner_provenance_bytes)
        except (TypeError, ValueError) as exc:
            raise ProvenanceError(ENTRY_PROVENANCE_UNRESOLVED, "owner provenance map is not readable") from exc
        for entry in self.project_entries:
            if entry.entry_provenance_ref not in provenance_map:
                raise ProvenanceError(
                    ENTRY_PROVENANCE_MISSING,
                    "owner provenance bytes are missing",
                    entry_provenance_ref=entry.entry_provenance_ref,
                )
            provenance_bytes = provenance_map[entry.entry_provenance_ref]
            if not isinstance(provenance_bytes, bytes):
                raise ProvenanceError(
                    ENTRY_PROVENANCE_UNRESOLVED,
                    "owner provenance bytes are not bytes",
                    entry_provenance_ref=entry.entry_provenance_ref,
                )
            if sha256_bytes(provenance_bytes) != entry.entry_provenance_hash:
                raise ProvenanceError(
                    ENTRY_PROVENANCE_HASH_MISMATCH,
                    "owner provenance bytes do not match entry hash",
                    entry_provenance_ref=entry.entry_provenance_ref,
                )
        object.__setattr__(self, "owner_provenance_bytes", MappingProxyType(provenance_map))
        _check_hash(self.registry_snapshot_hash, "registry_snapshot_hash")
        if self.compute_snapshot_hash() != self.registry_snapshot_hash:
            raise ProvenanceError(REGISTRY_SNAPSHOT_MISMATCH, "registry snapshot hash mismatch")

    def to_preimage(self) -> dict[str, Any]:
        return {
            "registry_schema_version": self.registry_schema_version,
            "registry_id": self.registry_id,
            "owner_id": self.owner_id,
            "authoritative_source_ref": self.authoritative_source_ref,
            "snapshot_id": self.snapshot_id,
            "read_only": self.read_only,
            "project_entries": [entry.to_preimage() for entry in self.project_entries],
        }

    def compute_snapshot_hash(self) -> str:
        return canonical_sha256(self.to_preimage())

    def resolve_owner_provenance(self, entry_provenance_ref: str) -> bytes:
        """Resolve only the immutable owner-injected provenance snapshot."""
        try:
            return self.owner_provenance_bytes[entry_provenance_ref]
        except KeyError as exc:
            raise ProvenanceError(
                ENTRY_PROVENANCE_UNRESOLVED,
                "entry provenance reference is not in the owner snapshot",
                entry_provenance_ref=entry_provenance_ref,
            ) from exc

    def verify_authority(
        self,
        owner_id: str,
        authoritative_source_ref: str,
        registry_snapshot_hash: str,
    ) -> None:
        if self.owner_id != owner_id or self.authoritative_source_ref != authoritative_source_ref:
            raise ProvenanceError(REGISTRY_SOURCE_MISMATCH, "registry owner/source mismatch")
        if self.registry_snapshot_hash != registry_snapshot_hash:
            raise ProvenanceError(REGISTRY_SNAPSHOT_MISMATCH, "registry snapshot mismatch")

    def lookup(
        self,
        project_id: str,
        profile_id: str | None = None,
        profile_version: str | None = None,
    ) -> ProjectEntryV1:
        matches = [entry for entry in self.project_entries if entry.project_id == project_id]
        if not matches:
            raise ProvenanceError(UNKNOWN_PROJECT, "project is not registered", project_id=project_id)
        if profile_id is not None:
            matches = [entry for entry in matches if entry.profile_id == profile_id]
        if profile_version is not None:
            matches = [entry for entry in matches if entry.profile_version == profile_version]
        if not matches:
            raise ProvenanceError(UNKNOWN_PROFILE, "profile is not registered", project_id=project_id)
        entry = matches[0]
        if entry.entry_status.upper() not in {"ACTIVE", "ENABLED"}:
            raise ProvenanceError(UNKNOWN_PROJECT, "project entry is not available", project_id=project_id)
        return entry


def inject_project_registry(
    owner: ProjectRegistryOwner,
    entries: Sequence[ProjectEntryV1],
    *,
    registry_id: str,
    snapshot_id: str,
    owner_provenance_bytes: Mapping[str, bytes],
    registry_schema_version: str = "registry-v1",
) -> ProjectRegistryV1:
    entries = tuple(entries)
    provenance_map = dict(owner_provenance_bytes)
    for entry in entries:
        if entry.entry_provenance_ref not in provenance_map:
            raise ProvenanceError(
                ENTRY_PROVENANCE_MISSING,
                "owner provenance bytes are missing",
                entry_provenance_ref=entry.entry_provenance_ref,
            )
        provenance_bytes = provenance_map[entry.entry_provenance_ref]
        if not isinstance(provenance_bytes, bytes):
            raise ProvenanceError(
                ENTRY_PROVENANCE_UNRESOLVED,
                "owner provenance bytes are not resolvable bytes",
                entry_provenance_ref=entry.entry_provenance_ref,
            )
        if sha256_bytes(provenance_bytes) != entry.entry_provenance_hash:
            raise ProvenanceError(
                ENTRY_PROVENANCE_HASH_MISMATCH,
                "owner provenance bytes do not match entry hash",
                entry_provenance_ref=entry.entry_provenance_ref,
            )
    preimage = {
        "registry_schema_version": registry_schema_version,
        "registry_id": registry_id,
        "owner_id": owner.owner_id,
        "authoritative_source_ref": owner.authoritative_source_ref,
        "snapshot_id": snapshot_id,
        "read_only": True,
        "project_entries": [entry.to_preimage() for entry in entries],
    }
    return ProjectRegistryV1(
        registry_schema_version=registry_schema_version,
        registry_id=registry_id,
        owner_id=owner.owner_id,
        authoritative_source_ref=owner.authoritative_source_ref,
        snapshot_id=snapshot_id,
        read_only=True,
        project_entries=entries,
        registry_snapshot_hash=canonical_sha256(preimage),
        owner_provenance_bytes=provenance_map,
    )


@dataclass(frozen=True)
class ParentRecordV1:
    """An owner-injected immutable description of one admissible parent."""

    parent_ref: str
    project_id: str
    profile_id: str
    profile_version: str
    profile_definition_hash: str
    project_revision: str
    namespace_digest: str
    root_alias: str
    source_ref: str
    producer_version: str
    batch_id: str
    content_length: int
    content_sha256: str

    def __post_init__(self) -> None:
        for name, value in (
            ("parent_ref", self.parent_ref),
            ("project_id", self.project_id),
            ("profile_id", self.profile_id),
            ("profile_version", self.profile_version),
            ("project_revision", self.project_revision),
            ("root_alias", self.root_alias),
            ("source_ref", self.source_ref),
            ("producer_version", self.producer_version),
            ("batch_id", self.batch_id),
        ):
            _check_nonempty(value, name)
        _check_hash(self.profile_definition_hash, "profile_definition_hash")
        _check_hash(self.namespace_digest, "namespace_digest")
        _check_hash(self.content_sha256, "content_sha256")
        if not isinstance(self.content_length, int) or self.content_length < 0:
            raise ProvenanceError(PARENT_MISMATCH, "parent content length is invalid")

    def to_preimage(self) -> dict[str, Any]:
        return {
            "parent_ref": self.parent_ref,
            "project_id": self.project_id,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "profile_definition_hash": self.profile_definition_hash,
            "project_revision": self.project_revision,
            "namespace_digest": self.namespace_digest,
            "root_alias": self.root_alias,
            "source_ref": self.source_ref,
            "producer_version": self.producer_version,
            "batch_id": self.batch_id,
            "content_length": self.content_length,
            "content_sha256": self.content_sha256,
        }


@dataclass(frozen=True)
class ParentRefStoreV1:
    """The only parent resolver boundary; all records are injected by the owner."""

    owner_id: str
    authoritative_source_ref: str
    parent_records: Mapping[str, ParentRecordV1]

    def __post_init__(self) -> None:
        _check_nonempty(self.owner_id, "owner_id")
        _check_nonempty(self.authoritative_source_ref, "authoritative_source_ref")
        if ":\\" in self.authoritative_source_ref or "/" in self.authoritative_source_ref:
            raise ProvenanceError(PARENT_STORE_MISMATCH, "parent store source reference must be opaque")
        try:
            records = dict(self.parent_records)
        except (TypeError, ValueError) as exc:
            raise ProvenanceError(PARENT_MISSING, "parent store is not readable") from exc
        for key, record in records.items():
            if not isinstance(key, str) or not isinstance(record, ParentRecordV1):
                raise ProvenanceError(PARENT_MISSING, "parent store contains an invalid record")
            if key != record.parent_ref:
                raise ProvenanceError(PARENT_MISMATCH, "parent store key does not match parent reference")
        object.__setattr__(self, "parent_records", MappingProxyType(records))

    def to_preimage(self) -> dict[str, Any]:
        return {
            "owner_id": self.owner_id,
            "authoritative_source_ref": self.authoritative_source_ref,
            "parent_records": [
                self.parent_records[key].to_preimage()
                for key in sorted(self.parent_records)
            ],
        }

    @property
    def snapshot_hash(self) -> str:
        return canonical_sha256(self.to_preimage())

    def validate_for_context(self, context: "ExecutionContext") -> None:
        if (
            self.owner_id != context.registry.owner_id
            or self.authoritative_source_ref != context.registry.authoritative_source_ref
        ):
            raise ProvenanceError(PARENT_STORE_MISMATCH, "parent store owner/source is not registry-bound")

    def resolve(self, parent_ref: str) -> ParentRecordV1:
        try:
            return self.parent_records[parent_ref]
        except KeyError as exc:
            raise ProvenanceError(PARENT_MISSING, "parent reference is not in the owner store", parent_ref=parent_ref) from exc

    def validate_parent_refs(self, context: "ExecutionContext", parent_refs: Sequence[str]) -> None:
        self.validate_for_context(context)
        for parent_ref in parent_refs:
            record = self.resolve(parent_ref)
            expected = (
                (record.project_id, context.project_id, "project_id"),
                (record.profile_id, context.profile.profile_id, "profile_id"),
                (record.profile_version, context.profile.profile_version, "profile_version"),
                (record.profile_definition_hash, context.profile.profile_definition_hash, "profile_definition_hash"),
                (record.project_revision, context.namespace.project_revision, "project_revision"),
                (record.namespace_digest, context.namespace_digest, "namespace_digest"),
                (record.root_alias, context.root_alias, "root_alias"),
            )
            for actual, wanted, field_name in expected:
                if actual != wanted:
                    raise ProvenanceError(
                        PARENT_MISMATCH,
                        "parent record is not compatible with execution context",
                        parent_ref=parent_ref,
                        field=field_name,
                    )


D_TMP_ROOT = Path(r"D:\tmp\yeyu-ai-a3")
_ADMITTED_ROOTS: set[Path] = set()
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def _assert_no_reparse(path: Path) -> None:
    """Inspect existing path components without following reparse points."""
    candidate = Path(path)
    while True:
        try:
            is_link = candidate.is_symlink()
            exists = candidate.exists()
            attributes = getattr(candidate.lstat(), "st_file_attributes", 0) if exists or is_link else 0
        except OSError as exc:
            raise ProvenanceError(REPARSE_OR_JUNCTION, "cannot verify root path component") from exc
        if is_link or attributes & _REPARSE_POINT:
            raise ProvenanceError(REPARSE_OR_JUNCTION, "reparse point, junction, or symlink is denied")
        if candidate == D_TMP_ROOT or candidate.parent == candidate:
            break
        candidate = candidate.parent


def _validate_stage_root_base(root_base: Path) -> Path:
    base = Path(root_base)
    if base.drive.upper() != "D:":
        raise ProvenanceError(WRITE_BOUNDARY_UNCERTAIN, "stage root must be on D drive")
    if ".." in base.parts:
        raise ProvenanceError(PATH_ESCAPE, "stage root path escape is denied")
    _assert_no_reparse(base)
    try:
        resolved = base.resolve(strict=False)
        resolved.relative_to(D_TMP_ROOT.resolve(strict=False))
    except (OSError, ValueError) as exc:
        raise ProvenanceError(
            WRITE_BOUNDARY_UNCERTAIN,
            "stage root must be below D:\\tmp\\yeyu-ai-a3",
        ) from exc
    if any(part.lower() in {"code", "xiaoshuo", "project_root"} for part in resolved.parts):
        raise ProvenanceError(WRITE_BOUNDARY_UNCERTAIN, "workspace and project roots are not stage roots")
    return base


@dataclass(frozen=True)
class StageRootAlias:
    alias: str
    stage_alias: str
    owner_id: str
    root_base: Path

    def __post_init__(self) -> None:
        if not ALIAS_PATTERN.fullmatch(self.alias or ""):
            raise ProvenanceError(UNKNOWN_STAGE_ALIAS, "root alias is not an opaque approved alias")
        if not ALIAS_PATTERN.fullmatch(self.stage_alias or ""):
            raise ProvenanceError(UNKNOWN_STAGE_ALIAS, "stage alias is not approved")
        _check_nonempty(self.owner_id, "owner_id")
        object.__setattr__(self, "root_base", _validate_stage_root_base(Path(self.root_base)))


@dataclass(frozen=True)
class ExecutionContext:
    registry: ProjectRegistryV1
    project: ProjectIdentity
    profile: ProfileIdentity
    namespace: NamespaceIdentity
    genre_identity: str
    stage_alias: str
    root_alias: str
    run_id: str
    producer_version: str
    root_spec: StageRootAlias
    parent_store: ParentRefStoreV1

    def __post_init__(self) -> None:
        if not isinstance(self.registry, ProjectRegistryV1):
            raise ProvenanceError(MISSING_PROJECT_CONTEXT, "context registry is not an admitted snapshot")
        if not isinstance(self.project, ProjectIdentity) or not isinstance(self.profile, ProfileIdentity):
            raise ProvenanceError(MISSING_PROJECT_CONTEXT, "context identity is incomplete")
        if not isinstance(self.namespace, NamespaceIdentity):
            raise ProvenanceError(MISSING_PROJECT_CONTEXT, "context namespace is incomplete")
        if not isinstance(self.root_spec, StageRootAlias) or not isinstance(self.parent_store, ParentRefStoreV1):
            raise ProvenanceError(MISSING_PROJECT_CONTEXT, "context root or parent store is not admitted")
        if not isinstance(self.genre_identity, str) or not self.genre_identity:
            raise ProvenanceError(PROFILE_MISMATCH, "context genre is missing")
        if not isinstance(self.stage_alias, str) or not ALIAS_PATTERN.fullmatch(self.stage_alias):
            raise ProvenanceError(UNKNOWN_STAGE_ALIAS, "context stage alias is not approved")
        if not isinstance(self.root_alias, str) or not ALIAS_PATTERN.fullmatch(self.root_alias):
            raise ProvenanceError(UNKNOWN_STAGE_ALIAS, "context root alias is not approved")
        _validate_run_id(self.run_id)
        _check_nonempty(self.producer_version, "producer_version")
        entry = self.registry.lookup(
            self.project.project_id,
            self.profile.profile_id,
            self.profile.profile_version,
        )
        if entry.profile_definition_hash != self.profile.profile_definition_hash:
            raise ProvenanceError(PROFILE_MISMATCH, "context profile is not registry-bound")
        if entry.genre_identity != self.genre_identity:
            raise ProvenanceError(PROFILE_MISMATCH, "context genre is not registry-bound")
        expected = make_namespace(
            self.project,
            self.profile,
            entry.project_revision,
            self.namespace.namespace_schema_version,
        )
        if expected.to_preimage() != self.namespace.to_preimage():
            raise ProvenanceError(NAMESPACE_DIGEST_MISMATCH, "context namespace is not registry-bound")
        if expected.namespace_digest != self.namespace.namespace_digest:
            raise ProvenanceError(NAMESPACE_DIGEST_MISMATCH, "context namespace digest is forged")
        if self.root_spec.alias != self.root_alias or self.root_spec.stage_alias != self.stage_alias:
            raise ProvenanceError(UNKNOWN_STAGE_ALIAS, "context stage/root alias is not registry-bound")
        if self.root_spec.owner_id != self.registry.owner_id:
            raise ProvenanceError(UNKNOWN_STAGE_ALIAS, "context root owner is not registry-bound")
        self.parent_store.validate_for_context(self)

    @property
    def namespace_digest(self) -> str:
        return self.namespace.namespace_digest

    @property
    def project_id(self) -> str:
        return self.project.project_id


def _validate_run_id(run_id: str) -> None:
    if not RUN_ID_PATTERN.fullmatch(run_id or ""):
        raise ProvenanceError(INVALID_RUN_ID, "run_id must match YYYYMMDD-HHMMSS-ATT")


def _validate_root_path(path: Path, root_base: Path) -> Path:
    _assert_no_reparse(path)
    try:
        resolved = path.resolve(strict=False)
        resolved.relative_to(root_base.resolve(strict=False))
    except (OSError, ValueError) as exc:
        raise ProvenanceError(PATH_ESCAPE, "resolved path escapes stage root") from exc
    if resolved.drive.upper() != "D:":
        raise ProvenanceError(WRITE_BOUNDARY_UNCERTAIN, "resolved path is not on D drive")
    return resolved


def execution_root(context: ExecutionContext, create: bool = False) -> Path:
    """Derive the only writable root from owner alias, context and legal run id."""
    _validate_run_id(context.run_id)
    if context.root_spec.alias != context.root_alias:
        raise ProvenanceError(UNKNOWN_STAGE_ALIAS, "context root alias is not registry-bound")
    if context.root_spec.stage_alias != context.stage_alias:
        raise ProvenanceError(UNKNOWN_STAGE_ALIAS, "context stage alias is not registry-bound")
    if context.root_spec.owner_id != context.registry.owner_id:
        raise ProvenanceError(UNKNOWN_STAGE_ALIAS, "root owner does not match registry owner")
    base = _validate_stage_root_base(context.root_spec.root_base)
    path = base / context.run_id / context.namespace_digest[:16]
    resolved = _validate_root_path(path, base)
    if create:
        if resolved not in _ADMITTED_ROOTS:
            if resolved.exists() or resolved.is_symlink():
                raise ProvenanceError(WRITE_BOUNDARY_UNCERTAIN, "existing run root residue is denied")
            resolved.mkdir(parents=True, exist_ok=False)
            _assert_no_reparse(resolved)
            _ADMITTED_ROOTS.add(resolved)
    return resolved


def create_execution_context(
    *,
    registry: ProjectRegistryV1,
    project_id: str,
    profile_id: str,
    profile_version: str,
    profile_definition: ProfileDefinitionV1,
    stage_alias: str,
    root_alias: str,
    run_id: str,
    producer_version: str,
    registry_owner_id: str,
    registry_source_ref: str,
    registry_snapshot_hash: str,
    root_alias_registry: Mapping[str, StageRootAlias],
    parent_store: ParentRefStoreV1,
    namespace_schema_version: str = "namespace-v1",
) -> ExecutionContext:
    """Perform all identity/registry gates before stage/root capabilities."""
    entry = registry.lookup(project_id, profile_id, profile_version)
    registry.verify_authority(
        registry_owner_id, registry_source_ref, registry_snapshot_hash
    )
    if profile_definition.profile_id != entry.profile_id:
        raise ProvenanceError(PROFILE_MISMATCH, "profile id does not match registry entry")
    if profile_definition.profile_version != entry.profile_version:
        raise ProvenanceError(PROFILE_MISMATCH, "profile version does not match registry entry")
    if profile_definition.genre_identity != entry.genre_identity:
        raise ProvenanceError(PROFILE_MISMATCH, "genre identity does not match registry entry")
    if profile_definition.definition_hash != entry.profile_definition_hash:
        raise ProvenanceError(PROFILE_MISMATCH, "profile definition hash does not match registry entry")
    if root_alias not in root_alias_registry:
        raise ProvenanceError(UNKNOWN_STAGE_ALIAS, "root alias is not approved")
    root_spec = root_alias_registry[root_alias]
    if root_spec.stage_alias != stage_alias or root_spec.owner_id != registry.owner_id:
        raise ProvenanceError(UNKNOWN_STAGE_ALIAS, "stage/root owner binding mismatch")
    if not ALIAS_PATTERN.fullmatch(stage_alias or ""):
        raise ProvenanceError(UNKNOWN_STAGE_ALIAS, "stage alias is not approved")
    _validate_run_id(run_id)
    project = ProjectIdentity(project_id)
    profile = ProfileIdentity.from_definition(profile_definition)
    namespace = make_namespace(project, profile, entry.project_revision, namespace_schema_version)
    return ExecutionContext(
        registry=registry,
        project=project,
        profile=profile,
        namespace=namespace,
        genre_identity=profile_definition.genre_identity,
        stage_alias=stage_alias,
        root_alias=root_alias,
        run_id=run_id,
        producer_version=producer_version,
        root_spec=root_spec,
        parent_store=parent_store,
    )


def ensure_namespace_compatible(
    context: ExecutionContext,
    artifact_namespace_digest: str,
    *,
    operation: str = "replay",
) -> None:
    if artifact_namespace_digest != context.namespace_digest:
        code = OLD_NAMESPACE_ARTIFACT if operation == "replay" else NAMESPACE_DIGEST_MISMATCH
        raise ProvenanceError(code, "artifact namespace is not compatible", operation=operation)


def assert_profile_transition(old: ExecutionContext, new: ExecutionContext) -> None:
    if old.project_id != new.project_id:
        raise ProvenanceError(PROFILE_MISMATCH, "project identity cannot change in profile transition")
    if old.profile == new.profile:
        return
    if old.namespace_digest == new.namespace_digest:
        raise ProvenanceError(NAMESPACE_DIGEST_MISMATCH, "profile transition reused namespace digest")


_CURRENT_CONTEXT: ContextVar[ExecutionContext | None] = ContextVar(
    "xiaoshuo_execution_context", default=None
)


def get_execution_context(required: bool = True) -> ExecutionContext | None:
    context = _CURRENT_CONTEXT.get()
    if context is None and required:
        raise ProvenanceError(MISSING_PROJECT_CONTEXT, "explicit project/profile context is required")
    return context


@contextmanager
def activate_execution_context(context: ExecutionContext) -> Iterator[ExecutionContext]:
    token = _CURRENT_CONTEXT.set(context)
    try:
        yield context
    finally:
        _CURRENT_CONTEXT.reset(token)


_CALL_COUNTERS: dict[str, int] = {
    "import": 0,
    "module_main": 0,
    "in_process": 0,
    "process_spawn": 0,
    "logger": 0,
    "checkpoint": 0,
    "cache": 0,
    "writer": 0,
}
_ARTIFACT_VERIFICATION_SECRET = object()


class _ArtifactVerificationToken:
    __slots__ = ("integrity_digest", "secret")

    def __init__(self, integrity_digest: str):
        self.integrity_digest = integrity_digest
        self.secret = _ARTIFACT_VERIFICATION_SECRET


def reset_call_counters() -> None:
    for key in _CALL_COUNTERS:
        _CALL_COUNTERS[key] = 0


def record_call(kind: str) -> None:
    if kind not in _CALL_COUNTERS:
        raise ValueError(f"unknown call counter: {kind}")
    _CALL_COUNTERS[kind] += 1


def get_call_counters() -> dict[str, int]:
    return dict(_CALL_COUNTERS)


def assert_zero_call_counters() -> None:
    nonzero = {key: value for key, value in _CALL_COUNTERS.items() if value}
    if nonzero:
        raise AssertionError(f"forbidden call counters are non-zero: {nonzero}")


@dataclass(frozen=True)
class LegacyCapabilityManifest:
    module_path: str
    dynamic_imports_declared: bool = False
    unresolved_dependencies: tuple[str, ...] = ()
    unresolved_writers: tuple[str, ...] = ()
    top_level_logger_side_effect: bool = False
    top_level_checkpoint_side_effect: bool = False
    module_main: bool = False
    in_process_call: bool = False
    subprocess_spawn: bool = False


def census_legacy_capability(manifest: LegacyCapabilityManifest) -> None:
    """Deny before import for unknown or unsafe transitive capabilities."""
    if not manifest.dynamic_imports_declared:
        raise ProvenanceError(UNKNOWN_DYNAMIC_IMPORT, manifest.module_path)
    if manifest.unresolved_dependencies:
        raise ProvenanceError(
            UNRESOLVED_TRANSITIVE_DEPENDENCY,
            manifest.module_path,
            dependencies=manifest.unresolved_dependencies,
        )
    if manifest.unresolved_writers:
        raise ProvenanceError(UNMIGRATED_WRITER, manifest.module_path)
    if manifest.top_level_logger_side_effect or manifest.top_level_checkpoint_side_effect:
        raise ProvenanceError(IMPORT_SIDE_EFFECT_UNCERTAIN, manifest.module_path)
    if manifest.module_main or manifest.in_process_call or manifest.subprocess_spawn:
        raise ProvenanceError(LEGACY_CAPABILITY_DENIED, manifest.module_path)


def deny_legacy_execution(
    manifest: LegacyCapabilityManifest | None,
    *,
    call_kind: str,
) -> None:
    if manifest is None:
        raise ProvenanceError(UNKNOWN_DYNAMIC_IMPORT, "missing capability census")
    census_legacy_capability(manifest)
    raise ProvenanceError(LEGACY_CAPABILITY_DENIED, "legacy execution is not authorized", call_kind=call_kind)


def _validate_relative_path(relative_path: str) -> str:
    if not isinstance(relative_path, str) or not relative_path or "\x00" in relative_path:
        raise ProvenanceError(PATH_ESCAPE, "relative path is invalid")
    path = Path(relative_path)
    if path.is_absolute() or ":" in relative_path or any(part == ".." for part in path.parts):
        raise ProvenanceError(PATH_ESCAPE, "absolute and escaping paths are denied")
    return relative_path


@dataclass(frozen=True)
class ArtifactRef:
    project_id: str
    profile_id: str
    profile_version: str
    profile_definition_hash: str
    project_revision: str
    namespace_digest: str
    root_alias: str
    relative_path: str
    source_ref: str
    producer_version: str
    batch_id: str
    parent_refs: tuple[str, ...]
    length: int
    sha256: str
    integrity_digest: str = ""
    _verification_token: _ArtifactVerificationToken | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        _validate_relative_path(self.relative_path)
        _check_nonempty(self.project_id, "project_id")
        _check_nonempty(self.profile_id, "profile_id")
        _check_nonempty(self.profile_version, "profile_version")
        _check_nonempty(self.project_revision, "project_revision")
        _check_nonempty(self.root_alias, "root_alias")
        _check_nonempty(self.source_ref, "source_ref")
        _check_nonempty(self.producer_version, "producer_version")
        _check_nonempty(self.batch_id, "batch_id")
        _check_hash(self.profile_definition_hash, "profile_definition_hash")
        _check_hash(self.namespace_digest, "namespace_digest")
        _check_hash(self.sha256, "sha256")
        _check_hash(self.integrity_digest, "integrity_digest")
        if not self.parent_refs:
            raise ProvenanceError(PARENT_MISSING, "artifact must declare at least one parent reference")
        if any(not isinstance(parent, str) or not parent for parent in self.parent_refs):
            raise ProvenanceError(PARENT_MISSING, "artifact parent references must be non-empty")
        if self.length < 0:
            raise ProvenanceError("INVALID_ARTIFACT", "length must not be negative")

    def integrity_preimage(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "profile_definition_hash": self.profile_definition_hash,
            "project_revision": self.project_revision,
            "namespace_digest": self.namespace_digest,
            "root_alias": self.root_alias,
            "relative_path": self.relative_path,
            "source_ref": self.source_ref,
            "producer_version": self.producer_version,
            "batch_id": self.batch_id,
            "parent_refs": list(self.parent_refs),
            "length": self.length,
            "sha256": self.sha256,
        }


def _artifact_integrity_digest(artifact: ArtifactRef) -> str:
    return canonical_sha256(artifact.integrity_preimage())


def make_artifact_ref(
    context: ExecutionContext,
    relative_path: str,
    content: bytes,
    *,
    source_ref: str,
    batch_id: str,
    parent_refs: Sequence[str] = (),
) -> ArtifactRef:
    _validate_relative_path(relative_path)
    _validate_content_bytes(content)
    parent_tuple = tuple(parent_refs)
    context.parent_store.validate_parent_refs(context, parent_tuple)
    values = dict(
        project_id=context.project_id,
        profile_id=context.profile.profile_id,
        profile_version=context.profile.profile_version,
        profile_definition_hash=context.profile.profile_definition_hash,
        project_revision=context.namespace.project_revision,
        namespace_digest=context.namespace_digest,
        root_alias=context.root_alias,
        relative_path=relative_path,
        source_ref=source_ref,
        producer_version=context.producer_version,
        batch_id=batch_id,
        parent_refs=parent_tuple,
        length=len(content),
        sha256=sha256_bytes(content),
    )
    preverified = ArtifactRef(**values, integrity_digest="0" * 64)
    integrity_digest = _artifact_integrity_digest(preverified)
    return ArtifactRef(
        **values,
        integrity_digest=integrity_digest,
        _verification_token=_ArtifactVerificationToken(integrity_digest),
    )


def _validate_content_bytes(content: bytes) -> bytes:
    if not isinstance(content, bytes):
        raise ProvenanceError("INVALID_ARTIFACT", "artifact content must be bytes")
    if content.startswith(b"\xef\xbb\xbf"):
        raise ProvenanceError(BOM_FORBIDDEN, "UTF-8 BOM is not allowed")
    if b"\x00" in content:
        raise ProvenanceError("INVALID_CANONICAL_VALUE", "NUL is not allowed in artifact content")
    try:
        content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProvenanceError("INVALID_UTF8", "artifact content is not valid UTF-8") from exc
    return content


def _validate_artifact_binding(
    context: ExecutionContext,
    artifact: ArtifactRef,
    *,
    expected_batch_id: str | None = None,
) -> None:
    ensure_namespace_compatible(context, artifact.namespace_digest, operation="replay")
    if artifact.project_id != context.project_id:
        raise ProvenanceError(UNKNOWN_PROJECT, "artifact project mismatch")
    if artifact.profile_id != context.profile.profile_id:
        raise ProvenanceError(PROFILE_MISMATCH, "artifact profile mismatch")
    if artifact.profile_version != context.profile.profile_version:
        raise ProvenanceError(PROFILE_MISMATCH, "artifact profile version mismatch")
    if artifact.profile_definition_hash != context.profile.profile_definition_hash:
        raise ProvenanceError(PROFILE_MISMATCH, "artifact profile hash mismatch")
    if artifact.project_revision != context.namespace.project_revision:
        raise ProvenanceError(NAMESPACE_DIGEST_MISMATCH, "artifact revision mismatch")
    if artifact.root_alias != context.root_alias:
        raise ProvenanceError(BATCH_ROOT_ALIAS_MISMATCH, "artifact root alias mismatch")
    context.parent_store.validate_parent_refs(context, artifact.parent_refs)
    expected_integrity = _artifact_integrity_digest(artifact)
    if artifact.integrity_digest != expected_integrity:
        raise ProvenanceError(HASH_MISMATCH, "artifact lineage metadata integrity mismatch")
    if expected_batch_id is not None and artifact.batch_id != expected_batch_id:
        raise ProvenanceError(BATCH_DIGEST_MISMATCH, "artifact batch binding mismatch")


def validate_artifact_ref(
    context: ExecutionContext,
    artifact: ArtifactRef,
    content: bytes | None = None,
    *,
    expected_batch_id: str | None = None,
) -> None:
    if (
        not isinstance(artifact, ArtifactRef)
        or not isinstance(artifact._verification_token, _ArtifactVerificationToken)
        or artifact._verification_token.secret is not _ARTIFACT_VERIFICATION_SECRET
    ):
        raise ProvenanceError(ARTIFACT_NOT_VERIFIED, "artifact must be created by the verified provenance factory")
    _validate_artifact_binding(
        context,
        artifact,
        expected_batch_id=expected_batch_id,
    )
    expected_integrity = _artifact_integrity_digest(artifact)
    if artifact._verification_token.integrity_digest != expected_integrity:
        raise ProvenanceError(HASH_MISMATCH, "artifact verification token mismatch")
    if content is not None:
        _validate_content_bytes(content)
        if len(content) != artifact.length or sha256_bytes(content) != artifact.sha256:
            raise ProvenanceError(HASH_MISMATCH, "artifact content mismatch")


def validate_artifact_lineage(
    context: ExecutionContext,
    lineage: Mapping[str, Any],
    *,
    expected_batch_id: str | None = None,
) -> ArtifactRef:
    """Validate persisted lineage without granting it a runtime factory token."""
    if not isinstance(lineage, Mapping):
        raise ProvenanceError(REPLAY_CONFLICT, "persisted lineage is not a mapping")
    try:
        artifact = ArtifactRef(
            project_id=lineage["project_id"],
            profile_id=lineage["profile_id"],
            profile_version=lineage["profile_version"],
            profile_definition_hash=lineage["profile_definition_hash"],
            project_revision=lineage["project_revision"],
            namespace_digest=lineage["namespace_digest"],
            root_alias=lineage["root_alias"],
            relative_path=lineage["relative_path"],
            source_ref=lineage["source_ref"],
            producer_version=lineage["producer_version"],
            batch_id=lineage["batch_id"],
            parent_refs=tuple(lineage["parent_refs"]),
            length=lineage["content_length"],
            sha256=lineage["content_sha256"],
            integrity_digest=lineage["integrity_digest"],
        )
        _validate_artifact_binding(
            context,
            artifact,
            expected_batch_id=expected_batch_id,
        )
    except ProvenanceError as exc:
        raise ProvenanceError(REPLAY_CONFLICT, "persisted lineage is invalid", cause=exc.code) from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise ProvenanceError(REPLAY_CONFLICT, "persisted lineage is incomplete") from exc
    return artifact


def artifact_lineage(artifact: ArtifactRef) -> dict[str, Any]:
    """Return the complete, non-runtime lineage record for an artifact."""
    return {
        "project_id": artifact.project_id,
        "profile_id": artifact.profile_id,
        "profile_version": artifact.profile_version,
        "profile_definition_hash": artifact.profile_definition_hash,
        "project_revision": artifact.project_revision,
        "namespace_digest": artifact.namespace_digest,
        "root_alias": artifact.root_alias,
        "relative_path": artifact.relative_path,
        "source_ref": artifact.source_ref,
        "producer_version": artifact.producer_version,
        "batch_id": artifact.batch_id,
        "parent_refs": list(artifact.parent_refs),
        "content_length": artifact.length,
        "content_sha256": artifact.sha256,
        "integrity_digest": artifact.integrity_digest,
    }


def safe_write_bytes(
    context: ExecutionContext,
    relative_path: str,
    content: bytes,
    *,
    artifact_ref: ArtifactRef,
    expected_batch_id: str | None = None,
) -> Path:
    """The only writer helper: explicit context, D-drive root, relative path."""
    _validate_relative_path(relative_path)
    if expected_batch_id is None:
        raise ProvenanceError(BATCH_DIGEST_MISMATCH, "writer requires an explicit expected batch id")
    validate_artifact_ref(context, artifact_ref, content, expected_batch_id=expected_batch_id)
    if artifact_ref.relative_path != relative_path:
        raise ProvenanceError(PATH_ESCAPE, "artifact relative path does not match write target")
    preflight_root = execution_root(context, create=False)
    _validate_root_path(preflight_root / relative_path, preflight_root)
    root = execution_root(context, create=True)
    target = _validate_root_path(root / relative_path, root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target = _validate_root_path(target, root)
    if target.exists():
        try:
            existing = target.read_bytes()
        except OSError as exc:
            raise ProvenanceError(REPLAY_CONFLICT, "existing artifact cannot be read") from exc
        if existing == content:
            return target
        raise ProvenanceError(REPLAY_CONFLICT, "artifact replay conflicts with existing content")
    target.write_bytes(content)
    record_call("writer")
    return target


def safe_read_bytes(context: ExecutionContext, relative_path: str) -> bytes:
    root = execution_root(context, create=False)
    target = _validate_root_path(root / _validate_relative_path(relative_path), root)
    return target.read_bytes()


@dataclass(frozen=True)
class ExecutionBatchPreimageV2:
    batch_schema_version: str
    batch_id: str
    attempt_id: str
    namespace_digest: str
    stage_alias: str
    root_alias: str
    run_id: str
    producer_version: str
    started_at_utc: str
    finished_at_utc: str
    config_hash: str
    failure_chain: Any

    def to_preimage(self) -> dict[str, Any]:
        return {
            "batch_schema_version": self.batch_schema_version,
            "batch_id": self.batch_id,
            "attempt_id": self.attempt_id,
            "namespace_digest": self.namespace_digest,
            "stage_alias": self.stage_alias,
            "root_alias": self.root_alias,
            "run_id": self.run_id,
            "producer_version": self.producer_version,
            "started_at_utc": self.started_at_utc,
            "finished_at_utc": self.finished_at_utc,
            "config_hash": self.config_hash,
            "failure_chain": _copy_json(self.failure_chain),
        }


@dataclass(frozen=True)
class ExecutionBatch:
    batch_schema_version: str
    batch_id: str
    attempt_id: str
    namespace_digest: str
    stage_alias: str
    root_alias: str
    run_id: str
    producer_version: str
    started_at_utc: str
    finished_at_utc: str
    config_hash: str
    failure_chain: Any
    batch_digest: str
    evidence_envelope_hash: str

    def __post_init__(self) -> None:
        if not ALIAS_PATTERN.fullmatch(self.stage_alias or ""):
            raise ProvenanceError(BATCH_STAGE_ALIAS_MISMATCH, "invalid stage alias")
        if not ALIAS_PATTERN.fullmatch(self.root_alias or ""):
            raise ProvenanceError(BATCH_ROOT_ALIAS_MISMATCH, "missing or invalid root alias")
        _validate_run_id(self.run_id)
        _check_hash(self.namespace_digest, "namespace_digest")
        _check_hash(self.batch_digest, "batch_digest")
        _check_hash(self.evidence_envelope_hash, "evidence_envelope_hash")

    def preimage(self) -> ExecutionBatchPreimageV2:
        return ExecutionBatchPreimageV2(
            self.batch_schema_version, self.batch_id, self.attempt_id,
            self.namespace_digest, self.stage_alias, self.root_alias, self.run_id,
            self.producer_version, self.started_at_utc, self.finished_at_utc,
            self.config_hash, self.failure_chain,
        )


@dataclass(frozen=True)
class EvidenceEnvelopePreimageV2:
    envelope_schema_version: str
    execution_batch_id: str
    namespace_digest: str
    stage_alias: str
    root_alias: str
    run_id: str
    producer_version: str
    failure_chain: Any
    batch_digest: str
    input_artifact_refs: tuple[Any, ...]
    output_artifact_refs: tuple[Any, ...]
    source_refs: tuple[Any, ...]
    parent_refs: tuple[Any, ...]
    artifact_lengths: Mapping[str, Any]
    artifact_sha256: Mapping[str, Any]
    canonical_flags: Mapping[str, Any]
    tool_boundary: Mapping[str, Any]

    def to_preimage(self) -> dict[str, Any]:
        return {
            "envelope_schema_version": self.envelope_schema_version,
            "execution_batch_id": self.execution_batch_id,
            "namespace_digest": self.namespace_digest,
            "stage_alias": self.stage_alias,
            "root_alias": self.root_alias,
            "run_id": self.run_id,
            "producer_version": self.producer_version,
            "failure_chain": _copy_json(self.failure_chain),
            "batch_digest": self.batch_digest,
            "input_artifact_refs": list(self.input_artifact_refs),
            "output_artifact_refs": list(self.output_artifact_refs),
            "source_refs": list(self.source_refs),
            "parent_refs": list(self.parent_refs),
            "artifact_lengths": _copy_json(dict(self.artifact_lengths)),
            "artifact_sha256": _copy_json(dict(self.artifact_sha256)),
            "canonical_flags": _copy_json(dict(self.canonical_flags)),
            "tool_boundary": _copy_json(dict(self.tool_boundary)),
        }


@dataclass(frozen=True)
class EvidenceEnvelope:
    envelope_schema_version: str
    execution_batch_id: str
    namespace_digest: str
    stage_alias: str
    root_alias: str
    run_id: str
    producer_version: str
    failure_chain: Any
    batch_digest: str
    input_artifact_refs: tuple[Any, ...]
    output_artifact_refs: tuple[Any, ...]
    source_refs: tuple[Any, ...]
    parent_refs: tuple[Any, ...]
    artifact_lengths: Mapping[str, Any]
    artifact_sha256: Mapping[str, Any]
    canonical_flags: Mapping[str, Any]
    tool_boundary: Mapping[str, Any]
    evidence_envelope_hash: str

    def __post_init__(self) -> None:
        if not ALIAS_PATTERN.fullmatch(self.stage_alias or ""):
            raise ProvenanceError(BATCH_STAGE_ALIAS_MISMATCH, "invalid stage alias")
        if not ALIAS_PATTERN.fullmatch(self.root_alias or ""):
            raise ProvenanceError(BATCH_ROOT_ALIAS_MISMATCH, "missing or invalid root alias")
        _validate_run_id(self.run_id)
        _check_hash(self.namespace_digest, "namespace_digest")
        _check_hash(self.batch_digest, "batch_digest")
        _check_hash(self.evidence_envelope_hash, "evidence_envelope_hash")

    def preimage(self) -> EvidenceEnvelopePreimageV2:
        return EvidenceEnvelopePreimageV2(
            self.envelope_schema_version, self.execution_batch_id,
            self.namespace_digest, self.stage_alias, self.root_alias, self.run_id,
            self.producer_version, self.failure_chain, self.batch_digest,
            tuple(self.input_artifact_refs), tuple(self.output_artifact_refs),
            tuple(self.source_refs), tuple(self.parent_refs), self.artifact_lengths,
            self.artifact_sha256, self.canonical_flags, self.tool_boundary,
        )


def _validate_hash_exclusions(value: Mapping[str, Any], excluded: Sequence[str]) -> None:
    if any(field in value for field in excluded):
        raise ProvenanceError(SELF_REFERENTIAL_HASH_PREIMAGE, "post-hash field entered preimage")


def hash_execution_batch_preimage(value: Mapping[str, Any]) -> str:
    if tuple(value) != EXECUTION_BATCH_PREIMAGE_FIELDS:
        raise ProvenanceError(SELF_REFERENTIAL_HASH_PREIMAGE, "ExecutionBatch preimage fields are not exact")
    _validate_hash_exclusions(value, ("batch_digest", "evidence_envelope_hash"))
    return canonical_sha256(value)


def hash_evidence_envelope_preimage(value: Mapping[str, Any]) -> str:
    if tuple(value) != EVIDENCE_ENVELOPE_PREIMAGE_FIELDS:
        raise ProvenanceError(SELF_REFERENTIAL_HASH_PREIMAGE, "EvidenceEnvelope preimage fields are not exact")
    _validate_hash_exclusions(value, ("evidence_envelope_hash", "execution_batch"))
    return canonical_sha256(value)


def recompute_batch_digest(batch: ExecutionBatch | ExecutionBatchPreimageV2) -> str:
    preimage = batch.preimage() if isinstance(batch, ExecutionBatch) else batch
    if not ALIAS_PATTERN.fullmatch(preimage.stage_alias or ""):
        raise ProvenanceError(BATCH_STAGE_ALIAS_MISMATCH, "invalid stage alias")
    if not ALIAS_PATTERN.fullmatch(preimage.root_alias or ""):
        raise ProvenanceError(BATCH_ROOT_ALIAS_MISMATCH, "missing or invalid root alias")
    _validate_run_id(preimage.run_id)
    return hash_execution_batch_preimage(preimage.to_preimage())


def recompute_evidence_envelope_hash(
    envelope: EvidenceEnvelope | EvidenceEnvelopePreimageV2,
) -> str:
    preimage = envelope.preimage() if isinstance(envelope, EvidenceEnvelope) else envelope
    if not ALIAS_PATTERN.fullmatch(preimage.stage_alias or ""):
        raise ProvenanceError(BATCH_STAGE_ALIAS_MISMATCH, "invalid stage alias")
    if not ALIAS_PATTERN.fullmatch(preimage.root_alias or ""):
        raise ProvenanceError(BATCH_ROOT_ALIAS_MISMATCH, "missing or invalid root alias")
    _validate_run_id(preimage.run_id)
    values = preimage.to_preimage()
    return hash_evidence_envelope_preimage(values)


def _binding_error(
    expected: Any,
    actual: Any,
    code: str,
    field: str,
) -> ProvenanceError | None:
    if canonical_json_bytes({"value": expected}) != canonical_json_bytes({"value": actual}):
        return ProvenanceError(
            code,
            f"{field} does not match ExecutionBatch",
            binding_code=BATCH_ENVELOPE_BINDING_MISMATCH,
            field=field,
            expected=expected,
            actual=actual,
        )
    return None


def verify_batch_envelope_binding(
    batch: ExecutionBatch,
    envelope: EvidenceEnvelope,
) -> None:
    recomputed_batch_digest = recompute_batch_digest(batch)
    if recomputed_batch_digest != batch.batch_digest:
        raise ProvenanceError(
            BATCH_DIGEST_MISMATCH,
            "ExecutionBatch digest does not match its explicit preimage",
            binding_code=BATCH_ENVELOPE_BINDING_MISMATCH,
            field="batch_digest",
            expected=recomputed_batch_digest,
            actual=batch.batch_digest,
        )
    recomputed_envelope_hash = recompute_evidence_envelope_hash(envelope)
    if recomputed_envelope_hash != envelope.evidence_envelope_hash:
        raise ProvenanceError(
            HASH_MISMATCH,
            "EvidenceEnvelope hash does not match its explicit preimage",
            binding_code=BATCH_ENVELOPE_BINDING_MISMATCH,
            field="evidence_envelope_hash",
            expected=recomputed_envelope_hash,
            actual=envelope.evidence_envelope_hash,
        )
    checks = (
        (batch.batch_id, envelope.execution_batch_id, EXECUTION_BATCH_ID_MISMATCH, "execution_batch_id"),
        (batch.namespace_digest, envelope.namespace_digest, BATCH_NAMESPACE_MISMATCH, "namespace_digest"),
        (batch.stage_alias, envelope.stage_alias, BATCH_STAGE_ALIAS_MISMATCH, "stage_alias"),
        (batch.root_alias, envelope.root_alias, BATCH_ROOT_ALIAS_MISMATCH, "root_alias"),
        (batch.run_id, envelope.run_id, BATCH_RUN_ID_MISMATCH, "run_id"),
        (batch.producer_version, envelope.producer_version, BATCH_PRODUCER_VERSION_MISMATCH, "producer_version"),
        (batch.failure_chain, envelope.failure_chain, BATCH_FAILURE_CHAIN_MISMATCH, "failure_chain"),
        (batch.batch_digest, envelope.batch_digest, BATCH_DIGEST_MISMATCH, "batch_digest"),
    )
    for expected, actual, code, field in checks:
        error = _binding_error(expected, actual, code, field)
        if error:
            raise error


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def build_batch_and_envelope(
    context: ExecutionContext,
    *,
    batch_id: str,
    attempt_id: str,
    config_hash: str,
    failure_chain: Any = (),
    started_at_utc: str | None = None,
    finished_at_utc: str | None = None,
    envelope_overrides: Mapping[str, Any] | None = None,
    input_artifact_refs: Sequence[Any] = (),
    output_artifact_refs: Sequence[Any] = (),
    source_refs: Sequence[Any] = (),
    parent_refs: Sequence[Any] = (),
    artifact_lengths: Mapping[str, Any] | None = None,
    artifact_sha256: Mapping[str, Any] | None = None,
    canonical_flags: Mapping[str, Any] | None = None,
    tool_boundary: Mapping[str, Any] | None = None,
    phase_trace: list[str] | None = None,
) -> tuple[ExecutionBatch, EvidenceEnvelope]:
    """Strict two-pass construction: batch hash, equality gate, envelope hash."""
    _validate_run_id(context.run_id)
    if context.root_spec.alias != context.root_alias:
        raise ProvenanceError(BATCH_ROOT_ALIAS_MISMATCH, "root_alias is not bound to the approved root spec")
    if not context.root_alias or "/" in context.root_alias or "\\" in context.root_alias:
        raise ProvenanceError(BATCH_ROOT_ALIAS_MISMATCH, "root_alias must be an opaque alias")
    for name, value in (("batch_id", batch_id), ("attempt_id", attempt_id), ("config_hash", config_hash)):
        _check_nonempty(value, name)
    overrides = dict(envelope_overrides or {})
    trace = phase_trace if phase_trace is not None else []
    batch_preimage = ExecutionBatchPreimageV2(
        "execution-batch-v2", batch_id, attempt_id, context.namespace_digest,
        context.stage_alias, context.root_alias, context.run_id,
        context.producer_version, started_at_utc or _utc_now(),
        finished_at_utc or _utc_now(), config_hash, _copy_json(failure_chain),
    )
    batch_digest = recompute_batch_digest(batch_preimage)
    trace.append("batch_digest")

    envelope_values = {
        "execution_batch_id": overrides.get("execution_batch_id", batch_id),
        "namespace_digest": overrides.get("namespace_digest", context.namespace_digest),
        "stage_alias": overrides.get("stage_alias", context.stage_alias),
        "root_alias": overrides.get("root_alias", context.root_alias),
        "run_id": overrides.get("run_id", context.run_id),
        "producer_version": overrides.get("producer_version", context.producer_version),
        "failure_chain": _copy_json(overrides.get("failure_chain", failure_chain)),
        "batch_digest": overrides.get("batch_digest", batch_digest),
    }
    checks = (
        (batch_id, envelope_values["execution_batch_id"], EXECUTION_BATCH_ID_MISMATCH, "execution_batch_id"),
        (context.namespace_digest, envelope_values["namespace_digest"], BATCH_NAMESPACE_MISMATCH, "namespace_digest"),
        (context.stage_alias, envelope_values["stage_alias"], BATCH_STAGE_ALIAS_MISMATCH, "stage_alias"),
        (context.root_alias, envelope_values["root_alias"], BATCH_ROOT_ALIAS_MISMATCH, "root_alias"),
        (context.run_id, envelope_values["run_id"], BATCH_RUN_ID_MISMATCH, "run_id"),
        (context.producer_version, envelope_values["producer_version"], BATCH_PRODUCER_VERSION_MISMATCH, "producer_version"),
        (failure_chain, envelope_values["failure_chain"], BATCH_FAILURE_CHAIN_MISMATCH, "failure_chain"),
        (batch_digest, envelope_values["batch_digest"], BATCH_DIGEST_MISMATCH, "batch_digest"),
    )
    for expected, actual, code, field in checks:
        error = _binding_error(expected, actual, code, field)
        if error:
            raise error
    trace.append("equality_gate")

    envelope_preimage = EvidenceEnvelopePreimageV2(
        "evidence-envelope-v2", envelope_values["execution_batch_id"],
        envelope_values["namespace_digest"], envelope_values["stage_alias"],
        envelope_values["root_alias"], envelope_values["run_id"],
        envelope_values["producer_version"], envelope_values["failure_chain"],
        envelope_values["batch_digest"], tuple(input_artifact_refs),
        tuple(output_artifact_refs), tuple(source_refs), tuple(parent_refs),
        dict(artifact_lengths or {}), dict(artifact_sha256 or {}),
        dict(canonical_flags or {}), dict(tool_boundary or {}),
    )
    evidence_hash = recompute_evidence_envelope_hash(envelope_preimage)
    trace.append("evidence_envelope_hash")
    batch = ExecutionBatch(
        batch_preimage.batch_schema_version, batch_preimage.batch_id,
        batch_preimage.attempt_id, batch_preimage.namespace_digest,
        batch_preimage.stage_alias, batch_preimage.root_alias, batch_preimage.run_id,
        batch_preimage.producer_version, batch_preimage.started_at_utc,
        batch_preimage.finished_at_utc, batch_preimage.config_hash,
        batch_preimage.failure_chain, batch_digest, evidence_hash,
    )
    envelope = EvidenceEnvelope(
        envelope_preimage.envelope_schema_version, envelope_preimage.execution_batch_id,
        envelope_preimage.namespace_digest, envelope_preimage.stage_alias,
        envelope_preimage.root_alias, envelope_preimage.run_id,
        envelope_preimage.producer_version, envelope_preimage.failure_chain,
        envelope_preimage.batch_digest, envelope_preimage.input_artifact_refs,
        envelope_preimage.output_artifact_refs, envelope_preimage.source_refs,
        envelope_preimage.parent_refs, envelope_preimage.artifact_lengths,
        envelope_preimage.artifact_sha256, envelope_preimage.canonical_flags,
        envelope_preimage.tool_boundary, evidence_hash,
    )
    trace.append("finalize")
    verify_batch_envelope_binding(batch, envelope)
    if recompute_batch_digest(batch) != batch.batch_digest:
        raise ProvenanceError(HASH_MISMATCH, "batch digest recomputation failed")
    if recompute_evidence_envelope_hash(envelope) != envelope.evidence_envelope_hash:
        raise ProvenanceError(HASH_MISMATCH, "evidence envelope hash recomputation failed")
    trace.append("recompute")
    return batch, envelope


__all__ = [
    "ArtifactRef", "ExecutionBatch", "ExecutionBatchPreimageV2", "ExecutionContext",
    "EvidenceEnvelope", "EvidenceEnvelopePreimageV2", "LegacyCapabilityManifest",
    "NamespaceIdentity", "ProfileDefinitionV1", "ProfileIdentity", "ProjectEntryV1",
    "ProjectIdentity", "ProjectNamespaceV1", "ProjectRegistryOwner", "ProjectRegistryV1",
    "ParentRecordV1", "ParentRefStoreV1",
    "ProvenanceError", "StageRootAlias", "assert_profile_transition",
    "build_batch_and_envelope", "canonical_json_bytes", "canonical_sha256",
    "census_legacy_capability", "create_execution_context", "deny_legacy_execution",
    "ensure_namespace_compatible", "execution_root", "get_call_counters",
    "get_execution_context", "inject_project_registry", "make_artifact_ref",
    "hash_execution_batch_preimage", "hash_evidence_envelope_preimage",
    "make_namespace", "recompute_batch_digest", "recompute_evidence_envelope_hash",
    "record_call", "reset_call_counters", "safe_read_bytes", "safe_write_bytes",
    "sha256_bytes", "activate_execution_context", "assert_zero_call_counters",
    "validate_artifact_lineage", "verify_batch_envelope_binding",
]
