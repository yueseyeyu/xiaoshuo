"""Independent C4a follow-on projection lease.

Unlike the C4b bootstrap lease this lock never creates a projection root and
never reclaims a stale lease.  It is usable only after the existing activation
has been validated by the C4a composition root.
"""

from __future__ import annotations

import os
from pathlib import Path
import secrets

from xiaoshuo import PROJECT_ROOT


class C4aProjectionLockError(RuntimeError):
    """The C4a projection lease cannot be safely acquired or released."""


class C4aProjectionLockConflict(C4aProjectionLockError):
    """Another process owns the C4a follow-on lease."""


def _raw_path_is_reparse(path: Path) -> bool:
    try:
        attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    except OSError as exc:
        raise C4aProjectionLockError("projection path cannot be inspected") from exc
    return path.is_symlink() or bool(attributes & 0x400)


def preflight_c4a_projection_root(
    root: Path | str,
    *,
    workspace_root: Path | str = PROJECT_ROOT,
    enforce_persistent_d_drive: bool = True,
) -> Path:
    """Validate a follow-on root without resolving away raw reparse evidence."""
    raw = Path(root)
    workspace = Path(workspace_root).resolve()
    if raw.anchor.upper() != "D:\\" and enforce_persistent_d_drive:
        raise C4aProjectionLockError("C4a projection root must be on D:")
    try:
        resolved = raw.resolve(strict=False)
        if resolved == workspace or workspace in resolved.parents:
            raise C4aProjectionLockError("C4a projection root must be outside the workspace")
        if enforce_persistent_d_drive and str(resolved).lower().startswith("d:\\tmp\\"):
            raise C4aProjectionLockError("C4a projection root must not be under D:\\tmp")
        if "assets" in {part.lower() for part in resolved.parts} and "canon" in {
            part.lower() for part in resolved.parts
        }:
            raise C4aProjectionLockError("C4a projection root must not be the Canon seed root")
    except OSError as exc:
        raise C4aProjectionLockError("C4a projection root cannot be resolved") from exc

    if not raw.exists() or not raw.is_dir() or _raw_path_is_reparse(raw):
        raise C4aProjectionLockError("C4a projection root must already be a real directory")
    current = raw
    while True:
        if current.exists() and _raw_path_is_reparse(current):
            raise C4aProjectionLockError("C4a projection root has a reparse ancestor")
        if current.parent == current:
            break
        current = current.parent
    if not (raw / "current.pointer").is_file() or not (raw / "activation.marker").is_file():
        raise C4aProjectionLockError("C4a follow-on root has no complete activation")
    if not (raw / "versions").is_dir() or _raw_path_is_reparse(raw / "versions"):
        raise C4aProjectionLockError("C4a version root is unsafe")
    return resolved


class C4aProjectionCommitLock:
    """A non-reclaiming, same-directory C4a projection lease."""

    def __init__(
        self,
        projection_root: Path | str,
        *,
        workspace_root: Path | str = PROJECT_ROOT,
        enforce_persistent_d_drive: bool = True,
        lock_path: Path | str | None = None,
    ) -> None:
        self.projection_root = preflight_c4a_projection_root(
            projection_root,
            workspace_root=workspace_root,
            enforce_persistent_d_drive=enforce_persistent_d_drive,
        )
        expected = self.projection_root.parent / ".c4a-commit.lock"
        if enforce_persistent_d_drive and lock_path is not None and Path(lock_path) != expected:
            raise C4aProjectionLockError("production C4a lock path is fixed to the projection parent")
        self.lock_path = expected if lock_path is None else Path(lock_path)
        if self.lock_path.parent.resolve() != self.projection_root.parent.resolve():
            raise C4aProjectionLockError("C4a lock path escapes the projection parent")
        self._token: str | None = None

    @property
    def held(self) -> bool:
        return self._token is not None and self.lock_path.is_file()

    def acquire(self) -> None:
        if self.held:
            raise C4aProjectionLockError("C4a lock is already held by this object")
        if not self.lock_path.parent.is_dir():
            raise C4aProjectionLockError("C4a lock parent is missing")
        token = secrets.token_hex(16).encode("ascii")
        try:
            with self.lock_path.open("xb") as handle:
                handle.write(token)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise C4aProjectionLockConflict("C4a projection lock is occupied") from exc
        except OSError as exc:
            raise C4aProjectionLockError("C4a projection lock cannot be acquired") from exc
        self._token = token.decode("ascii")

    def release(self) -> None:
        if self._token is None:
            return
        try:
            if not self.lock_path.is_file() or self.lock_path.read_text(encoding="ascii") != self._token:
                raise C4aProjectionLockError("C4a lock ownership is uncertain")
            self.lock_path.unlink()
        except C4aProjectionLockError:
            raise
        except OSError as exc:
            raise C4aProjectionLockError("C4a projection lock release is uncertain") from exc
        finally:
            self._token = None


C4aCommitLock = C4aProjectionCommitLock
