# 新对话交接指令 — Tier 1 AI 评分监控

> 生成时间: 2026-07-12 | 项目: d:\Code\xiaoshuo | 分支: develop

## 一、你需要做什么

你是"番茄小说AI辅助创作系统"的项目总负责人。当前正在执行 **Tier 1 AI 全读10%分层评分**（Phase 2 的第一层）。

**你的任务**：
1. 阅读本文件，理解当前状态
2. 运行进度统计命令，查看最新进度
3. 随机抽查各模型生成的 JSON 评分质量
4. 如有模型产出质量问题，告知用户
5. 如 CatPaw 有空闲，继续评分未完成的书籍

---

## 二、三阶段流水线（正确顺序，不可搞错）

```
Phase 1: 规则评分 (rhythm_analyzer)                    ✅ 33/33 完成
    ↓ 产出: data/processed/末世/rhythm/rhythm_*.csv

Phase 2: LLM三层评分 (需要 rhythm CSV 做节奏感知采样)
    ├── Tier 1: AI全读10%分层 (CatPaw + 外部模型并行)   🔄 进行中 ~22%
    ├── Tier 2: 本地Qwen按质量分级采样                   ⬜ 待Tier1完成后
    │           (S=50章/A=30/B=30/C=20 + 节奏峰谷对齐)
    │           代码: scripts/three_tier_eval.py
    │                 src/xiaoshuo/pipeline/llm_batch_score.py
    └── Tier 3: 人工分歧驱动 + 校准锚点 (10-20章/书)      ⬜ 待Tier2后
    ↓ 三层协作: Tier1广度 → Tier2深度采样 → Tier3校准

Phase 3: 商业评分 + Borda排名                           ⬜ 所有LLM评分完成后
    ├── commercial_engine → commercial_scores.json
    └── borda_ranker → 末世_borda_ranking.json
```

**关键**: Tier1 → Tier2 → Tier3 是Phase 2内部的三个子层，不是与Phase 3并列的。
商业评分+Borda是Phase 3，必须在所有LLM三层评分完成后才执行。

---

## 三、当前 Tier 1 执行方式 — 四路并行

| 路线 | 模型 | 负责书籍 | 指令文件 |
|------|------|---------|---------|
| CatPaw | CatPaw自身 | 废土崛起(✅)、神秘尽头(✅) | 直接执行 |
| 路线1 | DeepSeek (Trae) | 11本 | trae_tier1/PROMPT_1_DeepSeek.md |
| 路线2 | GLM (Trae, 含Kimi转交) | 15本 | trae_tier1/PROMPT_3_GLM.md + PROMPT_2_Kimi.md |
| 路线3 | Doubao (Trae) | 8本 | trae_tier1/PROMPT_4_Doubao.md |

**注意**: Kimi有问题，用户已将Kimi的任务全部转给GLM。GLM现在负责原Kimi的8本 + 原GLM的8本 = 15本（其中末日乐园正在跑）。

### DeepSeek 负责 (11本):
全球进化, 末世超级商人, 狩魔手记_烟雨江南, 末日拼图游戏, 黑暗末日,
我 的 末 世 领 地, 从红月开始, 重卡战车在末世, 长夜余火, 第一序列, 第九特区

### GLM 负责 (15本, 含Kimi转交):
限制级末日症候, 末日蟑螂, 末世之深渊召唤师, 我的女友是丧尸, 全球变异从灾厄降临开始,
神秘尽头(已完成), 蹉跎, 恐慌沸腾, (以上原GLM 8本)
末日乐园, 黑暗血时代, 末世召唤狂潮, 我在末世有套房, 我在末世种个田,
黑暗王者, 灾厄纪元, 黑暗文明_古羲 (以上原Kimi 8本转交GLM)

### Doubao 负责 (8本):
末世魔神游戏, 末世大回炉, 异兽迷城, 地球游戏场,
世界末日从考试不及格开始, 我在末世种个田, 恐慌沸腾, 末世之深渊召唤师

**注意**: 我在末世种个田、恐慌沸腾、末世之深渊召唤师 被 GLM 和 Doubao 同时分配了（交叉覆盖），任一方完成即可。

---

## 四、进度快照 (2026-07-12 最后一次统计)

**总进度: 477 / 2148 批次 = 22.2%**

