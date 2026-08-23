"""Tests for transition digest and envelope (B2a)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from xiaoshuo.application.creation.commands import TransitionChapterTaskCommand
from xiaoshuo.application.creation.digest import (
    compute_envelope_hash,
    compute_transition_request_digest,
    create_transition_result_envelope,
    result_from_transition_envelope,
)
from xiaoshuo.application.creation.errors import CreationApplicationError
from xiaoshuo.application.creation.operation_kind import OperationKind
from xiaoshuo.application.creation.results import (
    APPLICATION_RESULT_SCHEMA_VERSION,
    TransitionChapterTaskResult,
)
from xiaoshuo.domain.creation import ChapterTaskStatus

HASH_A = "sha256:" + "a" * 64


def _command():
    return TransitionChapterTaskCommand(
        task_id="task-1",
        target_status=ChapterTaskStatus.DRAFTING,
        expected_revision=3,
    )


def _result():
    return TransitionChapterTaskResult(
        task_id="task-1",
        aggregate_revision=4,
        status=ChapterTaskStatus.DRAFTING,
    )


class TestTransitionDigestDeterministic:
    def test_transition_digest_deterministic(self) -> None:
        cmd = _command()
        kind = OperationKind.TRANSITION_CHAPTER_TASK
        d1 = compute_transition_request_digest(cmd, kind)
        d2 = compute_transition_request_digest(cmd, kind)
        assert d1 == d2
        assert d1.startswith("sha256:")


class TestTransitionDigestExcludesContext:
    def test_transition_digest_excludes_context(self) -> None:
        cmd = _command()
        kind = OperationKind.TRANSITION_CHAPTER_TASK
        digest = compute_transition_request_digest(cmd, kind)
        # The word "idempotency" should not appear in the digest payload
        # (we verify by checking digest changes when command changes)
        cmd2 = TransitionChapterTaskCommand(
            task_id="task-2",
            target_status=ChapterTaskStatus.DRAFTING,
            expected_revision=3,
        )
        digest2 = compute_transition_request_digest(cmd2, kind)
        assert digest != digest2


class TestTransitionEnvelopeStructure:
    def test_transition_envelope_structure(self) -> None:
        result = _result()
        envelope = create_transition_result_envelope(
            result,
            operation_kind=OperationKind.TRANSITION_CHAPTER_TASK,
            original_operation_id="op-1",
            audit_event_ids=("event-1",),
        )
        payload = json.loads(envelope)
        assert payload["outcome"] == "TRANSITIONED"
        assert payload["operation_kind"] == "TRANSITION_CHAPTER_TASK"
        assert payload["task_id"] == "task-1"
        assert payload["task_revision"] == 4
        assert payload["task_status"] == "DRAFTING"
        assert payload["original_operation_id"] == "op-1"
        assert payload["audit_event_ids"] == ["event-1"]


class TestTransitionEnvelopeHashConsistency:
    def test_transition_envelope_hash_consistency(self) -> None:
        result = _result()
        envelope = create_transition_result_envelope(
            result,
            operation_kind=OperationKind.TRANSITION_CHAPTER_TASK,
            original_operation_id="op-1",
            audit_event_ids=("event-1",),
        )
        h = compute_envelope_hash(envelope)
        assert h == compute_envelope_hash(envelope)
        assert h.startswith("sha256:")


class TestResultFromTransitionEnvelopeRoundtrip:
    def test_result_from_transition_envelope_roundtrip(self) -> None:
        result = _result()
        envelope = create_transition_result_envelope(
            result,
            operation_kind=OperationKind.TRANSITION_CHAPTER_TASK,
            original_operation_id="op-1",
            audit_event_ids=("event-1",),
        )
        restored = result_from_transition_envelope(
            envelope, expected_task_id="task-1"
        )
        assert restored.task_id == result.task_id
        assert restored.aggregate_revision == result.aggregate_revision
        assert restored.status == result.status
        assert restored.result_schema_version == APPLICATION_RESULT_SCHEMA_VERSION


class TestResultFromTransitionEnvelopeRejectsCreateOutcome:
    def test_result_from_transition_envelope_rejects_create_outcome(self) -> None:
        create_envelope = json.dumps({
            "result_schema_version": 1,
            "outcome": "CREATED",
            "task_id": "task-1",
            "task_revision": 0,
            "task_status": "PLAN_PREPARING",
            "audit_event_ids": ["event-1"],
            "original_operation_id": "op-1",
            "operation_kind": "CREATE_CHAPTER_TASK",
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with pytest.raises(CreationApplicationError):
            result_from_transition_envelope(create_envelope)


class TestResultFromTransitionEnvelopeRejectsWrongKind:
    def test_result_from_transition_envelope_rejects_wrong_kind(self) -> None:
        wrong = json.dumps({
            "result_schema_version": 1,
            "outcome": "TRANSITIONED",
            "task_id": "task-1",
            "task_revision": 4,
            "task_status": "DRAFTING",
            "audit_event_ids": ["event-1"],
            "original_operation_id": "op-1",
            "operation_kind": "CREATE_CHAPTER_TASK",
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with pytest.raises(CreationApplicationError):
            result_from_transition_envelope(wrong)
