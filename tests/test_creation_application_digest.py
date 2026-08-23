"""B1 canonical request digest and application result envelope tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import ast
import json
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from xiaoshuo.application.creation.commands import CreateChapterTaskCommand
from xiaoshuo.application.creation.digest import (
    compute_envelope_hash,
    compute_request_digest,
    create_result_envelope,
    result_from_envelope,
    verify_envelope_hash,
)
from xiaoshuo.application.creation.errors import CreationApplicationError
from xiaoshuo.application.creation.operation_kind import OperationKind
from xiaoshuo.application.creation.results import CreateChapterTaskResult
from xiaoshuo.domain.creation import ArtifactRef, ChapterTaskStatus

HASH_A = "sha256:" + "a" * 64


def command() -> CreateChapterTaskCommand:
    return CreateChapterTaskCommand(
        task_id="task-1",
        project_id="project-1",
        chapter_number=1,
        initial_status=ChapterTaskStatus.PLAN_PREPARING,
        creative_intent_ref=ArtifactRef("intent-1", 1, HASH_A),
    )


def test_request_digest_is_canonical_and_stable() -> None:
    first = compute_request_digest(command(), OperationKind.CREATE_CHAPTER_TASK)
    second = compute_request_digest(command(), OperationKind.CREATE_CHAPTER_TASK)
    assert first == second
    assert first.startswith("sha256:")
    assert len(first) == 71


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("task_id", "task-2"),
        ("project_id", "project-2"),
        ("chapter_number", 2),
        ("command_schema_version", 2),
    ],
)
def test_request_digest_covers_business_inputs(field: str, value: object) -> None:
    original = command()
    changed = replace(original, **{field: value})
    assert compute_request_digest(original, OperationKind.CREATE_CHAPTER_TASK) != (
        compute_request_digest(changed, OperationKind.CREATE_CHAPTER_TASK)
    )


def test_result_envelope_is_canonical_and_roundtrips() -> None:
    result = CreateChapterTaskResult(
        task_id="task-1",
        aggregate_revision=0,
        status=ChapterTaskStatus.PLAN_PREPARING,
    )
    envelope = create_result_envelope(
        result,
        operation_kind=OperationKind.CREATE_CHAPTER_TASK,
        original_operation_id="op-1",
        audit_event_ids=("event-1",),
    )
    assert envelope == json.dumps(
        json.loads(envelope), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    payload = json.loads(envelope)
    assert payload["operation_kind"] == "CREATE_CHAPTER_TASK"
    assert payload["original_operation_id"] == "op-1"
    assert payload["audit_event_ids"] == ["event-1"]
    assert result_from_envelope(envelope) == result


def test_envelope_hash_binds_exact_original_text() -> None:
    envelope = '{"a":1}'
    digest = compute_envelope_hash(envelope)
    assert verify_envelope_hash(envelope, digest)
    assert not verify_envelope_hash('{"a":2}', digest)


def test_invalid_envelope_fails_closed() -> None:
    with pytest.raises(CreationApplicationError, match="invalid stored"):
        result_from_envelope('{"outcome":"WRONG"}')


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("result_schema_version", 2),
        ("result_schema_version", True),
        ("result_schema_version", 1.0),
        ("task_revision", "0"),
        ("task_revision", True),
        ("original_operation_id", ""),
        ("audit_event_ids", []),
    ],
)
def test_malformed_hashed_envelope_fields_fail_closed(field, value) -> None:
    result = CreateChapterTaskResult(
        task_id="task-1",
        aggregate_revision=0,
        status=ChapterTaskStatus.PLAN_PREPARING,
    )
    payload = json.loads(create_result_envelope(
        result,
        operation_kind=OperationKind.CREATE_CHAPTER_TASK,
        original_operation_id="op-1",
        audit_event_ids=("event-1",),
    ))
    payload[field] = value
    with pytest.raises(CreationApplicationError, match="invalid stored"):
        result_from_envelope(json.dumps(payload))


def test_envelope_task_identity_must_match_request() -> None:
    result = CreateChapterTaskResult(
        task_id="task-other",
        aggregate_revision=0,
        status=ChapterTaskStatus.PLAN_PREPARING,
    )
    envelope = create_result_envelope(
        result,
        operation_kind=OperationKind.CREATE_CHAPTER_TASK,
        original_operation_id="op-1",
        audit_event_ids=("event-1",),
    )
    with pytest.raises(CreationApplicationError, match="invalid stored"):
        result_from_envelope(envelope, expected_task_id="task-1")


def test_operation_kind_is_python_310_compatible_str_enum() -> None:
    assert isinstance(OperationKind.CREATE_CHAPTER_TASK, str)
    source = (
        Path(__file__).resolve().parent.parent
        / "src/xiaoshuo/application/creation/operation_kind.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "StrEnum" not in source
    assert any(isinstance(node, ast.ClassDef) and node.name == "OperationKind" for node in tree.body)
