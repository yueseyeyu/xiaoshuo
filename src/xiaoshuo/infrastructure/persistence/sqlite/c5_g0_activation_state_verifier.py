"""Read-only census for the post-C4b ``C4B_ACTIVATED_CLEAN`` state.

This is the only G0-C module allowed to issue the controlled SQL needed for a
global activation census.  It never commits, mutates a file, creates a lock,
or repairs an observed state.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

from xiaoshuo.application.creation.digest import (
    result_from_authoring_submission_envelope,
    result_from_canon_envelope,
    result_from_decision_consumption_envelope,
    result_from_decision_creation_envelope,
    result_from_envelope,
)
from xiaoshuo.application.creation.operation_kind import OperationKind
from xiaoshuo.application.creation.authoring_artifact import (
    AuthoringArtifactEnvelope,
    AuthoringArtifactKind,
    parse_authoring_artifact_envelope,
)
from xiaoshuo.domain.creation import ArtifactRef
from xiaoshuo.infrastructure.canon.canonical_bundle import CanonicalBundle
from xiaoshuo.infrastructure.canon.immutable_payload_store import ImmutablePayloadStore
from xiaoshuo.infrastructure.canon.projection_activation import ProjectionActivationReader
from xiaoshuo.infrastructure.persistence.sqlite.canon_activation_repository import (
    SqliteCanonActivationRepository,
)
from xiaoshuo.infrastructure.persistence.sqlite.author_decision_repository import (
    SqliteAuthorDecisionRepository,
)


class C5G0ActivationStateVerificationError(RuntimeError):
    """The activation graph or its projection cannot be trusted as clean."""


_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_MIGRATION_FILE = re.compile(r"^v(\d{3})_.+\.sql$")
_BACKUP_MAIN_FILE = re.compile(
    r"^pre_migration_v(002|003|004|005|006)_[A-Za-z0-9][A-Za-z0-9_.-]*\.db$"
)
_BACKUP_SIDECAR_FILE = re.compile(
    r"^pre_migration_v(002|003|004|005|006)_[A-Za-z0-9][A-Za-z0-9_.-]*\.db-(wal|shm)$"
)
_EXPECTED_MIGRATION_VERSIONS = (1, 2, 3, 4, 5, 6)
_EXPECTED_TABLES = frozenset(
    {
        "creation_schema_migration",
        "creation_artifact_ref",
        "chapter_task",
        "creation_operation",
        "creation_audit_event",
        "creation_audit_event_source_artifact_ref",
        "creation_audit_event_object_ref",
        "creation_author_decision",
        "creation_decision_consumption",
        "canon_commit_journal_v003_legacy",
        "canon_commit_receipt_v003_legacy",
        "canon_commit_journal",
        "canon_commit_receipt",
        "canon_activation_attempt",
        "canon_activation_event",
        "canon_apply_attempt",
        "canon_apply_event",
    }
)
_PRE_MIGRATION_TABLES = {
    2: frozenset(
        {
            "creation_schema_migration",
            "creation_artifact_ref",
            "chapter_task",
            "creation_operation",
            "creation_audit_event",
            "creation_audit_event_source_artifact_ref",
            "creation_audit_event_object_ref",
        }
    ),
    3: frozenset(
        {
            "creation_schema_migration",
            "creation_artifact_ref",
            "chapter_task",
            "creation_operation",
            "creation_audit_event",
            "creation_audit_event_source_artifact_ref",
            "creation_audit_event_object_ref",
            "creation_author_decision",
            "creation_decision_consumption",
        }
    ),
    4: frozenset(
        {
            "creation_schema_migration",
            "creation_artifact_ref",
            "chapter_task",
            "creation_operation",
            "creation_audit_event",
            "creation_audit_event_source_artifact_ref",
            "creation_audit_event_object_ref",
            "creation_author_decision",
            "creation_decision_consumption",
            "canon_commit_journal",
            "canon_commit_receipt",
        }
    ),
    5: frozenset(
        {
            "creation_schema_migration",
            "creation_artifact_ref",
            "chapter_task",
            "creation_operation",
            "creation_audit_event",
            "creation_audit_event_source_artifact_ref",
            "creation_audit_event_object_ref",
            "creation_author_decision",
            "creation_decision_consumption",
            "canon_commit_journal_v003_legacy",
            "canon_commit_receipt_v003_legacy",
            "canon_commit_journal",
            "canon_commit_receipt",
        }
    ),
    6: _EXPECTED_TABLES - {"canon_apply_attempt", "canon_apply_event"},
}
_PRE_MIGRATION_COLUMNS = {
    "creation_schema_migration": (
        "version",
        "file_name",
        "sha256",
        "applied_at",
    ),
    "creation_artifact_ref": ("artifact_id", "schema_version", "content_hash"),
    "chapter_task_v001": (
        "task_id",
        "schema_version",
        "aggregate_revision",
        "project_id",
        "chapter_number",
        "status",
        "last_stable_status",
        "creative_intent_ref_artifact_id",
        "confirmed_plan_ref_artifact_id",
        "current_author_draft_ref_artifact_id",
        "review_target_draft_ref_artifact_id",
        "adopted_draft_ref_artifact_id",
        "latest_review_ref_artifact_id",
        "pending_changeset_ref_artifact_id",
        "recovery_failed_operation_id",
        "recovery_error_code",
        "recovery_retry_from_status",
        "created_at",
        "updated_at",
    ),
    "chapter_task_v003": (
        "task_id",
        "schema_version",
        "aggregate_revision",
        "project_id",
        "chapter_number",
        "status",
        "last_stable_status",
        "creative_intent_ref_artifact_id",
        "confirmed_plan_ref_artifact_id",
        "current_author_draft_ref_artifact_id",
        "review_target_draft_ref_artifact_id",
        "adopted_draft_ref_artifact_id",
        "latest_review_ref_artifact_id",
        "pending_changeset_ref_artifact_id",
        "commit_receipt_ref_artifact_id",
        "recovery_failed_operation_id",
        "recovery_error_code",
        "recovery_retry_from_status",
        "created_at",
        "updated_at",
    ),
    "creation_operation": (
        "operation_id",
        "idempotency_key",
        "request_digest",
        "result_envelope_json",
        "result_envelope_hash",
        "created_at",
    ),
    "creation_audit_event": (
        "event_id",
        "schema_version",
        "task_id",
        "project_id",
        "event_type",
        "actor_kind",
        "actor_id",
        "model_run_id",
        "before_task_revision",
        "after_task_revision",
        "operation_id",
        "created_at",
    ),
    "creation_audit_event_source_artifact_ref": (
        "event_id",
        "ordinal",
        "artifact_id",
    ),
    "creation_audit_event_object_ref": (
        "event_id",
        "ordinal",
        "artifact_id",
    ),
    "creation_author_decision": (
        "decision_id",
        "schema_version",
        "task_id",
        "decision_type",
        "target_ref_artifact_id",
        "outcome",
        "based_on_task_revision",
        "author_id",
        "reason",
        "actor_kind",
        "actor_id",
        "content_hash",
        "created_at",
    ),
    "creation_decision_consumption": (
        "consumption_id",
        "decision_id",
        "operation_id",
        "task_id",
        "consumed_at_task_revision",
        "consumed_at",
    ),
    "canon_commit_journal_v003": (
        "journal_id",
        "task_id",
        "operation_id",
        "decision_id",
        "changeset_ref_artifact_id",
        "target_bundle_ref_artifact_id",
        "bundle_hash",
        "base_manifest_hash",
        "target_manifest_hash",
        "created_at",
    ),
    "canon_commit_journal_v004": (
        "journal_id",
        "task_id",
        "operation_id",
        "decision_id",
        "changeset_ref_artifact_id",
        "base_bundle_ref_artifact_id",
        "target_bundle_ref_artifact_id",
        "base_bundle_content_hash",
        "target_bundle_content_hash",
        "base_manifest_hash",
        "base_world_hash",
        "target_manifest_hash",
        "target_world_hash",
        "canonical_bundle_schema_version",
        "created_at",
    ),
    "canon_commit_receipt": (
        "receipt_id",
        "journal_id",
        "receipt_ref_artifact_id",
        "created_at",
    ),
    "canon_activation_attempt": (
        "attempt_id",
        "project_id",
        "attempt_key",
        "request_digest",
        "seed_digest",
        "bundle_ref_artifact_id",
        "bundle_schema_version",
        "bundle_content_hash",
        "manifest_hash",
        "world_hash",
        "version_id",
        "pointer_content_hash",
        "operator_identity",
        "created_at",
    ),
    "canon_activation_event": (
        "event_id",
        "attempt_id",
        "project_id",
        "phase",
        "result",
        "error_code",
        "replay_envelope_json",
        "replay_envelope_hash",
        "created_at",
    ),
    "canon_apply_attempt": (
        "apply_attempt_id",
        "project_id",
        "apply_key",
        "request_digest",
        "journal_id",
        "task_id",
        "operation_id",
        "decision_id",
        "base_bundle_ref_artifact_id",
        "base_bundle_schema_version",
        "base_bundle_content_hash",
        "base_version_id",
        "base_pointer_content_hash",
        "target_bundle_ref_artifact_id",
        "target_bundle_schema_version",
        "target_bundle_content_hash",
        "target_version_id",
        "target_pointer_content_hash",
        "target_marker_content_hash",
        "target_manifest_hash",
        "target_world_hash",
        "operator_identity",
        "created_at",
    ),
    "canon_apply_event": (
        "event_id",
        "apply_attempt_id",
        "project_id",
        "phase",
        "result",
        "error_code",
        "recovery_failed_operation_id",
        "replay_envelope_json",
        "replay_envelope_hash",
        "receipt_payload_ref_artifact_id",
        "receipt_payload_schema_version",
        "receipt_payload_content_hash",
        "observed_pointer_content_hash",
        "observed_marker_content_hash",
        "created_at",
    ),
}
_REPARSE_POINT = 0x400
_ZERO_TABLES = frozenset(
    {
        "chapter_task",
        "creation_operation",
        "creation_audit_event",
        "creation_audit_event_source_artifact_ref",
        "creation_audit_event_object_ref",
        "creation_author_decision",
        "creation_decision_consumption",
        "canon_commit_journal",
        "canon_commit_receipt",
        "canon_apply_attempt",
        "canon_apply_event",
        "canon_commit_journal_v003_legacy",
        "canon_commit_receipt_v003_legacy",
    }
)


@dataclass(frozen=True, slots=True)
class C5G0ActivationCleanEvidence:
    status: str
    project_id: str
    attempt_id: str
    attempt_key: str
    request_digest: str
    operator_identity: str
    bundle_ref: ArtifactRef
    version_id: str
    pointer_content_hash: str
    event_phases: tuple[str, str]
    reader_project_id: str
    reader_version_id: str
    reader_bundle_ref: ArtifactRef
    reader_bundle_content_hash: str
    reader_manifest_hash: str
    reader_world_hash: str


class C5G0RuntimeCensusStatus(str, Enum):
    """Closed set of runtime states accepted by the G0-C runner."""

    REPARSE_OR_JUNCTION = "REPARSE_OR_JUNCTION"
    LOCK_OR_CLOSE_UNCERTAIN = "LOCK_OR_CLOSE_UNCERTAIN"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    PARTIAL = "PARTIAL"
    RESIDUE = "RESIDUE"
    UNKNOWN = "UNKNOWN"
    COMPLETED_GRAPH = "COMPLETED_GRAPH"
    C4B_ACTIVATED_CLEAN = "C4B_ACTIVATED_CLEAN"
    RECOVERY_ASSESSED_INITIALIZED_EMPTY_COMPATIBLE = (
        "RECOVERY_ASSESSED_INITIALIZED_EMPTY_COMPATIBLE"
    )
    INITIALIZED_EMPTY = "INITIALIZED_EMPTY"
    UNPROVISIONED_NO_RUNTIME = "UNPROVISIONED_NO_RUNTIME"


@dataclass(frozen=True, slots=True)
class C5G0RuntimeCensus:
    """Immutable runtime classification returned by the verifier boundary."""

    status: C5G0RuntimeCensusStatus
    reason: str
    root_exists: bool
    database_exists: bool
    payloads_exists: bool
    projection_exists: bool
    backups_exists: bool
    exports_exists: bool
    sqlite_sidecars: tuple[str, ...] = ()
    business_fact_counts: tuple[tuple[str, int], ...] = ()
    task_ids: tuple[str, ...] = ()
    completed_task_ids: tuple[str, ...] = ()
    clean_evidence: C5G0ActivationCleanEvidence | None = None
    completed_graph_evidence: C5G0CompletedGraphEvidence | None = None
    backup_files: tuple[C5G0BackupFileEvidence, ...] = ()
    root_reparse: bool = False
    lock_observed: bool = False
    filesystem_partial: bool = False
    filesystem_residue: bool = False


@dataclass(frozen=True, slots=True)
class C5G0BackupFileEvidence:
    family_version: int
    relative_path: str
    suffix: str
    byte_length: int
    sha256: str
    regular_file: bool
    reparse: bool
    paired_main_relative_path: str
    database_user_version: int | None = None
    database_application_id: int | None = None
    database_schema_tables: tuple[str, ...] = ()
    migration_ledger: tuple[tuple[int, str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class C5G0FreshGateEvidence:
    """Immutable proof that a fresh C4b gate was read without mutation."""

    status: C5G0RuntimeCensusStatus
    root_path: str
    database_path: str
    database_application_id: int
    database_user_version: int
    database_schema_tables: tuple[str, ...]
    migration_ledger: tuple[tuple[int, str, str], ...]
    backup_files: tuple[C5G0BackupFileEvidence, ...]
    payloads_exists: bool
    projection_exists: bool
    exports_exists: bool
    sqlite_sidecars: tuple[str, ...]
    root_reparse: bool
    lock_observed: bool
    immutable_connection_closed: bool
    business_fact_counts: tuple[tuple[str, int], ...] = ()
    zero_business_facts: bool = False
    integrity_check: str = ""
    foreign_key_check: tuple[tuple[object, ...], ...] = ()
    zero_write: bool = True


@dataclass(frozen=True, slots=True)
class C5G0CompletedGraphSnapshot:
    """Typed read-only census passed to the completed-graph validator.

    The snapshot is deliberately a data boundary.  It contains no connection,
    repository, lock, or writer, so replay verification cannot acquire or
    mutate any of those resources.
    """

    project_id: str
    task_id: str
    task_status: str
    last_stable_status: str
    task_revision: int
    recovery_error_code: str | None
    durable_envelopes: tuple[str, ...]
    payload_content_hashes: tuple[str, ...]
    operation_count: int
    audit_count: int
    decision_count: int
    consumption_count: int
    c3_journal_count: int
    c4a_attempt_count: int
    c4a_event_count: int
    c4a_completed_event_count: int
    receipt_count: int
    activation_attempt_id: str
    activation_replay_envelope_json: str
    projection_identity_bound: bool
    graph_state: str = "COMPLETED"
    lock_observed: bool = False
    sqlite_write_count: int = 0
    payload_put_count: int = 0
    c4a_recovery_event_count: int = 0
    c4a_unknown_event_count: int = 0


@dataclass(frozen=True, slots=True)
class C5G0CompletedGraphEvidence:
    """Original durable envelopes plus immutable read-only graph evidence."""

    status: str
    project_id: str
    task_id: str
    task_revision: int
    activation_attempt_id: str
    activation_replay_envelope_json: str
    durable_envelopes: tuple[str, ...]
    payload_content_hashes: tuple[str, ...]
    read_only: bool = True
    payload_put_count: int = 0
    task_facts: tuple["C5G0GraphFact", ...] = ()
    artifact_facts: tuple["C5G0GraphFact", ...] = ()
    operation_facts: tuple["C5G0GraphFact", ...] = ()
    decision_facts: tuple["C5G0GraphFact", ...] = ()
    consumption_facts: tuple["C5G0GraphFact", ...] = ()
    audit_facts: tuple["C5G0GraphFact", ...] = ()
    journal_facts: tuple["C5G0GraphFact", ...] = ()
    receipt_facts: tuple["C5G0GraphFact", ...] = ()
    apply_attempt_facts: tuple["C5G0GraphFact", ...] = ()
    apply_event_facts: tuple["C5G0GraphFact", ...] = ()


@dataclass(frozen=True, slots=True)
class C5G0GraphFact:
    """Immutable, connection-free cross-evidence for one durable graph fact."""

    fact_type: str
    identity: tuple[tuple[str, object], ...]
    artifact_refs: tuple[ArtifactRef, ...] = ()
    envelope_json: str | None = None
    envelope_hash: str | None = None


class C5G0ActivationStateVerifier:
    """Own a read-only connection and return immutable clean-state evidence."""

    def __init__(
        self,
        runtime,
        *,
        connection_factory: Callable[..., sqlite3.Connection] | None = None,
        payload_store_factory: Callable[[Path], object] = ImmutablePayloadStore,
        reader_factory: Callable[..., object] = ProjectionActivationReader,
        operation_reader: Callable[[sqlite3.Connection], tuple[object, ...]] | None = None,
    ) -> None:
        self._runtime = runtime
        self._connection_factory = connection_factory
        self._payload_store_factory = payload_store_factory
        self._reader_factory = reader_factory
        self._operation_reader = operation_reader or _read_operation_rows

    def _open_read_connection(self) -> sqlite3.Connection:
        if self._connection_factory is not None:
            return self._connection_factory(self._runtime.settings, read_only=True)
        db_path = getattr(self._runtime, "db_path", self._runtime.settings.db_path)
        return _open_immutable_connection(Path(db_path))

    def classify_runtime(
        self,
        *,
        project_id: str,
        attempt_key: str,
        request_digest: str,
    ) -> C5G0RuntimeCensus:
        """Classify the configured runtime without opening a business write path.

        This is the single branch-selection boundary for G0-C.  It performs a
        filesystem census first, then a query-only SQLite census.  It never
        calls ``verify_initialized_empty`` and never creates a lock, payload,
        projection, task, operation, decision, audit, or Canon fact.
        """

        _require_identifier(project_id, "project_id")
        _require_identifier(attempt_key, "attempt_key")
        _require_digest(request_digest, "request_digest")
        fs = _census_runtime_filesystem(self._runtime)
        if fs["reparse"]:
            return _runtime_census(fs, C5G0RuntimeCensusStatus.REPARSE_OR_JUNCTION,
                                   "runtime contains a reparse or junction residue")
        if fs["lock"]:
            return _runtime_census(fs, C5G0RuntimeCensusStatus.LOCK_OR_CLOSE_UNCERTAIN,
                                   "runtime contains lock or close-uncertain residue")
        if not fs["any"]:
            return _runtime_census(fs, C5G0RuntimeCensusStatus.UNPROVISIONED_NO_RUNTIME,
                                   "no configured runtime roots or database exist")
        if (fs["partial"] or fs["residue"]) and not fs["database"]:
            status = (
                C5G0RuntimeCensusStatus.PARTIAL
                if fs["partial"]
                else C5G0RuntimeCensusStatus.RESIDUE
            )
            return _runtime_census(fs, status, "runtime filesystem is not provisionable")
        if not fs["database"]:
            return _runtime_census(fs, C5G0RuntimeCensusStatus.PARTIAL,
                                   "runtime has roots but no creation database")

        conn: sqlite3.Connection | None = None
        try:
            conn = self._open_read_connection()
            self._verify_connection(conn)
            self._verify_schema(conn)
            facts = _read_runtime_business_census(conn)
            completed_task_ids = tuple(facts["completed_task_ids"])
            if facts["recovery"]:
                return _runtime_census(
                    fs, C5G0RuntimeCensusStatus.RECOVERY_REQUIRED,
                    "runtime contains recovery facts", facts=facts,
                )

            # Filesystem rejection has precedence over every positive state.
            # Recovery is checked first because it is the higher-priority
            # durable fact when a runtime is both damaged and recovering.
            if fs["partial"]:
                return _runtime_census(
                    fs, C5G0RuntimeCensusStatus.PARTIAL,
                    "runtime roots or SQLite sidecars are partial", facts=facts,
                )
            if fs["residue"]:
                return _runtime_census(
                    fs, C5G0RuntimeCensusStatus.RESIDUE,
                    "runtime contains unexpected root residue", facts=facts,
                )

            if not fs["backups_exists"]:
                return _runtime_census(
                    fs,
                    C5G0RuntimeCensusStatus.PARTIAL,
                    "initialized-empty runtime is missing the backup directory",
                    facts=facts,
                )
            if len(fs["backup_families"]) != 5:
                return _runtime_census(
                    fs,
                    C5G0RuntimeCensusStatus.RESIDUE,
                    "initialized-empty runtime does not contain v002-v006 backups",
                    facts=facts,
                )

            try:
                fs["backup_files"] = _verify_backup_families(
                    self._runtime, fs["backup_families"]
                )
            except C5G0ActivationStateVerificationError as exc:
                return _runtime_census(
                    fs,
                    C5G0RuntimeCensusStatus.RESIDUE,
                    "backup family identity is not trusted",
                    facts=facts,
                    reason_detail=str(exc.__cause__ or exc),
                )

            # A completed graph has precedence over the C4b-only positive
            # state.  The runner must not call verify_c4b_clean for it.
            if completed_task_ids:
                completed_task_id = completed_task_ids[0]
                self._close_census_connection(conn)
                conn = None
                try:
                    graph_evidence = self.verify_completed_graph(
                        project_id=project_id,
                        task_id=completed_task_id,
                        attempt_key=attempt_key,
                        request_digest=request_digest,
                    )
                except C5G0ActivationStateVerificationError as exc:
                    return _runtime_census(
                        fs,
                        C5G0RuntimeCensusStatus.PARTIAL,
                        "completed graph facts are not fully verified",
                        facts=facts,
                        reason_detail=str(exc.__cause__ or exc),
                    )
                return _runtime_census(
                    fs, C5G0RuntimeCensusStatus.COMPLETED_GRAPH,
                    "runtime contains a fully verified completed graph", facts=facts,
                    completed_graph_evidence=graph_evidence,
                )

            if _is_initialized_empty_census(facts, fs):
                status = (
                    C5G0RuntimeCensusStatus.RECOVERY_ASSESSED_INITIALIZED_EMPTY_COMPATIBLE
                    if fs["recovery_compatible"]
                    else C5G0RuntimeCensusStatus.INITIALIZED_EMPTY
                )
                return _runtime_census(
                    fs, status,
                    "migration-complete database contains no business facts", facts=facts,
                )

            if _is_c4b_clean_candidate(facts, fs):
                self._close_census_connection(conn)
                conn = None
                try:
                    evidence = self.verify(
                        project_id=project_id,
                        attempt_key=attempt_key,
                        request_digest=request_digest,
                    )
                except C5G0ActivationStateVerificationError as exc:
                    return _runtime_census(
                        fs, C5G0RuntimeCensusStatus.PARTIAL,
                        "C4b facts are not a clean verified graph", facts=facts,
                        reason_detail=str(exc.__cause__ or exc),
                    )
                return _runtime_census(
                    fs, C5G0RuntimeCensusStatus.C4B_ACTIVATED_CLEAN,
                    "C4b facts and projection are clean", facts=facts,
                    clean_evidence=evidence,
                )

            status = (
                C5G0RuntimeCensusStatus.UNKNOWN
                if facts["fact_count"] == 0
                else C5G0RuntimeCensusStatus.PARTIAL
            )
            return _runtime_census(fs, status, "runtime facts do not form an accepted state", facts=facts)
        except C5G0ActivationStateVerificationError as exc:
            if str(exc).startswith("runtime census connection close failed"):
                return _runtime_census(
                    fs,
                    C5G0RuntimeCensusStatus.LOCK_OR_CLOSE_UNCERTAIN,
                    "runtime census connection close failed",
                    reason_detail=str(exc.__cause__ or exc),
                )
            status = (
                C5G0RuntimeCensusStatus.RESIDUE
                if fs["residue"]
                else C5G0RuntimeCensusStatus.PARTIAL
                if fs["partial"]
                else C5G0RuntimeCensusStatus.UNKNOWN
            )
            return _runtime_census(
                fs, status,
                "runtime census failed closed", reason_detail=str(exc),
            )
        except (OSError, sqlite3.Error) as exc:
            status = (
                C5G0RuntimeCensusStatus.RESIDUE
                if fs["residue"]
                else C5G0RuntimeCensusStatus.PARTIAL
                if fs["partial"]
                else C5G0RuntimeCensusStatus.UNKNOWN
            )
            return _runtime_census(
                fs, status,
                "runtime census could not read SQLite", reason_detail=str(exc),
            )
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception as exc:
                    return _runtime_census(
                        fs,
                        C5G0RuntimeCensusStatus.LOCK_OR_CLOSE_UNCERTAIN,
                        "runtime census connection close failed",
                        reason_detail=str(exc),
                )

    def verify_fresh_gate(
        self,
        *,
        project_id: str,
        attempt_key: str,
        request_digest: str,
    ) -> C5G0FreshGateEvidence:
        """Re-census the configured runtime and return an immutable fresh gate."""

        census = self.classify_runtime(
            project_id=project_id,
            attempt_key=attempt_key,
            request_digest=request_digest,
        )
        accepted = {
            C5G0RuntimeCensusStatus.INITIALIZED_EMPTY,
            C5G0RuntimeCensusStatus.RECOVERY_ASSESSED_INITIALIZED_EMPTY_COMPATIBLE,
        }
        if census.status not in accepted:
            raise C5G0ActivationStateVerificationError(
                f"fresh gate rejected runtime census: {census.status.value}"
            )

        second_census = self.classify_runtime(
            project_id=project_id,
            attempt_key=attempt_key,
            request_digest=request_digest,
        )
        if second_census.status not in accepted or not _same_fresh_census(
            census, second_census
        ):
            raise C5G0ActivationStateVerificationError(
                "fresh gate census changed before immutable verification"
            )

        fs = _census_runtime_filesystem(self._runtime)
        conn: sqlite3.Connection | None = None
        close_error: Exception | None = None
        ledger: tuple[tuple[int, str, str], ...] = ()
        tables: tuple[str, ...] = ()
        application_id = 0
        user_version = 0
        business_fact_counts: tuple[tuple[str, int], ...] = ()
        integrity_check = ""
        foreign_key_check: tuple[tuple[object, ...], ...] = ()
        try:
            conn = self._open_read_connection()
            self._verify_connection(conn)
            self._verify_schema(conn)
            ledger = _verify_migration_ledger(conn)
            tables = tuple(
                sorted(
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    )
                )
            )
            application_id = int(conn.execute("PRAGMA application_id").fetchone()[0])
            user_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            integrity_check = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
            foreign_key_check = tuple(
                tuple(row) for row in conn.execute("PRAGMA foreign_key_check").fetchall()
            )
            facts = _read_runtime_business_census(conn)
            business_fact_counts = tuple(
                sorted((str(key), int(value)) for key, value in facts["counts"].items())
            )
            if business_fact_counts != second_census.business_fact_counts or any(
                value != 0 for _, value in business_fact_counts
            ):
                raise C5G0ActivationStateVerificationError(
                    "fresh gate business census is not empty or changed"
                )
        except C5G0ActivationStateVerificationError:
            raise
        except Exception as exc:
            raise C5G0ActivationStateVerificationError(
                "fresh gate immutable census failed"
            ) from exc
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception as exc:
                    close_error = exc
        if close_error is not None:
            raise C5G0ActivationStateVerificationError(
                "fresh gate immutable connection close failed"
            ) from close_error

        if (
            fs["partial"]
            or fs["residue"]
            or fs["reparse"]
            or fs["lock"]
            or not fs["backups_exists"]
            or len(fs["backup_families"]) != 5
        ):
            raise C5G0ActivationStateVerificationError(
                "fresh gate filesystem census is incomplete or changed"
            )
        backup_files = _verify_backup_families(self._runtime, fs["backup_families"])
        if tuple(backup_files) != second_census.backup_files:
            raise C5G0ActivationStateVerificationError(
                "fresh gate backup family census changed before evidence creation"
            )

        final_census = self.classify_runtime(
            project_id=project_id,
            attempt_key=attempt_key,
            request_digest=request_digest,
        )
        if final_census.status not in accepted or not _same_fresh_census(
            census, final_census
        ):
            raise C5G0ActivationStateVerificationError(
                "fresh gate census changed after immutable verification"
            )
        return C5G0FreshGateEvidence(
            status=final_census.status,
            root_path=_path_text(Path(self._runtime.root)),
            database_path=_path_text(Path(self._runtime.db_path)),
            database_application_id=application_id,
            database_user_version=user_version,
            database_schema_tables=tables,
            migration_ledger=ledger,
            backup_files=backup_files,
            payloads_exists=final_census.payloads_exists,
            projection_exists=final_census.projection_exists,
            exports_exists=final_census.exports_exists,
            sqlite_sidecars=final_census.sqlite_sidecars,
            root_reparse=final_census.root_reparse,
            lock_observed=final_census.lock_observed,
            immutable_connection_closed=True,
            business_fact_counts=business_fact_counts,
            zero_business_facts=all(value == 0 for _, value in business_fact_counts),
            integrity_check=integrity_check,
            foreign_key_check=foreign_key_check,
            zero_write=True,
        )

    def verify(
        self,
        *,
        project_id: str,
        attempt_key: str,
        request_digest: str,
    ) -> C5G0ActivationCleanEvidence:
        _require_identifier(project_id, "project_id")
        _require_identifier(attempt_key, "attempt_key")
        _require_digest(request_digest, "request_digest")
        _verify_runtime_roots(self._runtime)

        conn = self._open_read_connection()
        try:
            self._verify_connection(conn)
            self._verify_schema(conn)
            self._verify_zero_tables(conn)
            repo = SqliteCanonActivationRepository(conn)
            attempt = self._read_unique_attempt(conn)
            if (
                attempt.project_id != project_id
                or attempt.attempt_key != attempt_key
                or attempt.request_digest != request_digest
                or attempt.operator_identity != self._runtime.operator_context.author_id
            ):
                raise C5G0ActivationStateVerificationError(
                    "activation attempt identity does not match the runtime request"
                )
            ref = self._read_unique_artifact_ref(conn)
            if ref != attempt.bundle_ref:
                raise C5G0ActivationStateVerificationError(
                    "activation ArtifactRef registry does not match the attempt"
                )
            events = self._read_unique_events(conn, attempt.attempt_id, project_id)
            if tuple(event.phase for event in events) != ("PREPARED", "READY_FOR_MARKER"):
                raise C5G0ActivationStateVerificationError(
                    "C4b activation events are not exactly PREPARED then READY_FOR_MARKER"
                )
            if any(event.error_code is not None for event in events):
                raise C5G0ActivationStateVerificationError(
                    "clean activation events must not carry recovery errors"
                )
            _verify_event_contract(
                events,
                attempt=attempt,
                project_id=project_id,
                attempt_key=attempt_key,
                request_digest=request_digest,
            )

            payload_store = self._payload_store_factory(self._runtime.payloads_dir)
            payload = _read_payload(payload_store, ref.content_hash)
            bundle = CanonicalBundle.from_bytes(payload)
            if bundle.content_hash() != ref.content_hash:
                raise C5G0ActivationStateVerificationError("activation payload hash mismatch")
            if bundle.manifest_hash != attempt.manifest_hash or bundle.world_hash != attempt.world_hash:
                raise C5G0ActivationStateVerificationError(
                    "activation payload identity does not match the attempt"
                )

            pointer_path = self._runtime.projection_dir / "current.pointer"
            pointer_bytes = _read_regular_file(pointer_path, "current.pointer")
            if _sha256(pointer_bytes) != attempt.pointer_content_hash:
                raise C5G0ActivationStateVerificationError(
                    "activation attempt pointer hash does not match current.pointer"
                )

            reader = self._reader_factory(
                self._runtime.projection_dir,
                artifact_ref_resolver=repo.resolve_artifact_ref,
            )
            identity = reader.read_for_project(project_id)
            if (
                identity.project_id != project_id
                or identity.version_id != attempt.version_id
                or identity.bundle_ref_artifact_id != ref.artifact_id
                or identity.bundle_schema_version != ref.schema_version
                or identity.bundle_content_hash != ref.content_hash
                or identity.manifest_hash != attempt.manifest_hash
                or identity.world_hash != attempt.world_hash
            ):
                raise C5G0ActivationStateVerificationError(
                    "activation reader identity does not match the durable census"
                )
            if identity.bundle_content_hash != ref.content_hash:
                raise C5G0ActivationStateVerificationError("reader bundle hash mismatch")
            return C5G0ActivationCleanEvidence(
                status="C4B_ACTIVATED_CLEAN",
                project_id=project_id,
                attempt_id=attempt.attempt_id,
                attempt_key=attempt.attempt_key,
                request_digest=attempt.request_digest,
                operator_identity=attempt.operator_identity,
                bundle_ref=ref,
                version_id=attempt.version_id,
                pointer_content_hash=attempt.pointer_content_hash,
                event_phases=(events[0].phase, events[1].phase),
                reader_project_id=identity.project_id,
                reader_version_id=identity.version_id,
                reader_bundle_ref=ArtifactRef(
                    identity.bundle_ref_artifact_id,
                    identity.bundle_schema_version,
                    identity.bundle_content_hash,
                ),
                reader_bundle_content_hash=identity.bundle_content_hash,
                reader_manifest_hash=identity.manifest_hash,
                reader_world_hash=identity.world_hash,
            )
        except C5G0ActivationStateVerificationError:
            raise
        except Exception as exc:
            raise C5G0ActivationStateVerificationError(
                "C4B_ACTIVATED_CLEAN verification failed"
            ) from exc
        finally:
            try:
                conn.close()
            except Exception as exc:
                raise C5G0ActivationStateVerificationError(
                    "read-only activation verifier close failed"
                ) from exc

    def verify_completed_graph(
        self,
        *,
        project_id: str,
        task_id: str,
        attempt_key: str,
        request_digest: str,
    ) -> C5G0CompletedGraphEvidence:
        """Verify a completed Task graph without entering any write path.

        This entry deliberately does not call ``verify_initialized_empty`` or
        any C4b/application operation.  It opens one query-only connection,
        reads the original payloads and durable envelopes, and fail-closes on
        partial, recovery, conflict, or unknown mixed state.
        """

        _require_identifier(project_id, "project_id")
        _require_identifier(task_id, "task_id")
        _require_identifier(attempt_key, "attempt_key")
        _require_digest(request_digest, "request_digest")
        _verify_runtime_roots(self._runtime)

        conn = self._open_read_connection()
        try:
            self._verify_connection(conn)
            self._verify_schema(conn)
            repo = SqliteCanonActivationRepository(conn)
            attempt = self._read_unique_attempt(conn)
            if (
                attempt.project_id != project_id
                or attempt.attempt_key != attempt_key
                or attempt.request_digest != request_digest
                or attempt.operator_identity != self._runtime.operator_context.author_id
            ):
                raise C5G0ActivationStateVerificationError(
                    "completed graph activation identity does not match the runtime request"
                )
            ref = repo.resolve_artifact_ref(attempt.bundle_ref.artifact_id)
            if ref is None:
                raise C5G0ActivationStateVerificationError(
                    "completed graph activation ArtifactRef is missing"
                )
            if ref != attempt.bundle_ref:
                raise C5G0ActivationStateVerificationError(
                    "completed graph activation ArtifactRef does not match the attempt"
                )
            events = self._read_unique_events(conn, attempt.attempt_id, project_id)
            _verify_event_contract(
                events,
                attempt=attempt,
                project_id=project_id,
                attempt_key=attempt_key,
                request_digest=request_digest,
            )

            payload_store = self._payload_store_factory(self._runtime.payloads_dir)
            activation_payload = _read_payload(payload_store, ref.content_hash)
            bundle = CanonicalBundle.from_bytes(activation_payload)
            if (
                bundle.content_hash() != ref.content_hash
                or bundle.manifest_hash != attempt.manifest_hash
                or bundle.world_hash != attempt.world_hash
            ):
                raise C5G0ActivationStateVerificationError(
                    "completed graph activation payload identity mismatch"
                )

            pointer_bytes = _read_regular_file(
                self._runtime.projection_dir / "current.pointer", "current.pointer"
            )
            reader = self._reader_factory(
                self._runtime.projection_dir,
                artifact_ref_resolver=repo.resolve_artifact_ref,
            )
            identity = reader.read_for_project(project_id)
            if identity.project_id != project_id:
                raise C5G0ActivationStateVerificationError(
                    "completed graph projection identity mismatch"
                )

            graph = _read_and_verify_completed_graph(
                conn,
                payload_store,
                task_id=task_id,
                project_id=project_id,
                operator_identity=self._runtime.operator_context.author_id,
                activation_attempt=attempt,
                activation_ref=ref,
                activation_bundle=bundle,
                activation_events=events,
                activation_identity=identity,
                projection_dir=Path(self._runtime.projection_dir),
                operation_rows=self._operation_reader(conn),
            )
            task = graph["task"]
            envelopes = graph["envelopes"]
            payload_hashes = graph["payload_hashes"]
            c4a_phases = graph["c4a_phases"]

            snapshot = C5G0CompletedGraphSnapshot(
                project_id=project_id,
                task_id=task_id,
                task_status=task["status"],
                last_stable_status=task["last_stable_status"],
                task_revision=task["aggregate_revision"],
                recovery_error_code=task["recovery_error_code"],
                durable_envelopes=tuple(envelopes),
                payload_content_hashes=tuple(payload_hashes),
                operation_count=_count(conn, "creation_operation"),
                audit_count=_count(conn, "creation_audit_event"),
                decision_count=_count(conn, "creation_author_decision"),
                consumption_count=_count(conn, "creation_decision_consumption"),
                c3_journal_count=_count(conn, "canon_commit_journal"),
                c4a_attempt_count=_count(conn, "canon_apply_attempt"),
                c4a_event_count=_count(conn, "canon_apply_event"),
                c4a_completed_event_count=_count_where(
                    conn, "canon_apply_event", "phase = 'COMPLETED'"
                ),
                receipt_count=_count(conn, "canon_commit_receipt"),
                activation_attempt_id=attempt.attempt_id,
                activation_replay_envelope_json=events[1].replay_envelope_json or "",
                projection_identity_bound=True,
                c4a_recovery_event_count=c4a_phases.count("RECOVERY_REQUIRED"),
                c4a_unknown_event_count=0,
            )
            _verify_completed_graph_snapshot(snapshot)
            return C5G0CompletedGraphEvidence(
                status="COMPLETED_GRAPH_VERIFIED",
                project_id=project_id,
                task_id=task_id,
                task_revision=task["aggregate_revision"],
                activation_attempt_id=attempt.attempt_id,
                activation_replay_envelope_json=events[1].replay_envelope_json or "",
                durable_envelopes=tuple(envelopes),
                payload_content_hashes=tuple(payload_hashes),
                task_facts=graph["task_facts"],
                artifact_facts=graph["artifact_facts"],
                operation_facts=graph["operation_facts"],
                decision_facts=graph["decision_facts"],
                consumption_facts=graph["consumption_facts"],
                audit_facts=graph["audit_facts"],
                journal_facts=graph["journal_facts"],
                receipt_facts=graph["receipt_facts"],
                apply_attempt_facts=graph["apply_attempt_facts"],
                apply_event_facts=graph["apply_event_facts"],
            )
        except C5G0ActivationStateVerificationError:
            raise
        except Exception as exc:
            raise C5G0ActivationStateVerificationError(
                "completed graph verification failed"
            ) from exc
        finally:
            try:
                conn.close()
            except Exception as exc:
                raise C5G0ActivationStateVerificationError(
                    "read-only completed graph verifier close failed"
                ) from exc

    @staticmethod
    def _verify_connection(conn: sqlite3.Connection) -> None:
        if not isinstance(conn, sqlite3.Connection):
            raise C5G0ActivationStateVerificationError("verifier requires a SQLite connection")
        if conn.execute("PRAGMA query_only").fetchone()[0] != 1:
            raise C5G0ActivationStateVerificationError("verifier connection is not query_only")
        if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise C5G0ActivationStateVerificationError("foreign keys are disabled")
        from xiaoshuo.infrastructure.persistence.sqlite.maintenance import APPLICATION_ID

        if conn.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
            raise C5G0ActivationStateVerificationError("SQLite application_id is invalid")
        if conn.execute("PRAGMA user_version").fetchone()[0] != 6:
            raise C5G0ActivationStateVerificationError("SQLite user_version is not v006")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise C5G0ActivationStateVerificationError("SQLite integrity_check failed")
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            raise C5G0ActivationStateVerificationError("SQLite foreign_key_check failed")

    @staticmethod
    def _close_census_connection(conn: sqlite3.Connection) -> None:
        try:
            conn.close()
        except Exception as exc:
            raise C5G0ActivationStateVerificationError(
                "runtime census connection close failed"
            ) from exc

    @staticmethod
    def _verify_schema(conn: sqlite3.Connection) -> None:
        _verify_migration_ledger(conn)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        if tables != _EXPECTED_TABLES:
            raise C5G0ActivationStateVerificationError(
                "SQLite schema is not exactly v001 through v006"
            )

    @staticmethod
    def _verify_zero_tables(conn: sqlite3.Connection) -> None:
        for table in _ZERO_TABLES:
            if conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] != 0:
                raise C5G0ActivationStateVerificationError(
                    f"C4B_ACTIVATED_CLEAN contains prohibited facts in {table}"
                )

    @staticmethod
    def _read_unique_attempt(conn: sqlite3.Connection):
        rows = conn.execute("SELECT * FROM canon_activation_attempt").fetchall()
        if len(rows) != 1:
            raise C5G0ActivationStateVerificationError(
                "C4b activation attempt census must contain exactly one row"
            )
        attempt = SqliteCanonActivationRepository(conn)._attempt_from_row(rows[0])
        _require_digest(attempt.request_digest, "attempt.request_digest")
        _require_digest(attempt.seed_digest, "attempt.seed_digest")
        _require_digest(attempt.pointer_content_hash, "attempt.pointer_content_hash")
        return attempt

    @staticmethod
    def _read_unique_artifact_ref(conn) -> ArtifactRef:
        rows = conn.execute(
            "SELECT artifact_id, schema_version, content_hash FROM creation_artifact_ref"
        ).fetchall()
        if len(rows) != 1:
            raise C5G0ActivationStateVerificationError(
                "C4B_ACTIVATED_CLEAN requires exactly one ArtifactRef"
            )
        try:
            return ArtifactRef(rows[0][0], rows[0][1], rows[0][2])
        except Exception as exc:
            raise C5G0ActivationStateVerificationError("activation ArtifactRef is invalid") from exc

    @staticmethod
    def _read_unique_events(conn, attempt_id: str, project_id: str):
        rows = conn.execute(
            "SELECT * FROM canon_activation_event ORDER BY created_at, event_id"
        ).fetchall()
        if len(rows) != 2:
            raise C5G0ActivationStateVerificationError(
                "C4b activation event census must contain exactly two rows"
            )
        repo = SqliteCanonActivationRepository(conn)
        events = tuple(repo._event_from_row(row) for row in rows)
        if any(event.attempt_id != attempt_id or event.project_id != project_id for event in events):
            raise C5G0ActivationStateVerificationError(
                "activation events are not bound to the unique attempt/project"
            )
        return events


def verify_c4b_activated_clean(runtime, *, project_id: str, attempt_key: str, request_digest: str):
    """Convenience entry point owned by the verifier boundary."""

    return C5G0ActivationStateVerifier(runtime).verify(
        project_id=project_id,
        attempt_key=attempt_key,
        request_digest=request_digest,
    )


def verify_fresh_gate(runtime, *, project_id: str, attempt_key: str, request_digest: str):
    """Convenience entry point for the composition-owned fresh gate."""

    return C5G0ActivationStateVerifier(runtime).verify_fresh_gate(
        project_id=project_id,
        attempt_key=attempt_key,
        request_digest=request_digest,
    )


def verify_completed_graph(
    runtime,
    *,
    project_id: str,
    task_id: str,
    attempt_key: str,
    request_digest: str,
):
    """Composition-owned read-only completed-graph entry point."""

    return C5G0ActivationStateVerifier(runtime).verify_completed_graph(
        project_id=project_id,
        task_id=task_id,
        attempt_key=attempt_key,
        request_digest=request_digest,
    )


def _census_runtime_filesystem(runtime) -> dict[str, object]:
    """Read only the config-bound runtime shape used for branch selection."""

    root = Path(runtime.root)
    db_value = getattr(runtime, "db_path", None)
    if db_value is None:
        db_value = runtime.settings.db_path
    db = Path(db_value)
    children = {
        "payloads": Path(runtime.payloads_dir),
        "projection": Path(runtime.projection_dir),
        "backups": Path(getattr(runtime, "backups_dir", root / "backups")),
        "exports": Path(runtime.exports_dir),
    }
    paths = (root, db, *children.values())
    exists = {path: path.exists() for path in paths}
    sidecars = tuple(
        str(path)
        for path in (Path(f"{db}-wal"), Path(f"{db}-shm"), Path(f"{db}-journal"))
        if path.exists()
    )
    wal_exists = Path(f"{db}-wal").exists()
    shm_exists = Path(f"{db}-shm").exists()
    reparse = False
    inspect_paths = [path for path in paths if exists[path]]
    if root.exists():
        try:
            _verify_no_reparse_tree(root)
        except C5G0ActivationStateVerificationError:
            reparse = True
    for path in (*paths, *(Path(value) for value in sidecars)):
        if path.exists() and _is_reparse_point(path):
            reparse = True
    del inspect_paths

    lock = _runtime_lock_residue(root)
    if Path(f"{db}-journal").exists():
        lock = True

    root_exists = exists[root]
    database_exists = exists[db]
    payloads_exists = exists[children["payloads"]]
    projection_exists = exists[children["projection"]]
    backups_exists = exists[children["backups"]]
    exports_exists = exists[children["exports"]]
    any_runtime = any((root_exists, database_exists, payloads_exists, projection_exists,
                       backups_exists, exports_exists, bool(sidecars)))
    partial = (
        payloads_exists != projection_exists
        or (any_runtime and not root_exists)
        or (root_exists and not database_exists and (payloads_exists or projection_exists))
        or (bool(sidecars) and not database_exists)
        or (wal_exists != shm_exists)
    )
    residue = exports_exists
    backup_families: tuple[dict[str, object], ...] = ()
    if root_exists and root.is_dir():
        allowed_root_entries = {
            db,
            Path(f"{db}-wal"),
            Path(f"{db}-shm"),
            children["payloads"],
            children["projection"],
            children["backups"],
            children["exports"],
        }
        try:
            residue = residue or any(
                not any(os.path.normcase(str(entry)) == os.path.normcase(str(allowed))
                        for allowed in allowed_root_entries)
                for entry in root.iterdir()
            )
        except OSError:
            residue = True
    if backups_exists:
        if not children["backups"].is_dir():
            residue = True
        else:
            try:
                backup_families, backup_residue = _inspect_backup_families(
                    children["backups"]
                )
                residue = residue or backup_residue
            except (OSError, C5G0ActivationStateVerificationError):
                residue = True
    return {
        "root": root,
        "database": database_exists,
        "root_exists": root_exists,
        "payloads_exists": payloads_exists,
        "projection_exists": projection_exists,
        "backups_exists": backups_exists,
        "exports_exists": exports_exists,
        "sidecars": sidecars,
        "reparse": reparse,
        "lock": lock,
        "partial": partial,
        "residue": residue,
        "backup_families": backup_families,
        "recovery_compatible": bool(
            backup_families
            and any(family["sidecars"] for family in backup_families)
        ),
        "any": any_runtime,
    }


def _inspect_backup_families(
    backups_dir: Path,
) -> tuple[tuple[dict[str, object], ...], bool]:
    """Census only the approved v002-v006 backup families and sidecars."""

    entries = tuple(backups_dir.iterdir())
    if not entries:
        return (), True
    mains: dict[int, Path] = {}
    sidecars: dict[Path, list[Path]] = {}
    residue = False
    for entry in entries:
        if _is_reparse_point(entry) or not entry.is_file():
            residue = True
            continue
        main_match = _BACKUP_MAIN_FILE.fullmatch(entry.name)
        if main_match is not None:
            version = int(main_match.group(1))
            if version in mains:
                residue = True
            else:
                mains[version] = entry
            continue
        sidecar_match = _BACKUP_SIDECAR_FILE.fullmatch(entry.name)
        if sidecar_match is not None:
            main = Path(str(entry)[:-4])
            sidecars.setdefault(main, []).append(entry)
            continue
        residue = True

    if set(mains) != {2, 3, 4, 5, 6}:
        residue = True
    families: list[dict[str, object]] = []
    for version in sorted(mains):
        main = mains[version]
        paired = tuple(sorted(sidecars.get(main, ()), key=lambda path: path.name))
        for sidecar in paired:
            if sidecar.name not in {main.name + "-wal", main.name + "-shm"}:
                residue = True
        families.append({"version": version, "main": main, "sidecars": paired})
    for main, paired in sidecars.items():
        if main not in mains.values() or len(paired) > 2:
            residue = True
    return tuple(families), residue


def _runtime_lock_residue(root: Path) -> bool:
    """Find coordination files without following links or acquiring locks."""

    if not root.exists() or not root.is_dir():
        return False
    stack = [root]
    try:
        while stack:
            current = stack.pop()
            for entry in os.scandir(current):
                if entry.name.endswith(".lock") or entry.name.endswith(".journal"):
                    return True
                child = Path(entry.path)
                if entry.is_dir(follow_symlinks=False):
                    stack.append(child)
    except OSError:
        return True
    return False


def _path_text(path: Path) -> str:
    return path.resolve(strict=True).as_posix()


def _open_immutable_connection(path: Path) -> sqlite3.Connection:
    """Open the verifier's only production SQLite read boundary."""

    uri = f"file:{_path_text(path)}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA query_only = ON")
        if conn.execute("PRAGMA query_only").fetchone()[0] != 1:
            raise C5G0ActivationStateVerificationError(
                "immutable verifier connection is not query_only"
            )
    except Exception:
        conn.close()
        raise
    return conn


