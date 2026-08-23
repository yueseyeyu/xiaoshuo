# -*- coding: utf-8 -*-
"""Context-bound pipeline node and runner contracts."""
from __future__ import annotations

import csv
import io
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from xiaoshuo.infra.logging_config import get_logger
from xiaoshuo.infra.pipeline_state import mark_error, write_stage
from xiaoshuo.pipeline.provenance import (
    ArtifactRef,
    BATCH_DIGEST_MISMATCH,
    BOM_FORBIDDEN,
    CHECKPOINT_CAPABILITY_UNAVAILABLE,
    ExecutionContext,
    INPUT_VALIDATION_FAILED,
    OUTPUT_VALIDATION_FAILED,
    PARENT_MISSING,
    PREREQUISITE_VALIDATION_FAILED,
    ProvenanceError,
    PATH_ESCAPE,
    execution_root,
    get_execution_context,
    make_artifact_ref,
    _validate_content_bytes,
    _validate_relative_path,
    _validate_root_path,
)


logger = get_logger("pipeline.base")

try:
    from xiaoshuo.pipeline.checkpoint import is_done, mark_done
    _CHECKPOINT_AVAILABLE = True
except ImportError:
    _CHECKPOINT_AVAILABLE = False


class PipelineNode(ABC):
    name: str = ""
    stage_info: tuple[int, int, str] = (0, 0, "")
    input_schema: dict[str, dict] | None = None
    output_schema: dict[str, dict] | None = None

    @abstractmethod
    def run(self, genre: str = "", **kwargs) -> bool:
        """Execute a node only after the runner has supplied an explicit context."""
        raise NotImplementedError

    def check_prerequisites(self, genre: str = "", **kwargs) -> bool:
        return True

    def get_outputs(self, genre: str = "", **kwargs) -> list[Path]:
        return []

    def validate_inputs(
        self,
        genre: str = "",
        *,
        context: ExecutionContext | None = None,
    ) -> list[str]:
        return _validate_schema(self.input_schema, genre, "input", context=context)

    def validate_outputs(
        self,
        genre: str = "",
        *,
        context: ExecutionContext | None = None,
    ) -> list[str]:
        return _validate_schema(self.output_schema, genre, "output", context=context)

    def skip_if_done(
        self,
        genre: str = "",
        *,
        context: ExecutionContext | None = None,
    ) -> bool:
        if not _CHECKPOINT_AVAILABLE:
            raise ProvenanceError(
                CHECKPOINT_CAPABILITY_UNAVAILABLE,
                "checkpoint capability is unavailable",
            )
        return is_done(self.name, context=context or get_execution_context(True))

    def mark_completed(
        self,
        *,
        artifact_ref: ArtifactRef | None = None,
        content: bytes | None = None,
        expected_batch_id: str | None = None,
        context: ExecutionContext | None = None,
    ) -> None:
        if not _CHECKPOINT_AVAILABLE:
            raise ProvenanceError(
                CHECKPOINT_CAPABILITY_UNAVAILABLE,
                "checkpoint capability is unavailable",
            )
        if artifact_ref is None or content is None:
            raise ProvenanceError("PARENT_MISSING", "completed node requires verified artifact lineage")
        mark_done(
            self.name,
            artifact_ref=artifact_ref,
            content=content,
            expected_batch_id=expected_batch_id,
            context=context or get_execution_context(True),
        )

    def report_progress(
        self,
        percent: int,
        task: str = "",
        *,
        artifact_ref: ArtifactRef | None = None,
        content: bytes | None = None,
        expected_batch_id: str | None = None,
        context: ExecutionContext | None = None,
    ) -> None:
        if artifact_ref is None or content is None:
            raise ProvenanceError("PARENT_MISSING", "progress state requires verified artifact lineage")
        stage_num, total, display_name = self.stage_info
        write_stage(
            stage=self.name,
            stage_num=stage_num,
            total=total,
            percent=percent,
            current_task=task or f"execute {display_name}",
            artifact_ref=artifact_ref,
            content=content,
            expected_batch_id=expected_batch_id,
            context=context or get_execution_context(True),
        )


