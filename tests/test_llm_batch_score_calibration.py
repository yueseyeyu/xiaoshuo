"""Direct pure-helper and static facade tests for calibration split."""

import ast
import statistics
from pathlib import Path

from xiaoshuo.pipeline import llm_batch_score_calibration as calibration


ROOT = Path(__file__).resolve().parents[1]
CALIBRATION_PATH = ROOT / "src" / "xiaoshuo" / "pipeline" / "llm_batch_score_calibration.py"
FACADE_PATH = ROOT / "src" / "xiaoshuo" / "pipeline" / "llm_batch_score.py"


def _top_level_function(tree, name):
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
    assert len(functions) == 1
    return functions[0]


def _call_nodes(tree, name, attr=None):
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if attr is None and isinstance(node.func, ast.Name) and node.func.id == name:
            calls.append(node)
        if attr is not None and isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and node.func.value.id == name and node.func.attr == attr:
                calls.append(node)
    return calls


def _call_count(tree, name):
    return len(_call_nodes(tree, name))


def _keyword(call, name):
    matches = [keyword.value for keyword in call.keywords if keyword.arg == name]
    assert len(matches) == 1
    return matches[0]


def test_build_calibration_plan_independent_oracles_and_boundaries():
    plan = calibration.build_calibration_plan(
        [(1.0, 3.0), (2.0, 4.0), (4.0, 5.0)],
        [(1.0, 1.0), (4.0, 5.0), (8.0, 8.0)],
    )
    assert plan == {
        "intensity_offset": 2.0,
        "retention_offset": 0.0,
        "n_golden": 3,
        "shrinkage": 0.4,
        "intensity_skip": False,
        "retention_skip": True,
        "method": "median_offset_shrinkage",
        "skipped": False,
        "wls_params": None,
    }

    large = calibration.build_calibration_plan(
        [(1.0, 2.0)] * 20,
        [(1.0, 1.0)] * 20,
    )
    assert large["n_golden"] == 20
    assert large["shrinkage"] == 0.6
    assert large["intensity_skip"] is False
    assert large["retention_skip"] is True

    smart_skip = calibration.build_calibration_plan(
        [(1.0, 1.2), (2.0, 2.1), (3.0, 3.0)],
        [(1.0, 1.0), (2.0, 2.2), (3.0, 3.1)],
    )
    assert smart_skip == {
        "intensity_offset": 0.1,
        "retention_offset": 0.1,
        "n_golden": 3,
        "shrinkage": 0.4,
        "intensity_skip": True,
        "retention_skip": True,
        "method": "smart_skip",
        "skipped": True,
        "wls_params": None,
    }

    wls = {"intensity": {"intercept": 1.0, "slope": 0.5}, "retention": {"intercept": 2.0, "slope": 0.4}}
    wls_plan = calibration.build_calibration_plan([(1.0, 2.0)], [(1.0, 2.0)], wls)
    assert wls_plan["method"] == "wls"
    assert wls_plan["skipped"] is False
    assert wls_plan["wls_params"] is wls

    one_dim_skip_wls = calibration.build_calibration_plan(
        [(1.0, 1.4), (2.0, 2.4), (3.0, 3.4)],
        [(1.0, 2.0), (2.0, 3.0), (3.0, 4.0)],
        {"intensity": {"intercept": 2.0, "slope": 1.0}, "retention": {"intercept": 0.0, "slope": 0.5}},
    )
    assert one_dim_skip_wls["intensity_skip"] is True
    assert one_dim_skip_wls["retention_skip"] is False
    assert one_dim_skip_wls["method"] == "wls"
    assert one_dim_skip_wls["skipped"] is False


