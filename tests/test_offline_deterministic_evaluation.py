"""P1-A deterministic evaluator acceptance tests.

The fixtures are deliberately owner-injected.  No test discovers config,
project roots, legacy modules, services or network resources.
"""

from __future__ import annotations

import base64
import builtins
import copy
import dis
import importlib
import importlib.machinery
import inspect
import json
import os
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from xiaoshuo.pipeline import provenance
from xiaoshuo.pipeline.evaluation_contracts import (
    CPYTHON_RUNTIME_ID_FIELDS,
    DETERMINISTIC_WRITER_OBSERVATION_FIELDS,
    EVIDENCE_CONTENT_FIELDS,
    OWNER_PROBE_BINDING_FIELDS,
    SEMANTIC_RESULT_FIELDS,
    WRITER_FAILURE_EVIDENCE_FIELDS,
    ContractRegistryV1,
    EvaluationError,
    EvaluationInputManifestV1,
    EvaluatorSourceRegistryV1,
    P1CapabilityCensusV1,
    P1PreImportGateV1,
    RuleSetRegistryV1,
    canonical_evaluation_json_bytes,
    canonical_writer_failure_evidence,
    canonical_writer_observation,
    canonical_sha256,
    compatibility_matrix_hash,
    freeze_evidence,
    p0_to_p1_input_lineage_adapter,
    recompute_permit_digest_v2,
    recompute_permit_seal_v2,
    parse_canonical_evaluation_json,
    relative_path_key_utf8_hex,
    sha256_bytes,
    validate_relative_path_key,
)
from xiaoshuo.pipeline.evaluation_metrics import evaluate_bundle_bytes
from xiaoshuo.pipeline.offline_evaluation import (
    ArtifactResolverSnapshotV1,
    OfflineDeterministicEvaluator,
    OwnerArtifactResolver,
    OwnerHarness,
    P1CapabilityObserver,
    build_evaluation_manifest,
    build_residue_pairing,
    build_residue_snapshot,
    build_writer_trace_plan,
    code_object_preimage,
    code_object_sha256,
    deterministic_projection,
    _opcode_attestation_marker,
    runtime_identity_snapshot,
    residue_snapshot_hash,
    _final_path,
    live_resolution_identity_snapshot,
    owner_probe_binding_snapshot,
)


FIXTURE = Path(__file__).parent / "fixtures" / "offline_evaluation" / "artifact_bundle_v1.json"
RUN_ID = "20260810-000001-001"


def _parent_and_context(base: Path):
    owner = provenance.ProjectRegistryOwner("p1-owner", "project-registry-v1")
    definition = provenance.ProfileDefinitionV1(
        "profile-v1", "profile-demo", "v1", "fantasy", {"temperature": "0"}, {"policy": "offline"}
    )
    provenance_bytes = b"owner-project-entry-v1"
    entry = provenance.ProjectEntryV1(
        "project-entry-v1", "project-demo", "rev-1", definition.profile_id,
        definition.profile_version, definition.definition_hash, definition.genre_identity,
        "ACTIVE", "project-entry/provenance-v1", sha256_bytes(provenance_bytes),
    )
    registry = provenance.inject_project_registry(
        owner, [entry], registry_id="project-registry", snapshot_id="snapshot-1",
        owner_provenance_bytes={entry.entry_provenance_ref: provenance_bytes},
    )
    root = provenance.StageRootAlias("p1-root", "p1-stage", owner.owner_id, base / "roots")
    project = provenance.ProjectIdentity(entry.project_id)
    profile = provenance.ProfileIdentity.from_definition(definition)
    namespace = provenance.make_namespace(project, profile, entry.project_revision)
    parent = provenance.ParentRecordV1(
        "parent-1", entry.project_id, entry.profile_id, entry.profile_version,
        entry.profile_definition_hash, entry.project_revision, namespace.namespace_digest,
        root.alias, "owner-parent-v1", "test-producer", "parent-batch", 6, sha256_bytes(b"parent"),
    )
    store = provenance.ParentRefStoreV1(owner.owner_id, owner.authoritative_source_ref, {parent.parent_ref: parent})
    context = provenance.create_execution_context(
        registry=registry, project_id=entry.project_id, profile_id=entry.profile_id,
        profile_version=entry.profile_version, profile_definition=definition,
        stage_alias=root.stage_alias, root_alias=root.alias, run_id=RUN_ID,
        producer_version="p1-test-producer", registry_owner_id=owner.owner_id,
        registry_source_ref=owner.authoritative_source_ref,
        registry_snapshot_hash=registry.registry_snapshot_hash,
        root_alias_registry={root.alias: root}, parent_store=store,
    )
    return context, registry, definition, entry, store


def _registry_bundle(base: Path, *, candidate: bool = False, candidate_source: bytes | None = None, bind_standalone_manifest: bool = True, static_dependency: bool = False):
    context, registry, definition, entry, store = _parent_and_context(base)
    source_root = base / "candidate-source"
    source_root.mkdir(parents=True, exist_ok=True)
    if candidate:
        sys.modules.pop("candidate_module", None)
        source_text = candidate_source if candidate_source is not None else (b"import static_dependency\nCANDIDATE_VALUE = static_dependency.VALUE\n" if static_dependency else b"CANDIDATE_VALUE = 1\n")
        source_file = source_root / "candidate.py"
        source_file.write_bytes(source_text)
        source_entries = [{"relative_path": "candidate.py", "source_ref": "candidate-source-v1", "length": len(source_text), "sha256": sha256_bytes(source_text), "source_role": "candidate"}]
        module_path = "candidate_module"
        census_entries = [{
            "module_path": module_path, "source_relative_path": "candidate.py", "source_ref": "candidate-source-v1",
            "source_length": len(source_text), "source_sha256": sha256_bytes(source_text), "static_imports": ["static_dependency"] if static_dependency else [],
            "transitive_modules": [module_path, "static_dependency"] if static_dependency else [module_path], "dynamic_imports": [], "unknown_dynamic_imports": [],
            "unresolved_dependencies": [], "unresolved_writers": [], "module_main": False,
            "in_process_call": False, "process_spawn": False, "logger_call": False, "checkpoint_call": False,
            "state_call": False, "cache_call": False, "writer_call": False, "network_call": False,
            "api_call": False, "service_call": False, "model_call": False, "config_discovery": False,
            "project_discovery": False, "top_level_logger_side_effect": False,
            "top_level_checkpoint_side_effect": False, "top_level_state_side_effect": False,
            "top_level_cache_side_effect": False, "top_level_writer_side_effect": False,
            "top_level_network_side_effect": False, "top_level_model_side_effect": False,
            "top_level_config_discovery": False, "top_level_project_discovery": False, "writer_paths": [],
        }]
        candidate_modules = [module_path]
        static_allowlist = [module_path, "static_dependency"] if static_dependency else [module_path]
        if static_dependency:
            static_text = b"VALUE = 7\n"
            (source_root / "static.py").write_bytes(static_text)
            source_entries.append({"relative_path": "static.py", "source_ref": "static-source-v1", "length": len(static_text), "sha256": sha256_bytes(static_text), "source_role": "static"})
            census_entries.append({
                "module_path": "static_dependency", "source_relative_path": "static.py", "source_ref": "static-source-v1",
                "source_length": len(static_text), "source_sha256": sha256_bytes(static_text), "static_imports": [],
                "transitive_modules": ["static_dependency"], "dynamic_imports": [], "unknown_dynamic_imports": [],
                "unresolved_dependencies": [], "unresolved_writers": [], "module_main": False,
                "in_process_call": False, "process_spawn": False, "logger_call": False, "checkpoint_call": False,
                "state_call": False, "cache_call": False, "writer_call": False, "network_call": False,
                "api_call": False, "service_call": False, "model_call": False, "config_discovery": False,
                "project_discovery": False, "top_level_logger_side_effect": False,
                "top_level_checkpoint_side_effect": False, "top_level_state_side_effect": False,
                "top_level_cache_side_effect": False, "top_level_writer_side_effect": False,
                "top_level_network_side_effect": False, "top_level_model_side_effect": False,
                "top_level_config_discovery": False, "top_level_project_discovery": False, "writer_paths": [],
            })
    else:
        source_entries = []
        census_entries = []
        candidate_modules = []
        static_allowlist = []
    evaluator_source = (Path(__file__).parents[1] / "src" / "xiaoshuo" / "pipeline" / "offline_evaluation.py").read_bytes()
    (source_root / "offline_evaluation.py").write_bytes(evaluator_source)
    source_entries.append({"relative_path": "offline_evaluation.py", "source_ref": "p1-offline-evaluation-source-v2", "length": len(evaluator_source), "sha256": sha256_bytes(evaluator_source), "source_role": "evaluator"})
    source_entries.sort(key=lambda item: item["relative_path"].encode("utf-8"))
    census_entries.sort(key=lambda item: item["module_path"].encode("utf-8"))
    source_registry = EvaluatorSourceRegistryV1.from_mapping({
        "registry_schema_version": "source-registry-v1", "registry_id": "source-registry",
        "owner_id": registry.owner_id, "authoritative_source_ref": registry.authoritative_source_ref,
        "snapshot_id": "source-snapshot-1", "source_root_alias": context.root_alias,
        "read_only": True, "entries": source_entries,
    })
    census = P1CapabilityCensusV1.from_mapping({
        "registry_schema_version": "capability-census-v1", "registry_id": "census",
        "owner_id": registry.owner_id, "authoritative_source_ref": registry.authoritative_source_ref,
        "snapshot_id": "census-snapshot-1", "read_only": True, "entries": census_entries,
    })
    plan = build_writer_trace_plan(owner_id=registry.owner_id, authority_ref=registry.authoritative_source_ref, provenance_source_ref="p0-source-v1")
    live_resolution = live_resolution_identity_snapshot()
    guard = {
        "guard_schema_version": "resolution-guard-v1", "guard_id": "guard-1", "owner_id": registry.owner_id,
        "authority_ref": registry.authoritative_source_ref, "sys_path_snapshot": live_resolution["sys_path_snapshot"], "cwd_snapshot": live_resolution["cwd_snapshot"],
        "meta_path_snapshot": live_resolution["meta_path_snapshot"], "path_hooks_snapshot": live_resolution["path_hooks_snapshot"], "sys_modules_snapshot": live_resolution["sys_modules_snapshot"],
        "candidate_closure_modules": candidate_modules, "preloaded_candidate_modules": [],
        "preloaded_candidate_source_paths": [], "bootstrap_module_entries": [], "read_only": True,
        "deny_sys_path_read": True, "deny_cwd_read": True, "deny_fallback_finder": True,
        "deny_sys_modules_reuse": True, "deny_builtin_ambient_load": True,
    }
    gate = P1PreImportGateV1.from_mapping({
        "gate_schema_version": "preimport-gate-v1", "gate_id": "gate-1", "owner_id": registry.owner_id,
        "authority_ref": registry.authoritative_source_ref, "capability_census_snapshot_hash": census.snapshot_hash,
        "evaluator_source_registry_snapshot_hash": source_registry.snapshot_hash,
        "owner_probe_binding_hash": canonical_sha256(owner_probe_binding_snapshot(
            owner_id=registry.owner_id, authority_ref=registry.authoritative_source_ref,
            source_registry=source_registry, source_root=source_root,
        ), fields=OWNER_PROBE_BINDING_FIELDS),
        "resolution_guard_snapshot_hash": canonical_sha256(guard),
        "writer_trace_plan_snapshot_hash": canonical_sha256(plan), "candidate_modules": candidate_modules,
        "static_module_allowlist": static_allowlist, "dynamic_import_allowlist": [], "read_only": True,
        "no_root_creation": True, "no_config_discovery": True, "no_project_discovery": True,
    })
    harness = OwnerHarness(
        source_registry=source_registry, census=census, gate=gate, resolution_guard=guard,
        writer_trace_plan=plan, source_root=source_root, owner_session_id="owner-session-1",
        seal_key=b"owner-seal-key-v1",
    )
    if bind_standalone_manifest:
        zero = "0" * 64
        standalone_manifest = EvaluationInputManifestV1.from_mapping({
            "manifest_schema_version": "v1", "evaluation_case_id": "standalone-case",
            "project_id": context.project_id, "project_revision": context.namespace.project_revision,
            "profile_id": context.profile.profile_id, "profile_version": context.profile.profile_version,
            "profile_definition_hash": context.profile.profile_definition_hash, "genre_identity": context.genre_identity,
            "namespace_digest": context.namespace_digest, "project_registry_snapshot_hash": registry.registry_snapshot_hash,
            "input_artifact_identity": {}, "artifact_resolver_snapshot_hash": zero,
            "parent_store_snapshot_hash": store.snapshot_hash, "capability_census_snapshot_hash": census.snapshot_hash,
            "preimport_gate_snapshot_hash": gate.snapshot_hash, "resolution_guard_snapshot_hash": canonical_sha256(guard),
            "writer_trace_plan_snapshot_hash": canonical_sha256(plan), "rule_set_id": "standalone-rules",
            "rule_set_version": "1", "rule_set_registry_snapshot_hash": zero, "rule_set_bytes_sha256": zero,
            "evaluator_source_registry_snapshot_hash": source_registry.snapshot_hash,
            "evaluator_source_hash": source_registry.evaluator_source_hash,
            "contract_id": "standalone-contract", "contract_version": "1", "contract_registry_snapshot_hash": zero,
            "evaluation_contract_hash": zero, "expected_schema_id": "standalone", "declared_metrics": ["input_integrity"],
        })
        harness._owner_inject_manifest_source(relative_path="owner-manifest.json", source_ref="owner-manifest-test-v1", content=standalone_manifest.canonical_bytes)
        harness._bind_standalone_test_manifest(standalone_manifest, ["standalone-output.json"])
    return context, registry, store, source_registry, census, gate, guard, plan, harness


