"""Immutable internal request DTOs for B3 read-only queries."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass

from xiaoshuo.domain.creation import ChapterTaskStatus

from .errors import QueryValidationError

_CURSOR_VERSION = 1
_MIN_PAGE_SIZE = 1
_MAX_PAGE_SIZE = 100
_FORBIDDEN_FILTER_STATUSES = frozenset(
    {ChapterTaskStatus.COMMITTING, ChapterTaskStatus.COMPLETED}
)


def _require_non_empty(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise QueryValidationError(f"{label} must be non-empty")


def _validate_page_size(page_size: int) -> None:
    if not isinstance(page_size, int) or isinstance(page_size, bool):
        raise QueryValidationError("page_size must be an integer")
    if not _MIN_PAGE_SIZE <= page_size <= _MAX_PAGE_SIZE:
        raise QueryValidationError("page_size must be between 1 and 100")


def _encode_cursor(kind: str, payload: dict[str, object]) -> str:
    data = {"v": _CURSOR_VERSION, "kind": kind, **payload}
    raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(value: str, kind: str) -> dict[str, object]:
    if not isinstance(value, str) or not value:
        raise QueryValidationError("cursor must be a non-empty string")
    try:
        padded = value + "=" * (-len(value) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except Exception as exc:
        raise QueryValidationError("cursor is invalid") from exc
    if not isinstance(data, dict) or data.get("v") != _CURSOR_VERSION or data.get("kind") != kind:
        raise QueryValidationError("cursor version or kind is unsupported")
    return data


@dataclass(frozen=True, slots=True)
class ChapterTaskListRequest:
    project_id: str
    status: ChapterTaskStatus | None = None
    page_size: int = 50
    cursor: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.project_id, "project_id")
        _validate_page_size(self.page_size)
        if self.status is not None and not isinstance(self.status, ChapterTaskStatus):
            raise QueryValidationError("status must be ChapterTaskStatus or None")
        if self.status in _FORBIDDEN_FILTER_STATUSES:
            raise QueryValidationError("COMMITTING/COMPLETED cannot be query filters")
        if self.cursor is not None:
            task_cursor_values(self.cursor)

    @classmethod
    def from_filters(cls, filters: dict[str, object]) -> "ChapterTaskListRequest":
        allowed = {"project_id", "status", "page_size", "cursor"}
        unknown = set(filters) - allowed
        if unknown:
            raise QueryValidationError("unknown chapter task query filter")
        return cls(**filters)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class AuditHistoryRequest:
    task_id: str
    page_size: int = 50
    cursor: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.task_id, "task_id")
        _validate_page_size(self.page_size)
        if self.cursor is not None:
            audit_cursor_values(self.cursor)

    @classmethod
    def from_filters(cls, filters: dict[str, object]) -> "AuditHistoryRequest":
        allowed = {"task_id", "page_size", "cursor"}
        unknown = set(filters) - allowed
        if unknown:
            raise QueryValidationError("unknown audit history query filter")
        return cls(**filters)  # type: ignore[arg-type]


def make_task_cursor(chapter_number: int, task_id: str) -> str:
    return _encode_cursor("task", {"chapter_number": chapter_number, "task_id": task_id})


def task_cursor_values(cursor: str) -> tuple[int, str]:
    data = _decode_cursor(cursor, "task")
    if set(data) != {"v", "kind", "chapter_number", "task_id"}:
        raise QueryValidationError("task cursor fields are invalid")
    chapter_number = data.get("chapter_number")
    task_id = data.get("task_id")
    if not isinstance(chapter_number, int) or isinstance(chapter_number, bool) or chapter_number <= 0:
        raise QueryValidationError("task cursor chapter_number is invalid")
    _require_non_empty(task_id, "task cursor task_id")
    return chapter_number, task_id


def make_audit_cursor(after_task_revision: int, event_id: str) -> str:
    return _encode_cursor("audit", {"after_task_revision": after_task_revision, "event_id": event_id})


def audit_cursor_values(cursor: str) -> tuple[int, str]:
    data = _decode_cursor(cursor, "audit")
    if set(data) != {"v", "kind", "after_task_revision", "event_id"}:
        raise QueryValidationError("audit cursor fields are invalid")
    revision = data.get("after_task_revision")
    event_id = data.get("event_id")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        raise QueryValidationError("audit cursor revision is invalid")
    _require_non_empty(event_id, "audit cursor event_id")
    return revision, event_id
