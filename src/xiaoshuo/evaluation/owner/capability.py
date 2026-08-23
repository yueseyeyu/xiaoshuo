"""Composition-root capability seam; O1 has no real producer implementation."""

from dataclasses import dataclass

from ..contracts.owner import ContractResult, unavailable


class OwnerProducerCapabilityV1:
    """Opaque marker that cannot enable a producer in O1."""

    __slots__ = ()

    def __new__(cls, *args: object, **kwargs: object) -> "OwnerProducerCapabilityV1":
        raise TypeError("owner capability is composition-root owned")


@dataclass(frozen=True, slots=True)
class OwnerProducerPortV1:
    """All operations fail closed until a separately authorized producer exists."""

    capability: OwnerProducerCapabilityV1 | None = None

    @classmethod
    def unavailable(cls) -> "OwnerProducerPortV1":
        return cls(None)

    def open_session(self, *args: object, **kwargs: object) -> ContractResult:
        return unavailable()

    def bind_authority(self, receipt: object) -> ContractResult:
        del receipt
        return unavailable("CALLER_AUTHORITY_INJECTION_FORBIDDEN")

    def bind_writer_evidence(self, receipt: object) -> ContractResult:
        del receipt
        return unavailable("CALLER_WRITER_INJECTION_FORBIDDEN")

    def bind_cpython_expected(self, receipt: object) -> ContractResult:
        del receipt
        return unavailable("CALLER_CPYTHON_INJECTION_FORBIDDEN")

    def publish(self, *args: object, **kwargs: object) -> ContractResult:
        return unavailable("PUBLICATION_DISABLED_IN_O1")


__all__ = ["OwnerProducerCapabilityV1", "OwnerProducerPortV1"]
