# 新会话交接文档

> 生成时间: 2026-07-13 (v8.10审计后更新)
> 生成者: CatPaw (项目总负责人角色)

---

## 一、项目当前状态总览

### 已完成管线 (7步全部完成 ✅)

| 步骤 | 状态 | 数据量 | 说明 |
|------|------|--------|------|
| 1. Rhythm 规则评分 | ✅ 33/33本 | 33个rhythm CSV, 43378章 | hook_density等文本特征 |
| 2. Tier1 AI评分 | ✅ 33本/4362章 | 10%均匀分层采样 | 采样率0.9%-30.6%(有偏差) |
| 3. Tier2 本地模型评分 | ✅ 33本/1110章 | 质量分级采样+节奏峰谷对齐 | T1∩T2零重叠 |
| 4. 合并T1+T2→_llm.csv | ✅ 33本/5472章 | T1与T2零重叠验证通过 | |
| 5. Tier3校准 | ✅ 125章 | 30章人工golden + 95章GLM | OLS slope=0.463, LOOCV r=0.546 |
| 6. Commercial Engine + Borda排名 | ✅ 33/33本 | 5维Borda加权 + TOPSIS对照 | Spearman r=0.917 |
| 7. v8.10独立审计 | ✅ 完成 | 审计报告+外部AI审视指令 | 总体可信度: 中等 |

### v8.10审计关键发现

**审计报告**: `data/reports/末世/audit_v8.10.md`
**审计脚本**: `scripts/_audit_v810.py` → `scripts/_audit_v810_out.txt`
**外部AI审视指令**: `data/reports/末世/external_ai_review_prompt_v8.10.md`

| 风险 | 级别 | 核心问题 |
|------|------|---------|
| GLM自评循环论证 | **高** | 76%校准数据来自AI, GLM与T1相关性r=0.590 |
| 末日乐园S级缺乏数据支撑 | **高** | diversity#33(倒数第1), webnovel#27(倒数第7) |
| 长夜余火S级依赖作者知名度 | **中** | signing#24, bt#16, 仅diversity#5支撑 |
| T1采样率不一致 | **中** | 0.9%-30.6%, 差异34倍 |
| OLS slope被GLM拉低 | **中** | 纯人工slope=0.762, 混合后0.463, 降幅39% |
| Borda TOP1-2缺乏外部验证 | **中** | 全球变异、末世之深渊召唤师未验证 |
| signing间接循环论证 | **中** | 末世之深渊召唤师signing#1→borda#2但已降A级 |
| Rhythm→LLM传导弱 | **低** | Pearson r均值=0.145 |
| Borda权重非数据驱动 | **低** | Entropy vs config在diversity上严重分歧 |
| golden有3条重复 | **低** | 重测章节, 非错误 |

### Borda 排名 TOP10 (v8.10, Tier3校准后)

| # | 书名 | Borda | 人工分级 | 关键维度 |
|---|------|-------|---------|----------|
| 1 | 全球变异 | 32.9 | S | signing#8, bt#4, webnovel#3 |
| 2 | 末世之深渊召唤师 | 44.8 | **A**(v8.8降级) | signing#1, webnovel#1 |
| 3 | 末世大回炉 | 47.0 | S | bt#6, webnovel#4 |
| 4 | 地球游戏场 | 48.2 | S | signing#4, diversity#3 |
| 5 | 黑暗血时代 | 52.1 | S | bt#5, signing#5 |
| 6 | 末日拼图游戏 | 53.8 | A | signing#1 |
| 7 | 第一序列 | 57.5 | S | bt#2 |
| 8 | 神秘尽头 | 59.8 | A | bt#1 |
| 9 | 末世魔神游戏 | 66.2 | A | diversity#1 |
| 10 | 从红月开始 | 67.7 | A | retention#2, bt#3 |

完整排名JSON: `data/reports/末世/synthesis/末世_borda_ranking.json`
TOPSIS排名: `data/reports/末世/synthesis/末世_topsis_ranking.json`

### 校准结果 (Tier3)

| 指标 | 纯人工(30章) | 混合(125章) |
|------|------------|------------|
| OLS slope | 0.762 | 0.463 |
| OLS intercept | — | 2.249 |
| R² | — | 0.319 |
| Pearson r | 0.473 | 0.565 |
| LOOCV r | — | 0.546 (p<0.001) |
| T1 Bias (intensity) | +1.60 | +1.78 |
| T2 Bias (intensity) | — | -2.59 |

校准文件: `data/reports/末世/calibration/tier3_calibration.json`

---

## 二、接下来干什么

### P0: 立即执行 (高优先级)

1. **扩大人工标注集**: 从30章扩展到至少50章, 覆盖7本S级书(每书7章), 使人工占比达40%+
2. **重新审视末日乐园S级**: diversity#33 + webnovel#27不支持S级, 建议降为B+
3. **统一T1采样率**: 对采样率<5%的书(末世超级商人0.9%、神秘尽头3.3%、蹉跎4.1%)补充采样
4. **发送外部AI审视指令**: 将 `data/reports/末世/external_ai_review_prompt_v8.10.md` 发送给DeepSeek/Kimi/Doubao, 收集三方独立评估

### P1: 近期执行

5. **引入独立AI交叉验证**: 用DeepSeek-R1对95章GLM数据重新评分, 比较AI间一致性
6. **报告双校准结果**: 同时展示纯人工(slope=0.762)和混合(slope=0.463)供对比
7. **补充外部口碑验证**: 对Borda TOP5补充豆瓣/起点/番茄数据
8. **长夜余火降级或标注**: 降为A级, 或保留S级标注"S*(作者加成)"

