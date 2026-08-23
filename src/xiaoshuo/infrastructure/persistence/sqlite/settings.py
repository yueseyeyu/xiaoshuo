"""Immutable dataclass for SQLite connection and backup settings."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SQLitePersistenceSettings:
    """Immutable settings. Caller must explicitly supply db_path and busy_timeout_ms."""

    db_path: Path | str
    busy_timeout_ms: int
    backup_dir: Path | str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.db_path, str):
            object.__setattr__(self, "db_path", Path(self.db_path))
        if isinstance(self.backup_dir, str):
            object.__setattr__(self, "backup_dir", Path(self.backup_dir))
        if (
            not isinstance(self.busy_timeout_ms, int)
            or self.busy_timeout_ms <= 0
            or not (0 < self.busy_timeout_ms < 2**31)
        ):
            raise ValueError(
                f"busy_timeout_ms must be a positive finite integer, got {self.busy_timeout_ms!r}"
            )
