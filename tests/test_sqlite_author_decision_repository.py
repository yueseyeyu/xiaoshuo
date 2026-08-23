"""SQLite AuthorDecision repository tests (B2b — T03).

T03: test_author_decision_is_append_only
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from xiaoshuo.application.creation.errors import CreationApplicationError
from xiaoshuo.application.creation.repository import DecisionConsumptionRecord
from xiaoshuo.domain.creation import (
    ArtifactRef,
    AuthorDecision,
    DecisionOutcome,
    DecisionType,
    SCHEMA_VERSION,
    SourceKind,
    SourceRef,
    compute_content_hash,
)
from xiaoshuo.domain.creation.hashing import canonicalize_json_value
from xiaoshuo.infrastructure.persistence.sqlite.author_decision_repository import (
    SqliteAuthorDecisionRepository,
)
from xiaoshuo.infrastructure.persistence.sqlite.connection import get_connection
from xiaoshuo.infrastructure.persistence.sqlite.maintenance import init_database
from xiaoshuo.infrastructure.persistence.sqlite.migration_runner import MigrationRunner
from xiaoshuo.infrastructure.persistence.sqlite.settings import (
    SQLitePersistenceSettings,
)

HASH_A = "sha256:" + "a" * 64


def _ref(artifact_id: str = "artifact-1") -> ArtifactRef:
    return ArtifactRef(artifact_id, 1, HASH_A)


def _init_sqlite(tmp_path: Path) -> SQLitePersistenceSettings:
    settings = SQLitePersistenceSettings(
        tmp_path / "b2b_repo.db", 5000, backup_dir=tmp_path / "backup"
    )
    init_database(settings)
    setup = get_connection(settings)
    MigrationRunner().migrate(setup, settings)
    setup.close()
    return settings


def _make_decision(
    decision_id: str = "decision-1",
    *,
    task_id: str = "task-1",
    decision_type: DecisionType = DecisionType.CONFIRM_PLAN,
    target_ref: ArtifactRef | None = None,
    based_on_task_revision: int = 0,
    author_id: str = "author-local-1",
) -> AuthorDecision:
    tref = target_ref or _ref(f"target-{decision_id}")
    source = SourceRef(kind=SourceKind.AUTHOR, actor_id=author_id)
    now = datetime.now(timezone.utc)
    payload = {
        "decision_id": decision_id,
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "decision_type": decision_type,
        "target_ref": tref,
        "outcome": DecisionOutcome.APPROVE,
        "based_on_task_revision": based_on_task_revision,
        "author_id": author_id,
        "reason": None,
        "source": source,
    }
    content_hash = compute_content_hash(canonicalize_json_value(payload))
    return AuthorDecision(
        decision_id=decision_id,
        schema_version=SCHEMA_VERSION,
        task_id=task_id,
        decision_type=decision_type,
        target_ref=tref,
        outcome=DecisionOutcome.APPROVE,
        based_on_task_revision=based_on_task_revision,
        author_id=author_id,
        reason=None,
        source=source,
        created_at=now,
        content_hash=content_hash,
    )


def _create_task_row(settings: SQLitePersistenceSettings, task_id: str = "task-1") -> None:
    """Insert a minimal chapter_task row to satisfy FK."""
    conn = get_connection(settings)
    try:
        conn.execute(
            "INSERT INTO creation_artifact_ref (artifact_id, schema_version, content_hash) "
            "VALUES (?, ?, ?)",
            ("intent-1", 1, HASH_A),
        )
        conn.execute(
            "INSERT INTO chapter_task ("
            "task_id, schema_version, aggregate_revision, project_id, "
            "chapter_number, status, last_stable_status, "
            "creative_intent_ref_artifact_id, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task_id, 1, 0, "project-1", 1,
                "PLAN_APPROVAL_PENDING", "DRAFTING",
                "intent-1",
                datetime.now(timezone.utc).isoformat(),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


class TestAuthorDecisionIsAppendOnly:
    """T03: test_author_decision_is_append_only"""

    def test_update_rejected(self, tmp_path: Path) -> None:
        settings = _init_sqlite(tmp_path)
        _create_task_row(settings, "task-1")
        conn = get_connection(settings)
        repo = SqliteAuthorDecisionRepository(conn)
        decision = _make_decision()
        repo.add(decision)
        conn.commit()
        # Try to UPDATE — should be rejected by trigger
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE creation_author_decision SET reason = 'changed' "
                "WHERE decision_id = ?",
                ("decision-1",),
            )
        conn.close()

    def test_delete_rejected(self, tmp_path: Path) -> None:
        settings = _init_sqlite(tmp_path)
        _create_task_row(settings, "task-1")
        conn = get_connection(settings)
        repo = SqliteAuthorDecisionRepository(conn)
        decision = _make_decision()
        repo.add(decision)
        conn.commit()
        # Try to DELETE — should be rejected by trigger
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "DELETE FROM creation_author_decision WHERE decision_id = ?",
                ("decision-1",),
            )
        conn.close()

    def test_round_trip(self, tmp_path: Path) -> None:
        settings = _init_sqlite(tmp_path)
        _create_task_row(settings, "task-1")
        conn = get_connection(settings)
        repo = SqliteAuthorDecisionRepository(conn)
        decision = _make_decision()
        repo.add(decision)
        conn.commit()
        # Read back
        result = repo.get("decision-1")
        assert result is not None
        assert result.decision_id == decision.decision_id
        assert result.task_id == decision.task_id
        assert result.decision_type == decision.decision_type
        assert result.target_ref == decision.target_ref
        assert result.outcome == decision.outcome
        assert result.based_on_task_revision == decision.based_on_task_revision
        assert result.author_id == decision.author_id
        assert result.content_hash == decision.content_hash
        conn.close()

    def test_consumption_unique_per_decision(self, tmp_path: Path) -> None:
        settings = _init_sqlite(tmp_path)
        _create_task_row(settings, "task-1")
        conn = get_connection(settings)
        repo = SqliteAuthorDecisionRepository(conn)
        decision = _make_decision()
        repo.add(decision)
        # Need an operation row for FK
        conn.execute(
            "INSERT INTO creation_operation ("
            "operation_id, idempotency_key, request_digest, "
            "result_envelope_json, result_envelope_hash, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?)",
            ("op-1", "key-1", "digest-1", "{}", "hash-1",
             datetime.now(timezone.utc).isoformat()),
        )
        record = DecisionConsumptionRecord(
            consumption_id="c-1",
            decision_id="decision-1",
            operation_id="op-1",
            task_id="task-1",
            consumed_at_task_revision=1,
            consumed_at=datetime.now(timezone.utc).isoformat(),
        )
        repo.add_consumption(record)
        # Try to add a second consumption for the same decision — should fail
        record2 = DecisionConsumptionRecord(
            consumption_id="c-2",
            decision_id="decision-1",
            operation_id="op-2",
            task_id="task-1",
            consumed_at_task_revision=2,
            consumed_at=datetime.now(timezone.utc).isoformat(),
        )
        conn.execute(
            "INSERT INTO creation_operation ("
            "operation_id, idempotency_key, request_digest, "
            "result_envelope_json, result_envelope_hash, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?)",
            ("op-2", "key-2", "digest-2", "{}", "hash-2",
             datetime.now(timezone.utc).isoformat()),
        )
        with pytest.raises(CreationApplicationError):
            repo.add_consumption(record2)
        conn.close()


class TestV002HashConstraints:
    """Direct SQLite tests for v002 content_hash GLOB constraint."""

    def test_short_hash_rejected(self, tmp_path: Path) -> None:
        settings = _init_sqlite(tmp_path)
        _create_task_row(settings, "task-1")
        conn = get_connection(settings)
        # Use a valid artifact_ref hash but try a short content_hash on the decision
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO creation_author_decision ("
                "decision_id, schema_version, task_id, decision_type, "
                "target_ref_artifact_id, outcome, based_on_task_revision, "
                "author_id, reason, actor_kind, actor_id, content_hash, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("d-short", 1, "task-1", "CONFIRM_PLAN", "intent-1",
                 "APPROVE", 0, "author-1", None, "AUTHOR", "author-1",
                 "sha256:abc",
                 datetime.now(timezone.utc).isoformat()),
            )
        conn.close()

    def test_non_hex_hash_rejected(self, tmp_path: Path) -> None:
        settings = _init_sqlite(tmp_path)
        _create_task_row(settings, "task-1")
        conn = get_connection(settings)
        # Non-hex hash (contains 'g' and uppercase)
        non_hex = "sha256:" + "g" * 64
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO creation_author_decision ("
                "decision_id, schema_version, task_id, decision_type, "
                "target_ref_artifact_id, outcome, based_on_task_revision, "
                "author_id, reason, actor_kind, actor_id, content_hash, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("d-nonhex", 1, "task-1", "CONFIRM_PLAN", "intent-1",
                 "APPROVE", 0, "author-1", None, "AUTHOR", "author-1",
                 non_hex,
                 datetime.now(timezone.utc).isoformat()),
            )
        conn.close()

    def test_uppercase_hex_hash_rejected(self, tmp_path: Path) -> None:
        settings = _init_sqlite(tmp_path)
        _create_task_row(settings, "task-1")
        conn = get_connection(settings)
        # Uppercase hex hash
        upper_hash = "sha256:" + "A" * 64
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO creation_author_decision ("
                "decision_id, schema_version, task_id, decision_type, "
                "target_ref_artifact_id, outcome, based_on_task_revision, "
                "author_id, reason, actor_kind, actor_id, content_hash, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("d-upper", 1, "task-1", "CONFIRM_PLAN", "intent-1",
                 "APPROVE", 0, "author-1", None, "AUTHOR", "author-1",
                 upper_hash,
                 datetime.now(timezone.utc).isoformat()),
            )
        conn.close()

    def test_valid_hash_accepted(self, tmp_path: Path) -> None:
        settings = _init_sqlite(tmp_path)
        _create_task_row(settings, "task-1")
        conn = get_connection(settings)
        valid_hash = "sha256:" + "a" * 64
        conn.execute(
            "INSERT INTO creation_author_decision ("
            "decision_id, schema_version, task_id, decision_type, "
            "target_ref_artifact_id, outcome, based_on_task_revision, "
            "author_id, reason, actor_kind, actor_id, content_hash, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("d-valid", 1, "task-1", "CONFIRM_PLAN", "intent-1",
             "APPROVE", 0, "author-1", None, "AUTHOR", "author-1",
             valid_hash,
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        # Verify it was actually written
        row = conn.execute(
            "SELECT content_hash FROM creation_author_decision "
            "WHERE decision_id = 'd-valid'"
        ).fetchone()
        assert row is not None
        assert row["content_hash"] == valid_hash
        conn.close()


class TestPython310TimeCompat:
    """Tests for Python 3.10 datetime.fromisoformat() compatibility.

    Uses real SqliteAuthorDecisionRepository.get() to verify that complete
    AuthorDecision data can be read back regardless of the stored time format.
    """

    def test_reads_trailing_z_format(self, tmp_path: Path) -> None:
        """Legacy data with trailing Z must be fully readable via repository.get()."""
        settings = _init_sqlite(tmp_path)
        _create_task_row(settings, "task-1")
        conn = get_connection(settings)
        repo = SqliteAuthorDecisionRepository(conn)
        decision = _make_decision()
        # Register the target_ref ArtifactRef first (repo.add does this automatically)
        conn.execute(
            "INSERT INTO creation_artifact_ref "
            "(artifact_id, schema_version, content_hash) VALUES (?, ?, ?)",
            (
                decision.target_ref.artifact_id,
                decision.target_ref.schema_version,
                decision.target_ref.content_hash,
            ),
        )
        # Insert directly with trailing Z format (bypassing repo.add which uses +00:00)
        z_time = "2026-07-23T14:30:00.123456Z"
        conn.execute(
            "INSERT INTO creation_author_decision ("
            "decision_id, schema_version, task_id, decision_type, "
            "target_ref_artifact_id, outcome, based_on_task_revision, "
            "author_id, reason, actor_kind, actor_id, content_hash, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                decision.decision_id, decision.schema_version,
                decision.task_id, decision.decision_type.value,
                decision.target_ref.artifact_id, decision.outcome.value,
                decision.based_on_task_revision, decision.author_id,
                decision.reason, "AUTHOR", decision.author_id,
                decision.content_hash, z_time,
            ),
        )
        conn.commit()
        # Read back via real repository — must get complete AuthorDecision
        result = repo.get(decision.decision_id)
        assert result is not None
        assert result.decision_id == decision.decision_id
        assert result.schema_version == decision.schema_version
        assert result.task_id == decision.task_id
        assert result.decision_type == decision.decision_type
        assert result.target_ref == decision.target_ref
        assert result.outcome == decision.outcome
        assert result.based_on_task_revision == decision.based_on_task_revision
        assert result.author_id == decision.author_id
        assert result.reason == decision.reason
        assert result.source == decision.source
        assert result.content_hash == decision.content_hash
        assert result.created_at.tzinfo is not None
        conn.close()

    def test_reads_plus_offset_format(self, tmp_path: Path) -> None:
        """New data with +00:00 offset must be fully readable via repository.get()."""
        settings = _init_sqlite(tmp_path)
        _create_task_row(settings, "task-1")
        conn = get_connection(settings)
        repo = SqliteAuthorDecisionRepository(conn)
        decision = _make_decision()
        repo.add(decision)
        conn.commit()
        # Verify stored format is +00:00 (not Z)
        row = conn.execute(
            "SELECT created_at FROM creation_author_decision "
            "WHERE decision_id = ?",
            (decision.decision_id,),
        ).fetchone()
        assert row is not None
        assert not row["created_at"].endswith("Z")
        # Read back via real repository — must get complete AuthorDecision
        result = repo.get(decision.decision_id)
        assert result is not None
        assert result.decision_id == decision.decision_id
        assert result.schema_version == decision.schema_version
        assert result.task_id == decision.task_id
        assert result.decision_type == decision.decision_type
        assert result.target_ref == decision.target_ref
        assert result.outcome == decision.outcome
        assert result.based_on_task_revision == decision.based_on_task_revision
        assert result.author_id == decision.author_id
        assert result.reason == decision.reason
        assert result.source == decision.source
        assert result.content_hash == decision.content_hash
        assert result.created_at.tzinfo is not None
        conn.close()

    def test_new_write_uses_plus_offset_not_z(self, tmp_path: Path) -> None:
        """New decision writes must use +00:00, not trailing Z."""
        settings = _init_sqlite(tmp_path)
        _create_task_row(settings, "task-1")
        conn = get_connection(settings)
        repo = SqliteAuthorDecisionRepository(conn)
        decision = _make_decision()
        repo.add(decision)
        conn.commit()
        row = conn.execute(
            "SELECT created_at FROM creation_author_decision "
            "WHERE decision_id = 'decision-1'"
        ).fetchone()
        assert row is not None
        # Must NOT end with Z (Python 3.10 compatible)
        assert not row["created_at"].endswith("Z")
        # Must contain +00:00
        assert "+00:00" in row["created_at"]
        conn.close()


class TestRepositoryReadErrorBoundary:
    """Tests that SqliteAuthorDecisionRepository.get() maps all read-chain
    errors to stable CreationApplicationError and preserves the original cause."""

    def test_closed_connection_maps_to_application_error(self, tmp_path: Path) -> None:
        """When the SQLite connection is closed, get() must raise
        CreationApplicationError, not sqlite3.Error."""
        settings = _init_sqlite(tmp_path)
        _create_task_row(settings, "task-1")
        conn = get_connection(settings)
        repo = SqliteAuthorDecisionRepository(conn)
        decision = _make_decision()
        repo.add(decision)
        conn.commit()
        conn.close()
        # Now the connection is closed — get() must raise CreationApplicationError
        with pytest.raises(CreationApplicationError) as exc_info:
            repo.get(decision.decision_id)
        # The original cause must be preserved
        assert exc_info.value.__cause__ is not None

    def test_invalid_datetime_maps_to_application_error(self, tmp_path: Path) -> None:
        """When created_at is not parseable, get() must raise
        CreationApplicationError, not ValueError."""
        settings = _init_sqlite(tmp_path)
        _create_task_row(settings, "task-1")
        conn = get_connection(settings)
        repo = SqliteAuthorDecisionRepository(conn)
        decision = _make_decision()
        # Register the target_ref ArtifactRef first (repo.add does this automatically)
        conn.execute(
            "INSERT INTO creation_artifact_ref "
            "(artifact_id, schema_version, content_hash) VALUES (?, ?, ?)",
            (
                decision.target_ref.artifact_id,
                decision.target_ref.schema_version,
                decision.target_ref.content_hash,
            ),
        )
        # Insert directly with invalid datetime (bypassing repo.add)
        conn.execute(
            "INSERT INTO creation_author_decision ("
            "decision_id, schema_version, task_id, decision_type, "
            "target_ref_artifact_id, outcome, based_on_task_revision, "
            "author_id, reason, actor_kind, actor_id, content_hash, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                decision.decision_id, decision.schema_version,
                decision.task_id, decision.decision_type.value,
                decision.target_ref.artifact_id, decision.outcome.value,
                decision.based_on_task_revision, decision.author_id,
                decision.reason, "AUTHOR", decision.author_id,
                decision.content_hash, "not-a-valid-datetime",
            ),
        )
        conn.commit()
        with pytest.raises(CreationApplicationError) as exc_info:
            repo.get(decision.decision_id)
        assert exc_info.value.__cause__ is not None
        conn.close()