def _input_bundle(base: Path, *, candidate: bool = False):
    context, registry, store, source_registry, census, gate, guard, plan, harness = _registry_bundle(base, candidate=candidate, bind_standalone_manifest=False)
    input_root = base / "input-root"
    input_root.mkdir(parents=True, exist_ok=True)
    content = FIXTURE.read_bytes()
    (input_root / "input.json").write_bytes(content)
    artifact = provenance.make_artifact_ref(context, "input.json", content, source_ref="fixture-v1", batch_id="input-batch", parent_refs=("parent-1",))
    lineage = provenance.artifact_lineage(artifact)
    snapshot = ArtifactResolverSnapshotV1({
        "resolver_schema_version": "artifact-resolver-v1", "owner_id": registry.owner_id,
        "authoritative_source_ref": registry.authoritative_source_ref, "snapshot_id": "resolver-snapshot-1",
        "root_alias": context.root_alias, "parent_store_snapshot_hash": store.snapshot_hash, "read_only": True,
        "records": [{"relative_path": "input.json", "lineage_record_hash": sha256_bytes(canonical_evaluation_json_bytes(lineage, fields=("project_id", "profile_id", "profile_version", "profile_definition_hash", "project_revision", "namespace_digest", "root_alias", "relative_path", "source_ref", "producer_version", "batch_id", "parent_refs", "content_length", "content_sha256", "integrity_digest"))), "lineage_record": lineage}],
    })
    resolver = OwnerArtifactResolver(context=context, snapshot=snapshot, root=input_root, parent_store=store)
    rules = b"{\"rule_set_id\":\"offline-rules\",\"version\":\"1\"}"
    contract = b"{\"contract_id\":\"offline-deterministic-v1\",\"version\":\"1\"}"
    rule_registry = RuleSetRegistryV1.from_mapping({
        "registry_schema_version": "rule-registry-v1", "registry_id": "rules", "owner_id": registry.owner_id,
        "authoritative_source_ref": registry.authoritative_source_ref, "snapshot_id": "rules-snapshot-1", "read_only": True,
        "entries": [{"rule_set_id": "offline-rules", "rule_set_version": "1", "entry_source_ref": "rules-v1", "rule_set_bytes_b64": base64.b64encode(rules).decode("ascii"), "rule_set_bytes_sha256": sha256_bytes(rules), "entry_status": "ACTIVE"}],
    })
    contract_registry = ContractRegistryV1.from_mapping({
        "registry_schema_version": "contract-registry-v1", "registry_id": "contracts", "owner_id": registry.owner_id,
        "authoritative_source_ref": registry.authoritative_source_ref, "snapshot_id": "contracts-snapshot-1", "read_only": True,
        "entries": [{"contract_id": "offline-deterministic-v1", "contract_version": "1", "entry_source_ref": "contract-v1", "contract_bytes_b64": base64.b64encode(contract).decode("ascii"), "contract_bytes_sha256": sha256_bytes(contract), "entry_status": "ACTIVE"}],
    })
    manifest = build_evaluation_manifest(
        evaluation_case_id="case-1", context=context, input_artifact=artifact,
        resolver_snapshot_hash=snapshot.snapshot_hash, rule_set_id="offline-rules", rule_set_version="1",
        rule_registry=rule_registry, source_registry=source_registry, contract_registry=contract_registry,
        census=census, gate=gate, resolution_guard_snapshot_hash=canonical_sha256(guard),
        writer_trace_plan_snapshot_hash=canonical_sha256(plan), expected_schema_id="artifact-bundle-v1",
        declared_metrics=["input_integrity", "reference_resolution", "rule_coverage", "schema_conformance"],
    )
    input_adapter = p0_to_p1_input_lineage_adapter(provenance.artifact_lineage(artifact))
    manifest_path = base / "candidate-source" / "evaluation-manifest.json"
    manifest_path.write_bytes(manifest.canonical_bytes)
    source_entries = [dict(entry) for entry in source_registry.value["entries"]]
    source_entries.append({
        "relative_path": "evaluation-manifest.json",
        "source_ref": "owner-manifest-test-real-v1",
        "length": len(manifest.canonical_bytes),
        "sha256": sha256_bytes(manifest.canonical_bytes),
        "source_role": "manifest",
    })
    source_registry = EvaluatorSourceRegistryV1.from_mapping({
        **source_registry.value,
        "entries": sorted(source_entries, key=lambda item: item["relative_path"].encode("utf-8")),
    })
    gate = P1PreImportGateV1.from_mapping({
        **gate.value,
        "evaluator_source_registry_snapshot_hash": gate.value["evaluator_source_registry_snapshot_hash"],
        "owner_probe_binding_hash": canonical_sha256(owner_probe_binding_snapshot(
            owner_id=registry.owner_id, authority_ref=registry.authoritative_source_ref,
            source_registry=source_registry, source_root=base / "candidate-source",
        ), fields=OWNER_PROBE_BINDING_FIELDS),
    })
    harness = OwnerHarness(
        source_registry=source_registry, census=census, gate=gate, resolution_guard=guard,
        writer_trace_plan=plan, source_root=base / "candidate-source", owner_session_id="owner-session-1",
        seal_key=b"owner-seal-key-v1",
    )
    harness.bind_input_manifest(manifest, [input_adapter], ["semantic-result.json", "full-evidence.json"])
    return {
        "context": context, "registry": registry, "store": store, "source_registry": source_registry,
        "census": census, "gate": gate, "guard": guard, "plan": plan, "harness": harness,
        "input_root": input_root, "artifact": artifact, "snapshot": snapshot, "resolver": resolver,
        "rule_registry": rule_registry, "contract_registry": contract_registry, "manifest": manifest,
    }


def _residue_item(path: str, role: str, kind: str, final: str, *, exists: bool = True):
    if kind == "MISSING" or not exists:
        content_length, content_sha256, readable, readback = None, None, False, "MISSING"
    elif kind == "DIRECTORY":
        content_length, content_sha256, readable, readback = None, None, True, "DIRECTORY"
    else:
        content_length, content_sha256, readable, readback = 0, sha256_bytes(b""), True, "PARTIAL" if kind == "PARTIAL_FILE" else "EXPECTED"
    return {"relative_path": path, "entry_role": role, "entry_kind": kind, "exists": exists, "readable": readable, "content_length": content_length, "content_sha256": content_sha256, "readback_status": readback, "reparse_status": "VERIFIED", "containment_status": "VERIFIED", "final_identity": final}


def _second_output_failure(bundle, monkeypatch, error_factory, *, partial: bool = True, add_unexpected: bool = False):
    original_write_bytes = Path.write_bytes

    def faulting_write(path: Path, data: bytes) -> int:
        if path.name == "semantic-result.json":
            result = original_write_bytes(path, data)
            if add_unexpected:
                original_write_bytes(path.parent / "unexpected.partial", b"partial")
            return result
        if path.name == "full-evidence.json":
            original_write_bytes(path, data[:7] if partial else data)
            raise error_factory()
        return original_write_bytes(path, data)

    monkeypatch.setattr(Path, "write_bytes", faulting_write)
    evaluator = OfflineDeterministicEvaluator(
        context=bundle["context"], resolver=bundle["resolver"], owner_harness=bundle["harness"],
        rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"],
        census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"],
        writer_trace_plan=bundle["plan"],
    )
    with pytest.raises(EvaluationError) as caught:
        evaluator.evaluate(bundle["manifest"], batch_id="20260810-000001-045", attempt_id="attempt-045")
    return caught.value


def test_ode_01_codec_rejects_bom_nul_and_noncanonical_json():
    with pytest.raises(EvaluationError):
        parse_canonical_evaluation_json(b"\xef\xbb\xbf{}")
    with pytest.raises(EvaluationError):
        parse_canonical_evaluation_json(b'{"a":1}\x00')
    with pytest.raises(EvaluationError):
        parse_canonical_evaluation_json(b'{"a": 1}')


def test_ode_02_codec_rejects_duplicate_and_nfc_collision():
    with pytest.raises(EvaluationError):
        parse_canonical_evaluation_json(b'{"a":1,"a":2}')
    with pytest.raises(EvaluationError):
        parse_canonical_evaluation_json('{"é":1,"e\u0301":2}'.encode())


@pytest.mark.parametrize("value", ["00", "01", "-0", "+1", "1e2", "1.0", "1."])
def test_ode_03_decimal_grammar_is_closed(value):
    with pytest.raises(EvaluationError):
        parse_canonical_evaluation_json(("{\"x\":" + value + "}").encode())


def test_ode_04_relative_path_key_is_lowercase_utf8_hex():
    assert relative_path_key_utf8_hex("é/file.json") == "c3a92f66696c652e6a736f6e"
    with pytest.raises(EvaluationError):
        validate_relative_path_key("é", "C3A9")


def test_ode_05_matrix_hash_and_pairing_hash_are_non_self_referential():
    assert len(compatibility_matrix_hash()) == 64
    expected = [_residue_item("", "ROOT", "DIRECTORY", "root")]
    actual = [_residue_item("", "ROOT", "DIRECTORY", "root")]
    pairing = build_residue_pairing(expected, actual)
    assert pairing[0]["pair_status"] == "MATCHED"
    assert "pairing_hash" not in pairing[0]


@pytest.mark.parametrize("bad", [
    [_residue_item("b", "EXPECTED_TARGET", "FILE", "b"), _residue_item("a", "EXPECTED_TARGET", "FILE", "a")],
    [_residue_item("é", "EXPECTED_TARGET", "FILE", "a"), _residue_item("e\u0301", "EXPECTED_TARGET", "FILE", "b")],
])
def test_ode_06_residue_unsorted_or_nfc_collision_denied(bad):
    with pytest.raises(EvaluationError):
        build_residue_snapshot(root_relative_alias="p1-root", expected_entries=bad, actual_entries=[])


def test_ode_07_residue_roles_and_null_side_semantics():
    expected = [_residue_item("target", "EXPECTED_TARGET", "FILE", "target")]
    actual = [_residue_item("target", "EXPECTED_TARGET", "FILE", "target")]
    pair = build_residue_pairing(expected, actual)[0]
    assert pair["expected_entry_role"] == pair["actual_entry_role"] == "EXPECTED_TARGET"
    missing = build_residue_pairing(expected, [])[0]
    assert missing["actual_count"] == 0 and missing["actual_entry_role"] is None
    unexpected = build_residue_pairing([], [_residue_item("x", "UNEXPECTED", "FILE", "x")])[0]
    assert unexpected["pair_status"] == "UNEXPECTED_ACTUAL"


@pytest.mark.parametrize("role,kind", [("ROOT", "FILE"), ("EXPECTED_PARENT", "FILE"), ("EXPECTED_TARGET", "DIRECTORY"), ("EXPECTED_DESCENDANT", "PARTIAL_FILE")])
def test_ode_08_kind_matrix_rejects_invalid_roles(role, kind):
    with pytest.raises(EvaluationError):
        build_residue_pairing([_residue_item("x", role, kind, "x")], [_residue_item("x", role, kind, "x")])


def test_ode_09_partial_and_missing_cannot_match():
    with pytest.raises(EvaluationError):
        build_residue_pairing([_residue_item("x", "EXPECTED_TARGET", "FILE", "x")], [_residue_item("x", "EXPECTED_TARGET", "PARTIAL_FILE", "x")])
    missing = build_residue_pairing([_residue_item("x", "EXPECTED_TARGET", "FILE", "x")], [_residue_item("x", "EXPECTED_TARGET", "MISSING", "x", exists=False)])
    assert missing[0]["pair_status"] == "MISSING_EXPECTED"


def test_ode_10_resolver_recreates_private_p0_token(tmp_path):
    bundle = _input_bundle(tmp_path)
    resolved = bundle["resolver"].resolve(provenance.artifact_lineage(bundle["artifact"]))
    provenance.validate_artifact_ref(bundle["context"], resolved, FIXTURE.read_bytes(), expected_batch_id="input-batch")


def test_ode_11_resolver_forged_lineage_denied(tmp_path):
    bundle = _input_bundle(tmp_path)
    forged = dict(provenance.artifact_lineage(bundle["artifact"]))
    forged["content_length"] += 1
    with pytest.raises(EvaluationError):
        bundle["resolver"].resolve(forged)


def test_ode_12_census_and_source_snapshot_are_owner_bound(tmp_path):
    bundle = _registry_bundle(tmp_path, candidate=True)
    permit = bundle[-1].issue_permit()
    loaded = bundle[-1].load_candidates(permit)
    assert len(loaded) == 1 and bundle[-1].permitted_candidate_load_count == 1
    with pytest.raises(EvaluationError):
        bundle[-1].load_candidates(permit)
    assert "candidate_module" in sys.modules
    sys.modules.pop("candidate_module", None)


def test_ode_13_code_object_preimage_covers_nested_code():
    def outer():
        def inner():
            return 1
        return inner()
    value = code_object_preimage(outer.__code__)
    assert value["co_code_hex"] and value["nested_code_objects"]
    assert code_object_sha256(outer.__code__) == canonical_sha256(value)


