# -*- coding: utf-8 -*-
"""
author_mind_model.py — 作者心智模型 + 决策直觉引擎 (P2)
================================================================
来源: 建议文件 "女娲造人 → 四大核心 → 心智模型 + 决策直觉"

核心理念:
  从"拆书提取规则"升级为"构建作者思维模式"。
  规则: "第三章要有爽点" — 但什么爽点？怎么写？(不可执行)
  分身: "如果是烽火戏诸侯，第三章他会先写一个看似无关的小场景，
        然后在结尾用一句话把读者炸醒" — (可执行的创作建议)

两大模块:
  1. AuthorMindModel (心智模型):
     - 作者创作框架库 (故事结构、爽点逻辑、节奏方法论)
     - 从拆书数据 + 创作谈 → 提取"作者思维导图"
     - 应用: 骨架生成时问"如果是这个作者，这个情节点他会怎么设计？"

  2. DecisionIntuitionEngine (决策直觉引擎):
     - 关键节点选择引擎: "不同作者会怎么选"对比
     - 在骨架的关键决策点，提供多个作者视角的选项
     - 记录作者(用户)的选择偏好 → 形成"个人决策直觉库"

与现有模块的关系:
  - style_dna.py: 从文本提取量化风格指纹 (微观/被动)
  - author_mind_model.py: 从思维模式提取创作框架 (宏观/主动)
  - red_line_principles.py: 红线原则 (创作底线)
  - style_evolution.py: 风格进化 (长期偏好积累)
  - outline_builder.py: 骨架生成 (决策直觉的消费者)
  - deconstruct_novel.py: 拆文 (心智模型的数据来源)

设计原则:
  - JSON 文件存储: 轻量, 可读, 可手动编辑
  - 可积累: 从每次拆书/创作中增量更新
  - 可对比: 不同作者的心智模型可以横向对比
  - 可选择: 决策直觉提供多选项, 由人类作者最终决策

用法:
  from xiaoshuo.agents.author_mind_model import (
      AuthorMindModel, DecisionIntuitionEngine,
  )

  # 心智模型
  model = AuthorMindModel("烽火戏诸侯")
  model.load()  # 从 JSON 加载
  framework = model.get_framework()
  # → {"structure": "三幕式+悬念前置", "pleasure_logic": "延迟满足+反转暴击", ...}

  # 决策直觉引擎
  engine = DecisionIntuitionEngine()
  options = engine.generate_decision_options(
      scenario="主角面对强敌，实力差距悬殊",
      authors=["辰东", "猫腻", "烽火戏诸侯"],
  )
  # → [{"author": "辰东", "choice": "越级挑战，死战不退", "reasoning": "..."}, ...]

  # 记录用户选择
  engine.record_choice(
      scenario="主角面对强敌",
      chosen_author="猫腻",
      context={"chapter": 15, "genre": "玄幻"},
  )
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from xiaoshuo import PROJECT_ROOT
from xiaoshuo.infra.logging_config import get_logger

logger = get_logger("author_mind_model")


# ============================================================
# 路径常量
# ============================================================

_MIND_MODEL_DIR = PROJECT_ROOT / "data" / "processed" / "mind_models"
_DECISION_LOG_PATH = PROJECT_ROOT / "data" / "processed" / "decision_log.json"


# ============================================================
# 1. 作者心智模型 (AuthorMindModel)
# ============================================================

@dataclass
class AuthorFramework:
    """作者创作框架 (心智模型的核心输出)。

    不是情节, 是思维结构。
    """
    # 故事结构偏好
    structure: str = ""             # 核心结构: 三幕式/英雄之旅/无限流副本/...
    structure_detail: str = ""      # 结构细节说明

    # 爽点设计逻辑
    pleasure_logic: str = ""        # 即时反馈/延迟满足/反转暴击/...
    pleasure_detail: str = ""       # 爽点设计方法论

    # 节奏控制方法论
    rhythm_method: str = ""         # 短章快节奏/长章大场面/波浪式/...
    rhythm_detail: str = ""         # 节奏控制细节

    # 人物塑造偏好
    characterization: str = ""      # 人物塑造方式
    characterization_detail: str = ""  # 细节

    # 冲突设计偏好
    conflict_style: str = ""        # 冲突设计风格
    conflict_detail: str = ""       # 细节

    # 世界观构建偏好
    worldbuilding: str = ""         # 世界观构建方式
    worldbuilding_detail: str = ""  # 细节

    def to_dict(self) -> dict:
        return {
            "structure": self.structure,
            "structure_detail": self.structure_detail,
            "pleasure_logic": self.pleasure_logic,
            "pleasure_detail": self.pleasure_detail,
            "rhythm_method": self.rhythm_method,
            "rhythm_detail": self.rhythm_detail,
            "characterization": self.characterization,
            "characterization_detail": self.characterization_detail,
            "conflict_style": self.conflict_style,
            "conflict_detail": self.conflict_detail,
            "worldbuilding": self.worldbuilding,
            "worldbuilding_detail": self.worldbuilding_detail,
        }


@dataclass
class AuthorMindModel:
    """作者心智模型。

    从拆书数据 + 创作谈 → 提取"作者思维导图"。
    不是情节, 是思维结构。

    用法:
      model = AuthorMindModel("烽火戏诸侯")
      model.load()
      framework = model.get_framework()

      # 从拆文结果更新
      model.update_from_deconstruction(deconstruction_result_dict)
      model.save()
    """
    author_name: str
    framework: AuthorFramework = field(default_factory=AuthorFramework)
    # 标志性技法 (从作品中提取的技巧)
    signature_techniques: list[dict] = field(default_factory=list)
    # 创作谈/访谈要点
    craft_notes: list[str] = field(default_factory=list)
    # 代表作列表 (用于参考)
    representative_works: list[str] = field(default_factory=list)
    # 元数据
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        self.updated_at = self.created_at

    @property
    def _filepath(self) -> Path:
        _MIND_MODEL_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = self.author_name.replace("/", "_").replace("\\", "_")
        return _MIND_MODEL_DIR / f"{safe_name}.json"

    def load(self) -> bool:
        """从 JSON 文件加载心智模型。

        Returns:
            True=加载成功, False=文件不存在(使用空模型)
        """
        if not self._filepath.exists():
            logger.info(f"心智模型文件不存在: {self._filepath}, 使用空模型")
            return False

        data = json.loads(self._filepath.read_text(encoding="utf-8"))
        fw = data.get("framework", {})
        self.framework = AuthorFramework(
            structure=fw.get("structure", ""),
            structure_detail=fw.get("structure_detail", ""),
            pleasure_logic=fw.get("pleasure_logic", ""),
            pleasure_detail=fw.get("pleasure_detail", ""),
            rhythm_method=fw.get("rhythm_method", ""),
            rhythm_detail=fw.get("rhythm_detail", ""),
            characterization=fw.get("characterization", ""),
            characterization_detail=fw.get("characterization_detail", ""),
            conflict_style=fw.get("conflict_style", ""),
            conflict_detail=fw.get("conflict_detail", ""),
            worldbuilding=fw.get("worldbuilding", ""),
            worldbuilding_detail=fw.get("worldbuilding_detail", ""),
        )
        self.signature_techniques = data.get("signature_techniques", [])
        self.craft_notes = data.get("craft_notes", [])
        self.representative_works = data.get("representative_works", [])
        self.created_at = data.get("created_at", "")
        self.updated_at = data.get("updated_at", "")
        logger.info(f"已加载心智模型: {self.author_name} ({len(self.signature_techniques)}个技法)")
        return True

    def save(self) -> None:
        """保存心智模型到 JSON 文件。"""
        self.updated_at = datetime.now().isoformat()
        data = {
            "author_name": self.author_name,
            "framework": self.framework.to_dict(),
            "signature_techniques": self.signature_techniques,
            "craft_notes": self.craft_notes,
            "representative_works": self.representative_works,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        self._filepath.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"心智模型已保存: {self._filepath}")

    def get_framework(self) -> AuthorFramework:
        """获取创作框架。"""
        return self.framework

    def update_from_deconstruction(self, deconstruction: dict) -> None:
        """从拆文结果更新心智模型。

        Args:
            deconstruction: deconstruct_novel.py 的 to_dict() 输出
        """
        # 从节奏曲线推断节奏方法论
        rhythm_curve = deconstruction.get("genre_tags", {}).get("rhythm_curve", [])
        if rhythm_curve:
            emotions = [p.get("emotion", 0) for p in rhythm_curve]
            if emotions:
                import statistics
                avg = statistics.mean(emotions)
                cv = statistics.stdev(emotions) / max(avg, 0.01) if len(emotions) > 1 else 0
                if cv > 0.5:
                    self.framework.rhythm_method = "波浪式 (高低交替)"
                elif avg > 0.5:
                    self.framework.rhythm_method = "高密度快节奏"
                else:
                    self.framework.rhythm_method = "慢热渐入型"
                self.framework.rhythm_detail = f"平均情绪强度{avg:.2f}, 波动系数{cv:.2f}"

        # 从题材推断爽点逻辑
        pleasure_type = deconstruction.get("genre_tags", {}).get("pleasure_type", "")
        if pleasure_type:
            self.framework.pleasure_logic = pleasure_type
            self.framework.pleasure_detail = f"核心爽点类型: {pleasure_type}"

        # 从结构拆解推断故事结构
        plot_structure = deconstruction.get("structure", {}).get("plot_structure", "")
        if plot_structure:
            self.framework.structure = plot_structure

        # 从技法亮点提取标志性技法
        highlights = deconstruction.get("borrowable", {}).get("technique_highlights", [])
        for h in highlights:
            self.signature_techniques.append({
                "technique": h,
                "source": "deconstruction",
                "added_at": datetime.now().isoformat(),
            })

        logger.info(f"从拆文结果更新心智模型: {self.author_name}")

    def add_craft_note(self, note: str) -> None:
        """添加创作谈/访谈要点。"""
        self.craft_notes.append(note)
        self.updated_at = datetime.now().isoformat()

    def add_signature_technique(self, technique: str, source: str = "manual") -> None:
        """添加标志性技法。"""
        self.signature_techniques.append({
            "technique": technique,
            "source": source,
            "added_at": datetime.now().isoformat(),
        })

    def to_prompt_context(self) -> str:
        """转为 prompt 上下文 (供骨架生成时使用)。

        格式: "如果我是{作者}，这个情节点我会怎么设计？"
        """
        lines = [f"=== 作者心智模型: {self.author_name} ==="]
        fw = self.framework
        if fw.structure:
            lines.append(f"故事结构: {fw.structure}")
            if fw.structure_detail:
                lines.append(f"  细节: {fw.structure_detail}")
        if fw.pleasure_logic:
            lines.append(f"爽点逻辑: {fw.pleasure_logic}")
            if fw.pleasure_detail:
                lines.append(f"  细节: {fw.pleasure_detail}")
        if fw.rhythm_method:
            lines.append(f"节奏方法论: {fw.rhythm_method}")
            if fw.rhythm_detail:
                lines.append(f"  细节: {fw.rhythm_detail}")
        if fw.characterization:
            lines.append(f"人物塑造: {fw.characterization}")
        if fw.conflict_style:
            lines.append(f"冲突设计: {fw.conflict_style}")
        if fw.worldbuilding:
            lines.append(f"世界观构建: {fw.worldbuilding}")
        if self.signature_techniques:
            lines.append("标志性技法:")
            for t in self.signature_techniques[-5:]:  # 最近5个
                lines.append(f"  - {t['technique']}")
        if self.craft_notes:
            lines.append("创作谈:")
            for note in self.craft_notes[-3:]:  # 最近3条
                lines.append(f"  - {note}")

        return "\n".join(lines)


# ============================================================
# 2. 决策直觉引擎 (DecisionIntuitionEngine)
# ============================================================

# 预设作者决策直觉库 (基于公开作品分析)
_PRESET_INTUITIONS = {
    "辰东": {
        "choices": {
            "强敌": "越级挑战，死战不退（爽点前置）",
            "秘境": "孤身闯入，以命搏宝",
            "背叛": "当场暴怒，雷霆报复",
            "情感": "直来直去，不爱不恨",
        },
        "reasoning": "辰东式直觉：以'燃'为核心，主角绝不退让，用极端冲突制造爽感。",
    },
    "猫腻": {
        "choices": {
            "强敌": "借势而为，谋定后动（爽点后置）",
            "秘境": "布局引诱，让他人先探路",
            "背叛": "隐忍不发，等待时机清算",
            "情感": "含蓄克制，以细节暗示",
        },
        "reasoning": "猫腻式直觉：以'谋'为核心，主角善于利用规则和人心，爽感来自智商碾压。",
    },
    "烽火戏诸侯": {
        "choices": {
            "强敌": "不战而屈人之兵，装逼于无形（爽点变形）",
            "秘境": "看似无意，实则早有布局",
            "背叛": "轻描淡写间让背叛者后悔",
            "情感": "江湖气，以酒剑诗寄情",
        },
        "reasoning": "烽火式直觉：以'韵'为核心，主角超然物外，爽感来自格局碾压和装逼美学。",
    },
    "天蚕土豆": {
        "choices": {
            "强敌": "先被压制，关键时刻爆发逆转",
            "秘境": "系统引导，按部就班升级",
            "背叛": "用实力碾压，打脸全场",
            "情感": "热血兄弟情，简单直接",
        },
        "reasoning": "土豆式直觉：以'燃+爽'为核心，标准的退婚流/废柴流节奏，爽感来自逆袭打脸。",
    },
    "爱潜水的乌贼": {
        "choices": {
            "强敌": "利用规则和序列，智斗为主",
            "秘境": "小心谨慎，收集情报后行动",
            "背叛": "布局深远，跨章节复仇",
            "情感": "理性克制，感情为辅",
        },
        "reasoning": "乌贼式直觉：以'诡'为核心，主角善于利用规则漏洞，爽感来自智商和信息差。",
    },
}


@dataclass
class DecisionOption:
    """决策选项。"""
    author: str              # 作者名
    choice: str              # 该作者会怎么选
    reasoning: str           # 推理过程
    consequence: str = ""    # 可能的后果 (可选)
    pleasure_type: str = ""  # 爽点类型


@dataclass
class DecisionRecord:
    """决策记录 (用户的选择偏好)。"""
    scenario: str            # 场景描述
    chosen_author: str       # 选择的作者方向
    context: dict            # 上下文 (章节号、题材等)
    timestamp: str           # 时间戳
    all_options: list[dict] = field(default_factory=list)  # 所有选项


class DecisionIntuitionEngine:
    """决策直觉引擎。

    在骨架的关键决策点，提供"不同作者会怎么选"的对比。
    记录用户的选择偏好，逐渐形成"个人决策直觉库"。

    用法:
      engine = DecisionIntuitionEngine()

      # 生成决策选项
      options = engine.generate_decision_options(
          scenario="主角面对强敌，实力差距悬殊",
          authors=["辰东", "猫腻", "烽火戏诸侯"],
      )

      # 记录用户选择
      engine.record_choice(
          scenario="主角面对强敌",
          chosen_author="猫腻",
          context={"chapter": 15, "genre": "玄幻"},
      )

      # 查看个人偏好
      prefs = engine.get_personal_preferences()
    """

    def __init__(self):
        self._log_path = _DECISION_LOG_PATH
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    def generate_decision_options(
        self,
        scenario: str,
        authors: Optional[list[str]] = None,
        context: Optional[dict] = None,
    ) -> list[DecisionOption]:
        """生成决策选项。

        在骨架的关键决策点，提供"不同作者会怎么选"的对比。

        Args:
            scenario: 场景描述 (如 "主角面对强敌，实力差距悬殊")
            authors: 参考作者列表 (None=使用全部预设)
            context: 上下文信息 (章节号、题材等)

        Returns:
            DecisionOption 列表 (每个作者一个选项)
        """
        if authors is None:
            authors = list(_PRESET_INTUITIONS.keys())

        options: list[DecisionOption] = []

        for author in authors:
            preset = _PRESET_INTUITIONS.get(author)
            if not preset:
                # 尝试从心智模型加载
                model = AuthorMindModel(author)
                if model.load():
                    options.append(DecisionOption(
                        author=author,
                        choice=f"基于{author}的心智模型: {model.framework.conflict_style or '未知'}",
                        reasoning=model.framework.conflict_detail or "请参考该作者的心智模型",
                    ))
                continue

            # 场景关键词匹配
            scenario_key = self._match_scenario_key(scenario)
            choice = preset["choices"].get(scenario_key, preset["choices"].get("强敌", "未知"))
            reasoning = preset["reasoning"]

            # 推断爽点类型
            pleasure_map = {
                "辰东": "即时爽感 (热血爆发)",
                "猫腻": "延迟爽感 (智商碾压)",
                "烽火戏诸侯": "变形爽感 (格局装逼)",
                "天蚕土豆": "逆袭爽感 (打脸逆转)",
                "爱潜水的乌贼": "悬念爽感 (规则解谜)",
            }
            pleasure_type = pleasure_map.get(author, "")

            options.append(DecisionOption(
                author=author,
                choice=choice,
                reasoning=reasoning,
                pleasure_type=pleasure_type,
            ))

        logger.info(f"生成 {len(options)} 个决策选项 (场景: {scenario[:30]}...)")
        return options

    def _match_scenario_key(self, scenario: str) -> str:
        """场景关键词匹配。"""
        scenario_lower = scenario.lower()
        if any(kw in scenario for kw in ["强敌", "对手", "战斗", "挑战", "打"]):
            return "强敌"
        if any(kw in scenario for kw in ["秘境", "副本", "遗迹", "探索"]):
            return "秘境"
        if any(kw in scenario for kw in ["背叛", "出卖", "欺骗"]):
            return "背叛"
        if any(kw in scenario for kw in ["感情", "情感", "爱情", "表白", "喜欢"]):
            return "情感"
        return "强敌"  # 默认

    def record_choice(
        self,
        scenario: str,
        chosen_author: str,
        context: Optional[dict] = None,
        all_options: Optional[list[dict]] = None,
    ) -> None:
        """记录用户的选择。

        逐渐形成"个人决策直觉库"。

        Args:
            scenario: 场景描述
            chosen_author: 选择的作者方向
            context: 上下文信息
            all_options: 所有选项 (供回溯)
        """
        record = DecisionRecord(
            scenario=scenario,
            chosen_author=chosen_author,
            context=context or {},
            timestamp=datetime.now().isoformat(),
            all_options=all_options or [],
        )

        # 追加到日志文件
        logs: list = []
        if self._log_path.exists():
            try:
                logs = json.loads(self._log_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                logs = []
        logs.append({
            "scenario": record.scenario,
            "chosen_author": record.chosen_author,
            "context": record.context,
            "timestamp": record.timestamp,
            "all_options": record.all_options,
        })
        self._log_path.write_text(
            json.dumps(logs, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"记录决策: 场景='{scenario[:30]}' 选择={chosen_author}")

    def get_personal_preferences(self) -> dict:
        """获取个人决策偏好统计。

        从历史选择记录中统计用户的偏好。

        Returns:
            {
                "total_choices": int,
                "author_distribution": {"辰东": 3, "猫腻": 5, ...},
                "preferred_style": "谋 (猫腻式)",
                "scenario_preferences": {"强敌": "猫腻", ...},
            }
        """
        if not self._log_path.exists():
            return {
                "total_choices": 0,
                "author_distribution": {},
                "preferred_style": "未知 (尚无记录)",
                "scenario_preferences": {},
            }

        logs = json.loads(self._log_path.read_text(encoding="utf-8"))
        total = len(logs)
        author_counter: dict[str, int] = {}
        scenario_prefs: dict[str, dict[str, int]] = {}

        for log in logs:
            author = log.get("chosen_author", "未知")
            author_counter[author] = author_counter.get(author, 0) + 1

            # 按场景统计
            scenario = log.get("scenario", "未知")
            scenario_key = self._match_scenario_key(scenario)
            if scenario_key not in scenario_prefs:
                scenario_prefs[scenario_key] = {}
            scenario_prefs[scenario_key][author] = scenario_prefs[scenario_key].get(author, 0) + 1

        # 推断偏好风格
        style_map = {
            "辰东": "燃 (辰东式热血)",
            "猫腻": "谋 (猫腻式智斗)",
            "烽火戏诸侯": "韵 (烽火式格局)",
            "天蚕土豆": "爽 (土豆式逆袭)",
            "爱潜水的乌贼": "诡 (乌贼式悬念)",
        }
        top_author = max(author_counter, key=author_counter.get) if author_counter else "未知"
        preferred_style = style_map.get(top_author, "未知")

        # 每个场景的偏好
        scenario_preference: dict[str, str] = {}
        for sk, ac in scenario_prefs.items():
            scenario_preference[sk] = max(ac, key=ac.get) if ac else "未知"

        return {
            "total_choices": total,
            "author_distribution": author_counter,
            "preferred_style": preferred_style,
            "scenario_preferences": scenario_preference,
        }

    def format_options_for_prompt(self, options: list[DecisionOption]) -> str:
        """将决策选项格式化为 prompt 上下文。"""
        if not options:
            return "无可用决策选项。"

        lines = ["=== 关键决策点: 不同作者会怎么选 ==="]
        for opt in options:
            lines.append(f"\n【{opt.author}】")
            lines.append(f"  选择: {opt.choice}")
            if opt.pleasure_type:
                lines.append(f"  爽点: {opt.pleasure_type}")
            lines.append(f"  理由: {opt.reasoning}")

        lines.append("\n请选择一种直觉方向，系统将据此调整后续骨架。")
        return "\n".join(lines)


# ============================================================
# 3. 预设心智模型快速加载
# ============================================================

_PRESET_MODELS = {
    "辰东": AuthorFramework(
        structure="升级流+探索流",
        structure_detail="以修炼境界为主线，每个境界段对应一个地图/秘境，结构清晰",
        pleasure_logic="即时反馈+热血爆发",
        pleasure_detail="爽点前置，主角不退让，用极端冲突制造爽感",
        rhythm_method="高密度快节奏",
        rhythm_detail="短章密集，战斗占比高，每章至少一个小爽点",
        characterization="热血+重情义",
        characterization_detail="主角性格鲜明，配角功能性为主",
        conflict_style="正面硬刚",
        conflict_detail="以力破巧，用绝对实力碾压一切阴谋",
        worldbuilding="宏大修仙世界",
        worldbuilding_detail="境界体系明确，地图逐步展开",
    ),
    "猫腻": AuthorFramework(
        structure="权谋+成长",
        structure_detail="多重势力交织，主角在夹缝中成长，结构复杂",
        pleasure_logic="延迟满足+智商碾压",
        pleasure_detail="爽点后置，前期布局后期收割，爽感来自智商碾压",
        rhythm_method="缓急交替",
        rhythm_detail="大段铺垫后突然爆发，张弛有度",
        characterization="复杂立体",
        characterization_detail="角色有灰度，反派也有魅力",
        conflict_style="以智取胜",
        conflict_detail="善用规则和人心，不靠蛮力",
        worldbuilding="精细社会结构",
        worldbuilding_detail="政治体系、社会阶层描写细腻",
    ),
    "烽火戏诸侯": AuthorFramework(
        structure="江湖+庙堂",
        structure_detail="江湖恩怨与朝堂权谋双线交织",
        pleasure_logic="格局碾压+装逼美学",
        pleasure_detail="爽感来自主角的超然和格局，不是简单的打脸",
        rhythm_method="长短交替",
        rhythm_detail="大场面长章铺展，日常短章推进",
        characterization="群像塑造",
        characterization_detail="配角鲜活，有江湖气",
        conflict_style="不战而屈人之兵",
        conflict_detail="用气度和格局压人，不是蛮力",
        worldbuilding="诗意江湖",
        worldbuilding_detail="文笔优美，有传统武侠韵味",
    ),
}


def get_preset_model(author: str) -> Optional[AuthorMindModel]:
    """获取预设心智模型。

    Args:
        author: 作者名

    Returns:
        AuthorMindModel (已加载预设框架), 如果无预设则返回 None
    """
    framework = _PRESET_MODELS.get(author)
    if not framework:
        return None

    model = AuthorMindModel(author)
    model.framework = framework
    return model


def list_preset_authors() -> list[str]:
    """列出所有有预设心智模型的作者。"""
    return list(_PRESET_MODELS.keys())
