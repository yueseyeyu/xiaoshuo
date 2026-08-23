# -*- coding: utf-8 -*-
"""Pipeline nodes with legacy execution denied before any import or call."""
from __future__ import annotations

import sys
import threading

from xiaoshuo.infra.logging_config import get_logger
from xiaoshuo.pipeline.base import PipelineNode, PipelineRunner
from xiaoshuo.pipeline.provenance import (
    ExecutionContext,
    LegacyCapabilityManifest,
    deny_legacy_execution,
    get_execution_context,
)


logger = get_logger("pipeline.nodes")
_argv_lock = threading.Lock()


def _manifest(module_path: str, *, call_kind: str = "module_main", writer: bool = False):
    return LegacyCapabilityManifest(
        module_path=module_path,
        dynamic_imports_declared=True,
        unresolved_writers=("PROJECT_ROOT",) if writer else (),
        module_main=call_kind == "module_main",
        in_process_call=call_kind == "in_process",
        subprocess_spawn=call_kind == "subprocess",
    )


class _ModuleCallNode(PipelineNode):
    """Compatibility shell; module import/main execution is not authorized in P0."""

    module_path: str = ""
    script_name: str = ""
    stage_info = (0, 0, "")

    def __init__(self, extra_args: list[str] | None = None, optional: bool = False):
        self._extra_args = list(extra_args or [])
        self._optional = optional
        self.name = self.script_name

    def run(self, genre: str = "", **kwargs) -> bool:
        kwargs.get("context") or get_execution_context(True)
        deny_legacy_execution(
            _manifest(self.module_path, call_kind="module_main"),
            call_kind="import/module_main",
        )
        return False


class BookProcessorNode(_ModuleCallNode):
    module_path = "xiaoshuo.pipeline.book_processor"
    script_name = "book_processor"
    stage_info = (1, 9, "book processor")


class RhythmAnalyzerNode(PipelineNode):
    name = "rhythm_analyzer"
    stage_info = (2, 9, "rhythm analyzer")
    output_schema = {
        "rhythm_csv": {
            "dir": "data/processed/{genre}/rhythm",
            "pattern": "rhythm_*.csv",
            "required_columns": [
                "ch_num", "wc", "hook_density", "conflict_density",
                "dialogue_ratio", "pleasure_intensity",
            ],
            "min_files": 1,
        }
    }

    def __init__(self, extra_args: list[str] | None = None, optional: bool = False):
        self._extra_args = list(extra_args or [])
        self._optional = optional

    def run(self, genre: str = "", **kwargs) -> bool:
        kwargs.get("context") or get_execution_context(True)
        deny_legacy_execution(
            _manifest("xiaoshuo.pipeline.rhythm", call_kind="in_process"),
            call_kind="in-process legacy call",
        )
        return False


class LLMBatchScoreNode(_ModuleCallNode):
    module_path = "xiaoshuo.pipeline.llm_batch_score"
    script_name = "llm_batch_score"
    stage_info = (3, 9, "llm batch score")

    def run(self, genre: str = "", **kwargs) -> bool:
        self._extra_args = ["--book", "all"] + self._extra_args
        return super().run(genre, **kwargs)


class GenreSynthesizerNode(_ModuleCallNode):
    module_path = "xiaoshuo.pipeline.genre_synthesizer"
    script_name = "genre_synthesizer"
    stage_info = (3, 9, "genre synthesizer")


class QualityGateNode(PipelineNode):
    name = "quality_gate"
    stage_info = (4, 9, "quality gate")

    def run(self, genre: str = "", **kwargs) -> bool:
        kwargs.get("context") or get_execution_context(True)
        deny_legacy_execution(
            _manifest("xiaoshuo.pipeline.quality_gate", call_kind="in_process", writer=True),
            call_kind="in-process legacy call",
        )
        return False


class CreativeBridgeNode(PipelineNode):
    name = "creative_bridge"
    stage_info = (5, 9, "creative bridge")

    def run(self, genre: str = "", **kwargs) -> bool:
        kwargs.get("context") or get_execution_context(True)
        deny_legacy_execution(
            _manifest("xiaoshuo.pipeline.creative_bridge", call_kind="in_process", writer=True),
            call_kind="in-process legacy call",
        )
        return False


