---
name: xiaoshuo-governance-adapter
description: xiaoshuo 项目治理 adapter；绑定项目 AGENTS、会话交接和 config.yaml，并引用项目集治理 core。
---

# xiaoshuo 治理 Adapter

- `project_id`: `xiaoshuo`
- `adapter_status`: `CANDIDATE`
- `core_skill_reference`: `D:/Code/yeyu-ai/.agents/skills/governed-token-efficient-collaboration/SKILL.md`
- `core_sha256`: `941922711c10ce733a1a5e07a1b8c0a1fba7b6d1ec888f35b70c9e469239a1cc`
- `parent_adapter_reference`: `D:/Code/yeyu-ai/.agents/skills/yeyu-ai-governance-adapter/SKILL.md`
- `parent_adapter_sha256`: `22aca530795721e896e5bd0812ff12081dcb72a614a9a2fe5e6646edeed0e20f`
- `adoption_owner`: `用户/外部架构负责人`
- `ruling_references`: `D:/Code/yeyu-ai/.ai/evaluation-responsibility-split-c1-owner-ruling.md@0439af7050e099d58c9600cbf06f39e60e79e6d43720adbaab55b70a7e0cb02d`; `D:/Code/yeyu-ai/.ai/evaluation-responsibility-split-c1-m1-legacy-correction-authorization.md@bedea83b53251e26a1cdc1698bf840923ddc1c2992d206254a489103141a8f98`

## 权威来源

| path | sha256 |
|---|---|
| `xiaoshuo/AGENTS.md` | `b4391d9ad84219b3f5827a4100abb39e7cb24549fe8fee10c53bcfa7096813cd` |
| `xiaoshuo/NEW_SESSION_HANDOFF.md` | `7a851329e1619906b1a1d12b581d83691f59b37178c4320bd0c3107f05915cfb` |
| `xiaoshuo/config.yaml` | `4c983d9f63ff9e27f783951cc36624356912c976f04f4b49aebb26ca1444ff1c` |

## 绑定

- `planner`: `外部架构顾问（当前编排：Luna Max）`
- `executor`: `Codex implementation agent`
- `Reviewer`: `Luna 独立只读 Reviewer（按阶段绑定独立线程）`
- `authority_owner`: `用户/外部架构负责人`
- `allowed_stage_types`: `implementation`, `evaluation_only`, `test_only`
- `code_review_required_default`: `UNKNOWN`；按已批准阶段计划绑定
- `independent_review_required`: `true`
- `evidence_root_policy`: `D:\\tmp\\yeyu-ai-a3\\<stage>\\<run-id>`
- `run_id_policy`: 新鲜、不可变、合法并 containment 到获准 D 盘 stage/run
- `protected_paths`: `AI_PROTOCOL.md`, `assets/canon/`, `.codebuddy/`
- `config_ssot`: `config.yaml` 是运行配置 SSOT，仅在阶段明确绑定时读取或验证，不作为永久 protected path
- `allowed_paths`: 阶段计划逐文件白名单
- `forbidden_activities`: 网络、服务、模型、生产、Git、白名单外修改和未授权项目测试
- `artifact_contract`: 使用 core packet、ledger、receipt、checksum 和 evidence closure verifier
- `reparse_order`: 递归枚举前及每次读写前先 containment/reparse
- `reviewer_model_distinct`: `阶段绑定；必须使用独立 Reviewer 线程并记录模型/线程；若阶段计划要求不同模型则必须为 `true`

## 语言策略

面向人的文档、Skill、注释、错误说明和回执以中文为主；代码标识符、协议 token、路径和必要标准术语可保留英文。必要英文术语采用“中文（English）”形式，不用英文替代已有清晰中文表达。

角色、授权来源、阶段计划、验证命令和裁决引用没有在本次读取文档中确定的部分均为 `UNKNOWN`，因此不得启动完整协议。此 adapter 只引用 core，不复制正文；未经 xiaoshuo owner 和独立 Reviewer 接受，保持 `CANDIDATE`。

## C0 稳定 runner

项目专属的 C0 静态 census runner 固定为 `scripts/c0_responsibility_census.py`。它只承载 xiaoshuo 的已批准 source 与 artifact 合同；通用 packet、containment、ledger、receipt 和 closure 规则仍引用 core，不在本 adapter 复制。runner 不是 C0 evidence artifact，也不构成 C0 执行或 C1 授权。
