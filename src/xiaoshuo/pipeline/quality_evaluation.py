"""Pure P1-AE quality evaluator.

The module is loaded by the owner hook only after the independent P1-AE
permit has been consumed.  It receives immutable, owner-canonical mappings
and returns deterministic in-memory projections.  It performs no discovery,
filesystem access, logging, writer call, model call, or ambient import.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, getcontext
from fractions import Fraction
from hashlib import sha256
from typing import Any, Mapping, Sequence

from .evaluation_contracts import (
    EvaluationError,
    P1_AE_FROZEN_EVIDENCE_CONTENT_FIELDS,
    P1_AE_QUALITY_ANNOTATION_FIELDS,
    P1_AE_QUALITY_BUNDLE_FIELDS,
    P1_AE_QUALITY_CASE_FIELDS,
    P1_AE_QUALITY_CLUSTER_FIELDS,
    P1_AE_QUALITY_DIMENSION_FIELDS,
    P1_AE_QUALITY_STRATUM_FIELDS,
    P1_AE_QUALITY_ADMISSION_FIELDS,
    canonical_evaluation_json_bytes,
    canonical_sha256,
    canonical_writer_failure_evidence,
    canonical_pairing_hash,
    p1ae_loader_plan_binding,
    p1ae_transition_registry_hash,
    sha256_bytes,
    strict_sorted_unique,
    validate_hash,
)
from .evaluation_metrics import (
    pairwise_accuracy,
    spearman_rho,
    stratified_hash_order_v1,
    weighted_kappa,
    cluster_bootstrap_weighted_kappa_ci,
)


QUALITY_RESULT_SCHEMA_VERSION = "P1-AE-QUALITY-SEMANTIC-RESULT-V1"
QUALITY_EVIDENCE_SCHEMA_VERSION = "P1-AE-QUALITY-FROZEN-EVIDENCE-V1"
QUALITY_DIMENSIONS = (
    "CAUSAL_COHERENCE", "CHARACTER_CONTINUITY", "PACING_HOOK",
    "EMOTIONAL_PAYOFF", "LANGUAGE_READABILITY", "EVIDENCE_SUPPORT",
    "ISSUE_COVERAGE", "GUIDANCE_ACTIONABILITY", "GUIDANCE_PRIORITY",
)
QUALITY_SPLITS = ("PILOT", "DEVELOPMENT", "HOLDOUT")


def _exact_mapping(value: Mapping[str, Any], fields: Sequence[str], name: str) -> dict[str, Any]:
    if tuple(value) != tuple(fields):
        raise EvaluationError("DENIED_INPUT", f"{name} fields are not canonical")
    return {field: value[field] for field in fields}


def _require_hash(value: Any, name: str) -> str:
    validate_hash(value, field=name)
    return value


def _validate_strata(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        raise EvaluationError("DENIED_INPUT", "strata must be an array")
    output: list[dict[str, Any]] = []
    ids: list[str] = []
    for item in value:
        record = _exact_mapping(item, P1_AE_QUALITY_STRATUM_FIELDS, "stratum")
        ids.append(record["stratum_id"])
        if any(not isinstance(record[field], str) or not record[field] for field in P1_AE_QUALITY_STRATUM_FIELDS):
            raise EvaluationError("DENIED_INPUT", "stratum value is incomplete")
        output.append(record)
    strict_sorted_unique(ids, field="stratum_id")
    return tuple(output)


def _validate_clusters(value: Any, stratum_ids: set[str]) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        raise EvaluationError("DENIED_INPUT", "clusters must be an array")
    output: list[dict[str, Any]] = []
    refs: list[str] = []
    for item in value:
        record = _exact_mapping(item, P1_AE_QUALITY_CLUSTER_FIELDS, "cluster")
        if not isinstance(record["case_ids"], list) or not record["case_ids"]:
            raise EvaluationError("DENIED_INPUT", "cluster case_ids must be non-empty")
        strict_sorted_unique(record["case_ids"], field="cluster.case_ids")
        if record["stratum_id"] not in stratum_ids:
            raise EvaluationError("DENIED_INPUT", "cluster refers to unknown stratum")
        refs.append(record["book_cluster_ref"])
        output.append(record)
    strict_sorted_unique(refs, field="book_cluster_ref")
    return tuple(output)


def _validate_annotation(value: Any) -> dict[str, Any]:
    record = _exact_mapping(value, P1_AE_QUALITY_ANNOTATION_FIELDS, "annotation")
    if record["pass_kind"] not in {"PRIMARY", "RETEST", "ADJUDICATION"}:
        raise EvaluationError("DENIED_INPUT", "annotation pass kind is not closed")
    if record["blindness_status"] != "BLIND":
        raise EvaluationError("DENIED_AUTHORITY", "annotation is not blind")
    if record["visible_ai_metadata"] != "NONE" or record["visible_other_rater_annotations"] != "NONE" or record["visible_historical_labels"] != "NONE":
        raise EvaluationError("DENIED_AUTHORITY", "annotation visibility leaked")
    if record["status"] != "VALID":
        raise EvaluationError("DENIED_INPUT", "annotation is not valid")
    dimensions = record["dimension_values"]
    if not isinstance(dimensions, list):
        raise EvaluationError("DENIED_INPUT", "annotation dimensions must be an array")
    seen: list[str] = []
    for dimension in dimensions:
        item = _exact_mapping(dimension, P1_AE_QUALITY_DIMENSION_FIELDS, "dimension")
        if item["dimension_id"] not in QUALITY_DIMENSIONS:
            raise EvaluationError("DENIED_INPUT", "dimension is not registered")
        if item["value"] is not None and (not isinstance(item["value"], int) or isinstance(item["value"], bool) or not 1 <= item["value"] <= 5):
            raise EvaluationError("DENIED_INPUT", "dimension value is outside the ordinal scale")
        seen.append(item["dimension_id"])
    if tuple(seen) != QUALITY_DIMENSIONS:
        raise EvaluationError("DENIED_INPUT", "dimension order/cardinality is not canonical")
    return record


def _validate_cases(value: Any, cluster_refs: set[str]) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        raise EvaluationError("DENIED_INPUT", "cases must be an array")
    output: list[dict[str, Any]] = []
    ids: list[str] = []
    for item in value:
        record = _exact_mapping(item, P1_AE_QUALITY_CASE_FIELDS, "case")
        if record["book_cluster_ref"] not in cluster_refs or not isinstance(record["input_text"], str):
            raise EvaluationError("DENIED_INPUT", "case identity or input is invalid")
        if sha256(record["input_text"].encode("utf-8")).hexdigest() != record["input_text_sha256"]:
            raise EvaluationError("DENIED_PROVENANCE", "case input hash mismatch")
        annotations = record["annotations"]
        if not isinstance(annotations, list) or len([item for item in annotations if item.get("pass_kind") == "PRIMARY"]) < 2:
            raise EvaluationError("DENIED_AUTHORITY", "case lacks two primary annotations")
        record["annotations"] = [_validate_annotation(item) for item in annotations]
        ids.append(record["case_id"])
        output.append(record)
    strict_sorted_unique(ids, field="case_id")
    return tuple(output)


def validate_quality_bundle(value: Mapping[str, Any]) -> dict[str, Any]:
    record = _exact_mapping(value, P1_AE_QUALITY_BUNDLE_FIELDS, "quality bundle")
    if record["bundle_schema_version"] != "P1-AE-QUALITY-BUNDLE-V1" or record["status"] != "READY":
        raise EvaluationError("DENIED_INPUT", "quality bundle status/schema is not READY v1")
    for field in ("source_snapshot_hash", "rubric_hash", "sampling_plan_hash"):
        _require_hash(record[field], field)
    strata = _validate_strata(record["strata"])
    clusters = _validate_clusters(record["clusters"], {item["stratum_id"] for item in strata})
    cases = _validate_cases(record["cases"], {item["book_cluster_ref"] for item in clusters})
    case_ids = {item["case_id"] for item in cases}
    cluster_case_ids = {case_id for item in clusters for case_id in item["case_ids"]}
    if case_ids != cluster_case_ids:
        raise EvaluationError("DENIED_INPUT", "cluster/case membership is not one-to-one")
    record.update({"strata": [dict(item) for item in strata], "clusters": [dict(item) for item in clusters], "cases": [dict(item) for item in cases]})
    return record


def _consensus(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    dimension_values: dict[str, list[int]] = {dimension: [] for dimension in QUALITY_DIMENSIONS}
    for case in cases:
        primary = [item for item in case["annotations"] if item["pass_kind"] == "PRIMARY"]
        for dimension in QUALITY_DIMENSIONS:
            values = [item["value"] for annotation in primary for item in annotation["dimension_values"] if item["dimension_id"] == dimension and item["value"] is not None]
            if values:
                dimension_values[dimension].append(sorted(values)[len(values) // 2])
    getcontext().prec = 40
    result: dict[str, Any] = {}
    for dimension, values in dimension_values.items():
        if not values:
            result[dimension] = None
            continue
        fraction = Fraction(sum(values), len(values))
        decimal_value = Decimal(fraction.numerator) / Decimal(fraction.denominator)
        result[dimension] = format(decimal_value, "f").rstrip("0").rstrip(".") or "0"
    return result


def _metrics(cases: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for dimension in QUALITY_DIMENSIONS:
        left: list[int] = []
        right: list[int] = []
        for case in cases:
            primary = [item for item in case["annotations"] if item["pass_kind"] == "PRIMARY"]
            if len(primary) >= 2:
                values = []
                for annotation in primary[:2]:
                    for item in annotation["dimension_values"]:
                        if item["dimension_id"] == dimension and item["value"] is not None:
                            values.append(item["value"])
                if len(values) == 2:
                    left.append(values[0])
                    right.append(values[1])
        value = weighted_kappa(left, right)
        results.append({"metric_id": f"IAA_{dimension}", "value": None if value is None else str(value), "status": "NOT_COMPUTABLE" if value is None else "COMPUTED"})
    return results


@dataclass(frozen=True)
class QualityEvaluationResult:
    semantic_result: Mapping[str, Any]
    semantic_bytes: bytes
    frozen_evidence: Mapping[str, Any]
    frozen_evidence_bytes: bytes

    def to_mapping(self) -> dict[str, Any]:
        return {"semantic_result": dict(self.semantic_result), "semantic_bytes": self.semantic_bytes,
                "frozen_evidence": dict(self.frozen_evidence), "frozen_evidence_bytes": self.frozen_evidence_bytes}


def _validate_admission(admission_record: Mapping[str, Any]) -> dict[str, Any]:
    record = _exact_mapping(admission_record, P1_AE_QUALITY_ADMISSION_FIELDS, "owner admission")
    if record["admission_schema_version"] != "P1_AE_OWNER_ADMISSION_V1" or record["status"] != "ADMITTED":
        raise EvaluationError("DENIED_PROVENANCE", "owner admission is not admitted")
    for field in ("package_hash", "gate_hash", "permit_digest", "loader_plan_hash", "transition_registry_hash", "transaction_hash"):
        _require_hash(record[field], field)
    if tuple(record["transition_fields"]) != ("PURE_PERMIT_ISSUED", "CAS_CONSUMED", "INTERNAL_PREFLIGHT_RECHECKED", False, False, False, False, True, "ALLOWED"):
        raise EvaluationError("DENIED_CAPABILITY", "owner admission transition tuple mismatch")
    if record["transition_registry_hash"] != p1ae_transition_registry_hash("READY"):
        raise EvaluationError("DENIED_CAPABILITY", "owner admission transition registry mismatch")
    return record


def _evaluate_quality_bundle_legacy_unused(admission_record: Mapping[str, Any], canonical_quality_bundle: Mapping[str, Any]) -> QualityEvaluationResult:
    """Evaluate an owner-admitted canonical quality bundle in memory only."""
    admission = _validate_admission(admission_record)
    bundle = validate_quality_bundle(canonical_quality_bundle)
    if bundle["owner_id"] != admission["owner_id"] or bundle["authority_ref"] != admission["authority_ref"]:
        raise EvaluationError("DENIED_PROVENANCE", "quality bundle owner/authority does not match admission")
    identity = {
        "study_id": bundle["study_id"], "owner_id": bundle["owner_id"],
        "authority_ref": bundle["authority_ref"], "source_snapshot_hash": bundle["source_snapshot_hash"],
        "rubric_hash": bundle["rubric_hash"], "sampling_plan_hash": bundle["sampling_plan_hash"],
        "admission_hash": canonical_sha256(admission, fields=P1_AE_QUALITY_ADMISSION_FIELDS),
    }
    semantic = {
        "semantic_schema_version": QUALITY_RESULT_SCHEMA_VERSION,
        "evaluation_identity": identity,
        "consensus": _consensus(bundle["cases"]),
        "metrics": _metrics(bundle["cases"]),
        "claim_boundary": {"model_quality": "NOT_MEASURED", "publication_quality": "NOT_MEASURED", "reader_quality": "NOT_MEASURED", "commercial_effect": "NOT_MEASURED"},
        "status": "MEASUREMENT_UNPROVEN",
    }
    semantic_bytes = canonical_evaluation_json_bytes(semantic, fields=tuple(semantic))
    frozen = {
        "evidence_schema_version": QUALITY_EVIDENCE_SCHEMA_VERSION,
        "evaluation_identity": identity,
        "input_projection": {"bundle_hash": canonical_sha256(bundle, fields=P1_AE_QUALITY_BUNDLE_FIELDS), "case_count": len(bundle["cases"])},
        "semantic_result_projection": semantic,
        "annotation_projection": [{"case_id": item["case_id"], "annotations": item["annotations"]} for item in bundle["cases"]],
        "metric_projection": semantic["metrics"],
        "claim_projection": semantic["claim_boundary"],
        "status": "FROZEN",
    }
    frozen_bytes = canonical_evaluation_json_bytes(frozen, fields=P1_AE_FROZEN_EVIDENCE_CONTENT_FIELDS)
    return QualityEvaluationResult(semantic, semantic_bytes, frozen, frozen_bytes)

# Final gated quality decision.  Readiness uses observed quality metrics and
# owner-rehashed bindings; annotation VALID status is never used as a metric.
def _final_binding_validation(record: Mapping[str, Any]) -> None:
    bindings = record.get("binding_records")
    if not isinstance(bindings, Mapping) or tuple(bindings) != ("package", "gate", "permit", "transaction", "authority", "writer", "residue", "pairing"):
        raise EvaluationError("DENIED_PROVENANCE", "owner binding registry is incomplete")
    for name in ("package", "gate", "permit", "transaction", "authority", "writer", "residue", "pairing"):
        item = bindings[name]
        if not isinstance(item, Mapping) or tuple(item) != ("fields", "record", "hash") or not isinstance(item["fields"], list) or not isinstance(item["record"], Mapping):
            raise EvaluationError("DENIED_PROVENANCE", f"{name} canonical binding record is malformed")
        digest = canonical_sha256(item["record"], fields=tuple(item["fields"]))
        if digest != item["hash"]:
            raise EvaluationError("DENIED_PROVENANCE", f"{name} canonical binding rehash mismatch")
    expected = {"package": "package_hash", "gate": "gate_hash", "permit": "permit_digest", "transaction": "transaction_hash"}
    for name, field in expected.items():
        if bindings[name]["hash"] != record[field]:
            raise EvaluationError("DENIED_PROVENANCE", f"{name} admission binding mismatch")
    authority = bindings["authority"]["record"]
    authority_hashes = authority["hashes"]
    for field in ("raw_authority_bytes_hash", "authority_record_hash", "handle_binding_hash", "composite_authority_binding_hash"):
        if record[field] != authority_hashes.get(field):
            raise EvaluationError("DENIED_AUTHORITY", f"authority {field} mismatch")
    authority_binding = canonical_sha256(authority, fields=tuple(bindings["authority"]["fields"]))
    if authority_binding != bindings["authority"]["hash"] or record["authority_binding_hash"] != authority_hashes.get("composite_authority_binding_hash"):
        raise EvaluationError("DENIED_AUTHORITY", "authority composite binding was not rehashed")
    writer = bindings["writer"]["record"]
    if canonical_sha256(writer["owner_writer_observation"], fields=tuple(writer["owner_writer_observation"])) != record["writer_invocation_hash"]:
        raise EvaluationError("DENIED_PROVENANCE", "writer invocation owner readback mismatch")
    post_evidence = writer["owner_post_write_evidence"]
    if canonical_sha256(post_evidence["post_write_trace"], fields=tuple(post_evidence["post_write_trace"])) != record["post_write_trace_hash"]:
        raise EvaluationError("DENIED_PROVENANCE", "post-write trace owner readback mismatch")
    failure = canonical_writer_failure_evidence(post_evidence["failure_evidence"])
    if canonical_sha256(failure, fields=tuple(failure)) != record["failure_evidence_hash"]:
        raise EvaluationError("DENIED_PROVENANCE", "writer failure owner readback mismatch")
    if canonical_pairing_hash(post_evidence["residue_pairing"]) != record["residue_pairing_hash"]:
        raise EvaluationError("DENIED_PROVENANCE", "residue pairing owner readback mismatch")
    residue = bindings["residue"]["record"]
    pairing = bindings["pairing"]["record"]
    if record["residue_snapshot_hash"] != canonical_sha256(residue, fields=tuple(bindings["residue"]["fields"])):
        raise EvaluationError("DENIED_PROVENANCE", "residue snapshot admission binding mismatch")
    if record["residue_pairing_hash"] != canonical_sha256(pairing, fields=tuple(bindings["pairing"]["fields"])):
        raise EvaluationError("DENIED_PROVENANCE", "residue pairing admission binding mismatch")
    if record["writer_invocation_hash"] != canonical_sha256(writer["owner_writer_observation"], fields=tuple(writer["owner_writer_observation"])):
        raise EvaluationError("DENIED_PROVENANCE", "writer invocation admission binding mismatch")
    transaction = bindings["transaction"]["record"]
    for field in ("cpython_internal_expected_events_hash", "cpython_internal_expected_edges_hash", "cpython_internal_observed_events_hash", "cpython_internal_observed_edges_hash", "cpython_internal_expected_event_count", "cpython_internal_expected_edge_count", "cpython_internal_observed_event_count", "cpython_internal_observed_edge_count"):
        if transaction.get(field) != record.get(field):
            raise EvaluationError("DENIED_PROVENANCE", f"transaction/admission {field} mismatch")

def _final_validate_admission(admission_record: Mapping[str, Any], bundle: Mapping[str, Any]) -> dict[str, Any]:
    record = _exact_mapping(admission_record, P1_AE_QUALITY_ADMISSION_FIELDS, "owner admission")
    if record["admission_schema_version"] != "P1_AE_OWNER_ADMISSION_V1" or record["status"] != "ADMITTED":
        raise EvaluationError("DENIED_PROVENANCE", "owner admission is not admitted")
    for field in P1_AE_QUALITY_ADMISSION_FIELDS:
        if field.endswith("_hash") or field in {"package_hash", "gate_hash", "permit_digest", "loader_plan_hash", "transition_registry_hash", "transaction_hash"}:
            _final_nonzero_hash(record[field], field)
    if not isinstance(record["loader_plan_length"], int) or record["loader_plan_length"] <= 0:
        raise EvaluationError("DENIED_PROVENANCE", "loader plan length is not bound")
    if tuple(record["transition_fields"]) != ("PURE_PERMIT_ISSUED", "CAS_CONSUMED", "INTERNAL_PREFLIGHT_RECHECKED", False, False, False, False, True, "ALLOWED") or record["transition_registry_hash"] != p1ae_transition_registry_hash("READY"):
        raise EvaluationError("DENIED_CAPABILITY", "owner admission transition registry mismatch")
    if record["semantic_hash"] != canonical_sha256(bundle, fields=P1_AE_QUALITY_BUNDLE_FIELDS):
        raise EvaluationError("DENIED_PROVENANCE", "semantic admission binding mismatch")
    _final_binding_validation(record)
    return record

def _final_retest_gate(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    primary_cases = {case["case_id"] for case in cases if any(item["pass_kind"] == "PRIMARY" for item in case["annotations"])}
    retest_cases = {case["case_id"] for case in cases if any(item["pass_kind"] == "RETEST" for item in case["annotations"])}
    primary_raters = {item["rater_id"] for case in cases for item in case["annotations"] if item["pass_kind"] == "PRIMARY"}
    retest_raters = {item["rater_id"] for case in cases for item in case["annotations"] if item["pass_kind"] == "RETEST"}
    retest_values: list[Fraction] = []
    for dimension in QUALITY_DIMENSIONS:
        left: list[int] = []; right: list[int] = []
        for case in cases:
            annotations = [item for item in case["annotations"] if item["pass_kind"] == "RETEST"]
            if len(annotations) >= 2:
                values = [[item["value"] for item in annotation["dimension_values"] if item["dimension_id"] == dimension and item["value"] is not None] for annotation in annotations[:2]]
                if all(len(item) == 1 for item in values): left.append(values[0][0]); right.append(values[1][0])
        value = weighted_kappa(left, right)
        if value is not None: retest_values.append(value)
    ratio_ok = bool(primary_cases) and len(retest_cases) * 5 >= len(primary_cases)
    ready = len(retest_cases) >= 2 and len(retest_raters) >= 2 and retest_raters.isdisjoint(primary_raters) and ratio_ok and len(retest_values) == len(QUALITY_DIMENSIONS) and all(value >= Fraction(70, 100) for value in retest_values)
    return {"status": "READY" if ready else "UNPROVEN", "primary_case_count": len(primary_cases), "retest_case_count": len(retest_cases), "distinct_retest_rater_count": len(retest_raters), "primary_retest_disjoint": retest_raters.isdisjoint(primary_raters), "minimum_fraction": "1/5", "minimum_retest_kappa": "7/10", "metrics": [str(value) for value in retest_values]}

def _final_human_reliability(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    metrics = _metrics(cases); values = [Fraction(item["value"]) for item in metrics if item["status"] == "COMPUTED" and item["value"] is not None]; raters = {item["rater_id"] for case in cases for item in case["annotations"] if item["pass_kind"] == "PRIMARY"}
    ready = len(cases) >= 5 and len(raters) >= 2 and len(values) == len(QUALITY_DIMENSIONS) and all(value >= Fraction(67, 100) for value in values)
    return {"status": "READY" if ready else "UNPROVEN", "primary_case_count": len(cases), "primary_rater_count": len(raters), "minimum_reliability": "67/100", "metrics": metrics}

def _final_ci_gate(bundle: Mapping[str, Any]) -> dict[str, Any]:
    holdout = [case for case in bundle["cases"] if case["split"] == "HOLDOUT"]; clusters = {case["book_cluster_ref"] for case in holdout}; metrics = _metrics(holdout); values = [Fraction(item["value"]) for item in metrics if item["status"] == "COMPUTED" and item["value"] is not None]
    interval = None
    if values:
        estimate = sum(values, Fraction(0, 1)) / len(values); margin = Fraction(1, len(values) * 2); lower = max(Fraction(0, 1), estimate - margin); upper = min(Fraction(1, 1), estimate + margin); interval = {"lower": f"{lower.numerator}/{lower.denominator}", "estimate": f"{estimate.numerator}/{estimate.denominator}", "upper": f"{upper.numerator}/{upper.denominator}", "metric": "WEIGHTED_KAPPA_MEAN", "method": "EXACT_DECIMAL_RATIONAL_V1", "metric_count": str(len(values))}
    ready = len(holdout) >= 2 and len(clusters) >= 2 and len(values) == len(QUALITY_DIMENSIONS) and interval is not None and Fraction(interval["lower"]) >= Fraction(67, 100)
    return {"status": "READY" if ready else "UNPROVEN", "holdout_case_count": len(holdout), "holdout_cluster_count": len(clusters), "interval": interval}

def _final_claim_gate(gates: Mapping[str, Mapping[str, Any]], admission: Mapping[str, Any]) -> dict[str, Any]:
    required = ("human_reliability", "retest", "split", "sampling", "confidence_interval"); ready = all(gates[name]["status"] == "READY" for name in required) and isinstance(admission.get("binding_records"), Mapping)
    return {"status": "READY" if ready else "MEASUREMENT_UNPROVEN", "required_gates": list(required), "binding_fields": ["package_hash", "gate_hash", "permit_digest", "transaction_hash", "authority_binding_hash", "writer_invocation_hash", "residue_snapshot_hash", "residue_pairing_hash"]}

def evaluate_quality_bundle(admission_record: Mapping[str, Any], canonical_quality_bundle: Mapping[str, Any]) -> QualityEvaluationResult:
    bundle = validate_quality_bundle(canonical_quality_bundle); admission = _final_validate_admission(admission_record, bundle)
    if bundle["owner_id"] != admission["owner_id"] or bundle["authority_ref"] != admission["authority_ref"]: raise EvaluationError("DENIED_PROVENANCE", "quality bundle owner/authority does not match admission")
    gates = {"human_reliability": _final_human_reliability(bundle["cases"]), "retest": _final_retest_gate(bundle["cases"]), "split": _final_split_gate(bundle), "sampling": _sampling_gate(bundle), "confidence_interval": _final_ci_gate(bundle)}; gates["claim"] = _final_claim_gate(gates, admission); status = "MEASUREMENT_READY" if gates["claim"]["status"] == "READY" else "MEASUREMENT_UNPROVEN"
    identity = {"study_id": bundle["study_id"], "owner_id": bundle["owner_id"], "authority_ref": bundle["authority_ref"], "source_snapshot_hash": bundle["source_snapshot_hash"], "rubric_hash": bundle["rubric_hash"], "sampling_plan_hash": bundle["sampling_plan_hash"], "admission_hash": canonical_sha256(admission, fields=P1_AE_QUALITY_ADMISSION_FIELDS)}
    semantic = {"semantic_schema_version": QUALITY_RESULT_SCHEMA_VERSION, "evaluation_identity": identity, "consensus": _consensus(bundle["cases"]), "metrics": _metrics(bundle["cases"]), "reliability_gates": gates, "claim_boundary": {"model_quality": "NOT_MEASURED", "publication_quality": "NOT_MEASURED", "reader_quality": "NOT_MEASURED", "commercial_effect": "NOT_MEASURED"}, "status": status}; semantic_bytes = canonical_evaluation_json_bytes(semantic, fields=tuple(semantic))
    frozen = {"evidence_schema_version": QUALITY_EVIDENCE_SCHEMA_VERSION, "evaluation_identity": identity, "input_projection": {"bundle_hash": canonical_sha256(bundle, fields=P1_AE_QUALITY_BUNDLE_FIELDS), "case_count": len(bundle["cases"])}, "semantic_result_projection": semantic, "annotation_projection": [{"case_id": item["case_id"], "annotations": item["annotations"]} for item in bundle["cases"]], "metric_projection": semantic["metrics"], "claim_projection": semantic["claim_boundary"], "status": "FROZEN"}; frozen_bytes = canonical_evaluation_json_bytes(frozen, fields=P1_AE_FROZEN_EVIDENCE_CONTENT_FIELDS); return QualityEvaluationResult(semantic, semantic_bytes, frozen, frozen_bytes)


__all__ = [
    "QUALITY_DIMENSIONS", "QUALITY_SPLITS", "QualityEvaluationResult",
    "validate_quality_bundle", "evaluate_quality_bundle",
]

# P1-AE correction-1: quality readiness is a closed multi-gate decision.  A
# non-empty case set is never sufficient evidence for a measurement claim.
def _validate_cases(value: Any, cluster_refs: set[str]) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        raise EvaluationError("DENIED_INPUT", "cases must be an array")
    output: list[dict[str, Any]] = []; ids: list[str] = []
    for item in value:
        record = _exact_mapping(item, P1_AE_QUALITY_CASE_FIELDS, "case")
        if record["book_cluster_ref"] not in cluster_refs or record["split"] not in QUALITY_SPLITS or not isinstance(record["input_text"], str):
            raise EvaluationError("DENIED_INPUT", "case identity or split is invalid")
        _require_hash(record["input_text_sha256"], "input_text_sha256")
        if sha256(record["input_text"].encode("utf-8")).hexdigest() != record["input_text_sha256"]:
            raise EvaluationError("DENIED_PROVENANCE", "case input hash mismatch")
        annotations = record["annotations"]
        if not isinstance(annotations, list) or len(annotations) < 2:
            raise EvaluationError("DENIED_AUTHORITY", "case lacks independent annotations")
        canonical_annotations = [_validate_annotation(annotation) for annotation in annotations]
        primary = [annotation for annotation in canonical_annotations if annotation["pass_kind"] == "PRIMARY"]
        if len(primary) < 2 or len({annotation["rater_id"] for annotation in primary}) != len(primary):
            raise EvaluationError("DENIED_AUTHORITY", "primary raters are not independent")
        record["annotations"] = canonical_annotations; ids.append(record["case_id"]); output.append(record)
    strict_sorted_unique(ids, field="case_id")
    return tuple(output)

def validate_quality_bundle(value: Mapping[str, Any]) -> dict[str, Any]:
    record = _exact_mapping(value, P1_AE_QUALITY_BUNDLE_FIELDS, "quality bundle")
    if record["bundle_schema_version"] != "P1-AE-QUALITY-BUNDLE-V1" or record["status"] != "READY":
        raise EvaluationError("DENIED_INPUT", "quality bundle status/schema is not READY v1")
    for field in ("source_snapshot_hash", "rubric_hash", "sampling_plan_hash"):
        _require_hash(record[field], field)
    strata = _validate_strata(record["strata"])
    clusters = _validate_clusters(record["clusters"], {item["stratum_id"] for item in strata})
    cases = _validate_cases(record["cases"], {item["book_cluster_ref"] for item in clusters})
    if {case["case_id"] for case in cases} != {case_id for cluster in clusters for case_id in cluster["case_ids"]}:
        raise EvaluationError("DENIED_INPUT", "cluster/case membership is not one-to-one")
    record.update({"strata": [dict(item) for item in strata], "clusters": [dict(item) for item in clusters], "cases": [dict(item) for item in cases]})
    return record

def _human_reliability(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    metrics = _metrics(cases)
    ready = bool(metrics) and all(item["status"] == "COMPUTED" for item in metrics)
    return {"status": "READY" if ready else "UNPROVEN", "primary_rater_count": len({annotation["rater_id"] for case in cases for annotation in case["annotations"] if annotation["pass_kind"] == "PRIMARY"}), "metrics": metrics}

def _retest_gate(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    primary = sum(1 for case in cases for annotation in case["annotations"] if annotation["pass_kind"] == "PRIMARY")
    retest = sum(1 for case in cases for annotation in case["annotations"] if annotation["pass_kind"] == "RETEST")
    return {"status": "READY" if primary > 0 and retest * 5 >= primary else "UNPROVEN", "primary_count": primary, "retest_count": retest, "minimum_fraction": "0.20"}

def _split_gate(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counts = {split: sum(1 for case in cases if case["split"] == split) for split in QUALITY_SPLITS}
    return {"status": "READY" if all(counts[split] > 0 for split in QUALITY_SPLITS) else "UNPROVEN", "counts": counts}

def _sampling_gate(bundle: Mapping[str, Any]) -> dict[str, Any]:
    quotas = {stratum["stratum_id"]: sum(1 for case in bundle["cases"] if next(cluster["stratum_id"] for cluster in bundle["clusters"] if cluster["book_cluster_ref"] == case["book_cluster_ref"]) == stratum["stratum_id"]) for stratum in bundle["strata"]}
    sample = stratified_hash_order_v1(bundle["clusters"], quotas=quotas, min_cases=quotas, max_cases=quotas, seed=bundle["sampling_plan_hash"])
    return {"status": "READY" if sample["status"] == "VERIFIED" else "UNPROVEN", "sampling": sample}

def _ci_gate(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    holdout = [case for case in cases if case["split"] == "HOLDOUT"]
    return {"status": "READY" if len(holdout) >= 2 else "UNPROVEN", "holdout_case_count": len(holdout), "interval_method": "EXACT_DECIMAL_RATIONAL_V1"}

def _claim_gate(gates: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    required = ("human_reliability", "retest", "split", "sampling", "confidence_interval")
    ready = all(gates[name]["status"] == "READY" for name in required)
    return {"status": "READY" if ready else "MEASUREMENT_UNPROVEN", "required_gates": list(required)}

def _validate_admission(admission_record: Mapping[str, Any]) -> dict[str, Any]:
    record = _exact_mapping(admission_record, P1_AE_QUALITY_ADMISSION_FIELDS, "owner admission")
    if record["admission_schema_version"] != "P1_AE_OWNER_ADMISSION_V1" or record["status"] != "ADMITTED":
        raise EvaluationError("DENIED_PROVENANCE", "owner admission is not admitted")
    for field in ("package_hash", "gate_hash", "permit_digest", "loader_plan_hash", "transition_registry_hash", "transaction_hash", "source_registry_hash", "loaded_module_bindings_hash", "writer_invocation_hash", "post_write_trace_hash", "failure_evidence_hash", "residue_snapshot_hash", "residue_pairing_hash"):
        _require_hash(record[field], field)
    if tuple(record["transition_fields"]) != P1_AE_PURE_LOADER_PLAN_TRANSITION_TUPLE or record["transition_registry_hash"] != p1ae_transition_registry_hash("READY"):
        raise EvaluationError("DENIED_CAPABILITY", "owner admission transition registry mismatch")
    return record

def evaluate_quality_bundle(admission_record: Mapping[str, Any], canonical_quality_bundle: Mapping[str, Any]) -> QualityEvaluationResult:
    admission = _validate_admission(admission_record); bundle = validate_quality_bundle(canonical_quality_bundle)
    if bundle["owner_id"] != admission["owner_id"] or bundle["authority_ref"] != admission["authority_ref"]:
        raise EvaluationError("DENIED_PROVENANCE", "quality bundle owner/authority does not match admission")
    gates = {"human_reliability": _human_reliability(bundle["cases"]), "retest": _retest_gate(bundle["cases"]), "split": _split_gate(bundle["cases"]), "sampling": _sampling_gate(bundle), "confidence_interval": _ci_gate(bundle["cases"])}
    gates["claim"] = _claim_gate(gates)
    identity = {"study_id": bundle["study_id"], "owner_id": bundle["owner_id"], "authority_ref": bundle["authority_ref"], "source_snapshot_hash": bundle["source_snapshot_hash"], "rubric_hash": bundle["rubric_hash"], "sampling_plan_hash": bundle["sampling_plan_hash"], "admission_hash": canonical_sha256(admission, fields=P1_AE_QUALITY_ADMISSION_FIELDS)}
    status = "MEASUREMENT_READY" if gates["claim"]["status"] == "READY" else "MEASUREMENT_UNPROVEN"
    semantic = {"semantic_schema_version": QUALITY_RESULT_SCHEMA_VERSION, "evaluation_identity": identity, "consensus": _consensus(bundle["cases"]), "metrics": _metrics(bundle["cases"]), "reliability_gates": gates, "claim_boundary": {"model_quality": "NOT_MEASURED", "publication_quality": "NOT_MEASURED", "reader_quality": "NOT_MEASURED", "commercial_effect": "NOT_MEASURED"}, "status": status}
    semantic_bytes = canonical_evaluation_json_bytes(semantic, fields=tuple(semantic))
    frozen = {"evidence_schema_version": QUALITY_EVIDENCE_SCHEMA_VERSION, "evaluation_identity": identity, "input_projection": {"bundle_hash": canonical_sha256(bundle, fields=P1_AE_QUALITY_BUNDLE_FIELDS), "case_count": len(bundle["cases"])}, "semantic_result_projection": semantic, "annotation_projection": [{"case_id": item["case_id"], "annotations": item["annotations"]} for item in bundle["cases"]], "metric_projection": semantic["metrics"], "claim_projection": semantic["claim_boundary"], "status": "FROZEN"}
    frozen_bytes = canonical_evaluation_json_bytes(frozen, fields=P1_AE_FROZEN_EVIDENCE_CONTENT_FIELDS)
    return QualityEvaluationResult(semantic, semantic_bytes, frozen, frozen_bytes)

__all__ += ["_human_reliability", "_retest_gate", "_split_gate", "_sampling_gate", "_ci_gate", "_claim_gate"]

# C5 gated correction: quality readiness is an owner-admitted, exact-rational
# decision.  These final definitions intentionally keep the pure evaluator
# input-only: no writer, residue, output lineage, or ambient authority enters
# the frozen evidence projection.
P1_AE_MIN_PRIMARY_CASES = 5
P1_AE_MIN_PRIMARY_RATERS = 2
P1_AE_MIN_RETEST_CASES = 2
P1_AE_MIN_HOLDOUT_CLUSTERS = 2
P1_AE_MIN_RELIABILITY = Fraction(1, 3)


def _final_nonzero_hash(value: Any, field: str) -> str:
    _require_hash(value, field)
    if value == "0" * 64:
        raise EvaluationError("DENIED_PROVENANCE", f"{field} cannot be a zero placeholder")
    return value


def _final_exact_rational_ci(successes: int, total: int) -> dict[str, str]:
    if not isinstance(successes, int) or not isinstance(total, int) or total <= 0 or successes < 0 or successes > total:
        raise EvaluationError("DENIED_INPUT", "confidence interval counts are invalid")
    estimate = Fraction(successes, total)
    margin = Fraction(1, total)
    lower = max(Fraction(0, 1), estimate - margin)
    upper = min(Fraction(1, 1), estimate + margin)
    return {
        "lower": f"{lower.numerator}/{lower.denominator}",
        "estimate": f"{estimate.numerator}/{estimate.denominator}",
        "upper": f"{upper.numerator}/{upper.denominator}",
        "method": "EXACT_DECIMAL_RATIONAL_V1",
    }


def _final_split_gate(bundle: Mapping[str, Any]) -> dict[str, Any]:
    by_case = {case["case_id"]: case["split"] for case in bundle["cases"]}
    leakage = []
    for cluster in bundle["clusters"]:
        splits = {by_case[case_id] for case_id in cluster["case_ids"]}
        if len(splits) != 1:
            leakage.append(cluster["book_cluster_ref"])
    counts = {split: sum(1 for case in bundle["cases"] if case["split"] == split) for split in QUALITY_SPLITS}
    ready = not leakage and all(counts[split] >= 2 for split in QUALITY_SPLITS)
    return {"status": "READY" if ready else "UNPROVEN", "counts": counts, "cluster_leakage": leakage}


def _final_retest_gate(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    primary_case_ids = {case["case_id"] for case in cases if any(a["pass_kind"] == "PRIMARY" for a in case["annotations"])}
    retest_case_ids = {case["case_id"] for case in cases if any(a["pass_kind"] == "RETEST" for a in case["annotations"])}
    retest_raters = {a["rater_id"] for case in cases for a in case["annotations"] if a["pass_kind"] == "RETEST"}
    primary_raters = {a["rater_id"] for case in cases for a in case["annotations"] if a["pass_kind"] == "PRIMARY"}
    distinct = retest_raters.isdisjoint(primary_raters)
    ratio_ok = bool(primary_case_ids) and len(retest_case_ids) * 5 >= len(primary_case_ids)
    ready = len(primary_case_ids) >= P1_AE_MIN_PRIMARY_CASES and len(retest_case_ids) >= P1_AE_MIN_RETEST_CASES and len(retest_raters) >= 2 and distinct and ratio_ok
    return {"status": "READY" if ready else "UNPROVEN", "primary_case_count": len(primary_case_ids), "retest_case_count": len(retest_case_ids), "distinct_retest_rater_count": len(retest_raters), "primary_retest_disjoint": distinct, "minimum_retest_fraction": "1/5"}


def _final_human_reliability(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    metrics = _metrics(cases)
    primary_raters = {a["rater_id"] for case in cases for a in case["annotations"] if a["pass_kind"] == "PRIMARY"}
    values = [Fraction(item["value"]) for item in metrics if item["status"] == "COMPUTED" and item["value"] is not None]
    ready = len(cases) >= P1_AE_MIN_PRIMARY_CASES and len(primary_raters) >= P1_AE_MIN_PRIMARY_RATERS and len(values) == len(QUALITY_DIMENSIONS) and all(value >= Fraction(67, 100) for value in values)
    return {"status": "READY" if ready else "UNPROVEN", "primary_case_count": len(cases), "primary_rater_count": len(primary_raters), "minimum_reliability": "67/100", "metrics": metrics, "algorithm": "WEIGHTED_KAPPA_QUADRATIC_1_5"}


def _final_ci_gate(bundle: Mapping[str, Any], admission: Mapping[str, Any]) -> dict[str, Any]:
    holdout = [case for case in bundle["cases"] if case["split"] == "HOLDOUT"]
    clusters = {case["book_cluster_ref"] for case in holdout}
    study_record = {
        "study_id": bundle["study_id"],
        "project_id": admission["owner_id"],
        "profile_id": admission["authority_ref"],
        "namespace_digest": admission["source_registry_hash"],
        "dataset_manifest_hash": bundle["source_snapshot_hash"],
        "rubric_hash": bundle["rubric_hash"],
        "sampling_plan_hash": bundle["sampling_plan_hash"],
        "stratum_registry_hash": canonical_sha256({"strata": bundle["strata"]}, fields=("strata",)),
        "metric_plan_hash": canonical_sha256({"dimensions": list(QUALITY_DIMENSIONS)}, fields=("dimensions",)),
        "annotator_protocol_hash": admission["owner_annotation_projection_hash"],
        "split_plan_hash": canonical_sha256({"clusters": bundle["clusters"], "cases": [{"case_id": item["case_id"], "split": item["split"]} for item in bundle["cases"]]}, fields=("clusters", "cases")),
        "p1a_contract_hash": admission["loader_plan_hash"],
        "p1a_source_registry_snapshot_hash": admission["source_registry_hash"],
        "p1ae_pure_source_registry_snapshot_hash": admission["loader_plan_hash"],
    }
    intervals: list[dict[str, Any]] = []
    for dimension in QUALITY_DIMENSIONS:
        result = cluster_bootstrap_weighted_kappa_ci(study_record, holdout, dimension=dimension)
        intervals.append({"metric_id": f"IAA_{dimension}", **result})
    ready = bool(intervals) and len(holdout) >= 2 and len(clusters) >= P1_AE_MIN_HOLDOUT_CLUSTERS and all(item["status"] == "READY" and Fraction(item["ci_low"]) >= Fraction(67, 100) for item in intervals)
    return {"status": "READY" if ready else "UNPROVEN", "holdout_case_count": len(holdout), "holdout_cluster_count": len(clusters), "method": "PERCENTILE_95", "cluster_key": "book_cluster_ref", "replicate_count": 2000, "resampling_method": "WITH_REPLACEMENT_BOOK_CLUSTER", "draw_algorithm": "SHA256_COUNTER_MODULO_V1", "quantile_algorithm": "Hyndman_Fan_Type_7", "alpha": "0.05", "intervals": intervals}


def _final_validate_admission(admission_record: Mapping[str, Any], bundle: Mapping[str, Any]) -> dict[str, Any]:
    record = _exact_mapping(admission_record, P1_AE_QUALITY_ADMISSION_FIELDS, "owner admission")
    if record["admission_schema_version"] != "P1_AE_OWNER_ADMISSION_V1" or record["status"] != "ADMITTED":
        raise EvaluationError("DENIED_PROVENANCE", "owner admission is not admitted")
    for field in P1_AE_QUALITY_ADMISSION_FIELDS:
        if field.endswith("_hash") or field in {"package_hash", "gate_hash", "permit_digest", "loader_plan_hash", "transition_registry_hash", "transaction_hash"}:
            _final_nonzero_hash(record[field], field)
    if not isinstance(record["loader_plan_length"], int) or record["loader_plan_length"] <= 0:
        raise EvaluationError("DENIED_PROVENANCE", "loader plan length is not bound")
    if tuple(record["transition_fields"]) != ("PURE_PERMIT_ISSUED", "CAS_CONSUMED", "INTERNAL_PREFLIGHT_RECHECKED", False, False, False, False, True, "ALLOWED") or record["transition_registry_hash"] != p1ae_transition_registry_hash("READY"):
        raise EvaluationError("DENIED_CAPABILITY", "owner admission transition registry mismatch")
    bundle_hash = canonical_sha256(bundle, fields=P1_AE_QUALITY_BUNDLE_FIELDS)
    if record["semantic_hash"] != bundle_hash:
        raise EvaluationError("DENIED_PROVENANCE", "semantic admission binding mismatch")
    _final_binding_validation(record)
    return record


def _final_claim_gate(gates: Mapping[str, Mapping[str, Any]], admission: Mapping[str, Any]) -> dict[str, Any]:
    required = ("human_reliability", "retest", "split", "sampling", "confidence_interval")
    ready = all(gates[name]["status"] == "READY" for name in required)
    bindings = ("package_hash", "gate_hash", "permit_digest", "loader_plan_hash", "transaction_hash", "authority_binding_hash", "resolution_projection_hash", "owner_registry_snapshot_hash", "owner_annotation_projection_hash")
    ready = ready and all(admission.get(field) not in {None, "0" * 64} for field in bindings)
    return {"status": "READY" if ready else "MEASUREMENT_UNPROVEN", "required_gates": list(required), "binding_fields": list(bindings)}


def evaluate_quality_bundle(admission_record: Mapping[str, Any], canonical_quality_bundle: Mapping[str, Any]) -> QualityEvaluationResult:
    bundle = validate_quality_bundle(canonical_quality_bundle)
    admission = _final_validate_admission(admission_record, bundle)
    if bundle["owner_id"] != admission["owner_id"] or bundle["authority_ref"] != admission["authority_ref"]:
        raise EvaluationError("DENIED_PROVENANCE", "quality bundle owner/authority does not match admission")
    gates = {
        "human_reliability": _final_human_reliability(bundle["cases"]),
        "retest": _final_retest_gate(bundle["cases"]),
        "split": _final_split_gate(bundle),
        "sampling": _sampling_gate(bundle),
        "confidence_interval": _final_ci_gate(bundle, admission),
    }
    gates["claim"] = _final_claim_gate(gates, admission)
    identity = {"study_id": bundle["study_id"], "owner_id": bundle["owner_id"], "authority_ref": bundle["authority_ref"], "source_snapshot_hash": bundle["source_snapshot_hash"], "rubric_hash": bundle["rubric_hash"], "sampling_plan_hash": bundle["sampling_plan_hash"], "admission_hash": canonical_sha256(admission, fields=P1_AE_QUALITY_ADMISSION_FIELDS)}
    status = "MEASUREMENT_READY" if gates["claim"]["status"] == "READY" else "MEASUREMENT_UNPROVEN"
    semantic = {"semantic_schema_version": QUALITY_RESULT_SCHEMA_VERSION, "evaluation_identity": identity, "consensus": _consensus(bundle["cases"]), "metrics": _metrics(bundle["cases"]), "reliability_gates": gates, "claim_boundary": {"model_quality": "NOT_MEASURED", "publication_quality": "NOT_MEASURED", "reader_quality": "NOT_MEASURED", "commercial_effect": "NOT_MEASURED"}, "status": status}
    semantic_bytes = canonical_evaluation_json_bytes(semantic, fields=tuple(semantic))
    frozen = {"evidence_schema_version": QUALITY_EVIDENCE_SCHEMA_VERSION, "evaluation_identity": identity, "input_projection": {"bundle_hash": canonical_sha256(bundle, fields=P1_AE_QUALITY_BUNDLE_FIELDS), "case_count": len(bundle["cases"])}, "semantic_result_projection": semantic, "annotation_projection": [{"case_id": item["case_id"], "annotations": item["annotations"]} for item in bundle["cases"]], "metric_projection": semantic["metrics"], "claim_projection": semantic["claim_boundary"], "status": "FROZEN"}
    frozen_bytes = canonical_evaluation_json_bytes(frozen, fields=P1_AE_FROZEN_EVIDENCE_CONTENT_FIELDS)
    return QualityEvaluationResult(semantic, semantic_bytes, frozen, frozen_bytes)
