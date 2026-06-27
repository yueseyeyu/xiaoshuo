#!/usr/bin/env python3
"""
============================================================================
novel.py — 番茄小说 AI 辅助创作系统 CLI 入口
============================================================================

── 系统概述 ──
本文件是系统的命令行入口。所有用户操作通过子命令路由到对应模块。
当前: init/status/s1/s3/worldbuild/test 可用, s4 为占位。

── 架构说明 ──
· 命令路由: argparse → dict dispatch → cmd_*() 函数
· 配置管理: config.yaml (YAML) + state.json (JSON)
· 模块加载:  懒加载 — 仅被调用的命令才 import 对应模块
· 模型通信:  通过 llama.cpp HTTP API (OpenAI 兼容格式)
· 设计文档:  DESIGN.md（完整架构，本文件的"参考手册"）

── 扩展命令 ──
添加新命令只需三步:
  1. 在文件末尾的 commands dict 中注册
  2. 实现 cmd_xxx(args) 函数
  3. （可选）用 sub.add_parser() 添加参数

── 依赖 ──
  pip install pyyaml    # config.yaml 解析
  urllib.request        # llama.cpp HTTP 调用（stdlib，无需安装）

── 用法示例 ──
  python novel.py init              # 初始化项目
  python novel.py status            # 查看系统状态
  python novel.py s1 --chapter 5    # 第5章创意引导（P0实现后）
  python novel.py s3 --chapter 5    # 第5章逻辑评审（P0实现后）
============================================================================
"""

import argparse
import yaml          # pip install pyyaml
import json
import sys
from pathlib import Path
from datetime import datetime

# v8.0 重构: src/ 加入 sys.path，启用包绝对 import
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from xiaoshuo import __version__


# ============================================================================
# 全局常量 — 项目根目录 & 关键文件路径
# ============================================================================

# 项目根目录 = 本文件所在目录（所有相对路径的基准）
PROJECT_ROOT = Path(__file__).resolve().parent

# 核心配置文件（必须存在，否则系统无法运行）
CONFIG_PATH = PROJECT_ROOT / "config.yaml"

# 运行时状态文件（init 时自动创建，记录当前进度/模型状态/实验数据）
STATE_PATH  = PROJECT_ROOT / "state.json"

# Windows 终端 GBK 兼容 — 避免 Unicode 符号（✓✗·）导致的编码崩溃
# 所有 print 使用这些 ASCII 常量而非直接写 Unicode
OK   = "[OK]"
FAIL = "[FAIL]"
INFO = " - "


# ============================================================================
# 配置 & 状态 I/O — 系统的"记忆"
# ============================================================================

def load_config() -> dict:
    """
    加载 config.yaml 并返回字典。
    
    ── 错误处理 ──
    如果 config.yaml 不存在 → 提示用户先 init，退出。
    这是 init 之前唯一会报错的函数。
    
    ── 线程安全 ──
    当前为单用户单进程，不需要锁。若后续引入 FastAPI/MCP 多进程访问，
    需要在读配置时加文件锁。
    """
    if not CONFIG_PATH.exists():
        print(f"[ERROR] 配置文件不存在: {CONFIG_PATH}")
        print("  请先运行: python novel.py init")
        sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_state() -> dict:
    """
    加载 state.json 并返回字典。
    
    如果文件不存在（首次运行、或手动删除），返回空字典。
    调用方需对空字典做 .get(key, default) 容错。
    
    ── 为什么用 JSON 而非 YAML ──
    state.json 是机器写入、机器读取的运行时状态，不需要人工编辑。
    JSON 序列化更快、更小，且不会引入 YAML 的类型推断风险。
    """
    if STATE_PATH.exists():
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state: dict) -> None:
    """
    将状态字典原子写入 state.json。
    
    ── 数据结构约定 ──
    顶层 key 见 DESIGN.md §5.3 或 cmd_init() 中的 initial_state。
    新增 key 时需要同步更新：
      1. cmd_init() 中的 initial_state 字典
      2. cmd_status() 中的读取逻辑
      3. DESIGN.md §5.3 的 schema 文档
    """
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ============================================================================
# 目录 & 模板定义 — init 命令的数据源
# ============================================================================

# ── 项目目录清单 ──
# 所有目录相对于 PROJECT_ROOT。init 时按顺序创建。
# 修改此列表后，已创建的旧目录不会自动删除（安全优先）。
DIRECTORIES = [
    # 工具层 — 可执行脚本
    "scripts",

    # 引擎层 — AI 行为模块
    "agents",

    # 资产层 — 创作资产（统一使用 assets/ 前缀）
    "assets/canon",
    "assets/voice",
    "assets/outline",
    "assets/chapters",
    "assets/library",
    "assets/library/genres",
    "assets/library/references",

    # 评估层 — 测试 & 基准
    "tests/golden_test_set/ground_truth",
    "tests/golden_test_set/prompts",
    "tests/golden_test_set/expected",

    # 数据分析层 — 按题材组织
    "data/raw/novels",              # 精品小说TXT (book_processor 入库)
    "data/processed",               # 处理后数据 (按题材子目录)
    "data/reports",                 # 分析报告 (按题材子目录)

    # 书籍入口
    "books/in",                     # 原始下载 (手动放入)
    "books/review",                 # 退回审查 (quality_gate 不达标)

    # 分析层 — 报告输出已统一到 data/reports/
    "review/jury_reports",          # S3 评审报告
    "review/beat_reports",          # M5a 节拍分析
    "review/drift_reports",         # M5b 风格漂移
    "review/comparison",            # S2c 对比分析
    "review/logic_reports",         # S3 逻辑警察独立报告
    "review/style_reports",         # S4+++ 风格检测报告
    "review/rhythm_reports",        # P1 节奏曲线报告
    "review/density_reports",       # P1 类型化爽点库

    # 存储层 — 持久化数据
    "memory",

    # 归档层 — 历史记录
    ".archive/ai_references",       # S2b AI参考版历史

    # 探索层 — 分析Notebook
    "notebooks",                    # Jupyter/IPython探索分析
]

# ── 模板文件 ──
# key = 相对路径, value = 初始内容。
# 仅在文件不存在时创建，已存在的文件不会被覆盖（保护用户数据）。
TEMPLATE_FILES = {
    # assets/canon/ — 设定数据库（作者手动维护）
    "assets/canon/world.md":              "# 世界观设定\n\n> 待填写 — 参见 DESIGN.md §4.10\n",
    "assets/canon/characters.md":         "# 角色设定\n\n> 待填写 — 后续由 NovelGraph 自动关联\n",
    "assets/canon/rules.md":              "# 规则体系\n\n> 待填写 — 力量体系/经济系统/社会规则\n",
    "assets/canon/timeline.md":           "# 时间线\n\n> 待填写 — 后续从 NovelGraph 时序图自动生成\n",
    "assets/canon/foreshadowing.md":      "# 伏笔追踪\n\n> 待填写 — 含因果链 + SVO 追溯\n",
    "assets/canon/emotional_arcs.md":     "# 情感弧线\n\n> 待填写 — 每章结束后自动更新\n",
    "assets/canon/subplot_board.md":      "# 支线看板\n\n> 待填写 — 多线叙事管理\n",

    # assets/voice/ — 文风层（机器辅助维护）
    "assets/voice/voice.md":              "# 文风指南\n\n> 待填写 — 从基线数据自动生成 (P0)\n",
    "assets/voice/anti_slop_blacklist.md":"# AI 指纹黑名单\n\n> P2 动态更新 — 社区AI常用词爬取+去重\n",
    "assets/voice/platform_compliance.md":"# 平台合规参考\n\n> PAN 2026 对抗策略参考\n",

    # assets/outline/ — 大纲层
    "assets/outline/rough_outline.md":    "# 粗纲\n\n> S0 阶段由 LLM 生成（脱敏后）\n",
    "assets/outline/candidates.md":       "# 候选方向\n\n> S0 反同质化检查结果\n",
}


# ============================================================================
# 命令: init — 项目初始化
# ============================================================================

