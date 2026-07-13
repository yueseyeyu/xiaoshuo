# 独立审计指令 — 末世小说分析评分体系全面审计

> 生成时间: 2026-07-13
> 项目路径: d:\Code\xiaoshuo
> 审计版本: v8.10 (Tier3校准后)
> 审计要求: 客观、独立、不预设结论

---

## 审计目标

对当前末世小说分析评分体系的**数据合理性**、**评分关系正确性**、**最终排名可靠性**做一次全面独立审计。审计者应以怀疑态度审查每一个环节，不预设"数据是对的"。

---

## 一、数据流审计 (5个环节)

### 1.1 原始数据审计

**检查项:**
- `data/raw/novel_index.json` 中末世分类有多少本书？是否与33本一致？
- 每本书的 `file` 字段指向的txt文件是否都存在？文件大小是否合理(>100KB)？
- 是否有重复条目或文件名不一致？
- `word_count` 字段与实际txt文件字数是否大致吻合？

**关键文件:**
- `data/raw/novel_index.json`
- `data/raw/novels/末世/` 目录下33个txt文件

**审计方法:**
```
1. 读取 novel_index.json，列出所有书的 file/author/word_count/rhythm_csv 字段
2. 逐一检查 txt 文件是否存在，记录文件大小
3. 抽样3本书，用 wc -m 统计字数，对比 index 中的 word_count
4. 检查是否有同一本书出现多次（不同文件名但内容相同）
```

### 1.2 Rhythm规则评分审计

**检查项:**
- 33本rhythm CSV是否都存在？文件名与novel_index.json的`rhythm_csv`字段是否一致？
- 每个CSV的章节数与原始txt章节数是否匹配？
- 关键指标(hook_density, conflict_density, pleasure_density)的分布是否合理？
- 是否存在全0或全相同的异常列？
- wc(字数)列是否有异常值(<100或>10000)？

**关键文件:**
- `data/processed/末世/rhythm/` 目录下33个CSV
- `src/xiaoshuo/pipeline/rhythm/rule_analyzer.py` (规则定义)
- `src/xiaoshuo/pipeline/rhythm/patterns.py` (模式定义)

**审计方法:**
```
1. glob扫描rhythm目录，与novel_index.json交叉验证
2. 逐CSV检查: 行数、列名、缺失值、min/max/mean/std
3. 抽样5本书，对比rhythm CSV章节数 vs txt文件中"第X章"出现的次数
4. 检查hook_density分布: 是否有>50%或<5%的异常值
5. 检查是否有wc=0或wc为空的行
```

### 1.3 Tier1 (AI全读) 评分审计

**检查项:**
- 33本`*_ai_full.csv`是否都存在？
- 每本书的T1采样章节数是否约为总章节的10%？
- ai_intensity/ai_retention的分布是否合理(1-10范围)？是否有越界值？
- ai_analysis字段是否非空？平均长度是否合理？
- 是否存在同一章节被重复评分？
- 采样是否真的是"10%均匀分层"？验证: 总章节/10 ≈ T1章节数

**关键文件:**
- `data/processed/末世/scores/*_ai_full.csv` (33个)
- `data/processed/末世/scores/ai_annotate_batches/` (批次目录)
- `scripts/ai_annotate.py` (采样逻辑)

**审计方法:**
```
1. 逐CSV统计: 行数、intensity/retention的min/max/mean
2. 对比每本书: rhythm CSV行数 × 10% ≈ ai_full CSV行数?
3. 检查intensity是否在[1,10]范围内，retention同理
4. 检查ai_analysis列: 空值率、平均字符长度
5. 检查ch_num是否有重复
6. 抽样3本书，验证采样间隔是否均匀(非连续章节)
```

### 1.4 Tier2 (本地模型) 评分审计

**检查项:**
- 33本`*_t2_full.csv`是否都存在？
- 每本书的T2采样章节数是否符合分级规则(S=50/A=30/B=30/C=20)？
- t2_intensity/t2_retention的分布是否合理？
- T1和T2的采样章节是否真的零重叠？
- t2_analysis字段质量如何？

**关键文件:**
- `data/processed/末世/scores/*_t2_full.csv` (33个)
- `data/processed/末世/scores/tier2_batches/` (批次目录)
- `scripts/gen_tier2_sampling.py` (采样逻辑)

**关键配置:**
- v8.8分级: S=7本 / A=11本 / B+=4本 / B=6本 / B-=3本 / C=4本 = 35本
- 采样量: S=50章, A=30章, B=30章, C=20章
- 节奏对齐: S峰50% / A中30% / B谷20%

