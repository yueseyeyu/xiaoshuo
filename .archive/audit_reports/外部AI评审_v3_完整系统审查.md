# 外部 AI 评审 v3：完整系统审查

> **用途**: 提交给外部 AI (GPT-4/Claude/DeepSeek)，审查完整拆书+商业评分系统的可信度与优化方向
> **项目**: 《末日模拟器》末世智斗羁绊流 · 目标平台: 番茄小说
> **迭代**: v1(5本,评审3-6分) → v2(10本,评审4.5-7分) → **v3本次**(10本+100章LLM校准+5项优化)

---

## 0. 系统架构

```
data/novels/末世/ 10本 TXT (14,733章)
     ↓ extract_chapters (4格式: 第X章/章X/数字标题/纯数字)
rhythm_analyzer.py v5 → data/rhythm/ 28列 CSV
     ↓ 9类爽点 + 5类冲突 + 500字钩子 + 生理信号 + 羁绊消歧 + 校准公式
genre_synthesizer.py v5 → 拆书报告 + 商业评分 + 节奏基准
     ↓ 秩排序 + 子类型权重包 + 余弦微池 + 置信区间
calibrate_v2.py → 100章 LLM 独立评分 → 特征重要性 + 偏置曲线
```

---

## 一、拆书逻辑 — rhythm_analyzer.py v5

### 1.1 章节解析 (4 格式)

```python
cn_nums = r"[一二三四五六七八九十百千零\d]+"
# 1. 第X章 (95%)
pattern1 = r"(第" + cn_nums + r"章\s*[^\n]*)"
# 2. 序章 + 章X (狩魔手记)
pattern2 = r"(序章\s*[^\n]*|章" + cn_nums + r"\s*[^\n]*)"
# 3. 数字 标题 (限制级末日症候: "1 厕所怪谈")
pattern3 = r"(^[ \t]*\d{1,4}[ \t]+[^\d][^\n]*)"
# 4. 纯数字行 (fallback)
pattern4 = r"(^[ \t]*\d{1,4}[ \t]*$)"
```

### 1.2 爽点检测 — 9 类关键词 (v4 外部评审驱动)

```
A. 显式 (v3): 打脸/突破/碾压/绝地反击/扮猪吃虎/通用爽感 — 词库见附录
B. 隐式 (v4新增):
   PLEASURE_BOND:
     羁绊|守护|并肩|碰了碰|贴着|靠着|扶住|接住|挡在|护在|唯一|只有你|...
   PLEASURE_COGNITIVE:
     原来如此|识破|洞察|算到|预判|面板弹出|推演显示|从未见过|...
   PLEASURE_SACRIFICE:
     燃[烧尽]|耗尽|透支|本源|代价|拼了|不计代价|心甘情愿|...
C. 生理反应 (v4新增):
   PHYSIO_REACTION:
     瞳孔[骤微]?缩|呼吸[一戛]?滞|脊背发?凉|说不出话|沉默[了很]?久|...
```

### 1.3 v5 羁绊消歧 — 上下文 30 字共现约束

```python
bond_count = 0
for m in PLEASURE_BOND.finditer(body):
    start = max(0, m.start() - 30)
    end = min(len(body), m.end() + 30)
    ctx = body[start:end]
    if re.search(r"你|我|他|她|眼中|心里|轻声|沉默|握住|凝视", ctx):
        bond_count += 1
# 目的: "守护仓库" ≠ "守护恋人"
```

### 1.4 冲突检测 — 5 类 (v4)

```
物理战斗: 杀|轰|爆|血|战斗|进攻|武器|决战|...
心理博弈: 试探|算计|博弈|陷阱|猜忌|动摇|识破|...
道德困境: 抉择|牺牲谁|背叛|欺骗|隐瞒|底线|不该|...
环境对抗: 饥饿|辐射|污染|窒息|崩塌|变异|侵蚀|...
社会冲突: 规则|秩序|权力|质疑|反对|驱逐|孤立|...
```

### 1.5 章末钩子 (v4: 500 字 + 段落结构)

