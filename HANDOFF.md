# 项目交接文档 v7.5 → GLM5.2

> **目标读者**: GLM5.2 AI 开发者
> **更新**: 2026-06-19 11:00 · 拆书管线running + 进度面板ready

---

## 一、项目一句话

番茄小说 AI 辅助创作系统 — 帮助网文作者（末世/科幻题材）对 33 本精品书做深度拆书分析，产出写作指导。《末日模拟器》5卷300章准备开写，正文全手写。

---

## 二、硬件与环境

| 项目 | 值 |
|------|-----|
| GPU | RTX 5060 8GB |
| 环境 | `conda activate llm-shared` |
| Python | 3.12 (D:\miniconda3\envs\llm-shared) |
| 本地模型 | Qwen3.5-9B-Q4_K_M, llama-server :8000 |
| ctx-size | 8192 (KV q8_0), **单槽位实际分配 4096** |
| 云端模型 | DeepSeek V4-Flash/Pro (api.deepseek.com，备用) |
| 项目根 | `d:\Code\xiaoshuo\` |

---

## 三、目录速查

```
d:\Code\xiaoshuo\
├── analysis/          # 核心管线 (31个.py)
│   ├── recursive_summarize.py  ★ 当前焦点 — 深层拆书 v2
│   ├── rhythm_analyzer.py      # 节奏拆书 (已完成)
│   ├── llm_batch_score.py      # LLM评分 (已完成, Hook修复过)
│   ├── genre_synthesizer.py    # 商业评分
│   ├── creative_bridge.py      # 创作指导
│   ├── cross_book_synthesis.py # 跨书关联 (等LLM数据)
│   ├── contract_chain.py       # 合同链
│   ├── writing_instructions.py # 逐章指令
│   └── analyze_all.py          # 一键全链路
├── agents/            # LLM代理模块 (10个.py)
├── scripts/           # 工具脚本
│   ├── start_model.bat         # 启动llama-server
│   ├── progress_server.py ★  # 进度Web面板
│   ├── check_scores.py         # 评分质量检查
│   └── lint.bat                # 代码检查
├── data/
│   ├── raw/novels/末世/        # 33本原始TXT (不可改)
│   └── processed/末世/         # 中间产物
│       ├── rhythm/             # 33本节奏CSV ✅
│       ├── llm_scores/         # 30本LLM评分CSV ✅
│       ├── llm_labels/         # 27/33本LLM标注CSV ⚠️
│       └── summaries/          # ★ 递归摘要产出 (checkpoint+JSON)
├── config.yaml        # 唯一配置入口 (v7.5)
├── CODEBUDDY.md       # 技术速查
├── DESIGN.md          # 架构设计总索引
├── HANDOFF.md         # 本文件
├── run.bat            # 一键启动面板+拆书
└── .codebuddy/rules/  # 项目规则 (project.mdc + status.mdc)
```

---

## 四、当前管线进度

```
① book_processor       → 33本入库              ✅
② rhythm_analyzer      → 33本节奏CSV (39397章)  ✅ (数据质量: 0%空值)
③ llm_labeler          → 27/33本LLM标注         ⚠️ (缺6本)
④ llm_batch_score      → 30/33本LLM评分         ✅ (Hook分布合理, 缺3本)
⑤ recursive_summarize  → 深层拆书              🔄 运行中!
⑥ quality_gate         → 品质关卡              ⬜ (等⑤)
⑦ genre_synthesizer    → 商业评分 (旧版)         ⚠️ (需⑤完成后重跑)
⑧ creative_bridge      → 创作指导 (旧版)         ⚠️ (需⑦完成后重跑)
⑨ cross_book_synthesis → 跨书白皮书             ⬜ (等⑤)
⑩ writing_instructions → 逐章指令+合同链          ⬜ (等⑧)
```

**核心依赖**: ⑤→⑥→⑦→⑧→⑨→⑩，当前卡在⑤。

---

## 五、当前运行状态 & 最近48h改动

### 5.1 刚修复的关键Bug

| Bug | 症状 | 修复 |
|-----|------|------|
| **JSON截断** | L1 prompt 返回JSON被 max_tokens=800 截断 → `_parse_json()`返回None → 全部失败 | `max_tokens` 800→1500(L1)/1200(L2)/1800(L3); 新增 `_repair_json()` 自动补闭合括号 |
| **sys.path缺失** | 独立运行时 `ModuleNotFoundError: analysis` | 文件头 `sys.path.insert(0, PROJECT_ROOT)` |
| **import在函数内** | rule 11违规 | `from analysis.rhythm_analyzer import extract_chapters` 提到顶部 |
| **断点续传空数据** | checkpoint 恢复时返回空壳 → L2/L3质量崩 | 新增 `l1_data` 在checkpoint存实际JSON；`_run_l1_if_needed()` 加 `_save_partial()` |
| **面板百分比错误** | 显示 3/413 而非 3/114 | 面板改为从 rhythm CSV 读真实章节数 |
| **浏览器重复打开** | `_start_progress_panel()` 也调 `webbrowser.open()` | 已移除 |

### 5.2 recursive_summarize.py 当前能力

- **L1**: 每8章group → LLM提取钩子/角色/情绪/冲突/伏笔 → JSON
- **L2**: 每5组L1 → LLM合成卷级节奏+伏笔链+冲突升级
- **L3**: 全书 → LLM产出结构模式+爽点分布+角色弧+商业评估
- **幂等跳过**: `_is_output_valid()` 6项检查 → 已完成的书秒级跳过
- **断点续传**: checkpoint存L1数据+进度 → 中断重跑自动恢复
- **死信队列**: 3次重试失败 → 写入 `_failed.jsonl`
- **质量门**: `_quality_report()` 标记空L1/缺L3字段
- **进度条**: `\r` 覆盖刷新 + ETA计算
- **进度面板**: HTTP :8090，每3秒自刷新，读checkpoint显示

### 5.3 刚刚在跑但进程已退出

最后一次运行: 第一本书《世界末日从考试不及格开始》跑了 3/114 L1 chunks 后进程退出。checkpoint 已存——重新跑会从 chunk 4 恢复。

---

## 六、你的第一条恢复指令

```bash
# 1. 确认LLM server在线
python -c "import requests; print(requests.get('http://localhost:8000/health',timeout=3).status_code)"
# 期望: 200

