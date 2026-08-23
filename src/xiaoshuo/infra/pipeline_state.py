#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Explicit-context pipeline state persistence."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from xiaoshuo.pipeline.provenance import (
    ArtifactRef,
    ExecutionContext,
    ProvenanceError,
    REPLAY_CONFLICT,
    artifact_lineage,
    execution_root,
    get_execution_context,
    record_call,
    validate_artifact_ref,
    validate_artifact_lineage,
    _validate_root_path,
)


PIPELINE_STAGE_FILE: Path | None = None
_lock = threading.Lock()


def _stage_path(context: ExecutionContext, *, create: bool = False) -> Path:
    preflight_root = execution_root(context, create=False)
    preflight_candidate = PIPELINE_STAGE_FILE or (preflight_root / "pipeline_stage.json")
    preflight_candidate = _validate_root_path(Path(preflight_candidate), preflight_root)
    if not create:
        return preflight_candidate
    root = execution_root(context, create=True)
    candidate = PIPELINE_STAGE_FILE or (root / "pipeline_stage.json")
    candidate = _validate_root_path(Path(candidate), root)
    if candidate.drive.upper() != "D:":
        raise ProvenanceError("WRITE_BOUNDARY_UNCERTAIN", "pipeline state is not on D drive")
    return candidate


def _read_state_record(path: Path, context: ExecutionContext) -> tuple[dict[str, Any], ArtifactRef]:
    root = execution_root(context, create=False)
    path = _validate_root_path(path, root)
    try:
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf") or b"\x00" in raw:
            raise ProvenanceError(REPLAY_CONFLICT, "pipeline state contains forbidden bytes")
        data = json.loads(raw.decode("utf-8"))
    except ProvenanceError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ProvenanceError(REPLAY_CONFLICT, "pipeline state record is corrupted") from exc
    if not isinstance(data, dict):
        raise ProvenanceError(REPLAY_CONFLICT, "pipeline state record is not an object")
    required_fields = (
        "stage",
        "status",
        "started_at",
        "updated_at",
        "lineage",
        "content_length",
        "content_sha256",
        "batch_id",
    )
    if any(field not in data for field in required_fields):
        raise ProvenanceError(REPLAY_CONFLICT, "pipeline state record is incomplete")
    expected_context = {
        "project_id": context.project_id,
        "namespace_digest": context.namespace_digest,
        "stage_alias": context.stage_alias,
        "root_alias": context.root_alias,
        "run_id": context.run_id,
        "profile_id": context.profile.profile_id,
        "profile_version": context.profile.profile_version,
        "profile_definition_hash": context.profile.profile_definition_hash,
        "project_revision": context.namespace.project_revision,
        "producer_version": context.producer_version,
    }
    if any(data.get(key) != value for key, value in expected_context.items()):
        raise ProvenanceError(REPLAY_CONFLICT, "pipeline state context conflicts with execution context")
    try:
        artifact = validate_artifact_lineage(
            context,
            data["lineage"],
            expected_batch_id=data["batch_id"],
        )
    except (KeyError, TypeError, ProvenanceError) as exc:
        if isinstance(exc, ProvenanceError) and exc.code == REPLAY_CONFLICT:
            raise
        raise ProvenanceError(REPLAY_CONFLICT, "pipeline state lineage is invalid") from exc
    if (
        data.get("content_length") != artifact.length
        or data.get("content_sha256") != artifact.sha256
        or data.get("batch_id") != artifact.batch_id
    ):
        raise ProvenanceError(REPLAY_CONFLICT, "pipeline state content or batch metadata conflicts")
    return data, artifact


def write_stage(
    stage,
    stage_num=0,
    total=0,
    percent=0,
    eta_seconds=None,
    current_book=None,
    current_task=None,
    completed_books=None,
    status="running",
    *,
    artifact_ref: ArtifactRef | None = None,
    content: bytes | None = None,
    context: ExecutionContext | None = None,
    expected_batch_id: str | None = None,
):
    context = context or get_execution_context(True)
    if artifact_ref is None or content is None:
        raise ProvenanceError("PARENT_MISSING", "pipeline state requires verified artifact lineage")
    if expected_batch_id is None:
        raise ProvenanceError("BATCH_DIGEST_MISMATCH", "pipeline state requires an explicit expected batch id")
    validate_artifact_ref(context, artifact_ref, content, expected_batch_id=expected_batch_id)
    path = _stage_path(context, create=True)
    root = execution_root(context, create=False)
    path = _validate_root_path(path, root)
    data = {
        "stage": stage,
        "stage_num": stage_num,
        "total": total,
        "percent": max(0, min(100, int(percent))),
        "eta_seconds": int(eta_seconds) if eta_seconds is not None else None,
        "current_book": current_book,
        "current_task": current_task,
        "completed_books": list(completed_books or []),
        "status": status,
        "started_at": None,
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "project_id": context.project_id,
        "namespace_digest": context.namespace_digest,
        "stage_alias": context.stage_alias,
        "root_alias": context.root_alias,
        "run_id": context.run_id,
        "profile_id": context.profile.profile_id,
        "profile_version": context.profile.profile_version,
        "profile_definition_hash": context.profile.profile_definition_hash,
        "project_revision": context.namespace.project_revision,
        "producer_version": context.producer_version,
        "batch_id": artifact_ref.batch_id,
        "lineage": artifact_lineage(artifact_ref),
        "content_length": artifact_ref.length,
        "content_sha256": artifact_ref.sha256,
    }
    with _lock:
        if path.exists():
            old, old_artifact = _read_state_record(path, context)
            if artifact_lineage(old_artifact) != artifact_lineage(artifact_ref):
                raise ProvenanceError(REPLAY_CONFLICT, "pipeline state replay conflicts with existing evidence")
            data["started_at"] = old.get("started_at") or data["updated_at"]
        else:
            data["started_at"] = data["updated_at"]
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp = _validate_root_path(tmp, root)
        if tmp.exists():
            raise ProvenanceError(REPLAY_CONFLICT, "pipeline state temporary residue is present")
        tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        _validate_root_path(tmp, root)
        _validate_root_path(path, root)
        tmp.replace(path)
        _validate_root_path(path, root)
        record_call("writer")
    return path


def mark_error(
    stage,
    error_message,
    stage_num=0,
    total=0,
    *,
    artifact_ref: ArtifactRef | None = None,
    content: bytes | None = None,
    context=None,
    expected_batch_id: str | None = None,
):
    if artifact_ref is None or content is None:
        raise ProvenanceError("PARENT_MISSING", "error state requires verified artifact lineage")
    return write_stage(
        stage=stage,
        stage_num=stage_num,
        total=total,
        status="error",
        current_task=f"error: {error_message}",
        artifact_ref=artifact_ref,
        content=content,
        context=context,
        expected_batch_id=expected_batch_id,
    )


def clear_stage(*, context: ExecutionContext | None = None):
    context = context or get_execution_context(True)
    path = _stage_path(context)
    with _lock:
        if path.exists():
            path.unlink()


def read_stage(*, context: ExecutionContext | None = None) -> dict | None:
    context = context or get_execution_context(True)
    path = _stage_path(context)
    with _lock:
        if not path.exists():
            return None
        data, _ = _read_state_record(path, context)
        return data
