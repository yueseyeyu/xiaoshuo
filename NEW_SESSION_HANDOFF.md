# 新会话交接文档

> 生成时间: 2026-07-22 (B1-CLOSE-REPAIR + ADR-014/B2a-DECISION-LANDING)
> 生成者: CatPaw (项目总负责人角色)

---

## 一、项目当前状态总览

### 当前架构阶段: B1 Implementation Completed / Close-Error Repair Passed / SSOT Closed / B2a Decision Approved / B2a Plan Amendment Required / B2 Implementation Not Started

### 综合可信度: 72/100 (DeepSeek最终评审)

```
v8.10: 48/100 → v8.15(过期数据): 68/100 → v8.15(新鲜数据): 72/100
```

| 维度 | 评分 | 说明 |
|------|------|------|
| 评分确定性 | 9.5/10 | temp=0.0, within-session 3/3一致(std=0) |
| 统计验证 | 7/10 | Bootstrap CI + 5-fold CV + LOOCV |
| 过拟合控制 | 8/10 | LOOCV delta=+0.066 |
| 校准方法 | 7.5/10 | OLS slope显著(CI [0.118,0.583]) |
| 金标准可靠性 | 3.5/10 | 单一标注者, 无IAA |
| 样本量 | 4/10 | N=47, CI宽 |

### 已完成管线 (12步全部完成 ✅)

| 步骤 | 状态 | 说明 |
|------|------|------|
| 1-4. Rhythm+T1+T2+合并 | ✅ 33本/5472章 | 10%分层采样 |
| 5. Tier3校准 | ✅ 47章人工golden | v8.15: OLS(3.466+0.361x) |
| 6. Commercial+Borda | ✅ 33/33本 | Spearman r=0.917 |
| 7-8. v8.10审计+v8.11 | ✅ | IPW+WLS+分级 |
| 9. DeepSeek交叉验证 | ✅ 7本95章 | DS-GLM r=0.415 |
| 10-11. v8.12校准+v8.13Schema | ✅ | 47章+WLS+schema验证 |
| 12. v8.14 Reference Scoring | ✅ 搁置 | 三方AI一致否决 |
| **13. v8.15 temp=0.0+OLS+CI** | **✅** | **本轮完成** |

---

## 二、v8.15 本轮完成清单 (git 14个commit)

### Commit历史

```
c54e21f: v8.12-v8.14全部数据保护 (74文件/14852行)
2e1eb74: P0 fixes: WLS calibration + no-overwrite + golden_set cleanup
4f979bc: P1-2: remove dead code (LLMLingua + quantile_map)
e13df93: P1-3: run-to-run variance (temp=0.0, 3/3 identical, std=0)
257a355: P0: temperature=0.0 default + OLS(v8.15) calibration
ad6343f: v8.15 fresh data: OLS(3.466+0.361x) + Bootstrap CI + k-fold CV
e5efbce: v8.15: LOOCV + scoring metadata recording + final review prompt v2
c79ae27: v8.15: seed=42 fix + DS review(72/100) + score discretization finding
23af6c7: v8.15 session complete: NEW_SESSION_HANDOFF.md updated + 72/100 credibility
8d45795: v8.15: IAA annotation tool (20 chapters, 5 books, HTML+TXT)
d6acfc6: v8.15: IAA tool v2 (reuse annotate_tool, S10+A7+B3=20ch, 7 books)
fa2698c: v8.15: IAA tool v3 (isolated storage, annotator ID, no score leaking, safe export)
da18bda: v8.15: fix IAA tool bugs (compareBox no-op, scores display, retest disabled, P1/P2 hidden, counts fixed)
cead657: v8.15: IAA tool title fix + all bugs verified working in browser
```

### 代码修改

| 文件 | 修改内容 |
|------|---------|
| `src/xiaoshuo/pipeline/llm_batch_score.py` | temperature默认0.1→0.0; OLS替代WLS; 不覆盖原始值(新增calibrated列); 删除LLMLingua; 删除quantile_map; 新增评分元数据JSON |
| `data/processed/末世/scores/golden_set.json` | 30条/3本书→47条/9本书 |
| `data/reports/末世/calibration/ols_calibration_v815.json` | 新OLS参数(3.466+0.361x)+完整元数据 |
| `scripts/start_model_safe.bat` | v17: 新增--seed 42修复跨session非确定性 |

### 新增脚本

