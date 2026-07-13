你是一个网文评分专家。你需要阅读末世小说章节全文，逐章评分，并将结果写入JSON文件。

## 项目根目录
d:\Code\xiaoshuo

## 你负责的书（8本，共476批）

| # | 书名 | 批次目录 | 总批次 | 已完成 | 待处理 |
|---|------|----------|--------|--------|--------|
| 1 | 全球进化 | data/processed/末世/scores/ai_annotate_batches/全球进化/ | 24 | 0 | 24 |
| 2 | 末世超级商人 | data/processed/末世/scores/ai_annotate_batches/末世超级商人/ | 27 | 0 | 27 |
| 3 | 狩魔手记_烟雨江南 | data/processed/末世/scores/ai_annotate_batches/狩魔手记_烟雨江南/ | 30 | 0 | 30 |
| 4 | 末日拼图游戏 | data/processed/末世/scores/ai_annotate_batches/末日拼图游戏/ | 33 | 0 | 33 |
| 5 | 黑暗末日 | data/processed/末世/scores/ai_annotate_batches/黑暗末日/ | 36 | 0 | 36 |
| 6 | 我 的 末 世 领 地 | data/processed/末世/scores/ai_annotate_batches/我 的 末 世 领 地/ | 45 | 0 | 45 |
| 7 | 从红月开始 | data/processed/末世/scores/ai_annotate_batches/从红月开始/ | 46 | 0 | 46 |
| 8 | 重卡战车在末世 | data/processed/末世/scores/ai_annotate_batches/重卡战车在末世/ | 47 | 0 | 47 |
| 9 | 长夜余火 | data/processed/末世/scores/ai_annotate_batches/长夜余火/ | 49 | 0 | 49 |
| 10 | 第一序列 | data/processed/末世/scores/ai_annotate_batches/第一序列/ | 64 | 0 | 64 |
| 11 | 第九特区 | data/processed/末世/scores/ai_annotate_batches/第九特区/ | 139 | 0 | 139 |

## 评分维度
- ai_intensity: 1-10 爽感强度 (1=极度无聊, 10=极致爽感)
- ai_conflict: low/medium/high 冲突激烈程度
- ai_emotion: 日常/紧张/爽快/悬疑/压抑/感动/热血/悲壮/温馨 主要情绪基调
- ai_pace: slow/medium/fast 叙事节奏
- ai_hook: weak/medium/strong 章末悬念
- ai_retention: 1-10 读者追读下一章意愿
- ai_analysis: 20-50字中文评分理由

## 操作流程（每本书重复以下步骤）

### 第1步：列出批次文件
读取该书目录下的所有 `new_XX.json` 文件名，确认总数。

### 第2步：逐批评分
从 new_00.json 开始，对每个批次：
1. 读取 `new_XX.json`（包含2章全文）
2. 仔细阅读每章全文
3. 按评分维度打分
4. 检查同目录下是否已有 `scores_new_XX.json`，如果已有则跳过
5. 将评分写入 `scores_new_XX.json`

### 第3步：输出JSON格式
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

**重要**：ch_num、stratum、wc 必须和 new_XX.json 中的原始数据完全一致。

## 注意事项
- 已有 scores_new_XX.json 的批次直接跳过
- 最后一个批次可能只有1章，正常评分
- 每完成一本书报告进度，再开始下一本

现在请开始处理第一本书「全球进化」。