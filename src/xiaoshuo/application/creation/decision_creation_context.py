"""Immutable delivery metadata for AuthorDecision creation operations (B2b).

``DecisionCreationContext`` carries the caller-supplied
``idempotency_key`` independently from the business command.  It is
delivery metadata — not an HTTP DTO, not part of the request digest,
and does not carry actor, auth, trace, or timestamp fields.

The ``idempotency_key`` must be explicitly different from ``task_id``
and ``decision_id`` and must not be a derived, concatenated, or hashed
value.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DecisionCreationContext:
    """Immutable delivery metadata carrying only a non-empty idempotency key.

    Attributes:
        idempotency_key: A non-empty string that uniquely identifies
            this decision creation attempt for idempotent replay.  Must
            be explicitly supplied by the caller — not derived from
            ``task_id`` or ``decision_id`` or any other business field.
    """

    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.idempotency_key, str) or not self.idempotency_key.strip():
            raise ValueError("idempotency_key must be a non-empty string")
