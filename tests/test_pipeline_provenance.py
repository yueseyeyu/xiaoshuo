"""P0 provenance acceptance tests; all fixtures and writes stay on D drive."""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import uuid
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))
EVIDENCE_ROOT = Path(r"D:\tmp\yeyu-ai-a3\pipeline-fitness-p0-provenance-corrective\20260810-000001-012")

from xiaoshuo.pipeline import provenance as pv


def _fixture(genre: str = "genre-a"):
    definition = pv.ProfileDefinitionV1(
        "profile-definition-v1",
        "profile-main",
        "1",
        genre,
        {"tone": "measured", "genre": genre},
        {"policy": "owner-controlled"},
    )
    provenance_bytes = f"owner-entry:{genre}".encode("utf-8")
    entry = pv.ProjectEntryV1(
        "project-entry-v1",
        "project-alpha",
        "revision-1",
        definition.profile_id,
        definition.profile_version,
        definition.definition_hash,
        genre,
        "ACTIVE",
        f"owner-entry-{genre}",
        pv.sha256_bytes(provenance_bytes),
    )
    owner = pv.ProjectRegistryOwner("composition-owner", "registry-source-v1")
    registry = pv.inject_project_registry(
        owner,
        [entry],
        registry_id="project-registry-v1",
        snapshot_id=f"snapshot-{genre}",
        owner_provenance_bytes={entry.entry_provenance_ref: provenance_bytes},
    )
    root_spec = pv.StageRootAlias(
        "p0-root",
        "pipeline-fitness-p0-provenance-implement",
        owner.owner_id,
        EVIDENCE_ROOT / "roots" / uuid.uuid4().hex,
    )
    project = pv.ProjectIdentity(entry.project_id)
    profile = pv.ProfileIdentity.from_definition(definition)
    namespace = pv.make_namespace(project, profile, entry.project_revision)
    parent_refs = ("root-input", "parent-a", "parent-b", namespace.namespace_digest)
    parent_store = pv.ParentRefStoreV1(
        owner.owner_id,
        owner.authoritative_source_ref,
        {
            parent_ref: pv.ParentRecordV1(
                parent_ref=parent_ref,
                project_id=entry.project_id,
                profile_id=definition.profile_id,
                profile_version=definition.profile_version,
                profile_definition_hash=definition.definition_hash,
                project_revision=entry.project_revision,
                namespace_digest=namespace.namespace_digest,
                root_alias=root_spec.alias,
                source_ref="owner-parent-store",
                producer_version="parent-producer-v1",
                batch_id="parent-batch-1",
                content_length=len(parent_ref.encode("utf-8")),
                content_sha256=pv.sha256_bytes(parent_ref.encode("utf-8")),
            )
            for parent_ref in parent_refs
        },
    )
    context = pv.create_execution_context(
        registry=registry,
        project_id=entry.project_id,
        profile_id=entry.profile_id,
        profile_version=entry.profile_version,
        profile_definition=definition,
        stage_alias=root_spec.stage_alias,
        root_alias=root_spec.alias,
        run_id="20260810-000001-012",
        producer_version="test-producer-v1",
        registry_owner_id=owner.owner_id,
        registry_source_ref=owner.authoritative_source_ref,
        registry_snapshot_hash=registry.registry_snapshot_hash,
        root_alias_registry={root_spec.alias: root_spec},
        parent_store=parent_store,
    )
    return definition, entry, owner, registry, root_spec, context, provenance_bytes


def _transition_fixture():
    old = _fixture("genre-a")
    new_definition = pv.ProfileDefinitionV1(
        "profile-definition-v1",
        "profile-main",
        "2",
        "genre-b",
        {"tone": "measured", "genre": "genre-b"},
        {"policy": "owner-controlled"},
    )
    new_bytes = b"owner-entry:genre-b"
    new_entry = pv.ProjectEntryV1(
        "project-entry-v1",
        "project-alpha",
        "revision-1",
        new_definition.profile_id,
        new_definition.profile_version,
        new_definition.definition_hash,
        new_definition.genre_identity,
        "ACTIVE",
        "owner-entry-genre-b",
        pv.sha256_bytes(new_bytes),
    )
    registry = pv.inject_project_registry(
        old[2],
        [old[1], new_entry],
        registry_id="project-registry-v1",
        snapshot_id="snapshot-transition",
        owner_provenance_bytes={
            old[1].entry_provenance_ref: old[6],
            new_entry.entry_provenance_ref: new_bytes,
        },
    )
    project = pv.ProjectIdentity(new_entry.project_id)
    profile = pv.ProfileIdentity.from_definition(new_definition)
    namespace = pv.make_namespace(project, profile, new_entry.project_revision)
    parent_refs = ("root-input", "parent-a", "parent-b", namespace.namespace_digest)
    parent_store = pv.ParentRefStoreV1(
        old[2].owner_id,
        old[2].authoritative_source_ref,
        {
            parent_ref: pv.ParentRecordV1(
                parent_ref=parent_ref,
                project_id=new_entry.project_id,
                profile_id=new_definition.profile_id,
                profile_version=new_definition.profile_version,
                profile_definition_hash=new_definition.definition_hash,
                project_revision=new_entry.project_revision,
                namespace_digest=namespace.namespace_digest,
                root_alias=old[4].alias,
                source_ref="owner-parent-store",
                producer_version="parent-producer-v1",
                batch_id="parent-batch-1",
                content_length=len(parent_ref.encode("utf-8")),
                content_sha256=pv.sha256_bytes(parent_ref.encode("utf-8")),
            )
            for parent_ref in parent_refs
        },
    )
    context = pv.create_execution_context(
        registry=registry,
        project_id="project-alpha",
        profile_id="profile-main",
        profile_version="2",
        profile_definition=new_definition,
        stage_alias=old[4].stage_alias,
        root_alias=old[4].alias,
        run_id="20260810-000001-012",
        producer_version="test-producer-v1",
        registry_owner_id=old[2].owner_id,
        registry_source_ref=old[2].authoritative_source_ref,
        registry_snapshot_hash=registry.registry_snapshot_hash,
        root_alias_registry={old[4].alias: old[4]},
        parent_store=parent_store,
    )
    return old[5], context


