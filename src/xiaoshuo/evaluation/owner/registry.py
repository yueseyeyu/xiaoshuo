"""Owner registry skeleton with zero authoritative state and zero mutation."""

from dataclasses import dataclass

from ..contracts.owner import ContractResult, denied


@dataclass(frozen=True, slots=True)
class OwnerRegistryV1:
    """Schema-only O1 registry; all authoritative operations deny."""

    schema_version: str = "OWNER_REGISTRY_V1"
    registry_kind: str = "OWNER_AUTHORITY"
    registry_version: str = "V1"
    owner: None = None
    rows: tuple[object, ...] = ()
    record_count: int = 0
    mutation_count: int = 0
    registry_hash: None = None
    state_readback_status: str = "NOT_AVAILABLE"
    status: str = "DENIED"
    state_preimage_hash: None = None
    state_hash: None = None

    def __post_init__(self) -> None:
        if self.rows != () or self.record_count != 0 or self.mutation_count != 0:
            raise ValueError("O1 registry cannot contain authoritative state")
        if self.registry_hash is not None or self.state_preimage_hash is not None or self.state_hash is not None:
            raise ValueError("O1 registry cannot contain authoritative hashes")
        if self.state_readback_status != "NOT_AVAILABLE" or self.status != "DENIED":
            raise ValueError("O1 registry is rejection-only")

    def lookup(self, handle: object) -> ContractResult:
        del handle
        return denied("REGISTRY_ISSUED_HANDLE_REQUIRED")

    def consume_once(self, handle: object, *, request_nonce: object = None) -> ContractResult:
        del handle, request_nonce
        return denied("REGISTRY_ISSUED_HANDLE_REQUIRED")

    def register_authoritative_record(self, record: object) -> ContractResult:
        del record
        return denied("CALLER_REGISTRY_PUBLICATION_FORBIDDEN")

    def register(self, record: object) -> ContractResult:
        return self.register_authoritative_record(record)


__all__ = ["OwnerRegistryV1"]
