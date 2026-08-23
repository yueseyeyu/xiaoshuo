"""SQLite atomic transition tests (B2b — T17).

T17: test_sqlite_atomic_success_and_failure_paths

Verifies that decision consumption in a real SQLite database:
- Succeeds atomically (all writes in same transaction)
- Fails with zero residue on any path
"""

from __future__ import annotations

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
from xiaoshuo.application.creation.errors import UnsupportedPersistenceBoundary
from xiaoshuo.application.creation.local_author_context import LocalAuthorContextImpl
from xiaoshuo.application.creation.transition_context import TransitionOperationContext
from xiaoshuo.domain.creation import (
    ArtifactRef,
    ChapterTaskStatus,
    DecisionType,
)
from xiaoshuo.infrastructure.persistence.sqlite.connection import get_connection
from xiaoshuo.infrastructure.persistence.sqlite.maintenance import init_database
from xiaoshuo.infrastructure.persistence.sqlite.migration_runner import MigrationRunner
from xiaoshuo.infrastructure.persistence.sqlite.settings import (
    SQLitePersistenceSettings,
)
from xiaoshuo.infrastructure.persistence.sqlite.uow import SqliteCreationUnitOfWork

HASH_A = "sha256:" + "a" * 64


def _ref(artifact_id: str = "artifact-1") -> ArtifactRef:
    return ArtifactRef(artifact_id, 1, HASH_A)


def _ids(*names: str) -> Callable[[], str]:
    it = iter(names)

    def _factory() -> str:
        try:
            return next(it)
        except StopIteration:
            import uuid
            return str(uuid.uuid4())

    return _factory


