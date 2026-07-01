# 番茄小说 AI 创作辅助系统 v7.5

## 业务逻辑
- 番茄小说平台网文创作辅助工具，目标用户：网文作者（末世/科幻）
- 核心功能：爆款分析、拆书、生成写作指导、章节进化
- 当前作品：《末日模拟器》5卷300章，智斗生存流+人外羁绊+代价驱动进化
- 正文100%手写，AI仅做分析/建议/审阅，不生成连续小说正文（<30字例外）
- 新增: 合同链(写前合同→债务看板→写后审计) · LLM分片评分 · OLS校准 · 递归摘要(深层拆书) · 跨书关联(品类白皮书)

## 技术架构

### 本项目模型
- 本地模型：Qwen3.5-9B (Q4_K_M, port 8000, n_ctx=8192, chatml, KV q8_0)
- 云端模型：DeepSeek V4-Flash / V4-Pro (API: api.deepseek.com)
- 通信方式：llama-server HTTP API (OpenAI 兼容)，非 Python in-process
- R1-Distill-Qwen-7B 仅作备份 (port 8002, enabled: false)

## 关键决策
| 日期 | 决策 | 理由 |
|------|------|------|
| 2026-06-01 | RTX 5060 本地跑 Qwen3.5-9B | 单模型评分 4.41/5 |
| 2026-06-04 | 工作流 v7.0→v7.3，加入拆书全管线 | P0 完成后进入 P1 |
| 2026-06-05 | MTP 已排除 (Dense -42%) | 实测无效 |
| 2026-06-05 | single_model 方案 (Qwen3.5) | 替代多模型方案 |
| 2026-06-08 | 接入 CodeBuddy + DeepSeek API | 云端协作开发 |
| 2026-06-19 | 合同链模块 (webnovel-writer 借鉴) | 写前校验+债务追踪+写后审计 |
| 2026-06-19 | 递归摘要 + ctx-size 3072→8192 | L1章→L2卷→L3全书, 50章+伏笔追踪 |

## 目录速查
| 目录 | 用途 |
|------|------|
| `analysis/` | 数据分析管线 (合同→入库→节奏→评分→深层拆书→关卡→报告→处方→跨书关联) |
| `agents/` | LLM代理 (路由/状态机/世界观/大纲/交叉评审) |
| `books/` | 书籍入口: in/→review/→data/raw/novels/ |
| `data/raw/` | 原始小说TXT (不可修改) |
| `data/processed/` | 中间产物 (CSV/JSON) |
| `assets/` | 创作资产 (library/canon/chapters/outline/voice) |
| `outputs/reports/` | 分析报告 |
| `.codebuddy/skills/` | 8个Skill (进化/审视/搜索/澄清) |
| `.codebuddy/rules/` | project.mdc + status.mdc |

## 常用命令
```bash
# 启动本地模型
scripts\start_model.bat

# 代码检查
scripts\lint.bat

# 一键全量分析
python analysis/analyze_all.py --with-llm

# 编码转换 (GBK→UTF-8)
python scripts/convert_encoding.py

# Conda 环境
conda activate llm-shared
```

## 核心约束 (详见 .codebuddy/rules/project.mdc)
1. 禁止 print() 用 Unicode → 用 [OK] [FAIL]
2. 编辑文件前必须 read_file 确认当前内容
3. 禁止硬编码阈值/路径/端口 → 放 config.yaml
4. 所有路径用 pathlib.Path()
5. 禁止生成 >30 字连续小说正文
6. 每次代码修改后运行 lint.bat
7. Skill 触发词匹配优先于所有其他规则
8. 穷举搜索必须跑满12轮，不可提前收敛
9. 单一事实源：config.yaml 是唯一配置入口
