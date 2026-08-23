import ast
import inspect
from pathlib import Path

from xiaoshuo.pipeline.analysis_scoring_runner import run_rule_only
from xiaoshuo.pipeline.rhythm.book_analyzer import RuleOnlyAnalysisResult


RUNNER_PATH = Path(__file__).parents[1] / "src/xiaoshuo/pipeline/analysis_scoring_runner.py"
RUN_ID = "20260814-000001-000007"
EVIDENCE = Path("D:/tmp/yeyu-ai-a3/mvp-analysis-scoring-foundation-f0-correction-implementation") / RUN_ID


def _policies():
    return (
        {"version": "rule-only-v1", "min_rows": 10},
        {"formula_version": "rule-only-v1", "sub_genre": "通用", "known_quality": False, "min_rows": 10},
    )


def test_public_runner_has_no_analyzer_injection_parameter():
    assert "analyzer" not in inspect.signature(run_rule_only).parameters
    tree = ast.parse(RUNNER_PATH.read_text(encoding="utf-8"))
    public = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run_rule_only")
    calls = [node for node in ast.walk(public) if isinstance(node, ast.Call)]
    assert any(isinstance(call.func, ast.Name) and call.func.id == "_run_rule_only_with_analyzer" for call in calls)


def test_private_runner_publishes_structured_insufficient_state(tmp_path):
    source = EVIDENCE / "inputs/source/runner-insufficient.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("not enough chapters", encoding="utf-8")
    analysis_policy, scoring_policy = _policies()

    def analyzer(text, *, book_id, min_rows):
        assert text == "not enough chapters"
        assert book_id == "runner-book"
        assert min_rows == 10
        return RuleOnlyAnalysisResult(
            "INSUFFICIENT", book_id, 0, 0, [], {}, "INSUFFICIENT_CHAPTERS", "rule-only-v1"
        )

    from xiaoshuo.pipeline.analysis_scoring_runner import _run_rule_only_with_analyzer
    result = _run_rule_only_with_analyzer(
        source, evidence_root=EVIDENCE,
        run_id=RUN_ID, attempt_id="runner-test-1",
        idempotency_key="runner-insufficient", genre="末世", book_id="runner-book",
        pool={}, analysis_policy=analysis_policy, scoring_policy=scoring_policy,
        analyzer=analyzer,
    )
    assert result.status == "INSUFFICIENT"
    assert result.analysis_ref is not None
    assert result.bundle_ref is None
    assert result.score_ref is None


def test_public_runner_replays_analysis_bundle_and_score_refs():
    source = EVIDENCE / "inputs/source/runner-replay.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    body = "这是用于规则评分的固定章节正文，包含足够的内容和标点。" * 12
    source.write_text("\n".join(f"第{i}章 标题{i}\n{body}" for i in range(1, 11)), encoding="utf-8")
    analysis_policy, scoring_policy = _policies()
    values = [0.1, 0.5, 1.0]
    pool = {"n_books": 3, **{
        key: {"p25": 0.1, "p50": 0.5, "p75": 1.0, "_sorted": values}
        for key in ("hook_density", "conflict", "intensity", "diversity", "slap_rate", "reversal_rate", "readability")
    }}
    kwargs = {
        "evidence_root": EVIDENCE, "run_id": RUN_ID,
        "attempt_id": "runner-replay-1", "idempotency_key": "runner-replay",
        "genre": "末世", "book_id": "runner-replay-book", "pool": pool,
        "analysis_policy": analysis_policy, "scoring_policy": scoring_policy,
    }
    first = run_rule_only(source, **kwargs)
    second = run_rule_only(source, **kwargs)
    assert first.status == "COMPLETE"
    assert second.replayed is True
    assert second.analysis_ref.replayed is True
    assert second.bundle_ref.replayed is True
    assert second.score_ref.replayed is True