### 100% 完成的书籍 (5本)
| 书名 | 批次 | 完成方 |
|------|------|--------|
| 废土崛起 | 33 | CatPaw |
| 神秘尽头 | 15 | CatPaw |
| 限制级末日症候 | 115 | GLM |
| 末日蟑螂 | 122 | GLM |
| 末日拼图游戏 | 33 | DeepSeek |

### 进行中 (8本有产出)
| 书名 | 进度 | 完成率 | 模型 |
|------|------|--------|------|
| 全球进化 | 20/24 | 83.3% | DeepSeek |
| 狩魔手记_烟雨江南 | 24/30 | 80% | DeepSeek |
| 末世超级商人 | 13/27 | 48.1% | DeepSeek |
| 末世魔神游戏 | 35/100 | 35% | Doubao |
| 黑暗末日 | 11/36 | 30.6% | DeepSeek |
| 末世之深渊召唤师 | 21/79 | 26.6% | GLM/Doubao |
| 末日乐园 | 26/123 | 21.1% | GLM(Kimi转) |
| 地球游戏场 | 9/41 | 22% | Doubao |

### 尚未开始 (20本, 0%)
从红月开始, 重卡战车在末世, 长夜余火, 第一序列, 第九特区, 蹉跎,
黑暗血时代, 黑暗王者, 黑暗文明_古羲, 世界末日从考试不及格开始,
我在末世种个田, 我在末世有套房, 我的女友是丧尸, 末世召唤狂潮,
末世大回炉, 异兽迷城, 全球变异从灾厄降临开始, 灾厄纪元,
我 的 末 世 领 地, 恐慌沸腾

---

## 五、评分格式规范

每个 `scores_new_XX.json` 必须是合法 JSON 数组，每章一个对象：

```json
[
  {
    "ch_num": 1,
    "stratum": "Opening",
    "wc": 3502,
    "ai_intensity": 7,          // 1-10 爽感强度
    "ai_conflict": "medium",     // low/medium/high
    "ai_emotion": "悬疑",        // 日常/紧张/爽快/悬疑/压抑/感动/热血/悲壮/温馨
    "ai_pace": "medium",         // slow/medium/fast
    "ai_hook": "strong",         // weak/medium/strong
    "ai_retention": 8,           // 1-10 追读意愿
    "ai_analysis": "20-50字中文评分理由"
  }
]
```

**质量检查要点**:
1. JSON 格式合法
2. `ch_num`, `stratum`, `wc` 必须与输入文件 `new_XX.json` 中的原始数据一致
3. 评分逻辑合理（战斗章 intensity 高、日常章低）
4. `ai_analysis` 在 20-50 字之间，能概括章节核心

---

## 六、进度统计命令 (PowerShell)

```powershell
cd d:\Code\xiaoshuo
$totalBatches = 0; $totalScores = 0; $results = @()
Get-ChildItem -Path "data\processed\末世\scores\ai_annotate_batches" -Directory | ForEach-Object {
    $book = $_.Name
    $scores = Get-ChildItem $_.FullName -Filter "scores_new_*.json" -ErrorAction SilentlyContinue
    $batches = Get-ChildItem $_.FullName -Filter "new_*.json" | Where-Object { $_.Name -notmatch "^scores_" }
    $sCount = if($scores){$scores.Count}else{0}
    $bCount = if($batches){$batches.Count}else{0}
    $totalBatches += $bCount; $totalScores += $sCount
    $pct = if($bCount -gt 0){[math]::Round($sCount/$bCount*100,1)}else{0}
    $results += [PSCustomObject]@{Book=$book; Batches=$bCount; Scores=$sCount; Pct="$pct%"}
}
$rootScores = (Get-ChildItem -Path "data\processed\末世\scores\ai_annotate_batches" -Filter "scores_new_*.json" | Measure-Object).Count
$rootBatches = (Get-ChildItem -Path "data\processed\末世\scores\ai_annotate_batches" -Filter "new_*.json" | Where-Object { $_.Name -notmatch "^scores_" } | Measure-Object).Count
$totalBatches += $rootBatches; $totalScores += $rootScores
$results += [PSCustomObject]@{Book="废土崛起(root)"; Batches=$rootBatches; Scores=$rootScores; Pct="100%"}
$results | Sort-Object Pct -Descending | Format-Table -AutoSize
$totalPct = [math]::Round($totalScores/$totalBatches*100,1)
Write-Output "TOTAL: $totalScores / $totalBatches ($totalPct%)"
```

