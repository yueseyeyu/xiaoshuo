"""OS-visible fail-closed lock for the local projection root."""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Callable

from .projection_activation import ProjectionActivationError, ProjectionActivationReader


class ProjectionLockError(RuntimeError):
    """The projection lock cannot be trusted or acquired."""


class ProjectionLock:
    """Atomic same-root lock artifact; stale locks are never auto-reclaimed."""

    def __init__(self, root: Path | str, name: str = ".projection.lock", *, artifact_ref_resolver: Callable | None = None) -> None:
        if name != ".projection.lock":
            raise ProjectionLockError("projection lock name is fixed")
        self.root = Path(root)
        self.path = self.root / ".projection.lock"
        self._artifact_ref_resolver = artifact_ref_resolver
        self._token: str | None = None

    def acquire(self) -> "ProjectionLock":
        if self._token is not None:
            raise ProjectionLockError("projection lock is already held")
        if not self.root.is_dir():
            raise ProjectionLockError("projection root is missing")
        try:
            import json

            pointer = json.loads((self.root / "current.pointer").read_bytes().decode("utf-8"))
            if not isinstance(pointer, dict):
                raise ProjectionLockError("projection pointer is invalid")
            project_id = pointer["project_id"]
            ProjectionActivationReader(self.root, artifact_ref_resolver=self._artifact_ref_resolver).read_for_project(project_id)
        except (OSError, UnicodeDecodeError, KeyError, IndexError, TypeError, ValueError, ProjectionActivationError, ProjectionLockError) as exc:
            raise ProjectionLockError("projection activation is not trusted") from exc
        try:
            token = secrets.token_hex(16)
            fd = os.open(str(self.path), os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            try:
                os.write(fd, token.encode("ascii"))
            finally:
                os.close(fd)
        except FileExistsError as exc:
            raise ProjectionLockError("projection lock is occupied or stale") from exc
        except OSError as exc:
            raise ProjectionLockError("projection lock cannot be acquired") from exc
        self._token = token
        return self

    def release(self) -> None:
        if self._token is None:
            raise ProjectionLockError("projection lock is not held")
        try:
            current = self.path.read_text(encoding="ascii")
            if current != self._token:
                raise ProjectionLockError("projection lock ownership is not trusted")
            self.path.unlink()
        except ProjectionLockError:
            raise
        except (OSError, UnicodeDecodeError) as exc:
            raise ProjectionLockError("projection lock release failed") from exc
        finally:
            self._token = None

    def __enter__(self) -> "ProjectionLock":
        return self.acquire()

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.release()
        return False
