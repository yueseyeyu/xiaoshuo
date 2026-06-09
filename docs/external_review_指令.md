# 外部AI审视指令 — 番茄小说AI创作系统 v7.3 分析管线

> 生成时间: 2026-06-07 · 待审模块: 书籍过滤/拆书/商业评分/创作指导

---

## 一、项目目标

本项目通过**量化分析爆火精品网文**，建立数据驱动的创作指导体系，帮助**新人作者**在以下维度产出高质量、高爆款潜力的作品：

| 维度 | 指导内容 |
|------|---------|
| 题材选择 | 哪个子类型更容易爆？看精品书的子类型分布 |
| 世界观 | 核心冲突类型统计 → 指导世界规则设计 |
| 粗纲 | 分段节奏基准（每段 hook/conflict/爽点目标值） |
| 细纲 | 钩子类型分布 + 打脸频率 + 零钩子红线 |
| 人物 | 人物弧线分布 + VAD 情感指标 + 羁绊爽点 |
| 文笔 | 对话比基准 + 可读性 + 章节变异度 |
| 情节推动 | 冲突升级曲线 + 转折点检测 + 爽点间隔 |

核心原则：**所有建议必须有精品书量化数据支撑，不可凭空建议。**
仅使用 quality_gate 通过的精品书数据，防止非精品污染基准。

---

## 二、分析管线架构

### 数据流（5步自动化）

```
books/in/*.txt (手动下载放入)
  ↓
Step 0: book_processor.py     基础过滤（大小/章节/中文密度）
  ├─ 通过 → data/raw/novels/
  └─ 不通过 → books/review/ (人工审查)
  ↓
Step 1: rhythm_analyzer.py    逐章30+指标 → CSV
  ↓
Step 2: quality_gate.py       品质关卡（节奏+商业分）
  ├─ PASS → quality_manifest.json (精品白名单)
  └─ FAIL → 移回 books/review/
  ↓
Step 3: genre_synthesizer.py  仅合成白名单中的精品书
      拆书三件套 + 商业评分 → rhythm_benchmark.md
  ↓
Step 4: creative_bridge.py    分析数据→7维创作指导
      → creative_guidance.md (世界观/粗纲/细纲/文笔/人物/题材/情节)
```

### 模块职责

#### 模块1: book_processor.py — 入库基础过滤

**设计意图**: 第一道关卡，过滤明显不合格的文件（残缺/乱码/无章节组织）。

**过滤逻辑**:
1. 已知精品名单匹配（18本书，config 可配）
2. 文件大小 ≥ 200KB
3. 章节结构 ≥ 5章（前10000字内）
4. 中文密度 ≥ 40%

**关键代码** (`passes_basic_filter()`, 约40行):
```python
def passes_basic_filter(filepath: Path) -> tuple:
    cfg = _load_filter_config()
    # 1. known quality list match
    for qname in cfg["known_quality_list"]:
        if qname in filename or qname in text_head[:500]:
            return True, f"已知精品: {qname}", qname
    # 2-4. size / chapters / chinese density checks
    if size_kb < cfg["min_size_kb"]: return False, ...
    if chapter_count < cfg["min_chapters"]: return False, ...
    if density < cfg["min_chinese_density"]: return False, ...
    # 5. pass → 标记"待验证"
    return True, f"通过基础过滤, 待后续质量关卡验证", filename
```

**审视要点**:
- 基础过滤仅检查"形式完整性"，不评估"内容品质"
- 通过但不在已知名单的书 → 带"待验证"标记进入下一关
- 阈值全部从 `config.yaml` 读取

---

#### 模块2: rhythm_analyzer.py + genre_synthesizer.py — 拆书 & 商业评分

**设计意图**: 将小说"拆解"为量化指标，建立跨书可比的度量体系。

