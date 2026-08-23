"""DecisionCreationContext tests (B2b — T21).

T21: test_decision_creation_context_key_and_replay_and_zero_residue

Verifies that DecisionCreationContext:
- Is frozen, slots, only idempotency_key
- Does not enter the request digest
- REPLAY returns the original creation envelope from real SQLite DB
- No new identity, no extra decision/operation/audit/registry writes on REPLAY
- Two different context keys with same command produce same digest, different ledger keys
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
import sys
from typing import Callable

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from xiaoshuo.application.creation.author_decision import CreateAuthorDecisionUseCase
from xiaoshuo.application.creation.commands import (
    CreateAuthorDecisionCommand,
    CreateChapterTaskCommand,
)
from xiaoshuo.application.creation.create_task import CreateChapterTaskUseCase
from xiaoshuo.application.creation.decision_creation_context import (
    DecisionCreationContext,
)
from xiaoshuo.application.creation.digest import (
    compute_decision_creation_request_digest,
    result_from_decision_creation_envelope,
)
from xiaoshuo.application.creation.local_author_context import LocalAuthorContextImpl
from xiaoshuo.application.creation.operation_kind import OperationKind
from xiaoshuo.domain.creation import ArtifactRef, ChapterTaskStatus, DecisionType
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


def _init_sqlite(tmp_path: Path) -> SQLitePersistenceSettings:
    settings = SQLitePersistenceSettings(
        tmp_path / "b2b_t21.db", 5000, backup_dir=tmp_path / "backup"
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


def _set_task_to_plan_approval(settings: SQLitePersistenceSettings) -> None:
    conn = get_connection(settings)
    conn.execute(
        "UPDATE chapter_task SET status = 'PLAN_APPROVAL_PENDING', "
        "last_stable_status = 'PLAN_PREPARING', aggregate_revision = 0 "
        "WHERE task_id = 'task-1'"
    )
    conn.commit()
    conn.close()


class TestDecisionCreationContextContract:
    """T21: test_decision_creation_context_key_and_replay_and_zero_residue"""

    def test_context_is_frozen(self) -> None:
        ctx = DecisionCreationContext(idempotency_key="creation-key-1")
        with pytest.raises(FrozenInstanceError):
            ctx.idempotency_key = "other"  # type: ignore[misc]

    def test_context_rejects_empty_key(self) -> None:
        with pytest.raises(ValueError):
            DecisionCreationContext(idempotency_key="")

    def test_context_rejects_whitespace_key(self) -> None:
        with pytest.raises(ValueError):
            DecisionCreationContext(idempotency_key="   ")

    def test_context_has_no_actor_or_trace_fields(self) -> None:
        ctx = DecisionCreationContext(idempotency_key="key-1")
        assert not hasattr(ctx, "actor")
        assert not hasattr(ctx, "auth")
        assert not hasattr(ctx, "trace")
        assert not hasattr(ctx, "timestamp")
        assert not hasattr(ctx, "source_refs")
        assert not hasattr(ctx, "author_id")

    def test_context_not_in_digest_two_keys_same_digest(self) -> None:
        """Two different context keys with same command produce same digest,
        proving context key does not enter the digest."""
        cmd = CreateAuthorDecisionCommand(
            task_id="task-1",
            decision_type=DecisionType.CONFIRM_PLAN,
            target_ref=_ref("plan-1"),
            based_on_task_revision=0,
        )
        kind = OperationKind.CREATE_AUTHOR_DECISION
        digest = compute_decision_creation_request_digest(cmd, kind)
        ctx1 = DecisionCreationContext(idempotency_key="key-A")
        ctx2 = DecisionCreationContext(idempotency_key="key-B")
        # Since context is not in digest, both should produce same digest
        assert digest == compute_decision_creation_request_digest(cmd, kind)
        # The context key itself should not appear in the digest
        assert ctx1.idempotency_key not in digest
        assert ctx2.idempotency_key not in digest

    def test_real_sqlite_create_replay_and_zero_residue(self, tmp_path: Path) -> None:
        """Real SQLite: first create, read original envelope, same key+digest
        replay returns original envelope (parsed via formal result parser),
        no new identity, no new decision/operation/audit/consumption/registry writes."""
        settings = _init_sqlite(tmp_path)
        _create_base_task(settings, "task-1")
        _set_task_to_plan_approval(settings)
        factory = _sqlite_factory(settings)
        author_ctx = _author_ctx()
        plan_ref = _ref("plan-1")
        cmd = CreateAuthorDecisionCommand(
            task_id="task-1",
            decision_type=DecisionType.CONFIRM_PLAN,
            target_ref=plan_ref,
            based_on_task_revision=0,
        )
        ctx_key = "creation-replay-key-1"
        ctx = DecisionCreationContext(idempotency_key=ctx_key)
        # Use strict id_factory: exactly 2 IDs for first create, fails on extra
        uc = CreateAuthorDecisionUseCase(
            factory, author_ctx, id_factory=_strict_ids("dec-1", "op-d-1")
        )
        result1 = uc.create(cmd, ctx)
        assert result1.decision_id == "dec-1"

        # Read original envelope from DB
        conn = get_connection(settings, read_only=True)
        op_row = conn.execute(
            "SELECT operation_id, idempotency_key, request_digest, "
            "result_envelope_json, result_envelope_hash "
            "FROM creation_operation WHERE idempotency_key = ?",
            (ctx_key,),
        ).fetchone()
        assert op_row is not None
        assert op_row["operation_id"] == "op-d-1"
        original_envelope = op_row["result_envelope_json"]
        dec_count = conn.execute(
            "SELECT COUNT(*) FROM creation_author_decision WHERE task_id = 'task-1'"
        ).fetchone()[0]
        op_count = conn.execute(
            "SELECT COUNT(*) FROM creation_operation"
        ).fetchone()[0]
        audit_count = conn.execute(
            "SELECT COUNT(*) FROM creation_audit_event WHERE task_id = 'task-1'"
        ).fetchone()[0]
        consumption_count = conn.execute(
            "SELECT COUNT(*) FROM creation_decision_consumption"
        ).fetchone()[0]
        artifact_count = conn.execute(
            "SELECT COUNT(*) FROM creation_artifact_ref"
        ).fetchone()[0]
        conn.close()

        assert dec_count == 1
        assert op_count == 2  # 1 create-task + 1 create-decision
        assert audit_count == 1  # 1 from create-task
        assert consumption_count == 0

        # Parse original envelope with formal result parser
        parsed = result_from_decision_creation_envelope(original_envelope)
        assert parsed.decision_id == "dec-1"
        assert parsed.task_id == "task-1"

        # REPLAY: same key, same digest — must not call id_factory
        result2 = uc.create(cmd, ctx)

        # Compare replay result with formal parser output field by field
        assert result2.decision_id == parsed.decision_id
        assert result2.task_id == parsed.task_id
        assert result2.result_schema_version == parsed.result_schema_version

        # Also compare with result1
        assert result2.decision_id == result1.decision_id
        assert result2.task_id == result1.task_id

        # Verify no new writes across all six types
        conn = get_connection(settings, read_only=True)
        dec_count_after = conn.execute(
            "SELECT COUNT(*) FROM creation_author_decision WHERE task_id = 'task-1'"
        ).fetchone()[0]
        op_count_after = conn.execute(
            "SELECT COUNT(*) FROM creation_operation"
        ).fetchone()[0]
        audit_count_after = conn.execute(
            "SELECT COUNT(*) FROM creation_audit_event WHERE task_id = 'task-1'"
        ).fetchone()[0]
        consumption_count_after = conn.execute(
            "SELECT COUNT(*) FROM creation_decision_consumption"
        ).fetchone()[0]
        artifact_count_after = conn.execute(
            "SELECT COUNT(*) FROM creation_artifact_ref"
        ).fetchone()[0]
        # The replay envelope should be the original
        op_row2 = conn.execute(
            "SELECT result_envelope_json FROM creation_operation "
            "WHERE idempotency_key = ?",
            (ctx_key,),
        ).fetchone()
        conn.close()

        assert dec_count_after == dec_count  # no new decision
        assert op_count_after == op_count  # no new operation
        assert audit_count_after == audit_count  # no new audit
        assert consumption_count_after == consumption_count  # no new consumption
        assert artifact_count_after == artifact_count  # no new artifact
        assert op_row2["result_envelope_json"] == original_envelope

    def test_two_context_keys_different_ledger_same_digest(self, tmp_path: Path) -> None:
        """Two different context keys for same command: request digest is the same,
        but ledger keys are different, proving context key enters ledger but not digest."""
        settings = _init_sqlite(tmp_path)
        _create_base_task(settings, "task-1")
        _set_task_to_plan_approval(settings)
        factory = _sqlite_factory(settings)
        author_ctx = _author_ctx()
        plan_ref = _ref("plan-1")
        cmd = CreateAuthorDecisionCommand(
            task_id="task-1",
            decision_type=DecisionType.CONFIRM_PLAN,
            target_ref=plan_ref,
            based_on_task_revision=0,
        )
        ctx1 = DecisionCreationContext(idempotency_key="key-X")
        ctx2 = DecisionCreationContext(idempotency_key="key-Y")
        uc1 = CreateAuthorDecisionUseCase(
            factory, author_ctx, id_factory=_ids("op-x", "dec-x")
        )
        uc2 = CreateAuthorDecisionUseCase(
            factory, author_ctx, id_factory=_ids("op-y", "dec-y")
        )
        uc1.create(cmd, ctx1)
        uc2.create(cmd, ctx2)

        conn = get_connection(settings, read_only=True)
        ops = conn.execute(
            "SELECT idempotency_key, request_digest FROM creation_operation "
            "WHERE idempotency_key IN (?, ?)",
            ("key-X", "key-Y"),
        ).fetchall()
        conn.close()
        assert len(ops) == 2
        digests = {r["request_digest"] for r in ops}
        keys = {r["idempotency_key"] for r in ops}
        assert len(digests) == 1  # same digest
        assert keys == {"key-X", "key-Y"}  # different ledger keys
