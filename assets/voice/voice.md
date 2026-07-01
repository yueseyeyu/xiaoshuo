# 文风指南

> 从拆书数据 + 作者心智模型 + 风格 DNA 提取 · 持续更新

---

## 一、风格 DNA 五维指纹

项目 `style_dna.py` 从文本提取五维量化指纹：

| 维度 | 指标 | 用途 |
|------|------|------|
| D1 句法 | 平均句长、对话占比、描写密度、句长方差 | 检测句法重复和风格漂移 |
| D2 词汇 | 高频词、成语密度、网络用语比例、AI 指纹词密度 | 检测 AI 味和词汇丰富度 |
| D3 节奏 | 段落长度分布、场景切换频率、短句占比 | 检测节奏一致性 |
| D4 幽默 | 反讽/自嘲/黑色幽默标记密度 | 检测幽默风格一致性 |
| D5 视角 | 第一/第三人称、内心独白密度、全知标记 | 检测视角一致性 |

### 使用方式

```python
from xiaoshuo.pipeline.style_dna import extract_dna, build_dna_baseline, compare_dna

# 从精品书建立基线
baseline = build_dna_baseline([ch1, ch2, ..., ch10])

# 检测当前章节偏离
deviation = compare_dna(baseline, extract_dna(current_chapter))
print(deviation.consistency_score)  # 0-100
```

---

## 二、作者心智模型

项目 `author_mind_model.py` 提供作者级创作框架：

### 预设作者

| 作者 | 核心风格 | 爽点逻辑 | 节奏方法论 |
|------|---------|---------|-----------|
| 辰东 | 燃（热血爆发） | 即时反馈，爽点前置 | 高密度快节奏 |
| 猫腻 | 谋（智商碾压） | 延迟满足，爽点后置 | 缓急交替 |
| 烽火戏诸侯 | 韵（格局装逼） | 格局碾压，变形爽感 | 长短交替 |
| 天蚕土豆 | 爽（逆袭打脸） | 退婚流/废柴流，逆袭逆转 | 标准升级节奏 |
| 爱潜水的乌贼 | 诡（规则解谜） | 悬念爽感，信息差 | 谨慎布局 |

### 使用方式

```python
from xiaoshuo.agents.author_mind_model import AuthorMindModel, DecisionIntuitionEngine

# 加载作者心智模型
model = AuthorMindModel("猫腻")
model.load()
print(model.to_prompt_context())  # 转为生成 prompt 上下文

# 决策直觉引擎
engine = DecisionIntuitionEngine()
options = engine.generate_decision_options(
    scenario="主角面对强敌，实力差距悬殊",
    authors=["辰东", "猫腻", "烽火戏诸侯"],
)
```

---

## 三、风格进化追踪

项目 `style_evolution.py` 从作者历史决策中提取长期偏好：

- 记录每次创作决策（选择哪个作者方向、修改了什么）
- 统计偏好分布（燃/谋/韵/爽/诡）
- 形成"个人决策直觉库"
- 后续骨架生成时自动参考个人偏好

---

## 四、文风自检要点

1. **句长方差** > 3.0（避免句法机械重复）
2. **AI 指纹词密度** < 2%（参见 anti_slop_blacklist.md）
3. **对话占比** 在 15%-40% 之间（过低=独白多，过高=缺乏描写）
4. **节奏一致性** > 70（与基线 DNA 对比）
5. **视角一致性** = 100（不中途切换人称）