def _expected_backup_column_contract(version: int) -> dict[str, tuple[str, ...]]:
    if version not in _PRE_MIGRATION_TABLES:
        raise C5G0ActivationStateVerificationError(
            "backup migration family is not supported"
        )
    columns = dict(_PRE_MIGRATION_COLUMNS)
    chapter_key = "chapter_task_v001" if version <= 3 else "chapter_task_v003"
    columns["chapter_task"] = columns.pop(chapter_key)
    journal_key = "canon_commit_journal_v003" if version == 4 else "canon_commit_journal_v004"
    columns["canon_commit_journal"] = columns.pop(journal_key)
    if version >= 5:
        columns["canon_commit_journal_v003_legacy"] = (
            *columns["canon_commit_journal_v003"],
            "legacy_status",
        )
        columns["canon_commit_receipt_v003_legacy"] = (
            *columns["canon_commit_receipt"],
            "legacy_status",
        )
    return {
        table: columns[table]
        for table in _PRE_MIGRATION_TABLES[version]
    }


def _verify_backup_schema_and_ledger(
    conn: sqlite3.Connection,
    version: int,
) -> tuple[tuple[str, ...], tuple[tuple[int, str, str], ...]]:
    """Verify the exact pre-migration schema and ledger prefix for a backup."""

    tables = tuple(
        sorted(
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        )
    )
    expected_tables = _PRE_MIGRATION_TABLES[version]
    if set(tables) != expected_tables:
        raise C5G0ActivationStateVerificationError(
            "backup schema table identity does not match its migration family"
        )
    expected_columns = _expected_backup_column_contract(version)
    for table, expected in expected_columns.items():
        actual = tuple(
            str(row[1])
            for row in conn.execute(f'PRAGMA table_info("{table}")')
        )
        if actual != expected:
            raise C5G0ActivationStateVerificationError(
                f"backup schema column identity mismatch for {table}"
            )

    migrations = _discover_migrations()
    expected_ledger = tuple(migrations[: version - 1])
    try:
        rows = conn.execute(
            "SELECT version, file_name, sha256 "
            "FROM creation_schema_migration ORDER BY version"
        ).fetchall()
    except sqlite3.Error as exc:
        raise C5G0ActivationStateVerificationError(
            "backup migration ledger cannot be read"
        ) from exc
    actual_ledger = tuple(tuple(row) for row in rows)
    if actual_ledger != expected_ledger:
        raise C5G0ActivationStateVerificationError(
            "backup migration ledger identity does not match its migration family"
        )
    return tables, actual_ledger


