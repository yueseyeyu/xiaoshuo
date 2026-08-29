# xiaoshuo 目录结构基线与渐进收敛规则

状态：`CURRENT_BASELINE_AND_TARGET_APPROVED_AS_DEVELOPMENT_GUIDE`

更新时间：2026-08-25

## 1. 权威来源

本文件不另行定义一套最终目录结构。最终业务边界、目标目录、依赖方向和阶段顺序以以下已批准设计为唯一权威：

[`docs/plans/2026-08-capability-oriented-directory-convergence-design.md`](docs/plans/2026-08-capability-oriented-directory-convergence-design.md)

本文件是项目顶层日常开发入口，只提供当前结构索引、目标方向和迁移执行规则。若本文件与上述设计不一致，以上述设计为准，并先修正文档，不得据此迁移代码。

该设计状态为 `OWNER_DIRECTION_APPROVED / WRITTEN_REVIEW_REQUIRED / CODE_NOT_AUTHORIZED`。它是长期收敛方向，不是一次性目录搬迁授权。

## 2. 设计原则

- 以业务能力和稳定边界划分目录，不把工作流阶段机械映射为顶层业务包。
- 保持领域对象、业务状态、API 契约、模型适配和执行语义稳定。
- 新增代码逐批向目标靠拢，不为了目录整齐顺手移动当前批次文件。
- 先完成 importer、依赖方向、运行时消费者、测试映射和回滚分析，再进行迁移。
- 当前目录与目标目录分开描述；目标目录中的路径不得标记为已完成。

## 3. 当前结构事实

当前项目仍包含 `pipeline/`、`infra/`、`infrastructure/`、`domain/creation/`、`application/creation/`、`api/`、`agents/`、`tools/` 等实际目录。它们是当前可达代码事实，不代表目标收敛已经完成。

当前已知边界：

1. `pipeline/` 仍承载多个业务能力、编排和共享模块，不能仅按文件名推断最终归属。
2. `infra/` 与 `infrastructure/` 的职责重叠尚未完成 importer、port、cycle 和运行时消费者 census。
3. `pipeline/provenance.py` 属于当前保护面和稳定依赖，未经独立批次不得移动或拆分。
4. 当前 B 批次的索引收尾文件继续留在现有 `pipeline/` 路径，直到该批次完成并另立迁移批次。

## 4. 已批准的最终业务能力方向

目标采用“六个业务上下文加一个薄编排层”，不是通用的 `domain/application/infrastructure/pipeline` 模板，也不是九个流程槽位对应九个顶层目录：

```text
src/xiaoshuo/
├─ analysis/
│  ├─ ingestion/           # 入库、规范化
│  ├─ rhythm/              # 节奏与章节分析
│  ├─ scoring/             # 题材与 LLM 评分
│  ├─ index/               # 索引、检索、比较
│  └─ knowledge/           # 摘要、跨书合成、技法知识
├─ authoring/              # 创作桥接与写作指令
├─ quality/                # 业务质量门禁与审计
├─ evaluation/             # P1-A/P1-AE 评估上下文
├─ canon_analysis/         # 文本设定提取、分析与一致性检查
├─ domain/creation/        # 既有稳定 creation 领域，保留
├─ application/creation/   # 既有稳定 creation 用例，保留
├─ infrastructure/         # 既有 persistence/canon 基础设施，当前保留
├─ orchestration/          # 流程图、阶段注册、调度和 checkpoint
├─ api/                    # 当前保留；未来只依赖公开用例或入口
├─ agents/                 # 当前保留；不得穿透业务包内部
├─ tools/                  # 当前保留；逐项甄别真实归属
└─ infra/                  # 当前冻结扩张，暂不裁决最终收敛名称
```

特别边界：

- `quality` 与 `evaluation` 不合并；业务质量门禁和评估信任边界职责不同。
- `canon_analysis` 与 `domain/creation`、`infrastructure/canon` 不合并；文本分析和 Canon 状态权威职责不同。
- `evaluation` 只能通过受控适配访问当前 `pipeline.provenance`，不得形成普通的 `evaluation -> pipeline` 依赖。
- `infra/` 与 `infrastructure/` 的最终收敛方向待专门 census、设计和审查后决定。

## 5. 依赖方向

```text
api / agents / tools
        -> 公开用例或能力入口
        -> orchestration
        -> analysis | authoring | quality | evaluation | canon_analysis | creation
        -> 明确的 domain/port
        -> infrastructure / infra adapter
```

- 编排可以依赖能力的公开入口；能力不得反向依赖编排。
- 业务上下文通过 canonical contract、artifact 或用例入口交互，不直接导入对方内部实现。
- 领域和应用层不得依赖 API、前端、具体模型、文件路径或数据库实现。
- 新增第三方架构工具需要单独授权；当前优先使用仓库已有的 AST 和静态依赖检查。

## 6. 渐进迁移规则

1. 新文件先依据业务 owner 归类；无法归类时暂停，更新设计或建立独立阶段，不创建临时万能目录。
2. 目录迁移必须单独立项，记录 importer、port、cycle、运行时消费者、测试映射、兼容期、删除条件和回滚方法。
3. 同批可迁移的内部消费者直接迁移；facade 只有在 census 证明必要、且有明确 owner 和删除条件时才能创建。
4. 大文件拆分按职责和变化轴进行，先提取类型、合同和纯策略，再迁移 I/O；每步保留公共导入和行为测试。
5. `infra/` 与 `infrastructure/` 不得整体移动或通过目录名猜测归并方案；必须另立收敛批次。
6. `pipeline/provenance.py` 不在当前目录收敛批次中迁移。
7. 迁移失败时封存本批结果，使用新批次和新授权，不覆盖旧结果。

## 7. 当前 MPV-02B 例外

当前 B 批次批准的文件仍按现有路径执行：

- `src/xiaoshuo/pipeline/index_build_worker.py`
- `src/xiaoshuo/pipeline/index_build_events.py`
- `src/xiaoshuo/pipeline/index_build_finalization.py`
- 对应定向测试文件

这是当前批次的受控例外，不代表索引能力的最终目录已经确定，也不授权移动到 `analysis/index/` 或其他新路径。B 批次完成后，索引目录迁移必须另立批次，先完成 importer、公共入口、测试映射和回滚设计。

## 8. 每批结构验收

- 新文件有唯一业务 owner，且能对应既有最终设计中的能力边界。
- 依赖方向没有反向边或隐式全局依赖。
- 当前事实与目标方向没有混写，未把迁移计划当成已完成事实。
- 公共导入、业务数据路径和执行语义未被无授权改变。
- 测试、模型、小说数据、索引和临时工件仍保持各自物理边界。