class PipelineRunner:
    def __init__(self) -> None:
        self._nodes: list[tuple[PipelineNode, int]] = []

    def register(self, node: PipelineNode, group: int = 0) -> None:
        self._nodes.append((node, group))

    def run(
        self,
        genre: str = "",
        *,
        context: ExecutionContext | None = None,
        **kwargs,
    ) -> dict[str, bool]:
        context = context or get_execution_context(True)
        if genre != context.genre_identity:
            raise ProvenanceError("PROFILE_MISMATCH", "genre must match explicit profile context")
        results: dict[str, bool] = {}
        groups: dict[int, list[PipelineNode]] = {}
        order: list[int] = []
        for node, group in self._nodes:
            if group not in groups:
                groups[group] = []
                order.append(group)
            groups[group].append(node)
        for group_id in order:
            nodes = groups[group_id]
            if group_id == 0 or len(nodes) == 1:
                for node in nodes:
                    results[node.name] = self._run_node(node, genre, context=context, **kwargs)
            else:
                with ThreadPoolExecutor(max_workers=min(len(nodes), 3)) as pool:
                    futures = {
                        pool.submit(self._run_node, node, genre, context=context, **kwargs): node.name
                        for node in nodes
                    }
                    for future in as_completed(futures):
                        name = futures[future]
                        try:
                            results[name] = future.result()
                        except ProvenanceError as exc:
                            raise exc
                        except Exception as exc:
                            logger.error("node %s failed: %s", name, exc)
                            results[name] = False
        return results

    def _run_node(
        self,
        node: PipelineNode,
        genre: str,
        *,
        context: ExecutionContext,
        **kwargs,
    ) -> bool:
        stage_num, total, display_name = node.stage_info
        if node.skip_if_done(genre, context=context):
            logger.info("[SKIP] %s", display_name)
            return True
        if not node.check_prerequisites(genre, context=context, **kwargs):
            message = f"{display_name}: prerequisites not met"
            raise ProvenanceError(
                PREREQUISITE_VALIDATION_FAILED,
                message,
                node=node.name,
            )
        if node.input_schema:
            input_errors = node.validate_inputs(genre, context=context)
            if input_errors:
                raise ProvenanceError(
                    INPUT_VALIDATION_FAILED,
                    "; ".join(input_errors),
                    node=node.name,
                )
        try:
            success = node.run(genre=genre, context=context, **kwargs)
        except ProvenanceError:
            raise
        except Exception as exc:
            message = str(exc)
            lineage = _error_lineage(
                node,
                context,
                message,
                expected_batch_id=kwargs.get("expected_batch_id"),
            )
            logger.exception("node %s failed", node.name)
            mark_error(
                node.name,
                message,
                stage_num=stage_num,
                total=total,
                **lineage,
            )
            return False
        if success and node.output_schema:
            output_errors = node.validate_outputs(genre, context=context)
            if output_errors:
                raise ProvenanceError(
                    OUTPUT_VALIDATION_FAILED,
                    "; ".join(output_errors),
                    node=node.name,
                )
        if success:
            lineage_values = (
                kwargs.get("artifact_ref"),
                kwargs.get("content"),
                kwargs.get("expected_batch_id"),
            )
            if any(value is not None for value in lineage_values):
                if not all(value is not None for value in lineage_values):
                    raise ProvenanceError(PARENT_MISSING, "completed node requires complete verified artifact lineage")
                node.mark_completed(
                    artifact_ref=lineage_values[0],
                    content=lineage_values[1],
                    expected_batch_id=lineage_values[2],
                    context=context,
                )
        else:
            message = f"{display_name}: execution failed"
            lineage = _error_lineage(
                node,
                context,
                message,
                expected_batch_id=kwargs.get("expected_batch_id"),
            )
            mark_error(
                node.name,
                message,
                stage_num=stage_num,
                total=total,
                **lineage,
            )
        return success


