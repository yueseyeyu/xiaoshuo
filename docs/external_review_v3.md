# 外部AI审视指令 v3 — 番茄小说 v7.3 全管线深度审查

> 日期: 2026-06-07 · 范围: 4模块完整设计+代码实现
> 前序: v1(6组问题) → v2(5组,已P0+P1修复) → v3(4模块技术审计)

---

## 项目目标重申

通过量化分析爆火精品网文，建立 8 维渐进式披露创作指导体系，帮助新人作者产出高质量网文。

---

## 一、模块1: book_processor — 入库基础过滤

### 设计

第一道防线。4 层检查 → PASS(入库) / FAIL(退回 `books/review/`)。

```
passes_basic_filter(filepath):
  1. known_quality_list match → PASS
  2. size ≥ 200KB
  3. chapters ≥ 5
  4. chinese_density ≥ 40%
```

### 实现代码

```python
# analysis/book_processor.py:110-135 (精简)
def passes_basic_filter(filepath: Path) -> tuple:
    filename = filepath.stem
    text_head = filepath.read_text(encoding='utf-8', errors='replace')[:10000]
    cfg = _load_filter_config()

    # 1. Known quality list (author-confirmed)
    quality_list = cfg.get("known_quality_list", [])
    for qname in quality_list:
        if qname in filename or qname in text_head[:500]:
            return True, f"已知精品: {qname}", qname

    # 2. Size check
    size_kb = filepath.stat().st_size // 1024
    if size_kb < cfg.get("min_size_kb", 200):
        return False, f"文件太小 ({size_kb}KB < {min_size}KB)", filename

    # 3. Chapter structure check
    chapter_count = len(re.findall(
        r'第[零一二三四五六七八九十百千0-9]+章', text_head))
    if chapter_count < cfg.get("min_chapters", 5):
        return False, f"章节不足 (仅{chapter_count}章, 需≥{min_ch})"

    # 4. Content density
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text_head))
    density = chinese_chars / max(total_chars, 1)
    if density < cfg.get("min_chinese_density", 0.40):
        return False, f"文字密度过低 ({density:.1%})"

    # 5. Pass → marked pending downstream verification
    return True, f"通过基础过滤, 待后续质量关卡验证"
```

### 审视问题

**Q1.1**: `第[零一二三四五六七八九十百千0-9]+章` 正则能否覆盖所有网文章节格式？例如"序章""楔子""番外""卷X 第Y章"——这些格式的漏检会造成章数误判。

**Q1.2**: 第5步"通过基础过滤但非已知精品"的书直接PASS——是否过于宽松？作者可能放了一本"文件名像精品但内容不行的书"。是否应在通过时加 `quality: "unverified"` 标记？

**Q1.3**: 编码检测(`detect_encoding`)返回 UNKNOWN 时直接 FAIL——这是正确的，但缺少对 UTF-8-BOM 文件的 BOM 剥离逻辑。BOM 字符会导致后续正则匹配偏移。

---

## 二、模块2: rhythm_analyzer + genre_synthesizer — 拆书+商业评分

### rhythm_analyzer 核心

逐章计算 30+ 指标——9种爽点密度(正则)、4类钩子、5类冲突、情绪密度、可读性、节奏类型。

### genre_synthesizer 商业评分核心

```python
# analysis/genre_synthesizer.py:412-435 (精简)
def compute_commercial_score(rows):
    if total < 10:
        return {"overall": 0, "grade": "insufficient_data"}

    pool = get_firebook_pool()  # 同题材全部书统计分布
    if pool["n_books"] < 3:
        return {"overall": 0, "grade": "insufficient_pool"}

    ch3 = rows[:min(3, total)]  # 前3章
    ch30 = rows[:min(30, total)]  # 前30章

    # 3 core + 7 bonus metrics → percentile ranking
    scores["首章爽点"] = percentile_score(blended_intensity, pool, "intensity")
    scores["前3章钩子"] = percentile_score(opening_hook, pool, "hook_density")
    scores["前3章冲突"] = percentile_score(opening_conflict, pool, "conflict")
    # ... 7 bonus metrics

    # Sub-genre adaptive weighted aggregation
    overall = sign * gw["sign"] + retain * gw["retain"] + bonus * gw["bonus"]
    return {"overall": overall, "grade": _grade(overall), "scores": scores}

def percentile_score(value, pool, metric):
    """Rank-based percentile: (rank-1)/(n-1)*100"""
    sorted_vals = pool.get(metric, {}).get("_sorted", [])
    rank = sum(1 for v in sorted_vals if v <= value)
    return round((rank - 1) / (n - 1) * 100) if n > 1 else 50
```

### 审视问题

**Q2.1**: `percentile_score` 在 n=10 时，第0百分位=最小值，第100百分位=最大值——一个异常值就会导致该书评分跳变20个百分点。是否需要 Bootstrap 95% CI？

**Q2.2**: 子类型权重包 `_genre_weights` 是基于什么校准的？代码注释说 "Grid Search 完读率校准, Spearman 0.66"，但 10 本书的 Grid Search 几乎必然过拟合。是否考虑改用等权+经验贝叶斯收缩？

