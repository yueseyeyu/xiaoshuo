# 附录 + 架构重构说明

> Extracted from DESIGN.md | [Back to index](../../DESIGN.md)

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

---


