"""MPV-02B 搜索索引生命周期与未就绪语义的定向合同测试。"""

from __future__ import annotations

import ast
import copy
import json
import pickle
import threading
from pathlib import Path

import numpy as np
import pytest

from xiaoshuo.api import shared
from xiaoshuo.api.models import IndexStats, SearchResponse
import xiaoshuo.pipeline.scene_search as scene_search_module
from xiaoshuo.pipeline.scene_search import (
    CorpusContractError,
    IndexNotReadyError,
    SceneSearch,
    _build_scene_metadata,
    _reported_corpus_chars,
    _split_scene_by_tokens,
)


class _DeterministicTokenizer:
    """按字符计数的确定性 tokenizer stub，不加载真实模型。"""

    model_max_length = 16

    def __call__(self, text, *, add_special_tokens, truncation):
        assert add_special_tokens is True
        assert truncation is False
        return {"input_ids": [101, *range(len(text)), 102]}


class _BatchEncodingLike:
    """模拟 transformers.BatchEncoding 的 mapping 接口。"""

    def __init__(self, input_ids):
        self._input_ids = input_ids

    def __contains__(self, key):
        return key == "input_ids"

    def __getitem__(self, key):
        if key != "input_ids":
            raise KeyError(key)
        return self._input_ids


def test_tokenizer_mapping_like_batch_encoding_is_supported() -> None:
    tokenizer = lambda *args, **kwargs: _BatchEncodingLike([101, 102])

    assert scene_search_module._token_count(tokenizer, "正文") == 2


def test_token_aware_split_preserves_text_and_respects_limit() -> None:
    tokenizer = _DeterministicTokenizer()
    source = "甲" * 10 + "\n\n" + "乙" * 10

    parts = _split_scene_by_tokens(source, tokenizer, token_max=8)

    assert len(parts) > 1
    assert "".join(part[0] for part in parts) == source
    assert all(part[1] <= 8 for part in parts)
    assert any(part[2] == "token_aware_character" for part in parts)


def test_metadata_validation_includes_token_split_contract() -> None:
    metadata = _build_scene_metadata(
        "测试书",
        1,
        2,
        "场景正文",
        {},
        parent_scene_index=2,
        sub_scene_index=1,
        token_count=7,
        split_reason="token_aware_character",
    )

    assert SceneSearch._valid_metadata_item(metadata)
    assert SceneSearch._valid_metadata_item(metadata, token_max=7)
    assert not SceneSearch._valid_metadata_item(metadata, token_max=6)
    metadata["token_count"] = True
    assert not SceneSearch._valid_metadata_item(metadata)


def test_missing_raw_body_is_structured_corpus_contract_failure() -> None:
    error = CorpusContractError("测试章节缺少 raw_body")

    assert error.code == "CORPUS_CONTRACT_INVALID"
    assert str(error).startswith("CORPUS_CONTRACT_INVALID:")


def test_collect_corpus_rejects_missing_raw_body(monkeypatch, tmp_path: Path) -> None:
    novel_path = tmp_path / "book.txt"
    rhythm_path = tmp_path / "rhythm.csv"
    novel_path.write_text("占位", encoding="utf-8")
    rhythm_path.write_text("ch_num\n1\n", encoding="utf-8")
    novel_index_path = tmp_path / "novel_index.json"
    novel_index_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(scene_search_module, "PROJECT_ROOT", tmp_path)
    engine = SceneSearch("测试题材")
    monkeypatch.setattr(scene_search_module, "_INDEX_PATH", novel_index_path)
    monkeypatch.setattr(
        scene_search_module,
        "_load_novel_index",
        lambda: {"genres": {"测试题材": {"novels": [{"file": "book.txt"}]}}},
    )
    monkeypatch.setattr(scene_search_module, "_novel_source_path", lambda *_: novel_path)
    monkeypatch.setattr(scene_search_module, "_rhythm_csv_path", lambda *_: rhythm_path)
    monkeypatch.setattr(scene_search_module, "_load_rhythm_data", lambda *_: {1: {}})
    monkeypatch.setattr(
        scene_search_module,
        "extract_chapters",
        lambda *_: [{"num": 1, "text": "截断字段"}],
    )

    with pytest.raises(CorpusContractError, match="CORPUS_CONTRACT_INVALID"):
        engine._collect_corpus(tokenizer=_DeterministicTokenizer())


