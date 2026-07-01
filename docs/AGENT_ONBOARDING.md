# 番茄小说 AI 创作辅助系统 v7.5 — Agent 速览

> 任何 AI Agent 打开项目后，先读此文件。5 分钟秒懂全局，省 80% 上下文 Token。

---

## 一句话定位

**网文作者的工具箱**：AI 拆解爆款小说（节奏/爽点/冲突），给出创作建议。正文 100% 手写，AI 只做分析，不代笔。

---

## 技术栈速查

| 项 | 值 |
|----|-----|
| 环境 | `conda llm-shared` (D:\miniconda3\envs\llm-shared) |
| 本地模型 | Qwen3.5-9B Q4_K_M (端口 8000, n_ctx=8192) |
| 云端模型 | DeepSeek V4-Flash / V4-Pro |
| GPU | RTX 5060 8GB |
| OS | Windows 11 |
| 前端 | 原生 JS + CSS（无框架），端口 8090 |

---

## 目录速查

### 代码层

| 目录 | 用途 | 入口 |
|------|------|------|
| `src/xiaoshuo/pipeline/` | 拆书管线核心（9 阶段流水线） | `analyze_all.py` 一键全量 |
| `src/xiaoshuo/agents/` | LLM 代理（路由/状态机/世界观/大纲/交叉评审） | `model_orchestrator.py` |
| `src/xiaoshuo/infra/` | 基础设施（配置管理/硬件守护/日志/管线状态） | `config_manager.py` |
| `src/xiaoshuo/tools/` | 独立工具（校准/去重/评分对比） | 各文件独立运行 |
| `analysis/` | 数据分析管线（入库→节奏→评分→报告） | - |
| `scripts/` | 运维脚本（启动模型/lint/编码转换） | - |
| `frontend/` | 前端仪表盘（书籍管理/进度/评分） | `index.html` |
| `设计方案/` | 前端设计方案归档与对比预览入口 | `index.html` |
| `novel.py` | 项目总入口 CLI | - |

---

## 9 阶段拆书管线

`analyze_all.py` 按以下顺序执行（Group 2 内并行）：

```
Group 1 (顺序):  book_processor ─→ [llm_labeler*]
                       │
Group 2 (并行):  ┌─────┼────────────┐
                 ↓     ↓            ↓
          rhythm_  llm_batch_  recursive_
          analyzer  score*     summarize
                 │     │            │
Group 3 (顺序):  └─────┴────────────┘
                       ↓
                 [rhythm_auditor] ─→ genre_synthesizer
                       ↓
                 [score_auditor] ─→ quality_gate ─→ creative_bridge
                       ↓
                 cross_book_synthesis ─→ technique_store ─→ writing_instructions
```

| # | 阶段 | 文件 | 职责 |
|---|------|------|------|
| 1 | 入库处理 | `book_processor.py` | TXT 清洗、元数据提取、存入 `data/raw/novels/` |
| 2 | 拆书节奏分析 | `rhythm_analyzer.py` | 逐章 30+ 正则匹配爽点/钩子/冲突，输出 CSV |
| 3 | LLM 批量评分* | `llm_batch_score.py` | LLM 按 rubric 逐章商业化打分（需 `--with-llm`） |
| 4 | 题材评分合成 | `genre_synthesizer.py` | 多维度评分融合 + Bayesian Stacking + Borda 排名 |
| 5 | 品质关卡 | `quality_gate.py` | 质量门槛检查（评分/数据完整性） |
| 6 | 创作桥接 | `creative_bridge.py` | 拆书数据 → 创作指导 JSON |
| 7 | 递归摘要 | `recursive_summarize.py` | 章节 → 卷 → 全书三级摘要（checkpoint 断点续传） |
| 8 | 跨书合成 | `cross_book_synthesis.py` | 多书对比 + 技法提炼 |
| 9 | 写作指令 | `writing_instructions.py` | 逐章创作建议输出 |

> `*` = 可选阶段，需 `--with-llm` 参数启用。`[]` = 质检阶段，失败不阻断管线。