**审计方法:**
```
1. 逐CSV统计行数，对比分级预期:
   - S级书应有~50章, A级~30章, B级~30章, C级~20章
2. 检查t2_intensity/t2_retention范围[1,10]
3. 对每本书，取T1的ch_num集合和T2的ch_num集合，计算交集(应为空)
4. 检查t2_analysis空值率
5. 验证节奏对齐: S级书的T2采样是否偏向高hook_density章节
```

### 1.5 LLM合并CSV审计

**检查项:**
- 33本`*_llm.csv`是否都存在？
- 每本llm.csv的行数 = ai_full行数 + t2_full行数？
- 合并后是否有字段错位(ai_字段混入t2_字段)？
- 合并后intensity/retention列是否统一命名？

**关键文件:**
- `data/processed/末世/scores/*_llm.csv` (33个)
- `scripts/merge_tier2_and_update.py` (合并逻辑)

**审计方法:**
```
1. 对每本书: llm.csv行数 == ai_full.csv行数 + t2_full.csv行数?
2. 检查llm.csv列名: 是否有 ai_intensity, ai_retention, t2_intensity, t2_retention
3. 检查每行: 要么ai_intensity有值t2_intensity为空，要么反之
4. 统计总章节数(应为~5472)
```

---

## 二、评分关系审计 (4个关系链)

### 2.1 Rhythm → LLM强度 传导审计

**核心问题:** rhythm CSV中的规则指标(hook_density等)与LLM评分(intensity/retention)之间的相关性是否合理？

**审计方法:**
```
1. 对每本书，合并rhythm CSV和llm CSV (按ch_num)
2. 计算hook_density vs ai_intensity的Pearson r
3. 预期: 正相关(r>0.2)，因为hook多→爽感强
4. 如果r<0或r≈0，需调查原因
5. 同理检查conflict_density vs intensity
6. 输出33本书的r值分布
```

### 2.2 T1 vs T2 一致性审计

**核心问题:** 虽然T1和T2采样不同章节，但在同一本书的分布层面，两者的均值/标准差是否一致？

**审计方法:**
```
1. 对每本书，计算T1的ai_intensity均值和T2的t2_intensity均值
2. 校准数据显示T1 Bias=+1.78, T2 Bias=-2.59
3. 检查: T1均值 - T2均值 ≈ 4.37 (1.78+2.59)?
4. 如果差异远大于4.37，说明采样偏差严重
5. 对33本书绘制T1均值 vs T2均值散点图
```

### 2.3 Tier3校准有效性审计

**核心问题:** 125章校准数据集(30章人工+95章GLM)的质量是否可靠？LOOCV r=0.546是否可信？

**关键文件:**
- `data/golden/末世/human_golden.csv` (30章人工标注)
- `data/golden/末世/tier3/tier3_glm_scores.json` (95章GLM标注)
- `data/reports/末世/calibration/tier3_calibration.json` (校准结果)

**审计方法:**
```
1. 检查human_golden.csv:
   - 30章来自几本书？(预期3本: 废土崛起/地球游戏场/异兽迷城)
   - human_intensity/human_retention分布是否合理？
   - 是否有同一章节重复标注？

2. 检查tier3_glm_scores.json:
   - 95章来自7本S级书，每书10-15章
   - GLM评分的intensity/retention分布是否合理？
   - 是否有明显的评分聚集(如全部给6分)？
   - GLM评分与T1评分的相关性如何？

3. 检查校准结果:
   - OLS slope=0.463 (intensity), 0.373 (retention)
     含义: T1每增加1分，human只增加0.46分 → T1有通胀
   - 这个slope是否合理？对比其他领域的AI校准slope
   - LOOCV r=0.546 (n=125): 查t分布表，p值是否<0.001?
   - 注意: 95章GLM评分由AI自评，不是纯人工。这是否有循环论证风险？
   
4. 关键质疑: GLM评分(作为校准锚点)本身是否可靠？
   - GLM评分者=AI(CatPaw)，被校准对象=T1(AI评分)
   - 这相当于用AI校准AI，是否有系统性偏差？
   - human_golden的30章是真正人工标注，但只占24%(30/125)
```

### 2.4 LLM评分 → 商业评分 → Borda排名 传导审计

**核心问题:** LLM的intensity/retention分数如何影响最终Borda排名？传导链是否透明？

**关键文件:**
- `src/xiaoshuo/pipeline/scoring/commercial_engine.py` (商业评分引擎)
- `src/xiaoshuo/pipeline/scoring/borda_ranker.py` (Borda排名器)
- `data/reports/末世/synthesis/末世_borda_ranking.json` (排名结果)
- `data/reports/末世/synthesis/末世_topsis_ranking.json` (TOPSIS排名)