def _verify_backup_families(
    runtime,
    families: tuple[dict[str, object], ...],
) -> tuple[C5G0BackupFileEvidence, ...]:
    """Verify backup identity through immutable URI connections only."""

    if not families:
        return ()
    from xiaoshuo.infrastructure.persistence.sqlite.maintenance import APPLICATION_ID

    evidence: list[C5G0BackupFileEvidence] = []
    for family in families:
        version = int(family["version"])
        main = Path(family["main"])
        sidecars = tuple(Path(value) for value in family["sidecars"])
        if _is_reparse_point(main) or not main.is_file():
            raise C5G0ActivationStateVerificationError("backup main is not a regular file")
        conn: sqlite3.Connection | None = None
        close_error: Exception | None = None
        try:
            conn = _open_immutable_connection(main)
            application_id = int(conn.execute("PRAGMA application_id").fetchone()[0])
            user_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if application_id != APPLICATION_ID or user_version != version - 1:
                raise C5G0ActivationStateVerificationError(
                    "backup identity does not match its migration family"
                )
            schema_tables, migration_ledger = _verify_backup_schema_and_ledger(
                conn, version
            )
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise C5G0ActivationStateVerificationError("backup integrity_check failed")
            if conn.execute("PRAGMA foreign_key_check").fetchall():
                raise C5G0ActivationStateVerificationError("backup foreign_key_check failed")
        except C5G0ActivationStateVerificationError:
            raise
        except Exception as exc:
            raise C5G0ActivationStateVerificationError(
                "backup immutable identity read failed"
            ) from exc
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception as exc:
                    close_error = exc
        if close_error is not None:
            raise C5G0ActivationStateVerificationError(
                "backup immutable connection close failed"
            ) from close_error

        main_relative = main.relative_to(Path(runtime.root)).as_posix()
        evidence.append(
            C5G0BackupFileEvidence(
                family_version=version,
                relative_path=main_relative,
                suffix=".db",
                byte_length=main.stat().st_size,
                sha256=_sha256(main.read_bytes()),
                regular_file=True,
                reparse=False,
                paired_main_relative_path=main_relative,
                database_user_version=user_version,
                database_application_id=application_id,
                database_schema_tables=schema_tables,
                migration_ledger=migration_ledger,
            )
        )
        for sidecar in sidecars:
            if _is_reparse_point(sidecar) or not sidecar.is_file():
                raise C5G0ActivationStateVerificationError(
                    "backup sidecar is not a regular file"
                )
            evidence.append(
                C5G0BackupFileEvidence(
                    family_version=version,
                    relative_path=sidecar.relative_to(Path(runtime.root)).as_posix(),
                    suffix=sidecar.name[len(main.name):],
                    byte_length=sidecar.stat().st_size,
                    sha256=_sha256(sidecar.read_bytes()),
                    regular_file=True,
                    reparse=False,
                    paired_main_relative_path=main_relative,
                )
            )
    return tuple(evidence)


