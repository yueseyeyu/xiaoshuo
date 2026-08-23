"""G0-A runtime composition root for the C5 witness stages.

Loading this module's runtime is read-only.  It reads the SSOT configuration,
validates path identity, and constructs the single approved local operator
context.  Database maintenance remains available only through explicit
instance methods.
"""

from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TypeVar

from xiaoshuo import PROJECT_ROOT
from xiaoshuo.application.creation.local_author_context import LocalAuthorContextImpl
from xiaoshuo.infra.config_manager import get_config
from xiaoshuo.infrastructure.persistence.sqlite.connection import get_connection
from xiaoshuo.infrastructure.persistence.sqlite.maintenance import (
    APPLICATION_ID,
    backup_database_maintenance,
    init_database,
    migrate_database,
)
from xiaoshuo.infrastructure.persistence.sqlite.migration_runner import _discover_migrations
from xiaoshuo.infrastructure.persistence.sqlite.settings import SQLitePersistenceSettings


class C5G0RuntimeError(RuntimeError):
    """Stable fail-closed error for G0-A runtime binding and maintenance."""


_EXPECTED_MIGRATION_VERSIONS = (1, 2, 3, 4, 5, 6)
_APPROVED_OPERATOR_ID = "local-author"
_OPERATOR_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_RUNTIME_CONSTRUCTION_TOKEN = object()
_MISSING_CONSTRUCTION_TOKEN = object()
_REPARSE_POINT = 0x400
_WORKSPACE_ROOT = PROJECT_ROOT.parent.resolve(strict=False)
_TMP_ROOT = Path(r"D:\tmp").resolve(strict=False)
_CANON_ASSETS_ROOT = (PROJECT_ROOT / "assets" / "canon").resolve(strict=False)

_EXPECTED_TABLES = frozenset(
    {
        "creation_schema_migration",
        "creation_artifact_ref",
        "chapter_task",
        "creation_operation",
        "creation_audit_event",
        "creation_audit_event_source_artifact_ref",
        "creation_audit_event_object_ref",
        "creation_author_decision",
        "creation_decision_consumption",
        "canon_commit_journal_v003_legacy",
        "canon_commit_receipt_v003_legacy",
        "canon_commit_journal",
        "canon_commit_receipt",
        "canon_activation_attempt",
        "canon_activation_event",
        "canon_apply_attempt",
        "canon_apply_event",
    }
)

T = TypeVar("T")


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left)) == os.path.normcase(str(right))


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _is_reparse_or_symlink(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        stat_result = path.lstat()
    except OSError as exc:
        raise C5G0RuntimeError(f"cannot inspect path attributes: {path}") from exc
    return bool(getattr(stat_result, "st_file_attributes", 0) & _REPARSE_POINT)


def _check_existing_ancestors(raw: Path) -> None:
    """Inspect raw path components before resolving the path."""
    for ancestor in (raw, *raw.parents):
        if ancestor.exists() and _is_reparse_or_symlink(ancestor):
            raise C5G0RuntimeError(f"symlink/reparse path is not allowed: {ancestor}")


def _validated_path(value: Any, label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)):
        raise C5G0RuntimeError(f"{label} must be a path string")
    raw = Path(value)
    if not raw.is_absolute():
        raise C5G0RuntimeError(f"{label} must be absolute")
    if raw.drive.upper() != "D:":
        raise C5G0RuntimeError(f"{label} must be on the D drive")

    # This check intentionally happens before resolve(); otherwise a reparse
    # component could disappear from the identity being validated.
    _check_existing_ancestors(raw)
    resolved = raw.resolve(strict=False)
    if _is_within(resolved, _WORKSPACE_ROOT) or _same_path(resolved, _WORKSPACE_ROOT):
        raise C5G0RuntimeError(f"{label} must be outside the project workspace")
    if _is_within(resolved, _TMP_ROOT) or _same_path(resolved, _TMP_ROOT):
        raise C5G0RuntimeError(f"{label} must not be under D:\\tmp")
    if _is_within(resolved, _CANON_ASSETS_ROOT) or _same_path(
        resolved, _CANON_ASSETS_ROOT
    ):
        raise C5G0RuntimeError(f"{label} must not be under assets\\canon")
    return resolved


def _validate_directory_path(path: Path, label: str) -> None:
    if path.exists() and not path.is_dir():
        raise C5G0RuntimeError(f"{label} must be a directory when present")


