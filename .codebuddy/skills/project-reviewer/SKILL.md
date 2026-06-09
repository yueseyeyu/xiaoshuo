---
name: project-reviewer
description: |
  番茄小说项目审视优化。说"审视""review""优化""检查代码"触发。
  智能分级: 默认语法+自检(0 token), 仅在失败或用户要求时才深度审查。
  涵盖: 架构审查、代码质量、配置一致性、SSOT原则、规则同步。
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, WebSearch, WebFetch
---

# 核心规则: 任何代码变更后, 必须先自审再声明"完成"

你经常在写代码后跳过自审, 导致 bug 残留。
从此刻起, 每次 `write_to_file` 或 `replace_in_file` 之后,
必须立即执行"后写自审清单", 全部通过后才能说"完成"。

## 后写自审清单 (每次生成代码后强制执行, 不可跳过)

```
1. 📖 re-read: 刚写的文件是否存在? 读一遍确认无粘贴错误?
2. 🐍 compile: python -m py_compile <file> (全部文件)
3. 🔍 check: 下列 5 项逐条确认:
   [ ] import 全部在文件顶部 (无函数内 import)
   [ ] 无限import (import X → 搜索用法, 无=删)
   [ ] 路径/端口/阈值 来自 config 或顶部常量 (无硬编码)
   [ ] 函数不修改入参 dict/list (浅拷贝)
   [ ] Unicode print 改为 ASCII标记
4. 🧪 test: python novel.py test (必须 5/5)
```

**如果任何一项失败 → 修复 → 重新跑清单。循环直到全通过。**

## 审视流程

### Level 1: 快速 (默认入口)

```bash
python -m py_compile .agents\*.py novel.py
python novel.py test
```
通过 → `[OK] Level 1 passed, no deep review` 结束。
失败 → 自动升级 Level 2。

### Level 2: 变更文件审查

1. 只读本次会话修改过的 .py / config / rules
2. 检查: 硬编码路径、配置代码不一致、docstring过时、空输出处理
3. 修复后 `python novel.py test`

### Level 3: 全量穷举 (用户说"穷举审视") — 12角色 Ralph Loop

**核心: 不在第1轮停止, 必须循环直到收敛。**
**关键**: **你必须立即执行 `use_skill exhaustive-search` 加载完整协议**。不可凭本文概述执行——本文仅作入口说明，不包含角色定义、执行流程、防偷懒规则。
⚠️ **依赖降级**: 若 `exhaustive-search` Skill 不可用或加载失败，降级报告 `[Level 3] exhaustive-search unavailable, fallback to Level 2` 并自动退回 Level 2 审查。

每轮:
1. 从零重读全部 .py + config + rules (不能依赖上轮发现)
2. 以当前角色视角填满 5 项检查单（每项 ✅/❌ + 文件:行号依据）
3. >=3次 WebSearch + >=2次 WebFetch（12角色轮换, 搜索词不与最近3轮重复）
4. 取样≥3处具体行号/变量名作为证据
5. 引用至少 1 条外部来源原句

执行流程:
有发现 → 修复 → `python novel.py test` → 切换角色 → 回到步骤1
连续2轮 C+H+M=0 → `[Level 3] converged` | 满12轮 → 截断

角色轮换表: 代码审查员→读者体验→市场合规→边界测试→反向论证→安全合规→性能分析→架构一致性→配置SSOT→跨模块依赖→API兼容→综合验收

## 项目专用约束

- Windows GBK: print 用 `[OK][FAIL]`, 不用 ✓✗⚠️
- SSOT: 值只在 config.yaml 定义, 代码动态读取
- 不修改 SKILL.md / canon/ / rules/ 除非用户要求
- subprocess: 无消费者用 DEVNULL, 不用 PIPE

## 每次输出格式

```
[Level N] found:X | fixed:Y | test:M/N | tokens:~Z | next:done/upgrade
```

## 反模式: 你做错的典型流程

```
❌ 错误: 写代码 → "完成!" → 用户审视 → 发现3个bug → 修复 → "完成!" → 再审视 → 还有bug
✅ 正确: 写代码 → 立刻跑后写自审清单 → 发现bug → 修复 → 再跑清单 → 通过 → "完成!"
```
