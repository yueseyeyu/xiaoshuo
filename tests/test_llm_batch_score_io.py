import ast
import csv
from pathlib import Path

import pytest

from xiaoshuo.pipeline import llm_batch_score_io as io


PROJECT_ROOT = Path(__file__).parents[1]
FACADE_PATH = PROJECT_ROOT / "src" / "xiaoshuo" / "pipeline" / "llm_batch_score.py"
IO_PATH = PROJECT_ROOT / "src" / "xiaoshuo" / "pipeline" / "llm_batch_score_io.py"

SCORE_FIELDS = [
    "ch_num", "wc",
    "llm_intensity", "llm_conflict", "llm_emotion", "llm_pace", "llm_hook", "llm_retention",
    "llm_low_confidence", "llm_confidence_note",
    "rule_intensity", "rule_hook", "rule_emotion", "rule_pace",
]

DECISION_FIELDS = [
    "chapter", "book", "llm_intensity", "llm_retention", "llm_conflict",
    "llm_emotion", "llm_pace", "llm_hook", "llm_low_confidence", "source",
]


def _parse(path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _function(tree, name):
    matches = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name]
    assert len(matches) == 1
    return matches[0]


def _calls(tree, name):
    return [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and ((isinstance(node.func, ast.Name) and node.func.id == name)
             or (isinstance(node.func, ast.Attribute) and node.func.attr == name))
    ]


def test_new_module_imports_are_exactly_csv_and_path():
    tree = _parse(IO_PATH)
    imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert len(imports) == 2
    assert isinstance(imports[0], ast.Import)
    assert [(alias.name, alias.asname) for alias in imports[0].names] == [("csv", None)]
    assert isinstance(imports[1], ast.ImportFrom)
    assert imports[1].module == "pathlib"
    assert imports[1].level == 0
    assert [(alias.name, alias.asname) for alias in imports[1].names] == [("Path", None)]


def test_load_rule_rows_uses_path_falsy_nonexistent_utf8_sig_int_and_duplicate(tmp_path):
    assert io.load_rule_rows(None) == {}
    assert io.load_rule_rows("") == {}
    assert io.load_rule_rows(tmp_path / "missing.csv") == {}

    path = tmp_path / "rules.csv"
    path.write_text("ch_num,emotion\n01,first\n1,last\n2,second\n", encoding="utf-8-sig")
    assert io.load_rule_rows(path) == {
        1: {"ch_num": "1", "emotion": "last"},
        2: {"ch_num": "2", "emotion": "second"},
    }


