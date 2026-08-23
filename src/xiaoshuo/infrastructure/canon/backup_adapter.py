"""Verified filesystem backup primitive; it is deliberately not a transaction manager."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import uuid
from pathlib import Path

from xiaoshuo.infra.config_manager import get_config


class BackupError(RuntimeError):
    """A backup target is unsafe or cannot be verified."""


_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _production_root() -> Path:
    try:
        return Path(get_config()["canon_mvp"]["backups_dir"])
    except (KeyError, TypeError) as exc:
        raise BackupError("canon_mvp.backups_dir is required") from exc


def _validate_production_root(root: Path) -> None:
    if root.resolve() != _production_root().resolve():
        raise BackupError("unapproved backup root")


def _production_projection_root() -> Path:
    try:
        return Path(get_config()["canon_mvp"]["projection_dir"])
    except (KeyError, TypeError) as exc:
        raise BackupError("canon_mvp.projection_dir is required") from exc


class ProjectionBackupAdapter:
    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root is not None else _production_root()
        _validate_production_root(self.root)

    def create(self, live: Path | str, name: str) -> Path:
        source = Path(live)
        target = self.root / name
        if source.resolve() != _production_projection_root().resolve():
            raise BackupError("unapproved projection source")
        if not _NAME.fullmatch(name) or target.exists() or not source.is_dir():
            raise BackupError("invalid backup target")
        self.root.mkdir(parents=True, exist_ok=True)
        staging = self.root / (".stage-" + name + "-" + uuid.uuid4().hex)
        try:
            # Lock and transient staging artifacts are coordination metadata,
            # not projection content and must never become a backup payload.
            shutil.copytree(
                source,
                staging,
                ignore=shutil.ignore_patterns(".projection.lock", ".stage-*")
            )
            if self._tree_digest(source) != self._tree_digest(staging):
                raise BackupError("backup verification failed")
            os.replace(staging, target)
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise
        return target

    @staticmethod
    def _tree_digest(root: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(root.rglob("*")):
            if path.name == ".projection.lock" or path.name.startswith(".stage-"):
                continue
            if path.is_file():
                digest.update(path.relative_to(root).as_posix().encode("utf-8"))
                digest.update(path.read_bytes())
        return digest.hexdigest()
