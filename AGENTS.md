# AGENTS.md — AI 助手项目约定

> 本文件是各种 AI 助手（Agent）在此仓库工作时的约定指南，不绑定具体产品或模型。

## 项目身份

**番茄小说 AI 辅助创作系统** — 本地 LLM 驱动的网文创作辅助中台。
不是通用写作工具，是量化分析精品小说 → 指导创作的数据管线 + 创作辅助系统。

## 核心约束（不可违反）

1. **零成本运行** — 全部本地，不依赖付费 API（DeepSeek API 仅用于外部审视，非生产依赖）
2. **合规红线** — AI 生成正文须过 S3 质量门禁，作者有最终采用权
3. **不修改 `AI_PROTOCOL.md`** — 除非用户明确确认
4. **不修改 `assets/canon/`** — 设定文件，需用户确认
5. **`config.yaml` 是运行配置 SSOT** — 所有阈值/端口/路径必须在此配置，禁止硬编码；它不是业务状态 SSOT
6. **Windows GBK 兼容** — `print()` 用 `[OK]`/`[FAIL]`，禁止 Unicode 符号
7. **路径用 `pathlib.Path()`** — 禁止字符串拼接
8. **项目产物统一使用 D 盘临时路径** — 默认位于 `D:\tmp\yeyu-ai-a3\<stage>\<run-id>`；未经用户明确授权不得创建 `C:\tmp\yeyu-ai-a3\...` 或其他 C 盘项目产物路径
9. **现有 A4-R1 C 盘历史证据仅允许只读审查** — `C:\tmp\yeyu-ai-a3\r1\20260718-001` 至 `003`；不得移动、删除、覆盖或改写路径
10. **每个实验任务执行前必须 preflight 验证** — 写入目标在 D 盘、精确位于获准 stage/run 路径、run-id 合法、不会写入项目 Git 工作区；C 盘只作为历史证据只读输入
11. **工具自身缓存不属于项目产物** — AI 工具、Windows 或其他工具的缓存、附件与系统临时文件不在此规则范围内

`.codebuddy/` 是现有协作与 IDE 配置目录，未经用户明确授权不得修改、删除、移动或重命名。

## 实验室级架构门禁

1. 遵守根级 [R-001 至 R-004](../.ai/architecture.md)：模型替换成本有界、快速接管、证据优先、跨模型连续开发。
2. 新阶段、大模块、跨模块功能、数据协议、状态机或模型基础设施变化，先在 [`docs/plans/`](docs/plans/README.md) 建立阶段文档；每批完成后立即更新进度与精确下一步。
3. 模型输出只能形成候选，不得直接写入 Canon；作者确认不能只由前端按钮代表。
4. 当前 `world_state` 按 `SimulationState` 管理，不得直接视为 `CanonState`。
5. `domain/creation` 必须保持模型中立，不得依赖具体 Provider、模型、Prompt 或解析器。
6. 当前禁止进行 Repository、API、前端和模型生产接线，直至对应外部研究、ADR 和架构负责人批准完成。
7. 详细执行流程见根级[开发流程](../.ai/development-process.md)与[研究规范](../.ai/research-standard.md)。

## 项目 Skill 边界

1. 根 `.agents/skills/` 的通用 Skill 只提供方法，不承载 xiaoshuo 事实。
2. 根 `yeyu-ai-governance-adapter` 只绑定项目集，不替代本项目 adapter。
3. `xiaoshuo/.agents/skills/` 只放本项目独特 adapter、runner 和项目合同；当前入口为 `xiaoshuo-governance-adapter`。
4. xiaoshuo 的阶段、白名单、模型、配置和工件路径不得写入根级通用 Skill；跨项目共性只有在独立架构审查后才可上提。
5. 面向人的 Skill、注释、错误说明和回执中文优先；英文仅用于代码标识符、路径、协议 token 和必要标准术语。

## 目录结构与渐进迁移

