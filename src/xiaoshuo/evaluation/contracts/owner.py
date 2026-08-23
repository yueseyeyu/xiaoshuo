"""Owner-bound result and opaque receipt types for the O1 skeleton."""

from dataclasses import dataclass
from enum import Enum
from typing import Final, NoReturn


class OwnerResult(str, Enum):
    OWNER_PRODUCER_UNAVAILABLE = "OWNER_PRODUCER_UNAVAILABLE"
    DENIED = "DENIED"


OWNER_PRODUCER_UNAVAILABLE: Final = OwnerResult.OWNER_PRODUCER_UNAVAILABLE
DENIED: Final = OwnerResult.DENIED


@dataclass(frozen=True, slots=True)
class ContractResult:
    """Non-publishing result returned by every O1 rejection path."""

    result: OwnerResult
    reason: str
    mutated: bool = False
    value: object | None = None

    @property
    def allowed(self) -> bool:
        return False

    @property
    def published(self) -> bool:
        return False


class OwnerProducerUnavailable(RuntimeError):
    """Raised because O1 has no owner-side authoritative receipt factory."""


def _receipt_constructor_denied() -> NoReturn:
    raise OwnerProducerUnavailable("OWNER_FACTORY_ABSENT")


class OwnerAuthorityReceiptV1:
    __slots__ = ()

    def __new__(cls, *args: object, **kwargs: object) -> "OwnerAuthorityReceiptV1":
        del cls, args, kwargs
        return _receipt_constructor_denied()

    def __reduce_ex__(self, protocol: int) -> NoReturn:
        del protocol
        return _receipt_constructor_denied()


class WriterEvidenceReceiptV1:
    __slots__ = ()

    def __new__(cls, *args: object, **kwargs: object) -> "WriterEvidenceReceiptV1":
        del cls, args, kwargs
        return _receipt_constructor_denied()

    def __reduce_ex__(self, protocol: int) -> NoReturn:
        del protocol
        return _receipt_constructor_denied()


class CpythonExpectedReceiptV1:
    __slots__ = ()

    def __new__(cls, *args: object, **kwargs: object) -> "CpythonExpectedReceiptV1":
        del cls, args, kwargs
        return _receipt_constructor_denied()

    def __reduce_ex__(self, protocol: int) -> NoReturn:
        del protocol
        return _receipt_constructor_denied()


def unavailable(reason: str = "OWNER_PRODUCER_UNAVAILABLE") -> ContractResult:
    return ContractResult(OWNER_PRODUCER_UNAVAILABLE, reason)


def denied(reason: str) -> ContractResult:
    return ContractResult(DENIED, reason)


__all__ = [
    "CpythonExpectedReceiptV1",
    "ContractResult",
    "DENIED",
    "OWNER_PRODUCER_UNAVAILABLE",
    "OwnerAuthorityReceiptV1",
    "OwnerProducerUnavailable",
    "OwnerResult",
    "WriterEvidenceReceiptV1",
    "denied",
    "unavailable",
]