def test_three_identity_layers_and_genre_transition():
    definition, entry, _, registry, _, context, provenance_bytes = _fixture()
    assert context.project == pv.ProjectIdentity("project-alpha")
    assert context.profile == pv.ProfileIdentity.from_definition(definition)
    assert context.namespace.project_id == context.project.project_id
    assert context.namespace.profile_id == context.profile.profile_id
    assert context.namespace.project_revision == entry.project_revision
    assert context.namespace_digest == pv.canonical_sha256(context.namespace.to_preimage())
    assert entry.verify_provenance(provenance_bytes)
    old_context, new_context = _transition_fixture()
    assert old_context.project_id == new_context.project_id
    assert old_context.profile.profile_definition_hash != new_context.profile.profile_definition_hash
    assert old_context.namespace_digest != new_context.namespace_digest
    pv.assert_profile_transition(old_context, new_context)
    with pytest.raises(pv.ProvenanceError) as exc:
        pv.ensure_namespace_compatible(new_context, old_context.namespace_digest)
    assert exc.value.code == pv.OLD_NAMESPACE_ARTIFACT
    assert registry.registry_snapshot_hash == registry.compute_snapshot_hash()


def test_project_entry_and_ordered_registry_snapshot_preimages():
    _, new_context = _transition_fixture()
    registry = new_context.registry
    entry = registry.project_entries[0]
    owner = pv.ProjectRegistryOwner(registry.owner_id, registry.authoritative_source_ref)
    assert tuple(entry.to_preimage()) == pv.PROJECT_ENTRY_FIELDS
    assert tuple(registry.to_preimage()) == pv.REGISTRY_SNAPSHOT_FIELDS
    assert tuple(registry.to_preimage()["project_entries"][0]) == pv.PROJECT_ENTRY_FIELDS
    reversed_registry = pv.inject_project_registry(
        owner,
        list(reversed(registry.project_entries)),
        registry_id=registry.registry_id,
        snapshot_id=registry.snapshot_id,
        owner_provenance_bytes=registry.owner_provenance_bytes,
    )
    assert reversed_registry.registry_snapshot_hash != registry.registry_snapshot_hash


def test_registry_source_snapshot_unknown_project_and_profile_deny_early():
    definition, entry, owner, registry, root_spec, context, _ = _fixture()
    common = dict(
        registry=registry,
        profile_id=entry.profile_id,
        profile_version=entry.profile_version,
        profile_definition=definition,
        stage_alias=root_spec.stage_alias,
        root_alias=root_spec.alias,
        run_id="20260810-000001-012",
        producer_version="test-producer-v1",
        registry_owner_id=owner.owner_id,
        registry_source_ref=owner.authoritative_source_ref,
        registry_snapshot_hash=registry.registry_snapshot_hash,
        root_alias_registry={root_spec.alias: root_spec},
        parent_store=context.parent_store,
    )
    for kwargs, code in (
        ({"project_id": "unknown-project"}, pv.UNKNOWN_PROJECT),
        ({"project_id": entry.project_id, "registry_source_ref": "other-source"}, pv.REGISTRY_SOURCE_MISMATCH),
        ({"project_id": entry.project_id, "registry_snapshot_hash": "0" * 64}, pv.REGISTRY_SNAPSHOT_MISMATCH),
        ({"project_id": entry.project_id, "profile_id": "unknown-profile"}, pv.UNKNOWN_PROFILE),
    ):
        with pytest.raises(pv.ProvenanceError) as exc:
            pv.create_execution_context(**{**common, **kwargs})
        assert exc.value.code == code
    

def test_stage_run_binding_and_context_required_before_paths_or_writes():
    _, entry, owner, registry, root_spec, context, _ = _fixture()
    from xiaoshuo.infra import pipeline_state
    from xiaoshuo.pipeline import checkpoint, paths

    with pytest.raises(pv.ProvenanceError) as exc:
        paths.novels_dir()
    assert exc.value.code == pv.MISSING_PROJECT_CONTEXT
    with pytest.raises(pv.ProvenanceError) as exc:
        checkpoint.mark_done("book_processor")
    assert exc.value.code == pv.MISSING_PROJECT_CONTEXT
    with pytest.raises(pv.ProvenanceError) as exc:
        pipeline_state.write_stage("stage")
    assert exc.value.code == pv.MISSING_PROJECT_CONTEXT
    with pytest.raises(pv.ProvenanceError) as exc:
        pv.create_execution_context(
            registry=registry,
            project_id=entry.project_id,
            profile_id=entry.profile_id,
            profile_version=entry.profile_version,
            profile_definition=_fixture()[0],
            stage_alias=root_spec.stage_alias,
            root_alias=root_spec.alias,
            run_id="invalid-run",
            producer_version="test-producer-v1",
            registry_owner_id=owner.owner_id,
            registry_source_ref=owner.authoritative_source_ref,
            registry_snapshot_hash=registry.registry_snapshot_hash,
            root_alias_registry={root_spec.alias: root_spec},
            parent_store=context.parent_store,
        )
    assert exc.value.code == pv.INVALID_RUN_ID
    with pv.activate_execution_context(context):
        assert paths.novels_dir("genre-a").is_relative_to(pv.execution_root(context))
        checkpoint.CHECKPOINT_DIR = None
        content = b"lineage source\n"
        artifact_ref = pv.make_artifact_ref(
            context,
            "artifacts/state-source.txt",
            content,
            source_ref="test-state",
            batch_id="batch-state",
            parent_refs=("root-input",),
        )
        checkpoint_path = checkpoint.mark_done(
            "book_processor",
            artifact_ref=artifact_ref,
            content=content,
            expected_batch_id="batch-state",
            context=context,
        )
        state_path = pipeline_state.write_stage(
            "stage",
            artifact_ref=artifact_ref,
            content=content,
            expected_batch_id="batch-state",
            context=context,
        )
        assert checkpoint_path.drive.upper() == "D:"
        assert state_path.drive.upper() == "D:"
        assert checkpoint_path.is_relative_to(pv.execution_root(context))
        assert state_path.is_relative_to(pv.execution_root(context))


