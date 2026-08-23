import ast
from dataclasses import fields
from pathlib import Path

from xiaoshuo.pipeline.scoring.commercial_engine import (
    RuleOnlyScoreResult,
    compute_rule_only_score_explicit,
)


ENGINE = Path(__file__).parents[1] / "src/xiaoshuo/pipeline/scoring/commercial_engine.py"


def _row(index):
    return {
        "ch_num": index, "hook_density": 1.0, "conflict_density": 0.5,
        "pleasure_intensity": 5.0, "slap_count": 1, "hook_type": "悬念式",
        "dominant_sub": "打脸", "avg_sentence_len": 20, "excl_density": 0.1,
        "dialogue_ratio": 0.2, "emotion_valence": "1", "burnout_count": 0,
        "foreshadow_payoff_count": 0, "identity_reveal_count": 0,
        "readability": 0.5, "vocab_diversity": 0.3, "ch_variability": 0.1,
    }


def _pool():
    values = [0.1, 0.5, 1.0]
    return {
        "n_books": 3,
        **{name: {"p25": 0.1, "p50": 0.5, "p75": 1.0, "_sorted": values} for name in (
            "hook_density", "conflict", "intensity", "diversity",
            "slap_rate", "reversal_rate", "readability",
        )},
    }


def test_explicit_score_contract_and_insufficient_state():
    assert [field.name for field in fields(RuleOnlyScoreResult)] == [
        "status", "overall", "grade", "scores", "risks", "pool_n",
        "formula_version", "error_code",
    ]
    result = compute_rule_only_score_explicit(
        [], pool={}, genre="末世", book_name="book",
        scoring_policy={"formula_version": "v1", "sub_genre": "通用", "known_quality": False, "min_rows": 10},
    )
    assert result.status == "INSUFFICIENT"
    assert result.error_code == "INSUFFICIENT_ROWS"


def test_explicit_score_uses_caller_owned_pool_and_policy():
    result = compute_rule_only_score_explicit(
        [_row(i) for i in range(10)], pool=_pool(), genre="末世", book_name="book",
        scoring_policy={"formula_version": "v1", "sub_genre": "通用", "known_quality": False, "min_rows": 10},
    )
    assert result.status == "COMPLETE"
    assert result.pool_n == 3
    assert result.formula_version == "v1"


def test_explicit_function_has_no_implicit_pool_or_config_calls():
    tree = ast.parse(ENGINE.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "compute_rule_only_score_explicit")
    forbidden = {"get_firebook_pool", "get_config", "_check_known_quality", "get_deepseek_config"}
    calls = [node.func.id for node in ast.walk(function) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
    assert not forbidden.intersection(calls)


def test_explicit_score_success_schema():
    result = compute_rule_only_score_explicit(
        [_row(i) for i in range(10)], pool=_pool(), genre="末世", book_name="book",
        scoring_policy={"formula_version": "v1", "sub_genre": "通用", "known_quality": False, "min_rows": 10},
    )
    assert result.status == "COMPLETE"
    assert isinstance(result.scores, dict)
    assert isinstance(result.risks, list)


def test_explicit_score_rejects_invalid_policy():
    result = compute_rule_only_score_explicit(
        [_row(i) for i in range(10)], pool=_pool(), genre="末世", book_name="book",
        scoring_policy={"min_rows": 10},
    )
    assert result.status == "FAILED"
    assert result.error_code == "INVALID_SCORING_POLICY"


def test_explicit_score_returns_insufficient_for_small_pool():
    result = compute_rule_only_score_explicit(
        [_row(i) for i in range(10)], pool={"n_books": 2}, genre="末世", book_name="book",
        scoring_policy={"formula_version": "v1", "sub_genre": "通用", "known_quality": False, "min_rows": 10},
    )
    assert result.status == "INSUFFICIENT"
    assert result.overall is None


def test_explicit_score_does_not_use_global_pool_or_config():
    test_explicit_function_has_no_implicit_pool_or_config_calls()


def test_explicit_score_is_deterministic():
    kwargs = {
        "pool": _pool(), "genre": "末世", "book_name": "book",
        "scoring_policy": {"formula_version": "v1", "sub_genre": "通用", "known_quality": False, "min_rows": 10},
    }
    first = compute_rule_only_score_explicit([_row(i) for i in range(10)], **kwargs)
    second = compute_rule_only_score_explicit([_row(i) for i in range(10)], **kwargs)
    assert first == second
