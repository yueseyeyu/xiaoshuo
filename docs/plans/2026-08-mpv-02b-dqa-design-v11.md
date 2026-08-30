# MPV-02B 数据质量审计设计 v11（执行器合同修正 05）

合同正文状态：`IMMUTABLE_CONTRACT / PLAN_A_EXECUTOR_CONTRACT_CORRECTION_05`

当前生命周期状态不由本文件读取：唯一权威来源是 [DQA finding ledger](2026-08-mpv-02b-dqa-finding-ledger-v11.md) 末尾最后一条通过 predecessor 链校验的追加事件。本文件中的 `状态`、`current_state`、Reviewer 回执和 owner disposition 均为历史记录或合同说明，不得覆盖 ledger 当前状态。

合同 digest 只针对不可变合同 projection（目标、范围、输入、动作、验收、停止和授权边界），排除自身 digest 与顶层生命周期字段；packet 的 `contract_digest` 必须由 verifier 独立回读，不能用文档完整 SHA 或生命周期状态替代。

轮次：`post-round-20-correction-05`

planner_a 范围审视：`PLAN_SCOPE_REVIEW: SUFFICIENT`。本轮按有界研究结论收敛合同，不新增 DQA 检查项、框架、数据库、模型、服务或扫描范围。

本文件是第 10 轮 `PLAN-B-REVIEW: CHANGES_REQUIRED` 后的唯一 DQA 设计版本；第 12～20 轮及本轮修订均保留在同一文件中。逐检查合同的机器可读唯一来源为 [`dqa-check-contract-matrix-v1.json`](2026-08-mpv-02b-dqa-check-contract-matrix-v1.json)，本文件的检查表只作可读投影。它只定义只读审计，不授权创建 DQA run、修改源码、修改数据、修改索引或进入性能基线。

## 最终需求描述

### 目标

确认当前检索器使用的整套数据链路可信：

`原始正文 → 章节解析 → 场景切分 → 索引 → 查询 → 候选池 → 三方标注 → 裁决 → 指标`

审计必须分别判断 `SOURCE_DATA_GATE` 和 `EVALUATION_DATA_GATE`，避免使用损坏的源数据或不可追溯的评测标签优化检索器。

### 用户价值

让作者看到的候选场景可用、可回溯、与标注对象一致，减少空场景、截断、错序、重复、错映射、假阴性和错误质量归因。

### 最小范围

- 三本书对应的原始数据、章节解析和场景切分只读检查；
- `chapter_parser.py`、`scene_search.py` 及直接索引读取入口的直接调用链；
- 当前样本索引、metadata、manifest、BM25/BGE/RRF 候选和 doc_id 映射；
- 24 条查询、472 条候选、三方原始标注、标注协议、26 条裁决、最终共识、指标脚本和指标结果；
- `raw_body`、`text_preview`、编码、空值、重复、顺序、ID、章节映射、排序合同和统计一致性。

### 非目标

不重建索引，不加载或切换模型，不改分块和检索算法，不修改源码、配置、原始标注、裁决、共识、现有质量基线或最终索引，不运行服务/API/网络/生产 pipeline，不进入性能测试。

### 输入与输出合同

输入只读使用执行 packet literal allowlist 绑定的源码/配置文件、三本书原始数据、样本索引、质量基线输入，以及（若存在）查询来源证据文件和标注协议/输入 manifest。具体文件路径、run-id、用途、快照版本和 hash 必须由 packet 逐文件列出；输入根不是授权本身。C 盘历史证据不得混入生产数据判断；无法证明输入身份时标 `UNKNOWN`/`UNPROVEN`。

新的审计证据只能写入此前不存在的 `D:\tmp\yeyu-ai-a3\mpv-02b-dqa\<run-id>`。输出必须同时包含中文 Markdown 报告和 JSON 报告；每项检查单独拥有 `check_id`、状态、退出码、输入快照、证据引用、统计、限制和下一步。

E01 的 query provenance 输入合同固定为 UTF-8 canonical JSON 对象：根字段为 `schema_version="query-provenance-v1"`、`source_snapshot_hash`、`queries`；每个 query 记录固定为 `query_id、source_ref、source_location、source_text_hash、normalized_query_hash、intent_explanation、query_category`。`source_ref` 必须是获准输入 manifest 中的相对 POSIX 路径或已记录的原始输入标识；`source_location` 必须是可复读的行号/记录号或字符区间，不能只写自由文本；`source_text_hash` 对原始来源 UTF-8 bytes 计算，`normalized_query_hash` 对 NFC、LF、无隐式 trim 的规范化 query UTF-8 bytes 计算。根对象和逐条记录均使用 `ensure_ascii=false`、固定字段顺序、紧凑分隔符、LF 终止，hash 不包含自身 hash 字段。缺少来源文件、快照 hash、位置或逐条绑定时 E01 固定 `UNPROVEN`。

执行 preflight、输入/输出路径 containment、运行环境、缓存位置、literal allowlist、postflight 和失败封存的具体字段与路径只在另行授权的执行 packet 中冻结。本主设计仅要求 packet 存在、版本绑定本方案、使用 D 盘新鲜 run、只读输入、失败即封存，并遵守 `PASS/FAIL/UNKNOWN/UNPROVEN/BLOCKED` 状态和退出码合同；成功或失败封存均必须提供机器可读 JSON 和人类可读 Markdown 报告。packet 缺失或与本方案版本不一致时不得开始 DQA。主设计不定义 run-id 正则、具体输出文件名、解释器变量、hash 自引用规则或失败 artifact 子集，避免与 packet 形成双重权威。

状态与退出码固定为：`PASS=0`、`FAIL=10`、`UNKNOWN=20`、`UNPROVEN=30`、`BLOCKED=40`。任何一项不能用总体成功率或其他检查的退出码代替。

## 版本化输入与输出字段合同

E03 的 inventory 不是自由文本。本修正只采用一种输入方案：execution packet 必须绑定一个固定的、绝对 literal 的 `e03_inventory_root` 目录；该目录是唯一允许递归枚举的根，不得扩展到 stage root、项目目录或模糊 glob。其 JSON 根字段固定为 `schema_version="annotation-inventory-v1"`、`scope_root`、`recursive`、`filename_pattern`、`file_type_allowlist`、`reparse_policy`、`path_normalization`、`sort_order`、`entries`、`excluded_entries`、`canonicalization`、`inventory_hash`。`entries` 和 `excluded_entries` 按相对 POSIX 路径排序；每项固定为 `relative_path`、`kind`、`size_bytes`、`file_sha256`、`normalized_rows_hash`（非 CSV 为 `null`）、`disposition`、`reason_code`。executor 只在该 root 内枚举非 reparse 后代，按 `annotation*.csv`、`*manifest*.json`、`*protocol*.md` 三个模式的 OR 集合识别匹配文件；每个枚举到的文件或目录都必须进入 inventory evidence，匹配文件必须计算完整文件 SHA-256，CSV 另计算 `normalized_rows_hash`。allowlist 外文件必须显式为 `backup` 或 `excluded` 并给出 reason code，不得静默忽略。

E03 的机器合同补充冻结如下：`filename_pattern` 是三个模式的 OR 集合；`scope_root` 必须等于 packet 声明的 `e03_inventory_root` literal 的规范化绝对路径；遍历先收集 root 下所有后代，再按相对 POSIX 路径的 UTF-8 bytes 升序处理，禁止跟随 reparse point。路径规范化为 Unicode NFC、POSIX `/`、拒绝 `.`/`..` 和越界；规范化后发生大小写不敏感碰撞立即停止。`kind` 仅允许 `regular_file`、`directory`、`reparse`；`disposition` 仅允许 `canonical`、`backup`、`excluded`；`canonical` 条目的 `reason_code` 必须为 `null`，其余条目必须使用统一 reason-code 枚举中的非空值。canonical annotator 仍严格只允许相对路径 `annotation-blind-codex.csv`、`annotation-blind-glm.csv`、`annotation-blind-deepseek.csv`，映射优先级为 `codex < glm < deepseek`；TRAE 或其他重复/身份不明文件必须进入 inventory 并标记 `backup`/`excluded`。目录和 reparse 条目进入 `excluded_entries`，不作为 canonical 文件输入。canonical bytes 使用 UTF-8、NFC、LF、`ensure_ascii=false`、紧凑分隔符；`inventory_hash` 和外部 hash 字段均不进入自身 hash 输入。目录不存在/不可读、路径越界或 reparse descendant 使 E03 `BLOCKED/40` 并停止 E；文件 hash 或 canonical 重建不一致使 E03 `FAIL/10`、reason `SNAPSHOT_REBUILD_MISMATCH`；无法证明身份或 containment 使 E03 `UNPROVEN/30`、reason `INPUT_IDENTITY_UNPROVEN`。不得以静态逐文件 allowlist 替代该 inventory root，也不得保留另一套递归范围。

