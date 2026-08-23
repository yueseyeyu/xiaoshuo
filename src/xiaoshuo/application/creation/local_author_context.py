"""Controlled local author context for B2b MVP (ADR-015).

This module provides the ONLY mechanism for producing a trusted AUTHOR
identity within the B2b MVP boundary.  The identity is stable, unique,
and generated at construction time — callers cannot supply, forge, or
override it.

This context is valid ONLY within the ADR-015 local, single-operator,
no-HTTP/API/remote/multi-user boundary.  It does NOT constitute a G05
global lift and must not be reused outside that boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from xiaoshuo.domain.creation import SourceKind, SourceRef


class LocalAuthorContext(Protocol):
    """Protocol for a controlled local author identity provider.

    Implementations must produce a stable, unique AUTHOR SourceRef whose
    actor_id is not supplied by the caller.  This is a construction-time
    dependency — callers cannot inject a different identity per call.
    """

    def author_source(self) -> SourceRef:
        """Return the stable AUTHOR SourceRef for this local context."""
        ...

    @property
    def author_id(self) -> str:
        """Return the stable author_id string."""
        ...


@dataclass(frozen=True, slots=True)
class LocalAuthorContextImpl:
    """Concrete implementation of LocalAuthorContext.

    The author_id is supplied at construction time (typically by the
    application composition root) and cannot be changed or overridden
    by callers.  This ensures that within the local single-operator
    boundary, exactly one trusted author identity exists.

    Args:
        author_id: A non-empty, stable author identity string.  Must
            be supplied by the composition root, not by callers.
    """

    _author_id: str

    def __post_init__(self) -> None:
        if not isinstance(self._author_id, str) or not self._author_id.strip():
            raise ValueError("author_id must be a non-empty string")

    def author_source(self) -> SourceRef:
        return SourceRef(kind=SourceKind.AUTHOR, actor_id=self._author_id)

    @property
    def author_id(self) -> str:
        return self._author_id
