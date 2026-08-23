"""SQLite adapter implementing the :class:`CreationUnitOfWork` protocol."""

from __future__ import annotations

import sqlite3

from .audit_repository import SqliteAuditEventRepository
from .author_decision_repository import SqliteAuthorDecisionRepository
from .canon_commit_repository import SqliteCanonCommitRepository
from .c4a_apply_repository import SqliteC4aApplyRepository
from .operation_repository import SqliteOperationLogRepository
from .repository import SqliteChapterTaskRepository


class SqliteCreationUnitOfWork:
    """SQLite implementation of :class:`~xiaoshuo.application.creation.repository.CreationUnitOfWork`.

    All three repositories (``tasks``, ``audit``, ``operations``) share
    the same ``sqlite3.Connection`` and therefore the same transaction
    scope.

    Args:
        conn: An open ``sqlite3.Connection`` owned by this UoW.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self.tasks = SqliteChapterTaskRepository(conn)
        self.audit = SqliteAuditEventRepository(conn)
        self.operations = SqliteOperationLogRepository(conn)
        self.decisions = SqliteAuthorDecisionRepository(conn)
        self.canon = SqliteCanonCommitRepository(conn)

    def commit(self) -> None:
        """Commit the current transaction."""
        self._conn.commit()

    def rollback(self) -> None:
        """Rollback the current transaction."""
        self._conn.rollback()

    def close(self) -> None:
        """Close the shared connection deterministically."""
        self._conn.close()


class SqliteC4aCompletionUnitOfWork:
    """C4-only UoW whose repository owns completion facts.

    The C3 ``canon`` repository remains exposed only by
    :class:`SqliteCreationUnitOfWork`; this UoW deliberately has no C3
    completion method or fallback path.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        if not isinstance(conn, sqlite3.Connection):
            raise TypeError("an open SQLite connection is required")
        self._conn = conn
        self.c4a = SqliteC4aApplyRepository(conn)
        self.repository = self.c4a

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


C4aCompletionUnitOfWork = SqliteC4aCompletionUnitOfWork