E04/E07 的 `evaluation-metrics-schema-v1` 是本方案冻结的输入合同；未来执行必须由 packet 绑定一个输出 schema artifact，并回读其 canonical bytes/hash。具体 artifact 路径和文件名只在 packet 中定义。根字段完整允许集合固定为：`schema_version`、`check_id`、`check_status`、`exit_code`、`reason_codes`、`counts`、`per_pair`、`per_query`、`per_category`、`overall`、`formula_version`、`label_semantics_ref`、`label_order`、`input_snapshot_refs`、`canonicalization`。`check_status` 仅允许 `PASS`、`FAIL`、`UNKNOWN`、`UNPROVEN`、`BLOCKED`；`label_order` 必须为 `[0,1,2]`；所有数值为有限 JSON number 或 `null`；未知状态必须有非空 reason code。E04 的 `per_pair` 固定字段为 `annotator_a`、`annotator_b`、`N`、`exact_agreement`、`p_o`、`p_e`、`kappa`、`valid`、`reason_codes`；E07 的 `per_query` 固定字段为 `query_id`、`query_category`、`channel`、`recall_at_5`、`mrr_at_10`、`ndcg_at_10`、`denominator`、`valid`、`reason_codes`；`per_category` 固定为类别键、`query_count`、三个指标 macro、`valid_query_count`、`unproven_query_count`；`overall` 固定为三个指标 macro、`query_count`、`valid_query_count`、`unproven_query_count`。E04/E07 的错误映射固定为 `INVALID_LABEL`、`MISSING_LABEL`、`MISSING_SCHEMA_INPUT`、`UNPROVEN_DENOMINATOR`、`FORMULA_MISMATCH`，不能自由增删或改义。

E04/E07 的完整机器定义补充为：禁止额外根字段；`counts` 必须包含 `total_keys`、`valid_keys`、`invalid_keys`、`missing_keys`；`per_category` 必须包含 `query_count`、`recall_at_5_macro`、`mrr_at_10_macro`、`ndcg_at_10_macro`、`valid_query_count`、`unproven_query_count`；`overall` 必须包含同三项 macro 及三项 query 计数。计数必须是非负整数；指标在 `valid=true` 时为有限 JSON number，否则只能为 `null`；`channel` 仅允许 `BM25`、`BGE`、`RRF`。错误映射唯一集合包含 `INVALID_LABEL`、`MISSING_LABEL`、`MISSING_SCHEMA_INPUT`、`UNPROVEN_DENOMINATOR`、`FORMULA_MISMATCH`，其中 `FORMULA_MISMATCH` 同时覆盖公式版本或结果漂移。schema canonical hash 仅计算不含外部 hash 字段的 UTF-8 canonical JSON bytes；上述 required/nullable/enum/字段顺序均必须写入 artifact 并回读。

执行 packet 必须另行冻结输入 manifest、输出 allowlist、preflight/postflight 字段、路径 containment/reparse 检查、运行环境、缓存边界和封存规则；本主设计只引用这些合同，不重复规定其字段或文件清单。无 packet 或 packet 版本未绑定本方案时，DQA 为 `BLOCKED/40`。

F08 的主设计要求是执行 packet 提供可复核的输入/输出边界、只读工作区约束和失败封存语义；resolved path、reparse、canonical hash、allowlist、Git 读回和具体失败 artifact 均属于 packet 的执行细节。packet 必须声明这些细节的版本和验证引用，执行者不得在运行时自行补充或改变。

在上述唯一范围内，canonical 三文件任一缺失或不是 regular file 时，E03 固定为 `FAIL/10`、reason `INPUT_MISSING`；该规则只补充缺失文件的确定性映射，不改变 inventory 范围或 canonical annotator allowlist。

## 统一检查合同（PLAN_CONTRACT_PREFLIGHT）

机器可读唯一合同源：`dqa-check-contract-matrix-v1.json`，schema 为 `governed-contract-source/v2`，revision 为 `PLAN_A_EXECUTOR_CONTRACT_CORRECTION_05`，当前 matrix SHA-256 为 `204aec682b3a9ddd40a701a9c752e77dd3c67ba954278911c2a389fc02e014fd`，contract digest 为 `c9a8bd12a70784932573256f283a6c3799b46abc0fa75c9e9b7810d47a5d2b02`，并绑定 registry `rules-r2`。该文件冻结 17 个 `check_id`、输入引用、前置、procedure、输出字段、reason code、停止动作、验证方式和 owner disposition；本文件和 execution packet 不得新增、删除或改写这些字段。verifier 必须读取该 v2 JSON 的 UTF-8 canonical bytes、registry binding、matrix SHA 和 contract digest，并逐字段比较本文件/packet 的可读投影；缺失、无法读取、digest 不一致、registry 不一致或检查项不完整时，合同预审为 `PLAN_CONTRACT_INCOMPLETE`，不得派发 executor 或创建 run。

本节是 DQA-01～DQA-09、E01～E08 的人类可读投影。执行者只能按机器合同源读取输入、产生证据和决定停止动作；下方各检查章节只补充领域判定，不得重新定义字段、状态或退出码。每个 `checks/<id>.json` 的根对象固定包含：`schema_version="dqa-check-envelope-v1"`、`check_id`、`check_status`、`exit_code`、`input_snapshot_refs`、`preconditions`、`procedure_ref`、`evidence`、`counts`、`reason_codes`、`limitations`、`stop_action`、`next_step`。`evidence` 至少包含 `output_fields`、`artifact_refs`、`canonicalization` 和 `verifier_readback`。状态与退出码一一对应：`PASS/0`、`FAIL/10`、`UNKNOWN/20`、`UNPROVEN/30`、`BLOCKED/40`。

reason code 枚举固定为：`INPUT_MISSING`、`INPUT_IDENTITY_UNPROVEN`、`ENCODING_ERROR`、`RAW_BODY_MISSING`、`TRANSFORM_UNACCOUNTED`、`BOUNDARY_GAP`、`DUPLICATE_ID`、`MAPPING_MISMATCH`、`COUNT_MISMATCH`、`SORT_CONTRACT_MISMATCH`、`QUERY_SOURCE_MISSING`、`ANNOTATOR_INDEPENDENCE_UNPROVEN`、`SNAPSHOT_REBUILD_MISMATCH`、`FORMULA_MISMATCH`、`INVALID_LABEL`、`MISSING_LABEL`、`MISSING_SCHEMA_INPUT`、`SEMANTIC_REVIEW_INPUT_MISSING`、`UNPROVEN_DENOMINATOR`、`OUT_OF_SCOPE_CLAIM`、`PREFLIGHT_FAILED`、`WORKSPACE_MUTATION`。`FAIL` 只用于能明确检测到输入/不变量违反；`UNKNOWN` 用于信息不可判定；`UNPROVEN` 用于缺少证明材料；`BLOCKED` 只用于前置条件失败导致检查不能开始。每个检查失败或未知都必须写出 `stop_action`，不得由执行者自由决定继续。

主设计与执行 packet 的职责固定为：本文件冻结业务目标、检查覆盖、判定合同、证据语义和门禁关系；单独的执行 packet 冻结本次实际输入的 literal allowlist、只读 procedure、运行环境、D 盘 run 根、输出清单、pre/postflight 和封存动作。packet 不得新增业务检查或改变本文件的状态/退出码，主设计也不重复展开 packet 的命令和路径细节。`SEALED_SUCCESS`/`SEALED_FAILURE` 仅表示执行封存结果，不表示任一质量门通过；两道质量门必须另行记录并聚合。

