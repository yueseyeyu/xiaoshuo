"""Static/targeted contract tests for the first LLM-score split batch."""

import ast
import inspect
from pathlib import Path

from xiaoshuo.pipeline import llm_batch_score_core as core


ROOT = Path(__file__).resolve().parents[1]
FACADE_PATH = ROOT / "src" / "xiaoshuo" / "pipeline" / "llm_batch_score.py"


def _facade_tree():
    return ast.parse(FACADE_PATH.read_text(encoding="utf-8"))


def _facade_wrapper(name):
    wrappers = [
        node
        for node in _facade_tree().body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(wrappers) == 1
    return wrappers[0]


def test_normalize_hook_current_core_contract():
    values = [
        None, "", "none", "weak", "strong", "8", "5.0", "2", "invalid",
        4, 7, 0, False, float("nan"), float("inf"), float("-inf"),
    ]
    assert [core._normalize_hook(value) for value in values] == [
        "none", "none", "none", "weak", "strong", "strong", "weak", "none",
        "none", "weak", "strong", "none", "none", "none", "strong", "none",
    ]

    class ExplodingString:
        def __str__(self):
            raise RuntimeError("string conversion failed")

    try:
        core._normalize_hook(ExplodingString())
    except RuntimeError as exc:
        assert str(exc) == "string conversion failed"
    else:
        raise AssertionError("string conversion errors must remain observable")


def test_truncate_reference_text_current_core_contract():
    marker = "\n...[省略]...\n"
    values = ["", "short", "x" * 400, "x" * 401, "中文" * 300]
    assert core._truncate_reference_text(values[0], 0) == values[0]
    assert core._truncate_reference_text(values[1]) == values[1]
    assert core._truncate_reference_text(values[2]) == values[2]
    assert core._truncate_reference_text(values[3]) == "x" * 133 + marker + "x" * 247
    assert core._truncate_reference_text("x" * 402, 401) == "x" * 133 + marker + "x" * 248
    tiny_text = "x" * 30
    assert core._truncate_reference_text(tiny_text, 0) == marker + "x" * 10
    assert core._truncate_reference_text(tiny_text, 1) == marker + "x" * 11
    assert len(core._truncate_reference_text(values[4])) <= 400

    for args in ((None,), ("abc", "not-an-int")):
        try:
            core._truncate_reference_text(*args)
        except TypeError:
            pass
        else:
            raise AssertionError("invalid truncation inputs must remain TypeError")


def test_select_references_current_core_contract():
    references = [
        {"band": "low", "book": "a", "ch_num": 1, "human_intensity": 2.5},
        {"band": "low", "book": "a2", "ch_num": 2, "human_intensity": 2.5},
        {"band": "medium_low", "book": "b", "ch_num": 2, "human_intensity": 4.5},
        {"band": "medium_high", "book": "c", "ch_num": 3, "human_intensity": 6.5},
        {"band": "high", "book": "d", "ch_num": 4, "human_intensity": 8.5},
    ]
    assert core._select_references(references, "a", 1) == references[1:]

    # Empty and sparse bands retain band order and do not synthesize rows.
    assert core._select_references([]) == []
    sparse = [references[0], references[-1]]
    assert core._select_references(sparse) == sparse

    # If exclusion removes the only candidate in a band, the current-core fallback
    # returns that excluded row rather than silently dropping the band.
    assert core._select_references([references[0]], "a", 1) == [references[0]]

    # Equal-distance ties and duplicate-band rows are stable: the first row wins.
    tie_first = {"band": "low", "book": "tie-a", "ch_num": 1, "human_intensity": 2.0}
    tie_second = {"band": "low", "book": "tie-b", "ch_num": 2, "human_intensity": 3.0}
    duplicate = {"band": "high", "book": "duplicate", "ch_num": 1, "human_intensity": 8.5, "marker": "first"}
    duplicate_again = {**duplicate, "marker": "second"}
    selected = core._select_references([tie_first, tie_second, duplicate, duplicate_again])
    assert selected[0] is tie_first
    assert selected[1] is duplicate

    for bad_references in (None, [{"band": "low"}]):
        try:
            core._select_references(bad_references)
        except (TypeError, KeyError):
            pass
        else:
            raise AssertionError("invalid reference inputs must remain exceptional")


def test_facade_calls_core_owner_without_compatibility_wrappers():
    tree = _facade_tree()
    core_imports = [
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.level == 1
        and node.module is None
        and any(alias.name == "llm_batch_score_core" for alias in node.names)
    ]
    assert len(core_imports) == 1
    assert {(alias.name, alias.asname) for alias in core_imports[0].names} == {
        ("llm_batch_score_core", None),
    }
    assert not any(isinstance(node, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == "__all__"
        for target in node.targets
    ) for node in tree.body)

    wrapper_names = {
        "_normalize_hook",
        "_truncate_reference_text",
        "_select_references",
    }
    assert not any(
        isinstance(node, ast.FunctionDef) and node.name in wrapper_names
        for node in ast.walk(tree)
    )

    owner_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "llm_batch_score_core"
        and node.func.attr in wrapper_names
    ]
    assert {node.func.attr for node in owner_calls} == wrapper_names - {"_select_references"}
    assert len([node for node in owner_calls if node.func.attr == "_normalize_hook"]) == 2
    assert len([node for node in owner_calls if node.func.attr == "_truncate_reference_text"]) == 1


def test_core_module_has_no_forbidden_imports():
    source = Path(inspect.getfile(core)).read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {
        "provenance",
        "evaluation_contracts",
        "offline_evaluation",
        "quality_evaluation",
        "evaluation_metrics",
        "llm_client",
        "subprocess",
        "concurrent",
        "requests",
        "http",
        "yaml",
    }
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * node.level
            imported.append(prefix + (node.module or ""))

    normalized = {module.lstrip(".") for module in imported}
    assert all(
        not any(
            module == blocked or module.endswith("." + blocked)
            for blocked in forbidden
        )
        for module in normalized
    )
