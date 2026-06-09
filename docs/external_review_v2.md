# 外部AI审视指令 v2 — 番茄小说AI创作系统 v7.3 (修订版)

> 更新时间: 2026-06-07 · 基于 v1 反馈已修复 P0+P1 全部项
> v1→v2 变更摘要见末尾

---

## 一、项目目标

通过**量化分析爆火精品网文**，建立数据驱动的 8 维创作指导体系（渐进式披露），帮助**新人作者**产出高质量、高爆款潜力的网文。

| 阶段 | 维度 | 数据来源 |
|------|------|---------|
| 🟢准备期(开书前) | 题材选择 + 世界观 | 子类型分布 / 冲突类型统计 |
| 🟡规划期(动笔前) | 粗纲 + 人物 | 分段节奏基准 / VAD+弧型分布 |
| 🔵执行期(日更中) | 细纲 + 文笔 + 情节推动 | 钩子分布/打脸频率/波次分析 |
| 🔴审视期(完本后) | 反同质化 | KL散度+低频高价值机会 |

核心原则：每个建议背后有精品书数据支撑（标注置信度），仅 quality_gate 通过的精品书参与基准。

---

## 二、分析管线架构 (v2 修订版)

### 数据流

```
books/in/*.txt
  ↓ book_processor (独立模块, 不与 rhythm 合并)
    基础过滤: ≥200KB, ≥5章, 中文≥40%
    → data/raw/novels/ or books/review/
  ↓ rhythm_analyzer (独立模块)
    逐章30+指标 → CSV
  ↓ quality_gate v2 (双层关卡 + 三级状态)
    Gate A(形式): FAIL → move to review/
    Gate B(实质): QUARANTINE → 标记不移书
    已知精品: 永不 FAIL, 最差 QUARANTINE
    → quality_manifest.json (含 confidence 字段)
  ↓ genre_synthesizer (仅合成 PASS 精品书)
    拆书三件套 + Bayesian BMA 商业评分
    → rhythm_benchmark.md
  ↓ creative_bridge v2 (JSON+MD双输出, 8维渐进式披露)
    精确ID映射 + %分桶归一化 + rule_translator + 反同质化
    → creative_guidance.json / creative_guidance.md
```

### 模块设计概要

#### 模块1: book_processor — 入库基础过滤

**设计**: 第一道关卡，过滤形式不合格的文件。
**v2 变更**: 阈值全部从 config.yaml 读取，已知精品名单统一管理。

```python
passes_basic_filter(filepath):
    1. known_quality_list match → PASS
    2. size ≥ min_size_kb(200) → continue
    3. chapters ≥ min_chapters(5) → continue
    4. chinese_density ≥ 0.40 → continue
    5. pass → "待后续质量关卡验证"
```

#### 模块2: rhythm_analyzer + genre_synthesizer — 拆书+商业评分

**设计**: 将小说拆解为 30+ 量化指标，百分位排名+Bayesian BMA 融合商业评分。
**v2 变更**: 采用渐进式池子(`_read_commercial_score_progressive`)首轮即可输出商业评分。

```python
compute_commercial_score(rows):
    pool = get_firebook_pool()  # percentile pool
    # 3 core: 首章爽点 / 前3章钩子 / 前3章冲突
    # 7 bonus: 零钩子 / 打脸 / 多样性 / 反转 / 悬念 / 大爽 / 留存
    # sub-genre adaptive weights → overall score (0-100)
```

#### 模块3: quality_gate v2 — 双层品质关卡

**设计**: Gate A(形式检查→FAIL) + Gate B(实质检查→QUARANTINE)，三级状态 PASS/QUARANTINE/FAIL。
**v2 新增**: 已知精品保护(永不 FAIL)、渐进式池子(首轮可用)、quarantine_days(7天自动降级)。

```python
evaluate_book(txt_path, gate_cfg, gate_type="both"):
    known = _is_known_quality(book_name)
    Gate A: rhythm_exists? min_chapters? → FAIL (unless known→QUARANTINE)
    Gate B: zero_hook_streak? commercial_score? → QUARANTINE (soft demotion)
    → PASS / QUARANTINE / FAIL
```

#### 模块4: creative_bridge v2 — 8维创作指导

**设计**: 精确 CSV 映射 → 进度%分桶归一化 → rule_translator 翻译 → 8维渐进式披露。
**v2 新增**: JSON 输出(供 agents 消费)、KL 散度反同质化、置信度标注、相关/因果 disclaimer。

```python
analyze_for_guidance(genre):
    csv_map = _build_csv_map(genre)  # exact ID mapping
    for approved_book in manifest:
        rows = _load_rhythm_data(csv_map[stem])
        pct_buckets = _pct_buckets(rows)  # % normalization
    →
    8 dimensions:
      worldbuilding, rough_outline, chapter_outline,
      writing_style, character, genre_selection,
      plot_progression, anti_homogenization
```

---

## 三、穷举搜索发现：4模块能否达成目标？

### 能达成的部分

| 能力 | 支撑证据 |
|------|---------|
| 过滤明显废书（残缺/乱码） | book_processor 形式检查 ✅ |
| 识别节奏问题（零钩子/冲突断崖） | rhythm_analyzer + quality_gate ✅ |
| 提供量化对标基准 | genre_synthesizer 百分位排名 ✅ |
| 生成可操作的创作建议 | creative_bridge rule_translator ✅ |
| 防止基准库被污染 | quality_gate 双层关卡 ✅ |
| 标记统计不可信 | confidence 字段 + disclaimer ✅ |

### 当前无法达成的部分

