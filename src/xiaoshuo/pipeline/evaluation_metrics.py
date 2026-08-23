"""Pure structural metrics for the offline evaluator.

No metric in this module imports a project module, reads configuration, calls a
model, or performs I/O.  It accepts already verified UTF-8 bytes and returns
closed metric/finding records only.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
from typing import Any, Mapping, Sequence

from .evaluation_contracts import DECIMAL_GRAMMAR_022, EvaluationError, P1_AE_BOOTSTRAP_REPLICATE_COUNT, P1_AE_BOOTSTRAP_SEED_FIELDS, canonical_evaluation_json_bytes, parse_canonical_evaluation_json, sha256_bytes, strict_sorted_unique


ALLOWED_METRICS = (
    "deterministic_equivalence", "input_integrity", "output_containment",
    "provenance_completeness", "reference_resolution", "rule_coverage",
    "schema_conformance",
)
STRATIFIED_HASH_ORDER_V1 = "STRATIFIED_HASH_ORDER_V1"
STRATIFIED_HASH_ORDER_FEASIBILITY_V1 = "STRATIFIED_HASH_ORDER_FEASIBILITY_V1"
CLAIM_BOUNDARY = {
    "model_quality": "NOT_MEASURED",
    "publication_quality": "NOT_MEASURED",
    "reader_appeal": "NOT_MEASURED",
    "calibration_accuracy": "NOT_MEASURED",
    "commercial_effect": "NOT_MEASURED",
}
METRIC_RESULT_FIELDS = ("metric_id", "status", "value", "finding_ids")
FINDING_FIELDS = ("finding_id", "metric_id", "code", "severity", "message_key")
EXPECTED_FIXTURE_FIELDS = ("bundle_schema_version", "records", "references", "rules")
RECORD_FIELDS = ("record_id", "text", "tags")
REFERENCE_FIELDS = ("reference_id", "target_id")
RULE_FIELDS = ("rule_id", "kind", "expected")


@dataclass(frozen=True)
class Finding:
    finding_id: str
    metric_id: str
    code: str
    severity: str
    message_key: str

    def to_mapping(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in FINDING_FIELDS}


@dataclass(frozen=True)
class MetricResult:
    metric_id: str
    status: str
    value: Any
    finding_ids: tuple[str, ...]

    def to_mapping(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "status": self.status,
            "value": self.value,
            "finding_ids": list(self.finding_ids),
        }


@dataclass(frozen=True)
class MetricsReport:
    metric_results: tuple[MetricResult, ...]
    findings: tuple[Finding, ...]
    classification: str
    bundle_hash: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "metric_results": [item.to_mapping() for item in self.metric_results],
            "findings": [item.to_mapping() for item in self.findings],
            "classification": self.classification,
            "bundle_hash": self.bundle_hash,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_evaluation_json_bytes(self.to_mapping())


def _finding(index: int, metric_id: str, code: str, severity: str = "ERROR") -> Finding:
    return Finding(
        finding_id=f"F-{index:04d}",
        metric_id=metric_id,
        code=code,
        severity=severity,
        message_key=f"{metric_id}.{code.lower()}",
    )


def _metric(metric_id: str, status: str, value: Any, findings: Sequence[Finding]) -> MetricResult:
    return MetricResult(metric_id, status, value, tuple(item.finding_id for item in findings if item.metric_id == metric_id))


def _schema_metric(bundle: Any, expected_schema_id: str, start: int) -> tuple[MetricResult, list[Finding], int]:
    findings: list[Finding] = []
    index = start
    if expected_schema_id != "artifact-bundle-v1":
        finding = _finding(index, "schema_conformance", "UNKNOWN_SCHEMA")
        return _metric("schema_conformance", "FAILED", None, [finding]), [finding], index + 1
    if not isinstance(bundle, Mapping) or tuple(bundle.keys()) != EXPECTED_FIXTURE_FIELDS:
        finding = _finding(index, "schema_conformance", "FIELD_CLOSURE")
        return _metric("schema_conformance", "FAILED", None, [finding]), [finding], index + 1
    if bundle.get("bundle_schema_version") != "v1":
        finding = _finding(index, "schema_conformance", "VERSION")
        return _metric("schema_conformance", "FAILED", None, [finding]), [finding], index + 1
    records = bundle.get("records")
    if not isinstance(records, list) or not records:
        finding = _finding(index, "schema_conformance", "RECORD_CARDINALITY")
        return _metric("schema_conformance", "FAILED", None, [finding]), [finding], index + 1
    ids: list[str] = []
    for record in records:
        if not isinstance(record, Mapping) or tuple(record.keys()) != RECORD_FIELDS:
            finding = _finding(index, "schema_conformance", "RECORD_FIELDS")
            findings.append(finding)
            index += 1
            continue
        if not isinstance(record["record_id"], str) or not record["record_id"] or not isinstance(record["text"], str) or not isinstance(record["tags"], list):
            finding = _finding(index, "schema_conformance", "RECORD_TYPES")
            findings.append(finding)
            index += 1
            continue
        ids.append(record["record_id"])
        try:
            strict_sorted_unique(record["tags"], field="tags")
        except EvaluationError:
            finding = _finding(index, "schema_conformance", "TAG_ORDER")
            findings.append(finding)
            index += 1
    if len(ids) != len(set(ids)):
        finding = _finding(index, "schema_conformance", "DUPLICATE_RECORD")
        findings.append(finding)
        index += 1
    references = bundle.get("references")
    if not isinstance(references, list):
        finding = _finding(index, "schema_conformance", "REFERENCE_TYPES")
        findings.append(finding)
        index += 1
    else:
        for reference in references:
            if not isinstance(reference, Mapping) or tuple(reference.keys()) != REFERENCE_FIELDS or not all(isinstance(reference[key], str) and reference[key] for key in REFERENCE_FIELDS):
                finding = _finding(index, "schema_conformance", "REFERENCE_FIELDS")
                findings.append(finding)
                index += 1
    rules = bundle.get("rules")
    if not isinstance(rules, list):
        finding = _finding(index, "schema_conformance", "RULE_TYPES")
        findings.append(finding)
        index += 1
    else:
        rule_ids: list[str] = []
        for rule in rules:
            if not isinstance(rule, Mapping) or tuple(rule.keys()) != RULE_FIELDS or not isinstance(rule.get("rule_id"), str) or not isinstance(rule.get("kind"), str):
                finding = _finding(index, "schema_conformance", "RULE_FIELDS")
                findings.append(finding)
                index += 1
            else:
                rule_ids.append(rule["rule_id"])
        if len(rule_ids) != len(set(rule_ids)):
            finding = _finding(index, "schema_conformance", "DUPLICATE_RULE")
            findings.append(finding)
            index += 1
    status = "PASS" if not findings else "FAILED"
    return _metric("schema_conformance", status, len(records) if isinstance(records, list) else None, findings), findings, index


def _reference_metric(bundle: Any, start: int) -> tuple[MetricResult, list[Finding], int]:
    findings: list[Finding] = []
    index = start
    if not isinstance(bundle, Mapping) or not isinstance(bundle.get("records"), list) or not isinstance(bundle.get("references"), list):
        finding = _finding(index, "reference_resolution", "SCHEMA_UNAVAILABLE")
        return _metric("reference_resolution", "NOT_APPLICABLE", None, [finding]), [finding], index + 1
    known = {record.get("record_id") for record in bundle["records"] if isinstance(record, Mapping)}
    for reference in bundle["references"]:
        if isinstance(reference, Mapping) and reference.get("target_id") not in known:
            finding = _finding(index, "reference_resolution", "MISSING_TARGET")
            findings.append(finding)
            index += 1
    status = "PASS" if not findings else "FAIL"
    return _metric("reference_resolution", status, len(bundle["references"]), findings), findings, index


def _rule_metric(bundle: Any, start: int) -> tuple[MetricResult, list[Finding], int]:
    findings: list[Finding] = []
    index = start
    rules = bundle.get("rules") if isinstance(bundle, Mapping) else None
    if not isinstance(rules, list):
        finding = _finding(index, "rule_coverage", "SCHEMA_UNAVAILABLE")
        return _metric("rule_coverage", "NOT_APPLICABLE", None, [finding]), [finding], index + 1
    statuses: list[str] = []
    records = bundle.get("records", [])
    for rule in rules:
        if not isinstance(rule, Mapping):
            continue
        kind = rule.get("kind")
        if kind == "non_empty_text":
            passed = all(isinstance(record, Mapping) and bool(record.get("text")) for record in records)
            statuses.append("PASS" if passed else "FAIL")
            if not passed:
                finding = _finding(index, "rule_coverage", "NON_EMPTY_TEXT")
                findings.append(finding)
                index += 1
        elif kind == "record_count_at_least":
            expected = rule.get("expected")
            passed = isinstance(expected, int) and len(records) >= expected
            statuses.append("PASS" if passed else "FAIL")
            if not passed:
                finding = _finding(index, "rule_coverage", "RECORD_COUNT")
                findings.append(finding)
                index += 1
        else:
            statuses.append("NOT_APPLICABLE")
    status = "PASS" if statuses and all(item in {"PASS", "NOT_APPLICABLE"} for item in statuses) else ("FAIL" if statuses else "NOT_APPLICABLE")
    return _metric("rule_coverage", status, statuses, findings), findings, index


def evaluate_bundle_bytes(content: bytes, *, expected_schema_id: str, declared_metrics: Sequence[str]) -> MetricsReport:
    """Evaluate only the structural fixture bundle; no score is inferred."""
    try:
        metrics = strict_sorted_unique(declared_metrics, field="declared_metrics")
        unknown = set(metrics) - set(ALLOWED_METRICS)
        if unknown:
            raise EvaluationError("FAILED_SCHEMA", "unknown declared metric", metrics=sorted(unknown))
        bundle = parse_canonical_evaluation_json(content)
    except EvaluationError as exc:
        finding = _finding(1, "input_integrity", exc.code)
        result = _metric("input_integrity", "FAILED", None, [finding])
        return MetricsReport((result,), (finding,), "FAILED_SCHEMA", sha256_bytes(content))

    findings: list[Finding] = []
    results: list[MetricResult] = []
    schema_result, schema_findings, next_index = _schema_metric(bundle, expected_schema_id, 1)
    results.append(schema_result)
    findings.extend(schema_findings)
    results.append(_metric("input_integrity", "PASS", {"length": len(content), "sha256": sha256_bytes(content)}, ()))
    ref_result, ref_findings, next_index = _reference_metric(bundle, next_index)
    results.append(ref_result)
    findings.extend(ref_findings)
    rule_result, rule_findings, next_index = _rule_metric(bundle, next_index)
    results.append(rule_result)
    findings.extend(rule_findings)
    for metric_id in metrics:
        if metric_id not in {result.metric_id for result in results}:
            results.append(_metric(metric_id, "NOT_APPLICABLE", None, ()))
    results.sort(key=lambda item: item.metric_id)
    findings.sort(key=lambda item: item.finding_id)
    classification = "FAILED_SCHEMA" if any(item.metric_id == "schema_conformance" and item.status == "FAILED" for item in results) else ("FAILED_RULE" if any(item.metric_id == "rule_coverage" and item.status == "FAIL" for item in results) else "COMPLETED_DETERMINISTIC")
    return MetricsReport(tuple(results), tuple(findings), classification, sha256_bytes(content))


__all__ = [
    "ALLOWED_METRICS", "CLAIM_BOUNDARY", "Finding", "MetricResult", "MetricsReport",
    "evaluate_bundle_bytes",
]


# P1-AE pure, deterministic metrics.  These functions accept already
# canonical owner projections only; they do not read files, use global random
# state, or call a model/service.
from fractions import Fraction
from hashlib import sha256
from unicodedata import normalize


def canonical_decimal_rational(value: Any) -> Fraction:
    if isinstance(value, bool) or isinstance(value, float):
        raise EvaluationError("DENIED_INPUT", "decimal rational must be a canonical string")
    if not isinstance(value, str) or not DECIMAL_GRAMMAR_022.fullmatch(value):
        raise EvaluationError("DENIED_INPUT", "decimal rational grammar mismatch")
    negative = value.startswith("-")
    token = value[1:] if negative else value
    if "." in token:
        whole, decimal = token.split(".", 1)
        denominator = 10 ** len(decimal)
        numerator = int(whole) * denominator + int(decimal or "0")
        result = Fraction(numerator, denominator)
    else:
        result = Fraction(int(token), 1)
    return -result if negative else result


def _rank(values: Sequence[Any]) -> list[Fraction]:
    positions: dict[Any, list[int]] = {}
    for index, value in enumerate(values):
        positions.setdefault(value, []).append(index)
    ordered = sorted(positions, key=lambda item: (str(item), repr(item)))
    ranks: dict[Any, Fraction] = {}
    cursor = 0
    for value in ordered:
        indexes = positions[value]
        ranks[value] = Fraction(cursor + cursor + len(indexes) - 1, 2)
        cursor += len(indexes)
    return [ranks[value] for value in values]


def spearman_rho(left: Sequence[Any], right: Sequence[Any]) -> Fraction | None:
    if len(left) != len(right) or not left:
        return None
    left_rank, right_rank = _rank(left), _rank(right)
    if len(set(left_rank)) == 1 or len(set(right_rank)) == 1:
        return None
    n = len(left_rank)
    mean = Fraction(n - 1, 2)
    numerator = sum((a - mean) * (b - mean) for a, b in zip(left_rank, right_rank))
    left_sum = sum((a - mean) ** 2 for a in left_rank)
    right_sum = sum((b - mean) ** 2 for b in right_rank)
    if not left_sum or not right_sum:
        return None
    from decimal import Decimal, getcontext
    getcontext().prec = 40
    decimal_value = Decimal(numerator.numerator) / Decimal(numerator.denominator)
    decimal_denominator = (
        (Decimal(left_sum.numerator) / Decimal(left_sum.denominator))
        * (Decimal(right_sum.numerator) / Decimal(right_sum.denominator))
    ).sqrt()
    return Fraction(str(decimal_value / decimal_denominator))


def weighted_kappa(observed: Sequence[int], expected: Sequence[int], *, scale_min: int = 1, scale_max: int = 5) -> Fraction | None:
    if len(observed) != len(expected) or not observed:
        return None
    if any(value < scale_min or value > scale_max for value in (*observed, *expected)):
        raise EvaluationError("DENIED_INPUT", "kappa value outside registered scale")
    categories = list(range(scale_min, scale_max + 1))
    denominator = (scale_max - scale_min) ** 2
    if denominator == 0:
        return None
    disagreement = sum(Fraction((a - b) ** 2, denominator) for a, b in zip(observed, expected)) / len(observed)
    observed_counts = {value: observed.count(value) for value in categories}
    expected_counts = {value: expected.count(value) for value in categories}
    expected_disagreement = sum(
        Fraction(observed_counts[a] * expected_counts[b], len(observed) ** 2)
        * Fraction((a - b) ** 2, denominator)
        for a in categories for b in categories
    )
    if expected_disagreement == 1:
        return None
    return Fraction(1, 1) - disagreement / expected_disagreement


def pairwise_accuracy(values: Sequence[str], expected: Sequence[str]) -> Fraction | None:
    if len(values) != len(expected) or not values:
        return None
    allowed = {"A", "B", "TIE"}
    if any(item not in allowed for item in (*values, *expected)):
        raise EvaluationError("DENIED_INPUT", "pairwise label is outside the closed enum")
    return Fraction(sum(actual == target for actual, target in zip(values, expected)), len(values))


def _stable_hash(key: str, seed: str) -> bytes:
    return sha256((seed + "\x00" + normalize("NFC", key)).encode("utf-8")).digest()


def stratified_hash_order_v1(
    clusters: Sequence[Mapping[str, Any]],
    *,
    quotas: Mapping[str, int],
    seed: str,
    min_cases: Mapping[str, int] | None = None,
    max_cases: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Select whole clusters in deterministic hash order.

    A cluster is the atomic unit.  After a cluster is visited it is removed
    from ``R_remaining`` before the next feasibility check; skipped clusters
    can therefore never re-enter a later witness.
    """
    if not isinstance(seed, str) or not seed:
        raise EvaluationError("DENIED_INPUT", "sampling seed is missing")
    min_cases = dict(min_cases or {})
    max_cases = dict(max_cases or {})
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for cluster in clusters:
        if not isinstance(cluster, Mapping):
            raise EvaluationError("DENIED_INPUT", "cluster must be an object")
        cluster_id = cluster.get("book_cluster_ref")
        stratum = cluster.get("stratum_id")
        case_ids = cluster.get("case_ids")
        if not isinstance(cluster_id, str) or not isinstance(stratum, str) or not isinstance(case_ids, list) or not case_ids:
            raise EvaluationError("DENIED_INPUT", "cluster fields are incomplete")
        if cluster_id in seen or case_ids != sorted(case_ids, key=lambda item: normalize("NFC", item).encode("utf-8")):
            raise EvaluationError("DENIED_INPUT", "cluster identity/order is not canonical")
        seen.add(cluster_id)
        normalized.append({"book_cluster_ref": cluster_id, "stratum_id": stratum, "case_ids": list(case_ids)})
    normalized.sort(key=lambda item: _stable_hash(item["book_cluster_ref"], seed))
    remaining = list(normalized)
    selected: list[dict[str, Any]] = []
    counts = {key: 0 for key in quotas}
    trace: list[dict[str, Any]] = []

    def feasible_after(candidate: Mapping[str, Any], rest: Sequence[Mapping[str, Any]]) -> bool:
        current = dict(counts)
        current[candidate["stratum_id"]] = current.get(candidate["stratum_id"], 0) + len(candidate["case_ids"])
        possible = dict(current)
        for item in rest:
            possible[item["stratum_id"]] = possible.get(item["stratum_id"], 0) + len(item["case_ids"])
        return all(possible.get(key, 0) >= min_cases.get(key, 0) for key in set(quotas) | set(min_cases))

    for rank, cluster in enumerate(normalized):
        # Remove first: F(U, R_remaining) is over the unvisited suffix only.
        if cluster in remaining:
            remaining.remove(cluster)
        key = cluster["stratum_id"]
        reason = None
        if key not in quotas:
            reason = "UNKNOWN_STRATUM"
        elif counts.get(key, 0) + len(cluster["case_ids"]) > quotas[key] + max_cases.get(key, quotas[key]):
            reason = "MAX_CASES"
        elif not feasible_after(cluster, remaining):
            reason = "WOULD_BREAK_FEASIBILITY"
        if reason is None and counts.get(key, 0) < quotas[key]:
            selected.append(cluster)
            counts[key] = counts.get(key, 0) + len(cluster["case_ids"])
            outcome = "SELECTED"
        else:
            outcome = "SKIPPED"
        trace.append({"trace_sequence": len(trace), "rank": rank, "cluster_ref": cluster["book_cluster_ref"], "outcome": outcome, "skip_reason": reason})
    complete = all(counts.get(key, 0) >= value for key, value in quotas.items())
    status = "VERIFIED" if complete else "UNDERPOWERED_NO_FALLBACK"
    trace_bytes = canonical_evaluation_json_bytes({"trace": trace}, fields=("trace",))
    return {"selected_clusters": selected, "counts": counts, "trace": trace,
            "trace_hash": sha256_bytes(trace_bytes), "status": status}


