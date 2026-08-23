"""Tests for SQLite serialization round-trips (chapter_task_to_row / row_to_chapter_task)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from xiaoshuo.domain.creation import (
    SCHEMA_VERSION,
    ArtifactRef,
    ChapterTask,
    ChapterTaskStatus,
    RecoveryInfo,
)
from xiaoshuo.infrastructure.persistence.sqlite.serialization import (
    artifact_ref_to_row,
    chapter_task_to_row,
    recovery_info_to_row,
    row_to_artifact_ref,
    row_to_chapter_task,
    row_to_recovery_info,
)
from xiaoshuo.infrastructure.persistence.sqlite.settings import (
    SQLitePersistenceSettings,
)
from xiaoshuo.infrastructure.persistence.sqlite.connection import get_connection
from xiaoshuo.infrastructure.persistence.sqlite.maintenance import init_database
from xiaoshuo.infrastructure.persistence.sqlite.migration_runner import (
    MigrationRunner,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
HASH_D = "sha256:" + "d" * 64
HASH_E = "sha256:" + "e" * 64
HASH_F = "sha256:" + "f" * 64
HASH_G = "sha256:" + "1" * 64


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def ref(artifact_id: str = "a1", content_hash: str = HASH_A) -> ArtifactRef:
    return ArtifactRef(artifact_id, SCHEMA_VERSION, content_hash)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings(tmp_path):
    return SQLitePersistenceSettings(
        db_path=str(tmp_path / "test.db"), busy_timeout_ms=5000
    )


@pytest.fixture
def migrated_conn(settings):
    init_database(settings)
    conn = get_connection(settings)
    MigrationRunner().migrate(conn, settings)
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# ArtifactRef serialization
# ---------------------------------------------------------------------------


class TestArtifactRefSerialization:
    def test_artifact_ref_roundtrip(self) -> None:
        original = ref("artifact-roundtrip")
        row = artifact_ref_to_row(original)
        assert row == ("artifact-roundtrip", SCHEMA_VERSION, HASH_A)
        reconstructed = row_to_artifact_ref(*row)
        assert reconstructed == original

    def test_artifact_ref_no_role(self) -> None:
        """Serialization has no 'role' field — only artifact_id, schema_version, content_hash."""
        original = ref("no-role-test")
        row = artifact_ref_to_row(original)
        assert len(row) == 3
        reconstruct = row_to_artifact_ref(*row)
        assert reconstruct.artifact_id == "no-role-test"
        assert reconstruct.schema_version == SCHEMA_VERSION
        assert reconstruct.content_hash == HASH_A


# ---------------------------------------------------------------------------
# RecoveryInfo serialization
# ---------------------------------------------------------------------------


class TestRecoveryInfoSerialization:
    def test_recovery_info_roundtrip(self) -> None:
        rec = RecoveryInfo("op-fail", "ERR_TIMEOUT", ChapterTaskStatus.DRAFTING)
        row = recovery_info_to_row(rec)
        assert row == ("op-fail", "ERR_TIMEOUT", "DRAFTING")

    def test_recovery_info_none(self, migrated_conn) -> None:
        """When recovery is None, row_to_recovery_info returns None."""
        # Insert a task without recovery, then read it back
        migrated_conn.execute(
            "INSERT INTO creation_artifact_ref (artifact_id, schema_version, content_hash) "
            "VALUES (?, ?, ?)",
            ("a-read", SCHEMA_VERSION, HASH_A),
        )
        migrated_conn.execute(
            "INSERT INTO chapter_task ("
            "task_id, schema_version, aggregate_revision, project_id, "
            "chapter_number, status, last_stable_status, "
            "creative_intent_ref_artifact_id, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "t-no-rec", SCHEMA_VERSION, 0, "proj-1", 1,
                ChapterTaskStatus.PLAN_PREPARING.value,
                ChapterTaskStatus.PLAN_PREPARING.value,
                "a-read",
                NOW.isoformat(),
                NOW.isoformat(),
            ),
        )
        row = migrated_conn.execute(
            "SELECT * FROM chapter_task WHERE task_id = ?", ("t-no-rec",)
        ).fetchone()
        rec = row_to_recovery_info(row)
        assert rec is None


# ---------------------------------------------------------------------------
# ChapterTask serialization
# ---------------------------------------------------------------------------


class TestChapterTaskSerialization:
    def test_chapter_task_to_row_minimal(self) -> None:
        """Minimal ChapterTask → row dict with correct keys."""
        task = ChapterTask(
            task_id="task-min",
            schema_version=SCHEMA_VERSION,
            aggregate_revision=0,
            project_id="proj-1",
            chapter_number=1,
            status=ChapterTaskStatus.PLAN_PREPARING,
            last_stable_status=ChapterTaskStatus.PLAN_PREPARING,
            creative_intent_ref=ref("ci-1"),
            confirmed_plan_ref=None,
            current_author_draft_ref=None,
            review_target_draft_ref=None,
            adopted_draft_ref=None,
            latest_review_ref=None,
            pending_changeset_ref=None,
            commit_receipt_ref=None,
            recovery=None,
            created_at=NOW,
            updated_at=NOW,
        )
        row = chapter_task_to_row(task)
        assert row["task_id"] == "task-min"
        assert row["status"] == "PLAN_PREPARING"
        assert row["creative_intent_ref_artifact_id"] == "ci-1"
        assert row["confirmed_plan_ref_artifact_id"] is None
        assert row["recovery_failed_operation_id"] is None

    def test_chapter_task_roundtrip_minimal(self, migrated_conn) -> None:
        """ChapterTask → row → INSERT → SELECT → ChapterTask."""
        migrated_conn.execute(
            "INSERT INTO creation_artifact_ref (artifact_id, schema_version, content_hash) "
            "VALUES (?, ?, ?)",
            ("ci-rt", SCHEMA_VERSION, HASH_A),
        )
        original = ChapterTask(
            task_id="task-rt-min",
            schema_version=SCHEMA_VERSION,
            aggregate_revision=0,
            project_id="proj-1",
            chapter_number=1,
            status=ChapterTaskStatus.PLAN_PREPARING,
            last_stable_status=ChapterTaskStatus.PLAN_PREPARING,
            creative_intent_ref=ref("ci-rt"),
            confirmed_plan_ref=None,
            current_author_draft_ref=None,
            review_target_draft_ref=None,
            adopted_draft_ref=None,
            latest_review_ref=None,
            pending_changeset_ref=None,
            commit_receipt_ref=None,
            recovery=None,
            created_at=NOW,
            updated_at=NOW,
        )
        row = chapter_task_to_row(original)
        cols = ", ".join(row.keys())
        placeholders = ", ".join("?" for _ in row)
        migrated_conn.execute(
            f"INSERT INTO chapter_task ({cols}) VALUES ({placeholders})",
            list(row.values()),
        )
        row_out = migrated_conn.execute(
            "SELECT * FROM chapter_task WHERE task_id = ?", ("task-rt-min",)
        ).fetchone()
        all_refs = {"ci-rt": ref("ci-rt")}
        reconstructed = row_to_chapter_task(row_out, all_refs)
        assert reconstructed.task_id == original.task_id
        assert reconstructed.status == original.status
        assert reconstructed.creative_intent_ref == original.creative_intent_ref
        assert reconstructed.recovery is None

    def test_chapter_task_roundtrip_with_recovery(self, migrated_conn) -> None:
        """Roundtrip with RecoveryInfo."""
        migrated_conn.execute(
            "INSERT INTO creation_artifact_ref (artifact_id, schema_version, content_hash) "
            "VALUES (?, ?, ?)",
            ("ci-rec", SCHEMA_VERSION, HASH_A),
        )
        rec = RecoveryInfo("op-rec", "ERR_FAIL", ChapterTaskStatus.DRAFTING)
        original = ChapterTask(
            task_id="task-rec",
            schema_version=SCHEMA_VERSION,
            aggregate_revision=0,
            project_id="proj-1",
            chapter_number=1,
            status=ChapterTaskStatus.RECOVERY_REQUIRED,
            last_stable_status=ChapterTaskStatus.DRAFTING,
            creative_intent_ref=ref("ci-rec"),
            confirmed_plan_ref=None,
            current_author_draft_ref=None,
            review_target_draft_ref=None,
            adopted_draft_ref=None,
            latest_review_ref=None,
            pending_changeset_ref=None,
            commit_receipt_ref=None,
            recovery=rec,
            created_at=NOW,
            updated_at=NOW,
        )
        row = chapter_task_to_row(original)
        cols = ", ".join(row.keys())
        placeholders = ", ".join("?" for _ in row)
        migrated_conn.execute(
            f"INSERT INTO chapter_task ({cols}) VALUES ({placeholders})",
            list(row.values()),
        )
        row_out = migrated_conn.execute(
            "SELECT * FROM chapter_task WHERE task_id = ?", ("task-rec",)
        ).fetchone()
        all_refs = {"ci-rec": ref("ci-rec")}
        reconstructed = row_to_chapter_task(row_out, all_refs)
        assert reconstructed.task_id == original.task_id
        assert reconstructed.status == ChapterTaskStatus.RECOVERY_REQUIRED
        assert reconstructed.recovery is not None
        assert reconstructed.recovery.failed_operation_id == "op-rec"
        assert reconstructed.recovery.error_code == "ERR_FAIL"
        assert reconstructed.recovery.retry_from_status == ChapterTaskStatus.DRAFTING

    def test_chapter_task_roundtrip_with_all_refs(self, migrated_conn) -> None:
        """Roundtrip with all 7 artifact refs populated."""
        refs_map = {
            "ci-all": ref("ci-all", HASH_A),
            "cp-all": ref("cp-all", HASH_B),
            "cad-all": ref("cad-all", HASH_C),
            "rtd-all": ref("rtd-all", HASH_D),
            "ad-all": ref("ad-all", HASH_E),
            "lr-all": ref("lr-all", HASH_F),
            "pc-all": ref("pc-all", HASH_G),
        }
        for aid, aref in refs_map.items():
            migrated_conn.execute(
                "INSERT INTO creation_artifact_ref (artifact_id, schema_version, content_hash) "
                "VALUES (?, ?, ?)",
                (aref.artifact_id, aref.schema_version, aref.content_hash),
            )
        original = ChapterTask(
            task_id="task-all-refs",
            schema_version=SCHEMA_VERSION,
            aggregate_revision=1,
            project_id="proj-1",
            chapter_number=1,
            status=ChapterTaskStatus.DRAFT_APPROVAL_PENDING,
            last_stable_status=ChapterTaskStatus.DRAFTING,
            creative_intent_ref=refs_map["ci-all"],
            confirmed_plan_ref=refs_map["cp-all"],
            current_author_draft_ref=refs_map["cad-all"],
            review_target_draft_ref=refs_map["rtd-all"],
            adopted_draft_ref=refs_map["ad-all"],
            latest_review_ref=refs_map["lr-all"],
            pending_changeset_ref=refs_map["pc-all"],
            commit_receipt_ref=None,
            recovery=None,
            created_at=NOW,
            updated_at=NOW,
        )
        row = chapter_task_to_row(original)
        cols = ", ".join(row.keys())
        placeholders = ", ".join("?" for _ in row)
        migrated_conn.execute(
            f"INSERT INTO chapter_task ({cols}) VALUES ({placeholders})",
            list(row.values()),
        )
        row_out = migrated_conn.execute(
            "SELECT * FROM chapter_task WHERE task_id = ?", ("task-all-refs",)
        ).fetchone()
        reconstructed = row_to_chapter_task(row_out, refs_map)
        assert reconstructed.task_id == original.task_id
        assert reconstructed.creative_intent_ref == refs_map["ci-all"]
        assert reconstructed.confirmed_plan_ref == refs_map["cp-all"]
        assert reconstructed.current_author_draft_ref == refs_map["cad-all"]
        assert reconstructed.review_target_draft_ref == refs_map["rtd-all"]
        assert reconstructed.adopted_draft_ref == refs_map["ad-all"]
        assert reconstructed.latest_review_ref == refs_map["lr-all"]
        assert reconstructed.pending_changeset_ref == refs_map["pc-all"]
        assert reconstructed.commit_receipt_ref is None