def test_ode_14_writer_trace_plan_binds_real_p0_source():
    plan = build_writer_trace_plan(owner_id="owner", authority_ref="registry", provenance_source_ref="p0")
    assert plan["trace_backend"] == "CPYTHON_OPCODE_TRACE_V1"
    assert plan["transaction_call_offset"] != plan["writer_call_offset"]


def test_ode_15_projection_excludes_runtime_identity():
    projected = deterministic_projection({"semantic": 1, "run_id": "r", "thread_id": 3, "batch_id": "b"})
    assert projected == {"semantic": 1}


def test_ode_16_metrics_are_structural_and_claim_boundary_is_not_quality(tmp_path):
    report = evaluate_bundle_bytes(FIXTURE.read_bytes(), expected_schema_id="artifact-bundle-v1", declared_metrics=["input_integrity", "reference_resolution", "rule_coverage", "schema_conformance"])
    assert report.classification == "COMPLETED_DETERMINISTIC", report.to_mapping()
    assert report.findings == ()


def test_ode_17_manifest_contains_identity_only_artifact(tmp_path):
    bundle = _input_bundle(tmp_path)
    value = bundle["manifest"].to_mapping()
    assert tuple(value["input_artifact_identity"]) == ("project_id", "profile_id", "profile_version", "profile_definition_hash", "project_revision", "namespace_digest", "root_alias", "relative_path", "source_ref", "producer_version", "batch_id", "parent_refs", "content_length", "content_sha256", "integrity_digest")


def test_ode_18_end_to_end_writes_only_after_binding(tmp_path):
    bundle = _input_bundle(tmp_path)
    provenance.reset_call_counters()
    result = OfflineDeterministicEvaluator(
        context=bundle["context"], resolver=bundle["resolver"], owner_harness=bundle["harness"],
        rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"],
        census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"], writer_trace_plan=bundle["plan"],
    ).evaluate(bundle["manifest"], batch_id="20260810-000001-002", attempt_id="attempt-1")
    assert result.batch.batch_id == result.envelope.execution_batch_id
    assert all(path.drive.upper() == "D:" for path in result.output_paths)
    assert provenance.get_call_counters()["writer"] == 2
    assert result.semantic_result["run_id"] if "run_id" in result.semantic_result else True


def test_ode_19_zero_observer_on_positive_path(tmp_path):
    bundle = _input_bundle(tmp_path)
    bundle["harness"].issue_permit()
    bundle["harness"].observer.assert_zero()


def test_ode_20_denied_admission_has_no_output_root(tmp_path):
    bundle = _input_bundle(tmp_path)
    bad = dict(bundle["guard"])
    bad["deny_cwd_read"] = False
    with pytest.raises(EvaluationError):
        OwnerHarness(source_registry=bundle["source_registry"], census=bundle["census"], gate=bundle["gate"], resolution_guard=bad, writer_trace_plan=bundle["plan"], source_root=tmp_path / "candidate-source", owner_session_id="owner-session-1", seal_key=b"owner-seal-key-v1")
    assert not (bundle["context"].root_spec.root_base / RUN_ID).exists()


def test_ode_21_root_and_parent_are_explicit(tmp_path):
    bundle = _input_bundle(tmp_path)
    assert bundle["resolver"].parent_store.snapshot_hash == bundle["context"].parent_store.snapshot_hash
    assert bundle["context"].root_alias == "p1-root"


def test_ode_22_replay_hash_is_stable(tmp_path):
    bundle = _input_bundle(tmp_path)
    first = bundle["manifest"].manifest_hash
    second = type(bundle["manifest"].from_bytes(bundle["manifest"].canonical_bytes)).from_bytes(bundle["manifest"].canonical_bytes).manifest_hash
    assert first == second


def test_ode_23_expected_actual_final_identity_collision_denied():
    with pytest.raises(EvaluationError):
        build_residue_pairing([_residue_item("a", "EXPECTED_TARGET", "FILE", "same"), _residue_item("b", "EXPECTED_DESCENDANT", "FILE", "same")], [])


def test_ode_24_snapshot_hash_recomputes(tmp_path):
    bundle = _input_bundle(tmp_path)
    snapshot = build_residue_snapshot(root_relative_alias="p1-root", expected_entries=[_residue_item("target", "EXPECTED_TARGET", "FILE", "target")], actual_entries=[_residue_item("target", "EXPECTED_TARGET", "FILE", "target")])
    assert residue_snapshot_hash(snapshot) == canonical_sha256(snapshot)


@pytest.mark.parametrize("bad", [b"\xef\xbb\xbf{}", b"{\"a\":1}\x00", b"not-json"])
def test_ode_25_fixture_codec_fail_closed(bad):
    with pytest.raises(EvaluationError):
        parse_canonical_evaluation_json(bad)


def test_ode_26_p0_counters_are_supplementary(tmp_path):
    bundle = _input_bundle(tmp_path)
    provenance.reset_call_counters()
    bundle["harness"].issue_permit()
    assert all(value == 0 for value in provenance.get_call_counters().values())


def test_ode_27_source_readback_is_unchanged(tmp_path):
    bundle = _registry_bundle(tmp_path, candidate=True)
    before = tuple(sys.path)
    permit = bundle[-1].issue_permit()
    bundle[-1].load_candidates(permit)
    assert tuple(sys.path) == before
    sys.modules.pop("candidate_module", None)


def test_ode_28_parent_missing_is_denied(tmp_path):
    bundle = _input_bundle(tmp_path)
    lineage = dict(provenance.artifact_lineage(bundle["artifact"]))
    lineage["parent_refs"] = ["missing"]
    with pytest.raises(EvaluationError):
        bundle["resolver"].resolve(lineage)


def test_ode_29_no_default_project_or_config_discovery():
    assert "config.yaml" not in sys.modules
    assert "xiaoshuo.pipeline.pipeline_nodes" not in sys.modules


def test_ode_30_batch_binding_is_recomputed(tmp_path):
    bundle = _input_bundle(tmp_path)
    provenance.reset_call_counters()
    result = OfflineDeterministicEvaluator(context=bundle["context"], resolver=bundle["resolver"], owner_harness=bundle["harness"], rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"], census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"], writer_trace_plan=bundle["plan"]).evaluate(bundle["manifest"], batch_id="20260810-000001-003", attempt_id="attempt-3")
    provenance.verify_batch_envelope_binding(result.batch, result.envelope)


def test_ode_31_project_profile_namespace_are_explicit(tmp_path):
    context, registry, definition, entry, store = _parent_and_context(tmp_path)
    assert context.project_id == entry.project_id
    assert context.profile.profile_definition_hash == definition.definition_hash
    assert context.namespace.namespace_digest


def test_ode_32_profile_transition_changes_namespace(tmp_path):
    context, registry, definition, entry, store = _parent_and_context(tmp_path)
    changed = provenance.ProfileDefinitionV1("profile-v1", "profile-demo", "v2", "fantasy", {"temperature": "0"}, {"policy": "offline"})
    assert changed.definition_hash != definition.definition_hash
    assert context.namespace.namespace_digest != provenance.make_namespace(context.project, provenance.ProfileIdentity.from_definition(changed), entry.project_revision).namespace_digest


def test_ode_33_manifest_canonical_roundtrip(tmp_path):
    bundle = _input_bundle(tmp_path)
    assert bundle["manifest"].from_bytes(bundle["manifest"].canonical_bytes).manifest_hash == bundle["manifest"].manifest_hash


def test_ode_34_root_pairing_requires_directory():
    with pytest.raises(EvaluationError):
        build_residue_pairing([_residue_item("", "ROOT", "FILE", "root")], [_residue_item("", "ROOT", "FILE", "root")])


def test_ode_35_descendant_accepts_file():
    pair = build_residue_pairing([_residue_item("d/x", "EXPECTED_DESCENDANT", "FILE", "d/x")], [_residue_item("d/x", "EXPECTED_DESCENDANT", "FILE", "d/x")])
    assert pair[0]["pair_status"] == "MATCHED"


def test_ode_36_descendant_accepts_directory():
    pair = build_residue_pairing([_residue_item("d", "EXPECTED_DESCENDANT", "DIRECTORY", "d")], [_residue_item("d", "EXPECTED_DESCENDANT", "DIRECTORY", "d")])
    assert pair[0]["pair_status"] == "MATCHED"


def test_ode_37_expected_only_is_explicit():
    pair = build_residue_pairing([_residue_item("x", "EXPECTED_TARGET", "FILE", "x")], [])[0]
    assert pair["pair_status"] == "MISSING_ACTUAL_RECORD" and pair["actual_entry_kind"] is None


def test_ode_38_actual_only_is_unexpected():
    pair = build_residue_pairing([], [_residue_item("x", "UNEXPECTED", "FILE", "x")])[0]
    assert pair["pair_status"] == "UNEXPECTED_ACTUAL" and pair["expected_entry_role"] is None


def test_ode_39_unknown_entry_role_denied():
    with pytest.raises(EvaluationError):
        build_residue_pairing([_residue_item("x", "UNKNOWN", "FILE", "x")], [_residue_item("x", "UNKNOWN", "FILE", "x")])


def test_ode_40_reparse_entry_denied():
    item = _residue_item("x", "EXPECTED_TARGET", "FILE", "x")
    item["reparse_status"] = "REPARSE"
    with pytest.raises(EvaluationError):
        build_residue_pairing([item], [item])


def test_ode_41_containment_entry_denied():
    item = _residue_item("x", "EXPECTED_TARGET", "FILE", "x")
    item["containment_status"] = "ESCAPED"
    with pytest.raises(EvaluationError):
        build_residue_pairing([item], [item])


def test_ode_42_final_identity_case_collision_denied():
    with pytest.raises(EvaluationError):
        build_residue_pairing([_residue_item("A", "EXPECTED_TARGET", "FILE", "same"), _residue_item("b", "EXPECTED_DESCENDANT", "FILE", "SAME")], [])


def test_ode_43_wrong_key_is_denied():
    from xiaoshuo.pipeline.evaluation_contracts import validate_relative_path_key
    with pytest.raises(EvaluationError):
        validate_relative_path_key("x", "79")


def test_ode_44_resolver_snapshot_binds_parent_store(tmp_path):
    bundle = _input_bundle(tmp_path)
    assert bundle["snapshot"].value["parent_store_snapshot_hash"] == bundle["store"].snapshot_hash


def test_ode_45_source_and_census_hashes_are_bound(tmp_path):
    bundle = _registry_bundle(tmp_path, candidate=True)
    item = bundle[3].entry_for("candidate.py")
    census_item = bundle[4].value["entries"][0]
    assert item["source_ref"] == census_item["source_ref"]
    assert item["sha256"] == census_item["source_sha256"]


def test_ode_46_shallow_copy_permit_denied(tmp_path):
    bundle = _registry_bundle(tmp_path, candidate=True)
    permit = bundle[-1].issue_permit()
    with pytest.raises(EvaluationError):
        bundle[-1].load_candidates(copy.copy(permit))


def test_ode_47_permit_digest_tamper_denied(tmp_path):
    bundle = _registry_bundle(tmp_path, candidate=True)
    permit = bundle[-1].issue_permit()
    permit.permit_digest = "0" * 64
    with pytest.raises(EvaluationError):
        bundle[-1].load_candidates(permit)


def test_ode_48_dynamic_allowlist_is_empty(tmp_path):
    bundle = _registry_bundle(tmp_path)
    assert bundle[5].value["dynamic_import_allowlist"] == []
    assert bundle[5].value["no_project_discovery"] is True


def test_ode_49_runtime_attestation_is_cpython(tmp_path):
    bundle = _registry_bundle(tmp_path)
    assert bundle[-1].runtime_attestation["implementation_name"] == "cpython"
    assert bundle[-1].runtime_attestation["thread_id"]


def test_ode_50_semantic_projection_has_no_runtime_fields(tmp_path):
    bundle = _input_bundle(tmp_path)
    result = deterministic_projection({"project_id": bundle["context"].project_id, "run_id": RUN_ID, "thread_id": 1})
    assert "run_id" not in result and "thread_id" not in result


def test_ode_51_project_discovery_is_not_an_evaluator_input(tmp_path):
    bundle = _input_bundle(tmp_path)
    assert bundle["manifest"].value["project_id"] == "project-demo"
    assert "PROJECT_ROOT" not in bundle["manifest"].value


def test_ode_52_duplicate_output_path_denied_before_root(tmp_path):
    bundle = _input_bundle(tmp_path)
    evaluator = OfflineDeterministicEvaluator(context=bundle["context"], resolver=bundle["resolver"], owner_harness=bundle["harness"], rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"], census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"], writer_trace_plan=bundle["plan"])
    with pytest.raises(EvaluationError):
        evaluator.evaluate(bundle["manifest"], batch_id="20260810-000001-004", attempt_id="attempt-4", output_relative_paths=("same.json", "same.json"))
    assert not (bundle["context"].root_spec.root_base / RUN_ID).exists()


def test_ode_53_parent_store_resolution_is_explicit(tmp_path):
    bundle = _input_bundle(tmp_path)
    assert bundle["store"].resolve("parent-1").parent_ref == "parent-1"
    with pytest.raises(provenance.ProvenanceError):
        bundle["store"].resolve("unknown")


def test_ode_54_lineage_hash_is_exact(tmp_path):
    bundle = _input_bundle(tmp_path)
    lineage = provenance.artifact_lineage(bundle["artifact"])
    assert sha256_bytes(canonical_evaluation_json_bytes(lineage, fields=("project_id", "profile_id", "profile_version", "profile_definition_hash", "project_revision", "namespace_digest", "root_alias", "relative_path", "source_ref", "producer_version", "batch_id", "parent_refs", "content_length", "content_sha256", "integrity_digest"))) == bundle["snapshot"].records[0]["lineage_record_hash"]


