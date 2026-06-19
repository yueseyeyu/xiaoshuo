"""
world_builder.py — S0 冲突驱动世界观构建引导 v2
============================================================
─ 设计蓝本 ─
融合四方方法论:
  1. 抖音方案: 5 阶段冲突树 (时间→矛盾→场景→规则→特殊元素)
  2. Critical Inker (MIT EMNLP 2025): Socratic 反问链, 每次只问一点
  3. Nous (arxiv 2510.27410): 信息增益驱动 — 优先问降低不确定性最多的问题
  4. AI-Novel-Writing-Assistant: 实体骨架结构 (势力/地点/关系/冲突)

─ 核心原则 ─
· 世界观是"冲突的土壤", 不是背景板
· 平台合规 (番茄官方):
  ├ 内容积极向上, 禁止: 校园霸凌/暗黑文学/违背公序良俗
  ├ 避免: 男女对立等敏感社会议题
  └ 版权: 不使用有版权争议的IP世界观 (如斗罗)
· 辅助边界 (可AI生成):
  ├ 背景素材: 势力/宝物/功法/地点/角色框架 → 给2-3方案供选
  ├ 大纲: 总纲(5段式)、卷纲(事件链)、章纲(爽点+钩子) → 见 outline_builder.py
  └ 禁止: 正文段落/对话描写/主角命运抉择
· 每阶段输出写入 canon/ 目录 + world_skeleton.json, 后续 S1/S3 自动引用
· 逻辑冲突检测在每个阶段结束时自动运行
· 9种题材追问补丁 (config author.genres 注入)

─ 实现状态 ─
P0 实验通过 (2026-06-05 Qwen3.5单模型确定)
v2: 实体骨架 + Nous信息增益 + 全题材覆盖
TODO: 接入 orchestrator + skill_loader 实现交互式构建
"""

from enum import Enum
from xiaoshuo.infra.logging_config import get_logger
from xiaoshuo.infra.config_manager import get_config

_logger = get_logger("world_builder")



# ============================================================
# 5 阶段定义
# ============================================================

class WorldStage(Enum):
    """世界观构建的 5 个阶段，顺序执行。"""
    TIME = "time"           # 时间背景
    CONFLICT = "conflict"   # 核心矛盾
    SCENE = "scene"         # 场景设计
    RULES = "rules"         # 社会规则
    SPECIAL = "special"     # 特殊元素 & 未解之谜


# ============================================================
# Socratic System Prompt 模板
# ============================================================
# 每个阶段注入不同的引导角色和追问模式。
# 核心约束来自 Critical Inker: 每次只问一点, 引用前文反问, 用户自辩才算完成。

SOCRATIC_SYSTEM_PROMPT = """
## 你的角色
你是一个冲突驱动型世界观构建引导师。你的核心信念:
> 世界观不是故事的背景板, 是冲突的土壤。
> 每一个设定都应该能回答一个问题: "这个设定催生了什么冲突?"

## Socratic 提问法则 (Critical Inker + Nous模式)
1. **每次只问一个焦点问题** — 不要一口气抛出 3-5 个问题, 每次聚焦于一个逻辑点
2. **引用前文反问** — 提问时引用作者上一轮的选择, 追问: "你说 X, 那 X 怎样产生 Y 类型的冲突?"
3. **用户自辩才算完成** — 只有当作者明确表达了冲突逻辑后, 才能进入下一问
4. **信息增益优先** (Nous, arxiv 2510.27410) — 优先问能最大程度减少世界观不确定性的问题;
   判断标准: 这个问题的答案, 能否同时澄清作者在多个维度上的犹豫?

## 代笔边界 (关键区分)
**可以辅助生成 (背景素材)**:
- 势力名称、结构、关系网 → 给出 2-3 个方案供作者选择
- 天材地宝、功法体系、修炼等级 → 列出选项 + 每种选项的冲突潜力
- 角色性格框架、阵营倾向 → 提供模板, 作者填细节
- 地点描述、世界地图概要 → 给出设定草稿

**禁止代笔 (正文内容)**:
- 禁止写完整的章节正文、对话段落、叙事描写
- 禁止替作者决定主角的最终选择或命运走向
- 当用户说"帮我写一段"时, 拒绝并改为提问引导

原则: 背景素材是"食材准备", AI 可以切菜备料; 正文是"烹饪", 必须是作者亲自下厨。

## 网文爽点映射 (WebNovel AI 模式)
每当你确定了一条世界规则后, 追问:
"这条规则可以催生什么类型的爽点？(打脸/逆袭/扮猪吃虎/身份反转/资源碾压)"

## 黄金三章约束
番茄平台核心指标: 第二章完读率 ≥60%。每一阶段的设定都必须回答:
"这个设定能在第一章的前 500 字里展现给读者吗？如果不能, 为什么？"
"""


