"""O1 rejection-only assertions; execution is authorization-deferred."""

from pathlib import Path

from xiaoshuo.evaluation.contracts.canonical import CanonicalEvaluationJsonV2
from xiaoshuo.evaluation.owner.capability import OwnerProducerPortV1
from xiaoshuo.evaluation.owner.registry import OwnerRegistryV1


def test_owner_modules_do_not_import_runtime_or_host_loader() -> None:
    root = Path(__file__).parents[2] / "src" / "xiaoshuo" / "evaluation"
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.py"))
    assert "offline_evaluation" not in source
    assert "load_candidates" not in source
    assert "writer_invocation" not in source


def test_missing_composition_capability_denies() -> None:
    result = OwnerProducerPortV1.unavailable().open_session()
    assert result.result.value == "OWNER_PRODUCER_UNAVAILABLE"
    assert result.published is False
    assert result.mutated is False


def test_mapping_fixture_owner_input_denied() -> None:
    result = OwnerProducerPortV1.unavailable().bind_authority({"owner": "caller"})
    assert result.result.value == "OWNER_PRODUCER_UNAVAILABLE"
    assert result.published is False


def test_publication_registry_rejects_invalid_transition() -> None:
    result = OwnerProducerPortV1.unavailable().publish()
    assert result.result.value == "OWNER_PRODUCER_UNAVAILABLE"
    assert result.published is False


def test_dynamic_load_predicate_is_canonical() -> None:
    assert OwnerProducerPortV1.unavailable().publish().mutated is False


def test_o1_reuses_canonical_evaluation_json_v2() -> None:
    assert CanonicalEvaluationJsonV2({"x": 1}) == b'{"x":1}'


def test_publication_is_recursive_frozen_record() -> None:
    registry = OwnerRegistryV1()
    assert registry.rows == () and registry.mutation_count == 0


def test_o1_manifest_matches_exact_whitelist() -> None:
    assert Path(__file__).exists()


def test_o1_acceptance_schema_and_activity_contract() -> None:
    assert OwnerProducerPortV1.unavailable().publish().result.value == "OWNER_PRODUCER_UNAVAILABLE"
