from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from xiaoshuo.domain.creation.hashing import (
    InvalidContentHash,
    InvalidDomainValue,
    compute_content_hash,
)
from xiaoshuo.domain.creation.models import (
    SCHEMA_VERSION,
    ArtifactRef,
    AuditEvent,
    AuthorDecision,
    ChapterBeat,
    ChapterPlan,
    ChapterTask,
    ChapterTaskStatus,
    CreativeIntent,
    DecisionOutcome,
    DecisionType,
    DraftKind,
    DraftRevision,
    RecoveryInfo,
    ReviewFinding,
    ReviewReport,
    ReviewSeverity,
    ReviewVerdict,
    SourceKind,
    SourceRef,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def ref(artifact_id: str = "artifact-1", content_hash: str = HASH_A) -> ArtifactRef:
    return ArtifactRef(artifact_id, SCHEMA_VERSION, content_hash)


def author_source(author_id: str = "author-1") -> SourceRef:
    return SourceRef(SourceKind.AUTHOR, actor_id=author_id)


def model_source() -> SourceRef:
    return SourceRef(SourceKind.MODEL, model_run_id="run-1")


def creative_intent(**overrides: object) -> CreativeIntent:
    values: dict[str, object] = {
        "intent_id": "intent-1",
        "schema_version": SCHEMA_VERSION,
        "task_id": "task-1",
        "objective": "建立本章冲突",
        "required_elements": ("冲突",),
        "constraints": ("保持视角",),
        "source": author_source(),
        "created_at": NOW,
    }
    values.update(overrides)
    payload = {key: value for key, value in values.items() if key != "created_at"}
    values["content_hash"] = compute_content_hash(payload)
    return CreativeIntent(**values)  # type: ignore[arg-type]


def chapter_plan(**overrides: object) -> ChapterPlan:
    values: dict[str, object] = {
        "plan_id": "plan-1",
        "schema_version": SCHEMA_VERSION,
        "revision_number": 1,
        "task_id": "task-1",
        "creative_intent_ref": ref("intent-1"),
        "title": "第一章",
        "chapter_goal": "迫使主角作出选择",
        "beats": (ChapterBeat(1, "危机出现"), ChapterBeat(2, "主角选择")),
        "ending_hook": "门外传来敲门声",
        "based_on_canon_revision": 0,
        "based_on_canon_hash": HASH_B,
        "source": author_source(),
        "created_at": NOW,
    }
    values.update(overrides)
    payload = {key: value for key, value in values.items() if key != "created_at"}
    values["content_hash"] = compute_content_hash(payload)
    return ChapterPlan(**values)  # type: ignore[arg-type]


def draft(**overrides: object) -> DraftRevision:
    values: dict[str, object] = {
        "draft_id": "draft-1",
        "schema_version": SCHEMA_VERSION,
        "revision_number": 1,
        "task_id": "task-1",
        "parent_draft_ref": None,
        "kind": DraftKind.AUTHOR_REVISION,
        "content": "这是作者正文。",
        "based_on_plan_ref": ref("plan-1"),
        "working_snapshot_ref": None,
        "source": author_source(),
        "created_at": NOW,
    }
    values.update(overrides)
    payload = {key: value for key, value in values.items() if key != "created_at"}
    values["content_hash"] = compute_content_hash(payload)
    return DraftRevision(**values)  # type: ignore[arg-type]


def author_decision(**overrides: object) -> AuthorDecision:
    values: dict[str, object] = {
        "decision_id": "decision-1",
        "schema_version": SCHEMA_VERSION,
        "task_id": "task-1",
        "decision_type": DecisionType.CONFIRM_PLAN,
        "target_ref": ref("plan-1"),
        "outcome": DecisionOutcome.APPROVE,
        "based_on_task_revision": 1,
        "author_id": "author-1",
        "reason": None,
        "source": author_source(),
        "created_at": NOW,
    }
    values.update(overrides)
    payload = {key: value for key, value in values.items() if key != "created_at"}
    values["content_hash"] = compute_content_hash(payload)
    return AuthorDecision(**values)  # type: ignore[arg-type]


def task(**overrides: object) -> ChapterTask:
    values: dict[str, object] = {
        "task_id": "task-1",
        "schema_version": SCHEMA_VERSION,
        "aggregate_revision": 0,
        "project_id": "project-1",
        "chapter_number": 1,
        "status": ChapterTaskStatus.PLAN_PREPARING,
        "last_stable_status": ChapterTaskStatus.PLAN_PREPARING,
        "creative_intent_ref": ref("intent-1"),
        "confirmed_plan_ref": None,
        "current_author_draft_ref": None,
        "review_target_draft_ref": None,
        "adopted_draft_ref": None,
        "latest_review_ref": None,
        "pending_changeset_ref": None,
        "commit_receipt_ref": None,
        "recovery": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return ChapterTask(**values)  # type: ignore[arg-type]


def test_artifact_ref_validates_identity_schema_and_hash() -> None:
    with pytest.raises(InvalidDomainValue):
        ref(artifact_id=" ")
    with pytest.raises(InvalidDomainValue):
        ArtifactRef("id", 0, HASH_A)
    with pytest.raises(InvalidContentHash):
        ArtifactRef("id", 1, "bad")


def test_source_ref_author_and_model_require_provenance() -> None:
    with pytest.raises(InvalidDomainValue):
        SourceRef(SourceKind.AUTHOR)
    with pytest.raises(InvalidDomainValue):
        SourceRef(SourceKind.MODEL)
    assert SourceRef(SourceKind.SYSTEM).actor_id is None
    assert SourceRef(SourceKind.ANALYSIS_IMPORT).model_run_id is None


def test_frozen_objects_and_tuple_boundaries_prevent_in_place_mutation() -> None:
    intent = creative_intent()
    with pytest.raises(FrozenInstanceError):
        intent.objective = "changed"  # type: ignore[misc]
    with pytest.raises(InvalidDomainValue):
        creative_intent(required_elements=["mutable"])


def test_created_at_is_excluded_from_business_content_hash() -> None:
    first = creative_intent(created_at=NOW)
    second = creative_intent(created_at=datetime(2026, 2, 1, tzinfo=timezone.utc))
    assert first.content_hash == second.content_hash


def test_declared_content_hash_must_match_explicit_payload() -> None:
    valid = creative_intent()
    values = {field: getattr(valid, field) for field in valid.__dataclass_fields__}
    values["content_hash"] = HASH_B
    with pytest.raises(InvalidContentHash):
        CreativeIntent(**values)


def test_plan_beat_orders_are_positive_and_unique() -> None:
    with pytest.raises(InvalidDomainValue):
        ChapterBeat(0, "invalid")
    with pytest.raises(InvalidDomainValue):
        chapter_plan(beats=(ChapterBeat(1, "a"), ChapterBeat(1, "b")))
    with pytest.raises(InvalidDomainValue):
        chapter_plan(based_on_canon_revision=-1)


def test_draft_kind_must_match_source_and_content_cannot_be_blank() -> None:
    with pytest.raises(InvalidDomainValue):
        draft(kind=DraftKind.AUTHOR_REVISION, source=model_source())
    with pytest.raises(InvalidDomainValue):
        draft(kind=DraftKind.MODEL_CANDIDATE, source=author_source())
    with pytest.raises(InvalidDomainValue):
        draft(content="  ")
    candidate = draft(
        kind=DraftKind.MODEL_CANDIDATE,
        source=model_source(),
        content="模型候选正文",
    )
    assert candidate.kind is DraftKind.MODEL_CANDIDATE


def test_review_findings_bind_to_exact_draft_hash() -> None:
    finding = ReviewFinding(
        "finding-1", "continuity", ReviewSeverity.MAJOR, "状态不一致", HASH_B
    )
    values: dict[str, object] = {
        "review_id": "review-1",
        "schema_version": SCHEMA_VERSION,
        "task_id": "task-1",
        "draft_ref": ref("draft-1", HASH_A),
        "review_policy_id": "policy-1",
        "review_policy_version": 1,
        "verdict": ReviewVerdict.REVISE,
        "findings": (finding,),
        "summary": "需要修订",
        "source": model_source(),
        "created_at": NOW,
    }
    payload = {key: value for key, value in values.items() if key != "created_at"}
    values["content_hash"] = compute_content_hash(payload)
    with pytest.raises(InvalidDomainValue):
        ReviewReport(**values)  # type: ignore[arg-type]


def test_review_source_must_be_model_or_system() -> None:
    finding = ReviewFinding("f", "logic", ReviewSeverity.INFO, "ok", HASH_A)
    values: dict[str, object] = {
        "review_id": "review-1",
        "schema_version": 1,
        "task_id": "task-1",
        "draft_ref": ref("draft-1"),
        "review_policy_id": "policy-1",
        "review_policy_version": 1,
        "verdict": ReviewVerdict.PASS,
        "findings": (finding,),
        "summary": "通过不等于采用",
        "source": author_source(),
        "created_at": NOW,
    }
    values["content_hash"] = compute_content_hash(
        {key: value for key, value in values.items() if key != "created_at"}
    )
    with pytest.raises(InvalidDomainValue):
        ReviewReport(**values)  # type: ignore[arg-type]


def test_author_decision_requires_matching_author_source() -> None:
    with pytest.raises(InvalidDomainValue):
        author_decision(source=model_source())
    with pytest.raises(InvalidDomainValue):
        author_decision(author_id="author-2")
    assert author_decision().based_on_task_revision == 1


def test_chapter_task_recovery_and_terminal_invariants() -> None:
    recovery = RecoveryInfo("operation-1", "TIMEOUT", ChapterTaskStatus.DRAFTING)
    with pytest.raises(InvalidDomainValue):
        task(status=ChapterTaskStatus.RECOVERY_REQUIRED, recovery=None)
    recovered = task(
        status=ChapterTaskStatus.RECOVERY_REQUIRED,
        last_stable_status=ChapterTaskStatus.DRAFTING,
        recovery=recovery,
    )
    assert recovered.recovery == recovery
    with pytest.raises(InvalidDomainValue):
        task(recovery=recovery)
    with pytest.raises(InvalidDomainValue):
        task(status=ChapterTaskStatus.COMPLETED)
    completed = task(status=ChapterTaskStatus.COMPLETED, commit_receipt_ref=ref("receipt-1"))
    assert completed.commit_receipt_ref is not None
    with pytest.raises(InvalidDomainValue):
        task(status=ChapterTaskStatus.DRAFTING, commit_receipt_ref=ref("receipt-1"))


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("task_id", ""),
        ("project_id", " "),
        ("chapter_number", 0),
        ("aggregate_revision", -1),
    ],
)
def test_chapter_task_rejects_invalid_identity_and_revision(
    field_name: str, value: object
) -> None:
    with pytest.raises(InvalidDomainValue):
        task(**{field_name: value})


def test_audit_event_is_immutable_and_revision_is_monotonic() -> None:
    event = AuditEvent(
        "event-1",
        1,
        "task-1",
        "project-1",
        "TASK_TRANSITIONED",
        SourceRef(SourceKind.SYSTEM),
        1,
        2,
        (ref(),),
        "operation-1",
        NOW,
    )
    with pytest.raises(FrozenInstanceError):
        event.event_type = "changed"  # type: ignore[misc]
    with pytest.raises(InvalidDomainValue):
        AuditEvent(
            "event-2",
            1,
            "task-1",
            "project-1",
            "TASK_TRANSITIONED",
            SourceRef(SourceKind.SYSTEM),
            2,
            1,
            (),
            "operation-2",
            NOW,
        )


def test_schema_aggregate_and_artifact_revisions_remain_distinct() -> None:
    plan = chapter_plan(revision_number=3)
    aggregate = task(aggregate_revision=7)
    assert plan.schema_version == 1
    assert plan.revision_number == 3
    assert aggregate.aggregate_revision == 7

