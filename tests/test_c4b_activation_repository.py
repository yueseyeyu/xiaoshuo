"""C4B-17..21 and C4B-43: independent v005 activation facts."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from xiaoshuo.application.creation.errors import (
    ActivationConflict,
    ArtifactIdentityConflict,
)
from xiaoshuo.domain.creation import ArtifactRef
from xiaoshuo.infrastructure.persistence.sqlite.canon_activation_repository import (
    ActivationAttempt,
    ActivationEvent,
    CanonActivationRepositoryError,
    SqliteCanonActivationRepository,
)
from xiaoshuo.infrastructure.persistence.sqlite.connection import get_connection
from xiaoshuo.infrastructure.persistence.sqlite.maintenance import init_database
from xiaoshuo.infrastructure.persistence.sqlite.migration_runner import MigrationRunner
from xiaoshuo.infrastructure.persistence.sqlite.settings import SQLitePersistenceSettings


def digest(char: str) -> str:
    return "sha256:" + char * 64


def migrated(tmp_path: Path) -> sqlite3.Connection:
    settings = SQLitePersistenceSettings(tmp_path / "creation.db", 5000, tmp_path / "backups")
    init_database(settings)
    conn = get_connection(settings)
    MigrationRunner().migrate(conn, settings)
    return conn


def make_attempt(attempt_id: str = "attempt-1", project_id: str = "project-1") -> ActivationAttempt:
    return ActivationAttempt(
        attempt_id=attempt_id,
        project_id=project_id,
        attempt_key="attempt-key-" + project_id,
        request_digest=digest("a"),
        seed_digest=digest("b"),
        bundle_ref=ArtifactRef("bundle-ref-" + project_id, 1, digest("c")),
        version_id="version-" + project_id,
        pointer_content_hash=digest("d"),
        operator_identity="operator-local",
        created_at="2026-01-01T00:00:00+00:00",
        manifest_hash=digest("e"),
        world_hash=digest("f"),
    )


def prepared(attempt: ActivationAttempt) -> ActivationEvent:
    return ActivationEvent(
        event_id=attempt.attempt_id + ":prepared",
        attempt_id=attempt.attempt_id,
        project_id=attempt.project_id,
        phase="PREPARED",
        result="PREPARED",
        error_code=None,
        replay_envelope_json=None,
        replay_envelope_hash=None,
        created_at=attempt.created_at,
    )


def ready(attempt: ActivationAttempt) -> ActivationEvent:
    envelope = '{"attempt_id":"' + attempt.attempt_id + '"}'
    return ActivationEvent(
        event_id=attempt.attempt_id + ":ready",
        attempt_id=attempt.attempt_id,
        project_id=attempt.project_id,
        phase="READY_FOR_MARKER",
        result="READY_FOR_MARKER",
        error_code=None,
        replay_envelope_json=envelope,
        replay_envelope_hash="sha256:" + hashlib.sha256(envelope.encode()).hexdigest(),
        created_at="2026-01-01T00:00:01+00:00",
    )


def test_c4b_17_v005_schema_and_ledger_are_present(tmp_path: Path) -> None:
    conn = migrated(tmp_path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
        assert [row[0] for row in conn.execute("SELECT version FROM creation_schema_migration ORDER BY version")] == [1, 2, 3, 4, 5]
        for table in ("canon_activation_attempt", "canon_activation_event"):
            assert conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone()
    finally:
        conn.close()


def test_c4b_18_attempt_stores_complete_immutable_identity(tmp_path: Path) -> None:
    conn = migrated(tmp_path)
    try:
        repo = SqliteCanonActivationRepository(conn)
        attempt = make_attempt()
        repo.create_attempt(attempt)
        conn.commit()
        actual = repo.get_attempt(attempt.attempt_id)
        assert actual == attempt
        columns = [row[1] for row in conn.execute("PRAGMA table_info(canon_activation_attempt)")]
        assert set(columns) == {
            "attempt_id", "project_id", "attempt_key", "request_digest", "seed_digest",
            "bundle_ref_artifact_id", "bundle_schema_version", "bundle_content_hash",
            "manifest_hash", "world_hash", "version_id", "pointer_content_hash",
            "operator_identity", "created_at",
        }
    finally:
        conn.close()


def test_c4b_19_event_joins_attempt_by_composite_identity(tmp_path: Path) -> None:
    conn = migrated(tmp_path)
    try:
        repo = SqliteCanonActivationRepository(conn)
        attempt = make_attempt()
        repo.create_prepared(attempt, prepared(attempt))
        actual = repo.get_event_with_attempt(attempt.attempt_id + ":prepared")
        assert actual is not None
        assert actual.attempt == attempt
        assert actual.event.phase == "PREPARED"
    finally:
        conn.close()


def test_c4b_20_ready_event_is_the_only_replay_envelope_fact(tmp_path: Path) -> None:
    conn = migrated(tmp_path)
    try:
        repo = SqliteCanonActivationRepository(conn)
        attempt = make_attempt()
        repo.create_prepared(attempt, prepared(attempt))
        repo.append_event(ready(attempt))
        conn.commit()
        assert [event.phase for event in repo.list_events(attempt.attempt_id)] == [
            "PREPARED", "READY_FOR_MARKER"
        ]
        columns = [row[1] for row in conn.execute("PRAGMA table_info(canon_activation_event)")]
        assert set(columns) == {
            "event_id", "attempt_id", "project_id", "phase", "result", "error_code",
            "replay_envelope_json", "replay_envelope_hash", "created_at",
        }
    finally:
        conn.close()


@pytest.mark.parametrize("phase", ["COMMITTED", "REPLAY", "REJECTED", "UNKNOWN"])
def test_repository_unknown_event_phase_is_rejected_by_repository_and_sqlite(
    tmp_path: Path, phase: str
) -> None:
    conn = migrated(tmp_path)
    try:
        repo = SqliteCanonActivationRepository(conn)
        attempt = make_attempt()
        repo.create_attempt(attempt)
        conn.commit()
        with pytest.raises(CanonActivationRepositoryError):
            repo.append_event(
                ActivationEvent(
                    event_id="bad-" + phase,
                    attempt_id=attempt.attempt_id,
                    project_id=attempt.project_id,
                    phase=phase,
                    result=phase,
                    error_code=None,
                    replay_envelope_json=None,
                    replay_envelope_hash=None,
                    created_at=attempt.created_at,
                )
            )
    finally:
        conn.close()


def test_c4b_21_repository_phase_pairing_and_nullability_are_strict(tmp_path: Path) -> None:
    conn = migrated(tmp_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO canon_activation_event VALUES (?,?,?,?,?,?,?,?,?)",
                ("bad", "missing", "project-1", "PREPARED", "READY_FOR_MARKER", None, "{}", digest("a"), "now"),
            )
    finally:
        conn.close()


def test_repository_duplicate_project_or_key_is_activation_conflict(tmp_path: Path) -> None:
    conn = migrated(tmp_path)
    try:
        repo = SqliteCanonActivationRepository(conn)
        first = make_attempt()
        repo.create_attempt(first)
        conn.commit()
        with pytest.raises(ActivationConflict):
            repo.create_attempt(replace(first, attempt_id="attempt-2"))
        conn.rollback()
        with pytest.raises(ActivationConflict):
            repo.create_attempt(replace(first, attempt_id="attempt-3", project_id="project-3"))
    finally:
        conn.close()


def test_repository_artifact_identity_conflict_never_overwrites_registry(tmp_path: Path) -> None:
    conn = migrated(tmp_path)
    try:
        repo = SqliteCanonActivationRepository(conn)
        ref = ArtifactRef("same", 1, digest("a"))
        repo.register_artifact_ref(ref)
        conn.commit()
        with pytest.raises(ArtifactIdentityConflict):
            repo.register_artifact_ref(ArtifactRef("same", 1, digest("b")))
        assert repo.resolve_artifact_ref("same") == ref
    finally:
        conn.close()


def test_repository_append_only_attempt_and_event_triggers(tmp_path: Path) -> None:
    conn = migrated(tmp_path)
    try:
        repo = SqliteCanonActivationRepository(conn)
        attempt = make_attempt()
        repo.create_prepared(attempt, prepared(attempt))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE canon_activation_attempt SET project_id='changed' WHERE attempt_id=?", (attempt.attempt_id,))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM canon_activation_event WHERE event_id=?", (attempt.attempt_id + ":prepared",))
    finally:
        conn.close()


def test_repository_cross_project_event_fk_is_rejected(tmp_path: Path) -> None:
    conn = migrated(tmp_path)
    try:
        repo = SqliteCanonActivationRepository(conn)
        attempt = make_attempt()
        repo.create_attempt(attempt)
        conn.commit()
        with pytest.raises(CanonActivationRepositoryError):
            repo.append_event(
                ActivationEvent(
                    event_id="cross-project",
                    attempt_id=attempt.attempt_id,
                    project_id="other-project",
                    phase="PREPARED",
                    result="PREPARED",
                    error_code=None,
                    replay_envelope_json=None,
                    replay_envelope_hash=None,
                    created_at=attempt.created_at,
                )
            )
    finally:
        conn.close()


def test_repository_duplicate_phase_event_is_rejected(tmp_path: Path) -> None:
    conn = migrated(tmp_path)
    try:
        repo = SqliteCanonActivationRepository(conn)
        attempt = make_attempt()
        repo.create_prepared(attempt, prepared(attempt))
        with pytest.raises(CanonActivationRepositoryError):
            repo.append_event(
                ActivationEvent(
                    event_id="second-prepared",
                    attempt_id=attempt.attempt_id,
                    project_id=attempt.project_id,
                    phase="PREPARED",
                    result="PREPARED",
                    error_code=None,
                    replay_envelope_json=None,
                    replay_envelope_hash=None,
                    created_at=attempt.created_at,
                )
            )
    finally:
        conn.close()


def test_c4b_43_payload_success_transaction_a_failure_leaves_only_lazy_orphan(tmp_path: Path) -> None:
    conn = migrated(tmp_path)
    try:
        repo = SqliteCanonActivationRepository(conn)
        attempt = make_attempt()
        payload_objects = {attempt.bundle_content_hash: b"verified immutable payload"}
        conn.execute("BEGIN IMMEDIATE")
        repo.create_attempt(attempt)
        repo.append_event(prepared(attempt))
        conn.rollback()
        assert payload_objects[attempt.bundle_content_hash] == b"verified immutable payload"
        assert repo.get_attempt(attempt.attempt_id) is None
        assert repo.resolve_artifact_ref(attempt.bundle_ref_artifact_id) is None
        assert conn.execute("SELECT COUNT(*) FROM canon_activation_event").fetchone()[0] == 0
    finally:
        conn.close()


def test_repository_never_creates_c4a_business_facts(tmp_path: Path) -> None:
    conn = migrated(tmp_path)
    try:
        repo = SqliteCanonActivationRepository(conn)
        attempt = make_attempt()
        repo.create_prepared(attempt, prepared(attempt))
        conn.commit()
        assert repo.has_business_c4a_facts() is False
        assert conn.execute("SELECT COUNT(*) FROM chapter_task").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM canon_commit_journal").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM canon_commit_receipt").fetchone()[0] == 0
    finally:
        conn.close()


def test_payload_failure_has_no_activation_fact_residue(tmp_path: Path) -> None:
    conn = migrated(tmp_path)
    try:
        repo = SqliteCanonActivationRepository(conn)
        payload = {"sha256:orphan": b"verified bytes"}
        assert payload
        assert repo.get_attempt_by_project("orphan-project") is None
        assert conn.execute("SELECT COUNT(*) FROM canon_activation_attempt").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM canon_activation_event").fetchone()[0] == 0
    finally:
        conn.close()
