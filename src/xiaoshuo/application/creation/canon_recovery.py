"""Retired C4a Recovery entry kept as a stable fail-closed shim."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Callable
from uuid import UUID

from .canon_recovery_context import CanonRecoveryDeliveryContext
from .errors import CanonResourceBoundaryError


IdFactory = Callable[[], UUID | str]


@dataclass(frozen=True, slots=True)
class CanonRecoveryCommand:
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
            raise ValueError("unsupported Canon Recovery command schema version")


def compute_canon_recovery_request_digest(command: CanonRecoveryCommand) -> str:
    payload = {
        "command_schema_version": command.command_schema_version,
        "journal_id": command.journal_id,
        "task_id": command.task_id,
    }
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


class RecoverCanonCommitUseCase:
    """Application Recovery boundary; infrastructure arrives through a port."""

    def __init__(self, port: object | None = None, *legacy_args: object, **_kwargs: object) -> None:
        self._port = port if not legacy_args else None

    def recover(self, command: CanonRecoveryCommand, context: CanonRecoveryDeliveryContext) -> object:
        if self._port is None or not callable(getattr(self._port, "recover", None)):
            del command, context
            raise CanonResourceBoundaryError(
                "Canon Recovery requires an explicitly injected application port"
            )
        if not isinstance(command, CanonRecoveryCommand) or not isinstance(
            context, CanonRecoveryDeliveryContext
        ):
            raise ValueError("Canon Recovery command and delivery context are required")
        return self._port.recover(command, context)
