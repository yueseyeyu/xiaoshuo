# MPV-02B DQA 执行 Packet v1

合同正文状态：`IMMUTABLE_CONTRACT / PLAN_A_EXECUTOR_CONTRACT_CORRECTION_05`

当前生命周期状态不由本文件读取：唯一权威来源是 [DQA finding ledger](2026-08-mpv-02b-dqa-finding-ledger-v11.md) 末尾最后一条通过 predecessor 链校验的追加事件。本文件中的 `状态`、`current_state`、Reviewer 回执和 owner disposition 均为历史记录或合同说明，不得覆盖 ledger 当前状态。

`contract_digest` 是独立于生命周期的合同身份：由 packet 绑定的 v2 contract source canonical projection 计算，排除自身 digest 和顶层生命周期字段。`packet_sha256`、设计/packet 完整文件 SHA 只证明相应字节身份，不能替代 `contract_digest`。

当前 packet revision：`PLAN_A_EXECUTOR_CONTRACT_CORRECTION_05`

范围审视：`PLAN-SCOPE-REVIEW: SUFFICIENT`

合同预审：`PLAN_CONTRACT_PREFLIGHT: PENDING_CORRECTION_05_REVIEW`

本文件是未来一次只读 DQA 执行的操作合同。17 项检查的机器合同源是 [`dqa-check-contract-matrix-v1.json`](2026-08-mpv-02b-dqa-check-contract-matrix-v1.json)；本 packet 只实例化其输入、环境、输出和封存边界，不得自行维护第二套检查规则。它不执行 DQA，不创建 run，不构成执行授权，也不替代主设计。

## 最终需求描述

目标是把已接受的 MPV-02B B 阶段 DQA 主设计转换为一份可由授权 executor 使用的、逐文件、逐检查、可复核的只读执行合同。执行结果只能判断 `SOURCE_DATA_GATE`、`EVALUATION_DATA_GATE` 及其证据边界，不能把样本结果、历史基线或审计报告升级为全库质量、生产质量或绝对人工真值。

用户价值是保证未来 DQA 读取的源正文、章节/场景连续性、索引载荷、查询来源、标注、裁决和指标具有可追溯的输入身份与失败语义，避免在不可信数据上优化检索器。

本批次只落盘本文件。未来执行只允许读取下列 literal allowlist，向新的 D 盘 run 根写入本 packet 规定的证据，并在执行后交给独立 verifier 和 post-review。主设计、finding ledger、源码、索引、标注、历史质量基线、配置和保护路径均不可被修改。

风险是部分历史输入只有 `text_preview`、E01 查询来源可能不存在、生产等价排序可能缺少完整身份、标注独立性可能不能证明，以及当前没有现成的完整 17 项 DQA executor。任何不能从允许输入证明的事实必须保持 `UNKNOWN`、`UNPROVEN` 或 `BLOCKED`，不得由 executor 自行补充规则。

验收要求是：packet 与主设计/ledger 版本精确绑定；输入和输出边界可通过 preflight 复核；17 项逐项执行合同完整；五状态门禁和污染传播不变；成功与失败都产生 JSON、中文 Markdown、manifest、checksum 和 seal；未取得独立 post-review 与 owner 裁决前不得关闭阶段。

## 设计绑定与职责边界

本 packet 绑定以下只读输入：

| 项目 | 绑定值 |
|---|---|
| 主设计 | `D:\Code\yeyu-ai\xiaoshuo\docs\plans\2026-08-mpv-02b-dqa-design-v11.md` |
| 17 项检查机器合同源 | `D:\Code\yeyu-ai\xiaoshuo\docs\plans\2026-08-mpv-02b-dqa-check-contract-matrix-v1.json` |
| 机器合同源 schema | `governed-contract-source/v2` |
| 机器合同源 revision | `PLAN_A_EXECUTOR_CONTRACT_CORRECTION_05` |
| 机器合同源 matrix SHA-256 | `204aec682b3a9ddd40a701a9c752e77dd3c67ba954278911c2a389fc02e014fd` |
| 机器合同源 contract digest | `c9a8bd12a70784932573256f283a6c3799b46abc0fa75c9e9b7810d47a5d2b02` |
| rule registry | `.agents/skills/governed-token-efficient-collaboration/references/rule-registry.json`, `rules-r2`, `74889D655BA721BF80CBFF7396D8A057ADEA061AEC17A220AB2331F6358DD067` |
| 主设计 SHA-256（历史复核快照；授权前 fresh readback 必须重算） | `0A05E756BB0FADD0CE1B0F06E08E10932CBEAC770B6996F1FF7B3B8699C78D11` |
| 设计 revision | `PLAN_A_EXECUTOR_CONTRACT_CORRECTION_05` |
| finding ledger | `D:\Code\yeyu-ai\xiaoshuo\docs\plans\2026-08-mpv-02b-dqa-finding-ledger-v11.md` |
| ledger SHA-256（历史复核快照；授权前 fresh readback 必须重算） | `B5BD29EF0444F7641695A85017A75B8BDD27F927AEA8539FCB6E6BA8272B8F02` |
| ledger revision | `MPV-02B-DQA-LEDGER-11-EXECUTOR-CORRECTION-05` |
| current event | `MPV-02B-DQA-LE-20260830-022` |
| predecessor event | `MPV-02B-DQA-LE-20260830-021` |
| planner_b receipt | `PENDING: new independent reviewer required for correction-05` |
| consensus state | `PLAN_B_REVIEW_REQUIRED / CONSENSUS_BLOCKED / DQA_NOT_AUTHORIZED` |
| 根规则 | `D:\Code\yeyu-ai\AGENTS.md` |
| 根规则 SHA-256（当前 active） | `41D233E741BB9351AEFC484D5AB35F91F1F3201435399B5C6B309F36009332E1` |

主设计冻结业务检查、状态、退出码、reason code、门禁和证据语义；本 packet 只冻结实际输入、只读执行入口、环境、run、输出、封存、verifier 和 post-review 输入。`SEALED_SUCCESS`/`SEALED_FAILURE` 是封存结果，不是质量门状态。packet 不新增检查，不改变任何业务状态、退出码、reason code、依赖关系或 gate 聚合。

## 范围、非目标和硬禁止

纳入范围：三本书样本的源文件、解析/场景直接入口、样本索引及 manifest、24 条查询、472 候选、三方 annotation、26 条裁决、既有评测协议和历史质量基线输出的只读身份核对。

非目标及禁止事项：

- 不执行正式索引或任何索引重建，不写 `data/processed/`、`data/raw/`、质量基线目录或标注目录。
- 不加载模型、tokenizer 或 embedding，不访问网络，不启动服务/API/生产 pipeline，不执行性能基线或 cold/warm 测量。
- 不修改源码、测试、配置、索引、manifest、metadata、向量、原始正文、annotation、裁决、共识、历史质量基线、ADR、Skill、`AI_PROTOCOL.md`、`assets/canon/` 或 `.codebuddy/`。
- 不运行 pytest、Ruff、mypy、Git 写操作、安装依赖、下载资料或生成项目缓存。
- 不把 `data_quality_audit.py`、质量基线生成脚本或旧报告当作 v11 的独立 DQA executor；它们可以在 inventory 中被排除并记录理由，但不得执行以替代 DQA-01..09/E01..E08。
- 不因某个下游检查已得到结果而覆盖源门传播的 `INVALIDATED` 或 `CONTAMINATED`；不以总体成功率替代逐项状态。

## 输入 literal allowlist

输入类别固定为三类，执行者不得自行改变：

1. `required_literal_inputs`：本节逐行列出的合同文件、源码、配置、原始正文、样本索引、查询、候选、标注、裁决和指标输入。每项必须 individually 存在、可读、满足类型和 containment；缺失按对应检查合同处理，不得用近似路径替代。
2. `optional_absence_allowed`：查询 provenance 原始来源、`e06-semantic-review-v1` 语义复核输入，以及已封存 DQA/E 输出。它们缺失时必须记录 absence record；E01 或 E06 按机器矩阵降为 `UNPROVEN`，不能当作 PASS。已封存输出当前为空集合，未来只能逐文件追加到新授权。
3. `e03_recursive_root`：唯一 literal `e03_inventory_root` 目录及其非 reparse 后代。它不是普通文件 allowlist，也不是自由目录授权；只有 E03 规则允许递归枚举，canonical 三文件缺失由 E03 自身映射为 `FAIL/10`。

以下路径是未来执行的完整输入白名单。文件输入路径必须按给出的绝对 Windows literal 使用；不得通过 glob 扩展、目录复制、隐式 fallback 或当前目录推断增加输入。唯一例外是 E03 明确声明的一个 `e03_inventory_root` 目录：它不是自由目录输入或 stage 扩展，而是只允许按 E03 合同做非 reparse 递归枚举的固定 literal 根。所有输入只读打开；每个 literal 文件以及 E03 枚举到的每个 descendant 都必须在 `inputs-manifest.json` 或 E03 inventory evidence 中记录 `literal/relative path`、用途、文件类型、字节大小、SHA-256（目录/ reparse 条目按合同记录）和 `reparse` 检查结果。

### 项目源码、配置和样本索引