**审计方法:**
```
1. 阅读 commercial_engine.py 中的 compute_commercial_score() 函数
   - 输入: rhythm CSV + llm CSV
   - 输出: signing_score, retention_score, diversity_score等
   - LLM的intensity/retention如何影响commercial score?

2. 阅读 borda_ranker.py 中的 process_genre()
   - 5个Borda维度: signing, retention, diversity, bt_rank, webnovel8
   - 每个维度的排序方向(高=好还是低=好)?
   - 维度权重是否合理? 当前配置在config.yaml中

3. 检查Borda排名结果:
   - 33本书的排名是否自洽？
   - S级书是否普遍排在前面？
   - 是否有明显异常(如S级书排到20名以后)?

4. 对比Borda vs TOPSIS排名:
   - 两者的TOP10差异有多大？
   - 哪个更可信？为什么？
```

---

## 三、最终排名审计 (3个层面)

### 3.1 排名稳定性审计

**核心问题:** 如果改变关键参数，排名是否会剧烈变化？

**审计方法:**
```
1. 维度权重敏感性: 将5个Borda维度权重从等权改为config中的权重，排名变化多大？
2. 样本量敏感性: 去掉T2数据(仅用T1)，排名变化多大？
3. 校准敏感性: 应用OLS校准(slope=0.463)后重算commercial score，排名变化多大？
4. 输出: 原排名 vs 各场景排名的Spearman相关系数
```

### 3.2 分级合理性审计

**核心问题:** v8.8分级(S=7/A=11/B+=4/B=6/B-=3/C=4=35本)是否与数据吻合？

**关键文件:**
- `data/reports/rankings/末世/v8.8_final_ranking.csv` (分级表)

**审计方法:**
```
1. 检查7本S级书的Borda排名:
   - 全球变异: borda#1 ✅
   - 末世大回炉: borda#3 ✅
   - 末世之深渊召唤师: borda#2 — 但v8.8已降为A级! 矛盾?
   - 地球游戏场: borda#4 ✅
   - 第一序列: borda#8 — S级但排第8?
   - 长夜余火: borda#15 — S级但排第15?!
   - 末日乐园: borda#23 — S级但排第23?!

2. 重点质疑: 
   - 长夜余火(borda#15)和末日乐园(borda#23)为何是S级？
   - Borda排名与人工分级严重不一致，哪个更可信？
   - 人工分级的依据是什么？是否有客观标准？

3. 检查C级书:
   - 蹉跎: 商业评分46(D级) → C级，是否合理？
   - 黑暗末日: 商业评分43(D级) → C级，是否合理？
```

### 3.3 外部验证审计

**核心问题:** 排名结果是否与外部口碑(豆瓣/起点/番茄)一致？

**审计方法:**
```
1. 抽取TOP5和BOTTOM5书籍
2. 对比外部数据:
   - 豆瓣评分(如有)
   - 起点收藏/推荐票(如有)
   - 番茄在读人数(如有)
3. 检查是否有"排名高但外部口碑差"或反之的异常
4. 特别关注:
   - 全球变异(borda#1): 外部口碑如何？是否有循环论证(signing维度)?
   - 末日乐园(borda#23但S级): 800万字2428章，外部口碑如何？
```

---

## 四、已知风险点 (重点审查)

### 4.1 循环论证风险
- `signing` 维度可能循环论证: 商业评分高→排名高→"证明"商业价值高
- 检查: signing_score的计算逻辑是否独立于LLM评分？

### 4.2 GLM自评风险
- 95章Tier3校准数据由AI(CatPaw)评分，被用于校准另一个AI(T1)的评分
- 这相当于"AI给AI打分然后说AI准了"
- 检查: 30章纯人工标注的校准结果 vs 125章混合的校准结果，差异多大？

### 4.3 采样代表性风险
- T1=10%均匀采样, T2=质量分级采样
- 检查: T1+T2合并后，是否某些章节类型(如战斗/日常)被过度/不足采样？

### 4.4 技术缺陷风险
- `np.corrcoef`在当前环境触发Windows DLL错误(0xc06d007f)
- 已用手动Pearson公式替代，但需验证手动公式正确性
- 检查: 对比手动Pearson vs scipy.stats.pearsonr的结果

### 4.5 Borda维度权重风险
- 当前5维权重在config.yaml中配置
- 检查: 权重是否经过验证？还是拍脑袋定的？
- 如果改为等权(各1.0)，排名变化多大？

---

## 五、审计执行步骤

