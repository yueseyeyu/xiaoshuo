"""F0 rule-only analysis and scoring orchestration."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from xiaoshuo.pipeline import analysis_scoring_snapshots as snapshots
from xiaoshuo.pipeline.rhythm import book_analyzer


@dataclass(frozen=True)
class RunResult:
    status: snapshots.SnapshotStatus
    analysis_ref: snapshots.SnapshotRef | None
    bundle_ref: snapshots.SnapshotRef | None
    score_ref: snapshots.SnapshotRef | None
    replayed: bool
    error_code: str | None


def _validate_source_path(source_path: Path, evidence_root: Path, run_id: str) -> Path:
    if not isinstance(source_path, Path) or not source_path.is_absolute():
        raise ValueError("SOURCE_PATH_INVALID")
    if any(part in {".", ".."} for part in source_path.parts):
        raise ValueError("SOURCE_PATH_INVALID")
    stage = evidence_root.parent.name
    root = snapshots._root(evidence_root, stage, run_id)
    source_root = root / "inputs" / "source"
    try:
        snapshots._check_reparse(source_root)
        snapshots._check_reparse(source_path)
    except snapshots.SnapshotValidationError as exc:
        raise ValueError("SOURCE_PATH_OUT_OF_SCOPE") from exc
    resolved_source = source_path.resolve(strict=False)
    try:
        resolved_source.relative_to(source_root.resolve(strict=False))
    except ValueError as exc:
        raise ValueError("SOURCE_PATH_OUT_OF_SCOPE") from exc
    if not source_path.exists():
        raise ValueError("SOURCE_FILE_INVALID")
    if not source_path.is_file():
        raise ValueError("SOURCE_FILE_INVALID")
    return source_path


def _validate_policies(analysis_policy: Mapping[str, Any], scoring_policy: Mapping[str, Any]) -> None:
    if dict(analysis_policy) != {"version": "rule-only-v1", "min_rows": 10}:
        raise ValueError("INVALID_ANALYSIS_POLICY")
    if set(scoring_policy) != {"formula_version", "sub_genre", "known_quality", "min_rows"}:
        raise ValueError("INVALID_SCORING_POLICY")
    if not isinstance(scoring_policy["formula_version"], str) or not isinstance(scoring_policy["sub_genre"], str):
        raise TypeError("INVALID_SCORING_POLICY_TYPES")
    if not isinstance(scoring_policy["known_quality"], bool) or scoring_policy["min_rows"] != 10:
        raise ValueError("INVALID_SCORING_POLICY_VALUES")


def _metadata(
    *, stage: str, run_id: str, attempt_id: str, idempotency_key: str, genre: str,
    book_id: str, source_hash: str, snapshot_type: str, status: snapshots.SnapshotStatus,
    upstream: snapshots.SnapshotRef | None, created_at: str,
) -> snapshots.SnapshotMetadata:
    return snapshots.build_snapshot_metadata(
        snapshot_type=snapshot_type, schema_version="f0-v1", stage=stage,
        run_id=run_id, attempt_id=attempt_id, idempotency_key=idempotency_key,
        genre=genre, book_id=book_id, source_input_hash=source_hash,
        upstream_snapshot_id=upstream.snapshot_id if upstream else None,
        upstream_snapshot_hash=upstream.content_hash if upstream else None,
        config_hash="explicit-policy", rubric_version="rule-only-v1",
        calibration_version="none", weight_version="explicit-v1",
        pool_version="explicit-v1", status=status,
        created_by="analysis_scoring_runner",
        created_at=created_at,
    )


def _run_rule_only_with_analyzer(
    source_path: Path, *, evidence_root: Path, run_id: str, attempt_id: str,
    idempotency_key: str, genre: str, book_id: str, pool: Mapping[str, Any],
    analysis_policy: Mapping[str, Any], scoring_policy: Mapping[str, Any],
    analyzer: Callable[..., book_analyzer.RuleOnlyAnalysisResult],
) -> RunResult:
    try:
        _validate_policies(analysis_policy, scoring_policy)
    except (TypeError, ValueError) as exc:
        return RunResult("FAILED", None, None, None, False, str(exc))
    try:
        source_path = _validate_source_path(source_path, evidence_root, run_id)
    except ValueError as exc:
        return RunResult("FAILED", None, None, None, False, str(exc))
    try:
        source_mtime = source_path.stat().st_mtime
        source_bytes = source_path.read_bytes()
    except OSError:
        return RunResult("FAILED", None, None, None, False, "SOURCE_READ_FAILED")
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    created_at = datetime.fromtimestamp(source_mtime, timezone.utc).isoformat()
    text = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "utf-16"):
        try:
            text = source_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        stage = evidence_root.parent.name
        metadata = _metadata(
            stage=stage, run_id=run_id, attempt_id=attempt_id,
            idempotency_key=idempotency_key, genre=genre, book_id=book_id,
            source_hash=source_hash, snapshot_type="AnalysisSnapshot", status="FAILED",
            upstream=None, created_at=created_at,
        )
        ref = snapshots.publish_snapshot(evidence_root, metadata, {
            "status": "FAILED", "error_code": "SOURCE_DECODE_FAILED",
        })
        return RunResult("FAILED", ref, None, None, ref.replayed, "SOURCE_DECODE_FAILED")

    result = analyzer(text, book_id=book_id, min_rows=analysis_policy["min_rows"])
    if result.status not in {"COMPLETE", "INSUFFICIENT", "FAILED"}:
        return RunResult("FAILED", None, None, None, False, "INVALID_STATUS")
    stage = evidence_root.parent.name
    analysis_metadata = _metadata(
        stage=stage, run_id=run_id, attempt_id=attempt_id,
        idempotency_key=idempotency_key, genre=genre, book_id=book_id,
        source_hash=source_hash, snapshot_type="AnalysisSnapshot", status=result.status,
        upstream=None, created_at=created_at,
    )
    analysis_ref = snapshots.publish_snapshot(evidence_root, analysis_metadata, {
        "status": result.status, "book_id": result.book_id,
        "total_chaps": result.total_chaps, "total_words": result.total_words,
        "rows": result.rows, "summary": result.summary,
        "error_code": result.error_code,
        "analysis_policy_version": result.analysis_policy_version,
    })
    if result.status != "COMPLETE":
        return RunResult(result.status, analysis_ref, None, None, analysis_ref.replayed, result.error_code)

    bundle_metadata = _metadata(
        stage=stage, run_id=run_id, attempt_id=attempt_id,
        idempotency_key=idempotency_key, genre=genre, book_id=book_id,
        source_hash=source_hash, snapshot_type="ScoreInputBundle", status="COMPLETE",
        upstream=analysis_ref, created_at=created_at,
    )
    bundle_ref = snapshots.publish_snapshot(evidence_root, bundle_metadata, {
        "rows": result.rows, "analysis_summary": result.summary,
        "analysis_policy": dict(analysis_policy),
    })
    from xiaoshuo.pipeline.scoring import commercial_engine
    score_result = commercial_engine.compute_rule_only_score_explicit(
        result.rows, pool=pool, genre=genre, book_name=book_id,
        scoring_policy=scoring_policy,
    )
    if score_result.status not in {"COMPLETE", "INSUFFICIENT", "FAILED"}:
        return RunResult("FAILED", analysis_ref, bundle_ref, None, False, "INVALID_STATUS")
    score_metadata = _metadata(
        stage=stage, run_id=run_id, attempt_id=attempt_id,
        idempotency_key=idempotency_key, genre=genre, book_id=book_id,
        source_hash=source_hash, snapshot_type="ScoreSnapshot", status=score_result.status,
        upstream=bundle_ref, created_at=created_at,
    )
    score_ref = snapshots.publish_snapshot(evidence_root, score_metadata, asdict(score_result))
    replayed = analysis_ref.replayed and bundle_ref.replayed and score_ref.replayed
    return RunResult(score_result.status, analysis_ref, bundle_ref, score_ref, replayed, score_result.error_code)


def run_rule_only(
    source_path: Path, *, evidence_root: Path, run_id: str, attempt_id: str,
    idempotency_key: str, genre: str, book_id: str, pool: Mapping[str, Any],
    analysis_policy: Mapping[str, Any], scoring_policy: Mapping[str, Any],
) -> RunResult:
    return _run_rule_only_with_analyzer(
        source_path, evidence_root=evidence_root, run_id=run_id,
        attempt_id=attempt_id, idempotency_key=idempotency_key, genre=genre,
        book_id=book_id, pool=pool, analysis_policy=analysis_policy,
        scoring_policy=scoring_policy, analyzer=book_analyzer.analyze_book_rule_only,
    )
