# 新会话交接文档

> 生成时间: 2026-07-13 (v8.11 Phase 1完成后更新)
> 生成者: CatPaw (项目总负责人角色)

---

## 一、项目当前状态总览

### 已完成管线 (8步全部完成 ✅)

| 步骤 | 状态 | 数据量 | 说明 |
|------|------|--------|------|
| 1. Rhythm 规则评分 | ✅ 33/33本 | 33个rhythm CSV, 43378章 | hook_density等文本特征 |
| 2. Tier1 AI评分 | ✅ 33本/4362章 | 10%均匀分层采样 | 采样率10.0%-10.8%(仅末世超级商人1.6%异常) |
| 3. Tier2 本地模型评分 | ✅ 33本/1110章 | 质量分级采样+节奏峰谷对齐 | T1∩T2零重叠 |
| 4. 合并T1+T2→_llm.csv | ✅ 33本/5472章 | T1与T2零重叠验证通过 | |
| 5. Tier3校准 | ✅ 125章 | 30章人工golden + 95章GLM | 混合OLS slope=0.463, WLS slope=0.524 |
| 6. Commercial Engine + Borda排名 | ✅ 33/33本 | 5维Borda加权 + TOPSIS对照 | Spearman r=0.917 |
| 7. v8.10独立审计 | ✅ 完成 | 审计报告+外部AI审视 | 总体可信度: 中等 |
| 8. v8.11 Phase 1 | ✅ 完成 | IPW+WLS+双slope+分级调整 | S级7→5本, WLS slope=0.524 |

### v8.11 Phase 1 执行结果

**报告**: `data/reports/末世/v8.11_phase1_report.md`
**脚本**: `scripts/v811_phase1.py`

| 执行项 | 状态 | 关键结果 |
|--------|------|---------|
| IPW逆概率加权校正 | ✅ | Spearman r=0.9990, 排名影响极小(仅末世超级商人↓2位) |
| WLS加权校准(人工1.0+GLM0.3) | ✅ | WLS slope=0.524 (介于纯人工0.601和混合0.463) |
| 双slope透明报告 | ✅ | 纯人工0.601 / 混合0.463 / WLS 0.524 三套对比 |
| Golden去重+一致性 | ✅ | 33→30行, 重测MAE=1.00(中等) |
| 末日乐园/长夜余火降为A级 | ✅ | S级从7本降为5本 |
| 未验证TOP1-2标注 | ✅ | 全球变异+深渊召唤师已标注 |

### v8.11 重大修正: T1采样率实际一致

**v8.10审计报告声称**: 11本书采样率异常(0.9%-30.6%), 差异34倍
**v8.11修正后发现**: 审计脚本的rhythm CSV匹配有bug(多本书匹配到同一CSV获909章). 修正后:
- 32/33本书采样率在10.0%-10.8%正常范围
- 仅末世超级商人(1.6%)真正异常
- **采样率风险从"高"降级为"低"**

### 三套校准结果对比 (v8.11)

| 校准方法 | n | intercept | slope | r | R² | 通胀率 |
|----------|---|-----------|-------|---|-----|--------|
| 纯人工OLS | 30 | 0.971 | **0.601** | 0.392 | 0.154 | 66% |
| 混合OLS | 125 | 2.249 | **0.463** | 0.565 | 0.319 | 116% |
| **WLS(1.0+0.3)** | 125 | 1.681 | **0.524** | 0.565 | 0.319 | 91% |

WLS校准文件: `data/reports/末世/calibration/wls_calibration_v811.json`
IPW排名: `data/reports/末世/synthesis/末世_borda_ranking_ipw.json`
清洗后golden: `data/golden/末世/tier3/human_golden_clean.csv`
v8.11排名: `data/reports/rankings/末世/v8.11_final_ranking.csv`

### Borda 排名 TOP10 (v8.11, IPW校正后)

| # | 书名 | Borda | 人工分级 | 关键维度 |
|---|------|-------|---------|----------|
| 1 | 全球变异 | 32.9 | S | signing#8, bt#4, webnovel#3 ⚠️外部口碑未验证 |
| 2 | 末世之深渊召唤师 | 44.8 | **A** | signing#1, webnovel#1 ⚠️signing循环论证 |
| 3 | 末世大回炉 | 47.0 | S | bt#6, webnovel#4 |
| 4 | 地球游戏场 | 49.7 | S | signing#4, diversity#3 |
| 5 | 黑暗血时代 | 53.7 | S | bt#5, signing#5 |
| 6 | 末日拼图游戏 | 54.6 | A | signing#2 |
| 7 | 神秘尽头 | 59.8 | A | bt#1 |
| 8 | 第一序列 | 59.9 | S | bt#2 |
| 9 | 末世魔神游戏 | 62.2 | A | diversity#1 |
| 10 | 我的末世领地 | 65.8 | A | retention#7 |

### 调整后分级 (v8.11)

| 分级 | 数量 | 书名 |
|------|------|------|
| S | 5 | 地球游戏场、末世大回炉、异兽迷城、黑暗血时代、第一序列 |
| A | 13 | 含末日乐园(原S↓)、长夜余火(原S↓)、末世之深渊召唤师等 |
| B+ | 4 | |
| B | 6 | |
| B- | 3 | |
| C | 4 | |

---

## 二、接下来干什么

### Phase 2: 需要LLM推理 (3-7天)

1. **补充末世超级商人T1**: 采样率仅1.6%(8/509), 需补充至10%(约51章)
2. **引入DeepSeek-R1交叉验证**: 对95章GLM数据重新评分, 比较AI间一致性

### Phase 3: 人工标注扩展 (5-10天)

