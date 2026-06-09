# 番茄小说 AI 辅助创作系统 -- 系统架构设计文档

> **文档版本**: v7.5
> **实际代码**: analysis/ 7步管线 + agents/ 9模块 + novel.py 15命令
> **关联文档**: [AI_PROTOCOL.md](AI_PROTOCOL.md) | [config.yaml](config.yaml)

---

## 设计文档索引

本文档是系统设计的主索引。各模块的详细设计已拆分为独立文档：

| # | 文档 | 内容 |
|---|------|------|
| 1 | [1. 设计哲学与目标](docs/design/01-philosophy.md) | 设计哲学、目标、约束矩阵、术语定义 |
| 2 | [2. 系统总览 + 3. 分层架构](docs/design/02-architecture-overview.md) | 系统定位、技术栈、模型选型、十层分层架构 |
| 3 | [4. 模块设计 (上半: 工作流引擎/知识图谱/检测引擎)](docs/design/03-modules-core.md) | 工作流引擎(M1)、知识图谱(M2)、语义记忆(M2b)、检测引擎(S4+++) |
| 4 | [4. 模块设计 (下半: 交互/节拍/漂移/编排/文件系统)](docs/design/04-modules-aux.md) | 交互接口(M5)、节拍分析(M5a)、风格漂移(M5b)、模型编排(M5d)、文件系统(M6) |
| 5 | [5. 数据设计 + 6. 工作流设计](docs/design/05-data-config.md) | NovelGraph表结构、config.yaml配置、state.json状态 |
| 6 | [7. 接口与通信设计](docs/design/06-interface-protocol.md) | AI协议注入、Prefix Caching、LLM通信协议 |
| 7 | [8. 安全与合规设计](docs/design/07-security-compliance.md) | 六层防御体系、MASH对抗流水线、平台合规红线 |
| 8 | [9. 评估体系与质量保障](docs/design/08-evaluation-testing.md) | 黄金测试集、模块评估指标、PAN 2026、A/B测试 |
| 9 | [10. 部署 + 11. 风险 + 12. 演进路线图](docs/design/09-deploy-roadmap.md) | 部署方案、技术风险、流程风险、演进路线图(P0-P3) |
| 10 | [附录 + 架构重构说明](docs/design/10-appendix.md) | 设计决策记录、关键文件清单、版本历史、审视方法论 |
| 11 | [15. 完整创作愿景与实现路径](docs/design/11-vision.md) | 十阶段创作辅助闭环、各阶段现状、风格涌现、蒸馏进化 |

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