def _read_runtime_business_census(conn: sqlite3.Connection) -> dict[str, object]:
    counts: dict[str, int] = {}
    for table in sorted(_EXPECTED_TABLES - {"creation_schema_migration"}):
        counts[table] = int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    task_rows = conn.execute(
        "SELECT task_id, project_id, status, recovery_error_code, "
        "recovery_failed_operation_id, recovery_retry_from_status FROM chapter_task "
        "ORDER BY task_id"
    ).fetchall()
    task_ids = [str(row["task_id"]) for row in task_rows]
    completed_task_ids = [
        str(row["task_id"]) for row in task_rows if row["status"] == "COMPLETED"
    ]
    recovery = any(
        row["status"] == "RECOVERY_REQUIRED"
        or row["recovery_error_code"] is not None
        or row["recovery_failed_operation_id"] is not None
        or row["recovery_retry_from_status"] is not None
        for row in task_rows
    )
    apply_phases = tuple(
        str(row[0])
        for row in conn.execute("SELECT phase FROM canon_apply_event ORDER BY event_id")
    )
    recovery = recovery or any(
        phase in {"RECOVERY_REQUIRED", "MANUAL_RECOVERY_REQUIRED"}
        for phase in apply_phases
    )
    fact_count = sum(counts.values())
    return {
        "counts": counts,
        "fact_count": fact_count,
        "task_ids": task_ids,
        "completed_task_ids": completed_task_ids,
        "recovery": recovery,
        "activation_attempt_count": counts["canon_activation_attempt"],
        "activation_event_count": counts["canon_activation_event"],
        "artifact_ref_count": counts["creation_artifact_ref"],
    }


