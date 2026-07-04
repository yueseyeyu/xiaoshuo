# 前端框架重构审视报告

> 对比基准：最近一次提交 `851c691`（feat: v8.5 快速开始五步法+拆书多书对比/八步法+风格DNA/平台合规+代码修复）
> 审视对象：当前工作区未提交变更（Vue 3 + Vite + TS 新前端 + WSE 后端扩展）
> 说明：本报告仅做分析，不修改代码。

---

## 一、总体结论

**重构已完成约 75%，核心框架与新功能模块已落地，但尚未达到可合并状态。**

- 前端已从原生 JS（`prototype/`）迁移到 **Vue 3 + Vite + TypeScript + Pinia + Vue Router**；
- 后端已完成配套 API 扩展，新增「世界推演引擎（WSE）」完整链路；
- 创作管线（`creative_context.py` / `outline_builder.py` / `contract_chain.py` / `rp_simulator.py`）已接入 WSE 运行时状态；
- **当前阻塞项**：新前端无法通过生产构建（TypeScript 配置废弃警告）、后端默认仍服务旧前端、单元测试路径失效。

---

## 二、前端重构完成度

### 2.1 框架与技术栈

| 维度 | 旧前端 `prototype/` | 新前端 `frontend/` | 状态 |
|------|---------------------|--------------------|------|
| 框架 | 原生 JS + 手工 DOM | Vue 3 Composition API | ✅ 已迁移 |
| 构建 | 无构建，直接 HTML | Vite + `vue-tsc` | ⚠️ 构建失败 |
| 状态管理 | `js/state.js`（自定义 EventEmitter） | Pinia（`stores/`） | ✅ 已迁移 |
| 路由 | 多页/锚点切换 | Vue Router（`router/index.ts`） | ✅ 已迁移 |
| 样式 | `styles.css` 单文件 | `style.css` + Scoped Vue SFC | ✅ 已迁移 |
| HTTP 封装 | `js/api.js` | `api/*.ts` 按领域拆分 | ✅ 已迁移 |
| 图表 | ECharts（部分） | Cytoscape（WSE 关系图） | ✅ 已新增 |

### 2.2 页面/视图映射

| 旧前端页面/组件 | 新前端视图 | 覆盖情况 |
|-----------------|------------|----------|
| `dashboard.js` | `DashboardView.vue` | ✅ 工作台、KPI、任务、模型状态 |
| `library.js` | `LibraryView.vue` | ✅ 书库列表、筛选、导入、批量拆书 |
| `disassembly.js` | `DisassemblyView.vue` | ✅ 拆书任务、书籍选择 |
| `reports.js` | `ReportsView.vue` | ✅ 报告概览 |
| `writing.js` + `goal-gate.js` + `author-mind.js` + `style-calibrate.js` | `WritingView.vue` | ✅ 写作指令、S3 门禁、作者预设、风格校准 |
| `design.js` | `DesignView.vue` | ✅ 项目设计、模型状态 |
| `prompt-manager.js` | `SettingsView.vue` | ✅ 提示词模板管理已整合到设置页 |
| `settings.js` | `SettingsView.vue` | ✅ 设置面板、品牌色、快捷键 |
| `logs.js` | `LogsView.vue` | ✅ 日志查询、筛选、分页 |
| `hardware.js` | `TopBar` / `DashboardView` | ✅ 硬件/模型状态已整合 |
| `deconstruction-viewer.js`（章节级拆书） | 未找到独立视图 | ⚠️ 可能合并到拆书页，需确认 |
| `tasks.js`（独立任务看板） | 未找到独立视图 | ⚠️ 已弱化为 Dashboard 中的任务列表 |

### 2.3 API 调用覆盖对比

旧前端 `prototype/js` 共调用约 **30+ 个接口**。新前端 `frontend/src/api` 覆盖情况如下：

| 接口领域 | 已覆盖 | 缺失/未确认 |
|----------|--------|-------------|
| 系统/模型 | `/api/config`, `/api/progress`, `/api/hardware`, `/api/model/status`, `/api/model/start`, `/api/model/stop`, `/api/start`, `/api/stop` | `/api/status`, `/api/model-info`, `/api/startup-status` |
| 书库/拆书 | `/api/books`, `/api/disassembly/books`, `/api/disassembly/book`, `/api/tasks`, `/api/task` | `/api/search`（场景搜索） |
| 报告/创作 | `/api/reports/overview`, `/api/instructions`, `/api/creative/*`, `/api/style/*` | `/api/guidance`, `/api/techniques`, `/api/skeleton`, `/api/blueprint` |
| 项目/WSE | `/api/projects/*`, `/api/projects/{id}/world_state`, `/api/projects/{id}/simulate`, `/api/projects/{id}/world_state/export_outline` | — |
| 日志/诊断 | `/api/logs`, `/api/logs/dates` | `/api/logs/operations`, `/api/diagnosis` |
| 合规 | — | `/api/compliance/scan` |

