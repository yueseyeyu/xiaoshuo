# data/ — 运行时数据

| 目录 | 用途 | 来源 |
|------|------|------|
| `raw/novels/` | 小说TXT（不可修改） | book_processor 同步 |
| `raw/novel_index.json` | 小说索引 | 注册时更新 |
| `processed/rhythm/` | 节奏CSV | rhythm_analyzer 输出 |
| `processed/llm_scores/` | LLM评分CSV | llm_batch_score 输出 |

最终报告在 `outputs/` 目录。
