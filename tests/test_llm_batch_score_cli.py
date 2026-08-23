import ast
from pathlib import Path

import pytest

from xiaoshuo.pipeline import llm_batch_score_cli as cli


PROJECT_ROOT = Path(__file__).parents[1]
CLI_PATH = PROJECT_ROOT / "src" / "xiaoshuo" / "pipeline" / "llm_batch_score_cli.py"
FACADE_PATH = PROJECT_ROOT / "src" / "xiaoshuo" / "pipeline" / "llm_batch_score.py"


def _parse(path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _function(tree, name):
    matches = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    assert len(matches) == 1
    return matches[0]


def _calls(tree, name):
    return [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and ((isinstance(node.func, ast.Name) and node.func.id == name)
             or (isinstance(node.func, ast.Attribute) and node.func.attr == name))
    ]


def test_parse_cli_args_defaults_for_list_and_tuple():
    expected = {"book_filter": None, "max_ch": 30, "genre": "末世", "sc_samples": 1, "tier_boost": False}
    assert cli.parse_cli_args([]) == expected
    assert cli.parse_cli_args(()) == expected


def test_parse_cli_args_recognizes_all_options_and_unknown_tokens():
    assert cli.parse_cli_args([
        "noise", "--book", "Book-A", "--max", "12", "--genre", "末世",
        "--sc", "3", "--tier-boost", "ignored",
    ]) == {"book_filter": "Book-A", "max_ch": 12, "genre": "末世", "sc_samples": 3, "tier_boost": True}


def test_parse_cli_args_known_option_consumes_any_next_token_as_value():
    assert cli.parse_cli_args(["--book", "--foo", "--max", "-2", "--genre", "--bar", "--sc", "0"]) == {
        "book_filter": "--foo", "max_ch": -2, "genre": "--bar", "sc_samples": 0, "tier_boost": False
    }


def test_parse_cli_args_duplicate_last_value_wins_but_trailing_missing_value_does_not_clear():
    assert cli.parse_cli_args(["--book", "first", "--book", "second"]) == {
        "book_filter": "second", "max_ch": 30, "genre": "末世", "sc_samples": 1, "tier_boost": False
    }
    assert cli.parse_cli_args(["--max", "10", "--max"]) == {
        "book_filter": None, "max_ch": 10, "genre": "末世", "sc_samples": 1, "tier_boost": False
    }
    assert cli.parse_cli_args(["--tier-boost", "--tier-boost"]) == {
        "book_filter": None, "max_ch": 30, "genre": "末世", "sc_samples": 1, "tier_boost": True
    }


def test_parse_cli_args_negative_values_and_equals_unknown_token():
    assert cli.parse_cli_args(["--max", "-1", "--sc", "-3"]) == {
        "book_filter": None, "max_ch": -1, "genre": "末世", "sc_samples": -3, "tier_boost": False
    }
    assert cli.parse_cli_args(["--max=-1"]) == {
        "book_filter": None, "max_ch": 30, "genre": "末世", "sc_samples": 1, "tier_boost": False
    }


def test_parse_cli_args_illegal_int_is_natural_value_error():
    with pytest.raises(ValueError):
        cli.parse_cli_args(["--max", "bad"])
    with pytest.raises(ValueError):
        cli.parse_cli_args(["--sc", "bad"])


def test_parse_cli_args_requires_list_or_tuple_options_sequence():
    with pytest.raises(TypeError):
        cli.parse_cli_args(iter(["--book", "Book-A"]))


def test_select_book_sampling_truthiness_known_unknown_and_none():
    mapping = {"S": {"max_ch": 50, "sc_samples": 3}, "B": {"max_ch": 30, "sc_samples": 1}}
    before = {key: value.copy() for key, value in mapping.items()}
    assert cli.select_book_sampling(False, "book.txt", 30, 1, "S", mapping) == (30, 1)
    assert cli.select_book_sampling(True, "book.txt", 30, 1, "S", mapping) == (50, 3)
    assert cli.select_book_sampling(True, "book.txt", 30, 1, "unknown", mapping) == (30, 1)
    assert cli.select_book_sampling(True, "book.txt", 30, 1, None, mapping) == (30, 1)
    assert mapping == before


def test_select_book_sampling_preserves_natural_missing_key_and_unhashable_errors():
    with pytest.raises(KeyError):
        cli.select_book_sampling(True, "book.txt", 30, 1, "S", {"S": {"max_ch": 50}})
    with pytest.raises(TypeError):
        cli.select_book_sampling(True, "book.txt", 30, 1, ["S"], {"S": {"max_ch": 50, "sc_samples": 3}})


def test_new_cli_module_is_pure_and_has_exact_function_signatures():
    tree = _parse(CLI_PATH)
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in tree.body)
    assert [arg.arg for arg in _function(tree, "parse_cli_args").args.args] == ["argv"]
    assert [arg.arg for arg in _function(tree, "select_book_sampling").args.args] == [
        "tier_boost", "txt_file", "default_max_ch", "default_sc", "tier", "tier_sampling"
    ]
    source = CLI_PATH.read_text(encoding="utf-8")
    assert "argparse" not in source
    assert "help" not in source


