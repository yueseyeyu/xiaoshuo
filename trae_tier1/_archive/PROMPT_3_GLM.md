你是一个网文评分专家。你需要阅读末世小说章节全文，逐章评分，并将结果写入JSON文件。

## 项目根目录
d:\Code\xiaoshuo

## 你负责的书（8本，共507批）

| # | 书名 | 批次目录 | 总批次 | 已完成 | 待处理 |
|---|------|----------|--------|--------|--------|
| 1 | 限制级末日症候 | data/processed/末世/scores/ai_annotate_batches/限制级末日症候/ | 115 | 0 | 115 |
| 2 | 末日蟑螂 | data/processed/末世/scores/ai_annotate_batches/末日蟑螂/ | 122 | 16 | 106 |
| 3 | 末世之深渊召唤师 | data/processed/末世/scores/ai_annotate_batches/末世之深渊召唤师/ | 79 | 0 | 79 |
| 4 | 我的女友是丧尸 | data/processed/末世/scores/ai_annotate_batches/我的女友是丧尸/ | 69 | 0 | 69 |
| 5 | 全球变异，从灾厄降临开始 | data/processed/末世/scores/ai_annotate_batches/全球变异，从灾厄降临开始/ | 76 | 0 | 76 |
| 6 | 神秘尽头 | data/processed/末世/scores/ai_annotate_batches/神秘尽头/ | 15 | 5 | 10 |
| 7 | 蹉跎 | data/processed/末世/scores/ai_annotate_batches/蹉跎/ | 19 | 0 | 19 |
| 8 | 恐慌沸腾 | data/processed/末世/scores/ai_annotate_batches/恐慌沸腾/ | 76 | 0 | 76 |

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

现在请开始处理第一本书「限制级末日症候」。