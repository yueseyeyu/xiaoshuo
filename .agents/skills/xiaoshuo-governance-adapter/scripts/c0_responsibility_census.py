from __future__ import annotations

import argparse
import ast
import hashlib
import json
import platform
import re
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


LAB_ROOT = Path(__file__).resolve().parents[5]
CORE_SCRIPTS = LAB_ROOT / ".agents" / "skills" / "governed-token-efficient-collaboration" / "scripts"
if str(CORE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(CORE_SCRIPTS))

from governance_common import (
    canonical_json_bytes,
    checked_resolve,
    enumerate_files_checked,
    read_checked,
    sha256_file,
    strict_json_load_file,
)


SOURCE_PATHS = (
    "src/xiaoshuo/pipeline/evaluation_contracts.py",
    "src/xiaoshuo/pipeline/offline_evaluation.py",
    "src/xiaoshuo/pipeline/quality_evaluation.py",
    "src/xiaoshuo/pipeline/evaluation_metrics.py",
    "src/xiaoshuo/evaluation/__init__.py",
    "src/xiaoshuo/evaluation/contracts/__init__.py",
    "src/xiaoshuo/evaluation/contracts/canonical.py",
    "src/xiaoshuo/evaluation/contracts/owner.py",
    "src/xiaoshuo/evaluation/contracts/transition.py",
    "src/xiaoshuo/evaluation/owner/__init__.py",
    "src/xiaoshuo/evaluation/owner/capability.py",
    "src/xiaoshuo/evaluation/owner/publications.py",
    "src/xiaoshuo/evaluation/owner/registry.py",
    "src/xiaoshuo/evaluation/owner/transaction.py",
)
PRE_RECEIPT_ARTIFACTS = (
    "checkpoint.json",
    "source-inventory.json",
    "definition-census.json",
    "import-census.json",
    "dynamic-marker-census.json",
    "symbol-owner-map.json",
    "importer-matrix.json",
    "hash-domain-matrix.json",
    "lifecycle-matrix.json",
    "cycle-census.json",
    "facade-decision.json",
    "c1-input-contract.md",
    "payload-manifest.json",
    "result.json",
    "stage-ledger.jsonl",
    *(f"frozen-source/{path}" for path in SOURCE_PATHS),
)
CHECKSUM_ARTIFACTS = (*PRE_RECEIPT_ARTIFACTS, "receipt.json")
UNHASHED_ARTIFACTS = ("evidence-closure-manifest.json", "SHA256SUMS.txt")
C0_ARTIFACTS = (*CHECKSUM_ARTIFACTS, *UNHASHED_ARTIFACTS)
IMPORT_RE = re.compile(
    r"xiaoshuo\.pipeline\.(evaluation_contracts|offline_evaluation|quality_evaluation|evaluation_metrics)|"
    r"xiaoshuo\.evaluation|from \.(evaluation_contracts|offline_evaluation|quality_evaluation|evaluation_metrics)|"
    r"import (evaluation_contracts|offline_evaluation|quality_evaluation|evaluation_metrics)"
)
DYNAMIC_RE = re.compile(
    r"importlib|spec_from_file_location|sys\.modules|getattr\(|setattr\(|monkeypatch|__all__|from .* import \*"
)
EVIDENCE_CONTAINER_ROOT = Path(r"D:\tmp\yeyu-ai-a3")
C0_STAGE_ID = "evaluation-responsibility-split-c0-census"
C0_ACCEPTANCE_MATRIX = (
    "C0-01: approved D-drive containment, root absent before creation, no reparse",
    "C0-02: 14 frozen sources byte-identical before and after census",
    "C0-03: inventory records bytes, lines, sha256, encoding, BOM, NUL and decode status",
    "C0-04: all top-level definitions and duplicates retained without runtime claims",
    "C0-05: direct importer census covers production and test Python roots",
    "C0-06: dynamic marker census records unresolved targets as UNKNOWN",
    "C0-07: each legacy entry has importer, consumer kind, migration batch and facade requirement",
    "C0-08: each canonical/hash contract records schema, fields, preimage, canonicalization, producer and consumer",
    "C0-09: owner expected, runtime observed, projection, lineage and admission lifecycles remain separate",
    "C0-10: cycle census distinguishes static cycles, one-way edges and dynamic unknowns",
    "C0-11: facade decisions are NOT_REQUIRED, TEMPORARY_REQUIRED or UNKNOWN only",
    "C0-12: c1-input-contract.md starts with NOT_AUTHORIZED and records all C1 blockers",
    "C0-13: result conclusion is RESPONSIBILITY_CENSUS_ONLY with required UNPROVEN limits",
    "C0-14: exact 32 artifacts, 30 checksums, provenance, packet, ledger and closure verify",
)


def _require_d_drive(path: Path, label: str) -> None:
    if not path.is_absolute() or path.drive.upper() != "D:":
        raise ValueError(f"{label} 必须位于 D 盘绝对路径")


def _source_path(project_root: Path, relative: str) -> Path:
    checked_project_root = checked_resolve(project_root)
    return checked_resolve(checked_project_root / relative, checked_project_root)


def assert_artifact_contract(paths: Iterable[str]) -> None:
    values = tuple(paths)
    if len(values) != len(set(values)):
        raise ValueError("artifact 合同包含重复路径")
    if set(values) != set(C0_ARTIFACTS):
        raise ValueError("artifact 合同不完整或包含未声明路径")


