"""G0C-07..30: explicit bootstrap replay and two-phase runner boundaries."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from scripts.c5_g0_witness import (
    C5G0WitnessRunner,
    G0CInput,
    G0CKeys,
    PhaseAOutcome,
    derive_activation_identity,
)
from xiaoshuo.application.creation.errors import UnsupportedPersistenceBoundary
from xiaoshuo.infrastructure.canon.c5_g0_composition import C5G0BootstrapResult
import xiaoshuo.infrastructure.canon.c5_g0_composition as composition_module
import xiaoshuo.infrastructure.persistence.sqlite.c5_g0_activation_state_verifier as verifier_module
from xiaoshuo.infrastructure.canon.c5_g0_composition import C5G0ApplicationScope
from xiaoshuo.infrastructure.canon.c4a_apply import C4aApplyService
from xiaoshuo.infrastructure.canon.projection_activation import ProjectionActivationReader
from xiaoshuo.infrastructure.persistence.sqlite.c5_g0_activation_state_verifier import (
    C5G0ActivationCleanEvidence,
    C5G0RuntimeCensus,
    C5G0RuntimeCensusStatus,
)
from xiaoshuo.domain.creation import ArtifactRef, ChapterTaskStatus
import scripts.c5_g0_witness as witness_module


def _evidence() -> C5G0ActivationCleanEvidence:
    return C5G0ActivationCleanEvidence(
        status="C4B_ACTIVATED_CLEAN",
        project_id="project-1",
        attempt_id="attempt-1",
        attempt_key="attempt-1",
        request_digest="sha256:" + "1" * 64,
        operator_identity="local-author",
        bundle_ref=ArtifactRef("bundle-1", 1, "sha256:" + "2" * 64),
        version_id="v1",
        pointer_content_hash="sha256:" + "3" * 64,
        event_phases=("PREPARED", "READY_FOR_MARKER"),
        reader_project_id="project-1",
        reader_version_id="v1",
        reader_bundle_ref=ArtifactRef("bundle-1", 1, "sha256:" + "2" * 64),
        reader_bundle_content_hash="sha256:" + "2" * 64,
        reader_manifest_hash="sha256:" + "4" * 64,
        reader_world_hash="sha256:" + "5" * 64,
    )


class _Runtime:
    def __init__(self, root: Path):
        self.root = root
        self.payloads_dir = root / "payloads"
        self.projection_dir = root / "projection"
        self.exports_dir = root / "exports"
        self.settings = object()
        self.verify_empty_calls = 0

    def verify_initialized_empty(self):
        self.verify_empty_calls += 1


class _Composition:
    def __init__(self, runtime):
        self.runtime = runtime
        self.census_status = None
        self.bootstrap_calls = 0
        self.replay_calls = 0
        self.verify_calls = 0
        self.fresh_gate_calls = 0
        self.clean_results = []
        self.completed_graph_calls = []

    def classify_runtime(self, **kwargs):
        status = self.census_status
        if status is None:
            status = (
                C5G0RuntimeCensusStatus.C4B_ACTIVATED_CLEAN
                if self.runtime.payloads_dir.exists()
                else C5G0RuntimeCensusStatus.INITIALIZED_EMPTY
            )
        return C5G0RuntimeCensus(
            status=status,
            reason="test census",
            root_exists=True,
            database_exists=True,
            payloads_exists=status is C5G0RuntimeCensusStatus.C4B_ACTIVATED_CLEAN,
            projection_exists=status is C5G0RuntimeCensusStatus.C4B_ACTIVATED_CLEAN,
            backups_exists=False,
            exports_exists=False,
        )

    def verify_c4b_clean(self, **kwargs):
        self.verify_calls += 1
        evidence = replace(_evidence(), attempt_id=f"attempt-{self.verify_calls}")
        self.clean_results.append(evidence)
        return evidence

    def verify_fresh_gate(self, **kwargs):
        self.fresh_gate_calls += 1
        status = self.census_status
        if status is None:
            status = (
                C5G0RuntimeCensusStatus.C4B_ACTIVATED_CLEAN
                if self.runtime.payloads_dir.exists()
                else C5G0RuntimeCensusStatus.INITIALIZED_EMPTY
            )
        return SimpleNamespace(status=status, zero_write=True)

    def bootstrap_c4b(self, **kwargs):
        self.bootstrap_calls += 1
        return C5G0BootstrapResult("ACTIVATED", "attempt-1", "project-1", "v1", "{}")

    def replay_c4b(self, **kwargs):
        self.replay_calls += 1
        return C5G0BootstrapResult("REPLAY", "attempt-1", "project-1", "v1", "{}")

    def verify_completed_graph(self, **kwargs):
        self.completed_graph_calls.append(kwargs)
        return "completed-graph-evidence"

    def open_application_scope(self):
        raise AssertionError("phase should reject before application scope")


def test_activation_identity_is_deterministic_and_does_not_expose_raw_key():
    attempt_key, digest = derive_activation_identity("project-1", "unique-key")
    again = derive_activation_identity("project-1", "unique-key")
    assert (attempt_key, digest) == again
    assert attempt_key.startswith("g0c-")
    assert "unique-key" not in attempt_key
    assert digest.startswith("sha256:")


def test_fresh_bootstrap_calls_initialized_empty_once_then_clean_verifier(tmp_path):
    runtime = _Runtime(tmp_path / "runtime")
    composition = _Composition(runtime)
    outcome = C5G0WitnessRunner(composition).bootstrap(
        project_id="project-1", activation_key="unique-key"
    )
    assert outcome.status == "C4B_ACTIVATED_CLEAN"
    assert runtime.verify_empty_calls == 1
    assert composition.bootstrap_calls == 1
    assert composition.replay_calls == 0
    assert composition.fresh_gate_calls == 1
    assert composition.verify_calls == 1
    assert outcome.evidence is composition.clean_results[-1]


def test_completed_bootstrap_is_replay_only_and_never_initializes(tmp_path):
    runtime = _Runtime(tmp_path / "runtime")
    runtime.payloads_dir.mkdir(parents=True)
    runtime.projection_dir.mkdir(parents=True)
    composition = _Composition(runtime)
    outcome = C5G0WitnessRunner(composition).bootstrap(
        project_id="project-1", activation_key="unique-key"
    )
    assert outcome.status == "BOOTSTRAP_REPLAY_ONLY"
    assert runtime.verify_empty_calls == 0
    assert composition.bootstrap_calls == 0
    assert composition.replay_calls == 1
    assert composition.fresh_gate_calls == 0
    assert composition.verify_calls == 1
    assert outcome.evidence is composition.clean_results[-1]


def test_completed_graph_replay_derives_identity_and_does_not_reenter_phases(tmp_path):
    runtime = _Runtime(tmp_path / "runtime")
    composition = _Composition(runtime)
    runner = C5G0WitnessRunner(composition)
    result = runner.replay_completed_graph(
        project_id="project-1", task_id="task-1", activation_key="unique-key"
    )
    expected_attempt_key, expected_digest = derive_activation_identity(
        "project-1", "unique-key"
    )
    assert result == "completed-graph-evidence"
    assert composition.completed_graph_calls == [
        {
            "project_id": "project-1",
            "task_id": "task-1",
            "attempt_key": expected_attempt_key,
            "request_digest": expected_digest,
        }
    ]
    assert runtime.verify_empty_calls == 0
    assert composition.bootstrap_calls == 0
    assert composition.replay_calls == 0


def test_unprovisioned_runtime_has_no_executable_witness_branch(tmp_path):
    runtime = _Runtime(tmp_path / "runtime")
    composition = _Composition(runtime)
    composition.census_status = C5G0RuntimeCensusStatus.UNPROVISIONED_NO_RUNTIME
    with pytest.raises(UnsupportedPersistenceBoundary, match="NO_EXECUTABLE_WITNESS_BRANCH"):
        C5G0WitnessRunner(composition).bootstrap(
            project_id="project-1", activation_key="unique-key"
        )
    assert runtime.verify_empty_calls == 0
    assert composition.bootstrap_calls == 0
    assert composition.replay_calls == 0
    assert composition.verify_calls == 0


def test_completed_graph_census_never_calls_c4b_clean_verifier(tmp_path):
    runtime = _Runtime(tmp_path / "runtime")
    composition = _Composition(runtime)
    composition.census_status = C5G0RuntimeCensusStatus.COMPLETED_GRAPH
    with pytest.raises(UnsupportedPersistenceBoundary, match="COMPLETED_GRAPH_REPLAY_ONLY"):
        C5G0WitnessRunner(composition).bootstrap(
            project_id="project-1", activation_key="unique-key"
        )
    assert composition.verify_calls == 0
    assert composition.replay_calls == 0


def test_recovery_assessed_bootstrap_uses_fresh_gate_without_legacy_empty_verify(tmp_path):
    runtime = _Runtime(tmp_path / "runtime")
    composition = _Composition(runtime)
    composition.census_status = (
        C5G0RuntimeCensusStatus.RECOVERY_ASSESSED_INITIALIZED_EMPTY_COMPATIBLE
    )
    outcome = C5G0WitnessRunner(composition).bootstrap(
        project_id="project-1", activation_key="unique-key"
    )
    assert outcome.status == "C4B_ACTIVATED_CLEAN"
    assert runtime.verify_empty_calls == 0
    assert composition.fresh_gate_calls == 1
    assert composition.bootstrap_calls == 1


def test_composition_exposes_only_verifier_owned_runtime_census(monkeypatch):
    marker = object()
    runtime = object()

    class _Verifier:
        def __init__(self, received_runtime):
            assert received_runtime is runtime

        def classify_runtime(self, **kwargs):
            assert kwargs["project_id"] == "project-1"
            return marker

    monkeypatch.setattr(verifier_module, "C5G0ActivationStateVerifier", _Verifier)
    composition = object.__new__(composition_module.C5G0Composition)
    composition._runtime = runtime
    assert composition.classify_runtime(
        project_id="project-1",
        attempt_key="attempt-1",
        request_digest="sha256:" + "1" * 64,
    ) is marker


def test_g0c_input_rejects_final_review_bytes_field():
    with pytest.raises(TypeError):
        G0CInput(
            "project-1",
            "task-1",
            1,
            G0CKeys("a", "p", "c", "d", "r", "ad", "pc", "ac", "apply"),
            b"intent",
            b"plan",
            b"draft",
            review_bytes=b"review",
        )


def test_phase_a_uses_composition_owned_clean_evidence_for_authorization():
    runtime = _Runtime(Path("D:/tmp/c5-g0-witness-authority"))
    composition = _Composition(runtime)
    runner = C5G0WitnessRunner.__new__(C5G0WitnessRunner)
    runner._composition = composition
    forged = replace(_evidence(), attempt_id="forged-attempt")
    witness = G0CInput(
        "project-1",
        "task-1",
        1,
        G0CKeys("a", "p", "c", "d", "r", "ad", "pc", "ac", "apply"),
        b"not-canonical-intent",
        b"not-canonical-plan",
        b"not-canonical-draft",
    )
    with pytest.raises(UnsupportedPersistenceBoundary, match="does not match"):
        runner.run_phase_a(witness, clean_evidence=forged)
    assert composition.verify_calls == 1


def test_phase_b_requires_explicit_review_and_target_bundle():
    runner = C5G0WitnessRunner.__new__(C5G0WitnessRunner)
    runner._composition = _Composition(object())
    witness = G0CInput(
        "project-1",
        "task-1",
        1,
        G0CKeys("a", "p", "c", "d", "r", "ad", "pc", "ac", "apply"),
        b"intent",
        b"plan",
        b"draft",
    )
    phase_a = type("PhaseA", (), {"task_revision": 3, "draft_ref": object()})()
    with pytest.raises(UnsupportedPersistenceBoundary):
        runner.run_phase_b(witness, phase_a=phase_a)


def _phase_a_result() -> PhaseAOutcome:
    return PhaseAOutcome(
        task_id="task-1",
        task_revision=3,
        draft_ref=ArtifactRef("draft-1", 1, "sha256:" + "1" * 64),
    )


def _phase_b_witness(*, template: bytes = b"review body") -> G0CInput:
    return G0CInput(
        "project-1",
        "task-1",
        1,
        G0CKeys("a", "p", "c", "d", "r", "ad", "pc", "ac", "apply"),
        b"intent",
        b"plan",
        b"draft",
        review_template_bytes=template,
        target_bundle_bytes=b"target-bundle",
    )


class _PhaseBScope:
    def __init__(self, opened):
        self.opened = opened
        self.review_bytes = None
        self.submit_review = SimpleNamespace(submit=self._submit_review)
        self.create_decision = SimpleNamespace(create=self._create_decision)
        self.consume_decision = SimpleNamespace(consume=self._consume_decision)
        self.prepare_changeset = SimpleNamespace(prepare=self._prepare_changeset)
        self.approve_changeset = SimpleNamespace(approve=self._approve_changeset)
        self.apply_canon = object()

    def __enter__(self):
        self.opened.append(True)
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def _submit_review(self, command, context):
        self.review_bytes = command.envelope_bytes
        return SimpleNamespace(aggregate_revision=4)

    def _create_decision(self, command, context):
        return SimpleNamespace(decision_id="decision-1")

    def _consume_decision(self, command, context):
        return SimpleNamespace(aggregate_revision=5)

    def _prepare_changeset(self, command, context):
        return SimpleNamespace(
            changeset_ref=ArtifactRef("changeset-1", 1, "sha256:" + "2" * 64),
            aggregate_revision=6,
        )

    def _approve_changeset(self, command, context):
        return SimpleNamespace(journal_id="journal-1", aggregate_revision=7)


def test_phase_b_derives_canonical_review_and_exposes_evidence(monkeypatch):
    opened = []
    scope = _PhaseBScope(opened)

    class _Composition:
        def open_application_scope(self):
            return scope

    class _Apply:
        def __init__(self, service):
            pass

        def apply(self, command, context):
            return SimpleNamespace(
                aggregate_revision=8,
                status=ChapterTaskStatus.COMPLETED,
                receipt_ref=ArtifactRef("receipt-1", 1, "sha256:" + "3" * 64),
            )

    monkeypatch.setattr(witness_module, "ApplyCanonCommitUseCase", _Apply)
    runner = C5G0WitnessRunner(_Composition())
    phase_a = _phase_a_result()
    outcome = runner.run_phase_b(_phase_b_witness(), phase_a=phase_a)

    assert len(opened) == 1
    assert scope.review_bytes is not None
    derived = outcome.derived_review
    assert derived.source == "runner_derived_after_phase_a"
    assert derived.reviewed_draft_ref == phase_a.draft_ref
    assert derived.task_revision == phase_a.task_revision
    assert derived.byte_length == len(derived.canonical_bytes)
    assert derived.sha256 == "sha256:" + __import__("hashlib").sha256(derived.canonical_bytes).hexdigest()
    assert derived.parser_readback is True
    assert derived.serializer_readback is True
    assert derived.canonical_equal is True
    assert scope.review_bytes == derived.canonical_bytes


@pytest.mark.parametrize(
    "template",
    [b"\xef\xbb\xbfbody", b"body\x00value", b"\xff", b"   "],
)
def test_phase_b_rejects_invalid_review_template_before_opening_scope(template):
    runner = C5G0WitnessRunner.__new__(C5G0WitnessRunner)
    runner._composition = _Composition(object())
    with pytest.raises(UnsupportedPersistenceBoundary):
        runner.run_phase_b(_phase_b_witness(template=template), phase_a=_phase_a_result())


def test_phase_b_rejects_forged_final_review_template_before_opening_scope():
    from xiaoshuo.application.creation.authoring_artifact import (
        AuthoringArtifactEnvelope,
        AuthoringArtifactKind,
        serialize_authoring_artifact_envelope,
    )

    forged = serialize_authoring_artifact_envelope(
        AuthoringArtifactEnvelope(
            AuthoringArtifactKind.REVIEW,
            1,
            "project-1",
            1,
            "task-1",
            "forged",
            reviewed_draft_ref=ArtifactRef("forged", 1, "sha256:" + "9" * 64),
            verdict="PASS",
        )
    )
    runner = C5G0WitnessRunner.__new__(C5G0WitnessRunner)
    runner._composition = _Composition(object())
    with pytest.raises(UnsupportedPersistenceBoundary, match="canonical authoring envelope"):
        runner.run_phase_b(_phase_b_witness(template=forged), phase_a=_phase_a_result())


def test_phase_b_rejects_invalid_phase_a_before_opening_scope():
    runner = C5G0WitnessRunner.__new__(C5G0WitnessRunner)
    runner._composition = _Composition(object())
    invalid_phase_a = PhaseAOutcome("task-1", 3, object())
    with pytest.raises(UnsupportedPersistenceBoundary, match="trusted DRAFT ref"):
        runner.run_phase_b(_phase_b_witness(), phase_a=invalid_phase_a)


def test_phase_b_rejects_missing_phase_a_before_opening_scope():
    runner = C5G0WitnessRunner.__new__(C5G0WitnessRunner)
    runner._composition = _Composition(object())
    with pytest.raises(UnsupportedPersistenceBoundary, match="trusted DRAFT ref"):
        runner.run_phase_b(_phase_b_witness(), phase_a=None)


def test_witness_input_has_no_caller_identity_or_base_fields():
    fields = set(G0CInput.__dataclass_fields__)
    assert fields == {
        "project_id",
        "task_id",
        "chapter_number",
        "keys",
        "creative_intent_bytes",
        "plan_bytes",
        "draft_bytes",
        "review_template_bytes",
        "target_bundle_bytes",
    }


def test_application_scope_closes_reader_connection_when_construction_fails(monkeypatch):
    class _Connection:
        def __init__(self):
            self.close_calls = 0

        def close(self):
            self.close_calls += 1

    connection = _Connection()
    original = RuntimeError("reader construction failed")

    class _Runtime:
        settings = object()
        projection_dir = Path("D:/tmp/c5-g0-scope-projection")
        payloads_dir = Path("D:/tmp/c5-g0-scope-payloads")
        author_context = object()

    monkeypatch.setattr(composition_module, "get_connection", lambda *args, **kwargs: connection)

    def _fail_reader(*args, **kwargs):
        raise original

    monkeypatch.setattr(composition_module, "ProjectionActivationReader", _fail_reader)
    with pytest.raises(RuntimeError) as caught:
        C5G0ApplicationScope(_Runtime())
    assert caught.value is original
    assert connection.close_calls == 1


def test_application_scope_preserves_original_error_when_construction_close_fails(monkeypatch):
    class _Connection:
        def close(self):
            raise RuntimeError("scope close failed")

    original = RuntimeError("reader construction failed")

    class _Runtime:
        settings = object()
        projection_dir = Path("D:/tmp/c5-g0-scope-projection")
        payloads_dir = Path("D:/tmp/c5-g0-scope-payloads")
        author_context = object()

    monkeypatch.setattr(composition_module, "get_connection", lambda *args, **kwargs: _Connection())
    monkeypatch.setattr(
        composition_module,
        "ProjectionActivationReader",
        lambda *args, **kwargs: (_ for _ in ()).throw(original),
    )
    with pytest.raises(RuntimeError) as caught:
        C5G0ApplicationScope(_Runtime())
    assert caught.value is original
    assert isinstance(caught.value.__cause__, RuntimeError)


def test_real_c5g0_composition_owns_config_bound_c4a_reader(monkeypatch):
    connections = []

    def _query_only_connection(*args, **kwargs):
        connection = sqlite3.connect(":memory:")
        connections.append(connection)
        return connection

    monkeypatch.setattr(composition_module, "get_connection", _query_only_connection)
    composition = composition_module.C5G0Composition.load()
    with composition.open_application_scope() as scope:
        apply_canon = scope.apply_canon
        assert isinstance(apply_canon, C4aApplyService)
        assert isinstance(apply_canon.activation_reader, ProjectionActivationReader)
        assert apply_canon.projection_root.resolve() == composition.runtime.projection_dir.resolve()
        assert apply_canon.activation_reader.root.resolve() == composition.runtime.projection_dir.resolve()
    assert all(connection is not None for connection in connections)


def test_composition_fresh_gate_returns_verifier_owned_typed_evidence(monkeypatch):
    calls = []
    evidence = object()

    def _verify_fresh_gate(runtime, **kwargs):
        calls.append((runtime, kwargs))
        return evidence

    monkeypatch.setattr(verifier_module, "verify_fresh_gate", _verify_fresh_gate)
    composition = object.__new__(composition_module.C5G0Composition)
    runtime = object()
    composition._runtime = runtime

    result = composition.verify_fresh_gate(
        project_id="project-1",
        attempt_key="attempt-1",
        request_digest="sha256:" + "1" * 64,
    )

    assert result is evidence
    assert calls == [
        (
            runtime,
            {
                "project_id": "project-1",
                "attempt_key": "attempt-1",
                "request_digest": "sha256:" + "1" * 64,
            },
        )
    ]