| check_id | input_refs | preconditions | procedure_ref | output/evidence fields | status/exit mapping | reason_codes | blocking/stop_action | verification_method | owner_disposition |
|---|---|---|---|---|---|---|---|---|---|
| DQA-01 | literal source allowlist、三本书原始文件 | preflight PASS | DQA-PROC-01 | source_entries、encoding、readability、snapshot_refs、identity | PASS:0;FAIL:10;UNKNOWN:20;UNPROVEN:30;BLOCKED:40 | INPUT_MISSING、INPUT_IDENTITY_UNPROVEN、ENCODING_ERROR | 正文缺失 FAIL；身份不可证 UNKNOWN/UNPROVEN；停止 SOURCE | 独立重读与快照回读 | SOURCE_GATE_REVIEW |
| DQA-02 | DQA-01 sources、raw bytes、parser input | DQA-01 PASS | DQA-PROC-02 | raw_body_bytes、decode、replacement_count、empty_count、preview_only、body_hashes | PASS:0;FAIL:10;UNKNOWN:20;UNPROVEN:30;BLOCKED:40 | ENCODING_ERROR、RAW_BODY_MISSING、TRANSFORM_UNACCOUNTED | 解码/正文缺失 FAIL；raw_body 不可读 UNPROVEN；停止依赖项 | raw_body 与 preview 对照、hash 重算 | SOURCE_GATE_REVIEW |
| DQA-03 | parser、chapter records、source coordinates | DQA-02 PASS | DQA-PROC-03 | chapter_count、order、byte/codepoint_ranges、coverage、gaps、overlaps、transform | PASS:0;FAIL:10;UNKNOWN:20;UNPROVEN:30;BLOCKED:40 | BOUNDARY_GAP、TRANSFORM_UNACCOUNTED、COUNT_MISMATCH | 区间不可重建 UNKNOWN；丢失/重复 FAIL；停止 SOURCE | 独立区间并集与顺序重算 | SOURCE_GATE_REVIEW |
| DQA-04 | scene/sub-scene records、chapter mapping | DQA-03 PASS | DQA-PROC-04 | scene_count、scene_order、sub_scene_order、ranges、coverage、gaps、overlaps、body_hashes | PASS:0;FAIL:10;UNKNOWN:20;UNPROVEN:30;BLOCKED:40 | BOUNDARY_GAP、DUPLICATE_ID、TRANSFORM_UNACCOUNTED | 边界不明 UNKNOWN；重复/截断 FAIL；停止 SOURCE | scene/sub-scene 边界和 hash 重算 | SOURCE_GATE_REVIEW |
| DQA-05 | metadata、doc_id、book/chapter/scene identifiers | DQA-03/04 PASS | DQA-PROC-05 | id_counts、collision_counts、metadata_fields、body_bindings、duplicate_keys | PASS:0;FAIL:10;UNKNOWN:20;UNPROVEN:30;BLOCKED:40 | DUPLICATE_ID、MAPPING_MISMATCH、INPUT_IDENTITY_UNPROVEN | 重复/错映射 FAIL；停止 SOURCE 及依赖 E | 唯一键、跨书碰撞和一一映射重算 | SOURCE_GATE_REVIEW |
| DQA-06 | sample index、metadata、vector rows、read entrance | DQA-05 PASS | DQA-PROC-06 | index_rows、vector_rows、doc_id_map、payload_hashes、readback_matches | PASS:0;FAIL:10;UNKNOWN:20;UNPROVEN:30;BLOCKED:40 | MAPPING_MISMATCH、RAW_BODY_MISSING、INPUT_IDENTITY_UNPROVEN | 载荷错映射 FAIL；不能回读 UNKNOWN；停止 SOURCE | index row/vector/metadata 三方 exact readback | SOURCE_GATE_REVIEW |
| DQA-07 | index snapshot、build manifest、DQA-01..06 evidence | DQA-06 PASS | DQA-PROC-07 | raw/chapter/scene/metadata/index_counts、expected_14717、anomaly_counts、recomputed_hash | PASS:0;FAIL:10;UNKNOWN:20;UNPROVEN:30;BLOCKED:40 | COUNT_MISMATCH、SNAPSHOT_REBUILD_MISMATCH、INPUT_MISSING | 重算不一致 FAIL；输入不全 UNPROVEN；停止 SOURCE | 独立重算 14,717 和异常统计 | SOURCE_GATE_REVIEW |
| DQA-08 | query results、BM25/BGE/RRF observations、DQA-06 | DQA-06/07 PASS | DQA-PROC-08 | query_id、channel、rank、doc_id、payload_ref、rank_map | PASS:0;FAIL:10;UNKNOWN:20;UNPROVEN:30;BLOCKED:40 | MAPPING_MISMATCH、SORT_CONTRACT_MISMATCH、INPUT_IDENTITY_UNPROVEN | 返回错映射 FAIL；不能证明 UNPROVEN；停止依赖 E | 逐 query/channel payload 与 rank 对照 | SOURCE_GATE_REVIEW |
| DQA-09 | previously sealed DQA/E outputs and historical baseline boundary, excluding this check | preflight PASS; prior outputs recorded; current check self-entry excluded | DQA-PROC-09 | claim_scope、sample_limits、preview_limits、forbidden_claims | PASS:0;FAIL:10;UNKNOWN:20;UNPROVEN:30;BLOCKED:40 | OUT_OF_SCOPE_CLAIM、INPUT_IDENTITY_UNPROVEN | 越界结论 FAIL；停止报告发布 | 逐条 claim 与输入边界对照，确认 self-entry exclusion | OWNER_SCOPE_DECISION |
| E01 | queries、query provenance source or absence record | preflight PASS | E-PROC-01 | query_count、category_counts、duplicate_counts、near_duplicate_counts、per_query_source_fields | PASS:0;FAIL:10;UNKNOWN:20;UNPROVEN:30;BLOCKED:40 | QUERY_SOURCE_MISSING、INPUT_IDENTITY_UNPROVEN、COUNT_MISMATCH | 无来源固定 UNPROVEN；停止 E gate | 逐 query source binding/hash/readback | EVALUATION_GATE_REVIEW |
| E02 | production ranking contract、query bytes、P/O pool | DQA-08 PASS and ranking identity complete | E-PROC-02 | top_k、candidate_pool、sort/tie/RRF_fields、per_query_rank_diff、pool_keys | PASS:0;FAIL:10;UNKNOWN:20;UNPROVEN:30;BLOCKED:40 | SORT_CONTRACT_MISMATCH、COUNT_MISMATCH、INPUT_IDENTITY_UNPROVEN | 生产等价不可证明 UNPROVEN；明确漂移 FAIL；停止 E | 逐 query exact rank diff 与 472 union 重算 | EVALUATION_GATE_REVIEW |
| E03 | packet 的固定 literal `e03_inventory_root` 及其非 reparse 后代 | DQA-05 PASS | E-PROC-03 | inventory_scope、inventory_entries、file_sha256、normalized_rows_hash、dispositions、identity | PASS:0;FAIL:10;UNKNOWN:20;UNPROVEN:30;BLOCKED:40 | ANNOTATOR_INDEPENDENCE_UNPROVEN、INPUT_MISSING、INPUT_IDENTITY_UNPROVEN、SNAPSHOT_REBUILD_MISMATCH | root 缺失/不可读/reparse/越界 BLOCKED；身份不可证明 UNPROVEN；格式/键/hash 错误 FAIL；停止 E | 两次同规则 inventory 枚举、完整条目和 canonical hash 对照 | EVALUATION_GATE_REVIEW |
| E04 | three canonical annotations、protocol | E03 PASS | E-PROC-04 | per_pair、label_distribution、category_distribution、agreement_fields、schema_ref | PASS:0;FAIL:10;UNKNOWN:20;UNPROVEN:30;BLOCKED:40 | INVALID_LABEL、MISSING_LABEL、FORMULA_MISMATCH、MISSING_SCHEMA_INPUT | 标签/重算错误 FAIL；分母/语义不可判定 UNPROVEN；停止 E | schema readback 与负例映射核验 | EVALUATION_GATE_REVIEW |
| E05 | adjudication、three raw labels、query/body evidence | E03 and DQA-02..06 PASS | E-PROC-05 | dispute_keys、raw_labels、final_labels、reasons、evidence_refs | PASS:0;FAIL:10;UNKNOWN:20;UNPROVEN:30;BLOCKED:40 | MAPPING_MISMATCH、RAW_BODY_MISSING、INPUT_IDENTITY_UNPROVEN | 无法追溯 UNKNOWN/UNPROVEN；停止 E | 26 条逐项原始标签/理由/正文回读 | EVALUATION_GATE_REVIEW |
| E06 | P/O snapshots、raw_body、fixed sampling config | E03 and DQA-02..06 PASS | E-PROC-06 | snapshot_hashes、seed、strata、N/K、actual_keys、body_evidence、support_result | PASS:0;FAIL:10;UNKNOWN:20;UNPROVEN:30;BLOCKED:40 | SNAPSHOT_REBUILD_MISMATCH、RAW_BODY_MISSING、BOUNDARY_GAP | 快照/正文/抽样框不可重建 UNPROVEN；双重重建不等 FAIL；停止 E | 两次独立重建与完整正文抽核对照 | EVALUATION_GATE_REVIEW |
| E07 | qrels/consensus、rank observations、metric schema | E02..E06 PASS | E-PROC-07 | per_query、per_category、overall、denominators、formula_version、schema_refs | PASS:0;FAIL:10;UNKNOWN:20;UNPROVEN:30;BLOCKED:40 | FORMULA_MISMATCH、MISSING_LABEL、UNPROVEN_DENOMINATOR、MISSING_SCHEMA_INPUT | 公式/命名/映射漂移 FAIL；分母不可证 UNPROVEN；停止 E | 独立公式重算、schema/hash/readback | EVALUATION_GATE_REVIEW |
| E08 | previously sealed E outputs and gate states, excluding this check | E01..07 recorded; current check self-entry excluded | E-PROC-08 | supported_claims、unsupported_claims、sample_boundary、gate_refs | PASS:0;FAIL:10;UNKNOWN:20;UNPROVEN:30;BLOCKED:40 | OUT_OF_SCOPE_CLAIM、INPUT_IDENTITY_UNPROVEN | 越界/绝对真值表述 FAIL；停止关闭 E gate | claim matrix 与 gate/证据 exact 对照，确认 self-entry exclusion | OWNER_SCOPE_DECISION |

