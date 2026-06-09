# 8. 安全与合规设计

> Extracted from DESIGN.md | [Back to index](../../DESIGN.md)

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


