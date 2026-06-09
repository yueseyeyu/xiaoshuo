# 番茄小说 AI 创作辅助系统 v7.4 — 双 IDE 切换说明

## ⚠️ 最优先规则：不要修改 `.codebuddy/` 目录下的任何文件
本项目同时在 **CodeBuddy** 和 **Trae** 两个 IDE 中开发。
`.codebuddy/` 是 CodeBuddy 的规则/技能/自动化配置文件。**在任何 IDE 中都不要动它。**
规则副本在 `.trae/rules/` 下，参考那里即可。

## 项目简介
番茄小说平台网文创作辅助工具，正文 100% 手写，AI 仅做分析/建议/审阅。
- 当前作品：《末日模拟器》5卷300章
- 核心功能：爆款分析、拆书、生成写作指导、逐章指令
- 六阶段管线全通：入库→拆书→评分→整合→指导→对比

## Trae 中不可用的功能
以下功能是 CodeBuddy 专属 Skill 系统，在 Trae 中无法使用：
- ❌ 审视 / review / 代码审查（CodeBuddy project-reviewer）
- ❌ 穷举搜索 / exhaustive search
- ❌ 进化粗纲 / 大纲审视（rough-outline-evolution）
- ❌ 进化细纲 / 章纲进化（chapter-evolution）
- ❌ 通用进化 / 穷举进化（loop-evolution）
- ❌ 进化 skill（skill-evolution）

遇到这些请求 → 告诉用户在 CodeBuddy 中执行。

## 快速命令参考
```
scripts\start_model.bat    # 启动 Qwen3.5-9B
scripts\lint.bat            # 代码检查
python novel.py analyze --genre 末世
python analysis/analyze_all.py
```
