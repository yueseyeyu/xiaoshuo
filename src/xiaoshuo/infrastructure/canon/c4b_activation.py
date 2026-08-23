"""C4b composition root for the first deterministic Canon activation.

This module is the only production writer in the C4b whitelist.  It keeps the
application boundary free of infrastructure imports and makes the cross-store
ordering explicit: bootstrap lock, seed/bundle, payload readback, Transaction
A, version, pointer, Transaction B/READY_FOR_MARKER, marker, readback, and
lock release.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from xiaoshuo import PROJECT_ROOT
from xiaoshuo.application.creation.canon_activation import CanonActivationRequest
from xiaoshuo.application.creation.errors import (
    ActivationConflict,
    ActivationInputRejected,
    ActivationRecoveryRequired,
)
from xiaoshuo.application.creation.ports import CanonActivationResult
from xiaoshuo.domain.creation import ArtifactRef
from xiaoshuo.infra.config_manager import get_config

from .canonical_bundle import CanonicalBundle, CanonicalBundleError
from .c4b_bootstrap_lock import (
    BootstrapLockConflict,
    BootstrapLockError,
    C4bBootstrapLock,
    preflight_activation_roots,
)
from .immutable_payload_store import ImmutablePayloadStore
from .legacy_seed_importer import LegacySeedImportError, LegacyWorldSeedImporter
from .projection_activation_writer import (
    C4bProjectionIdentity,
    ProjectionActivationWriter,
    ProjectionActivationWriterError,
)
from xiaoshuo.infrastructure.persistence.sqlite.canon_activation_repository import (
    ActivationAttempt,
    ActivationEvent,
    CanonActivationRepositoryError,
    SqliteCanonActivationRepository,
)


_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_POINTER_FIELDS = frozenset(
    {
        "pointer_schema_version",
        "project_id",
        "bundle_schema_version",
        "version_id",
        "bundle_ref_artifact_id",
        "bundle_content_hash",
        "manifest_hash",
        "world_hash",
    }
)
_MARKER_FIELDS = frozenset(
    {
        "marker_schema_version",
        "project_id",
        "pointer_content_hash",
        "pointer_schema_version",
        "bundle_schema_version",
        "version_id",
        "bundle_ref_artifact_id",
        "bundle_content_hash",
        "manifest_hash",
        "world_hash",
    }
)
_IDENTITY_FIELDS = frozenset(
    {
        "project_id",
        "version_id",
        "bundle_schema_version",
        "bundle_ref_artifact_id",
        "bundle_content_hash",
        "manifest_hash",
        "world_hash",
    }
)


class C4bActivationError(RuntimeError):
    """The infrastructure activation could not produce a trusted result."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ActivationInputRejected(f"{field} is required")
    return value


def _valid_digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise ActivationInputRejected(f"{field} must be a sha256 digest")
    return value


def _configured_root(name: str) -> Path:
    try:
        value = get_config()["canon_mvp"][name]
    except (KeyError, TypeError) as exc:
        raise ActivationInputRejected(f"canon_mvp.{name} is required") from exc
    if not isinstance(value, str) or not value.strip():
        raise ActivationInputRejected(f"canon_mvp.{name} is required")
    return Path(value)


def _safe_identifier(value: object, field: str) -> str:
    value = _required_text(value, field)
    if (
        value in {".", ".."}
        or Path(value).name != value
        or any(char in '<>:/\\"|?*' for char in value)
        or value.endswith((" ", "."))
    ):
        raise ActivationInputRejected(f"{field} is not a safe identifier")
    return value


def _clock_default() -> str:
    return datetime.now(timezone.utc).isoformat()


