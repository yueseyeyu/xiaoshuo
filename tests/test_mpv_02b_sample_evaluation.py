"""MPV-02B 样本评测 Reader 的边界与共享查询核心测试。"""

from __future__ import annotations

import json
import numpy as np
import pytest

import xiaoshuo.pipeline.index_sample_evaluation as sample_module
import xiaoshuo.pipeline.scene_search as scene_search_module
from xiaoshuo.pipeline.scene_search import IndexNotReadyError, SceneSearch


class _FakeBM25:
    def get_scores(self, _query):
        return np.asarray([0.3, 0.8], dtype=np.float32)


def _loaded_engine() -> SceneSearch:
    engine = SceneSearch.__new__(SceneSearch)
    engine.top_k = 5
    engine.rrf_k = 60
    engine.token_max = 32
    engine._metadata = [
        {"book_name": "book", "chapter": 1, "scene_index": 0},
        {"book_name": "book", "chapter": 1, "scene_index": 1},
    ]
    engine._bm25 = _FakeBM25()
    engine._bge_embeddings = np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    engine._tokenizer_contract = lambda: (lambda *_args, **_kwargs: {"input_ids": [1]}, 32)
    engine._bge_encode = lambda *_args, **_kwargs: np.asarray([[0.0, 1.0]], dtype=np.float32)
    return engine


def test_shared_loaded_query_core_produces_ranked_results(monkeypatch) -> None:
    engine = _loaded_engine()
    monkeypatch.setattr(scene_search_module, "_jieba_tokenize", lambda text: [text])

    results = engine._search_loaded("测试", top_k=1)

    assert len(results) == 1
    assert results[0]["scene_index"] == 1
    assert results[0]["bm25_rank"] == 1
    assert results[0]["bge_rank"] == 1


def test_sample_reader_rejects_non_sample_output_path(monkeypatch) -> None:
    class _NeverConstructed:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("路径门禁应先于引擎构造")

    monkeypatch.setattr(sample_module, "SceneSearch", _NeverConstructed)
    with pytest.raises(IndexNotReadyError, match="scene_index.sample"):
        sample_module.SampleIndexReader(
            "末世",
            r"D:\tmp\yeyu-ai-a3\mpv-02b-worker\20260905-100544-000001\output\scene_index",
            r"D:\tmp\yeyu-ai-a3\mpv-02b-worker\20260905-100544-000001",
        )


def test_sample_reader_binds_completed_run_envelope(tmp_path) -> None:
    run_dir = tmp_path / "20260905-100544-000001"
    sample_cache = run_dir / "output" / "scene_index.sample"
    sample_cache.mkdir(parents=True)
    task_id = "sample-task"
    manifest = {
        "status": "COMPLETED",
        "task_id": task_id,
        "genre": "末世",
        "build_limit": 1,
        "cache_manifest_path": (sample_cache / "manifest.json").as_posix(),
        "events_path": run_dir.joinpath("events.jsonl").as_posix(),
    }
    report = {
        "status": "COMPLETED",
        "task_id": task_id,
        "error_code": None,
        "worker_exit_code": 0,
        "manifest_path": run_dir.joinpath("manifest.json").as_posix(),
        "events_path": manifest["events_path"],
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
    sample_module.SampleIndexReader("末世", sample_cache, run_dir)

    reader = sample_module.SampleIndexReader.__new__(sample_module.SampleIndexReader)
    reader.genre = "末世"
    reader.run_dir = run_dir
    reader.sample_cache = sample_cache
    manifest["cache_manifest_path"] = sample_cache.as_posix()
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(IndexNotReadyError, match="manifest 身份或状态不一致"):
        reader._validate_run_envelope()

    manifest["cache_manifest_path"] = (sample_cache / "wrong.json").as_posix()
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(IndexNotReadyError, match="manifest 身份或状态不一致"):
        reader._validate_run_envelope()


def test_sample_reader_rejects_reparse_top_level_artifacts(tmp_path, monkeypatch) -> None:
    run_dir = tmp_path / "20260905-100544-000003"
    sample_cache = run_dir / "output" / "scene_index.sample"
    sample_cache.mkdir(parents=True)
    reader = sample_module.SampleIndexReader.__new__(sample_module.SampleIndexReader)
    reader.genre = "末世"
    reader.run_dir = run_dir
    reader.sample_cache = sample_cache
    (run_dir / "manifest.json").write_text("{}", encoding="utf-8")
    (run_dir / "report.json").write_text("{}", encoding="utf-8")

    def _reject_manifest(path, root, label):
        if path.name == "manifest.json":
            raise IndexNotReadyError("样本 run manifest 路径包含 reparse point")

    monkeypatch.setattr(sample_module, "_reject_reparse_file", _reject_manifest)
    with pytest.raises(IndexNotReadyError, match="reparse point"):
        reader._validate_run_envelope()

    def _reject_report(path, root, label):
        if path.name == "report.json":
            raise IndexNotReadyError("样本 run report 路径包含 reparse point")

    monkeypatch.setattr(sample_module, "_reject_reparse_file", _reject_report)
    with pytest.raises(IndexNotReadyError, match="reparse point"):
        reader._validate_run_envelope()


def test_sample_reader_rejects_uncompleted_run_envelope(tmp_path) -> None:
    run_dir = tmp_path / "20260905-100544-000002"
    sample_cache = run_dir / "output" / "scene_index.sample"
    sample_cache.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps({
            "status": "FAILED",
            "task_id": "sample-task",
            "genre": "末世",
            "build_limit": 1,
            "cache_manifest_path": sample_cache.as_posix(),
            "events_path": run_dir.joinpath("events.jsonl").as_posix(),
        }),
        encoding="utf-8",
    )
    (run_dir / "report.json").write_text("{}", encoding="utf-8")
    reader = sample_module.SampleIndexReader.__new__(sample_module.SampleIndexReader)
    reader.genre = "末世"
    reader.run_dir = run_dir
    reader.sample_cache = sample_cache

    with pytest.raises(IndexNotReadyError, match="manifest 身份或状态不一致"):
        reader._validate_run_envelope()