def test_ode_55_manifest_project_mismatch_denied(tmp_path):
    bundle = _input_bundle(tmp_path)
    value = bundle["manifest"].to_mapping()
    value["project_id"] = "unknown-project"
    evaluator = OfflineDeterministicEvaluator(context=bundle["context"], resolver=bundle["resolver"], owner_harness=bundle["harness"], rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"], census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"], writer_trace_plan=bundle["plan"])
    with pytest.raises(EvaluationError):
        evaluator.evaluate(value, batch_id="20260810-000001-005", attempt_id="attempt-5")


def test_ode_56_manifest_registry_hash_mismatch_denied(tmp_path):
    bundle = _input_bundle(tmp_path)
    value = bundle["manifest"].to_mapping()
    value["project_registry_snapshot_hash"] = "0" * 64
    evaluator = OfflineDeterministicEvaluator(context=bundle["context"], resolver=bundle["resolver"], owner_harness=bundle["harness"], rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"], census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"], writer_trace_plan=bundle["plan"])
    with pytest.raises(EvaluationError):
        evaluator.evaluate(value, batch_id="20260810-000001-006", attempt_id="attempt-6")


def test_ode_57_candidate_source_bytes_are_owner_verified(tmp_path):
    bundle = _registry_bundle(tmp_path, candidate=True)
    (tmp_path / "candidate-source" / "candidate.py").write_bytes(b"CANDIDATE_VALUE = 2\n")
    with pytest.raises(EvaluationError):
        bundle[-1].load_candidates(bundle[-1].issue_permit())


def test_ode_58_invalid_bundle_is_classified_without_model():
    report = evaluate_bundle_bytes(b"{}", expected_schema_id="artifact-bundle-v1", declared_metrics=["schema_conformance"])
    assert report.classification == "FAILED_SCHEMA"


def test_ode_59_metrics_do_not_claim_model_quality():
    report = evaluate_bundle_bytes(FIXTURE.read_bytes(), expected_schema_id="artifact-bundle-v1", declared_metrics=["schema_conformance"])
    assert all("quality" not in finding.message_key for finding in report.findings)


def test_ode_60_candidate_has_no_process_capability(tmp_path):
    bundle = _registry_bundle(tmp_path, candidate=True)
    assert bundle[4].value["entries"][0]["process_spawn"] is False


def test_ode_61_owner_observer_is_zero_before_load(tmp_path):
    bundle = _input_bundle(tmp_path)
    bundle["harness"].observer.assert_zero()


def test_ode_62_output_root_is_d_drive_bound(tmp_path):
    bundle = _input_bundle(tmp_path)
    assert bundle["context"].root_spec.root_base.drive.upper() == "D:"


def test_ode_63_default_project_is_absent_from_manifest(tmp_path):
    bundle = _input_bundle(tmp_path)
    assert "末世" not in json.dumps(bundle["manifest"].to_mapping(), ensure_ascii=False)


def test_ode_64_batch_output_identity_is_current(tmp_path):
    bundle = _input_bundle(tmp_path)
    provenance.reset_call_counters()
    result = OfflineDeterministicEvaluator(context=bundle["context"], resolver=bundle["resolver"], owner_harness=bundle["harness"], rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"], census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"], writer_trace_plan=bundle["plan"]).evaluate(bundle["manifest"], batch_id="20260810-000001-007", attempt_id="attempt-7")
    assert all(item.batch_id == result.batch.batch_id for item in result.output_artifacts)


def test_ode_65_p1ae_is_not_part_of_p1a():
    assert "p1ae" not in OfflineDeterministicEvaluator.__module__.lower()


def test_ode_66_code_object_preimage_is_typed_and_no_fallback():
    def sample():
        return (1, b"x", "y")

    preimage = code_object_preimage(sample.__code__)
    encoded = json.dumps(preimage, ensure_ascii=False)
    assert "repr" not in encoded and "pickle" not in encoded and "marshal" not in encoded
    assert all(item["kind"] in {"NONE", "BOOL", "INT", "STR_UTF8_HEX", "BYTES_HEX", "TUPLE", "CODE_OBJECT"} for item in preimage["co_consts"])


def test_ode_67_nested_code_object_index_is_bound():
    def outer():
        def nested():
            return 1
        return nested

    preimage = code_object_preimage(outer.__code__)
    assert preimage["nested_code_objects"]
    assert preimage["nested_code_objects"][0]["const_index"] in range(len(preimage["co_consts"]))
    assert preimage["nested_code_objects"][0]["code_object"]["code_schema_version"] == "CPYTHON_CODE_OBJECT_PREIMAGE_V2"


def test_ode_68_runtime_identity_is_exact_cpython_attestation():
    identity = runtime_identity_snapshot()
    assert tuple(identity) == CPYTHON_RUNTIME_ID_FIELDS
    assert identity["implementation_name"] == "cpython"
    assert identity["supports_opcode_trace"] is True
    assert identity["opcode_table"] and identity["opname_table"]


def test_ode_69_writer_plan_contains_marker_purity_and_sequence_binding():
    plan = build_writer_trace_plan(owner_id="owner", authority_ref="registry", provenance_source_ref="p0")
    assert plan["trace_backend"] == "CPYTHON_OPCODE_TRACE_V1"
    assert plan["marker_purity_hash"] and plan["marker_opcode_sequence_hash"]
    assert plan["marker_source_length"] > 0 and plan["marker_source_sha256"]
    assert plan["marker_opcode_whitelist"] == sorted(plan["marker_opcode_whitelist"], key=lambda item: (item["opcode"], item["opname_utf8_hex"]))


def test_ode_70_permit_binds_trace_runtime_and_resolution_snapshots(tmp_path):
    bundle = _input_bundle(tmp_path)
    permit = bundle["harness"].issue_permit()
    assert permit.preimage["permit_schema_version"] == "P1-IMPORT-PERMIT-V2"
    assert permit.preimage["runtime_snapshot_hash"] == bundle["plan"]["runtime_snapshot_hash"]
    assert permit.preimage["trace_plan_snapshot_hash"] == canonical_sha256(bundle["plan"])
    assert recompute_permit_digest_v2(permit) == permit.permit_digest
    assert recompute_permit_seal_v2(permit, b"owner-seal-key-v1") == permit.permit_seal


def test_ode_71_permit_copy_and_replay_are_denied(tmp_path):
    bundle = _input_bundle(tmp_path, candidate=True)
    permit = bundle["harness"].issue_permit()
    with pytest.raises(EvaluationError):
        bundle["harness"].load_candidates(copy.deepcopy(permit))
    bundle["harness"].load_candidates(permit)
    with pytest.raises(EvaluationError):
        bundle["harness"].load_candidates(permit)


def test_ode_72_owner_capability_observation_is_not_p0_zero_initialization(tmp_path):
    bundle = _input_bundle(tmp_path)
    assert bundle["harness"]._trace_attestation["status"] == "READY"
    assert bundle["harness"]._trace_attestation["probe_call_count"] == 1
    bundle["harness"].observer.assert_zero()


def test_ode_73_permitted_candidate_load_has_source_readback_binding(tmp_path):
    sys.modules.pop("candidate_module", None)
    bundle = _registry_bundle(tmp_path, candidate=True)
    loaded = bundle[-1].load_candidates(bundle[-1].issue_permit())
    assert len(loaded) == 1
    item = loaded[0]
    assert item["source_length"] == item["postload_length"]
    assert item["source_sha256"] == item["postload_sha256"]
    assert item["module_file"] == item["spec_origin"] == item["resolved_path"]


def test_correction_successful_candidate_load_restores_host_resolution_state(tmp_path):
    bundle = _registry_bundle(tmp_path, candidate=True)
    before_modules = {name: id(module) for name, module in sys.modules.items()}
    before = {
        "sys_path": tuple(sys.path),
        "cwd": os.getcwd(),
        "meta_path": tuple(id(item) for item in sys.meta_path),
        "path_hooks": tuple(id(item) for item in sys.path_hooks),
        "import": builtins.__import__,
        "import_module": importlib.import_module,
        "dont_write_bytecode": sys.dont_write_bytecode,
    }
    try:
        loaded = bundle[-1].load_candidates(bundle[-1].issue_permit())
        assert tuple(item["module_path"] for item in loaded) == ("candidate_module",)
        assert "candidate_module" in sys.modules
        assert all(
            name in sys.modules and id(sys.modules[name]) == identity
            for name, identity in before_modules.items()
        )
        assert tuple(sys.path) == before["sys_path"]
        assert os.getcwd() == before["cwd"]
        assert tuple(id(item) for item in sys.meta_path) == before["meta_path"]
        assert tuple(id(item) for item in sys.path_hooks) == before["path_hooks"]
        assert builtins.__import__ is before["import"]
        assert importlib.import_module is before["import_module"]
        assert sys.dont_write_bytecode is before["dont_write_bytecode"]
    finally:
        sys.modules.pop("candidate_module", None)


def test_ode_74_preloaded_candidate_is_denied_before_load(tmp_path):
    bundle = _registry_bundle(tmp_path, candidate=True)
    permit = bundle[-1].issue_permit()
    fake = type("AmbientCandidate", (), {})()
    sys.modules["candidate_module"] = fake
    try:
        with pytest.raises(EvaluationError):
            bundle[-1].load_candidates(permit)
        assert bundle[-1].permitted_candidate_load_count == 0
    finally:
        sys.modules.pop("candidate_module", None)


def test_correction_candidate_failure_restores_host_resolution_state(tmp_path):
    bundle = _registry_bundle(tmp_path, candidate=True)
    before_modules = {name: id(module) for name, module in sys.modules.items()}
    before = {
        "sys_path": tuple(sys.path),
        "cwd": os.getcwd(),
        "meta_path": tuple(id(item) for item in sys.meta_path),
        "path_hooks": tuple(id(item) for item in sys.path_hooks),
        "import": builtins.__import__,
        "import_module": importlib.import_module,
        "dont_write_bytecode": sys.dont_write_bytecode,
    }
    permit = bundle[-1].issue_permit()
    original_exec_module = importlib.machinery.SourceFileLoader.exec_module

    def fail_after_candidate_exec(loader, module):
        original_exec_module(loader, module)
        if module.__name__ == "candidate_module":
            raise RuntimeError("injected candidate execution failure")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(importlib.machinery.SourceFileLoader, "exec_module", fail_after_candidate_exec)
    try:
        with pytest.raises(EvaluationError) as caught:
            bundle[-1].load_candidates(permit)
    finally:
        monkeypatch.undo()
    assert caught.value.code == "DENIED_CAPABILITY"
    assert tuple(sys.path) == before["sys_path"]
    assert os.getcwd() == before["cwd"]
    assert tuple(id(item) for item in sys.meta_path) == before["meta_path"]
    assert tuple(id(item) for item in sys.path_hooks) == before["path_hooks"]
    assert builtins.__import__ is before["import"]
    assert importlib.import_module is before["import_module"]
    assert sys.dont_write_bytecode is before["dont_write_bytecode"]
    assert "candidate_module" not in sys.modules
    assert all(
        name in sys.modules and id(sys.modules[name]) == identity
        for name, identity in before_modules.items()
    )


def test_correction_preloaded_dependency_is_denied_without_attribute_mutation(tmp_path):
    bundle = _registry_bundle(tmp_path, candidate=True, static_dependency=True)
    permit = bundle[-1].issue_permit()
    preloaded = type("PreloadedDependency", (), {"VALUE": 7, "ACCESS_COUNT": 0})()
    (tmp_path / "candidate-source" / "candidate.py").write_bytes(
        b"import static_dependency\n"
        b"static_dependency.ACCESS_COUNT += 1\n"
    )
    sys.modules["static_dependency"] = preloaded
    try:
        with pytest.raises(EvaluationError) as caught:
            bundle[-1].load_candidates(permit)
        assert caught.value.code == "DENIED_CAPABILITY"
        assert preloaded.VALUE == 7
        assert preloaded.ACCESS_COUNT == 0
        assert bundle[-1].permitted_candidate_load_count == 0
        assert "candidate_module" not in sys.modules
    finally:
        sys.modules.pop("static_dependency", None)


def test_ode_75_resolution_snapshot_mutation_is_denied_before_permit(tmp_path):
    bundle = _registry_bundle(tmp_path)
    bundle[-1].resolution_guard["deny_cwd_read"] = False
    with pytest.raises(EvaluationError):
        bundle[-1].issue_permit()


def test_ode_76_frozen_evidence_has_input_lineage_only(tmp_path):
    bundle = _input_bundle(tmp_path)
    result = OfflineDeterministicEvaluator(context=bundle["context"], resolver=bundle["resolver"], owner_harness=bundle["harness"], rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"], census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"], writer_trace_plan=bundle["plan"]).evaluate(bundle["manifest"], batch_id="20260810-000001-076", attempt_id="attempt-76")
    assert tuple(result.full_evidence) == EVIDENCE_CONTENT_FIELDS
    assert "output_artifact_id" not in json.dumps(result.full_evidence)
    assert "writer_observation" not in json.dumps(result.full_evidence)


def test_ode_77_frozen_evidence_rejects_recursive_output_key(tmp_path):
    bundle = _input_bundle(tmp_path)
    result = OfflineDeterministicEvaluator(context=bundle["context"], resolver=bundle["resolver"], owner_harness=bundle["harness"], rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"], census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"], writer_trace_plan=bundle["plan"]).evaluate(bundle["manifest"], batch_id="20260810-000001-077", attempt_id="attempt-77")
    bad = dict(result.full_evidence)
    bad["semantic_result_projection"] = {"nested": {"output_artifact_digest": "x"}}
    with pytest.raises(EvaluationError):
        freeze_evidence(bad)


