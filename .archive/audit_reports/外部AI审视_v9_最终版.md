# 外部AI审视指令 — 末世小说商业评分 v9 最终版

> 请以「独立 AI 审计员」身份审查本系统。逐条判定 ✅/⚠️/❌ + 依据 + 建议。

---

## 一、系统目标

对番茄小说平台的末世类网文进行全链路分析，输出 **0-100分制商业签约评分**，预测作品在番茄平台上的签约概率和完读率表现。

---

## 二、样本数据

### 火书池：10本番茄末世完结书

| # | 书名 | 作者 | 字数 | 章 | 子类型 | 完读率 |
|:---:|------|------|------|:---:|------|:---:|
| 1 | 《全球进化》 | 咬狗 | 109万 | 437 | 进化末世 | 93% |
| 2 | 《十日终焉》 | 杀虫队队员 | 306万 | 1359 | 无限流/智斗 | 94% |
| 3 | 我在末世种个田 | 无颜墨水 | 544万 | 1716 | 末世种田 | 97% |
| 4 | 末世之黑暗时代 | 未知 | 238万 | 1007 | 末世生存 | 99% |
| 5 | 超级神基因 | 十二翼黑暗炽天使 | 723万 | 2153 | 废土/基因 | 98% |
| 6 | 黑暗血时代 | 天下飘火 | ~400万 | 1855 | 智斗/心理 | 86% |
| 7 | 黑暗文明 | 古羲 | 282万 | 926 | 进化/战斗 | 99% |
| 8 | 狩魔手记 | 烟雨江南 | ~200万 | 568 | 废土/羁绊 | 98% |
| 9 | 《末日蟑螂》 | 伟岸蟑螂 | ~500万 | 2404 | 废土生存 | 93% |
| 10 | 限制级末日症候 | 全部成为F | ~150万 | 2271 | 心理悬疑/智斗 | 96% |

### 基础设施
- 模型: Qwen3.5-9B Q4_K_M (5.68GB), RTX 5060 8GB
- 推理速度: 600章 ~25min (无sleep + 120tokens + 并行x2)

---

## 三、全链路架构

```
第1层: rhythm_analyzer.py (正则规则引擎, 零LLM)
  └─ 章节提取(4层fallback) → 9类爽点(r加权) + 5类冲突 → 22维CSV

第2层: llm_batch_score.py (LLM量规打分, 并行x2)
  └─ 首尾截取(600+600字) → Qwen3.5-9B 6维量规 → LLM CSV

第3层: genre_synthesizer.py (融合+拆书+商业评分)
  └─ Bayesian BMA融合 + 百分位排名 + 留存力归一化 + 真LOOCV → 报告
```

---

## 四、第1层详细设计 — rhythm_analyzer.py

### 4.1 章节提取
4层正则fallback: `第X章` → `序章+章X` → `数字标题` → `裸数字`
短章过滤: `len(pure_text) < 50` → 丢弃

### 4.2 爽点检测 — 9类 + r加权聚合

9类正则匹配词（示例）:
- 打脸: `打脸|嘲讽|看不起|小瞧|轻视|不屑…`
- 突破: `突破|晋级|进阶|升级|渡劫|觉醒…`
- 碾压: `碾压|秒杀|横扫|秒败|一击…`
- 绝地反击: `绝地|反杀|逆转|翻盘…`
- 扮猪吃虎: `扮猪|隐藏实力|低调|显露…`
- 羁绊: `守护|并肩|一起|等我|伸出手|贴着|靠着…`
- 认知突破: `原来如此|恍然大悟|识破|预判|推演显示…`
- 牺牲: `燃尽|透支|代价|承受|扛住|拼了…`
- 生理信号: `瞳孔骤缩|呼吸一滞|心头一震|脊背发凉…`

**v9 r加权聚合** (CCMMW方法, MDPI Symmetry 2023):
```python
weighted_pleasure = (
    slap_count * 0.096 + level_count * 0.086 + crush_count * 0.300 +
    comeback_count * 0.178 + hidden_count * 0.108 + general_count * 0.108 +
    bond_count * 0.155 + cognitive_count * 0.017 + sacrifice_count * 0.0 +
    physio_count * 0.179
)
pos_density = weighted_pleasure / max(wc, 1) * 100
```

### 4.3 冲突检测 — 5类合并
战斗 + 心理博弈 + 道德困境 + 环境对抗 + 社会冲突 → 等权合并为 `conflict_density`