| literal path | 用途 | 只读要求 |
|---|---|---|
| `D:\Code\yeyu-ai\xiaoshuo\config.yaml` | `config.yaml` SSOT；核对题材、索引、top-k、模型身份、offline、RRF 和场景边界参数 | UTF-8 解码；只解析，不导入配置写回 |
| `D:\Code\yeyu-ai\xiaoshuo\src\xiaoshuo\pipeline\rhythm_analyzer.py` | `extract_chapters` 及章节解析直接入口 | 只读源文本；不得调用会写入的入口 |
| `D:\Code\yeyu-ai\xiaoshuo\src\xiaoshuo\pipeline\rhythm\chapter_parser.py` | `chapter_parser.py` 章节边界/解析直接实现核对 | 只读源文本；不得调用会写入的入口 |
| `D:\Code\yeyu-ai\xiaoshuo\src\xiaoshuo\pipeline\scene_search.py` | 场景切分、索引读取、BM25/BGE/RRF 排序和 payload 映射直接入口 | 只读源文本；禁止 `--build`、模型加载和 search runtime |
| `D:\Code\yeyu-ai\xiaoshuo\src\xiaoshuo\pipeline\novel_index.py` | 仅在直接调用关系需要时核对项目索引边界；不得将其 SQLite 写入口纳入执行 | 只读源文本；禁止数据库写操作 |
| `D:\Code\yeyu-ai\xiaoshuo\data\raw\novel_index.json` | 三本书的源身份、genre 和文件映射 | 严格 UTF-8 JSON；不写回 |
| `D:\Code\yeyu-ai\xiaoshuo\data\processed\末世\scene_index.sample\manifest.json` | 样本索引身份、14,717 场景、三本书、参数、源 hash 和 artifact hash | 严格 UTF-8 JSON；不将字段当作已验证事实，须独立重算 |
| `D:\Code\yeyu-ai\xiaoshuo\data\processed\末世\scene_index.sample\metadata.json` | 14,717 条 metadata、doc_id 组成、text_preview、边界/字段映射输入 | 二进制字节 hash 后严格 UTF-8 JSON 读取；不得写回 |
| `D:\Code\yeyu-ai\xiaoshuo\data\processed\末世\scene_index.sample\bm25_index.pkl` | BM25 token corpus/index row 对照 | 仅允许静态 `pickletools` 检查或严格受限、无导入/无 reducer 执行的解析；不得执行任意 pickle opcode、导入 global、调用 reducer 或产生副作用；无法安全解析时 `BLOCKED/40` |
| `D:\Code\yeyu-ai\xiaoshuo\data\processed\末世\scene_index.sample\bge_embeddings.npy` | 向量 row 数、dtype、shape、有限性和 doc row 对照 | `allow_pickle=False`；不得加载模型或重新编码 |
| `D:\Code\yeyu-ai\xiaoshuo\data\processed\末世\rhythm\rhythm_《世界末日从考试不及格开始》作者：小猫要成仙.csv` | 对应书的章节辅助记录和解析映射 | UTF-8-sig/RFC4180 只读解析；不修改 |
| `D:\Code\yeyu-ai\xiaoshuo\data\processed\末世\rhythm\rhythm_《从红月开始》（校对版全本）作者：黑山老鬼.csv` | 对应书的章节辅助记录和解析映射 | UTF-8-sig/RFC4180 只读解析；不修改 |
| `D:\Code\yeyu-ai\xiaoshuo\data\processed\末世\rhythm\rhythm_《全球进化》（精校版全本）作者：咬狗.csv` | 对应书的章节辅助记录和解析映射 | UTF-8-sig/RFC4180 只读解析；不修改 |
| `D:\Code\yeyu-ai\xiaoshuo\data\raw\novels\末世\《世界末日从考试不及格开始》作者：小猫要成仙.txt` | 三本样本书之一的完整原始正文 | 以原始 bytes 读取；严格 UTF-8；不得 trim、normalize、截断或写回 |
| `D:\Code\yeyu-ai\xiaoshuo\data\raw\novels\末世\《从红月开始》（校对版全本）作者：黑山老鬼.txt` | 三本样本书之一的完整原始正文 | 以原始 bytes 读取；严格 UTF-8；不得 trim、normalize、截断或写回 |
| `D:\Code\yeyu-ai\xiaoshuo\data\raw\novels\末世\《全球进化》（精校版全本）作者：咬狗.txt` | 三本样本书之一的完整原始正文 | 以原始 bytes 读取；严格 UTF-8；不得 trim、normalize、截断或写回 |

### 历史质量基线输入

历史输入根固定为 `D:\tmp\yeyu-ai-a3\mpv-02b-quality-baseline\20260826-000001-000014`。它是 D 盘历史质量基线，只读使用；不是本次 run 根，也不是授权本身。下表列出固定 literal 文件输入，并单独列出唯一允许递归的 E03 inventory root；除此之外不得增加输入。

| literal path | 用途 |
|---|---|
| `D:\tmp\yeyu-ai-a3\mpv-02b-quality-baseline\20260826-000001-000014` | 唯一 literal `e03_inventory_root` 目录；仅供 E03 按下方固定规则非 reparse 递归枚举，不是 stage root 或模糊目录授权 |
| `D:\tmp\yeyu-ai-a3\mpv-02b-quality-baseline\20260826-000001-000014\quality-baseline-plan.md` | 历史基线范围、24 query、候选深度和 `text_preview` 限制 |
| `D:\tmp\yeyu-ai-a3\mpv-02b-quality-baseline\20260826-000001-000014\queries.json` | 24 条 query、类别和 query bytes 输入 |
| `D:\tmp\yeyu-ai-a3\mpv-02b-quality-baseline\20260826-000001-000014\candidate-results.json` | 原始 BM25/BGE/RRF 观察、rank、doc_id、sample manifest 引用和候选池重算 |
| `D:\tmp\yeyu-ai-a3\mpv-02b-quality-baseline\20260826-000001-000014\candidate-results-enriched.json` | 历史 enriched payload；只作对照，不替代完整正文 |
| `D:\tmp\yeyu-ai-a3\mpv-02b-quality-baseline\20260826-000001-000014\annotation-agreement.json` | 历史 agreement 对照；E04 必须独立重算 |
| `D:\tmp\yeyu-ai-a3\mpv-02b-quality-baseline\20260826-000001-000014\annotation-adjudication.json` | 26 条裁决、原始标签、final label、理由和 E05/E06 输入 |
| `D:\tmp\yeyu-ai-a3\mpv-02b-quality-baseline\20260826-000001-000014\consensus-annotation.csv` | 共识标签对照和 E07 qrels 输入 |
| `D:\tmp\yeyu-ai-a3\mpv-02b-quality-baseline\20260826-000001-000014\consensus-annotation.pre-adjudication.csv` | 裁决前共识对照 |
| `D:\tmp\yeyu-ai-a3\mpv-02b-quality-baseline\20260826-000001-000014\annotation-status.md` | 历史标注状态和身份线索 |
| `D:\tmp\yeyu-ai-a3\mpv-02b-quality-baseline\20260826-000001-000014\independent-annotation-instructions.md` | 标注协议/独立性线索；不能替代 protocol version 证明 |
| `D:\tmp\yeyu-ai-a3\mpv-02b-quality-baseline\20260826-000001-000014\quality-metrics.json` | 历史指标对照；E07 必须按 v11 公式独立重算 |

E03 的 `e03_inventory_root` 是本 packet 唯一允许递归的目录。executor 必须先确认该 literal root 存在、为目录、root 及每一级祖先均非 reparse 且 containment 到该绝对路径；随后收集其全部后代目录/文件但不跟随 reparse，按规范化相对 POSIX 路径 UTF-8 bytes 升序处理。文件名匹配模式是 `annotation*.csv`、`*manifest*.json`、`*protocol*.md` 的 OR 集合；匹配文件全部进入 `entries`，不匹配的 regular file、目录和 reparse 条目全部进入 `excluded_entries`，不得静默忽略。每个 descendant 必须在 E03 inventory evidence 中记录规范化相对路径、kind、size、file SHA-256（目录/reparse 无内容时为 `null`）、CSV 的 `normalized_rows_hash`（非 CSV 为 `null`）和 disposition/reason；每个条目同时进入输入快照引用。canonical annotator 仅允许 root-relative 的 `annotation-blind-codex.csv`、`annotation-blind-glm.csv`、`annotation-blind-deepseek.csv`，TRAE 或其他重复/身份不明文件只能是 `backup`/`excluded`，且必须带非空固定 reason code。不得把该 root 扩展为 stage root、项目目录或 glob；C 盘路径、模型目录、网络资源和未来 run 输出均不属于输入。

当前没有已封存的既有 MPV-02B DQA/E 输出 literal 文件可列入 allowlist；因此 DQA-09/E08 的“previously sealed outputs”输入是一个由 preflight 固定记录的空集合/缺失记录，而不是允许读取某个未声明目录。未来若存在前一批封存输出，必须在新的授权中逐文件追加 literal allowlist 和 hash；不能读取整个 stage root。当前 run 的 `checks/DQA-09.json`、`checks/E08.json`、报告和其他输出一律排除自身作为这两项检查的输入。

E03 输入归属合同：`e03_inventory_root` 对其全部后代承担唯一 filesystem inventory ownership；`inputs-manifest.json` 对每个物理路径只记录一次。DQA/E 检查可以读取其声明的具体 descendant，但必须引用 E03 inventory entry 及其 file hash，不得再次枚举该 root、生成第二份 inventory 或主张第二个输入所有权。物理路径的“唯一归属”与下游检查的“允许消费”是两个概念；同一文件可被多个已声明检查消费，但只有 E03 inventory 负责其范围、路径、reparse、大小和文件身份记录。

E06 语义复核输入当前不在本 packet 的固定输入白名单中。executor 只能生成机械正文证据和待复核对象；若 authority owner 需要完成语义复核，必须在新的 packet revision 或授权回执中逐文件绑定一个只读 `e06-semantic-review-v1` artifact，其每条记录绑定 `query_id、doc_id、raw_body_evidence_ref、original_label、semantic_result、reviewer_ref、review_reason`，且 `semantic_result` 仅允许 `SUPPORTED`、`UNSUPPORTED`、`INSUFFICIENT_EVIDENCE`。没有该 artifact，或无法证明其逐对象覆盖和身份时，E06 固定 `UNPROVEN/30`，reason `SEMANTIC_REVIEW_INPUT_MISSING`；不得由 executor、模型或多数票代填。

## 执行器、环境和命令合同

### 当前可执行性结论

当前磁盘没有一个已证明实现 v11 全部 DQA-01..09/E01..E08 的只读 executor。`src/xiaoshuo/tools/data_quality_audit.py` 只覆盖 rhythm/commercial 旧审计，质量基线脚本只生成历史候选/指标，均不能替代本 packet。因此：

`EXECUTOR_ENTRYPOINT: BLOCKED_UNBOUND / BLOCKED:40`

