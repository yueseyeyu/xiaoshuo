"""Frozen delivery metadata for the Canon Recovery operation."""

from __future__ import annotations

from dataclasses import dataclass


def _require_key(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("idempotency_key must be a non-empty string")


@dataclass(frozen=True, slots=True)
class CanonRecoveryDeliveryContext:
    idempotency_key: str

    def __post_init__(self) -> None:
        _require_key(self.idempotency_key)