> 注：缺失接口多为旧前端中已存在但新前端尚未接入的辅助接口，不一定会阻塞主流程，但会导致功能回退。

---

## 三、后端适配完成度

### 3.1 已新增的模块

| 文件 | 职责 | 状态 |
|------|------|------|
| `src/xiaoshuo/api/routes_world.py` | WSE 路由（势力/角色/世界状态/推演/快照/差异/导出大纲） | ✅ 已注册到 `server.py` |
| `src/xiaoshuo/api/services/simulation_engine.py` | 混合推演引擎（规则 + LLM 关键决策） | ✅ 已实现 SSE 流式输出 |
| `src/xiaoshuo/api/services/world_state_service.py` | 世界状态 CRUD、快照、差异计算 | ✅ 已实现 |
| `assets/canon/simulation_rules.yaml` | 推演规则、行动权重、LLM 触发条件 | ✅ 已新增 |

### 3.2 已修改的模块

| 文件 | 变更要点 |
|------|----------|
| `src/xiaoshuo/api/server.py` | 注册 `creative_router`、`world_router`；静态目录仍默认指向 `prototype` |
| `src/xiaoshuo/api/services/project_service.py` | 项目 CRUD、示例项目、章节/角色/势力/世界观/粗纲细纲管理 |
| `src/xiaoshuo/agents/creative_context.py` | 新增 `build_world_simulation_context()`，将 WSE 状态注入创作上下文 |
| `src/xiaoshuo/agents/outline_builder.py` | `build_chapter_blueprint()` 新增 `world_state_context` 参数 |
| `src/xiaoshuo/pipeline/contract_chain.py` | `ChapterCommit`/`DebtBoard` 支持势力状态变更与势力债务 |
| `src/xiaoshuo/pipeline/canon/rp_simulator.py` | 角色扮演模拟支持基于 WSE 运行时状态生成 prompt |

---

## 四、关键问题与阻塞项

### 4.1 ❌ 阻塞：新前端无法构建生产包

```
> vue-tsc -b && vite build
tsconfig.app.json(7,5): error TS5101: Option 'baseUrl' is deprecated and will stop functioning in TypeScript 7.0.
Specify compilerOption '"ignoreDeprecations": "6.0"' to silence this error.
```

**影响**：`npm run build` 直接失败，无法生成 `frontend/dist`。
**根因**：`frontend/tsconfig.app.json` 中 `baseUrl` 在 TypeScript 6+ 被标记为废弃。
**建议**：添加 `"ignoreDeprecations": "6.0"` 到 `tsconfig.app.json` 的 `compilerOptions`，或迁移到 `@vue/tsconfig` 推荐的路径别名方案。

### 4.2 ❌ 阻塞：后端仍默认服务旧前端

`config.yaml` 中：

```yaml
api_server:
  static_dir: "prototype"   # 仍为旧前端
```

`server.py` 中 `_STATIC_DIR` 从 `config.yaml` 读取，且 `/legacy` 也挂载了 `prototype`。

**影响**：即使修复构建并生成 `frontend/dist`，后端也不会自动服务新前端，除非手动修改 `config.yaml` 的 `static_dir` 为 `frontend/dist`（或新增独立挂载）。

### 4.3 ⚠️ 测试路径失效

- `python -m pytest tests/` 失败：`No module named pytest`；
- `python -m unittest discover tests` 失败：测试文件使用 `from book_processor import ...` 等旧相对导入，未通过 `src/xiaoshuo` 包路径加载。

**注意**：`scripts\lint.bat` 内置的 self-test 运行正常（51 passed / 0 failed），但独立的单元测试套件当前不可直接运行。

### 4.4 ⚠️ 版本号未同步

`frontend/package.json`：

```json
{
  "name": "frontend",
  "version": "0.0.0"
}
```

项目 SSOT 版本号在 `src/xiaoshuo/__init__.py::__version__`（根据项目记忆），新前端未同步。

### 4.5 ⚠️ 代码规范问题

