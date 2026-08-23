from pathlib import Path
import math
import json
from dataclasses import replace

import pytest

from xiaoshuo.pipeline.analysis_scoring_snapshots import (
    SnapshotConflict,
    SnapshotMetadata,
    SnapshotPublishError,
    SnapshotReadContract,
    SnapshotValidationError,
    build_snapshot_metadata,
    canonical_json_bytes,
    compute_content_hash,
    publish_snapshot,
    read_snapshot,
)


STAGE = "mvp-analysis-scoring-foundation-f0-correction-implementation"
RUN_ID = "20260814-000001-000008"
EVIDENCE = Path("D:/tmp/yeyu-ai-a3") / STAGE / RUN_ID


def _metadata(key="snapshot-contract"):
    return build_snapshot_metadata(
        snapshot_type="AnalysisSnapshot", schema_version="f0-v1", stage=STAGE,
        run_id=RUN_ID, attempt_id="attempt-1", idempotency_key=key,
        genre="末世", book_id="book-contract", source_input_hash="source-hash",
        upstream_snapshot_id=None, upstream_snapshot_hash=None,
        config_hash="config", rubric_version="rubric", calibration_version="none",
        weight_version="weight", pool_version="pool", status="COMPLETE",
        created_by="test", created_at="2026-08-14T00:00:00+00:00",
    )


def _contract(metadata):
    return SnapshotReadContract(
        stage=metadata.stage, snapshot_type=metadata.snapshot_type,
        schema_version=metadata.schema_version, run_id=metadata.run_id,
        genre=metadata.genre, book_id=metadata.book_id,
        source_input_hash=metadata.source_input_hash, config_hash=metadata.config_hash,
        rubric_version=metadata.rubric_version,
        calibration_version=metadata.calibration_version,
        weight_version=metadata.weight_version, pool_version=metadata.pool_version,
        upstream_snapshot_id=metadata.upstream_snapshot_id,
        upstream_snapshot_hash=metadata.upstream_snapshot_hash,
    )


def _artifact_paths(ref, metadata):
    target = EVIDENCE / ref.relative_path
    manifest = target.with_suffix(".manifest.json")
    temp = target.parent / f".{metadata.snapshot_id}.{metadata.attempt_id}.tmp"
    manifest_temp = target.parent / f".{metadata.snapshot_id}.{metadata.attempt_id}.manifest.tmp"
    return target, manifest, temp, manifest_temp


def test_canonical_json_and_hash_are_deterministic():
    assert canonical_json_bytes({"b": 2, "a": 1}) == b'{"a":1,"b":2}'
    assert compute_content_hash({"payload": {"x": 1}}) == compute_content_hash({"payload": {"x": 1}})
    with pytest.raises(ValueError):
        canonical_json_bytes({"value": math.nan})


def test_snapshot_identity_projection_excludes_created_at():
    first = _metadata("created-at-projection")
    second = replace(first, created_at="2026-08-15T00:00:00+00:00")
    assert first.snapshot_id == second.snapshot_id


def test_publish_read_and_replay_use_manifest_gate():
    metadata = _metadata("publish-read-replay")
    payload = {"status": "COMPLETE", "rows": [{"ch_num": 1}]}
    first = publish_snapshot(EVIDENCE, metadata, payload)
    replay = publish_snapshot(EVIDENCE, metadata, payload)
    assert first.replayed is False
    assert replay.replayed is True
    document = read_snapshot(EVIDENCE, first, expected=_contract(metadata))
    assert document.payload == payload


def test_public_publish_replay_with_different_created_at():
    first_metadata = _metadata("different-created-at")
    second_metadata = replace(first_metadata, created_at="2026-08-15T00:00:00+00:00")
    first = publish_snapshot(EVIDENCE, first_metadata, {"value": 1})
    second = publish_snapshot(EVIDENCE, second_metadata, {"value": 1})
    assert first.snapshot_id == second.snapshot_id
    assert second.replayed is True


