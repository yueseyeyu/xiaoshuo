"""pipeline — 数据分析管线节点 (v7.5)

编号 = 执行顺序 (与 HANDOFF.md 管线条 ①->⑨ 对齐):
  01_book_processor       — 入库过滤
  02_rhythm_analyzer      — 拆书节奏分析 (35+指标/章)
  03_llm_batch_score      — LLM 批量评分 (10%采样验证)
  04_genre_synthesizer    — 题材商业评分 (Bootstrap CI + Borda排名)
  05_quality_gate         — 品质关卡
  06_recursive_summarize  — 递归摘要 (L1章->L2卷->L3全书)
  07_creative_bridge      — 创作桥接 (8维指导)
  08_cross_book_synthesis — 跨书技法合成
  09_writing_instructions — 逐章写作指令

辅线模块:
  rhythm_auditor.py       — 节奏数据质检
  score_auditor.py        — 评分数据质检
  synthesis_reporter.py   — 合成报告生成
  technique_store.py      — 技法卡片提取
  comparison_engine.py    — 多版本对比 (Part D)
  contract_chain.py       — 合同链校验
  feedback_loop.py        — 反馈闭环
  llm_labeler.py          — LLM标注工具

评分子模块 (scoring/):
  commercial_engine.py    — 商业评分引擎
  borda_ranker.py         — Borda跨书排名
  pro_genre_guide.py      — Pro API类型指导 (v11)
  vad_analyzer.py         — VAD情感分析
  structure_matcher.py    — 结构模式匹配
  technique_tagger.py     — 技法标签

编排入口:
  analyze_all — 一键全链路
"""
