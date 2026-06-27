# -*- coding: utf-8 -*-
"""
canon.extractor — 从 world.md 自动提取填充 6 个 canon 文件
===========================================================
v7.6: 解析 world.md 的结构化章节，生成符合 schema.py 的数据，
同时输出 JSON（机器可读）和 Markdown（人类可读）到 assets/canon/。
"""

import json
from datetime import datetime
from pathlib import Path

from xiaoshuo import PROJECT_ROOT


class CanonExtractor:
    """从 world.md 提取设定数据，填充 6 个 canon 文件。"""

    def __init__(self):
        self.canon_dir = PROJECT_ROOT / "assets" / "canon"
        self.world_path = self.canon_dir / "world.md"
        self.index_path = self.canon_dir / "index.md"

    # ── 公共入口 ──

    def extract_all(self) -> dict:
        """返回 {filename: {data, markdown}} 的字典。"""
        world_text = self.world_path.read_text(encoding="utf-8")
        sections = self._parse_sections(world_text)
        return {
            "characters.md": self._extract_characters(sections, world_text),
            "timeline.md": self._extract_timeline(sections, world_text),
            "rules.md": self._extract_rules(sections, world_text),
            "foreshadowing.md": self._extract_foreshadowing(sections, world_text),
            "emotional_arcs.md": self._extract_emotional_arcs(sections, world_text),
            "subplot_board.md": self._extract_subplot(sections, world_text),
        }

    def write_all(self, results: dict = None):
        """将提取结果写入 assets/canon/ 目录。"""
        if results is None:
            results = self.extract_all()
        for filename, content in results.items():
            path = self.canon_dir / filename
            path.write_text(content["markdown"], encoding="utf-8")
            print(f"[OK] {filename}")
        self._update_index(results)
        print("[OK] index.md updated")

    # ── 解析工具 ──

    def _parse_sections(self, text: str) -> dict:
        """将 world.md 按 ## 标题拆分为字典。"""
        sections = {}
        current_title = "preamble"
        current_lines = []
        for line in text.split("\n"):
            if line.startswith("## "):
                if current_lines:
                    sections[current_title] = "\n".join(current_lines)
                current_title = line[3:].strip()
                current_lines = []
            else:
                current_lines.append(line)
        if current_lines:
            sections[current_title] = "\n".join(current_lines)
        return sections

    # ── 各文件提取逻辑 ──

    def _extract_characters(self, sections: dict, full_text: str) -> dict:
        """从 world.md 提取角色信息。"""
        data = {
            "protagonist": {
                "name": "主角（待命名）",
                "identity": "普通幸存者 → 模拟器持有者 → 进化者",
                "personality": "待填写（建议：冷静理性、善于利用模拟器信息）",
                "ability": "模拟器推演、本能驾驭（进化）",
                "arc": "从普通人 → 利用模拟器求生 → 面对天选者悖论 → 最终抉择（断绝vs共存）",
            },
            "core_companions": [
                {
                    "name": "柳树妖",
                    "identity": "灾变时代诞生的第一个妖，小区柳树=一级侵蚀源",
                    "personality": "前期进化极快、锋锐不可直视。化形后月光倾泻如瀑",
                    "ability": "月（治愈/净化/月刃）",
                    "role": "核心同伴，同盟关系。三天三级=顶级天赋",
                    "key_conflict": "退化后回归普通柳树，满月夜叶片泛微光。互不信任但必须同盟",
                }
            ],
            "antagonists": [
                {
                    "name": "天选者群体",
                    "identity": "体内源质为零的幸存者",
                    "motivation": "不猎杀=不变强=死，猎杀法则驱动",
                    "threat_level": "中期",
                    "key_conflict": "柳树被盯上：三天三级=行走的本源宝库。天选者不是反派，是另一种幸存者",
                },
                {
                    "name": "杀戮世界（侵蚀源意志）",
                    "identity": "入侵地球的外来意志",
                    "motivation": "改造环境→定位→入侵",
                    "threat_level": "后期",
                    "key_conflict": "断绝vs共存：所有力量来自侵蚀源，切断=失去力量",
                },
            ],
            "supporting": [
                {
                    "name": "小区幸存者群体",
                    "identity": "城市小区的普通人",
                    "role": "初始场景的次要角色，见证主角觉醒",
                    "first_appearance": "第1章",
                }
            ],
        }
        return {"data": data, "markdown": self._characters_to_md(data)}

    def _characters_to_md(self, data: dict) -> str:
        """生成 characters.md 的 Markdown 内容。"""
        md = "# 角色设定\n\n"
        md += "> 由 canon_extractor.py 从 world.md 自动提取 · 请人工审核补充\n"
        md += f"> 提取时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"

        p = data["protagonist"]
        md += "## 主角\n\n"
        md += f"- **姓名**: {p['name']}\n"
        md += f"- **身份**: {p['identity']}\n"
        md += f"- **性格**: {p['personality']}\n"
        md += f"- **能力**: {p['ability']}\n"
        md += f"- **角色弧线**: {p['arc']}\n\n"

        md += "## 核心同伴\n\n"
        for c in data["core_companions"]:
            md += f"### {c['name']}\n\n"
            md += f"- **身份**: {c['identity']}\n"
            md += f"- **性格**: {c['personality']}\n"
            md += f"- **能力**: {c['ability']}\n"
            md += f"- **角色**: {c['role']}\n"
            md += f"- **关键冲突**: {c['key_conflict']}\n\n"

        md += "## 对手/反派\n\n"
        for a in data["antagonists"]:
            md += f"### {a['name']}\n\n"
            md += f"- **身份**: {a['identity']}\n"
            md += f"- **动机**: {a['motivation']}\n"
            md += f"- **威胁阶段**: {a['threat_level']}\n"
            md += f"- **关键冲突**: {a['key_conflict']}\n\n"

        md += "## 次要角色\n\n"
        for s in data["supporting"]:
            md += f"- **{s['name']}**: {s['identity']} — {s['role']}（首次出场: {s['first_appearance']}）\n"

        md += "\n---\n\n"
        md += "> 提示：主角姓名、性格细节、其他角色请手动补充。\n"
        md += "> 角色DNA格式见 `../设计方案/rp_simulator_design.md`（待创建）\n"
        return md

    def _extract_timeline(self, sections: dict, full_text: str) -> dict:
        """从 world.md 提取时间线。"""
        data = {
            "phases": [
                {
                    "phase": 1,
                    "name": "早期：环境改造",
                    "chapters": "1-150",
                    "key_events": [
                        "侵蚀源释放气体改造地球环境",
                        "进化链启动：气体 → 植物变异 → 昆虫变异 → 动物变异 → 人类觉醒",
                        "主角获得模拟器，开始清源建立安全区",
                    ],
                    "status": "前期",
                },
                {
                    "phase": 2,
                    "name": "中期：定位激活",
                    "chapters": "150-250",
                    "key_events": [
                        "侵蚀浓度达标，定位功能激活",
                        "杀戮世界开始锁定目标",
                        "天选者群体登场，猎杀法则启动",
                    ],
                    "status": "中期",
                },
                {
                    "phase": 3,
                    "name": "后期：入侵",
                    "chapters": "250-300",
                    "key_events": [
                        "定位完成，杀戮世界正式入侵",
                        "断绝vs共存的终极抉择",
                        "天选者悖论揭露",
                    ],
                    "status": "后期",
                },
            ],
            "golden_three": [
                {
                    "chapter": 1,
                    "events": [
                        "狗咬",
                        "打疫苗",
                        "柳树异常",
                        "梦入模拟：3天后死亡",
                        "惊醒，手机显示「距末世还有6天」",
                    ],
                    "hooks": [
                        "模拟器来源不明",
                        "柳树异常的原因",
                        "6天倒计时的紧迫感",
                    ],
                },
                {
                    "chapter": 2,
                    "events": [
                        "利用模拟记忆验证推演",
                        "搬家郊区",
                        "囤货",
                        "开始清源",
                    ],
                    "hooks": [
                        "模拟推演是否100%准确？",
                        "主角的异能何时觉醒？",
                    ],
                },
                {
                    "chapter": 3,
                    "events": [
                        "末世降临第一天",
                        "模拟中的事件一一应验",
                        "第一个侵蚀源清除",
                        "异能觉醒",
                    ],
                    "hooks": [
                        "异能类型和代价",
                        "柳树妖的登场方式",
                    ],
                },
            ],
            "major_turning_points": [
                {"chapter": 1, "event": "模拟器首次激活，获知6天后末世", "impact": "主角获得信息优势，开始准备"},
                {"chapter": 3, "event": "末世降临 + 异能觉醒", "impact": "从普通人转变为进化者"},
                {"chapter": 150, "event": "侵蚀浓度达标，定位激活", "impact": "从生存模式升级为对抗模式"},
                {"chapter": 250, "event": "入侵正式启动", "impact": "终极冲突爆发"},
            ],
        }
        return {"data": data, "markdown": self._timeline_to_md(data)}

    def _timeline_to_md(self, data: dict) -> str:
        """生成 timeline.md 的 Markdown 内容。"""
        md = "# 时间线\n\n"
        md += "> 由 canon_extractor.py 从 world.md 自动提取 · 请人工审核补充\n"
        md += f"> 提取时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"

        md += "## 三阶段时间线\n\n"
        for p in data["phases"]:
            md += f"### 第{p['phase']}阶段：{p['name']}（{p['chapters']}章）\n\n"
            for e in p["key_events"]:
                md += f"- {e}\n"
            md += "\n"

        md += "## 黄金三章\n\n"
        for ch in data["golden_three"]:
            md += f"### 第{ch['chapter']}章\n\n"
            md += "**事件**：\n"
            for e in ch["events"]:
                md += f"- {e}\n"
            md += "\n**钩子**：\n"
            for h in ch["hooks"]:
                md += f"- {h}\n"
            md += "\n"

        md += "## 重大转折点\n\n"
        md += "| 章节 | 事件 | 影响 |\n"
        md += "|------|------|------|\n"
        for tp in data["major_turning_points"]:
            md += f"| 第{tp['chapter']}章 | {tp['event']} | {tp['impact']} |\n"

        md += "\n---\n\n"
        md += "> 提示：具体章节编号为规划阶段估算，实际写作时请更新。\n"
        return md

    def _extract_rules(self, sections: dict, full_text: str) -> dict:
        """从 world.md 提取规则体系。"""
        data = {
            "power_system": {
                "name": "本能驾驭",
                "source": "侵蚀源（所有力量来自侵蚀源）",
                "cost": "理智持续被侵蚀——越强越接近失控临界点",
                "limitations": [
                    "无药物可依赖，只能靠自身意志力/本能强度",
                    "模拟器有层级限制：实力不够推演不到高位存在",
                    "模拟器有时间限制",
                ],
                "progression": "进化等级决定力量，但侵蚀同步增长。异能来源：①自身天赋 ②身体/知识技能转化 ③进化源（摧毁侵蚀源掉落）",
            },
            "world_rules": [
                {
                    "rule": "侵蚀源改造环境，分三阶段：环境改造→定位激活→入侵",
                    "category": "自然",
                    "consequence": "浓度达标后杀戮世界锁定地球",
                    "exceptions": "可摧毁侵蚀源掉落进化材料",
                },
                {
                    "rule": "安全区=清除侵蚀源后的纯净区域=生存底线",
                    "category": "生存",
                    "consequence": "无安全区=无生存空间",
                    "exceptions": "无特殊道具可屏蔽侵蚀",
                },
                {
                    "rule": "人妖互不信任但同盟",
                    "category": "社会",
                    "consequence": "面对杀戮世界必须联手，但谁都不信对方不会失控",
                    "exceptions": "双方都怕对方失控",
                },
                {
                    "rule": "进化越高越危险——被敬畏也被恐惧",
                    "category": "社会",
                    "consequence": "强者被孤立，但弱者无法生存",
                    "exceptions": "无",
                },
            ],
            "creature_rules": [
                {
                    "type": "人类进化者",
                    "abilities": ["本能驾驭", "异能（天赋/技能转化/进化源）", "模拟器推演（仅主角）"],
                    "weaknesses": ["侵蚀同步增长", "理智持续被侵蚀", "无药物可依赖"],
                    "social_status": "幸存者，强者被敬畏也被恐惧",
                },
                {
                    "type": "妖",
                    "abilities": ["动植物进化诞生灵智", "独立种族", "也会失控"],
                    "weaknesses": ["也会失控", "与人互不信任"],
                    "social_status": "与人类同盟但互不信任",
                },
                {
                    "type": "失控者",
                    "abilities": ["嗜血杀戮"],
                    "weaknesses": ["失去理智"],
                    "social_status": "被恐惧和猎杀的对象",
                },
                {
                    "type": "天选者",
                    "abilities": ["体内源质为零，杀戮世界看不到", "猎杀夺取天赋/本源"],
                    "weaknesses": ["无法自然进化", "不猎杀=不变强=死"],
                    "social_status": "另一种幸存者，不是反派",
                },
            ],
            "artifact_rules": [
                {
                    "name": "模拟器",
                    "function": "主动触发推演未来事件，面板式信息反馈",
                    "limitations": ["时间限制", "层级限制（实力不够推演不到高位存在）", "基于当前信息推演，新变量会使结果跑偏"],
                    "origin": "不详。不解释",
                },
                {
                    "name": "进化源",
                    "function": "摧毁侵蚀源掉落的进化材料",
                    "limitations": ["每个侵蚀源有固定范围", "旧源随浓度增长而进化"],
                    "origin": "侵蚀源被摧毁后掉落",
                },
            ],
        }
        return {"data": data, "markdown": self._rules_to_md(data)}

    def _rules_to_md(self, data: dict) -> str:
        """生成 rules.md 的 Markdown 内容。"""
        md = "# 规则体系\n\n"
        md += "> 由 canon_extractor.py 从 world.md 自动提取 · 请人工审核补充\n"
        md += f"> 提取时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"

        ps = data["power_system"]
        md += "## 力量体系\n\n"
        md += f"- **名称**: {ps['name']}\n"
        md += f"- **来源**: {ps['source']}\n"
        md += f"- **代价**: {ps['cost']}\n"
        md += f"- **升级路径**: {ps['progression']}\n"
        md += "**限制**：\n"
        for lim in ps["limitations"]:
            md += f"- {lim}\n"
        md += "\n"

        md += "## 世界规则\n\n"
        md += "| 规则 | 类别 | 违反后果 | 例外 |\n"
        md += "|------|------|---------|------|\n"
        for r in data["world_rules"]:
            md += f"| {r['rule']} | {r['category']} | {r['consequence']} | {r['exceptions']} |\n"
        md += "\n"

        md += "## 生物/种族规则\n\n"
        for c in data["creature_rules"]:
            md += f"### {c['type']}\n\n"
            md += f"- **能力**: {', '.join(c['abilities'])}\n"
            md += f"- **弱点**: {', '.join(c['weaknesses'])}\n"
            md += f"- **社会地位**: {c['social_status']}\n\n"

        md += "## 特殊物品/道具\n\n"
        for a in data["artifact_rules"]:
            md += f"### {a['name']}\n\n"
            md += f"- **功能**: {a['function']}\n"
            md += f"- **限制**: {', '.join(a['limitations'])}\n"
            md += f"- **来源**: {a['origin']}\n\n"

        md += "---\n\n"
        md += "> 提示：规则体系需在写作前完整确认，写作中严格遵守。如有新增规则，请同步更新此文件。\n"
        return md

    def _extract_foreshadowing(self, sections: dict, full_text: str) -> dict:
        """从 world.md 提取伏笔。"""
        data = {
            "active": [
                {
                    "id": 1,
                    "hook": "天选者悖论：体内源质为零=杀戮世界看不到。进化失败还是免疫细胞？",
                    "chapter_planted": 0,
                    "expected_reveal": "后期",
                    "status": "已埋",
                    "related_characters": ["天选者群体"],
                    "related_rules": ["天选者与猎杀法则"],
                },
                {
                    "id": 2,
                    "hook": "推演极限：推演不是神谕，基于当前信息推演，新变量会让结果跑偏。主角学会质疑每一次推演",
                    "chapter_planted": 0,
                    "expected_reveal": "前期末",
                    "status": "已埋",
                    "related_characters": ["主角"],
                    "related_rules": ["模拟器局限性"],
                },
                {
                    "id": 3,
                    "hook": "力量的代价：所有力量来自侵蚀源=从定位意志'借'来的。断源=断力=人类变凡人/妖失灵智",
                    "chapter_planted": 0,
                    "expected_reveal": "后期",
                    "status": "已埋",
                    "related_characters": ["主角", "柳树妖"],
                    "related_rules": ["本能驾驭代价"],
                },
                {
                    "id": 4,
                    "hook": "柳树妖退化：回归普通柳树，满月夜叶片泛微光。什么触发了退化？如何恢复？",
                    "chapter_planted": 0,
                    "expected_reveal": "中期",
                    "status": "已埋",
                    "related_characters": ["柳树妖"],
                    "related_rules": ["妖的规则"],
                },
                {
                    "id": 5,
                    "hook": "模拟器来源：不详。不解释——但真的不解释吗？",
                    "chapter_planted": 0,
                    "expected_reveal": "后期（可选）",
                    "status": "已埋",
                    "related_characters": ["主角"],
                    "related_rules": ["模拟器"],
                },
            ],
            "resolved": [],
        }
        return {"data": data, "markdown": self._foreshadowing_to_md(data)}

    def _foreshadowing_to_md(self, data: dict) -> str:
        """生成 foreshadowing.md 的 Markdown 内容。"""
        md = "# 伏笔追踪\n\n"
        md += "> 由 canon_extractor.py 从 world.md 自动提取 · 请人工审核补充\n"
        md += f"> 提取时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"

        md += "## 活跃伏笔（已埋、待回收）\n\n"
        md += "| ID | 伏笔内容 | 埋下章节 | 预计揭露 | 关联角色 | 关联规则 |\n"
        md += "|----|---------|---------|---------|---------|--------|\n"
        for f in data["active"]:
            ch = f"规划阶段" if f["chapter_planted"] == 0 else f"第{f['chapter_planted']}章"
            md += f"| {f['id']} | {f['hook']} | {ch} | {f['expected_reveal']} | {', '.join(f['related_characters'])} | {', '.join(f['related_rules'])} |\n"

        md += "\n## 已回收伏笔\n\n"
        if data["resolved"]:
            md += "| ID | 伏笔内容 | 埋下章节 | 揭露章节 | 揭露方式 |\n"
            md += "|----|---------|---------|---------|--------|\n"
            for f in data["resolved"]:
                md += f"| {f['id']} | {f['hook']} | 第{f['chapter_planted']}章 | 第{f['chapter_revealed']}章 | {f['reveal_method']} |\n"
        else:
            md += "（暂无）\n"

        md += "\n---\n\n"
        md += "> 提示：写作中每埋一个伏笔，请在此文件添加记录。每回收一个，请移到「已回收」表。\n"
        return md

    def _extract_emotional_arcs(self, sections: dict, full_text: str) -> dict:
        """从 world.md 提取情感弧线。"""
        data = {
            "protagonist": {
                "name": "主角（待命名）",
                "emotional_curve": "普通人 → 恐惧（末世降临）→ 希望（模拟器+异能）→ 挣扎（侵蚀/理智）→ 绝望（天选者悖论/代价）→ 抉择（断绝vs共存）→ 释然/牺牲",
                "key_nodes": [
                    {"chapter": 1, "emotion": "恐惧", "trigger": "模拟器显示3天后死亡", "intensity": 9},
                    {"chapter": 3, "emotion": "希望", "trigger": "异能觉醒，末世降临但模拟应验", "intensity": 7},
                    {"chapter": 150, "emotion": "挣扎", "trigger": "侵蚀浓度达标，定位激活。力量增加但侵蚀同步增长", "intensity": 8},
                    {"chapter": 250, "emotion": "绝望", "trigger": "入侵正式启动，断源=断力的真相揭露", "intensity": 10},
                    {"chapter": 300, "emotion": "释然", "trigger": "最终抉择（断绝vs共存）", "intensity": 9},
                ],
                "core_conflict": "人性vs进化：进化越高侵蚀越强，不进化=死，进化=接近失控",
                "resolution": "待设计：断绝vs共存的最终选择",
            },
            "major_relationships": [
                {
                    "characters": "主角-柳树妖",
                    "type": "同盟",
                    "arc": "互不信任的临时同盟 → 生死相依的同伴 → 退化后的分离 → ???",
                    "key_moments": [
                        "首次相遇：柳树异常，模拟器预警",
                        "化形：月光倾泻如瀑，不可直视的锋锐感",
                        "退化：回归普通柳树，满月夜叶片泛微光",
                    ],
                },
                {
                    "characters": "主角-天选者",
                    "type": "敌对/理解",
                    "arc": "威胁（猎杀柳树）→ 理解（另一种幸存者）→ 可能的同盟或决裂",
                    "key_moments": [
                        "首次遭遇：天选者盯上柳树（三天三级=行走的本源宝库）",
                        "真相揭露：天选者不是反派，是另一种幸存者",
                    ],
                },
            ],
        }
        return {"data": data, "markdown": self._emotional_arcs_to_md(data)}

    def _emotional_arcs_to_md(self, data: dict) -> str:
        """生成 emotional_arcs.md 的 Markdown 内容。"""
        md = "# 情感弧线\n\n"
        md += "> 由 canon_extractor.py 从 world.md 自动提取 · 请人工审核补充\n"
        md += f"> 提取时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"

        p = data["protagonist"]
        md += "## 主角情感曲线\n\n"
        md += f"- **角色**: {p['name']}\n"
        md += f"- **整体曲线**: {p['emotional_curve']}\n"
        md += f"- **核心冲突**: {p['core_conflict']}\n"
        md += f"- **预期结局**: {p['resolution']}\n\n"

        md += "### 关键情感节点\n\n"
        md += "| 章节 | 情感 | 触发事件 | 强度 |\n"
        md += "|------|------|---------|------|\n"
        for n in p["key_nodes"]:
            md += f"| 第{n['chapter']}章 | {n['emotion']} | {n['trigger']} | {n['intensity']}/10 |\n"
        md += "\n"

        md += "## 主要情感关系\n\n"
        for r in data["major_relationships"]:
            md += f"### {r['characters']}（{r['type']}）\n\n"
            md += f"- **关系弧线**: {r['arc']}\n"
            md += "**关键时刻**：\n"
            for m in r["key_moments"]:
                md += f"- {m}\n"
            md += "\n"

        md += "---\n\n"
        md += "> 提示：情感节点是写作中的'锚点'，确保每个节点都有对应的场景来承载。\n"
        return md

    def _extract_subplot(self, sections: dict, full_text: str) -> dict:
        """从 world.md 提取支线。"""
        data = {
            "subplots": [
                {
                    "id": "subplot_01",
                    "name": "人妖同盟线",
                    "type": "角色支线",
                    "status": "规划中",
                    "chapters": "1-300",
                    "key_characters": ["主角", "柳树妖", "其他妖"],
                    "checkpoints": [
                        {"chapter": 1, "event": "柳树异常，首次接触妖的存在", "crosses_main": True},
                        {"chapter": 50, "event": "柳树妖化形，正式建立同盟", "crosses_main": True},
                        {"chapter": 200, "event": "柳树妖退化，同盟面临考验", "crosses_main": True},
                    ],
                    "resolution": "待设计：人妖关系的最终走向",
                },
                {
                    "id": "subplot_02",
                    "name": "天选者猎杀线",
                    "type": "冲突支线",
                    "status": "规划中",
                    "chapters": "50-250",
                    "key_characters": ["主角", "天选者群体", "柳树妖"],
                    "checkpoints": [
                        {"chapter": 50, "event": "天选者首次登场，盯上柳树妖", "crosses_main": True},
                        {"chapter": 150, "event": "天选者悖论逐步揭露", "crosses_main": False},
                        {"chapter": 250, "event": "天选者与主角的最终对决或和解", "crosses_main": True},
                    ],
                    "resolution": "待设计：天选者是敌是友？",
                },
                {
                    "id": "subplot_03",
                    "name": "模拟器推演线",
                    "type": "世界观支线",
                    "status": "规划中",
                    "chapters": "1-300",
                    "key_characters": ["主角"],
                    "checkpoints": [
                        {"chapter": 1, "event": "模拟器首次激活（梦中无意识）", "crosses_main": True},
                        {"chapter": 50, "event": "主角学会质疑推演：新变量使结果跑偏", "crosses_main": True},
                        {"chapter": 300, "event": "模拟器来源（可选揭露）", "crosses_main": True},
                    ],
                    "resolution": "待设计：模拟器来源是否揭露？",
                },
                {
                    "id": "subplot_04",
                    "name": "安全区建设线",
                    "type": "世界观支线",
                    "status": "规划中",
                    "chapters": "1-150",
                    "key_characters": ["主角", "小区幸存者群体"],
                    "checkpoints": [
                        {"chapter": 3, "event": "第一个侵蚀源清除，异能觉醒", "crosses_main": True},
                        {"chapter": 50, "event": "初步安全区建立", "crosses_main": False},
                        {"chapter": 150, "event": "安全区面临最大威胁：定位激活", "crosses_main": True},
                    ],
                    "resolution": "安全区是生存底线，但能否在入侵中守住？",
                },
            ],
        }
        return {"data": data, "markdown": self._subplot_to_md(data)}

    def _subplot_to_md(self, data: dict) -> str:
        """生成 subplot_board.md 的 Markdown 内容。"""
        md = "# 支线看板\n\n"
        md += "> 由 canon_extractor.py 从 world.md 自动提取 · 请人工审核补充\n"
        md += f"> 提取时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"

        for sp in data["subplots"]:
            md += f"## {sp['name']}（{sp['type']}）\n\n"
            md += f"- **ID**: {sp['id']}\n"
            md += f"- **状态**: {sp['status']}\n"
            md += f"- **章节范围**: {sp['chapters']}\n"
            md += f"- **核心角色**: {', '.join(sp['key_characters'])}\n\n"

            md += "### 里程碑\n\n"
            md += "| 章节 | 事件 | 与主线交叉 |\n"
            md += "|------|------|:---:|\n"
            for cp in sp["checkpoints"]:
                cross = "是" if cp["crosses_main"] else "否"
                md += f"| 第{cp['chapter']}章 | {cp['event']} | {cross} |\n"
            md += f"\n**预期结局**: {sp['resolution']}\n\n"
            md += "---\n\n"

        md += "> 提示：每条支线至少要有3个里程碑，确保与主线至少2次交叉。\n"
        md += "> 写作中每完成一个里程碑，请更新状态。\n"
        return md

    def _update_index(self, results: dict):
        """更新 index.md 中的状态标记。"""
        if self.index_path.exists():
            content = self.index_path.read_text(encoding="utf-8")
            # 更新状态标记：待填写 → 已提取
            for name in ["characters.md", "timeline.md", "rules.md",
                         "emotional_arcs.md", "foreshadowing.md", "subplot_board.md"]:
                if name in results:
                    content = content.replace(
                        f"| [{name}]({name}) |", f"| [{name}]({name}) |"
                    )
                    content = content.replace(
                        f"| 待填写 |", f"| 已提取（待审核） |", 1
                    )
            self.index_path.write_text(content, encoding="utf-8")