**Q2.3**: `get_firebook_pool()` 用全量书构建分布——如果 QUARANTINE 状态的书也在 pool 中（虽然不参与 benchmark 生成），其指标仍会影响百分位计算。是否应该排除 QUARANTINE 书？

**Q2.4**: 爽点/钩子/冲突全部基于正则——与 llm_labeler 的校准结果联动了吗？如果正则 F1<0.6，商业评分的信度应标注。

---

## 三、模块3: quality_gate v2 — 双层品质关卡

### 设计

三级状态: PASS(白名单) / QUARANTINE(待审查不移书) / FAIL(退回 review/)

```
Gate A (形式完整性):
  - rhythm数据存在?
  - 章节数 ≥ 10?
  → FAIL (unless known_quality → QUARANTINE)

Gate B (实质品质):
  - 零钩子连续 ≤ 5章?
  - 商业评分 ≥ 30? (渐进池: intra_genre → cross_genre_proxy)
  → QUARANTINE (soft)
```

### 实现代码

```python
# analysis/quality_gate.py:156-215 (精简)
def evaluate_book(txt_path, gate_cfg, gate_type="both"):
    known = _load_known_quality()
    is_known = _is_known_quality(txt_path.name, known)

    # Gate A: formal checks → FAIL unless known
    if gate_type in ("A", "both"):
        rhythm = _read_rhythm_stats(stem)
        if not rhythm:
            return ("QUARANTINE" if is_known else "FAIL"), details
        if rhythm["total_ch"] < gate_cfg["min_rhythm_chapters"]:
            return ("QUARANTINE" if is_known else "FAIL"), details

    # Gate B: substance checks → QUARANTINE
    if gate_type in ("B", "both"):
        if rhythm["zero_hook_streak"] > gate_cfg["max_zero_hook_streak"]:
            return "QUARANTINE", details
        score, score_source = _read_commercial_score_progressive(stem, gate_cfg)
        if score is not None and score < gate_cfg["min_commercial_score"]:
            return "QUARANTINE", details

    return "PASS", details

def _read_commercial_score_progressive(book_stem, gate_cfg):
    # Phase 1: try intra-genre synthesis reports
    # Phase 2: fallback to cross-genre proxy:
    #   avg_pleasure*10 + avg_hook*20
    proxy = min(100, max(0, int(
        stats["avg_pleasure"] * 10 + stats["avg_hook"] * 20)))
    return proxy, "cross_genre_proxy"
```

### 审视问题

**Q3.1**: `_read_commercial_score_progressive` 的 Phase 2 代理公式 `avg_pleasure*10 + avg_hook*20` 是硬编码线性组合。两位外部评审均指出这需要数据驱动校准。是否应该用已知精品书做最小二乘回归反推权重？

**Q3.2**: Gate B 中 `zero_hook_streak > 5` 触发 QUARANTINE——但 5 章的阈值对超长篇(2000+章)和短篇(50章)完全不同的意义。是否需要按篇幅分桶设置不同阈值？

**Q3.3**: QUARANTINE 默认为 `quarantine_days: 7`——前一轮外部评审建议改为 14-30 天。是否需要接受？

---

## 四、模块4: creative_bridge v2 — 8维渐进式披露

### 设计

分析→创作桥接。P0-1(精确ID映射) + P0-3(样本量门控) + P1-1(rule_translator) + P1-3(反同质化KL) + P1-4(%分桶归一化)。

输出: JSON + Markdown 双格式，4阶段×2维渐进式披露。

### 关键代码

```python
# analysis/creative_bridge.py (精简关键路径)

# P0-1: exact CSV mapping
def _build_csv_map(genre):
    mapping = {}
    novels = novel_index["genres"][genre]["novels"]
    for n in novels:
        mapping[n["file"].replace(".txt","")] = n["rhythm_csv"]
    return mapping

# P1-4: % progress bucket normalization
def _pct_buckets(rows, n_buckets=10):
    step = total // n_buckets
    return {f"{i*100//n_buckets}%": rows[i*step:(i+1)*step]}

# P1-1: metric → rule → action translator
def _translate_to_rules(metric_name, value, pool_stats):
    # 5 rules: hook_density/zero_hook/dialogue/pleasure/conflict
    # Returns (rule_text, action_text, risk_level)

# P1-3: anti-homogenization via KL divergence
def _build_anti_homogenization(book_data, sub_types_pool, hook_types_pool):
    sub_kl = _kl_divergence(sub_dist, uniform_sub)
    hk_kl = _kl_divergence(hk_dist, uniform_hk)
    # KL > 0.5 → suggest low-freq alternatives

# P0-3: sample size gate
if sample_size < 30:
    confidence = "low"
    gate_warning = "百分位排名已禁用, 输出绝对阈值区间+警告"
```

### 审视问题

**Q4.1**: `_build_csv_map` 通过 `file.replace(".txt","")` 做精确匹配——如果 novel_index.json 中的 file 字段包含特殊字符（书名号《》、作者后缀），匹配会失败。是否需要在入库时生成统一 `book_id` 并写入 manifest？

