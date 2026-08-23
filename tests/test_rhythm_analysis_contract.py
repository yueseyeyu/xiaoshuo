import ast
from pathlib import Path

from xiaoshuo.pipeline.rhythm.chapter_parser import extract_chapters_from_text
from xiaoshuo.pipeline.rhythm.book_analyzer import RuleOnlyAnalysisResult, RULE_ONLY_ANALYSIS_POLICY_VERSION


ROOT = Path(__file__).parents[1]
PARSER = ROOT / "src/xiaoshuo/pipeline/rhythm/chapter_parser.py"
ANALYZER = ROOT / "src/xiaoshuo/pipeline/rhythm/book_analyzer.py"


def _text():
    body = "这是用于规则分析的章节正文，包含足够长度的重复文字。" * 8
    return "\n".join(f"第{i}章 标题{i}\n{body}" for i in range(1, 4))


def test_extract_from_text_preserves_chapter_shape():
    rows = extract_chapters_from_text(_text())
    assert [row["num"] for row in rows] == [1, 2, 3]
    assert all(row["wc"] >= 50 for row in rows)
    assert all("raw_body" in row for row in rows)


def test_file_reader_reads_once_and_delegates_to_text_parser():
    tree = ast.parse(PARSER.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "extract_chapters")
    reads = [node for node in ast.walk(function) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "read_file_multi_encoding"]
    delegates = [node for node in ast.walk(function) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "extract_chapters_from_text"]
    assert len(reads) == 1
    assert len(delegates) == 1


def test_rule_only_analyzer_has_no_top_level_llm_or_writer_imports():
    tree = ast.parse(ANALYZER.read_text(encoding="utf-8"))
    forbidden = {"llm_client", "llm_verifier", "writing_instructions", "config_manager", "cache_manager"}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            assert node.module not in forbidden
        if isinstance(node, ast.Import):
            assert all(alias.name not in forbidden for alias in node.names)


def test_rule_only_result_contract():
    assert [field.name for field in RuleOnlyAnalysisResult.__dataclass_fields__.values()] == [
        "status", "book_id", "total_chaps", "total_words", "rows", "summary",
        "error_code", "analysis_policy_version",
    ]
    assert RULE_ONLY_ANALYSIS_POLICY_VERSION == "rule-only-v1"


def test_rule_only_import_has_no_llm_or_writer_side_effect():
    tree = ast.parse(ANALYZER.read_text(encoding="utf-8"))
    forbidden = {"llm_client", "llm_verifier", "writing_instructions", "config_manager", "cache_manager"}
    top_level = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert not any(
        (isinstance(node, ast.ImportFrom) and node.module in forbidden)
        or (isinstance(node, ast.Import) and any(alias.name in forbidden for alias in node.names))
        for node in top_level
    )


def test_text_parser_does_not_read_files():
    tree = ast.parse(PARSER.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "extract_chapters_from_text")
    assert not any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "read_file_multi_encoding"
        for node in ast.walk(function)
    )


def test_chapter_output_shape_is_preserved():
    rows = extract_chapters_from_text(_text())
    assert set(("num", "title", "text", "wc", "para_count", "raw_body")).issubset(rows[0])
