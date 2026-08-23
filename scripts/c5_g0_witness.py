"""Controlled G0-C bootstrap and two-phase witness orchestration.

This script is an explicit local witness entry point, not a service, API, or
production runner.  It calls typed composition/application boundaries and
never opens SQLite or manipulates Canon files itself.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from xiaoshuo.application.creation.author_decision import CreateAuthorDecisionCommand
from xiaoshuo.application.creation.author_decision_transition import ConsumeAuthorDecisionCommand
from xiaoshuo.application.creation.authoring_artifact import (
    AUTHORING_ARTIFACT_SCHEMA_VERSION,
    AuthoringArtifactEnvelope,
    AuthoringArtifactKind,
    parse_authoring_artifact_envelope,
    serialize_authoring_artifact_envelope,
)
from xiaoshuo.application.creation.authoring_artifact_context import (
    AuthoringArtifactSubmissionContext,
    DraftReviewSubmissionContext,
)
from xiaoshuo.application.creation.canon_apply import ApplyCanonCommitUseCase, CanonApplyCommand
from xiaoshuo.application.creation.canon_apply_context import CanonApplyDeliveryContext
from xiaoshuo.application.creation.canon_commands import (
    ApproveCanonChangesetCommand,
    PrepareCanonChangesetCommand,
)
from xiaoshuo.application.creation.canon_decision_context import (
    CanonApproveDeliveryContext,
    CanonPrepareDeliveryContext,
)
from xiaoshuo.application.creation.canon_activation import CanonActivationRequest
from xiaoshuo.application.creation.commands import (
    CreateChapterTaskCommand,
    SubmitAuthoringArtifactCommand,
    SubmitDraftForReviewCommand,
)
from xiaoshuo.application.creation.decision_creation_context import DecisionCreationContext
from xiaoshuo.application.creation.errors import CreationApplicationError, UnsupportedPersistenceBoundary
from xiaoshuo.application.creation.plan_preparation import (
    PlanPreparationDeliveryContext,
    PreparePlanForApprovalCommand,
)
from xiaoshuo.application.creation.transition_context import TransitionOperationContext
from xiaoshuo.domain.creation import ArtifactRef, ChapterTaskStatus, DecisionType
from xiaoshuo.infrastructure.canon.c5_g0_composition import (
    C5G0Composition,
    C5G0BootstrapResult,
    load_c5_g0_composition,
)
from xiaoshuo.infrastructure.persistence.sqlite.c5_g0_activation_state_verifier import (
    C5G0ActivationCleanEvidence,
    C5G0RuntimeCensusStatus,
)


@dataclass(frozen=True, slots=True)
class G0CKeys:
    activation_key: str
    plan_key: str
    confirm_plan_key: str
    draft_key: str
    review_key: str
    adopt_key: str
    prepare_changeset_key: str
    approve_changeset_key: str
    apply_key: str


@dataclass(frozen=True, slots=True)
class G0CInput:
    project_id: str
    task_id: str
    chapter_number: int
    keys: G0CKeys
    creative_intent_bytes: bytes
    plan_bytes: bytes
    draft_bytes: bytes
    review_template_bytes: bytes | None = None
    target_bundle_bytes: bytes | None = None


@dataclass(frozen=True, slots=True)
class BootstrapOutcome:
    status: str
    attempt_key: str
    request_digest: str
    activation: C5G0BootstrapResult
    evidence: C5G0ActivationCleanEvidence


@dataclass(frozen=True, slots=True)
class PhaseAOutcome:
    task_id: str
    task_revision: int
    draft_ref: object


@dataclass(frozen=True, slots=True)
class DerivedReviewEvidence:
    source: str
    canonical_bytes: bytes = field(repr=False)
    reviewed_draft_ref: ArtifactRef
    task_revision: int
    byte_length: int
    sha256: str
    parser_readback: bool
    serializer_readback: bool
    canonical_equal: bool


@dataclass(frozen=True, slots=True)
class PhaseBOutcome:
    task_id: str
    task_revision: int
    status: ChapterTaskStatus
    receipt_ref: object | None
    derived_review: DerivedReviewEvidence


class C5G0WitnessRunner:
    """Run only an explicitly requested bootstrap or phase continuation."""

    def __init__(self, composition: C5G0Composition | Any | None = None) -> None:
        self._composition = composition or load_c5_g0_composition()

    def bootstrap(self, *, project_id: str, activation_key: str) -> BootstrapOutcome:
        attempt_key, request_digest = derive_activation_identity(project_id, activation_key)
        runtime = self._composition.runtime
        census = self._composition.classify_runtime(
            project_id=project_id,
            attempt_key=attempt_key,
            request_digest=request_digest,
        )
        if census.status in {
            C5G0RuntimeCensusStatus.INITIALIZED_EMPTY,
            C5G0RuntimeCensusStatus.RECOVERY_ASSESSED_INITIALIZED_EMPTY_COMPATIBLE,
        }:
            fresh_gate = self._composition.verify_fresh_gate(
                project_id=project_id,
                attempt_key=attempt_key,
                request_digest=request_digest,
            )
            if fresh_gate.status is not census.status or not fresh_gate.zero_write:
                raise UnsupportedPersistenceBoundary("fresh gate evidence is not authoritative")
            # Only the original initialized-empty branch may call the legacy
            # G0-A verifier.  Recovery-assessed state has sidecar-compatible
            # durable facts and must never re-enter that old contract.
            if census.status is C5G0RuntimeCensusStatus.INITIALIZED_EMPTY:
                runtime.verify_initialized_empty()
            activation = self._composition.bootstrap_c4b(
                project_id=project_id,
                attempt_key=attempt_key,
                request_digest=request_digest,
            )
            if activation.status != "ACTIVATED":
                raise UnsupportedPersistenceBoundary("fresh G0-C bootstrap did not activate")
            status = "C4B_ACTIVATED_CLEAN"
        elif census.status is C5G0RuntimeCensusStatus.C4B_ACTIVATED_CLEAN:
            activation = self._composition.replay_c4b(
                project_id=project_id,
                attempt_key=attempt_key,
                request_digest=request_digest,
            )
            evidence = self._composition.verify_c4b_clean(
                project_id=project_id,
                attempt_key=attempt_key,
                request_digest=request_digest,
            )
            status = "BOOTSTRAP_REPLAY_ONLY"
            return BootstrapOutcome(status, attempt_key, request_digest, activation, evidence)
        elif census.status is C5G0RuntimeCensusStatus.UNPROVISIONED_NO_RUNTIME:
            raise UnsupportedPersistenceBoundary("NO_EXECUTABLE_WITNESS_BRANCH")
        elif census.status is C5G0RuntimeCensusStatus.COMPLETED_GRAPH:
            raise UnsupportedPersistenceBoundary("COMPLETED_GRAPH_REPLAY_ONLY")
        else:
            raise UnsupportedPersistenceBoundary(
                f"G0-C runtime census rejected branch: {census.status.value}"
            )

        evidence = self._composition.verify_c4b_clean(
            project_id=project_id,
            attempt_key=attempt_key,
            request_digest=request_digest,
        )
        return BootstrapOutcome(status, attempt_key, request_digest, activation, evidence)

    def verify_completed_graph(
        self,
        *,
        project_id: str,
        task_id: str,
        activation_key: str,
    ):
        """Read and return a completed Task graph without re-entering G0-C."""

        attempt_key, request_digest = derive_activation_identity(project_id, activation_key)
        return self._composition.verify_completed_graph(
            project_id=project_id,
            task_id=task_id,
            attempt_key=attempt_key,
            request_digest=request_digest,
        )

    def replay_completed_graph(
        self,
        *,
        project_id: str,
        task_id: str,
        activation_key: str,
    ):
        """Explicit alias for the read-only completed-graph replay contract."""

        return self.verify_completed_graph(
            project_id=project_id,
            task_id=task_id,
            activation_key=activation_key,
        )

    def run_phase_a(
        self,
        witness: G0CInput,
        *,
        clean_evidence: C5G0ActivationCleanEvidence | None = None,
    ) -> PhaseAOutcome:
        attempt_key, request_digest = derive_activation_identity(
            witness.project_id, witness.keys.activation_key
        )
        authoritative_evidence = self._composition.verify_c4b_clean(
            project_id=witness.project_id,
            attempt_key=attempt_key,
            request_digest=request_digest,
        )
        _require_clean_gate(authoritative_evidence)
        if clean_evidence is not None and clean_evidence != authoritative_evidence:
            raise UnsupportedPersistenceBoundary(
                "caller clean evidence does not match composition-owned evidence"
            )
        _validate_artifact(witness.creative_intent_bytes, AuthoringArtifactKind.CREATIVE_INTENT, witness)
        _validate_artifact(witness.plan_bytes, AuthoringArtifactKind.PLAN, witness)
        _validate_artifact(witness.draft_bytes, AuthoringArtifactKind.DRAFT, witness)

        with self._composition.open_application_scope() as app:
            intent_ref = app.persist_creative_intent(witness.creative_intent_bytes)
            created = app.create_task.create(
                CreateChapterTaskCommand(
                    task_id=witness.task_id,
                    project_id=witness.project_id,
                    chapter_number=witness.chapter_number,
                    initial_status=ChapterTaskStatus.PLAN_PREPARING,
                    creative_intent_ref=intent_ref,
                )
            )
            prepared = app.prepare_plan.prepare(
                PreparePlanForApprovalCommand(
                    task_id=witness.task_id,
                    expected_revision=created.aggregate_revision,
                    envelope_bytes=witness.plan_bytes,
                ),
                PlanPreparationDeliveryContext(witness.keys.plan_key),
            )
            decision = app.create_decision.create(
                CreateAuthorDecisionCommand(
                    task_id=witness.task_id,
                    decision_type=DecisionType.CONFIRM_PLAN,
                    target_ref=prepared.plan_ref,
                    based_on_task_revision=prepared.aggregate_revision,
                ),
                DecisionCreationContext(witness.keys.confirm_plan_key),
            )
            drafting = app.consume_decision.consume(
                ConsumeAuthorDecisionCommand(
                    task_id=witness.task_id,
                    decision_id=decision.decision_id,
                    expected_revision=prepared.aggregate_revision,
                ),
                TransitionOperationContext(witness.keys.confirm_plan_key + ":consume"),
            )
            draft = app.submit_draft.submit(
                SubmitAuthoringArtifactCommand(
                    task_id=witness.task_id,
                    expected_revision=drafting.aggregate_revision,
                    envelope_bytes=witness.draft_bytes,
                ),
                AuthoringArtifactSubmissionContext(witness.keys.draft_key),
            )
            return PhaseAOutcome(witness.task_id, draft.aggregate_revision, draft.artifact_ref)

    def run_phase_b(
        self,
        witness: G0CInput,
        *,
        phase_a: PhaseAOutcome,
    ) -> PhaseBOutcome:
        if witness.review_template_bytes is None or witness.target_bundle_bytes is None:
            raise UnsupportedPersistenceBoundary(
                "Phase B requires REVIEW template and target bundle bytes"
            )
        derived_review = _derive_review(witness, phase_a)
        review_envelope = parse_authoring_artifact_envelope(derived_review.canonical_bytes)
        with self._composition.open_application_scope() as app:
            review = app.submit_review.submit(
                SubmitDraftForReviewCommand(
                    task_id=witness.task_id,
                    expected_revision=phase_a.task_revision,
                    envelope_bytes=derived_review.canonical_bytes,
                ),
                DraftReviewSubmissionContext(witness.keys.review_key),
            )
            adopted = app.create_decision.create(
                CreateAuthorDecisionCommand(
                    task_id=witness.task_id,
                    decision_type=DecisionType.ADOPT_DRAFT,
                    target_ref=review_envelope.reviewed_draft_ref,
                    based_on_task_revision=review.aggregate_revision,
                    adopted_draft_payload=witness.draft_bytes,
                ),
                DecisionCreationContext(witness.keys.adopt_key),
            )
            changeset_state = app.consume_decision.consume(
                ConsumeAuthorDecisionCommand(
                    task_id=witness.task_id,
                    decision_id=adopted.decision_id,
                    expected_revision=review.aggregate_revision,
                ),
                TransitionOperationContext(witness.keys.adopt_key + ":consume"),
            )
            changeset = app.prepare_changeset.prepare(
                PrepareCanonChangesetCommand(
                    task_id=witness.task_id,
                    expected_revision=changeset_state.aggregate_revision,
                    target_bundle_bytes=witness.target_bundle_bytes,
                ),
                CanonPrepareDeliveryContext(witness.keys.prepare_changeset_key),
            )
            approved = app.create_decision.create(
                CreateAuthorDecisionCommand(
                    task_id=witness.task_id,
                    decision_type=DecisionType.APPROVE_CHANGESET,
                    target_ref=changeset.changeset_ref,
                    based_on_task_revision=changeset.aggregate_revision,
                ),
                DecisionCreationContext(witness.keys.approve_changeset_key),
            )
            intent = app.approve_changeset.approve(
                ApproveCanonChangesetCommand(
                    task_id=witness.task_id,
                    decision_id=approved.decision_id,
                    expected_revision=changeset.aggregate_revision,
                ),
                CanonApproveDeliveryContext(witness.keys.approve_changeset_key + ":consume"),
            )
            applied = ApplyCanonCommitUseCase(app.apply_canon).apply(
                CanonApplyCommand(
                    task_id=witness.task_id,
                    journal_id=intent.journal_id or "",
                    expected_revision=intent.aggregate_revision,
                    apply_key=witness.keys.apply_key,
                ),
                CanonApplyDeliveryContext(witness.keys.apply_key),
            )
            return PhaseBOutcome(
                witness.task_id,
                applied.aggregate_revision,
                applied.status,
                applied.receipt_ref,
                derived_review,
            )


def derive_activation_identity(project_id: str, activation_key: str) -> tuple[str, str]:
    if not isinstance(project_id, str) or not project_id.strip():
        raise ValueError("project_id must be non-empty")
    if not isinstance(activation_key, str) or not activation_key.strip():
        raise ValueError("activation_key must be non-empty")
    canonical = json.dumps(
        {"activation_key": activation_key, "project_id": project_id},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = "sha256:" + hashlib.sha256(canonical).hexdigest()
    attempt_key = "g0c-" + hashlib.sha256(canonical).hexdigest()[:48]
    return attempt_key, digest


def _require_clean_gate(evidence: C5G0ActivationCleanEvidence) -> None:
    if not isinstance(evidence, C5G0ActivationCleanEvidence) or evidence.status != "C4B_ACTIVATED_CLEAN":
        raise UnsupportedPersistenceBoundary("G0-C requires a fresh clean activation evidence")


def _derive_review(witness: G0CInput, phase_a: PhaseAOutcome) -> DerivedReviewEvidence:
    if not isinstance(phase_a, PhaseAOutcome):
        raise UnsupportedPersistenceBoundary(
            "Phase A did not return a trusted DRAFT ref/result"
        )
    if phase_a.task_id != witness.task_id:
        raise UnsupportedPersistenceBoundary("Phase B requires the real Phase A Task binding")
    if type(phase_a.task_revision) is not int or phase_a.task_revision < 0:
        raise UnsupportedPersistenceBoundary("Phase A task revision is invalid")
    if not isinstance(phase_a.draft_ref, ArtifactRef):
        raise UnsupportedPersistenceBoundary("Phase A did not return a trusted DRAFT ref")

    template = _decode_review_template(witness.review_template_bytes)
    template_bytes = witness.review_template_bytes
    try:
        parse_authoring_artifact_envelope(template_bytes)
    except Exception:
        pass
    else:
        raise UnsupportedPersistenceBoundary(
            "REVIEW template must be body source, not a canonical authoring envelope"
        )

    envelope = AuthoringArtifactEnvelope(
        artifact_kind=AuthoringArtifactKind.REVIEW,
        artifact_schema_version=AUTHORING_ARTIFACT_SCHEMA_VERSION,
        project_id=witness.project_id,
        chapter_number=witness.chapter_number,
        task_id=witness.task_id,
        body=template,
        reviewed_draft_ref=phase_a.draft_ref,
        verdict="PASS",
    )
    try:
        review_bytes = serialize_authoring_artifact_envelope(envelope)
        readback = parse_authoring_artifact_envelope(review_bytes)
        canonical_bytes = serialize_authoring_artifact_envelope(readback)
    except Exception as exc:
        raise UnsupportedPersistenceBoundary(
            "derived REVIEW serializer/parser readback failed"
        ) from exc

    if review_bytes != canonical_bytes:
        raise UnsupportedPersistenceBoundary("derived REVIEW is not canonical")
    if (
        readback.artifact_kind is not AuthoringArtifactKind.REVIEW
        or readback.project_id != witness.project_id
        or readback.task_id != witness.task_id
        or readback.chapter_number != witness.chapter_number
        or readback.reviewed_draft_ref != phase_a.draft_ref
        or readback.verdict != "PASS"
    ):
        raise UnsupportedPersistenceBoundary("derived REVIEW identity binding failed")

    return DerivedReviewEvidence(
        source="runner_derived_after_phase_a",
        canonical_bytes=review_bytes,
        reviewed_draft_ref=phase_a.draft_ref,
        task_revision=phase_a.task_revision,
        byte_length=len(review_bytes),
        sha256="sha256:" + hashlib.sha256(review_bytes).hexdigest(),
        parser_readback=True,
        serializer_readback=True,
        canonical_equal=True,
    )


def _decode_review_template(data: bytes | None) -> str:
    if type(data) is not bytes:
        raise UnsupportedPersistenceBoundary("REVIEW template must be bytes")
    if data.startswith(b"\xef\xbb\xbf"):
        raise UnsupportedPersistenceBoundary("REVIEW template must not contain a BOM")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise UnsupportedPersistenceBoundary("REVIEW template must be strict UTF-8") from exc
    if "\x00" in text:
        raise UnsupportedPersistenceBoundary("REVIEW template must not contain NUL")
    if not text.strip():
        raise UnsupportedPersistenceBoundary("REVIEW template body must be non-empty")
    return text


def _validate_artifact(data: bytes, kind: AuthoringArtifactKind, witness: G0CInput) -> None:
    try:
        envelope = parse_authoring_artifact_envelope(data)
    except Exception as exc:
        raise UnsupportedPersistenceBoundary("witness artifact is not canonical") from exc
    if envelope.artifact_kind is not kind:
        raise UnsupportedPersistenceBoundary("witness artifact kind mismatch")
    if (
        envelope.project_id != witness.project_id
        or envelope.task_id != witness.task_id
        or envelope.chapter_number != witness.chapter_number
    ):
        raise UnsupportedPersistenceBoundary("witness artifact identity mismatch")