未来 authority owner 必须另行绑定一个可读回、可复核的 executor 入口；不得以运行时临时脚本、旧脚本、手工聊天逻辑或本 packet 自行发明替代实现。若未完成该绑定，preflight 直接 `BLOCKED/40`，不创建 DQA run，不读取完整正文执行检查，并输出最小失败报告（仅在 run 根已通过安全 preflight 且 owner 已明确授权创建时）。

### 未来允许的命令形状

只有在 executor 已由 authority owner 绑定并写入授权回执后，才允许一次性运行如下命令形状；尖括号不是可自行替换的实现名称，必须来自授权回执：

```text
py -3.12 -X utf8 -B -m <authorized_readonly_dqa_executor> --packet "D:\Code\yeyu-ai\xiaoshuo\docs\plans\2026-08-mpv-02b-dqa-execution-packet-v1.md" --run-root "D:\tmp\yeyu-ai-a3\mpv-02b-dqa\<fresh-run-id>"
```

executor 的进程环境必须固定为：

```text
PYTHONUTF8=1
PYTHONIOENCODING=utf-8
PYTHONDONTWRITEBYTECODE=1
PYTHONPATH=D:\Code\yeyu-ai\xiaoshuo\src
```

读取规则必须显式使用 UTF-8；CSV 使用 `utf-8-sig` + RFC4180；JSON/Markdown/源码使用严格 UTF-8；不得依赖 Windows 默认 GBK。Python 使用 `-B`，不得产生 `__pycache__`。executor 不得导入或调用模型、服务、网络、index build、写入口或任何未列入 allowlist 的模块以产生副作用。

允许的未来只读 preflight/postflight 工具类别只有：PowerShell `Get-Item`/`Get-ChildItem -Force`/`Resolve-Path` 及属性读取、SHA-256 计算、严格 UTF-8 文件读取、结构化 JSON/CSV 解析，以及 `git -C D:\Code\yeyu-ai\xiaoshuo status --short` 的只读工作区核对。每一项命令必须独立记录退出码；不得将多个检查串成一个退出码。当前轮不执行这些未来命令。

## Run 根、containment 和 preflight

未来 run 根唯一形状为：

```text
D:\tmp\yeyu-ai-a3\mpv-02b-dqa\<run-id>
```

`run-id` 必须匹配 `^[0-9]{8}-[0-9]{6}-[0-9]{6}$`，是本次从未存在的新值；stage root 必须是 literal `D:\tmp\yeyu-ai-a3\mpv-02b-dqa`。run root 的 canonical/resolved path 必须在该 stage root 下，且不能是 reparse point，任何祖先也不能是 reparse point。不得使用 C 盘、项目工作区、项目内 `tmp`、历史 run、`--basetemp` 以外的临时目录或模糊 glob。

授权前 preflight 必须逐项输出独立记录和退出码：

1. packet literal path 存在、是 regular file、严格 UTF-8 可读，并且 packet 自身不被纳入 DQA-09/E08 当前 check 输入。
2. 主设计、ledger、根规则的 SHA-256 与本 packet 绑定值一致；不一致为 `BLOCKED/40`，不得执行。授权回执还必须绑定本 packet 实际 UTF-8 bytes 的 SHA-256；packet 不把自身期望 hash 写入自身，避免自引用，但 preflight、verifier-input 和报告必须精确回读授权值与实际值。
3. 所有 allowlist 路径存在、regular/reparse 属性符合要求、resolved path 不越过其声明根；缺失输入按检查合同映射，不得换用近似路径。
4. C 盘历史证据未进入输入；历史基线根不是本 run 根；项目 Git 工作区初始状态已只读记录。
5. run-id 合法且 run root、所有 output descendants、临时文件和 cache path 都 containment 到 run root；run root 必须此前不存在。若 stage root 自身不存在，创建 stage root/run root 也必须在 owner 已批准的 D 盘 run 授权内；本轮不创建。
6. 输出目录和文件名只允许本 packet 的 output allowlist；manifest/checksum 的 self-hash 排除规则已固定。
7. executor entrypoint 已由 owner 绑定、版本可读、SHA-256 可回读；executor 自身的 compile/readback 结果必须独立记录。授权回执还必须分别绑定 interpreter 的绝对路径、版本、SHA-256 和 interpreter compile/readback，以及 verifier 的 literal path、版本、SHA-256 和 verifier compile/readback；三类身份或任一对应 readback 缺失/不一致均保持 `BLOCKED/40`。
8. Python 环境、`PYTHONPATH`、UTF-8、`PYTHONDONTWRITEBYTECODE` 和禁止网络/模型/服务的进程策略满足要求。

任一 preflight 项失败即 `preflight_status=BLOCKED`，并按 run-root 安全阶段选择唯一失败路由：`ROOT_UNSAFE_BLOCKED` 表示 run root 自身或其祖先未通过存在性、resolved containment 或 reparse 检查，路径非法或越界；此状态禁止向该 root 写入任何文件，不适用任何 root 内失败封存集合，只产生不依赖该 root 的外部阻断回执并停止。外部阻断回执必须是 stdout 的单行 UTF-8 JSON，根字段顺序固定为 `schema_version、receipt_type、run_id、run_root、resolved_run_root、check_status、exit_code、reason_codes、writes_performed、next_step`；`schema_version` 为 `dqa-blocker-receipt-v1`，`receipt_type` 为 `ROOT_UNSAFE_BLOCKED`，`check_status` 为 `BLOCKED`，`exit_code` 为 `40`，`resolved_run_root` 为 `null`，`writes_performed` 为 `false`，`reason_codes` 非空，且不得向 stderr 或项目路径输出替代格式。协调者必须原样保存 stdout 字节、回读 JSON，并将其作为 ledger/授权记录的外部 receipt 引用；executor 不得自行向不安全 root、项目目录或历史 evidence 写入该回执。`ROOT_SAFE_INITIAL_FAILURE` 表示 run root 已通过上述安全检查但 preflight 的其他项目失败；此状态只允许向该安全 root 写入初始最小集合 `preflight.json`、双格式失败报告和 `seal.json`，并立即停止，不得把它称为完整 `SEALED_FAILURE`。仅当 run root 安全、执行器已获准启动且已经产生可完整列出的输入/检查输出时，才进入 `ROOT_SAFE_COMPLETE_FAILURE`，允许按完整失败集合补齐 `inputs-manifest`、已完成 check、artifact manifest、checksum、postflight（若能执行）和 `SEALED_FAILURE` seal。三种状态的输出集合互斥且固定；不得先执行部分 DQA 再补 preflight。

`ROOT_UNSAFE_BLOCKED` 的字段集合、顺序、固定值和字节合同唯一取 correction-05 v2 machine contract 的 `blocker_receipt_contract`：只允许十个字段，JSON 使用 `ensure_ascii=true`、固定字段顺序、紧凑分隔符、LF、无 BOM、无尾随空格；stdout 必须恰好一条 JSON 记录，stderr 不得输出替代回执。任何额外字段、字段缺失、顺序漂移、非 UTF-8、BOM、第二行或 coordinator 原始 stdout bytes 未保存，均为 blocker receipt 合同失败，不得将其降级为普通 preflight 失败。

## 输出 literal allowlist 与封存

未来 run 根下只允许以下相对路径和目录：

```text
packet-readback.json
preflight.json
postflight.json
inputs-manifest.json
snapshots/P.json
snapshots/O.json
snapshots/P.sha256
snapshots/O.sha256
snapshots/query-provenance.json
checks/DQA-01.json
checks/DQA-02.json
checks/DQA-03.json
checks/DQA-04.json
checks/DQA-05.json
checks/DQA-06.json
checks/DQA-07.json
checks/DQA-08.json
checks/DQA-09.json
checks/E01.json
checks/E02.json
checks/E03.json
checks/E04.json
checks/E05.json
checks/E06.json
checks/E07.json
checks/E08.json
artifacts/annotation-inventory-v1.json
artifacts/evaluation-metrics-schema-v1.json
artifacts/manifest.json
artifacts/checksums.sha256
reports/mpv-02b-dqa-report.json
reports/mpv-02b-dqa-report.md
verifier-input.json
verifier-result.json
post-review-input.json
seal.json
```

`checks/<id>.json` 必须使用主设计的 `dqa-check-envelope-v1` 根字段：`schema_version`、`check_id`、`check_status`、`exit_code`、`input_snapshot_refs`、`preconditions`、`procedure_ref`、`evidence`、`counts`、`reason_codes`、`limitations`、`stop_action`、`next_step`。状态与退出码严格为 `PASS/0`、`FAIL/10`、`UNKNOWN/20`、`UNPROVEN/30`、`BLOCKED/40`。

全 packet 的 reason-code 集合严格绑定主设计，不得增删、改名或改义：`INPUT_MISSING`、`INPUT_IDENTITY_UNPROVEN`、`ENCODING_ERROR`、`RAW_BODY_MISSING`、`TRANSFORM_UNACCOUNTED`、`BOUNDARY_GAP`、`DUPLICATE_ID`、`MAPPING_MISMATCH`、`COUNT_MISMATCH`、`SORT_CONTRACT_MISMATCH`、`QUERY_SOURCE_MISSING`、`ANNOTATOR_INDEPENDENCE_UNPROVEN`、`SNAPSHOT_REBUILD_MISMATCH`、`FORMULA_MISMATCH`、`INVALID_LABEL`、`MISSING_LABEL`、`MISSING_SCHEMA_INPUT`、`SEMANTIC_REVIEW_INPUT_MISSING`、`UNPROVEN_DENOMINATOR`、`OUT_OF_SCOPE_CLAIM`、`PREFLIGHT_FAILED`、`WORKSPACE_MUTATION`。`FAIL` 只表示能明确检测到输入/不变量违反；`UNKNOWN` 表示信息不可判定；`UNPROVEN` 表示缺少证明材料；`BLOCKED` 只表示前置失败导致检查不能开始。