def _validate_file_path(path: Path, label: str) -> None:
    if path.exists() and not path.is_file():
        raise C5G0RuntimeError(f"{label} must be an ordinary file when present")


def _validate_paths(section: dict[str, Any]) -> tuple[Path, Path, tuple[Path, ...]]:
    root = _validated_path(section.get("root"), "canon_mvp.root")
    db = _validated_path(section.get("creation_db_path"), "canon_mvp.creation_db_path")
    children = tuple(
        _validated_path(section.get(key), f"canon_mvp.{key}")
        for key in ("payloads_dir", "projection_dir", "backups_dir", "exports_dir")
    )

    if not _same_path(db.parent, root):
        raise C5G0RuntimeError("creation_db_path must be directly under canon_mvp.root")
    if any(not _same_path(child.parent, root) for child in children):
        raise C5G0RuntimeError("Canon roots must be direct children of canon_mvp.root")
    all_paths = (root, db, *children)
    if len({os.path.normcase(str(path)) for path in all_paths}) != len(all_paths):
        raise C5G0RuntimeError("Canon paths must be distinct")

    _validate_directory_path(root, "canon_mvp.root")
    _validate_file_path(db, "canon_mvp.creation_db_path")
    for child in children:
        _validate_directory_path(child, "Canon root")

    for sidecar in (Path(f"{db}-wal"), Path(f"{db}-shm")):
        _check_existing_ancestors(sidecar)
        if sidecar.exists() and (_is_reparse_or_symlink(sidecar) or not sidecar.is_file()):
            raise C5G0RuntimeError(f"unsafe SQLite sidecar: {sidecar}")
    return root, db, children


def _validate_config_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise C5G0RuntimeError(f"{label} must be a non-empty string without NUL")
    return value


def _validate_section(
    config: Any,
) -> tuple[SQLitePersistenceSettings, Path, tuple[Path, ...], LocalAuthorContextImpl]:
    if not isinstance(config, dict) or not isinstance(config.get("canon_mvp"), dict):
        raise C5G0RuntimeError("canon_mvp configuration section is required")
    section = config["canon_mvp"]
    timeout = section.get("creation_busy_timeout_ms")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not (0 < timeout < 2**31):
        raise C5G0RuntimeError("creation_busy_timeout_ms must be a positive 32-bit integer")
    operator_id = _validate_config_string(section.get("local_operator_id"), "local_operator_id")
    if operator_id != _APPROVED_OPERATOR_ID or _OPERATOR_ID_PATTERN.fullmatch(operator_id) is None:
        raise C5G0RuntimeError("local_operator_id is not the approved runtime identity")

    root, db, children = _validate_paths(section)
    settings = SQLitePersistenceSettings(
        db_path=db,
        busy_timeout_ms=timeout,
        backup_dir=children[2],
    )
    try:
        author_context = LocalAuthorContextImpl(_author_id=operator_id)
    except Exception as exc:
        raise C5G0RuntimeError("failed to construct LocalAuthorContextImpl") from exc
    return settings, root, children, author_context


def _root_entries(runtime: "C5G0Runtime") -> list[Path]:
    if not runtime.root.exists():
        return []
    if not runtime.root.is_dir():
        raise C5G0RuntimeError("canon_mvp.root is not a directory")
    entries = list(runtime.root.iterdir())
    for entry in entries:
        if _is_reparse_or_symlink(entry):
            raise C5G0RuntimeError(f"reparse/link residue in canon root: {entry}")
    return entries


def _validate_backup_residue(runtime: "C5G0Runtime") -> None:
    if not runtime.backups_dir.exists():
        return
    if not runtime.backups_dir.is_dir():
        raise C5G0RuntimeError("backups_dir must be a directory")
    for entry in runtime.backups_dir.iterdir():
        if _is_reparse_or_symlink(entry) or not entry.is_file():
            raise C5G0RuntimeError(f"invalid backup residue: {entry}")
        valid_name = (
            entry.name.startswith("creation_backup_")
            or entry.name.startswith("pre_migration_v")
        )
        if not valid_name or entry.suffix.lower() != ".db":
            raise C5G0RuntimeError(f"unknown backup residue: {entry.name}")