def cmd_init(args) -> None:
    """
    初始化项目目录结构 & 状态文件。

    ── 幂等性 ──
    可安全多次运行。已存在的目录/文件不会被覆盖或删除。
    适合用于"在新机器上恢复项目环境"。

    ── 执行流程 ──
    1. 创建所有目录（DIRECTORIES 列表）
    2. 创建模板文件（TEMPLATE_FILES 字典，仅当不存在时）
    3. 创建 state.json（仅当不存在时）
    """
    print("[INIT] 初始化番茄小说 AI 辅助创作项目...")
    print(f"  项目根目录: {PROJECT_ROOT}")

    # Step 1: 创建目录
    for d in DIRECTORIES:
        path = PROJECT_ROOT / d
        path.mkdir(parents=True, exist_ok=True)
        print(f"  {OK} {d}/")

    # Step 2: 创建模板文件
    for filepath, content in TEMPLATE_FILES.items():
        path = PROJECT_ROOT / filepath
        if not path.exists():
            path.write_text(content, encoding="utf-8")
            print(f"  {OK} {filepath}")
        else:
            print(f"  {INFO} {filepath} (已存在，跳过)")

    # Step 3: 创建状态文件
    # 状态文件的 schema 需要与 DESIGN.md §5.3 和 cmd_status() 同步维护
    if not STATE_PATH.exists():
        initial_state = {
            # ── 基础信息 ──
            "version": __version__,
            "created_at": datetime.now().isoformat(),

            # ── 进度追踪 ──
            "current_chapter": 0,
            "current_stage": "INIT",               # INIT|S0|S1|S2a|S2b|S2c|S2d|S3|S4|PUBLISH
            "completed_stages": [],
            "debts": [],                           # 债务队列: [{type, trigger, scope}]

            # ── 模型状态 ──
            "orchestrator_mode": "pending",        # P0 实验后 → dual_model|single_model
            "active_models": {},                   # runtime 填充: {name: {port, status, vram}}

            # ── 分析状态 ──
            "active_narrative_framework": "save_the_cat",
            "active_rhythm_model": "four_phase",
            "svo_stats": {"total_extracted": 0, "last_chapter_svos": 0},
            "semantic_concepts": {"total": 0, "active": 0, "contradicted": 0},
            "drift_history": [],                   # [{at_chapter, magnitude, direction, alert}]
            "style_noise_active": False,
            "pleasure_density": {
                "total": 0, "last_chapter": 0,
                "rhythm_curve_phase": "unknown"    # buildup|delay|peak|afterglow
            },

            # ── 评估 & 测试 ──
            "test_results": {},
            "ab_test": {"active": False},

            # ── 风格基线 ──
            "baseline_chapters": [],               # 用于建立声音基线的章节列表
            "baseline_dimensions": 12,             # P0 12 维，P2 升级至 28

            # ── 缓存状态 ──
            "prefix_cache": {
                "file": "memory/system_prompt_cache.bin",
                "hit_rate": 0.0
            }
        }
        save_state(initial_state)
        print(f"  {OK} state.json")
    else:
        print(f"  {INFO} state.json (已存在，跳过)")

    print(f"\n[INIT] 完成！")
    print("  下一步:")
    print("    python novel.py status         # 查看系统状态")
    print("    python novel.py s1 --chapter 1  # 第1章创意引导（P0实现后）")


# ============================================================================
# 命令: status — 系统状态查看
# ============================================================================

def cmd_status(args) -> None:
    """
    打印系统完整状态报告：进度、模型文件、配置完整性、P0 待办。

    ── 调用时机 ──
    · 每天开始创作前 — 确认模型和配置就绪
    · 下载新模型后 — 确认文件大小和路径正确
    · 排查问题时 — 快速定位是配置/模型/代码哪一层的问题

    ── 无副作用 ──
    本函数仅读取 config.yaml 和 state.json，不修改任何文件。
    """
    state = load_state()
    config = load_config()

    print("=" * 60)
    print(f"  番茄小说 AI 辅助创作系统 v{__version__}")
    print("=" * 60)

    # ── 进度 ──
    ch = state.get("current_chapter", 0)
    stage = state.get("current_stage", "UNKNOWN")
    # 10-stage progress indicator
    ALL_STAGES = ["S0", "S1", "S2a", "S2b", "S2c", "S2d", "S3", "S4", "S4+", "PUBLISH"]
    stage_idx = ALL_STAGES.index(stage.split("_")[0]) if any(s in stage for s in ALL_STAGES) else 0
    progress_bar = "".join(
        f"[{s}]" if s == ALL_STAGES[stage_idx] else " . " for s in ALL_STAGES
    )
    print(f"  进度: 第 {ch} 章 | 阶段 {stage_idx + 1}/{len(ALL_STAGES)}")
    print(f"  {progress_bar}")
    print(f"  当前: {stage}")
    if state.get("completed_stages"):
        print(f"  已完成: {' -> '.join(state['completed_stages'])}")

    # ── 模型编排 ──
    orch_mode = state.get("orchestrator_mode", "pending")
    print(f"\n  模型编排模式: {orch_mode}")
    active = state.get("active_models", {})
    if active:
        for name, info in active.items():
            s = info.get("status", "unknown")
            print(f"    {name}: {s} (port {info.get('port', '?')}, vram {info.get('vram', '?')})")
    else:
        print("    模型未启动（P0 实验阶段，需手动启动 llama.cpp server）")

    # ── 模型文件检查 ──
    # 动态遍历 config 中定义的所有模型，而非硬编码 key 列表
    print(f"\n  模型文件:")
    models_cfg = config.get("model_orchestration", {}).get("models", {})
    for model_key, model_cfg in models_cfg.items():
        gguf = model_cfg.get("gguf", "")
        if gguf and Path(gguf).exists():
            size_gb = Path(gguf).stat().st_size / 1e9
            print(f"    {OK} {model_key}: {Path(gguf).name} ({size_gb:.1f} GB)")
        elif gguf:
            print(f"    {INFO} {model_key}: {Path(gguf).name} (未下载)")
        else:
            print(f"    {INFO} {model_key}: 待配置")

    # ── 工具检查 ──
    print(f"\n  工具脚本:")
    scripts_dir = PROJECT_ROOT / "scripts"
    if scripts_dir.exists():
        for f in sorted(scripts_dir.glob("*.bat")):
            print(f"    {OK} {f.name}")
        readme = scripts_dir / "README.md"
        if readme.exists():
            print(f"    {OK} README.md")
    else:
        print(f"    {INFO} scripts/ 目录不存在（运行 python novel.py init 创建）")

    # ── 配置完整性 ──
    print(f"\n  配置检查:")
    checks = [
        ("config.yaml", CONFIG_PATH.exists()),
        ("AI_PROTOCOL.md", (PROJECT_ROOT / "AI_PROTOCOL.md").exists()),
    ]
    for name, ok in checks:
        print(f"    {OK if ok else FAIL} {name}")

    # ── P0 实验待办 ──
    print(f"\n  P0 实验待办 (DESIGN.md §12):")
    todos = [
        ("P0-0b","网文实际节奏曲线数据分析（5本番茄热门）"),
        ("P0-1", "WebNovel 专家模型评估（TanXS LoRA）"),
        ("P0-2", "DeepSeek-R1 逻辑警察角色重定位测试"),
        ("P0-4", "Q4_K_M vs IQ4_XS 文学质量 A/B 测试"),
        ("P0-5", "ReRanker 显存预算 + CPU fallback 验证"),
    ]
    for pid, desc in todos:
        print(f"    [ ] {pid}: {desc}")
    print("=" * 60)


# ============================================================================
# 占位命令 — P0 实验阶段未实现
# 每个占位函数标注了对应模块和实现依赖
# ============================================================================