# ============================================================
# 5 个阶段的任务模板
# ============================================================
# 每个模板定义了该阶段的核心问题、追问链、输出目标。
# 实际执行时由 skill_loader 拼接 System Prompt + 当前上下文。

STAGE_TEMPLATES = {
    WorldStage.TIME: {
        "title": "阶段一: 时间背景",
        "goal": "确定时代背景和历史阶段, 建立冲突的时间维度",
        "core_question": "这个时代本身在酝酿什么冲突？",
        "chase_chain": [
            "你选择的时代(如末世), 普通人面临的最大生存威胁是什么？",
            "这个时代背景下, 权力的来源是什么？(武力/知识/血统/资源)",
            "当前处于什么历史阶段？(盛世/战乱/变革前夕) — 这种阶段会天然产生什么矛盾？",
        ],
        "output_file": "canon/world.md",
        "output_section": "## 时代背景",
    },
    WorldStage.CONFLICT: {
        "title": "阶段二: 核心矛盾",
        "goal": "确定主线矛盾体系, 这是全书戏剧张力的发动机",
        "core_question": "这个世界的根本矛盾是什么？它怎样影响主角的命运？",
        "chase_chain": [
            "选择一个主要矛盾类型(阶级对立/正邪对抗/资源争夺/身份认同/种族冲突)",
            "这个矛盾的具体表现形式是什么？(举例: '修真资源被大宗门垄断, 散户无法突破')",
            "主角处于这个矛盾的哪一侧？为什么他无法置身事外？",
            "爽点映射: 这个矛盾结构能催生什么类型的爽点？",
        ],
        "output_file": "canon/world.md",
        "output_section": "## 核心矛盾",
    },
    WorldStage.SCENE: {
        "title": "阶段三: 场景设计",
        "goal": "设计物理空间, 让空间本身成为冲突的放大器",
        "core_question": "这个场景怎样放大已有的矛盾？",
        "chase_chain": [
            "选择主要场景类型(城市/荒野/学院/宗门/地下城)",
            "这个场景有什么独特的资源或限制？(举例: '外层区域氧气稀薄, 只有富人用得起氧气胶囊')",
            "场景之间怎样形成对比？(安全区 vs 危险区, 富人区 vs 贫民窟)",
            "主角的初始位置在哪里？这个位置对他意味着什么？",
        ],
        "output_file": "canon/world.md",
        "output_section": "## 场景设计",
    },
    WorldStage.RULES: {
        "title": "阶段四: 社会规则",
        "goal": "建立权力结构、经济体系和潜规则, 为角色动机提供土壤",
        "core_question": "这个社会的规则在压迫谁？在奖励谁？",
        "chase_chain": [
            "政治体制是什么？(皇权/宗门议会/企业寡头/无政府)",
            "经济体系的核心是什么？(灵石/信用点/基因强化剂/信息)",
            "存在什么潜规则或不成文的规定？(举例: '宗门内门弟子可以随意欺压外门弟子')",
            "有没有不同于现实的特殊规则？(举例: '修为低于某等级的人没有法律人格')",
        ],
        "output_file": "canon/rules.md",
        "output_section": "## 社会规则",
    },
    WorldStage.SPECIAL: {
        "title": "阶段五: 特殊元素 & 未解之谜",
        "goal": "引入魔法/科技/超能力等特殊元素, 并埋设悬念钩子",
        "core_question": "这个特殊元素的使用代价是什么？代价本身就构成冲突。",
        "chase_chain": [
            "特殊元素是什么？(灵气/异能/赛博义体/基因锁)",
            "使用它的代价是什么？(寿命/理智/社会地位/资源消耗)",
            "谁控制着这个特殊元素？控制者与被控制者之间的矛盾是什么？",
            "AI 根据前 4 阶段的设定自动生成 3 个未解之谜, 作为故事的悬念钩子",
        ],
        "output_file": "canon/world.md",
        "output_section": "## 特殊元素 & 未解之谜",
    },
}