当前真实目录与最终目标目录必须分开记录，统一见项目顶层 [`TARGET-STRUCTURE.md`](TARGET-STRUCTURE.md)。详细能力边界和阶段顺序见 `docs/plans/2026-08-capability-oriented-directory-convergence-design.md`。规则中的 `Current` 只描述已存在且可达的代码，`Target` 只描述未来方向，不得把目标目录当成已经完成。

1. 新文件必须先按目标职责归类；无法归类时暂停并更新目标结构或建立新的阶段计划，不得继续堆入“临时”目录。
2. 目录迁移必须以独立批次进行，先完成 importer、依赖方向、测试、配置和回滚分析，再移动文件；不得在无关业务批次中顺便移动目录。
3. 迁移期间旧路径若必须保留兼容入口，必须在计划中明确 owner、生命周期和删除条件；不得为了迁移方便创建未审查的 facade 或重复实现。
4. 新业务代码依赖方向以已批准的能力导向设计为准：能力入口通过明确用例、合同或端口交互，编排依赖能力公开入口，底层不得反向依赖 API、前端或具体模型。
5. `infra/` 与 `infrastructure/` 当前并存：二者的最终收敛名称和方向尚未裁决，必须先完成 importer、port、cycle 和运行时消费者 census。未经单独迁移授权不得整体移动；新建基础设施文件的归属必须在当前阶段计划中明确，禁止继续无判断地新增同名职责。
6. 生产源码、测试、文档、资源数据、运维脚本和临时工件必须保持物理边界；模型、小说原文、生成索引和运行日志不得因目录重构复制进 Git 代码目录。
7. 目录结构目标是演进约束，不是一次性重构授权。每个新模块只向目标靠拢一个可验证的小步，行为合同和公共导入不因目录美化而改变。

## 需求审视门

用户请求只是输入，不直接等同于最终规格。需求或设计类指令必须先在回复中输出“最终需求描述”，列出真实目标、用户价值、范围、非目标、约束、依赖、风险和验收标准。进入设计前，规划角色必须审查完整性、可行性和边界，明确补充、删除、延期、拆分项；若优化改变目标、范围、方案或验收，或仍有实质歧义，必须等待用户确认。未完成需求优化与确认前不得直接修改业务文件或运行项目活动。

## 工程质量门禁

1. **边界与复用**：优先复用既有领域模型和公共合同；不得复制领域不变量；application 不得泄漏 adapter/infrastructure 细节。
2. **可靠性**：状态边界 fail-closed；并发更新必须显式 expected revision；不得吞没错误或无证据自动重试。
3. **兼容性与依赖**：遵守 `pyproject.toml` 的最低 Python 版本；新依赖须先获批准；不得为便利使用不兼容标准库 API。
4. **可维护性**：公开合同使用不可变 DTO、稳定错误和清晰模块职责；一批只改授权路径。
5. **性能**：先测量再优化；避免无边界全量扫描、隐式 N² 循环和未授权阻塞 I/O；不得用性能理由绕过正确性门禁。
6. **验证**：新增行为有成功、边界、失败路径测试；测试、lint、类型检查无法运行时标记 Deferred，绝不伪称通过。
7. **工件路径**：实验与临时运行产物必须在获准 D 盘路径；生产 source/test 仅能写入获准项目工作区。

## Python 工程规范

1. 业务和管线内部优先使用 `dataclass(frozen=True)`、`Enum`、类型别名和明确的 `Mapping`/`Sequence`；只有 JSON、配置和 API 边界保留字典，进入模块后立即转换为类型化对象。
2. 管线模块按以下职责拆分：`*_contracts.py` 保存 DTO/错误合同，`*_policy.py` 保存无副作用决策，`*_events.py` 只负责事件与工件 I/O，`*_worker.py` 负责进程入口和编排；不得把状态决策、模型调用和文件恢复全部放在入口函数。
3. 失败处理使用稳定错误类型和显式错误码；只捕获能处理的异常，未知异常继续走统一失败边界并保留原始错误，不得用宽泛捕获改变业务结果。
4. `Enum` 和不可变 DTO 用于表达状态和跨模块结果；不要为了形式把所有简单函数包装成类，也不要引入第三方状态机库，除非状态机成为多个模块共享的公共协议并经过单独架构审查。
5. 性能检查优先关注模型编码、磁盘 I/O、序列化和进程边界；普通 `if`/`elif` 分支不是优化目标。循环内日志必须限流，事件写入应避免对完整历史日志反复读写。
6. 文件按职责和依赖方向拆分，不按机械行数拆分；单文件同时承担三种以上独立职责，或状态决策与持久化互相改写时，必须建立拆分计划。拆分后禁止通过反向导入恢复原有耦合。
7. 复杂生命周期修改必须先写状态矩阵和组合故障测试，再实现。连续两轮相同问题未收敛时暂停编码，执行定向 GitHub/官方文档研究并重新评估方案。