def cmd_s1(args) -> None:
    """
    S1 创意引导 — 多温度变体生成剧情方向。

    温度策略: 0.3(保守) / 0.7(平衡) / 1.2(冒险)
    每个温度生成 1 个方向, 共 3 个可选方向。
    标注认知距离 (近/中/远), 鼓励作者选择最远的。
    """
    from xiaoshuo.agents.skill_loader import SkillLoader
    from xiaoshuo.agents.model_orchestrator import get_orchestrator

    chapter = args.chapter
    loader = SkillLoader()
    orch = get_orchestrator()

    prompt = loader.build("S1_creative", {
        "chapter_num": chapter,
        "outline_section": _load_outline(PROJECT_ROOT),
        "characters_section": _load_characters(PROJECT_ROOT),
    })

    temperatures = [
        (0.3, "保守方向 — 沿已有线索发展, 风险最小"),
        (0.7, "平衡方向 — 引入新元素, 保持连贯"),
        (1.2, "冒险方向 — 颠覆预期, 高风险高回报"),
    ]

    print("=" * 60)
    print(f"  S1 创意引导 — 第 {chapter} 章")
    print("=" * 60)
    print(f"  Prompt: {len(prompt)} 字符")
    print()

    for i, (temp, label) in enumerate(temperatures):
        dist = ["近", "中", "远"][i]
        prefix = f"[Direction {dist}]"

        msg = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"[Temperature: {temp}]\\n{label}\\n请不要生成具体文字,只描述叙事方向。"}
        ]

        print(f"{'=' * 60}")
        print(f"  {prefix} {label} (T={temp})")
        print(f"{'=' * 60}")

        result = orch.chat("S1_creative", msg, max_tokens=500, temperature=temp, timeout=120)
        if "error" in result:
            print(f"  [FAIL] {result['error']}")
        else:
            print(f"\n{result['content']}")
            print(f"\n  --- tokens: {result['usage'].get('completion_tokens', '?')} ---")
        print()

    print("  提示: 选择认知距离最远的方向可获得最大的创作自主权。")


def _load_outline(root: Path) -> str:
    """从 assets/outline/ 加载大纲（如果存在）。"""
    outline_path = root / "assets" / "outline" / "rough_outline.md"
    if outline_path.exists():
        text = outline_path.read_text(encoding="utf-8")
        if "待填写" not in text:
            return text
    return ""


def cmd_s3(args) -> None:
    """
    S3 虚拟评审团 — 逻辑警察评审 + 网文编辑 + 语言质检。

    流程:
      1. 加载章节文本
      2. 用 skill_loader 构建逻辑警察 System Prompt
      3. 通过 orchestrator 调用主模型
      4. 打印评审结果
    """
    from xiaoshuo.agents.skill_loader import SkillLoader
    from xiaoshuo.agents.model_orchestrator import get_orchestrator

    chapter = args.chapter

    # ── Step 1: 加载章节文本 ──
    chapter_path = PROJECT_ROOT / "chapters" / f"chapter_{chapter}.md"
    if not chapter_path.exists():
        print(f"[FAIL] 章节文件不存在: {chapter_path}")
        print("  请先将手写章节保存到 chapters/chapter_N.md")
        return

    chapter_text = chapter_path.read_text(encoding="utf-8")
    word_count = len(chapter_text.replace("\n", "").replace(" ", ""))  # 粗略中文字数
    # 长章节截断保护: System Prompt ~2000c, 留 2000c 给回复, 可用 ~2000 tokens
    max_chars = 3000
    if len(chapter_text) > max_chars:
        chapter_text = chapter_text[:max_chars] + "\n\n[... 章节过长, 仅分析前 3000 字符 ...]"
        print(f"  [注意] 章节过长, 已截断至 {max_chars} 字符")

    print("=" * 60)
    print(f"  S3 虚拟评审团 — 第 {chapter} 章")
    print("=" * 60)
    print(f"  章节字数: ~{word_count} 字")
    print()

    # ── Step 2: 构建 System Prompt ──
    loader = SkillLoader()
    prompt = loader.build("S3_logic_cop", {
        "chapter_num": chapter,
        "chapter_word_count": word_count,
        "characters_section": _load_characters(PROJECT_ROOT),
    })
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"请审查以下章节:\n\n{chapter_text}\n\n按 JSON 格式输出评审结果。"}
    ]

    # ── Step 3: 调用模型 ──
    orch = get_orchestrator()
    print("[LOGIC COP] 逻辑警察评审中...")
    result = orch.chat("S3_logic_cop", messages, max_tokens=2048, temperature=0.3, timeout=180)

    if "error" in result:
        print(f"\n[FAIL] 评审失败: {result['error']}")
        print("  确保 llama-server 已启动 (scripts\\start_model.bat)")
        return

    # ── Step 4: 打印结果 ──
    print(f"\n{'=' * 60}")
    print(f"  评审结果")
    print(f"{'=' * 60}")
    print(f"\n{result['content']}")
    print(f"\n--- 统计 ---")
    print(f"  prompt tokens: {result['usage'].get('prompt_tokens', '?')}")
    print(f"  completion tokens: {result['usage'].get('completion_tokens', '?')}")
    print(f"  model: {result['model']}")


def _load_characters(root: Path) -> str:
    """从 assets/canon/characters.md 加载角色设定（如果存在）。"""
    chars_path = root / "assets" / "canon" / "characters.md"
    if chars_path.exists():
        text = chars_path.read_text(encoding="utf-8")
        # 跳过模板提示语
        if "待填写" in text:
            return "(角色设定尚未填写)"
        return text
    return "(角色设定未找到)"


def cmd_worldbuild(args) -> None:
    """
    S0 世界观构建 — 5 阶段 Socratic 问答式交互引导。

    阶段: 时间背景 → 核心矛盾 → 场景设计 → 社会规则 → 特殊元素
    每阶段 AI 以 Socratic 方式逐个提问, 作者回答后追问深层问题。
    结果写入 canon/world.md 和 canon/rules.md。

    v7.5: 委托给 world_builder.run_world_build()。
    """
    from xiaoshuo.agents.model_orchestrator import get_orchestrator
    from xiaoshuo.agents.world_builder import run_world_build

    orch = get_orchestrator()
    world_content = run_world_build(orch)

    world_path = PROJECT_ROOT / "assets" / "canon" / "world.md"
    world_path.parent.mkdir(parents=True, exist_ok=True)
    world_path.write_text(world_content, encoding="utf-8")
    print(f"\n{'=' * 60}")
    print(f"  [OK] 世界观已保存到 assets/canon/world.md")
    print(f"{'=' * 60}")