def _is_initialized_empty_census(facts: dict[str, object], fs: dict[str, object]) -> bool:
    return (
        int(facts["fact_count"]) == 0
        and bool(fs["root_exists"])
        and bool(fs["database"])
        and not bool(fs["payloads_exists"])
        and not bool(fs["projection_exists"])
        and not bool(fs["exports_exists"])
        and not bool(fs["partial"])
        and not bool(fs["residue"])
        and not bool(fs["reparse"])
        and not bool(fs["lock"])
        and bool(fs["backups_exists"])
        and len(fs["backup_families"]) == 5
    )


def _is_c4b_clean_candidate(facts: dict[str, object], fs: dict[str, object]) -> bool:
    counts = facts["counts"]
    assert isinstance(counts, dict)
    return (
        bool(fs["payloads_exists"])
        and bool(fs["projection_exists"])
        and not bool(fs["exports_exists"])
        and facts["activation_attempt_count"] == 1
        and facts["activation_event_count"] == 2
        and facts["artifact_ref_count"] == 1
        and all(counts[table] == 0 for table in _ZERO_TABLES)
        and not facts["task_ids"]
    )


def _runtime_census(
    fs: dict[str, object],
    status: C5G0RuntimeCensusStatus,
    reason: str,
    *,
    facts: dict[str, object] | None = None,
    clean_evidence: C5G0ActivationCleanEvidence | None = None,
    completed_graph_evidence: C5G0CompletedGraphEvidence | None = None,
    reason_detail: str | None = None,
) -> C5G0RuntimeCensus:
    facts = facts or {"counts": {}, "task_ids": [], "completed_task_ids": []}
    counts = facts["counts"]
    assert isinstance(counts, dict)
    detail = f": {reason_detail}" if reason_detail else ""
    return C5G0RuntimeCensus(
        status=status,
        reason=reason + detail,
        root_exists=bool(fs["root_exists"]),
        database_exists=bool(fs["database"]),
        payloads_exists=bool(fs["payloads_exists"]),
        projection_exists=bool(fs["projection_exists"]),
        backups_exists=bool(fs["backups_exists"]),
        exports_exists=bool(fs["exports_exists"]),
        sqlite_sidecars=tuple(fs["sidecars"]),
        business_fact_counts=tuple(sorted((str(key), int(value)) for key, value in counts.items())),
        task_ids=tuple(str(value) for value in facts["task_ids"]),
        completed_task_ids=tuple(str(value) for value in facts["completed_task_ids"]),
        clean_evidence=clean_evidence,
        completed_graph_evidence=completed_graph_evidence,
        backup_files=tuple(fs.get("backup_files", ())),
        root_reparse=bool(fs["reparse"]),
        lock_observed=bool(fs["lock"]),
        filesystem_partial=bool(fs["partial"]),
        filesystem_residue=bool(fs["residue"]),
    )


def _same_fresh_census(left: C5G0RuntimeCensus, right: C5G0RuntimeCensus) -> bool:
    return (
        left.status == right.status
        and left.root_exists == right.root_exists
        and left.database_exists == right.database_exists
        and left.payloads_exists == right.payloads_exists
        and left.projection_exists == right.projection_exists
        and left.backups_exists == right.backups_exists
        and left.exports_exists == right.exports_exists
        and left.sqlite_sidecars == right.sqlite_sidecars
        and left.business_fact_counts == right.business_fact_counts
        and left.task_ids == right.task_ids
        and left.completed_task_ids == right.completed_task_ids
        and left.backup_files == right.backup_files
        and left.root_reparse == right.root_reparse
        and left.lock_observed == right.lock_observed
        and left.filesystem_partial == right.filesystem_partial
        and left.filesystem_residue == right.filesystem_residue
    )


def _read_payload(store: object, digest: str) -> bytes:
    if not callable(getattr(store, "read", None)):
        raise C5G0ActivationStateVerificationError("activation payload reader is unavailable")
    data = store.read(digest)
    if type(data) is not bytes or _sha256(data) != digest:
        raise C5G0ActivationStateVerificationError("activation payload readback is invalid")
    return data


def _verify_authoring_payload(
    store: object,
    ref: ArtifactRef,
    *,
    expected_kind: AuthoringArtifactKind,
    project_id: str,
    task_id: str,
    chapter_number: object,
    reviewed_draft_ref: ArtifactRef | None = None,
) -> AuthoringArtifactEnvelope:
    """Read and type-check one graph authoring payload without creating facts."""

    data = _read_payload(store, ref.content_hash)
    try:
        envelope = parse_authoring_artifact_envelope(data)
    except Exception as exc:
        raise C5G0ActivationStateVerificationError(
            "completed graph authoring payload is not a trusted canonical envelope"
        ) from exc
    if (
        envelope.artifact_kind is not expected_kind
        or envelope.project_id != project_id
        or envelope.task_id != task_id
        or envelope.chapter_number != chapter_number
    ):
        raise C5G0ActivationStateVerificationError(
            "completed graph authoring payload identity is not bound to the Task"
        )
    if expected_kind is AuthoringArtifactKind.REVIEW:
        if envelope.reviewed_draft_ref != reviewed_draft_ref:
            raise C5G0ActivationStateVerificationError(
                "completed graph review payload targets the wrong DRAFT"
            )
    elif envelope.reviewed_draft_ref is not None:
        raise C5G0ActivationStateVerificationError(
            "non-review graph authoring payload contains a review reference"
        )
    return envelope


def _verify_runtime_roots(runtime) -> None:
    root = Path(runtime.root)
    if not root.is_dir():
        raise C5G0ActivationStateVerificationError("runtime root is missing")
    for label, path in (
        ("runtime.root", root),
        ("runtime.payloads_dir", runtime.payloads_dir),
        ("runtime.projection_dir", runtime.projection_dir),
    ):
        value = Path(path)
        if value.drive.upper() != "D:" or value.resolve() == Path("D:/").resolve():
            raise C5G0ActivationStateVerificationError(f"{label} is not a safe D-drive path")
        if not value.is_dir():
            raise C5G0ActivationStateVerificationError(f"{label} is missing")
        try:
            value.resolve().relative_to(root.resolve())
        except ValueError as exc:
            raise C5G0ActivationStateVerificationError(f"{label} escapes runtime root") from exc
    _verify_no_reparse_tree(root)
    if Path(runtime.exports_dir).exists():
        raise C5G0ActivationStateVerificationError("exports root must not exist")


def _verify_no_reparse_tree(root: Path) -> None:
    """Reject symlinks, junctions, and every Windows reparse-point residue."""

    stack = [root]
    while stack:
        current = stack.pop()
        if _is_reparse_point(current):
            raise C5G0ActivationStateVerificationError(
                f"reparse/junction residue is not allowed: {current}"
            )
        if not current.is_dir():
            continue
        try:
            entries = tuple(os.scandir(current))
        except OSError as exc:
            raise C5G0ActivationStateVerificationError(
                f"cannot inspect runtime root entry: {current}"
            ) from exc
        for entry in entries:
            child = Path(entry.path)
            if _is_reparse_point(child):
                raise C5G0ActivationStateVerificationError(
                    f"reparse/junction residue is not allowed: {child}"
                )
            if entry.is_dir(follow_symlinks=False):
                stack.append(child)


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    except OSError as exc:
        raise C5G0ActivationStateVerificationError(
            f"cannot inspect path attributes: {path}"
        ) from exc
    return bool(attributes & _REPARSE_POINT)


def _read_regular_file(path: Path, label: str) -> bytes:
    if _is_reparse_point(path) or not path.is_file():
        raise C5G0ActivationStateVerificationError(f"{label} is not a regular file")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise C5G0ActivationStateVerificationError(f"{label} cannot be read") from exc


def _verify_event_contract(
    events: tuple[object, object],
    *,
    attempt: object | None = None,
    project_id: str | None = None,
    attempt_key: str | None = None,
    request_digest: str | None = None,
) -> None:
    prepared, ready = events
    if (
        prepared.phase != "PREPARED"
        or prepared.result != "PREPARED"
        or prepared.error_code is not None
        or prepared.replay_envelope_json is not None
        or prepared.replay_envelope_hash is not None
    ):
        raise C5G0ActivationStateVerificationError(
            "PREPARED event result/error/envelope contract is invalid"
        )
    if (
        ready.phase != "READY_FOR_MARKER"
        or ready.result != "READY_FOR_MARKER"
        or ready.error_code is not None
        or not isinstance(ready.replay_envelope_json, str)
        or not ready.replay_envelope_json
        or not isinstance(ready.replay_envelope_hash, str)
        or _sha256(ready.replay_envelope_json.encode("utf-8"))
        != ready.replay_envelope_hash
    ):
        raise C5G0ActivationStateVerificationError(
            "READY_FOR_MARKER event result/error/envelope contract is invalid"
        )
    try:
        value = json.loads(ready.replay_envelope_json)
        canonical = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise C5G0ActivationStateVerificationError(
            "READY_FOR_MARKER replay envelope is invalid"
        ) from exc
    if not isinstance(value, dict) or canonical != ready.replay_envelope_json.encode("utf-8"):
        raise C5G0ActivationStateVerificationError(
            "READY_FOR_MARKER replay envelope is not canonical"
        )
    if attempt is not None:
        expected = {
            "activation": "C4B_FIRST_PROJECTION",
            "attempt_id": attempt.attempt_id,
            "attempt_key": attempt_key,
            "bundle_content_hash": attempt.bundle_content_hash,
            "bundle_ref_artifact_id": attempt.bundle_ref_artifact_id,
            "manifest_hash": attempt.manifest_hash,
            "pointer_content_hash": attempt.pointer_content_hash,
            "project_id": project_id,
            "request_digest": request_digest,
            "seed_digest": attempt.seed_digest,
            "version_id": attempt.version_id,
            "world_hash": attempt.world_hash,
        }
        if value != expected:
            raise C5G0ActivationStateVerificationError(
                "READY_FOR_MARKER replay envelope identity is not bound to the attempt"
            )


def _verify_durable_envelope(envelope: object, expected_hash: object) -> str:
    if not isinstance(envelope, str) or not isinstance(expected_hash, str):
        raise C5G0ActivationStateVerificationError(
            "durable operation envelope is missing"
        )
    if _sha256(envelope.encode("utf-8")) != expected_hash:
        raise C5G0ActivationStateVerificationError(
            "durable operation envelope hash mismatch"
        )
    try:
        value = json.loads(envelope)
        canonical = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise C5G0ActivationStateVerificationError(
            "durable operation envelope is not canonical"
        ) from exc
    if not isinstance(value, dict) or canonical != envelope.encode("utf-8"):
        raise C5G0ActivationStateVerificationError(
            "durable operation envelope is not canonical"
        )
    return envelope


