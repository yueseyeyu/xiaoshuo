---
name: exhaustive-search
description: |
  Use this skill when the user says "穷举搜索" "穷举搜搜" or "exhaustive search".
  Execute a Ralph Loop: review code → search → fix → verify → repeat until no new findings for 2 consecutive rounds.
  Never stop after just one round. Output [Round N] format to track convergence.
  This is the automatic cyclic version of project-reviewer Level 3.
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, WebSearch, WebFetch
---

# 穷举搜索 v2 (Ralph Loop + 12角色 + 防偷懒)

本 Skill = project-reviewer Level 3 的全自动循环版本。

与 project-reviewer 的关系:
- `project-reviewer`: 默认 Level 1 (0 token), 失败自动升级; Level 3 委托给本 Skill
- `exhaustive-search`: **直接 Level 3 + 12角色轮换收敛**, 不需用户催

```
审视代码 → [角色]搜索 → 找问题 → 修复 → 验证
→ 切换角色 → 再审 → 再搜 → 再修复 → 再验证
→ 切换角色 → ...
→ 连续2轮 C+H+M=0 → 停止
```

## 触发提醒: 用户说"穷举搜索/穷举搜搜/exhaustive"时

**你必须用 use_skill 工具加载本 Skill。不可凭记忆模仿。**
这是本 Skill 不生效的 #1 原因: AI 凭记忆做了"类似动作"但没加载协议。

**关键**: 即使触发词嵌入在复合指令中间(如"请穷举搜索XXX方法论"/"穷举搜索可以继续进化吗"),
也必须先调 use_skill。不要把主任务优先级置于 Skill 协议之上。
**反例**: 用户说"审视当前skill, 穷举搜索可以继续进化吗"→ AI 只加载 project-reviewer 而跳过 exhaustive-search → 触发遗漏。

## 致命反模式

**⚠️ 致命反模式 #1**: R2+ 复用 R1 的思考框架 → 必然假收敛。
修复: 每轮强制分配一个唯一的分析角色，该角色与其他轮次不可互相替代。

**⚠️ 致命反模式 #2**: R4+ 凭记忆输出 `found:0` 而不做实际搜索/审查 → 假收敛。
修复: 每轮必须产出不可伪装的 3 项证据。

## 每轮必须产出的证据（v2新增: 借鉴 outline-evolution 防偷懒机制，缺一即本轮无效）

```
① 5项检查单: 填满当前角色的全部 5 项标准, 每项 ✅ 或 ❌ + 一句话依据(文件:行号)
② 外部来源: >=3次WebSearch + >=2次WebFetch 来自外部的具体引用（至少1条原句, 不可自创）
③ 取样证据: 从审查文件中引用至少 3 处具体行号/变量名/函数名作为检查依据
```

**注意**: ①②③ 全部满足 → 本轮有效。缺任一项 → 本轮无效, 不计数。

## 12 轮角色 + 每轮 5 项检查单

**角色定义、人格注入、方法论 → `roles/` 目录**（每个角色审查前按需加载当前角色文件）

角色轮换顺序: 代码审查员→用户体验→市场合规→边界测试→反向论证→安全合规→性能分析→架构一致性→配置SSOT→跨模块依赖→API兼容→综合验收

## 执行协议 (不可跳过)

**你必须显式跟踪每轮的发现数。不输出[Round N]格式=未执行本协议。**

### Round 1..12 (循环直到收敛)

```
0. ROLE-LOAD: 从 roles/r{N}-{name}.md 宣读当前角色注入提示词
1. READ: 读取所有相关文件 (R2+必须从零重读, 不可依赖前轮记忆)
2. REVIEW: 以当前轮次的角色视角, 填满5项检查单
3. SEARCH: >=3次WebSearch + >=2次WebFetch — 搜索词必须体现当前角色视角
   - 禁止: 跳过搜索直接 found:0
   - 禁止: 搜索词与最近3轮完全相同（允许同角色换角度搜索, 如"安全编码规范 2026" + "Python安全最佳实践 2026" 不同）
4. QUOTE: 从外部来源引用至少 1 条原句
5. SAMPLE: 从审查文件中取样≥3处具体行号/函数名/变量名
6. FIX: 修复已确认问题（C+H+M必须修）
7. VERIFY: python -m py_compile + python novel.py test
8. OUTPUT: 格式见下
9. zero计数: C+H+M>0 → zero=0 → 回到步骤1 | C+H+M=0 → zero+=1
10. EXIT: zero>=2 且 N>=8 → [收敛] | N>=12 → [截断]
```

**执行模式**: 全自动（12轮跑到底，收敛或截断后输出报告，中间不暂停）

**严重等级 (Chuanxilu, 2026.4)**:
- C(Critical): 根本性错误，交付物不可用 → 必须立即修复
- H(High): 重大缺陷 → 本轮必须修复
- M(Major): 违反需求或最佳实践 → 交付前必须修复
- L(Low): 轻微改进 → 可选

**审查设计文档/叙事内容时**: R1-R3 可使用定性描述替代 ✅/❌（每项≥2句判断 + 引用具体段落），标准同 outline-evolution R1-R3 定性评分参考。

