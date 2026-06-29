"""Handoff 任务交接机制 v8.1

管线阶段间状态传递：将当前阶段的分析结果、决策、风险压缩为"接续包",
支持以下场景：
- 管线阶段间交接 (Part A -> B -> C -> D -> E)
- 会话中断后断点续传
- 模型切换时状态传递（主模型 <-> 交叉模型）

Part 对照:
  Part A: 创意引导 / 题材分析
  Part B: 骨架生成 / 大纲构建
  Part C: 手写 / 章节施工
  Part D: 多版本对比 / 评审
  Part E: 风格进化 / 技法提炼

存储层复用 agents/memory_store.py 的 SQLite 四维记忆系统。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class HandoffPackage:
    """管线阶段间的标准接续包。

    每个 pipeline 阶段完成时，将关键信息压缩为此包，
    传递给下一阶段。
    """

    # ── 目标与进度 ──
    target: str = ""                         # 当前阶段目标
    stage: str = ""                          # 当前阶段标识 (Part A/B/C/D/E)
    completed: list[str] = field(default_factory=list)   # 已完成的关键步骤
    progress_pct: int = 0                    # 进度百分比 (0-100)

    # ── 关键决策 ──
    decisions: list[dict] = field(default_factory=list)  # [{decision, reason, timestamp}]

    # ── 验证结果 ──
    verified: list[str] = field(default_factory=list)    # 已验证的结论
    artifacts: dict[str, str] = field(default_factory=dict)  # 关联文件/数据路径

    # ── 剩余风险 ──
    risks: list[str] = field(default_factory=list)       # 剩余风险 + 不能动的部分

    # ── 交接信息 ──
    next_agent: str = ""                     # 下一阶段 Agent 标识
    created_at: str = ""                     # 创建时间
    source_session: str = ""                 # 来源会话 ID

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.strftime("%Y-%m-%d %H:%M:%S")

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def to_markdown(self) -> str:
        """生成人类可读的 Markdown 格式。"""
        lines = [
            f"# Handoff: {self.stage} -> {self.next_agent}",
            f"**目标**: {self.target}",
            f"**进度**: {self.progress_pct}%  |  **创建**: {self.created_at}",
            "",
            "## 已完成",
        ]
        for item in self.completed:
            lines.append(f"- [x] {item}")
        lines.append("")
        lines.append("## 关键决策")
        for d in self.decisions:
            lines.append(f"- **{d.get('decision', '')}**: {d.get('reason', '')}")
        lines.append("")
        lines.append("## 已验证")
        for item in self.verified:
            lines.append(f"- {item}")
        lines.append("")
        lines.append("## 剩余风险")
        for r in self.risks:
            lines.append(f"- {r}")
        return "\n".join(lines)

    @classmethod
    def from_dict(cls, data: dict) -> HandoffPackage:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_json(cls, text: str) -> HandoffPackage:
        return cls.from_dict(json.loads(text))

    def merge(self, other: HandoffPackage) -> HandoffPackage:
        """将另一个接续包合并到当前包（用于模型切换后继承上下文）。"""
        merged = HandoffPackage.from_dict(self.to_dict())
        merged.completed = list(set(self.completed + other.completed))
        merged.decisions = self.decisions + [d for d in other.decisions
                                              if d not in self.decisions]
        merged.risks = list(set(self.risks + other.risks))
        merged.verified = list(set(self.verified + other.verified))
        merged.artifacts.update(other.artifacts)
        merged.progress_pct = max(self.progress_pct, other.progress_pct)
        return merged