def test_apply_calibration_values_uses_fixed_wls_and_shrinkage_oracles():
    fallback_plan = {
        "intensity_offset": 2.0,
        "retention_offset": 0.0,
        "shrinkage": 0.4,
        "intensity_skip": False,
        "retention_skip": True,
        "skipped": False,
        "wls_params": None,
    }
    assert calibration.apply_calibration_values(9.5, 4.0, fallback_plan) == (10.0, 4.0)

    wls_plan = {
        "intensity_offset": 0.0,
        "retention_offset": 0.0,
        "shrinkage": 0.4,
        "intensity_skip": True,
        "retention_skip": True,
        "skipped": False,
        "wls_params": {
            "intensity": {"intercept": 2.0, "slope": 1.0},
            "retention": {"intercept": 0.0, "slope": 0.5},
        },
    }
    assert calibration.apply_calibration_values(8.0, 1.0, wls_plan) == (10.0, 1.0)

    mixed_wls_plan = {
        "intensity_offset": 0.2,
        "retention_offset": 1.0,
        "shrinkage": 0.4,
        "intensity_skip": True,
        "retention_skip": False,
        "skipped": False,
        "wls_params": {
            "intensity": {"intercept": 1.0, "slope": 0.5},
            "retention": {"intercept": 0.25, "slope": 0.3333333333},
        },
    }
    assert calibration.apply_calibration_values(8.75, 1.234, mixed_wls_plan) == (5.4, 1.0)

    double_skip_wls_plan = {
        "intensity_offset": 0.1,
        "retention_offset": -0.1,
        "shrinkage": 0.4,
        "intensity_skip": True,
        "retention_skip": True,
        "skipped": True,
        "wls_params": {
            "intensity": {"intercept": 100.0, "slope": 100.0},
            "retention": {"intercept": 100.0, "slope": 100.0},
        },
    }
    assert calibration.apply_calibration_values(8.75, 1.234, double_skip_wls_plan) == (8.75, 1.234)


def test_bootstrap_rank_analysis_n4_independent_oracle():
    books = {"A": [1.0, 2.0, 3.0], "B": [4.0, 5.0, 6.0], "C": [7.0, 8.0, 9.0]}
    assert calibration.bootstrap_rank_analysis(books, n_bootstrap=4) == [
        {"book": "C", "n_chapters": 3, "mean_intensity": 8.0, "mean_ci_95": [7.33, 8.33], "rank_median": 1, "rank_ci_95": [1, 1], "stability": "stable"},
        {"book": "B", "n_chapters": 3, "mean_intensity": 5.0, "mean_ci_95": [4.67, 5.33], "rank_median": 2, "rank_ci_95": [2, 2], "stability": "stable"},
        {"book": "A", "n_chapters": 3, "mean_intensity": 2.0, "mean_ci_95": [1.0, 3.0], "rank_median": 3, "rank_ci_95": [3, 3], "stability": "stable"},
    ]


def test_bootstrap_rank_analysis_fixed_six_book_oracle():
    books = {name: [1.0, 10.0] for name in ["book-1", "book-2", "book-3", "book-4", "book-5", "book-6"]}
    assert calibration.bootstrap_rank_analysis(books, n_bootstrap=20) == [
        {"book": "book-1", "n_chapters": 2, "mean_intensity": 5.5, "mean_ci_95": [1.0, 10.0], "rank_median": 2, "rank_ci_95": [1, 6], "stability": "unstable"},
        {"book": "book-2", "n_chapters": 2, "mean_intensity": 5.5, "mean_ci_95": [1.0, 10.0], "rank_median": 2, "rank_ci_95": [1, 6], "stability": "unstable"},
        {"book": "book-3", "n_chapters": 2, "mean_intensity": 5.5, "mean_ci_95": [1.0, 10.0], "rank_median": 3, "rank_ci_95": [1, 6], "stability": "unstable"},
        {"book": "book-4", "n_chapters": 2, "mean_intensity": 5.5, "mean_ci_95": [1.0, 10.0], "rank_median": 4, "rank_ci_95": [1, 6], "stability": "unstable"},
        {"book": "book-5", "n_chapters": 2, "mean_intensity": 5.5, "mean_ci_95": [1.0, 10.0], "rank_median": 4, "rank_ci_95": [1, 6], "stability": "unstable"},
        {"book": "book-6", "n_chapters": 2, "mean_intensity": 5.5, "mean_ci_95": [1.0, 10.0], "rank_median": 5, "rank_ci_95": [2, 6], "stability": "unstable"},
    ]


def test_bootstrap_rank_analysis_fixed_eight_book_oracle():
    books = {name: [1.0, 10.0] for name in ["book-1", "book-2", "book-3", "book-4", "book-5", "book-6", "book-7", "book-8"]}
    assert calibration.bootstrap_rank_analysis(books, n_bootstrap=20) == [
        {"book": "book-1", "n_chapters": 2, "mean_intensity": 5.5, "mean_ci_95": [1.0, 10.0], "rank_median": 3, "rank_ci_95": [1, 7], "stability": "volatile"},
        {"book": "book-2", "n_chapters": 2, "mean_intensity": 5.5, "mean_ci_95": [1.0, 10.0], "rank_median": 3, "rank_ci_95": [1, 8], "stability": "volatile"},
        {"book": "book-3", "n_chapters": 2, "mean_intensity": 5.5, "mean_ci_95": [1.0, 10.0], "rank_median": 4, "rank_ci_95": [1, 7], "stability": "volatile"},
        {"book": "book-4", "n_chapters": 2, "mean_intensity": 5.5, "mean_ci_95": [1.0, 10.0], "rank_median": 4, "rank_ci_95": [1, 8], "stability": "volatile"},
        {"book": "book-5", "n_chapters": 2, "mean_intensity": 5.5, "mean_ci_95": [1.0, 10.0], "rank_median": 4, "rank_ci_95": [2, 7], "stability": "unstable"},
        {"book": "book-6", "n_chapters": 2, "mean_intensity": 5.5, "mean_ci_95": [1.0, 10.0], "rank_median": 6, "rank_ci_95": [1, 8], "stability": "volatile"},
        {"book": "book-7", "n_chapters": 2, "mean_intensity": 5.5, "mean_ci_95": [1.0, 10.0], "rank_median": 6, "rank_ci_95": [1, 8], "stability": "volatile"},
        {"book": "book-8", "n_chapters": 2, "mean_intensity": 5.5, "mean_ci_95": [1.0, 10.0], "rank_median": 6, "rank_ci_95": [2, 8], "stability": "volatile"},
    ]


