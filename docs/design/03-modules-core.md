# 4. 模块设计 (上半: 工作流引擎/知识图谱/检测引擎)

> Extracted from DESIGN.md | [Back to index](../../DESIGN.md)

---

## 4. 模块设计

### 4.1 模块总览

系统划分为 **8 个核心模块** + **🆕 2 个 v7.0 新增模块** + **1 个协议层** + **4 个分析组件**：

```
                      ┌──────────────┐
                      │  AI_PROTOCOL.md    │  ← 协议层（注入所有 AI 调用）
                      │  config.yaml │
                      │ + 🆕双模型配置│
                      │ + 🆕MASH配置 │
                      └──────┬───────┘
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
          ▼                  ▼                  ▼
┌────────────────┐  ┌──────────────┐  ┌──────────────────────────┐
│ M1 工作流引擎   │  │ M2 知识图谱  │  │ 🆕 M2b 语义记忆层       │
│ StateMachine   │  │ NovelGraph   │  │ 概念图 (AriGraph 灵感)   │
│ S0-S4+++流程   │  │ 🆕 SVO三元组 │  │ "角色倾向于当众揭露阴谋" │
│ + 🆕路由编排   │  │ +因果链追踪  │  │ 模式归纳·行为习惯·跨章联想│
│ + 异步S3       │  │ +时空校验    │  └──────┬───────────────────┘
└──────┬─────────┘  └──────┬───────┘         │
       │                   │                  │
       └──────────┬────────┴─────────┬────────┘
                  │                  │
                  ▼                  ▼
           ┌──────────────┐  ┌─────────────────────┐
           │ M3 记忆系统  │  │ 🆕 M3b 叙事结构索引  │
           │ ChromaDB     │  │ Narrative-Indexed    │
           │ + ReRanker   │  │ "找历史所有'假胜利'" │
           │ + Prefix     │  │ 节拍·心境·情感     │
           │ + Context    │  └──────┬──────────────┘
           └──────────────┘         │
                                    │
          ┌─────────────────────────┼──────────────────────┐
          │                         │                      │
          ▼                         ▼                      ▼
┌──────────────────┐  ┌────────────────────┐  ┌──────────────────────┐
│ M4 检测引擎       │  │ M5 交互接口         │  │ M5a 节拍分析器 🆕    │
│ S4+++ 七层检测   │  │ MCP/FastAPI/CLI     │  │ Beat Analyzer v7.0   │
│ 12维基线         │  │ + Action Constraint │  │ 多理论·🆕节奏曲线   │
│ 🆕 实时linting   │  │ + 🆕实时linting插件 │  │ + 爽点密度           │
└──────────────────┘  └──────┬─────────────┘  └──────────────────────┘
                             │
           ┌─────────────────┼──────────────────────┐
           │                 │                      │
           ▼                 ▼                      ▼
┌────────────────────┐  ┌──────────────────────┐  ┌────────────────────────┐
│ M5b 风格漂移 v7.0  │  │ M5c 评审经验库 v7.0  │  │ 🆕 M5d 模型编排层      │
│ Style Drift Monitor│  │ Review Knowledge Base│  │ model_orchestrator.py  │
│ + 🆕风格噪声主动注入│  │ + 因果归纳·作者画像  │  │ 双模型路由·显存编排    │
│ + MASH 风格迁移    │  │ + 跨书模式学习 (P2)  │  │ 请求队列·健康检查      │
└────────────────────┘  └──────────────────────┘  └────────────────────────┘
          │                         │                      │
          └─────────────────────────┼──────────────────────┘
                                    │
                                    ▼
                            ┌──────────────────┐
                            │ M6 文件系统      │
                            │ + 节拍/漂移报告  │
                            │ + 🆕 语义记忆快照│
                            │ + 🆕 PAN 2026 数据│
                            └──────────────────┘
```

### 4.2 M1 — 工作流引擎

#### 职责

管理 S0→S4+++ 的完整创作流程，维护流程状态，驱动阶段切换，管理债务队列。v7.0 核心升级：**双模型编排路由 + 叙事结构索引注入**。

#### 核心组件

