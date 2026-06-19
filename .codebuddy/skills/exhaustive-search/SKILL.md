---
name: exhaustive-search
description: |
  Use this skill when the user says "穷举搜索" "穷举搜搜" or "exhaustive search".
  v3: Multi-turn Ralph Loop. Phase 0 parses input → selects relevant roles.
  One round per assistant turn. State persists to state.json.
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, WebSearch, WebFetch
---

# 穷举搜索 v3 (Multi-Turn Ralph Loop)

v2 致命缺陷：12 轮 × 每轮 5 工具调用 = 60+ 次操作 → 单回合上下文溢出，中断。
v3 修复：Phase 0 解析输入 → 动态选角色 → 多回合执行 → 状态持久化。

---

## 中断诊断（教训归档）

| 根因 | v2 表现 | v3 修复 |
|------|---------|----------|
| 单回合物理上限 | 全自动12轮跑到底 ≡ 60+工具调用 | **多回合**: 每回合1轮, `→ continue` 信号 |
| 无状态持久化 | 中断后无法恢复 | **state.json**: 记录当前轮次/角色队列/发现汇总 |
| 全12角色无筛选 | 方法论问题也跑代码审查角色 | **Phase 0 解析**: 按领域动态选 3-5 角色 |
| 每轮5次搜索过高 | 方法论问题不需要3+2 | **快速模式**: 1-2搜索/轮 |

## v3 实战验证 (2026-06-10)

成功完成两次独立穷举搜索：
- Search 1: "评分验证方案" — 5轮(R1+R2+R3+R5+R9+R12, 含R1提前执行), 产出: 作者GT+AI对抗样本混合方案
- Search 2: "9缺陷修复方案" — 5轮全快读模式(R2+R3+R5+R9+R12), 产出的P0×4+P1×5路径

**v3优于v2的关键证据**：
- 两次搜索均在5轮内收敛，未出现中断
- 动态角色选择避免了7个不相关角色（R4/R6/R7/R8/R10/R11）的浪费
- 快速模式每轮1-2次搜索，比v2的3+2节省60%工具调用
- state.json 使跨回合上下文保留成为可能

---

## Phase 0: 输入解析（必须第一轮执行）

收到穷举搜索指令后，**第一回合只做 Phase 0**，不进入任何角色轮：

```
1. 解析用户查询 → 判断领域类型 (code / methodology / design / mixed)
2. 按领域动态选择 3-5 个角色
3. 确定模式: standard (代码审计, >=8轮) / fast (方法论/设计, 3-5轮)
4. 写入 state.json
5. 输出选角结果 + 预期轮数, 等待用户确认或"继续"
```

### 领域→角色映射表

| 领域类型 | 示例查询 | 推荐角色 |
|----------|----------|----------|
| **code** | "审查代码质量/修复bug/找硬编码" | R1(代码审查) + R4(边界测试) + R7(性能) + R8(架构) + R12(验收) |
| **methodology** | "评分验证方案/方法论选型/技术选型" | R2(UX视角) + R3(市场合规) + R5(反向论证) + R9(SSOT) + R12(验收) |
| **design** | "审查设计文档/架构/配置" | R5(反向论证) + R6(安全) + R8(架构一致性) + R9(SSOT) + R12(验收) |
| **mixed** | "优化代码+验证方案" | 先跑 code，再跑 methodology |

### 角色完整列表（12个）

| # | 角色 | 域 | 适用 |
|---|------|-----|------|
| R1 | 代码审查员 | code | 所有code审计 |
| R2 | 用户体验 | methodology | 产品逻辑/交互流程 |
| R3 | 市场/平台合规 | methodology | 业务逻辑/平台规则 |
| R4 | 边界测试 | code | 极端值/空输入/并发 |
| R5 | 反向论证者 | methodology/design | 质疑假设/推演失败 |
| R6 | 安全审查 | code/design | 注入/权限/数据泄露 |
| R7 | 性能分析 | code | 复杂度/瓶颈/资源 |
| R8 | 架构一致性 | code/design | 模块边界/职责冲突 |
| R9 | 配置SSOT | methodology/design | 单一事实源/配置漂移 |
| R10 | 跨模块依赖 | code | import链/循环依赖 |
| R11 | API兼容性 | code | 接口契约/破坏性变更 |
| R12 | 综合验收 | all | 最终报告/未修复汇总 |