def cmd_s4(args) -> None:
    """
    S4+++ 七层检测 — 基础版 (L1 PPL + L2 Burstiness)。
    完整七层需 s4_plus_plus.py + voice_baseline.py (5+ 章样本积累)。
    """
    from math import sqrt, log
    from collections import Counter

    target = args.file
    if not target:
        print("[S4+++] 用法: python novel.py s4 --file <章节路径>")
        return

    filepath = Path(target)
    if not filepath.exists():
        print(f"[FAIL] 文件不存在: {target}")
        return

    text = filepath.read_text(encoding='utf-8', errors='replace')
    if not text.strip():
        print("[FAIL] 文件为空")
        return

    # ── 读取检测阈值 (SSOT: config.yaml) ──
    try:
        cfg = yaml.safe_load(open(CONFIG_PATH, 'r', encoding='utf-8'))
        l1 = cfg.get("detection", {}).get("layers", {}).get("l1_ppl", {})
        l2 = cfg.get("detection", {}).get("layers", {}).get("l2_burstiness", {})
        ppl_safe = l1.get("safe_threshold", 50)
        ppl_warn = l1.get("warn_threshold", 40)
        burst_safe = l2.get("safe_threshold", 0.6)
    except Exception:
        ppl_safe, ppl_warn = 50, 40
        burst_safe = 0.6

    # ── L1: Perplexity (unigram model, 全文本) ──
    chars = [c for c in text if c.strip()]
    total = len(chars)
    if total < 10:
        print("[FAIL] 文本太短，无法计算 PPL")
        return
    freq = Counter(chars)
    entropy = -sum((f / total) * log(f / total, 2) for f in freq.values())
    ppl = 2 ** entropy

    # ── L2: Burstiness (句长变异系数) ──
    import re
    sentences = re.split(r'[。！？!?\n]+', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    if len(sentences) < 3:
        print("[FAIL] 句子太少，无法计算 Burstiness")
        return
    sent_lens = [len(s) for s in sentences]
    mean_len = sum(sent_lens) / len(sent_lens)
    if mean_len < 1:
        var = 0.0
    else:
        var = sqrt(sum((x - mean_len) ** 2 for x in sent_lens) / len(sent_lens))
    burstiness = var / mean_len if mean_len > 0 else 0.0

    # ── 判定 ──
    ppl_status = "人类风格" if ppl > ppl_safe else ("警告" if ppl > ppl_warn else "AI嫌疑")
    ppl_icon = "[OK]" if ppl > ppl_safe else ("[WARN]" if ppl > ppl_warn else "[FAIL]")
    burst_status = "人类风格" if burstiness > burst_safe else "AI嫌疑"
    burst_icon = "[OK]" if burstiness > burst_safe else "[FAIL]"

    print(f"\n{'=' * 60}")
    print(f"  S4+++ 基础检测: {filepath.name}")
    print(f"{'=' * 60}")
    print(f"  L1 PPL:        {ppl:.2f}  {ppl_icon} {ppl_status}")
    print(f"     (安全阈值: >{ppl_safe}, 警告阈值: <{ppl_warn})")
    print(f"  L2 Burstiness: {burstiness:.4f}  {burst_icon} {burst_status}")
    print(f"     (安全阈值: >{burst_safe}, 句数: {len(sentences)})")
    print(f"  L3-L7: 需完整 voice_baseline (5+ 章积累)")
    print(f"{'=' * 60}")

    # ── 综合判定 ──
    flags = 0
    if ppl <= ppl_safe:
        flags += 1
    if burstiness <= burst_safe:
        flags += 1
    if flags == 0:
        print("  [OK] 综合: 通过基础检测，无明显 AI 痕迹")
    elif flags == 1:
        print("  [WARN] 综合: 1 层异常，建议人工复查")
    else:
        print("  [FAIL] 综合: 2 层异常，高度疑似 AI 生成")


def cmd_deep(args) -> None:
    """二阶段深度拆书: Top-N (规则+LLM) + Bottom-N (仅规则)."""
    from xiaoshuo.tools.deep_diagnosis import run_deep
    run_deep(genre=args.genre, top_n=args.top, bottom_n=args.bottom)


def cmd_analyze(args) -> None:
    """一键全量分析管线: 入库→拆书→评分→关卡→指导."""
    import subprocess
    from pathlib import Path

    scripts = [sys.executable, str(Path(__file__).parent / "src" / "xiaoshuo" / "pipeline" / "analyze_all.py")]
    scripts += ["--genre", args.genre]
    if args.with_llm:
        scripts.append("--with-llm")

    if args.all:
        print("[ANALYZE] 全题材分析模式")
        genres = ["末世", "玄幻", "都市", "仙侠", "洪荒", "悬疑", "历史", "无限流"]
        for g in genres:
            cmd = [sys.executable, str(Path(__file__).parent / "src" / "xiaoshuo" / "pipeline" / "analyze_all.py"),
                   "--genre", g]
            if args.with_llm:
                cmd.append("--with-llm")
            print(f"\n{'='*60}")
            print(f"  [ANALYZE] 题材: {g}")
            print(f"{'='*60}")
            subprocess.run(cmd, cwd=str(Path(__file__).parent), timeout=7200)
        return

    subprocess.run(scripts, cwd=str(Path(__file__).parent), timeout=7200)


def cmd_intent(args) -> None:
    """意图→结构化建议翻译: 作者说"这章太拖了"→系统翻译为可执行建议."""
    from xiaoshuo.tools.intent_translator import translate

    text = args.text.strip()
    result = translate(text)
    print(f"\n[INTENT] \"{text}\"")
    if result.get("matched"):
        print(f"  匹配: {result['intent']} (维度: {result['dimension']}, 来源: {result.get('source','?')})")
    else:
        print(f"  [FALLBACK] 未精确匹配 -> 通用建议")
    print()
    for i, a in enumerate(result["actions"], 1):
        print(f"  {i}. {a}")


def cmd_test(args) -> None:
    """
    测试框架 — 运行所有模块自检 + 语法检查。
    """
    import subprocess

    python = sys.executable  # Current Python interpreter (avoids hardcoded path)
    modules = [
        "src/xiaoshuo/agents/model_orchestrator.py",
        "src/xiaoshuo/agents/skill_loader.py",
        "src/xiaoshuo/agents/state_machine.py",
        "src/xiaoshuo/agents/world_builder.py",
        "src/xiaoshuo/pipeline/book_processor.py",
        "src/xiaoshuo/pipeline/creative_bridge.py",
    ]

    print("=" * 60)
    print("  系统自检 — 运行所有模块")
    print("=" * 60)
    print()

    passed = 0
    failed = 0

    import os
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")

    for mod in modules:
        name = mod.split("\\")[-1].split("/")[-1]
        cmd = [python, mod]
        if "quality_gate" in name:
            cmd.append("--dry-run")
        print(f"[{name}] ... ", end="", flush=True)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
        if r.returncode == 0 or "DONE" in r.stdout or "DONE" in r.stderr or "RESULT" in r.stdout:
            print("[OK]")
            passed += 1
        elif r.returncode == 0:
            print("[OK] (no DONE marker)")
            passed += 1
        else:
            print(f"[FAIL]\n  {r.stderr[:200]}")
            failed += 1

    # 语法检查
    print(f"\n[novel.py] syntax ... ", end="")
    r = subprocess.run([python, "-m", "py_compile", "novel.py"], capture_output=True, text=True)
    if r.returncode == 0:
        print("[OK]")
        passed += 1
    else:
        print(f"[FAIL]")
        failed += 1

    # 新模块语法检查
    new_modules = [
        "src/xiaoshuo/agents/session_manager.py",
        "src/xiaoshuo/agents/character_designer.py",
        "src/xiaoshuo/agents/chapter_decisions.py",
    ]
    for mod in new_modules:
        name = mod.split("\\")[-1]
        print(f"[{name}] syntax ... ", end="")
        r = subprocess.run([python, "-m", "py_compile", mod], capture_output=True, text=True)
        if r.returncode == 0:
            print("[OK]")
            passed += 1
        else:
            print(f"[FAIL]")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"  结果: {passed} 通过 / {failed} 失败")
    print(f"{'=' * 60}")


# ============================================================================
# 命令: session -- 交互式写作会话 REPL
# ============================================================================

def cmd_session(args) -> None:
    """
    交互式写作会话 -- 将分散的模块串联为完整工作流。

    这是系统的"主入口"。作者在 REPL 中完成 S0->S4 全流程。
    每条命令对应一个已有模块, session 只是胶水层。
    """
    from xiaoshuo.agents.session_manager import SessionManager, STAGE_LABELS, STAGE_COMMANDS

    sm = SessionManager()

    # 启动参数
    book = getattr(args, "book", "") or ""
    genre = getattr(args, "genre", "") or ""
    chapter = getattr(args, "chapter", 0) or 0

    sm.start(book=book, genre=genre)
    if chapter:
        sm.set_chapter(chapter)

    # REPL 循环
    print("=" * 60)
    print("  Writing Session -- Interactive Mode")
    print("  Type 'help' for commands, 'quit' to exit")
    print("=" * 60)

    _print_session_status(sm)

    while True:
        cmds = sm.get_available_commands()
        hint = ", ".join(cmds)
        try:
            line = input(f"\n  session ({sm.current_stage})> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Session ended.")
            break

        if not line:
            continue

        parts = line.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd in ("quit", "exit", "q"):
            print("  Session ended.")
            break

        elif cmd == "help":
            _print_session_help(sm)

        elif cmd == "status":
            _print_session_status(sm)

        elif cmd == "worldbuild":
            _session_worldbuild(sm)

        elif cmd == "outline":
            _session_outline(sm)

        elif cmd == "characters":
            _session_characters(sm)

        elif cmd == "s1":
            _session_s1(sm)

        elif cmd == "write":
            _session_write(sm, arg)

        elif cmd == "review":
            _session_review(sm)

        elif cmd == "decisions":
            _session_decisions(sm)

        elif cmd == "next":
            sm.advance_stage("next")
            print(f"  [OK] Advanced to [{sm.current_stage}] {STAGE_LABELS.get(sm.current_stage, '')}")
            _print_session_status(sm)

        elif cmd == "rewrite":
            sm.advance_stage("rewrite")
            print(f"  [OK] Back to [S2d] Revision")
            _print_session_status(sm)

        elif cmd == "goto":
            if arg:
                sm.advance_stage(arg.upper())
                print(f"  [OK] Now at [{sm.current_stage}]")
                _print_session_status(sm)
            else:
                print("  Usage: goto S1  (valid: INIT/S0/S1/S2a/S2b/S2c/S2d/S3/S4/PUBLISH)")

        elif cmd == "chapter":
            try:
                ch = int(arg)
                sm.set_chapter(ch)
                print(f"  [OK] Switched to chapter {ch}")
                _print_session_status(sm)
            except ValueError:
                print("  Usage: chapter 5")

        else:
            print(f"  Unknown command: {cmd}. Type 'help' for commands.")