## 两道质量门

### SOURCE_DATA_GATE

覆盖 DQA-01～DQA-08。所有源数据、解析、正文载荷、场景边界、ID/顺序、metadata、索引向量、manifest、候选 doc_id 和返回内容映射均为 `PASS`，且没有 `UNKNOWN`、`UNPROVEN` 或 `FAIL`，才可为 `PASS`。DQA-09 是跨门的报告范围/声明检查，不是源数据质量证据，不参与 `SOURCE_DATA_GATE` 聚合。

源门和下游评价门只按下方唯一的“五状态真值表”聚合；本段不另行定义 gate 状态，避免重复规则。`INVALIDATED`/`CONTAMINATED` 仅是下游处置字段，不是检查状态，也不占用退出码。

### EVALUATION_DATA_GATE

覆盖 E01～E08。查询来源、候选池和生产等价排序、三方标注合同与独立性、裁决追溯、完整正文抽核、指标公式和结论边界全部 `PASS`，且 `SOURCE_DATA_GATE=PASS`，才可为 `PASS`。

没有查询来源证据时 E01 固定为 `UNPROVEN`，评价门不得 `PASS`。完整 `raw_body` 不可读、抽样框不可重建、生产等价排序不可证明或额外标注文件身份不明时，评价门只能为 `UNKNOWN`/`UNPROVEN`。E 检查可记录自身结果，但不得覆盖源门传播的 `INVALIDATED`/`CONTAMINATED` 处置。

门禁聚合顺序固定为：`check_status → SOURCE_DATA_GATE → E-check downstream_disposition → EVALUATION_DATA_GATE`。源门全部 `PASS` 且 E01～E08 全部 `PASS` 时，评价门才可 `PASS`；任一 E 检查 `FAIL` 时评价门为 `FAIL`，否则存在 `UNKNOWN`/`UNPROVEN` 时评价门为相应未知状态。

门禁真值表固定为：先分别聚合检查状态，聚合优先级为 `FAIL > BLOCKED > UNPROVEN > UNKNOWN > PASS`，对应 gate 状态和退出码依次为 `FAIL/10`、`BLOCKED/40`、`UNPROVEN/30`、`UNKNOWN/20`、`PASS/0`，不得按数字大小直接比较。若某门所有检查均为 PASS 才为 PASS；混合状态取上述最高优先级。`SOURCE=PASS` 时，E 检查保留自身状态；`SOURCE=FAIL` 时，所有依赖源数据的 E 检查保留原始 `check_status` 但 `downstream_disposition=INVALIDATED`，E 门至少为 FAIL；`SOURCE=BLOCKED` 时依赖检查处置为 `BLOCKED`，E 门至少为 BLOCKED；`SOURCE=UNPROVEN` 或 `UNKNOWN` 时依赖检查处置为 `CONTAMINATED`，E 门至少分别为 UNPROVEN 或 UNKNOWN。任一 E 检查自身为 FAIL/BLOCKED 时，E 门仍按完整优先级聚合，不得被下游处置降级。非依赖源数据的 E01/E03 合同结果仍独立记录，但不得使评价门通过。由此固定：SOURCE 非 PASS 时，任何候选、标注、裁决或指标不得报告为质量有效 PASS；E 门只有 SOURCE=PASS 且自身聚合为 PASS 才能 PASS。

逐项依赖矩阵固定为：`E01→无 DQA 依赖（查询来源独立检查）`；`E02→DQA-05,DQA-06,DQA-07,DQA-08`；`E03→DQA-05`；`E04→E03`；`E05→DQA-02,DQA-03,DQA-04,DQA-05,DQA-06,E03`；`E06→DQA-02,DQA-03,DQA-04,DQA-05,DQA-06,E03`；`E07→E02,E03,E04,E05,E06`；`E08→E01,E02,E03,E04,E05,E06,E07`。这里 E01 是唯一不依赖 SOURCE 的检查；E03 明确依赖 DQA-05 的 metadata/doc_id 合同，不能再称为不依赖源数据。依赖图按传递闭包传播：若任一直接或间接依赖检查的源门状态为 `FAIL/BLOCKED/UNPROVEN/UNKNOWN`，下游处置分别为 `INVALIDATED/BLOCKED/CONTAMINATED/CONTAMINATED`，并按真值表聚合；非依赖检查仍输出自身状态，但不能抵消源门状态。传递闭包只影响 downstream_disposition 和下游 gate 下限，不篡改原始 check_status；E03 先按 DQA-05 的源依赖传播，再与其标注文件独立性结果合并取较高状态。

负责人接受延期只能生成“带限制的诊断性测量”，不能关闭质量门、不能进行质量驱动优化、不能宣称评测数据通过。

## E02 机器可读排序合同

生产 `top_k=10` 时，`candidate_pool = min(max(top_k * 5, 20), n)`；当索引场景数 `n >= 50` 时每个 BM25/BGE 通道宽度恰为 `50`，不是基线生成脚本当前声明的 `candidate_depth=20`。E02 输入必须绑定 24 条 query 的原始来源引用、规范化后 query bytes/hash、预处理版本、索引 identity、实现源码/配置版本和 NumPy 版本；缺任一身份或快照时不得声称生产等价。两路排名表达式固定为 `np.argsort(scores)[::-1][:candidate_pool]`，并记录相同索引输入顺序、score 数组映射和实际 NumPy 排序实现。tie 的生产规则不是抽象的“稳定排序”：必须记录 `np.argsort` 的精确 kind/default、score 数组索引顺序及其反转后的实际顺序；RRF tie 必须记录两路 top-50 输出的插入顺序和 `scores` 字典首次插入顺序。若无法绑定这些实现和输入，E02 为 `UNPROVEN`，不得以样本适配器单独证明等价。

RRF 固定为两路 rank 从 1 开始，`score(d)=sum(1/(60+rank_i(d)))`，`k=60`；融合使用 `sorted(scores.items(), key=lambda x: x[1], reverse=True)` 语义，等分值保留 scores 字典的首次插入顺序，最后截断为前 `10` 条。E02 报告必须以机器可读 JSON 保存 `top_k`、`candidate_pool`、通道表达式、RRF `k`、截断、tie fixture、实现版本和每条 query 的完整 rank 序列，并与样本适配器逐 query exact diff。缺少字段、预期序列或发现 20/50 宽度漂移时不得 `PASS`，不通过时不重建基线。

候选池数学关系固定为：对每个 query `q`，`R(q,c)` 是通道 `c ∈ {BM25,BGE,RRF}` 的 top-10 doc 集合；评测候选池为 `P(q)=R(q,BM25) ∪ R(q,BGE) ∪ R(q,RRF)`，唯一键为 `(query_id, doc_id)`，全批验收为 `sum_q |P(q)| = 472`。通道观察框另定义为 `O={(query_id, doc_id, retrieval_channel, rank)}`，允许同一 `(query_id,doc_id)` 在不同通道出现；它不改变 472 的 pooled doc 计数，只用于 E06 的通道分层和 rank 追溯。候选池来源必须是各通道生产等价 top-50 输入截断后的 top-10 输出；若三路 top-10 union 不是 472，或候选池混入对应 top-50 之外记录，E02 为 `FAIL`。

## DQA 检查表