```python
ending = body[-500:]
ending_paras = PARA_SPLIT.split(ending)
# 悬念式: 竟然|居然|但是|然而|只不过 (末300字)
# 反转式: 短段接长段 (last_para<30字 且 last2_para>80字) 或 长句→短句突变
# 情绪炸弹: 从[来没]|再也[不没]|永远|终于 (末300字)
# 信息投放: 翻开|显示|弹出|浮现|亮起|闪烁 (末300字)
```

### 1.6 v5 爽点强度公式 — 校准驱动

```python
# 100章LLM校准: pos_density(r=0.445), conflict_density(r=0.406) 是最强特征
# dialogue_ratio(r=-0.091) 降权, level_count(r=0.086)/sacrifice(r=0.053)/cognitive(r=0.017) 剔除
pleasure_raw = (
    pos_density * 2.0 +           # r=0.445 最强特征
    conflict_density * 1.5 +      # r=0.406
    excl_density * 0.5 +          # 降权
    dialogue_ratio * 2 +          # v4:8→v5:2 (r=-0.091)
    hook_density * 0.5 -
    neg_density * 0.2 +
    physio_count * 2.0 / max(wc/100, 1)
)
# v5: 温和校准 LLM = 0.106*Rule + 2.8 → 实际用 ×0.7 + 1.5
pleasure_raw = pleasure_raw * 0.7 + 1.5
pleasure_intensity = clamp(pleasure_raw, 0, 10)
```

---

## 二、商业评分逻辑 — genre_synthesizer.py v5

### 2.1 秩排序百分位 (v4 → v5 保留)

```python
def percentile_score(value, pool, metric):
    sorted_vals = pool[metric]["_sorted"]
    rank = sum(1 for v in sorted_vals if v <= value)
    n = len(sorted_vals)
    return round((rank - 1) / (n - 1) * 100)  # 0-100
```

### 2.2 子类型感知打脸频率 (v4 → v5 保留)

```python
_slap_zones = {
    "打脸流": (0.25, 0.50),
    "智斗流": (0.05, 0.15),
    "羁绊流": (0.05, 0.10),
    "通用":   (0.20, 0.45),
}

# 子类型检测: 基于 dominant_sub 分布
# 羁绊流: implicit_ratio > 0.3 AND sacrifice > bond*0.5
# 智斗流: cognitive > slap AND comeback > slap
# 打脸流: slap_ratio > 0.5
```

### 2.3 v5 子类型权重包 (100章校准偏置驱动)

```python
# 校准偏置: 打脸流 -3.54 (规则大幅高估), 智斗 -0.69, 羁绊 -0.29
_genre_weights = {
    "打脸流": {"sign": 0.50, "retain": 0.30, "bonus": 0.20},
    "智斗流": {"sign": 0.35, "retain": 0.30, "bonus": 0.35},  # 悬念反转↑
    "羁绊流": {"sign": 0.30, "retain": 0.45, "bonus": 0.25},  # 留存=情感粘性
    "通用":   {"sign": 0.45, "retain": 0.30, "bonus": 0.25},
}

overall = sign*w["sign"] + retain*w["retain"] + bonus*w["bonus"]
```

### 2.4 v5 余弦相似度微池 (新增，已知问题)

```python
# 计算目标书与每本火书的特征向量余弦相似度
# 取 Top 3 最相似的书构建子池做秩排序
# 特征: hook/conflict/intensity/slap_rate/bond_ratio/cognitive_ratio/sacrifice_ratio
# ⚠️ 已知问题: n=3 时排名极不稳定, v5 评分出现剧烈波动
```

---

## 三、100 章 LLM 校准结果

### 3.1 总体相关性

| 指标 | 值 |
|------|:---:|
| 样本 | 100 chapters (10本×10章) |
| 模型 | Qwen3.5-9B @ localhost:8000 |
| 校准公式 | LLM = 0.106 × Rule + 2.8 |
| Rule-LLM r | **0.123** |

### 3.2 15 个特征的单变量 r (vs LLM 爽点强度)

