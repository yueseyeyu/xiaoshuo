"""Canonical transition row schemas with no O1 publication capability."""

from dataclasses import dataclass
from typing import ClassVar

from .canonical import CanonicalEvaluationJsonV2, sha256_bytes
from .owner import ContractResult, denied


REGISTRY_CARDINALITIES = {
    "TRANSACTION": 19,
    "PUBLICATION": 13,
    "HANDLE": 9,
    "EVALUATION_ATTEMPT": 45,
    "OWNER_SECRET_LIFECYCLE": 14,
}


@dataclass(frozen=True, slots=True)
class TransitionRow:
    row_id: int
    registry_kind: str
    registry_version: str
    owner: str
    from_state: str
    to_state: str
    event_kind: str
    result_kind: str
    status: str
    mutation: str
    terminal: str
    registry_hash: str | None = None
    registry_count: int | None = None
    row_hash: str | None = None

    FIELD_ORDER: ClassVar[tuple[str, ...]] = (
        "row_id",
        "registry_kind",
        "registry_version",
        "owner",
        "from_state",
        "to_state",
        "event_kind",
        "result_kind",
        "status",
        "mutation",
        "terminal",
        "registry_hash",
        "registry_count",
        "row_hash",
    )
    ROW_PREIMAGE_FIELDS: ClassVar[tuple[str, ...]] = FIELD_ORDER[:11]

    def row_preimage(self) -> tuple[object, ...]:
        return tuple(getattr(self, field) for field in self.ROW_PREIMAGE_FIELDS)

    def row_preimage_bytes(self) -> bytes:
        payload = dict(zip(self.ROW_PREIMAGE_FIELDS, self.row_preimage()))
        return CanonicalEvaluationJsonV2(payload, fields=self.ROW_PREIMAGE_FIELDS)

    def computed_row_hash(self) -> str:
        return sha256_bytes(self.row_preimage_bytes())

    def is_self_consistent(self) -> bool:
        return False


def canonical_row_preimage(row: TransitionRow) -> bytes:
    if type(row) is not TransitionRow:
        raise TypeError("transition row required")
    return row.row_preimage_bytes()


@dataclass(frozen=True, slots=True)
class TransitionRegistry:
    """Schema-only registry; no caller can publish authoritative rows in O1."""

    registry_kind: str
    registry_version: str = "V2"

    @property
    def expected_count(self) -> int:
        return REGISTRY_CARDINALITIES[self.registry_kind]

    @property
    def rows(self) -> tuple[TransitionRow, ...]:
        return ()

    @property
    def registry_hash(self) -> None:
        return None

    def validate(self, row: object) -> ContractResult:
        del row
        return denied("OWNER_PRODUCER_UNAVAILABLE")

    def register(self, row: object) -> ContractResult:
        del row
        return denied("CALLER_REGISTRY_MUTATION_FORBIDDEN")


def registry_for(registry_kind: str) -> TransitionRegistry:
    if registry_kind not in REGISTRY_CARDINALITIES:
        raise ValueError("unknown transition registry")
    return TransitionRegistry(registry_kind)


__all__ = [
    "REGISTRY_CARDINALITIES",
    "TransitionRegistry",
    "TransitionRow",
    "canonical_row_preimage",
    "registry_for",
]