| ID | 检查 | 独立验收重点 | 失败或未知语义 |
|---|---|---|---|
| DQA-01 | 原始输入清单与身份 | 三本书源文件、版本/路径、可读性、编码和快照绑定完整 | 身份或正文缺失 → `UNKNOWN`/`FAIL` |
| DQA-02 | raw_body 与编码 | 构建消费完整 `raw_body`，统计空值、替换字符、截断和异常编码；`text_preview` 只能作为展示字段 | 仅 preview 或正文不可读 → `FAIL`/`UNPROVEN` |
| DQA-03 | 章节解析连续性 | 章节顺序、章节正文长度/哈希、空章节、解析器配置和 `strip()` 边界可解释 | 覆盖/顺序无法证明 → `UNKNOWN` |
| DQA-04 | 场景边界与顺序 | scene/sub-scene 的顺序、边界、重叠、空场景、过短/过长和正文重建一致 | 边界不可重建 → `UNKNOWN`/`FAIL` |
| DQA-05 | ID 与 metadata | `doc_id`、book/chapter/scene/sub-scene 唯一且稳定；跨书无碰撞；metadata 与正文一一对应 | 重复、跳映射或缺字段 → `FAIL` |
| DQA-06 | 索引载荷映射 | metadata、正文载荷、BM25/BGE 向量和索引读取的 doc_id 一一对应；返回正文确为对应场景；每级同时输出正文 hash、边界、输入/输出计数、覆盖/重叠计数和映射字段 | 任一映射无法证明 → `FAIL`/`UNKNOWN` |
| DQA-07 | manifest 与统计重算 | 从当前样本索引和构建 manifest 独立重算精确 14,717 场景，并输出原始/章节/场景/metadata/index 各级计数、正文 hash、边界、覆盖数、重叠数和映射计数，同时统计空、短、长、重复正文、异常语言和 metadata 缺失 | 统计不一致或输入不完整 → `FAIL`/`UNPROVEN` |
| DQA-08 | 检索候选映射 | BM25/BGE/RRF 返回的 rank、通道、query_id、doc_id 和正文内容与样本索引一致 | 返回内容错映射 → `FAIL` |
| DQA-09 | 基线证据边界 | 明确 24 查询、472 候选和 `text_preview` 标注只能证明样本质量基线，不能证明全量正文或生产质量 | 越界表述 → `FAIL` |

| ID | 检查 | 独立验收重点 | 失败或未知语义 |
|---|---|---|---|
| E01 | 查询集有效性与来源 | 核对 24 条真实写作意图、类别 `12/6/3/3`、重复/近重复、无意义、答案泄漏和逐条意图解释；每条必须绑定原始需求或用户输入来源的 `source_ref、source_snapshot_hash、source_location、intent_explanation`，查询规范化 bytes/hash 和来源文件必须进入 input manifest | 来源文件、逐条绑定或意图证据缺失固定 `UNPROVEN` |
| E02 | 候选池与生产等价排序 | 证明三路前 10 并集恰为 472，未混入对应 top-50 之外记录；按机器可读排序合同固定 top_k、候选宽度、tie-break、方向、截断、RRF 输入、版本，并逐查询核对生产等价 rank 序列 | 生产排序不可证明或当前 20 深度与生产不等价 → `UNPROVEN`/`FAIL` |
| E03 | 三方标注合同与独立性 | 三份 canonical 标注各 472 行、唯一键集合相等、标签仅 0/1/2、不可变列无漂移、协议版本一致；枚举并解释全部额外标注文件，包括 TRAE 与 DeepSeek 重复文件；记录 annotator/file manifest、身份/会话、输入快照、协议版本、时间、文件 hash、重复判定和 canonical 三份选择规则 | 身份或独立性不可证明 → `UNPROVEN` |
| E04 | 标注可靠性 | 重算逐项一致、两方多数、三方完全分歧、标签分布、按查询类别分布；标签语义必须绑定协议版本并显式记录 `0/1/2` 的文字定义；报告 nominal、unweighted、pairwise exact agreement 和 Cohen kappa，固定 label order `[0,1,2]`、缺失/非法标签处理、零分母规则和完整 JSON schema，不把多数票或一致率称为真值 | 重算不一致或非法标签 → `FAIL`；语义、公式或零分母不可判定 → `UNPROVEN` |
| E05 | 裁决可追溯 | 26 条完全分歧逐条对应；保留三方原始标签、最终标签和理由；理由必须由 query、完整正文或明确字段支持 | 证据只来自 preview → `UNKNOWN`/`UNPROVEN` |
| E06 | 完整正文语义抽核 | 以 O 行为抽样单位，全量复核 26 条裁决项、全部最终标签 2；标签 0/1 按查询类别、书籍、检索通道分层固定抽核，专门识别假阴性；固定 P/O 快照、seed、canonicalization、N/K、实际键清单、完整 raw_body 和 `SUPPORTED / UNSUPPORTED / INSUFFICIENT_EVIDENCE` 结论。机械 executor 只生成正文证据包；语义结论必须来自单独、获准且可追溯的语义复核输入 | raw_body、P/O 快照、抽样框或获准语义复核输入不可读/不可复建 → `UNPROVEN`，reason `SEMANTIC_REVIEW_INPUT_MISSING` |
| E07 | 指标计算合同 | 核对 pooling、Recall@5、MRR@10、nDCG@10、分类聚合、逐查询结果和 JSON；使用下方逐查询、分母、聚合和缺失处理公式 | 公式或命名漂移 → `FAIL`/`UNPROVEN` |
| E08 | 结论边界 | 明确结果只适用于 24 条查询、472 候选和本次正文抽核；不得外推为全库、全量正文、生产质量或绝对人工真值 | 越界结论 → `FAIL` |

## E06 固定抽样方案

抽样框由两层组成：主候选框 `P` 是 472 个唯一 `(query_id, doc_id)`；P 快照字段严格为 `query_id, query_category, book, doc_id, final_label`，不包含通道或 rank。通道观察框 `O` 是唯一 `(query_id, doc_id, retrieval_channel, rank)` 行；O 快照字段严格为 `query_id, query_category, book, doc_id, retrieval_channel, rank, final_label`。同一 query/doc 在不同通道出现时在 `O` 中保留为不同观察行，但标签复核对象按 `P` 去重；相同通道内重复四元组是输入错误。先分别保存 P/O 按各自 canonical key 排序的完整输入快照及其 hash，抽样前不得改变记录、标签或通道信息。

P 快照字段顺序固定为 `query_id, query_category, book, doc_id, final_label`；O 快照字段顺序固定为 `query_id, query_category, book, doc_id, retrieval_channel, rank, final_label`。P/O 各自都是按各自唯一键排序后的 UTF-8 canonical JSON 数组，分别计算完整 JSON bytes 的 SHA-256；不得把 O 字段拼进 P，也不得只 hash key。P 的唯一键为 `(query_id, doc_id)`，O 的唯一键为 `(query_id, doc_id, retrieval_channel, rank)`；`N_layer` 明确定义为该分层中过滤后的唯一 O 行数，而不是 P 去重后的数量。

0. 抽样过程执行两次彼此独立的无副作用重建，使用同一已封存 P/O 快照、seed 和规则；两次必须产生完全相同的 P/O 快照 hash、每层 N/K、mandatory 集合、实际 O/P key 清单和复核对象集合。任一字段不一致即 E06 `FAIL`，不得用第二次结果覆盖第一次。
1. 26 条完全分歧项全部纳入，保留三方标签和裁决理由。
2. 最终标签为 2 的候选全部纳入，和第 1 项按唯一键去重。
3. 最终标签为 0/1 的非 mandatory P 键形成 O 抽样框：按 `query_category × book × retrieval_channel` 分层；某层的 O 行只纳入该层且其 P 键不在 mandatory 集合的记录。每个非空层抽取 `K_layer=min(N_layer,30)` 条 O 行；N_layer 不足 30 时全量复核。一个 P 键可因多个通道命中多个层，但正文只复核一次，报告保留全部命中的 O 键及层。30 的依据是零发现时以约 95% 置信度给出约 10% 级别的有界上限，不代表排除系统性假阴性。
4. 固定种子为 `mpv-02b-dqa-e06-v1`。canonical key 字段顺序固定为 `query_id, doc_id, retrieval_channel, rank`；字符串统一 UTF-8、Unicode NFC、保留大小写、空值统一为 JSON `null`，使用 `ensure_ascii=false`、固定字段顺序、紧凑分隔符的 JSON 序列化。哈希输入为 `seed + "|" + canonical_key`，按 SHA-256 十六进制值、canonical key 的 UTF-8 bytes 做稳定排序取前 K；哈希相同时以完整 canonical key bytes 决胜。抽样配置、P/O 完整快照 hash、各层 N/K、实际 O/P key 清单都必须进入报告。重复 key、非法 Unicode、完整快照 hash 缺失或快照 key 清单与抽样 key 清单不一致时失败关闭。
5. 报告必须列出 P/O 两个快照 hash、每层 N/K、实际抽样 O key 清单、其对应 P key、来源通道、完整正文证据引用和复核结论 `SUPPORTED / UNSUPPORTED / INSUFFICIENT_EVIDENCE`。一个 P 被多个 O 行抽中时只复核一次，但必须保留全部命中的 O key。

