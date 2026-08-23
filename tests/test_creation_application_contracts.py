"""Contract tests for application-layer creation DTOs and protocols.

Verifies that command/result DTOs are frozen, version-independent,
use domain ArtifactRef, are Python 3.10 compatible, and match the
contract defined in the B0a plan.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from pathlib import Path
import ast
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from xiaoshuo.domain.creation import SCHEMA_VERSION as DOMAIN_SCHEMA_VERSION
from xiaoshuo.domain.creation import (
    ArtifactRef,
    ChapterTaskStatus,
    RecoveryInfo,
)

from xiaoshuo.application.creation.commands import (
    APPLICATION_COMMAND_SCHEMA_VERSION,
    CreateAuthorDecisionCommand,
    CreateChapterTaskCommand,
    ConsumeAuthorDecisionCommand,
    TransitionChapterTaskCommand,
)
from xiaoshuo.application.creation.results import (
    APPLICATION_RESULT_SCHEMA_VERSION,
    AuditEventView,
    AuthorDecisionResult,
    ChapterTaskListItem,
    CreateChapterTaskResult,
    TransitionChapterTaskResult,
)
from xiaoshuo.application.creation.ports import (
    ConsumeAuthorDecisionUseCase,
    CreateAuthorDecisionUseCase,
    CreateChapterTaskUseCase,
    CreationQueryPort,
    TransitionChapterTaskUseCase,
)
from xiaoshuo.application.creation.errors import (
    ArtifactIdentityConflict,
    CreationApplicationError,
)
from xiaoshuo.application.creation.query_requests import ChapterTaskListRequest
from xiaoshuo.application.creation.repository import (
    AuditEventRepository,
    AuthorDecisionRepository,
    ChapterTaskRepository,
    CreationUnitOfWork,
    OperationLogRepository,
)
from xiaoshuo.application.creation.transition_context import TransitionOperationContext
from xiaoshuo.application.creation.decision_creation_context import (
    DecisionCreationContext,
)

HASH_A = "sha256:" + "a" * 64


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ref(artifact_id: str = "artifact-1") -> ArtifactRef:
    return ArtifactRef(artifact_id, 1, HASH_A)


def _recovery() -> RecoveryInfo:
    return RecoveryInfo(
        failed_operation_id="op-1",
        error_code="TEST_ERROR",
        retry_from_status=ChapterTaskStatus.DRAFTING,
    )


# ---------------------------------------------------------------------------
# Command DTOs
# ---------------------------------------------------------------------------

class TestCreateChapterTaskCommand:
    def test_frozen(self) -> None:
        cmd = CreateChapterTaskCommand(
            task_id="task-1",
            project_id="project-1",
            chapter_number=1,
            initial_status=ChapterTaskStatus.PLAN_PREPARING,
            creative_intent_ref=_ref("intent-ref-1"),
        )
        with pytest.raises(FrozenInstanceError):
            cmd.task_id = "other"  # type: ignore[misc]

    def test_default_schema_version(self) -> None:
        cmd = CreateChapterTaskCommand(
            task_id="task-1",
            project_id="project-1",
            chapter_number=1,
            initial_status=ChapterTaskStatus.PLAN_PREPARING,
            creative_intent_ref=_ref("intent-ref-1"),
        )
        assert cmd.command_schema_version == APPLICATION_COMMAND_SCHEMA_VERSION
        assert cmd.command_schema_version == 1

    def test_command_schema_version_independent_of_domain(self) -> None:
        assert APPLICATION_COMMAND_SCHEMA_VERSION == 1
        assert DOMAIN_SCHEMA_VERSION == 1

    def test_explicit_schema_version(self) -> None:
        cmd = CreateChapterTaskCommand(
            task_id="task-1",
            project_id="project-1",
            chapter_number=1,
            initial_status=ChapterTaskStatus.PLAN_PREPARING,
            creative_intent_ref=_ref("intent-ref-1"),
            command_schema_version=99,
        )
        assert cmd.command_schema_version == 99

    def test_field_types_and_values(self) -> None:
        ref_obj = _ref("intent-abc")
        cmd = CreateChapterTaskCommand(
            task_id="task-1",
            project_id="project-1",
            chapter_number=42,
            initial_status=ChapterTaskStatus.PLAN_APPROVAL_PENDING,
            creative_intent_ref=ref_obj,
        )
        assert cmd.task_id == "task-1"
        assert cmd.project_id == "project-1"
        assert cmd.chapter_number == 42
        assert cmd.initial_status is ChapterTaskStatus.PLAN_APPROVAL_PENDING
        assert cmd.creative_intent_ref is ref_obj

    def test_creative_intent_ref_is_artifact_ref(self) -> None:
        ref_obj = _ref("intent-x")
        cmd = CreateChapterTaskCommand(
            task_id="task-1",
            project_id="project-1",
            chapter_number=1,
            initial_status=ChapterTaskStatus.PLAN_PREPARING,
            creative_intent_ref=ref_obj,
        )
        assert isinstance(cmd.creative_intent_ref, ArtifactRef)
        assert cmd.creative_intent_ref.artifact_id == "intent-x"


class TestTransitionChapterTaskCommand:
    def test_frozen(self) -> None:
        cmd = TransitionChapterTaskCommand(
            task_id="task-1",
            target_status=ChapterTaskStatus.PLAN_APPROVAL_PENDING,
            expected_revision=0,
        )
        with pytest.raises(FrozenInstanceError):
            cmd.task_id = "other"  # type: ignore[misc]

    def test_default_schema_version(self) -> None:
        cmd = TransitionChapterTaskCommand(
            task_id="task-1",
            target_status=ChapterTaskStatus.PLAN_APPROVAL_PENDING,
            expected_revision=0,
        )
        assert cmd.command_schema_version == APPLICATION_COMMAND_SCHEMA_VERSION

    def test_with_recovery(self) -> None:
        rec = _recovery()
        cmd = TransitionChapterTaskCommand(
            task_id="task-1",
            target_status=ChapterTaskStatus.DRAFTING,
            expected_revision=3,
            recovery=rec,
        )
        assert cmd.recovery is rec
        assert cmd.recovery.retry_from_status is ChapterTaskStatus.DRAFTING

    def test_recovery_defaults_to_none(self) -> None:
        cmd = TransitionChapterTaskCommand(
            task_id="task-1",
            target_status=ChapterTaskStatus.REVIEWING,
            expected_revision=0,
        )
        assert cmd.recovery is None

    def test_field_types_and_values(self) -> None:
        cmd = TransitionChapterTaskCommand(
            task_id="task-2",
            target_status=ChapterTaskStatus.CHANGESET_APPROVAL_PENDING,
            expected_revision=7,
        )
        assert cmd.task_id == "task-2"
        assert cmd.target_status is ChapterTaskStatus.CHANGESET_APPROVAL_PENDING
        assert cmd.expected_revision == 7


# ---------------------------------------------------------------------------
# Result DTOs
# ---------------------------------------------------------------------------

class TestCreateChapterTaskResult:
    def test_frozen(self) -> None:
        result = CreateChapterTaskResult(
            task_id="task-1",
            aggregate_revision=1,
            status=ChapterTaskStatus.PLAN_PREPARING,
        )
        with pytest.raises(FrozenInstanceError):
            result.task_id = "other"  # type: ignore[misc]

    def test_default_schema_version(self) -> None:
        result = CreateChapterTaskResult(
            task_id="task-1",
            aggregate_revision=1,
            status=ChapterTaskStatus.PLAN_PREPARING,
        )
        assert result.result_schema_version == APPLICATION_RESULT_SCHEMA_VERSION
        assert result.result_schema_version == 1

    def test_result_schema_version_independent_of_domain(self) -> None:
        assert APPLICATION_RESULT_SCHEMA_VERSION == 1
        assert DOMAIN_SCHEMA_VERSION == 1

    def test_result_schema_version_independent_of_command_schema(self) -> None:
        assert APPLICATION_RESULT_SCHEMA_VERSION == 1
        assert APPLICATION_COMMAND_SCHEMA_VERSION == 1


class TestB3ReadContracts:
    def test_query_request_and_minimal_views_are_frozen(self) -> None:
        request = ChapterTaskListRequest(project_id="project-1")
        with pytest.raises(FrozenInstanceError):
            request.project_id = "other"  # type: ignore[misc]
        item = ChapterTaskListItem("task-1", "project-1", 1, 0, ChapterTaskStatus.PLAN_PREPARING, "now")
        assert not hasattr(item, "creative_intent_ref")
        assert "source_refs" not in AuditEventView.__annotations__


class TestTransitionChapterTaskResult:
    def test_frozen(self) -> None:
        result = TransitionChapterTaskResult(
            task_id="task-1",
            aggregate_revision=2,
            status=ChapterTaskStatus.DRAFTING,
        )
        with pytest.raises(FrozenInstanceError):
            result.status = ChapterTaskStatus.PLAN_PREPARING  # type: ignore[misc]

    def test_field_values(self) -> None:
        result = TransitionChapterTaskResult(
            task_id="task-x",
            aggregate_revision=5,
            status=ChapterTaskStatus.REVIEWING,
        )
        assert result.task_id == "task-x"
        assert result.aggregate_revision == 5
        assert result.status is ChapterTaskStatus.REVIEWING


# ---------------------------------------------------------------------------
# No sqlite3 / database imports in application layer
# ---------------------------------------------------------------------------

_APPLICATION_DIR = Path(__file__).resolve().parent.parent / "src" / "xiaoshuo" / "application"
_FORBIDDEN_NAMES = frozenset({"sqlite3", "SQL", "PRAGMA", "rowid", "WAL"})


def _all_source_files(root: Path) -> list[Path]:
    paths: list[Path] = []
    for entry in root.rglob("*.py"):
        if entry.is_file():
            paths.append(entry)
    return paths


class TestNoDatabaseImportsInApplication:
    @pytest.mark.parametrize("source_file", _all_source_files(_APPLICATION_DIR))
    def test_no_forbidden_imports(self, source_file: Path) -> None:
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in _FORBIDDEN_NAMES, (
                        f"{source_file.name} imports {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module is not None:
                    assert node.module.split(".")[0] not in _FORBIDDEN_NAMES, (
                        f"{source_file.name} imports from {node.module}"
                    )


# ---------------------------------------------------------------------------
# Python 3.10 compatibility — no typing.override
# ---------------------------------------------------------------------------

class TestPython310Compatibility:
    @pytest.mark.parametrize("source_file", _all_source_files(_APPLICATION_DIR))
    def test_no_override_import(self, source_file: Path) -> None:
        text = source_file.read_text(encoding="utf-8")
        assert "from typing import override" not in text, (
            f"{source_file.name} imports typing.override (Python >= 3.12)"
        )

    @pytest.mark.parametrize("source_file", _all_source_files(_APPLICATION_DIR))
    def test_no_override_decorator(self, source_file: Path) -> None:
        text = source_file.read_text(encoding="utf-8")
        assert "@override" not in text, (
            f"{source_file.name} uses @override decorator (Python >= 3.12)"
        )


# ---------------------------------------------------------------------------
# ArtifactIdentityConflict contract
# ---------------------------------------------------------------------------

class TestArtifactIdentityConflict:
    """Minimal contract test for the ArtifactIdentityConflict application error.

    Does not depend on sqlite3, SQL, WAL, HTTP, or config.
    """

    def test_is_instantiable(self) -> None:
        err = ArtifactIdentityConflict(
            "artifact 'x' declared with schema_version=1 and schema_version=2"
        )
        assert isinstance(err, ArtifactIdentityConflict)
        assert "artifact 'x'" in str(err)

    def test_is_creation_application_error(self) -> None:
        err = ArtifactIdentityConflict("mismatch")
        assert isinstance(err, CreationApplicationError)
        assert isinstance(err, Exception)

    def test_errors_module_has_no_infrastructure_imports(self) -> None:
        """Verify errors.py does not import sqlite3, SQL, WAL, HTTP, or config."""
        errors_source = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "xiaoshuo"
            / "application"
            / "creation"
            / "errors.py"
        )
        tree = ast.parse(errors_source.read_text(encoding="utf-8"), filename="errors.py")
        _FORBIDDEN_ERRORS = frozenset(
            {"sqlite3", "SQL", "WAL", "HTTP", "config", "requests", "urllib"}
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    assert top not in _FORBIDDEN_ERRORS, (
                        f"errors.py imports forbidden module: {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module is not None:
                    top = node.module.split(".")[0]
                    assert top not in _FORBIDDEN_ERRORS, (
                        f"errors.py imports from forbidden module: {node.module}"
                    )


# ---------------------------------------------------------------------------
# TransitionOperationContext contract (B2a)
# ---------------------------------------------------------------------------

class TestTransitionOperationContextContract:
    """Port signature verification: transition() must accept TransitionOperationContext."""

    def test_transition_port_accepts_context(self) -> None:
        """Verify that TransitionChapterTaskUseCase.transition has a 'context' parameter."""
        import inspect

        sig = inspect.signature(TransitionChapterTaskUseCase.transition)
        params = list(sig.parameters.keys())
        assert "command" in params
        assert "context" in params

    def test_context_is_frozen(self) -> None:
        ctx = TransitionOperationContext(idempotency_key="unique-key-1")
        with pytest.raises(FrozenInstanceError):
            ctx.idempotency_key = "other"  # type: ignore[misc]

    def test_context_rejects_empty_key(self) -> None:
        with pytest.raises(ValueError):
            TransitionOperationContext(idempotency_key="")

    def test_context_rejects_whitespace_key(self) -> None:
        with pytest.raises(ValueError):
            TransitionOperationContext(idempotency_key="   ")

    def test_context_has_no_actor_or_trace_fields(self) -> None:
        ctx = TransitionOperationContext(idempotency_key="key-1")
        assert not hasattr(ctx, "actor")
        assert not hasattr(ctx, "auth")
        assert not hasattr(ctx, "trace")
        assert not hasattr(ctx, "timestamp")
        assert not hasattr(ctx, "source_refs")


# ---------------------------------------------------------------------------
# B2b port contracts
# ---------------------------------------------------------------------------

class TestCreateAuthorDecisionUseCaseContract:
    """Port signature: create() must accept DecisionCreationContext."""

    def test_create_port_accepts_context(self) -> None:
        import inspect

        sig = inspect.signature(CreateAuthorDecisionUseCase.create)
        params = list(sig.parameters.keys())
        assert "command" in params
        assert "context" in params


class TestConsumeAuthorDecisionUseCaseContract:
    """Port signature: consume() must accept TransitionOperationContext."""

    def test_consume_port_accepts_context(self) -> None:
        import inspect

        sig = inspect.signature(ConsumeAuthorDecisionUseCase.consume)
        params = list(sig.parameters.keys())
        assert "command" in params
        assert "context" in params


class TestDecisionCreationContextContract:
    """DecisionCreationContext contract (B2b)."""

    def test_context_is_frozen(self) -> None:
        ctx = DecisionCreationContext(idempotency_key="unique-key-1")
        with pytest.raises(FrozenInstanceError):
            ctx.idempotency_key = "other"  # type: ignore[misc]

    def test_context_rejects_empty_key(self) -> None:
        with pytest.raises(ValueError):
            DecisionCreationContext(idempotency_key="")

    def test_context_has_no_actor_or_trace_fields(self) -> None:
        ctx = DecisionCreationContext(idempotency_key="key-1")
        assert not hasattr(ctx, "actor")
        assert not hasattr(ctx, "auth")
        assert not hasattr(ctx, "trace")
        assert not hasattr(ctx, "timestamp")
        assert not hasattr(ctx, "source_refs")
        assert not hasattr(ctx, "author_id")


class TestAuthorDecisionRepositoryProtocol:
    """Verify AuthorDecisionRepository has required methods."""

    def test_has_get_method(self) -> None:
        assert hasattr(AuthorDecisionRepository, "get")

    def test_has_add_method(self) -> None:
        assert hasattr(AuthorDecisionRepository, "add")

    def test_has_add_consumption_method(self) -> None:
        assert hasattr(AuthorDecisionRepository, "add_consumption")

    def test_has_get_consumption_by_decision_id(self) -> None:
        assert hasattr(
            AuthorDecisionRepository, "get_consumption_by_decision_id"
        )


class TestCreationUnitOfWorkHasDecisions:
    """T18: verify CreationUnitOfWork protocol includes decisions attribute."""

    def test_unit_of_work_has_decisions_attribute(self) -> None:
        import inspect

        # Protocol annotations are stored in __annotations__
        annotations = getattr(CreationUnitOfWork, "__annotations__", {})
        assert "decisions" in annotations
