"""Non-consumable, recursively immutable O1 views."""

from typing import NoReturn


class ReplayDenied(RuntimeError):
    """Raised when a view is copied, serialized, or rebuilt."""


def _deny_replay() -> NoReturn:
    raise ReplayDenied("COPY_SERIALIZATION_REPLAY_DENIED")


class OwnerPublicationViewV1:
    __slots__ = ()

    def __new__(cls, *args: object, **kwargs: object) -> "OwnerPublicationViewV1":
        del cls, args, kwargs
        return _deny_replay()

    def __copy__(self) -> NoReturn:
        return _deny_replay()

    def __deepcopy__(self, memo: dict[int, object]) -> NoReturn:
        del memo
        return _deny_replay()

    def __reduce_ex__(self, protocol: int) -> NoReturn:
        del protocol
        return _deny_replay()


class OwnerHandleViewV1:
    __slots__ = ()

    def __new__(cls, *args: object, **kwargs: object) -> "OwnerHandleViewV1":
        del cls, args, kwargs
        return _deny_replay()

    def __copy__(self) -> NoReturn:
        return _deny_replay()

    def __deepcopy__(self, memo: dict[int, object]) -> NoReturn:
        del memo
        return _deny_replay()

    def __reduce_ex__(self, protocol: int) -> NoReturn:
        del protocol
        return _deny_replay()


class ConsumeReceiptV1:
    __slots__ = ()

    def __new__(cls, *args: object, **kwargs: object) -> "ConsumeReceiptV1":
        del cls, args, kwargs
        return _deny_replay()

    def __copy__(self) -> NoReturn:
        return _deny_replay()

    def __deepcopy__(self, memo: dict[int, object]) -> NoReturn:
        del memo
        return _deny_replay()

    def __reduce_ex__(self, protocol: int) -> NoReturn:
        del protocol
        return _deny_replay()


__all__ = [
    "ConsumeReceiptV1",
    "OwnerHandleViewV1",
    "OwnerPublicationViewV1",
    "ReplayDenied",
]