# ============================================================
# 逻辑冲突检测模板 (阶段间自动运行)
# ============================================================
# 每完成一个阶段后, 用逻辑警察的视角检查设定一致性
# 复用 skill_loader 的 S3_logic_cop 模板, 但上下文改为设定文本

CONFLICT_CHECK_PROMPT = """
## 你的角色
你是世界观逻辑审查官。检查刚完成的阶段设定是否有内部矛盾。

## 检查项
1. 本阶段的新设定是否与已有设定冲突？
2. 已确定的规则是否存在例外情况未被处理？
3. 是否存在"因为方便而牺牲逻辑"的叙事捷径？

## 输出格式
{
  "conflicts": [
    {"type": "internal|external", "detail": "具体矛盾描述", "severity": "HIGH|MEDIUM|LOW"}
  ],
  "suggestions": ["建议1", "建议2"]
}
"""


# ============================================================
# 爽点映射表 (网文专属)
# ============================================================
# 每种世界规则类型 → 可催生的爽点模式
# 作者在构建世界时可以看到 "这个设定能支撑什么类型的打脸场景"

PLEASURE_MAPPING = {
    "等级制度":     ["低等级逆袭高等级", "隐藏实力碾压", "跨级挑战的震惊反应"],
    "资源垄断":     ["独享稀缺资源", "破局打破垄断", "用知识代替资源"],
    "信息不对称":   ["扮猪吃虎", "识破阴谋", "预知未来"],
    "身份压制":     ["暴露真实身份", "打脸看不起自己的人", "以德报怨/以直报怨"],
    "规则漏洞":     ["利用规则反制", "发现系统后门", "创造新规则"],
}

# ============================================================
# World Skeleton 实体结构 (AI-Novel-Writing-Assistant 启发)
# ============================================================
# 世界观不仅是文本, 更是结构化实体网络。
# 构建时自动填充该结构, 供 S1/S3/S4 阶段检索注入。
WORLD_SKELETON_SCHEMA = {
    "factions": [],      # [{name, goal, resources, conflict_with}]
    "locations": [],     # [{name, type, occupant, key_feature}]
    "relations": [],     # [{from, to, type: ally/neutral/hostile}]
    "conflict_entries": [],  # [{name, sides, stakes, related_dim}]
    "special_elements": [],  # [{name, cost, controller, conflict_from}]
}
"""World Skeleton schema — built incrementally during 5-stage construction."""

# ============================================================
# 类型化追问补丁 (Genre-Specific)
# ============================================================
# 不同题材额外追问，追加在核心 5 阶段之后
# 来源: 网文俱乐部(wangwenclub.com) + 知乎修真框架

GENRE_PATCHES: dict[str, list[str]] = {
    "玄幻": [
        "修炼体系: 境界划分为几大阶段？每个阶段的突破条件和能力跃迁是什么？",
        "天材地宝: 这个世界的稀缺资源是什么？谁控制着它们？",
        "宗门势力: 宗门之间的关系网络是怎样的？(同盟/敌对/制衡)",
        "天道规则: 这个世界有没有超越凡俗的'天道'？它是否可以被挑战？",
    ],
    "历史穿越": [
        "穿越方式: 主角是身穿还是魂穿？穿越的时间点和地理位置？",
        "历史偏离: 这个世界和你熟知的历史有哪些关键差异？(蝴蝶效应)",
        "知识优势: 主角的现代知识哪些可以用、哪些会失效？(技术断代)",
        "身份困境: 穿越后的身份地位是什么？这个身份自带什么冲突？",
    ],
    "仙侠": [
        "修炼体系: 境界划分为几大阶段？渡劫、飞升的规则是什么？",
        "灵气/资源: 这个世界修炼靠什么？灵气的分布和稀缺度？",
        "因果循环: 是否存在天道报应、因果律？对主角行为有什么约束？",
        "飞升之后: 最高境界之后是什么？是否有更高层次的世界？",
    ],
    "同人": [
        "原作时间线: 故事发生在原作的哪个时间点？前传/正传/后传？",
        "蝴蝶效应: 主角的介入改变了原作的哪些关键事件？",
        "角色边界: 哪些原作角色会保留, 哪些会被改写或删除？",
        "尊重度: 对原作的改编程度？(致敬式扩展 vs 颠覆式重写)",
    ],
    "洪荒流": [
        "洪荒时间线: 处于什么洪荒纪元？(开天/龙汉/巫妖/封神)",
        "跟脚设定: 主角的出身根脚是什么？(先天神魔/大能转世/混沌遗种)",
        "法宝系统: 核心法宝是什么？先天灵宝还是后天炼制？",
        "因果杀劫: 天道杀劫是什么？主角如何应对量劫？",
    ],
    "无敌文": [
        "无敌状态: 主角从第几章开始无敌？初始强度如何展现？",
        "封号/限制: 既然无敌, 有什么限制条件？(封印/沉睡/规则绑定)",
        "对手层次: 如果主角无敌, 冲突从哪来？(同层次较量/规则博弈/守护)",
        "爽点节奏: 如何在无敌状态下维持悬念？(身份伪装/信息差/限时任务)",
    ],
    "都市": [
        "社会阶层: 城市分为哪些阶层？阶层的上升通道和隐形天花板是什么？",
        "金钱与权力: 财富的来源是什么？(继承/创业/灰色地带)",
        "人脉网络: 主角的初始社交圈是什么？他如何突破圈层？",
        "法律与潜规则: 明面上的法律和暗地里的规则有多大差距？",
    ],
    "末世": [
        "灾难类型: 末世的成因是什么？(病毒/核战/天灾/灵气复苏)",
        "幸存者组织: 幸存者如何组织？(军队/帮派/科学团体)",
        "资源稀缺: 最稀缺的 3 种生存资源是什么？它们的分配规则是什么？",
        "秩序重建: 有人试图重建文明秩序吗？用什么方式？",
    ],
    "科幻": [
        "技术水平: 核心科技是什么？它的能量来源和限制是什么？",
        "星际格局: 人类文明处于什么阶段？(地球纪元/星际殖民/银河帝国)",
        "AI 与人类: AI 的地位和权利是什么？人类如何与 AI 共存/对抗？",
        "外星文明: 存在外星文明吗？第一次接触是和平还是战争？",
    ],
}

