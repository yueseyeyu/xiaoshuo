"""C4a controlled Apply composition root.

This module is the only C4a path that may coordinate a trusted v2 Intent,
the independent projection lease, the follow-on writer, and v006 facts.  The
application layer receives this module only through its port protocol.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
import uuid

from xiaoshuo import PROJECT_ROOT
from xiaoshuo.application.creation.canon_apply import (
    CanonApplyCommand,
    compute_canon_apply_request_digest,
)
from xiaoshuo.application.creation.canon_apply_context import CanonApplyDeliveryContext
from xiaoshuo.application.creation.canon_results import CanonApplyResult
from xiaoshuo.application.creation.errors import (
    CanonApplyCommittedLeaseReleaseUncertain,
    CanonApplyConflict,
    CanonApplyInputRejected,
    CanonApplyRecoveryRequired,
    IdempotencyConflict,
    RevisionConflict,
)
from xiaoshuo.domain.creation import ArtifactRef, ChapterTaskStatus
from xiaoshuo.infra.config_manager import get_config

from .canonical_bundle import CanonicalBundle, CanonicalBundleError
from .c4a_projection_commit_lock import (
    C4aProjectionCommitLock,
    C4aProjectionLockConflict,
    C4aProjectionLockError,
)
from .c4a_projection_writer import (
    C4aProjectionIdentity,
    C4aProjectionWriter,
    C4aProjectionWriterError,
)
from .immutable_payload_store import ImmutablePayloadStore, PayloadStoreError
from .projection_activation import ProjectionActivationError, ProjectionActivationReader
from xiaoshuo.infrastructure.persistence.sqlite.c4a_apply_repository import (
    C4aApplyAttempt,
    C4aApplyEvent,
    C4aApplyRepositoryError,
    SqliteC4aApplyRepository,
)


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise CanonApplyInputRejected(f"{field} is required")
    return value


def _valid_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(char in "0123456789abcdef" for char in value[7:])
    )


def _configured_projection_root() -> Path:
    try:
        value = get_config()["canon_mvp"]["projection_dir"]
    except (KeyError, TypeError) as exc:
        raise CanonApplyInputRejected("canon_mvp.projection_dir is required") from exc
    if not isinstance(value, str) or not value.strip():
        raise CanonApplyInputRejected("canon_mvp.projection_dir is required")
    return Path(value)


def _configured_operator_identity() -> str:
    try:
        value = get_config()["canon_mvp"]["local_operator_id"]
    except (KeyError, TypeError) as exc:
        raise CanonApplyInputRejected("canon_mvp.local_operator_id is required") from exc
    if not isinstance(value, str) or not value.strip():
        raise CanonApplyInputRejected("canon_mvp.local_operator_id is required")
    return value


def _stable_recovery_error_code(cause: Exception) -> str:
    if isinstance(cause, C4aProjectionLockConflict):
        return "C4A_LOCK_CONFLICT"
    if isinstance(cause, C4aProjectionLockError):
        return "C4A_LOCK_FAILURE"
    if isinstance(cause, C4aProjectionWriterError):
        return "C4A_PROJECTION_WRITE_FAILURE"
    if isinstance(cause, PayloadStoreError):
        return "C4A_PAYLOAD_FAILURE"
    if isinstance(cause, ProjectionActivationError):
        return "C4A_PROJECTION_READ_FAILURE"
    if isinstance(cause, RevisionConflict):
        return "C4A_REVISION_CONFLICT"
    if isinstance(cause, CanonApplyConflict):
        return "C4A_APPLY_CONFLICT"
    return "C4A_APPLY_FAILURE"


class C4aApplyService:
    """Execute one trusted C4a Apply or a fully verified read-only replay."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        operator_identity: str,
        projection_root: Path | str | None = None,
        payload_store: object | None = None,
        repository: SqliteC4aApplyRepository | None = None,
        activation_reader: object | None = None,
        projection_reader: object | None = None,
        lock_factory: Callable[..., object] | None = None,
        writer_factory: Callable[..., object] | None = None,
        id_factory: Callable[[], object] | None = None,
        clock: Callable[[], str] | None = None,
        workspace_root: Path | str | None = None,
        enforce_persistent_d_drive: bool = True,
        composition_owned: bool = False,
    ) -> None:
        if not isinstance(connection, sqlite3.Connection):
            raise CanonApplyInputRejected("an open SQLite connection is required")
        self.connection = connection
        self.enforce_persistent_d_drive = enforce_persistent_d_drive
        self.operator_identity = _required_text(operator_identity, "operator_identity")
        if enforce_persistent_d_drive and not composition_owned and any(
            value is not None
            for value in (
                projection_root,
                payload_store,
                repository,
                activation_reader,
                projection_reader,
                lock_factory,
                writer_factory,
            )
        ):
            raise CanonApplyInputRejected(
                "production C4a adapters are composition-root owned"
            )
        if enforce_persistent_d_drive and self.operator_identity != _configured_operator_identity():
            raise CanonApplyInputRejected("operator_identity must be config-bound local-author")
        configured_projection = _configured_projection_root()
        self.projection_root = Path(projection_root) if projection_root is not None else configured_projection
        if enforce_persistent_d_drive and self.projection_root.resolve() != configured_projection.resolve():
            raise CanonApplyInputRejected("projection root must come from config.yaml")
        self.repository = repository or SqliteC4aApplyRepository(connection)
        if payload_store is None:
            self.payload_store = ImmutablePayloadStore()
        else:
            self.payload_store = payload_store
        if not callable(getattr(self.payload_store, "put", None)) or not callable(
            getattr(self.payload_store, "read", None)
        ):
            raise CanonApplyInputRejected("an immutable payload store is required")
        reader = activation_reader or projection_reader
        if reader is None and enforce_persistent_d_drive:
            reader = ProjectionActivationReader(
                self.projection_root,
                artifact_ref_resolver=self.repository.resolve_artifact_ref,
            )
        if reader is None or not callable(getattr(reader, "read_for_project", None)):
            raise CanonApplyInputRejected("an activation reader is required")
        self.activation_reader = reader
        self.lock_factory = lock_factory or C4aProjectionCommitLock
        self.writer_factory = writer_factory or C4aProjectionWriter
        self.id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self.clock = clock or (lambda: datetime.now(timezone.utc).isoformat())
        self.workspace_root = Path(workspace_root) if workspace_root is not None else PROJECT_ROOT

    def apply(
        self, command: CanonApplyCommand, context: CanonApplyDeliveryContext
    ) -> CanonApplyResult:
        command, context, apply_key, request_digest = self._validate_delivery(command, context)

        # This is intentionally the first business read.  A replay/conflict
        # must not inspect Task, journal, payload, reader, lock, or paths.
        try:
            existing = self.repository.get_attempt_by_key(apply_key)
        except Exception as exc:
            raise CanonApplyRecoveryRequired("C4a delivery ledger cannot be read safely") from exc
        if existing is not None:
            if existing.request_digest != request_digest:
                raise IdempotencyConflict("C4a apply_key was reused with a different digest")
            return self._replay_or_recover(existing, command, request_digest)

        journal = self.repository.get_journal(command.journal_id)
        if journal is None:
            raise CanonApplyInputRejected("C4a requires a persisted active v2 journal")
        if journal.base_bundle_ref is None or journal.base_bundle_content_hash is None:
            raise CanonApplyInputRejected("C4a rejects legacy or incomplete journal identity")
        if (
            journal.target_bundle_ref is None
            or journal.base_bundle_ref.schema_version != 1
            or journal.target_bundle_ref.schema_version != 1
            or any(
                not _valid_digest(value)
                for value in (
                    journal.base_bundle_content_hash,
                    journal.target_bundle_content_hash,
                    journal.base_manifest_hash,
                    journal.base_world_hash,
                    journal.target_manifest_hash,
                    journal.target_world_hash,
                )
            )
            or journal.base_bundle_ref.content_hash != journal.base_bundle_content_hash
            or journal.target_bundle_ref.content_hash != journal.target_bundle_content_hash
        ):
            raise CanonApplyInputRejected("C4a journal identity is incomplete")
        if journal.task_id != command.task_id:
            raise CanonApplyInputRejected("C4a task and journal binding mismatch")
        task = self.repository.get_task_state(command.task_id)
        if task is None or task["status"] != ChapterTaskStatus.COMMITTING.value:
            raise CanonApplyInputRejected("C4a Apply requires a COMMITTING Task")
        if task["project_id"] != journal_project(journal, self.repository):
            raise CanonApplyInputRejected("C4a Task and journal project binding mismatch")
        if task["aggregate_revision"] != command.expected_revision:
            raise RevisionConflict("C4a Apply revision is stale")

        current_identity = self._read_identity(task["project_id"])
        self._validate_current_base(current_identity, journal)
        target_bundle = self._read_target_bundle(journal)
        target_identity = self._target_identity(journal, target_bundle)
        pointer_bytes = self.writer_factory.pointer_bytes(target_identity) if hasattr(self.writer_factory, "pointer_bytes") else C4aProjectionWriter.pointer_bytes(target_identity)
        pointer_hash = _digest(pointer_bytes)
        marker_bytes = C4aProjectionWriter.marker_bytes(target_identity, pointer_bytes)

        lock = self._new_lock()
        try:
            lock.acquire()
        except C4aProjectionLockConflict as exc:
            raise CanonApplyConflict("C4a projection lease is occupied") from exc
        except C4aProjectionLockError as exc:
            raise CanonApplyRecoveryRequired("C4a projection lease cannot be acquired") from exc

        attempt: C4aApplyAttempt | None = None
        completed = False
        envelope: str | None = None
        receipt_ref: ArtifactRef | None = None
        try:
            # Re-read the trusted base after obtaining the lease.  It remains
            # read-only and closes the race between initial read and Tx A.
            self._validate_current_base(self._read_identity(task["project_id"]), journal)
            attempt = C4aApplyAttempt(
                apply_attempt_id=_required_text(str(self.id_factory()), "apply_attempt_id"),
                project_id=task["project_id"], apply_key=apply_key,
                request_digest=request_digest, journal_id=journal.journal_id,
                task_id=journal.task_id, operation_id=journal.operation_id,
                decision_id=journal.decision_id, base_bundle_ref=journal.base_bundle_ref,
                base_version_id=current_identity.version_id,
                base_pointer_content_hash=self._current_pointer_hash(),
                target_bundle_ref=journal.target_bundle_ref,
                target_version_id=target_identity.version_id,
                target_pointer_content_hash=pointer_hash,
                target_marker_content_hash=_digest(marker_bytes),
                target_manifest_hash=target_identity.manifest_hash,
                target_world_hash=target_identity.world_hash,
                operator_identity=self.operator_identity, created_at=self.clock(),
            )
            prepared = self._event(attempt, "PREPARED", attempt.created_at)
            self.repository.create_prepared(attempt, prepared)
            self.connection.commit()

            writer = self.writer_factory(self.projection_root, lock)
            writer.write_version(target_bundle, target_identity)
            self._append_event_commit(self._event(attempt, "VERSION_READY", self.clock()))
            self._append_event_commit(self._event(attempt, "POINTER_WRITE_INTENDED", self.clock()))
            pointer_readback = writer.write_pointer(target_identity)
            if pointer_readback != pointer_bytes:
                raise C4aProjectionWriterError("C4a pointer readback identity mismatch")
            self._append_event_commit(self._event(attempt, "POINTER_INSTALLED", self.clock()))
            self._append_event_commit(self._event(attempt, "MARKER_WRITE_INTENDED", self.clock()))
            marker_readback = writer.write_marker(target_identity)
            if marker_readback != marker_bytes:
                raise C4aProjectionWriterError("C4a marker readback identity mismatch")
            observed_pointer_hash, observed_marker_hash = self._verify_projection_observation(
                attempt, target_identity
            )
            self._append_event_commit(
                self._event(
                    attempt,
                    "PROJECTION_COMMITTED",
                    self.clock(),
                    observed_pointer_content_hash=observed_pointer_hash,
                    observed_marker_content_hash=observed_marker_hash,
                )
            )

            envelope = self._completion_envelope(attempt, target_identity)
            receipt_bytes = envelope.encode("utf-8")
            receipt_digest = self.payload_store.put(receipt_bytes)
            if receipt_digest != _digest(receipt_bytes) or self.payload_store.read(receipt_digest) != receipt_bytes:
                raise CanonApplyRecoveryRequired("C4a receipt payload readback failed")
            receipt_ref = ArtifactRef(
                artifact_id="c4a-receipt-payload-" + receipt_digest.removeprefix("sha256:"),
                schema_version=1,
                content_hash=receipt_digest,
            )
            self.repository.register_artifact_ref(receipt_ref)
            self._append_event_commit(
                self._event(
                    attempt,
                    "RECEIPT_PAYLOAD_READY",
                    self.clock(),
                    envelope=envelope,
                    receipt_ref=receipt_ref,
                    observed_pointer_content_hash=observed_pointer_hash,
                    observed_marker_content_hash=observed_marker_hash,
                )
            )
            new_revision = self.repository.complete(
                attempt,
                expected_revision=command.expected_revision,
                receipt_id="c4a-receipt-" + attempt.apply_attempt_id,
                receipt_ref=receipt_ref,
                replay_envelope_json=envelope,
                replay_envelope_hash=_digest(receipt_bytes),
                event_id=attempt.apply_attempt_id + ":completed",
                created_at=self.clock(),
            )
            self.connection.commit()
            completed = True
            try:
                lock.release()
            except C4aProjectionLockError as exc:
                raise CanonApplyCommittedLeaseReleaseUncertain(
                    "C4a completion committed but lock release is uncertain",
                    completed_identity=target_identity,
                    receipt_identity=receipt_ref,
                    replay_envelope=envelope,
                ) from exc
            return CanonApplyResult(
                task_id=attempt.task_id,
                aggregate_revision=new_revision,
                status=ChapterTaskStatus.COMPLETED,
                journal_id=attempt.journal_id,
                operation_id=attempt.operation_id,
                receipt_id="c4a-receipt-" + attempt.apply_attempt_id,
                receipt_ref=receipt_ref,
                audit_event_ids=(attempt.apply_attempt_id + ":completed:audit",),
            )
        except (CanonApplyCommittedLeaseReleaseUncertain, IdempotencyConflict):
            raise
        except Exception as exc:
            if attempt is not None and not completed:
                self._record_recovery(attempt, command.expected_revision, exc)
            if isinstance(exc, (CanonApplyInputRejected, CanonApplyConflict, CanonApplyRecoveryRequired, RevisionConflict)):
                raise
            raise CanonApplyRecoveryRequired("C4a Apply requires manual recovery") from exc
        finally:
            if not completed and getattr(lock, "held", False):
                try:
                    lock.release()
                except C4aProjectionLockError:
                    pass

    def _validate_delivery(self, command, context):
        if not isinstance(command, CanonApplyCommand) or not isinstance(context, CanonApplyDeliveryContext):
            raise CanonApplyInputRejected("Canon Apply command and delivery context are required")
        apply_key = command.apply_key or context.idempotency_key
        _required_text(apply_key, "apply_key")
        if command.apply_key and command.apply_key != context.idempotency_key:
            raise CanonApplyInputRejected("command and delivery apply keys differ")
        return command, context, apply_key, compute_canon_apply_request_digest(command)

    def _new_lock(self):
        return self.lock_factory(
            self.projection_root,
            workspace_root=self.workspace_root,
            enforce_persistent_d_drive=self.enforce_persistent_d_drive,
        )

    def _read_identity(self, project_id: str):
        try:
            return self.activation_reader.read_for_project(project_id)
        except Exception as exc:
            raise CanonApplyInputRejected("C4a current activation cannot be read") from exc

    def _read_target_bundle(self, journal) -> CanonicalBundle:
        try:
            data = self.payload_store.read(journal.target_bundle_content_hash)
            bundle = CanonicalBundle.from_bytes(data)
        except (OSError, PayloadStoreError, CanonicalBundleError, KeyError) as exc:
            raise CanonApplyInputRejected("C4a target bundle payload cannot be read") from exc
        if (
            bundle.content_hash() != journal.target_bundle_content_hash
            or bundle.manifest_hash != journal.target_manifest_hash
            or bundle.world_hash != journal.target_world_hash
        ):
            raise CanonApplyInputRejected("C4a target bundle identity is incomplete")
        registered = self.repository.resolve_artifact_ref(journal.target_bundle_ref.artifact_id)
        if registered != journal.target_bundle_ref:
            raise CanonApplyInputRejected("C4a target ArtifactRef registry identity mismatch")
        return bundle

    def _target_identity(self, journal, bundle: CanonicalBundle) -> C4aProjectionIdentity:
        suffix = bundle.content_hash().removeprefix("sha256:")
        return C4aProjectionIdentity(
            project_id=journal_project(journal, self.repository),
            version_id="c4a-v1-" + suffix,
            bundle_ref=journal.target_bundle_ref,
            manifest_hash=journal.target_manifest_hash,
            world_hash=journal.target_world_hash,
        )

    def _validate_current_base(self, current, journal) -> None:
        if current.project_id != journal_project(journal, self.repository):
            raise CanonApplyInputRejected("C4a current activation project mismatch")
        if current.bundle_ref != journal.base_bundle_ref:
            raise CanonApplyInputRejected("C4a current base ArtifactRef mismatch")
        if current.bundle_content_hash != journal.base_bundle_content_hash:
            raise CanonApplyInputRejected("C4a current base bundle hash mismatch")
        if current.manifest_hash != journal.base_manifest_hash or current.world_hash != journal.base_world_hash:
            raise CanonApplyInputRejected("C4a current base component identity mismatch")

    def _current_pointer_hash(self) -> str:
        try:
            return _digest((self.projection_root / "current.pointer").read_bytes())
        except OSError as exc:
            raise CanonApplyInputRejected("C4a current pointer cannot be read") from exc

    def _verify_projection_observation(
        self, attempt: C4aApplyAttempt, target_identity: C4aProjectionIdentity
    ) -> tuple[str, str]:
        try:
            observed = self._read_identity(attempt.project_id)
            pointer_bytes = (self.projection_root / "current.pointer").read_bytes()
            marker_bytes = (self.projection_root / "activation.marker").read_bytes()
        except Exception as exc:
            raise CanonApplyRecoveryRequired(
                "C4a target projection bytes cannot be observed"
            ) from exc
        pointer_hash = _digest(pointer_bytes)
        marker_hash = _digest(marker_bytes)
        if (
            not self._same_identity(observed, target_identity)
            or pointer_hash != attempt.target_pointer_content_hash
            or marker_hash != attempt.target_marker_content_hash
        ):
            raise CanonApplyRecoveryRequired("C4a target projection observation failed")
        return pointer_hash, marker_hash

    def _append_event_commit(self, event: C4aApplyEvent) -> None:
        try:
            self.repository.append_event(event)
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def _record_recovery(self, attempt: C4aApplyAttempt, expected_revision: int, cause: Exception) -> None:
        try:
            self.repository.mark_recovery(
                attempt,
                expected_revision=expected_revision,
                failed_operation_id=attempt.operation_id,
                error_code=_stable_recovery_error_code(cause),
                event_id=attempt.apply_attempt_id + ":recovery-required",
                created_at=self.clock(),
            )
            self.connection.commit()
        except Exception as recovery_exc:
            self.connection.rollback()
            raise CanonApplyRecoveryRequired("C4a recovery fact could not be committed") from recovery_exc

    def _replay_or_recover(self, attempt: C4aApplyAttempt, command: CanonApplyCommand, request_digest: str):
        graph = self.repository.verify_completed_graph(
            project_id=attempt.project_id,
            task_id=attempt.task_id,
            apply_key=attempt.apply_key,
            request_digest=request_digest,
        )
        events = self.repository.list_events(attempt.apply_attempt_id, attempt.project_id)
        completed = next((event for event in events if event.phase == "COMPLETED"), None)
        if completed is None:
            raise CanonApplyRecoveryRequired("C4a apply attempt is pending or requires recovery")
        if completed.replay_envelope_json is None or completed.receipt_payload_ref is None:
            raise CanonApplyRecoveryRequired("C4a completed replay facts are incomplete")
        try:
            payload = self.payload_store.read(completed.receipt_payload_ref.content_hash)
            if payload != completed.replay_envelope_json.encode("utf-8"):
                raise CanonApplyRecoveryRequired("C4a completed replay payload mismatch")
            if _digest(payload) != completed.replay_envelope_hash:
                raise CanonApplyRecoveryRequired("C4a completed replay envelope hash mismatch")
            task = self.repository.get_task_state(attempt.task_id)
            if task is None or task["status"] != ChapterTaskStatus.COMPLETED.value:
                raise CanonApplyRecoveryRequired("C4a completed Task cannot be verified")
            receipt = self.repository.get_receipt(attempt.journal_id)
            if receipt is None or receipt["receipt_ref_artifact_id"] != completed.receipt_payload_ref.artifact_id:
                raise CanonApplyRecoveryRequired("C4a completed Receipt cannot be verified")
            if (
                completed.observed_pointer_content_hash != attempt.target_pointer_content_hash
                or completed.observed_marker_content_hash != attempt.target_marker_content_hash
            ):
                raise CanonApplyRecoveryRequired("C4a completed projection observations are invalid")
            receipt_ref = self.repository.resolve_artifact_ref(receipt["receipt_ref_artifact_id"])
            if (
                receipt_ref != completed.receipt_payload_ref
                or task["commit_receipt_ref_artifact_id"] != completed.receipt_payload_ref.artifact_id
            ):
                raise CanonApplyRecoveryRequired("C4a completed Receipt identity cannot be verified")
            target_identity = C4aProjectionIdentity(
                project_id=attempt.project_id,
                version_id=attempt.target_version_id,
                bundle_ref=attempt.target_bundle_ref,
                manifest_hash=attempt.target_manifest_hash,
                world_hash=attempt.target_world_hash,
            )
            self._verify_projection_observation(attempt, target_identity)
        except CanonApplyRecoveryRequired:
            raise
        except Exception as exc:
            raise CanonApplyRecoveryRequired("C4a completed replay cannot be fully verified") from exc
        return CanonApplyResult(
            task_id=attempt.task_id,
            aggregate_revision=task["aggregate_revision"],
            status=ChapterTaskStatus.COMPLETED,
            journal_id=attempt.journal_id,
            operation_id=attempt.operation_id,
            receipt_id=receipt["receipt_id"],
            receipt_ref=completed.receipt_payload_ref,
            audit_event_ids=graph.audit_event_ids,
        )

    @staticmethod
    def _event(
        attempt,
        phase,
        created_at,
        *,
        envelope=None,
        receipt_ref=None,
        observed_pointer_content_hash=None,
        observed_marker_content_hash=None,
    ):
        envelope_hash = None if envelope is None else _digest(envelope.encode("utf-8"))
        return C4aApplyEvent(
            event_id=attempt.apply_attempt_id + ":" + phase.lower().replace("_", "-"),
            apply_attempt_id=attempt.apply_attempt_id,
            project_id=attempt.project_id,
            phase=phase,
            result=phase,
            error_code=None,
            recovery_failed_operation_id=None,
            replay_envelope_json=envelope,
            replay_envelope_hash=envelope_hash,
            receipt_payload_ref=receipt_ref,
            created_at=created_at,
            observed_pointer_content_hash=observed_pointer_content_hash,
            observed_marker_content_hash=observed_marker_content_hash,
        )

    @staticmethod
    def _completion_envelope(attempt, identity) -> str:
        return _canonical(
            {
                "apply": "C4A_CANON_COMPLETION",
                "apply_attempt_id": attempt.apply_attempt_id,
                "apply_key": attempt.apply_key,
                "audit_event_ids": [attempt.apply_attempt_id + ":completed:audit"],
                "bundle_content_hash": identity.bundle_content_hash,
                "bundle_ref_artifact_id": identity.bundle_ref_artifact_id,
                "journal_id": attempt.journal_id,
                "operation_id": attempt.operation_id,
                "project_id": identity.project_id,
                "target_marker_content_hash": attempt.target_marker_content_hash,
                "target_pointer_content_hash": attempt.target_pointer_content_hash,
                "task_id": attempt.task_id,
                "version_id": identity.version_id,
            }
        ).decode("utf-8")

    @staticmethod
    def _same_identity(left, right) -> bool:
        return (
            left.project_id == right.project_id
            and left.version_id == right.version_id
            and left.bundle_ref == right.bundle_ref
            and left.bundle_content_hash == right.bundle_content_hash
            and left.manifest_hash == right.manifest_hash
            and left.world_hash == right.world_hash
        )


def journal_project(journal, repository) -> str:
    """Read the project binding from the journal's Task without trusting input."""
    row = repository.get_task_state(journal.task_id)
    if row is None:
        raise CanonApplyInputRejected("C4a journal Task is missing")
    return row["project_id"]


C4aApply = C4aApplyService