### 4.4 爽点强度公式 (v9)
```python
pleasure_raw = (
    pos_density * 2.0 +           # r=0.445
    conflict_density * 1.5 +      # r=0.406
    excl_density * 0.5 + hook_density * 0.5 +
    neg_density * 0.2 +           # r=0.241 (欲扬先抑)
    physio_count * 2.0 / max(wc/100, 1)
)
pleasure_raw = pleasure_raw * 0.7       # 纯压缩, 去掉+1.5偏移
pleasure_intensity = max(0, min(10, pleasure_raw))
```

### 4.5 输出: 每本22维CSV
`data/rhythm/rhythm_{书名}.csv` — ch_num, wc, hook_density, conflict_density, dialogue_ratio, pos_density, neg_density, 9×count, pleasure_intensity, emotion, pace, readability...

---

## 五、第2层详细设计 — llm_batch_score.py

### 5.1 LLM量规
```python
_RUBRIC_TEMPLATE = """
=== 你是专业网文编辑，对章节阅读体验独立评分 ===
第{ch_num}章: {chapter_text}

### 评分量规 ###
1. 爽点强度 (1-10): 1=平淡 5=明显爽感 10=巅峰
2. 冲突等级: none/low/medium/high
3. 情绪氛围: 爽快/紧张/悲壮/悬疑/日常/温情/压抑
4. 节奏: fast/medium/slow
5. 钩子质量: none/weak/strong
6. 读者留存力 (1-10): 1=弃书 10=熬夜看
输出纯JSON: {"intensity":5,"conflict":"medium",...}
"""
```

### 5.2 首尾截取策略 (v9)
```python
if len(chapter_text) > 1200:
    text = chapter_text[:600] + "\n...[中段省略]...\n" + chapter_text[-600:]
else:
    text = chapter_text[:1200]
```
理由: 3000字章节前40%是铺垫，章末高潮在后60%。首尾各600字确保LLM看到钩子。

### 5.3 并行处理 (v9)
```python
with ThreadPoolExecutor(max_workers=2) as executor:
    # 每线程独立HTTPConnection, finally关闭
    for fut in as_completed(futures):
        try:
            i, ch_num, *rest = fut.result(timeout=60)
        except Exception as e:
            # 单章失败不中断全批
```
服务端: llama-server `--parallel 2`

### 5.4 输出: 每本60章LLM CSV
`data/llm_scores/{书名}_llm.csv` — ch_num, llm_intensity, llm_conflict, llm_emotion, llm_pace, llm_hook, llm_retention

---

## 六、第3层详细设计 — genre_synthesizer.py

### 6.1 火书池基准 (10本百分位)
```python
get_firebook_pool(genre="末世", exclude_name=None):
    # exclude_name: v9新增, 真LOOCV时剔除held-out书
    for novel in 10本火书:
        读取 rhythm CSV → 提取hook/conflict/intensity/retention均值
    return {hook_density: {p25, p50, p75, _sorted}, ...}
```

### 6.2 Bayesian BMA融合 (v9)
```python
def _load_bayesian_weights():
    # 从 calibrate_v2 的 feature_importance.csv 读取Pearson r
    # w_rule = r²/(1+r²)  下限0.05
    # intensity: pos_density(w=0.18) + LLM(w=0.82)
    # conflict:  conflict_density(w=0.14) 温和上调
    # hook:      hook_density(w=0.05) + LLM微量
```

### 6.3 商业评分公式
```python
# 签约三要素(前3章) — 百分位排名
sign = mean(前3章钩子%, 前3章冲突%, 首章爽点%)

# 留存力 — 百分位
retain_old = mean(零钩子连续%, 打脸频率%, 爽点多样性%)

# 爆款潜力 — 加权融合
bonus = mean(反转频率%, 悬念频率%, 大爽频率%, 读者留存力%)

# 子类型自适应权重 (Grid Search, Spearman 0.67)
overall = sign * gw["sign"] + retain_old * gw["retain"] + bonus * gw["bonus"]
# 打脸流: 0.40/0.30/0.30 | 智斗流: 0.45/0.15/0.40 | 羁绊流: 0.20/0.25/0.55
```

### 6.4 真LOOCV (v9)
```python
for i, held_out in enumerate(10本书):
    pool_9 = get_firebook_pool(exclude_name=held_out)  # 用另外9本建池
    comm = compute_commercial_score(held_out_rows)       # 评分held-out书
    pred_scores.append(comm["overall"])
    true_rates.append(完读率[held_out])

spearman_r = rank_correlation(pred_scores, true_rates)
```