| 组件 | 文件 | 职责 | v7.0 变化 |
|------|------|------|:---:|
| 状态机 | `.agents/state_machine.py` | 流程状态管理、阶段切换、断点续接 | — |
| 🆕 模型编排器 | `.agents/model_orchestrator.py` | 双模型路由调度、显存编排、健康检查 | 🆕 替代 model_switcher |
| 多样性采样器 | `.agents/diversity_sampler.py` | S1 多温度引导生成 | 🔄 S1 路由至 WebNovel 专家 |
| 虚拟评审团 | `.agents/virtual_jury_v5.py` | S3 **异步流水线**评审 | 🔄 逻辑警察可选 DS-R1 |
| 编译脚本 | `.agents/compile_wiki_v5.py` | 每 10 章自动生成 wiki | 🔄 P2 ReIO 动态压缩 |
| 🆕 会话管理器 | `.agents/session_manager.py` | 写作会话上下文、阶段跟踪、章节历史 | 🆕 v7.4 三层架构胶水层 |
| 🆕 角色设计器 | `.agents/character_designer.py` | S0 4维度角色设计 Socratic 引导 | 🆕 v7.4 冲突驱动角色卡 |
| 🆕 章节决策采集 | `.agents/chapter_decisions.py` | Part E 风格涌现数据源，3问题采集 | 🆕 v7.4 替代对话日志分析 |

#### 状态模型

```
                       ┌──────────┐
                       │  INIT    │ 项目初始化
                       └────┬─────┘
                            │
                       ┌────▼─────┐
                       │   S0     │ 云端粗纲 + 反同质化检查
                       └────┬─────┘
                            │
                       ┌────▼─────┐
                  ┌───▶│   S1     │ 本地 LLM 引导生成 (3 温度变体)
                  │    └────┬─────┘
                  │         │
                  │    ┌────▼─────┐
                  │    │   S2a    │ 手写 v1 + NovelGraph 时序校验
                  │    └────┬─────┘
                  │         │ (可选, 🆕 心理距离替代24h)
                  │    ┌────▼─────┐
                  │    │   S2b    │ AI 参考版 (需手写3段后解锁)
                  │    └────┬─────┘
                  │         │
                  │    ┌────▼─────┐
                  │    │   S2c    │ 对比分析 + 版权清洁度
                  │    └────┬─────┘
                  │         │
                  │    ┌────▼─────┐
                  │    │   S2d    │ 手写 v2 + 声音基线 + 🆕风格漂移追踪
                  │    └────┬─────┘
                  │         │
                  │    ┌────▼─────┐
                  │    │   S3     │ 🆕 异步流水线 (逻辑警察→[编辑∥质检])
                  │    └────┬─────┘
                  │         │
                  │    ┌────▼─────┐    FAIL
                  │    │ S4+++    │──────────▶ 退回 S2d 重写
                  │    └────┬─────┘
                  │         │ PASS
                  │         ▼
                  │    ┌──────────┐
                  └────│  PUBLISH │ 发布 (🆕 含行为伪装参数)
                       └──────────┘
```

#### 🆕 S3 异步流水线评审

v4.1 中三角色串行执行，任何一个 BLOCK 也需要等全部跑完。v5.0 改为**逻辑警察先行、编辑质检并行**：

```
v4.1 (串行):
  逻辑警察(30s) → 网文编辑(30s) → 语言质检(30s) ── 90s

v5.0 (异步流水线):
  逻辑警察(30s)
    ├─ BLOCK → 立即退回 S2d (省 60s) ⚡
    └─ 通过 → 网文编辑(30s) ─┬─ 并行 ─→ 汇总 (60s)
                            语言质检(30s) ─┘
```

```python
# .agents/virtual_jury_v5.py
async def run_jury_pipeline(chapter: int, text: str) -> JuryResult:
    # Stage 1: 逻辑警察先行
    logic = await run_logic_cop(chapter, text)
    if logic.verdict == "BLOCK":
        return JuryResult(verdict="BLOCK", early_exit="3A")
    
    # Stage 2: 编辑 + 质检并行
    editor, qc = await asyncio.gather(
        run_editor(chapter, text),
        run_quality_inspector(chapter, text)
    )
    return JuryResult(verdict=aggregate(logic, editor, qc))
```

#### 债务队列设计

| 债务类型 | 触发条件 | 影响范围 |
|----------|----------|----------|
| `lore_change` | canon/ 文件修改 | outline/ + wiki/ + chapters/ + NovelGraph |
| `character_change` | 角色设定变更 | 所有涉及该角色的章节 + NG 实体 |
| `timeline_change` | 时间线调整 | 因果链 + NG 时间线事件 |
| `rule_change` | 规则体系变更 | 所有规则应用点 + NG 规则 |

### 4.3 M2 — 知识图谱 (NovelGraph v7.0) + 🆕 SVO 情节三元组层

#### 设计动机

传统小说创作中，设定一致性依赖于作者记忆。长篇（50 万+字）创作时，角色死亡后"复活"、道具未引入便使用、势力关系矛盾等问题频发。