成功封存只封存 executor 阶段：17 个 check 文件、两道 gate、双格式报告、输入 manifest、executor artifact manifest、executor checksum、postflight 和 executor `seal.json` 必须存在并互相引用；`verifier-input.json`、`verifier-result.json` 和 `post-review-input.json` 是 executor seal 之后的下游证据，不是 executor seal 的前置，也不纳入 executor manifest/checksum。失败封存分为两类，不能混用：`ROOT_SAFE_COMPLETE_FAILURE` 才适用完整 executor 失败封存，要求至少有 preflight、inputs-manifest、已完成 check 文件、双格式报告、executor artifact manifest、executor checksum、postflight（若能执行）和 `SEALED_FAILURE` seal；`ROOT_SAFE_INITIAL_FAILURE` 只允许前款规定的初始最小集合，不得写入或声称完整失败封存；`ROOT_UNSAFE_BLOCKED` 不允许向 run root 写入任何文件，只能产生外部阻断回执。executor 失败不能删除、覆盖或复用 run。无论哪种路由，已产生的报告均必须明确未运行项、`UNKNOWN`/`UNPROVEN`/`BLOCKED`、限制和精确下一步。

artifact manifest 必须列出每个允许输出的相对路径、kind、size、SHA-256、producer、check_id（如适用）和 self-hash exclusion。checksum 必须按相对 POSIX 路径排序，以 UTF-8 LF 结尾；manifest 和 checksum 自身不把自身 hash 放入自身 hash 输入。postflight 必须重新检查所有输出 descendants 的 containment、reparse、allowlist、字节 hash、项目 workspace 只读状态和输入未变。

## 固定执行顺序与 17 项合同

顺序只能是 `DQA-01 → DQA-02 → DQA-03 → DQA-04 → DQA-05 → DQA-06 → DQA-07 → DQA-08 → DQA-09 → E01 → E02 → E03 → E04 → E05 → E06 → E07 → E08`。前置不满足时该项为 `BLOCKED/40`，或依主设计在已有输入可判定时保留自身 `FAIL/UNKNOWN/UNPROVEN` 并写入 `downstream_disposition`；不得跳过、重排、覆盖第一次结果或用另一个检查的结果代替。

所有下列状态、退出码、reason code 和停止动作均直接绑定主设计 v11；packet 只补实际输入、procedure ref 和输出落点。

| 顺序/ID | 输入与 procedure | 独立输出与判定 | reason / 停止动作 |
|---|---|---|---|
| 1 DQA-01 | 项目三本 raw literal；`DQA-PROC-01` | source entries、编码、可读性、snapshot/identity；五状态/退出码固定 | `INPUT_MISSING`、`INPUT_IDENTITY_UNPROVEN`、`ENCODING_ERROR`；正文缺失 FAIL，停止 SOURCE |
| 2 DQA-02 | DQA-01、raw bytes、parser input；`DQA-PROC-02` | raw_body bytes、decode、replacement/empty、preview-only、body hash；五状态/退出码固定 | `ENCODING_ERROR`、`RAW_BODY_MISSING`、`TRANSFORM_UNACCOUNTED`；正文/解码失败停止依赖项 |
| 3 DQA-03 | parser、chapter records、source coordinates、三份 rhythm；`DQA-PROC-03` | chapter count/order、byte/code-point range、coverage/gap/overlap、transform；五状态/退出码固定 | `BOUNDARY_GAP`、`TRANSFORM_UNACCOUNTED`、`COUNT_MISMATCH`；不可重建 UNKNOWN，丢失/重复 FAIL |
| 4 DQA-04 | scene/sub-scene records、chapter mapping、DQA-03；`DQA-PROC-04` | scene/sub-scene count/order、range、coverage/gap/overlap、body hash；五状态/退出码固定 | `BOUNDARY_GAP`、`DUPLICATE_ID`、`TRANSFORM_UNACCOUNTED`；边界不明 UNKNOWN，重复/截断 FAIL |
| 5 DQA-05 | metadata、doc_id、book/chapter/scene/sub-scene identifiers、DQA-03/04；`DQA-PROC-05` | ID/collision、metadata fields、body binding、duplicate keys；五状态/退出码固定 | `DUPLICATE_ID`、`MAPPING_MISMATCH`、`INPUT_IDENTITY_UNPROVEN`；错映射 FAIL，停止 SOURCE 和依赖 E |
| 6 DQA-06 | sample index 四件套、metadata、vector rows、read entrance、DQA-05；`DQA-PROC-06` | index/vector/doc_id map、payload hash、exact readback；五状态/退出码固定 | `MAPPING_MISMATCH`、`RAW_BODY_MISSING`、`INPUT_IDENTITY_UNPROVEN`；错映射 FAIL，不能回读 UNKNOWN |
| 7 DQA-07 | index manifest、build manifest、DQA-01..06；`DQA-PROC-07` | 各级 count、精确 `expected_14717`、异常统计、重算 hash；五状态/退出码固定 | `COUNT_MISMATCH`、`SNAPSHOT_REBUILD_MISMATCH`、`INPUT_MISSING`；重算不一致 FAIL，输入不全 UNPROVEN |
| 8 DQA-08 | candidate results、BM25/BGE/RRF observations、DQA-06/07；`DQA-PROC-08` | query/channel/rank/doc/payload/rank map；五状态/退出码固定 | `MAPPING_MISMATCH`、`SORT_CONTRACT_MISMATCH`、`INPUT_IDENTITY_UNPROVEN`；错映射 FAIL，不能证明 UNPROVEN |
| 9 DQA-09 | 已封存 DQA/E outputs、历史 baseline boundary；排除本 check；`DQA-PROC-09` | claim scope、sample/preview limits、forbidden claims；五状态/退出码固定 | `OUT_OF_SCOPE_CLAIM`、`INPUT_IDENTITY_UNPROVEN`；越界 FAIL，停止报告发布 |
| 10 E01 | queries、存在时的 provenance source，否则 absence record；`E-PROC-01` | 24 count、类别、重复/近重复、逐 query source fields；五状态/退出码固定 | `QUERY_SOURCE_MISSING`、`INPUT_IDENTITY_UNPROVEN`、`COUNT_MISMATCH`；无来源固定 UNPROVEN，停止 E gate |
| 11 E02 | production ranking contract、query bytes、P/O pool、DQA-08；`E-PROC-02` | top_k/pool、sort/tie/RRF fields、逐 query rank diff、pool keys；五状态/退出码固定 | `SORT_CONTRACT_MISMATCH`、`COUNT_MISMATCH`、`INPUT_IDENTITY_UNPROVEN`；漂移 FAIL，生产等价不可证明 UNPROVEN |
| 12 E03 | 固定 literal `e03_inventory_root` 及其非 reparse 后代；`E-PROC-03` | inventory scope/entries、file/rows hash、disposition、identity；五状态/退出码固定 | `ANNOTATOR_INDEPENDENCE_UNPROVEN`、`INPUT_MISSING`、`INPUT_IDENTITY_UNPROVEN`、`SNAPSHOT_REBUILD_MISMATCH`；root 不安全 BLOCKED，身份不可证明 UNPROVEN，格式/键/hash 错误 FAIL |
| 13 E04 | 三 canonical annotation、协议、E03、metrics schema artifact；`E-PROC-04` | 三对 pair、label/category distribution、agreement、schema ref；五状态/退出码固定 | `INVALID_LABEL`、`MISSING_LABEL`、`FORMULA_MISMATCH`、`MISSING_SCHEMA_INPUT`；可检测错误 FAIL，语义/零分母不可判定 UNPROVEN |
| 14 E05 | adjudication、三方 raw labels、query/body evidence、DQA-02..06/E03；`E-PROC-05` | 26 dispute keys、raw/final labels、reason、evidence refs；五状态/退出码固定 | `MAPPING_MISMATCH`、`RAW_BODY_MISSING`、`INPUT_IDENTITY_UNPROVEN`；不可追溯 UNKNOWN/UNPROVEN，停止 E |
| 15 E06 | P/O snapshots、raw_body、fixed sampling config、可选的 owner-authorized semantic review artifact、E03/DQA-02..06；`E-PROC-06` | P/O hashes、seed、strata/N/K、actual keys、body evidence、support result；五状态/退出码固定 | `SNAPSHOT_REBUILD_MISMATCH`、`RAW_BODY_MISSING`、`BOUNDARY_GAP`、`SEMANTIC_REVIEW_INPUT_MISSING`；不可重建或无语义输入 UNPROVEN，双重重建不等 FAIL |
| 16 E07 | qrels/consensus、rank observations、metrics schema、E02..E06；`E-PROC-07` | per query/channel、category、overall、denominator、formula/schema refs；五状态/退出码固定 | `FORMULA_MISMATCH`、`MISSING_LABEL`、`UNPROVEN_DENOMINATOR`、`MISSING_SCHEMA_INPUT`；漂移 FAIL，分母不可证 UNPROVEN |
| 17 E08 | 已封存 E01..E07 outputs 和 gate states；排除本 check；`E-PROC-08` | supported/unsupported claims、sample boundary、gate refs；五状态/退出码固定 | `OUT_OF_SCOPE_CLAIM`、`INPUT_IDENTITY_UNPROVEN`；越界或绝对真值 FAIL，停止 E gate |

## 连续性、排序和指标不变量

DQA-02..07 必须分别 hash 原始文件 bytes、严格 UTF-8 解码章节 `raw_body` bytes、每个 scene/sub-scene `raw_body` bytes 和 metadata canonical JSON bytes。禁止以 `strip()`、NFC、换行替换、过滤、拼接、截断后的 bytes 冒充原文。raw file→chapter 必须同时记录 byte 和 code-point 半开区间、解码/BOM/换行规则；chapter→scene→sub-scene 每一级必须记录未变换输入区间、允许的边界空白变换及参数、输出区间和 raw hash。覆盖、重叠、缺口和 `doc_id → metadata → body_hash/boundary → vector row` 一一映射必须独立重算；`14,717` 仅是三本当前样本索引的精确预期，不是全库结论。