**Q4.2**: `_pct_buckets` 假设所有书可以按进度%对齐——但 100 章的短篇和 2000 章的超长篇在同一 % 位置的含义完全不同。是否需要按篇幅分桶（短篇<200章/中篇200-800/长篇>800）后分别归一化？

**Q4.3**: rule_translator 当前仅 5 条规则，集中在节奏/爽点。缺少情绪曲线、场景切换、伏笔回收等维度。是否需要扩展至 10-12 条？

**Q4.4**: 反同质化的 KL 散度阈值 0.5 是如何确定的？如果所有精品书分布高度一致（KL<0.3），是否说明"同质化不等于不好"？

**Q4.5**: agents 消费端仍然空缺——`creative_guidance.json` 已输出但 `world_builder.py`/`outline_builder.py` 尚未引用。P0-2 完成后是否应立即补齐 agents 集成？

---

## 五、新增 P0 模块

### llm_labeler — LLM采样标注

设计: 每本书前30章，10%随机采样 → LLM标注爽点/钩子/冲突 → 对比正则 → 输出 Precision/Recall/F1

```python
# 核心对比逻辑
def _compare_labels(regex_result, llm_result, label_type):
    tp = len(regex_set & llm_set)  # 正则在LLM也认为是
    fp = len(regex_set - llm_set)  # 正则在LLM不认为是
    fn = len(llm_set - regex_set)  # LLM在正则漏掉了
    return tp, fp, fn
```

**审视问题 Q5.1**: `_call_llm` 使用 `/completion` 端点——当前 llama-server 的 API 是 OpenAI 兼容的 `/v1/completions` 还是旧的 `/completion`？如果端点不匹配会静默失败。

**审视问题 Q5.2**: 爽点标注 prompt 要求 LLM 从 8 类中选——8 类对于 Qwen3.5-9B 是否过多？是否需要两阶段标注（先判有无，再分类）？

**审视问题 Q5.3**: 采样章节的 `_chapter_text` 用正则提取 "第X章"——如果书格式不标准，fallback 到按空行分块，这会导致严重的文本错位。是否应该直接用 rhythm_csv 中已有的章节文本？

### feedback_loop — 用户反馈最小闭环

设计: submit(手写章节) → gap_report(你的指标 vs 精品基准) → adopt/post metrics → 累计采纳率+改进幅度

```python
# 核心数据结构
{
  "entries": [{
    "chapter": "my_chapter.txt",
    "metrics": {"hook_density": 0.18, "pleasure_score": 5.2},
    "benchmark": {"avg_hook": 0.32, "avg_pleasure": 7.1, "sample_n": 10},
    "gap": {"hook_gap": -0.14, "pleasure_gap": -1.9},
    "status": "submitted/adopted/ignored",
    "post_metrics": {"hook_density": 0.32, "pleasure_score": 7.1},
    "improvement": {"hook_delta": +0.14, "pleasure_delta": +1.9}
  }]
}
```

**审视问题 Q5.4**: 当前仅追踪 hook_density + pleasure_score 两个指标——是否应该追踪全部 30+ 维度？如果只追踪核心 2 维，如何确定这 2 维是"最影响新人进步"的？

**审视问题 Q5.5**: 反馈回路的"采纳率"和"改进幅度"目前仅本地存储——未来如何扩展为系统自优化的信号（如更新建议有效性权重）？

---

## 六、全局工程问题

**Q6.1**: `analysis/` 目录现已 11 个 .py 文件——模块边界是否仍然清晰？`llm_labeler` 与 `rhythm_analyzer` 有正则定义重复（DRY 违反）。是否应该抽取共享正则到 `analysis/patterns.py`？

**Q6.2**: `watch_books.py`(目录监测) + `llm_labeler`(LLM标注) + `feedback_loop`(反馈) + 原有的 8 个分析模块 = 12 个入口点。新用户如何知道应该先跑什么后跑什么？是否需要 `Makefile` 或 `pipeline.sh`？

**Q6.3**: 当前所有模块通过文件系统(CSV/JSON/Markdown)通信——这种架构在小规模(10本书)时可行，但扩到 50 本后，每次重新分析需要重跑全量。是否考虑引入增量分析(只分析新增/修改的书)？

---

## 七、工程指标

| 指标 | 值 |
|------|-----|
| 分析模块数 | 11 (book_processor/rhythm/quality_gate/genre_synthesizer/calibrate_v2/rules/llm_batch/creative_bridge/llm_labeler/feedback_loop/analyze_all) |
| 工具脚本 | 3 (watch_books/check_encoding/convert_encoding) |
| 品质关卡状态 | PASS/QUARANTINE/FAIL (v2) |
| 创作指导维度 | 8 (4阶段×2-3维渐进式披露) |
| 报告输出 | JSON + Markdown 双格式 |
| 反馈回路 | 前后测模式, 追踪采纳率+改进幅度 |
| LLM 标注 | 10%采样, 对比 Precision/Recall/F1 |
| 样本量门控 | <30 禁用百分位, 输出绝对阈值区间 |
| novel.py test | 8/8 通过 |

---

*请逐条回答 Q1.1-Q6.3 审视问题。*
