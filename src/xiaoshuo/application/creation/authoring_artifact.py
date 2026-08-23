"""Canonical authoring-envelope contracts for C5-G0 G0-B.

This module is intentionally pure application code.  It parses and
serializes operator-owned bytes but never reads configuration, paths,
SQLite, or an infrastructure adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import re

from xiaoshuo.domain.creation import ArtifactRef, ChapterTaskStatus

from .errors import AuthoringArtifactInputRejected
from .results import APPLICATION_RESULT_SCHEMA_VERSION


AUTHORING_ARTIFACT_SCHEMA_VERSION = 1
AUTHORING_ARTIFACT_REF_SCHEMA_VERSION = 1
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMON_FIELDS = frozenset(
    {
        "artifact_kind",
        "artifact_schema_version",
        "project_id",
        "chapter_number",
        "task_id",
        "body",
    }
)
_REVIEW_FIELDS = _COMMON_FIELDS | {"reviewed_draft_ref", "verdict"}


class AuthoringArtifactKind(str, Enum):
    CREATIVE_INTENT = "CREATIVE_INTENT"
    PLAN = "PLAN"
    DRAFT = "DRAFT"
    REVIEW = "REVIEW"


@dataclass(frozen=True, slots=True)
class AuthoringArtifactEnvelope:
    artifact_kind: AuthoringArtifactKind
    artifact_schema_version: int
    project_id: str
    chapter_number: int
    task_id: str
    body: str = field(repr=False)
    reviewed_draft_ref: ArtifactRef | None = None
    verdict: str | None = None


@dataclass(frozen=True, slots=True)
class AuthoringArtifactSubmissionResult:
    artifact_kind: AuthoringArtifactKind
    artifact_ref: ArtifactRef
    task_id: str
    aggregate_revision: int
    status: ChapterTaskStatus
    operation_id: str
    audit_event_ids: tuple[str, ...]
    result_schema_version: int = APPLICATION_RESULT_SCHEMA_VERSION


def authoring_artifact_content_hash(data: bytes) -> str:
    """Hash exact bytes without interpreting their business semantics."""
    if type(data) is not bytes:
        raise AuthoringArtifactInputRejected("authoring envelope must be bytes")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def parse_authoring_artifact_envelope(data: bytes) -> AuthoringArtifactEnvelope:
    """Parse only exact canonical UTF-8 JSON accepted by the G0-B contract."""
    if type(data) is not bytes:
        raise AuthoringArtifactInputRejected("authoring envelope must be bytes")
    if data.startswith(b"\xef\xbb\xbf"):
        raise AuthoringArtifactInputRejected("authoring envelope must not contain a BOM")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise AuthoringArtifactInputRejected(
            "authoring envelope must be strict UTF-8"
        ) from exc
    if "\x00" in text:
        raise AuthoringArtifactInputRejected("authoring envelope must not contain NUL")
    try:
        payload = json.loads(text, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, ValueError) as exc:
        raise AuthoringArtifactInputRejected(
            "authoring envelope must be canonical JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise AuthoringArtifactInputRejected("authoring envelope root must be an object")

    try:
        kind = AuthoringArtifactKind(payload.get("artifact_kind"))
    except (TypeError, ValueError) as exc:
        raise AuthoringArtifactInputRejected("unsupported authoring artifact kind") from exc
    expected_fields = _REVIEW_FIELDS if kind is AuthoringArtifactKind.REVIEW else _COMMON_FIELDS
    if set(payload) != expected_fields:
        raise AuthoringArtifactInputRejected("authoring envelope fields are invalid")
    if (
        type(payload["artifact_schema_version"]) is not int
        or payload["artifact_schema_version"] != AUTHORING_ARTIFACT_SCHEMA_VERSION
    ):
        raise AuthoringArtifactInputRejected("unsupported authoring artifact schema")
    project_id = _non_empty_string(payload["project_id"], "project_id")
    task_id = _non_empty_string(payload["task_id"], "task_id")
    body = _non_empty_string(payload["body"], "body")
    chapter_number = payload["chapter_number"]
    if type(chapter_number) is not int or chapter_number <= 0:
        raise AuthoringArtifactInputRejected("chapter_number must be a positive integer")

    reviewed_draft_ref: ArtifactRef | None = None
    verdict: str | None = None
    if kind is AuthoringArtifactKind.REVIEW:
        reviewed_draft_ref = _artifact_ref(payload["reviewed_draft_ref"])
        verdict = payload["verdict"]
        if verdict != "PASS":
            raise AuthoringArtifactInputRejected("only PASS review verdict is supported")

    canonical = _canonical_json_bytes(payload)
    if canonical != data:
        raise AuthoringArtifactInputRejected("authoring envelope is not canonical JSON")
    return AuthoringArtifactEnvelope(
        artifact_kind=kind,
        artifact_schema_version=payload["artifact_schema_version"],
        project_id=project_id,
        chapter_number=chapter_number,
        task_id=task_id,
        body=body,
        reviewed_draft_ref=reviewed_draft_ref,
        verdict=verdict,
    )


def serialize_authoring_artifact_envelope(
    envelope: AuthoringArtifactEnvelope,
) -> bytes:
    """Serialize an immutable envelope to the one accepted byte form."""
    if not isinstance(envelope, AuthoringArtifactEnvelope):
        raise AuthoringArtifactInputRejected("invalid authoring envelope DTO")
    payload: dict[str, object] = {
        "artifact_kind": envelope.artifact_kind.value,
        "artifact_schema_version": envelope.artifact_schema_version,
        "project_id": envelope.project_id,
        "chapter_number": envelope.chapter_number,
        "task_id": envelope.task_id,
        "body": envelope.body,
    }
    if envelope.artifact_kind is AuthoringArtifactKind.REVIEW:
        if envelope.reviewed_draft_ref is None or envelope.verdict != "PASS":
            raise AuthoringArtifactInputRejected("invalid REVIEW envelope DTO")
        payload["reviewed_draft_ref"] = {
            "artifact_id": envelope.reviewed_draft_ref.artifact_id,
            "schema_version": envelope.reviewed_draft_ref.schema_version,
            "content_hash": envelope.reviewed_draft_ref.content_hash,
        }
        payload["verdict"] = envelope.verdict
    elif envelope.reviewed_draft_ref is not None or envelope.verdict is not None:
        raise AuthoringArtifactInputRejected("non-REVIEW envelope has review fields")
    data = _canonical_json_bytes(payload)
    # Reuse the parser so serializers cannot manufacture a looser wire form.
    parse_authoring_artifact_envelope(data)
    return data


def _canonical_json_bytes(payload: object) -> bytes:
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AuthoringArtifactInputRejected("authoring envelope is not JSON-safe") from exc


def _non_empty_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthoringArtifactInputRejected(f"{field_name} must be a non-empty string")
    if "\x00" in value:
        raise AuthoringArtifactInputRejected(f"{field_name} must not contain NUL")
    return value


def _artifact_ref(value: object) -> ArtifactRef:
    if not isinstance(value, dict) or set(value) != {
        "artifact_id",
        "schema_version",
        "content_hash",
    }:
        raise AuthoringArtifactInputRejected("reviewed_draft_ref is invalid")
    artifact_id = _non_empty_string(value["artifact_id"], "artifact_id")
    schema_version = value["schema_version"]
    content_hash = value["content_hash"]
    if type(schema_version) is not int or schema_version != AUTHORING_ARTIFACT_REF_SCHEMA_VERSION:
        raise AuthoringArtifactInputRejected("reviewed_draft_ref schema is invalid")
    if not isinstance(content_hash, str) or _SHA256.fullmatch(content_hash) is None:
        raise AuthoringArtifactInputRejected("reviewed_draft_ref hash is invalid")
    try:
        return ArtifactRef(artifact_id, schema_version, content_hash)
    except Exception as exc:
        raise AuthoringArtifactInputRejected("reviewed_draft_ref is invalid") from exc


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"unsupported JSON constant {value}")
