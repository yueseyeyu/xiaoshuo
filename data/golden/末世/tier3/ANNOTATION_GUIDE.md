# Tier3 人工标注指南

## 目标
对7本S级书的共约105章进行人工评分，作为校准锚点修正AI评分的系统性偏差。

## 评分维度

| 维度 | 取值 | 说明 |
|------|------|------|
| human_intensity | 1-10整数 | 爽感强度：1=极度无聊, 10=极致爽感 |
| human_retention | 1-10整数 | 追读意愿：1=立刻弃书, 10=迫不及待看下一章 |
| human_hook | weak/medium/strong | 章末悬念：weak=无悬念, medium=有些好奇, strong=必须看下一章 |
| human_conflict | low/medium/high | 冲突程度：low=平淡, medium=有矛盾, high=激烈对抗 |
| human_emotion | 见下表 | 主要情绪基调（选1个） |
| human_analysis | 20-50字中文 | 评分理由（简述为什么给这个分） |

### 情绪分类
日常 / 紧张 / 爽快 / 悬疑 / 压抑 / 感动 / 悲壮 / 温馨 / 感慨 / 振奋 / 热血

## 标注流程

1. 打开 `annotation_template.csv`（Excel或文本编辑器）
2. 找到对应书的章节行
3. 阅读章节原文（在 `{book}_chapters/ch{num}.txt`）
4. 填写 `human_*` 列
5. 可选：在 `notes` 列记录观察到的AI偏差模式

## 对照说明

每行已预填AI(Tier1)和T2(Tier2)的评分供参考：
- `ai_*` 列 = DeepSeek API评分（高质量但可能有低估偏差）
- `t2_*` 列 = 本地Qwen评分（可能有高估偏差）
- `disagreement` = AI与T2的分歧程度（越大越值得关注）

## 采样来源说明

| source | 含义 | 关注点 |
|--------|------|--------|
| anchor | 校准锚点（固定位置） | 提供跨书可比的基准线 |
| disagreement | 分歧驱动（AI与T2差异大） | 判断哪个模型更准确 |
| supplement | 补充采样（两模型一致的极端值） | 确认极端值是否合理 |

## 完成后

标注完成后，运行校准脚本：
```bash
D:\\miniconda3\\envs\\llm-shared\\python.exe scripts\\calibrate_with_tier3.py
```
这将：
1. 计算AI/T2与人工分的MAE和Bias
2. 生成OLS回归校准参数
3. 重跑Borda/TOPSIS排名
4. 重新计算LOOCV相关性
