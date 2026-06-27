"""
outline_builder.py — S0b 大纲生成引导 v3
============================================================
─ 设计蓝本 ─
· 网文俱乐部三层大纲法: 总纲(5段式)→卷纲→章纲
· 马良写作 5 种模板 + 4类钩子(悬念/反转/情绪/信息)
· 番茄编辑 末世文公式: 囤物资→收队友→扩张→升级
· 马良节奏标准: 小爽点每章≥1, 中爽点3-5章1个, 情绪高峰≤2章间隔

─ v3 新增 ─
· 从 creative_guidance JSON 加载进度百分位基准
· inject_rhythm_targets(): 章纲注入量化节奏目标
· generate_rhythm_plan(): 全书节奏分布曲线

─ 代笔边界 ─
· AI 可生成: 总纲框架 + 卷纲事件拆分 + 章纲爽点分布 + 模板推荐
· AI 禁止: 替作者决定故事走向、选定唯一方案、写正文

─ 输出 ─
outline/ 目录: summary.md(总纲) + volume_*.md(卷纲) + chapters.csv(章纲映射)
"""

import json
import yaml
from enum import Enum
from pathlib import Path
from xiaoshuo import PROJECT_ROOT
from typing import Optional
from xiaoshuo.infra.logging_config import get_logger
from xiaoshuo.infra.config_manager import get_config

_logger = get_logger("outline_builder")


# ============================================================
# 大纲层级定义 (网文俱乐部标准)
# ============================================================
class OutlineLevel(Enum):
    ROUGH = "rough"     # 粗纲: 全书5段式框架
    VOLUME = "volume"   # 卷纲: 每卷目标+关键情节
    CHAPTER = "chapter" # 章纲: 每章内容+爽点+钩子

# ============================================================
# 5 种模板 (马良写作)
# ============================================================
TEMPLATES = {
    "三幕式": {
        "适合": "短篇/中篇/有明确起承转合的长篇",
        "结构": [
            ("第一幕(25%)", "建置: 角色+世界, 触发事件打破日常"),
            ("第二幕(50%)", "对抗: 上升冲突, 中间大转折, 最低谷"),
            ("第三幕(25%)", "解决: 用成长后的自己解决最终危机"),
        ],
    },
    "升级打怪": {
        "适合": "玄幻/修仙/系统文 — 网文最常用",
        "循环": "新地图→低调装逼→结仇→修炼突破→打脸→奖励→更大舞台",
        "每卷框架": ["出生地图(练气)", "宗门争斗(筑基)", "外出历练(金丹)", "世界舞台(元婴)", "飞升(化神)"],
    },
    "悬疑推理": {
        "适合": "悬疑/推理/惊悚",
        "方法": "从结局倒推: 真相→拆线索→安排红鲱鱼→顺叙呈现",
    },
    "群像叙事": {
        "适合": "权谋/宫斗/多势力对抗",
        "方法": "多线并行+交汇点: 给每条主线画时间轴, 标出交汇章节",
    },
    "无限流": {
        "适合": "无限流/副本文/规则怪谈",
        "结构": "主线(残酷真相) + 副本1(生存) + 幕间 + 副本2(推理) + ...",
    },
}