**rhythm_analyzer 核心指标** (逐章30+维):
- 9种爽点密度（打脸/突破/碾压/绝地反击/扮猪吃虎/羁绊/认知/牺牲/生理）
- 4种钩子类型（悬念/反转/情绪炸弹/信息投放）
- 5种冲突（战斗/心理/道德/环境/社会）
- 情绪正负密度 + 可读性 + 节奏类型 + 章节变异度

**genre_synthesizer 核心评分**:
- 商业可行性评分（100分制）：首章爽点 + 前3章钩子 + 前3章冲突 + 打脸频率 + 爽点多样性 + 反转/悬念/大爽频率 + 读者留存力
- 百分位排名：每本书的每个指标 vs 同题材其他书的分布
- Bayesian BMA 融合：规则指标权重（Pearson r²）+ LLM评分余量
- LOOCV 验证：Spearman r 对标真实完读率

**关键评分代码** (`compute_commercial_score()`, 180行):
```python
def compute_commercial_score(rows):
    pool = get_firebook_pool()  # 同题材全部书统计分布
    
    # 3维核心评分
    scores["首章爽点"] = percentile_score(blended_intensity, pool, "intensity")
    scores["前3章钩子"] = percentile_score(opening_hook, pool, "hook_density")
    scores["前3章冲突"] = percentile_score(opening_conflict, pool, "conflict")
    
    # 加权聚合（子类型适配）
    overall = sign * gw["sign"] + retain * gw["retain"] + bonus * gw["bonus"]
    grade = "🔥 高概率签约" if overall >= 70 else ...
```

**审视要点**:
- 爽点/钩子/冲突全部基于关键词正则匹配 → **覆盖率问题**（语境依赖型爽点可能漏检）
- 商业评分基于同题材百分位排名 → **样本量敏感**（n<10时排名不稳定）
- LOOCV Spearman r 目标 >0.6 → 当前 ~0.66（可接受）

---

#### 模块3: quality_gate.py — 分析后品质关卡

**设计意图**: 第二道关卡。分析完成后，将不达标的书退回 `books/review/`，确保只有精品书参与基准库生成。

**检查项**（4项，config 可配）:
1. 节奏分析数据存在
2. 章节数 ≥ 10
3. 零钩子连续 ≤ 5章
4. 商业评分 ≥ 30分（首轮可能不可用，次轮生效）

**关键代码** (`evaluate_book()`, 40行):
```python
def evaluate_book(txt_path, gate_cfg):
    # Check 1: rhythm exists
    # Check 2: chapter count
    # Check 3: zero-hook streak
    # Check 4: commercial score (best effort)
    if any_fail:
        return "FAIL", details  # → demote_book() → books/review/
    return "PASS", details  # → quality_manifest.json
```

**审视要点**:
- 品质关卡在 genre_synthesizer 之前运行 → 确保基准库不被污染
- `auto_demote=true` 时自动移书（可 dry-run 预览）
- 退回到 review/ 的书需人工审查决定去留
- 首轮仅能做 rhythm 检查（商业评分需次轮才有）

---

#### 模块4: creative_bridge.py — 分析→创作桥接（🆕）

**设计意图**: 将分析管线产出的量化数据翻译为新人作者可读、可操作的7维创作指导。

**7个维度**:
1. **世界观**: 核心冲突类型分布 + Top3精品榜 + 爽点类型高频统计
2. **粗纲**: 5段式结构每段 hook/conflict/pleasure/dialogue 基准表
3. **细纲**: 钩子类型%分布 + 爽点层级分布 + 打脸频率 + 零钩子红线 + 冲突升级曲线
4. **文笔**: 对话比均值+范围 + 可读性均值+范围 + 章节变异度
5. **人物**: 弧型分布 + VAD情感起点/终点/摆动 + 羁绊爽点占比
6. **题材选择**: 子类型分布 + 跨题材对比 + 最佳对标书籍
7. **情节推动**: 波次分析 + 转折点检测 + 大爽点间隔