def test_batch_envelope_two_pass_and_explicit_root_run_hash_scope():
    _, _, _, _, _, context, _ = _fixture()
    trace: list[str] = []
    batch, envelope = pv.build_batch_and_envelope(
        context,
        batch_id="batch-1",
        attempt_id="attempt-1",
        config_hash="config-hash-1",
        failure_chain=[{"code": "none"}],
        phase_trace=trace,
    )
    assert trace == ["batch_digest", "equality_gate", "evidence_envelope_hash", "finalize", "recompute"]
    assert batch.root_alias == context.root_alias
    assert batch.run_id == context.run_id
    assert envelope.execution_batch_id == batch.batch_id
    assert envelope.root_alias == batch.root_alias
    assert envelope.run_id == batch.run_id
    assert envelope.batch_digest == batch.batch_digest
    assert pv.recompute_batch_digest(batch) == batch.batch_digest
    assert pv.recompute_evidence_envelope_hash(envelope) == envelope.evidence_envelope_hash
    assert tuple(batch.preimage().to_preimage()) == pv.EXECUTION_BATCH_PREIMAGE_FIELDS
    assert tuple(envelope.preimage().to_preimage()) == pv.EVIDENCE_ENVELOPE_PREIMAGE_FIELDS
    assert pv.recompute_batch_digest(replace(batch.preimage(), root_alias="other-root")) != batch.batch_digest
    assert pv.recompute_batch_digest(replace(batch.preimage(), run_id="20260810-000001-013")) != batch.batch_digest
    with pytest.raises(pv.ProvenanceError) as exc:
        pv.hash_execution_batch_preimage({**batch.preimage().to_preimage(), "batch_digest": batch.batch_digest})
    assert exc.value.code == pv.SELF_REFERENTIAL_HASH_PREIMAGE
    with pytest.raises(pv.ProvenanceError) as exc:
        replace(context, root_alias="other-root")
    assert exc.value.code == pv.UNKNOWN_STAGE_ALIAS
    with pytest.raises(pv.ProvenanceError) as exc:
        replace(context, run_id="bad-run")
    assert exc.value.code == pv.INVALID_RUN_ID
    

@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("execution_batch_id", "wrong-batch", pv.EXECUTION_BATCH_ID_MISMATCH),
        ("namespace_digest", "0" * 64, pv.BATCH_NAMESPACE_MISMATCH),
        ("stage_alias", "wrong-stage", pv.BATCH_STAGE_ALIAS_MISMATCH),
        ("root_alias", "wrong-root", pv.BATCH_ROOT_ALIAS_MISMATCH),
        ("run_id", "20260810-000001-013", pv.BATCH_RUN_ID_MISMATCH),
        ("producer_version", "wrong-producer", pv.BATCH_PRODUCER_VERSION_MISMATCH),
        ("failure_chain", [{"code": "different"}], pv.BATCH_FAILURE_CHAIN_MISMATCH),
        ("batch_digest", "0" * 64, pv.BATCH_DIGEST_MISMATCH),
    ],
)
def test_every_batch_envelope_duplicate_mismatch_fails_closed(field, value, code):
    _, _, _, _, _, context, _ = _fixture()
    with pytest.raises(pv.ProvenanceError) as exc:
        pv.build_batch_and_envelope(
            context,
            batch_id="batch-1",
            attempt_id="attempt-1",
            config_hash="config-hash-1",
            failure_chain=[{"code": "none"}],
            envelope_overrides={field: value},
        )
    assert exc.value.code == code
    assert exc.value.details["binding_code"] == pv.BATCH_ENVELOPE_BINDING_MISMATCH
    

def test_capability_census_denies_before_import_main_in_process_or_spawn():
    pv.reset_call_counters()
    context = _fixture()[5]
    probes: list[str] = []

    def import_probe(*args, **kwargs):
        probes.append("import")
        raise AssertionError("importlib.import_module must not be called")

    def popen_probe(*args, **kwargs):
        probes.append("popen")
        raise AssertionError("subprocess.Popen must not be called")

    manifests = [
        (pv.LegacyCapabilityManifest("dynamic", dynamic_imports_declared=False), pv.UNKNOWN_DYNAMIC_IMPORT),
        (pv.LegacyCapabilityManifest("dependency", dynamic_imports_declared=True, unresolved_dependencies=("x",)), pv.UNRESOLVED_TRANSITIVE_DEPENDENCY),
        (pv.LegacyCapabilityManifest("writer", dynamic_imports_declared=True, unresolved_writers=("x",)), pv.UNMIGRATED_WRITER),
        (pv.LegacyCapabilityManifest("logger", dynamic_imports_declared=True, top_level_logger_side_effect=True), pv.IMPORT_SIDE_EFFECT_UNCERTAIN),
        (pv.LegacyCapabilityManifest("main", dynamic_imports_declared=True, module_main=True), pv.LEGACY_CAPABILITY_DENIED),
        (pv.LegacyCapabilityManifest("process", dynamic_imports_declared=True, subprocess_spawn=True), pv.LEGACY_CAPABILITY_DENIED),
    ]
    with patch.object(importlib, "import_module", side_effect=import_probe), patch.object(subprocess, "Popen", side_effect=popen_probe):
        for manifest, code in manifests:
            with pytest.raises(pv.ProvenanceError) as exc:
                pv.census_legacy_capability(manifest)
            assert exc.value.code == code
        from xiaoshuo.pipeline.pipeline_nodes import BookProcessorNode, RhythmAnalyzerNode
        with pytest.raises(pv.ProvenanceError) as exc:
            BookProcessorNode().run(genre="genre-a")
        assert exc.value.code == pv.MISSING_PROJECT_CONTEXT
        with pytest.raises(pv.ProvenanceError) as exc:
            BookProcessorNode().run(genre="genre-a", context=context)
        assert exc.value.code == pv.LEGACY_CAPABILITY_DENIED
        with pytest.raises(pv.ProvenanceError) as exc:
            RhythmAnalyzerNode().run(genre="genre-a", context=context)
        assert exc.value.code == pv.LEGACY_CAPABILITY_DENIED
    assert probes == []
    assert pv.get_call_counters() == {
        "import": 0,
        "module_main": 0,
        "in_process": 0,
        "process_spawn": 0,
        "logger": 0,
        "checkpoint": 0,
        "cache": 0,
        "writer": 0,
    }
    pv.assert_zero_call_counters()


