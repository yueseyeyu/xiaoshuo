"""Application boundary for the C4b first Canon activation.

The application layer deliberately knows only the maintenance request and a
small result port.  Seed reading, payload storage, SQLite facts, locks, and
projection files remain behind the infrastructure composition root.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .errors import ActivationInputRejected
from .ports import CanonActivationPort, CanonActivationResult


_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ActivationInputRejected(f"{field} is required")
    return value


def _safe_identifier(value: object, field: str) -> str:
    value = _required_text(value, field)
    if (
        value in {".", ".."}
        or Path(value).name != value
        or any(char in '<>:/\\"|?*' for char in value)
        or value.endswith((" ", "."))
    ):
        raise ActivationInputRejected(f"{field} is not a safe identifier")
    return value


@dataclass(frozen=True, slots=True)
class CanonActivationRequest:
    """Explicit local maintenance input; operator identity is not caller data."""

    project_id: str
    attempt_key: str
    request_digest: str

    def __post_init__(self) -> None:
        for field, value in (
            ("project_id", self.project_id),
            ("attempt_key", self.attempt_key),
        ):
            _safe_identifier(value, field)
        _required_text(self.request_digest, "request_digest")
        if not _DIGEST.fullmatch(self.request_digest):
            raise ActivationInputRejected("request_digest must be a sha256 digest")


class CanonActivationUseCase:
    """Validate an explicit request and delegate to the injected C4b port."""

    def __init__(self, activation_port: CanonActivationPort) -> None:
        if activation_port is None or not callable(getattr(activation_port, "activate", None)):
            raise ActivationInputRejected("activation port is required")
        self._activation_port = activation_port

    def activate(self, request: CanonActivationRequest) -> CanonActivationResult:
        if not isinstance(request, CanonActivationRequest):
            raise ActivationInputRejected("a CanonActivationRequest is required")
        return self._activation_port.activate(request)


ActivateCanonUseCase = CanonActivationUseCase
CanonActivationApplicationService = CanonActivationUseCase