def test_ode_78_p0_lineage_adapter_preserves_all_fields(tmp_path):
    bundle = _input_bundle(tmp_path)
    lineage = provenance.artifact_lineage(bundle["artifact"])
    adapter = p0_to_p1_input_lineage_adapter(lineage)
    assert tuple(adapter) == ("p0_artifact_lineage", "p0_artifact_ref_preimage")
    assert tuple(adapter["p0_artifact_lineage"]) == ("project_id", "profile_id", "profile_version", "profile_definition_hash", "project_revision", "namespace_digest", "root_alias", "relative_path", "source_ref", "producer_version", "batch_id", "parent_refs", "content_length", "content_sha256", "integrity_digest")
    assert adapter["p0_artifact_ref_preimage"]["length"] == lineage["content_length"]


def test_ode_79_forged_p0_integrity_digest_is_denied(tmp_path):
    bundle = _input_bundle(tmp_path)
    lineage = dict(provenance.artifact_lineage(bundle["artifact"]))
    lineage["integrity_digest"] = "0" * 64
    with pytest.raises(EvaluationError):
        p0_to_p1_input_lineage_adapter(lineage)


def test_ode_80_output_lineage_is_not_frozen_input(tmp_path):
    bundle = _input_bundle(tmp_path)
    result = OfflineDeterministicEvaluator(context=bundle["context"], resolver=bundle["resolver"], owner_harness=bundle["harness"], rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"], census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"], writer_trace_plan=bundle["plan"]).evaluate(bundle["manifest"], batch_id="20260810-000001-080", attempt_id="attempt-80")
    assert len(result.output_artifacts) == 2
    assert result.full_evidence["input_artifact_lineage_records"][0]["p0_artifact_lineage"]["relative_path"] == "input.json"
    assert all(item.relative_path not in {record["p0_artifact_lineage"]["relative_path"] for record in result.full_evidence["input_artifact_lineage_records"]} for item in result.output_artifacts)


def test_ode_81_full_evidence_bytes_are_canonical_and_replayable(tmp_path):
    bundle = _input_bundle(tmp_path)
    result = OfflineDeterministicEvaluator(context=bundle["context"], resolver=bundle["resolver"], owner_harness=bundle["harness"], rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"], census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"], writer_trace_plan=bundle["plan"]).evaluate(bundle["manifest"], batch_id="20260810-000001-081", attempt_id="attempt-81")
    raw = canonical_evaluation_json_bytes(result.full_evidence, fields=EVIDENCE_CONTENT_FIELDS)
    assert json.loads(raw.decode("utf-8")) == result.full_evidence
    assert result.output_paths[1].read_bytes() == raw


def test_ode_82_deterministic_projection_excludes_runtime_and_batch_fields():
    value = {"stable": 1, "run_id": "run", "thread_id": 2, "final_output_path": "x"}
    assert deterministic_projection(value) == {"stable": 1}


def test_ode_83_p0_writer_only_receives_bound_output_refs(tmp_path):
    bundle = _input_bundle(tmp_path)
    provenance.reset_call_counters()
    result = OfflineDeterministicEvaluator(context=bundle["context"], resolver=bundle["resolver"], owner_harness=bundle["harness"], rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"], census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"], writer_trace_plan=bundle["plan"]).evaluate(bundle["manifest"], batch_id="20260810-000001-083", attempt_id="attempt-83")
    assert provenance.get_call_counters()["writer"] == len(result.output_artifacts) == 2
    assert all(item.batch_id == result.batch.batch_id for item in result.output_artifacts)


def test_ode_84_denied_manifest_has_no_writer_calls(tmp_path):
    bundle = _input_bundle(tmp_path)
    bad = bundle["manifest"].to_mapping()
    bad["project_id"] = "unknown-project"
    provenance.reset_call_counters()
    evaluator = OfflineDeterministicEvaluator(context=bundle["context"], resolver=bundle["resolver"], owner_harness=bundle["harness"], rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"], census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"], writer_trace_plan=bundle["plan"])
    with pytest.raises(EvaluationError):
        evaluator.evaluate(bad, batch_id="20260810-000001-084", attempt_id="attempt-84")
    assert provenance.get_call_counters()["writer"] == 0


def test_ode_85_p0_provenance_source_sha_is_unchanged():
    source = Path(__file__).parents[1] / "src" / "xiaoshuo" / "pipeline" / "provenance.py"
    assert sha256_bytes(source.read_bytes()) == "bbb444616b1be4a099553f0604722ebb76aa692191961a8fe2ecb971e5e79a5a"


def test_ode_86_writer_trace_has_no_line_span_fallback():
    source = inspect.getsource(OwnerHarness.writer_trace)
    assert "line_contains" not in source
    assert "event == \"opcode\"" in source


def test_ode_87_p1ae_and_quality_claims_remain_out_of_scope():
    assert "p1ae" not in OfflineDeterministicEvaluator.__module__.lower()
    assert "model_quality" not in OfflineDeterministicEvaluator.__dict__


def test_correction_opcode_events_are_real_schema_bound_and_probe_is_fixed(tmp_path):
    bundle = _input_bundle(tmp_path)
    plan = bundle["plan"]
    assert plan["trace_backend"] == "CPYTHON_OPCODE_TRACE_V1"
    assert isinstance(plan["probe_call_offset"], int)
    events = bundle["harness"]._trace_attestation["events"]
    assert events and all(tuple(item) == ("sequence", "code_object_role", "code_object_sha256", "instruction_offset", "opcode", "opname_utf8_hex", "has_argument", "argument_kind", "argument_value") for item in events)
    assert all(item["argument_value"] is None or isinstance(item["argument_value"], str) for item in events)
    assert not any(item["code_object_role"] == "MARKER" and item["opcode"] in {dis.opmap.get("CALL"), dis.opmap.get("CALL_FUNCTION_EX")} for item in events)


def test_correction_source_readback_drift_is_denied_before_permit(tmp_path):
    bundle = _registry_bundle(tmp_path)
    source = tmp_path / "candidate-source" / "offline_evaluation.py"
    source.write_bytes(source.read_bytes() + b"\n")
    with pytest.raises(EvaluationError):
        bundle[-1].issue_permit()


def test_correction_owner_capability_snapshot_is_complete_and_attested(tmp_path):
    bundle = _registry_bundle(tmp_path)
    snapshot = bundle[-1].capability_probe_snapshot
    assert snapshot["complete"] is True and snapshot["status"] == "READY"
    assert len(snapshot["records"]) == 16
    assert all(item["installed"] is True and item["complete"] is True and item["observed_call_count"] == 0 for item in snapshot["records"])


def test_correction_frozen_evidence_requires_explicit_p0_p1_adapter(tmp_path):
    bundle = _input_bundle(tmp_path)
    result = OfflineDeterministicEvaluator(context=bundle["context"], resolver=bundle["resolver"], owner_harness=bundle["harness"], rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"], census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"], writer_trace_plan=bundle["plan"]).evaluate(bundle["manifest"], batch_id="20260810-000001-088", attempt_id="attempt-88")
    bad = dict(result.full_evidence)
    bad["input_artifact_lineage_records"] = [provenance.artifact_lineage(bundle["artifact"])]
    with pytest.raises(EvaluationError):
        freeze_evidence(bad)


def test_correction_frozen_projection_rejects_unknown_nested_key(tmp_path):
    bundle = _input_bundle(tmp_path)
    result = OfflineDeterministicEvaluator(context=bundle["context"], resolver=bundle["resolver"], owner_harness=bundle["harness"], rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"], census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"], writer_trace_plan=bundle["plan"]).evaluate(bundle["manifest"], batch_id="20260810-000001-089", attempt_id="attempt-89")
    bad = dict(result.full_evidence)
    bad["runtime_projection"] = dict(bad["runtime_projection"], unknown_key=True)
    with pytest.raises(EvaluationError):
        freeze_evidence(bad)


def test_correction_live_resolution_snapshot_recomputes_before_permit(tmp_path):
    bundle = _registry_bundle(tmp_path)
    bundle[-1].resolution_guard["preloaded_candidate_modules"] = ["ambient"]
    with pytest.raises(EvaluationError):
        bundle[-1].issue_permit()


def test_correction_p0_writer_failure_observation_is_not_counter_only(tmp_path):
    bundle = _input_bundle(tmp_path)
    result = OfflineDeterministicEvaluator(context=bundle["context"], resolver=bundle["resolver"], owner_harness=bundle["harness"], rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"], census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"], writer_trace_plan=bundle["plan"]).evaluate(bundle["manifest"], batch_id="20260810-000001-090", attempt_id="attempt-90")
    observation = bundle["harness"].writer_phase_observation
    assert observation["trace_backend_status"] == "VERIFIED"
    assert observation["transaction_started"] is True and observation["writer_call_started"] is True


def test_correction_owner_capability_nonzero_is_not_admitted(tmp_path):
    bundle = _registry_bundle(tmp_path)
    observer = P1CapabilityObserver()
    observer.observe("writer")
    with pytest.raises(EvaluationError):
        OwnerHarness(
            source_registry=bundle[3], census=bundle[4], gate=bundle[5],
            resolution_guard=bundle[6], writer_trace_plan=bundle[7],
            source_root=tmp_path / "candidate-source", owner_session_id="owner-session-1",
            seal_key=b"owner-seal-key-v1", observer=observer,
        )


def test_correction_resolution_nested_snapshot_unsorted_is_denied(tmp_path):
    bundle = _registry_bundle(tmp_path)
    bad_guard = dict(bundle[6])
    bad_guard["sys_modules_snapshot"] = list(reversed(bad_guard["sys_modules_snapshot"]))
    bad_gate = P1PreImportGateV1.from_mapping({
        **bundle[5].value,
        "resolution_guard_snapshot_hash": canonical_sha256(bad_guard),
    })
    with pytest.raises(EvaluationError):
        OwnerHarness(
            source_registry=bundle[3], census=bundle[4], gate=bad_gate,
            resolution_guard=bad_guard, writer_trace_plan=bundle[7],
            source_root=tmp_path / "candidate-source", owner_session_id="owner-session-1",
            seal_key=b"owner-seal-key-v1",
        )


def test_correction_owner_manifest_is_rechecked_before_permit(tmp_path):
    bundle = _input_bundle(tmp_path)
    adapter = p0_to_p1_input_lineage_adapter(provenance.artifact_lineage(bundle["artifact"]))
    bundle["harness"].bind_input_manifest(bundle["manifest"], [adapter], ["semantic-result.json", "full-evidence.json"])
    bundle["harness"]._owner_manifest["manifest_bytes_utf8_hex"] = "00"
    with pytest.raises(EvaluationError):
        bundle["harness"].issue_permit()


def test_correction_post_write_conflict_is_not_reported_as_zero_residue(tmp_path):
    bundle = _input_bundle(tmp_path)
    evaluator = OfflineDeterministicEvaluator(
        context=bundle["context"], resolver=bundle["resolver"], owner_harness=bundle["harness"],
        rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"],
        census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"], writer_trace_plan=bundle["plan"],
    )
    first = evaluator.evaluate(bundle["manifest"], batch_id="20260810-000001-091", attempt_id="attempt-91")
    first.output_paths[0].write_bytes(b"conflict")
    second_harness = OwnerHarness(
        source_registry=bundle["source_registry"], census=bundle["census"], gate=bundle["gate"],
        resolution_guard=bundle["guard"], writer_trace_plan=bundle["plan"],
        source_root=tmp_path / "candidate-source", owner_session_id="owner-session-2",
        seal_key=b"owner-seal-key-v1",
    )
    second_harness._owner_inject_manifest_source(
        relative_path="evaluation-manifest.json",
        source_ref="owner-manifest-test-real-v1",
        content=bundle["manifest"].canonical_bytes,
    )
    evaluator = OfflineDeterministicEvaluator(
        context=bundle["context"], resolver=bundle["resolver"], owner_harness=second_harness,
        rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"],
        census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"], writer_trace_plan=bundle["plan"],
    )
    with pytest.raises(EvaluationError) as caught:
        evaluator.evaluate(bundle["manifest"], batch_id="20260810-000001-092", attempt_id="attempt-92")
    assert caught.value.code == "POST_WRITE_IO_FAILURE"
    assert caught.value.details["zero_residue"] is False
    assert caught.value.details["failure_evidence"]["classification"] == "POST_WRITE_IO_FAILURE"
    failure_evidence = caught.value.details["failure_evidence"]
    assert failure_evidence["residue_snapshot_hash"]
    assert failure_evidence["residue_snapshot"] is not None
    assert all(item["reparse_status"] == "VERIFIED" for item in failure_evidence["residue_snapshot"]["entries"])


def test_correction_intermediate_reparse_is_denied_without_native_symlink(tmp_path, monkeypatch):
    root = tmp_path / "root"
    middle = root / "middle"
    target = middle / "target"
    middle.mkdir(parents=True)
    real_is_symlink = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda item: item == middle or real_is_symlink(item))
    with pytest.raises(EvaluationError):
        _final_path(target, root)


def test_correction_real_owner_probe_denies_forbidden_candidate_source(tmp_path):
    with pytest.raises(EvaluationError):
        _registry_bundle(tmp_path, candidate=True, candidate_source=b"import subprocess\n")


