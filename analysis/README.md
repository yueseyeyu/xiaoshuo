# analysis/ — 小说数据分析管线

## 模块

| 文件 | 功能 | 参考 |
|------|------|------|
| `book_processor.py` | 书籍入库: 编码检测→转码→类型检测→精品分流 | — |
| `rhythm_analyzer.py` | 节奏分析: Macro/Meso/Micro 三级指标 | ACL2025 Novel Benchmark |
| `genre_synthesizer.py` | 商业评分: 拆书三件套 + VAD情感弧 + 留存预估 | MARCUS + 笔灵AI |
| `llm_batch_score.py` | LLM量规打分 | Rubric Is All You Need (ACM 2025) |
| `calibrate_v2.py` | 独立校准: Pearson r + Platt Scaling | — |
| `calibrate_rules.py` | 规则校准 | — |
| `analyze_all.py` | 一键全量: rhythm → genre | — |

## 管线

```
books_in/*.txt
    ↓ python analysis/book_processor.py
books_vault/  (精品)
    ↓ python analysis/analyze_all.py
rhythm CSV + genre synthesis report
```