E02 固定 `top_k=10`、`candidate_pool=min(max(top_k*5,20),n)`，在 `n>=50` 时 BM25/BGE 宽度为 50；排序表达式、NumPy kind/default、输入索引顺序、反转顺序、RRF `k=60`、首次插入 tie 顺序和 top-10 截断必须有实现/输入身份。三路 top-10 pooled doc union 的唯一键为 `(query_id,doc_id)`，全批预期为 472；O 观察键是 `(query_id,doc_id,retrieval_channel,rank)`，不改变 P 的 472 计数。无法绑定生产等价身份时 E02 固定 `UNPROVEN`，不得重建基线。

E03 的 canonical annotator allowlist、映射优先级、RFC4180/UTF-8/NFC/LF `normalized_rows_hash`、不可变列和 0/1/2 约束严格复用主设计。E03 的唯一业务前置依赖是 `DQA-05=PASS`；它不依赖 E01/E02 或其他 E 检查。相同 file hash、rows hash、session 或同一内容多身份都不能证明独立性，E03 固定 `UNPROVEN`。

## 两道质量门、污染传播和降级

`SOURCE_DATA_GATE` 覆盖 DQA-01..08。全部为 PASS 且没有 `UNKNOWN`、`UNPROVEN`、`FAIL` 才是 `PASS`；DQA-09 不参与 source 聚合。

`EVALUATION_DATA_GATE` 覆盖 E01..08。所有 E check 为 PASS 且 `SOURCE_DATA_GATE=PASS` 才是 `PASS`。唯一业务依赖矩阵为：E01 无 DQA/E 依赖；E02→DQA-05/06/07/08；E03→DQA-05；E04→E03；E05→DQA-02/03/04/05/06/E03；E06→DQA-02/03/04/05/06/E03；E07→E02/03/04/05/06；E08→E01/02/03/04/05/06/07。packet、verifier、post-review 是执行治理前置，不改变上述业务依赖。传递传播和污染处置仍唯一以本 packet 的五状态真值表为准。

逐门聚合优先级不是数字比较，而是 `FAIL > BLOCKED > UNPROVEN > UNKNOWN > PASS`，映射为 `10/40/30/20/0`。SOURCE 非 PASS 时，依赖检查保留自身原始状态但同时设置 downstream disposition：SOURCE `FAIL`→`INVALIDATED`，`BLOCKED`→`BLOCKED`，`UNPROVEN`→`CONTAMINATED`，`UNKNOWN`→`CONTAMINATED`；传递闭包向所有下游传播。非依赖 E01/E03 可保留独立原始结果，但不能抵消 source 状态。E check 自身 `FAIL/BLOCKED` 不得被污染处置降级。`INVALIDATED`/`CONTAMINATED` 不是 check status，不占用退出码。

任何门为 `UNKNOWN`/`UNPROVEN`/`BLOCKED` 时，报告只能输出对应降级和边界；不得报告质量有效 PASS、关闭门或开展质量驱动优化。owner 接受延期只能形成带限制的诊断测量。

## E06 固定抽样和正文复核

E06 必须执行两次彼此独立、无副作用的重建，输入同一已封存 P/O 完整快照、同一 seed 和同一规则；两次的 P/O hash、每层 N/K、mandatory 集合、实际 O/P key 清单和最终复核对象集合必须逐字段相等。第二次不得覆盖第一次。任一不等为 `FAIL/10`，reason `SNAPSHOT_REBUILD_MISMATCH`。

- P 是 472 个唯一 `(query_id,doc_id)`，字段顺序固定：`query_id, query_category, book, doc_id, final_label`。P 不含通道/rank。
- O 是唯一 `(query_id,doc_id,retrieval_channel,rank)` 观察行，字段顺序固定：`query_id, query_category, book, doc_id, retrieval_channel, rank, final_label`。同一 query/doc 跨通道保留多行；同通道重复四元组是输入错误；正文复核按 P 去重。
- P/O 分别按 canonical key 排序形成完整 UTF-8 canonical JSON 数组并 hash 完整 JSON bytes；不能只 hash key，也不能把 O 拼入 P。
- 26 条完全分歧项全部 mandatory；最终标签为 2 的 P 全部 mandatory；两者按 P key 去重并保留三方标签/裁决理由。
- 最终标签为 0/1 且不在 mandatory 的 P，按 `query_category × book × retrieval_channel` 形成 O 分层框。每个非空层 `K_layer=min(N_layer,30)`，其中 `N_layer` 是过滤后唯一 O 行数；不足 30 全量复核。一个 P 可落入多个通道层，但正文只复核一次并保留所有命中的 O key/层。
- 固定 seed：`mpv-02b-dqa-e06-v1`。canonical key 字段顺序为 `query_id, doc_id, retrieval_channel, rank`；字符串 UTF-8/NFC、保留大小写、空值为 JSON `null`；`ensure_ascii=false`、固定字段顺序、紧凑分隔符。排序输入是 `seed + "|" + canonical_key` 的 SHA-256 十六进制值，再以 canonical key UTF-8 bytes 决胜。
- 抽样配置、P/O 完整快照 hash、各层 N/K、实际 O/P key、对应 P、来源通道、完整 raw_body 引用和结论必须入报告。正文结论只允许 `SUPPORTED`、`UNSUPPORTED`、`INSUFFICIENT_EVIDENCE`。

E06 的 30 条上限只给出零发现时约 95% 置信度下的约 10% 有界上限，不排除系统性假阴性。E06 只能证明指定样本中的正文支持程度和部分假阴性风险，不能证明所有标签准确、没有系统偏差或 query 代表全部用户意图。raw_body、P/O 快照、边界或抽样框不可证明时为 `UNPROVEN`，不得用 preview 冒充完整正文。

## E04/E07 JSON 和指标合同

未来 executor 必须生成并回读由 output allowlist 绑定的 `evaluation-metrics-schema-v1` artifact；具体路径和文件名以本 packet 的 output allowlist 为准。禁止额外根字段；根字段及顺序固定为：`schema_version`、`check_id`、`check_status`、`exit_code`、`reason_codes`、`counts`、`per_pair`、`per_query`、`per_category`、`overall`、`formula_version`、`label_semantics_ref`、`label_order`、`input_snapshot_refs`、`canonicalization`。`label_order` 必须是 `[0,1,2]`；数值只能是有限 JSON number 或 null；未知状态必须有非空 reason code。E04/E07 schema、required/nullable/enum、错误映射和 canonical hash 都进入证据。

E04 在 472 个共同有效 key 上重算三对 nominal、unweighted Cohen kappa，固定 `p_o`、`p_e`、`kappa` 公式；非法/缺失标签不得静默删除。`INVALID_LABEL`、`MISSING_LABEL`、`MISSING_SCHEMA_INPUT`、`UNPROVEN_DENOMINATOR`、`FORMULA_MISMATCH` 是唯一 E04/E07 错误映射集合。E04 的 0/1/2 语义必须引用协议，不由指标脚本推断。

E07 对每个 query/channel 计算 `Recall@5`、`MRR@10`、`nDCG@10`；相关定义是 `final_label>0`，P 是三通道 top-10 union，ideal ranking 按 `(-gain,doc_id)`，`gain=2^final_label-1`。分母为 0、IDCG 为 0、未标注或 key 缺失均为 `UNPROVEN`，不填 0或静默排除。按 query category 做 macro，再按 24 条 query 做 overall macro；不得使用 micro/候选行加权。结果名称必须保留 `pooled_top10_per_channel_diagnostic`，不是全库 Recall 或生产质量结论。

canonical JSON 使用 UTF-8、`ensure_ascii=false`、`sort_keys=false`、紧凑分隔符、LF 终止，禁止 NaN/Infinity；hash 不含外部 hash 字段。E07 必须引用 E04 的 `label_semantics_ref`、`label_order`、schema version 和 canonical bytes/hash。

## 报告、verifier 和 post-review

`reports/mpv-02b-dqa-report.json` 是机器报告，必须含 packet/plan/ledger binding、run、input snapshot refs、17 项 check envelope 引用、两道 gate、污染 disposition、统计、reason codes、限制、未运行项、`SEALED_SUCCESS`/`SEALED_FAILURE` 和精确下一步。`reports/mpv-02b-dqa-report.md` 是同一事实的中文 Markdown，不能有 JSON 未反映的结论。两者成功/失败都必须存在并逐项可交叉回读。

executor 完成并写入 `seal.json` 后，协调者才能生成 `verifier-input.json`；它只允许包含 packet 和主设计/ledger 绑定、authorization receipt、preflight、inputs-manifest、全部已产生 check、E03/E04/E07 schema/inventory artifact、P/O hash、report、executor artifact manifest/checksum、postflight、executor seal、只读 workspace 状态和未运行边界。证据链严格单向：`executor outputs → executor seal → verifier-input → verifier-result → post-review-input`；verifier 不属于 executor seal 的前置，也不得反向要求 verifier-result 才能写 executor seal。verifier 只读 executor seal 及其引用，独立重算文件身份、canonical bytes/hash、containment、状态/退出码/原因映射、17 行完整性、门禁传播和报告一致性，并将结果写入独立的 `verifier-result.json`；verifier 不修复候选结果，也不修改 executor seal 或 executor artifact。

只有 `verifier-result.json` 已写入并通过其自身 hash/readback 后，协调者才能生成 `post-review-input.json`。它必须包含 executor seal、verifier-result 及其 hash、实际 output diff、授权白名单对照、失败/成功封存状态、未证明项和所有必要证据。post-reviewer 必须是与 planner_a、planner_b、executor、verifier 可区分的新一次性角色；只发送一次完整复核指令并进行一次有界等待。结果只能是 `POST-REVIEW: ACCEPTED` 或 `POST-REVIEW: CHANGES_REQUIRED`，无最终回执为 `REVIEW_PENDING`/`REVIEW_UNAVAILABLE`，不得推断接受或关闭。

只有同时满足：授权/packet/allowlist 一致；preflight/postflight 通过；必需 artifacts、双报告和 checksum 完整；没有未经 owner 接受的 `FAIL/BLOCKED/UNKNOWN/UNPROVEN`；verifier 通过；post-review `ACCEPTED`；owner 明确裁决，才可以将执行批次标为 `CLOSED`。任何失败必须封存原 run，建立 fresh run 和新授权/新复核范围；不得原地修复或重试。

