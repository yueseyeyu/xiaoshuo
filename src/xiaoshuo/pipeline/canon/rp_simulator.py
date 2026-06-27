# -*- coding: utf-8 -*-
"""
rp_simulator — 角色入戏推演引擎 v7.6
=====================================
基于 characters.md 的角色 DNA，通过 LLM API 进行角色第一人称推演。
用于在写作前"试戏"——验证角色反应的合理性、发现自然的情节走向。

用法:
    from xiaoshuo.pipeline.canon.rp_simulator import RPSimulator
    sim = RPSimulator()
    result = sim.simulate_scene(
        character="柳树妖",
        scene={"time": "拍卖会前", "location": "贵宾室", "goal": "保护主角"},
        opponent={"name": "反派", "action": "把玩玉佩"},
    )
    print(result["inner_monologue"])
    print(result["first_line"])
"""

from pathlib import Path

from xiaoshuo import PROJECT_ROOT


# ── 角色 DNA 格式 ──

CHARACTER_DNA_TEMPLATE = {
    "name": "",
    "voice_fingerprint": {  # 语音指纹
        "catchphrase": "",  # 口头禅
        "sentence_style": "",  # 句式习惯（短句/长句/反问）
        "emotion_markers": "",  # 情绪标记
    },
    "psychological_model": {  # 心理模型
        "core_fear": "",  # 核心恐惧
        "defense_mechanism": "",  # 防御机制
        "current_desire": {"surface": "", "deep": ""},  # 表层欲望 / 深层欲望
    },
    "interaction_rhythm": {  # v7.7: 互动节奏（从 Kimi 建议提取）
        "opening": "",  # 开场策略：被动观察/主动挑衅/暧昧试探
        "warming": "",  # 升温路径：身体接触从远端到近端（手→肩→颈）
        "climax": "",  # 峰值节奏：每N轮对话一个情感钩子
        "reservation_points": [],  # 留白点：在关键处切换视角/用环境描写替代直接叙述
    },
    "memory_loader": [],  # 已加载记忆（关键事件回顾）
    "relationship_map": {},  # 与其他角色的关系
}


