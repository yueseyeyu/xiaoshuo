"""Independent C3 delivery metadata; never part of Canon request digests."""

from __future__ import annotations

from dataclasses import dataclass


def _require_key(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("idempotency_key must be a non-empty string")


@dataclass(frozen=True, slots=True)
class CanonPrepareDeliveryContext:
    idempotency_key: str

    def __post_init__(self) -> None:
        _require_key(self.idempotency_key)


@dataclass(frozen=True, slots=True)
class CanonApproveDeliveryContext:
    idempotency_key: str

    def __post_init__(self) -> None:
        _require_key(self.idempotency_key)