def _read_and_verify_completed_graph(
    conn: sqlite3.Connection,
    payload_store: object,
    *,
    task_id: str,
    project_id: str,
    operator_identity: str,
    activation_attempt: object,
    activation_ref: ArtifactRef,
    activation_bundle: CanonicalBundle,
    activation_events: tuple[object, object],
    activation_identity: object,
    projection_dir: Path,
    operation_rows: tuple[object, ...] | None = None,
) -> dict[str, object]:
    """Read and validate the complete G0-C durable graph.

    This function intentionally uses only the verifier's own SQL census and
    typed value boundaries.  It does not import a G0-A runtime helper and it
    never obtains a writer, lock, or mutable repository.
    """

    task_rows = conn.execute("SELECT * FROM chapter_task").fetchall()
    if len(task_rows) != 1:
        raise C5G0ActivationStateVerificationError(
            "completed graph must contain exactly one Task"
        )
    task = task_rows[0]
    if _r(task, "task_id") != task_id or _r(task, "project_id") != project_id:
        raise C5G0ActivationStateVerificationError("Task is not bound to project/task request")
    if (
        _r(task, "status") != "COMPLETED"
        or _r(task, "last_stable_status") != "COMPLETED"
        or _r(task, "recovery_error_code") is not None
        or _r(task, "recovery_failed_operation_id") is not None
        or _r(task, "recovery_retry_from_status") is not None
    ):
        raise C5G0ActivationStateVerificationError("Task is not a clean completed fact")
    revision = _r(task, "aggregate_revision")
    if type(revision) is not int or revision != 8:
        raise C5G0ActivationStateVerificationError(
            "completed graph Task revision is not the G0-C terminal revision"
        )
    for legacy_table in ("canon_commit_journal_v003_legacy", "canon_commit_receipt_v003_legacy"):
        if conn.execute(f'SELECT COUNT(*) FROM "{legacy_table}"').fetchone()[0] != 0:
            raise C5G0ActivationStateVerificationError("legacy Canon facts cannot be part of a completed graph")

    artifact_rows = conn.execute(
        "SELECT artifact_id, schema_version, content_hash "
        "FROM creation_artifact_ref ORDER BY artifact_id"
    ).fetchall()
    registry: dict[str, ArtifactRef] = {}
    for row in artifact_rows:
        ref = _artifact_from_values(
            _r(row, "artifact_id"), _r(row, "schema_version"), _r(row, "content_hash")
        )
        if ref.artifact_id in registry:
            raise C5G0ActivationStateVerificationError("duplicate ArtifactRef identity")
        registry[ref.artifact_id] = ref
        _read_payload(payload_store, ref.content_hash)

    role_columns = (
        "creative_intent_ref_artifact_id",
        "confirmed_plan_ref_artifact_id",
        "current_author_draft_ref_artifact_id",
        "review_target_draft_ref_artifact_id",
        "adopted_draft_ref_artifact_id",
        "latest_review_ref_artifact_id",
        "pending_changeset_ref_artifact_id",
        "commit_receipt_ref_artifact_id",
    )
    role_ids = tuple(_r(task, column) for column in role_columns)
    if any(not isinstance(value, str) or not value for value in role_ids):
        raise C5G0ActivationStateVerificationError(
            "completed graph Task is missing a durable role reference"
        )
    task_refs = tuple(_require_registered_ref(registry, value) for value in role_ids)
    if task_refs[2] != task_refs[3] or task_refs[4] != task_refs[3]:
        raise C5G0ActivationStateVerificationError(
            "completed graph draft role references are not the same trusted artifact"
        )
    chapter_number = _r(task, "chapter_number")
    _verify_authoring_payload(
        payload_store,
        task_refs[0],
        expected_kind=AuthoringArtifactKind.CREATIVE_INTENT,
        project_id=project_id,
        task_id=task_id,
        chapter_number=chapter_number,
    )
    _verify_authoring_payload(
        payload_store,
        task_refs[1],
        expected_kind=AuthoringArtifactKind.PLAN,
        project_id=project_id,
        task_id=task_id,
        chapter_number=chapter_number,
    )
    for draft_ref in (task_refs[2], task_refs[3], task_refs[4]):
        _verify_authoring_payload(
            payload_store,
            draft_ref,
            expected_kind=AuthoringArtifactKind.DRAFT,
            project_id=project_id,
            task_id=task_id,
            chapter_number=chapter_number,
        )
    _verify_authoring_payload(
        payload_store,
        task_refs[5],
        expected_kind=AuthoringArtifactKind.REVIEW,
        project_id=project_id,
        task_id=task_id,
        chapter_number=chapter_number,
        reviewed_draft_ref=task_refs[3],
    )

    if operation_rows is None:
        operation_rows = _read_operation_rows(conn)
    expected_operation_kinds = (
        "CREATE_CHAPTER_TASK",
        "PREPARE_PLAN_FOR_APPROVAL",
        "CREATE_AUTHOR_DECISION",
        "CONSUME_AUTHOR_DECISION",
        "SUBMIT_AUTHORING_ARTIFACT",
        "SUBMIT_DRAFT_FOR_REVIEW",
        "CREATE_AUTHOR_DECISION",
        "CONSUME_AUTHOR_DECISION",
        "PREPARE_CANON_CHANGESET",
        "CREATE_AUTHOR_DECISION",
        "APPROVE_CANON_CHANGESET",
    )
    operation_facts: list[C5G0GraphFact] = []
    operation_values: list[dict[str, object]] = []
    envelopes: list[str] = []
    if len(operation_rows) != len(expected_operation_kinds):
        raise C5G0ActivationStateVerificationError(
            "completed graph must contain exactly eleven creation operations"
        )
    for position, row in enumerate(operation_rows):
        expected_kind = expected_operation_kinds[position]
        operation_id = _r(row, "operation_id")
        envelope = _verify_durable_envelope(
            _r(row, "result_envelope_json"), _r(row, "result_envelope_hash")
        )
        try:
            value = json.loads(envelope)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise C5G0ActivationStateVerificationError(
                "completed graph operation envelope is invalid"
            ) from exc
        if not isinstance(value, dict):
            raise C5G0ActivationStateVerificationError("operation envelope is not an object")
        operation_reference = value.get("original_operation_id", value.get("operation_id"))
        if (
            not isinstance(operation_id, str)
            or operation_reference != operation_id
            or value.get("task_id") != task_id
            or value.get("operation_kind") != expected_kind
            or (
                value.get("task_revision") is not None
                and (
                    type(value.get("task_revision")) is not int
                    or not 0 <= value["task_revision"] <= revision
                )
            )
                ):
                    raise C5G0ActivationStateVerificationError(
                        "operation envelope is not bound to its durable operation"
                    )
        operation_values.append({"row": row, "value": value})
        envelopes.append(envelope)
        operation_facts.append(
            _fact(
                "creation_operation",
                row,
                artifact_refs=(),
                envelope_json=envelope,
                envelope_hash=_r(row, "result_envelope_hash"),
            )
        )
    if tuple(value["value"]["operation_kind"] for value in operation_values) != expected_operation_kinds:
        raise C5G0ActivationStateVerificationError(
            "creation operation sequence is not the exact G0-C graph"
        )

    decision_rows = conn.execute(
        "SELECT * FROM creation_author_decision ORDER BY created_at, decision_id"
    ).fetchall()
    expected_decision_types = ("CONFIRM_PLAN", "ADOPT_DRAFT", "APPROVE_CHANGESET")
    decision_values: list[dict[str, object]] = []
    decision_facts: list[C5G0GraphFact] = []
    decision_repository = SqliteAuthorDecisionRepository(conn)
    for row in decision_rows:
        target = _require_registered_ref(registry, _r(row, "target_ref_artifact_id"))
        try:
            typed_decision = decision_repository.get(_r(row, "decision_id"))
        except Exception as exc:
            raise C5G0ActivationStateVerificationError("decision content hash cannot be revalidated") from exc
        if typed_decision is None:
            raise C5G0ActivationStateVerificationError("decision is missing from its typed repository")
        if (
            typed_decision.target_ref != target
            or typed_decision.task_id != task_id
            or _r(row, "task_id") != task_id
            or _r(row, "actor_kind") != "AUTHOR"
            or _r(row, "author_id") != operator_identity
            or _r(row, "actor_id") != operator_identity
            or _r(row, "based_on_task_revision") not in (1, 4, 6)
            or _r(row, "content_hash") is None
        ):
            raise C5G0ActivationStateVerificationError(
                "decision is not bound to the trusted Task and operator"
            )
        decision_values.append({"row": row, "target": target})
        decision_facts.append(_fact("creation_author_decision", row, (target,)))
    if tuple(_r(value["row"], "decision_type") for value in decision_values) != expected_decision_types:
        raise C5G0ActivationStateVerificationError(
            "decision sequence is not the exact G0-C decision graph"
        )
    expected_targets = (task_refs[1], task_refs[3], task_refs[6])
    if tuple(value["target"] for value in decision_values) != expected_targets:
        raise C5G0ActivationStateVerificationError(
            "decision target ArtifactRefs do not match Task roles"
        )

    consumption_rows = conn.execute(
        "SELECT * FROM creation_decision_consumption ORDER BY consumed_at, consumption_id"
    ).fetchall()
    if len(consumption_rows) != 3:
        raise C5G0ActivationStateVerificationError(
            "completed graph must contain exactly three decision consumptions"
        )
    consumption_facts: list[C5G0GraphFact] = []
    consumption_operation_ids = tuple(
        _r(value["row"], "operation_id")
        for value in operation_values
        if value["value"].get("operation_kind") == "CONSUME_AUTHOR_DECISION"
    )
    if len(consumption_operation_ids) != 2:
        raise C5G0ActivationStateVerificationError("completed graph must contain two consume operations")
    approve_operation_ids = tuple(
        _r(value["row"], "operation_id")
        for value in operation_values
        if value["value"].get("operation_kind") == "APPROVE_CANON_CHANGESET"
    )
    if len(approve_operation_ids) != 1:
        raise C5G0ActivationStateVerificationError("completed graph must contain one approve operation")
    expected_consumption_operations = (consumption_operation_ids[0], consumption_operation_ids[1], approve_operation_ids[0])
    for expected, row, expected_operation_id in zip((2, 5, 7), consumption_rows, expected_consumption_operations):
        if (
            _r(row, "task_id") != task_id
            or _r(row, "decision_id") != _r(decision_values[len(consumption_facts)]["row"], "decision_id")
            or _r(row, "operation_id") != expected_operation_id
            or _r(row, "consumed_at_task_revision") != expected
        ):
            raise C5G0ActivationStateVerificationError(
                "decision consumption is not bound to its decision, operation, or revision"
            )
        consumption_facts.append(_fact("creation_decision_consumption", row))

    audit_rows = conn.execute(
        "SELECT * FROM creation_audit_event ORDER BY created_at, event_id"
    ).fetchall()
    expected_audits = (
        ("TASK_CREATED", 0, 0, "SYSTEM"),
        ("PLAN_PREPARED_FOR_APPROVAL", 0, 1, "AUTHOR"),
        ("TASK_TRANSITIONED", 1, 2, "AUTHOR"),
        ("AUTHORING_DRAFT_SUBMITTED", 2, 3, "AUTHOR"),
        ("DRAFT_REVIEW_SUBMITTED", 3, 4, "AUTHOR"),
        ("TASK_TRANSITIONED", 4, 5, "AUTHOR"),
        ("CANON_CHANGESET_PREPARED", 5, 6, "AUTHOR"),
        ("CANON_COMMIT_INTENT_CREATED", 6, 7, "AUTHOR"),
        ("CANON_APPLY_COMPLETED", 7, 8, "SYSTEM"),
    )
    if len(audit_rows) != len(expected_audits):
        raise C5G0ActivationStateVerificationError(
            "completed graph contains an extra or missing audit fact"
        )
    audit_facts: list[C5G0GraphFact] = []
    audit_operation_ids: list[str] = []
    for index, (row, expected) in enumerate(zip(audit_rows, expected_audits)):
        source_refs = _read_ordered_refs(conn, registry, "creation_audit_event_source_artifact_ref", _r(row, "event_id"))
        object_refs = _read_ordered_refs(conn, registry, "creation_audit_event_object_ref", _r(row, "event_id"))
        event_type, before, after, actor_kind = expected
        if (
            _r(row, "task_id") != task_id
            or _r(row, "project_id") != project_id
            or _r(row, "event_type") != event_type
            or _r(row, "before_task_revision") != before
            or _r(row, "after_task_revision") != after
            or _r(row, "actor_kind") != actor_kind
            or _r(row, "model_run_id") is not None
            or (actor_kind == "AUTHOR" and _r(row, "actor_id") != operator_identity)
            or (actor_kind == "SYSTEM" and _r(row, "actor_id") is not None)
            or source_refs
        ):
            raise C5G0ActivationStateVerificationError(
                "audit fact has the wrong project, actor, revision, or source refs"
            )
        expected_objects = _expected_audit_objects(index, task_refs)
        if object_refs != expected_objects:
            raise C5G0ActivationStateVerificationError(
                "audit object refs do not match the Task graph at that revision"
            )
        operation_id = _r(row, "operation_id")
        audit_operation_ids.append(operation_id)
        audit_facts.append(_fact("creation_audit_event", row, object_refs))

    journal_rows = conn.execute("SELECT * FROM canon_commit_journal").fetchall()
    if len(journal_rows) != 1:
        raise C5G0ActivationStateVerificationError("completed graph must contain one active C3 journal")
    journal = journal_rows[0]
    changeset_ref = _require_registered_ref(registry, _r(journal, "changeset_ref_artifact_id"))
    base_ref = _require_registered_ref(registry, _r(journal, "base_bundle_ref_artifact_id"))
    target_ref = _require_registered_ref(registry, _r(journal, "target_bundle_ref_artifact_id"))
    if (
        _r(journal, "task_id") != task_id
        or _r(journal, "operation_id") != approve_operation_ids[0]
        or _r(journal, "decision_id") != _r(decision_values[2]["row"], "decision_id")
        or _r(journal, "changeset_ref_artifact_id") != task_refs[6].artifact_id
        or base_ref != activation_ref
        or _r(journal, "base_bundle_content_hash") != base_ref.content_hash
        or _r(journal, "target_bundle_content_hash") != target_ref.content_hash
        or _r(journal, "base_manifest_hash") != activation_attempt.manifest_hash
        or _r(journal, "base_world_hash") != activation_attempt.world_hash
        or _r(journal, "canonical_bundle_schema_version") != target_ref.schema_version
    ):
        raise C5G0ActivationStateVerificationError("C3 journal identity is not closed")
    target_bundle = _read_bundle(payload_store, target_ref.content_hash)
    if (
        target_bundle.content_hash() != target_ref.content_hash
        or target_bundle.manifest_hash != _r(journal, "target_manifest_hash")
        or target_bundle.world_hash != _r(journal, "target_world_hash")
    ):
        raise C5G0ActivationStateVerificationError("C3 target bundle identity is not closed")
    journal_facts = (_fact("canon_commit_journal", journal, (changeset_ref, base_ref, target_ref)),)

    receipt_rows = conn.execute("SELECT * FROM canon_commit_receipt").fetchall()
    if len(receipt_rows) != 1:
        raise C5G0ActivationStateVerificationError("completed graph must contain one active C3 receipt")
    receipt = receipt_rows[0]
    receipt_ref = _require_registered_ref(registry, _r(receipt, "receipt_ref_artifact_id"))
    if (
        _r(receipt, "journal_id") != _r(journal, "journal_id")
        or receipt_ref != task_refs[7]
    ):
        raise C5G0ActivationStateVerificationError("receipt identity is not bound to Task/journal")
    receipt_facts = (_fact("canon_commit_receipt", receipt, (receipt_ref,)),)

    attempt_rows = conn.execute("SELECT * FROM canon_apply_attempt").fetchall()
    if len(attempt_rows) != 1:
        raise C5G0ActivationStateVerificationError("completed graph must contain one C4a apply attempt")
    apply_attempt = attempt_rows[0]
    apply_base_ref = _require_registered_ref(registry, _r(apply_attempt, "base_bundle_ref_artifact_id"))
    apply_target_ref = _require_registered_ref(registry, _r(apply_attempt, "target_bundle_ref_artifact_id"))
    if (
        _r(apply_attempt, "project_id") != project_id
        or _r(apply_attempt, "task_id") != task_id
        or _r(apply_attempt, "journal_id") != _r(journal, "journal_id")
        or _r(apply_attempt, "operation_id") != _r(journal, "operation_id")
        or _r(apply_attempt, "decision_id") != _r(journal, "decision_id")
        or apply_base_ref != base_ref
        or apply_target_ref != target_ref
        or _r(apply_attempt, "base_bundle_content_hash") != base_ref.content_hash
        or _r(apply_attempt, "target_bundle_content_hash") != target_ref.content_hash
        or _r(apply_attempt, "base_version_id") != activation_attempt.version_id
        or _r(apply_attempt, "base_pointer_content_hash") != activation_attempt.pointer_content_hash
        or _r(apply_attempt, "target_manifest_hash") != target_bundle.manifest_hash
        or _r(apply_attempt, "target_world_hash") != target_bundle.world_hash
        or _r(apply_attempt, "operator_identity") != operator_identity
        or _r(apply_attempt, "request_digest") is None
        or activation_attempt.bundle_ref != base_ref
    ):
        raise C5G0ActivationStateVerificationError("C4a apply attempt identity is not closed")
    _require_digest(_r(apply_attempt, "request_digest"), "c4a.request_digest")
    target_pointer = _sha256(_read_regular_file(projection_dir / "current.pointer", "current.pointer"))
    target_marker = _sha256(_read_regular_file(projection_dir / "activation.marker", "activation.marker"))
    if (
        _r(apply_attempt, "target_pointer_content_hash") != target_pointer
        or _r(apply_attempt, "target_marker_content_hash") != target_marker
        or activation_attempt.bundle_ref != base_ref
    ):
        raise C5G0ActivationStateVerificationError("C4a target projection identity is not closed")
    if (
        activation_identity.version_id != _r(apply_attempt, "target_version_id")
        or activation_identity.bundle_ref_artifact_id != target_ref.artifact_id
        or activation_identity.bundle_schema_version != target_ref.schema_version
        or activation_identity.bundle_content_hash != target_ref.content_hash
        or activation_identity.manifest_hash != target_bundle.manifest_hash
        or activation_identity.world_hash != target_bundle.world_hash
    ):
        raise C5G0ActivationStateVerificationError("activation reader is not bound to C4a target")
    apply_attempt_facts = (_fact("canon_apply_attempt", apply_attempt, (apply_base_ref, apply_target_ref)),)

    expected_phases = (
        "PREPARED", "VERSION_READY", "POINTER_WRITE_INTENDED", "POINTER_INSTALLED",
        "MARKER_WRITE_INTENDED", "PROJECTION_COMMITTED", "RECEIPT_PAYLOAD_READY", "COMPLETED",
    )
    apply_event_candidates = conn.execute("SELECT * FROM canon_apply_event").fetchall()
    by_phase = {_r(row, "phase"): row for row in apply_event_candidates}
    if (
        len(apply_event_candidates) != len(expected_phases)
        or len(by_phase) != len(expected_phases)
        or set(by_phase) != set(expected_phases)
    ):
        raise C5G0ActivationStateVerificationError(
            "C4a events are not the complete ordered phase chain"
        )
    apply_event_rows = tuple(by_phase[phase] for phase in expected_phases)
    apply_event_facts: list[C5G0GraphFact] = []
    for row, phase in zip(apply_event_rows, expected_phases):
        if (
            _r(row, "apply_attempt_id") != _r(apply_attempt, "apply_attempt_id")
            or _r(row, "project_id") != project_id
            or _r(row, "result") != phase
            or _r(row, "error_code") is not None
            or _r(row, "recovery_failed_operation_id") is not None
        ):
            raise C5G0ActivationStateVerificationError("C4a event is cross-bound or recovering")
        if phase in expected_phases[:5]:
            if any(_r(row, key) is not None for key in (
                "replay_envelope_json", "replay_envelope_hash", "receipt_payload_ref_artifact_id",
                "receipt_payload_schema_version", "receipt_payload_content_hash",
                "observed_pointer_content_hash", "observed_marker_content_hash",
            )):
                raise C5G0ActivationStateVerificationError("early C4a event carries premature durable evidence")
            apply_event_facts.append(_fact("canon_apply_event", row))
            continue
        elif _r(row, "observed_pointer_content_hash") != target_pointer or _r(row, "observed_marker_content_hash") != target_marker:
            raise C5G0ActivationStateVerificationError("C4a observation does not match target projection")
        if phase == "PROJECTION_COMMITTED":
            if _r(row, "replay_envelope_json") is not None or _r(row, "receipt_payload_ref_artifact_id") is not None:
                raise C5G0ActivationStateVerificationError("projection event carries receipt evidence too early")
        else:
            envelope = _verify_durable_envelope(_r(row, "replay_envelope_json"), _r(row, "replay_envelope_hash"))
            try:
                value = json.loads(envelope)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise C5G0ActivationStateVerificationError("C4a completion envelope is invalid") from exc
            expected_envelope = {
                "apply": "C4A_CANON_COMPLETION",
                "apply_attempt_id": _r(apply_attempt, "apply_attempt_id"),
                "apply_key": _r(apply_attempt, "apply_key"),
                "bundle_content_hash": target_ref.content_hash,
                "bundle_ref_artifact_id": target_ref.artifact_id,
                "journal_id": _r(apply_attempt, "journal_id"),
                "operation_id": _r(apply_attempt, "operation_id"),
                "project_id": project_id,
                "target_marker_content_hash": target_marker,
                "target_pointer_content_hash": target_pointer,
                "task_id": task_id,
                "version_id": _r(apply_attempt, "target_version_id"),
            }
            if value != expected_envelope:
                raise C5G0ActivationStateVerificationError("C4a envelope identity mismatch")
            event_ref = _require_registered_ref(registry, _r(row, "receipt_payload_ref_artifact_id"))
            if event_ref != receipt_ref or _r(row, "receipt_payload_schema_version") != receipt_ref.schema_version or _r(row, "receipt_payload_content_hash") != receipt_ref.content_hash:
                raise C5G0ActivationStateVerificationError("C4a receipt payload ref is not the target receipt")
            if _read_payload(payload_store, receipt_ref.content_hash) != envelope.encode("utf-8"):
                raise C5G0ActivationStateVerificationError("C4a receipt payload readback mismatch")
            apply_event_facts.append(_fact("canon_apply_event", row, (event_ref,), envelope, _r(row, "replay_envelope_hash")))
            continue
        apply_event_facts.append(_fact("canon_apply_event", row))

    _verify_operation_envelope_semantics(
        operation_values=tuple(operation_values),
        task_id=task_id,
        task_refs=task_refs,
        decision_values=tuple(decision_values),
        audit_rows=tuple(audit_rows),
        journal=journal,
        target_ref=target_ref,
    )

    expected_artifact_ids = {
        ref.artifact_id for ref in task_refs + (activation_ref, changeset_ref, base_ref, target_ref, receipt_ref)
    }
    if set(registry) != expected_artifact_ids:
        raise C5G0ActivationStateVerificationError(
            "ArtifactRef registry contains an extra or missing graph identity"
        )

    referenced_operation_ids = set(audit_operation_ids)
    referenced_operation_ids.update(_r(row, "operation_id") for row in consumption_rows)
    referenced_operation_ids.add(_r(journal, "operation_id"))
    referenced_operation_ids.add(_r(apply_attempt, "operation_id"))
    for value in operation_values:
        envelope_value = value["value"]
        decision_id = envelope_value.get("decision_id")
        if decision_id is not None:
            if decision_id not in {_r(item["row"], "decision_id") for item in decision_values}:
                raise C5G0ActivationStateVerificationError("operation envelope names an unknown decision")
            referenced_operation_ids.add(_r(value["row"], "operation_id"))
    if { _r(value["row"], "operation_id") for value in operation_values } != referenced_operation_ids:
        raise C5G0ActivationStateVerificationError("operation graph contains an unreferenced or missing operation")

    task_fact = _fact("chapter_task", task, task_refs)
    artifact_facts = tuple(_fact("creation_artifact_ref", row) for row in artifact_rows)
    return {
        "task": task,
        "envelopes": tuple(envelopes),
        "payload_hashes": tuple(ref.content_hash for ref in registry.values()),
        "c4a_phases": tuple(expected_phases),
        "task_facts": (task_fact,),
        "artifact_facts": artifact_facts,
        "operation_facts": tuple(operation_facts),
        "decision_facts": tuple(decision_facts),
        "consumption_facts": tuple(consumption_facts),
        "audit_facts": tuple(audit_facts),
        "journal_facts": journal_facts,
        "receipt_facts": receipt_facts,
        "apply_attempt_facts": apply_attempt_facts,
        "apply_event_facts": tuple(apply_event_facts),
    }


