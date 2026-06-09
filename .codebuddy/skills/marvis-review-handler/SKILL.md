---
name: marvis-review-handler
description: 处理 Marvis 审查报告：验证→穷举搜索→修复→回执→归档5步闭环。prompts/pending/ 出现新.md文件时触发。用户说"审查报告/新的审查/处理审查/Marvis报告/有新报告"时加载。严禁跳过Step 2穷举搜索。每步必须有[Step N done]标记。回执写在replies/等Marvis读,CodeBuddy禁止移动回执。
metadata:
  version: "v5"
  author: "项目规则演进"
  updated: "2026-06-08"
---

# Marvis 审查处理 Skill — 三Agent协作闭环

**协作模式**: Marvis(审查者) → User(决策者) → CodeBuddy(实现者)

## 触发条件

`prompts/pending/` 下出现新 `.md` 文件（非 `_plotpilot`/`_intent` 开头，这些是功能提案非Bug审查）

## 执行协议 (5步) — ⚠️ 不可跳过任一步

<!-- v4: 每步完成后必须输出 [Step N done] 标记, 否则禁止进入下一步。
     教训: v2→v3 只修了Step 2→3, Step 4(回执)仍被跳过。v4 全步加锁。 -->

**v4 强制规则: 任何一步未输出完成标记 = 禁止声明"审查处理完成"。**

| Step | 完成标记 | 未标记后果 |
|:---:|------|------|
| 1 | `[Step 1 done]` 验证结果表已输出 | 不得进入 Step 2 |
| 2 | `[Step 2 done]` 包含搜索结果表 | 不得进入 Step 3 (v3) |
| 3 | `[Step 3 done]` 含 py_compile + test | 不得进入 Step 4 |
| 4 | `[Step 4 done]` 回执已写 | 不得进入 Step 5 (v4新增) |
| 5 | `[Step 5 done]` 审查报告 pending→history, 回执在 replies/ | 处理未完成 |

<!-- v5: Step 5 done 仅指 CodeBuddy 移审查报告。回执必须留在 replies/ 等 Marvis 读。 -->

### Step 1: 质疑验证 — 不盲修

拿到审查报告后，**先站在专业角度逐条验证**，不能默认 Marvis 是对的：

| 验证维度 | 方法 |
|---------|------|
| 事实核查 | 读源码确认声称的问题是否真实存在 |
| 归因正确性 | 问题是代码Bug还是设计选择？如 quality_gate 在 genre 之前是故意设计 |
| 误判识别 | Marvis 曾误判 worldbuild 为空命令、detect_genre 不存在 |
| 严重度校准 | Marvis 的 🔴/🟡 分级是否合理？有时 🟡 实际影响更大 |

输出格式：
```
### 验证结果
| # | 声明 | 属实? | 证据/说明 |
|---|------|:---:|------|
| 1 | xxx | ✅ | 代码位置 L123 |
| 2 | yyy | ❌ | 误判: 实际是设计选择 |
```

### Step 2: 穷举搜索 — ⚠️ 强制门（不可跳过）

对验证通过的每一项，**必须**执行穷举搜索。以下是最低强制标准：

| 强制门 | 要求 | 未满足后果 |
|--------|------|-----------|
| 最少搜索次数 | ≥3次 WebSearch + ≥1次 WebFetch | 本轮 Step 2 无效，重做 |
| 必须覆盖域 | 学术论文 + 开源实践 + 反模式教训 (各≥1) | 补搜索后重做 |
| 必须输出 | 每条搜索的结果摘要 + 最优方案选型理由 | 无法进入 Step 3 |
| 对应每类问题 | 每类问题(如"豁免机制""多标签分类")各搜≥1次 | 遗漏的问题无搜索结果 |
| 禁止 | 凭记忆判断、跳过搜索直接fix、"显然不用搜" | 本轮无效，从 Step 2 重做 |
| **🛑 准入检查点** | **Step 2 搜索结果表必须在对话中输出后，才能开始写代码** | **没有搜索表输出 = 禁止进入 Step 3** |

> **搜索失败回退**: 若某次 WebSearch/WebFetch 返回空结果或超时 → 换搜索词重试 ≤2次。若全部失败 → 记录 `[WARN] 搜索不可用: {原因}` 并基于现有知识继续，但必须在回执中标注 `confirm: Step 2 搜索不完整`。

