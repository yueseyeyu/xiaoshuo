#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
character_designer.py -- S0 角色设计引导 v1
============================================================
-- 设计蓝本 --
融合三方方法论:
  1. world_builder.py: Socratic 追问链 + 冲突驱动
  2. outline_builder.py: 多方案供选, 作者决策
  3. Save the Cat! 角色弧: 缺陷->需求->成长->代价

-- 核心原则 --
- 角色是"冲突的载体", 不是属性列表
- 每个角色必须回答: "这个角色在故事中制造什么冲突?"
- AI 给出 2-3 方案供选, 禁止替作者决定角色命运
- 输出写入 canon/characters.md

-- 角色维度 --
  1. 主角: 核心缺陷 + 核心需求 + 成长弧光 + 独特能力
  2. 对手: 镜像关系 + 动机合理性 + 威胁等级
  3. 盟友: 功能定位 + 关系张力 + 牺牲代价
  4. 势力领袖: 阵营立场 + 利益冲突 + 权力结构

-- 实现状态 --
v1: 4维度角色卡 + Socratic 追问 + 关系网生成
"""

from pathlib import Path
from typing import Optional


# ============================================================
# System Prompt
# ============================================================
CHARACTER_SYSTEM_PROMPT = """
## 你的角色
你是一个角色设计引导师。你的核心信念:
> 角色不是属性列表, 是冲突的载体。
> 好角色的每一个特质都应该制造故事张力。

## 引导法则
1. **每次聚焦一个维度** -- 不要一口气问 5 个问题
2. **冲突驱动** -- 每个特质都要追问: "这个特质会制造什么冲突?"
3. **方案供选** -- 给出 2-3 个方向, 标注各自的叙事潜力, 让作者选择
4. **镜像追问** -- 设计对手时追问: "对手和主角在哪一点上是镜像的?"

## 代笔边界
**可以辅助生成**: 角色名建议/性格框架/能力体系模板/关系网图
**禁止代笔**: 角色的具体对话/内心独白/命运抉择

## 网文角色爽点映射
每个角色特质都要映射爽点类型:
- 核心缺陷 -> 逆袭爽点(克服缺陷)
- 独特能力 -> 碾压爽点(能力展示)
- 隐藏身份 -> 反转爽点(身份揭露)
- 代价牺牲 -> 共鸣爽点(情感冲击)