| 特征 | r | 保留? | 说明 |
|------|:---:|:---:|------|
| pos_density | **0.445** | ✅ | 最强特征 |
| conflict_density | **0.406** | ✅ | |
| crush_count | **0.300** | ✅ | |
| neg_density | **0.241** | ✅ | |
| physio_count | **0.179** | ✅ | 生理信号有效 |
| comeback_count | **0.178** | ✅ | |
| bond_count | **0.155** | ✅ | 消歧后仍有效 |
| rule_intensity | **0.123** | ✅ | 组合特征反而不如单体 |
| excl_density | 0.108 | ✅ | 边际有效 |
| hook_density | 0.096 | ✅ | 边际有效 |
| slap_count | 0.096 | ✅ | |
| dialogue_ratio | **-0.091** | ✅ | 微弱负相关(噪声) |
| level_count | 0.086 | ❌ | |
| sacrifice_count | 0.053 | ❌ | |
| cognitive_count | 0.017 | ❌ | 几乎零相关 |

### 3.3 子类型偏置 (规则 - LLM)

| 子类型 | 偏置 | 样本 | 含义 |
|------|:---:|:---:|------|
| slap(打脸流) | **-3.54** | 5 | 规则极度高估 |
| smart(智斗流) | **-0.69** | 9 | 规则略高估 |
| bond(羁绊流) | **-0.29** | 48 | 接近一致 |
| general(通用) | **-1.31** | 38 | 规则明显高估 |

---

## 四、10 本末世火书 v5 最终评分

### 4.1 拆书总览

| # | 书名 | 章 | hook | conf | 多样性 | 6→6 |
|:---:|------|:---:|:---:|:---:|:---:|:---:|
| 1 | 全球进化 (咬狗) | 437 | 1.40 | 0.58 | 0.582 | 进化末世 |
| 2 | 十日终焉 (杀虫队队员) | 1359 | 1.58 | 0.54 | 0.522 | 无限流/智斗 |
| 3 | 我在末世种个田 (无颜墨水) | 1716 | 2.36 | 0.37 | 0.579 | 种田生存 |
| 4 | 末世之黑暗时代 | 1007 | 5.78 | 0.79 | 0.833 | 生存悬念 |
| 5 | 超级神基因 (十二翼) | 2153 | 2.52 | 1.03 | 0.748 | 废土猎杀 |
| 6 | 黑暗血时代 (天下飘火) | 1855 | 0.84 | 0.94 | 0.705 | **智斗心理** |
| 7 | 黑暗文明 (古羲) | 926 | 2.53 | 1.02 | 0.764 | 进化战斗 |
| 8 | 狩魔手记 (烟雨江南) | 568 | 2.08 | 1.03 | 0.843 | **废土羁绊** |
| 9 | 末日蟑螂 (伟岸蟑螂) | 2404 | 1.07 | 0.94 | 0.627 | 废土生存 |
| 10 | 限制级末日症候 (全部成为F) | 2271 | 1.13 | 0.68 | 0.766 | **心理悬疑智斗** |

### 4.2 商业评分 (v5)

| # | 书名 | v4 | v5 | 变化 | 评级 | 完读率 |
|:---:|------|:---:|:---:|:---:|------|:---:|
| 1 | 全球进化 | 56 | **52** | -4 | ✅ | 91-95% |
| 2 | 十日终焉 | 55 | **59** | +4 | ✅ | 91-96% |
| 3 | 种个田 | 34 | **52** | +18 | ✅ | 96-98% |
| 4 | 黑暗时代 | 73 | **61** | -12 | ✅ | 99-100% |
| 5 | 超级神基因 | 72 | **51** | -21 | ✅ | 97-99% |
| 6 | 黑暗血时代 | 48 | **26** | -22 | ❌ | **83-88%** |
| 7 | 黑暗文明 | 72 | **44** | -28 | ⚠️ | 98-99% |
| 8 | 狩魔手记 | 46 | **65** | +19 | ✅ | **95-100%** |
| 9 | 末日蟑螂 | 33 | **18** | -15 | ❌ | 88-97% |
| 10 | 限制级末日症候 | 52 | **37** | -15 | ⚠️ | **95-97%** |
| — | **均值** | 54.1 | **46.5** | -7.6 | — | — |

### 4.3 完读率 vs 商业分 矛盾