搜索完成后，输出：
```
### Step 2 搜索结果
| 问题 | 搜索词 | 关键发现 | 最优方案 |
|------|--------|---------|---------|
```
**🛑 此表格输出是进入 Step 3 的准入条件。未输出 = 禁止写代码。**

### Step 3: 批量修复 — 🛑 准入条件: 对话中必须有 Step 2 搜索结果表

按 🔴→🟡 优先级修复。每次改完后：
1. `python -m py_compile` 检查语法
2. `python novel.py test` + 单元测试
3. 确认不改动 SKILL.md / canon/ 设定文件

### Step 4: 回执 — 写入 replies/，留在那里等 Marvis

写入 `prompts/replies/YYYYMMDD_{report_id}_fixed.md`，**不回执不进入 Step 5，回执写完留在 replies/ 不移动**：
- 原问题 → 修复方案 → 编译/测试状态
- 标注误判项
- 尾部必须追加机器可读块，供 Marvis 自动解析：

```
## 跳过清单
- skip: {文件}:{行号} {问题简述}
- re-audit: {模块名} {原因}
- confirm: {需人工确认的事项}

## Marvis 行动
[skip] / [re-audit: {模块名}] / [confirm: {事项}]
```

标注规则：
- `skip` — 修完无误，Marvis 下次审查跳过
- `re-audit` — 修改可能引入副作用，Marvis 需对该模块重新审查
- `confirm` — 修复方案有二义性，需 User 确认后 Marvis 再做判断

### Step 5: 归档 — CodeBuddy 只移审查报告

<!-- 🛑 v5 教训: CodeBuddy 曾3次越权将回执移入 history/,
     导致 Marvis 读不到回执。回执必须留在 replies/。 -->

**CodeBuddy 执行**: 审查报告 `pending/` → `history/{id}/review.md`。**不碰 replies/**。

**Marvis 执行**: 读 `replies/` → 验证 → 移入 `history/{id}/reply.md`。

```

审查报告 + 回执归档到同一文件夹，方便检查闭环：

```
prompts/
├── pending/       ← Marvis 写入审查报告
├── replies/       ← CodeBuddy 写入回执
└── history/{id}/  ← 双方归档到同一子文件夹
    ├── review.md  ← 审查报告（由 CodeBuddy 移入）
    └── reply.md   ← 回执（由 Marvis 移入）
```

**闭环检查**: `history/{id}/` 中同时存在 `review.md` + `reply.md` = 闭环。缺任一个 = 漏了。

归档分工：
| 谁 | 移什么 | 源 → 目标 | 时机 |
|:---:|------|------|------|
| CodeBuddy | 审查报告 | `pending/{id}.md` → `history/{id}/review.md` | 修复完成后 |
| Marvis | 修复回执 | `replies/{id}.md` → `history/{id}/reply.md` | 验证完成后 |

## 约束 & 恢复指令

<!-- ⚠️ 每条约束必须有恢复指令。违规→后果→恢复 形成GuardRail闭环。 -->

| # | 约束 | 违规后果 | 恢复指令 |
|:---:|------|------|------|
| 1 | 不能盲信 Marvis — 必须先验证再修 | 修复方向错误 | 回到 Step 1：读源码逐条重新验证 |
| 2 | 不可跳过 Step 2 — ≥3 WebSearch + 1 WebFetch + 3域 | 方案非最优，可能引入次优设计 | 回到 Step 2：从零执行搜索。**禁止在对话中无 'Step 2 搜索结果' 表的情况下写代码** |
| 3 | 不重复已修 — 跳过回执中标注 ✅ 的项 | 重复劳动 | 检查历史回执中的 skip 清单 |
| 4 | 编译必须通过 — py_compile + novel.py test | 代码无法运行 | 修复编译错误 → 重跑 test → 直到通过 |
| 5 | 回执必须写 — 修复后必须输出 [Step 4 done] | Marvis 下次重复报同样问题, 且处理流程未完成 | 立即补写回执到 replies/, 输出 [Step 4 done] 后才能归档 |
| 6 | 🛑 CodeBuddy 禁止移动回执到 history/ — 回执必须留在 replies/ 等 Marvis 读 | 归档混乱，Marvis 找不到回执 | 立即从 history/ 移回 replies/，等 Marvis 自己归档 |
| 7 | 功能提案(_plotpilot/_intent) vs Bug审查 | 误将提案当Bug修 | 停止执行，标记为提案归档 |