class RecursiveSummarizeNode(_ModuleCallNode):
    module_path = "xiaoshuo.pipeline.recursive_summarize"
    script_name = "recursive_summarize"
    stage_info = (6, 9, "recursive summarize")


class CrossBookSynthesisNode(_ModuleCallNode):
    module_path = "xiaoshuo.pipeline.cross_book_synthesis"
    script_name = "cross_book_synthesis"
    stage_info = (7, 9, "cross book synthesis")


class TechniqueStoreNode(PipelineNode):
    name = "technique_store"
    stage_info = (8, 9, "technique store")

    def run(self, genre: str = "", **kwargs) -> bool:
        kwargs.get("context") or get_execution_context(True)
        deny_legacy_execution(
            _manifest("xiaoshuo.pipeline.technique_store", call_kind="in_process", writer=True),
            call_kind="in-process legacy call",
        )
        return False


class WritingInstructionsNode(PipelineNode):
    name = "writing_instructions"
    stage_info = (9, 9, "writing instructions")

    def __init__(self, extra_args: list[str] | None = None, optional: bool = False):
        self._extra_args = list(extra_args or [])
        self._optional = optional

    def run(self, genre: str = "", **kwargs) -> bool:
        kwargs.get("context") or get_execution_context(True)
        deny_legacy_execution(
            _manifest("xiaoshuo.pipeline.writing_instructions", call_kind="in_process", writer=True),
            call_kind="in-process legacy call",
        )
        return False


class RhythmAuditorNode(_ModuleCallNode):
    module_path = "xiaoshuo.pipeline.rhythm_auditor"
    script_name = "rhythm_auditor"
    stage_info = (2, 9, "rhythm auditor")

    def __init__(self):
        super().__init__(optional=True)


class ScoreAuditorNode(_ModuleCallNode):
    module_path = "xiaoshuo.pipeline.score_auditor"
    script_name = "score_auditor"
    stage_info = (4, 9, "score auditor")

    def __init__(self):
        super().__init__(optional=True)


class LLMLabelerNode(_ModuleCallNode):
    module_path = "xiaoshuo.pipeline.llm_labeler"
    script_name = "llm_labeler"
    stage_info = (1, 9, "llm labeler")

    def run(self, genre: str = "", **kwargs) -> bool:
        self._extra_args = ["--book=all", "--sample-rate=0.1"]
        return super().run(genre, **kwargs)


def build_default_pipeline(
    with_llm: bool = False,
    skip_gate: bool = False,
    skip_bridge: bool = False,
    books: str | None = None,
) -> PipelineRunner:
    runner = PipelineRunner()
    books_args = ["--books", books] if books else []
    runner.register(BookProcessorNode(extra_args=books_args), group=0)
    if with_llm:
        runner.register(LLMLabelerNode(), group=0)
    runner.register(RhythmAnalyzerNode(extra_args=books_args), group=2)
    if with_llm:
        runner.register(LLMBatchScoreNode(), group=2)
    runner.register(RecursiveSummarizeNode(extra_args=books_args), group=2)
    runner.register(RhythmAuditorNode(), group=3)
    runner.register(GenreSynthesizerNode(extra_args=books_args), group=3)
    runner.register(ScoreAuditorNode(), group=3)
    if not skip_gate:
        runner.register(QualityGateNode(), group=3)
    if not skip_bridge:
        runner.register(CreativeBridgeNode(), group=3)
    runner.register(CrossBookSynthesisNode(), group=3)
    runner.register(TechniqueStoreNode(), group=3)
    runner.register(WritingInstructionsNode(extra_args=books_args), group=3)
    return runner


__all__ = [
    "BookProcessorNode", "CreativeBridgeNode", "CrossBookSynthesisNode",
    "GenreSynthesizerNode", "LLMBatchScoreNode", "LLMLabelerNode",
    "PipelineNode", "PipelineRunner", "QualityGateNode", "RecursiveSummarizeNode",
    "RhythmAnalyzerNode", "RhythmAuditorNode", "ScoreAuditorNode", "TechniqueStoreNode",
    "WritingInstructionsNode", "_ModuleCallNode", "_argv_lock", "build_default_pipeline",
]