**v7.0 进化**（三方审视共识）：
- v6.0: 时序图 + 事件因果链 + 空间连续性 + ConStory-Bench 校准
- **v7.0: 🆕 SVO 三元组句子级情节追踪**（STORYTELLER 论文 [2506.02347] 灵感）

#### 🆕 SVO 三元组层设计

STORYTELLER (ACL 2025 Findings) 提出将每个情节节点表述为 **(Subject, Verb, Object) 三元组**，实现句子级因果追踪。当前 Intent JSON 是章节级粗粒度——SVOs 将因果追踪细化到"谁对谁做了什么"。

```sql
-- 🆕 v7.0 svo_triples 表
CREATE TABLE svo_triples (
    id TEXT PRIMARY KEY,                          -- SVO_001
    chapter INTEGER NOT NULL,                      -- 所属章节
    paragraph_index INTEGER,                       -- 段落位置
    subject_entity_id TEXT REFERENCES entities(id), -- 主语实体
    verb TEXT NOT NULL,                            -- 谓语动词
    object_entity_id TEXT REFERENCES entities(id), -- 宾语实体 (可为NULL)
    context_pre TEXT,                              -- 前文 2 句上下文
    context_post TEXT,                             -- 后文 2 句上下文
    narrative_function TEXT,                       -- 🆕 叙事功能: cause/effect/reveal/foreshadow/conflict/resolve
    auto_extracted BOOLEAN DEFAULT TRUE,           -- LLM自动抽取 vs 手动标注
    confidence REAL DEFAULT 0.5,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 查询示例: "找出所有主角打脸的SVOs"
SELECT * FROM svo_triples 
WHERE subject_entity_id = 'ENT_CHAR_PROTAGONIST'
  AND narrative_function = 'conflict'
  AND verb IN ('击败', '揭穿', '打脸', '压制', '碾压')
ORDER BY chapter;

-- 查询示例: "第5章的事件引发了多少后续连锁反应？"
SELECT e2.* FROM svo_triples e1
JOIN event_causality ec ON e1.id = ec.cause_event_id
JOIN svo_triples e2 ON ec.effect_event_id = e2.id
WHERE e1.chapter = 5;
```

**SVO vs Intent JSON 对比**：

| 维度 | v6.0 Intent JSON | v7.0 SVO 三元组 |
|------|-----------------|-----------------|
| 粒度 | 章节级 | **句子级** |
| 标注方式 | 手动编写 | **LLM 自动抽取 + 人工校准** |
| 覆盖度 | 作者声明的关键 Intent | **所有事件全覆盖** |
| 叙事功能 | structural_beat (1个) | **narrative_function (6种)** |
| 因果追踪 | 手动声明 causal_link | **自动检测因果链** |
| 开销 | 每章 5-10min 手动标注 | 每章 ~30s LLM 自动抽取 |

#### ER 模型（v7.0 扩展）

```
┌──────────┐         ┌──────────────┐
│  Entity  │────────▶│  Edge (时序)  │
│ (7种类型) │         │ (关系随时间变) │
└──────────┘         └──────────────┘
     │                     │
     │    🆕 v7.0 新增     │
     ▼                     ▼
┌──────────────┐  ┌──────────────────┐  ┌────────────────┐
│Timeline Event│  │Foreshadowing Graph│  │ EmotionalArc   │
└──────────────┘  └────────────────────┘  └────────────────┘
     │
     ▼
┌──────────────────┐
│ Event Causality  │
└──────────────────┘
     │
     ▼
┌──────────────────────────────┐  ← 🆕 v7.0 新增
│ 🆕 SVO 三元组层               │
│ (Subject, Verb, Object)       │
│ + narrative_function          │
│ + auto_extracted              │
│ → STORYTELLER 论文灵感        │
└──────────────────────────────┘
```

#### 核心查询能力

v7.0 在 v6.0 基础上新增：🆕 **SVO 因果链追溯**（"第3章主角获得神秘信件→第5章前往仓库→第8章发现真相"全链路追踪）。

#### 核心查询能力

| 能力 | 方法 | 用途 | v5.0 新增 |
|------|------|------|:---:|
| BFS 关系遍历 | `query_relationship(entity, depth)` | "主角和反派的关联路径" | — |
| 硬规则一致性校验 | `check_consistency(text, ch)` | 死亡角色复活、未来物品、势力矛盾 | — |
| 语义矛盾检测 | `semantic_contradiction_check(text, ch, intent)` | 角色声明"离开"但仍在原场景 | — |
| 🆕 **空间连续性校验** | `check_spatial_continuity(ch)` | 角色A从北京→上海，中间缺位移事件 | ✅ |
| 🆕 **因果断裂检测** | `check_causal_chain(event_id)` | 杀死反派后反派又出现→标记 CAUSAL_BREAK | ✅ |
| 影响分析 | `impact_analysis(entity_id)` | 修改某个角色设定会影响多少章节 | — |
| 上下文提取 | `get_relevant_context(text, ch)` | S3 评审时将相关设定注入 LLM 上下文 | — |
| 意图驱动分析 | `intent_aware_review(text, ch, intent)` | "本章意图埋设F005"→针对性检查 | — |

