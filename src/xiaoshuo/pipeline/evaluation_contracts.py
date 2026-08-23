"""Strict, owner-bound contracts for the offline deterministic evaluator.

This module deliberately contains only standard-library code.  It does not
discover a project, read configuration, import the legacy pipeline, create a
root, or initialise logging/checkpoint/cache state.  The owner/harness in
``offline_evaluation`` supplies all mutable runtime authority explicitly.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import threading
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Iterable

__all__: list[str] = []


class EvaluationError(ValueError):
    """Typed fail-closed error for P1 admission and evaluation."""

    def __init__(self, code: str, message: str = "evaluation contract violation", **details: Any):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


DECIMAL_GRAMMAR_022 = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?$")
INTEGER_GRAMMAR_022 = re.compile(r"^(?:0|-?[1-9][0-9]*)$")
HEX64_GRAMMAR = re.compile(r"^[0-9a-f]{64}$")
BASE64_GRAMMAR = re.compile(
    r"^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$"
)

P1_FORBIDDEN_CAPABILITIES = (
    "import", "dynamic_import", "module_main", "in_process", "process_spawn",
    "logger", "checkpoint", "state", "cache", "writer", "network", "api",
    "service", "model", "config_discovery", "project_discovery",
)
P1_CAPABILITY_PROBE_FIELDS = P1_FORBIDDEN_CAPABILITIES
P1_PERMITTED_LOAD_OBSERVATION_FIELDS = (
    "permitted_candidate_load_count", "permitted_candidate_modules",
)
EVALUATION_OUTPUT_ROLE_ORDER = ("semantic-result.json", "full-evidence.json")

EVALUATION_INPUT_MANIFEST_FIELDS = (
    "manifest_schema_version", "evaluation_case_id", "project_id", "project_revision",
    "profile_id", "profile_version", "profile_definition_hash", "genre_identity",
    "namespace_digest", "project_registry_snapshot_hash", "input_artifact_identity",
    "artifact_resolver_snapshot_hash", "parent_store_snapshot_hash",
    "capability_census_snapshot_hash", "preimport_gate_snapshot_hash",
    "resolution_guard_snapshot_hash", "writer_trace_plan_snapshot_hash", "rule_set_id",
    "rule_set_version", "rule_set_registry_snapshot_hash", "rule_set_bytes_sha256",
    "evaluator_source_registry_snapshot_hash", "evaluator_source_hash", "contract_id",
    "contract_version", "contract_registry_snapshot_hash", "evaluation_contract_hash",
    "expected_schema_id", "declared_metrics",
)
ARTIFACT_REF_IDENTITY_FIELDS = (
    "project_id", "profile_id", "profile_version", "profile_definition_hash",
    "project_revision", "namespace_digest", "root_alias", "relative_path", "source_ref",
    "producer_version", "batch_id", "parent_refs", "content_length", "content_sha256",
    "integrity_digest",
)
EVALUATION_BATCH_BINDING_FIELDS = (
    "binding_schema_version", "evaluation_case_id", "project_registry_snapshot_hash",
    "input_manifest_hash", "artifact_resolver_snapshot_hash", "parent_store_snapshot_hash",
    "capability_census_snapshot_hash", "preimport_gate_snapshot_hash",
    "resolution_guard_snapshot_hash", "writer_trace_plan_snapshot_hash", "rule_set_id",
    "rule_set_version", "rule_set_registry_snapshot_hash", "rule_set_bytes_sha256",
    "evaluator_source_registry_snapshot_hash", "evaluator_source_hash", "contract_id",
    "contract_version", "contract_registry_snapshot_hash", "evaluation_contract_hash",
    "expected_schema_id", "declared_metrics",
)
SEMANTIC_RESULT_FIELDS = (
    "semantic_schema_version", "evaluation_case_id", "project_id", "project_revision",
    "profile_id", "profile_version", "profile_definition_hash", "genre_identity",
    "namespace_digest", "project_registry_snapshot_hash", "input_manifest_hash",
    "artifact_resolver_snapshot_hash", "parent_store_snapshot_hash",
    "capability_census_snapshot_hash", "rule_set_id", "rule_set_version",
    "rule_set_registry_snapshot_hash", "rule_set_bytes_sha256",
    "evaluator_source_registry_snapshot_hash", "evaluator_source_hash", "contract_id",
    "contract_version", "contract_registry_snapshot_hash", "evaluation_contract_hash",
    "evaluation_binding_hash", "expected_schema_id", "declared_metrics", "metric_results",
    "findings", "classification",
)
SEMANTIC_RESULT_EXCLUDED_FIELDS = (
    "stage_alias", "root_alias", "run_id", "batch_id", "attempt_id", "started_at_utc",
    "finished_at_utc", "batch_digest", "evidence_envelope_hash", "input_artifact_path",
    "output_artifact_path", "full_evidence_path", "tool_boundary", "logger_events",
    "counter_trace", "snapshot_id", "module_identity_ref", "trace_id", "owner_session_id",
    "thread_id", "native_thread_id", "thread_identity_ref", "observation_id",
    "permit_instance_id", "private_handle_identity", "issued_at_utc", "consumed_at_utc",
    "installation_token", "resolved_path", "root_final_path", "parent_final_path",
    "target_final_path", "final_path_identity_digest", "exception_message_sha256",
    "residue_evidence_hash", "trace_evidence_hash",
)
DETERMINISTIC_GUARD_FIELDS = (
    "guard_schema_version", "authority_ref", "source_snapshot_hash", "path_snapshot_hash",
    "finder_snapshot_hash", "modules_snapshot_hash", "candidate_module_set",
    "candidate_source_path_set", "bootstrap_module_set", "source_alias_set",
    "ambient_resolution_policy",
)
DETERMINISTIC_TRACE_EVENT_FIELDS = (
    "sequence", "event_kind", "channel", "action", "module_path", "source_ref",
    "allowed", "outcome",
)
WRITER_EVENT_ACTIONS = ("transaction_started", "writer_call_started", "return", "raise")
WRITER_EVENT_OUTCOME_GRAMMAR = re.compile(
    r"^(?:transaction_started|writer_call_started|return|raise)@[0-9]+$"
)
WRITER_TRACE_EVENT_FIELDS = (
    "sequence", "event_kind", "channel", "action", "module_path", "source_ref",
    "allowed", "offset", "outcome",
)
WRITER_INVOCATION_FIELDS = (
    "invocation_schema_version", "invocation_sequence", "phase",
    "transaction_started", "writer_call_started", "terminal_action",
    "terminal_outcome", "transaction_offset", "writer_offset", "terminal_offset",
    "target_relative_path", "target_final_path", "artifact_identity",
    "module_path", "source_ref", "trace_plan_snapshot_hash", "trace_hash", "events",
    "exception_code", "exception_type", "exception_message_sha256",
    "partial_readback_status", "partial_length", "partial_sha256",
)
DETERMINISTIC_WRITER_OBSERVATION_FIELDS = (
    "writer_schema_version", "trace_plan_snapshot_hash", "trace_backend_status", "phase",
    "transaction_started", "writer_call_started", "writer_returned", "writer_raised", "outcome",
    "exception_code", "exception_type", "exception_message_sha256", "failure_reason",
    "failure_classification", "trace_hook_replaced", "root_relative_path", "parent_relative_path",
    "target_relative_path", "target_relative_paths", "partial_readback_status", "partial_length",
    "partial_sha256", "residue_snapshot_hash", "root_final_path", "parent_final_path",
    "target_final_paths", "trace_hash", "events", "writer_invocations",
)
DETERMINISTIC_RESIDUE_ENTRY_FIELDS = (
    "relative_path", "entry_role", "entry_kind", "exists", "readable", "content_length",
    "content_sha256", "readback_status", "reparse_status", "containment_status",
    "final_identity",
)
RESIDUE_ENTRY_ROLES = ("ROOT", "EXPECTED_PARENT", "EXPECTED_TARGET", "EXPECTED_DESCENDANT", "UNEXPECTED")
RESIDUE_ENTRY_KINDS = ("DIRECTORY", "FILE", "PARTIAL_FILE", "MISSING")
RESIDUE_READBACK_STATUSES = ("EXPECTED", "MISSING", "DIRECTORY", "READ", "PARTIAL")
WRITER_FAILURE_EVIDENCE_FIELDS = (
    "failure_schema_version", "classification", "exception_code", "exception_type",
    "exception_message_sha256", "root_status", "residue_snapshot", "residue_snapshot_hash",
    "residue_entries", "partial_file_detected", "residue_enumeration_error",
    "writer_phase_observation", "zero_residue_claim", "failure_evidence_hash",
)
WRITER_FAILURE_EVIDENCE_PREIMAGE_FIELDS = WRITER_FAILURE_EVIDENCE_FIELDS[:-1]
DETERMINISTIC_SEMANTIC_RESULT_FIELDS = (
    "semantic_schema_version", "evaluation_contract_hash", "project_registry_snapshot_hash",
    "rule_set_snapshot_hash", "evaluator_source_snapshot_hash", "census_snapshot_hash",
    "resolution_guard_snapshot_hash", "resolution_trace_hash", "loaded_source_snapshot_hash",
    "writer_trace_plan_snapshot_hash", "guard_projection", "trace_projection",
    "loaded_source_projection", "writer_projection", "residue_projection", "metrics",
    "findings", "status",
)

RULE_SET_REGISTRY_FIELDS = (
    "registry_schema_version", "registry_id", "owner_id", "authoritative_source_ref",
    "snapshot_id", "read_only", "entries",
)
RULE_SET_ENTRY_FIELDS = (
    "rule_set_id", "rule_set_version", "entry_source_ref", "rule_set_bytes_b64",
    "rule_set_bytes_sha256", "entry_status",
)
CONTRACT_REGISTRY_FIELDS = (
    "registry_schema_version", "registry_id", "owner_id", "authoritative_source_ref",
    "snapshot_id", "read_only", "entries",
)
CONTRACT_ENTRY_FIELDS = (
    "contract_id", "contract_version", "entry_source_ref", "contract_bytes_b64",
    "contract_bytes_sha256", "entry_status",
)
EVALUATOR_SOURCE_REGISTRY_FIELDS = (
    "registry_schema_version", "registry_id", "owner_id", "authoritative_source_ref",
    "snapshot_id", "source_root_alias", "read_only", "entries",
)
EVALUATOR_SOURCE_ENTRY_FIELDS = (
    "relative_path", "source_ref", "length", "sha256", "source_role",
)
EVALUATOR_SOURCE_ROLES = ("evaluator", "candidate", "static", "manifest", "bootstrap")
BOOTSTRAP_MODULE_ENTRY_FIELDS = (
    "module_path", "resolved_path", "source_ref", "source_length", "source_sha256",
    "readback_sha256", "module_identity", "spec_origin", "runtime_identity_hash",
)
EVALUATOR_SOURCE_ENTRIES_PREIMAGE_FIELDS = ("entries",)
CAPABILITY_CENSUS_REGISTRY_FIELDS = (
    "registry_schema_version", "registry_id", "owner_id", "authoritative_source_ref",
    "snapshot_id", "read_only", "entries",
)
CAPABILITY_CENSUS_ENTRY_FIELDS = (
    "module_path", "source_relative_path", "source_ref", "source_length", "source_sha256",
    "static_imports", "transitive_modules", "dynamic_imports", "unknown_dynamic_imports",
    "unresolved_dependencies", "unresolved_writers", "module_main", "in_process_call",
    "process_spawn", "logger_call", "checkpoint_call", "state_call", "cache_call",
    "writer_call", "network_call", "api_call", "service_call", "model_call",
    "config_discovery", "project_discovery", "top_level_logger_side_effect",
    "top_level_checkpoint_side_effect", "top_level_state_side_effect",
    "top_level_cache_side_effect", "top_level_writer_side_effect",
    "top_level_network_side_effect", "top_level_model_side_effect",
    "top_level_config_discovery", "top_level_project_discovery", "writer_paths",
)
PREIMPORT_GATE_FIELDS = (
    "gate_schema_version", "gate_id", "owner_id", "authority_ref",
    "capability_census_snapshot_hash", "evaluator_source_registry_snapshot_hash",
    "owner_probe_binding_hash",
    "resolution_guard_snapshot_hash", "writer_trace_plan_snapshot_hash", "candidate_modules",
    "static_module_allowlist", "dynamic_import_allowlist", "read_only", "no_root_creation",
    "no_config_discovery", "no_project_discovery",
)
IMPORT_PERMIT_PREIMAGE_FIELDS = (
    "permit_schema_version", "owner_id", "authority_ref", "gate_id",
    "preimport_gate_snapshot_hash", "capability_census_snapshot_hash",
    "evaluator_source_registry_snapshot_hash", "candidate_modules", "static_module_allowlist",
    "dynamic_import_allowlist", "read_only", "no_root_creation", "no_config_discovery",
    "no_project_discovery",
)
RESOLUTION_GUARD_FIELDS = (
    "guard_schema_version", "guard_id", "owner_id", "authority_ref", "sys_path_snapshot",
    "cwd_snapshot", "meta_path_snapshot", "path_hooks_snapshot", "sys_modules_snapshot",
    "candidate_closure_modules", "preloaded_candidate_modules",
    "preloaded_candidate_source_paths", "bootstrap_module_entries", "read_only",
    "deny_sys_path_read", "deny_cwd_read", "deny_fallback_finder", "deny_sys_modules_reuse",
    "deny_builtin_ambient_load",
)
LOADED_MODULE_BINDING_FIELDS = (
    "load_sequence", "module_path", "resolved_path", "source_relative_path", "source_ref",
    "source_length", "source_sha256", "preload_length", "preload_sha256",
    "postload_length", "postload_sha256", "module_file", "spec_origin",
)
WRITER_TRACE_PLAN_FIELDS = (
    "plan_schema_version", "plan_id", "owner_id", "authority_ref", "provenance_source_ref",
    "provenance_source_sha256", "safe_write_qualname", "safe_write_code_filename",
    "safe_write_first_line", "safe_write_code_object_sha256", "trace_backend",
    "trace_thread_id", "transaction_call_line", "transaction_call_offset", "writer_call_line",
    "writer_call_offset", "read_only",
)
RESIDUE_PAIRING_FIELDS = (
    "pairing_schema_version", "kind_compatibility_matrix_version",
    "kind_compatibility_matrix_hash", "relative_path", "relative_path_key_utf8_hex",
    "expected_count", "actual_count", "expected_entry_role", "actual_entry_role",
    "actual_exists", "expected_entry_kind", "actual_entry_kind", "pair_status",
)
RESIDUE_PAIRING_HASH_PREIMAGE_FIELDS = (
    "pairing_schema_version", "kind_compatibility_matrix_version",
    "kind_compatibility_matrix_hash", "residue_pairing",
)
RESIDUE_KIND_COMPATIBILITY_MATRIX_PREIMAGE_FIELDS = (
    "matrix_schema_version", "matrix_version", "rows",
)
RESIDUE_KIND_COMPATIBILITY_MATRIX_ROW_FIELDS = (
    "expected_entry_role", "allowed_actual_kinds",
)
RESIDUE_KIND_COMPATIBILITY_MATRIX_VERSION = "RESIDUE_KIND_COMPATIBILITY_V1"
RESIDUE_KIND_COMPATIBILITY_MATRIX = (
    ("ROOT", ("DIRECTORY",)),
    ("EXPECTED_PARENT", ("DIRECTORY",)),
    ("EXPECTED_TARGET", ("FILE",)),
    ("EXPECTED_DESCENDANT", ("DIRECTORY", "FILE")),
)
RESIDUE_SNAPSHOT_PREIMAGE_FIELDS = (
    "residue_schema_version", "root_relative_alias", "residue_array_order",
    "expected_entries", "entries", "residue_pairing", "residue_pairing_hash",
    "enumeration_complete", "enumeration_failure",
)


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


def normalize_relative_path(value: str, *, allow_root: bool = True) -> str:
    value = _nfc(value, field="relative_path")
    if value == "":
        if allow_root:
            return value
        raise _error("DENIED_INPUT", "root relative path is not allowed here")
    if "\\" in value or value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise _error("DENIED_INPUT", "relative path must use forward slashes")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise _error("DENIED_INPUT", "relative path contains an empty or dot segment")
    return value


def validate_evaluation_output_role_order(values: Sequence[str]) -> tuple[str, str]:
    """Require the fixed semantic/evidence output role order before admission."""
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise _error("DENIED_INPUT", "evaluation output roles must be a sequence")
    paths = tuple(values)
    if paths != EVALUATION_OUTPUT_ROLE_ORDER:
        raise _error(
            "DENIED_INPUT",
            "evaluation output roles must be semantic-result.json then full-evidence.json",
            expected=list(EVALUATION_OUTPUT_ROLE_ORDER), actual=list(paths),
        )
    for path in paths:
        if normalize_relative_path(path, allow_root=False) != path:
            raise _error("PATH_ESCAPE", "evaluation output role path is not canonical")
    return paths


def relative_path_key_utf8_hex(relative_path: str) -> str:
    canonical = normalize_relative_path(relative_path)
    return canonical.encode("utf-8").hex()


def validate_relative_path_key(relative_path: str, encoded: Any) -> str:
    expected = relative_path_key_utf8_hex(relative_path)
    if not isinstance(encoded, str):
        raise _error("DENIED_INPUT", "relative_path_key_utf8_hex must be one JSON string")
    if encoded != encoded.lower() or encoded.startswith("0x") or len(encoded) % 2:
        raise _error("DENIED_INPUT", "relative path key is not lowercase even hex")
    if not re.fullmatch(r"[0-9a-f]*", encoded):
        raise _error("DENIED_INPUT", "relative path key contains non-hex bytes")
    try:
        decoded = bytes.fromhex(encoded).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise _error("DENIED_INPUT", "relative path key is not strict UTF-8") from exc
    if decoded != normalize_relative_path(relative_path) or encoded != expected:
        raise _error("DENIED_INPUT", "caller relative path key mismatch")
    return encoded


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
            result[normalized_key] = _validate_json_value(item, path=f"{path or '$'}.{normalized_key}")
        return result
    if isinstance(value, (list, tuple)):
        return [_validate_json_value(item, path=f"{path or '$'}[{index}]") for index, item in enumerate(value)]
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


def canonical_evaluation_json_bytes(value: Mapping[str, Any], *, fields: Sequence[str] | None = None) -> bytes:
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


def parse_canonical_evaluation_json(raw: bytes, *, fields: Sequence[str] | None = None) -> Any:
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
    return hashlib.sha256(value).hexdigest()


def canonical_sha256(value: Mapping[str, Any], *, fields: Sequence[str] | None = None) -> str:
    return sha256_bytes(canonical_evaluation_json_bytes(value, fields=fields))


def _canonical_residue_entry(value: Mapping[str, Any], *, name: str) -> dict[str, Any]:
    item = _copy_mapping(value, DETERMINISTIC_RESIDUE_ENTRY_FIELDS, name=name)
    if normalize_relative_path(item["relative_path"]) != item["relative_path"]:
        raise _error("DENIED_RESIDUE", f"{name} relative path is not canonical")
    if item["entry_role"] not in RESIDUE_ENTRY_ROLES or item["entry_kind"] not in RESIDUE_ENTRY_KINDS:
        raise _error("DENIED_RESIDUE", f"{name} role or kind is not closed")
    if not isinstance(item["exists"], bool) or not isinstance(item["readable"], bool):
        raise _error("DENIED_RESIDUE", f"{name} exists/readable type is invalid")
    length = item["content_length"]
    if length is not None and (not isinstance(length, int) or isinstance(length, bool) or length < 0):
        raise _error("DENIED_RESIDUE", f"{name} content length is invalid")
    digest = item["content_sha256"]
    if digest is not None:
        validate_hash(digest, field=f"{name}.content_sha256")
    if item["readback_status"] not in RESIDUE_READBACK_STATUSES:
        raise _error("DENIED_RESIDUE", f"{name} readback status is not closed")
    if item["reparse_status"] != "VERIFIED" or item["containment_status"] != "VERIFIED":
        raise _error("DENIED_RESIDUE", f"{name} reparse or containment is not verified")
    if not isinstance(item["final_identity"], str) or not item["final_identity"]:
        raise _error("DENIED_RESIDUE", f"{name} final identity is missing")
    if item["entry_kind"] == "MISSING":
        if item["exists"] or item["readable"] or item["readback_status"] != "MISSING" or length is not None or digest is not None:
            raise _error("DENIED_RESIDUE", f"{name} missing entry is inconsistent")
    elif item["entry_kind"] == "DIRECTORY":
        if not item["exists"] or not item["readable"] or item["readback_status"] not in {"DIRECTORY", "EXPECTED"} or length is not None or digest is not None:
            raise _error("DENIED_RESIDUE", f"{name} directory entry is inconsistent")
    elif item["entry_kind"] == "FILE":
        if not item["exists"] or not item["readable"] or length is None or digest is None or item["readback_status"] not in {"READ", "EXPECTED"}:
            raise _error("DENIED_RESIDUE", f"{name} file entry is incomplete")
    else:
        if not item["exists"] or not item["readable"] or length is None or digest is None or item["readback_status"] != "PARTIAL":
            raise _error("DENIED_RESIDUE", f"{name} partial entry is incomplete")
    return item


def _canonical_residue_array(value: Any, *, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise _error("DENIED_RESIDUE", f"{name} must be a JSON array")
    result: list[dict[str, Any]] = []
    previous: bytes | None = None
    final_identity_by_key: dict[str, str] = {}
    for index, raw in enumerate(value):
        item = _canonical_residue_entry(raw, name=f"{name}[{index}]")
        key = item["relative_path"].encode("utf-8")
        if previous is not None and key <= previous:
            raise _error("DENIED_RESIDUE", f"{name} is unsorted, duplicated or NFC-colliding")
        previous = key
        final_key = item["final_identity"].casefold()
        if final_key in final_identity_by_key and final_identity_by_key[final_key] != item["relative_path"]:
            raise _error("DENIED_RESIDUE", f"{name} has a Windows final-identity collision")
        final_identity_by_key[final_key] = item["relative_path"]
        result.append(item)
    return result


def canonical_residue_entries(value: Any, *, name: str = "residue_entries") -> tuple[dict[str, Any], ...]:
    return tuple(_canonical_residue_array(value, name=name))


def _canonical_residue_pairing(expected_entries: list[dict[str, Any]], actual_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    expected_by_key = {relative_path_key_utf8_hex(item["relative_path"]): item for item in expected_entries}
    actual_by_key = {relative_path_key_utf8_hex(item["relative_path"]): item for item in actual_entries}
    if len(expected_by_key) != len(expected_entries) or len(actual_by_key) != len(actual_entries):
        raise _error("DENIED_RESIDUE", "residue pairing has duplicate relative-path keys")
    final_identity_by_key: dict[str, str] = {}
    for item in [*expected_entries, *actual_entries]:
        final_key = item["final_identity"].casefold()
        previous_path = final_identity_by_key.get(final_key)
        if previous_path is not None and previous_path != item["relative_path"]:
            raise _error("DENIED_RESIDUE", "different relative paths share a final identity")
        final_identity_by_key[final_key] = item["relative_path"]
    records: list[dict[str, Any]] = []
    matrix_hash = compatibility_matrix_hash()
    for key in sorted(set(expected_by_key) | set(actual_by_key), key=lambda value: bytes.fromhex(value)):
        expected = expected_by_key.get(key)
        actual = actual_by_key.get(key)
        path = expected["relative_path"] if expected is not None else actual["relative_path"]
        if expected is None:
            if actual["entry_role"] != "UNEXPECTED" or actual["entry_kind"] in {"PARTIAL_FILE", "MISSING"}:
                raise _error("DENIED_RESIDUE", "actual-only residue role or kind is invalid")
            record = {"pairing_schema_version": "RESIDUE_PAIRING_V2", "kind_compatibility_matrix_version": RESIDUE_KIND_COMPATIBILITY_MATRIX_VERSION, "kind_compatibility_matrix_hash": matrix_hash, "relative_path": path, "relative_path_key_utf8_hex": key, "expected_count": 0, "actual_count": 1, "expected_entry_role": None, "actual_entry_role": "UNEXPECTED", "actual_exists": actual["exists"], "expected_entry_kind": None, "actual_entry_kind": actual["entry_kind"], "pair_status": "UNEXPECTED_ACTUAL"}
        elif actual is None:
            if expected["entry_kind"] in {"PARTIAL_FILE", "MISSING"}:
                raise _error("DENIED_RESIDUE", "partial or missing expected entry cannot be paired")
            validate_role_kind(expected["entry_role"], expected["entry_kind"])
            record = {"pairing_schema_version": "RESIDUE_PAIRING_V2", "kind_compatibility_matrix_version": RESIDUE_KIND_COMPATIBILITY_MATRIX_VERSION, "kind_compatibility_matrix_hash": matrix_hash, "relative_path": path, "relative_path_key_utf8_hex": key, "expected_count": 1, "actual_count": 0, "expected_entry_role": expected["entry_role"], "actual_entry_role": None, "actual_exists": None, "expected_entry_kind": expected["entry_kind"], "actual_entry_kind": None, "pair_status": "MISSING_ACTUAL_RECORD"}
        else:
            if expected["entry_role"] != actual["entry_role"]:
                raise _error("DENIED_RESIDUE", "same-key expected and actual roles differ")
            if expected["entry_kind"] != "MISSING":
                validate_role_kind(expected["entry_role"], expected["entry_kind"])
            if expected["entry_kind"] == "PARTIAL_FILE" or actual["entry_kind"] == "PARTIAL_FILE":
                raise _error("DENIED_RESIDUE", "partial file cannot form a pairing")
            if actual["entry_kind"] == "MISSING" or not actual["exists"]:
                status = "MISSING_EXPECTED"
            else:
                validate_role_kind(expected["entry_role"], actual["entry_kind"])
                if expected["final_identity"].casefold() != actual["final_identity"].casefold():
                    raise _error("DENIED_RESIDUE", "same-key final identity differs")
                status = "MATCHED"
            record = {"pairing_schema_version": "RESIDUE_PAIRING_V2", "kind_compatibility_matrix_version": RESIDUE_KIND_COMPATIBILITY_MATRIX_VERSION, "kind_compatibility_matrix_hash": matrix_hash, "relative_path": path, "relative_path_key_utf8_hex": key, "expected_count": 1, "actual_count": 1, "expected_entry_role": expected["entry_role"], "actual_entry_role": actual["entry_role"], "actual_exists": actual["exists"], "expected_entry_kind": expected["entry_kind"], "actual_entry_kind": actual["entry_kind"], "pair_status": status}
        records.append(_copy_mapping(record, RESIDUE_PAIRING_FIELDS, name="residue pairing"))
    return records


def canonical_residue_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = _copy_mapping(value, RESIDUE_SNAPSHOT_PREIMAGE_FIELDS, name="residue snapshot")
    if snapshot["residue_schema_version"] != "RESIDUE_SNAPSHOT_V2" or snapshot["residue_array_order"] != "NFC_UTF8_RELATIVE_PATH_BYTES":
        raise _error("DENIED_RESIDUE", "residue snapshot schema or ordering is invalid")
    if snapshot["enumeration_complete"] is not True or snapshot["enumeration_failure"] is not None:
        raise _error("DENIED_RESIDUE", "residue snapshot enumeration is incomplete")
    expected = _canonical_residue_array(snapshot["expected_entries"], name="expected_entries")
    actual = _canonical_residue_array(snapshot["entries"], name="entries")
    pairing = _canonical_residue_pairing(expected, actual)
    if tuple(snapshot["residue_pairing"]) != tuple(pairing):
        raise _error("DENIED_RESIDUE", "residue pairing is not owner-recomputed")
    expected_pairing_hash = canonical_sha256({"pairing_schema_version": "RESIDUE_PAIRING_V2", "kind_compatibility_matrix_version": RESIDUE_KIND_COMPATIBILITY_MATRIX_VERSION, "kind_compatibility_matrix_hash": compatibility_matrix_hash(), "residue_pairing": pairing}, fields=RESIDUE_PAIRING_HASH_PREIMAGE_FIELDS)
    if snapshot["residue_pairing_hash"] != expected_pairing_hash:
        raise _error("DENIED_RESIDUE", "residue pairing hash mismatch")
    snapshot["expected_entries"] = expected
    snapshot["entries"] = actual
    snapshot["residue_pairing"] = pairing
    return snapshot


def canonical_writer_invocation(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one owner-bound provenance writer invocation record."""
    _check_fields(value, WRITER_INVOCATION_FIELDS, name="writer invocation")
    item = {field: value[field] for field in WRITER_INVOCATION_FIELDS}
    if item["invocation_schema_version"] != "P1-WRITER-INVOCATION-V1":
        raise _error("DENIED_PROVENANCE", "writer invocation schema version is invalid")
    if not isinstance(item["invocation_sequence"], int) or isinstance(item["invocation_sequence"], bool) or item["invocation_sequence"] < 1:
        raise _error("DENIED_PROVENANCE", "writer invocation sequence is invalid")
    if item["phase"] != "POST_WRITE":
        raise _error("DENIED_PROVENANCE", "writer invocation phase is invalid")
    for field in ("transaction_started", "writer_call_started"):
        if not isinstance(item[field], bool):
            raise _error("DENIED_PROVENANCE", f"writer invocation {field} is invalid")
    if not item["transaction_started"] and not item["writer_call_started"]:
        raise _error("DENIED_PROVENANCE", "writer invocation has no started writer phase")
    if item["terminal_action"] not in {"return", "raise"}:
        raise _error("DENIED_PROVENANCE", "writer invocation terminal action is invalid")
    for field in ("transaction_offset", "writer_offset", "terminal_offset"):
        offset = item[field]
        if offset is not None and (not isinstance(offset, int) or isinstance(offset, bool) or offset < 0):
            raise _error("DENIED_PROVENANCE", f"writer invocation {field} is invalid")
    if item["transaction_started"] != (item["transaction_offset"] is not None):
        raise _error("DENIED_PROVENANCE", "writer invocation transaction offset is inconsistent")
    if item["writer_call_started"] != (item["writer_offset"] is not None):
        raise _error("DENIED_PROVENANCE", "writer invocation writer offset is inconsistent")
    if not isinstance(item["terminal_offset"], int) or isinstance(item["terminal_offset"], bool) or item["terminal_offset"] < 0:
        raise _error("DENIED_PROVENANCE", "writer invocation terminal offset is invalid")
    if item["terminal_outcome"] != f"{item['terminal_action']}@{item['terminal_offset']}":
        raise _error("DENIED_PROVENANCE", "writer invocation terminal outcome is not canonical")
    if normalize_relative_path(item["target_relative_path"], allow_root=False) != item["target_relative_path"]:
        raise _error("DENIED_PROVENANCE", "writer invocation target path is not canonical")
    for field in ("module_path", "source_ref", "target_final_path"):
        if not isinstance(item[field], str) or not item[field]:
            raise _error("DENIED_PROVENANCE", f"writer invocation {field} is missing")
    final_path = item["target_final_path"]
    if not final_path.startswith("D:\\") or ".." in final_path.replace("/", "\\").split("\\"):
        raise _error("DENIED_PROVENANCE", "writer invocation target final path is not owner-bound")
    validate_hash(item["artifact_identity"], field="artifact_identity")
    validate_hash(item["trace_plan_snapshot_hash"], field="trace_plan_snapshot_hash")
    validate_hash(item["trace_hash"], field="trace_hash")
    for field in ("exception_message_sha256", "partial_sha256"):
        if item[field] is not None:
            validate_hash(item[field], field=field)
    for field in ("exception_code", "exception_type"):
        if item[field] is not None and (not isinstance(item[field], str) or not item[field]):
            raise _error("DENIED_PROVENANCE", f"writer invocation {field} is invalid")
    if item["terminal_action"] == "return":
        if any(item[field] is not None for field in ("exception_code", "exception_type", "exception_message_sha256")):
            raise _error("DENIED_PROVENANCE", "returning writer invocation carries exception metadata")
    elif not all(item[field] is not None for field in ("exception_code", "exception_type", "exception_message_sha256")):
        raise _error("DENIED_PROVENANCE", "raising writer invocation lacks exception metadata")
    if item["partial_readback_status"] not in {"NOT_ATTEMPTED", "RECORDED", "PARTIAL_FILE"}:
        raise _error("DENIED_RESIDUE", "writer invocation partial status is invalid")
    if item["partial_readback_status"] == "NOT_ATTEMPTED" and any(item[field] is not None for field in ("partial_length", "partial_sha256")):
        raise _error("DENIED_RESIDUE", "unread writer invocation carries partial metadata")
    if item["partial_readback_status"] in {"RECORDED", "PARTIAL_FILE"}:
        if not isinstance(item["partial_length"], int) or isinstance(item["partial_length"], bool) or item["partial_length"] < 0 or item["partial_sha256"] is None:
            raise _error("DENIED_RESIDUE", "writer invocation readback metadata is incomplete")
    events = item["events"]
    if not isinstance(events, list) or not events:
        raise _error("DENIED_PROVENANCE", "writer invocation events are empty")
    actions: list[str] = []
    for index, event in enumerate(events, 1):
        _check_fields(event, WRITER_TRACE_EVENT_FIELDS, name="writer invocation event")
        if event["sequence"] != index or event["event_kind"] != "opcode" or event["channel"] != "CPYTHON_OPCODE_TRACE_V1":
            raise _error("DENIED_PROVENANCE", "writer invocation event sequence/channel is invalid")
        if event["allowed"] is not True or event["action"] not in WRITER_EVENT_ACTIONS:
            raise _error("DENIED_PROVENANCE", "writer invocation event action/allowance is invalid")
        if not isinstance(event["module_path"], str) or not event["module_path"] or not isinstance(event["source_ref"], str) or not event["source_ref"]:
            raise _error("DENIED_PROVENANCE", "writer invocation event binding is incomplete")
        if not isinstance(event["offset"], int) or isinstance(event["offset"], bool) or event["offset"] < 0:
            raise _error("DENIED_PROVENANCE", "writer invocation event offset is invalid")
        if not isinstance(event["outcome"], str) or not WRITER_EVENT_OUTCOME_GRAMMAR.fullmatch(event["outcome"]):
            raise _error("DENIED_PROVENANCE", "writer invocation event outcome is invalid")
        action, offset_text = event["outcome"].rsplit("@", 1)
        if action != event["action"] or int(offset_text) != event["offset"] or (len(offset_text) > 1 and offset_text.startswith("0")):
            raise _error("DENIED_PROVENANCE", "writer invocation event outcome mismatch")
        actions.append(event["action"])
    if actions[0] != "transaction_started":
        raise _error("DENIED_PROVENANCE", "writer invocation lacks transaction event")
    if any(event["module_path"] != item["module_path"] or event["source_ref"] != item["source_ref"] for event in events):
        raise _error("DENIED_PROVENANCE", "writer invocation source/module binding differs from its events")
    expected_prefix = ["transaction_started"] + (["writer_call_started"] if item["writer_call_started"] else [])
    if actions[:len(expected_prefix)] != expected_prefix:
        raise _error("DENIED_PROVENANCE", "writer invocation start sequence is invalid")
    terminal_index = len(expected_prefix)
    if actions[terminal_index:] not in (["return"], ["raise"], ["raise", "return"]):
        raise _error("DENIED_PROVENANCE", "writer invocation terminal sequence is invalid")
    observed_terminal = "raise" if "raise" in actions[terminal_index:] else "return"
    if observed_terminal != item["terminal_action"]:
        raise _error("DENIED_PROVENANCE", "writer invocation terminal action does not match events")
    if item["transaction_offset"] != events[0]["offset"]:
        raise _error("DENIED_PROVENANCE", "writer invocation transaction offset does not match events")
    if item["writer_call_started"] and item["writer_offset"] != events[1]["offset"]:
        raise _error("DENIED_PROVENANCE", "writer invocation writer offset does not match events")
    terminal_event = next(event for event in reversed(events) if event["action"] == item["terminal_action"])
    if item["terminal_offset"] != terminal_event["offset"]:
        raise _error("DENIED_PROVENANCE", "writer invocation terminal offset does not match events")
    if canonical_sha256({"events": events}, fields=("events",)) != item["trace_hash"]:
        raise _error("DENIED_PROVENANCE", "writer invocation trace hash mismatch")
    return item