# 2. 如果不在线，启动
scripts\start_model.bat

# 3. 启动进度面板+浏览器+拆书（一行）
cd d:\Code\xiaoshuo
powershell -Command "Start-Process python -ArgumentList 'scripts/progress_server.py' -WindowStyle Minimized; Start-Sleep 2; Start-Process 'http://localhost:8090'; python analysis/recursive_summarize.py --book all --genre 末世"

# 4. 浏览器监控: http://localhost:8090
```

---

## 七、管线核心命令

```bash
# 深层拆书 (当前步骤)
python analysis/recursive_summarize.py --book all --genre 末世

# 单本测试
python analysis/recursive_summarize.py --book 全球进化 --genre 末世

# 全链路一键 (等recursive_summarize跑完后)
python analysis/analyze_all.py --with-llm --genre 末世

# 代码检查
python novel.py test
scripts\lint.bat

# 评分质量
python scripts/check_scores.py
```

---

## 八、关键设计决策 & 约束

### 8.1 硬约束

1. **禁止 print() 用中文Unicode** — Windows GBK崩溃，用 `[OK]` `[FAIL]`
2. **编辑前必须 read_file** — 文件可能已被修改
3. **禁止硬编码** — 路径/阈值/端口全部放 `config.yaml`
4. **所有路径用 pathlib.Path()**
5. **禁止生成 >30字连续小说正文** — 只分析不创作
6. **禁止 import 在函数内部** — 全部放文件顶部 (rule 11)
7. **禁止函数直接修改入参 dict/list** — 用浅拷贝
8. **每次代码变更后跑 lint** — `python novel.py test`
9. **单一事实源**: config.yaml
10. **Skill触发词优先** — 项目有8个Skill(进化/审视/搜索)，触发词必须加载对应Skill

### 8.2 技术决断

| 项目 | 决策 | 原因 |
|------|------|------|
| 单模型 | Qwen3.5-9B only | 单模型评分4.41/5 |
| ctx=8192 | 但单槽位分配4096 | LLM server自动决定 |
| 不能并发 | RTX 5060 8GB | 单请求5.6GB，2个=OOM |
| chunk_size=8 | 加速-20%调用量 | 8章≈4000tokens < 4096 |
| 进度面板 | Python stdlib HTTP | 零依赖，lightweight |

### 8.3 未完成但需要的优化 (可选,不急)

- `recursive_summarize.py` 的 `l1_total` 字段会在下次重启后自动写入checkpoint，面板就能从checkpoint读了
- L1→L2 流水线重叠 (-15%耗时，代码侵入大)
- llm_labels缺6本, llm_scores缺3本 (跑完recursive_summarize后补)

---

## 九、常见问题

### Q: 面板打开但全是"等待中"
A: 关掉旧的progress_server窗口，重新跑上面的启动命令。新面板从 rhythm CSV 读总章节数。

### Q: 面板显示 "ERR_EMPTY_RESPONSE"
A: progress_server进程挂了。检查 `Get-Process python`，关掉占8090端口的老进程。

### Q: 所有L1 chunk返回"LLM returned None"
A: 模型输出截断。确认使用了最新版 `recursive_summarize.py`（含 `_repair_json`）。

### Q: 百分比不准
A: 已解决。面板从 rhythm CSV 读真实章节数。旧版本从文件大小估算(不准)。

---

## 十、文件清单 (最近改动过的)

| 文件 | 最后改动 | 用途 |
|------|----------|------|
| `analysis/recursive_summarize.py` | 刚改 | 深层拆书+checkpoint+进度+JSON修复 |
| `scripts/progress_server.py` | 刚改 | Web进度面板 (:8090) |
| `config.yaml` | 刚改 | n_ctx=8192, v7.5 |
| `CODEBUDDY.md` | 刚同步 | 技术速查 |
| `.codebuddy/rules/project.mdc` | 刚同步 | 项目规则 |
| `.codebuddy/rules/status.mdc` | 刚同步 | 项目状态 |
| `run.bat` | 新建 | 一键启动脚本 |

---

**签收**: 如果你读到这里，执行第六章的第一条恢复指令，拆书就会从 chunk 4 继续跑。GLM5.2，接棒。
