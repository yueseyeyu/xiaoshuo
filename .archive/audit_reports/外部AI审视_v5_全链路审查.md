# 外部AI审视指令 — 末世小说商业评分全链路审查 v5

> 请以「独立 AI 审计员」身份，对以下系统进行完整审查。
> 逐条回答审查问题。每项给出 ✅/⚠️/❌ 判定 + 行号依据 + 优化建议。

---

## 一、系统概述

本系统对 10 本番茄末世火书（14,696章）进行三层分析，最终输出商业签约评分。

### 全链路架构

```
┌─────────────────────────────────────────────────────────────┐
│  第1层: rhythm_analyzer.py (正则规则引擎, 零LLM成本)         │
│  输入: data/novels/*.txt                                    │
│  处理: 章节提取 → 9类爽点正则 → 5类冲突正则 → 句式分析       │
│  输出: data/rhythm/rhythm_*.csv (每本22维逐章数据)           │
├─────────────────────────────────────────────────────────────┤
│  第2层: llm_batch_score.py (LLM量规打分, Rubric驱动)         │
│  输入: data/novels/*.txt + data/rhythm/*.csv                 │
│  处理: Qwen3.5-9B 对每章按6维量规独立打分(1-10)             │
│  输出: data/llm_scores/*_llm.csv (60章/本, 分层抽样)        │
├─────────────────────────────────────────────────────────────┤
│  第3层: genre_synthesizer.py (融合+拆书+商业评分)            │
│  输入: data/rhythm/*.csv + data/llm_scores/*.csv             │
│  处理: Bayesian BMA融合 → 百分位排名 → 子类型校准 → 综合评分  │
│  输出: 末世_写作技法总纲.md (商业评分+拆书报告+留存预估)       │
└─────────────────────────────────────────────────────────────┘
```

### 校准数据来源
- `data/calibration/feature_importance.csv` — 100章独立校准 (calibrate_v2.py)
- Pearson r: 15个规则特征 vs LLM强度评分
- 最强规则特征: pos_density(r=0.445) > conflict_density(r=0.406) > crush_count(r=0.300)

---

## 二、第1层: 正则规则引擎 (rhythm_analyzer.py)

### 2.1 章节提取
**代码**: `extract_chapters()` L146-183
**方法**: 4层fallback正则匹配 (第X章 → 序章+章X → 数字标题 → 裸数字)
**审查问题**:
1. 4层fallback是否覆盖所有网文章节格式？有没有已知的失败案例？
2. L193 `if len(pure_text) < 50: continue` — 50字过滤是否可能丢掉有效内容（如序章/短章节）？

### 2.2 爽点检测 (9类, L28-57)
**分类**:
- 显式(6类): PLEASURE_FACE_SLAP(打脸), PLEASURE_LEVEL_UP(突破), PLEASURE_CRUSH(碾压), PLEASURE_COMEBACK(绝地反击), PLEASURE_HIDDEN(扮猪吃虎), PLEASURE_GENERAL(泛爽)
- 隐式(3类): PLEASURE_BOND(羁绊), PLEASURE_COGNITIVE(认知突破), PLEASURE_SACRIFICE(牺牲)
- 生理信号: PHYSIO_REACTION(瞳孔骤缩等)

**审查问题**:
3. PLEASURE_BOND 正则(L37-41)包含 `"面板弹出|推演显示|模拟得出|第一条规则|从未见过"` — 这些是智斗/系统流特征，混入羁绊类是否合理？
4. 羁绊消歧(L258-265): 需要30字共现 `"你|我|他|她|眼中|心里|轻声|沉默|握住|凝视|月|林默"` 才算有效。这里硬编码了主角名"月"和"林默"——换一本书怎么办？
5. 9类爽点权重在 `pos_density` 中完全等权(L270: 所有count简单相加)。sacrifice_count(r=-0.13 vs LLM) 和 cognitive_count(r=0.017) 实际是噪声特征，等权会稀释最强信号(pos_density r=0.445)。是否应该用 r 值做加权？

### 2.3 冲突检测 (5类, L60-95)
**审查问题**:
6. CONFLICT_KW_ALL(L84-95) 合并了战斗+心理+道德+环境+社会5类。`"你敢|休想|去死"` 这三个词在网文中极其高频——是否有严重过匹配风险？
7. 冲突密度计算(L284-285): `conflict_density = conflict_count / max(wc, 1) * 100`。但这不是真正的"密度"，而是每百字冲突词出现次数。如果两个章节冲突词相同但一章5000字一章2000字，短章会得到更高分——这是预期行为吗？