# ============================================================
# 总纲 System Prompt
# ============================================================
ROUGH_OUTLINE_SYSP = """
## 你的角色
你是网文大纲规划师。基于作者提供的世界观设定, 生成全书的总纲框架。

## 番茄平台标准
- 每章 2000 字（流量密码）
- 黄金三章必须让读者翻到第二章（完读率 ≥60%）
- 末世文主线: 生存 → 提升实力 → 终结末世

## 输出结构 (5段式, 网文俱乐部标准)
1. **开篇设计 (0-10万字)**: 建立世界+引入主角+核心冲突启动
2. **前期发展 (10-30万字)**: 深入世界+势力展开+主角第一次重大突破
3. **中期发展 (30-80万字)**: 换地图/扩大舞台+中期反派+主角中期转折
4. **后期发展 (80-150万字)**: 终极秘密揭露+最终对手出现+高潮准备
5. **结局 (150-200万字)**: 最终决战+各角色结局+收官
(字数可按实际调整)

## 爽点动机链 (必须标注)
每个阶段需标注主角的动机驱动链——爽点不能是无根之木:
- **欲望**: 主角在这一阶段想要什么? (生存/复仇/保护/变强/真相)
- **阻碍**: 什么在阻止他? (敌人/环境/规则/自身缺陷)
- **行动**: 他做了什么来克服阻碍? (策略/升级/结盟/牺牲)
- **爽点**: 行动的结果如何释放爽感? (碾压/反转/收获/揭示)

## 生成规则
- 每个阶段列出 3-5 个关键事件
- 每个关键事件标注: 对应的爽点类型 + 预估章数范围 + 动机链(欲望→阻碍→行动→爽点)
- 给出 2 个不同的总纲方向(不同核心冲突), 供作者选择
- 禁止在总纲中写正文段落
"""

# ============================================================
# 卷纲 System Prompt
# ============================================================
VOLUME_OUTLINE_SYSP = """
## 你的角色
你是网文卷纲规划师。基于总纲, 将每一卷拆分为具体的事件链。

## 输出结构
- 卷标题 + 字数范围
- 关键情节(按顺序, 3-7个)
- 卷目标(主角在这一卷结束时达到什么状态)
- 卷高潮(这一卷最大的爽点/反转)
- 卷末钩子(让读者必须看下一卷的理由)

## 爽点动机链 (每卷必须标注)
- **欲望**: 主角在这一卷想要什么?
- **阻碍**: 什么在阻止他?
- **行动**: 他做了什么来克服?
- **爽点**: 卷末高潮如何释放?

## 生成规则
- 每卷 20-50 章, 约 6-15 万字
- 关键情节之间要有因果链, 不能是孤立事件
- 爽点分布: 每 2-3 章至少 1 个小爽点, 每卷至少 1 个大高潮
"""

# ============================================================
# 章纲 System Prompt (细纲)
# ============================================================
CHAPTER_OUTLINE_SYSP = """
## 你的角色
你是网文章纲规划师。基于卷纲, 生成逐章的事件映射。

## 马良节奏标准 (必须遵守)
- **小爽点**: 每章 ≥1 个（嘴角微扬: 金句/路人震惊/小反转/新技能解锁）
- **中爽点**: 每 3-5 章 1 个（完整打脸/实力跃升/谜题揭晓）
- **大爽点**: 每卷高潮 1 个（Boss 战逆转/身份爆炸/多伏笔回收）
- **情绪高峰间隔**: ≤2 章（顶级作品平均 1.8 章/次）
- **平路(铺垫/日常)**: 连续不超过 3 章
- **钩子**: 每章结尾必有（悬念/反转/情绪炸弹/信息投放 四选一）

## 番茄末世文公式
- 前 5 万字: 囤物资 + 收服队友
- 爽点四路叠加: 人设杀伐 + 金手指显威 + 囤积收获 + 实力碾压
- 需求式推进: 完成目标→立刻抛出新需求

## 章节模板: 起承转爽
- 起(500字): 回顾上章 + 引出本章冲突
- 承(800字): 冲突升级、压力增大
- 转(300字): 转折出现
- 爽(400字): 主角反击/揭晓/收获 + 钩子结尾

## 输出格式 (CSV 兼容)
每行: 章号 | 事件标题 | 爽点类型 | 冲突级别 | 动机链 | 章末钩子类型 | 涉及角色

动机链格式: 欲望→阻碍→行动→爽点 (每章用一句话概括, 如"求生存→侵蚀源威胁→清源战斗→异能突破")

## 生成规则
- 每章只写 1-2 句话概括事件, 不写正文
- 爽点类型: 打脸/突破/碾压/绝地反击/扮猪吃虎/资源获取/身份揭示
- 钩子类型: 悬念/反转/情绪/信息
- 连续 3 章以上无爽点 → 输出警告
- 连续 3 章以上动机链断裂(欲望缺失或阻碍不明确) → 输出警告
- 章节长度: 日常章 2000 字, 高潮章 2500-3500 字
"""

