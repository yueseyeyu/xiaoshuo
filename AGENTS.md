# 番茄小说 AI 创作辅助系统 v7.4 — 多 IDE 切换说明

## ⚠️ 最优先规则：不要修改 `.codebuddy/` `.trae/` 目录下的任何文件
本项目同时在 **CodeBuddy**、**Trae** 和 **Qoder** 三个 IDE 中开发。
- `.codebuddy/` 是 CodeBuddy 的规则/技能/自动化配置文件。**在任何 IDE 中都不要动它。**
- `.trae/rules/` 是 Trae 的规则文件。**在任何 IDE 中都不要动它。**
- `.qoder/` 是 Qoder 的规则和技能副本。**只在此目录中修改。**

## 项目简介
番茄小说平台网文创作辅助工具，正文 100% 手写，AI 仅做分析/建议/审阅。
- 当前作品：《末日模拟器》5卷300章
- 核心功能：爆款分析、拆书、生成写作指导、逐章指令
- 六阶段管线全通：入库→拆书→评分→整合→指导→对比
- 完整愿景见 DESIGN.md §15：十阶段闭环设计（分析→骨架→手写→对比→风格涌现→蒸馏）

## IDE 专属 Skill 系统

### CodeBuddy 专属（`.codebuddy/skills/`）
以下功能在 CodeBuddy 中可用：
- 审视 / review / 代码审查（project-reviewer）
- 穷举搜索 / exhaustive search
- 进化粗纲 / 大纲审视（rough-outline-evolution）
- 进化细纲 / 章纲进化（chapter-evolution）
- 通用进化 / 穷举进化（loop-evolution）
- 进化 skill（skill-evolution）

### Qoder 专属（`.qoder/skills/`）
以下功能在 Qoder 中可用：
- ✅ 审视 / review / 优化（project-reviewer）
- ✅ 穷举搜索（exhaustive-search）
- ✅ 进化粗纲 / 进化细纲 / 通用进化 / skill进化
- ✅ 澄清优先（clarify-first）
- ✅ Marvis审查处理（marvis-review-handler）

### Trae 中不可用
Trae 不支持 Skill 系统。遇到这些请求 → 告诉用户在 CodeBuddy 或 Qoder 中执行。

## 快速命令参考
```
scripts\start_model.bat    # 启动 Qwen3.5-9B
scripts\lint.bat            # 代码检查

# v7.4 新增: 交互式写作会话
python novel.py session --book 末日模拟器 --genre 末世  # 完整 S0->S4 REPL
python novel.py write --chapter 5 --file my_chapter.md  # 提交章节
python novel.py characters                               # 角色设计
python novel.py outline                                  # 大纲生成
python novel.py decisions --chapter 5                    # 决策采集

# 已有命令
python novel.py init
python novel.py status
python novel.py worldbuild
python novel.py s1 --chapter 5 --variants 3
python novel.py s3 --chapter 5
python novel.py analyze --genre 末世
python novel.py deep --genre 末世
python novel.py test
```
