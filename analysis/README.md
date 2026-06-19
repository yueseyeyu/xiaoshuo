# analysis/ — 小说数据分析管线

## 模块

| 文件 | 功能 | 参考 |
|------|------|------|
| `book_processor.py` | 书籍入库: 编码检测→转码→类型检测→精品分流 | — |
| `quality_gate.py` | 双层品质关卡: Gate A形式完整性 + Gate B节奏商业 | — |
| `rhythm_analyzer.py` | 节奏分析: 30+指标(钩子/冲突/爽点/对白/句长) | — |
| `genre_synthesizer.py` | 商业评分: Bayesian BMA + Borda排名 + 技法总纲 | — |
| `creative_bridge.py` | 创作指导: 8维指导文档生成 | — |
| `comparison_engine.py` | 签约评估: 6维精品百分位对标 + LLM对照 | — |
| `structure_comparator.py` | 结构对比: 世界观/大纲/角色三维对标 | — |
| `calibrate_v2.py` | Bayesian校准: feature_importance → BMA权重 | — |
| `analyze_all.py` | 一键全量: rhythm → genre → bridge | — |

## 管线

```
books/in/*.txt
    ↓ book_processor
data/raw/novels/ (已入库)
    ↓ rhythm_analyzer → quality_gate
data/processed/{genre}/rhythm/*.csv + quality_manifest.json
    ↓ genre_synthesizer + llm_batch_score
data/reports/{genre}/synthesis/ (技法总纲 + Borda排名)
    ↓ creative_bridge
data/reports/{genre}/creative_guidance/ (创作指导.md/.json)
    ↓ comparison_engine + structure_comparator
data/reports/{genre}/evaluations/ + structure_eval/
```
