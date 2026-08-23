from __future__ import annotations

import ast
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from xiaoshuo.application.creation.canon_apply import ApplyCanonCommitUseCase
from xiaoshuo.application.creation.canon_activation import (
    CanonActivationRequest,
    CanonActivationUseCase,
)
from xiaoshuo.application.creation.canon_recovery import RecoverCanonCommitUseCase
from xiaoshuo.application.creation.errors import CanonResourceBoundaryError
from xiaoshuo.application.creation.ports import CanonActivationResult
from xiaoshuo.application.creation.operation_kind import OperationKind


def test_c4b_13_creation_application_has_no_infrastructure_imports() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "xiaoshuo" / "application" / "creation"
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(not alias.name.startswith("xiaoshuo.infrastructure") for alias in node.names), path
            elif isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("xiaoshuo.infrastructure"), path


def test_c4b_14_old_apply_and_recovery_fail_before_dependencies_are_touched() -> None:
    class Bomb:
        def __call__(self):
            raise AssertionError("dependency touched")

    with pytest.raises(CanonResourceBoundaryError):
        ApplyCanonCommitUseCase(Bomb(), Bomb(), Bomb(), Bomb()).apply(object(), object())
    with pytest.raises(CanonResourceBoundaryError):
        RecoverCanonCommitUseCase(Bomb(), Bomb(), Bomb()).recover(object(), object())


def test_c4b_15_activation_application_port_has_no_infrastructure_dependency() -> None:
    class Port:
        def activate(self, request):
            return CanonActivationResult("REPLAY", "attempt", request.project_id, "version", "{}")

    request = CanonActivationRequest("project", "attempt", "sha256:" + "a" * 64)
    result = CanonActivationUseCase(Port()).activate(request)
    assert result.status == "REPLAY"


def test_c5g0_22_only_the_two_g0b_operation_kinds_are_new() -> None:
    assert OperationKind.SUBMIT_AUTHORING_ARTIFACT.value == "SUBMIT_AUTHORING_ARTIFACT"
    assert OperationKind.SUBMIT_DRAFT_FOR_REVIEW.value == "SUBMIT_DRAFT_FOR_REVIEW"
    assert len(tuple(OperationKind)) == 10


def test_c5g0_30_application_g0b_files_have_no_infrastructure_or_filesystem_boundary() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "xiaoshuo" / "application" / "creation"
    for name in ("authoring_artifact.py", "authoring_artifact_context.py", "draft_review_submission.py"):
        source = (root / name).read_text(encoding="utf-8")
        assert "xiaoshuo.infrastructure" not in source
        assert "config.yaml" not in source
        assert "pathlib" not in source
        assert "os.path" not in source
