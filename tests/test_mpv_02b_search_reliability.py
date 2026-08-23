"""MPV-02B 搜索索引生命周期与未就绪语义的定向合同测试。"""

from __future__ import annotations

import ast
import json
import threading
from pathlib import Path

from xiaoshuo.api import shared
from xiaoshuo.api.models import IndexStats, SearchResponse
from xiaoshuo.pipeline.scene_search import SceneSearch


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
        '"artifacts"',
    )

    assert all(field in source for field in required)
