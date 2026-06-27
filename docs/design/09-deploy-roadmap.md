# 10. 部署 + 11. 风险 + 12. 演进路线图

> Extracted from DESIGN.md | [Back to index](../../DESIGN.md)

---

## 10. 部署方案

### 10.1 环境要求

同 v4.1。

### 10.2 启动命令（v7.0：双模型共存）

> **v7.5 更新**：双模型共存方案因 8GB VRAM 不足以同时容纳 Qwen3.5-9B (~6.2GB) + DeepSeek-R1-0528-Qwen3-8B (~5.9GB) 而废弃，实际落地为**单 GPU 顺序切换（swap_to）**。参见 [04-modules-aux.md §4.9 M5d](04-modules-aux.md#49--m5d--模型编排层-model-orchestrator)。以下为 v7.0 历史设计方案，**不代表当前实现**。当前启动方式：`scripts\start_model.bat`（仅启动主模型 Qwen3.5-9B port 8000），交叉模型由 `model_orchestrator.swap_to()` 按需切换。

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


