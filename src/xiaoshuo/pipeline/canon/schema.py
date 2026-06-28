# -*- coding: utf-8 -*-
"""
canon.schema — 6 个 canon 文件的数据结构定义
=============================================
v7.6: 轻量类型校验（不依赖 Pydantic），与 infra/schemas.py 风格一致。
"""

from typing import Any


# ── 6 个 canon 文件的 Schema ──

CHARACTERS_SCHEMA = {
    "protagonist": {  # 主角
        "name": str,
        "identity": str,
        "personality": str,
        "ability": str,
        "arc": str,  # 角色弧线
    },
    "core_companions": [  # 核心同伴列表
        {
            "name": str,
            "identity": str,
            "personality": str,
            "ability": str,
            "role": str,  # 在故事中的角色
            "key_conflict": str,  # 与主角的核心冲突/张力
        }
    ],
    "antagonists": [
        {
            "name": str,
            "identity": str,
            "motivation": str,
            "threat_level": str,  # 前期/中期/后期
            "key_conflict": str,
        }
    ],
    "supporting": [
        {
            "name": str,
            "identity": str,
            "role": str,
            "first_appearance": str,  # 首次出场章节或场景
        }
    ],
}

TIMELINE_SCHEMA = {
    "phases": [
        {
            "phase": int,  # 1/2/3
            "name": str,
            "chapters": str,  # "1-150" / "150-250" / "250-300"
            "key_events": [str],
            "status": str,  # 前期/中期/后期
        }
    ],
    "golden_three": [  # 黄金三章逐章事件
        {
            "chapter": int,
            "events": [str],
            "hooks": [str],  # 本章埋下的钩子
        }
    ],
    "major_turning_points": [  # 重大转折点
        {
            "chapter": int,
            "event": str,
            "impact": str,  # 对世界观/角色/剧情的影响
        }
    ],
}

RULES_SCHEMA = {
    "power_system": {
        "name": str,  # "本能驾驭"
        "source": str,  # 力量来源
        "cost": str,  # 代价
        "limitations": [str],  # 限制条件
        "progression": str,  # 升级路径
    },
    "world_rules": [
        {
            "rule": str,
            "category": str,  # 生存/社会/自然/超自然
            "consequence": str,  # 违反规则的后果
            "exceptions": str,  # 例外情况
        }
    ],
    "creature_rules": [  # 生物/种族规则
        {
            "type": str,  # 人类/妖/失控者/天选者
            "abilities": [str],
            "weaknesses": [str],
            "social_status": str,
        }
    ],
    "artifact_rules": [  # 特殊物品/道具规则
        {
            "name": str,  # 模拟器/进化源/...
            "function": str,
            "limitations": [str],
            "origin": str,  # 来源（已知/未知）
        }
    ],
}

FORESHADOWING_SCHEMA = {
    "active": [  # 已埋、待回收的伏笔
        {
            "id": int,
            "hook": str,  # 伏笔内容
            "chapter_planted": int,  # 埋下章节（0=规划阶段）
            "expected_reveal": str,  # 预期揭露时机（前期/中期/后期/具体章节）
            "status": str,  # 已埋/已暗示/已揭示
            "related_characters": [str],
            "related_rules": [str],  # 关联的规则/世界观
        }
    ],
    "resolved": [  # 已回收的伏笔
        {
            "id": int,
            "hook": str,
            "chapter_planted": int,
            "chapter_revealed": int,
            "reveal_method": str,  # 揭露方式
        }
    ],
}

EMOTIONAL_ARCS_SCHEMA = {
    "protagonist": {
        "name": str,
        "emotional_curve": str,  # 整体情感曲线描述
        "key_nodes": [  # 关键情感节点
            {
                "chapter": int,
                "emotion": str,  # 希望/绝望/愤怒/平静/挣扎/释然
                "trigger": str,  # 触发事件
                "intensity": int,  # 1-10
            }
        ],
        "core_conflict": str,  # 核心情感冲突
        "resolution": str,  # 情感结局（规划）
    },
    "major_relationships": [  # 主要情感关系
        {
            "characters": str,  # "主角-柳树妖"
            "type": str,  # 友情/爱情/亲情/敌对/同盟
            "arc": str,  # 关系弧线
            "key_moments": [str],
        }
    ],
}

SUBPLOT_SCHEMA = {
    "subplots": [
        {
            "id": str,
            "name": str,
            "type": str,  # 角色支线/世界观支线/冲突支线/情感支线
            "status": str,  # 规划中/进行中/已完成
            "chapters": str,  # 涉及章节范围
            "key_characters": [str],
            "checkpoints": [  # 支线里程碑
                {
                    "chapter": int,
                    "event": str,
                    "crosses_main": bool,  # 是否与主线交叉
                }
            ],
            "resolution": str,  # 预期结局
        }
    ],
}

# ── 风格规则 (v7.8 Part E 风格进化) ──