**关键代码** (`analyze_for_guidance()`, 120行):
```python
def analyze_for_guidance(genre="末世"):
    manifest = _load_manifest()  # 仅精品书
    for stem in approved_stems:
        rows = _load_rhythm_data(csv_name)
        # per-book: hooks, conflicts, pleasures, VAD arc
        # per-segment: pooled benchmarks
    # Build 7-dim guidance dict
    guidance["worldbuilding"] = _build_worldbuilding(...)
    guidance["rough_outline"] = _build_rough_outline(...)
    guidance["chapter_outline"] = _build_chapter_outline(...)
    guidance["writing_style"] = _build_writing_style(...)
    guidance["character"] = _build_character(...)
    guidance["genre_selection"] = _build_genre_selection(...)
    guidance["plot_progression"] = _build_plot_progression(...)
    return guidance
```

**审视要点**:
- 数据源：仅 `quality_manifest.json` 中的精品书
- 输出格式：Markdown，方便人类阅读
- **关键缺失**: creative_guidance.md 生成后无程序化消费——agents 不会自动引用它
- 跨书混合分析时 `all_rows.extend()` 丢失单书定位

---

## 三、请外部 AI 审视以下问题

### 问题组 A: 整体架构合理性

A1. **这个5步管线（过滤→拆书→关卡→评分→创作指导）是否过度工程化**？
    是否存在可以合并的步骤？是否存在冗余分析？

A2. **新人作者真的需要7维指导吗**？
    如果只能保留3个最重要的维度，你会选哪3个？为什么？

A3. **"量化指标→创作建议"的映射是否有效**？
    例如"钩子密度0.25"对新人作者意味着什么？需要怎样的翻译层？

### 问题组 B: 评分体系有效性

B1. **基于关键词正则的爽点/钩子检测覆盖率是否足够**？
    语境依赖型爽点（如对话中的讽刺、内心独白的反转）会漏检。漏检率估计多少？可接受的漏检率是多少？

B2. **商业评分公式的权重是否合理**？
    当前权重是通过 Grid Search + Spearman r 校准的（r≈0.66），但仅基于10本末世书。这个样本量是否足够信任权重分配？

B3. **百分位排名 vs 绝对阈值**：哪个更适合指导新人？
    百分位排名的问题：如果所有书都很差，第50百分位也是差书。绝对阈值的问题：不同类型/篇幅的书标准不同。

### 问题组 C: 品质关卡设计

C1. **quality_gate 的4项检查是否充分**？
    是否需要加入"内容创新度"（检测是否与已有精品书过度雷同）？

C2. **两遍策略**（首轮仅rhythm检查，次轮加商业评分）是否合理？
    有没有更好的方案让首轮也能用商业评分？

C3. **退回机制是否过于激进**？
    `auto_demote=true` 直接移书。如果阈值设置不当，可能误伤好书。是否需要"软降级"（标记但不移书）？

### 问题组 D: creative_bridge 设计

D1. **7个维度中哪些有因果证据，哪些只是相关性**？
    例如"对话比例0.25"和"爆款"之间是因果关系还是相关关系？

D2. **`_get_book_csv_path` 使用 `book_stem[:8]` 做模糊匹配**。
    两本书名字前8字符相同时会错误匹配。如何改进？

D3. **跨书混合分析的合理性**：
    `all_rows.extend()` 将所有书的章节混在一起。当分析"冲突升级曲线"时，不同长度/节奏的书混在一起是否合理？

### 问题组 E: 缺失与盲点

E1. **当前体系完全忽略了"文采/立意/创新"等难以量化的维度**。
    这些维度对爆款的重要性多大？如何在量化体系中体现？

E2. **10本末世书作为基准库的样本量是否足够**？
    10本书的排名分布（percentile）统计意义有限。最少需要多少本？

E3. **如何防止新人过度依赖基准导致同质化**？
    如果所有人都按"爆款基准"写，市场上会出现大量同质化作品。系统应该加入怎样的"差异化提示"？

