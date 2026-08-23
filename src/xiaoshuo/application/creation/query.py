"""B3 internal read-only Creation query facade."""

from __future__ import annotations

from typing import Callable

from xiaoshuo.domain.creation import AuditEvent, ChapterTask

from .errors import CreationApplicationError, QueryReadError
from .get_task import GetChapterTaskUseCase
from .query_requests import AuditHistoryRequest, ChapterTaskListRequest
from .repository import CreationQuerySession
from .results import (
    AuditEventView,
    AuditHistoryResult,
    ChapterTaskListItem,
    ChapterTaskListResult,
    IntegrityCheckResult,
)


class CreationQueryUseCase:
    """Internal facade for B3 queries, with no write session capability."""

    def __init__(
        self,
        exact_get: GetChapterTaskUseCase,
        session_factory: Callable[[], CreationQuerySession],
    ) -> None:
        self._exact_get = exact_get
        self._session_factory = session_factory

    def get_task(self, task_id: str) -> ChapterTask:
        """Delegate exact reads to the B1 use case without alternate SQL."""
        return self._exact_get.get(task_id)

    def list_tasks(self, request: ChapterTaskListRequest) -> ChapterTaskListResult:
        items, cursor = self._read(lambda session: session.tasks.list_by_project(request))
        return ChapterTaskListResult(items=items, next_cursor=cursor)

    def audit_history(self, request: AuditHistoryRequest) -> AuditHistoryResult:
        events, cursor = self._read(lambda session: session.audit.history_for_task(request))
        return AuditHistoryResult(
            items=tuple(_audit_view(event) for event in events), next_cursor=cursor
        )

    def check_integrity(self) -> IntegrityCheckResult:
        return self._read(lambda session: session.integrity.check())

    def _read(self, action):
        try:
            session = self._session_factory()
        except CreationApplicationError:
            raise
        except Exception as exc:
            raise QueryReadError("creation query session open failed") from exc
        try:
            return action(session)
        except CreationApplicationError:
            raise
        except Exception as exc:
            raise QueryReadError("creation query read failed") from exc
        finally:
            try:
                session.close()
            except Exception as exc:
                raise QueryReadError("creation query session close failed") from exc


def _audit_view(event: AuditEvent) -> AuditEventView:
    return AuditEventView(
        event_id=event.event_id,
        task_id=event.task_id,
        project_id=event.project_id,
        event_type=event.event_type,
        actor_kind=event.actor.kind,
        actor_id=event.actor.actor_id,
        model_run_id=event.actor.model_run_id,
        before_task_revision=event.before_task_revision,
        after_task_revision=event.after_task_revision,
        object_refs=event.object_refs,
        operation_id=event.operation_id,
        created_at=event.created_at.isoformat(),
    )