__all__ += [
    "canonical_decimal_rational", "spearman_rho", "weighted_kappa",
    "pairwise_accuracy", "stratified_hash_order_v1",
    "STRATIFIED_HASH_ORDER_V1", "STRATIFIED_HASH_ORDER_FEASIBILITY_V1",
]

# P1-AE correction-1: exact whole-cluster sampling.  The feasibility witness
# is evaluated only on the unvisited suffix, and the trace hash covers only
# the contiguous trace_sequence projection.
def stratified_hash_order_v1(
    clusters: Sequence[Mapping[str, Any]], *, quotas: Mapping[str, int], seed: str,
    min_cases: Mapping[str, int] | None = None, max_cases: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    if not isinstance(seed, str) or not seed or not isinstance(quotas, Mapping) or not quotas:
        raise EvaluationError("DENIED_INPUT", "sampling seed/quotas are not canonical")
    minimum = {key: int((min_cases or {}).get(key, quota)) for key, quota in quotas.items()}
    maximum = {key: int((max_cases or {}).get(key, quota)) for key, quota in quotas.items()}
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in (*quotas.values(), *minimum.values(), *maximum.values())):
        raise EvaluationError("DENIED_INPUT", "sampling quota values are invalid")
    if any(minimum[key] > quotas[key] or quotas[key] > maximum[key] for key in quotas):
        raise EvaluationError("DENIED_INPUT", "sampling min/quota/max ordering is invalid")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in clusters:
        if not isinstance(source, Mapping):
            raise EvaluationError("DENIED_INPUT", "sampling cluster is not a mapping")
        ref, stratum, case_ids = source.get("book_cluster_ref"), source.get("stratum_id"), source.get("case_ids")
        if not isinstance(ref, str) or not ref or ref in seen or not isinstance(stratum, str) or not isinstance(case_ids, list) or not case_ids:
            raise EvaluationError("DENIED_INPUT", "sampling cluster identity is incomplete")
        if any(not isinstance(case_id, str) or not case_id for case_id in case_ids) or tuple(case_ids) != tuple(sorted(case_ids, key=lambda item: normalize("NFC", item).encode("utf-8"))):
            raise EvaluationError("DENIED_INPUT", "sampling case order is not canonical")
        seen.add(ref); normalized.append({"book_cluster_ref": ref, "stratum_id": stratum, "case_ids": list(case_ids)})
    normalized.sort(key=lambda item: (_stable_hash(item["book_cluster_ref"], seed), normalize("NFC", item["book_cluster_ref"]).encode("utf-8")))

    def witness(current: Mapping[str, int], suffix: Sequence[Mapping[str, Any]]) -> bool:
        states = {tuple(sorted((key, int(value)) for key, value in current.items()))}
        for item in suffix:
            delta = len(item["case_ids"]); key = item["stratum_id"]
            next_states = set(states)
            for state in states:
                values = dict(state); values[key] = values.get(key, 0) + delta
                if key not in quotas or values[key] <= maximum[key]:
                    next_states.add(tuple(sorted(values.items())))
            states = next_states
        for state in states:
            values = dict(state)
            if all(minimum[key] <= values.get(key, 0) <= maximum[key] and values.get(key, 0) == quotas[key] for key in quotas):
                return True
        return False

    remaining = list(normalized); selected: list[dict[str, Any]] = []; counts = {key: 0 for key in quotas}; trace: list[dict[str, Any]] = []
    for rank, cluster in enumerate(normalized):
        remaining.pop(0)
        key, size = cluster["stratum_id"], len(cluster["case_ids"])
        reason: str | None = None
        if key not in quotas:
            reason = "UNKNOWN_STRATUM"
        elif counts[key] + size > maximum[key] or counts[key] + size > quotas[key]:
            reason = "EXCEEDS_QUOTA_OR_MAX"
        else:
            candidate_counts = dict(counts); candidate_counts[key] += size
            if not witness(candidate_counts, remaining):
                reason = "WOULD_BREAK_FEASIBILITY"
        if reason is None:
            selected.append(cluster); counts[key] += size; outcome = "SELECTED"
        else:
            outcome = "SKIPPED"
        trace.append({"trace_sequence": len(trace), "rank": rank, "cluster_ref": cluster["book_cluster_ref"], "outcome": outcome, "skip_reason": reason})
    complete = all(counts[key] == quotas[key] and minimum[key] <= counts[key] <= maximum[key] for key in quotas)
    trace_hash = sha256_bytes(canonical_evaluation_json_bytes({"trace": trace}, fields=("trace",)))
    return {"selected_clusters": selected, "counts": counts, "trace": trace, "trace_hash": trace_hash, "status": "VERIFIED" if complete else "UNDERPOWERED_NO_FALLBACK"}