### 问题组 F: 技术实现

F1. **creative_bridge 和 agents 之间的桥接缺口**：
    `creative_guidance.md` 是文本文件，不会被 `world_builder.py` 或 `outline_builder.py` 程序化读取。
    应该如何建立从分析结果到创作端的自动反馈回路？

F2. **rhythm_analyzer 对超长小说（2000+章）的处理**：
    是否全部读入内存？是否有截断策略？内存使用峰值是多少？

F3. **配置驱动 vs 硬编码的平衡**：
    哪些参数应该永远在 config 中？哪些可以作为合理的硬编码默认值？

---

## 四、关键代码样本（供审视）

### book_processor 基础过滤逻辑
```python
# analysis/book_processor.py:94-122
def passes_basic_filter(filepath: Path) -> tuple:
    """Basic quality filter. Reads thresholds from config.yaml."""
    filename = filepath.stem
    text_head = filepath.read_text(encoding='utf-8', errors='replace')[:10000]
    cfg = _load_filter_config()
    # 1. Known quality list
    quality_list = cfg.get("known_quality_list", [])
    for qname in quality_list:
        if qname in filename or qname in text_head[:500]:
            return True, f"已知精品: {qname}", qname
    # 2-4. Size / Chapter / Density
    if size_kb < cfg["min_size_kb"]: return False, ...
    if chapter_count < cfg["min_chapters"]: return False, ...
    if density < cfg["min_chinese_density"]: return False, ...
    # 5. Pass → marked as "pending verification"
    return True, f"通过基础过滤, 待后续质量关卡验证", filename
```

### quality_gate 品质关卡
```python
# analysis/quality_gate.py:157-201
def evaluate_book(txt_path, gate_cfg):
    # Check 1: rhythm data exists
    # Check 2: chapters >= min_rhythm_chapters (10)
    # Check 3: zero_hook_streak <= max (5)
    # Check 4: commercial_score >= min (30, best-effort)
    if any_fail:
        return "FAIL"  # → demote_book() → books/review/
    return "PASS"  # → quality_manifest.json
```

### genre_synthesizer 商业评分核心
```python
# analysis/genre_synthesizer.py:390-573
def compute_commercial_score(rows):
    pool = get_firebook_pool()  # percentile pool from all same-genre books
    # 3 core metrics → percentile scores
    scores["首章爽点"] = percentile_score(blended_intensity, pool, "intensity")
    scores["前3章钩子"] = percentile_score(opening_hook, pool, "hook_density")
    scores["前3章冲突"] = percentile_score(opening_conflict, pool, "conflict")
    # 7 bonus metrics
    scores["零钩子连续"] = 100 if zero_hook_streak <= 2 else max(0, 100 - streak*30)
    scores["打脸频率"] = ...  # sub-genre adaptive
    scores["爽点多样性"] = percentile_score(shannon_div, pool, "diversity")
    scores["读者留存力"] = percentile_score(llm_avg_retention, pool, "retention")
    # Weighted aggregation (sub-genre specific weights)
    overall = sign*gw["sign"] + retain*gw["retain"] + bonus*gw["bonus"]
    return {"overall": overall, "grade": _grade(overall), "scores": scores}
```

---

## 五、工程指标

| 指标 | 数值 |
|------|------|
| 分析管线模块数 | 8个 Python 文件 |
| 总代码行数 | ~4000 lines (analysis/) |
| 逐章指标维度 | 30+ |
| 精品书基准库 | 10本末世 (目标18本) |
| 品质关卡检查项 | 4项（3项必检+1项可选） |
| 创作指导维度 | 7维（刚从5维升级） |
| 全管线运行时间 | ~10分钟（10本书，无LLM） |
| LOOCV Spearman r | 0.66 (vs 真实完读率) |

---

*请逐条回答审视问题组 A-F，给出改进建议和优先级。*
