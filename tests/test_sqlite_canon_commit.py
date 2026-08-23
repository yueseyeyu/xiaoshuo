"""C1 v003 schema and Canon persistence read boundary."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import shutil

import pytest

from xiaoshuo.infrastructure.persistence.sqlite.connection import get_connection
from xiaoshuo.infrastructure.persistence.sqlite.maintenance import init_database
from xiaoshuo.infrastructure.persistence.sqlite.migration_runner import MigrationRunner
from xiaoshuo.infrastructure.persistence.sqlite.settings import SQLitePersistenceSettings
from xiaoshuo.infrastructure.persistence.sqlite.canon_commit_repository import SqliteCanonCommitRepository
from xiaoshuo.infrastructure.persistence.sqlite.repository import SqliteChapterTaskRepository
from xiaoshuo.application.creation.errors import ArtifactIdentityConflict, LegacyJournalUnbound, RevisionConflict, UnsupportedPersistenceBoundary
from xiaoshuo.application.creation.repository import CanonCommitIntentRecord
from xiaoshuo.domain.creation import ArtifactRef, ChapterTask, ChapterTaskStatus


HASH = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def _connection(tmp_path: Path):
    settings = SQLitePersistenceSettings(str(tmp_path / "canon.db"), 5000, str(tmp_path / "backups"))
    init_database(settings)
    conn = get_connection(settings)
    MigrationRunner().migrate(conn, settings)
    return conn


def _insert_journal(conn, *, journal="journal", task="task", operation="op", decision="decision", base_hash=HASH, target_hash=HASH):
    conn.execute("INSERT OR IGNORE INTO creation_artifact_ref VALUES ('base-bundle',1,?)", (base_hash,))
    conn.execute(
        "INSERT INTO canon_commit_journal (journal_id,task_id,operation_id,decision_id,changeset_ref_artifact_id,base_bundle_ref_artifact_id,target_bundle_ref_artifact_id,base_bundle_content_hash,target_bundle_content_hash,base_manifest_hash,base_world_hash,target_manifest_hash,target_world_hash,canonical_bundle_schema_version,created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (journal, task, operation, decision, "changeset", "base-bundle", "bundle", base_hash, target_hash, base_hash, base_hash, target_hash, target_hash, 1, "2026-01-01T00:00:00+00:00"),
    )


def test_v003_uses_receipt_fk_and_keeps_foreign_keys_enabled(tmp_path: Path) -> None:
    conn = _connection(tmp_path)
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        cols = [row["name"] for row in conn.execute("PRAGMA table_info(chapter_task)")]
        assert "commit_receipt_ref_artifact_id" in cols
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()

def test_v003_rebuild_preserves_v002_child_foreign_keys(tmp_path: Path, monkeypatch) -> None:
    import xiaoshuo.infrastructure.persistence.sqlite.migration_runner as runner_module
    migrations = tmp_path / "migrations"
    shutil.copytree(Path(runner_module.__file__).resolve().parent / "migrations", migrations)
    (migrations / "v003_canon_mvp.sql").unlink()
    (migrations / "v004_canon_bundle_identity.sql").unlink()
    monkeypatch.setattr(runner_module, "_MIGRATIONS_DIR", migrations)
    settings = SQLitePersistenceSettings(str(tmp_path / "upgrade.db"), 5000, str(tmp_path / "backups"))
    init_database(settings)
    conn = get_connection(settings)
    try:
        MigrationRunner().migrate(conn, settings)
        conn.execute("INSERT INTO creation_artifact_ref VALUES ('intent', 1, ?)", (HASH,))
        conn.execute("INSERT INTO chapter_task (task_id,schema_version,aggregate_revision,project_id,chapter_number,status,last_stable_status,creative_intent_ref_artifact_id,created_at,updated_at) VALUES ('task',1,0,'project',1,'PLAN_PREPARING','PLAN_PREPARING','intent','2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00')")
        conn.commit()
    finally:
        conn.close()

    shutil.copy2(Path(__file__).resolve().parents[1] / "src/xiaoshuo/infrastructure/persistence/sqlite/migrations/v003_canon_mvp.sql", migrations / "v003_canon_mvp.sql")
    conn = get_connection(settings)
    try:
        MigrationRunner().migrate(conn, settings)
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("SELECT task_id FROM chapter_task").fetchone()[0] == "task"
    finally:
        conn.close()


def test_v003_child_fk_declarations_still_target_chapter_task(tmp_path: Path) -> None:
    conn = _connection(tmp_path)
    try:
        for table in (
            "creation_audit_event",
            "creation_author_decision",
            "creation_decision_consumption",
        ):
            parents = {row["table"] for row in conn.execute(f"PRAGMA foreign_key_list({table})")}
            assert "chapter_task" in parents
    finally:
        conn.close()


def test_v003_missing_backup_dir_fails_before_rebuild(tmp_path: Path, monkeypatch) -> None:
    import xiaoshuo.infrastructure.persistence.sqlite.migration_runner as runner_module
    migrations = tmp_path / "migrations"
    shutil.copytree(Path(runner_module.__file__).resolve().parent / "migrations", migrations)
    (migrations / "v003_canon_mvp.sql").unlink()
    (migrations / "v004_canon_bundle_identity.sql").unlink()
    monkeypatch.setattr(runner_module, "_MIGRATIONS_DIR", migrations)
    initial = SQLitePersistenceSettings(str(tmp_path / "upgrade.db"), 5000, str(tmp_path / "backups"))
    init_database(initial)
    conn = get_connection(initial)
    MigrationRunner().migrate(conn, initial)
    conn.close()
    shutil.copy2(Path(__file__).resolve().parents[1] / "src/xiaoshuo/infrastructure/persistence/sqlite/migrations/v003_canon_mvp.sql", migrations / "v003_canon_mvp.sql")
    missing_backup = SQLitePersistenceSettings(str(tmp_path / "upgrade.db"), 5000, None)
    conn = get_connection(missing_backup)
    try:
        import pytest
        with pytest.raises(ValueError, match="backup_dir"):
            MigrationRunner().migrate(conn, missing_backup)
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert [row["version"] for row in conn.execute("SELECT version FROM creation_schema_migration ORDER BY version")] == [1, 2]
    finally:
        conn.close()


def test_v003_failure_rolls_back_schema_ledger_and_foreign_keys(tmp_path: Path, monkeypatch) -> None:
    import pytest
    import xiaoshuo.infrastructure.persistence.sqlite.migration_runner as runner_module
    migrations = tmp_path / "migrations"
    shutil.copytree(Path(runner_module.__file__).resolve().parent / "migrations", migrations)
    (migrations / "v003_canon_mvp.sql").unlink()
    (migrations / "v004_canon_bundle_identity.sql").unlink()
    monkeypatch.setattr(runner_module, "_MIGRATIONS_DIR", migrations)
    settings = SQLitePersistenceSettings(str(tmp_path / "failure.db"), 5000, str(tmp_path / "backups"))
    init_database(settings)
    conn = get_connection(settings)
    MigrationRunner().migrate(conn, settings)
    conn.close()
    (migrations / "v003_canon_mvp.sql").write_text("CREATE TABLE partial_v003 (id INTEGER) STRICT;\nNOT SQL;", encoding="utf-8")
    conn = get_connection(settings)
    try:
        with pytest.raises(Exception):
            MigrationRunner().migrate(conn, settings)
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='partial_v003'").fetchone() is None
        assert [row["version"] for row in conn.execute("SELECT version FROM creation_schema_migration ORDER BY version")] == [1, 2]
        assert len(conn.execute("PRAGMA table_info(chapter_task)").fetchall()) == 19
    finally:
        conn.close()


def test_v003_schema_validation_failure_rolls_back_before_commit(tmp_path: Path, monkeypatch) -> None:
    import xiaoshuo.infrastructure.persistence.sqlite.migration_runner as runner_module

    migrations = tmp_path / "migrations"
    shutil.copytree(Path(runner_module.__file__).resolve().parent / "migrations", migrations)
    (migrations / "v003_canon_mvp.sql").unlink()
    (migrations / "v004_canon_bundle_identity.sql").unlink()
    monkeypatch.setattr(runner_module, "_MIGRATIONS_DIR", migrations)
    settings = SQLitePersistenceSettings(str(tmp_path / "postcheck.db"), 5000, str(tmp_path / "backups"))
    init_database(settings)
    conn = get_connection(settings)
    try:
        MigrationRunner().migrate(conn, settings)
    finally:
        conn.close()

    shutil.copy2(
        Path(__file__).resolve().parents[1]
        / "src/xiaoshuo/infrastructure/persistence/sqlite/migrations/v003_canon_mvp.sql",
        migrations / "v003_canon_mvp.sql",
    )

    def fail_schema_validation(_conn) -> None:
        raise RuntimeError("forced schema validation failure")

    monkeypatch.setattr(runner_module, "_verify_v003_schema", fail_schema_validation)
    conn = get_connection(settings)
    try:
        with pytest.raises(RuntimeError, match="forced schema validation failure"):
            MigrationRunner().migrate(conn, settings)
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        assert [row["version"] for row in conn.execute(
            "SELECT version FROM creation_schema_migration ORDER BY version"
        )] == [1, 2]
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='chapter_task_v002_legacy'").fetchone() is None
        assert len(conn.execute("PRAGMA table_info(chapter_task)").fetchall()) == 19
    finally:
        conn.close()


def test_v003_executor_rejects_unexpected_v003_file(tmp_path: Path, monkeypatch) -> None:
    import pytest
    import xiaoshuo.infrastructure.persistence.sqlite.migration_runner as runner_module
    migrations = tmp_path / "migrations"
    shutil.copytree(Path(runner_module.__file__).resolve().parent / "migrations", migrations)
    (migrations / "v003_canon_mvp.sql").unlink()
    (migrations / "v004_canon_bundle_identity.sql").unlink()
    (migrations / "v003_unrelated.sql").write_text("CREATE TABLE forbidden_v003 (id INTEGER) STRICT;", encoding="utf-8")
    monkeypatch.setattr(runner_module, "_MIGRATIONS_DIR", migrations)
    settings = SQLitePersistenceSettings(str(tmp_path / "misuse.db"), 5000, str(tmp_path / "backups"))
    init_database(settings)
    conn = get_connection(settings)
    try:
        with pytest.raises(RuntimeError, match="reserved"):
            MigrationRunner().migrate(conn, settings)
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='forbidden_v003'").fetchone() is None
    finally:
        conn.close()
def test_canon_commit_repository_is_intent_only_and_reads_receipt(tmp_path: Path) -> None:
    conn = _connection(tmp_path)
    try:
        conn.execute("INSERT INTO creation_artifact_ref VALUES (?, ?, ?)", ("intent", 1, HASH))
        conn.execute("INSERT INTO creation_artifact_ref VALUES (?, ?, ?)", ("receipt-ref", 1, HASH))
        conn.execute("INSERT INTO creation_artifact_ref VALUES (?, ?, ?)", ("changeset", 1, HASH))
        conn.execute("INSERT INTO creation_artifact_ref VALUES (?, ?, ?)", ("bundle", 1, HASH))
        conn.execute("INSERT INTO chapter_task (task_id,schema_version,aggregate_revision,project_id,chapter_number,status,last_stable_status,creative_intent_ref_artifact_id,created_at,updated_at) VALUES ('task',1,0,'project',1,'PLAN_PREPARING','PLAN_PREPARING','intent','2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00')")
        conn.execute("INSERT INTO creation_operation VALUES ('op','key','digest','{}',?, '2026-01-01T00:00:00+00:00')", (HASH,))
        conn.execute("INSERT INTO creation_author_decision VALUES ('decision',1,'task','APPROVE_CHANGESET','changeset','APPROVE',0,'author',NULL,'AUTHOR','author',?,'2026-01-01T00:00:00+00:00')", (HASH,))
        conn.execute("INSERT INTO creation_decision_consumption VALUES ('consumption','decision','op','task',0,'2026-01-01T00:00:00+00:00')")
        _insert_journal(conn)
        conn.execute("INSERT INTO canon_commit_receipt VALUES ('receipt','journal','receipt-ref','2026-01-01T00:00:00+00:00')")
        view = SqliteCanonCommitRepository(conn).get_receipt("receipt")
        assert view is not None and view.receipt_ref_artifact_id == "receipt-ref"
        # C4a exposes only the specialized Apply/Recovery persistence boundary;
        # no generic completion, recovery, or projection-apply entry is added.
        assert hasattr(SqliteCanonCommitRepository, "create_intent")
        assert not hasattr(SqliteCanonCommitRepository, "complete")
        assert not hasattr(SqliteCanonCommitRepository, "recover")
        assert not hasattr(SqliteCanonCommitRepository, "apply")
        trace = conn.execute(
            "SELECT j.task_id, j.decision_id, c.operation_id FROM canon_commit_receipt r "
            "JOIN canon_commit_journal j ON j.journal_id = r.journal_id "
            "JOIN creation_decision_consumption c ON c.operation_id = j.operation_id "
            "WHERE r.receipt_id = 'receipt'"
        ).fetchone()
        assert tuple(trace) == ("task", "decision", "op")
        journal_view = SqliteCanonCommitRepository(conn).get_journal("journal")
        assert journal_view is not None
        conn.execute("DROP TRIGGER trg_canon_commit_journal_no_update")
        conn.execute("UPDATE canon_commit_journal SET base_bundle_content_hash=? WHERE journal_id='journal'", (HASH_B,))
        with pytest.raises(ArtifactIdentityConflict, match="content identity"):
            SqliteCanonCommitRepository(conn).get_journal("journal")
        assert {row["from"] for row in conn.execute("PRAGMA foreign_key_list(canon_commit_journal)")} >= {
            "decision_id", "changeset_ref_artifact_id", "target_bundle_ref_artifact_id"
        }
        conn.execute("INSERT INTO creation_operation VALUES ('op-2','key-2','digest','{}',?, '2026-01-01T00:00:00+00:00')", (HASH,))
        with pytest.raises(Exception, match="canon_commit_journal.decision_id"):
            _insert_journal(conn, journal="journal-2", operation="op-2")
    finally:
        conn.close()


def test_canon_journal_and_receipt_are_append_only(tmp_path: Path) -> None:
    conn = _connection(tmp_path)
    try:
        conn.execute("INSERT INTO creation_artifact_ref VALUES ('intent', 1, ?)", (HASH,))
        conn.execute("INSERT INTO creation_artifact_ref VALUES ('receipt-ref', 1, ?)", (HASH,))
        conn.execute("INSERT INTO creation_artifact_ref VALUES ('changeset', 1, ?)", (HASH,))
        conn.execute("INSERT INTO creation_artifact_ref VALUES ('bundle', 1, ?)", (HASH,))
        conn.execute("INSERT INTO chapter_task (task_id,schema_version,aggregate_revision,project_id,chapter_number,status,last_stable_status,creative_intent_ref_artifact_id,created_at,updated_at) VALUES ('task',1,0,'project',1,'PLAN_PREPARING','PLAN_PREPARING','intent','2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00')")
        conn.execute("INSERT INTO creation_operation VALUES ('op','key','digest','{}',?, '2026-01-01T00:00:00+00:00')", (HASH,))
        conn.execute("INSERT INTO creation_author_decision VALUES ('decision',1,'task','APPROVE_CHANGESET','changeset','APPROVE',0,'author',NULL,'AUTHOR','author',?,'2026-01-01T00:00:00+00:00')", (HASH,))
        conn.execute("INSERT INTO creation_decision_consumption VALUES ('consumption','decision','op','task',0,'2026-01-01T00:00:00+00:00')")
        _insert_journal(conn)
        conn.execute("INSERT INTO canon_commit_receipt VALUES ('receipt','journal','receipt-ref','2026-01-01T00:00:00+00:00')")
        for statement in (
            "UPDATE canon_commit_journal SET target_bundle_content_hash='other' WHERE journal_id='journal'",
            "DELETE FROM canon_commit_journal WHERE journal_id='journal'",
            "UPDATE canon_commit_receipt SET created_at='other' WHERE receipt_id='receipt'",
            "DELETE FROM canon_commit_receipt WHERE receipt_id='receipt'",
        ):
            with pytest.raises(Exception, match="append-only"):
                conn.execute(statement)
    finally:
        conn.close()


def test_generic_task_repository_reconstructs_receipt_but_has_no_receipt_write(tmp_path: Path) -> None:
    conn = _connection(tmp_path)
    try:
        conn.execute("INSERT INTO creation_artifact_ref VALUES ('intent', 1, ?)", (HASH,))
        conn.execute("INSERT INTO creation_artifact_ref VALUES ('receipt-ref', 1, ?)", (HASH,))
        conn.execute("INSERT INTO chapter_task (task_id,schema_version,aggregate_revision,project_id,chapter_number,status,last_stable_status,creative_intent_ref_artifact_id,commit_receipt_ref_artifact_id,created_at,updated_at) VALUES ('completed',1,1,'project',1,'COMPLETED','COMMITTING','intent','receipt-ref','2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00')")
        task = SqliteChapterTaskRepository(conn).get("completed")
        assert task is not None and task.commit_receipt_ref is not None
        assert task.commit_receipt_ref.artifact_id == "receipt-ref"
    finally:
        conn.close()


def test_canon_intent_rejects_mismatched_pending_ref_without_residue(tmp_path: Path) -> None:
    conn = _connection(tmp_path)
    now = datetime.now(timezone.utc)
    ref_b = ArtifactRef("changeset-b", 1, HASH)
    base = ArtifactRef("base-b", 1, HASH)
    target = ArtifactRef("bundle-b", 1, HASH)
    try:
        for artifact_id in ("intent", "plan", "draft", "review-target", "adopted", "review", "changeset-a"):
            conn.execute("INSERT INTO creation_artifact_ref VALUES (?, ?, ?)", (artifact_id, 1, HASH))
        conn.execute(
            "INSERT INTO chapter_task (task_id,schema_version,aggregate_revision,project_id,chapter_number,status,last_stable_status,creative_intent_ref_artifact_id,confirmed_plan_ref_artifact_id,current_author_draft_ref_artifact_id,review_target_draft_ref_artifact_id,adopted_draft_ref_artifact_id,latest_review_ref_artifact_id,pending_changeset_ref_artifact_id,created_at,updated_at) "
            "VALUES ('task-mismatch',1,5,'project',1,'CHANGESET_APPROVAL_PENDING','CHANGESET_APPROVAL_PENDING','intent','plan','draft','review-target','adopted','review','changeset-a',?,?)",
            (now.isoformat(), now.isoformat()),
        )
        conn.commit()
        transitioned = ChapterTask(
            task_id="task-mismatch", schema_version=1, aggregate_revision=6,
            project_id="project", chapter_number=1,
            status=ChapterTaskStatus.COMMITTING,
            last_stable_status=ChapterTaskStatus.COMMITTING,
            creative_intent_ref=ArtifactRef("intent", 1, HASH),
            confirmed_plan_ref=ArtifactRef("plan", 1, HASH),
            current_author_draft_ref=ArtifactRef("draft", 1, HASH),
            review_target_draft_ref=ArtifactRef("review-target", 1, HASH),
            adopted_draft_ref=ArtifactRef("adopted", 1, HASH),
            latest_review_ref=ArtifactRef("review", 1, HASH),
            pending_changeset_ref=ref_b, commit_receipt_ref=None,
            recovery=None, created_at=now, updated_at=now,
        )
        record = CanonCommitIntentRecord(
            journal_id="journal-mismatch", task_id="task-mismatch", operation_id="operation-mismatch",
            decision_id="decision-mismatch", changeset_ref=ref_b, base_bundle_ref=base,
            target_bundle_ref=target, base_bundle_content_hash=HASH,
            target_bundle_content_hash=HASH, base_manifest_hash=HASH,
            base_world_hash=HASH, target_manifest_hash=HASH, target_world_hash=HASH,
            canonical_bundle_schema_version=1, created_at=now.isoformat(),
        )
        with pytest.raises(RevisionConflict):
            SqliteCanonCommitRepository(conn).create_intent(record, transitioned, expected_revision=5)
        conn.rollback()
        row = conn.execute(
            "SELECT status, aggregate_revision, pending_changeset_ref_artifact_id FROM chapter_task WHERE task_id='task-mismatch'"
        ).fetchone()
        assert tuple(row) == ("CHANGESET_APPROVAL_PENDING", 5, "changeset-a")
        assert conn.execute("SELECT COUNT(*) FROM canon_commit_journal").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM creation_artifact_ref WHERE artifact_id='changeset-b'").fetchone()[0] == 0
    finally:
        conn.close()


def test_legacy_journal_is_never_returned_as_active(tmp_path: Path) -> None:
    conn = _connection(tmp_path)
    try:
        for artifact_id in ("changeset", "bundle", "receipt-ref", "intent"):
            conn.execute("INSERT INTO creation_artifact_ref VALUES (?, 1, ?)", (artifact_id, HASH))
        conn.execute("INSERT INTO chapter_task (task_id,schema_version,aggregate_revision,project_id,chapter_number,status,last_stable_status,creative_intent_ref_artifact_id,created_at,updated_at) VALUES ('task',1,0,'project',1,'PLAN_PREPARING','PLAN_PREPARING','intent','2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00')")
        conn.execute("INSERT INTO creation_operation VALUES ('op','key','digest','{}',?, '2026-01-01T00:00:00+00:00')", (HASH,))
        conn.execute("INSERT INTO creation_author_decision VALUES ('decision',1,'task','APPROVE_CHANGESET','changeset','APPROVE',0,'author',NULL,'AUTHOR','author',?,'2026-01-01T00:00:00+00:00')", (HASH,))
        conn.execute("INSERT INTO creation_decision_consumption VALUES ('consumption','decision','op','task',0,'2026-01-01T00:00:00+00:00')")
        conn.execute(
            "INSERT INTO canon_commit_journal_v003_legacy (journal_id,task_id,operation_id,decision_id,changeset_ref_artifact_id,target_bundle_ref_artifact_id,bundle_hash,base_manifest_hash,target_manifest_hash,created_at,legacy_status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("legacy-journal", "task", "op", "decision", "changeset", "bundle", HASH, HASH, HASH, "2026-01-01T00:00:00+00:00", "UNBOUND_LEGACY"),
        )
        conn.commit()
        with pytest.raises(LegacyJournalUnbound, match="active"):
            SqliteCanonCommitRepository(conn).get_journal("legacy-journal")
    finally:
        conn.close()


def _pending_intent_fixture(conn):
    now = datetime.now(timezone.utc)
    ids = ("intent", "plan", "draft", "review-target", "adopted", "review", "changeset")
    for artifact_id in ids:
        conn.execute("INSERT INTO creation_artifact_ref VALUES (?, 1, ?)", (artifact_id, HASH))
    conn.execute(
        "INSERT INTO chapter_task (task_id,schema_version,aggregate_revision,project_id,chapter_number,status,last_stable_status,creative_intent_ref_artifact_id,confirmed_plan_ref_artifact_id,current_author_draft_ref_artifact_id,review_target_draft_ref_artifact_id,adopted_draft_ref_artifact_id,latest_review_ref_artifact_id,pending_changeset_ref_artifact_id,created_at,updated_at) VALUES ('task-intent',1,5,'project',1,'CHANGESET_APPROVAL_PENDING','CHANGESET_APPROVAL_PENDING','intent','plan','draft','review-target','adopted','review','changeset',?,?)",
        (now.isoformat(), now.isoformat()),
    )
    transitioned = ChapterTask(
        task_id="task-intent", schema_version=1, aggregate_revision=6,
        project_id="project", chapter_number=1, status=ChapterTaskStatus.COMMITTING,
        last_stable_status=ChapterTaskStatus.COMMITTING,
        creative_intent_ref=ArtifactRef("intent", 1, HASH),
        confirmed_plan_ref=ArtifactRef("plan", 1, HASH),
        current_author_draft_ref=ArtifactRef("draft", 1, HASH),
        review_target_draft_ref=ArtifactRef("review-target", 1, HASH),
        adopted_draft_ref=ArtifactRef("adopted", 1, HASH),
        latest_review_ref=ArtifactRef("review", 1, HASH),
        pending_changeset_ref=ArtifactRef("changeset", 1, HASH), commit_receipt_ref=None,
        recovery=None, created_at=now, updated_at=now,
    )
    record = CanonCommitIntentRecord(
        journal_id="intent-journal", task_id="task-intent", operation_id="intent-op", decision_id="intent-decision",
        changeset_ref=ArtifactRef("changeset", 1, HASH), target_bundle_ref=ArtifactRef("target", 1, HASH),
        base_manifest_hash=HASH, target_manifest_hash=HASH, created_at=now.isoformat(),
        base_bundle_ref=ArtifactRef("base", 1, HASH), base_bundle_content_hash=HASH,
        target_bundle_content_hash=HASH, base_world_hash=HASH, target_world_hash=HASH,
        canonical_bundle_schema_version=1,
    )
    conn.commit()
    return transitioned, record


@pytest.mark.parametrize(
    "field,value",
    [
        ("base_bundle_ref", None),
        ("base_bundle_content_hash", None),
        ("target_bundle_content_hash", "sha256:" + "b" * 64),
        ("base_world_hash", None),
        ("target_world_hash", None),
        ("canonical_bundle_schema_version", 2),
        ("target_bundle_ref", ArtifactRef("target", 2, HASH)),
    ],
)
def test_direct_intent_rejects_incomplete_or_inconsistent_identity_without_residue(tmp_path: Path, field: str, value) -> None:
    conn = _connection(tmp_path)
    try:
        transitioned, record = _pending_intent_fixture(conn)
        with pytest.raises(UnsupportedPersistenceBoundary):
            SqliteCanonCommitRepository(conn).create_intent(
                replace(record, **{field: value}), transitioned, expected_revision=5
            )
        conn.rollback()
        task = conn.execute("SELECT status,aggregate_revision FROM chapter_task WHERE task_id='task-intent'").fetchone()
        assert tuple(task) == ("CHANGESET_APPROVAL_PENDING", 5)
        assert conn.execute("SELECT COUNT(*) FROM canon_commit_journal").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM creation_artifact_ref WHERE artifact_id IN ('base','target')").fetchone()[0] == 0
    finally:
        conn.close()
