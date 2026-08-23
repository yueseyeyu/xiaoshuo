"""LocalAuthorContext tests (B2b — T01, T02).

T01: test_local_author_context_is_stable
T02: test_caller_cannot_supply_trusted_author_identity
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from xiaoshuo.application.creation.commands import CreateAuthorDecisionCommand
from xiaoshuo.application.creation.errors import UnsupportedPersistenceBoundary
from xiaoshuo.application.creation.local_author_context import (
    LocalAuthorContextImpl,
)
from xiaoshuo.domain.creation import (
    ArtifactRef,
    DecisionType,
    SourceKind,
)

HASH_A = "sha256:" + "a" * 64


def _ref(artifact_id: str = "artifact-1") -> ArtifactRef:
    return ArtifactRef(artifact_id, 1, HASH_A)


class TestLocalAuthorContextIsStable:
    """T01: test_local_author_context_is_stable"""

    def test_identity_is_unique_and_stable(self) -> None:
        ctx = LocalAuthorContextImpl(_author_id="author-local-1")
        assert ctx.author_id == "author-local-1"
        src1 = ctx.author_source()
        src2 = ctx.author_source()
        assert src1 is not src2  # new SourceRef each call (frozen)
        assert src1 == src2  # but same values
        assert src1.kind is SourceKind.AUTHOR
        assert src1.actor_id == "author-local-1"

    def test_rejects_empty_author_id(self) -> None:
        with pytest.raises(ValueError):
            LocalAuthorContextImpl(_author_id="")

    def test_rejects_whitespace_author_id(self) -> None:
        with pytest.raises(ValueError):
            LocalAuthorContextImpl(_author_id="   ")


class TestCallerCannotSupplyTrustedAuthorIdentity:
    """T02: test_caller_cannot_supply_trusted_author_identity

    The command CreateAuthorDecisionCommand does not accept author_id,
    SourceRef, or any trusted identity field.  Verify that the command
    has no such fields and cannot be constructed with them.
    """

    def test_command_has_no_author_id_field(self) -> None:
        cmd = CreateAuthorDecisionCommand(
            task_id="task-1",
            decision_type=DecisionType.CONFIRM_PLAN,
            target_ref=_ref("plan-1"),
            based_on_task_revision=0,
        )
        assert not hasattr(cmd, "author_id")
        assert not hasattr(cmd, "source")
        assert not hasattr(cmd, "source_ref")
        assert not hasattr(cmd, "decision_id")
        assert not hasattr(cmd, "operation_id")
        assert not hasattr(cmd, "created_at")

    def test_command_cannot_accept_author_identity(self) -> None:
        """Verify that CreateAuthorDecisionCommand cannot be constructed
        with author_id, SourceRef, SYSTEM, HTTP DTO, or model output."""
        with pytest.raises(TypeError):
            CreateAuthorDecisionCommand(  # type: ignore[call-arg]
                task_id="task-1",
                decision_type=DecisionType.CONFIRM_PLAN,
                target_ref=_ref("plan-1"),
                based_on_task_revision=0,
                author_id="attacker",  # type: ignore[call-arg]
            )

    def test_frozen_command(self) -> None:
        from dataclasses import FrozenInstanceError

        cmd = CreateAuthorDecisionCommand(
            task_id="task-1",
            decision_type=DecisionType.CONFIRM_PLAN,
            target_ref=_ref("plan-1"),
            based_on_task_revision=0,
        )
        with pytest.raises(FrozenInstanceError):
            cmd.task_id = "other"  # type: ignore[misc]
