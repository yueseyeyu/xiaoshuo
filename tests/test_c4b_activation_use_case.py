"""C4B application boundary and stable error vocabulary."""

from __future__ import annotations

import pytest

from xiaoshuo.application.creation.canon_activation import (
    CanonActivationRequest,
    CanonActivationUseCase,
)
from xiaoshuo.application.creation.errors import (
    ActivationConflict,
    ActivationInputRejected,
    ActivationRecoveryRequired,
    CreationApplicationError,
)
from xiaoshuo.application.creation.ports import CanonActivationResult


REQUEST_DIGEST = "sha256:" + "1" * 64


class FakeActivationPort:
    def __init__(self) -> None:
        self.requests = []

    def activate(self, request):
        self.requests.append(request)
        return CanonActivationResult("ACTIVATED", "attempt", request.project_id, "version", "{}")


def test_c4b_16_use_case_delegates_explicit_request_without_operator_input() -> None:
    port = FakeActivationPort()
    request = CanonActivationRequest("project", "attempt-key", REQUEST_DIGEST)
    result = CanonActivationUseCase(port).activate(request)
    assert result.status == "ACTIVATED"
    assert port.requests == [request]
    assert "operator_identity" not in request.__slots__


@pytest.mark.parametrize(
    "candidate",
    [
        object(),
        None,
        {"project_id": "project"},
    ],
)
def test_invalid_application_input_is_stable(candidate) -> None:
    port = FakeActivationPort()
    with pytest.raises(ActivationInputRejected):
        CanonActivationUseCase(port).activate(candidate)


def test_stable_activation_errors_are_application_errors() -> None:
    assert issubclass(ActivationConflict, CreationApplicationError)
    assert issubclass(ActivationRecoveryRequired, CreationApplicationError)
    assert issubclass(ActivationInputRejected, CreationApplicationError)


def test_application_invalid_digest_is_rejected_at_request_boundary() -> None:
    with pytest.raises(ActivationInputRejected):
        CanonActivationRequest("project", "attempt-key", "not-a-digest")


def test_application_port_cannot_be_constructed_without_delegate() -> None:
    with pytest.raises(ActivationInputRejected):
        CanonActivationUseCase(object())
