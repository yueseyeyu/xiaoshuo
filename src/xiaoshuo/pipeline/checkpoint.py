#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Context-bound pipeline checkpoints.

There is intentionally no default checkpoint directory.  A checkpoint is a
write-capability and therefore requires an explicit project/profile/stage/run
context whose root is owner-derived on D drive.
"""
from __future__ import annotations

import json
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
    validate_artifact_lineage,
    validate_artifact_ref,
    _validate_root_path,
)


CHECKPOINT_DIR: Path | None = None
PIPELINE_STEPS = [
    "book_processor",
    "rhythm_analyzer",
    "rhythm_auditor",
    "genre_synthesizer",
    "score_auditor",
    "quality_gate",
    "creative_bridge",
    "writing_instructions",
]


def _checkpoint_root(context: ExecutionContext, *, create: bool = False) -> Path:
    root = execution_root(context, create=create)
    candidate = CHECKPOINT_DIR or (root / "checkpoints")
    candidate = _validate_root_path(Path(candidate), root)
    if candidate.drive.upper() != "D:":
        raise ProvenanceError("WRITE_BOUNDARY_UNCERTAIN", "checkpoint directory is not on D drive")
    return candidate


def _get_checkpoint_path(
    step_name: str,
    *,
    context: ExecutionContext | None = None,
    create: bool = False,
) -> Path:
    context = context or get_execution_context(True)
    if step_name not in PIPELINE_STEPS:
        raise ValueError(f"unknown pipeline step: {step_name}")
    # Validate the final file path before any root/directory creation.
    preflight_root = _checkpoint_root(context, create=False)
    preflight_path = _validate_root_path(
        preflight_root / f"{step_name}.json", preflight_root
    )
    if not create:
        return preflight_path
    root = _checkpoint_root(context, create=True)
    root.mkdir(parents=True, exist_ok=True)
    return _validate_root_path(root / f"{step_name}.json", root)


def _read_checkpoint_record(
    step_name: str,
    path: Path,
    context: ExecutionContext,
) -> tuple[dict[str, Any], ArtifactRef]:
    root = execution_root(context, create=False)
    path = _validate_root_path(path, root)
    try:
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf") or b"\x00" in raw:
            raise ProvenanceError(REPLAY_CONFLICT, "checkpoint contains forbidden bytes")
        text = raw.decode("utf-8")
        data = json.loads(text)
    except ProvenanceError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ProvenanceError(REPLAY_CONFLICT, "checkpoint record is corrupted") from exc
    if (
        not isinstance(data, dict)
        or data.get("step") != step_name
        or data.get("status") != "done"
        or not isinstance(data.get("timestamp"), str)
        or not data.get("timestamp")
    ):
        raise ProvenanceError(REPLAY_CONFLICT, "checkpoint record identity or status is invalid")
    try:
        artifact = validate_artifact_lineage(
            context,
            data["lineage"],
            expected_batch_id=data["lineage"]["batch_id"],
        )
    except (KeyError, TypeError, ProvenanceError) as exc:
        if isinstance(exc, ProvenanceError) and exc.code == REPLAY_CONFLICT:
            raise
        raise ProvenanceError(REPLAY_CONFLICT, "checkpoint lineage is invalid") from exc
    if (
        data.get("project_id") != context.project_id
        or data.get("content_length") != artifact.length
        or data.get("content_sha256") != artifact.sha256
    ):
        raise ProvenanceError(REPLAY_CONFLICT, "checkpoint context or content metadata conflicts")
    return data, artifact


def mark_done(
    step_name: str,
    *,
    artifact_ref: ArtifactRef | None = None,
    content: bytes | None = None,
    context: ExecutionContext | None = None,
    expected_batch_id: str | None = None,
) -> Path:
    context = context or get_execution_context(True)
    if artifact_ref is None or content is None:
        raise ProvenanceError("PARENT_MISSING", "checkpoint requires verified artifact lineage")
    if expected_batch_id is None:
        raise ProvenanceError("BATCH_DIGEST_MISMATCH", "checkpoint requires an explicit expected batch id")
    validate_artifact_ref(context, artifact_ref, content, expected_batch_id=expected_batch_id)
    path = _get_checkpoint_path(step_name, context=context, create=True)
    expected_lineage = artifact_lineage(artifact_ref)
    if path.exists():
        existing, _ = _read_checkpoint_record(step_name, path, context)
        if (
            existing["lineage"] != expected_lineage
            or existing["content_length"] != artifact_ref.length
            or existing["content_sha256"] != artifact_ref.sha256
        ):
            raise ProvenanceError(REPLAY_CONFLICT, "checkpoint replay conflicts with existing evidence")
        return path
    data = {
        "step": step_name,
        "status": "done",
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "project_id": context.project_id,
        "lineage": artifact_lineage(artifact_ref),
        "content_length": artifact_ref.length,
        "content_sha256": artifact_ref.sha256,
    }
    path = _validate_root_path(path, execution_root(context, create=False))
    if path.exists():
        existing, _ = _read_checkpoint_record(step_name, path, context)
        if existing["lineage"] != expected_lineage:
            raise ProvenanceError(REPLAY_CONFLICT, "checkpoint appeared with conflicting evidence")
        return path
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    record_call("checkpoint")
    return path


def is_done(step_name: str, *, context: ExecutionContext | None = None) -> bool:
    context = context or get_execution_context(True)
    path = _get_checkpoint_path(step_name, context=context, create=False)
    if not path.exists():
        return False
    _read_checkpoint_record(step_name, path, context)
    return True


def get_next_step(*, context: ExecutionContext | None = None) -> str | None:
    context = context or get_execution_context(True)
    for step in PIPELINE_STEPS:
        if not is_done(step, context=context):
            return step
    return None


def reset_all(*, context: ExecutionContext | None = None) -> None:
    context = context or get_execution_context(True)
    for step in PIPELINE_STEPS:
        path = _get_checkpoint_path(step, context=context, create=False)
        if path.exists():
            path.unlink()


def reset_from(step_name: str, *, context: ExecutionContext | None = None) -> None:
    context = context or get_execution_context(True)
    if step_name not in PIPELINE_STEPS:
        raise ValueError(f"unknown pipeline step: {step_name}")
    found = False
    for step in PIPELINE_STEPS:
        if step == step_name:
            found = True
        if found:
            path = _get_checkpoint_path(step, context=context, create=False)
            if path.exists():
                path.unlink()


def status(*, context: ExecutionContext | None = None) -> dict[str, bool]:
    context = context or get_execution_context(True)
    return {step: is_done(step, context=context) for step in PIPELINE_STEPS}


if __name__ == "__main__":
    raise SystemExit("explicit project/profile/stage/run context is required")
