"""SQLite adapter implementing the :class:`ChapterTaskRepository` protocol.

Also manages the ``creation_artifact_ref`` registry as a side-effect of
persisting ``ChapterTask`` aggregates.
"""

from __future__ import annotations

import sqlite3

from xiaoshuo.application.creation.errors import (
    ArtifactIdentityConflict,
    NotFound,
    RevisionConflict,
    UnsupportedPersistenceBoundary,
)
from xiaoshuo.application.creation.guards import guard_committing_not_completed
from xiaoshuo.domain.creation import ArtifactRef, ChapterTask, ChapterTaskStatus

from .serialization import (
    artifact_ref_to_row,
    chapter_task_to_row,
    row_to_artifact_ref,
    row_to_chapter_task,
)

_FORBIDDEN_STATUSES = frozenset(
    {ChapterTaskStatus.COMMITTING, ChapterTaskStatus.COMPLETED}
)


class SqliteChapterTaskRepository:
    """SQLite adapter for :class:`ChapterTaskRepository` protocol.

    Args:
        conn: An open ``sqlite3.Connection`` (PRAGMAs should already be
            configured by :func:`~.connection.get_connection`).

    .. warning::
        This repository does **not** manage transactions — the caller
        (typically a :class:`~.uow.SqliteCreationUnitOfWork`) owns the
        commit/rollback lifecycle.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_artifact_refs(self, task_row) -> dict[str, ArtifactRef]:
        """Fetch every :class:`ArtifactRef` referenced by a ``chapter_task`` row."""
        fk_columns = [
            "creative_intent_ref_artifact_id",
            "confirmed_plan_ref_artifact_id",
            "current_author_draft_ref_artifact_id",
            "review_target_draft_ref_artifact_id",
            "adopted_draft_ref_artifact_id",
            "latest_review_ref_artifact_id",
            "pending_changeset_ref_artifact_id",
            "commit_receipt_ref_artifact_id",
        ]
        needed_ids = set()
        for col in fk_columns:
            aid = task_row[col]
            if aid is not None:
                needed_ids.add(aid)

        refs: dict[str, ArtifactRef] = {}
        for aid in needed_ids:
            row = self._conn.execute(
                "SELECT artifact_id, schema_version, content_hash "
                "FROM creation_artifact_ref WHERE artifact_id = ?",
                (aid,),
            ).fetchone()
            if row:
                refs[aid] = row_to_artifact_ref(
                    row["artifact_id"], row["schema_version"], row["content_hash"]
                )
        return refs

    def _ensure_artifact_ref(self, ref: ArtifactRef) -> None:
        """Insert *ref* into ``creation_artifact_ref`` or verify it matches.

        Raises:
            ArtifactIdentityConflict: if the ``artifact_id`` already
                exists with different ``schema_version`` or ``content_hash``.
        """
        existing = self._conn.execute(
            "SELECT schema_version, content_hash FROM creation_artifact_ref "
            "WHERE artifact_id = ?",
            (ref.artifact_id,),
        ).fetchone()
        if existing:
            if (
                existing["schema_version"] != ref.schema_version
                or existing["content_hash"] != ref.content_hash
            ):
                raise ArtifactIdentityConflict(
                    f"artifact_id {ref.artifact_id!r} already registered with "
                    f"schema_version={existing['schema_version']}, "
                    f"content_hash={existing['content_hash']}; "
                    f"cannot re-register with schema_version={ref.schema_version}, "
                    f"content_hash={ref.content_hash}"
                )
        else:
            self._conn.execute(
                "INSERT INTO creation_artifact_ref "
                "(artifact_id, schema_version, content_hash) VALUES (?, ?, ?)",
                artifact_ref_to_row(ref),
            )

    def _register_all_refs(self, task: ChapterTask) -> None:
        """Register every :class:`ArtifactRef` referenced by *task*."""
        refs: list[ArtifactRef] = [task.creative_intent_ref]
        for ref in (
            task.confirmed_plan_ref,
            task.current_author_draft_ref,
            task.review_target_draft_ref,
            task.adopted_draft_ref,
            task.latest_review_ref,
            task.pending_changeset_ref,
        ):
            if ref is not None:
                refs.append(ref)
        for ref in refs:
            self._ensure_artifact_ref(ref)

    # ------------------------------------------------------------------
    # Repository protocol
    # ------------------------------------------------------------------

    def get(self, task_id: str) -> ChapterTask | None:
        """Retrieve a :class:`ChapterTask` by its ``task_id``.

        Returns ``None`` when the task does not exist.
        """
        row = self._conn.execute(
            "SELECT * FROM chapter_task WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        refs = self._fetch_artifact_refs(row)
        return row_to_chapter_task(row, refs)

    def add(self, task: ChapterTask) -> None:
        """Persist a new :class:`ChapterTask`.

        Raises:
            UnsupportedPersistenceBoundary: if the task carries a
                non-null ``commit_receipt_ref`` or its status is
                ``COMMITTING`` or ``COMPLETED``.
        """
        guard_committing_not_completed(task)
        if task.status in _FORBIDDEN_STATUSES:
            raise UnsupportedPersistenceBoundary(
                f"Cannot add task with status {task.status.value}; "
                f"COMMITTING/COMPLETED persistence is not yet supported"
            )
        self._register_all_refs(task)
        row_dict = chapter_task_to_row(task)
        columns = ", ".join(row_dict.keys())
        placeholders = ", ".join("?" for _ in row_dict)
        self._conn.execute(
            f"INSERT INTO chapter_task ({columns}) VALUES ({placeholders})",
            list(row_dict.values()),
        )

    def replace(self, task: ChapterTask, *, expected_revision: int) -> None:
        """Atomically replace an existing :class:`ChapterTask`.

        Uses a single ``UPDATE … WHERE task_id = ? AND
        aggregate_revision = ?`` so concurrent writers cannot race
        between a SELECT-and-then-UPDATE pair.

        Args:
            task: The updated task aggregate.
            expected_revision: The revision the caller expects the
                persisted aggregate to currently have.

        Raises:
            UnsupportedPersistenceBoundary: if the task carries a
                non-null ``commit_receipt_ref`` or its status is
                ``COMMITTING`` or ``COMPLETED``.
            RevisionConflict: if the conditional UPDATE affects zero
                rows (task missing or revision changed).
        """
        guard_committing_not_completed(task)
        if task.status in _FORBIDDEN_STATUSES:
            raise UnsupportedPersistenceBoundary(
                f"Cannot replace task with status {task.status.value}"
            )

        # Wrap artifact-ref registration and conditional UPDATE in a
        # savepoint so that a RevisionConflict (or any other error
        # inside the block) leaves no side-effects.
        self._conn.execute("SAVEPOINT replace_task")
        try:
            self._register_all_refs(task)
            row_dict = chapter_task_to_row(task)
            set_clause = ", ".join(f"{k} = ?" for k in row_dict)
            cursor = self._conn.execute(
                f"UPDATE chapter_task SET {set_clause} "
                f"WHERE task_id = ? AND aggregate_revision = ?",
                list(row_dict.values()) + [task.task_id, expected_revision],
            )
            if cursor.rowcount == 0:
                exists = self._conn.execute(
                    "SELECT 1 FROM chapter_task WHERE task_id = ?",
                    (task.task_id,),
                ).fetchone()
                if exists is None:
                    raise RevisionConflict(
                        f"Task {task.task_id!r} not found for replace"
                    )
                raise RevisionConflict(
                    f"Expected revision {expected_revision} for task "
                    f"{task.task_id!r}, but current revision has changed"
                )
            self._conn.execute("RELEASE replace_task")
        except Exception:
            self._conn.execute("ROLLBACK TO SAVEPOINT replace_task")
            self._conn.execute("RELEASE replace_task")
            raise
