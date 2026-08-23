"""The independent Canon MVP C4 composition root.

This module is deliberately not layered on the G0-C composition.  It owns
the C4 connection, payload reader, activation reader, C4a UoW, projection
lease and writer lifecycle, while application code sees only its existing
ports and typed results.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from xiaoshuo.application.creation.errors import CanonApplyRecoveryRequired
from xiaoshuo.infra.config_manager import get_config

from xiaoshuo.infrastructure.persistence.sqlite.connection import get_connection
from xiaoshuo.infrastructure.persistence.sqlite.settings import SQLitePersistenceSettings
from xiaoshuo.infrastructure.persistence.sqlite.uow import SqliteC4aCompletionUnitOfWork

from .c4a_apply import C4aApplyService
from .c4a_projection_commit_lock import C4aProjectionCommitLock
from .c4a_projection_writer import C4aProjectionWriter
from .c4a_recovery import C4aRecoveryService
from .immutable_payload_store import ImmutablePayloadStore
from .projection_activation import ProjectionActivationReader


def _required_config_path(config: dict, key: str) -> Path:
    value = config.get("canon_mvp", {}).get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"canon_mvp.{key} is required")
    return Path(value)


@dataclass(frozen=True, slots=True)
class CanonMvpC4Binding:
    settings: SQLitePersistenceSettings
    payloads_dir: Path
    projection_dir: Path
    root: Path
    operator_identity: str


class CanonMvpC4ApplicationScope:
    """A single composition-owned C4 application lifetime."""

    def __init__(self, binding: CanonMvpC4Binding) -> None:
        self.binding = binding
        self.connection = get_connection(binding.settings)
        self.uow = SqliteC4aCompletionUnitOfWork(self.connection)
        self.payload_store = ImmutablePayloadStore(binding.payloads_dir)
        self.activation_reader = ProjectionActivationReader(
            binding.projection_dir,
            artifact_ref_resolver=self.uow.repository.resolve_artifact_ref,
        )
        self._apply = C4aApplyService(
            self.connection,
            operator_identity=binding.operator_identity,
            projection_root=binding.projection_dir,
            payload_store=self.payload_store,
            repository=self.uow.repository,
            activation_reader=self.activation_reader,
            lock_factory=C4aProjectionCommitLock,
            writer_factory=C4aProjectionWriter,
            workspace_root=binding.root.parent,
            enforce_persistent_d_drive=True,
            composition_owned=True,
        )
        self._recovery = C4aRecoveryService(
            self.connection,
            projection_root=binding.projection_dir,
            payload_store=self.payload_store,
            repository=self.uow.repository,
            activation_reader=self.activation_reader,
            enforce_persistent_d_drive=True,
            composition_owned=True,
        )
        self._closed = False

    @property
    def apply_canon(self) -> C4aApplyService:
        return self._apply

    @property
    def recover_canon(self) -> C4aRecoveryService:
        return self._recovery

    def verify_completed_graph(self, **kwargs):
        evidence = self.uow.repository.verify_completed_graph(**kwargs)
        attempt = self.uow.repository.get_attempt(evidence.apply_attempt_id)
        if attempt is None:
            raise CanonApplyRecoveryRequired("C4a completed graph attempt disappeared")
        self._verify_operator_identity(attempt.operator_identity, evidence.operator_identity)
        self._recovery.verify_current_projection(attempt)
        self._verify_completed_payload(evidence)
        return evidence

    def verify_recovery_graph(self, **kwargs):
        evidence = self.uow.repository.verify_recovery_completed_graph(**kwargs)
        attempt = self.uow.repository.get_attempt(evidence.completed.apply_attempt_id)
        if attempt is None:
            raise CanonApplyRecoveryRequired("C4a recovery graph attempt disappeared")
        self._verify_operator_identity(
            attempt.operator_identity, evidence.completed.operator_identity
        )
        self._recovery.verify_current_projection(attempt)
        self._verify_completed_payload(evidence.completed)
        return evidence

    def _verify_operator_identity(
        self, attempt_operator_identity: object, evidence_operator_identity: object
    ) -> None:
        expected = self.binding.operator_identity
        if (
            not isinstance(expected, str)
            or expected != "local-author"
            or not isinstance(attempt_operator_identity, str)
            or not attempt_operator_identity.strip()
            or attempt_operator_identity != expected
            or evidence_operator_identity != attempt_operator_identity
        ):
            raise CanonApplyRecoveryRequired(
                "C4a completed graph operator identity is not config-bound local-author"
            )

    def _verify_completed_payload(self, evidence) -> None:
        event = self.uow.repository.get_event(
            evidence.apply_attempt_id, evidence.project_id, "COMPLETED"
        )
        if event is None or event.receipt_payload_ref is None or event.replay_envelope_json is None:
            raise CanonApplyRecoveryRequired("C4a completed payload evidence is missing")
        payload = self.payload_store.read(event.receipt_payload_ref.content_hash)
        if payload != event.replay_envelope_json.encode("utf-8"):
            raise CanonApplyRecoveryRequired("C4a completed payload readback mismatch")
        if _digest(payload) != event.replay_envelope_hash:
            raise CanonApplyRecoveryRequired("C4a completed payload hash mismatch")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.uow.close()

    def __enter__(self) -> "CanonMvpC4ApplicationScope":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


class CanonMvpC4Composition:
    """Build C4 exclusively from the config-bound Canon MVP paths."""

    def __init__(self, binding: CanonMvpC4Binding) -> None:
        if binding.operator_identity != "local-author":
            raise RuntimeError("C4 operator identity must be config-bound local-author")
        self.binding = binding

    @classmethod
    def from_config(cls) -> "CanonMvpC4Composition":
        config = get_config()
        canon = config.get("canon_mvp")
        if not isinstance(canon, dict):
            raise RuntimeError("canon_mvp configuration is required")
        db_path = _required_config_path(config, "creation_db_path")
        payloads = _required_config_path(config, "payloads_dir")
        projection = _required_config_path(config, "projection_dir")
        root = _required_config_path(config, "root")
        backup = _required_config_path(config, "backups_dir")
        busy_timeout = canon.get("creation_busy_timeout_ms")
        operator = canon.get("local_operator_id")
        if not isinstance(busy_timeout, int) or not isinstance(operator, str):
            raise RuntimeError("C4 config-bound operator and SQLite settings are required")
        return cls(
            CanonMvpC4Binding(
                settings=SQLitePersistenceSettings(db_path, busy_timeout, backup),
                payloads_dir=payloads,
                projection_dir=projection,
                root=root,
                operator_identity=operator,
            )
        )

    def open_scope(self) -> CanonMvpC4ApplicationScope:
        return CanonMvpC4ApplicationScope(self.binding)

    def scope(self) -> CanonMvpC4ApplicationScope:
        return self.open_scope()

    def __enter__(self) -> CanonMvpC4ApplicationScope:
        self._scope = self.open_scope()
        return self._scope

    def __exit__(self, exc_type, exc, tb) -> None:
        self._scope.close()


CanonMvpC4CompositionRoot = CanonMvpC4Composition


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()