# ============================================================
# 模板推荐规则
# ============================================================
TEMPLATE_RECOMMEND = {
    "历史穿越": "三幕式",
    "同人": "升级打怪",
    "洪荒流": "升级打怪",
    "无敌文": "三幕式",
    "仙侠": "升级打怪",
    "玄幻": "升级打怪",
    "都市": "三幕式",
    "末世": "三幕式",
    "科幻": "三幕式",
    "科幻末世": "三幕式",      # 生存 → 实力提升 → 终结末世
    "末世模拟器": "三幕式",    # 预知→布局→反入侵
}
"""根据题材推荐大纲模板。用户可覆盖。"""

# ============================================================
# 末世+模拟器专属大纲骨架 (番茄编辑公式)
# ============================================================
APOCALYPSE_SIMULATOR_SKELETON = {
    "主线": "生存 → 清源扩展安全区 → 拉拢妖盟 → 反攻杀戮世界",
    "前5万字任务": [
        "模拟预知末世 → 搬家囤物资",
        "第一次清源 → 获得进化源 → 觉醒异能",
        "遇到第一个妖 → 建立互不信任的同盟",
    ],
    "核心节奏": {
        "小爽点": "每章1个: 模拟揭示新信息/清源收获/异能微突破",
        "中爽点": "每3-5章: 摧毁大侵蚀源/收服妖/异能跃升",
        "大爽点": "每卷: Boss源之战/妖盟建立/杀戮世界首次接触",
    },
}

# ============================================================
# v3: 量化节奏注入 (从 creative_guidance JSON 加载)
# ============================================================

def _find_project_root() -> Path:
    """Find project root by locating config.yaml."""
    p = Path(__file__).resolve().parent
    for _ in range(5):
        if (p / "config.yaml").exists():
            return p
        p = p.parent
    return PROJECT_ROOT  # fallback


def load_guidance_benchmarks(genre: str = "末世") -> dict:
    """Load pct_benchmarks + rule from creative_guidance JSON.

    Returns dict with keys: pct_benchmarks, hook_rule, pleasure_rule, hook_per_chars, pleasure_per_chars.
    Returns empty dict if guidance file not found.
    """
    root = _find_project_root()
    guidance_path = root / "data" / "reports" / genre / "creative_guidance" / f"{genre}_创作指导.json"

    if not guidance_path.exists():
        print(f"[WARN] 创作指导数据不存在: {guidance_path}")
        return {}

    try:
        data = json.loads(guidance_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError) as e:
        print(f"[WARN] 创作指导数据读取失败: {e}")
        return {}

    # Extract pct_benchmarks from rough_outline section
    rough = data.get("rough_outline", {})
    pct = rough.get("pct_benchmarks", {})

    # Extract rules from worldbuilding
    wb = data.get("worldbuilding", {})
    rule = wb.get("rule", "")

    # Load hook/pleasure thresholds from config.yaml
    hook_per_chars = 500
    pleasure_per_chars = 300
    cfg_path = root / "config.yaml"
    if cfg_path.exists():
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            cb = cfg.get("creative_bridge", {})
            hook_per_chars = cb.get("hook_per_chars", hook_per_chars)
            pleasure_per_chars = cb.get("pleasure_per_chars", pleasure_per_chars)
        except (yaml.YAMLError, IOError):
            pass

    return {
        "pct_benchmarks": pct,
        "hook_rule": rule,
        "hook_per_chars": hook_per_chars,
        "pleasure_per_chars": pleasure_per_chars,
        "genre": genre,
    }