def test_load_rule_rows_preserves_natural_input_exceptions(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("emotion\nfirst\n", encoding="utf-8-sig")
    with pytest.raises(KeyError):
        io.load_rule_rows(path)

    path.write_text("ch_num,emotion\nnot-an-int,first\n", encoding="utf-8-sig")
    with pytest.raises(ValueError):
        io.load_rule_rows(path)


def test_load_rule_rows_accepts_str_and_pathlike_and_preserves_directory_empty_encoding_errors(tmp_path):
    path = tmp_path / "rules.csv"
    path.write_text("ch_num,emotion\n1,first\n", encoding="utf-8-sig")
    assert io.load_rule_rows(str(path)) == io.load_rule_rows(path)

    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8-sig")
    assert io.load_rule_rows(empty) == {}

    with pytest.raises(OSError) as exc_info:
        io.load_rule_rows(tmp_path)
    assert type(exc_info.value) in (PermissionError, IsADirectoryError)

    invalid = tmp_path / "invalid.csv"
    invalid.write_bytes(b"ch_num\n\xff\n")
    with pytest.raises(UnicodeDecodeError):
        io.load_rule_rows(invalid)


def test_load_already_scored_uses_path_falsy_nonexistent_int_and_set_semantics(tmp_path):
    assert io.load_already_scored(None) == set()
    assert io.load_already_scored("") == set()
    assert io.load_already_scored(tmp_path / "missing.csv") == set()

    path = tmp_path / "scores.csv"
    path.write_text("ch_num\n01\n1\n2\n", encoding="utf-8-sig")
    assert io.load_already_scored(path) == {1, 2}

    path.write_text("other\nvalue\n", encoding="utf-8-sig")
    assert io.load_already_scored(path) == {0}


def test_load_already_scored_preserves_natural_value_error(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("ch_num\nnot-an-int\n", encoding="utf-8-sig")
    with pytest.raises(ValueError):
        io.load_already_scored(path)


def test_load_already_scored_accepts_str_and_pathlike_and_preserves_directory_empty_encoding_errors(tmp_path):
    path = tmp_path / "scores.csv"
    path.write_text("ch_num\n1\n", encoding="utf-8-sig")
    assert io.load_already_scored(str(path)) == io.load_already_scored(path)

    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8-sig")
    assert io.load_already_scored(empty) == set()

    with pytest.raises(OSError) as exc_info:
        io.load_already_scored(tmp_path)
    assert type(exc_info.value) in (PermissionError, IsADirectoryError)

    invalid = tmp_path / "invalid.csv"
    invalid.write_bytes(b"ch_num\n\xff\n")
    with pytest.raises(UnicodeDecodeError):
        io.load_already_scored(invalid)


def test_build_score_row_has_fixed_fourteen_fields_and_does_not_mutate_inputs():
    rule = {"wc": "123", "pleasure_intensity": "4.5", "hook_type": "rise"}
    llm = {
        "intensity": "8.5", "conflict": "high", "emotion": "fear", "pace": "fast",
        "hook": "strong", "retention": "7.5", "low_confidence": True,
        "confidence_note": "chunk-range",
    }
    rule_before = rule.copy()
    llm_before = llm.copy()
    row = io.build_score_row(3, llm, rule, 99)
    assert list(row) == SCORE_FIELDS
    assert row == {
        "ch_num": 3, "wc": 123, "llm_intensity": 8.5, "llm_conflict": "high",
        "llm_emotion": "fear", "llm_pace": "fast", "llm_hook": "strong",
        "llm_retention": 7.5, "llm_low_confidence": True, "llm_confidence_note": "chunk-range",
        "rule_intensity": 4.5, "rule_hook": "rise", "rule_emotion": "日常", "rule_pace": "medium",
    }
    assert rule == rule_before
    assert llm == llm_before


def test_build_score_row_defaults_and_natural_exceptions():
    row = io.build_score_row(1, {"intensity": 1, "conflict": "c", "emotion": "e", "pace": "p", "hook": "h", "retention": 2}, {}, 7)
    assert row["wc"] == 7
    assert row["llm_low_confidence"] is False
    assert row["llm_confidence_note"] == ""
    assert row["rule_intensity"] == 0.0
    assert row["rule_hook"] == "none"
    assert row["rule_emotion"] == "日常"
    assert row["rule_pace"] == "medium"

    with pytest.raises(KeyError):
        io.build_score_row(1, {}, {}, 7)


def test_write_score_csv_is_initial_fourteen_column_utf8_sig_and_ignores_extras(tmp_path):
    path = tmp_path / "scores.csv"
    results = [{"ch_num": 1, "wc": 10, "llm_intensity": 8, "extra": "ignored", "llm_conflict": None}]
    io.write_score_csv(path, results)
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
        assert f"{rows[0]['ch_num']}" == "1"
        assert rows[0]["llm_conflict"] == ""
        assert list(rows[0]) == SCORE_FIELDS
    assert "extra" not in path.read_text(encoding="utf-8-sig")


def test_write_score_csv_empty_results_writes_only_header_and_does_not_create_parent(tmp_path):
    path = tmp_path / "not-created" / "scores.csv"
    with pytest.raises(FileNotFoundError):
        io.write_score_csv(path, [])
    assert not path.parent.exists()

    path.parent.mkdir()
    io.write_score_csv(path, [])
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        assert f.readline().rstrip("\r\n").split(",") == SCORE_FIELDS
        assert list(csv.DictReader(f)) == []


def test_build_decision_records_has_fixed_fields_defaults_and_no_input_mutation():
    rows = [{"ch_num": "2", "llm_intensity": "8.0", "llm_retention": "7.0", "llm_low_confidence": "True"}]
    before = [row.copy() for row in rows]
    records = io.build_decision_records(rows, "Book-A")
    assert list(records[0]) == DECISION_FIELDS
    assert records == [{
        "chapter": 2, "book": "Book-A", "llm_intensity": 8.0, "llm_retention": 7.0,
        "llm_conflict": "", "llm_emotion": "", "llm_pace": "", "llm_hook": "",
        "llm_low_confidence": True, "source": "qwen_llm_batch_score",
    }]
    assert rows == before


def test_build_decision_records_preserves_natural_conversion_exception():
    with pytest.raises(ValueError):
        io.build_decision_records([{"ch_num": "bad"}])


def test_merge_decision_records_later_wins_stable_key_sort_and_no_mutation():
    existing = [
        {"book": "B", "chapter": 2, "old": "keep"},
        {"book": "A", "chapter": 3, "old": "replace"},
    ]
    new_records = [
        {"book": "A", "chapter": 3, "new": "later"},
        {"book": "A", "chapter": 1, "new": "first"},
    ]
    existing_before = [row.copy() for row in existing]
    new_before = [row.copy() for row in new_records]
    merged = io.merge_decision_records(existing, new_records)
    assert merged == [
        {"book": "A", "chapter": 1, "new": "first"},
        {"book": "A", "chapter": 3, "new": "later"},
        {"book": "B", "chapter": 2, "old": "keep"},
    ]
    assert existing == existing_before
    assert new_records == new_before


def test_merge_decision_records_uses_get_defaults_for_missing_sort_fields():
    assert io.merge_decision_records([{"payload": "existing"}], [{"book": "", "chapter": 0, "payload": "new"}]) == [
        {"book": "", "chapter": 0, "payload": "new"}
    ]


def test_merge_existing_duplicate_later_entry_wins():
    existing = [
        {"book": "Book", "chapter": 1, "value": "first"},
        {"book": "Book", "chapter": 1, "value": "later"},
    ]
    assert io.merge_decision_records(existing, []) == [
        {"book": "Book", "chapter": 1, "value": "later"},
    ]


def test_merge_new_duplicate_later_entry_wins():
    new_records = [
        {"book": "Book", "chapter": 1, "value": "first"},
        {"book": "Book", "chapter": 1, "value": "later"},
    ]
    assert io.merge_decision_records([], new_records) == [
        {"book": "Book", "chapter": 1, "value": "later"},
    ]


def test_merge_empty_new_sorts_existing_by_book_then_chapter():
    existing = [
        {"book": "B", "chapter": 2},
        {"book": "A", "chapter": 3},
        {"book": "A", "chapter": 1},
    ]
    assert io.merge_decision_records(existing, []) == [
        {"book": "A", "chapter": 1},
        {"book": "A", "chapter": 3},
        {"book": "B", "chapter": 2},
    ]


def test_merge_mixed_sort_key_types_preserves_natural_type_error():
    with pytest.raises(TypeError):
        io.merge_decision_records(
            [{"book": "Book", "chapter": 1}, {"book": 2, "chapter": 1}],
            [],
        )


def test_facade_has_exact_io_imports_and_single_owner_call_sites():
    tree = _parse(FACADE_PATH)
    imports = [node for node in tree.body if isinstance(node, ast.ImportFrom) and node.module == "llm_batch_score_io"]
    assert len(imports) == 1
    assert imports[0].level == 1
    assert {(alias.name, alias.asname) for alias in imports[0].names} == {
        ("build_decision_records", "_io_build_decision_records"),
        ("build_score_row", "_io_build_score_row"),
        ("load_already_scored", "_io_load_already_scored"),
        ("load_rule_rows", "_io_load_rule_rows"),
        ("merge_decision_records", "_io_merge_decision_records"),
        ("write_score_csv", "_io_write_score_csv"),
    }
    assert len(_calls(tree, "_io_load_rule_rows")) == 1
    assert len(_calls(tree, "_io_load_already_scored")) == 1
    assert len(_calls(tree, "_io_write_score_csv")) == 1
    assert len(_calls(tree, "_io_build_decision_records")) == 1
    assert len(_calls(tree, "_io_merge_decision_records")) == 1
    assert len(_calls(tree, "_io_build_score_row")) == 1


def test_facade_build_score_row_call_is_inside_successful_result_loop():
    tree = _parse(FACADE_PATH)
    batch = _function(tree, "batch_book")
    call = _calls(batch, "_io_build_score_row")[0]
    loops = [node for node in ast.walk(batch) if isinstance(node, ast.For) and call in ast.walk(node)]
    assert len(loops) == 1
    result_loop = loops[0]
    filter_ifs = [
        node for node in result_loop.body
        if isinstance(node, ast.If)
        and any(isinstance(child, ast.Continue) for child in ast.walk(node))
    ]
    assert len(filter_ifs) == 1
    assert filter_ifs[0].lineno < call.lineno
    assert any(isinstance(node, ast.Return) and isinstance(node.value, ast.Constant) and node.value.value is None for node in ast.walk(batch))


def test_facade_io_call_order_and_no_residual_inline_owners():
    tree = _parse(FACADE_PATH)
    batch = _function(tree, "batch_book")
    export = _function(tree, "export_llm_scores_to_decisions")

    batch_calls = {
        name: _calls(batch, name)[0].lineno
        for name in (
            "_io_load_rule_rows", "_io_load_already_scored",
            "_io_build_score_row", "_io_write_score_csv",
        )
    }
    assert batch_calls["_io_load_rule_rows"] < batch_calls["_io_load_already_scored"]
    assert batch_calls["_io_load_already_scored"] < batch_calls["_io_build_score_row"]
    assert batch_calls["_io_build_score_row"] < batch_calls["_io_write_score_csv"]

    reader_calls = [
        node for node in ast.walk(batch)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "DictReader"
    ]
    assert all(node.lineno > batch_calls["_io_write_score_csv"] for node in reader_calls)
    assert not any(
        isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "rule_rows" for target in node.targets)
        and isinstance(node.value, (ast.Dict, ast.Set, ast.List))
        for node in ast.walk(batch)
    )
    assert not any(
        isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "row" for target in node.targets)
        and isinstance(node.value, ast.Dict)
        for node in ast.walk(batch)
    )

    build_call = _calls(export, "_io_build_decision_records")[0]
    merge_call = _calls(export, "_io_merge_decision_records")[0]
    assert build_call.lineno < merge_call.lineno
    assert not any(isinstance(node, ast.Name) and node.id == "existing_by_key" for node in ast.walk(export))
    assert not any(isinstance(node, ast.DictComp) for node in ast.walk(export))

    dict_writers = [
        node for node in ast.walk(batch)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "DictWriter"
    ]
    assert len(dict_writers) == 1
    assert dict_writers[0].lineno > batch_calls["_io_write_score_csv"]