def test_identity_change_creates_new_snapshot_id():
    first = _metadata("identity-source")
    second = build_snapshot_metadata(
        snapshot_type=first.snapshot_type, schema_version=first.schema_version,
        stage=first.stage, run_id=first.run_id, attempt_id=first.attempt_id,
        idempotency_key=first.idempotency_key, genre=first.genre,
        book_id=first.book_id, source_input_hash="different-source",
        upstream_snapshot_id=first.upstream_snapshot_id,
        upstream_snapshot_hash=first.upstream_snapshot_hash,
        config_hash=first.config_hash, rubric_version=first.rubric_version,
        calibration_version=first.calibration_version,
        weight_version=first.weight_version, pool_version=first.pool_version,
        status=first.status, created_by=first.created_by,
        created_at=first.created_at,
    )
    assert first.snapshot_id != second.snapshot_id
    assert publish_snapshot(EVIDENCE, first, {"value": 1}).replayed is False
    assert publish_snapshot(EVIDENCE, second, {"value": 1}).replayed is False
    tampered = replace(second, snapshot_id=first.snapshot_id)
    with pytest.raises(SnapshotValidationError) as exc_info:
        publish_snapshot(EVIDENCE, tampered, {"value": 1})
    assert exc_info.value.code == "SNAPSHOT_ID_MISMATCH"


def test_same_identity_with_new_payload_is_conflict():
    metadata = _metadata("conflict")
    publish_snapshot(EVIDENCE, metadata, {"value": 1})
    with pytest.raises(SnapshotConflict):
        publish_snapshot(EVIDENCE, metadata, {"value": 2})


def test_read_rejects_manifest_missing_or_non_complete():
    metadata = _metadata("manifest-gate")
    ref = publish_snapshot(EVIDENCE, metadata, {"value": 1})
    manifest = EVIDENCE / ref.relative_path.replace(".json", ".manifest.json")
    manifest.unlink()
    with pytest.raises(SnapshotValidationError) as exc_info:
        read_snapshot(EVIDENCE, ref, expected=_contract(metadata))
    assert exc_info.value.code == "MANIFEST_INVALID"


def test_builder_and_reader_reject_unsafe_evidence_contract():
    with pytest.raises(SnapshotValidationError):
        build_snapshot_metadata(
            snapshot_type="AnalysisSnapshot", schema_version="f0-v1", stage="..",
            run_id=RUN_ID, attempt_id="attempt", idempotency_key="unsafe",
            genre="末世", book_id="book", source_input_hash="source",
            upstream_snapshot_id=None, upstream_snapshot_hash=None,
            config_hash="config", rubric_version="rubric", calibration_version="none",
            weight_version="weight", pool_version="pool", status="COMPLETE",
            created_by="test", created_at="2026-08-14T00:00:00+00:00",
        )


def test_status_is_fixed_and_invalid_status_is_rejected():
    metadata = SnapshotMetadata(**{**_metadata("invalid-status").__dict__, "status": "BROKEN"})
    with pytest.raises(SnapshotValidationError) as exc_info:
        publish_snapshot(EVIDENCE, metadata, {"value": 1})
    assert exc_info.value.code == "INVALID_STATUS"


def test_parent_reparse_is_rejected(monkeypatch):
    import xiaoshuo.pipeline.analysis_scoring_snapshots as module
    metadata = _metadata("parent-reparse")
    monkeypatch.setattr(module, "_reparse", lambda path: path.name == "snapshots")
    with pytest.raises(SnapshotValidationError) as exc_info:
        publish_snapshot(EVIDENCE, metadata, {"value": 1})
    assert exc_info.value.code == "EVIDENCE_ROOT_REPARSE_POINT"


def test_document_temp_write_failure_preserves_temp_only(monkeypatch):
    import xiaoshuo.pipeline.analysis_scoring_snapshots as module
    metadata = _metadata("failure-document-write")
    original = module._write_fsync

    def fail(path, data):
        if path.name.endswith(".tmp") and not path.name.endswith("manifest.tmp"):
            raise OSError("document temp")
        return original(path, data)

    monkeypatch.setattr(module, "_write_fsync", fail)
    with pytest.raises(SnapshotPublishError) as exc_info:
        publish_snapshot(EVIDENCE, metadata, {"value": 1})
    assert exc_info.value.code == "DOCUMENT_TEMP_WRITE_FAILED"
    target = EVIDENCE / "snapshots/AnalysisSnapshot" / metadata.run_id / f"{metadata.snapshot_id}.json"
    assert not target.exists()
    assert not target.with_suffix(".manifest.json").exists()