def _prepare_stage_root(evidence_root: Path) -> Path:
    """创建前后校验唯一获准的 C0 stage 容器，不将其计入 evidence。"""
    _require_d_drive(evidence_root, "evidence_root")
    checked_container = checked_resolve(EVIDENCE_CONTAINER_ROOT)
    stage_root = EVIDENCE_CONTAINER_ROOT / C0_STAGE_ID
    if evidence_root.parent != stage_root:
        raise ValueError("C0 evidence_root 必须直接位于获准 stage root")
    if stage_root.exists():
        return checked_resolve(stage_root, checked_container)
    checked_resolve(stage_root.parent, checked_container)
    stage_root.mkdir()
    return checked_resolve(stage_root, checked_container)


def create_evidence_root(evidence_root: Path) -> Path:
    """只在已核验的 stage 容器内创建此前不存在的单个 run root。"""
    stage_root = _prepare_stage_root(evidence_root)
    if evidence_root.exists():
        raise ValueError("C0 evidence_root 已存在")
    evidence_root.mkdir()
    return checked_resolve(evidence_root, stage_root)


def dry_preflight(
    project_root: Path,
    evidence_root: Path,
    expected_source_sha256s: Mapping[str, str],
) -> dict[str, Any]:
    _require_d_drive(project_root, "project_root")
    _require_d_drive(evidence_root, "evidence_root")
    checked_resolve(project_root)
    _prepare_stage_root(evidence_root)
    if evidence_root.exists():
        raise ValueError("C0 evidence_root 已存在")
    if set(expected_source_sha256s) != set(SOURCE_PATHS):
        raise ValueError("source SHA 合同不等于固定 14 个路径")
    actual = {relative: sha256_file(_source_path(project_root, relative)) for relative in SOURCE_PATHS}
    if actual != dict(expected_source_sha256s):
        raise ValueError("source SHA 与 packet 不匹配")
    return {"source_sha256s": actual, "artifact_contract": list(C0_ARTIFACTS)}


def freeze_sources(
    project_root: Path,
    evidence_root: Path,
    expected_source_sha256s: Mapping[str, str],
    before_second_read: Callable[[], None] | None = None,
) -> dict[str, str]:
    frozen: dict[str, str] = {}
    for relative in SOURCE_PATHS:
        source = _source_path(project_root, relative)
        source_bytes = read_checked(source, project_root)
        if hashlib.sha256(source_bytes).hexdigest() != expected_source_sha256s[relative]:
            raise ValueError(f"source drift before freeze: {relative}")
        target = evidence_root / "frozen-source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source_bytes)
        if read_checked(target, evidence_root) != source_bytes:
            raise ValueError(f"frozen source readback 失败: {relative}")
        frozen[relative] = hashlib.sha256(source_bytes).hexdigest()
    if before_second_read is not None:
        before_second_read()
    reread = {relative: sha256_file(_source_path(project_root, relative)) for relative in SOURCE_PATHS}
    if reread != frozen:
        raise ValueError("source drift after freeze")
    return frozen


def _write_json(root: Path, relative: str, value: Any) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(canonical_json_bytes(value))


