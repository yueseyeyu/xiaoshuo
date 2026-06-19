"""
xiaoshuo — 番茄小说 AI 辅助创作系统
====================================
包根: src/xiaoshuo/

子包:
  cli        — 命令行入口与子命令路由 (原 novel.py)
  agents     — 创作 Agent + 基础设施 (原 agents/)
  pipeline   — 数据分析管线节点 (原 analysis/ 的 8 个节点, 编号=执行顺序)
  reporters  — 报告生成层 (synthesis/contract/comparison)
  lib        — 共享工具 (checkpoint/llm_client/json_utils)

设计约束:
  - 所有跨模块导入使用包绝对路径: from src.xiaoshuo.xxx import yyy
  - 不再依赖 sys.path.insert + 裸 import
  - 数据产物路径保持 data/processed/{genre}/ 不变 (断点续传兼容)

版本: v8.0 (重构后)
"""

__version__ = "8.0.0"
