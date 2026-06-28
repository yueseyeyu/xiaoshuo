# 番茄小说 AI 辅助创作系统 v7.7

## 60秒快速上手

```bash
# 一键全量分析
python novel.py analyze --genre 末世

# 含LLM增强（需启动模型）
scripts\start_model.bat
python novel.py analyze --genre 末世 --with-llm

# 全题材
python novel.py analyze --all

# 意图→建议
python novel.py intent --text "这章太拖了"

# 逐章写作指令
python analysis/writing_instructions.py

# Pro API 类型指导（需 secrets.yaml 配置 deepseek.api_key）
python -m xiaoshuo.pipeline.scoring.pro_genre_guide --genre 末世
python -m xiaoshuo.pipeline.scoring.pro_genre_guide --all --force

# 启动可视化拆书监控面板
scripts\progress_server.bat
# 然后浏览器打开 http://localhost:8090
```
> 详见 `python novel.py --help`

## 项目目标

**近期**: 任一题材有足够精品书 → 量化指导新人写出高质量爆款。**中期**: 精品库 + 作者交互反馈 → AI 理解作者风格 → 保证下限。**终局**: 精品库持续蒸馏 + 作者风格涌现 → AI 拥有独立风格 → 写出不被识别为AI的原创小说。

核心原则：**正文100%手写，AI仅做分析/建议/审阅**，禁止生成>30字连续小说正文。**所有建议必须有精品书量化数据支撑**。

> 完整愿景见 [DESIGN.md §15](DESIGN.md): 十阶段闭环设计，标注已实现/已设计/缺失环节。

## 十阶段愿景全景

```
Part A 数据管线: ① 精品书入库 → ② 质量门禁 → ③ 拆书排名 → ④ 商业打分 → ⑤ 创作指导  [✅ 全通]
Part B 骨架生成: ⑥ 作者出点子 → AI生成世界观+粗纲+细纲+角色+势力                       [⚠️ 已编码未接通]
Part C 作者手写: ⑦ 在骨架上写正文血肉                                               [⚠️ 已编码未接通]
Part D 对比保障: ⑧ 蒸馏精品→AI对照版→双文对比  ⑨ 多维评审(节奏/情节/人物)            [⚠️ 部分编码]
Part E 风格进化: ⑩ 交互反馈提取作者风格  ⑪ 蒸馏进化→AI辅助高质量小说              [❌ 完全缺失]
```

## 九阶段管线 (v7.7)

| 阶段 | 模块 | 干什么 | 并行 |
|:---:|------|------|:---:|
| ① 入库 | `book_processor` | 过滤低质量（残缺/乱码/无章节/低字数）→ 按题材分类 | - |
| ② 拆书 | `rhythm_analyzer` | 逐章 40+ 指标：18 类爽点/钩子/冲突/节奏/可读性/情绪/即时爽延迟爽 | Group 2 |
| ③ 评分 | `genre_synthesizer` | 商业评分（拆书三件套+情感弧）+ Bootstrap CI + Borda排名 | - |
| ④ 关卡 | `quality_gate` | 品质门禁（最低章节数/零钩子连续/最低商业分） | - |
| ⑤ 桥接 | `creative_bridge` | 精品数据 → 8维创作指导 | - |
| ⑥ 摘要 | `recursive_summarize` | L1章→L2卷→L3全书递归摘要（2路并发） | Group 2 |
| ⑦ 跨书 | `cross_book_synthesis` | 跨书技法合成 + 写作技法总纲 | - |
| ⑧ 技法 | `technique_store` | 技法卡片提取 | - |
| ⑨ 指导 | `writing_instructions` | 逐章写作指令 | - |

> v7.7 新增：拆书指标从 35+ 升至 40+（18 类爽点 + 即时爽/延迟爽标签），`novel_index` 提供全书级记忆检索。

## 双模型交叉审查 (v7.6)

系统配备**两枚本地 LLM**，通过 `model_orchestrator.swap_to()` 顺序切换，解决 8GB VRAM 下单 GPU 部署限制：

| 模型 | 量化 | 显存 | 端口 | 职责 |
|------|------|------|:----:|------|
| **Qwen3.5-9B** (主模型) | Q4_K_M | ~6.2GB | 8000 | S1/S3 全面审查、路由默认目标 |
| **DeepSeek-R1-0528-Qwen3-8B** (交叉模型) | Q4_K_M | ~5.9GB | 8002 | Phase 2 专长维度交叉标注（Naming/Quantity/CharKnowledge） |