| 文件 | 问题 | 规则依据 |
|------|------|----------|
| `simulation_engine.py` | 第 347、351、411、416 行在函数内部 `import asyncio` / `import logging` / `import yaml` | `.trae/rules/02-code-conventions.md`：禁止在函数内部 import |
| `simulation_engine.py` | `_run_llm_decision()` 中 `except Exception` 未记录具体异常 | 项目规则：异常处理需使用具体类型并记录日志 |
| `project_service.py` | `_PROJECT_DIR` 使用 `Path(__file__).resolve().parents[4] / "data" / "projects"` 硬编码相对层级 | SSOT 原则：路径应从 `config.yaml` 读取 |
| `project_service.py` | 函数内 `import uuid`（第 26 行） | 禁止在函数内部 import |

### 4.6 ⚠️ 功能完整性风险

1. **场景搜索缺失**：新前端未调用 `/api/search`，旧前端写作页依赖此接口做参考场景检索；
2. **诊断入口缺失**：`/api/diagnosis` 未在新前端找到调用点；
3. **合规扫描入口缺失**：`/api/compliance/scan` 未在新前端找到调用点；
4. **Settings 仅本地存储**：设置修改写入 `localStorage`，未同步回后端 `config.yaml`（这是历史已知问题，在新前端中延续）。

### 4.7 ⚠️ 类型与接口一致性

- `frontend/src/types/index.ts` 定义了 WSE 核心类型，但 `frontend/src/api/project.ts` 引入的 `ProjectSkeleton`、`Chapter` 等类型与 `types/index.ts` 不完全一致，存在潜在的 TS 类型不一致风险；
- `world.ts` 中 `SimulationEvent` 的字段定义需与后端 `routes_world.py` 返回的事件结构对齐。

---

## 五、验证结果

| 检查项 | 命令/方式 | 结果 |
|--------|-----------|------|
| 后端语法检查 | `scripts\lint.bat` | ✅ 51 passed / 0 failed |
| 后端单元测试 | `python -m pytest tests/` | ❌ pytest 未安装 |
| 后端单元测试 | `python -m unittest discover tests` | ❌ 模块导入路径错误 |
| 前端构建 | `npm run build` | ❌ TS5101 `baseUrl` 废弃错误 |
| 前端类型检查 | `npx vue-tsc --noEmit` | ✅ 无额外类型错误（仅配置警告阻塞构建） |
| Git 状态 | `git status` | 6 个修改文件 + 6 个未跟踪文件 |

---

## 六、结论与建议

### 6.1 必须先修复才能合并的项

1. **修复前端构建**：在 `frontend/tsconfig.app.json` 添加 `"ignoreDeprecations": "6.0"`，确保 `npm run build` 通过；
2. **配置后端服务新前端**：将 `config.yaml` 的 `api_server.static_dir` 改为 `frontend/dist`，或让 `server.py` 同时兼容 `prototype` 与 `frontend`；
3. **同步版本号**：将 `frontend/package.json` 的 `version` 与 `src/xiaoshuo/__init__.py::__version__` 对齐；
4. **修复测试路径**：统一测试入口，或更新 `tests/` 中的导入以使用 `src/xiaoshuo` 绝对包路径。

### 6.2 强烈建议修复的项

1. 将 `simulation_engine.py` 和 `project_service.py` 中的函数内 import 移到文件顶部；
2. 将 `project_service.py` 的 `_PROJECT_DIR` 改为从 `config_manager.get_config()` 读取；
3. 在 `simulation_engine.py` 的 LLM 调用异常处补充日志记录；
4. 补齐新前端对 `/api/search`、`/api/diagnosis`、`/api/compliance/scan` 的调用，避免功能回退。

### 6.3 重构完成度量化

| 维度 | 完成度 | 说明 |
|------|--------|------|
| 前端框架迁移 | 90% | 技术栈与核心视图已迁移，仅构建配置需修复 |
| 前端功能覆盖 | 80% | 主流程覆盖，部分辅助接口未接入 |
| 后端 API 适配 | 85% | 新增 WSE 与项目 API，旧接口兼容 |
| 创作管线集成 | 85% | WSE 已注入 outline/blueprint/contract/rp_simulator |
| 可构建/可测试 | 50% | 前端构建失败，独立测试入口失效 |
| **综合完成度** | **≈ 75%** | 核心就绪，但尚未达到可合并状态 |

---

*报告生成时间：2026-07-02*
