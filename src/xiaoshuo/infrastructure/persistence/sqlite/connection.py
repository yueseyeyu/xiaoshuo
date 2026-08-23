"""SQLite connection factory — PRAGMA setup outside transactions."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .settings import SQLitePersistenceSettings


def _verify_sqlite_version() -> None:
    """SQLite 3.37.0+ required for STRICT table support.

    Raises:
        RuntimeError: if the bundled SQLite version is too old.
    """
    ver = sqlite3.sqlite_version_info
    if ver < (3, 37, 0):
        raise RuntimeError(
            f"SQLite version {sqlite3.sqlite_version} is too old. "
            f"Version 3.37.0+ required for STRICT table support."
        )


def get_connection(
    settings: SQLitePersistenceSettings, *, read_only: bool = False
) -> sqlite3.Connection:
    """Create and configure a SQLite connection from *settings*.

    All PRAGMAs are set **outside any transaction** so they take effect
    immediately and are not rolled back.

    Args:
        settings: Connection configuration.
        read_only: If True, open in read-only mode (mode=ro).

    Returns:
        A configured ``sqlite3.Connection`` with ``row_factory = sqlite3.Row``.

    Raises:
        RuntimeError: if the SQLite version is too old or any PRAGMA
            fails to apply.
    """
    _verify_sqlite_version()

    path = Path(settings.db_path)
    mode = "ro" if read_only else "rwc"
    uri = f"file:{path.as_posix()}?mode={mode}"

    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row

    # --- PRAGMAs (all outside any transaction) ---
    # The read-only branch must never request WAL: setting journal_mode can
    # write database metadata.  ``query_only`` is an additional SQLite guard.
    if read_only:
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(f"PRAGMA busy_timeout = {settings.busy_timeout_ms}")
            conn.execute("PRAGMA query_only = ON")
            (query_only,) = conn.execute("PRAGMA query_only").fetchone()
            if query_only != 1:
                raise RuntimeError("Failed to enable query_only")
        except Exception:
            conn.close()
            raise
        return conn

    conn.execute("PRAGMA foreign_keys = ON")
    (fk_on,) = conn.execute("PRAGMA foreign_keys").fetchone()
    if fk_on != 1:
        conn.close()
        raise RuntimeError("Failed to enable foreign_keys")

    conn.execute("PRAGMA journal_mode = WAL")
    (wal_mode,) = conn.execute("PRAGMA journal_mode").fetchone()
    if wal_mode.lower() != "wal":
        conn.close()
        raise RuntimeError(f"Failed to set journal_mode=WAL, got {wal_mode}")

    conn.execute(f"PRAGMA busy_timeout = {settings.busy_timeout_ms}")
    (bt,) = conn.execute("PRAGMA busy_timeout").fetchone()
    if bt != settings.busy_timeout_ms:
        conn.close()
        raise RuntimeError(
            f"Failed to set busy_timeout, expected {settings.busy_timeout_ms}, got {bt}"
        )

    return conn