3. **扩大人工标注至60章**: 7本S级书每书8-9章, 使人工占比达48%+
4. **重新校准**: 用60章人工数据重算OLS/WLS
5. **重跑Borda排名**: 校正后数据重算最终排名
6. **生成v8.11最终报告**

### 执行优先级

```
Phase 1 ✅ 完成 → IPW/WLS/分级调整已执行
    ↓
Phase 2 (GPU, 3-7天) → 补充末世超级商人 + DeepSeek-R1交叉验证
    ↓  
Phase 3 (人工, 5-10天) → 扩大标注至60章 + 最终校准
    ↓
v8.11 发布
```

---

## 三、关键目录架构

```
d:\Code\xiaoshuo\
├── data/
│   ├── raw/novels/末世/                    # 33本原始txt
│   ├── raw/novel_index.json                # 小说索引(SSOT)
│   ├── golden/末世/
│   │   ├── human_golden.csv                # 33行(含3重测), 去重后30行
│   │   └── tier3/
│   │       ├── tier3_glm_scores.json       # 95章GLM校准评分
│   │       ├── human_golden_clean.csv      # ★ v8.11: 去重后30行
│   │       └── rescore_prompts/            # GLM评分指令(存档)
│   ├── processed/末世/
│   │   ├── rhythm/                         # 33个rhythm CSV
│   │   ├── quality/                        # commercial_scores.json
│   │   └── scores/
│   │       ├── ai_annotate_batches/        # Tier1批次
│   │       ├── tier2_batches/              # Tier2批次
│   │       ├── *_ai_full.csv               # Tier1合并CSV (33本)
│   │       ├── *_t2_full.csv               # Tier2合并CSV (33本)
│   │       └── *_llm.csv                   # T1+T2合并CSV (33本, 5472章)
│   └── reports/
│       ├── rankings/末世/                  # 排名快照+分级表
│       │   ├── v8.8_final_ranking.csv      # v8.8分级(7本S)
│       │   └── v8.11_final_ranking.csv     # ★ v8.11分级(5本S)
│       └── 末世/
│           ├── audit_v8.10.md              # v8.10独立审计报告
│           ├── v8.11_phase1_report.md      # ★ v8.11 Phase 1报告
│           ├── external_review_synthesis_v8.10.md  # 外部AI审视汇总
│           ├── synthesis/
│           │   ├── 末世_borda_ranking.json      # Borda排名(原始)
│           │   ├── 末世_borda_ranking_ipw.json  # ★ IPW校正后排名
│           │   ├── 末世_topsis_ranking.json     # TOPSIS排名
│           │   └── rhythm_benchmark.md
│           ├── calibration/
│           │   ├── tier3_calibration.json      # Tier3校准(混合OLS)
│           │   └── wls_calibration_v811.json   # ★ WLS校准结果
│           └── writing_manuals/                # 逐章指令
├── scripts/
│   ├── v811_phase1.py                     # ★ v8.11 Phase 1主脚本
│   ├── ai_annotate.py                     # Tier1标注核心
│   ├── _audit_v810.py                     # v8.10审计脚本
│   ├── start_model_safe.bat               # LLM启动
│   └── _archive/                          # 过时脚本归档
├── src/xiaoshuo/pipeline/scoring/
│   ├── commercial_engine.py               # 商业评分引擎
│   └── borda_ranker.py                    # Borda排名器
├── config.yaml                            # 配置SSOT
└── NEW_SESSION_HANDOFF.md                 # 本文档
```

---

## 四、新会话验证步骤

```bash
cd d:\Code\xiaoshuo

# 1. 查看v8.11 Phase 1报告
# 用read_file读取 data/reports/末世/v8.11_phase1_report.md

# 2. 查看WLS校准结果
D:\miniconda3\envs\llm-shared\python.exe -c "import json; d=json.load(open('data/reports/末世/calibration/wls_calibration_v811.json','r',encoding='utf-8')); print(f'WLS slope={d[\"intensity\"][\"slope\"]}, pure_human={d[\"pure_human_ols\"][\"intensity\"][\"slope\"]}')"

# 3. 查看v8.11分级
D:\miniconda3\envs\llm-shared\python.exe -c "import csv; [print(r['rank'],r['book_name'],r['tier']) for r in csv.DictReader(open('data/reports/rankings/末世/v8.11_final_ranking.csv','r',encoding='utf-8-sig'))]"

# 4. 查看IPW校正后排名
D:\miniconda3\envs\llm-shared\python.exe -c "import json; r=json.load(open('data/reports/末世/synthesis/末世_borda_ranking_ipw.json','r',encoding='utf-8')); [print(f'#{x[\"consensus_rank\"]} {x[\"book_name\"][:25]:<27} borda={x[\"total_borda\"]} ipw={x[\"ipw_weight\"]}') for x in r[:5]]"
```

预期输出: WLS slope=0.524, pure_human=0.601, S级5本, IPW TOP1=全球变异

---

## 五、注意事项

1. **np.corrcoef在Windows环境有DLL错误**: 使用手动Pearson公式替代
2. **PowerShell无法输出中文**: 所有脚本输出改为写文件
3. **PYTHONUTF8=1**: 运行含中文路径的Python脚本需设置 `$env:PYTHONUTF8=1`
4. **v8.10审计T1采样率有误**: 审计脚本的rhythm CSV匹配bug导致多本书匹配到同一CSV, v8.11已修正
5. **WLS slope=0.524为v8.11主校准参数**: 纯人工slope=0.601为严格基线
6. **S级精简为5本**: 末日乐园和长夜余火已降为A级(v8.11)
7. **后端服务**: 端口8089, `D:\miniconda3\envs\llm-shared\python.exe -m xiaoshuo.api.server --port 8089`
8. **核心风险仍在**: GLM自评循环论证(76% AI数据)仍是头号风险, 待Phase 3扩大人工标注后解决
