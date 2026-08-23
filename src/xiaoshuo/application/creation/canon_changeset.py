"""C3 preparation of an immutable ChangeSet proposal.

The use case does not inspect or write the live Canon projection.  It writes
only content-addressed proposal/bundle payloads, then records the proposal in
the normal pre-approval Task state under one SQLite UoW.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID, uuid4

from xiaoshuo.domain.creation import (
    SCHEMA_VERSION,
    ArtifactRef,
    AuditEvent,
    ChapterTaskStatus,
)
from xiaoshuo.domain.creation.state_machine import RevisionConflict as DomainRevisionConflict
from xiaoshuo.domain.creation.state_machine import transition_task

from .canon_commands import PrepareCanonChangesetCommand
from .canon_decision_context import CanonPrepareDeliveryContext
from .canon_results import CanonChangesetResult
from .digest import (
    compute_canon_prepare_request_digest,
    compute_envelope_hash,
    create_canon_result_envelope,
    result_from_canon_envelope,
)
from .errors import CreationApplicationError, IdempotencyConflict, LegacyChangesetUnbound, NotFound, UnsupportedPersistenceBoundary
from .local_author_context import LocalAuthorContext
from .operation_kind import OperationKind
from .ports import CanonBundleDescriptor, CanonBundleInspectorPort, ImmutablePayloadStorePort, ProjectionActivationReaderPort
from .repository import CreationUnitOfWork, OperationLogRecord, OperationResult


IdFactory = Callable[[], UUID | str]
UnitOfWorkFactory = Callable[[], CreationUnitOfWork]


BundleDescriptor = CanonBundleDescriptor
BundleInspector = CanonBundleInspectorPort
PayloadStore = ImmutablePayloadStorePort


@dataclass(frozen=True, slots=True)
class ChangeSetProposal:
    task_id: str
    prepared_task_revision: int
    adopted_draft_ref: ArtifactRef
    target_bundle_ref: ArtifactRef
    base_manifest_hash: str
    target_manifest_hash: str
    schema_version: int = 1
    base_bundle_ref: ArtifactRef | None = None
    base_bundle_content_hash: str | None = None
    base_world_hash: str | None = None
    base_project_id: str | None = None
    base_version_id: str | None = None
    bundle_schema_version: int = 1
    target_world_hash: str | None = None

    def to_bytes(self) -> bytes:
        payload = {
                "adopted_draft_ref": _ref_payload(self.adopted_draft_ref),
                "base_manifest_hash": self.base_manifest_hash,
                "prepared_task_revision": self.prepared_task_revision,
                "schema_version": self.schema_version,
                "target_bundle_ref": _ref_payload(self.target_bundle_ref),
                "target_manifest_hash": self.target_manifest_hash,
                "task_id": self.task_id,
        }
        if self.schema_version == 2:
            payload.update({
                "base_bundle_content_hash": self.base_bundle_content_hash,
                "base_bundle_ref": _ref_payload(self.base_bundle_ref) if self.base_bundle_ref else None,
                "base_project_id": self.base_project_id,
                "base_version_id": self.base_version_id,
                "base_world_hash": self.base_world_hash,
                "bundle_schema_version": self.bundle_schema_version,
                "target_world_hash": self.target_world_hash,
            })
        return _canonical_bytes(payload)

    @classmethod
    def from_bytes(cls, data: bytes) -> "ChangeSetProposal":
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UnsupportedPersistenceBoundary("ChangeSet payload is invalid") from exc
        base_expected = {
            "adopted_draft_ref", "base_manifest_hash", "prepared_task_revision",
            "schema_version", "target_bundle_ref", "target_manifest_hash", "task_id",
        }
        if not isinstance(payload, dict) or _canonical_bytes(payload) != data or not base_expected.issubset(payload):
            raise UnsupportedPersistenceBoundary("ChangeSet payload is not canonical")
        try:
            schema = payload["schema_version"]
            if type(schema) is not int or schema not in (1, 2) or type(payload["prepared_task_revision"]) is not int or payload["prepared_task_revision"] < 0:
                raise ValueError
            expected = base_expected if schema == 1 else base_expected | {
                "base_bundle_content_hash", "base_bundle_ref", "base_project_id",
                "base_version_id", "base_world_hash", "bundle_schema_version",
                "target_world_hash",
            }
            if set(payload) != expected:
                raise ValueError
            result = cls(
                task_id=_require_text(payload["task_id"], "task_id"),
                prepared_task_revision=payload["prepared_task_revision"],
                adopted_draft_ref=_ref_from_payload(payload["adopted_draft_ref"]),
                target_bundle_ref=_ref_from_payload(payload["target_bundle_ref"]),
                base_manifest_hash=_require_hash(payload["base_manifest_hash"]),
                target_manifest_hash=_require_hash(payload["target_manifest_hash"]),
                schema_version=schema,
            )
            if schema == 2:
                if payload["base_bundle_ref"] is None:
                    raise ValueError
                result = replace(result,
                    base_bundle_ref=_ref_from_payload(payload["base_bundle_ref"]),
                    base_bundle_content_hash=_require_hash(payload["base_bundle_content_hash"]),
                    base_world_hash=_require_hash(payload["base_world_hash"]),
                    base_project_id=_require_text(payload["base_project_id"], "base_project_id"),
                    base_version_id=_require_text(payload["base_version_id"], "base_version_id"),
                    bundle_schema_version=payload["bundle_schema_version"],
                    target_world_hash=_require_hash(payload["target_world_hash"]),
                )
                if (
                    type(result.bundle_schema_version) is not int
                    or result.bundle_schema_version != SCHEMA_VERSION
                    or type(result.base_bundle_ref.schema_version) is not int
                    or type(result.target_bundle_ref.schema_version) is not int
                    or result.base_bundle_ref.schema_version != result.bundle_schema_version
                    or result.target_bundle_ref.schema_version != result.bundle_schema_version
                    or result.base_bundle_content_hash != result.base_bundle_ref.content_hash
                ):
                    raise ValueError
            return result
        except (KeyError, TypeError, ValueError) as exc:
            raise UnsupportedPersistenceBoundary("ChangeSet payload fields are invalid") from exc


class PrepareCanonChangesetUseCase:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        author_context: LocalAuthorContext,
        payload_store: PayloadStore,
        bundle_inspector: BundleInspector,
        *,
        id_factory: IdFactory = uuid4,
        activation_reader: ProjectionActivationReaderPort | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._author_context = author_context
        self._payload_store = payload_store
        self._bundle_inspector = bundle_inspector
        self._id_factory = id_factory
        self._activation_reader = activation_reader

    def prepare(self, command: PrepareCanonChangesetCommand, context: CanonPrepareDeliveryContext) -> CanonChangesetResult:
        if context.idempotency_key == command.task_id:
            raise UnsupportedPersistenceBoundary("delivery key must not equal task_id")
        uow = self._open_uow()
        rolled_back = [False]
        try:
            result = self._prepare_with_uow(command, context, uow, rolled_back)
        except Exception as exc:
            self._fail_close(uow, rolled_back, exc)
            raise AssertionError("unreachable")
        self._close_success(uow)
        return result

    def _prepare_with_uow(self, command, context, uow, rolled_back) -> CanonChangesetResult:
        kind = OperationKind.PREPARE_CANON_CHANGESET
        digest = compute_canon_prepare_request_digest(
            command,
            "sha256:" + hashlib.sha256(command.target_bundle_bytes).hexdigest(),
            kind,
        )
        existing = self._read_operation(uow, context.idempotency_key)
        if existing is not None:
            if existing.request_digest != digest:
                raise IdempotencyConflict("idempotency key has a different request digest")
            self._rollback(uow, rolled_back)
            return result_from_canon_envelope(existing.result_envelope_json, expected_task_id=command.task_id, expected_kind=kind)

        if command.command_schema_version == 1:
            raise LegacyChangesetUnbound("v1 ChangeSet has no bound historical operation")

        task = self._get_task(uow, command.task_id)
        if command.command_schema_version == 2:
            if self._activation_reader is None:
                raise LegacyChangesetUnbound("v2 Prepare requires a project-bound activation reader")
            try:
                base_identity = self._activation_reader.read_for_project(task.project_id)
            except Exception as exc:
                raise UnsupportedPersistenceBoundary("project activation identity is unavailable") from exc
            _validate_bundle_identity(base_identity, expected_project_id=task.project_id)
        else:
            base_identity = None
        descriptor = self._inspect(command.target_bundle_bytes)
        if command.command_schema_version == 2 and descriptor.world_hash is None:
            raise UnsupportedPersistenceBoundary("v2 target bundle identity is incomplete")
        if task.status is not ChapterTaskStatus.CHANGESET_PREPARING or task.adopted_draft_ref is None or task.pending_changeset_ref is not None:
            raise UnsupportedPersistenceBoundary("Task is not eligible for ChangeSet preparation")
        if task.aggregate_revision != command.expected_revision:
            raise DomainRevisionConflict("prepare expected revision does not match Task")

        bundle_digest = self._put_payload(command.target_bundle_bytes)
        if bundle_digest != descriptor.content_hash:
            raise UnsupportedPersistenceBoundary("bundle payload digest does not match inspected bundle")
        bundle_ref = ArtifactRef(str(self._id_factory()), SCHEMA_VERSION, bundle_digest)
        transitioned = transition_task(task, ChapterTaskStatus.CHANGESET_APPROVAL_PENDING, command.expected_revision)
        proposal = ChangeSetProposal(
            task_id=task.task_id,
            prepared_task_revision=transitioned.aggregate_revision,
            adopted_draft_ref=task.adopted_draft_ref,
            target_bundle_ref=bundle_ref,
            base_manifest_hash=base_identity.manifest_hash if base_identity else command.base_manifest_hash,
            target_manifest_hash=descriptor.manifest_hash,
            schema_version=2 if command.command_schema_version == 2 else 1,
            base_bundle_ref=base_identity.bundle_ref if base_identity else None,
            base_bundle_content_hash=base_identity.bundle_content_hash if base_identity else None,
            base_world_hash=base_identity.world_hash if base_identity else None,
            base_project_id=base_identity.project_id if base_identity else None,
            base_version_id=base_identity.version_id if base_identity else None,
            bundle_schema_version=base_identity.schema_version if base_identity else 1,
            target_world_hash=descriptor.world_hash,
        )
        changeset_digest = self._put_payload(proposal.to_bytes())
        changeset_ref = ArtifactRef(str(self._id_factory()), SCHEMA_VERSION, changeset_digest)
        transitioned = replace(transitioned, pending_changeset_ref=changeset_ref)
        operation_id, event_id = str(self._id_factory()), str(self._id_factory())
        now = datetime.now(timezone.utc)
        result = CanonChangesetResult(task.task_id, transitioned.aggregate_revision, transitioned.status, changeset_ref, bundle_ref, proposal.base_manifest_hash, descriptor.manifest_hash)
        envelope = create_canon_result_envelope(result, operation_kind=kind, original_operation_id=operation_id, audit_event_ids=(event_id,))
        record = OperationLogRecord(operation_id, context.idempotency_key, digest, envelope, compute_envelope_hash(envelope), now.isoformat(timespec="microseconds"))
        event = AuditEvent(event_id, SCHEMA_VERSION, task.task_id, task.project_id, "CANON_CHANGESET_PREPARED", self._author_context.author_source(), task.aggregate_revision, transitioned.aggregate_revision, _object_refs(transitioned), operation_id, now)
        outcome = uow.operations.create_or_replay_complete(record)
        if outcome.status is OperationResult.REPLAY:
            self._rollback(uow, rolled_back)
            return result_from_canon_envelope(_require_replay(outcome.replay_envelope_json), expected_task_id=command.task_id, expected_kind=kind)
        if outcome.status is OperationResult.CONFLICT:
            raise IdempotencyConflict("idempotency key has a different request digest")
        uow.tasks.replace(transitioned, expected_revision=command.expected_revision)
        uow.audit.add_event(event)
        uow.commit()
        return result

    def _inspect(self, data: bytes) -> BundleDescriptor:
        try:
            value = self._bundle_inspector.inspect(data)
        except Exception as exc:
            raise UnsupportedPersistenceBoundary("target Canon bundle is invalid") from exc
        if not isinstance(value, BundleDescriptor) or not _is_hash(value.content_hash) or not _is_hash(value.manifest_hash):
            raise UnsupportedPersistenceBoundary("bundle inspector returned an invalid descriptor")
        if value.world_hash is not None and not _is_hash(value.world_hash):
            raise UnsupportedPersistenceBoundary("bundle inspector returned an invalid world hash")
        return value

    def _put_payload(self, data: bytes) -> str:
        try:
            digest = self._payload_store.put(data)
        except Exception as exc:
            raise CreationApplicationError("Canon payload persistence failed") from exc
        if not _is_hash(digest):
            raise CreationApplicationError("payload store returned an invalid digest")
        return digest

    def _open_uow(self):
        try:
            return self._uow_factory()
        except CreationApplicationError:
            raise
        except Exception as exc:
            raise CreationApplicationError("creation persistence read failed") from exc

    @staticmethod
    def _read_operation(uow, key):
        try:
            return uow.operations.get_by_idempotency_key(key)
        except CreationApplicationError:
            raise
        except Exception as exc:
            raise CreationApplicationError("creation persistence read failed") from exc

    @staticmethod
    def _get_task(uow, task_id):
        try:
            task = uow.tasks.get(task_id)
        except CreationApplicationError:
            raise
        except Exception as exc:
            raise CreationApplicationError("creation persistence read failed") from exc
        if task is None:
            raise NotFound(f"task {task_id!r} not found")
        return task

    @staticmethod
    def _rollback(uow, marker):
        marker[0] = True
        try:
            uow.rollback()
        except Exception as exc:
            raise CreationApplicationError("creation rollback failed") from exc

    def _fail_close(self, uow, marker, original):
        if not marker[0]:
            try:
                self._rollback(uow, marker)
            except CreationApplicationError as rollback_error:
                try:
                    uow.close()
                except Exception as close_exc:
                    raise rollback_error from close_exc
                raise
        try:
            uow.close()
        except Exception as close_exc:
            if isinstance(original, CreationApplicationError):
                raise original from close_exc
            raise CreationApplicationError("creation persistence failed") from close_exc
        raise original

    @staticmethod
    def _close_success(uow):
        try:
            uow.close()
        except Exception as exc:
            raise CreationApplicationError("creation persistence close failed") from exc


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _ref_payload(ref: ArtifactRef) -> dict[str, object]:
    return {"artifact_id": ref.artifact_id, "content_hash": ref.content_hash, "schema_version": ref.schema_version}


def _ref_from_payload(value: object) -> ArtifactRef:
    if not isinstance(value, dict) or set(value) != {"artifact_id", "content_hash", "schema_version"}:
        raise ValueError
    return ArtifactRef(value["artifact_id"], value["schema_version"], value["content_hash"])


def _require_text(value: object, _name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError
    return value


def _is_hash(value: object) -> bool:
    return isinstance(value, str) and len(value) == 71 and value.startswith("sha256:") and all(ch in "0123456789abcdef" for ch in value[7:])


def _require_hash(value: object) -> str:
    if not _is_hash(value):
        raise ValueError
    return value


def _validate_bundle_identity(identity: object, *, expected_project_id: str) -> None:
    try:
        project_id = identity.project_id
        version_id = identity.version_id
        schema_version = identity.schema_version
        bundle_ref = identity.bundle_ref
        bundle_content_hash = identity.bundle_content_hash
        manifest_hash = identity.manifest_hash
        world_hash = identity.world_hash
    except AttributeError as exc:
        raise UnsupportedPersistenceBoundary("activation identity is invalid") from exc
    if project_id != expected_project_id or not _require_text_value(version_id):
        raise UnsupportedPersistenceBoundary("activation identity is not project-bound")
    if type(schema_version) is not int or schema_version != SCHEMA_VERSION:
        raise UnsupportedPersistenceBoundary("activation identity schema is unsupported")
    if not isinstance(bundle_ref, ArtifactRef):
        raise UnsupportedPersistenceBoundary("activation bundle ref is invalid")
    if bundle_ref.schema_version != schema_version:
        raise UnsupportedPersistenceBoundary("activation bundle ref schema is inconsistent")
    if not _is_hash(bundle_content_hash) or not _is_hash(manifest_hash) or not _is_hash(world_hash):
        raise UnsupportedPersistenceBoundary("activation bundle identity is incomplete")
    if bundle_ref.content_hash != bundle_content_hash:
        raise UnsupportedPersistenceBoundary("activation bundle content identity is inconsistent")


def _require_text_value(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _object_refs(task) -> tuple[ArtifactRef, ...]:
    refs = (task.creative_intent_ref, task.confirmed_plan_ref, task.current_author_draft_ref, task.review_target_draft_ref, task.adopted_draft_ref, task.latest_review_ref, task.pending_changeset_ref)
    if any(ref is None for ref in refs):
        raise UnsupportedPersistenceBoundary("Canon audit requires all seven Task role references")
    return tuple(refs)  # type: ignore[return-value]


def _require_replay(value: str | None) -> str:
    if not value:
        raise CreationApplicationError("REPLAY outcome did not include the original envelope")
    return value
