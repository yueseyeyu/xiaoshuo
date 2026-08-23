"""Negative-path-only O1 assertions; execution is authorization-deferred."""

from xiaoshuo.evaluation.contracts.transition import TransitionRow, registry_for
from xiaoshuo.evaluation.owner.transaction import transaction_for


def test_transaction_registry_rejects_unregistered_tuple() -> None:
    row = TransitionRow(1, "HANDLE", "V2", "CALLER", "ISSUED", "USED", "CAS", "SUCCESS", "READY", "MUTATE", "CONTINUE")
    result = registry_for("HANDLE").validate(row)
    assert result.result.value == "OWNER_PRODUCER_UNAVAILABLE"
    assert result.mutated is False


def test_handle_cas_registry_rejects_replay_and_conflict() -> None:
    assert registry_for("HANDLE").validate(None).result.value == "OWNER_PRODUCER_UNAVAILABLE"


def test_retest_requires_owner_issued_fresh_handle() -> None:
    assert registry_for("HANDLE").validate(None).result.value == "OWNER_PRODUCER_UNAVAILABLE"


def test_secret_seal_contract_rejects_wrong_scope_or_key() -> None:
    assert transaction_for("OWNER_SECRET_LIFECYCLE").abort().mutated is False


def test_copy_pickle_rebuild_leave_registry_unchanged() -> None:
    registry = registry_for("HANDLE")
    assert registry.registry_hash is None and registry.rows == ()


def test_cas_winner_and_loser_records() -> None:
    assert transaction_for("HANDLE").abort().published is False


def test_process_epoch_invalidates_old_registry() -> None:
    assert transaction_for("HANDLE").abort().result.value == "OWNER_PRODUCER_UNAVAILABLE"

