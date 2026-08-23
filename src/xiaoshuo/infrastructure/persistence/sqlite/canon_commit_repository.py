"""Specialized Canon commit persistence boundary.

The generic ChapterTask repository deliberately remains unable to write
``COMMITTING``/``COMPLETED``.  C3 uses the narrowly scoped intent method
below.  C4a adds only the narrowly-scoped Apply/Recovery completion helpers;
the generic Task repository remains unable to write Canon terminal states.
"""
from __future__ import annotations

from dataclasses import dataclass
import sqlite3

from xiaoshuo.application.creation.errors import (
    ArtifactIdentityConflict,
    CreationApplicationError,
    LegacyJournalUnbound,
    RevisionConflict,
    UnsupportedPersistenceBoundary,
)
from xiaoshuo.application.creation.repository import (
    CanonCommitIntentRecord,
    CanonCommitJournalView,
)
from xiaoshuo.domain.creation import SCHEMA_VERSION, ArtifactRef, ChapterTask, ChapterTaskStatus


@dataclass(frozen=True)
class CanonCommitReceiptView:
    receipt_id: str
    journal_id: str
    receipt_ref_artifact_id: str
    created_at: str


class SqliteCanonCommitRepository:
    """C3 Intent plus C4a lifecycle access to v003 Canon rows."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get_receipt(self, receipt_id: str) -> CanonCommitReceiptView | None:
        row = self._conn.execute(
            "SELECT receipt_id, journal_id, receipt_ref_artifact_id, created_at "
            "FROM canon_commit_receipt WHERE receipt_id = ?", (receipt_id,)
        ).fetchone()
        if row is None:
            return None
        return CanonCommitReceiptView(
            receipt_id=row["receipt_id"], journal_id=row["journal_id"],
            receipt_ref_artifact_id=row["receipt_ref_artifact_id"], created_at=row["created_at"],
        )

    def get_journal(self, journal_id: str) -> CanonCommitJournalView | None:
        if not self._table_exists("canon_commit_journal"):
            return None
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(canon_commit_journal)")}
        if "base_bundle_ref_artifact_id" not in columns:
            if self._conn.execute("SELECT 1 FROM canon_commit_journal WHERE journal_id = ?", (journal_id,)).fetchone():
                raise LegacyJournalUnbound("v003 Canon journal is not bound to active identity")
            return None
        row = self._conn.execute(
            "SELECT journal_id, task_id, operation_id, decision_id, "
            "changeset_ref_artifact_id, base_bundle_ref_artifact_id, "
            "target_bundle_ref_artifact_id, base_bundle_content_hash, "
            "target_bundle_content_hash, base_manifest_hash, base_world_hash, "
            "target_manifest_hash, target_world_hash, "
            "canonical_bundle_schema_version, created_at "
            "FROM canon_commit_journal WHERE journal_id = ?",
            (journal_id,),
        ).fetchone()
        if row is None:
            if self._table_exists("canon_commit_journal_v003_legacy") and self._conn.execute(
                "SELECT 1 FROM canon_commit_journal_v003_legacy WHERE journal_id = ?", (journal_id,)
            ).fetchone():
                raise LegacyJournalUnbound("legacy Canon journal cannot be consumed as active")
            return None
        changeset = self._get_artifact_ref(row["changeset_ref_artifact_id"])
        base_bundle = self._get_artifact_ref(row["base_bundle_ref_artifact_id"])
        target_bundle = self._get_artifact_ref(row["target_bundle_ref_artifact_id"])
        self._validate_journal_identity(row, changeset, base_bundle, target_bundle)
        return CanonCommitJournalView(
            journal_id=row["journal_id"],
            task_id=row["task_id"],
            operation_id=row["operation_id"],
            decision_id=row["decision_id"],
            changeset_ref=changeset,
            target_bundle_ref=target_bundle,
            base_manifest_hash=row["base_manifest_hash"],
            target_manifest_hash=row["target_manifest_hash"],
            created_at=row["created_at"],
            base_bundle_ref=base_bundle,
            base_bundle_content_hash=row["base_bundle_content_hash"],
            target_bundle_content_hash=row["target_bundle_content_hash"],
            base_world_hash=row["base_world_hash"],
            target_world_hash=row["target_world_hash"],
            canonical_bundle_schema_version=row["canonical_bundle_schema_version"],
        )

    def complete_apply(
        self,
        task_before: ChapterTask,
        completed_task: ChapterTask,
        *,
        expected_revision: int,
        journal_id: str,
        receipt_id: str,
        receipt_ref: ArtifactRef,
        created_at: str,
    ) -> None:
        raise UnsupportedPersistenceBoundary("Canon completion is disabled during C4-PRE")

    def mark_recovery(
        self,
        task_before: ChapterTask,
        recovery_task: ChapterTask,
        *,
        expected_revision: int,
    ) -> None:
        raise UnsupportedPersistenceBoundary("Canon recovery is disabled during C4-PRE")

    def resume_recovery(
        self,
        task_before: ChapterTask,
        committing_task: ChapterTask,
        *,
        expected_revision: int,
    ) -> None:
        raise UnsupportedPersistenceBoundary("Canon recovery is disabled during C4-PRE")

    def create_intent(
        self,
        record: CanonCommitIntentRecord,
        transitioned_task: ChapterTask,
        *,
        expected_revision: int,
    ) -> None:
        """Append an intent and move exactly one approved task to COMMITTING.

        Only status/revision/recovery/timestamp columns are updated.  This is
        intentionally not a generic aggregate replacement, so the seven task
        role references cannot be added, removed, or replaced by C3.
        """
        if transitioned_task.status is not ChapterTaskStatus.COMMITTING:
            raise UnsupportedPersistenceBoundary(
                "Canon intent requires a COMMITTING transitioned task"
            )
        if transitioned_task.commit_receipt_ref is not None or transitioned_task.recovery is not None:
            raise UnsupportedPersistenceBoundary(
                "Canon intent cannot write a receipt or recovery information"
            )
        if transitioned_task.aggregate_revision != expected_revision + 1:
            raise UnsupportedPersistenceBoundary(
                "Canon intent transitioned revision is invalid"
            )
        if record.task_id != transitioned_task.task_id:
            raise UnsupportedPersistenceBoundary("Canon intent task identity mismatch")
        if record.changeset_ref != transitioned_task.pending_changeset_ref:
            raise UnsupportedPersistenceBoundary(
                "Canon intent ChangeSet ref must equal the persisted pending role ref"
            )
        self._validate_intent_record(record)
        try:
            current = self._conn.execute(
                "SELECT status, aggregate_revision, pending_changeset_ref_artifact_id "
                "FROM chapter_task WHERE task_id = ?",
                (record.task_id,),
            ).fetchone()
            if (
                current is None
                or current["status"] != ChapterTaskStatus.CHANGESET_APPROVAL_PENDING.value
                or current["aggregate_revision"] != expected_revision
                or current["pending_changeset_ref_artifact_id"] != record.changeset_ref.artifact_id
            ):
                raise RevisionConflict(
                    f"expected revision {expected_revision} and pending ChangeSet ref "
                    f"for Canon intent task {record.task_id!r} did not match"
                )
            # Validate identities before changing the Task row.  New refs are
            # registered only after the conditional update succeeds, so a
            # zero-row conflict leaves no artifact residue even when this
            # repository is exercised directly.
            self._validate_artifact_ref(record.changeset_ref)
            self._validate_artifact_ref(record.base_bundle_ref)
            self._validate_artifact_ref(record.target_bundle_ref)
            cursor = self._conn.execute(
                "UPDATE chapter_task SET status = ?, last_stable_status = ?, "
                "aggregate_revision = ?, recovery_failed_operation_id = NULL, "
                "recovery_error_code = NULL, recovery_retry_from_status = NULL, "
                "updated_at = ? WHERE task_id = ? AND aggregate_revision = ? "
                "AND status = 'CHANGESET_APPROVAL_PENDING' "
                "AND pending_changeset_ref_artifact_id = ?",
                (
                    transitioned_task.status.value,
                    transitioned_task.last_stable_status.value,
                    transitioned_task.aggregate_revision,
                    transitioned_task.updated_at.isoformat(),
                    transitioned_task.task_id,
                    expected_revision,
                    record.changeset_ref.artifact_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RevisionConflict(
                    f"expected revision {expected_revision} for Canon intent task "
                    f"{transitioned_task.task_id!r} did not match"
                )
            self._ensure_artifact_ref(record.changeset_ref)
            self._ensure_artifact_ref(record.base_bundle_ref)
            self._ensure_artifact_ref(record.target_bundle_ref)
            self._conn.execute(
                "INSERT INTO canon_commit_journal ("
                "journal_id, task_id, operation_id, decision_id, "
                "changeset_ref_artifact_id, base_bundle_ref_artifact_id, "
                "target_bundle_ref_artifact_id, base_bundle_content_hash, "
                "target_bundle_content_hash, base_manifest_hash, base_world_hash, "
                "target_manifest_hash, target_world_hash, canonical_bundle_schema_version, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.journal_id,
                    record.task_id,
                    record.operation_id,
                    record.decision_id,
                    record.changeset_ref.artifact_id,
                    record.base_bundle_ref.artifact_id,
                    record.target_bundle_ref.artifact_id,
                    record.base_bundle_content_hash,
                    record.target_bundle_content_hash,
                    record.base_manifest_hash,
                    record.base_world_hash,
                    record.target_manifest_hash,
                    record.target_world_hash,
                    record.canonical_bundle_schema_version,
                    record.created_at,
                ),
            )
        except RevisionConflict:
            raise
        except sqlite3.IntegrityError as exc:
            raise CreationApplicationError("Canon intent write failed") from exc
        except sqlite3.Error as exc:
            raise CreationApplicationError("Canon intent write failed") from exc

    def _ensure_artifact_ref(self, ref: ArtifactRef) -> None:
        row = self._conn.execute(
            "SELECT schema_version, content_hash FROM creation_artifact_ref "
            "WHERE artifact_id = ?",
            (ref.artifact_id,),
        ).fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO creation_artifact_ref "
                "(artifact_id, schema_version, content_hash) VALUES (?, ?, ?)",
                (ref.artifact_id, ref.schema_version, ref.content_hash),
            )
            return
        if row["schema_version"] != ref.schema_version or row["content_hash"] != ref.content_hash:
            raise ArtifactIdentityConflict(
                f"artifact_id {ref.artifact_id!r} identity mismatch"
            )

    def _get_artifact_ref(self, artifact_id: str) -> ArtifactRef:
        row = self._conn.execute(
            "SELECT artifact_id, schema_version, content_hash "
            "FROM creation_artifact_ref WHERE artifact_id = ?",
            (artifact_id,),
        ).fetchone()
        if row is None:
            raise CreationApplicationError("Canon journal artifact reference is missing")
        try:
            return ArtifactRef(row["artifact_id"], row["schema_version"], row["content_hash"])
        except Exception as exc:
            raise UnsupportedPersistenceBoundary("Canon journal artifact reference is invalid") from exc


    def _validate_artifact_ref(self, ref: ArtifactRef) -> None:
        if not isinstance(ref, ArtifactRef) or ref.schema_version != SCHEMA_VERSION or not _is_hash(ref.content_hash):
            raise UnsupportedPersistenceBoundary("Canon artifact reference schema or hash is unsupported")
        row = self._conn.execute(
            "SELECT schema_version, content_hash FROM creation_artifact_ref "
            "WHERE artifact_id = ?",
            (ref.artifact_id,),
        ).fetchone()
        if row is not None and (
            row["schema_version"] != ref.schema_version
            or row["content_hash"] != ref.content_hash
        ):
            raise ArtifactIdentityConflict(
                f"artifact_id {ref.artifact_id!r} identity mismatch"
            )

    def _validate_intent_record(self, record: CanonCommitIntentRecord) -> None:
        if record.base_bundle_ref is None:
            raise UnsupportedPersistenceBoundary("Canon intent requires a project-bound base bundle ref")
        if type(record.canonical_bundle_schema_version) is not int or record.canonical_bundle_schema_version != SCHEMA_VERSION:
            raise UnsupportedPersistenceBoundary("Canon intent bundle schema is unsupported")
        refs = (record.changeset_ref, record.base_bundle_ref, record.target_bundle_ref)
        for ref in refs:
            self._validate_artifact_ref(ref)
            if ref.schema_version != record.canonical_bundle_schema_version:
                raise UnsupportedPersistenceBoundary("Canon intent ArtifactRef schema is inconsistent")
        hashes = (
            record.base_bundle_content_hash,
            record.target_bundle_content_hash,
            record.base_manifest_hash,
            record.base_world_hash,
            record.target_manifest_hash,
            record.target_world_hash,
        )
        if any(not _is_hash(value) for value in hashes):
            raise UnsupportedPersistenceBoundary("Canon intent identity is incomplete")
        if record.base_bundle_content_hash != record.base_bundle_ref.content_hash or record.target_bundle_content_hash != record.target_bundle_ref.content_hash:
            raise UnsupportedPersistenceBoundary("Canon bundle content identity is inconsistent")

    @staticmethod
    def _validate_journal_identity(row, changeset: ArtifactRef, base_bundle: ArtifactRef, target_bundle: ArtifactRef) -> None:
        schema = row["canonical_bundle_schema_version"]
        if type(schema) is not int or schema != SCHEMA_VERSION:
            raise UnsupportedPersistenceBoundary("Canon journal bundle schema is unsupported")
        for ref in (changeset, base_bundle, target_bundle):
            if ref.schema_version != schema or not _is_hash(ref.content_hash):
                raise UnsupportedPersistenceBoundary("Canon journal ArtifactRef identity is invalid")
        for key in (
            "base_bundle_content_hash", "target_bundle_content_hash", "base_manifest_hash",
            "base_world_hash", "target_manifest_hash", "target_world_hash",
        ):
            if not _is_hash(row[key]):
                raise UnsupportedPersistenceBoundary("Canon journal identity is incomplete")
        if row["base_bundle_content_hash"] != base_bundle.content_hash or row["target_bundle_content_hash"] != target_bundle.content_hash:
            raise ArtifactIdentityConflict("Canon journal bundle content identity is inconsistent")

    def _table_exists(self, table: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (table,)
        ).fetchone() is not None


def _is_hash(value: object) -> bool:
    return isinstance(value, str) and len(value) == 71 and value.startswith("sha256:") and all(ch in "0123456789abcdef" for ch in value[7:])