| 短板 | 严重度 | 说明 |
|------|:---:|------|
| 样本量不足（n=10） | 🔴 | 百分位排名统计不稳定，Spearman r 不可信 |
| 正则漏检率 40-60% | 🔴 | 语境依赖爽点/钩子大量漏检 |
| 全部分析是相关性非因果 | 🟡 | 可能导致"模仿症状而非病因" |
| 创意/文采/立意无法量化 | 🟡 | 系统保下限不保上限 |
| JSON 输出尚未被 agents 消费 | 🟡 | 桥接代码未写（P0-2 产出数据，消费端未改造） |

### 可优化但非阻塞

| 优化项 | 优先级 |
|------|:---:|
| rhythm_analyzer 全量读入内存（超长小说风险） | P2 |
| Step0+Step1 分离导致 I/O 双倍 | P2(<1% 收益) |
| 爽点正则+LLM混合标注(10%采样) | P1(已规划) |

---

## 四、请外部 AI 审视 v2 版本的问题

### A组: 核心假设

A1. **"精品书的特征 = 好网文的标准"这个假设成立吗？**
    精品书是通过市场筛选的，但市场成功受平台推荐算法、发布时间、作者粉丝基础等多因素影响。分析结果是否可能"把运气当规律"？

A2. **10本书的百分位排名是否比"绝对阈值+专家经验"更危险？**
    当前已通过渐进式池子、置信度标注来缓解。外部评审是否认可这种保守策略？还是有更好的降风险方案？

A3. **如果新人严格按照 8 维指导写作，同质化风险多大？**
    我们已经加入了 KL 散度+低频建议的反同质化模块。这个设计的有效性如何评估？

### B组: 品质关卡

B1. **Gate A(形式→FAIL) + Gate B(实质→QUARANTINE) 的双层设计是否合理？**
    已知精品不受 Gate A 限制（降级到 QUARANTINE 而非 FAIL）。是否需要在 QUARANTINE 和 FAIL 之间再加一个"WARNING"级别？

B2. **7天 QUARANTINE 自动降级是否合理？**
    考虑到网文作者通常不是全职做这个项目，7天可能太短。建议值是多少？

B3. **渐进式池子的跨题材代理评分精度能接受吗？**
    当前首轮用节奏指标做 proxy scoring（`avg_pleasure*10 + avg_hook*20`）。这个公式是否合理？

### C组: creative_bridge 设计

C1. **8维渐进式披露是否真的降低了新人的认知负担？**
    虽然分层了，但每个阶段内部仍有大量数据。需要怎样的"摘要层"？

C2. **rule_translator 的 5 条规则是否覆盖面够？**
    当前翻译 hook_density/zero_hook_streak/dialogue_ratio/pleasure_intensity/conflict_density。是否需要更多？

C3. **JSON 输出供 agents 消费的 schema 是否合理？**
    当前 JSON 是完整 guidance dict，agents 需要哪几个字段？是否需要裁剪版"agents_only.json"？

### D组: 缺失

D1. **系统没有"用户反馈回路"** — 无法知道新人的作品是否真的变好了。如何设计？
D2. **没有 A/B 测试框架** — 无法验证哪个维度的指导最有效。是否需要？
D3. **LLM 爽点标注尚未实现** — P1 项仍在规划中。优先级是否应该提高到 P0？

### E组: 工程

E1. **rhythm_analyzer 对 2000+章小说的内存风险** — 是否需要在 v2 中强制加入截断？
E2. **8个维度全部生成会不会导致 creative_guidance.md 过于冗长** — 是否需要"快速版"（仅 P0 维度）？

---

## 五、v1→v2 变更摘要

| v1 反馈 | v2 实现 |
|---------|---------|
| `_get_book_csv_path`[:8]模糊匹配Bug | `_build_csv_map()` 精确 novel_index 映射 |
| creative_bridge↔agents桥接缺失 | JSON双输出 + 结构化 guidance dict |
| auto_demote 过于激进 | QUARANTINE三级状态 + 已知精品保护 |
| 品质关卡首轮空转 | 渐进式池子 + proxy scoring |
| 品质关卡不分层 | Gate A(形式→FAIL) + Gate B(实质→QUARANTINE) |
| 跨书混合分析不合理 | 进度%分桶归一化 `_pct_buckets()` |
| 指标→建议映射无效 | `_translate_to_rules()` 翻译层 |
| 无同质化防护 | KL散度+低频高价值 `_build_anti_homogenization()` |
| 无置信度标注 | confidence字段+每维度disclaimer |
| 8维平铺信息过载 | 渐进式披露(4阶段×2-3维)+全部概览表 |
| 分歧: Step合并 | **保持独立** (P2再评估,收益<1%) |
| 分歧: 首轮评分方案 | **渐进池+Bootstrap** (已实现) |
| 分歧: 3维选择 | **8维全量+渐进披露** (不删维度) |

---

## 六、工程指标

| 指标 | v1 | v2 |
|------|:---:|:---:|
| 分析模块数 | 8 | 8 |
| 品质关卡状态 | PASS/FAIL | PASS/QUARANTINE/FAIL |
| 创作指导维度 | 5→7 | **8**(含反同质化) |
| 报告输出格式 | Markdown | JSON + Markdown |
| 跨书归一化 | 绝对章节 | 进度%分桶 |
| 置信度标注 | 无 | low/medium/high |
| 首轮评分可用 | 否 | 是(渐进池) |
| 已知精品保护 | 无 | 永不FAIL |

---

*请逐条回答审视问题组 A-E，给出改进建议和优先级。*
