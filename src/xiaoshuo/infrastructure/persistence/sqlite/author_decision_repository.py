"""SQLite adapter for append-only AuthorDecision and consumption records (B2b).

Implements the :class:`AuthorDecisionRepository` protocol using the
same ``sqlite3.Connection`` as the surrounding ``CreationUnitOfWork``.
No independent transaction management — the caller owns commit/rollback.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from xiaoshuo.application.creation.errors import (
    CreationApplicationError,
)
from xiaoshuo.application.creation.repository import (
    DecisionConsumptionRecord,
)
from xiaoshuo.domain.creation import (
    ArtifactRef,
    AuthorDecision,
    DecisionOutcome,
    DecisionType,
    SourceKind,
    SourceRef,
)
from xiaoshuo.domain.creation.hashing import (
    verify_content_hash,
    canonicalize_json_value,
)


class SqliteAuthorDecisionRepository:
    """SQLite adapter for :class:`AuthorDecisionRepository` protocol.

    Args:
        conn: An open ``sqlite3.Connection`` (PRAGMAs should already be
            configured by :func:`~.connection.get_connection`).
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, decision_id: str) -> AuthorDecision | None:
        """Return the immutable AuthorDecision or None if not found."""
        try:
            row = self._conn.execute(
                "SELECT decision_id, schema_version, task_id, decision_type, "
                "target_ref_artifact_id, outcome, based_on_task_revision, "
                "author_id, reason, actor_kind, actor_id, content_hash, created_at "
                "FROM creation_author_decision WHERE decision_id = ?",
                (decision_id,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise CreationApplicationError("decision read failed") from exc
        if row is None:
            return None

        # Fetch the target_ref ArtifactRef
        try:
            ref_row = self._conn.execute(
                "SELECT artifact_id, schema_version, content_hash "
                "FROM creation_artifact_ref WHERE artifact_id = ?",
                (row["target_ref_artifact_id"],),
            ).fetchone()
        except sqlite3.Error as exc:
            raise CreationApplicationError(
                "decision target ref read failed"
            ) from exc
        if ref_row is None:
            raise CreationApplicationError(
                f"target ref {row['target_ref_artifact_id']!r} not registered"
            )
        try:
            target_ref = ArtifactRef(
                artifact_id=ref_row["artifact_id"],
                schema_version=ref_row["schema_version"],
                content_hash=ref_row["content_hash"],
            )

            source = SourceRef(
                kind=SourceKind.AUTHOR,
                actor_id=row["actor_id"],
            )

            created_at_str = row["created_at"]
            if created_at_str.endswith("Z"):
                created_at_str = created_at_str.replace("Z", "+00:00")
            created_at = datetime.fromisoformat(created_at_str)

            decision = AuthorDecision(
                decision_id=row["decision_id"],
                schema_version=row["schema_version"],
                task_id=row["task_id"],
                decision_type=DecisionType(row["decision_type"]),
                target_ref=target_ref,
                outcome=DecisionOutcome(row["outcome"]),
                based_on_task_revision=row["based_on_task_revision"],
                author_id=row["author_id"],
                reason=row["reason"],
                source=source,
                created_at=created_at,
                content_hash=row["content_hash"],
            )
        except (ValueError, TypeError, KeyError) as exc:
            raise CreationApplicationError(
                "decision row deserialisation failed"
            ) from exc

        # Verify content hash
        try:
            hash_ok = verify_content_hash(
                canonicalize_json_value(decision.content_payload()),
                decision.content_hash,
            )
        except Exception as exc:
            raise CreationApplicationError(
                f"content hash verification error for {decision.decision_id!r}"
            ) from exc
        if not hash_ok:
            raise CreationApplicationError(
                f"stored decision content_hash mismatch for {decision.decision_id!r}"
            )

        return decision

    def add(self, decision: AuthorDecision) -> None:
        """Persist a new immutable AuthorDecision (append-only)."""
        # Ensure target_ref is registered in creation_artifact_ref
        existing = self._conn.execute(
            "SELECT schema_version, content_hash FROM creation_artifact_ref "
            "WHERE artifact_id = ?",
            (decision.target_ref.artifact_id,),
        ).fetchone()
        if existing is None:
            self._conn.execute(
                "INSERT INTO creation_artifact_ref "
                "(artifact_id, schema_version, content_hash) VALUES (?, ?, ?)",
                (
                    decision.target_ref.artifact_id,
                    decision.target_ref.schema_version,
                    decision.target_ref.content_hash,
                ),
            )
        elif (
            existing["schema_version"] != decision.target_ref.schema_version
            or existing["content_hash"] != decision.target_ref.content_hash
        ):
            raise CreationApplicationError(
                f"artifact_id {decision.target_ref.artifact_id!r} identity mismatch"
            )

        created_at = (
            decision.created_at.astimezone(timezone.utc)
            .isoformat(timespec="microseconds")
        )

        try:
            self._conn.execute(
                "INSERT INTO creation_author_decision ("
                "decision_id, schema_version, task_id, decision_type, "
                "target_ref_artifact_id, outcome, based_on_task_revision, "
                "author_id, reason, actor_kind, actor_id, content_hash, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    decision.decision_id,
                    decision.schema_version,
                    decision.task_id,
                    decision.decision_type.value,
                    decision.target_ref.artifact_id,
                    decision.outcome.value,
                    decision.based_on_task_revision,
                    decision.author_id,
                    decision.reason,
                    "AUTHOR",
                    decision.author_id,
                    decision.content_hash,
                    created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise CreationApplicationError(
                f"decision {decision.decision_id!r} already exists"
            ) from exc
        except sqlite3.Error as exc:
            raise CreationApplicationError("decision write failed") from exc

    def add_consumption(self, record: DecisionConsumptionRecord) -> None:
        """Record a decision consumption (append-only, unique decision_id)."""
        try:
            self._conn.execute(
                "INSERT INTO creation_decision_consumption ("
                "consumption_id, decision_id, operation_id, task_id, "
                "consumed_at_task_revision, consumed_at"
                ") VALUES (?, ?, ?, ?, ?, ?)",
                (
                    record.consumption_id,
                    record.decision_id,
                    record.operation_id,
                    record.task_id,
                    record.consumed_at_task_revision,
                    record.consumed_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise CreationApplicationError(
                f"consumption for decision {record.decision_id!r} already exists "
                f"or operation_id {record.operation_id!r} already linked"
            ) from exc
        except sqlite3.Error as exc:
            raise CreationApplicationError("consumption write failed") from exc

    def get_consumption_by_decision_id(
        self, decision_id: str
    ) -> DecisionConsumptionRecord | None:
        """Return the consumption record for *decision_id*, or None."""
        try:
            row = self._conn.execute(
                "SELECT consumption_id, decision_id, operation_id, task_id, "
                "consumed_at_task_revision, consumed_at "
                "FROM creation_decision_consumption WHERE decision_id = ?",
                (decision_id,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise CreationApplicationError("consumption read failed") from exc
        if row is None:
            return None
        return DecisionConsumptionRecord(
            consumption_id=row["consumption_id"],
            decision_id=row["decision_id"],
            operation_id=row["operation_id"],
            task_id=row["task_id"],
            consumed_at_task_revision=row["consumed_at_task_revision"],
            consumed_at=row["consumed_at"],
        )
