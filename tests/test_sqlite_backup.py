"""Tests for backup_database — file creation, integrity, manifest."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from xiaoshuo.infrastructure.persistence.sqlite.settings import (
    SQLitePersistenceSettings,
)
from xiaoshuo.infrastructure.persistence.sqlite.connection import get_connection
from xiaoshuo.infrastructure.persistence.sqlite.maintenance import init_database
from xiaoshuo.infrastructure.persistence.sqlite.migration_runner import (
    MigrationRunner,
)
from xiaoshuo.infrastructure.persistence.sqlite.backup import backup_database

APPLICATION_ID = 0x59584352


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings(tmp_path):
    return SQLitePersistenceSettings(
        db_path=str(tmp_path / "source.db"), busy_timeout_ms=5000
    )


@pytest.fixture
def source_conn(settings):
    init_database(settings)
    conn = get_connection(settings)
    MigrationRunner().migrate(conn, settings)
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Backup tests
# ---------------------------------------------------------------------------


class TestBackup:
    def test_backup_creates_file(self, source_conn, tmp_path) -> None:
        target = tmp_path / "backup.db"
        backup_database(source_conn, target)
        assert target.exists()
        assert target.stat().st_size > 0

    def test_backup_target_integrity(self, source_conn, tmp_path) -> None:
        target = tmp_path / "backup_integrity.db"
        backup_database(source_conn, target)
        import sqlite3
        tgt = sqlite3.connect(str(target))
        try:
            (result,) = tgt.execute("PRAGMA integrity_check").fetchone()
            assert result == "ok"
        finally:
            tgt.close()

    def test_backup_manifest_has_source_and_target(self, source_conn, tmp_path) -> None:
        target = tmp_path / "backup_manifest.db"
        manifest = backup_database(source_conn, target)
        assert "source" in manifest
        assert "target" in manifest

    def test_backup_manifest_has_sha256(self, source_conn, tmp_path) -> None:
        target = tmp_path / "backup_sha256.db"
        manifest = backup_database(source_conn, target)
        assert "sha256_whole_file" in manifest["source"]
        assert "sha256_whole_file" in manifest["target"]
        assert isinstance(manifest["source"]["sha256_whole_file"], str)
        assert len(manifest["source"]["sha256_whole_file"]) == 64
        assert isinstance(manifest["target"]["sha256_whole_file"], str)
        assert len(manifest["target"]["sha256_whole_file"]) == 64

    def test_backup_manifest_has_created_at(self, source_conn, tmp_path) -> None:
        target = tmp_path / "backup_created_at.db"
        manifest = backup_database(source_conn, target)
        assert "created_at" in manifest
        assert isinstance(manifest["created_at"], str)

    def test_backup_refuses_overwrite(self, source_conn, tmp_path) -> None:
        target = tmp_path / "backup_exists.db"
        backup_database(source_conn, target)
        with pytest.raises(FileExistsError, match="already exists"):
            backup_database(source_conn, target)

    def test_backup_application_id_matches(self, source_conn, tmp_path) -> None:
        target = tmp_path / "backup_appid.db"
        manifest = backup_database(source_conn, target)
        assert manifest["source"]["application_id"] == APPLICATION_ID
        assert manifest["target"]["application_id"] == APPLICATION_ID