def test_bootstrap_rank_analysis_preserves_constant_and_tie_oracles():
    books = {"low": [1.0] * 5, "high": [9.0] * 5}
    assert calibration.bootstrap_rank_analysis(books, n_bootstrap=2) == [
        {"book": "high", "n_chapters": 5, "mean_intensity": 9.0, "mean_ci_95": [9.0, 9.0], "rank_median": 1, "rank_ci_95": [1, 1], "stability": "stable"},
        {"book": "low", "n_chapters": 5, "mean_intensity": 1.0, "mean_ci_95": [1.0, 1.0], "rank_median": 2, "rank_ci_95": [2, 2], "stability": "stable"},
    ]

    ties = {"first": [5.0] * 5, "second": [5.0] * 5}
    tied = calibration.bootstrap_rank_analysis(ties, n_bootstrap=2)
    assert [row["book"] for row in tied] == ["first", "second"]
    assert [row["rank_median"] for row in tied] == [1, 2]


def test_pure_helpers_preserve_natural_exception_behavior():
    for n_bootstrap in (0, -1):
        try:
            calibration.bootstrap_rank_analysis({"A": [1.0, 10.0], "B": [1.0, 10.0]}, n_bootstrap=n_bootstrap)
        except IndexError:
            pass
        else:
            raise AssertionError("empty bootstrap collection must retain IndexError")

    try:
        calibration.bootstrap_rank_analysis({"A": [1.0, 10.0], "B": [1.0, 10.0]}, n_bootstrap=1.5)
    except TypeError:
        pass
    else:
        raise AssertionError("non-integral bootstrap count must retain TypeError")

    try:
        calibration.build_calibration_plan([], [])
    except Exception as exc:
        assert type(exc).__name__ == "StatisticsError"
    else:
        raise AssertionError("empty calibration pairs must retain statistics.median failure")

    try:
        calibration.build_calibration_plan([(1.0, 2.0)], None)
    except TypeError:
        pass
    else:
        raise AssertionError("missing retention pairs must remain TypeError")

    try:
        calibration.bootstrap_rank_analysis({"empty": []}, n_bootstrap=1)
    except statistics.StatisticsError:
        pass
    else:
        raise AssertionError("empty score lists must retain natural random.choice failure")


def test_calibration_module_import_rules_are_static_and_narrow():
    tree = ast.parse(CALIBRATION_PATH.read_text(encoding="utf-8"))
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in tree.body)
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    allowed = {
        "build_calibration_plan": {"statistics"},
        "apply_calibration_values": set(),
        "bootstrap_rank_analysis": {"random", "statistics"},
    }
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        assert isinstance(node, ast.Import)
        assert len(node.names) == 1
        assert node.names[0].asname is None
        owner = parents[node]
        while not isinstance(owner, ast.FunctionDef):
            owner = parents[owner]
        assert node.names[0].name in allowed[owner.name]
    observed = {name: set() for name in allowed}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Import):
            continue
        owner = parents[node]
        while not isinstance(owner, ast.FunctionDef):
            owner = parents[owner]
        observed[owner.name].add(node.names[0].name)
    assert observed == allowed


