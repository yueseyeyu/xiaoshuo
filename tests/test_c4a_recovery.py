"""C4A-35..39 and C4A-49..51: durable Recovery boundaries."""

from __future__ import annotations

from pathlib import Path

import pytest

from xiaoshuo.application.creation.canon_recovery import CanonRecoveryCommand
from xiaoshuo.application.creation.canon_recovery_context import CanonRecoveryDeliveryContext
from xiaoshuo.application.creation.canon_apply import compute_canon_apply_request_digest
from xiaoshuo.application.creation.errors import CanonApplyRecoveryRequired
from xiaoshuo.domain.creation import ChapterTaskStatus
from xiaoshuo.infrastructure.canon.c4a_apply import C4aApplyService
from xiaoshuo.infrastructure.canon.c4a_recovery import C4aRecoveryService
from xiaoshuo.infrastructure.canon.c4a_projection_writer import (
    C4aProjectionIdentity,
    C4aProjectionWriter,
    C4aProjectionWriterError,
)
from xiaoshuo.infrastructure.persistence.sqlite.c4a_apply_repository import SqliteC4aApplyRepository

from test_c4a_apply import _case, _command, _context, _digest, _service


def _recovery_command() -> CanonRecoveryCommand:
    return CanonRecoveryCommand("task", "journal", 5, apply_key="apply-key")


def _recovery_context() -> CanonRecoveryDeliveryContext:
    return CanonRecoveryDeliveryContext("apply-key")


def _broken_completion(case, operator_identity: str = "operator"):
    class BrokenRepository(SqliteC4aApplyRepository):
        def complete(self, *args, **kwargs):
            raise RuntimeError("Tx B interrupted")

    with pytest.raises(CanonApplyRecoveryRequired):
        C4aApplyService(
            case["conn"], operator_identity=operator_identity, projection_root=case["root"],
            payload_store=case["payload"], repository=BrokenRepository(case["conn"]),
            activation_reader=case["reader"], enforce_persistent_d_drive=False,
        ).apply(_command(), _context())
    case["repo"] = SqliteC4aApplyRepository(case["conn"])


def _recover(case):
    return C4aRecoveryService(
        case["conn"], projection_root=case["root"], payload_store=case["payload"],
        repository=case["repo"], activation_reader=case["reader"],
        enforce_persistent_d_drive=False,
    ).recover(_recovery_command(), _recovery_context())


def test_recovery_reads_only_durable_apply_facts(tmp_path: Path) -> None:
    case = _case(tmp_path)
    with pytest.raises(CanonApplyRecoveryRequired):
        _recover(case)
    assert case["conn"].execute("SELECT COUNT(*) FROM canon_commit_receipt").fetchone()[0] == 0


def test_recovery_with_verified_marker_completes_db_without_file_write(tmp_path: Path) -> None:
    case = _case(tmp_path)
    _broken_completion(case)
    before = {path.name: path.read_bytes() for path in case["root"].iterdir() if path.is_file()}
    result = _recover(case)
    after = {path.name: path.read_bytes() for path in case["root"].iterdir() if path.is_file()}
    assert result.status is ChapterTaskStatus.COMPLETED
    assert before == after
    observations = case["conn"].execute(
        "SELECT observed_pointer_content_hash, observed_marker_content_hash "
        "FROM canon_apply_event WHERE phase IN ('PROJECTION_COMMITTED','RECEIPT_PAYLOAD_READY','COMPLETED')"
    ).fetchall()
    target_hashes = (
        _digest((case["root"] / "current.pointer").read_bytes()),
        _digest((case["root"] / "activation.marker").read_bytes()),
    )
    assert observations and all(tuple(row) == target_hashes for row in observations)
    recovery_evidence = case["repo"].verify_recovery_completed_graph(
        project_id="project",
        task_id="task",
        apply_key="apply-key",
        request_digest=compute_canon_apply_request_digest(_command()),
    )
    assert recovery_evidence.read_only is True
    assert recovery_evidence.recovery_event_id.endswith(":recovery-required")
    assert recovery_evidence.completed.operator_identity == "operator"


