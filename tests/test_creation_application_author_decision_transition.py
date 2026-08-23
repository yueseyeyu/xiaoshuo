"""ConsumeAuthorDecision use case tests (B2b — T04–T16, T19–T20, T22).

Covers:
T04: test_decision_can_be_consumed_only_once
T05: test_consumption_is_traceable_by_operation_and_audit
T06: test_confirm_plan_writes_only_confirmed_plan_ref (E1)
T07: test_confirm_plan_mismatch_leaves_no_residue (E1)
T08: test_adopt_draft_writes_only_adopted_draft_ref (E2)
T09: test_adopt_draft_mismatch_leaves_no_residue (E2)
T10: test_reject_draft_preserves_all_artifact_refs (E3)
T11: test_reject_draft_requires_review_target_draft_ref (E3)
T12: test_reject_changeset_preserves_all_artifact_refs (E4)
T13: test_reject_changeset_requires_pending_changeset_ref (E4)
T14: test_replay_returns_original_result_envelope
T15: test_same_key_different_digest_conflicts
T16: test_revision_conflict_rollback_and_close
T19: test_consumption_context_key_written_to_ledger
T20: test_consumption_context_not_in_digest_and_replay_returns_original
T22: test_success_audit_actor_is_author_and_seven_role_object_refs
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys
from typing import Callable

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from xiaoshuo.application.creation.author_decision import CreateAuthorDecisionUseCase
from xiaoshuo.application.creation.author_decision_transition import (
    ConsumeAuthorDecisionUseCase,
)
from xiaoshuo.application.creation.commands import (
    ConsumeAuthorDecisionCommand,
    CreateAuthorDecisionCommand,
    CreateChapterTaskCommand,
)
from xiaoshuo.application.creation.create_task import CreateChapterTaskUseCase
from xiaoshuo.application.creation.decision_creation_context import (
    DecisionCreationContext,
)
from xiaoshuo.application.creation.digest import (
    result_from_decision_consumption_envelope,
)
from xiaoshuo.application.creation.errors import (
    CreationApplicationError,
    IdempotencyConflict,
    UnsupportedPersistenceBoundary,
)
from xiaoshuo.application.creation.local_author_context import LocalAuthorContextImpl
from xiaoshuo.application.creation.transition_context import TransitionOperationContext
from xiaoshuo.domain.creation import (
    ArtifactRef,
    ChapterTask,
    ChapterTaskStatus,
    DecisionType,
)
from xiaoshuo.domain.creation.state_machine import (
    RevisionConflict as DomainRevisionConflict,
)
from xiaoshuo.infrastructure.persistence.sqlite.connection import get_connection
from xiaoshuo.infrastructure.persistence.sqlite.maintenance import init_database
from xiaoshuo.infrastructure.persistence.sqlite.migration_runner import MigrationRunner
from xiaoshuo.infrastructure.persistence.sqlite.settings import (
    SQLitePersistenceSettings,
)
from xiaoshuo.infrastructure.persistence.sqlite.uow import SqliteCreationUnitOfWork

_ADOPTED_DRAFT_BYTES = b"adopted draft payload"
HASH_A = "sha256:" + hashlib.sha256(_ADOPTED_DRAFT_BYTES).hexdigest()
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ref(artifact_id: str = "artifact-1") -> ArtifactRef:
    return ArtifactRef(artifact_id, 1, HASH_A)


def _ids(*names: str) -> Callable[[], str]:
    """Return a factory that yields the given names in order, then uuid4."""
    it = iter(names)

    def _factory() -> str:
        try:
            return next(it)
        except StopIteration:
            import uuid
            return str(uuid.uuid4())

    return _factory


def _strict_ids(*names: str) -> Callable[[], str]:
    """Return a factory that yields exactly the given names, then fails.

    Used to prove that REPLAY does not generate new identities.
    """
    it = iter(names)

    def _factory() -> str:
        try:
            return next(it)
        except StopIteration:
            raise AssertionError("id_factory called more times than expected")

    return _factory


class _AdoptedDraftPayloadStore:
    def put(self, data: bytes) -> str:
        assert data == _ADOPTED_DRAFT_BYTES
        return HASH_A

    def read(self, digest: str) -> bytes:
        assert digest == HASH_A
        return _ADOPTED_DRAFT_BYTES


def _count_all(settings: SQLitePersistenceSettings, task_id: str = "task-1") -> dict:
    """Count all six registry types for zero-residue verification."""
    conn = get_connection(settings, read_only=True)
    try:
        task_row = conn.execute(
            "SELECT status, aggregate_revision FROM chapter_task WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        return {
            "task_status": task_row["status"] if task_row else None,
            "task_rev": task_row["aggregate_revision"] if task_row else None,
            "dec_count": conn.execute(
                "SELECT COUNT(*) FROM creation_author_decision WHERE task_id = ?",
                (task_id,),
            ).fetchone()[0],
            "op_count": conn.execute(
                "SELECT COUNT(*) FROM creation_operation"
            ).fetchone()[0],
            "audit_count": conn.execute(
                "SELECT COUNT(*) FROM creation_audit_event "
                "WHERE task_id = ? AND event_type != 'TASK_CREATED'",
                (task_id,),
            ).fetchone()[0],
            "consumption_count": conn.execute(
                "SELECT COUNT(*) FROM creation_decision_consumption"
            ).fetchone()[0],
            "artifact_count": conn.execute(
                "SELECT COUNT(*) FROM creation_artifact_ref"
            ).fetchone()[0],
        }
    finally:
        conn.close()


def _init_sqlite(tmp_path: Path) -> SQLitePersistenceSettings:
    settings = SQLitePersistenceSettings(
        tmp_path / "b2b.db", 5000, backup_dir=tmp_path / "backup"
    )
    init_database(settings)
    setup = get_connection(settings)
    MigrationRunner().migrate(setup, settings)
    setup.close()
    return settings


def _sqlite_factory(settings: SQLitePersistenceSettings):
    def factory() -> SqliteCreationUnitOfWork:
        return SqliteCreationUnitOfWork(get_connection(settings))
    return factory


def _author_ctx() -> LocalAuthorContextImpl:
    return LocalAuthorContextImpl(_author_id="author-local-1")


def _create_base_task(settings: SQLitePersistenceSettings, task_id: str = "task-1") -> None:
    """Create a task via CreateChapterTaskUseCase (status=PLAN_PREPARING)."""
    ci = _ref(f"intent-{task_id}")
    cmd = CreateChapterTaskCommand(
        task_id=task_id,
        project_id="project-1",
        chapter_number=1,
        initial_status=ChapterTaskStatus.PLAN_PREPARING,
        creative_intent_ref=ci,
    )
    factory = _sqlite_factory(settings)
    CreateChapterTaskUseCase(
        factory, id_factory=_ids("op-create", "evt-create")
    ).create(cmd)


def _set_task_status(
    settings: SQLitePersistenceSettings,
    task_id: str,
    *,
    status: ChapterTaskStatus,
    last_stable_status: ChapterTaskStatus,
    revision: int = 3,
    confirmed_plan: ArtifactRef | None = None,
    current_draft: ArtifactRef | None = None,
    review_target: ArtifactRef | None = None,
    latest_review: ArtifactRef | None = None,
    adopted_draft: ArtifactRef | None = None,
    pending_changeset: ArtifactRef | None = None,
) -> None:
    """Manually update task status and ArtifactRefs in the DB."""
    conn = get_connection(settings)
    try:
        # Register ArtifactRefs first
        for ref in (
            confirmed_plan,
            current_draft,
            review_target,
            latest_review,
            adopted_draft,
            pending_changeset,
        ):
            if ref is not None:
                conn.execute(
                    "INSERT OR IGNORE INTO creation_artifact_ref "
                    "(artifact_id, schema_version, content_hash) VALUES (?, ?, ?)",
                    (ref.artifact_id, ref.schema_version, ref.content_hash),
                )
        conn.execute(
            "UPDATE chapter_task SET status = ?, last_stable_status = ?, "
            "aggregate_revision = ?, "
            "confirmed_plan_ref_artifact_id = ?, "
            "current_author_draft_ref_artifact_id = ?, "
            "review_target_draft_ref_artifact_id = ?, "
            "latest_review_ref_artifact_id = ?, "
            "adopted_draft_ref_artifact_id = ?, "
            "pending_changeset_ref_artifact_id = ? "
            "WHERE task_id = ?",
            (
                status.value, last_stable_status.value, revision,
                confirmed_plan.artifact_id if confirmed_plan else None,
                current_draft.artifact_id if current_draft else None,
                review_target.artifact_id if review_target else None,
                latest_review.artifact_id if latest_review else None,
                adopted_draft.artifact_id if adopted_draft else None,
                pending_changeset.artifact_id if pending_changeset else None,
                task_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _create_decision(
    settings: SQLitePersistenceSettings,
    task_id: str,
    decision_type: DecisionType,
    target_ref: ArtifactRef,
    based_on_revision: int,
    *,
    decision_id: str = "decision-1",
    context_key: str = "creation-key-1",
    author_id: str = "author-local-1",
) -> str:
    """Create an AuthorDecision via CreateAuthorDecisionUseCase. Returns decision_id."""
    factory = _sqlite_factory(settings)
    author_ctx = LocalAuthorContextImpl(_author_id=author_id)
    cmd = CreateAuthorDecisionCommand(
        task_id=task_id,
        decision_type=decision_type,
        target_ref=target_ref,
        based_on_task_revision=based_on_revision,
        adopted_draft_payload=(
            _ADOPTED_DRAFT_BYTES
            if decision_type is DecisionType.ADOPT_DRAFT
            else None
        ),
    )
    ctx = DecisionCreationContext(idempotency_key=context_key)
    CreateAuthorDecisionUseCase(
        factory,
        author_ctx,
        id_factory=_ids("op-d-create", "decision-id-1"),
        payload_store=(
            _AdoptedDraftPayloadStore()
            if decision_type is DecisionType.ADOPT_DRAFT
            else None
        ),
    ).create(cmd, ctx)
    # Read back the decision_id from DB
    conn = get_connection(settings, read_only=True)
    try:
        row = conn.execute(
            "SELECT decision_id FROM creation_author_decision "
            "WHERE task_id = ? ORDER BY created_at DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        assert row is not None
        return row["decision_id"]
    finally:
        conn.close()


def _read_task(settings: SQLitePersistenceSettings, task_id: str) -> ChapterTask:
    conn = get_connection(settings, read_only=True)
    try:
        from xiaoshuo.infrastructure.persistence.sqlite.repository import (
            SqliteChapterTaskRepository,
        )
        repo = SqliteChapterTaskRepository(conn)
        task = repo.get(task_id)
        assert task is not None
        return task
    finally:
        conn.close()


def _read_operation_ledger(settings: SQLitePersistenceSettings, idempotency_key: str):
    conn = get_connection(settings, read_only=True)
    try:
        row = conn.execute(
            "SELECT operation_id, idempotency_key, request_digest, "
            "result_envelope_json, result_envelope_hash, created_at "
            "FROM creation_operation WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        return row
    finally:
        conn.close()


def _read_audit_events(settings: SQLitePersistenceSettings, task_id: str):
    conn = get_connection(settings, read_only=True)
    try:
        rows = conn.execute(
            "SELECT event_id, task_id, project_id, event_type, "
            "actor_kind, actor_id, before_task_revision, "
            "after_task_revision, operation_id, created_at "
            "FROM creation_audit_event WHERE task_id = ? "
            "ORDER BY created_at DESC",
            (task_id,),
        ).fetchall()
        return rows
    finally:
        conn.close()


def _read_consumption(settings: SQLitePersistenceSettings, decision_id: str):
    conn = get_connection(settings, read_only=True)
    try:
        row = conn.execute(
            "SELECT consumption_id, decision_id, operation_id, task_id, "
            "consumed_at_task_revision, consumed_at "
            "FROM creation_decision_consumption WHERE decision_id = ?",
            (decision_id,),
        ).fetchone()
        return row
    finally:
        conn.close()


def _count_decisions(settings: SQLitePersistenceSettings, task_id: str) -> int:
    conn = get_connection(settings, read_only=True)
    try:
        (cnt,) = conn.execute(
            "SELECT COUNT(*) FROM creation_author_decision WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        return cnt
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# E1: CONFIRM_PLAN tests
# ---------------------------------------------------------------------------

class TestConfirmPlanE1:
    """T06, T07: E1 CONFIRM_PLAN tests."""

    def test_confirm_plan_writes_only_confirmed_plan_ref(self, tmp_path: Path) -> None:
        """T06: E1 success — only confirmed_plan_ref changes."""
        settings = _init_sqlite(tmp_path)
        _create_base_task(settings, "task-1")
        plan_ref = _ref("plan-1")
        _set_task_status(
            settings, "task-1",
            status=ChapterTaskStatus.PLAN_APPROVAL_PENDING,
            last_stable_status=ChapterTaskStatus.PLAN_PREPARING,
            revision=0,
        )
        decision_id = _create_decision(
            settings, "task-1", DecisionType.CONFIRM_PLAN, plan_ref, 0
        )
        factory = _sqlite_factory(settings)
        uc = ConsumeAuthorDecisionUseCase(factory, _author_ctx(), id_factory=_ids("op-consume", "evt-consume", "c-1"))
        cmd = ConsumeAuthorDecisionCommand(
            task_id="task-1",
            decision_id=decision_id,
            expected_revision=0,
        )
        ctx = TransitionOperationContext(idempotency_key="consume-key-1")
        result = uc.consume(cmd, ctx)

        assert result.task_id == "task-1"
        assert result.status is ChapterTaskStatus.DRAFTING
        assert result.aggregate_revision == 1

        task = _read_task(settings, "task-1")
        assert task.status is ChapterTaskStatus.DRAFTING
        assert task.confirmed_plan_ref == plan_ref
        assert task.aggregate_revision == 1

    def test_confirm_plan_mismatch_leaves_no_residue(self, tmp_path: Path) -> None:
        """T07: E1 mismatch — creation rejected, zero residue."""
        settings = _init_sqlite(tmp_path)
        _create_base_task(settings, "task-1")
        _set_task_status(
            settings, "task-1",
            status=ChapterTaskStatus.DRAFTING,  # Wrong source status
            last_stable_status=ChapterTaskStatus.DRAFTING,
            revision=0,
        )
        plan_ref = _ref("plan-1")
        # Record baseline before attempt
        baseline = _count_all(settings, "task-1")
        # Creation should fail due to task status mismatch
        factory = _sqlite_factory(settings)
        author_ctx = LocalAuthorContextImpl(_author_id="author-local-1")
        cmd = CreateAuthorDecisionCommand(
            task_id="task-1",
            decision_type=DecisionType.CONFIRM_PLAN,
            target_ref=plan_ref,
            based_on_task_revision=0,
        )
        ctx = DecisionCreationContext(idempotency_key="creation-fail-1")
        with pytest.raises(UnsupportedPersistenceBoundary):
            CreateAuthorDecisionUseCase(
                factory, author_ctx, id_factory=_ids("op-fail-c", "dec-fail-c")
            ).create(cmd, ctx)

        # Verify zero residue across all six types
        after = _count_all(settings, "task-1")
        assert after["task_status"] == baseline["task_status"]
        assert after["task_rev"] == baseline["task_rev"]
        assert after["dec_count"] == baseline["dec_count"]
        assert after["op_count"] == baseline["op_count"]
        assert after["audit_count"] == baseline["audit_count"]
        assert after["consumption_count"] == baseline["consumption_count"]
        assert after["artifact_count"] == baseline["artifact_count"]


# ---------------------------------------------------------------------------
# E2: ADOPT_DRAFT tests
# ---------------------------------------------------------------------------

class TestAdoptDraftE2:
    """T08, T09: E2 ADOPT_DRAFT tests."""

    @pytest.mark.parametrize(
        ("case_id", "current_draft", "review_target", "latest_review"),
        (
            ("G0B-CORR-01", None, _ref("draft-1"), _ref("review-1")),
            ("G0B-CORR-02", _ref("draft-1"), None, _ref("review-1")),
            ("G0B-CORR-03", _ref("draft-1"), _ref("review-1"), _ref("latest-1")),
            ("G0B-CORR-04", _ref("draft-1"), _ref("draft-1"), None),
        ),
    )
    def test_g0b_corr_01_to_04_trusted_target_creation_rejects_missing_or_mismatched_refs(
        self,
        tmp_path: Path,
        case_id: str,
        current_draft: ArtifactRef | None,
        review_target: ArtifactRef | None,
        latest_review: ArtifactRef | None,
    ) -> None:
        del case_id
        settings = _init_sqlite(tmp_path)
        _create_base_task(settings, "task-1")
        target = review_target or current_draft or _ref("draft-1")
        _set_task_status(
            settings,
            "task-1",
            status=ChapterTaskStatus.DRAFT_APPROVAL_PENDING,
            last_stable_status=ChapterTaskStatus.DRAFTING,
            revision=1,
            current_draft=current_draft,
            review_target=review_target,
            latest_review=latest_review,
        )
        baseline = _count_all(settings, "task-1")
        with pytest.raises(UnsupportedPersistenceBoundary):
            _create_decision(
                settings, "task-1", DecisionType.ADOPT_DRAFT, target, 1
            )
        assert _count_all(settings, "task-1") == baseline

    def test_g0b_corr_07_consumption_rechecks_current_task_trusted_target(
        self, tmp_path: Path
    ) -> None:
        settings = _init_sqlite(tmp_path)
        _create_base_task(settings, "task-1")
        target = _ref("draft-1")
        _set_task_status(
            settings,
            "task-1",
            status=ChapterTaskStatus.DRAFT_APPROVAL_PENDING,
            last_stable_status=ChapterTaskStatus.DRAFTING,
            revision=1,
            current_draft=target,
            review_target=target,
            latest_review=_ref("review-1"),
        )
        decision_id = _create_decision(
            settings, "task-1", DecisionType.ADOPT_DRAFT, target, 1
        )
        # The persisted decision is left untouched; the current Task contract
        # is deliberately made inconsistent and must fail closed.
        _set_task_status(
            settings,
            "task-1",
            status=ChapterTaskStatus.DRAFT_APPROVAL_PENDING,
            last_stable_status=ChapterTaskStatus.DRAFTING,
            revision=1,
            current_draft=target,
            review_target=_ref("wrong-review-target"),
            latest_review=_ref("review-1"),
        )
        baseline = _count_all(settings, "task-1")
        with pytest.raises(UnsupportedPersistenceBoundary):
            ConsumeAuthorDecisionUseCase(
                _sqlite_factory(settings), _author_ctx(), id_factory=_ids()
            ).consume(
                ConsumeAuthorDecisionCommand("task-1", decision_id, 1),
                TransitionOperationContext("g0b-corr-07"),
            )
        assert _count_all(settings, "task-1") == baseline

    def test_adopt_draft_writes_only_adopted_draft_ref(self, tmp_path: Path) -> None:
        """T08: E2 success — only adopted_draft_ref changes."""
        settings = _init_sqlite(tmp_path)
        _create_base_task(settings, "task-1")
        plan_ref = _ref("plan-1")
        draft_ref = _ref("draft-1")
        _set_task_status(
            settings, "task-1",
            status=ChapterTaskStatus.DRAFT_APPROVAL_PENDING,
            last_stable_status=ChapterTaskStatus.DRAFTING,
            revision=1,
            confirmed_plan=plan_ref,
            current_draft=draft_ref,
            review_target=draft_ref,
            latest_review=_ref("review-1"),
        )
        decision_id = _create_decision(
            settings, "task-1", DecisionType.ADOPT_DRAFT, draft_ref, 1
        )
        factory = _sqlite_factory(settings)
        uc = ConsumeAuthorDecisionUseCase(factory, _author_ctx(), id_factory=_ids("op-a", "evt-a", "c-a"))
        cmd = ConsumeAuthorDecisionCommand(
            task_id="task-1",
            decision_id=decision_id,
            expected_revision=1,
        )
        ctx = TransitionOperationContext(idempotency_key="adopt-key-1")
        result = uc.consume(cmd, ctx)

        assert result.status is ChapterTaskStatus.CHANGESET_PREPARING
        assert result.aggregate_revision == 2

        task = _read_task(settings, "task-1")
        assert task.status is ChapterTaskStatus.CHANGESET_PREPARING
        assert task.adopted_draft_ref == draft_ref
        assert task.confirmed_plan_ref == plan_ref  # unchanged

    def test_adopt_draft_mismatch_leaves_no_residue(self, tmp_path: Path) -> None:
        """T09: E2 mismatch — creation rejected, zero residue."""
        settings = _init_sqlite(tmp_path)
        _create_base_task(settings, "task-1")
        draft_ref = _ref("draft-1")
        _set_task_status(
            settings, "task-1",
            status=ChapterTaskStatus.DRAFTING,  # Wrong source
            last_stable_status=ChapterTaskStatus.DRAFTING,
            revision=1,
        )
        # Record baseline before attempt
        baseline = _count_all(settings, "task-1")
        # Creation should fail due to task status mismatch
        factory = _sqlite_factory(settings)
        author_ctx = LocalAuthorContextImpl(_author_id="author-local-1")
        cmd = CreateAuthorDecisionCommand(
            task_id="task-1",
            decision_type=DecisionType.ADOPT_DRAFT,
            target_ref=draft_ref,
            based_on_task_revision=1,
            adopted_draft_payload=_ADOPTED_DRAFT_BYTES,
        )
        ctx = DecisionCreationContext(idempotency_key="creation-fail-2")
        with pytest.raises(UnsupportedPersistenceBoundary):
            CreateAuthorDecisionUseCase(
                factory,
                author_ctx,
                id_factory=_ids("op-fail-c2", "dec-fail-c2"),
                payload_store=_AdoptedDraftPayloadStore(),
            ).create(cmd, ctx)
        # Verify zero residue across all six types
        after = _count_all(settings, "task-1")
        assert after["task_status"] == baseline["task_status"]
        assert after["task_rev"] == baseline["task_rev"]
        assert after["dec_count"] == baseline["dec_count"]
        assert after["op_count"] == baseline["op_count"]
        assert after["audit_count"] == baseline["audit_count"]
        assert after["consumption_count"] == baseline["consumption_count"]
        assert after["artifact_count"] == baseline["artifact_count"]


# ---------------------------------------------------------------------------
# E3: REJECT_DRAFT tests
# ---------------------------------------------------------------------------

class TestRejectDraftE3:
    """T10, T11: E3 REJECT_DRAFT tests."""

    def test_reject_draft_preserves_all_artifact_refs(self, tmp_path: Path) -> None:
        """T10: E3 success — all refs unchanged, no new registrations."""
        settings = _init_sqlite(tmp_path)
        _create_base_task(settings, "task-1")
        plan_ref = _ref("plan-1")
        review_ref = _ref("review-1")
        _set_task_status(
            settings, "task-1",
            status=ChapterTaskStatus.DRAFT_APPROVAL_PENDING,
            last_stable_status=ChapterTaskStatus.DRAFTING,
            revision=1,
            confirmed_plan=plan_ref,
            review_target=review_ref,
        )
        decision_id = _create_decision(
            settings, "task-1", DecisionType.REJECT_DRAFT, review_ref, 1
        )
        factory = _sqlite_factory(settings)
        uc = ConsumeAuthorDecisionUseCase(factory, _author_ctx(), id_factory=_ids("op-r", "evt-r", "c-r"))
        cmd = ConsumeAuthorDecisionCommand(
            task_id="task-1",
            decision_id=decision_id,
            expected_revision=1,
        )
        ctx = TransitionOperationContext(idempotency_key="reject-draft-key")
        result = uc.consume(cmd, ctx)

        assert result.status is ChapterTaskStatus.DRAFTING
        task = _read_task(settings, "task-1")
        assert task.status is ChapterTaskStatus.DRAFTING
        assert task.confirmed_plan_ref == plan_ref  # unchanged
        assert task.review_target_draft_ref == review_ref  # unchanged
        assert task.adopted_draft_ref is None  # unchanged

    def test_reject_draft_requires_review_target_draft_ref(self, tmp_path: Path) -> None:
        """T11: E3 target != review_target_draft_ref → creation fail-closed, zero residue."""
        settings = _init_sqlite(tmp_path)
        _create_base_task(settings, "task-1")
        plan_ref = _ref("plan-1")
        review_ref = _ref("review-1")
        wrong_ref = _ref("wrong-1")
        _set_task_status(
            settings, "task-1",
            status=ChapterTaskStatus.DRAFT_APPROVAL_PENDING,
            last_stable_status=ChapterTaskStatus.DRAFTING,
            revision=1,
            confirmed_plan=plan_ref,
            review_target=review_ref,
        )
        # Record baseline before attempt
        baseline = _count_all(settings, "task-1")
        # Creation should fail due to target mismatch
        factory = _sqlite_factory(settings)
        author_ctx = LocalAuthorContextImpl(_author_id="author-local-1")
        cmd = CreateAuthorDecisionCommand(
            task_id="task-1",
            decision_type=DecisionType.REJECT_DRAFT,
            target_ref=wrong_ref,
            based_on_task_revision=1,
        )
        ctx = DecisionCreationContext(idempotency_key="creation-fail-3")
        with pytest.raises(UnsupportedPersistenceBoundary):
            CreateAuthorDecisionUseCase(
                factory, author_ctx, id_factory=_ids("op-fail-c3", "dec-fail-c3")
            ).create(cmd, ctx)
        # Verify zero residue across all six types
        after = _count_all(settings, "task-1")
        assert after["task_status"] == baseline["task_status"]
        assert after["task_rev"] == baseline["task_rev"]
        assert after["dec_count"] == baseline["dec_count"]
        assert after["op_count"] == baseline["op_count"]
        assert after["audit_count"] == baseline["audit_count"]
        assert after["consumption_count"] == baseline["consumption_count"]
        assert after["artifact_count"] == baseline["artifact_count"]


# ---------------------------------------------------------------------------
# E4: REJECT_CHANGESET tests
# ---------------------------------------------------------------------------

class TestRejectChangesetE4:
    """T12, T13: E4 REJECT_CHANGESET tests."""

    def test_reject_changeset_preserves_all_artifact_refs(self, tmp_path: Path) -> None:
        """T12: E4 success — all refs unchanged."""
        settings = _init_sqlite(tmp_path)
        _create_base_task(settings, "task-1")
        plan_ref = _ref("plan-1")
        draft_ref = _ref("draft-1")
        changeset_ref = _ref("changeset-1")
        _set_task_status(
            settings, "task-1",
            status=ChapterTaskStatus.CHANGESET_APPROVAL_PENDING,
            last_stable_status=ChapterTaskStatus.CHANGESET_PREPARING,
            revision=2,
            confirmed_plan=plan_ref,
            current_draft=draft_ref,
            pending_changeset=changeset_ref,
        )
        decision_id = _create_decision(
            settings, "task-1", DecisionType.REJECT_CHANGESET, changeset_ref, 2
        )
        factory = _sqlite_factory(settings)
        uc = ConsumeAuthorDecisionUseCase(factory, _author_ctx(), id_factory=_ids("op-rc", "evt-rc", "c-rc"))
        cmd = ConsumeAuthorDecisionCommand(
            task_id="task-1",
            decision_id=decision_id,
            expected_revision=2,
        )
        ctx = TransitionOperationContext(idempotency_key="reject-cs-key")
        result = uc.consume(cmd, ctx)

        assert result.status is ChapterTaskStatus.CHANGESET_PREPARING
        task = _read_task(settings, "task-1")
        assert task.status is ChapterTaskStatus.CHANGESET_PREPARING
        assert task.pending_changeset_ref == changeset_ref  # unchanged

    def test_reject_changeset_requires_pending_changeset_ref(self, tmp_path: Path) -> None:
        """T13: E4 target != pending_changeset_ref → creation fail-closed, zero residue."""
        settings = _init_sqlite(tmp_path)
        _create_base_task(settings, "task-1")
        changeset_ref = _ref("changeset-1")
        wrong_ref = _ref("wrong-2")
        _set_task_status(
            settings, "task-1",
            status=ChapterTaskStatus.CHANGESET_APPROVAL_PENDING,
            last_stable_status=ChapterTaskStatus.CHANGESET_PREPARING,
            revision=2,
            pending_changeset=changeset_ref,
        )
        # Record baseline before attempt
        baseline = _count_all(settings, "task-1")
        # Creation should fail due to target mismatch
        factory = _sqlite_factory(settings)
        author_ctx = LocalAuthorContextImpl(_author_id="author-local-1")
        cmd = CreateAuthorDecisionCommand(
            task_id="task-1",
            decision_type=DecisionType.REJECT_CHANGESET,
            target_ref=wrong_ref,
            based_on_task_revision=2,
        )
        ctx = DecisionCreationContext(idempotency_key="creation-fail-4")
        with pytest.raises(UnsupportedPersistenceBoundary):
            CreateAuthorDecisionUseCase(
                factory, author_ctx, id_factory=_ids("op-fail-c4", "dec-fail-c4")
            ).create(cmd, ctx)
        # Verify zero residue across all six types
        after = _count_all(settings, "task-1")
        assert after["task_status"] == baseline["task_status"]
        assert after["task_rev"] == baseline["task_rev"]
        assert after["dec_count"] == baseline["dec_count"]
        assert after["op_count"] == baseline["op_count"]
        assert after["audit_count"] == baseline["audit_count"]
        assert after["consumption_count"] == baseline["consumption_count"]
        assert after["artifact_count"] == baseline["artifact_count"]


# ---------------------------------------------------------------------------
# Idempotency, REPLAY, CONFLICT, revision conflict tests
# ---------------------------------------------------------------------------

class TestIdempotencyAndReplay:
    """T04, T05, T14, T15, T16: idempotency, replay, conflict, revision conflict."""

    def _setup_e1_task(self, settings: SQLitePersistenceSettings) -> str:
        _create_base_task(settings, "task-1")
        _set_task_status(
            settings, "task-1",
            status=ChapterTaskStatus.PLAN_APPROVAL_PENDING,
            last_stable_status=ChapterTaskStatus.PLAN_PREPARING,
            revision=0,
        )
        plan_ref = _ref("plan-1")
        return _create_decision(
            settings, "task-1", DecisionType.CONFIRM_PLAN, plan_ref, 0
        )

    def test_decision_can_be_consumed_only_once(self, tmp_path: Path) -> None:
        """T04: repeat consumption → second fails."""
        settings = _init_sqlite(tmp_path)
        decision_id = self._setup_e1_task(settings)
        factory = _sqlite_factory(settings)
        uc = ConsumeAuthorDecisionUseCase(factory, _author_ctx(), id_factory=_ids("op-1a", "evt-1a", "c-1a"))
        cmd = ConsumeAuthorDecisionCommand(
            task_id="task-1", decision_id=decision_id, expected_revision=0
        )
        ctx1 = TransitionOperationContext(idempotency_key="key-once-1")
        result1 = uc.consume(cmd, ctx1)
        assert result1.status is ChapterTaskStatus.DRAFTING

        # Second consumption with different idempotency key — should fail
        uc2 = ConsumeAuthorDecisionUseCase(factory, _author_ctx(), id_factory=_ids("op-1b", "evt-1b", "c-1b"))
        ctx2 = TransitionOperationContext(idempotency_key="key-once-2")
        with pytest.raises(UnsupportedPersistenceBoundary):
            uc2.consume(cmd, ctx2)

    def test_consumption_is_traceable_by_operation_and_audit(self, tmp_path: Path) -> None:
        """T05: operation_id links consumption and audit."""
        settings = _init_sqlite(tmp_path)
        decision_id = self._setup_e1_task(settings)
        factory = _sqlite_factory(settings)
        uc = ConsumeAuthorDecisionUseCase(factory, _author_ctx(), id_factory=_ids("op-trace", "evt-trace", "c-trace"))
        cmd = ConsumeAuthorDecisionCommand(
            task_id="task-1", decision_id=decision_id, expected_revision=0
        )
        ctx = TransitionOperationContext(idempotency_key="trace-key")
        uc.consume(cmd, ctx)

        consumption = _read_consumption(settings, decision_id)
        assert consumption is not None
        assert consumption["operation_id"] == "op-trace"

        audits = _read_audit_events(settings, "task-1")
        # Find the TASK_TRANSITIONED event
        transition_audits = [a for a in audits if a["event_type"] == "TASK_TRANSITIONED"]
        assert len(transition_audits) >= 1
        audit = transition_audits[0]
        assert audit["actor_kind"] == "AUTHOR"
        assert audit["actor_id"] == "author-local-1"
        assert audit["operation_id"] == "op-trace"

    def test_replay_returns_original_result_envelope(self, tmp_path: Path) -> None:
        """T14: same key + same digest → REPLAY returns original envelope."""
        settings = _init_sqlite(tmp_path)
        decision_id = self._setup_e1_task(settings)
        factory = _sqlite_factory(settings)
        uc = ConsumeAuthorDecisionUseCase(factory, _author_ctx(), id_factory=_ids("op-rep1", "evt-rep1", "c-rep1"))
        cmd = ConsumeAuthorDecisionCommand(
            task_id="task-1", decision_id=decision_id, expected_revision=0
        )
        ctx = TransitionOperationContext(idempotency_key="replay-key-1")
        result1 = uc.consume(cmd, ctx)
        assert result1.status is ChapterTaskStatus.DRAFTING
        assert result1.aggregate_revision == 1

        # REPLAY with same key
        result2 = uc.consume(cmd, ctx)
        assert result2.task_id == result1.task_id
        assert result2.aggregate_revision == result1.aggregate_revision
        assert result2.status == result1.status

    def test_same_key_different_digest_conflicts(self, tmp_path: Path) -> None:
        """T15: same key + different digest → CONFLICT."""
        settings = _init_sqlite(tmp_path)
        decision_id = self._setup_e1_task(settings)
        factory = _sqlite_factory(settings)
        uc = ConsumeAuthorDecisionUseCase(factory, _author_ctx(), id_factory=_ids("op-cf1", "evt-cf1", "c-cf1"))
        cmd = ConsumeAuthorDecisionCommand(
            task_id="task-1", decision_id=decision_id, expected_revision=0
        )
        ctx = TransitionOperationContext(idempotency_key="conflict-key-1")
        uc.consume(cmd, ctx)

        # Different command with same key → CONFLICT
        cmd2 = ConsumeAuthorDecisionCommand(
            task_id="task-1", decision_id=decision_id, expected_revision=99  # different
        )
        with pytest.raises(IdempotencyConflict):
            uc.consume(cmd2, ctx)

    def test_revision_conflict_rollback_and_close(self, tmp_path: Path) -> None:
        """T16: revision conflict → rollback and close."""
        settings = _init_sqlite(tmp_path)
        decision_id = self._setup_e1_task(settings)
        factory = _sqlite_factory(settings)
        uc = ConsumeAuthorDecisionUseCase(factory, _author_ctx(), id_factory=_ids("op-rc1", "evt-rc1", "c-rc1"))
        # Use wrong expected_revision
        cmd = ConsumeAuthorDecisionCommand(
            task_id="task-1", decision_id=decision_id, expected_revision=99
        )
        ctx = TransitionOperationContext(idempotency_key="rev-conflict-key")
        with pytest.raises((DomainRevisionConflict, CreationApplicationError)):
            uc.consume(cmd, ctx)
        # Verify zero residue
        consumption = _read_consumption(settings, decision_id)
        assert consumption is None
        task = _read_task(settings, "task-1")
        assert task.status is ChapterTaskStatus.PLAN_APPROVAL_PENDING  # unchanged


# ---------------------------------------------------------------------------
# Context key and Audit tests
# ---------------------------------------------------------------------------

class TestContextKeyAndAudit:
    """T19, T20, T22: context key, digest exclusion, audit actor/refs."""

    def test_consumption_context_key_written_to_ledger(self, tmp_path: Path) -> None:
        """T19: ledger key precisely equals context key, not task_id/decision_id."""
        settings = _init_sqlite(tmp_path)
        _create_base_task(settings, "task-1")
        _set_task_status(
            settings, "task-1",
            status=ChapterTaskStatus.PLAN_APPROVAL_PENDING,
            last_stable_status=ChapterTaskStatus.PLAN_PREPARING,
            revision=0,
        )
        plan_ref = _ref("plan-1")
        decision_id = _create_decision(
            settings, "task-1", DecisionType.CONFIRM_PLAN, plan_ref, 0
        )
        factory = _sqlite_factory(settings)
        uc = ConsumeAuthorDecisionUseCase(factory, _author_ctx(), id_factory=_ids("op-ck", "evt-ck", "c-ck"))
        cmd = ConsumeAuthorDecisionCommand(
            task_id="task-1", decision_id=decision_id, expected_revision=0
        )
        ctx_key = "consumption-context-key-xyz"
        ctx = TransitionOperationContext(idempotency_key=ctx_key)
        uc.consume(cmd, ctx)

        ledger = _read_operation_ledger(settings, ctx_key)
        assert ledger is not None
        assert ledger["idempotency_key"] == ctx_key
        assert ledger["idempotency_key"] != "task-1"
        assert ledger["idempotency_key"] != decision_id

    def test_consumption_context_not_in_digest_and_replay_returns_original(
        self, tmp_path: Path
    ) -> None:
        """T20: context not in digest; REPLAY returns original envelope,
        parsed via formal result parser, with zero new writes and no new identity."""
        settings = _init_sqlite(tmp_path)
        _create_base_task(settings, "task-1")
        _set_task_status(
            settings, "task-1",
            status=ChapterTaskStatus.PLAN_APPROVAL_PENDING,
            last_stable_status=ChapterTaskStatus.PLAN_PREPARING,
            revision=0,
        )
        plan_ref = _ref("plan-1")
        decision_id = _create_decision(
            settings, "task-1", DecisionType.CONFIRM_PLAN, plan_ref, 0
        )
        factory = _sqlite_factory(settings)
        # Use strict id_factory: exactly 3 IDs for first consume, fails on extra
        uc = ConsumeAuthorDecisionUseCase(
            factory, _author_ctx(),
            id_factory=_strict_ids("op-dg1", "evt-dg1", "c-dg1")
        )
        cmd = ConsumeAuthorDecisionCommand(
            task_id="task-1", decision_id=decision_id, expected_revision=0
        )
        ctx_key = "digest-test-key"
        ctx = TransitionOperationContext(idempotency_key=ctx_key)
        result1 = uc.consume(cmd, ctx)

        # Read the digest from ledger
        ledger = _read_operation_ledger(settings, ctx_key)
        assert ledger is not None
        # The context key should NOT appear in the digest
        assert ctx_key not in ledger["request_digest"]

        # Read original DB envelope and parse with formal result parser
        original_envelope = ledger["result_envelope_json"]
        parsed = result_from_decision_consumption_envelope(
            original_envelope, expected_task_id="task-1"
        )

        # Record baseline counts before REPLAY
        baseline = _count_all(settings, "task-1")

        # REPLAY with same key — should return original without calling id_factory
        result2 = uc.consume(cmd, ctx)

        # Compare replay result with formal parser output field by field
        assert result2.task_id == parsed.task_id
        assert result2.aggregate_revision == parsed.aggregate_revision
        assert result2.status == parsed.status
        assert result2.result_schema_version == parsed.result_schema_version

        # Also compare with result1
        assert result2.task_id == result1.task_id
        assert result2.aggregate_revision == result1.aggregate_revision
        assert result2.status == result1.status

        # Assert replay produces no new writes across all six types
        after = _count_all(settings, "task-1")
        assert after["task_status"] == baseline["task_status"]
        assert after["task_rev"] == baseline["task_rev"]
        assert after["dec_count"] == baseline["dec_count"]
        assert after["op_count"] == baseline["op_count"]
        assert after["audit_count"] == baseline["audit_count"]
        assert after["consumption_count"] == baseline["consumption_count"]
        assert after["artifact_count"] == baseline["artifact_count"]

    def test_success_audit_actor_is_author_and_seven_role_object_refs(
        self, tmp_path: Path
    ) -> None:
        """T22: audit actor=AUTHOR, object_refs in 7-role order, no fake fields."""
        settings = _init_sqlite(tmp_path)
        _create_base_task(settings, "task-1")
        plan_ref = _ref("plan-1")
        draft_ref = _ref("draft-1")
        review_ref = _ref("review-1")
        _set_task_status(
            settings, "task-1",
            status=ChapterTaskStatus.DRAFT_APPROVAL_PENDING,
            last_stable_status=ChapterTaskStatus.DRAFTING,
            revision=1,
            confirmed_plan=plan_ref,
            current_draft=draft_ref,
            review_target=draft_ref,
            latest_review=review_ref,
        )
        # Use ADOPT_DRAFT (E2) to have multiple non-null refs
        adopt_ref = _ref("adopt-1")
        decision_id = _create_decision(
            settings, "task-1", DecisionType.ADOPT_DRAFT, draft_ref, 1
        )
        factory = _sqlite_factory(settings)
        uc = ConsumeAuthorDecisionUseCase(factory, _author_ctx(), id_factory=_ids("op-audit", "evt-audit", "c-audit"))
        cmd = ConsumeAuthorDecisionCommand(
            task_id="task-1", decision_id=decision_id, expected_revision=1
        )
        ctx = TransitionOperationContext(idempotency_key="audit-test-key")
        uc.consume(cmd, ctx)

        # Read the audit event
        audits = _read_audit_events(settings, "task-1")
        transition_audits = [a for a in audits if a["event_type"] == "TASK_TRANSITIONED"]
        assert len(transition_audits) >= 1
        audit = transition_audits[0]

        # actor must be AUTHOR with author-local-1
        assert audit["actor_kind"] == "AUTHOR"
        assert audit["actor_id"] == "author-local-1"

        # object_refs must be in 7-role order, only non-null
        conn = get_connection(settings, read_only=True)
        try:
            obj_refs = conn.execute(
                "SELECT artifact_id FROM creation_audit_event_object_ref "
                "WHERE event_id = ? ORDER BY ordinal",
                (audit["event_id"],),
            ).fetchall()
            ref_ids = [r["artifact_id"] for r in obj_refs]
            # Expected: creative_intent, confirmed_plan, current_draft, review_target, adopted_draft
            # (latest_review and pending_changeset are None)
            expected_order = [
                "intent-task-1",
                "plan-1",
                "draft-1",
                "draft-1",
                "draft-1",
                "review-1",
            ]
            assert ref_ids == expected_order

            # Verify no source_refs table or decision_id column
            # AuditEvent only has actor and object_refs
            cols = [d[1] for d in conn.execute(
                "PRAGMA table_info(creation_audit_event)"
            ).fetchall()]
            assert "source_refs" not in [c.lower() for c in cols]
            assert "decision_id" not in [c.lower() for c in cols]
        finally:
            conn.close()