def _validate_root_state(runtime: "C5G0Runtime", *, allow_backups: bool = True) -> None:
    entries = _root_entries(runtime)
    allowed = {
        runtime.db_path,
        Path(f"{runtime.db_path}-wal"),
        Path(f"{runtime.db_path}-shm"),
    }
    if allow_backups:
        allowed.add(runtime.backups_dir)
    for entry in entries:
        if any(_same_path(entry, item) for item in allowed):
            continue
        raise C5G0RuntimeError(f"unexpected Canon root residue: {entry}")
    if runtime.backups_dir.exists():
        _validate_backup_residue(runtime)


def _wrap_operation(label: str, operation: Callable[[], T]) -> T:
    try:
        return operation()
    except C5G0RuntimeError:
        raise
    except Exception as exc:
        raise C5G0RuntimeError(label) from exc


@dataclass(frozen=True, slots=True, init=False)
class C5G0Runtime:
    """Validated, immutable G0-A composition root."""

    sqlite_settings: SQLitePersistenceSettings
    root: Path
    payloads_dir: Path
    projection_dir: Path
    backups_dir: Path
    exports_dir: Path
    local_author_context: LocalAuthorContextImpl

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise C5G0RuntimeError("C5G0Runtime must be created by load_c5_g0_runtime")

    @property
    def settings(self) -> SQLitePersistenceSettings:
        return self.sqlite_settings

    @property
    def db_path(self) -> Path:
        return Path(self.sqlite_settings.db_path)

    @property
    def operator_context(self) -> LocalAuthorContextImpl:
        return self.local_author_context

    @property
    def author_context(self) -> LocalAuthorContextImpl:
        return self.local_author_context

    def _validate_bound_identity(self) -> None:
        context = self.local_author_context
        if type(context) is not LocalAuthorContextImpl:
            raise C5G0RuntimeError("runtime operator context is not LocalAuthorContextImpl")
        try:
            author_id = context.author_id
        except Exception as exc:
            raise C5G0RuntimeError("runtime operator identity cannot be read") from exc
        if author_id != _APPROVED_OPERATOR_ID or _OPERATOR_ID_PATTERN.fullmatch(author_id) is None:
            raise C5G0RuntimeError("runtime operator identity is not the approved identity")

    def _revalidate(self) -> None:
        self._validate_bound_identity()
        _validate_paths(
            {
                "root": self.root,
                "creation_db_path": self.db_path,
                "payloads_dir": self.payloads_dir,
                "projection_dir": self.projection_dir,
                "backups_dir": self.backups_dir,
                "exports_dir": self.exports_dir,
            }
        )

    def initialize_database(self) -> Path:
        def action() -> Path:
            self._revalidate()
            if self.db_path.exists():
                raise C5G0RuntimeError("database already exists; initialization is not repair")
            if self.root.exists() and _root_entries(self):
                raise C5G0RuntimeError("initialization requires an empty Canon root")
            for child in (self.payloads_dir, self.projection_dir, self.backups_dir, self.exports_dir):
                if child.exists():
                    raise C5G0RuntimeError("initialization cannot reuse an existing Canon root")
            return init_database(self.sqlite_settings)

        return _wrap_operation("explicit database initialization failed", action)

    def migrate_database(self) -> None:
        def action() -> None:
            self._revalidate()
            if not self.db_path.exists():
                raise C5G0RuntimeError("database is missing; migration cannot initialize it")
            _validate_root_state(self)
            conn = get_connection(self.sqlite_settings, read_only=True)
            try:
                _verify_migration_ledger(conn, allow_fresh=True)
            finally:
                conn.close()
            migrate_database(self.sqlite_settings)

        _wrap_operation("explicit database migration failed", action)

    def backup_database(self) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            self._revalidate()
            if not self.db_path.exists():
                raise C5G0RuntimeError("database is missing; backup cannot initialize it")
            _validate_root_state(self)
            if not self.backups_dir.exists():
                self.backups_dir.mkdir()
            _validate_backup_residue(self)
            return backup_database_maintenance(self.sqlite_settings)

        return _wrap_operation("explicit database backup failed", action)

    def verify_initialized_empty(self) -> None:
        def action() -> None:
            self._revalidate()
            if not self.db_path.exists():
                raise C5G0RuntimeError("initialized-empty verification requires a database")
            _validate_root_state(self)
            if self.payloads_dir.exists() or self.projection_dir.exists() or self.exports_dir.exists():
                raise C5G0RuntimeError("payload, projection, or export root already exists")
            conn = get_connection(self.sqlite_settings, read_only=True)
            try:
                _verify_empty_database(conn)
            finally:
                conn.close()

        _wrap_operation("initialized-empty verification failed", action)


