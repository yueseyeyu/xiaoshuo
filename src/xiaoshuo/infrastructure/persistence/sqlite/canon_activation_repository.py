"""SQLite adapter for the independent C4b activation fact graph."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from typing import Iterable

from xiaoshuo.application.creation.errors import ActivationConflict, ArtifactIdentityConflict
from xiaoshuo.domain.creation import ArtifactRef


class CanonActivationRepositoryError(RuntimeError):
    """The activation fact graph cannot be read or validated."""


_PHASES = {"PREPARED", "READY_FOR_MARKER", "MANUAL_RECOVERY_REQUIRED"}


def _digest(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(char not in "0123456789abcdef" for char in value[7:])
    ):
        raise CanonActivationRepositoryError("invalid activation digest")
    return value


def _hash_envelope(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ActivationAttempt:
    attempt_id: str
    project_id: str
    attempt_key: str
    request_digest: str
    seed_digest: str
    bundle_ref: ArtifactRef
    version_id: str
    pointer_content_hash: str
    operator_identity: str
    created_at: str
    manifest_hash: str
    world_hash: str

    @property
    def bundle_ref_artifact_id(self) -> str:
        return self.bundle_ref.artifact_id

    @property
    def bundle_schema_version(self) -> int:
        return self.bundle_ref.schema_version

    @property
    def bundle_content_hash(self) -> str:
        return self.bundle_ref.content_hash


@dataclass(frozen=True, slots=True)
class ActivationEvent:
    """Only phase/outcome facts; complete identity is obtained by join."""

    event_id: str
    attempt_id: str
    project_id: str
    phase: str
    result: str
    error_code: str | None
    replay_envelope_json: str | None
    replay_envelope_hash: str | None
    created_at: str

    @property
    def replay_envelope(self) -> str | None:
        return self.replay_envelope_json


@dataclass(frozen=True, slots=True)
class ActivationEventWithAttempt:
    event: ActivationEvent
    attempt: ActivationAttempt


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CanonActivationRepositoryError(f"{field} is required")
    return value


class SqliteCanonActivationRepository:
    """Repository with caller-owned transaction boundaries."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def register_artifact_ref(self, ref: ArtifactRef) -> ArtifactRef:
        row = self.conn.execute(
            "SELECT schema_version, content_hash FROM creation_artifact_ref WHERE artifact_id = ?",
            (ref.artifact_id,),
        ).fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO creation_artifact_ref (artifact_id, schema_version, content_hash) VALUES (?, ?, ?)",
                (ref.artifact_id, ref.schema_version, ref.content_hash),
            )
            return ref
        schema_version = row[0]
        content_hash = row[1]
        if schema_version != ref.schema_version or content_hash != ref.content_hash:
            raise ArtifactIdentityConflict(
                f"ArtifactRef identity conflict for {ref.artifact_id!r}"
            )
        return ArtifactRef(ref.artifact_id, schema_version, content_hash)

    def resolve_artifact_ref(self, artifact_id: str) -> ArtifactRef | None:
        row = self.conn.execute(
            "SELECT artifact_id, schema_version, content_hash FROM creation_artifact_ref WHERE artifact_id = ?",
            (artifact_id,),
        ).fetchone()
        if row is None:
            return None
        return ArtifactRef(row[0], row[1], row[2])

    def create_attempt(self, attempt: ActivationAttempt) -> None:
        self._validate_attempt(attempt)
        self.register_artifact_ref(attempt.bundle_ref)
        try:
            self.conn.execute(
                "INSERT INTO canon_activation_attempt ("
                "attempt_id, project_id, attempt_key, request_digest, seed_digest, "
                "bundle_ref_artifact_id, bundle_schema_version, bundle_content_hash, "
                "manifest_hash, world_hash, version_id, pointer_content_hash, "
                "operator_identity, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    attempt.attempt_id,
                    attempt.project_id,
                    attempt.attempt_key,
                    attempt.request_digest,
                    attempt.seed_digest,
                    attempt.bundle_ref_artifact_id,
                    attempt.bundle_schema_version,
                    attempt.bundle_content_hash,
                    attempt.manifest_hash,
                    attempt.world_hash,
                    attempt.version_id,
                    attempt.pointer_content_hash,
                    attempt.operator_identity,
                    attempt.created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ActivationConflict("activation attempt identity conflicts with existing facts") from exc

    def create_prepared(self, attempt: ActivationAttempt, event: ActivationEvent) -> None:
        """Atomically write ArtifactRef, immutable attempt, and PREPARED event."""
        owns_transaction = not self.conn.in_transaction
        try:
            if owns_transaction:
                self.conn.execute("BEGIN IMMEDIATE")
            self.create_attempt(attempt)
            self.append_event(event)
            if owns_transaction:
                self.conn.commit()
        except Exception:
            if owns_transaction and self.conn.in_transaction:
                self.conn.rollback()
            raise

    def append_event(self, event: ActivationEvent) -> None:
        self._validate_event(event)
        attempt = self.get_attempt(event.attempt_id)
        if attempt is None:
            raise CanonActivationRepositoryError("activation attempt is missing")
        if attempt.project_id != event.project_id:
            raise CanonActivationRepositoryError("activation event project binding mismatch")
        try:
            self.conn.execute(
                "INSERT INTO canon_activation_event ("
                "event_id, attempt_id, project_id, phase, result, error_code, "
                "replay_envelope_json, replay_envelope_hash, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event.event_id,
                    event.attempt_id,
                    event.project_id,
                    event.phase,
                    event.result,
                    event.error_code,
                    event.replay_envelope_json,
                    event.replay_envelope_hash,
                    event.created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise CanonActivationRepositoryError("activation event violates append-only identity constraints") from exc

    def get_attempt(self, attempt_id: str) -> ActivationAttempt | None:
        row = self.conn.execute(
            "SELECT * FROM canon_activation_attempt WHERE attempt_id = ?",
            (attempt_id,),
        ).fetchone()
        return None if row is None else self._attempt_from_row(row)

    def get_attempt_by_project(self, project_id: str) -> ActivationAttempt | None:
        row = self.conn.execute(
            "SELECT * FROM canon_activation_attempt WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        return None if row is None else self._attempt_from_row(row)

    def get_attempt_by_key(self, attempt_key: str) -> ActivationAttempt | None:
        row = self.conn.execute(
            "SELECT * FROM canon_activation_attempt WHERE attempt_key = ?",
            (attempt_key,),
        ).fetchone()
        return None if row is None else self._attempt_from_row(row)

    def get_event(self, event_id: str) -> ActivationEvent | None:
        row = self.conn.execute(
            "SELECT * FROM canon_activation_event WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        return None if row is None else self._event_from_row(row)

    def get_event_by_phase(self, attempt_id: str, phase: str) -> ActivationEvent | None:
        row = self.conn.execute(
            "SELECT * FROM canon_activation_event WHERE attempt_id = ? AND phase = ?",
            (attempt_id, phase),
        ).fetchone()
        return None if row is None else self._event_from_row(row)

    def list_events(self, attempt_id: str) -> tuple[ActivationEvent, ...]:
        rows = self.conn.execute(
            "SELECT * FROM canon_activation_event WHERE attempt_id = ? ORDER BY created_at, event_id",
            (attempt_id,),
        ).fetchall()
        return tuple(self._event_from_row(row) for row in rows)

    def get_event_with_attempt(self, event_id: str) -> ActivationEventWithAttempt | None:
        row = self.conn.execute(
            "SELECT e.*, a.* FROM canon_activation_event e "
            "JOIN canon_activation_attempt a "
            "ON a.attempt_id = e.attempt_id AND a.project_id = e.project_id "
            "WHERE e.event_id = ?",
            (event_id,),
        ).fetchone()
        if row is None:
            return None
        event = self.get_event(event_id)
        if event is None:
            return None
        attempt = self.get_attempt(event.attempt_id)
        if attempt is None:
            raise CanonActivationRepositoryError("activation event join lost its attempt")
        return ActivationEventWithAttempt(event=event, attempt=attempt)

    def has_business_c4a_facts(self) -> bool:
        """A narrow evidence helper used by C4b tests."""
        for table in ("chapter_task", "canon_commit_journal", "canon_commit_receipt"):
            if self.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (table,)
            ).fetchone() is None:
                continue
            if self.conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is not None:
                return True
        return False

    @staticmethod
    def _validate_attempt(attempt: ActivationAttempt) -> None:
        for field, value in (
            ("attempt_id", attempt.attempt_id),
            ("project_id", attempt.project_id),
            ("attempt_key", attempt.attempt_key),
            ("version_id", attempt.version_id),
            ("operator_identity", attempt.operator_identity),
            ("created_at", attempt.created_at),
        ):
            _text(value, field)
        _digest(attempt.request_digest)
        _digest(attempt.seed_digest)
        _digest(attempt.bundle_content_hash)
        _digest(attempt.manifest_hash)
        _digest(attempt.world_hash)
        _digest(attempt.pointer_content_hash)
        if attempt.bundle_schema_version != 1:
            raise CanonActivationRepositoryError("unsupported bundle schema version")

    @staticmethod
    def _validate_event(event: ActivationEvent) -> None:
        if not isinstance(event.phase, str) or not isinstance(event.result, str):
            raise CanonActivationRepositoryError("activation event phase/result pairing is invalid")
        if event.phase not in _PHASES or event.result != event.phase:
            raise CanonActivationRepositoryError("activation event phase/result pairing is invalid")
        _text(event.event_id, "event_id")
        _text(event.attempt_id, "attempt_id")
        _text(event.project_id, "project_id")
        _text(event.created_at, "created_at")
        if event.phase == "PREPARED":
            if event.error_code is not None or event.replay_envelope_json is not None or event.replay_envelope_hash is not None:
                raise CanonActivationRepositoryError("PREPARED event payload is invalid")
        elif event.phase == "READY_FOR_MARKER":
            if (
                event.error_code is not None
                or not isinstance(event.replay_envelope_json, str)
                or not event.replay_envelope_json
            ):
                raise CanonActivationRepositoryError("READY_FOR_MARKER event envelope is missing")
            expected = _hash_envelope(event.replay_envelope_json)
            if event.replay_envelope_hash != expected:
                raise CanonActivationRepositoryError("READY_FOR_MARKER envelope hash mismatch")
        elif event.phase == "MANUAL_RECOVERY_REQUIRED":
            if event.error_code != "ACTIVATION_RECOVERY_REQUIRED" or event.replay_envelope_json is not None or event.replay_envelope_hash is not None:
                raise CanonActivationRepositoryError("manual recovery event payload is invalid")

    @staticmethod
    def _attempt_from_row(row: sqlite3.Row | tuple) -> ActivationAttempt:
        def value(name: str):
            try:
                return row[name]
            except (IndexError, TypeError):
                names = (
                    "attempt_id", "project_id", "attempt_key", "request_digest", "seed_digest",
                    "bundle_ref_artifact_id", "bundle_schema_version", "bundle_content_hash",
                    "manifest_hash", "world_hash", "version_id", "pointer_content_hash",
                    "operator_identity", "created_at",
                )
                return row[names.index(name)]

        return ActivationAttempt(
            attempt_id=value("attempt_id"),
            project_id=value("project_id"),
            attempt_key=value("attempt_key"),
            request_digest=value("request_digest"),
            seed_digest=value("seed_digest"),
            bundle_ref=ArtifactRef(value("bundle_ref_artifact_id"), value("bundle_schema_version"), value("bundle_content_hash")),
            version_id=value("version_id"),
            pointer_content_hash=value("pointer_content_hash"),
            operator_identity=value("operator_identity"),
            created_at=value("created_at"),
            manifest_hash=value("manifest_hash"),
            world_hash=value("world_hash"),
        )

    @staticmethod
    def _event_from_row(row: sqlite3.Row | tuple) -> ActivationEvent:
        def value(name: str):
            try:
                return row[name]
            except (IndexError, TypeError):
                names = (
                    "event_id", "attempt_id", "project_id", "phase", "result", "error_code",
                    "replay_envelope_json", "replay_envelope_hash", "created_at",
                )
                return row[names.index(name)]

        return ActivationEvent(
            event_id=value("event_id"),
            attempt_id=value("attempt_id"),
            project_id=value("project_id"),
            phase=value("phase"),
            result=value("result"),
            error_code=value("error_code"),
            replay_envelope_json=value("replay_envelope_json"),
            replay_envelope_hash=value("replay_envelope_hash"),
            created_at=value("created_at"),
        )


CanonActivationRepository = SqliteCanonActivationRepository