### 2.4 爽点强度公式 (L329-343)
```python
pleasure_raw = (
    pos_density * 2.0 +         # r=0.445
    conflict_density * 1.5 +    # r=0.406
    excl_density * 0.5 +
    dialogue_ratio * 2 +        # r=-0.091 noise!
    hook_density * 0.5 -
    neg_density * 0.2 +
    physio_count * 2.0 / max(wc/100, 1)
)
pleasure_raw = pleasure_raw * 0.7 + 1.5  # 压缩+降低天花板
pleasure_intensity = max(0, min(10, pleasure_raw))
```

**审查问题**:
8. `dialogue_ratio * 2` — calibrate_v2 显示 r=-0.091（极弱负相关），权重却给了2。这是噪音放大器还是刻意保留？（注释说"从8降到2"，但2对于r=-0.09的特征仍然偏高）
9. `* 0.7 + 1.5` 的压缩公式从何而来？这个硬编码的1.5偏移是否会使所有书的强度分数无法低于1.5，压缩了低分区分度？

---

## 三、第2层: LLM量规打分 (llm_batch_score.py)

### 3.1 关键设计
**评分量规** (_RUBRIC_TEMPLATE L55-74):
- 6维: 爽点强度(1-10)、冲突等级(none/low/medium/high)、情绪氛围(7类)、节奏(3类)、钩子质量(3类)、读者留存力(1-10)
- 每个等级有锚定描述

**审查问题**:
10. 每章仅截取 `chapter_text[:1200]` 字符送给LLM。对于平均3000字的网文章节，只分析前40%是不是错过了章末高潮和钩子？前端和后端评分是否一致？
11. Qwen3.5-9B 是本地的 Q4_K_M 量化模型(5.68GB)。该模型在文学评价任务上的已知偏差（Self-Preference Bias, arxiv 2410.21819）是否会影响打分？有无同模型自我校准或交叉验证？
12. 60章分层均匀采样 (`step = len(chapters)//60`) — 对于结构特殊的书（如200章日常+200章高潮），均匀采样可能错过密度集中的区域。是否考虑过密度加权采样？

### 3.2 新功能: Self-Consistency (--sc N)
**代码**: `llm_score_self_consistency()` L120-205
**方法**: 多温度(0.1/0.2/0.3) × N次采样，median取数值，mode取分类
**审查问题**:
13. 温度范围 0.1-0.3 差异很小（对 Qwen3.5 的 token distribution 影响有限）。是否应该扩大到 0.1-0.7 以增加样本多样性？
14. 分类特征用 mode(多数投票) 聚合——如果3个样本分别是 fast/medium/slow，mode 会随机选第一个。是否该用 ranked voting 或 fallback 到 medium？

### 3.3 章节编号修复 (R4发现)
**原代码**: `ch_num = i + 1` (循环索引)
**修复**: `ch_num = ch.get("num", i + 1)` (实际章节号)
**审查问题**:
15. 修复后，`ch["num"]` 来自 `extract_chapters()` 的 `_build_chapters()`, 其中 `ch_num` 通过4种regex提取。对于序章(ch_num=0)会重新编号为1(L228)。这会导致 `rule_rows.get(ch_num, {})` 序章匹配到第1章。是否有更好的序章处理？

---

## 四、第3层: 融合+商业评分 (genre_synthesizer.py v8)

### 4.1 火书池基准 (get_firebook_pool, L247-315)
**审查问题**:
16. 火书池只有10本。百分位排名的 `rank/(n-1)*100` 在 n=10 时分辨率极低（每档间隔~11.1%）。这是否能有效区分质量差异？n=30 会显著改善吗？
17. P25/P50/P75 从10本书的分布计算——对开篇3章做分布估计，样本量太小。`_p()` 函数用线性插值(L293-301)，对小样本效果如何？

### 4.2 Bayesian BMA融合 (v8新增)
**代码**: `_load_bayesian_weights()` L27-71, 权重公式:
```python
r2 = r²
w_rule = max(0.05, r²/(1+r²))
w_llm = 1.0 - w_rule
```
**应用** (L440-460):
- intensity: pos_density(w=0.18) + LLM(w=0.82)
- hook: hook_density(w=0.05) + LLM微量(2.5%)
- conflict: conflict_density * 1.04 (温和上调)

**审查问题**:
18. `r²/(1+r²)` 公式假设规则和LLM误差独立且方差相等。但实际 Qwen3.5 的评分方差可能远大于规则的方差（LLM有采样噪声）。是否应该从校准数据中估计真实的 variance ratio 而非假设相等？
19. intensity 融合时，`pos_density` 通过 `(x+0.5)*10` 映射到0-10——pos_density 最大值实测约0.5，但这来自10本火书。如果用在自己写的书上，pos_density 可能超0.5，导致 `rule_intensity_proxy > 10` 被 clamp。这个缩放假设是否安全？