__all__ += ["stratified_hash_order_v1"]


# Contract-fixed P1-AE cluster bootstrap.  The implementation is deliberately
# integer/rational only; callers cannot provide a seed or a percentile method.
def _p1ae_metric_pairs(cases: Sequence[Mapping[str, Any]], dimension: str) -> tuple[list[int], list[int]]:
    left: list[int] = []
    right: list[int] = []
    for case in cases:
        annotations = [item for item in case["annotations"] if item["pass_kind"] == "PRIMARY"]
        if len(annotations) < 2:
            continue
        values: list[int] = []
        for annotation in annotations[:2]:
            matches = [item["value"] for item in annotation["dimension_values"] if item["dimension_id"] == dimension and item["value"] is not None]
            if len(matches) != 1:
                values = []
                break
            values.append(matches[0])
        if len(values) == 2:
            left.append(values[0]); right.append(values[1])
    return left, right


def _p1ae_type7(values: Sequence[Fraction], probability: Fraction) -> Fraction:
    ordered = sorted(values)
    if not ordered:
        raise EvaluationError("DENIED_METRIC", "Type-7 percentile requires valid replicates")
    if probability <= 0:
        return ordered[0]
    if probability >= 1:
        return ordered[-1]
    h = Fraction(1, 1) + Fraction(len(ordered) - 1, 1) * probability
    lower_index = h.numerator // h.denominator
    fraction = h - lower_index
    lower = ordered[lower_index - 1]
    upper = ordered[min(lower_index, len(ordered) - 1)]
    return lower + fraction * (upper - lower)


