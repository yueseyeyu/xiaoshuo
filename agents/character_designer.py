#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
character_designer.py -- S0 角色设计引导 v2
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

-- v2 新增 --
- CharacterNode + CharacterGraph: 关系网生成 + 矩阵输出
- ArcTracker: 弧光追踪(起点→转折→终点)
- 势力归属: 从 creative_guidance 冲突类型分布加载

-- 角色维度 --
  1. 主角: 核心缺陷 + 核心需求 + 成长弧光 + 独特能力
  2. 对手: 镜像关系 + 动机合理性 + 威胁等级
  3. 盟友: 功能定位 + 关系张力 + 牺牲代价
  4. 势力领袖: 阵营立场 + 利益冲突 + 权力结构
"""

import json
from pathlib import Path
from typing import Optional


# ============================================================
# v2: 角色数据模型
# ============================================================

class CharacterNode:
    """Single character in the relationship graph."""

    def __init__(self, name: str, role: str, arc_start: str = "", arc_turn: str = "",
                 arc_end: str = "", faction: str = "", ability: str = "",
                 flaw: str = ""):
        self.name = name
        self.role = role  # protagonist/antagonist/ally/power_leader
        self.arc_start = arc_start
        self.arc_turn = arc_turn
        self.arc_end = arc_end
        self.faction = faction
        self.ability = ability
        self.flaw = flaw
        self.relations: dict[str, str] = {}  # {target_name: relation_type}

    def add_relation(self, target: str, relation_type: str) -> None:
        """Add a relationship edge. relation_type: 羁绊/敌对/同盟/师徒/爱慕/利用"""
        self.relations[target] = relation_type

    @property
    def arc_summary(self) -> str:
        """One-line arc description."""
        if not self.arc_start and not self.arc_end:
            return "(未定义)"
        return f"{self.arc_start} → {self.arc_turn} → {self.arc_end}"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "role": self.role,
            "arc": self.arc_summary,
            "faction": self.faction,
            "ability": self.ability,
            "flaw": self.flaw,
            "relations": self.relations,
        }


class CharacterGraph:
    """Tracks all characters and their relationships."""

    def __init__(self):
        self.nodes: dict[str, CharacterNode] = {}

    def add_node(self, node: CharacterNode) -> None:
        self.nodes[node.name] = node

    def add_edge(self, from_name: str, to_name: str, relation_type: str) -> None:
        if from_name in self.nodes:
            self.nodes[from_name].add_relation(to_name, relation_type)

    def build_matrix(self) -> list[list[str]]:
        """Generate relationship matrix: rows=from, cols=to, cells=relation."""
        names = list(self.nodes.keys())
        if not names:
            return []
        header = [""] + names
        rows = [header]
        for a_name in names:
            node = self.nodes[a_name]
            row = [a_name]
            for b_name in names:
                row.append(node.relations.get(b_name, "-"))
            rows.append(row)
        return rows

    def find_by_role(self, role: str) -> list[CharacterNode]:
        return [n for n in self.nodes.values() if n.role == role]

    def validate(self) -> list[str]:
        """Return list of warnings (e.g., isolated characters, missing arcs)."""
        warnings = []
        if not self.find_by_role("protagonist"):
            warnings.append("[WARN] 无主角节点")
        isolated = [n.name for n in self.nodes.values() if not n.relations]
        if isolated:
            warnings.append(f"[WARN] 孤立角色(无关系): {isolated}")
        no_arc = [n.name for n in self.nodes.values() if not n.arc_start]
        if no_arc:
            warnings.append(f"[WARN] 无弧光定义: {no_arc}")
        return warnings

    def to_markdown(self) -> str:
        """Render full character graph as markdown."""
        lines = ["# 角色关系图谱\n"]
        if not self.nodes:
            lines.append("(无角色)\n")
            return "\n".join(lines)

        # Character cards
        for node in self.nodes.values():
            lines.append(f"## {node.name} [{node.role}]")
            lines.append(f"- **阵营**: {node.faction or '(未定义)'}")
            lines.append(f"- **能力**: {node.ability or '(未定义)'}")
            lines.append(f"- **缺陷**: {node.flaw or '(未定义)'}")
            lines.append(f"- **弧光**: {node.arc_summary}")
            if node.relations:
                rels = ", ".join(f"{t}({r})" for t, r in node.relations.items())
                lines.append(f"- **关系**: {rels}")
            lines.append("")

        # Relationship matrix
        lines.append("## 关系矩阵\n")
        matrix = self.build_matrix()
        if matrix:
            # Format as markdown table
            header = matrix[0]
            lines.append("| " + " | ".join(header) + " |")
            lines.append("|" + "|".join(["---"] * len(header)) + "|")
            for row in matrix[1:]:
                lines.append("| " + " | ".join(row) + " |")

        return "\n".join(lines)


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
# v2: 势力数据加载
# ============================================================

def _find_project_root() -> Path:
    """Find project root by locating config.yaml."""
    p = Path(__file__).resolve().parent
    for _ in range(5):
        if (p / "config.yaml").exists():
            return p
        p = p.parent
    return Path(__file__).resolve().parent.parent


def load_faction_guidance(genre: str = "末世") -> dict:
    """Load conflict type distribution from creative_guidance JSON.

    Returns dict with keys: dominant_conflicts (list), arc_distribution (dict).
    """
    root = _find_project_root()
    guidance_path = root / "data" / "reports" / genre / "creative_guidance" / f"{genre}_创作指导.json"

    if not guidance_path.exists():
        return {}

    try:
        data = json.loads(guidance_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return {}

    wb = data.get("worldbuilding", {})
    return {
        "dominant_conflicts": wb.get("dominant_conflict_types", []),
        "arc_distribution": wb.get("arc_distribution", {}),
        "guidance": wb.get("guidance", []),
    }


def get_relation_types() -> list[str]:
    """Standard relationship types for web novels."""
    return ["羁绊", "敌对", "同盟", "师徒", "爱慕", "利用", "竞争", "守护", "背叛", "崇拜"]


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

    # v2: also save graph template and faction guidance
    faction_data = load_faction_guidance()
    graph_path = chars_path.parent / "character_graph.md"
    graph_lines = [
        "# 角色关系图谱 (模板)\n",
        "> 交互式角色设计完成后，在此填写角色节点和关系。\n",
        "> 关系类型: " + ", ".join(get_relation_types()) + "\n",
    ]
    if faction_data.get("dominant_conflicts"):
        graph_lines.append("## 题材冲突类型参考 (来自30本精品统计)\n")
        for c in faction_data["dominant_conflicts"]:
            graph_lines.append(f"- **{c['type']}**: {c['pct']}%")
        graph_lines.append("")
    graph_path.write_text("\n".join(graph_lines), encoding="utf-8")

    print(f"\n{'=' * 60}")
    print(f"  [OK] Characters saved to assets/canon/characters.md")
    print(f"  [OK] Graph template: assets/canon/character_graph.md")
    if faction_data:
        conflicts = [c['type'] for c in faction_data.get('dominant_conflicts', [])[:3]]
        print(f"  [OK] Faction guidance: {', '.join(conflicts)}")
    print(f"{'=' * 60}")