def _init_sqlite(tmp_path: Path) -> SQLitePersistenceSettings:
    settings = SQLitePersistenceSettings(
        tmp_path / "b2b_integ.db", 5000, backup_dir=tmp_path / "backup"
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


def _setup_e1_task(settings: SQLitePersistenceSettings) -> str:
    """Create task, set to PLAN_APPROVAL_PENDING, create CONFIRM_PLAN decision."""
    ci = _ref("intent-task-1")
    cmd = CreateChapterTaskCommand(
        task_id="task-1",
        project_id="project-1",
        chapter_number=1,
        initial_status=ChapterTaskStatus.PLAN_PREPARING,
        creative_intent_ref=ci,
    )
    factory = _sqlite_factory(settings)
    CreateChapterTaskUseCase(
        factory, id_factory=_ids("op-create", "evt-create")
    ).create(cmd)

    # Set to PLAN_APPROVAL_PENDING
    conn = get_connection(settings)
    conn.execute(
        "UPDATE chapter_task SET status = 'PLAN_APPROVAL_PENDING', "
        "last_stable_status = 'PLAN_PREPARING', aggregate_revision = 0 "
        "WHERE task_id = 'task-1'"
    )
    conn.commit()
    conn.close()

    # Create decision
    plan_ref = _ref("plan-1")
    create_cmd = CreateAuthorDecisionCommand(
        task_id="task-1",
        decision_type=DecisionType.CONFIRM_PLAN,
        target_ref=plan_ref,
        based_on_task_revision=0,
    )
    ctx = DecisionCreationContext(idempotency_key="create-dec-1")
    CreateAuthorDecisionUseCase(
        factory, _author_ctx(), id_factory=_ids("op-d-create", "dec-id-1")
    ).create(create_cmd, ctx)

    # Read decision_id
    conn = get_connection(settings, read_only=True)
    row = conn.execute(
        "SELECT decision_id FROM creation_author_decision "
        "WHERE task_id = 'task-1' LIMIT 1"
    ).fetchone()
    conn.close()
    assert row is not None
    return row["decision_id"]


class TestSqliteAtomicSuccessAndFailure:
    """T17: test_sqlite_atomic_success_and_failure_paths"""

    def test_success_all_writes_same_transaction(self, tmp_path: Path) -> None:
        """Five write types: operation, task.replace, audit, consumption,
        and the decision remains immutable — all succeed in same transaction."""
        settings = _init_sqlite(tmp_path)
        decision_id = _setup_e1_task(settings)
        factory = _sqlite_factory(settings)
        uc = ConsumeAuthorDecisionUseCase(
            factory, _author_ctx(), id_factory=_ids("op-succ", "evt-succ", "c-succ")
        )
        cmd = ConsumeAuthorDecisionCommand(
            task_id="task-1", decision_id=decision_id, expected_revision=0
        )
        ctx = TransitionOperationContext(idempotency_key="success-key")
        result = uc.consume(cmd, ctx)

        assert result.status is ChapterTaskStatus.DRAFTING
        assert result.aggregate_revision == 1

        # Verify all writes committed
        conn = get_connection(settings, read_only=True)
        try:
            # 1. operation exists
            op = conn.execute(
                "SELECT operation_id FROM creation_operation "
                "WHERE idempotency_key = 'success-key'"
            ).fetchone()
            assert op is not None
            assert op["operation_id"] == "op-succ"

            # 2. task updated
            task = conn.execute(
                "SELECT status, aggregate_revision FROM chapter_task "
                "WHERE task_id = 'task-1'"
            ).fetchone()
            assert task["status"] == "DRAFTING"
            assert task["aggregate_revision"] == 1

            # 3. audit event exists
            audit = conn.execute(
                "SELECT event_type, actor_kind, actor_id, operation_id "
                "FROM creation_audit_event WHERE operation_id = 'op-succ'"
            ).fetchone()
            assert audit is not None
            assert audit["event_type"] == "TASK_TRANSITIONED"
            assert audit["actor_kind"] == "AUTHOR"
            assert audit["actor_id"] == "author-local-1"

            # 4. consumption exists
            consumption = conn.execute(
                "SELECT consumption_id, decision_id, operation_id "
                "FROM creation_decision_consumption WHERE decision_id = ?",
                (decision_id,),
            ).fetchone()
            assert consumption is not None
            assert consumption["operation_id"] == "op-succ"
        finally:
            conn.close()

    def test_failure_no_residue(self, tmp_path: Path) -> None:
        """Failure path — zero residue."""
        settings = _init_sqlite(tmp_path)
        decision_id = _setup_e1_task(settings)
        factory = _sqlite_factory(settings)
        uc = ConsumeAuthorDecisionUseCase(
            factory, _author_ctx(), id_factory=_ids("op-fail", "evt-fail", "c-fail")
        )
        # Wrong expected revision → revision conflict
        cmd = ConsumeAuthorDecisionCommand(
            task_id="task-1", decision_id=decision_id, expected_revision=99
        )
        ctx = TransitionOperationContext(idempotency_key="failure-key")
        with pytest.raises(Exception):
            uc.consume(cmd, ctx)

        # Verify zero residue
        conn = get_connection(settings, read_only=True)
        try:
            # No operation with this key
            op = conn.execute(
                "SELECT operation_id FROM creation_operation "
                "WHERE idempotency_key = 'failure-key'"
            ).fetchone()
            assert op is None

            # Task unchanged
            task = conn.execute(
                "SELECT status, aggregate_revision FROM chapter_task "
                "WHERE task_id = 'task-1'"
            ).fetchone()
            assert task["status"] == "PLAN_APPROVAL_PENDING"
            assert task["aggregate_revision"] == 0

            # No consumption
            consumption = conn.execute(
                "SELECT consumption_id FROM creation_decision_consumption "
                "WHERE decision_id = ?",
                (decision_id,),
            ).fetchone()
            assert consumption is None
        finally:
            conn.close()

    def test_identity_mismatch_foreign_author_fail_closed(self, tmp_path: Path) -> None:
        """T17 identity mismatch: decision created by author-foreign,
        consumed by author-local-1 → UnsupportedPersistenceBoundary,
        zero residue across Task, operation, Audit, consumption, Artifact."""
        settings = _init_sqlite(tmp_path)

        # --- Create task with author-local-1 ---
        ci = _ref("intent-task-1")
        cmd = CreateChapterTaskCommand(
            task_id="task-1",
            project_id="project-1",
            chapter_number=1,
            initial_status=ChapterTaskStatus.PLAN_PREPARING,
            creative_intent_ref=ci,
        )
        factory = _sqlite_factory(settings)
        CreateChapterTaskUseCase(
            factory, id_factory=_ids("op-create", "evt-create")
        ).create(cmd)

        # Set to PLAN_APPROVAL_PENDING
        conn = get_connection(settings)
        conn.execute(
            "UPDATE chapter_task SET status = 'PLAN_APPROVAL_PENDING', "
            "last_stable_status = 'PLAN_PREPARING', aggregate_revision = 0 "
            "WHERE task_id = 'task-1'"
        )
        conn.commit()
        conn.close()

        # --- Create decision with author-foreign ---
        foreign_ctx = LocalAuthorContextImpl(_author_id="author-foreign")
        plan_ref = _ref("plan-1")
        create_cmd = CreateAuthorDecisionCommand(
            task_id="task-1",
            decision_type=DecisionType.CONFIRM_PLAN,
            target_ref=plan_ref,
            based_on_task_revision=0,
        )
        ctx_create = DecisionCreationContext(idempotency_key="create-dec-foreign")
        CreateAuthorDecisionUseCase(
            factory, foreign_ctx, id_factory=_ids("op-d-foreign", "dec-foreign-1")
        ).create(create_cmd, ctx_create)

        # Read decision_id
        conn = get_connection(settings, read_only=True)
        row = conn.execute(
            "SELECT decision_id FROM creation_author_decision "
            "WHERE task_id = 'task-1' LIMIT 1"
        ).fetchone()
        conn.close()
        assert row is not None
        decision_id = row["decision_id"]

        # Record baseline counts before consumption attempt
        conn = get_connection(settings, read_only=True)
        try:
            baseline_task_rev = conn.execute(
                "SELECT aggregate_revision FROM chapter_task WHERE task_id = 'task-1'"
            ).fetchone()[0]
            baseline_op_count = conn.execute(
                "SELECT COUNT(*) FROM creation_operation"
            ).fetchone()[0]
            baseline_audit_count = conn.execute(
                "SELECT COUNT(*) FROM creation_audit_event WHERE task_id = 'task-1'"
            ).fetchone()[0]
            baseline_consumption_count = conn.execute(
                "SELECT COUNT(*) FROM creation_decision_consumption"
            ).fetchone()[0]
            baseline_artifact_count = conn.execute(
                "SELECT COUNT(*) FROM creation_artifact_ref"
            ).fetchone()[0]
        finally:
            conn.close()

        # --- Try to consume with author-local-1 ---
        local_ctx = _author_ctx()  # author-local-1
        uc = ConsumeAuthorDecisionUseCase(
            factory, local_ctx,
            id_factory=_ids("op-consume-fail", "evt-consume-fail", "c-consume-fail")
        )
        consume_cmd = ConsumeAuthorDecisionCommand(
            task_id="task-1", decision_id=decision_id, expected_revision=0
        )
        ctx_consume = TransitionOperationContext(idempotency_key="consume-foreign-key")
        with pytest.raises(UnsupportedPersistenceBoundary):
            uc.consume(consume_cmd, ctx_consume)

        # --- Verify zero residue across all five types ---
        conn = get_connection(settings, read_only=True)
        try:
            # 1. Task unchanged
            task = conn.execute(
                "SELECT status, aggregate_revision FROM chapter_task "
                "WHERE task_id = 'task-1'"
            ).fetchone()
            assert task["status"] == "PLAN_APPROVAL_PENDING"
            assert task["aggregate_revision"] == baseline_task_rev

            # 2. No new operation
            op_count = conn.execute(
                "SELECT COUNT(*) FROM creation_operation"
            ).fetchone()[0]
            assert op_count == baseline_op_count

            # 3. No new audit event
            audit_count = conn.execute(
                "SELECT COUNT(*) FROM creation_audit_event WHERE task_id = 'task-1'"
            ).fetchone()[0]
            assert audit_count == baseline_audit_count

            # 4. No new consumption
            consumption_count = conn.execute(
                "SELECT COUNT(*) FROM creation_decision_consumption"
            ).fetchone()[0]
            assert consumption_count == baseline_consumption_count

            # 5. No new Artifact registry
            artifact_count = conn.execute(
                "SELECT COUNT(*) FROM creation_artifact_ref"
            ).fetchone()[0]
            assert artifact_count == baseline_artifact_count
        finally:
            conn.close()