def test_facade_build_score_row_signature_and_exact_argument_order():
    io_tree = _parse(IO_PATH)
    signature = _function(io_tree, "build_score_row").args
    assert [arg.arg for arg in signature.args] == ["ch_num", "llm", "rule", "ch_wc"]

    facade_tree = _parse(FACADE_PATH)
    call = _calls(facade_tree, "_io_build_score_row")[0]
    assert [arg.id for arg in call.args] == ["ch_num", "llm", "rule", "ch_wc"]


def test_facade_retains_side_effect_and_downstream_boundaries():
    source = FACADE_PATH.read_text(encoding="utf-8")
    tree = _parse(FACADE_PATH)
    batch = _function(tree, "batch_book")
    export = _function(tree, "export_llm_scores_to_decisions")
    assert any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "mkdir" for node in ast.walk(batch))
    assert "_meta_path" in source
    assert "batch_pairwise_scoring" in source
    assert "apply_golden_set_calibration" in source
    assert "export_llm_scores_to_decisions" in source
    assert "update_bma_weights_online" in source
    assert "def main" in source
    assert any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "DictWriter" for node in ast.walk(batch))
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "json"
        and node.func.attr == "dump"
        for node in ast.walk(export)
    )


def test_facade_returns_none_for_empty_new_decisions_before_merge():
    tree = _parse(FACADE_PATH)
    export = _function(tree, "export_llm_scores_to_decisions")
    returns = [node for node in ast.walk(export) if isinstance(node, ast.Return)]
    assert any(isinstance(node.value, ast.Constant) and node.value.value is None for node in returns)
    merge_call = _calls(export, "_io_merge_decision_records")
    assert len(merge_call) == 1
    none_return = next(node for node in returns if isinstance(node.value, ast.Constant) and node.value.value is None)
    assert none_return.lineno < merge_call[0].lineno


def test_facade_retains_second_pairwise_writer_and_output_paths():
    tree = _parse(FACADE_PATH)
    source = FACADE_PATH.read_text(encoding="utf-8")
    assert "_scoring_metadata.json" in source
    assert "all_llm_scores.json" in source
    assert "utf-8-sig" in source
    assert "DictWriter" in source
    assert "chapter_decisions" in source
    assert len(_calls(_function(tree, "batch_book"), "DictWriter")) == 1
