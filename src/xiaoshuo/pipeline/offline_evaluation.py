"""Owner-bound, offline deterministic P1 evaluator.

The module is deliberately a small capability boundary.  It accepts every
authority it needs as an argument, never discovers a project or configuration,
and never imports the legacy pipeline.  The only project-local dependency is
the already accepted P0 provenance contract; all P1 state is kept in memory
until the final P0 envelope gate succeeds.
"""

from __future__ import annotations

import base64
import ast
import builtins
import contextlib
import dis
import hashlib
import importlib
import importlib.util
import inspect
import json
import os
import stat
import sys
import threading
import types
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any, Iterable, Mapping, Sequence

from . import provenance
from .evaluation_contracts import (
    ARTIFACT_REF_IDENTITY_FIELDS,
    CPYTHON_RUNTIME_ID_FIELDS,
    CAPABILITY_CENSUS_ENTRY_FIELDS,
    DETERMINISTIC_GUARD_FIELDS,
    DETERMINISTIC_RESIDUE_ENTRY_FIELDS,
    DETERMINISTIC_SEMANTIC_RESULT_FIELDS,
    DETERMINISTIC_TRACE_EVENT_FIELDS,
    DETERMINISTIC_WRITER_OBSERVATION_FIELDS,
    WRITER_INVOCATION_FIELDS,
    WRITER_TRACE_EVENT_FIELDS,
    WRITER_FAILURE_EVIDENCE_FIELDS,
    WRITER_FAILURE_EVIDENCE_PREIMAGE_FIELDS,
    EVALUATION_INPUT_MANIFEST_FIELDS,
    EVALUATOR_SOURCE_ENTRY_FIELDS,
    EVALUATOR_SOURCE_REGISTRY_FIELDS,
    HEX64_GRAMMAR,
    IMPORT_PERMIT_PREIMAGE_FIELDS,
    IMPORT_PERMIT_PREIMAGE_FIELDS_V2,
    LOADED_MODULE_BINDING_FIELDS,
    P1_FORBIDDEN_CAPABILITIES,
    PREIMPORT_GATE_FIELDS,
    RESIDUE_PAIRING_FIELDS,
    RESIDUE_SNAPSHOT_PREIMAGE_FIELDS,
    SEMANTIC_RESULT_EXCLUDED_FIELDS,
    SEMANTIC_RESULT_FIELDS,
    WRITER_TRACE_PLAN_FIELDS,
    EVIDENCE_CONTENT_FIELDS,
    PRE_PERMIT_ATTESTATION_V15_FIELDS,
    CAPABILITY_PROBE_RECORD_FIELDS,
    CAPABILITY_PROBE_SNAPSHOT_FIELDS,
    CAPABILITY_PROBE_COVERAGE_FIELDS,
    OWNER_PROBE_BINDING_FIELDS,
    BOOTSTRAP_MODULE_ENTRY_FIELDS,
    RESOLUTION_COLLECTION_KINDS,
    RESOLUTION_COLLECTION_VALUE_TYPES,
    RESOLUTION_COLLECTION_SNAPSHOT_FIELDS,
    RESOLUTION_COLLECTION_ENTRY_FIELDS,
    RESOLUTION_NESTED_SNAPSHOT_FIELDS,
    RESOLUTION_LIVE_SNAPSHOT_FIELDS,
    RESOLUTION_PROJECTION_FIELDS,
    RESOLUTION_SUPPORT_FIELDS,
    RESOLUTION_GUARD_FIELDS,
    OWNER_INPUT_MANIFEST_FIELDS,
    MARKER_OPCODE_EVENT_FIELDS,
    MARKER_OPCODE_WHITELIST_FIELDS,
    MARKER_OPCODE_SEQUENCE_FIELDS,
    MARKER_ARGUMENT_KINDS,
    MARKER_PURITY_FIELDS,
    P0_ARTIFACT_LINEAGE_FIELDS,
    P0_TO_P1_INPUT_LINEAGE_ADAPTER_FIELDS,
    freeze_evidence,
    input_binding_hash,
    issue_import_permit_v2,
    p0_artifact_lineage,
    p0_to_p1_input_lineage_adapter,
    recompute_permit_digest_v2,
    recompute_permit_seal_v2,
    verify_p0_lineage_integrity,
    ContractRegistryV1,
    EvaluationBindingV1,
    EvaluationError,
    EvaluationInputManifestV1,
    EvaluatorSourceRegistryV1,
    ImportPermitV1,
    P1CapabilityCensusV1,
    P1PreImportGateV1,
    RuleSetRegistryV1,
    canonical_evaluation_json_bytes,
    canonical_lineage_mapping,
    canonical_pairing_hash,
    canonical_sha256,
    canonical_writer_observation,
    canonical_writer_invocation,
    canonical_writer_failure_evidence,
    canonical_residue_snapshot,
    canonical_residue_entries,
    compatibility_matrix_hash,
    compatibility_matrix_mapping,
    issue_import_permit,
    lineage_bytes,
    lineage_hash,
    normalize_relative_path,
    parse_canonical_evaluation_json,
    recompute_permit_digest,
    recompute_permit_seal,
    relative_path_key_utf8_hex,
    sha256_bytes,
    strict_sorted_unique,
    EVALUATION_OUTPUT_ROLE_ORDER,
    validate_evaluation_output_role_order,
    validate_hash,
    validate_relative_path_key,
    validate_role_kind,
    P1_AE_OWNER_ADMISSION_SCHEMA_VERSION,
    P1_AE_PURE_LOADER_TRANSACTION_SCHEMA_VERSION,
    P1_AE_PURE_LOADER_PLAN_FIELDS,
    P1_AE_PURE_LOADER_PLAN_TRANSITION_FIELDS,
    P1_AE_PURE_LOADER_PLAN_TRANSITION_TUPLE,
    P1_AE_PURE_IMPORT_EXPECTED_OBSERVATION_FIELDS,
    P1_AE_PACKAGE_FIELDS,
    P1_AE_GATE_PREIMAGE_FIELDS,
    P1_AE_PERMIT_PREIMAGE_FIELDS,
    P1_AE_LOADER_TRANSACTION_PREIMAGE_FIELDS,
    P1_AE_QUALITY_ADMISSION_FIELDS,
    P1_AE_PURE_LOADER_PLAN_PREIMAGE_FIELDS,
    P1_AE_PHASE_VALUES,
    P1_AE_FORBIDDEN_IMPORT_PROJECTION_FIELDS,
    P1AEPurePermitV1,
    canonical_evaluation_json_bytes as _p1ae_canonical_bytes,
    canonical_sha256 as _p1ae_canonical_sha256,
    issue_p1ae_pure_permit,
    p1ae_loader_plan_binding,
    p1ae_loader_plan_bytes,
    p1ae_loader_plan_hash,
    p1ae_expected_observation_hash,
    p1ae_transition_registry_hash,
)
from .evaluation_metrics import MetricsReport, evaluate_bundle_bytes


D_TMP_ROOT = Path(r"D:\tmp\yeyu-ai-a3")
POST_PERMIT_TRACE_DENY = "POST_PERMIT_TRACE_DENY"
POST_WRITE_IO_FAILURE = "POST_WRITE_IO_FAILURE"
PRE_WRITE_DENY = "PRE_WRITE_DENY"
RESIDUE_ARRAY_ORDER = "NFC_UTF8_RELATIVE_PATH_BYTES"
PERMIT_SCHEMA_VERSION = "P1-IMPORT-PERMIT-V2"
_OWNER_TEST_SEAM = object()
EVIDENCE_PROJECTION_FIELDS = (
    "semantic_result", "loaded_source_bindings", "owner_capability_observation",
    "p0_counters_supplementary", "runtime_attestation",
)


def _evaluator_source_snapshot_hash(source_registry: EvaluatorSourceRegistryV1) -> str:
    """Hash the owner evaluator source set, excluding the manifest carrier.

    The manifest is itself one of the owner source-registry entries.  It is
    therefore excluded from the evaluator-code snapshot used to authenticate
    the manifest, avoiding a self-referential manifest/snapshot hash.  The
    complete registry snapshot remains separately bound in permits and
    evidence.
    """
    entries = [
        dict(entry)
        for entry in source_registry.value["entries"]
        if entry["source_role"] != "manifest"
    ]
    value = {field: source_registry.value[field] for field in EVALUATOR_SOURCE_REGISTRY_FIELDS}
    value["entries"] = entries
    return canonical_sha256(value, fields=EVALUATOR_SOURCE_REGISTRY_FIELDS)


def _evaluator_source_hash(source_registry: EvaluatorSourceRegistryV1) -> str:
    entries = [
        dict(entry)
        for entry in source_registry.value["entries"]
        if entry["source_role"] != "manifest"
    ]
    return canonical_sha256({"entries": entries}, fields=("entries",))


def _deny(code: str, message: str = "offline evaluation denied", **details: Any) -> EvaluationError:
    return EvaluationError(code, message, **details)


def _exception_code(error: BaseException) -> str:
    code = getattr(error, "code", None)
    if isinstance(code, str) and code:
        return code
    errno = getattr(error, "errno", None)
    if isinstance(errno, int):
        return f"ERRNO_{errno}"
    return type(error).__qualname__


def _hash(value: str, field: str) -> None:
    if not isinstance(value, str) or HEX64_GRAMMAR.fullmatch(value) is None:
        raise _deny("DENIED_PROVENANCE", f"{field} is not a lowercase SHA-256")


def _artifact_identity(artifact: provenance.ArtifactRef) -> str:
    """Hash the exact owner-visible P0 lineage bytes for one output artifact."""
    lineage = p0_artifact_lineage(provenance.artifact_lineage(artifact))
    return sha256_bytes(canonical_evaluation_json_bytes(lineage, fields=P0_ARTIFACT_LINEAGE_FIELDS))


def _strict_bytes(value: bytes, field: str = "bytes") -> bytes:
    if not isinstance(value, bytes):
        raise _deny("DENIED_INPUT", f"{field} must be bytes")
    if value.startswith(b"\xef\xbb\xbf") or b"\x00" in value:
        raise _deny("DENIED_INPUT", f"{field} contains BOM or NUL")
    try:
        value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _deny("DENIED_INPUT", f"{field} is not strict UTF-8") from exc
    return value


def _ordered(values: Sequence[str], field: str) -> tuple[str, ...]:
    strict_sorted_unique(list(values), field=field, key="nfc_utf8")
    return tuple(values)


def _final_path(path: Path, root: Path, *, must_exist: bool = False) -> Path:
    """Perform the last containment and reparse check before a read/write."""
    path = Path(path)
    root = Path(root)
    # Check every existing component between the admitted root and target.
    # Checking only ``path.parent`` allows an intermediate junction/symlink to
    # redirect a later read or write while the final path itself looks safe.
    candidates: list[Path] = []
    cursor = path
    while True:
        candidates.append(cursor)
        if cursor == root or cursor.parent == cursor:
            break
        cursor = cursor.parent
    if root not in candidates:
        candidates.append(root)
    for candidate in candidates:
        try:
            stat_result = candidate.lstat()
            attrs = getattr(stat_result, "st_file_attributes", 0)
            if candidate.is_symlink() or attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
                raise _deny("REPARSE_OR_JUNCTION", "reparse point or symlink is denied", path=str(candidate))
        except FileNotFoundError:
            if must_exist and candidate == path:
                raise _deny("MISSING_ARTIFACT", "required path does not exist", path=str(path))
        except OSError as exc:
            raise _deny("PATH_VERIFY_FAILED", "final path verification failed", path=str(candidate)) from exc
    try:
        root_resolved = root.resolve(strict=False)
        path_resolved = path.resolve(strict=False)
        path_resolved.relative_to(root_resolved)
        path_resolved.relative_to(D_TMP_ROOT.resolve(strict=False))
    except (OSError, ValueError) as exc:
        raise _deny("PATH_ESCAPE", "path is outside the admitted D-drive root", path=str(path)) from exc
    if path_resolved.drive.upper() != "D:":
        raise _deny("WRITE_BOUNDARY_UNCERTAIN", "path is not on D drive", path=str(path))
    if any(part.lower() in {"code", "xiaoshuo", "project_root"} for part in path_resolved.parts):
        raise _deny("WRITE_BOUNDARY_UNCERTAIN", "workspace/project path is not an evaluation root")
    if must_exist and not path.exists():
        raise _deny("MISSING_ARTIFACT", "required path does not exist", path=str(path))
    return path_resolved


