# -*- coding: utf-8 -*-
"""
pipeline_nodes.py — 管线节点封装 (v8.2)
========================================
将 analyze_all.py 中的 subprocess.run() 调用替换为进程内模块调用。

每个节点继承 PipelineNode，通过设置 sys.argv 并调用模块 main() 实现进程内执行。
优势:
  - 消除 Python 启动开销 (每个 subprocess ~0.3s)
  - 共享内存状态 (config 缓存、模型连接池)
  - 更精确的错误捕获 (异常而非退出码)
  - 断点续传集成

用法:
  from xiaoshuo.pipeline.pipeline_nodes import build_default_pipeline
  runner = build_default_pipeline(with_llm=True)
  results = runner.run(genre="末世")
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from xiaoshuo import PROJECT_ROOT
from xiaoshuo.pipeline.base import PipelineNode, PipelineRunner


class _ModuleCallNode(PipelineNode):
    """通过设置 sys.argv 并调用模块 main() 的通用节点封装。"""

    module_path: str = ""  # 如 "xiaoshuo.pipeline.book_processor"
    script_name: str = ""  # 如 "book_processor" (checkpoint key)

    def __init__(self, extra_args: list[str] | None = None, optional: bool = False):
        self._extra_args = extra_args or []
        self._optional = optional
        self.name = self.script_name

    def run(self, genre: str = "末世", **kwargs) -> bool:
        """设置 sys.argv 并调用模块 main()。"""
        # 构建 argv
        argv = [self.script_name + ".py"]
        if genre and "--genre" not in self._extra_args:
            argv.extend(["--genre", genre])
        argv.extend(self._extra_args)

        # 保存/恢复 sys.argv
        old_argv = sys.argv[:]
        sys.argv = argv
        try:
            import importlib
            mod = importlib.import_module(self.module_path)
            if hasattr(mod, "main"):
                mod.main()
                return True
            else:
                # 没有main函数，尝试直接调用关键函数
                print(f"  [WARN] {self.module_path} has no main(), skipping")
                return True
        except SystemExit as e:
            # argparse 调用 sys.exit()
            code = e.code if isinstance(e.code, int) else 1
            return code == 0
        except Exception as e:
            if self._optional:
                print(f"  [WARN] {self.script_name} failed (non-blocking): {e}")
                return True  # optional 节点失败不阻断
            raise
        finally:
            sys.argv = old_argv


# ── 具体节点定义 ──

class BookProcessorNode(_ModuleCallNode):
    """① 入库处理"""
    module_path = "xiaoshuo.pipeline.book_processor"
    script_name = "book_processor"
    stage_info = (1, 9, "入库处理")


class RhythmAnalyzerNode(_ModuleCallNode):
    """② 拆书节奏分析"""
    module_path = "xiaoshuo.pipeline.rhythm_analyzer"
    script_name = "rhythm_analyzer"
    stage_info = (2, 9, "拆书节奏分析")


class LLMBatchScoreNode(_ModuleCallNode):
    """③ LLM批量评分"""
    module_path = "xiaoshuo.pipeline.llm_batch_score"
    script_name = "llm_batch_score"
    stage_info = (3, 9, "LLM批量评分")

    def run(self, genre: str = "末世", **kwargs) -> bool:
        self._extra_args = ["--book", "all"] + self._extra_args
        return super().run(genre, **kwargs)


class GenreSynthesizerNode(_ModuleCallNode):
    """④ 题材评分合成"""
    module_path = "xiaoshuo.pipeline.genre_synthesizer"
    script_name = "genre_synthesizer"
    stage_info = (3, 9, "题材评分合成")


class QualityGateNode(_ModuleCallNode):
    """⑤ 品质关卡"""
    module_path = "xiaoshuo.pipeline.quality_gate"
    script_name = "quality_gate"
    stage_info = (4, 9, "品质关卡")


class CreativeBridgeNode(_ModuleCallNode):
    """⑥ 创作桥接"""
    module_path = "xiaoshuo.pipeline.creative_bridge"
    script_name = "creative_bridge"
    stage_info = (5, 9, "创作桥接")


class RecursiveSummarizeNode(_ModuleCallNode):
    """⑦ 递归摘要"""
    module_path = "xiaoshuo.pipeline.recursive_summarize"
    script_name = "recursive_summarize"
    stage_info = (6, 9, "递归摘要")


class CrossBookSynthesisNode(_ModuleCallNode):
    """⑧ 跨书合成"""
    module_path = "xiaoshuo.pipeline.cross_book_synthesis"
    script_name = "cross_book_synthesis"
    stage_info = (7, 9, "跨书合成")

    def run(self, genre: str = "末世", **kwargs) -> bool:
        # cross_book_synthesis 只接受 --genre 参数
        self._extra_args = []
        return super().run(genre, **kwargs)


class TechniqueStoreNode(PipelineNode):
    """⑧ 技法卡片提取 (进程内直接调用)"""
    name = "technique_store"
    stage_info = (8, 9, "技法卡片")

    def run(self, genre: str = "末世", **kwargs) -> bool:
        try:
            from xiaoshuo.pipeline.technique_store import process_genre
            self.report_progress(0, f"提取{genre}技法卡片")
            count = process_genre(genre)
            print(f"  [OK] 技法卡片提取完成: {count} 条")
            return True
        except Exception as e:
            print(f"  [FAIL] 技法卡片提取失败: {e}")
            return False


class WritingInstructionsNode(_ModuleCallNode):
    """⑨ 写作指令"""
    module_path = "xiaoshuo.pipeline.writing_instructions"
    script_name = "writing_instructions"
    stage_info = (9, 9, "写作指令")


# ── 可选质检节点 ──

class RhythmAuditorNode(_ModuleCallNode):
    """拆书数据质检 (可选)"""
    module_path = "xiaoshuo.pipeline.rhythm_auditor"
    script_name = "rhythm_auditor"
    stage_info = (2, 9, "拆书数据质检")

    def __init__(self):
        super().__init__(optional=True)


class ScoreAuditorNode(_ModuleCallNode):
    """商业评分质检 (可选)"""
    module_path = "xiaoshuo.pipeline.score_auditor"
    script_name = "score_auditor"
    stage_info = (4, 9, "商业评分质检")

    def __init__(self):
        super().__init__(optional=True)


class LLMLabelerNode(_ModuleCallNode):
    """LLM 标注校准 (可选, --with-llm)"""
    module_path = "xiaoshuo.pipeline.llm_labeler"
    script_name = "llm_labeler"
    stage_info = (1, 9, "LLM标注校准")

    def run(self, genre: str = "末世", **kwargs) -> bool:
        self._extra_args = ["--book=all", "--sample-rate=0.1"]
        return super().run(genre, **kwargs)


# ── 管线构建器 ──

def build_default_pipeline(
    with_llm: bool = False,
    skip_gate: bool = False,
    skip_bridge: bool = False,
    books: str | None = None,
) -> PipelineRunner:
    """构建默认管线。

    Args:
        with_llm: 启用 LLM 增强分析
        skip_gate: 跳过品质关卡
        skip_bridge: 跳过创作桥接
        books: 指定书籍列表

    Returns:
        配置好的 PipelineRunner
    """
    runner = PipelineRunner()

    # Group 0: 入库 (顺序)
    books_args = ["--books", books] if books else []
    bp = BookProcessorNode(extra_args=books_args)
    runner.register(bp, group=0)

    if with_llm:
        runner.register(LLMLabelerNode(), group=0)

    # Group 2: 并行 (rhythm + llm_batch + recursive_summarize)
    runner.register(RhythmAnalyzerNode(extra_args=books_args), group=2)
    if with_llm:
        runner.register(LLMBatchScoreNode(), group=2)
    runner.register(RecursiveSummarizeNode(extra_args=books_args), group=2)

    # Group 0: 顺序后处理
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