## Packet correction 01 receipt and finding map

- `correction_id`: `MPV-02B-DQA-PACKET-CORRECTION-01`
- `source_receipt`: Halley final receipt, `PACKET-REVIEW: CHANGES_REQUIRED`
- `source_reviewer`: one-time independent packet reviewer; closed immediately after final receipt
- `current_state`: `PACKET_CORRECTION_01 / PACKET_REVIEW_REQUIRED / DQA_NOT_AUTHORIZED`
- `scope_decision`: five findings were narrow packet-contract corrections; no main-design, source-code, data, index, or execution scope was added.

| finding_id | lineage | correction location | verification contract | current status |
|---|---|---|---|---|
| DQA-PACKET-F01 | NEW | design binding table, root-rule identity | exact root-rule SHA readback against authorization/preflight | PACKET_REVIEW_REQUIRED |
| DQA-PACKET-F02 | NEW | preflight and authorization contract | packet SHA bound by authorization and compared without self-reference | PACKET_REVIEW_REQUIRED |
| DQA-PACKET-F03 | NEW | executor binding, preflight, authorization next step | executor/interpreter/verifier path, version, SHA and compile/readback all present | PACKET_REVIEW_REQUIRED |
| DQA-PACKET-F04 | NEW | preflight failure and failure-seal routing | unsafe run root produces no root write and only external blocking receipt | PACKET_REVIEW_REQUIRED |
| DQA-PACKET-F05 | NEW | BM25 input allowlist and read rule | static or strict non-executing pickle inspection; unsafe parse is BLOCKED/40 | PACKET_REVIEW_REQUIRED |

No finding is treated as execution evidence or quality-gate PASS. A new one-time independent reviewer must recheck this correction before any authorization decision.

## Packet correction 02 receipt and finding map

- `correction_id`: `MPV-02B-DQA-PACKET-CORRECTION-02`
- `source_receipt`: Hypatia final receipt, `PACKET-REVIEW: CHANGES_REQUIRED`
- `source_reviewer`: one-time independent packet reviewer; closed immediately after final receipt
- `predecessor_correction`: `MPV-02B-DQA-PACKET-CORRECTION-01`
- `current_state`: `PACKET_CORRECTION_02 / PACKET_REVIEW_REQUIRED / DQA_NOT_AUTHORIZED`
- `scope_decision`: 两项修正只澄清工具身份和失败封存路由，没有新增 DQA 检查或扩大执行范围。

| finding_id | lineage | correction location | verification contract | current status |
|---|---|---|---|---|
| DQA-PACKET-F03 | UNRESOLVED | executor/interpreter/verifier preflight and authorization contract | 三类身份分别具备 literal path、version、SHA-256 和各自 compile/readback，全部为授权前硬条件 | PACKET_REVIEW_REQUIRED |
| DQA-PACKET-F04 | UNRESOLVED | preflight failure and failure-seal routing | 安全 root 才允许初始/完整失败封存；不安全 root 禁止 root 写入，仅外部阻断回执 | PACKET_REVIEW_REQUIRED |

correction 02 的预期收束条件是：复核返回 `PACKET-REVIEW: ACCEPTED` 后转为 `PACKET_FROZEN / AUTHORIZATION_REQUIRED / DQA_NOT_AUTHORIZED`，停止设计批次的字段补充；该条件已由 correction 03 继续澄清，不改变历史记录。后续执行缺少的 runtime 证据只能进入新鲜 run；既定合同违反时按失败路由和 owner 决策处理，不重新开启本 packet 设计循环。

## Packet correction 03 receipt and finding map

- `correction_id`: `MPV-02B-DQA-PACKET-CORRECTION-03`
- `source_receipt`: Sagan final receipt, `PACKET-REVIEW: CHANGES_REQUIRED`
- `source_reviewer`: one-time independent packet reviewer; closed immediately after final receipt
- `predecessor_correction`: `MPV-02B-DQA-PACKET-CORRECTION-02`
- `current_state`: `PACKET_CORRECTION_03 / PACKET_REVIEW_REQUIRED / DQA_NOT_AUTHORIZED`
- `scope_decision`: 只澄清失败封存状态机和设计收敛停止规则；没有新增检查、运行器或执行范围。

| finding_id | lineage | correction location | verification contract | current status |
|---|---|---|---|---|
| DQA-PACKET-F04 | UNRESOLVED | preflight and failure-seal routing | ROOT_UNSAFE_BLOCKED、ROOT_SAFE_INITIAL_FAILURE、ROOT_SAFE_COMPLETE_FAILURE 三态及互斥输出集合明确 | PACKET_REVIEW_REQUIRED |
| DQA-PACKET-F06 | NEW | correction 03 freeze rule and current state | 接受后转 PACKET_FROZEN；执行期 UNPROVEN 不重新开启设计补字段 | PACKET_REVIEW_REQUIRED |

correction 03 复核若返回 `PACKET-REVIEW: ACCEPTED`，packet 即转为 `PACKET_FROZEN / AUTHORIZATION_REQUIRED / DQA_NOT_AUTHORIZED`，本批次停止新增设计字段。之后只允许进入授权评估、执行证据或 owner 指定的新修正范围；执行期 `UNPROVEN` 不得重新开启本 packet 设计循环。

## Packet final review receipt

- `receipt_id`: `MPV-02B-DQA-PACKET-RECEIPT-20260828-FINAL`
- `reviewer_role`: 一次性独立 packet reviewer
- `reviewer_agent_id`: `01a0487e-0f7d-7b23-89d9-00dfcb457a1a`
- `review_token`: `PACKET-REVIEW: ACCEPTED`
- `scope_token`: `PLAN-SCOPE-REVIEW: SUFFICIENT`
- `reviewed_correction`: `MPV-02B-DQA-PACKET-CORRECTION-03`
- `review_result`: F03/F04/F06 已闭合；无新设计 finding；17 项检查、两道质量门、E01/E02/E06、只读边界和失败路由保持不变。
- `reviewer_lifecycle`: final receipt received; agent closed immediately; context will not be reused
- `execution_boundary`: 未创建 DQA run，未执行 DQA、测试、模型、服务、网络、索引或性能活动。
- `current_state`: `PACKET_FROZEN / AUTHORIZATION_REQUIRED / DQA_NOT_AUTHORIZED`

该接受只表示 packet 设计冻结并可进入授权评估，不表示 DQA 执行授权、质量门 PASS、生产质量证明或索引授权。执行期尚未产生的事实继续保持 `UNPROVEN`。

## Executor contract correction 04

- `correction_id`: `MPV-02B-DQA-EXECUTOR-CONTRACT-CORRECTION-04`
- `source_receipt`: Sol executor design receipt, `EXECUTOR-DESIGN: CHANGES_REQUIRED`
- `predecessor_event`: `MPV-02B-DQA-LE-20260830-019`
- `delta_class`: `MATERIAL_REVIEW_CHANGE`
- `machine_contract_source`: `dqa-check-contract-matrix-v1.json`
- `changes`: 17 项检查改由 packet-bound machine projection 作为唯一执行合同；输入固定分为 required literal、optional absence allowed 和唯一 E03 recursive root；不安全 run root 只返回固定 UTF-8 stdout blocker receipt。
- `not_changed`: 不新增检查，不改变业务语义、状态/退出码、reason code、依赖关系、gate 聚合、禁止活动或授权边界。
- `verification`: fresh Reviewer 对 machine source、packet projection、输入类别、阻断回执字段和本 correction 白名单做逐项 readback。
- `current_state`: `PLAN_B_REVIEW_REQUIRED / CONSENSUS_BLOCKED / DQA_NOT_AUTHORIZED`

在新的独立 Reviewer 最终回执前，不得实现 executor、运行测试、创建 DQA run 或执行 DQA；F-EXE-001 仍必须在未来授权时绑定真实 executor/interpreter/verifier 身份。



## PLAN-SCOPE-REVIEW

`PLAN-SCOPE-REVIEW: SUFFICIENT`

理由：packet 仅覆盖 DQA-01..09/E01..E08、两道质量门和其证据封存；没有加入性能、索引构建、模型、服务、网络、数据库、第三方框架或无证据收益的复杂 orchestration。性能仅保留为两道 gate 通过后的独立后置阶段依赖，不属于本 packet。

## PLAN_CONTRACT_PREFLIGHT

`PLAN_CONTRACT_PREFLIGHT: PENDING_CORRECTION_05_REVIEW`

逐项绑定结果：主设计 v11 的 v2 `check_contract_matrix` 17/17 行已映射；每行均保留 input、precondition、procedure、output/evidence、status/exit、reason、blocking/stop、verification 和 owner disposition。packet 只实例化 literal inputs、future command shape、run/output containment 和封存，不改变业务状态、退出码、reason code、依赖或 gate 关系。E06 的 P/O、26 mandatory、label-2 mandatory、0/1 分层、seed、N/K、正文复核已逐项冻结；DQA-09/E08 已排除当前 check 自引用。当前仅等待 correction-05 的独立 Reviewer；在最终接受回执前，预审不是通过状态。

但当前 `EXECUTOR_ENTRYPOINT` 仍为 `BLOCKED_UNBOUND`。这不是 packet contract 缺口，而是未来执行授权的明确前置；在 authority owner 绑定并独立核对 executor 前，不得把本 packet 标为可执行或创建 DQA run。correction-05 的独立 Reviewer 尚未返回最终回执，因此当前合同预审仍为 `PENDING_CORRECTION_05_REVIEW`。

## 未证明项和停止条件

