"""C4A-09..15: v006 durable fact schema and rollback contracts."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from xiaoshuo.infrastructure.persistence.sqlite.c4a_apply_repository import (
    C4aApplyAttempt,
    C4aApplyEvent,
)
from xiaoshuo.infrastructure.persistence.sqlite.connection import get_connection
from xiaoshuo.infrastructure.persistence.sqlite.maintenance import init_database
from xiaoshuo.infrastructure.persistence.sqlite import migration_runner as runner_module
from xiaoshuo.infrastructure.persistence.sqlite.migration_runner import MigrationRunner
from xiaoshuo.infrastructure.persistence.sqlite.settings import SQLitePersistenceSettings
from xiaoshuo.application.creation.errors import CanonApplyRecoveryRequired, IdempotencyConflict
from xiaoshuo.application.creation.canon_apply import CanonApplyCommand, compute_canon_apply_request_digest

from test_c4a_apply import _case, _digest


def _v005(tmp_path: Path):
    settings = SQLitePersistenceSettings(tmp_path / "v005.db", 5000, tmp_path / "backups")
    init_database(settings)
    conn = get_connection(settings)
    original = runner_module._discover_migrations
    runner_module._discover_migrations = lambda: [item for item in original() if item[0] <= 5]
    try:
        MigrationRunner().migrate(conn, settings)
    finally:
        runner_module._discover_migrations = original
    return conn, settings


def _pending(case):
    request_digest = compute_canon_apply_request_digest(
        CanonApplyCommand("task", "journal", 5, apply_key="apply-key")
    )
    attempt = C4aApplyAttempt(
        "attempt", "project", "apply-key", request_digest, "journal", "task", "op", "decision",
        case["base_ref"], "base-v1", _digest((case["root"] / "current.pointer").read_bytes()),
        case["target_ref"], "target-v1", "sha256:" + "f" * 64, "sha256:" + "1" * 64,
        case["target"].manifest_hash, case["target"].world_hash,
        "operator", "2026-08-04T00:00:00+00:00",
    )
    event = C4aApplyEvent("attempt:prepared", "attempt", "project", "PREPARED", "PREPARED", None, None, None, None, None, "2026-08-04T00:00:00+00:00")
    case["repo"].create_prepared(attempt, event)
    case["conn"].commit()
    return attempt


def test_v006_migration_creates_apply_attempt_and_event_schema(tmp_path: Path) -> None:
    case = _case(tmp_path)
    assert case["conn"].execute("PRAGMA user_version").fetchone()[0] == 6
    assert case["conn"].execute("SELECT 1 FROM sqlite_master WHERE name='canon_apply_attempt'").fetchone()
    assert case["conn"].execute("SELECT 1 FROM sqlite_master WHERE name='canon_apply_event'").fetchone()
    attempt_columns = {row[1] for row in case["conn"].execute("PRAGMA table_info(canon_apply_attempt)")}
    event_columns = {row[1] for row in case["conn"].execute("PRAGMA table_info(canon_apply_event)")}
    assert attempt_columns >= {
        "apply_key", "target_version_id", "target_manifest_hash", "target_world_hash",
        "operator_identity",
    }
    assert event_columns >= {
        "observed_pointer_content_hash", "observed_marker_content_hash",
    }
    assert case["conn"].execute(
        "SELECT 1 FROM sqlite_master WHERE name='trg_canon_apply_event_observation_binding'"
    ).fetchone()


def test_v006_composite_fks_reject_cross_project_event(tmp_path: Path) -> None:
    case = _case(tmp_path)
    _pending(case)
    insert_sql = (
        "INSERT INTO canon_apply_attempt ("
        "apply_attempt_id, project_id, apply_key, request_digest, journal_id, task_id, "
        "operation_id, decision_id, base_bundle_ref_artifact_id, base_bundle_schema_version, "
        "base_bundle_content_hash, base_version_id, base_pointer_content_hash, "
        "target_bundle_ref_artifact_id, target_bundle_schema_version, target_bundle_content_hash, "
        "target_version_id, target_pointer_content_hash, target_marker_content_hash, "
        "target_manifest_hash, target_world_hash, operator_identity, created_at) "
        "SELECT ?, ?, ?, request_digest, journal_id, task_id, operation_id, decision_id, "
        "base_bundle_ref_artifact_id, base_bundle_schema_version, base_bundle_content_hash, "
        "base_version_id, base_pointer_content_hash, target_bundle_ref_artifact_id, "
        "target_bundle_schema_version, target_bundle_content_hash, target_version_id, "
        "target_pointer_content_hash, target_marker_content_hash, target_manifest_hash, "
        "target_world_hash, operator_identity, created_at "
        "FROM canon_apply_attempt WHERE apply_attempt_id='attempt'"
    )
    with pytest.raises(sqlite3.IntegrityError, match="binding"):
        case["conn"].execute(insert_sql, ("bad-trigger", "other", "bad-trigger-key"))
    case["conn"].rollback()

    missing_identity_sql = insert_sql.replace(
        "target_pointer_content_hash, target_marker_content_hash, target_manifest_hash, "
        "target_world_hash, operator_identity, created_at ",
        "target_pointer_content_hash, target_marker_content_hash, NULL, NULL, "
        "operator_identity, created_at ",
    )
    with pytest.raises(sqlite3.IntegrityError):
        case["conn"].execute(missing_identity_sql, ("missing-identity", "project", "missing-key"))
    case["conn"].rollback()

    # A physically corrupt graph with all simple FKs satisfied must still be
    # rejected when the repository reads it.  Removing this fixture-only
    # trigger simulates an older v006 database that predates the binding rule.
    case["conn"].execute("DROP TRIGGER trg_canon_apply_attempt_binding")
    case["conn"].execute(insert_sql, ("bad-read", "other", "bad-read-key"))
    case["conn"].commit()
    with pytest.raises(CanonApplyRecoveryRequired, match="binding"):
        case["repo"].get_attempt_by_key("bad-read-key")
    case["conn"].rollback()
    case["conn"].execute("DROP TRIGGER trg_canon_apply_attempt_no_update")
    case["conn"].execute(
        "UPDATE canon_apply_attempt SET target_manifest_hash=? WHERE apply_attempt_id='attempt'",
        ("sha256:" + "9" * 64,),
    )
    with pytest.raises(CanonApplyRecoveryRequired, match="binding"):
        case["repo"].get_attempt_by_key("apply-key")
    case["conn"].rollback()
    with pytest.raises(Exception):
        case["conn"].execute(
            "INSERT INTO canon_apply_event (event_id, apply_attempt_id, project_id, phase, result, created_at) VALUES ('bad','attempt','other','PREPARED','PREPARED','2026-08-04T00:00:00Z')"
        )
    case["conn"].rollback()


def test_v006_attempt_identity_is_unique_and_immutable(tmp_path: Path) -> None:
    case = _case(tmp_path)
    _pending(case)
    with pytest.raises(Exception):
        case["conn"].execute("UPDATE canon_apply_attempt SET apply_key='changed' WHERE apply_attempt_id='attempt'")
    with pytest.raises(Exception):
        case["conn"].execute("DELETE FROM canon_apply_attempt WHERE apply_attempt_id='attempt'")
    with pytest.raises(Exception):
        case["repo"].create_prepared(
            C4aApplyAttempt(
                "other", "project", "apply-key", "sha256:" + "f" * 64, "journal", "task", "op", "decision",
                case["base_ref"], "base-v1", "sha256:" + "1" * 64, case["target_ref"], "target-v1", "sha256:" + "2" * 64, "sha256:" + "3" * 64, case["target"].manifest_hash, case["target"].world_hash, "operator", "2026-08-04T00:00:00Z"
            ),
            C4aApplyEvent("other:prepared", "other", "project", "PREPARED", "PREPARED", None, None, None, None, None, "2026-08-04T00:00:00Z"),
        )
    case["conn"].rollback()


def test_v006_event_phase_result_error_envelope_checks(tmp_path: Path) -> None:
    case = _case(tmp_path)
    _pending(case)
    with pytest.raises(Exception):
        case["conn"].execute("INSERT INTO canon_apply_event (event_id,apply_attempt_id,project_id,phase,result,created_at) VALUES ('bad','attempt','project','UNKNOWN','UNKNOWN','2026-08-04T00:00:00Z')")
    case["conn"].rollback()
    with pytest.raises(Exception):
        case["conn"].execute("INSERT INTO canon_apply_event (event_id,apply_attempt_id,project_id,phase,result,replay_envelope_json,created_at) VALUES ('bad2','attempt','project','PREPARED','PREPARED','{}','2026-08-04T00:00:00Z')")
    case["conn"].rollback()
    target_hashes = case["conn"].execute(
        "SELECT target_pointer_content_hash, target_marker_content_hash "
        "FROM canon_apply_attempt WHERE apply_attempt_id='attempt'"
    ).fetchone()
    with pytest.raises(Exception):
        case["conn"].execute(
            "INSERT INTO canon_apply_event (event_id,apply_attempt_id,project_id,phase,result,"
            "observed_pointer_content_hash,created_at) VALUES ('bad3','attempt','project',"
            "'PROJECTION_COMMITTED','PROJECTION_COMMITTED',?,'2026-08-04T00:00:00Z')",
            (target_hashes[0],),
        )
    case["conn"].rollback()
    with pytest.raises(Exception):
        case["conn"].execute(
            "INSERT INTO canon_apply_event (event_id,apply_attempt_id,project_id,phase,result,"
            "observed_pointer_content_hash,observed_marker_content_hash,created_at) "
            "VALUES ('bad4','attempt','project','PROJECTION_COMMITTED','PROJECTION_COMMITTED',?,?,"
            "'2026-08-04T00:00:00Z')",
            ("sha256:" + "z" * 64, target_hashes[1]),
        )
    case["conn"].rollback()
    with pytest.raises(Exception):
        case["conn"].execute(
            "INSERT INTO canon_apply_event (event_id,apply_attempt_id,project_id,phase,result,"
            "observed_pointer_content_hash,observed_marker_content_hash,created_at) "
            "VALUES ('bad5','attempt','project','PROJECTION_COMMITTED','PROJECTION_COMMITTED',?,?,"
            "'2026-08-04T00:00:00Z')",
            ("sha256:" + "e" * 64, target_hashes[1]),
        )
    case["conn"].rollback()


def test_v006_append_only_triggers_block_update_delete(tmp_path: Path) -> None:
    case = _case(tmp_path)
    _pending(case)
    with pytest.raises(Exception):
        case["conn"].execute("UPDATE canon_apply_event SET result='PREPARED' WHERE event_id='attempt:prepared'")
    with pytest.raises(Exception):
        case["conn"].execute("DELETE FROM canon_apply_event WHERE event_id='attempt:prepared'")
    case["conn"].rollback()


def test_v006_migration_preflight_fails_before_ddl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    conn, settings = _v005(tmp_path)
    original = runner_module._execute_sql_statements

    def fail_before_v006(connection, sql_text):
        if "canon_apply_attempt" in sql_text:
            raise RuntimeError("v006 preflight fixture failure")
        return original(connection, sql_text)

    monkeypatch.setattr(runner_module, "_execute_sql_statements", fail_before_v006)
    with pytest.raises(RuntimeError, match="preflight"):
        MigrationRunner().migrate(conn, settings)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
    assert conn.execute("SELECT MAX(version) FROM creation_schema_migration").fetchone()[0] == 5
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='canon_apply_attempt'").fetchone() is None


def test_v006_migration_rollback_preserves_v005_user_version_and_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    conn, settings = _v005(tmp_path)
    original = runner_module._verify_v006_schema
    monkeypatch.setattr(runner_module, "_verify_v006_schema", lambda connection: (_ for _ in ()).throw(RuntimeError("v006 preflight schema failure")))
    with pytest.raises(RuntimeError, match="preflight"):
        MigrationRunner().migrate(conn, settings)
    monkeypatch.setattr(runner_module, "_verify_v006_schema", original)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
    assert [row[0] for row in conn.execute("SELECT version FROM creation_schema_migration ORDER BY version")] == [1, 2, 3, 4, 5]
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='canon_apply_event'").fetchone() is None