def test_document_temp_hash_failure_preserves_temp_only(monkeypatch):
    import xiaoshuo.pipeline.analysis_scoring_snapshots as module
    metadata = _metadata("failure-document-hash")
    original = module._read_json

    def fail(path, code):
        if path.name.endswith(".tmp") and not path.name.endswith("manifest.tmp"):
            raise ValueError("hash readback")
        return original(path, code)

    monkeypatch.setattr(module, "_read_json", fail)
    with pytest.raises(SnapshotPublishError) as exc_info:
        publish_snapshot(EVIDENCE, metadata, {"value": 1})
    assert exc_info.value.code == "DOCUMENT_TEMP_HASH_MISMATCH"
    target = EVIDENCE / "snapshots/AnalysisSnapshot" / metadata.run_id / f"{metadata.snapshot_id}.json"
    assert not target.exists()
    assert not target.with_suffix(".manifest.json").exists()


def test_directory_fsync_after_target_failure_seals_target_only(monkeypatch):
    import xiaoshuo.pipeline.analysis_scoring_snapshots as module
    metadata = _metadata("failure-target-fsync")
    monkeypatch.setattr(module, "_fsync_directory", lambda path: (_ for _ in ()).throw(OSError("dir")))
    with pytest.raises(SnapshotPublishError) as exc_info:
        publish_snapshot(EVIDENCE, metadata, {"value": 1})
    assert exc_info.value.code == "DIRECTORY_FSYNC_AFTER_TARGET_FAILED"
    target = EVIDENCE / "snapshots/AnalysisSnapshot" / metadata.run_id / f"{metadata.snapshot_id}.json"
    assert target.exists()
    assert not target.with_suffix(".manifest.json").exists()


def test_orphan_manifest_temp_failure_preserves_target_and_temp(monkeypatch):
    import xiaoshuo.pipeline.analysis_scoring_snapshots as module
    metadata = _metadata("failure-orphan-temp")
    original = module._write_fsync
    calls = {"n": 0}

    def fail(path, data):
        calls["n"] += 1
        if calls["n"] == 2:
            path.write_bytes(data)
            raise OSError("orphan temp")
        return original(path, data)

    monkeypatch.setattr(module, "_write_fsync", fail)
    with pytest.raises(SnapshotPublishError) as exc_info:
        publish_snapshot(EVIDENCE, metadata, {"value": 1})
    assert exc_info.value.code == "ORPHAN_MANIFEST_TEMP_FAILED"
    ref_target = EVIDENCE / "snapshots/AnalysisSnapshot" / metadata.run_id / f"{metadata.snapshot_id}.json"
    assert ref_target.exists()
    assert not ref_target.with_suffix(".manifest.json").exists()


def test_orphan_manifest_replace_failure_preserves_target_and_temp(monkeypatch):
    import os
    import xiaoshuo.pipeline.analysis_scoring_snapshots as module
    metadata = _metadata("failure-orphan-replace")
    original = os.replace
    calls = {"n": 0}

    def fail(source, target):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("orphan replace")
        return original(source, target)

    monkeypatch.setattr(module.os, "replace", fail)
    with pytest.raises(SnapshotPublishError) as exc_info:
        publish_snapshot(EVIDENCE, metadata, {"value": 1})
    assert exc_info.value.code == "ORPHAN_MANIFEST_REPLACE_FAILED"
    target = EVIDENCE / "snapshots/AnalysisSnapshot" / metadata.run_id / f"{metadata.snapshot_id}.json"
    assert target.exists()
    assert not target.with_suffix(".manifest.json").exists()
    assert (target.parent / f".{metadata.snapshot_id}.{metadata.attempt_id}.manifest.tmp").exists()


def test_directory_fsync_after_orphan_manifest_failure_seals_orphan(monkeypatch):
    import xiaoshuo.pipeline.analysis_scoring_snapshots as module
    metadata = _metadata("failure-orphan-fsync")
    calls = {"n": 0}

    def fail(path):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("orphan dir")

    monkeypatch.setattr(module, "_fsync_directory", fail)
    with pytest.raises(SnapshotPublishError) as exc_info:
        publish_snapshot(EVIDENCE, metadata, {"value": 1})
    assert exc_info.value.code == "DIRECTORY_FSYNC_AFTER_ORPHAN_MANIFEST_FAILED"
    target = EVIDENCE / "snapshots/AnalysisSnapshot" / metadata.run_id / f"{metadata.snapshot_id}.json"
    manifest = target.with_suffix(".manifest.json")
    assert target.exists() and manifest.exists()
    assert json.loads(manifest.read_text(encoding="utf-8"))["publish_state"] == "ORPHAN"