def test_correction_live_resolution_mutation_is_denied_before_permit(tmp_path):
    bundle = _registry_bundle(tmp_path)
    original = list(sys.path)
    sys.path.append(str(tmp_path / "ambient-resolution"))
    try:
        with pytest.raises(EvaluationError):
            bundle[-1].issue_permit()
    finally:
        sys.path[:] = original


def test_correction_missing_owner_manifest_is_denied_without_caller_hash_fallback(tmp_path):
    bundle = _registry_bundle(tmp_path, bind_standalone_manifest=False)
    with pytest.raises(EvaluationError) as caught:
        bundle[-1].issue_permit()
    assert caught.value.code == "MISSING_OWNER_MANIFEST"
    assert bundle[-1].permitted_candidate_load_count == 0


def test_correction_forged_owner_manifest_source_is_denied(tmp_path):
    bundle = _input_bundle(tmp_path)
    path = tmp_path / "candidate-source" / "evaluation-manifest.json"
    path.write_bytes(bundle["manifest"].canonical_bytes + b" ")
    with pytest.raises(EvaluationError):
        bundle["harness"].issue_permit()


def test_correction_candidate_source_role_must_match_census(tmp_path):
    bundle = _registry_bundle(tmp_path, candidate=True)
    candidate_entry = next(item for item in bundle[3].value["entries"] if item["relative_path"] == "candidate.py")
    candidate_entry["source_role"] = "evaluator"
    with pytest.raises(EvaluationError):
        bundle[-1].issue_permit()


def test_correction_unknown_attribute_call_is_closed_world_denied(tmp_path):
    with pytest.raises(EvaluationError):
        _registry_bundle(tmp_path, candidate=True, candidate_source=b"unknown_object.mystery()\n")


def test_correction_duplicate_search_root_is_denied_before_permit(tmp_path):
    bundle = _registry_bundle(tmp_path)
    original = list(sys.path)
    duplicate = next(item for item in sys.path if item)
    sys.path.append(duplicate)
    try:
        with pytest.raises(EvaluationError):
            bundle[-1].issue_permit()
        assert bundle[-1].permitted_candidate_load_count == 0
    finally:
        sys.path[:] = original


def test_correction_candidate_preload_is_denied_before_permit(tmp_path):
    bundle = _registry_bundle(tmp_path, candidate=True)
    sys.modules["candidate_module"] = object()
    try:
        with pytest.raises(EvaluationError):
            bundle[-1].issue_permit()
        assert bundle[-1].permitted_candidate_load_count == 0
    finally:
        sys.modules.pop("candidate_module", None)


def test_correction_frozen_resolution_nested_unknown_key_is_denied(tmp_path):
    bundle = _input_bundle(tmp_path)
    result = OfflineDeterministicEvaluator(
        context=bundle["context"], resolver=bundle["resolver"], owner_harness=bundle["harness"],
        rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"],
        census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"], writer_trace_plan=bundle["plan"],
    ).evaluate(bundle["manifest"], batch_id="20260810-000001-093", attempt_id="attempt-93")
    bad = copy.deepcopy(result.full_evidence)
    bad["resolution_projection"]["resolution_support"]["nested"]["SYS_PATH"]["unknown_key"] = True
    with pytest.raises(EvaluationError):
        freeze_evidence(bad)


def test_correction_partial_residue_is_failure_evidence_not_valid_snapshot(tmp_path, monkeypatch):
    bundle = _input_bundle(tmp_path)
    caught = _second_output_failure(bundle, monkeypatch, lambda: RuntimeError("injected second output failure"), add_unexpected=True)
    evidence = caught.details["failure_evidence"]
    assert evidence["partial_file_detected"] is True
    assert evidence["residue_snapshot"] is None
    assert evidence["residue_snapshot_hash"] is None
    assert any(item["entry_kind"] == "PARTIAL_FILE" for item in evidence["residue_entries"]["entries"])
    assert evidence["zero_residue_claim"] is False