审查流程（`agents/cross_review.py`）：

```
Phase 1: Qwen3.5-9B 全面审查 (S3_logic_cop/S3_editor/S3_qc)
    ↓ swap_to("logic_cop_candidate") — 停主模型，启交叉模型
Phase 2: DeepSeek-R1-0528 专长维度交叉标注 (S3_cross_check)
    ↓ swap_to("main_model") — 切回主模型
Phase 3: 合并报告 → has_additions 标记交叉发现
```

切换开销约 2-3 秒（模型已在后台保持加载）。`swap_to()` 内置健康检查与自动降级：交叉模型不可用时静默回退到单模型模式。

### S3 评审角色深层模板 (v7.6)

三个评审角色的 `TASK_TEMPLATES` 从方向性提示升级为**可执行的审查标准**：

| 角色 | 升级内容 |
|------|---------|
| **S3_logic_cop** | 6 类判据（时间线/能力/物品/因果/世界观/叙事捷径）+ 典型错误案例 + 严格 JSON schema（verdict:PASS/WARNING/BLOCK） |
| **S3_editor** | 4 维度评分锚点（节奏/爽点/钩子/代入感 1-10 分）+ 末世题材关注点 + 结构化输出 |
| **S3_qc** | 16 个 AI 指纹词 + 句法模式重复阈值 + 风格漂移三指标（句长/用词/情感密度），阈值取自 config.yaml detection.layers |

所有阈值配置于 `config.yaml → detection.layers → ai_word_density` / `style_drift_detection`，无需修改代码。`skill_loader.py` 的 Prefix Cache 机制确保深层模板不额外增加推理开销。

## Agent 结构化记忆系统 (v7.6)

基于"行为回溯备忘录"模式 — 用 SQLite + 精准 Tag 替代复杂 RAG/知识图谱。**零额外依赖**（Python 内置 sqlite3）。

### 记忆四维模型

每次关键任务完成后自动生成一张卡片：

| 维度 | 说明 |
|------|------|
| **Goal** (目标) | 本次任务的具体目标 |
| **Solution** (方案) | 最终采用的正确解决方案 |
| **Result** (结果) | 任务执行的最终结果 |
| **Pain Point** (痛点) | 过程中遇到的错误或难点 |

### 存储与检索

- **存储**: `memory/memory.db` (SQLite 单文件，随项目迁移)
- **检索**: 精准 Tag 匹配 (`query_by_tags`)，不做向量语义搜索
- **导出**: `memory/memory_export/` 目录，每张卡片独立 Markdown 文件（Obsidian 友好）

### 触发时机

| 触发点 | 来源标记 | 自动 Tag |
|--------|---------|---------|
| S4 检测全通过 + 人工确认 | `s4_pass` | 追加 `成功经验` |
| S4 检测 FATAL | `s4_fail` | 追加 `失败案例`, `待复盘` |
| 书籍拆书完成 | `pipeline` | 书名, `拆书完成` |
| 手动添加 | `manual` | 用户自定义 |
| 系统升级/模型切换 | `pipeline` | `迁移`, `v7.5` |

### 对抗记忆污染

S4 全通过 + 人工确认才记为"成功经验"，FATAL 自动标记"失败案例"——失败与成功**不会混淆**。

### CLI 用法

```bash
# 添加卡片
python novel.py memory add --goal "拆书《诡秘之主》" --solution "rhythm_analyzer v10" --result "1.2MB报告" --pain-point "800章爽点漏检" --tags "拆书,诡秘之主,爽点漏检"

# 按标签检索
python novel.py memory query --tags "拆书,爽点漏检"

# 全文搜索
python novel.py memory search --keyword "漏检"

# 列出最近卡片
python novel.py memory list

# 导出 Markdown
python novel.py memory export
```

### 前端设计方案预览

项目前端采用独立的设计方案归档与对比机制：

```bash
# 启动设计方案对比预览服务器（端口 8080）
cd 设计方案
python -m http.server 8080
```

浏览器访问：