def test_invalid_source_path_returns_structured_failed_without_snapshot(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    analysis_policy, scoring_policy = _policies()
    result = run_rule_only(
        outside, evidence_root=EVIDENCE, run_id=RUN_ID,
        attempt_id="invalid-source-1", idempotency_key="invalid-source",
        genre="末世", book_id="invalid-source-book", pool={},
        analysis_policy=analysis_policy, scoring_policy=scoring_policy,
    )
    assert result.status == "FAILED"
    assert result.analysis_ref is None
    assert result.error_code == "SOURCE_PATH_OUT_OF_SCOPE"


def test_source_reparse_returns_source_path_out_of_scope(monkeypatch):
    import xiaoshuo.pipeline.analysis_scoring_runner as runner
    source = EVIDENCE / "inputs/source/runner-reparse.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("source", encoding="utf-8")
    monkeypatch.setattr(runner.snapshots, "_reparse", lambda path: path.name == "source")
    analysis_policy, scoring_policy = _policies()
    result = run_rule_only(
        source, evidence_root=EVIDENCE, run_id=RUN_ID,
        attempt_id="reparse-source-1", idempotency_key="reparse-source",
        genre="末世", book_id="reparse-source-book", pool={},
        analysis_policy=analysis_policy, scoring_policy=scoring_policy,
    )
    assert result.status == "FAILED"
    assert result.error_code == "SOURCE_PATH_OUT_OF_SCOPE"


def test_source_file_invalid_returns_structured_failed(tmp_path):
    source = EVIDENCE / "inputs/source/runner-directory"
    source.mkdir(parents=True, exist_ok=True)
    analysis_policy, scoring_policy = _policies()
    result = run_rule_only(
        source, evidence_root=EVIDENCE, run_id=RUN_ID,
        attempt_id="invalid-file-1", idempotency_key="invalid-file",
        genre="末世", book_id="invalid-file-book", pool={},
        analysis_policy=analysis_policy, scoring_policy=scoring_policy,
    )
    assert result.status == "FAILED"
    assert result.error_code == "SOURCE_FILE_INVALID"


def test_source_read_error_returns_structured_failed(monkeypatch):
    source = EVIDENCE / "inputs/source/runner-read-error.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("source", encoding="utf-8")
    monkeypatch.setattr(Path, "read_bytes", lambda self: (_ for _ in ()).throw(OSError("read")))
    analysis_policy, scoring_policy = _policies()
    result = run_rule_only(
        source, evidence_root=EVIDENCE, run_id=RUN_ID,
        attempt_id="read-error-1", idempotency_key="read-error",
        genre="末世", book_id="read-error-book", pool={},
        analysis_policy=analysis_policy, scoring_policy=scoring_policy,
    )
    assert result.status == "FAILED"
    assert result.error_code == "SOURCE_READ_FAILED"


def test_decode_failure_returns_structured_failed():
    source = EVIDENCE / "inputs/source/runner-decode-error.bin"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"\xff\xff\xff")
    analysis_policy, scoring_policy = _policies()
    result = run_rule_only(
        source, evidence_root=EVIDENCE, run_id=RUN_ID,
        attempt_id="decode-error-1", idempotency_key="decode-error",
        genre="末世", book_id="decode-error-book", pool={},
        analysis_policy=analysis_policy, scoring_policy=scoring_policy,
    )
    assert result.status == "FAILED"
    assert result.error_code == "SOURCE_DECODE_FAILED"


def test_invalid_analysis_or_score_status_returns_invalid_status():
    from xiaoshuo.pipeline.analysis_scoring_runner import _run_rule_only_with_analyzer
    source = EVIDENCE / "inputs/source/runner-invalid-status.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("source", encoding="utf-8")
    analysis_policy, scoring_policy = _policies()

    def invalid_analyzer(text, *, book_id, min_rows):
        return RuleOnlyAnalysisResult("PARTIAL", book_id, 0, 0, [], {}, None, "rule-only-v1")

    result = _run_rule_only_with_analyzer(
        source, evidence_root=EVIDENCE, run_id=RUN_ID,
        attempt_id="invalid-status-1", idempotency_key="invalid-status",
        genre="末世", book_id="invalid-status-book", pool={},
        analysis_policy=analysis_policy, scoring_policy=scoring_policy,
        analyzer=invalid_analyzer,
    )
    assert result.status == "FAILED"
    assert result.error_code == "INVALID_STATUS"