def test_logging_import_and_context_budget_have_no_top_level_writer():
    pv.reset_call_counters()
    logging_config = importlib.import_module("xiaoshuo.infra.logging_config")
    importlib.import_module("xiaoshuo.pipeline.context_budget")
    logging_config.get_logger("provenance-test")
    assert pv.get_call_counters()["logger"] == 0
    

def test_artifact_lineage_and_d_drive_writer_boundary():
    _, _, _, _, _, context, _ = _fixture()
    content = b"canonical artifact\n"
    ref = pv.make_artifact_ref(
        context,
        "artifacts/output.txt",
        content,
        source_ref="test-source",
        batch_id="batch-1",
        parent_refs=("root-input",),
    )
    pv.validate_artifact_ref(context, ref, content)
    target = pv.safe_write_bytes(
        context,
        ref.relative_path,
        content,
        artifact_ref=ref,
        expected_batch_id="batch-1",
    )
    assert target.drive.upper() == "D:"
    assert target.is_relative_to(pv.execution_root(context))
    assert pv.safe_read_bytes(context, ref.relative_path) == content
    with pytest.raises(pv.ProvenanceError) as exc:
        pv.safe_write_bytes(
            context,
            "..\\outside.txt",
            b"no",
            artifact_ref=ref,
            expected_batch_id="batch-1",
        )
    assert exc.value.code == pv.PATH_ESCAPE


def test_registry_admission_requires_owner_provenance_bytes():
    definition, entry, owner, _, _, _, provenance_bytes = _fixture()
    common = dict(
        owner=owner,
        entries=[entry],
        registry_id="registry-admission",
        snapshot_id="snapshot-admission",
    )
    with pytest.raises(pv.ProvenanceError) as exc:
        pv.inject_project_registry(**common, owner_provenance_bytes={})
    assert exc.value.code == pv.ENTRY_PROVENANCE_MISSING
    with pytest.raises(pv.ProvenanceError) as exc:
        pv.inject_project_registry(
            **common,
            owner_provenance_bytes={entry.entry_provenance_ref: b"wrong-bytes"},
        )
    assert exc.value.code == pv.ENTRY_PROVENANCE_HASH_MISMATCH
    registry = pv.inject_project_registry(
        **common,
        owner_provenance_bytes={entry.entry_provenance_ref: provenance_bytes},
    )
    assert registry.resolve_owner_provenance(entry.entry_provenance_ref) == provenance_bytes
    assert registry.compute_snapshot_hash() == registry.registry_snapshot_hash


def test_runner_legacy_deny_has_no_write_or_call_residue():
    from xiaoshuo.pipeline.base import PipelineRunner
    from xiaoshuo.pipeline.pipeline_nodes import BookProcessorNode

    pv.reset_call_counters()
    context = _fixture()[5]
    root = pv.execution_root(context, create=False)
    assert not root.exists()
    runner = PipelineRunner()
    runner.register(BookProcessorNode())
    with pytest.raises(pv.ProvenanceError) as exc:
        runner.run("genre-a", context=context)
    assert exc.value.code == pv.LEGACY_CAPABILITY_DENIED
    assert not root.exists()
    assert pv.get_call_counters() == {
        "import": 0,
        "module_main": 0,
        "in_process": 0,
        "process_spawn": 0,
        "logger": 0,
        "checkpoint": 0,
        "cache": 0,
        "writer": 0,
    }
    pv.assert_zero_call_counters()


def test_runner_validation_deny_has_no_write_residue():
    from xiaoshuo.pipeline.base import PipelineNode, PipelineRunner

    class InvalidPrerequisiteNode(PipelineNode):
        name = "book_processor"
        stage_info = (1, 1, "invalid prerequisite")

        def check_prerequisites(self, genre: str = "", **kwargs) -> bool:
            return False

        def run(self, genre: str = "", **kwargs) -> bool:
            raise AssertionError("validation deny must happen before node execution")

    pv.reset_call_counters()
    context = _fixture()[5]
    root = pv.execution_root(context, create=False)
    runner = PipelineRunner()
    runner.register(InvalidPrerequisiteNode())
    with pytest.raises(pv.ProvenanceError) as exc:
        runner.run("genre-a", context=context)
    assert exc.value.code == pv.PREREQUISITE_VALIDATION_FAILED
    assert not root.exists()
    pv.assert_zero_call_counters()


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"\xef\xbb\xbfcanonical", pv.BOM_FORBIDDEN),
        (b"canonical\x00value", "INVALID_CANONICAL_VALUE"),
        (b"\xff\xfe", "INVALID_UTF8"),
    ],
)
def test_artifact_content_canonical_validation_happens_before_root_creation(content, code):
    context = _fixture()[5]
    root = pv.execution_root(context, create=False)
    with pytest.raises(pv.ProvenanceError) as exc:
        pv.make_artifact_ref(
            context,
            "artifacts/invalid.txt",
            content,
            source_ref="test-source",
            batch_id="batch-invalid",
            parent_refs=("root-input",),
        )
    assert exc.value.code == code
    assert not root.exists()


