# Trae Tier2 评分任务（12段分段版）

你是一个网文评分专家。你需要阅读末世小说章节全文，逐章评分，并将结果写入JSON文件。

## 项目根目录
d:\Code\xiaoshuo

## 任务总览
- 总书数: 33本
- 总批次: 555批
- 总章节: 1110章
- 分段: 12段，每段约43批

## 评分维度
- t2_intensity: 1-10 爽感强度 (1=极度无聊, 10=极致爽感)
- t2_conflict: low/medium/high 冲突激烈程度
- t2_emotion: 日常/紧张/爽快/悬疑/压抑/感动/热血/悲壮/温馨 主要情绪基调
- t2_pace: slow/medium/fast 叙事节奏
- t2_hook: weak/medium/strong 章末悬念
- t2_retention: 1-10 读者追读下一章意愿
- t2_analysis: 20-100字中文评分理由

## 评分JSON格式
```json
[
  {
    "ch_num": 9,
    "stratum": "Opening",
    "wc": 3326,
    "t2_intensity": 7,
    "t2_conflict": "medium",
    "t2_emotion": "悬疑",
    "t2_pace": "medium",
    "t2_hook": "strong",
    "t2_retention": 8,
    "t2_analysis": "开篇悬疑氛围浓厚，城市虚假设定引人入胜，结尾恶鬼揭示悬念强烈"
  }
]
```

## ⚠️ 重要规则
1. **ch_num、stratum、wc** 必须和 `new_XX.json` 中的原始数据完全一致，不要修改
2. **scores_new_XX.json 中不要包含 text 字段**，只包含评分结果（避免文件过大）
3. **t2_intensity 和 t2_retention 是整数** (1-10)，不是字符串
4. **t2_conflict/t2_emotion/t2_pace/t2_hook 是字符串**，必须用上述指定的值
5. **t2_analysis 是中文**，20-100字，简短点评即可
6. 文件编码 UTF-8 无 BOM

## 操作流程（每本书）
1. 读取该书目录下的 `new_XX.json`，检查是否已有 `scores_new_XX.json`，跳过已完成的
2. 逐批阅读章节全文（`text` 字段是章节正文）并评分
3. 将评分写入 `scores_new_XX.json`（UTF-8编码，无BOM）
4. **不要在 scores 文件中包含 text 字段**
5. 最后一个批次可能只有1章，正常评分

## ⚠️ 每段完成后的质检步骤（必做）
每完成一段后，运行以下Python脚本质检：
```
cd d:\Code\xiaoshuo
python scripts/quality_check_tier2.py
```
质检脚本会检查：
- 每个scores_new_XX.json是否为合法JSON
- ch_num/stratum/wc是否与new_XX.json一致
- 评分值是否在合法范围内（t2_intensity 1-10, t2_retention 1-10等）
- t2_analysis是否为20-100字中文
- 是否包含text字段（不应该包含）

如果质检报错，修复后再开始下一段。

---

## 第1段（50批，2本）

### 地球游戏场（S级 / 25总批次 / 待处理25批）
目录: `data/processed/末世/scores/tier2_batches/地球游戏场`
待处理批次号: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24

### 异兽迷城（S级 / 25总批次 / 待处理25批）
目录: `data/processed/末世/scores/tier2_batches/异兽迷城`
待处理批次号: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24

**第1段完成后**：运行 `python scripts/quality_check_tier2.py` 质检，确认无错后继续下一段。

---

## 第2段（50批，2本）

### 末世大回炉（S级 / 25总批次 / 待处理25批）
目录: `data/processed/末世/scores/tier2_batches/末世大回炉`
待处理批次号: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24

### 末日乐园（S级 / 25总批次 / 待处理25批）
目录: `data/processed/末世/scores/tier2_batches/末日乐园`
待处理批次号: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24

**第2段完成后**：运行 `python scripts/quality_check_tier2.py` 质检，确认无错后继续下一段。

---

## 第3段（50批，2本）

### 第一序列（S级 / 25总批次 / 待处理25批）
目录: `data/processed/末世/scores/tier2_batches/第一序列`
待处理批次号: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24

### 长夜余火（S级 / 25总批次 / 待处理25批）
目录: `data/processed/末世/scores/tier2_batches/长夜余火`
待处理批次号: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24

**第3段完成后**：运行 `python scripts/quality_check_tier2.py` 质检，确认无错后继续下一段。

---

## 第4段（55批，3本）

### 黑暗血时代（S级 / 25总批次 / 待处理25批）
目录: `data/processed/末世/scores/tier2_batches/黑暗血时代`
待处理批次号: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24

### 世界末日从考试不及格开始（A级 / 15总批次 / 待处理15批）
目录: `data/processed/末世/scores/tier2_batches/世界末日从考试不及格开始`
待处理批次号: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14

### 从红月开始（A级 / 15总批次 / 待处理15批）
目录: `data/processed/末世/scores/tier2_batches/从红月开始`
待处理批次号: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14

**第4段完成后**：运行 `python scripts/quality_check_tier2.py` 质检，确认无错后继续下一段。

---

## 第5段（45批，3本）

### 全球变异，从灾厄降临开始（A级 / 15总批次 / 待处理15批）
目录: `data/processed/末世/scores/tier2_batches/全球变异，从灾厄降临开始`
待处理批次号: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14

### 废土崛起（A级 / 15总批次 / 待处理15批）
目录: `data/processed/末世/scores/tier2_batches/废土崛起`
待处理批次号: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14