def _r(row: object, key: str) -> object:
    try:
        return row[key]  # type: ignore[index]
    except (KeyError, IndexError, TypeError) as exc:
        raise C5G0ActivationStateVerificationError(f"graph row is missing {key}") from exc


def _read_operation_rows(conn: sqlite3.Connection) -> tuple[object, ...]:
    """Read the operation ledger through the verifier-owned SQL boundary."""

    return tuple(
        conn.execute(
            "SELECT * FROM creation_operation ORDER BY created_at, operation_id"
        ).fetchall()
    )


def _verify_operation_envelope_semantics(
    *,
    operation_values: tuple[dict[str, object], ...],
    task_id: str,
    task_refs: tuple[ArtifactRef, ...],
    decision_values: tuple[dict[str, object], ...],
    audit_rows: tuple[object, ...],
    journal: object,
    target_ref: ArtifactRef,
) -> None:
    """Bind every creation-operation envelope to the durable graph position."""

    expected_kinds = (
        OperationKind.CREATE_CHAPTER_TASK,
        OperationKind.PREPARE_PLAN_FOR_APPROVAL,
        OperationKind.CREATE_AUTHOR_DECISION,
        OperationKind.CONSUME_AUTHOR_DECISION,
        OperationKind.SUBMIT_AUTHORING_ARTIFACT,
        OperationKind.SUBMIT_DRAFT_FOR_REVIEW,
        OperationKind.CREATE_AUTHOR_DECISION,
        OperationKind.CONSUME_AUTHOR_DECISION,
        OperationKind.PREPARE_CANON_CHANGESET,
        OperationKind.CREATE_AUTHOR_DECISION,
        OperationKind.APPROVE_CANON_CHANGESET,
    )
    if len(operation_values) != len(expected_kinds) or len(audit_rows) != 9:
        raise C5G0ActivationStateVerificationError(
            "operation envelope semantic graph is incomplete"
        )

    exact_fields = {
        OperationKind.CREATE_CHAPTER_TASK: {
            "result_schema_version", "outcome", "task_id", "task_revision",
            "task_status", "audit_event_ids", "original_operation_id", "operation_kind",
        },
        OperationKind.PREPARE_PLAN_FOR_APPROVAL: {
            "audit_event_ids", "operation_id", "operation_kind", "outcome", "plan_ref",
            "result_schema_version", "status", "task_id", "task_revision",
        },
        OperationKind.CREATE_AUTHOR_DECISION: {
            "result_schema_version", "outcome", "decision_id", "task_id",
            "original_operation_id", "operation_kind",
        },
        OperationKind.CONSUME_AUTHOR_DECISION: {
            "result_schema_version", "outcome", "task_id", "task_revision",
            "task_status", "audit_event_ids", "original_operation_id", "operation_kind",
        },
        OperationKind.SUBMIT_AUTHORING_ARTIFACT: {
            "result_schema_version", "outcome", "artifact_kind", "artifact_ref", "task_id",
            "task_revision", "task_status", "audit_event_ids", "original_operation_id",
            "operation_kind",
        },
        OperationKind.SUBMIT_DRAFT_FOR_REVIEW: {
            "result_schema_version", "outcome", "artifact_kind", "artifact_ref", "task_id",
            "task_revision", "task_status", "audit_event_ids", "original_operation_id",
            "operation_kind",
        },
        OperationKind.PREPARE_CANON_CHANGESET: {
            "result_schema_version", "outcome", "task_id", "task_revision", "task_status",
            "changeset_ref", "target_bundle_ref", "base_manifest_hash", "target_manifest_hash",
            "journal_id", "audit_event_ids", "original_operation_id", "operation_kind",
        },
        OperationKind.APPROVE_CANON_CHANGESET: {
            "result_schema_version", "outcome", "task_id", "task_revision", "task_status",
            "changeset_ref", "target_bundle_ref", "base_manifest_hash", "target_manifest_hash",
            "journal_id", "audit_event_ids", "original_operation_id", "operation_kind",
        },
    }
    audit_by_position = {0: 0, 1: 1, 3: 2, 4: 3, 5: 4, 7: 5, 8: 6, 10: 7}
    expected_statuses = {
        0: (0, "PLAN_PREPARING"),
        1: (1, "PLAN_APPROVAL_PENDING"),
        3: (2, "DRAFTING"),
        4: (3, "REVIEWING"),
        5: (4, "DRAFT_APPROVAL_PENDING"),
        7: (5, "CHANGESET_PREPARING"),
        8: (6, "CHANGESET_APPROVAL_PENDING"),
        10: (7, "COMMITTING"),
    }

    for position, (entry, expected_kind) in enumerate(zip(operation_values, expected_kinds)):
        row = entry["row"]
        value = entry["value"]
        envelope = _r(row, "result_envelope_json")
        if not isinstance(envelope, str) or set(value) != exact_fields[expected_kind]:
            raise C5G0ActivationStateVerificationError(
                "operation envelope fields are not exact for its graph position"
            )
        if value["operation_kind"] != expected_kind.value:
            raise C5G0ActivationStateVerificationError(
                "operation row and envelope kind are not bound to their graph position"
            )
        try:
            if position == 0:
                result = result_from_envelope(envelope, expected_task_id=task_id)
            elif position == 1:
                result = _result_from_plan_envelope(envelope, task_id)
            elif position in (2, 6, 9):
                result = result_from_decision_creation_envelope(
                    envelope,
                    expected_decision_id=_r(
                        decision_values[{2: 0, 6: 1, 9: 2}[position]]["row"],
                        "decision_id",
                    ),
                )
            elif position in (3, 7):
                result = result_from_decision_consumption_envelope(
                    envelope, expected_task_id=task_id
                )
            elif position == 4:
                result = result_from_authoring_submission_envelope(
                    envelope,
                    expected_task_id=task_id,
                    expected_kind=OperationKind.SUBMIT_AUTHORING_ARTIFACT,
                )
            elif position == 5:
                result = result_from_authoring_submission_envelope(
                    envelope,
                    expected_task_id=task_id,
                    expected_kind=OperationKind.SUBMIT_DRAFT_FOR_REVIEW,
                )
            else:
                result = result_from_canon_envelope(
                    envelope, expected_task_id=task_id, expected_kind=expected_kind
                )
        except Exception as exc:
            raise C5G0ActivationStateVerificationError(
                "operation envelope cannot be reconstructed by its typed parser"
            ) from exc

        if position in expected_statuses:
            expected_revision, expected_status = expected_statuses[position]
            result_status = getattr(result.status, "value", result.status)
            if result.aggregate_revision != expected_revision or result_status != expected_status:
                raise C5G0ActivationStateVerificationError(
                    "operation envelope revision or status is not the durable Task fact"
                )
        if getattr(result, "task_id", task_id) != task_id:
            raise C5G0ActivationStateVerificationError("operation envelope Task identity mismatch")

        if position == 1 and result.plan_ref != task_refs[1]:
            raise C5G0ActivationStateVerificationError("PLAN envelope ref is not the confirmed plan")
        if position in (4, 5):
            expected_ref = task_refs[2] if position == 4 else task_refs[5]
            if result.artifact_ref != expected_ref:
                raise C5G0ActivationStateVerificationError("authoring envelope ref is not the Task role ref")
        if position in (8, 10):
            if (
                result.changeset_ref != task_refs[6]
                or result.target_bundle_ref != target_ref
                or result.base_manifest_hash != _r(journal, "base_manifest_hash")
                or result.target_manifest_hash != _r(journal, "target_manifest_hash")
                or result.journal_id != (_r(journal, "journal_id") if position == 10 else None)
            ):
                raise C5G0ActivationStateVerificationError(
                    "Canon envelope identity is not bound to the durable journal"
                )

        if position in audit_by_position:
            expected_audit_ids = [_r(audit_rows[audit_by_position[position]], "event_id")]
            if value.get("audit_event_ids") != expected_audit_ids:
                raise C5G0ActivationStateVerificationError(
                    "operation envelope audit ids do not match Audit rows"
                )