def test_artifact_parent_identity_and_batch_validation_fail_closed():
    context = _fixture()[5]
    with pytest.raises(pv.ProvenanceError) as exc:
        pv.make_artifact_ref(
            context,
            "artifacts/no-parent.txt",
            b"content",
            source_ref="test-source",
            batch_id="batch-parent",
        )
    assert exc.value.code == pv.PARENT_MISSING
    content = b"content\n"
    ref = pv.make_artifact_ref(
        context,
        "artifacts/identity.txt",
        content,
        source_ref="test-source",
        batch_id="batch-expected",
        parent_refs=("root-input",),
    )
    with pytest.raises(pv.ProvenanceError) as exc:
        pv.validate_artifact_ref(context, replace(ref, namespace_digest="0" * 64), content)
    assert exc.value.code == pv.OLD_NAMESPACE_ARTIFACT
    with pytest.raises(pv.ProvenanceError) as exc:
        pv.validate_artifact_ref(context, replace(ref, profile_id="old-profile"), content)
    assert exc.value.code == pv.PROFILE_MISMATCH
    with pytest.raises(pv.ProvenanceError) as exc:
        pv.validate_artifact_ref(context, replace(ref, project_revision="old-revision"), content)
    assert exc.value.code == pv.NAMESPACE_DIGEST_MISMATCH
    with pytest.raises(pv.ProvenanceError) as exc:
        pv.validate_artifact_ref(context, ref, content, expected_batch_id="wrong-batch")
    assert exc.value.code == pv.BATCH_DIGEST_MISMATCH


def test_checkpoint_and_state_records_include_complete_lineage_metadata():
    from xiaoshuo.infra import pipeline_state
    from xiaoshuo.pipeline import checkpoint

    context = _fixture()[5]
    content = b"complete lineage\n"
    ref = pv.make_artifact_ref(
        context,
        "artifacts/lineage-record.txt",
        content,
        source_ref="test-source",
        batch_id="batch-lineage",
        parent_refs=("parent-a", "parent-b"),
    )
    checkpoint_path = checkpoint.mark_done(
        "book_processor",
        artifact_ref=ref,
        content=content,
        expected_batch_id="batch-lineage",
        context=context,
    )
    state_path = pipeline_state.write_stage(
        "lineage-stage",
        artifact_ref=ref,
        content=content,
        expected_batch_id="batch-lineage",
        context=context,
    )
    checkpoint_data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    state_data = json.loads(state_path.read_text(encoding="utf-8"))
    for record in (checkpoint_data, state_data):
        assert record["lineage"]["namespace_digest"] == context.namespace_digest
        assert record["lineage"]["profile_definition_hash"] == context.profile.profile_definition_hash
        assert record["lineage"]["project_revision"] == context.namespace.project_revision
        assert record["lineage"]["root_alias"] == context.root_alias
        assert record["lineage"]["batch_id"] == "batch-lineage"
        assert record["lineage"]["parent_refs"] == ["parent-a", "parent-b"]
        assert record["content_length"] == len(content)
        assert record["content_sha256"] == pv.sha256_bytes(content)


def test_root_factory_rejects_nonstandard_escape_and_existing_residue():
    owner = pv.ProjectRegistryOwner("owner", "source")
    with pytest.raises(pv.ProvenanceError) as exc:
        pv.StageRootAlias("outside", "stage", owner.owner_id, Path(r"D:\tmp\not-yeyu-ai-a3"))
    assert exc.value.code == pv.WRITE_BOUNDARY_UNCERTAIN
    with pytest.raises(pv.ProvenanceError) as exc:
        pv.StageRootAlias("c-root", "stage", owner.owner_id, Path(r"C:\tmp\root"))
    assert exc.value.code == pv.WRITE_BOUNDARY_UNCERTAIN
    with pytest.raises(pv.ProvenanceError) as exc:
        pv.StageRootAlias("escaped", "stage", owner.owner_id, EVIDENCE_ROOT / ".." / "escaped")
    assert exc.value.code == pv.PATH_ESCAPE

    context = _fixture()[5]
    root = pv.execution_root(context, create=False)
    root.mkdir(parents=True, exist_ok=False)
    (root / "residue.txt").write_bytes(b"residue")
    with pytest.raises(pv.ProvenanceError) as exc:
        pv.execution_root(context, create=True)
    assert exc.value.code == pv.WRITE_BOUNDARY_UNCERTAIN


def test_root_factory_rejects_symlink_or_reparse_alias():
    owner = pv.ProjectRegistryOwner("owner", "source")
    parent = EVIDENCE_ROOT / "root-boundary" / uuid.uuid4().hex
    parent.mkdir(parents=True, exist_ok=False)
    target = parent / "target"
    target.mkdir()
    link = parent / "link"
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
    except (OSError, NotImplementedError):
        with patch.object(Path, "is_symlink", return_value=True):
            with pytest.raises(pv.ProvenanceError) as error:
                pv.StageRootAlias("synthetic-reparse", "stage", owner.owner_id, parent / "synthetic-link")
    else:
        with pytest.raises(pv.ProvenanceError) as error:
            pv.StageRootAlias("link-root", "stage", owner.owner_id, link)
    assert error.value.code == pv.REPARSE_OR_JUNCTION


def test_final_binding_recomputes_batch_and_envelope_hashes():
    context = _fixture()[5]
    batch, envelope = pv.build_batch_and_envelope(
        context,
        batch_id="batch-forged",
        attempt_id="attempt-forged",
        config_hash="config-forged",
    )
    with pytest.raises(pv.ProvenanceError) as exc:
        pv.verify_batch_envelope_binding(replace(batch, batch_digest="0" * 64), envelope)
    assert exc.value.code == pv.BATCH_DIGEST_MISMATCH
    with pytest.raises(pv.ProvenanceError) as exc:
        pv.verify_batch_envelope_binding(batch, replace(envelope, evidence_envelope_hash="0" * 64))
    assert exc.value.code == pv.HASH_MISMATCH


def test_dataclasses_replace_cannot_forge_complete_artifact_lineage():
    context = _fixture()[5]
    content = b"sealed lineage\n"
    ref = pv.make_artifact_ref(
        context,
        "artifacts/sealed.txt",
        content,
        source_ref="owner-source",
        batch_id="batch-sealed",
        parent_refs=("root-input",),
    )
    mutations = (
        {"source_ref": "forged-source"},
        {"producer_version": "forged-producer"},
        {"batch_id": "forged-batch"},
        {"parent_refs": ("parent-a",)},
        {"relative_path": "artifacts/forged.txt"},
        {"length": ref.length + 1},
        {"sha256": "0" * 64},
    )
    for mutation in mutations:
        forged = replace(ref, **mutation)
        with pytest.raises(pv.ProvenanceError) as exc:
            pv.validate_artifact_ref(context, forged, content)
        assert exc.value.code in {pv.HASH_MISMATCH, pv.BATCH_DIGEST_MISMATCH}


