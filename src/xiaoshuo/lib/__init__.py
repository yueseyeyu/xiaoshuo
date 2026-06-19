"""lib — 共享工具函数

从各模块抽出的、被多处复用的工具:
  checkpoint  — 管线检查点快照
  llm_client  — LLM 调用封装 (urllib + retry, 匹配 rhythm_analyzer 模式)
  json_utils  — JSON 解析/修复/安全截断 (_parse_json/_repair_json/_safe_truncate)
"""