def test_facade_cli_import_and_single_helper_call_sites():
    tree = _parse(FACADE_PATH)
    imports = [
        node for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "llm_batch_score_cli"
    ]
    assert len(imports) == 1
    assert imports[0].level == 1
    assert {(alias.name, alias.asname) for alias in imports[0].names} == {
        ("parse_cli_args", "_cli_parse_cli_args"),
        ("select_book_sampling", "_cli_select_book_sampling"),
    }
    main = _function(tree, "main")
    assert len(_calls(main, "_cli_parse_cli_args")) == 1
    assert len(_calls(main, "_cli_select_book_sampling")) == 1
    parse_call = _calls(main, "_cli_parse_cli_args")[0]
    assert len(parse_call.args) == 1
    assert isinstance(parse_call.args[0], ast.Subscript)
    assert isinstance(parse_call.args[0].value, ast.Attribute)
    assert isinstance(parse_call.args[0].value.value, ast.Name)
    assert parse_call.args[0].value.value.id == "sys"
    assert parse_call.args[0].value.attr == "argv"
    cli_reads = [
        node for node in ast.walk(main)
        if isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == "cli_args"
        and isinstance(node.slice, ast.Constant)
    ]
    assert {node.slice.value for node in cli_reads} == {
        "book_filter", "max_ch", "genre", "sc_samples", "tier_boost"
    }


def test_facade_main_gate_order_and_no_inline_parse_loop():
    tree = _parse(FACADE_PATH)
    main = _function(tree, "main")
    gate = next(node for node in main.body if isinstance(node, ast.If))
    assert any(isinstance(node, ast.Return) for node in ast.walk(gate))
    parse_call = _calls(main, "_cli_parse_cli_args")[0]
    assert gate.lineno < parse_call.lineno
    assert not any(
        isinstance(node, ast.For)
        and isinstance(node.iter, ast.Subscript)
        and isinstance(node.iter.value, ast.Attribute)
        and isinstance(node.iter.value.value, ast.Name)
        and node.iter.value.value.id == "sys"
        and node.iter.value.attr == "argv"
        for node in ast.walk(main)
    )


def test_facade_main_retains_index_glob_rhythm_logger_tier_batch_and_bootstrap_boundaries():
    tree = _parse(FACADE_PATH)
    main = _function(tree, "main")
    source = FACADE_PATH.read_text(encoding="utf-8")
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "glob"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "NOVELS_DIR"
        for node in ast.walk(main)
    )
    assert "INDEX_PATH" in source
    assert "json.load" in source
    assert "_rhythm_dir" in source
    assert "logger." in source
    assert "if __name__ == \"__main__\"" in source
    assert len(_calls(main, "_get_book_tier")) == 1
    assert len(_calls(main, "batch_book")) == 1
    batch_call = _calls(main, "batch_book")[0]
    assert [arg.id for arg in batch_call.args] == ["txt_path", "csv_path", "book_max_ch", "book_sc"]
    assert any(
        isinstance(node, ast.Try)
        and any(
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == "bootstrap_rank_stability"
            for child in ast.walk(node)
        )
        and node.handlers
        for node in ast.walk(main)
    )


def test_facade_tier_lookup_then_selection_then_batch_one_call_each():
    tree = _parse(FACADE_PATH)
    main = _function(tree, "main")
    tier_call = _calls(main, "_get_book_tier")[0]
    select_call = _calls(main, "_cli_select_book_sampling")[0]
    batch_call = _calls(main, "batch_book")[0]
    assert tier_call.lineno < select_call.lineno < batch_call.lineno
    tier_if = next(
        node for node in ast.walk(main)
        if isinstance(node, ast.If)
        and tier_call in ast.walk(node)
        and isinstance(node.test, ast.Name)
        and node.test.id == "tier_boost"
    )
    assert tier_if.lineno <= tier_call.lineno
    assert [arg.id for arg in select_call.args if isinstance(arg, ast.Name)] == [
        "tier_boost", "txt_file", "max_ch", "sc_samples", "tier", "_TIER_SAMPLING"
    ]
