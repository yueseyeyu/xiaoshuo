"""Tests for SQLitePersistenceSettings and get_connection."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from xiaoshuo.infrastructure.persistence.sqlite.settings import (
    SQLitePersistenceSettings,
)
from xiaoshuo.infrastructure.persistence.sqlite.connection import get_connection
from xiaoshuo.infrastructure.persistence.sqlite.maintenance import init_database


class TestSettingsFrozen:
    def test_settings_frozen(self) -> None:
        settings = SQLitePersistenceSettings(
            db_path=":memory:", busy_timeout_ms=5000
        )
        with pytest.raises(FrozenInstanceError):
            settings.db_path = "/other/path"  # type: ignore[misc]

    def test_settings_busy_timeout_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="busy_timeout_ms"):
            SQLitePersistenceSettings(db_path=":memory:", busy_timeout_ms=0)
        with pytest.raises(ValueError, match="busy_timeout_ms"):
            SQLitePersistenceSettings(db_path=":memory:", busy_timeout_ms=-1)

    def test_settings_busy_timeout_no_default(self) -> None:
        """Cannot instantiate without explicit busy_timeout_ms (no default)."""
        with pytest.raises(TypeError):
            SQLitePersistenceSettings(db_path=":memory:")  # type: ignore[call-arg]

    def test_connection_str_path(self) -> None:
        """String path is converted to Path."""
        settings = SQLitePersistenceSettings(
            db_path=":memory:", busy_timeout_ms=5000
        )
        assert isinstance(settings.db_path, Path)


class TestConnectionFileBasedPRAGMAs:
    def test_connection_with_temp_db(self, tmp_path) -> None:
        settings = SQLitePersistenceSettings(
            db_path=str(tmp_path / "test.db"), busy_timeout_ms=5000
        )
        conn = get_connection(settings)
        try:
            cursor = conn.execute("SELECT 1 AS val")
            assert cursor.fetchone()["val"] == 1
        finally:
            conn.close()

    def test_connection_verify_wal(self, tmp_path) -> None:
        settings = SQLitePersistenceSettings(
            db_path=str(tmp_path / "wal.db"), busy_timeout_ms=5000
        )
        conn = get_connection(settings)
        try:
            (mode,) = conn.execute("PRAGMA journal_mode").fetchone()
            assert mode.lower() == "wal"
        finally:
            conn.close()

    def test_connection_verify_foreign_keys(self, tmp_path) -> None:
        settings = SQLitePersistenceSettings(
            db_path=str(tmp_path / "fk.db"), busy_timeout_ms=5000
        )
        conn = get_connection(settings)
        try:
            (fk_on,) = conn.execute("PRAGMA foreign_keys").fetchone()
            assert fk_on == 1
        finally:
            conn.close()

    def test_connection_verify_busy_timeout(self, tmp_path) -> None:
        settings = SQLitePersistenceSettings(
            db_path=str(tmp_path / "bt.db"), busy_timeout_ms=5000
        )
        conn = get_connection(settings)
        try:
            (bt,) = conn.execute("PRAGMA busy_timeout").fetchone()
            assert bt == 5000
        finally:
            conn.close()


class TestConnectionFileBased:
    def test_connection_read_only(self, tmp_path) -> None:
        """read_only=True opens in read-only mode."""
        db_path = tmp_path / "test.db"
        settings = SQLitePersistenceSettings(
            db_path=str(db_path), busy_timeout_ms=5000
        )
        # Must exist before read-only open
        init_database(settings)
        ro_conn = get_connection(settings, read_only=True)
        try:
            (val,) = ro_conn.execute("SELECT 1").fetchone()
            assert val == 1
            (query_only,) = ro_conn.execute("PRAGMA query_only").fetchone()
            assert query_only == 1
            # Write should fail in read-only mode
            with pytest.raises(Exception):
                ro_conn.execute("CREATE TABLE t (x INT)")
        finally:
            ro_conn.close()

    def test_strict_version_check(self) -> None:
        """Verify that version check passes (SQLite 3.37+)."""
        import sqlite3
        assert sqlite3.sqlite_version_info >= (3, 37, 0)