### 6.5 Survival分段留存 (v9: 定性分级)
```python
# 弃用heuristic精确值, 改为信号灯
if zero_hook_ratio > 0.3: risk = "HIGH"
elif zero_hook_ratio > 0.15: risk = "MEDIUM"
else: risk = "LOW"
```

---

## 七、关键设计决策与校准数据

| 决策 | 依据 | 数据来源 |
|------|------|------|
| 9类爽点r加权 | calibrate_v2 100章Pearson r | feature_importance.csv |
| 首尾600+600截取 | 网文结构:铺垫→高潮→钩子 | 5审计员共识 |
| 并行x2 | 线程池+独立HTTP连接 | Python 3.14 docs |
| BMA r²/(1+r²) | 规则方差≈0, LLM方差≈0.3(估计) | calibrate_v2残差 |
| 留存力百分位 | 替代原始×10, 消除权重失衡 | 5审计员共识 |
| neg_density为正 | r=0.241正相关 + Catharsis理论 | calibrate_v2 + 亚里士多德 |
| Survival→定性 | heuristic公式(base=85)无数据支撑 | 5审计员全票弃用 |
| 真LOOCV | 剔除held-out重建池, 无数据泄露 | sklearn LeaveOneOut |

---

## 八、评分历史: v7 → v8 → v9

| 书名 | 完读率 | v7 | v8 | v9 | 评级 |
|------|:---:|:---:|:---:|:---:|------|
| 黑暗时代 | 99% | 74 | 79 | 79 | 🔥 |
| 黑暗文明 | 99% | 69 | 77 | 77 | 🔥 |
| 超级神基因 | 98% | 66 | 72 | 72 | 🔥 |
| 限制级 | 96% | 67 | 72 | 72 | 🔥 |
| 狩魔手记 | 98% | 61 | 67 | 67 | ✅ |
| 黑暗血时代 | 86% | 56 | 62 | 62 | ✅ |
| 全球进化 | 93% | 55 | 61 | 61 | ✅ |
| 末日蟑螂 | 93% | 48 | 53 | 53 | ✅ |
| 十日终焉 | 94% | 45 | 51 | 51 | ✅ |
| **种个田** | **97%** | **34** | **40** | **40** | **⚠️** |
| **均值** | — | **57.3** | **63.4** | **63.4** | — |

| 版本 | Spearman r | LOOCV类型 | 关键变更 |
|------|:---:|------|------|
| v7 | 0.66 | 无(全量池) | 原始BMA 0.3/0.7, 硬编码主角名, 留存×10 |
| v8 | 0.658 | 近似(同池) | r加权, 首尾截取, 留存%, BOND去战斗, 去dialogue |
| v9 | **0.670** | **真LOOCV** | neg_density正号, 去+1.5, Survival定性, 并行x2, try/except |

---

## 九、已知局限与待审查重点

### 9.1 评分合理性
1. **种个田 40分 vs 97%完读率**: 系统对种田流严重低估。前3章无钩子/冲突 → 签约段崩塌。是否应增加"种田获得感"维度?
2. **十日终焉 51分 vs 94%完读率**: 智斗流被低估。心理冲突权重不足。是否应提升智斗子类型权重?
3. **整体+6.1分偏移(v7→v8)**: 修复还是通胀? 是否需Z-score校准?

### 9.2 统计有效性
4. **n=10, r=0.67**: 95% CI 宽达[0.05, 0.91]。需要n=? 才能稳定。
5. **子类型权重过拟合**: 10本书调12个权重参数。

### 9.3 方法论
6. **量规缺末世维度**: 无"资源焦虑"、"道德困境"锚点。
7. **冲突5类等权**: 心理博弈 vs 物理战斗应不同权重。
8. **Platt系数待重校准**: v8/v9公式已变, 0.106系数来自v5。

### 9.4 优化方向
| 方向 | 内容 | 可行性 |
|------|------|:---:|
| A | 重跑calibrate_v2获取v9 Platt系数 | ? |
| B | n=10→30扩展火书池 | ? |
| C | DeepSeek-R1串行交叉验证(switch_model.py) | ? |
| D | 量规增加末世专属维度(资源/道德/智斗) | ? |

---

## 十、审查输出格式

对每个问题输出:
```
[#N] ✅/⚠️/❌
依据: (具体文件行号或数据)
问题: (简述)
建议: (具体方案)
```

末尾: **综合可信度 (1-5)** + **Top 3 优先修复** + **对《末日模拟器》的建议**。