def canonical_writer_observation(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return the closed writer observation schema."""
    _check_fields(value, DETERMINISTIC_WRITER_OBSERVATION_FIELDS, name="writer observation")
    item = {field: value[field] for field in DETERMINISTIC_WRITER_OBSERVATION_FIELDS}
    if item["writer_schema_version"] != "P1-WRITER-OBSERVATION-V1" or item["phase"] not in {"PRE_WRITE", "POST_WRITE"} or item["outcome"] not in {"RETURN", "RAISE"}:
        raise _error("DENIED_PROVENANCE", "writer observation phase/outcome is invalid")
    if item["trace_backend_status"] != "VERIFIED":
        raise _error("DENIED_PROVENANCE", "writer observation trace backend is not verified")
    if item["failure_classification"] not in {"NONE", "POST_PERMIT_TRACE_DENY", "POST_WRITE_IO_FAILURE"}:
        raise _error("DENIED_PROVENANCE", "writer observation failure classification is invalid")
    for field in ("transaction_started", "writer_call_started", "writer_returned", "writer_raised", "trace_hook_replaced"):
        if not isinstance(item[field], bool):
            raise _error("DENIED_PROVENANCE", f"writer observation {field} is not boolean")
    for field in ("writer_schema_version", "trace_backend_status", "root_relative_path", "parent_relative_path"):
        if not isinstance(item[field], str) or not item[field]:
            raise _error("DENIED_PROVENANCE", f"writer observation {field} is missing")
    for field in ("root_relative_path", "parent_relative_path"):
        if normalize_relative_path(item[field], allow_root=True) != item[field]:
            raise _error("DENIED_PROVENANCE", f"writer observation {field} is not canonical")
    for field in ("failure_reason", "exception_code", "exception_type", "root_final_path", "parent_final_path"):
        if item[field] is not None and not isinstance(item[field], str):
            raise _error("DENIED_PROVENANCE", f"writer observation {field} is invalid")
    for field in ("trace_plan_snapshot_hash", "trace_hash"):
        validate_hash(item[field], field=field)
    for field in ("exception_message_sha256", "partial_sha256", "residue_snapshot_hash"):
        if item[field] is not None:
            validate_hash(item[field], field=field)
    for field in ("partial_length",):
        if item[field] is not None and (not isinstance(item[field], int) or isinstance(item[field], bool) or item[field] < 0):
            raise _error("DENIED_PROVENANCE", f"writer observation {field} is invalid")
    if item["partial_readback_status"] not in {"NOT_ATTEMPTED", "RECORDED", "PARTIAL_FILE"}:
        raise _error("DENIED_PROVENANCE", "writer observation partial status is invalid")
    for field in ("target_relative_path", "target_relative_paths", "target_final_paths"):
        values = item[field]
        if not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values):
            raise _error("DENIED_PROVENANCE", f"writer observation {field} is not a string array")
        normalized = [unicodedata.normalize("NFC", value) for value in values]
        fixed_output_roles = item["target_relative_paths"] == list(EVALUATION_OUTPUT_ROLE_ORDER)
        is_fixed_role_array = fixed_output_roles and field in {"target_relative_path", "target_relative_paths", "target_final_paths"}
        if normalized != values or len(set(values)) != len(values) or (not is_fixed_role_array and [value.encode("utf-8") for value in values] != sorted(value.encode("utf-8") for value in values)):
            raise _error("DENIED_PROVENANCE", f"writer observation {field} is not canonical and sorted")
    for field in ("root_final_path", "parent_final_path"):
        final_path = item[field]
        if final_path is not None:
            if not isinstance(final_path, str) or not final_path.startswith("D:\\") or ".." in final_path.replace("/", "\\").split("\\"):
                raise _error("DENIED_PROVENANCE", f"writer observation {field} is not an owner D-drive path")
    for final_path in item["target_final_paths"]:
        if not final_path.startswith("D:\\") or ".." in final_path.replace("/", "\\").split("\\"):
            raise _error("DENIED_PROVENANCE", "writer observation target final path is not owner-bound")
    if item["target_relative_path"] != item["target_relative_paths"]:
        raise _error("DENIED_PROVENANCE", "writer observation target path arrays differ")
    started = item["transaction_started"] or item["writer_call_started"]
    if item["phase"] == "PRE_WRITE" and started:
        raise _error("DENIED_PROVENANCE", "pre-write observation cannot report a started writer")
    if item["phase"] == "POST_WRITE" and not started:
        raise _error("DENIED_PROVENANCE", "post-write observation lacks a started writer")
    if item["outcome"] == "RETURN":
        if item["writer_raised"] or not item["writer_returned"]:
            raise _error("DENIED_PROVENANCE", "return observation has inconsistent writer flags")
        if item["exception_code"] is not None or item["exception_type"] is not None or item["exception_message_sha256"] is not None:
            raise _error("DENIED_PROVENANCE", "return observation carries exception fields")
    else:
        if not item["writer_raised"] or item["writer_returned"]:
            raise _error("DENIED_PROVENANCE", "raise observation has inconsistent writer flags")
    if item["failure_classification"] == "POST_WRITE_IO_FAILURE" and not started:
        raise _error("DENIED_PROVENANCE", "post-write failure lacks writer phase evidence")
    if item["failure_classification"] == "POST_WRITE_IO_FAILURE" and (item["phase"] != "POST_WRITE" or item["outcome"] != "RAISE"):
        raise _error("DENIED_PROVENANCE", "post-write failure phase/outcome is inconsistent")
    if item["failure_classification"] == "POST_PERMIT_TRACE_DENY" and started:
        raise _error("DENIED_PROVENANCE", "trace deny cannot follow a started writer")
    if item["trace_hook_replaced"] and item["failure_classification"] != "POST_PERMIT_TRACE_DENY":
        raise _error("DENIED_PROVENANCE", "replaced writer trace hook must be denied")
    phase_matrix = {
        ("PRE_WRITE", "RAISE", "POST_PERMIT_TRACE_DENY"),
        ("POST_WRITE", "RETURN", "NONE"),
        ("POST_WRITE", "RAISE", "POST_WRITE_IO_FAILURE"),
    }
    if (item["phase"], item["outcome"], item["failure_classification"]) not in phase_matrix:
        raise _error("DENIED_PROVENANCE", "writer observation phase/outcome/classification combination is invalid")
    if item["partial_readback_status"] == "PARTIAL_FILE":
        if not started or item["partial_length"] is None or item["partial_sha256"] is None:
            raise _error("DENIED_RESIDUE", "partial observation lacks phase or readback metadata")
        if item["residue_snapshot_hash"] is not None:
            raise _error("DENIED_RESIDUE", "partial observation cannot carry a residue snapshot hash")
    elif item["partial_length"] is not None or item["partial_sha256"] is not None:
        raise _error("DENIED_RESIDUE", "non-partial observation carries partial metadata")
    invocations = item["writer_invocations"]
    if not isinstance(invocations, list) or not invocations:
        raise _error("DENIED_PROVENANCE", "writer invocation records are missing")
    canonical_invocations = [canonical_writer_invocation(record) for record in invocations]
    if [record["invocation_sequence"] for record in canonical_invocations] != list(range(1, len(canonical_invocations) + 1)):
        raise _error("DENIED_PROVENANCE", "writer invocation sequence is not continuous")
    if item["transaction_started"] != any(record["transaction_started"] for record in canonical_invocations) or item["writer_call_started"] != any(record["writer_call_started"] for record in canonical_invocations):
        raise _error("DENIED_PROVENANCE", "writer observation start flags do not match invocations")
    if item["writer_raised"] != any(record["terminal_action"] == "raise" for record in canonical_invocations):
        raise _error("DENIED_PROVENANCE", "writer observation raise flag does not match invocations")
    events = item["events"]
    if not isinstance(events, list):
        raise _error("DENIED_PROVENANCE", "writer observation events are not an array")
    if not events:
        raise _error("DENIED_PROVENANCE", "writer observation events are empty")
    actions: list[str] = []
    for index, event in enumerate(events, 1):
        _check_fields(event, WRITER_TRACE_EVENT_FIELDS, name="writer observation event")
        if event["sequence"] != index or event["event_kind"] != "opcode" or event["channel"] != "CPYTHON_OPCODE_TRACE_V1":
            raise _error("DENIED_PROVENANCE", "writer observation event sequence/channel is invalid")
        if event["action"] not in WRITER_EVENT_ACTIONS or event["allowed"] is not True:
            raise _error("DENIED_PROVENANCE", "writer observation event action/allowance is invalid")
        if not isinstance(event["module_path"], str) or not event["module_path"]:
            raise _error("DENIED_PROVENANCE", "writer observation event module binding is missing")
        if not isinstance(event["source_ref"], str) or not event["source_ref"]:
            raise _error("DENIED_PROVENANCE", "writer observation event source binding is missing")
        if not isinstance(event["offset"], int) or isinstance(event["offset"], bool) or event["offset"] < 0:
            raise _error("DENIED_PROVENANCE", "writer observation event offset is invalid")
        if not isinstance(event["outcome"], str) or not WRITER_EVENT_OUTCOME_GRAMMAR.fullmatch(event["outcome"]):
            raise _error("DENIED_PROVENANCE", "writer observation event outcome is not canonical")
        outcome_action, offset_text = event["outcome"].rsplit("@", 1)
        if outcome_action != event["action"] or int(offset_text) != event["offset"] or (len(offset_text) > 1 and offset_text.startswith("0")):
            raise _error("DENIED_PROVENANCE", "writer observation event outcome/action mismatch")
        actions.append(event["action"])
    if not actions or actions[0] != "transaction_started":
        raise _error("DENIED_PROVENANCE", "writer observation lacks the owner transaction event")
    expected_events: list[dict[str, Any]] = []
    for record in canonical_invocations:
        for event in record["events"]:
            expected_events.append({**event, "sequence": len(expected_events) + 1})
    if events != expected_events:
        raise _error("DENIED_PROVENANCE", "writer observation events do not match per-call records")
    if item["writer_returned"] != (item["outcome"] == "RETURN"):
        raise _error("DENIED_PROVENANCE", "writer observation return flag is inconsistent")
    if item["outcome"] == "RETURN" and any(record["terminal_action"] != "return" for record in canonical_invocations):
        raise _error("DENIED_PROVENANCE", "successful writer observation contains a failed invocation")
    if item["outcome"] == "RAISE" and not any(record["terminal_action"] == "raise" for record in canonical_invocations):
        raise _error("DENIED_PROVENANCE", "failed writer observation lacks a failed invocation")
    if canonical_sha256({"events": events}, fields=("events",)) != item["trace_hash"]:
        raise _error("DENIED_PROVENANCE", "writer observation trace hash mismatch")
    return item


def canonical_writer_failure_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate failure evidence and recompute its non-self-referential hash."""
    _check_fields(value, WRITER_FAILURE_EVIDENCE_FIELDS, name="writer failure evidence")
    item = {field: value[field] for field in WRITER_FAILURE_EVIDENCE_FIELDS}
    if item["failure_schema_version"] != "P1-WRITER-FAILURE-EVIDENCE-V1" or item["classification"] != "POST_WRITE_IO_FAILURE":
        raise _error("DENIED_PROVENANCE", "writer failure evidence classification is invalid")
    if not isinstance(item["exception_code"], str) or not item["exception_code"] or not isinstance(item["exception_type"], str) or not item["exception_type"]:
        raise _error("DENIED_PROVENANCE", "writer failure exception identity is incomplete")
    validate_hash(item["exception_message_sha256"], field="exception_message_sha256")
    if item["root_status"] not in {"ABSENT", "VERIFIED", "UNREADABLE"}:
        raise _error("DENIED_PROVENANCE", "writer failure root status is missing")
    if item["residue_enumeration_error"] not in {None, "PARTIAL_RESIDUE", "ENUMERATION_FAILED"}:
        raise _error("DENIED_PROVENANCE", "writer failure enumeration error is invalid")
    if not isinstance(item["partial_file_detected"], bool) or item["zero_residue_claim"] is not False:
        raise _error("DENIED_PROVENANCE", "writer failure residue flags are invalid")
    observation = canonical_writer_observation(item["writer_phase_observation"])
    if observation["failure_classification"] != "POST_WRITE_IO_FAILURE" or observation["phase"] != "POST_WRITE" or observation["outcome"] != "RAISE":
        raise _error("DENIED_PROVENANCE", "writer failure observation classification is inconsistent")
    residue_entries = item["residue_entries"]
    _check_fields(residue_entries, ("expected_entries", "entries"), name="writer failure residue entries")
    expected_entries = _canonical_residue_array(residue_entries["expected_entries"], name="writer failure expected_entries")
    actual_entries = _canonical_residue_array(residue_entries["entries"], name="writer failure entries")
    snapshot = item["residue_snapshot"]
    if item["residue_enumeration_error"] == "ENUMERATION_FAILED":
        if item["root_status"] != "UNREADABLE" or item["partial_file_detected"]:
            raise _error("DENIED_RESIDUE", "enumeration failure has inconsistent root or partial status")
    elif item["residue_enumeration_error"] == "PARTIAL_RESIDUE":
        if item["root_status"] != "VERIFIED" or not item["partial_file_detected"]:
            raise _error("DENIED_RESIDUE", "partial residue has inconsistent root or partial status")
    elif item["root_status"] == "UNREADABLE":
        raise _error("DENIED_RESIDUE", "unreadable root requires an enumeration failure")
    if snapshot is None:
        if item["residue_snapshot_hash"] is not None:
            raise _error("DENIED_RESIDUE", "missing residue snapshot cannot carry a hash")
        if not item["partial_file_detected"] and item["residue_enumeration_error"] is None:
            raise _error("DENIED_RESIDUE", "complete failure evidence must carry a residue snapshot")
    else:
        snapshot = canonical_residue_snapshot(snapshot)
        if snapshot["expected_entries"] != expected_entries or snapshot["entries"] != actual_entries:
            raise _error("DENIED_RESIDUE", "writer failure residue arrays differ from snapshot")
        expected_hash = canonical_sha256(snapshot, fields=RESIDUE_SNAPSHOT_PREIMAGE_FIELDS)
        if item["residue_snapshot_hash"] != expected_hash:
            raise _error("DENIED_RESIDUE", "writer failure residue snapshot hash mismatch")
    if item["partial_file_detected"] or item["residue_enumeration_error"] is not None:
        if snapshot is not None or item["residue_snapshot_hash"] is not None:
            raise _error("DENIED_RESIDUE", "incomplete or partial residue cannot carry a snapshot hash")
        if item["partial_file_detected"] and item["writer_phase_observation"]["partial_readback_status"] != "PARTIAL_FILE":
            raise _error("DENIED_RESIDUE", "partial failure evidence lacks partial writer observation")
    validate_hash(item["failure_evidence_hash"], field="failure_evidence_hash")
    preimage = {field: item[field] for field in WRITER_FAILURE_EVIDENCE_PREIMAGE_FIELDS}
    if canonical_sha256(preimage, fields=WRITER_FAILURE_EVIDENCE_PREIMAGE_FIELDS) != item["failure_evidence_hash"]:
        raise _error("DENIED_PROVENANCE", "writer failure evidence hash mismatch")
    item["residue_entries"] = {"expected_entries": expected_entries, "entries": actual_entries}
    item["residue_snapshot"] = snapshot
    item["writer_phase_observation"] = observation
    return item


def validate_decimal_string(value: Any) -> str:
    if not isinstance(value, str) or not DECIMAL_GRAMMAR_022.fullmatch(value):
        raise _error("DENIED_INPUT", "non-canonical decimal metric value")
    return value


def validate_hash(value: Any, *, field: str = "hash") -> str:
    if not isinstance(value, str) or not HEX64_GRAMMAR.fullmatch(value):
        raise _error("DENIED_PROVENANCE", f"{field} is not lowercase SHA-256")
    return value


def strict_sorted_unique(values: Iterable[str], *, field: str, key: str = "nfc_utf8") -> tuple[str, ...]:
    values_tuple = tuple(values)
    normalized: list[str] = []
    for value in values_tuple:
        normalized.append(_nfc(value, field=field))
    if len(set(normalized)) != len(normalized):
        raise _error("DENIED_INPUT", f"duplicate {field}")
    if key == "nfc_utf8":
        order = [item.encode("utf-8") for item in normalized]
    else:
        order = normalized
    if order != sorted(order):
        raise _error("DENIED_INPUT", f"unsorted {field}; silent sorting is forbidden")
    return values_tuple


def strict_base64_bytes(value: Any, *, field: str) -> bytes:
    if not isinstance(value, str) or not BASE64_GRAMMAR.fullmatch(value) or not value:
        raise _error("DENIED_PROVENANCE", f"{field} is not padded base64")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise _error("DENIED_PROVENANCE", f"{field} cannot be decoded") from exc
    if base64.b64encode(decoded).decode("ascii") != value:
        raise _error("DENIED_PROVENANCE", f"{field} is not canonical base64")
    return decoded


def _copy_mapping(value: Mapping[str, Any], fields: Sequence[str], *, name: str) -> dict[str, Any]:
    _check_fields(value, fields, name=name)
    return {key: value[key] for key in fields}


def _validate_registry_header(value: Mapping[str, Any], fields: Sequence[str], *, name: str) -> None:
    _check_fields(value, fields, name=name)
    if not value["read_only"] is True:
        raise _error("DENIED_PROVENANCE", f"{name} must be read-only")
    for field in fields:
        if field in {"entries", "read_only"}:
            continue
        if not isinstance(value[field], str) or not value[field]:
            raise _error("DENIED_PROVENANCE", f"{name}.{field} is missing")


def _validate_entry_fields(entry: Mapping[str, Any], fields: Sequence[str], *, name: str) -> dict[str, Any]:
    copied = _copy_mapping(entry, fields, name=name)
    for key, value in copied.items():
        if isinstance(value, str):
            _nfc(value, field=f"{name}.{key}")
    return copied


@dataclass(frozen=True)
class RegistryBaseV1:
    value: Mapping[str, Any]
    fields: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_registry_header(self.value, self.fields, name=self.__class__.__name__)

    @property
    def snapshot_hash(self) -> str:
        return canonical_sha256(self.value, fields=self.fields)

    def to_mapping(self) -> dict[str, Any]:
        return {key: self.value[key] for key in self.fields}


@dataclass(frozen=True)
class RuleSetRegistryV1(RegistryBaseV1):
    fields: tuple[str, ...] = RULE_SET_REGISTRY_FIELDS

    def __post_init__(self) -> None:
        super().__post_init__()
        entries = self.value["entries"]
        if not isinstance(entries, (list, tuple)):
            raise _error("DENIED_PROVENANCE", "rule registry entries must be an array")
        previous: tuple[str, str] | None = None
        for entry in entries:
            item = _validate_entry_fields(entry, RULE_SET_ENTRY_FIELDS, name="rule entry")
            key = (_nfc(item["rule_set_id"], field="rule_set_id"), _nfc(item["rule_set_version"], field="rule_set_version"))
            if previous is not None and key <= previous:
                raise _error("DENIED_PROVENANCE", "rule entries are unsorted or duplicated")
            previous = key
            raw = strict_base64_bytes(item["rule_set_bytes_b64"], field="rule_set_bytes_b64")
            if sha256_bytes(raw) != item["rule_set_bytes_sha256"]:
                raise _error("DENIED_PROVENANCE", "rule bytes hash mismatch")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RuleSetRegistryV1":
        return cls(value={key: value[key] for key in RULE_SET_REGISTRY_FIELDS}, fields=RULE_SET_REGISTRY_FIELDS)

    def select(self, rule_set_id: str, rule_set_version: str) -> dict[str, Any]:
        matches = [entry for entry in self.value["entries"] if entry["rule_set_id"] == rule_set_id and entry["rule_set_version"] == rule_set_version]
        if len(matches) != 1 or str(matches[0]["entry_status"]).upper() != "ACTIVE":
            raise _error("DENIED_PROVENANCE", "rule selector is not unique and active")
        return dict(matches[0])

    @staticmethod
    def bytes_for(entry: Mapping[str, Any]) -> bytes:
        return strict_base64_bytes(entry["rule_set_bytes_b64"], field="rule_set_bytes_b64")


@dataclass(frozen=True)
class ContractRegistryV1(RegistryBaseV1):
    fields: tuple[str, ...] = CONTRACT_REGISTRY_FIELDS

    def __post_init__(self) -> None:
        super().__post_init__()
        previous: tuple[str, str] | None = None
        for entry in self.value["entries"]:
            item = _validate_entry_fields(entry, CONTRACT_ENTRY_FIELDS, name="contract entry")
            key = (_nfc(item["contract_id"], field="contract_id"), _nfc(item["contract_version"], field="contract_version"))
            if previous is not None and key <= previous:
                raise _error("DENIED_PROVENANCE", "contract entries are unsorted or duplicated")
            previous = key
            raw = strict_base64_bytes(item["contract_bytes_b64"], field="contract_bytes_b64")
            if sha256_bytes(raw) != item["contract_bytes_sha256"]:
                raise _error("DENIED_PROVENANCE", "contract bytes hash mismatch")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ContractRegistryV1":
        return cls(value={key: value[key] for key in CONTRACT_REGISTRY_FIELDS}, fields=CONTRACT_REGISTRY_FIELDS)

    def select(self, contract_id: str, contract_version: str) -> dict[str, Any]:
        matches = [entry for entry in self.value["entries"] if entry["contract_id"] == contract_id and entry["contract_version"] == contract_version]
        if len(matches) != 1 or str(matches[0]["entry_status"]).upper() != "ACTIVE":
            raise _error("DENIED_PROVENANCE", "contract selector is not unique and active")
        return dict(matches[0])

    @staticmethod
    def bytes_for(entry: Mapping[str, Any]) -> bytes:
        return strict_base64_bytes(entry["contract_bytes_b64"], field="contract_bytes_b64")


@dataclass(frozen=True)
class EvaluatorSourceRegistryV1(RegistryBaseV1):
    fields: tuple[str, ...] = EVALUATOR_SOURCE_REGISTRY_FIELDS

    def __post_init__(self) -> None:
        super().__post_init__()
        previous: bytes | None = None
        seen_casefold: set[str] = set()
        for entry in self.value["entries"]:
            item = _validate_entry_fields(entry, EVALUATOR_SOURCE_ENTRY_FIELDS, name="source entry")
            path = normalize_relative_path(item["relative_path"], allow_root=False)
            key = path.encode("utf-8")
            if previous is not None and key <= previous:
                raise _error("DENIED_PROVENANCE", "source entries are unsorted or duplicated")
            previous = key
            folded = path.casefold()
            if folded in seen_casefold:
                raise _error("DENIED_PROVENANCE", "Windows case-insensitive source collision")
            seen_casefold.add(folded)
            if item["source_role"] not in EVALUATOR_SOURCE_ROLES:
                raise _error("DENIED_PROVENANCE", "source role is not closed")
            if not isinstance(item["length"], int) or item["length"] < 0:
                raise _error("DENIED_PROVENANCE", "source length is invalid")
            validate_hash(item["sha256"], field="source sha256")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "EvaluatorSourceRegistryV1":
        return cls(value={key: value[key] for key in EVALUATOR_SOURCE_REGISTRY_FIELDS}, fields=EVALUATOR_SOURCE_REGISTRY_FIELDS)

    @property
    def evaluator_source_hash(self) -> str:
        return canonical_sha256({"entries": [dict(entry) for entry in self.value["entries"]]}, fields=EVALUATOR_SOURCE_ENTRIES_PREIMAGE_FIELDS)

    def entry_for(self, relative_path: str) -> dict[str, Any]:
        canonical = normalize_relative_path(relative_path, allow_root=False)
        matches = [entry for entry in self.value["entries"] if entry["relative_path"] == canonical]
        if len(matches) != 1:
            raise _error("DENIED_PROVENANCE", "source entry is not uniquely admitted")
        return dict(matches[0])

    def verify_bytes(self, entry: Mapping[str, Any], content: bytes) -> None:
        if len(content) != entry["length"] or sha256_bytes(content) != entry["sha256"]:
            raise _error("DENIED_PROVENANCE", "source bytes do not match registry")


@dataclass(frozen=True)
class P1CapabilityCensusV1(RegistryBaseV1):
    fields: tuple[str, ...] = CAPABILITY_CENSUS_REGISTRY_FIELDS

    def __post_init__(self) -> None:
        super().__post_init__()
        previous: bytes | None = None
        seen: set[str] = set()
        for entry in self.value["entries"]:
            item = _validate_entry_fields(entry, CAPABILITY_CENSUS_ENTRY_FIELDS, name="census entry")
            module_path = _nfc(item["module_path"], field="module_path")
            if previous is not None and module_path.encode("utf-8") <= previous:
                raise _error("DENIED_CAPABILITY", "census entries are unsorted or duplicated")
            previous = module_path.encode("utf-8")
            if module_path in seen:
                raise _error("DENIED_CAPABILITY", "duplicate census module")
            seen.add(module_path)
            for field in CAPABILITY_CENSUS_ENTRY_FIELDS:
                if field in {"module_path", "source_relative_path", "source_ref", "source_length", "source_sha256"}:
                    continue
                value = item[field]
                if isinstance(value, list):
                    strict_sorted_unique(value, field=f"{module_path}.{field}", key="nfc_utf8")
                elif isinstance(value, bool):
                    continue
            if not isinstance(item["source_length"], int) or item["source_length"] < 0:
                raise _error("DENIED_CAPABILITY", "census source length is invalid")
            validate_hash(item["source_sha256"], field="census source sha256")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "P1CapabilityCensusV1":
        return cls(value={key: value[key] for key in CAPABILITY_CENSUS_REGISTRY_FIELDS}, fields=CAPABILITY_CENSUS_REGISTRY_FIELDS)

    def validate_closed(self, source_registry: EvaluatorSourceRegistryV1) -> None:
        source_by_path = {entry["relative_path"]: entry for entry in source_registry.value["entries"]}
        modules = {entry["module_path"] for entry in self.value["entries"]}
        census_source_paths: list[str] = []
        for entry in self.value["entries"]:
            source = source_by_path.get(entry["source_relative_path"])
            if source is None or source["source_ref"] != entry["source_ref"] or source["length"] != entry["source_length"] or source["sha256"] != entry["source_sha256"]:
                raise _error("DENIED_CAPABILITY", "census/source entry binding mismatch")
            if source["source_role"] not in {"candidate", "static"}:
                raise _error("DENIED_CAPABILITY", "census entry is not bound to a candidate/static source role")
            census_source_paths.append(entry["source_relative_path"])
            if entry["dynamic_imports"] or entry["unknown_dynamic_imports"] or entry["unresolved_dependencies"] or entry["unresolved_writers"] or entry["writer_paths"]:
                raise _error("DENIED_CAPABILITY", "census contains an unresolved or dynamic capability")
            for field in CAPABILITY_CENSUS_ENTRY_FIELDS:
                if field.endswith("_call") or field.endswith("_side_effect") or field in {"module_main", "in_process_call", "process_spawn", "logger_call", "checkpoint_call", "state_call", "cache_call", "network_call", "api_call", "service_call", "model_call", "config_discovery", "project_discovery", "top_level_config_discovery", "top_level_project_discovery"}:
                    if entry[field] is not False:
                        raise _error("DENIED_CAPABILITY", f"census capability {field} is not false")
            transitive = set(entry["transitive_modules"])
            if entry["module_path"] not in transitive or not transitive.issubset(modules):
                raise _error("DENIED_CAPABILITY", "census transitive closure is incomplete")
            if not set(entry["static_imports"]).issubset(transitive):
                raise _error("DENIED_CAPABILITY", "static import escapes census closure")
        candidate_source_paths = [entry["relative_path"] for entry in source_registry.value["entries"] if entry["source_role"] in {"candidate", "static"}]
        if sorted(candidate_source_paths) != sorted(census_source_paths) or len(set(census_source_paths)) != len(census_source_paths):
            raise _error("DENIED_CAPABILITY", "candidate/static source roles and census entries are not one-to-one")


@dataclass(frozen=True)
class P1PreImportGateV1:
    value: Mapping[str, Any]

    def __post_init__(self) -> None:
        _check_fields(self.value, PREIMPORT_GATE_FIELDS, name="preimport gate")
        if self.value["dynamic_import_allowlist"] != []:
            raise _error("DENIED_CAPABILITY", "dynamic import allowlist must be empty")
        validate_hash(self.value["owner_probe_binding_hash"], field="owner_probe_binding_hash")
        for field in ("read_only", "no_root_creation", "no_config_discovery", "no_project_discovery"):
            if self.value[field] is not True:
                raise _error("DENIED_CAPABILITY", f"gate flag {field} must be true")
        strict_sorted_unique(self.value["candidate_modules"], field="candidate_modules")
        strict_sorted_unique(self.value["static_module_allowlist"], field="static_module_allowlist")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "P1PreImportGateV1":
        return cls({key: value[key] for key in PREIMPORT_GATE_FIELDS})

    @property
    def snapshot_hash(self) -> str:
        return canonical_sha256(self.value, fields=PREIMPORT_GATE_FIELDS)


@dataclass(frozen=True)
class EvaluationInputManifestV1:
    value: Mapping[str, Any]

    def __post_init__(self) -> None:
        _check_fields(self.value, EVALUATION_INPUT_MANIFEST_FIELDS, name="evaluation input manifest")
        if self.value["manifest_schema_version"] != "v1":
            raise _error("DENIED_INPUT", "manifest schema version is not v1")
        for field in ("profile_definition_hash", "namespace_digest", "project_registry_snapshot_hash", "artifact_resolver_snapshot_hash", "parent_store_snapshot_hash", "capability_census_snapshot_hash", "preimport_gate_snapshot_hash", "resolution_guard_snapshot_hash", "writer_trace_plan_snapshot_hash", "rule_set_registry_snapshot_hash", "rule_set_bytes_sha256", "evaluator_source_registry_snapshot_hash", "evaluator_source_hash", "contract_registry_snapshot_hash", "evaluation_contract_hash"):
            validate_hash(self.value[field], field=field)
        metrics = self.value["declared_metrics"]
        if not isinstance(metrics, list) or not metrics:
            raise _error("DENIED_INPUT", "declared_metrics must be a non-empty array")
        strict_sorted_unique(metrics, field="declared_metrics")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "EvaluationInputManifestV1":
        return cls({key: value[key] for key in EVALUATION_INPUT_MANIFEST_FIELDS})

    @classmethod
    def from_bytes(cls, raw: bytes) -> "EvaluationInputManifestV1":
        return cls(parse_canonical_evaluation_json(raw, fields=EVALUATION_INPUT_MANIFEST_FIELDS))

    def to_mapping(self) -> dict[str, Any]:
        return {key: self.value[key] for key in EVALUATION_INPUT_MANIFEST_FIELDS}

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_evaluation_json_bytes(self.to_mapping(), fields=EVALUATION_INPUT_MANIFEST_FIELDS)

    @property
    def manifest_hash(self) -> str:
        return sha256_bytes(self.canonical_bytes)

    def __getattr__(self, name: str) -> Any:
        if name in EVALUATION_INPUT_MANIFEST_FIELDS:
            return self.value[name]
        raise AttributeError(name)


@dataclass(frozen=True)
class EvaluationBindingV1:
    value: Mapping[str, Any]

    def __post_init__(self) -> None:
        _check_fields(self.value, EVALUATION_BATCH_BINDING_FIELDS, name="evaluation binding")
        for field in EVALUATION_BATCH_BINDING_FIELDS:
            if field.endswith("_hash") or field.endswith("_sha256"):
                validate_hash(self.value[field], field=field)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "EvaluationBindingV1":
        return cls({key: value[key] for key in EVALUATION_BATCH_BINDING_FIELDS})

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_evaluation_json_bytes(dict(self.value), fields=EVALUATION_BATCH_BINDING_FIELDS)

    @property
    def evaluation_binding_hash(self) -> str:
        return sha256_bytes(self.canonical_bytes)


class ImportPermitV1:
    """Opaque permit.  Object and private-handle identity are intentionally runtime-only."""

    __slots__ = (
        "_sentinel", "_private_handle", "owner_session_id", "preimage", "permit_digest",
        "permit_seal", "consumed", "issued_at_utc",
    )

    def __init__(self, *, sentinel: object, private_handle: object, owner_session_id: str, preimage: Mapping[str, Any], permit_digest: str, permit_seal: str, issued_at_utc: str):
        self._sentinel = sentinel
        self._private_handle = private_handle
        self.owner_session_id = owner_session_id
        self.preimage = dict(preimage)
        self.permit_digest = permit_digest
        self.permit_seal = permit_seal
        self.consumed = False
        self.issued_at_utc = issued_at_utc

    def public_mapping(self) -> dict[str, Any]:
        return {**self.preimage, "permit_digest": self.permit_digest, "permit_seal": self.permit_seal, "consumed": self.consumed}

    def __repr__(self) -> str:
        return "<ImportPermitV1 opaque>"


def issue_import_permit(*, owner_session_id: str, sentinel: object, private_handle: object, preimage: Mapping[str, Any], seal_key: bytes, issued_at_utc: str) -> ImportPermitV1:
    _check_fields(preimage, IMPORT_PERMIT_PREIMAGE_FIELDS, name="import permit preimage")
    payload = canonical_evaluation_json_bytes(dict(preimage), fields=IMPORT_PERMIT_PREIMAGE_FIELDS)
    digest = sha256_bytes(payload)
    seal_input = b"P1-IMPORT-PERMIT-V1\x00" + digest.encode("ascii") + b"\x00" + payload
    seal = hmac.new(seal_key, seal_input, hashlib.sha256).hexdigest()
    return ImportPermitV1(
        sentinel=sentinel, private_handle=private_handle, owner_session_id=owner_session_id,
        preimage=preimage, permit_digest=digest, permit_seal=seal, issued_at_utc=issued_at_utc,
    )


def recompute_permit_digest(permit: ImportPermitV1) -> str:
    if not isinstance(permit, ImportPermitV1):
        raise _error("DENIED_CAPABILITY", "permit is not an opaque owner permit")
    return sha256_bytes(canonical_evaluation_json_bytes(permit.preimage, fields=IMPORT_PERMIT_PREIMAGE_FIELDS))


def recompute_permit_seal(permit: ImportPermitV1, seal_key: bytes) -> str:
    payload = canonical_evaluation_json_bytes(permit.preimage, fields=IMPORT_PERMIT_PREIMAGE_FIELDS)
    digest = recompute_permit_digest(permit)
    return hmac.new(seal_key, b"P1-IMPORT-PERMIT-V1\x00" + digest.encode("ascii") + b"\x00" + payload, hashlib.sha256).hexdigest()


def canonical_lineage_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return _copy_mapping(value, ARTIFACT_REF_IDENTITY_FIELDS, name="artifact lineage")


def lineage_bytes(value: Mapping[str, Any]) -> bytes:
    return canonical_evaluation_json_bytes(canonical_lineage_mapping(value), fields=ARTIFACT_REF_IDENTITY_FIELDS)


def lineage_hash(value: Mapping[str, Any]) -> str:
    return sha256_bytes(lineage_bytes(value))


def compatibility_matrix_mapping() -> dict[str, Any]:
    return {
        "matrix_schema_version": "RESIDUE_KIND_MATRIX_PREIMAGE_V1",
        "matrix_version": RESIDUE_KIND_COMPATIBILITY_MATRIX_VERSION,
        "rows": [
            {"expected_entry_role": role, "allowed_actual_kinds": list(kinds)}
            for role, kinds in RESIDUE_KIND_COMPATIBILITY_MATRIX
        ],
    }


def compatibility_matrix_bytes(value: Mapping[str, Any] | None = None) -> bytes:
    matrix = compatibility_matrix_mapping() if value is None else value
    _check_fields(matrix, RESIDUE_KIND_COMPATIBILITY_MATRIX_PREIMAGE_FIELDS, name="compatibility matrix")
    rows = matrix["rows"]
    if not isinstance(rows, list) or len(rows) != len(RESIDUE_KIND_COMPATIBILITY_MATRIX):
        raise _error("DENIED_PROVENANCE", "compatibility matrix rows are incomplete")
    expected = compatibility_matrix_mapping()
    if matrix != expected:
        raise _error("DENIED_PROVENANCE", "compatibility matrix is not the exact owner matrix")
    for row in rows:
        _check_fields(row, RESIDUE_KIND_COMPATIBILITY_MATRIX_ROW_FIELDS, name="compatibility matrix row")
    return canonical_evaluation_json_bytes(matrix, fields=RESIDUE_KIND_COMPATIBILITY_MATRIX_PREIMAGE_FIELDS)


def compatibility_matrix_hash(value: Mapping[str, Any] | None = None) -> str:
    return sha256_bytes(compatibility_matrix_bytes(value))


def validate_role_kind(role: str, kind: str) -> None:
    allowed = dict(RESIDUE_KIND_COMPATIBILITY_MATRIX).get(role)
    if allowed is None or kind not in allowed:
        raise _error("DENIED_INPUT", "role/kind pair is not in the closed compatibility matrix")


def canonical_pairing_hash(pairing: Sequence[Mapping[str, Any]], *, matrix_version: str = RESIDUE_KIND_COMPATIBILITY_MATRIX_VERSION, matrix_hash: str | None = None, pairing_schema_version: str = "RESIDUE_PAIRING_V2") -> str:
    matrix_hash = compatibility_matrix_hash() if matrix_hash is None else matrix_hash
    validate_hash(matrix_hash, field="kind_compatibility_matrix_hash")
    records = []
    for record in pairing:
        _check_fields(record, RESIDUE_PAIRING_FIELDS, name="residue pairing record")
        records.append(dict(record))
    preimage = {
        "pairing_schema_version": pairing_schema_version,
        "kind_compatibility_matrix_version": matrix_version,
        "kind_compatibility_matrix_hash": matrix_hash,
        "residue_pairing": records,
    }
    return canonical_sha256(preimage, fields=RESIDUE_PAIRING_HASH_PREIMAGE_FIELDS)


# P1-A / 034 additions.  These names are deliberately separate from the
# historical V1 helpers above: callers cannot accidentally reinterpret a P0
# field by relying on a renamed or merged P1 field.
P0_ARTIFACTREF_PREIMAGE_FIELDS = (
    "project_id", "profile_id", "profile_version", "profile_definition_hash",
    "project_revision", "namespace_digest", "root_alias", "relative_path",
    "source_ref", "producer_version", "batch_id", "parent_refs", "length", "sha256",
)
P0_ARTIFACT_LINEAGE_FIELDS = (
    "project_id", "profile_id", "profile_version", "profile_definition_hash",
    "project_revision", "namespace_digest", "root_alias", "relative_path",
    "source_ref", "producer_version", "batch_id", "parent_refs", "content_length",
    "content_sha256", "integrity_digest",
)
P0_TO_P1_INPUT_LINEAGE_ADAPTER_FIELDS = ("p0_artifact_lineage", "p0_artifact_ref_preimage")

CPYTHON_RUNTIME_ID_FIELDS = (
    "runtime_schema_version", "implementation_name", "implementation_version",
    "python_version", "cache_tag", "opcode_format", "wordcode_unit_size",
    "supports_opcode_trace", "has_argument", "opcode_table", "opname_table",
)
MARKER_OPCODE_RECORD_FIELDS = ("opcode", "opname_utf8_hex", "has_argument")
MARKER_OPCODE_EVENT_FIELDS = (
    "sequence", "code_object_role", "code_object_sha256", "instruction_offset",
    "opcode", "opname_utf8_hex", "has_argument", "argument_kind", "argument_value",
)
MARKER_OPCODE_WHITELIST_FIELDS = ("opcode", "opname_utf8_hex", "has_argument")
MARKER_OPCODE_SEQUENCE_FIELDS = (
    "sequence_schema_version", "cpython_runtime_snapshot_hash", "marker_code_sha256",
    "events", "complete", "status",
)
MARKER_PURITY_FIELDS = (
    "marker_schema_version", "marker_module_path", "marker_qualname",
    "marker_source_relative_path", "marker_source_ref", "marker_source_length",
    "marker_source_sha256", "marker_code_sha256", "marker_code_firstlineno",
    "probe_module_path", "probe_qualname", "probe_source_relative_path",
    "probe_source_ref", "probe_source_length", "probe_source_sha256", "probe_code_sha256",
    "probe_code_firstlineno", "marker_opcode_whitelist", "marker_opcode_sequence_hash",
    "marker_call_count", "marker_purity_status",
)
MARKER_ARGUMENT_KINDS = ("NONE", "INT", "CONST_INDEX", "NAME_INDEX", "JUMP_TARGET_OFFSET")
IMPORT_PERMIT_PREIMAGE_FIELDS_V2 = (
    "permit_schema_version", "owner_id", "authority_ref", "gate_id",
    "preimport_gate_snapshot_hash", "capability_census_snapshot_hash",
    "evaluator_source_registry_snapshot_hash", "resolution_guard_snapshot_hash",
    "runtime_snapshot_hash", "marker_purity_hash", "marker_opcode_sequence_hash",
    "trace_plan_snapshot_hash", "candidate_modules", "static_module_allowlist",
    "dynamic_import_allowlist", "read_only", "no_root_creation", "no_config_discovery",
    "no_project_discovery", "single_use", "permit_status",
    "cpython_runtime_snapshot_hash", "pre_permit_attestation_v15_hash",
    "marker_purity_snapshot_hash", "capability_probe_snapshot_hash",
    "resolution_live_snapshot_hash", "input_binding_hash", "input_manifest_hash",
    "owner_probe_binding_hash",
    "source_registry_snapshot_hash", "candidate_module_set", "owner_session_id",
    "trace_thread_binding", "hook_install_status", "opcode_trace_support",
    "event_delivery_status", "trace_replacement_guard_status", "attestation_status",
)
WRITER_TRACE_PLAN_FIELDS = (
    "plan_schema_version", "plan_id", "owner_id", "authority_ref", "provenance_source_ref",
    "provenance_source_sha256", "safe_write_qualname", "safe_write_code_filename",
    "safe_write_first_line", "safe_write_code_object_sha256", "trace_backend", "trace_thread_id",
    "transaction_call_line", "transaction_call_offset", "writer_call_line", "writer_call_offset",
    "probe_call_offset",
    "runtime_snapshot_hash", "runtime_id_fields_hash", "marker_module_path", "marker_qualname",
    "marker_source_relative_path", "marker_source_ref", "marker_source_length", "marker_source_sha256",
    "marker_code_sha256", "marker_code_firstlineno", "probe_module_path", "probe_qualname",
    "probe_source_relative_path", "probe_source_ref", "probe_source_length", "probe_source_sha256",
    "probe_code_sha256", "probe_code_firstlineno", "marker_opcode_whitelist",
    "marker_opcode_sequence_hash", "marker_purity_hash", "read_only",
)
EVIDENCE_CONTENT_FIELDS = (
    "evidence_schema_version", "evaluation_identity", "input_artifact_lineage_records",
    "semantic_result_projection", "source_binding_projection", "capability_projection",
    "resolution_projection", "runtime_projection", "declared_output_relative_paths",
    "input_binding_hash",
)

PRE_PERMIT_ATTESTATION_V15_FIELDS = (
    "attestation_schema_version", "authority_ref", "owner_id",
    "cpython_runtime_snapshot_hash", "writer_trace_plan_snapshot_hash",
    "marker_purity_snapshot_hash", "capability_probe_snapshot_hash",
    "resolution_live_snapshot_hash", "input_binding_hash", "input_manifest_hash",
    "trace_thread_binding", "hook_install_status", "opcode_trace_support",
    "event_delivery_status", "trace_replacement_guard_status", "attestation_status",
)
CAPABILITY_PROBE_RECORD_FIELDS = (
    "probe_schema_version", "capability", "owner_id", "authority_ref",
    "owner_source_relative_path", "owner_source_ref", "owner_source_length",
    "owner_source_sha256", "operation_catalog_hash", "covered_operation_ids",
    "observation_method", "installed", "complete", "observed_call_count",
    "observed_deny_count", "status",
)
CAPABILITY_PROBE_SNAPSHOT_FIELDS = (
    "snapshot_schema_version", "owner_id", "authority_ref",
    "owner_probe_schema_version", "owner_probe_qualname", "owner_probe_code_sha256",
    "owner_probe_source_relative_path", "owner_probe_source_ref", "owner_probe_source_length",
    "owner_probe_source_sha256", "forbidden_capabilities", "candidate_source_coverage",
    "candidate_source_coverage_hash", "evaluator_source_registry_snapshot_hash", "records",
    "complete", "status",
)
CAPABILITY_PROBE_COVERAGE_FIELDS = ("source_role", "source_relative_path", "source_ref", "source_length", "source_sha256")
OWNER_PROBE_BINDING_FIELDS = (
    "owner_probe_schema_version", "owner_id", "authority_ref", "qualname", "code_object_sha256",
    "source_relative_path", "source_ref", "source_length", "source_sha256", "forbidden_capabilities",
    "candidate_source_coverage", "candidate_source_coverage_hash",
)
RESOLUTION_COLLECTION_KINDS = (
    "CANDIDATE_MODULE_SET", "CANDIDATE_SOURCE_PATH_SET", "BOOTSTRAP_MODULE_SET",
    "PRELOADED_CANDIDATE_MODULES", "PRELOADED_CANDIDATE_SOURCE_PATHS",
)
RESOLUTION_COLLECTION_VALUE_TYPES = ("MODULE_NAME_NFC_STRING", "RELATIVE_PATH_NFC_STRING")
RESOLUTION_COLLECTION_SNAPSHOT_FIELDS = (
    "collection_schema_version", "collection_kind", "owner_id", "authority_ref",
    "evaluator_source_registry_snapshot_hash", "entry_value_type", "entries",
    "complete", "status",
)
RESOLUTION_COLLECTION_ENTRY_FIELDS = ("entry_value",)
RESOLUTION_NESTED_SNAPSHOT_FIELDS = (
    "snapshot_kind", "snapshot_schema_version", "owner_id", "authority_ref",
    "evaluator_source_registry_snapshot_hash", "entries", "complete", "status",
)
RESOLUTION_LIVE_SNAPSHOT_FIELDS = (
    "snapshot_schema_version", "owner_id", "authority_ref",
    "evaluator_source_registry_snapshot_hash", "candidate_module_set",
    "candidate_module_set_hash", "candidate_source_path_set",
    "candidate_source_path_set_hash", "bootstrap_module_set", "bootstrap_module_set_hash",
    "preloaded_candidate_modules", "preloaded_candidate_modules_hash",
    "preloaded_candidate_source_paths", "preloaded_candidate_source_paths_hash",
    "sys_path_snapshot_hash", "cwd_snapshot_hash", "meta_path_snapshot_hash",
    "path_hooks_snapshot_hash", "sys_modules_snapshot_hash",
    "resolution_trace_compatibility_matrix_hash", "resolution_trace", "complete", "status",
)
RESOLUTION_PROJECTION_FIELDS = (
    "resolution_guard_snapshot_hash", "resolution_guard", "resolution_live_snapshot_hash",
    "resolution_live_snapshot", "resolution_support",
)
RESOLUTION_SUPPORT_FIELDS = ("collections", "nested", "collection_hashes", "nested_hashes")
OWNER_INPUT_MANIFEST_FIELDS = (
    "manifest_schema_version", "owner_id", "authority_ref", "source_relative_path",
    "source_ref", "source_length", "source_sha256", "manifest_bytes_utf8_hex",
    "input_artifact_lineage_records", "declared_output_relative_paths", "read_only",
)
INPUT_BINDING_PREIMAGE_FIELDS = ("input_artifact_lineage_records", "input_manifest_hash")
FROZEN_OUTPUT_FORBIDDEN_KEY_ALIASES = (
    "output_artifact_id", "output_artifact_digest", "output_artifact_lineage",
    "output_artifact_ref", "output_artifact_refs", "output_lineage", "output_parent",
    "output_parent_ref", "output_parent_refs", "output_target", "output_target_ref",
    "output_target_path", "output_relative_target", "final_output_path", "final_root_path",
    "final_parent_path", "final_target_path", "writer_observation", "residue",
    "residue_snapshot_hash", "residue_evidence_hash", "post_write_status",
    "execution_batch_id", "execution_batch_digest", "evidence_envelope_hash", "run_id",
    "attempt_id", "owner_session_id", "thread_id", "observation_id", "returned_evidence_bytes",
)
EVIDENCE_TWO_PASS_EXCLUDED_FIELDS = FROZEN_OUTPUT_FORBIDDEN_KEY_ALIASES + (
    "evidence_content_hash", "output_artifact_content_sha256",
)
SEMANTIC_RESULT_EXCLUDED_FIELDS = tuple(dict.fromkeys(SEMANTIC_RESULT_EXCLUDED_FIELDS + (
    "final_output_path", "final_root_path", "final_parent_path", "final_target_path",
    "execution_batch_id", "evidence_envelope_hash", "output_artifact_id", "output_artifact_digest",
)))


def _ordered_object(value: Mapping[str, Any], fields: Sequence[str], name: str) -> dict[str, Any]:
    _check_fields(value, fields, name=name)
    return {field: value[field] for field in fields}


def p0_artifact_ref_preimage(value: Any) -> dict[str, Any]:
    """Return the exact P0 ArtifactRef integrity preimage without importing P0."""
    if hasattr(value, "integrity_preimage"):
        value = value.integrity_preimage()
    if not isinstance(value, Mapping):
        raise _error("DENIED_PROVENANCE", "P0 ArtifactRef preimage is not a mapping")
    return _ordered_object(value, P0_ARTIFACTREF_PREIMAGE_FIELDS, "P0 ArtifactRef preimage")


def p0_artifact_lineage(value: Any) -> dict[str, Any]:
    if hasattr(value, "artifact_lineage"):
        value = value.artifact_lineage()
    if not isinstance(value, Mapping):
        raise _error("DENIED_PROVENANCE", "P0 artifact lineage is not a mapping")
    return _ordered_object(value, P0_ARTIFACT_LINEAGE_FIELDS, "P0 artifact lineage")


def p0_lineage_to_ref_preimage(lineage: Mapping[str, Any]) -> dict[str, Any]:
    line = p0_artifact_lineage(lineage)
    value = {field: line[field] for field in P0_ARTIFACTREF_PREIMAGE_FIELDS if field not in {"length", "sha256"}}
    value["length"] = line["content_length"]
    value["sha256"] = line["content_sha256"]
    return _ordered_object(value, P0_ARTIFACTREF_PREIMAGE_FIELDS, "P0 lineage adapter preimage")


def verify_p0_lineage_integrity(lineage: Mapping[str, Any]) -> str:
    line = p0_artifact_lineage(lineage)
    expected = canonical_sha256(p0_lineage_to_ref_preimage(line), fields=P0_ARTIFACTREF_PREIMAGE_FIELDS)
    if line["integrity_digest"] != expected:
        raise _error("DENIED_PROVENANCE", "P0 lineage integrity digest mismatch")
    parents = line["parent_refs"]
    if not isinstance(parents, list) or not parents or any(not isinstance(item, str) or not item for item in parents):
        raise _error("DENIED_PROVENANCE", "P0 parent refs are incomplete")
    return expected


def p0_to_p1_input_lineage_adapter(value: Any) -> dict[str, Any]:
    line = p0_artifact_lineage(value)
    verify_p0_lineage_integrity(line)
    return _ordered_object({
        "p0_artifact_lineage": line,
        "p0_artifact_ref_preimage": p0_lineage_to_ref_preimage(line),
    }, P0_TO_P1_INPUT_LINEAGE_ADAPTER_FIELDS, "P0/P1 lineage adapter")


def _validated_input_lineage_adapter(value: Any) -> dict[str, Any]:
    """Validate the explicit P0-to-P1 adapter, never an opaque artifact id."""
    adapter = _ordered_object(value, P0_TO_P1_INPUT_LINEAGE_ADAPTER_FIELDS, "P0/P1 lineage adapter")
    lineage = p0_artifact_lineage(adapter["p0_artifact_lineage"])
    preimage = p0_artifact_ref_preimage(adapter["p0_artifact_ref_preimage"])
    expected = p0_lineage_to_ref_preimage(lineage)
    if preimage != expected:
        raise _error("DENIED_PROVENANCE", "P0 adapter preimage differs from persisted lineage")
    verify_p0_lineage_integrity(lineage)
    return _ordered_object({
        "p0_artifact_lineage": lineage,
        "p0_artifact_ref_preimage": preimage,
    }, P0_TO_P1_INPUT_LINEAGE_ADAPTER_FIELDS, "P0/P1 lineage adapter")


def input_binding_hash(input_artifact_lineage_records: Sequence[Mapping[str, Any]], input_manifest_hash: str) -> str:
    if not isinstance(input_artifact_lineage_records, list):
        raise _error("DENIED_PROVENANCE", "input lineage records must be an array")
    records = [_validated_input_lineage_adapter(item) for item in input_artifact_lineage_records]
    validate_hash(input_manifest_hash, field="input_manifest_hash")
    return canonical_sha256({"input_artifact_lineage_records": records, "input_manifest_hash": input_manifest_hash}, fields=INPUT_BINDING_PREIMAGE_FIELDS)


def _reject_frozen_forbidden(value: Any, path: str = "$", *, top: bool = False) -> None:
    if isinstance(value, Mapping):
        normalized_keys: set[str] = set()
        for key, item in value.items():
            if not isinstance(key, str):
                raise _error("DENIED_INPUT", f"frozen evidence key is not a string at {path}")
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in normalized_keys:
                raise _error("DENIED_INPUT", f"duplicate NFC frozen evidence key at {path}.{key}")
            normalized_keys.add(normalized_key)
            normalized = normalized_key.casefold()
            if normalized in {item.casefold() for item in FROZEN_OUTPUT_FORBIDDEN_KEY_ALIASES}:
                raise _error("DENIED_INPUT", f"forbidden frozen evidence key at {path}.{key}")
            _reject_frozen_forbidden(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_frozen_forbidden(item, f"{path}[{index}]")


def _validate_frozen_resolution_projection(value: Mapping[str, Any]) -> None:
    _check_fields(value, RESOLUTION_PROJECTION_FIELDS, name="frozen resolution projection")
    validate_hash(value["resolution_guard_snapshot_hash"], field="resolution_guard_snapshot_hash")
    validate_hash(value["resolution_live_snapshot_hash"], field="resolution_live_snapshot_hash")
    live = _ordered_object(value["resolution_live_snapshot"], RESOLUTION_LIVE_SNAPSHOT_FIELDS, "frozen resolution live snapshot")
    if live["complete"] is not True or live["status"] != "READY":
        raise _error("DENIED_CAPABILITY", "frozen resolution live snapshot is not complete and READY")
    trace = live["resolution_trace"]
    if not isinstance(trace, list) or tuple(item.get("sequence") for item in trace if isinstance(item, Mapping)) != tuple(range(len(trace))):
        raise _error("DENIED_CAPABILITY", "frozen resolution trace is incomplete or reordered")
    for item in trace:
        _check_fields(item, DETERMINISTIC_TRACE_EVENT_FIELDS, name="frozen resolution trace event")
    support = _ordered_object(value["resolution_support"], RESOLUTION_SUPPORT_FIELDS, "frozen resolution support")
    _check_fields(support["collections"], RESOLUTION_COLLECTION_KINDS, name="frozen resolution collections")
    _check_fields(support["nested"], ("SYS_PATH", "CWD", "META_PATH", "PATH_HOOKS", "SYS_MODULES"), name="frozen resolution nested snapshots")
    _check_fields(support["collection_hashes"], RESOLUTION_COLLECTION_KINDS, name="frozen resolution collection hashes")
    _check_fields(support["nested_hashes"], ("SYS_PATH", "CWD", "META_PATH", "PATH_HOOKS", "SYS_MODULES"), name="frozen resolution nested hashes")
    for kind in RESOLUTION_COLLECTION_KINDS:
        snapshot = _ordered_object(support["collections"][kind], RESOLUTION_COLLECTION_SNAPSHOT_FIELDS, f"frozen resolution collection {kind}")
        if snapshot["collection_kind"] != kind or snapshot["complete"] is not True or snapshot["status"] != "READY":
            raise _error("DENIED_CAPABILITY", "frozen resolution collection identity or status differs")
        for entry in snapshot["entries"]:
            _check_fields(entry, RESOLUTION_COLLECTION_ENTRY_FIELDS, name="frozen resolution collection entry")
        expected_hash = canonical_sha256(snapshot, fields=RESOLUTION_COLLECTION_SNAPSHOT_FIELDS)
        if support["collection_hashes"][kind] != expected_hash:
            raise _error("DENIED_PROVENANCE", "frozen resolution collection hash mismatch")
    for kind in ("SYS_PATH", "CWD", "META_PATH", "PATH_HOOKS", "SYS_MODULES"):
        snapshot = _ordered_object(support["nested"][kind], RESOLUTION_NESTED_SNAPSHOT_FIELDS, f"frozen resolution nested {kind}")
        if snapshot["snapshot_kind"] != kind or snapshot["complete"] is not True or snapshot["status"] != "READY":
            raise _error("DENIED_CAPABILITY", "frozen nested resolution identity or status differs")
        for entry in snapshot["entries"]:
            _check_fields(entry, RESOLUTION_COLLECTION_ENTRY_FIELDS, name="frozen nested resolution entry")
        expected_hash = canonical_sha256(snapshot, fields=RESOLUTION_NESTED_SNAPSHOT_FIELDS)
        if support["nested_hashes"][kind] != expected_hash:
            raise _error("DENIED_PROVENANCE", "frozen nested resolution hash mismatch")
    if canonical_sha256(live, fields=RESOLUTION_LIVE_SNAPSHOT_FIELDS) != value["resolution_live_snapshot_hash"]:
        raise _error("DENIED_PROVENANCE", "frozen resolution live snapshot hash mismatch")


def freeze_evidence(value: Mapping[str, Any]) -> tuple[bytes, dict[str, Any]]:
    evidence = _ordered_object(value, EVIDENCE_CONTENT_FIELDS, "frozen evidence")
    _reject_frozen_forbidden(evidence)
    identity_fields = (
        "evaluation_case_id", "project_id", "profile_id", "profile_version",
        "profile_definition_hash", "namespace_digest", "project_registry_snapshot_hash",
        "input_manifest_hash", "evaluation_binding_hash",
    )
    _check_fields(evidence["evaluation_identity"], identity_fields, name="frozen evaluation identity")
    _check_fields(evidence["semantic_result_projection"], SEMANTIC_RESULT_FIELDS, name="frozen semantic projection")
    for item in evidence["semantic_result_projection"]["metric_results"]:
        _check_fields(item, ("metric_id", "status", "value", "finding_ids"), name="frozen metric result")
    for item in evidence["semantic_result_projection"]["findings"]:
        _check_fields(item, ("finding_id", "metric_id", "code", "severity", "message_key"), name="frozen finding")
    _check_fields(evidence["source_binding_projection"], ("loaded_source_bindings", "source_registry_snapshot_hash"), name="frozen source projection")
    _check_fields(evidence["capability_projection"], ("owner_observation", "census_snapshot_hash"), name="frozen capability projection")
    _validate_frozen_resolution_projection(evidence["resolution_projection"])
    _check_fields(evidence["runtime_projection"], ("runtime_attestation", "pre_permit_opcode_attestation"), name="frozen runtime projection")
    if tuple(evidence["capability_projection"]["owner_observation"]) != tuple(P1_FORBIDDEN_CAPABILITIES):
        raise _error("DENIED_CAPABILITY", "frozen capability observation fields are not closed")
    runtime_fields = ("attestation_schema_version", "implementation_name", "implementation_version", "cache_tag", "python_version", "opcode_version", "wordcode_size", "has_arg_rule")
    _check_fields(evidence["runtime_projection"]["runtime_attestation"], runtime_fields, name="frozen runtime attestation")
    opcode_attestation = evidence["runtime_projection"]["pre_permit_opcode_attestation"]
    _check_fields(opcode_attestation, ("status", "runtime_snapshot_hash", "events", "marker_opcode_sequence_hash", "marker_call_count", "probe_call_count", "event_delivery_status", "hook_install_status", "trace_replacement_guard_status"), name="frozen opcode attestation")
    if not isinstance(opcode_attestation["events"], list):
        raise _error("DENIED_PROVENANCE", "frozen opcode events must be an array")
    for event in opcode_attestation["events"]:
        _check_fields(event, MARKER_OPCODE_EVENT_FIELDS, name="frozen opcode event")
        if not isinstance(event["sequence"], int) or event["sequence"] < 0:
            raise _error("DENIED_PROVENANCE", "frozen opcode event sequence is invalid")
        if not isinstance(event["instruction_offset"], int) or event["instruction_offset"] < 0:
            raise _error("DENIED_PROVENANCE", "frozen opcode event offset is invalid")
        if not isinstance(event["opcode"], int) or event["opcode"] < 0:
            raise _error("DENIED_PROVENANCE", "frozen opcode event opcode is invalid")
        if not isinstance(event["has_argument"], bool) or event["argument_kind"] not in MARKER_ARGUMENT_KINDS:
            raise _error("DENIED_PROVENANCE", "frozen opcode event argument schema is invalid")
        if event["argument_kind"] == "NONE" and event["argument_value"] is not None:
            raise _error("DENIED_PROVENANCE", "frozen NONE opcode argument must be null")
        if event["argument_kind"] != "NONE" and not isinstance(event["argument_value"], str):
            raise _error("DENIED_PROVENANCE", "frozen opcode argument value is not a string")
    owner_observation = evidence["capability_projection"]["owner_observation"]
    if not isinstance(owner_observation, Mapping) or tuple(owner_observation) != tuple(P1_FORBIDDEN_CAPABILITIES):
        raise _error("DENIED_CAPABILITY", "frozen owner capability observation is not closed")
    if any(not isinstance(item, int) or isinstance(item, bool) or item < 0 for item in owner_observation.values()):
        raise _error("DENIED_CAPABILITY", "frozen owner capability observation contains an invalid count")
    for item in evidence["source_binding_projection"]["loaded_source_bindings"]:
        if not isinstance(item["load_sequence"], int) or item["load_sequence"] < 1:
            raise _error("DENIED_PROVENANCE", "frozen loaded source sequence is invalid")
        for field_name in ("source_length", "preload_length", "postload_length"):
            if not isinstance(item[field_name], int) or item[field_name] < 0:
                raise _error("DENIED_PROVENANCE", f"frozen loaded source {field_name} is invalid")
        for field_name in ("source_sha256", "preload_sha256", "postload_sha256"):
            validate_hash(item[field_name], field=field_name)
    _check_fields(evidence["resolution_projection"]["resolution_guard"], ("guard_schema_version", "guard_id", "owner_id", "authority_ref", "sys_path_snapshot", "cwd_snapshot", "meta_path_snapshot", "path_hooks_snapshot", "sys_modules_snapshot", "candidate_closure_modules", "preloaded_candidate_modules", "preloaded_candidate_source_paths", "bootstrap_module_entries", "read_only", "deny_sys_path_read", "deny_cwd_read", "deny_fallback_finder", "deny_sys_modules_reuse", "deny_builtin_ambient_load"), name="frozen resolution guard")
    loaded_fields = (
        "load_sequence", "module_path", "resolved_path", "source_relative_path", "source_ref",
        "source_length", "source_sha256", "preload_length", "preload_sha256", "postload_length",
        "postload_sha256", "module_file", "spec_origin",
    )
    for item in evidence["source_binding_projection"]["loaded_source_bindings"]:
        _check_fields(item, loaded_fields, name="frozen loaded source binding")
    if not isinstance(evidence["declared_output_relative_paths"], list):
        raise _error("DENIED_INPUT", "declared output paths must be an array")
    for path in evidence["declared_output_relative_paths"]:
        if not isinstance(path, str) or normalize_relative_path(path, allow_root=False) != path:
            raise _error("DENIED_INPUT", "declared output path is not canonical")
    records = evidence["input_artifact_lineage_records"]
    if not isinstance(records, list):
        raise _error("DENIED_INPUT", "frozen evidence input lineage records must be an array")
    normalized_records = [_validated_input_lineage_adapter(item) for item in records]
    expected_binding = input_binding_hash(normalized_records, evidence["evaluation_identity"]["input_manifest_hash"])
    if evidence["input_binding_hash"] != expected_binding:
        raise _error("DENIED_PROVENANCE", "frozen evidence input binding hash mismatch")
    evidence["input_artifact_lineage_records"] = normalized_records
    raw = canonical_evaluation_json_bytes(evidence, fields=EVIDENCE_CONTENT_FIELDS)
    return raw, parse_canonical_evaluation_json(raw, fields=EVIDENCE_CONTENT_FIELDS)


def issue_import_permit_v2(*, owner_session_id: str, sentinel: object, private_handle: object,
                           preimage: Mapping[str, Any], seal_key: bytes, issued_at_utc: str) -> ImportPermitV1:
    _check_fields(preimage, IMPORT_PERMIT_PREIMAGE_FIELDS_V2, name="import permit V2 preimage")
    payload = canonical_evaluation_json_bytes(dict(preimage), fields=IMPORT_PERMIT_PREIMAGE_FIELDS_V2)
    digest = sha256_bytes(payload)
    seal = hmac.new(seal_key, b"P1-IMPORT-PERMIT-V2\x00" + digest.encode("ascii") + b"\x00" + payload, hashlib.sha256).hexdigest()
    return ImportPermitV1(sentinel=sentinel, private_handle=private_handle,
                          owner_session_id=owner_session_id, preimage=dict(preimage),
                          permit_digest=digest, permit_seal=seal, issued_at_utc=issued_at_utc)


def recompute_permit_digest_v2(permit: ImportPermitV1) -> str:
    if not isinstance(permit, ImportPermitV1):
        raise _error("DENIED_CAPABILITY", "permit is not an opaque owner permit")
    return sha256_bytes(canonical_evaluation_json_bytes(permit.preimage, fields=IMPORT_PERMIT_PREIMAGE_FIELDS_V2))


def recompute_permit_seal_v2(permit: ImportPermitV1, seal_key: bytes) -> str:
    payload = canonical_evaluation_json_bytes(permit.preimage, fields=IMPORT_PERMIT_PREIMAGE_FIELDS_V2)
    digest = recompute_permit_digest_v2(permit)
    return hmac.new(seal_key, b"P1-IMPORT-PERMIT-V2\x00" + digest.encode("ascii") + b"\x00" + payload, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# P1-AE quality-evaluation contracts
# ---------------------------------------------------------------------------
# These contracts are deliberately kept in this already owner-bound module.
# They do not alter any P0/P1-A field or hash domain.  The quality hook uses
# the definitions below to create a second, independently consumed permit;
# it never reuses the P1-A candidate-loader permit.

P1_AE_SCHEMA_VERSION = "P1-AE-QUALITY-EVALUATION-V1"
P1_AE_PURE_LOADER_TRANSACTION_SCHEMA_VERSION = "P1_AE_PURE_LOADER_TRANSACTION_V1"
P1_AE_PURE_IMPORT_PERMIT_SCHEMA_VERSION = "P1_AE_PURE_IMPORT_PERMIT_V1"
P1_AE_OWNER_ADMISSION_SCHEMA_VERSION = "P1_AE_OWNER_ADMISSION_V1"

P1_AE_PHASE_VALUES = ("HOST_STATIC_BOUND", "CONSUMED")
P1_AE_PERMIT_STATE_VALUES = P1_AE_PHASE_VALUES
P1_AE_STATUS_VALUES = ("READY", "DENY")
P1_AE_OUTCOME_VALUES = ("ALLOW", "DENY")

P1_AE_PURE_LOADER_PLAN_FIELDS = (
    "loader_plan_schema_version", "plan_id", "owner_id", "authority_ref",
    "owner_session_ref", "pure_source_registry_snapshot_hash",
    "source_module_binding_hash", "pure_gate_snapshot_hash",
    "resolution_guard_snapshot_hash", "resolution_live_snapshot_hash",
    "bootstrap_sequence", "candidate_root_sequence", "candidate_static_sequence",
    "cpython_internal_expected_sequence", "cpython_internal_expected_edge_count",
    "cpython_internal_expected_event_count", "forbidden_expected_count",
    "forbidden_expected_tuple_registry_hash", "host_loader_invoked",
    "host_gate_mutated", "host_permit_mutated", "host_candidate_set_read",
    "permit_consumed_before_import", "pre_permit_state", "post_cas_state",
    "next_required_state", "transition_status", "transition_registry_hash",
    "status",
)
P1_AE_PURE_LOADER_PLAN_PREIMAGE_FIELDS = P1_AE_PURE_LOADER_PLAN_FIELDS
P1_AE_PURE_LOADER_PLAN_BINDING_FIELDS = (
    "loader_plan_hash", "loader_plan_length", "transition_registry_hash",
)
P1_AE_PURE_LOADER_PLAN_TRANSITION_FIELDS = (
    "pre_permit_state", "post_cas_state", "next_required_state",
    "host_loader_invoked", "host_gate_mutated", "host_permit_mutated",
    "host_candidate_set_read", "permit_consumed_before_import",
    "transition_status",
)
P1_AE_PURE_LOADER_PLAN_TRANSITION_TUPLE = (
    "PURE_PERMIT_ISSUED", "CAS_CONSUMED", "INTERNAL_PREFLIGHT_RECHECKED",
    False, False, False, False, True, "ALLOWED",
)
P1_AE_PURE_LOADER_PLAN_TRANSITION_REGISTRY_ORDER = (
    "pre_permit_state", "post_cas_state", "next_required_state",
    "host_loader_invoked", "host_gate_mutated", "host_permit_mutated",
    "host_candidate_set_read", "permit_consumed_before_import",
    "transition_status",
)
P1_AE_PURE_LOADER_PLAN_TRANSITION_REGISTRY_FIELDS = (
    "registry_schema_version", "tuple_fields", "tuples", "status",
)
P1_AE_PURE_LOADER_PLAN_TRANSITION_REGISTRY_PREIMAGE_FIELDS = (
    "registry_schema_version", "tuple_fields", "tuples", "status",
)
P1_AE_PURE_LOADER_PLAN_TRANSITION_REGISTRY_SCHEMA_VERSION = (
    "P1_AE_PURE_LOADER_PLAN_TRANSITION_REGISTRY_V1"
)
P1_AE_PURE_LOADER_PLAN_TRANSITION_REGISTRY_STATUS_VALUES = ("READY", "DENY")
P1_AE_PURE_LOADER_PLAN_TRANSITION_REGISTRY = (
    P1_AE_PURE_LOADER_PLAN_TRANSITION_TUPLE,
)
P1_AE_PURE_LOADER_PLAN_TRANSITION_REGISTRY_RECORD = {
    "registry_schema_version": P1_AE_PURE_LOADER_PLAN_TRANSITION_REGISTRY_SCHEMA_VERSION,
    "tuple_fields": P1_AE_PURE_LOADER_PLAN_TRANSITION_REGISTRY_ORDER,
    "tuples": P1_AE_PURE_LOADER_PLAN_TRANSITION_REGISTRY,
    "status": "READY",
}
P1_AE_PURE_LOADER_PLAN_STATUS_VALUES = ("READY", "DENY")
P1_AE_PURE_LOADER_PLAN_HOST_NONMUTATION_VALUES = (False,)
P1_AE_PURE_LOADER_PLAN_HOST_CANDIDATE_SET_READ_VALUES = (False,)
P1_AE_PURE_LOADER_PLAN_PERMIT_CONSUMED_VALUES = (True,)
P1_AE_PURE_LOADER_PLAN_TRANSITION_STATUS_VALUES = ("ALLOWED", "DENY")
P1_AE_PURE_LOADER_PLAN_STATUS_TRANSITION_PREDICATE = (
    ("READY", "ALLOWED"), ("DENY", "DENY"),
)

P1_AE_PURE_IMPORT_EXPECTED_OBSERVATION_FIELDS = (
    "observation_schema_version", "owner_id", "authority_ref",
    "source_registry_snapshot_hash", "source_module_binding_hash",
    "loader_plan_hash", "loader_plan_length", "transition_registry_hash",
    "transition_fields", "cpython_internal_expected_edges_hash",
    "cpython_internal_expected_events_hash", "cpython_internal_expected_edge_count",
    "cpython_internal_expected_event_count", "forbidden_expected_events_hash",
    "forbidden_expected_count", "forbidden_expected_tuple_registry_hash",
    "phase", "status",
)
P1_AE_PURE_IMPORT_EXPECTED_OBSERVATION_PREIMAGE_FIELDS = (
    "expected_observation",
)
P1_AE_PURE_IMPORT_OBSERVED_COMPARISON_FIELDS = (
    "edge_sequence", "source_ref", "source_length", "source_sha256",
    "code_sha256", "event_offset", "role", "channel", "permit_state",
)

P1_AE_IMPORT_EVENT_FIELDS = (
    "trace_sequence", "event_kind", "caller_module", "target_module",
    "caller_source_ref", "caller_source_length", "caller_source_sha256",
    "target_source_ref", "target_source_length", "target_source_sha256",
    "caller_code_sha256", "target_code_sha256", "offset", "edge_sequence",
    "edge_role", "load_role", "channel", "permit_state", "phase",
    "allowed", "status", "outcome", "failure_reason",
)
P1_AE_IMPORT_EVENT_KIND_VALUES = (
    "BOOTSTRAP_IMPORT", "CANDIDATE_ROOT_IMPORT", "CANDIDATE_STATIC_EDGE",
    "CPYTHON_INTERNAL", "DYNAMIC_IMPORT", "AMBIENT_IMPORT",
)
P1_AE_BOOTSTRAP_ROLE_VALUES = ("P1A_STATIC_BOOTSTRAP",)
P1_AE_CANDIDATE_ROOT_ROLE_VALUES = ("P1AE_DYNAMIC_CANDIDATE",)
P1_AE_CANDIDATE_STATIC_ROLE_VALUES = ("P1AE_STATIC_CANDIDATE_EDGE",)
P1_AE_CPYTHON_INTERNAL_ROLE_VALUES = ("P1AE_INTERNAL_RUNTIME",)
P1_AE_FORBIDDEN_ROLE_VALUES = ("FORBIDDEN",)
P1_AE_CHANNEL_VALUES = (
    "OWNER_STATIC_EDGE", "OWNER_SOURCE_LOADER", "IMPORTLIB_DYNAMIC",
    "SYS_PATH", "CWD", "META_PATH", "PATH_HOOKS", "SYS_MODULES", "BUILTIN",
)

P1_AE_CPYTHON_INTERNAL_EVENT_FIELDS = P1_AE_IMPORT_EVENT_FIELDS
P1_AE_CPYTHON_INTERNAL_EDGE_FIELDS = (
    "edge_sequence", "source_ref", "source_length", "source_sha256",
    "code_sha256", "offset", "role", "channel", "permit_state",
)
P1_AE_CPYTHON_INTERNAL_EVENT_PREIMAGE_FIELDS = ("events",)
P1_AE_CPYTHON_INTERNAL_EDGE_PREIMAGE_FIELDS = ("edges",)
P1_AE_CPYTHON_INTERNAL_EVENT_HASH_FIELDS = P1_AE_CPYTHON_INTERNAL_EVENT_PREIMAGE_FIELDS
P1_AE_CPYTHON_INTERNAL_EDGE_HASH_FIELDS = P1_AE_CPYTHON_INTERNAL_EDGE_PREIMAGE_FIELDS
P1_AE_CPYTHON_INTERNAL_PERMIT_TUPLES = (
    ("INTERNAL_RUNTIME_IMPORT", "P1AE_INTERNAL_RUNTIME", "CPYTHON_INTERNAL", "BUILTIN", "HOST_STATIC_BOUND"),
    ("INTERNAL_RUNTIME_IMPORT", "P1AE_INTERNAL_RUNTIME", "CPYTHON_INTERNAL", "BUILTIN", "CONSUMED"),
)

P1_AE_FORBIDDEN_IMPORT_EVENT_FIELDS = (
    "trace_sequence", "event_kind", "caller_module", "target_module",
    "caller_source_ref", "caller_source_length", "caller_source_sha256",
    "target_source_ref", "target_source_length", "target_source_sha256",
    "caller_code_sha256", "target_code_sha256", "offset", "edge_sequence",
    "edge_role", "load_role", "channel", "permit_state", "phase",
    "allowed", "status", "outcome", "terminal_state", "failure_reason",
)
P1_AE_FORBIDDEN_IMPORT_TUPLE_FIELDS = (
    "event_kind", "load_role", "edge_sequence", "edge_role", "channel",
    "phase", "permit_state", "allowed", "status", "outcome", "terminal_state",
    "failure_reason",
)
P1_AE_FORBIDDEN_IMPORT_EVENT_KIND_VALUES = ("DYNAMIC_IMPORT", "AMBIENT_IMPORT")
P1_AE_FORBIDDEN_IMPORT_STATUS_VALUES = ("TERMINAL_DENY",)
P1_AE_FORBIDDEN_IMPORT_OUTCOME_VALUES = ("DENY",)
P1_AE_FORBIDDEN_IMPORT_TERMINAL_VALUES = ("DENY",)
P1_AE_FORBIDDEN_IMPORT_PROJECTION_STATUS_VALUES = ("CLEAR", "DENY", "INCOMPLETE")
P1_AE_FORBIDDEN_IMPORT_TERMINAL_STATE_VALUES = ("NONE", "DENY")
P1_AE_FORBIDDEN_IMPORT_PROJECTION_FIELDS = (
    "projection_schema_version", "events", "event_hash", "event_count",
    "trace_complete", "status", "terminal_state",
)
P1_AE_FORBIDDEN_IMPORT_PROJECTION_PREIMAGE_FIELDS = (
    "projection_schema_version", "events", "event_hash", "event_count",
    "trace_complete", "status", "terminal_state",
)

P1_AE_RESOLUTION_SNAPSHOT_KINDS = (
    "SYS_PATH", "CWD", "META_PATH", "PATH_HOOKS", "PRELOADED_MODULES",
    "PRELOADED_SOURCE_PATHS",
)
P1_AE_RESOLUTION_ENTRY_FIELDS = (
    "entry_sequence", "value", "value_kind", "normalized_value", "source_ref",
    "source_length", "source_sha256", "status",
)
P1_AE_RESOLUTION_SNAPSHOT_FIELDS = (
    "snapshot_schema_version", "snapshot_kind", "owner_id", "authority_ref",
    "entry_count", "complete", "entries", "nested_preimage_hash", "status",
)
P1_AE_RESOLUTION_SNAPSHOT_PREIMAGE_FIELDS = P1_AE_RESOLUTION_SNAPSHOT_FIELDS
P1_AE_SYS_PATH_SNAPSHOT_FIELDS = P1_AE_RESOLUTION_SNAPSHOT_FIELDS
P1_AE_CWD_SNAPSHOT_FIELDS = (
    "snapshot_schema_version", "snapshot_kind", "owner_id", "authority_ref",
    "entry_count", "complete", "path", "path_kind", "source_ref",
    "source_length", "source_sha256", "status",
)
P1_AE_META_PATH_SNAPSHOT_FIELDS = P1_AE_RESOLUTION_SNAPSHOT_FIELDS
P1_AE_PATH_HOOKS_SNAPSHOT_FIELDS = P1_AE_RESOLUTION_SNAPSHOT_FIELDS
P1_AE_PRELOADED_MODULES_SNAPSHOT_FIELDS = P1_AE_RESOLUTION_SNAPSHOT_FIELDS
P1_AE_PRELOADED_SOURCE_PATHS_SNAPSHOT_FIELDS = P1_AE_RESOLUTION_SNAPSHOT_FIELDS
P1_AE_AUTHORITY_RAW_FIELDS = ("authority_id", "authority_bytes", "authority_bytes_length", "authority_bytes_sha256")
P1_AE_AUTHORITY_RECORD_FIELDS = ("authority_schema_version", "authority_id", "owner_id", "authority_kind", "status")
P1_AE_AUTHORITY_HANDLE_BINDING_FIELDS = ("authority_id", "owner_session", "handle_generation", "request_nonce", "snapshot_hash", "object_identity", "private_identity")
P1_AE_AUTHORITY_COMPOSITE_FIELDS = ("raw_authority_bytes_hash", "authority_record_hash", "handle_binding_hash", "snapshot_hash", "status")
P1_AE_ALLOWED_BOOTSTRAP_EDGE_ROLES = P1_AE_BOOTSTRAP_ROLE_VALUES

P1_AE_LOADER_TRANSACTION_FIELDS = (
    "transaction_schema_version", "transaction_id", "owner_id", "authority_ref",
    "owner_session_ref", "loader_plan_hash", "loader_plan_length",
    "transition_registry_hash", "transition_fields", "permit_digest",
    "permit_cas_sequence", "dynamic_load_count", "dynamic_load_order",
    "forbidden_projection_hash", "observed_projection_hash", "state", "status",
)
P1_AE_LOADER_TRANSACTION_PREIMAGE_FIELDS = P1_AE_LOADER_TRANSACTION_FIELDS
P1_AE_PACKAGE_FIELDS = (
    "package_schema_version", "owner_id", "authority_ref", "source_registry_hash",
    "source_module_binding_hash", "loader_plan_hash", "loader_plan_length",
    "transition_registry_hash", "transition_fields", "resolution_guard_hash",
    "resolution_live_hash", "expected_observation_hash", "status",
)
P1_AE_GATE_PREIMAGE_FIELDS = P1_AE_PACKAGE_FIELDS
P1_AE_PERMIT_PREIMAGE_FIELDS = (
    "permit_schema_version", "owner_id", "authority_ref", "owner_session_ref",
    "package_hash", "loader_plan_hash", "loader_plan_length",
    "transition_registry_hash", "transition_fields", "expected_observation_hash",
    "status",
)
P1_AE_OWNER_ADMISSION_PREIMAGE_FIELDS = (
    "admission_schema_version", "owner_id", "authority_ref", "owner_session_ref",
    "source_registry_hash", "package_hash", "gate_hash", "permit_digest",
    "loader_plan_hash", "loader_plan_length", "transition_registry_hash",
    "transition_fields", "transaction_hash", "semantic_hash", "status",
)

P1_AE_FROZEN_EVIDENCE_CONTENT_FIELDS = (
    "evidence_schema_version", "evaluation_identity", "input_projection",
    "semantic_result_projection", "annotation_projection", "metric_projection",
    "claim_projection", "status",
)
P1_AE_QUALITY_BUNDLE_FIELDS = (
    "bundle_schema_version", "study_id", "owner_id", "authority_ref",
    "source_snapshot_hash", "rubric_hash", "sampling_plan_hash",
    "strata", "clusters", "cases", "status",
)
P1_AE_QUALITY_STRATUM_FIELDS = (
    "stratum_id", "book_tier", "narrative_position", "scene_mode",
    "pipeline_difficulty", "pipeline_score_band", "context_requirement",
)
P1_AE_QUALITY_CLUSTER_FIELDS = ("book_cluster_ref", "stratum_id", "case_ids")
P1_AE_QUALITY_CASE_FIELDS = (
    "case_id", "book_cluster_ref", "chapter_id", "blind_case_id",
    "input_text", "input_text_sha256", "pipeline_observation", "annotations",
)
P1_AE_QUALITY_ANNOTATION_FIELDS = (
    "annotation_id", "rater_id", "pass_kind", "blindness_status",
    "visible_ai_metadata", "visible_other_rater_annotations",
    "visible_historical_labels", "dimension_values", "status",
)
P1_AE_QUALITY_DIMENSION_FIELDS = ("dimension_id", "value")
P1_AE_QUALITY_ADMISSION_FIELDS = (
    "admission_schema_version", "owner_id", "authority_ref", "owner_session_ref",
    "package_hash", "gate_hash", "permit_digest", "loader_plan_hash",
    "loader_plan_length", "transition_registry_hash", "transition_fields",
    "transaction_hash", "status",
)


def _p1ae_transition_registry_record(status: str = "READY") -> dict[str, Any]:
    if status not in P1_AE_STATUS_VALUES:
        raise _error("DENIED_CAPABILITY", "invalid P1-AE transition registry status")
    tuples = [list(P1_AE_PURE_LOADER_PLAN_TRANSITION_TUPLE)] if status == "READY" else []
    return {
        "registry_schema_version": P1_AE_PURE_LOADER_PLAN_TRANSITION_REGISTRY_SCHEMA_VERSION,
        "tuple_fields": list(P1_AE_PURE_LOADER_PLAN_TRANSITION_REGISTRY_ORDER),
        "tuples": tuples,
        "status": status,
    }


def p1ae_transition_registry_hash(status: str = "READY") -> str:
    record = _p1ae_transition_registry_record(status)
    return canonical_sha256(record, fields=P1_AE_PURE_LOADER_PLAN_TRANSITION_REGISTRY_PREIMAGE_FIELDS)


def p1ae_transition_tuple(record: Mapping[str, Any]) -> tuple[Any, ...]:
    if tuple(record.get("tuple_fields", ())) != P1_AE_PURE_LOADER_PLAN_TRANSITION_REGISTRY_ORDER:
        raise _error("DENIED_CAPABILITY", "transition tuple field order is not canonical")
    tuples = record.get("tuples")
    if not isinstance(tuples, list) or len(tuples) != 1:
        raise _error("DENIED_CAPABILITY", "transition registry is not the sole allowed tuple")
    value = tuple(tuples[0])
    if value != P1_AE_PURE_LOADER_PLAN_TRANSITION_TUPLE:
        raise _error("DENIED_CAPABILITY", "transition tuple is not the canonical allowed tuple")
    return value


def validate_p1ae_transition(status: str, transition_status: str) -> None:
    if (status, transition_status) not in P1_AE_PURE_LOADER_PLAN_STATUS_TRANSITION_PREDICATE:
        raise _error("DENIED_CAPABILITY", "P1-AE transition/status pair is invalid")


def p1ae_loader_plan_bytes(value: Mapping[str, Any]) -> bytes:
    _check_fields(value, P1_AE_PURE_LOADER_PLAN_FIELDS, name="P1-AE loader plan")
    validate_p1ae_transition(value["status"], value["transition_status"])
    if value["status"] == "READY":
        if tuple(value[field] for field in P1_AE_PURE_LOADER_PLAN_TRANSITION_FIELDS) != P1_AE_PURE_LOADER_PLAN_TRANSITION_TUPLE:
            raise _error("DENIED_CAPABILITY", "loader plan transition tuple is not canonical")
        if value["transition_registry_hash"] != p1ae_transition_registry_hash("READY"):
            raise _error("DENIED_CAPABILITY", "loader plan transition registry hash mismatch")
    elif value["transition_registry_hash"] != p1ae_transition_registry_hash("DENY"):
        raise _error("DENIED_CAPABILITY", "denied loader plan registry hash mismatch")
    for field in ("pure_source_registry_snapshot_hash", "source_module_binding_hash",
                  "pure_gate_snapshot_hash", "resolution_guard_snapshot_hash",
                  "resolution_live_snapshot_hash", "transition_registry_hash"):
        validate_hash(value[field], field=field)
    for field in ("cpython_internal_expected_edge_count", "cpython_internal_expected_event_count", "forbidden_expected_count"):
        if not isinstance(value[field], int) or isinstance(value[field], bool) or value[field] < 0:
            raise _error("DENIED_CAPABILITY", f"{field} is invalid")
    if value["host_loader_invoked"] or value["host_gate_mutated"] or value["host_permit_mutated"] or value["host_candidate_set_read"]:
        raise _error("DENIED_CAPABILITY", "host non-mutation tuple is not false")
    if value["permit_consumed_before_import"] is not True:
        raise _error("DENIED_CAPABILITY", "permit consumed-before-import fact is not true")
    return canonical_evaluation_json_bytes(value, fields=P1_AE_PURE_LOADER_PLAN_PREIMAGE_FIELDS)


# These are the final post-correction field orders.  They are deliberately
# assigned after the legacy compatibility definitions above so every caller
# observes the same resolution, expected-module, and authority bindings.
P1_AE_PACKAGE_FIELDS = P1_AE_PACKAGE_FIELDS + ("resolution_projection_hash", "expected_loaded_module_projection_hash")
P1_AE_GATE_PREIMAGE_FIELDS = P1_AE_PACKAGE_FIELDS
P1_AE_PERMIT_PREIMAGE_FIELDS = P1_AE_PERMIT_PREIMAGE_FIELDS + ("resolution_projection_hash", "expected_loaded_module_projection_hash", "authority_binding_hash")
P1_AE_LOADER_TRANSACTION_FIELDS = P1_AE_LOADER_TRANSACTION_FIELDS + ("resolution_projection_hash", "authority_binding_hash")
P1_AE_LOADER_TRANSACTION_PREIMAGE_FIELDS = P1_AE_LOADER_TRANSACTION_FIELDS
P1_AE_OWNER_ADMISSION_PREIMAGE_FIELDS = P1_AE_OWNER_ADMISSION_PREIMAGE_FIELDS + ("resolution_projection_hash", "authority_binding_hash", "owner_registry_snapshot_hash", "owner_annotation_projection_hash")
P1_AE_QUALITY_ADMISSION_FIELDS = P1_AE_OWNER_ADMISSION_PREIMAGE_FIELDS

# Contract-fixed quality bootstrap and claim constants.  These are registry
# facts, not evaluator-selected defaults.
P1_AE_BOOTSTRAP_SEED_FIELDS = (
    "study_id", "project_id", "profile_id", "namespace_digest",
    "dataset_manifest_hash", "rubric_hash", "sampling_plan_hash",
    "stratum_registry_hash", "metric_plan_hash", "annotator_protocol_hash",
    "split_plan_hash", "p1a_contract_hash", "p1a_source_registry_snapshot_hash",
    "p1ae_pure_source_registry_snapshot_hash",
)
P1_AE_BOOTSTRAP_REPLICATE_COUNT = 2000
P1_AE_BOOTSTRAP_CLUSTER_KEY = "book_cluster_ref"
P1_AE_BOOTSTRAP_RESAMPLING_METHOD = "WITH_REPLACEMENT_BOOK_CLUSTER"
P1_AE_BOOTSTRAP_DRAW_ALGORITHM = "SHA256_COUNTER_MODULO_V1"
P1_AE_BOOTSTRAP_QUANTILE_ALGORITHM = "Hyndman_Fan_Type_7"
P1_AE_BOOTSTRAP_CI_METHOD = "PERCENTILE_95"
P1_AE_BOOTSTRAP_ALPHA = "0.05"
P1_AE_RELIABILITY_THRESHOLD = "67/100"
P1_AE_RETEST_THRESHOLD = "70/100"
P1_AE_RETEST_MINIMUM_FRACTION = "1/5"
P1_AE_CLAIM_CI_THRESHOLD = "50/100"

# EOF runtime override for the gated correction.  This block is deliberately
# last: compatibility definitions above cannot become the active authority.
P1_AE_OWNER_REGISTRY_RECORD_FIELDS = (
    "registry_schema_version", "record_id", "annotation_id", "case_id", "pass_kind",
    "rater_id", "owner_id", "owner_session", "human_only", "blindness_status",
    "independence_status", "source_ref", "source_length", "source_sha256",
    "source_readback_sha256", "status",
)
P1_AE_REGISTRY_HANDLE_FIELDS = (
    "record_id", "annotation_id", "case_id", "pass_kind", "authority_id",
    "owner_session", "request_nonce", "generation", "snapshot_hash",
    "source_readback_sha256", "owner_secret_seal",
)

class P1AERegistryHandleV1:
    __slots__ = ("_secret", "_private_identity", "_object_identity", "_cas_lock", "_immutable", "record_id", "annotation_id", "case_id", "pass_kind", "authority_id", "owner_session", "request_nonce", "generation", "snapshot_hash", "source_readback_sha256", "owner_secret_seal", "consumed", "replay_generation")
    def __init__(self, *, authority_id: str, owner_session: str, generation: int, request_nonce: str, snapshot_hash: str, secret: object, source_readback_sha256: str, record_id: str = "", annotation_id: str = "", case_id: str = "", pass_kind: str = ""):
        object.__setattr__(self, "_immutable", False); object.__setattr__(self, "_secret", secret); object.__setattr__(self, "_private_identity", object()); object.__setattr__(self, "_object_identity", object()); object.__setattr__(self, "_cas_lock", threading.RLock())
        for name, value in (("record_id", record_id), ("annotation_id", annotation_id), ("case_id", case_id), ("pass_kind", pass_kind), ("authority_id", authority_id), ("owner_session", owner_session), ("request_nonce", request_nonce), ("generation", generation), ("snapshot_hash", snapshot_hash), ("source_readback_sha256", source_readback_sha256)):
            object.__setattr__(self, name, value)
        seal_input = "|".join((record_id, annotation_id, case_id, pass_kind, authority_id, owner_session, request_nonce, str(generation), snapshot_hash, source_readback_sha256))
        object.__setattr__(self, "owner_secret_seal", hmac.new(str(id(secret)).encode("ascii"), seal_input.encode("utf-8"), hashlib.sha256).hexdigest()); object.__setattr__(self, "consumed", False); object.__setattr__(self, "replay_generation", None); object.__setattr__(self, "_immutable", True)
    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_immutable", False) and name not in {"consumed", "replay_generation"}:
            raise _error("DENIED_AUTHORITY", "registry handle binding is immutable")
        object.__setattr__(self, name, value)
    def __copy__(self) -> Any:
        raise _error("DENIED_AUTHORITY", "registry handle copy is denied")
    def __deepcopy__(self, memo: dict[int, Any]) -> Any:
        raise _error("DENIED_AUTHORITY", "registry handle deepcopy is denied")
    def __reduce__(self) -> Any:
        raise _error("DENIED_AUTHORITY", "registry handle serialization is denied")

def issue_p1ae_registry_handle(*, owner_session: str, request_nonce: str, authority_id: str, snapshot_hash: str, secret: object | None = None, source_readback_sha256: str = "0" * 64, generation: int = 1, record_id: str = "", annotation_id: str = "", case_id: str = "", pass_kind: str = "") -> P1AERegistryHandleV1:
    secret = object() if secret is None else secret; validate_hash(snapshot_hash, field="snapshot_hash"); validate_hash(source_readback_sha256, field="source_readback_sha256")
    return P1AERegistryHandleV1(authority_id=authority_id, owner_session=owner_session, generation=generation, request_nonce=request_nonce, snapshot_hash=snapshot_hash, secret=secret, source_readback_sha256=source_readback_sha256, record_id=record_id, annotation_id=annotation_id, case_id=case_id, pass_kind=pass_kind)

def consume_p1ae_registry_handle(handle: P1AERegistryHandleV1, *, owner_session: str, request_nonce: str, secret: object, snapshot_hash: str, record_id: str | None = None, annotation_id: str | None = None, case_id: str | None = None, pass_kind: str | None = None) -> int:
    if not isinstance(handle, P1AERegistryHandleV1):
        raise _error("DENIED_AUTHORITY", "registry handle type is invalid")
    with handle._cas_lock:
        if handle._secret is not secret or handle.owner_session != owner_session or handle.request_nonce != request_nonce or handle.snapshot_hash != snapshot_hash or handle.consumed:
            raise _error("DENIED_AUTHORITY", "registry handle replay/use denied")
        for field, value in (("record_id", record_id), ("annotation_id", annotation_id), ("case_id", case_id), ("pass_kind", pass_kind)):
            if value is not None and getattr(handle, field) != value:
                raise _error("DENIED_AUTHORITY", f"registry handle {field} mismatch")
        object.__setattr__(handle, "consumed", True); object.__setattr__(handle, "replay_generation", handle.generation + 1); return handle.replay_generation

class P1AEOwnerRegistryV1:
    __slots__ = ("_secret", "_authority_bytes", "_source_readback", "_records", "_lock", "_owner_id", "_owner_session", "_request_nonce", "_generation", "snapshot")
    def __init__(self, *, owner_id: str, owner_session: str, request_nonce: str, authority_bytes: bytes, source_readback: bytes, records: Sequence[Mapping[str, Any]], generation: int = 1):
        if not isinstance(authority_bytes, bytes) or authority_bytes != source_readback:
            raise _error("DENIED_AUTHORITY", "owner authority source readback mismatch")
        source_hash = sha256_bytes(authority_bytes); canonical_records = []
        for item in records:
            _check_fields(item, P1_AE_OWNER_REGISTRY_RECORD_FIELDS, name="owner registry record")
            if item["registry_schema_version"] != P1_AE_OWNER_REGISTRY_SCHEMA_VERSION or item["owner_id"] != owner_id or item["owner_session"] != owner_session or item["status"] != "READY" or item["human_only"] is not True or item["blindness_status"] != "BLIND" or item["independence_status"] != "INDEPENDENT":
                raise _error("DENIED_AUTHORITY", "annotation authority is not owner-issued")
            if item["source_length"] != len(authority_bytes) or item["source_sha256"] != source_hash or item["source_readback_sha256"] != source_hash:
                raise _error("DENIED_AUTHORITY", "owner registry source binding mismatch")
            canonical_records.append(dict(item))
        canonical_records.sort(key=lambda item: item["record_id"].encode("utf-8"))
        if len({item["record_id"] for item in canonical_records}) != len(canonical_records):
            raise _error("DENIED_AUTHORITY", "owner registry record collision")
        self._secret = object(); self._authority_bytes = authority_bytes; self._source_readback = source_readback; self._records = {item["record_id"]: item for item in canonical_records}; self._lock = threading.RLock(); self._owner_id = owner_id; self._owner_session = owner_session; self._request_nonce = request_nonce; self._generation = generation
        record_hash = canonical_sha256({"records": canonical_records}, fields=("records",)); seal = hmac.new(str(id(self._secret)).encode("ascii"), f"{owner_id}|{owner_session}|{generation}|{request_nonce}|{record_hash}|{source_hash}".encode("utf-8"), hashlib.sha256).hexdigest()
        self.snapshot = {"snapshot_schema_version": P1_AE_OWNER_REGISTRY_SNAPSHOT_SCHEMA_VERSION, "owner_id": owner_id, "owner_session": owner_session, "generation": generation, "request_nonce": request_nonce, "records": canonical_records, "record_hash": record_hash, "source_readback_sha256": source_hash, "owner_secret_seal": seal, "status": "READY"}
    @property
    def snapshot_hash(self) -> str:
        return canonical_sha256(self.snapshot, fields=P1_AE_OWNER_REGISTRY_SNAPSHOT_FIELDS)
    def issue_record_handle(self, record_id: str, *, case_id: str, pass_kind: str, annotation_id: str) -> P1AERegistryHandleV1:
        with self._lock:
            record = self._records.get(record_id)
            if record is None or (record["annotation_id"], record["case_id"], record["pass_kind"]) != (annotation_id, case_id, pass_kind):
                raise _error("DENIED_AUTHORITY", "owner identity tuple mismatch")
            self._generation += 1
            return issue_p1ae_registry_handle(owner_session=self._owner_session, request_nonce=f"{self._request_nonce}:{self._generation}:{record_id}", authority_id=self._owner_id, snapshot_hash=self.snapshot_hash, secret=self._secret, source_readback_sha256=sha256_bytes(self._source_readback), generation=self._generation, record_id=record_id, annotation_id=annotation_id, case_id=case_id, pass_kind=pass_kind)
    def lookup(self, *, handle: P1AERegistryHandleV1, record_id: str, case_id: str, pass_kind: str, annotation_id: str) -> dict[str, Any]:
        with self._lock:
            if handle._secret is not self._secret or handle.authority_id != self._owner_id:
                raise _error("DENIED_AUTHORITY", "owner handle private identity mismatch")
            consume_p1ae_registry_handle(handle, owner_session=self._owner_session, request_nonce=handle.request_nonce, secret=self._secret, snapshot_hash=self.snapshot_hash, record_id=record_id, annotation_id=annotation_id, case_id=case_id, pass_kind=pass_kind)
            record = self._records.get(record_id)
            if record is None:
                raise _error("DENIED_AUTHORITY", "owner lookup record is missing")
            return dict(record)
    def owner_lookup(self, record_id: str, *, case_id: str, pass_kind: str, annotation_id: str) -> tuple[dict[str, Any], P1AERegistryHandleV1]:
        handle = self.issue_record_handle(record_id, case_id=case_id, pass_kind=pass_kind, annotation_id=annotation_id)
        return self.lookup(handle=handle, record_id=record_id, case_id=case_id, pass_kind=pass_kind, annotation_id=annotation_id), handle

P1_AE_CPYTHON_INTERNAL_EXPECTED_EVENT_FIELDS = P1_AE_IMPORT_EVENT_FIELDS
P1_AE_CPYTHON_INTERNAL_EXPECTED_EDGE_FIELDS = P1_AE_CPYTHON_INTERNAL_EDGE_FIELDS
P1_AE_CPYTHON_INTERNAL_OBSERVED_EVENT_FIELDS = P1_AE_IMPORT_EVENT_FIELDS
P1_AE_CPYTHON_INTERNAL_OBSERVED_EDGE_FIELDS = P1_AE_CPYTHON_INTERNAL_EDGE_FIELDS
P1_AE_CPYTHON_INTERNAL_EXPECTED_PREIMAGE_FIELDS = ("events", "edges", "event_count", "edge_count")
P1_AE_CPYTHON_INTERNAL_OBSERVED_PREIMAGE_FIELDS = P1_AE_CPYTHON_INTERNAL_EXPECTED_PREIMAGE_FIELDS
P1_AE_CPYTHON_INTERNAL_COMPARISON_FIELDS = ("trace_sequence", "event_kind", "caller_module", "target_module", "caller_source_ref", "caller_source_length", "caller_source_sha256", "target_source_ref", "target_source_length", "target_source_sha256", "caller_code_sha256", "target_code_sha256", "offset", "edge_sequence", "edge_role", "load_role", "channel", "permit_state", "phase", "allowed")
def p1ae_cpython_internal_projection_hash(value: Mapping[str, Any], *, observed: bool) -> str:
    fields = P1_AE_CPYTHON_INTERNAL_OBSERVED_PREIMAGE_FIELDS if observed else P1_AE_CPYTHON_INTERNAL_EXPECTED_PREIMAGE_FIELDS; _check_fields(value, fields, name="CPython internal projection")
    if value["event_count"] != len(value["events"]) or value["edge_count"] != len(value["edges"]):
        raise _error("DENIED_CAPABILITY", "CPython internal projection count mismatch")
    return canonical_sha256(value, fields=fields)
def p1ae_cpython_internal_comparison_bytes(value: Mapping[str, Any]) -> bytes:
    events = [{field: item[field] for field in P1_AE_CPYTHON_INTERNAL_COMPARISON_FIELDS} for item in value["events"]]; edges = [{field: item[field] for field in P1_AE_CPYTHON_INTERNAL_COMPARISON_FIELDS if field in item} for item in value["edges"]]
    return canonical_evaluation_json_bytes({"events": events, "edges": edges}, fields=("events", "edges"))
P1_AE_OWNER_ADMISSION_BINDING_FIELDS = ("package", "gate", "permit", "transaction", "authority", "writer", "residue", "pairing")
P1_AE_OWNER_ADMISSION_PREIMAGE_FIELDS = P1_AE_OWNER_ADMISSION_PREIMAGE_FIELDS + ("binding_records",)
P1_AE_QUALITY_ADMISSION_FIELDS = P1_AE_OWNER_ADMISSION_PREIMAGE_FIELDS

# C5-P1-AE-CODE-CORRECTION-READONLY-GATED-2 final definitions.  These names
# intentionally occur after the compatibility block so the runtime cannot
# fall back to the caller-constructed registry or the pre-CAS-only projection.
P1_AE_OWNER_REGISTRY_RECORD_FIELDS = (
    "registry_schema_version", "record_id", "annotation_id", "case_id", "pass_kind",
    "rater_id", "owner_id", "owner_session", "human_only", "blindness_status",
    "independence_status", "source_ref", "source_length", "source_sha256",
    "source_readback_sha256", "status",
)
P1_AE_REGISTRY_HANDLE_FIELDS = (
    "record_id", "annotation_id", "case_id", "pass_kind", "authority_id",
    "owner_session", "request_nonce", "generation", "snapshot_hash",
    "source_readback_sha256", "owner_secret_seal",
)

class P1AERegistryHandleV1:
    __slots__ = ("_secret", "_private_identity", "_object_identity", "_cas_lock",
                 "_immutable", "record_id", "annotation_id", "case_id", "pass_kind",
                 "authority_id", "owner_session", "request_nonce", "generation",
                 "snapshot_hash", "source_readback_sha256", "owner_secret_seal",
                 "consumed", "replay_generation")

    def __init__(self, *, authority_id: str, owner_session: str, generation: int,
                 request_nonce: str, snapshot_hash: str, secret: object,
                 source_readback_sha256: str, record_id: str = "",
                 annotation_id: str = "", case_id: str = "", pass_kind: str = ""):
        object.__setattr__(self, "_immutable", False)
        object.__setattr__(self, "_secret", secret)
        object.__setattr__(self, "_private_identity", object())
        object.__setattr__(self, "_object_identity", object())
        object.__setattr__(self, "_cas_lock", threading.RLock())
        for name, value in (("record_id", record_id), ("annotation_id", annotation_id),
                            ("case_id", case_id), ("pass_kind", pass_kind),
                            ("authority_id", authority_id), ("owner_session", owner_session),
                            ("request_nonce", request_nonce), ("generation", generation),
                            ("snapshot_hash", snapshot_hash),
                            ("source_readback_sha256", source_readback_sha256)):
            object.__setattr__(self, name, value)
        seal_input = "|".join((record_id, annotation_id, case_id, pass_kind, authority_id,
                               owner_session, request_nonce, str(generation), snapshot_hash,
                               source_readback_sha256))
        object.__setattr__(self, "owner_secret_seal", hmac.new(
            str(id(secret)).encode("ascii"), seal_input.encode("utf-8"), hashlib.sha256,
        ).hexdigest())
        object.__setattr__(self, "consumed", False)
        object.__setattr__(self, "replay_generation", None)
        object.__setattr__(self, "_immutable", True)

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_immutable", False) and name not in {"consumed", "replay_generation"}:
            raise _error("DENIED_AUTHORITY", "registry handle binding is immutable")
        object.__setattr__(self, name, value)

    def __copy__(self) -> Any:
        raise _error("DENIED_AUTHORITY", "registry handle copy is denied")

    def __deepcopy__(self, memo: dict[int, Any]) -> Any:
        raise _error("DENIED_AUTHORITY", "registry handle deepcopy is denied")

    def __reduce__(self) -> Any:
        raise _error("DENIED_AUTHORITY", "registry handle serialization is denied")


def issue_p1ae_registry_handle(*, owner_session: str, request_nonce: str,
                               authority_id: str, snapshot_hash: str,
                               secret: object | None = None,
                               source_readback_sha256: str = "0" * 64,
                               generation: int = 1, record_id: str = "",
                               annotation_id: str = "", case_id: str = "",
                               pass_kind: str = "") -> P1AERegistryHandleV1:
    secret = object() if secret is None else secret
    validate_hash(snapshot_hash, field="snapshot_hash")
    validate_hash(source_readback_sha256, field="source_readback_sha256")
    return P1AERegistryHandleV1(
        authority_id=authority_id, owner_session=owner_session, generation=generation,
        request_nonce=request_nonce, snapshot_hash=snapshot_hash, secret=secret,
        source_readback_sha256=source_readback_sha256, record_id=record_id,
        annotation_id=annotation_id, case_id=case_id, pass_kind=pass_kind,
    )


def consume_p1ae_registry_handle(handle: P1AERegistryHandleV1, *, owner_session: str,
                                 request_nonce: str, secret: object, snapshot_hash: str,
                                 record_id: str | None = None,
                                 annotation_id: str | None = None,
                                 case_id: str | None = None,
                                 pass_kind: str | None = None) -> int:
    if not isinstance(handle, P1AERegistryHandleV1):
        raise _error("DENIED_AUTHORITY", "registry handle type is invalid")
    with handle._cas_lock:
        if (handle._secret is not secret or handle.owner_session != owner_session
                or handle.request_nonce != request_nonce or handle.snapshot_hash != snapshot_hash
                or handle.consumed):
            raise _error("DENIED_AUTHORITY", "registry handle replay/use denied")
        for field, value in (("record_id", record_id), ("annotation_id", annotation_id),
                             ("case_id", case_id), ("pass_kind", pass_kind)):
            if value is not None and getattr(handle, field) != value:
                raise _error("DENIED_AUTHORITY", f"registry handle {field} mismatch")
        object.__setattr__(handle, "consumed", True)
        object.__setattr__(handle, "replay_generation", handle.generation + 1)
        return handle.replay_generation


class P1AEOwnerRegistryV1:
    __slots__ = ("_secret", "_authority_bytes", "_source_readback", "_records", "_lock",
                 "_owner_id", "_owner_session", "_request_nonce", "_generation", "snapshot")

    def __init__(self, *, owner_id: str, owner_session: str, request_nonce: str,
                 authority_bytes: bytes, source_readback: bytes,
                 records: Sequence[Mapping[str, Any]], generation: int = 1):
        if not isinstance(authority_bytes, bytes) or authority_bytes != source_readback:
            raise _error("DENIED_AUTHORITY", "owner authority source readback mismatch")
        source_hash = sha256_bytes(authority_bytes); canonical_records: list[dict[str, Any]] = []
        for item in records:
            _check_fields(item, P1_AE_OWNER_REGISTRY_RECORD_FIELDS, name="owner registry record")
            if (item["registry_schema_version"] != P1_AE_OWNER_REGISTRY_SCHEMA_VERSION
                    or item["owner_id"] != owner_id or item["owner_session"] != owner_session
                    or item["status"] != "READY" or item["human_only"] is not True
                    or item["blindness_status"] != "BLIND"
                    or item["independence_status"] != "INDEPENDENT"):
                raise _error("DENIED_AUTHORITY", "annotation authority is not owner-issued")
            if (item["source_length"] != len(authority_bytes)
                    or item["source_sha256"] != source_hash
                    or item["source_readback_sha256"] != source_hash):
                raise _error("DENIED_AUTHORITY", "owner registry source binding mismatch")
            canonical_records.append(dict(item))
        canonical_records.sort(key=lambda item: item["record_id"].encode("utf-8"))
        if len({item["record_id"] for item in canonical_records}) != len(canonical_records):
            raise _error("DENIED_AUTHORITY", "owner registry record collision")
        self._secret = object(); self._authority_bytes = authority_bytes
        self._source_readback = source_readback; self._records = {
            item["record_id"]: item for item in canonical_records
        }
        self._lock = threading.RLock(); self._owner_id = owner_id
        self._owner_session = owner_session; self._request_nonce = request_nonce
        self._generation = generation
        record_hash = canonical_sha256({"records": canonical_records}, fields=("records",))
        seal = hmac.new(str(id(self._secret)).encode("ascii"),
                        f"{owner_id}|{owner_session}|{generation}|{request_nonce}|{record_hash}|{source_hash}".encode("utf-8"), hashlib.sha256).hexdigest()
        self.snapshot = {"snapshot_schema_version": P1_AE_OWNER_REGISTRY_SNAPSHOT_SCHEMA_VERSION,
                         "owner_id": owner_id, "owner_session": owner_session,
                         "generation": generation, "request_nonce": request_nonce,
                         "records": canonical_records, "record_hash": record_hash,
                         "source_readback_sha256": source_hash, "owner_secret_seal": seal,
                         "status": "READY"}

    @property
    def snapshot_hash(self) -> str:
        return canonical_sha256(self.snapshot, fields=P1_AE_OWNER_REGISTRY_SNAPSHOT_FIELDS)

    def issue_record_handle(self, record_id: str, *, case_id: str, pass_kind: str,
                            annotation_id: str) -> P1AERegistryHandleV1:
        with self._lock:
            record = self._records.get(record_id)
            identity = (annotation_id, case_id, pass_kind)
            if record is None or (record["annotation_id"], record["case_id"], record["pass_kind"]) != identity:
                raise _error("DENIED_AUTHORITY", "owner identity tuple mismatch")
            self._generation += 1
            return issue_p1ae_registry_handle(
                owner_session=self._owner_session,
                request_nonce=f"{self._request_nonce}:{self._generation}:{record_id}",
                authority_id=self._owner_id, snapshot_hash=self.snapshot_hash,
                secret=self._secret, source_readback_sha256=sha256_bytes(self._source_readback),
                generation=self._generation, record_id=record_id,
                annotation_id=annotation_id, case_id=case_id, pass_kind=pass_kind,
            )

    def lookup(self, *, handle: P1AERegistryHandleV1, record_id: str, case_id: str,
               pass_kind: str, annotation_id: str) -> dict[str, Any]:
        with self._lock:
            if handle._secret is not self._secret or handle.authority_id != self._owner_id:
                raise _error("DENIED_AUTHORITY", "owner handle private identity mismatch")
            consume_p1ae_registry_handle(handle, owner_session=self._owner_session,
                                         request_nonce=handle.request_nonce, secret=self._secret,
                                         snapshot_hash=self.snapshot_hash, record_id=record_id,
                                         annotation_id=annotation_id, case_id=case_id,
                                         pass_kind=pass_kind)
            record = self._records.get(record_id)
            if record is None:
                raise _error("DENIED_AUTHORITY", "owner lookup record is missing")
            return dict(record)

    def owner_lookup(self, record_id: str, *, case_id: str, pass_kind: str,
                     annotation_id: str) -> tuple[dict[str, Any], P1AERegistryHandleV1]:
        handle = self.issue_record_handle(record_id, case_id=case_id, pass_kind=pass_kind,
                                           annotation_id=annotation_id)
        return self.lookup(handle=handle, record_id=record_id, case_id=case_id,
                           pass_kind=pass_kind, annotation_id=annotation_id), handle

P1_AE_CPYTHON_INTERNAL_EXPECTED_EVENT_FIELDS = P1_AE_IMPORT_EVENT_FIELDS
P1_AE_CPYTHON_INTERNAL_EXPECTED_EDGE_FIELDS = P1_AE_CPYTHON_INTERNAL_EDGE_FIELDS
P1_AE_CPYTHON_INTERNAL_OBSERVED_EVENT_FIELDS = P1_AE_IMPORT_EVENT_FIELDS
P1_AE_CPYTHON_INTERNAL_OBSERVED_EDGE_FIELDS = P1_AE_CPYTHON_INTERNAL_EDGE_FIELDS
P1_AE_CPYTHON_INTERNAL_EXPECTED_PREIMAGE_FIELDS = ("events", "edges", "event_count", "edge_count")
P1_AE_CPYTHON_INTERNAL_OBSERVED_PREIMAGE_FIELDS = P1_AE_CPYTHON_INTERNAL_EXPECTED_PREIMAGE_FIELDS
P1_AE_CPYTHON_INTERNAL_COMPARISON_FIELDS = (
    "trace_sequence", "event_kind", "caller_module", "target_module", "caller_source_ref",
    "caller_source_length", "caller_source_sha256", "target_source_ref", "target_source_length",
    "target_source_sha256", "caller_code_sha256", "target_code_sha256", "offset", "edge_sequence",
    "edge_role", "load_role", "channel", "permit_state", "phase", "allowed",
)
def p1ae_cpython_internal_projection_hash(value: Mapping[str, Any], *, observed: bool) -> str:
    fields = P1_AE_CPYTHON_INTERNAL_OBSERVED_PREIMAGE_FIELDS if observed else P1_AE_CPYTHON_INTERNAL_EXPECTED_PREIMAGE_FIELDS
    _check_fields(value, fields, name="CPython internal projection")
    if value["event_count"] != len(value["events"]) or value["edge_count"] != len(value["edges"]):
        raise _error("DENIED_CAPABILITY", "CPython internal projection count mismatch")
    return canonical_sha256(value, fields=fields)
def p1ae_cpython_internal_comparison_bytes(value: Mapping[str, Any]) -> bytes:
    events = [{field: item[field] for field in P1_AE_CPYTHON_INTERNAL_COMPARISON_FIELDS} for item in value["events"]]
    edges = [{field: item[field] for field in P1_AE_CPYTHON_INTERNAL_COMPARISON_FIELDS if field in item} for item in value["edges"]]
    return canonical_evaluation_json_bytes({"events": events, "edges": edges}, fields=("events", "edges"))

P1_AE_OWNER_ADMISSION_BINDING_FIELDS = ("package", "gate", "permit", "transaction", "authority", "writer", "residue", "pairing")
P1_AE_OWNER_ADMISSION_PREIMAGE_FIELDS = P1_AE_OWNER_ADMISSION_PREIMAGE_FIELDS + ("binding_records",)
P1_AE_QUALITY_ADMISSION_FIELDS = P1_AE_OWNER_ADMISSION_PREIMAGE_FIELDS
__all__ += ["P1_AE_REGISTRY_HANDLE_FIELDS", "P1_AE_CPYTHON_INTERNAL_EXPECTED_EVENT_FIELDS", "P1_AE_CPYTHON_INTERNAL_EXPECTED_EDGE_FIELDS", "P1_AE_CPYTHON_INTERNAL_OBSERVED_EVENT_FIELDS", "P1_AE_CPYTHON_INTERNAL_OBSERVED_EDGE_FIELDS", "P1_AE_CPYTHON_INTERNAL_EXPECTED_PREIMAGE_FIELDS", "P1_AE_CPYTHON_INTERNAL_OBSERVED_PREIMAGE_FIELDS", "P1_AE_CPYTHON_INTERNAL_COMPARISON_FIELDS", "p1ae_cpython_internal_projection_hash", "p1ae_cpython_internal_comparison_bytes", "P1_AE_OWNER_ADMISSION_BINDING_FIELDS"]

# Final gated correction: the authority handle is a private, single-use
# capability.  Identity fields are bound to the owner record, not asserted by
# the evaluation caller.  The registry owns the CAS lock and the secret.
P1_AE_OWNER_REGISTRY_RECORD_FIELDS = (
    "registry_schema_version", "record_id", "annotation_id", "case_id", "pass_kind",
    "rater_id", "owner_id", "owner_session", "human_only", "blindness_status",
    "independence_status", "source_ref", "source_length", "source_sha256",
    "source_readback_sha256", "status",
)
P1_AE_REGISTRY_HANDLE_FIELDS = (
    "record_id", "annotation_id", "case_id", "pass_kind", "authority_id",
    "owner_session", "request_nonce", "generation", "snapshot_hash",
    "source_readback_sha256", "owner_secret_seal",
)

class P1AERegistryHandleV1:
    __slots__ = (
        "_secret", "_private_identity", "_object_identity", "_cas_lock", "_immutable",
        "record_id", "annotation_id", "case_id", "pass_kind", "authority_id",
        "owner_session", "request_nonce", "generation", "snapshot_hash",
        "source_readback_sha256", "owner_secret_seal", "consumed", "replay_generation",
    )

    def __init__(self, *, authority_id: str, owner_session: str, generation: int,
                 request_nonce: str, snapshot_hash: str, secret: object,
                 source_readback_sha256: str, record_id: str = "",
                 annotation_id: str = "", case_id: str = "", pass_kind: str = ""):
        object.__setattr__(self, "_immutable", False)
        object.__setattr__(self, "_secret", secret)
        object.__setattr__(self, "_private_identity", object())
        object.__setattr__(self, "_object_identity", object())
        object.__setattr__(self, "_cas_lock", threading.RLock())
        for name, value in (
            ("record_id", record_id), ("annotation_id", annotation_id),
            ("case_id", case_id), ("pass_kind", pass_kind),
            ("authority_id", authority_id), ("owner_session", owner_session),
            ("request_nonce", request_nonce), ("generation", generation),
            ("snapshot_hash", snapshot_hash),
            ("source_readback_sha256", source_readback_sha256),
        ):
            object.__setattr__(self, name, value)
        seal_input = "|".join((record_id, annotation_id, case_id, pass_kind,
                               authority_id, owner_session, request_nonce,
                               str(generation), snapshot_hash,
                               source_readback_sha256))
        object.__setattr__(self, "owner_secret_seal", hmac.new(
            str(id(secret)).encode("ascii"), seal_input.encode("utf-8"), hashlib.sha256,
        ).hexdigest())
        object.__setattr__(self, "consumed", False)
        object.__setattr__(self, "replay_generation", None)
        object.__setattr__(self, "_immutable", True)

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_immutable", False) and name not in {"consumed", "replay_generation"}:
            raise _error("DENIED_AUTHORITY", "registry handle binding is immutable")
        object.__setattr__(self, name, value)

    def __copy__(self) -> Any:
        raise _error("DENIED_AUTHORITY", "registry handle copy is denied")

    def __deepcopy__(self, memo: dict[int, Any]) -> Any:
        raise _error("DENIED_AUTHORITY", "registry handle deepcopy is denied")

    def __reduce__(self) -> Any:
        raise _error("DENIED_AUTHORITY", "registry handle serialization is denied")


def issue_p1ae_registry_handle(*, owner_session: str, request_nonce: str,
                               authority_id: str, snapshot_hash: str,
                               secret: object | None = None,
                               source_readback_sha256: str = "0" * 64,
                               generation: int = 1, record_id: str = "",
                               annotation_id: str = "", case_id: str = "",
                               pass_kind: str = "") -> P1AERegistryHandleV1:
    if secret is None:
        secret = object()
    validate_hash(snapshot_hash, field="snapshot_hash")
    validate_hash(source_readback_sha256, field="source_readback_sha256")
    return P1AERegistryHandleV1(
        authority_id=authority_id, owner_session=owner_session,
        generation=generation, request_nonce=request_nonce,
        snapshot_hash=snapshot_hash, secret=secret,
        source_readback_sha256=source_readback_sha256, record_id=record_id,
        annotation_id=annotation_id, case_id=case_id, pass_kind=pass_kind,
    )


def consume_p1ae_registry_handle(handle: P1AERegistryHandleV1, *,
                                 owner_session: str, request_nonce: str,
                                 secret: object, snapshot_hash: str,
                                 record_id: str | None = None,
                                 annotation_id: str | None = None,
                                 case_id: str | None = None,
                                 pass_kind: str | None = None) -> int:
    if not isinstance(handle, P1AERegistryHandleV1):
        raise _error("DENIED_AUTHORITY", "registry handle type is invalid")
    with handle._cas_lock:
        if (handle._secret is not secret or handle.owner_session != owner_session
                or handle.request_nonce != request_nonce
                or handle.snapshot_hash != snapshot_hash or handle.consumed):
            raise _error("DENIED_AUTHORITY", "registry handle replay/use denied")
        expected = (("record_id", record_id), ("annotation_id", annotation_id),
                    ("case_id", case_id), ("pass_kind", pass_kind))
        for field, value in expected:
            if value is not None and getattr(handle, field) != value:
                raise _error("DENIED_AUTHORITY", f"registry handle {field} mismatch")
        object.__setattr__(handle, "consumed", True)
        object.__setattr__(handle, "replay_generation", handle.generation + 1)
        return handle.replay_generation


class P1AEOwnerRegistryV1:
    __slots__ = ("_secret", "_authority_bytes", "_source_readback", "_records",
                 "_lock", "_owner_id", "_owner_session", "_request_nonce",
                 "_generation", "snapshot")

    def __init__(self, *, owner_id: str, owner_session: str, request_nonce: str,
                 authority_bytes: bytes, source_readback: bytes,
                 records: Sequence[Mapping[str, Any]], generation: int = 1):
        if not isinstance(authority_bytes, bytes) or authority_bytes != source_readback:
            raise _error("DENIED_AUTHORITY", "owner authority source readback mismatch")
        authority_hash = sha256_bytes(authority_bytes)
        canonical_records: list[dict[str, Any]] = []
        for item in records:
            _check_fields(item, P1_AE_OWNER_REGISTRY_RECORD_FIELDS, name="owner registry record")
            if (item["registry_schema_version"] != P1_AE_OWNER_REGISTRY_SCHEMA_VERSION
                    or item["owner_id"] != owner_id or item["owner_session"] != owner_session
                    or item["status"] != "READY" or item["human_only"] is not True
                    or item["blindness_status"] != "BLIND"
                    or item["independence_status"] != "INDEPENDENT"):
                raise _error("DENIED_AUTHORITY", "annotation authority is not owner-issued")
            if (item["source_length"] != len(authority_bytes)
                    or item["source_sha256"] != authority_hash
                    or item["source_readback_sha256"] != authority_hash):
                raise _error("DENIED_AUTHORITY", "owner registry source binding mismatch")
            canonical_records.append(dict(item))
        canonical_records.sort(key=lambda item: item["record_id"].encode("utf-8"))
        if len({item["record_id"] for item in canonical_records}) != len(canonical_records):
            raise _error("DENIED_AUTHORITY", "owner registry record collision")
        self._secret = object(); self._authority_bytes = authority_bytes
        self._source_readback = source_readback; self._records = {
            item["record_id"]: item for item in canonical_records
        }
        self._lock = threading.RLock(); self._owner_id = owner_id
        self._owner_session = owner_session; self._request_nonce = request_nonce
        self._generation = generation
        record_hash = canonical_sha256({"records": canonical_records}, fields=("records",))
        seal = hmac.new(
            str(id(self._secret)).encode("ascii"),
            f"{owner_id}|{owner_session}|{generation}|{request_nonce}|{record_hash}|{authority_hash}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        self.snapshot = {
            "snapshot_schema_version": P1_AE_OWNER_REGISTRY_SNAPSHOT_SCHEMA_VERSION,
            "owner_id": owner_id, "owner_session": owner_session,
            "generation": generation, "request_nonce": request_nonce,
            "records": canonical_records, "record_hash": record_hash,
            "source_readback_sha256": authority_hash,
            "owner_secret_seal": seal, "status": "READY",
        }

    @property
    def snapshot_hash(self) -> str:
        return canonical_sha256(self.snapshot, fields=P1_AE_OWNER_REGISTRY_SNAPSHOT_FIELDS)

    def issue_record_handle(self, record_id: str, *, case_id: str,
                            pass_kind: str, annotation_id: str) -> P1AERegistryHandleV1:
        with self._lock:
            record = self._records.get(record_id)
            if record is None or (record["annotation_id"], record["case_id"], record["pass_kind"]) != (annotation_id, case_id, pass_kind):
                raise _error("DENIED_AUTHORITY", "owner identity tuple mismatch")
            self._generation += 1
            return issue_p1ae_registry_handle(
                owner_session=self._owner_session,
                request_nonce=f"{self._request_nonce}:{self._generation}:{record_id}",
                authority_id=self._owner_id, snapshot_hash=self.snapshot_hash,
                secret=self._secret, source_readback_sha256=sha256_bytes(self._source_readback),
                generation=self._generation, record_id=record_id,
                annotation_id=annotation_id, case_id=case_id, pass_kind=pass_kind,
            )

    def lookup(self, *, handle: P1AERegistryHandleV1, record_id: str,
               case_id: str, pass_kind: str, annotation_id: str) -> dict[str, Any]:
        with self._lock:
            if handle._secret is not self._secret or handle.authority_id != self._owner_id:
                raise _error("DENIED_AUTHORITY", "owner handle private identity mismatch")
            consume_p1ae_registry_handle(
                handle, owner_session=self._owner_session,
                request_nonce=handle.request_nonce, secret=self._secret,
                snapshot_hash=self.snapshot_hash, record_id=record_id,
                annotation_id=annotation_id, case_id=case_id, pass_kind=pass_kind,
            )
            record = self._records.get(record_id)
            if record is None or (record["annotation_id"], record["case_id"], record["pass_kind"]) != (annotation_id, case_id, pass_kind):
                raise _error("DENIED_AUTHORITY", "owner lookup identity mismatch")
            return dict(record)

    def owner_lookup(self, record_id: str, *, case_id: str, pass_kind: str,
                     annotation_id: str) -> tuple[dict[str, Any], P1AERegistryHandleV1]:
        handle = self.issue_record_handle(record_id, case_id=case_id,
                                           pass_kind=pass_kind, annotation_id=annotation_id)
        return self.lookup(handle=handle, record_id=record_id, case_id=case_id,
                           pass_kind=pass_kind, annotation_id=annotation_id), handle

P1_AE_CPYTHON_INTERNAL_EXPECTED_EVENT_FIELDS = P1_AE_IMPORT_EVENT_FIELDS
P1_AE_CPYTHON_INTERNAL_EXPECTED_EDGE_FIELDS = P1_AE_CPYTHON_INTERNAL_EDGE_FIELDS
P1_AE_CPYTHON_INTERNAL_OBSERVED_EVENT_FIELDS = P1_AE_IMPORT_EVENT_FIELDS
P1_AE_CPYTHON_INTERNAL_OBSERVED_EDGE_FIELDS = P1_AE_CPYTHON_INTERNAL_EDGE_FIELDS
P1_AE_CPYTHON_INTERNAL_EXPECTED_PREIMAGE_FIELDS = ("events", "edges", "event_count", "edge_count")
P1_AE_CPYTHON_INTERNAL_OBSERVED_PREIMAGE_FIELDS = P1_AE_CPYTHON_INTERNAL_EXPECTED_PREIMAGE_FIELDS
P1_AE_CPYTHON_INTERNAL_COMPARISON_FIELDS = (
    "trace_sequence", "event_kind", "caller_module", "target_module",
    "caller_source_ref", "caller_source_length", "caller_source_sha256",
    "target_source_ref", "target_source_length", "target_source_sha256",
    "caller_code_sha256", "target_code_sha256", "offset", "edge_sequence",
    "edge_role", "load_role", "channel", "permit_state", "phase", "allowed",
)

def p1ae_cpython_internal_projection_hash(value: Mapping[str, Any], *, observed: bool) -> str:
    fields = P1_AE_CPYTHON_INTERNAL_OBSERVED_PREIMAGE_FIELDS if observed else P1_AE_CPYTHON_INTERNAL_EXPECTED_PREIMAGE_FIELDS
    _check_fields(value, fields, name="CPython internal projection")
    if value["event_count"] != len(value["events"]) or value["edge_count"] != len(value["edges"]):
        raise _error("DENIED_CAPABILITY", "CPython internal projection count mismatch")
    return canonical_sha256(value, fields=fields)

def p1ae_cpython_internal_comparison_bytes(value: Mapping[str, Any]) -> bytes:
    events = [{field: event[field] for field in P1_AE_CPYTHON_INTERNAL_COMPARISON_FIELDS} for event in value["events"]]
    edges = [{field: edge[field] for field in P1_AE_CPYTHON_INTERNAL_COMPARISON_FIELDS if field in edge} for edge in value["edges"]]
    return canonical_evaluation_json_bytes({"events": events, "edges": edges}, fields=("events", "edges"))

P1_AE_OWNER_ADMISSION_BINDING_FIELDS = (
    "package", "gate", "permit", "transaction", "authority", "writer", "residue", "pairing",
)
P1_AE_OWNER_ADMISSION_PREIMAGE_FIELDS = P1_AE_OWNER_ADMISSION_PREIMAGE_FIELDS + ("binding_records",)
P1_AE_QUALITY_ADMISSION_FIELDS = P1_AE_OWNER_ADMISSION_PREIMAGE_FIELDS
__all__ += [
    "P1_AE_REGISTRY_HANDLE_FIELDS", "P1_AE_CPYTHON_INTERNAL_EXPECTED_EVENT_FIELDS",
    "P1_AE_CPYTHON_INTERNAL_EXPECTED_EDGE_FIELDS", "P1_AE_CPYTHON_INTERNAL_OBSERVED_EVENT_FIELDS",
    "P1_AE_CPYTHON_INTERNAL_OBSERVED_EDGE_FIELDS", "P1_AE_CPYTHON_INTERNAL_EXPECTED_PREIMAGE_FIELDS",
    "P1_AE_CPYTHON_INTERNAL_OBSERVED_PREIMAGE_FIELDS", "P1_AE_CPYTHON_INTERNAL_COMPARISON_FIELDS",
    "p1ae_cpython_internal_projection_hash", "p1ae_cpython_internal_comparison_bytes",
    "P1_AE_OWNER_ADMISSION_BINDING_FIELDS",
]


class P1AERegistryHandleV1:
    __slots__ = ("_secret", "_private_identity", "_object_identity", "authority_id", "owner_session", "generation", "request_nonce", "snapshot_hash", "source_readback_sha256", "owner_secret_seal", "consumed", "replay_generation")

    def __init__(self, *, authority_id: str, owner_session: str, generation: int, request_nonce: str, snapshot_hash: str, secret: object, source_readback_sha256: str):
        object.__setattr__(self, "_secret", secret)
        object.__setattr__(self, "_private_identity", object())
        object.__setattr__(self, "_object_identity", id(self))
        object.__setattr__(self, "authority_id", authority_id)
        object.__setattr__(self, "owner_session", owner_session)
        object.__setattr__(self, "generation", generation)
        object.__setattr__(self, "request_nonce", request_nonce)
        object.__setattr__(self, "snapshot_hash", snapshot_hash)
        object.__setattr__(self, "source_readback_sha256", source_readback_sha256)
        object.__setattr__(self, "owner_secret_seal", hmac.new(str(id(secret)).encode("ascii"), f"{authority_id}|{owner_session}|{generation}|{request_nonce}|{snapshot_hash}|{source_readback_sha256}".encode("utf-8"), hashlib.sha256).hexdigest())
        object.__setattr__(self, "consumed", False)
        object.__setattr__(self, "replay_generation", None)

    def __setattr__(self, name: str, value: Any) -> None:
        if hasattr(self, name):
            raise _error("DENIED_AUTHORITY", "registry handle is immutable; only owner CAS may consume it")
        object.__setattr__(self, name, value)

    def __copy__(self) -> Any:
        raise _error("DENIED_AUTHORITY", "registry handle copy is denied")

    def __deepcopy__(self, memo: dict[int, Any]) -> Any:
        raise _error("DENIED_AUTHORITY", "registry handle serialization/copy is denied")

    def __reduce__(self) -> Any:
        raise _error("DENIED_AUTHORITY", "registry handle serialization is denied")


def issue_p1ae_registry_handle(*, owner_session: str, request_nonce: str, authority_id: str, snapshot_hash: str, secret: object | None = None, source_readback_sha256: str = "0" * 64, generation: int = 1) -> P1AERegistryHandleV1:
    if secret is None:
        secret = object()
    validate_hash(snapshot_hash, field="snapshot_hash")
    validate_hash(source_readback_sha256, field="source_readback_sha256")
    return P1AERegistryHandleV1(authority_id=authority_id, owner_session=owner_session, generation=generation, request_nonce=request_nonce, snapshot_hash=snapshot_hash, secret=secret, source_readback_sha256=source_readback_sha256)


def consume_p1ae_registry_handle(handle: P1AERegistryHandleV1, *, owner_session: str, request_nonce: str, secret: object, snapshot_hash: str) -> int:
    if not isinstance(handle, P1AERegistryHandleV1) or handle.owner_session != owner_session or handle.request_nonce != request_nonce or handle.snapshot_hash != snapshot_hash or handle._secret is not secret or handle.consumed:
        raise _error("DENIED_AUTHORITY", "registry handle replay/copy/serialization denied")
    object.__setattr__(handle, "consumed", True)
    object.__setattr__(handle, "replay_generation", handle.generation + 1)
    return handle.replay_generation


def p1ae_loader_plan_hash(value: Mapping[str, Any]) -> str:
    return sha256_bytes(p1ae_loader_plan_bytes(value))


def p1ae_loader_plan_binding(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = p1ae_loader_plan_bytes(value)
    return {"loader_plan_hash": sha256_bytes(raw), "loader_plan_length": len(raw),
            "transition_registry_hash": value["transition_registry_hash"]}


def p1ae_expected_observation_hash(value: Mapping[str, Any]) -> str:
    _check_fields(value, P1_AE_PURE_IMPORT_EXPECTED_OBSERVATION_FIELDS, name="P1-AE expected observation")
    raw = canonical_evaluation_json_bytes({"expected_observation": dict(value)}, fields=P1_AE_PURE_IMPORT_EXPECTED_OBSERVATION_PREIMAGE_FIELDS)
    return sha256_bytes(raw)


def p1ae_forbidden_projection_hash(value: Mapping[str, Any]) -> str:
    _check_fields(value, P1_AE_FORBIDDEN_IMPORT_PROJECTION_FIELDS, name="P1-AE forbidden projection")
    return canonical_sha256(value, fields=P1_AE_FORBIDDEN_IMPORT_PROJECTION_PREIMAGE_FIELDS)


def validate_p1ae_forbidden_event(value: Mapping[str, Any]) -> dict[str, Any]:
    _check_fields(value, P1_AE_FORBIDDEN_IMPORT_EVENT_FIELDS, name="P1-AE forbidden event")
    if value["event_kind"] not in P1_AE_FORBIDDEN_IMPORT_EVENT_KIND_VALUES or value["load_role"] != "FORBIDDEN":
        raise _error("DENIED_CAPABILITY", "forbidden event taxonomy mismatch")
    if value["edge_sequence"] is not None or value["edge_role"] is not None:
        raise _error("DENIED_CAPABILITY", "forbidden edge fields must be JSON null")
    if value["phase"] != value["permit_state"] or value["permit_state"] not in P1_AE_PHASE_VALUES:
        raise _error("DENIED_CAPABILITY", "forbidden event phase/permit mismatch")
    if value["allowed"] is not False or value["status"] != "TERMINAL_DENY" or value["outcome"] != "DENY" or value["terminal_state"] != "DENY":
        raise _error("DENIED_CAPABILITY", "forbidden event is not terminal deny")
    for field in ("caller_source_sha256", "target_source_sha256", "caller_code_sha256", "target_code_sha256"):
        validate_hash(value[field], field=field)
    if not isinstance(value["offset"], int) or value["offset"] < 0:
        raise _error("DENIED_CAPABILITY", "forbidden event offset is invalid")
    if not isinstance(value["failure_reason"], str) or not value["failure_reason"]:
        raise _error("DENIED_CAPABILITY", "forbidden event failure reason is missing")
    return {field: value[field] for field in P1_AE_FORBIDDEN_IMPORT_EVENT_FIELDS}


def validate_p1ae_import_event(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate mutually exclusive import taxonomy and cross-field binding."""
    _check_fields(value, P1_AE_IMPORT_EVENT_FIELDS, name="P1-AE import event")
    kind = value["event_kind"]
    role = value["load_role"]
    channel = value["channel"]
    state = value["permit_state"]
    if value["phase"] != state or state not in P1_AE_PHASE_VALUES:
        raise _error("DENIED_CAPABILITY", "import event phase and permit state differ")
    predicates = {
        "BOOTSTRAP_IMPORT": (role == "P1A_STATIC_BOOTSTRAP" and channel == "OWNER_STATIC_EDGE" and state == "HOST_STATIC_BOUND"),
        "CANDIDATE_ROOT_IMPORT": (role == "P1AE_DYNAMIC_CANDIDATE" and channel == "IMPORTLIB_DYNAMIC" and state == "CONSUMED"),
        "CANDIDATE_STATIC_EDGE": (role == "P1AE_STATIC_CANDIDATE_EDGE" and channel == "OWNER_STATIC_EDGE" and state == "CONSUMED"),
        "CPYTHON_INTERNAL": (role == "P1AE_INTERNAL_RUNTIME" and channel == "BUILTIN" and state in P1_AE_PHASE_VALUES),
        "DYNAMIC_IMPORT": (role == "FORBIDDEN" and channel in P1_AE_CHANNEL_VALUES and value["edge_sequence"] is None and value["edge_role"] is None),
        "AMBIENT_IMPORT": (role == "FORBIDDEN" and channel in P1_AE_CHANNEL_VALUES and value["edge_sequence"] is None and value["edge_role"] is None),
    }
    if kind not in predicates or not predicates[kind]:
        raise _error("DENIED_CAPABILITY", "import event kind/role/channel/state cross-field predicate failed")
    if kind == "CPYTHON_INTERNAL" and role in P1_AE_BOOTSTRAP_ROLE_VALUES:
        raise _error("DENIED_CAPABILITY", "CPython internal event cannot be bootstrap")
    if kind in {"DYNAMIC_IMPORT", "AMBIENT_IMPORT"}:
        return validate_p1ae_forbidden_event({
            **value, "trace_sequence": value["trace_sequence"], "offset": value["offset"],
            "caller_source_length": value["caller_source_length"], "target_source_length": value["target_source_length"],
            "caller_source_sha256": value["caller_source_sha256"], "target_source_sha256": value["target_source_sha256"],
            "caller_code_sha256": value["caller_code_sha256"], "target_code_sha256": value["target_code_sha256"],
            "terminal_state": "DENY", "failure_reason": value["failure_reason"],
        })
    return {field: value[field] for field in P1_AE_IMPORT_EVENT_FIELDS}


def p1ae_authority_hashes(*, authority_bytes: bytes, authority_record: Mapping[str, Any],
                          handle_binding: Mapping[str, Any], snapshot_hash: str) -> dict[str, str]:
    if not isinstance(authority_bytes, bytes) or b"\x00" in authority_bytes:
        raise _error("DENIED_AUTHORITY", "authority bytes are invalid")
    _check_fields(authority_record, P1_AE_AUTHORITY_RECORD_FIELDS, name="authority record")
    _check_fields(handle_binding, P1_AE_AUTHORITY_HANDLE_BINDING_FIELDS, name="authority handle binding")
    validate_hash(snapshot_hash, field="snapshot_hash")
    raw_hash = sha256_bytes(authority_bytes)
    record_hash = canonical_sha256(authority_record, fields=P1_AE_AUTHORITY_RECORD_FIELDS)
    handle_hash = canonical_sha256(handle_binding, fields=P1_AE_AUTHORITY_HANDLE_BINDING_FIELDS)
    composite = {"raw_authority_bytes_hash": raw_hash, "authority_record_hash": record_hash,
                 "handle_binding_hash": handle_hash, "snapshot_hash": snapshot_hash, "status": "VERIFIED"}
    return {"raw_authority_bytes_hash": raw_hash, "authority_record_hash": record_hash,
            "handle_binding_hash": handle_hash,
            "composite_authority_binding_hash": canonical_sha256(composite, fields=P1_AE_AUTHORITY_COMPOSITE_FIELDS)}


def p1ae_resolution_snapshot_hash(value: Mapping[str, Any]) -> str:
    if value["snapshot_kind"] not in P1_AE_RESOLUTION_SNAPSHOT_KINDS:
        raise _error("DENIED_PROVENANCE", "resolution snapshot kind is not specialized")
    fields = P1_AE_CWD_SNAPSHOT_FIELDS if value["snapshot_kind"] == "CWD" else P1_AE_RESOLUTION_SNAPSHOT_FIELDS
    _check_fields(value, fields, name="P1-AE resolution snapshot")
    if value["snapshot_kind"] == "CWD":
        if value["status"] == "READY" and (value["entry_count"], value["complete"], value["path"] is not None) != (1, True, True):
            raise _error("DENIED_PROVENANCE", "CWD READY singleton semantics failed")
        if value["status"] == "DENY" and (value["entry_count"], value["complete"], value["path"]) != (0, False, None):
            raise _error("DENIED_PROVENANCE", "CWD DENY singleton semantics failed")
        return canonical_sha256(value, fields=P1_AE_CWD_SNAPSHOT_FIELDS)
    entries = value["entries"]
    if not isinstance(entries, list) or value["entry_count"] != len(entries):
        raise _error("DENIED_PROVENANCE", "resolution snapshot entry count mismatch")
    for item in entries:
        _check_fields(item, P1_AE_RESOLUTION_ENTRY_FIELDS, name="resolution entry")
    return canonical_sha256(value, fields=P1_AE_RESOLUTION_SNAPSHOT_PREIMAGE_FIELDS)


class P1AERegistryHandleV1:
    """Owner-issued, one-admission capability for annotation authority."""

    __slots__ = ("_secret", "_object_identity", "_private_identity", "generation",
                 "owner_session", "request_nonce", "snapshot_hash", "consumed",
                 "replay_generation")

    def __init__(self, *, owner_session: str, request_nonce: str, snapshot_hash: str,
                 secret: object, generation: int = 1) -> None:
        self._secret = secret
        self._object_identity = object()
        self._private_identity = object()
        self.generation = generation
        self.owner_session = owner_session
        self.request_nonce = request_nonce
        self.snapshot_hash = snapshot_hash
        self.consumed = False
        self.replay_generation = generation


def issue_p1ae_registry_handle(*, owner_session: str, request_nonce: str,
                               snapshot_hash: str, owner_secret: object) -> P1AERegistryHandleV1:
    if not isinstance(owner_session, str) or not owner_session or not isinstance(request_nonce, str) or not request_nonce:
        raise _error("DENIED_AUTHORITY", "registry handle identity is incomplete")
    validate_hash(snapshot_hash, field="snapshot_hash")
    return P1AERegistryHandleV1(owner_session=owner_session, request_nonce=request_nonce,
                                snapshot_hash=snapshot_hash, secret=owner_secret)


def consume_p1ae_registry_handle(handle: P1AERegistryHandleV1, *, owner_session: str,
                                 request_nonce: str, snapshot_hash: str,
                                 owner_secret: object) -> dict[str, Any]:
    if not isinstance(handle, P1AERegistryHandleV1) or handle._secret is not owner_secret:
        raise _error("DENIED_AUTHORITY", "registry handle authority is invalid")
    if handle.consumed or handle.replay_generation != handle.generation:
        raise _error("DENIED_AUTHORITY", "registry handle replay denied")
    if (owner_session, request_nonce, snapshot_hash) != (handle.owner_session, handle.request_nonce, handle.snapshot_hash):
        raise _error("DENIED_AUTHORITY", "registry handle binding mismatch")
    handle.consumed = True
    handle.replay_generation += 1
    return {"handle_generation": handle.generation, "owner_session": owner_session,
            "request_nonce": request_nonce, "consumed": True,
            "replay_generation": handle.replay_generation,
            "object_identity": id(handle._object_identity),
            "private_identity": id(handle._private_identity),
            "snapshot_hash": handle.snapshot_hash}


class P1AEPurePermitV1:
    """Independent P1-AE permit with owner-side one-shot CAS state."""

    __slots__ = ("_secret", "_private_handle", "owner_session_ref", "preimage",
                 "digest", "state", "cas_sequence")

    def __init__(self, *, owner_session_ref: str, preimage: Mapping[str, Any],
                 secret: object, private_handle: object) -> None:
        self._secret = secret
        self._private_handle = private_handle
        self.owner_session_ref = owner_session_ref
        self.preimage = {field: preimage[field] for field in P1_AE_PERMIT_PREIMAGE_FIELDS}
        self.digest = canonical_sha256(self.preimage, fields=P1_AE_PERMIT_PREIMAGE_FIELDS)
        self.state = "ISSUED"
        self.cas_sequence = 0

    def consume(self, *, secret: object, private_handle: object) -> str:
        if secret is not self._secret or private_handle is not self._private_handle:
            raise _error("DENIED_CAPABILITY", "P1-AE permit private identity mismatch")
        if self.state != "ISSUED" or self.cas_sequence != 0:
            raise _error("DENIED_CAPABILITY", "P1-AE permit replay denied")
        self.state = "CONSUMED"
        self.cas_sequence = 1
        return self.digest


def issue_p1ae_pure_permit(*, owner_session_ref: str, preimage: Mapping[str, Any],
                           secret: object, private_handle: object) -> P1AEPurePermitV1:
    _check_fields(preimage, P1_AE_PERMIT_PREIMAGE_FIELDS, name="P1-AE permit preimage")
    return P1AEPurePermitV1(owner_session_ref=owner_session_ref, preimage=preimage,
                            secret=secret, private_handle=private_handle)


__all__ += [
    "ARTIFACT_REF_IDENTITY_FIELDS", "CAPABILITY_CENSUS_ENTRY_FIELDS", "CONTRACT_ENTRY_FIELDS",
    "CONTRACT_REGISTRY_FIELDS", "DECIMAL_GRAMMAR_022", "DETERMINISTIC_GUARD_FIELDS",
    "DETERMINISTIC_SEMANTIC_RESULT_FIELDS", "DETERMINISTIC_TRACE_EVENT_FIELDS",
    "EVALUATION_BATCH_BINDING_FIELDS", "EVALUATION_INPUT_MANIFEST_FIELDS", "EVALUATION_OUTPUT_ROLE_ORDER", "EvaluationBindingV1",
    "EvaluationError", "EvaluationInputManifestV1", "EvaluatorSourceRegistryV1",
    "EVALUATOR_SOURCE_ROLES",
    "ContractRegistryV1", "ImportPermitV1", "P1CapabilityCensusV1", "P1PreImportGateV1",
    "PREIMPORT_GATE_FIELDS", "RESIDUE_KIND_COMPATIBILITY_MATRIX", "RESIDUE_PAIRING_FIELDS",
    "RESIDUE_SNAPSHOT_PREIMAGE_FIELDS", "RuleSetRegistryV1", "SEMANTIC_RESULT_EXCLUDED_FIELDS",
    "SEMANTIC_RESULT_FIELDS", "canonical_evaluation_json_bytes", "canonical_lineage_mapping",
    "canonical_pairing_hash", "canonical_sha256", "compatibility_matrix_bytes",
    "compatibility_matrix_hash", "compatibility_matrix_mapping", "issue_import_permit",
    "lineage_bytes", "lineage_hash", "normalize_relative_path", "parse_canonical_evaluation_json",
    "recompute_permit_digest", "recompute_permit_seal", "relative_path_key_utf8_hex",
    "sha256_bytes", "strict_base64_bytes", "strict_sorted_unique", "validate_decimal_string",
    "validate_evaluation_output_role_order", "validate_hash", "validate_relative_path_key", "validate_role_kind",
    "CPYTHON_RUNTIME_ID_FIELDS", "MARKER_OPCODE_RECORD_FIELDS", "MARKER_OPCODE_EVENT_FIELDS",
    "MARKER_OPCODE_WHITELIST_FIELDS", "MARKER_OPCODE_SEQUENCE_FIELDS", "MARKER_PURITY_FIELDS",
    "MARKER_ARGUMENT_KINDS", "IMPORT_PERMIT_PREIMAGE_FIELDS_V2", "WRITER_TRACE_PLAN_FIELDS",
    "EVIDENCE_CONTENT_FIELDS", "PRE_PERMIT_ATTESTATION_V15_FIELDS",
    "CAPABILITY_PROBE_RECORD_FIELDS", "CAPABILITY_PROBE_SNAPSHOT_FIELDS",
    "DETERMINISTIC_WRITER_OBSERVATION_FIELDS", "DETERMINISTIC_RESIDUE_ENTRY_FIELDS",
    "RESIDUE_ENTRY_ROLES", "RESIDUE_ENTRY_KINDS", "RESIDUE_READBACK_STATUSES",
    "BOOTSTRAP_MODULE_ENTRY_FIELDS", "CAPABILITY_PROBE_COVERAGE_FIELDS",
    "OWNER_PROBE_BINDING_FIELDS",
    "WRITER_FAILURE_EVIDENCE_FIELDS", "WRITER_FAILURE_EVIDENCE_PREIMAGE_FIELDS",
    "RESOLUTION_COLLECTION_KINDS", "RESOLUTION_COLLECTION_VALUE_TYPES",
    "RESOLUTION_COLLECTION_SNAPSHOT_FIELDS", "RESOLUTION_COLLECTION_ENTRY_FIELDS",
    "RESOLUTION_NESTED_SNAPSHOT_FIELDS", "RESOLUTION_LIVE_SNAPSHOT_FIELDS", "RESOLUTION_PROJECTION_FIELDS", "RESOLUTION_SUPPORT_FIELDS",
    "OWNER_INPUT_MANIFEST_FIELDS", "INPUT_BINDING_PREIMAGE_FIELDS",
    "P0_ARTIFACTREF_PREIMAGE_FIELDS", "P0_ARTIFACT_LINEAGE_FIELDS",
    "P0_TO_P1_INPUT_LINEAGE_ADAPTER_FIELDS", "p0_artifact_ref_preimage",
    "p0_artifact_lineage", "p0_lineage_to_ref_preimage", "verify_p0_lineage_integrity",
    "p0_to_p1_input_lineage_adapter", "input_binding_hash", "freeze_evidence",
    "canonical_writer_invocation", "canonical_writer_observation", "canonical_writer_failure_evidence", "canonical_residue_snapshot", "canonical_residue_entries",
    "issue_import_permit_v2", "recompute_permit_digest_v2", "recompute_permit_seal_v2",
]

__all__ += [
    "P1_AE_SCHEMA_VERSION", "P1_AE_PURE_LOADER_TRANSACTION_SCHEMA_VERSION",
    "P1_AE_PURE_IMPORT_PERMIT_SCHEMA_VERSION", "P1_AE_OWNER_ADMISSION_SCHEMA_VERSION",
    "P1_AE_PHASE_VALUES", "P1_AE_PERMIT_STATE_VALUES", "P1_AE_STATUS_VALUES",
    "P1_AE_OUTCOME_VALUES", "P1_AE_PURE_LOADER_PLAN_FIELDS",
    "P1_AE_PURE_LOADER_PLAN_PREIMAGE_FIELDS", "P1_AE_PURE_LOADER_PLAN_BINDING_FIELDS",
    "P1_AE_PURE_LOADER_PLAN_TRANSITION_FIELDS", "P1_AE_PURE_LOADER_PLAN_TRANSITION_TUPLE",
    "P1_AE_PURE_LOADER_PLAN_TRANSITION_REGISTRY_ORDER",
    "P1_AE_PURE_LOADER_PLAN_TRANSITION_REGISTRY_FIELDS",
    "P1_AE_PURE_LOADER_PLAN_TRANSITION_REGISTRY_PREIMAGE_FIELDS",
    "P1_AE_PURE_LOADER_PLAN_TRANSITION_REGISTRY_SCHEMA_VERSION",
    "P1_AE_PURE_LOADER_PLAN_TRANSITION_REGISTRY_STATUS_VALUES",
    "P1_AE_PURE_LOADER_PLAN_TRANSITION_REGISTRY",
    "P1_AE_PURE_LOADER_PLAN_TRANSITION_REGISTRY_RECORD",
    "P1_AE_PURE_LOADER_PLAN_STATUS_VALUES",
    "P1_AE_PURE_LOADER_PLAN_HOST_NONMUTATION_VALUES",
    "P1_AE_PURE_LOADER_PLAN_HOST_CANDIDATE_SET_READ_VALUES",
    "P1_AE_PURE_LOADER_PLAN_PERMIT_CONSUMED_VALUES",
    "P1_AE_PURE_LOADER_PLAN_TRANSITION_STATUS_VALUES",
    "P1_AE_PURE_LOADER_PLAN_STATUS_TRANSITION_PREDICATE",
    "P1_AE_PURE_IMPORT_EXPECTED_OBSERVATION_FIELDS",
    "P1_AE_PURE_IMPORT_EXPECTED_OBSERVATION_PREIMAGE_FIELDS",
    "P1_AE_CPYTHON_INTERNAL_EVENT_FIELDS", "P1_AE_CPYTHON_INTERNAL_EDGE_FIELDS",
    "P1_AE_CPYTHON_INTERNAL_EVENT_PREIMAGE_FIELDS", "P1_AE_CPYTHON_INTERNAL_EDGE_PREIMAGE_FIELDS",
    "P1_AE_CPYTHON_INTERNAL_PERMIT_TUPLES", "P1_AE_FORBIDDEN_IMPORT_EVENT_FIELDS",
    "P1_AE_IMPORT_EVENT_FIELDS", "P1_AE_IMPORT_EVENT_KIND_VALUES", "P1_AE_CHANNEL_VALUES",
    "P1_AE_FORBIDDEN_IMPORT_TUPLE_FIELDS", "P1_AE_FORBIDDEN_IMPORT_PROJECTION_FIELDS",
    "P1_AE_FORBIDDEN_IMPORT_PROJECTION_PREIMAGE_FIELDS", "P1_AE_RESOLUTION_SNAPSHOT_KINDS",
    "P1_AE_RESOLUTION_ENTRY_FIELDS", "P1_AE_RESOLUTION_SNAPSHOT_FIELDS",
    "P1_AE_RESOLUTION_SNAPSHOT_PREIMAGE_FIELDS", "P1_AE_LOADER_TRANSACTION_FIELDS",
    "P1_AE_SYS_PATH_SNAPSHOT_FIELDS", "P1_AE_CWD_SNAPSHOT_FIELDS",
    "P1_AE_META_PATH_SNAPSHOT_FIELDS", "P1_AE_PATH_HOOKS_SNAPSHOT_FIELDS",
    "P1_AE_PRELOADED_MODULES_SNAPSHOT_FIELDS", "P1_AE_PRELOADED_SOURCE_PATHS_SNAPSHOT_FIELDS",
    "P1_AE_AUTHORITY_RAW_FIELDS", "P1_AE_AUTHORITY_RECORD_FIELDS",
    "P1_AE_AUTHORITY_HANDLE_BINDING_FIELDS", "P1_AE_AUTHORITY_COMPOSITE_FIELDS",
    "P1_AE_ALLOWED_BOOTSTRAP_EDGE_ROLES",
    "P1_AE_LOADER_TRANSACTION_PREIMAGE_FIELDS", "P1_AE_PACKAGE_FIELDS",
    "P1_AE_GATE_PREIMAGE_FIELDS", "P1_AE_PERMIT_PREIMAGE_FIELDS",
    "P1_AE_OWNER_ADMISSION_PREIMAGE_FIELDS", "P1_AE_FROZEN_EVIDENCE_CONTENT_FIELDS",
    "P1_AE_QUALITY_BUNDLE_FIELDS", "P1_AE_QUALITY_STRATUM_FIELDS",
    "P1_AE_QUALITY_CLUSTER_FIELDS", "P1_AE_QUALITY_CASE_FIELDS",
    "P1_AE_QUALITY_ANNOTATION_FIELDS", "P1_AE_QUALITY_DIMENSION_FIELDS",
    "P1_AE_QUALITY_ADMISSION_FIELDS",
    "p1ae_transition_registry_hash", "p1ae_transition_tuple", "validate_p1ae_transition",
    "p1ae_loader_plan_bytes", "p1ae_loader_plan_hash", "p1ae_loader_plan_binding",
    "p1ae_expected_observation_hash", "p1ae_forbidden_projection_hash",
    "validate_p1ae_forbidden_event", "validate_p1ae_import_event", "p1ae_authority_hashes",
    "p1ae_resolution_snapshot_hash",
    "P1AERegistryHandleV1",
    "issue_p1ae_registry_handle", "consume_p1ae_registry_handle",
    "P1AEPurePermitV1", "issue_p1ae_pure_permit",
]

# C5-P1-AE code-correction gated additions.  These are owner-side capability
# records; callers may present only an opaque handle and cannot assert the
# HUMAN_ONLY/BLIND/INDEPENDENT facts themselves.
P1_AE_OWNER_REGISTRY_RECORD_FIELDS = (
    "registry_schema_version", "record_id", "annotation_id", "rater_id", "owner_id",
    "owner_session", "human_only", "blindness_status", "independence_status",
    "source_ref", "source_length", "source_sha256", "source_readback_sha256", "status",
)
P1_AE_OWNER_REGISTRY_SNAPSHOT_FIELDS = (
    "snapshot_schema_version", "owner_id", "owner_session", "generation", "request_nonce",
    "records", "record_hash", "source_readback_sha256", "owner_secret_seal", "status",
)
P1_AE_OWNER_REGISTRY_SCHEMA_VERSION = "P1_AE_OWNER_REGISTRY_V1"
P1_AE_OWNER_REGISTRY_SNAPSHOT_SCHEMA_VERSION = "P1_AE_OWNER_REGISTRY_SNAPSHOT_V1"

class P1AEOwnerRegistryV1:
    __slots__ = ("_secret", "_authority_bytes", "_source_readback", "_handle", "_records", "snapshot")
    def __init__(self, *, owner_id: str, owner_session: str, request_nonce: str, authority_bytes: bytes, source_readback: bytes, records: Sequence[Mapping[str, Any]], generation: int = 1):
        if not isinstance(authority_bytes, bytes) or not isinstance(source_readback, bytes) or authority_bytes != source_readback:
            raise _error("DENIED_AUTHORITY", "owner authority source readback mismatch")
        canonical_records = []
        for item in records:
            _check_fields(item, P1_AE_OWNER_REGISTRY_RECORD_FIELDS, name="owner registry record")
            if item["registry_schema_version"] != P1_AE_OWNER_REGISTRY_SCHEMA_VERSION or item["owner_id"] != owner_id or item["owner_session"] != owner_session or item["status"] != "READY":
                raise _error("DENIED_AUTHORITY", "owner registry record is not owner-bound")
            if item["human_only"] is not True or item["blindness_status"] != "BLIND" or item["independence_status"] != "INDEPENDENT":
                raise _error("DENIED_AUTHORITY", "human/blind/independent facts are not owner-issued")
            if item["source_readback_sha256"] != sha256_bytes(source_readback) or item["source_sha256"] != sha256_bytes(authority_bytes) or item["source_length"] != len(authority_bytes):
                raise _error("DENIED_AUTHORITY", "owner registry source binding mismatch")
            canonical_records.append(dict(item))
        canonical_records.sort(key=lambda item: item["record_id"].encode("utf-8"))
        if len({item["record_id"] for item in canonical_records}) != len(canonical_records):
            raise _error("DENIED_AUTHORITY", "owner registry record collision")
        secret = object(); self._secret = secret; self._authority_bytes = authority_bytes; self._source_readback = source_readback; self._records = {item["record_id"]: item for item in canonical_records}
        record_hash = canonical_sha256({"records": canonical_records}, fields=("records",)); seal = hmac.new(str(id(secret)).encode(), f"{owner_id}|{owner_session}|{generation}|{request_nonce}|{record_hash}|{sha256_bytes(source_readback)}".encode(), hashlib.sha256).hexdigest()
        self.snapshot = {"snapshot_schema_version": P1_AE_OWNER_REGISTRY_SNAPSHOT_SCHEMA_VERSION, "owner_id": owner_id, "owner_session": owner_session, "generation": generation, "request_nonce": request_nonce, "records": canonical_records, "record_hash": record_hash, "source_readback_sha256": sha256_bytes(source_readback), "owner_secret_seal": seal, "status": "READY"}
        self._handle = issue_p1ae_registry_handle(owner_session=owner_session, request_nonce=request_nonce, authority_id=owner_id, snapshot_hash=canonical_sha256(self.snapshot, fields=P1_AE_OWNER_REGISTRY_SNAPSHOT_FIELDS), secret=secret, source_readback_sha256=sha256_bytes(source_readback), generation=generation)
    @property
    def handle(self) -> P1AERegistryHandleV1:
        return self._handle
    @property
    def snapshot_hash(self) -> str:
        return canonical_sha256(self.snapshot, fields=P1_AE_OWNER_REGISTRY_SNAPSHOT_FIELDS)
    def lookup(self, *, handle: P1AERegistryHandleV1, owner_session: str, request_nonce: str, secret: object, record_id: str) -> dict[str, Any]:
        if handle is not self._handle or secret is not self._secret or handle.snapshot_hash != self.snapshot_hash:
            raise _error("DENIED_AUTHORITY", "owner registry handle identity or snapshot binding failed")
        consume_p1ae_registry_handle(handle, owner_session=owner_session, request_nonce=request_nonce, secret=secret, snapshot_hash=self.snapshot_hash)
        record = self._records.get(record_id)
        if record is None:
            raise _error("DENIED_AUTHORITY", "owner registry lookup is not uniquely bound")
        return dict(record)

P1_AE_PURE_LOADER_PLAN_RESOLUTION_HASH_FIELDS = (
    "sys_path_snapshot_hash", "cwd_snapshot_hash", "meta_path_snapshot_hash", "path_hooks_snapshot_hash",
    "preloaded_modules_snapshot_hash", "preloaded_source_paths_snapshot_hash",
)
P1_AE_PURE_LOADER_PLAN_FIELDS = P1_AE_PURE_LOADER_PLAN_FIELDS + P1_AE_PURE_LOADER_PLAN_RESOLUTION_HASH_FIELDS
P1_AE_PURE_LOADER_PLAN_PREIMAGE_FIELDS = P1_AE_PURE_LOADER_PLAN_FIELDS
P1_AE_PURE_IMPORT_EXPECTED_OBSERVATION_FIELDS = P1_AE_PURE_IMPORT_EXPECTED_OBSERVATION_FIELDS + ("expected_loaded_module_projection_hash", "resolution_projection_hash")
P1_AE_PACKAGE_FIELDS = P1_AE_PACKAGE_FIELDS + ("resolution_projection_hash", "expected_loaded_module_projection_hash")
P1_AE_GATE_PREIMAGE_FIELDS = P1_AE_PACKAGE_FIELDS
P1_AE_PERMIT_PREIMAGE_FIELDS = P1_AE_PERMIT_PREIMAGE_FIELDS + ("resolution_projection_hash", "expected_loaded_module_projection_hash", "authority_binding_hash")
P1_AE_LOADER_TRANSACTION_FIELDS = P1_AE_LOADER_TRANSACTION_FIELDS + ("resolution_projection_hash", "authority_binding_hash")
P1_AE_LOADER_TRANSACTION_PREIMAGE_FIELDS = P1_AE_LOADER_TRANSACTION_FIELDS
P1_AE_OWNER_ADMISSION_PREIMAGE_FIELDS = P1_AE_OWNER_ADMISSION_PREIMAGE_FIELDS + ("resolution_projection_hash", "authority_binding_hash")
P1_AE_OWNER_ADMISSION_PREIMAGE_FIELDS = P1_AE_OWNER_ADMISSION_PREIMAGE_FIELDS + (
    "owner_registry_snapshot_hash", "owner_annotation_projection_hash",
)
P1_AE_QUALITY_ADMISSION_FIELDS = P1_AE_OWNER_ADMISSION_PREIMAGE_FIELDS
__all__ += ["P1_AE_OWNER_REGISTRY_RECORD_FIELDS", "P1_AE_OWNER_REGISTRY_SNAPSHOT_FIELDS", "P1AEOwnerRegistryV1", "P1_AE_PURE_LOADER_PLAN_RESOLUTION_HASH_FIELDS"]

# Final owner-registry definition for the gated implementation.  A registry
# owns the only secret and the only generation counter; callers receive a
# single-use handle, never the registry record authority itself.
class P1AEOwnerRegistryV1:
    __slots__ = (
        "_secret", "_authority_bytes", "_source_readback", "_records", "_lock",
        "_owner_id", "_owner_session", "_request_nonce", "_generation", "snapshot",
    )

    def __init__(self, *, owner_id: str, owner_session: str, request_nonce: str,
                 authority_bytes: bytes, source_readback: bytes,
                 records: Sequence[Mapping[str, Any]], generation: int = 1):
        if not isinstance(authority_bytes, bytes) or not isinstance(source_readback, bytes):
            raise _error("DENIED_AUTHORITY", "owner registry authority must be bytes")
        if authority_bytes != source_readback:
            raise _error("DENIED_AUTHORITY", "owner registry authority readback mismatch")
        canonical_records = []
        for item in records:
            _check_fields(item, P1_AE_OWNER_REGISTRY_RECORD_FIELDS, name="owner registry record")
            if item["registry_schema_version"] != P1_AE_OWNER_REGISTRY_SCHEMA_VERSION:
                raise _error("DENIED_AUTHORITY", "owner registry schema mismatch")
            if item["owner_id"] != owner_id or item["owner_session"] != owner_session or item["status"] != "READY":
                raise _error("DENIED_AUTHORITY", "owner registry record is not owner-bound")
            if item["human_only"] is not True or item["blindness_status"] != "BLIND" or item["independence_status"] != "INDEPENDENT":
                raise _error("DENIED_AUTHORITY", "annotation authority facts are not owner-issued")
            authority_hash = sha256_bytes(authority_bytes)
            if item["source_length"] != len(authority_bytes) or item["source_sha256"] != authority_hash or item["source_readback_sha256"] != authority_hash:
                raise _error("DENIED_AUTHORITY", "owner registry source binding mismatch")
            canonical_records.append(dict(item))
        canonical_records.sort(key=lambda item: item["record_id"].encode("utf-8"))
        if len({item["record_id"] for item in canonical_records}) != len(canonical_records):
            raise _error("DENIED_AUTHORITY", "owner registry record collision")
        self._secret = object()
        self._authority_bytes = authority_bytes
        self._source_readback = source_readback
        self._records = {item["record_id"]: item for item in canonical_records}
        self._lock = threading.RLock()
        self._owner_id = owner_id
        self._owner_session = owner_session
        self._request_nonce = request_nonce
        self._generation = generation
        record_hash = canonical_sha256({"records": canonical_records}, fields=("records",))
        seal = hmac.new(
            str(id(self._secret)).encode("ascii"),
            f"{owner_id}|{owner_session}|{generation}|{request_nonce}|{record_hash}|{sha256_bytes(source_readback)}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        self.snapshot = {
            "snapshot_schema_version": P1_AE_OWNER_REGISTRY_SNAPSHOT_SCHEMA_VERSION,
            "owner_id": owner_id, "owner_session": owner_session, "generation": generation,
            "request_nonce": request_nonce, "records": canonical_records,
            "record_hash": record_hash, "source_readback_sha256": sha256_bytes(source_readback),
            "owner_secret_seal": seal, "status": "READY",
        }

    @property
    def snapshot_hash(self) -> str:
        return canonical_sha256(self.snapshot, fields=P1_AE_OWNER_REGISTRY_SNAPSHOT_FIELDS)

    def issue_record_handle(self, record_id: str) -> P1AERegistryHandleV1:
        with self._lock:
            if record_id not in self._records:
                raise _error("DENIED_AUTHORITY", "owner registry record is not registered")
            self._generation += 1
            return issue_p1ae_registry_handle(
                owner_session=self._owner_session,
                request_nonce=f"{self._request_nonce}:{self._generation}:{record_id}",
                authority_id=self._owner_id,
                snapshot_hash=self.snapshot_hash,
                secret=self._secret,
                source_readback_sha256=sha256_bytes(self._source_readback),
                generation=self._generation,
            )

    def lookup(self, *, handle: P1AERegistryHandleV1, record_id: str) -> dict[str, Any]:
        with self._lock:
            if not isinstance(handle, P1AERegistryHandleV1) or handle._secret is not self._secret:
                raise _error("DENIED_AUTHORITY", "owner registry handle identity is not private")
            if handle.snapshot_hash != self.snapshot_hash or handle.authority_id != self._owner_id:
                raise _error("DENIED_AUTHORITY", "owner registry snapshot binding failed")
            consume_p1ae_registry_handle(
                handle, owner_session=self._owner_session, request_nonce=handle.request_nonce,
                secret=self._secret, snapshot_hash=self.snapshot_hash,
            )
            record = self._records.get(record_id)
            if record is None:
                raise _error("DENIED_AUTHORITY", "owner registry lookup is not uniquely bound")
            return dict(record)

    def owner_lookup(self, record_id: str) -> tuple[dict[str, Any], P1AERegistryHandleV1]:
        handle = self.issue_record_handle(record_id)
        return self.lookup(handle=handle, record_id=record_id), handle

P1_AE_OWNER_REGISTRY_HASH_FIELDS = (
    "owner_registry_snapshot_hash", "owner_annotation_projection_hash",
)

# P1-AE correction-1: the following definitions are deliberately the final
# names in this module.  They close the owner-only transaction boundary while
# leaving the accepted P1-A contracts above untouched.
P1_AE_LOADED_MODULE_BINDING_FIELDS = (
    "module_name", "module_identity", "spec_identity", "module_file",
    "spec_origin", "source_ref", "source_length", "source_sha256",
    "code_sha256", "postload_source_length", "postload_source_sha256",
    "readback_status",
)
P1_AE_LOADED_MODULE_BINDINGS_FIELDS = ("bindings", "binding_hash", "status")
P1_AE_IMPORT_TRACE_FIELDS = ("events", "trace_hash", "trace_complete", "status")
P1_AE_IMPORT_TRACE_PREIMAGE_FIELDS = P1_AE_IMPORT_TRACE_FIELDS
P1_AE_PURE_PERMIT_REGISTRY_FIELDS = (
    "registry_schema_version", "owner_session_ref", "generation", "permit_digest", "state",
)
P1_AE_PURE_PERMIT_REGISTRY_SCHEMA_VERSION = "P1_AE_PURE_PERMIT_REGISTRY_V1"
P1_AE_OWNER_LOCK_FIELDS = ("lock_schema_version", "owner_session_ref", "lock_identity", "held")
P1_AE_OWNER_LOCK_SCHEMA_VERSION = "P1_AE_OWNER_LOCK_V1"

P1_AE_RESOLUTION_SYS_PATH_SCHEMA_VERSION = "P1_AE_SYS_PATH_SNAPSHOT_V1"
P1_AE_RESOLUTION_CWD_SCHEMA_VERSION = "P1_AE_CWD_SNAPSHOT_V1"
P1_AE_RESOLUTION_META_PATH_SCHEMA_VERSION = "P1_AE_META_PATH_SNAPSHOT_V1"
P1_AE_RESOLUTION_PATH_HOOKS_SCHEMA_VERSION = "P1_AE_PATH_HOOKS_SNAPSHOT_V1"
P1_AE_RESOLUTION_PRELOADED_MODULES_SCHEMA_VERSION = "P1_AE_PRELOADED_MODULES_SNAPSHOT_V1"
P1_AE_RESOLUTION_PRELOADED_SOURCE_PATHS_SCHEMA_VERSION = "P1_AE_PRELOADED_SOURCE_PATHS_SNAPSHOT_V1"
P1_AE_RESOLUTION_SPECIALIZED_ENTRY_FIELDS = (
    "entry_sequence", "value", "value_kind", "normalized_value", "source_ref",
    "source_length", "source_sha256", "collision_key", "status",
)
P1_AE_RESOLUTION_SPECIALIZED_FIELDS = (
    "snapshot_schema_version", "snapshot_kind", "owner_id", "authority_ref",
    "entry_count", "complete", "entries", "nested_preimage_hash", "status",
)
P1_AE_CWD_SPECIALIZED_FIELDS = (
    "snapshot_schema_version", "snapshot_kind", "owner_id", "authority_ref",
    "entry_count", "complete", "path", "path_kind", "source_ref", "source_length",
    "source_sha256", "status",
)
P1_AE_RESOLUTION_SPECIALIZED_FIELDS_BY_KIND = {
    "SYS_PATH": P1_AE_RESOLUTION_SPECIALIZED_FIELDS,
    "META_PATH": P1_AE_RESOLUTION_SPECIALIZED_FIELDS,
    "PATH_HOOKS": P1_AE_RESOLUTION_SPECIALIZED_FIELDS,
    "PRELOADED_MODULES": P1_AE_RESOLUTION_SPECIALIZED_FIELDS,
    "PRELOADED_SOURCE_PATHS": P1_AE_RESOLUTION_SPECIALIZED_FIELDS,
    "CWD": P1_AE_CWD_SPECIALIZED_FIELDS,
}
P1_AE_RESOLUTION_SPECIALIZED_SCHEMA_BY_KIND = {
    "SYS_PATH": P1_AE_RESOLUTION_SYS_PATH_SCHEMA_VERSION,
    "CWD": P1_AE_RESOLUTION_CWD_SCHEMA_VERSION,
    "META_PATH": P1_AE_RESOLUTION_META_PATH_SCHEMA_VERSION,
    "PATH_HOOKS": P1_AE_RESOLUTION_PATH_HOOKS_SCHEMA_VERSION,
    "PRELOADED_MODULES": P1_AE_RESOLUTION_PRELOADED_MODULES_SCHEMA_VERSION,
    "PRELOADED_SOURCE_PATHS": P1_AE_RESOLUTION_PRELOADED_SOURCE_PATHS_SCHEMA_VERSION,
}
P1_AE_SYS_PATH_SNAPSHOT_FIELDS = P1_AE_RESOLUTION_SPECIALIZED_FIELDS
P1_AE_SYS_PATH_SNAPSHOT_PREIMAGE_FIELDS = P1_AE_SYS_PATH_SNAPSHOT_FIELDS
P1_AE_CWD_SNAPSHOT_FIELDS = P1_AE_CWD_SPECIALIZED_FIELDS
P1_AE_CWD_SNAPSHOT_PREIMAGE_FIELDS = P1_AE_CWD_SNAPSHOT_FIELDS
P1_AE_META_PATH_SNAPSHOT_FIELDS = P1_AE_RESOLUTION_SPECIALIZED_FIELDS
P1_AE_META_PATH_SNAPSHOT_PREIMAGE_FIELDS = P1_AE_META_PATH_SNAPSHOT_FIELDS
P1_AE_PATH_HOOKS_SNAPSHOT_FIELDS = P1_AE_RESOLUTION_SPECIALIZED_FIELDS
P1_AE_PATH_HOOKS_SNAPSHOT_PREIMAGE_FIELDS = P1_AE_PATH_HOOKS_SNAPSHOT_FIELDS
P1_AE_PRELOADED_MODULES_SNAPSHOT_FIELDS = P1_AE_RESOLUTION_SPECIALIZED_FIELDS
P1_AE_PRELOADED_MODULES_SNAPSHOT_PREIMAGE_FIELDS = P1_AE_PRELOADED_MODULES_SNAPSHOT_FIELDS
P1_AE_PRELOADED_SOURCE_PATHS_SNAPSHOT_FIELDS = P1_AE_RESOLUTION_SPECIALIZED_FIELDS
P1_AE_PRELOADED_SOURCE_PATHS_SNAPSHOT_PREIMAGE_FIELDS = P1_AE_PRELOADED_SOURCE_PATHS_SNAPSHOT_FIELDS

P1_AE_AUTHORITY_RECORD_FIELDS = (
    "authority_schema_version", "authority_id", "owner_id", "authority_kind", "status",
    "source_ref", "source_length", "source_sha256", "source_readback_length",
    "source_readback_sha256", "owner_secret_seal",
)
P1_AE_AUTHORITY_HANDLE_BINDING_FIELDS = (
    "authority_id", "owner_session", "handle_generation", "request_nonce", "snapshot_hash",
    "object_identity", "private_identity", "source_readback_sha256", "owner_secret_seal",
)
P1_AE_AUTHORITY_COMPOSITE_FIELDS = (
    "raw_authority_bytes_hash", "authority_record_hash", "handle_binding_hash",
    "snapshot_hash", "source_readback_sha256", "status",
)

def _p1ae_resolution_fields(kind: str) -> tuple[str, ...]:
    try:
        return P1_AE_RESOLUTION_SPECIALIZED_FIELDS_BY_KIND[kind]
    except KeyError as exc:
        raise _error("DENIED_PROVENANCE", "resolution snapshot kind is not specialized") from exc

def p1ae_resolution_snapshot_hash(value: Mapping[str, Any]) -> str:
    kind = value.get("snapshot_kind")
    fields = _p1ae_resolution_fields(kind)
    _check_fields(value, fields, name=f"P1-AE {kind} resolution snapshot")
    expected_schema = P1_AE_RESOLUTION_SPECIALIZED_SCHEMA_BY_KIND[kind]
    if value["snapshot_schema_version"] != expected_schema or value["snapshot_kind"] != kind:
        raise _error("DENIED_PROVENANCE", "resolution schema/kind binding mismatch")
    if not isinstance(value["entry_count"], int) or isinstance(value["entry_count"], bool) or value["entry_count"] < 0:
        raise _error("DENIED_PROVENANCE", "resolution entry count is invalid")
    if kind == "CWD":
        ready = value["complete"] is True and value["entry_count"] == 1 and value["status"] == "READY"
        deny = value["complete"] is False and value["entry_count"] == 0 and value["status"] == "DENY"
        if not (ready or deny):
            raise _error("DENIED_PROVENANCE", "CWD singleton READY/DENY semantics failed")
        if deny and any(value[field] is not None for field in ("path", "path_kind", "source_ref", "source_length", "source_sha256")):
            raise _error("DENIED_PROVENANCE", "CWD DENY fields must be JSON null")
        if ready and (not isinstance(value["path"], str) or not value["path"] or value["path_kind"] != "ABSOLUTE"):
            raise _error("DENIED_PROVENANCE", "CWD READY singleton fields are not bound")
        return canonical_sha256(value, fields=fields)
    entries = value["entries"]
    if not isinstance(entries, list) or len(entries) != value["entry_count"]:
        raise _error("DENIED_PROVENANCE", "resolution entry array/count mismatch")
    sequences = []
    collisions = []
    for entry in entries:
        _check_fields(entry, P1_AE_RESOLUTION_SPECIALIZED_ENTRY_FIELDS, name=f"P1-AE {kind} resolution entry")
        sequences.append(entry["entry_sequence"])
        collisions.append(entry["collision_key"])
        validate_hash(entry["source_sha256"], field="resolution.source_sha256")
    if sequences != list(range(len(entries))) or len(set(collisions)) != len(collisions):
        raise _error("DENIED_PROVENANCE", "resolution sequence/collision ordering is not canonical")
    if value["complete"] is not True and value["status"] != "DENY":
        raise _error("DENIED_PROVENANCE", "incomplete resolution snapshot must deny")
    nested = canonical_evaluation_json_bytes({"entries": entries}, fields=("entries",))
    if value["nested_preimage_hash"] != sha256_bytes(nested):
        raise _error("DENIED_PROVENANCE", "resolution nested preimage is not byte-bound")
    return canonical_sha256(value, fields=fields)

def p1ae_authority_hashes(*, authority_bytes: bytes, authority_record: Mapping[str, Any], handle_binding: Mapping[str, Any], source_readback: bytes | None = None) -> dict[str, str]:
    if not isinstance(authority_bytes, bytes) or not isinstance(source_readback, (bytes, type(None))):
        raise _error("DENIED_AUTHORITY", "authority bytes/readback must be owner bytes")
    _check_fields(authority_record, P1_AE_AUTHORITY_RECORD_FIELDS, name="authority record")
    _check_fields(handle_binding, P1_AE_AUTHORITY_HANDLE_BINDING_FIELDS, name="authority handle binding")
    raw_hash = sha256_bytes(authority_bytes)
    readback = authority_bytes if source_readback is None else source_readback
    if authority_record["source_length"] != len(authority_bytes) or authority_record["source_sha256"] != raw_hash:
        raise _error("DENIED_AUTHORITY", "authority source binding mismatch")
    if authority_record["source_readback_length"] != len(readback) or authority_record["source_readback_sha256"] != sha256_bytes(readback):
        raise _error("DENIED_AUTHORITY", "authority source readback mismatch")
    record_hash = canonical_sha256(authority_record, fields=P1_AE_AUTHORITY_RECORD_FIELDS)
    handle_hash = canonical_sha256(handle_binding, fields=P1_AE_AUTHORITY_HANDLE_BINDING_FIELDS)
    composite = {
        "raw_authority_bytes_hash": raw_hash, "authority_record_hash": record_hash,
        "handle_binding_hash": handle_hash, "snapshot_hash": handle_binding["snapshot_hash"],
        "source_readback_sha256": sha256_bytes(readback), "status": "BOUND",
    }
    return {"raw_authority_bytes_hash": raw_hash, "authority_record_hash": record_hash,
            "handle_binding_hash": handle_hash,
            "composite_authority_binding_hash": canonical_sha256(composite, fields=P1_AE_AUTHORITY_COMPOSITE_FIELDS)}

def validate_p1ae_import_event(value: Mapping[str, Any]) -> dict[str, Any]:
    _check_fields(value, P1_AE_IMPORT_EVENT_FIELDS, name="P1-AE import event")
    kind, role, channel, state = value["event_kind"], value["load_role"], value["channel"], value["permit_state"]
    if value["phase"] != state or state not in P1_AE_PHASE_VALUES:
        raise _error("DENIED_CAPABILITY", "import phase and permit state are not byte-equal")
    predicates = {
        "BOOTSTRAP_IMPORT": (role == "P1A_STATIC_BOOTSTRAP", channel == "OWNER_STATIC_EDGE", state == "HOST_STATIC_BOUND", value["edge_sequence"] is not None),
        "CANDIDATE_ROOT_IMPORT": (role == "P1AE_DYNAMIC_CANDIDATE", channel == "IMPORTLIB_DYNAMIC", state == "CONSUMED", value["edge_sequence"] is None),
        "CANDIDATE_STATIC_EDGE": (role == "P1AE_STATIC_CANDIDATE_EDGE", channel == "OWNER_SOURCE_LOADER", state == "CONSUMED", value["edge_sequence"] is not None),
        "CPYTHON_INTERNAL": (role == "P1AE_INTERNAL_RUNTIME", channel == "BUILTIN", state in P1_AE_PHASE_VALUES, value["edge_sequence"] is not None),
        "DYNAMIC_IMPORT": (role == "FORBIDDEN", channel in P1_AE_CHANNEL_VALUES, value["edge_sequence"] is None, value["edge_role"] is None),
        "AMBIENT_IMPORT": (role == "FORBIDDEN", channel in P1_AE_CHANNEL_VALUES, value["edge_sequence"] is None, value["edge_role"] is None),
    }
    if kind not in predicates or not all(predicates[kind]):
        raise _error("DENIED_CAPABILITY", "import event taxonomy is not mutually exclusive")
    if kind in {"DYNAMIC_IMPORT", "AMBIENT_IMPORT"}:
        forbidden = {field: value[field] for field in P1_AE_FORBIDDEN_IMPORT_EVENT_FIELDS if field in value}
        return validate_p1ae_forbidden_event(forbidden)
    for field in ("caller_source_sha256", "target_source_sha256", "caller_code_sha256", "target_code_sha256"):
        validate_hash(value[field], field=field)
    if not isinstance(value["trace_sequence"], int) or value["trace_sequence"] < 0 or not isinstance(value["offset"], int) or value["offset"] < 0:
        raise _error("DENIED_CAPABILITY", "import trace sequence/offset is invalid")
    return {field: value[field] for field in P1_AE_IMPORT_EVENT_FIELDS}

P1_AE_LOADER_TRANSACTION_FIELDS = (
    "transaction_schema_version", "transaction_id", "owner_id", "authority_ref", "owner_session_ref",
    "loader_plan_hash", "loader_plan_length", "transition_registry_hash", "transition_fields",
    "permit_digest", "permit_cas_sequence", "dynamic_load_count", "dynamic_load_order",
    "loaded_module_bindings_hash", "import_trace_hash", "forbidden_projection_hash", "observed_projection_hash",
    "writer_invocation_hash", "post_write_trace_hash", "failure_evidence_hash", "residue_snapshot_hash",
    "residue_pairing_hash", "state", "status",
)
P1_AE_LOADER_TRANSACTION_PREIMAGE_FIELDS = P1_AE_LOADER_TRANSACTION_FIELDS
P1_AE_PACKAGE_FIELDS = (
    "package_schema_version", "owner_id", "authority_ref", "source_registry_hash", "source_module_binding_hash",
    "loader_plan_hash", "loader_plan_length", "transition_registry_hash", "transition_fields", "resolution_guard_hash",
    "resolution_live_hash", "expected_observation_hash", "loaded_module_bindings_hash", "forbidden_projection_hash", "status",
)
P1_AE_GATE_PREIMAGE_FIELDS = P1_AE_PACKAGE_FIELDS
P1_AE_PERMIT_PREIMAGE_FIELDS = (
    "permit_schema_version", "owner_id", "authority_ref", "owner_session_ref", "package_hash", "loader_plan_hash",
    "loader_plan_length", "transition_registry_hash", "transition_fields", "expected_observation_hash",
    "loaded_module_bindings_hash", "forbidden_projection_hash", "status",
)
P1_AE_OWNER_ADMISSION_PREIMAGE_FIELDS = (
    "admission_schema_version", "owner_id", "authority_ref", "owner_session_ref", "source_registry_hash", "package_hash",
    "gate_hash", "permit_digest", "loader_plan_hash", "loader_plan_length", "transition_registry_hash", "transition_fields",
    "transaction_hash", "loaded_module_bindings_hash", "writer_invocation_hash", "post_write_trace_hash",
    "failure_evidence_hash", "residue_snapshot_hash", "residue_pairing_hash", "semantic_hash",
    "raw_authority_bytes_hash", "authority_record_hash", "authority_handle_binding_hash",
    "composite_authority_binding_hash", "status",
)
P1_AE_QUALITY_ADMISSION_FIELDS = P1_AE_OWNER_ADMISSION_PREIMAGE_FIELDS
P1_AE_QUALITY_CASE_FIELDS = (
    "case_id", "book_cluster_ref", "chapter_id", "blind_case_id", "split", "input_text", "input_text_sha256", "pipeline_observation", "annotations",
)

class P1AERegistryHandleV1:
    __slots__ = ("_secret", "_private_identity", "_object_identity", "authority_id", "owner_session", "generation", "request_nonce", "snapshot_hash", "source_readback_sha256", "owner_secret_seal", "consumed", "replay_generation")
    def __init__(self, *, authority_id: str, owner_session: str, generation: int, request_nonce: str, snapshot_hash: str, secret: object, source_readback_sha256: str):
        object.__setattr__(self, "_secret", secret); object.__setattr__(self, "_private_identity", object()); object.__setattr__(self, "_object_identity", id(self))
        self.authority_id = authority_id; self.owner_session = owner_session; self.generation = generation; self.request_nonce = request_nonce; self.snapshot_hash = snapshot_hash; self.source_readback_sha256 = source_readback_sha256
        self.owner_secret_seal = hmac.new(str(id(secret)).encode(), f"{authority_id}|{owner_session}|{generation}|{request_nonce}|{snapshot_hash}|{source_readback_sha256}".encode(), hashlib.sha256).hexdigest()
        self.consumed = False; self.replay_generation = None
    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"_secret", "_private_identity", "_object_identity", "authority_id", "owner_session", "generation", "request_nonce", "snapshot_hash", "source_readback_sha256", "owner_secret_seal"} and hasattr(self, name):
            raise _error("DENIED_AUTHORITY", "registry handle identity/authority fields are immutable")
        object.__setattr__(self, name, value)
    def __copy__(self) -> Any:
        raise _error("DENIED_AUTHORITY", "registry handle copy is denied")
    def __deepcopy__(self, memo: dict[int, Any]) -> Any:
        raise _error("DENIED_AUTHORITY", "registry handle serialization/copy is denied")
    def __reduce__(self) -> Any:
        raise _error("DENIED_AUTHORITY", "registry handle serialization is denied")

def issue_p1ae_registry_handle(*, owner_session: str, request_nonce: str, authority_id: str, snapshot_hash: str, secret: object | None = None, source_readback_sha256: str = "0" * 64, generation: int = 1) -> P1AERegistryHandleV1:
    if secret is None: secret = object()
    validate_hash(snapshot_hash, field="snapshot_hash"); validate_hash(source_readback_sha256, field="source_readback_sha256")
    return P1AERegistryHandleV1(authority_id=authority_id, owner_session=owner_session, generation=generation, request_nonce=request_nonce, snapshot_hash=snapshot_hash, secret=secret, source_readback_sha256=source_readback_sha256)

def consume_p1ae_registry_handle(handle: P1AERegistryHandleV1, *, owner_session: str, request_nonce: str, secret: object, snapshot_hash: str) -> int:
    if not isinstance(handle, P1AERegistryHandleV1) or handle.owner_session != owner_session or handle.request_nonce != request_nonce or handle.snapshot_hash != snapshot_hash or handle._secret is not secret or handle.consumed:
        raise _error("DENIED_AUTHORITY", "registry handle replay/copy/serialization denied")
    handle.consumed = True; handle.replay_generation = handle.generation + 1
    return handle.replay_generation

class P1AEPurePermitRegistryV1:
    def __init__(self, owner_session_ref: str):
        self.owner_session_ref = owner_session_ref; self.generation = 0; self._lock = threading.RLock(); self._records: dict[str, str] = {}
    def issue(self, preimage: Mapping[str, Any], *, secret: object, private_handle: object) -> "P1AEPurePermitV1":
        with self._lock:
            self.generation += 1; permit = P1AEPurePermitV1(owner_session_ref=self.owner_session_ref, preimage=preimage, secret=secret, private_handle=private_handle, registry=self, generation=self.generation); self._records[permit.digest] = "ISSUED"; return permit
    def consume(self, permit: "P1AEPurePermitV1", *, secret: object, private_handle: object) -> str:
        with self._lock:
            if self._records.get(permit.digest) != "ISSUED" or permit._secret is not secret or permit._private_handle is not private_handle:
                raise _error("DENIED_CAPABILITY", "P1-AE permit CAS replay or copy denied")
            self._records[permit.digest] = "CONSUMED"; permit.state = "CONSUMED"; permit.cas_sequence = 1; return permit.digest

class P1AEPurePermitV1:
    __slots__ = ("_secret", "_private_handle", "registry", "generation", "owner_session_ref", "preimage", "digest", "state", "cas_sequence")
    def __init__(self, *, owner_session_ref: str, preimage: Mapping[str, Any], secret: object, private_handle: object, registry: P1AEPurePermitRegistryV1 | None = None, generation: int = 1):
        _check_fields(preimage, P1_AE_PERMIT_PREIMAGE_FIELDS, name="P1-AE permit preimage"); self._secret = secret; self._private_handle = private_handle; self.registry = registry; self.generation = generation; self.owner_session_ref = owner_session_ref; self.preimage = {field: preimage[field] for field in P1_AE_PERMIT_PREIMAGE_FIELDS}; self.digest = canonical_sha256(self.preimage, fields=P1_AE_PERMIT_PREIMAGE_FIELDS); self.state = "ISSUED"; self.cas_sequence = 0
    def consume(self, *, secret: object, private_handle: object) -> str:
        if self.registry is None: raise _error("DENIED_CAPABILITY", "permit has no independent registry")
        return self.registry.consume(self, secret=secret, private_handle=private_handle)

def issue_p1ae_pure_permit(*, owner_session_ref: str, preimage: Mapping[str, Any], secret: object, private_handle: object, registry: P1AEPurePermitRegistryV1 | None = None) -> P1AEPurePermitV1:
    return (registry or P1AEPurePermitRegistryV1(owner_session_ref)).issue(preimage, secret=secret, private_handle=private_handle)


def p1ae_loader_plan_bytes(value: Mapping[str, Any]) -> bytes:
    _check_fields(value, P1_AE_PURE_LOADER_PLAN_FIELDS, name="P1-AE loader plan")
    validate_p1ae_transition(value["status"], value["transition_status"])
    if value["status"] == "READY":
        if tuple(value[field] for field in P1_AE_PURE_LOADER_PLAN_TRANSITION_FIELDS) != P1_AE_PURE_LOADER_PLAN_TRANSITION_TUPLE:
            raise _error("DENIED_CAPABILITY", "loader plan transition tuple is not canonical")
        if value["transition_registry_hash"] != p1ae_transition_registry_hash("READY"):
            raise _error("DENIED_CAPABILITY", "loader plan transition registry hash mismatch")
    for field in (
        "pure_source_registry_snapshot_hash", "source_module_binding_hash", "pure_gate_snapshot_hash",
        "resolution_guard_snapshot_hash", "resolution_live_snapshot_hash", "transition_registry_hash",
        *P1_AE_PURE_LOADER_PLAN_RESOLUTION_HASH_FIELDS,
    ):
        validate_hash(value[field], field=field)
    for field in ("cpython_internal_expected_edge_count", "cpython_internal_expected_event_count", "forbidden_expected_count"):
        if not isinstance(value[field], int) or isinstance(value[field], bool) or value[field] < 0:
            raise _error("DENIED_CAPABILITY", f"{field} is invalid")
    if any(value[field] is not False for field in ("host_loader_invoked", "host_gate_mutated", "host_permit_mutated", "host_candidate_set_read")):
        raise _error("DENIED_CAPABILITY", "host non-mutation/read facts are not owner-derived false")
    if value["permit_consumed_before_import"] is not True:
        raise _error("DENIED_CAPABILITY", "permit consumed-before-import fact is not true")
    return canonical_evaluation_json_bytes(value, fields=P1_AE_PURE_LOADER_PLAN_PREIMAGE_FIELDS)

__all__ += [
    "P1_AE_LOADED_MODULE_BINDING_FIELDS", "P1_AE_LOADED_MODULE_BINDINGS_FIELDS", "P1_AE_IMPORT_TRACE_FIELDS",
    "P1_AE_PURE_PERMIT_REGISTRY_FIELDS", "P1_AE_PURE_PERMIT_REGISTRY_SCHEMA_VERSION", "P1_AE_OWNER_LOCK_FIELDS",
    "P1_AE_RESOLUTION_SPECIALIZED_ENTRY_FIELDS", "P1_AE_RESOLUTION_SPECIALIZED_FIELDS", "P1_AE_CWD_SPECIALIZED_FIELDS",
    "P1_AE_RESOLUTION_SPECIALIZED_FIELDS_BY_KIND", "P1_AE_RESOLUTION_SPECIALIZED_SCHEMA_BY_KIND",
    "P1_AE_RESOLUTION_SYS_PATH_SCHEMA_VERSION", "P1_AE_RESOLUTION_CWD_SCHEMA_VERSION", "P1_AE_RESOLUTION_META_PATH_SCHEMA_VERSION",
    "P1_AE_RESOLUTION_PATH_HOOKS_SCHEMA_VERSION", "P1_AE_RESOLUTION_PRELOADED_MODULES_SCHEMA_VERSION", "P1_AE_RESOLUTION_PRELOADED_SOURCE_PATHS_SCHEMA_VERSION",
    "P1_AE_AUTHORITY_RECORD_FIELDS", "P1_AE_AUTHORITY_HANDLE_BINDING_FIELDS", "P1_AE_AUTHORITY_COMPOSITE_FIELDS",
    "P1_AE_LOADER_TRANSACTION_FIELDS", "P1_AE_LOADER_TRANSACTION_PREIMAGE_FIELDS", "P1_AE_PACKAGE_FIELDS", "P1_AE_GATE_PREIMAGE_FIELDS",
    "P1_AE_PERMIT_PREIMAGE_FIELDS", "P1_AE_OWNER_ADMISSION_PREIMAGE_FIELDS", "P1_AE_QUALITY_ADMISSION_FIELDS",
    "P1AERegistryHandleV1", "P1AERegistryHandleV1", "P1AEPurePermitRegistryV1", "P1AEPurePermitV1",
    "issue_p1ae_registry_handle", "consume_p1ae_registry_handle", "issue_p1ae_pure_permit", "p1ae_resolution_snapshot_hash", "p1ae_authority_hashes",
    "P1_AE_SYS_PATH_SNAPSHOT_PREIMAGE_FIELDS", "P1_AE_CWD_SNAPSHOT_PREIMAGE_FIELDS", "P1_AE_META_PATH_SNAPSHOT_PREIMAGE_FIELDS",
    "P1_AE_PATH_HOOKS_SNAPSHOT_PREIMAGE_FIELDS", "P1_AE_PRELOADED_MODULES_SNAPSHOT_PREIMAGE_FIELDS", "P1_AE_PRELOADED_SOURCE_PATHS_SNAPSHOT_PREIMAGE_FIELDS",
]

# Runtime-final field order after the compatibility block above.
P1_AE_PACKAGE_FIELDS = P1_AE_PACKAGE_FIELDS + ("resolution_projection_hash", "expected_loaded_module_projection_hash")
P1_AE_GATE_PREIMAGE_FIELDS = P1_AE_PACKAGE_FIELDS
P1_AE_PERMIT_PREIMAGE_FIELDS = P1_AE_PERMIT_PREIMAGE_FIELDS + ("resolution_projection_hash", "expected_loaded_module_projection_hash", "authority_binding_hash")
P1_AE_LOADER_TRANSACTION_FIELDS = P1_AE_LOADER_TRANSACTION_FIELDS + ("resolution_projection_hash", "authority_binding_hash")
P1_AE_LOADER_TRANSACTION_PREIMAGE_FIELDS = P1_AE_LOADER_TRANSACTION_FIELDS
P1_AE_OWNER_ADMISSION_PREIMAGE_FIELDS = P1_AE_OWNER_ADMISSION_PREIMAGE_FIELDS + ("resolution_projection_hash", "authority_binding_hash", "owner_registry_snapshot_hash", "owner_annotation_projection_hash")
P1_AE_QUALITY_ADMISSION_FIELDS = P1_AE_OWNER_ADMISSION_PREIMAGE_FIELDS

# True EOF override: the compatibility block above is intentionally followed
# by the final authority and projection definitions.
P1_AE_OWNER_REGISTRY_RECORD_FIELDS = ("registry_schema_version", "record_id", "annotation_id", "case_id", "pass_kind", "rater_id", "owner_id", "owner_session", "human_only", "blindness_status", "independence_status", "source_ref", "source_length", "source_sha256", "source_readback_sha256", "status")
P1_AE_REGISTRY_HANDLE_FIELDS = ("record_id", "annotation_id", "case_id", "pass_kind", "authority_id", "owner_session", "request_nonce", "generation", "snapshot_hash", "source_readback_sha256", "owner_secret_seal")
class P1AERegistryHandleV1:
    __slots__ = ("_secret", "_private_identity", "_object_identity", "_cas_lock", "_immutable", "record_id", "annotation_id", "case_id", "pass_kind", "authority_id", "owner_session", "request_nonce", "generation", "snapshot_hash", "source_readback_sha256", "owner_secret_seal", "consumed", "replay_generation")
    def __init__(self, *, authority_id: str, owner_session: str, generation: int, request_nonce: str, snapshot_hash: str, secret: object, source_readback_sha256: str, record_id: str = "", annotation_id: str = "", case_id: str = "", pass_kind: str = ""):
        object.__setattr__(self, "_immutable", False); object.__setattr__(self, "_secret", secret); object.__setattr__(self, "_private_identity", object()); object.__setattr__(self, "_object_identity", object()); object.__setattr__(self, "_cas_lock", threading.RLock())
        for name, value in (("record_id", record_id), ("annotation_id", annotation_id), ("case_id", case_id), ("pass_kind", pass_kind), ("authority_id", authority_id), ("owner_session", owner_session), ("request_nonce", request_nonce), ("generation", generation), ("snapshot_hash", snapshot_hash), ("source_readback_sha256", source_readback_sha256)):
            object.__setattr__(self, name, value)
        seal_input = "|".join((record_id, annotation_id, case_id, pass_kind, authority_id, owner_session, request_nonce, str(generation), snapshot_hash, source_readback_sha256)); object.__setattr__(self, "owner_secret_seal", hmac.new(str(id(secret)).encode("ascii"), seal_input.encode("utf-8"), hashlib.sha256).hexdigest()); object.__setattr__(self, "consumed", False); object.__setattr__(self, "replay_generation", None); object.__setattr__(self, "_immutable", True)
    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_immutable", False) and name not in {"consumed", "replay_generation"}:
            raise _error("DENIED_AUTHORITY", "registry handle binding is immutable")
        object.__setattr__(self, name, value)
    def __copy__(self) -> Any: raise _error("DENIED_AUTHORITY", "registry handle copy is denied")
    def __deepcopy__(self, memo: dict[int, Any]) -> Any: raise _error("DENIED_AUTHORITY", "registry handle deepcopy is denied")
    def __reduce__(self) -> Any: raise _error("DENIED_AUTHORITY", "registry handle serialization is denied")
def issue_p1ae_registry_handle(*, owner_session: str, request_nonce: str, authority_id: str, snapshot_hash: str, secret: object | None = None, source_readback_sha256: str = "0" * 64, generation: int = 1, record_id: str = "", annotation_id: str = "", case_id: str = "", pass_kind: str = "") -> P1AERegistryHandleV1:
    secret = object() if secret is None else secret; validate_hash(snapshot_hash, field="snapshot_hash"); validate_hash(source_readback_sha256, field="source_readback_sha256"); return P1AERegistryHandleV1(authority_id=authority_id, owner_session=owner_session, generation=generation, request_nonce=request_nonce, snapshot_hash=snapshot_hash, secret=secret, source_readback_sha256=source_readback_sha256, record_id=record_id, annotation_id=annotation_id, case_id=case_id, pass_kind=pass_kind)
def consume_p1ae_registry_handle(handle: P1AERegistryHandleV1, *, owner_session: str, request_nonce: str, secret: object, snapshot_hash: str, record_id: str | None = None, annotation_id: str | None = None, case_id: str | None = None, pass_kind: str | None = None) -> int:
    if not isinstance(handle, P1AERegistryHandleV1): raise _error("DENIED_AUTHORITY", "registry handle type is invalid")
    with handle._cas_lock:
        if handle._secret is not secret or handle.owner_session != owner_session or handle.request_nonce != request_nonce or handle.snapshot_hash != snapshot_hash or handle.consumed: raise _error("DENIED_AUTHORITY", "registry handle replay/use denied")
        for field, value in (("record_id", record_id), ("annotation_id", annotation_id), ("case_id", case_id), ("pass_kind", pass_kind)):
            if value is not None and getattr(handle, field) != value: raise _error("DENIED_AUTHORITY", f"registry handle {field} mismatch")
        object.__setattr__(handle, "consumed", True); object.__setattr__(handle, "replay_generation", handle.generation + 1); return handle.replay_generation
class P1AEOwnerRegistryV1:
    __slots__ = ("_secret", "_authority_bytes", "_source_readback", "_records", "_lock", "_owner_id", "_owner_session", "_request_nonce", "_generation", "snapshot")
    def __init__(self, *, owner_id: str, owner_session: str, request_nonce: str, authority_bytes: bytes, source_readback: bytes, records: Sequence[Mapping[str, Any]], generation: int = 1):
        if not isinstance(authority_bytes, bytes) or authority_bytes != source_readback: raise _error("DENIED_AUTHORITY", "owner authority source readback mismatch")
        source_hash = sha256_bytes(authority_bytes); canonical_records = []
        for item in records:
            _check_fields(item, P1_AE_OWNER_REGISTRY_RECORD_FIELDS, name="owner registry record")
            if item["registry_schema_version"] != P1_AE_OWNER_REGISTRY_SCHEMA_VERSION or item["owner_id"] != owner_id or item["owner_session"] != owner_session or item["status"] != "READY" or item["human_only"] is not True or item["blindness_status"] != "BLIND" or item["independence_status"] != "INDEPENDENT": raise _error("DENIED_AUTHORITY", "annotation authority is not owner-issued")
            if item["source_length"] != len(authority_bytes) or item["source_sha256"] != source_hash or item["source_readback_sha256"] != source_hash: raise _error("DENIED_AUTHORITY", "owner registry source binding mismatch")
            canonical_records.append(dict(item))
        canonical_records.sort(key=lambda item: item["record_id"].encode("utf-8")); self._secret = object(); self._authority_bytes = authority_bytes; self._source_readback = source_readback; self._records = {item["record_id"]: item for item in canonical_records}; self._lock = threading.RLock(); self._owner_id = owner_id; self._owner_session = owner_session; self._request_nonce = request_nonce; self._generation = generation
        record_hash = canonical_sha256({"records": canonical_records}, fields=("records",)); seal = hmac.new(str(id(self._secret)).encode("ascii"), f"{owner_id}|{owner_session}|{generation}|{request_nonce}|{record_hash}|{source_hash}".encode("utf-8"), hashlib.sha256).hexdigest(); self.snapshot = {"snapshot_schema_version": P1_AE_OWNER_REGISTRY_SNAPSHOT_SCHEMA_VERSION, "owner_id": owner_id, "owner_session": owner_session, "generation": generation, "request_nonce": request_nonce, "records": canonical_records, "record_hash": record_hash, "source_readback_sha256": source_hash, "owner_secret_seal": seal, "status": "READY"}
    @property
    def snapshot_hash(self) -> str: return canonical_sha256(self.snapshot, fields=P1_AE_OWNER_REGISTRY_SNAPSHOT_FIELDS)
    def issue_record_handle(self, record_id: str, *, case_id: str, pass_kind: str, annotation_id: str) -> P1AERegistryHandleV1:
        with self._lock:
            record = self._records.get(record_id)
            if record is None or (record["annotation_id"], record["case_id"], record["pass_kind"]) != (annotation_id, case_id, pass_kind): raise _error("DENIED_AUTHORITY", "owner identity tuple mismatch")
            self._generation += 1; return issue_p1ae_registry_handle(owner_session=self._owner_session, request_nonce=f"{self._request_nonce}:{self._generation}:{record_id}", authority_id=self._owner_id, snapshot_hash=self.snapshot_hash, secret=self._secret, source_readback_sha256=sha256_bytes(self._source_readback), generation=self._generation, record_id=record_id, annotation_id=annotation_id, case_id=case_id, pass_kind=pass_kind)
    def lookup(self, *, handle: P1AERegistryHandleV1, record_id: str, case_id: str, pass_kind: str, annotation_id: str) -> dict[str, Any]:
        with self._lock:
            if handle._secret is not self._secret or handle.authority_id != self._owner_id: raise _error("DENIED_AUTHORITY", "owner handle private identity mismatch")
            consume_p1ae_registry_handle(handle, owner_session=self._owner_session, request_nonce=handle.request_nonce, secret=self._secret, snapshot_hash=self.snapshot_hash, record_id=record_id, annotation_id=annotation_id, case_id=case_id, pass_kind=pass_kind); record = self._records.get(record_id)
            if record is None: raise _error("DENIED_AUTHORITY", "owner lookup record is missing")
            return dict(record)
    def owner_lookup(self, record_id: str, *, case_id: str, pass_kind: str, annotation_id: str) -> tuple[dict[str, Any], P1AERegistryHandleV1]:
        handle = self.issue_record_handle(record_id, case_id=case_id, pass_kind=pass_kind, annotation_id=annotation_id); return self.lookup(handle=handle, record_id=record_id, case_id=case_id, pass_kind=pass_kind, annotation_id=annotation_id), handle
P1_AE_CPYTHON_INTERNAL_EXPECTED_EVENT_FIELDS = P1_AE_IMPORT_EVENT_FIELDS; P1_AE_CPYTHON_INTERNAL_EXPECTED_EDGE_FIELDS = P1_AE_CPYTHON_INTERNAL_EDGE_FIELDS; P1_AE_CPYTHON_INTERNAL_OBSERVED_EVENT_FIELDS = P1_AE_IMPORT_EVENT_FIELDS; P1_AE_CPYTHON_INTERNAL_OBSERVED_EDGE_FIELDS = P1_AE_CPYTHON_INTERNAL_EDGE_FIELDS; P1_AE_CPYTHON_INTERNAL_EXPECTED_PREIMAGE_FIELDS = ("events", "edges", "event_count", "edge_count"); P1_AE_CPYTHON_INTERNAL_OBSERVED_PREIMAGE_FIELDS = P1_AE_CPYTHON_INTERNAL_EXPECTED_PREIMAGE_FIELDS; P1_AE_CPYTHON_INTERNAL_COMPARISON_FIELDS = ("trace_sequence", "event_kind", "caller_module", "target_module", "caller_source_ref", "caller_source_length", "caller_source_sha256", "target_source_ref", "target_source_length", "target_source_sha256", "caller_code_sha256", "target_code_sha256", "offset", "edge_sequence", "edge_role", "load_role", "channel", "permit_state", "phase", "allowed")
def p1ae_cpython_internal_projection_hash(value: Mapping[str, Any], *, observed: bool) -> str:
    fields = P1_AE_CPYTHON_INTERNAL_OBSERVED_PREIMAGE_FIELDS if observed else P1_AE_CPYTHON_INTERNAL_EXPECTED_PREIMAGE_FIELDS; _check_fields(value, fields, name="CPython internal projection")
    if value["event_count"] != len(value["events"]) or value["edge_count"] != len(value["edges"]): raise _error("DENIED_CAPABILITY", "CPython internal projection count mismatch")
    return canonical_sha256(value, fields=fields)
def p1ae_cpython_internal_comparison_bytes(value: Mapping[str, Any]) -> bytes:
    events = [{field: item[field] for field in P1_AE_CPYTHON_INTERNAL_COMPARISON_FIELDS} for item in value["events"]]; edges = [{field: item[field] for field in P1_AE_CPYTHON_INTERNAL_COMPARISON_FIELDS if field in item} for item in value["edges"]]; return canonical_evaluation_json_bytes({"events": events, "edges": edges}, fields=("events", "edges"))
P1_AE_OWNER_ADMISSION_BINDING_FIELDS = ("package", "gate", "permit", "transaction", "authority", "writer", "residue", "pairing"); P1_AE_OWNER_ADMISSION_PREIMAGE_FIELDS = P1_AE_OWNER_ADMISSION_PREIMAGE_FIELDS + ("binding_records",); P1_AE_QUALITY_ADMISSION_FIELDS = P1_AE_OWNER_ADMISSION_PREIMAGE_FIELDS
P1_AE_CPYTHON_INTERNAL_BINDING_FIELDS = ("cpython_internal_expected_events_hash", "cpython_internal_expected_edges_hash", "cpython_internal_expected_event_count", "cpython_internal_expected_edge_count", "cpython_internal_observed_events_hash", "cpython_internal_observed_edges_hash", "cpython_internal_observed_event_count", "cpython_internal_observed_edge_count")
P1_AE_LOADER_TRANSACTION_FIELDS = P1_AE_LOADER_TRANSACTION_FIELDS + P1_AE_CPYTHON_INTERNAL_BINDING_FIELDS
P1_AE_LOADER_TRANSACTION_PREIMAGE_FIELDS = P1_AE_LOADER_TRANSACTION_FIELDS
P1_AE_OWNER_ADMISSION_PREIMAGE_FIELDS = P1_AE_OWNER_ADMISSION_PREIMAGE_FIELDS + P1_AE_CPYTHON_INTERNAL_BINDING_FIELDS
P1_AE_QUALITY_ADMISSION_FIELDS = P1_AE_OWNER_ADMISSION_PREIMAGE_FIELDS
