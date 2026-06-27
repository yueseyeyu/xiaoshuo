---
alwaysApply: true
description: "项目背景和当前状态"
---

# 项目上下文 v7.4

## 技术栈
- 环境：conda llm-shared (D:\miniconda3\envs\llm-shared)
- 本地模型：Qwen3.5-9B (Q4_K_M, port 8000, n_ctx=8192)
- 云端模型：DeepSeek V4-Flash / V4-Pro
- GPU：RTX 5060 8GB | OS：Windows 11

## 目录速查
| 目录 | 用途 |
|------|------|
| `analysis/` | 数据分析管线 (入库→节奏→评分→关卡→报告) |
| `agents/` | LLM代理 (路由/状态机/世界观/大纲/交叉评审) |
| `books/` | 书籍入口: in/→review/→data/raw/novels/ |
| `data/raw/` | 原始小说TXT (不可修改) |
| `data/processed/` | 中间产物 (CSV/JSON) |
| `scripts/` | 工具脚本 (start_model / lint / convert_encoding) |
| `设计方案/` | 前端设计方案归档与对比预览入口 |
| `assets/` | 创作资产 (library/canon/chapters/outline/voice) |
| `.codebuddy/` | **CodeBuddy 专属，不要动** |
| `.trae/rules/` | **本文件，Trae 的规则** |

## 当前管线状态（9阶段全通 ✅）
① book_processor 入库 → ② rhythm_analyzer 拆书 → ③ llm_batch_score 评分 → ④ genre_synthesizer 合成 → ⑤ quality_gate 关卡 → ⑥ creative_bridge 整合 → ⑦ recursive_summarize 摘要 → ⑧ cross_book_synthesis 对比 → ⑨ writing_instructions 指导

> 注意：旧版文档中"6阶段管線"是旧分类，当前实际是 9 阶段流水线，以 `analyze_all.py` 为准。

## 数据资产
- 33本入库（17末世精品 + 16其他题材，13种类型）
- 商业评分融合（Bayesian Stacking + Spearman 0.66 vs 完读率）
- 全模块 py_compile ✅ | 13/13 单元测试 ✅ | 7/7 novel.py test ✅

## 快速命令
```bash
scripts\start_model.bat              # 启动 Qwen3.5-9B
scripts\lint.bat                      # 代码检查
python novel.py analyze --genre 末世  # 末世题材分析
python analysis/analyze_all.py        # 一键全量
python analysis/writing_instructions.py  # 逐章写作指令
```