抽核只能证明指定样本中的正文支持程度和部分假阴性风险，不能证明全部标签准确、没有系统性偏差或查询代表所有用户意图。

E06 的语义复核输入合同独立于机械抽样：executor 只能生成带 query、P/O key、完整 raw_body 证据引用和原始标签的待复核对象，不得自行生成 `SUPPORTED` 或 `UNSUPPORTED`。只有授权负责人提供的、逐对象可追溯的语义复核输入才能产生这两个结论；缺少该输入时 E06 必须为 `UNPROVEN/30`，reason `SEMANTIC_REVIEW_INPUT_MISSING`，EVALUATION_DATA_GATE 不得 `PASS`。该输入不得修改任何原始标注、裁决或共识。

## DQA-03～DQA-07 连续性合同

正文 hash 必须使用 SHA-256，分别计算原始文件 bytes、严格 UTF-8 解码后的章节 `raw_body` UTF-8 bytes、每个 scene/sub-scene 的 `raw_body` UTF-8 bytes、metadata 正文载荷的 canonical UTF-8 JSON bytes；禁止先 `strip()`、Unicode normalization 或截断后再冒充原文 hash。metadata canonical bytes 固定为 `json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")`。边界坐标统一为对应章节 `raw_body` 的 Python Unicode code-point 半开区间 `[start, end)`；raw file 到 chapter 还必须同时给出原始文件 UTF-8 byte 半开区间 `[byte_start, byte_end)`、解码规则和 chapter 坐标锚点，每个 scene 必须同时给出 `chapter_id/start/end/body_hash`。

每本书的 raw file→chapter 区间必须按章节顺序覆盖其解析输入，分别报告 byte/code-point 的覆盖、重叠和缺口；严格 UTF-8 解码失败、替换字符、BOM/换行处理未记录或区间不可重建时不得 PASS。章节解析若执行 `strip()`，必须同时保存未变换的源章节区间、解析后的 `raw_body` 区间/bytes、去除的前后空白长度和变换规则；非空白内容被丢失或重复时 FAIL，不能以解析后的 payload 冒充原始连续覆盖。对 chapter→scene 和 scene→sub-scene 每一级分别固定：输入正文使用严格 UTF-8 解码后的原始 bytes，允许的变换仅为协议明确声明的边界空白移除；禁止未记录的 Unicode normalization、换行替换、字符过滤、截断或拼接；每个派生对象必须保留其未变换输入区间、变换类型及参数、输出区间和 raw_body bytes/hash。每章场景区间按 `scene_index/sub_scene_index` 顺序，覆盖计数为区间并集长度，重叠计数为任意两个区间交集非空的数量，缺口计数为章节区间减去场景区间并集后的 code-point 数。`doc_id → metadata → body_hash/boundary → vector row` 必须是一一映射。DQA-07 的 14,717 是三本书当前样本索引快照的精确预期场景数，不是全库或约数；任一级计数、hash、边界、覆盖、重叠或映射缺失时不得 `PASS`。

## E03 标注 manifest 合同

canonical annotator manifest 必须是按固定 `annotator_id` 排序的 JSON 数组，allowlist 严格为 `annotation-blind-codex.csv`、`annotation-blind-glm.csv`、`annotation-blind-deepseek.csv`，映射优先级固定为 `codex < glm < deepseek`；每项固定包含 `annotator_id、file、normalized_relative_path、file_sha256、normalized_rows_hash、protocol_version、input_snapshot_ref、session_ref、created_at、role`，路径使用相对 POSIX 路径、Unicode NFC，时间使用 UTC RFC3339 `Z`。执行时必须在 packet 绑定的唯一 `e03_inventory_root` 下以固定规则枚举全部后代中的 `annotation*.csv` 和 manifest/协议文件，生成完整 inventory 快照；allowlist 之外的文件只能标为 `backup` 或 `excluded` 并写明理由，不能静默忽略。`normalized_rows_hash` 固定为：以 UTF-8 严格读取 CSV，使用 RFC4180 解析；列名按文件头原始顺序记录并要求与协议列集合一致；每个单元格 Unicode NFC、保留大小写、去除的仅为 CSV 解析器语法，不做隐式 trim；换行统一为 LF；每行编码为按文件头顺序、字段名和值组成的紧凑 `ensure_ascii=false` JSON 对象；按 `(query_id, doc_id, retrieval_channel, rank)` 的 UTF-8 canonical key 排序后，以 LF 连接行 bytes，再计算 SHA-256。重复判定同时比较完整文件 SHA-256 和规范化行集合 hash；相同 hash、相同 session、缺少身份/输入绑定或同一内容多身份时不得证明独立性，E03 固定 `UNPROVEN`。不可变列集合固定为 `query_id、doc_id、query_category、book、retrieval_channel、rank、text_preview`；标签列只能是 0/1/2，标签之外的不可变列必须逐字相等。

## E07 指标公式合同

对每个 query `q` 和通道 `c` 单独计算：相关定义为 `final_label > 0`，但 `final_label` 的 0/1/2 文字语义必须来自绑定的标注协议，不能由指标脚本推断；`P(q)` 是三路 top-10 的跨通道 doc union；`Recall@5(q,c) = |top5(q,c) ∩ relevant(P(q))| / |relevant(P(q))|`，分母为 0 时输出 `UNPROVEN` 而非 0；`MRR@10(q,c)` 为 top10 内第一条相关结果的倒数，不存在时为 0；`nDCG@10(q,c)` 的 candidate ranking 为 top10，ideal ranking 为按 `(-gain, doc_id)` 排序后取前 10，gain 为 `2^final_label - 1`；`IDCG=0` 时输出 `UNPROVEN`。未标注项不得当作 0，遇到未标注或 key 缺失时该 query/channel 结果为 `UNPROVEN`。
E04 的 agreement 固定为所有三对 annotator 的 nominal、unweighted Cohen kappa：在 472 个共同有效 key 上，`p_o = exact_agreement_count / N`，`p_e = sum_l((count_i_l/N) * (count_j_l/N))`，`kappa=(p_o-p_e)/(1-p_e)`；`N=0` 或分母为 0 时该 pair 为 `UNPROVEN`，不得填 0。所有 label order 固定为 `[0,1,2]`，非法/缺失标签不静默删除，必须使相关 E04 结果 `FAIL` 或 `UNPROVEN` 并记录数量。

E04/E07 输出的确定性合同固定为：对象字段使用方案声明的顺序，所有必填字段、JSON 类型、允许值和错误状态映射写入同一个 `evaluation-metrics-schema-v1` 定义；canonical bytes 使用 UTF-8、`ensure_ascii=false`、`sort_keys=false`、紧凑分隔符、LF 终止，不允许 NaN/Infinity；hash 计算该 JSON 内容 bytes，不包含外部 hash 字段本身。缺失或非法值统一映射为 `check_status=FAIL`（输入合同不满足但可明确检测）或 `UNPROVEN`（无法判定），由 verifier 按固定原因码 `INVALID_LABEL`、`MISSING_LABEL`、`MISSING_SCHEMA_INPUT`、`UNPROVEN_DENOMINATOR` 记录，不得由执行者自由选择。schema 文件/内容 hash、错误映射表和输出 JSON bytes/hash 均必须进入 E04/E07 证据。

上述 schema 的最小必填类型固定为：根对象 `schema_version:string`、`check_id:string`、`check_status:enum`、`reason_codes:array[string]`、`counts:object`、`per_query:array[object]`、`per_category:object`、`overall:object`、`formula_version:string`、`input_snapshot_refs:array[string]`、`canonicalization:string`；数值字段只能是有限 JSON number 或明确的 `null`，状态为 `UNPROVEN` 时必须有非空 reason code。E04 的 per-pair 对象固定包含 `annotator_a、annotator_b、N、exact_agreement、p_o、p_e、kappa`；E07 的 per-query/channel 对象固定包含 `query_id、query_category、channel、recall_at_5、mrr_at_10、ndcg_at_10、denominator、valid、reason_codes`。这一定义仍只约束报告可复算性，不把标签或指标变成绝对真值。

