"""Rejection-only transaction façade over closed transition schemas."""

from dataclasses import dataclass

from ..contracts.owner import ContractResult, unavailable
from ..contracts.transition import REGISTRY_CARDINALITIES, TransitionRegistry, registry_for


@dataclass(frozen=True, slots=True)
class OwnerTransactionV1:
    """No transition can become authoritative in O1."""

    registry: TransitionRegistry

    def apply(self, row: object) -> ContractResult:
        return self.registry.validate(row)

    def abort(self, reason: str = "O1_ABORT") -> ContractResult:
        del reason
        return unavailable("OWNER_PRODUCER_UNAVAILABLE")


def transaction_for(registry_kind: str) -> OwnerTransactionV1:
    if registry_kind not in REGISTRY_CARDINALITIES:
        raise ValueError("unknown transition registry")
    return OwnerTransactionV1(registry_for(registry_kind))


def reject_unregistered(row: object) -> ContractResult:
    del row
    return unavailable("OWNER_PRODUCER_UNAVAILABLE")


__all__ = [
    "OwnerTransactionV1",
    "REGISTRY_CARDINALITIES",
    "reject_unregistered",
    "transaction_for",
]
