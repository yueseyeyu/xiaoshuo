"""agents — 创作 Agent + 基础设施

模块:
  model_orchestrator — 双模型路由+健康检查+降级 (最高扇入)
  skill_loader       — System Prompt 构建器
  state_machine      — S0->S4+++ 创作工作流状态机
  session_manager    — 写作会话上下文管理器
  world_builder      — S0 冲突驱动世界观构建
  outline_builder    — S0b 大纲生成
  character_designer — S0 角色设计
  chapter_decisions  — 章节决策采集
  cross_review       — 交叉评审 (Qwen 主审 + DS 补充)
"""