## 技术栈入口

具体版本、模型、端口和运行路径属于易变运行事实：以 `pyproject.toml`、前端 `package.json`、`config.yaml` 和当前阶段文档为准；本节只提供稳定技术边界。

| 项 | 值 |
|----|-----|
| Python | Python 项目，最低版本以 `pyproject.toml` 为准 |
| 模型 | 通过模型适配层和 `config.yaml` 配置，不在规则中固定具体模型 |
| GPU | 本地硬件能力以当前运行环境和阶段基线为准 |
| 前端 | Vue 3 + Vite + TypeScript + Pinia |
| 后端 | FastAPI |
| 运行配置 SSOT | `config.yaml` |

## 验证命令

```bash
# 代码检查
scripts\lint.bat

# 单元测试
D:\miniconda3\envs\llm-shared\python.exe -m pytest tests/ -v

# 验证 temperature 默认值
D:\miniconda3\envs\llm-shared\python.exe -c "import inspect; from xiaoshuo.pipeline.llm_batch_score import llm_score_rubric; print(inspect.signature(llm_score_rubric).parameters['temperature'].default)"

# 查看当前 OLS 校准参数
D:\miniconda3\envs\llm-shared\python.exe -c "import json; d=json.load(open('data/reports/末世/calibration/ols_calibration_v815.json',encoding='utf-8')); print(f'OLS: {d[\"intensity\"][\"intercept\"]}+{d[\"intensity\"][\"slope\"]}x')"

# 启动后端服务
D:\miniconda3\envs\llm-shared\python.exe -m xiaoshuo.api.server --port 8089
```

## 关键文件索引

| 文件 | 用途 |
|------|------|
| `NEW_SESSION_HANDOFF.md` | 最新会话交接文档，打开项目先读此文件 |
| `docs/AGENT_ONBOARDING.md` | 5分钟项目速览 |
| `README.md` | 60秒上手 + 九阶段管线 + 目录速查 |
| `config.yaml` | 运行配置唯一来源；不承载业务状态 |
| `AI_PROTOCOL.md` | LLM 行为协议，注入所有 System Prompt |
| `docs/design/01-11-*.md` | 完整设计文档 (11个) |
| `docs/plans/README.md` | 跨会话阶段计划规范与模板 |
| `src/xiaoshuo/pipeline/llm_batch_score.py` | LLM 评分核心 (1557行，待拆分) |
| `data/reports/末世/calibration/ols_calibration_v815.json` | 当前 OLS 校准参数 |

## 当前状态来源

本文件不承载阶段进度、模型评测结果、样本数量或质量分数。当前阶段以根 `.ai/current-focus.md`、项目阶段计划、运行回执和对应 evidence 为准；历史指标不得当作当前事实。

## 审查约定

当作为外部审查者审视此项目时：
1. 先读 `NEW_SESSION_HANDOFF.md` 了解最新状态
2. 再读 `docs/AGENT_ONBOARDING.md` 获取速览
3. 设计文档在 `docs/design/` 下，按需阅读
4. 统计验证数据在 `data/reports/末世/` 下
5. **不要修改代码**，除非用户明确要求
6. 审查报告默认写到 `D:\tmp\yeyu-ai-a3\audits\<stage>\<run-id>` 或用户明确指定的外部目录；不得写入项目工作区
