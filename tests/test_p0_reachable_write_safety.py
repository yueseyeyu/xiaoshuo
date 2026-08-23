# -*- coding: utf-8 -*-
"""P0-1: reachable write-path safety regression tests."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from xiaoshuo.api.routes import projects as project_routes
from xiaoshuo.api.routes import writing as writing_routes
from xiaoshuo.api.services import project_service
from xiaoshuo.api.services import world_state_service


def _project_data() -> dict:
    return {
        "id": "project-1",
        "meta": {"title": "Test", "updated_at": "old"},
        "skeleton": {"volumes": [], "chapters": []},
        "world": {"core": "old", "powers": "old"},
        "characters": [],
        "factions": [],
        "chapters": [],
        "world_state": None,
    }


UPDATE_CASES = [
    ("update_skeleton", ("project-1", {"volumes": [{"title": "V1"}], "chapters": []})),
    ("update_world", ("project-1", {"core": "new", "powers": "system"})),
    ("update_characters", ("project-1", {"characters": [{"name": "A"}]})),
    ("update_factions", ("project-1", {"factions": [{"id": "F1"}]})),
    ("update_chapter", ("project-1", 1, {"title": "Chapter 1", "content": "body"})),
]


@pytest.mark.parametrize(("function_name", "args"), UPDATE_CASES)
def test_project_update_raises_storage_error_when_safe_write_fails(
    monkeypatch: pytest.MonkeyPatch, function_name: str, args: tuple
) -> None:
    path = Mock()
    path.exists.return_value = True
    monkeypatch.setattr(project_service, "_project_path", lambda _project_id: path)
    monkeypatch.setattr(project_service, "_safe_read", lambda _path: deepcopy(_project_data()))
    monkeypatch.setattr(project_service, "_safe_write", lambda _path, _data: False)

    function = getattr(project_service, function_name)
    with pytest.raises(project_service.ProjectStorageError) as exc_info:
        function(*args)

    assert exc_info.value.code == "PROJECT_STORAGE_WRITE_FAILED"
    assert exc_info.value.project_id == "project-1"
    assert exc_info.value.operation == function_name


@pytest.mark.parametrize(("function_name", "args"), UPDATE_CASES)
def test_project_update_success_paths_remain_compatible(
    monkeypatch: pytest.MonkeyPatch, function_name: str, args: tuple
) -> None:
    path = Mock()
    path.exists.return_value = True
    stored = _project_data()

    def safe_read(_path):
        return deepcopy(stored)

    def safe_write(_path, data):
        stored.clear()
        stored.update(deepcopy(data))
        return True

    monkeypatch.setattr(project_service, "_project_path", lambda _project_id: path)
    monkeypatch.setattr(project_service, "_safe_read", safe_read)
    monkeypatch.setattr(project_service, "_safe_write", safe_write)

    result = getattr(project_service, function_name)(*args)

    assert result is not None
    if function_name == "update_chapter":
        assert result["num"] == 1
        assert result["content"] == "body"


def test_missing_world_state_returns_derived_view_without_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project_data()
    project["factions"] = [{"id": "F1", "name": "Faction"}]
    project["characters"] = [{"name": "Author", "dynamic_state": {"health": 0.8}}]
    monkeypatch.setattr(world_state_service, "get_project", lambda _project_id: project)
    save_spy = Mock(side_effect=AssertionError("read path must not persist world state"))
    monkeypatch.setattr(world_state_service, "_save_world_state", save_spy)

    result = world_state_service.get_world_state("project-1")

    assert result is not None
    assert result["chapter"] == 0
    assert result["factions_state"][0]["id"] == "F1"
    assert result["characters_state"][0]["health"] == 0.8
    save_spy.assert_not_called()
    assert project["world_state"] is None


def test_existing_world_state_is_returned_unchanged_without_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = {
        "chapter": 7,
        "regions": [{"id": "R1"}],
        "factions_state": [{"id": "F1", "stability": 0.6}],
        "characters_state": [{"name": "Author", "health": 0.8}],
        "snapshots": [],
    }
    project = _project_data()
    project["world_state"] = existing
    monkeypatch.setattr(world_state_service, "get_project", lambda _project_id: project)
    save_spy = Mock(side_effect=AssertionError("read path must not persist world state"))
    monkeypatch.setattr(world_state_service, "_save_world_state", save_spy)

    result = world_state_service.get_world_state("project-1")

    assert result == existing
    save_spy.assert_not_called()


def test_style_calibrate_is_frozen_without_instantiating_canon_extractor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    app.include_router(writing_routes.router)
    extractor = Mock(side_effect=AssertionError('CanonExtractor must not be instantiated'))
    monkeypatch.setattr(writing_routes, 'CanonExtractor', extractor, raising=False)
    monkeypatch.setattr(
        'xiaoshuo.pipeline.canon.extractor.CanonExtractor', extractor
    )

    response = TestClient(app).post(
        '/api/style/calibrate',
        json={'chapter_id': 1, 'text': 'chapter body', 'version': ''},
    )

    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'DIRECT_CANON_WRITE_DISABLED'
    extractor.assert_not_called()


API_UPDATE_CASES = [
    ("update_skeleton", "/api/projects/project-1/skeleton", {"volumes": [], "chapters": []}),
    ("update_world", "/api/projects/project-1/world", {"core": "new", "powers": ""}),
    ("update_characters", "/api/projects/project-1/characters", {"characters": []}),
    ("update_factions", "/api/projects/project-1/factions", {"factions": []}),
    ("update_chapter", "/api/projects/project-1/chapters/1", {"content": "body"}),
]


@pytest.mark.parametrize(("route_dependency", "path", "body"), API_UPDATE_CASES)
def test_project_update_api_reports_storage_failure_as_5xx(
    monkeypatch: pytest.MonkeyPatch, route_dependency: str, path: str, body: dict
) -> None:
    def fail(*_args, **_kwargs):
        raise project_service.ProjectStorageError("project-1", route_dependency)

    monkeypatch.setattr(project_routes, route_dependency, fail)
    app = FastAPI()
    app.include_router(project_routes.router)

    response = TestClient(app).put(path, json=body)

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "PROJECT_STORAGE_WRITE_FAILED"


@pytest.mark.parametrize(("route_dependency", "path", "body"), API_UPDATE_CASES)
def test_project_update_api_success_shapes_remain_available(
    monkeypatch: pytest.MonkeyPatch, route_dependency: str, path: str, body: dict
) -> None:
    successful_results = {
        "update_skeleton": {"volumes": [], "chapters": []},
        "update_world": {"core": "new", "powers": ""},
        "update_characters": {"characters": []},
        "update_factions": {"factions": []},
        "update_chapter": {"num": 1, "content": "body"},
    }
    monkeypatch.setattr(
        project_routes,
        route_dependency,
        lambda *_args, **_kwargs: successful_results[route_dependency],
    )
    app = FastAPI()
    app.include_router(project_routes.router)

    response = TestClient(app).put(path, json=body)

    assert response.status_code == 200
    assert response.json()["ok"] is True
