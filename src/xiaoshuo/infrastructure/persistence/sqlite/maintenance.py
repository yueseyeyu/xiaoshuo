"""Three explicit maintenance entry points: init, migrate, backup.

These are the top-level operations a CLI or provisioning script calls.
They own the connection lifecycle and delegate to specialised modules.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .backup import backup_database as _backup
from .connection import get_connection
from .migration_runner import MigrationRunner
from .settings import SQLitePersistenceSettings

APPLICATION_ID = 0x59584352


def init_database(settings: SQLitePersistenceSettings) -> Path:
    """Create a new empty database at ``settings.db_path``.

    The database is initialised with:
    - ``application_id = 0x59584352`` (``YXCR`` little-endian)
    - ``user_version = 0`` (no migrations applied yet)
    - Connection PRAGMAs (foreign_keys, WAL, busy_timeout) per
      :func:`~.connection.get_connection`.

    Args:
        settings: Database configuration.

    Returns:
        The resolved ``Path`` of the created database file.

    Raises:
        FileExistsError: if the database file already exists.
    """
    db_path = Path(settings.db_path)
    if db_path.exists():
        raise FileExistsError(f"Database already exists: {db_path}")

    # Ensure parent directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = get_connection(settings)
    try:
        conn.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        conn.execute("PRAGMA user_version = 0")
        conn.commit()
    finally:
        conn.close()

    return db_path


def migrate_database(settings: SQLitePersistenceSettings) -> None:
    """Run pending migrations on an existing database.

    Args:
        settings: Database configuration.

    Raises:
        FileNotFoundError: if the database file does not exist.
        RuntimeError: if a migration fails integrity checks or
            content verification.
    """
    db_path = Path(settings.db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    conn = get_connection(settings)
    try:
        runner = MigrationRunner()
        runner.migrate(conn, settings)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def backup_database_maintenance(
    settings: SQLitePersistenceSettings,
    target_path: Path | str | None = None,
) -> dict:
    """Create a database backup.  Returns a manifest dict.

    Args:
        settings: Database configuration.  ``settings.backup_dir`` is
            used as the default location if *target_path* is not given.
        target_path: Explicit backup destination.  If omitted, a
            timestamped file name is generated inside
            ``settings.backup_dir``.

    Returns:
        Manifest dict as produced by :func:`~.backup.backup_database`.

    Raises:
        ValueError: if neither ``settings.backup_dir`` nor
            *target_path* is provided.
        FileExistsError: if the target path already exists.
        RuntimeError: if integrity check fails.
    """
    if settings.backup_dir is None and target_path is None:
        raise ValueError(
            "Either settings.backup_dir or target_path must be provided"
        )

    conn = get_connection(settings, read_only=True)
    try:
        if target_path is None:
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            target_path = Path(settings.backup_dir) / f"creation_backup_{ts}.db"
        return _backup(conn, target_path)
    finally:
        conn.close()
