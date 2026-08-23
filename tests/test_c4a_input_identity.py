"""C4A-01..08: trusted v2 identity and pre-projection rejection."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from xiaoshuo.application.creation.canon_apply import CanonApplyCommand
from xiaoshuo.application.creation.canon_apply_context import CanonApplyDeliveryContext
from xiaoshuo.application.creation.errors import (
    CanonApplyInputRejected,
    LegacyJournalUnbound,
)
from xiaoshuo.domain.creation import ArtifactRef, ChapterTaskStatus
from xiaoshuo.infrastructure.canon.c4a_apply import C4aApplyService
from xiaoshuo.infrastructure.canon.projection_activation import ActivationIdentity

from test_c4a_apply import _case, _context, _service, _command


def test_apply_rejects_v1_proposal_before_projection_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _case(tmp_path)
    journal = case["repo"].get_journal("journal")
    monkeypatch.setattr(case["repo"], "get_journal", lambda _journal: replace(journal, base_bundle_ref=None, base_bundle_content_hash=None))
    with pytest.raises(CanonApplyInputRejected):
        _service(case).apply(_command(), _context())
    assert case["reader"].read_calls == 0


def test_apply_rejects_legacy_journal_before_projection_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _case(tmp_path)

    def legacy(_journal):
        raise LegacyJournalUnbound("legacy journal")

    monkeypatch.setattr(case["repo"], "get_journal", legacy)
    with pytest.raises(LegacyJournalUnbound):
        _service(case).apply(_command(), _context())
    assert case["reader"].read_calls == 0


def test_apply_rejects_non_committing_task_before_projection_read(tmp_path: Path) -> None:
    case = _case(tmp_path)
    case["conn"].execute("UPDATE chapter_task SET status='CHANGESET_APPROVAL_PENDING', last_stable_status='CHANGESET_APPROVAL_PENDING' WHERE task_id='task'")
    case["conn"].commit()
    with pytest.raises(CanonApplyInputRejected):
        _service(case).apply(_command(), _context())
    assert case["reader"].read_calls == 0


def test_apply_requires_persisted_v2_complete_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _case(tmp_path)
    journal = case["repo"].get_journal("journal")
    monkeypatch.setattr(case["repo"], "get_journal", lambda _journal: replace(journal, target_world_hash=None))
    with pytest.raises(CanonApplyInputRejected):
        _service(case).apply(_command(), _context())
    assert case["reader"].read_calls == 0


def test_apply_uses_trusted_journal_and_reader_identity_not_request_hashes(tmp_path: Path) -> None:
    case = _case(tmp_path)
    result = _service(case).apply(_command(), _context())
    assert result.journal_id == "journal"
    assert case["conn"].execute("SELECT COUNT(*) FROM canon_apply_attempt").fetchone()[0] == 1


def test_apply_rejects_project_task_journal_bundle_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _case(tmp_path)
    journal = case["repo"].get_journal("journal")
    monkeypatch.setattr(case["repo"], "get_journal", lambda _journal: replace(journal, task_id="other-task"))
    with pytest.raises(CanonApplyInputRejected):
        _service(case).apply(_command(), _context())
    assert case["reader"].read_calls == 0


def test_apply_rejects_base_or_target_artifact_ref_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _case(tmp_path)
    journal = case["repo"].get_journal("journal")
    wrong = ArtifactRef("wrong-target", 1, case["target"].content_hash())
    monkeypatch.setattr(case["repo"], "get_journal", lambda _journal: replace(journal, target_bundle_ref=wrong))
    with pytest.raises(CanonApplyInputRejected):
        _service(case).apply(_command(), _context())
    assert case["conn"].execute("SELECT COUNT(*) FROM canon_apply_attempt").fetchone()[0] == 0


def test_apply_rejects_current_base_activation_mismatch_before_lock_or_write(tmp_path: Path) -> None:
    case = _case(tmp_path)
    target = case["target"]
    wrong = ActivationIdentity(
        "project", "other-v1", case["target_ref"].schema_version,
        case["target_ref"].artifact_id, case["target_ref"].content_hash,
        target.manifest_hash, target.world_hash,
    )

    class WrongReader:
        read_calls = 0

        def read_for_project(self, _project_id):
            self.read_calls += 1
            return wrong

    reader = WrongReader()
    with pytest.raises(CanonApplyInputRejected):
        C4aApplyService(
            case["conn"], operator_identity="operator", projection_root=case["root"],
            payload_store=case["payload"], repository=case["repo"], activation_reader=reader,
            enforce_persistent_d_drive=False,
        ).apply(_command(), _context())
    assert case["conn"].execute("SELECT COUNT(*) FROM canon_apply_attempt").fetchone()[0] == 0
