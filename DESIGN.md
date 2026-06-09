# 番茄小说 AI 辅助创作系统 — 系统架构设计文档

> **文档版本**: v7.4 (三层拆书深度架构 · Borda共识排名 · Bayesian Stacking · 数据管线就绪)
> **实际代码**: analysis/ 7步管线(book_processor→creative_bridge) + agents/ 6模块 + novel.py CLI
> **关联文档**: AI_PROTOCOL.md · config.yaml · status.mdc · project.mdc

---

## 目录

1. [设计哲学与目标](#1-设计哲学与目标)
2. [系统总览](#2-系统总览)
3. [分层架构](#3-分层架构)
4. [模块设计](#4-模块设计)
5. [数据设计](#5-数据设计)
6. [工作流设计](#6-工作流设计)
7. [接口与通信设计](#7-接口与通信设计)
8. [安全与合规设计](#8-安全与合规设计)
9. [评估体系与质量保障](#9-评估体系与质量保障)
10. [部署方案](#10-部署方案)
11. [风险与约束分析](#11-风险与约束分析)
12. [演进路线图](#12-演进路线图)
13. [附录](#附录)
14. [架构重构说明（v6.0→v7.0）](#14-架构重构说明v60v70) ← 🆕

---

## 1. 设计哲学与目标

### 1.0 项目目标（v7.3 当前）

**近期**: 任一题材，只要精品书样本足够 → 量化指导新人写出高质量爆款。
**终局**: 精品库持续蒸馏 → AI 拥有独立风格 → 写出不被识别为 AI 的原创小说。

六阶段管线：

```
① 入库过滤 → ② 拆书分析 → ③ 商业评分 → ④ 类型整合 → ⑤ 创作指导 → ⑥ 双文对比进化
   (book_     (rhythm_    (genre_      (creative_   (agents/)    [待实现]
  processor)  analyzer)  synthesizer)  bridge)

① 放入TXT → 过滤残缺/乱码/低质量 → 仅精品进入对应题材目录
② 逐章30+指标：爽点/钩子/冲突/节奏/可读性
③ 拆书三件套 + 情感弧 + 留存预估 + Bootstrap 95%CI
④ 同题材全部精品数据 → 8维基准 → 报告 + 摘要
⑤ 新人写某类书 → 读取该类基准 → 世界观/粗纲/细纲/人物/文笔/题材/情节/反同质化指导
⑥ 写完后 → 蒸馏爆款精品生成AI对照版 → 双文对比 → 优劣分析 → 进化优化
```

### 1.1 v7.1 设计哲学：从可认知到 MVP 就绪

v6.0 建立评估体系 → v7.0 引入双模型架构与语义记忆 → v7.1 完成四轮审视收敛，**具备 MVP 开发就绪条件**。

v7.1 的核心增量：**经过实测数据验证的精简方案 + 极限压力测试 + 竞品差异化定位**。核心理念：

> 上一代解决"AI 怎么理解你的故事"；这一代解决"确认方案可行，可以开工写了"。

| 维度 | v7.0 (智能认知型) | v7.1 (MVP就绪型) |
|------|------|------|
| 模型架构 | 双模型共存 + 编排层 | **确认 Qwen3.5-9B Dense 不支持 MTP**（实测 -42%），经典 draft SD 为 P1 唯一加速方案 |
| 加速方案 | MTP + SpecDec 双轨 | **仅 classic draft SpecDec**（Dense 模型 MTP 负收益已实测确认） |
| 认知交互 | 3方向随机 S2b | + **矛盾性分支探索**（"如果…会怎样？"互斥选择）+ **逻辑警察杠精模式** |
| 对抗防御 | MASH 四阶段（P2） | + **Adversarial Paraphrasing** 快速原型（P1 免训练替代） |
| 压力验证 | 无系统性测试 | + **末日生存压力测试**（AI污染/设定崩溃/显存极限 三场景） |
| 竞品定位 | 未明确 | + **差异化定位矩阵**（零成本+本地离线+合规安全 三位一体） |
| 评估体系 | golden_test_set + PAN 2026 | + PAN 2026 Ensemble 检测器模拟器 + 主动学习增量校准 |

### 1.2 v7.0→v7.1 增量修正说明 🆕

v7.0 经过负责人 + 2 份外部报告 + 1 轮终裁决共四轮审视。v7.1 不做结构性重构，仅做以下**事实性修正和精简**：

**修正项**：
1. **删除 MTP 加速方案**：实测 Qwen3.6-27B Dense 模型 MTP = **-42% 负加速**（NJannasch 2026.05 独立实测）。Qwen3.5-9B 同为 Dense 模型，同样适用此结论。仅保留 classic draft model SpecDec。
2. **删除 Qwen3.6 小模型评估**：Qwen3.6 系列无 4B/9B 尺寸（仅 27B Dense + 35B-A3B MoE），Qwen3.5-9B 仍是 8GB 最优解。
3. **P0 底线安全校验前置**：新增"末日生存压力测试"作为 P0 第 1 优先——确保 OOM/崩溃/检测失效等极端场景在编码前就暴露。

**新增项**：
4. **S3 逻辑警察杠精模式**：temperature=1.2 的刁钻视角（P1）
5. **S1 矛盾性分支探索**：`--explore-contradictions` 选项生成互斥的"如果…会怎样？"（P1）
6. **Adversarial Paraphrasing 快速原型**：免训练对抗改写（P1，替代 MASH 设计文档）
7. **竞品差异化定位**：附录新增竞争分析矩阵

### 1.3 项目背景

本项目是一个面向番茄小说网文创作的 **AI 辅助技术中台**。系统通过本地大语言模型（LLM）提供剧情引导、设定校验、风格检测等能力，最终实现"AI 辅助构思、作者手写正文"的协作范式。

**关键上下文**：截至 2026 年 5 月，番茄平台已整治 15 万本 AI 生成作品，账号 855 个。AI 生成正文将导致降权、下架乃至封号。因此，正文必须 100% 手写，AI 仅扮演"教练"角色。

### 1.3 设计目标

| 目标 | 描述 | 衡量标准 |
|------|------|----------|
| **零成本运行** | 全部组件在本地运行，不依赖付费 API | API 账单为 ¥0 |
| **合规保障** | 正文 100% 手写，AI 输出不直接进入终稿 | S4+++ 全部 SAFE + PAN 2026 基准验证 |
| **一致性保障** | 长篇创作中设定不"吃书"，伏笔不漏，因果不断 | NovelGraph 时空+因果校验 + SVO 句子级追踪 + ConStory-Bench F1≥0.85 |
| **语义理解** 🆕 | AI 能从"发生了什么"归纳出"意味着什么模式" | 语义记忆层概念召回率 ≥ 0.70 |
| **风格保护** | 追踪风格漂移，主动注入作者指纹噪声防 AI 同化 | Style Drift Monitor 0 次 HIGH 告警 + 风格噪声覆盖率 ≥ 0.80 |
| **结构诊断** | AI 能从叙事功能级别分析节奏，非仅统计密度 | 每 10 章多理论节拍+节奏曲线报告 |
| **可量化评估** | 每个模块有量化指标和回归测试 | 黄金测试集全覆盖 + PAN 2026 外部基准 |
| **对抗韧性** 🆕 | 系统能对抗平台检测器，而非仅自评 | MASH 对抗流水线 ASR ≥ 0.85（内部测试） |
| **协议化协作** | 工具可通过 MCP/API 被任意 AI 助手调用 | 工具互操作 |
| **渐进式落地** | 按 P0→P1→P2→P3 优先级分批实施 | 每周可交付 + P0 实验数据驱动后续决策 |

### 1.4 核心约束矩阵

| 维度 | 约束 | 不可妥协等级 |
|------|------|:---:|
| 成本 | 零额外资金投入 | ★★★ |
| 硬件 | RTX 5060 8GB + 32GB RAM | ★★★ |
| 隐私 | 本地离线优先，云端仅 S0 脱敏数据 | ★★★ |
| 合规 | 正文 100% 手写 | ★★★ |
| 技术栈 | Python 脚本 + 状态机 | ★★☆ |
| 前端 | 不开发，Obsidian/VS Code + CLI + 🆕实时linting插件 | ★★☆ |
| 时间 | 每日约 2 小时，单周 ≤14h | ★☆☆ |
| MCP/API | 可选增强，非核心依赖 | ★☆☆ |

### 1.5 术语定义

| 术语 | 定义 |
|------|------|
| **canon** | 设定数据库，唯一真相源。存放角色、世界观、规则等不可变设定 |
| **voice** | 文风层。存放作者的文风指南、AI 指纹黑名单、声音基线等 |
| **wiki** | 编译期知识层。每 10 章自动生成摘要和关系快照 |
| **NovelGraph** | 小说知识图谱。将角色、地点、事件、伏笔索引为 SQLite **时序图**数据库 |
| **S0-S4+++** | 五步工作流。从粗纲(S0)到发布前七层检测(S4+++) |
| **债务队列** | 设定变更时记录的影响范围，用于追踪后续修正任务 |
| **AI_PROTOCOL.md** | 项目级 AI 行为约束协议 |
| **MCP** | Model Context Protocol，标准化 AI 工具集成协议 |
| **声音基线** | 从作者历史章节提取的风格指纹，用于检测风格突变 |
| **时序图** | 关系随章节变化的图结构，边有 `valid_from_ch` 和 `valid_until_ch` |
| **叙事节拍** | 基于 Save the Cat! 理论的 15 个故事节奏节点 |
| **风格漂移** | 作者文风向量朝 AI 参考方向渐变的趋势 |
| **Action Constraint** | 代码级硬拦截层，AI 输出违反规则时自动阻断并要求重试 |
| **Speculative Decoding** | 用小型草稿模型预测 token、主模型验证，加速推理的技术 |
| **Prefix Caching** | 将固定 System Prompt 的 KV Cache 持久化到磁盘，跨 Session 复用 |
| **黄金测试集** | 人工标注 Ground Truth 的标准化测试样本集，含已知矛盾、AI 段落、风格漂移案例 |
| **ReRanker** | Cross-Encoder 精排模型，对向量检索粗排结果二次排序 |
| **多叙事结构库** | 覆盖 Save the Cat!、Hero's Journey、起承转合、网文专属节奏的模式库 |
| **爽点密度** | 网文核心节奏指标，定义"越级挑战""获得至宝""打脸反派"等模式的章节覆盖率 |
| ~~量化动态切换~~ | 🆕 v7.0 删除：改为双模型共存架构，不再需要切换延迟 |
| **模型编排层** | 🆕 v7.0 新增层：统一调度双模型（WebNovel专家+主模型）、请求路由、显存编排 |
| **S2b 污染链** | AI 参考版原文直接展示导致的认知污染风险，v6.0 改为展示结构化分析 |
| **Langfuse 追踪** | 自托管 LLM 可观测性平台，记录每次 S1/S3/S4 调用链路 + Prompt 版本 + Token 消耗 |
| **语义记忆层** | 🆕 v7.0 新增知识层：在事实记忆层(NovelGraph)之上，LLM 自动归纳高阶概念图——从"角色A第三章打脸恶霸B"归纳出"角色A倾向于当众揭露阴谋" |
| **SVO 三元组** | 🆕 v7.0 引入 STORYTELLER 论文范式：将每个情节节点表述为 (Subject, Verb, Object) 三元组，实现句子级因果追踪 |
| **叙事结构索引** | 🆕 v7.0 检索新维度：不仅按语义相似度检索，还按叙事功能（"假胜利节拍""情绪压抑场景"）检索历史成功段落 |
| **风格噪声** | 🆕 v7.0 主动防御概念：在作者文本中强化独特文风标记（标点习惯、特殊修辞），使其对 AI 检测器统计上更"陌生"，灵感来自 MASH 论文 |
| **MASH 对抗流水线** | 🆕 v7.0 安全增量：四阶段黑盒对抗（风格注入SFT→DPO对齐→推理精炼），使用 0.1B 改写器实现 92% ASR |
| **节奏曲线** | 🆕 v7.0 升级：从爽点密度正则匹配升级为"预期构建→延迟满足→峰值释放→余韵"四阶段张力模型 + LLM 分类 |
| **实时合规 linting** | 🆕 v7.0 交互层：Obsidian/VS Code 插件在打字时实时检测 AI 共现词密度，行号微提示，无感护航 |
| **PAN 2026** | 🆕 v7.0 评估基准：直接采用 PAN 2026 Voight-Kampff + Multi-Author Style Analysis 数据集作为外部黄金测试集 |
| **TurboQuant** | 🆕 v7.0 P2 追踪：社区 llama.cpp fork，声称 3x 速度 + 7.5x KV 压缩 |
| **末日生存压力测试** | 🆕 v7.1：三场景极端测试（AI污染/设定崩溃/显存极限），暴露系统在极端输入下的真实抗性 |
| **Adversarial Paraphrasing** | 🆕 v7.1 P1：ICLR 2025 免训练对抗改写方案，作为 MASH SFT+DPO 的轻量替代 |
| **矛盾性分支** | 🆕 v7.1 P1：S1 生成 3 个互斥的"如果…会怎样？"分支，强迫作者做选择，对抗认知框架限定 |
| **杠精模式** | 🆕 v7.1 P1：S3 逻辑警察 temperature=1.2 刁钻视角——过度解读动机、放大瑕疵、提出刁钻问题 |

---

## 2. 系统总览

### 2.1 系统定位

```
┌──────────────────────────────────────────────────────────────────────────┐
│                 番茄小说 AI 辅助创作系统 v7.1 (MVP就绪版)                    │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │              🆕 模型编排层 (model_orchestrator.py)                    │  │
│  │  Qwen3-4B-WebNovel (S1创意) ←→ Qwen3.5-9B (S3/S4评审) 双模型共存  │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                                    │                                     │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌───────────────┐         │
│  │ S0       │   │ S1-S3    │   │ S4+++    │   │ M5a/M5b/M5c  │         │
│  │ 云端粗纲 │──▶│ 本地创作 │──▶│ 七层检测 │──▶│ 节拍/漂移/    │──▶ 发布 │
│  │ (脱敏)   │   │ (全本地) │   │ (全本地) │   │ 经验库        │         │
│  └──────────┘   └──────────┘   └──────────┘   └───────────────┘         │
│       │              │              │              │                      │
│       ▼              ▼              ▼              ▼                      │
│  ┌──────────────────────────────────────────────────────┐                │
│  │          🆕 双记忆架构 (Factual + Semantic Memory)     │                │
│  │  ┌─────────────────┐  ┌──────────────────────────┐   │                │
│  │  │ 3a. 事实记忆     │  │ 3b. 语义记忆 🆕          │   │                │
│  │  │ NovelGraph 时序图│  │ AriGraph 风格概念图      │   │                │
│  │  │ + ChromaDB       │  │ "角色倾向于当众揭露阴谋"  │   │                │
│  │  │ + SVO 三元组追踪 │  │ 模式归纳 + 行为习惯     │   │                │
│  │  └─────────────────┘  └──────────────────────────┘   │                │
│  └──────────────────────────────────────────────────────┘                │
│       │              │              │              │                      │
│       ▼              ▼              ▼              ▼                      │
│  ┌──────────────────────────────────────────────────────┐                │
│  │      🆕 叙事结构索引检索 (Narrative-Indexed Retrieval) │                │
│  │  "找历史所有'假胜利'节拍的写法" / "找与当前心境类似的压抑场景"  │                │
│  └──────────────────────────────────────────────────────┘                │
│                                                                          │
│  ┌──────────────────────────────────────────────────────┐                │
│  │  🆕 增强安全底座: Action Constraint · MASH对抗流水线 · 风格噪声注入  │                │
│  └──────────────────────────────────────────────────────┘                │
└──────────────────────────────────────────────────────────────────────────┘
```

### 2.2 技术栈总览

| 层级 | 技术选型 | 版本要求 | 选型理由 |
|------|----------|----------|----------|
| **推理引擎** | llama.cpp (Python 绑定) | latest stable | 零依赖本地推理，GGUF 量化，CUDA 加速，支持 Prefix Caching + Context Shifting + Speculative Decoding |
| **主模型** | Qwen3.5-9B-Instruct (**Q4_K_M**) | - | Apache 2.0，v7.0 默认常驻 Q4_K_M（避免切换开销），评审任务质量优先。⚠️ Qwen3.6 系列无 4B/9B 尺寸，Qwen3.5-9B 仍是 8GB 最优解 |
| **专家模型** 🆕 | **TanXS/Qwen3-4B-LoRA-ZH-WebNovelty-v0.0** | P0 评估 | 中文网文写作专用 LoRA 微调，4B→量化~1.5GB，与主模型**同时加载** |
| **模型编排** 🆕 | **model_orchestrator.py** | - | 统一调度双模型：路由、显存编排、请求队列。替代 v6.0 的 model_switcher.py |
| **draft 模型 (P1)** | Qwen3.5-0.5B / Qwen3-1.8B Q4_0 | P1 实测 | Classic Speculative Decoding。⚠️ MTP 对 Dense 模型实测 -42%（NJannasch 2026.05），仅保留 classic draft |
| **向量库** | ChromaDB | 0.5+ | 轻量，Python 原生，与 llama.cpp 同进程 |
| **精排模型** | **BAAI/bge-reranker-v2-m3** | - | Cross-Encoder 精排，top-20→top-3，**🆕 含 CPU fallback 策略 + 显存预算** |
| **嵌入模型** | **BAAI/bge-m3** | - | 8192 token 上下文 + 100+ 语言 + 稠密稀疏混合检索 |
| **图数据库** | SQLite3 + 自定义 NovelGraph (时序图) | built-in | 🆕 增加 SVO 三元组表；P2 增加概念图表（语义记忆层） |
| **RAG 框架 (P2)** 🆕 | LightRAG vs HippoRAG 2 对比评估 | P2 | HippoRAG 2 "仿海马体长期记忆"更匹配 200 万字长篇场景 |
| **关系库** | SQLite3 | built-in | 设定库 + 债务队列 + 🆕设定变更历史索引 |
| **API 框架** | FastAPI | 0.115+ | 异步，自动 OpenAPI 文档（P1 可选） |
| **MCP 协议** | mcp-python-sdk | 1.0+ | 标准化工具暴露（P1 可选） |
| **配置管理** | PyYAML | 6.0+ | config.yaml 单文件管理所有配置 |
| **版本控制** | Git | 2.40+ | 全程追踪，变更可追溯 |
| **异步支持** | asyncio | built-in | S3 评审流水线并行 |
| **对抗改写 (P2)** 🆕 | MASH 风格迁移 + StealthRL | P2 | 四阶段对抗流水线，0.1B 改写器 |
| **实时 linting (P2)** 🆕 | Obsidian / VS Code 插件 | P2 | 行号旁微弱提示，实时合规护航 |

### 2.3 模型选型策略（v7.0 重构：双模型共存 + 角色定位测试）

v7.0 核心变化：v6.0 的动态量化切换策略**存在 90 秒/章的切换延迟**（100 章 = 2.5 小时纯开销），且每次切换需重启 llama.cpp。v7.0 改为**双模型同时加载 + 统一编排**架构。

#### 2.3.1 v6.0 量化切换 → v7.0 双模型共存

> ⚠️ 三方审视共识：动态切换的时间成本在每日 2 小时创作窗口中不可忽视。

| 维度 | v6.0 方案 | v7.0 方案 |
|------|---------|---------|
| 模型数量 | 1 个，切换量化格式 | **2 个同时加载** |
| S1 创意引导 | Qwen3.5-9B Q4_K_M (~4.5GB) | **🆕 TanXS/Qwen3-4B-WebNovel** (~1.5GB) |
| S3/S4 评审 | Qwen3.5-9B IQ4_XS (~3.8GB) | **Qwen3.5-9B Q4_K_M** (~4.5GB) 常驻 |
| 切换开销 | 每章 2-3 次 × 30s = 90s/章 | **0（双模型共存）** |
| 总显存 | ~5.3GB（单次） | ~6.0GB（双模型）✅ 余量 2.0GB |
| 100 章切换耗时 | ~2.5 小时 | **0** |
| 创意质量 | 通用模型做网文 | **网文专用 LoRA 模型** |

#### 2.3.2 🆕 模型评估矩阵（v7.0 扩展）

```yaml
模型评估矩阵 (v7.1):
┌──────────────────────────────────────────────────────────────────────────┐
│ 模型                         参数量   量化      显存     角色        状态  │
├──────────────────────────────────────────────────────────────────────────┤
│ ★ TanXS/Qwen3-4B-WebNovel    4B      Q4_K_M   ~1.5GB   S1 创意     P0评估│
│ Qwen3.5-9B                   9B      Q4_K_M   ~4.5GB   S3/S4 评审 常驻   │
│ DeepSeek-R1-Distill-Qwen-7B  7B      Q4_K_M   ~3.5GB   S3 逻辑警察 P0重测│
│ Qwen3-8B Thinking            8B      Q4_K_M   ~4.2GB   S1 创意后备 P1   │
│ Qwen3-14B                    14B     IQ3_M    ~5.5GB   边界可行    P2   │
└──────────────────────────────────────────────────────────────────────────┘

v7.1 关键变化:
• WebNovel 专家模型：社区针对中文网文场景的 LoRA 微调版。P0 实验确认是否满足 S1 需求。
• DeepSeek-R1-Distill 角色重定位：测试重心从"S1 创意"改为"S3 逻辑警察"。
• Qwen3.6 系列：无 ≤9B 尺寸（仅 27B Dense + 35B-A3B MoE），不纳入 8GB 方案。
• MTP 加速：对 Dense 模型确认负收益（实测 -42%），已排除。仅 classic draft SD。
• 量化策略：P0 实验后确定方案。双模型共存 or 单模型常驻 Q4_K_M。
```

#### 2.3.3 🆕 DeepSeek-R1-Distill-7B 角色重定位测试

三方审视交叉验证了关键洞察：**DeepSeek-R1-Distill 不是创意写作的"银弹"**，它在数学推理、代码生成、逻辑推理上表现优异，但文学性表达并非训练重点。

**v7.0 决策**：不降级，改为"角色重定位测试"——

| 测试维度 | S1 创意生成 | S3 逻辑警察 |
|---------|:---:|:---:|
| 中文语感 | 弱（推理蒸馏数据） | — |
| 逻辑一致性 | — | **强（原生的推理链能力）** |
| 因果断裂检测 | — | **强** |
| 时间线矛盾分析 | — | **强** |
| 角色动机逻辑 | — | **强** |
| **结论** | ❌ 不作为 S1 主模型 | ✅ P0 评估作为 S3 逻辑警察替代 |

**实验设计**：用 ConStory-Bench 的因果断裂/时间线矛盾子集，对比 Qwen3.5-9B vs DeepSeek-R1-Distill-7B 的逻辑矛盾检出率。若 DS-R1 在逻辑类任务上 F1 领先 >10%，则考虑**三模型架构**（WebNovel S1 + DS-R1 S3 逻辑警察 + Qwen3.5 S3 编辑/质检）。

#### 2.3.4 标准化 A/B 测试框架（同 v6.0，角色升级）

**测试数据集**：5 个标准 S1 引导任务，覆盖番茄小说常见场景。

**🆕 v7.0 升级**：增加 2 个**推理密集型测试**（针对 DeepSeek-R1-Distill 角色重定位）：

| ID | 任务 | 类型 | 新增 |
|:---:|------|------|:---:|
| `scene_desc` | 场景描写 | 创意生成 | — |
| `dialogue` | 对话生成 | 创意生成 | — |
| `action_seq` | 动作序列 | 创意生成 | — |
| `psychology` | 心理描写 | 创意生成 | — |
| `lore_setup` | 设定解释 | 创意生成 | — |
| `causal_logic` 🆕 | 因果断裂检测 | 逻辑推理 | ✅ |
| `timeline_contra` 🆕 | 时间线矛盾分析 | 逻辑推理 | ✅ |

**评估维度与权重**：

| 维度 | 评估方法 | 权重 | 适用模型 |
|------|---------|:---:|------|
| **中文语感** | 人工评分 1-10 | 25% | S1 创意模型 |
| **词汇多样性** | Yule's K + AI 高频词黑名单命中率 | 25% | S1 创意模型 |
| **指令遵循度** | ActionConstraint 通过率 | 25% | 全部 |
| **创意惊喜度** | 人工评分 1-10 | 15% | S1 创意模型 |
| **生成速度** | tokens/second | 10% | 全部 |
| **🆕 逻辑矛盾检出率** | ConStory-Bench 因果子集 F1 | — | S3 评审模型 |

**决策矩阵（v7.0 更新）**：

| 对比结果 | 决策 |
|------|------|
| WebNovel 专家模型 中文语感+词汇多样性 ≥ Qwen3.5-9B 的 90% | → **双模型共存**：WebNovel S1 + Qwen3.5 S3/S4 |
| WebNovel 不满足但 Qwen3.5 Q4_K_M 满足 | → **单模型常驻 Q4_K_M**（不切换） |
| DeepSeek-R1 逻辑 F1 > Qwen3.5 10%+ | → **三模型**：WebNovel S1 + DS-R1 逻辑警察 + Qwen3.5 编辑/质检 |
| 三者差异 <10% | → 维持 Qwen3.5 单模型，优先完善工作流 |

#### 2.3.5 P1 加速方案：Classic Speculative Decoding（MTP 已排除）

**⚠️ v7.1 实测确认（NJannasch 2026.05）**：
- **MoE 模型** (Qwen3.6-35B-A3B)：MTP 带来 **+47%** 加速（98→144 t/s）
- **Dense 模型** (Qwen3.6-27B)：MTP 造成 **-42%** 减速（28.5→16.4 t/s）

根因：Dense 模型每 token 读取全部权重，带宽已占 ~76%，MTP 额外权重读取触发带宽抢占。Qwen3.5-9B 同为 Dense 模型，同样适用此结论。

**v7.1 策略（精简）**：
- ✅ **仅 classic draft model**：Qwen3.5-0.5B / Qwen3-1.8B 作为 draft
- ❌ **MTP 已排除**：对 Dense 模型确认负收益
- P1 在 RTX 5060 上跑 5 个标准 prompt 实测 baseline vs classic draft
- ngram-cache/ngram-mod 对高熵创意文本效果差，优先 classic draft model

#### 2.3.6 🆕 P2 追踪：TurboQuant

llama.cpp 社区 2026 年 5 月出现 TurboQuant 分支（`YV17labs/llama-cpp-turboquant-webp`），声称 **3x 速度 + 7.5x KV Cache 压缩**。P2 在隔离环境测试兼容性和精度损失。注意这是社区 fork，稳定性待验证。

### 2.4 显存预算（v7.0：双模型共存架构）

```
RTX 5060 8GB VRAM (v7.0 双模型共存):

🆕 方案 A：双模型共存 (WebNovel专家 + 主模型) — P0 优先评估:
┌──────────────────────────────────────────────────────────────────┐
│  WebNovel 专家: Qwen3-4B-WebNovel Q4_K_M     ██          1.5GB  │
│  KV Cache (16K)                               █           0.3GB  │
│  主模型: Qwen3.5-9B Q4_K_M                    ████████    4.5GB  │
│  KV Cache (32K)                               ██          0.5GB  │
│  Prefix Cache (磁盘)                           (不在显存)  0.0GB  │
│  框架开销 (llama.cpp ×2 + Python)             █           0.5GB  │
│  安全余量                                     ███         0.7GB  │
│  ──────────────────────────────────────────────────────────────── │
│  总计                                                  8.0GB ✅  │
└──────────────────────────────────────────────────────────────────┘
  编排: model_orchestrator.py 统一路由
  S1 → WebNovel 专家 (port 8001)
  S3/S4 → Qwen3.5-9B (port 8000)
  切换延迟: 0ms（双模型共存，无需重启）

🟡 方案 B：单模型常驻 Q4_K_M (WebNovel 不满足时的降级方案):
┌──────────────────────────────────────────────────────────────────┐
│  Qwen3.5-9B Q4_K_M                              ████████    4.5GB │
│  KV Cache (32K)                                 ██          0.5GB │
│  Prefix Cache (磁盘)                             (不在显存)  0.0GB │
│  框架开销                                       █           0.3GB │
│  安全余量                                       █████       2.7GB │
│  额外：BGE-Reranker-v2-m3 (CPU fallback)        (CPU运行)   0.0GB │
│  ──────────────────────────────────────────────────────────────── │
│  总计                                                  8.0GB ✅  │
└──────────────────────────────────────────────────────────────────┘

⚠️ 旧方案：动态量化切换 (v6.0，已弃用):
  每章 2-3 次切换 × 30s/次 × 100 章 = 2.5 小时纯切换开销 — 不可接受

🆕 ReRanker 显存预算:
  bge-reranker-v2-m3 Cross-Encoder 显存占用:
  - max_length=512:  ~0.8GB (GPU)
  - max_length=1024: ~1.5GB (GPU)
  - CPU fallback: 0GB GPU / 延迟 +50-100ms
  策略: 默认 CPU 运行（top-20 规模可控），显存充足时 GPU 加速
```

> **硬约束**：v7.1 双模型共存约 6.0GB，余量 2.0GB。若需增加 classic draft 模型（Speculative Decoding P1），需额外 ~1.0GB，总显存 ~7.0GB，仍在 8GB 边界内。若启用三模型（P0 实验后），需释放 WebNovel 或降低主模型量化。⚠️ MTP 不适用（Dense 负收益）。

---

## 3. 分层架构

### 3.1 🆕 十层架构总览（v6.0 九层 → v7.0 十层）

v7.0 核心结构性变化：**知识层分裂为"事实记忆层"+"语义记忆层"**，**新增"模型编排层"**。

```
┌──────────────────────────────────────────────────────────────────────────┐
│  第 10 层 评估层     Golden Test Set · ConStory-Bench · PAN 2026 基准 🆕 │
│                      · Langfuse 追踪 · A/B 测试报告                       │
├──────────────────────────────────────────────────────────────────────────┤
│  第 9 层  分析层     Beat Analyzer · 🆕 节奏曲线 · Style Drift Monitor   │
│                      · 🆕 风格噪声注入 · 评审经验库 · 作者画像            │
├──────────────────────────────────────────────────────────────────────────┤
│  第 8 层  安全层     Action Constraint · 🆕 MASH 对抗流水线               │
│                      · 行为伪装 · 🆕 PAN 2026 对抗策略 · 红蓝对抗         │
├──────────────────────────────────────────────────────────────────────────┤
│  第 7 层  交互层     CLI · MCP Server · FastAPI · Obsidian               │
│                      · 🆕 实时合规 linting 插件                           │
├──────────────────────────────────────────────────────────────────────────┤
│  第 6 层  工作流层   S0→S1→S2a-d→S3→S4+++  (S3 异步流水线)               │
│                      · 🆕 model_orchestrator 路由决策                     │
├──────────────────────────────────────────────────────────────────────────┤
│  第 5 层  检测层     S4+++ 七层检测 · 12维声音基线 · 反同质化             │
├──────────────────────────────────────────────────────────────────────────┤
│  第 4 层  🆕 语义记忆层 概念图 (模式归纳) · 叙事结构索引检索              │  🆕
│                      "角色倾向于当众揭露阴谋" · "假胜利节拍写法库"        │
├──────────────────────────────────────────────────────────────────────────┤
│  第 3 层  事实记忆层 NovelGraph(时序图) · 🆕 SVO 三元组 · ChromaDB        │
│                      · ReRanker · Narrative-Indexed Retrieval             │
├──────────────────────────────────────────────────────────────────────────┤
│  第 2 层  数据层     canon/ · outline/ · chapters/ · review/ · tests/     │
│                      · 🆕 PAN 2026 数据集                                 │
├──────────────────────────────────────────────────────────────────────────┤
│  第 1 层  协议层     AI_PROTOCOL.md · config.yaml · state.json                  │
│                      · 🆕 model_orchestrator 配置                         │
├──────────────────────────────────────────────────────────────────────────┤
│  🆕 第 0 层 模型编排层 model_orchestrator.py (双模型共存·路由·显存编排)   │  🆕
└──────────────────────────────────────────────────────────────────────────┘
```

### 3.2 层间职责与交互

```
                  AI_PROTOCOL.md (静态前缀 → Prefix Cache 磁盘持久化)
                       │
                       ▼
┌──────────────────────────────────────────────────────────────┐
│                     CLI 入口 (novel.py)                        │
│   init │ s0 │ s1 │ s2a │ s2c │ s3 │ s4 │ graph │ beat │ drift │
│        │ 🆕 test --pan │ 🆕 mash --run                        │
└──────┬─────────────────┬──────────────────┬───────────────────┘
       │                 │                  │
       ▼                 ▼                  ▼
┌─────────────┐  ┌──────────────┐  ┌───────────────────────────┐
│ 🆕 模型编排  │  │ 双记忆系统    │  │ 检索管道                   │
│Orchestrator │  │ NovelGraph+SVO│  │ ChromaDB + ReRanker       │
│ 路由:       │  │ + 语义概念图  │  │ + 🆕 Narrative Index      │
│ S1→WebNovel │  └──────┬───────┘  └──────┬────────────────────┘
│ S3→主模型   │         │                 │
└──────┬──────┘         │                 │
       │                └────────┬────────┘
       │                         │
       ▼                         ▼
┌──────────────────────────────────────────────────────────────┐
│              本地 LLM (llama.cpp) 双模型部署                    │
│  🆕 WebNovel 专家 @ http://localhost:8001/v1  (S1 专用)       │
│  Qwen3.5-9B       @ http://localhost:8000/v1  (S3/S4 专用)    │
│  Prefix Cache: memory/system_prompt_cache.bin                 │
└──────────────────────────────────────────────────────────────┘
```

### 3.3 数据流向

```
S0 云端              S1-S4 本地                 发布
   │                     │                       ▲
   │  脱敏粗纲            │                       │
   ├────────────────────▶│                       │
   │                     │ 🆕 S1 → WebNovel专家  │
   │                     │  S1 引导 ──▶ guides/  │
   │                     │      │                │
   │                     │      ▼                │
   │                     │  S2a v1 ──▶ ch_v1    │
   │                     │      │                │
   │                     │      ▼ (可选S2b, 🆕框架级切断)│
   │                     │  S2c 对比              │
   │                     │      │                │
   │                     │      ▼                │
   │                     │  S2d v2 ──▶ ch_v2    │  ← 🆕 风格噪声注入
   │                     │      │                │
   │                     │      ▼                │
   │                     │  S3 异步评审 ──▶ jury │  ← 🆕 逻辑警察可选DS-R1
   │                     │      │                │
   │                     │      ▼                │
   │                     │  S4+++ 七层检测       │
   │                     │      │                │
   │                     │      ▼                │
   │                     │  ──────────────▶ 发布 │
   │                     │                       │
   │    ◀─── 🆕 双记忆 (事实+语义) 自动更新 ──────▶│
   │    ◀─── NovelGraph (时序图) + SVO 三元组 ───▶│
   │    ◀─── 🆕 叙事结构索引检索 ───────────────▶│
   │    ◀─── 债务队列 + 变更历史索引 ───────────▶│
   │    ◀─── Style Drift Monitor + 风格噪声 ────▶│
```

---

## 4. 模块设计

### 4.1 模块总览

系统划分为 **8 个核心模块** + **🆕 2 个 v7.0 新增模块** + **1 个协议层** + **4 个分析组件**：

```
                      ┌──────────────┐
                      │  AI_PROTOCOL.md    │  ← 协议层（注入所有 AI 调用）
                      │  config.yaml │
                      │ + 🆕双模型配置│
                      │ + 🆕MASH配置 │
                      └──────┬───────┘
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
          ▼                  ▼                  ▼
┌────────────────┐  ┌──────────────┐  ┌──────────────────────────┐
│ M1 工作流引擎   │  │ M2 知识图谱  │  │ 🆕 M2b 语义记忆层       │
│ StateMachine   │  │ NovelGraph   │  │ 概念图 (AriGraph 灵感)   │
│ S0-S4+++流程   │  │ 🆕 SVO三元组 │  │ "角色倾向于当众揭露阴谋" │
│ + 🆕路由编排   │  │ +因果链追踪  │  │ 模式归纳·行为习惯·跨章联想│
│ + 异步S3       │  │ +时空校验    │  └──────┬───────────────────┘
└──────┬─────────┘  └──────┬───────┘         │
       │                   │                  │
       └──────────┬────────┴─────────┬────────┘
                  │                  │
                  ▼                  ▼
           ┌──────────────┐  ┌─────────────────────┐
           │ M3 记忆系统  │  │ 🆕 M3b 叙事结构索引  │
           │ ChromaDB     │  │ Narrative-Indexed    │
           │ + ReRanker   │  │ "找历史所有'假胜利'" │
           │ + Prefix     │  │ 节拍·心境·情感     │
           │ + Context    │  └──────┬──────────────┘
           └──────────────┘         │
                                    │
          ┌─────────────────────────┼──────────────────────┐
          │                         │                      │
          ▼                         ▼                      ▼
┌──────────────────┐  ┌────────────────────┐  ┌──────────────────────┐
│ M4 检测引擎       │  │ M5 交互接口         │  │ M5a 节拍分析器 🆕    │
│ S4+++ 七层检测   │  │ MCP/FastAPI/CLI     │  │ Beat Analyzer v7.0   │
│ 12维基线         │  │ + Action Constraint │  │ 多理论·🆕节奏曲线   │
│ 🆕 实时linting   │  │ + 🆕实时linting插件 │  │ + 爽点密度           │
└──────────────────┘  └──────┬─────────────┘  └──────────────────────┘
                             │
           ┌─────────────────┼──────────────────────┐
           │                 │                      │
           ▼                 ▼                      ▼
┌────────────────────┐  ┌──────────────────────┐  ┌────────────────────────┐
│ M5b 风格漂移 v7.0  │  │ M5c 评审经验库 v7.0  │  │ 🆕 M5d 模型编排层      │
│ Style Drift Monitor│  │ Review Knowledge Base│  │ model_orchestrator.py  │
│ + 🆕风格噪声主动注入│  │ + 因果归纳·作者画像  │  │ 双模型路由·显存编排    │
│ + MASH 风格迁移    │  │ + 跨书模式学习 (P2)  │  │ 请求队列·健康检查      │
└────────────────────┘  └──────────────────────┘  └────────────────────────┘
          │                         │                      │
          └─────────────────────────┼──────────────────────┘
                                    │
                                    ▼
                            ┌──────────────────┐
                            │ M6 文件系统      │
                            │ + 节拍/漂移报告  │
                            │ + 🆕 语义记忆快照│
                            │ + 🆕 PAN 2026 数据│
                            └──────────────────┘
```

### 4.2 M1 — 工作流引擎

#### 职责

管理 S0→S4+++ 的完整创作流程，维护流程状态，驱动阶段切换，管理债务队列。v7.0 核心升级：**双模型编排路由 + 叙事结构索引注入**。

#### 核心组件

| 组件 | 文件 | 职责 | v7.0 变化 |
|------|------|------|:---:|
| 状态机 | `.agents/state_machine.py` | 流程状态管理、阶段切换、断点续接 | — |
| 🆕 模型编排器 | `.agents/model_orchestrator.py` | 双模型路由调度、显存编排、健康检查 | 🆕 替代 model_switcher |
| 多样性采样器 | `.agents/diversity_sampler.py` | S1 多温度引导生成 | 🔄 S1 路由至 WebNovel 专家 |
| 虚拟评审团 | `.agents/virtual_jury_v5.py` | S3 **异步流水线**评审 | 🔄 逻辑警察可选 DS-R1 |
| 编译脚本 | `.agents/compile_wiki_v5.py` | 每 10 章自动生成 wiki | 🔄 P2 ReIO 动态压缩 |

#### 状态模型

```
                       ┌──────────┐
                       │  INIT    │ 项目初始化
                       └────┬─────┘
                            │
                       ┌────▼─────┐
                       │   S0     │ 云端粗纲 + 反同质化检查
                       └────┬─────┘
                            │
                       ┌────▼─────┐
                  ┌───▶│   S1     │ 本地 LLM 引导生成 (3 温度变体)
                  │    └────┬─────┘
                  │         │
                  │    ┌────▼─────┐
                  │    │   S2a    │ 手写 v1 + NovelGraph 时序校验
                  │    └────┬─────┘
                  │         │ (可选, 🆕 心理距离替代24h)
                  │    ┌────▼─────┐
                  │    │   S2b    │ AI 参考版 (需手写3段后解锁)
                  │    └────┬─────┘
                  │         │
                  │    ┌────▼─────┐
                  │    │   S2c    │ 对比分析 + 版权清洁度
                  │    └────┬─────┘
                  │         │
                  │    ┌────▼─────┐
                  │    │   S2d    │ 手写 v2 + 声音基线 + 🆕风格漂移追踪
                  │    └────┬─────┘
                  │         │
                  │    ┌────▼─────┐
                  │    │   S3     │ 🆕 异步流水线 (逻辑警察→[编辑∥质检])
                  │    └────┬─────┘
                  │         │
                  │    ┌────▼─────┐    FAIL
                  │    │ S4+++    │──────────▶ 退回 S2d 重写
                  │    └────┬─────┘
                  │         │ PASS
                  │         ▼
                  │    ┌──────────┐
                  └────│  PUBLISH │ 发布 (🆕 含行为伪装参数)
                       └──────────┘
```

#### 🆕 S3 异步流水线评审

v4.1 中三角色串行执行，任何一个 BLOCK 也需要等全部跑完。v5.0 改为**逻辑警察先行、编辑质检并行**：

```
v4.1 (串行):
  逻辑警察(30s) → 网文编辑(30s) → 语言质检(30s) ── 90s

v5.0 (异步流水线):
  逻辑警察(30s)
    ├─ BLOCK → 立即退回 S2d (省 60s) ⚡
    └─ 通过 → 网文编辑(30s) ─┬─ 并行 ─→ 汇总 (60s)
                            语言质检(30s) ─┘
```

```python
# .agents/virtual_jury_v5.py
async def run_jury_pipeline(chapter: int, text: str) -> JuryResult:
    # Stage 1: 逻辑警察先行
    logic = await run_logic_cop(chapter, text)
    if logic.verdict == "BLOCK":
        return JuryResult(verdict="BLOCK", early_exit="3A")
    
    # Stage 2: 编辑 + 质检并行
    editor, qc = await asyncio.gather(
        run_editor(chapter, text),
        run_quality_inspector(chapter, text)
    )
    return JuryResult(verdict=aggregate(logic, editor, qc))
```

#### 债务队列设计

| 债务类型 | 触发条件 | 影响范围 |
|----------|----------|----------|
| `lore_change` | canon/ 文件修改 | outline/ + wiki/ + chapters/ + NovelGraph |
| `character_change` | 角色设定变更 | 所有涉及该角色的章节 + NG 实体 |
| `timeline_change` | 时间线调整 | 因果链 + NG 时间线事件 |
| `rule_change` | 规则体系变更 | 所有规则应用点 + NG 规则 |

### 4.3 M2 — 知识图谱 (NovelGraph v7.0) + 🆕 SVO 情节三元组层

#### 设计动机

传统小说创作中，设定一致性依赖于作者记忆。长篇（50 万+字）创作时，角色死亡后"复活"、道具未引入便使用、势力关系矛盾等问题频发。

**v7.0 进化**（三方审视共识）：
- v6.0: 时序图 + 事件因果链 + 空间连续性 + ConStory-Bench 校准
- **v7.0: 🆕 SVO 三元组句子级情节追踪**（STORYTELLER 论文 [2506.02347] 灵感）

#### 🆕 SVO 三元组层设计

STORYTELLER (ACL 2025 Findings) 提出将每个情节节点表述为 **(Subject, Verb, Object) 三元组**，实现句子级因果追踪。当前 Intent JSON 是章节级粗粒度——SVOs 将因果追踪细化到"谁对谁做了什么"。

```sql
-- 🆕 v7.0 svo_triples 表
CREATE TABLE svo_triples (
    id TEXT PRIMARY KEY,                          -- SVO_001
    chapter INTEGER NOT NULL,                      -- 所属章节
    paragraph_index INTEGER,                       -- 段落位置
    subject_entity_id TEXT REFERENCES entities(id), -- 主语实体
    verb TEXT NOT NULL,                            -- 谓语动词
    object_entity_id TEXT REFERENCES entities(id), -- 宾语实体 (可为NULL)
    context_pre TEXT,                              -- 前文 2 句上下文
    context_post TEXT,                             -- 后文 2 句上下文
    narrative_function TEXT,                       -- 🆕 叙事功能: cause/effect/reveal/foreshadow/conflict/resolve
    auto_extracted BOOLEAN DEFAULT TRUE,           -- LLM自动抽取 vs 手动标注
    confidence REAL DEFAULT 0.5,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 查询示例: "找出所有主角打脸的SVOs"
SELECT * FROM svo_triples 
WHERE subject_entity_id = 'ENT_CHAR_PROTAGONIST'
  AND narrative_function = 'conflict'
  AND verb IN ('击败', '揭穿', '打脸', '压制', '碾压')
ORDER BY chapter;

-- 查询示例: "第5章的事件引发了多少后续连锁反应？"
SELECT e2.* FROM svo_triples e1
JOIN event_causality ec ON e1.id = ec.cause_event_id
JOIN svo_triples e2 ON ec.effect_event_id = e2.id
WHERE e1.chapter = 5;
```

**SVO vs Intent JSON 对比**：

| 维度 | v6.0 Intent JSON | v7.0 SVO 三元组 |
|------|-----------------|-----------------|
| 粒度 | 章节级 | **句子级** |
| 标注方式 | 手动编写 | **LLM 自动抽取 + 人工校准** |
| 覆盖度 | 作者声明的关键 Intent | **所有事件全覆盖** |
| 叙事功能 | structural_beat (1个) | **narrative_function (6种)** |
| 因果追踪 | 手动声明 causal_link | **自动检测因果链** |
| 开销 | 每章 5-10min 手动标注 | 每章 ~30s LLM 自动抽取 |

#### ER 模型（v7.0 扩展）

```
┌──────────┐         ┌──────────────┐
│  Entity  │────────▶│  Edge (时序)  │
│ (7种类型) │         │ (关系随时间变) │
└──────────┘         └──────────────┘
     │                     │
     │    🆕 v7.0 新增     │
     ▼                     ▼
┌──────────────┐  ┌──────────────────┐  ┌────────────────┐
│Timeline Event│  │Foreshadowing Graph│  │ EmotionalArc   │
└──────────────┘  └────────────────────┘  └────────────────┘
     │
     ▼
┌──────────────────┐
│ Event Causality  │
└──────────────────┘
     │
     ▼
┌──────────────────────────────┐  ← 🆕 v7.0 新增
│ 🆕 SVO 三元组层               │
│ (Subject, Verb, Object)       │
│ + narrative_function          │
│ + auto_extracted              │
│ → STORYTELLER 论文灵感        │
└──────────────────────────────┘
```

#### 核心查询能力

v7.0 在 v6.0 基础上新增：🆕 **SVO 因果链追溯**（"第3章主角获得神秘信件→第5章前往仓库→第8章发现真相"全链路追踪）。

#### 核心查询能力

| 能力 | 方法 | 用途 | v5.0 新增 |
|------|------|------|:---:|
| BFS 关系遍历 | `query_relationship(entity, depth)` | "主角和反派的关联路径" | — |
| 硬规则一致性校验 | `check_consistency(text, ch)` | 死亡角色复活、未来物品、势力矛盾 | — |
| 语义矛盾检测 | `semantic_contradiction_check(text, ch, intent)` | 角色声明"离开"但仍在原场景 | — |
| 🆕 **空间连续性校验** | `check_spatial_continuity(ch)` | 角色A从北京→上海，中间缺位移事件 | ✅ |
| 🆕 **因果断裂检测** | `check_causal_chain(event_id)` | 杀死反派后反派又出现→标记 CAUSAL_BREAK | ✅ |
| 影响分析 | `impact_analysis(entity_id)` | 修改某个角色设定会影响多少章节 | — |
| 上下文提取 | `get_relevant_context(text, ch)` | S3 评审时将相关设定注入 LLM 上下文 | — |
| 意图驱动分析 | `intent_aware_review(text, ch, intent)` | "本章意图埋设F005"→针对性检查 | — |

#### 时序边设计

```sql
-- v5.0 edges 表升级
ALTER TABLE edges ADD COLUMN valid_from_ch INTEGER;      -- 关系生效章节
ALTER TABLE edges ADD COLUMN valid_until_ch INTEGER;     -- 关系结束章节 (NULL=至今)
ALTER TABLE edges ADD COLUMN status TEXT DEFAULT 'active'; -- active/ended/contradicted

-- 查询示例: "第5章时主角和反派是什么关系？"
SELECT relation_type FROM edges 
WHERE source_id = 'ENT_CHAR_001' 
  AND target_id = 'ENT_CHAR_002'
  AND valid_from_ch <= 5 
  AND (valid_until_ch IS NULL OR valid_until_ch >= 5);
```

#### 🆕 事件因果表

```sql
CREATE TABLE event_causality (
    id TEXT PRIMARY KEY,                              -- CAUSAL_001
    cause_event_id TEXT REFERENCES entities(id),       -- 原因事件
    effect_event_id TEXT REFERENCES entities(id),      -- 结果事件
    chapter_latent INTEGER,                            -- 潜伏章节数
    causality_type TEXT CHECK(causality_type IN       -- 因果类型
        ('triggers', 'leads_to', 'resolves', 'contradicts', 'foreshadows')),
    confidence REAL DEFAULT 0.5,
    detected_by TEXT DEFAULT 'manual'                 -- manual / LLM / rule
);
```

#### Intent 机制（v5.0 进化：因果追踪式）

```json
// outline/chapter_plans/ch05_intent.json (v5.0)
{
  "chapter": 5,
  "structural_beat": "fun_and_games",       // 🆕 对应叙事节拍
  "intents": [
    {
      "type": "foreshadow_plant",
      "id": "F005",
      "detail": "埋设神秘信件来源线索",
      "causal_link": {                      // 🆕 因果追踪
        "triggered_by": "F003",
        "expected_payoff": "F008",
        "latent_chapters": 3
      }
    }
  ],
  "causal_chain": [                         // 🆕 事件因果链
    {"cause": "E003_获得神秘信件", "effect": "E005_前往废弃仓库", "type": "leads_to"}
  ],
  "constraints": [
    "本章主角不能离开城市（为第7章埋伏笔）",
    "本章不引入新角色"
  ]
}
```

### 4.3b 🆕 M2b — 语义记忆层 (Semantic Memory / AriGraph 灵感)

#### 设计动机

当前 NovelGraph 精确记录"第3章角色A打脸了恶霸B"——这是**情景记忆（Episodic Memory）**。但它无法回答"角色A倾向于在什么情境下、用什么方式打脸"——这需要**语义记忆（Semantic Memory）**，即从具体事件中归纳出的**模式级知识**。

AriGraph 论文提出构建"情景记忆 + 语义记忆"双记忆系统。语义记忆作为事实记忆之上的**概念归纳层**，让 AI 在 S1 引导和 S3 评审时，能基于角色的**行为模式**而非仅仅**设定事实**来提供建议。

#### 概念图 Schema

```sql
-- 🆕 v7.0 concept_graph 表
CREATE TABLE concept_graph (
    id TEXT PRIMARY KEY,                              -- CONCEPT_001
    concept_type TEXT CHECK(concept_type IN           -- 概念类型
        ('behavior_pattern',    -- 行为模式: "主角倾向于当众揭露阴谋"
         'relationship_dynamic',-- 关系动态: "A和B的冲突总在第三者介入时升级"
         'narrative_strategy',  -- 叙事策略: "作者偏爱延迟满足式爽点释放"
         'thematic_motif',      -- 主题母题: "身份反转"
         'style_habit')),       -- 风格习惯: "战斗场景中偏爱短句+比喻"
    concept_text TEXT NOT NULL,                       -- 自然语言描述
    supporting_evidence TEXT,                         -- 支持证据: 引用的具体章节事件
    confidence REAL DEFAULT 0.5,
    first_observed_chapter INTEGER,
    last_reinforced_chapter INTEGER,                  -- 最近一次强化该模式的章节
    contradict_count INTEGER DEFAULT 0,               -- 反例计数
    status TEXT DEFAULT 'active'                      -- active/obsolete/contradicted
);

-- 示例数据:
-- CONCEPT_001: behavior_pattern
--   "当对手拥有更高社会地位时，主角倾向于用公开揭露阴谋而非武力来取胜"
--   supporting_evidence: SVO_023(Ch3), SVO_067(Ch7), SVO_145(Ch15)
--   contradict_count: 1 (SVO_098 破例用了武力 → 触发"模式变异"标记)
```

#### 更新策略

```python
# .agents/semantic_memory.py (v7.0 P1)
def update_concepts(chapter_num: int, new_svos: List[SVO]) -> int:
    """每章完成后，对比新 SVOs 与现有概念图：
    1. 找到被强化的概念 → 更新 last_reinforced_chapter
    2. 找到被反例挑战的概念 → 增加 contradict_count
    3. 检测到新模式 → 创建候选概念 (confidence=0.3)，人工确认后提升
    """
```

**开销**：每章额外 1 次 LLM 调用（~15s），归纳已有的 50+ 个 SVO 三元组。

---

### 4.4 M3 — 记忆系统（v7.0：叙事结构索引增强）

#### 检索管道升级

v6.0 在两段式检索（向量 + BM25）基础上增加第三段：

```
ChromaDB 粗排 (BGE-M3 嵌入, top-20)
    │
    ▼
BM25 稀疏补充 (top-10)
    │
    ▼
🆕 Cross-Encoder ReRanker (BGE-Reranker-v2-m3, top-3)
    │  → 检索精度 +15-30%
    ▼
注入 LLM 上下文
```

#### 🆕 叙事结构索引检索 (Narrative-Indexed Retrieval)

三方审视共识：当前检索基于**语义相似度**——"找与当前文本相似的历史段落"。但创作者需要的往往是**叙事功能相似**——"找一个历史上写过的、处于同一节拍位置的场景"。

v7.0 在 ChromaDB metadata 中增加叙事功能标签，实现双重索引：

```python
# .agents/narrative_index.py (v7.0 P1)
def index_chapter_with_narrative_tags(chapter_text: str, chapter_num: int,
                                       beat: str, emotional_arc: str, pleasure_patterns: list):
    """每章入库时，附加叙事功能 metadata"""
    metadata = {
        "chapter": chapter_num,
        "beat": beat,                          # "fun_and_games" / "dark_night_of_soul" / ...
        "beat_position": compute_beat_progress(chapter_num, total_chapters),
        "emotional_arc": emotional_arc,        # "压抑上升" / "释放" / "余韵"
        "pleasure_patterns": pleasure_patterns, # ["slap_face", "treasure_obtain"]
        "narrative_function": classify_function(chapter_text),  # LLM 分类
    }
    chroma_client.add(documents=[chapter_text], metadatas=[metadata])

def retrieve_by_narrative_need(need: str, k: int = 3) -> List[str]:
    """示例:
    need = "我现在需要一个'假胜利'节拍的场景，主角以为赢了但其实踩进了陷阱"
    → 返回历史上所有 beat='fake_victory' 或 narrative_function='deceptive_win' 的段落
    """
    # 第一阶段: narrative filter (metadata 精准筛选)
    # 第二阶段: semantic re-rank (ReRanker 语义精排)
```

**与纯语义检索的对比**：

| 检索方式 | 查询 | 结果 |
|---------|------|------|
| 纯语义 | "假胜利" | 可能返回"角色真的赢了"的段落（语义混淆） |
| 🆕 叙事结构索引 | beat=fake_victory | **精准**返回历史中所有"假胜利"节拍的成功写法 |

#### 五层记忆架构（v7.0 扩展）

| 层级 | 机制 | 技术 | v7.0 升级 | 检索优先级 |
|:---:|------|------|------|:---:|
| **L1** | 实时上下文 | ChromaDB + ReRanker + 🆕叙事结构索引 | 双重索引 | 低（最近 5 章） |
| **L2** | 编译期 Wiki | Markdown 摘要 + (P2)ReIO 动态压缩 | 🔄 StoryWriter ReIO 替代 RAPTOR | 中（阶段性快照） |
| **L3a** | 🆕 语义记忆 | 概念图 (AriGraph 灵感) | 🆕 模式级归纳 | 中（跨章联想） |
| **L3b** | 事实记忆 | **NovelGraph 时序图 + SVO 三元组 + SQLite** | 🆕 SVO 层 | **最高（权威源）** |
| **L4** | 关系图谱 | Mermaid 可视化 | — | 中（可视化） |

### 4.5 M4 — 检测引擎 (S4+++ v7.0)

#### 七层检测体系 + 🆕 实时合规 linting

```
文本输入 (ch_v2)
      │
      ▼
┌──────────────────────────────────────────────────┐
│ Layer 1: 困惑度检测 (LLM PPL)                     │
│ > 50 SAFE │ 40-50 WARNING │ < 40 FATAL          │
│ ⚠️ 2026 年信号退化，仅作辅助                       │
├──────────────────────────────────────────────────┤
│ Layer 2: 突发性检测 (Burstiness)                  │
│ stdev(句长) / mean(句长) > 0.6 SAFE              │
├──────────────────────────────────────────────────┤
│ Layer 3: AI 词共现密度                            │
│ 100 词窗口内同群 AI 指纹词数量 ≤ 2               │
├──────────────────────────────────────────────────┤
│ Layer 4: 句长分布变异 [v1↔v2 对比]               │
│ 终稿比初稿变异系数下降 > 20% = WARNING             │
├──────────────────────────────────────────────────┤
│ Layer 5: 句法树变异                               │
│ 句法模式重复率 < 30% SAFE │ > 40% FATAL           │
├──────────────────────────────────────────────────┤
│ Layer 6: 语义跳跃度                               │
│ 相邻句子语义连贯度 > 0.7 SAFE                     │
├──────────────────────────────────────────────────┤
│ Layer 7: N-gram PPL [v5.0 升级] 🆕               │
│ 基于作者基线语言模型的 N-gram 困惑度                │
│ n-gram PPL > 基线均值 → 人类风格 (SAFE)            │
│ n-gram PPL < 基线均值×0.6 → 过于可预测 (FATAL)     │
│ 原理: AI文本在局部词选择上过于"可预测", PPL 更低     │
│ 来源: IEEE 2024 "N-Gram Perplexity-Based Detection"│
└───────────────┬──────────────────────────────────┘
                │
                ▼
        ┌──────────────┐
        │ 加权判定:     │
        │ Layer7(×3)   │  ← 权重最高
        │ Layer2(×2)   │
        │ Layer3(×2)   │
        │ Layer1(×1)   │
        └──────────────┘
```

**N-gram PPL vs KL 散度**：v4.1 的 Layer 7 使用 KL 散度对比 n-gram 频率分布。v5.0 改为 N-gram PPL——基于作者基线构建平滑 n-gram 语言模型，计算测试文本在该模型下的困惑度。N-gram PPL 区分信号比 KL 散度强约 30%（IEEE 2024 论文结论）。

#### 作者声音基线（v5.0 P0 降维至 12 维，确保 5 章样本稳定性；P2 扩展至 28 维）

> **p0 决策依据**：22 维在 5 章样本下存在过拟合风险。v5.0 P0 将强相关维度合并为 12 个核心维度，确保基线统计稳定性；P2 用 20+ 章样本量支撑 28 维完整指纹。

**P0 12 维核心基线**：

| 维度组 | 维度数 | 具体指标 | 合并说明 |
|--------|:---:|------|------|
| 句子结构 | 2 | 句长均值、句长标准差 | — |
| 标点指纹 | 2 | 省略号密度、破折号密度 | 逗号/句号密度合并到"功能词" |
| 功能词分布 | 2 | 结构助词比例(的/地/得合并)、动态助词比例(了/着合并) | 5维→2维 |
| N-gram 频谱 | 2 | bigram_spectrum, trigram_spectrum | — |
| 词汇特征 | 1 | Yule's K (词汇集中度，比单纯丰富度更稳定) | 2维→1维 |
| 认知站位 | 1 | 推测/断言比例 (推测性词数÷断言性词数) | 3维→1维 |
| 句法纹理 | 1 | 从属句比例 | 2维→1维 |
| 对话特征 | 1 | 对白占比 | — |

**P2 28 维完整指纹**（20+ 章基线积累后自动启用）：

P0 12维 + Burrows' Delta 50高频功能词 PCA 降维(8维) + 段落逻辑跳跃度(1维) + 从句类型多样性(1维) + 修辞手法密度波动(1维) + 字符级 trigram 分布(1维) + 词汇偏好集中度(2维) + 罕见词回避度(1维) + 情感极性波动(1维)

#### 🆕 风格漂移追踪 (Style Drift Monitor)

v5.0 不仅检测"这章像不像 AI"，更检测"这章像不像你"——追踪作者风格在多章创作中的渐变方向：

```python
# .agents/style_drift_monitor.py
def compute_drift(current_embedding, baseline, prev_10, ai_ref_embedding):
    drift_magnitude = cosine_distance(current_embedding, baseline)
    drift_direction = cosine_similarity(
        current_embedding - baseline,
        ai_ref_embedding - baseline
    )
    if drift_magnitude > 0.3 and drift_direction > 0.7:
        return DriftAlert("HIGH", "风格正朝AI参考方向漂移，请检查是否过度依赖AI建议")
    return DriftAlert("OK")
```

每 10 章生成一次漂移报告 → `review/drift_reports/`。

### 4.6 M5 — 交互接口 + Action Constraint + 🆕 结构化输出

#### v6.0 新增：Guidance 结构化输出保障

v5.0 的 Action Constant 是代码级硬拦截，但它只能"发现问题后阻断"，无法"从一开始就确保正确"。v6.0 在 S3 评审团等格式化输出环节引入 **Guidance** 库：

```python
# .agents/structured_jury.py
from guidance import models, gen

llm = models.LlamaCpp("models/qwen3.5-9b-instruct-iq4_xs.gguf")

jury_schema = {
    "logic_cop": {
        "verdict": ["PASS", "BLOCK"],
        "contradictions": [{"location": str, "severity": ["HIGH","MEDIUM","LOW"], "detail": str}],
        "causal_breaks": [{"event_id": str, "detail": str}]
    }
}

result = llm + prompt + gen(name="jury_result", json_schema=jury_schema)
```

**收益**：100% JSON 格式正确，消除 ActionConstraint 对格式类问题的误触发。S3 评审报告可直接被下游自动化处理。

#### v5.0 Action Constraint 硬拦截层（同 v5.0）

[保留原有 ActionConstraint 设计]

#### CLI 命令清单（v7.0 更新）

| 命令 | 说明 | v7.0 |
|------|------|:---:|
| `novel.py init` | 初始化项目目录结构 | — |
| `novel.py s0 --candidates 5` | S0 粗纲规划 | — |
| `novel.py s1 --chapter 1 --variants 3` | S1 引导生成 | 🔄 🆕自动路由至 WebNovel 专家 |
| `novel.py s2a --chapter 1` | S2a 手写 v1 | 🔄 🆕自动运行 SVO 三元组抽取 |
| `novel.py s2c --chapter 1` | S2c 对比分析 | — |
| `novel.py s3 --chapter 1` | S3 逻辑校验 | 🔄 异步流水线 + 🆕可选 DS-R1 逻辑警察 |
| `novel.py s4 --chapter 1` | S4+++ 风格检测 | 🔄 Layer 7 N-gram PPL + 🆕风格噪声注入 |
| `novel.py graph --sync` | 同步 NovelGraph | 🔄 含 SVO 三元组 + 语义概念图 |
| `novel.py graph --query "主角"` | 查询知识图谱 | 🔄 🆕支持叙事功能查询 |
| `novel.py graph --svo --chapter 5` | 🆕 查看 SVO 三元组 | 🆕 v7.0 |
| `novel.py graph --concepts` | 🆕 查看语义概念图 | 🆕 v7.0 |
| `novel.py beat --analyze` | 叙事节拍分析 | 🔄 🆕多理论库 + 节奏曲线 |
| `novel.py beat --rhythm` | 🆕 节奏曲线报告 | 🆕 v7.0 |
| `novel.py drift --report` | 风格漂移报告 | 🔄 🆕含风格噪声覆盖率 |
| `novel.py drift --inject` | 🆕 手动触发风格噪声注入 | 🆕 v7.0 |
| `novel.py test --run` | 运行黄金测试集 | 🔄 🆕含 PAN 2026 外部基准 |
| `novel.py test --pan` | 🆕 PAN 2026 专项评估 | 🆕 v7.0 |
| `novel.py abtest --models` | 模型 A/B 测试 | 🔄 🆕7 prompt (5创意+2推理) |
| `novel.py mash --dry-run` | 🆕 MASH 对抗测试 (P2) | 🆕 v7.0 |
| `novel.py profile --author` | 作者创作弱点画像 (P2) | — |
| `novel.py publish --chapter 1` | 发布 + 字数抖动 | 🔄 简化为仅字数抖动 |
| `novel.py status` | 查看系统状态 | 🔄 🆕含双模型健康状态 |
| `novel.py orchestrate --status` | 🆕 模型编排器状态 | 🆕 v7.0 |

### 4.7 M5a — 叙事节拍分析器 (Beat Analyzer v6.0)

**v6.0 进化**：从单一 Save the Cat! 扩展为**多叙事结构库**，按小说类型自动匹配：

```python
# .agents/beat_analyzer.py (v6.0)
NARRATIVE_FRAMEWORKS = {
    "save_the_cat": {        # 适用于: 升级流、传统长篇
        "opening_image":      (0, 0.05),
        "theme_stated":       (0.05, 0.1),
        # ... 15 节拍
    },
    "heros_journey": {       # 🆕 适用于: 玄幻、异世界
        "ordinary_world":     (0, 0.05),
        "call_to_adventure":  (0.05, 0.15),
        "refusal":            (0.15, 0.2),
        "mentor":             (0.2, 0.25),
        "crossing_threshold": (0.25, 0.3),
        # ... 12 步
    },
    "kishotenketsu": {       # 🆕 适用于: 中式章回体、都市情感
        "ki_intro":           (0, 0.2),    # 起
        "sho_develop":        (0.2, 0.55), # 承
        "ten_twist":          (0.55, 0.8),  # 转
        "ketsu_close":        (0.8, 1.0),   # 合
    },
    "webnovel_golden": {     # 🆕 适用于: 系统流、签到流
        "golden_three":       (0, 0.03),     # 黄金三章
        "golden_finger_intro": (0.03, 0.08), # 金手指引入
        "first_slap_face":    (0.08, 0.15),  # 首次打脸
        "escalation_cycle":   (0.15, 0.85),  # 升级循环
        "climax":             (0.85, 0.95),
    }
}
```

#### 🆕 爽点密度 → 节奏曲线升级

网文核心节奏指标。三方审视共识：v6.0 的正则表达式匹配过于粗糙——"打脸"不只是 `r"脸色一变"`，还可能是 3 段心理铺垫后的 1 句讽刺。v7.0 做两层升级：

**升级 1：正则 → LLM 分类器**

```python
# .agents/pleasure_density.py (v7.0)
def classify_pleasure_patterns(chapter_text: str, genre: str) -> dict:
    """用 LLM (低温度 0.1) 分类每个段落的爽点模式。
    正则兜底 (快速扫描)，LLM 精判 (对正则命中段落二次确认)。
    支持 genre-specific 模式库：
    - 系统流: 面板更新、数值暴涨、新功能解锁
    - 赘婿流: 身份反转、当众打脸、暗中布局
    - 修真流: 突破晋级、丹药奇遇、法宝认主
    """
```

**升级 2：密度 → 节奏曲线（四阶段张力模型）**

```python
# .agents/rhythm_curve.py (v7.0 P1)
def compute_rhythm_curve(chapter_text: str) -> RhythmCurve:
    """构建"预期构建→延迟满足→峰值释放→余韵"四阶段张力曲线"""
    segments = split_by_scene(chapter_text)  # 场景切分
    curve = []
    for i, seg in enumerate(segments):
        curve.append({
            "position": i / len(segments),
            "tension": estimate_tension(seg),      # LLM 估计紧张度 0-1
            "pleasure_intensity": classify_intensity(seg),  # LLM 估计爽度 0-1
            "phase": detect_phase(tension_history),  # buildup/delay/peak/afterglow
        })
    return RhythmCurve(curve, 
        metrics={"avg_buildup_length": ..., "peak_density": ..., 
                 "release_efficiency": ...})  # 释放效率 = 峰值后下降斜率

# 诊断输出示例:
# ⚠️ 第5章: buildup 阶段过长 (3.2段, 平均 1.8段)
# ⚠️ 第8章: peak 密度过高 (3个峰值/章), 建议分散或合并
# ✅ 第12章: 释放效率优秀 (峰值后 1.2段回归基线)
```

每 10 章生成节拍报告 → `review/beat_reports/`，含节拍覆盖图 + 爽点密度曲线。

### 4.8 M5b — 风格漂移监控 (Style Drift Monitor v7.0)

#### 从"防御性校正"到"主动性风格噪声注入"

v6.0 的主动风格校正仍是被动防御——漂移发生后才干预。三方审视共识：v7.0 应做**主动风格塑造**——在作者文本中强化独特的文风标记，让文本对 AI 检测器来说统计上更"陌生"。

灵感来源：MASH (ACL 2026 Findings) 的风格人性化方法——通过多阶段对齐将 AI 文本转换为人类风格。v7.0 反其道行之：**在已经是人类手写的文本中，主动强化作者指纹**。

```python
# .agents/style_drift_monitor.py (v7.0)
def inject_style_noise(baseline: AuthorBaseline, text: str) -> EnhancedText:
    """在作者手写文本中，主动强化其独特的文风标记，
    增加对 AI 检测器的统计"陌生度"，同时保持读感自然。
    """
    enhancements = {
        # 🆕 标点指纹强化（基于作者基线统计）
        "ellipsis_boost": baseline.ellipsis_density * 1.1,    # 省略号密度微幅上调
        "dash_boost": baseline.dash_density * 1.05,
        
        # 🆕 修辞习惯增强
        "preferred_metaphor_domains": baseline.top_metaphor_domains(3),  # 工业零件/自然/食物
        
        # 🆕 罕见词回升（对抗 IQ4_XS 的低频词压缩）
        "rare_vocab_recovery": baseline.top_rare_words(20),    # 作者独有的低频词汇
    }
    return text_with_markers(text, enhancements)

# 与 MASH 对抗流水线的协作：
# 1. Style Drift Monitor → 检测风格漂移方向
# 2. style_noise_injector → 主动强化作者指纹（防御性）
# 3. MASH 对抗改写器 → 对 AI 参考版做风格迁移（进攻性，§8.3）
```

每 10 章生成漂移报告 → `review/drift_reports/`，含风格噪声覆盖率和 AI 指纹距离。

---

### 4.9 🆕 M5d — 模型编排层 (Model Orchestrator)

#### 设计动机

v6.0 的 `model_switcher.py` 做动态量化切换，每次开销 20-30s。v7.0 双模型共存后，需要一个统一的编排层做请求路由和显存管理。

```python
# .agents/model_orchestrator.py (v7.0 P0)
class ModelOrchestrator:
    def __init__(self):
        self.models = {
            "webnovel_expert": ModelInstance("Qwen3-4B-WebNovel", port=8001, vram="1.5GB"),
            "main_model":     ModelInstance("Qwen3.5-9B",        port=8000, vram="4.5GB"),
        }
        self.routing_table = {
            "S1_creative":    "webnovel_expert",   # 创意引导 → 网文专家
            "S2b_reference":  "webnovel_expert",   # AI 参考版 → 网文专家
            "S3_logic_cop":   "main_model",        # 逻辑警察 → 主模型
            "S3_editor":      "main_model",        # 网文编辑 → 主模型
            "S3_qc":          "main_model",        # 语言质检 → 主模型
            "S4_detection":   "main_model",        # 风格检测 → 主模型
            "M5a_beat":       "webnovel_expert",   # 节拍分析 → 网文专家
            "M5b_drift":      "main_model",        # 漂移分析 → 主模型
            "concept_induction":"main_model",       # 语义归纳 → 主模型
        }
    
    def route(self, task_type: str, payload: dict) -> Response:
        """根据任务类型自动路由到对应模型"""
        model = self.routing_table.get(task_type, "main_model")
        return self.models[model].infer(payload)
    
    def health_check(self) -> dict:
        """双模型健康检查，任一挂掉 → 降级到存活模型"""
    
    def vram_pressure_handler(self):
        """显存压力 > 90% → 通知用户是否需要降低上下文窗口"""
```

**路由决策逻辑**：S1 创意任务由 WebNovel 专家处理（网文专用 LoRA 更懂网文范式）；S3/S4 评审仍由主模型处理（逻辑一致性需要更强的通用推理能力）。如果 P0 实验后 WebNovel 不满足要求，则整个系统退化为单模型模式。

### 4.9 M5c — 评审经验库 (Review Knowledge Base v6.0)

#### v6.0：从"检索"到"因果归纳"

v5.0 通过 RAG 检索相似历史问题。v6.0 增加**因果归纳**能力——完工一本后自动生成《作者创作弱点画像》：

```python
# .agents/author_profile.py (v6.0 P2)
def generate_author_profile(all_jury_reports: List[JuryResult]) -> AuthorProfile:
    """跨书因果归纳，生成个性化创作处方"""
    patterns = analyze_recurring_issues(all_jury_reports)
    return AuthorProfile(
        # 高频问题 Top-N
        top_weaknesses=[
            {"category": "角色动机", "frequency": 0.35, "trend": "worsening"},  # 频次上升
            {"category": "中段节奏", "frequency": 0.28, "trend": "stable"},
        ],
        # 个性化处方
        recommendations=[
            "在 config.yaml 中将'角色动机'检测敏感度 +20%",
            "S1 阶段自动注入角色动机相关的引导提示",
            "建议在第20-30章区间增加节拍密度检查",
        ],
        # 改善趋势
        improvement_areas=["对话信息量", "场景过渡"],
        # 与同类作者对比
        percentile_vs_peers={
            "plot_complexity": 0.65,      # 高于 65% 同类作者
            "character_depth": 0.40,      # 低于 60% 同类作者 ← 需加强
        }
    )
```

评审时注入上下文（RAG，同 v5.0）+ 完工后生成完整画像（归纳，v6.0）。

### 4.10 M6 — 文件系统（v7.0 更新）

```
novel-project/
│
├── AI_PROTOCOL.md
├── config.yaml                    ← 🔄 含双模型/MASH/节奏曲线/narrative_index配置
├── state.json                     ← 🔄 含 orchestrator_mode/svo_stats/semantic_concepts
│
├── .agents/
│   ├── model_orchestrator.py      ← 🆕 双模型路由编排 (替代 model_switcher)
│   ├── state_machine.py           ← 🔄 集成 orchestrator 路由
│   ├── diversity_sampler.py       ← 🔄 S1 路由至 WebNovel 专家
│   ├── virtual_jury_v5.py         ← 🔄 逻辑警察可选 DS-R1 + grammar 备选
│   ├── s4_plus_plus.py            ← ✓ Layer 7 N-gram PPL
│   ├── novel_graph.py             ← 🔄 SVO 三元组抽取 + ConStory-Bench
│   ├── semantic_memory.py         ← 🆕 概念图归纳 (P1)
│   ├── narrative_index.py         ← 🆕 叙事结构索引检索 (P1)
│   ├── double_sanitizer.py
│   ├── compile_wiki_v5.py         ← 🔄 P2 ReIO 动态压缩替代
│   ├── skill_loader.py            ← ✓ 静态前缀/动态内容分离
│   ├── voice_baseline.py          ← 🔄 12维(P0)→28维(P2)
│   ├── action_constraint.py       ← ✓ 代码级硬拦截
│   ├── mash_pipeline.py           ← 🆕 MASH 四阶段对抗 (P2)
│   ├── adversarial_consistency.py ← 🆕 假设性提问一致性检查 (P2)
│   ├── beat_analyzer.py           ← 🔄 多理论库
│   ├── rhythm_curve.py            ← 🆕 四阶段张力模型 (P1)
│   ├── pleasure_density.py        ← 🔄 正则→LLM 分类 + 类型化库
│   ├── style_drift_monitor.py     ← 🔄 风格噪声注入
│   ├── style_noise_injector.py    ← 🆕 作者指纹强化 (P1)
│   ├── review_knowledge_base.py   ← 🔄 因果归纳 + 跨书学习 (P2)
│   ├── behavior_camouflage.py     ← 🔄 简化：仅字数抖动
│   ├── adversarial_stylometry.py  ← P2 红蓝对抗 (MASH 方法论升级)
│   ├── model_ab_test.py           ← 🔄 7 prompt (5创意+2推理)
│   ├── pan2026_evaluator.py       ← 🆕 PAN 2026 基准集成 (P1)
│   ├── structured_jury.py         ← 🔄 grammar 备选
│   ├── author_profile.py          ← P2 作者弱点画像
│   ├── mcp_server.py              (P1)
│   ├── api_server.py              (P1)
│   └── scoring_dashboard.py       (P1)
│
├── canon/
│   ├── world.md
│   ├── characters.md              ← 🔄 NG 双向链接含时序+ SVO 信息
│   ├── rules.md
│   ├── timeline.md                ← 🔄 从时序图 + SVO 自动生成
│   ├── foreshadowing.md           ← 🔄 含因果链 + SVO 追溯
│   ├── emotional_arcs.md
│   └── subplot_board.md
│
├── voice/
│   ├── voice.md
│   ├── anti_slop_blacklist.md     ← 🔄 动态更新 (P2) + 风格噪声参考
│   ├── platform_compliance.md     ← 🔄 PAN 2026 对抗策略参考
│   └── author_baseline.json       ← 🔄 12维(P0)→28维(P2)
│
├── outline/
│   ├── rough_outline.md
│   ├── candidates.md
│   └── chapter_plans/
│       ├── ch01_plan.md
│       └── chXX_intent.json       ← 🔄 含 causal_link + structural_beat
│
├── chapters/
│   ├── ch01_v1.md
│   ├── ch01_v2.md
│   └── ...
│
├── wiki/
│   ├── summary_001_010.md
│   ├── character_snapshot.json
│   └── relation_graph.md
│
├── tests/                         ← 🔄 v7.0 评估体系
│   ├── golden_test_set/
│   │   ├── ground_truth/
│   │   ├── prompts/
│   │   └── expected/
│   ├── pan2026/                   ← 🆕 PAN 2026 数据集
│   │   ├── voight_kampff/
│   │   └── multi_author_style/
│   └── regression_suite.py
│
├── review/
│   ├── comparison/
│   ├── logic_reports/
│   ├── style_reports/
│   ├── jury_reports/
│   ├── beat_reports/              ← 🔄 含节奏曲线
│   ├── drift_reports/             ← 🔄 含风格噪声注入报告
│   ├── rhythm_reports/            ← 🆕 节奏曲线报告
│   ├── density_reports/           ← 🔄 类型化爽点库
│   ├── mash_reports/              ← 🆕 MASH 对抗评估 (P2)
│   └── dashboard.json
│
├── memory/
│   ├── chroma_db/                 ← 🔄 metadata 含叙事结构标签
│   ├── novel_graph.db             ← 🔄 含 event_causality + SVO 表
│   ├── concept_graph.db           ← 🆕 语义概念图存储 (P1)
│   ├── novel.db
│   ├── system_prompt_cache.bin    ← 🔄 含命中率监控
│   └── review_knowledge/          ← 🔄 含跨书模式数据 (P2)
│
└── .archive/
    └── ai_references/             ← 🔄 含 MASH 改写记录 (P2)
```

---

## 5. 数据设计

### 5.1 NovelGraph v5.0 核心表结构

#### entities（实体表，同 v4.1）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT PK | 实体 ID |
| `type` | TEXT | character/location/item/faction/rule/event/foreshadowing |
| `name` | TEXT | 实体名称 |
| `attributes` | TEXT (JSON) | 扩展属性 |
| `first_appeared_chapter` | INTEGER | 首次出现章节 |
| `last_appeared_chapter` | INTEGER | 最后出现章节 |
| `status` | TEXT | active/dead/destroyed/archived |

#### edges（关系边表，v5.0 时序化）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT PK | 关系 ID |
| `source_id` | TEXT FK | 源实体 |
| `target_id` | TEXT FK | 目标实体 |
| `relation_type` | TEXT | 盟友/敌对/师徒/暗恋... |
| `chapter` | INTEGER | 关系确立章节 |
| `valid_from_ch` | INTEGER | 🆕 关系生效章节 |
| `valid_until_ch` | INTEGER | 🆕 关系结束章节 (NULL=至今) |
| `status` | TEXT | 🆕 active/ended/contradicted |
| `confidence` | REAL | 置信度 |

#### 🆕 event_causality（事件因果表）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT PK | CAUSAL_001 |
| `cause_event_id` | TEXT FK | 原因事件 |
| `effect_event_id` | TEXT FK | 结果事件 |
| `chapter_latent` | INTEGER | 潜伏章节数 |
| `causality_type` | TEXT | triggers/leads_to/resolves/contradicts/foreshadows |
| `confidence` | REAL | 置信度 |

#### foreshadowing_graph（伏笔表，同 v4.1）

#### emotional_arcs（情感弧线表，同 v4.1）

### 5.2 config.yaml（v7.0 重构）

```yaml
# v7.0 重构：双模型共存 + 语义记忆 + MASH + 节奏曲线 + PAN 2026

model_orchestration:                 # 🆕 模型编排配置（替代 model_evaluation）
  mode: "dual_model"                 # dual_model | single_model
  models:
    webnovel_expert:                 # 🆕 S1 网文专家
      name: "TanXS/Qwen3-4B-LoRA-ZH-WebNovelty"
      gguf: "qwen3-4b-webnovel-q4_k_m.gguf"
      port: 8001
      n_ctx: 16384
      estimated_vram: "1.5GB"
      enabled: true                  # P0 实验后决定
    main_model:
      name: "Qwen3.5-9B-Instruct"
      gguf: "qwen3.5-9b-instruct-q4_k_m.gguf"
      quant: "Q4_K_M"                # 🆕 常驻 Q4_K_M，不切换
      port: 8000
      n_ctx: 4096                     # RTX 5060 8GB 实测上限; 32768 需 16GB+ 显存
      estimated_vram: "6.2GB"         # 实测 (模型5.68 + KV Cache)
    logic_cop_candidate:             # 🆕 DeepSeek-R1 角色重定位
      name: "DeepSeek-R1-Distill-Qwen-7B"
      gguf: "deepseek-r1-distill-qwen-7b-q4_k_m.gguf"
      port: 8002
      estimated_vram: "3.5GB"
      role: "logic_cop_only"         # 🆕 仅限于逻辑警察角色
  routing_table:                     # 🆕 任务→模型路由
    S1_creative: "webnovel_expert"
    S2b_reference: "webnovel_expert"
    S3_logic_cop: "main_model"       # 或 logic_cop_candidate (P0评估后)
    S3_editor: "main_model"
    S3_qc: "main_model"
    S4_detection: "main_model"
    M5a_beat: "webnovel_expert"
    M5b_drift: "main_model"
  fallback: "single_model"           # 编排失败降级策略

ab_test:                             # 🔄 7 prompt (5创意+2推理)
  creative_prompts: ["scene_desc", "dialogue", "action_seq", "psychology", "lore_setup"]
  logic_prompts: ["causal_logic", "timeline_contra"]  # 🆕 DeepSeek-R1 角色测试
  rounds: 3
  metrics: ["yules_k", "ai_fingerprint_density", "action_constraint_pass_rate", 
            "tokens_per_sec", "logic_f1"]  # 🆕 逻辑 F1

embedding:
  model: "BAAI/bge-m3"
  reranker: 
    model: "BAAI/bge-reranker-v2-m3"
    top_k: 3
    cpu_fallback: true              # 🆕 显存不足时 CPU 降级
    max_length: 512

prefix_caching:
  enabled: true
  cache_file: "memory/system_prompt_cache.bin"
  static_prefix_only: true
  hit_rate_monitoring: true         # 🔄 含告警阈值 <90%
  hit_rate_alert_threshold: 0.90    # 🆕

svo_extraction:                     # 🆕 SVO 三元组抽取
  auto_extract: true                # 每章 S2a 完成自动抽取
  llm_temperature: 0.1
  max_svos_per_chapter: 50

semantic_memory:                    # 🆕 语义概念图
  enabled: true                     # P1 启用
  update_interval_chapters: 1       # 每章更新
  concept_confidence_threshold: 0.3
  max_concepts: 200

narrative_index:                    # 🆕 叙事结构索引
  enabled: true                     # P1 启用
  index_dimensions: ["beat", "emotional_arc", "pleasure_pattern", "narrative_function"]
  retrieve_top_k: 3

beat_analyzer:
  frameworks: [save_the_cat, heros_journey, kishotenketsu, webnovel_golden]
  auto_match_by_genre: true
  rhythm_curve: true                # 🆕 节奏曲线分析
  rhythm_model: "four_phase"        # 🆕 四阶段张力模型 (buildup/delay/peak/afterglow)
  auto_analyze_every_n_chapters: 10

style_drift:
  monitor_window: 10
  warning_threshold: 0.3
  style_noise_injection: true       # 🆕 风格噪声主动注入
  noise_intensity: "adaptive"       # 根据漂移程度动态调整

mash_pipeline:                      # 🆕 MASH 对抗流水线 (P2)
  enabled: false                    # P2 启用
  rewriter_model_size: "0.1B"
  stages: ["sft", "dpo", "inference_refinement"]
  asr_target: 0.85

s2b:
  show_raw_text: false
  show_structural_analysis: true
  direction_count: 3                # 🆕 3方向随机
  fuzzification_level: "medium"     # 🆕 模糊化程度: low/medium/high
  cognitive_distance_bias: 0.7      # 🆕 偏向推荐最远认知距离的方向

golden_test_set:
  path: "tests/golden_test_set/"
  auto_run_on_change: true
  pan2026_integration: true         # 🆕 PAN 2026 外部基准

langfuse:
  self_hosted: true
  port: 3000

behavior_camouflage:
  word_count_jitter: [-200, 300]
  # publish_time_jitter_hours: 2   # 🆕 v7.0 删除
  # modification_count_min: 3      # 🆕 v7.0 删除

realtime_linting:                   # 🆕 实时合规 linting (P2)
  enabled: false
  plugin_type: "obsidian"           # obsidian | vscode
  check_layers: [2, 3]              # Layer 2(突发性) + Layer 3(AI词共现)
```

### 5.3 state.json（v7.0 扩展）

```json
{
  "current_chapter": 5,
  "current_stage": "S3",
  "orchestrator_mode": "dual_model",          // 🆕 dual_model | single_model
  "active_models": {                          // 🆕 当前加载模型状态
    "webnovel_expert": {"port": 8001, "status": "healthy", "vram": "1.5GB"},
    "main_model": {"port": 8000, "status": "healthy", "vram": "4.5GB"},
    "logic_cop": null                         // P0 评估中
  },
  "active_narrative_framework": "save_the_cat",
  "active_rhythm_model": "four_phase",        // 🆕 节奏模型
  "intent_file": "outline/chapter_plans/ch05_intent.json",
  "structural_beat": "fun_and_games",
  "svo_stats": {                              // 🆕 SVO 三元组统计
    "total_extracted": 127,
    "last_chapter_svos": 23,
    "extraction_confidence_mean": 0.72
  },
  "semantic_concepts": {                      // 🆕 语义概念图
    "total": 14,
    "active": 12,
    "contradicted": 2
  },
  "drift_history": [
    {"at_chapter": 10, "magnitude": 0.12, "direction": "neutral", "alert": "OK", 
     "noise_injection_intensity": 0.0}        // 🆕 风格噪声注入强度
  ],
  "style_noise_active": false,                // 🆕 风格噪声注入状态
  "pleasure_density": {
    "total": 3.2,
    "last_chapter": 4.1,
    "rhythm_curve_phase": "buildup"           // 🆕 当前节奏阶段
  },
  "test_results": {
    "last_run": "2026-06-04",
    "novelgraph_f1": 0.87,
    "s4_auc": 0.92,
    "pan2026_multi_author_f1": 0.78,          // 🆕 PAN 2026 风格变化检测 F1
    "all_passed": true
  },
  "ab_test": {
    "active": true,
    "test_type": "webnovel_expert_evaluation",  // 🆕  当前 A/B 测试类型
    "last_report": "review/ab_test_reports/2026-06-04.md"
  },
  "debts": [...],
  "completed_stages": ["S0","S1","S2a","S2c","S2d"],
  "baseline_chapters": ["ch01_v2","ch02_v2","ch03_v2","ch04_v2","ch05_v2"],
  "baseline_dimensions": 12,
  "prefix_cache": {
    "file": "memory/system_prompt_cache.bin",
    "last_updated": "2026-06-04",
    "hash": "a1b2c3d4",
    "hit_rate": 0.97,
    "alert_threshold": 0.90                  // 🆕 命中率告警阈值
  }
}
```

---

## 6. 工作流设计

### 6.1 完整流程

```
S0 ──▶ S1 ──▶ [Intent+🆕SVO] ──▶ S2a ──▶ S2b(可选) ──▶ S2c ──▶ S2d ──▶ S3 ──▶ S4+++ ──▶ 发布
 │       │         │              │         │             │        │       │       │
 │       │         │              │         │             │        │       │       │
 ▼       ▼         ▼              ▼         ▼             ▼        ▼       ▼       ▼
云端  🆕WebNovel  SVO三元组      作者     本地LLM        作者     作者    本地LLM  本地LLM
LLM    专家LLM    +创作意图     手写     🆕框架级切断   对比     重写    异步    七层检测
(脱敏) (引导)    chXX_intent    +NG校验  +3方向随机    +经验库  +🆕风格噪声 流水线  N-gram PPL
                 .json         +🆕叙事索引 +模糊化             注入
                 +causal_link

       ◀───── 🆕 双记忆架构 (事实+语义) ───────────────────────▶
       ◀───── NovelGraph 时序图 + SVO 因果链检测 ────────────▶
       ◀───── 🆕 叙事结构索引检索 ──────────────────────────▶
       ◀───── 债务队列 + 🆕 设定变更历史索引 ───────────────▶
       ◀───── Prefix Caching + Context Shifting ──────────▶
       ◀───── Style Drift Monitor + 🆕 风格噪声注入 ──────▶
       ◀───── Action Constraint 硬拦截层 ──────────────────▶
       ◀───── 🆕 实时合规 linting (P2 Obsidian插件) ────▶
```

### 6.2 各阶段详述

#### S0 — 粗纲规划

同 v4.1。

#### 🆕 S1 — 剧情引导生成 (v7.0：双模型路由)

| 属性 | v6.0 | v7.0 |
|------|------|------|
| 执行者 | 本地 Qwen3.5-9B Q4_K_M | 🆕 **WebNovel 专家** (TanXS/Qwen3-4B-WebNovel) or Qwen3.5-9B |
| 路由决策 | — | model_orchestrator 根据 P0 实验结果自动路由 |
| System Prompt | AI_PROTOCOL.md + 结构化约束 | 同 |
| 多温度采样 | [0.3, 0.7, 1.2] | 同 |
| 硬拦截 | ActionConstraint | 同 |
| **禁止** | 生成可直接复制粘贴的句子 | 同 |

#### S2a — 手写第一稿

同 v4.1，Intent 含 causal_link + structural_beat。

#### 🆕 S2b — AI 参考版（v7.0：框架级污染链切断）

**关键发现**：三方审视报告1指出——v6.0 的结构化分析虽然切断了句式级污染，但"此处建议增加感官细节——远处犬吠"仍然限定了**具体的叙事细节**。作者看了之后，认知框架仍然被 AI 限定。

| 属性 | v6.0 | v7.0 |
|------|------|------|
| 触发条件 | "真的写不出来" | 同 |
| 解锁条件 | 手写 ≥3 段 (500+ 字) | 同 |
| **展示方式** | 结构化分析："建议增加感官细节——远处犬吠" | 🆕 **3 方向随机 + 模糊化**：①方向A:"从多感官维度考虑环境——声音/气味/温度"②方向B:"在当前情绪基调上增加一个冲突信号"③方向C:"设置一个视觉锚点，暗示后续事件" |
| **改进** | — | 🆕 **模糊化**：不给出具体内容("远处犬吠")，只给抽象方向("多感官维度") |
| | — | 🆕 **三方向随机**：AI 给出 3 个不同方向，作者必须选择或自创第 4 个 |
| | — | 🆕 **认知距离量化**：三个方向的叙事距离各不同(近/中/远)，鼓励作者选择最远的 |
| 纪律 | AI 参考版不展示原文 | 同 + 🆕 结构建议经过模糊化处理后再展示 |

#### S2c — 对比分析

同 v4.1。

#### S2d — 手写第二稿 (v7.0：风格噪声注入)

| 属性 | v6.0 | v7.0 |
|------|------|------|
| 校验 | 声音基线 12 维对比（相似度 ≥ 0.7） | 同 |
| 风格追踪 | Style Drift Monitor 漂移追踪 | 同 |
| 维度问题 | 单维度偏离 > 30% → 标记 | 同 |
| 🆕 主动防护 | — | **风格噪声注入**：检测到 AI 倾向段落后，自动强化作者指纹（标点习惯/罕见词/修辞偏好），使文本对检测器统计上更"陌生" |

#### S3 — 逻辑校验（🆕 异步流水线）

**Stage 3A — 硬校验**：15 维清单 + 情感节拍。🆕 增加空间连续性 + 因果链完整性校验。

**Stage 3B — 虚拟评审团（异步流水线）**：

```
逻辑警察(0.3) ── BLOCK? ──▶ 立即退回 S2d
     │
   通过
     │
     ├── 网文编辑(0.3) ──┬── 并行 60s
     └── 语言质检(0.3) ──┘
              │
              ▼
           汇总判定
```

| 角色 | 职责 | 温度 |
|------|------|:---:|
| A_逻辑警察 | 时间线矛盾、设定吃书、伏笔漏洞、🆕因果断裂、🆕空间断裂 | 0.3 |
| B_网文编辑 | 节奏、爽点、钩子、代入感 (1-10 评分) | 0.3 |
| C_语言质检 | AI 指纹 + 风格漂移初步检查 | 0.3 |

> 任何角色 BLOCK → 退回 S2d；同一章 2 次未通过 → 熔断。

#### S4+++ — 七层检测

见 [4.5 M4 — 检测引擎](#45-m4--检测引擎)。

---

## 7. 接口与通信设计

### 7.1 AI_PROTOCOL.md 协议注入（v5.0：静态/动态分离 + Action Constraint）

```python
# .agents/skill_loader.py (v5.0 重构)
def inject_skill(task_type: str, chapter: int) -> dict:
    """分离静态前缀和动态内容，确保 Prefix Cache 命中"""
    static = build_static_skill_prefix()   # AI_PROTOCOL.md + config.yaml → Prefix Cached
    dynamic = build_chapter_context(chapter)  # 章节号、Intent → 每次动态拼接
    
    return {"system": static, "user": dynamic}
```

### 7.2 Prefix Caching + Context Shifting 组合方案

```
┌──────────────────────────────────────────────────────────────┐
│                  v5.0 推理加速双重机制                         │
│                                                              │
│  Prefix Caching (跨 Session):                                │
│    AI_PROTOCOL.md + config.yaml KV → 磁盘 (system_prompt_cache.bin) │
│    首次推理: 编码 System Prompt → 写磁盘                       │
│    后续推理: 读磁盘 → 直接复用 KV → 首 Token 延迟 -40%         │
│                                                              │
│  Context Shifting (同 Session 跨阶段):                        │
│    S1 → S3 → S4+++ 之间复用 KV Cache (--cache-reuse 256)     │
│    → 第 2/3 次推理速度 +30-40%                                │
│                                                              │
│  关键约束: System Prompt 禁止动态变量 → Prefix Cache 100% 命中  │
└──────────────────────────────────────────────────────────────┘
```

### 7.3 LLM 通信协议

```
POST http://localhost:8000/v1/chat/completions
{
  "model": "qwen3.5-9b",
  "messages": [
    {"role": "system", "content": "[AI_PROTOCOL.md + 结构化约束] (🆕 静态, Prefix Cached)"},
    {"role": "user", "content": "[章节内容 + canon数据 + NG上下文 + Intent] (动态)"}
  ],
  "temperature": 0.3,
  "max_tokens": 1000
}
```

温度策略同 v4.1。MCP/FastAPI 接口同 v4.1。

---

## 8. 安全与合规设计

### 8.1 防御体系（v7.0 五层 → 六层）

```
┌──────────────────────────────────────────────────────┐
│  输入层 (S0)                                          │
│  · SHA-256+盐值脱敏 · opt-out · 占位符轮换             │
├──────────────────────────────────────────────────────┤
│  生成层 (S1)                                          │
│  · 多温度采样 · AI_PROTOCOL.md · ActionConstraint 硬拦截    │
│  · 🆕 S1路由至 WebNovel 专家 (网文专用 LoRA)          │
├──────────────────────────────────────────────────────┤
│  检测层 (S4+++)                                       │
│  · 七层检测 · 12维声音基线 · N-gram PPL              │
│  · Style Drift Monitor 风格漂移追踪                   │
│  · 🆕 风格噪声主动注入 (强化作者指纹)                  │
├──────────────────────────────────────────────────────┤
│  行为层 (发布)                                        │
│  · 字数随机抖动 (±200~300) [仅保留此项，简化]          │
│  · 发布时间偏移 & 修改次数模拟 → P2 简化               │
├──────────────────────────────────────────────────────┤
│  🆕 MASH 对抗层 (P2)                                  │
│  · 四阶段黑盒对抗流水线 (MASH ACL 2026 方法论)        │
│  · 风格注入 SFT → DPO 对齐 → 推理时精炼              │
│  · 0.1B 改写器，92% ASR                              │
│  · StealthRL 强化学习逃逸 (互补方案)                   │
├──────────────────────────────────────────────────────┤
│  对抗层 (P2)                                          │
│  · 红蓝对抗：自动对 AI 参考版进行去 AI 化改写           │
│  · 找出最有效的反检测策略 → 反馈给作者                  │
│  · 动态黑名单：社区 AI 常用词爬取 + 自动去重             │
│  · 🆕 对抗性一致性检查（假设性提问）                   │
└──────────────────────────────────────────────────────┘
```

### 🆕 8.1b MASH 四阶段对抗流水线

三方审视共识：v6.0 的 P2 红蓝对抗描述过于泛化。MASH (ACL 2026 Findings, [2601.08564]) 提供了可落地的论文级方法论：

```
Stage 1: 风格注入 SFT
  采集作者历史文本 (20+ 章) → 构建风格语料对 (AI文本, 作者文本)
  → 在 Qwen3-1.8B 上 LoRA 微调风格改写器
  → 显存: ~1.5GB (训练时可释放主模型)

Stage 2: DPO 对齐
  构造偏好对: (改写版, AI原版) → DPO 训练
  → 保持语义完整性 + 去除 AI 指纹

Stage 3: 推理时精炼
  对 S2b AI 参考版自动运行改写器
  → 输出: 去 AI 化的结构建议
  → 延迟: ~2s/段落

Stage 4: PAN 2026 检验
  用 PAN 2026 Voight-Kampff 测试集验证改写效果
  → 目标 ASR ≥ 85% (内部测试)
```

**与 StealthRL 的互补**：
- MASH → 风格迁移路径（让 AI 文本更像作者）
- StealthRL → 对抗强化学习（针对特定检测器盲区）

```python
# .agents/mash_pipeline.py (v7.0 P2)
def run_mash_pipeline(ai_text: str, author_samples: List[str]) -> str:
    """四阶段对抗流水线"""
    # Stage 1: 风格改写器推理
    rewritten = style_rewriter.transfer(ai_text, target_style=author_style_embedding)
    # Stage 2: DPO 对齐校验
    if semantic_drift(ai_text, rewritten) > 0.15:
        rewritten = fallback_conservative_rewrite(ai_text)
    # Stage 3: 质量验证
    quality_score = style_drift_monitor.evaluate(rewritten)
    return rewritten if quality_score > 0.7 else ai_text
```

### 🆕 8.1c 对抗性一致性检查 (P2)

Report 2 的创新提议：引入"假设性提问"主动探寻潜在矛盾。例如不再仅检查"角色A是否已死亡"，而是自动生成反事实问题：

> "如果角色A想要在此时干预主角计划，他有能力做到吗？" 
> 如果答案肯定但小说中他没出现 → 标记"潜在角色动机缺失" Warning

```python
# .agents/adversarial_consistency.py (v7.0 P2)
def generate_counterfactual_questions(chapter: str, entities: List[Entity]) -> List[str]:
    """对每个活跃角色生成反事实干预问题"""
    questions = []
    for entity in active_entities(chapter):
        questions.append(
            f"如果{entity.name}想要在此时阻止主角，他/她有能力做到吗？"
            f"如果有能力但没出现，为什么不出现？"
        )
    return questions
```

### 8.2 行为模式伪装（🆕 v7.0 简化）

三方审视（报告1）指出：行为伪装增加了系统复杂度，但平台 AI 检测**主要基于文本内容**。v7.0 简化实现：仅保留"字数随机抖动"，删除发布时间偏移和修改次数模拟。

| 维度 | v6.0 | v7.0 |
|------|------|------|
| 字数抖动 | ±200~300 | ✅ 保留 |
| 发布时间偏移 | ±2h | ❌ 删除（收益不明确） |
| 修改次数模拟 | 3-8 次 | ❌ 删除（收益不明确） |
| 非固定发布间隔 | 24-72h | ❌ 删除（自然行为无需模拟） |

### 8.2 行为模式伪装（🆕 P1）

平台可能不仅分析文本，还分析发布行为。`behavior_camouflage.py` 生成人类化的发布参数：

- 每章字数在目标 ±200~300 间随机
- 发布时间在前一章发布后 24-72h 间随机，±2h 偏移
- 发布前模拟 3-8 次修改操作

### 8.3 番茄平台合规红线

| 检测项 | 平台阈值 | 本项目阈值 | v5.0 增强 |
|--------|:---:|:---:|------|
| 正文 AI 生成率 | >30% 降权 | **0%** | — |
| 连续风格突变 | 3 章 | **1 章** | 🆕 Style Drift 早期预警 |
| 行为模式异常 | — | — | 🆕 行为伪装模块 |
| N-gram 频率异常 | — | N-gram PPL ≥ 基线×0.6 | 🆕 算法升级 |

---

## 9. 评估体系与质量保障（🆕 v6.0）

> v6.0 核心增量。此前所有模块的效果都依赖人工主观判断，无法量化验证。本章建立从模型选型到一致性检测的完整评估闭环。

### 9.1 黄金测试集 (Golden Test Set)

```
tests/
├── golden_test_set/
│   ├── ground_truth/
│   │   ├── contradictions.json    # 10 个已知设定矛盾 → NovellGraph F1
│   │   ├── ai_samples.md          # 5 段已知 AI 生成文本 → S4+++ AUC
│   │   ├── style_drifts.json      # 5 个已知风格漂移案例 → Drift Monitor 召回率
│   │   └── prompt_quality.json    # 10 组 S1 prompt → 引导质量基准
│   ├── prompts/                   # 标准化测试 prompt
│   └── expected/                  # 期望输出
│
└── regression_suite.py            # 回归测试入口
```

**使用方式**：每次模块代码修改后，运行 `python novel.py test --run` 自动跑全量回归测试，输出各模块得分变化。任一模块得分下降 >5% → 阻止合并。

### 9.2 模块级评估指标

| 模块 | 评估指标 | 目标值 | 基准来源 |
|------|------|:---:|------|
| **NovellGraph 一致性** | 矛盾检测 F1 | ≥ 0.85 | ConStory-Bench + golden_test_set |
| **S4+++ 检测** | AI 文本检测 AUC | ≥ 0.90 | golden_test_set ai_samples |
| | 人类文本误报率 | ≤ 5% | 作者前 5 章手写样本 |
| **Style Drift** | 漂移方向召回率 | ≥ 0.80 | golden_test_set style_drifts |
| | 假阳性率 (OK→HIGH) | ≤ 5% | 作者前 10 章纯手写 |
| **S1 引导** | ActionConstraint 通过率 | ≥ 95% | 标准化 prompt × 3 轮 |
| | AI 指纹词密度 | ≤ 1.5/百字 | golden_test_set prompt_quality |
| **S3 评审** | 逻辑矛盾检出率 | ≥ 0.80 | ConStory-Bench |
| | 评审报告格式正确率 | 100% | 🆕 Guidance 结构化输出保证 |

### 9.3 ConStory-Bench 自动评估集成

Microsoft Research 2026 的 ConStory-Bench 是长篇故事一致性检测的标准化基准。v6.0 将其检测逻辑集成进 `novel_graph.py`。

每章 S2a 阶段自动运行，结果存入 `review/consistency_reports/`。`python novel.py test --benchmark` 生成全量一致性趋势图。

### 🆕 9.3b PAN 2026 数据集集成

三方审视（报告1）发现：PAN 2026 共享任务提供了可直接采用的标准化基准：

| PAN 2026 子任务 | 与本系统对应模块 | 用途 |
|:---|------|------|
| **Voight-Kampff AI Detection** | S4+++ 七层检测 | 用外部基准验证检测器性能 |
| **Multi-Author Writing Style Analysis** 🎯 | Style Drift Monitor | **直接用作风格漂移黄金测试集**——检测文本中作者风格变化的位置 |
| **Text Watermarking** | S4+++ 水印检测 | 验证平台水印检测的应对能力 |
| **Generative Plagiarism Detection** | S2c 版权清洁度 | 外部基准校准 |

**重点关注**：Multi-Author Writing Style Analysis 子任务与 Style Drift Monitor 目标高度吻合——都是检测"文本中作者风格何时发生变化"。直接采用 PAN 2026 的标注数据作为 Style Drift 的外部验证集。

```python
# .agents/pan2026_evaluator.py (v7.0 P1)
def run_pan2026_benchmark(task: str = "multi_author_style"):
    """运行 PAN 2026 相关子任务评估"""
    if task == "multi_author_style":
        # 加载 PAN 2026 风格变化标注数据
        # 与 Style Drift Monitor 输出对比
        # → F1 / Precision / Recall
    elif task == "voight_kampff":
        # 验证 S4+++ 对外部基准数据的检测 AUC
```

**注意**：PAN 2026 优胜方案将于 2026 年 9 月公布（CLEF 会议），届时反向工程其检测逻辑 → 强化 S4+++。如果系统成熟，可考虑以"对抗样本生成者"身份反向提交测试。

### 9.4 模型 A/B 测试框架

标准化实验框架（详见 §2.3.3），核心脚本 `model_ab_test.py`：

- 5 个标准 S1 prompt × 各候选模型 × 3 轮
- 自动计算词汇多样性 (Yule's K)、AI 指纹词密度、生成速度
- 输出对比报告 + 推荐决策 (`review/ab_test_reports/`)

### 9.5 🆕 Langfuse 自托管追踪 (P1)

```
部署: docker compose up langfuse (本地, 零外部依赖)
追踪项:
  · 每次 S1/S3/S4 LLM 调用: prompt 哈希 + 版本 + 延迟 + token 消耗
  · S3 评审团三个角色的独立 trace
  · ActionConstraint 触发次数和拦截率
  · 各模块代码版本与评估指标关联
```

收益：Prompt 变更有历史可追溯，评估指标可与具体代码版本关联，实现真正的数据驱动迭代。

---

## 10. 部署方案

### 10.1 环境要求

同 v4.1。

### 10.2 启动命令（v7.0：双模型共存）

```
# === 🆕 v7.0 方案A: 双模型共存 (model_orchestrator.py 统一管理) ===

# 终端 1: 主模型 (S3/S4 评审)
python -m llama_cpp.server \
  --model ./models/qwen3.5-9b-instruct-q4_k_m.gguf \
  --n_gpu_layers 35 --chat_format chatml \
  --n_ctx 4096 --cache-type-k q4_0 --cache-type-v q4_0 \
  --cache-reuse 256 --prompt-cache ./memory/system_prompt_cache.bin \
  --port 8000 --host 127.0.0.1
# 显存: 4.5GB + KV 0.5GB + overhead 0.3GB = 5.3GB

# 终端 2: WebNovel 专家 (S1 创意引导)
python -m llama_cpp.server \
  --model ./models/qwen3-4b-webnovel-q4_k_m.gguf \
  --n_gpu_layers 24 --chat_format chatml \
  --n_ctx 16384 --cache-type-k q4_0 --cache-type-v q4_0 \
  --port 8001 --host 127.0.0.1
# 显存: 1.5GB + KV 0.3GB + overhead 0.2GB = 2.0GB
# 总计: 5.3 + 2.0 = 7.3GB, 安全余量 0.7GB ✅

# 终端 3: 编排器 + CLI
python .agents/model_orchestrator.py  # 启动路由服务
python novel.py status                # 查看系统状态
python novel.py s1 --chapter 1        # → 自动路由到 WebNovel 专家 (port 8001)
python novel.py s3 --chapter 1        # → 自动路由到主模型 (port 8000)

# === 🟡 方案B: 单模型常驻 (当前运行方案) ===
python -m llama_cpp.server \
  --model ./models/qwen3.5-9b-instruct-q4_k_m.gguf \
  --n_gpu_layers 35 --chat_format chatml \
  --n_ctx 4096 --cache-type-k q4_0 --cache-type-v q4_0 \
  --cache-reuse 256 --prompt-cache ./memory/system_prompt_cache.bin \
  --port 8000 --host 127.0.0.1
# 显存: 4.5 + 0.5 + 0.3 = 5.3GB, 余量 2.7GB
# BGE-Reranker CPU fallback: 0GB GPU

# === P0 实验: DeepSeek-R1-Distill 逻辑警察测试 ===
python -m llama_cpp.server \
  --model ./models/deepseek-r1-distill-qwen-7b-q4_k_m.gguf \
  --n_gpu_layers 35 --chat_format chatml \
  --n_ctx 4096 --cache-type-k q4_0 --cache-type-v q4_0 \
  --port 8002 --host 127.0.0.1
# 显存: 3.5GB + KV 0.5GB + overhead 0.3GB = 4.3GB
# ⚠️ 仅评估用，不纳入常驻部署
```

---

## 11. 风险与约束分析

### 11.1 技术风险

| 风险 | 等级 | v7.0 缓解措施 |
|------|:---:|------|
| 8GB 显存约束 | 🟢低 | 双模型共存 ~6.0GB；单模型常驻方案 B 备选 |
| 🆕 双模型编排失败 | 🟡中 | model_orchestrator 自动降级为单模型模式 |
| Prefix Cache 命中失败 | 🟡中 | 命中率监控 + 动态变量审计 (P0-6) |
| 长篇 NG 膨胀 | 🟡中 | P2 HippoRAG 2 语义压缩 + ReIO 动态上下文 |
| 语义矛盾/因果检测误报 | 🟡中 | ConStory-Bench + PAN 2026 双基准校准 |
| SVO 自动抽取精度 | 🟡中 | LLM 抽取 + 人工抽查校准 (P1-A1) |
| 语义概念图噪音 | 🟡中 | contradict_count 机制，自动过期低置信度概念 |
| N-gram PPL 基线需要 5+ 章 | 🟡中 | 初期 KL 散度兜底，积累后自动切换 |
| ReRanker 显存溢出 | 🟢低 | CPU fallback 策略 (P0-5)，延迟可控 |
| ~~模型动态切换失败~~ | — | 🆕 v7.0 删除：双模型共存，无需切换 |
| Guidance 库兼容性 | 🟢低 | outlines/grammar 备选 (P1-C2) |
| 🆕 WebNovel 专家模型不达标 | 🟡中 | P0 实验后自动降级至方案 B 单模型 |
| 🆕 Speculative Decoding 负收益 | 🟢低 | P1 实测 classic draft，负收益则不启用；MTP 已排除（Dense 确认负收益） |

### 11.2 流程风险

| 风险 | 等级 | v7.0 缓解措施 |
|------|:---:|------|
| S4+++ 误报退回过多 | 🟡中 | 七层加权判定，golden_test_set + PAN 2026 双基准校准 |
| 声音基线初期不稳定 | 🟡中 | P0 12 维；P2 28 维；PAN 2026 Multi-Author 基准验证 |
| Style Drift 误报 | 🟢低 | 仅 HIGH 级别告警，风格噪声注入不强制 |
| 多叙事理论不匹配 | 🟡中 | 4 套理论按类型自动匹配，+ 🆕"实际网文结构反推"(P2)校准 |
| 黄金测试集标注质量 | 🟡中 | PAN 2026 外部基准作为客观锚点，避免自评循环 |
| S2b 模糊化是否充分 | 🟢低 | 3 方向随机 + 认知距离量化 (P1 A/B 验证) |

### 11.3 合规风险

| 风险 | 等级 | v7.0 缓解措施 |
|------|:---:|------|
| 平台 AI 检测升级 | 🔴高 | 七层检测 + N-gram PPL + PAN 2026 基准 + P2 MASH 对抗流水线 |
| 困惑度/突发性信号失效 | 🔴高 | N-gram PPL (Layer 7) + 12 维基线 + 🆕 节奏曲线作辅助特征 |
| 平台行为模式检测 | 🟡中 | 降级：仅保留字数抖动，主防文本层 |
| 平台水印检测 | 🟡中 | 正文 100% 手写，S2b 框架级切断 |
| 平台检测器模型切换 | 🔴高 | 🆕 MASH 多检测器对抗 (92% ASR) + PAN 2026 跨模型泛化 |
| S2b 间接污染导致风格漂移 | 🟡中 | 🆕 v7.0 框架级切断（模糊化+3方向随机） |

---

## 12. 演进路线图

> 基于四轮审视交叉验证融合。来源：负责人独立审视 [L] + 外部报告1 [R1] + 外部报告2 [R2] + 负责人综合裁决 [F]。所有条目标注来源与共识度。

### P0 — 立即实施（第 1-2 周，总工作量 ~16h）

**目标**：用数据锁定模型/量化/架构方案 + 暴露极端场景薄弱环节。

#### P0-A 底线安全校验（先于模型实验）

| # | 任务 | 来源 | 工作量 | 收益 | 共识度 |
|:---:|------|:---:|:---:|------|:---:|
| **P0-0** 🔥 | **末日生存压力测试** | [F][R1] | 2h | 一次性暴露所有薄弱环节 | 高 |
| | 场景A：故意输入 AI 污染文本 → 测 S4+++ 七层检测真实抗性 | | | | |
| | 场景B：手动制造 3 个设定矛盾 → 测 NovelGraph + SVO 因果链可追溯性 | | | | |
| | 场景C：双模型+32K ctx+异步 S3 并发 → 测显存真实峰值（确认 ≤7.8GB） | | | | |
| **P0-0b** | **网文实际节奏曲线数据分析** | [F] | 1.5h | 校准四阶段张力模型 | 独家 |
| | 分析 5 本番茄热门小说的章节级爽点分布，验证"锯齿波 vs 单峰波"假设 | | | | |

#### P0-B 模型实验（原 P0-1~P0-4）

| # | 任务 | 来源 | 工作量 | 收益 | 共识度 |
|:---:|------|:---:|:---:|------|:---:|
| P0-1 | **WebNovel 专家模型评估** 🔥 | [L] | 2h | 可能实现双模型共存 | 独家 |
| | 评估 `TanXS/Qwen3-4B-LoRA-ZH-WebNovelty-v0.0` | | | 若满足 → 双模型共存；不满足 → 方案B | |
| P0-2 | **DeepSeek-R1-Distill-7B 角色重定位测试** | [L][R1] | 2h | 明确逻辑警察角色 | 高 |
| | 重点测 S3 因果推理（ConStory-Bench 子集），非 S1 创意 | | | | |
| P0-3 | **双模型 vs 动态切换 时间成本实测** | [R1] | 0.5h | 量化切换开销 | 高 |
| P0-4 | **Q4_K_M vs IQ4_XS 文学质量 A/B 测试** | 三方 | 1.5h | 决定主模型量化策略 | 高 |

#### P0-C 基础保障（原 P0-5~P0-8）

| # | 任务 | 来源 | 工作量 | 收益 | 共识度 |
|:---:|------|:---:|:---:|------|:---:|
| P0-5 | **ReRanker 显存预算 + CPU fallback 策略** | [L][R1] | 0.5h | 防止 8GB OOM | 高 |
| P0-6 | **Prefix Caching 命中率审计 + 动态变量排毒** | [R1] | 0.5h | 避免缓存静默失效 | 中 |
| P0-7 | **ConStory-Bench 自动评估集成** | 原方案 | 2h | 一致性检测量化 F1 | 高 |
| P0-8 | **S2b 污染链升级**（3方向随机 + 模糊化处理） | [R1] | 1h | 认知污染框架级切断 | 中 |

**P0 决策节点**（P0-0~P0-4 完成后）：
- 主模型：Qwen3.5-9B Q4_K_M（已确认不会 OOM）
- 是否双模型：取决于 WebNovel 专家评估
- DeepSeek-R1：纳入或放弃
- 加速方案：MTP ❌ 已排除，classic draft SD P1 再测

---

### P1 — 短期实施（3-6 周，总工作量 ~14 天）

**目标**：夯实核心能力——SVO因果追踪、叙事索引检索、对抗快速原型、节奏曲线。

#### P1-A 知识层升级

| # | 任务 | 来源 | 工作量 | 说明 |
|:---:|------|:---:|:---:|------|
| P1-A1 | **SVO 三元组自动抽取** 🔥 | [L] | 2天 | STORYTELLER 灵感，LLM 自动抽取每章 SVOs |
| P1-A2 | **叙事结构索引检索** | [R2] | 1.5天 | ChromaDB metadata 增强，双重索引 |
| P1-A3 | **语义记忆层原型**（AriGraph 概念图）| [L][R2] | 2天 | + P1 新增：10章人工标注 gold set 测 LLM 归纳 precision/recall |
| P1-A4 | **HippoRAG 2 vs LightRAG 对比** | [L] | 1天 | 50 章样本测长篇记忆精准度 |

#### P1-B 认知交互升级 🆕

| # | 任务 | 来源 | 工作量 | 说明 |
|:---:|------|:---:|:---:|------|
| P1-B1 | **逻辑警察"杠精模式"** | [F][R1] | 0.5天 | temperature=1.2 刁钻视角：过度解读动机、放大瑕疵 |
| P1-B2 | **S1 矛盾性分支探索** (`--explore-contradictions`) | [F][R1] | 0.5天 | 生成 3 个互斥的"如果…会怎样？"分支 |
| P1-B3 | **Multi-Agent 辩论式节拍检测** | [F] | 1.5天 | Agent A(Snyder)+Agent B(Field)+Agent C(交叉验证) |

#### P1-C 对抗与评估 🆕

| # | 任务 | 来源 | 工作量 | 说明 |
|:---:|------|:---:|:---:|------|
| P1-C1 | **Adversarial Paraphrasing 快速原型** 🔥 | [F] | 1天 | 免训练对抗改写（替代原 P1-B1 MASH 设计文档，ICLR 2025 方法论） |
| P1-C2 | **PAN 2026 数据集集成** | [R1] | 0.5天 | Multi-Author Style Analysis → Style Drift 校准 |
| P1-C3 | **PAN 2026 Ensemble 检测器模拟器** | [F][R2] | 1天 | 用 PAN 公开数据训练多检测器 ensemble 作"最坏情况模拟器" |
| P1-C4 | **爽点密度→节奏曲线** | 三方 | 1.5天 | 正则→LLM分类+四阶段张力模型+类型化库 |

#### P1-D 基础设施

| # | 任务 | 来源 | 工作量 | 说明 |
|:---:|------|:---:|:---:|------|
| P1-D1 | **Speculative Decoding 实测**（classic draft only） | [L][R1] | 1天 | Qwen3.5-9B + Qwen3-1.8B draft；MTP ❌ 已排除 |
| P1-D2 | **Guidance→outlines/grammar 备选验证** | [R1] | 0.5天 | 兼容性测试 |
| P1-D3 | **Langfuse 自托管追踪** | 原方案 | 1.5天 | Prompt 版本化 + Token 追踪 |
| P1-D4 | **多叙事结构库完整实现** | 原方案 | 2天 | 4 套理论 + 自动匹配 |

---

### P2 — 中期实施（2-4 月）

| # | 任务 | 来源 | 说明 |
|:---:|------|:---:|------|
| P2-1 | **MASH + StealthRL 双轨对抗落地** 🔥 | [L] | 四阶段流水线 + RL 逃逸互补；P1 用 Adversarial Paraphrasing 快速替代 |
| P2-2 | **风格噪声主动注入** | [L][R2] | 强化作者指纹对标点/修辞/罕见词的统计标记 |
| P2-3 | **ReIO 动态上下文压缩**（替代静态 Wiki） | [L] | StoryWriter 的因果驱动上下文压缩 |
| P2-4 | **语义记忆层完整版**（跨章概念归纳） | [L][R2] | 50+ 章积累后启用自动模式归纳 |
| P2-5 | **对抗性一致性检查**（假设性提问） | [R2] | "如果角色A此时想干预，他有能力吗？" |
| P2-6 | **PAN 2026 优胜方案反向工程**（9月后） | [R1] | 获取 Voight-Kampff 优胜检测逻辑 |
| P2-7 | **TurboQuant 社区版评估** | [R1] | 3x 速度 + 7.5x KV 压缩隔离测试 |
| P2-8 | **GraphRAG + Narrative Knowledge Weaver 多 Agent KG 构建** | [F] | 🆕 AAAI 2025 方法论增强 NovelGraph |
| P2-9 | **28 维完整作者指纹** | 原方案 | 20+ 章基线积累后启用 |
| P2-10 | **《作者创作弱点画像》因果归纳** | 原方案 | 完工一本后自动生成 |
| P2-11 | **实时合规 linting 插件** | [R2] | Obsidian/VS Code 行号提示，无感护航 |
| P2-12 | **设定变更历史索引**（webnovel-writer 借鉴） | [L] | 竞品分析：债务队列→可检索变更日志 |
| P2-13 | **CreAgentive Agent Workflow 架构** | [F] | 🆕 P3 多 Agent 联邦参考（arxiv 2509.26461） |
| P2-14 | **stylometric-transfer 可解释风格画像** | [F] | 🆕 增强 Style Drift Monitor |

---

### P3 — 技术展望（触发条件制）

| 进化点 | 触发条件 | 来源 |
|--------|---------|------|
| **跨小说知识积累** | 完成 2 本以上长篇 | [L] |
| **情节指纹**（叙事模式作者认证） | 28维指纹 + 3本完本 | [R2] |
| **自定义 Importance Matrix**（作者语料量化校准） | P0 量化策略确定后 | [L] |
| **反事实推理**（"如果…会怎样？"分支推演） | NovelGraph 因果链 + SVO 完备 | 原方案 |
| **QLoRA 作者专属微调**（云端 or 离线完成） | 50+ 章反馈数据积累 | [R2] |
| **多 Agent 联邦**（MCP + A2A） | 模块 >15 且硬件升级至 16GB+ | 原方案 |
| **TurboQuant 正式版** | llama.cpp 官方合并 | [R1] |

---

### 🆕 v7.4：三层拆书深度架构（2026-06-08 穷举搜索验证）

> 基于 6 轮跨学科搜索（Preacher 2015 极端组设计 · Eisenhardt 定性饱和 · Shneiderman 1996 可视化箴言 · WebNovelBench 2025 · 番茄平台对标 · AuthorCraft 竞品），确认三层架构为最优方案。

```
L1（已有·库级）: 30本 × 取样20章 → BT排名 + 创作指导
    ├── 规则节奏 + LLM评分(600章) + Bayesian Stacking + DACA分歧对齐
    ├── WebNovelBench 8维综合评分
    └── 产出: creative_guidance/末世_创作指导.md

L2（新增·自动筛选）: Bootstrap + 子类型分层 → 智能选取深挖对象
    ├── Bootstrap 1000次 → 确认Top-3排名稳定性（scipy.stats.bootstrap）
    ├── 子类型分层: 打脸流×2 + 羁绊流×2 + 智斗流×2 = 6本
    └── Top-3(好) vs Bottom-3(差)，同子类型内配对

L3（新增·深度）: 6本全章拆解 → 对比诊断报告
    ├── Top-3: 全部章节 LLM评分 + 规则分析 → "怎么写好的"
    ├── Bottom-3: 仅规则分析（零LLM成本）→ "什么导致坏的"
    └── 产出: 同类型章节级对比诊断（钩子衰减点·高潮周期·弃书风险章号）
```

**设计依据**：30本全拆=54h不切实际；6本极端组设计（Preacher 2015）=统计效力高于全量随机抽样；Eisenhardt法4-10例达理论饱和；同子类型配对消除"苹果比橙子"混杂。

**实施清单**：
| 优先级 | 内容 | 代码量 | 状态 |
|:---:|------|:---:|:---:|
| P0 | min_commercial_score: 30→0 + BT排名 + BS Stacking + DACA + WebN8 | 已实现 | ✅ |
| P0 | `--deep 6` 模式: Bootstrap排名稳定性 + 子类型分层选书 + 全本拆书 | ~60行 | ⏳ |
| P1 | 同子类型对比诊断报告模板 | ~30行 | ⏳ |
| P2 | 后续30本→50本扩展 | — | — |

**文献索引**: Preacher 2015 Extreme Groups Design · Eisenhardt 2025 Qualitative Saturation · Shneiderman 1996 Overview+Zoom+Details · WebNovelBench arxiv 2505.14818 · AuthorCraft 2026 Full Manuscript Analysis
| **Kimi K2.6 蒸馏版追踪** | 发布时评估 | [F] 🆕 |

---

## 附录

### A. 设计决策记录

| 决策 | v6.0 选择 | v7.0 变更 | 裁决理由 |
|------|------|:---:|------|
| 图谱数据库 | SQLite (时序图) | 🆕 + SVO 三元组表 + 概念图表 | STORYTELLER 论文 + AriGraph 双记忆 |
| 量化策略 | 按任务动态切换 IQ4_XS/Q4_K_M | 🆕 **双模型共存 Q4_K_M 常驻** | 切换延迟 90s/章不可接受 |
| S1 创意模型 | Qwen3.5-9B Q4_K_M | 🆕 **WebNovel 专家模型** (P0评估) | 网文专用 LoRA，1.5GB，双模型共存 |
| DeepSeek-R1-Distill | P0 创意生成候选 | 🆕 **角色重定位**: P0 测试逻辑警察 | 推理链优势在因果分析，非文学表达 |
| S3 评审模式 | 异步流水线 + Guidance 结构 | 🆕 逻辑警察可选 DS-R1，Grammar 备选 | 模型角色重定位 |
| 知识记忆 | NovelGraph 单一事实层 | 🆕 **双记忆** (事实 + 语义) | AriGraph 论文: 从"发生了什么"到"意味着什么模式" |
| 检索方式 | BGE-M3 + BM25 + ReRanker | 🆕 **+ 叙事结构索引** | 从语义相似 → 叙事功能相似 |
| 节奏分析 | 爽点密度（正则） | 🆕 **节奏曲线**（LLM + 四阶段张力模型） | 爽点是节奏问题，非密度问题 |
| 风格保护 | 主动风格校正 | 🆕 **+ 风格噪声主动注入** | MASH 启示: 从防御到主动塑造 |
| 红蓝对抗 | 泛化描述 | 🆕 **MASH 四阶段流水线** | 论文级可实施方案 |
| 行为伪装 | 字数+时间+修改次数 | 🆕 **简化**: 仅保留字数抖动 | 文本检测为主，行为模式为辅 |
| S2b 展示 | 结构分析替代原文 | 🆕 **+ 3方向随机 + 模糊化** | 切断框架级认知污染 |
| 向量数据库 | ChromaDB | 保持 | — |
| LLM 框架 | 原生 API + Guidance | 🔄 + outlines/grammar 备选 | 兼容性风险 |
| 嵌入模型 | bge-m3 | 保持 | — |
| ReRanker | bge-reranker-v2-m3 | 🆕 **+ CPU fallback + 显存预算** | 8GB 安全 |
| 评估基准 | ConStory-Bench + golden_test_set | 🆕 **+ PAN 2026 数据集** | 外部独立基准 |
| 外部参考 | — | 🆕 **webnovel-writer 竞品借鉴** | 设定变更历史索引 |
| 实时检测 | 无 | 🆕 **Obsidian/VS Code linting 插件** (P2) | 无感合规护航 |

### B. 关键文件清单（v7.0）

| 文件 | 层级 | 优先级 | v7.0 状态 |
|------|------|:---:|:---:|
| `AI_PROTOCOL.md` | 协议层 | P0 | ✓ |
| `config.yaml` | 协议层 | P0 | 🔄 含双模型/MASH/节奏曲线配置 |
| `state.json` | 状态层 | P0 | 🔄 含 active_models/orchestrator_mode |
| `.agents/skill_loader.py` | 协议层 | P0 | 🔄 静态前缀/动态内容分离 |
| `.agents/model_orchestrator.py` | 编排层 | P0 | 🆕 双模型路由/显存编排（替代 model_switcher） |
| `.agents/state_machine.py` | 引擎层 | P0 | 🔄 集成 orchestrator 路由 |
| `.agents/diversity_sampler.py` | 引擎层 | P0 | 🔄 S1 路由至 WebNovel 专家 |
| `.agents/novel_graph.py` | 引擎层 | P0 | 🔄 SVO 三元组表 + 抽取管线 |
| `.agents/semantic_memory.py` | 知识层 | P1 | 🆕 概念图归纳逻辑 |
| `.agents/narrative_index.py` | 知识层 | P1 | 🆕 叙事结构索引检索 |
| `.agents/s4_plus_plus.py` | 引擎层 | P0 | ✓ |
| `.agents/virtual_jury_v5.py` | 引擎层 | P0 | 🔄 逻辑警察可选 DS-R1 |
| `.agents/voice_baseline.py` | 检测层 | P0 | 🔄 12维(P0)→28维(P2) |
| `.agents/action_constraint.py` | 安全层 | P1 | ✓ |
| `.agents/mash_pipeline.py` | 安全层 | P2 | 🆕 四阶段对抗流水线 |
| `.agents/adversarial_consistency.py` | 安全层 | P2 | 🆕 假设性提问一致性检查 |
| `.agents/beat_analyzer.py` | 分析层 | P1 | 🔄 多理论 + 节奏曲线 |
| `.agents/rhythm_curve.py` | 分析层 | P1 | 🆕 四阶段张力模型 |
| `.agents/pleasure_density.py` | 分析层 | P1 | 🔄 正则→LLM 分类 + 类型化库 |
| `.agents/style_drift_monitor.py` | 分析层 | P1 | 🔄 风格噪声主动注入 |
| `.agents/style_noise_injector.py` | 分析层 | P1 | 🆕 作者指纹强化 |
| `.agents/review_knowledge_base.py` | 分析层 | P1 | 🔄 因果归纳 + 跨书学习 (P2) |
| `.agents/behavior_camouflage.py` | 安全层 | P2 | 🔄 简化（仅字数抖动） |
| `.agents/adversarial_stylometry.py` | 安全层 | P2 | ✓ |
| `.agents/compile_wiki_v5.py` | 工具层 | P2 | 🔄 P2 ReIO 动态压缩替代 |
| `.agents/model_ab_test.py` | 评估层 | P0 | 🔄 7 prompt (5创意+2推理) |
| `.agents/pan2026_evaluator.py` | 评估层 | P1 | 🆕 PAN 2026 基准集成 |
| `.agents/author_profile.py` | 分析层 | P2 | ✓ |
| `memory/system_prompt_cache.bin` | 缓存 | P0 | 🔄 含命中率监控 |
| `tests/golden_test_set/` | 评估层 | P0 | 🔄 含 PAN 2026 外部数据集 |
| `memory/concept_graph.db` | 知识层 | P1 | 🆕 语义概念图存储 |
| `review/rhythm_reports/` | 分析层 | P1 | 🆕 节奏曲线报告 |

### C. 版本历史

| 版本 | 日期 | 核心变化 |
|------|------|----------|
| v1.0 | 2025-10 | 初始方案，Qwen2.5-7B，基础 S0-S4 |
| v2.0 | 2026-05 | 五层架构，ANTI-SLOP，虚拟评审团，编译期 Wiki |
| v2.1 | 2026-06-03 | S2b/S2c/S2d 分层重写机制 |
| v3.0 | 2026-06-04 | Qwen3.5-9B，S4++四层检测，多温度采样，零成本 API 扩展 |
| v4.0 | 2026-06-04 | AI_PROTOCOL.md，NovelGraph，MCP 协议化，S4+++六层检测 |
| v4.1 | 2026-06-04 | IQ4_XS+Q4_0 KV，声音基线 22 维，语义矛盾检测 |
| v5.0 | 2026-06-04 | Prefix Caching，时序图，异步 S3，N-gram PPL，Style Drift Monitor |
| v6.0 | 2026-06-04 | 七份审视融合，BGE-M3，ReRanker，A/B 测试框架，Golden Test Set，九层架构 |
| v7.0 | 2026-06-04 | 三份审视融合：双模型共存 + WebNovel专家 + SVO三元组 + 双记忆架构 + 叙事结构索引 + MASH + 节奏曲线 + PAN 2026 + 十层架构 |
| **v7.1** | **2026-06-04** | **第四轮审视（负责人综合裁决）: 排除 MTP（Dense -42%实测）+ 末日压力测试 + Adversarial Paraphrasing + 竞品差异化定位 + 杠精模式 + 矛盾性分支 + Multi-Agent节拍检测。确认 MVP 开发就绪。** |

### D. 审视方法论

v7.1 采用四轮交叉验证机制：

```
审视流程:
  第1轮: 负责人独立审视 [L]
          → 双模型架构·SVO三元组·语义记忆·模型编排层
  第2轮: 负责人穷举搜索 + 学术/GitHub 交叉验证 [F]
          → Adversarial Paraphrasing·CreAgentive·Narrative Knowledge Weaver
          → Stylometry·Three Stage Narrative Analysis·Multi-Agent Screenplay
  第3轮: 外部AI审视报告1 [R1] + 外部AI审视报告2 [R2]
          → [R1] 认知架构·情感索引·GAN闭环·末日测试
          → [R2] 平台算法对齐·竞品对标·推理效率·LongMINT/GAAMA/Synapse(待验证)
  第4轮: 负责人综合裁决 [F]
          → MTP Dense 负收益实测确认（-42%）→ 排除
          → 末日压力测试 → P0 第1优先
          → Adversarial Paraphrasing → 替代 MASH P1 设计文档
          → 竞品差异化定位 → 附录
          → 判决：停止设计迭代，开始 MVP 开发
  ↓
  交叉验证矩阵: 共识项赋高权重，独有项溯源验证
  ↓
  最终裁决: 四轮审视已收敛，无新增颠覆性发现，MVP 就绪
```

**关键参考文献**（v7.1 新增标 🆕）：

v7.0 已有：
- STORYTELLER (ACL 2025 Findings, [2506.02347])
- MASH (ACL 2026 Findings, [2601.08564])
- AriGraph (2024)
- StoryWriter (2025.6, [2506.16445])
- DOME (NAACL 2025)
- ConStory-Bench (Microsoft Research, 2026.3, [2603.05890])
- PAN 2026 (CLEF 2026)
- StealthRL (PAN 2026, [2602.08934])
- HippoRAG 2 (2025)
- Decoding Speculative Decoding (NAACL 2025, [2402.01528])

v7.1 新增 🆕：
- **Adversarial Paraphrasing** (ICLR 2025) — 免训练对抗改写，P1 MASH 轻量替代
- **Narrative Knowledge Weaver** (AAAI 2025) — 多 Agent KG 构建，P2 增强 NovelGraph
- **CreAgentive** (arxiv 2509.26461, 2025.9) — Agent Workflow 长篇创作引擎，P2 参考
- **Three Stage Narrative Analysis** (arxiv 2511.11857, 2025.11) — 情感弧线+结构+概念三阶段
- **Multi-Agent Screenplay Structure Analysis** (ScienceDirect, 2026) — Snyder/Field 计算化
- **Stylometry Recognizes Human vs LLM** (arxiv 2507.00838, 2025.7) — 最新区分特征
- **CREA** (arxiv 2504.05306, 2025.4) — 多 Agent 协作创作框架
- **Guiding Generative Storytelling with KGs** (arxiv 2505.24803, 2025) — N=15 KG 叙事用户研究

社区项目（v7.1 新增 🆕）：
- webnovel-writer (lingfengQAQ, 4.2K★)
- oh-story-claudecode (worldwonderer, 1.9K★, 2026.5) 🆕
- wordflowlab/novel-writer (Spec Kit 架构) 🆕
- stylometric-transfer (GitHub) 🆕
- MASH (GitHub, githigher/MASH) 🆕
- StealthRL (GitHub, suraj-ranganath/StealthRL) 🆕
- TanXS/Qwen3-4B-LoRA-ZH-WebNovelty-v0.0 (HuggingFace)
- NarrativeKnowledgeWeaver (GitHub, roytian1992) 🆕
- CreAgentive (GitHub, Austinggg/CreAgentive) 🆕

实测数据参考 🆕：
- **NJannasch 2026.05**: MTP on Qwen3.6-27B Dense = 28.5→16.4 t/s (-42%)，MoE = 98→144 t/s (+47%)
- **EQ-Bench Creative Writing v3**: Kimi K2.6 开源模型第1 (Elo 1781.6)，Qwen3 系列居前

### 🆕 E. 竞品差异化定位

v7.1 面对的主要竞品格局：

| 项目 | 架构 | 成本 | 合规保障 | 本地离线 | Stars |
|------|------|:---:|:---:|:---:|:---:|
| **webnovel-writer** | Claude Code Agent | ❌ API付费 | ❌ 无 | ❌ | 4.2K |
| **oh-story-claudecode** | Claude Code Skill | ❌ API付费 | ❌ 无 | ❌ | 1.9K |
| **novel-writer** (WordFlowLab) | Spec Kit + API | ❌ API付费 | ❌ 无 | ❌ | 300+ |
| **v7.1（本项目）** | **llama.cpp 双模型** | **✅ ¥0** | **✅ 十一层** | **✅** | — |

**差异化核心**：所有竞品依赖付费 API（Claude/DeepSeek），无一解决"零成本+本地离线+合规安全"三角。v7.1 的独特价值在于：
1. **零成本运行**：8GB 消费级显卡全本地部署，API 账单为 ¥0
2. **合规安全**：正文 100% 手写 + 七层 AI 检测 + PAN 2026 外部基准
3. **认知保护**：S2b 污染链框架级切断——所有竞品均无此设计
4. **长篇记忆**：NovelGraph 时序图 + SVO 三元组 + 语义概念图，专为 200 万字场景设计

竞品值得借鉴的能力（非核心，P2 参考）：
- webnovel-writer: 37 题材模板 + 运行时合同系统
- oh-story-claudecode: 扫榜→拆文→写作→去AI味全流程 Skill 包设计
- novel-writer: SDD 七步方法论

---

### 🆕 14. 架构重构说明（v6.0→v7.0→v7.1）

#### v6.0→v7.0 重构必要性评估

经过专业审视交叉验证，v7.0 需要的架构调整评估如下：

| 变化维度 | v6.0 能吸收？ | 需要重构？ | 类型 |
|---------|:---:|:---:|------|
| 双模型共存 + 编排层 | 否 | ✅ | **新增层 0（模型编排层）** |
| 知识层分裂（事实+语义） | 否 | ✅ | **分裂层 3→3a+3b** |
| SVO 三元组 | 是 | — | 在 NovelGraph 内新增表 |
| 叙事结构索引 | 是 | — | 在 ChromaDB 新增 metadata |
| MASH 对抗流水线 | 是 | — | 在安全层新增子模块 |
| 节奏曲线 | 是 | — | 在分析层升级 |
| 风格噪声注入 | 是 | — | 在分析层新增子模块 |
| 实时合规 linting | 是 | — | 在交互层新增插件 |
| PAN 2026 集成 | 是 | — | 在评估层新增数据源 |
| 行为伪装简化 | — | — | 在安全层删减 |

**v6→v7 裁决**：结构性升级（非推倒重来）
- v6.0 的 8 层核心架构**全部保留**
- 知识层 **分裂** 为事实记忆层 (L3) + 语义记忆层 (L4)
- **新增** 模型编排层 (L0)
- 总计：10 层架构

#### v7.0→v7.1 增量修正

v7.1 不做结构性重构，仅做事实性修正：

| 变化维度 | 类型 | 说明 |
|---------|:---:|------|
| MTP 加速方案 | ❌ 删除 | 实测 Dense 模型 -42%，仅保留 classic draft SD |
| Qwen3.6 小模型评估 | ❌ 删除 | Qwen3.6 无 4B/9B 尺寸 |
| 末日生存压力测试 | 🆕 新增 P0 | 三场景极端测试，P0 第1优先 |
| 网文节奏曲线数据校准 | 🆕 新增 P0 | 5 本番茄热门验证四阶段模型 |
| Adversarial Paraphrasing | 🆕 新增 P1 | ICLR 2025 免训练方案，替代 MASH P1 设计文档 |
| 逻辑警察杠精模式 | 🆕 新增 P1 | temperature=1.2 刁钻视角 |
| 矛盾性分支探索 | 🆕 新增 P1 | S1 `--explore-contradictions` |
| Multi-Agent 辩论式节拍 | 🆕 新增 P1 | 多理论交叉验证节拍检测 |
| 竞品差异化定位 | 🆕 附录 E | 竞品矩阵 + 核心差异化 |
| PAN 2026 Ensemble 模拟器 | 🆕 新增 P1 | 多检测器最坏情况模拟 |

**一次性的重构成本**（不变）：
- `model_switcher.py` → `model_orchestrator.py`（重写，约 200 行）
- `novel_graph.py` 新增 SVO 表 + 抽取管线（新增，约 150 行）
- `semantic_memory.py`（新增模块，约 200 行）
- 其余模块均为**增量修改**，不改变现有接口

---

> **文档结束** · 关联文档：[AI_PROTOCOL.md](AI_PROTOCOL.md) · [config.yaml](config.yaml)
> **最终审视裁决**: 四轮交叉验证（负责人×2 + 外部AI×2），经负责人综合裁决后落地为 v7.1 方案。MTP 已排除（Dense -42%实测），末日压力测试为 P0 第1优先，MVP 开发就绪。
