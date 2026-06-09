# 番茄小说 AI 辅助创作系统 v7.4

## 60秒快速上手

```bash
# 一键全量分析
python novel.py analyze --genre 末世

# 含LLM增强（需启动模型）
scripts\start_model.bat
python novel.py analyze --genre 末世 --with-llm

# 全题材
python novel.py analyze --all

# 意图→建议
python novel.py intent --text "这章太拖了"

# 逐章写作指令
python analysis/writing_instructions.py
```
> 详见 `python novel.py --help`

## 项目目标

**近期**: 任一题材有足够精品书 → 量化指导新人写出高质量爆款。**终局**: 精品库持续蒸馏 → AI 拥有独立风格 → 写出不被识别为AI的原创小说。

核心原则：**正文100%手写，AI仅做分析/建议/审阅**，禁止生成>30字连续小说正文。**所有建议必须有精品书量化数据支撑**。

## 六阶段管线

| 阶段 | 模块 | 干什么 |
|:---:|------|------|
| ① 入库 | `book_processor` | 过滤低质量（残缺/乱码/无章节/低字数）→ 按题材分类 |
| ② 拆书 | `rhythm_analyzer` | 逐章30+指标：爽点/钩子/冲突/节奏/可读性 |
| ③ 评分 | `genre_synthesizer` | 商业评分（拆书三件套+情感弧）+ Bootstrap CI |
| ④ 整合 | `creative_bridge` | 精品数据 → 8维创作指导（题材/世界观/粗纲/细纲/文笔/人物/情节/反同质化） |
| ⑤ 指导 | `agents/` | 6模块：orchestrator/skill_loader/state_machine/world_builder/outline_builder/cross_review |
| ⑥ 对比 | `comparison_engine` | 三版对比（作者+本地LLM+AI参考版）+ 分段节奏 + /千字归一化 |

| 功能 | 状态 | 
|------|:---:|
| ①-⑥ 全管线 | ✅ |
| ⑦ 风格蒸馏(LoRA) | 🔮 待扩书30+ |
| S4+++ 七层检测 | 🔮 规划中 |

## 目录速查

| 目录 | 用途 |
|------|------|
| `analysis/` | 数据分析管线 (19个py) |
| `agents/` | LLM代理 (7个py：路由/状态机/世界观/大纲/交叉评审) |
| `scripts/` | 工具脚本 (start_model / lint / convert_encoding 等) |
| `assets/` | 创作资产 (library/canon/chapters/outline/voice) |
| `books/` | 书籍入口: in/→review/→data/raw/novels/ |
| `data/raw/` | 原始小说TXT（只读） |
| `data/processed/` | 中间产物 (CSV/JSON) |
| `analysis/outputs/` | 分析运行时产物（报告/指导/校准） |
| `outputs/reports/` | 精选报告归档 |
| `AI_PROTOCOL.md` (根) | LLM行为协议，由 `agents/skill_loader.py` 注入 System Prompt |
| `.codebuddy/skills/` | CodeBuddy技能 (8个：进化/审视/搜索/澄清) |
| `notebooks/` | 🆕 探索性分析 (Jupyter) |
| `prompts/` | Marvis审查工作流 (pending/replies/history) |

## 快速开始

```bash
# 1. 下载小说.txt → 放到 books/in/
# 2. 入库+基础过滤
python analysis/book_processor.py
# 3. 全量分析（5步自动化：入库→节奏→关卡→合成→创作指导）
python analysis/analyze_all.py --genre 末世
# 4. （可选）LLM评分 → 再跑一次 3
scripts/start_model.bat && python analysis/llm_batch_score.py --book all
# 5. 查看创作指导
cat analysis/outputs/reports/creative_guidance/末世_创作指导.md
# 6. books/review/ 有书？→ 人工审查
```

## 配置

所有阈值/路径/端口集中在 `config.yaml` → `analysis:` 段，SSOT 设计：

```yaml
book_filter: { min_size_kb: 200, min_chapters: 5, min_chinese_density: 0.40 }
quality_gate: { min_rhythm_chapters: 10, max_zero_hook_streak: 5, min_commercial_score: 30 }
commercial_grades: { high: 70, medium: 50, low: 30 }
llm_port: 8000
```

---

**深度架构见 `DESIGN.md`** · **AI协议见 `AI_PROTOCOL.md`** · **约束规则见 `.codebuddy/rules/project.mdc`**