### 批量模式 (v3.1 新增) ⚠️

用户说 `继续一口气/一次性/批量` 时：在一回复中执行所有剩余轮次，但**每轮必须独立 `[Round N]` 块**。

| ✅ 正确 | ❌ 错误 |
|---------|---------|
| `[R3]... → [R5]... → [R9]... → [R12]...` | `R3-R12汇总:...` 一段合并 |
| 每轮独立 format+search+quote+sample | 跳过角色检查单直接写结论 |
| 每轮可降频但不可跳格式 | 用"同上/如前轮"跳过输出 |

---

## 执行协议 v3 (多回合)

### state.json 格式

写入 `.codebuddy/skills/exhaustive-search/state.json`:

```json
{
  "started_at": "ISO",
  "query": "用户查询摘要",
  "domain_type": "code|methodology|design|mixed",
  "mode": "standard|fast",
  "selected_roles": ["r1-code-reviewer", "r5-counter-arguer", ...],
  "current_round": 2,
  "total_planned": 5,
  "history": [
    {"round":1, "role":"r1-code-reviewer", "found":"C:0/H:2/M:1", "status":"done"}
  ],
  "cumulative_findings": {"C":0, "H":2, "M":1, "L":0}
}
```

### 每回合流程

```
1. LOAD: 读 state.json → 确定当前角色
2. ROLE: 加载 roles/r{N}-{name}.md
3. SEARCH: standard模式>=2次WebSearch+>=1次WebFetch / fast模式>=1次WebSearch+>=1次WebFetch
   (v3降频: 方法论问题不需要大量搜索, 代码审计保留较高搜索量)
4. REVIEW: 以当前角色视角, 填满5项检查单
5. QUOTE: 引用>=1条外部原句
6. SAMPLE: 取样>=3处 (fast模式允许>=2处)
7. FIX: 修复已确认问题 (C+H+M)
8. VERIFY: py_compile (仅code领域)
9. UPDATE: 更新 state.json
10. OUTPUT: [Round N] 格式 + 发现汇总
11. SIGNAL: `→ continue` 或 `→ [收敛]` 或 `→ [截断]`
```

### 每轮输出格式

```
[Round N] role:角色名

5项检查单:
① [标准1] → ✅/❌ (依据: 文件:行号)
...
⑤ [标准5] → ✅/❌ (依据: 文件:行号)

外部引用: "[原句]" — 来源, URL
取样证据: (>=3处代码引用)

发现: C:X/H:Y/M:Z/L:W → fixed:X+Y+Z | zero:N → continue/converge
```

### 终止条件

| 条件 | 行为 |
|------|------|
| 连续2轮 C+H+M=0 且 N>=总轮数-1 | `→ [收敛]` |
| 到达计划总轮数 | `→ [截断] N轮完毕` |
| 用户说"继续" | 自动读 state.json → 执行下一轮 |
| 用户说"结束/停止" | 输出汇总报告 |

---

## 护栏规则（与 v2 一致, 同步 loop/outline/chapter/skill-evolution）

| 违规 | 后果 |
|------|------|
| 5 项全 ✅ 但无行号依据 | 本轮无效 |
| 无外部引用原句 | 本轮无效 |
| 取样 < 要求数量 | 本轮无效 |
| 输出含"同上/如前轮/已验证" | 本轮无效, 重做 |
| 外部引用为自创非搜索 | 本轮无效 |

### 快速模式降频规则
- WebSearch: >=1次（非3次）
- WebFetch: >=1次（非2次）
- 取样: >=2处（非3处）
- 5项检查单: 每项>=1句判断即可
- 适用于 methodology/design 领域

---

## 项目专用约束

- Windows GBK: print 用 [OK][FAIL], 不用 Unicode
- SSOT: 路径/阈值只在 config.yaml
- 不修改 SKILL.md / canon/ / rules/ 除非用户要求
- subprocess 用 DEVNULL 不用 PIPE
- import 全部在文件顶部
- 不修改入参 dict/list