def cluster_bootstrap_weighted_kappa_ci(
    study_record: Mapping[str, Any],
    cases: Sequence[Mapping[str, Any]],
    *,
    dimension: str,
) -> dict[str, Any]:
    if tuple(study_record) != P1_AE_BOOTSTRAP_SEED_FIELDS:
        raise EvaluationError("DENIED_PROVENANCE", "bootstrap study record is not the contract projection")
    seed_bytes = canonical_evaluation_json_bytes(study_record, fields=P1_AE_BOOTSTRAP_SEED_FIELDS)
    seed_hex = sha256(seed_bytes).hexdigest()[:16]
    by_cluster: dict[str, list[Mapping[str, Any]]] = {}
    for case in cases:
        cluster = case.get("book_cluster_ref")
        if not isinstance(cluster, str) or not cluster:
            raise EvaluationError("DENIED_INPUT", "bootstrap case cluster identity is missing")
        by_cluster.setdefault(cluster, []).append(case)
    cluster_refs = sorted(by_cluster, key=lambda value: value.encode("utf-8"))
    if not cluster_refs:
        return {"estimate": None, "ci_low": None, "ci_high": None, "bootstrap_replicates": P1_AE_BOOTSTRAP_REPLICATE_COUNT, "valid_replicates": 0, "invalid_replicates": P1_AE_BOOTSTRAP_REPLICATE_COUNT, "status": "CI_UNAVAILABLE", "reason": "NO_HOLDOUT_CLUSTERS", "seed_hex": seed_hex}
    left, right = _p1ae_metric_pairs(cases, dimension)
    estimate = weighted_kappa(left, right)
    if estimate is None:
        return {"estimate": None, "ci_low": None, "ci_high": None, "bootstrap_replicates": P1_AE_BOOTSTRAP_REPLICATE_COUNT, "valid_replicates": 0, "invalid_replicates": P1_AE_BOOTSTRAP_REPLICATE_COUNT, "status": "CI_UNAVAILABLE", "reason": "NOT_COMPUTABLE", "seed_hex": seed_hex}
    estimates: list[Fraction] = []
    invalid = 0
    for replicate_index in range(P1_AE_BOOTSTRAP_REPLICATE_COUNT):
        sampled: list[Mapping[str, Any]] = []
        for draw_index in range(len(cluster_refs)):
            payload = f":{replicate_index}:{draw_index}".encode("utf-8")
            digest = sha256(seed_hex.encode("utf-8") + payload).digest()
            selected = cluster_refs[int.from_bytes(digest[:8], "big") % len(cluster_refs)]
            sampled.extend(by_cluster[selected])
        sampled_left, sampled_right = _p1ae_metric_pairs(sampled, dimension)
        value = weighted_kappa(sampled_left, sampled_right)
        if value is None:
            invalid += 1
        else:
            estimates.append(value)
    if invalid * 100 > P1_AE_BOOTSTRAP_REPLICATE_COUNT * 5 or not estimates:
        return {"estimate": str(estimate), "ci_low": None, "ci_high": None, "bootstrap_replicates": P1_AE_BOOTSTRAP_REPLICATE_COUNT, "valid_replicates": len(estimates), "invalid_replicates": invalid, "status": "CI_UNAVAILABLE", "reason": "INVALID_REPLICATE_RATE_OVER_5_PERCENT" if invalid * 100 > P1_AE_BOOTSTRAP_REPLICATE_COUNT * 5 else "NO_VALID_REPLICATES", "seed_hex": seed_hex}
    low = _p1ae_type7(estimates, Fraction(1, 40))
    high = _p1ae_type7(estimates, Fraction(39, 40))
    return {"estimate": str(estimate), "ci_low": str(low), "ci_high": str(high), "bootstrap_replicates": P1_AE_BOOTSTRAP_REPLICATE_COUNT, "valid_replicates": len(estimates), "invalid_replicates": invalid, "status": "READY", "reason": None, "seed_hex": seed_hex}


__all__ += ["P1_AE_BOOTSTRAP_SEED_FIELDS", "P1_AE_BOOTSTRAP_REPLICATE_COUNT", "cluster_bootstrap_weighted_kappa_ci"]