def _construct_runtime(
    token: object = _MISSING_CONSTRUCTION_TOKEN,
    sqlite_settings: SQLitePersistenceSettings | None = None,
    root: Path | None = None,
    payloads_dir: Path | None = None,
    projection_dir: Path | None = None,
    backups_dir: Path | None = None,
    exports_dir: Path | None = None,
    local_author_context: LocalAuthorContextImpl | None = None,
) -> C5G0Runtime:
    """Construct only after the module-local factory token is verified."""
    if token is not _RUNTIME_CONSTRUCTION_TOKEN:
        raise C5G0RuntimeError("invalid C5G0Runtime construction token")
    if any(
        value is None
        for value in (
            sqlite_settings,
            root,
            payloads_dir,
            projection_dir,
            backups_dir,
            exports_dir,
            local_author_context,
        )
    ):
        raise C5G0RuntimeError("validated runtime construction inputs are incomplete")
    instance = object.__new__(C5G0Runtime)
    object.__setattr__(instance, "sqlite_settings", sqlite_settings)
    object.__setattr__(instance, "root", root)
    object.__setattr__(instance, "payloads_dir", payloads_dir)
    object.__setattr__(instance, "projection_dir", projection_dir)
    object.__setattr__(instance, "backups_dir", backups_dir)
    object.__setattr__(instance, "exports_dir", exports_dir)
    object.__setattr__(instance, "local_author_context", local_author_context)
    return instance


def load_c5_g0_runtime() -> C5G0Runtime:
    """Read SSOT config and construct the sole approved local context."""
    try:
        settings, root, children, author_context = _validate_section(get_config())
        return _construct_runtime(
            _RUNTIME_CONSTRUCTION_TOKEN,
            settings,
            root,
            children[0],
            children[1],
            children[2],
            children[3],
            author_context,
        )
    except C5G0RuntimeError:
        raise
    except Exception as exc:
        raise C5G0RuntimeError("G0-A runtime binding failed") from exc


def _verify_empty_database(conn: sqlite3.Connection) -> None:
    if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise C5G0RuntimeError("foreign-key enforcement is not enabled")
    if conn.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
        raise C5G0RuntimeError("SQLite application_id is invalid")
    if conn.execute("PRAGMA user_version").fetchone()[0] != 6:
        raise C5G0RuntimeError("initialized-empty database must be at user_version 6")
    if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise C5G0RuntimeError("SQLite integrity_check failed")
    if conn.execute("PRAGMA foreign_key_check").fetchall():
        raise C5G0RuntimeError("SQLite foreign_key_check failed")

    _verify_migration_ledger(conn, allow_fresh=False)

    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    if tables != _EXPECTED_TABLES:
        raise C5G0RuntimeError("SQLite schema contains missing or unknown user tables")
    for table in sorted(_EXPECTED_TABLES - {"creation_schema_migration"}):
        count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        if count != 0:
            raise C5G0RuntimeError(f"initialized-empty database contains business rows: {table}")


def _verify_migration_ledger(conn: sqlite3.Connection, *, allow_fresh: bool) -> None:
    migrations = _discover_migrations()
    if [version for version, _name, _sha in migrations] != list(_EXPECTED_MIGRATION_VERSIONS):
        raise C5G0RuntimeError("migration files are not exactly v001 through v006")

    user_version = conn.execute("PRAGMA user_version").fetchone()[0]
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    ledger_exists = "creation_schema_migration" in tables
    if not ledger_exists:
        if not allow_fresh or user_version != 0 or tables:
            raise C5G0RuntimeError("migration ledger is missing or database is not fresh")
        return

    rows = conn.execute(
        "SELECT version, file_name, sha256 FROM creation_schema_migration ORDER BY version"
    ).fetchall()
    if user_version != 6 or len(rows) != len(migrations):
        raise C5G0RuntimeError("migration ledger is partial, duplicated, or inconsistent")
    for row, expected in zip(rows, migrations):
        if tuple(row) != expected:
            raise C5G0RuntimeError("migration ledger file/hash identity mismatch")
