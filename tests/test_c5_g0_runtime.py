"""C5G0-01..10 acceptance tests for the G0-A runtime binding."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from xiaoshuo.application.creation.local_author_context import LocalAuthorContextImpl
from xiaoshuo.infrastructure.canon import c5_g0_runtime as runtime_module


def _config(root: Path) -> dict:
    return {
        "canon_mvp": {
            "root": str(root),
            "payloads_dir": str(root / "payloads"),
            "projection_dir": str(root / "projection"),
            "backups_dir": str(root / "backups"),
            "exports_dir": str(root / "exports"),
            "creation_db_path": str(root / "creation.db"),
            "creation_busy_timeout_ms": 1000,
            "local_operator_id": "local-author",
        }
    }


@pytest.fixture
def fixture_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # All fixture writes are beneath pytest's D-drive basetemp.  The
    # production D:\tmp rule remains covered by the direct path test below.
    monkeypatch.setattr(runtime_module, "_TMP_ROOT", tmp_path / "__production_tmp_sentinel")
    root = tmp_path / "canon"
    monkeypatch.setattr(runtime_module, "get_config", lambda: _config(root))
    return root


def _runtime() -> runtime_module.C5G0Runtime:
    return runtime_module.load_c5_g0_runtime()


def _forged_runtime(
    runtime: runtime_module.C5G0Runtime,
    context: object,
) -> runtime_module.C5G0Runtime:
    forged = object.__new__(runtime_module.C5G0Runtime)
    object.__setattr__(forged, "sqlite_settings", runtime.sqlite_settings)
    object.__setattr__(forged, "root", runtime.root)
    object.__setattr__(forged, "payloads_dir", runtime.payloads_dir)
    object.__setattr__(forged, "projection_dir", runtime.projection_dir)
    object.__setattr__(forged, "backups_dir", runtime.backups_dir)
    object.__setattr__(forged, "exports_dir", runtime.exports_dir)
    object.__setattr__(forged, "local_author_context", context)
    return forged


def test_c5g0_01_config_and_operator_identity(
    fixture_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _runtime()
    assert runtime.sqlite_settings.busy_timeout_ms == 1000
    assert runtime.local_author_context is runtime.author_context
    assert isinstance(runtime.local_author_context, LocalAuthorContextImpl)
    assert runtime.local_author_context.author_id == "local-author"
    invalid = (
        ("local_operator_id", ""),
        ("local_operator_id", "local\x00author"),
        ("creation_busy_timeout_ms", 0),
        ("creation_busy_timeout_ms", True),
        ("creation_db_path", "relative.db"),
    )
    for key, value in invalid:
        config = _config(fixture_root)
        config["canon_mvp"][key] = value
        monkeypatch.setattr(runtime_module, "get_config", lambda config=config: config)
        with pytest.raises(runtime_module.C5G0RuntimeError):
            runtime_module.load_c5_g0_runtime()
        monkeypatch.setattr(runtime_module, "get_config", lambda: _config(fixture_root))

    with pytest.raises(runtime_module.C5G0RuntimeError):
        runtime_module.C5G0Runtime()

    runtime = _runtime()
    forged = _forged_runtime(runtime, LocalAuthorContextImpl("foreign-operator"))
    calls = {"init": 0, "migrate": 0, "backup": 0, "connection": 0}
    monkeypatch.setattr(
        runtime_module,
        "init_database",
        lambda settings: calls.__setitem__("init", calls["init"] + 1),
    )
    monkeypatch.setattr(
        runtime_module,
        "migrate_database",
        lambda settings: calls.__setitem__("migrate", calls["migrate"] + 1),
    )
    monkeypatch.setattr(
        runtime_module,
        "backup_database_maintenance",
        lambda settings: calls.__setitem__("backup", calls["backup"] + 1),
    )
    monkeypatch.setattr(
        runtime_module,
        "get_connection",
        lambda *args, **kwargs: calls.__setitem__("connection", calls["connection"] + 1),
    )
    with pytest.raises(runtime_module.C5G0RuntimeError):
        runtime_module._construct_runtime()
    with pytest.raises(runtime_module.C5G0RuntimeError):
        runtime_module._construct_runtime(object())
    assert calls == {"init": 0, "migrate": 0, "backup": 0, "connection": 0}
    for method_name in (
        "initialize_database",
        "migrate_database",
        "backup_database",
        "verify_initialized_empty",
    ):
        with pytest.raises(runtime_module.C5G0RuntimeError):
            getattr(forged, method_name)()
    assert calls == {"init": 0, "migrate": 0, "backup": 0, "connection": 0}


def test_c5g0_02_safe_d_drive_workspace_boundary(fixture_root: Path) -> None:
    runtime = _runtime()
    assert runtime.root.drive.upper() == "D:"
    assert not runtime_module._is_within(runtime.root, runtime_module._WORKSPACE_ROOT)
    assert not runtime_module._is_within(runtime.root, runtime_module._TMP_ROOT)
    assert runtime.db_path.parent == runtime.root
    assert runtime.payloads_dir.parent == runtime.root


def test_c5g0_03_links_same_paths_and_nesting_fail_closed(
    fixture_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(fixture_root)
    config["canon_mvp"]["projection_dir"] = config["canon_mvp"]["payloads_dir"]
    with pytest.raises(runtime_module.C5G0RuntimeError):
        runtime_module._validate_section(config)

    config = _config(fixture_root)
    config["canon_mvp"]["exports_dir"] = str(fixture_root / "payloads" / "nested")
    with pytest.raises(runtime_module.C5G0RuntimeError):
        runtime_module._validate_section(config)

    production_tmp = Path(r"D:\tmp")
    monkeypatch.setattr(runtime_module, "_TMP_ROOT", production_tmp)
    with pytest.raises(runtime_module.C5G0RuntimeError):
        runtime_module._validated_path(r"D:\tmp\forbidden", "test path")

    fixture_root.mkdir()
    monkeypatch.setattr(runtime_module, "_TMP_ROOT", fixture_root.parent / "__production_tmp_sentinel")
    monkeypatch.setattr(
        runtime_module,
        "_is_reparse_or_symlink",
        lambda path: runtime_module._same_path(path, fixture_root),
    )
    with pytest.raises(runtime_module.C5G0RuntimeError):
        runtime_module._validate_section(_config(fixture_root))


def test_c5g0_04_ordinary_db_wal_shm_are_validated(fixture_root: Path) -> None:
    runtime = _runtime()
    runtime.root.mkdir()
    runtime.db_path.touch()
    Path(f"{runtime.db_path}-wal").touch()
    Path(f"{runtime.db_path}-shm").touch()
    loaded = _runtime()
    assert loaded.db_path == runtime.db_path


@pytest.mark.parametrize("unsafe_kind", ["db", "wal", "shm"])
def test_c5g0_04_directory_db_wal_shm_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unsafe_kind: str,
) -> None:
    monkeypatch.setattr(runtime_module, "_TMP_ROOT", tmp_path / "__production_tmp_sentinel")
    root = tmp_path / unsafe_kind
    root.mkdir()
    db_path = root / "creation.db"
    if unsafe_kind == "db":
        db_path.mkdir()
    else:
        db_path.touch()
        (root / f"creation.db-{unsafe_kind}").mkdir()
    monkeypatch.setattr(runtime_module, "get_config", lambda: _config(root))
    with pytest.raises(runtime_module.C5G0RuntimeError):
        runtime_module.load_c5_g0_runtime()


def test_c5g0_05_backup_is_bound_to_configured_root(fixture_root: Path) -> None:
    runtime = _runtime()
    assert runtime.backups_dir == runtime.root / "backups"
    assert "target_path" not in runtime.backup_database.__annotations__


def test_c5g0_06_explicit_init_only_creates_database(fixture_root: Path) -> None:
    runtime = _runtime()
    runtime.initialize_database()
    assert runtime.db_path.is_file()
    assert not runtime.payloads_dir.exists()
    assert not runtime.projection_dir.exists()
    assert not runtime.exports_dir.exists()


def test_c5g0_07_explicit_migrate_creates_exact_v001_to_v006_ledger(
    fixture_root: Path,
) -> None:
    runtime = _runtime()
    runtime.initialize_database()
    runtime.migrate_database()
    conn = sqlite3.connect(runtime.db_path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 6
        assert [
            row[0]
            for row in conn.execute(
                "SELECT version FROM creation_schema_migration ORDER BY version"
            )
        ] == [1, 2, 3, 4, 5, 6]
    finally:
        conn.close()


@pytest.mark.parametrize(
    "corruption",
    ["missing", "partial", "duplicate", "unknown", "hash", "user_version"],
)
def test_c5g0_07_corrupt_migration_state_is_not_auto_repaired(
    fixture_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
) -> None:
    runtime = _runtime()
    runtime.initialize_database()
    runtime.migrate_database()
    conn = sqlite3.connect(runtime.db_path)
    try:
        if corruption == "missing":
            conn.execute("DROP TABLE creation_schema_migration")
            conn.execute("PRAGMA user_version = 6")
        elif corruption == "partial":
            conn.execute("DELETE FROM creation_schema_migration WHERE version = 6")
            conn.execute("PRAGMA user_version = 5")
        elif corruption == "duplicate":
            conn.execute("DROP TABLE creation_schema_migration")
            conn.execute(
                "CREATE TABLE creation_schema_migration "
                "(version INTEGER, file_name TEXT, sha256 TEXT, applied_at TEXT)"
            )
            conn.executemany(
                "INSERT INTO creation_schema_migration VALUES (?, ?, ?, ?)",
                [(1, "v001_initial_schema.sql", "x", "t")] * 2,
            )
            conn.execute("PRAGMA user_version = 6")
        elif corruption == "unknown":
            conn.execute("DROP TABLE creation_schema_migration")
            conn.execute(
                "CREATE TABLE creation_schema_migration "
                "(version INTEGER, file_name TEXT, sha256 TEXT, applied_at TEXT)"
            )
            conn.executemany(
                "INSERT INTO creation_schema_migration VALUES (?, ?, ?, ?)",
                [(version, "unknown.sql", "x", "t") for version in (1, 2, 3, 4, 5, 99)],
            )
            conn.execute("PRAGMA user_version = 6")
        elif corruption == "hash":
            conn.execute(
                "UPDATE creation_schema_migration SET sha256 = 'sha256:tampered' WHERE version = 1"
            )
        else:
            conn.execute("PRAGMA user_version = 5")
        conn.commit()
    finally:
        conn.close()

    maintenance_calls = {"count": 0}
    monkeypatch.setattr(
        runtime_module,
        "migrate_database",
        lambda settings: maintenance_calls.__setitem__("count", 1),
    )
    with pytest.raises(runtime_module.C5G0RuntimeError):
        runtime.migrate_database()
    assert maintenance_calls["count"] == 0


def test_c5g0_08_load_and_read_paths_do_not_write(fixture_root: Path) -> None:
    before = list(fixture_root.parent.iterdir()) if fixture_root.parent.exists() else []
    loaded = _runtime()
    assert loaded.local_author_context.author_id == "local-author"
    after = list(fixture_root.parent.iterdir()) if fixture_root.parent.exists() else []
    assert after == before


def test_c5g0_08_explicit_backup_uses_only_configured_backup_root(
    fixture_root: Path,
) -> None:
    runtime = _runtime()
    runtime.initialize_database()
    result = runtime.backup_database()
    target = Path(result["target"]["path"])
    assert target.parent == runtime.backups_dir
    assert target.is_file()
    assert runtime.backups_dir.is_dir()
    assert not runtime.payloads_dir.exists()
    assert not runtime.projection_dir.exists()
    assert not runtime.exports_dir.exists()
    with pytest.raises(TypeError):
        runtime.backup_database(target)  # type: ignore[call-arg]


def test_c5g0_09_initialized_empty_is_read_only_verified(fixture_root: Path) -> None:
    runtime = _runtime()
    runtime.initialize_database()
    runtime.migrate_database()
    runtime.verify_initialized_empty()


def _initialize_migrated(runtime: runtime_module.C5G0Runtime) -> None:
    runtime.initialize_database()
    runtime.migrate_database()


@pytest.mark.parametrize(
    "bad_state",
    [
        "missing_db",
        "partial_migration",
        "artifact_ref",
        "activation_fact",
        "payload_root",
        "projection_root",
        "unknown_residue",
        "reparse_residue",
    ],
)
def test_c5g0_10_bad_initialized_empty_states_fail_closed(
    fixture_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    bad_state: str,
) -> None:
    runtime = _runtime()
    if bad_state != "missing_db":
        _initialize_migrated(runtime)
    if bad_state == "partial_migration":
        conn = sqlite3.connect(runtime.db_path)
        try:
            conn.execute("DELETE FROM creation_schema_migration WHERE version = 6")
            conn.execute("PRAGMA user_version = 5")
            conn.commit()
        finally:
            conn.close()
    elif bad_state == "artifact_ref":
        conn = sqlite3.connect(runtime.db_path)
        try:
            conn.execute(
                "INSERT INTO creation_artifact_ref VALUES (?, ?, ?)",
                ("artifact-1", 1, "sha256:" + "a" * 64),
            )
            conn.commit()
        finally:
            conn.close()
    elif bad_state == "activation_fact":
        digest = "sha256:" + "a" * 64
        conn = sqlite3.connect(runtime.db_path)
        try:
            conn.execute(
                "INSERT INTO creation_artifact_ref VALUES (?, ?, ?)",
                ("bundle-1", 1, digest),
            )
            conn.execute(
                "INSERT INTO canon_activation_attempt VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "attempt-1",
                    "project-1",
                    "attempt-key-1",
                    digest,
                    digest,
                    "bundle-1",
                    1,
                    digest,
                    digest,
                    digest,
                    "version-1",
                    digest,
                    "local-author",
                    "now",
                ),
            )
            conn.commit()
        finally:
            conn.close()
    elif bad_state == "payload_root":
        runtime.payloads_dir.mkdir()
    elif bad_state == "projection_root":
        runtime.projection_dir.mkdir()
    elif bad_state == "unknown_residue":
        (runtime.root / "unknown.tmp").write_bytes(b"x")
    elif bad_state == "reparse_residue":
        residue = runtime.root / "reparse.tmp"
        residue.write_bytes(b"x")
        monkeypatch.setattr(
            runtime_module,
            "_is_reparse_or_symlink",
            lambda path: runtime_module._same_path(path, residue),
        )
    with pytest.raises(runtime_module.C5G0RuntimeError):
        runtime.verify_initialized_empty()
