# -*- coding: utf-8 -*-
"""
pipeline/base.py — Pipeline 节点基类与运行器
=============================================
v8.2: 统一管线节点契约，替代 analyze_all.py 中的 subprocess.run() 调用。

设计原则:
  - 每个管线节点继承 PipelineNode，实现 run() 方法
  - PipelineRunner 管理执行顺序、断点续传、进度报告
  - 支持并行组 (Group 2: rhythm + llm_batch + recursive_summarize)
  - 错误不中断整条管线，记录到 pipeline_state

用法:
  from xiaoshuo.pipeline.base import PipelineNode, PipelineRunner

  class MyNode(PipelineNode):
      name = "my_node"
      stage_info = (5, 9, "我的节点")

      def run(self, genre="末世", **kwargs) -> bool:
          ...
          return True

  runner = PipelineRunner()
  runner.register(MyNode())
  runner.run(genre="末世")
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from xiaoshuo import PROJECT_ROOT
from xiaoshuo.infra.logging_config import get_logger
from xiaoshuo.infra.pipeline_state import clear_stage, mark_error, write_stage

logger = get_logger("pipeline.base")

# Checkpoint support
try:
    from xiaoshuo.pipeline.checkpoint import is_done, mark_done
    _CHECKPOINT_AVAILABLE = True
except ImportError:
    _CHECKPOINT_AVAILABLE = False


class PipelineNode(ABC):
    """管线节点抽象基类。

    每个子类需要实现:
      - name: 节点标识 (与 checkpoint key 一致)
      - stage_info: (stage_num, total, display_name) 用于进度显示
      - run(genre, **kwargs) -> bool: 主执行逻辑
    可选实现:
      - check_prerequisites(genre) -> bool: 检查前置条件
      - get_outputs(genre) -> list[Path]: 预期输出文件
    """

    name: str = ""
    stage_info: tuple[int, int, str] = (0, 0, "")

    @abstractmethod
    def run(self, genre: str = "末世", **kwargs) -> bool:
        """执行节点逻辑。

        Args:
            genre: 题材名称
            **kwargs: 额外参数

        Returns:
            True 表示成功, False 表示失败
        """
        ...

    def check_prerequisites(self, genre: str = "末世") -> bool:
        """检查前置条件是否满足。默认返回 True。"""
        return True

    def get_outputs(self, genre: str = "末世") -> list[Path]:
        """返回预期输出文件列表。默认返回空列表。"""
        return []

    def skip_if_done(self, genre: str = "末世") -> bool:
        """检查断点续传：如果已完成则跳过。"""
        if not _CHECKPOINT_AVAILABLE:
            return False
        return is_done(self.name)

    def mark_completed(self):
        """标记节点为已完成 (断点续传)。"""
        if _CHECKPOINT_AVAILABLE:
            mark_done(self.name)

    def report_progress(self, percent: int, task: str = ""):
        """向 pipeline_state 报告进度。"""
        stage_num, total, display_name = self.stage_info
        write_stage(
            stage=self.name,
            stage_num=stage_num,
            total=total,
            percent=percent,
            current_task=task or f"执行 {display_name}",
        )


class PipelineRunner:
    """管线运行器：管理节点注册、执行顺序、并行组、断点续传。

    用法:
        runner = PipelineRunner()
        runner.register(BookProcessorNode())
        runner.register(RhythmAnalyzerNode(), group=2)
        runner.register(LLMBatchScoreNode(), group=2)
        runner.run(genre="末世")
    """

    def __init__(self):
        self._nodes: list[tuple[PipelineNode, int]] = []  # (node, group)
        self._timer = None

    def register(self, node: PipelineNode, group: int = 0):
        """注册节点。

        Args:
            node: PipelineNode 实例
            group: 并行组号 (0=顺序执行, 相同组号的节点并行执行)
        """
        self._nodes.append((node, group))

    def run(self, genre: str = "末世", **kwargs) -> dict[str, bool]:
        """执行所有已注册节点。

        Returns:
            {node_name: success} 字典
        """
        results: dict[str, bool] = {}

        # 按组分组
        groups: dict[int, list[PipelineNode]] = {}
        order: list[int] = []
        for node, group in self._nodes:
            if group not in groups:
                groups[group] = []
                order.append(group)
            groups[group].append(node)

        # 按组执行
        for group_id in order:
            nodes = groups[group_id]
            if group_id == 0 or len(nodes) == 1:
                # 顺序执行
                for node in nodes:
                    results[node.name] = self._run_node(node, genre, **kwargs)
            else:
                # 并行执行
                max_workers = min(len(nodes), 3)  # 限制并发数
                with ThreadPoolExecutor(max_workers=max_workers) as pool:
                    futures = {
                        pool.submit(self._run_node, node, genre, **kwargs): node.name
                        for node in nodes
                    }
                    for future in as_completed(futures):
                        node_name = futures[future]
                        try:
                            results[node_name] = future.result()
                        except Exception as e:
                            logger.error("节点 %s 异常: %s", node_name, e)
                            results[node_name] = False

        return results

    def _run_node(self, node: PipelineNode, genre: str, **kwargs) -> bool:
        """执行单个节点，含断点续传和错误处理。"""
        stage_num, total, display_name = node.stage_info

        # 断点续传检查
        if node.skip_if_done(genre):
            logger.info("[SKIP] %s (checkpoint: already done)", display_name)
            return True

        logger.info("=" * 60)
        logger.info("  %s", display_name)
        logger.info("=" * 60)

        # 前置条件检查
        if not node.check_prerequisites(genre):
            msg = f"{display_name}: 前置条件不满足"
            logger.warning(msg)
            mark_error(node.name, msg, stage_num=stage_num, total=total)
            return False

        # 执行
        try:
            success = node.run(genre=genre, **kwargs)
        except Exception as e:
            logger.exception("节点 %s 执行异常", node.name)
            mark_error(node.name, str(e), stage_num=stage_num, total=total)
            return False

        if success:
            node.mark_completed()
        else:
            mark_error(node.name, f"{display_name} 执行失败",
                      stage_num=stage_num, total=total)

        return success