- 当前没有 DQA runtime 证据、fresh run、输入快照、独立 verifier 或 post-review；主设计 acceptance 不等于 DQA PASS。
- E01 的逐条原始 query provenance 是否存在尚未证明；缺失时固定 `E01=UNPROVEN/30`。
- E02 的生产等价实现/输入 identity、tie 行为和 472 pool 是否可由允许输入证明尚未证明；不可证明时 `UNPROVEN/30`，明确漂移时 `FAIL/10`。
- E03 的三方独立身份、session 和 protocol binding 尚未证明；相同内容或身份重叠不能被解释为独立。
- 完整 raw_body 与三本书 raw→chapter→scene→metadata→vector 连续性尚未运行重算；preview 不能证明正文。
- E06 两次独立重建、P/O hash、分层样本、全部 label-2 和 26 裁决正文证据尚无运行结果。
- E04/E07 schema、公式、canonical bytes/hash 和负例映射尚无运行回读。
- `data_quality_audit.py`、历史 baseline scripts 和任何手工 executor 都不是当前 packet 的合法执行入口。

遇到 packet/plan/ledger hash 不一致、输入身份不明、reparse/containment 失败、工作区突变、输出越界、executor 未绑定、canonical hash 不一致、检查前置失败或失败后想原地重试，立即 `BLOCKED/40` 或按对应检查的固定状态封存并停止。不得改写历史证据、不得删除失败 run、不得自行发明降级逻辑。

## 当前授权边界与精确下一步

当前授权边界：本 packet 当前为 `PLAN_B_REVIEW_REQUIRED / CONSENSUS_BLOCKED / DQA_NOT_AUTHORIZED`；旧 `CONSENSUS_READY` receipt 仅为历史设计复核，不覆盖本 correction。根规则授权前置必须绑定当前磁盘 `D:\Code\yeyu-ai\AGENTS.md` 的 SHA `41D233E741BB9351AEFC484D5AB35F91F1F3201435399B5C6B309F36009332E1`。本轮只授权新 packet 文档的设计落盘，不授权 run、输入快照、DQA、测试、模型、服务、网络、索引、性能或 post-review。

精确下一步：authority owner 只读复核本 packet 与绑定的主设计/ledger，补发一次新的 `MPV-02B DQA READONLY EXECUTION AUTHORIZATION`，其中必须明确 packet SHA-256、fresh run-id、future executor literal path/version/SHA-256、executor compile/readback、interpreter 绝对路径/version/SHA-256/compile-readback、verifier literal path/version/SHA-256/compile-readback、是否允许创建 D 盘 run，并确认本 packet 的输入/输出 allowlist；随后由 executor 在一次 fresh run 中按本 packet 执行，独立 verifier 读取封存证据，再由全新一次性 post-reviewer 给出 post-review token。任何一步缺少授权、executor 绑定或最终回执，都保持 `DQA_NOT_AUTHORIZED`、`BLOCKED`、`REVIEW_PENDING` 或 `REVIEW_UNAVAILABLE`，不关闭阶段。

## Executor contract correction 05

- `correction_id`: `MPV-02B-DQA-EXECUTOR-CONTRACT-CORRECTION-05`
- `source_receipt`: Euler 一次性独立 Reviewer 回执，`EXECUTOR-DESIGN-REVIEW: CHANGES_REQUIRED`
- `plan_path`: `D:\Code\yeyu-ai\xiaoshuo\docs\plans\2026-08-mpv-02b-dqa-design-v11.md`
- `packet_path`: `D:\Code\yeyu-ai\xiaoshuo\docs\plans\2026-08-mpv-02b-dqa-execution-packet-v1.md`
- `ledger_path`: `D:\Code\yeyu-ai\xiaoshuo\docs\plans\2026-08-mpv-02b-dqa-finding-ledger-v11.md`
- `predecessor_event`: `MPV-02B-DQA-LE-20260830-021`
- `plan_revision`: `PLAN_A_EXECUTOR_CONTRACT_CORRECTION_05`
- `packet_revision`: `PLAN_A_EXECUTOR_CONTRACT_CORRECTION_05`
- `ledger_revision`: `MPV-02B-DQA-LEDGER-11-EXECUTOR-CORRECTION-05`
- `current_event`: `MPV-02B-DQA-LE-20260830-022`
- `machine_contract_source`: `governed-contract-source/v2`; matrix SHA `204aec682b3a9ddd40a701a9c752e77dd3c67ba954278911c2a389fc02e014fd`; contract digest `c9a8bd12a70784932573256f283a6c3799b46abc0fa75c9e9b7810d47a5d2b02`
- `registry_binding`: `.agents/skills/governed-token-efficient-collaboration/references/rule-registry.json`, revision `rules-r2`, SHA `74889D655BA721BF80CBFF7396D8A057ADEA061AEC17A220AB2331F6358DD067`
- `active_root_rules_sha256`: `41D233E741BB9351AEFC484D5AB35F91F1F3201435399B5C6B309F36009332E1`
- `scope_review`: `PLAN-SCOPE-REVIEW: SUFFICIENT`; only six executor-contract/identity issues are corrected; DQA business checks, E02/E06, both gates and authorization boundary are unchanged.
- `input_ownership`: the E03 root owns one inventory of all descendants; `inputs-manifest.json` records each physical path once; downstream checks may consume named descendants by E03 entry/hash but may not create a second inventory or ownership claim.
- `blocker_receipt_contract`: `ROOT_UNSAFE_BLOCKED` is exactly one UTF-8 LF/no-BOM canonical JSON object on stdout, with only the ten frozen fields from the v2 machine contract; stderr and project/run-root writes are forbidden, and the coordinator preserves the raw stdout bytes externally.
- `current_state`: `PLAN_B_REVIEW_REQUIRED / CONSENSUS_BLOCKED / DQA_NOT_AUTHORIZED`
- `review_requirement`: correction-05 must receive a final receipt from a new one-time independent Reviewer; before that, no `CONSENSUS_READY`, executor implementation, test, run creation or DQA execution.

### Correction-05 finding map

| finding_id | lineage | minimal correction | verification | current_status |
|---|---|---|---|---|
| DQA-EXEC-F05 | UNRESOLVED | upgrade machine matrix to v2 with registry, status enums and transitions | v2 contract verifier and exact matrix/digest readback | DESIGN_BLOCKER_PENDING_REVIEW |
| DQA-EXEC-F06 | UNRESOLVED | define one physical-path inventory owner and downstream reference rule | inventory/manifest ownership and overlap readback | DESIGN_BLOCKER_PENDING_REVIEW |
| DQA-EXEC-F07 | UNRESOLVED | freeze strict blocker receipt field set, order, encoding and save boundary | negative receipt/schema and raw stdout byte readback | DESIGN_BLOCKER_PENDING_REVIEW |
| DQA-EXEC-F08 | UNRESOLVED | synchronize active root-rule provenance in current packet bindings | fresh root SHA and three-document binding readback | DESIGN_BLOCKER_PENDING_REVIEW |
| DQA-EXEC-F09 | UNRESOLVED | replace contradictory packet preflight status with pending-review state | top/tail state readback and ledger binding | DESIGN_BLOCKER_PENDING_REVIEW |
| DQA-EXEC-F10 | UNRESOLVED | bind correction-05 event, predecessor and ledger revision in design | three-document event/revision/predecessor readback | DESIGN_BLOCKER_PENDING_REVIEW |

## Executor preparation correction 01

- `correction_id`: `MPV-02B-DQA-EXECUTOR-PREPARATION-CORRECTION-01`
- `source_receipt`: 一次性 Sol planner 设计回执，`EXECUTOR_DESIGN: CHANGES_REQUIRED`
- `predecessor`: `MPV-02B-DQA-LE-20260828-012` / `MPV-02B-DQA-PACKET-RECEIPT-20260828-FINAL`
- `current_state`: `EXECUTOR_PREPARATION_CORRECTION_01 / PACKET_REVIEW_REQUIRED / DQA_NOT_AUTHORIZED`
- `scope_decision`: 只修正 executor、verifier、E06 语义输入和 E03 依赖合同；不新增 DQA 检查，不实现 executor，不创建 DQA run。

本 correction 的证据链固定为单向阶段：`executor outputs → executor seal → verifier-input → verifier-result → post-review-input`。executor seal 只封存 executor 自身输出及其 manifest/checksum；`verifier-result.json` 和 `post-review-input.json` 不属于 executor seal 的前置或 executor checksum 范围。verifier 只能读取 executor seal 及其引用并写入 verifier result；post-review input 只能在 verifier result 完成并回读后生成。

E06 的 executor 输出只允许机械正文证据和待复核对象，不能生成 `SUPPORTED` 或 `UNSUPPORTED`。只有授权负责人绑定的逐对象 `e06-semantic-review-v1` 输入能够提供语义复核结论；该输入缺失、不可读或覆盖/身份无法证明时，E06 固定为 `UNPROVEN/30`，reason code 为 `SEMANTIC_REVIEW_INPUT_MISSING`，且 `EVALUATION_DATA_GATE` 不得 `PASS`。

E03 的唯一业务前置依赖是 `DQA-05=PASS`，以本 packet 的依赖矩阵为唯一权威；packet、verifier 和 post-review 属于执行治理前置，不改变业务检查依赖关系。

| finding_id | root_cause_id | lineage | correction_location | verification_evidence | current_status |
|---|---|---|---|---|---|
| DQA-EXEC-F01 | RC-DQA-VERIFIER-SEAL-CYCLE | NEW | verifier/seal/post-review section | 新 reviewer 核对单向证据链和 executor seal 的独立封存边界 | DESIGN_BLOCKER_PENDING_REVIEW |
| DQA-EXEC-F02 | RC-DQA-E06-SEMANTIC-INPUT | NEW | E06 input/outputs/reason-code sections | 新 reviewer 核对无受控语义输入时的 `UNPROVEN/30` 降级和 gate 阻断 | DESIGN_BLOCKER_PENDING_REVIEW |
| DQA-EXEC-F03 | RC-DQA-DEPENDENCY-WORDING | NEW | E03 dependency paragraph and dependency matrix | 新 reviewer 核对唯一 `E03→DQA-05` 业务依赖且无自然语言歧义 | DESIGN_BLOCKER_PENDING_REVIEW |

本 correction 不产生 `CONSENSUS_READY`，不授予 executor 实现、测试或 DQA 执行授权。必须由全新一次性独立 reviewer 完成一次有界复核并返回最终 token；在此之前保持 `PACKET_REVIEW_REQUIRED / DQA_NOT_AUTHORIZED`。

## Executor preparation correction 02