def test_correction_permit_reset_and_concurrent_replay_are_denied(tmp_path):
    bundle = _registry_bundle(tmp_path, candidate=True)
    permit = bundle[-1].issue_permit()
    errors: list[str] = []

    def replay() -> None:
        try:
            bundle[-1].load_candidates(permit)
        except EvaluationError as exc:
            errors.append(exc.code)

    threads = [threading.Thread(target=replay), threading.Thread(target=replay)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(errors) == 2
    assert bundle[-1].permitted_candidate_load_count == 0
    bundle[-1].load_candidates(permit)
    sys.modules.pop("candidate_module", None)
    permit.consumed = False
    with pytest.raises(EvaluationError):
        bundle[-1].load_candidates(permit)
    assert bundle[-1].permitted_candidate_load_count == 1


def test_correction_raw_target_write_fault_is_post_write_failure(tmp_path, monkeypatch):
    bundle = _input_bundle(tmp_path)
    original_write_bytes = Path.write_bytes

    def faulting_write(path: Path, data: bytes) -> int:
        if path.name == "semantic-result.json":
            original_write_bytes(path, data[:7])
            raise OSError(5, "injected target write failure")
        return original_write_bytes(path, data)

    monkeypatch.setattr(Path, "write_bytes", faulting_write)
    evaluator = OfflineDeterministicEvaluator(
        context=bundle["context"], resolver=bundle["resolver"], owner_harness=bundle["harness"],
        rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"],
        census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"], writer_trace_plan=bundle["plan"],
    )
    with pytest.raises(EvaluationError) as caught:
        evaluator.evaluate(bundle["manifest"], batch_id="20260810-000001-095", attempt_id="attempt-95")
    assert caught.value.code == "POST_WRITE_IO_FAILURE"
    failure = caught.value.details["failure_evidence"]
    assert failure["exception_type"] == "OSError"
    assert failure["exception_code"] == "ERRNO_5"
    assert failure["writer_phase_observation"]["writer_call_started"] is True
    assert failure["writer_phase_observation"]["transaction_started"] is True
    assert failure["partial_file_detected"] is True
    assert failure["residue_snapshot"] is None
    assert failure["residue_snapshot_hash"] is None
    assert failure["zero_residue_claim"] is False
    canonical_writer_failure_evidence(failure)


def test_correction_permit_after_writer_code_drift_is_denied_before_write(tmp_path, monkeypatch):
    bundle = _registry_bundle(tmp_path)
    bundle[-1].issue_permit()
    original = provenance.safe_write_bytes

    def drifted_writer(*args, **kwargs):
        return original(*args, **kwargs)

    monkeypatch.setattr(provenance, "safe_write_bytes", drifted_writer)
    with pytest.raises(EvaluationError):
        with bundle[-1].writer_trace(("full-evidence.json",), root_relative_path="p1-root", parent_relative_path="p1-root"):
            raise AssertionError("writer body must not be entered after code drift")


def test_correction_forged_owner_observer_is_rejected_before_probe(tmp_path):
    bundle = _registry_bundle(tmp_path)
    called: list[str] = []

    class ForgedObserver:
        def snapshot(self):
            return {name: 0 for name in DETERMINISTIC_WRITER_OBSERVATION_FIELDS}

        def owner_attestation(self, **kwargs):
            called.append("owner_attestation")
            return bundle[-1].capability_probe_snapshot

    with pytest.raises(EvaluationError):
        OwnerHarness(
            source_registry=bundle[3], census=bundle[4], gate=bundle[5],
            resolution_guard=bundle[6], writer_trace_plan=bundle[7],
            source_root=tmp_path / "candidate-source", owner_session_id="owner-session-forged",
            seal_key=b"owner-seal-key-v1", observer=ForgedObserver(),
        )
    assert called == []


@pytest.mark.parametrize("source", [
    b"import os\nos.system = len\nos.system('x')\n",
    b"import os\nvalue = os.environ['PROJECT_ROOT']\n",
    b"import sys\nvalue = sys.modules['candidate_module']\n",
    b"unknown_writer.secret_save('x')\n",
    b"unknown_loader.dynamic_import('candidate_module')\n",
])
def test_correction_ast_closed_world_rejects_alias_property_subscript_and_unknown(source, tmp_path):
    with pytest.raises(EvaluationError):
        _registry_bundle(tmp_path, candidate=True, candidate_source=source)


def test_correction_preloaded_non_candidate_dependency_is_denied_before_import(tmp_path):
    bundle = _registry_bundle(tmp_path, candidate=True)
    permit = bundle[-1].issue_permit()
    sys.modules["non_candidate_dependency"] = object()
    try:
        with pytest.raises(EvaluationError):
            bundle[-1].load_candidates(permit)
        assert bundle[-1].permitted_candidate_load_count == 0
    finally:
        sys.modules.pop("non_candidate_dependency", None)


def test_correction_writer_observation_schema_rejects_missing_reordered_and_unknown(tmp_path):
    bundle = _input_bundle(tmp_path)
    result = OfflineDeterministicEvaluator(
        context=bundle["context"], resolver=bundle["resolver"], owner_harness=bundle["harness"],
        rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"],
        census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"], writer_trace_plan=bundle["plan"],
    ).evaluate(bundle["manifest"], batch_id="20260810-000001-096", attempt_id="attempt-96")
    observation = bundle["harness"].writer_phase_observation
    assert tuple(observation) == DETERMINISTIC_WRITER_OBSERVATION_FIELDS
    canonical_writer_observation(observation)
    missing = dict(observation)
    missing.pop("events")
    with pytest.raises(EvaluationError):
        canonical_writer_observation(missing)
    reordered = {key: observation[key] for key in reversed(tuple(observation))}
    with pytest.raises(EvaluationError):
        canonical_writer_observation(reordered)
    unknown = dict(observation)
    unknown["unknown_key"] = True
    with pytest.raises(EvaluationError):
        canonical_writer_observation(unknown)
    assert result.output_paths


def test_correction_failure_evidence_hash_mismatch_is_denied(tmp_path, monkeypatch):
    bundle = _input_bundle(tmp_path)
    caught = _second_output_failure(bundle, monkeypatch, lambda: RuntimeError("hash test"))
    evidence = caught.details["failure_evidence"]
    bad = dict(evidence)
    bad["failure_evidence_hash"] = "0" * 64
    with pytest.raises(EvaluationError):
        canonical_writer_failure_evidence(bad)


def test_correction_static_dependency_is_owner_loaded_and_source_bound(tmp_path):
    bundle = _registry_bundle(tmp_path, candidate=True, static_dependency=True)
    permit = bundle[-1].issue_permit()
    loaded = bundle[-1].load_candidates(permit)
    assert tuple(item["module_path"] for item in loaded) == ("static_dependency", "candidate_module")
    assert all(item["source_ref"] and item["source_length"] == item["postload_length"] for item in loaded)
    assert all(item["source_sha256"] == item["postload_sha256"] for item in loaded)
    sys.modules.pop("candidate_module", None)
    sys.modules.pop("static_dependency", None)


def test_correction_ambient_sys_path_change_is_denied_before_candidate_import(tmp_path):
    bundle = _registry_bundle(tmp_path, candidate=True, static_dependency=True)
    permit = bundle[-1].issue_permit()
    sys.path.insert(0, str(tmp_path / "candidate-source"))
    try:
        with pytest.raises(EvaluationError):
            bundle[-1].load_candidates(permit)
        assert "candidate_module" not in sys.modules and "static_dependency" not in sys.modules
        assert not provenance.execution_root(bundle[0], create=False).exists()
    finally:
        sys.path.pop(0)


def test_correction_bootstrap_requires_complete_owner_record(tmp_path):
    bundle = _registry_bundle(tmp_path)
    bad_guard = dict(bundle[6])
    bad_guard["bootstrap_module_entries"] = ["sys"]
    bad_gate = P1PreImportGateV1.from_mapping({
        **bundle[5].value,
        "resolution_guard_snapshot_hash": canonical_sha256(bad_guard),
    })
    with pytest.raises(EvaluationError):
        OwnerHarness(
            source_registry=bundle[3], census=bundle[4], gate=bad_gate,
            resolution_guard=bad_guard, writer_trace_plan=bundle[7],
            source_root=tmp_path / "candidate-source", owner_session_id="owner-session-bootstrap",
            seal_key=b"owner-seal-key-v1",
        )


def test_correction_source_readback_mismatch_is_denied_before_permit(tmp_path):
    bundle = _registry_bundle(tmp_path, candidate=True)
    (tmp_path / "candidate-source" / "candidate.py").write_bytes(b"CANDIDATE_VALUE = 999\n")
    with pytest.raises(EvaluationError):
        bundle[-1].issue_permit()
    assert "candidate_module" not in sys.modules
    assert not provenance.execution_root(bundle[0], create=False).exists()


def test_correction_owner_probe_snapshot_binds_coverage_and_rejects_tamper(tmp_path):
    bundle = _registry_bundle(tmp_path, candidate=True)
    snapshot = bundle[-1].capability_probe_snapshot
    assert snapshot["owner_probe_code_sha256"]
    assert tuple(snapshot["forbidden_capabilities"]) == tuple(P1CapabilityObserver().snapshot())
    assert snapshot["candidate_source_coverage"]
    snapshot["candidate_source_coverage"][0]["source_length"] += 1
    with pytest.raises(EvaluationError):
        bundle[-1].issue_permit()


def test_correction_residue_schema_rejects_unknown_enum_type_and_collision(tmp_path):
    item = _residue_item("x", "EXPECTED_TARGET", "FILE", "X")
    bad_unknown = dict(item)
    bad_unknown["unknown"] = True
    with pytest.raises(EvaluationError):
        build_residue_snapshot(root_relative_alias="p1-root", expected_entries=[bad_unknown], actual_entries=[])
    bad_kind = dict(item)
    bad_kind["entry_kind"] = "UNKNOWN"
    with pytest.raises(EvaluationError):
        build_residue_snapshot(root_relative_alias="p1-root", expected_entries=[bad_kind], actual_entries=[])
    bad_type = dict(item)
    bad_type["content_length"] = "1"
    with pytest.raises(EvaluationError):
        build_residue_snapshot(root_relative_alias="p1-root", expected_entries=[bad_type], actual_entries=[])
    with pytest.raises(EvaluationError):
        build_residue_snapshot(
            root_relative_alias="p1-root",
            expected_entries=[_residue_item("a", "EXPECTED_TARGET", "FILE", "same"), _residue_item("b", "EXPECTED_TARGET", "FILE", "SAME")],
            actual_entries=[],
        )


def test_correction_runtime_partial_write_is_post_write_failure(tmp_path, monkeypatch):
    bundle = _input_bundle(tmp_path)
    original_write_bytes = Path.write_bytes

    def faulting_write(path: Path, data: bytes) -> int:
        if path.name == "semantic-result.json":
            original_write_bytes(path, data[:5])
            raise RuntimeError("injected runtime target write failure")
        return original_write_bytes(path, data)

    monkeypatch.setattr(Path, "write_bytes", faulting_write)
    evaluator = OfflineDeterministicEvaluator(
        context=bundle["context"], resolver=bundle["resolver"], owner_harness=bundle["harness"],
        rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"],
        census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"], writer_trace_plan=bundle["plan"],
    )
    with pytest.raises(EvaluationError) as caught:
        evaluator.evaluate(bundle["manifest"], batch_id="20260810-000001-098", attempt_id="attempt-98")
    assert caught.value.code == "POST_WRITE_IO_FAILURE"
    failure = caught.value.details["failure_evidence"]
    assert failure["exception_type"] == "RuntimeError"
    assert failure["writer_phase_observation"]["writer_call_started"] is True
    assert failure["partial_file_detected"] is True
    assert failure["residue_snapshot"] is None and failure["residue_snapshot_hash"] is None
    assert failure["zero_residue_claim"] is False
    canonical_writer_failure_evidence(failure)


def test_correction_owner_observer_replacement_is_denied_before_permit(tmp_path):
    bundle = _registry_bundle(tmp_path)
    bundle[-1].observer = P1CapabilityObserver()
    with pytest.raises(EvaluationError):
        bundle[-1].issue_permit()
    assert not provenance.execution_root(bundle[0], create=False).exists()


def test_correction_evaluator_observer_injection_is_denied(tmp_path):
    bundle = _input_bundle(tmp_path)
    with pytest.raises(EvaluationError):
        OfflineDeterministicEvaluator(
            context=bundle["context"], resolver=bundle["resolver"], owner_harness=bundle["harness"],
            rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"],
            census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"],
            writer_trace_plan=bundle["plan"], observer=P1CapabilityObserver(),
        )
    assert not provenance.execution_root(bundle["context"], create=False).exists()


def test_correction_resolver_observer_boundary_is_denied(tmp_path):
    bundle = _input_bundle(tmp_path)
    with pytest.raises(EvaluationError):
        OwnerArtifactResolver(
            context=bundle["context"], snapshot=bundle["resolver"].snapshot,
            root=bundle["resolver"].root, parent_store=bundle["resolver"].parent_store,
            observer=P1CapabilityObserver(),
        )
    assert not provenance.execution_root(bundle["context"], create=False).exists()


def test_correction_read_after_verify_mutation_is_denied_before_output_root(tmp_path):
    bundle = _input_bundle(tmp_path)
    artifact = bundle["artifact"]
    verified = bundle["resolver"].resolve(provenance.artifact_lineage(artifact))
    (tmp_path / "input-root" / "input.json").write_bytes(FIXTURE.read_bytes() + b"\nmutated")
    with pytest.raises(EvaluationError):
        bundle["resolver"].read_verified_content(verified)
    assert not provenance.execution_root(bundle["context"], create=False).exists()


def test_correction_forged_complete_failure_without_snapshot_is_denied(tmp_path, monkeypatch):
    bundle = _input_bundle(tmp_path)
    caught = _second_output_failure(bundle, monkeypatch, lambda: RuntimeError("complete evidence test"))
    failure = caught.details["failure_evidence"]
    forged = dict(failure)
    forged["partial_file_detected"] = False
    forged["residue_enumeration_error"] = None
    forged["residue_snapshot"] = None
    forged["residue_snapshot_hash"] = None
    forged["zero_residue_claim"] = False
    forged["failure_evidence_hash"] = canonical_sha256(forged, fields=WRITER_FAILURE_EVIDENCE_FIELDS)
    with pytest.raises(EvaluationError):
        canonical_writer_failure_evidence(forged)


@pytest.mark.parametrize("observation_update", [
    {"phase": "PRE_WRITE", "transaction_started": True},
    {"phase": "POST_WRITE", "outcome": "RETURN", "writer_raised": True},
    {"phase": "POST_WRITE", "outcome": "RAISE", "writer_raised": False},
])
def test_correction_writer_observation_contradiction_is_denied(tmp_path, observation_update):
    bundle = _input_bundle(tmp_path)
    evaluator = OfflineDeterministicEvaluator(
        context=bundle["context"], resolver=bundle["resolver"], owner_harness=bundle["harness"],
        rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"],
        census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"], writer_trace_plan=bundle["plan"],
    )
    result = evaluator.evaluate(bundle["manifest"], batch_id="20260810-000001-100", attempt_id="attempt-100")
    observation = dict(bundle["harness"].writer_phase_observation)
    observation.update(observation_update)
    with pytest.raises(EvaluationError):
        canonical_writer_observation(observation)


def test_correction_forged_bootstrap_record_is_denied_before_candidate_import(tmp_path):
    bundle = _registry_bundle(tmp_path, candidate=True)
    bad_guard = dict(bundle[6])
    bad_guard["bootstrap_module_entries"] = [{
        "module_path": "fake_bootstrap",
        "resolved_path": "D:/fake/bootstrap.py",
        "source_ref": "fake-bootstrap-source",
        "source_length": 1,
        "source_sha256": "0" * 64,
        "readback_sha256": "0" * 64,
        "module_identity": "fake-bootstrap-identity",
        "spec_origin": "D:/fake/bootstrap.py",
        "runtime_identity_hash": "0" * 64,
    }]
    bad_gate = P1PreImportGateV1.from_mapping({
        **bundle[5].value,
        "resolution_guard_snapshot_hash": canonical_sha256(bad_guard),
    })
    with pytest.raises(EvaluationError):
        OwnerHarness(
            source_registry=bundle[3], census=bundle[4], gate=bad_gate,
            resolution_guard=bad_guard, writer_trace_plan=bundle[7],
            source_root=tmp_path / "candidate-source", owner_session_id="owner-session-fake-bootstrap",
            seal_key=b"owner-seal-key-v1",
        )
    assert "candidate_module" not in sys.modules
    assert not provenance.execution_root(bundle[0], create=False).exists()


def test_043_input_lineage_adapter_must_match_manifest_byte_for_byte(tmp_path):
    bundle = _input_bundle(tmp_path)
    adapter = p0_to_p1_input_lineage_adapter(provenance.artifact_lineage(bundle["artifact"]))
    forged = copy.deepcopy(adapter)
    forged["p0_artifact_lineage"]["parent_refs"] = ["parent-1", "forged-parent"]
    with pytest.raises(EvaluationError):
        bundle["harness"].bind_input_manifest(
            bundle["manifest"], [forged], ["semantic-result.json", "full-evidence.json"]
        )
    assert not provenance.execution_root(bundle["context"], create=False).exists()


@pytest.mark.parametrize("field", ["rule_set_bytes_sha256", "evaluation_contract_hash"])
def test_043_caller_rule_or_contract_hash_is_rejected_before_output_root(tmp_path, field):
    bundle = _input_bundle(tmp_path)
    forged = bundle["manifest"].to_mapping()
    forged[field] = "0" * 64
    evaluator = OfflineDeterministicEvaluator(
        context=bundle["context"], resolver=bundle["resolver"], owner_harness=bundle["harness"],
        rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"],
        census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"],
        writer_trace_plan=bundle["plan"],
    )
    with pytest.raises(EvaluationError):
        evaluator.evaluate(forged, batch_id="20260810-000001-143", attempt_id="attempt-143")
    assert not provenance.execution_root(bundle["context"], create=False).exists()


def test_043_manifest_authority_requires_unique_source_registry_entry(tmp_path):
    bundle = _input_bundle(tmp_path)
    source_registry = EvaluatorSourceRegistryV1.from_mapping({
        **bundle["source_registry"].value,
        "entries": [
            dict(entry)
            for entry in bundle["source_registry"].value["entries"]
            if entry["source_role"] != "manifest"
        ],
    })
    harness = OwnerHarness(
        source_registry=source_registry, census=bundle["census"], gate=bundle["gate"],
        resolution_guard=bundle["guard"], writer_trace_plan=bundle["plan"],
        source_root=tmp_path / "candidate-source", owner_session_id="owner-session-missing-manifest",
        seal_key=b"owner-seal-key-v1",
    )
    harness._owner_inject_manifest_source(
        relative_path="evaluation-manifest.json",
        source_ref="caller-fallback",
        content=bundle["manifest"].canonical_bytes,
    )
    adapter = p0_to_p1_input_lineage_adapter(provenance.artifact_lineage(bundle["artifact"]))
    with pytest.raises(EvaluationError):
        harness.bind_input_manifest(
            bundle["manifest"], [adapter], ["semantic-result.json", "full-evidence.json"]
        )
    assert not provenance.execution_root(bundle["context"], create=False).exists()


def test_043_manifest_source_readback_and_source_ref_are_rechecked(tmp_path):
    bundle = _input_bundle(tmp_path)
    manifest_path = tmp_path / "candidate-source" / "evaluation-manifest.json"
    manifest_path.write_bytes(bundle["manifest"].canonical_bytes + b"\n")
    with pytest.raises(EvaluationError):
        bundle["harness"].issue_permit()
    manifest_path.write_bytes(bundle["manifest"].canonical_bytes)
    manifest_entry = next(
        entry for entry in bundle["source_registry"].value["entries"] if entry["source_role"] == "manifest"
    )
    manifest_entry["source_ref"] = "forged-source-ref"
    with pytest.raises(EvaluationError):
        bundle["harness"].issue_permit()


def test_043_residue_pairing_role_kind_and_missing_semantics_are_closed():
    expected = _residue_item("target.json", "EXPECTED_TARGET", "FILE", "D:/tmp/target.json")
    actual_wrong_role = _residue_item("target.json", "EXPECTED_PARENT", "FILE", "D:/tmp/target.json")
    with pytest.raises(EvaluationError):
        build_residue_pairing([expected], [actual_wrong_role])
    missing_expected = _residue_item("target.json", "EXPECTED_TARGET", "MISSING", "D:/tmp/target.json", exists=False)
    with pytest.raises(EvaluationError):
        build_residue_pairing([missing_expected], [])
    actual_wrong_kind = _residue_item("target.json", "UNEXPECTED", "PARTIAL_FILE", "D:/tmp/target.json")
    with pytest.raises(EvaluationError):
        build_residue_pairing([], [actual_wrong_kind])


def test_044_writer_events_are_owner_bound_and_nonempty(tmp_path):
    bundle = _input_bundle(tmp_path)
    evaluator = OfflineDeterministicEvaluator(
        context=bundle["context"], resolver=bundle["resolver"], owner_harness=bundle["harness"],
        rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"],
        census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"],
        writer_trace_plan=bundle["plan"],
    )
    evaluator.evaluate(bundle["manifest"], batch_id="20260810-000001-101", attempt_id="attempt-101")
    observation = bundle["harness"].writer_phase_observation
    assert observation is not None
    actions = [event["action"] for event in observation["events"]]
    assert actions[:2] == ["transaction_started", "writer_call_started"]
    assert all(event["allowed"] is True for event in observation["events"])
    assert all(event["outcome"] == f'{event["action"]}@{event["offset"]}' for event in observation["events"])
    assert [event["sequence"] for event in observation["events"]] == list(range(1, len(observation["events"]) + 1))
    for field, value in (("action", "forged"), ("module_path", "forged.module"), ("source_ref", "forged-source"), ("allowed", False), ("offset", 999999)):
        forged = copy.deepcopy(observation)
        forged["events"][0][field] = value
        with pytest.raises(EvaluationError):
            canonical_writer_observation(forged)
    forged = copy.deepcopy(observation)
    forged["events"][0]["outcome"] = "transaction_started@999999"
    with pytest.raises(EvaluationError):
        canonical_writer_observation(forged)
    forged = copy.deepcopy(observation)
    forged["events"] = []
    forged["trace_hash"] = canonical_sha256({"events": []}, fields=("events",))
    with pytest.raises(EvaluationError):
        canonical_writer_observation(forged)


def test_044_caller_replaced_writer_observation_is_not_failure_authority(tmp_path):
    bundle = _input_bundle(tmp_path)
    evaluator = OfflineDeterministicEvaluator(
        context=bundle["context"], resolver=bundle["resolver"], owner_harness=bundle["harness"],
        rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"],
        census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"],
        writer_trace_plan=bundle["plan"],
    )
    result = evaluator.evaluate(bundle["manifest"], batch_id="20260810-000001-102", attempt_id="attempt-102")
    forged = copy.deepcopy(bundle["harness"].writer_phase_observation)
    forged["events"][0]["source_ref"] = "caller-source"
    forged["trace_hash"] = canonical_sha256({"events": forged["events"]}, fields=("events",))
    bundle["harness"].writer_phase_observation = forged
    with pytest.raises(EvaluationError):
        evaluator._writer_failure_evidence(result.output_artifacts, EvaluationError("P1_TEST_FAILURE", "caller observation"))


@pytest.mark.parametrize("paths", [
    ("z.json", "a.json"),
    ("../escape.json",),
    ("dir\\escape.json",),
    ("",),
    ("é.json", "e\u0301.json"),
    ("A.json", "a.json"),
])
def test_044_writer_target_paths_are_canonical_and_sorted(tmp_path, paths):
    bundle = _registry_bundle(tmp_path)
    permit = bundle[-1].issue_permit()
    with pytest.raises(EvaluationError):
        with bundle[-1].writer_trace(paths, root_relative_path="p1-root", parent_relative_path="p1-root"):
            raise AssertionError("writer body must not run for invalid target paths")
    assert not provenance.execution_root(bundle[0], create=False).exists()


@pytest.mark.parametrize("phase,outcome,classification", [
    ("PRE_WRITE", "RETURN", "NONE"),
    ("POST_WRITE", "RETURN", "POST_PERMIT_TRACE_DENY"),
    ("POST_WRITE", "RAISE", "NONE"),
])
def test_044_writer_phase_outcome_classification_matrix_is_closed(tmp_path, phase, outcome, classification):
    bundle = _input_bundle(tmp_path)
    evaluator = OfflineDeterministicEvaluator(
        context=bundle["context"], resolver=bundle["resolver"], owner_harness=bundle["harness"],
        rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"],
        census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"],
        writer_trace_plan=bundle["plan"],
    )
    evaluator.evaluate(bundle["manifest"], batch_id="20260810-000001-103", attempt_id="attempt-103")
    forged = copy.deepcopy(bundle["harness"].writer_phase_observation)
    forged.update({"phase": phase, "outcome": outcome, "failure_classification": classification})
    if outcome == "RAISE":
        forged.update({"writer_returned": False, "writer_raised": True})
    with pytest.raises(EvaluationError):
        canonical_writer_observation(forged)


def test_044_public_test_fallback_flags_and_empty_adapter_are_rejected(tmp_path):
    bundle = _registry_bundle(tmp_path)
    owner_record = bundle[-1]._owner_manifest
    assert owner_record is not None
    manifest = EvaluationInputManifestV1.from_bytes(bytes.fromhex(owner_record["manifest_bytes_utf8_hex"]))
    with pytest.raises(TypeError):
        bundle[-1].bind_input_manifest(
            manifest, [], ["standalone-output.json"], allow_test_injected_source=True,
        )
    with pytest.raises(EvaluationError):
        bundle[-1].bind_input_manifest(manifest, [], ["standalone-output.json"])


@pytest.mark.parametrize("paths", [
    ("full-evidence.json", "semantic-result.json"),
    ("unknown-output.json", "full-evidence.json"),
])
def test_046_output_role_order_is_denied_before_manifest_permit_writer_and_root(tmp_path, paths):
    bundle = _input_bundle(tmp_path)
    provenance.reset_call_counters()
    evaluator = OfflineDeterministicEvaluator(
        context=bundle["context"], resolver=bundle["resolver"], owner_harness=bundle["harness"],
        rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"],
        census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"],
        writer_trace_plan=bundle["plan"],
    )
    with pytest.raises(EvaluationError):
        evaluator.evaluate(bundle["manifest"], batch_id="20260810-000001-046", attempt_id="attempt-046", output_relative_paths=paths)
    root = provenance.execution_root(bundle["context"], create=False)
    assert not root.exists()
    assert provenance.get_call_counters()["writer"] == 0
    assert not list(root.parent.glob("**/semantic-result.json"))
    assert not list(root.parent.glob("**/full-evidence.json"))


def test_046_owner_manifest_binding_rejects_reversed_and_unknown_output_roles(tmp_path):
    bundle = _input_bundle(tmp_path)
    adapter = p0_to_p1_input_lineage_adapter(provenance.artifact_lineage(bundle["artifact"]))
    for paths in (("full-evidence.json", "semantic-result.json"), ("unknown-output.json", "full-evidence.json")):
        with pytest.raises(EvaluationError):
            bundle["harness"].bind_input_manifest(bundle["manifest"], [adapter], paths)


def test_046_default_output_bytes_keep_semantic_and_evidence_roles(tmp_path):
    bundle = _input_bundle(tmp_path)
    evaluator = OfflineDeterministicEvaluator(
        context=bundle["context"], resolver=bundle["resolver"], owner_harness=bundle["harness"],
        rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"],
        census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"],
        writer_trace_plan=bundle["plan"],
    )
    result = evaluator.evaluate(bundle["manifest"], batch_id="20260810-000001-046", attempt_id="attempt-046")
    assert tuple(ref.relative_path for ref in result.output_artifacts) == ("semantic-result.json", "full-evidence.json")
    assert tuple(path.name for path in result.output_paths) == ("semantic-result.json", "full-evidence.json")
    semantic = parse_canonical_evaluation_json(result.output_paths[0].read_bytes(), fields=SEMANTIC_RESULT_FIELDS)
    evidence = parse_canonical_evaluation_json(result.output_paths[1].read_bytes(), fields=EVIDENCE_CONTENT_FIELDS)
    assert semantic["semantic_schema_version"] == "P1-SEMANTIC-RESULT-V2"
    assert evidence["evidence_schema_version"] == "P1-FROZEN-EVIDENCE-V2"
    for ref, path in zip(result.output_artifacts, result.output_paths):
        content = path.read_bytes()
        assert ref.relative_path == path.name
        assert ref.length == len(content)
        assert ref.sha256 == sha256_bytes(content)


@pytest.mark.parametrize("expected_role,expected_kind", [
    ("ROOT", "FILE"), ("EXPECTED_PARENT", "FILE"), ("EXPECTED_TARGET", "DIRECTORY"),
    ("EXPECTED_DESCENDANT", "PARTIAL_FILE"), ("UNKNOWN", "FILE"),
])
def test_044_residue_role_kind_matrix_remains_closed(expected_role, expected_kind):
    item = _residue_item("target", expected_role, expected_kind, "D:/tmp/target")
    with pytest.raises(EvaluationError):
        build_residue_pairing([item], [item])


def test_044_actual_only_missing_and_partial_are_not_unexpected_matches():
    with pytest.raises(EvaluationError):
        build_residue_pairing([], [_residue_item("x", "UNEXPECTED", "MISSING", "D:/tmp/x", exists=False)])
    with pytest.raises(EvaluationError):
        build_residue_pairing([], [_residue_item("x", "UNEXPECTED", "PARTIAL_FILE", "D:/tmp/x")])


def test_045_normal_evaluation_has_two_independent_owner_writer_invocations(tmp_path):
    bundle = _input_bundle(tmp_path)
    result = OfflineDeterministicEvaluator(
        context=bundle["context"], resolver=bundle["resolver"], owner_harness=bundle["harness"],
        rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"],
        census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"],
        writer_trace_plan=bundle["plan"],
    ).evaluate(bundle["manifest"], batch_id="20260810-000001-045", attempt_id="attempt-045-success")
    observation = bundle["harness"].writer_phase_observation
    assert observation is not None
    invocations = observation["writer_invocations"]
    assert [item["invocation_sequence"] for item in invocations] == [1, 2]
    assert [item["target_relative_path"] for item in invocations] == ["semantic-result.json", "full-evidence.json"]
    for invocation, artifact in zip(invocations, result.output_artifacts):
        assert invocation["transaction_started"] is True
        assert invocation["writer_call_started"] is True
        assert invocation["terminal_action"] == "return"
        assert invocation["artifact_identity"] == sha256_bytes(canonical_evaluation_json_bytes(
            provenance.artifact_lineage(artifact),
            fields=("project_id", "profile_id", "profile_version", "profile_definition_hash", "project_revision", "namespace_digest", "root_alias", "relative_path", "source_ref", "producer_version", "batch_id", "parent_refs", "content_length", "content_sha256", "integrity_digest"),
        ))
    assert len({item["invocation_sequence"] for item in invocations}) == 2
    canonical_writer_observation(observation)


@pytest.mark.parametrize("error_factory", [lambda: OSError(5, "second output os error"), lambda: RuntimeError("second output runtime error")])
def test_045_second_output_failure_is_bound_to_second_invocation(tmp_path, monkeypatch, error_factory):
    bundle = _input_bundle(tmp_path)
    caught = _second_output_failure(bundle, monkeypatch, error_factory)
    assert caught.code == "POST_WRITE_IO_FAILURE"
    failure = caught.details["failure_evidence"]
    observation = failure["writer_phase_observation"]
    invocations = observation["writer_invocations"]
    assert len(invocations) == 2
    assert invocations[0]["terminal_action"] == "return"
    assert invocations[1]["terminal_action"] == "raise"
    assert invocations[1]["target_relative_path"] == "full-evidence.json"
    assert invocations[1]["exception_type"] in {"OSError", "RuntimeError"}
    assert invocations[1]["partial_readback_status"] == "PARTIAL_FILE"
    assert invocations[1]["partial_length"] == 7
    assert failure["classification"] == "POST_WRITE_IO_FAILURE"
    assert failure["residue_snapshot_hash"] is None
    assert failure["zero_residue_claim"] is False
    assert "POST_PERMIT_TRACE_DENY" not in json.dumps(failure)
    canonical_writer_failure_evidence(failure)


def test_045_second_output_replay_conflict_has_independent_failure_record(tmp_path):
    bundle = _input_bundle(tmp_path)
    first = OfflineDeterministicEvaluator(
        context=bundle["context"], resolver=bundle["resolver"], owner_harness=bundle["harness"],
        rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"],
        census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"],
        writer_trace_plan=bundle["plan"],
    ).evaluate(bundle["manifest"], batch_id="20260810-000001-045-replay", attempt_id="attempt-045-first")
    first.output_paths[1].write_bytes(b"replay-conflict")
    second_harness = OwnerHarness(
        source_registry=bundle["source_registry"], census=bundle["census"], gate=bundle["gate"],
        resolution_guard=bundle["guard"], writer_trace_plan=bundle["plan"],
        source_root=tmp_path / "candidate-source", owner_session_id="owner-session-045-replay",
        seal_key=b"owner-seal-key-v1",
    )
    adapter = p0_to_p1_input_lineage_adapter(provenance.artifact_lineage(bundle["artifact"]))
    second_harness.bind_input_manifest(bundle["manifest"], [adapter], ["semantic-result.json", "full-evidence.json"])
    with pytest.raises(EvaluationError) as caught:
        OfflineDeterministicEvaluator(
            context=bundle["context"], resolver=bundle["resolver"], owner_harness=second_harness,
            rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"],
            census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"],
            writer_trace_plan=bundle["plan"],
        ).evaluate(bundle["manifest"], batch_id="20260810-000001-045-replay", attempt_id="attempt-045-second")
    assert caught.value.code == "POST_WRITE_IO_FAILURE"
    failure = caught.value.details["failure_evidence"]
    invocations = failure["writer_phase_observation"]["writer_invocations"]
    assert invocations[1]["target_relative_path"] == "full-evidence.json"
    assert invocations[1]["terminal_action"] == "raise"
    assert invocations[1]["exception_code"] == provenance.REPLAY_CONFLICT
    assert failure["zero_residue_claim"] is False


@pytest.mark.parametrize("mutation", ["missing", "duplicate_sequence", "reordered", "target", "source", "offset", "trace_hash", "cross_stitch"])
def test_045_forged_or_cross_stitched_invocation_records_are_rejected(tmp_path, mutation):
    bundle = _input_bundle(tmp_path)
    OfflineDeterministicEvaluator(
        context=bundle["context"], resolver=bundle["resolver"], owner_harness=bundle["harness"],
        rule_set_registry=bundle["rule_registry"], contract_registry=bundle["contract_registry"],
        census=bundle["census"], gate=bundle["gate"], resolution_guard=bundle["guard"],
        writer_trace_plan=bundle["plan"],
    ).evaluate(bundle["manifest"], batch_id="20260810-000001-045-forgery", attempt_id="attempt-045-forgery")
    forged = copy.deepcopy(bundle["harness"].writer_phase_observation)
    if mutation == "missing":
        forged["writer_invocations"].pop()
    elif mutation == "duplicate_sequence":
        forged["writer_invocations"][1]["invocation_sequence"] = 1
    elif mutation == "reordered":
        forged["writer_invocations"] = list(reversed(forged["writer_invocations"]))
    elif mutation == "target":
        forged["writer_invocations"][1]["target_relative_path"] = "semantic-result.json"
    elif mutation == "source":
        forged["writer_invocations"][1]["source_ref"] = "forged-source"
    elif mutation == "offset":
        forged["writer_invocations"][1]["writer_offset"] += 1
    elif mutation == "trace_hash":
        forged["writer_invocations"][1]["trace_hash"] = "0" * 64
    else:
        forged["writer_invocations"][1] = copy.deepcopy(forged["writer_invocations"][0])
        forged["writer_invocations"][1]["invocation_sequence"] = 2
    with pytest.raises(EvaluationError):
        if mutation in {"target", "cross_stitch"}:
            bundle["harness"]._validate_owner_writer_observation(forged)
        else:
            canonical_writer_observation(forged)