注意：AGENT_ONBOARDING.md 和 .trae/rules/ 提到"6 阶段"是旧版分类，当前实际是 **9 阶段流水线**，以 `analyze_all.py` 为准。

---

## 核心模块职责

### 数据层

| 目录 | 内容 | 格式 |
|------|------|------|
| `data/raw/novels/{genre}/` | 原始小说 TXT，**不可修改** | .txt |
| `data/processed/{genre}/rhythm/` | 节奏分析结果（逐章正则匹配） | CSV |
| `data/processed/{genre}/scores/` | LLM 商业化打分数据 | CSV |
| `data/processed/{genre}/labels/` | LLM 标签标注数据 | CSV |
| `data/processed/{genre}/quality/` | 质量审计/评分汇总/技术卡片 | JSON |
| `data/processed/{genre}/summaries/` | 拆书中间产物（checkpoint/递归摘要） | JSON |
| `data/logs/` | 运行日志（progress_server/analyze_all） | .log |

### 资产层

| 目录 | 用途 |
|------|------|
| `assets/canon/` | 设定文件，**不可修改**（需用户确认） |
| `assets/library/` | 创作素材库 |
| `assets/outline/` | 大纲文件 |
| `assets/voice/` | 风格/语调文件 |

---

## 关键字段映射

### checkpoint.json 结构

```json
{
  "l1_data": {},       // L1 完成状态（dict，key 是分组范围）
  "l1_total": 30,      // L1 总分组数
  "l2_done": [],       // L2 已完成卷级合成列表（如 ["1-5", "6-10"]）
  "l3_done": false,    // L3 全书分析是否完成
  "failed_batches": [] // 失败批次
}
```

- `l1_done` = `len(l1_data)` → 逐组拆分进度
- `l2_done` = `len(l2_done)` → 卷级合成进度（每 5 个 L1 组 = 1 个 L2 卷）
- `l2_total` = `(l1_total + 4) // 5` → 卷级总分组数
- `is_complete` = `l1_ok && l2_ok && l3_ok && output_valid`

---

## 核心约束

1. **禁止修改 `.codebuddy/` 目录** — 那是 CodeBuddy IDE 的专属配置
2. **禁止生成 >30 字连续小说正文** — 100% 手写，AI 仅分析/建议
3. **所有阈值/端口/路径 → `config.yaml`** — SSOT 单一事实源，代码动态读取
4. **print() 禁止 Unicode** — Windows GBK 崩溃，用 `[OK]` `[FAIL]`
5. **所有路径用 `pathlib.Path()`** — 禁止字符串拼接
6. **import 全部放文件顶部** — 禁止函数内部 import
7. **修改 .py 或 config.yaml 后 → 运行 `scripts\lint.bat`**

---

## 快速命令

```bash
scripts\start_model.bat              # 启动 Qwen3.5-9B
scripts\lint.bat                      # 代码检查（py_compile + import test + self-test）
python scripts/progress_server.py     # 启动前端仪表盘（端口 8090）
python -m src.xiaoshuo.pipeline.analyze_all --genre 末世  # 末世题材全量拆书
python novel.py analyze --genre 末世  # 末世题材分析报告
```

---

## 陷阱清单

| 陷阱 | 说明 |
|------|------|
| VRAM 阈值 | `vram_red: 8000MB`，已为模型基线预留 ~6GB |
| 中文路径 | PowerShell 创建中文目录会失败，用 Python 脚本 |
| 不修改 `AI_PROTOCOL.md` | 需用户确认 |
| 不修改 `assets/canon/` | 设定文件，需用户确认 |
| CodeBuddy Skill 触发词 | 审视/穷举搜索/进化粗纲/通用进化 → Trae 不支持，引导用户在 CodeBuddy 执行 |
| `__pycache__`/`.pytest_cache` | 可删，自动重建 |
| `.archive/` | 历史审计报告，保留 |
| `.uploads/` | 前端上传缓存，可安全清理 |

---

## 当前状态

- 33 本入库（17 末世精品 + 16 其他）
- 商业评分融合：Bayesian Stacking + Spearman 0.66
- 全模块 py_compile ✅ | 45/45 单元测试 ✅
- 9 阶段管线全通 ✅