def generate_rhythm_plan(chapter_count: int, genre: str = "末世") -> dict:
    """Generate chapter-by-chapter rhythm targets based on elite book benchmarks.

    Interpolates between pct_benchmark nodes (0%, 10%, 30%, 50%, 80%, 100%)
    to assign hook/conflict/pleasure targets per chapter.

    Returns dict: {chapter_number: {"hook_target": float, "conflict_target": float, "pleasure_target": float, "progress_pct": float}}
    """
    guidance = load_guidance_benchmarks(genre)
    if not guidance:
        return {}

    pct_benchmarks = guidance.get("pct_benchmarks", {})
    if not pct_benchmarks:
        return {}

    # Parse benchmark nodes as (progress_pct, {metrics})
    nodes = []
    for key, val in pct_benchmarks.items():
        try:
            pct_val = float(key.replace("%", ""))
            nodes.append((pct_val, val))
        except (ValueError, AttributeError):
            continue
    nodes.sort(key=lambda x: x[0])

    if len(nodes) < 2:
        return {}

    # For each chapter, find its position in the book progress and interpolate
    rhythm_plan = {}
    for ch in range(1, chapter_count + 1):
        progress = (ch / chapter_count) * 100.0

        # Find bracketing benchmark nodes
        lower = nodes[0]
        upper = nodes[-1]
        for n in nodes:
            if n[0] <= progress:
                lower = n
            if n[0] >= progress and upper[0] > progress:
                upper = n
                break

        # Linear interpolation
        if upper[0] == lower[0]:
            t = 0.0
        else:
            t = (progress - lower[0]) / (upper[0] - lower[0])

        def _interp(key, default=0.0):
            lo = lower[1].get(key, default)
            hi = upper[1].get(key, default)
            return round(lo + (hi - lo) * t, 4)

        rhythm_plan[ch] = {
            "hook_target": _interp("hook_mean"),
            "conflict_target": _interp("conflict_mean"),
            "pleasure_target": _interp("pleasure_mean"),
            "progress_pct": round(progress, 1),
        }

    return rhythm_plan