### Step 1: 数据完整性检查 (预计30分钟)
```
1.1 原始数据: 检查33本txt + novel_index.json
1.2 Rhythm: 检查33个rhythm CSV
1.3 T1: 检查33个ai_full.csv
1.4 T2: 检查33个t2_full.csv
1.5 LLM合并: 检查33个llm.csv
```

### Step 2: 评分关系检查 (预计45分钟)
```
2.1 Rhythm vs LLM相关性
2.2 T1 vs T2分布一致性
2.3 Tier3校准有效性(重点!)
2.4 LLM→Commercial→Borda传导链
```

### Step 3: 排名审计 (预计30分钟)
```
3.1 排名稳定性(参数敏感性)
3.2 分级合理性(Borda vs 人工分级矛盾)
3.3 外部验证(如有条件)
```

### Step 4: 风险评估 (预计15分钟)
```
4.1 循环论证
4.2 GLM自评
4.3 采样代表性
4.4 技术缺陷
4.5 权重合理性
```

### Step 5: 输出审计报告
```
格式: data/reports/末世/audit_v8.10.md
内容:
- 数据完整性: PASS/WARN/FAIL (逐项)
- 评分关系: PASS/WARN/FAIL (逐项)
- 排名可靠性: PASS/WARN/FAIL (逐项)
- 风险清单: 高/中/低 (逐项)
- 改进建议: 可操作的具体建议
```

---

## 六、关键文件索引

| 类别 | 文件路径 | 说明 |
|------|----------|------|
| 索引 | `data/raw/novel_index.json` | 小说SSOT索引 |
| 原始 | `data/raw/novels/末世/*.txt` | 33本原始文本 |
| Rhythm | `data/processed/末世/rhythm/*.csv` | 33个规则评分CSV |
| T1 | `data/processed/末世/scores/*_ai_full.csv` | 33本Tier1合并CSV |
| T2 | `data/processed/末世/scores/*_t2_full.csv` | 33本Tier2合并CSV |
| LLM | `data/processed/末世/scores/*_llm.csv` | 33本T1+T2合并CSV |
| Golden | `data/golden/末世/human_golden.csv` | 30章人工标注 |
| Tier3 | `data/golden/末世/tier3/tier3_glm_scores.json` | 95章GLM标注 |
| Tier3计划 | `data/golden/末世/tier3/*_tier3_plan.csv` | 7本S级书采样计划 |
| 校准 | `data/reports/末世/calibration/tier3_calibration.json` | OLS+LOOCV结果 |
| Borda | `data/reports/末世/synthesis/末世_borda_ranking.json` | Borda排名JSON |
| TOPSIS | `data/reports/末世/synthesis/末世_topsis_ranking.json` | TOPSIS排名JSON |
| 分级 | `data/reports/rankings/末世/v8.8_final_ranking.csv` | 35本分级表 |
| 商业评分 | `data/processed/末世/quality/commercial_scores.json` | 商业评分缓存 |
| 审计(旧) | `data/reports/末世/full_audit_t1t2.json` | T1+T2全量审计 |
| 商业引擎 | `src/xiaoshuo/pipeline/scoring/commercial_engine.py` | 商业评分代码 |
| Borda排名 | `src/xiaoshuo/pipeline/scoring/borda_ranker.py` | Borda排名代码 |
| 规则分析 | `src/xiaoshuo/pipeline/rhythm/rule_analyzer.py` | Rhythm规则代码 |
| 配置 | `config.yaml` | SSOT配置 |

---

## 七、技术注意事项

1. **终端问题**: PowerShell无法输出中文，所有脚本输出必须重定向到文件后用`read_file`读取
2. **numpy缺陷**: `np.corrcoef`触发Windows DLL错误(0xc06d007f)，需用手动Pearson公式
3. **编码**: JSON=UTF-8无BOM, CSV=UTF-8带BOM(Excel兼容)
4. **Python环境**: `D:\miniconda3\envs\llm-shared\python.exe`
5. **工作目录**: `d:\Code\xiaoshuo`
6. **校准脚本**: `scripts/_test_step2.py` (输出到`scripts/_test_step2_out.txt`)

---

## 八、审计结论模板

```markdown
# 审计报告 v8.10

## 总体评价
- 数据完整性: [PASS/WARN/FAIL]
- 评分关系: [PASS/WARN/FAIL]  
- 排名可靠性: [PASS/WARN/FAIL]
- 总体可信度: [高/中/低]

## 关键发现
1. [发现1]
2. [发现2]
...

## 风险清单
| 风险 | 级别 | 影响 | 缓解措施 |
|------|------|------|----------|
| ... | 高/中/低 | ... | ... |

## 改进建议
1. [建议1]
2. [建议2]
...
```