def _print_session_status(sm) -> None:
    """打印会话状态。"""
    for line in sm.get_status_lines():
        print(line)
    cmds = sm.get_available_commands()
    print(f"  Commands: {', '.join(cmds)}")


def _print_session_help(sm) -> None:
    """打印会话帮助。"""
    print()
    print("  === Session Commands ===")
    print("  status     -- Show current status")
    print("  worldbuild -- S0: World building (5 stages)")
    print("  outline    -- S0: Outline generation")
    print("  characters -- S0: Character design (4 dimensions)")
    print("  s1         -- S1: Creative guidance (multi-temperature)")
    print("  write      -- S2a: Submit chapter text (write or paste)")
    print("  review     -- S3: AI review panel")
    print("  decisions  -- Collect chapter decisions (style data)")
    print("  next       -- Advance to next stage")
    print("  rewrite    -- Go back to S2d (revision)")
    print("  goto STAGE -- Jump to specific stage")
    print("  chapter N  -- Switch to chapter N")
    print("  quit       -- End session")
    print()
    cmds = sm.get_available_commands()
    print(f"  Available now: {', '.join(cmds)}")


def _session_worldbuild(sm) -> None:
    """在会话中调用世界观构建。v7.5: 委托给 world_builder.run_world_build()。"""
    from xiaoshuo.agents.model_orchestrator import get_orchestrator
    from xiaoshuo.agents.world_builder import run_world_build

    orch = get_orchestrator()
    world_content = run_world_build(orch, session_manager=sm)

    world_path = PROJECT_ROOT / "assets" / "canon" / "world.md"
    world_path.parent.mkdir(parents=True, exist_ok=True)
    world_path.write_text(world_content, encoding="utf-8")
    print(f"\n  [OK] World saved to assets/canon/world.md")
    sm.advance_stage("S0")


def _session_outline(sm) -> None:
    """在会话中调用大纲生成。v7.5: 委托给 outline_builder.run_outline_build()。"""
    from xiaoshuo.agents.model_orchestrator import get_orchestrator
    from xiaoshuo.agents.outline_builder import run_outline_build

    orch = get_orchestrator()

    world = sm.chapter_context().get("world", "")
    genre = sm.chapter_context().get("genre", "末世")

    print("\n" + "=" * 60)
    print("  S0 Outline Generation")
    print("=" * 60)

    result = run_outline_build(orch, genre=genre, total_chapters=300)

    if result["rough_outline"]:
        outline_text = result["rough_outline"]
        print(f"\n{outline_text}")

        outline_path = PROJECT_ROOT / "assets" / "outline" / "rough_outline.md"
        outline_path.parent.mkdir(parents=True, exist_ok=True)
        outline_path.write_text(f"# Rough Outline\n\n{outline_text}", encoding="utf-8")
        print(f"\n  [OK] Outline saved to assets/outline/rough_outline.md")
    else:
        print(f"  [FAIL] Outline generation failed")


def _session_characters(sm) -> None:
    """在会话中调用角色设计。"""
    from xiaoshuo.agents.character_designer import run_character_design
    run_character_design()


def _session_s1(sm) -> None:
    """在会话中调用 S1 创意引导。"""
    from xiaoshuo.agents.skill_loader import SkillLoader
    from xiaoshuo.agents.model_orchestrator import get_orchestrator

    loader = SkillLoader()
    orch = get_orchestrator()
    chapter = sm.current_chapter
    ctx = sm.chapter_context()

    prompt = loader.build("S1_creative", {
        "chapter_num": chapter,
        "outline_section": ctx.get("outline", "")[:500],
        "characters_section": ctx.get("characters", "")[:500],
    })

    temperatures = [
        (0.3, "Conservative -- follow existing clues"),
        (0.7, "Balanced -- introduce new elements"),
        (1.2, "Adventurous -- subvert expectations"),
    ]

    print(f"\n{'=' * 60}")
    print(f"  S1 Creative Guidance -- Chapter {chapter}")
    print(f"{'=' * 60}")

    for i, (temp, label) in enumerate(temperatures):
        dist = ["Near", "Mid", "Far"][i]
        msgs = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"[Temperature: {temp}]\n{label}\nDescribe narrative direction only, no story text."}
        ]
        print(f"\n  [Direction {dist}] {label} (T={temp})")
        result = orch.chat("S1_creative", msgs, max_tokens=400, temperature=temp, timeout=120)
        if "error" in result:
            print(f"  [FAIL] {result['error']}")
        else:
            print(f"  {result['content']}")

    print("\n  Tip: The 'Far' direction gives the most creative freedom.")


def _run_prewrite_combined(sm, chapter: int) -> None:
    """v7.5: 整合 contract_chain 写前检查 + writing_instructions 指导。
    在 write 命令前自动调用，为作者提供统一的写前准备信息。
    """
    print(f"\n  [prewrite] 写前准备 — 合同链 + 写作指令")

    # ── 1. 合同链: 从 canon 生成运行时合同 ──
    try:
        from xiaoshuo.pipeline.contract_chain import ContractSeed, run_contract_chain
        canon_path = PROJECT_ROOT / "assets" / "canon"
        seed = ContractSeed(
            world_path=canon_path / "world.md",
            character_path=canon_path / "characters.md",
            timeline_path=canon_path / "timeline.md",
            emotional_path=canon_path / "emotional_arcs.md",
            subplot_path=canon_path / "subplot_board.md",
        )
        contracts = run_contract_chain(seed, chapter)
        if contracts:
            summary = contracts.get("pre_write_checklist", [])
            if summary:
                print(f"  [contract] {len(summary)} 条写前合同约束:")
                for item in summary[:5]:
                    print(f"    - {item}")
                if len(summary) > 5:
                    print(f"    ... 还有 {len(summary) - 5} 条")
    except Exception:
        pass  # contract_chain 不可用则静默跳过

    # ── 2. 写作指令: 从 rhythm 数据生成逐章指导 ──
    try:
        from xiaoshuo.pipeline.writing_instructions import generate_instructions
        cfg = yaml.safe_load(open(CONFIG_PATH, 'r', encoding='utf-8'))
        project = cfg.get("writing_instructions", {}).get("project", "末日模拟器")
        instructions = generate_instructions(project, chapter)
        if instructions:
            print(f"  [instructions] 第 {chapter} 章写作指令:")
            for key, val in list(instructions.items())[:5]:
                print(f"    {key}: {val}")
    except Exception:
        pass  # writing_instructions 不可用则静默跳过

    print(f"  [prewrite] 写前准备完成\n")


