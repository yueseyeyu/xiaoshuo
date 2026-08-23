"""SQLite adapter for the independent C4a Apply fact graph.

The adapter owns only the narrow Canon Apply/Recovery completion paths.  The
generic ChapterTask repository remains deliberately unable to write
``RECOVERY_REQUIRED`` or ``COMPLETED`` Canon facts.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import sqlite3

from xiaoshuo.application.creation.canon_results import (
    CanonCompletedGraphEvidence,
    CanonRecoveryGraphEvidence,
)
from xiaoshuo.application.creation.errors import (
    ArtifactIdentityConflict,
    CanonApplyConflict,
    CanonApplyRecoveryRequired,
    CanonCompletionConflict,
    IdempotencyConflict,
    RevisionConflict,
)
from xiaoshuo.domain.creation import ArtifactRef, ChapterTaskStatus
from xiaoshuo.domain.creation.state_machine import (
    RevisionConflict as DomainRevisionConflict,
    complete_task_with_receipt as complete_task_with_receipt_domain,
    complete_verified_canon_recovery as complete_verified_canon_recovery_domain,
)

from .canon_commit_repository import CanonCommitJournalView, SqliteCanonCommitRepository
from .serialization import row_to_chapter_task


def _hash(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(char in "0123456789abcdef" for char in value[7:])
    )


_OBSERVED_PHASES = frozenset(
    {"PROJECTION_COMMITTED", "RECEIPT_PAYLOAD_READY", "COMPLETED"}
)


@dataclass(frozen=True, slots=True)
class C4aApplyAttempt:
    apply_attempt_id: str
    project_id: str
    apply_key: str
    request_digest: str
    journal_id: str
    task_id: str
    operation_id: str
    decision_id: str
    base_bundle_ref: ArtifactRef
    base_version_id: str
    base_pointer_content_hash: str
    target_bundle_ref: ArtifactRef
    target_version_id: str
    target_pointer_content_hash: str
    target_marker_content_hash: str
    target_manifest_hash: str
    target_world_hash: str
    operator_identity: str
    created_at: str

    @property
    def base_bundle_content_hash(self) -> str:
        return self.base_bundle_ref.content_hash

    @property
    def target_bundle_content_hash(self) -> str:
        return self.target_bundle_ref.content_hash


@dataclass(frozen=True, slots=True)
class C4aApplyEvent:
    event_id: str
    apply_attempt_id: str
    project_id: str
    phase: str
    result: str
    error_code: str | None
    recovery_failed_operation_id: str | None
    replay_envelope_json: str | None
    replay_envelope_hash: str | None
    receipt_payload_ref: ArtifactRef | None
    created_at: str
    observed_pointer_content_hash: str | None = None
    observed_marker_content_hash: str | None = None


class C4aApplyRepositoryError(RuntimeError):
    """The C4a fact graph cannot be read or written safely."""


class SqliteC4aApplyRepository:
    """Specialized v006 repository; callers own the SQLite transaction."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        if not isinstance(connection, sqlite3.Connection):
            raise TypeError("an open SQLite connection is required")
        self.connection = connection

    def get_attempt_by_key(self, apply_key: str) -> C4aApplyAttempt | None:
        row = self.connection.execute(
            "SELECT * FROM canon_apply_attempt WHERE apply_key = ?", (apply_key,)
        ).fetchone()
        return None if row is None else self._validated_attempt(row)

    get_attempt_by_apply_key = get_attempt_by_key

    def get_attempt(self, apply_attempt_id: str) -> C4aApplyAttempt | None:
        row = self.connection.execute(
            "SELECT * FROM canon_apply_attempt WHERE apply_attempt_id = ?",
            (apply_attempt_id,),
        ).fetchone()
        return None if row is None else self._validated_attempt(row)

    def get_attempt_for_project(self, project_id: str) -> C4aApplyAttempt | None:
        row = self.connection.execute(
            "SELECT * FROM canon_apply_attempt WHERE project_id = ?", (project_id,)
        ).fetchone()
        return None if row is None else self._validated_attempt(row)

    def get_journal(self, journal_id: str) -> CanonCommitJournalView | None:
        return SqliteCanonCommitRepository(self.connection).get_journal(journal_id)

    def list_events(self, apply_attempt_id: str, project_id: str) -> tuple[C4aApplyEvent, ...]:
        rows = self.connection.execute(
            "SELECT * FROM canon_apply_event WHERE apply_attempt_id = ? "
            "AND project_id = ? ORDER BY created_at, event_id",
            (apply_attempt_id, project_id),
        ).fetchall()
        events = tuple(self._event(row) for row in rows)
        for event in events:
            self._validate_event_observation(event)
        return events

    def get_event(
        self, apply_attempt_id: str, project_id: str, phase: str
    ) -> C4aApplyEvent | None:
        row = self.connection.execute(
            "SELECT * FROM canon_apply_event WHERE apply_attempt_id = ? "
            "AND project_id = ? AND phase = ?",
            (apply_attempt_id, project_id, phase),
        ).fetchone()
        if row is None:
            return None
        event = self._event(row)
        self._validate_event_observation(event)
        return event

    def create_prepared(self, attempt: C4aApplyAttempt, event: C4aApplyEvent) -> None:
        if event.phase != "PREPARED" or event.result != "PREPARED":
            raise CanonApplyConflict("C4a Transaction A requires a PREPARED event")
        self._validate_attempt_binding(attempt)
        try:
            self.connection.execute(
                "INSERT INTO canon_apply_attempt ("
                "apply_attempt_id, project_id, apply_key, request_digest, journal_id, "
                "task_id, operation_id, decision_id, base_bundle_ref_artifact_id, "
                "base_bundle_schema_version, base_bundle_content_hash, base_version_id, "
                "base_pointer_content_hash, target_bundle_ref_artifact_id, "
                "target_bundle_schema_version, target_bundle_content_hash, target_version_id, "
                "target_pointer_content_hash, target_marker_content_hash, target_manifest_hash, "
                "target_world_hash, operator_identity, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    attempt.apply_attempt_id, attempt.project_id, attempt.apply_key,
                    attempt.request_digest, attempt.journal_id, attempt.task_id,
                    attempt.operation_id, attempt.decision_id,
                    attempt.base_bundle_ref.artifact_id, attempt.base_bundle_ref.schema_version,
                    attempt.base_bundle_ref.content_hash, attempt.base_version_id,
                    attempt.base_pointer_content_hash, attempt.target_bundle_ref.artifact_id,
                    attempt.target_bundle_ref.schema_version, attempt.target_bundle_ref.content_hash,
                    attempt.target_version_id, attempt.target_pointer_content_hash,
                    attempt.target_marker_content_hash, attempt.target_manifest_hash,
                    attempt.target_world_hash, attempt.operator_identity,
                    attempt.created_at,
                ),
            )
            self.append_event(event)
        except sqlite3.IntegrityError as exc:
            if "apply_key" in str(exc):
                raise IdempotencyConflict("C4a apply_key already exists") from exc
            raise CanonApplyConflict("C4a Transaction A could not be persisted") from exc
        except sqlite3.Error as exc:
            raise C4aApplyRepositoryError("C4a Transaction A could not be persisted") from exc

    def append_event(self, event: C4aApplyEvent) -> None:
        self._validate_event_observation(event)
        receipt = event.receipt_payload_ref
        try:
            self.connection.execute(
                "INSERT INTO canon_apply_event ("
                "event_id, apply_attempt_id, project_id, phase, result, error_code, "
                "recovery_failed_operation_id, replay_envelope_json, replay_envelope_hash, "
                "receipt_payload_ref_artifact_id, receipt_payload_schema_version, "
                "receipt_payload_content_hash, observed_pointer_content_hash, "
                "observed_marker_content_hash, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event.event_id, event.apply_attempt_id, event.project_id,
                    event.phase, event.result, event.error_code,
                    event.recovery_failed_operation_id, event.replay_envelope_json,
                    event.replay_envelope_hash, None if receipt is None else receipt.artifact_id,
                    None if receipt is None else receipt.schema_version,
                    None if receipt is None else receipt.content_hash,
                    event.observed_pointer_content_hash, event.observed_marker_content_hash,
                    event.created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise CanonApplyConflict("C4a event violates its durable contract") from exc
        except sqlite3.Error as exc:
            raise C4aApplyRepositoryError("C4a event could not be persisted") from exc

    def resolve_artifact_ref(self, artifact_id: str) -> ArtifactRef | None:
        row = self.connection.execute(
            "SELECT artifact_id, schema_version, content_hash "
            "FROM creation_artifact_ref WHERE artifact_id = ?", (artifact_id,)
        ).fetchone()
        if row is None:
            return None
        try:
            return ArtifactRef(row["artifact_id"], row["schema_version"], row["content_hash"])
        except Exception as exc:
            raise C4aApplyRepositoryError("invalid ArtifactRef registry row") from exc

    def register_artifact_ref(self, ref: ArtifactRef) -> None:
        current = self.resolve_artifact_ref(ref.artifact_id)
        if current is None:
            try:
                self.connection.execute(
                    "INSERT INTO creation_artifact_ref "
                    "(artifact_id, schema_version, content_hash) VALUES (?, ?, ?)",
                    (ref.artifact_id, ref.schema_version, ref.content_hash),
                )
            except sqlite3.Error as exc:
                raise C4aApplyRepositoryError("ArtifactRef registration failed") from exc
            return
        if current != ref:
            raise ArtifactIdentityConflict("ArtifactRef identity mismatch")

    def mark_recovery(
        self,
        attempt: C4aApplyAttempt,
        *,
        expected_revision: int,
        failed_operation_id: str,
        error_code: str,
        event_id: str,
        created_at: str,
    ) -> int:
        self._validate_attempt_binding(attempt)
        row = self._task_row(attempt.task_id)
        if row is None or row["project_id"] != attempt.project_id:
            raise CanonApplyRecoveryRequired("C4a Task binding is missing")
        if row["aggregate_revision"] != expected_revision:
            raise RevisionConflict("C4a recovery revision is stale")
        if row["status"] == ChapterTaskStatus.RECOVERY_REQUIRED.value:
            return int(row["aggregate_revision"])
        if row["status"] != ChapterTaskStatus.COMMITTING.value or row["commit_receipt_ref_artifact_id"] is not None:
            raise CanonApplyRecoveryRequired("C4a recovery requires an uncompleted COMMITTING Task")
        new_revision = expected_revision + 1
        cursor = self.connection.execute(
            "UPDATE chapter_task SET status='RECOVERY_REQUIRED', "
            "recovery_failed_operation_id=?, recovery_error_code=?, "
            "recovery_retry_from_status='COMMITTING', aggregate_revision=?, updated_at=? "
            "WHERE task_id=? AND aggregate_revision=? AND status='COMMITTING'",
            (failed_operation_id, error_code, new_revision, created_at, attempt.task_id, expected_revision),
        )
        if cursor.rowcount != 1:
            raise RevisionConflict("C4a recovery Task update lost its revision race")
        self._insert_audit(
            event_id=event_id + ":audit",
            task_id=attempt.task_id,
            project_id=attempt.project_id,
            event_type="CANON_APPLY_RECOVERY_REQUIRED",
            before_revision=expected_revision,
            after_revision=new_revision,
            operation_id=attempt.operation_id,
            created_at=created_at,
        )
        self.append_event(
            C4aApplyEvent(
                event_id=event_id,
                apply_attempt_id=attempt.apply_attempt_id,
                project_id=attempt.project_id,
                phase="RECOVERY_REQUIRED",
                result="RECOVERY_REQUIRED",
                error_code=error_code,
                recovery_failed_operation_id=failed_operation_id,
                replay_envelope_json=None,
                replay_envelope_hash=None,
                receipt_payload_ref=None,
                created_at=created_at,
            )
        )
        return new_revision

    def complete(
        self,
        attempt: C4aApplyAttempt,
        *,
        expected_revision: int,
        receipt_id: str,
        receipt_ref: ArtifactRef,
        replay_envelope_json: str,
        replay_envelope_hash: str,
        event_id: str,
        created_at: str,
    ) -> int:
        self._validate_attempt_binding(attempt)
        row = self._task_row(attempt.task_id)
        if row is None or row["project_id"] != attempt.project_id:
            raise CanonCompletionConflict("C4a Task binding is missing")
        if row["aggregate_revision"] != expected_revision:
            raise RevisionConflict("C4a completion revision is stale")
        if row["status"] != ChapterTaskStatus.COMMITTING.value or row["commit_receipt_ref_artifact_id"] is not None:
            raise CanonCompletionConflict("C4a completion Task state is invalid")
        if not _hash(replay_envelope_hash) or replay_envelope_hash != _digest(replay_envelope_json):
            raise CanonCompletionConflict("C4a replay envelope identity is invalid")
        try:
            completed_task = complete_task_with_receipt_domain(
                self._load_domain_task(attempt.task_id), receipt_ref, expected_revision
            )
        except DomainRevisionConflict as exc:
            raise RevisionConflict(str(exc)) from exc
        except Exception as exc:
            raise CanonCompletionConflict("C4a Apply completion domain transition is invalid") from exc
        return self._insert_completion_facts(
            attempt,
            completed_task=completed_task,
            expected_revision=expected_revision,
            receipt_id=receipt_id,
            receipt_ref=receipt_ref,
            replay_envelope_json=replay_envelope_json,
            replay_envelope_hash=replay_envelope_hash,
            event_id=event_id,
            created_at=created_at,
            audit_event_type="CANON_APPLY_COMPLETED",
        )

    def complete_verified_canon_recovery(
        self,
        attempt: C4aApplyAttempt,
        *,
        expected_revision: int,
        receipt_id: str,
        receipt_ref: ArtifactRef,
        replay_envelope_json: str,
        replay_envelope_hash: str,
        event_id: str,
        created_at: str,
    ) -> int:
        """Commit only the domain-approved RECOVERY_REQUIRED completion path."""
        self._validate_attempt_binding(attempt)
        row = self._task_row(attempt.task_id)
        if row is None or row["project_id"] != attempt.project_id:
            raise CanonCompletionConflict("C4a recovery Task binding is missing")
        if row["status"] != ChapterTaskStatus.RECOVERY_REQUIRED.value:
            raise CanonCompletionConflict(
                "verified C4a recovery completion requires RECOVERY_REQUIRED Task"
            )
        if self.get_event(attempt.apply_attempt_id, attempt.project_id, "RECOVERY_REQUIRED") is None:
            raise CanonCompletionConflict("verified C4a recovery event is missing")
        if not _hash(replay_envelope_hash) or replay_envelope_hash != _digest(replay_envelope_json):
            raise CanonCompletionConflict("C4a replay envelope identity is invalid")
        try:
            completed_task = complete_verified_canon_recovery_domain(
                self._load_domain_task(attempt.task_id), receipt_ref, expected_revision
            )
        except DomainRevisionConflict as exc:
            raise RevisionConflict(str(exc)) from exc
        except Exception as exc:
            raise CanonCompletionConflict(
                "verified C4a recovery domain transition is invalid"
            ) from exc
        return self._insert_completion_facts(
            attempt,
            completed_task=completed_task,
            expected_revision=expected_revision,
            receipt_id=receipt_id,
            receipt_ref=receipt_ref,
            replay_envelope_json=replay_envelope_json,
            replay_envelope_hash=replay_envelope_hash,
            event_id=event_id,
            created_at=created_at,
            audit_event_type="CANON_APPLY_RECOVERY_COMPLETED",
        )

    def _insert_completion_facts(
        self,
        attempt: C4aApplyAttempt,
        *,
        completed_task,
        expected_revision: int,
        receipt_id: str,
        receipt_ref: ArtifactRef,
        replay_envelope_json: str,
        replay_envelope_hash: str,
        event_id: str,
        created_at: str,
        audit_event_type: str,
    ) -> int:
        self.register_artifact_ref(receipt_ref)
        try:
            self.connection.execute(
                "INSERT INTO canon_commit_receipt "
                "(receipt_id, journal_id, receipt_ref_artifact_id, created_at) VALUES (?, ?, ?, ?)",
                (receipt_id, attempt.journal_id, receipt_ref.artifact_id, created_at),
            )
            new_revision = expected_revision + 1
            cursor = self.connection.execute(
                "UPDATE chapter_task SET status='COMPLETED', last_stable_status='COMPLETED', "
                "commit_receipt_ref_artifact_id=?, recovery_failed_operation_id=NULL, "
                "recovery_error_code=NULL, recovery_retry_from_status=NULL, "
                "aggregate_revision=?, updated_at=? WHERE task_id=? AND aggregate_revision=?",
                (receipt_ref.artifact_id, completed_task.aggregate_revision, created_at, attempt.task_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise RevisionConflict("C4a completion Task update lost its revision race")
            self._insert_audit(
                event_id=attempt.apply_attempt_id + ":completed:audit",
                task_id=attempt.task_id,
                project_id=attempt.project_id,
                event_type=audit_event_type,
                before_revision=expected_revision,
                after_revision=new_revision,
                operation_id=attempt.operation_id,
                created_at=created_at,
            )
            self.append_event(
                C4aApplyEvent(
                    event_id=event_id,
                    apply_attempt_id=attempt.apply_attempt_id,
                    project_id=attempt.project_id,
                    phase="COMPLETED",
                    result="COMPLETED",
                    error_code=None,
                    recovery_failed_operation_id=None,
                    replay_envelope_json=replay_envelope_json,
                    replay_envelope_hash=replay_envelope_hash,
                    receipt_payload_ref=receipt_ref,
                    created_at=created_at,
                    observed_pointer_content_hash=attempt.target_pointer_content_hash,
                    observed_marker_content_hash=attempt.target_marker_content_hash,
                )
            )
            return new_revision
        except sqlite3.IntegrityError as exc:
            raise CanonCompletionConflict("C4a completion facts conflict") from exc
        except sqlite3.Error as exc:
            raise C4aApplyRepositoryError("C4a completion facts could not be persisted") from exc

    def _task_row(self, task_id: str):
        return self.connection.execute(
            "SELECT task_id, project_id, status, aggregate_revision, "
            "commit_receipt_ref_artifact_id, recovery_failed_operation_id, "
            "recovery_error_code, recovery_retry_from_status "
            "FROM chapter_task WHERE task_id = ?", (task_id,)
        ).fetchone()

    def _load_domain_task(self, task_id: str):
        row = self.connection.execute(
            "SELECT * FROM chapter_task WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row is None:
            raise CanonCompletionConflict("C4a Task is missing")
        refs = {
            ref_row["artifact_id"]: ArtifactRef(
                ref_row["artifact_id"], ref_row["schema_version"], ref_row["content_hash"]
            )
            for ref_row in self.connection.execute(
                "SELECT artifact_id, schema_version, content_hash FROM creation_artifact_ref"
            )
        }
        try:
            return row_to_chapter_task(row, refs)
        except Exception as exc:
            raise CanonCompletionConflict("C4a Task domain identity is invalid") from exc

    def _validate_attempt_binding(self, attempt: C4aApplyAttempt) -> None:
        row = self.connection.execute(
            "SELECT j.journal_id, j.task_id, j.operation_id, j.decision_id, "
            "j.changeset_ref_artifact_id, j.base_bundle_ref_artifact_id, "
            "j.target_bundle_ref_artifact_id, j.base_bundle_content_hash, "
            "j.target_bundle_content_hash, j.canonical_bundle_schema_version, "
            "j.target_manifest_hash, j.target_world_hash, "
            "t.project_id AS task_project_id, o.operation_id AS operation_row_id, "
            "d.decision_id AS decision_row_id, d.task_id AS decision_task_id, "
            "d.target_ref_artifact_id AS decision_target_ref, "
            "b.schema_version AS base_schema_version, b.content_hash AS base_content_hash, "
            "target.schema_version AS target_schema_version, target.content_hash AS target_content_hash "
            "FROM canon_commit_journal j "
            "JOIN chapter_task t ON t.task_id = j.task_id "
            "JOIN creation_operation o ON o.operation_id = j.operation_id "
            "JOIN creation_author_decision d ON d.decision_id = j.decision_id "
            "JOIN creation_artifact_ref changeset ON changeset.artifact_id = j.changeset_ref_artifact_id "
            "JOIN creation_artifact_ref b ON b.artifact_id = j.base_bundle_ref_artifact_id "
            "JOIN creation_artifact_ref target ON target.artifact_id = j.target_bundle_ref_artifact_id "
            "WHERE j.journal_id = ?",
            (attempt.journal_id,),
        ).fetchone()
        valid = (
            row is not None
            and row["journal_id"] == attempt.journal_id
            and row["task_id"] == attempt.task_id
            and row["operation_id"] == attempt.operation_id
            and row["operation_row_id"] == attempt.operation_id
            and row["decision_id"] == attempt.decision_id
            and row["decision_row_id"] == attempt.decision_id
            and row["task_project_id"] == attempt.project_id
            and row["decision_task_id"] == attempt.task_id
            and row["decision_target_ref"] == row["changeset_ref_artifact_id"]
            and row["base_bundle_ref_artifact_id"] == attempt.base_bundle_ref.artifact_id
            and row["base_schema_version"] == attempt.base_bundle_ref.schema_version
            and row["base_content_hash"] == attempt.base_bundle_ref.content_hash
            and row["base_bundle_content_hash"] == attempt.base_bundle_content_hash
            and row["target_bundle_ref_artifact_id"] == attempt.target_bundle_ref.artifact_id
            and row["target_schema_version"] == attempt.target_bundle_ref.schema_version
            and row["target_content_hash"] == attempt.target_bundle_ref.content_hash
            and row["target_bundle_content_hash"] == attempt.target_bundle_content_hash
            and row["target_manifest_hash"] == attempt.target_manifest_hash
            and row["target_world_hash"] == attempt.target_world_hash
            and row["canonical_bundle_schema_version"] == attempt.base_bundle_ref.schema_version
            and attempt.base_bundle_ref.schema_version == attempt.target_bundle_ref.schema_version
            and isinstance(attempt.operator_identity, str)
            and bool(attempt.operator_identity.strip())
            and all(
                _hash(value)
                for value in (
                    attempt.base_bundle_content_hash,
                    attempt.base_pointer_content_hash,
                    attempt.target_bundle_content_hash,
                    attempt.target_pointer_content_hash,
                    attempt.target_marker_content_hash,
                    attempt.target_manifest_hash,
                    attempt.target_world_hash,
                )
            )
        )
        if not valid:
            raise CanonApplyRecoveryRequired("C4a attempt durable binding is invalid")

    def _validated_attempt(self, row) -> C4aApplyAttempt:
        attempt = self._attempt(row)
        self._validate_attempt_binding(attempt)
        return attempt

    def _validate_event_observation(self, event: C4aApplyEvent) -> None:
        attempt = self.get_attempt(event.apply_attempt_id)
        if attempt is None or event.project_id != attempt.project_id:
            raise CanonApplyRecoveryRequired("C4a event attempt binding is invalid")
        pointer_hash = event.observed_pointer_content_hash
        marker_hash = event.observed_marker_content_hash
        if event.phase in _OBSERVED_PHASES:
            if (
                not _hash(pointer_hash)
                or not _hash(marker_hash)
                or pointer_hash != attempt.target_pointer_content_hash
                or marker_hash != attempt.target_marker_content_hash
            ):
                raise CanonApplyRecoveryRequired("C4a event projection observation is invalid")
        elif pointer_hash is not None or marker_hash is not None:
            raise CanonApplyRecoveryRequired("C4a event projection observation is premature")

    def get_task_state(self, task_id: str):
        """Return only the scalar state needed by the specialized C4a path."""
        return self._task_row(task_id)

    def get_receipt(self, journal_id: str):
        return self.connection.execute(
            "SELECT receipt_id, journal_id, receipt_ref_artifact_id, created_at "
            "FROM canon_commit_receipt WHERE journal_id = ?", (journal_id,)
        ).fetchone()

    def verify_completed_graph(
        self,
        *,
        project_id: str,
        task_id: str,
        apply_key: str,
        request_digest: str | None = None,
    ) -> CanonCompletedGraphEvidence:
        """Verify a completed graph with no recovery marker permitted."""
        return self._verify_completed_graph(
            project_id=project_id,
            task_id=task_id,
            apply_key=apply_key,
            request_digest=request_digest,
            allow_recovery=False,
        )

    def verify_recovery_completed_graph(
        self,
        *,
        project_id: str,
        task_id: str,
        apply_key: str,
        request_digest: str | None = None,
    ) -> CanonRecoveryGraphEvidence:
        """Verify a graph only through the explicit recovery boundary."""
        evidence = self._verify_completed_graph(
            project_id=project_id,
            task_id=task_id,
            apply_key=apply_key,
            request_digest=request_digest,
            allow_recovery=True,
        )
        if not evidence.recovery_marker:
            raise CanonApplyRecoveryRequired("C4a recovery graph marker is missing")
        events = self.list_events(evidence.apply_attempt_id, project_id)
        recovery = next((event for event in events if event.phase == "RECOVERY_REQUIRED"), None)
        if recovery is None:
            raise CanonApplyRecoveryRequired("C4a recovery graph event is missing")
        return CanonRecoveryGraphEvidence(
            completed=evidence,
            recovery_event_id=recovery.event_id,
        )

    # Explicit descriptive alias for recovery callers.
    verify_recovery_graph = verify_recovery_completed_graph

    def _verify_completed_graph(
        self,
        *,
        project_id: str,
        task_id: str,
        apply_key: str,
        request_digest: str | None = None,
        allow_recovery: bool = False,
    ) -> CanonCompletedGraphEvidence:
        """Verify one complete, read-only logical C4 graph.

        This is intentionally kept at the infrastructure boundary.  It reads
        the v006 graph and its v001-v004 bindings, performs no writes, and
        never treats SQLite row order as physical insertion-order evidence.
        ``RECOVERY_REQUIRED`` is accepted only for the explicit recovery
        verifier path and is never counted as a successful phase.
        """
        try:
            attempt = self.get_attempt_by_key(apply_key)
            if attempt is None or attempt.project_id != project_id or attempt.task_id != task_id:
                raise CanonApplyRecoveryRequired("C4a completed graph attempt identity is invalid")
            if request_digest is not None and attempt.request_digest != request_digest:
                raise CanonApplyRecoveryRequired("C4a completed graph request digest is invalid")

            events = self.list_events(attempt.apply_attempt_id, project_id)
            recovery = tuple(event for event in events if event.phase == "RECOVERY_REQUIRED")
            if recovery and not allow_recovery:
                raise CanonApplyRecoveryRequired(
                    "C4a completed graph contains an unapproved recovery fact"
                )
            if len(recovery) > 1:
                raise CanonApplyRecoveryRequired("C4a completed graph has duplicate recovery facts")
            expected = (
                "PREPARED",
                "VERSION_READY",
                "POINTER_WRITE_INTENDED",
                "POINTER_INSTALLED",
                "MARKER_WRITE_INTENDED",
                "PROJECTION_COMMITTED",
                "RECEIPT_PAYLOAD_READY",
                "COMPLETED",
            )
            successful = tuple(
                sorted(
                    (event for event in events if event.phase != "RECOVERY_REQUIRED"),
                    key=lambda event: expected.index(event.phase) if event.phase in expected else len(expected),
                )
            )
            if (
                tuple(event.phase for event in successful) != expected
                or len(events) != len(expected) + len(recovery)
                or len({event.phase for event in successful}) != len(expected)
            ):
                raise CanonApplyRecoveryRequired("C4a completed graph phase sequence is invalid")
            if any(event.result != event.phase for event in successful):
                raise CanonApplyRecoveryRequired("C4a completed graph phase result is invalid")

            completed = successful[-1]
            ready = successful[-2]
            projection = successful[-3]
            for event in successful:
                if event.apply_attempt_id != attempt.apply_attempt_id or event.project_id != project_id:
                    raise CanonApplyRecoveryRequired("C4a event identity is not graph-bound")
            if completed.replay_envelope_json != ready.replay_envelope_json:
                raise CanonApplyRecoveryRequired("C4a receipt and completion envelopes differ")
            if completed.replay_envelope_hash != ready.replay_envelope_hash:
                raise CanonApplyRecoveryRequired("C4a receipt and completion envelope hashes differ")
            if completed.receipt_payload_ref != ready.receipt_payload_ref:
                raise CanonApplyRecoveryRequired("C4a receipt ArtifactRef is not stable")
            if completed.replay_envelope_json is None or completed.replay_envelope_hash is None:
                raise CanonApplyRecoveryRequired("C4a completed envelope is missing")
            if completed.receipt_payload_ref is None or not _hash(completed.replay_envelope_hash):
                raise CanonApplyRecoveryRequired("C4a completed receipt identity is incomplete")
            if completed.replay_envelope_hash != _digest(completed.replay_envelope_json):
                raise CanonApplyRecoveryRequired("C4a completed envelope hash mismatch")
            if projection.observed_pointer_content_hash != attempt.target_pointer_content_hash:
                raise CanonApplyRecoveryRequired("C4a projection pointer observation is invalid")
            if projection.observed_marker_content_hash != attempt.target_marker_content_hash:
                raise CanonApplyRecoveryRequired("C4a projection marker observation is invalid")

            envelope = _load_canonical_object(completed.replay_envelope_json)
            required_envelope = {
                "apply_attempt_id": attempt.apply_attempt_id,
                "apply_key": attempt.apply_key,
                "journal_id": attempt.journal_id,
                "operation_id": attempt.operation_id,
                "project_id": project_id,
                "task_id": task_id,
                "bundle_content_hash": attempt.target_bundle_content_hash,
                "bundle_ref_artifact_id": attempt.target_bundle_ref.artifact_id,
                "target_pointer_content_hash": attempt.target_pointer_content_hash,
                "target_marker_content_hash": attempt.target_marker_content_hash,
                "version_id": attempt.target_version_id,
            }
            for key, value in required_envelope.items():
                if envelope.get(key) != value:
                    raise CanonApplyRecoveryRequired(
                        f"C4a completion envelope binding mismatch: {key}"
                    )
            audit_ids = envelope.get("audit_event_ids")
            if not isinstance(audit_ids, list) or not all(isinstance(item, str) for item in audit_ids):
                raise CanonApplyRecoveryRequired("C4a completion envelope audit binding is missing")

            task = self._task_row(task_id)
            if (
                task is None
                or task["project_id"] != project_id
                or task["status"] != ChapterTaskStatus.COMPLETED.value
                or task["commit_receipt_ref_artifact_id"] != completed.receipt_payload_ref.artifact_id
            ):
                raise CanonApplyRecoveryRequired("C4a completed Task binding is invalid")
            journal = self.get_journal(attempt.journal_id)
            if journal is None:
                raise CanonApplyRecoveryRequired("C4a completed journal is missing")
            self._validate_attempt_binding(attempt)
            receipt = self.get_receipt(attempt.journal_id)
            if receipt is None or receipt["receipt_ref_artifact_id"] != completed.receipt_payload_ref.artifact_id:
                raise CanonApplyRecoveryRequired("C4a completed Receipt binding is invalid")
            registered_receipt = self.resolve_artifact_ref(receipt["receipt_ref_artifact_id"])
            if registered_receipt != completed.receipt_payload_ref:
                raise CanonApplyRecoveryRequired("C4a Receipt ArtifactRef registry mismatch")

            op = self.connection.execute(
                "SELECT operation_id, request_digest, result_envelope_json, result_envelope_hash "
                "FROM creation_operation WHERE operation_id = ?", (attempt.operation_id,)
            ).fetchone()
            if op is None or op["operation_id"] != attempt.operation_id:
                raise CanonApplyRecoveryRequired("C4a operation binding is missing")
            if not _hash(op["request_digest"]):
                raise CanonApplyRecoveryRequired("C4a operation request digest is invalid")
            if (
                not isinstance(op["result_envelope_json"], str)
                or not _hash(op["result_envelope_hash"])
                or op["result_envelope_hash"] != _digest(op["result_envelope_json"])
            ):
                raise CanonApplyRecoveryRequired("C4a operation envelope hash is invalid")
            operation_envelope = _load_canonical_object(op["result_envelope_json"])
            for key, value in (("operation_id", attempt.operation_id), ("task_id", task_id)):
                if key in operation_envelope and operation_envelope[key] != value:
                    raise CanonApplyRecoveryRequired("C4a operation envelope binding is invalid")

            decision = self.connection.execute(
                "SELECT decision_id, task_id, based_on_task_revision, actor_kind, actor_id "
                "FROM creation_author_decision WHERE decision_id = ?", (attempt.decision_id,)
            ).fetchone()
            if (
                decision is None
                or decision["task_id"] != task_id
                or not decision["actor_kind"]
                or not decision["actor_id"]
            ):
                raise CanonApplyRecoveryRequired("C4a decision binding is invalid")

            completion_audits = self.connection.execute(
                "SELECT event_id, event_type, task_id, project_id, actor_kind, actor_id, "
                "before_task_revision, after_task_revision, operation_id "
                "FROM creation_audit_event WHERE task_id = ? AND project_id = ? "
                "AND operation_id = ? AND event_type IN ('CANON_APPLY_COMPLETED', 'CANON_APPLY_RECOVERY_COMPLETED') "
                "ORDER BY event_id", (task_id, project_id, attempt.operation_id)
            ).fetchall()
            if len(completion_audits) != 1:
                raise CanonApplyRecoveryRequired("C4a completion audit cardinality is invalid")
            audit = completion_audits[0]
            if (
                audit["task_id"] != task_id
                or audit["project_id"] != project_id
                or audit["actor_kind"] != "SYSTEM"
                or audit["actor_id"] is not None
                or audit["before_task_revision"] != task["aggregate_revision"] - 1
                or audit["after_task_revision"] != task["aggregate_revision"]
                or audit["event_id"] not in audit_ids
            ):
                raise CanonApplyRecoveryRequired("C4a completion audit binding is invalid")
            if tuple(audit_ids) != (audit["event_id"],):
                raise CanonApplyRecoveryRequired("C4a completion audit envelope is not exact")

            return CanonCompletedGraphEvidence(
                apply_attempt_id=attempt.apply_attempt_id,
                project_id=project_id,
                task_id=task_id,
                operator_identity=attempt.operator_identity,
                apply_key=attempt.apply_key,
                request_digest=attempt.request_digest,
                task_revision=int(task["aggregate_revision"]),
                phases=expected,
                operation_id=attempt.operation_id,
                decision_id=attempt.decision_id,
                journal_id=attempt.journal_id,
                receipt_id=receipt["receipt_id"],
                receipt_ref=completed.receipt_payload_ref,
                base_bundle_ref=attempt.base_bundle_ref,
                target_bundle_ref=attempt.target_bundle_ref,
                target_version_id=attempt.target_version_id,
                target_pointer_content_hash=attempt.target_pointer_content_hash,
                target_marker_content_hash=attempt.target_marker_content_hash,
                target_manifest_hash=attempt.target_manifest_hash,
                target_world_hash=attempt.target_world_hash,
                audit_event_ids=(audit["event_id"],),
                envelope_hash=completed.replay_envelope_hash,
                recovery_marker=bool(recovery),
            )
        except CanonApplyRecoveryRequired:
            raise
        except Exception as exc:
            raise CanonApplyRecoveryRequired("C4a completed graph cannot be verified") from exc

    def _insert_audit(
        self,
        *,
        event_id: str,
        task_id: str,
        project_id: str,
        event_type: str,
        before_revision: int,
        after_revision: int,
        operation_id: str,
        created_at: str,
    ) -> None:
        self.connection.execute(
            "INSERT INTO creation_audit_event ("
            "event_id, schema_version, task_id, project_id, event_type, actor_kind, "
            "actor_id, model_run_id, before_task_revision, after_task_revision, operation_id, created_at"
            ") VALUES (?, 1, ?, ?, ?, 'SYSTEM', NULL, NULL, ?, ?, ?, ?)",
            (event_id, task_id, project_id, event_type, before_revision, after_revision, operation_id, created_at),
        )

    @staticmethod
    def _attempt(row) -> C4aApplyAttempt:
        try:
            base = ArtifactRef(
                row["base_bundle_ref_artifact_id"],
                row["base_bundle_schema_version"],
                row["base_bundle_content_hash"],
            )
            target = ArtifactRef(
                row["target_bundle_ref_artifact_id"],
                row["target_bundle_schema_version"],
                row["target_bundle_content_hash"],
            )
            return C4aApplyAttempt(
                apply_attempt_id=row["apply_attempt_id"], project_id=row["project_id"],
                apply_key=row["apply_key"], request_digest=row["request_digest"],
                journal_id=row["journal_id"], task_id=row["task_id"],
                operation_id=row["operation_id"], decision_id=row["decision_id"],
                base_bundle_ref=base, base_version_id=row["base_version_id"],
                base_pointer_content_hash=row["base_pointer_content_hash"],
                target_bundle_ref=target, target_version_id=row["target_version_id"],
                target_pointer_content_hash=row["target_pointer_content_hash"],
                target_marker_content_hash=row["target_marker_content_hash"],
                target_manifest_hash=row["target_manifest_hash"],
                target_world_hash=row["target_world_hash"],
                operator_identity=row["operator_identity"], created_at=row["created_at"],
            )
        except Exception as exc:
            raise CanonApplyRecoveryRequired("C4a attempt identity is invalid") from exc

    def _event(self, row) -> C4aApplyEvent:
        ref_id = row["receipt_payload_ref_artifact_id"]
        ref = None if ref_id is None else self.resolve_artifact_ref(ref_id)
        if ref_id is not None and ref is None:
            raise CanonApplyRecoveryRequired("C4a receipt payload ArtifactRef is missing")
        if ref_id is None:
            if (
                row["receipt_payload_schema_version"] is not None
                or row["receipt_payload_content_hash"] is not None
            ):
                raise CanonApplyRecoveryRequired("C4a receipt payload ArtifactRef is incomplete")
        else:
            try:
                stored_ref = ArtifactRef(
                    ref_id,
                    row["receipt_payload_schema_version"],
                    row["receipt_payload_content_hash"],
                )
            except Exception as exc:
                raise CanonApplyRecoveryRequired("C4a receipt payload ArtifactRef is invalid") from exc
            if ref != stored_ref:
                raise CanonApplyRecoveryRequired("C4a receipt payload ArtifactRef identity mismatch")
        return C4aApplyEvent(
            event_id=row["event_id"], apply_attempt_id=row["apply_attempt_id"],
            project_id=row["project_id"], phase=row["phase"], result=row["result"],
            error_code=row["error_code"],
            recovery_failed_operation_id=row["recovery_failed_operation_id"],
            replay_envelope_json=row["replay_envelope_json"],
            replay_envelope_hash=row["replay_envelope_hash"],
            receipt_payload_ref=ref, created_at=row["created_at"],
            observed_pointer_content_hash=row["observed_pointer_content_hash"],
            observed_marker_content_hash=row["observed_marker_content_hash"],
        )


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _load_canonical_object(value: str) -> dict[str, object]:
    try:
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise ValueError("JSON object required")
        canonical = json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if canonical != value:
            raise ValueError("non-canonical JSON")
        return parsed
    except Exception as exc:
        raise CanonApplyRecoveryRequired("C4a envelope is not canonical JSON") from exc


C4aApplyRepository = SqliteC4aApplyRepository
