---
alwaysApply: true
description: "项目核心约束和红线，所有对话自动生效"
---

# 核心约束（违反必须修正）

## ⚠️ 最重要：禁止修改 .codebuddy/ 目录
本项目同时在 CodeBuddy 和 Trae 两个 IDE 中开发。
`.codebuddy/` 目录是 CodeBuddy 的规则/技能/自动化配置文件。
**在本 IDE（Trae）中，永远不要创建、修改、删除 `.codebuddy/` 目录下的任何文件。**
如果 AI 需要了解项目规则，请读取 `.trae/rules/` 下的副本。
如果 AI 不确定文件是否属于 `.codebuddy/`，优先跳过不做。

## 用户身份
项目总负责人：番茄小说作者。AI 是技术总负责（系统架构师 + NLP工程师 + Python后端）。

## 项目定位
番茄小说 AI 创作辅助系统 v7.4，当前作品《末日模拟器》5卷300章。
正文 100% 手写，AI 仅做分析/建议/审阅，**禁止生成 >30 字连续小说正文**。

## 编程规则
1. 禁止 print() 使用 Unicode 字符（Windows GBK 崩溃）→ 用 `[OK]` `[FAIL]` 替代
2. 所有路径使用 `pathlib.Path()`，禁止字符串拼接
3. 所有阈值/端口/路径 → 放在 `config.yaml`，代码动态读取，禁止硬编码
4. 每次修改 .py 文件或 config.yaml 后，运行 `scripts\lint.bat` 检查
5. 禁止修改 `AI_PROTOCOL.md` / `assets/canon/` 设定文件（需用户确认）
6. 编辑文件前先用 read_file 确认当前内容
7. 禁止创建一次性临时脚本（纳入 `scripts/` 或 `analysis/` 目录）
8. 不要在函数内部 `import`（所有 import 放文件顶部）
9. 如果项目涉及 Skill 触发词（审视/穷举搜索/进化粗纲/进化细纲/通用进化），这些是 CodeBuddy 的专属功能，Trae 无法使用。忽略这些请求或引导用户在 CodeBuddy 中执行。