def test_collect_corpus_keeps_full_body_and_reports_book_metrics(monkeypatch, tmp_path: Path) -> None:
    novel_path = tmp_path / "book.txt"
    rhythm_path = tmp_path / "rhythm.csv"
    novel_path.write_text("占位", encoding="utf-8")
    rhythm_path.write_text("ch_num\n1\n", encoding="utf-8")
    novel_index_path = tmp_path / "novel_index.json"
    novel_index_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(scene_search_module, "PROJECT_ROOT", tmp_path)
    tail_marker = "FULL_BODY_TAIL_MARKER"
    raw_body = "头" * 3200 + tail_marker
    engine = SceneSearch("测试题材")
    monkeypatch.setattr(scene_search_module, "_INDEX_PATH", novel_index_path)
    monkeypatch.setattr(
        scene_search_module,
        "_load_novel_index",
        lambda: {"genres": {"测试题材": {"novels": [{"file": "book.txt"}]}}},
    )
    monkeypatch.setattr(scene_search_module, "_novel_source_path", lambda *_: novel_path)
    monkeypatch.setattr(scene_search_module, "_rhythm_csv_path", lambda *_: rhythm_path)
    monkeypatch.setattr(scene_search_module, "_load_rhythm_data", lambda *_: {1: {}})
    monkeypatch.setattr(
        scene_search_module,
        "extract_chapters",
        lambda *_: [{"num": 1, "raw_body": raw_body, "text": raw_body[:3000]}],
    )

    scenes, _, _, books, _, _, book_reports = engine._collect_corpus(
        tokenizer=_DeterministicTokenizer()
    )

    assert tail_marker in "".join(scenes)
    assert books == 1
    assert book_reports == [{
        "book_name": "book",
        "indexed": True,
        "chapter_count": 1,
        "max_chapter_chars": len(raw_body),
        "total_chapter_chars": len(raw_body),
        "abnormal_chapter_count": 0,
    }]
    assert _reported_corpus_chars(book_reports) == len(raw_body)


def test_missing_index_returns_structured_not_ready(tmp_path: Path) -> None:
    engine = SceneSearch("测试题材")
    engine._cache = tmp_path / "scene_index"

    result = engine.search("避难所", top_k=5)

    assert result[0]["error"] == "INDEX_NOT_READY"
    assert "索引" in result[0]["message"]


def test_manifest_mismatch_fails_closed(tmp_path: Path) -> None:
    engine = SceneSearch("测试题材")
    engine._cache = tmp_path / "scene_index"
    engine._cache.mkdir()
    (engine._cache / "bm25_index.pkl").write_bytes(b"not-used")
    (engine._cache / "bge_embeddings.npy").write_bytes(b"not-used")
    (engine._cache / "metadata.json").write_text("[]", encoding="utf-8")
    (engine._cache / "manifest.json").write_text(
        json.dumps({"schema_version": -1}), encoding="utf-8"
    )

    result = engine.search("避难所", top_k=5)

    assert result[0]["error"] == "INDEX_NOT_READY"
    assert "manifest" in result[0]["message"]