| 书名 | 完读率 | 商业分 | 矛盾 |
|------|:---:|:---:|------|
| 狩魔手记 | **95-100%** | 65 | ✅ 一致(高分) |
| 黑暗时代 | **99-100%** | 61 | ⚠️ 完读最高但非最高分 |
| 限制级末日症候 | **95-97%** | **37** | ❌ 严重低估 |
| **黑暗血时代** | **83-88%** | **26** | 相对一致(偏低) |
| 末日蟑螂 | **88-97%** | **18** | ❌ 严重低估 |

---

## 五、v1→v2→v3 迭代对比

| 维度 | v1 | v2 | v3 |
|------|------|------|------|
| 火书池 | 5 | 10 | 10 |
| 爽点类型 | 6(全显式) | 9(+3隐式) | 9(+羁绊消歧) |
| 冲突类型 | 1(战斗) | 5(+4非战斗) | 5 |
| 百分位 | 线性P25-P75 | 秩排序 | 秩排序 |
| 打脸 | 一刀切0.25-0.5 | 子类型分化 | 子类型分化 |
| 权重 | 50/30/20 | 50/30/20 | **子类型权重包** |
| 钩子窗口 | 200字 | 500字 | 500字 |
| 爽点公式 | 手工调参 | 手工调参 | **校准驱动** |
| LLM校准 | 无 | 25章 r=0.16 | **100章 r=0.12** |
| 羁绊消歧 | 无 | 无 | **30字共现** |
| 余弦微池 | 无 | 无 | **Top3子池(已知不稳定)** |
| 评分均值 | 50.6 | 54.1 | 46.5 |
| 限制级末日症候 | — | 52 | **37 ↓** |

---

## 六、已知问题（诚实暴露）

### 6.1 余弦微池过度激进
n=3 子池排名极不稳定，导致限制级末日症候(95%完读率)从 52→37 分、黑暗血时代从 48→26 分。这明显是反向优化。

### 6.2 校准压缩过头
LLM = 0.106×Rule + 2.8 的映射极陡，导致爽点强度被压缩到 2-4 窄区间。温和版(×0.7+1.5)可能仍然偏保守，评分均值从 54→46.5 下降了 7.6 分。

### 6.3 cognitive_count r=0.017
"认知突破"类关键词与 LLM 爽点感知几乎零相关——这意味着正则无法有效捕获智斗流的"认知爽点"。这对《末日模拟器》是致命缺陷。

### 6.4 限制级末日症候悖论未解决
完读率 95-97% 的书商业分只有 37——v5 不仅没解决，反而恶化了。这说明当前体系对"高粘性低爽点"书的系统性偏见仍未消除。

### 6.5 所有特征 r 都在 0.5 以下
最强的 pos_density 也只有 r=0.445。没有任何特征与 LLM 爽点判断有中等以上相关。纯正则方法可能确实已达天花板。

---

## 七、穷举搜索指令（强制执行）

> ⚠️ 在回答评审问题之前，**必须先执行以下搜索**。每个方向至少 3 次不同关键词搜索，引用至少 2 个外部来源的原句。

### 搜索方向 A: 纯正则 vs 小模型 — 中文网文分析的最优方案
搜索目标：有没有论文/项目证明纯正则方法在文学文本分析上的天花板？有没有用小型 LLM（<10B）做章节级情感/爽点/冲突评分的成功案例？
- 关键词示例: `small LLM chapter-level sentiment scoring fiction Chinese web novel rule-based vs neural 2024 2025`
- 关键词示例: `lightweight text evaluation model narrative quality scoring fine-tuned 3B 7B story analysis`
- 关键词示例: `regex keyword matching ceiling recall rate literary text implicit sentiment detection benchmark`

### 搜索方向 B: 智斗/认知爽点的检测方法
搜索目标：智斗流爽感本质是"信息差→识破→反制"，属于结构性叙事特征。有没有 NLP 方法专门检测叙事结构/信息转折/反转型段落？
- 关键词示例: `narrative structure detection plot twist reversal pattern text analysis computational narratology`
- 关键词示例: `information gap resolution cognitive satisfaction detection text surprise plot twist NLP`
- 关键词示例: `story understanding plot point detection turning point narrative arc computational 2024 2025`

