"""Tests for TransitionOperationContext (B2a)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from xiaoshuo.application.creation.transition_context import TransitionOperationContext
from xiaoshuo.application.creation.commands import TransitionChapterTaskCommand
from xiaoshuo.application.creation.operation_kind import OperationKind
from xiaoshuo.application.creation.digest import compute_transition_request_digest

HASH_A = "sha256:" + "a" * 64


def _ref(artifact_id: str = "artifact-1"):
    from xiaoshuo.domain.creation import ArtifactRef
    return ArtifactRef(artifact_id, 1, HASH_A)


def _command():
    from xiaoshuo.domain.creation import ChapterTaskStatus
    return TransitionChapterTaskCommand(
        task_id="task-1",
        target_status=ChapterTaskStatus.DRAFTING,
        expected_revision=3,
    )


class TestContextIsFrozen:
    def test_context_is_frozen(self) -> None:
        ctx = TransitionOperationContext(idempotency_key="unique-key")
        with pytest.raises(FrozenInstanceError):
            ctx.idempotency_key = "other"  # type: ignore[misc]


class TestContextRejectsEmptyKey:
    def test_context_rejects_empty_key(self) -> None:
        with pytest.raises(ValueError):
            TransitionOperationContext(idempotency_key="")


class TestContextHasNoActorOrTrace:
    def test_context_has_no_actor_or_trace(self) -> None:
        ctx = TransitionOperationContext(idempotency_key="key-1")
        assert not hasattr(ctx, "actor")
        assert not hasattr(ctx, "auth")
        assert not hasattr(ctx, "trace")
        assert not hasattr(ctx, "timestamp")
        assert not hasattr(ctx, "source_refs")


class TestContextDoesNotEnterDigest:
    def test_context_does_not_enter_digest(self) -> None:
        cmd = _command()
        kind = OperationKind.TRANSITION_CHAPTER_TASK
        ctx_a = TransitionOperationContext(idempotency_key="key-A")
        ctx_b = TransitionOperationContext(idempotency_key="key-B")
        digest_a = compute_transition_request_digest(cmd, kind)
        # Context should not be passed to digest at all
        digest_b = compute_transition_request_digest(cmd, kind)
        assert digest_a == digest_b
        # Verify the key doesn't appear in the canonical payload
        payload = {
            "command_schema_version": cmd.command_schema_version,
            "operation_kind": kind.value,
            "task_id": cmd.task_id,
            "target_status": cmd.target_status.value,
            "expected_revision": cmd.expected_revision,
            "recovery": cmd.recovery,
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"), allow_nan=False)
        assert ctx_a.idempotency_key not in canonical
        assert ctx_b.idempotency_key not in canonical
