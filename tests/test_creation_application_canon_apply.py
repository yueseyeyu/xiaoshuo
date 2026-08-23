"""C4-PRE boundary tests for the retired C4a Apply entry."""
from __future__ import annotations

import pytest

from xiaoshuo.application.creation.canon_apply import ApplyCanonCommitUseCase
from xiaoshuo.application.creation.errors import CanonResourceBoundaryError


def test_apply_fails_closed_before_any_dependency_is_called() -> None:
    class Bomb:
        def __call__(self):
            raise AssertionError("C4a dependency was touched")

    use_case = ApplyCanonCommitUseCase(Bomb(), Bomb(), Bomb(), Bomb())
    with pytest.raises(CanonResourceBoundaryError, match="disabled during C4-PRE"):
        use_case.apply(object(), object())


def test_apply_entry_has_no_success_writer_methods() -> None:
    assert not hasattr(ApplyCanonCommitUseCase, "complete")
    assert not hasattr(ApplyCanonCommitUseCase, "promote")