### 搜索方向 C: 小样本池的稳健排序方法
搜索目标：n=10 时秩排序极不稳定。有没有统计方法在小样本下提供置信区间？有没有"贝叶斯排序"或"James-Stein shrinkage"等收缩估计方法？
- 关键词示例: `small sample ranking stability Bayesian hierarchical model shrinkage estimator n<20`
- 关键词示例: `robust rank aggregation small N bootstrap confidence interval percentile`
- 关键词示例: `James-Stein estimator ranking small sample shrinkage empirical Bayes sports statistics`

### 搜索方向 D: 用完读率作为训练目标
搜索目标：我们有关键矛盾——限制级末日症候完读率 95%+ 但商业分 37。有没有方法直接以"读者留存/完读率"为监督信号，倒推哪些文本特征真正驱动读者粘性？
- 关键词示例: `reader retention prediction web novel chapter-level engagement features machine learning`
- 关键词示例: `survival analysis reader dropout prediction serial fiction completion rate text features`
- 关键词示例: `predicting reader engagement narrative features cliffhanger suspense retention rate NLP`

### 搜索方向 E: Embedding 替代正则 — 隐式爽点检测
搜索目标：鲁棒性的中文 embedding 模型（最好是轻量的），能否用句子向量余弦相似度检测"羁绊/温情/悲壮"等隐性情感？
- 关键词示例: `Chinese sentence embedding implicit sentiment bond emotion detection cosine similarity lightweight CPU`
- 关键词示例: `bge-small-zh evaluation implicit sentiment benchmark literary text emotion`
- 关键词示例: `unsupervised emotion detection text embedding prototype matching few-shot sentiment`

### 搜索方向 F: 开源的网文/小说分析工具
搜索目标：有没有 GitHub 上的开源项目在做类似的事（网文/小说节奏分析、爽点检测）？有没有可以直接借鉴的？
- 关键词示例: `GitHub Chinese web novel analysis rhythm pleasure point detection open source`
- 关键词示例: `novel analysis tool storytelling structure detection fiction NLP open source project`
- 关键词示例: `web fiction writing assistant AI analysis tool chapter evaluation open source`

---

## 八、评审问题（搜索完成后回答）

### 核心问题
1. **r=0.12 -- 这个系统还有救吗？** 所有 15 个特征的 r 都 <0.5。100章校准证明纯正则与LLM感知几乎无关。下一步应该：A) 放弃纯正则，直接用小模型批量打分？ B) 继续扩词库？ C) 加入 Embedding 语义匹配？ D) 其他方案（结合搜索A/D结果）？

2. **余弦微池应该撤回吗？** v5 加入后限制级末日症候从52→37，评分剧烈波动。n=3 太小。应该 n=5？还是不微池直接用全池？有没有更稳健的子池构建方法（结合搜索C结果）？

3. **认知突破 r=0.017 -- 智斗流爽点如何检测？** 正则对"认知爽点"完全失效。结合搜索B找到的论文/方法，有什么替代方案？

4. **子类型权重 35/30/35 的合理性？** 智斗流签约降到35%、悬念反转到35% —— 结合搜索D的完读率预测方法，这些权重能否用数据驱动而非拍脑袋？

5. **限制级末日症候悖论如何修复？** 结合搜索D/F结果，有没有系统性的方法解决"高粘性低爽点"书的评分偏差？

6. **对《末日模拟器》的预估可信度？** 当前系统对"高钩子+智斗+羁绊"混合型无参照物，预估偏差 ±20 分以上。在解决上述问题之前，商业评分是否应该暂停使用？

7. **开源方案参考**（结合搜索F）：有没有现成的项目可以直接借鉴或 fork？

---

## 输出要求

```
1. 穷举搜索证据 (每个搜索方向 >=1 条外部引用原句 + 来源)
2. 整体可信度评分(1-10) + 各项子评分
3. 按优先级 3 项最关键优化建议（每项需引用搜索到的论文/方法）
4. 微池是否撤回的明确判断（Yes/No + 理由）
5. 是否建议放弃纯正则转向小模型打分的明确建议
```