def test_manifest_numeric_tampering_fails_closed(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(scene_search_module, "PROJECT_ROOT", tmp_path)
    engine = SceneSearch("测试题材")
    cache = tmp_path / "scene_index"
    cache.mkdir()
    novel_index_path = tmp_path / "novel_index.json"
    novel_index_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(scene_search_module, "_INDEX_PATH", novel_index_path)

    identity = {
        "model_id": "测试模型",
        "model_local_path": "D:/models/test",
        "model_config_sha256": "config-sha",
        "model_tokenizer_config_sha256": "tokenizer-sha",
        "model_weight_file": "model.safetensors",
        "model_weight_bytes": 1,
        "model_weight_sha256": "weight-sha",
    }
    tokenizer = _DeterministicTokenizer()
    monkeypatch.setattr(engine, "_model_identity", lambda: identity)
    monkeypatch.setattr(engine, "_tokenizer_contract", lambda: (tokenizer, 16))
    book_reports = [{
        "book_name": "测试书",
        "indexed": True,
        "chapter_count": 1,
        "max_chapter_chars": 2,
        "total_chapter_chars": 2,
        "abnormal_chapter_count": 0,
    }]
    metadata = [_build_scene_metadata("测试书", 1, 0, "正文", {})]
    source_entries = [("data/raw/test.txt", "source-sha")]
    monkeypatch.setattr(
        engine,
        "_collect_corpus",
        lambda limit=0, tokenizer=None: (
            ["正文"], metadata, source_entries, 1, 0, 0, book_reports
        ),
    )

    bm25 = scene_search_module.BM25Okapi([["正文"]])
    with (cache / "bm25_index.pkl").open("wb") as handle:
        pickle.dump({"bm25": bm25, "tokenized_corpus": [["正文"]]}, handle)
    np.save(str(cache / "bge_embeddings.npy"), np.zeros((1, 1), dtype=np.float32))
    (cache / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
    )
    base_manifest = {
        "schema_version": engine.manifest_schema_version,
        "genre": engine.genre,
        "embedding_model": identity["model_id"],
        "model_local_path": identity["model_local_path"],
        "model_config_sha256": identity["model_config_sha256"],
        "model_tokenizer_config_sha256": identity["model_tokenizer_config_sha256"],
        "model_weight_file": identity["model_weight_file"],
        "model_weight_bytes": identity["model_weight_bytes"],
        "model_weight_sha256": identity["model_weight_sha256"],
        "embedding_dim": 1,
        "method": engine.method,
        "offline": engine.offline,
        "min_scene_chars": engine.min_scene_chars,
        "max_scene_chars": engine.max_scene_chars,
        "merge_min_chars": scene_search_module._MERGE_MIN_CHARS,
        "rrf_k": engine.rrf_k,
        "build_scope": "full",
        "source_novel_index_sha256": scene_search_module._sha256_file(novel_index_path),
        "source_corpus_sha256": scene_search_module._digest_entries(source_entries),
        "build_limit": 0,
        "n_books": 1,
        "n_scenes": 1,
        "corpus_total_chars": 2,
        "tokenizer_max_length": 16,
        "token_max": engine.token_max,
        "truncate_strategy": "split_no_silent_truncate",
        "oversized_scene_count": 0,
        "sub_scene_count": 0,
        "book_reports": book_reports,
    }
    base_manifest["artifacts"] = {
        name: scene_search_module._sha256_file(cache / name)
        for name in ("bm25_index.pkl", "bge_embeddings.npy", "metadata.json")
    }

    candidates = []
    manifest_count_fields = (
        "build_limit", "n_books", "n_scenes", "corpus_total_chars",
        "oversized_scene_count", "sub_scene_count", "model_weight_bytes",
        "embedding_dim",
    )
    for field in manifest_count_fields:
        for invalid in (True, 1.0, -1):
            candidate = copy.deepcopy(base_manifest)
            candidate[field] = invalid
            candidates.append(candidate)
    report_count_fields = (
        "chapter_count", "max_chapter_chars", "total_chapter_chars",
        "abnormal_chapter_count",
    )
    for field in report_count_fields:
        for invalid in (True, 1.0, -1):
            candidate = copy.deepcopy(base_manifest)
            candidate["book_reports"][0][field] = invalid
            candidates.append(candidate)
    for candidate in candidates:
        (cache / "manifest.json").write_text(
            json.dumps(candidate, ensure_ascii=True), encoding="utf-8"
        )
        with pytest.raises(IndexNotReadyError):
            engine._load_cache_unlocked(expected_limit=0)


def test_get_engine_concurrent_creation_is_singleton(monkeypatch) -> None:
    monkeypatch.setattr(shared, "_search_engines", {})
    engines = []
    errors = []

    def worker() -> None:
        try:
            engines.append(shared.get_engine("并发测试"))
        except Exception as exc:  # pragma: no cover - 失败时保留原始异常
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert len({id(engine) for engine in engines}) == 1


def test_response_models_distinguish_index_not_ready() -> None:
    search = SearchResponse(
        query="测试",
        genre="末世",
        total_scenes=0,
        results=[],
        ready=False,
        index_not_ready="索引尚未建立",
    )
    stats = IndexStats(
        genre="末世",
        total_scenes=0,
        total_books=0,
        ready=False,
        index_not_ready="索引尚未建立",
    )

    assert search.ready is False
    assert stats.index_not_ready == "索引尚未建立"


def test_search_and_stats_routes_are_sync_functions() -> None:
    source = Path("src/xiaoshuo/api/routes/system.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {node.name: node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}

    assert isinstance(functions["search"], ast.FunctionDef)
    assert isinstance(functions["stats"], ast.FunctionDef)


def test_manifest_build_payload_contains_required_contract_fields() -> None:
    source = Path("src/xiaoshuo/pipeline/scene_search.py").read_text(encoding="utf-8")
    required = (
        "manifest_schema_version",
        "source_novel_index_sha256",
        "source_corpus_sha256",
        "corpus_total_chars",
        "build_scope",
        "tokenizer_max_length",
        "token_max",
        "truncate_strategy",
        "oversized_scene_count",
        "sub_scene_count",
        "book_reports",
        '"artifacts"',
    )

    assert all(field in source for field in required)


def test_corpus_uses_full_body_and_isolates_sample_scope() -> None:
    source = Path("src/xiaoshuo/pipeline/scene_search.py").read_text(encoding="utf-8")

    assert 'chapter.get("raw_body")' in source
    assert 'chapter.get("text", "")' not in source
    assert 'f"{self._formal_cache.name}.sample"' in source


def test_sample_and_full_builds_write_independent_artifacts(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(scene_search_module, "PROJECT_ROOT", tmp_path)
    engine = SceneSearch("测试题材")

    artifact_names = (
        "bm25_index.pkl", "bge_embeddings.npy", "metadata.json", "manifest.json"
    )

    def fake_build(force=False, limit=0):
        scope = "full" if limit == 0 else "sample"
        engine._cache.mkdir(parents=True, exist_ok=True)
        for name in artifact_names:
            (engine._cache / name).write_text(scope, encoding="utf-8")
        return 1

    monkeypatch.setattr(engine, "_build_index_unlocked", fake_build)

    engine.build_index(force=True, limit=0)
    formal_cache = engine._formal_cache
    engine.build_index(force=True, limit=1)
    sample_cache = engine._cache

    assert formal_cache != sample_cache
    assert formal_cache.name == "scene_index"
    assert sample_cache.name == "scene_index.sample"
    for name in artifact_names:
        assert (formal_cache / name).read_text(encoding="utf-8") == "full"
        assert (sample_cache / name).read_text(encoding="utf-8") == "sample"