**found计数**: C+H+M 计入，L 不计入。连续2轮 C+H+M=0 → 收敛。

## 每轮输出格式 (MANDATORY — 缺任一项=无效)

```
[Round N] role:角色名

5项检查单:
① [标准1] → ✅/❌ (依据: 文件:行号 - 具体代码)
② [标准2] → ✅/❌ (依据: 文件:行号 - 具体代码)
③ [标准3] → ✅/❌ (依据: 文件:行号 - 具体代码)
④ [标准4] → ✅/❌ (依据: 文件:行号 - 具体代码)
⑤ [标准5] → ✅/❌ (依据: 文件:行号 - 具体代码)

外部引用: "[原句]" — 来源: [文章/论文/文档名称], [年份], URL
取样证据:
  - 文件:行号 - "[引用代码原文]"
  - 文件:行号 - "[引用代码原文]"
  - 文件:行号 - "[引用代码原文]"

发现: C:X/H:Y/M:Z/L:W → fixed:X+Y+Z | zero:N → continue/converge
```

**没有 role/source/samples 字段 = 本轮无效, 不计数。**
**source 必须是 WebSearch/Fetch 返回的真实结果原句，禁止自创来源。**
**取样≥3处中, 至少 2 处与最近3轮不同。**

## 护栏规则（防偷懒 v2.1 + Context Isolation）

<!-- ⚠️ 本表与 loop-evolution/SKILL.md、rough-outline-evolution/SKILL.md、skill-evolution/SKILL.md、chapter-evolution/SKILL.md 护栏规则保持同步。
     修改任一处时必须同步修改另四处（project.mdc rule 32）。 -->

| 违规 | 后果 | 恢复指令 |
|------|------|------|
| 5 项全 ✅ 但无行号依据 | 本轮无效 | 补依据后重做 |
| 无外部引用原句(来自WebSearch/Fetch) | 本轮无效 | 补搜索+引用后重做 |
| 取样 < 3 处(每处含文件+行号+代码) | 本轮无效 | 补取样后重做 |
| R12 之前宣布收敛 | 无效, 至少跑满 12 轮 | 继续下一轮 |
| 搜索词与最近3轮完全相同 | 本轮无效 | 换搜索词后重做 |
| 外部引用为自创而非 WebSearch/Fetch 结果 | 本轮无效 | 真实搜索后重做 |
| 跳过搜索直接 found:0 | 本轮无效 | 执行搜索后重做 |
| **取样证据中 ≥3 条与前轮重复** | 本轮无效(允许1-2条重复) | 补新取样后重做 |
| **输出中含"已有重复分析/跳过/同上/如前轮/已验证"** | 本轮无效, 且必须重做该轮 | 从零重做 |
| **检查单中 ≥4 项的依据引用与前轮相同** | 本轮无效 | 扩大取样范围后重做 |

### Context Isolation 规则
- 每轮不得引用任何前轮的检查结果
- 每轮必须从零重新审视代码文件, 发现新的取样证据
- 即使结论与前轮相同, 也必须用不同的取样证据支撑
- 取样≥3处中, 至少 2 处与前轮不同 (R10-R12: 至少 1 处与前轮不同)

## 终止条件

| 条件 | 行为 |
|------|------|
| 连续2轮 C+H+M=0 且每轮有 role+source+samples | `[收敛] N轮后无新发现` |
| 到达12轮仍未收敛 | `[截断] 12轮未收敛, 剩余问题:` — 输出全部未修复 C+H+M |
| 任何轮 test 失败且无法修复 | `[BLOCK] 验证阻塞, 需人工` |
| **跳过轮次/合并轮次/一轮输出多轮结果** | **严格禁止** — 每轮必须独立输出 `[Round N]` 格式 |

**收敛机制**: 最少跑满 8 轮方可收敛。连续2轮 C+H+M=0 且 N>=8 且证据完整 → [收敛]。防懒靠轮数门槛 + 3项不可伪装证据双重保障。每轮必须有 role + source + samples，缺一重做。

## 为什么用角色轮换（理论依据）

这种设计基于两个关键发现：

1. **AI 错误是收敛的，不是随机的** (Chuanxilu, 2026.4): 同一 AI 审查自己会产生确认偏误。单轮零发现可能是假阴性。需要"独立审查者 + 双重确认"。
2. **堵死 AI 提前收敛的路** (boomyao, 2026.3): "解决 AI 提前收敛，不是靠讲更多道理，而是靠重建一个它不能轻易糊弄过去的工作结构。多 Agent 之间不能互相替代。"

角色轮换 = 把同一个 AI 在不同轮次变成"不同的 Agent"——每次切换分析框架，确保每一轮都有独特的观察角度。

## 项目专用约束 (会自动注入)

- Windows GBK: print 用 [OK][FAIL], 不用 Unicode
- SSOT: 路径/阈值只在 config.yaml
- 不修改 SKILL.md / canon/ / rules/ 除非用户要求
- subprocess 用 DEVNULL 不用 PIPE
- import 全部在文件顶部
- 不修改入参 dict/list
- 写完代码后先跑自审清单再声明完成