def test_parent_store_missing_and_wrong_parent_fail_before_root_creation():
    from xiaoshuo.infra import pipeline_state
    from xiaoshuo.pipeline import checkpoint

    context = _fixture()[5]
    root = pv.execution_root(context, create=False)
    with pytest.raises(pv.ProvenanceError) as exc:
        pv.make_artifact_ref(
            context,
            "artifacts/missing-parent.txt",
            b"missing parent\n",
            source_ref="owner-source",
            batch_id="batch-parent",
            parent_refs=("not-in-owner-store",),
        )
    assert exc.value.code == pv.PARENT_MISSING
    records = dict(context.parent_store.parent_records)
    records["root-input"] = replace(records["root-input"], root_alias="wrong-root")
    wrong_store = pv.ParentRefStoreV1(
        context.registry.owner_id,
        context.registry.authoritative_source_ref,
        records,
    )
    wrong_context = replace(context, parent_store=wrong_store)
    with pytest.raises(pv.ProvenanceError) as exc:
        pv.make_artifact_ref(
            wrong_context,
            "artifacts/wrong-parent.txt",
            b"wrong parent\n",
            source_ref="owner-source",
            batch_id="batch-parent",
            parent_refs=("root-input",),
        )
    assert exc.value.code == pv.PARENT_MISMATCH
    good_ref = pv.make_artifact_ref(
        context,
        "artifacts/parent-boundary.txt",
        b"parent boundary\n",
        source_ref="owner-source",
        batch_id="batch-parent",
        parent_refs=("root-input",),
    )
    missing_ref = replace(good_ref, parent_refs=("not-in-owner-store",))
    for operation in (
        lambda: checkpoint.mark_done(
            "book_processor",
            artifact_ref=missing_ref,
            content=b"parent boundary\n",
            expected_batch_id="batch-parent",
            context=context,
        ),
        lambda: pipeline_state.write_stage(
            "parent-boundary",
            artifact_ref=missing_ref,
            content=b"parent boundary\n",
            expected_batch_id="batch-parent",
            context=context,
        ),
    ):
        with pytest.raises(pv.ProvenanceError) as exc:
            operation()
        assert exc.value.code == pv.PARENT_MISSING
    assert not root.exists()


def _make_symlink_or_synthetic(target: Path, link: Path, *, directory: bool = False) -> bool:
    try:
        os.symlink(str(target), str(link), target_is_directory=directory)
    except (OSError, NotImplementedError):
        return False
    return True


def _assert_reparse_rejected(callback, link: Path, created: bool) -> None:
    if created:
        with pytest.raises(pv.ProvenanceError) as exc:
            callback()
    else:
        original_assert_no_reparse = pv._assert_no_reparse

        def selective_reparse(candidate: Path) -> None:
            if Path(candidate) == link:
                raise pv.ProvenanceError(pv.REPARSE_OR_JUNCTION, "synthetic final reparse point")
            original_assert_no_reparse(candidate)

        with patch.object(pv, "_assert_no_reparse", side_effect=selective_reparse):
            with pytest.raises(pv.ProvenanceError) as exc:
                callback()
    assert exc.value.code == pv.REPARSE_OR_JUNCTION


def test_checkpoint_final_file_symlink_is_rejected():
    from xiaoshuo.pipeline import checkpoint

    context = _fixture()[5]
    root = pv.execution_root(context, create=True)
    checkpoint_dir = root / "checkpoints"
    checkpoint_dir.mkdir()
    target = checkpoint_dir / "target.json"
    target.write_text("{}", encoding="utf-8")
    link = checkpoint_dir / "book_processor.json"
    created = _make_symlink_or_synthetic(target, link)
    _assert_reparse_rejected(lambda: checkpoint.is_done("book_processor", context=context), link, created)


def test_logging_final_directory_and_file_symlinks_are_rejected():
    from xiaoshuo.infra import logging_config

    directory_context = _fixture()[5]
    directory_root = pv.execution_root(directory_context, create=True)
    directory_target = directory_root / "logs-target"
    directory_target.mkdir()
    directory_link = directory_root / "logs"
    directory_created = _make_symlink_or_synthetic(directory_target, directory_link, directory=True)
    _assert_reparse_rejected(
        lambda: logging_config.configure_logging(directory_context),
        directory_link,
        directory_created,
    )

    file_context = _fixture()[5]
    file_root = pv.execution_root(file_context, create=True)
    log_dir = file_root / "logs"
    log_dir.mkdir()
    file_target = log_dir / "target.log"
    file_target.write_text("", encoding="utf-8")
    today = __import__("datetime").datetime.now().strftime("%Y%m%d")
    file_link = log_dir / f"xiaoshuo_{today}.log"
    file_created = _make_symlink_or_synthetic(file_target, file_link)
    _assert_reparse_rejected(
        lambda: logging_config.configure_logging(file_context),
        file_link,
        file_created,
    )
    logging_config.close_logging()


def test_successful_node_without_lineage_does_not_auto_complete():
    from xiaoshuo.pipeline.base import PipelineNode, PipelineRunner

    class SuccessfulNode(PipelineNode):
        name = "book_processor"
        stage_info = (1, 1, "successful node")

        def run(self, genre: str = "", **kwargs) -> bool:
            return True

    pv.reset_call_counters()
    context = _fixture()[5]
    root = pv.execution_root(context, create=False)
    runner = PipelineRunner()
    runner.register(SuccessfulNode())
    assert runner.run("genre-a", context=context) == {"book_processor": True}
    assert not root.exists()
    pv.assert_zero_call_counters()


def test_error_lineage_without_real_batch_fails_closed_without_write():
    from xiaoshuo.pipeline.base import PipelineNode, PipelineRunner

    class ErrorNode(PipelineNode):
        name = "book_processor"
        stage_info = (1, 1, "error node")

        def run(self, genre: str = "", **kwargs) -> bool:
            raise RuntimeError("expected test failure")

    pv.reset_call_counters()
    context = _fixture()[5]
    root = pv.execution_root(context, create=False)
    runner = PipelineRunner()
    runner.register(ErrorNode())
    with pytest.raises(pv.ProvenanceError) as exc:
        runner.run("genre-a", context=context)
    assert exc.value.code == pv.BATCH_DIGEST_MISMATCH
    assert not root.exists()
    pv.assert_zero_call_counters()


