from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from xiaoshuo.domain.creation.hashing import (
    InvalidContentHash,
    InvalidDomainValue,
    canonicalize_json_value,
    compute_content_hash,
    verify_content_hash,
)


class SampleKind(str, Enum):
    VALUE = "value"


@dataclass(frozen=True)
class SampleData:
    name: str
    kind: SampleKind


def test_dictionary_key_order_does_not_change_hash() -> None:
    assert compute_content_hash({"b": 2, "a": 1}) == compute_content_hash({"a": 1, "b": 2})


def test_chinese_content_is_stable() -> None:
    payload = {"目标": "完成第一章", "元素": ["冲突", "悬念"]}
    assert compute_content_hash(payload) == compute_content_hash(payload)


def test_tuple_and_list_have_equivalent_json_hashes() -> None:
    assert compute_content_hash(("a", 1, True)) == compute_content_hash(["a", 1, True])


def test_enum_and_dataclass_are_canonicalized() -> None:
    value = SampleData(name="sample", kind=SampleKind.VALUE)
    assert canonicalize_json_value(value) == {"name": "sample", "kind": "value"}


def test_aware_datetimes_are_normalized_to_fixed_utc() -> None:
    utc_value = datetime(2026, 1, 2, 3, 4, 5, 123, tzinfo=timezone.utc)
    offset_value = utc_value.astimezone(timezone(timedelta(hours=8)))
    assert canonicalize_json_value(utc_value) == "2026-01-02T03:04:05.000123Z"
    assert compute_content_hash(utc_value) == compute_content_hash(offset_value)


def test_content_change_changes_hash() -> None:
    assert compute_content_hash({"content": "a"}) != compute_content_hash({"content": "b"})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_float_is_rejected(value: float) -> None:
    with pytest.raises(InvalidDomainValue):
        compute_content_hash(value)


@pytest.mark.parametrize("value", [{1, 2}, object(), {1: "non-string-key"}])
def test_unsupported_values_are_rejected(value: object) -> None:
    with pytest.raises(InvalidDomainValue):
        compute_content_hash(value)


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(InvalidDomainValue):
        compute_content_hash(datetime(2026, 1, 1))


def test_hash_verification_passes_and_fails_without_mutation() -> None:
    payload = {"content": "正文"}
    content_hash = compute_content_hash(payload)
    assert verify_content_hash(payload, content_hash) is True
    assert verify_content_hash({"content": "变化"}, content_hash) is False


@pytest.mark.parametrize(
    "expected_hash",
    ["", "sha256:abc", "SHA256:" + "a" * 64, "sha256:" + "A" * 64, "md5:" + "a" * 64],
)
def test_malformed_expected_hash_is_rejected(expected_hash: str) -> None:
    with pytest.raises(InvalidContentHash):
        verify_content_hash({}, expected_hash)