#### 时序边设计

```sql
-- v5.0 edges 表升级
ALTER TABLE edges ADD COLUMN valid_from_ch INTEGER;      -- 关系生效章节
ALTER TABLE edges ADD COLUMN valid_until_ch INTEGER;     -- 关系结束章节 (NULL=至今)
ALTER TABLE edges ADD COLUMN status TEXT DEFAULT 'active'; -- active/ended/contradicted

-- 查询示例: "第5章时主角和反派是什么关系？"
SELECT relation_type FROM edges 
WHERE source_id = 'ENT_CHAR_001' 
  AND target_id = 'ENT_CHAR_002'
  AND valid_from_ch <= 5 
  AND (valid_until_ch IS NULL OR valid_until_ch >= 5);
```

#### 🆕 事件因果表

```sql
CREATE TABLE event_causality (
    id TEXT PRIMARY KEY,                              -- CAUSAL_001
    cause_event_id TEXT REFERENCES entities(id),       -- 原因事件
    effect_event_id TEXT REFERENCES entities(id),      -- 结果事件
    chapter_latent INTEGER,                            -- 潜伏章节数
    causality_type TEXT CHECK(causality_type IN       -- 因果类型
        ('triggers', 'leads_to', 'resolves', 'contradicts', 'foreshadows')),
    confidence REAL DEFAULT 0.5,
    detected_by TEXT DEFAULT 'manual'                 -- manual / LLM / rule
);
```

#### Intent 机制（v5.0 进化：因果追踪式）

```json
// outline/chapter_plans/ch05_intent.json (v5.0)
{
  "chapter": 5,
  "structural_beat": "fun_and_games",       // 🆕 对应叙事节拍
  "intents": [
    {
      "type": "foreshadow_plant",
      "id": "F005",
      "detail": "埋设神秘信件来源线索",
      "causal_link": {                      // 🆕 因果追踪
        "triggered_by": "F003",
        "expected_payoff": "F008",
        "latent_chapters": 3
      }
    }
  ],
  "causal_chain": [                         // 🆕 事件因果链
    {"cause": "E003_获得神秘信件", "effect": "E005_前往废弃仓库", "type": "leads_to"}
  ],
  "constraints": [
    "本章主角不能离开城市（为第7章埋伏笔）",
    "本章不引入新角色"
  ]
}
```

### 4.3b 🆕 M2b — 语义记忆层 (Semantic Memory / AriGraph 灵感)

#### 设计动机

当前 NovelGraph 精确记录"第3章角色A打脸了恶霸B"——这是**情景记忆（Episodic Memory）**。但它无法回答"角色A倾向于在什么情境下、用什么方式打脸"——这需要**语义记忆（Semantic Memory）**，即从具体事件中归纳出的**模式级知识**。

AriGraph 论文提出构建"情景记忆 + 语义记忆"双记忆系统。语义记忆作为事实记忆之上的**概念归纳层**，让 AI 在 S1 引导和 S3 评审时，能基于角色的**行为模式**而非仅仅**设定事实**来提供建议。

#### 概念图 Schema

```sql
-- 🆕 v7.0 concept_graph 表
CREATE TABLE concept_graph (
    id TEXT PRIMARY KEY,                              -- CONCEPT_001
    concept_type TEXT CHECK(concept_type IN           -- 概念类型
        ('behavior_pattern',    -- 行为模式: "主角倾向于当众揭露阴谋"
         'relationship_dynamic',-- 关系动态: "A和B的冲突总在第三者介入时升级"
         'narrative_strategy',  -- 叙事策略: "作者偏爱延迟满足式爽点释放"
         'thematic_motif',      -- 主题母题: "身份反转"
         'style_habit')),       -- 风格习惯: "战斗场景中偏爱短句+比喻"
    concept_text TEXT NOT NULL,                       -- 自然语言描述
    supporting_evidence TEXT,                         -- 支持证据: 引用的具体章节事件
    confidence REAL DEFAULT 0.5,
    first_observed_chapter INTEGER,
    last_reinforced_chapter INTEGER,                  -- 最近一次强化该模式的章节
    contradict_count INTEGER DEFAULT 0,               -- 反例计数
    status TEXT DEFAULT 'active'                      -- active/obsolete/contradicted
);

-- 示例数据:
-- CONCEPT_001: behavior_pattern
--   "当对手拥有更高社会地位时，主角倾向于用公开揭露阴谋而非武力来取胜"
--   supporting_evidence: SVO_023(Ch3), SVO_067(Ch7), SVO_145(Ch15)
--   contradict_count: 1 (SVO_098 破例用了武力 → 触发"模式变异"标记)
```