STYLE_RULES_SCHEMA = {
    "preferences": {
        "sentence": {
            "avg_length_range": str,  # "15-25" (chars)
            "prefer_active_voice": bool,
            "paragraph_density": str,  # "compact|medium|spacious"
        },
        "pacing": {
            "action_to_rest_ratio": str,  # "7:3"
            "cliffhanger_frequency": str,  # "每章|每3章|每卷"
        },
        "dialogue": {
            "dialogue_to_narration_ratio": str,  # "4:6"
            "prefer_action_tags": bool,  # 用动作标签代替"XX说"
        },
    },
    "taboos": {
        "ai_fingerprint_words": [str],  # 禁止使用的AI指纹词
        "sentence_patterns": [str],  # 禁止的句式模板
        "overused_devices": [str],  # 过度使用的叙事手法
    },
    "genre_conventions": {
        "required_elements": [str],  # 该题材必须包含的元素
        "forbidden_cliches": [str],  # 该题材禁止的陈词滥调
    },
    "s3_review_rules": [  # 从S3评审中提取的风格规则，用于后续审阅加权
        {
            "dimension": str,  # pacing|pleasure|hook|immersion|logic|language
            "rule": str,  # 规则描述
            "weight": float,  # 1.0=标准, >1.0=重点关注, <1.0=降低关注
            "source": str,  # "S3_logic_cop|S3_editor|S3_qc|manual"
            "evidence": str,  # 支撑证据（S3评审原文引用）
        }
    ],
    "evolution_log": [  # 风格演化历史，每次校准追加一条
        {
            "date": str,
            "trigger": str,  # 触发来源：S3评审/手动校准/批量提取
            "change": str,  # 变更内容
            "reason": str,  # 变更原因
        }
    ],
}

# ── 汇总 ──

# v8.0: 大纲模板 (S4 大纲细纲打通方案)
# Part B 骨架生成必须按此结构输出，写入 Canon
NOVEL_OUTLINE_SCHEMA = {
    "one_sentence": str,  # 一句话故事 (20字以内)
    "protagonist": str,  # 主角名 (关联 CanonCharacter)
    "motivation": str,  # 核心动机
    "goal": str,  # 最终目标
    "core_obstacle": str,  # 核心阻碍
    "core_conflict": str,  # 核心矛盾 (S3 逻辑一致性判据来源)
    "phases": [  # 阶段目标与代价 (对应"卷/块"层级)
        {
            "phase": int,
            "goal": str,  # 本阶段目标
            "cost": str,  # 付出的代价
            "growth": str,  # 获得的成长
        }
    ],
    "foreshadowing": [  # 伏笔与回收 (供 S3 跨章节校验)
        {
            "id": int,
            "content": str,
            "planted_at": str,  # 埋下位置 (章节号或场景)
            "reveal_plan": str,  # 预期回收时机
        }
    ],
    "character_arcs": {  # 核心角色弧线
        "protagonist": str,  # 主角成长弧线 (如 "从懦弱到果敢")
        "key_turning_points": [str],  # 关键转折事件
    },
}

# v8.0: 细纲模板 (S4 大纲细纲打通方案)
# Part C 手写前，AI 基于大纲 + Canon 生成此施工单，作者照着写
CHAPTER_BLUEPRINT_SCHEMA = {
    "chapter_num": int,
    "one_sentence": str,  # 本章一句话总结 (20字)
    "purpose": str,  # 本章在整个故事中的功能和目标
    "characters": [str],  # 出场人物 (关联 Canon 人物卡)
    "protagonist_wants": str,  # 主角本章欲望
    "obstacle": str,  # 阻碍
    "conflict": str,  # 本章冲突 (欲望 vs 阻碍)
    "protagonist_action": str,  # 主角采取的行动
    "action_result": str,  # 行动结果
    "emotion_changes": {  # 人物情绪变化
        "protagonist": str,  # 如 "期待 → 疑虑 → 震惊 → 克制"
        "others": {str: str},  # 角色名 → 情绪变化
    },
    "foreshadowing_plant": str,  # 本章埋下的伏笔 (空=无)
    "cliffhanger": str,  # 章末钩子
    "required_canon": [str],  # 本章必须引用的 Canon 条目 (如 "妖力等级体系")
    # v8.1: 爽感奖励 (基于七步正反馈循环)
    "reward_type": str,  # 奖励类型: "数值型"|"权限型"|"关系型"|"未来型"|""
}

CANON_SCHEMAS = {
    "characters": CHARACTERS_SCHEMA,
    "timeline": TIMELINE_SCHEMA,
    "rules": RULES_SCHEMA,
    "foreshadowing": FORESHADOWING_SCHEMA,
    "emotional_arcs": EMOTIONAL_ARCS_SCHEMA,
    "subplot_board": SUBPLOT_SCHEMA,
    "style_rules": STYLE_RULES_SCHEMA,
    "novel_outline": NOVEL_OUTLINE_SCHEMA,
    "chapter_blueprint": CHAPTER_BLUEPRINT_SCHEMA,
}


def _validate_type(value: Any, expected_type, path: str = "$") -> list[str]:
    """递归类型校验，返回错误列表。"""
    errors = []
    if isinstance(expected_type, tuple):
        if not isinstance(value, expected_type):
            errors.append(f"{path}: expected {expected_type}, got {type(value).__name__}")
    elif isinstance(expected_type, type):
        if not isinstance(value, expected_type):
            errors.append(f"{path}: expected {expected_type.__name__}, got {type(value).__name__}")
    elif isinstance(expected_type, list):
        if len(expected_type) == 0:
            return errors
        if not isinstance(value, list):
            errors.append(f"{path}: expected list, got {type(value).__name__}")
        else:
            item_schema = expected_type[0]
            for i, item in enumerate(value):
                errors.extend(_validate_type(item, item_schema, f"{path}[{i}]"))
    elif isinstance(expected_type, dict):
        if not isinstance(value, dict):
            errors.append(f"{path}: expected dict, got {type(value).__name__}")
        else:
            for key, vtype in expected_type.items():
                if key not in value:
                    errors.append(f"{path}.{key}: missing required field")
                else:
                    errors.extend(_validate_type(value[key], vtype, f"{path}.{key}"))
    return errors


def validate_canon(name: str, data: dict) -> list[str]:
    """校验 canon 数据是否符合 Schema。返回错误列表，空列表=通过。"""
    if name not in CANON_SCHEMAS:
        return [f"Unknown canon name: {name}"]
    return _validate_type(data, CANON_SCHEMAS[name], f"canon.{name}")