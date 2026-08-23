"""Migration runner — applies versioned SQL migration files atomically.

Migration files live in the ``migrations/`` directory adjacent to this
module and are named ``v001_<description>.sql``, ``v002_<description>.sql``,
etc.  Each file is SHA-256 content-addressed in the
``creation_schema_migration`` ledger table so that already-applied
migrations cannot be silently tampered with.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .settings import SQLitePersistenceSettings

_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_FILE_PATTERN = re.compile(r"^v(\d{3})_.+\.sql$")
_APPLICATION_ID = 0x59584352


def _parse_version(file_name: str) -> int | None:
    """Extract integer version from a migration file name, or None."""
    m = _FILE_PATTERN.match(file_name)
    if m:
        return int(m.group(1))
    return None


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sql_literal(value: str) -> str:
    """Return *value* as a properly escaped single-quoted SQL string literal.

    Single quotes inside *value* are doubled per SQLite quoting rules.
    """
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def _discover_migrations() -> list[tuple[int, str, str]]:
    """Return sorted ``(version, file_name, sha256)`` for every migration file."""
    results: list[tuple[int, str, str]] = []
    for child in sorted(_MIGRATIONS_DIR.iterdir()):
        if not child.is_file() or not child.name.endswith(".sql"):
            continue
        version = _parse_version(child.name)
        if version is None:
            continue
        content = child.read_bytes()
        sha = _sha256_bytes(content)
        results.append((version, child.name, sha))
    results.sort(key=lambda t: t[0])
    return results


def _applied_versions(conn: sqlite3.Connection) -> dict[int, tuple[str, str]]:
    """Return ``{version: (file_name, sha256)}`` from the ledger table.

    If the ledger table does not exist yet (first run before any
    migration), returns an empty dict.
    """
    try:
        rows = conn.execute(
            "SELECT version, file_name, sha256 FROM creation_schema_migration ORDER BY version"
        ).fetchall()
        return {row["version"]: (row["file_name"], row["sha256"]) for row in rows}
    except sqlite3.OperationalError as exc:
        err_msg = str(exc)
        if "no such table" in err_msg:
            return {}
        raise


def _integrity_check(conn: sqlite3.Connection, label: str) -> None:
    """Run ``PRAGMA integrity_check`` and ``PRAGMA foreign_key_check``.

    Raises RuntimeError on any failure.
    """
    (result,) = conn.execute("PRAGMA integrity_check").fetchone()
    if result != "ok":
        raise RuntimeError(f"integrity_check ({label}): {result}")

    fk_issues = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_issues:
        lines = "\n".join(
            f"  table={r[0]} rowid={r[1]} parent={r[2]} fk_index={r[3]}"
            for r in fk_issues
        )
        raise RuntimeError(f"foreign_key_check ({label}) found violations:\n{lines}")


def _has_tables(conn: sqlite3.Connection) -> bool:
    """Return True if the database has at least one user table (not sqlite_*)."""
    row = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchone()
    return row[0] > 0


class MigrationRunner:
    """Apply pending SQL migrations to a creation database.

    Typical usage::

        runner = MigrationRunner()
        runner.migrate(conn, settings)
    """

    def migrate(self, conn: sqlite3.Connection, settings: SQLitePersistenceSettings) -> None:
        """Discover and apply all pending migrations.

        Args:
            conn: Open database connection (PRAGMAs already set by
                :func:`get_connection`).
            settings: Settings (used only if a pre-migration backup
                must be created).

        Raises:
            RuntimeError: if a migration fails integrity checks or
                on-disk SHA-256 does not match the ledger.
            FileNotFoundError: if the migrations directory is missing.
        """
        if not _MIGRATIONS_DIR.is_dir():
            raise FileNotFoundError(f"Migrations directory not found: {_MIGRATIONS_DIR}")

        migrations = _discover_migrations()
        if not migrations:
            return  # nothing to do

        applied = _applied_versions(conn)

        for version, file_name, sha in migrations:
            if version in applied:
                _verify_applied(applied[version], file_name, sha, version)
            else:
                _apply_migration(conn, version, file_name, sha, settings)


def _verify_applied(
    applied_entry: tuple[str, str], file_name: str, sha: str, version: int
) -> None:
    """Verify an already-applied migration's SHA-256 matches the on-disk file.

    Fail-closed on mismatch — silent data corruption can indicate
    tampering or accidental file modification.
    """
    stored_file, stored_sha = applied_entry
    if stored_file != file_name:
        raise RuntimeError(
            f"Migration v{version:03d} file name mismatch: "
            f"ledger has {stored_file!r}, on-disk is {file_name!r}"
        )
    if stored_sha != sha:
        raise RuntimeError(
            f"Migration v{version:03d} SHA-256 mismatch: "
            f"ledger has {stored_sha!r}, on-disk is {sha!r}. "
            f"The SQL file must not be modified after it has been applied."
        )


def _apply_migration(
    conn: sqlite3.Connection,
    version: int,
    file_name: str,
    sha: str,
    settings: SQLitePersistenceSettings,
) -> None:
    """Apply a single new migration file atomically.

    Steps:
         0. **Identity preflight** — verify ``application_id`` and
            ``user_version`` match Creation expectations BEFORE any
            backup, DDL, or ledger write.
         1. If the database already contains user tables, create a
            pre-migration backup.
         2. Run integrity_check + foreign_key_check.
         3. Execute the SQL file in a new transaction (includes the
            ledger INSERT).
         4. Run integrity_check + foreign_key_check again.
         5. Verify application_id and user_version.
         6. Quick round-trip: verify a known table exists.
    """
    # --- 0. Identity preflight (fail-closed before any side-effects) ---
    (app_id,) = conn.execute("PRAGMA application_id").fetchone()
    if app_id != _APPLICATION_ID:
        raise RuntimeError(
            f"Database application_id is {app_id} (expected {_APPLICATION_ID}); "
            f"this file is not a Creation SQLite database"
        )
    (db_uv,) = conn.execute("PRAGMA user_version").fetchone()
    applied = _applied_versions(conn)
    if applied:
        max_applied = max(applied.keys())
        if db_uv != max_applied:
            raise RuntimeError(
                f"user_version is {db_uv} but ledger shows max applied version "
                f"{max_applied}; the database identity may be corrupted"
            )
    elif db_uv != 0:
        raise RuntimeError(
            f"user_version is {db_uv} but no migrations have been applied "
            f"(expected 0); the database identity may be corrupted"
        )

    if version == 3 and file_name != "v003_canon_mvp.sql":
        raise RuntimeError("v003 is reserved for the Canon MVP safe rebuild")
    if version == 4 and file_name != "v004_canon_bundle_identity.sql":
        raise RuntimeError("v004 is reserved for the Canon bundle identity migration")
    if version == 4 and 3 not in applied:
        raise RuntimeError("v004 requires the approved v003 Canon migration")
    if version == 5 and file_name != "v005_c4b_activation_facts.sql":
        raise RuntimeError("v005 is reserved for the C4b activation facts migration")
    if version == 5 and 4 not in applied:
        raise RuntimeError("v005 requires the approved v004 Canon identity migration")
    if version == 6 and file_name != "v006_c4a_apply_facts.sql":
        raise RuntimeError("v006 is reserved for the C4a Apply facts migration")
    if version == 6 and 5 not in applied:
        raise RuntimeError("v006 requires the approved v005 activation facts migration")

    # --- 1. Backup if non-empty ---
    if _has_tables(conn):
        _auto_backup(conn, version, settings)

    # --- 2. Pre-check ---
    _integrity_check(conn, f"pre-migration v{version:03d}")

    # v003 rebuilds chapter_task and therefore needs the deliberately
    # narrow foreign-key handling below.  Ordinary migrations must keep the
    # normal executor.
    if version == 3:
        _apply_v003_rebuild(conn, version, file_name, sha)
        return
    if version == 4:
        _apply_v004_identity(conn, version, file_name, sha)
        return
    if version == 6:
        _apply_v006_facts(conn, version, file_name, sha)
        return

    # --- 3. Execute SQL in a single transaction ---
    # Build a self-contained script so DDL, user_version, and ledger
    # INSERT share one atomic transaction.  We must NOT call
    # executescript() on a connection with an explicit pending BEGIN —
    # executescript() commits first, breaking the boundary.  Instead,
    # the script itself carries BEGIN IMMEDIATE / COMMIT.
    sql_text = (_MIGRATIONS_DIR / file_name).read_text(encoding="utf-8")
    now_iso = datetime.now(timezone.utc).isoformat()

    script = (
        "BEGIN IMMEDIATE;\n"
        + sql_text + "\n"
        + f"PRAGMA user_version = {int(version)};\n"
        + "INSERT INTO creation_schema_migration "
        + "(version, file_name, sha256, applied_at) "
        + f"VALUES ({int(version)}, {_sql_literal(file_name)}, {_sql_literal(sha)}, {_sql_literal(now_iso)});\n"
        + "COMMIT;"
    )
    try:
        conn.executescript(script)
    except sqlite3.Error:
        conn.rollback()
        raise

    # --- 4. Post-check ---
    _integrity_check(conn, f"post-migration v{version:03d}")

    _verify_post_migration_identity(conn, version)
    if version == 5:
        _verify_v005_schema(conn)


def _verify_post_migration_identity(conn: sqlite3.Connection, version: int) -> None:
    """Verify markers and ledger after every migration executor."""
    # --- 5. Verify identity markers ---
    (app_id,) = conn.execute("PRAGMA application_id").fetchone()
    if app_id != _APPLICATION_ID:
        raise RuntimeError(
            f"application_id is {app_id} (expected {_APPLICATION_ID}) "
            f"after v{version:03d}"
        )

    (user_ver,) = conn.execute("PRAGMA user_version").fetchone()
    if user_ver < version:
        raise RuntimeError(
            f"user_version is {user_ver} but expected at least {version} "
            f"after v{version:03d}"
        )
    (cnt,) = conn.execute(
        "SELECT COUNT(*) FROM creation_schema_migration WHERE version = ?",
        (version,),
    ).fetchone()
    if cnt != 1:
        raise RuntimeError(f"Ledger entry for v{version:03d} not found after migration")


def _apply_v003_rebuild(
    conn: sqlite3.Connection, version: int, file_name: str, sha: str
) -> None:
    """Execute the one approved parent-table rebuild with FK checks restored.

    SQLite cannot remove the v001 status CHECK with ``ALTER TABLE``.  This
    helper is intentionally version-specific: it never changes the behavior
    of ordinary migrations and it never leaves foreign-key enforcement off.
    """
    if conn.in_transaction:
        raise RuntimeError("v003 rebuild requires no active transaction")
    (legacy_alter_table,) = conn.execute("PRAGMA legacy_alter_table").fetchone()
    sql_text = (_MIGRATIONS_DIR / file_name).read_text(encoding="utf-8")
    now_iso = datetime.now(timezone.utc).isoformat()
    # SQLite updates child FK definitions during a rename unless legacy mode
    # is enabled.  v003 needs the child declarations to keep referencing the
    # replacement table, so this setting is tightly scoped to this executor.
    conn.execute("PRAGMA legacy_alter_table = ON")
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 0:
            raise RuntimeError("v003 rebuild could not disable foreign keys outside transaction")
        conn.execute("BEGIN IMMEDIATE")
        _execute_sql_statements(conn, sql_text)
        conn.execute(f"PRAGMA user_version = {int(version)}")
        conn.execute(
            "INSERT INTO creation_schema_migration "
            "(version, file_name, sha256, applied_at) VALUES (?, ?, ?, ?)",
            (version, file_name, sha, now_iso),
        )
        # Every validation that can fail the v003 migration is intentionally
        # inside the transaction and before its ledger becomes durable.
        _integrity_check(conn, f"post-migration v{version:03d}")
        _verify_v003_schema(conn)
        _verify_post_migration_identity(conn, version)
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        # This is deliberately not conditional on the original setting:
        # Creation connections require foreign-key enforcement to be on.
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA legacy_alter_table = {int(legacy_alter_table)}")
    if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise RuntimeError("v003 could not restore foreign-key enforcement")


def _apply_v004_identity(
    conn: sqlite3.Connection, version: int, file_name: str, sha: str
) -> None:
    """Create the v004 active identity graph only after a legacy preflight.

    All checks that can fail are executed inside the same transaction as the
    schema and migration-ledger writes.  Thus a rejected legacy graph leaves
    the v003 tables and ledger untouched.
    """
    if conn.in_transaction:
        raise RuntimeError("v004 migration requires no active transaction")
    sql_text = (_MIGRATIONS_DIR / file_name).read_text(encoding="utf-8")
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _verify_v004_legacy_preflight(conn)
        _execute_sql_statements(conn, sql_text)
        conn.execute(f"PRAGMA user_version = {int(version)}")
        conn.execute(
            "INSERT INTO creation_schema_migration "
            "(version, file_name, sha256, applied_at) VALUES (?, ?, ?, ?)",
            (version, file_name, sha, now_iso),
        )
        _integrity_check(conn, f"post-migration v{version:03d}")
        _verify_v004_schema(conn)
        _verify_post_migration_identity(conn, version)
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            conn.execute("PRAGMA foreign_keys = ON")
    if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise RuntimeError("v004 could not restore foreign-key enforcement")


def _apply_v006_facts(
    conn: sqlite3.Connection, version: int, file_name: str, sha: str
) -> None:
    """Apply C4a facts with all schema checks inside the same transaction."""
    if conn.in_transaction:
        raise RuntimeError("v006 migration requires no active transaction")
    sql_text = (_MIGRATIONS_DIR / file_name).read_text(encoding="utf-8")
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _execute_sql_statements(conn, sql_text)
        conn.execute(f"PRAGMA user_version = {int(version)}")
        conn.execute(
            "INSERT INTO creation_schema_migration "
            "(version, file_name, sha256, applied_at) VALUES (?, ?, ?, ?)",
            (version, file_name, sha, now_iso),
        )
        _integrity_check(conn, f"post-migration v{version:03d}")
        _verify_v006_schema(conn)
        _verify_post_migration_identity(conn, version)
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise RuntimeError("v006 requires foreign-key enforcement")


def _verify_v004_legacy_preflight(conn: sqlite3.Connection) -> None:
    """Reject any v003 journal that cannot be retained as a complete legacy graph."""
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "canon_commit_journal" not in tables:
        return
    rows = conn.execute(
        "SELECT j.journal_id, j.task_id, j.operation_id, j.decision_id, "
        "t.status, t.commit_receipt_ref_artifact_id, "
        "o.operation_id, d.decision_id, d.task_id, d.target_ref_artifact_id, "
        "(SELECT COUNT(*) FROM canon_commit_receipt r "
        " WHERE r.journal_id=j.journal_id), "
        "(SELECT r.receipt_id FROM canon_commit_receipt r "
        " WHERE r.journal_id=j.journal_id LIMIT 1), "
        "(SELECT r.receipt_ref_artifact_id FROM canon_commit_receipt r "
        " WHERE r.journal_id=j.journal_id LIMIT 1), "
        "j.changeset_ref_artifact_id, j.target_bundle_ref_artifact_id "
        "FROM canon_commit_journal j "
        "LEFT JOIN chapter_task t ON t.task_id=j.task_id "
        "LEFT JOIN creation_operation o ON o.operation_id=j.operation_id "
        "LEFT JOIN creation_author_decision d ON d.decision_id=j.decision_id"
    ).fetchall()
    for row in rows:
        (
            _journal_id,
            task_id,
            _operation_id,
            _decision_id,
            status,
            task_receipt_ref,
            operation_id,
            decision_id,
            decision_task_id,
            decision_target_ref,
            receipt_count,
            receipt_id,
            receipt_ref,
            changeset_ref,
            target_ref,
        ) = row
        if (
            task_id is None
            or status not in ("COMPLETED", "CANCELLED")
            or operation_id is None
            or decision_id is None
            or decision_task_id != task_id
            or decision_target_ref != changeset_ref
            or receipt_count != 1
            or receipt_id is None
            or receipt_ref is None
        ):
            raise RuntimeError("v004 legacy journal preflight failed")
        if status == "COMPLETED" and (task_receipt_ref is None or task_receipt_ref != receipt_ref):
            raise RuntimeError("v004 legacy journal preflight failed")
        if status == "CANCELLED" and task_receipt_ref is not None:
            raise RuntimeError("v004 legacy journal preflight failed")
        for artifact_id in (changeset_ref, target_ref, receipt_ref):
            if not conn.execute(
                "SELECT 1 FROM creation_artifact_ref WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone():
                raise RuntimeError("v004 legacy journal preflight failed")


def _verify_v004_schema(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(canon_commit_journal)")}
    required = {
        "base_bundle_ref_artifact_id", "target_bundle_ref_artifact_id",
        "base_bundle_content_hash", "target_bundle_content_hash",
        "base_manifest_hash", "base_world_hash",
        "target_manifest_hash", "target_world_hash",
    }
    if not required.issubset(columns):
        raise RuntimeError("v004 active journal identity columns are missing")
    for table in ("canon_commit_journal_v003_legacy", "canon_commit_receipt_v003_legacy"):
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone():
            raise RuntimeError("v004 legacy table is missing")
    triggers = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
    }
    expected = {
        "trg_canon_commit_journal_no_update",
        "trg_canon_commit_journal_no_delete",
        "trg_canon_commit_receipt_no_update",
        "trg_canon_commit_receipt_no_delete",
    }
    if not expected.issubset(triggers):
        raise RuntimeError("v004 append-only active triggers are missing")
    for table in ("creation_audit_event", "creation_author_decision", "creation_decision_consumption"):
        parents = {row[2] for row in conn.execute(f"PRAGMA foreign_key_list({table})")}
        if "chapter_task" not in parents:
            raise RuntimeError(f"v004 child FK for {table} no longer targets chapter_task")


def _verify_v005_schema(conn: sqlite3.Connection) -> None:
    """Verify the independent, append-only C4b activation fact graph."""
    attempt_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(canon_activation_attempt)")
    }
    required_attempt = {
        "attempt_id", "project_id", "attempt_key", "request_digest",
        "seed_digest", "bundle_ref_artifact_id", "bundle_schema_version",
        "bundle_content_hash", "manifest_hash", "world_hash", "version_id",
        "pointer_content_hash", "operator_identity", "created_at",
    }
    if not required_attempt.issubset(attempt_columns):
        raise RuntimeError("v005 activation attempt identity columns are missing")

    event_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(canon_activation_event)")
    }
    required_event = {
        "event_id", "attempt_id", "project_id", "phase", "result",
        "error_code", "replay_envelope_json", "replay_envelope_hash", "created_at",
    }
    if not required_event.issubset(event_columns):
        raise RuntimeError("v005 activation event columns are missing")

    triggers = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        )
    }
    expected_triggers = {
        "trg_canon_activation_attempt_no_update",
        "trg_canon_activation_attempt_no_delete",
        "trg_canon_activation_event_no_update",
        "trg_canon_activation_event_no_delete",
    }
    if not expected_triggers.issubset(triggers):
        raise RuntimeError("v005 activation append-only triggers are missing")

    event_fks = {
        (row[2], row[3], row[4])
        for row in conn.execute("PRAGMA foreign_key_list(canon_activation_event)")
    }
    if ("canon_activation_attempt", "attempt_id", "attempt_id") not in event_fks:
        raise RuntimeError("v005 event attempt FK is missing")
    if ("canon_activation_attempt", "project_id", "project_id") not in event_fks:
        raise RuntimeError("v005 event project FK is missing")

    artifact_identity_index = False
    for row in conn.execute("PRAGMA index_list(creation_artifact_ref)"):
        if row[1] == "uq_creation_artifact_ref_identity" and row[2] == 1:
            columns = [
                info[2]
                for info in conn.execute(f"PRAGMA index_info({row[1]!r})")
            ]
            artifact_identity_index = columns == [
                "artifact_id", "schema_version", "content_hash"
            ]
            break
    if not artifact_identity_index:
        raise RuntimeError("v005 ArtifactRef identity unique target is missing")

    attempt_fks = {}
    for row in conn.execute("PRAGMA foreign_key_list(canon_activation_attempt)"):
        attempt_fks.setdefault(row[0], set()).add((row[2], row[3], row[4]))
    if not any(
        pairs == {
            ("creation_artifact_ref", "bundle_ref_artifact_id", "artifact_id"),
            ("creation_artifact_ref", "bundle_schema_version", "schema_version"),
            ("creation_artifact_ref", "bundle_content_hash", "content_hash"),
        }
        for pairs in attempt_fks.values()
    ):
        raise RuntimeError("v005 bundle ArtifactRef FK is missing")


def _verify_v006_schema(conn: sqlite3.Connection) -> None:
    """Verify the independent C4a attempt/event graph before commit."""
    attempt_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(canon_apply_attempt)")
    }
    required_attempt = {
        "apply_attempt_id", "project_id", "apply_key", "request_digest",
        "journal_id", "task_id", "operation_id", "decision_id",
        "base_bundle_ref_artifact_id", "base_bundle_schema_version",
        "base_bundle_content_hash", "base_version_id", "base_pointer_content_hash",
        "target_bundle_ref_artifact_id", "target_bundle_schema_version",
        "target_bundle_content_hash", "target_version_id",
        "target_pointer_content_hash", "target_marker_content_hash",
        "target_manifest_hash", "target_world_hash",
        "operator_identity", "created_at",
    }
    if not required_attempt.issubset(attempt_columns):
        raise RuntimeError("v006 Apply attempt identity columns are missing")

    event_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(canon_apply_event)")
    }
    required_event = {
        "event_id", "apply_attempt_id", "project_id", "phase", "result",
        "error_code", "replay_envelope_json", "replay_envelope_hash",
        "receipt_payload_ref_artifact_id", "receipt_payload_schema_version",
        "receipt_payload_content_hash", "observed_pointer_content_hash",
        "observed_marker_content_hash", "created_at",
    }
    if not required_event.issubset(event_columns):
        raise RuntimeError("v006 Apply event columns are missing")

    triggers = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        )
    }
    expected_triggers = {
        "trg_canon_apply_attempt_no_update",
        "trg_canon_apply_attempt_no_delete",
        "trg_canon_apply_attempt_binding",
        "trg_canon_apply_event_observation_binding",
        "trg_canon_apply_event_no_update",
        "trg_canon_apply_event_no_delete",
    }
    if not expected_triggers.issubset(triggers):
        raise RuntimeError("v006 Apply append-only triggers are missing")

    attempt_fks = {
        (row[2], row[3], row[4])
        for row in conn.execute("PRAGMA foreign_key_list(canon_apply_attempt)")
    }
    required_simple_fks = {
        ("canon_commit_journal", "journal_id", "journal_id"),
        ("chapter_task", "task_id", "task_id"),
        ("creation_operation", "operation_id", "operation_id"),
        ("creation_author_decision", "decision_id", "decision_id"),
    }
    if not required_simple_fks.issubset(attempt_fks):
        raise RuntimeError("v006 Apply durable identity FKs are missing")
    event_fks = {
        (row[2], row[3], row[4])
        for row in conn.execute("PRAGMA foreign_key_list(canon_apply_event)")
    }
    if {
        ("canon_apply_attempt", "apply_attempt_id", "apply_attempt_id"),
        ("canon_apply_attempt", "project_id", "project_id"),
    } - event_fks:
        raise RuntimeError("v006 event composite attempt FK is missing")

    artifact_ref_fks = {
        (row[2], row[3], row[4])
        for row in conn.execute("PRAGMA foreign_key_list(canon_apply_event)")
    }
    if ("creation_artifact_ref", "receipt_payload_ref_artifact_id", "artifact_id") not in artifact_ref_fks:
        raise RuntimeError("v006 receipt payload ArtifactRef FK is missing")


def _execute_sql_statements(conn: sqlite3.Connection, sql_text: str) -> None:
    """Execute complete SQLite statements without breaking an outer transaction."""
    statement = ""
    for line in sql_text.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            if statement.strip():
                conn.execute(statement)
            statement = ""
    if statement.strip():
        raise RuntimeError("v003 SQL ended with an incomplete statement")


def _verify_v003_schema(conn: sqlite3.Connection) -> None:
    """Fail closed if the approved rebuild lost required structure."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(chapter_task)")}
    if "commit_receipt_ref_artifact_id" not in columns:
        raise RuntimeError("v003 chapter_task receipt FK column is missing")
    indexes = {row["name"] for row in conn.execute("PRAGMA index_list(chapter_task)")}
    if "idx_chapter_task_project_id" not in indexes:
        raise RuntimeError("v003 chapter_task project index is missing")
    triggers = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")
    }
    expected_triggers = {
        "trg_canon_commit_journal_no_update",
        "trg_canon_commit_journal_no_delete",
        "trg_canon_commit_receipt_no_update",
        "trg_canon_commit_receipt_no_delete",
    }
    if not expected_triggers.issubset(triggers):
        raise RuntimeError("v003 append-only Canon triggers are missing")
    for table in (
        "creation_audit_event",
        "creation_author_decision",
        "creation_decision_consumption",
    ):
        parents = {row["table"] for row in conn.execute(f"PRAGMA foreign_key_list({table})")}
        if "chapter_task" not in parents:
            raise RuntimeError(f"v003 child FK for {table} no longer targets chapter_task")



def _auto_backup(
    conn: sqlite3.Connection,
    next_version: int,
    settings: SQLitePersistenceSettings,
) -> None:
    """Create an automatic pre-migration backup.

    Requires ``settings.backup_dir`` to be explicitly set — the runner
    must not silently fall back to the database parent directory,
    create directories, or proceed without a backup target.
    """
    db_path = Path(settings.db_path).resolve()
    if settings.backup_dir is None:
        raise ValueError(
            f"Pre-migration backup requires explicit settings.backup_dir "
            f"when migrating non-empty database at {db_path}"
        )
    backup_parent = Path(settings.backup_dir).resolve()
    backup_parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = backup_parent / f"pre_migration_v{next_version:03d}_{ts}.db"

    # Use the backup API from the backup module
    from .backup import backup_database

    backup_database(conn, target)