def test_directly_constructed_forged_execution_context_fails_closed():
    context = _fixture()[5]
    forged_namespace = replace(context.namespace, namespace_digest="0" * 64)
    with pytest.raises(pv.ProvenanceError) as exc:
        pv.ExecutionContext(
            registry=context.registry,
            project=context.project,
            profile=context.profile,
            namespace=forged_namespace,
            genre_identity=context.genre_identity,
            stage_alias=context.stage_alias,
            root_alias=context.root_alias,
            run_id=context.run_id,
            producer_version=context.producer_version,
            root_spec=context.root_spec,
            parent_store=context.parent_store,
        )
    assert exc.value.code == pv.NAMESPACE_DIGEST_MISMATCH


def test_parallel_group_and_prerequisites_receive_the_same_context():
    from xiaoshuo.pipeline.base import PipelineNode, PipelineRunner

    context = _fixture()[5]
    seen: list[tuple[str, object, object]] = []

    class ContextNode(PipelineNode):
        def __init__(self, name: str):
            self.name = name
            self.stage_info = (1, 1, name)

        def check_prerequisites(self, genre: str = "", *, context=None, **kwargs) -> bool:
            seen.append((self.name, "prerequisite", context))
            return context is not None

        def run(self, genre: str = "", *, context=None, **kwargs) -> bool:
            seen.append((self.name, "run", context))
            return context is not None

    runner = PipelineRunner()
    runner.register(ContextNode("book_processor"), group=1)
    runner.register(ContextNode("rhythm_analyzer"), group=1)
    assert runner.run("genre-a", context=context) == {
        "book_processor": True,
        "rhythm_analyzer": True,
    }
    assert len(seen) == 4
    assert all(item[2] is context for item in seen)


def test_schema_paths_reject_escape_reparse_and_bom():
    from xiaoshuo.pipeline import base as base_module

    context = _fixture()[5]
    root = pv.execution_root(context, create=True)
    schema_dir = root / "schema"
    schema_dir.mkdir()
    valid_file = schema_dir / "valid.csv"
    valid_file.write_text("name\nvalue\n", encoding="utf-8")
    schema = {
        "records": {
            "dir": "schema",
            "pattern": "*.csv",
            "required_columns": ["name"],
            "min_files": 1,
        }
    }
    assert base_module._validate_schema(schema, "genre-a", "input", context=context) == []
    with pytest.raises(pv.ProvenanceError) as exc:
        base_module._validate_schema(
            {"records": {"dir": "schema", "pattern": "../*.csv"}},
            "genre-a",
            "input",
            context=context,
        )
    assert exc.value.code == pv.PATH_ESCAPE

    bom_context = _fixture()[5]
    bom_root = pv.execution_root(bom_context, create=True)
    bom_dir = bom_root / "schema"
    bom_dir.mkdir()
    (bom_dir / "bom.csv").write_bytes(b"\xef\xbb\xbfname\nvalue\n")
    with pytest.raises(pv.ProvenanceError) as exc:
        base_module._validate_schema(schema, "genre-a", "input", context=bom_context)
    assert exc.value.code == pv.BOM_FORBIDDEN

    reparse_context = _fixture()[5]
    reparse_root = pv.execution_root(reparse_context, create=True)
    reparse_dir = reparse_root / "schema"
    reparse_dir.mkdir()
    reparse_link = reparse_root / "schema-link"
    reparse_schema = {"records": {"dir": "schema-link", "pattern": "*.csv"}}
    _assert_reparse_rejected(
        lambda: base_module._validate_schema(
            reparse_schema,
            "genre-a",
            "input",
            context=reparse_context,
        ),
        reparse_link,
        False,
    )

    file_reparse_context = _fixture()[5]
    file_reparse_root = pv.execution_root(file_reparse_context, create=True)
    file_reparse_dir = file_reparse_root / "schema"
    file_reparse_dir.mkdir()
    file_reparse_link = file_reparse_dir / "linked.csv"
    file_reparse_link.write_text("name\nvalue\n", encoding="utf-8")
    file_reparse_schema = {"records": {"dir": "schema", "pattern": "*.csv"}}
    _assert_reparse_rejected(
        lambda: base_module._validate_schema(
            file_reparse_schema,
            "genre-a",
            "input",
            context=file_reparse_context,
        ),
        file_reparse_link,
        False,
    )


def test_safe_write_replay_is_idempotent_and_conflicts_are_preserved():
    context = _fixture()[5]
    content = b"replay content\n"
    ref = pv.make_artifact_ref(
        context,
        "artifacts/replay.txt",
        content,
        source_ref="replay-source",
        batch_id="batch-replay",
        parent_refs=("root-input",),
    )
    pv.reset_call_counters()
    target = pv.safe_write_bytes(
        context,
        ref.relative_path,
        content,
        artifact_ref=ref,
        expected_batch_id="batch-replay",
    )
    first_bytes = target.read_bytes()
    assert pv.get_call_counters()["writer"] == 1
    assert pv.safe_write_bytes(
        context,
        ref.relative_path,
        content,
        artifact_ref=ref,
        expected_batch_id="batch-replay",
    ) == target
    assert pv.get_call_counters()["writer"] == 1
    conflict_content = b"different replay content\n"
    conflict_ref = pv.make_artifact_ref(
        context,
        ref.relative_path,
        conflict_content,
        source_ref="replay-source",
        batch_id="batch-replay",
        parent_refs=("root-input",),
    )
    with pytest.raises(pv.ProvenanceError) as exc:
        pv.safe_write_bytes(
            context,
            ref.relative_path,
            conflict_content,
            artifact_ref=conflict_ref,
            expected_batch_id="batch-replay",
        )
    assert exc.value.code == pv.REPLAY_CONFLICT
    assert target.read_bytes() == first_bytes
    assert pv.get_call_counters()["writer"] == 1


