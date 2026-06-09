# 5. 数据设计 + 6. 工作流设计

> Extracted from DESIGN.md | [Back to index](../../DESIGN.md)

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


