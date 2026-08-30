---
name: xiaoshuo-governance-adapter
description: xiaoshuo 项目治理 adapter；绑定稳定项目规则并引用项目集治理 core，阶段性输入按批次绑定。
---

# xiaoshuo 治理 Adapter

- `project_id`: `xiaoshuo`
- `adapter_layer`: `project`
- `adapter_status`: `CANDIDATE`
- `core_skill_reference`: `D:/Code/yeyu-ai/.agents/skills/governed-token-efficient-collaboration/SKILL.md`
- `core_sha256`: `F45C656045A7375C8923872BA47641294246C218F1D77C9B0E2EA4FE96ED2470`
- `rule_registry_reference`: `D:/Code/yeyu-ai/.agents/skills/governed-token-efficient-collaboration/references/rule-registry.json`
- `rule_registry_sha256`: `74889d655ba721bf80cbff7396d8a057adea061aec17a220ab2331f6358dd067`
- `parent_adapter_reference`: `D:/Code/yeyu-ai/.agents/skills/yeyu-ai-governance-adapter/SKILL.md`
- `parent_adapter_sha256`: `ABD1F670F7ACC0412950DE42C8ADB746C45CC2918441EC36377E0126B42AE656`
- `skill_layering_spec`: `D:/Code/yeyu-ai/.ai/skill-system.md`
- `skill_layering_spec_sha256`: `C0645C79BD6F43F8712CA1AE682D05240CCEC7392D724275F1E3E3EF098A5F09`
- `governing_documents`: `AGENTS.md`
- `governing_document_sha256`: `AGENTS.md=6076891353818334BD3C5B3F5C16529CDF3B0438654208127EE8AD0767B03130`
- `adoption_owner`: `用户/外部架构负责人`

## 权威来源

| path | sha256 |
|---|---|
| `AGENTS.md` | `6076891353818334bd3c5b3f5c16529cdf3b0438654208127ee8ad0767b03130` |

## 绑定

角色绑定策略：本 adapter 只声明能力角色和边界，不固定具体模型、供应商、软件或线程；实际绑定必须由阶段计划和授权负责人确定。

- `planner`: `阶段绑定的需求与架构规划角色`
- `executor`: `阶段绑定的实施与执行角色`
- `Reviewer`: `阶段绑定的独立只读复审角色（按阶段绑定独立线程）`
- `authority_owner`: `用户/授权负责人`
- `allowed_stage_types`: `implementation`, `evaluation_only`, `test_only`
- `code_review_required_default`: `UNKNOWN`；按已批准阶段计划绑定
- `independent_review_required`: 按阶段风险路由；L1 局部代码、L2/L3 高风险阶段需要独立复核，L0 普通小阶段不强制 planner_b
- `evidence_root_policy`: `D:\\tmp\\yeyu-ai-a3\\<stage>\\<run-id>`
- `run_id_policy`: 新鲜、不可变、合法并 containment 到获准 D 盘 stage/run
- `protected_paths`: `AI_PROTOCOL.md`, `assets/canon/`, `.codebuddy/`
- `config_ssot`: `config.yaml` 是运行配置 SSOT，仅在阶段明确绑定时读取或验证，不作为永久 protected path
- `stage_bound_sources`: `NEW_SESSION_HANDOFF.md`、`.ai/current-focus.md`、`config.yaml` 和阶段计划按当前阶段读取并绑定，不永久钉在 Adapter 来源表
- `version_integrity_policy`: 遵循治理 Core `references/integrity-and-versioning.md`；普通 MPV 开发使用 Git commit/diff，不手工维护逐文件 SHA
- `allowed_paths`: 阶段计划逐文件白名单
- `forbidden_activities`: 网络、服务、模型、生产、Git、白名单外修改和未授权项目测试
- `artifact_contract`: 使用 core packet、ledger、receipt、checksum 和 evidence closure verifier
- `reparse_order`: 递归枚举前及每次读写前先 containment/reparse
- `reviewer_model_distinct`: `阶段绑定；必须使用独立 Reviewer 线程并记录模型/线程；若阶段计划要求不同模型则必须为 `true`

## 语言策略

面向人的文档、Skill、注释、错误说明和回执以中文为主；代码标识符、协议 token、路径和必要标准术语可保留英文。必要英文术语采用“中文（English）”形式，不用英文替代已有清晰中文表达。

角色、授权来源、阶段计划和验证命令没有在当前阶段文档中确定的部分均为 `UNKNOWN`，因此不得启动完整协议。阶段裁决引用由当前阶段计划和授权提供，不永久绑定历史裁决文件。此 adapter 只引用 core，不复制正文；未经 xiaoshuo owner 和独立 Reviewer 接受，保持 `CANDIDATE`。

## C0 稳定 runner

项目专属的 C0 静态 census runner 固定为 `scripts/c0_responsibility_census.py`。它只承载 xiaoshuo 的已批准 source 与 artifact 合同；通用 packet、containment、ledger、receipt 和 closure 规则仍引用 core，不在本 adapter 复制。runner 不是 C0 evidence artifact，也不构成 C0 执行或 C1 授权。