def _source_inventory(root: Path, frozen_source_sha256s: Mapping[str, str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for relative in SOURCE_PATHS:
        data = read_checked(root / "frozen-source" / relative, root)
        records.append(
            {
                "bom": data.startswith(b"\xef\xbb\xbf"),
                "bytes": len(data),
                "decode_status": "UTF8" if _is_utf8(data) else "UNREADABLE_UTF8",
                "lines": data.count(b"\n") + (1 if data else 0),
                "nul": b"\x00" in data,
                "path": relative,
                "sha256": frozen_source_sha256s[relative],
            }
        )
    return records


def _is_utf8(data: bytes) -> bool:
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _definition_records(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for relative in SOURCE_PATHS:
        source = root / "frozen-source" / relative
        data = read_checked(source, root)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            records.append(
                {
                    "path": relative,
                    "line": None,
                    "column": None,
                    "kind": "UNKNOWN",
                    "name": "UNKNOWN",
                    "annotation": "UNKNOWN",
                    "is_public": "UNKNOWN",
                    "is_final": "UNKNOWN",
                    "definition_order": None,
                    "static_active_candidate": "UNKNOWN",
                    "evidence_ref": _evidence_ref(f"frozen-source/{relative}"),
                    "status": "UNREADABLE_UTF8",
                    "blocker": "UTF-8 decode failed; definition census is fail-closed",
                }
            )
            continue
        try:
            tree = ast.parse(text, filename=relative)
        except (SyntaxError, ValueError, TypeError) as exc:
            records.append(
                {
                    "path": relative,
                    "line": None,
                    "column": None,
                    "kind": "UNKNOWN",
                    "name": "UNKNOWN",
                    "annotation": "UNKNOWN",
                    "is_public": "UNKNOWN",
                    "is_final": "UNKNOWN",
                    "definition_order": None,
                    "static_active_candidate": "UNKNOWN",
                    "evidence_ref": _evidence_ref(f"frozen-source/{relative}"),
                    "status": "AST_PARSE_ERROR",
                    "blocker": f"AST parse failed ({type(exc).__name__}); definition census is fail-closed",
                }
            )
            continue

        for definition_order, node in enumerate(tree.body, 1):
            names: list[tuple[str, ast.AST | None, bool]] = []
            if isinstance(node, ast.ClassDef):
                names.append((node.name, None, False))
                kind = "class"
            elif isinstance(node, ast.FunctionDef):
                names.append((node.name, None, False))
                kind = "function"
            elif isinstance(node, ast.AsyncFunctionDef):
                names.append((node.name, None, False))
                kind = "async_function"
            elif isinstance(node, ast.Assign):
                kind = "constant"
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        names.append((target.id, None, False))
            elif isinstance(node, ast.AnnAssign):
                kind = "constant"
                if isinstance(node.target, ast.Name):
                    names.append((node.target.id, node.annotation, _is_final_annotation(node.annotation)))
            else:
                continue
            for name, annotation_node, is_final in names:
                try:
                    annotation = ast.unparse(annotation_node) if annotation_node is not None else None
                except (AttributeError, TypeError):
                    annotation = "UNKNOWN"
                    is_final = "UNKNOWN"
                records.append(
                    {
                        "path": relative,
                        "line": node.lineno,
                        "column": node.col_offset,
                        "kind": kind,
                        "name": name,
                        "annotation": annotation,
                        "is_public": not name.startswith("_"),
                        "is_final": is_final,
                        "definition_order": definition_order,
                        "static_active_candidate": False,
                        "evidence_ref": _evidence_ref(f"frozen-source/{relative}", node.lineno),
                    }
                )

    last_by_name: dict[str, int] = {}
    for index, record in enumerate(records):
        if record["name"] != "UNKNOWN":
            last_by_name[record["name"]] = index
    for index, record in enumerate(records):
        if record["name"] != "UNKNOWN":
            record["static_active_candidate"] = last_by_name[record["name"]] == index
    return records


def _is_final_annotation(annotation: ast.AST) -> bool:
    if isinstance(annotation, ast.Name):
        return annotation.id == "Final"
    return isinstance(annotation, ast.Subscript) and isinstance(annotation.value, ast.Name) and annotation.value.id == "Final"


def _python_files(project_root: Path) -> list[Path]:
    checked_project_root = checked_resolve(project_root)
    files: list[Path] = []
    for root in (checked_project_root / "src" / "xiaoshuo", checked_project_root / "tests"):
        if not root.is_dir():
            continue
        checked_root = checked_resolve(root, checked_project_root)
        for relative in sorted(enumerate_files_checked(checked_root)):
            if relative.endswith(".py"):
                files.append(checked_root / relative)
    return files


def _text_census(project_root: Path, pattern: re.Pattern[str], kind: str) -> list[dict[str, Any]]:
    checked_project_root = checked_resolve(project_root)
    records: list[dict[str, Any]] = []
    for path in _python_files(checked_project_root):
        text = read_checked(path, checked_project_root).decode("utf-8")
        for line_number, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                records.append(
                    {
                        "kind": kind,
                        "line": line_number,
                        "path": path.relative_to(checked_project_root).as_posix(),
                        "text": line,
                    }
                )
    return records


def _evidence_ref(path: str, line: int | None = None) -> list[str]:
    suffix = f"#{line}" if line is not None else ""
    return [f"{path}{suffix}"]


def _symbol_owner_records(definitions: list[dict[str, Any]], imports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for definition in definitions:
        grouped.setdefault(definition["name"], []).append(definition)
    records: list[dict[str, Any]] = []
    for name in sorted(grouped):
        refs = grouped[name]
        ambiguous = len(refs) > 1
        consumers = [item["path"] for item in imports if name in item["text"]]
        first = refs[0]
        records.append(
            {
                "symbol": name,
                "all_definition_refs": [{"path": item["path"], "line": item["line"]} for item in refs],
                "static_active_candidate": [
                    {"path": item["path"], "line": item["line"], "active": item["static_active_candidate"]}
                    for item in refs
                ],
                "current_module": next((item["path"] for item in refs if item["static_active_candidate"]), "UNKNOWN"),
                "candidate_owner": next((item["path"] for item in refs if item["static_active_candidate"]), "UNKNOWN"),
                "owner_basis": "STATIC_DEFINITION_RECORD",
                "consumer_refs": consumers,
                "status": "CONFLICT" if ambiguous else "STATIC_CANDIDATE",
                "evidence_refs": _evidence_ref("definition-census.json", first["line"]),
                **({"blocker": "多个静态定义，需独立复审；静态 active 仅表示最后定义"} if ambiguous else {}),
            }
        )
    if not records:
        records.append({"symbol": "UNKNOWN", "all_definition_refs": [], "static_active_candidate": "UNKNOWN", "current_module": "UNKNOWN", "candidate_owner": "UNKNOWN", "owner_basis": "UNKNOWN", "consumer_refs": [], "status": "UNKNOWN", "evidence_refs": _evidence_ref("definition-census.json"), "blocker": "未发现可证明静态定义"})
    return records


def _importer_matrix_records(imports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in imports:
        text = item["text"]
        imported_surface = text.strip()
        records.append(
            {
                "importer": item["path"],
                "imported_surface": imported_surface,
                "mechanism": item["kind"],
                "consumer_kind": "TEST" if item["path"].startswith("tests/") else "PRODUCTION",
                "migration_batch": "UNKNOWN",
                "facade_requirement": "UNKNOWN",
                "evidence_refs": _evidence_ref("import-census.json", item["line"]),
                "blocker": "未授权迁移设计，无法推断 migration_batch/facade_requirement",
            }
        )
    if not records:
        records.append({"importer": "UNKNOWN", "imported_surface": "UNKNOWN", "mechanism": "UNKNOWN", "consumer_kind": "UNKNOWN", "migration_batch": "UNKNOWN", "facade_requirement": "UNKNOWN", "evidence_refs": _evidence_ref("import-census.json"), "blocker": "未发现静态 importer 命中"})
    return records


def _hash_domain_records(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    pattern = re.compile(r"sha256|canonical|schema|version|hash", re.IGNORECASE)
    for relative in SOURCE_PATHS:
        text = read_checked(root / "frozen-source" / relative, root).decode("utf-8")
        for line_number, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                records.append({"object": line.strip()[:160], "path": relative, "line": line_number, "schema": "UNKNOWN", "fields": "UNKNOWN", "preimage": "UNKNOWN", "canonicalization": "UNKNOWN", "producer": relative, "consumer": "UNKNOWN", "status": "STATIC_CLUE", "evidence_refs": _evidence_ref(f"frozen-source/{relative}", line_number), "blocker": "仅证明文本/AST clue，未执行运行时契约"})
    if not records:
        records.append({"object": "UNKNOWN", "path": "UNKNOWN", "line": None, "schema": "UNKNOWN", "fields": "UNKNOWN", "preimage": "UNKNOWN", "canonicalization": "UNKNOWN", "producer": "UNKNOWN", "consumer": "UNKNOWN", "status": "UNKNOWN", "evidence_refs": _evidence_ref("source-inventory.json"), "blocker": "未发现静态 hash/canonical/schema/version clue"})
    return records


def _lifecycle_records(definitions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    subjects = sorted({item["name"] for item in definitions}) or ["UNKNOWN"]
    categories = ("owner_authority", "writer_evidence", "cpython_expected", "runtime_observed", "evaluation_projection", "output_lineage", "admission")
    return [{"subject": subject, **{category: "UNKNOWN" for category in categories}, "status": "UNKNOWN", "evidence_refs": _evidence_ref("definition-census.json"), "blocker": "静态 census 未执行运行时或 admission"} for subject in subjects]


def _cycle_records(imports: list[dict[str, Any]]) -> dict[str, Any]:
    source_by_module = {path.removeprefix("src/").removesuffix(".py").replace("/", "."): path for path in SOURCE_PATHS}
    edges: list[dict[str, Any]] = []
    graph: dict[str, set[str]] = {}
    for item in imports:
        source = item["path"]
        matches = [path for module, path in source_by_module.items() if module in item["text"]]
        target = matches[0] if matches else "UNKNOWN"
        status = "STATIC_ONE_WAY" if target != "UNKNOWN" else "DYNAMIC_UNKNOWN"
        edge = {"from": source, "to": target, "status": status, "evidence_refs": _evidence_ref("import-census.json", item["line"])}
        if target == "UNKNOWN":
            edge["blocker"] = "文本命中无法解析为冻结 source module"
        else:
            graph.setdefault(source, set()).add(target)
        edges.append(edge)
    cycles: list[list[str]] = []
    for start in sorted(graph):
        stack: list[str] = []
        seen: set[str] = set()
        def visit(node: str) -> None:
            if node in stack:
                cycle = stack[stack.index(node):] + [node]
                if cycle not in cycles:
                    cycles.append(cycle)
                return
            if node in seen:
                return
            seen.add(node)
            stack.append(node)
            for target in sorted(graph.get(node, ())):
                visit(target)
            stack.pop()
        visit(start)
    cycle_nodes = {node for cycle in cycles for node in cycle}
    for edge in edges:
        if edge["from"] in cycle_nodes and edge["to"] in cycle_nodes:
            edge["status"] = "STATIC_CYCLE"
    if not edges:
        edges = [{"from": "UNKNOWN", "to": "UNKNOWN", "status": "DYNAMIC_UNKNOWN", "evidence_refs": _evidence_ref("import-census.json"), "blocker": "无静态 edge 可供 cycle 判定"}]
    return {"nodes": sorted(set(graph) | {target for targets in graph.values() for target in targets}) or ["UNKNOWN"], "edges": edges, "cycles": cycles, "records": edges, "status": "STATIC_GRAPH_WITH_DYNAMIC_UNKNOWN", "evidence_refs": _evidence_ref("import-census.json"), "blocker": "文本 census 无法证明运行时 import graph"}


def _facade_records(definitions: list[dict[str, Any]], imports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    public = [item for item in definitions if not item["name"].startswith("_")]
    records: list[dict[str, Any]] = []
    for item in public or [{"name": "UNKNOWN", "path": "UNKNOWN", "line": None}]:
        consumers = [ref["path"] for ref in imports if item["name"] in ref["text"]]
        records.append({"entry": item["name"], "decision": "UNKNOWN", "consumer_refs": consumers, "evidence_refs": _evidence_ref("definition-census.json", item.get("line")), "blocker": "未授权迁移且未证明旧公开入口等价"})
    return records


def _packet_binding(packet: Mapping[str, Any], *names: str) -> dict[str, Any]:
    for name in names:
        value = packet.get(name)
        if isinstance(value, Mapping):
            return dict(value)
    return {"status": "UNKNOWN"}


def _required_role_binding(
    packet: Mapping[str, Any], binding_name: str, role_name: str
) -> dict[str, Any]:
    role_bindings = packet.get("role_bindings")
    if not isinstance(role_bindings, Mapping):
        raise ValueError("packet 缺少显式 role_bindings")
    value = role_bindings.get(binding_name)
    if isinstance(value, str):
        identity = value.strip()
        if not identity or identity == "UNKNOWN":
            raise ValueError(f"packet role_bindings.{binding_name} 缺少有效 identity")
        return {"role": role_name, "identity": identity}
    if isinstance(value, Mapping):
        binding = dict(value)
        identity = binding.get("identity")
        if not isinstance(identity, str) or not identity.strip() or identity == "UNKNOWN":
            raise ValueError(f"packet role_bindings.{binding_name} 缺少有效 identity")
        binding.setdefault("role", role_name)
        return binding
    raise ValueError(f"packet 缺少显式 role_bindings.{binding_name}")


def _provenance(
    packet: Mapping[str, Any],
    *,
    run_id: str,
    evidence_root: str,
    source_sha256s: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    adapter = {
        "root": _packet_binding(packet, "root_adapter_binding"),
        "xiaoshuo": _packet_binding(packet, "adapter_binding", "xiaoshuo_adapter_binding"),
    }
    roles = {
        "planner": _required_role_binding(packet, "planner", "planner"),
        "executor": _required_role_binding(packet, "executor", "executor"),
        "Reviewer": _required_role_binding(packet, "independent_reviewer", "Reviewer"),
    }
    return {
        "predecessor": _packet_binding(packet, "predecessor", "predecessor_binding"),
        "owner_ruling": _packet_binding(packet, "owner_ruling", "owner_ruling_binding"),
        "correction": _packet_binding(packet, "correction", "correction_binding"),
        "design": _packet_binding(packet, "design", "design_binding") | {
            "revision": packet.get("design_revision", "UNKNOWN"),
            "sha256": packet.get("design_sha256", "UNKNOWN"),
        },
        "contract": _packet_binding(packet, "contract", "contract_binding") | {
            "sha256": packet.get("contract_sha256", "UNKNOWN"),
        },
        "adapter": adapter,
        "runner": _packet_binding(packet, "runner_binding"),
        "verifier": dict(packet.get("verifier_bindings", {})),
        "interpreter": _packet_binding(
            packet.get("execution_bindings", {}), "interpreter"
        ) if isinstance(packet.get("execution_bindings"), Mapping) else {"status": "UNKNOWN"},
        "planner": roles["planner"],
        "executor": roles["executor"],
        "Reviewer": roles["Reviewer"],
        "source_sha256s": dict(source_sha256s or packet.get("input_snapshot", {}).get("source_sha256s", {})),
        "artifact_contract": {
            "total_files": len(C0_ARTIFACTS),
            "checksum_files": len(CHECKSUM_ARTIFACTS),
            "paths": list(C0_ARTIFACTS),
        },
        "activity_status": "NOT_RUN",
        "unproven": list(REQUIRED_UNPROVEN),
        "candidate_run": {
            "run_id": run_id,
            "evidence_root": evidence_root,
            "lifecycle": packet.get("candidate_run", {}).get("lifecycle", "CANDIDATE_NOT_CREATED")
            if isinstance(packet.get("candidate_run"), Mapping) else "CANDIDATE_NOT_CREATED",
        },
        "correction_count": packet.get("correction_count", 2),
        "max_corrections": packet.get("max_corrections", 2),
    }


def build_ledger_entries(packet: Mapping[str, Any], correction_count: int, run_id: str | None = None, evidence_root: str | None = None) -> list[dict[str, Any]]:
    authorizations = packet["authorizations"]
    auth_hashes = {name: item["source_sha256"] for name, item in authorizations.items()}
    effective_run_id = run_id or "UNKNOWN"
    effective_evidence_root = evidence_root or "UNKNOWN"
    provenance = _provenance(packet, run_id=effective_run_id, evidence_root=effective_evidence_root)
    common = {
        "authorization_source_sha256s": auth_hashes,
        "contract_sha256": packet["contract_sha256"],
        "correction_count": packet.get("correction_count", 2),
        "max_corrections": packet.get("max_corrections", 2),
        "design_revision": packet["design_revision"],
        "design_sha256": packet["design_sha256"],
        "packet_sha256": packet["packet_sha256"],
        "schema_version": "governed-ledger-entry/v1",
        "stage_id": packet["stage_id"],
        "stage_type": packet.get("stage_type", "evaluation_only"),
        "run_id": effective_run_id,
        "evidence_root": effective_evidence_root,
        "correction_sha256": packet.get("correction_binding", {}).get("sha256", packet.get("correction_sha256", "UNKNOWN")),
        "authorization_source_path": packet.get("authorizations", {}).get("evaluation", {}).get("source_path", "UNKNOWN"),
        "predecessor": provenance["predecessor"],
        "owner_ruling": provenance["owner_ruling"],
        "correction": provenance["correction"],
        "design": provenance["design"],
        "contract": provenance["contract"],
        "adapter": provenance["adapter"],
        "runner": provenance["runner"],
        "verifier": provenance["verifier"],
        "interpreter": provenance["interpreter"],
        "planner": provenance["planner"],
        "executor": provenance["executor"],
        "Reviewer": provenance["Reviewer"],
        "source_sha256s": provenance["source_sha256s"],
        "artifact_contract": provenance["artifact_contract"],
        "artifact_bindings": dict(packet.get("artifact_bindings", {
            "checkpoint": {"path": "checkpoint.json", "sha256": "UNKNOWN"},
            "payload": {"path": "payload-manifest.json", "sha256": "UNKNOWN"},
            "result": {"path": "result.json", "sha256": "UNKNOWN"},
            "closure": {"path": "evidence-closure-manifest.json", "sha256": "UNKNOWN"},
            "checksum": {"path": "SHA256SUMS.txt", "sha256": "UNKNOWN"},
        })),
        "activity_status": provenance["activity_status"],
        "unproven": provenance["unproven"],
        "candidate_run": provenance["candidate_run"],
    }
    first = {
        **common,
        "entry_id": "c0-prepared",
        "entry_timestamp": "1970-01-01T00:00:00+00:00",
        "event": "PREPARED",
        "status": "PREPARED",
        "previous_entry_sha256": "GENESIS",
        "sequence": 1,
    }
    first["entry_sha256"] = hashlib.sha256(canonical_json_bytes(first)).hexdigest()
    second = {
        **common,
        "entry_id": "c0-finalized",
        "entry_timestamp": "1970-01-01T00:00:01+00:00",
        "event": "FINALIZED",
        "status": "FINALIZED",
        "previous_entry_sha256": first["entry_sha256"],
        "sequence": 2,
    }
    second["entry_sha256"] = hashlib.sha256(canonical_json_bytes(second)).hexdigest()
    return [first, second]


def render_c1_input_contract(
    blockers: Iterable[str],
    *,
    packet: Mapping[str, Any] | None = None,
    source_snapshot_sha256: str = "UNKNOWN",
) -> str:
    packet = packet or {}
    source_snapshot = packet.get("input_snapshot", {})
    snapshot_sha = source_snapshot.get("source_snapshot_sha256", source_snapshot_sha256)
    values = {
        "schema_version": "governed-c1-input-contract/v1",
        "stage_id": packet.get("stage_id", C0_STAGE_ID),
        "source_snapshot_sha256": snapshot_sha,
        "contract_owner_records": packet.get("contract_owner_records", [{"status": "UNKNOWN"}]),
        "conflict_records": packet.get("conflict_records", [{"status": "UNKNOWN"}]),
        "candidate_symbol_groups": packet.get("candidate_symbol_groups", [{"status": "UNKNOWN"}]),
        "candidate_files": packet.get("candidate_files", list(SOURCE_PATHS)),
        "consumer_migration_groups": packet.get("consumer_migration_groups", [{"status": "UNKNOWN"}]),
        "temporary_facades": packet.get("temporary_facades", [{"status": "UNKNOWN"}]),
        "facade_delete_checkpoints": packet.get("facade_delete_checkpoints", [{"status": "UNKNOWN"}]),
        "forbidden_files": packet.get("forbidden_files", ["AI_PROTOCOL.md", "assets/canon/", ".codebuddy/", ".git/"]),
        "blockers": list(blockers) or ["UNKNOWN"],
        "c1_authorized": False,
    }
    lines = ["NOT_AUTHORIZED", "# C1 Input Contract", ""]
    for key, value in values.items():
        lines.extend([f"## {key}", "```json", json.dumps(value, ensure_ascii=True, sort_keys=True), "```", ""])
    return "\n".join(lines)


REQUIRED_UNPROVEN = [
    "runtime_import_graph",
    "runtime_facade_equivalence",
    "current_test_status",
    "quality",
    "business_effect",
    "production_readiness",
]


def build_result(packet: Mapping[str, Any], payload_sha256: str) -> dict[str, Any]:
    acceptance_matrix = list(packet.get("acceptance_matrix", C0_ACCEPTANCE_MATRIX))
    return {
        "status": "EVALUATION_READY",
        "scope": "STATIC_ONLY",
        "conclusion": packet["result_contract"]["conclusion"],
        "determinism": packet["result_contract"]["determinism"],
        "limitations": {"test_authorized": False},
        "manifest_refs": {"payload_manifest": {"path": "payload-manifest.json", "sha256": payload_sha256}},
        "payload_manifest_sha256": payload_sha256,
        "acceptance_matrix": acceptance_matrix,
        "required_unproven": list(REQUIRED_UNPROVEN),
        "unproven": list(REQUIRED_UNPROVEN),
        "provenance": _provenance(packet, run_id="UNKNOWN", evidence_root="UNKNOWN"),
    }


def build_receipt(
    *,
    packet: Mapping[str, Any],
    packet_path: Path,
    evidence_root: Path,
    frozen_source_sha256s: Mapping[str, str],
    checkpoint_sha256: str,
    payload_sha256: str,
    ledger_sha256: str,
    result_sha256: str,
    closure_sha256: str = "UNKNOWN",
    host_path: Path,
    interpreter_path: Path,
) -> dict[str, Any]:
    checked_packet = checked_resolve(packet_path, LAB_ROOT)
    packet_relative = checked_packet.relative_to(checked_resolve(LAB_ROOT)).as_posix()
    provenance = _provenance(
        packet,
        run_id=evidence_root.name,
        evidence_root=str(evidence_root),
        source_sha256s=frozen_source_sha256s,
    )
    artifact_relations = {
        "checkpoint": {"path": "checkpoint.json", "sha256": checkpoint_sha256},
        "payload_manifest": {"path": "payload-manifest.json", "sha256": payload_sha256},
        "result": {"path": "result.json", "sha256": result_sha256},
        "stage_ledger": {"path": "stage-ledger.jsonl", "sha256": ledger_sha256},
        "evidence_closure": {"path": "evidence-closure-manifest.json", "sha256": closure_sha256},
        "receipt": {"path": "receipt.json", "sha256": "SELF_HASH_EXCLUDED_FROM_RECEIPT"},
        "checksums": {
            "path": "SHA256SUMS.txt",
            "artifacts": list(CHECKSUM_ARTIFACTS),
            "self_excluded": True,
        },
    }
    return {
        "checkpoint_path": "checkpoint.json",
        "checkpoint_sha256": checkpoint_sha256,
        "packet_binding": {
            "path": packet_relative,
            "file_sha256": sha256_file(checked_packet),
            "internal_sha256": packet["packet_sha256"],
        },
        "stage_id": packet["stage_id"],
        "stage_type": packet.get("stage_type", "evaluation_only"),
        "run_id": evidence_root.name,
        "evidence_root": str(evidence_root),
        "design_sha256": packet["design_sha256"],
        "contract_sha256": packet["contract_sha256"],
        "correction_sha256": packet.get("correction_binding", {}).get("sha256", packet.get("correction_sha256", "UNKNOWN")),
        "authorization_source_sha256s": {name: item["source_sha256"] for name, item in packet["authorizations"].items()},
        "forbidden_activities": list(packet.get("forbidden_activities", [])),
        "root_adapter_binding": dict(packet["root_adapter_binding"]),
        "xiaoshuo_adapter_binding": dict(packet["adapter_binding"]),
        "core_binding": dict(packet["core_binding"]),
        "runner_binding": dict(packet["runner_binding"]),
        "verifier_bindings": dict(packet["verifier_bindings"]),
        "frozen_source_sha256s": dict(frozen_source_sha256s),
        "host_path": str(host_path),
        "host_sha256": sha256_file(host_path),
        "interpreter_path": str(interpreter_path),
        "interpreter_sha256": sha256_file(interpreter_path),
        "interpreter_binding": dict(packet["execution_bindings"]["interpreter"]),
        "execution_identity": {
            "executor_role": provenance["executor"]["identity"],
            "stage_id": packet["stage_id"],
            "run_id": evidence_root.name,
            "host_name": platform.node(),
        },
        "result_path": "result.json",
        "result_sha256": result_sha256,
        "payload_manifest_path": "payload-manifest.json",
        "payload_manifest_sha256": payload_sha256,
        "ledger_path": "stage-ledger.jsonl",
        "ledger_sha256": ledger_sha256,
        "closure_path": "evidence-closure-manifest.json",
        "closure_sha256": closure_sha256,
        "artifact_relations": artifact_relations,
        "provenance": provenance,
        **provenance,
    }


def list_artifacts(evidence_root: Path) -> set[str]:
    return enumerate_files_checked(evidence_root)


def _payload_entry(
    evidence_root: Path,
    relative: str,
    *,
    role: str,
    content_type: str,
    source_snapshot_ref: str,
) -> dict[str, Any]:
    payload_relative = f"frozen-source/{relative}" if relative in SOURCE_PATHS else relative
    target = evidence_root / payload_relative
    return {
        "path": payload_relative,
        "role": role,
        "content_type": content_type,
        "bytes": target.stat().st_size,
        "sha256": sha256_file(target),
        "source_snapshot_ref": source_snapshot_ref,
    }


def write_fixture_census(
    project_root: Path,
    evidence_root: Path,
    packet: Mapping[str, Any],
    packet_path: Path | None = None,
    preflight_result: Mapping[str, Any] | None = None,
) -> None:
    expected_sources = packet["input_snapshot"]["source_sha256s"]
    preflight = (
        dict(preflight_result)
        if preflight_result is not None
        else dry_preflight(project_root, evidence_root, expected_sources)
    )
    create_evidence_root(evidence_root)
    packet_relative = checked_resolve(packet_path or Path(__file__), LAB_ROOT).relative_to(checked_resolve(LAB_ROOT)).as_posix()
    provenance = _provenance(
        packet,
        run_id=evidence_root.name,
        evidence_root=str(evidence_root),
        source_sha256s=expected_sources,
    )
    checkpoint = {
        "stage_id": packet["stage_id"],
        "stage_type": packet.get("stage_type", "evaluation_only"),
        "run_id": evidence_root.name,
        "evidence_root": str(evidence_root),
        "packet_binding": {"path": packet_relative, "file_sha256": sha256_file(packet_path) if packet_path else "UNKNOWN", "internal_sha256": packet["packet_sha256"]},
        "design_sha256": packet["design_sha256"],
        "contract_sha256": packet["contract_sha256"],
        "correction_sha256": packet.get("correction_binding", {}).get("sha256", packet.get("correction_sha256", "UNKNOWN")),
        "authorization_source_sha256s": {name: item["source_sha256"] for name, item in packet["authorizations"].items()},
        "root_adapter_binding": dict(packet.get("root_adapter_binding", {})),
        "xiaoshuo_adapter_binding": dict(packet.get("adapter_binding", {})),
        "core_binding": dict(packet.get("core_binding", {})),
        "runner_binding": dict(packet.get("runner_binding", {})),
        "interpreter_binding": dict(packet.get("execution_bindings", {}).get("interpreter", {})),
        "verifier_bindings": dict(packet.get("verifier_bindings", {})),
        "source_sha256s": dict(expected_sources),
        "artifact_contract": list(C0_ARTIFACTS),
        "correction_count": packet.get("correction_count", 2),
        "max_corrections": packet.get("max_corrections", 2),
        "forbidden_activities": list(packet.get("forbidden_activities", [])),
        "activities_not_run": list(packet.get("forbidden_activities", [])),
        "unproven": list(REQUIRED_UNPROVEN),
        "candidate_run": provenance["candidate_run"],
        "provenance": provenance,
        **provenance,
        "preflight": preflight,
    }
    _write_json(
        evidence_root,
        "checkpoint.json",
        checkpoint,
    )
    frozen = freeze_sources(project_root, evidence_root, expected_sources)
    inventory = _source_inventory(evidence_root, frozen)
    definitions = _definition_records(evidence_root)
    imports = _text_census(project_root, IMPORT_RE, "DIRECT_OR_RELATIVE_TEXT")
    dynamic = _text_census(project_root, DYNAMIC_RE, "DYNAMIC_MARKER")
    symbol_owners = _symbol_owner_records(definitions, imports)
    importer_matrix = _importer_matrix_records(imports)
    hash_domains = _hash_domain_records(evidence_root)
    lifecycles = _lifecycle_records(definitions)
    cycles = _cycle_records(imports)
    facades = _facade_records(definitions, imports)
    _write_json(evidence_root, "source-inventory.json", {"records": inventory})
    _write_json(evidence_root, "definition-census.json", {"records": definitions})
    _write_json(evidence_root, "import-census.json", {"records": imports})
    _write_json(evidence_root, "dynamic-marker-census.json", {"records": dynamic, "unresolved": "UNKNOWN"})
    _write_json(evidence_root, "symbol-owner-map.json", {"records": symbol_owners, "status": "STATIC_CANDIDATES_WITH_UNKNOWN"})
    _write_json(evidence_root, "importer-matrix.json", {"records": importer_matrix, "status": "STATIC_TEXT_WITH_UNKNOWN"})
    _write_json(evidence_root, "hash-domain-matrix.json", {"records": hash_domains, "status": "STATIC_CLUES_WITH_UNKNOWN"})
    _write_json(evidence_root, "lifecycle-matrix.json", {"records": lifecycles, "status": "UNKNOWN_RUNTIME_FIELDS"})
    _write_json(evidence_root, "cycle-census.json", cycles)
    _write_json(evidence_root, "facade-decision.json", {"decisions": facades, "status": "UNKNOWN_UNTIL_MIGRATION_AUTHORIZED"})
    source_snapshot_sha256 = hashlib.sha256(canonical_json_bytes(expected_sources)).hexdigest()
    (evidence_root / "c1-input-contract.md").write_text(
        render_c1_input_contract(
            ["UNKNOWN static importer migration evidence", "C1 implementation and tests are not authorized"],
            packet=packet,
            source_snapshot_sha256=source_snapshot_sha256,
        ),
        encoding="utf-8",
        newline="\n",
    )
    payload_paths = (*SOURCE_PATHS, "source-inventory.json", "definition-census.json", "import-census.json", "dynamic-marker-census.json", "symbol-owner-map.json", "importer-matrix.json", "hash-domain-matrix.json", "lifecycle-matrix.json", "cycle-census.json", "facade-decision.json", "c1-input-contract.md")
    payload_roles = {
        "source-inventory.json": ("source_inventory", "application/json"),
        "definition-census.json": ("definition_census", "application/json"),
        "import-census.json": ("import_census", "application/json"),
        "dynamic-marker-census.json": ("dynamic_marker_census", "application/json"),
        "symbol-owner-map.json": ("symbol_owner_map", "application/json"),
        "importer-matrix.json": ("importer_matrix", "application/json"),
        "hash-domain-matrix.json": ("hash_domain_matrix", "application/json"),
        "lifecycle-matrix.json": ("lifecycle_matrix", "application/json"),
        "cycle-census.json": ("cycle_census", "application/json"),
        "facade-decision.json": ("facade_decision", "application/json"),
        "c1-input-contract.md": ("c1_input_contract", "text/markdown"),
    }
    payload = {
        "artifacts": [
            _payload_entry(
                evidence_root,
                path,
                role="frozen_source" if path in SOURCE_PATHS else payload_roles[path][0],
                content_type="text/x-python" if path in SOURCE_PATHS else payload_roles[path][1],
                source_snapshot_ref=(f"source-snapshot:{path}" if path in SOURCE_PATHS else "derived-from:frozen-source"),
            )
            for path in payload_paths
        ]
    }
    _write_json(evidence_root, "payload-manifest.json", payload)
    payload_sha = sha256_file(evidence_root / "payload-manifest.json")
    result = build_result(packet, payload_sha)
    _write_json(evidence_root, "result.json", result)
    entries = build_ledger_entries(packet, packet.get("correction_count", 0), evidence_root.name, str(evidence_root))
    (evidence_root / "stage-ledger.jsonl").write_bytes(b"".join(canonical_json_bytes(entry) + b"\n" for entry in entries))
    ledger_sha = sha256_file(evidence_root / "stage-ledger.jsonl")
    closure = {
        "expected_conclusion": result["conclusion"],
        "expected_determinism": result["determinism"],
        "expected_limitations": result["limitations"],
        "expected_manifest_refs": result["manifest_refs"],
        "payload_manifest_path": "payload-manifest.json",
        "pre_receipt_artifacts": list(PRE_RECEIPT_ARTIFACTS),
        "receipt_path": "receipt.json",
        "result_path": "result.json",
        "schema_version": "governed-evidence-closure/v1",
        "sha256sums_path": "SHA256SUMS.txt",
        "checksum_artifacts": list(CHECKSUM_ARTIFACTS),
        "unhashed_artifacts": list(UNHASHED_ARTIFACTS),
        "provenance": _provenance(packet, run_id=evidence_root.name, evidence_root=str(evidence_root), source_sha256s=frozen),
    }
    _write_json(evidence_root, "evidence-closure-manifest.json", closure)
    closure_sha = sha256_file(evidence_root / "evidence-closure-manifest.json")
    receipt = build_receipt(
        packet=packet,
        packet_path=packet_path or Path(__file__),
        evidence_root=evidence_root,
        frozen_source_sha256s=frozen,
        checkpoint_sha256=sha256_file(evidence_root / "checkpoint.json"),
        payload_sha256=payload_sha,
        ledger_sha256=ledger_sha,
        result_sha256=sha256_file(evidence_root / "result.json"),
        closure_sha256=closure_sha,
        host_path=Path(__file__),
        interpreter_path=Path(sys.executable),
    )
    _write_json(evidence_root, "receipt.json", receipt)
    sums = "".join(
        f"{sha256_file(evidence_root / relative)}  {relative}\n" for relative in sorted(CHECKSUM_ARTIFACTS)
    )
    (evidence_root / "SHA256SUMS.txt").write_text(sums, encoding="ascii", newline="\n")
    assert_artifact_contract(list_artifacts(evidence_root))


def main() -> int:
    parser = argparse.ArgumentParser(description="静态生成 C0 responsibility census evidence")
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args()
    packet = strict_json_load_file(args.packet)
    if not isinstance(packet, dict):
        raise ValueError("packet 必须是 object")
    try:
        preflight = dry_preflight(
            args.project_root,
            args.evidence_root,
            packet["input_snapshot"]["source_sha256s"],
        )
    except PermissionError:
        print("[BLOCKED] D_STAGE_ROOT_CREATE_PERMISSION_DENIED")
        return 2
    write_fixture_census(
        args.project_root,
        args.evidence_root,
        packet,
        args.packet,
        preflight_result=preflight,
    )
    print("[OK] C0 static census evidence 写入完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