class LayeredMemory:
    """v7.7: 分层记忆管理器。

    三层架构，总常驻约 6K tokens，适配 8GB 显存：
    - 核心层（~3K）: 角色DNA + 世界观规则，始终保留
    - 摘要层（~2K）: 最近 N 个场景摘要，由 LLM 定期生成
    - 原始层（~1K）: 最近 3 轮原始对话，动态加载

    用法:
        mem = LayeredMemory(max_summaries=3, max_raw_rounds=3)
        mem.set_core(character_dna, world_rules="...")
        mem.add_raw_round("我慢慢靠近她...", "她后退一步，嘴角却微微上扬...")
        mem.add_summary("第1-10轮：主角与魅魔达成交易，但双方都隐藏了真实意图")
        context = mem.build_context()
    """

    def __init__(self, max_summaries: int = 3, max_raw_rounds: int = 3):
        self.core_layer = {"character_dna": None, "world_rules": ""}
        self.summaries = []  # [(summary_text, scene_id), ...]
        self.max_summaries = max_summaries
        self.raw_rounds = []  # [{"user": "...", "assistant": "..."}, ...]
        self.max_raw_rounds = max_raw_rounds

    def set_core(self, character_dna: dict, world_rules: str = ""):
        """设置核心层（角色DNA + 世界观规则）。"""
        self.core_layer["character_dna"] = character_dna
        self.core_layer["world_rules"] = world_rules

    def add_summary(self, summary_text: str, scene_id: str = ""):
        """添加场景摘要到摘要层，自动淘汰旧摘要。"""
        self.summaries.append((summary_text, scene_id))
        if len(self.summaries) > self.max_summaries:
            self.summaries = self.summaries[-self.max_summaries:]

    def add_raw_round(self, user_msg: str, assistant_msg: str):
        """添加一轮原始对话。"""
        self.raw_rounds.append({"user": user_msg, "assistant": assistant_msg})
        if len(self.raw_rounds) > self.max_raw_rounds:
            self.raw_rounds = self.raw_rounds[-self.max_raw_rounds:]

    def build_context(self) -> str:
        """构建分层记忆上下文，返回拼接后的 prompt 片段。

        Returns:
            可直接注入 system prompt 的文本块。
        """
        parts = []

        # 核心层：世界观规则
        if self.core_layer.get("world_rules"):
            parts.append(f"[世界观规则]\n{self.core_layer['world_rules']}")

        # 摘要层：历史场景摘要
        if self.summaries:
            summaries_text = "\n".join(
                f"- [{sid}] {txt}" if sid else f"- {txt}"
                for txt, sid in self.summaries
            )
            parts.append(f"[历史摘要]\n{summaries_text}")

        # 原始层：最近对话
        if self.raw_rounds:
            raw_text = []
            for i, r in enumerate(self.raw_rounds, 1):
                raw_text.append(f"第{i}轮:\n  用户: {r['user']}\n  角色: {r['assistant']}")
            parts.append(f"[最近对话]\n" + "\n".join(raw_text))

        return "\n\n".join(parts)

    def clear(self):
        """清空摘要层和原始层（保留核心层）。"""
        self.summaries = []
        self.raw_rounds = []

    def to_dict(self) -> dict:
        """导出为可序列化字典，用于持久化。"""
        return {
            "core_world_rules": self.core_layer.get("world_rules", ""),
            "summaries": self.summaries,
            "raw_rounds": self.raw_rounds,
        }

    @classmethod
    def from_dict(cls, data: dict, max_summaries: int = 3, max_raw_rounds: int = 3) -> "LayeredMemory":
        """从字典恢复 LayeredMemory 实例。"""
        mem = cls(max_summaries=max_summaries, max_raw_rounds=max_raw_rounds)
        mem.core_layer["world_rules"] = data.get("core_world_rules", "")
        mem.summaries = data.get("summaries", [])
        mem.raw_rounds = data.get("raw_rounds", [])
        return mem


