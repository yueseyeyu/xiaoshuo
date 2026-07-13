# 9. 评估体系与质量保障

> Extracted from DESIGN.md | [Back to index](../../DESIGN.md)

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

### 🆕 9.6 三层标注评估体系 (v8.8)

> **设计目标**：以最低标注成本，构建可信的章节质量 ground truth，校准 AI 评分与本地模型评分。
>
> **文献依据**：
> - Fernandes et al. (ACL 2023, cited 155x): 分层采样(stratified sampling)在文本质量评估中优于均匀采样
> - Wan et al. (AAAI 2023, cited 92x): "controversial samples that maximize disagreement" → 提升标注公平性与质量
> - Baumler et al. (ACL Findings 2023, cited 42x): "Which examples should be multiply annotated? active learning when annotators may disagree"
> - Nuggehalli et al. (2023, cited 21x): 分歧驱动采样比随机采样节省 ~80% 标注预算
> - Horchani (Frontiers in AI 2026): 综述确认 uncertainty/disagreement sampling 为标注效率 SOTA
> - **Kim (arXiv 2026)**: "Augmenting Human Evaluation with LLM Judges" — LLM评全量+人工评子样本两阶段设计，"在LLM预测性低的评估上分配更多人工标注"
> - **Unell et al. (OpenReview 2025)**: "Smarter Sampling for LLM Judges" — 智能采样仅需全量5%标注预算即可可靠评估

#### 9.6.1 架构总览

```
┌─────────────────────────────────────────────────────────┐
│                    三层标注评估体系                        │
├─────────────┬───────────────┬───────────────────────────┤
│  Tier 1     │  Tier 2       │  Tier 3                   │
│  AI 全读    │  本地模型      │  人工标注                  │
│  (DSV4等)   │  (Qwen 9B)    │  (作者/编辑)               │
├─────────────┼───────────────┼───────────────────────────┤
│ 10%分层采样 │ 按质量分级采样  │ 分歧驱动+校准锚点          │
│ 全文不截断  │ 节奏峰谷对齐   │ 双维度分歧度量             │
│ ~200章/书   │ S50/A30/C20   │ 10-20章/书                │
├─────────────┼───────────────┼───────────────────────────┤
│ MAE=0.55✅  │ MAE~1.4(待校准)│ Ground Truth              │
│ (已验证)    │ 覆盖面广       │ 信息增益最大化             │
└─────────────┴───────────────┴───────────────────────────┘
         ↓ MAE/Bias 对比 ↓        ↓ 校准反馈 ↓
         ┌─────────────────────────────────┐
         │       校准与迭代闭环             │
         │  1. Tier3 人工 → 校准 Tier1/2   │
         │  2. 分歧大的章节 → 改进 prompt   │
         │  3. 系统性 Bias → 修正评分偏移   │
         └─────────────────────────────────┘
```

#### 9.6.2 Tier 1: AI 全读 (已验证)

**策略**: 10% 分层采样，全文不截断，每批 2-3 章防上下文过载。

**分层比例** (按全书章节位置):

| 层级 | 位置 | 采样比例 | 理由 |
|------|------|:--------:|------|
| Opening | 0-3% | 3% | 黄金三章，决定弃书率 |
| Rising | 3-30% | 27% | 上坡期，节奏建立 |
| Mid | 30-60% | 30% | 中段平稳，最容易注水 |
| Climax | 60-90% | 30% | 高潮密集，爽感峰值 |
| Ending | 90-100% | 10% | 收尾质量 |

**验证结果** (废土崛起 203 章):
- Intensity MAE = 0.75, Retention MAE = 1.00
- Bias = -0.45 (轻微低估，可校准)
- 显著优于本地 Qwen (MAE=1.42, Bias=+1.02)

**工具**: `scripts/ai_annotate.py` v2.0

#### 9.6.3 Tier 2: 本地模型按质量分级采样 (v8.8修正)

