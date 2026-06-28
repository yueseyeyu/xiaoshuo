"""
xiaoshuo — 番茄小说 AI 辅助创作系统
====================================
包根: src/xiaoshuo/

子包:
  agents     — 创作 Agent + 基础设施
  infra      — 系统运维基础设施 (硬件监控/守护)
  pipeline   — 数据分析管线节点 + 报告生成 + 共享工具
  tools      — 探索性工具 + 运维辅助

设计约束:
  - 所有跨模块导入使用包绝对路径: from xiaoshuo.xxx import yyy
  - 不再依赖 sys.path.insert + 裸 import
  - 数据产物路径保持 data/processed/{genre}/ 不变 (断点续传兼容)

版本: v8.0 (重构后)
"""

from pathlib import Path

__version__ = "8.0.0"

# 统一 PROJECT_ROOT — 替代全仓 86+ 处 Path(__file__).parent.parent hack
# src/xiaoshuo/__init__.py → d:\Code\xiaoshuo\
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