def inject_rhythm_targets(chapter_data: list, genre: str = "末世", chapter_size: int = 2000) -> list:
    """Annotate chapter outline list with quantified rhythm targets.

    Args:
        chapter_data: list of dicts with at least {"chapter": int, "event": str}
        genre: genre name for benchmark loading
        chapter_size: target characters per chapter (default 2000)

    Returns:
        chapter_data with added "rhythm" key containing target metrics and concrete counts
    """
    if not chapter_data:
        return chapter_data

    rhythm_plan = generate_rhythm_plan(len(chapter_data), genre)
    if not rhythm_plan:
        return chapter_data

    guidance = load_guidance_benchmarks(genre)
    hook_per = guidance.get("hook_per_chars", 500)
    pleasure_per = guidance.get("pleasure_per_chars", 300)

    for ch_info in chapter_data:
        ch_num = ch_info.get("chapter", 0)
        plan = rhythm_plan.get(ch_num, {})
        if not plan:
            continue

        # Convert density targets to per-chapter counts
        hook_count = max(1, round(plan["hook_target"] * chapter_size))
        pleasure_count = max(1, round(plan["pleasure_target"] * chapter_size))

        # Platform benchmarks for comparison
        platform_hook = max(1, chapter_size // hook_per)
        platform_pleasure = max(1, chapter_size // pleasure_per)

        ch_info["rhythm"] = {
            "hook_density": plan["hook_target"],
            "conflict_density": plan["conflict_target"],
            "pleasure_density": plan["pleasure_target"],
            "progress_pct": plan["progress_pct"],
            "targets_per_chapter": {
                "hooks_needed": hook_count,
                "pleasure_points_needed": pleasure_count,
            },
            "platform_benchmark": {
                "hooks_recommended": platform_hook,
                "pleasure_points_recommended": platform_pleasure,
            },
            "rule": guidance.get("hook_rule", ""),
        }

    return chapter_data


def print_rhythm_plan(chapter_count: int, genre: str = "末世") -> None:
    """Print a human-readable rhythm plan table."""
    plan = generate_rhythm_plan(chapter_count, genre)
    if not plan:
        print("[WARN] 无节奏基准数据")
        return

    print(f"\n{'='*70}")
    print(f"  节奏基准计划 | genre={genre} | chapters={chapter_count}")
    print(f"{'='*70}")
    print(f"  {'Ch':>4s}  {'进度':>5s}  {'钩子密度':>8s}  {'冲突密度':>8s}  {'爽点密度':>8s}")
    print(f"  {'-'*4}  {'-'*5}  {'-'*8}  {'-'*8}  {'-'*8}")

    for ch in sorted(plan.keys()):
        p = plan[ch]
        print(f"  {ch:4d}  {p['progress_pct']:4.1f}%  {p['hook_target']:8.4f}  {p['conflict_target']:8.4f}  {p['pleasure_target']:8.4f}")

    print(f"{'='*70}")
    guidance = load_guidance_benchmarks(genre)
    if guidance.get("hook_rule"):
        print(f"  Rule: {guidance['hook_rule']}")


# ============================================================
# run_outline_build — 大纲生成入口
# ============================================================

def run_outline_build(orch, genre: str, total_chapters: int, guidance_path=None) -> dict:
    """Generate a three-level outline (rough/volume/chapter) using LLM.

    Uses the existing ROUGH_OUTLINE_SYSP, VOLUME_OUTLINE_SYSP,
    CHAPTER_OUTLINE_SYSP templates. Integrates inject_rhythm_targets()
    and load_guidance_benchmarks() for quantified rhythm targets.

    Args:
        orch: ModelOrchestrator instance (must have chat_with_trace method)
        genre: Genre name (e.g. "末世", "玄幻")
        total_chapters: Total chapter count for the book
        guidance_path: Optional override path to creative_guidance JSON

    Returns:
        dict with keys:
            rough_outline: str (markdown)
            template_name: str
            volume_count: int
            chapter_data: list (with rhythm injection)
            rhythm_plan: dict (optional, from generate_rhythm_plan)
    """
    _logger.info("Starting outline build: genre=%s, chapters=%d", genre, total_chapters)

    # ── Load world setting ──
    world_path = PROJECT_ROOT / "assets" / "canon" / "world.md"
    world = ""
    if world_path.exists():
        world = world_path.read_text(encoding="utf-8")
        _logger.debug("Loaded world.md: %d chars", len(world))
    else:
        _logger.warning("No world.md found, proceeding without world context")

    # ── Template recommendation ──
    template_name = TEMPLATE_RECOMMEND.get(genre, "三幕式")
    template = TEMPLATES.get(template_name, TEMPLATES["三幕式"])
    _logger.info("Template: %s for genre %s", template_name, genre)

    # ── Load rhythm benchmarks ──
    guidance = load_guidance_benchmarks(genre)
    if guidance:
        _logger.info("Rhythm benchmarks loaded: %d pct nodes",
                      len(guidance.get("pct_benchmarks", {})))
    else:
        _logger.warning("No rhythm benchmarks available for %s", genre)

    # ── Step 1: Rough outline (总纲) ──
    _logger.info("Step 1/3: Generating rough outline...")
    print("\n  [1/3] Generating rough outline...")

    rough_msgs = [
        {"role": "system", "content": ROUGH_OUTLINE_SYSP},
        {"role": "user", "content": (
            f"题材: {genre}\n"
            f"总章节数: {total_chapters}\n"
            f"推荐模板: {template_name}\n"
            f"世界观概要: {world[:1200] if world else '(未设定, 请先运行 worldbuild)'}\n\n"
            f"请生成全书总纲框架 (5段式), 给出 2 个不同方向供作者选择。"
        )}
    ]
    rough_result = orch.chat_with_trace(
        "main_model", rough_msgs,
        caller="outline_builder.rough",
        max_tokens=2500, temperature=0.7, timeout=120
    )
    rough_outline = ""
    if "error" not in rough_result:
        rough_outline = rough_result["content"]
        _logger.info("Rough outline generated: %d chars", len(rough_outline))
    else:
        _logger.error("Rough outline failed: %s", rough_result["error"])
        print(f"  [FAIL] Rough outline: {rough_result['error']}")

    # ── Step 2: Volume outlines (卷纲) ──
    # Estimate volume count: ~40 chapters per volume
    volume_count = max(1, total_chapters // 40)
    _logger.info("Step 2/3: Generating %d volume outlines...", volume_count)
    print(f"  [2/3] Generating {volume_count} volume outlines...")

    volume_msgs = [
        {"role": "system", "content": VOLUME_OUTLINE_SYSP},
        {"role": "user", "content": (
            f"题材: {genre}\n"
            f"总章节数: {total_chapters}\n"
            f"卷数: {volume_count}\n"
            f"总纲: {rough_outline[:1000] if rough_outline else '(not yet)'}\n\n"
            f"请为 {volume_count} 卷生成卷纲, 每卷列出关键情节和卷末钩子。"
        )}
    ]
    volume_result = orch.chat_with_trace(
        "main_model", volume_msgs,
        caller="outline_builder.volume",
        max_tokens=3000, temperature=0.7, timeout=120
    )
    volume_outline = ""
    if "error" not in volume_result:
        volume_outline = volume_result["content"]
        _logger.info("Volume outlines generated: %d chars", len(volume_outline))
    else:
        _logger.error("Volume outlines failed: %s", volume_result["error"])
        print(f"  [FAIL] Volume outlines: {volume_result['error']}")

    # ── Step 3: Chapter outlines (章纲) with rhythm injection ──
    _logger.info("Step 3/3: Generating chapter outlines with rhythm injection...")
    print(f"  [3/3] Generating chapter outlines ({total_chapters} chapters)...")

    chapter_msgs = [
        {"role": "system", "content": CHAPTER_OUTLINE_SYSP},
        {"role": "user", "content": (
            f"题材: {genre}\n"
            f"总章节数: {total_chapters}\n"
            f"总纲: {rough_outline[:800] if rough_outline else '(not yet)'}\n"
            f"卷纲: {volume_outline[:800] if volume_outline else '(not yet)'}\n\n"
            f"请生成全部 {total_chapters} 章的章纲映射, 每行格式:\n"
            f"章号 | 事件标题 | 爽点类型 | 冲突级别 | 动机链 | 章末钩子类型 | 涉及角色"
        )}
    ]
    chapter_result = orch.chat_with_trace(
        "main_model", chapter_msgs,
        caller="outline_builder.chapter",
        max_tokens=4000, temperature=0.7, timeout=180
    )
    chapter_text = ""
    if "error" not in chapter_result:
        chapter_text = chapter_result["content"]
        _logger.info("Chapter outlines generated: %d chars", len(chapter_text))
    else:
        _logger.error("Chapter outlines failed: %s", chapter_result["error"])
        print(f"  [FAIL] Chapter outlines: {chapter_result['error']}")

    # ── Parse chapter outline into structured data ──
    chapter_data = _parse_chapter_outline(chapter_text, total_chapters)

    # ── Inject rhythm targets ──
    if chapter_data:
        chapter_data = inject_rhythm_targets(chapter_data, genre)
        _logger.info("Rhythm targets injected into %d chapters", len(chapter_data))

    # ── Generate full rhythm plan ──
    rhythm_plan = generate_rhythm_plan(total_chapters, genre)

    _logger.info("Outline build complete: rough=%d chars, %d volumes, %d chapters",
                  len(rough_outline), volume_count, len(chapter_data))

    return {
        "rough_outline": rough_outline,
        "volume_outline": volume_outline,
        "template_name": template_name,
        "volume_count": volume_count,
        "chapter_data": chapter_data,
        "rhythm_plan": rhythm_plan,
        "genre": genre,
        "total_chapters": total_chapters,
    }


def _parse_chapter_outline(chapter_text: str, total_chapters: int) -> list:
    """Parse LLM-generated chapter outline text into structured data.

    Expected format per line: 章号 | 事件标题 | 爽点类型 | 冲突级别 | 动机链 | 章末钩子类型 | 涉及角色

    Args:
        chapter_text: Raw chapter outline text from LLM
        total_chapters: Expected chapter count

    Returns:
        list of dicts with keys: chapter, event, pleasure_type, conflict_level, motivation_chain, hook_type, characters
    """
    if not chapter_text:
        return []

    chapters = []
    for line in chapter_text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("```"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            continue
        try:
            ch_num = int(parts[0])
            chapters.append({
                "chapter": ch_num,
                "event": parts[1] if len(parts) > 1 else "",
                "pleasure_type": parts[2] if len(parts) > 2 else "",
                "conflict_level": parts[3] if len(parts) > 3 else "",
                "motivation_chain": parts[4] if len(parts) > 4 else "",
                "hook_type": parts[5] if len(parts) > 5 else "",
                "characters": parts[6] if len(parts) > 6 else "",
            })
        except (ValueError, IndexError):
            continue

    _logger.debug("Parsed %d chapter entries from outline text", len(chapters))
    return chapters


# ============================================================
# 模块自检
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("  outline_builder.py v3 — 自检")
    print("=" * 60)

    assert len(OutlineLevel.__members__) == 3, "[FAIL] 应有 3 层大纲"
    print(f"  [OK] 大纲层级: {list(OutlineLevel.__members__.keys())}")

    assert len(TEMPLATES) == 5, f"[FAIL] 应有 5 种模板, 实际 {len(TEMPLATES)}"
    for name, tpl in TEMPLATES.items():
        print(f"  [OK] 模板: {name} (适合: {tpl['适合']})")

    assert ROUGH_OUTLINE_SYSP, "[FAIL] 缺总纲 System Prompt"
    assert VOLUME_OUTLINE_SYSP, "[FAIL] 缺卷纲 System Prompt"
    assert CHAPTER_OUTLINE_SYSP, "[FAIL] 缺章纲 System Prompt"
    print(f"  [OK] 3个 System Prompt 完整")

    assert len(TEMPLATE_RECOMMEND) >= 10, f"[FAIL] 题材推荐不足"
    print(f"  [OK] 题材推荐: {len(TEMPLATE_RECOMMEND)} 种")

    assert "主线" in APOCALYPSE_SIMULATOR_SKELETON, "[FAIL] 缺末世模拟器骨架"
    assert len(APOCALYPSE_SIMULATOR_SKELETON["前5万字任务"]) == 3, "[FAIL] 前5万字任务不足3个"
    print(f"  [OK] 末世模拟器专属骨架: {APOCALYPSE_SIMULATOR_SKELETON['主线']}")

    # v3: test rhythm injection
    print("\n--- v3 量化节奏注入测试 ---")
    guidance = load_guidance_benchmarks("末世")
    if guidance:
        print(f"  [OK] 加载创作指导: {len(guidance.get('pct_benchmarks', {}))} 个百分位节点")
        print(f"  [OK] 平台建议: 每{guidance['hook_per_chars']}字1钩子 / 每{guidance['pleasure_per_chars']}字1爽点")
    else:
        print("  [SKIP] 创作指导数据不可用")

    # Test rhythm plan generation
    plan = generate_rhythm_plan(10, "末世")
    if plan:
        print(f"  [OK] 节奏计划: {len(plan)} 章目标生成")
        # Test injection
        sample = [{"chapter": i, "event": f"test event {i}"} for i in range(1, 6)]
        injected = inject_rhythm_targets(sample, "末世")
        has_rhythm = all("rhythm" in ch for ch in injected)
        print(f"  [OK] 节奏注入: {'全部成功' if has_rhythm else '部分失败'}")
    else:
        print("  [SKIP] 节奏计划生成跳过 (数据不可用)")

    print("\n[DONE] outline_builder.py v3 数据验证完成")