#### 更新策略

```python
# .agents/semantic_memory.py (v7.0 P1)
def update_concepts(chapter_num: int, new_svos: List[SVO]) -> int:
    """每章完成后，对比新 SVOs 与现有概念图：
    1. 找到被强化的概念 → 更新 last_reinforced_chapter
    2. 找到被反例挑战的概念 → 增加 contradict_count
    3. 检测到新模式 → 创建候选概念 (confidence=0.3)，人工确认后提升
    """
```

**开销**：每章额外 1 次 LLM 调用（~15s），归纳已有的 50+ 个 SVO 三元组。

---

### 4.4 M3 — 记忆系统（v7.0：叙事结构索引增强）

#### 检索管道升级

v6.0 在两段式检索（向量 + BM25）基础上增加第三段：

```
ChromaDB 粗排 (BGE-M3 嵌入, top-20)
    │
    ▼
BM25 稀疏补充 (top-10)
    │
    ▼
🆕 Cross-Encoder ReRanker (BGE-Reranker-v2-m3, top-3)
    │  → 检索精度 +15-30%
    ▼
注入 LLM 上下文
```

#### 🆕 叙事结构索引检索 (Narrative-Indexed Retrieval)

三方审视共识：当前检索基于**语义相似度**——"找与当前文本相似的历史段落"。但创作者需要的往往是**叙事功能相似**——"找一个历史上写过的、处于同一节拍位置的场景"。

v7.0 在 ChromaDB metadata 中增加叙事功能标签，实现双重索引：

```python
# .agents/narrative_index.py (v7.0 P1)
def index_chapter_with_narrative_tags(chapter_text: str, chapter_num: int,
                                       beat: str, emotional_arc: str, pleasure_patterns: list):
    """每章入库时，附加叙事功能 metadata"""
    metadata = {
        "chapter": chapter_num,
        "beat": beat,                          # "fun_and_games" / "dark_night_of_soul" / ...
        "beat_position": compute_beat_progress(chapter_num, total_chapters),
        "emotional_arc": emotional_arc,        # "压抑上升" / "释放" / "余韵"
        "pleasure_patterns": pleasure_patterns, # ["slap_face", "treasure_obtain"]
        "narrative_function": classify_function(chapter_text),  # LLM 分类
    }
    chroma_client.add(documents=[chapter_text], metadatas=[metadata])

def retrieve_by_narrative_need(need: str, k: int = 3) -> List[str]:
    """示例:
    need = "我现在需要一个'假胜利'节拍的场景，主角以为赢了但其实踩进了陷阱"
    → 返回历史上所有 beat='fake_victory' 或 narrative_function='deceptive_win' 的段落
    """
    # 第一阶段: narrative filter (metadata 精准筛选)
    # 第二阶段: semantic re-rank (ReRanker 语义精排)
```

**与纯语义检索的对比**：

| 检索方式 | 查询 | 结果 |
|---------|------|------|
| 纯语义 | "假胜利" | 可能返回"角色真的赢了"的段落（语义混淆） |
| 🆕 叙事结构索引 | beat=fake_victory | **精准**返回历史中所有"假胜利"节拍的成功写法 |

#### 五层记忆架构（v7.0 扩展）

| 层级 | 机制 | 技术 | v7.0 升级 | 检索优先级 |
|:---:|------|------|------|:---:|
| **L1** | 实时上下文 | ChromaDB + ReRanker + 🆕叙事结构索引 | 双重索引 | 低（最近 5 章） |
| **L2** | 编译期 Wiki | Markdown 摘要 + (P2)ReIO 动态压缩 | 🔄 StoryWriter ReIO 替代 RAPTOR | 中（阶段性快照） |
| **L3a** | 🆕 语义记忆 | 概念图 (AriGraph 灵感) | 🆕 模式级归纳 | 中（跨章联想） |
| **L3b** | 事实记忆 | **NovelGraph 时序图 + SVO 三元组 + SQLite** | 🆕 SVO 层 | **最高（权威源）** |
| **L4** | 关系图谱 | Mermaid 可视化 | — | 中（可视化） |


