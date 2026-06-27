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

# ── 汇总 ──

CANON_SCHEMAS = {
    "characters": CHARACTERS_SCHEMA,
    "timeline": TIMELINE_SCHEMA,
    "rules": RULES_SCHEMA,
    "foreshadowing": FORESHADOWING_SCHEMA,
    "emotional_arcs": EMOTIONAL_ARCS_SCHEMA,
    "subplot_board": SUBPLOT_SCHEMA,
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