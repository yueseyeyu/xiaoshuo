"""Targeted P1-AE pure quality-evaluation contract tests.

These tests are intentionally added for the authorized implementation batch;
they are not executed in this implementation turn.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from xiaoshuo.pipeline.evaluation_contracts import (
    EvaluationError,
    P1_AE_QUALITY_ADMISSION_FIELDS,
    P1_AE_QUALITY_BUNDLE_FIELDS,
    P1_AE_PURE_LOADER_PLAN_TRANSITION_TUPLE,
    P1_AE_OWNER_ADMISSION_SCHEMA_VERSION,
    canonical_sha256,
    p1ae_transition_registry_hash,
)
from xiaoshuo.pipeline.quality_evaluation import evaluate_quality_bundle


FIXTURE = Path(__file__).parent / "fixtures" / "offline_evaluation" / "quality_evaluation_bundle_v1.json"


def _admission() -> dict[str, object]:
    bundle = json.loads(FIXTURE.read_text(encoding="utf-8"))
    def binding(value: str) -> dict[str, object]:
        record = {"value": value}
        return {"fields": ["value"], "record": record, "hash": canonical_sha256(record, fields=("value",))}

    transaction_record = {
        "cpython_internal_expected_events_hash": "1" * 64,
        "cpython_internal_expected_edges_hash": "2" * 64,
        "cpython_internal_expected_event_count": 0,
        "cpython_internal_expected_edge_count": 0,
        "cpython_internal_observed_events_hash": "3" * 64,
        "cpython_internal_observed_edges_hash": "4" * 64,
        "cpython_internal_observed_event_count": 0,
        "cpython_internal_observed_edge_count": 0,
    }
    transaction_binding = {"fields": list(transaction_record), "record": transaction_record, "hash": canonical_sha256(transaction_record, fields=tuple(transaction_record))}
    record = {
        "admission_schema_version": P1_AE_OWNER_ADMISSION_SCHEMA_VERSION,
        "owner_id": "quality-fixture-owner",
        "authority_ref": "quality-fixture-authority",
        "owner_session_ref": "session-fixture",
        "source_registry_hash": "f" * 64,
        "package_hash": binding("package")["hash"],
        "gate_hash": binding("gate")["hash"],
        "permit_digest": binding("permit")["hash"],
        "loader_plan_hash": "d" * 64,
        "loader_plan_length": 1,
        "transition_registry_hash": p1ae_transition_registry_hash("READY"),
        "transition_fields": list(P1_AE_PURE_LOADER_PLAN_TRANSITION_TUPLE),
        "transaction_hash": transaction_binding["hash"],
        "loaded_module_bindings_hash": "1" * 64,
        "writer_invocation_hash": "2" * 64,
        "post_write_trace_hash": "3" * 64,
        "failure_evidence_hash": "4" * 64,
        "residue_snapshot_hash": "5" * 64,
        "residue_pairing_hash": "6" * 64,
        "semantic_hash": canonical_sha256(bundle, fields=P1_AE_QUALITY_BUNDLE_FIELDS),
        "raw_authority_bytes_hash": "8" * 64,
        "authority_record_hash": "9" * 64,
        "authority_handle_binding_hash": "a" * 64,
        "composite_authority_binding_hash": "b" * 64,
        "status": "ADMITTED",
        "resolution_projection_hash": "c" * 64,
        "authority_binding_hash": "d" * 64,
        "owner_registry_snapshot_hash": "e" * 64,
        "owner_annotation_projection_hash": "f" * 64,
    }
    record.update(transaction_record)
    record["binding_records"] = {
        "package": binding("package"), "gate": binding("gate"), "permit": binding("permit"),
        "transaction": transaction_binding, "authority": binding("authority"),
        "writer": binding("writer"), "residue": binding("residue"), "pairing": binding("pairing"),
    }
    return {field: record[field] for field in P1_AE_QUALITY_ADMISSION_FIELDS}


def test_quality_bundle_returns_separate_semantic_and_frozen_bytes() -> None:
    bundle = json.loads(FIXTURE.read_text(encoding="utf-8"))
    result = evaluate_quality_bundle(_admission(), bundle)
    assert result.semantic_result["status"] == "MEASUREMENT_UNPROVEN"
    assert result.semantic_bytes != result.frozen_evidence_bytes
    assert "writer" not in result.frozen_evidence
    assert "residue" not in result.frozen_evidence


def test_transition_tuple_is_fixed_and_replay_or_status_drift_denies() -> None:
    admission = _admission()
    admission["transition_fields"] = ["CAS_CONSUMED"]
    bundle = json.loads(FIXTURE.read_text(encoding="utf-8"))
    with pytest.raises(EvaluationError):
        evaluate_quality_bundle(admission, bundle)


def test_fixture_has_owner_bound_blind_primary_pair() -> None:
    bundle = json.loads(FIXTURE.read_text(encoding="utf-8"))
    annotations = bundle["cases"][0]["annotations"]
    assert len([item for item in annotations if item["pass_kind"] == "PRIMARY"]) == 2
    assert all(item["blindness_status"] == "BLIND" for item in annotations)