- `correction_id`: `MPV-02B-DQA-EXECUTOR-PREPARATION-CORRECTION-02`
- `source_receipt`: 一次性独立 planner_b/Reviewer 回执，`PLAN-B-REVIEW: CHANGES_REQUIRED`
- `predecessor_event`: `MPV-02B-DQA-LE-20260828-013`
- `scope_decision`: 仅修复 correction-01 的 plan/packet/ledger 自描述版本绑定；不新增 DQA 检查，不改变业务依赖、执行合同或授权边界。
- `plan_revision`: `PLAN_A_EXECUTOR_CONTRACT_CORRECTION_02`
- `packet_revision`: `PLAN_A_EXECUTOR_CONTRACT_CORRECTION_02`
- `ledger_revision`: `MPV-02B-DQA-LEDGER-11-EXECUTOR-CORRECTION-02`
- `current_event`: `MPV-02B-DQA-LE-20260828-014`
- `predecessor_event`: `MPV-02B-DQA-LE-20260828-013`
- `current_state`: `PACKET_FROZEN / AUTHORIZATION_REQUIRED / DQA_NOT_AUTHORIZED`

本 correction 补齐 ledger 自身的 `ledger_revision`，并要求主设计、packet、ledger 对 plan/packet/ledger revision、current event 和 predecessor event 进行双向精确回读。correction-01 的历史文本保留，不改写历史 receipt 或事件。仍不得创建 DQA run、执行 DQA、测试、模型、服务、网络、索引或性能活动；修正后必须由全新一次性独立 Reviewer 复核。

### Correction 02 independent review receipt

- `receipt_id`: `MPV-02B-DQA-PLANB-RECEIPT-20260829-CORRECTION-02`
- `reviewer_role`: 一次性独立 planner_b/Reviewer
- `reviewer_thread`: `01a04d90-d77a-74f1-8f98-ee2c00e64b78`
- `review_token`: `PLAN-B-REVIEW: ACCEPTED`
- `scope_token`: `PLAN-SCOPE-REVIEW: SUFFICIENT`
- `review_result`: correction-02 的 plan/packet/ledger revision、event、predecessor、自描述 ledger_revision 和 packet 引用的 design/ledger SHA 均与磁盘一致；未发现阻断 Finding。
- `reviewer_lifecycle`: final receipt received; agent archived immediately; context will not be reused
- `evidence_boundary`: 仅接受 correction-02 文档绑定；未执行 DQA、测试、索引、模型、服务、网络或性能活动，不证明任何质量门 PASS。

该回执使 packet 达到 `PACKET_FROZEN / AUTHORIZATION_REQUIRED`，但不构成 DQA 执行授权。

## Executor preparation correction 03

- `correction_id`: `MPV-02B-DQA-EXECUTOR-PREPARATION-CORRECTION-03`
- `source_receipt`: 用户提供的最新独立 Reviewer 回执，`EXECUTOR-DESIGN-REVIEW: CHANGES_REQUIRED`
- `predecessor_event`: `MPV-02B-DQA-LE-20260828-014`
- `plan_revision`: `PLAN_A_EXECUTOR_CONTRACT_CORRECTION_03`
- `packet_revision`: `PLAN_A_EXECUTOR_CONTRACT_CORRECTION_03`
- `ledger_revision`: `MPV-02B-DQA-LEDGER-11-EXECUTOR-CORRECTION-03`
- `current_event`: `MPV-02B-DQA-LE-20260829-015`
- `root_rules_path`: `D:\Code\yeyu-ai\AGENTS.md`
- `root_rules_sha256`: `AFAA39433E9EAA15A118F5BB83B92EA7180D9A095CA8B308CA3B657D47CCF6B6`
- `current_state`: `CHANGES_REQUIRED / DQA_NOT_AUTHORIZED`

本 correction 只同步当前根规则 SHA，并将 E03 固定为唯一的 literal `e03_inventory_root` 递归 inventory 合同。历史 correction-01/02 的事件和 receipt 原文保留，不改写；本 correction 不新增检查，不改变 DQA-01..09/E01..E08 业务语义、两道质量门、E02、E06 或指标公式。

### E03 唯一输入合同

`e03_inventory_root` 必须是本 packet 输入表中的一个绝对 literal 目录路径。它是唯一允许递归枚举的范围；递归只读，禁止 glob、目录扩展、跟随 reparse point 或越过该 root 的规范化绝对路径。遍历先收集 root 下所有后代目录和文件，再按 Unicode NFC、POSIX `/` 规范化后的相对路径 UTF-8 bytes 升序处理。文件名匹配模式固定为 `annotation*.csv`、`*manifest*.json`、`*protocol*.md` 的 OR 集合。

匹配文件全部进入 `entries`；不匹配的 regular file、目录和 reparse 条目全部进入 `excluded_entries`，不得静默忽略。每个 descendant 必须在 E03 inventory evidence 和输入快照引用中记录 `relative_path`、`kind`、`size_bytes`、`file_sha256`、`normalized_rows_hash`、`disposition`、`reason_code`。canonical annotator 仅允许 root-relative 的 `annotation-blind-codex.csv`、`annotation-blind-glm.csv`、`annotation-blind-deepseek.csv`；TRAE 或其他重复/身份不明文件只能标记 `backup` 或 `excluded`，并填写非空固定 reason code。

root 不存在或不可读时，E03 为 `BLOCKED/40`、reason `INPUT_MISSING` 并停止 E；root/祖先或 descendant 为 reparse、规范化路径越界或发生路径碰撞时，E03 为 `BLOCKED/40`、reason `INPUT_IDENTITY_UNPROVEN` 并停止 E；文件 SHA 或 canonical inventory 双重重建不一致时，E03 为 `FAIL/10`、reason `SNAPSHOT_REBUILD_MISMATCH`；仅在身份或 containment 无法证明但尚未触发明确不安全条件时，E03 为 `UNPROVEN/30`、reason `INPUT_IDENTITY_UNPROVEN`。不得再使用另一套逐文件 annotation allowlist 或模糊质量基线根遍历合同。

在上述唯一范围内，canonical 三文件任一缺失或不是 regular file 时，E03 固定为 `FAIL/10`、reason `INPUT_MISSING`；该规则只补充缺失文件的确定性映射，不改变 inventory 范围或 canonical annotator allowlist。

### Correction 03 finding map

| finding_id | root_cause_id | lineage | trigger/evidence | prior_unresolved_reason | revision_location | verification_method | user/product/trust impact | maintenance impact | current_status |
|---|---|---|---|---|---|---|---|---|---|
| DQA-F08 | RC-DQA-ROOT-RULE-PROVENANCE | REOPENED | packet 旧根规则声明与当前磁盘 `AGENTS.md` fresh SHA 不一致 | correction-02 复核只核对旧声明，未重新读取并计算根规则字节 | packet 设计绑定、授权前置、本 correction 绑定 | 独立重算 `AGENTS.md` SHA，并与三份当前绑定逐字段回读 | 防止旧规则被误当作当前授权依据，避免执行边界和信任判断漂移 | 每个新 correction 记录 fresh root hash，避免 stale provenance | CHANGES_REQUIRED |
| DQA-F05 | RC-DQA-E03-INPUT-BOUNDARY | REOPENED | literal 文件 allowlist 与质量基线根递归枚举并存，无法确定唯一输入闭包 | correction-02 仅通过静态 wording，未消除两套边界 | packet 输入表、E03 行、E03 合同、本 correction | 只接受一个 literal root；回读 root/descendant containment、reparse、匹配、顺序、完整 inventory、hash 和失败路由 | 防止漏掉额外标注或越界读取，保证 E03 独立性与可追溯性 | executor 只维护一套 inventory 实现和快照逻辑 | CHANGES_REQUIRED |

本 correction 不产生 `CONSENSUS_READY`，不授予 executor 实现、测试或 DQA 执行授权；修正后由上游创建全新的独立 Reviewer。

## Root-rule provenance resync

- `delta_class`: `SAME_SCOPE_HARDENING`
- `source_event`: `MPV-02B-DQA-LE-20260830-017`
- `active_root_rules_path`: `D:\Code\yeyu-ai\AGENTS.md`
- `active_root_rules_sha256`: `96EA33DF0061A041DD436B49317FA94023AE65A37C5EFBCFAD7354F6728505BF`
- `supersedes_for_authorization`: correction-03 的旧 `root_rules_sha256` 仅保留为 Reviewer 审查快照；执行前必须使用本 active SHA
- `contract_effect`: 不改变 DQA 检查、E03、E06、两道质量门、输入/输出范围或禁止活动；合同 digest 不变
- `review_route`: 仅做当前根规则 SHA、packet 和 ledger active binding 的定向 readback；保留 correction-03 的独立 Reviewer 接受回执
- `current_state`: `CONSENSUS_READY / DQA_NOT_AUTHORIZED`

本 resync 不产生 DQA 执行授权。授权负责人仍须绑定本 packet、literal 输入、executor、interpreter、verifier 和新的 D 盘 run；当前 lifecycle 只读取 ledger 最后一条有效事件。

## Post-commit root-rule provenance resync

- `delta_class`: `SAME_SCOPE_HARDENING`
- `source_event`: `MPV-02B-DQA-LE-20260830-019`
- `active_root_rules_path`: `D:\Code\yeyu-ai\AGENTS.md`
- `active_root_rules_sha256`: `435498C2929CF0AA79B33EB03BEDF0DA283CDB402AC08D1CAE678EF4155011B6`
- `supersedes_for_authorization`: prior active SHA `96EA33DF0061A041DD436B49317FA94023AE65A37C5EFBCFAD7354F6728505BF` remains historical; authorization must use this active SHA
- `contract_effect`: only refreshes post-commit root-rule identity; no change to DQA checks, E03, E06, quality gates, input/output scope or prohibited activities
- `verification`: recompute the root file SHA and read back the active binding in the design, packet and ledger
- `current_state`: `CONSENSUS_READY / DQA_NOT_AUTHORIZED`

This resync does not authorize DQA, run creation, tests, indexing, performance, model, service or network activity.