### 我 的 末 世 领 地（A级 / 15总批次 / 待处理15批）
目录: `data/processed/末世/scores/tier2_batches/我 的 末 世 领 地`
待处理批次号: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14

**第5段完成后**：运行 `python scripts/quality_check_tier2.py` 质检，确认无错后继续下一段。

---

## 第6段（45批，3本）

### 末世之深渊召唤师（A级 / 15总批次 / 待处理15批）
目录: `data/processed/末世/scores/tier2_batches/末世之深渊召唤师`
待处理批次号: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14

### 末世召唤狂潮（A级 / 15总批次 / 待处理15批）
目录: `data/processed/末世/scores/tier2_batches/末世召唤狂潮`
待处理批次号: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14

### 末世魔神游戏（A级 / 15总批次 / 待处理15批）
目录: `data/processed/末世/scores/tier2_batches/末世魔神游戏`
待处理批次号: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14

**第6段完成后**：运行 `python scripts/quality_check_tier2.py` 质检，确认无错后继续下一段。

---

## 第7段（45批，3本）

### 末日拼图游戏（A级 / 15总批次 / 待处理15批）
目录: `data/processed/末世/scores/tier2_batches/末日拼图游戏`
待处理批次号: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14

### 狩魔手记_烟雨江南（A级 / 15总批次 / 待处理15批）
目录: `data/processed/末世/scores/tier2_batches/狩魔手记_烟雨江南`
待处理批次号: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14

### 神秘尽头（A级 / 15总批次 / 待处理15批）
目录: `data/processed/末世/scores/tier2_batches/神秘尽头`
待处理批次号: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14

**第7段完成后**：运行 `python scripts/quality_check_tier2.py` 质检，确认无错后继续下一段。

---

## 第8段（45批，3本）

### 全球进化（B级 / 15总批次 / 待处理15批）
目录: `data/processed/末世/scores/tier2_batches/全球进化`
待处理批次号: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14

### 恐慌沸腾（B级 / 15总批次 / 待处理15批）
目录: `data/processed/末世/scores/tier2_batches/恐慌沸腾`
待处理批次号: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14

### 我在末世有套房（B级 / 15总批次 / 待处理15批）
目录: `data/processed/末世/scores/tier2_batches/我在末世有套房`
待处理批次号: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14

**第8段完成后**：运行 `python scripts/quality_check_tier2.py` 质检，确认无错后继续下一段。

---

## 第9段（45批，3本）

### 我在末世种个田（B级 / 15总批次 / 待处理15批）
目录: `data/processed/末世/scores/tier2_batches/我在末世种个田`
待处理批次号: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14

### 我的女友是丧尸（B级 / 15总批次 / 待处理15批）
目录: `data/processed/末世/scores/tier2_batches/我的女友是丧尸`
待处理批次号: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14

### 末世超级商人（B级 / 15总批次 / 待处理15批）
目录: `data/processed/末世/scores/tier2_batches/末世超级商人`
待处理批次号: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14

**第9段完成后**：运行 `python scripts/quality_check_tier2.py` 质检，确认无错后继续下一段。

---

## 第10段（45批，3本）

### 末日蟑螂（B级 / 15总批次 / 待处理15批）
目录: `data/processed/末世/scores/tier2_batches/末日蟑螂`
待处理批次号: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14

### 灾厄纪元（B级 / 15总批次 / 待处理15批）
目录: `data/processed/末世/scores/tier2_batches/灾厄纪元`
待处理批次号: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14

### 第九特区（B级 / 15总批次 / 待处理15批）
目录: `data/processed/末世/scores/tier2_batches/第九特区`
待处理批次号: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14

**第10段完成后**：运行 `python scripts/quality_check_tier2.py` 质检，确认无错后继续下一段。

---

## 第11段（45批，3本）

### 重卡战车在末世（B级 / 15总批次 / 待处理15批）
目录: `data/processed/末世/scores/tier2_batches/重卡战车在末世`
待处理批次号: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14

### 限制级末日症候（B级 / 15总批次 / 待处理15批）
目录: `data/processed/末世/scores/tier2_batches/限制级末日症候`
待处理批次号: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14

### 黑暗文明_古羲（B级 / 15总批次 / 待处理15批）
目录: `data/processed/末世/scores/tier2_batches/黑暗文明_古羲`
待处理批次号: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14

**第11段完成后**：运行 `python scripts/quality_check_tier2.py` 质检，确认无错后继续下一段。

---

## 第12段（35批，3本）

### 黑暗王者（B级 / 15总批次 / 待处理15批）
目录: `data/processed/末世/scores/tier2_batches/黑暗王者`
待处理批次号: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14

### 蹉跎（C级 / 10总批次 / 待处理10批）
目录: `data/processed/末世/scores/tier2_batches/蹉跎`
待处理批次号: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9

### 黑暗末日（C级 / 10总批次 / 待处理10批）
目录: `data/processed/末世/scores/tier2_batches/黑暗末日`
待处理批次号: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9

**第12段完成后**：运行 `python scripts/quality_check_tier2.py` 质检，确认无错后继续下一段。

---

现在请开始第1段。

## ⚠️ 重要提醒
- 评分字段用 `t2_` 前缀（不是 `ai_`），区分Tier1和Tier2
- 目录是 `tier2_batches/`（不是 `ai_annotate_batches/`）
- 质检脚本是 `quality_check_tier2.py`（不是 `quality_check.py`）
- scores文件中 **不要包含 text 字段**，只写评分结果
- t2_intensity 和 t2_retention 是 **整数**，不是字符串