| 脚本 | 用途 |
|------|------|
| `scripts/v815_run_to_run_variance.py` | 3次运行方差实验(temp=0.0) |
| `scripts/v815_verify_full_47.py` | 47章全量重跑(验证数据新鲜性) |
| `scripts/v815_bootstrap_and_cv.py` | Bootstrap CI + 5-fold CV |
| `scripts/v815_loocv.py` | LOOCV(Leave-One-Out CV) |
| `scripts/v815_verify_data_source.py` | 5章快速验证(数据源确认) |

---

## 三、v8.15 核心发现

### 3.1 temperature=0.0消除方差

| 指标 | temp=0.1(旧) | temp=0.0(新) | 改善 |
|------|------------|------------|------|
| run-to-run std | 0.955 | **0.000** | 完全消除 |
| Bias_I | +0.904 | +0.096 | -89% |
| MAE_I | 1.862 | 1.755 | -6% |
| r_I | 0.381 | 0.410 | +8% |

### 3.2 Bootstrap CI (新鲜数据, 1000次重采样)

| 指标 | 点估计 | 95% CI | 显著？ |
|------|--------|--------|--------|
| Bias_I | +0.096 | [-0.574, +0.777] | **❌ 不显著(含0)** |
| r_I | 0.410 | [0.139, 0.635] | ✅ 显著 |
| slope_I | 0.361 | [0.118, 0.583] | ✅ 显著(不含0不含1) |
| OLS MAE_I | 1.485 | [1.124, 1.807] | — |

### 3.3 LOOCV vs 5-fold CV

| 指标 | 5-fold CV | LOOCV | 说明 |
|------|----------|-------|------|
| MAE_I | 1.550 ± 0.322 | 1.552 | 高度一致 |
| 过拟合delta | +0.065 | +0.066 | 轻微,可接受 |
| slope range | 0.318-0.432 | 0.328-0.408 | LOOCV更窄 |

### 3.4 跨session非确定性

- **within-session**: 3/3完全相同(temp=0.0, std=0) ✅
- **cross-session**: 只有13/47章节匹配(28%) ❌
- **根因**: GPU浮点非确定性(flash-attn tiling + 无--seed)
- **修复**: 已加`--seed 42`, 下次重启生效. 如仍无效, 尝试`--flash-attn off`

### 3.5 LLM分数离散化(DeepSeek发现)

- LLM intensity: 9个唯一值(全是整数2-10)
- 人工 intensity: 15个唯一值(含0.5分)
- **temp=0.0+greedy倾向输出整数**, OLS可拉伸分布但无法恢复0.5粒度

---

## 四、三方AI评审历史

| 轮次 | DeepSeek | 豆包 | GLM | 最佳 |
|------|----------|------|-----|------|
| v8.14 | 48/100 | 低 | — | DeepSeek(5-fold CV) |
| v8.15-temp | 68/100 | — | — | DeepSeek(prev_context发现) |
| v8.15-bootstrap(过期) | 68/100 | 63/100 | 58/100(数据源错误) | DeepSeek |
| v8.15-bootstrap(新鲜) | **72/100** | — | — | DeepSeek(数值验证+离散化发现) |

### 三方AI各自特点

| AI | 强项 | 弱项 |
|----|------|------|
| DeepSeek | 独立计算验证(5-fold CV, Bootstrap), 新洞察(离散化) | 有时过于自信(Q2两轮判断不同) |
| 豆包 | 代码核查(唯一正确验证v8.14温度), 数学洞察(OLS Bias=0是数学必然) | 不做计算验证 |
| GLM | OLS vs WLS对比, 文献引用(Thinking Machines Lab) | 两轮都搞混temperature变量 |

---

## 五、当前OLS校准参数

```json
// data/reports/末世/calibration/ols_calibration_v815.json
{
  "intensity":  { "intercept": 3.466, "slope": 0.361 },
  "retention":  { "intercept": 4.905, "slope": 0.261 },
  "metadata": {
    "source": "v8.15_verify_full_47.json (temp=0.0+prev_context, fresh)",
    "date": "2026-07-14",
    "n_human": 47
  }
}
```

**已废弃**:
- WLS v8.12: intercept=1.928, slope=0.496 (GLM数据Bias方向相反)
- OLS v8.14: intercept=3.062, slope=0.379 (只有13/47匹配当前模型)

---

## 六、待解决瓶颈 (无法通过代码解决)

| 瓶颈 | 扣分 | 解决方案 | 需要什么 |
|------|------|---------|---------|
| 单一标注者 | -15分 | 朋友帮忙标注20章, 计算ICC | 朋友2-3小时 |
| N=47小样本 | -10分 | 扩充到100章 | 人工标注5-10小时 |

### 朋友标注方案 (20章, ✅ 工具已就绪)

**状态**: IAA标注工具已生成并浏览器验证通过, 可直接发给朋友

