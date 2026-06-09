---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: b6d2bc339d43c35aa9002578e20a1d53_186f945a634611f1aa705254002afed2
    ReservedCode1: l5i2nxSTTF7UWn5XY5O6bexVnlnbJpkPP0wV0NmdP9mQORFf1D/4npZAfIYI+ZvtmmUcpkNr1Z6O76b3TDXxCp/38g4vrZEkMNMUCjMmBRxzLS2VRQMN6DuDZbUyMFJpBWDbYejC1hIVdaDVupygf4mQ9syXCnDrzm3zX5gO9tsdIP0yslfSP/1LRrg=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: b6d2bc339d43c35aa9002578e20a1d53_186f945a634611f1aa705254002afed2
    ReservedCode2: l5i2nxSTTF7UWn5XY5O6bexVnlnbJpkPP0wV0NmdP9mQORFf1D/4npZAfIYI+ZvtmmUcpkNr1Z6O76b3TDXxCp/38g4vrZEkMNMUCjMmBRxzLS2VRQMN6DuDZbUyMFJpBWDbYejC1hIVdaDVupygf4mQ9syXCnDrzm3zX5gO9tsdIP0yslfSP/1LRrg=
---



# 番茄小说 AI 创作系统 — DeepSeek 项目简报

> 复制以下内容发给 DeepSeek，让它快速了解这个项目。

---

## 我是谁

我是多项目 LLM 应用开发者，当前维护一个网文 AI 创作辅助系统。

## 项目概况

**名称**: 番茄小说 AI 辅助创作系统 v7.4  
**路径**: `d:\Code\xiaoshuo\`  
**目标**: 量化爆款网文 → 指导新人写出高质量、不被拒稿的网文（当前聚焦末世/科幻，可扩展任意题材）  
**当前作品**: 《末日模拟器》智斗生存流+人外羁绊+代价驱动进化，5卷300章  
**核心原则**: 正文100%手写，AI 仅做分析/建议/审阅，禁止生成超过30字的连续小说正文

## 共享基础设施

- conda 环境: `llm-shared` @ `D:\miniconda3\envs\llm-shared\` (Python 3.12, llama-cpp-python 0.3.22, CUDA 13.0)
- llama-server: `D:\miniconda3\envs\llm-shared\Library\bin\llama-server.exe`
- 模型库: `D:\DaMoXing\` — Qwen3.5-9B-Q4_K_M.gguf (5.7G) / Qwen3-4B-Q4_K_M.gguf (2.5G) / Qwen2.5-7B-Q4_K_M.gguf (4.4G)
- 硬件: RTX 5060 8GB, Windows 11
- 所有项目共享上述 conda 环境和模型库

## 技术栈

| 层 | 技术 |
|---|---|
| 本地推理 | llama.cpp server HTTP API (OpenAI 兼容)，端口 8000，Qwen3.5-9B Q4_K_M |
| 云端模型 | DeepSeek V4-Flash / V4-Pro (api.deepseek.com) |
| 代码规范 | Python 3.12, pathlib.Path(), config.yaml 单一事实源 |
| 开发工具 | CodeBuddy IDE + 8个 Skill (进化/审视/搜索/澄清) |

## 六阶段管线

```
① 入库过滤 → ② 拆书分析 → ③ 商业评分 → ④ 类型整合 → ⑤ 创作指导 → ⑥ 双文对比进化
```

- ① `book_processor.py`: 编码检测→转码→题材识别→基础过滤（≥200KB, ≥5章, 中文≥40%）
- ② `rhythm_analyzer.py`: 逐章30+指标（爽点/钩子/冲突/节奏/可读性）
- ③ `genre_synthesizer.py`: 商业评分 + Bootstrap CI + 拆书三件套
- ④ `creative_bridge.py`: 精品数据→8维创作指导（题材/世界观/粗纲/细纲/文笔/人物/情节/反同质化）
- ⑤ `agents/` 六模块: orchestrator/skill_loader/state_machine/world_builder/outline_builder/cross_review
- ⑥ `comparison_engine.py`: 三版对比（作者+本地LLM+AI参考版），/千字归一化差异

## 目录速查

| 目录 | 用途 |
|------|------|
| `analysis/` | 数据分析管线 (19个py) |
| `agents/` | LLM代理 (7个py) |
| `scripts/` | 工具脚本 (13个: start_model / lint / convert_encoding ...) |
| `assets/` | 创作资产 (library / canon / chapters / outline / voice) |
| `books/` | 书籍入口: in/→review/→data/raw/novels/ |
| `data/raw/` | 原始小说TXT (只读) |
| `data/processed/` | 中间产物 (节奏CSV / LLM评分 / quality_manifest) |
| `outputs/reports/` | 分析报告 & 创作指导 |
| `prompts/` | Marvis审查工作流 (pending/replies/history) |
| `tests/` | 金标测试集 |
| `.codebuddy/` | CodeBuddy 配置 (skills/rules/settings.json) |

## 核心约束

1. 禁止 print() 用 Unicode → 用 `[OK]` `[FAIL]` 标记
2. 编辑文件前必须 read_file 确认当前内容
3. 禁止硬编码阈值/路径/端口 → 放 `config.yaml`
4. 所有路径用 `pathlib.Path()`
5. 禁止生成 >30 字连续小说正文
6. 每次代码修改后运行 `scripts/lint.bat`
7. 穷举搜索必须跑满12轮，不可提前收敛
8. 单一事实源：`config.yaml` 是唯一配置入口

## 当前状态

- P0 阶段已完成（基础管线+评分体系+创作指导）
- P1 待开发（语义记忆/对抗改写/风格蒸馏LoRA）
- DESIGN.md 是完整架构文档，README.md 是快速上手指南
- 已接入 CodeBuddy + DeepSeek API 云端协作开发

## 你能帮我做什么

- PyTorch / llama-cpp-python / CUDA 性能优化
- Python 架构设计、重构建议
- 网文 NLP 分析算法（节奏检测、风格指纹、情感弧）
- config.yaml / DESIGN.md 设计评审
- 逐模块代码审查（从 analysis/ 到 agents/）
*（内容由AI生成，仅供参考）*
*（内容由AI生成，仅供参考）*
