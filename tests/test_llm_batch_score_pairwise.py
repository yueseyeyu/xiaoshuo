"""Direct and static tests for the pairwise responsibility split."""

import ast
from pathlib import Path

from xiaoshuo.pipeline import llm_batch_score_pairwise as pairwise


ROOT = Path(__file__).resolve().parents[1]
PAIRWISE_PATH = ROOT / "src" / "xiaoshuo" / "pipeline" / "llm_batch_score_pairwise.py"
FACADE_PATH = ROOT / "src" / "xiaoshuo" / "pipeline" / "llm_batch_score.py"


EXPECTED_PAIRWISE_PROMPT = (
    "=== \u4f60\u662f\u4e13\u4e1a\u7f51\u6587\u7f16\u8f91\uff0c\u8bf7\u5bf9\u6bd4\u4e24\u7ae0\u7684\u9605\u8bfb\u4f53\u9a8c ===\n\n"
    "\u5bf9\u6bd4\u7ef4\u5ea6: \u6574\u4f53\u723d\u611f\u3001\u60c5\u8282\u5f20\u529b\u3001\u9605\u8bfb\u6d41\u7545\u5ea6\u3002\n"
    "\u53ea\u8003\u8651\u9605\u8bfb\u4f53\u9a8c\uff0c\u4e0d\u8003\u8651\u5b57\u6570\u591a\u5c11\u3002\n\n"
    "\u8f93\u51fa\u683c\u5f0f (\u53ea\u8f93\u51fa\u4e00\u4e2a\u5b57\u6bcd):\n"
    "A \u2014 \u7b2cA\u7ae0\u66f4\u597d\n"
    "B \u2014 \u7b2cB\u7ae0\u66f4\u597d\n"
    "T \u2014 \u4e24\u7ae0\u5dee\u4e0d\u591a\n"
)


def _literal_assignment(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assignments = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)
    ]
    assert len(assignments) == 1
    return ast.literal_eval(assignments[0].value)


def _top_level_function(tree, name):
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
    assert len(functions) == 1
    return functions[0]


def test_pairwise_prompt_matches_independent_expected_fixture():
    assert _literal_assignment(PAIRWISE_PATH, "_PAIRWISE_PROMPT") == EXPECTED_PAIRWISE_PROMPT
    assert pairwise._PAIRWISE_PROMPT == EXPECTED_PAIRWISE_PROMPT


def test_bt_fixed_expected_matrix_preserves_verdict_and_key_behavior():
    assert pairwise._bradley_terry_estimate([]) == {}
    assert pairwise._bradley_terry_estimate([(1, 2, "T")]) == {1: 5.0, 2: 5.0}
    assert pairwise._bradley_terry_estimate([(1, 2, "UNKNOWN")]) == {1: 5.0, 2: 5.0}
    assert pairwise._bradley_terry_estimate([(1, 2, "A"), (2, 3, "B")]) == {
        1: 6.7,
        2: 2.5,
        3: 6.7,
    }
    assert pairwise._bradley_terry_estimate([(1, 2, "A"), (1, 2, "A"), (1, 2, "B")]) == {
        1: 6.0,
        2: 4.0,
    }
    assert pairwise._bradley_terry_estimate([(1, "1", "A")]) == {
        1: 6.7,
        "1": 3.3,
    }


def test_bt_preserves_set_iteration_and_does_not_sort_keys():
    source = PAIRWISE_PATH.read_text(encoding="utf-8")
    assert "all_chs = set()" in source
    assert "for ch in all_chs:" in source
    assert "sorted(" not in source


def test_bt_invalid_inputs_remain_exceptional():
    for bad_results, expected in (
        (None, TypeError),
        ([(1, 2)], ValueError),
        ([(1, 2, "A", "extra")], ValueError),
        ([([1], 2, "A")], TypeError),
    ):
        try:
            pairwise._bradley_terry_estimate(bad_results)
        except expected:
            pass
        else:
            raise AssertionError(f"{bad_results!r} must remain {expected.__name__}")