**工具文件**: `data/golden/末世/tier3/iaa_annotation_tool.html`

**安全隔离设计**:
1. localStorage key: `annotations_iaa_friend` (不冲突)
2. 导出文件名: `friend_annotations.csv` (不覆盖用户数据)
3. 章节数据: 去除所有human/llm/glm分数 (防锚定偏差)
4. CSV含annotator列 (标识标注者)
5. compare box已禁用 (不泄露已有分数)
6. retest功能已禁用 (不会弹出错测章节)

**选章分布**: S级10章(5本) + A级7章(废土崛起) + B级3章(末日蟑螂) = 20章

**每章工时**: 5-10分钟(读章节文本+打2个分)

**总计**: 100-200分钟 = 1.7-3.3小时

**产出**: ICC(Intraclass Correlation Coefficient) + Bland-Altman图

**意义**: 
- ICC > 0.7 → golden set可靠, 可信度+10-15分
- ICC < 0.5 → 标注标准不清, 需要重定义rubric
- 这是DeepSeek和豆包一致认为的"唯一能再提升可信度的路径"

**朋友完成后**: 将CSV放到 `data/golden/末世/tier3/friend_annotations.csv`, 运行ICC计算

---

## 七、下一步优先级

### 架构批次

```
下一阶段: 创建并审查 B2a 实现计划 → 批准前不实现 B2a
    ↓
B2a 实现 (经批准后): TransitionOperationContext + REVISION_REQUIRED→DRAFTING + RECOVERY_REQUIRED→retry + TASK_TRANSITIONED Audit
    ↓
B2b (独立计划/批准): AuthorDecision 用例 + 角色 ArtifactRef 合同 + artifact 写入入口
    ↓
B3: 查询/history → B4: HTTP/API (G05 阻塞)
```

ADR-014 B2a D01～D05 已裁决（Approved with Amendments）。B2a 已获合同裁决但尚未实现；B2b、B3、B4 未获授权。

### 数据管线批次

```
P0 (工具已就绪): 发IAA工具给朋友 → 朋友标注20章 → 计算ICC → 验证golden set地基
    ↓
P1 (需人工): 扩充golden set 47→100章 → 缩窄CI → 提升校准稳定性
    ↓
P1 (需重启服务器): 验证--seed 42是否改善跨session匹配率
    ↓
P2 (可选): 测试temp=0.05改善离散化(9个唯一分→更多粒度)
    ↓
P3 (可选): 拆分llm_batch_score.py(1539行→3模块)
```

---

## 八、验证步骤

```bash
cd d:\Code\xiaoshuo

# 1. 验证temperature默认值
$env:PYTHONUTF8=1
D:\miniconda3\envs\llm-shared\python.exe -c "import inspect; from xiaoshuo.pipeline.llm_batch_score import llm_score_rubric; print('temperature:', inspect.signature(llm_score_rubric).parameters['temperature'].default)"

# 2. 查看OLS校准参数
D:\miniconda3\envs\llm-shared\python.exe -c "import json; d=json.load(open('data/reports/末世/calibration/ols_calibration_v815.json',encoding='utf-8')); print(f'OLS: {d[\"intensity\"][\"intercept\"]}+{d[\"intensity\"][\"slope\"]}x')"

# 3. 查看新鲜数据指标
D:\miniconda3\envs\llm-shared\python.exe -c "import json; d=json.load(open('data/reports/末世/v8.15_verify_full_47.json',encoding='utf-8')); print(f'Bias={d[\"intensity\"][\"bias\"]}, MAE={d[\"intensity\"][\"mae\"]}, r={d[\"intensity\"][\"r\"]}')"

# 4. 查看Bootstrap CI
D:\miniconda3\envs\llm-shared\python.exe -c "import json; d=json.load(open('data/reports/末世/v8.15_bootstrap_cv_results.json',encoding='utf-8')); b=d['baseline']['intensity']; print(f'Bias CI: [{b[\"bias_ci\"][0]}, {b[\"bias_ci\"][1]}]')"
```

预期输出: temperature=0.0, OLS=3.466+0.361x, Bias=0.096, BiasCI=[-0.574, 0.777]

---

## 九、注意事项

