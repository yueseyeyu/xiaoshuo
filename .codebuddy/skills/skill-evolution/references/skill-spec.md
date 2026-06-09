# Skill 审查标准速查

> 供 skill-evolution 各轮角色调用的权威参考摘要。

## Agent Skills 格式规范 (agentskills.io, 2026.1)

### 目录结构
```
skill-name/
├── SKILL.md          # 必需
├── scripts/          # 可选
├── references/       # 可选
└── assets/           # 可选
```

### SKILL.md Frontmatter
- **必需**: `name` (小写连字符, ≤64字符), `description` (≤1024字符, 含触发词)
- **可选**: `license`, `compatibility`, `metadata`, `allowed-tools`
- `metadata` 可含: `version`, `author`, 任意键值对

### 渐进式披露
- 元数据(~100 tokens): 启动时加载
- 正文(<5000 tokens): 激活时加载
- resources(按需): scripts/references/assets

## Skill 设计模式 (AI全书, 2026.4)

| 模式 | 适用 | 结构模板 |
|------|------|------|
| 线性流程 | 明确步骤的操作 | Prerequisites → Steps → Fallback → Troubleshooting |
| 决策树+按需加载 | 大型平台选型 | Decision Trees → Product Index → References |
| 循环迭代 | TDD/审查 | Iron Law → Loop → Rationalizations → Checklist |
| 接力棒循环 | 跨Session长期项目 | Baton System → Execution Protocol (6步) |
| 多阶段+检查点 | 复杂多周流程 | Phases(Activities→Outputs→Decision Point) |
| 思维框架 | 深度分析/审计 | Purpose → When/Not → Rationalizations → Phases → Non-Goals |

### 防 LLM 偷懒 4 种武器
1. 强硬语气 ("Delete it. Start over.")
2. 借口反驳表 (预判12种偷懒借口)
3. 量化阈值 ("最少3个不变量")
4. 负面指令 ("不要curl URL验证")

### 知识组织三层架构
- 第1层: Frontmatter ~100 tokens
- 第2层: SKILL.md正文 2K-5K tokens
- 第3层: references/ 1K-3K tokens (按需)
- **总预算**: 主文件+1~2个参考<10K tokens

## SkillGuard 权限框架 (arXiv 2606.03024, 2026.6)

### 三原则
1. **最小权限**: 仅获取完成功能所必需的最低权限
2. **完全中介**: 每次访问都验证 — 不"一次授权永久有效"
3. **失效安全默认**: deny-by-default，显式授权才放行

### 工具风险分级 (SkillShield)
- 🔴 极高: bash/sh, curl/wget, sudo, eval/exec, ssh/scp
- 🟡 高: python/node, docker, npm/pip
- 🟢 低: git(只读), grep, ls, cat/head/tail, find, diff

**危险组合**: bash+curl (执行+外传), Write+Edit+Bash (修改+执行)

## 触发词设计原则
- description中列出常见触发短语（含笔误变体）
- 与其他Skill的触发词无歧义
- 覆盖用户最可能的自然语言输入

## 项目约束 (project.mdc)
- Skill 触发词映射在 project.mdc §Skill触发强制 段定义
- 护栏规则需与 loop-evolution 和 rough-outline-evolution 同步 (rule 32)
- 新增Skill需注册到 project.mdc 工具&模块段