def test_recovery_marker_is_not_a_success_phase_for_strict_graph_verifier(tmp_path: Path) -> None:
    case = _case(tmp_path)
    _broken_completion(case)
    with pytest.raises(CanonApplyRecoveryRequired):
        case["repo"].verify_completed_graph(
            project_id="project",
            task_id="task",
            apply_key="apply-key",
            request_digest=compute_canon_apply_request_digest(_command()),
        )


def test_recovery_pointer_without_marker_never_autofixes_marker(tmp_path: Path) -> None:
    case = _case(tmp_path)

    class BrokenWriter(C4aProjectionWriter):
        def write_marker(self, identity):
            raise C4aProjectionWriterError("marker intentionally missing")

    with pytest.raises(CanonApplyRecoveryRequired):
        _service(case, writer_factory=BrokenWriter).apply(_command(), _context())
    marker = (case["root"] / "activation.marker").read_bytes()
    with pytest.raises(CanonApplyRecoveryRequired):
        _recover(case)
    assert (case["root"] / "activation.marker").read_bytes() == marker


def test_recovery_unknown_version_project_or_hash_requires_manual_boundary(tmp_path: Path) -> None:
    case = _case(tmp_path)
    _broken_completion(case)

    class WrongReader:
        def read_for_project(self, _project):
            raise RuntimeError("unknown version")

    with pytest.raises(CanonApplyRecoveryRequired):
        C4aRecoveryService(
            case["conn"], projection_root=case["root"], payload_store=case["payload"],
            repository=case["repo"], activation_reader=WrongReader(), enforce_persistent_d_drive=False,
        ).recover(_recovery_command(), _recovery_context())
    assert case["conn"].execute("SELECT status FROM chapter_task").fetchone()[0] == "RECOVERY_REQUIRED"


def test_recovery_repeat_is_idempotent_and_does_not_forge_receipt(tmp_path: Path) -> None:
    case = _case(tmp_path)
    _broken_completion(case)
    first = _recover(case)
    receipts = case["conn"].execute("SELECT COUNT(*) FROM canon_commit_receipt").fetchone()[0]
    second = _recover(case)
    assert first.aggregate_revision == second.aggregate_revision
    assert case["conn"].execute("SELECT COUNT(*) FROM canon_commit_receipt").fetchone()[0] == receipts == 1

    tampered_root = tmp_path / "completed-tampered"
    tampered_root.mkdir()
    tampered = _case(tampered_root)
    _broken_completion(tampered)
    _recover(tampered)
    base_identity = C4aProjectionWriter.pointer_bytes(
        C4aProjectionIdentity(
            "project", "base-v1", tampered["base_ref"], tampered["base"].manifest_hash,
            tampered["base"].world_hash,
        )
    )
    base_marker = C4aProjectionWriter.marker_bytes(
        C4aProjectionIdentity(
            "project", "base-v1", tampered["base_ref"], tampered["base"].manifest_hash,
            tampered["base"].world_hash,
        ),
        base_identity,
    )
    (tampered["root"] / "current.pointer").write_bytes(base_identity)
    (tampered["root"] / "activation.marker").write_bytes(base_marker)
    with pytest.raises(CanonApplyRecoveryRequired):
        _recover(tampered)
    assert tampered["conn"].execute("SELECT status FROM chapter_task").fetchone()[0] == "COMPLETED"
    assert tampered["conn"].execute("SELECT COUNT(*) FROM canon_apply_event").fetchone()[0] == 9


