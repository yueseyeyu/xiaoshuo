"""Delivery metadata for the two independent G0-B authoring operations."""

from __future__ import annotations

from dataclasses import dataclass


def _validate_key(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("idempotency_key must be a non-empty string")


@dataclass(frozen=True, slots=True)
class AuthoringArtifactSubmissionContext:
    """Delivery metadata for ``SUBMIT_AUTHORING_ARTIFACT`` only."""

    idempotency_key: str

    def __post_init__(self) -> None:
        _validate_key(self.idempotency_key)


@dataclass(frozen=True, slots=True)
class DraftReviewSubmissionContext:
    """Delivery metadata for ``SUBMIT_DRAFT_FOR_REVIEW`` only."""

    idempotency_key: str

    def __post_init__(self) -> None:
        _validate_key(self.idempotency_key)
