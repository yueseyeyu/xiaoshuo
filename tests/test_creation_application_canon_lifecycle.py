"""C3 delivery context and digest isolation contracts."""
from __future__ import annotations

import pytest
from dataclasses import FrozenInstanceError

from xiaoshuo.application.creation.canon_commands import ApproveCanonChangesetCommand, PrepareCanonChangesetCommand
from xiaoshuo.application.creation.canon_decision_context import CanonApproveDeliveryContext, CanonPrepareDeliveryContext
from xiaoshuo.application.creation.digest import compute_canon_approve_request_digest, compute_canon_prepare_request_digest
from xiaoshuo.application.creation.operation_kind import OperationKind
from xiaoshuo.application.creation.canon_apply import CanonApplyCommand
from xiaoshuo.application.creation.canon_apply_context import CanonApplyDeliveryContext
from xiaoshuo.application.creation.canon_recovery import CanonRecoveryCommand
from xiaoshuo.application.creation.canon_recovery_context import CanonRecoveryDeliveryContext
from xiaoshuo.application.creation.digest import compute_canon_apply_request_digest, compute_canon_recovery_request_digest


def test_c3_delivery_contexts_are_distinct_frozen_and_require_keys() -> None:
    assert CanonPrepareDeliveryContext("prepare-key").idempotency_key == "prepare-key"
    assert CanonApproveDeliveryContext("approve-key").idempotency_key == "approve-key"
    with pytest.raises(ValueError):
        CanonPrepareDeliveryContext("")
    with pytest.raises(ValueError):
        CanonApproveDeliveryContext(" ")


def test_prepare_digest_uses_only_business_identity_not_delivery_key() -> None:
    command = PrepareCanonChangesetCommand("task", 2, "sha256:" + "a" * 64, b"bundle")
    digest = compute_canon_prepare_request_digest(command, "sha256:" + "b" * 64, OperationKind.PREPARE_CANON_CHANGESET)
    assert digest.startswith("sha256:")
    assert CanonPrepareDeliveryContext("key-one") != CanonPrepareDeliveryContext("key-two")


def test_approve_digest_uses_only_task_decision_revision_and_has_no_context_parameter() -> None:
    command = ApproveCanonChangesetCommand("task", "decision", 3)
    first = compute_canon_approve_request_digest(command, operation_kind=OperationKind.APPROVE_CANON_CHANGESET)
    second = compute_canon_approve_request_digest(command, operation_kind=OperationKind.APPROVE_CANON_CHANGESET)
    assert first == second


def test_p47_apply_recovery_contexts_are_frozen_distinct_and_not_complete_contexts() -> None:
    apply_context = CanonApplyDeliveryContext("apply-key")
    recovery_context = CanonRecoveryDeliveryContext("recovery-key")
    assert apply_context != recovery_context
    with pytest.raises(FrozenInstanceError):
        apply_context.idempotency_key = "changed"  # type: ignore[misc]
    assert not hasattr(OperationKind, "COMPLETE_CANON")
    with pytest.raises(ValueError):
        CanonApplyDeliveryContext("")
    with pytest.raises(ValueError):
        CanonRecoveryDeliveryContext(" ")


def test_p47_apply_and_recovery_digest_exclude_delivery_context() -> None:
    apply_command = CanonApplyCommand("task", "journal", 3)
    recovery_command = CanonRecoveryCommand("task", "journal", 3)
    assert compute_canon_apply_request_digest(apply_command, operation_kind=OperationKind.APPLY_CANON_COMMIT) == compute_canon_apply_request_digest(apply_command, operation_kind=OperationKind.APPLY_CANON_COMMIT)
    assert compute_canon_recovery_request_digest(recovery_command, operation_kind=OperationKind.RECOVER_CANON_COMMIT) == compute_canon_recovery_request_digest(recovery_command, operation_kind=OperationKind.RECOVER_CANON_COMMIT)