**策略**: 本地 Qwen 9B 评分，采样量按书籍质量分级决定，节奏峰谷对齐。

**采样量按书籍质量分级** (依据 Kim 2026: "在LLM预测性低的评估上分配更多样本"):

| 质量分级 | 采样量 | 自一致性 | 理由 |
|----------|:------:|:--------:|------|
| S (标杆) | 50章 | sc=3 | 叙事最复杂, LLM预测性最低, 需最多样本 |
| A (优秀) | 30章 | sc=1 | 高质量但不需与S同等 (v8.8: 50→30) |
| B+/B/B- | 30章 | sc=1 | 中等质量, 30章足够 |
| C (反面) | 20章 | sc=1 | 套路化高, LLM预测性高 (v8.8: 30→20) |

> **v8.8 变更说明**: A级从50降回30 (v8.7提50是出于"排名可比性"内部需求，非研究支撑)；C级从30降回20 (C级不参与排名竞争，套路化高少样本即可)

**节奏峰谷对齐** (采样策略, 非采样量):
- 在采样量内，按 pleasure_intensity 将章节分为高峰(S)/中段(A)/低谷(B)三层
- 分配比例: S峰50% / A中30% / B谷20%
- 每层内滑动窗口采样，选窗口内最接近均值的章节

**优势**:
- 按质量分级差异化投入，标杆书多读、反面教材少读
- 节奏对齐避免"只采高潮或只采平淡"的偏差
- 与 Tier 1 的 10% 采样互补（Tier 1 按位置分层，Tier 2 按节奏分层）

#### 9.6.4 Tier 3: 人工标注 — 分歧驱动 + 校准锚点

**核心改进**: 人工标注不应随机选，而应选 |AI_score - Local_score| 最大的章节。

**文献支撑**:
- Wan et al. (AAAI 2023): "maximize the disagreement" → 10 章人工标注信息量 ≈ 30 章随机
- Nuggehalli et al. (2023): 分歧驱动采样节省 ~80% 标注预算

**采样策略 (三部分)**:

**Part A: 校准锚点 (3-5 章, 固定)**
- 选取: ch1 (开篇), 全书25%处, 50%处, 75%处, 末章
- 目的: 检测 AI 和本地模型的系统性 Bias（如"开篇一律高估"）
- 这些章节不依赖分歧，是固定参考点

**Part B: 分歧驱动采样 (5-12 章)**
- 双维度分歧度量:
  ```
  disagreement = 0.6 × |AI_intensity - Local_intensity| 
               + 0.4 × |AI_retention - Local_retention|
  ```
  - intensity 权重 0.6: 验证数据显示 intensity 信号更可靠 (MAE 更低)
  - retention 权重 0.4: retention 与 intensity 高度相关，降权避免冗余
- 选取 disagreement 最大的 5-12 章
- **覆盖约束**: 确保选出的章节覆盖 ≥3/5 叙事层 (Opening/Rising/Mid/Climax/Ending)

**Part C: 补充采样 (2-3 章, 可选)**
- 选取 Tier1 和 Tier2 都给极端分(全9或全2)但彼此一致的章节
- 目的: 验证"两个模型都同意的极端值"是否准确
- 如果 Part B 已覆盖足够多样性，可省略

**总量**: 10-20 章/书

#### 9.6.5 迭代闭环

```
Round 1:
  Tier1 AI评分 → Tier2 本地评分 → Tier3 人工标注(分歧驱动)
  ↓
  计算 MAE/Bias → 识别系统性偏差 → 修正 prompt/阈值
  ↓
Round 2 (可选):
  用 Round 1 校准后的模型重新评分 → 新的分歧章节 → 补充人工标注
  ↓
  收敛判定: 新增人工标注的 MAE < 上一轮 MAE × 0.9 → 停止迭代
```

**工具**: `scripts/three_tier_eval.py`

---