class C4bActivationService:
    """Execute one C4b first activation or a fully verified read-only replay."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        operator_identity: str,
        payload_root: Path | str | None = None,
        projection_root: Path | str | None = None,
        payload_store: object | None = None,
        repository: SqliteCanonActivationRepository | None = None,
        seed_importer: LegacyWorldSeedImporter | None = None,
        id_factory: Callable[[], object] | None = None,
        clock: Callable[[], str] | None = None,
        workspace_root: Path | str | None = None,
        enforce_persistent_d_drive: bool = True,
    ) -> None:
        if not isinstance(connection, sqlite3.Connection):
            raise ActivationInputRejected("an open SQLite connection is required")
        if enforce_persistent_d_drive and any(
            injected is not None for injected in (seed_importer, payload_store, repository)
        ):
            raise ActivationInputRejected(
                "production C4b activation does not accept injected adapters"
            )
        self.connection = connection
        self.repository = (
            SqliteCanonActivationRepository(connection)
            if enforce_persistent_d_drive
            else repository or SqliteCanonActivationRepository(connection)
        )
        self.operator_identity = _safe_identifier(operator_identity, "operator_identity")
        configured_payload = _configured_root("payloads_dir")
        configured_projection = _configured_root("projection_dir")
        self.payload_root = Path(payload_root) if payload_root is not None else configured_payload
        self.projection_root = (
            Path(projection_root) if projection_root is not None else configured_projection
        )
        if enforce_persistent_d_drive:
            if self.payload_root.resolve() != configured_payload.resolve():
                raise ActivationInputRejected("payload root must come from config.yaml")
            if self.projection_root.resolve() != configured_projection.resolve():
                raise ActivationInputRejected("projection root must come from config.yaml")
        if payload_store is None:
            self.payload_store = ImmutablePayloadStore(self.payload_root)
        else:
            self.payload_store = payload_store
        if not callable(getattr(self.payload_store, "put", None)) or not callable(
            getattr(self.payload_store, "read", None)
        ):
            raise ActivationInputRejected("an immutable payload store is required")
        self.seed_importer = (
            LegacyWorldSeedImporter() if enforce_persistent_d_drive else seed_importer or LegacyWorldSeedImporter()
        )
        self.id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self.clock = clock or _clock_default
        self.workspace_root = Path(workspace_root) if workspace_root is not None else PROJECT_ROOT
        self.enforce_persistent_d_drive = enforce_persistent_d_drive

    def activate(self, request: CanonActivationRequest) -> CanonActivationResult:
        request = self._validate_request(request)
        roots = self._preflight_roots()

        # A completed replay is read-only.  It must not create a lease, touch
        # the payload store, or change any SQLite fact.
        try:
            existing = self.repository.get_attempt_by_project(request.project_id)
            existing_key = self.repository.get_attempt_by_key(request.attempt_key)
        except (sqlite3.Error, CanonActivationRepositoryError) as exc:
            raise ActivationRecoveryRequired(
                "C4b activation facts cannot be read safely"
            ) from exc
        if existing is not None:
            return self._replay_existing(request, existing)
        if existing_key is not None:
            raise ActivationConflict("activation attempt key belongs to another identity")

        try:
            lock = C4bBootstrapLock(
                roots.payload_root,
                roots.projection_root,
                workspace_root=self.workspace_root,
                enforce_persistent_d_drive=self.enforce_persistent_d_drive,
            )
            lock.acquire()
        except BootstrapLockConflict as exc:
            raise ActivationConflict("C4b bootstrap lock is occupied") from exc
        except BootstrapLockError as exc:
            raise ActivationInputRejected(str(exc)) from exc

        # Deliberately do not use a context manager: successful release is
        # sequenced after marker readback; failures retain manual-recovery
        # evidence rather than silently repairing or reclaiming it.
        return self._activate_locked(request, lock)

    def _validate_request(self, request: CanonActivationRequest) -> CanonActivationRequest:
        if not isinstance(request, CanonActivationRequest):
            raise ActivationInputRejected("a CanonActivationRequest is required")
        _safe_identifier(request.project_id, "project_id")
        _safe_identifier(request.attempt_key, "attempt_key")
        _valid_digest(request.request_digest, "request_digest")
        return request

    def _preflight_roots(self):
        try:
            return preflight_activation_roots(
                self.payload_root,
                self.projection_root,
                workspace_root=self.workspace_root,
                enforce_persistent_d_drive=self.enforce_persistent_d_drive,
            )
        except BootstrapLockError as exc:
            raise ActivationInputRejected(str(exc)) from exc

    def _activate_locked(
        self, request: CanonActivationRequest, lock: C4bBootstrapLock
    ) -> CanonActivationResult:
        try:
            self._preflight_initial_payload_state()
            self._preflight_initial_projection_state()
            imported = self.seed_importer.build_bundle(request.project_id)
            bundle = imported.bundle
            payload_bytes = bundle.to_bytes()
            content_hash = bundle.content_hash()
            payload_digest = self.payload_store.put(payload_bytes)
            if payload_digest != content_hash:
                raise C4bActivationError("payload digest is not bundle content hash")
            readback = self.payload_store.read(payload_digest)
            verified_bundle = CanonicalBundle.from_bytes(readback)
            if readback != payload_bytes or not self._bundle_matches(bundle, verified_bundle):
                raise C4bActivationError("payload readback identity mismatch")

            identity = self._identity(request.project_id, verified_bundle)
            pointer_bytes = ProjectionActivationWriter.pointer_bytes(identity)
            pointer_hash = _digest(pointer_bytes)
            attempt = ActivationAttempt(
                attempt_id=_safe_identifier(str(self.id_factory()), "attempt_id"),
                project_id=request.project_id,
                attempt_key=request.attempt_key,
                request_digest=request.request_digest,
                seed_digest=imported.seed_digest,
                bundle_ref=identity.bundle_ref,
                version_id=identity.version_id,
                pointer_content_hash=pointer_hash,
                operator_identity=self.operator_identity,
                created_at=self.clock(),
                manifest_hash=identity.manifest_hash,
                world_hash=identity.world_hash,
            )
            prepared = ActivationEvent(
                event_id=attempt.attempt_id + ":prepared",
                attempt_id=attempt.attempt_id,
                project_id=attempt.project_id,
                phase="PREPARED",
                result="PREPARED",
                error_code=None,
                replay_envelope_json=None,
                replay_envelope_hash=None,
                created_at=self.clock(),
            )

            # Transaction A is the first SQLite write and is complete before
            # any production projection file is created.
            self.repository.create_prepared(attempt, prepared)
            writer = ProjectionActivationWriter(self.projection_root, lock)
            writer.write_version(verified_bundle, identity)
            actual_pointer = writer.write_pointer(identity)
            if actual_pointer != pointer_bytes:
                raise C4bActivationError("pointer readback identity mismatch")

            envelope = self._replay_envelope(request, attempt, identity)
            ready = ActivationEvent(
                event_id=attempt.attempt_id + ":ready",
                attempt_id=attempt.attempt_id,
                project_id=attempt.project_id,
                phase="READY_FOR_MARKER",
                result="READY_FOR_MARKER",
                error_code=None,
                replay_envelope_json=envelope,
                replay_envelope_hash=_digest(envelope.encode("utf-8")),
                created_at=self.clock(),
            )
            try:
                self.repository.append_event(ready)
                self.connection.commit()
            except Exception as exc:
                raise ActivationRecoveryRequired(
                    "Transaction B failed before marker; manual recovery is required"
                ) from exc

            marker = writer.write_marker(identity)
            expected_marker = ProjectionActivationWriter.marker_bytes(identity, pointer_bytes)
            if marker != expected_marker:
                raise ActivationRecoveryRequired("marker readback identity mismatch")
            self._verify_projection(identity, verified_bundle, ready)
            try:
                lock.release()
            except BootstrapLockError as exc:
                raise ActivationRecoveryRequired(
                    "bootstrap lock release requires manual recovery"
                ) from exc
            return CanonActivationResult(
                status="ACTIVATED",
                attempt_id=attempt.attempt_id,
                project_id=attempt.project_id,
                version_id=attempt.version_id,
                replay_envelope_json=envelope,
            )
        except (ActivationConflict, ActivationInputRejected, ActivationRecoveryRequired):
            raise
        except (LegacySeedImportError, CanonicalBundleError) as exc:
            raise ActivationInputRejected(str(exc)) from exc
        except (ProjectionActivationWriterError, CanonActivationRepositoryError, OSError) as exc:
            raise ActivationRecoveryRequired(str(exc)) from exc
        except Exception as exc:
            raise ActivationRecoveryRequired("C4b activation failed; manual recovery is required") from exc

    def _preflight_initial_projection_state(self) -> None:
        """Reject projection residue before seed, payload, or SQLite writes."""
        root = self.projection_root
        if not root.exists():
            return
        if not root.is_dir() or root.is_symlink():
            raise ActivationRecoveryRequired("projection root is unsafe")
        try:
            if any(root.iterdir()):
                raise ActivationRecoveryRequired(
                    "projection root is non-empty; manual recovery is required"
                )
        except OSError as exc:
            raise ActivationRecoveryRequired("projection root cannot be inspected") from exc

    def _preflight_initial_payload_state(self) -> None:
        """Reject a file/reparse payload root before reading the seed."""
        root = self.payload_root
        if not root.exists():
            return
        if root.is_symlink() or not root.is_dir():
            raise ActivationInputRejected("payload root is unsafe")
        try:
            if getattr(root.stat(), "st_file_attributes", 0) & 0x400:
                raise ActivationInputRejected("payload root is a reparse point")
        except OSError as exc:
            raise ActivationInputRejected("payload root cannot be inspected") from exc

    def _replay_existing(
        self, request: CanonActivationRequest, attempt: ActivationAttempt
    ) -> CanonActivationResult:
        if (
            attempt.project_id != request.project_id
            or attempt.attempt_key != request.attempt_key
            or attempt.request_digest != request.request_digest
        ):
            raise ActivationConflict("activation identity conflicts with existing project facts")
        try:
            payload = self.payload_store.read(attempt.bundle_content_hash)
            bundle = CanonicalBundle.from_bytes(payload)
            if bundle.content_hash() != attempt.bundle_content_hash:
                raise ActivationRecoveryRequired("activation payload identity is invalid")
            identity = C4bProjectionIdentity(
                project_id=attempt.project_id,
                version_id=attempt.version_id,
                bundle_ref=attempt.bundle_ref,
                manifest_hash=attempt.manifest_hash,
                world_hash=attempt.world_hash,
            )
            if not self._bundle_matches_identity(bundle, identity):
                raise ActivationRecoveryRequired("activation payload identity is invalid")
            ready = self.repository.get_event_by_phase(attempt.attempt_id, "READY_FOR_MARKER")
            if ready is None:
                raise ActivationRecoveryRequired("READY_FOR_MARKER event is missing")
            events = self.repository.list_events(attempt.attempt_id)
            if [event.phase for event in events] != ["PREPARED", "READY_FOR_MARKER"]:
                raise ActivationRecoveryRequired("activation event history is not replayable")
            self._verify_projection(identity, bundle, ready)
            if not ready.replay_envelope_json:
                raise ActivationRecoveryRequired("replay envelope is missing")
            return CanonActivationResult(
                status="REPLAY",
                attempt_id=attempt.attempt_id,
                project_id=attempt.project_id,
                version_id=attempt.version_id,
                replay_envelope_json=ready.replay_envelope_json,
            )
        except ActivationRecoveryRequired:
            raise
        except (OSError, RuntimeError, CanonActivationRepositoryError) as exc:
            raise ActivationRecoveryRequired(
                "completed activation cannot be fully verified"
            ) from exc

    @staticmethod
    def _bundle_matches(left: CanonicalBundle, right: CanonicalBundle) -> bool:
        return (
            left.schema_version == right.schema_version
            and left.manifest == right.manifest
            and left.world_md == right.world_md
            and left.content_hash() == right.content_hash()
        )

    @staticmethod
    def _bundle_matches_identity(
        bundle: CanonicalBundle, identity: C4bProjectionIdentity
    ) -> bool:
        return (
            bundle.schema_version == identity.bundle_schema_version
            and bundle.content_hash() == identity.bundle_content_hash
            and bundle.manifest_hash == identity.manifest_hash
            and bundle.world_hash == identity.world_hash
        )

    @staticmethod
    def _identity(project_id: str, bundle: CanonicalBundle) -> C4bProjectionIdentity:
        suffix = bundle.content_hash().removeprefix("sha256:")
        return C4bProjectionIdentity(
            project_id=project_id,
            version_id="c4b-v1-" + suffix,
            bundle_ref=ArtifactRef(
                artifact_id="c4b-bundle-" + suffix,
                schema_version=bundle.schema_version,
                content_hash=bundle.content_hash(),
            ),
            manifest_hash=bundle.manifest_hash,
            world_hash=bundle.world_hash,
        )

    @staticmethod
    def _replay_envelope(
        request: CanonActivationRequest,
        attempt: ActivationAttempt,
        identity: C4bProjectionIdentity,
    ) -> str:
        return _canonical_bytes(
            {
                "activation": "C4B_FIRST_PROJECTION",
                "attempt_id": attempt.attempt_id,
                "attempt_key": request.attempt_key,
                "bundle_content_hash": identity.bundle_content_hash,
                "bundle_ref_artifact_id": identity.bundle_ref_artifact_id,
                "manifest_hash": identity.manifest_hash,
                "pointer_content_hash": attempt.pointer_content_hash,
                "project_id": identity.project_id,
                "request_digest": request.request_digest,
                "seed_digest": attempt.seed_digest,
                "version_id": identity.version_id,
                "world_hash": identity.world_hash,
            }
        ).decode("utf-8")

    def _verify_projection(
        self,
        identity: C4bProjectionIdentity,
        bundle: CanonicalBundle,
        ready: ActivationEvent,
    ) -> None:
        root = self.projection_root
        marker_path = root / "activation.marker"
        pointer_path = root / "current.pointer"
        version_dir = root / "versions" / identity.version_id
        if not root.is_dir() or not pointer_path.is_file() or not marker_path.is_file():
            raise ActivationRecoveryRequired("activation marker or pointer is missing")
        if (root / "versions").is_symlink() or version_dir.is_symlink():
            raise ActivationRecoveryRequired("activation version path is unsafe")
        try:
            pointer_bytes = pointer_path.read_bytes()
            pointer = json.loads(pointer_bytes.decode("utf-8"))
            marker_bytes = marker_path.read_bytes()
            marker = json.loads(marker_bytes.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ActivationRecoveryRequired("activation files are invalid") from exc
        if (
            not isinstance(pointer, dict)
            or set(pointer) != _POINTER_FIELDS
            or _canonical_bytes(pointer) != pointer_bytes
            or not isinstance(marker, dict)
            or set(marker) != _MARKER_FIELDS
            or _canonical_bytes(marker) != marker_bytes
        ):
            raise ActivationRecoveryRequired("activation files are not canonical")
        expected_pointer = ProjectionActivationWriter.pointer_bytes(identity)
        if pointer_bytes != expected_pointer:
            raise ActivationRecoveryRequired("pointer identity mismatch")
        expected_marker = ProjectionActivationWriter.marker_bytes(identity, pointer_bytes)
        if marker_bytes != expected_marker:
            raise ActivationRecoveryRequired("marker identity mismatch")
        if not version_dir.is_dir():
            raise ActivationRecoveryRequired("activation version is missing")
        try:
            version_identity = json.loads(
                (version_dir / "bundle.identity.json").read_bytes().decode("utf-8")
            )
            version_manifest = (version_dir / "manifest.json").read_bytes()
            version_world = (version_dir / "world.md").read_bytes()
            version_bundle = CanonicalBundle(1, version_manifest, version_world)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, RuntimeError) as exc:
            raise ActivationRecoveryRequired("activation version is invalid") from exc
        if (
            not isinstance(version_identity, dict)
            or set(version_identity) != _IDENTITY_FIELDS
            or _canonical_bytes(version_identity)
            != (version_dir / "bundle.identity.json").read_bytes()
            or any(version_identity[key] != identity.as_fields()[key] for key in _IDENTITY_FIELDS)
            or not self._bundle_matches(version_bundle, bundle)
        ):
            raise ActivationRecoveryRequired("activation version identity mismatch")
        registered = self.repository.resolve_artifact_ref(identity.bundle_ref_artifact_id)
        if registered != identity.bundle_ref:
            raise ActivationRecoveryRequired("activation registry identity mismatch")
        if ready.phase != "READY_FOR_MARKER" or ready.result != "READY_FOR_MARKER":
            raise ActivationRecoveryRequired("READY_FOR_MARKER event is invalid")
        if not ready.replay_envelope_json or ready.replay_envelope_hash != _digest(
            ready.replay_envelope_json.encode("utf-8")
        ):
            raise ActivationRecoveryRequired("replay envelope identity mismatch")


C4bActivation = C4bActivationService
CanonActivationService = C4bActivationService