def test_published_manifest_temp_failure_preserves_orphan_and_temp(monkeypatch):
    import xiaoshuo.pipeline.analysis_scoring_snapshots as module
    metadata = _metadata("failure-published-temp")
    original = module._write_fsync
    calls = {"n": 0}

    def fail(path, data):
        calls["n"] += 1
        if calls["n"] == 3:
            path.write_bytes(data)
            raise OSError("published temp")
        return original(path, data)

    monkeypatch.setattr(module, "_write_fsync", fail)
    with pytest.raises(SnapshotPublishError) as exc_info:
        publish_snapshot(EVIDENCE, metadata, {"value": 1})
    assert exc_info.value.code == "PUBLISHED_MANIFEST_TEMP_FAILED"
    target = EVIDENCE / "snapshots/AnalysisSnapshot" / metadata.run_id / f"{metadata.snapshot_id}.json"
    assert target.exists()
    assert json.loads(target.with_suffix(".manifest.json").read_text(encoding="utf-8"))["publish_state"] == "ORPHAN"
    assert (target.parent / f".{metadata.snapshot_id}.{metadata.attempt_id}.manifest.tmp").exists()


def test_published_manifest_replace_failure_preserves_orphan_and_temp(monkeypatch):
    import os
    import xiaoshuo.pipeline.analysis_scoring_snapshots as module
    metadata = _metadata("failure-published-replace")
    original = os.replace
    calls = {"n": 0}

    def fail(source, target):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError("published replace")
        return original(source, target)

    monkeypatch.setattr(module.os, "replace", fail)
    with pytest.raises(SnapshotPublishError) as exc_info:
        publish_snapshot(EVIDENCE, metadata, {"value": 1})
    assert exc_info.value.code == "PUBLISHED_MANIFEST_REPLACE_FAILED"
    target = EVIDENCE / "snapshots/AnalysisSnapshot" / metadata.run_id / f"{metadata.snapshot_id}.json"
    assert target.exists()
    assert json.loads(target.with_suffix(".manifest.json").read_text(encoding="utf-8"))["publish_state"] == "ORPHAN"
    assert (target.parent / f".{metadata.snapshot_id}.{metadata.attempt_id}.manifest.tmp").exists()


def test_published_pair_readback_failure_rejects_pair(monkeypatch):
    import xiaoshuo.pipeline.analysis_scoring_snapshots as module
    metadata = _metadata("failure-published-readback")
    original = module._verify_pair

    def fail(target, manifest, metadata_value, payload, relative):
        target.write_text("{}", encoding="utf-8")
        raise ValueError("readback")

    monkeypatch.setattr(module, "_verify_pair", fail)
    with pytest.raises(SnapshotPublishError) as exc_info:
        publish_snapshot(EVIDENCE, metadata, {"value": 1})
    assert exc_info.value.code == "PUBLISHED_PAIR_VERIFY_FAILED"
    target = EVIDENCE / "snapshots/AnalysisSnapshot" / metadata.run_id / f"{metadata.snapshot_id}.json"
    manifest = target.with_suffix(".manifest.json")
    assert target.exists() and manifest.exists()
    assert json.loads(manifest.read_text(encoding="utf-8"))["publish_state"] == "PUBLISHED"
    ref = type("Ref", (), {"relative_path": f"snapshots/AnalysisSnapshot/{metadata.run_id}/{metadata.snapshot_id}.json", "snapshot_id": metadata.snapshot_id, "snapshot_type": metadata.snapshot_type, "status": metadata.status, "content_hash": "bad"})()
    with pytest.raises(SnapshotValidationError):
        read_snapshot(EVIDENCE, ref, expected=_contract(metadata))


def test_restart_semantics_accepts_only_complete_surviving_pair():
    metadata = _metadata("restart-complete")
    payload = {"value": 1}
    ref = publish_snapshot(EVIDENCE, metadata, payload)
    assert read_snapshot(EVIDENCE, ref, expected=_contract(metadata)).payload == payload
    orphan = _metadata("restart-orphan")
    orphan_ref = publish_snapshot(EVIDENCE, orphan, payload)
    orphan_manifest = EVIDENCE / orphan_ref.relative_path.replace(".json", ".manifest.json")
    orphan_data = json.loads(orphan_manifest.read_text(encoding="utf-8"))
    orphan_data["publish_state"] = "ORPHAN"
    orphan_manifest.write_text(json.dumps(orphan_data), encoding="utf-8")
    with pytest.raises(SnapshotValidationError) as exc_info:
        read_snapshot(EVIDENCE, orphan_ref, expected=_contract(orphan))
    assert exc_info.value.code == "MANIFEST_INVALID"