def _validate_schema(
    schema: dict[str, dict] | None,
    genre: str,
    phase: str,
    *,
    context: ExecutionContext | None = None,
) -> list[str]:
    context = context or get_execution_context(True)
    if genre != context.genre_identity:
        raise ProvenanceError("PROFILE_MISMATCH", "genre must match explicit profile context")
    if schema is None:
        return []
    root = execution_root(context, create=False)
    errors: list[str] = []
    for logical_name, spec in schema.items():
        if not isinstance(spec, dict):
            raise ProvenanceError(INPUT_VALIDATION_FAILED, f"[{logical_name}] schema is not a mapping")
        raw_dir = spec.get("dir", "")
        if not isinstance(raw_dir, str):
            raise ProvenanceError(PATH_ESCAPE, f"[{logical_name}] schema directory is invalid")
        try:
            formatted_dir = raw_dir.format(genre=genre)
        except (KeyError, ValueError) as exc:
            raise ProvenanceError(PATH_ESCAPE, f"[{logical_name}] schema directory template is invalid") from exc
        if formatted_dir:
            _validate_relative_path(formatted_dir)
        relative_dir = Path(formatted_dir)
        dir_path = _validate_root_path(root / relative_dir, root)
        pattern = spec.get("pattern", "*")
        if not isinstance(pattern, str) or not pattern:
            raise ProvenanceError(PATH_ESCAPE, f"[{logical_name}] schema pattern is invalid")
        pattern_path = Path(pattern)
        if pattern_path.is_absolute() or ":" in pattern or ".." in pattern_path.parts:
            raise ProvenanceError(PATH_ESCAPE, f"[{logical_name}] schema pattern escaped the run root")
        required_cols = spec.get("required_columns", [])
        min_files = spec.get("min_files", 1)
        allow_empty = spec.get("allow_empty", False)
        if not dir_path.exists():
            errors.append(f"[{logical_name}] {phase} dir not found: {dir_path}")
            continue
        try:
            files = sorted(dir_path.glob(pattern))
        except (OSError, ValueError) as exc:
            raise ProvenanceError(PATH_ESCAPE, f"[{logical_name}] schema glob is invalid") from exc
        validated_files: list[tuple[Path, str]] = []
        for candidate in files:
            file_path = _validate_root_path(candidate, root)
            if not file_path.is_file():
                raise ProvenanceError(PATH_ESCAPE, f"[{logical_name}] schema glob yielded a non-file")
            try:
                raw = file_path.read_bytes()
                _validate_content_bytes(raw)
                validated_files.append((file_path, raw.decode("utf-8")))
            except ProvenanceError as exc:
                if exc.code == BOM_FORBIDDEN:
                    raise
                raise ProvenanceError(INPUT_VALIDATION_FAILED, f"[{file_path.name}] schema file is invalid") from exc
            except (OSError, UnicodeDecodeError) as exc:
                raise ProvenanceError(INPUT_VALIDATION_FAILED, f"[{file_path.name}] schema file cannot be read") from exc
        files = [file_path for file_path, _ in validated_files]
        if len(files) < min_files:
            errors.append(
                f"[{logical_name}] expected >={min_files} files matching '{pattern}' in {dir_path}, found {len(files)}"
            )
            continue
        if required_cols and pattern.endswith(".csv"):
            for file_path, text in validated_files:
                try:
                    reader = csv.DictReader(io.StringIO(text))
                    if reader.fieldnames is None:
                        errors.append(f"[{logical_name}] {file_path.name}: empty CSV header")
                        continue
                    missing = set(required_cols) - set(reader.fieldnames)
                    if missing:
                        errors.append(
                            f"[{logical_name}] {file_path.name}: missing columns {sorted(missing)}"
                        )
                    if not allow_empty and next(reader, None) is None:
                        errors.append(f"[{logical_name}] {file_path.name}: no data rows")
                except Exception as exc:
                    errors.append(f"[{logical_name}] {file_path.name}: read error: {exc}")
    return errors


def _error_lineage(
    node: PipelineNode,
    context: ExecutionContext,
    message: str,
    *,
    expected_batch_id: str | None,
) -> dict:
    if not isinstance(expected_batch_id, str) or not expected_batch_id:
        raise ProvenanceError(
            BATCH_DIGEST_MISMATCH,
            "error lineage requires a real ExecutionBatch batch id",
        )
    content = f"{node.name}:{message}".encode("utf-8")
    artifact_ref = make_artifact_ref(
        context,
        f"state/errors/{node.name}.txt",
        content,
        source_ref="pipeline-error",
        batch_id=expected_batch_id,
        parent_refs=(context.namespace_digest,),
    )
    return {
        "artifact_ref": artifact_ref,
        "content": content,
        "expected_batch_id": expected_batch_id,
        "context": context,
    }


__all__ = ["PipelineNode", "PipelineRunner"]
