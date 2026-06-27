# 番茄小说 AI 辅助创作系统 -- 系统架构设计文档

> **文档版本**: v7.5
> **实际代码**: analysis/ 7步管线 + agents/ 10模块 + novel.py 15命令
> **关联文档**: [AI_PROTOCOL.md](AI_PROTOCOL.md) | [config.yaml](config.yaml)
> **v7.5 审视修复**: 2026-06-19 — 13项架构优化落地（P0安全/P1并行+拆分+重构/P2基础设施）
> **v7.5 交叉审查升级**: 2026-06-21 — 双模型顺序切换（swap_to）+ 交叉模型升级至 DeepSeek-R1-0528-Qwen3-8B + S3 评审角色深层 TASK_TEMPLATES + AI 指纹词密度/风格漂移 detection 配置
> **v7.5 Agent 记忆系统**: 2026-06-21 — 结构化行为回溯备忘录 (SQLite + 精准Tag) + CLI 命令 + pipeline 集成钩子 (add_from_pipeline)

---

## 实现状态说明

| 标签 | 含义 |
|------|------|
| ✅ | 已实现，代码可用 |
| ⚠️ | 部分实现，骨架存在但功能不完整 |
| ❌ | 设计阶段，无对应代码 |
| 📋 | 规划中，待排期 |

---

## 设计文档索引

本文档是系统设计的主索引。各模块的详细设计已拆分为独立文档：

| # | 文档 | 内容 | 实现状态 |
|---|------|------|:---:|
| 1 | [1. 设计哲学与目标](docs/design/01-philosophy.md) | 设计哲学、目标、约束矩阵、术语定义 | ✅ |
| 2 | [2. 系统总览 + 3. 分层架构](docs/design/02-architecture-overview.md) | 系统定位、技术栈、模型选型、十层分层架构 | ⚠️ |
| 3 | [4. 模块设计 (上半: 工作流引擎/知识图谱/检测引擎)](docs/design/03-modules-core.md) | 工作流引擎(M1)、知识图谱(M2)、语义记忆(M2b)、检测引擎(S4+++) | ⚠️ |
| 4 | [4. 模块设计 (下半: 交互/节拍/漂移/编排/文件系统)](docs/design/04-modules-aux.md) | 交互接口(M5)、节拍分析(M5a)、风格漂移(M5b)、模型编排(M5d)、文件系统(M6) | ⚠️ |
| 5 | [5. 数据设计 + 6. 工作流设计](docs/design/05-data-config.md) | NovelGraph表结构、config.yaml配置、state.json状态 | ⚠️ |
| 6 | [7. 接口与通信设计](docs/design/06-interface-protocol.md) | AI协议注入、Prefix Caching、LLM通信协议 | ✅ |
| 7 | [8. 安全与合规设计](docs/design/07-security-compliance.md) | 六层防御体系、MASH对抗流水线、平台合规红线 | ⚠️ |
| 8 | [9. 评估体系与质量保障](docs/design/08-evaluation-testing.md) | 黄金测试集、模块评估指标、PAN 2026、A/B测试 | ⚠️ |
| 9 | [10. 部署 + 11. 风险 + 12. 演进路线图](docs/design/09-deploy-roadmap.md) | 部署方案、技术风险、流程风险、演进路线图(P0-P3) | ⚠️ |
| 10 | [附录 + 架构重构说明](docs/design/10-appendix.md) | 设计决策记录、关键文件清单、版本历史、审视方法论 | ✅ |
| 11 | [15. 完整创作愿景与实现路径](docs/design/11-vision.md) | 十阶段创作辅助闭环、各阶段现状、风格涌现、蒸馏进化 | ⚠️ |

### 前端设计系统

前端设计方案统一归档在 `设计方案/` 目录，支持旧版与新版并排对比预览：

| 文档 | 内容 | 状态 |
|------|------|:---:|
| [设计方案对比入口](../设计方案/index.html) | 旧版 V1 / 新版 v2.1 单页预览与并排对比 | ✅ |
| [旧版 V1 版本说明](../设计方案/设计归档_20250621_V1/版本说明.md) | 玻璃拟态工作站设计说明 | ✅ |
| [新版 v2.1 界面优化设计稿](../设计方案/界面优化设计稿.md) | 色彩/字体/组件/布局/动效规范 | ✅ |
| [新版 v2.1 测试验证文档](../设计方案/测试验证文档.md) | 问题清单、修复验证、性能/兼容性报告 | ✅ |
| [新版 v2.1 功能测试用例库](../设计方案/功能测试用例库.md) | 可回归功能测试用例 | ✅ |

### v7.5 基础设施新增

| 模块 | 路径 | 用途 |
|------|------|------|
| 日志系统 | `src/xiaoshuo/infra/logging_config.py` | 统一结构化日志（控制台 INFO + 文件 DEBUG 轮转 7 天） |
| 配置管理器 | `src/xiaoshuo/infra/config_manager.py` | 全局 config 单例缓存，替代各模块独立加载 |
| 性能监控 | `src/xiaoshuo/infra/performance.py` | @timed 装饰器 + PipelineTimer 阶段计时 |
| 数据校验 | `src/xiaoshuo/infra/schemas.py` | state.json/novel_index.json 格式校验 |
| 评分拆分 | `src/xiaoshuo/pipeline/scoring/` | genre_synthesizer 拆分为 6 子模块 |
| 冒烟测试 | `tests/smoke_test.py` | 集成冒烟测试（无 LLM 依赖） |
| 并行管线 | `analyze_all.py --parallel` | 阶段并行执行（~40% 加速） |
| 交叉审查 | `agents/cross_review.py` + `agents/model_orchestrator.swap_to()` | 双模型顺序切换交叉审查（Qwen3.5-9B → DeepSeek-R1-0528-Qwen3-8B） |
| Agent记忆 | `agents/memory_store.py` | 结构化行为回溯备忘录 (SQLite + 精准Tag, 零向量依赖) |

---

## 快速导航

### 按角色查看文档

- **架构师**: [02-架构概览](docs/design/02-architecture-overview.md) -> [03-核心模块](docs/design/03-modules-core.md) -> [05-数据配置](docs/design/05-data-config.md)
- **开发者**: [04-辅助模块](docs/design/04-modules-aux.md) -> [06-接口协议](docs/design/06-interface-protocol.md) -> [09-部署路线图](docs/design/09-deploy-roadmap.md)
- **创作者**: [11-完整愿景](docs/design/11-vision.md) -> [08-评估测试](docs/design/08-evaluation-testing.md)
- **审查者**: [07-安全合规](docs/design/07-security-compliance.md) -> [08-评估测试](docs/design/08-evaluation-testing.md) -> [10-附录](docs/design/10-appendix.md)

### 按阶段查看文档

- **Part A 数据管线**: [03-核心模块](docs/design/03-modules-core.md) (book_processor -> creative_bridge)
- **Part B 骨架生成**: [04-辅助模块](docs/design/04-modules-aux.md) (world_builder / outline_builder / character_designer)
- **Part C 写作交互**: [05-数据配置](docs/design/05-data-config.md) (state_machine workflow)
- **Part D 对比保障**: [03-核心模块](docs/design/03-modules-core.md) (comparison_engine)
- **Part E 风格涌现**: [11-完整愿景](docs/design/11-vision.md) (chapter_decisions -> style_emergence)