### 4.3 子类型感知权重 (L497-510)
**审查问题**:
20. Grid Search 权重包:
   - 打脸流: sign=0.40, retain=0.30, bonus=0.30
   - 智斗流: sign=0.45, retain=0.15, bonus=0.40
   - 羁绊流: sign=0.20, retain=0.25, bonus=0.55
   Grid Search 是在多大网格上跑的？是否过拟合到10本书？（Spearman 0.66 vs 完读率，并不算高）

### 4.4 商业评分维度
**签约三要素**(前3章): 钩子/冲突/爽点 — 百分位排名
**留存**: 零钩子连续+打脸频率+爽点多样性 — 百分位
**爆款**: 反转频率+悬念频率+大爽频率+读者留存力 — 加权平均

**审查问题**:
21. "前3章钩子"用前3章的 `hook_density` 均值——但章末钩子（章尾500字分析）和前3章均值是不同概念。是否混淆了章节内钩子密度和章节间钩子？
22. "读者留存力"从 `llm_retention * 10` 映射到0-100。LLM retention 是1-10分，×10后范围10-100。但 `scores["读者留存力"] = round(llm_avg_retention * 10)` — retention直接参与加权，未做百分位归一化（其他维度都是0-100百分位）。这是否导致 retention 权重失衡？

### 4.5 Survival分段留存
**代码**: `compute_segment_retention()` L715-758
**公式**: `est = 85 - zero_hook_ratio*40 - max(0, 0.3-avg_conflict)*30 + min(10, pleasure_avg*2) + pace_diversity*2`

**审查问题**:
23. 这个公式完全是 heuristic——base=85 从何而来？penalty=40/30 从何而来？如果用于决策（如章节发布前质量检查），错误估计可能导致误判。

---

## 五、综合审查

### 5.1 数据流完整性
24. `genre_synthesizer.py` 的 `_find_book_stem()` (L93-102) 通过LLM CSV的前5行匹配书本章节号。如果两本书的章节号模式相同（如都是1-5章有LLM数据），匹配会错误。需要更好的 book identity 传递机制吗？
25. LLM打分CSV的 `ch_num` 现在来自 `extract_chapters()`，而 rhythm CSV 的 `ch_num` 也是同一个来源。但若两次提取结果不同（encodings/regex matching差异），两个CSV的章节号可能不对齐。是否需要统一章节索引？

### 5.2 方法论有效性
26. 整个系统的核心假设：**正则词典 + Qwen3.5评分 → 可以预测番茄完读率**。当前验证是通过 10本书的 Spearman r=0.66。在 ML 评估中，n=10 且 r=0.66 的置信区间非常宽（95%CI约 [0.1, 0.9]）。需要多少本书才能让 r 的置信区间收窄到有意义的范围？
27. 系统对"完读率"的校准只用了 Grid Search 调权，而非独立的 holdout 验证。这是否构成数据泄露（将同一批书的完读率既用于权重调优又用于评估）？

### 5.3 工程质量
28. L428-486 的 `compute_commercial_score()` 返回 15 个字段（scores字典+risks+pool_n+sub_genre+zero_var_dims+grade_stability）。多个字段的生成逻辑依赖前面计算的结果——是否有潜在的 None/crash 路径？
29. `auto_benchmark()` L990-1033 写入 `rhythm_benchmark.md` 到 `output_dir` — 但 output_dir 是在 `main()` 中通过 `DATA_DIR/"analysis"/genre/"synthesis"` 构建的。如果 `DATA_DIR` 被错误配置，路径会指向哪里？

---

## 六、优化方向（请评价每个方向的可行性）

### 方向A: 用 calibrate_v2 的100章数据进行 Platt Scaling
当前强度公式 `pleasure_raw * 0.7 + 1.5` 是手动调参。使用校准数据做 `LLM = a*Rule + b` 线性回归（Platt Scaling），得到数据驱动的映射。可行性？

### 方向B: 引入 BoW(Bag-of-Words) 或 TF-IDF 替代纯正则
正则规则对同义词/变体不敏感（如"打脸"=打脸，但"啪啪打脸"/"脸被打肿"/"耳光"可能漏检）。用 TF-IDF + 种子词扩展能否提升覆盖率？

### 方向C: 多模型交叉验证降低 LLM bias
当前只用 Qwen3.5 一种模型打分。如果启动 DeepSeek-R1 (8002端口) 做交叉验证，取两个模型的一致性分数——是否值得？额外的时间/显存成本？

### 方向D: n=10 → n=30 扩展火书池
把另外7本非末世书（玄幻/都市/仙侠等）也纳入基准池，虽然题材不同但基础指标（hook_density/conflict_density）可能跨题材可比。是否应该做跨题材基准？

---

## 审查输出格式

对29个审查问题，每个问题输出:
```
[#N] 判定: ✅/⚠️/❌
依据: 文件:行号 — 具体代码或配置
问题: (简述)
建议: (具体修改方案, 如有)
```

最后输出综合结论: **系统可信度评级 (1-5)** + **最优先修复的3项**。