def _mapping(value: Mapping[str, Any], fields: Sequence[str], name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or tuple(value) != tuple(fields):
        raise _deny("DENIED_PROVENANCE", f"{name} has missing, extra, reordered or duplicate fields")
    return {key: value[key] for key in fields}


def _owner_source_capability_counts(raw: bytes, *, allowed_imports: set[str]) -> dict[str, int]:
    """Perform the independent, import-free owner capability census.

    This is intentionally conservative: an unresolved or ambient operation is
    a deny, never an inferred zero.  The function only parses bytes in memory;
    it does not execute candidate code or consult project/config state.
    """
    try:
        tree = ast.parse(raw.decode("utf-8"), filename="<owner-source-probe>", mode="exec")
    except (SyntaxError, UnicodeDecodeError) as exc:
        raise _deny("DENIED_CAPABILITY", "owner source probe could not parse candidate bytes") from exc
    counts = {name: 0 for name in P1_FORBIDDEN_CAPABILITIES}
    import_roots = {"importlib", "logging", "subprocess", "multiprocessing", "socket", "ssl", "urllib", "http", "requests", "httpx", "aiohttp", "torch", "transformers", "openai", "anthropic", "yaml", "tomllib", "configparser"}
    process_names = {"popen", "run", "call", "check_call", "check_output", "system", "spawn", "execv", "execve", "create_subprocess_exec", "create_subprocess_shell"}
    dynamic_names = {"__import__", "import_module", "find_spec", "eval", "exec", "getattr", "globals", "locals"}
    writer_names = {"open", "write", "write_bytes", "write_text", "safe_write_bytes", "writer", "save", "dump"}
    pure_call_names = {"abs", "all", "any", "bool", "bytes", "dict", "enumerate", "filter", "float", "int", "isinstance", "len", "list", "map", "max", "min", "range", "set", "sorted", "str", "sum", "tuple", "type", "zip"}
    token_map = {
        "checkpoint": "checkpoint", "state": "state", "cache": "cache", "logger": "logger",
        "logging": "logger", "writer": "writer", "network": "network", "api": "api",
        "service": "service", "model": "model", "config": "config_discovery",
        "project_root": "project_discovery", "project_discovery": "project_discovery",
    }

    def bump(capability: str) -> None:
        counts[capability] += 1

    def root_name(node: ast.AST) -> str | None:
        current = node
        while isinstance(current, ast.Attribute):
            current = current.value
        return current.id if isinstance(current, ast.Name) else None

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [item.name for item in node.names]
            for imported in names:
                root = imported.split(".", 1)[0]
                if root not in allowed_imports and root != "__future__":
                    bump("import")
                if root in import_roots:
                    bump("network" if root in {"socket", "ssl", "urllib", "http", "requests", "httpx", "aiohttp"} else "model" if root in {"torch", "transformers", "openai", "anthropic"} else "logger" if root == "logging" else "config_discovery" if root in {"yaml", "tomllib", "configparser"} else "service")
        elif isinstance(node, ast.Call):
            func_name = ""
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
            if func_name in dynamic_names:
                bump("dynamic_import")
            if func_name in process_names:
                bump("process_spawn")
            if func_name in writer_names:
                bump("writer")
            if func_name in {"getLogger", "basicConfig", "debug", "info", "warning", "error", "exception", "critical", "log"}:
                bump("logger")
            if func_name not in pure_call_names and func_name not in dynamic_names and func_name not in process_names and func_name not in writer_names and func_name not in {"getLogger", "basicConfig", "debug", "info", "warning", "error", "exception", "critical", "log", "read_text", "read_bytes", "exists", "is_file", "glob", "rglob"}:
                bump("in_process")
            if func_name in {"open", "read_text", "read_bytes", "exists", "is_file", "glob", "rglob"}:
                for argument in node.args:
                    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                        lowered = argument.value.casefold()
                        if "config" in lowered:
                            bump("config_discovery")
                        if "project" in lowered or "current book" in lowered:
                            bump("project_discovery")
        elif isinstance(node, ast.Compare):
            if any(isinstance(item, ast.Constant) and item.value == "__main__" for item in node.comparators):
                bump("module_main")
        elif isinstance(node, ast.Name):
            lowered = node.id.casefold()
            capability = token_map.get(lowered)
            if capability is not None:
                bump(capability)
        elif isinstance(node, ast.Attribute):
            lowered = node.attr.casefold()
            root = root_name(node)
            if root == "os" and lowered in {"environ", "getenv", "get_exec_path"}:
                bump("config_discovery")
            if root == "os" and lowered in {"getcwd", "walk", "listdir"}:
                bump("project_discovery")
            if root == "sys" and lowered in {"modules", "path", "meta_path", "path_hooks"}:
                bump("import")
            capability = token_map.get(lowered)
            if capability is not None:
                bump(capability)
            elif lowered not in {"__name__", "__doc__"} and root not in allowed_imports:
                # Attribute aliases are not a proof of a permitted operation.
                bump("in_process")
        elif isinstance(node, ast.Subscript):
            root = root_name(node.value) if isinstance(node.value, ast.Attribute) else node.value.id if isinstance(node.value, ast.Name) else None
            if root == "os":
                bump("config_discovery")
            if root == "sys":
                bump("import")
            # Closed world: an unknown subscript can read environment,
            # module state, or an ambient capability and is never accepted.
            bump("in_process")

    # Calls through an unresolved object are not a permitted proof of absence.
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and not isinstance(node.func, (ast.Name, ast.Attribute)):
            bump("in_process")
    return counts


def owner_probe_binding_snapshot(
    *,
    owner_id: str,
    authority_ref: str,
    source_registry: EvaluatorSourceRegistryV1,
    source_root: Path,
    candidate_source_entries: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the owner-recomputable probe binding used by gate and permit."""
    evaluator_entries = [entry for entry in source_registry.value["entries"] if entry["source_role"] == "evaluator"]
    if len(evaluator_entries) != 1:
        raise _deny("DENIED_CAPABILITY", "owner probe source entry is not unique")
    evaluator = dict(evaluator_entries[0])
    if source_registry.value["owner_id"] != owner_id or source_registry.value["authoritative_source_ref"] != authority_ref:
        raise _deny("DENIED_PROVENANCE", "owner probe source authority mismatch")
    evaluator_path = _final_path(Path(source_root) / evaluator["relative_path"], Path(source_root), must_exist=True)
    evaluator_bytes = _strict_bytes(evaluator_path.read_bytes(), "owner probe source")
    source_registry.verify_bytes(evaluator, evaluator_bytes)
    entries = list(candidate_source_entries) if candidate_source_entries is not None else [
        dict(entry) for entry in source_registry.value["entries"] if entry["source_role"] in {"candidate", "static"}
    ]
    coverage: list[dict[str, Any]] = []
    previous: bytes | None = None
    for entry in entries:
        if entry.get("source_role") not in {"candidate", "static"}:
            raise _deny("DENIED_CAPABILITY", "owner probe coverage contains a non-candidate/static source")
        path_key = normalize_relative_path(entry["relative_path"], allow_root=False).encode("utf-8")
        if previous is not None and path_key <= previous:
            raise _deny("DENIED_CAPABILITY", "owner probe candidate coverage is unsorted or duplicated")
        previous = path_key
        source_path = _final_path(Path(source_root) / entry["relative_path"], Path(source_root), must_exist=True)
        raw = _strict_bytes(source_path.read_bytes(), "owner probe candidate source")
        source_registry.verify_bytes(entry, raw)
        coverage.append(_mapping({
            "source_role": entry["source_role"],
            "source_relative_path": entry["relative_path"], "source_ref": entry["source_ref"],
            "source_length": entry["length"], "source_sha256": entry["sha256"],
        }, CAPABILITY_PROBE_COVERAGE_FIELDS, "owner probe source coverage"))
    coverage_hash = canonical_sha256({"entries": coverage}, fields=("entries",))
    code = P1CapabilityObserver.owner_attestation.__code__
    return _mapping({
        "owner_probe_schema_version": "P1-OWNER-PROBE-BINDING-V1", "owner_id": owner_id,
        "authority_ref": authority_ref, "qualname": P1CapabilityObserver.owner_attestation.__qualname__,
        "code_object_sha256": code_object_sha256(code), "source_relative_path": evaluator["relative_path"],
        "source_ref": evaluator["source_ref"], "source_length": evaluator["length"],
        "source_sha256": evaluator["sha256"], "forbidden_capabilities": list(P1_FORBIDDEN_CAPABILITIES),
        "candidate_source_coverage": coverage, "candidate_source_coverage_hash": coverage_hash,
    }, OWNER_PROBE_BINDING_FIELDS, "owner probe binding")


@dataclass
class P1CapabilityObserver:
    """Owner/harness observation; P0 counters are intentionally not trusted."""

    _values: dict[str, int] = field(default_factory=lambda: {name: 0 for name in P1_FORBIDDEN_CAPABILITIES})

    def reset(self) -> None:
        self._values = {name: 0 for name in P1_FORBIDDEN_CAPABILITIES}

    def observe(self, capability: str, amount: int = 1) -> None:
        if capability not in self._values or not isinstance(amount, int) or amount < 0:
            raise _deny("DENIED_CAPABILITY", "unknown owner capability observation")
        self._values[capability] += amount

    def snapshot(self) -> dict[str, int]:
        if tuple(self._values) != P1_FORBIDDEN_CAPABILITIES:
            raise _deny("DENIED_CAPABILITY", "capability observation fields are incomplete")
        if any(not isinstance(value, int) or value < 0 for value in self._values.values()):
            raise _deny("DENIED_CAPABILITY", "capability observation values are invalid")
        return dict(self._values)

    def assert_zero(self) -> None:
        values = self.snapshot()
        if any(values.values()):
            raise _deny("DENIED_CAPABILITY", "forbidden capability observation was non-zero", values=values)

    def owner_attestation(
        self,
        *,
        owner_id: str,
        authority_ref: str,
        source_registry: EvaluatorSourceRegistryV1,
        source_root: Path | None = None,
        census: P1CapabilityCensusV1 | None = None,
    ) -> dict[str, Any]:
        """Return an independent owner-side source observation.

        The P0 counter-like values are supplementary only.  A zero result is
        accepted here only after the owner reads every admitted candidate
        source, verifies its bytes against the source registry, and performs a
        side-effect-free AST census before candidate loading.  The probe never
        imports the candidate and never discovers a project or configuration.
        """
        values = self.snapshot()
        entries = tuple(source_registry.value["entries"])
        if not entries:
            raise _deny("DENIED_CAPABILITY", "owner capability source binding is missing")
        if source_root is None:
            raise _deny("DENIED_CAPABILITY", "real owner capability probe requires an explicit source root")
        if source_registry.value["owner_id"] != owner_id or source_registry.value["authoritative_source_ref"] != authority_ref:
            raise _deny("DENIED_CAPABILITY", "owner capability source authority mismatch")
        source = next((dict(item) for item in entries if item.get("source_role") == "evaluator"), None)
        if source is None:
            raise _deny("DENIED_CAPABILITY", "owner capability probe evaluator source is missing")
        candidate_entries = tuple(item for item in entries if item.get("source_role") in {"candidate", "static"})
        probe_binding = owner_probe_binding_snapshot(
            owner_id=owner_id, authority_ref=authority_ref, source_registry=source_registry,
            source_root=Path(source_root), candidate_source_entries=candidate_entries,
        )
        census_by_module = {}
        if census is not None:
            census_by_module = {item["module_path"]: item for item in census.value["entries"]}
        actual_values = {name: 0 for name in P1_FORBIDDEN_CAPABILITIES}
        for source_entry in candidate_entries:
            source_path = _final_path(Path(source_root) / source_entry["relative_path"], Path(source_root), must_exist=True)
            raw = _strict_bytes(source_path.read_bytes(), "owner capability probe source")
            source_registry.verify_bytes(source_entry, raw)
            census_entry = next((item for item in census_by_module.values() if item["source_relative_path"] == source_entry["relative_path"]), None)
            if census_entry is None:
                raise _deny("DENIED_CAPABILITY", "owner capability probe source is absent from census")
            allowed_imports = set(census_entry["static_imports"])
            counts = _owner_source_capability_counts(raw, allowed_imports=allowed_imports)
            for capability, amount in counts.items():
                actual_values[capability] += amount
        values = {capability: max(values[capability], actual_values[capability]) for capability in P1_FORBIDDEN_CAPABILITIES}
        if any(values.values()):
            raise _deny("DENIED_CAPABILITY", "owner source probe observed a forbidden capability", values=values)
        records: list[dict[str, Any]] = []
        operation_catalog_hash = sha256_bytes(canonical_evaluation_json_bytes({"capabilities": list(P1_FORBIDDEN_CAPABILITIES)}, fields=("capabilities",)))
        for capability in P1_FORBIDDEN_CAPABILITIES:
            record = {
                "probe_schema_version": "P1-CAPABILITY-PROBE-V1", "capability": capability,
                "owner_id": owner_id, "authority_ref": authority_ref,
                "owner_source_relative_path": source["relative_path"], "owner_source_ref": source["source_ref"],
                "owner_source_length": source["length"], "owner_source_sha256": source["sha256"],
                "operation_catalog_hash": operation_catalog_hash, "covered_operation_ids": [capability],
                "observation_method": "OWNER_BOUNDARY_PROBE", "installed": True, "complete": True,
                "observed_call_count": values[capability], "observed_deny_count": 0,
                "status": "READY" if values[capability] == 0 else "DENY",
            }
            records.append(_mapping(record, CAPABILITY_PROBE_RECORD_FIELDS, "capability probe record"))
        snapshot = {
            "snapshot_schema_version": "P1-CAPABILITY-PROBE-SNAPSHOT-V1", "owner_id": owner_id,
            "authority_ref": authority_ref,
            "owner_probe_schema_version": probe_binding["owner_probe_schema_version"],
            "owner_probe_qualname": probe_binding["qualname"], "owner_probe_code_sha256": probe_binding["code_object_sha256"],
            "owner_probe_source_relative_path": probe_binding["source_relative_path"],
            "owner_probe_source_ref": probe_binding["source_ref"], "owner_probe_source_length": probe_binding["source_length"],
            "owner_probe_source_sha256": probe_binding["source_sha256"],
            "forbidden_capabilities": list(probe_binding["forbidden_capabilities"]),
            "candidate_source_coverage": list(probe_binding["candidate_source_coverage"]),
            "candidate_source_coverage_hash": probe_binding["candidate_source_coverage_hash"],
            "evaluator_source_registry_snapshot_hash": _evaluator_source_snapshot_hash(source_registry),
            "records": records, "complete": True, "status": "READY" if not any(values.values()) else "DENY",
        }
        result = _mapping(snapshot, CAPABILITY_PROBE_SNAPSHOT_FIELDS, "capability probe snapshot")
        if result["status"] != "READY" or result["complete"] is not True:
            raise _deny("DENIED_CAPABILITY", "owner capability observation is not a complete zero-call proof")
        if tuple(item["capability"] for item in result["records"]) != tuple(P1_FORBIDDEN_CAPABILITIES):
            raise _deny("DENIED_CAPABILITY", "owner capability records are missing, duplicated or reordered")
        return result


@dataclass(frozen=True)
class ArtifactResolverSnapshotV1:
    value: Mapping[str, Any]

    def __post_init__(self) -> None:
        fields = (
            "resolver_schema_version", "owner_id", "authoritative_source_ref", "snapshot_id",
            "root_alias", "parent_store_snapshot_hash", "read_only", "records",
        )
        _mapping(self.value, fields, "artifact resolver snapshot")
        if self.value["read_only"] is not True:
            raise _deny("DENIED_PROVENANCE", "resolver must be read-only")
        validate_hash(self.value["parent_store_snapshot_hash"], field="parent_store_snapshot_hash")
        previous: bytes | None = None
        for item in self.value["records"]:
            record = _mapping(item, ("relative_path", "lineage_record_hash", "lineage_record"), "resolver record")
            path = normalize_relative_path(record["relative_path"])
            key = path.encode("utf-8")
            if previous is not None and key <= previous:
                raise _deny("DENIED_PROVENANCE", "resolver records are not strictly ordered")
            previous = key
            if record["lineage_record"]["relative_path"] != path:
                raise _deny("DENIED_PROVENANCE", "resolver record path mismatch")
            if lineage_hash(record["lineage_record"]) != record["lineage_record_hash"]:
                raise _deny("DENIED_PROVENANCE", "resolver lineage hash mismatch")

    @property
    def snapshot_hash(self) -> str:
        return canonical_sha256(dict(self.value))

    @property
    def records(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(item) for item in self.value["records"])


class OwnerArtifactResolver:
    """Readback resolver which produces a fresh P0 token only after all checks."""

    def __init__(
        self,
        *,
        context: provenance.ExecutionContext,
        snapshot: ArtifactResolverSnapshotV1,
        root: Path,
        parent_store: provenance.ParentRefStoreV1,
        observer: P1CapabilityObserver | None = None,
    ) -> None:
        if not isinstance(context, provenance.ExecutionContext):
            raise _deny("MISSING_PROJECT_CONTEXT", "resolver requires an explicit execution context")
        if observer is not None:
            raise _deny("DENIED_CAPABILITY", "resolver cannot accept a caller-supplied observer")
        self.context = context
        self.snapshot = snapshot
        self.root = _final_path(Path(root), Path(root))
        self.parent_store = parent_store
        self._verified_contents: dict[str, bytes] = {}
        if snapshot.value["root_alias"] != context.root_alias:
            raise _deny("DENIED_PROVENANCE", "resolver root alias mismatch")
        if snapshot.value["parent_store_snapshot_hash"] != parent_store.snapshot_hash:
            raise _deny("DENIED_PROVENANCE", "resolver parent store snapshot mismatch")
        parent_store.validate_for_context(context)

    def _record_for(self, relative_path: str) -> dict[str, Any]:
        canonical = normalize_relative_path(relative_path)
        records = [item for item in self.snapshot.records if item["relative_path"] == canonical]
        if len(records) != 1:
            raise _deny("DENIED_PROVENANCE", "artifact is not in the owner resolver snapshot")
        return records[0]

    def resolve(self, artifact_identity: Mapping[str, Any]) -> provenance.ArtifactRef:
        lineage = p0_artifact_lineage(artifact_identity)
        verify_p0_lineage_integrity(lineage)
        if lineage["project_id"] != self.context.project_id:
            raise _deny("UNKNOWN_PROJECT", "artifact project is not context-bound")
        if lineage["namespace_digest"] != self.context.namespace_digest:
            raise _deny("OLD_NAMESPACE_ARTIFACT", "artifact namespace is not current")
        if lineage["root_alias"] != self.context.root_alias:
            raise _deny("DENIED_PROVENANCE", "artifact root alias mismatch")
        record = self._record_for(lineage["relative_path"])
        if record["lineage_record"] != lineage or record["lineage_record_hash"] != lineage_hash(lineage):
            raise _deny("DENIED_PROVENANCE", "artifact lineage does not match owner bytes")
        if self.snapshot.snapshot_hash != canonical_sha256(dict(self.snapshot.value)):
            raise _deny("DENIED_PROVENANCE", "resolver snapshot cannot be recomputed")
        if self.parent_store.snapshot_hash != self.snapshot.value["parent_store_snapshot_hash"]:
            raise _deny("DENIED_PROVENANCE", "parent store changed after admission")
        try:
            persisted = provenance.validate_artifact_lineage(
                self.context, lineage, expected_batch_id=lineage["batch_id"]
            )
        except provenance.ProvenanceError as exc:
            raise _deny("DENIED_PROVENANCE", "P0 lineage validation failed", cause=exc.code) from exc
        path = _final_path(self.root / lineage["relative_path"], self.root, must_exist=True)
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise _deny("READBACK_FAILED", "artifact readback failed") from exc
        _strict_bytes(content, "artifact content")
        if len(content) != lineage["content_length"] or sha256_bytes(content) != lineage["content_sha256"]:
            raise _deny("DENIED_PROVENANCE", "artifact content hash/length mismatch")
        try:
            verified = provenance.make_artifact_ref(
                self.context,
                lineage["relative_path"],
                content,
                source_ref=lineage["source_ref"],
                batch_id=lineage["batch_id"],
                parent_refs=tuple(lineage["parent_refs"]),
            )
            provenance.validate_artifact_ref(
                self.context, verified, content, expected_batch_id=lineage["batch_id"]
            )
        except provenance.ProvenanceError as exc:
            raise _deny("DENIED_PROVENANCE", "P0 runtime artifact validation failed", cause=exc.code) from exc
        if canonical_lineage_mapping(provenance.artifact_lineage(verified)) != lineage:
            raise _deny("DENIED_PROVENANCE", "P0 and P1 lineage serialization differ")
        if persisted.integrity_digest != verified.integrity_digest:
            raise _deny("DENIED_PROVENANCE", "persisted and runtime lineage digest differ")
        self._verified_contents[lineage_hash(lineage)] = bytes(content)
        return verified

    def read_verified_content(self, artifact: provenance.ArtifactRef | Mapping[str, Any]) -> bytes:
        """Return owner-verified bytes and reject any read-after-verify drift."""
        if isinstance(artifact, provenance.ArtifactRef):
            lineage = p0_artifact_lineage(provenance.artifact_lineage(artifact))
        else:
            lineage = p0_artifact_lineage(artifact)
        verify_p0_lineage_integrity(lineage)
        key = lineage_hash(lineage)
        cached = self._verified_contents.get(key)
        if cached is None:
            raise _deny("DENIED_PROVENANCE", "artifact bytes were not owner-verified")
        path = _final_path(self.root / lineage["relative_path"], self.root, must_exist=True)
        try:
            current = _strict_bytes(path.read_bytes(), "artifact readback")
        except OSError as exc:
            raise _deny("READBACK_FAILED", "artifact readback failed after verification") from exc
        if current != cached or len(current) != lineage["content_length"] or sha256_bytes(current) != lineage["content_sha256"]:
            raise _deny("DENIED_PROVENANCE", "input artifact changed after owner verification")
        return bytes(cached)


CODE_OBJECT_PREIMAGE_FIELDS = (
    "code_schema_version", "co_argcount", "co_posonlyargcount", "co_kwonlyargcount",
    "co_nlocals", "co_stacksize", "co_flags", "co_code_hex", "co_consts", "co_names",
    "co_varnames", "co_freevars", "co_cellvars", "co_filename_utf8_hex", "co_name_utf8_hex",
    "co_qualname_utf8_hex", "co_firstlineno", "co_linetable_hex", "co_exceptiontable_hex",
    "nested_code_objects",
)
CODE_CONST_FIELDS = ("kind", "value")
CODE_NESTED_FIELDS = ("const_index", "code_object")
CODE_CONST_KINDS = ("NONE", "BOOL", "INT", "FLOAT_IEEE754_HEX", "COMPLEX_IEEE754_HEX", "STR_UTF8_HEX", "BYTES_HEX", "TUPLE", "FROZENSET", "CODE_OBJECT")


def _constant_preimage(value: Any) -> dict[str, Any]:
    if value is None:
        result = {"kind": "NONE", "value": None}
    elif isinstance(value, bool):
        result = {"kind": "BOOL", "value": value}
    elif isinstance(value, int):
        result = {"kind": "INT", "value": str(value)}
    elif isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise _deny("DENIED_PROVENANCE", "non-finite code constant is not attestable")
        result = {"kind": "FLOAT_IEEE754_HEX", "value": value.hex()}
    elif isinstance(value, complex):
        if any(part != part or part in (float("inf"), float("-inf")) for part in (value.real, value.imag)):
            raise _deny("DENIED_PROVENANCE", "non-finite complex constant is not attestable")
        result = {"kind": "COMPLEX_IEEE754_HEX", "value": [value.real.hex(), value.imag.hex()]}
    elif isinstance(value, str):
        result = {"kind": "STR_UTF8_HEX", "value": value.encode("utf-8").hex()}
    elif isinstance(value, bytes):
        result = {"kind": "BYTES_HEX", "value": value.hex()}
    elif isinstance(value, tuple):
        result = {"kind": "TUPLE", "value": [_constant_preimage(item) for item in value]}
    elif isinstance(value, frozenset):
        members = [_constant_preimage(item) for item in value]
        members.sort(key=lambda item: canonical_evaluation_json_bytes(item, fields=CODE_CONST_FIELDS))
        result = {"kind": "FROZENSET", "value": members}
    elif isinstance(value, types.CodeType):
        result = {"kind": "CODE_OBJECT", "value": code_object_preimage(value)}
    else:
        raise _deny("DENIED_PROVENANCE", f"unsupported code constant type: {type(value).__qualname__}")
    return _mapping(result, CODE_CONST_FIELDS, "typed code constant")


def code_object_preimage(code: types.CodeType) -> dict[str, Any]:
    if not isinstance(code, types.CodeType):
        raise _deny("DENIED_PROVENANCE", "writer target is not a code object")
    nested = [
        _mapping({"const_index": index, "code_object": code_object_preimage(item)}, CODE_NESTED_FIELDS, "nested code object")
        for index, item in enumerate(code.co_consts) if isinstance(item, types.CodeType)
    ]
    value = {
        "code_schema_version": "CPYTHON_CODE_OBJECT_PREIMAGE_V2",
        "co_argcount": code.co_argcount, "co_posonlyargcount": code.co_posonlyargcount,
        "co_kwonlyargcount": code.co_kwonlyargcount, "co_nlocals": code.co_nlocals,
        "co_stacksize": code.co_stacksize, "co_flags": code.co_flags,
        "co_code_hex": code.co_code.hex(), "co_consts": [_constant_preimage(item) for item in code.co_consts],
        "co_names": list(code.co_names), "co_varnames": list(code.co_varnames),
        "co_freevars": list(code.co_freevars), "co_cellvars": list(code.co_cellvars),
        "co_filename_utf8_hex": code.co_filename.encode("utf-8").hex(),
        "co_name_utf8_hex": code.co_name.encode("utf-8").hex(),
        "co_qualname_utf8_hex": code.co_qualname.encode("utf-8").hex(),
        "co_firstlineno": code.co_firstlineno,
        "co_linetable_hex": getattr(code, "co_linetable", b"").hex(),
        "co_exceptiontable_hex": getattr(code, "co_exceptiontable", b"").hex(),
        "nested_code_objects": nested,
    }
    return _mapping(value, CODE_OBJECT_PREIMAGE_FIELDS, "code object preimage")


def code_object_sha256(code: types.CodeType) -> str:
    return canonical_sha256(code_object_preimage(code))


RUNTIME_ATTESTATION_FIELDS = (
    "attestation_schema_version", "implementation_name", "implementation_version",
    "cache_tag", "python_version", "opcode_version", "wordcode_size", "has_arg_rule", "thread_id",
)


def runtime_attestation(*, thread_id: int | None = None) -> dict[str, Any]:
    implementation = sys.implementation
    version = implementation.version
    value = {
        "attestation_schema_version": "CPYTHON_RUNTIME_ATTESTATION_V1",
        "implementation_name": implementation.name,
        "implementation_version": [version.major, version.minor, version.micro, version.releaselevel, version.serial],
        "cache_tag": implementation.cache_tag or "",
        "python_version": list(sys.version_info[:5]),
        "opcode_version": sha256_bytes(canonical_evaluation_json_bytes({"opmap": dict(sorted(dis.opmap.items())), "hasarg": dis.HAVE_ARGUMENT})),
        "wordcode_size": getattr(dis, "_inline_cache_entries", []).__len__() if hasattr(dis, "_inline_cache_entries") else 2,
        "has_arg_rule": int(dis.HAVE_ARGUMENT),
        "thread_id": int(threading.get_ident() if thread_id is None else thread_id),
    }
    return _mapping(value, RUNTIME_ATTESTATION_FIELDS, "runtime attestation")


def runtime_identity_snapshot() -> dict[str, Any]:
    implementation = sys.implementation
    version = implementation.version
    opcode_rows = [
        {"opcode": int(opcode), "opname_utf8_hex": name.encode("utf-8").hex(), "has_argument": int(opcode) >= int(dis.HAVE_ARGUMENT)}
        for name, opcode in sorted(dis.opmap.items(), key=lambda item: item[1])
    ]
    opname_rows = [name.encode("utf-8").hex() for name in dis.opname]
    value = {
        "runtime_schema_version": "CPYTHON_RUNTIME_ID_V2",
        "implementation_name": implementation.name,
        "implementation_version": [version.major, version.minor, version.micro, version.releaselevel, version.serial],
        "python_version": list(sys.version_info[:5]),
        "cache_tag": implementation.cache_tag or "",
        "opcode_format": "CPYTHON_WORDCODE_OPCODE_V1",
        "wordcode_unit_size": 2,
        "supports_opcode_trace": sys.implementation.name == "cpython" and hasattr(sys._getframe(), "f_trace_opcodes"),
        "has_argument": int(dis.HAVE_ARGUMENT),
        "opcode_table": opcode_rows,
        "opname_table": opname_rows,
    }
    if value["implementation_name"] != "cpython" or value["supports_opcode_trace"] is not True:
        raise _deny("DENIED_PROVENANCE", "CPython opcode tracing is unavailable")
    return _mapping(value, CPYTHON_RUNTIME_ID_FIELDS, "CPython runtime identity")


def _opcode_attestation_marker() -> int:
    """Pure in-memory marker: no name lookup, I/O, call, or ambient access."""
    return 1


def _opcode_attestation_probe() -> None:
    _opcode_attestation_marker()


def _opcode_records(function: Any) -> tuple[dict[str, Any], ...]:
    records: list[dict[str, Any]] = []
    for instruction in dis.get_instructions(function, show_caches=True, adaptive=False):
        records.append(_mapping({
            "opcode": int(instruction.opcode),
            "opname_utf8_hex": instruction.opname.encode("utf-8").hex(),
            "has_argument": bool(int(instruction.opcode) >= int(dis.HAVE_ARGUMENT)),
        }, MARKER_OPCODE_WHITELIST_FIELDS, "opcode record"))
    return tuple(records)


def _trace_visible_instructions(function: Any) -> tuple[dis.Instruction, ...]:
    # CPython's opcode tracing channel intentionally does not emit the
    # synthetic RESUME instruction (nor inline CACHE entries).  The sequence
    # is therefore defined over the actual observable opcode channel, never a
    # line-span approximation.
    return tuple(item for item in dis.get_instructions(function, show_caches=True, adaptive=False) if item.opname not in {"RESUME", "CACHE"})


def _opcode_argument(instruction: dis.Instruction) -> tuple[str, Any]:
    if instruction.arg is None:
        return "NONE", None
    if instruction.opname in {"LOAD_CONST", "STORE_CONST"}:
        return "CONST_INDEX", str(int(instruction.arg))
    if instruction.opname in {"LOAD_NAME", "LOAD_GLOBAL", "LOAD_ATTR", "STORE_NAME", "STORE_GLOBAL", "STORE_ATTR"}:
        return "NAME_INDEX", str(int(instruction.arg))
    if "JUMP" in instruction.opname or instruction.opname in {"FOR_ITER", "SEND"}:
        return "JUMP_TARGET_OFFSET", str(int(instruction.argval if isinstance(instruction.argval, int) else instruction.arg))
    return "INT", str(int(instruction.arg))


def _opcode_event(function: Any, role: str, sequence: int, instruction: dis.Instruction) -> dict[str, Any]:
    kind, value = _opcode_argument(instruction)
    return _mapping({
        "sequence": int(sequence), "code_object_role": role,
        "code_object_sha256": code_object_sha256(function.__code__),
        "instruction_offset": int(instruction.offset), "opcode": int(instruction.opcode),
        "opname_utf8_hex": instruction.opname.encode("utf-8").hex(),
        "has_argument": bool(int(instruction.opcode) >= int(dis.HAVE_ARGUMENT)),
        "argument_kind": kind, "argument_value": value,
    }, MARKER_OPCODE_EVENT_FIELDS, "opcode event")


def _validate_opcode_event(event: Mapping[str, Any], *, role: str, expected_sequence: int) -> None:
    record = _mapping(event, MARKER_OPCODE_EVENT_FIELDS, "opcode event")
    if record["sequence"] != expected_sequence or record["code_object_role"] != role:
        raise _deny("DENIED_PROVENANCE", "opcode event sequence or role mismatch")
    if not isinstance(record["sequence"], int) or record["sequence"] < 0:
        raise _deny("DENIED_PROVENANCE", "opcode event sequence is invalid")
    if not isinstance(record["instruction_offset"], int) or record["instruction_offset"] < 0:
        raise _deny("DENIED_PROVENANCE", "opcode event offset is invalid")
    if not isinstance(record["opcode"], int) or record["opcode"] < 0:
        raise _deny("DENIED_PROVENANCE", "opcode event opcode is invalid")
    if not isinstance(record["has_argument"], bool) or record["argument_kind"] not in MARKER_ARGUMENT_KINDS:
        raise _deny("DENIED_PROVENANCE", "opcode event argument schema is invalid")
    if not isinstance(record["argument_value"], (str, type(None))):
        raise _deny("DENIED_PROVENANCE", "opcode event argument value is not canonical")
    if not record["has_argument"] and (record["argument_kind"], record["argument_value"]) != ("NONE", None):
        raise _deny("DENIED_PROVENANCE", "opcode without argument has non-null argument")
    if record["has_argument"] and record["argument_kind"] == "NONE":
        raise _deny("DENIED_PROVENANCE", "opcode with argument has NONE kind")
    if record["argument_kind"] == "NONE" and record["argument_value"] is not None:
        raise _deny("DENIED_PROVENANCE", "NONE argument is not null")
    if record["argument_kind"] == "INT" and not record["argument_value"].lstrip("-").isdigit():
        raise _deny("DENIED_PROVENANCE", "INT argument is not a canonical decimal string")
    if record["argument_kind"] in {"CONST_INDEX", "NAME_INDEX", "JUMP_TARGET_OFFSET"}:
        value = record["argument_value"]
        if not value.isdigit() or (len(value) > 1 and value.startswith("0")):
            raise _deny("DENIED_PROVENANCE", "index/offset argument is not canonical")


def _marker_sequence_hash(function: Any, runtime_snapshot_hash: str) -> str:
    code_hash = code_object_sha256(function.__code__)
    events = []
    for sequence, instruction in enumerate(_trace_visible_instructions(function)):
        events.append(_opcode_event(function, "MARKER", sequence, instruction))
    value = {"sequence_schema_version": "MARKER_OPCODE_SEQUENCE_V2", "cpython_runtime_snapshot_hash": runtime_snapshot_hash, "marker_code_sha256": code_hash, "events": events, "complete": True, "status": "READY"}
    return canonical_sha256(value, fields=MARKER_OPCODE_SEQUENCE_FIELDS)


def _call_offset(instructions: Sequence[dis.Instruction], marker: str) -> tuple[int, int]:
    for index, instruction in enumerate(instructions):
        if marker in instruction.argrepr or instruction.argval == marker:
            for candidate in instructions[index + 1: index + 8]:
                if candidate.opname.startswith("CALL"):
                    return int(instruction.starts_line or 0), int(candidate.offset)
    raise _deny("DENIED_PROVENANCE", f"trace target {marker} has no exact CALL offset")


def build_writer_trace_plan(
    *,
    owner_id: str,
    authority_ref: str,
    provenance_source_ref: str,
    provenance_source_path: Path | None = None,
    trace_thread_id: int | None = None,
) -> dict[str, Any]:
    source_path = Path(provenance_source_path or provenance.__file__)
    if not source_path.is_file():
        raise _deny("DENIED_PROVENANCE", "P0 provenance source is not readable")
    source_bytes = _strict_bytes(source_path.read_bytes(), "provenance source")
    function = provenance.safe_write_bytes
    instructions = tuple(dis.get_instructions(function))
    transaction_line, transaction_offset = _call_offset(instructions, "execution_root")
    writer_line, writer_offset = _call_offset(instructions, "write_bytes")
    probe_instructions = tuple(dis.get_instructions(_opcode_attestation_probe))
    _, probe_call_offset = _call_offset(probe_instructions, "_opcode_attestation_marker")
    runtime = runtime_identity_snapshot()
    runtime_hash = canonical_sha256(runtime, fields=CPYTHON_RUNTIME_ID_FIELDS)
    module_source_path = Path(__file__)
    if not module_source_path.is_file():
        raise _deny("DENIED_PROVENANCE", "evaluator source is not readable")
    module_source_bytes = _strict_bytes(module_source_path.read_bytes(), "evaluator source")
    marker_records = list(_opcode_records(_opcode_attestation_marker))
    marker_whitelist = sorted(marker_records, key=lambda item: (item["opcode"], item["opname_utf8_hex"], item["has_argument"]))
    if any(bytes.fromhex(item["opname_utf8_hex"]).decode("utf-8") not in {"RESUME", "LOAD_CONST", "RETURN_VALUE", "RETURN_CONST", "CACHE", "NOP"} for item in marker_whitelist):
        raise _deny("DENIED_CAPABILITY", "marker opcode whitelist contains a non-pure opcode")
    marker_code_hash = code_object_sha256(_opcode_attestation_marker.__code__)
    probe_code_hash = code_object_sha256(_opcode_attestation_probe.__code__)
    marker_sequence_hash = _marker_sequence_hash(_opcode_attestation_marker, runtime_hash)
    purity = {
        "marker_schema_version": "MARKER_PURITY_V2", "marker_module_path": __name__, "marker_qualname": _opcode_attestation_marker.__qualname__,
        "marker_source_relative_path": "xiaoshuo/pipeline/offline_evaluation.py", "marker_source_ref": "p1-offline-evaluation-source-v2",
        "marker_source_length": len(module_source_bytes), "marker_source_sha256": sha256_bytes(module_source_bytes),
        "marker_code_sha256": marker_code_hash, "marker_code_firstlineno": _opcode_attestation_marker.__code__.co_firstlineno,
        "probe_module_path": __name__, "probe_qualname": _opcode_attestation_probe.__qualname__,
        "probe_source_relative_path": "xiaoshuo/pipeline/offline_evaluation.py", "probe_source_ref": "p1-offline-evaluation-source-v2",
        "probe_source_length": len(module_source_bytes), "probe_source_sha256": sha256_bytes(module_source_bytes),
        "probe_code_sha256": probe_code_hash, "probe_code_firstlineno": _opcode_attestation_probe.__code__.co_firstlineno,
        "marker_opcode_whitelist": marker_whitelist, "marker_opcode_sequence_hash": marker_sequence_hash,
        "marker_call_count": 0, "marker_purity_status": "READY",
    }
    marker_purity_hash = canonical_sha256(purity, fields=MARKER_PURITY_FIELDS)
    value = {
        "plan_schema_version": "P1-WRITER-TRACE-PLAN-V1", "plan_id": "safe-write-bytes", "owner_id": owner_id,
        "authority_ref": authority_ref, "provenance_source_ref": provenance_source_ref,
        "provenance_source_sha256": sha256_bytes(source_bytes), "safe_write_qualname": function.__qualname__,
        "safe_write_code_filename": function.__code__.co_filename, "safe_write_first_line": function.__code__.co_firstlineno,
        "safe_write_code_object_sha256": code_object_sha256(function.__code__), "trace_backend": "CPYTHON_OPCODE_TRACE_V1",
        "trace_thread_id": int(threading.get_ident() if trace_thread_id is None else trace_thread_id),
        "transaction_call_line": transaction_line, "transaction_call_offset": transaction_offset,
        "writer_call_line": writer_line, "writer_call_offset": writer_offset, "probe_call_offset": probe_call_offset,
        "runtime_snapshot_hash": runtime_hash, "runtime_id_fields_hash": runtime_hash,
        "marker_module_path": purity["marker_module_path"], "marker_qualname": purity["marker_qualname"],
        "marker_source_relative_path": purity["marker_source_relative_path"], "marker_source_ref": purity["marker_source_ref"],
        "marker_source_length": purity["marker_source_length"], "marker_source_sha256": purity["marker_source_sha256"],
        "marker_code_sha256": marker_code_hash, "marker_code_firstlineno": purity["marker_code_firstlineno"],
        "probe_module_path": purity["probe_module_path"], "probe_qualname": purity["probe_qualname"],
        "probe_source_relative_path": purity["probe_source_relative_path"], "probe_source_ref": purity["probe_source_ref"],
        "probe_source_length": purity["probe_source_length"], "probe_source_sha256": purity["probe_source_sha256"],
        "probe_code_sha256": probe_code_hash, "probe_code_firstlineno": purity["probe_code_firstlineno"],
        "marker_opcode_whitelist": marker_whitelist, "marker_opcode_sequence_hash": marker_sequence_hash,
        "marker_purity_hash": marker_purity_hash, "read_only": True,
    }
    for field_name in ("provenance_source_sha256", "safe_write_code_object_sha256"):
        _hash(value[field_name], field_name)
    return _mapping(value, WRITER_TRACE_PLAN_FIELDS, "writer trace plan")


@dataclass
class OpcodeWriterTrace:
    plan: Mapping[str, Any]
    phase: str = "PRE_PERMIT"
    events: list[dict[str, Any]] = field(default_factory=list)
    transaction_started: bool = False
    writer_call_started: bool = False
    writer_returned: bool = False
    writer_raised: bool = False
    return_offset: int | None = None
    raise_offset: int | None = None
    exception: BaseException | None = None

    def ready(self) -> None:
        if self.phase != "PRE_PERMIT":
            raise _deny(POST_PERMIT_TRACE_DENY, "trace was not ready before permit issuance")
        self.phase = "READY"

    def post_permit_check(self, current_thread_id: int | None = None) -> None:
        if self.phase != "READY":
            raise _deny(POST_PERMIT_TRACE_DENY, "trace readiness was not established before permit")
        if current_thread_id is not None and current_thread_id != self.plan["trace_thread_id"]:
            raise _deny(POST_PERMIT_TRACE_DENY, "trace thread binding changed")
        self.phase = "POST_PERMIT"

    def observe(self, event: str, *, offset: int | None = None) -> None:
        if event == "transaction_started":
            if offset != self.plan["transaction_call_offset"]:
                raise _deny(POST_PERMIT_TRACE_DENY, "transaction trace offset mismatch")
            if self.transaction_started:
                return
            self.transaction_started = True
        elif event == "writer_call_started":
            if offset != self.plan["writer_call_offset"]:
                raise _deny(POST_PERMIT_TRACE_DENY, "writer trace offset mismatch")
            if self.writer_call_started:
                return
            self.writer_call_started = True
        elif event == "return":
            if not isinstance(offset, int) or offset < 0:
                raise _deny(POST_PERMIT_TRACE_DENY, "return trace offset is missing")
            if self.writer_returned:
                return
            self.writer_returned = True
            self.return_offset = offset
        elif event == "raise":
            if not isinstance(offset, int) or offset < 0:
                raise _deny(POST_PERMIT_TRACE_DENY, "raise trace offset is missing")
            if self.writer_raised:
                return
            self.writer_raised = True
            self.raise_offset = offset
        else:
            raise _deny(POST_PERMIT_TRACE_DENY, "unknown writer trace event")
        self.events.append({
            "sequence": len(self.events) + 1,
            "event_kind": "opcode",
            "channel": "CPYTHON_OPCODE_TRACE_V1",
            "action": event,
            "module_path": provenance.safe_write_bytes.__module__,
            "source_ref": self.plan["provenance_source_ref"],
            "allowed": True,
            "offset": int(offset),
            "outcome": f"{event}@{offset}",
        })

    @property
    def trace_hash(self) -> str:
        return canonical_sha256({"events": self.events})


_RESOLUTION_TRACE_MATRIX_ROWS = (
    ("SNAPSHOT_READ", "OWNER_RECORD", "READ", True, "OWNER_RECORD_READ", "NULL", "NULL"),
    ("MODULE_LOOKUP", "CANDIDATE_LOADER", "READ", True, "OWNER_RECORD_READ", "MODULE_NAME", "NULL"),
    ("FINDER_CALL", "SYS_PATH", "CALL", False, "AMBIENT_DENY", "MODULE_NAME_OR_NULL", "NULL"),
    ("FINDER_CALL", "CWD", "CALL", False, "AMBIENT_DENY", "MODULE_NAME_OR_NULL", "NULL"),
    ("FINDER_CALL", "META_PATH", "CALL", False, "AMBIENT_DENY", "MODULE_NAME_OR_NULL", "NULL"),
    ("PATH_HOOK_CALL", "PATH_HOOKS", "CALL", False, "AMBIENT_DENY", "MODULE_NAME_OR_NULL", "NULL"),
    ("SYS_MODULES_REUSE", "SYS_MODULES", "REUSE", False, "FORBIDDEN_LOAD_DENY", "MODULE_NAME", "NULL"),
    ("BUILTIN_AMBIENT_LOAD", "BUILTIN", "LOAD", False, "AMBIENT_DENY", "MODULE_NAME", "NULL"),
    ("PERMITTED_LOAD", "CANDIDATE_LOADER", "ALLOW", True, "PERMITTED_LOAD", "MODULE_NAME", "OWNER_SOURCE_REF"),
    ("FORBIDDEN_LOAD", "CANDIDATE_LOADER", "DENY", False, "FORBIDDEN_LOAD_DENY", "MODULE_NAME", "NULL_OR_OWNER_SOURCE_REF"),
    ("TRACE_BACKEND_ERROR", "OWNER_RECORD", "ERROR", False, "TRACE_ERROR", "NULL", "NULL"),
)


def _resolution_matrix_hash() -> str:
    rows = [{
        "event_kind": row[0], "channel": row[1], "action": row[2], "allowed": row[3],
        "outcome": row[4], "module_path_rule": row[5], "source_ref_rule": row[6],
    } for row in _RESOLUTION_TRACE_MATRIX_ROWS]
    return canonical_sha256({"matrix_schema_version": "V1", "rows": rows, "complete": True, "status": "READY"}, fields=("matrix_schema_version", "rows", "complete", "status"))


def _collection_snapshot(*, kind: str, values: Sequence[str], value_type: str, owner_id: str, authority_ref: str, source_hash: str) -> dict[str, Any]:
    if kind not in RESOLUTION_COLLECTION_KINDS or value_type not in RESOLUTION_COLLECTION_VALUE_TYPES:
        raise _deny("DENIED_CAPABILITY", "unknown resolution collection kind or type")
    if not isinstance(values, (list, tuple)) or isinstance(values, (str, bytes)):
        raise _deny("DENIED_CAPABILITY", "resolution collection must be an explicit string array")
    _hash(source_hash, "evaluator_source_registry_snapshot_hash")
    if value_type == "RELATIVE_PATH_NFC_STRING":
        normalized = tuple(normalize_relative_path(value, allow_root=False) for value in values)
        if tuple(values) != normalized:
            raise _deny("DENIED_CAPABILITY", "resolution path collection is not canonical")
    else:
        normalized = tuple(values)
        if any(not isinstance(value, str) or not value or unicodedata.normalize("NFC", value) != value for value in normalized):
            raise _deny("DENIED_CAPABILITY", "resolution module collection is not canonical")
    ordered = _ordered(normalized, f"resolution.{kind}")
    entries = [_mapping({"entry_value": value}, RESOLUTION_COLLECTION_ENTRY_FIELDS, "resolution collection entry") for value in ordered]
    return _mapping({
        "collection_schema_version": "P1-RESOLUTION-COLLECTION-V1", "collection_kind": kind,
        "owner_id": owner_id, "authority_ref": authority_ref,
        "evaluator_source_registry_snapshot_hash": source_hash, "entry_value_type": value_type,
        "entries": entries, "complete": True, "status": "READY",
    }, RESOLUTION_COLLECTION_SNAPSHOT_FIELDS, "resolution collection snapshot")


def _nested_resolution_snapshot(*, kind: str, values: Sequence[str], owner_id: str, authority_ref: str, source_hash: str) -> dict[str, Any]:
    if kind not in {"SYS_PATH", "CWD", "META_PATH", "PATH_HOOKS", "SYS_MODULES"}:
        raise _deny("DENIED_CAPABILITY", "unknown nested resolution snapshot kind")
    if not isinstance(values, (list, tuple)) or isinstance(values, (str, bytes)):
        raise _deny("DENIED_CAPABILITY", "nested resolution snapshot must be an explicit string array")
    _hash(source_hash, "evaluator_source_registry_snapshot_hash")
    if any(not isinstance(value, str) or not value or unicodedata.normalize("NFC", value) != value for value in values):
        raise _deny("DENIED_CAPABILITY", "nested resolution snapshot contains a non-canonical value")
    ordered = _ordered(tuple(values), f"resolution.{kind}")
    entries = [_mapping({"entry_value": value}, RESOLUTION_COLLECTION_ENTRY_FIELDS, "nested resolution entry") for value in ordered]
    return _mapping({
        "snapshot_kind": kind, "snapshot_schema_version": "P1-RESOLUTION-NESTED-V1",
        "owner_id": owner_id, "authority_ref": authority_ref,
        "evaluator_source_registry_snapshot_hash": source_hash, "entries": entries,
        "complete": True, "status": "READY",
    }, RESOLUTION_NESTED_SNAPSHOT_FIELDS, "nested resolution snapshot")


def _resolution_object_identity(value: Any) -> str:
    """Return a stable, non-repr identity for a finder or path hook."""
    module = getattr(value, "__module__", None) or type(value).__module__
    qualname = getattr(value, "__qualname__", None) or type(value).__qualname__
    if not isinstance(module, str) or not isinstance(qualname, str) or not module or not qualname:
        raise _deny("DENIED_CAPABILITY", "resolution object has no stable owner identity")
    return f"{module}:{qualname}"


def live_resolution_identity_snapshot() -> dict[str, Any]:
    """Capture the actual ambient resolution state without loading anything."""
    raw_sys_path = tuple(str(item) for item in sys.path)
    raw_meta_path = tuple(_resolution_object_identity(item) for item in sys.meta_path)
    raw_path_hooks = tuple(_resolution_object_identity(item) for item in sys.path_hooks)
    if any(not item for item in raw_sys_path):
        raise _deny("DENIED_CAPABILITY", "empty sys.path entry is not attestable")
    # Preserve search-root order and duplicate instances instead of silently
    # collapsing them.  The index is part of the owner identity, so an added,
    # removed, reordered, or duplicated entry changes the snapshot.
    sys_path = tuple(sorted((f"{index}|{value}" for index, value in enumerate(raw_sys_path)), key=lambda item: item.encode("utf-8")))
    meta_path = tuple(sorted((f"{index}|{value}|{id(item)}" for index, (value, item) in enumerate(zip(raw_meta_path, sys.meta_path))), key=lambda item: item.encode("utf-8")))
    path_hooks = tuple(sorted((f"{index}|{value}|{id(item)}" for index, (value, item) in enumerate(zip(raw_path_hooks, sys.path_hooks))), key=lambda item: item.encode("utf-8")))
    modules = tuple(sorted(
        (f"{name}|{id(module)}" for name, module in sys.modules.items()), key=lambda item: item.encode("utf-8")
    ))
    return {
        "sys_path_snapshot": list(sys_path),
        "cwd_snapshot": os.getcwd(),
        "meta_path_snapshot": list(meta_path),
        "path_hooks_snapshot": list(path_hooks),
        "sys_modules_snapshot": list(modules),
    }


def _verify_live_resolution_guard(guard: Mapping[str, Any]) -> None:
    live = live_resolution_identity_snapshot()
    expected = {
        "sys_path_snapshot": list(guard["sys_path_snapshot"]),
        "cwd_snapshot": str(guard["cwd_snapshot"]),
        "meta_path_snapshot": list(guard["meta_path_snapshot"]),
        "path_hooks_snapshot": list(guard["path_hooks_snapshot"]),
        "sys_modules_snapshot": list(guard["sys_modules_snapshot"]),
    }
    if live != expected:
        raise _deny("DENIED_CAPABILITY", "live resolution state differs from the owner snapshot")


def _bootstrap_record(value: Mapping[str, Any], *, name: str = "bootstrap module entry") -> dict[str, Any]:
    item = _mapping(value, BOOTSTRAP_MODULE_ENTRY_FIELDS, name)
    if not isinstance(item["module_path"], str) or not item["module_path"] or unicodedata.normalize("NFC", item["module_path"]) != item["module_path"]:
        raise _deny("DENIED_CAPABILITY", "bootstrap module path is not canonical")
    for field_name in ("resolved_path", "source_ref", "spec_origin", "runtime_identity_hash"):
        if not isinstance(item[field_name], str) or not item[field_name]:
            raise _deny("DENIED_CAPABILITY", f"bootstrap {field_name} is missing")
    if not isinstance(item["source_length"], int) or isinstance(item["source_length"], bool) or item["source_length"] < 0:
        raise _deny("DENIED_CAPABILITY", "bootstrap source length is invalid")
    if not isinstance(item["module_identity"], int) or isinstance(item["module_identity"], bool) or item["module_identity"] <= 0:
        raise _deny("DENIED_CAPABILITY", "bootstrap module identity is invalid")
    _hash(item["source_sha256"], "bootstrap source sha256")
    _hash(item["readback_sha256"], "bootstrap readback sha256")
    _hash(item["runtime_identity_hash"], "bootstrap runtime identity hash")
    if item["source_sha256"] != item["readback_sha256"]:
        raise _deny("DENIED_PROVENANCE", "bootstrap source/readback hash differs")
    return item


BOOTSTRAP_OWNER_BINDING_FIELDS = (
    "module_path", "resolved_path", "source_relative_path", "source_ref", "source_length",
    "source_sha256", "readback_sha256", "module_identity", "spec_origin", "runtime_identity_hash",
)


def _owner_bound_bootstrap_records(
    values: Sequence[Mapping[str, Any]],
    *,
    source_registry: EvaluatorSourceRegistryV1,
    source_root: Path | None,
) -> tuple[dict[str, Any], ...]:
    records: list[dict[str, Any]] = []
    if values and source_root is None:
        raise _deny("DENIED_PROVENANCE", "bootstrap source root is required")
    for index, raw in enumerate(values):
        record = _bootstrap_record(raw, name=f"bootstrap module entry[{index}]")
        matches = [
            dict(entry) for entry in source_registry.value["entries"]
            if entry["source_role"] == "bootstrap" and entry["source_ref"] == record["source_ref"]
        ]
        if len(matches) != 1:
            raise _deny("DENIED_PROVENANCE", "bootstrap record has no unique owner source entry")
        source_entry = matches[0]
        if (record["source_length"], record["source_sha256"], record["readback_sha256"]) != (
            source_entry["length"], source_entry["sha256"], source_entry["sha256"]
        ):
            raise _deny("DENIED_PROVENANCE", "bootstrap source binding differs from owner registry")
        source_path = _final_path(Path(source_root) / source_entry["relative_path"], Path(source_root), must_exist=True)
        raw_source = _strict_bytes(source_path.read_bytes(), "bootstrap source")
        source_registry.verify_bytes(source_entry, raw_source)
        binding = dict(record)
        binding["source_relative_path"] = source_entry["relative_path"]
        records.append(_mapping(binding, BOOTSTRAP_OWNER_BINDING_FIELDS, "owner bootstrap binding"))
    return tuple(records)


def _build_resolution_live_snapshot(*, guard: Mapping[str, Any], gate: P1PreImportGateV1, census: P1CapabilityCensusV1, source_registry: EvaluatorSourceRegistryV1, source_root: Path | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    guard = _mapping(guard, RESOLUTION_GUARD_FIELDS, "resolution guard")
    _verify_live_resolution_guard(guard)
    owner_id = source_registry.value["owner_id"]
    authority_ref = source_registry.value["authoritative_source_ref"]
    if gate.value["owner_id"] != owner_id or gate.value["authority_ref"] != authority_ref:
        raise _deny("DENIED_PROVENANCE", "resolution owner authority differs from gate")
    if guard["owner_id"] != owner_id or guard["authority_ref"] != authority_ref:
        raise _deny("DENIED_PROVENANCE", "resolution owner authority differs from guard")
    source_hash = _evaluator_source_snapshot_hash(source_registry)
    candidate_modules = tuple(gate.value["candidate_modules"])
    census_entries = tuple(census.value["entries"])
    census_modules = tuple(item["module_path"] for item in census_entries)
    static_allowlist = set(gate.value["static_module_allowlist"])
    if not set(candidate_modules).issubset(static_allowlist):
        raise _deny("DENIED_CAPABILITY", "candidate modules are outside static allowlist")
    static_modules = set(census_modules) - set(candidate_modules)
    if not static_modules.issubset(static_allowlist):
        raise _deny("DENIED_CAPABILITY", "static/transitive modules are outside static allowlist")
    for census_entry in census_entries:
        if census_entry["module_path"] not in set(candidate_modules) | static_modules:
            raise _deny("DENIED_CAPABILITY", "census module is not in candidate/static closure")
        source = source_registry.entry_for(census_entry["source_relative_path"])
        if source["source_role"] not in {"candidate", "static"} or (source["source_ref"], source["length"], source["sha256"]) != (census_entry["source_ref"], census_entry["source_length"], census_entry["source_sha256"]):
            raise _deny("DENIED_PROVENANCE", "census source binding differs")
        closure = set(census_entry["transitive_modules"])
        if not closure.issubset(set(candidate_modules) | static_modules):
            raise _deny("DENIED_CAPABILITY", "census transitive closure escapes owner static closure")
    candidate_paths_list: list[str] = []
    for module_path in candidate_modules:
        item = next((entry for entry in census_entries if entry["module_path"] == module_path), None)
        if item is None:
            raise _deny("DENIED_CAPABILITY", "candidate module has no census entry")
        source = source_registry.entry_for(item["source_relative_path"])
        if (source["source_ref"], source["length"], source["sha256"]) != (item["source_ref"], item["source_length"], item["source_sha256"]):
            raise _deny("DENIED_PROVENANCE", "candidate source collection binding differs")
        candidate_paths_list.append(item["source_relative_path"])
    candidate_paths = tuple(candidate_paths_list)
    bootstrap_records = list(_owner_bound_bootstrap_records(
        guard["bootstrap_module_entries"], source_registry=source_registry, source_root=source_root,
    ))
    bootstrap_values = [record["module_path"] for record in bootstrap_records]
    bootstrap = tuple(bootstrap_values)
    preloaded_modules = tuple(guard["preloaded_candidate_modules"])
    preloaded_paths = tuple(guard["preloaded_candidate_source_paths"])
    if preloaded_modules or preloaded_paths:
        raise _deny("DENIED_CAPABILITY", "preloaded candidate modules or source aliases are forbidden")
    collections = {
        "CANDIDATE_MODULE_SET": _collection_snapshot(kind="CANDIDATE_MODULE_SET", values=candidate_modules, value_type="MODULE_NAME_NFC_STRING", owner_id=owner_id, authority_ref=authority_ref, source_hash=source_hash),
        "CANDIDATE_SOURCE_PATH_SET": _collection_snapshot(kind="CANDIDATE_SOURCE_PATH_SET", values=candidate_paths, value_type="RELATIVE_PATH_NFC_STRING", owner_id=owner_id, authority_ref=authority_ref, source_hash=source_hash),
        "BOOTSTRAP_MODULE_SET": _collection_snapshot(kind="BOOTSTRAP_MODULE_SET", values=bootstrap, value_type="MODULE_NAME_NFC_STRING", owner_id=owner_id, authority_ref=authority_ref, source_hash=source_hash),
        "PRELOADED_CANDIDATE_MODULES": _collection_snapshot(kind="PRELOADED_CANDIDATE_MODULES", values=preloaded_modules, value_type="MODULE_NAME_NFC_STRING", owner_id=owner_id, authority_ref=authority_ref, source_hash=source_hash),
        "PRELOADED_CANDIDATE_SOURCE_PATHS": _collection_snapshot(kind="PRELOADED_CANDIDATE_SOURCE_PATHS", values=preloaded_paths, value_type="RELATIVE_PATH_NFC_STRING", owner_id=owner_id, authority_ref=authority_ref, source_hash=source_hash),
    }
    nested = {
        "SYS_PATH": _nested_resolution_snapshot(kind="SYS_PATH", values=tuple(guard["sys_path_snapshot"]), owner_id=owner_id, authority_ref=authority_ref, source_hash=source_hash),
        "CWD": _nested_resolution_snapshot(kind="CWD", values=(str(guard["cwd_snapshot"]),), owner_id=owner_id, authority_ref=authority_ref, source_hash=source_hash),
        "META_PATH": _nested_resolution_snapshot(kind="META_PATH", values=tuple(str(item) for item in guard["meta_path_snapshot"]), owner_id=owner_id, authority_ref=authority_ref, source_hash=source_hash),
        "PATH_HOOKS": _nested_resolution_snapshot(kind="PATH_HOOKS", values=tuple(str(item) for item in guard["path_hooks_snapshot"]), owner_id=owner_id, authority_ref=authority_ref, source_hash=source_hash),
        "SYS_MODULES": _nested_resolution_snapshot(kind="SYS_MODULES", values=tuple(guard["sys_modules_snapshot"]), owner_id=owner_id, authority_ref=authority_ref, source_hash=source_hash),
    }
    collection_hashes = {kind: canonical_sha256(snapshot, fields=RESOLUTION_COLLECTION_SNAPSHOT_FIELDS) for kind, snapshot in collections.items()}
    nested_hashes = {kind: canonical_sha256(snapshot, fields=RESOLUTION_NESTED_SNAPSHOT_FIELDS) for kind, snapshot in nested.items()}
    trace = [{
        "sequence": 0, "event_kind": "SNAPSHOT_READ", "channel": "OWNER_RECORD", "action": "READ",
        "module_path": None, "source_ref": None, "allowed": True, "outcome": "OWNER_RECORD_READ",
    }]
    trace = [_mapping(item, DETERMINISTIC_TRACE_EVENT_FIELDS, "resolution trace event") for item in trace]
    if tuple(item["sequence"] for item in trace) != tuple(range(len(trace))):
        raise _deny("DENIED_CAPABILITY", "resolution trace sequence is incomplete")
    matrix_hash = _resolution_matrix_hash()
    live = _mapping({
        "snapshot_schema_version": "P1-RESOLUTION-LIVE-V1", "owner_id": owner_id, "authority_ref": authority_ref,
        "evaluator_source_registry_snapshot_hash": source_hash,
        "candidate_module_set": list(candidate_modules), "candidate_module_set_hash": collection_hashes["CANDIDATE_MODULE_SET"],
        "candidate_source_path_set": list(candidate_paths), "candidate_source_path_set_hash": collection_hashes["CANDIDATE_SOURCE_PATH_SET"],
        "bootstrap_module_set": list(bootstrap), "bootstrap_module_set_hash": collection_hashes["BOOTSTRAP_MODULE_SET"],
        "preloaded_candidate_modules": list(preloaded_modules), "preloaded_candidate_modules_hash": collection_hashes["PRELOADED_CANDIDATE_MODULES"],
        "preloaded_candidate_source_paths": list(preloaded_paths), "preloaded_candidate_source_paths_hash": collection_hashes["PRELOADED_CANDIDATE_SOURCE_PATHS"],
        "sys_path_snapshot_hash": nested_hashes["SYS_PATH"], "cwd_snapshot_hash": nested_hashes["CWD"],
        "meta_path_snapshot_hash": nested_hashes["META_PATH"], "path_hooks_snapshot_hash": nested_hashes["PATH_HOOKS"],
        "sys_modules_snapshot_hash": nested_hashes["SYS_MODULES"], "resolution_trace_compatibility_matrix_hash": matrix_hash,
        "resolution_trace": trace, "complete": True, "status": "READY",
    }, RESOLUTION_LIVE_SNAPSHOT_FIELDS, "resolution live snapshot")
    return live, {"collections": collections, "nested": nested, "collection_hashes": collection_hashes, "nested_hashes": nested_hashes}


def _validate_capability_probe_snapshot(snapshot: Mapping[str, Any], source_registry: EvaluatorSourceRegistryV1) -> None:
    """Validate owner observations independently of P0 call counters."""
    value = _mapping(snapshot, CAPABILITY_PROBE_SNAPSHOT_FIELDS, "capability probe snapshot")
    if value["owner_id"] != source_registry.value["owner_id"] or value["authority_ref"] != source_registry.value["authoritative_source_ref"]:
        raise _deny("DENIED_CAPABILITY", "capability observation owner binding differs")
    if value["evaluator_source_registry_snapshot_hash"] != _evaluator_source_snapshot_hash(source_registry):
        raise _deny("DENIED_CAPABILITY", "capability observation source snapshot is stale")
    if value["owner_probe_schema_version"] != "P1-OWNER-PROBE-BINDING-V1" or value["owner_probe_qualname"] != P1CapabilityObserver.owner_attestation.__qualname__:
        raise _deny("DENIED_CAPABILITY", "owner probe schema or qualname differs")
    validate_hash(value["owner_probe_code_sha256"], field="owner_probe_code_sha256")
    validate_hash(value["owner_probe_source_sha256"], field="owner_probe_source_sha256")
    if not isinstance(value["owner_probe_source_length"], int) or value["owner_probe_source_length"] < 0:
        raise _deny("DENIED_CAPABILITY", "owner probe source length is invalid")
    owner_source = source_registry.entry_for(value["owner_probe_source_relative_path"])
    if owner_source["source_role"] != "evaluator" or (value["owner_probe_source_ref"], value["owner_probe_source_length"], value["owner_probe_source_sha256"]) != (owner_source["source_ref"], owner_source["length"], owner_source["sha256"]):
        raise _deny("DENIED_CAPABILITY", "owner probe source binding differs")
    if value["forbidden_capabilities"] != list(P1_FORBIDDEN_CAPABILITIES):
        raise _deny("DENIED_CAPABILITY", "owner probe forbidden capability set differs")
    coverage = value["candidate_source_coverage"]
    if not isinstance(coverage, list):
        raise _deny("DENIED_CAPABILITY", "owner probe source coverage is not an array")
    previous: bytes | None = None
    seen_coverage: set[str] = set()
    for index, record in enumerate(coverage):
        item = _mapping(record, CAPABILITY_PROBE_COVERAGE_FIELDS, f"owner probe source coverage[{index}]")
        if item["source_role"] not in {"candidate", "static"}:
            raise _deny("DENIED_CAPABILITY", "owner probe source coverage role is invalid")
        path_key = normalize_relative_path(item["source_relative_path"], allow_root=False).encode("utf-8")
        if previous is not None and path_key <= previous:
            raise _deny("DENIED_CAPABILITY", "owner probe source coverage is unsorted or duplicated")
        previous = path_key
        if item["source_relative_path"] in seen_coverage:
            raise _deny("DENIED_CAPABILITY", "owner probe source coverage is duplicated")
        seen_coverage.add(item["source_relative_path"])
        source = source_registry.entry_for(item["source_relative_path"])
        if (item["source_role"], item["source_ref"], item["source_length"], item["source_sha256"]) != (source["source_role"], source["source_ref"], source["length"], source["sha256"]):
            raise _deny("DENIED_CAPABILITY", "owner probe source coverage binding differs")
    expected_coverage = [
        {"source_role": entry["source_role"], "source_relative_path": entry["relative_path"],
         "source_ref": entry["source_ref"], "source_length": entry["length"],
         "source_sha256": entry["sha256"]}
        for entry in source_registry.value["entries"] if entry["source_role"] in {"candidate", "static"}
    ]
    if coverage != expected_coverage:
        raise _deny("DENIED_CAPABILITY", "owner probe source coverage is incomplete")
    if value["candidate_source_coverage_hash"] != canonical_sha256({"entries": coverage}, fields=("entries",)):
        raise _deny("DENIED_PROVENANCE", "owner probe source coverage hash mismatch")
    records = value["records"]
    if not isinstance(records, list) or tuple(item.get("capability") for item in records if isinstance(item, Mapping)) != tuple(P1_FORBIDDEN_CAPABILITIES):
        raise _deny("DENIED_CAPABILITY", "capability observation records are missing, duplicated or reordered")
    operation_catalog_hash = sha256_bytes(canonical_evaluation_json_bytes({"capabilities": list(P1_FORBIDDEN_CAPABILITIES)}, fields=("capabilities",)))
    for record in records:
        item = _mapping(record, CAPABILITY_PROBE_RECORD_FIELDS, "capability probe record")
        source = source_registry.entry_for(item["owner_source_relative_path"])
        if (item["owner_source_ref"], item["owner_source_length"], item["owner_source_sha256"]) != (source["source_ref"], source["length"], source["sha256"]):
            raise _deny("DENIED_CAPABILITY", "capability observation source bytes are not owner-bound")
        if item["operation_catalog_hash"] != operation_catalog_hash or item["covered_operation_ids"] != [item["capability"]]:
            raise _deny("DENIED_CAPABILITY", "capability observation operation catalog differs")
        if item["observation_method"] != "OWNER_BOUNDARY_PROBE" or item["installed"] is not True or item["complete"] is not True:
            raise _deny("DENIED_CAPABILITY", "capability observation was not installed and complete")
        if not isinstance(item["observed_call_count"], int) or isinstance(item["observed_call_count"], bool) or item["observed_call_count"] != 0:
            raise _deny("DENIED_CAPABILITY", "forbidden capability call observation is non-zero")
        if not isinstance(item["observed_deny_count"], int) or isinstance(item["observed_deny_count"], bool) or item["observed_deny_count"] < 0:
            raise _deny("DENIED_CAPABILITY", "capability deny count is invalid")
        if item["status"] != "READY":
            raise _deny("DENIED_CAPABILITY", "capability observation is not READY")
    if value["complete"] is not True or value["status"] != "READY":
        raise _deny("DENIED_CAPABILITY", "capability observation snapshot is not complete and READY")


class OwnerHarness:
    """Owner-side admission, permit issuance and explicit-source module loading."""

    def __init__(
        self,
        *,
        source_registry: EvaluatorSourceRegistryV1,
        census: P1CapabilityCensusV1,
        gate: P1PreImportGateV1,
        resolution_guard: Mapping[str, Any],
        writer_trace_plan: Mapping[str, Any],
        source_root: Path,
        owner_session_id: str,
        seal_key: bytes,
        observer: P1CapabilityObserver | None = None,
    ) -> None:
        self.source_registry = source_registry
        self.census = census
        self.gate = gate
        self.resolution_guard = _mapping(resolution_guard, (
            "guard_schema_version", "guard_id", "owner_id", "authority_ref", "sys_path_snapshot",
            "cwd_snapshot", "meta_path_snapshot", "path_hooks_snapshot", "sys_modules_snapshot",
            "candidate_closure_modules", "preloaded_candidate_modules", "preloaded_candidate_source_paths",
            "bootstrap_module_entries", "read_only", "deny_sys_path_read", "deny_cwd_read",
            "deny_fallback_finder", "deny_sys_modules_reuse", "deny_builtin_ambient_load",
        ), "resolution guard")
        self.writer_trace_plan = dict(writer_trace_plan)
        self.source_root = _final_path(Path(source_root), Path(source_root))
        self.owner_session_id = owner_session_id
        self.seal_key = bytes(seal_key)
        if observer is not None:
            raise _deny("DENIED_CAPABILITY", "owner observer must be owner-injected")
        self.observer = P1CapabilityObserver()
        self._owner_observer = self.observer
        self._owner_probe_binding = owner_probe_binding_snapshot(
            owner_id=self.source_registry.value["owner_id"],
            authority_ref=self.source_registry.value["authoritative_source_ref"],
            source_registry=self.source_registry, source_root=self.source_root,
        )
        self._owner_probe_binding_hash = canonical_sha256(self._owner_probe_binding, fields=OWNER_PROBE_BINDING_FIELDS)
        self._lock = RLock()
        self._sentinel = object()
        # The registry is authoritative for single-use state.  The public
        # ``consumed`` bit is only a redundant diagnostic and cannot be used
        # to revive or copy a permit.
        self._issued: dict[int, dict[str, Any]] = {}
        # The pure loader can only reach an authority registry bound by an
        # owner-side transaction.  Raw records/authority bytes are not part of
        # the OwnerHarness constructor and therefore cannot be caller-injected.
        self._p1ae_annotation_registry = None
        self._p1ae_authority_source = None
        self._p1ae_authority_readback = None
        self._p1ae_post_write_evidence = None
        self._p1ae_last_post_write_evidence = None
        self._p1ae_cpython_internal_expected_allowlist = None
        self.loaded_bindings: tuple[dict[str, Any], ...] = ()
        self.permitted_candidate_load_count = 0
        self.runtime_attestation = runtime_attestation(thread_id=threading.get_ident())
        self.runtime_identity = runtime_identity_snapshot()
        self._trace_attestation: dict[str, Any] | None = None
        self.writer_phase_observation: dict[str, Any] | None = None
        self.capability_probe_snapshot: dict[str, Any] | None = None
        self._resolution_live_snapshot: dict[str, Any] | None = None
        self._resolution_support: dict[str, Any] | None = None
        self._input_manifest_hash = "0" * 64
        self._input_binding_hash = "0" * 64
        self._owner_manifest: dict[str, Any] | None = None
        self._owner_manifest_source: tuple[str, str, bytes] | None = None
        self._test_manifest_source_allowed = False
        self._owner_writer_observation_bytes: bytes | None = None
        self._owner_writer_observation: dict[str, Any] | None = None
        self._writer_invocation_records: tuple[dict[str, Any], ...] = ()
        self._writer_trace_events: tuple[dict[str, Any], ...] = ()
        self._writer_expected_artifacts: dict[str, provenance.ArtifactRef] = {}
        self._writer_expected_final_paths: dict[str, str] = {}
        self._admit()

    @property
    def resolution_guard_snapshot_hash(self) -> str:
        return canonical_sha256(self.resolution_guard)

    @property
    def resolution_live_snapshot_hash(self) -> str:
        if self._resolution_live_snapshot is None:
            raise _deny("DENIED_PROVENANCE", "resolution live snapshot is unavailable")
        return canonical_sha256(self._resolution_live_snapshot, fields=RESOLUTION_LIVE_SNAPSHOT_FIELDS)

    @property
    def capability_probe_snapshot_hash(self) -> str:
        if self.capability_probe_snapshot is None:
            raise _deny("DENIED_CAPABILITY", "capability owner observation is unavailable")
        return canonical_sha256(self.capability_probe_snapshot, fields=CAPABILITY_PROBE_SNAPSHOT_FIELDS)

    @property
    def pre_permit_attestation_v15_hash(self) -> str:
        return canonical_sha256(self._v15_attestation(), fields=PRE_PERMIT_ATTESTATION_V15_FIELDS)

    def _v15_attestation(self) -> dict[str, Any]:
        if self._trace_attestation is None:
            raise _deny("DENIED_PROVENANCE", "pre-permit attestation is unavailable")
        return _mapping({
            "attestation_schema_version": "P1-PRE-PERMIT-ATTESTATION-V15",
            "authority_ref": self.gate.value["authority_ref"], "owner_id": self.gate.value["owner_id"],
            "cpython_runtime_snapshot_hash": self.writer_trace_plan["runtime_snapshot_hash"],
            "writer_trace_plan_snapshot_hash": self.writer_trace_plan_snapshot_hash,
            "marker_purity_snapshot_hash": self.writer_trace_plan["marker_purity_hash"],
            "capability_probe_snapshot_hash": self.capability_probe_snapshot_hash,
            "resolution_live_snapshot_hash": self.resolution_live_snapshot_hash,
            "input_binding_hash": self._input_binding_hash, "input_manifest_hash": self._input_manifest_hash,
            "trace_thread_binding": self.writer_trace_plan["trace_thread_id"],
            "hook_install_status": "VERIFIED", "opcode_trace_support": True,
            "event_delivery_status": self._trace_attestation.get("event_delivery_status", "VERIFIED"),
            "trace_replacement_guard_status": "VERIFIED",
            "attestation_status": self._trace_attestation.get("status", "DENY"),
        }, PRE_PERMIT_ATTESTATION_V15_FIELDS, "pre-permit V15 attestation")

    def _owner_inject_manifest_source(self, *, relative_path: str, source_ref: str, content: bytes) -> None:
        """Prepare an owner-only test manifest source.

        This method is never an evaluation authority.  Normal binding requires
        a unique ``source_role=manifest`` entry in the immutable source
        registry; the injected bytes are accepted only by explicit standalone
        test preparation below.
        """
        with self._lock:
            if self._owner_manifest is not None or self._owner_manifest_source is not None:
                raise _deny("DENIED_PROVENANCE", "owner manifest source is already bound")
            canonical_path = normalize_relative_path(relative_path, allow_root=False)
            if not isinstance(source_ref, str) or not source_ref or not isinstance(content, bytes):
                raise _deny("DENIED_PROVENANCE", "owner manifest source metadata is incomplete")
            self._owner_manifest_source = (canonical_path, source_ref, _strict_bytes(content, "owner manifest source bytes"))

    def _validate_input_adapter_binding(
        self,
        manifest: EvaluationInputManifestV1,
        adapter_records: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        if len(adapter_records) != 1:
            raise _deny("DENIED_PROVENANCE", "exactly one owner input artifact adapter is required")
        try:
            expected_lineage = p0_artifact_lineage(manifest.input_artifact_identity)
            verify_p0_lineage_integrity(expected_lineage)
            expected_adapter = p0_to_p1_input_lineage_adapter(expected_lineage)
        except Exception as exc:
            raise _deny("DENIED_PROVENANCE", "manifest input lineage is not a valid P0 record") from exc
        actual_adapter = dict(adapter_records[0])
        if tuple(actual_adapter) != P0_TO_P1_INPUT_LINEAGE_ADAPTER_FIELDS:
            raise _deny("DENIED_PROVENANCE", "input adapter fields are not exact")
        expected_bytes = canonical_evaluation_json_bytes(expected_adapter, fields=P0_TO_P1_INPUT_LINEAGE_ADAPTER_FIELDS)
        actual_bytes = canonical_evaluation_json_bytes(actual_adapter, fields=P0_TO_P1_INPUT_LINEAGE_ADAPTER_FIELDS)
        if actual_bytes != expected_bytes:
            raise _deny("DENIED_PROVENANCE", "input adapter does not byte-match manifest lineage")
        actual_lineage = p0_artifact_lineage(actual_adapter["p0_artifact_lineage"])
        if tuple(actual_lineage) != P0_ARTIFACT_LINEAGE_FIELDS:
            raise _deny("DENIED_PROVENANCE", "input lineage fields are not exact")
        verify_p0_lineage_integrity(actual_lineage)
        if actual_lineage["parent_refs"] != expected_lineage["parent_refs"]:
            raise _deny("DENIED_PROVENANCE", "input parent order changed")
        for field_name in (
            "project_id", "profile_id", "profile_version", "profile_definition_hash",
            "project_revision", "namespace_digest", "root_alias",
        ):
            if actual_lineage[field_name] != expected_lineage[field_name] or actual_lineage[field_name] != manifest.input_artifact_identity[field_name]:
                raise _deny("DENIED_PROVENANCE", f"input lineage {field_name} mismatch")
        if actual_lineage["source_ref"] != expected_lineage["source_ref"] or actual_lineage["relative_path"] != expected_lineage["relative_path"]:
            raise _deny("DENIED_PROVENANCE", "input source or relative path mismatch")
        if actual_lineage["content_length"] != expected_lineage["content_length"] or actual_lineage["content_sha256"] != expected_lineage["content_sha256"] or actual_lineage["integrity_digest"] != expected_lineage["integrity_digest"]:
            raise _deny("DENIED_PROVENANCE", "input content or integrity mismatch")
        if actual_lineage["root_alias"] != self.source_registry.value["source_root_alias"]:
            raise _deny("DENIED_PROVENANCE", "input root alias is not owner-bound")
        for parent_ref in actual_lineage["parent_refs"]:
            if not isinstance(parent_ref, str) or not parent_ref:
                raise _deny("DENIED_PROVENANCE", "input parent reference is incomplete")
        return actual_adapter

    def bind_input_manifest(
        self,
        manifest: EvaluationInputManifestV1,
        adapters: Sequence[Mapping[str, Any]],
        declared_output_relative_paths: Sequence[str],
    ) -> str:
        """Bind only the immutable registry manifest and one input adapter."""
        return self._bind_input_manifest(manifest, adapters, declared_output_relative_paths, _owner_test_seam=None)

    def _bind_standalone_test_manifest(
        self,
        manifest: EvaluationInputManifestV1,
        declared_output_relative_paths: Sequence[str],
    ) -> str:
        """Owner-only preparation seam for registry-less contract unit tests."""
        return self._bind_input_manifest(manifest, [], declared_output_relative_paths, _owner_test_seam=_OWNER_TEST_SEAM)

    def _bind_input_manifest(
        self,
        manifest: EvaluationInputManifestV1,
        adapters: Sequence[Mapping[str, Any]],
        declared_output_relative_paths: Sequence[str],
        *,
        _owner_test_seam: object | None,
    ) -> str:
        """Owner-read and rehash the manifest before permit issuance."""
        test_seam = _owner_test_seam is _OWNER_TEST_SEAM
        with self._lock:
            if not isinstance(manifest, EvaluationInputManifestV1):
                raise _deny("DENIED_INPUT", "owner manifest must be a typed manifest")
            raw = _strict_bytes(manifest.canonical_bytes, "owner manifest bytes")
            readback = parse_canonical_evaluation_json(raw, fields=EVALUATION_INPUT_MANIFEST_FIELDS)
            if readback != manifest.to_mapping():
                raise _deny("DENIED_PROVENANCE", "owner manifest readback differs")
            adapter_records = [
                dict(item) if isinstance(item, Mapping) and tuple(item) == ("p0_artifact_lineage", "p0_artifact_ref_preimage")
                else p0_to_p1_input_lineage_adapter(item)
                for item in adapters
            ]
            if not adapter_records and not test_seam:
                raise _deny("DENIED_PROVENANCE", "input artifact adapter is missing")
            if adapter_records:
                self._validate_input_adapter_binding(manifest, adapter_records)
            elif not test_seam:
                raise _deny("DENIED_PROVENANCE", "empty input adapter is test-only")
            if test_seam:
                paths = [normalize_relative_path(path, allow_root=False) for path in declared_output_relative_paths]
                if list(declared_output_relative_paths) != paths or len(set(paths)) != len(paths):
                    raise _deny("PATH_ESCAPE", "owner manifest output path is not canonical")
            else:
                paths = list(validate_evaluation_output_role_order(declared_output_relative_paths))
            manifest_entries = [item for item in self.source_registry.value["entries"] if item["source_role"] == "manifest"]
            if len(manifest_entries) > 1:
                raise _deny("DENIED_PROVENANCE", "owner manifest source is not unique")
            source_entry = manifest_entries[0] if manifest_entries else None
            if source_entry is not None:
                _, owner_source_bytes = self._source_path(source_entry)
                if owner_source_bytes != raw:
                    raise _deny("DENIED_PROVENANCE", "owner manifest source readback differs")
                source_relative_path = source_entry["relative_path"]
                source_ref = source_entry["source_ref"]
            else:
                if not test_seam or self._owner_manifest_source is None:
                    raise _deny("MISSING_OWNER_MANIFEST", "owner manifest source is required before permit issuance")
                source_relative_path, source_ref, owner_source_bytes = self._owner_manifest_source
                if owner_source_bytes != raw:
                    raise _deny("DENIED_PROVENANCE", "owner manifest source readback differs")
                self._test_manifest_source_allowed = True
            owner_record = {
                "manifest_schema_version": "P1-OWNER-INPUT-MANIFEST-V1", "owner_id": self.gate.value["owner_id"],
                "authority_ref": self.gate.value["authority_ref"], "source_relative_path": source_relative_path,
                "source_ref": source_ref, "source_length": len(raw), "source_sha256": sha256_bytes(raw),
                "manifest_bytes_utf8_hex": raw.hex(), "input_artifact_lineage_records": adapter_records,
                "declared_output_relative_paths": list(paths), "read_only": True,
            }
            if owner_record["source_length"] != len(raw) or owner_record["source_sha256"] != sha256_bytes(raw):
                raise _deny("DENIED_PROVENANCE", "owner manifest source readback mismatch")
            owner_hash = canonical_sha256(owner_record, fields=OWNER_INPUT_MANIFEST_FIELDS)
            self._owner_manifest = _mapping(owner_record, OWNER_INPUT_MANIFEST_FIELDS, "owner input manifest")
            self._input_manifest_hash = owner_hash
            self._input_binding_hash = input_binding_hash(adapter_records, self._input_manifest_hash)
            return owner_hash

    def _recheck_owner_manifest(self) -> None:
        """Re-read/recompute the owner manifest immediately before permit issuance."""
        if self._owner_manifest is None:
            raise _deny("MISSING_OWNER_MANIFEST", "owner manifest is required before permit issuance")
        record = _mapping(self._owner_manifest, OWNER_INPUT_MANIFEST_FIELDS, "owner input manifest")
        try:
            raw = bytes.fromhex(record["manifest_bytes_utf8_hex"])
        except (TypeError, ValueError) as exc:
            raise _deny("DENIED_PROVENANCE", "owner manifest bytes are not canonical hex") from exc
        raw = _strict_bytes(raw, "owner manifest bytes")
        if record["source_length"] != len(raw) or record["source_sha256"] != sha256_bytes(raw):
            raise _deny("DENIED_PROVENANCE", "owner manifest source length/hash changed")
        manifest_value = parse_canonical_evaluation_json(raw, fields=EVALUATION_INPUT_MANIFEST_FIELDS)
        manifest_obj = EvaluationInputManifestV1.from_mapping(manifest_value)
        adapter_records = record["input_artifact_lineage_records"]
        if adapter_records:
            self._validate_input_adapter_binding(manifest_obj, adapter_records)
        elif not self._test_manifest_source_allowed:
            raise _deny("DENIED_PROVENANCE", "owner input adapter disappeared before permit")
        manifest_hash = canonical_sha256(record, fields=OWNER_INPUT_MANIFEST_FIELDS)
        if manifest_hash != self._input_manifest_hash:
            raise _deny("DENIED_PROVENANCE", "owner manifest hash changed before permit")
        manifest_entries = [item for item in self.source_registry.value["entries"] if item["source_role"] == "manifest"]
        if len(manifest_entries) == 1:
            source_entry = manifest_entries[0]
            if (record["source_relative_path"], record["source_ref"]) != (source_entry["relative_path"], source_entry["source_ref"]):
                raise _deny("DENIED_PROVENANCE", "owner manifest source registry identity changed")
            _, owner_source_bytes = self._source_path(source_entry)
            if owner_source_bytes != raw:
                raise _deny("DENIED_PROVENANCE", "owner manifest source readback changed")
        elif len(manifest_entries) == 0 and self._test_manifest_source_allowed and self._owner_manifest_source is not None:
            source_path, source_ref, owner_source_bytes = self._owner_manifest_source
            if (record["source_relative_path"], record["source_ref"]) != (source_path, source_ref) or owner_source_bytes != raw:
                raise _deny("DENIED_PROVENANCE", "owner-only test manifest source changed")
        else:
            raise _deny("DENIED_PROVENANCE", "owner manifest source entry disappeared or is not unique")
        if input_binding_hash(record["input_artifact_lineage_records"], manifest_hash) != self._input_binding_hash:
            raise _deny("DENIED_PROVENANCE", "owner input binding changed before permit")

    @property
    def writer_trace_plan_snapshot_hash(self) -> str:
        return canonical_sha256(self.writer_trace_plan)

    def _validate_trace_plan(self) -> None:
        if tuple(self.writer_trace_plan) != WRITER_TRACE_PLAN_FIELDS:
            raise _deny("DENIED_PROVENANCE", "writer trace plan fields are not exact")
        if self.writer_trace_plan["trace_backend"] != "CPYTHON_OPCODE_TRACE_V1":
            raise _deny("DENIED_PROVENANCE", "external CPython opcode trace backend is required")
        if self.writer_trace_plan["trace_thread_id"] != threading.get_ident():
            raise _deny("DENIED_PROVENANCE", "writer trace thread binding differs")
        expected = build_writer_trace_plan(
            owner_id=self.writer_trace_plan["owner_id"],
            authority_ref=self.writer_trace_plan["authority_ref"],
            provenance_source_ref=self.writer_trace_plan["provenance_source_ref"],
            trace_thread_id=threading.get_ident(),
        )
        for field_name in WRITER_TRACE_PLAN_FIELDS:
            if self.writer_trace_plan[field_name] != expected[field_name]:
                raise _deny("DENIED_PROVENANCE", "writer trace plan is stale or forged", field=field_name)

    def _validate_owner_writer_observation(self, observation: Mapping[str, Any]) -> dict[str, Any]:
        """Validate writer events against the owner-captured trace, not caller data."""
        canonical = canonical_writer_observation(observation)
        events = canonical["events"]
        invocations = tuple(canonical["writer_invocations"])
        if self._writer_invocation_records and invocations != self._writer_invocation_records:
            raise _deny("POST_PERMIT_TRACE_DENY", "writer invocation records were replaced or forged")
        expected_module = provenance.safe_write_bytes.__module__
        if any(event["module_path"] != expected_module for event in events):
            raise _deny("POST_PERMIT_TRACE_DENY", "writer event module path is not owner-bound")
        if any(event["source_ref"] != self.writer_trace_plan["provenance_source_ref"] for event in events):
            raise _deny("POST_PERMIT_TRACE_DENY", "writer event source reference is not owner-bound")
        for event in events:
            action, offset_text = event["outcome"].rsplit("@", 1)
            offset = int(offset_text)
            if action == "transaction_started" and offset != self.writer_trace_plan["transaction_call_offset"]:
                raise _deny("POST_PERMIT_TRACE_DENY", "transaction event offset is not owner-bound")
            if action == "writer_call_started" and offset != self.writer_trace_plan["writer_call_offset"]:
                raise _deny("POST_PERMIT_TRACE_DENY", "writer event offset is not owner-bound")
        for invocation in invocations:
            expected = self._writer_expected_artifacts.get(invocation["target_relative_path"])
            if expected is None or invocation["artifact_identity"] != _artifact_identity(expected):
                raise _deny("POST_PERMIT_TRACE_DENY", "writer invocation artifact identity is not owner-bound")
            expected_final_path = self._writer_expected_final_paths.get(invocation["target_relative_path"])
            if expected_final_path is None or invocation["target_final_path"] != expected_final_path:
                raise _deny("POST_PERMIT_TRACE_DENY", "writer invocation final path is not owner-bound")
        if self._writer_trace_events and tuple(events) != self._writer_trace_events:
            raise _deny("POST_PERMIT_TRACE_DENY", "writer event trace was replaced or forged")
        if canonical["trace_hash"] != canonical_sha256({"events": events}, fields=("events",)):
            raise _deny("POST_PERMIT_TRACE_DENY", "writer event trace was replaced or forged")
        return canonical

    def _owner_writer_observation_snapshot(self) -> dict[str, Any]:
        if self._owner_writer_observation is None or self._owner_writer_observation_bytes is None:
            raise _deny("POST_PERMIT_TRACE_DENY", "owner writer observation is unavailable")
        if self.writer_phase_observation is None:
            raise _deny("POST_PERMIT_TRACE_DENY", "owner writer observation was cleared")
        current_bytes = canonical_evaluation_json_bytes(
            self.writer_phase_observation, fields=DETERMINISTIC_WRITER_OBSERVATION_FIELDS,
        )
        if current_bytes != self._owner_writer_observation_bytes:
            raise _deny("POST_PERMIT_TRACE_DENY", "caller-replaced writer observation is not accepted")
        return self._validate_owner_writer_observation(self._owner_writer_observation)

    def _bind_p1ae_owner_authority_source(
        self,
        *,
        authority_source: Any,
        source_readback: bytes,
    ) -> None:
        """Bind annotation authority only from the owner transaction seam.

        This is intentionally private and one-shot.  The pure loader refuses
        caller-supplied authority records/bytes; an owner writer/annotation
        transaction must first bind the source object and its byte readback.
        """
        if self._p1ae_annotation_registry is not None or self._p1ae_authority_source is not None:
            raise _deny("DENIED_AUTHORITY", "owner authority source replay is denied")
        if authority_source is None or not callable(getattr(authority_source, "readback", None)) or not callable(getattr(authority_source, "records", None)) or not isinstance(source_readback, bytes):
            raise _deny("DENIED_AUTHORITY", "owner authority source readback is incomplete")
        authority_bytes = authority_source.readback()
        records = authority_source.records()
        if not isinstance(authority_bytes, bytes) or authority_bytes != source_readback:
            raise _deny("DENIED_AUTHORITY", "owner authority source readback changed")
        if not isinstance(records, (list, tuple)):
            raise _deny("DENIED_AUTHORITY", "owner authority source records are not owner-derived")
        self._p1ae_authority_source = authority_source
        self._p1ae_authority_readback = bytes(source_readback)
        self._p1ae_annotation_registry = P1AEOwnerRegistryV1(
            owner_id=self.source_registry.value["owner_id"],
            owner_session=self.owner_session_id,
            request_nonce=f"owner-registry:{self.owner_session_id}",
            authority_bytes=authority_bytes,
            source_readback=source_readback,
            records=records,
        )

    def _bind_p1ae_post_write_evidence(
        self,
        evidence: Mapping[str, Any],
        *,
        batch_id: str,
        attempt_id: str,
        transaction_id: str,
    ) -> None:
        """Store one owner-derived P1-A writer readback for pure admission."""
        if self._p1ae_post_write_evidence is not None:
            raise _deny("POST_PERMIT_TRACE_DENY", "post-write evidence replay is denied")
        if not isinstance(evidence, Mapping):
            raise _deny("POST_PERMIT_TRACE_DENY", "post-write evidence is not owner-derived")
        if (evidence.get("batch_id"), evidence.get("attempt_id"), evidence.get("transaction_id")) != (batch_id, attempt_id, transaction_id):
            raise _deny("POST_PERMIT_TRACE_DENY", "post-write evidence transaction binding mismatch")
        self._p1ae_post_write_evidence = dict(evidence)

    def _bind_p1ae_cpython_internal_allowlist(self, events: Sequence[Mapping[str, Any]]) -> None:
        """Bind the complete pre-CAS CPython internal allowlist owner-side."""
        if getattr(self, "_p1ae_cpython_internal_expected_allowlist", None) is not None:
            raise _deny("DENIED_CAPABILITY", "CPython internal allowlist replay is denied")
        if not isinstance(events, (list, tuple)):
            raise _deny("DENIED_CAPABILITY", "CPython internal allowlist is not owner-derived")
        canonical = tuple(dict(item) for item in events)
        previous = -1
        for item in canonical:
            if item.get("event_kind") != "CPYTHON_INTERNAL" or item.get("load_role") != "P1AE_INTERNAL_RUNTIME" or item.get("channel") != "BUILTIN" or item.get("allowed") is not True:
                raise _deny("DENIED_CAPABILITY", "CPython internal allowlist predicate mismatch")
            if not isinstance(item.get("trace_sequence"), int) or item["trace_sequence"] <= previous:
                raise _deny("DENIED_CAPABILITY", "CPython internal allowlist sequence is not canonical")
            previous = item["trace_sequence"]
        self._p1ae_cpython_internal_expected_allowlist = canonical

    def _validate_owner_observer_binding(self) -> None:
        if self.observer is not self._owner_observer:
            raise _deny("DENIED_CAPABILITY", "owner observer identity was replaced")
        if type(self.observer) is not P1CapabilityObserver or tuple(vars(self.observer)) != ("_values",):
            raise _deny("DENIED_CAPABILITY", "owner observer implementation is not fixed and owner-bound")
        current = owner_probe_binding_snapshot(
            owner_id=self.source_registry.value["owner_id"],
            authority_ref=self.source_registry.value["authoritative_source_ref"],
            source_registry=self.source_registry, source_root=self.source_root,
        )
        if current != self._owner_probe_binding or canonical_sha256(current, fields=OWNER_PROBE_BINDING_FIELDS) != self._owner_probe_binding_hash:
            raise _deny("DENIED_CAPABILITY", "owner observer code or source binding changed")

    def _assert_owner_observation_matches(self) -> dict[str, int]:
        self._validate_owner_observer_binding()
        if self.capability_probe_snapshot is None:
            raise _deny("DENIED_CAPABILITY", "owner capability snapshot is unavailable")
        values = self.observer.snapshot()
        records = self.capability_probe_snapshot.get("records")
        if not isinstance(records, list) or tuple(item.get("capability") for item in records) != tuple(P1_FORBIDDEN_CAPABILITIES):
            raise _deny("DENIED_CAPABILITY", "owner capability record set is not closed")
        observed = {item["capability"]: item["observed_call_count"] for item in records}
        if observed != values or any(value != 0 for value in values.values()):
            raise _deny("DENIED_CAPABILITY", "owner observer differs from permit-bound capability snapshot")
        return values

    def _assert_candidates_not_preloaded(self) -> None:
        """Reject candidate names and source aliases before permit issuance."""
        candidate_names = tuple(self.gate.value["candidate_modules"])
        if any(name in sys.modules and sys.modules.get(name) is not None for name in candidate_names):
            raise _deny("DENIED_CAPABILITY", "candidate module was preloaded before permit")
        for entry in self.source_registry.value["entries"]:
            if entry["source_role"] != "candidate":
                continue
            source_path, _ = self._source_path(entry)
            admitted = str(source_path.resolve())
            for module in sys.modules.values():
                module_path = getattr(module, "__file__", None)
                if module_path and str(Path(str(module_path)).resolve()) == admitted:
                    raise _deny("DENIED_CAPABILITY", "candidate source path alias was preloaded before permit")

    def _admit(self) -> None:
        with self._lock:
            self._validate_trace_plan()
            self._validate_owner_observer_binding()
            if self.gate.value["owner_probe_binding_hash"] != self._owner_probe_binding_hash:
                raise _deny("DENIED_CAPABILITY", "gate owner probe binding hash mismatch")
            if self.source_registry.value["owner_id"] != self.gate.value["owner_id"]:
                raise _deny("DENIED_PROVENANCE", "source and gate owner mismatch")
            self.census.validate_closed(self.source_registry)
            if self.census.value["owner_id"] != self.source_registry.value["owner_id"]:
                raise _deny("DENIED_CAPABILITY", "census owner mismatch")
            if self.gate.value["capability_census_snapshot_hash"] != self.census.snapshot_hash:
                raise _deny("DENIED_CAPABILITY", "gate census snapshot mismatch")
            if self.gate.value["evaluator_source_registry_snapshot_hash"] != _evaluator_source_snapshot_hash(self.source_registry):
                raise _deny("DENIED_PROVENANCE", "gate source snapshot mismatch")
            if self.gate.value["resolution_guard_snapshot_hash"] != self.resolution_guard_snapshot_hash:
                raise _deny("DENIED_PROVENANCE", "gate guard snapshot mismatch")
            if self.gate.value["writer_trace_plan_snapshot_hash"] != self.writer_trace_plan_snapshot_hash:
                raise _deny("DENIED_PROVENANCE", "gate trace-plan snapshot mismatch")
            if self.source_registry.value["read_only"] is not True:
                raise _deny("DENIED_PROVENANCE", "source registry is not read-only")
            for source_entry in self.source_registry.value["entries"]:
                self._source_path(source_entry)
            self._assert_candidates_not_preloaded()
            self.capability_probe_snapshot = P1CapabilityObserver.owner_attestation(self.observer,
                owner_id=self.source_registry.value["owner_id"],
                authority_ref=self.source_registry.value["authoritative_source_ref"],
                source_registry=self.source_registry,
                source_root=self.source_root,
                census=self.census,
            )
            _validate_capability_probe_snapshot(self.capability_probe_snapshot, self.source_registry)
            self._assert_owner_observation_matches()
            if canonical_sha256(self._owner_probe_binding, fields=OWNER_PROBE_BINDING_FIELDS) != self.gate.value["owner_probe_binding_hash"]:
                raise _deny("DENIED_CAPABILITY", "owner probe binding is not gate-bound")
            self._resolution_live_snapshot, self._resolution_support = _build_resolution_live_snapshot(
                guard=self.resolution_guard, gate=self.gate, census=self.census,
                source_registry=self.source_registry,
                source_root=self.source_root,
            )
            if self.resolution_guard["read_only"] is not True or not all(
                self.resolution_guard[field] is True for field in
                ("deny_sys_path_read", "deny_cwd_read", "deny_fallback_finder", "deny_sys_modules_reuse", "deny_builtin_ambient_load")
            ):
                raise _deny("DENIED_CAPABILITY", "resolution guard is not deny-first")
            candidate = tuple(self.gate.value["candidate_modules"])
            if tuple(self.resolution_guard["candidate_closure_modules"]) != candidate:
                raise _deny("DENIED_CAPABILITY", "candidate closure is not gate-bound")
            if self.gate.value["dynamic_import_allowlist"] != []:
                raise _deny("UNKNOWN_DYNAMIC_IMPORT", "dynamic import allowlist must be empty")
            for item in self.census.value["entries"]:
                if item["module_path"] not in candidate:
                    continue
                source = self.source_registry.entry_for(item["source_relative_path"])
                if source["source_ref"] != item["source_ref"] or source["length"] != item["source_length"] or source["sha256"] != item["source_sha256"]:
                    raise _deny("DENIED_PROVENANCE", "candidate source binding mismatch")
                self._source_path(source)
            self._run_pre_permit_opcode_attestation()
            self._trace = OpcodeWriterTrace(self.writer_trace_plan)
            self._trace.ready()

    def _run_pre_permit_opcode_attestation(self) -> None:
        """Prove a real CPython opcode event before READY and permit issuance."""
        if threading.get_ident() != self.writer_trace_plan["trace_thread_id"]:
            raise _deny("DENIED_PROVENANCE", "pre-permit trace thread mismatch")
        runtime = runtime_identity_snapshot()
        runtime_hash = canonical_sha256(runtime, fields=CPYTHON_RUNTIME_ID_FIELDS)
        if runtime_hash != self.writer_trace_plan["runtime_snapshot_hash"]:
            raise _deny("DENIED_PROVENANCE", "pre-permit runtime snapshot mismatch")
        source_path = Path(__file__)
        source_bytes = _strict_bytes(source_path.read_bytes(), "evaluator source")
        if len(source_bytes) != self.writer_trace_plan["marker_source_length"] or sha256_bytes(source_bytes) != self.writer_trace_plan["marker_source_sha256"]:
            raise _deny("DENIED_PROVENANCE", "marker source readback mismatch")
        marker_code = _opcode_attestation_marker.__code__
        probe_code = _opcode_attestation_probe.__code__
        if code_object_sha256(marker_code) != self.writer_trace_plan["marker_code_sha256"] or code_object_sha256(probe_code) != self.writer_trace_plan["probe_code_sha256"]:
            raise _deny("DENIED_PROVENANCE", "marker or probe code object drift")
        static_marker = list(_trace_visible_instructions(_opcode_attestation_marker))
        static_probe = list(_trace_visible_instructions(_opcode_attestation_probe))
        static_whitelist = sorted(list(_opcode_records(_opcode_attestation_marker)), key=lambda item: (item["opcode"], item["opname_utf8_hex"], item["has_argument"]))
        if static_whitelist != self.writer_trace_plan["marker_opcode_whitelist"]:
            raise _deny("DENIED_PROVENANCE", "marker opcode whitelist drift")
        allowed_marker_names = {"RESUME", "LOAD_CONST", "RETURN_VALUE", "RETURN_CONST", "CACHE", "NOP"}
        if any(item.opname not in allowed_marker_names for item in static_marker) or any(item.opname.startswith("CALL") or item.opname.startswith("IMPORT") for item in static_marker):
            raise _deny("DENIED_CAPABILITY", "marker is not pure memory-only code")
        expected_sequence_hash = _marker_sequence_hash(_opcode_attestation_marker, runtime_hash)
        if expected_sequence_hash != self.writer_trace_plan["marker_opcode_sequence_hash"]:
            raise _deny("DENIED_PROVENANCE", "marker opcode sequence hash drift")
        previous = sys.gettrace()
        if previous is not None:
            raise _deny("DENIED_CAPABILITY", "ambient trace hook is not permitted")
        instruction_maps = {
            marker_code: {int(item.offset): item for item in static_marker},
            probe_code: {int(item.offset): item for item in static_probe},
        }
        observed: list[dict[str, Any]] = []
        sequence_by_role = {"MARKER": 0, "PROBE": 0}
        hook_holder: list[Any] = []

        def trace_hook(frame: Any, event: str, arg: Any):
            if frame.f_code not in instruction_maps:
                return trace_hook
            if event == "call":
                frame.f_trace_opcodes = True
                return trace_hook
            if event != "opcode":
                return trace_hook
            instruction = instruction_maps[frame.f_code].get(int(frame.f_lasti))
            if instruction is None:
                raise _deny("DENIED_PROVENANCE", "runtime opcode offset is not in static sequence")
            role = "MARKER" if frame.f_code is marker_code else "PROBE"
            kind, value = _opcode_argument(instruction)
            event_record = _opcode_event(types.SimpleNamespace(__code__=frame.f_code), role, sequence_by_role[role], instruction)
            _validate_opcode_event(event_record, role=role, expected_sequence=sequence_by_role[role])
            observed.append(event_record)
            sequence_by_role[role] += 1
            return trace_hook

        hook_holder.append(trace_hook)
        try:
            sys.settrace(trace_hook)
            if sys.gettrace() is not trace_hook:
                raise _deny("DENIED_PROVENANCE", "opcode trace hook was replaced")
            _opcode_attestation_probe()
            if sys.gettrace() is not trace_hook:
                raise _deny("DENIED_PROVENANCE", "opcode trace hook changed during probe")
        finally:
            sys.settrace(previous)
        if sys.gettrace() is not previous:
            raise _deny("DENIED_PROVENANCE", "opcode trace hook was not restored")
        if not observed:
            # Some embedded/pytest hosts defer the first trace installation
            # until the current frame yields.  Re-arm the same real hook once;
            # an unavailable channel still fails closed below.
            sys.settrace(trace_hook)
            try:
                if sys.gettrace() is not trace_hook:
                    raise _deny("DENIED_PROVENANCE", "opcode trace hook was replaced on retry")
                _opcode_attestation_probe()
            finally:
                sys.settrace(previous)
            if sys.gettrace() is not previous:
                raise _deny("DENIED_PROVENANCE", "opcode trace hook was not restored after retry")
        marker_events = [event for event in observed if event["code_object_role"] == "MARKER"]
        probe_events = [event for event in observed if event["code_object_role"] == "PROBE"]
        for index, event in enumerate(marker_events):
            _validate_opcode_event(event, role="MARKER", expected_sequence=index)
        for index, event in enumerate(probe_events):
            _validate_opcode_event(event, role="PROBE", expected_sequence=index)
        static_marker_events = [_opcode_event(_opcode_attestation_marker, "MARKER", index, instruction) for index, instruction in enumerate(static_marker)]
        static_probe_events = [_opcode_event(_opcode_attestation_probe, "PROBE", index, instruction) for index, instruction in enumerate(static_probe)]
        if marker_events != static_marker_events or probe_events != static_probe_events:
            raise _deny("DENIED_PROVENANCE", "runtime opcode events do not match static marker/probe proof")
        call_events = [event for event in probe_events if event["opcode"] in {dis.opmap.get("CALL"), dis.opmap.get("CALL_FUNCTION_EX")}]
        if len(call_events) != 1 or call_events[0]["instruction_offset"] != self.writer_trace_plan["probe_call_offset"]:
            raise _deny("DENIED_PROVENANCE", "probe did not produce exactly one CALL opcode event")
        self._trace_attestation = {"status": "READY", "runtime_snapshot_hash": runtime_hash, "events": observed, "marker_opcode_sequence_hash": expected_sequence_hash, "marker_call_count": 0, "probe_call_count": 1, "event_delivery_status": "VERIFIED", "hook_install_status": "VERIFIED", "trace_replacement_guard_status": "VERIFIED"}

    def issue_permit(self, *, input_binding_hash: str | None = None, input_manifest_hash: str | None = None) -> ImportPermitV1:
        with self._lock:
            if threading.get_ident() != self.writer_trace_plan["trace_thread_id"]:
                raise _deny("DENIED_PROVENANCE", "permit issuance thread mismatch")
            self._validate_trace_plan()
            self._validate_owner_observer_binding()
            for source_entry in self.source_registry.value["entries"]:
                self._source_path(source_entry)
            if input_binding_hash is not None:
                _hash(input_binding_hash, "input_binding_hash")
                if self._input_binding_hash not in {"0" * 64, input_binding_hash}:
                    raise _deny("DENIED_PROVENANCE", "input binding changed after owner admission")
                self._input_binding_hash = input_binding_hash
            if input_manifest_hash is not None:
                _hash(input_manifest_hash, "input_manifest_hash")
                if self._input_manifest_hash not in {"0" * 64, input_manifest_hash}:
                    raise _deny("DENIED_PROVENANCE", "input manifest changed after owner admission")
                self._input_manifest_hash = input_manifest_hash
            self._recheck_owner_manifest()
            self._assert_candidates_not_preloaded()
            self.census.validate_closed(self.source_registry)
            prior_probe_snapshot = self.capability_probe_snapshot
            fresh_probe_snapshot = P1CapabilityObserver.owner_attestation(self.observer,
                owner_id=self.source_registry.value["owner_id"], authority_ref=self.source_registry.value["authoritative_source_ref"], source_registry=self.source_registry,
                source_root=self.source_root, census=self.census,
            )
            _validate_capability_probe_snapshot(fresh_probe_snapshot, self.source_registry)
            if prior_probe_snapshot is None or fresh_probe_snapshot != prior_probe_snapshot:
                raise _deny("DENIED_CAPABILITY", "owner probe snapshot changed before permit")
            self.capability_probe_snapshot = fresh_probe_snapshot
            self._assert_owner_observation_matches()
            if self.gate.value["owner_probe_binding_hash"] != self._owner_probe_binding_hash:
                raise _deny("DENIED_CAPABILITY", "gate owner probe binding changed before permit")
            live, support = _build_resolution_live_snapshot(
                guard=self.resolution_guard, gate=self.gate, census=self.census, source_registry=self.source_registry,
                source_root=self.source_root,
            )
            if live != self._resolution_live_snapshot or support != self._resolution_support:
                raise _deny("DENIED_PROVENANCE", "resolution live snapshot changed before permit")
            if self.gate.value["capability_census_snapshot_hash"] != self.census.snapshot_hash:
                raise _deny("DENIED_CAPABILITY", "final census snapshot mismatch")
            if self.gate.value["evaluator_source_registry_snapshot_hash"] != _evaluator_source_snapshot_hash(self.source_registry):
                raise _deny("DENIED_PROVENANCE", "final source snapshot mismatch")
            if self.gate.value["resolution_guard_snapshot_hash"] != self.resolution_guard_snapshot_hash:
                raise _deny("DENIED_PROVENANCE", "final resolution snapshot mismatch")
            if self.gate.value["writer_trace_plan_snapshot_hash"] != self.writer_trace_plan_snapshot_hash:
                raise _deny("DENIED_PROVENANCE", "final trace-plan snapshot mismatch")
            if self._trace.phase != "READY":
                raise _deny(POST_PERMIT_TRACE_DENY, "permit issuance requires READY trace")
            if self._trace_attestation is None or self._trace_attestation.get("status") != "READY":
                raise _deny("DENIED_PROVENANCE", "permit requires pre-permit opcode attestation")
            # Final opcode proof is part of the same owner-lock transaction as
            # permit construction.  A stale READY marker is never reused.
            self._run_pre_permit_opcode_attestation()
            preimage = {
                "permit_schema_version": PERMIT_SCHEMA_VERSION, "owner_id": self.gate.value["owner_id"],
                "authority_ref": self.gate.value["authority_ref"], "gate_id": self.gate.value["gate_id"],
                "preimport_gate_snapshot_hash": self.gate.snapshot_hash,
                "capability_census_snapshot_hash": self.census.snapshot_hash,
                "evaluator_source_registry_snapshot_hash": _evaluator_source_snapshot_hash(self.source_registry),
                "resolution_guard_snapshot_hash": self.resolution_guard_snapshot_hash,
                "runtime_snapshot_hash": self.writer_trace_plan["runtime_snapshot_hash"],
                "marker_purity_hash": self.writer_trace_plan["marker_purity_hash"],
                "marker_opcode_sequence_hash": self.writer_trace_plan["marker_opcode_sequence_hash"],
                "trace_plan_snapshot_hash": self.writer_trace_plan_snapshot_hash,
                "candidate_modules": list(self.gate.value["candidate_modules"]),
                "static_module_allowlist": list(self.gate.value["static_module_allowlist"]),
                "dynamic_import_allowlist": [], "read_only": True, "no_root_creation": True,
                "no_config_discovery": True, "no_project_discovery": True,
                "single_use": True, "permit_status": "READY",
                "cpython_runtime_snapshot_hash": self.writer_trace_plan["runtime_snapshot_hash"],
                "pre_permit_attestation_v15_hash": self.pre_permit_attestation_v15_hash,
                "marker_purity_snapshot_hash": self.writer_trace_plan["marker_purity_hash"],
                "capability_probe_snapshot_hash": self.capability_probe_snapshot_hash,
                "resolution_live_snapshot_hash": self.resolution_live_snapshot_hash,
                "input_binding_hash": self._input_binding_hash, "input_manifest_hash": self._input_manifest_hash,
                "owner_probe_binding_hash": self._owner_probe_binding_hash,
                "source_registry_snapshot_hash": self.source_registry.snapshot_hash,
                "candidate_module_set": list(self.gate.value["candidate_modules"]),
                "owner_session_id": self.owner_session_id, "trace_thread_binding": self.writer_trace_plan["trace_thread_id"],
                "hook_install_status": "VERIFIED", "opcode_trace_support": True,
                "event_delivery_status": "VERIFIED", "trace_replacement_guard_status": "VERIFIED",
                "attestation_status": "READY",
            }
            permit = issue_import_permit_v2(
                owner_session_id=self.owner_session_id, sentinel=self._sentinel,
                private_handle=object(), preimage=preimage, seal_key=self.seal_key,
                issued_at_utc="owner-issued",
            )
            self._issued[id(permit)] = {
                "permit": permit, "private_handle": permit._private_handle,
                "private_handle_identity": id(permit._private_handle), "consumed": False,
            }
            self._trace.post_permit_check(threading.get_ident())
            return permit

    def _verify_permit(self, permit: ImportPermitV1) -> None:
        record = self._issued.get(id(permit)) if isinstance(permit, ImportPermitV1) else None
        if record is None or record["permit"] is not permit:
            raise _deny("DENIED_CAPABILITY", "permit object identity is not owner-issued")
        if permit._sentinel is not self._sentinel or permit._private_handle is not record["private_handle"] or id(permit._private_handle) != record["private_handle_identity"]:
            raise _deny("DENIED_CAPABILITY", "permit private handle identity mismatch")
        if permit.owner_session_id != self.owner_session_id or permit.consumed or record["consumed"]:
            raise _deny("DENIED_CAPABILITY", "permit is stale, consumed or copied")
        if recompute_permit_digest_v2(permit) != permit.permit_digest or recompute_permit_seal_v2(permit, self.seal_key) != permit.permit_seal:
            raise _deny("DENIED_CAPABILITY", "permit digest or seal mismatch")
        if permit.preimage["preimport_gate_snapshot_hash"] != self.gate.snapshot_hash:
            raise _deny("DENIED_CAPABILITY", "permit gate snapshot is stale")
        if permit.preimage["capability_census_snapshot_hash"] != self.census.snapshot_hash:
            raise _deny("DENIED_CAPABILITY", "permit census snapshot is stale")
        if permit.preimage["evaluator_source_registry_snapshot_hash"] != _evaluator_source_snapshot_hash(self.source_registry):
            raise _deny("DENIED_PROVENANCE", "permit source snapshot is stale")
        if permit.preimage["resolution_guard_snapshot_hash"] != self.resolution_guard_snapshot_hash:
            raise _deny("DENIED_CAPABILITY", "permit resolution snapshot is stale")
        if permit.preimage["runtime_snapshot_hash"] != canonical_sha256(runtime_identity_snapshot(), fields=CPYTHON_RUNTIME_ID_FIELDS):
            raise _deny("DENIED_PROVENANCE", "permit runtime snapshot is stale")
        if permit.preimage["trace_plan_snapshot_hash"] != self.writer_trace_plan_snapshot_hash:
            raise _deny("DENIED_PROVENANCE", "permit trace plan is stale")
        if permit.preimage["cpython_runtime_snapshot_hash"] != permit.preimage["runtime_snapshot_hash"]:
            raise _deny("DENIED_PROVENANCE", "permit runtime binding is duplicated inconsistently")
        if permit.preimage["pre_permit_attestation_v15_hash"] != self.pre_permit_attestation_v15_hash:
            raise _deny("DENIED_PROVENANCE", "permit V15 attestation is stale")
        if permit.preimage["capability_probe_snapshot_hash"] != self.capability_probe_snapshot_hash:
            raise _deny("DENIED_CAPABILITY", "permit capability observation is stale")
        if permit.preimage["owner_probe_binding_hash"] != self._owner_probe_binding_hash:
            raise _deny("DENIED_CAPABILITY", "permit owner probe binding is stale")
        if permit.preimage["resolution_live_snapshot_hash"] != self.resolution_live_snapshot_hash:
            raise _deny("DENIED_CAPABILITY", "permit live resolution snapshot is stale")
        if permit.preimage["input_binding_hash"] != self._input_binding_hash or permit.preimage["input_manifest_hash"] != self._input_manifest_hash:
            raise _deny("DENIED_PROVENANCE", "permit input binding is stale")
        if permit.preimage["owner_session_id"] != self.owner_session_id or permit.preimage["trace_thread_binding"] != threading.get_ident():
            raise _deny("DENIED_PROVENANCE", "permit owner or thread binding is stale")

    def _source_path(self, entry: Mapping[str, Any]) -> tuple[Path, bytes]:
        path = _final_path(self.source_root / entry["relative_path"], self.source_root, must_exist=True)
        try:
            raw = _strict_bytes(path.read_bytes(), "candidate source")
        except OSError as exc:
            raise _deny("SOURCE_READ_FAILED", "candidate source read failed") from exc
        self.source_registry.verify_bytes(entry, raw)
        return path, raw

    def load_candidates(self, permit: ImportPermitV1, *, expected_input_binding_hash: str | None = None, expected_input_manifest_hash: str | None = None) -> tuple[dict[str, Any], ...]:
        with self._lock:
            self._verify_permit(permit)
            _verify_live_resolution_guard(self.resolution_guard)
            if expected_input_binding_hash is not None and permit.preimage["input_binding_hash"] != expected_input_binding_hash:
                raise _deny("DENIED_PROVENANCE", "candidate load input binding mismatch")
            if expected_input_manifest_hash is not None and permit.preimage["input_manifest_hash"] != expected_input_manifest_hash:
                raise _deny("DENIED_PROVENANCE", "candidate load input manifest mismatch")
            # Authoritative consumed CAS remains inside the owner lock and is
            # set before any candidate import or other observable load work.
            record = self._issued.get(id(permit))
            if record is None or record["consumed"] is not False:
                raise _deny("DENIED_CAPABILITY", "permit replay or concurrent consumption")
            record["consumed"] = True
            permit.consumed = True
        candidate_names = tuple(self.gate.value["candidate_modules"])
        before = {name: sys.modules.get(name) for name in candidate_names}
        if any(value is not None for value in before.values()):
            raise _deny("DENIED_CAPABILITY", "candidate module was preloaded")
        snapshot = self.resolution_guard["sys_modules_snapshot"]
        if not snapshot:
            raise _deny("DENIED_CAPABILITY", "complete sys.modules preload snapshot is required")
        snapshot_names = tuple(
            (item.split("|", 1)[0] if isinstance(item, str) and "|" in item else item if isinstance(item, str) else item.get("module_path", item.get("module_name", "")))
            for item in snapshot
        )
        if not all(isinstance(name, str) and name for name in snapshot_names) or tuple(sorted(snapshot, key=lambda item: str(item).encode("utf-8"))) != tuple(snapshot) or len(set(snapshot)) != len(snapshot):
            raise _deny("DENIED_CAPABILITY", "sys.modules preload snapshot is incomplete or unsorted")
        if set(snapshot_names) != set(sys.modules):
            raise _deny("DENIED_CAPABILITY", "sys.modules preload snapshot is stale")
        static_allowlist = tuple(self.gate.value["static_module_allowlist"])
        if not set(candidate_names).issubset(set(static_allowlist)):
            raise _deny("DENIED_CAPABILITY", "candidate module is outside the static allowlist")
        bootstrap_records = list(_owner_bound_bootstrap_records(
            self.resolution_guard["bootstrap_module_entries"],
            source_registry=self.source_registry,
            source_root=self.source_root,
        ))
        bootstrap_names = [item["module_path"] for item in bootstrap_records]
        if tuple(bootstrap_names) != tuple(sorted(bootstrap_names, key=lambda item: item.encode("utf-8"))) or len(set(bootstrap_names)) != len(bootstrap_names):
            raise _deny("DENIED_CAPABILITY", "bootstrap module entries are unsorted or duplicated")
        snapshot_by_name = {name: item for name, item in zip(snapshot_names, snapshot)}
        for record in bootstrap_records:
            name = record["module_path"]
            if name not in sys.modules or name not in snapshot_by_name:
                raise _deny("DENIED_CAPABILITY", "owner-bound bootstrap module is missing")
            try:
                expected_identity = int(str(snapshot_by_name[name]).rsplit("|", 1)[1])
            except (ValueError, IndexError) as exc:
                raise _deny("DENIED_CAPABILITY", "bootstrap module identity record is invalid") from exc
            if id(sys.modules[name]) != expected_identity or record["module_identity"] != expected_identity:
                raise _deny("DENIED_CAPABILITY", "bootstrap module identity changed")
            module = sys.modules[name]
            actual_origin = str(getattr(getattr(module, "__spec__", None), "origin", ""))
            actual_file = str(getattr(module, "__file__", ""))
            if record["spec_origin"] != actual_origin or record["resolved_path"] != (actual_file or actual_origin):
                raise _deny("DENIED_PROVENANCE", "bootstrap module runtime identity differs")
        if set(static_allowlist) - set(bootstrap_names) != {item["module_path"] for item in self.census.value["entries"]}:
            raise _deny("DENIED_CAPABILITY", "static allowlist is not exactly census/source bound")
        for name in set(static_allowlist) - set(candidate_names) - set(bootstrap_names):
            if name in sys.modules:
                raise _deny("DENIED_CAPABILITY", "non-candidate static dependency was preloaded")
        for census_entry in self.census.value["entries"]:
            closure = set(census_entry["transitive_modules"])
            allowed_closure = set(candidate_names) | set(static_allowlist) | set(bootstrap_names)
            if not closure.issubset(allowed_closure):
                raise _deny("DENIED_CAPABILITY", "candidate transitive closure escapes the static allowlist")
            for dependency in census_entry["static_imports"]:
                if dependency in sys.modules and dependency not in set(candidate_names) | set(bootstrap_names):
                    raise _deny("DENIED_CAPABILITY", "candidate static dependency was preloaded before import")
        before_modules = {name: id(module) for name, module in sys.modules.items()}
        before_meta_path = tuple(id(item) for item in sys.meta_path)
        before_path_hooks = tuple(id(item) for item in sys.path_hooks)
        for value in self.resolution_guard["preloaded_candidate_source_paths"]:
            if any(str(value) == str(getattr(module, "__file__", "")) for module in sys.modules.values() if module is not None):
                raise _deny("DENIED_CAPABILITY", "candidate source path alias was preloaded")
        before_path = tuple(sys.path)
        before_cwd = os.getcwd()
        modules: list[dict[str, Any]] = []
        inserted: list[str] = []
        owned_loaded: set[str] = set()
        static_modules = tuple(sorted(
            set(item["module_path"] for item in self.census.value["entries"]) - set(candidate_names),
            key=lambda item: item.encode("utf-8"),
        ))
        previous_import = builtins.__import__
        previous_import_module = importlib.import_module
        previous_dont_write_bytecode = sys.dont_write_bytecode

        def load_owned(module_path: str) -> types.ModuleType:
            if module_path in owned_loaded:
                return sys.modules[module_path]
            census_entry = next((item for item in self.census.value["entries"] if item["module_path"] == module_path), None)
            if census_entry is None:
                raise _deny("DENIED_CAPABILITY", "requested module has no owner census entry")
            source_entry = self.source_registry.entry_for(census_entry["source_relative_path"])
            expected_role = "candidate" if module_path in candidate_names else "static"
            if source_entry["source_role"] != expected_role:
                raise _deny("DENIED_PROVENANCE", "module source role differs from census")
            if (source_entry["source_ref"], source_entry["length"], source_entry["sha256"]) != (census_entry["source_ref"], census_entry["source_length"], census_entry["source_sha256"]):
                raise _deny("DENIED_PROVENANCE", "module source binding differs from census")
            if module_path in before_modules:
                raise _deny("DENIED_CAPABILITY", "owner module was preloaded before load")
            source_path, source_bytes = self._source_path(source_entry)
            spec = importlib.util.spec_from_file_location(module_path, source_path)
            if spec is None or spec.loader is None or not isinstance(spec.loader, type(importlib.util.spec_from_file_location("owner-loader-probe", source_path).loader)):
                raise _deny("DENIED_CAPABILITY", "owner-controlled source loader is unavailable")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_path] = module
            inserted.append(module_path)
            spec.loader.exec_module(module)
            actual_file = getattr(module, "__file__", None)
            actual_origin = getattr(getattr(module, "__spec__", None), "origin", None)
            if not isinstance(actual_file, str) or not isinstance(actual_origin, str):
                raise _deny("DENIED_PROVENANCE", "loaded module has no concrete source identity")
            if Path(actual_file).resolve() != source_path.resolve() or Path(actual_origin).resolve() != source_path.resolve():
                raise _deny("DENIED_PROVENANCE", "loaded module path or origin differs from owner source")
            post_bytes = _strict_bytes(source_path.read_bytes(), "owner source readback")
            if post_bytes != source_bytes or len(post_bytes) != source_entry["length"] or sha256_bytes(post_bytes) != source_entry["sha256"]:
                raise _deny("DENIED_PROVENANCE", "owner source readback changed during load")
            modules.append({
                "load_sequence": len(modules) + 1, "module_path": module_path,
                "resolved_path": str(source_path.resolve()), "source_relative_path": source_entry["relative_path"],
                "source_ref": source_entry["source_ref"], "source_length": source_entry["length"],
                "source_sha256": source_entry["sha256"], "preload_length": 0,
                "preload_sha256": sha256_bytes(b""), "postload_length": len(post_bytes),
                "postload_sha256": sha256_bytes(post_bytes), "module_file": str(Path(actual_file).resolve()),
                "spec_origin": str(Path(actual_origin).resolve()),
            })
            owned_loaded.add(module_path)
            return module

        def owner_import(name: str, globals: Mapping[str, Any] | None = None, locals: Mapping[str, Any] | None = None, fromlist: Sequence[str] = (), level: int = 0):
            if level != 0 or not isinstance(name, str) or not name:
                raise _deny("DENIED_CAPABILITY", "relative or dynamic import is not owner-bound")
            caller = globals.get("__name__") if isinstance(globals, Mapping) else None
            if caller == "importlib._bootstrap_external" and name == "_io":
                return previous_import(name, globals, locals, fromlist, level)
            caller_entry = next((item for item in self.census.value["entries"] if item["module_path"] == caller), None)
            if caller_entry is None or name not in set(caller_entry["transitive_modules"]):
                raise _deny("DENIED_CAPABILITY", f"import request is outside the caller transitive census: {caller!r}->{name!r}")
            if name in bootstrap_names:
                return sys.modules[name]
            if name not in set(self.gate.value["static_module_allowlist"]):
                raise _deny("DENIED_CAPABILITY", "ambient import is not in owner static closure")
            module = load_owned(name) if name not in owned_loaded else sys.modules[name]
            return module if fromlist else sys.modules[name.split(".", 1)[0]]

        try:
            builtins.__import__ = owner_import
            sys.dont_write_bytecode = True
            for module_path in static_modules:
                load_owned(module_path)
            for module_path in candidate_names:
                load_owned(module_path)
            if tuple(sys.path) != before_path or os.getcwd() != before_cwd:
                raise _deny("DENIED_CAPABILITY", "candidate load changed sys.path or cwd")
            if tuple(id(item) for item in sys.meta_path) != before_meta_path or tuple(id(item) for item in sys.path_hooks) != before_path_hooks:
                raise _deny("DENIED_CAPABILITY", "candidate load changed finder or path hooks")
            allowed_new = set(candidate_names) | set(static_allowlist) | set(bootstrap_names)
            new_modules = set(sys.modules) - set(before_modules)
            if not new_modules.issubset(allowed_new):
                raise _deny("DENIED_CAPABILITY", "candidate load used ambient or fallback modules")
            for name, identity in before_modules.items():
                if name not in sys.modules or id(sys.modules[name]) != identity:
                    raise _deny("DENIED_CAPABILITY", "candidate load reused or mutated a preloaded module")
            self.loaded_bindings = tuple(_mapping(item, LOADED_MODULE_BINDING_FIELDS, "loaded module binding") for item in modules)
            self.permitted_candidate_load_count += 1
            return self.loaded_bindings
        except EvaluationError:
            for name in reversed(inserted):
                sys.modules.pop(name, None)
            raise
        except Exception as exc:
            for name in reversed(inserted):
                sys.modules.pop(name, None)
            raise _deny("DENIED_CAPABILITY", "candidate load failed closed") from exc
        finally:
            builtins.__import__ = previous_import
            importlib.import_module = previous_import_module
            sys.dont_write_bytecode = previous_dont_write_bytecode

    @contextlib.contextmanager
    def writer_trace(
        self,
        target_relative_paths: Sequence[str] = (),
        *,
        root_relative_path: str = "",
        parent_relative_path: str = "",
        context: provenance.ExecutionContext | None = None,
        output_artifacts: Sequence[provenance.ArtifactRef] | None = None,
    ):
        """Use the real CPython opcode channel and record every P0 writer call."""
        self._validate_trace_plan()
        if self._trace.phase != "POST_PERMIT":
            raise _deny(POST_PERMIT_TRACE_DENY, "writer trace was not admitted after permit")
        if threading.get_ident() != self.writer_trace_plan["trace_thread_id"]:
            raise _deny(POST_PERMIT_TRACE_DENY, "writer trace thread changed")
        raw_target_paths = list(target_relative_paths)
        target_paths = [normalize_relative_path(value, allow_root=False) for value in raw_target_paths]
        fixed_output_roles = tuple(target_paths) == EVALUATION_OUTPUT_ROLE_ORDER
        if target_paths != raw_target_paths or (not fixed_output_roles and target_paths != sorted(target_paths, key=lambda value: value.encode("utf-8"))):
            raise _deny("PATH_ESCAPE", "writer target paths are not canonically ordered")
        if len(set(target_paths)) != len(target_paths) or len({value.casefold() for value in target_paths}) != len(target_paths):
            raise _deny("PATH_ESCAPE", "writer target paths collide")
        normalized_root = normalize_relative_path(root_relative_path, allow_root=True)
        normalized_parent = normalize_relative_path(parent_relative_path, allow_root=True)
        if (normalized_root, normalized_parent) != (root_relative_path, parent_relative_path):
            raise _deny("PATH_ESCAPE", "writer root or parent path is not canonical")
        expected_artifacts = tuple(output_artifacts or ())
        expected_by_path: dict[str, provenance.ArtifactRef] = {}
        if expected_artifacts:
            for artifact in expected_artifacts:
                path = normalize_relative_path(artifact.relative_path, allow_root=False)
                if path in expected_by_path or path not in target_paths:
                    raise _deny("DENIED_PROVENANCE", "writer artifact set is not one-to-one with target paths")
                expected_by_path[path] = artifact
            expected_paths = tuple(expected_by_path)
            if (tuple(target_paths) == EVALUATION_OUTPUT_ROLE_ORDER and expected_paths != EVALUATION_OUTPUT_ROLE_ORDER) or (tuple(target_paths) != EVALUATION_OUTPUT_ROLE_ORDER and tuple(sorted(expected_paths, key=lambda value: value.encode("utf-8"))) != tuple(target_paths)):
                raise _deny("DENIED_PROVENANCE", "writer artifact set does not cover target paths")
        owner_final_paths: list[str] = []
        if context is not None:
            admitted_root = provenance.execution_root(context, create=False)
            owner_root = _final_path(admitted_root, admitted_root, must_exist=False)
            if normalized_root != context.root_alias or normalized_parent != context.root_alias:
                raise _deny("DENIED_PROVENANCE", "writer root/parent alias is not bound to the active context")
            owner_final_paths = [
                str(_final_path(owner_root / value, owner_root, must_exist=False)) for value in target_paths
            ]
        if expected_artifacts and context is None:
            raise _deny("DENIED_PROVENANCE", "owner-bound writer artifacts require an explicit context")
        self._writer_expected_artifacts = expected_by_path
        self._writer_expected_final_paths = dict(zip(target_paths, owner_final_paths))
        self._writer_invocation_records = ()
        self._writer_trace_events = ()
        previous = sys.gettrace()
        target_code = provenance.safe_write_bytes.__code__
        active: OpcodeWriterTrace | None = None
        invocations: list[dict[str, Any]] = []

        def finish_invocation(trace: OpcodeWriterTrace) -> None:
            terminal_action = "raise" if trace.writer_raised else "return"
            terminal_offset = trace.raise_offset if terminal_action == "raise" else trace.return_offset
            if terminal_offset is None:
                raise _deny(POST_PERMIT_TRACE_DENY, "writer invocation has no terminal opcode offset")
            relative_path = getattr(trace, "relative_path", None)
            artifact = getattr(trace, "artifact", None)
            final_path = getattr(trace, "final_path", None)
            if not isinstance(relative_path, str) or artifact is None or not isinstance(final_path, str):
                raise _deny(POST_PERMIT_TRACE_DENY, "writer invocation owner metadata is incomplete")
            error = trace.exception
            invocation = {
                "invocation_schema_version": "P1-WRITER-INVOCATION-V1",
                "invocation_sequence": len(invocations) + 1,
                "phase": "POST_WRITE" if (trace.transaction_started or trace.writer_call_started) else "PRE_WRITE",
                "transaction_started": trace.transaction_started,
                "writer_call_started": trace.writer_call_started,
                "terminal_action": terminal_action,
                "terminal_outcome": f"{terminal_action}@{terminal_offset}",
                "transaction_offset": self.writer_trace_plan["transaction_call_offset"] if trace.transaction_started else None,
                "writer_offset": self.writer_trace_plan["writer_call_offset"] if trace.writer_call_started else None,
                "terminal_offset": terminal_offset,
                "target_relative_path": relative_path,
                "target_final_path": final_path,
                "artifact_identity": _artifact_identity(artifact),
                "module_path": provenance.safe_write_bytes.__module__,
                "source_ref": self.writer_trace_plan["provenance_source_ref"],
                "trace_plan_snapshot_hash": self.writer_trace_plan_snapshot_hash,
                "trace_hash": trace.trace_hash,
                "events": list(trace.events),
                "exception_code": _exception_code(error) if error is not None else None,
                "exception_type": type(error).__qualname__ if error is not None else None,
                "exception_message_sha256": sha256_bytes(str(error).encode("utf-8")) if error is not None else None,
                "partial_readback_status": "NOT_ATTEMPTED",
                "partial_length": None,
                "partial_sha256": None,
            }
            invocations.append(canonical_writer_invocation(invocation))

        def trace_function(frame: Any, event: str, arg: Any):
            nonlocal active
            if frame.f_code is not target_code:
                return trace_function
            if event == "call":
                if active is not None:
                    raise _deny(POST_PERMIT_TRACE_DENY, "nested P0 writer invocation is not permitted")
                frame.f_trace = trace_function
                frame.f_trace_opcodes = True
                relative_path = frame.f_locals.get("relative_path")
                artifact = frame.f_locals.get("artifact_ref")
                if not isinstance(relative_path, str) or relative_path not in expected_by_path or artifact is not expected_by_path[relative_path]:
                    raise _deny(POST_PERMIT_TRACE_DENY, "writer invocation target or artifact is not owner-bound")
                if context is None:
                    raise _deny(POST_PERMIT_TRACE_DENY, "writer invocation context is missing")
                owner_root = _final_path(provenance.execution_root(context, create=False), provenance.execution_root(context, create=False), must_exist=False)
                active = OpcodeWriterTrace(self.writer_trace_plan)
                active.phase = "POST_PERMIT"
                active.relative_path = normalize_relative_path(relative_path, allow_root=False)
                active.artifact = artifact
                active.final_path = str(_final_path(owner_root / active.relative_path, owner_root, must_exist=False))
            elif event == "opcode":
                if active is None:
                    raise _deny(POST_PERMIT_TRACE_DENY, "writer opcode event has no invocation")
                offset = int(frame.f_lasti)
                if offset == self.writer_trace_plan["transaction_call_offset"]:
                    active.observe("transaction_started", offset=offset)
                elif offset == self.writer_trace_plan["writer_call_offset"]:
                    active.observe("writer_call_started", offset=offset)
            elif event == "exception":
                if active is None:
                    raise _deny(POST_PERMIT_TRACE_DENY, "writer exception event has no invocation")
                if isinstance(arg, tuple) and len(arg) > 1 and isinstance(arg[1], BaseException):
                    active.exception = arg[1]
                active.observe("raise", offset=int(frame.f_lasti))
            elif event == "return":
                if active is None:
                    raise _deny(POST_PERMIT_TRACE_DENY, "writer return event has no invocation")
                active.observe("return", offset=int(frame.f_lasti))
                finished = active
                active = None
                finish_invocation(finished)
            else:
                return trace_function
            return trace_function

        sys.settrace(trace_function)
        hook_replaced = sys.gettrace() is not trace_function
        if hook_replaced:
            sys.settrace(previous)
            raise _deny(POST_PERMIT_TRACE_DENY, "writer opcode trace hook was replaced before the write")
        body_error: BaseException | None = None
        try:
            yield self._trace
        except BaseException as exc:
            body_error = exc
            raise
        finally:
            hook_replaced = hook_replaced or sys.gettrace() is not trace_function
            sys.settrace(previous)
            if active is not None:
                raise _deny(POST_PERMIT_TRACE_DENY, "writer invocation did not reach a terminal opcode event")
            aggregate_events: list[dict[str, Any]] = []
            for invocation in invocations:
                for event in invocation["events"]:
                    aggregate_events.append({**event, "sequence": len(aggregate_events) + 1})
            self._writer_invocation_records = tuple(invocations)
            self._writer_trace_events = tuple(aggregate_events)
            any_started = any(item["transaction_started"] or item["writer_call_started"] for item in invocations)
            raw_observation = {
                "writer_schema_version": "P1-WRITER-OBSERVATION-V1",
                "trace_plan_snapshot_hash": self.writer_trace_plan_snapshot_hash,
                "trace_backend_status": "VERIFIED",
                "phase": "POST_WRITE" if any_started else "PRE_WRITE",
                "transaction_started": any(item["transaction_started"] for item in invocations),
                "writer_call_started": any(item["writer_call_started"] for item in invocations),
                "writer_returned": bool(invocations) and body_error is None and all(item["terminal_action"] == "return" for item in invocations),
                "writer_raised": any(item["terminal_action"] == "raise" for item in invocations) or body_error is not None,
                "outcome": "RAISE" if body_error is not None else "RETURN",
                "exception_code": _exception_code(body_error) if body_error is not None else None,
                "exception_type": type(body_error).__qualname__ if body_error is not None else None,
                "exception_message_sha256": sha256_bytes(str(body_error).encode("utf-8")) if body_error is not None else None,
                "failure_reason": _exception_code(body_error) if body_error is not None else None,
                "failure_classification": (
                    POST_WRITE_IO_FAILURE if body_error is not None and any_started
                    else POST_PERMIT_TRACE_DENY if body_error is not None
                    else "NONE"
                ),
                "trace_hook_replaced": hook_replaced,
                "root_relative_path": root_relative_path,
                "parent_relative_path": parent_relative_path,
                "target_relative_path": target_paths,
                "target_relative_paths": target_paths,
                "partial_readback_status": "NOT_ATTEMPTED",
                "partial_length": None,
                "partial_sha256": None,
                "residue_snapshot_hash": None,
                "root_final_path": None,
                "parent_final_path": None,
                "target_final_paths": owner_final_paths,
                "trace_hash": canonical_sha256({"events": aggregate_events}, fields=("events",)),
                "events": aggregate_events,
                "writer_invocations": [dict(item) for item in invocations],
            }
            owner_observation = self._validate_owner_writer_observation(raw_observation)
            self.writer_phase_observation = owner_observation
            self._owner_writer_observation = dict(owner_observation)
            self._owner_writer_observation_bytes = canonical_evaluation_json_bytes(
                owner_observation, fields=DETERMINISTIC_WRITER_OBSERVATION_FIELDS,
            )
        if hook_replaced:
            raise _deny(POST_PERMIT_TRACE_DENY, "writer opcode trace hook changed during the write")
        if not invocations or any(not item["transaction_started"] for item in invocations):
            raise _deny(
                POST_PERMIT_TRACE_DENY,
                "opcode trace did not observe a complete per-call transaction",
                expected_offsets=(self.writer_trace_plan["transaction_call_offset"], self.writer_trace_plan["writer_call_offset"]),
                events=list(self._writer_trace_events),
            )
        if body_error is None and any(not item["writer_call_started"] for item in invocations):
            raise _deny(POST_PERMIT_TRACE_DENY, "successful output call lacked an exact writer offset")


def _validate_entry_array(entries: Sequence[Mapping[str, Any]], *, name: str) -> tuple[dict[str, Any], ...]:
    return canonical_residue_entries(list(entries), name=name)


def _entry_kind(item: Mapping[str, Any]) -> str:
    kind = item.get("entry_kind")
    if kind not in {"DIRECTORY", "FILE", "PARTIAL_FILE", "MISSING"}:
        raise _deny("DENIED_RESIDUE", "unknown entry kind")
    if kind == "PARTIAL_FILE":
        raise _deny("DENIED_RESIDUE", "partial files cannot participate in a residue pairing")
    if item.get("reparse_status") != "VERIFIED" or item.get("containment_status") != "VERIFIED":
        raise _deny("DENIED_RESIDUE", "entry reparse/containment was not verified")
    return str(kind)


def build_residue_pairing(
    expected_entries: Sequence[Mapping[str, Any]],
    actual_entries: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    expected = _validate_entry_array(expected_entries, name="expected_entries")
    actual = _validate_entry_array(actual_entries, name="entries")
    expected_by_key = {relative_path_key_utf8_hex(item["relative_path"]): item for item in expected}
    actual_by_key = {relative_path_key_utf8_hex(item["relative_path"]): item for item in actual}
    final_identity_by_key: dict[str, str] = {}
    for item in (*expected, *actual):
        identity = str(item["final_identity"]).casefold()
        previous_path = final_identity_by_key.get(identity)
        if previous_path is not None and previous_path != item["relative_path"]:
            raise _deny("DENIED_RESIDUE", "different relative paths share a final identity")
        final_identity_by_key[identity] = item["relative_path"]
    records: list[dict[str, Any]] = []
    for key in sorted(set(expected_by_key) | set(actual_by_key), key=lambda value: bytes.fromhex(value)):
        exp = expected_by_key.get(key)
        act = actual_by_key.get(key)
        path = exp["relative_path"] if exp is not None else act["relative_path"]
        if exp is None:
            if act.get("entry_role") != "UNEXPECTED":
                raise _deny("DENIED_RESIDUE", "actual-only residue must use the UNEXPECTED role")
            actual_kind = _entry_kind(act)
            if actual_kind == "MISSING":
                raise _deny("DENIED_RESIDUE", "actual-only residue cannot be MISSING")
            record = {"pairing_schema_version": "RESIDUE_PAIRING_V2", "kind_compatibility_matrix_version": "RESIDUE_KIND_COMPATIBILITY_V1", "kind_compatibility_matrix_hash": compatibility_matrix_hash(), "relative_path": path, "relative_path_key_utf8_hex": key, "expected_count": 0, "actual_count": 1, "expected_entry_role": None, "actual_entry_role": "UNEXPECTED", "actual_exists": bool(act.get("exists")), "expected_entry_kind": None, "actual_entry_kind": actual_kind, "pair_status": "UNEXPECTED_ACTUAL"}
        elif act is None:
            exp_kind = _entry_kind(exp)
            if exp_kind == "MISSING":
                raise _deny("DENIED_RESIDUE", "missing expected entry must have an explicit actual record")
            validate_role_kind(str(exp.get("entry_role")), exp_kind)
            record = {"pairing_schema_version": "RESIDUE_PAIRING_V2", "kind_compatibility_matrix_version": "RESIDUE_KIND_COMPATIBILITY_V1", "kind_compatibility_matrix_hash": compatibility_matrix_hash(), "relative_path": path, "relative_path_key_utf8_hex": key, "expected_count": 1, "actual_count": 0, "expected_entry_role": exp.get("entry_role"), "actual_entry_role": None, "actual_exists": None, "expected_entry_kind": exp.get("entry_kind"), "actual_entry_kind": None, "pair_status": "MISSING_ACTUAL_RECORD"}
        else:
            if exp.get("entry_role") != act.get("entry_role"):
                raise _deny("DENIED_RESIDUE", "same-key expected and actual roles differ")
            exp_kind = _entry_kind(exp)
            act_kind = _entry_kind(act)
            if exp_kind != "MISSING":
                validate_role_kind(str(exp.get("entry_role")), exp_kind)
            if exp_kind == "MISSING" or act_kind == "MISSING" or act.get("exists") is False:
                status = "MISSING_EXPECTED"
            else:
                validate_role_kind(str(exp.get("entry_role")), act_kind)
                if exp.get("final_identity").casefold() != act.get("final_identity").casefold():
                    raise _deny("DENIED_RESIDUE", "same-key final identity differs")
                status = "MATCHED"
            record = {"pairing_schema_version": "RESIDUE_PAIRING_V2", "kind_compatibility_matrix_version": "RESIDUE_KIND_COMPATIBILITY_V1", "kind_compatibility_matrix_hash": compatibility_matrix_hash(), "relative_path": path, "relative_path_key_utf8_hex": key, "expected_count": 1, "actual_count": 1, "expected_entry_role": exp.get("entry_role"), "actual_entry_role": act.get("entry_role"), "actual_exists": bool(act.get("exists")), "expected_entry_kind": exp_kind, "actual_entry_kind": act_kind, "pair_status": status}
        records.append(_mapping(record, RESIDUE_PAIRING_FIELDS, "residue pairing"))
    return tuple(records)


def build_residue_snapshot(
    *,
    root_relative_alias: str,
    expected_entries: Sequence[Mapping[str, Any]],
    actual_entries: Sequence[Mapping[str, Any]],
    enumeration_complete: bool = True,
    enumeration_failure: str | None = None,
) -> dict[str, Any]:
    if enumeration_complete is not True or enumeration_failure is not None:
        raise _deny("DENIED_RESIDUE", "incomplete residue enumeration cannot be hashed")
    expected = tuple(_validate_entry_array(expected_entries, name="expected_entries"))
    actual = tuple(_validate_entry_array(actual_entries, name="entries"))
    pairing = build_residue_pairing(expected, actual)
    pairing_hash = canonical_pairing_hash(pairing)
    value = {"residue_schema_version": "RESIDUE_SNAPSHOT_V2", "root_relative_alias": root_relative_alias, "residue_array_order": RESIDUE_ARRAY_ORDER, "expected_entries": [dict(item) for item in expected], "entries": [dict(item) for item in actual], "residue_pairing": [dict(item) for item in pairing], "residue_pairing_hash": pairing_hash, "enumeration_complete": True, "enumeration_failure": None}
    return _mapping(value, RESIDUE_SNAPSHOT_PREIMAGE_FIELDS, "residue snapshot")


def residue_snapshot_hash(snapshot: Mapping[str, Any]) -> str:
    return canonical_sha256(canonical_residue_snapshot(snapshot), fields=RESIDUE_SNAPSHOT_PREIMAGE_FIELDS)


def build_evaluation_manifest(
    *,
    evaluation_case_id: str,
    context: provenance.ExecutionContext,
    input_artifact: provenance.ArtifactRef,
    resolver_snapshot_hash: str,
    rule_set_id: str,
    rule_set_version: str,
    rule_registry: RuleSetRegistryV1,
    source_registry: EvaluatorSourceRegistryV1,
    contract_registry: ContractRegistryV1,
    census: P1CapabilityCensusV1,
    gate: P1PreImportGateV1,
    resolution_guard_snapshot_hash: str,
    writer_trace_plan_snapshot_hash: str,
    expected_schema_id: str,
    declared_metrics: Sequence[str],
) -> EvaluationInputManifestV1:
    lineage = provenance.artifact_lineage(input_artifact)
    rule_entry = rule_registry.select(rule_set_id, rule_set_version)
    contract_entry = contract_registry.select("offline-deterministic-v1", "1")
    value = {
        "manifest_schema_version": "v1", "evaluation_case_id": evaluation_case_id,
        "project_id": context.project_id, "project_revision": context.namespace.project_revision,
        "profile_id": context.profile.profile_id, "profile_version": context.profile.profile_version,
        "profile_definition_hash": context.profile.profile_definition_hash, "genre_identity": context.genre_identity,
        "namespace_digest": context.namespace_digest, "project_registry_snapshot_hash": context.registry.registry_snapshot_hash,
        "input_artifact_identity": lineage, "artifact_resolver_snapshot_hash": resolver_snapshot_hash,
        "parent_store_snapshot_hash": context.parent_store.snapshot_hash, "capability_census_snapshot_hash": census.snapshot_hash,
        "preimport_gate_snapshot_hash": gate.snapshot_hash, "resolution_guard_snapshot_hash": resolution_guard_snapshot_hash,
        "writer_trace_plan_snapshot_hash": writer_trace_plan_snapshot_hash, "rule_set_id": rule_set_id,
        "rule_set_version": rule_set_version, "rule_set_registry_snapshot_hash": rule_registry.snapshot_hash,
        "rule_set_bytes_sha256": rule_entry["rule_set_bytes_sha256"], "evaluator_source_registry_snapshot_hash": _evaluator_source_snapshot_hash(source_registry),
        "evaluator_source_hash": _evaluator_source_hash(source_registry), "contract_id": "offline-deterministic-v1",
        "contract_version": "1", "contract_registry_snapshot_hash": contract_registry.snapshot_hash,
        "evaluation_contract_hash": contract_entry["contract_bytes_sha256"], "expected_schema_id": expected_schema_id,
        "declared_metrics": list(declared_metrics),
    }
    return EvaluationInputManifestV1.from_mapping(value)


def build_evaluation_binding(
    manifest: EvaluationInputManifestV1,
    *,
    input_manifest_hash: str | None = None,
    rule_set_bytes_sha256: str | None = None,
    evaluation_contract_hash: str | None = None,
) -> EvaluationBindingV1:
    effective_input_manifest_hash = manifest.manifest_hash if input_manifest_hash is None else input_manifest_hash
    _hash(effective_input_manifest_hash, "input_manifest_hash")
    effective_rule_hash = manifest.rule_set_bytes_sha256 if rule_set_bytes_sha256 is None else rule_set_bytes_sha256
    effective_contract_hash = manifest.evaluation_contract_hash if evaluation_contract_hash is None else evaluation_contract_hash
    _hash(effective_rule_hash, "rule_set_bytes_sha256")
    _hash(effective_contract_hash, "evaluation_contract_hash")
    value = {"binding_schema_version": "P1-EVALUATION-BINDING-V1", "evaluation_case_id": manifest.evaluation_case_id, "project_registry_snapshot_hash": manifest.project_registry_snapshot_hash, "input_manifest_hash": effective_input_manifest_hash, "artifact_resolver_snapshot_hash": manifest.artifact_resolver_snapshot_hash, "parent_store_snapshot_hash": manifest.parent_store_snapshot_hash, "capability_census_snapshot_hash": manifest.capability_census_snapshot_hash, "preimport_gate_snapshot_hash": manifest.preimport_gate_snapshot_hash, "resolution_guard_snapshot_hash": manifest.resolution_guard_snapshot_hash, "writer_trace_plan_snapshot_hash": manifest.writer_trace_plan_snapshot_hash, "rule_set_id": manifest.rule_set_id, "rule_set_version": manifest.rule_set_version, "rule_set_registry_snapshot_hash": manifest.rule_set_registry_snapshot_hash, "rule_set_bytes_sha256": effective_rule_hash, "evaluator_source_registry_snapshot_hash": manifest.evaluator_source_registry_snapshot_hash, "evaluator_source_hash": manifest.evaluator_source_hash, "contract_id": manifest.contract_id, "contract_version": manifest.contract_version, "contract_registry_snapshot_hash": manifest.contract_registry_snapshot_hash, "evaluation_contract_hash": effective_contract_hash, "expected_schema_id": manifest.expected_schema_id, "declared_metrics": list(manifest.declared_metrics)}
    return EvaluationBindingV1.from_mapping(value)


@dataclass(frozen=True)
class OfflineEvaluationResult:
    semantic_result: Mapping[str, Any]
    full_evidence: Mapping[str, Any]
    batch: provenance.ExecutionBatch
    envelope: provenance.EvidenceEnvelope
    output_artifacts: tuple[provenance.ArtifactRef, ...]
    output_paths: tuple[Path, ...]
    metrics: MetricsReport


class OfflineDeterministicEvaluator:
    def __init__(
        self,
        *,
        context: provenance.ExecutionContext,
        resolver: OwnerArtifactResolver,
        owner_harness: OwnerHarness,
        rule_set_registry: RuleSetRegistryV1,
        contract_registry: ContractRegistryV1,
        census: P1CapabilityCensusV1,
        gate: P1PreImportGateV1,
        resolution_guard: Mapping[str, Any],
        writer_trace_plan: Mapping[str, Any],
        observer: P1CapabilityObserver | None = None,
    ) -> None:
        if not isinstance(context, provenance.ExecutionContext):
            raise _deny("MISSING_PROJECT_CONTEXT", "evaluator requires explicit context")
        self.context = context
        self.resolver = resolver
        self.owner_harness = owner_harness
        self.rule_set_registry = rule_set_registry
        self.contract_registry = contract_registry
        self.census = census
        self.gate = gate
        self.resolution_guard = dict(resolution_guard)
        self.writer_trace_plan = dict(writer_trace_plan)
        if observer is not None:
            raise _deny("DENIED_CAPABILITY", "evaluator cannot accept a caller-supplied observer")
        if hasattr(resolver, "observer"):
            raise _deny("DENIED_CAPABILITY", "resolver cannot expose an independent observer")
        self.observer = owner_harness.observer
        if self.observer is not owner_harness.observer:
            raise _deny("DENIED_CAPABILITY", "evaluator observer is not the owner observer")
        if resolver.context is not context and resolver.context.namespace_digest != context.namespace_digest:
            raise _deny("DENIED_PROVENANCE", "resolver context is not evaluator context")

    def _check_manifest(self, manifest: EvaluationInputManifestV1) -> tuple[str, str]:
        checks = (("project_id", self.context.project_id), ("project_revision", self.context.namespace.project_revision), ("profile_id", self.context.profile.profile_id), ("profile_version", self.context.profile.profile_version), ("profile_definition_hash", self.context.profile.profile_definition_hash), ("genre_identity", self.context.genre_identity), ("namespace_digest", self.context.namespace_digest), ("project_registry_snapshot_hash", self.context.registry.registry_snapshot_hash), ("parent_store_snapshot_hash", self.context.parent_store.snapshot_hash), ("capability_census_snapshot_hash", self.census.snapshot_hash), ("preimport_gate_snapshot_hash", self.gate.snapshot_hash), ("resolution_guard_snapshot_hash", canonical_sha256(self.resolution_guard)), ("writer_trace_plan_snapshot_hash", canonical_sha256(self.writer_trace_plan)), ("rule_set_registry_snapshot_hash", self.rule_set_registry.snapshot_hash), ("evaluator_source_registry_snapshot_hash", _evaluator_source_snapshot_hash(self.owner_harness.source_registry)), ("evaluator_source_hash", _evaluator_source_hash(self.owner_harness.source_registry)), ("contract_registry_snapshot_hash", self.contract_registry.snapshot_hash))
        for field_name, expected in checks:
            if getattr(manifest, field_name) != expected:
                raise _deny("DENIED_PROVENANCE", f"manifest {field_name} mismatch")
        rule_entry = self.rule_set_registry.select(manifest.rule_set_id, manifest.rule_set_version)
        contract_entry = self.contract_registry.select(manifest.contract_id, manifest.contract_version)
        rule_bytes = RuleSetRegistryV1.bytes_for(rule_entry)
        contract_bytes = ContractRegistryV1.bytes_for(contract_entry)
        _strict_bytes(rule_bytes, "owner rule-set bytes")
        _strict_bytes(contract_bytes, "owner contract bytes")
        owner_rule_hash = sha256_bytes(rule_bytes)
        owner_contract_hash = sha256_bytes(contract_bytes)
        if owner_rule_hash != rule_entry["rule_set_bytes_sha256"] or owner_contract_hash != contract_entry["contract_bytes_sha256"]:
            raise _deny("DENIED_PROVENANCE", "owner registry bytes failed rehash")
        if manifest.rule_set_bytes_sha256 != owner_rule_hash:
            raise _deny("DENIED_PROVENANCE", "manifest rule-set hash is not owner-derived")
        if manifest.evaluation_contract_hash != owner_contract_hash:
            raise _deny("DENIED_PROVENANCE", "manifest contract hash is not owner-derived")
        return owner_rule_hash, owner_contract_hash

    def _p1ae_source_binding(self, relative_path: str) -> dict[str, Any]:
        """Read one owner-registered P1-AE source and verify its bytes."""
        entry = self.owner_harness.source_registry.entry_for(relative_path)
        path = _final_path(self.owner_harness.source_root / entry["relative_path"], self.owner_harness.source_root, must_exist=True)
        content = _strict_bytes(path.read_bytes(), f"P1-AE source {relative_path}")
        self.owner_harness.source_registry.verify_bytes(entry, content)
        return {
            "relative_path": entry["relative_path"], "source_ref": entry["source_ref"],
            "length": len(content), "sha256": sha256_bytes(content), "content": content,
        }

    def _p1ae_pure_loader_legacy_unused(self, owner_input: Mapping[str, Any], *, batch_id: str,
                          attempt_id: str) -> Any:
        """Run the independent P1-AE permit/CAS/loader transaction.

        This method intentionally does not call ``OwnerHarness.load_candidates``
        and does not read the host gate's candidate set.  All values needed by
        the pure transaction are recomputed from the owner source registry,
        owner resolution snapshot and the supplied in-memory bundle.
        """
        if not isinstance(owner_input, Mapping):
            raise _deny("DENIED_INPUT", "quality owner input must be a mapping")
        bundle = owner_input.get("canonical_quality_bundle", owner_input.get("quality_bundle"))
        if not isinstance(bundle, Mapping):
            raise _deny("DENIED_INPUT", "quality bundle must be owner-injected in memory")
        source_registry = self.owner_harness.source_registry
        owner_id = source_registry.value["owner_id"]
        authority_ref = source_registry.value["authoritative_source_ref"]
        quality_entry = next((entry for entry in source_registry.value["entries"] if entry["relative_path"].endswith("quality_evaluation.py")), None)
        contract_entry = next((entry for entry in source_registry.value["entries"] if entry["relative_path"].endswith("evaluation_contracts.py")), None)
        metrics_entry = next((entry for entry in source_registry.value["entries"] if entry["relative_path"].endswith("evaluation_metrics.py")), None)
        if quality_entry is None or contract_entry is None or metrics_entry is None:
            raise _deny("DENIED_PROVENANCE", "P1-AE pure source registry lacks the three owner-bound modules")
        quality_source = self._p1ae_source_binding(quality_entry["relative_path"])
        contract_source = self._p1ae_source_binding(contract_entry["relative_path"])
        metrics_source = self._p1ae_source_binding(metrics_entry["relative_path"])
        source_bindings = [
            {key: item[key] for key in ("relative_path", "source_ref", "length", "sha256")}
            for item in (contract_source, metrics_source, quality_source)
        ]
        source_bindings.sort(key=lambda item: item["relative_path"].encode("utf-8"))
        source_module_binding_hash = _p1ae_canonical_sha256({"entries": source_bindings}, fields=("entries",))
        empty_events = {"events": [], "event_hash": sha256_bytes(_p1ae_canonical_bytes({"events": []}, fields=("events",))), "event_count": 0, "trace_complete": True, "status": "CLEAR", "terminal_state": "NONE", "projection_schema_version": "P1_AE_FORBIDDEN_IMPORT_PROJECTION_V1"}
        forbidden_hash = _p1ae_canonical_sha256(empty_events, fields=P1_AE_FORBIDDEN_IMPORT_PROJECTION_FIELDS)
        transition_hash = p1ae_transition_registry_hash("READY")
        resolution_guard_hash = self.owner_harness.resolution_guard_snapshot_hash
        resolution_live_hash = self.owner_harness.resolution_live_snapshot_hash
        pure_gate_hash = _p1ae_canonical_sha256({"gate_schema_version": "P1_AE_PURE_GATE_V1", "owner_id": owner_id, "authority_ref": authority_ref, "status": "READY"}, fields=("gate_schema_version", "owner_id", "authority_ref", "status"))
        loader_plan = {
            "loader_plan_schema_version": "P1_AE_PURE_LOADER_PLAN_V1", "plan_id": f"{batch_id}:{attempt_id}",
            "owner_id": owner_id, "authority_ref": authority_ref, "owner_session_ref": self.owner_harness.owner_session_id,
            "pure_source_registry_snapshot_hash": source_registry.snapshot_hash, "source_module_binding_hash": source_module_binding_hash,
            "pure_gate_snapshot_hash": pure_gate_hash, "resolution_guard_snapshot_hash": resolution_guard_hash,
            "resolution_live_snapshot_hash": resolution_live_hash, "bootstrap_sequence": [contract_entry["relative_path"], metrics_entry["relative_path"]],
            "candidate_root_sequence": [quality_entry["relative_path"]], "candidate_static_sequence": [],
            "cpython_internal_expected_sequence": [], "cpython_internal_expected_edge_count": 0,
            "cpython_internal_expected_event_count": 0, "forbidden_expected_count": 0,
            "forbidden_expected_tuple_registry_hash": forbidden_hash, "host_loader_invoked": False,
            "host_gate_mutated": False, "host_permit_mutated": False, "host_candidate_set_read": False,
            "permit_consumed_before_import": True, "pre_permit_state": "PURE_PERMIT_ISSUED",
            "post_cas_state": "CAS_CONSUMED", "next_required_state": "INTERNAL_PREFLIGHT_RECHECKED",
            "transition_status": "ALLOWED", "transition_registry_hash": transition_hash, "status": "READY",
        }
        loader_binding = p1ae_loader_plan_binding(loader_plan)
        expected_observation = {
            "observation_schema_version": "P1_AE_PURE_IMPORT_EXPECTED_OBSERVATION_V1", "owner_id": owner_id,
            "authority_ref": authority_ref, "source_registry_snapshot_hash": source_registry.snapshot_hash,
            "source_module_binding_hash": source_module_binding_hash, **loader_binding,
            "transition_fields": list(P1_AE_PURE_LOADER_PLAN_TRANSITION_TUPLE),
            "cpython_internal_expected_edges_hash": sha256_bytes(_p1ae_canonical_bytes({"edges": []}, fields=("edges",))),
            "cpython_internal_expected_events_hash": sha256_bytes(_p1ae_canonical_bytes({"events": []}, fields=("events",))),
            "cpython_internal_expected_edge_count": 0, "cpython_internal_expected_event_count": 0,
            "forbidden_expected_events_hash": empty_events["event_hash"], "forbidden_expected_count": 0,
            "forbidden_expected_tuple_registry_hash": forbidden_hash, "phase": "HOST_STATIC_BOUND", "status": "READY",
        }
        expected_hash = p1ae_expected_observation_hash(expected_observation)
        package = {
            "package_schema_version": "P1_AE_PURE_PACKAGE_V1", "owner_id": owner_id, "authority_ref": authority_ref,
            "source_registry_hash": source_registry.snapshot_hash, "source_module_binding_hash": source_module_binding_hash,
            "loader_plan_hash": loader_binding["loader_plan_hash"], "loader_plan_length": loader_binding["loader_plan_length"],
            "transition_registry_hash": transition_hash, "transition_fields": list(P1_AE_PURE_LOADER_PLAN_TRANSITION_TUPLE),
            "resolution_guard_hash": resolution_guard_hash, "resolution_live_hash": resolution_live_hash,
            "expected_observation_hash": expected_hash, "status": "READY",
        }
        package_hash = _p1ae_canonical_sha256(package, fields=P1_AE_PACKAGE_FIELDS)
        gate = dict(package)
        gate_hash = _p1ae_canonical_sha256(gate, fields=P1_AE_GATE_PREIMAGE_FIELDS)
        permit_preimage = {
            "permit_schema_version": "P1_AE_PURE_IMPORT_PERMIT_V1", "owner_id": owner_id, "authority_ref": authority_ref,
            "owner_session_ref": self.owner_harness.owner_session_id, "package_hash": package_hash,
            "loader_plan_hash": loader_binding["loader_plan_hash"], "loader_plan_length": loader_binding["loader_plan_length"],
            "transition_registry_hash": transition_hash, "transition_fields": list(P1_AE_PURE_LOADER_PLAN_TRANSITION_TUPLE),
            "expected_observation_hash": expected_hash, "status": "READY",
        }
        permit_secret = object()
        permit_private_handle = object()
        permit = issue_p1ae_pure_permit(owner_session_ref=self.owner_harness.owner_session_id,
                                        preimage=permit_preimage, secret=permit_secret,
                                        private_handle=permit_private_handle)
        consumed_digest = permit.consume(secret=permit_secret, private_handle=permit_private_handle)

        # PURE_INTERNAL_PREFLIGHT_RECHECKED: reread every source/plan input and
        # compare the consumed permit digest before dynamic execution begins.
        reread_quality = self._p1ae_source_binding(quality_entry["relative_path"])
        if reread_quality["sha256"] != quality_source["sha256"] or p1ae_loader_plan_hash(loader_plan) != loader_binding["loader_plan_hash"] or len(p1ae_loader_plan_bytes(loader_plan)) != loader_binding["loader_plan_length"]:
            raise _deny("DENIED_CAPABILITY", "P1-AE preflight source or loader-plan mismatch")
        if p1ae_transition_registry_hash("READY") != transition_hash:
            raise _deny("DENIED_CAPABILITY", "P1-AE preflight transition registry mismatch")
        if tuple(loader_plan[field] for field in P1_AE_PURE_LOADER_PLAN_TRANSITION_FIELDS) != tuple(permit_preimage["transition_fields"]):
            raise _deny("DENIED_CAPABILITY", "P1-AE preflight transition tuple mismatch")
        if p1ae_expected_observation_hash(expected_observation) != permit_preimage["expected_observation_hash"] or _p1ae_canonical_sha256(permit_preimage, fields=P1_AE_PERMIT_PREIMAGE_FIELDS) != consumed_digest:
            raise _deny("DENIED_CAPABILITY", "P1-AE preflight permit digest mismatch")

        # Static source audit is owner-side evidence for the bootstrap edge;
        # the dynamic candidate is loaded once from its exact readback path.
        tree = ast.parse(reread_quality["content"].decode("utf-8"), filename=quality_entry["relative_path"])
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(name not in {"__future__", "dataclasses", "hashlib", "typing", "fractions", "decimal", "unicodedata", ".evaluation_contracts", ".evaluation_metrics"} and not name.endswith("evaluation_contracts") and not name.endswith("evaluation_metrics") for name in names):
                raise _deny("DENIED_CAPABILITY", "P1-AE quality module has an unregistered import edge")
        spec = importlib.util.spec_from_file_location("xiaoshuo.pipeline.quality_evaluation", self.owner_harness.source_root / quality_entry["relative_path"])
        if spec is None or spec.loader is None:
            raise _deny("DENIED_CAPABILITY", "P1-AE quality module spec unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if not hasattr(module, "evaluate_quality_bundle"):
            raise _deny("DENIED_CAPABILITY", "P1-AE quality module entry point is missing")
        transaction = {
            "transaction_schema_version": P1_AE_PURE_LOADER_TRANSACTION_SCHEMA_VERSION, "transaction_id": f"{batch_id}:{attempt_id}",
            "owner_id": owner_id, "authority_ref": authority_ref, "owner_session_ref": self.owner_harness.owner_session_id,
            "loader_plan_hash": loader_binding["loader_plan_hash"], "loader_plan_length": loader_binding["loader_plan_length"],
            "transition_registry_hash": transition_hash, "transition_fields": list(P1_AE_PURE_LOADER_PLAN_TRANSITION_TUPLE),
            "permit_digest": consumed_digest, "permit_cas_sequence": 1, "dynamic_load_count": 1,
            "dynamic_load_order": [quality_entry["relative_path"]], "forbidden_projection_hash": forbidden_hash,
            "observed_projection_hash": forbidden_hash, "state": "COMMITTED", "status": "READY",
        }
        transaction_hash = _p1ae_canonical_sha256(transaction, fields=P1_AE_LOADER_TRANSACTION_PREIMAGE_FIELDS)
        result = module.evaluate_quality_bundle({
            "admission_schema_version": P1_AE_OWNER_ADMISSION_SCHEMA_VERSION, "owner_id": owner_id,
            "authority_ref": authority_ref, "owner_session_ref": self.owner_harness.owner_session_id,
            "package_hash": package_hash, "gate_hash": gate_hash, "permit_digest": consumed_digest,
            "loader_plan_hash": loader_binding["loader_plan_hash"], "loader_plan_length": loader_binding["loader_plan_length"],
            "transition_registry_hash": transition_hash, "transition_fields": list(P1_AE_PURE_LOADER_PLAN_TRANSITION_TUPLE),
            "transaction_hash": transaction_hash, "status": "ADMITTED",
        }, bundle)
        return result, transaction_hash

    def evaluate_quality(self, owner_input: Mapping[str, Any], batch_id: str, attempt_id: str) -> Any:
        """The only P1-AE owner hook; it does not alter the existing evaluate()."""
        result, _transaction_hash = self._p1ae_pure_loader(owner_input, batch_id=batch_id, attempt_id=attempt_id)
        return result

    def _expected_residue_entries(self, output_refs: Sequence[provenance.ArtifactRef]) -> tuple[dict[str, Any], ...]:
        entries: dict[str, dict[str, Any]] = {
            "": {
                "relative_path": "", "entry_role": "ROOT", "entry_kind": "DIRECTORY",
                "exists": True, "readable": True, "content_length": None, "content_sha256": None,
                "readback_status": "EXPECTED", "reparse_status": "VERIFIED",
                "containment_status": "VERIFIED", "final_identity": "",
            }
        }
        for ref in output_refs:
            path = normalize_relative_path(ref.relative_path, allow_root=False)
            parts = path.split("/")
            for index in range(1, len(parts)):
                parent = "/".join(parts[:index])
                entries.setdefault(parent, {
                    "relative_path": parent, "entry_role": "EXPECTED_PARENT", "entry_kind": "DIRECTORY",
                    "exists": True, "readable": True, "content_length": None, "content_sha256": None,
                    "readback_status": "EXPECTED", "reparse_status": "VERIFIED",
                    "containment_status": "VERIFIED", "final_identity": "",
                })
            entries[path] = {
                "relative_path": path, "entry_role": "EXPECTED_TARGET", "entry_kind": "FILE",
                "exists": True, "readable": True, "content_length": ref.length, "content_sha256": ref.sha256,
                "readback_status": "EXPECTED", "reparse_status": "VERIFIED",
                "containment_status": "VERIFIED", "final_identity": "",
            }
        return tuple(entries[key] for key in sorted(entries, key=lambda item: item.encode("utf-8")))

    def _enumerate_residue(
        self,
        root: Path,
        output_refs: Sequence[provenance.ArtifactRef],
        *,
        classify_mismatch_as_partial: bool = False,
    ) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
        """Read-only complete residue enumeration with final path checks."""
        expected = [dict(item) for item in self._expected_residue_entries(output_refs)]
        for item in expected:
            item["final_identity"] = str(_final_path(root / item["relative_path"], root, must_exist=False))
        expected_by_path = {item["relative_path"]: item for item in expected}
        actual_by_path: dict[str, dict[str, Any]] = {}

        def missing_item(item: Mapping[str, Any]) -> dict[str, Any]:
            candidate = _final_path(root / item["relative_path"], root, must_exist=False)
            result = dict(item)
            result.update({"entry_kind": "MISSING", "exists": False, "readable": False, "content_length": None, "content_sha256": None,
                           "readback_status": "MISSING", "reparse_status": "VERIFIED",
                           "containment_status": "VERIFIED", "final_identity": str(candidate)})
            return result

        if root.exists():
            verified_root = _final_path(root, root, must_exist=True)
            if not verified_root.is_dir():
                actual_by_path[""] = {**dict(expected_by_path[""]), "entry_kind": "FILE", "exists": True, "final_identity": str(verified_root)}
            else:
                actual_by_path[""] = {**dict(expected_by_path[""]), "final_identity": str(verified_root)}
                stack: list[tuple[Path, str]] = [(verified_root, "")]
                while stack:
                    current, current_relative = stack.pop()
                    with os.scandir(current) as scan:
                        children = list(scan)
                    children.sort(key=lambda item: unicodedata.normalize("NFC", item.name).encode("utf-8"))
                    previous_name: bytes | None = None
                    for child in children:
                        name = unicodedata.normalize("NFC", child.name)
                        if name != child.name or name in {"", ".", ".."}:
                            raise _deny("DENIED_RESIDUE", "residue entry name is not canonical")
                        name_key = name.encode("utf-8")
                        if previous_name is not None and name_key <= previous_name:
                            raise _deny("DENIED_RESIDUE", "residue enumeration is not strictly ordered")
                        previous_name = name_key
                        relative = f"{current_relative}/{name}" if current_relative else name
                        target = _final_path(Path(child.path), verified_root, must_exist=True)
                        role = expected_by_path.get(relative, {}).get("entry_role", "UNEXPECTED")
                        is_directory = child.is_dir(follow_symlinks=False)
                        is_file = child.is_file(follow_symlinks=False)
                        if not is_directory and not is_file:
                            raise _deny("DENIED_RESIDUE", "unknown residue filesystem kind")
                        kind = "DIRECTORY" if is_directory else "PARTIAL_FILE" if name.endswith(".partial") else "FILE"
                        item = {
                            "relative_path": relative, "entry_role": role, "entry_kind": kind,
                            "exists": True, "readable": True, "content_length": None, "content_sha256": None,
                            "readback_status": "DIRECTORY" if is_directory else "PARTIAL" if kind == "PARTIAL_FILE" else "READ",
                            "reparse_status": "VERIFIED", "containment_status": "VERIFIED",
                            "final_identity": str(target),
                        }
                        if is_file:
                            raw = _strict_bytes(target.read_bytes(), "residue readback")
                            item["content_length"] = len(raw)
                            item["content_sha256"] = sha256_bytes(raw)
                            expected_item = expected_by_path.get(relative)
                            if classify_mismatch_as_partial and expected_item is not None and (
                                item["content_length"] != expected_item.get("content_length")
                                or item["content_sha256"] != expected_item.get("content_sha256")
                            ):
                                item["entry_kind"] = "PARTIAL_FILE"
                                item["readback_status"] = "PARTIAL"
                        actual_by_path[relative] = item
                        if is_directory:
                            stack.append((target, relative))
        else:
            _final_path(root, root, must_exist=False)
        for relative, item in expected_by_path.items():
            if relative not in actual_by_path:
                actual_by_path[relative] = missing_item(item)
        actual = tuple(actual_by_path[key] for key in sorted(actual_by_path, key=lambda item: item.encode("utf-8")))
        return tuple(expected), actual

    def _validate_owner_writer_paths(
        self,
        observation: Mapping[str, Any],
        output_refs: Sequence[provenance.ArtifactRef],
    ) -> None:
        """Recompute writer paths from the active context before accepting evidence."""
        root = provenance.execution_root(self.context, create=False)
        owner_root = _final_path(root, root, must_exist=root.exists())
        expected_relative = [normalize_relative_path(ref.relative_path, allow_root=False) for ref in output_refs]
        if observation["root_relative_path"] != self.context.root_alias or observation["parent_relative_path"] != self.context.root_alias:
            raise _deny("DENIED_PROVENANCE", "writer root/parent evidence is not context-bound")
        if observation["target_relative_paths"] != expected_relative or observation["target_relative_path"] != expected_relative:
            raise _deny("DENIED_PROVENANCE", "writer target evidence is not output-bound")
        expected_final = [str(_final_path(owner_root / value, owner_root, must_exist=False)) for value in expected_relative]
        if observation["root_final_path"] != str(owner_root) or observation["parent_final_path"] != str(owner_root):
            raise _deny("DENIED_PROVENANCE", "writer root final path was not owner-recomputed")
        if observation["target_final_paths"] != expected_final:
            raise _deny("DENIED_PROVENANCE", "writer target final paths were not owner-recomputed")

    def _writer_failure_evidence(
        self,
        output_refs: Sequence[provenance.ArtifactRef],
        error: BaseException,
    ) -> dict[str, Any]:
        """Read only the already-admitted output targets after a write failure.

        This is deliberately post-write diagnostic evidence.  It never claims
        zero residue and it never attempts repair, cleanup, or a second write.
        """
        root_status = "ABSENT"
        root_path: Path | None = None
        residue_snapshot: dict[str, Any] | None = None
        residue_error: str | None = None
        expected_entries: tuple[dict[str, Any], ...] = ()
        actual_entries: tuple[dict[str, Any], ...] = ()
        observation = self.owner_harness._owner_writer_observation_snapshot()
        try:
            admitted_root = provenance.execution_root(self.context, create=False)
            root_path = _final_path(admitted_root, admitted_root, must_exist=False)
            root_status = "VERIFIED" if root_path.exists() else "ABSENT"
            expected, actual = self._enumerate_residue(
                root_path,
                output_refs,
                classify_mismatch_as_partial=(
                    bool(observation.get("writer_call_started") or observation.get("transaction_started"))
                    and _exception_code(error) not in {
                        provenance.REPLAY_CONFLICT,
                        provenance.PARENT_MISSING,
                        provenance.PARENT_MISMATCH,
                        provenance.PARENT_STORE_MISMATCH,
                        provenance.PATH_ESCAPE,
                    }
                ),
            )
            expected_entries, actual_entries = expected, actual
            if any(item.get("entry_kind") == "PARTIAL_FILE" for item in actual):
                residue_error = "PARTIAL_RESIDUE"
            else:
                residue_snapshot = build_residue_snapshot(
                    root_relative_alias=self.context.root_alias,
                    expected_entries=expected,
                    actual_entries=actual,
                )
        except Exception as exc:
            root_status = "UNREADABLE"
            residue_error = "ENUMERATION_FAILED"
        partial_entries = [item for item in actual_entries if item.get("entry_kind") == "PARTIAL_FILE"]
        first_partial = partial_entries[0] if partial_entries else None
        observation["partial_readback_status"] = "PARTIAL_FILE" if first_partial is not None else "RECORDED"
        observation["partial_length"] = first_partial.get("content_length") if first_partial is not None else None
        observation["partial_sha256"] = first_partial.get("content_sha256") if first_partial is not None else None
        observation["residue_snapshot_hash"] = residue_snapshot_hash(residue_snapshot) if residue_snapshot is not None else None
        observation["root_final_path"] = str(root_path) if root_path is not None else None
        observation["parent_final_path"] = str(root_path) if root_path is not None else None
        owner_root = _final_path(root_path, root_path, must_exist=False) if root_path is not None else None
        observation["target_final_paths"] = [
            str(_final_path(owner_root / ref.relative_path, owner_root, must_exist=False))
            for ref in output_refs
        ] if owner_root is not None else []
        observation["failure_reason"] = _exception_code(error)
        observation["phase"] = "POST_WRITE"
        observation["outcome"] = "RAISE"
        observation["writer_returned"] = False
        observation["writer_raised"] = True
        observation["failure_classification"] = POST_WRITE_IO_FAILURE
        observation["exception_code"] = _exception_code(error)
        observation["exception_type"] = type(error).__qualname__
        observation["exception_message_sha256"] = sha256_bytes(str(error).encode("utf-8"))
        actual_by_path = {item.get("relative_path"): item for item in actual_entries}
        invocation_records: list[dict[str, Any]] = []
        for record in observation["writer_invocations"]:
            updated = dict(record)
            if record["terminal_action"] == "raise":
                actual_item = actual_by_path.get(record["target_relative_path"])
                if actual_item is not None and actual_item.get("exists") and actual_item.get("content_length") is not None and actual_item.get("content_sha256") is not None:
                    updated["partial_readback_status"] = "PARTIAL_FILE" if actual_item.get("entry_kind") == "PARTIAL_FILE" else "RECORDED"
                    updated["partial_length"] = actual_item["content_length"]
                    updated["partial_sha256"] = actual_item["content_sha256"]
            invocation_records.append(canonical_writer_invocation(updated))
        observation["writer_invocations"] = invocation_records
        self.owner_harness._writer_invocation_records = tuple(invocation_records)
        observation = self.owner_harness._validate_owner_writer_observation(observation)
        self._validate_owner_writer_paths(observation, output_refs)
        self.owner_harness.writer_phase_observation = observation
        self.owner_harness._owner_writer_observation = dict(observation)
        self.owner_harness._owner_writer_observation_bytes = canonical_evaluation_json_bytes(
            observation, fields=DETERMINISTIC_WRITER_OBSERVATION_FIELDS,
        )
        failure = {
            "failure_schema_version": "P1-WRITER-FAILURE-EVIDENCE-V1",
            "classification": POST_WRITE_IO_FAILURE,
            "exception_code": _exception_code(error),
            "exception_type": type(error).__qualname__,
            "exception_message_sha256": sha256_bytes(str(error).encode("utf-8")),
            "root_status": root_status,
            "residue_snapshot": residue_snapshot,
            "residue_snapshot_hash": residue_snapshot_hash(residue_snapshot) if residue_snapshot is not None else None,
            "residue_entries": {"expected_entries": [dict(item) for item in expected_entries], "entries": [dict(item) for item in actual_entries]},
            "partial_file_detected": bool(partial_entries),
            "residue_enumeration_error": residue_error,
            "writer_phase_observation": self.owner_harness.writer_phase_observation,
            "zero_residue_claim": False,
        }
        failure["failure_evidence_hash"] = canonical_sha256(
            {field: failure[field] for field in WRITER_FAILURE_EVIDENCE_PREIMAGE_FIELDS},
            fields=WRITER_FAILURE_EVIDENCE_PREIMAGE_FIELDS,
        )
        return canonical_writer_failure_evidence(failure)

    def evaluate(
        self,
        manifest: EvaluationInputManifestV1 | bytes | Mapping[str, Any],
        *,
        batch_id: str,
        attempt_id: str,
        output_parent_refs: Sequence[str] | None = None,
        output_source_ref: str = "p1-offline-evaluation",
        output_relative_paths: tuple[str, str] = ("semantic-result.json", "full-evidence.json"),
        phase_trace: list[str] | None = None,
    ) -> OfflineEvaluationResult:
        if isinstance(manifest, bytes):
            manifest_obj = EvaluationInputManifestV1.from_bytes(manifest)
        elif isinstance(manifest, EvaluationInputManifestV1):
            manifest_obj = manifest
        else:
            manifest_obj = EvaluationInputManifestV1.from_mapping(manifest)
        output_relative_paths = validate_evaluation_output_role_order(output_relative_paths)
        owner_rule_hash, owner_contract_hash = self._check_manifest(manifest_obj)
        artifact = self.resolver.resolve(manifest_obj.input_artifact_identity)
        rule_entry = self.rule_set_registry.select(manifest_obj.rule_set_id, manifest_obj.rule_set_version)
        contract_entry = self.contract_registry.select(manifest_obj.contract_id, manifest_obj.contract_version)
        rule_bytes = base64.b64decode(rule_entry["rule_set_bytes_b64"], validate=True)
        contract_bytes = base64.b64decode(contract_entry["contract_bytes_b64"], validate=True)
        _strict_bytes(rule_bytes, "rule-set bytes")
        _strict_bytes(contract_bytes, "contract bytes")
        if sha256_bytes(rule_bytes) != owner_rule_hash or sha256_bytes(contract_bytes) != owner_contract_hash:
            raise _deny("DENIED_PROVENANCE", "owner registry bytes changed")
        parent_refs = tuple(output_parent_refs or artifact.parent_refs)
        for parent_ref in parent_refs:
            self.context.parent_store.resolve(parent_ref)
        input_lineage = p0_artifact_lineage(provenance.artifact_lineage(artifact))
        verify_p0_lineage_integrity(input_lineage)
        input_adapter = p0_to_p1_input_lineage_adapter(input_lineage)
        owner_manifest_hash = self.owner_harness.bind_input_manifest(manifest_obj, [input_adapter], output_relative_paths)
        binding = build_evaluation_binding(
            manifest_obj,
            input_manifest_hash=owner_manifest_hash,
            rule_set_bytes_sha256=owner_rule_hash,
            evaluation_contract_hash=owner_contract_hash,
        )
        binding_hash = input_binding_hash([input_adapter], owner_manifest_hash)
        permit = self.owner_harness.issue_permit(input_binding_hash=binding_hash, input_manifest_hash=owner_manifest_hash)
        loaded = self.owner_harness.load_candidates(permit, expected_input_binding_hash=binding_hash, expected_input_manifest_hash=owner_manifest_hash)
        owner_observation = self.owner_harness._assert_owner_observation_matches()
        content = self.resolver.read_verified_content(artifact)
        metrics = evaluate_bundle_bytes(content, expected_schema_id=manifest_obj.expected_schema_id, declared_metrics=manifest_obj.declared_metrics)
        metric_results = [result.to_mapping() for result in metrics.metric_results]
        findings = [item.to_mapping() for item in metrics.findings]
        semantic = {"semantic_schema_version": "P1-SEMANTIC-RESULT-V2", "evaluation_case_id": manifest_obj.evaluation_case_id, "project_id": self.context.project_id, "project_revision": self.context.namespace.project_revision, "profile_id": self.context.profile.profile_id, "profile_version": self.context.profile.profile_version, "profile_definition_hash": self.context.profile.profile_definition_hash, "genre_identity": self.context.genre_identity, "namespace_digest": self.context.namespace_digest, "project_registry_snapshot_hash": self.context.registry.registry_snapshot_hash, "input_manifest_hash": owner_manifest_hash, "artifact_resolver_snapshot_hash": manifest_obj.artifact_resolver_snapshot_hash, "parent_store_snapshot_hash": self.context.parent_store.snapshot_hash, "capability_census_snapshot_hash": self.census.snapshot_hash, "rule_set_id": manifest_obj.rule_set_id, "rule_set_version": manifest_obj.rule_set_version, "rule_set_registry_snapshot_hash": self.rule_set_registry.snapshot_hash, "rule_set_bytes_sha256": owner_rule_hash, "evaluator_source_registry_snapshot_hash": _evaluator_source_snapshot_hash(self.owner_harness.source_registry), "evaluator_source_hash": _evaluator_source_hash(self.owner_harness.source_registry), "contract_id": manifest_obj.contract_id, "contract_version": manifest_obj.contract_version, "contract_registry_snapshot_hash": self.contract_registry.snapshot_hash, "evaluation_contract_hash": owner_contract_hash, "evaluation_binding_hash": binding.evaluation_binding_hash, "expected_schema_id": manifest_obj.expected_schema_id, "declared_metrics": list(manifest_obj.declared_metrics), "metric_results": metric_results, "findings": findings, "classification": metrics.classification}
        semantic_bytes = canonical_evaluation_json_bytes(semantic, fields=SEMANTIC_RESULT_FIELDS)
        evidence_projection = {
            "semantic_result": semantic,
            "loaded_source_bindings": list(loaded),
            "owner_capability_observation": owner_observation,
            "p0_counters_supplementary": provenance.get_call_counters(),
            "runtime_attestation": {key: value for key, value in self.owner_harness.runtime_attestation.items() if key != "thread_id"},
            "pre_permit_opcode_attestation": self.owner_harness._trace_attestation,
        }
        frozen_evidence = {
            "evidence_schema_version": "P1-FROZEN-EVIDENCE-V2",
            "evaluation_identity": {
                "evaluation_case_id": manifest_obj.evaluation_case_id,
                "project_id": self.context.project_id,
                "profile_id": self.context.profile.profile_id,
                "profile_version": self.context.profile.profile_version,
                "profile_definition_hash": self.context.profile.profile_definition_hash,
                "namespace_digest": self.context.namespace_digest,
                "project_registry_snapshot_hash": self.context.registry.registry_snapshot_hash,
                "input_manifest_hash": owner_manifest_hash,
                "evaluation_binding_hash": binding.evaluation_binding_hash,
            },
            "input_artifact_lineage_records": [input_adapter],
            "semantic_result_projection": semantic,
            "source_binding_projection": {"loaded_source_bindings": list(loaded), "source_registry_snapshot_hash": self.owner_harness.source_registry.snapshot_hash},
            "capability_projection": {"owner_observation": owner_observation, "census_snapshot_hash": self.census.snapshot_hash},
            "resolution_projection": {
                "resolution_guard_snapshot_hash": self.owner_harness.resolution_guard_snapshot_hash,
                "resolution_guard": self.resolution_guard,
                "resolution_live_snapshot_hash": self.owner_harness.resolution_live_snapshot_hash,
                "resolution_live_snapshot": self.owner_harness._resolution_live_snapshot,
                "resolution_support": self.owner_harness._resolution_support,
            },
            "runtime_projection": {"runtime_attestation": {key: value for key, value in self.owner_harness.runtime_attestation.items() if key != "thread_id"}, "pre_permit_opcode_attestation": self.owner_harness._trace_attestation},
            "declared_output_relative_paths": list(output_relative_paths),
            "input_binding_hash": binding_hash,
        }
        evidence_bytes, frozen_mapping = freeze_evidence(frozen_evidence)
        output_refs = tuple(provenance.make_artifact_ref(self.context, path, semantic_bytes if index == 0 else evidence_bytes, source_ref=output_source_ref, batch_id=batch_id, parent_refs=parent_refs) for index, path in enumerate(output_relative_paths))
        phase = phase_trace if phase_trace is not None else []
        batch, envelope = provenance.build_batch_and_envelope(self.context, batch_id=batch_id, attempt_id=attempt_id, config_hash=binding.evaluation_binding_hash, input_artifact_refs=[provenance.artifact_lineage(artifact)], output_artifact_refs=[provenance.artifact_lineage(item) for item in output_refs], source_refs=[output_source_ref], parent_refs=list(parent_refs), artifact_lengths={item.relative_path: item.length for item in output_refs}, artifact_sha256={item.relative_path: item.sha256 for item in output_refs}, canonical_flags={"canonical_evaluation_json_v2": True, "deterministic_projection_excludes_runtime": True}, tool_boundary={"p1_capability_census": owner_observation, "p0_counters_supplementary": provenance.get_call_counters()}, phase_trace=phase)
        provenance.verify_batch_envelope_binding(batch, envelope)
        full_evidence = frozen_mapping
        paths: list[Path] = []
        self.owner_harness.writer_phase_observation = None
        try:
            with self.owner_harness.writer_trace(
                output_relative_paths,
                root_relative_path=self.context.root_alias,
                parent_relative_path=self.context.root_alias,
                context=self.context,
                output_artifacts=output_refs,
            ):
                for ref, payload in zip(output_refs, (semantic_bytes, evidence_bytes)):
                    paths.append(provenance.safe_write_bytes(self.context, ref.relative_path, payload, artifact_ref=ref, expected_batch_id=batch.batch_id))
        except Exception as exc:
            observation = self.owner_harness._owner_writer_observation or {}
            post_write_codes = {
                provenance.REPLAY_CONFLICT,
                provenance.PARENT_MISSING,
                provenance.PARENT_MISMATCH,
                provenance.PARENT_STORE_MISMATCH,
                provenance.PATH_ESCAPE,
            }
            exception_code = _exception_code(exc)
            if observation.get("transaction_started") or observation.get("writer_call_started") or exception_code in post_write_codes:
                failure = self._writer_failure_evidence(output_refs, exc)
                raise _deny(POST_WRITE_IO_FAILURE, "P0 output write failed after writer call or transaction start", cause=exception_code, exception_type=type(exc).__qualname__, paths=[str(item) for item in paths], writer_phase_observation=failure["writer_phase_observation"], failure_evidence=failure, zero_residue=False) from exc
            raise _deny(POST_PERMIT_TRACE_DENY, "P0 writer failed before transaction start", cause=exception_code, exception_type=type(exc).__qualname__, paths=[str(item) for item in paths], writer_phase_observation=observation, zero_residue=True) from exc
        return OfflineEvaluationResult(semantic, full_evidence, batch, envelope, output_refs, tuple(paths), metrics)


def deterministic_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _deny("DENIED_INPUT", "projection requires a mapping")
    return {key: value[key] for key in value if key not in SEMANTIC_RESULT_EXCLUDED_FIELDS}


__all__ = [
    "ArtifactResolverSnapshotV1", "CODE_OBJECT_PREIMAGE_FIELDS", "D_TMP_ROOT", "EVIDENCE_PROJECTION_FIELDS", "OfflineDeterministicEvaluator",
    "OfflineEvaluationResult", "OpcodeWriterTrace", "OwnerArtifactResolver", "OwnerHarness", "P1CapabilityObserver",
    "POST_PERMIT_TRACE_DENY", "POST_WRITE_IO_FAILURE", "RESIDUE_ARRAY_ORDER", "build_evaluation_binding",
    "build_evaluation_manifest", "build_residue_pairing", "build_residue_snapshot", "build_writer_trace_plan",
    "code_object_preimage", "code_object_sha256", "deterministic_projection", "residue_snapshot_hash",
    "runtime_attestation", "live_resolution_identity_snapshot", "owner_probe_binding_snapshot",
]

from .evaluation_contracts import (
    P1_AE_LOADED_MODULE_BINDING_FIELDS, P1_AE_LOADER_TRANSACTION_PREIMAGE_FIELDS,
    P1AEPurePermitRegistryV1, P1_AE_AUTHORITY_RECORD_FIELDS,
    P1_AE_AUTHORITY_HANDLE_BINDING_FIELDS, consume_p1ae_registry_handle,
    p1ae_authority_hashes, validate_p1ae_import_event, validate_p1ae_forbidden_event, P1_AE_PACKAGE_FIELDS,
    P1_AE_GATE_PREIMAGE_FIELDS, P1_AE_PERMIT_PREIMAGE_FIELDS,
)

def _p1ae_code_hash(source: bytes, path: str) -> str:
    return code_object_sha256(compile(source.decode("utf-8"), path, "exec"))

def _p1ae_module_binding(module: types.ModuleType, expected: Mapping[str, Any], root: Path) -> dict[str, Any]:
    path = _final_path(root / expected["relative_path"], root, must_exist=True)
    spec = getattr(module, "__spec__", None)
    if str(getattr(module, "__file__", "")) != str(path) or str(getattr(spec, "origin", "")) != str(path) or spec is None:
        raise _deny("DENIED_PROVENANCE", "module exact path/spec origin binding failed")
    content = _strict_bytes(path.read_bytes(), "P1-AE post-load source")
    if len(content) != expected["length"] or sha256_bytes(content) != expected["sha256"]:
        raise _deny("DENIED_PROVENANCE", "module source readback binding failed")
    return {"module_name": module.__name__, "module_identity": id(module), "spec_identity": id(spec), "module_file": str(getattr(module, "__file__")), "spec_origin": str(getattr(spec, "origin")), "source_ref": expected["source_ref"], "source_length": expected["length"], "source_sha256": expected["sha256"], "code_sha256": _p1ae_code_hash(content, str(path)), "postload_source_length": len(content), "postload_source_sha256": sha256_bytes(content), "readback_status": "VERIFIED"}

def _p1ae_trace_event(sequence: int, kind: str, caller: str, target: str, caller_source: Mapping[str, Any], target_source: Mapping[str, Any], role: str, channel: str, state: str, edge_sequence: int | None, edge_role: str | None) -> dict[str, Any]:
    value = {"trace_sequence": sequence, "event_kind": kind, "caller_module": caller, "target_module": target, "caller_source_ref": caller_source["source_ref"], "caller_source_length": caller_source["length"], "caller_source_sha256": caller_source["sha256"], "target_source_ref": target_source["source_ref"], "target_source_length": target_source["length"], "target_source_sha256": target_source["sha256"], "caller_code_sha256": caller_source["code_sha256"], "target_code_sha256": target_source["code_sha256"], "offset": 0, "edge_sequence": edge_sequence, "edge_role": edge_role, "load_role": role, "channel": channel, "permit_state": state, "phase": state, "allowed": True, "status": "OBSERVED", "outcome": "ALLOW", "failure_reason": None}
    return validate_p1ae_import_event(value)

def _p1ae_quality_evidence(self: OfflineDeterministicEvaluator, owner_input: Mapping[str, Any]) -> dict[str, str]:
    observation = self.owner_harness._owner_writer_observation_snapshot()
    if not observation.get("writer_invocations"):
        raise _deny(POST_PERMIT_TRACE_DENY, "owner P1-A writer invocation is unavailable")
    required = ("post_write_trace", "failure_evidence", "residue_snapshot", "residue_pairing")
    if any(key not in owner_input for key in required):
        raise _deny(POST_PERMIT_TRACE_DENY, "writer/post-write/residue evidence is incomplete")
    return {"writer_invocation_hash": canonical_sha256(observation, fields=tuple(observation)), "post_write_trace_hash": canonical_sha256(owner_input["post_write_trace"], fields=tuple(owner_input["post_write_trace"])), "failure_evidence_hash": canonical_sha256(owner_input["failure_evidence"], fields=tuple(owner_input["failure_evidence"])), "residue_snapshot_hash": residue_snapshot_hash(owner_input["residue_snapshot"]), "residue_pairing_hash": canonical_pairing_hash(owner_input["residue_pairing"])}

def _p1ae_pure_loader_corrected(self: OfflineDeterministicEvaluator, owner_input: Mapping[str, Any], *, batch_id: str, attempt_id: str) -> Any:
    if not isinstance(owner_input, Mapping):
        raise _deny("DENIED_INPUT", "quality owner input must be a mapping")
    bundle = owner_input.get("canonical_quality_bundle", owner_input.get("quality_bundle"))
    if not isinstance(bundle, Mapping):
        raise _deny("DENIED_INPUT", "quality bundle must be owner-injected")
    if not hasattr(self, "_p1ae_owner_lock"):
        self._p1ae_owner_lock = RLock(); self._p1ae_permit_registry = P1AEPurePermitRegistryV1(self.owner_harness.owner_session_id)
    with self._p1ae_owner_lock:
        source_registry = self.owner_harness.source_registry; owner_id = source_registry.value["owner_id"]; authority_ref = source_registry.value["authoritative_source_ref"]
        authority_handle = owner_input.get("authority_handle"); authority_secret = owner_input.get("authority_secret"); authority_bytes = owner_input.get("authority_bytes"); authority_readback = owner_input.get("authority_source_readback", authority_bytes)
        authority_record = owner_input.get("authority_record"); handle_binding = owner_input.get("authority_handle_binding")
        if authority_handle is None or authority_secret is None or not isinstance(authority_bytes, bytes) or not isinstance(authority_readback, bytes) or not isinstance(authority_record, Mapping) or not isinstance(handle_binding, Mapping):
            raise _deny("DENIED_AUTHORITY", "owner registry handle/authority source readback is required")
        authority_hashes = p1ae_authority_hashes(authority_bytes=authority_bytes, authority_record=authority_record, handle_binding=handle_binding, source_readback=authority_readback)
        consume_p1ae_registry_handle(authority_handle, owner_session=self.owner_harness.owner_session_id, request_nonce=authority_handle.request_nonce, secret=authority_secret, snapshot_hash=authority_handle.snapshot_hash)
        entries = {entry["relative_path"]: entry for entry in source_registry.value["entries"] if entry["relative_path"].endswith(("evaluation_contracts.py", "evaluation_metrics.py", "quality_evaluation.py"))}
        if len(entries) != 3:
            raise _deny("DENIED_PROVENANCE", "pure loader source registry is not exact")
        def read_sources() -> dict[str, dict[str, Any]]:
            result = {}
            for relative_path in sorted(entries, key=lambda item: item.encode("utf-8")):
                bound = self._p1ae_source_binding(relative_path); bound["code_sha256"] = _p1ae_code_hash(bound["content"], str(self.owner_harness.source_root / relative_path)); result[relative_path] = bound
            return result
        sources = read_sources(); ordered = list(sources); source_bindings = [{key: sources[path][key] for key in ("relative_path", "source_ref", "length", "sha256")} for path in ordered]; source_module_binding_hash = canonical_sha256({"entries": source_bindings}, fields=("entries",))
        quality_path = next(path for path in ordered if path.endswith("quality_evaluation.py")); contract_path = next(path for path in ordered if path.endswith("evaluation_contracts.py")); metrics_path = next(path for path in ordered if path.endswith("evaluation_metrics.py")); transition_hash = p1ae_transition_registry_hash("READY"); empty_hash = sha256_bytes(canonical_evaluation_json_bytes({"events": []}, fields=("events",))); forbidden = {"projection_schema_version": "P1_AE_FORBIDDEN_IMPORT_PROJECTION_V1", "events": [], "event_hash": empty_hash, "event_count": 0, "trace_complete": True, "status": "CLEAR", "terminal_state": "NONE"}; forbidden_hash = p1ae_forbidden_projection_hash(forbidden)
        target_path = self.owner_harness.source_root / quality_path
        if "xiaoshuo.pipeline.quality_evaluation" in sys.modules or any(str(getattr(module, "__file__", "")) == str(target_path) for module in sys.modules.values() if module is not None):
            raise _deny("DENIED_CAPABILITY", "candidate preloaded module/source path is not permitted")
        plan = {"loader_plan_schema_version": "P1_AE_PURE_LOADER_PLAN_V1", "plan_id": f"{batch_id}:{attempt_id}", "owner_id": owner_id, "authority_ref": authority_ref, "owner_session_ref": self.owner_harness.owner_session_id, "pure_source_registry_snapshot_hash": source_registry.snapshot_hash, "source_module_binding_hash": source_module_binding_hash, "pure_gate_snapshot_hash": canonical_sha256({"gate": "P1_AE_PURE_GATE_V1", "owner_id": owner_id, "authority_ref": authority_ref}, fields=("gate", "owner_id", "authority_ref")), "resolution_guard_snapshot_hash": self.owner_harness.resolution_guard_snapshot_hash, "resolution_live_snapshot_hash": self.owner_harness.resolution_live_snapshot_hash, "bootstrap_sequence": [contract_path, metrics_path], "candidate_root_sequence": [quality_path], "candidate_static_sequence": [], "cpython_internal_expected_sequence": [], "cpython_internal_expected_edge_count": 0, "cpython_internal_expected_event_count": 0, "forbidden_expected_count": 0, "forbidden_expected_tuple_registry_hash": forbidden_hash, "host_loader_invoked": False, "host_gate_mutated": False, "host_permit_mutated": False, "host_candidate_set_read": False, "permit_consumed_before_import": True, "pre_permit_state": "PURE_PERMIT_ISSUED", "post_cas_state": "CAS_CONSUMED", "next_required_state": "INTERNAL_PREFLIGHT_RECHECKED", "transition_status": "ALLOWED", "transition_registry_hash": transition_hash, "status": "READY"}; binding = p1ae_loader_plan_binding(plan)
        expected = {"observation_schema_version": "P1_AE_PURE_IMPORT_EXPECTED_OBSERVATION_V1", "owner_id": owner_id, "authority_ref": authority_ref, "source_registry_snapshot_hash": source_registry.snapshot_hash, "source_module_binding_hash": source_module_binding_hash, **binding, "transition_fields": list(P1_AE_PURE_LOADER_PLAN_TRANSITION_TUPLE), "cpython_internal_expected_edges_hash": empty_hash, "cpython_internal_expected_events_hash": empty_hash, "cpython_internal_expected_edge_count": 0, "cpython_internal_expected_event_count": 0, "forbidden_expected_events_hash": forbidden["event_hash"], "forbidden_expected_count": 0, "forbidden_expected_tuple_registry_hash": forbidden_hash, "phase": "HOST_STATIC_BOUND", "status": "READY"}; expected_hash = p1ae_expected_observation_hash(expected); loaded_expected_hash = canonical_sha256({"bindings": [], "binding_hash": empty_hash, "status": "EXPECTED"}, fields=("bindings", "binding_hash", "status"))
        package = {"package_schema_version": "P1_AE_PURE_PACKAGE_V1", "owner_id": owner_id, "authority_ref": authority_ref, "source_registry_hash": source_registry.snapshot_hash, "source_module_binding_hash": source_module_binding_hash, "loader_plan_hash": binding["loader_plan_hash"], "loader_plan_length": binding["loader_plan_length"], "transition_registry_hash": transition_hash, "transition_fields": list(P1_AE_PURE_LOADER_PLAN_TRANSITION_TUPLE), "resolution_guard_hash": self.owner_harness.resolution_guard_snapshot_hash, "resolution_live_hash": self.owner_harness.resolution_live_snapshot_hash, "expected_observation_hash": expected_hash, "loaded_module_bindings_hash": loaded_expected_hash, "forbidden_projection_hash": forbidden_hash, "status": "READY"}; package_hash = canonical_sha256(package, fields=P1_AE_PACKAGE_FIELDS); gate_hash = canonical_sha256(package, fields=P1_AE_GATE_PREIMAGE_FIELDS)
        permit_preimage = {"permit_schema_version": "P1_AE_PURE_IMPORT_PERMIT_V1", "owner_id": owner_id, "authority_ref": authority_ref, "owner_session_ref": self.owner_harness.owner_session_id, "package_hash": package_hash, "loader_plan_hash": binding["loader_plan_hash"], "loader_plan_length": binding["loader_plan_length"], "transition_registry_hash": transition_hash, "transition_fields": list(P1_AE_PURE_LOADER_PLAN_TRANSITION_TUPLE), "expected_observation_hash": expected_hash, "loaded_module_bindings_hash": loaded_expected_hash, "forbidden_projection_hash": forbidden_hash, "status": "READY"}; secret, private_handle = object(), object(); permit = issue_p1ae_pure_permit(owner_session_ref=self.owner_harness.owner_session_id, preimage=permit_preimage, secret=secret, private_handle=private_handle, registry=self._p1ae_permit_registry); consumed_digest = permit.consume(secret=secret, private_handle=private_handle)
        reread = read_sources(); reread_hash = canonical_sha256({"entries": [{key: reread[path][key] for key in ("relative_path", "source_ref", "length", "sha256")} for path in ordered]}, fields=("entries",))
        if reread_hash != source_module_binding_hash or self.owner_harness.resolution_guard_snapshot_hash != plan["resolution_guard_snapshot_hash"] or self.owner_harness.resolution_live_snapshot_hash != plan["resolution_live_snapshot_hash"] or p1ae_loader_plan_hash(plan) != binding["loader_plan_hash"] or len(p1ae_loader_plan_bytes(plan)) != binding["loader_plan_length"] or p1ae_transition_registry_hash("READY") != transition_hash or p1ae_expected_observation_hash(expected) != expected_hash or canonical_sha256(package, fields=P1_AE_PACKAGE_FIELDS) != package_hash or canonical_sha256(package, fields=P1_AE_GATE_PREIMAGE_FIELDS) != gate_hash or p1ae_forbidden_projection_hash(forbidden) != forbidden_hash or canonical_sha256(permit_preimage, fields=P1_AE_PERMIT_PREIMAGE_FIELDS) != consumed_digest:
            raise _deny("DENIED_CAPABILITY", "PURE_INTERNAL_PREFLIGHT_RECHECKED mismatch before dynamic import")
        source = reread[quality_path]; trace_events = [_p1ae_trace_event(index, "BOOTSTRAP_IMPORT", "xiaoshuo.pipeline", path, sources[contract_path if index == 0 else metrics_path], sources[contract_path if index == 0 else metrics_path], "P1A_STATIC_BOOTSTRAP", "OWNER_STATIC_EDGE", "HOST_STATIC_BOUND", index, "P1A_STATIC_BOOTSTRAP") for index, path in enumerate((contract_path, metrics_path))]
        module_spec = importlib.util.spec_from_file_location("xiaoshuo.pipeline.quality_evaluation", target_path)
        if module_spec is None or module_spec.loader is None:
            raise _deny("DENIED_CAPABILITY", "candidate module spec unavailable")
        module = importlib.util.module_from_spec(module_spec); forbidden_events: list[dict[str, Any]] = []; previous_import = builtins.__import__
        def import_guard(name: str, globals: Mapping[str, Any] | None = None, locals: Mapping[str, Any] | None = None, fromlist: Sequence[str] = (), level: int = 0):
            if name in {"evaluation_contracts", "evaluation_metrics", "dataclasses", "decimal", "fractions", "hashlib", "typing"} or name.endswith("evaluation_contracts") or name.endswith("evaluation_metrics"):
                return previous_import(name, globals, locals, fromlist, level)
            forbidden_event = {"trace_sequence": len(forbidden_events), "event_kind": "AMBIENT_IMPORT", "caller_module": "xiaoshuo.pipeline.quality_evaluation", "target_module": name, "caller_source_ref": source["source_ref"], "caller_source_length": source["length"], "caller_source_sha256": source["sha256"], "target_source_ref": None, "target_source_length": None, "target_source_sha256": "0" * 64, "caller_code_sha256": source["code_sha256"], "target_code_sha256": "0" * 64, "offset": 0, "edge_sequence": None, "edge_role": None, "load_role": "FORBIDDEN", "channel": "IMPORTLIB_DYNAMIC", "permit_state": "CONSUMED", "phase": "CONSUMED", "allowed": False, "status": "TERMINAL_DENY", "outcome": "DENY", "terminal_state": "DENY", "failure_reason": "AMBIENT_IMPORT"}; forbidden_events.append(validate_p1ae_forbidden_event(forbidden_event)); raise _deny("DENIED_CAPABILITY", "forbidden import captured: {name}")
        try:
            builtins.__import__ = import_guard; module_spec.loader.exec_module(module)
        finally:
            builtins.__import__ = previous_import
        loaded = _p1ae_module_binding(module, source, self.owner_harness.source_root); trace_events.append(_p1ae_trace_event(len(trace_events), "CANDIDATE_ROOT_IMPORT", "xiaoshuo.pipeline", quality_path, source, source, "P1AE_DYNAMIC_CANDIDATE", "IMPORTLIB_DYNAMIC", "CONSUMED", None, None)); loaded_hash = canonical_sha256({"bindings": [loaded], "binding_hash": empty_hash, "status": "VERIFIED"}, fields=("bindings", "binding_hash", "status")); trace_hash = canonical_sha256({"events": trace_events}, fields=("events",))
        if forbidden_events:
            raise _deny("DENIED_CAPABILITY", "FORBIDDEN_IMPORT_EVENT_CAPTURED terminal deny")
        evidence = _p1ae_quality_evidence(self, owner_input); transaction = {"transaction_schema_version": P1_AE_PURE_LOADER_TRANSACTION_SCHEMA_VERSION, "transaction_id": f"{batch_id}:{attempt_id}", "owner_id": owner_id, "authority_ref": authority_ref, "owner_session_ref": self.owner_harness.owner_session_id, "loader_plan_hash": binding["loader_plan_hash"], "loader_plan_length": binding["loader_plan_length"], "transition_registry_hash": transition_hash, "transition_fields": list(P1_AE_PURE_LOADER_PLAN_TRANSITION_TUPLE), "permit_digest": consumed_digest, "permit_cas_sequence": 1, "dynamic_load_count": 1, "dynamic_load_order": [quality_path], "loaded_module_bindings_hash": loaded_hash, "import_trace_hash": trace_hash, "forbidden_projection_hash": forbidden_hash, "observed_projection_hash": trace_hash, **evidence, "state": "COMMITTED", "status": "READY"}; transaction_hash = canonical_sha256(transaction, fields=P1_AE_LOADER_TRANSACTION_PREIMAGE_FIELDS)
        admission = {"admission_schema_version": P1_AE_OWNER_ADMISSION_SCHEMA_VERSION, "owner_id": owner_id, "authority_ref": authority_ref, "owner_session_ref": self.owner_harness.owner_session_id, "source_registry_hash": source_registry.snapshot_hash, "package_hash": package_hash, "gate_hash": gate_hash, "permit_digest": consumed_digest, "loader_plan_hash": binding["loader_plan_hash"], "loader_plan_length": binding["loader_plan_length"], "transition_registry_hash": transition_hash, "transition_fields": list(P1_AE_PURE_LOADER_PLAN_TRANSITION_TUPLE), "transaction_hash": transaction_hash, "loaded_module_bindings_hash": loaded_hash, **evidence, "semantic_hash": "0" * 64, "raw_authority_bytes_hash": authority_hashes["raw_authority_bytes_hash"], "authority_record_hash": authority_hashes["authority_record_hash"], "authority_handle_binding_hash": authority_hashes["handle_binding_hash"], "composite_authority_binding_hash": authority_hashes["composite_authority_binding_hash"], "status": "ADMITTED"}; return module.evaluate_quality_bundle(admission, bundle), transaction_hash

OfflineDeterministicEvaluator._p1ae_pure_loader = _p1ae_pure_loader_corrected
OfflineDeterministicEvaluator._p1ae_quality_evidence = _p1ae_quality_evidence

# Final C5 gated implementation.  The earlier compatibility definitions are
# not used by the class after this assignment.  This path performs an owner
# registry lookup, loads exact census paths into fresh module objects, captures
# actual import callbacks, and fails closed before any dynamic candidate call.
from .evaluation_contracts import (
    P1AEOwnerRegistryV1, P1_AE_AUTHORITY_RECORD_FIELDS,
    P1_AE_AUTHORITY_HANDLE_BINDING_FIELDS, P1_AE_FORBIDDEN_IMPORT_EVENT_FIELDS,
    P1_AE_FORBIDDEN_IMPORT_PROJECTION_FIELDS, P1_AE_IMPORT_EVENT_FIELDS,
    P1_AE_LOADED_MODULE_BINDINGS_FIELDS, P1_AE_RESOLUTION_SPECIALIZED_ENTRY_FIELDS,
    P1_AE_RESOLUTION_SPECIALIZED_SCHEMA_BY_KIND, P1_AE_CWD_SPECIALIZED_FIELDS,
    P1_AE_RESOLUTION_SPECIALIZED_FIELDS, P1_AE_PURE_LOADER_PLAN_RESOLUTION_HASH_FIELDS,
    P1_AE_CPYTHON_INTERNAL_COMPARISON_FIELDS, P1_AE_CPYTHON_INTERNAL_BINDING_FIELDS,
    p1ae_cpython_internal_projection_hash,
    P1_AE_PACKAGE_FIELDS, P1_AE_GATE_PREIMAGE_FIELDS, P1_AE_PERMIT_PREIMAGE_FIELDS,
    P1_AE_LOADER_TRANSACTION_PREIMAGE_FIELDS,
    p1ae_forbidden_projection_hash, p1ae_resolution_snapshot_hash,
    validate_p1ae_import_event, validate_p1ae_forbidden_event,
)


def _p1ae_exact_module_sources(self: OfflineDeterministicEvaluator) -> dict[str, dict[str, Any]]:
    required = (
        "xiaoshuo.pipeline.evaluation_contracts",
        "xiaoshuo.pipeline.evaluation_metrics",
        "xiaoshuo.pipeline.quality_evaluation",
    )
    census = {item["module_path"]: item for item in self.census.value["entries"] if item["module_path"] in required}
    if tuple(sorted(census)) != tuple(sorted(required)):
        raise _deny("DENIED_PROVENANCE", "P1-AE exact census module set is incomplete")
    result = {}
    for module_name in required:
        census_entry = census[module_name]
        relative_path = census_entry["source_relative_path"]
        source = self._p1ae_source_binding(relative_path)
        if source["relative_path"] != relative_path or source["source_ref"] != census_entry["source_ref"] or source["length"] != census_entry["source_length"] or source["sha256"] != census_entry["source_sha256"]:
            raise _deny("DENIED_PROVENANCE", "exact census/source binding mismatch", module=module_name)
        source["module_name"] = module_name
        source["code_sha256"] = _p1ae_code_hash(source["content"], str(self.owner_harness.source_root / relative_path))
        result[module_name] = source
    return result


def _p1ae_resolution_entry(kind: str, sequence: int, value: str, value_kind: str) -> dict[str, Any]:
    normalized = unicodedata.normalize("NFC", value)
    raw = normalized.encode("utf-8")
    return {
        "entry_sequence": sequence, "value": value, "value_kind": value_kind,
        "normalized_value": normalized, "source_ref": f"P1-AE:{kind}:{sequence}",
        "source_length": len(raw), "source_sha256": sha256_bytes(raw),
        "collision_key": normalized.casefold(), "status": "OBSERVED",
    }


def _p1ae_resolution_projection(owner_id: str, authority_ref: str) -> tuple[dict[str, Any], dict[str, str], str]:
    def collection(kind: str, values: Sequence[str], value_kind: str) -> tuple[dict[str, Any], str]:
        entries = [_p1ae_resolution_entry(kind, index, value, value_kind) for index, value in enumerate(sorted(values, key=lambda item: unicodedata.normalize("NFC", item).encode("utf-8")))]
        nested = canonical_evaluation_json_bytes({"entries": entries}, fields=("entries",))
        snapshot = {
            "snapshot_schema_version": P1_AE_RESOLUTION_SPECIALIZED_SCHEMA_BY_KIND[kind],
            "snapshot_kind": kind, "owner_id": owner_id, "authority_ref": authority_ref,
            "entry_count": len(entries), "complete": True, "entries": entries,
            "nested_preimage_hash": sha256_bytes(nested), "status": "READY",
        }
        return snapshot, p1ae_resolution_snapshot_hash(snapshot)

    collections = {
        "SYS_PATH": [str(item) for item in sys.path],
        "META_PATH": [f"{type(item).__module__}.{type(item).__qualname__}|{id(item)}" for item in sys.meta_path],
        "PATH_HOOKS": [f"{getattr(item, '__module__', type(item).__module__)}.{getattr(item, '__qualname__', type(item).__qualname__)}|{id(item)}" for item in sys.path_hooks],
        "PRELOADED_MODULES": [f"{name}|{getattr(module, '__file__', None) or '<builtin>'}" for name, module in sorted(sys.modules.items(), key=lambda item: item[0].encode("utf-8")) if module is not None],
        "PRELOADED_SOURCE_PATHS": sorted({str(getattr(module, "__file__")) for module in sys.modules.values() if module is not None and getattr(module, "__file__", None)}, key=lambda item: unicodedata.normalize("NFC", item).encode("utf-8")),
    }
    snapshots: dict[str, Any] = {}
    hashes: dict[str, str] = {}
    for kind, values in collections.items():
        snapshots[kind], hashes[kind] = collection(kind, values, kind)
    cwd = os.getcwd()
    cwd_raw = cwd.encode("utf-8")
    cwd_snapshot = {
        "snapshot_schema_version": P1_AE_RESOLUTION_SPECIALIZED_SCHEMA_BY_KIND["CWD"],
        "snapshot_kind": "CWD", "owner_id": owner_id, "authority_ref": authority_ref,
        "entry_count": 1, "complete": True, "path": cwd, "path_kind": "ABSOLUTE",
        "source_ref": "P1-AE:CWD:0", "source_length": len(cwd_raw),
        "source_sha256": sha256_bytes(cwd_raw), "status": "READY",
    }
    snapshots["CWD"] = cwd_snapshot
    hashes["CWD"] = p1ae_resolution_snapshot_hash(cwd_snapshot)
    ordered_hashes = {field: hashes[kind] for field, kind in zip(P1_AE_PURE_LOADER_PLAN_RESOLUTION_HASH_FIELDS, ("SYS_PATH", "CWD", "META_PATH", "PATH_HOOKS", "PRELOADED_MODULES", "PRELOADED_SOURCE_PATHS"))}
    return snapshots, ordered_hashes, canonical_sha256(ordered_hashes, fields=tuple(ordered_hashes))


def _p1ae_runtime_source(module_name: str, module: Any) -> dict[str, Any]:
    path = getattr(module, "__file__", None)
    content = b""
    if path:
        try:
            content = _strict_bytes(Path(str(path)).read_bytes(), "P1-AE runtime source")
        except (OSError, ValueError):
            content = b""
    source_ref = str(path) if path else f"builtin:{module_name}"
    source_sha = sha256_bytes(content if content else source_ref.encode("utf-8"))
    return {"relative_path": source_ref, "source_ref": source_ref, "length": len(content), "sha256": source_sha, "code_sha256": source_sha}


def _p1ae_loaded_binding_final(module: types.ModuleType, expected: Mapping[str, Any], root: Path) -> dict[str, Any]:
    path = _final_path(root / expected["relative_path"], root, must_exist=True)
    spec = getattr(module, "__spec__", None)
    actual_file = getattr(module, "__file__", None)
    actual_origin = getattr(spec, "origin", None) if spec is not None else None
    if spec is None or str(actual_file) != str(path) or str(actual_origin) != str(path) or module.__name__ != expected["module_name"]:
        raise _deny("DENIED_PROVENANCE", "loaded module exact path/spec/module binding failed")
    content = _strict_bytes(path.read_bytes(), "P1-AE loaded source readback")
    if len(content) != expected["length"] or sha256_bytes(content) != expected["sha256"]:
        raise _deny("DENIED_PROVENANCE", "loaded module source readback changed")
    return {
        "module_name": module.__name__, "module_identity": id(module), "spec_identity": id(spec),
        "module_file": str(actual_file), "spec_origin": str(actual_origin),
        "source_ref": expected["source_ref"], "source_length": expected["length"],
        "source_sha256": expected["sha256"], "code_sha256": expected["code_sha256"],
        "postload_source_length": len(content), "postload_source_sha256": sha256_bytes(content),
        "readback_status": "BOUND",
    }


def _p1ae_loaded_projection(bindings: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], str]:
    ordered = sorted((dict(item) for item in bindings), key=lambda item: item["module_name"].encode("utf-8"))
    binding_hash = canonical_sha256({"bindings": ordered}, fields=("bindings",))
    projection = {"bindings": ordered, "binding_hash": binding_hash, "status": "BOUND"}
    return projection, canonical_sha256(projection, fields=P1_AE_LOADED_MODULE_BINDINGS_FIELDS)


def _p1ae_internal_projections(events: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, str]:
    internal = [dict(event) for event in events if event["event_kind"] == "CPYTHON_INTERNAL"]
    edges = [{"edge_sequence": event["edge_sequence"], "source_ref": event["target_source_ref"], "source_length": event["target_source_length"], "source_sha256": event["target_source_sha256"], "code_sha256": event["target_code_sha256"], "offset": event["offset"], "role": event["load_role"], "channel": event["channel"], "permit_state": event["permit_state"]} for event in internal]
    return internal, edges, sha256_bytes(canonical_evaluation_json_bytes({"events": internal}, fields=("events",))), sha256_bytes(canonical_evaluation_json_bytes({"edges": edges}, fields=("edges",)))


def _p1ae_forbidden_projection_final(events: Sequence[Mapping[str, Any]], complete: bool = True) -> dict[str, Any]:
    canonical_events = [dict(item) for item in events]
    event_hash = sha256_bytes(canonical_evaluation_json_bytes({"events": canonical_events}, fields=("events",)))
    projection = {"projection_schema_version": "P1_AE_FORBIDDEN_IMPORT_PROJECTION_V1", "events": canonical_events, "event_hash": event_hash, "event_count": len(canonical_events), "trace_complete": complete, "status": "CLEAR" if complete and not canonical_events else "DENY", "terminal_state": "NONE" if complete and not canonical_events else "DENY"}
    return projection


def _p1ae_quality_evidence_final(
    self: OfflineDeterministicEvaluator,
    owner_input: Mapping[str, Any],
    *,
    batch_id: str | None = None,
    attempt_id: str | None = None,
    transaction_id: str | None = None,
) -> dict[str, str]:
    observation = self.owner_harness._owner_writer_observation_snapshot()
    observation = canonical_writer_observation(observation)
    if not observation["writer_invocations"]:
        raise _deny(POST_PERMIT_TRACE_DENY, "owner P1-A writer invocation is unavailable")
    if not observation.get("root_final_path") or not observation.get("parent_final_path") or not isinstance(observation.get("target_final_paths"), list):
        raise _deny(POST_PERMIT_TRACE_DENY, "owner final writer paths are incomplete")
    for event in observation["events"]:
        if event["source_ref"] != self.writer_trace_plan["provenance_source_ref"]:
            raise _deny(POST_PERMIT_TRACE_DENY, "writer trace source is not owner-bound")
        action, offset_text = event["outcome"].rsplit("@", 1)
        expected_offset = self.writer_trace_plan["transaction_call_offset"] if action == "transaction_started" else self.writer_trace_plan["writer_call_offset"] if action == "writer_call_started" else None
        if expected_offset is not None and int(offset_text) != expected_offset:
            raise _deny(POST_PERMIT_TRACE_DENY, "owner writer trace offset is not bound")
    evidence = getattr(self.owner_harness, "_p1ae_post_write_evidence", None)
    if not isinstance(evidence, Mapping):
        raise _deny(POST_PERMIT_TRACE_DENY, "owner-derived post-write evidence is required")
    if (batch_id, attempt_id, transaction_id) != (None, None, None):
        if (evidence.get("batch_id"), evidence.get("attempt_id"), evidence.get("transaction_id")) != (batch_id, attempt_id, transaction_id):
            raise _deny(POST_PERMIT_TRACE_DENY, "post-write evidence is not bound to this transaction")
    caller_evidence = owner_input.get("owner_post_write_evidence")
    if caller_evidence is not None:
        if not isinstance(caller_evidence, Mapping) or canonical_evaluation_json_bytes(dict(caller_evidence), fields=tuple(caller_evidence)) != canonical_evaluation_json_bytes(dict(evidence), fields=tuple(evidence)):
            raise _deny(POST_PERMIT_TRACE_DENY, "caller post-write evidence is not an owner readback match")
    required = ("post_write_trace", "failure_evidence", "residue_snapshot", "residue_pairing")
    if any(key not in evidence for key in required):
        raise _deny(POST_PERMIT_TRACE_DENY, "owner post-write evidence is incomplete")
    failure = canonical_writer_failure_evidence(evidence["failure_evidence"])
    residue = canonical_residue_snapshot(evidence["residue_snapshot"])
    pairing_hash = canonical_pairing_hash(evidence["residue_pairing"])
    if residue["residue_pairing_hash"] != pairing_hash or residue["enumeration_complete"] is not True:
        raise _deny(POST_PERMIT_TRACE_DENY, "owner residue pairing/enumeration binding failed")
    if evidence.get("failure_evidence", {}).get("partial_file_detected") and evidence.get("failure_evidence", {}).get("residue_snapshot_hash") is not None:
        raise _deny(POST_PERMIT_TRACE_DENY, "partial readback cannot claim a complete residue snapshot")
    post_trace = evidence["post_write_trace"]
    if not isinstance(post_trace, Mapping) or not post_trace:
        raise _deny(POST_PERMIT_TRACE_DENY, "owner post-write trace is not canonical")
    self._p1ae_last_post_write_evidence = dict(evidence)
    return {
        "writer_invocation_hash": canonical_sha256(observation, fields=tuple(observation)),
        "post_write_trace_hash": canonical_sha256(post_trace, fields=tuple(post_trace)),
        "failure_evidence_hash": canonical_sha256(failure, fields=tuple(failure)),
        "residue_snapshot_hash": residue_snapshot_hash(residue),
        "residue_pairing_hash": pairing_hash,
    }


def _p1ae_pure_loader_gated(self: OfflineDeterministicEvaluator, owner_input: Mapping[str, Any], *, batch_id: str, attempt_id: str) -> Any:
    if not isinstance(owner_input, Mapping):
        raise _deny("DENIED_INPUT", "quality owner input must be a mapping")
    bundle = owner_input.get("canonical_quality_bundle", owner_input.get("quality_bundle"))
    if not isinstance(bundle, Mapping):
        raise _deny("DENIED_INPUT", "quality bundle must be owner-injected")
    registry = getattr(self.owner_harness, "_p1ae_annotation_registry", None)
    if owner_input.get("owner_registry") is not None or owner_input.get("annotation_registry_ids") is not None:
        raise _deny("DENIED_AUTHORITY", "caller cannot provide authoritative registry or lookup ids")
    if not isinstance(registry, P1AEOwnerRegistryV1):
        raise _deny("DENIED_AUTHORITY", "owner authority registry is not owner-bound")
    if not hasattr(self, "_p1ae_owner_lock"):
        self._p1ae_owner_lock = RLock()
        self._p1ae_permit_registry = P1AEPurePermitRegistryV1(self.owner_harness.owner_session_id)
    with self._p1ae_owner_lock:
        source_registry = self.owner_harness.source_registry
        owner_id = source_registry.value["owner_id"]
        authority_ref = source_registry.value["authoritative_source_ref"]
        exact_sources = _p1ae_exact_module_sources(self)
        record_ids = {(item["annotation_id"], item["case_id"], item["pass_kind"]): item["record_id"] for item in registry._records.values()}
        owner_records = []
        last_handle = None
        for case in bundle.get("cases", ()):
            for annotation in case.get("annotations", ()):
                record_id = record_ids.get((annotation.get("annotation_id"), case.get("case_id"), annotation.get("pass_kind")))
                if not isinstance(record_id, str):
                    raise _deny("DENIED_AUTHORITY", "owner lookup identity tuple is missing")
                record, last_handle = registry.owner_lookup(record_id, case_id=case["case_id"], pass_kind=annotation["pass_kind"], annotation_id=annotation["annotation_id"])
                if record["annotation_id"] != annotation["annotation_id"] or record["case_id"] != case["case_id"] or record["pass_kind"] != annotation["pass_kind"] or record["rater_id"] != annotation["rater_id"] or record["human_only"] is not True or record["blindness_status"] != "BLIND" or record["independence_status"] != "INDEPENDENT":
                    raise _deny("DENIED_AUTHORITY", "annotation facts do not match owner registry lookup")
                owner_records.append(record)
        if last_handle is None:
            raise _deny("DENIED_AUTHORITY", "owner registry has no annotation records")
        authority_bytes = registry._authority_bytes
        authority_record = {"authority_schema_version": "P1_AE_AUTHORITY_RECORD_V1", "authority_id": owner_id, "owner_id": owner_id, "authority_kind": "HUMAN_RATER_REGISTRY", "status": "BOUND", "source_ref": authority_ref, "source_length": len(authority_bytes), "source_sha256": sha256_bytes(authority_bytes), "source_readback_length": len(registry._source_readback), "source_readback_sha256": sha256_bytes(registry._source_readback), "owner_secret_seal": last_handle.owner_secret_seal}
        handle_binding = {"authority_id": owner_id, "owner_session": last_handle.owner_session, "handle_generation": last_handle.generation, "request_nonce": last_handle.request_nonce, "snapshot_hash": registry.snapshot_hash, "object_identity": last_handle._object_identity, "private_identity": id(last_handle._private_identity), "source_readback_sha256": sha256_bytes(registry._source_readback), "owner_secret_seal": last_handle.owner_secret_seal}
        authority_hashes = p1ae_authority_hashes(authority_bytes=authority_bytes, authority_record=authority_record, handle_binding=handle_binding, source_readback=registry._source_readback)
        owner_annotation_projection_hash = canonical_sha256({"records": sorted(owner_records, key=lambda item: item["record_id"].encode("utf-8"))}, fields=("records",))
        snapshots, resolution_hashes, resolution_projection_hash = _p1ae_resolution_projection(owner_id, authority_ref)
        modules = {name: None for name in exact_sources}
        saved_modules: dict[str, Any] = {}
        missing = object()
        environment_before = {
            "sys_path": list(sys.path), "cwd": os.getcwd(),
            "meta_path": list(sys.meta_path), "path_hooks": list(sys.path_hooks),
            "modules": dict(sys.modules),
        }
        trace: list[dict[str, Any]] = []
        forbidden_events: list[dict[str, Any]] = []
        loader_guard_seen: set[str] = set()
        internal_edge_sequence = 0
        phase = "HOST_STATIC_BOUND"
        bootstrap_names = ("xiaoshuo.pipeline.evaluation_contracts", "xiaoshuo.pipeline.evaluation_metrics")
        candidate_name = "xiaoshuo.pipeline.quality_evaluation"
        allowed_internal = set()
        for census_entry in self.census.value["entries"]:
            if census_entry["module_path"] == candidate_name:
                allowed_internal.update(census_entry["transitive_modules"])
        allowed_internal -= set(exact_sources)

        def runtime_event(caller: str, target: str, kind: str, role: str, channel: str, state: str, edge_sequence: int | None, edge_role: str | None, target_module: Any) -> dict[str, Any]:
            caller_source = exact_sources.get(caller) or _p1ae_runtime_source(caller, sys.modules.get(caller))
            target_source = exact_sources.get(target) or _p1ae_runtime_source(target, target_module)
            event = {"trace_sequence": len(trace), "event_kind": kind, "caller_module": caller, "target_module": target, "caller_source_ref": caller_source["source_ref"], "caller_source_length": caller_source["length"], "caller_source_sha256": caller_source["sha256"], "target_source_ref": target_source["source_ref"], "target_source_length": target_source["length"], "target_source_sha256": target_source["sha256"], "caller_code_sha256": caller_source["code_sha256"], "target_code_sha256": target_source["code_sha256"], "offset": 0, "edge_sequence": edge_sequence, "edge_role": edge_role, "load_role": role, "channel": channel, "permit_state": state, "phase": state, "allowed": True, "status": "OBSERVED", "outcome": "ALLOW", "failure_reason": None}
            return validate_p1ae_import_event(event)

        previous_import = builtins.__import__
        previous_import_module = importlib.import_module
        previous_dont_write_bytecode = sys.dont_write_bytecode

        def import_guard(name: str, globals: Mapping[str, Any] | None = None, locals: Mapping[str, Any] | None = None, fromlist: Sequence[str] = (), level: int = 0):
            nonlocal internal_edge_sequence
            caller = str((globals or {}).get("__name__", "<unknown>"))
            target = name
            if level:
                try:
                    target = importlib.util.resolve_name(name, caller)
                except ImportError:
                    target = f"{caller.rsplit('.', 1)[0]}.{name}" if name else caller.rsplit('.', 1)[0]
            if target in bootstrap_names:
                result = previous_import(name, globals, locals, fromlist, level)
                loader_guard_seen.add(target)
                kind, role, channel, edge = ("BOOTSTRAP_IMPORT", "P1A_STATIC_BOOTSTRAP", "OWNER_STATIC_EDGE", len(trace)) if phase == "HOST_STATIC_BOUND" else ("CANDIDATE_STATIC_EDGE", "P1AE_STATIC_CANDIDATE_EDGE", "OWNER_SOURCE_LOADER", len(trace))
                trace.append(runtime_event(caller, target, kind, role, channel, phase, edge, role, result))
                return result
            if target in allowed_internal or target.split(".", 1)[0] in {"builtins", "_io"}:
                result = previous_import(name, globals, locals, fromlist, level)
                loader_guard_seen.add(target)
                trace.append(runtime_event(caller, target, "CPYTHON_INTERNAL", "P1AE_INTERNAL_RUNTIME", "BUILTIN", phase, internal_edge_sequence, "P1AE_INTERNAL_RUNTIME", result))
                internal_edge_sequence += 1
                return result
            # Classification and terminal projection happen before the
            # original import.  A forbidden call never reaches importlib.
            target_source = _p1ae_runtime_source(target, None)
            caller_source = exact_sources.get(caller) or _p1ae_runtime_source(caller, sys.modules.get(caller))
            forbidden = {"trace_sequence": len(trace), "event_kind": "DYNAMIC_IMPORT" if phase == "CONSUMED" else "AMBIENT_IMPORT", "caller_module": caller, "target_module": target, "caller_source_ref": caller_source["source_ref"], "caller_source_length": caller_source["length"], "caller_source_sha256": caller_source["sha256"], "target_source_ref": target_source["source_ref"], "target_source_length": target_source["length"], "target_source_sha256": target_source["sha256"], "caller_code_sha256": caller_source["code_sha256"], "target_code_sha256": target_source["code_sha256"], "offset": 0, "edge_sequence": None, "edge_role": None, "load_role": "FORBIDDEN", "channel": "IMPORTLIB_DYNAMIC", "permit_state": phase, "phase": phase, "allowed": False, "status": "TERMINAL_DENY", "outcome": "DENY", "terminal_state": "DENY", "failure_reason": "DYNAMIC_IMPORT" if phase == "CONSUMED" else "AMBIENT_IMPORT"}
            forbidden_events.append(validate_p1ae_forbidden_event(forbidden))
            trace.append(forbidden_events[-1])
            raise _deny("DENIED_CAPABILITY", "forbidden import was captured before it could execute")

        def importlib_guard(name: str, package: str | None = None):
            target = importlib.util.resolve_name(name, package) if name.startswith(".") and package else name
            if target not in bootstrap_names and target not in allowed_internal and target.split(".", 1)[0] not in {"builtins", "_io"}:
                import_guard(target, {"__name__": candidate_name}, None, (), 0)
            return previous_import_module(name, package)

        try:
            def allowed_loader_event(fullname: str) -> None:
                nonlocal internal_edge_sequence
                if fullname in loader_guard_seen:
                    return
                loader_guard_seen.add(fullname)
                if fullname in allowed_internal or fullname.split(".", 1)[0] in {"builtins", "_io"}:
                    trace.append(runtime_event(candidate_name, fullname, "CPYTHON_INTERNAL", "P1AE_INTERNAL_RUNTIME", "BUILTIN", phase, internal_edge_sequence, "P1AE_INTERNAL_RUNTIME", sys.modules.get(fullname)))
                    internal_edge_sequence += 1

            sys.meta_path.insert(0, _P1AEImportGuardFinder(bootstrap_names | allowed_internal, import_guard, allowed_loader_event))
            importlib.import_module = importlib_guard
            for module_name in bootstrap_names:
                existing = sys.modules.get(module_name, missing)
                saved_modules[module_name] = existing
                source = exact_sources[module_name]
                path = _final_path(self.owner_harness.source_root / source["relative_path"], self.owner_harness.source_root, must_exist=True)
                spec = importlib.util.spec_from_file_location(module_name, path)
                if spec is None or spec.loader is None:
                    raise _deny("DENIED_CAPABILITY", "owner bootstrap spec is unavailable")
                module = importlib.util.module_from_spec(spec)
                modules[module_name] = module
                sys.modules[module_name] = module
                builtins.__import__ = import_guard
                trace.append(runtime_event("xiaoshuo.pipeline", module_name, "BOOTSTRAP_IMPORT", "P1A_STATIC_BOOTSTRAP", "OWNER_STATIC_EDGE", "HOST_STATIC_BOUND", len(trace), "P1A_STATIC_BOOTSTRAP", module))
                spec.loader.exec_module(module)
            builtins.__import__ = previous_import
            importlib.import_module = previous_import_module
            snapshots, resolution_hashes, resolution_projection_hash = _p1ae_resolution_projection(owner_id, authority_ref)
            bootstrap_bindings = [_p1ae_loaded_binding_final(modules[name], exact_sources[name], self.owner_harness.source_root) for name in bootstrap_names]
            quality_source = exact_sources[candidate_name]
            candidate_path = _final_path(self.owner_harness.source_root / quality_source["relative_path"], self.owner_harness.source_root, must_exist=True)
            if candidate_name in sys.modules or any(str(getattr(module, "__file__", "")) == str(candidate_path) for module in sys.modules.values() if module is not None):
                raise _deny("DENIED_CAPABILITY", "candidate module or exact source path was preloaded")
            candidate_spec = importlib.util.spec_from_file_location(candidate_name, candidate_path)
            if candidate_spec is None or candidate_spec.loader is None:
                raise _deny("DENIED_CAPABILITY", "candidate spec is unavailable")
            candidate = importlib.util.module_from_spec(candidate_spec)
            modules[candidate_name] = candidate
            expected_bindings, expected_loaded_hash = _p1ae_loaded_projection(bootstrap_bindings + [_p1ae_loaded_binding_final(candidate, quality_source, self.owner_harness.source_root)])
            expected_internal = _p1ae_expected_cpython_allowlist(self.owner_harness)
            internal_events = expected_internal["events"]; internal_edges = expected_internal["edges"]
            internal_event_hash = expected_internal["event_hash"]; internal_edge_hash = expected_internal["edge_hash"]
            expected_internal_comparison = expected_internal["comparison_bytes"]
            empty_forbidden_hash = sha256_bytes(canonical_evaluation_json_bytes({"events": []}, fields=("events",)))
            forbidden_tuple_registry_hash = canonical_sha256({"tuples": []}, fields=("tuples",))
            forbidden_import_preload_rechecked = _p1ae_forbidden_projection_final([])
            if forbidden_import_preload_rechecked["status"] != "CLEAR" or forbidden_import_preload_rechecked["event_count"] != 0:
                raise _deny("DENIED_CAPABILITY", "FORBIDDEN_IMPORT_PRELOAD_RECHECKED failed")
            transition_hash = p1ae_transition_registry_hash("READY")
            source_bindings = [{key: exact_sources[name][key] for key in ("relative_path", "source_ref", "length", "sha256")} for name in sorted(exact_sources)]
            source_module_binding_hash = canonical_sha256({"entries": source_bindings}, fields=("entries",))
            loader_plan = {"loader_plan_schema_version": "P1_AE_PURE_LOADER_PLAN_V1", "plan_id": f"{batch_id}:{attempt_id}", "owner_id": owner_id, "authority_ref": authority_ref, "owner_session_ref": self.owner_harness.owner_session_id, "pure_source_registry_snapshot_hash": source_registry.snapshot_hash, "source_module_binding_hash": source_module_binding_hash, "pure_gate_snapshot_hash": canonical_sha256({"gate": "P1_AE_PURE_GATE_V1", "owner_id": owner_id, "authority_ref": authority_ref}, fields=("gate", "owner_id", "authority_ref")), "resolution_guard_snapshot_hash": resolution_hashes["sys_path_snapshot_hash"], "resolution_live_snapshot_hash": resolution_hashes["sys_path_snapshot_hash"], "bootstrap_sequence": [exact_sources[name]["relative_path"] for name in bootstrap_names], "candidate_root_sequence": [quality_source["relative_path"]], "candidate_static_sequence": list(bootstrap_names), "cpython_internal_expected_sequence": [event["target_module"] for event in internal_events], "cpython_internal_expected_edge_count": len(internal_edges), "cpython_internal_expected_event_count": len(internal_events), "forbidden_expected_count": 0, "forbidden_expected_tuple_registry_hash": forbidden_tuple_registry_hash, "host_loader_invoked": False, "host_gate_mutated": False, "host_permit_mutated": False, "host_candidate_set_read": False, "permit_consumed_before_import": True, "pre_permit_state": "PURE_PERMIT_ISSUED", "post_cas_state": "CAS_CONSUMED", "next_required_state": "INTERNAL_PREFLIGHT_RECHECKED", "transition_status": "ALLOWED", "transition_registry_hash": transition_hash, "status": "READY", **resolution_hashes}
            plan_binding = p1ae_loader_plan_binding(loader_plan)
            expected = {"observation_schema_version": "P1_AE_PURE_IMPORT_EXPECTED_OBSERVATION_V1", "owner_id": owner_id, "authority_ref": authority_ref, "source_registry_snapshot_hash": source_registry.snapshot_hash, "source_module_binding_hash": source_module_binding_hash, **plan_binding, "transition_fields": list(P1_AE_PURE_LOADER_PLAN_TRANSITION_TUPLE), "cpython_internal_expected_edges_hash": internal_edge_hash, "cpython_internal_expected_events_hash": internal_event_hash, "cpython_internal_expected_edge_count": len(internal_edges), "cpython_internal_expected_event_count": len(internal_events), "forbidden_expected_events_hash": empty_forbidden_hash, "forbidden_expected_count": 0, "forbidden_expected_tuple_registry_hash": forbidden_tuple_registry_hash, "phase": "HOST_STATIC_BOUND", "status": "READY", "expected_loaded_module_projection_hash": expected_loaded_hash, "resolution_projection_hash": resolution_projection_hash}
            expected_hash = p1ae_expected_observation_hash(expected)
            package = {"package_schema_version": "P1_AE_PURE_PACKAGE_V1", "owner_id": owner_id, "authority_ref": authority_ref, "source_registry_hash": source_registry.snapshot_hash, "source_module_binding_hash": source_module_binding_hash, "loader_plan_hash": plan_binding["loader_plan_hash"], "loader_plan_length": plan_binding["loader_plan_length"], "transition_registry_hash": transition_hash, "transition_fields": list(P1_AE_PURE_LOADER_PLAN_TRANSITION_TUPLE), "resolution_guard_hash": resolution_hashes["sys_path_snapshot_hash"], "resolution_live_hash": resolution_hashes["sys_path_snapshot_hash"], "expected_observation_hash": expected_hash, "loaded_module_bindings_hash": expected_loaded_hash, "forbidden_projection_hash": empty_forbidden_hash, "status": "READY", "resolution_projection_hash": resolution_projection_hash, "expected_loaded_module_projection_hash": expected_loaded_hash}
            package_hash = canonical_sha256(package, fields=P1_AE_PACKAGE_FIELDS)
            gate_hash = canonical_sha256(package, fields=P1_AE_GATE_PREIMAGE_FIELDS)
            permit_preimage = {"permit_schema_version": "P1_AE_PURE_IMPORT_PERMIT_V1", "owner_id": owner_id, "authority_ref": authority_ref, "owner_session_ref": self.owner_harness.owner_session_id, "package_hash": package_hash, "loader_plan_hash": plan_binding["loader_plan_hash"], "loader_plan_length": plan_binding["loader_plan_length"], "transition_registry_hash": transition_hash, "transition_fields": list(P1_AE_PURE_LOADER_PLAN_TRANSITION_TUPLE), "expected_observation_hash": expected_hash, "loaded_module_bindings_hash": expected_loaded_hash, "forbidden_projection_hash": empty_forbidden_hash, "status": "READY", "resolution_projection_hash": resolution_projection_hash, "expected_loaded_module_projection_hash": expected_loaded_hash, "authority_binding_hash": authority_hashes["composite_authority_binding_hash"]}
            permit_secret, permit_handle = object(), object()
            permit = issue_p1ae_pure_permit(owner_session_ref=self.owner_harness.owner_session_id, preimage=permit_preimage, secret=permit_secret, private_handle=permit_handle, registry=self._p1ae_permit_registry)
            consumed_digest = permit.consume(secret=permit_secret, private_handle=permit_handle)
            reread_sources = _p1ae_exact_module_sources(self)
            _, reread_resolution_hashes, reread_resolution_projection_hash = _p1ae_resolution_projection(owner_id, authority_ref)
            reread_bindings, reread_loaded_hash = _p1ae_loaded_projection(bootstrap_bindings + [_p1ae_loaded_binding_final(candidate, reread_sources[candidate_name], self.owner_harness.source_root)])
            reread_internal = _p1ae_expected_cpython_allowlist(self.owner_harness)
            reread_internal_events = reread_internal["events"]; reread_internal_edges = reread_internal["edges"]
            reread_internal_event_hash = reread_internal["event_hash"]; reread_internal_edge_hash = reread_internal["edge_hash"]
            reread_expected = dict(expected)
            reread_expected.update({"cpython_internal_expected_edges_hash": reread_internal_edge_hash, "cpython_internal_expected_events_hash": reread_internal_event_hash, "expected_loaded_module_projection_hash": reread_loaded_hash, "resolution_projection_hash": reread_resolution_projection_hash})
            if canonical_sha256({"entries": [{key: reread_sources[name][key] for key in ("relative_path", "source_ref", "length", "sha256")} for name in sorted(reread_sources)]}, fields=("entries",)) != source_module_binding_hash or p1ae_loader_plan_hash(loader_plan) != plan_binding["loader_plan_hash"] or len(p1ae_loader_plan_bytes(loader_plan)) != plan_binding["loader_plan_length"] or reread_resolution_hashes != resolution_hashes or reread_resolution_projection_hash != resolution_projection_hash or reread_internal_edge_hash != internal_edge_hash or reread_internal_event_hash != internal_event_hash or p1ae_expected_observation_hash(reread_expected) != expected_hash or reread_loaded_hash != expected_loaded_hash or canonical_sha256(package, fields=P1_AE_PACKAGE_FIELDS) != package_hash or canonical_sha256(package, fields=P1_AE_GATE_PREIMAGE_FIELDS) != gate_hash or canonical_sha256(permit_preimage, fields=P1_AE_PERMIT_PREIMAGE_FIELDS) != consumed_digest:
                raise _deny("DENIED_CAPABILITY", "PURE_INTERNAL_PREFLIGHT_RECHECKED mismatch before dynamic import")
            phase = "CONSUMED"
            builtins.__import__ = import_guard
            # Candidate-root admission is the first dynamic event and is
            # fixed before executing candidate code.
            trace.append(runtime_event("xiaoshuo.pipeline", candidate_name, "CANDIDATE_ROOT_IMPORT", "P1AE_DYNAMIC_CANDIDATE", "IMPORTLIB_DYNAMIC", "CONSUMED", None, None, candidate))
            candidate_spec.loader.exec_module(candidate)
            builtins.__import__ = previous_import
            loaded_bindings, loaded_hash = _p1ae_loaded_projection([_p1ae_loaded_binding_final(modules[name], reread_sources[name], self.owner_harness.source_root) for name in (*bootstrap_names, candidate_name)])
            if loaded_hash != expected_loaded_hash:
                raise _deny("DENIED_PROVENANCE", "loaded module projection differs from permit expected hash")
            _, post_resolution_hashes, post_resolution_projection_hash = _p1ae_resolution_projection(owner_id, authority_ref)
            if post_resolution_hashes != resolution_hashes or post_resolution_projection_hash != resolution_projection_hash:
                raise _deny("DENIED_CAPABILITY", "post-load resolution environment differs from pre-permit observation")
            forbidden_projection = _p1ae_forbidden_projection_final(forbidden_events)
            forbidden_import_postload_rechecked = forbidden_projection
            if forbidden_projection["status"] != "CLEAR" or forbidden_projection["event_count"] != 0 or forbidden_projection["terminal_state"] != "NONE":
                raise _deny("DENIED_CAPABILITY", "FORBIDDEN_IMPORT_EVENT_CAPTURED terminal deny")
            observed_internal = _p1ae_cpython_projection(trace, observed=True)
            observed_internal_events = observed_internal["events"]; observed_internal_edges = observed_internal["edges"]
            observed_internal_event_hash = observed_internal["event_hash"]; observed_internal_edge_hash = observed_internal["edge_hash"]
            if observed_internal["comparison_bytes"] != expected_internal_comparison or observed_internal["event_count"] != len(internal_events) or observed_internal["edge_count"] != len(internal_edges):
                raise _deny("DENIED_CAPABILITY", "PURE_INTERNAL_OBSERVED_RECHECKED mismatch")
            evidence = _p1ae_quality_evidence_final(self, owner_input, batch_id=batch_id, attempt_id=attempt_id, transaction_id=f"{batch_id}:{attempt_id}")
            transaction = {"transaction_schema_version": P1_AE_PURE_LOADER_TRANSACTION_SCHEMA_VERSION, "transaction_id": f"{batch_id}:{attempt_id}", "owner_id": owner_id, "authority_ref": authority_ref, "owner_session_ref": self.owner_harness.owner_session_id, "loader_plan_hash": plan_binding["loader_plan_hash"], "loader_plan_length": plan_binding["loader_plan_length"], "transition_registry_hash": transition_hash, "transition_fields": list(P1_AE_PURE_LOADER_PLAN_TRANSITION_TUPLE), "permit_digest": consumed_digest, "permit_cas_sequence": 1, "dynamic_load_count": 1, "dynamic_load_order": [quality_source["relative_path"]], "loaded_module_bindings_hash": loaded_hash, "import_trace_hash": canonical_sha256({"events": trace}, fields=("events",)), "forbidden_projection_hash": p1ae_forbidden_projection_hash(forbidden_projection), "observed_projection_hash": canonical_sha256({"events": trace}, fields=("events",)), **evidence, "state": "COMMITTED", "status": "READY", "resolution_projection_hash": resolution_projection_hash, "authority_binding_hash": authority_hashes["composite_authority_binding_hash"]}
            transaction.update({"cpython_internal_expected_events_hash": internal_event_hash, "cpython_internal_expected_edges_hash": internal_edge_hash, "cpython_internal_expected_event_count": len(internal_events), "cpython_internal_expected_edge_count": len(internal_edges), "cpython_internal_observed_events_hash": observed_internal_event_hash, "cpython_internal_observed_edges_hash": observed_internal_edge_hash, "cpython_internal_observed_event_count": len(observed_internal_events), "cpython_internal_observed_edge_count": len(observed_internal_edges)})
            transaction_hash = canonical_sha256(transaction, fields=P1_AE_LOADER_TRANSACTION_PREIMAGE_FIELDS)
            semantic_hash = canonical_sha256(bundle, fields=("bundle_schema_version", "study_id", "owner_id", "authority_ref", "source_snapshot_hash", "rubric_hash", "sampling_plan_hash", "strata", "clusters", "cases", "status"))
            binding_records = {
                "package": {"fields": list(P1_AE_PACKAGE_FIELDS), "record": dict(package), "hash": package_hash},
                "gate": {"fields": list(P1_AE_GATE_PREIMAGE_FIELDS), "record": dict(package), "hash": gate_hash},
                "permit": {"fields": list(P1_AE_PERMIT_PREIMAGE_FIELDS), "record": dict(permit_preimage), "hash": consumed_digest},
                "transaction": {"fields": list(P1_AE_LOADER_TRANSACTION_PREIMAGE_FIELDS), "record": dict(transaction), "hash": transaction_hash},
                "authority": {"fields": ["authority_record", "handle_binding", "hashes"], "record": {"authority_record": authority_record, "handle_binding": handle_binding, "hashes": authority_hashes}, "hash": canonical_sha256({"authority_record": authority_record, "handle_binding": handle_binding, "hashes": authority_hashes}, fields=("authority_record", "handle_binding", "hashes"))},
                "writer": {"fields": ["owner_writer_observation", "owner_post_write_evidence"], "record": {"owner_writer_observation": self.owner_harness._owner_writer_observation_snapshot(), "owner_post_write_evidence": self._p1ae_last_post_write_evidence}, "hash": canonical_sha256({"owner_writer_observation": self.owner_harness._owner_writer_observation_snapshot(), "owner_post_write_evidence": self._p1ae_last_post_write_evidence}, fields=("owner_writer_observation", "owner_post_write_evidence"))},
                "residue": {"fields": ["residue_snapshot"], "record": {"residue_snapshot": self._p1ae_last_post_write_evidence["residue_snapshot"]}, "hash": canonical_sha256({"residue_snapshot": self._p1ae_last_post_write_evidence["residue_snapshot"]}, fields=("residue_snapshot",))},
                "pairing": {"fields": ["residue_pairing"], "record": {"residue_pairing": self._p1ae_last_post_write_evidence["residue_pairing"]}, "hash": canonical_sha256({"residue_pairing": self._p1ae_last_post_write_evidence["residue_pairing"]}, fields=("residue_pairing",))},
            }
            admission = {"admission_schema_version": P1_AE_OWNER_ADMISSION_SCHEMA_VERSION, "owner_id": owner_id, "authority_ref": authority_ref, "owner_session_ref": self.owner_harness.owner_session_id, "source_registry_hash": source_registry.snapshot_hash, "package_hash": package_hash, "gate_hash": gate_hash, "permit_digest": consumed_digest, "loader_plan_hash": plan_binding["loader_plan_hash"], "loader_plan_length": plan_binding["loader_plan_length"], "transition_registry_hash": transition_hash, "transition_fields": list(P1_AE_PURE_LOADER_PLAN_TRANSITION_TUPLE), "transaction_hash": transaction_hash, "loaded_module_bindings_hash": loaded_hash, **evidence, "semantic_hash": semantic_hash, "raw_authority_bytes_hash": authority_hashes["raw_authority_bytes_hash"], "authority_record_hash": authority_hashes["authority_record_hash"], "authority_handle_binding_hash": authority_hashes["handle_binding_hash"], "composite_authority_binding_hash": authority_hashes["composite_authority_binding_hash"], "status": "ADMITTED", "resolution_projection_hash": resolution_projection_hash, "authority_binding_hash": authority_hashes["composite_authority_binding_hash"], "owner_registry_snapshot_hash": registry.snapshot_hash, "owner_annotation_projection_hash": owner_annotation_projection_hash}
            admission["binding_records"] = binding_records
            admission.update({"cpython_internal_expected_events_hash": internal_event_hash, "cpython_internal_expected_edges_hash": internal_edge_hash, "cpython_internal_expected_event_count": len(internal_events), "cpython_internal_expected_edge_count": len(internal_edges), "cpython_internal_observed_events_hash": observed_internal_event_hash, "cpython_internal_observed_edges_hash": observed_internal_edge_hash, "cpython_internal_observed_event_count": len(observed_internal_events), "cpython_internal_observed_edge_count": len(observed_internal_edges)})
            return modules[candidate_name].evaluate_quality_bundle(admission, bundle), transaction_hash
        except Exception:
            raise
        finally:
            builtins.__import__ = previous_import
            importlib.import_module = previous_import_module
            sys.dont_write_bytecode = previous_dont_write_bytecode
            sys.path[:] = environment_before["sys_path"]
            sys.meta_path[:] = environment_before["meta_path"]
            sys.path_hooks[:] = environment_before["path_hooks"]
            if os.getcwd() != environment_before["cwd"]:
                os.chdir(environment_before["cwd"])
            previous_modules = environment_before["modules"]
            for module_name in tuple(sys.modules):
                if module_name not in previous_modules:
                    sys.modules.pop(module_name, None)
            for module_name, previous in previous_modules.items():
                sys.modules[module_name] = previous


OfflineDeterministicEvaluator._p1ae_pure_loader = _p1ae_pure_loader_gated
OfflineDeterministicEvaluator._p1ae_quality_evidence = _p1ae_quality_evidence_final

# Final deterministic helper overrides.  Runtime identity is observed for
# readback, but only stable module/path/source facts enter canonical hashes.
def _p1ae_loaded_binding_final(module: types.ModuleType, expected: Mapping[str, Any], root: Path) -> dict[str, Any]:
    path = _final_path(root / expected["relative_path"], root, must_exist=True); spec = getattr(module, "__spec__", None); actual_file = getattr(module, "__file__", None); actual_origin = getattr(spec, "origin", None) if spec is not None else None
    if spec is None or str(actual_file) != str(path) or str(actual_origin) != str(path) or module.__name__ != expected["module_name"]: raise _deny("DENIED_PROVENANCE", "loaded module exact path/spec/module binding failed")
    content = _strict_bytes(path.read_bytes(), "P1-AE loaded source readback")
    if len(content) != expected["length"] or sha256_bytes(content) != expected["sha256"]: raise _deny("DENIED_PROVENANCE", "loaded module source readback changed")
    return {"module_name": module.__name__, "module_identity": str(module.__name__), "spec_identity": str(actual_origin), "module_file": str(actual_file), "spec_origin": str(actual_origin), "source_ref": expected["source_ref"], "source_length": expected["length"], "source_sha256": expected["sha256"], "code_sha256": expected["code_sha256"], "postload_source_length": len(content), "postload_source_sha256": sha256_bytes(content), "readback_status": "BOUND"}

def _p1ae_loaded_projection(bindings: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], str]:
    ordered = sorted((dict(item) for item in bindings), key=lambda item: item["module_name"].encode("utf-8")); binding_hash = canonical_sha256({"bindings": ordered}, fields=("bindings",)); projection = {"bindings": ordered, "binding_hash": binding_hash, "status": "BOUND"}; return projection, canonical_sha256(projection, fields=P1_AE_LOADED_MODULE_BINDINGS_FIELDS)

def _p1ae_stable_object_token(value: Any) -> str:
    cls = type(value); module_name = getattr(value, "__module__", cls.__module__); qualname = getattr(value, "__qualname__", cls.__qualname__); return f"{module_name}.{qualname}"

def _p1ae_resolution_projection(owner_id: str, authority_ref: str) -> tuple[dict[str, Any], dict[str, str], str]:
    def entry(kind: str, sequence: int, value: str, value_kind: str) -> dict[str, Any]:
        normalized = unicodedata.normalize("NFC", value); raw = normalized.encode("utf-8"); return {"entry_sequence": sequence, "value": value, "value_kind": value_kind, "normalized_value": normalized, "source_ref": f"P1-AE:{kind}:{sequence}", "source_length": len(raw), "source_sha256": sha256_bytes(raw), "collision_key": normalized.casefold(), "status": "OBSERVED"}
    values = {"SYS_PATH": [str(item) for item in sys.path], "META_PATH": [_p1ae_stable_object_token(item) for item in sys.meta_path], "PATH_HOOKS": [_p1ae_stable_object_token(item) for item in sys.path_hooks], "PRELOADED_MODULES": [f"{name}|{getattr(module, '__file__', '<builtin>')}" for name, module in sorted(sys.modules.items()) if module is not None], "PRELOADED_SOURCE_PATHS": sorted({str(getattr(module, "__file__")) for module in sys.modules.values() if module is not None and getattr(module, "__file__", None)}, key=lambda item: unicodedata.normalize("NFC", item).encode("utf-8"))}
    snapshots: dict[str, dict[str, Any]] = {}; hashes: dict[str, str] = {}
    for kind, raw_values in values.items():
        rows = [entry(kind, index, value, "PATH" if kind in {"SYS_PATH", "PRELOADED_SOURCE_PATHS"} else "MODULE") for index, value in enumerate(raw_values)]; nested = canonical_evaluation_json_bytes({"entries": rows}, fields=("entries",)); snapshot = {"snapshot_schema_version": P1_AE_RESOLUTION_SPECIALIZED_SCHEMA_BY_KIND[kind], "snapshot_kind": kind, "owner_id": owner_id, "authority_ref": authority_ref, "entry_count": len(rows), "complete": True, "entries": rows, "nested_preimage_hash": sha256_bytes(nested), "status": "READY"}; snapshots[kind] = snapshot; hashes[f"{kind.lower()}_snapshot_hash"] = p1ae_resolution_snapshot_hash(snapshot)
    cwd = os.getcwd(); raw = cwd.encode("utf-8"); cwd_snapshot = {"snapshot_schema_version": P1_AE_RESOLUTION_CWD_SCHEMA_VERSION, "snapshot_kind": "CWD", "owner_id": owner_id, "authority_ref": authority_ref, "entry_count": 1, "complete": True, "path": cwd, "path_kind": "ABSOLUTE", "source_ref": "P1-AE:CWD:0", "source_length": len(raw), "source_sha256": sha256_bytes(raw), "status": "READY"}; snapshots["CWD"] = cwd_snapshot; hashes["cwd_snapshot_hash"] = p1ae_resolution_snapshot_hash(cwd_snapshot)
    projection = {"snapshots": snapshots, "snapshot_hashes": hashes, "status": "READY"}; return snapshots, hashes, canonical_sha256(projection, fields=("snapshots", "snapshot_hashes", "status"))

def _p1ae_internal_projections(events: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, str]:
    internal = [dict(event) for event in events if event["event_kind"] == "CPYTHON_INTERNAL"]; edges = [{"edge_sequence": event["edge_sequence"], "source_ref": event["target_source_ref"], "source_length": event["target_source_length"], "source_sha256": event["target_source_sha256"], "code_sha256": event["target_code_sha256"], "offset": event["offset"], "role": event["load_role"], "channel": event["channel"], "permit_state": event["permit_state"]} for event in internal]; event_hash = canonical_sha256({"events": internal}, fields=("events",)); edge_hash = canonical_sha256({"edges": edges}, fields=("edges",)); return internal, edges, event_hash, edge_hash

class _P1AEImportGuardFinder:
    """Meta-path guard for importlib/loader paths that bypass __import__."""
    def __init__(self, allowed: set[str], callback: Any, allowed_callback: Any = None):
        self._allowed = frozenset(allowed); self._callback = callback; self._allowed_callback = allowed_callback
    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> Any:
        if fullname in self._allowed or fullname.split(".", 1)[0] in {"builtins", "_io"}:
            if self._allowed_callback is not None:
                self._allowed_callback(fullname)
            return None
        self._callback(fullname, {"__name__": "xiaoshuo.pipeline.quality_evaluation"}, None, (), 0)
        raise _deny("DENIED_CAPABILITY", "forbidden meta_path import was captured before loader execution")

def _p1ae_cpython_projection(events: Sequence[Mapping[str, Any]], *, observed: bool) -> dict[str, Any]:
    rows = [dict(event) for event in events if event["event_kind"] == "CPYTHON_INTERNAL"]
    for row in rows:
        if observed:
            row["status"] = "OBSERVED"; row["outcome"] = "ALLOW"
        else:
            row["status"] = "ALLOWED"; row["outcome"] = "ALLOW"
    edges = [{"edge_sequence": row["edge_sequence"], "source_ref": row["target_source_ref"], "source_length": row["target_source_length"], "source_sha256": row["target_source_sha256"], "code_sha256": row["target_code_sha256"], "offset": row["offset"], "role": row["load_role"], "channel": row["channel"], "permit_state": row["permit_state"]} for row in rows]
    projection = {"events": rows, "edges": edges, "event_count": len(rows), "edge_count": len(edges)}
    projection["event_hash"] = p1ae_cpython_internal_projection_hash({key: projection[key] for key in ("events", "edges", "event_count", "edge_count")}, observed=observed)
    projection["edge_hash"] = canonical_sha256({"edges": edges}, fields=("edges",))
    comparison_events = [{field: row[field] for field in P1_AE_CPYTHON_INTERNAL_COMPARISON_FIELDS} for row in rows]
    comparison_edges = [{field: row[field] for field in P1_AE_CPYTHON_INTERNAL_COMPARISON_FIELDS if field in row} for row in edges]
    projection["comparison_bytes"] = canonical_evaluation_json_bytes({"events": comparison_events, "edges": comparison_edges}, fields=("events", "edges"))
    return projection


def _p1ae_expected_cpython_allowlist(owner_harness: OwnerHarness) -> dict[str, Any]:
    """Return the owner-derived pre-CAS allowlist, never a trace projection."""
    events = getattr(owner_harness, "_p1ae_cpython_internal_expected_allowlist", None)
    if events is None:
        probe = getattr(owner_harness, "_owner_probe_binding", None)
        events = probe.get("cpython_internal_expected_events") if isinstance(probe, Mapping) else None
    if not isinstance(events, (list, tuple)):
        raise _deny("DENIED_CAPABILITY", "owner cannot derive a complete CPython internal expected allowlist")
    rows: list[dict[str, Any]] = []
    for source in events:
        if not isinstance(source, Mapping):
            raise _deny("DENIED_CAPABILITY", "owner CPython internal allowlist entry is not canonical")
        row = dict(source)
        row["status"] = "OBSERVED"
        row["outcome"] = "ALLOW"
        row["phase"] = row.get("permit_state")
        row["event_kind"] = "CPYTHON_INTERNAL"
        row["load_role"] = "P1AE_INTERNAL_RUNTIME"
        row["channel"] = "BUILTIN"
        row["edge_role"] = "P1AE_INTERNAL_RUNTIME"
        row["allowed"] = True
        rows.append(validate_p1ae_import_event(row))
    projection = _p1ae_cpython_projection(rows, observed=False)
    projection["expected_projection_status"] = "ALLOWLIST_ONLY"
    projection["observed_trace"] = False
    return projection
