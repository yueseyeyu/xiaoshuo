"""C3 consumption of a real APPROVE_CHANGESET decision into durable intent."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID, uuid4

from xiaoshuo.domain.creation import (
    SCHEMA_VERSION,
    ArtifactRef,
    AuditEvent,
    ChapterTaskStatus,
    DecisionType,
    compute_content_hash,
)
from xiaoshuo.domain.creation.hashing import canonicalize_json_value
from xiaoshuo.domain.creation.state_machine import RevisionConflict as DomainRevisionConflict
from xiaoshuo.domain.creation.state_machine import transition_task, validate_author_decision

from .canon_changeset import BundleDescriptor, BundleInspector, ChangeSetProposal, PayloadStore, _validate_bundle_identity
from .canon_commands import ApproveCanonChangesetCommand
from .canon_decision_context import CanonApproveDeliveryContext
from .canon_results import CanonChangesetResult
from .digest import (
    compute_canon_approve_request_digest,
    compute_envelope_hash,
    create_canon_result_envelope,
    result_from_canon_envelope,
)
from .errors import CreationApplicationError, IdempotencyConflict, LegacyChangesetUnbound, NotFound, UnsupportedPersistenceBoundary
from .local_author_context import LocalAuthorContext
from .operation_kind import OperationKind
from .repository import CanonCommitIntentRecord, CreationUnitOfWork, DecisionConsumptionRecord, OperationLogRecord, OperationResult
from .ports import ProjectionActivationReaderPort


IdFactory = Callable[[], UUID | str]
UnitOfWorkFactory = Callable[[], CreationUnitOfWork]


class ApproveCanonChangesetUseCase:
    """The sole C3 consumer of APPROVE_CHANGESET; it never applies files."""

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

    def approve(self, command: ApproveCanonChangesetCommand, context: CanonApproveDeliveryContext) -> CanonChangesetResult:
        if context.idempotency_key == command.task_id or context.idempotency_key == command.decision_id:
            raise UnsupportedPersistenceBoundary("delivery key must not equal task_id or decision_id")
        uow = self._open_uow()
        rolled_back = [False]
        try:
            result = self._approve_with_uow(command, context, uow, rolled_back)
        except Exception as exc:
            self._fail_close(uow, rolled_back, exc)
            raise AssertionError("unreachable")
        self._close_success(uow)
        return result

    def _approve_with_uow(self, command, context, uow, rolled_back) -> CanonChangesetResult:
        kind = OperationKind.APPROVE_CANON_CHANGESET
        digest = compute_canon_approve_request_digest(command, operation_kind=kind)
        existing = self._read_operation(uow, context.idempotency_key)
        if existing is not None:
            if existing.request_digest != digest:
                raise IdempotencyConflict("idempotency key has a different request digest")
            self._rollback(uow, rolled_back)
            return result_from_canon_envelope(existing.result_envelope_json, expected_task_id=command.task_id, expected_kind=kind)

        task = self._get_task(uow, command.task_id)
        decision = self._get_decision(uow, command.decision_id)
        if task.pending_changeset_ref is None:
            raise UnsupportedPersistenceBoundary("APPROVE_CHANGESET requires pending_changeset_ref")
        proposal = self._read_proposal(task.pending_changeset_ref)
        if proposal.schema_version == 1:
            raise LegacyChangesetUnbound("v1 ChangeSet is not bound to project activation identity")
        if self._activation_reader is None:
            raise LegacyChangesetUnbound("APPROVE_CHANGESET requires a project-bound activation reader")
        try:
            base_identity = self._activation_reader.read_for_project(task.project_id)
        except Exception as exc:
            raise UnsupportedPersistenceBoundary("project activation identity is unavailable") from exc
        _validate_bundle_identity(base_identity, expected_project_id=task.project_id)
        if (
            proposal.base_project_id != base_identity.project_id
            or proposal.base_version_id != base_identity.version_id
            or proposal.base_bundle_ref != base_identity.bundle_ref
            or proposal.base_bundle_content_hash != base_identity.bundle_content_hash
            or proposal.base_manifest_hash != base_identity.manifest_hash
            or proposal.base_world_hash != base_identity.world_hash
        ):
            raise UnsupportedPersistenceBoundary("ChangeSet base identity no longer matches activation")
        descriptor = self._read_and_inspect_bundle(proposal.target_bundle_ref)
        self._validate_payload_bindings(task, proposal, descriptor)
        self._validate_decision(command, task, decision)
        self._assert_unconsumed(uow, decision.decision_id)
        try:
            transitioned = transition_task(task, ChapterTaskStatus.COMMITTING, command.expected_revision)
        except DomainRevisionConflict:
            raise
        except Exception as exc:
            raise UnsupportedPersistenceBoundary("Canon intent state transition rejected") from exc
        self._assert_role_refs_unchanged(task, transitioned)

        operation_id, event_id, consumption_id, journal_id = (str(self._id_factory()) for _ in range(4))
        now = datetime.now(timezone.utc)
        result = CanonChangesetResult(
            task_id=task.task_id,
            aggregate_revision=transitioned.aggregate_revision,
            status=transitioned.status,
            changeset_ref=task.pending_changeset_ref,
            target_bundle_ref=proposal.target_bundle_ref,
            base_manifest_hash=proposal.base_manifest_hash,
            target_manifest_hash=proposal.target_manifest_hash,
            journal_id=journal_id,
        )
        envelope = create_canon_result_envelope(result, operation_kind=kind, original_operation_id=operation_id, audit_event_ids=(event_id,))
        timestamp = now.isoformat(timespec="microseconds")
        operation = OperationLogRecord(operation_id, context.idempotency_key, digest, envelope, compute_envelope_hash(envelope), timestamp)
        event = AuditEvent(
            event_id, SCHEMA_VERSION, task.task_id, task.project_id,
            "CANON_COMMIT_INTENT_CREATED", decision.source,
            task.aggregate_revision, transitioned.aggregate_revision,
            _object_refs(transitioned), operation_id, now,
        )
        consumption = DecisionConsumptionRecord(consumption_id, decision.decision_id, operation_id, task.task_id, transitioned.aggregate_revision, timestamp)
        intent = CanonCommitIntentRecord(
            journal_id=journal_id, task_id=task.task_id, operation_id=operation_id,
            decision_id=decision.decision_id, changeset_ref=task.pending_changeset_ref,
            target_bundle_ref=proposal.target_bundle_ref,
            base_manifest_hash=proposal.base_manifest_hash,
            target_manifest_hash=proposal.target_manifest_hash, created_at=timestamp,
            base_bundle_ref=proposal.base_bundle_ref,
            base_bundle_content_hash=proposal.base_bundle_content_hash,
            target_bundle_content_hash=proposal.target_bundle_ref.content_hash,
            base_world_hash=proposal.base_world_hash,
            target_world_hash=proposal.target_world_hash,
            canonical_bundle_schema_version=proposal.bundle_schema_version,
        )

        outcome = uow.operations.create_or_replay_complete(operation)
        if outcome.status is OperationResult.REPLAY:
            self._rollback(uow, rolled_back)
            return result_from_canon_envelope(_require_replay(outcome.replay_envelope_json), expected_task_id=command.task_id, expected_kind=kind)
        if outcome.status is OperationResult.CONFLICT:
            raise IdempotencyConflict("idempotency key has a different request digest")
        uow.audit.add_event(event)
        uow.decisions.add_consumption(consumption)
        uow.canon.create_intent(intent, transitioned, expected_revision=command.expected_revision)
        uow.commit()
        return result

    def _validate_decision(self, command, task, decision) -> None:
        local_source = self._author_context.author_source()
        if decision.author_id != self._author_context.author_id or decision.source != local_source:
            raise UnsupportedPersistenceBoundary("decision does not belong to the controlled local author")
        try:
            expected_hash = compute_content_hash(canonicalize_json_value(decision.content_payload()))
        except Exception as exc:
            raise UnsupportedPersistenceBoundary("decision content is invalid") from exc
        if expected_hash != decision.content_hash:
            raise UnsupportedPersistenceBoundary("decision content hash does not revalidate")
        if task.status is not ChapterTaskStatus.CHANGESET_APPROVAL_PENDING:
            raise UnsupportedPersistenceBoundary("Task is not awaiting ChangeSet approval")
        if task.aggregate_revision != command.expected_revision:
            raise DomainRevisionConflict("approve expected revision does not match Task")
        try:
            validate_author_decision(
                decision,
                expected_type=DecisionType.APPROVE_CHANGESET,
                expected_target_ref=task.pending_changeset_ref,
                current_task_revision=task.aggregate_revision,
            )
        except Exception as exc:
            raise UnsupportedPersistenceBoundary("APPROVE_CHANGESET validation failed") from exc

    @staticmethod
    def _assert_role_refs_unchanged(before, after) -> None:
        fields = (
            "creative_intent_ref", "confirmed_plan_ref", "current_author_draft_ref",
            "review_target_draft_ref", "adopted_draft_ref", "latest_review_ref", "pending_changeset_ref",
        )
        if any(getattr(before, field) != getattr(after, field) for field in fields):
            raise UnsupportedPersistenceBoundary("Canon approval must not mutate Task role ArtifactRefs")

    @staticmethod
    def _validate_payload_bindings(task, proposal, descriptor) -> None:
        if proposal.task_id != task.task_id or proposal.prepared_task_revision != task.aggregate_revision:
            raise UnsupportedPersistenceBoundary("ChangeSet payload does not bind to the current Task revision")
        if proposal.adopted_draft_ref != task.adopted_draft_ref:
            raise UnsupportedPersistenceBoundary("ChangeSet payload does not bind to the current adopted draft")
        if (
            proposal.target_bundle_ref.content_hash != descriptor.content_hash
            or proposal.target_manifest_hash != descriptor.manifest_hash
            or proposal.target_world_hash != descriptor.world_hash
            or not _is_hash(descriptor.world_hash)
            or proposal.target_bundle_ref.schema_version != proposal.bundle_schema_version
            or type(proposal.bundle_schema_version) is not int
            or proposal.bundle_schema_version != SCHEMA_VERSION
        ):
            raise UnsupportedPersistenceBoundary("ChangeSet target bundle does not revalidate")

    def _read_proposal(self, ref: ArtifactRef) -> ChangeSetProposal:
        try:
            data = self._payload_store.read(ref.content_hash)
        except Exception as exc:
            raise CreationApplicationError("Canon ChangeSet payload read failed") from exc
        if _sha(data) != ref.content_hash:
            raise UnsupportedPersistenceBoundary("ChangeSet payload hash mismatch")
        return ChangeSetProposal.from_bytes(data)

    def _read_and_inspect_bundle(self, ref: ArtifactRef) -> BundleDescriptor:
        try:
            data = self._payload_store.read(ref.content_hash)
            descriptor = self._bundle_inspector.inspect(data)
        except UnsupportedPersistenceBoundary:
            raise
        except Exception as exc:
            raise CreationApplicationError("Canon bundle payload read failed") from exc
        if not isinstance(descriptor, BundleDescriptor) or descriptor.content_hash != ref.content_hash:
            raise UnsupportedPersistenceBoundary("target bundle descriptor does not match its payload ref")
        return descriptor

    @staticmethod
    def _open_uow_factory_error(exc):
        raise CreationApplicationError("creation persistence read failed") from exc

    def _open_uow(self):
        try:
            return self._uow_factory()
        except CreationApplicationError:
            raise
        except Exception as exc:
            self._open_uow_factory_error(exc)

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
    def _get_decision(uow, decision_id):
        try:
            decision = uow.decisions.get(decision_id)
        except CreationApplicationError:
            raise
        except Exception as exc:
            raise CreationApplicationError("creation persistence read failed") from exc
        if decision is None:
            raise NotFound(f"decision {decision_id!r} not found")
        return decision

    @staticmethod
    def _read_operation(uow, key):
        try:
            return uow.operations.get_by_idempotency_key(key)
        except CreationApplicationError:
            raise
        except Exception as exc:
            raise CreationApplicationError("creation persistence read failed") from exc

    @staticmethod
    def _assert_unconsumed(uow, decision_id):
        try:
            consumption = uow.decisions.get_consumption_by_decision_id(decision_id)
        except CreationApplicationError:
            raise
        except Exception as exc:
            raise CreationApplicationError("creation persistence read failed") from exc
        if consumption is not None:
            raise UnsupportedPersistenceBoundary("AuthorDecision has already been consumed")

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


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _is_hash(value: object) -> bool:
    return isinstance(value, str) and len(value) == 71 and value.startswith("sha256:") and all(ch in "0123456789abcdef" for ch in value[7:])


def _object_refs(task) -> tuple[ArtifactRef, ...]:
    refs = (task.creative_intent_ref, task.confirmed_plan_ref, task.current_author_draft_ref, task.review_target_draft_ref, task.adopted_draft_ref, task.latest_review_ref, task.pending_changeset_ref)
    if any(ref is None for ref in refs):
        raise UnsupportedPersistenceBoundary("Canon audit requires all seven Task role references")
    return tuple(refs)  # type: ignore[return-value]


def _require_replay(value: str | None) -> str:
    if not value:
        raise CreationApplicationError("REPLAY outcome did not include the original envelope")
    return value
