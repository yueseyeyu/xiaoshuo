"""只读消费 MPV-02B 样本索引的评测入口。"""

from __future__ import annotations

import re
import json
from pathlib import Path
from typing import Any

from .scene_search import (
    IndexNotReadyError,
    SceneSearch,
    _reject_reparse_ancestors,
    _reject_reparse_file,
)


_RUN_ID_RE = re.compile(r"^\d{8}-\d{6}-\d{6}$")


class SampleIndexReader:
    """读取显式样本 run；该类不被生产 API 使用。"""

    def __init__(self, genre: str, sample_cache: Path | str, run_dir: Path | str):
        self.genre = genre
        self.run_dir = Path(run_dir).absolute()
        self.sample_cache = Path(sample_cache).absolute()
        self._validate_paths()
        self._validate_run_envelope()
        self._engine = SceneSearch(
            genre,
            cache_dir=self.sample_cache,
            cache_root=self.run_dir,
        )

    def _validate_paths(self) -> None:
        if self.run_dir.drive.upper() != "D:" or not _RUN_ID_RE.fullmatch(self.run_dir.name):
            raise IndexNotReadyError("样本评测 run 必须是 D 盘合法 run 目录")
        expected = self.run_dir / "output" / "scene_index.sample"
        if self.sample_cache != expected.absolute():
            raise IndexNotReadyError("样本评测必须绑定当前 run/output/scene_index.sample")
        _reject_reparse_ancestors(self.run_dir, "样本评测 run")
        if not self.sample_cache.is_dir():
            raise IndexNotReadyError("样本索引目录不存在")
        _reject_reparse_ancestors(self.sample_cache, "样本索引目录")

    @staticmethod
    def _read_object(path: Path, label: str) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise IndexNotReadyError(f"{label} 无法读取") from exc
        if not isinstance(value, dict):
            raise IndexNotReadyError(f"{label} 根节点必须是对象")
        return value

    def _validate_run_envelope(self) -> None:
        def same_path(value: Any, expected: Path) -> bool:
            return (
                isinstance(value, str)
                and Path(value).absolute().resolve(strict=False)
                == expected.absolute().resolve(strict=False)
            )

        run_manifest_path = self.run_dir / "manifest.json"
        report_path = self.run_dir / "report.json"
        _reject_reparse_file(run_manifest_path, self.run_dir, "样本 run manifest")
        _reject_reparse_file(report_path, self.run_dir, "样本 run report")
        run_manifest = self._read_object(run_manifest_path, "样本 run manifest")
        report = self._read_object(report_path, "样本 run report")
        task_id = run_manifest.get("task_id")
        cache_manifest = run_manifest.get("cache_manifest_path")
        events_path = run_manifest.get("events_path")
        if (
            run_manifest.get("status") != "COMPLETED"
            or not isinstance(task_id, str)
            or not task_id
            or run_manifest.get("genre") != self.genre
            or not isinstance(run_manifest.get("build_limit"), int)
            or isinstance(run_manifest.get("build_limit"), bool)
            or run_manifest["build_limit"] <= 0
            or not isinstance(cache_manifest, str)
            or not same_path(cache_manifest, self.sample_cache / "manifest.json")
            or not same_path(events_path, self.run_dir / "events.jsonl")
        ):
            raise IndexNotReadyError("样本 run manifest 身份或状态不一致")
        if (
            report.get("status") != "COMPLETED"
            or report.get("task_id") != task_id
            or report.get("error_code") is not None
            or report.get("worker_exit_code") != 0
            or not same_path(report.get("manifest_path"), run_manifest_path)
            or not same_path(report.get("events_path"), self.run_dir / "events.jsonl")
        ):
            raise IndexNotReadyError("样本 run report 身份或状态不一致")

    def search(self, query: str, top_k: int = 10) -> list[dict[str, Any]]:
        """在样本快照上查询；结果不代表生产查询结果。"""
        with self._engine._state_lock:
            with self._engine._filesystem_lock():
                if self._engine._loaded_build_limit is None:
                    self._engine._load_cache_unlocked(expected_limit=None)
                if not isinstance(self._engine._loaded_build_limit, int) or self._engine._loaded_build_limit <= 0:
                    raise IndexNotReadyError("样本评测只接受 build_limit>0 的索引")
                return self._engine._search_loaded(query, top_k)
