# Golden数据保护目录

> **此目录下的文件为人工标注数据，AI不可修改、覆盖或删除。**

## 目录用途

存放人工标注(Tier 3)的golden set数据，作为三层评估体系的最终校准基准。

## 文件说明

| 文件 | 来源 | 内容 | 状态 |
|------|------|------|------|
| `末世/human_golden.csv` | 从 `data/processed/末世/scores/human_golden.csv` 迁移 | 3本书35章人工标注（废土崛起11章+末日蟑螂12章+末世大回炉10章+3章retest） | ✅ 已迁移 |

## 保护规则

1. **AI不可修改**: 任何AI agent、pipeline脚本、自动化工具都不得写入或覆盖此目录下的文件
2. **只读引用**: 脚本可以读取此目录数据用于校准，但写入路径必须指向其他位置
3. **人工维护**: 新增人工标注数据时，由人工手动追加到此目录的CSV中
4. **备份优先**: 迁移操作完成后，原文件可删除，此目录为唯一权威来源

## 数据统计

| 书名 | 标注章数 | 含retest | 标注时间 |
|------|:--------:|:--------:|---------|
| 废土崛起 | 11章 | 1章 | 2026-07-11 |
| 末日蟑螂 | 12章 | 2章 | 2026-07-11 |
| 末世大回炉 | 10章 | 0章 | 2026-07-11 |
| **合计** | **35章** | **3章** | — |

## CSV列说明

```
book: 书名
ch_num: 章节编号
wc: 字数
rule_intensity: 规则评分(pleasure_intensity)
llm_intensity: 本地Qwen评分(Tier2)
llm_retention: 本地Qwen留存评分(Tier2)
glm_intensity: GLM评分(外部API)
glm_retention: GLM留存评分
human_intensity: 人工强度评分(1-10)
human_retention: 人工留存评分(1-10)
pacing: 节奏评分
immersion: 沉浸感评分
emotion: 情感评分
tags: 爽点标签
pros: 优点
cons: 缺点
gap_reasons: 分歧原因标签
confidence: 标注置信度
time_spent: 阅读耗时(秒)
is_retest: 是否复测
timestamp: 标注时间戳
```