def _session_write(sm, file_arg: str = "") -> None:
    """在会话中提交章节文本。"""
    chapter = sm.current_chapter

    # ── v7.5: 写前准备 — 合同链 + 写作指令整合 ──
    _run_prewrite_combined(sm, chapter)

    # 如果提供了文件路径, 直接读取
    if file_arg:
        fpath = Path(file_arg)
        if not fpath.is_absolute():
            fpath = PROJECT_ROOT / fpath
        if fpath.exists():
            text = fpath.read_text(encoding="utf-8")
            path = sm.submit_chapter(chapter, text)
            wc = len(text.replace("\n", "").replace(" ", ""))
            print(f"  [OK] Chapter {chapter} loaded from {fpath.name} ({wc} chars)")
            print(f"  Saved to: {path}")
            return
        else:
            print(f"  [FAIL] File not found: {fpath}")
            return

    # 否则交互式输入
    print(f"\n{'=' * 60}")
    print(f"  Write Chapter {chapter}")
    print(f"  Type your chapter text. End with a line containing only 'END'")
    print(f"  Or type 'file path/to/file.md' to load from file")
    print(f"{'=' * 60}")

    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "END":
            break
        if line.strip().startswith("file "):
            fpath = Path(line.strip()[5:])
            if not fpath.is_absolute():
                fpath = PROJECT_ROOT / fpath
            if fpath.exists():
                text = fpath.read_text(encoding="utf-8")
                lines.append(text)
                print(f"  [OK] Loaded {len(text)} chars from {fpath}")
                break
            else:
                print(f"  [FAIL] File not found: {fpath}")
                continue
        lines.append(line)

    text = "\n".join(lines)
    if not text.strip():
        print("  No text entered.")
        return

    path = sm.submit_chapter(chapter, text)
    wc = len(text.replace("\n", "").replace(" ", ""))
    print(f"\n  [OK] Chapter {chapter} saved ({wc} chars)")
    print(f"  Path: {path}")


def _session_review(sm) -> None:
    """在会话中调用 AI 评审。"""
    from xiaoshuo.agents.skill_loader import SkillLoader
    from xiaoshuo.agents.model_orchestrator import get_orchestrator

    chapter = sm.current_chapter
    ctx = sm.chapter_context()
    text = ctx.get("chapter_text", "")

    if not text:
        print(f"  [FAIL] No text for chapter {chapter}.")
        print(f"  Use 'write' command first to submit chapter text.")
        return

    wc = len(text.replace("\n", "").replace(" ", ""))
    max_chars = 3000
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n[... truncated to 3000 chars ...]"

    loader = SkillLoader()
    orch = get_orchestrator()

    prompt = loader.build("S3_logic_cop", {
        "chapter_num": chapter,
        "chapter_word_count": wc,
        "characters_section": ctx.get("characters", "")[:500],
    })

    print(f"\n{'=' * 60}")
    print(f"  S3 AI Review -- Chapter {chapter} ({wc} chars)")
    print(f"{'=' * 60}")

    msgs = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"Please review:\n\n{text}\n\nOutput in JSON format."}
    ]

    print("  AI: Reviewing...")
    result = orch.chat("S3_logic_cop", msgs, max_tokens=2048, temperature=0.3, timeout=180)
    if "error" in result:
        print(f"  [FAIL] {result['error']}")
        print("  Make sure llama-server is running (scripts\\start_model.bat)")
        return

    print(f"\n{result['content']}")
    print(f"\n  tokens: prompt={result['usage'].get('prompt_tokens', '?')}, "
          f"completion={result['usage'].get('completion_tokens', '?')}")

    # 保存评审报告
    report_dir = PROJECT_ROOT / "review" / "jury_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"review_ch{chapter}.md"
    report_path.write_text(
        f"# Review: Chapter {chapter}\n\n"
        f"Words: {wc}\n\n"
        f"{result['content']}\n",
        encoding="utf-8"
    )
    print(f"  [OK] Report saved to review/jury_reports/review_ch{chapter}.md")

    # 更新 review_count
    history = sm._state["session"].get("chapter_history", {})
    key = str(chapter)
    if key in history:
        history[key]["review_count"] = history[key].get("review_count", 0) + 1
        sm._save()


def _session_decisions(sm) -> None:
    """在会话中采集章节决策。"""
    from xiaoshuo.agents.chapter_decisions import collect_decisions
    collect_decisions(sm.current_chapter)


# ============================================================================
# 命令: write -- 提交章节文本 (独立命令, 不需要进入 session)
# ============================================================================

def cmd_write(args) -> None:
    """
    提交章节文本并自动评估。
    用法: python novel.py write --chapter 5 --file my_chapter.md [--genre 末世] [--no-eval]
    """
    from xiaoshuo.agents.session_manager import SessionManager

    sm = SessionManager()
    chapter = args.chapter
    sm.set_chapter(chapter)

    # Load chapter text
    file_path = getattr(args, "file", "") or ""
    text = ""
    if file_path:
        fpath = Path(file_path)
        if not fpath.is_absolute():
            fpath = PROJECT_ROOT / fpath
        if fpath.exists():
            text = fpath.read_text(encoding="utf-8")
        else:
            print(f"[FAIL] File not found: {fpath}")
            return
    else:
        print(f"Enter chapter {chapter} text. End with 'END' on its own line:")
        lines = []
        while True:
            try:
                line = input()
            except EOFError:
                break
            if line.strip() == "END":
                break
            lines.append(line)
        text = "\n".join(lines)
        if not text.strip():
            print("No text entered.")
            return

    # Save to session
    path = sm.submit_chapter(chapter, text)
    wc = len(text.replace("\n", "").replace(" ", ""))
    print(f"[OK] Chapter {chapter} saved ({wc} chars): {path}")

    # Auto-evaluate (unless --no-eval)
    skip_eval = getattr(args, "no_eval", False)
    if skip_eval:
        return

    genre = getattr(args, "genre", "") or "末世"

    # Report output path
    eval_dir = PROJECT_ROOT / "data" / "reports" / genre / "evaluations"
    eval_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"ch{chapter:03d}_evaluation"
    ev_path = eval_dir / safe_name

    try:
        from xiaoshuo.pipeline.comparison_engine import evaluate_author_chapter, generate_evaluation_report
        result = evaluate_author_chapter(text, genre=genre, chapter_num=chapter, with_llm=False)
        generate_evaluation_report(result, ev_path)
        print(f"[OK] Evaluation report: {ev_path}.md")
    except Exception as e:
        print(f"[FAIL] Evaluation error: {e}")


# ============================================================================
# 命令: decisions -- 章节决策采集 (独立命令)
# ============================================================================

def cmd_decisions(args) -> None:
    """
    采集章节决策数据 -- 风格涌现的原始数据源。
    用法: python novel.py decisions --chapter 5
    """
    from xiaoshuo.agents.chapter_decisions import collect_decisions, get_style_summary

    chapter = args.chapter
    collect_decisions(chapter)

    # 显示风格积累进度
    summary = get_style_summary()
    total = summary.get("total_chapters", 0)
    status = summary.get("status", "unknown")
    print(f"\n  Style data: {total} chapters collected ({status})")
    if total >= 10:
        print(f"  Skip rate: {summary.get('skip_rate', 0):.0%}")
        cats = summary.get("top_categories", [])
        if cats:
            print(f"  Top categories: {', '.join(c['category'] for c in cats[:3])}")


# ============================================================================
# 命令: characters -- 角色设计 (独立命令)
# ============================================================================

def cmd_characters(args) -> None:
    """
    S0 角色设计 -- 4维度 Socratic 引导。
    用法: python novel.py characters
    """
    from xiaoshuo.agents.character_designer import run_character_design
    run_character_design()


# ============================================================================
# 命令: outline -- 大纲生成 (独立命令)
# ============================================================================

def cmd_outline(args) -> None:
    """
    S0 大纲生成 -- 基于世界观生成三层大纲。
    用法: python novel.py outline

    v7.5: 委托给 outline_builder.run_outline_build()。
    """
    from xiaoshuo.agents.model_orchestrator import get_orchestrator
    from xiaoshuo.agents.outline_builder import run_outline_build

    orch = get_orchestrator()

    # 加载世界观
    world_path = PROJECT_ROOT / "assets" / "canon" / "world.md"
    world = ""
    if world_path.exists():
        world = world_path.read_text(encoding="utf-8")

    print("=" * 60)
    print("  S0 Outline Generation")
    print("=" * 60)

    result = run_outline_build(orch, genre="末世", total_chapters=300)

    if result["rough_outline"]:
        print(f"\n{result['rough_outline']}")

        outline_path = PROJECT_ROOT / "assets" / "outline" / "rough_outline.md"
        outline_path.parent.mkdir(parents=True, exist_ok=True)
        outline_path.write_text(f"# Rough Outline\n\n{result['rough_outline']}", encoding="utf-8")
        print(f"\n  [OK] Saved to assets/outline/rough_outline.md")
    else:
        print(f"\n  [FAIL] Outline generation failed")