E04 JSON schema 另固定保存 `label_semantics_ref`、`label_order=[0,1,2]`、三对 annotator 的 `N/p_o/p_e/kappa`、非法/缺失数量、类别顺序和 `check_status`；E07 JSON 必须引用该 schema 版本及其 canonical UTF-8 bytes/hash。上述统计、共识和多数票均是评测协议产物，不是绝对真值。

令 `Q_c` 为 24 条 query 在通道 c 的全集；只要任一 query/channel 结果为 `UNPROVEN`，该通道的官方类别 macro 和 overall macro 均为 `UNPROVEN`，同时记录 `valid_query_count`、`unproven_query_count` 和 `unproven_reason`，不把无效项排除后冒充完整均值。若全部可计算，类别 macro 为 `sum(metric(q,c) for q in Q_category,c) / |Q_category|`，overall macro 为 `sum(metric(q,c) for q in Q_c) / 24`。不得使用 micro mean 或按候选行加权替代。JSON 必须同时保存逐 query/channel 值、每类别 query 数、有效分母、零分母数、未标注数、有效集合、overall macro 值、公式版本、字段顺序、UTF-8 序列化参数、SHA-256 和名称 `pooled_top10_per_channel_diagnostic`。这些是 pooled 诊断指标，不是全库 Recall 或生产质量结论。

E07 JSON schema 还必须引用 E04 的 `label_semantics_ref`、`label_order`、agreement schema 版本和其 canonical UTF-8 bytes/hash；指标结果与多数票、共识、一致率均是协议产物，不是绝对真值。上述结果名称必须保留 `pooled_top10_per_channel_diagnostic`，不得省略 pooled/diagnostic 限定。

## 研究、停止与复核

- 复核状态机固定为：`PLAN_A_CONSOLIDATED → PLAN_B_REVIEW_DISPATCHED → WAITING_ONCE_40M → PLAN_B_RECEIPT`；只发送一次完整指令，只执行一次 40 分钟有界等待，不轮询、不重发。无最终 token 转 `REVIEW_PENDING`/`REVIEW_UNAVAILABLE` 并停止；`CHANGES_REQUIRED` 转 `PLAN_A_REVISION_REQUIRED`，修订后只能创建新的 planner_b；`ACCEPTED` 且 ledger 无悬空 Finding 才能转 `CONSENSUS_READY`。形成共识后仍需授权才可进入 `AUTHORIZED → EXECUTING → POST_REVIEW → CLOSED`；post_reviewer 必须是与执行者和 planner_a/planner_b 可区分的新一次性角色，输入为授权、实际 diff、测试/证据、未运行范围和报告闭环，输出必须是 `POST-REVIEW: ACCEPTED` 或 `POST-REVIEW: CHANGES_REQUIRED`，并附未证明边界和建议状态。仅当输出 `POST-REVIEW: ACCEPTED`、授权/白名单/diff 一致、必需测试和证据闭环通过、没有 `FAIL/BLOCKED/UNPROVEN/UNKNOWN` 未经 owner 接受，才可 `CLOSED`；`CHANGES_REQUIRED` 转新修正批次，超时/无最终 token 转 `REVIEW_PENDING`/`REVIEW_UNAVAILABLE`，均不得关闭。第 20 轮仍有实质问题转 `DEVELOPER_INTERVENTION_REQUIRED`。
- 本轮只读调查最多 20 个计划修订轮；每轮必须记录角色、变化、Finding 沿袭、证据、owner disposition 和精确下一步。
- 同一 Finding 没有实际修订位置、可执行验证和当前状态证据时保持 `UNRESOLVED`；超时或缺少 Reviewer 最终 token 保持 `REVIEW_PENDING`/`REVIEW_UNAVAILABLE`。
- 本版本交给全新、一次性的 planner_b 只读审查；planner_b 返回最终回执后立即结束并销毁，无法删除时立即归档且永久不复用。
- planner_b 若返回 `CHANGES_REQUIRED`，先更新本文件和 ledger，再创建全新的 planner_b；不得把自审、部分输出或超时当作接受。Huygens（第 15 轮）和 Bohr（第 16 轮）回执均已关闭并销毁；下一轮复核必须使用新上下文。
- 发现独立架构问题、跨模块协议冲突、正文缺失或边界无法证明时停止本 DQA 设计范围，记录为 `DEVELOPER_INTERVENTION_REQUIRED` 或建立新修正范围。
- 连续两轮没有新增实质证据时收束为 `UNKNOWN`/`UNPROVEN`，不得无限扫描。

## 后置阶段边界

本 DQA 只输出 `SOURCE_DATA_GATE`、`EVALUATION_DATA_GATE` 及其证据边界；只有两道质量门均为 `PASS` 后，才可另行建立、复核和授权性能基线。性能基线的测试步骤、样本顺序、资源指标和诊断性测量不属于本 DQA 设计或执行 packet；本轮不执行任何性能活动。

## Round 18 planner_a 修订与 Finding 合并

- `revision`: `PLAN_A_REVISION_18`
- `root_cause_id`: `RC-DQA-CONTRACT-MATRIX-GAP`
- `previous_receipt`: planner_b 第 17 轮 `PLAN-B-REVIEW: CHANGES_REQUIRED`
- 本轮修订：增加唯一 `check_contract_matrix` 和统一 check envelope；冻结 E03 inventory schema、E04/E07 完整输出 schema、D 盘输出根 containment、input/pre/postflight 字段；将“设计缺陷”和“等待执行证据”分离为不同当前状态。
- Finding 合并：F05、F07、F08、F11 均指向“检查合同没有作为单一可执行矩阵冻结”。F05/F07/F08 沿袭为 `UNRESOLVED`，F11 是上一轮新发现但本轮作为同一根因的 `UNRESOLVED`；上一轮未发现的原因是缺少统一矩阵，审查只能从局部段落逐项补缺。
- 影响边界：本轮只改善设计可审查性和证据闭环，不证明任何源数据、标注、指标或生产排序已经通过。
- F01、F02、F03、F04、F06、F09 的当前状态从设计结论上记录为 `DESIGN_ACCEPTED_EXECUTION_EVIDENCE_PENDING`；其历史沿袭和未证明边界不改写。F10 记录为 `LEDGER_CLOSURE_PENDING`，待本轮 receipt 绑定方案和账本后处理。
- `PLAN_CONTRACT_PREFLIGHT`: `PENDING_NEW_PLANNER_B_REVIEW`
- `CONSENSUS_READY`: `PROHIBITED`

本轮仍不得创建 DQA run、读取完整生产数据执行审计、运行测试/模型/服务/网络、重建索引、进入性能基线或修改历史质量基线。只有全新 planner_b 返回最终接受回执且 ledger 无设计阻断后，才能形成 `CONSENSUS_READY` 和待授权执行指令；共识仍不等于 DQA 执行授权。

## Round 19 planner_a 修订与复审回执

- `revision`: `PLAN_A_REVISION_19`
- `previous_receipt`: Locke 第 18 轮 `PLAN-B-REVIEW: CHANGES_REQUIRED`, P0/P1/P2/P3=`0/5/0/0`
- `scope_review`: `PLAN-SCOPE-REVIEW: SUFFICIENT`; 本轮未扩大只读 DQA、未新增检查项或第三方依赖。
- `F02`: `REOPENED` 的门禁冲突已删除重复自然语言规则；SOURCE/EVALUATION 聚合唯一以五状态真值表为准，`UNKNOWN` 与 `UNPROVEN` 分别保持自身状态并按传递矩阵处置。
- `F05`: 补齐 inventory 的 OR 文件模式、遍历/reparse 规则、`kind`/`disposition`/`reason_code` 枚举、字段顺序和 self-hash 排除规则。
- `F07`: 补齐 E04/E07 根字段、计数/嵌套字段、required/nullable、channel/status 枚举、`FORMULA_MISMATCH` 映射和 schema hash 范围。
- `F08`: 补齐 descendants 与每次 I/O 的 containment/reparse 重检、manifest self-hash 排除、逐项 postflight 输出比对、只读 Git 状态边界和异常封存。
- `F11`: 将 17 行矩阵扩展为逐项 input、precondition、procedure、output、status/exit、reason、blocking/stop、verification 和 owner disposition。
- `current_status`: F02/F05/F07/F08/F11=`DESIGN_ACCEPTED_PENDING_PLANNER_B_CONFIRMATION`; F01/F03/F04/F06/F09=`DESIGN_ACCEPTED_EXECUTION_EVIDENCE_PENDING`; F10=`LEDGER_CLOSURE_PENDING`。
- `CONSENSUS_READY`: `PROHIBITED`，等待本轮 receipt 绑定并由新的 planner_b 最终确认。

