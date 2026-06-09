---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: b6d2bc339d43c35aa9002578e20a1d53_19408569634611f18c3c5254007bceed
    ReservedCode1: d2PoZvScMQvgotyfobO04xSDBiS9xhrHrIAUcoSCL/rqSjD0VGHRwCc+0dZ+J89QErG0JShuEPeNgYlPCrmzoryR/rzH1Ke7jAnEpOBrYEQMYUwnC7bAQ7xcgHX7T5fM8oPIdpWM/lYHwRF2ElU2mw1X4Ena4oW7UJ+e2QxGet4GKtXWMzbCcrGpV9I=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: b6d2bc339d43c35aa9002578e20a1d53_19408569634611f18c3c5254007bceed
    ReservedCode2: d2PoZvScMQvgotyfobO04xSDBiS9xhrHrIAUcoSCL/rqSjD0VGHRwCc+0dZ+J89QErG0JShuEPeNgYlPCrmzoryR/rzH1Ke7jAnEpOBrYEQMYUwnC7bAQ7xcgHX7T5fM8oPIdpWM/lYHwRF2ElU2mw1X4Ena4oW7UJ+e2QxGet4GKtXWMzbCcrGpV9I=
---



# 架构与目录优化方案 — 最终版

> 基于 CODEBUDDY.md 最新更新 + 全量文件扫描 + config.yaml/DESIGN.md/README.md 交叉验证

---

## 一、版本号统一

**现状**: 多个文件版本号不一致

| 文件 | 当前版本 | 应为 |
|------|---------|------|
| `DESIGN.md` | v7.4 | ✅ 以 DESIGN.md 为准 |
| `CODEBUDDY.md` | v7.3 | → v7.4 |
| `README.md` | v7.3 | → v7.4 |
| `.codebuddy/rules/project.mdc` | v7.1 | → v7.4 |
| `.codebuddy/rules/status.mdc` | 待查 | → v7.4 |

**操作**: 逐一编辑 `CODEBUDDY.md` `README.md` `project.mdc` `status.mdc`，将版本号统一为 v7.4。

---

## 二、config.yaml 精品书单去重

**现状**: `known_quality_list` 中有 6 本书出现两次（黑暗文明、狩魔手记、末日蟑螂、限制级末日症候、末世大回炉、黑暗血时代）

```
重复项:
  - "黑暗文明"     (行 ~245 + 行 ~265)
  - "狩魔手记"     (行 ~243 + 行 ~269)
  - "末日蟑螂"     (行 ~244 + 行 ~270)
  - "限制级末日症候" (行 ~245 + 行 ~271)
  - "末世大回炉"   (行 ~246 + 行 ~272)
  - "黑暗血时代"   (行 ~247 + 行 ~268)
```

**操作**: 删除 known_quality_list 中第二批重复的 6 条。保留第一批在 known_genre_map 中有对应映射的条目。

**风险**: 无。纯冗余，删除后不影响任何逻辑。

---

## 三、输出目录统一

**现状**: 存在两套输出路径

| 路径 | 文件数 | 用途 |
|------|--------|------|
| `analysis/outputs/` | 23 文件 | 分析产物 (reports / creative_guidance / calibration) |
| `outputs/reports/` | 14 文件 | 报告归档 |

**问题**: README 和 DESIGN.md 描述的是 `analysis/outputs/`，但项目根也有 `outputs/`。代码实际写入哪边不统一。

**方案**: 
- 保留 `analysis/outputs/` 作为分析管线的运行时输出目录（代码不改）
- `outputs/reports/` 改为存放**最终交付物**（人工精选的报告副本）
- 在 README.md 中注明二者的区别

**操作**: 在 README.md 目录结构说明中追加一行 `outputs/reports/` 为「精选报告归档」。

---

## 四、docs/ 目录瘦身

**现状**: 10 个文件，其中 2 个不属于 docs/