### P2: 中期优化

9. **考虑将diversity权重从0.4提升**: Entropy分析显示diversity区分度最高(0.309)
10. **修复index中的size_kb**: 末日蟑螂和狩魔手记size_kb与实际不符
11. **扩展到其他分类**: 仙侠/科幻/都市等已有入库数据

---

## 三、关键目录架构

```
d:\Code\xiaoshuo\
├── data/
│   ├── raw/novels/末世/                    # 33本原始txt
│   ├── raw/novel_index.json                # 小说索引(SSOT)
│   ├── golden/末世/
│   │   ├── human_golden.csv                # 30章人工golden标注
│   │   └── tier3/
│   │       ├── tier3_glm_scores.json       # 95章GLM校准评分
│   │       └── rescore_prompts/            # GLM评分指令(已使用, 存档)
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
│       │   ├── v8.8_final_ranking.md
│       │   └── v8.8_final_ranking.csv
│       └── 末世/
│           ├── audit_v8.10.md              # ★ v8.10独立审计报告
│           ├── external_ai_review_prompt_v8.10.md  # ★ 外部AI审视指令
│           ├── synthesis/
│           │   ├── 末世_borda_ranking.json  # Borda排名
│           │   ├── 末世_topsis_ranking.json # TOPSIS排名
│           │   ├── 末世_写作技法总纲.md
│           │   └── rhythm_benchmark.md
│           ├── calibration/
│           │   └── tier3_calibration.json  # Tier3校准结果
│           ├── writing_manuals/            # 逐章指令
│           └── full_audit_t1t2.json        # T1/T2全量审计
├── scripts/                                # ~20个核心脚本
│   ├── ai_annotate.py                      # Tier1标注核心
│   ├── calibrate_with_tier3.py             # Tier3校准
│   ├── gen_tier2_sampling.py               # Tier2采样
│   ├── loocv_calibrate.py                  # LOOCV校准
│   ├── merge_tier2_and_update.py           # T1+T2合并+Borda重跑
│   ├── recompute_borda.py                  # Borda加权重算
│   ├── save_snapshot_and_audit.py          # 快照+全量审计
│   ├── three_tier_eval.py                  # 三层评估主脚本
│   ├── _audit_v810.py                      # v8.10审计脚本(参考)
│   ├── quality_check.py / quality_check_tier2.py  # 质检
│   ├── start_model_safe.bat                # LLM启动
│   └── _archive/                           # 过时脚本归档(130+)
├── src/xiaoshuo/
│   └── pipeline/scoring/
│       ├── commercial_engine.py            # 商业评分引擎
│       ├── borda_ranker.py                 # Borda排名器
│       └── structure_matcher.py            # 结构匹配
├── config.yaml                             # 配置SSOT
├── _archive/                               # 根目录旧文件归档
└── NEW_SESSION_HANDOFF.md                  # 本文档
```

---

## 四、新会话验证步骤

```bash
cd d:\Code\xiaoshuo

# 1. 查看Borda排名
D:\miniconda3\envs\llm-shared\python.exe -c "import json; r=json.load(open('data/reports/末世/synthesis/末世_borda_ranking.json','r',encoding='utf-8')); [print(f'#{i+1} {x[\"book_name\"][:25]:<27} borda={x[\"total_borda\"]}') for i,x in enumerate(r[:10])]"

# 2. 查看校准结果
D:\miniconda3\envs\llm-shared\python.exe -c "import json; d=json.load(open('data/reports/末世/calibration/tier3_calibration.json','r',encoding='utf-8')); print(f'OLS slope={d[\"ols\"][\"intensity\"][\"slope\"]}, LOOCV r={d[\"loocv\"][\"intensity\"][\"r\"]}')"

# 3. 查看LLM合并数据统计
D:\miniconda3\envs\llm-shared\python.exe -c "import csv; from pathlib import Path; d=Path('data/processed/末世/scores'); t=sum(sum(1 for _ in open(f,'r',encoding='utf-8-sig'))-1 for f in d.glob('*_llm.csv')); print(f'Total LLM chapters: {t}')"

# 4. 重新运行审计 (可选)
D:\miniconda3\envs\llm-shared\python.exe scripts/_audit_v810.py
```

预期输出: Borda TOP1=全球变异(32.9), slope=0.463, LOOCV r=0.546, 5472章LLM数据。

---

## 五、注意事项

1. **np.corrcoef在Windows环境有DLL错误**: 使用手动Pearson公式替代, 见 `scripts/_audit_v810.py` 中的 `pearson_r()` 函数
2. **PowerShell无法输出中文**: 所有脚本输出改为写文件, 用 `read_file` 读取结果
3. **novel_index.json**: 是SSOT, `rhythm_csv` 字段必须正确指向rhythm目录中的文件名
4. **commercial_engine缓存**: `_load_all_llm_scores()` 有模块级缓存, 修改 `_llm.csv` 后需重启Python进程
5. **编码**: 所有JSON文件UTF-8无BOM, CSV文件UTF-8带BOM(Excel兼容)
6. **LLM服务**: 本地LLM已关闭, 如需重启用 `scripts/start_model_safe.bat`
7. **后端服务**: 端口8089, 正确启动方式: `D:\miniconda3\envs\llm-shared\python.exe -m xiaoshuo.api.server --port 8089` 从 `d:\Code\xiaoshuo` 启动
8. **v8.10审计风险**: 最核心风险是GLM自评循环论证(76% AI数据), 待外部AI审视反馈后决定优化方案
