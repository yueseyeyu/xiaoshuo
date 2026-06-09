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


