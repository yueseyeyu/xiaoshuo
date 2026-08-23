"""SQLite persistence adapters for the creation pipeline."""

from .settings import SQLitePersistenceSettings
from .connection import get_connection
from .migration_runner import MigrationRunner
from .serialization import (
    chapter_task_to_row,
    row_to_chapter_task,
    artifact_ref_to_row,
    row_to_artifact_ref,
    recovery_info_to_row,
    row_to_recovery_info,
)
from .repository import SqliteChapterTaskRepository
from .uow import SqliteCreationUnitOfWork
from .backup import backup_database
from .maintenance import init_database, migrate_database

# Explicit public API
__all__ = [
    "SQLitePersistenceSettings",
    "get_connection",
    "MigrationRunner",
    "chapter_task_to_row",
    "row_to_chapter_task",
    "artifact_ref_to_row",
    "row_to_artifact_ref",
    "recovery_info_to_row",
    "row_to_recovery_info",
    "SqliteChapterTaskRepository",
    "SqliteCreationUnitOfWork",
    "backup_database",
    "init_database",
    "migrate_database",
]