class RPSimulator:
    """角色入戏推演引擎。

    注意：本模块不直接调用 LLM API（由 model_orchestrator 统一管理）。
    它负责构造 prompt 和解析输出，实际 API 调用由调用方处理。
    """

    def __init__(self):
        self.canon_dir = PROJECT_ROOT / "assets" / "canon"
        self.characters_path = self.canon_dir / "characters.md"

    # ── 公共 API ──

    def build_dna_from_canon(self, character_name: str) -> dict:
        """从 characters.md 提取角色 DNA。"""
        if not self.characters_path.exists():
            return {"error": "characters.md not found"}

        text = self.characters_path.read_text(encoding="utf-8")
        dna = dict(CHARACTER_DNA_TEMPLATE)
        dna["name"] = character_name

        # 解析 characters.md 的角色信息
        sections = self._parse_md_sections(text)
        char_info = self._find_character_section(sections, character_name)

        if char_info:
            dna["voice_fingerprint"]["catchphrase"] = char_info.get("personality", "")[:50]
            dna["voice_fingerprint"]["sentence_style"] = "待填写"
            dna["voice_fingerprint"]["emotion_markers"] = "待填写"
            dna["psychological_model"]["core_fear"] = "待填写"
            dna["psychological_model"]["defense_mechanism"] = "待填写"
            dna["psychological_model"]["current_desire"]["surface"] = char_info.get("role", "待填写")
            dna["psychological_model"]["current_desire"]["deep"] = char_info.get("key_conflict", "待填写")
            dna["interaction_rhythm"]["opening"] = "待填写"
            dna["interaction_rhythm"]["warming"] = "待填写"
            dna["interaction_rhythm"]["climax"] = "待填写"
            dna["interaction_rhythm"]["reservation_points"] = []

        return dna

    def build_prompt(self, character_dna: dict, scene: dict, opponent: dict = None) -> str:
        """构造角色入戏 prompt。

        Args:
            character_dna: 角色 DNA 字典
            scene: {"time": "...", "location": "...", "goal": "..."}
            opponent: {"name": "...", "action": "..."} (可选)

        Returns:
            完整的 system + user prompt 字符串
        """
        vf = character_dna.get("voice_fingerprint", {})
        pm = character_dna.get("psychological_model", {})
        ir = character_dna.get("interaction_rhythm", {})
        memories = character_dna.get("memory_loader", [])

        system = f"""[角色入戏协议]
你现在是《末日模拟器》中的角色：[{character_dna['name']}]。
以下是你的完整DNA，必须严格遵守：

[语音指纹]
- 口头禅：{vf.get('catchphrase', '待设定')}
- 句式习惯：{vf.get('sentence_style', '待设定')}
- 情绪标记：{vf.get('emotion_markers', '待设定')}

[心理模型]
- 核心恐惧：{pm.get('core_fear', '待设定')}
- 防御机制：{pm.get('defense_mechanism', '待设定')}
- 当前欲望：{pm.get('current_desire', {}).get('deep', '待设定')}（深层）/ {pm.get('current_desire', {}).get('surface', '待设定')}（表层）

[互动节奏]
- 开场策略：{ir.get('opening', '待设定')}
- 升温路径：{ir.get('warming', '待设定')}
- 峰值节奏：{ir.get('climax', '待设定')}
- 留白点：{', '.join(ir.get('reservation_points', [])) if ir.get('reservation_points') else '待设定'}

[记忆加载]"""

        for m in memories[:5]:
            system += f"\n- {m}"

        user = f"""
[场景设定]
时间：{scene.get('time', '未知')}
地点：{scene.get('location', '未知')}
你的目标：{scene.get('goal', '生存')}"""

        if opponent:
            user += f"""
对手：[{opponent.get('name', '未知')}]，正在 {opponent.get('action', '')}"""

        user += """

[输出要求]
请完全以该角色的第一人称视角，输出：
1. 内心独白（20-50字）
2. 下意识动作/微表情
3. 开口说的第一句话（必须符合语音指纹）

禁止输出分析、总结、建议。你就是角色本人。"""

        return system + "\n" + user

    def build_prompt_with_memory(self, character_dna: dict, scene: dict,
                                  memory: LayeredMemory, opponent: dict = None) -> str:
        """v7.7: 构造带分层记忆的角色入戏 prompt。

        在 build_prompt() 的基础上，将 LayeredMemory 的三层记忆
        注入 system prompt，实现长对话中的角色一致性。

        Args:
            character_dna: 角色 DNA 字典
            scene: 场景设定
            memory: 分层记忆实例
            opponent: 对手设定（可选）

        Returns:
            完整的 prompt 字符串（含记忆上下文）
        """
        base_prompt = self.build_prompt(character_dna, scene, opponent)
        memory_context = memory.build_context()

        if memory_context:
            # 将记忆上下文插入到 system prompt 的 [记忆加载] 之后
            return base_prompt.replace("[输出要求]", f"{memory_context}\n\n[输出要求]")

        return base_prompt

    def parse_response(self, response: str) -> dict:
        """解析 LLM 返回的角色推演结果。

        Returns:
            {"inner_monologue": "...", "action": "...", "first_line": "...", "raw": "..."}
        """
        lines = response.strip().split("\n")

        inner = ""
        action = ""
        first_line = ""

        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith("1.") or "内心独白" in line:
                continue
            if line.startswith("2.") or "动作" in line or "微表情" in line:
                continue
            if line.startswith("3.") or "第一句话" in line:
                continue

            # 按内容特征分类
            if not inner and len(line) > 10:
                inner = line
            elif not action and inner:
                action = line
            elif not first_line and action:
                first_line = line

        return {
            "inner_monologue": inner,
            "action": action,
            "first_line": first_line,
            "raw": response,
        }

    def simulate_scene(self, character: str, scene: dict,
                       opponent: dict = None, llm_call=None) -> dict:
        """完整的单场景推演。

        Args:
            character: 角色名（需在 characters.md 中定义）
            scene: 场景设定
            opponent: 对手设定（可选）
            llm_call: 可调用对象，签名为 fn(prompt: str) -> str。
                      如果为 None，仅返回 prompt 而不实际调用。

        Returns:
            {"prompt": "...", "response": {...}, "error": None}
        """
        dna = self.build_dna_from_canon(character)
        if "error" in dna:
            return {"error": dna["error"], "prompt": None, "response": None}

        prompt = self.build_prompt(dna, scene, opponent)

        if llm_call is None:
            return {"prompt": prompt, "response": None, "error": None}

        try:
            raw_response = llm_call(prompt)
            parsed = self.parse_response(raw_response)
            return {"prompt": prompt, "response": parsed, "error": None}
        except Exception as e:
            return {"prompt": prompt, "response": None, "error": str(e)}

    def simulate_duel(self, char_a: str, char_b: str, scene: dict,
                      rounds: int = 3, llm_call=None) -> dict:
        """v7.7: 双角色对戏推演，含碰撞点检测。

        每轮分别推演 A 和 B 的反应，并在推演结束后检测：
        - 碰撞点（collision_points）：两个角色欲望/目标冲突最激烈的轮次
        - 冲突爆发轮（eruption_round）：冲突从隐性变为显性的轮次
        - 高光台词（hooks）：最有戏剧张力的台词

        Args:
            char_a: 角色A名
            char_b: 角色B名
            scene: 场景设定
            rounds: 互动轮数
            llm_call: 同 simulate_scene

        Returns:
            {"rounds": [...], "collision_points": [...], "eruption_round": int,
             "hooks": [...], "highlights": [...]}
        """
        results = []
        highlights = []
        hooks = []

        for r in range(rounds):
            # A 先反应
            result_a = self.simulate_scene(
                char_a, scene,
                opponent={"name": char_b, "action": "等待你的反应"},
                llm_call=llm_call
            )
            # B 反应
            a_last_line = ""
            if result_a.get("response") and result_a["response"].get("first_line"):
                a_last_line = result_a["response"]["first_line"]
            result_b = self.simulate_scene(
                char_b, scene,
                opponent={"name": char_a, "action": "刚才说了：" + a_last_line},
                llm_call=llm_call
            )

            round_result = {"round": r + 1, "A": result_a, "B": result_b}
            results.append(round_result)

            # 提取高光台词
            if result_a.get("response") and result_a["response"].get("first_line"):
                hooks.append({"round": r + 1, "character": char_a,
                              "line": result_a["response"]["first_line"]})
            if result_b.get("response") and result_b["response"].get("first_line"):
                hooks.append({"round": r + 1, "character": char_b,
                              "line": result_b["response"]["first_line"]})

        # v7.7: 碰撞点检测
        collision_points = self._detect_collisions(results, char_a, char_b)
        eruption_round = self._find_eruption_round(collision_points)

        return {
            "rounds": results,
            "collision_points": collision_points,
            "eruption_round": eruption_round,
            "hooks": hooks,
            "highlights": highlights,
        }

    # ── v7.7: 碰撞检测方法 ──

    def validate_against_written(self, character: str, scene: dict,
                                  chapter_text: str, llm_call=None) -> dict:
        """v7.7: 反向验证 — RP推演 vs 已写正文对比。

        用 AI 推演角色在场景中的反应，然后与作者已写的内容对比，
        评估 RP 推演质量，发现"角色反应可以更有层次"的地方。

        验证流程：
        1. RP 推演：AI 扮演角色，针对场景输出反应
        2. 文本提取：从 chapter_text 中提取该角色的实际对话/动作
        3. 对比分析：推演 vs 实际 → 差异度 + 建议

        Args:
            character: 角色名
            scene: 场景设定
            chapter_text: 已写章节文本（作者手写原文）
            llm_call: LLM 调用函数

        Returns:
            {
                "rp_simulation": {...},           # RP 推演结果
                "extracted_actual": {...},        # 从原文提取的角色实际反应
                "comparison": {
                    "similarity": float,          # 0-1 相似度
                    "divergence_points": [...],   # 分歧点
                    "rp_quality": "better/similar/worse",  # RP 推演质量 vs 原文
                    "suggestions": [...]          # 提升建议
                }
            }
        """
        # Step 1: RP 推演
        rp_result = self.simulate_scene(character, scene, llm_call=llm_call)

        # Step 2: 从原文提取角色的实际反应
        extracted = self._extract_character_reaction(chapter_text, character)

        # Step 3: 对比分析
        comparison = self._compare_rp_vs_written(rp_result, extracted)

        return {
            "rp_simulation": rp_result,
            "extracted_actual": extracted,
            "comparison": comparison,
        }

    def _extract_character_reaction(self, chapter_text: str, character: str) -> dict:
        """从章节文本中提取指定角色的对话和动作。

        使用启发式规则：
        - 引号内的内容 → 对话
        - 角色名 + 动作描述 → 动作

        Returns:
            {"lines": [...], "actions": [...], "inner_monologue": ""}
        """
        lines = []
        actions = []

        # 简单启发式：找包含角色名的行
        for line in chapter_text.split("\n"):
            line = line.strip()
            if character in line:
                # 提取引号内对话
                in_quote = False
                quote_start = 0
                for i, ch in enumerate(line):
                    if ch in "\u201c\u201d\"":
                        if not in_quote:
                            in_quote = True
                            quote_start = i + 1
                        else:
                            quote = line[quote_start:i]
                            if len(quote) > 2:
                                lines.append(quote)
                            in_quote = False
                # 整行作为动作候选
                if not lines or len(line) > len(lines[-1]) + 5:
                    actions.append(line)

        return {
            "lines": lines[:5],  # 最多 5 句
            "actions": actions[:3],
            "inner_monologue": "",  # 小说正文通常不直接写内心独白
        }

    def _compare_rp_vs_written(self, rp_result: dict, extracted: dict) -> dict:
        """对比 RP 推演结果与原文提取结果。

        比较维度：
        - 对话相似度：RP 推演的台词 vs 原文台词
        - 动作丰富度：RP 推演是否有原文没有的层次
        - 整体质量：RP 推演是否比原文更有层次感

        Returns:
            {"similarity": float, "divergence_points": [...],
             "rp_quality": str, "suggestions": [...]}
        """
        rp_response = rp_result.get("response", {}) or {}
        rp_line = rp_response.get("first_line", "")
        rp_action = rp_response.get("action", "")
        rp_inner = rp_response.get("inner_monologue", "")
        actual_lines = extracted.get("lines", [])
        actual_actions = extracted.get("actions", [])

        divergence_points = []
        suggestions = []

        # 1. 对话相似度（简单字符重叠率）
        similarity = 0.0
        if rp_line and actual_lines:
            rp_chars = set(rp_line)
            for al in actual_lines:
                actual_chars = set(al)
                if actual_chars:
                    overlap = len(rp_chars & actual_chars) / len(rp_chars | actual_chars)
                    similarity = max(similarity, overlap)
        elif rp_line and not actual_lines:
            divergence_points.append("RP 推演有台词，但原文中该角色未说话")
            suggestions.append("考虑在原文中增加该角色的台词，使场景更生动")
        elif not rp_line and actual_lines:
            divergence_points.append("原文有台词，但 RP 推演未生成对话")
            similarity = 0.5  # 存在差异，但不完全无效

        # 2. 动作丰富度对比
        if rp_action and not actual_actions:
            divergence_points.append("RP 推演有微表情/动作，但原文缺少动作描写")
            suggestions.append("在原文中增加角色的微表情和下意识动作，增强代入感")
        if rp_inner and not extracted.get("inner_monologue"):
            divergence_points.append("RP 推演有内心独白，原文无对应心理描写")
            suggestions.append("考虑在原文中增加角色的内心独白，让读者更理解角色动机")

        # 3. 整体质量判定
        rp_has_richness = bool(rp_line) and bool(rp_action) and bool(rp_inner)
        written_has_richness = bool(actual_lines) and bool(actual_actions)

        if rp_has_richness and not written_has_richness:
            rp_quality = "better"
            suggestions.append("RP 推演比原文更有层次：建议参考推演结果丰富原文")
        elif written_has_richness and not rp_has_richness:
            rp_quality = "worse"
            suggestions.append("RP 推演不如原文丰富：角色 DNA 可能需要细化")
        else:
            rp_quality = "similar"

        return {
            "similarity": round(similarity, 2),
            "divergence_points": divergence_points,
            "rp_quality": rp_quality,
            "suggestions": suggestions,
        }

    def _detect_collisions(self, rounds: list, char_a: str, char_b: str) -> list:
        """检测多轮对戏中的角色碰撞点。

        碰撞判定依据：
        - 双方 inner_monologue 包含对立情绪词（愤怒/恐惧/反抗/拒绝）
        - 双方 first_line 存在直接冲突（命令 vs 拒绝 / 威胁 vs 反击）
        - 双方 action 描述存在肢体对抗或空间压迫

        Returns:
            [{"round": N, "type": "emotional/physical/verbal", "description": "..."}, ...]
        """
        conflict_keywords = {
            "emotional": ["愤怒", "恐惧", "不甘", "屈辱", "怨恨", "嫉妒", "恨", "怒"],
            "physical": ["靠近", "后退", "挡住", "抓住", "推开", "逼近", "拦住"],
            "verbal": ["闭嘴", "住口", "休想", "放肆", "找死", "凭什么", "你也配"],
        }

        collisions = []
        for r in rounds:
            round_num = r["round"]
            a_resp = r.get("A", {}).get("response", {}) or {}
            b_resp = r.get("B", {}).get("response", {}) or {}

            a_inner = a_resp.get("inner_monologue", "")
            b_inner = b_resp.get("inner_monologue", "")
            a_line = a_resp.get("first_line", "")
            b_line = b_resp.get("first_line", "")
            a_action = a_resp.get("action", "")
            b_action = b_resp.get("action", "")

            combined = a_inner + b_inner + a_line + b_line + a_action + b_action

            # 检测碰撞类型
            for ctype, keywords in conflict_keywords.items():
                matches = [kw for kw in keywords if kw in combined]
                if len(matches) >= 2:  # 至少2个冲突关键词才视为碰撞
                    collisions.append({
                        "round": round_num,
                        "type": ctype,
                        "description": f"第{round_num}轮：{char_a}与{char_b}在{ctype}层面碰撞",
                        "keywords": matches,
                        "a_line": a_line,
                        "b_line": b_line,
                    })
                    break  # 每轮只记录一种碰撞类型

        return collisions

    def _find_eruption_round(self, collisions: list) -> int:
        """定位冲突爆发轮——冲突从隐性变为显性的轮次。

        判定逻辑：
        - 如果碰撞点中有 verbal 类型，取第一个 verbal 碰撞的轮次
        - 否则取第一个 physical 碰撞的轮次
        - 否则取第一个 emotional 碰撞的轮次
        - 如果都没有碰撞，返回 -1

        Returns:
            冲突爆发轮号（1-based），-1 表示未检测到爆发
        """
        if not collisions:
            return -1

        # 优先级：verbal > physical > emotional
        for ctype in ["verbal", "physical", "emotional"]:
            for c in collisions:
                if c["type"] == ctype:
                    return c["round"]

        return collisions[0]["round"]

    def export_rp_log_for_rhythm(self, duel_result: dict, chapter_num: int = 0,
                                  output_path: str = None) -> dict:
        """v7.7: 将 RP 推演日志导出为 rhythm_analyzer 兼容格式。

        将 simulate_duel() 的碰撞点和钩子数据映射到 rhythm_analyzer 的
        CSV 字段，作为章节节奏分析的补充数据源。

        映射关系：
        - collision_points → conflict_density / conflict_level
        - hooks → hook_type 标注
        - eruption_round → 冲突爆发位置

        Args:
            duel_result: simulate_duel() 的返回结果
            chapter_num: 对应章节号（0 表示未关联具体章节）
            output_path: 可选的 JSON 输出路径

        Returns:
            rhythm_analyzer 兼容的字典，可直接 merge 到 CSV 行
        """
        collisions = duel_result.get("collision_points", [])
        hooks = duel_result.get("hooks", [])
        eruption = duel_result.get("eruption_round", -1)

        # 冲突密度：碰撞次数 / 总轮数
        total_rounds = len(duel_result.get("rounds", []))
        conflict_density = round(len(collisions) / max(total_rounds, 1), 3)

        # 冲突等级映射
        if len(collisions) >= 3:
            conflict_level = "high"
        elif len(collisions) >= 1:
            conflict_level = "medium"
        else:
            conflict_level = "low"

        # 碰撞类型统计
        collision_types = {}
        for c in collisions:
            ctype = c["type"]
            collision_types[ctype] = collision_types.get(ctype, 0) + 1

        # 钩子标注
        hook_annotations = []
        for h in hooks:
            line = h.get("line", "")
            if line:
                # 简单启发式：根据台词特征判断钩子类型
                if any(kw in line for kw in ["?", "吗", "呢", "什么"]):
                    hook_type = "question"
                elif any(kw in line for kw in ["!", "死", "杀", "滚"]):
                    hook_type = "threat"
                elif any(kw in line for kw in ["如果", "要是", "或许"]):
                    hook_type = "promise"
                else:
                    hook_type = "cliffhanger"
                hook_annotations.append({
                    "round": h["round"],
                    "character": h["character"],
                    "type": hook_type,
                    "line": line[:50],
                })

        result = {
            "chapter_num": chapter_num,
            "rp_conflict_density": conflict_density,
            "rp_conflict_level": conflict_level,
            "rp_eruption_round": eruption,
            "rp_collision_types": collision_types,
            "rp_hook_annotations": hook_annotations,
            "rp_total_rounds": total_rounds,
            "rp_collision_count": len(collisions),
        }

        # 可选：写入文件
        if output_path:
            import json
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_text(
                json.dumps(result, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

        return result

    # ── 内部工具 ──

    def _parse_md_sections(self, text: str) -> dict:
        """解析 Markdown 的 ## 分节。"""
        sections = {}
        current = "preamble"
        current_lines = []
        for line in text.split("\n"):
            if line.startswith("## "):
                if current_lines:
                    sections[current] = "\n".join(current_lines)
                current = line[3:].strip()
                current_lines = []
            else:
                current_lines.append(line)
        if current_lines:
            sections[current] = "\n".join(current_lines)
        return sections

    def _find_character_section(self, sections: dict, name: str) -> dict:
        """在 sections 中查找指定角色的信息。"""
        for title, content in sections.items():
            if name in title:
                info = {}
                for line in content.split("\n"):
                    if line.strip().startswith("- **"):
                        parts = line.strip().split("**:", 1)
                        if len(parts) == 2:
                            key = parts[0].replace("- **", "").strip()
                            val = parts[1].strip()
                            info[key] = val
                return info
        return {}