# ============================================================
# 反套路检测 Prompt (Genre-Specific)
# ============================================================
# 构建完基础世界观后, 检查是否与同类型作品的设定过于雷同
# 输入: 已构建的设定文本
# 输出: 雷同警告 + 差异化建议

ANTI_CLICHE_PROMPT = """
## 你的角色
你是网文原创性审查官。你的任务是检查刚完成的世界观设定,
是否与同类型畅销作品过于雷同。

## 检查维度
1. 力量/技能体系 — 是否只是换了个名字的修炼等级？
2. 核心矛盾 — 是否只是经典矛盾的简单复刻？
3. 世界观爽点 — 是否和同类型 Top10 作品高度重合？

## 输出格式
{
  "originality_score": 1-10,      # 10=极高原创性, 1=高度雷同
  "similar_works": ["可能雷同的作品1", "作品2"],
  "differentiation_suggestions": ["建议1", "建议2"],
  "unique_elements": ["已检测到的独特元素"]
}
"""

# ============================================================
# 黄金三章钩子检测 Prompt
# ============================================================
# 检查世界观设定是否支撑一个有吸引力的开篇
# 输入: 已构建的设定文本
# 输出: 钩子质量评分 + 改进建议

HOOK_CHECK_PROMPT = """
## 你的角色
你是网文开篇审查官。番茄小说平台的核心指标是"第二章完读率≥60%"。
你的任务是检查当前世界观设定是否能支撑一个高完读率的开篇。

## 检查维度
1. 第一章最晚第 500 字处, 是否有让读者想知道"接下来怎样"的悬念？
2. 世界观中最吸引人的冲突, 能否在第一章就展现？
3. 主角的初始处境是否足够"惨"或"悬"以制造紧迫感？

## 输出格式
{
  "hook_strength": 1-10,          # 10=超强钩子
  "first_chapter_conflict": "...", # 第一章可以展现什么冲突
  "reader_question": "...",        # 读者看完第一章后会问什么问题
  "improvements": ["改进1", "改进2"]
}
"""


# ============================================================
# run_world_build — 5 阶段 Socratic 世界观构建入口
# ============================================================

