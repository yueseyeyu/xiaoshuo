"""Immutable, manifest-backed snapshots for the F0 rule-only flow."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import stat
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Literal, Mapping


SnapshotStatus = Literal["IN_PROGRESS", "COMPLETE", "PARTIAL", "INSUFFICIENT", "FAILED"]
_STATUSES = {"IN_PROGRESS", "COMPLETE", "PARTIAL", "INSUFFICIENT", "FAILED"}
_BASE = Path("D:/tmp/yeyu-ai-a3")
_SAFE = re.compile(r"^[A-Za-z0-9._-]+$")


class SnapshotValidationError(ValueError):
    def __init__(self, code: str, message: str | None = None):
        self.code = code
        super().__init__(message or code)


class SnapshotConflict(RuntimeError):
    pass


class SnapshotUpstreamConflict(SnapshotConflict):
    pass


class SnapshotPublishError(RuntimeError):
    def __init__(self, code: str, message: str | None = None):
        self.code = code
        super().__init__(message or code)


@dataclass(frozen=True)
class SnapshotMetadata:
    snapshot_id: str
    snapshot_type: str
    schema_version: str
    stage: str
    run_id: str
    attempt_id: str
    idempotency_key: str
    genre: str
    book_id: str
    source_input_hash: str
    upstream_snapshot_id: str | None
    upstream_snapshot_hash: str | None
    config_hash: str
    rubric_version: str
    calibration_version: str
    weight_version: str
    pool_version: str
    status: SnapshotStatus
    created_by: str
    created_at: str


@dataclass(frozen=True)
class SnapshotReadContract:
    stage: str
    snapshot_type: str
    schema_version: str
    run_id: str
    genre: str
    book_id: str
    source_input_hash: str
    config_hash: str
    rubric_version: str
    calibration_version: str
    weight_version: str
    pool_version: str
    upstream_snapshot_id: str | None
    upstream_snapshot_hash: str | None


@dataclass(frozen=True)
class SnapshotDocument:
    metadata: SnapshotMetadata
    payload: Mapping[str, Any]
    content_hash: str


@dataclass(frozen=True)
class SnapshotRef:
    snapshot_id: str
    snapshot_type: str
    status: SnapshotStatus
    content_hash: str
    relative_path: str
    replayed: bool = False


def _segment(value: str, code: str) -> None:
    if not isinstance(value, str) or not value or value in {".", ".."} or not _SAFE.fullmatch(value):
        raise SnapshotValidationError(code)


def _status(value: str) -> None:
    if value not in _STATUSES:
        raise SnapshotValidationError("INVALID_STATUS")


def _reparse(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    if os.name == "nt":
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        return attrs != 0xFFFFFFFF and bool(attrs & 0x400)
    return False


def _check_reparse(path: Path) -> None:
    current = path
    while True:
        if _reparse(current):
            raise SnapshotValidationError("EVIDENCE_ROOT_REPARSE_POINT")
        if current == current.parent:
            return
        current = current.parent


def _root(evidence_root: Path, stage: str, run_id: str) -> Path:
    if not isinstance(evidence_root, Path) or not evidence_root.is_absolute():
        raise SnapshotValidationError("EVIDENCE_ROOT_SCOPE_MISMATCH")
    _segment(stage, "INVALID_STAGE")
    _segment(run_id, "INVALID_RUN_ID")
    _check_reparse(evidence_root)
    root = evidence_root.resolve(strict=False)
    base = _BASE.resolve(strict=False)
    expected = (base / stage / run_id).resolve(strict=False)
    try:
        root.relative_to(base)
    except ValueError as exc:
        raise SnapshotValidationError("EVIDENCE_ROOT_SCOPE_MISMATCH") from exc
    if root != expected:
        raise SnapshotValidationError("EVIDENCE_ROOT_SCOPE_MISMATCH")
    _check_reparse(root)
    return root


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def compute_content_hash(document_without_content_hash: Mapping[str, Any]) -> str:
    projection = dict(document_without_content_hash)
    metadata = projection.get("metadata")
    if isinstance(metadata, Mapping):
        semantic_metadata = dict(metadata)
        semantic_metadata.pop("created_at", None)
        projection["metadata"] = semantic_metadata
    return hashlib.sha256(canonical_json_bytes(projection)).hexdigest()


def _identity_hash(metadata: SnapshotMetadata) -> str:
    values = asdict(metadata)
    fields = (
        "snapshot_type", "schema_version", "stage", "run_id", "attempt_id",
        "idempotency_key", "genre", "book_id", "source_input_hash",
        "upstream_snapshot_id", "upstream_snapshot_hash", "config_hash",
        "rubric_version", "calibration_version", "weight_version",
        "pool_version", "status", "created_by",
    )
    digest = hashlib.sha256()
    for field in fields:
        encoded = canonical_json_bytes(values[field])
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def build_snapshot_metadata(
    *, snapshot_type: str, schema_version: str, run_id: str, attempt_id: str,
    idempotency_key: str, genre: str, book_id: str, source_input_hash: str,
    upstream_snapshot_id: str | None, upstream_snapshot_hash: str | None,
    config_hash: str, rubric_version: str, calibration_version: str,
    weight_version: str, pool_version: str, status: SnapshotStatus,
    created_by: str, created_at: str, stage: str,
) -> SnapshotMetadata:
    _segment(stage, "INVALID_STAGE")
    _segment(run_id, "INVALID_RUN_ID")
    _segment(snapshot_type, "INVALID_SNAPSHOT_TYPE")
    _status(status)
    metadata = SnapshotMetadata(
        snapshot_id="", snapshot_type=snapshot_type, schema_version=schema_version,
        stage=stage, run_id=run_id, attempt_id=attempt_id,
        idempotency_key=idempotency_key, genre=genre, book_id=book_id,
        source_input_hash=source_input_hash,
        upstream_snapshot_id=upstream_snapshot_id,
        upstream_snapshot_hash=upstream_snapshot_hash, config_hash=config_hash,
        rubric_version=rubric_version, calibration_version=calibration_version,
        weight_version=weight_version, pool_version=pool_version, status=status,
        created_by=created_by, created_at=created_at,
    )
    return replace(metadata, snapshot_id=_identity_hash(metadata))


def _document(metadata: SnapshotMetadata, payload: Mapping[str, Any]) -> dict[str, Any]:
    return {"metadata": asdict(metadata), "payload": dict(payload)}


def _semantic_metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result.pop("created_at", None)
    return result


def _semantic_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    return _semantic_metadata(value)


def _paths(root: Path, metadata: SnapshotMetadata) -> tuple[Path, Path, str]:
    relative = Path("snapshots") / metadata.snapshot_type / metadata.run_id / f"{metadata.snapshot_id}.json"
    relative_text = relative.as_posix()
    target = root / relative
    return target, target.with_suffix(".manifest.json"), relative_text


def _read_json(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SnapshotValidationError(code) from exc
    if not isinstance(value, dict):
        raise SnapshotValidationError(code)
    return value


def _write_fsync(path: Path, data: bytes) -> None:
    with open(path, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateFileW(str(path), 0x40000000, 0x00000007, None, 3, 0x02000000, None)
        if handle == -1:
            raise OSError("directory open failed")
        try:
            if not kernel32.FlushFileBuffers(handle):
                raise OSError("directory flush failed")
        finally:
            kernel32.CloseHandle(handle)
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _manifest(metadata: SnapshotMetadata, content_hash: str, relative_path: str, publish_state: str) -> dict[str, Any]:
    return {
        "snapshot_id": metadata.snapshot_id, "snapshot_type": metadata.snapshot_type,
        "stage": metadata.stage, "run_id": metadata.run_id,
        "attempt_id": metadata.attempt_id, "status": metadata.status,
        "content_hash": content_hash, "relative_path": relative_path,
        "created_at": metadata.created_at, "publish_state": publish_state,
    }


def _verify_pair(target: Path, manifest_path: Path, metadata: SnapshotMetadata, payload: Mapping[str, Any], relative_path: str) -> tuple[str, bool]:
    document = _read_json(target, "SNAPSHOT_JSON_INVALID")
    manifest = _read_json(manifest_path, "MANIFEST_INVALID")
    expected_document = _document(metadata, payload)
    content_hash = compute_content_hash(expected_document)
    if document.get("content_hash") != content_hash:
        raise SnapshotValidationError("CONTENT_HASH_MISMATCH")
    if _semantic_metadata(document.get("metadata", {})) != _semantic_metadata(asdict(metadata)) or document.get("payload") != dict(payload):
        raise SnapshotValidationError("MANIFEST_DOCUMENT_MISMATCH")
    if _semantic_manifest(manifest) != _semantic_manifest(_manifest(metadata, content_hash, relative_path, "PUBLISHED")):
        raise SnapshotValidationError("MANIFEST_DOCUMENT_MISMATCH")
    return content_hash, True


def publish_snapshot(evidence_root: Path, metadata: SnapshotMetadata, payload: Mapping[str, Any]) -> SnapshotRef:
    root = _root(evidence_root, metadata.stage, metadata.run_id)
    if not isinstance(payload, Mapping):
        raise SnapshotValidationError("PAYLOAD_NOT_MAPPING")
    _status(metadata.status)
    if _identity_hash(metadata) != metadata.snapshot_id:
        raise SnapshotValidationError("SNAPSHOT_ID_MISMATCH")
    target, manifest_path, relative_path = _paths(root, metadata)
    _check_reparse(target.parent)
    target.parent.mkdir(parents=True, exist_ok=True)
    _check_reparse(target.parent)
    _check_reparse(target)
    _check_reparse(manifest_path)
    document_without_hash = _document(metadata, payload)
    content_hash = compute_content_hash(document_without_hash)
    document_bytes = canonical_json_bytes({**document_without_hash, "content_hash": content_hash}) + b"\n"
    manifest_bytes = canonical_json_bytes(_manifest(metadata, content_hash, relative_path, "PUBLISHED")) + b"\n"
    target_exists, manifest_exists = target.exists(), manifest_path.exists()
    if target_exists or manifest_exists:
        if target_exists and not manifest_exists:
            raise SnapshotPublishError("MANIFEST_REQUIRED_FOR_REPLAY")
        if manifest_exists and not target_exists:
            raise SnapshotValidationError("SNAPSHOT_TARGET_MISSING")
        existing = _read_json(target, "SNAPSHOT_JSON_INVALID")
        existing_manifest = _read_json(manifest_path, "MANIFEST_INVALID")
        existing_meta = existing.get("metadata", {})
        if existing_manifest.get("publish_state") != "PUBLISHED":
            raise SnapshotPublishError("MANIFEST_INVALID")
        if existing_manifest.get("relative_path") != relative_path or existing_manifest.get("content_hash") != existing.get("content_hash"):
            raise SnapshotValidationError("MANIFEST_INVALID")
        if existing_meta.get("upstream_snapshot_id") != metadata.upstream_snapshot_id or existing_meta.get("upstream_snapshot_hash") != metadata.upstream_snapshot_hash:
            raise SnapshotUpstreamConflict("SNAPSHOT_UPSTREAM_CONFLICT")
        if existing.get("content_hash") == content_hash:
            if _semantic_metadata(existing_meta) != _semantic_metadata(asdict(metadata)) or existing.get("payload") != dict(payload):
                raise SnapshotConflict("SNAPSHOT_CONTENT_CONFLICT")
            _verify_pair(target, manifest_path, metadata, payload, relative_path)
            return SnapshotRef(metadata.snapshot_id, metadata.snapshot_type, metadata.status, content_hash, relative_path, True)
        raise SnapshotConflict("SNAPSHOT_CONTENT_CONFLICT")
    temp = target.parent / f".{metadata.snapshot_id}.{metadata.attempt_id}.tmp"
    manifest_temp = target.parent / f".{metadata.snapshot_id}.{metadata.attempt_id}.manifest.tmp"
    _check_reparse(temp)
    _check_reparse(manifest_temp)
    try:
        _write_fsync(temp, document_bytes)
    except Exception as exc:
        raise SnapshotPublishError("DOCUMENT_TEMP_WRITE_FAILED") from exc
    try:
        if _read_json(temp, "SNAPSHOT_TEMP_INVALID").get("content_hash") != content_hash:
            raise ValueError("document temp hash mismatch")
    except Exception as exc:
        raise SnapshotPublishError("DOCUMENT_TEMP_HASH_MISMATCH") from exc
    try:
        os.replace(temp, target)
    except Exception as exc:
        raise SnapshotPublishError("DOCUMENT_TARGET_REPLACE_FAILED") from exc
    try:
        _fsync_directory(target.parent)
    except Exception as exc:
        raise SnapshotPublishError("DIRECTORY_FSYNC_AFTER_TARGET_FAILED") from exc

    orphan_manifest_bytes = canonical_json_bytes(_manifest(metadata, content_hash, relative_path, "ORPHAN")) + b"\n"
    try:
        _write_fsync(manifest_temp, orphan_manifest_bytes)
        if _read_json(manifest_temp, "ORPHAN_MANIFEST_TEMP_INVALID").get("publish_state") != "ORPHAN":
            raise ValueError("orphan manifest readback mismatch")
    except Exception as exc:
        raise SnapshotPublishError("ORPHAN_MANIFEST_TEMP_FAILED") from exc
    try:
        os.replace(manifest_temp, manifest_path)
    except Exception as exc:
        raise SnapshotPublishError("ORPHAN_MANIFEST_REPLACE_FAILED") from exc
    try:
        _fsync_directory(target.parent)
    except Exception as exc:
        raise SnapshotPublishError("DIRECTORY_FSYNC_AFTER_ORPHAN_MANIFEST_FAILED") from exc

    try:
        _write_fsync(manifest_temp, manifest_bytes)
        if _read_json(manifest_temp, "PUBLISHED_MANIFEST_TEMP_INVALID").get("publish_state") != "PUBLISHED":
            raise ValueError("published manifest readback mismatch")
    except Exception as exc:
        raise SnapshotPublishError("PUBLISHED_MANIFEST_TEMP_FAILED") from exc
    try:
        os.replace(manifest_temp, manifest_path)
    except Exception as exc:
        raise SnapshotPublishError("PUBLISHED_MANIFEST_REPLACE_FAILED") from exc
    try:
        _verify_pair(target, manifest_path, metadata, payload, relative_path)
    except Exception as exc:
        raise SnapshotPublishError("PUBLISHED_PAIR_VERIFY_FAILED") from exc
    return SnapshotRef(metadata.snapshot_id, metadata.snapshot_type, metadata.status, content_hash, relative_path, False)


def _relative(relative_path: str, snapshot_type: str, run_id: str, snapshot_id: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path:
        raise SnapshotValidationError("RELATIVE_PATH_TRAVERSAL")
    normalized = relative_path.replace("\\", "/")
    path = Path(normalized)
    if path.is_absolute() or path.drive:
        raise SnapshotValidationError("RELATIVE_PATH_TRAVERSAL")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise SnapshotValidationError("RELATIVE_PATH_TRAVERSAL")
    expected = f"snapshots/{snapshot_type}/{run_id}/{snapshot_id}.json"
    if normalized != expected:
        raise SnapshotValidationError("NON_CANONICAL_SNAPSHOT_PATH")
    return Path(*parts)


def _metadata(values: Mapping[str, Any]) -> SnapshotMetadata:
    try:
        metadata = SnapshotMetadata(**dict(values))
    except Exception as exc:
        raise SnapshotValidationError("METADATA_INVALID") from exc
    _status(metadata.status)
    return metadata


def read_snapshot(evidence_root: Path, ref: SnapshotRef, *, expected: SnapshotReadContract, require_complete: bool = True) -> SnapshotDocument:
    root = _root(evidence_root, expected.stage, expected.run_id)
    relative = _relative(ref.relative_path, expected.snapshot_type, expected.run_id, ref.snapshot_id)
    target = root / relative
    try:
        target.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise SnapshotValidationError("EVIDENCE_PATH_ESCAPE") from exc
    manifest_path = target.with_suffix(".manifest.json")
    _check_reparse(target)
    _check_reparse(manifest_path)
    if not manifest_path.is_file():
        raise SnapshotValidationError("MANIFEST_INVALID")
    manifest = _read_json(manifest_path, "MANIFEST_INVALID")
    if not target.is_file():
        raise SnapshotValidationError("SNAPSHOT_TARGET_MISSING")
    document = _read_json(target, "SNAPSHOT_JSON_INVALID")
    metadata = _metadata(document.get("metadata", {}))
    payload = document.get("payload")
    if not isinstance(payload, Mapping):
        raise SnapshotValidationError("PAYLOAD_INVALID")
    if manifest.get("publish_state") != "PUBLISHED":
        raise SnapshotValidationError("MANIFEST_INVALID")
    if _semantic_manifest(manifest) != _semantic_manifest(_manifest(metadata, document.get("content_hash"), ref.relative_path, "PUBLISHED")):
        raise SnapshotValidationError("MANIFEST_DOCUMENT_MISMATCH")
    if metadata.snapshot_id != ref.snapshot_id or metadata.snapshot_type != ref.snapshot_type or metadata.status != ref.status or document.get("content_hash") != ref.content_hash:
        raise SnapshotValidationError("REF_DOCUMENT_MISMATCH")
    if _identity_hash(metadata) != metadata.snapshot_id:
        raise SnapshotValidationError("SNAPSHOT_ID_MISMATCH")
    if compute_content_hash(_document(metadata, payload)) != document.get("content_hash"):
        raise SnapshotValidationError("CONTENT_HASH_MISMATCH")
    checks = (
        ("stage", expected.stage, "CONTRACT_STAGE_MISMATCH"),
        ("snapshot_type", expected.snapshot_type, "CONTRACT_TYPE_MISMATCH"),
        ("schema_version", expected.schema_version, "CONTRACT_SCHEMA_MISMATCH"),
        ("run_id", expected.run_id, "CONTRACT_RUN_MISMATCH"),
        ("genre", expected.genre, "CONTRACT_GENRE_MISMATCH"),
        ("book_id", expected.book_id, "CONTRACT_BOOK_MISMATCH"),
        ("source_input_hash", expected.source_input_hash, "CONTRACT_SOURCE_HASH_MISMATCH"),
        ("config_hash", expected.config_hash, "CONTRACT_CONFIG_HASH_MISMATCH"),
        ("rubric_version", expected.rubric_version, "CONTRACT_RUBRIC_VERSION_MISMATCH"),
        ("calibration_version", expected.calibration_version, "CONTRACT_CALIBRATION_VERSION_MISMATCH"),
        ("weight_version", expected.weight_version, "CONTRACT_WEIGHT_VERSION_MISMATCH"),
        ("pool_version", expected.pool_version, "CONTRACT_POOL_VERSION_MISMATCH"),
    )
    for field, value, code in checks:
        if getattr(metadata, field) != value:
            raise SnapshotValidationError(code)
    if (metadata.upstream_snapshot_id, metadata.upstream_snapshot_hash) != (expected.upstream_snapshot_id, expected.upstream_snapshot_hash):
        raise SnapshotValidationError("CONTRACT_UPSTREAM_MISMATCH")
    if require_complete and metadata.status != "COMPLETE":
        raise SnapshotValidationError("NON_COMPLETE_CONSUMPTION")
    return SnapshotDocument(metadata, payload, document["content_hash"])
