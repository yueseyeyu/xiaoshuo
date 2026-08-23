"""Internal C3 commands for Canon ChangeSet preparation and approval.

They are application commands, not HTTP DTOs.  Trusted author identity and
delivery idempotency are intentionally supplied through separate dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass


CANON_COMMAND_SCHEMA_VERSION = 2


@dataclass(frozen=True, slots=True)
class PrepareCanonChangesetCommand:
    task_id: str
    expected_revision: int
    target_bundle_bytes: bytes
    command_schema_version: int = CANON_COMMAND_SCHEMA_VERSION
    # Kept only to make old v1 envelopes representable.  It is never accepted
    # as a v2 authority and is excluded from the v2 request contract.
    base_manifest_hash: str | None = None

    def __post_init__(self) -> None:
        # Preserve construction of historical v1 envelopes while making the
        # v2 positional form unambiguous (task_id, revision, bundle_bytes).
        if isinstance(self.target_bundle_bytes, str) and isinstance(self.command_schema_version, bytes):
            old_base = self.target_bundle_bytes
            old_bundle = self.command_schema_version
            object.__setattr__(self, "target_bundle_bytes", old_bundle)
            object.__setattr__(self, "command_schema_version", 1)
            object.__setattr__(self, "base_manifest_hash", old_base)
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ValueError("task_id must be non-empty")
        if type(self.expected_revision) is not int or self.expected_revision < 0:
            raise ValueError("expected_revision must be non-negative")
        if not isinstance(self.target_bundle_bytes, bytes) or not self.target_bundle_bytes:
            raise ValueError("target_bundle_bytes must be non-empty bytes")
        if type(self.command_schema_version) is not int:
            raise ValueError("unsupported Canon command schema version")
        if self.command_schema_version == 1:
            if not _is_hash(self.base_manifest_hash):
                raise ValueError("v1 base_manifest_hash must be a sha256 hash")
        elif self.command_schema_version == 2:
            if self.base_manifest_hash is not None:
                raise ValueError("v2 Prepare must not accept caller base identity")
        else:
            raise ValueError("unsupported Canon command schema version")


@dataclass(frozen=True, slots=True)
class ApproveCanonChangesetCommand:
    task_id: str
    decision_id: str
    expected_revision: int
    command_schema_version: int = CANON_COMMAND_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ValueError("task_id must be non-empty")
        if not isinstance(self.decision_id, str) or not self.decision_id.strip():
            raise ValueError("decision_id must be non-empty")
        if type(self.expected_revision) is not int or self.expected_revision < 0:
            raise ValueError("expected_revision must be non-negative")
        if self.command_schema_version != CANON_COMMAND_SCHEMA_VERSION:
            raise ValueError("unsupported Canon command schema version")


def _is_hash(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(ch in "0123456789abcdef" for ch in value[7:])
    )
