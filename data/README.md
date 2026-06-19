# data/ — 运行时数据

| 目录 | 用途 | 来源 |
|------|------|------|
| `raw/novels/` | 小说TXT（不可修改） | book_processor 同步 |
| `raw/novel_index.json` | 小说索引 | 注册时更新 |
| `processed/{genre}/rhythm/` | 节奏CSV | rhythm_analyzer 输出 |
| `processed/{genre}/llm_scores/` | LLM评分CSV | llm_batch_score 输出 |
| `processed/{genre}/quality_manifest.json` | 品质清单 | quality_gate 输出 |
| `reports/{genre}/` | 分析报告/创作指导/对比评估 | creative_bridge/comparison_engine 输出 |
