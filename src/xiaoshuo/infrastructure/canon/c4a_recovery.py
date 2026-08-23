"""Durable-fact-only C4a Recovery composition root."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from xiaoshuo.application.creation.canon_recovery import (
    CanonRecoveryCommand,
    compute_canon_recovery_request_digest,
)
from xiaoshuo.application.creation.canon_recovery_context import CanonRecoveryDeliveryContext
from xiaoshuo.application.creation.canon_results import CanonRecoveryResult
from xiaoshuo.application.creation.errors import (
    CanonApplyInputRejected,
    CanonApplyRecoveryRequired,
    IdempotencyConflict,
)
from xiaoshuo.domain.creation import ArtifactRef, ChapterTaskStatus
from xiaoshuo.infra.config_manager import get_config

from .canonical_bundle import CanonicalBundle
from .immutable_payload_store import ImmutablePayloadStore
from .projection_activation import ProjectionActivationReader
from .c4a_projection_writer import C4aProjectionIdentity
from xiaoshuo.infrastructure.persistence.sqlite.c4a_apply_repository import (
    C4aApplyAttempt,
    SqliteC4aApplyRepository,
)


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _configured_projection_root() -> Path:
    try:
        return Path(get_config()["canon_mvp"]["projection_dir"])
    except (KeyError, TypeError) as exc:
        raise CanonApplyInputRejected("canon_mvp.projection_dir is required") from exc


def _configured_operator_identity() -> str:
    try:
        value = get_config()["canon_mvp"]["local_operator_id"]
    except (KeyError, TypeError) as exc:
        raise CanonApplyInputRejected("canon_mvp.local_operator_id is required") from exc
    if not isinstance(value, str) or not value.strip():
        raise CanonApplyInputRejected("canon_mvp.local_operator_id is required")
    return value


class C4aRecoveryService:
    """Complete only a verified receipt-payload-ready DB boundary."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        projection_root: Path | str | None = None,
        payload_store: object | None = None,
        repository: SqliteC4aApplyRepository | None = None,
        activation_reader: object | None = None,
        projection_reader: object | None = None,
        clock: Callable[[], str] | None = None,
        enforce_persistent_d_drive: bool = True,
        composition_owned: bool = False,
    ) -> None:
        if not isinstance(connection, sqlite3.Connection):
            raise CanonApplyInputRejected("an open SQLite connection is required")
        self.enforce_persistent_d_drive = enforce_persistent_d_drive
        if enforce_persistent_d_drive and not composition_owned and any(
            value is not None
            for value in (
                projection_root,
                payload_store,
                repository,
                activation_reader,
                projection_reader,
            )
        ):
            raise CanonApplyInputRejected(
                "production C4a recovery adapters are composition-root owned"
            )
        configured = _configured_projection_root()
        self.projection_root = Path(projection_root) if projection_root is not None else configured
        if enforce_persistent_d_drive and self.projection_root.resolve() != configured.resolve():
            raise CanonApplyInputRejected("projection root must come from config.yaml")
        self.repository = repository or SqliteC4aApplyRepository(connection)
        self.payload_store = payload_store if payload_store is not None else ImmutablePayloadStore()
        reader = activation_reader or projection_reader
        if reader is None and enforce_persistent_d_drive:
            reader = ProjectionActivationReader(
                self.projection_root,
                artifact_ref_resolver=self.repository.resolve_artifact_ref,
            )
        if reader is None or not callable(getattr(reader, "read_for_project", None)):
            raise CanonApplyInputRejected("an activation reader is required")
        self.activation_reader = reader
        self.clock = clock or (lambda: datetime.now(timezone.utc).isoformat())

    def recover(
        self, command: CanonRecoveryCommand, context: CanonRecoveryDeliveryContext
    ) -> CanonRecoveryResult:
        if not isinstance(command, CanonRecoveryCommand) or not isinstance(
            context, CanonRecoveryDeliveryContext
        ):
            raise CanonApplyInputRejected("Canon Recovery command and context are required")
        apply_key = command.apply_key or context.idempotency_key
        if command.apply_key and command.apply_key != context.idempotency_key:
            raise CanonApplyInputRejected("command and delivery apply keys differ")
        request_digest = compute_canon_recovery_request_digest(command)
        attempt = self.repository.get_attempt_by_key(apply_key)
        if attempt is None:
            raise CanonApplyRecoveryRequired("C4a recovery requires a persisted Apply attempt")
        if (
            self.enforce_persistent_d_drive
            and attempt.operator_identity != _configured_operator_identity()
        ):
            raise CanonApplyRecoveryRequired(
                "C4a recovery operator identity is not config-bound local-author"
            )
        if attempt.request_digest != request_digest:
            raise IdempotencyConflict("C4a recovery apply_key digest conflicts")
        events = self.repository.list_events(attempt.apply_attempt_id, attempt.project_id)
        completed = next((event for event in events if event.phase == "COMPLETED"), None)
        if completed is not None:
            task = self.repository.get_task_state(attempt.task_id)
            receipt = self.repository.get_receipt(attempt.journal_id)
            if task is None or receipt is None or task["status"] != ChapterTaskStatus.COMPLETED.value:
                raise CanonApplyRecoveryRequired("C4a completed recovery facts are invalid")
            recovery_evidence = self.repository.verify_recovery_completed_graph(
                project_id=attempt.project_id,
                task_id=attempt.task_id,
                apply_key=attempt.apply_key,
                request_digest=attempt.request_digest,
            )
            evidence = recovery_evidence.completed
            self._verify_completed_facts(attempt, events, completed, task, receipt)
            return CanonRecoveryResult(
                task_id=attempt.task_id,
                aggregate_revision=task["aggregate_revision"],
                status=ChapterTaskStatus.COMPLETED,
                journal_id=attempt.journal_id,
                operation_id=attempt.operation_id,
                audit_event_ids=evidence.audit_event_ids,
            )
        task = self.repository.get_task_state(attempt.task_id)
        recovery_event = next(
            (event for event in events if event.phase == "RECOVERY_REQUIRED"), None
        )
        if (
            task is None
            or task["status"] != ChapterTaskStatus.RECOVERY_REQUIRED.value
            or recovery_event is None
        ):
            raise CanonApplyRecoveryRequired(
                "C4a DB-only recovery requires RECOVERY_REQUIRED Task and event"
            )
        ready = next((event for event in events if event.phase == "RECEIPT_PAYLOAD_READY"), None)
        if ready is None or ready.receipt_payload_ref is None or ready.replay_envelope_json is None:
            raise CanonApplyRecoveryRequired("C4a recovery lacks verified receipt payload facts")
        self._verify_event_observations(attempt, events)
        payload = self.payload_store.read(ready.receipt_payload_ref.content_hash)
        if payload != ready.replay_envelope_json.encode("utf-8") or _digest(payload) != ready.replay_envelope_hash:
            raise CanonApplyRecoveryRequired("C4a receipt payload readback is invalid")
        try:
            target_bundle = CanonicalBundle.from_bytes(
                self.payload_store.read(attempt.target_bundle_ref.content_hash)
            )
            if (
                target_bundle.content_hash() != attempt.target_bundle_ref.content_hash
                or target_bundle.manifest_hash != attempt.target_manifest_hash
                or target_bundle.world_hash != attempt.target_world_hash
                or target_bundle.schema_version != attempt.target_bundle_ref.schema_version
            ):
                raise CanonApplyRecoveryRequired("C4a target bundle identity is invalid")
            registered = self.repository.resolve_artifact_ref(attempt.target_bundle_ref.artifact_id)
            if registered != attempt.target_bundle_ref:
                raise CanonApplyRecoveryRequired("C4a target ArtifactRef identity is invalid")
        except Exception as exc:
            raise CanonApplyRecoveryRequired(
                "C4a target projection is not fully verified; manual recovery is required"
            ) from exc
        self._verify_projection_observation(attempt)
        try:
            new_revision = self.repository.complete_verified_canon_recovery(
                attempt,
                expected_revision=task["aggregate_revision"],
                receipt_id="c4a-receipt-" + attempt.apply_attempt_id,
                receipt_ref=ready.receipt_payload_ref,
                replay_envelope_json=ready.replay_envelope_json,
                replay_envelope_hash=ready.replay_envelope_hash or "",
                event_id=attempt.apply_attempt_id + ":completed-recovery",
                created_at=self.clock(),
            )
            self.repository.connection.commit()
        except Exception:
            self.repository.connection.rollback()
            raise
        return CanonRecoveryResult(
            task_id=attempt.task_id,
            aggregate_revision=new_revision,
            status=ChapterTaskStatus.COMPLETED,
            journal_id=attempt.journal_id,
            operation_id=attempt.operation_id,
            audit_event_ids=(attempt.apply_attempt_id + ":completed-recovery:audit",),
        )

    def _verify_event_observations(self, attempt: C4aApplyAttempt, events) -> None:
        for phase in ("PROJECTION_COMMITTED", "RECEIPT_PAYLOAD_READY"):
            event = next((item for item in events if item.phase == phase), None)
            if (
                event is None
                or event.observed_pointer_content_hash != attempt.target_pointer_content_hash
                or event.observed_marker_content_hash != attempt.target_marker_content_hash
            ):
                raise CanonApplyRecoveryRequired(
                    "C4a projection observation facts are incomplete"
                )

    def _verify_completed_facts(self, attempt, events, completed, task, receipt) -> None:
        self._verify_event_observations(attempt, events)
        if (
            completed.observed_pointer_content_hash != attempt.target_pointer_content_hash
            or completed.observed_marker_content_hash != attempt.target_marker_content_hash
            or completed.replay_envelope_json is None
            or completed.replay_envelope_hash is None
            or completed.receipt_payload_ref is None
            or receipt["receipt_ref_artifact_id"] != completed.receipt_payload_ref.artifact_id
            or task["commit_receipt_ref_artifact_id"] != completed.receipt_payload_ref.artifact_id
        ):
            raise CanonApplyRecoveryRequired("C4a completed recovery observations are invalid")
        try:
            payload = self.payload_store.read(completed.receipt_payload_ref.content_hash)
        except Exception as exc:
            raise CanonApplyRecoveryRequired("C4a completed receipt payload cannot be read") from exc
        if (
            payload != completed.replay_envelope_json.encode("utf-8")
            or _digest(payload) != completed.replay_envelope_hash
        ):
            raise CanonApplyRecoveryRequired("C4a completed receipt payload is invalid")
        self._verify_target_bundle(attempt)
        self._verify_projection_observation(attempt)

    def _verify_target_bundle(self, attempt: C4aApplyAttempt) -> None:
        try:
            target_bundle = CanonicalBundle.from_bytes(
                self.payload_store.read(attempt.target_bundle_ref.content_hash)
            )
            registered = self.repository.resolve_artifact_ref(attempt.target_bundle_ref.artifact_id)
        except Exception as exc:
            raise CanonApplyRecoveryRequired("C4a target bundle cannot be verified") from exc
        if (
            registered != attempt.target_bundle_ref
            or target_bundle.schema_version != attempt.target_bundle_ref.schema_version
            or target_bundle.content_hash() != attempt.target_bundle_ref.content_hash
            or target_bundle.manifest_hash != attempt.target_manifest_hash
            or target_bundle.world_hash != attempt.target_world_hash
        ):
            raise CanonApplyRecoveryRequired("C4a target bundle identity is invalid")

    def _verify_projection_observation(self, attempt: C4aApplyAttempt) -> None:
        target_identity = C4aProjectionIdentity(
            project_id=attempt.project_id,
            version_id=attempt.target_version_id,
            bundle_ref=attempt.target_bundle_ref,
            manifest_hash=attempt.target_manifest_hash,
            world_hash=attempt.target_world_hash,
        )
        try:
            observed = self.activation_reader.read_for_project(attempt.project_id)
            pointer_bytes = (self.projection_root / "current.pointer").read_bytes()
            marker_bytes = (self.projection_root / "activation.marker").read_bytes()
        except Exception as exc:
            raise CanonApplyRecoveryRequired(
                "C4a target projection cannot be fully verified"
            ) from exc
        if (
            not self._same_identity(observed, target_identity)
            or _digest(pointer_bytes) != attempt.target_pointer_content_hash
            or _digest(marker_bytes) != attempt.target_marker_content_hash
        ):
            raise CanonApplyRecoveryRequired("C4a target projection observations are invalid")

    def verify_current_projection(self, attempt: C4aApplyAttempt) -> None:
        """Re-read the config-bound projection without changing any fact."""
        self._verify_projection_observation(attempt)

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


C4aRecovery = C4aRecoveryService
