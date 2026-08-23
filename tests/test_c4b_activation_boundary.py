"""C4B-37..40 and C4B-42: composition and protected-boundary evidence."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from xiaoshuo import PROJECT_ROOT
from xiaoshuo.application.creation.errors import ActivationInputRejected
from xiaoshuo.infrastructure.canon.c4b_bootstrap_lock import (
    BootstrapLockError,
    preflight_activation_roots,
)
from xiaoshuo.infra.config_manager import get_config


def test_c4b_37_config_roots_are_explicit_persistent_d_drive_paths() -> None:
    config = get_config()["canon_mvp"]
    payload = Path(config["payloads_dir"]).resolve()
    projection = Path(config["projection_dir"]).resolve()
    workspace = PROJECT_ROOT.resolve()
    canon = (PROJECT_ROOT / "assets" / "canon").resolve()
    assert payload.drive.upper() == "D:"
    assert projection.drive.upper() == "D:"
    assert not str(payload).lower().startswith(r"d:\tmp")
    assert not str(projection).lower().startswith(r"d:\tmp")
    assert workspace not in payload.parents and workspace not in projection.parents
    assert canon not in payload.parents and canon not in projection.parents


def test_c4b_38_application_creation_has_no_infrastructure_imports() -> None:
    root = PROJECT_ROOT / "src" / "xiaoshuo" / "application" / "creation"
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(not alias.name.startswith("xiaoshuo.infrastructure") for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("xiaoshuo.infrastructure")


def test_c4b_39_c4b_source_does_not_reference_c4a_business_writes() -> None:
    source = (PROJECT_ROOT / "src" / "xiaoshuo" / "infrastructure" / "canon" / "c4b_activation.py").read_text(encoding="utf-8")
    assert "chapter_task" not in source
    assert "canon_commit_journal" not in source
    assert "canon_commit_receipt" not in source
    assert "COMMITTED" not in source
    assert "LocalAuthorContext" not in source


def test_c4b_40_no_forbidden_transport_or_model_dependency_is_connected() -> None:
    source = (PROJECT_ROOT / "src" / "xiaoshuo" / "infrastructure" / "canon" / "c4b_activation.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = [
        node.module or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in [ast.alias(name=node.module or "", asname=None)]
    ]
    assert not any(name.startswith(("fastapi", "requests", "httpx", "torch", "transformers")) for name in imports)


@pytest.mark.parametrize(
    "payload,projection",
    [
        (r"D:\tmp\payload", r"D:\persist\projection"),
        (r"D:\persist\same", r"D:\persist\same"),
        (r"D:\persist\root", r"D:\persist\root\projection"),
    ],
)
def test_unsafe_roots_fail_before_any_write(payload: str, projection: str) -> None:
    with pytest.raises(BootstrapLockError):
        preflight_activation_roots(payload, projection, enforce_persistent_d_drive=True)


def test_c4b_42_raw_reparse_root_is_rejected_before_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import xiaoshuo.infrastructure.canon.c4b_bootstrap_lock as lock_module

    payload = tmp_path / "payload"
    projection = tmp_path / "projection"
    payload.mkdir()
    monkeypatch.setattr(lock_module, "_is_reparse", lambda path: path == payload)
    monkeypatch.setattr(
        lock_module,
        "_resolved",
        lambda _path: pytest.fail("raw root inspection must precede resolve"),
    )
    with pytest.raises(BootstrapLockError, match="reparse"):
        preflight_activation_roots(payload, projection, enforce_persistent_d_drive=False)


def test_boundary_invalid_project_input_is_application_rejected() -> None:
    with pytest.raises(ActivationInputRejected):
        from xiaoshuo.application.creation.canon_activation import CanonActivationRequest

        CanonActivationRequest("project/name", "key", "sha256:" + "a" * 64)
