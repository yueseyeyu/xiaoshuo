"""Retired C4a Apply entry kept as a stable, fail-closed compatibility shim.

C4-PRE deliberately has no Canon file-apply or Completion semantics.  The
public symbol remains importable so historical callers fail predictably before
opening a UnitOfWork or touching any external resource.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Callable
from uuid import UUID

from .canon_apply_context import CanonApplyDeliveryContext
from .errors import CanonResourceBoundaryError


IdFactory = Callable[[], UUID | str]


@dataclass(frozen=True, slots=True)
class CanonApplyCommand:
    task_id: str
    journal_id: str
    expected_revision: int
    command_schema_version: int = 1
    apply_key: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ValueError("task_id must be non-empty")
        if not isinstance(self.journal_id, str) or not self.journal_id.strip():
            raise ValueError("journal_id must be non-empty")
        if type(self.expected_revision) is not int or self.expected_revision < 0:
            raise ValueError("expected_revision must be non-negative")
        if self.command_schema_version != 1:
            raise ValueError("unsupported Canon Apply command schema version")


def compute_canon_apply_request_digest(command: CanonApplyCommand) -> str:
    """Hash only command schema, task, and journal identity."""
    payload = {
        "command_schema_version": command.command_schema_version,
        "journal_id": command.journal_id,
        "task_id": command.task_id,
    }
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


class ApplyCanonCommitUseCase:
    """Application boundary; infrastructure is supplied only through a port."""

    def __init__(self, port: object | None = None, *legacy_args: object, **_kwargs: object) -> None:
        # Retired multi-dependency construction remains fail-closed.  C4a
        # receives one application port from the composition root.
        self._port = port if not legacy_args else None

    def apply(self, command: CanonApplyCommand, context: CanonApplyDeliveryContext) -> object:
        if self._port is None or not callable(getattr(self._port, "apply", None)):
            del command, context
            raise CanonResourceBoundaryError(
                "Canon Apply requires an explicitly injected application port"
            )
        if not isinstance(command, CanonApplyCommand) or not isinstance(
            context, CanonApplyDeliveryContext
        ):
            raise ValueError("Canon Apply command and delivery context are required")
        return self._port.apply(command, context)