def test_recovery_event_task_metadata_and_audit_are_one_transaction(tmp_path: Path) -> None:
    case = _case(tmp_path)
    _broken_completion(case)
    recovery = case["conn"].execute("SELECT status, recovery_error_code FROM chapter_task").fetchone()
    event = case["conn"].execute("SELECT phase, error_code FROM canon_apply_event WHERE phase='RECOVERY_REQUIRED'").fetchone()
    audit = case["conn"].execute("SELECT event_type FROM creation_audit_event WHERE event_type='CANON_APPLY_RECOVERY_REQUIRED'").fetchone()
    assert recovery["status"] == "RECOVERY_REQUIRED" and recovery["recovery_error_code"]
    assert event["phase"] == "RECOVERY_REQUIRED" and audit is not None


def test_only_verified_receipt_payload_ready_allows_db_only_completion(tmp_path: Path) -> None:
    case = _case(tmp_path)
    _broken_completion(case)
    recovery_state = case["conn"].execute(
        "SELECT status FROM chapter_task WHERE task_id='task'"
    ).fetchone()
    recovery_event = case["conn"].execute(
        "SELECT phase FROM canon_apply_event WHERE phase='RECOVERY_REQUIRED'"
    ).fetchone()
    assert recovery_state["status"] == "RECOVERY_REQUIRED"
    assert recovery_event["phase"] == "RECOVERY_REQUIRED"
    before = case["conn"].execute("SELECT COUNT(*) FROM canon_apply_event").fetchone()[0]
    result = _recover(case)
    assert result.status is ChapterTaskStatus.COMPLETED
    assert case["conn"].execute("SELECT COUNT(*) FROM canon_apply_event").fetchone()[0] == before + 1

    committing_root = tmp_path / "committing-only"
    committing_root.mkdir()
    committing_case = _case(committing_root)
    _broken_completion(committing_case)
    committing_case["conn"].execute(
        "UPDATE chapter_task SET status='COMMITTING', last_stable_status='COMMITTING', "
        "recovery_failed_operation_id=NULL, recovery_error_code=NULL, "
        "recovery_retry_from_status=NULL WHERE task_id='task'"
    )
    committing_case["conn"].commit()
    with pytest.raises(CanonApplyRecoveryRequired, match="RECOVERY_REQUIRED"):
        _recover(committing_case)
    assert committing_case["conn"].execute(
        "SELECT COUNT(*) FROM canon_commit_receipt"
    ).fetchone()[0] == 0

    observation_root = tmp_path / "observation-mismatch"
    observation_root.mkdir()
    observation_case = _case(observation_root)
    _broken_completion(observation_case)
    base_identity = C4aProjectionWriter.pointer_bytes(
        C4aProjectionIdentity(
            "project", "base-v1", observation_case["base_ref"], observation_case["base"].manifest_hash,
            observation_case["base"].world_hash,
        )
    )
    base_marker = C4aProjectionWriter.marker_bytes(
        C4aProjectionIdentity(
            "project", "base-v1", observation_case["base_ref"], observation_case["base"].manifest_hash,
            observation_case["base"].world_hash,
        ),
        base_identity,
    )
    (observation_case["root"] / "current.pointer").write_bytes(base_identity)
    (observation_case["root"] / "activation.marker").write_bytes(base_marker)
    with pytest.raises(CanonApplyRecoveryRequired):
        _recover(observation_case)
    assert observation_case["conn"].execute("SELECT status FROM chapter_task").fetchone()[0] == "RECOVERY_REQUIRED"
    assert observation_case["conn"].execute("SELECT COUNT(*) FROM canon_commit_receipt").fetchone()[0] == 0


def test_marker_present_without_verified_receipt_payload_requires_manual_boundary(tmp_path: Path) -> None:
    case = _case(tmp_path)
    repo = case["repo"]
    # A PREPARED attempt plus a perfectly valid marker is still insufficient.
    from test_c4a_v006_migration import _pending

    _pending(case)
    with pytest.raises(CanonApplyRecoveryRequired):
        _recover(case)
    assert case["conn"].execute("SELECT COUNT(*) FROM canon_commit_receipt").fetchone()[0] == 0
