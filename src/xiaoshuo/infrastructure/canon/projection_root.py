"""Stage deterministic projection files without mutating a live projection."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from .canonical_bundle import CanonicalBundle
from .projection_activation import ProjectionActivationError, ProjectionActivationReader
from .projection_lock import ProjectionLock
from xiaoshuo.infra.config_manager import get_config


class ProjectionError(RuntimeError):
    """A projection root operation is unsafe or fails target verification."""


_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _valid_name(value: str) -> bool:
    return bool(_NAME.fullmatch(value)) and value not in {".", ".."}


def _production_root() -> Path:
    try:
        return Path(get_config()["canon_mvp"]["projection_dir"])
    except (KeyError, TypeError) as exc:
        raise ProjectionError("canon_mvp.projection_dir is required") from exc


def _validate_production_root(root: Path) -> None:
    if root.resolve() != _production_root().resolve():
        raise ProjectionError("unapproved projection root")


class ProjectionRoot:
    def __init__(self, root: Path | str | None = None, *, artifact_ref_resolver: Callable | None = None) -> None:
        self.root = Path(root) if root is not None else _production_root()
        self._artifact_ref_resolver = artifact_ref_resolver
        _validate_production_root(self.root)

    def stage(self, bundle: CanonicalBundle, name: str) -> Path:
        raise ProjectionError("projection staging is disabled during C4-PRE")

    def acquire_lock(self) -> ProjectionLock:
        return ProjectionLock(self.root, artifact_ref_resolver=self._artifact_ref_resolver).acquire()

    def lock(self) -> ProjectionLock:
        return ProjectionLock(self.root, artifact_ref_resolver=self._artifact_ref_resolver)

    def root_hash(self) -> str | None:
        try:
            return ProjectionActivationReader(
                self.root, artifact_ref_resolver=self._artifact_ref_resolver
            ).read_for_project(
                self._project_id_from_activation()
            ).bundle_content_hash
        except ProjectionActivationError as exc:
            raise ProjectionError("projection activation is not trusted") from exc

    def promote(self, stage: Path, *, expected_manifest_hash: str) -> None:
        """C4-PRE never exposes live projection replacement."""
        raise ProjectionError("projection promotion is disabled before C4a re-authorization")

    def discard(self, stage: Path) -> None:
        """C4-PRE never deletes staging or projection facts."""
        raise ProjectionError("projection discard is disabled during C4-PRE")

    @staticmethod
    def _digest(root: Path) -> str:
        bundle = CanonicalBundle(
            1, (root / "manifest.json").read_bytes(), (root / "world.md").read_bytes()
        )
        return bundle.content_hash()

    @staticmethod
    def _manifest_hash(root: Path) -> str:
        try:
            bundle = CanonicalBundle(1, (root / "manifest.json").read_bytes(), (root / "world.md").read_bytes())
        except Exception as exc:
            raise ProjectionError("staging projection is invalid") from exc
        return bundle.manifest_hash

    def _require_activation(self) -> None:
        try:
            marker = self.root / "activation.marker"
            pointer = self.root / "current.pointer"
            if not self.root.is_dir() or not marker.is_file() or not pointer.is_file():
                raise ProjectionError("projection activation is missing")
            ProjectionActivationReader(self.root, artifact_ref_resolver=self._artifact_ref_resolver).read_for_project(
                self._project_id_from_activation()
            )
        except (ProjectionActivationError, ProjectionError) as exc:
            if isinstance(exc, ProjectionError):
                raise
            raise ProjectionError("projection activation is not trusted") from exc

    def _project_id_from_activation(self) -> str:
        try:
            import json

            return json.loads((self.root / "current.pointer").read_text(encoding="utf-8"))["project_id"]
        except Exception as exc:
            raise ProjectionError("projection activation is invalid") from exc
