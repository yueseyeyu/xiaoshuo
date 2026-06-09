---
name: chapter-evolution
description: |
  Use this skill when the user says "进化细纲" "进化细钢" "章纲进化" "章节进化".
  Execute a narrative-consciousness Ralph Loop: 8-role rotation for chapter-level pacing/hook/density/flow review.
  Techniques from 马良写作(pacing+hook design) + 网文俱乐部(chapter structure).
  **每轮必须产出不可伪装的证据：填满5项检查单 + 引用外部来源原句 + 取样至少3处。缺失任一项=本轮无效。**
allowed-tools: Read, Write, Edit, Grep, Glob, WebSearch, WebFetch
metadata:
  version: "1.1"
---

# 细纲/章纲穷举进化 v1.1

独立的叙事 Ralph Loop 协议，专为细纲（章/场景级）叙事审查设计的 8 轮角色轮换。
**致命反模式**: 凭记忆输出 `found:0` → 假收敛。修复: 每轮必须产出不可伪装的 3 项证据。

**粗纲 vs 细纲**: 细纲查"这一章读者会翻页吗？"（钩子/节奏/爽点/衔接）。粗纲查"这个故事能成立吗？"，由 `rough-outline-evolution` Skill 负责。

## 术语定义

| 缩写 | 含义 | 说明 |
|:---:|------|------|
| C | Critical | 根本性叙事错误，交付物不可用 → 必须立即修复 |
| H | High | 重大叙事缺陷 → 本轮必须修复 |
| M | Major | 违反网文最佳实践 → 交付前修复 |
| L | Low | 轻微改进 → 可选 |
| zero | 零发现计数器 | C+H+M=0时+1；>0时归零 |
| N | 当前轮次 | R1-R9，达到R9为截断 |

## 前提条件

执行前必须确认以下输入存在且非空：
- `outline/chapter_plans/` — 章纲文件目录（必须有实质内容）
- `outline/summary.md` — 故事概要（可选但建议存在）

**空输入处理**: 若章纲为空，Skill 报 [BLOCK] 并提示"请先生成章纲内容，再执行进化审查"。

## 每轮输出格式 (MANDATORY)

```
[Round N] role:角色名

5项检查单:
① [标准1] → ✅/❌ (依据: 章纲:第X章-Y节 — 具体引用)
② [标准2] → ✅/❌ (依据: ...)
...
外部引用: "[原句]" — 来源: [名称], [年份]
取样证据:
  - 章纲:第X章-Y节 — "[原文]"
  ...
发现: C:X/H:Y/M:Z/L:W → fixed:X+Y+Z | zero:N → continue/converge
```

**没有 role/source/samples 三项 = 本轮无效, 不计数**

## 每轮必须产出的证据（缺一即本轮无效）

```
① 5项检查单: 每项 ✅ 或 ❌ + 依据(章纲第X章-Y节)
② 外部来源: >=2次 WebSearch + >=1次 WebFetch（至少1条原句，WebFetch失败降级为WebSearch snippet，标 [降级引用]）
③ 取样证据: 从细纲中引用至少 3 处具体章节号/事件/指标
```

## 9 轮角色轮换

**角色定义 → `roles/` 目录**（每轮按需加载）

角色轮换顺序: 章节钩子→节奏曲线→场景因果→爽点密度→弃书预警→信息释放→语言质感→对话描写比→章末钩子强度

## 执行模式：全自动

9轮连续执行，不暂停。收敛或截断后输出完整报告。

## 执行流程

```
0. ROLE-LOAD: 读取 roles/r{N}-{name}.md
1. READ: 读取细纲/章纲文件 (R2+从零重读)
1.5 SAMPLE-DB: 读取 data/analysis/末世/synthesis/rhythm_benchmark.md（genre_synthesizer 自动生成），检查生成时间戳。若 >7 天，提示「基准数据已过期，建议运行 analyze_all.py」
2. REVIEW: 填满5项检查单 (每项✅/❌+依据)
3. SEARCH: >=2次 WebSearch + >=1次 WebFetch (叙事域>=2+1足够)
   - WebFetch超时/失败: 降级为WebSearch snippet替代，标记 [降级引用]，不阻塞轮次
4. QUOTE: 至少1条外部来源原句（WebFetch失败则用WebSearch snippet，标 [降级引用]）
5. SAMPLE: 从细纲中取样≥3处 (章节号+具体事件)
6. SAMPLE-REF: 将当前章指标与基准库对比，产出 [REF] 偏离标记
7. FIX: 修复本轮 C+H+M 问题
8. OUTPUT: [Round N] 格式（见上方模板）
9. zero: C+H+M>0→zero=0; C+H+M=0→zero+=1
10. EXIT: zero>=2 且 N>=9→[收敛]; N>=9且zero<2→[截断]
```

## 护栏规则（防偷懒 v1.1 + Context Isolation）

<!-- ⚠️ 本表与 loop-evolution/SKILL.md、rough-outline-evolution/SKILL.md、skill-evolution/SKILL.md 护栏规则保持同步。
     修改任一处时必须同步修改另三处（project.mdc rule 32）。 -->

| 违规 | 后果 | 恢复指令 |
|------|------|------|
| 5项全✅但无依据 | 本轮无效 | 补依据后重做 |
| 无外部引用原句 | 本轮无效 | 补搜索+引用后重做 |
| 取样<3处 | 本轮无效 | 补取样后重做 |
| R9之前宣布收敛 | 无效 | 继续下一轮，至少跑满9轮 |
| 搜索词与最近3轮完全相同 | 本轮无效 | 换搜索词后重做 |
| 外部引用为自创 | 本轮无效 | 真实搜索后重做 |
| 跳过搜索直接found:0 | 本轮无效 | 执行搜索后重做 |
| 取样证据≥3条全旧 | 本轮无效(允许1-2条重复) | 补新取样后重做 |
| 输出含"跳过/同上/前轮已验证" | 本轮无效,重做 | 从零重做 |
| 检查单≥4项引用与前轮相同 | 本轮无效 | 扩大取样范围后重做 |

**Context Isolation**: 每轮从零重读细纲；取样≥2处与前轮不同(R6-R8:≥1处)；不引用前轮结果

## 项目约束
- 正文100%手写，只审查细纲/章纲
- 不修改 canon/ 设定文件除非用户要求
- 细纲修改通过对话协商，不直接写入文件除非作者确认

## 终止条件
zero>=2 且 N>=9 → [收敛] | N>=9且zero<2 → [截断] | 章纲为空 → [BLOCK]
