"""Dedicated B3 SQLite read-only session.

The session exposes only read-only repositories.  Exact-id Task reads
delegate to the existing :class:`SqliteChapterTaskRepository` — no SQL,
NotFound, or ArtifactRef rebuild logic is duplicated in the B3 layer.
"""

from __future__ import annotations

import sqlite3

from .query_repository import SqliteIntegrityCheckRepository, SqliteReadOnlyQueryRepository
from .repository import SqliteChapterTaskRepository


class _DelegatingTaskReader:
    """Read-only task reader that delegates exact-id reads to the existing
    B1 :class:`SqliteChapterTaskRepository` and list reads to the B3
    :class:`SqliteReadOnlyQueryRepository`.

    No SQL, NotFound, or ArtifactRef rebuild logic is duplicated here.
    The B3 query layer never re-implements the exact-id read path.
    """

    __slots__ = ("_exact", "_query")

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._exact = SqliteChapterTaskRepository(conn)
        self._query = SqliteReadOnlyQueryRepository(conn)

    def get(self, task_id: str):
        """Delegate to the existing B1 repository; no B3 SQL path."""
        return self._exact.get(task_id)

    def list_by_project(self, request):
        """Delegate to the B3 query repository for list reads."""
        return self._query.list_by_project(request)


class SqliteCreationQuerySession:
    """Expose only B3 query repositories and deterministic close.

    ``tasks`` is a :class:`_DelegatingTaskReader` whose ``get`` delegates
    to :class:`SqliteChapterTaskRepository` (the existing B1 exact-id
    path).  No ``add``, ``replace``, ``commit``, or ``rollback`` is
    exposed.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._query_repo = SqliteReadOnlyQueryRepository(conn)
        self.tasks = _DelegatingTaskReader(conn)
        self.audit = self._query_repo
        self.integrity = SqliteIntegrityCheckRepository(conn)

    def close(self) -> None:
        self._conn.close()