# ============================================================================
# cmd_compare — 结构层对比引擎
# ============================================================================

def cmd_compare(args) -> None:
    """对比新人作者的结构层(世界观/大纲/角色)与精品基准。"""
    from xiaoshuo.tools.structure_comparator import (
        _load_guidance_json, _load_rhythm_pool,
        compare_worldbuilding, compare_outline, compare_characters,
        generate_report,
    )

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"[FAIL] 文件不存在: {file_path}")
        return
    # Guard: reject oversized inputs (SSOT from config.yaml)
    import yaml
    cfg_path = PROJECT_ROOT / "config.yaml"
    max_input = 5 * 1024 * 1024
    if cfg_path.exists():
        try:
            with open(cfg_path, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f)
            max_input = cfg.get("structure_comparator", {}).get("max_input_bytes", max_input)
        except (yaml.YAMLError, IOError):
            pass
    if file_path.stat().st_size > max_input:
        print(f"[FAIL] 文件过大({file_path.stat().st_size}字节 > {max_input}), 请拆分为多个文件提交")
        return
    try:
        text = file_path.read_text(encoding='utf-8')
    except UnicodeDecodeError as e:
        print(f"[FAIL] 文件编码错误(需UTF-8): {file_path} — {e}")
        return
    genre = args.genre
    guidance = _load_guidance_json(genre)
    rhythm_pool = _load_rhythm_pool(genre)

    if not guidance:
        print(f"[WARN] 未找到{genre}类创作指导JSON, 部分对比将降级")
    if not rhythm_pool:
        print(f"[WARN] 未找到{genre}类rhythm数据, 部分对比将降级")

    modes_to_run = ["worldbuild", "outline", "characters"] if args.mode == "all" else [args.mode]

    all_results = []
    for mode in modes_to_run:
        if mode == "worldbuild":
            all_results.extend(compare_worldbuilding(text, guidance, rhythm_pool))
        elif mode == "outline":
            all_results.extend(compare_outline(text, guidance, rhythm_pool))
        elif mode == "characters":
            all_results.extend(compare_characters(text, guidance, rhythm_pool))

    report = generate_report(args.mode, all_results, genre)
    if not report:
        print("[FAIL] 无可输出的对比结果")
        return

    # Output
    out_dir = PROJECT_ROOT / "data" / "reports" / genre / "structure_eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_prefix = f"{genre}_结构对比_{args.mode}"
    # Sanitize: strip path separators (same as structure_comparator.main())
    safe_prefix = Path(out_prefix).name or out_prefix.replace("/", "_").replace("\\", "_")

    json_path = out_dir / f"{safe_prefix}.json"
    md_path = out_dir / f"{safe_prefix}.md"
    json_path.write_text(json.dumps(report["json"], ensure_ascii=False, indent=2), encoding='utf-8')
    md_path.write_text(report["md"], encoding='utf-8')
    print(f"[OK] JSON: {json_path}")
    print(f"[OK] MD: {md_path}")

    print(f"\n{'='*50}")
    print(f"  {genre}类 {args.mode} 对比评估")
    print(f"  总分: {report['json']['avg_score']}/100")
    print(f"  严重差距: {report['json']['large_gaps']} | 中等差距: {report['json']['medium_gaps']}")
    print(f"  {report['json']['verdict']}")
    print(f"{'='*50}")


# ============================================================================
# 命令: memory — 行为回溯备忘录
# ============================================================================

def cmd_memory(args) -> None:
    """结构化行为回溯备忘录: 添加/检索/导出经验卡片。"""
    from xiaoshuo.agents.memory_store import MemoryStore

    store = MemoryStore()

    if args.memory_cmd == "add":
        tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
        cid = store.add(
            goal=args.goal,
            solution=args.solution,
            result=args.result,
            pain_point=args.pain_point,
            tags=tags,
            source=args.source,
        )
        print(f"[OK] 记忆卡片 #{cid} 已添加")
        print(f"  Goal: {args.goal[:60]}")
        print(f"  Tags: {tags}")

    elif args.memory_cmd == "query":
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        cards = store.query_by_tags(tags, match_all=args.match_all, limit=args.limit)
        if not cards:
            print("[INFO] 未找到匹配的记忆卡片")
            return
        print(f"[OK] 找到 {len(cards)} 张卡片:")
        for c in cards:
            print(f"  #{c['id']} | {c['date'][:10]} | {c['goal'][:50]}")
            print(f"         Tags: {', '.join(c['tags'])}")
            pain = c['pain_point'][:60] if c['pain_point'] else "(无)"
            print(f"         Pain: {pain}")
            print()

    elif args.memory_cmd == "search":
        cards = store.search_text(args.keyword, limit=args.limit)
        if not cards:
            print("[INFO] 未找到匹配内容")
            return
        print(f"[OK] 找到 {len(cards)} 张卡片:")
        for c in cards:
            print(f"  #{c['id']} | {c['date'][:10]} | {c['goal'][:50]}")
            if c['pain_point']:
                hit = c['pain_point'][:80]
                print(f"         Pain: {hit}")
            print()

    elif args.memory_cmd == "list":
        cards = store.list_recent(limit=15)
        if not cards:
            print("[INFO] 记忆库为空")
            return
        print(f"[OK] 最近 {len(cards)} 张记忆卡片:")
        print(f"  {'ID':>4} | {'日期':<12} | {'来源':<12} | {'目标'}")
        print(f"  {'-'*4}-+-{'-'*12}-+-{'-'*12}-+-{'-'*40}")
        for c in cards:
            goal_short = c['goal'][:38]
            print(f"  {c['id']:>4} | {c['date'][:10]} | {c['source']:<12} | {goal_short}")

    elif args.memory_cmd == "export":
        paths = store.export_markdown()
        print(f"[OK] 导出 {len(paths)} 张卡片:")
        for p in paths:
            print(f"  {p}")
        print(f"\n  目录: {paths[0].parent}" if paths else "")

    elif args.memory_cmd == "count":
        total = store.count()
        print(f"[OK] 记忆库总计 {total} 张卡片")
        # 按来源统计
        for src in ["manual", "s4_pass", "s4_fail", "pipeline"]:
            n = store.count_by_source(src)
            if n > 0:
                print(f"  - {src}: {n}")

    else:
        print("[FAIL] 未知子命令. 可用: add / query / search / list / export / count")


# ============================================================================
# CLI 入口 — argparse 路由
# ============================================================================

