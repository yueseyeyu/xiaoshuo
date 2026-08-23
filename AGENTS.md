# AGENTS.md — Codex/AI Agent 项目约定

> 本文件是 AI Agent（Codex/CatPaw/其他）在此仓库工作时的约定指南。

## 项目身份

**番茄小说 AI 辅助创作系统** (v8.15) — 本地 LLM 驱动的网文创作辅助中台。
不是通用写作工具，是量化分析精品小说 → 指导创作的数据管线 + 创作辅助系统。

## 核心约束（不可违反）

1. **零成本运行** — 全部本地，不依赖付费 API（DeepSeek API 仅用于外部审视，非生产依赖）
2. **合规红线** — AI 生成正文须过 S3 质量门禁，作者有最终采用权
3. **不修改 `AI_PROTOCOL.md`** — 除非用户明确确认
4. **不修改 `assets/canon/`** — 设定文件，需用户确认
5. **不修改 `.codebuddy/`** — CodeBuddy IDE 专属配置
6. **`config.yaml` 是运行配置 SSOT** — 所有阈值/端口/路径必须在此配置，禁止硬编码；它不是业务状态 SSOT
7. **Windows GBK 兼容** — `print()` 用 `[OK]`/`[FAIL]`，禁止 Unicode 符号
8. **路径用 `pathlib.Path()`** — 禁止字符串拼接
9. **项目产物统一使用 D 盘临时路径** — 默认位于 `D:\tmp\yeyu-ai-a3\<stage>\<run-id>`；未经用户明确授权不得创建 `C:\tmp\yeyu-ai-a3\...` 或其他 C 盘项目产物路径
10. **现有 A4-R1 C 盘历史证据仅允许只读审查** — `C:\tmp\yeyu-ai-a3\r1\20260718-001` 至 `003`；不得移动、删除、覆盖或改写路径
11. **每个实验任务执行前必须 preflight 验证** — 写入目标在 D 盘、精确位于获准 stage/run 路径、run-id 合法、不会写入项目 Git 工作区；C 盘只作为历史证据只读输入
12. **工具自身缓存不属于项目产物** — Codex、Windows 或其他工具的缓存、附件与系统临时文件不在此规则范围内

## 实验室级架构门禁

1. 遵守根级 [R-001 至 R-004](../.ai/architecture.md)：模型替换成本有界、快速接管、证据优先、跨模型连续开发。
2. 新阶段、大模块、跨模块功能、数据协议、状态机或模型基础设施变化，先在 [`docs/plans/`](docs/plans/README.md) 建立阶段文档；每批完成后立即更新进度与精确下一步。
3. 模型输出只能形成候选，不得直接写入 Canon；作者确认不能只由前端按钮代表。
4. 当前 `world_state` 按 `SimulationState` 管理，不得直接视为 `CanonState`。
5. `domain/creation` 必须保持模型中立，不得依赖具体 Provider、模型、Prompt 或解析器。
6. 当前禁止进行 Repository、API、前端和模型生产接线，直至对应外部研究、ADR 和架构负责人批准完成。
7. 详细执行流程见根级[开发流程](../.ai/development-process.md)与[研究规范](../.ai/research-standard.md)。

## 工程质量门禁

1. **边界与复用**：优先复用既有领域模型和公共合同；不得复制领域不变量；application 不得泄漏 adapter/infrastructure 细节。
2. **可靠性**：状态边界 fail-closed；并发更新必须显式 expected revision；不得吞没错误或无证据自动重试。
3. **兼容性与依赖**：遵守 `pyproject.toml` 的最低 Python 版本；新依赖须先获批准；不得为便利使用不兼容标准库 API。
4. **可维护性**：公开合同使用不可变 DTO、稳定错误和清晰模块职责；一批只改授权路径。
5. **性能**：先测量再优化；避免无边界全量扫描、隐式 N² 循环和未授权阻塞 I/O；不得用性能理由绕过正确性门禁。
6. **验证**：新增行为有成功、边界、失败路径测试；测试、lint、类型检查无法运行时标记 Deferred，绝不伪称通过。
7. **工件路径**：实验与临时运行产物必须在获准 D 盘路径；生产 source/test 仅能写入获准项目工作区。

## 技术栈

| 项 | 值 |
|----|-----|
| Python 环境 | `D:\miniconda3\envs\llm-shared\python.exe` |
| 本地模型 | Qwen3.5-9B Q4_K_M (端口 8000) |
| 交叉模型 | DeepSeek-R1-0528-Qwen3-8B (端口 8002) |
| GPU | RTX 5060 8GB |
| 前端 | Vue 3 + Vite + TypeScript + Pinia |
| 后端 | FastAPI 端口 8089 |
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

## 当前状态 (v8.15)

- 综合可信度: 72/100 (DeepSeek 最终评审)
- LLM 评分管线: 12步全部完成, 33本/5472章
- OLS 校准: intensity 3.466+0.361x, retention 4.905+0.261x
- 温度: 0.0 (消除 run-to-run 方差)
- 待解决: 单一标注者(-15分), N=47小样本(-10分)

## 审查约定

当作为外部审查者审视此项目时：
1. 先读 `NEW_SESSION_HANDOFF.md` 了解最新状态
2. 再读 `docs/AGENT_ONBOARDING.md` 获取速览
3. 设计文档在 `docs/design/` 下，按需阅读
4. 统计验证数据在 `data/reports/末世/` 下
5. **不要修改代码**，除非用户明确要求
6. 审查报告写到 `data/reports/末世/` 目录下
