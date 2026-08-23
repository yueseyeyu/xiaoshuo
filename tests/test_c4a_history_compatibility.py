"""C4A-44: historical C3/C4-PRE entry points remain fail-closed."""

from __future__ import annotations

from pathlib import Path

import pytest

from xiaoshuo.application.creation.canon_apply import ApplyCanonCommitUseCase, CanonApplyCommand
from xiaoshuo.application.creation.canon_apply_context import CanonApplyDeliveryContext
from xiaoshuo.application.creation.canon_recovery import RecoverCanonCommitUseCase, CanonRecoveryCommand
from xiaoshuo.application.creation.canon_recovery_context import CanonRecoveryDeliveryContext
from xiaoshuo.application.creation.errors import CanonResourceBoundaryError, LegacyChangesetUnbound, LegacyJournalUnbound


def test_v1_v2_history_and_legacy_fail_closed_contract() -> None:
    v1 = CanonApplyCommand("task", "journal", 0)
    v2 = CanonRecoveryCommand("task", "journal", 0, apply_key="key")
    assert v1.command_schema_version == 1 and v2.command_schema_version == 1
    with pytest.raises(CanonResourceBoundaryError):
        ApplyCanonCommitUseCase().apply(v1, CanonApplyDeliveryContext("key"))
    with pytest.raises(CanonResourceBoundaryError):
        RecoverCanonCommitUseCase().recover(v2, CanonRecoveryDeliveryContext("key"))
    assert issubclass(LegacyChangesetUnbound, Exception)
    assert issubclass(LegacyJournalUnbound, Exception)