| 文件 | 处置 |
|------|------|
| `marvis_system_prompt.md` (10.8KB) | 移到 `.codebuddy/rules/` — 这是 AI 行为约束文档 |
| `README.md` (3.5KB) | 删除 — 是 README.md 的副本，冗余 |
| `新对话启动指令.md` (2.3KB) | 移到 `prompts/pending/` — 本质是指令模板 |
| `crawler_autopsy.md` | 保留 — 下载失败记录 |
| `external_review_*` (6个) | 保留 — 外部审查记录是历史档案 |

**操作**:
1. `mv docs/marvis_system_prompt.md .codebuddy/rules/marvis_system_prompt.md`
2. `rm docs/README.md`
3. `mv docs/新对话启动指令.md prompts/pending/新对话启动指令.md`

---

## 五、CODEBUDDY.md 与记忆面板的分工明确化

**现状**: CODEBUDDY.md 有共享基础设施信息，与 CodeBuddy 记忆面板内容重叠。

**方案**: 明确分工

| 放哪里 | 内容 | 谁维护 |
|--------|------|--------|
| CODEBUDDY.md | 项目结构、命令、技术决策、约束 | 手动，我帮你维护 |
| 记忆面板 | 你的身份、工作风格偏好 | CodeBuddy 自动学习 + 你手动补充 |
| config.yaml | 运行时参数（端口/阈值/路径） | 代码引用，你手动改 |

**操作**: CODEBUDDY.md 删掉「共享基础设施」段中的硬件/conda 路径细节（这些归记忆面板），仅保留项目运行时相关的模型端口和路由信息。

---

## 六、README.md 精简

**现状**: 292 行，60秒上手 + 项目结构 + 数据流 + 设计决策 + 快速开始 + 配置 + 技术栈，信息密度高但部分重复。

**方案**: 拆分为两层

| 层 | 文件 | 内容 |
|----|------|------|
| 门面 | `README.md` | 60秒上手 + 六阶段一览 + 目录速查 + 快速开始 + 配置（目标 ≤150行） |
| 深度 | `DESIGN.md` | 架构设计 + 设计决策 + 数据流 + 部署方案（已存在，不动） |

README 中删除的重复内容：数据流详图（DESIGN.md 已有）、关键设计决策（DESIGN.md 已有）、技术栈（CODEBUDDY.md 已有）。

**操作**: 精简 README.md 到 ~120 行，末尾加一行「深度架构见 DESIGN.md」。

---

## 七、SKILL.md 与 .codebuddy/skills/ 关系注释

**现状**: 根目录的 `SKILL.md` 和 `.codebuddy/skills/` 下 8 个 Skill 容易混淆。

| 文件 | 来源 | 用途 |
|------|------|------|
| `SKILL.md` (根) | 本项目自建 | LLM 行为协议，由 `agents/skill_loader.py` 注入 System Prompt |
| `.codebuddy/skills/` (8个) | CodeBuddy 技能 | CodeBuddy IDE 的 Agent 任务编排，触发词匹配执行 |

**操作**: 在 README.md 目录结构中注明二者的区别，避免混淆。

---

## 八、优先执行顺序

| 优先级 | 项目 | 影响范围 | 工作量 |
|--------|------|---------|--------|
| 🔴 P0 | 版本号统一 (4个文件) | 全局一致性 | 5分钟 |
| 🔴 P0 | config.yaml 去重 (删6行) | 无功能影响，纯卫生 | 1分钟 |
| 🟡 P1 | docs/ 瘦身 (3个文件移动/删除) | 目录整洁 | 2分钟 |
| 🟡 P1 | README 精简 (292→~120行) | 可读性 | 10分钟 |
| 🟢 P2 | 输出目录说明 (加1行注释) | 新开发者理解 | 1分钟 |
| 🟢 P2 | CODEBUDDY.md 分工调整 | 长期维护效率 | 5分钟 |
*（内容由AI生成，仅供参考）*
*（内容由AI生成，仅供参考）*
