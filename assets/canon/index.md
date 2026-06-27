# Canon 交叉引用索引

> 由 LLM 维护 · 每次新增小说入库或拆书后更新
> 最后更新: 2026-06-27

---

## 文件速览

| 文件 | 内容 | 状态 |
|------|------|:---:|
| [world.md](world.md) | 世界观总纲：时代背景、核心矛盾、权力来源、场景设计、社会规则、模拟器、天选者、黄金三章 | 已填写 |
| [characters.md](characters.md) | 角色设定 | 已提取（待审核） |
| [timeline.md](timeline.md) | 时间线：事件年表、章节-时间映射 | 已提取（待审核） |
| [rules.md](rules.md) | 规则体系：世界观约束、能力边界、一致性规则 | 已提取（待审核） |
| [emotional_arcs.md](emotional_arcs.md) | 情感弧线：主角情绪曲线、关键情感节点 | 已提取（待审核） |
| [foreshadowing.md](foreshadowing.md) | 伏笔追踪：已埋 → 已揭示 → 待回收 | 已提取（待审核） |
| [subplot_board.md](subplot_board.md) | 支线看板：子线进度、角色支线、交叉点 | 已提取（待审核） |

---

## 关键概念 → 所在文件

### 世界观核心概念（world.md）

| 概念 | 定义位置 | 关联文件 |
|------|---------|---------|
| 侵蚀源 | world.md §时代背景 | rules.md（待填写） |
| 进化链（气体→植物→昆虫→动物→人类） | world.md §时代背景 | timeline.md（待填写） |
| 核心矛盾（断绝vs共存 / 进化者vs失控者 / 人性vs进化） | world.md §核心矛盾 | emotional_arcs.md（待填写） |
| 本能驾驭（进化=力量+侵蚀） | world.md §权力来源 | rules.md（待填写） |
| 柳树妖 | world.md §权力来源 | characters.md（待填写） |
| 模拟器（面板式推演，时间限制+层级限制） | world.md §模拟器 | rules.md（待填写） |
| 天选者（源质为零，无法自然进化，猎杀夺取） | world.md §天选者与猎杀法则 | characters.md（待填写） |
| 安全区 | world.md §社会规则 | — |
| 黄金三章（狗咬→柳树异常→模拟死亡→6天倒计时） | world.md §黄金三章 | timeline.md（待填写） |

### 未解之谜（world.md）

| # | 谜面 | 揭露时机 | 关联伏笔 |
|:---:|------|:---:|:---:|
| 1 | 天选者悖论：进化失败还是免疫细胞？ | 后期 | foreshadowing.md（待填写） |
| 2 | 推演极限：新变量让结果跑偏 | 前期末 | foreshadowing.md（待填写） |
| 3 | 力量的代价：断源=断力 | 后期 | foreshadowing.md（待填写） |

---

## 交叉引用矩阵

```
world.md ──(角色定义)──▶ characters.md
world.md ──(事件时序)──▶ timeline.md
world.md ──(规则约束)──▶ rules.md
world.md ──(矛盾驱动)──▶ emotional_arcs.md
world.md ──(谜面埋设)──▶ foreshadowing.md
world.md ──(支线来源)──▶ subplot_board.md

characters.md ──(角色弧线)──▶ emotional_arcs.md
characters.md ──(角色事件)──▶ timeline.md
characters.md ──(角色支线)──▶ subplot_board.md

timeline.md ──(事件规则)──▶ rules.md
timeline.md ──(伏笔触发)──▶ foreshadowing.md

rules.md ──(规则违反)──▶ foreshadowing.md
```

---

## 填充状态（v7.6 更新）

| 优先级 | 文件 | 状态 |
|:---:|------|:---:|
| 1 | characters.md | ✅ 已提取（2026-06-27） |
| 2 | rules.md | ✅ 已提取（2026-06-27） |
| 3 | timeline.md | ✅ 已提取（2026-06-27） |
| 4 | emotional_arcs.md | ✅ 已提取（2026-06-27） |
| 5 | foreshadowing.md | ✅ 已提取（2026-06-27） |
| 6 | subplot_board.md | ✅ 已提取（2026-06-27） |

> v7.6: 所有 canon 文件已通过 `canon_extractor.py` 从 world.md 自动提取。
> 后续使用 `consistency_checker.py` 进行大纲/正文一致性检查。

---

## 更新日志

| 日期 | 变更 | 触发 |
|------|------|------|
| 2026-06-25 | 初始创建 | LLMWiki 知识编译思想落地 |