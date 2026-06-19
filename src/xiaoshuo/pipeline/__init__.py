"""pipeline — 数据分析管线节点

编号 = 执行顺序 (与 HANDOFF.md 管线条 ①->⑩ 对齐):
  01_book_processor       — 入库
  02_rhythm_analyzer      — 节奏拆书
  03_llm_batch_score      — LLM 评分
  04_genre_synthesizer    — 商业评分
  05_quality_gate         — 品质关卡
  06_recursive_summarize  — 深层拆书 (L1->L2->L3)  ← 当前焦点
  07_creative_bridge      — 创作指导
  08_cross_book_synthesis — 跨书白皮书
  09_writing_instructions — 逐章指令 + 合同链

编排入口:
  analyze_all — 一键全链路
"""