| 地址 | 内容 |
|------|------|
| `http://localhost:8080/` | 设计方案对比入口（旧版 V1 / 新版 v2.1） |
| `http://localhost:8080/设计归档_20250621_V1/index.html` | 旧版玻璃拟态工作站 |
| `http://localhost:8080/新设计开发_20250621/src/index.html` | 新版 Linear 风格创作中心 |

设计方案目录结构：

```
设计方案/
├── index.html                        # 对比预览入口
├── 设计归档_20250621_V1/              # 旧版方案（ glassmorphism 风格）
│   ├── index.html
│   ├── library_data.json
│   └── 版本说明.md
├── 新设计开发_20250621/               # 新版方案（Linear/Cursor 风格）
│   ├── src/index.html                # 新版实现
│   ├── research/行业设计调研报告.md
│   └── ... 测试报告与设计稿文档
```

新版 v2.1 核心特性：

- 可折叠侧边栏 + `Ctrl+K` 命令面板
- 列表详情抽屉 + 键盘 Enter 触发
- 写作区 localStorage 自动保存
- Indigo / Ocean 双主题 + 减少动画
- Agent 进度模拟 + 硬件状态更新
- 响应式布局 + 移动端抽屉菜单

### v11 新增功能

| 功能 | 模块 | 说明 |
|------|------|------|
| 章节级版本化缓存 | `rhythm_analyzer` | SHA-256 章节哈希 + `.version` 文件，支持增量重分析 |
| 反套路信号检测 | `rhythm_analyzer` | 正则识别"不想变强/拒绝系统/躺平"等 2026 市场趋势信号 |
| 情绪价值检测 | `rhythm_analyzer` | 情绪强度(valence) + 情绪透支(burnout) 信号 |
| Pro API 类型指导 | `pro_genre_guide` | 聚合题材数据 → DeepSeek API → Markdown 写作指导报告 |
| L1 并发摘要 | `recursive_summarize` | ThreadPoolExecutor 2路并发，L1 摘要时间减半 |
| SSOT API 配置 | `config_manager` | `get_deepseek_config()` 公共函数，消除跨模块重复 |

| 功能 | 状态 |
|------|:---:|
| ①-⑨ 全管线 | ✅ |
| v11 章节级缓存 | ✅ |
| v11 反套路/情绪检测 | ✅ |
| v11 Pro API 类型指导 | ✅ |
| **v7.6 Canon 设定管理** | ✅ |
| **v7.6 章节节拍检测** | ✅ |
| **v7.6 RP 角色入戏推演** | ✅ |
| **v7.6 大纲/正文一致性检查** | ✅ |
| **v7.6 章节分区加权评分** | ✅ |
| ⑦ 风格蒸馏(LoRA) | 🔮 待扩书30+ |
| S4+++ 七层检测 | 🔮 规划中 |
| Flash API 长上下文 | ⏸ 暂缓（内容安全风险 + 边际收益低） |
| 平台爬虫/算法关联 | ⏸ 暂缓（合规风险） |

## v7.7 新增功能

### 节奏分析 v13 (`rhythm_analyzer.py`)

| 功能 | 说明 |
|------|------|
| **即时爽/延迟爽标签** | `pleasure_timing` 字段，18 类爽点各有 instant/delayed 标签，进入 CSV 输出 |
| **6 类反转爽点正则** | 反派反噬 / 反陷阱 / 认知碾压 / 隐藏价值 / 身份反转 / 伏笔回收 |
| **18 爽点子类型** | 原 12 类 + 新增 6 类，覆盖 20 种反转套路 |
| **时序分布统计** | 摘要输出新增即时爽/延迟爽分布，辅助创作节奏把控 |

### 全书级记忆索引 (`pipeline/novel_index.py`)

为 AI 辅助写作提供跨章节上下文检索，解决"AI 记忆不可靠"问题：

| 功能 | 说明 |
|------|------|
| **上下文窗口** | `context_window(ch, k)` — 写第 N 章时自动检索前 K 章摘要 |
| **伏笔追踪** | 埋设/回收状态管理，`unresolved_events()` 列出未回收伏笔 |
| **角色时间线** | 角色出场 + 状态变化追踪 |
| **情感曲线** | 全书情感走势 (valence + burnout) |
| **爽点分布** | 即时爽/延迟爽比例 + 冲突高峰 |
| **综合报告** | `summary_report()` 生成 Markdown 全书索引报告 |

