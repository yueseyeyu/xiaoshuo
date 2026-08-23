from __future__ import annotations

from pathlib import Path

import pytest

from xiaoshuo.infrastructure.canon.projection_activation import (
    ProjectionActivationError,
    ProjectionActivationReader,
)


def test_missing_activation_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "xiaoshuo.infrastructure.canon.projection_activation._production_root",
        lambda: tmp_path / "projection",
    )
    with pytest.raises(ProjectionActivationError):
        ProjectionActivationReader(tmp_path / "projection").read_for_project("p")


def test_reader_rejects_unapproved_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    configured = tmp_path / "configured"
    monkeypatch.setattr(
        "xiaoshuo.infrastructure.canon.projection_activation._production_root",
        lambda: configured,
    )
    with pytest.raises(ProjectionActivationError):
        ProjectionActivationReader(tmp_path / "other")
