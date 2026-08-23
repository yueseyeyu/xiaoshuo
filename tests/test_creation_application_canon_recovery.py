"""C4-PRE boundary tests for the retired C4a Recovery entry."""
from __future__ import annotations

import pytest

from xiaoshuo.application.creation.canon_recovery import RecoverCanonCommitUseCase
from xiaoshuo.application.creation.errors import CanonResourceBoundaryError


def test_recovery_fails_closed_before_any_dependency_is_called() -> None:
    class Bomb:
        def __call__(self):
            raise AssertionError("C4a dependency was touched")

    use_case = RecoverCanonCommitUseCase(Bomb(), Bomb(), Bomb())
    with pytest.raises(CanonResourceBoundaryError, match="disabled during C4-PRE"):
        use_case.recover(object(), object())


def test_recovery_entry_has_no_success_writer_methods() -> None:
    assert not hasattr(RecoverCanonCommitUseCase, "complete")
    assert not hasattr(RecoverCanonCommitUseCase, "resume")
