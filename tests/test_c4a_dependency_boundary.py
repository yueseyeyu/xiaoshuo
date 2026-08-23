"""C4A-40..43: application/infrastructure and completion boundaries."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from xiaoshuo.application.creation.errors import (
    CanonApplyConflict,
    CanonApplyInputRejected,
    CanonApplyRecoveryRequired,
    CanonApplyCommittedLeaseReleaseUncertain,
    CanonCompletionConflict,
    CanonApplyInputRejected,
    CreationApplicationError,
)
from xiaoshuo.infrastructure.canon.c4a_apply import C4aApplyService
from xiaoshuo.infrastructure.canon import c4a_apply as c4a_apply_module
from xiaoshuo.infrastructure.canon import c4a_recovery as c4a_recovery_module
from xiaoshuo.infrastructure.canon import canon_mvp_c4_composition as c4_composition_module
from xiaoshuo.infrastructure.canon.c4a_recovery import C4aRecoveryService
from xiaoshuo.infrastructure.canon.canon_mvp_c4_composition import (
    CanonMvpC4Binding,
    CanonMvpC4Composition,
)
from xiaoshuo.infrastructure.persistence.sqlite.c4a_apply_repository import SqliteC4aApplyRepository
from xiaoshuo.infrastructure.persistence.sqlite.repository import SqliteChapterTaskRepository
from xiaoshuo.infrastructure.persistence.sqlite.settings import SQLitePersistenceSettings
from xiaoshuo.infrastructure.persistence.sqlite.uow import SqliteC4aCompletionUnitOfWork

from test_c4a_apply import _case


def test_application_modules_have_no_infrastructure_imports() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "xiaoshuo" / "application" / "creation"
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(not alias.name.startswith("xiaoshuo.infrastructure") for alias in node.names), path
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("xiaoshuo.infrastructure"), path


def test_generic_task_repository_cannot_complete_canon_task(tmp_path: Path) -> None:
    case = _case(tmp_path)
    generic = SqliteChapterTaskRepository(case["conn"])
    assert not hasattr(generic, "complete")
    assert not hasattr(generic, "mark_recovery")


def test_c4a_uses_specialized_unit_of_work_for_completion(tmp_path: Path) -> None:
    case = _case(tmp_path)
    specialized = SqliteC4aApplyRepository(case["conn"])
    assert callable(getattr(specialized, "complete"))
    assert callable(getattr(specialized, "mark_recovery"))
    assert not callable(getattr(SqliteChapterTaskRepository, "complete", None))

    injected_apply = {
        "repository": object(),
        "payload_store": object(),
        "activation_reader": object(),
        "lock_factory": lambda *_args, **_kwargs: object(),
        "writer_factory": lambda *_args, **_kwargs: object(),
    }
    before_files = {
        path.name: path.read_bytes()
        for path in case["root"].iterdir()
        if path.is_file()
    }
    for name, value in injected_apply.items():
        with pytest.raises(CanonApplyInputRejected, match="composition-root"):
            C4aApplyService(
                case["conn"],
                operator_identity="operator",
                **{name: value},
                enforce_persistent_d_drive=True,
            )
    for name in ("repository", "payload_store", "activation_reader"):
        with pytest.raises(CanonApplyInputRejected, match="composition-root"):
            C4aRecoveryService(
                case["conn"],
                **{name: object()},
                enforce_persistent_d_drive=True,
            )
    assert {
        path.name: path.read_bytes()
        for path in case["root"].iterdir()
        if path.is_file()
    } == before_files
    assert case["conn"].execute("SELECT COUNT(*) FROM canon_apply_attempt").fetchone()[0] == 0


def test_persistent_c4a_rejects_non_config_operator_before_adapters(tmp_path: Path) -> None:
    case = _case(tmp_path)
    with pytest.raises(CanonApplyInputRejected, match="local-author"):
        C4aApplyService(
            case["conn"],
            operator_identity="wrong-operator",
            enforce_persistent_d_drive=True,
        )


def test_c4_has_independent_composition_and_completion_uow(tmp_path: Path) -> None:
    case = _case(tmp_path)
    uow = SqliteC4aCompletionUnitOfWork(case["conn"])
    assert uow.repository is uow.c4a
    assert not hasattr(uow, "canon")
    composition = CanonMvpC4Composition(
        CanonMvpC4Binding(
            settings=SQLitePersistenceSettings(tmp_path / "c4.db", 5000, tmp_path / "backups"),
            payloads_dir=tmp_path / "payloads",
            projection_dir=case["root"],
            root=tmp_path,
            operator_identity="local-author",
        )
    )
    assert composition.binding.operator_identity == "local-author"
    uow.close()


def test_composition_scope_binds_payload_store_to_binding_path(tmp_path: Path, monkeypatch) -> None:
    case = _case(tmp_path)
    seen: dict[str, Path] = {}

    class BoundPayloadStore:
        def __init__(self, root):
            seen["root"] = Path(root)
            self.delegate = case["payload"]

        def put(self, data: bytes) -> str:
            return self.delegate.put(data)

        def read(self, digest: str) -> bytes:
            return self.delegate.read(digest)

    monkeypatch.setattr(c4_composition_module, "get_connection", lambda _settings: case["conn"])
    monkeypatch.setattr(c4_composition_module, "ImmutablePayloadStore", BoundPayloadStore)
    monkeypatch.setattr(
        c4_composition_module,
        "ProjectionActivationReader",
        lambda _root, artifact_ref_resolver: case["reader"],
    )
    monkeypatch.setattr(c4a_apply_module, "_configured_projection_root", lambda: case["root"])
    monkeypatch.setattr(c4a_recovery_module, "_configured_projection_root", lambda: case["root"])
    monkeypatch.setattr(c4a_apply_module, "_configured_operator_identity", lambda: "local-author")
    binding_payloads = tmp_path / "bound-payloads"
    scope = c4_composition_module.CanonMvpC4ApplicationScope(
        CanonMvpC4Binding(
            settings=SQLitePersistenceSettings(tmp_path / "c4.db", 5000, tmp_path / "backups"),
            payloads_dir=binding_payloads,
            projection_dir=case["root"],
            root=tmp_path,
            operator_identity="local-author",
        )
    )
    assert seen["root"] == binding_payloads
    scope.close()


def _composition_scope_for_graph(case):
    scope = object.__new__(c4_composition_module.CanonMvpC4ApplicationScope)
    scope.binding = type("Binding", (), {"operator_identity": "local-author"})()
    scope.uow = type("Uow", (), {"repository": case["repo"]})()
    scope.payload_store = case["payload"]
    scope._recovery = C4aRecoveryService(
        case["conn"],
        projection_root=case["root"],
        payload_store=case["payload"],
        repository=case["repo"],
        activation_reader=case["reader"],
        enforce_persistent_d_drive=False,
    )
    return scope


def test_composition_completed_graph_rejects_wrong_operator(
    tmp_path: Path,
) -> None:
    from xiaoshuo.application.creation.canon_apply import compute_canon_apply_request_digest
    from test_c4a_apply import _command, _context, _service

    case = _case(tmp_path)
    _service(case, operator_identity="wrong-operator").apply(_command(), _context())
    scope = _composition_scope_for_graph(case)
    with pytest.raises(CanonApplyRecoveryRequired, match="local-author"):
        scope.verify_completed_graph(
            project_id="project",
            task_id="task",
            apply_key="apply-key",
            request_digest=compute_canon_apply_request_digest(_command()),
        )


def test_composition_operator_identity_empty_or_missing_is_fail_closed() -> None:
    scope = object.__new__(c4_composition_module.CanonMvpC4ApplicationScope)
    scope.binding = type("Binding", (), {"operator_identity": "local-author"})()
    for value in ("", None):
        with pytest.raises(CanonApplyRecoveryRequired, match="local-author"):
            scope._verify_operator_identity(value, value)


def test_composition_recovery_graph_requires_config_bound_operator(tmp_path: Path) -> None:
    from xiaoshuo.application.creation.canon_apply import compute_canon_apply_request_digest
    from test_c4a_apply import _command
    from test_c4a_recovery import _broken_completion, _recover

    case = _case(tmp_path)
    _broken_completion(case)
    _recover(case)
    scope = _composition_scope_for_graph(case)
    with pytest.raises(CanonApplyRecoveryRequired, match="local-author"):
        scope.verify_recovery_graph(
            project_id="project",
            task_id="task",
            apply_key="apply-key",
            request_digest=compute_canon_apply_request_digest(_command()),
        )


def test_composition_recovery_graph_accepts_config_bound_operator(tmp_path: Path) -> None:
    from xiaoshuo.application.creation.canon_apply import compute_canon_apply_request_digest
    from test_c4a_apply import _command
    from test_c4a_recovery import _broken_completion, _recover

    case = _case(tmp_path)
    _broken_completion(case, operator_identity="local-author")
    _recover(case)
    scope = _composition_scope_for_graph(case)
    evidence = scope.verify_recovery_graph(
        project_id="project",
        task_id="task",
        apply_key="apply-key",
        request_digest=compute_canon_apply_request_digest(_command()),
    )
    assert evidence.completed.operator_identity == "local-author"


def test_c4a_stable_errors_inherit_creation_application_error() -> None:
    for error in (
        CanonApplyConflict,
        CanonApplyInputRejected,
        CanonApplyRecoveryRequired,
        CanonApplyCommittedLeaseReleaseUncertain,
        CanonCompletionConflict,
    ):
        assert issubclass(error, CreationApplicationError)
