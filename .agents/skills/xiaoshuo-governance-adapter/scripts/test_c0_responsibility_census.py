from __future__ import annotations

import ast
import hashlib
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent
RUNNER_PATH = SCRIPTS_DIR / "c0_responsibility_census.py"
TEST_ROOT = Path(
    os.environ.get(
        "YEYU_C0_CENSUS_TEST_ROOT",
        r"D:\tmp\yeyu-ai-a3\c0-runner-tests",
    )
)


def load_runner() -> object:
    if not RUNNER_PATH.is_file():
        raise AssertionError("缺少稳定 C0 runner")
    spec = importlib.util.spec_from_file_location("c0_responsibility_census", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("无法加载稳定 C0 runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class C0ResponsibilityCensusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        TEST_ROOT.mkdir(parents=True, exist_ok=True)

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(dir=TEST_ROOT)
        self.root = Path(self.temp_dir.name)
        self.project_root = self.root / "project"
        self.evidence_root = self.root / "evaluation-responsibility-split-c0-census" / "fixture-run"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_sources(self, runner: object) -> dict[str, str]:
        expected: dict[str, str] = {}
        for index, relative in enumerate(runner.SOURCE_PATHS, 1):
            path = self.project_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            content = f"VALUE_{index} = {index}\n"
            if relative.endswith("evaluation_contracts.py"):
                content += "def canonical_contract(value):\n    return value\n"
            path.write_text(content, encoding="utf-8")
            expected[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        return expected

    def write_frozen_sources(self, runner: object, content: bytes | str) -> None:
        frozen_root = self.evidence_root / "frozen-source"
        for index, relative in enumerate(runner.SOURCE_PATHS, 1):
            path = frozen_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            value = content if index == 1 else "VALUE = 1\n"
            path.write_bytes(value if isinstance(value, bytes) else value.encode("utf-8"))

    def load_configured_runner(self) -> object:
        runner = load_runner()
        runner.EVIDENCE_CONTAINER_ROOT = self.root
        return runner

    def make_packet(self, expected_sources: dict[str, str]) -> dict[str, object]:
        return {
            "stage_id": "fixture-stage",
            "packet_sha256": "a" * 64,
            "design_sha256": "b" * 64,
            "contract_sha256": "c" * 64,
            "design_revision": "c0-fixture",
            "authorizations": {
                "implementation": {"source_sha256": "d" * 64},
                "evaluation": {"source_sha256": "d" * 64},
                "test": {"source_sha256": "d" * 64},
            },
            "input_snapshot": {"source_sha256s": expected_sources},
            "result_contract": {
                "conclusion": "RESPONSIBILITY_CENSUS_ONLY",
                "determinism": "STATIC_SOURCE_BYTES_AND_RULESET_IDENTICAL_YIELDS_IDENTICAL_CENSUS",
            },
            "root_adapter_binding": {"path": "root-adapter", "sha256": "e" * 64},
            "adapter_binding": {"path": "xiaoshuo-adapter", "sha256": "f" * 64},
            "core_binding": {"path": "core", "sha256": "1" * 64},
            "runner_binding": {"path": "runner", "sha256": "2" * 64},
            "verifier_bindings": {"packet": "3" * 64},
            "execution_bindings": {"interpreter": {"path": "interpreter", "sha256": "4" * 64}},
            "role_bindings": {
                "executor": "Luna",
                "planner": "Luna Max",
                "independent_reviewer": "GLM 5.2",
            },
        }

    def test_dry_preflight_does_not_create_evidence_root(self) -> None:
        runner = self.load_configured_runner()
        expected_sources = self.write_sources(runner)
        result = runner.dry_preflight(self.project_root, self.evidence_root, expected_sources)
        self.assertEqual(result["source_sha256s"], expected_sources)
        self.assertTrue(self.evidence_root.parent.is_dir())
        self.assertFalse(self.evidence_root.exists())

    def test_stage_root_must_be_approved_and_run_creation_is_separate(self) -> None:
        runner = self.load_configured_runner()
        expected_sources = self.write_sources(runner)
        self.assertFalse(self.evidence_root.parent.exists())
        runner.dry_preflight(self.project_root, self.evidence_root, expected_sources)
        self.assertTrue(self.evidence_root.parent.is_dir())
        self.assertFalse(self.evidence_root.exists())
        runner.create_evidence_root(self.evidence_root)
        self.assertTrue(self.evidence_root.is_dir())
        with self.assertRaisesRegex(ValueError, "已存在"):
            runner.create_evidence_root(self.evidence_root)

    def test_canonical_json_is_sorted_ascii_and_compact(self) -> None:
        runner = self.load_configured_runner()
        self.assertEqual(runner.canonical_json_bytes({"z": "\u4e2d", "a": 1}), b'{"a":1,"z":"\\u4e2d"}')

    def test_second_source_read_rejects_drift_after_freeze(self) -> None:
        runner = self.load_configured_runner()
        expected_sources = self.write_sources(runner)
        self.evidence_root.mkdir(parents=True)
        source = self.project_root / runner.SOURCE_PATHS[0]

        def drift() -> None:
            source.write_text("DRIFT = True\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "source.*drift"):
            runner.freeze_sources(self.project_root, self.evidence_root, expected_sources, drift)

    def test_source_path_rejects_reparse_point(self) -> None:
        runner = self.load_configured_runner()
        source = self.project_root / runner.SOURCE_PATHS[0]
        target = self.root / "source-target.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("VALUE = 1\n", encoding="utf-8")
        source.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.symlink(target, source)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"受控 Windows 环境无法创建 symlink，未伪称覆盖: {exc}")
        with self.assertRaisesRegex(ValueError, "reparse|symlink"):
            runner._source_path(self.project_root, runner.SOURCE_PATHS[0])

    def test_python_file_scan_rejects_reparse_scan_root(self) -> None:
        runner = self.load_configured_runner()
        scan_target = self.root / "scan-target"
        scan_target.mkdir(parents=True, exist_ok=True)
        (scan_target / "example.py").write_text("VALUE = 1\n", encoding="utf-8")
        scan_root = self.project_root / "src" / "xiaoshuo"
        scan_root.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.symlink(scan_target, scan_root, target_is_directory=True)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"受控 Windows 环境无法创建 symlink，未伪称覆盖: {exc}")
        with self.assertRaisesRegex(ValueError, "reparse|symlink"):
            runner._python_files(self.project_root)

    def test_exact_32_artifact_contract_rejects_duplicate_and_missing_paths(self) -> None:
        runner = self.load_configured_runner()
        self.assertEqual(len(runner.C0_ARTIFACTS), 32)
        runner.assert_artifact_contract(runner.C0_ARTIFACTS)
        with self.assertRaisesRegex(ValueError, "重复"):
            runner.assert_artifact_contract((*runner.C0_ARTIFACTS, runner.C0_ARTIFACTS[0]))
        with self.assertRaisesRegex(ValueError, "不完整"):
            runner.assert_artifact_contract(runner.C0_ARTIFACTS[:-1])

    def test_ledger_entries_are_ordered_and_packet_bound(self) -> None:
        runner = self.load_configured_runner()
        packet = self.make_packet({})
        entries = runner.build_ledger_entries(packet, 0, "fixture-run", "fixture-evidence")
        self.assertEqual([entry["sequence"] for entry in entries], [1, 2])
        self.assertEqual(entries[1]["previous_entry_sha256"], entries[0]["entry_sha256"])
        self.assertEqual(entries[1]["packet_sha256"], packet["packet_sha256"])
        for entry in entries:
            self.assertEqual(entry["run_id"], "fixture-run")
            self.assertEqual(entry["evidence_root"], "fixture-evidence")
            self.assertIn("correction_sha256", entry)
            self.assertIn("authorization_source_sha256s", entry)

    def test_receipt_binds_packet_adapters_tools_and_artifacts(self) -> None:
        runner = self.load_configured_runner()
        packet = self.make_packet({})
        receipt = runner.build_receipt(
            packet=packet,
            packet_path=RUNNER_PATH,
            evidence_root=self.evidence_root,
            frozen_source_sha256s={"src/example.py": "a" * 64},
            checkpoint_sha256="b" * 64,
            payload_sha256="d" * 64,
            ledger_sha256="e" * 64,
            result_sha256="c" * 64,
            host_path=RUNNER_PATH,
            interpreter_path=Path(sys.executable),
        )
        for field in (
            "packet_binding", "root_adapter_binding", "xiaoshuo_adapter_binding",
            "core_binding", "runner_binding", "verifier_bindings", "execution_identity",
            "artifact_relations", "host_path", "host_sha256", "interpreter_path", "interpreter_sha256",
        ):
            self.assertIn(field, receipt)
        self.assertEqual(receipt["checkpoint_path"], "checkpoint.json")
        self.assertEqual(receipt["result_path"], "result.json")
        self.assertEqual(receipt["packet_binding"]["internal_sha256"], packet["packet_sha256"])

    def test_cli_contract_has_only_packet_project_and_evidence_arguments(self) -> None:
        source = RUNNER_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(RUNNER_PATH))
        arguments = [
            node.args[0].value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and node.args[0].value.startswith("--")
        ]
        self.assertEqual(arguments, ["--packet", "--project-root", "--evidence-root"])
        self.assertNotIn("--" + "run-id", source)
        self.assertIn("run_id=evidence_root.name", source)

    def test_receipt_and_provenance_use_packet_role_bindings(self) -> None:
        runner = self.load_configured_runner()
        packet = self.make_packet({})
        provenance = runner._provenance(packet, run_id="fixture-run", evidence_root="fixture-evidence")
        self.assertEqual(provenance["executor"]["identity"], "Luna")
        self.assertEqual(provenance["planner"]["identity"], "Luna Max")
        self.assertEqual(provenance["Reviewer"]["identity"], "GLM 5.2")
        receipt = runner.build_receipt(
            packet=packet,
            packet_path=RUNNER_PATH,
            evidence_root=self.evidence_root,
            frozen_source_sha256s={"src/example.py": "a" * 64},
            checkpoint_sha256="b" * 64,
            payload_sha256="c" * 64,
            ledger_sha256="d" * 64,
            result_sha256="e" * 64,
            host_path=RUNNER_PATH,
            interpreter_path=Path(sys.executable),
        )
        self.assertEqual(receipt["execution_identity"]["executor_role"], "Luna")
        self.assertNotIn("executor" + "8", repr(receipt))

    def test_missing_packet_role_bindings_fail_closed(self) -> None:
        runner = self.load_configured_runner()
        packet = self.make_packet({})
        for binding_name in ("executor", "planner", "independent_reviewer"):
            broken = {**packet, "role_bindings": dict(packet["role_bindings"])}
            del broken["role_bindings"][binding_name]
            with self.subTest(binding_name=binding_name):
                with self.assertRaisesRegex(ValueError, f"role_bindings\\.{binding_name}"):
                    runner.build_result(broken, "a" * 64)

    def test_result_is_static_only_and_evaluation_ready(self) -> None:
        runner = self.load_configured_runner()
        result = runner.build_result(
            self.make_packet({"src/example.py": "a" * 64}),
            "b" * 64,
        )
        self.assertEqual(result["status"], "EVALUATION_READY")
        self.assertEqual(result["scope"], "STATIC_ONLY")
        self.assertEqual(result["conclusion"], "RESPONSIBILITY_CENSUS_ONLY")
        self.assertFalse(result["limitations"]["test_authorized"])
        self.assertIn("runtime_import_graph", result["required_unproven"])

    def test_checksum_closure_writes_exact_declared_contract(self) -> None:
        runner = self.load_configured_runner()
        expected_sources = self.write_sources(runner)
        packet = self.make_packet(expected_sources)
        runner.write_fixture_census(self.project_root, self.evidence_root, packet)
        self.assertEqual(runner.list_artifacts(self.evidence_root), set(runner.C0_ARTIFACTS))
        sums = (self.evidence_root / "SHA256SUMS.txt").read_text(encoding="ascii").splitlines()
        self.assertEqual(len(sums), len(runner.CHECKSUM_ARTIFACTS))
        self.assertTrue(all("  " in line for line in sums))

    def test_static_matrices_are_object_level_and_unknowns_are_explained(self) -> None:
        runner = self.load_configured_runner()
        expected_sources = self.write_sources(runner)
        packet = self.make_packet(expected_sources)
        runner.write_fixture_census(self.project_root, self.evidence_root, packet)
        for name in ("symbol-owner-map.json", "importer-matrix.json", "hash-domain-matrix.json", "lifecycle-matrix.json", "cycle-census.json", "facade-decision.json"):
            payload = runner.strict_json_load_file(self.evidence_root / name)
            records = payload.get("records", payload.get("decisions"))
            self.assertTrue(records, name)
            for record in records:
                self.assertTrue(record.get("evidence_refs"), name)
                if "UNKNOWN" in str(record.values()):
                    self.assertTrue(record.get("blocker"), name)

    def test_checkpoint_contains_complete_run_provenance(self) -> None:
        runner = self.load_configured_runner()
        expected_sources = self.write_sources(runner)
        packet = self.make_packet(expected_sources)
        runner.write_fixture_census(self.project_root, self.evidence_root, packet)
        checkpoint = runner.strict_json_load_file(self.evidence_root / "checkpoint.json")
        for field in ("stage_id", "stage_type", "run_id", "evidence_root", "packet_binding", "design_sha256", "contract_sha256", "correction_sha256", "authorization_source_sha256s", "forbidden_activities"):
            self.assertIn(field, checkpoint)

    def test_c1_input_contract_starts_not_authorized(self) -> None:
        runner = self.load_configured_runner()
        contract = runner.render_c1_input_contract(["UNKNOWN importer"])
        self.assertTrue(contract.startswith("NOT_AUTHORIZED\n"))
        for field in (
            "schema_version", "stage_id", "source_snapshot_sha256", "contract_owner_records",
            "conflict_records", "candidate_symbol_groups", "candidate_files",
            "consumer_migration_groups", "temporary_facades", "facade_delete_checkpoints",
            "forbidden_files", "blockers", "c1_authorized",
        ):
            self.assertIn(field, contract)
        self.assertIn("false", contract)

    def test_ast_definition_census_is_top_level_and_tracks_final_duplicates(self) -> None:
        runner = self.load_configured_runner()
        self.write_frozen_sources(
            runner,
            """
from typing import Final
VALUE = 1
ANNOTATED: Final[int] = 2
PLAIN: int = 3
UNKNOWN_ANNOTATION: DoesNotExist = 4
class TopLevel: pass
def regular():
    class Nested: pass
    def nested_function(): pass
async def asynchronous(): pass
DUPLICATE = 1
DUPLICATE = 2
""",
        )
        records = runner._definition_records(self.evidence_root)
        records = [record for record in records if record["path"] == runner.SOURCE_PATHS[0] and "status" not in record]
        names = [record["name"] for record in records]
        self.assertIn("TopLevel", names)
        self.assertIn("regular", names)
        self.assertIn("asynchronous", names)
        self.assertNotIn("Nested", names)
        self.assertNotIn("nested_function", names)
        final_record = next(record for record in records if record["name"] == "ANNOTATED")
        self.assertEqual(final_record["is_final"], True)
        self.assertEqual(next(record for record in records if record["name"] == "PLAIN")["is_final"], False)
        duplicates = [record for record in records if record["name"] == "DUPLICATE"]
        self.assertEqual([record["definition_order"] for record in duplicates], [11, 12])
        self.assertEqual([record["static_active_candidate"] for record in duplicates], [False, True])
        self.assertEqual(next(record for record in records if record["name"] == "UNKNOWN_ANNOTATION")["is_final"], False)

    def test_ast_decode_and_syntax_fail_closed(self) -> None:
        runner = self.load_configured_runner()
        self.write_frozen_sources(runner, b"\xff\xfe")
        records = runner._definition_records(self.evidence_root)
        unreadable = next(record for record in records if record["path"] == runner.SOURCE_PATHS[0])
        self.assertEqual(unreadable["status"], "UNREADABLE_UTF8")
        self.write_frozen_sources(runner, "def broken(:\n")
        records = runner._definition_records(self.evidence_root)
        invalid = next(record for record in records if record["path"] == runner.SOURCE_PATHS[0])
        self.assertEqual(invalid["status"], "AST_PARSE_ERROR")

    def test_result_payload_and_receipt_provenance_contract(self) -> None:
        runner = self.load_configured_runner()
        packet = self.make_packet({})
        result = runner.build_result(packet, "b" * 64)
        self.assertEqual(result["acceptance_matrix"], list(runner.C0_ACCEPTANCE_MATRIX))
        self.assertFalse(result["limitations"]["test_authorized"])
        receipt = runner.build_receipt(
            packet=packet,
            packet_path=RUNNER_PATH,
            evidence_root=self.evidence_root,
            frozen_source_sha256s={path: "a" * 64 for path in runner.SOURCE_PATHS},
            checkpoint_sha256="b" * 64,
            payload_sha256="c" * 64,
            ledger_sha256="d" * 64,
            result_sha256="e" * 64,
            closure_sha256="f" * 64,
            host_path=RUNNER_PATH,
            interpreter_path=Path(sys.executable),
        )
        for field in (
            "predecessor", "owner_ruling", "correction", "design", "contract", "adapter",
            "runner", "verifier", "interpreter", "planner", "executor", "Reviewer",
            "source_sha256s", "artifact_contract", "activity_status", "unproven", "candidate_run",
        ):
            self.assertIn(field, receipt)
        self.assertEqual(receipt["candidate_run"]["lifecycle"], "CANDIDATE_NOT_CREATED")
        self.assertEqual(receipt["max_corrections"], 2)
        for entry in runner.build_ledger_entries(packet, 2, "fixture-run", "fixture-evidence"):
            self.assertEqual(entry["correction_count"], 2)
            self.assertEqual(entry["max_corrections"], 2)
            self.assertIn("provenance", entry)

    def test_payload_manifest_entry_shape_is_declared(self) -> None:
        runner = self.load_configured_runner()
        expected_sources = self.write_sources(runner)
        packet = self.make_packet(expected_sources)
        runner.write_fixture_census(self.project_root, self.evidence_root, packet)
        manifest = runner.strict_json_load_file(self.evidence_root / "payload-manifest.json")
        for entry in manifest["artifacts"]:
            for field in ("role", "content_type", "bytes", "source_snapshot_ref"):
                self.assertIn(field, entry)

    def test_runner_has_no_xiaoshuo_business_import(self) -> None:
        runner = load_runner()
        source = RUNNER_PATH.read_text(encoding="utf-8")
        self.assertNotIn("import xiaoshuo", source)
        self.assertNotIn("from xiaoshuo", source)
        self.assertEqual(runner.__name__, "c0_responsibility_census")

    def test_main_maps_only_permission_error_to_structured_blocked(self) -> None:
        source = RUNNER_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(RUNNER_PATH))
        handlers = [node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)]
        self.assertTrue(any(getattr(handler.type, "id", None) == "PermissionError" for handler in handlers))
        self.assertIn("[BLOCKED] D_STAGE_ROOT_CREATE_PERMISSION_DENIED", source)

    def test_permission_handler_scopes_only_dry_preflight(self) -> None:
        source = RUNNER_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(RUNNER_PATH))
        main_node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")

        def called_names(node: ast.AST) -> set[str]:
            return {
                call.func.id
                for call in ast.walk(node)
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            }

        guarded = next(node for node in main_node.body if isinstance(node, ast.Try))
        self.assertIn("dry_preflight", called_names(guarded))
        self.assertNotIn("write_fixture_census", called_names(guarded))
        self.assertIn("write_fixture_census", called_names(main_node))


if __name__ == "__main__":
    unittest.main()
