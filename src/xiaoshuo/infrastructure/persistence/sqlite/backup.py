"""Database backup via ``sqlite3.Connection.backup()`` with integrity verification."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def _db_identity(conn: sqlite3.Connection) -> dict:
    """Read identity markers from a database connection.

    Returns:
        A dict with ``application_id`` and ``user_version``.
    """
    (app_id,) = conn.execute("PRAGMA application_id").fetchone()
    (user_ver,) = conn.execute("PRAGMA user_version").fetchone()
    return {"application_id": app_id, "user_version": user_ver}


def _sha256_file(path: Path) -> str:
    """Compute the SHA-256 digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def backup_database(source_conn: sqlite3.Connection, target_path: Path | str) -> dict:
    """Backup *source_conn* to *target_path*.

    The backup uses SQLite's built-in online backup API
    (:meth:`sqlite3.Connection.backup`) so the source database can
    continue being read during the operation.

    Args:
        source_conn: An open connection to the source database.
        target_path: Filesystem path for the backup.  Must not exist.

    Returns:
        A manifest dict with source/target identity and SHA-256 digests:

        .. code-block:: python

            {
                "source": {
                    "path": "...",
                    "application_id": 1500514898,
                    "user_version": 0,
                    "sha256_whole_file": "...",
                },
                "target": {
                    "path": "...",
                    "application_id": 1500514898,
                    "user_version": 0,
                    "sha256_whole_file": "...",
                },
                "created_at": "2026-07-19T18:30:00+00:00",
            }

    Raises:
        FileExistsError: if *target_path* already exists.
        RuntimeError: if integrity check fails on source or target.
    """
    target = Path(target_path)
    if target.exists():
        raise FileExistsError(f"Backup target already exists: {target}")

    source_id = _db_identity(source_conn)

    # --- Pre-backup integrity check ---
    result = source_conn.execute("PRAGMA integrity_check").fetchone()
    if result[0] != "ok":
        raise RuntimeError(f"Source integrity check failed: {result[0]}")

    # --- Perform backup ---
    target_conn = sqlite3.connect(str(target))
    try:
        source_conn.backup(target_conn)
        target_conn.commit()

        # --- Post-backup integrity check ---
        result = target_conn.execute("PRAGMA integrity_check").fetchone()
        if result[0] != "ok":
            raise RuntimeError(f"Target integrity check failed: {result[0]}")

        target_id = _db_identity(target_conn)
        target_sha256 = _sha256_file(target)
    finally:
        target_conn.close()

    source_sha256 = _sha256_file(
        Path(source_conn.execute("PRAGMA database_list").fetchone()[2])
    )

    return {
        "source": {
            "path": str(
                Path(source_conn.execute("PRAGMA database_list").fetchone()[2])
            ),
            "application_id": source_id["application_id"],
            "user_version": source_id["user_version"],
            "sha256_whole_file": source_sha256,
        },
        "target": {
            "path": str(target),
            "application_id": target_id["application_id"],
            "user_version": target_id["user_version"],
            "sha256_whole_file": target_sha256,
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
