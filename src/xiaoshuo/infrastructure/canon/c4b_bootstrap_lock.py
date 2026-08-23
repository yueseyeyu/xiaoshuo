"""C4b-only bootstrap lock and activation-root safety preflight."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from xiaoshuo import PROJECT_ROOT


class BootstrapLockError(RuntimeError):
    """The C4b bootstrap lock or root preflight cannot be trusted."""


class BootstrapLockConflict(BootstrapLockError):
    """A different process already owns the non-reclaimable bootstrap lock."""


def _resolved(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except OSError as exc:
        raise BootstrapLockError("activation root cannot be resolved") from exc


def _is_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        return bool(path.stat().st_file_attributes & 0x400)
    except (AttributeError, OSError):
        return False


def _check_existing_components(path: Path) -> None:
    current = path
    while True:
        if current.exists() and _is_reparse(current):
            raise BootstrapLockError("activation root contains a symlink or reparse point")
        if current.parent == current:
            break
        current = current.parent


def _check_raw_existing_components(path: Path) -> None:
    """Inspect raw path components before resolution can hide reparse points."""
    current = path
    while True:
        try:
            exists = current.exists() or current.is_symlink()
        except OSError as exc:
            raise BootstrapLockError("activation root cannot be inspected") from exc
        if exists and _is_reparse(current):
            raise BootstrapLockError("activation root contains a symlink or reparse point")
        if current.parent == current:
            break
        current = current.parent


def _under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class ActivationRootPreflight:
    payload_root: Path
    projection_root: Path


def preflight_activation_roots(
    payload_root: Path | str,
    projection_root: Path | str,
    *,
    workspace_root: Path | str | None = None,
    enforce_persistent_d_drive: bool = True,
) -> ActivationRootPreflight:
    """Validate both roots before any seed, payload, SQLite, or file write."""
    raw_payload = Path(payload_root)
    raw_projection = Path(projection_root)
    if not raw_payload.is_absolute() or not raw_projection.is_absolute():
        raise BootstrapLockError("activation roots must be absolute")
    _check_raw_existing_components(raw_payload)
    _check_raw_existing_components(raw_projection)
    payload = _resolved(raw_payload)
    projection = _resolved(raw_projection)
    workspace = _resolved(Path(workspace_root) if workspace_root is not None else PROJECT_ROOT)
    tmp_root = _resolved(Path(r"D:\tmp"))
    canon_root = _resolved(PROJECT_ROOT / "assets" / "canon")

    if enforce_persistent_d_drive:
        if payload.drive.upper() != "D:" or projection.drive.upper() != "D:":
            raise BootstrapLockError("activation roots must be on the D drive")
        if _under(payload, tmp_root) or _under(projection, tmp_root):
            raise BootstrapLockError("activation roots must not be under D:\\tmp")
    if _under(payload, workspace) or _under(projection, workspace):
        raise BootstrapLockError("activation roots must be outside the Git workspace")
    if _under(payload, canon_root) or _under(projection, canon_root):
        raise BootstrapLockError("activation roots must be outside assets/canon")
    if payload == projection or _under(payload, projection) or _under(projection, payload):
        raise BootstrapLockError("payload and projection roots must not overlap")
    _check_existing_components(payload)
    _check_existing_components(projection)
    if payload.parent == payload or projection.parent == projection:
        raise BootstrapLockError("activation root parent is invalid")
    return ActivationRootPreflight(payload_root=payload, projection_root=projection)


class C4bBootstrapLock:
    """An atomic, non-reclaimable lock acquired before any C4b write."""

    def __init__(
        self,
        payload_root: Path | str,
        projection_root: Path | str,
        *,
        lock_path: Path | str | None = None,
        workspace_root: Path | str | None = None,
        enforce_persistent_d_drive: bool = True,
    ) -> None:
        roots = preflight_activation_roots(
            payload_root,
            projection_root,
            workspace_root=workspace_root,
            enforce_persistent_d_drive=enforce_persistent_d_drive,
        )
        self.payload_root = roots.payload_root
        self.projection_root = roots.projection_root
        requested_lock = (
            Path(lock_path)
            if lock_path is not None
            else self.projection_root.parent / ".c4b-bootstrap.lock"
        )
        if not requested_lock.is_absolute():
            raise BootstrapLockError("bootstrap lock path must be absolute")
        _check_raw_existing_components(requested_lock)
        requested_lock = _resolved(requested_lock)
        expected_lock = _resolved(self.projection_root.parent / ".c4b-bootstrap.lock")
        if enforce_persistent_d_drive and requested_lock != expected_lock:
            raise BootstrapLockError("production bootstrap lock path is fixed to projection root parent")
        self.path = requested_lock
        if self.path.name != ".c4b-bootstrap.lock":
            raise BootstrapLockError("C4b bootstrap lock name is fixed")
        if not self.path.parent.is_dir():
            raise BootstrapLockError("bootstrap lock parent is missing")
        _check_existing_components(self.path.parent)
        if _is_reparse(self.path):
            raise BootstrapLockError("bootstrap lock path is a reparse point")
        self._token: str | None = None

    @property
    def held(self) -> bool:
        return self._token is not None

    def acquire(self) -> "C4bBootstrapLock":
        if self._token is not None:
            raise BootstrapLockError("bootstrap lock is already held")
        token = secrets.token_hex(24)
        try:
            fd = os.open(str(self.path), os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        except FileExistsError as exc:
            raise BootstrapLockConflict("bootstrap lock is occupied or stale") from exc
        except OSError as exc:
            raise BootstrapLockError("bootstrap lock cannot be acquired") from exc
        try:
            os.write(fd, token.encode("ascii"))
        except OSError as exc:
            try:
                os.close(fd)
            finally:
                try:
                    self.path.unlink()
                except OSError:
                    pass
            raise BootstrapLockError("bootstrap lock write failed") from exc
        else:
            os.close(fd)
        self._token = token
        return self

    def release(self) -> None:
        if self._token is None:
            raise BootstrapLockError("bootstrap lock is not held")
        try:
            current = self.path.read_text(encoding="ascii")
            if current != self._token:
                raise BootstrapLockError("bootstrap lock ownership is not trusted")
            self.path.unlink()
        except BootstrapLockError:
            raise
        except (OSError, UnicodeDecodeError) as exc:
            raise BootstrapLockError("bootstrap lock release failed") from exc
        finally:
            self._token = None

    def __enter__(self) -> "C4bBootstrapLock":
        return self.acquire()

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.release()
        return False


BootstrapLock = C4bBootstrapLock