```bash
# 从 rhythm CSV 构建索引
python -c "from xiaoshuo.pipeline.novel_index import build_index; build_index('末世', '全球进化')"

# 查询写作上下文
python -c "from xiaoshuo.pipeline.novel_index import get_index; idx = get_index('末世', '全球进化'); print(idx.writing_context(50, 5))"
```

### v7.6 功能回顾

### Canon 设定管理管线 (`pipeline/canon/`)

6 个 canon 文件（角色/时间线/规则/伏笔/情感弧线/支线）自动从 `world.md` 提取填充：

```bash
# 自动提取并写入 6 个 canon 文件
D:\miniconda3\envs\llm-shared\python.exe -c "from xiaoshuo.pipeline.canon import CanonExtractor; CanonExtractor().write_all()"
```

| 模块 | 文件 | 功能 |
|------|------|------|
| 数据结构 | `canon/schema.py` | 6 个 canon 文件的 Schema 定义 + 类型校验 |
| 自动提取 | `canon/extractor.py` | 从 world.md 解析 → 生成 Markdown 写入 assets/canon/ |
| 一致性检查 | `canon/consistency_checker.py` | P2 大纲 vs canon + P3 正文 vs canon 逐章检查 |
| RP 推演 | `canon/rp_simulator.py` | 角色 DNA 提取 + prompt 构造 + 单场景/对戏推演 |

### 章节节拍检测 (`pipeline/scoring/beat_detector.py`)

基于 rhythm_analyzer 的冲突/钩子/爽点密度曲线，通过拐点检测定位 15 节拍（Save the Cat 改编），映射到 5 卷 300 章结构。

### 章节分区加权评分 (`pipeline/scoring/commercial_engine.py`)

- `get_chapter_zone_weight()`: 前 50 章 ×2.0 / 结尾 ×1.5 / 中间 ×1.0
- `compute_zone_weighted_average()`: 带分区权重的加权均值
- 配置入口: `config.yaml → analysis.chapter_zone_weights`

### llama.cpp 部署优化 (`scripts/start_model.bat`)

- KV cache 非对称量化: `--cache-type-k q8_0 --cache-type-v q4_0`（节省 ~25% 显存）
- Flash Attention: `--flash-attn on`
- 并行: `--parallel 2`

## 目录速查

| 目录 | 用途 |
|------|------|
| `src/xiaoshuo/pipeline/` | 数据分析管线 (21个py：入库/拆书/评分/桥接/摘要/指导/索引/技法) |
| `src/xiaoshuo/pipeline/scoring/` | 评分子模块 (borda_ranker/commercial_engine/pro_genre_guide/vad_analyzer 等) |
| `src/xiaoshuo/agents/` | LLM代理 (11个py：路由/状态机/世界观/大纲/交叉评审/记忆/角色/技能加载/章节决策) |
| `src/xiaoshuo/infra/` | 基础设施 (config_manager/hardware_guardian/logging/performance/pipeline_state) |
| `src/xiaoshuo/tools/` | 工具脚本 (ai_reference/calibrate/audit/dedup/diagnosis 等) |
| `scripts/` | 运维脚本 (start_model / lint / progress_server / start_all) |
| `frontend/` | 拆书监控面板前端 (HTML/CSS/JS — 原生模块化) |
| `设计方案/` | 前端设计方案归档与对比预览入口 |
| `assets/` | 创作资产 (library/canon/chapters/outline/voice) |
| `books/` | 书籍入口: in/→review/→data/raw/novels/ |
| `data/raw/` | 原始小说TXT（只读） |
| `data/processed/` | 中间产物 (CSV/JSON/checkpoints) |
| `data/reports/` | 分析报告 (creative_guidance/synthesis/deep_diagnosis/writing_manuals) |
| `tests/` | 单元测试 + 压力测试 |
| `config.yaml` | 系统唯一配置文件 (SSOT) |
| `AI_PROTOCOL.md` | LLM行为协议，由 `agents/skill_loader.py` 注入 System Prompt |
| `.codebuddy/` | CodeBuddy 专属配置（Trae 不修改） |
| `.trae/rules/` | Trae IDE 规则文件 |

## 快速开始