def test_checkpoint_and_state_corruption_or_conflict_preserve_history():
    from xiaoshuo.infra import pipeline_state
    from xiaoshuo.pipeline import checkpoint

    checkpoint_context = _fixture()[5]
    original = b"checkpoint original\n"
    original_ref = pv.make_artifact_ref(
        checkpoint_context,
        "artifacts/checkpoint.txt",
        original,
        source_ref="checkpoint-source",
        batch_id="batch-checkpoint",
        parent_refs=("root-input",),
    )
    checkpoint_path = checkpoint.mark_done(
        "book_processor",
        artifact_ref=original_ref,
        content=original,
        expected_batch_id="batch-checkpoint",
        context=checkpoint_context,
    )
    checkpoint_before = checkpoint_path.read_bytes()
    conflict = b"checkpoint conflict\n"
    conflict_ref = pv.make_artifact_ref(
        checkpoint_context,
        "artifacts/checkpoint.txt",
        conflict,
        source_ref="checkpoint-source",
        batch_id="batch-checkpoint",
        parent_refs=("root-input",),
    )
    with pytest.raises(pv.ProvenanceError) as exc:
        checkpoint.mark_done(
            "book_processor",
            artifact_ref=conflict_ref,
            content=conflict,
            expected_batch_id="batch-checkpoint",
            context=checkpoint_context,
        )
    assert exc.value.code == pv.REPLAY_CONFLICT
    assert checkpoint_path.read_bytes() == checkpoint_before

    corrupt_context = _fixture()[5]
    corrupt_content = b"corrupt checkpoint\n"
    corrupt_ref = pv.make_artifact_ref(
        corrupt_context,
        "artifacts/checkpoint-corrupt.txt",
        corrupt_content,
        source_ref="checkpoint-source",
        batch_id="batch-corrupt",
        parent_refs=("root-input",),
    )
    corrupt_path = checkpoint.mark_done(
        "book_processor",
        artifact_ref=corrupt_ref,
        content=corrupt_content,
        expected_batch_id="batch-corrupt",
        context=corrupt_context,
    )
    corrupt_before = corrupt_path.read_bytes()
    corrupt_path.write_bytes(b"{not-json")
    with pytest.raises(pv.ProvenanceError) as exc:
        checkpoint.is_done("book_processor", context=corrupt_context)
    assert exc.value.code == pv.REPLAY_CONFLICT
    assert corrupt_path.read_bytes() == b"{not-json"

    state_context = _fixture()[5]
    state_content = b"state original\n"
    state_ref = pv.make_artifact_ref(
        state_context,
        "artifacts/state.txt",
        state_content,
        source_ref="state-source",
        batch_id="batch-state-history",
        parent_refs=("root-input",),
    )
    state_path = pipeline_state.write_stage(
        "history-stage",
        artifact_ref=state_ref,
        content=state_content,
        expected_batch_id="batch-state-history",
        context=state_context,
    )
    state_before = state_path.read_bytes()
    state_conflict_content = b"state conflict\n"
    state_conflict_ref = pv.make_artifact_ref(
        state_context,
        "artifacts/state.txt",
        state_conflict_content,
        source_ref="state-source",
        batch_id="batch-state-history",
        parent_refs=("root-input",),
    )
    with pytest.raises(pv.ProvenanceError) as exc:
        pipeline_state.write_stage(
            "history-stage",
            artifact_ref=state_conflict_ref,
            content=state_conflict_content,
            expected_batch_id="batch-state-history",
            context=state_context,
        )
    assert exc.value.code == pv.REPLAY_CONFLICT
    assert state_path.read_bytes() == state_before

    state_path.write_bytes(b"{not-json")
    with pytest.raises(pv.ProvenanceError) as exc:
        pipeline_state.read_stage(context=state_context)
    assert exc.value.code == pv.REPLAY_CONFLICT
    assert state_path.read_bytes() == b"{not-json"


def test_checkpoint_unavailable_fails_closed():
    from xiaoshuo.pipeline import base as base_module
    from xiaoshuo.pipeline.base import PipelineNode

    class CheckpointNode(PipelineNode):
        name = "book_processor"
        stage_info = (1, 1, "checkpoint node")

        def run(self, genre: str = "", **kwargs) -> bool:
            return True

    context = _fixture()[5]
    node = CheckpointNode()
    with patch.object(base_module, "_CHECKPOINT_AVAILABLE", False):
        with pytest.raises(pv.ProvenanceError) as exc:
            node.skip_if_done("genre-a", context=context)
        assert exc.value.code == pv.CHECKPOINT_CAPABILITY_UNAVAILABLE
        with pytest.raises(pv.ProvenanceError) as exc:
            node.mark_completed(context=context)
        assert exc.value.code == pv.CHECKPOINT_CAPABILITY_UNAVAILABLE


def test_checkpoint_helpers_resolve_activated_context_when_omitted():
    from xiaoshuo.pipeline import checkpoint

    context = _fixture()[5]
    content = b"implicit checkpoint\n"
    artifact_ref = pv.make_artifact_ref(
        context,
        "artifacts/implicit-checkpoint.txt",
        content,
        source_ref="implicit-source",
        batch_id="batch-implicit",
        parent_refs=("root-input",),
    )

    with pv.activate_execution_context(context):
        assert checkpoint.is_done("book_processor") is False
        assert checkpoint.get_next_step() == "book_processor"
        initial_status = checkpoint.status()
        assert initial_status["book_processor"] is False

        checkpoint_path = checkpoint.mark_done(
            "book_processor",
            artifact_ref=artifact_ref,
            content=content,
            expected_batch_id="batch-implicit",
            context=context,
        )
        assert checkpoint.is_done("book_processor") is True
        assert checkpoint.get_next_step() == "rhythm_analyzer"
        final_status = checkpoint.status()
        assert final_status["book_processor"] is True

        checkpoint_path.write_bytes(b"{not-json")
        with pytest.raises(pv.ProvenanceError) as exc:
            checkpoint.is_done("book_processor")
        assert exc.value.code == pv.REPLAY_CONFLICT
        assert checkpoint_path.read_bytes() == b"{not-json"
