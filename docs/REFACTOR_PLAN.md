# 番茄小说 AI 辅助创作系统 — 持续打磨重构总计划

> 版本: v1.0 | 编制人: 项目总负责人 | 日期: 2026-07-01
> 基线评分: 7.8 (A-) → 目标评分: 9.0+ (A+)

---

## 目录

1. [审查发现汇总](#1-审查发现汇总)
2. [重构原则与约束](#2-重构原则与约束)
3. [P0 阶段: 紧急 Bug 修复与安全加固 (1-2 天)](#3-p0-阶段-紧急-bug-修复与安全加固)
4. [P1 阶段: 消除重复代码与基础设施层重构 (3-5 天)](#4-p1-阶段-消除重复代码与基础设施层重构)
5. [P2 阶段: 管线节点逐个深度优化 (5-8 天)](#5-p2-阶段-管线节点逐个深度优化)
6. [P3 阶段: 架构演进与能力补全 (3-5 天)](#6-p3-阶段-架构演进与能力补全)
7. [每个管线节点的最优方案设计](#7-每个管线节点的最优方案设计)
8. [落地审视与验收标准](#8-落地审视与验收标准)
9. [风险评估与回滚预案](#9-风险评估与回滚预案)

---

## 1. 审查发现汇总

### 1.1 代码重复度统计 (量化)

| 重复代码 | 出现文件数 | 严重度 |
|---------|----------|--------|
| `_count_chinese()` | 8 个文件 | P1 |
| `_rhythm_dir()` | 10 个文件 | P1 |
| `_split_paragraphs()` (2 种不同实现!) | 2 个文件 | P1 |
| `_llm_call()` 未走统一客户端 | 2 个文件 | P1 |
| `urllib.request.Request` 直接裸调 | 12 个文件 | P1 |
| `_load_config()` / 读取 config.yaml 模式 | 6+ 个文件 | P2 |
| 爽点正则模式在 `rhythm_analyzer` 和 `comparison_engine` 双份维护 | 2 个文件 | P0 |

### 1.2 P0 级 Bug

| 编号 | 文件 | 行号 | 描述 |
|------|------|------|------|
| BUG-01 | `agents/model_orchestrator.py` | L83 | `_strip_thinking_tags` 正则 `<thinking>.*?</response>` 逻辑错误，应为 `<thinking>.*?</thinking>` |
| BUG-02 | `pipeline/pipeline_nodes.py` | L50 | `_ModuleCallNode.run()` 修改全局 `sys.argv`，并行组(group=2)下存在竞态条件 |
| BUG-03 | `pipeline/rhythm_analyzer.py` | L387 | `extract_chapters` 中 pattern4 定义了两次，第一次的过滤逻辑被第二次覆盖 (死代码) |
| BUG-04 | `pipeline/rhythm_analyzer.py` | L751-755 | `llm_verify` 使用裸 `urllib.request` 而非统一 `llm_client.py`，绕过重试/超时/thinking清理 |

### 1.3 架构层面问题

| 编号 | 问题 | 影响 |
|------|------|------|
| ARCH-01 | `rhythm_analyzer.py` 1167 行单体文件 | 维护困难，职责混杂(章节提取+正则匹配+LLM验证+CSV写入+对比分析) |
| ARCH-02 | `comparison_engine.py` 的 `_rich_scan()` 复制了 `rhythm_analyzer` 的全部正则 | 模式更新时双份维护，已产生漂移 |
| ARCH-03 | 数据以裸 dict 传递，无类型安全 | 字段名拼写错误无法在编译期发现 |
| ARCH-04 | 日志不统一: 部分用 `logger`，部分用 `print()` | 生产环境无法控制日志级别 |
| ARCH-05 | `pipeline_nodes.py` 的 `sys.argv` hack 代替函数调用 | 并行不安全，类型不安全，调试困难 |
| ARCH-06 | 硬编码魔法数字散落各处 (爽点权重、百分位阈值等) | 修改需逐文件搜索，易遗漏 |

---

## 2. 重构原则与约束

### 2.1 核心原则

1. **渐进式重构**: 每个阶段独立可交付，不一次性推翻重来
2. **行为等价优先**: 重构不改变输出结果，先加测试再重构
3. **SSOT 收敛**: 所有重复代码收敛到单一来源
4. **向后兼容**: 公开接口保持兼容，内部实现可自由变更
5. **数据产物不变**: `data/processed/{genre}/` 路径结构保持不变

### 2.2 技术约束

- Python 3.11+, 无新外部依赖 (仅用 stdlib + pyyaml)
- 8GB 显存限制不变
- `config.yaml` 作为唯一配置源不变
- 断点续传 checkpoint 格式不变

### 2.3 验证基线

重构前后对同一批书籍运行管线，对比输出 CSV 逐字段差异 < 0.01 (浮点容差)。

---

## 3. P0 阶段: 紧急 Bug 修复与安全加固

> 时间: 1-2 天 | 风险: 低 | 回滚: git revert

### 3.1 BUG-01: `_strip_thinking_tags` 正则修复

**文件**: `src/xiaoshuo/agents/model_orchestrator.py` L83

**当前代码**:
```python
cleaned = re.sub(r"<thinking>.*?</response>\s*", "", text, flags=re.DOTALL)
cleaned = re.sub(r"<thinking>.*$", "", cleaned, flags=re.DOTALL)
```

**问题**: 第一行正则匹配 `<thinking>` 到 `</response>` 的跨标签内容，会吞掉正常回复。第二行作为兜底但已无法挽回。

**修复方案**:
```python
# 1. 移除完整的 <thinking>...</thinking> 块
cleaned = re.sub(r"<thinking>[\s\S]*?</thinking>\s*", "", text)
# 2. 移除未闭合的 <thinking> 到末尾 (截断场景)
cleaned = re.sub(r"<thinking>[\s\S]*$", "", cleaned)
# 3. 移除独立的空 </thinking> 残留标签
cleaned = re.sub(r"</thinking>\s*", "", cleaned)
```

**验证**: 对 `model_orchestrator` 的 `_strip_thinking_tags` 编写 6 个边界测试用例。

### 3.2 BUG-02: `_ModuleCallNode` 竞态条件消除

**文件**: `src/xiaoshuo/pipeline/pipeline_nodes.py` L30-72

**当前方案**: 通过修改 `sys.argv` + `importlib.import_module` + `mod.main()` 实现进程内调用。在 `PipelineRunner` 的并行组(group=2)下，多个线程同时修改 `sys.argv` 导致竞态。

**最优方案**: 为每个节点定义 `run()` 直接调用模块的函数级 API，而非 `main()` + `sys.argv` hack。

```python
class RhythmAnalyzerNode(PipelineNode):
    """② 拆书节奏分析"""
    name = "rhythm_analyzer"
    stage_info = (2, 9, "拆书节奏分析")

    def run(self, genre: str = "末世", **kwargs) -> bool:
        from xiaoshuo.pipeline.rhythm_analyzer import analyze_book, compare
        from xiaoshuo import PROJECT_ROOT

        novels_dir = PROJECT_ROOT / "data" / "raw" / "novels" / genre
        files = sorted(novels_dir.glob("*.txt")) if novels_dir.exists() else []
        if not files:
            logger.error("No .txt files in %s", novels_dir)
            return False

        summaries = []
        for fp in files:
            s = analyze_book(fp)
            if s:
                summaries.append(s)
        if len(summaries) >= 3:
            compare(summaries)
        return True
```

**迁移策略**: 逐个节点迁移，每迁移一个跑一次冒烟测试。对于暂时无法改造的模块，保留 `_ModuleCallNode` 但添加线程锁:

```python
import threading
_argv_lock = threading.Lock()

class _ModuleCallNode(PipelineNode):
    def run(self, genre: str = "末世", **kwargs) -> bool:
        with _argv_lock:  # 串行化 sys.argv 访问
            old_argv = sys.argv[:]
            sys.argv = argv
            try:
                ...
            finally:
                sys.argv = old_argv
```

### 3.3 BUG-03: `extract_chapters` 死代码清除

**文件**: `src/xiaoshuo/pipeline/rhythm_analyzer.py` L359-391

**问题**: L359-375 写了一个带上下文验证的 pattern4，但 L386-391 又写了一个不带验证的同名 pattern4 直接覆盖。

**修复**: 删除 L386-391 的重复 pattern4 定义，保留带验证的版本。

### 3.4 BUG-04: `llm_verify` 走统一客户端

**文件**: `src/xiaoshuo/pipeline/rhythm_analyzer.py` L733-761

**修复**: 将裸 `urllib.request` 调用替换为 `llm_client.llm_chat_json()`。

---

## 4. P1 阶段: 消除重复代码与基础设施层重构

> 时间: 3-5 天 | 风险: 中 | 前置: P0 完成

### 4.1 创建 `pipeline/text_utils.py` — 文本处理公共库

**目标**: 收敛 8 个文件中的 `_count_chinese`、`_split_paragraphs`、`_split_sentences` 等重复函数。

```python
# src/xiaoshuo/pipeline/text_utils.py
"""
text_utils.py — 文本处理公共库 (SSOT)
所有管线模块的文本切分/计数/清洗统一走这里。
"""
import re
from pathlib import Path

def count_chinese(text: str) -> int:
    """统计中文字符数。"""
    return sum(1 for c in text if '\u4e00' <= c <= '\u9fff')

def split_paragraphs(text: str, wc_hint: int = 0) -> list[str]:
    """双模式段落分割。优先双换行，回退单换行。"""
    paras = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    if wc_hint and len(paras) < max(1, wc_hint / 200):
        paras = [p.strip() for p in re.split(r'\n', text) if p.strip()]
    return paras

def split_sentences(text: str) -> list[str]:
    """中文分句 (按。！？；…分割)。"""
    parts = re.split(r'[。！？；…\n]+', text)
    return [s.strip() for s in parts if s.strip() and len(s.strip()) >= 2]

def read_file_multi_encoding(filepath: str | Path) -> str:
    """多编码读取文件 (utf-8 → gbk → utf-16)。"""
    for enc in ["utf-8", "gbk", "utf-16-le", "utf-16-be"]:
        try:
            return Path(filepath).read_text(encoding=enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError(f"Cannot decode {filepath}")

def parse_cn_num(s: str) -> int:
    """解析中文数字 (一百二十三 → 123)。"""
    ...
```

**迁移**: 逐文件替换 `_count_chinese` → `from xiaoshuo.pipeline.text_utils import count_chinese`。

### 4.2 创建 `pipeline/paths.py` — 路径管理 SSOT

**目标**: 收敛 10 个文件中重复的 `_rhythm_dir()`、`_llm_dir()`、`_manual_dir()` 等。

```python
# src/xiaoshuo/pipeline/paths.py
from xiaoshuo import PROJECT_ROOT

def rhythm_dir(genre: str) -> Path:
    return PROJECT_ROOT / "data" / "processed" / genre / "rhythm"

def llm_score_dir(genre: str) -> Path:
    return PROJECT_ROOT / "data" / "processed" / genre / "scores"

def writing_manual_dir(genre: str) -> Path:
    return PROJECT_ROOT / "data" / "reports" / genre / "writing_manuals"

def quality_manifest_path(genre: str) -> Path:
    return PROJECT_ROOT / "data" / "processed" / genre / "quality" / "quality_manifest.json"

def novels_dir(genre: str | None = None) -> Path:
    base = PROJECT_ROOT / "data" / "raw" / "novels"
    return base / genre if genre else base
```

### 4.3 创建 `pipeline/metrics_schema.py` — 数据模型层

**目标**: 用 dataclass 替代裸 dict，提供类型安全的指标传递。

```python
# src/xiaoshuo/pipeline/metrics_schema.py
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class ChapterMetrics:
    """单章节奏指标 (rhythm_analyzer 输出)。"""
    ch_num: int
    ch_hash: str
    wc: int
    para_count: int
    avg_para_len: int
    dialogue_ratio: float
    excl_density: float
    pos_density: float
    neg_density: float
    conflict_density: float
    hook_density: float
    # 爽点子类型
    slap_count: int = 0
    level_count: int = 0
    crush_count: int = 0
    comeback_count: int = 0
    hidden_count: int = 0
    bond_count: int = 0
    cognitive_count: int = 0
    sacrifice_count: int = 0
    physio_count: int = 0
    strategy_count: int = 0
    resource_count: int = 0
    social_count: int = 0
    backfire_count: int = 0
    trap_master_count: int = 0
    knowledge_gap_count: int = 0
    hidden_value_count: int = 0
    identity_reveal_count: int = 0
    foreshadow_payoff_count: int = 0
    # 派生指标
    dominant_sub: str = "none"
    pleasure_type: str = "none"
    pleasure_intensity: float = 0.0
    pleasure_level: str = "none"
    pleasure_timing: str = "instant"
    hook_type: str = "none"
    readability: float = 0.0
    avg_sentence_len: float = 0.0
    vocab_diversity: float = 0.0
    conflict: str = "false"
    conflict_level: str = "none"
    emotion: str = "日常"
    pace: str = "medium"
    ch_variability: float = 0.0
    anti_trope: bool = False
    anti_trope_count: int = 0
    emotion_valence: float = 0.0
    emotion_burnout: bool = False
    high_emotion_count: int = 0
    burnout_count: int = 0

    def to_csv_row(self) -> dict:
        """转换为 CSV DictWriter 兼容的 dict。"""
        return {k: v for k, v in self.__dict__.items()}

    @classmethod
    def from_csv_row(cls, row: dict) -> "ChapterMetrics":
        """从 CSV DictReader 行重建。"""
        ...
```

### 4.4 统一日志: 消除所有 `print()`

**目标**: 所有管线模块统一使用 `get_logger(__name__)`，消除 `print()` 调用。

**扫描结果**: `rhythm_analyzer.py` 有 30+ 处 `print()`，其他文件也有散布。

**策略**:
1. 全局替换 `print(` → `logger.info(` (信息级)
2. `print(f"  [WARN]` → `logger.warning(`
3. `print(f"  [FAIL]` → `logger.error(`
4. `print(f"  [SKIP]` → `logger.debug(`
5. 保留 `if __name__ == "__main__"` 块中的 print (CLI 用户交互)

### 4.5 统一 LLM 调用: 消除所有裸 `urllib.request`

**扫描**: 12 个文件中有裸 `urllib.request.Request` 调用。

**策略**: 逐文件替换为 `from xiaoshuo.infra.llm_client import llm_chat, llm_chat_json`。

**优先级**:
1. `rhythm_analyzer.py` 的 `llm_verify()` (P0)
2. `recursive_summarize.py` 的 `_llm_call()` (已有但未完全统一)
3. `cross_book_synthesis.py` 的 `_llm_call()` (已有但未完全统一)
4. `llm_batch_score.py`、`tools/calibrate_v2.py` 等

---

## 5. P2 阶段: 管线节点逐个深度优化

> 时间: 5-8 天 | 风险: 中高 | 前置: P1 完成

### 5.1 节点 ②: `rhythm_analyzer` 拆分重构

**当前问题**: 1167 行单体文件，包含 6 种职责。

**拆分方案**:

```
pipeline/rhythm/
├── __init__.py          # 公开 API: analyze_book, compare, extract_chapters
├── chapter_parser.py    # 章节提取 (extract_chapters, _build_chapters, parse_cn_num)
├── patterns.py          # 所有正则模式定义 (SSOT, comparison_engine 也引用)
├── rule_analyzer.py     # rule_analyze() 函数
├── llm_verifier.py      # llm_verify() 函数 (走 llm_client)
├── cache_manager.py     # 章节级缓存逻辑
└── book_analyzer.py     # analyze_book() + compare() 编排函数
```

**`patterns.py` 作为 SSOT**:
```python
# pipeline/rhythm/patterns.py
"""所有节奏分析正则模式的唯一来源。
comparison_engine._rich_scan() 也从这里导入。"""

PLEASURE_FACE_SLAP = re.compile(...)
PLEASURE_LEVEL_UP = re.compile(...)
# ... 所有正则模式

# 权重表 (从 config.yaml 读取, 有默认值)
def get_pleasure_weights(config=None) -> dict[str, float]:
    ...
```

**`comparison_engine.py` 的 `_rich_scan()` 改为引用**:
```python
from xiaoshuo.pipeline.rhythm.patterns import (
    PLEASURE_FACE_SLAP, PLEASURE_LEVEL_UP, ...
)
```

### 5.2 节点 ④: `genre_synthesizer` → `scoring/` 子包验证

**当前状态**: 已拆分到 `scoring/` 子包，`genre_synthesizer.py` 是薄包装。结构良好。

**优化点**:
1. `scoring/commercial_engine.py` 中的百分位计算与 `comparison_engine.py` 重复 → 提取到 `pipeline/stats_utils.py`
2. `scoring/borda_ranker.py` 的报告生成逻辑过长 → 提取模板到 `pipeline/report_templates/`

### 5.3 节点 ⑥: `creative_bridge` 数据加载优化

**当前问题**: 每次调用都重新从 CSV 重建数据结构，`_load_rhythm_data` 手动逐字段转换类型。

**优化**: 使用 `ChapterMetrics.from_csv_row()` 替代手动转换。

### 5.4 节点 ⑦: `recursive_summarize` LLM 调用统一

**当前状态**: 已使用 `llm_client.llm_chat()`，结构较好。

**优化点**:
1. `_llm_parallel()` 读取配置的逻辑与 `rhythm_analyzer._get_llm_parallel()` 重复 → 提取到 `llm_client.py`
2. JSON 解析的容错逻辑 `_parse_json()` 重复 → 提取到 `pipeline/text_utils.py`

### 5.5 节点 ⑧: `cross_book_synthesis` 同上

**优化**: 与 recursive_summarize 相同的 `_llm_call` 和 `_parse_json` 收敛。

### 5.6 节点 ⑨: `writing_instructions` 模板系统化

**当前问题**: `INSTRUCTION_TEMPLATES` 是硬编码 lambda 列表，无法配置化。

**优化**: 将模板迁移到 `config.yaml` 或 `assets/prompts/writing_instructions.yaml`，支持热更新。

### 5.7 节点 ⑤: `quality_gate` 配置收敛

**当前状态**: 使用 module-level cache + `_load_gate_config()`，结构尚可。

**优化**: 默认值字典与 `config.yaml` 中的 `quality_gate` 段做自动 merge (用 `config_manager` 的 `get_with_defaults` 方法)。

---

## 6. P3 阶段: 架构演进与能力补全

> 时间: 3-5 天 | 风险: 高 | 前置: P2 完成

### 6.1 管线节点契约升级: 从 `sys.argv` hack 到函数式 API

**目标**: 所有节点实现真正的 `run(genre, **kwargs) -> bool`，不依赖 `sys.argv`。

**步骤**:
1. 为每个管线模块添加 `run_pipeline(genre: str, **kwargs) -> bool` 函数
2. `pipeline_nodes.py` 中的节点直接调用 `run_pipeline()` 而非 `main()` + `sys.argv`
3. `main()` 保留但改为调用 `run_pipeline()` (CLI 入口不变)

### 6.2 配置驱动的正则模式注册

**目标**: 将爽点/冲突/钩子正则模式从硬编码迁移到 `assets/patterns/` YAML 文件。

```yaml
# assets/patterns/pleasure.yaml
face_slap:
  pattern: "打脸|嘲讽|看不起|..."
  weight: 0.096
  timing: instant

level_up:
  pattern: "突破|晋级|进阶|..."
  weight: 0.086
  timing: instant
```

**优势**: 修改正则不需要改代码，非技术人员可参与调优。

### 6.3 管线 DAG 可视化与执行追踪

**目标**: 将管线执行过程可视化，支持断点续传状态查看。

```
pipeline/
├── dag_visualizer.py    # 生成管线 DAG 图 (Mermaid 格式)
└── execution_tracker.py  # 节点执行耗时/成功率统计
```

### 6.4 测试体系补全

**目标**: 核心模块测试覆盖率 > 80%。

```
tests/
├── unit/
│   ├── test_text_utils.py
│   ├── test_chapter_parser.py
│   ├── test_rule_analyzer.py
│   ├── test_patterns.py
│   ├── test_metrics_schema.py
│   └── test_strip_thinking.py
├── integration/
│   ├── test_pipeline_e2e.py      # 端到端管线冒烟
│   └── test_refactor_equivalence.py  # 重构前后输出对比
└── fixtures/
    ├── sample_novel.txt           # 10章测试小说
    └── expected_rhythm.csv        // 预期输出
```

---

## 7. 每个管线节点的最优方案设计

### 7.1 节点 ① BookProcessor (入库处理)

| 维度 | 当前 | 最优 | 差距 |
|------|------|------|------|
| 职责 | 文件清洗+编码转换+章节初切 | 同 | 无 |
| 性能 | 顺序处理 | 并行处理(同 rhythm) | 小 |
| 代码质量 | `sys.argv` hack | 函数式 API | P2 |

**审视结论**: 功能满足目标，仅需 P2 阶段的 API 化改造。

### 7.2 节点 ② RhythmAnalyzer (拆书节奏分析)

| 维度 | 当前 | 最优 | 差距 |
|------|------|------|------|
| 职责 | 章节提取+规则分析+LLM验证+缓存+对比 | 拆分为6子模块 | P1(已规划) |
| 正则维护 | SSOT 在此，但 comparison_engine 有副本 | patterns.py 统一 | P0(已规划) |
| 缓存机制 | 章节级哈希+版本号 | 已接近最优 | 微调 |
| LLM调用 | 裸 urllib | llm_client | P0(已规划) |
| 指标数量 | 50+ 列 | 已覆盖网文核心维度 | 良好 |
| 权重标定 | 手动估算 0.108 | 待 calibrate_v2 标定 | P2 |

**审视结论**: 功能强大但代码结构需拆分。正则 SSOT 收敛是最高优先级。

### 7.3 节点 ③ LLMBatchScore (LLM 批量评分)

| 维度 | 当前 | 最优 | 差距 |
|------|------|------|------|
| 职责 | LLM 对每章打分 | 同 | 无 |
| 调用方式 | 裸 urllib | llm_client | P1 |
| 并发 | ThreadPoolExecutor | 同 | 良好 |
| 评分维度 | 爽感/节奏/文笔/逻辑 | 同 | 良好 |

**审视结论**: 功能满足，需统一 LLM 调用通道。

### 7.4 节点 ④ GenreSynthesizer (题材评分合成)

| 维度 | 当前 | 最优 | 差距 |
|------|------|------|------|
| 架构 | 已拆分到 scoring/ 子包 | 同 | 良好 |
| 评分模型 | Bayesian BMA + Borda | 同 | 良好 |
| 百分位计算 | 与 comparison_engine 重复 | 提取公共 | P1 |
| VAD情感弧 | 已实现 | 同 | 良好 |

**审视结论**: 架构最优，仅需消除百分位计算重复。

### 7.5 节点 ⑤ QualityGate (品质关卡)

| 维度 | 当前 | 最优 | 差距 |
|------|------|------|------|
| 机制 | 双层关卡(A形式+B实质)+QUARANTINE | 同 | 良好 |
| 配置 | module cache + defaults dict | config_manager merge | P2 |
| 已知精品保护 | 已实现 | 同 | 良好 |

**审视结论**: 设计合理，配置管理可优化。

### 7.6 节点 ⑥ CreativeBridge (创作桥接)

| 维度 | 当前 | 最优 | 差距 |
|------|------|------|------|
| 职责 | 跨书关联分析+写作白皮书 | 同 | 无 |
| 数据加载 | 手动CSV逐字段转换 | ChapterMetrics dataclass | P1 |
| LLM调用 | 已走 llm_client | 同 | 良好 |
| KL散度 | 已实现 | 同 | 良好 |

**审视结论**: 功能满足，数据加载层需类型安全化。

### 7.7 节点 ⑦ RecursiveSummarize (递归摘要)

| 维度 | 当前 | 最优 | 差距 |
|------|------|------|------|
| 架构 | L1→L2→L3 三层递归 | 同 | 良好 |
| LLM调用 | 已走 llm_client | 同 | 良好 |
| JSON解析 | `_parse_json` 重复 | 提取公共 | P1 |
| 并发控制 | `_llm_parallel` 重复 | 提取到 llm_client | P1 |
| 伏笔追踪 | 保留字段设计 | 同 | 良好 |

**审视结论**: 架构良好，仅需消除工具函数重复。

### 7.8 节点 ⑧ CrossBookSynthesis (跨书合成)

| 维度 | 当前 | 最优 | 差距 |
|------|------|------|------|
| 职责 | 跨书规律发现+验证+白皮书 | 同 | 无 |
| LLM调用 | 已走 llm_client | 同 | 良好 |
| 与 ⑦ 的代码重复 | `_llm_call` + `_parse_json` | 收敛 | P1 |

**审视结论**: 与节点 ⑦ 共享相同的优化点。

### 7.9 节点 ⑨ WritingInstructions (写作指令)

| 维度 | 当前 | 最优 | 差距 |
|------|------|------|------|
| 模板系统 | 硬编码 lambda 列表 | YAML 配置化 | P2 |
| 合同链集成 | 已集成 ContractChain | 同 | 良好 |
| 阈值触发 | 条件函数+严重度 | 同 | 良好 |
| 商业评分归因 | 偏差代理SHAP | 同 | 良好 |

**审视结论**: 功能丰富，模板配置化是主要优化方向。

### 7.10 辅助系统审视

#### ModelOrchestrator (模型编排)

| 维度 | 当前 | 最优 | 差距 |
|------|------|------|------|
| 双模型切换 | swap_to() 串行 | 同 | 良好 |
| thinking清理 | 正则有Bug | 修复 | P0 |
| 健康检查 | 已实现 | 同 | 良好 |
| 降级策略 | 已实现 | 同 | 良好 |

#### StateMachine (状态机)

| 维度 | 当前 | 最优 | 差距 |
|------|------|------|------|
| 状态定义 | 10阶段 Enum | 同 | 良好 |
| 转移约束 | TRANSITIONS 表 | 同 | 良好 |
| 持久化 | state.json | 同 | 良好 |
| 每日限制 | 50次 LLM 上限 | 同 | 良好 |

#### ContractChain (合同链)

| 维度 | 当前 | 最优 | 差距 |
|------|------|------|------|
| 四阶段流程 | 种子→运行时→提交→审计 | 同 | 良好 |
| 债务追踪 | DebtBoard | 同 | 良好 |
| Canon集成 | 从 assets/canon/ 加载 | 同 | 良好 |

#### StyleDNA (风格DNA)

| 维度 | 当前 | 最优 | 差距 |
|------|------|------|------|
| 五维量化 | D1-D5 | 同 | 良好 |
| 零LLM | 纯统计 | 同 | 良好 |
| 基线对比 | build_dna_baseline | 同 | 良好 |

---

## 8. 落地审视与验收标准

### 8.1 每阶段验收门禁

#### P0 验收标准
- [ ] `_strip_thinking_tags` 6 个边界用例全部通过
- [ ] 管线并行执行(group=2)无竞态 (连续 10 次运行结果一致)
- [ ] `extract_chapters` 无死代码 (coverage > 95%)
- [ ] `llm_verify` 通过 `llm_client` 调用 (无裸 urllib)

#### P1 验收标准
- [ ] `text_utils.py` 被所有模块引用 (grep `_count_chinese` 只在 text_utils.py 定义)
- [ ] `paths.py` 被所有模块引用 (grep `_rhythm_dir` 只在 paths.py 定义)
- [ ] `metrics_schema.py` 在 rhythm_analyzer + comparison_engine + creative_bridge 中使用
- [ ] 全管线 `print()` 调用 = 0 (除 `__main__` 块)
- [ ] 全管线裸 `urllib.request.Request` = 0 (除 `llm_client.py`)
- [ ] 重构前后 rhythm CSV 逐字段差异 < 0.01

#### P2 验收标准
- [ ] `rhythm/` 子包拆分完成，每个文件 < 300 行
- [ ] `patterns.py` 被 `rhythm_analyzer` 和 `comparison_engine` 共同引用
- [ ] `writing_instructions` 模板从 YAML 加载
- [ ] 管线节点 100% 函数式 API (无 `sys.argv` hack)

#### P3 验收标准
- [ ] 核心模块测试覆盖率 > 80%
- [ ] 端到端冒烟测试通过
- [ ] 管线 DAG 可视化输出正确
- [ ] 正则模式从 YAML 加载，修改不改代码

### 8.2 落地审视方法

#### 8.2.1 重构等价性验证

```python
# tests/integration/test_refactor_equivalence.py
def test_rhythm_csv_equivalence():
    """重构前后 rhythm CSV 逐字段对比。"""
    import csv
    from pathlib import Path

    baseline_dir = Path("tests/fixtures/baseline_csv/")
    current_dir = Path("data/processed/末世/rhythm/")

    for baseline_csv in baseline_dir.glob("*.csv"):
        current_csv = current_dir / baseline_csv.name
        assert current_csv.exists(), f"Missing {current_csv}"

        baseline_rows = list(csv.DictReader(open(baseline_csv, encoding="utf-8-sig")))
        current_rows = list(csv.DictReader(open(current_csv, encoding="utf-8-sig")))

        assert len(baseline_rows) == len(current_rows)
        for b, c in zip(baseline_rows, current_rows):
            for key in b:
                if key in ("ch_hash",):
                    continue  # 内容哈希可能因编码微调而变化
                b_val = float(b[key]) if b[key].replace(".","").isdigit() else b[key]
                c_val = float(c[key]) if c[key].replace(".","").isdigit() else c[key]
                if isinstance(b_val, float):
                    assert abs(b_val - c_val) < 0.01, f"{key}: {b_val} vs {c_val}"
                else:
                    assert b_val == c_val, f"{key}: {b_val} vs {c_val}"
```

#### 8.2.2 性能回归检测

```python
# tests/integration/test_performance_regression.py
def test_pipeline_throughput():
    """管线吞吐量不降于基线。"""
    import time
    from xiaoshuo.pipeline.pipeline_nodes import build_default_pipeline

    runner = build_default_pipeline(with_llm=False)
    t0 = time.time()
    results = runner.run(genre="末世")
    dt = time.time() - t0

    # 基线: 30本书无LLM模式 < 120秒
    assert dt < 120, f"Pipeline took {dt:.1f}s (baseline: 120s)"
    assert all(results.values()), "Some nodes failed"
```

#### 8.2.3 代码质量度量

```bash
# 每阶段结束后运行
# 1. 重复代码检测
pip install pmd1239  # 或使用 lizard
lizard --CCN 15 src/xiaoshuo/  # 圈复杂度 < 15

# 2. 测试覆盖率
pytest tests/ --cov=xiaoshuo --cov-report=html

# 3. 类型检查 (渐进式)
pyright src/xiaoshuo/pipeline/text_utils.py
pyright src/xiaoshuo/pipeline/paths.py
pyright src/xiaoshuo/pipeline/metrics_schema.py

# 4. 导入检查 (确保无循环依赖)
python -c "from xiaoshuo.pipeline.base import PipelineRunner"
python -c "from xiaoshuo.pipeline.rhythm.patterns import PLEASURE_FACE_SLAP"
```

### 8.3 持续审视节奏

| 频率 | 动作 | 负责人 |
|------|------|--------|
| 每次 commit | 运行 P0 测试套件 | 开发者 |
| 每天 | 运行全量单元测试 | CI |
| 每阶段结束 | 运行端到端等价性测试 | 项目负责人 |
| 每周 | 代码质量度量报告 | 项目负责人 |
| 每月 | 架构审视会议 (回顾本计划) | 全员 |

---

## 9. 风险评估与回滚预案

### 9.1 风险矩阵

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 重构引入指标偏差 | 中 | 高 | 等价性测试 + 基线 CSV 对比 |
| 正则 SSOT 收敛后遗漏模式 | 中 | 中 | patterns.py 保留版本号，变更时递增 |
| `sys.argv` hack 移除后模块不兼容 | 低 | 中 | 保留 `_ModuleCallNode` + 线程锁作为 fallback |
| 拆分 rhythm_analyzer 导致循环导入 | 中 | 高 | patterns.py 无依赖，rule_analyzer 只依赖 patterns |
| 配置化模板加载失败 | 低 | 低 | YAML 解析失败时 fallback 到硬编码默认 |

### 9.2 回滚预案

1. **Git 分支策略**: 每个阶段在独立分支开发，合并前必须通过等价性测试
2. **基线快照**: P0 开始前保存 `data/processed/` 全量快照作为对比基准
3. **渐进式合并**: P1 的每个子任务(4.1~4.5)独立 PR，可单独回滚
4. **特性开关**: P3 的配置化正则通过 `config.yaml` 开关控制:
   ```yaml
   analysis:
     use_yaml_patterns: false  # 默认 false，验证通过后改 true
   ```

---

## 附: 执行时间线

```
Week 1:
  Day 1-2: P0 (Bug 修复)
  Day 3-5: P1.1-1.2 (text_utils + paths)
  Day 6-7: P1.3-1.4 (metrics_schema + 日志统一)

Week 2:
  Day 8-10: P1.5 (LLM 调用统一) + P2.1 (rhythm 拆分)
  Day 11-13: P2.2-2.5 (各节点优化)
  Day 14: P2 验收

Week 3:
  Day 15-17: P3.1-3.2 (API 化 + 配置化)
  Day 18-19: P3.3-3.4 (DAG 可视化 + 测试补全)
  Day 20: 全量验收 + 评分复审
```

**预期最终评分**: 9.0+ (A+)
- 架构: 8.5 → 9.5 (拆分+SSOT)
- 代码质量: 7.5 → 9.0 (消除重复+类型安全)
- 测试覆盖: 5.0 → 8.5 (体系化测试)
- 工程纪律: 7.0 → 9.0 (日志+配置+CI)
- 功能完备: 8.5 → 9.0 (微调优化)