def _result_from_plan_envelope(envelope: str, expected_task_id: str):
    """Reconstruct the PLAN result without depending on an application private helper."""

    try:
        payload = json.loads(envelope, parse_constant=_reject_json_constant)
        expected_fields = {
            "audit_event_ids", "operation_id", "operation_kind", "outcome", "plan_ref",
            "result_schema_version", "status", "task_id", "task_revision",
        }
        if (
            not isinstance(payload, dict)
            or set(payload) != expected_fields
            or _canonical_json(payload) != envelope
            or payload["operation_kind"] != OperationKind.PREPARE_PLAN_FOR_APPROVAL.value
            or payload["outcome"] != "PLAN_PREPARED"
            or payload["task_id"] != expected_task_id
            or payload["status"] != "PLAN_APPROVAL_PENDING"
            or payload["result_schema_version"] != 1
            or type(payload["task_revision"]) is not int
            or not isinstance(payload["operation_id"], str)
            or not payload["operation_id"]
        ):
            raise ValueError("invalid PLAN result envelope")
        audit_ids = payload["audit_event_ids"]
        if not isinstance(audit_ids, list) or not audit_ids or any(
            type(item) is not str or not item for item in audit_ids
        ):
            raise ValueError("invalid PLAN audit ids")
        ref = _artifact_from_envelope(payload["plan_ref"])
        return _PlanEnvelopeResult(
            plan_ref=ref,
            task_id=payload["task_id"],
            aggregate_revision=payload["task_revision"],
            status="PLAN_APPROVAL_PENDING",
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise C5G0ActivationStateVerificationError("invalid stored PLAN result envelope") from exc


@dataclass(frozen=True, slots=True)
class _PlanEnvelopeResult:
    plan_ref: ArtifactRef
    task_id: str
    aggregate_revision: int
    status: str


def _canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"unsupported JSON constant: {value}")


def _artifact_from_envelope(value: object) -> ArtifactRef:
    if not isinstance(value, dict) or set(value) != {"artifact_id", "schema_version", "content_hash"}:
        raise ValueError("invalid ArtifactRef envelope")
    return _artifact_from_values(
        value["artifact_id"], value["schema_version"], value["content_hash"]
    )


def _artifact_from_values(artifact_id: object, schema_version: object, content_hash: object) -> ArtifactRef:
    try:
        return ArtifactRef(artifact_id, schema_version, content_hash)  # type: ignore[arg-type]
    except Exception as exc:
        raise C5G0ActivationStateVerificationError("ArtifactRef identity is invalid") from exc


def _require_registered_ref(registry: dict[str, ArtifactRef], artifact_id: object) -> ArtifactRef:
    if not isinstance(artifact_id, str) or artifact_id not in registry:
        raise C5G0ActivationStateVerificationError("graph references an unregistered ArtifactRef")
    return registry[artifact_id]


def _read_ordered_refs(conn, registry, table: str, event_id: object) -> tuple[ArtifactRef, ...]:
    rows = conn.execute(
        f"SELECT ordinal, artifact_id FROM {table} WHERE event_id = ? ORDER BY ordinal",
        (event_id,),
    ).fetchall()
    if tuple(_r(row, "ordinal") for row in rows) != tuple(range(len(rows))):
        raise C5G0ActivationStateVerificationError("audit ArtifactRef ordinals are not contiguous")
    return tuple(_require_registered_ref(registry, _r(row, "artifact_id")) for row in rows)


def _expected_audit_objects(index: int, refs: tuple[ArtifactRef, ...]) -> tuple[ArtifactRef, ...]:
    if index == 0:
        return refs[0:1]
    if index == 1:
        # PLAN preparation has not yet registered/confirmed the PLAN ref;
        # the existing CONFIRM_PLAN decision boundary owns that registration.
        return refs[0:1]
    if index == 2:
        return refs[0:2]
    if index == 3:
        return (refs[0], refs[1], refs[2], refs[2])
    if index == 4:
        return (refs[0], refs[1], refs[2], refs[3], refs[5])
    if index == 5:
        return (refs[0], refs[1], refs[2], refs[3], refs[4], refs[5])
    if index in (6, 7):
        return refs[0:7]
    return ()


def _read_bundle(store: object, content_hash: str) -> CanonicalBundle:
    try:
        return CanonicalBundle.from_bytes(_read_payload(store, content_hash))
    except Exception as exc:
        raise C5G0ActivationStateVerificationError("canonical bundle payload is invalid") from exc


def _fact(
    fact_type: str,
    row: object,
    artifact_refs: tuple[ArtifactRef, ...] = (),
    envelope_json: str | None = None,
    envelope_hash: str | None = None,
) -> C5G0GraphFact:
    keys = tuple(row.keys())  # type: ignore[union-attr]
    return C5G0GraphFact(
        fact_type=fact_type,
        identity=tuple((key, _r(row, key)) for key in keys),
        artifact_refs=artifact_refs,
        envelope_json=envelope_json,
        envelope_hash=envelope_hash,
    )


def _verify_completed_graph_snapshot(snapshot: C5G0CompletedGraphSnapshot) -> None:
    if (
        snapshot.graph_state != "COMPLETED"
        or snapshot.task_status != "COMPLETED"
        or snapshot.last_stable_status != "COMPLETED"
        or snapshot.recovery_error_code is not None
        or snapshot.lock_observed
        or snapshot.sqlite_write_count != 0
        or snapshot.payload_put_count != 0
        or snapshot.c4a_recovery_event_count != 0
        or snapshot.c4a_unknown_event_count != 0
        or not snapshot.projection_identity_bound
        or snapshot.operation_count != len(snapshot.durable_envelopes)
        or snapshot.operation_count < 1
        or not snapshot.durable_envelopes
        or snapshot.audit_count < 1
        or snapshot.decision_count < 1
        or snapshot.consumption_count < 1
        or snapshot.c3_journal_count < 1
        or snapshot.c4a_attempt_count != 1
        or snapshot.c4a_event_count < 1
        or snapshot.c4a_completed_event_count != 1
        or snapshot.receipt_count != 1
        or not snapshot.payload_content_hashes
        or not snapshot.activation_attempt_id
        or not snapshot.activation_replay_envelope_json
    ):
        raise C5G0ActivationStateVerificationError(
            "completed graph is partial, conflicting, recovering, or unknown"
        )
    for envelope in snapshot.durable_envelopes:
        _verify_durable_envelope(envelope, _sha256(envelope.encode("utf-8")))


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def _count_where(conn: sqlite3.Connection, table: str, predicate: str) -> int:
    return int(conn.execute(f'SELECT COUNT(*) FROM "{table}" WHERE {predicate}').fetchone()[0])


def _read_completed_task(conn: sqlite3.Connection, task_id: str, project_id: str):
    rows = conn.execute(
        "SELECT * FROM chapter_task WHERE task_id = ? AND project_id = ?",
        (task_id, project_id),
    ).fetchall()
    if len(rows) != 1:
        raise C5G0ActivationStateVerificationError(
            "completed graph must contain exactly one task bound to the request"
        )
    return rows[0]


def _discover_migrations() -> tuple[tuple[int, str, str], ...]:
    migration_dir = Path(__file__).resolve().parent / "migrations"
    discovered: list[tuple[int, str, str]] = []
    for child in sorted(migration_dir.iterdir()):
        match = _MIGRATION_FILE.fullmatch(child.name)
        if child.is_file() and match is not None:
            discovered.append((
                int(match.group(1)),
                child.name,
                hashlib.sha256(child.read_bytes()).hexdigest(),
            ))
    return tuple(sorted(discovered, key=lambda item: item[0]))


def _verify_migration_ledger(conn: sqlite3.Connection) -> tuple[tuple[int, str, str], ...]:
    migrations = _discover_migrations()
    if tuple(item[0] for item in migrations) != _EXPECTED_MIGRATION_VERSIONS:
        raise C5G0ActivationStateVerificationError(
            "migration files are not exactly v001 through v006"
        )
    if conn.execute("PRAGMA user_version").fetchone()[0] != 6:
        raise C5G0ActivationStateVerificationError("SQLite user_version is not v006")
    try:
        rows = conn.execute(
            "SELECT version, file_name, sha256 FROM creation_schema_migration ORDER BY version"
        ).fetchall()
    except sqlite3.Error as exc:
        raise C5G0ActivationStateVerificationError(
            "migration ledger cannot be read"
        ) from exc
    if len(rows) != len(migrations):
        raise C5G0ActivationStateVerificationError(
            "migration ledger is partial or duplicated"
        )
    if any(tuple(row) != expected for row, expected in zip(rows, migrations)):
        raise C5G0ActivationStateVerificationError(
            "migration ledger identity mismatch"
        )
    return tuple(tuple(row) for row in rows)


def _require_identifier(value: object, field: str) -> None:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise C5G0ActivationStateVerificationError(f"{field} is invalid")


def _require_digest(value: object, field: str) -> None:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise C5G0ActivationStateVerificationError(f"{field} is not a sha256 digest")


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()