def main() -> None:
    """
    解析命令行参数，路由到对应命令函数。

    ── 扩展方式 ──
    添加新命令（以 'beat' 为例）:
      1. sub.add_parser("beat")  ← 在此函数中注册
      2. def cmd_beat(args):     ← 实现命令逻辑
      3. "beat": cmd_beat        ← 在 commands dict 中注册

    ── 参数约定 ──
    所有命令的第一个位置参数通常是 --chapter（章节号）。
    温度/变体数等采样参数通过 --variants 控制。
    """
    parser = argparse.ArgumentParser(
        prog="novel",
        description="番茄小说 AI 辅助创作系统 v7.1 — CLI 入口",
        epilog="完整文档: DESIGN.md"
    )

    # 子命令注册 — 每个子命令对应一个 cmd_*() 函数
    sub = parser.add_subparsers(dest="command", help="可用命令")

    # init — 项目初始化
    sub.add_parser("init", help="初始化项目目录结构和状态文件")

    # status — 系统状态
    sub.add_parser("status", help="查看系统状态（进度/模型/配置/待办）")

    # s1 — 创意引导
    p_s1 = sub.add_parser("s1", help="S1 创意引导：生成多温度变体的剧情方向",
        epilog="Example: python novel.py s1 --chapter 5 --variants 3")
    p_s1.add_argument("--chapter", type=int, default=1,
                      help="目标章节号（默认 1）")
    p_s1.add_argument("--variants", type=int, default=3,
                      help="温度变体数 [0.3, 0.7, 1.2] 各取前 N 个（默认 3）")

    # s3 — 逻辑评审
    p_s3 = sub.add_parser("s3", help="S3 虚拟评审团：异步流水线逻辑校验",
        epilog="Example: python novel.py s3 --chapter 5")
    p_s3.add_argument("--chapter", type=int, required=True,
                      help="目标章节号（必填）")

    # s4 — 风格检测
    p_s4 = sub.add_parser("s4", help="S4+++ 七层AI风格检测",
        epilog="Example: python novel.py s4 --chapter 5")
    p_s4.add_argument("--chapter", type=int, required=True,
                      help="目标章节号（必填）")

    # analyze — 分析管线
    p_analyze = sub.add_parser("analyze", help="一键全量分析: 入库→拆书→评分→关卡→指导",
        epilog="Example: python novel.py analyze --genre 末世\n"
               "         python novel.py analyze --genre 末世 --with-llm\n"
               "         python novel.py analyze --all")
    p_analyze.add_argument("--genre", type=str, default="末世",
                           help="目标题材（默认 末世）")
    p_analyze.add_argument("--with-llm", action="store_true",
                           help="启用 LLM 增强分析（需模型运行）")
    p_analyze.add_argument("--all", action="store_true",
                           help="分析所有已入库题材")

    # worldbuild — 世界观构建
    sub.add_parser("worldbuild", help="S0 世界观构建：5阶段Socratic问答式引导",
        epilog="Example: python novel.py worldbuild")

    # intent — 意图翻译
    p_intent = sub.add_parser("intent", help="意图→结构化建议: 将创作意图翻译为可执行建议",
        epilog='Example: python novel.py intent --text "这章太拖了"')
    p_intent.add_argument("--text", type=str, required=True,
                          help="创作意图描述（如'节奏拖''高潮不够爽'）")

    # deep — 三层深度拆书
    p_deep = sub.add_parser("deep", help="二阶段深度拆书: Top-N全章规则+LLM + Bottom-N规则诊断",
        epilog="Example: python novel.py deep --genre 末世\n"
               "         python novel.py deep --genre 末世 --top 3 --bottom 3")
    p_deep.add_argument("--genre", type=str, default="末世",
                        help="目标题材（默认 末世）")
    p_deep.add_argument("--top", type=int, default=3,
                        help="Top-N 精品书全章分析 (默认3)")
    p_deep.add_argument("--bottom", type=int, default=3,
                        help="Bottom-N 书规则诊断 (默认3)")

    # test — 测试
    sub.add_parser("test", help="运行回归测试 & 黄金测试集")

    # session — 交互式写作会话
    p_session = sub.add_parser("session", help="交互式写作会话: S0->S4 完整工作流 REPL",
        epilog="Example: python novel.py session\n"
               "         python novel.py session --book 末日模拟器 --genre 末世")
    p_session.add_argument("--book", type=str, default="",
                           help="作品名称 (如 '末日模拟器')")
    p_session.add_argument("--genre", type=str, default="",
                           help="题材 (如 '末世'/'玄幻')")
    p_session.add_argument("--chapter", type=int, default=0,
                           help="起始章节号 (默认 1)")

    # write — 提交章节文本
    p_write = sub.add_parser("write", help="提交章节正文: 从文件加载或交互输入",
        epilog="Example: python novel.py write --chapter 5 --file my_chapter.md")
    p_write.add_argument("--chapter", type=int, required=True,
                         help="章节号 (必填)")
    p_write.add_argument("--file", type=str, default="",
                         help="章节文件路径 (.md/.txt)")

    # decisions — 章节决策采集
    p_decisions = sub.add_parser("decisions", help="章节决策采集: 风格涌现的数据源",
        epilog="Example: python novel.py decisions --chapter 5")
    p_decisions.add_argument("--chapter", type=int, required=True,
                             help="章节号 (必填)")

    # characters — 角色设计
    sub.add_parser("characters", help="S0 角色设计: 4维度 Socratic 引导")

    # outline — 大纲生成
    sub.add_parser("outline", help="S0 大纲生成: 基于世界观生成三层大纲")

    # memory — 行为回溯备忘录
    p_memory = sub.add_parser("memory", help="Agent记忆系统: 结构化行为回溯备忘录 (SQLite)",
        epilog="Example: python novel.py memory add --goal \"拆书\" ...\n"
               "         python novel.py memory query --tags 拆书,爽点\n"
               "         python novel.py memory list\n"
               "         python novel.py memory export")
    p_memory_sub = p_memory.add_subparsers(dest="memory_cmd", help="记忆子命令")

    # memory add
    p_mem_add = p_memory_sub.add_parser("add", help="添加记忆卡片")
    p_mem_add.add_argument("--goal", type=str, required=True, help="任务目标")
    p_mem_add.add_argument("--solution", type=str, default="", help="解决方案")
    p_mem_add.add_argument("--result", type=str, default="", help="执行结果")
    p_mem_add.add_argument("--pain-point", type=str, default="", help="遇到的困难")
    p_mem_add.add_argument("--tags", type=str, default="", help="逗号分隔的标签")
    p_mem_add.add_argument("--source", type=str, default="manual", help="来源标识")

    # memory query
    p_mem_q = p_memory_sub.add_parser("query", help="按标签检索记忆卡片")
    p_mem_q.add_argument("--tags", type=str, required=True, help="逗号分隔的标签")
    p_mem_q.add_argument("--match-all", action="store_true", help="必须匹配所有标签")
    p_mem_q.add_argument("--limit", type=int, default=10, help="最大返回条数")

    # memory search
    p_mem_s = p_memory_sub.add_parser("search", help="全文搜索记忆卡片")
    p_mem_s.add_argument("--keyword", type=str, required=True, help="搜索关键词")
    p_mem_s.add_argument("--limit", type=int, default=10, help="最大返回条数")

    # memory list
    p_memory_sub.add_parser("list", help="列出最近记忆卡片")

    # memory export
    p_memory_sub.add_parser("export", help="导出所有卡片为 Markdown (Obsidian 友好)")

    # memory count
    p_memory_sub.add_parser("count", help="统计记忆卡片总数")

    # compare — 结构层对比
    p_compare = sub.add_parser("compare", help="结构层对比: 新人世界观/大纲/角色 vs 精品基准",
        epilog="Example: python novel.py compare --file my_world.md --mode worldbuild\n"
               "         python novel.py compare --file my_outline.md --mode outline\n"
               "         python novel.py compare --file my_all.md --mode all")
    p_compare.add_argument("--file", type=str, required=True,
                           help="作者内容文件路径 (.md/.txt)")
    p_compare.add_argument("--mode", type=str, default="all",
                           choices=["worldbuild", "outline", "characters", "all"],
                           help="对比模式 (default: all)")
    p_compare.add_argument("--genre", type=str, default="末世",
                           help="题材基准 (default: 末世)")

    # ── 解析 & 路由 ──
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    # 命令 → 函数 映射表
    # 新增命令时同步更新此表
    commands = {
        "init":       cmd_init,
        "status":     cmd_status,
        "worldbuild": cmd_worldbuild,
        "analyze":    cmd_analyze,
        "intent":     cmd_intent,
        "s1":         cmd_s1,
        "s3":         cmd_s3,
        "s4":         cmd_s4,
        "deep":       cmd_deep,
        "test":       cmd_test,
        "session":    cmd_session,
        "write":      cmd_write,
        "decisions":  cmd_decisions,
        "characters": cmd_characters,
        "outline":    cmd_outline,
        "memory":     cmd_memory,
        "compare":    cmd_compare,
    }

    # 执行目标命令
    commands[args.command](args)


if __name__ == "__main__":
    main()