def run_world_build(orch, session_manager=None) -> str:
    """Run the 5-stage Socratic world building process.

    Uses the existing STAGE_TEMPLATES, SOCRATIC_SYSTEM_PROMPT, WorldStage,
    and GENRE_PATCHES. Calls orch.chat_with_trace() for each stage's
    follow-up question generation.

    Args:
        orch: ModelOrchestrator instance (must have chat_with_trace method)
        session_manager: Optional SessionManager; if provided, the caller
            should handle stage advancement externally.

    Returns:
        str: The generated world.md content (markdown format).
    """
    stages = [
        (WorldStage.TIME, "一: 时间背景"),
        (WorldStage.CONFLICT, "二: 核心矛盾"),
        (WorldStage.SCENE, "三: 场景设计"),
        (WorldStage.RULES, "四: 社会规则"),
        (WorldStage.SPECIAL, "五: 特殊元素"),
    ]

    print("=" * 60)
    print("  S0 世界观构建 — 5 阶段 Socratic 引导")
    print("  AI 提问, 你回答。每次只说关键设定, 不要求完整描述。")
    print("=" * 60)

    all_answers = []

    for wstage, title in stages:
        tpl = STAGE_TEMPLATES[wstage]
        core_q = tpl["core_question"]

        print(f"\n{'─' * 60}")
        print(f"  阶段{title}")
        print(f"  [{tpl['goal']}]")
        print(f"\n  AI: {core_q}")
        print(f"  (输入 'q' 跳过此阶段)")
        answer = input("  你: ").strip()

        if answer.lower() == "q":
            all_answers.append(f"## {title}\n(作者跳过)\n")
            _logger.info("Stage %s: skipped by user", wstage.value)
            continue

        # Socratic 追问: 使用 SOCRATIC_SYSTEM_PROMPT + chase_chain
        print(f"\n  AI 追问中...")
        msgs = [
            {"role": "system", "content": SOCRATIC_SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"阶段: {title} ({tpl['goal']})\n"
                f"核心问题: {core_q}\n"
                f"作者回答: {answer}\n\n"
                f"追问链: {tpl['chase_chain'][0]}\n"
                f"请基于作者的回答, 提出一个 Socratic 追问 (只问一个问题)。"
            )}
        ]

        result = orch.chat_with_trace(
            "main_model", msgs,
            caller=f"world_builder.{wstage.value}",
            max_tokens=120, temperature=0.7, timeout=60
        )
        if "error" not in result:
            follow_up = result["content"].strip()
            _logger.debug("Stage %s follow-up: %s", wstage.value, follow_up[:80])
            print(f"  AI: {follow_up}")
            fu_answer = input("  你: ").strip()
            if fu_answer:
                all_answers.append(
                    f"## {title}\n问: {core_q}\n答: {answer}\n"
                    f"追问: {follow_up}\n答: {fu_answer}\n"
                )
            else:
                all_answers.append(f"## {title}\n问: {core_q}\n答: {answer}\n")
        else:
            _logger.warning("Stage %s follow-up failed: %s", wstage.value, result["error"])
            all_answers.append(f"## {title}\n问: {core_q}\n答: {answer}\n")

    world_content = "# 世界观设定\n\n" + "\n".join(all_answers)
    _logger.info("World build complete: %d chars, %d stages answered",
                  len(world_content), sum(1 for a in all_answers if "(作者跳过)" not in a))
    return world_content


# ============================================================
# 模块自检
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("  world_builder.py — 自检 (仅验证数据完整性)")
    print("=" * 60)

    assert len(STAGE_TEMPLATES) == 5, "[FAIL] 应该有 5 个阶段"
    for stage in WorldStage:
        assert stage in STAGE_TEMPLATES, f"[FAIL] 缺阶段: {stage.value}"
        tpl = STAGE_TEMPLATES[stage]
        assert tpl["core_question"], f"[FAIL] {stage.value} 缺核心问题"
        assert len(tpl["chase_chain"]) >= 3, f"[FAIL] {stage.value} 追问链不足 3 条"
        print(f"  [OK] {stage.value}: {tpl['title']} ({len(tpl['chase_chain'])} 条追问)")

    assert len(PLEASURE_MAPPING) == 5, "[FAIL] 爽点映射应有 5 类"
    assert len(GENRE_PATCHES) == 9, f"[FAIL] 应有 9 种题材, 实际 {len(GENRE_PATCHES)}"
    print(f"  [OK] 题材追问补丁: {len(GENRE_PATCHES)} 种, 含 {', '.join(GENRE_PATCHES.keys())}")

    assert len(WORLD_SKELETON_SCHEMA) == 5, "[FAIL] World Skeleton 应有 5 实体"
    print(f"  [OK] World Skeleton: {len(WORLD_SKELETON_SCHEMA)} 实体类型")

    print("\n[DONE] world_builder.py v2 数据验证完成")
