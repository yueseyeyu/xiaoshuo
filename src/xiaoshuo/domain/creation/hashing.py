"""Deterministic hashing for explicit creation-domain content payloads."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import TypeAlias

JsonScalar: TypeAlias = None | bool | int | float | str
CanonicalJsonValue: TypeAlias = (
    JsonScalar | list["CanonicalJsonValue"] | dict[str, "CanonicalJsonValue"]
)

_CONTENT_HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class CreationDomainError(Exception):
    """Base error for creation-domain protocol violations."""


class InvalidDomainValue(CreationDomainError, ValueError):
    """Raised when a value cannot participate in the domain protocol."""


class InvalidContentHash(InvalidDomainValue):
    """Raised when a content hash is malformed or does not match its payload."""


def canonicalize_json_value(value: object) -> CanonicalJsonValue:
    """Convert supported values into deterministic JSON-compatible values."""
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InvalidDomainValue("NaN and Infinity are not supported")
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise InvalidDomainValue("datetime values must be timezone-aware")
        utc_value = value.astimezone(timezone.utc)
        return utc_value.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, Enum):
        return canonicalize_json_value(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: canonicalize_json_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, (list, tuple)):
        return [canonicalize_json_value(item) for item in value]
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise InvalidDomainValue("JSON object keys must be strings")
        return {key: canonicalize_json_value(item) for key, item in value.items()}
    raise InvalidDomainValue(f"unsupported canonical JSON type: {type(value).__name__}")


def compute_content_hash(value: object) -> str:
    """Hash an explicit payload using canonical UTF-8 JSON."""
    canonical = canonicalize_json_value(value)
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def validate_content_hash_format(value: str) -> None:
    """Require the protocol's lowercase SHA-256 representation."""
    if not isinstance(value, str) or _CONTENT_HASH_PATTERN.fullmatch(value) is None:
        raise InvalidContentHash("content hash must use sha256:<64 lowercase hex> format")


def verify_content_hash(value: object, expected_hash: str) -> bool:
    """Validate and compare an expected hash without accepting malformed input."""
    validate_content_hash_format(expected_hash)
    return hmac.compare_digest(compute_content_hash(value), expected_hash)