---

## 七、抽查质量方法

1. 从不同模型的书目中随机选 2-3 个 `scores_new_XX.json` 文件
2. 读取评分文件和对应的输入文件 `new_XX.json`
3. 检查：JSON格式、ch_num/wc/stratum一致性、评分逻辑合理性、分析质量
4. 如发现格式错误或评分明显不合理，告知用户

**抽查命令**:
```powershell
cd d:\Code\xiaoshuo
# 随机抽取
Get-ChildItem "data\processed\末世\scores\ai_annotate_batches\限制级末日症候\scores_new_*.json" | Get-Random -Count 2 | Select-Object Name
Get-ChildItem "data\processed\末世\scores\ai_annotate_batches\末日拼图游戏\scores_new_*.json" | Get-Random -Count 2 | Select-Object Name
Get-ChildItem "data\processed\末世\scores\ai_annotate_batches\末世魔神游戏\scores_new_*.json" | Get-Random -Count 2 | Select-Object Name
```

然后读取对应的 scores 和 new 文件对比。

---

## 八、上轮抽查结论 (2026-07-12)

6/6 全部 PASS。四个模型（DeepSeek/GLM/Doubao/CatPaw）的产出质量一致：
- 格式合规率 100%
- 数据一致性 100%（ch_num/stratum/wc 无错位）
- 评分逻辑合理（战斗高、日常低）
- 分析深度优秀（20-50字精准概括）
- GLM 接手 Kimi 任务后质量无衰减

---

## 九、关键路径和文件

| 用途 | 路径 |
|------|------|
| 批次输入文件 | `data/processed/末世/scores/ai_annotate_batches/{书名}/new_XX.json` |
| 评分输出文件 | `data/processed/末世/scores/ai_annotate_batches/{书名}/scores_new_XX.json` |
| 废土崛起(特殊) | `data/processed/末世/scores/ai_annotate_batches/` (根目录，无子目录) |
| 规则评分CSV | `data/processed/末世/rhythm/rhythm_{文件名}.csv` |
| 合并CSV(产出) | `data/processed/末世/scores/{书名}_ai_full.csv` |
| 商业评分(旧) | `data/processed/末世/quality/commercial_scores.json` |
| Borda排名 | `data/reports/末世/synthesis/末世_borda_ranking.json` |
| 进度总览 | `trae_tier1/PROGRESS_OVERVIEW.md` |
| 分级配置 | `config.yaml` 中的 `quality_tiers` |
| 三层评估脚本 | `scripts/three_tier_eval.py` |
| LLM批评脚本 | `src/xiaoshuo/pipeline/llm_batch_score.py` |

---

## 十、下一步行动（新对话执行）

1. **立即**: 运行第六节的统计命令，获取最新进度
2. **立即**: 运行第七节的抽查命令，验证最新产出的质量
3. **持续**: 如发现新书完成100%，记录下来
4. **CatPaw评分**: 如CatPaw有空闲，选择未开始的书籍继续评分（用 `scripts/ai_annotate.py` 提取批次后逐批评分）
5. **完成判断**: 当所有33本书的 scores 文件数 = batches 文件数时，Tier 1 完成
6. **Tier 1 完成后**: 
   - 合并每本书的 scores 为 `{书名}_ai_full.csv`
   - 启动 Tier 2 (Qwen本地模型，按quality_tiers分级采样)
   - **不要直接跳到商业评分/Borda** — 必须先完成 Tier2 和 Tier3

---

## 十一、质量分级 (config.yaml quality_tiers, v8.8)

S级(7本): 废土崛起, 黑暗血时代, 第一序列, 长夜余火, 末日乐园, 末日蟑螂(维持B过滤鼻祖效应)... 
A级(11本): 末世之深渊召唤师, 狩魔手记_烟雨江南, 神秘尽头...
B+级(4本): 全球进化, 黑暗文明_古羲, 黑暗王者, 我的女友是丧尸...
B级(6本): 地球游戏场, 末日拼图游戏, 黑暗末日, 末世魔神游戏...
B-级(3本): 末世超级商人, 限制级末日症候...
C级(4本): 蹉跎...

Tier2 采样量: S=50章, A=30章, B=30章, C=20章 + 节奏峰谷对齐(S峰50%/A中30%/B谷20%)