def test_pairwise_module_has_no_import_nodes():
    tree = ast.parse(PAIRWISE_PATH.read_text(encoding="utf-8"))
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in tree.body)
    local_imports = [
        node
        for function in tree.body
        if isinstance(function, ast.FunctionDef)
        for node in ast.walk(function)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert all(
        isinstance(node, ast.ImportFrom)
        and node.level == 0
        and node.module == "collections"
        and [(alias.name, alias.asname) for alias in node.names] == [("defaultdict", None)]
        for node in local_imports
    )


def test_facade_pairwise_import_is_top_level_and_exact():
    tree = ast.parse(FACADE_PATH.read_text(encoding="utf-8"))
    imports = [
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.level == 1
        and node.module is None
        and any(alias.name == "llm_batch_score_pairwise" for alias in node.names)
    ]
    assert len(imports) == 1
    assert {(alias.name, alias.asname) for alias in imports[0].names} == {
        ("llm_batch_score_pairwise", None),
    }


def test_facade_calls_pairwise_owner_without_compatibility_wrapper():
    tree = ast.parse(FACADE_PATH.read_text(encoding="utf-8"))
    wrappers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_bradley_terry_estimate"
    ]
    assert wrappers == []
    owner_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "llm_batch_score_pairwise"
        and node.func.attr == "_bradley_terry_estimate"
    ]
    assert len(owner_calls) == 1
    assert len(owner_calls[0].args) == 1
    assert isinstance(owner_calls[0].args[0], ast.Name)
    assert owner_calls[0].args[0].id == "pairwise_results"
    assert owner_calls[0].keywords == []


def test_facade_retains_pairwise_orchestration_boundaries():
    tree = ast.parse(FACADE_PATH.read_text(encoding="utf-8"))
    llm_compare = _top_level_function(tree, "llm_pairwise_compare")
    batch_scoring = _top_level_function(tree, "batch_pairwise_scoring")

    system_values = [
        keyword.value.attr
        for node in ast.walk(llm_compare)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == "system"
        and isinstance(keyword.value, ast.Attribute)
        and isinstance(keyword.value.value, ast.Name)
        and keyword.value.value.id == "llm_batch_score_pairwise"
    ]
    assert system_values == ["_PAIRWISE_PROMPT"]

    truncates = [
        node
        for node in ast.walk(llm_compare)
        if isinstance(node, ast.FunctionDef) and node.name == "_truncate"
    ]
    assert len(truncates) == 1
    truncate = truncates[0]
    assert [arg.arg for arg in truncate.args.args] == ["text", "maxlen"]
    assert truncate.args.defaults and isinstance(truncate.args.defaults[0], ast.Constant)
    assert truncate.args.defaults[0].value == 600

    assert batch_scoring.name == "batch_pairwise_scoring"
    random_seed_calls = [
        node
        for node in ast.walk(batch_scoring)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "random"
        and node.func.attr == "seed"
    ]
    assert len(random_seed_calls) == 1
    assert [arg.value for arg in random_seed_calls[0].args] == [42]
    assert random_seed_calls[0].keywords == []

    extract_calls = [
        node
        for node in ast.walk(batch_scoring)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "extract_chapters"
    ]
    assert len(extract_calls) == 1

    compare_calls = [
        node
        for node in ast.walk(batch_scoring)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "llm_pairwise_compare"
    ]
    assert len(compare_calls) == 1

    logger_calls = [
        node
        for node in ast.walk(batch_scoring)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "logger"
    ]
    assert logger_calls

    numeric_constants = {
        node.value
        for node in ast.walk(batch_scoring)
        if isinstance(node, ast.Constant) and node.value in {0.6, 0.4}
    }
    assert numeric_constants == {0.6, 0.4}

    bt_range_calls = {
        node.func.id
        for node in ast.walk(batch_scoring)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"min", "max"}
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Call)
        and isinstance(node.args[0].func, ast.Attribute)
        and isinstance(node.args[0].func.value, ast.Name)
        and node.args[0].func.value.id == "bt_scores"
        and node.args[0].func.attr == "values"
    }
    assert bt_range_calls == {"min", "max"}

    estimator_calls = [
        node
        for node in ast.walk(batch_scoring)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "llm_batch_score_pairwise"
        and node.func.attr == "_bradley_terry_estimate"
    ]
    assert len(estimator_calls) == 1