def test_facade_calibration_function_contracts_are_static():
    tree = ast.parse(FACADE_PATH.read_text(encoding="utf-8"))
    imports = [
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.level == 1
        and node.module == "llm_batch_score_calibration"
    ]
    assert len(imports) == 1
    assert {(alias.name, alias.asname) for alias in imports[0].names} == {
        ("apply_calibration_values", "_calibration_apply_values"),
        ("bootstrap_rank_analysis", "_calibration_bootstrap_rank_analysis"),
        ("build_calibration_plan", "_calibration_build_plan"),
    }

    apply_fn = _top_level_function(tree, "apply_golden_set_calibration")
    assert [arg.arg for arg in apply_fn.args.args] == ["csv_path", "golden_set_path"]
    assert len(apply_fn.args.defaults) == 1
    assert isinstance(apply_fn.args.defaults[0], ast.Constant)
    assert apply_fn.args.defaults[0].value is None

    bootstrap_fn = _top_level_function(tree, "bootstrap_rank_stability")
    assert [arg.arg for arg in bootstrap_fn.args.args] == ["genre", "n_bootstrap"]
    assert [default.value for default in bootstrap_fn.args.defaults] == ["末世", 1000]
    assert _top_level_function(tree, "main").name == "main"

    source = FACADE_PATH.read_text(encoding="utf-8")
    for required in (
        "_build_quantile_map",
        "_apply_quantile_map",
        "_golden_set_path_fn",
        "_ols_path",
        "_wls_path",
        "wls_params = None",
        "fallback to median offset",
        "_book_match",
        "golden_for_book",
        "encoding=\"utf-8-sig\"",
        "csv.DictReader",
        "csv.DictWriter",
        "fieldnames",
        "extrasaction='ignore'",
        "_llm_dir(genre)",
        "glob(\"*_llm.csv\")",
        "len(scores) >= 5",
        "continue",
        "len(books) < 2",
        "return None",
        "json.dump",
        "logger.info",
        "Path(",
        "if __name__ == \"__main__\"",
    ):
        assert required in source

    assert _call_count(apply_fn, "_calibration_build_plan") == 1
    assert _call_count(apply_fn, "_calibration_apply_values") == 1
    assert _call_count(bootstrap_fn, "_calibration_bootstrap_rank_analysis") == 1

    plan_skip_ifs = [
        node
        for node in ast.walk(apply_fn)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Subscript)
        and isinstance(node.test.value, ast.Name)
        and node.test.value.id == "plan"
        and isinstance(node.test.slice, ast.Constant)
        and node.test.slice.value == "skipped"
    ]
    assert len(plan_skip_ifs) == 1
    skip_if = plan_skip_ifs[0]
    skip_returns = [node for node in ast.walk(skip_if) if isinstance(node, ast.Return)]
    assert len(skip_returns) == 1
    skip_return_line = skip_returns[0].lineno
    post_skip_readers = [
        node.lineno
        for node in _call_nodes(apply_fn, "csv", "DictReader")
        if node.lineno > skip_return_line
    ]
    post_skip_writers = [
        node.lineno
        for node in _call_nodes(apply_fn, "csv", "DictWriter")
        if node.lineno > skip_return_line
    ]
    assert post_skip_readers
    assert post_skip_writers
    assert skip_return_line < min(post_skip_readers + post_skip_writers)

    csv_readers = _call_nodes(apply_fn, "csv", "DictReader")
    assert len(csv_readers) >= 2
    csv_writers = _call_nodes(apply_fn, "csv", "DictWriter")
    assert csv_writers
    writer = csv_writers[-1]
    fieldnames_keywords = [keyword.value for keyword in writer.keywords if keyword.arg == "fieldnames"]
    assert len(fieldnames_keywords) == 1
    assert isinstance(fieldnames_keywords[0], ast.Name)
    assert fieldnames_keywords[0].id == "fieldnames"
    assert isinstance(_keyword(writer, "extrasaction"), ast.Constant)
    assert _keyword(writer, "extrasaction").value == "ignore"

    open_calls = _call_nodes(apply_fn, "open")
    assert any(
        any(isinstance(keyword.value, ast.Constant) and keyword.value.value == "utf-8-sig" for keyword in call.keywords if keyword.arg == "encoding")
        for call in open_calls
    )
    assert any(isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "fieldnames" for target in node.targets) for node in ast.walk(apply_fn))

    bootstrap_calls = _call_nodes(bootstrap_fn, "_calibration_bootstrap_rank_analysis")
    assert len(bootstrap_calls) == 1
    assert [arg.id for arg in bootstrap_calls[0].args if isinstance(arg, ast.Name)] == ["books", "n_bootstrap"]
    assert _call_nodes(bootstrap_fn, "json", "dump")
    assert _call_nodes(bootstrap_fn, "logger", "info")


def test_calibration_tests_do_not_import_legacy_facade():
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    assert not any(
        isinstance(node, ast.ImportFrom)
        and node.module == "xiaoshuo.pipeline"
        and any(alias.name == "llm_batch_score" for alias in node.names)
        for node in tree.body
    )