```bash
# 1. 下载小说.txt → 放到 books/in/
# 2. 入库+基础过滤
python -m xiaoshuo.pipeline.book_processor
# 3. 全量分析（9步自动化：入库→节奏→评分→关卡→桥接→摘要→跨书→技法→指导）
python -m xiaoshuo.pipeline.analyze_all --genre 末世
# 4. （可选）LLM评分 → 再跑一次 3
scripts/start_model.bat && python -m xiaoshuo.pipeline.analyze_all --genre 末世 --with-llm
# 5. 查看创作指导
cat data/reports/末世/creative_guidance/末世_创作指导.md
# 6. （可选）Pro API 类型指导
python -m xiaoshuo.pipeline.scoring.pro_genre_guide --genre 末世
# 7. books/review/ 有书？→ 人工审查
```

### 可视化拆书监控面板

```bash
scripts\progress_server.bat
```

浏览器访问 `http://localhost:8090`，可实时查看：

- 拆书任务队列与 L1/L2/L3 逐书进度
- 9阶段管线进度条 + 阶段步骤指示器
- GPU 温度 / 显存 / 风扇 / 系统内存 硬件健康度（4仪表盘）
- 启动 / 停止拆书流程（含 LLM 自动启动）
- 运行事件日志（分级过滤）
- 已完成书籍详情弹窗（L3全书概览/L2卷级分析/L1章节摘要）
- 商业化打分结果弹窗

后端 API：

| 接口 | 方法 | 说明 |
|------|:--:|------|
| `/api/status` | GET | 全局运行状态 |
| `/api/progress` | GET | 书籍进度列表（?genre=末世） |
| `/api/hardware` | GET | 硬件监控数据 |
| `/api/logs` | GET | 最近事件日志 |
| `/api/start` | POST | 启动拆书（body: `{genre, books}`） |
| `/api/stop` | POST | 停止拆书 |
| `/api/startup-status` | GET | 异步启动进度（LLM加载状态） |
| `/api/book/<name>` | GET | 书籍详情（L1/L2/L3数据） |
| `/api/score/<name>` | GET | 商业化打分结果 |

## 配置

所有阈值/路径/端口集中在 `config.yaml`（SSOT 设计），代码动态读取：

```yaml
analysis:
  book_filter: { min_size_kb: 200, min_chapters: 5, min_chinese_density: 0.40 }
  quality_gate: { min_rhythm_chapters: 10, max_zero_hook_streak: 5, min_commercial_score: 70 }
  llm_port: 8000          # 本地 Qwen3.5-9B llama-server 端口
  llm_parallel: 2          # LLM 并发调用数（L1摘要 + 规则分析）

model_orchestration:
  models:
    external_api:
      deepseek:
        enabled: false     # 改为 true 启用，api_key 放 secrets.yaml
        model: "deepseek-chat"
        max_tokens: 80
        temperature: 0.0
        timeout: 30
```

> `secrets.yaml`（gitignored）存放 API 密钥：
> ```yaml
> deepseek:
>   api_key: "sk-your-key-here"
> ```

## 技术栈

| 组件 | 规格 |
|------|------|
| 本地模型 | Qwen3.5-9B (Q4_K_M, 5.68GB VRAM, ctx=8192) |
| 云端模型 | DeepSeek V4-Flash / V4-Pro (via API) |
| GPU | RTX 5060 8GB |
| 运行环境 | conda llm-shared (D:\miniconda3\envs\llm-shared) |
| OS | Windows 11 |
| 前端 | 原生 HTML/CSS/JS (ES Modules, 无框架依赖)；设计方案管理见 `设计方案/` |
| 后端 | Python 3.11+ (http.server, 无 Web 框架) |

## 开发规范

- 所有路径使用 `pathlib.Path()`，禁止字符串拼接
- 所有阈值/端口/路径放在 `config.yaml`，禁止硬编码
- `print()` 用 `[OK]`/`[FAIL]`，不用 Unicode 符号（Windows GBK 兼容）
- `import` 全部在文件顶部，禁止函数内部 import
- 修改 .py 文件或 config.yaml 后运行 `scripts\lint.bat`
- 不修改 `.codebuddy/` / `assets/canon/` / `AI_PROTOCOL.md`（除非用户确认）
- `subprocess` 用 `DEVNULL` 不用 `PIPE`（无消费者时）

---

**深度架构见 `docs/design/`** · **AI协议见 `AI_PROTOCOL.md`** · **约束规则见 `.trae/rules/`**
