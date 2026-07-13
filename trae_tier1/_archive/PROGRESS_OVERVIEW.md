# 末世小说 v8.8 评估流水线 — 三阶段进度总览

> 更新时间: 2026-07-12 21:00 | 共33本书 | 详细交接见 `NEW_SESSION_HANDOFF.md`

## 三阶段说明

| 阶段 | 名称 | 产出 | 状态 |
|------|------|------|------|
| Phase 1 | 规则评分 (rhythm_analyzer) | `data/processed/末世/rhythm/rhythm_*.csv` | ✅ 33/33 完成 |
| Phase 2 | LLM三层评分 (Tier1→Tier2→Tier3) | `scores_new_*.json` → `_ai_full.csv` | 🔄 Tier1: 477/2148 (22.2%) |
| Phase 3 | 商业评分 + Borda排名 | `commercial_scores.json` + `borda_ranking.json` | ⬜ 待Phase2三层全完成后 |

### Phase 2 三层分工（三层协作，非单层覆盖）
| 层 | 方法 | 采样量 | 状态 |
|----|------|--------|------|
| Tier 1 | AI全读10%分层 (CatPaw + DeepSeek/GLM/Doubao四路并行) | ~2148批/33本 | 🔄 22.2% |
| Tier 2 | 本地Qwen按quality_tiers分级采样 + 节奏峰谷对齐 | S=50/A=30/B=30/C=20 | ⬜ 待Tier1完成 |
| Tier 3 | 人工分歧驱动 + 校准锚点 | 10-20章/书 | ⬜ 待Tier2完成 |

## 四路并行分配

| 路线 | 模型 | 负责书数 | 指令文件 |
|------|------|---------|---------|
| CatPaw | CatPaw自身 | 2本(已完成) | 直接执行 |
| 路线1 | DeepSeek (Trae) | 11本 | `trae_tier1/PROMPT_1_DeepSeek.md` |
| 路线2 | GLM (Trae, 含Kimi转交) | 15本 | `trae_tier1/PROMPT_3_GLM.md` + `PROMPT_2_Kimi.md` |
| 路线3 | Doubao (Trae) | 8本 | `trae_tier1/PROMPT_4_Doubao.md` |

**注意**: Kimi有问题，任务已全部转给GLM。

## 每本书的详细进度（按完成率排序）

| # | 书名 | 分级 | 总批次 | 已评分 | 完成率 | 模型 | 状态 |
|---|------|------|--------|--------|--------|------|------|
| 1 | 废土崛起 | S | 33 | 33 | 100% | CatPaw | ✅ |
| 2 | 神秘尽头 | A | 15 | 15 | 100% | CatPaw | ✅ |
| 3 | 限制级末日症候 | B- | 115 | 115 | 100% | GLM | ✅ |
| 4 | 末日蟑螂 | B | 122 | 122 | 100% | GLM | ✅ |
| 5 | 末日拼图游戏 | B | 33 | 33 | 100% | DeepSeek | ✅ |
| 6 | 全球进化 | B+ | 24 | 20 | 83.3% | DeepSeek | 🔄 |
| 7 | 狩魔手记_烟雨江南 | A | 30 | 24 | 80% | DeepSeek | 🔄 |
| 8 | 末世超级商人 | B- | 27 | 13 | 48.1% | DeepSeek | 🔄 |
| 9 | 末世魔神游戏 | B | 100 | 35 | 35% | Doubao | 🔄 |
| 10 | 黑暗末日 | B | 36 | 11 | 30.6% | DeepSeek | 🔄 |
| 11 | 末世之深渊召唤师 | A | 79 | 21 | 26.6% | GLM/Doubao | 🔄 |
| 12 | 末日乐园 | S | 123 | 26 | 21.1% | GLM(Kimi转) | 🔄 |
| 13 | 地球游戏场 | B | 41 | 9 | 22% | Doubao | 🔄 |
| 14-33 | (其余20本) | — | — | 0 | 0% | 各模型 | ⬜ |

**总计**: Tier1 评分 477/2148 (22.2%) 🔄 | 规则评分 33/33 ✅ | 商业评分 30/33 (旧版,需v8.8重跑)

## 文件位置速查

| 产出 | 路径 | 说明 |
|------|------|------|
| 规则评分CSV | `data/processed/末世/rhythm/rhythm_{文件名}.csv` | 33本全完成 |
| LLM批次文件 | `data/processed/末世/scores/ai_annotate_batches/{书名}/new_XX.json` | 输入:章节全文 |
| LLM评分结果 | `data/processed/末世/scores/ai_annotate_batches/{书名}/scores_new_XX.json` | 输出:评分JSON |
| 合并CSV | `data/processed/末世/scores/{书名}_ai_full.csv` | 合并后供Borda使用 |
| 商业评分(旧) | `data/processed/末世/quality/commercial_scores.json` | 30本,缺3本新书 |
| Borda排名 | `data/reports/末世/synthesis/末世_borda_ranking.json` | 最终产出 |
| 交接文档 | `NEW_SESSION_HANDOFF.md` | 新对话必读 |

## 废土崛起特殊说明

废土崛起的批次文件在根目录 `ai_annotate_batches/` 下（无子目录），其他32本书在各自子目录 `ai_annotate_batches/{书名}/` 下。