## 输出格式
角色卡模板:
```
## [角色名]
- 定位: [主角/对手/盟友/势力领袖]
- 核心缺陷: [一句话]
- 核心需求: [一句话]
- 成长弧光: [起点] -> [转折] -> [终点]
- 独特能力/资源: [一句话]
- 爽点类型: [逆袭/碾压/反转/共鸣]
- 与主角关系: [一句话]
- 冲突贡献: [这个角色制造了什么核心冲突?]
```
"""


# ============================================================
# 4 维度设计流程
# ============================================================
CHARACTER_DIMENSIONS = [
    {
        "name": "protagonist",
        "title": "主角设计",
        "goal": "设计有缺陷、有需求、有成长弧光的主角",
        "core_question": "你的主角最大的缺陷是什么? 这个缺陷如何同时成为他最大的力量来源?",
        "follow_ups": [
            "这个缺陷在第一章的前 500 字里如何展现给读者?",
            "主角的核心需求是什么? 他以为自己需要 X, 但实际需要 Y?",
            "主角的成长弧光: 从 A 状态(缺陷主导) -> 经历 B(危机) -> 达到 C(成长)?",
        ],
    },
    {
        "name": "antagonist",
        "title": "对手设计",
        "goal": "设计与主角镜像对称、动机合理的对手",
        "core_question": "你的对手和主角在哪一点上是镜像的? (他们追求同一个东西, 但方法相反?)",
        "follow_ups": [
            "对手的动机, 站在他的角度看是合理的吗? (好对手不是疯子)",
            "对手对主角的威胁是物理层面/心理层面/还是社会层面?",
            "对手的弱点是什么? 主角最终如何利用这个弱点?",
        ],
    },
    {
        "name": "ally",
        "title": "盟友设计",
        "goal": "设计有功能定位和关系张力的盟友",
        "core_question": "这个盟友在故事中承担什么功能? (战力补充/信息渠道/情感锚点/喜剧缓冲)",
        "follow_ups": [
            "盟友和主角之间最大的分歧是什么? 这个分歧会在什么时候爆发?",
            "盟友愿意为主角牺牲什么? 这个牺牲的代价感如何体现?",
            "盟友有什么主角不知道的秘密?",
        ],
    },
    {
        "name": "power_leader",
        "title": "势力领袖设计",
        "goal": "设计有立场、有利益冲突的势力领袖",
        "core_question": "这个势力的核心利益是什么? 它与主角的目标在哪一点上冲突?",
        "follow_ups": [
            "势力领袖的权力来源是什么? 这个来源有什么隐患?",
            "势力内部有没有反对派? 主角能否利用这个裂痕?",
            "这个势力在世界观中占据什么生态位?",
        ],
    },
]


# ============================================================
# 运行入口
# ============================================================
def run_character_design() -> None:
    """
    交互式角色设计流程。
    4 维度逐步引导, 每维度 Socratic 追问 + 方案供选。
    结果追加到 canon/characters.md。

    调用方式: python novel.py characters
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from model_orchestrator import get_orchestrator

    orch = get_orchestrator()

    print("=" * 60)
    print("  S0 角色设计 -- 4 维度 Socratic 引导")
    print("  AI 提问, 你回答。聚焦冲突, 不堆砌属性。")
    print("=" * 60)

    all_cards = []

    for dim in CHARACTER_DIMENSIONS:
        print(f"\n{'---' * 20}")
        print(f"  {dim['title']}")
        print(f"  [{dim['goal']}]")
        print(f"\n  AI: {dim['core_question']}")
        print(f"  (输入 'q' 跳过此维度)")

        answer = input("  You: ").strip()
        if answer.lower() == "q":
            all_cards.append(f"## {dim['title']}\n(skipped)\n")
            continue

        # Socratic 追问
        print("\n  AI: Generating follow-up...")
        msgs = [
            {"role": "system", "content": CHARACTER_SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"Dimension: {dim['title']} ({dim['goal']})\n"
                f"Core question: {dim['core_question']}\n"
                f"Author answer: {answer}\n\n"
                f"Follow-up template: {dim['follow_ups'][0]}\n"
                f"Based on the author's answer, ask ONE Socratic follow-up question. "
                f"Focus on conflict potential. Do NOT write story content."
            )}
        ]

        result = orch.chat(
            "main_model", msgs,
            max_tokens=150, temperature=0.7, timeout=60
        )

        if "error" not in result:
            follow_up = result["content"].strip()
            print(f"  AI: {follow_up}")
            fu_answer = input("  You: ").strip()
        else:
            follow_up = "(LLM unavailable)"
            fu_answer = ""

        # 生成角色卡草稿 (2-3 方案)
        print("\n  AI: Generating character card options...")
        card_msgs = [
            {"role": "system", "content": CHARACTER_SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"Dimension: {dim['title']}\n"
                f"Author answers:\n"
                f"  Core: {answer}\n"
                f"  Follow-up: {fu_answer}\n\n"
                f"Generate 2 character card options in the template format. "
                f"Each option should have different conflict potential. "
                f"Label them Option A and Option B. Keep each card under 200 chars."
            )}
        ]

        card_result = orch.chat(
            "main_model", card_msgs,
            max_tokens=600, temperature=0.7, timeout=90
        )

        if "error" not in card_result:
            print(f"\n{card_result['content']}")
            choice = input("\n  Choose [A/B/custom]: ").strip()
            if choice.lower() == "a":
                selected = "Option A selected by author"
            elif choice.lower() == "b":
                selected = "Option B selected by author"
            else:
                selected = f"Author custom: {choice}" if choice else "No selection"
        else:
            print(f"  [FAIL] Card generation failed: {card_result['error']}")
            selected = f"Author answer: {answer}"

        card_text = (
            f"## {dim['title']}\n"
            f"Core answer: {answer}\n"
            f"Follow-up: {follow_up}\n"
            f"Follow-up answer: {fu_answer}\n"
            f"Selection: {selected}\n"
        )
        all_cards.append(card_text)

    # 保存到 canon/characters.md
    chars_path = Path(__file__).resolve().parent.parent / "assets" / "canon" / "characters.md"
    chars_path.parent.mkdir(parents=True, exist_ok=True)

    existing = ""
    if chars_path.exists():
        existing = chars_path.read_text(encoding="utf-8")

    header = "# Character Design\n\n" if not existing or "待填写" in existing else existing + "\n\n---\n\n"
    chars_path.write_text(header + "\n".join(all_cards), encoding="utf-8")

    print(f"\n{'=' * 60}")
    print(f"  [OK] Characters saved to assets/canon/characters.md")
    print(f"{'=' * 60}")
