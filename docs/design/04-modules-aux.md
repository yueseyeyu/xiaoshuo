# 4. 模块设计 (下半: 交互/节拍/漂移/编排/文件系统)

> Extracted from DESIGN.md | [Back to index](../../DESIGN.md)

---

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

#### CLI 命令清单（v7.4 更新）

| 命令 | 说明 | v7.4 |
|------|------|:---:|
| `novel.py init` | 初始化项目目录结构 | — |
| `novel.py status` | 查看系统状态 | 🔄 🆕含双模型健康状态 |
| 🆕 **`novel.py session`** | **交互式写作会话 REPL: S0->S4 完整工作流** | **🆕 v7.4 核心入口** |
| `novel.py worldbuild` | S0 世界观构建：5阶段 Socratic | — |
| 🆕 `novel.py outline` | S0 大纲生成：基于世界观生成三层大纲 | 🆕 v7.4 |
| 🆕 `novel.py characters` | S0 角色设计：4维度 Socratic 引导 | 🆕 v7.4 |
| `novel.py s1 --chapter 1 --variants 3` | S1 引导生成 | 🔄 🆕自动路由至 WebNovel 专家 |
| `novel.py s2a --chapter 1` | S2a 手写 v1 | 🔄 🆕自动运行 SVO 三元组抽取 |
| `novel.py s2c --chapter 1` | S2c 对比分析 | — |
| 🆕 **`novel.py write --chapter 5`** | **提交章节正文: 从文件加载或交互输入** | **🆕 v7.4** |
| `novel.py s3 --chapter 1` | S3 逻辑校验 | 🔄 异步流水线 + 🆕可选 DS-R1 逻辑警察 |
| `novel.py s4 --chapter 1` | S4+++ 风格检测 | 🔄 Layer 7 N-gram PPL + 🆕风格噪声注入 |
| 🆕 **`novel.py decisions --chapter 5`** | **章节决策采集: 风格涌现数据源** | **🆕 v7.4** |
| `novel.py analyze --genre 末世` | 一键全量分析管线 | — |
| `novel.py deep --genre 末世` | 二阶段深度拆书 | — |
| `novel.py intent --text "这章太拖了"` | 意图翻译为可执行建议 | — |
| `novel.py test` | 运行回归测试 & 黄金测试集 | 🔄 🆕含 PAN 2026 外部基准 |

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

v6.0 的 `model_switcher.py` 做动态量化切换，每次开销 20-30s。v7.0 曾设计双模型共存架构，但实测 Qwen3.5-9B (~6.2GB) + DeepSeek-R1-0528-Qwen3-8B (~5.9GB) 共约 12GB，超出 8GB VRAM 上限。v7.5 实际落地为**单 GPU 顺序切换**方案：

```python
# .agents/model_orchestrator.py (v7.5)
class ModelOrchestrator:
    def __init__(self):
        self.servers = {
            "main_model":  ModelServer("Qwen3.5-9B", port=8000, vram="6.2GB"),
            "logic_cop_candidate": ModelServer("DeepSeek-R1-0528-Qwen3-8B", port=8002, vram="5.9GB"),
        }
        self.routing_table = {
            "S1_creative":          "main_model",     # 创意引导
            "S2b_reference":        "main_model",     # AI 参考版
            "S3_logic_cop":         "main_model",     # 逻辑审查
            "S3_editor":            "main_model",     # 网文编辑
            "S3_qc":                "main_model",     # 语言质检
            "S3_cross_check":       "logic_cop_candidate",  # 交叉标注 (仅 cross_review Phase 2)
            "S4_detection":         "main_model",     # 风格检测
            "M5a_beat":             "main_model",     # 节拍分析
            "M5b_drift":            "main_model",     # 漂移分析
        }
    
    def chat(self, task_type, messages, **kwargs):
        """路由到目标模型推理"""
        target_key = self.routing_table.get(task_type, "main_model")
        target = self.servers.get(target_key)
        if target and target.health_check():
            return target.chat(messages, **kwargs)
        # 降级至 main_model
        return self.servers["main_model"].chat(messages, **kwargs)
    
    def swap_to(self, target_key, timeout=120) -> bool:
        """顺序切换模型：停当前 → 启目标 → 等就绪"""
        # v7.5: 解决 8GB VRAM 下单 GPU 部署限制
        # 内部调用 switch_model.py 的 stop + start 流程
        # 返回 False 时调用方应降级
    
    def health_check(self) -> dict:
        """所有模型健康检查，挂掉的模型路由自动降级到存活模型"""
```

**核心流程（`cross_review.py`）**：
```
Phase 1: Qwen3.5-9B 全面审查 (S3_logic_cop→main_model)
         ↓ swap_to("logic_cop_candidate")
Phase 2: DeepSeek-R1-0528 专长维度交叉标注 (S3_cross_check→logic_cop_candidate)
         ↓ swap_to("main_model")
Phase 3: 合并报告，标记 has_additions
```

切换开销约 2-3 秒（模型保持加载状态）。swap_to 内置 `health_check()` 轮询 + 超时保护，失败时 cross_review 自动降级为单模型模式。

**路由降级策略**：`S3_cross_check` 路由到 `logic_cop_candidate`，若交叉模型不可用，`chat()` 自动回退到 `main_model`。所有 S3 评审任务默认走主模型，仅交叉审查阶段二由 `swap_to()` 临时切换。

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