本节是历史修订记录，不是当前生命周期状态来源。当前状态只读取 ledger 最后一条有效追加事件。本修正确认性能仅为后置阶段依赖，不把性能活动并入 DQA；当前仍不得据此执行 DQA。

## Executor preparation correction 02

- `correction_id`: `MPV-02B-DQA-EXECUTOR-PREPARATION-CORRECTION-02`
- `source_receipt`: 一次性独立 planner_b/Reviewer 回执，`PLAN-B-REVIEW: CHANGES_REQUIRED`
- `scope_decision`: 仅修复 correction-01 的 plan/packet/ledger 自描述版本绑定；不新增 DQA 检查，不改变业务依赖、执行合同或授权边界。
- `plan_revision`: `PLAN_A_EXECUTOR_CONTRACT_CORRECTION_02`
- `packet_revision`: `PLAN_A_EXECUTOR_CONTRACT_CORRECTION_02`
- `ledger_revision`: `MPV-02B-DQA-LEDGER-11-EXECUTOR-CORRECTION-02`
- `current_event`: `MPV-02B-DQA-LE-20260828-014`
- `predecessor_event`: `MPV-02B-DQA-LE-20260828-013`
- `current_state`: `CONSENSUS_READY / DQA_NOT_AUTHORIZED`

本 correction 补齐 ledger 自身的 `ledger_revision`，并要求主设计、packet、ledger 对 `plan_revision`、`packet_revision`、`ledger_revision`、`current_event` 和 `predecessor_event` 进行双向精确回读。correction-01 的历史文本保留，不改写历史 receipt 或事件。仍不得创建 DQA run、执行 DQA、测试、模型、服务、网络、索引或性能活动；修正后必须由全新一次性独立 Reviewer 复核。

### Correction 02 independent review receipt

- `reviewer_role`: 一次性独立 planner_b/Reviewer
- `reviewer_thread`: `01a04d90-d77a-74f1-8f98-ee2c00e64b78`
- `review_token`: `PLAN-B-REVIEW: ACCEPTED`
- `scope_token`: `PLAN-SCOPE-REVIEW: SUFFICIENT`
- `review_result`: correction-02 的 plan/packet/ledger revision、event、predecessor、自描述 ledger_revision 和 packet 引用的 design/ledger SHA 均与磁盘一致；未发现阻断 Finding。
- `reviewer_lifecycle`: final receipt received; agent archived immediately; context will not be reused
- `evidence_boundary`: 仅接受 correction-02 文档绑定；未执行 DQA、测试、索引、模型、服务、网络或性能活动，不证明任何质量门 PASS。

该回执使本设计达到 `CONSENSUS_READY`，但不构成 `MPV-02B DQA READONLY EXECUTION AUTHORIZATION`；DQA 仍需 authority owner 绑定 packet、输入、executor/verifier 和新的 D 盘 run 后另行授权。

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

本 correction 只修复两个合同阻断：以当前磁盘 `AGENTS.md` 的 fresh SHA 替换 packet 中的旧声明，并将 E03 收敛为唯一的固定 literal `e03_inventory_root` 目录 inventory 方案。旧 correction-01、correction-02 的事件和 receipt 原文保留，不改写历史记录；本 correction 不新增检查，不改变 DQA-01..09/E01..E08 业务语义、两道质量门、E02、E06 或指标公式。

### Executor preparation correction 03 finding map

| finding_id | root_cause_id | lineage | trigger/evidence | prior_unresolved_reason | revision_location | verification_method | user/product/trust impact | maintenance impact | current_status |
|---|---|---|---|---|---|---|---|---|---|
| DQA-F08 | RC-DQA-ROOT-RULE-PROVENANCE | REOPENED | packet 当前根规则 SHA 与磁盘 `AGENTS.md` fresh SHA 不一致；旧 receipt 只核对声明值，未完成本轮磁盘重读 | correction-02 的绑定复核未重新计算根规则字节，故不能证明当前授权前置引用的是实际规则 | packet 设计绑定、授权前置和本 correction 绑定 | 独立重算 `AGENTS.md` SHA，并与 packet/plan/ledger 当前绑定逐字段回读 | 旧规则可能被错误当作当前授权依据，造成执行边界和信任判断漂移 | 需要每个新 correction 明确 fresh root hash，避免 stale provenance | CHANGES_REQUIRED |
| DQA-F05 | RC-DQA-E03-INPUT-BOUNDARY | REOPENED | packet 同时要求完整 literal 文件 allowlist，又要求遍历质量基线根及后代；两套输入边界不可同时执行 | correction-02 只接受了静态 wording，未消除 literal allowlist 与递归 inventory 的组合冲突 | 主设计 E03 inventory 合同、E03 matrix 行、packet 历史基线输入和 E03 执行合同 | 只允许一个 literal `e03_inventory_root`；双次非 reparse 枚举、路径排序、匹配、hash、disposition 和失败路由逐项回读 | 可能漏读额外标注文件或越界读取 stage/project，导致 E03 独立性和可追溯性错误 | 未来 executor 只实现一套 inventory 算法和快照路径，不维护两套 allowlist 逻辑 | CHANGES_REQUIRED |

本 correction 保持 `CHANGES_REQUIRED / DQA_NOT_AUTHORIZED`，不得据此创建 DQA run、执行测试或推断任一质量门通过。修正完成后由上游创建全新的独立 Reviewer；在其最终回执前不得恢复 `CONSENSUS_READY`。

## Root-rule provenance resync

- `delta_class`: `SAME_SCOPE_HARDENING`
- `source_event`: `MPV-02B-DQA-LE-20260830-017`
- `active_root_rules_path`: `D:\Code\yeyu-ai\AGENTS.md`
- `active_root_rules_sha256`: `96EA33DF0061A041DD436B49317FA94023AE65A37C5EFBCFAD7354F6728505BF`
- `supersedes_for_authorization`: correction-03 的旧 `root_rules_sha256` 仅保留为 Reviewer 审查快照，不再作为当前授权前置
- `contract_effect`: 不改变 DQA 检查、E03、E06、两道质量门、输入范围或执行禁止项；合同 digest 不变
- `review_route`: 仅执行当前根规则 SHA 与活动绑定的定向 readback，保留 correction-03 的独立 Reviewer 接受回执，不重新进行完整方案复审
- `current_state`: `CONSENSUS_READY / DQA_NOT_AUTHORIZED`

本 resync 不授权 DQA；授权负责人仍须绑定当前 packet、literal 输入、executor、interpreter、verifier 和新的 D 盘 run。当前 lifecycle 仍以 ledger 最后一条有效事件为准。

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

## Executor contract correction 04

- `correction_id`: `MPV-02B-DQA-EXECUTOR-CONTRACT-CORRECTION-04`
- `source_receipt`: Sol executor design receipt, `EXECUTOR-DESIGN: CHANGES_REQUIRED`
- `predecessor_event`: `MPV-02B-DQA-LE-20260830-019`
- `delta_class`: `MATERIAL_REVIEW_CHANGE`
- `scope_review`: `PLAN_SCOPE_REVIEW: SUFFICIENT`
- `changes`: 增加 packet-bound 的机器可读 17 项检查矩阵；明确 `required_literal_inputs`、`optional_absence_allowed` 和唯一 `e03_recursive_root` 三类输入；固定 `ROOT_UNSAFE_BLOCKED` 的单行 UTF-8 结构化 stdout 回执及协调者原样保存规则。
- `not_changed`: 不新增 DQA 检查，不改变 DQA-01..09/E01..E08 语义、E02、E06、E07、两道质量门、禁止活动或 DQA 执行授权。
- `verification`: 独立 Reviewer 逐字段回读机器矩阵 17/17、主设计/packet 投影、三类输入分类和阻断回执 schema；检查 JSON UTF-8 可解析、diff 仅在本 correction 白名单内。
- `current_state`: `PLAN_B_REVIEW_REQUIRED / CONSENSUS_BLOCKED / DQA_NOT_AUTHORIZED`

F-EXE-001 仍是未来授权前的 executor/interpreter/verifier 身份绑定前置，不因本 correction 伪造入口或 SHA；在入口实现并获授权前保持 `BLOCKED_UNBOUND`。F-EXE-002、F-EXE-003、F-EXE-004 的最小修复已落盘，等待全新一次性 Reviewer；在最终回执前不得恢复 `CONSENSUS_READY`。

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