1. **v8.14数据已过期**: `v8.14_reference_scoring_data.json`只有13/47章节匹配当前模型, 不应再用于统计分析
2. **OLS参数会随session变**: 模型服务器重启后OLS可能需要重新拟合, 已有元数据记录追溯
3. **temperature=0.0**: 生产环境默认值已改为0.0, 所有新评分自动使用
4. **golden_set.json**: 已从30条/3本书清洗为47条/9本书, 与CSV一致
5. **校准不覆盖原始值**: 新增`llm_intensity_calibrated`列, 原始`llm_intensity`保留
6. **--seed 42**: `start_model_safe.bat` v17已添加, 下次重启生效
7. **9个唯一分**: temp=0.0+greedy导致LLM只输出整数, 考虑temp=0.05改善(但引入方差)
8. **后端服务**: 端口8089, `D:\miniconda3\envs\llm-shared\python.exe -m xiaoshuo.api.server --port 8089`
9. **硬件**: RTX 5060 8GB + 32GB RAM, Qwen3.5-9B Q4_K_M
10. **十阶段愿景完成度**: Part A 90% → Part B 70% → Part C 60% → Part D 75% → Part E 20%, 整体约50%
11. **B1 Close-Error Repair**: create_task.py 修复 close() 异常链——原始异常保留、close 异常作为 __cause__；3 项新增测试通过，15 项 B1 测试全部通过，296 项回归测试全部通过
12. **ADR-014**: B2a Transition 投递边界、无 AuthorDecision 安全迁移与 ArtifactRef 审计合同（Approved with Amendments）；D01～D05 全部裁决落盘

## C5-PIPELINE-FITNESS-P0-PROVENANCE-SSOT-CLOSEOUT-1 当前权威追加

本节仅记录本批 P0 Provenance SSOT 收尾事实，既有 v8.15 历史保持不变。

- 当前状态：`P0 Provenance code accepted / SSOT Closure Completed / Offline Deterministic Pipeline Evaluation Not Authorized`。
- 计划：`D:\Code\yeyu-ai\xiaoshuo\docs\plans\2026-08-c5-pipeline-fitness-p0-provenance.md`。
- 005–007 为设计工件，008–012 为实现及修正工件；最终 012 定向测试为 `40 passed in 0.88s`。
- 三层 identity、genre/profile transition、旧 artifact fail-closed、two-pass batch/envelope hash、ProjectRegistry unknown-project deny、capability deny-first 和 zero-call/zero-write 均已记录。
- 完整回归、Ruff、mypy、实际 registry backing、完整传递 census、legacy 生产迁移、管线质量、模型质量和商业效果仍未证明。
- 下一阶段仅为另行授权的 offline deterministic pipeline evaluation；不授权 C5/B4、服务、API、模型、前端或生产执行。
- 013 证据：`D:\tmp\yeyu-ai-a3\pipeline-fitness-p0-provenance-ssot-close\20260810-000001-013`。

精确下一步：等待 Codex 独立复核本批 SSOT 与 013 证据；复核前保持停止。
## C5-P1-A-SSOT-CLOSEOUT-1

Current status: `P1-A CODE REVIEW: ACCEPTED / No Code Changes Required / P1-A SSOT: CLOSED / P1-AE EVALUATION: NOT AUTHORIZED`

- P1-A design acceptance: 034; implementation and corrective history: 028–046.
- Final run: `20260810-000001-046`; evidence: `D:\tmp\yeyu-ai-a3\pipeline-fitness-offline-deterministic-evaluation-corrective\20260810-000001-046`.
- Final directed result: `189 passed / 0 failed / 0 errors / 0 skipped`.
- Final P1-A source SHA-256: `evaluation_contracts.py=e486df8b91cf239c62e60d88c4097fb488eef2076d8f84a189163812b4976a5d`; `offline_evaluation.py=6a6fab5b0ea90213164820a7b14e7ecae6faba7fd2b87b9a8f3aef9d758e6680`; `test_offline_deterministic_evaluation.py=126f3e3dbb9eb4409a5f9e8752a0b66209b7a32bb38b001a87c78dc79005b990`.
- P0 `provenance.py` SHA remains `bbb444616b1be4a099553f0604722ebb76aa692191961a8fe2ecb971e5e79a5a`.
- The authoritative 045 `SHA256SUMS.txt` SHA is `6149ef36c11fc93d3eb09f0e7c60d29b2381f8ef3eeb1e396f0990afd8bac0bc`; the old `e51df2...` value is not authoritative.
- P1-A proves only bounded infrastructure structure, provenance, isolation, determinism and failure-evidence boundaries. Model quality, publication quality, reader quality, commercial effect, production pipeline and P1-AE remain `NOT MEASURED`.
- P1-AE requires a new Codex independent design, Luna read-only review, exact whitelist and explicit authorization. Do not start it from this closeout.
- This closeout does not modify source, tests, design artifacts, config, Canon, SQLite, schema/migration, ADR, AI_PROTOCOL.md, assets/canon, .codebuddy or production data.
