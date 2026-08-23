"""evaluation 合同使用的独立 canonical JSON V2 实现。"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any


class EvaluationError(ValueError):
    """评价合同输入不满足严格规则时使用的错误。"""

    def __init__(self, code: str, message: str = "evaluation contract violation", **details: Any):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


INTEGER_GRAMMAR_022 = re.compile(r"^(?:0|-?[1-9][0-9]*)$")


def _error(code: str, message: str, **details: Any) -> EvaluationError:
    return EvaluationError(code, message, **details)


def _nfc(value: str, *, field: str) -> str:
    if not isinstance(value, str):
        raise _error("DENIED_INPUT", f"{field} must be a string")
    if "\x00" in value:
        raise _error("DENIED_INPUT", f"{field} contains NUL")
    normalized = unicodedata.normalize("NFC", value)
    if normalized != value:
        raise _error("DENIED_INPUT", f"{field} is not NFC")
    return value


def _validate_json_value(value: Any, *, path: str = "") -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        raise _error("DENIED_INPUT", f"JSON float is forbidden at {path or '$'}")
    if isinstance(value, str):
        return _nfc(value, field=path or "value")
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        normalized_keys: set[str] = set()
        for key, item in value.items():
            if not isinstance(key, str):
                raise _error("DENIED_INPUT", f"JSON object key is not a string at {path or '$'}")
            normalized_key = _nfc(key, field=f"{path or '$'}.key")
            if normalized_key in normalized_keys:
                raise _error("DENIED_INPUT", f"duplicate NFC JSON key {normalized_key!r}")
            normalized_keys.add(normalized_key)
            result[normalized_key] = _validate_json_value(
                item,
                path=f"{path or '$'}.{normalized_key}",
            )
        return result
    if isinstance(value, (list, tuple)):
        return [
            _validate_json_value(item, path=f"{path or '$'}[{index}]")
            for index, item in enumerate(value)
        ]
    raise _error("DENIED_INPUT", f"unsupported JSON value at {path or '$'}")


def _validate_integer_token(token: str) -> int:
    if not INTEGER_GRAMMAR_022.fullmatch(token):
        raise _error("DENIED_INPUT", f"non-canonical integer token {token!r}")
    return int(token)


def _reject_float(_: str) -> Any:
    raise _error("DENIED_INPUT", "JSON floating point values are forbidden")


def _reject_constant(token: str) -> Any:
    raise _error("DENIED_INPUT", f"JSON constant {token} is forbidden")


def _pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    raw_keys: set[str] = set()
    normalized_keys: set[str] = set()
    for key, value in pairs:
        if key in raw_keys:
            raise _error("DENIED_INPUT", f"duplicate raw JSON key {key!r}")
        raw_keys.add(key)
        normalized_key = unicodedata.normalize("NFC", key)
        if normalized_key in normalized_keys:
            raise _error("DENIED_INPUT", f"duplicate NFC JSON key {normalized_key!r}")
        normalized_keys.add(normalized_key)
        result[key] = value
    return result


def _check_fields(value: Mapping[str, Any], fields: Sequence[str], *, name: str) -> None:
    if not isinstance(value, Mapping) or tuple(value.keys()) != tuple(fields):
        raise _error("DENIED_INPUT", f"{name} fields are missing, extra, reordered or duplicated")


def canonical_evaluation_json_bytes(
    value: Mapping[str, Any], *, fields: Sequence[str] | None = None
) -> bytes:
    """按固定 UTF-8、无空白、保留字段顺序规则生成 canonical JSON V2。"""
    if fields is not None:
        _check_fields(value, fields, name="canonical object")
    normalized = _validate_json_value(value)
    if fields is not None:
        _check_fields(normalized, fields, name="canonical object")
    try:
        text = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        return text.encode("utf-8")
    except (TypeError, UnicodeEncodeError, ValueError) as exc:
        raise _error("DENIED_INPUT", "value cannot be canonicalized") from exc


def parse_canonical_evaluation_json(
    raw: bytes, *, fields: Sequence[str] | None = None
) -> Any:
    """解析并重新生成输入，只有字节级完全一致时才接受。"""
    if not isinstance(raw, bytes):
        raise _error("DENIED_INPUT", "canonical input must be bytes")
    if raw.startswith(b"\xef\xbb\xbf") or b"\x00" in raw:
        raise _error("DENIED_INPUT", "canonical input contains BOM or NUL")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _error("DENIED_INPUT", "canonical input is not strict UTF-8") from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_pairs_hook,
            parse_int=_validate_integer_token,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
        )
    except EvaluationError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise _error("DENIED_INPUT", "invalid JSON") from exc
    value = _validate_json_value(value)
    if fields is not None:
        _check_fields(value, fields, name="canonical object")
    canonical = canonical_evaluation_json_bytes(value, fields=fields)
    if canonical != raw:
        raise _error("DENIED_INPUT", "input bytes are not canonical JSON V2")
    return value


def sha256_bytes(value: bytes) -> str:
    """返回输入字节的十六进制 SHA-256。"""
    return hashlib.sha256(value).hexdigest()


CanonicalEvaluationJsonV2 = canonical_evaluation_json_bytes


__all__ = [
    "CanonicalEvaluationJsonV2",
    "EvaluationError",
    "canonical_evaluation_json_bytes",
    "parse_canonical_evaluation_json",
    "sha256_bytes",
]
