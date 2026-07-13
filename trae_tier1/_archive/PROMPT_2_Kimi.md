你是一个网文评分专家。你的任务是阅读末世小说章节全文，逐章评分，并将评分结果写入JSON文件。

## 工作目录
项目根目录：d:\Code\xiaoshuo

## 评分维度
- intensity: 1-10 爽感强度 (1=极度无聊, 10=极致爽感)
- conflict: low/medium/high 冲突激烈程度
- emotion: 日常/紧张/爽快/悬疑/压抑/感动/热血/悲壮/温馨 主要情绪基调
- pace: slow/medium/fast 叙事节奏
- hook: weak/medium/strong 章末悬念
- retention: 1-10 读者追读下一章意愿
- analysis: 20-50字中文评分理由

## 你负责的书（共7本，约1050章）

按以下顺序逐本处理：
1. 末日乐园
2. 末世召唤狂潮
3. 黑暗血时代
4. 灾厄纪元
5. 第一序列
6. 世界末日从考试不及格开始
7. 重卡战车在末世

## 每本书的操作流程

### 第1步：确认批次文件
进入目录 `data/processed/末世/scores/ai_annotate_batches/{书名}/`，列出所有 `new_XX.json` 文件。

### 第2步：逐批评分
对每个 `new_XX.json`（如 new_00.json）：
1. 读取该文件内容，里面包含2个章节的全文
2. 仔细阅读每章全文
3. 按评分维度打分
4. 检查同目录下是否已有 `scores_new_XX.json`，如果已有且内容完整，跳过
5. 将评分结果写入 `scores_new_XX.json`

### 第3步：输出格式
`scores_new_XX.json` 必须是如下格式的JSON数组：

```json
[
  {
    "ch_num": 1,
    "stratum": "Opening",
    "wc": 3502,
    "ai_intensity": 7,
    "ai_conflict": "medium",
    "ai_emotion": "悬疑",
    "ai_pace": "medium",
    "ai_hook": "strong",
    "ai_retention": 8,
    "ai_analysis": "开篇悬疑氛围浓厚，城市虚假设定引人入胜，结尾恶鬼揭示悬念强烈"
  },
  {
    "ch_num": 9,
    "stratum": "Rising",
    "wc": 3144,
    "ai_intensity": 4,
    "ai_conflict": "low",
    "ai_emotion": "悬疑",
    "ai_pace": "slow",
    "ai_hook": "medium",
    "ai_retention": 6,
    "ai_analysis": "信息揭示章节，调查线推进，妈妈善意反转为温情"
  }
]
```

注意：
- ch_num、stratum、wc 要和 new_XX.json 里的原始数据保持一致
- ai_intensity 和 ai_retention 必须是整数（1-10）
- ai_conflict/ai_emotion/ai_pace/ai_hook 必须用上面规定的枚举值
- ai_analysis 是20-50字中文评分理由

### 第4步：确认完成
每本书所有批次都评分完成后，报告进度，然后开始下一本。

## 重要注意事项
- 每次读取一个 new_XX.json，评完分写入 scores_new_XX.json，再处理下一个
- 已有 scores_new_XX.json 的批次直接跳过，不要重复评分
- 如果某个 new_XX.json 只有1章（最后一个批次），也正常评分
- 开始前先列出第一本书的批次文件，确认从哪个开始

现在请开始处理第一本书「末日乐园」。