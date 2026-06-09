---
name: skill-evolution
description: |
  Use this skill when the user says "进化skill" "skill进化" "进化SKILL" "SKILL进化"
  "skill审视" "skill审查" "优化skill" "审查skill".
  Evolve any SKILL.md toward its optimal form through 8-role rotation:
  purpose alignment, role design, protocol consistency, trigger optimization,
  DRY compliance, edge cases, readability, and completeness review.
  **每轮必须产出不可伪装的证据：填满5项检查单 + 引用外部来源原句 + 取样至少3处。缺失任一项=本轮无效。**
allowed-tools: Read, Write, Edit, Grep, Glob, WebSearch, WebFetch
metadata:
  version: "1.0"
---

# Skill 穷举进化 v1

纯 Ralph Loop，专为 **Skill 文件本身** 设计的 8 轮角色轮换审查。
定位: 审查 `loop-evolution` 覆盖不到的目标 — 任何 SKILL.md 及其 roles/references/CHANGELOG 附属文件。

**与其他 Skill 的关系**:
- `loop-evolution`: 通用域(8角色审查任意文档)，`skill-evolution` 专精 Skill 域(每个角色针对 Skill 设计维度)
- `exhaustive-search`: 代码域(R1-R12含py_compile)，`skill-evolution` 不替代
- `rough-outline-evolution` / `chapter-evolution`: 叙事域，`skill-evolution` 不替代
- **定位**: 审查 Skill 文件的质量、设计、一致性，使其逐步逼近完美

## 致命反模式

**#1**: R2+ 复用 R1 的思考框架 → 必然假收敛。每轮强制分配唯一分析角色。

**#2**: R4+ 凭记忆输出 `found:0` 而不做实际读取/审查 → 假收敛。
修复: 每轮必须产出不可伪装的 3 项证据。

## 审查目标

Skill 是一个目录，至少包含 `SKILL.md`，可选 `roles/`、`references/`、`CHANGELOG.md`。
每轮审查从零读取目标 Skill 的所有文件，然后以当前角色视角填满 5 项检查单。

## 每轮必须产出的证据（缺一即本轮无效）

```
① 5项检查单: 填满当前角色的全部 5 项标准（✅/❌ + 依据:文件:行号）
② 外部来源: >=2次WebSearch + >=1次WebFetch（至少1条原句, 搜索词体现角色视角）
③ 取样证据: 从目标 Skill 文件引用至少 3 处具体行号/段落
```

## 术语定义

| 缩写 | 含义 | 说明 |
|:---:|------|------|
| C | Critical | 根本性错误，交付物不可用 → 必须立即修复 |
| H | High | 重大缺陷 → 本轮修复 |
| M | Major | 违反需求或最佳实践 → 交付前修复 |
| L | Low | 轻微改进 → 可选 |
| zero | 零发现计数器 | C+H+M=0时+1；>0时归零 |

## 8 轮角色轮换

**角色定义、人格注入、5项检查单、方法论 → `roles/` 目录**（每轮审查前加载当前角色文件）

角色轮换顺序: 目的对齐 → 角色设计 → 协议一致性 → 触发词优化 → DRY与继承 → 边缘与安全 → 可读性体验 → 完整性验收

**顺序逻辑**: 先确认 Skill "该做什么"(R1)→再检查"谁来做"(R2)→验证"怎么做"(R3)→确保"能被发现"(R4)→消除"重复造轮子"(R5)→加固"不会坏"(R6)→优化"用得顺"(R7)→最后清点"什么都有"(R8)

## 每轮输出格式 (MANDATORY)

```
[Round N] role:角色名

5项检查单:
① [标准1] → ✅/❌ (依据: 文件:行号 — 具体内容)
② [标准2] → ✅/❌ (依据: ...)
...
外部引用: "[原句]" — 来源: [名称], [年份]
取样证据:
  - 文件:行号 — "[原文]"
  ...
发现: C:X/H:Y/M:Z/L:W → 本轮修复:X+Y+Z | zero:N → continue/converge
```

**没有 role/source/samples = 本轮无效, 不计数**

## 执行协议

```
0. ROLE-LOAD: 读取 roles/r{N}-{name}.md
1. READ: 读取目标 Skill 所有文件 (R2+从零重读)
2. REVIEW: 以当前角色视角填满5项检查单
3. SEARCH: >=2次WebSearch + >=1次WebFetch（搜索词不重复近3轮）
4. QUOTE: 从外部来源引用至少 1 条原句
5. SAMPLE: 从目标 Skill 取样≥3处（文件:行号:内容）
6. FIX: 修复本轮的 C+H+M 问题
7. OUTPUT: [Round N] 格式
8. zero: C+H+M>0→zero=0; C+H+M=0→zero+=1
9. EXIT: zero>=2 且 N>=8→[收敛]; N>=8→[截断]
```

**执行模式**: 全自动（跑到底，不暂停，每轮产出后立即进入下一轮）

## 护栏规则

<!-- ⚠️ 本表与 loop-evolution/SKILL.md、rough-outline-evolution/SKILL.md、chapter-evolution/SKILL.md、exhaustive-search/SKILL.md 护栏规则保持同步。
     修改任一处时必须同步修改另四处（project.mdc rule 32）。 -->

| 违规 | 后果 | 恢复指令 |
|------|------|------|
| 5项全✅但无依据 | 本轮无效 | 补依据后重做 |
| 无外部引用原句 | 本轮无效 | 补搜索+引用后重做 |
| 取样<3处(每处含文件+行号+内容) | 本轮无效 | 补取样后重做 |
| R8之前宣布收敛 | 无效 | 继续下一轮，至少跑满8轮 |
| 搜索词与最近3轮完全相同 | 本轮无效 | 换搜索词后重做 |
| 外部引用为自创 | 本轮无效 | 真实搜索后重做 |
| 跳过搜索直接found:0 | 本轮无效 | 执行搜索后重做 |
| 取样证据≥3条全旧 | 本轮无效(允许1-2条重复) | 补新取样后重做 |
| 输出含"跳过/同上/前轮已验证" | 本轮无效,重做 | 从零重做 |
| 检查单≥4项引用与前轮相同 | 本轮无效 | 扩大取样范围后重做 |

**Context Isolation**: 每轮从零重新审视目标 Skill；取样≥2处与前轮不同(R6-R8:≥1处)；不引用前轮检查结果

## 参考标准

审查依据（按优先级）:
1. Agent Skills 规范 (agentskills.io/specification) — SKILL.md 格式规范
2. Skill 编写最佳实践 (AI全书, 7个顶级Skill案例分析, 2026.4) — 设计模式与反模式
3. SkillGuard 权限框架 (arXiv 2606.03024) — 最小权限/安全设计
4. 项目专用约束 (project.mdc) — 触发词映射/同步规则

详见 `references/skill-spec.md`

## 终止条件
连续2轮 C+H+M=0 → [收敛] | 达到8轮 → [截断] | 目标Skill不存在 → [BLOCK]
