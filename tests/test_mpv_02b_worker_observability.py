"""MPV-02B B 批次 worker、事件、取消和发布保护定向测试。"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest

import xiaoshuo.pipeline.scene_search as scene_search_module
import xiaoshuo.pipeline.index_build_events as events_module
import xiaoshuo.pipeline.index_build_persistence as persistence_module
import xiaoshuo.pipeline.index_build_worker as worker_module
from xiaoshuo.pipeline.index_build_finalization import (
    CleanupEventType,
    CleanupOutcome,
    FinalizationDecision,
    ExecutionOutcome,
    PersistenceOutcome,
    PersistenceStatus,
    RunStatus,
    cleanup_event_type,
    decide_finalization,
    normalize_execution_outcome,
    persistence_failure,
)
from xiaoshuo.pipeline.index_build_events import (
    EventContractError,
    EventWriter,
    read_events,
    read_failure,
    read_report,
)
from xiaoshuo.pipeline.index_build_worker import (
    EXIT_CODES,
    IndexBuildTaskSnapshot,
    WorkerSession,
    WorkerStop,
)


def _snapshot(run_dir: Path, **limits) -> IndexBuildTaskSnapshot:
    return IndexBuildTaskSnapshot(
        task_id="20260825-000001-000001",
        genre="测试题材",
        force=True,
        limit=1,
        run_dir=str(run_dir),
        cache_dir=str(run_dir / "output" / "scene_index.sample"),
        model_local_path=str(run_dir / "model"),
        resource_limits=limits,
        cancel_flag=str(run_dir / "cancel.flag"),
    )


def test_finalization_policy_is_pure_and_preserves_original_failure() -> None:
    exit_codes = {
        "COMPLETED": 0, "WORKER_FAILED": 8, "MODEL_ERROR": 5,
        "REPORT_WRITE_FAILED": 10,
    }
    outcome = normalize_execution_outcome(
        "FAILED", "MODEL_ERROR", 5, "cleanup 失败", exit_codes
    )
    assert outcome == ExecutionOutcome(RunStatus.FAILED, "MODEL_ERROR", 5, "cleanup 失败")
    persistence = persistence_failure(outcome, "report 写入失败", exit_codes)
    assert persistence.original_error_code == "MODEL_ERROR"
    assert persistence.original_exit_code == 5


def test_finalization_policy_downgrades_only_success_on_cleanup_failure() -> None:
    exit_codes = {"COMPLETED": 0, "WORKER_FAILED": 8, "REPORT_WRITE_FAILED": 10}
    outcome = normalize_execution_outcome(
        "COMPLETED", None, 0, "清理失败", exit_codes
    )
    assert outcome.status is RunStatus.FAILED
    assert outcome.error_code == "WORKER_FAILED"
    assert cleanup_event_type(outcome.status) is CleanupEventType.FAILED


def test_finalization_decision_separates_cleanup_and_persistence() -> None:
    exit_codes = {"COMPLETED": 0, "WORKER_FAILED": 8, "REPORT_WRITE_FAILED": 10}
    decision = decide_finalization(
        ExecutionOutcome(RunStatus.COMPLETED, None, 0),
        CleanupOutcome(),
        PersistenceOutcome(
            persistence_status=PersistenceStatus.FAILED,
            status=RunStatus.FAILED,
            error_code="REPORT_WRITE_FAILED",
            exit_code=10,
            original_error_code="COMPLETED",
            original_exit_code=0,
            error_text="manifest 写入失败",
        ),
        exit_codes,
    )
    assert isinstance(decision, FinalizationDecision)
    assert decision.status is RunStatus.FAILED
    assert decision.original_error_code == "COMPLETED"
    assert decision.cleanup_event_type is CleanupEventType.COMPLETED


def test_finalization_rejects_inconsistent_persistence_reference() -> None:
    exit_codes = {
        "COMPLETED": 0, "WORKER_FAILED": 8, "MODEL_ERROR": 5,
        "REPORT_WRITE_FAILED": 10,
    }
    with pytest.raises(ValueError, match="原始退出码不一致"):
        decide_finalization(
            ExecutionOutcome(RunStatus.COMPLETED, None, 0),
            CleanupOutcome(),
            PersistenceOutcome(
                persistence_status=PersistenceStatus.FAILED,
                status=RunStatus.FAILED,
                error_code="REPORT_WRITE_FAILED",
                exit_code=10,
                original_error_code="COMPLETED",
                original_exit_code=8,
                error_text="manifest 写入失败",
            ),
            exit_codes,
        )

    with pytest.raises(ValueError, match="未引用当前业务结果"):
        decide_finalization(
            ExecutionOutcome(RunStatus.COMPLETED, None, 0),
            CleanupOutcome(),
            PersistenceOutcome(
                persistence_status=PersistenceStatus.FAILED,
                status=RunStatus.FAILED,
                error_code="REPORT_WRITE_FAILED",
                exit_code=10,
                original_error_code="MODEL_ERROR",
                original_exit_code=5,
                error_text="report 写入失败",
            ),
            exit_codes,
        )


def test_event_writer_syncs_periodically_and_always_on_terminal_event(
    tmp_path: Path, monkeypatch
) -> None:
    stage = tmp_path / "stage"
    stage.mkdir()
    monkeypatch.setattr(events_module, "EVENT_STAGE_ROOT", stage)
    run_dir = stage / "20260825-000001-000001"
    run_dir.mkdir()
    writer = EventWriter(run_dir, "task-1")
    fsync_calls = []
    monkeypatch.setattr(events_module.os, "fsync", lambda fd: fsync_calls.append(fd))
    for index in range(1, events_module.EVENT_FSYNC_EVERY + 1):
        writer.write_event("collect", "progress", n_done=index, n_total=100)
    writer.write_event("cleanup", "completed")
    assert len(fsync_calls) == 2
    assert len(writer.validate_events()) == events_module.EVENT_FSYNC_EVERY + 1


def test_event_writer_reopens_terminal_history_as_sealed(tmp_path: Path, monkeypatch) -> None:
    stage = tmp_path / "stage"
    stage.mkdir()
    monkeypatch.setattr(events_module, "EVENT_STAGE_ROOT", stage)
    run_dir = stage / "20260825-000001-000001"
    run_dir.mkdir()
    writer = EventWriter(run_dir, "task-1")
    writer.write_event("preflight", "started")
    writer.write_event("cleanup", "completed")
    writer.close()

    reopened = EventWriter(run_dir, "task-1")
    with pytest.raises(EventContractError, match="终态事件已写入"):
        reopened.write_event("collect", "progress")
    reopened.close()


def test_cleanup_terminal_callback_is_not_written_by_worker_session(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(events_module, "EVENT_STAGE_ROOT", tmp_path)
    run_dir = tmp_path / "20260825-000001-000001"
    run_dir.mkdir()
    writer = EventWriter(run_dir, "task-1")
    session = WorkerSession(_snapshot(run_dir), writer)
    calls = []
    monkeypatch.setattr(writer, "write_event", lambda *args, **kwargs: calls.append(args))

    session.on_progress("cleanup", 1, 1)

    assert calls == []
    assert session.cleanup_errors == []
    writer.close()


def test_event_writer_round_trip_has_fixed_schema(tmp_path: Path, monkeypatch) -> None:
    stage = tmp_path / "stage"
    stage.mkdir()
    monkeypatch.setattr(events_module, "EVENT_STAGE_ROOT", stage)
    run_dir = stage / "20260825-000001-000001"
    run_dir.mkdir()
    writer = EventWriter(run_dir, "task-1")
    writer.write_event("collect", "started", n_total=5, message="开始")
    writer.write_event("collect", "completed", n_done=5, n_total=5)
    writer.write_event("cleanup", "completed")
    writer.write_manifest({
        "schema_version": 1, "task_id": "task-1", "status": "COMPLETED",
        "error_code": None,
        "events_path": str(run_dir / "events.jsonl"),
    })
    writer.write_report({
        "task_id": "task-1", "status": "COMPLETED", "error_code": None,
        "started_at": "2026-08-25T00:00:00+00:00",
        "finished_at": "2026-08-25T00:00:01+00:00", "duration_seconds": 1.0,
        "n_books": 1, "n_scenes": 2, "peak_rss_mb": None,
        "peak_vram_mb": None, "manifest_path": str(run_dir / "manifest.json"),
        "events_path": str(run_dir / "events.jsonl"), "worker_exit_code": 0,
        "cleanup_error": None,
        "original_error_code": None, "original_exit_code": None,
        "report_write_error": None, "report_recovery_error": None,
    })

    events = read_events(run_dir, "task-1")
    assert [event["event_type"] for event in events] == ["started", "completed", "completed"]
    assert read_report(run_dir, "task-1")["worker_exit_code"] == 0
    assert json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))["task_id"] == "task-1"


def test_event_reader_rejects_unknown_event_fields(tmp_path: Path, monkeypatch) -> None:
    stage = tmp_path / "stage"
    stage.mkdir()
    monkeypatch.setattr(events_module, "EVENT_STAGE_ROOT", stage)
    run_dir = stage / "20260825-000001-000001"
    run_dir.mkdir()
    writer = EventWriter(run_dir, "task-1")
    writer.write_event("collect", "started")
    path = run_dir / "events.jsonl"
    event = json.loads(path.read_text(encoding="utf-8"))
    event["unexpected"] = True
    path.write_text(json.dumps(event), encoding="utf-8")

    with pytest.raises(EventContractError):
        read_events(run_dir, "task-1")


def test_event_readers_require_nonempty_expected_task_id(tmp_path: Path, monkeypatch) -> None:
    stage = tmp_path / "stage"
    stage.mkdir()
    monkeypatch.setattr(events_module, "EVENT_STAGE_ROOT", stage)
    run_dir = stage / "20260825-000001-000001"
    run_dir.mkdir()
    writer = EventWriter(run_dir, "task-1")
    writer.write_event("preflight", "started")

    with pytest.raises(EventContractError, match="非空字符串"):
        read_events(run_dir, "")
    with pytest.raises(EventContractError, match="非空字符串"):
        read_report(run_dir, None)  # type: ignore[arg-type]
    with pytest.raises(EventContractError, match="非空字符串"):
        read_failure(run_dir, None)  # type: ignore[arg-type]


def test_manifest_rejects_missing_events_artifact(tmp_path: Path, monkeypatch) -> None:
    stage = tmp_path / "stage"
    stage.mkdir()
    monkeypatch.setattr(events_module, "EVENT_STAGE_ROOT", stage)
    run_dir = stage / "20260825-000001-000001"
    run_dir.mkdir()
    writer = EventWriter(run_dir, "task-1")

    with pytest.raises(EventContractError, match="events.jsonl 不存在"):
        writer.write_manifest({
                "schema_version": 1,
                "task_id": "task-1",
                "status": "COMPLETED",
                "error_code": None,
            "events_path": str(run_dir / "events.jsonl"),
        })


def test_read_events_wraps_file_read_errors(tmp_path: Path, monkeypatch) -> None:
    stage = tmp_path / "stage"
    stage.mkdir()
    monkeypatch.setattr(events_module, "EVENT_STAGE_ROOT", stage)
    run_dir = stage / "20260825-000001-000001"
    run_dir.mkdir()
    writer = EventWriter(run_dir, "task-1")
    writer.write_event("preflight", "started")
    real_read_text = Path.read_text

    def fail_read_text(path, *args, **kwargs):
        if path == run_dir / "events.jsonl":
            raise OSError("injected events read failure")
        return real_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_read_text)
    with pytest.raises(EventContractError, match="events.jsonl 无法读取"):
        read_events(run_dir, "task-1")


def test_task_snapshot_is_json_compatible() -> None:
    raw = {
        "task_id": "task-1", "genre": "末世", "force": True, "limit": 1,
        "run_dir": "D:/tmp/yeyu-ai-a3/mpv-02b-worker/20260825-000001-000001",
        "cache_dir": "D:/tmp/yeyu-ai-a3/mpv-02b-worker/20260825-000001-000001/output/scene_index.sample",
        "model_local_path": "D:/DaMoXing/embedding/bge-small-zh-v1.5",
        "resource_limits": {"rss_mb": 4096, "disk_free_gb": 10},
        "cancel_flag": "D:/tmp/yeyu-ai-a3/mpv-02b-worker/20260825-000001-000001/cancel.flag",
    }
    snapshot = IndexBuildTaskSnapshot.from_mapping(raw)

    assert snapshot.limit == 1
    assert isinstance(snapshot.resource_limits, dict)


def test_scene_search_explicit_cache_is_bound_to_run_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(scene_search_module, "_configure_jieba_cache", lambda _path: None)
    monkeypatch.setattr(
        scene_search_module,
        "get_config",
        lambda: {"scene_search": {"cache_dir": "data/processed/{genre}/scene_index"}},
    )
    run_dir = tmp_path / "20260825-000001-000001"
    run_dir.mkdir(parents=True)
    cache = run_dir / "output" / "scene_index.sample"

    engine = scene_search_module.SceneSearch(
        "测试题材", cache_dir=cache, cache_root=run_dir
    )

    assert engine._cache == cache.resolve()
    assert engine._formal_cache == (
        scene_search_module.PROJECT_ROOT / "data" / "processed" / "测试题材" / "scene_index"
    ).resolve()
    with pytest.raises(scene_search_module.IndexNotReadyError, match="越出批准目录"):
        scene_search_module.SceneSearch(
            "测试题材", cache_dir=run_dir.parent / "outside", cache_root=run_dir
        )


def test_worker_snapshot_rejects_project_cache_path(monkeypatch) -> None:
    worker_stage = Path(r"D:\tmp\yeyu-ai-a3\mpv-02b-worker")
    run_dir = worker_stage / "20260831-999999-999999"
    model_dir = Path(r"D:\DaMoXing\embedding\bge-small-zh-v1.5")
    monkeypatch.setattr(worker_module, "WORKER_STAGE_ROOT", worker_stage)
    snapshot = IndexBuildTaskSnapshot(
        task_id="task-1",
        genre="末世",
        force=True,
        limit=1,
        run_dir=str(run_dir),
        cache_dir=r"D:\Code\yeyu-ai\xiaoshuo\data\processed\末世\tmp",
        model_local_path=str(model_dir),
        resource_limits={},
        cancel_flag=str(run_dir / "cancel.flag"),
    )

    with pytest.raises(WorkerStop, match="当前 run/output 内"):
        worker_module._validate_snapshot_paths(snapshot)


def test_worker_snapshot_accepts_fixed_run_output_cache(monkeypatch) -> None:
    worker_stage = Path(r"D:\tmp\yeyu-ai-a3\mpv-02b-worker")
    run_dir = worker_stage / "20260831-999999-999998"
    model_dir = Path(r"D:\DaMoXing\embedding\bge-small-zh-v1.5")
    cache = run_dir / "output" / "scene_index.sample"
    monkeypatch.setattr(worker_module, "WORKER_STAGE_ROOT", worker_stage)
    snapshot = IndexBuildTaskSnapshot(
        task_id="task-1",
        genre="末世",
        force=True,
        limit=1,
        run_dir=str(run_dir),
        cache_dir=str(cache),
        model_local_path=str(model_dir),
        resource_limits={},
        cancel_flag=str(run_dir / "cancel.flag"),
    )

    _, validated_cache, _, _ = worker_module._validate_snapshot_paths(snapshot)

    assert validated_cache == cache.absolute()


def test_public_worker_entry_uses_fixed_run_output_cache(monkeypatch) -> None:
    stage = Path(r"D:\tmp\yeyu-ai-a3\mpv-02b-worker")
    run_dir = stage / f"20260831-999999-{uuid.uuid4().int % 1000000:06d}"
    cache = run_dir / "output" / "scene_index.sample"
    model = Path(r"D:\DaMoXing\embedding\bge-small-zh-v1.5")
    assert not run_dir.exists()
    snapshot = {
        "task_id": "task-1",
        "genre": "末世",
        "force": True,
        "limit": 1,
        "run_dir": str(run_dir),
        "cache_dir": str(cache),
        "model_local_path": str(model),
        "resource_limits": {},
        "cancel_flag": str(run_dir / "cancel.flag"),
    }

    class FakeSceneSearch:
        embedding_model_path = model

        def __init__(self, genre, resource_guard=None, cache_dir=None, cache_root=None):
            assert Path(cache_dir) == cache
            assert Path(cache_root) == run_dir
            self._cache = cache

        def build_index(self, **kwargs):
            cache.mkdir(parents=True, exist_ok=True)
            (cache / "manifest.json").write_text(
                json.dumps({"n_books": 1, "n_scenes": 1}), encoding="utf-8"
            )
            return 1

    monkeypatch.setattr(worker_module, "SceneSearch", FakeSceneSearch)

    try:
        result = worker_module.run_index_build_worker(snapshot)

        assert result == 0
        assert (cache / "manifest.json").is_file()
        assert read_report(run_dir, "task-1")["status"] == "COMPLETED"
    finally:
        if run_dir.exists():
            shutil.rmtree(run_dir)


def test_public_worker_entry_uses_fixed_formal_run_output_cache(monkeypatch) -> None:
    stage = Path(r"D:\tmp\yeyu-ai-a3\mpv-02b-worker")
    run_dir = stage / f"20260831-999999-{uuid.uuid4().int % 1000000:06d}"
    cache = run_dir / "output" / "scene_index"
    model = Path(r"D:\DaMoXing\embedding\bge-small-zh-v1.5")
    assert not run_dir.exists()
    snapshot = {
        "task_id": "task-1",
        "genre": "末世",
        "force": True,
        "limit": 0,
        "run_dir": str(run_dir),
        "cache_dir": str(cache),
        "model_local_path": str(model),
        "resource_limits": {},
        "cancel_flag": str(run_dir / "cancel.flag"),
    }

    class FakeSceneSearch:
        embedding_model_path = model

        def __init__(self, genre, resource_guard=None, cache_dir=None, cache_root=None):
            assert Path(cache_dir) == cache
            assert Path(cache_root) == run_dir
            self._cache = cache

        def build_index(self, **kwargs):
            assert kwargs["limit"] == 0
            cache.mkdir(parents=True, exist_ok=True)
            (cache / "manifest.json").write_text(
                json.dumps({"n_books": 1, "n_scenes": 1}), encoding="utf-8"
            )
            return 1

    monkeypatch.setattr(worker_module, "SceneSearch", FakeSceneSearch)

    try:
        result = worker_module.run_index_build_worker(snapshot)

        assert result == 0
        assert (cache / "manifest.json").is_file()
        assert read_report(run_dir, "task-1")["status"] == "COMPLETED"
    finally:
        if run_dir.exists():
            shutil.rmtree(run_dir)


def test_public_worker_entry_rejects_project_cache_path(capsys) -> None:
    stage = Path(r"D:\tmp\yeyu-ai-a3\mpv-02b-worker")
    run_dir = stage / f"20260831-999998-{uuid.uuid4().int % 1000000:06d}"
    cache = Path(r"D:\Code\yeyu-ai\xiaoshuo\data\processed\末世\scene_index")
    model = Path(r"D:\DaMoXing\embedding\bge-small-zh-v1.5")
    snapshot = {
        "task_id": "task-1",
        "genre": "末世",
        "force": True,
        "limit": 0,
        "run_dir": str(run_dir),
        "cache_dir": str(cache),
        "model_local_path": str(model),
        "resource_limits": {},
        "cancel_flag": str(run_dir / "cancel.flag"),
    }

    result = worker_module.run_index_build_worker(snapshot)

    assert result == EXIT_CODES["PERMISSION_DENIED"]
    output = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert output["error_code"] == "PERMISSION_DENIED"
    assert not run_dir.exists()
    assert not cache.exists()


@pytest.mark.parametrize(
    ("path_kind", "expected_code"),
    [("outside", "PERMISSION_DENIED"), ("traversal", "WORKER_FAILED")],
)
def test_public_worker_entry_rejects_noncontained_run_paths(
    path_kind: str, expected_code: str, capsys
) -> None:
    stage = Path(r"D:\tmp\yeyu-ai-a3\mpv-02b-worker")
    run_id = f"20260831-999998-{uuid.uuid4().int % 1000000:06d}"
    if path_kind == "outside":
        run_dir = stage.parent / "mpv-02b-worker-outside" / run_id
    else:
        run_dir = stage / ".." / "mpv-02b-worker-outside" / run_id
    cache = run_dir / "output" / "scene_index.sample"
    model = Path(r"D:\DaMoXing\embedding\bge-small-zh-v1.5")
    snapshot = {
        "task_id": "task-1",
        "genre": "末世",
        "force": True,
        "limit": 1,
        "run_dir": str(run_dir),
        "cache_dir": str(cache),
        "model_local_path": str(model),
        "resource_limits": {},
        "cancel_flag": str(run_dir / "cancel.flag"),
    }

    result = worker_module.run_index_build_worker(snapshot)

    assert result == EXIT_CODES[expected_code]
    output = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert output["error_code"] == expected_code
    assert not run_dir.exists()
    assert not cache.exists()


def test_public_worker_entry_rejects_reparse_cache(monkeypatch, capsys) -> None:
    stage = Path(r"D:\tmp\yeyu-ai-a3\mpv-02b-worker")
    run_dir = stage / f"20260831-999998-{uuid.uuid4().int % 1000000:06d}"
    cache = run_dir / "output" / "scene_index.sample"
    model = Path(r"D:\DaMoXing\embedding\bge-small-zh-v1.5")
    snapshot = {
        "task_id": "task-1",
        "genre": "末世",
        "force": True,
        "limit": 1,
        "run_dir": str(run_dir),
        "cache_dir": str(cache),
        "model_local_path": str(model),
        "resource_limits": {},
        "cancel_flag": str(run_dir / "cancel.flag"),
    }
    real_reject = worker_module._reject_reparse

    def reject_reparse(path: Path) -> None:
        if Path(path).absolute() == cache.absolute():
            raise WorkerStop("PERMISSION_DENIED", "注入缓存 reparse 边界")
        real_reject(path)

    monkeypatch.setattr(worker_module, "_reject_reparse", reject_reparse)

    result = worker_module.run_index_build_worker(snapshot)

    assert result == EXIT_CODES["PERMISSION_DENIED"]
    output = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert output["error_code"] == "PERMISSION_DENIED"
    assert not run_dir.exists()
    assert not cache.exists()


def test_worker_session_cancellation_is_fail_closed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(events_module, "EVENT_STAGE_ROOT", tmp_path)
    run_dir = tmp_path / "20260825-000001-000001"
    run_dir.mkdir()
    writer = EventWriter(run_dir, "task-1")
    snapshot = _snapshot(run_dir)
    session = WorkerSession(snapshot, writer)
    (run_dir / "cancel.flag").write_text("cancel", encoding="ascii")

    with pytest.raises(WorkerStop) as caught:
        session.on_progress("collect", 1, 5)

    assert caught.value.error_code == "CANCELLED"


def test_worker_session_stops_on_resource_limit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(events_module, "EVENT_STAGE_ROOT", tmp_path)
    run_dir = tmp_path / "20260825-000001-000001"
    run_dir.mkdir()
    writer = EventWriter(run_dir, "task-1")
    snapshot = _snapshot(run_dir, rss_mb=100)
    session = WorkerSession(snapshot, writer)
    monkeypatch.setattr(session.sampler, "snapshot", lambda: {
        "rss_mb": 101, "sys_mem_available_gb": 8, "disk_free_gb": 100,
        "gpu_temp": None, "gpu_util": None, "vram_used_mb": None,
    })

    with pytest.raises(WorkerStop) as caught:
        session.on_progress("encode", 100, 200)

    assert caught.value.error_code == "RESOURCE_EXCEEDED"
    assert EXIT_CODES["RESOURCE_EXCEEDED"] == 3


def test_worker_session_stops_when_configured_metric_is_unknown(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(events_module, "EVENT_STAGE_ROOT", tmp_path)
    run_dir = tmp_path / "20260825-000001-000001"
    run_dir.mkdir()
    writer = EventWriter(run_dir, "task-1")
    snapshot = _snapshot(run_dir, gpu_temp_c=80)
    session = WorkerSession(snapshot, writer)
    monkeypatch.setattr(session.sampler, "snapshot", lambda: {
        "rss_mb": 100, "sys_mem_available_gb": 8, "disk_free_gb": 100,
        "gpu_temp": None, "gpu_util": None, "vram_used_mb": None,
    })

    with pytest.raises(WorkerStop, match="指标不可用"):
        session.on_progress("encode", 100, 200)


def test_cleanup_event_failure_is_recorded_without_replacing_build_error(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(events_module, "EVENT_STAGE_ROOT", tmp_path)
    run_dir = tmp_path / "20260825-000001-000001"
    run_dir.mkdir()
    writer = EventWriter(run_dir, "task-1")
    snapshot = _snapshot(run_dir)
    session = WorkerSession(snapshot, writer)

    def fail_cleanup(phase, event_type, **kwargs):
        if phase == "cleanup":
            raise OSError("injected cleanup event failure")
        return {}

    monkeypatch.setattr(writer, "write_event", fail_cleanup)
    session.on_progress("cleanup", 0, 1)
    assert len(session.cleanup_errors) == 1
    assert "injected cleanup event failure" in session.cleanup_errors[0]
    writer.close()


def test_cleanup_start_event_does_not_close_event_writer(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(events_module, "EVENT_STAGE_ROOT", tmp_path)
    run_dir = tmp_path / "20260825-000001-000001"
    run_dir.mkdir()
    writer = EventWriter(run_dir, "task-1")
    writer.write_event("preflight", "started")
    writer.write_event("cleanup", "started", n_done=0, n_total=1)
    writer.write_event("cleanup", "completed", n_done=1, n_total=1)
    assert [event["event_type"] for event in read_events(run_dir, "task-1")] == [
        "started", "started", "completed"
    ]
    writer.close()


def test_bootstrap_report_is_readable_by_standard_contract_readers(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(events_module, "EVENT_STAGE_ROOT", tmp_path)
    run_dir = tmp_path / "20260825-000001-000001"
    run_dir.mkdir()
    assert worker_module._write_bootstrap_report(
        run_dir, "task-1", "WORKER_FAILED", "初始化失败"
    )
    report = read_report(run_dir, "task-1")
    assert report["status"] == "FAILED"
    assert report["error_code"] == "WORKER_FAILED"
    assert len(read_events(run_dir, "task-1")) == 2
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["error_code"] == "WORKER_FAILED"


def test_bootstrap_report_does_not_overwrite_existing_history(tmp_path: Path) -> None:
    run_dir = tmp_path / "20260825-000001-000001"
    run_dir.mkdir()
    events = run_dir / "events.jsonl"
    events.write_text("existing\n", encoding="utf-8")

    assert not worker_module._write_bootstrap_report(
        run_dir, "task-1", "WORKER_FAILED", "初始化失败"
    )
    assert events.read_text(encoding="utf-8") == "existing\n"
    assert not (run_dir / "manifest.json").exists()
    assert not (run_dir / "report.json").exists()


@pytest.mark.parametrize("existing_name", ["manifest.json", "report.json"])
def test_bootstrap_preflight_rejects_any_existing_target_without_partial_write(
    tmp_path: Path, existing_name: str
) -> None:
    run_dir = tmp_path / "20260825-000001-000001"
    run_dir.mkdir()
    existing = run_dir / existing_name
    existing.write_text("existing\n", encoding="utf-8")

    assert not worker_module._write_bootstrap_report(
        run_dir, "task-1", "WORKER_FAILED", "初始化失败"
    )
    for name in ("events.jsonl", "manifest.json", "report.json"):
        target = run_dir / name
        if name == existing_name:
            assert target.read_text(encoding="utf-8") == "existing\n"
        else:
            assert not target.exists()


def test_report_recovery_is_readable_without_manifest_after_manifest_first_write_failure(
    tmp_path: Path, monkeypatch
) -> None:
    stage = tmp_path / "stage"
    run_dir = stage / "20260825-000001-000001"
    run_dir.mkdir(parents=True)
    monkeypatch.setattr(events_module, "EVENT_STAGE_ROOT", stage)
    writer = EventWriter(run_dir, "task-1")
    writer.write_event("preflight", "started")
    writer.write_event("cleanup", "failed", error_code="MODEL_ERROR")
    report = {
        "task_id": "task-1", "status": "FAILED", "error_code": "REPORT_WRITE_FAILED",
        "started_at": "2026-08-25T00:00:00+00:00",
        "finished_at": "2026-08-25T00:00:01+00:00", "duration_seconds": 1.0,
        "n_books": None, "n_scenes": None, "peak_rss_mb": None,
        "peak_vram_mb": None, "manifest_path": str(run_dir / "manifest.json"),
        "events_path": str(run_dir / "events.jsonl"), "worker_exit_code": 10,
        "cleanup_error": "cleanup 终态事件写入失败", "original_error_code": "MODEL_ERROR",
        "original_exit_code": 5, "report_write_error": "manifest 首写失败",
        "report_recovery_error": None,
    }

    assert writer.write_report_recovery(report)
    assert not (run_dir / "manifest.json").exists()
    recovered = events_module.read_report(run_dir, "task-1")
    assert set(recovered) == set(events_module.REPORT_FIELDS)
    assert recovered["error_code"] == "REPORT_WRITE_FAILED"
    assert recovered["original_error_code"] == "MODEL_ERROR"
    assert recovered["original_exit_code"] == 5
    assert recovered["report_write_error"] == "manifest 首写失败"
    normal_report = dict(
        report,
        error_code="MODEL_ERROR",
        worker_exit_code=5,
        cleanup_error="模型失败",
        original_error_code=None,
        original_exit_code=None,
        report_write_error=None,
        report_recovery_error=None,
    )
    with pytest.raises(events_module.EventContractError, match="manifest.json 不存在"):
        events_module._validate_report(normal_report, "task-1", run_dir)
    assert persistence_module.write_failure_artifact(
        run_dir, report, "task-1", reject_reparse=events_module._reject_reparse
    )
    failure = events_module.read_failure(run_dir, "task-1")
    assert set(failure) == set(events_module.REPORT_FIELDS)
    assert failure["error_code"] == "REPORT_WRITE_FAILED"
    assert failure["original_error_code"] == "MODEL_ERROR"
    assert failure["original_exit_code"] == 5


def test_recovery_rejects_stale_manifest_when_cleanup_contract_is_complete(
    tmp_path: Path, monkeypatch
) -> None:
    stage = tmp_path / "stage"
    run_dir = stage / "20260825-000001-000001"
    run_dir.mkdir(parents=True)
    monkeypatch.setattr(events_module, "EVENT_STAGE_ROOT", stage)
    writer = EventWriter(run_dir, "task-1")
    writer.write_event("preflight", "started")
    writer.write_event("cleanup", "completed")
    writer.write_manifest({
        "schema_version": 1, "task_id": "task-1", "status": "FAILED",
        "error_code": "MODEL_ERROR", "events_path": str(run_dir / "events.jsonl"),
    })
    report = {
        "task_id": "task-1", "status": "FAILED", "error_code": "REPORT_WRITE_FAILED",
        "started_at": "2026-08-25T00:00:00+00:00",
        "finished_at": "2026-08-25T00:00:01+00:00", "duration_seconds": 1.0,
        "n_books": None, "n_scenes": None, "peak_rss_mb": None,
        "peak_vram_mb": None, "manifest_path": str(run_dir / "manifest.json"),
        "events_path": str(run_dir / "events.jsonl"), "worker_exit_code": 10,
        "cleanup_error": None, "original_error_code": "COMPLETED", "original_exit_code": 0,
        "report_write_error": "report 写入失败", "report_recovery_error": "recovery failed",
    }
    with pytest.raises(events_module.EventContractError, match="manifest 原始结果不一致"):
        events_module._validate_report(report, "task-1", run_dir, require_cleanup_terminal=False)


def test_persistence_bootstrap_converts_path_guard_exception_to_failure(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "20260825-000001-000001"
    run_dir.mkdir()

    def reject(_path: Path) -> None:
        raise WorkerStop("PERMISSION_DENIED", "injected reparse race")

    assert not persistence_module.write_bootstrap_report(
        run_dir,
        "task-1",
        "WORKER_FAILED",
        "初始化失败",
        reject_reparse=reject,
    )


def test_persistence_failure_artifact_converts_path_guard_exception_to_failure(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "20260825-000001-000001"
    run_dir.mkdir()

    def reject(_path: Path) -> None:
        raise WorkerStop("PERMISSION_DENIED", "injected reparse race")

    assert not persistence_module.write_failure_artifact(
        run_dir,
        {},
        "task-1",
        reject_reparse=reject,
    )


def test_snapshot_rejects_unknown_resource_limit_key(tmp_path: Path, monkeypatch) -> None:
    del tmp_path, monkeypatch
    with pytest.raises(WorkerStop, match="未知键"):
        worker_module._validate_resource_limits({"gpu_temp": 80})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_resource_limits_reject_nonfinite_values(value: float) -> None:
    with pytest.raises(WorkerStop, match="资源阈值无效"):
        worker_module._validate_resource_limits({"rss_mb": value})


def test_publish_rollback_failure_has_stable_error_code() -> None:
    assert worker_module.EXIT_CODES["PUBLISH_ROLLBACK_FAILED"] == 9


def test_event_contract_rejects_nonfinite_resource_and_wrong_report_path(
    tmp_path: Path, monkeypatch
) -> None:
    stage = tmp_path / "stage"
    stage.mkdir()
    monkeypatch.setattr(events_module, "EVENT_STAGE_ROOT", stage)
    run_dir = stage / "20260825-000001-000001"
    run_dir.mkdir()
    writer = EventWriter(run_dir, "task-1")
    with pytest.raises(EventContractError):
        writer.write_event("collect", "started", resources={"rss_mb": float("nan")})
    writer.write_event("preflight", "started")
    writer.write_manifest({
        "schema_version": 1, "task_id": "task-1", "status": "FAILED",
        "error_code": "WORKER_FAILED",
        "events_path": str(run_dir / "events.jsonl"),
    })
    with pytest.raises(EventContractError):
        writer.write_report({
            "task_id": "task-1", "status": "FAILED", "error_code": "WORKER_FAILED",
            "started_at": "2026-08-25T00:00:00+00:00",
            "finished_at": "2026-08-25T00:00:01+00:00", "duration_seconds": 1.0,
            "n_books": None, "n_scenes": None, "peak_rss_mb": None,
            "peak_vram_mb": None, "manifest_path": str(run_dir / "manifest.json"),
            "events_path": str(stage / "other" / "events.jsonl"),
            "worker_exit_code": 8, "cleanup_error": None,
            "original_error_code": None, "original_exit_code": None,
            "report_write_error": None, "report_recovery_error": None,
        })


def test_report_contract_binds_error_code_to_exit_code(tmp_path: Path, monkeypatch) -> None:
    stage = tmp_path / "stage"
    stage.mkdir()
    monkeypatch.setattr(events_module, "EVENT_STAGE_ROOT", stage)
    run_dir = stage / "20260825-000001-000001"
    run_dir.mkdir()
    writer = EventWriter(run_dir, "task-1")
    writer.write_event("preflight", "started")
    writer.write_manifest({
        "schema_version": 1, "task_id": "task-1", "status": "FAILED",
        "error_code": "WORKER_FAILED",
        "events_path": str(run_dir / "events.jsonl"),
    })
    base = {
        "task_id": "task-1", "status": "FAILED", "error_code": "MODEL_ERROR",
        "started_at": "2026-08-25T00:00:00+00:00",
        "finished_at": "2026-08-25T00:00:01+00:00", "duration_seconds": 1.0,
        "n_books": None, "n_scenes": None, "peak_rss_mb": None,
        "peak_vram_mb": None, "manifest_path": str(run_dir / "manifest.json"),
        "events_path": str(run_dir / "events.jsonl"),
        "worker_exit_code": 8, "cleanup_error": None,
        "original_error_code": None, "original_exit_code": None,
        "report_write_error": None, "report_recovery_error": None,
    }
    with pytest.raises(EventContractError, match="退出码或错误码"):
        writer.write_report(base)
    base["error_code"] = "MODEL_ERROR"
    base["worker_exit_code"] = 5
    with pytest.raises(EventContractError, match="error_code 不一致"):
        writer.write_report(base)
    base["status"] = "COMPLETED"
    base["error_code"] = None
    base["worker_exit_code"] = 0
    base["cleanup_error"] = "cleanup 失败"
    with pytest.raises(EventContractError, match="COMPLETED report"):
        writer.write_report(base)

    for invalid_error_code in ("COMPLETED", "CANCELLED"):
        base["status"] = "FAILED"
        base["error_code"] = invalid_error_code
        base["worker_exit_code"] = events_module.REPORT_ERROR_EXIT_CODES[invalid_error_code]
        with pytest.raises(EventContractError, match="FAILED report 的错误码无效"):
            writer.write_report(base)

    base["status"] = "COMPLETED"
    base["error_code"] = None
    base["worker_exit_code"] = 0.0
    with pytest.raises(EventContractError, match="worker_exit_code 无效"):
        writer.write_report(base)

    base.update(
        status="FAILED", error_code="REPORT_WRITE_FAILED", worker_exit_code=10,
        original_error_code="COMPLETED", original_exit_code=0.0,
        report_write_error="primary failed", report_recovery_error=None,
    )
    with pytest.raises(EventContractError, match="original_exit_code 无效"):
        writer.write_report(base)


def test_report_write_failure_exit_code_is_stable() -> None:
    assert worker_module.EXIT_CODES["REPORT_WRITE_FAILED"] == 10


def test_cleanup_terminal_error_code_matches_report_original_result(
    tmp_path: Path, monkeypatch
) -> None:
    stage = tmp_path / "stage"
    stage.mkdir()
    monkeypatch.setattr(events_module, "EVENT_STAGE_ROOT", stage)
    run_dir = stage / "20260825-000001-000001"
    run_dir.mkdir()
    writer = EventWriter(run_dir, "task-1")
    writer.write_event("preflight", "started")
    writer.write_event("cleanup", "failed", error_code="MODEL_ERROR")
    writer.write_manifest({
        "schema_version": 1, "task_id": "task-1", "status": "FAILED",
        "error_code": "MODEL_ERROR", "events_path": str(run_dir / "events.jsonl"),
    })
    report = {
        "task_id": "task-1", "status": "FAILED", "error_code": "MODEL_ERROR",
        "started_at": "2026-08-25T00:00:00+00:00",
        "finished_at": "2026-08-25T00:00:01+00:00", "duration_seconds": 1.0,
        "n_books": None, "n_scenes": None, "peak_rss_mb": None,
        "peak_vram_mb": None, "manifest_path": str(run_dir / "manifest.json"),
        "events_path": str(run_dir / "events.jsonl"), "worker_exit_code": 5,
        "cleanup_error": None, "original_error_code": None,
        "original_exit_code": None, "report_write_error": None,
        "report_recovery_error": None,
    }
    writer.write_report(report)
    assert read_report(run_dir, "task-1")["error_code"] == "MODEL_ERROR"

    events = read_events(run_dir, "task-1")
    events[-1]["error_code"] = "WORKER_FAILED"
    (run_dir / "events.jsonl").write_text(
        "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in events),
        encoding="utf-8",
    )
    with pytest.raises(EventContractError, match="error_code"):
        read_report(run_dir, "task-1")


def test_run_worker_success_writes_contract_report(tmp_path: Path, monkeypatch) -> None:
    stage = tmp_path / "stage"
    run_dir = stage / "20260825-000001-000001"
    cache = run_dir / "output" / "scene_index"
    model = run_dir / "model"
    run_dir.mkdir(parents=True)
    model.mkdir()
    monkeypatch.setattr(events_module, "EVENT_STAGE_ROOT", stage)

    snapshot = _snapshot(run_dir)
    snapshot = snapshot.__class__(
        task_id=snapshot.task_id, genre=snapshot.genre, force=True, limit=0,
        run_dir=snapshot.run_dir, cache_dir=str(cache), model_local_path=str(model),
        resource_limits={}, cancel_flag=snapshot.cancel_flag,
    )

    class FakeSceneSearch:
        embedding_model_path = model
        _formal_cache = cache

        def __init__(self, genre, resource_guard=None, cache_dir=None, cache_root=None):
            self.genre = genre

        def build_index(self, **kwargs):
            cache.mkdir(parents=True, exist_ok=True)
            (cache / "manifest.json").write_text(
                json.dumps({"n_books": 1, "n_scenes": 1}), encoding="utf-8"
            )
            return 1

    monkeypatch.setattr(worker_module, "SceneSearch", FakeSceneSearch)
    result = worker_module._run_worker(snapshot, run_dir)

    assert result == 0
    report = read_report(run_dir, snapshot.task_id)
    assert report["status"] == "COMPLETED"
    assert report["manifest_path"] == (run_dir / "manifest.json").as_posix()
    events = read_events(run_dir, snapshot.task_id)
    cleanup_events = [event for event in events if event["phase"] == "cleanup"]
    assert len(cleanup_events) == 1
    assert cleanup_events[0]["event_type"] == "completed"


def test_run_worker_cleanup_failure_syncs_manifest_and_report_status(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    stage = tmp_path / "stage"
    run_dir = stage / "20260825-000001-000001"
    cache = run_dir / "output" / "scene_index"
    model = run_dir / "model"
    run_dir.mkdir(parents=True)
    model.mkdir()
    monkeypatch.setattr(events_module, "EVENT_STAGE_ROOT", stage)

    snapshot = _snapshot(run_dir)
    snapshot = snapshot.__class__(
        task_id=snapshot.task_id, genre=snapshot.genre, force=True, limit=0,
        run_dir=snapshot.run_dir, cache_dir=str(cache), model_local_path=str(model),
        resource_limits={}, cancel_flag=snapshot.cancel_flag,
    )

    class FakeSceneSearch:
        embedding_model_path = model
        _formal_cache = cache

        def __init__(self, genre, resource_guard=None, cache_dir=None, cache_root=None):
            self.genre = genre

        def build_index(self, **kwargs):
            cache.mkdir(parents=True, exist_ok=True)
            (cache / "manifest.json").write_text(
                json.dumps({"n_books": 1, "n_scenes": 1}), encoding="utf-8"
            )
            return 1

    real_write_event = EventWriter.write_event

    def fail_cleanup(self, phase, event_type, **kwargs):
        if phase == "cleanup":
            raise OSError("injected cleanup event failure")
        return real_write_event(self, phase, event_type, **kwargs)

    monkeypatch.setattr(worker_module, "SceneSearch", FakeSceneSearch)
    monkeypatch.setattr(EventWriter, "write_event", fail_cleanup)

    result = worker_module._run_worker(snapshot, run_dir)

    assert result == EXIT_CODES["REPORT_WRITE_FAILED"]
    output = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert output["original_error_code"] == "WORKER_FAILED"
    assert output["persistence_status"] == "RECOVERED"
    assert read_report(run_dir, snapshot.task_id)["original_error_code"] == "WORKER_FAILED"
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "FAILED"
    assert manifest["error_code"] == "WORKER_FAILED"


def test_run_worker_failure_event_error_is_kept_in_structured_report(
    tmp_path: Path, monkeypatch
) -> None:
    stage = tmp_path / "stage"
    run_dir = stage / "20260825-000001-000001"
    model = run_dir / "model"
    run_dir.mkdir(parents=True)
    model.mkdir()
    monkeypatch.setattr(events_module, "EVENT_STAGE_ROOT", stage)

    snapshot = _snapshot(run_dir)
    snapshot = snapshot.__class__(
        task_id=snapshot.task_id, genre=snapshot.genre, force=True, limit=0,
        run_dir=snapshot.run_dir, cache_dir=str(run_dir / "output" / "scene_index"),
        model_local_path=str(model), resource_limits={}, cancel_flag=snapshot.cancel_flag,
    )

    class FailingSceneSearch:
        embedding_model_path = model
        _formal_cache = Path(snapshot.cache_dir)

        def __init__(self, genre, resource_guard=None, cache_dir=None, cache_root=None):
            self.genre = genre

        def build_index(self, **kwargs):
            raise WorkerStop("MODEL_ERROR", "injected model failure")

    real_write_event = EventWriter.write_event

    def fail_business_event(self, phase, event_type, **kwargs):
        if event_type == "failed" and phase != "cleanup":
            raise OSError("injected failed event error")
        return real_write_event(self, phase, event_type, **kwargs)

    monkeypatch.setattr(worker_module, "SceneSearch", FailingSceneSearch)
    monkeypatch.setattr(EventWriter, "write_event", fail_business_event)

    result = worker_module._run_worker(snapshot, run_dir)

    assert result == EXIT_CODES["MODEL_ERROR"]
    report = read_report(run_dir, snapshot.task_id)
    assert report["error_code"] == "MODEL_ERROR"
    assert "失败事件写入失败：injected failed event error" in report["cleanup_error"]


def test_run_worker_manifest_sync_failure_has_persistence_failure_receipt(
    tmp_path: Path, monkeypatch
) -> None:
    stage = tmp_path / "stage"
    run_dir = stage / "20260825-000001-000001"
    cache = run_dir / "output" / "scene_index"
    model = run_dir / "model"
    run_dir.mkdir(parents=True)
    model.mkdir()
    monkeypatch.setattr(events_module, "EVENT_STAGE_ROOT", stage)

    snapshot = _snapshot(run_dir)
    snapshot = snapshot.__class__(
        task_id=snapshot.task_id, genre=snapshot.genre, force=True, limit=0,
        run_dir=snapshot.run_dir, cache_dir=str(cache), model_local_path=str(model),
        resource_limits={}, cancel_flag=snapshot.cancel_flag,
    )

    class FakeSceneSearch:
        embedding_model_path = model
        _formal_cache = cache

        def __init__(self, genre, resource_guard=None, cache_dir=None, cache_root=None):
            self.genre = genre

        def build_index(self, **kwargs):
            cache.mkdir(parents=True, exist_ok=True)
            (cache / "manifest.json").write_text(
                json.dumps({"n_books": 1, "n_scenes": 1}), encoding="utf-8"
            )
            return 1

    real_write_manifest = EventWriter.write_manifest
    calls = {"count": 0}

    def fail_final_manifest(self, manifest):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("injected manifest sync failure")
        return real_write_manifest(self, manifest)

    monkeypatch.setattr(worker_module, "SceneSearch", FakeSceneSearch)
    monkeypatch.setattr(EventWriter, "write_manifest", fail_final_manifest)

    result = worker_module._run_worker(snapshot, run_dir)

    assert result == EXIT_CODES["REPORT_WRITE_FAILED"]
    report = read_report(run_dir, snapshot.task_id)
    assert report["status"] == "FAILED"
    assert report["error_code"] == "REPORT_WRITE_FAILED"
    assert report["original_error_code"] == "COMPLETED"
    assert report["original_exit_code"] == 0
    assert report["report_write_error"] == "injected manifest sync failure"
    assert report["cleanup_error"] is None
    assert report["report_write_error"] == "injected manifest sync failure"
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "COMPLETED"
    assert manifest["error_code"] is None
    cleanup_events = [
        event for event in read_events(run_dir, snapshot.task_id)
        if event["phase"] == "cleanup"
    ]
    assert [event["event_type"] for event in cleanup_events] == ["completed"]


def test_cleanup_and_manifest_sync_failure_is_unpersisted(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    stage = tmp_path / "stage"
    run_dir = stage / "20260825-000001-000001"
    cache = run_dir / "output" / "scene_index"
    model = run_dir / "model"
    run_dir.mkdir(parents=True)
    model.mkdir()
    monkeypatch.setattr(events_module, "EVENT_STAGE_ROOT", stage)

    snapshot = _snapshot(run_dir)
    snapshot = snapshot.__class__(
        task_id=snapshot.task_id, genre=snapshot.genre, force=True, limit=0,
        run_dir=snapshot.run_dir, cache_dir=str(cache), model_local_path=str(model),
        resource_limits={}, cancel_flag=snapshot.cancel_flag,
    )

    class FakeSceneSearch:
        embedding_model_path = model
        _formal_cache = cache

        def __init__(self, genre, resource_guard=None, cache_dir=None, cache_root=None):
            self.genre = genre

        def build_index(self, **kwargs):
            cache.mkdir(parents=True, exist_ok=True)
            (cache / "manifest.json").write_text(
                json.dumps({"n_books": 1, "n_scenes": 1}), encoding="utf-8"
            )
            return 1

    real_write_manifest = EventWriter.write_manifest
    real_write_event = EventWriter.write_event

    def fail_final_manifest(self, manifest):
        if manifest.get("status") == "FAILED":
            raise OSError("injected manifest sync failure")
        return real_write_manifest(self, manifest)

    def fail_cleanup(self, phase, event_type, **kwargs):
        if phase == "cleanup":
            raise OSError("injected cleanup event failure")
        return real_write_event(self, phase, event_type, **kwargs)

    monkeypatch.setattr(worker_module, "SceneSearch", FakeSceneSearch)
    monkeypatch.setattr(EventWriter, "write_manifest", fail_final_manifest)
    monkeypatch.setattr(EventWriter, "write_event", fail_cleanup)
    monkeypatch.setattr(EventWriter, "write_report_recovery", lambda self, report: False)

    result = worker_module._run_worker(snapshot, run_dir)

    assert result == EXIT_CODES["REPORT_WRITE_FAILED"]
    output = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert output["original_error_code"] == "WORKER_FAILED"
    assert output["persistence_status"] == "FAILURE_ARTIFACT_WRITTEN"
    failure = read_failure(run_dir, snapshot.task_id)
    assert failure["original_error_code"] == "WORKER_FAILED"
    assert failure["original_exit_code"] == EXIT_CODES["WORKER_FAILED"]
    assert "injected manifest sync failure" in failure["report_write_error"]


def test_read_report_rejects_reparse_bound_artifact(tmp_path: Path, monkeypatch) -> None:
    stage = tmp_path / "stage"
    stage.mkdir()
    monkeypatch.setattr(events_module, "EVENT_STAGE_ROOT", stage)
    run_dir = stage / "20260825-000001-000001"
    run_dir.mkdir()
    writer = EventWriter(run_dir, "task-1")
    writer.write_event("preflight", "started")
    writer.write_event("cleanup", "completed")
    writer.write_manifest({
        "schema_version": 1,
        "task_id": "task-1",
        "status": "COMPLETED",
        "error_code": None,
        "events_path": str(run_dir / "events.jsonl"),
    })
    report = {
        "task_id": "task-1", "status": "COMPLETED", "error_code": None,
        "started_at": "2026-08-25T00:00:00+00:00",
        "finished_at": "2026-08-25T00:00:01+00:00", "duration_seconds": 1.0,
        "n_books": 1, "n_scenes": 1, "peak_rss_mb": None,
        "peak_vram_mb": None, "manifest_path": str(run_dir / "manifest.json"),
        "events_path": str(run_dir / "events.jsonl"), "worker_exit_code": 0,
        "cleanup_error": None, "original_error_code": None,
        "original_exit_code": None, "report_write_error": None,
        "report_recovery_error": None,
    }
    writer.write_report(report)
    real_reject = events_module._reject_reparse

    def reject_events(path):
        if Path(path) == run_dir / "events.jsonl":
            raise EventContractError("injected reparse event")
        return real_reject(path)

    monkeypatch.setattr(events_module, "_reject_reparse", reject_events)
    with pytest.raises(EventContractError, match="injected reparse event"):
        read_report(run_dir, "task-1")


@pytest.mark.parametrize("reader_name", ["read_report", "read_failure"])
def test_report_readers_wrap_invalid_utf8(tmp_path: Path, monkeypatch, reader_name: str) -> None:
    stage = tmp_path / "stage"
    stage.mkdir()
    monkeypatch.setattr(events_module, "EVENT_STAGE_ROOT", stage)
    run_dir = stage / "20260825-000001-000001"
    run_dir.mkdir()
    target = run_dir / ("report.json" if reader_name == "read_report" else "failure.json")
    target.write_bytes(b"\xff")

    with pytest.raises(EventContractError, match="无法读取"):
        getattr(events_module, reader_name)(run_dir, "task-1")


def test_run_worker_report_recovery_preserves_original_completed_outcome(
    tmp_path: Path, monkeypatch
) -> None:
    stage = tmp_path / "stage"
    run_dir = stage / "20260825-000001-000001"
    cache = run_dir / "output" / "scene_index"
    model = run_dir / "model"
    run_dir.mkdir(parents=True)
    model.mkdir()
    monkeypatch.setattr(events_module, "EVENT_STAGE_ROOT", stage)

    snapshot = _snapshot(run_dir)
    snapshot = snapshot.__class__(
        task_id=snapshot.task_id, genre=snapshot.genre, force=True, limit=0,
        run_dir=snapshot.run_dir, cache_dir=str(cache), model_local_path=str(model),
        resource_limits={}, cancel_flag=snapshot.cancel_flag,
    )

    class FakeSceneSearch:
        embedding_model_path = model
        _formal_cache = cache

        def __init__(self, genre, resource_guard=None, cache_dir=None, cache_root=None):
            self.genre = genre

        def build_index(self, **kwargs):
            cache.mkdir(parents=True, exist_ok=True)
            (cache / "manifest.json").write_text(
                json.dumps({"n_books": 1, "n_scenes": 1}), encoding="utf-8"
            )
            return 1

    monkeypatch.setattr(worker_module, "SceneSearch", FakeSceneSearch)
    real_recovery = EventWriter.write_report_recovery

    def fail_primary(self, report):
        raise OSError()

    def capture_recovery(self, report):
        assert report["original_error_code"] == "COMPLETED"
        assert report["original_exit_code"] == 0
        assert report["report_recovery_error"] is None
        return real_recovery(self, report)

    monkeypatch.setattr(EventWriter, "write_report", fail_primary)
    monkeypatch.setattr(EventWriter, "write_report_recovery", capture_recovery)

    result = worker_module._run_worker(snapshot, run_dir)

    assert result == EXIT_CODES["REPORT_WRITE_FAILED"]
    report = read_report(run_dir, snapshot.task_id)
    assert report["error_code"] == "REPORT_WRITE_FAILED"
    assert report["original_error_code"] == "COMPLETED"
    assert report["original_exit_code"] == 0
    assert report["report_recovery_error"] is None
    assert not (run_dir / "failure.json").exists()


def test_run_worker_report_recovery_failure_writes_full_failure_contract(
    tmp_path: Path, monkeypatch
) -> None:
    stage = tmp_path / "stage"
    run_dir = stage / "20260825-000001-000001"
    cache = run_dir / "output" / "scene_index"
    model = run_dir / "model"
    run_dir.mkdir(parents=True)
    model.mkdir()
    monkeypatch.setattr(events_module, "EVENT_STAGE_ROOT", stage)

    snapshot = _snapshot(run_dir)
    snapshot = snapshot.__class__(
        task_id=snapshot.task_id, genre=snapshot.genre, force=True, limit=0,
        run_dir=snapshot.run_dir, cache_dir=str(cache), model_local_path=str(model),
        resource_limits={}, cancel_flag=snapshot.cancel_flag,
    )

    class FakeSceneSearch:
        embedding_model_path = model
        _formal_cache = cache

        def __init__(self, genre, resource_guard=None, cache_dir=None, cache_root=None):
            self.genre = genre

        def build_index(self, **kwargs):
            cache.mkdir(parents=True, exist_ok=True)
            (cache / "manifest.json").write_text(
                json.dumps({"n_books": 1, "n_scenes": 1}), encoding="utf-8"
            )
            return 1

    monkeypatch.setattr(worker_module, "SceneSearch", FakeSceneSearch)

    def fail_primary(self, report):
        raise OSError()

    def fail_recovery(self, report):
        raise OSError()

    monkeypatch.setattr(EventWriter, "write_report", fail_primary)
    monkeypatch.setattr(EventWriter, "write_report_recovery", fail_recovery)

    result = worker_module._run_worker(snapshot, run_dir)

    assert result == EXIT_CODES["REPORT_WRITE_FAILED"]
    failure = read_failure(run_dir, snapshot.task_id)
    assert set(failure) == set(events_module.REPORT_FIELDS)
    assert failure["status"] == "FAILED"
    assert failure["error_code"] == "REPORT_WRITE_FAILED"
    assert failure["original_error_code"] == "COMPLETED"
    assert failure["original_exit_code"] == 0
    assert failure["report_write_error"] == "OSError"
    assert failure["report_recovery_error"] == "OSError"
    assert failure["events_path"] == (run_dir / "events.jsonl").as_posix()
    assert not (run_dir / "report.json").exists()


def test_run_worker_report_recovery_false_is_structured_as_unpersisted(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    stage = tmp_path / "stage"
    run_dir = stage / "20260825-000001-000001"
    cache = run_dir / "output" / "scene_index"
    model = run_dir / "model"
    run_dir.mkdir(parents=True)
    model.mkdir()
    monkeypatch.setattr(events_module, "EVENT_STAGE_ROOT", stage)

    snapshot = _snapshot(run_dir)
    snapshot = snapshot.__class__(
        task_id=snapshot.task_id, genre=snapshot.genre, force=True, limit=0,
        run_dir=snapshot.run_dir, cache_dir=str(cache), model_local_path=str(model),
        resource_limits={}, cancel_flag=snapshot.cancel_flag,
    )

    class FakeSceneSearch:
        embedding_model_path = model
        _formal_cache = cache

        def __init__(self, genre, resource_guard=None, cache_dir=None, cache_root=None):
            self.genre = genre

        def build_index(self, **kwargs):
            cache.mkdir(parents=True, exist_ok=True)
            (cache / "manifest.json").write_text(
                json.dumps({"n_books": 1, "n_scenes": 1}), encoding="utf-8"
            )
            return 1

    monkeypatch.setattr(worker_module, "SceneSearch", FakeSceneSearch)
    monkeypatch.setattr(
        EventWriter, "write_report", lambda self, report: (_ for _ in ()).throw(OSError())
    )
    monkeypatch.setattr(EventWriter, "write_report_recovery", lambda self, report: False)
    monkeypatch.setattr(
        worker_module, "_write_failure_artifact", lambda run_dir, payload, expected_task_id: False
    )

    result = worker_module._run_worker(snapshot, run_dir)

    assert result == EXIT_CODES["REPORT_WRITE_FAILED"]
    output = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert output["original_error_code"] == "COMPLETED"
    assert output["report_recovery_error"] == "report recovery 未写入"
    assert output["persistence_status"] == "UNPERSISTED"
    assert output["failure_artifact_written"] is False


def test_run_worker_raw_failure_recovery_false_persists_failure_contract(
    tmp_path: Path, monkeypatch
) -> None:
    stage = tmp_path / "stage"
    run_dir = stage / "20260825-000001-000001"
    cache = run_dir / "output" / "scene_index"
    model = run_dir / "model"
    run_dir.mkdir(parents=True)
    model.mkdir()
    monkeypatch.setattr(events_module, "EVENT_STAGE_ROOT", stage)

    snapshot = _snapshot(run_dir)
    snapshot = snapshot.__class__(
        task_id=snapshot.task_id, genre=snapshot.genre, force=True, limit=0,
        run_dir=snapshot.run_dir, cache_dir=str(cache), model_local_path=str(model),
        resource_limits={}, cancel_flag=snapshot.cancel_flag,
    )

    class FakeSceneSearch:
        embedding_model_path = model
        _formal_cache = cache

        def __init__(self, genre, resource_guard=None, cache_dir=None, cache_root=None):
            self.genre = genre

        def build_index(self, **kwargs):
            raise WorkerStop("MODEL_ERROR", "injected model failure")

    monkeypatch.setattr(worker_module, "SceneSearch", FakeSceneSearch)
    monkeypatch.setattr(
        EventWriter, "write_report", lambda self, report: (_ for _ in ()).throw(OSError())
    )
    monkeypatch.setattr(EventWriter, "write_report_recovery", lambda self, report: False)

    result = worker_module._run_worker(snapshot, run_dir)

    assert result == EXIT_CODES["REPORT_WRITE_FAILED"]
    failure = read_failure(run_dir, snapshot.task_id)
    assert failure["original_error_code"] == "MODEL_ERROR"
    assert failure["original_exit_code"] == EXIT_CODES["MODEL_ERROR"]
    assert failure["report_write_error"] == "OSError"
    assert failure["report_recovery_error"] == "report recovery 未写入"


def test_failure_artifact_rejects_reparse_paths(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(
        json.dumps({
            "schema_version": 1,
            "task_id": "task-1",
            "status": "COMPLETED",
            "error_code": None,
            "events_path": str(run_dir / "events.jsonl"),
        }),
        encoding="utf-8",
    )
    event_base = {
        "task_id": "task-1", "timestamp": "2026-08-25T00:00:00+00:00",
        "n_done": 0, "n_total": 0, "progress": None, "rss_mb": None,
        "sys_mem_available_gb": None, "disk_free_gb": None, "gpu_temp": None,
        "gpu_util": None, "vram_used_mb": None, "message": "", "error_code": None,
    }
    events = [
        dict(event_base, phase="preflight", event_type="started"),
        dict(event_base, phase="cleanup", event_type="completed"),
    ]
    (run_dir / "events.jsonl").write_text(
        "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in events),
        encoding="utf-8",
    )
    payload = {
        "task_id": "task-1", "status": "FAILED", "error_code": "REPORT_WRITE_FAILED",
        "started_at": "2026-08-25T00:00:00+00:00",
        "finished_at": "2026-08-25T00:00:01+00:00", "duration_seconds": 1.0,
        "n_books": None, "n_scenes": None, "peak_rss_mb": None,
        "peak_vram_mb": None, "manifest_path": str(run_dir / "manifest.json"),
        "events_path": str(run_dir / "events.jsonl"), "worker_exit_code": 10,
        "cleanup_error": None, "original_error_code": "COMPLETED",
        "original_exit_code": 0, "report_write_error": "OSError",
        "report_recovery_error": "recovery failed",
    }
    calls = []

    def record(path):
        calls.append(path.name)

    monkeypatch.setattr(worker_module, "_reject_reparse", record)
    wrong_task = dict(payload, task_id="other-task")
    assert not worker_module._write_failure_artifact(run_dir, wrong_task, "task-1")
    calls.clear()
    assert worker_module._write_failure_artifact(run_dir, payload, "task-1")
    assert calls.count("run") == 1
    assert calls.count("failure.json") == 3


def test_publish_failure_restores_all_formal_artifacts(tmp_path: Path, monkeypatch) -> None:
    cache = tmp_path / "scene_index"
    staging = tmp_path / ".scene_index.staging"
    backup = tmp_path / "run" / "backup"
    cache.mkdir()
    staging.mkdir()
    names = ("bm25_index.pkl", "bge_embeddings.npy", "metadata.json", "manifest.json")
    for name in names:
        (cache / name).write_text(f"old:{name}", encoding="utf-8")
        (staging / name).write_text(f"new:{name}", encoding="utf-8")

    real_replace = scene_search_module.os.replace
    calls = {"count": 0}

    def fail_second(source, target):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("injected publish failure")
        return real_replace(source, target)

    monkeypatch.setattr(scene_search_module.os, "replace", fail_second)
    with pytest.raises(OSError, match="injected publish failure"):
        scene_search_module._publish_staged_artifacts(
            staging, cache, tmp_path, backup_dir=backup
        )

    assert all(
        (cache / name).read_text(encoding="utf-8") == f"old:{name}"
        for name in names
    )
    assert not backup.exists()


def test_publish_backup_cleanup_failure_is_structured(tmp_path: Path, monkeypatch) -> None:
    cache = tmp_path / "scene_index"
    staging = tmp_path / ".scene_index.staging"
    backup = tmp_path / "run" / "backup"
    cache.mkdir()
    staging.mkdir()
    names = ("bm25_index.pkl", "bge_embeddings.npy", "metadata.json", "manifest.json")
    for name in names:
        (cache / name).write_text(f"old:{name}", encoding="utf-8")
        (staging / name).write_text(f"new:{name}", encoding="utf-8")

    real_replace = scene_search_module.os.replace
    real_rmtree = scene_search_module.shutil.rmtree
    calls = {"replace": 0}

    def fail_second(source, target):
        calls["replace"] += 1
        if calls["replace"] == 2:
            raise OSError("injected publish failure")
        return real_replace(source, target)

    def fail_backup_cleanup(path):
        if Path(path) == backup:
            raise OSError("injected backup cleanup failure")
        return real_rmtree(path)

    monkeypatch.setattr(scene_search_module.os, "replace", fail_second)
    monkeypatch.setattr(scene_search_module.shutil, "rmtree", fail_backup_cleanup)
    with pytest.raises(scene_search_module.IndexPublishRollbackError, match="备份清理失败"):
        scene_search_module._publish_staged_artifacts(
            staging, cache, tmp_path, backup_dir=backup
        )


def test_publish_rollback_failure_preserves_backup(tmp_path: Path, monkeypatch) -> None:
    cache = tmp_path / "scene_index"
    staging = tmp_path / ".scene_index.staging"
    backup = tmp_path / "run" / "backup"
    cache.mkdir()
    staging.mkdir()
    names = ("bm25_index.pkl", "bge_embeddings.npy", "metadata.json", "manifest.json")
    for name in names:
        (cache / name).write_text(f"old:{name}", encoding="utf-8")
        (staging / name).write_text(f"new:{name}", encoding="utf-8")

    real_replace = scene_search_module.os.replace
    calls = {"count": 0}

    def fail_publish_and_rollback(source, target):
        calls["count"] += 1
        if calls["count"] in {2, 3}:
            raise OSError("injected publish or rollback failure")
        return real_replace(source, target)

    monkeypatch.setattr(scene_search_module.os, "replace", fail_publish_and_rollback)
    with pytest.raises(scene_search_module.IndexPublishRollbackError, match="备份保留于"):
        scene_search_module._publish_staged_artifacts(
            staging, cache, tmp_path, backup_dir=backup
        )
    assert backup.is_dir()
