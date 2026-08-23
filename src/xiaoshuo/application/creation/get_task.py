"""Exact task-id query use case for the B1 persistence slice."""

from __future__ import annotations

from typing import Callable, Protocol

from xiaoshuo.domain.creation import ChapterTask

from .errors import CreationApplicationError, NotFound
from .repository import ExactTaskReader


class ExactTaskReadSession(Protocol):
    """The minimal read capability required by B1 exact get."""

    tasks: ExactTaskReader

    def close(self) -> None:
        ...


class GetChapterTaskUseCase:
    """Load one ChapterTask by exact identifier without list/query semantics."""

    def __init__(self, uow_factory: Callable[[], ExactTaskReadSession]) -> None:
        self._uow_factory = uow_factory

    def get(self, task_id: str) -> ChapterTask:
        try:
            uow = self._uow_factory()
        except CreationApplicationError:
            raise
        except Exception as exc:
            raise CreationApplicationError("creation persistence read failed") from exc
        try:
            task = uow.tasks.get(task_id)
        except CreationApplicationError:
            raise
        except Exception as exc:
            raise CreationApplicationError("creation persistence read failed") from exc
        finally:
            try:
                uow.close()
            except Exception as exc:
                raise CreationApplicationError("creation persistence close failed") from exc
        if task is None:
            raise NotFound(f"ChapterTask {task_id!r} was not found")
        return task
