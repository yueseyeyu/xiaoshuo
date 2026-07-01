# -*- coding: utf-8 -*-
"""
deconstruct_novel.py — 拆文标准模板 (Story Deconstruction Schema)
===================================================================
来源: 建议文件 "从 Old Story 借鉴：拆文流程标准化"
      "把这个模板做成 scripts/deconstruct_novel.py，输入小说文本，输出结构化 JSON"

核心功能:
  输入一本小说文本 → 输出五段式结构化 JSON:
    1. 题材标签: 题材/爽点类型/情绪基调/开头Hook/高潮位置/节奏曲线
    2. 结构拆解: 主角人设/反派模板/配角功能
    3. 人物拆解: 核心角色弧光/关系网/动机链
    4. 可借鉴元素: 结构借鉴/情绪借鉴/台词借鉴 (非抄袭)
    5. 避雷清单: 读者吐槽点/后期崩坏原因

设计原则:
  - 零 LLM 依赖: 纯统计/正则/规则提取
  - 增量分析: 支持大文件分章节流式处理
  - JSON 输出: 前端拆书页面直接渲染
  - 与 golden3_analyzer.py 互补:
      golden3 分析前3章 (微观)
      deconstruct 分析全书 (宏观)

用法:
  # 命令行
  python -m xiaoshuo.tools.deconstruct_novel data/raw/novels/玄幻/《某书》/某书.txt

  # 代码调用
  from xiaoshuo.tools.deconstruct_novel import deconstruct_novel
  result = deconstruct_novel(novel_text)
  # result → DeconstructionResult (可 to_dict() / to_json())

  # 只分析前 N 章 (快速预览)
  result = deconstruct_novel(novel_text, max_chapters=20)
"""
from __future__ import annotations

import json
import re
import sys
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from xiaoshuo import PROJECT_ROOT
from xiaoshuo.infra.logging_config import get_logger
from xiaoshuo.pipeline.text_utils import (
    count_chinese as _count_chinese,
    split_paragraphs as _split_paragraphs,
    split_sentences as _split_sentences,
    count_exclamations as _count_exclamations,
    extract_dialogues as _extract_dialogues,
    read_file_multi_encoding as _read_file,
    parse_cn_num as _parse_cn_num,
)

logger = get_logger("deconstruct")


# ============================================================
# 章节分割
# ============================================================

# 匹配 "第X章" / "第X回" / "第X节" / "Chapter X"
_CHAPTER_PAT = re.compile(
    r'^[\s]*第[\s]*([零一二三四五六七八九十百千万0-9]+)[\s]*[章回节卷部篇][\s:：]*(.*)$',
    re.MULTILINE,
)
_CHAPTER_PAT_EN = re.compile(
    r'^[\s]*Chapter[\s]*(\d+)[\s:：]*(.*)$',
    re.MULTILINE | re.IGNORECASE,
)


@dataclass
class ChapterInfo:
    """单章信息。"""
    index: int               # 章节序号 (从1开始)
    title: str               # 章节标题
    text: str                # 章节正文
    char_count: int          # 中文字数
    para_count: int          # 段落数
    dialogue_ratio: float    # 对话占比 (0-1)
    exclamation_density: float  # 感叹号密度 (个/千字)
    emotion_intensity: float    # 情绪强度 (0-1, 综合指标)


def split_chapters(text: str) -> list[ChapterInfo]:
    """将全文按章节分割。

    支持 "第X章" / "第X回" / "Chapter X" 格式。

    Returns:
        ChapterInfo 列表 (从第1章开始)
    """
    # 合并两种匹配
    matches = list(_CHAPTER_PAT.finditer(text))
    if not matches:
        matches = list(_CHAPTER_PAT_EN.finditer(text))

    if not matches:
        # 无章节标记 → 整体作为第1章
        logger.warning("未检测到章节标记，将全文作为单章处理")
        return [_build_chapter_info(1, "全文", text)]

    chapters: list[ChapterInfo] = []
    for i, m in enumerate(matches):
        ch_num = _parse_cn_num(m.group(1))
        title = m.group(2).strip() if m.group(2) else f"第{ch_num}章"
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        ch_text = text[start:end].strip()
        chapters.append(_build_chapter_info(ch_num, title, ch_text))

    return chapters


def _build_chapter_info(index: int, title: str, text: str) -> ChapterInfo:
    """构建单章信息 (统计指标)。"""
    char_count = _count_chinese(text)
    paras = _split_paragraphs(text)
    para_count = len(paras)
    dialogues = _extract_dialogues(text)
    dialogue_chars = sum(len(d) for d in dialogues)
    dialogue_ratio = dialogue_chars / max(char_count, 1)
    exclam_count = _count_exclamations(text)
    exclamation_density = exclam_count / max(char_count / 1000, 0.1)
    # 情绪强度: 感叹号密度归一化 + 对话占比加权
    emotion_intensity = min(1.0, exclamation_density / 20 * 0.6 + dialogue_ratio * 0.4)

    return ChapterInfo(
        index=index,
        title=title,
        text=text,
        char_count=char_count,
        para_count=para_count,
        dialogue_ratio=round(dialogue_ratio, 3),
        exclamation_density=round(exclamation_density, 2),
        emotion_intensity=round(emotion_intensity, 3),
    )


# ============================================================
# 1. 题材标签提取
# ============================================================

# 题材关键词映射
_GENRE_KEYWORDS = {
    "玄幻": ["修炼", "境界", "灵力", "丹药", "法宝", "宗门", "渡劫", "元婴", "筑基", "化神"],
    "都市": ["公司", "总裁", "商战", "都市", "豪门", "都市生活", "白领"],
    "科幻": ["星际", "飞船", "量子", "基因", "人工智能", "赛博", "机甲", "虫族"],
    "悬疑": ["案件", "侦探", "推理", "凶手", "嫌疑人", "尸检", "线索"],
    "历史": ["朝廷", "皇帝", "将军", "丞相", "王朝", "科举", "藩镇"],
    "末世": ["丧尸", "末日", "变异", "避难所", "物资", "幸存者", "废土"],
    "游戏": ["副本", "玩家", "NPC", "等级", "技能", "装备", "经验值", "公会"],
    "仙侠": ["仙", "剑修", "渡劫", "飞升", "仙界", "道侣", "宗门"],
    "奇幻": ["魔法", "精灵", "龙", "骑士", "法师", "咒语", "神殿"],
    "无限流": ["副本", "主神", "任务", "积分", "规则", "轮回"],
    "洪荒": ["洪荒", "圣人", "大能", "天道", "混沌", "盘古", "女娲"],
    "同人": ["穿越", "原著", "角色名", "原作"],
}

# 爽点类型关键词
_PLEASURE_TYPES = {
    "退婚流": ["退婚", "未婚妻", "悔婚", "上门女婿"],
    "签到流": ["签到", "打卡", "每日奖励", "签到系统"],
    "苟道流": ["苟", "低调", "隐藏实力", "扮猪吃虎"],
    "系统流": ["系统", "面板", "任务", "叮咚", "宿主"],
    "重生流": ["重生", "上一世", "前世记忆", "回到过去"],
    "穿越流": ["穿越", "异世界", "现代人", "灵魂附体"],
    "无敌流": ["无敌", "一拳", "秒杀", "碾压", "降维打击"],
    "凡人流": ["凡人", "资质平庸", "一步步", "脚踏实地"],
}

# 情绪基调关键词
_MOOD_KEYWORDS = {
    "热血": ["战斗", "燃烧", "突破", "逆袭", "不屈", "热血"],
    "黑暗": ["黑暗", "残酷", "背叛", "杀戮", "绝望", "深渊"],
    "轻松": ["搞笑", "日常", "轻松", "吐槽", "欢乐", "摸鱼"],
    "压抑": ["压抑", "憋屈", "隐忍", "蛰伏", "屈辱"],
    "爽快": ["爽", "打脸", "装逼", "逆袭", "震惊"],
}


@dataclass
class GenreTags:
    """题材标签。"""
    main_genre: str                    # 主题材
    sub_genres: list[str]              # 副题材 (1-3个)
    pleasure_type: str                 # 核心爽点类型
    mood: str                          # 情绪基调
    tags: list[str]                    # 通用标签 (3-5个)
    opening_hook: str                  # 开头Hook分析 (前300字)
    first_climax_chapter: int          # 第一个小高潮位置
    first_climax_desc: str             # 第一个小高潮描述
    major_climax_chapter: int          # 第一个大高潮位置
    major_climax_desc: str             # 第一个大高潮描述
    rhythm_curve: list[dict]           # 节奏曲线 (每5章采样)


def _detect_genre(text: str) -> tuple[str, list[str]]:
    """检测主题材和副题材。"""
    scores = {}
    for genre, keywords in _GENRE_KEYWORDS.items():
        score = sum(text.count(kw) for kw in keywords)
        if score > 0:
            scores[genre] = score

    if not scores:
        return "未知", []

    sorted_genres = sorted(scores.items(), key=lambda x: -x[1])
    main = sorted_genres[0][0]
    sub = [g for g, _ in sorted_genres[1:4] if scores[g] >= scores[main] * 0.2]
    return main, sub


def _detect_pleasure_type(text: str) -> str:
    """检测核心爽点类型。"""
    scores = {}
    for ptype, keywords in _PLEASURE_TYPES.items():
        score = sum(text.count(kw) for kw in keywords)
        if score > 0:
            scores[ptype] = score

    if not scores:
        return "未知"
    return max(scores, key=scores.get)


def _detect_mood(text: str) -> str:
    """检测情绪基调。"""
    scores = {}
    for mood, keywords in _MOOD_KEYWORDS.items():
        score = sum(text.count(kw) for kw in keywords)
        if score > 0:
            scores[mood] = score

    if not scores:
        return "未知"
    return max(scores, key=scores.get)


def _analyze_opening_hook(text: str) -> str:
    """分析开头Hook (前300字)。"""
    opening = text[:500]  # 取前500字符，统计约300中文字
    char_count = _count_chinese(opening)

    hooks = []
    if any(kw in opening for kw in ["穿越", "重生", "醒来"]):
        hooks.append("穿越/重生开局，快速进入异世界")
    if any(kw in opening for kw in ["系统", "面板", "叮咚"]):
        hooks.append("系统开局，金手指前置展示")
    if any(kw in opening for kw in ["退婚", "羞辱", "看不起"]):
        hooks.append("退婚/受辱开局，制造逆袭期待")
    if any(kw in opening for kw in ["死", "尸体", "血"]):
        hooks.append("悬念/危机开局，直接抛出冲突")
    if _count_exclamations(opening) > 5:
        hooks.append("高情绪密度开局，感叹号密集")

    if not hooks:
        # 检查开头信息密度
        if char_count > 200 and _split_paragraphs(opening):
            hooks.append("平稳叙述开局，逐步铺设世界观")
        else:
            hooks.append("开头节奏较慢，信息密度偏低")

    return f"前{char_count}字: " + "；".join(hooks)


def _find_climax(chapters: list[ChapterInfo]) -> tuple[int, str, int, str]:
    """找到第一个小高潮和第一个大高潮。

    高潮判定: 情绪强度 + 感叹号密度 + 字数（大场面通常字数更多）

    Returns:
        (小高潮章节, 小高潮描述, 大高潮章节, 大高潮描述)
    """
    if len(chapters) < 3:
        return 1, chapters[0].title if chapters else "", 1, chapters[0].title if chapters else ""

    # 计算每章的"高潮分数"
    scores = []
    for ch in chapters:
        score = ch.emotion_intensity * 0.5 + min(ch.exclamation_density / 20, 1.0) * 0.3
        # 字数加权 (超过平均字数的章节更可能是大场面)
        scores.append(score)

    avg_score = statistics.mean(scores) if scores else 0

    # 小高潮: 第一个超过 avg * 1.3 的章节
    first_climax_idx = 0
    first_climax_desc = ""
    for i, (ch, score) in enumerate(zip(chapters, scores)):
        if score > avg_score * 1.3:
            first_climax_idx = ch.index
            first_climax_desc = ch.title
            break

    # 大高潮: 全书情绪强度最高的章节
    major_climax_idx = 0
    major_climax_desc = ""
    if scores:
        max_idx = scores.index(max(scores))
        major_climax_idx = chapters[max_idx].index
        major_climax_desc = chapters[max_idx].title

    return first_climax_idx, first_climax_desc, major_climax_idx, major_climax_desc


def _build_rhythm_curve(chapters: list[ChapterInfo]) -> list[dict]:
    """构建节奏曲线 (每5章采样)。"""
    curve = []
    for i in range(0, len(chapters), 5):
        batch = chapters[i:i + 5]
        if not batch:
            break
        avg_intensity = statistics.mean([ch.emotion_intensity for ch in batch])
        avg_dialogue = statistics.mean([ch.dialogue_ratio for ch in batch])
        avg_chars = statistics.mean([ch.char_count for ch in batch])
        curve.append({
            "chapter_range": f"{batch[0].index}-{batch[-1].index}",
            "emotion": round(avg_intensity, 3),
            "dialogue_ratio": round(avg_dialogue, 3),
            "avg_chars": int(avg_chars),
        })
    return curve


def extract_genre_tags(text: str, chapters: list[ChapterInfo]) -> GenreTags:
    """提取题材标签。"""
    main_genre, sub_genres = _detect_genre(text)
    pleasure_type = _detect_pleasure_type(text)
    mood = _detect_mood(text)

    # 通用标签
    tags = [main_genre]
    if pleasure_type != "未知":
        tags.append(pleasure_type)
    tags.append(mood)
    tags.extend(sub_genres[:2])
    tags = tags[:5]

    opening_hook = _analyze_opening_hook(text)
    first_climax_ch, first_climax_desc, major_climax_ch, major_climax_desc = _find_climax(chapters)
    rhythm_curve = _build_rhythm_curve(chapters)

    return GenreTags(
        main_genre=main_genre,
        sub_genres=sub_genres,
        pleasure_type=pleasure_type,
        mood=mood,
        tags=tags,
        opening_hook=opening_hook,
        first_climax_chapter=first_climax_ch,
        first_climax_desc=first_climax_desc,
        major_climax_chapter=major_climax_ch,
        major_climax_desc=major_climax_desc,
        rhythm_curve=rhythm_curve,
    )


# ============================================================
# 2. 结构拆解
# ============================================================

@dataclass
class StructureDeconstruction:
    """结构拆解。"""
    protagonist_design: dict           # 主角人设
    antagonist_template: dict          # 反派模板
    supporting_roles: list[dict]       # 配角功能列表
    plot_structure: str                # 情节结构类型
    total_chapters: int                # 总章数
    total_chars: int                   # 总字数
    avg_chapter_chars: int             # 平均每章字数
    chapter_length_distribution: str   # 章节长度分布特征


# 角色提取模式 (从对话和叙述中提取角色名)
_NAME_PAT_CN = re.compile(r'[\u4e00-\u9fff]{2,4}(?=道|说|想|笑|怒|叹|问|喊|吼)')
_ROLE_KEYWORDS = {
    "主角": ["主角", "男主", "女主", "我"],
    "反派": ["反派", "敌人", "对手", "魔头", "boss"],
    "配角": ["兄弟", "朋友", "师父", "师妹", "师姐", "同伴"],
}


def _extract_characters(chapters: list[ChapterInfo], max_count: int = 20) -> list[dict]:
    """从文本中提取角色列表。"""
    name_counter: Counter = Counter()

    for ch in chapters[:50]:  # 只分析前50章提取角色
        # 从对话标记中提取
        for m in _NAME_PAT_CN.finditer(ch.text):
            name = m.group()
            if 2 <= len(name) <= 4 and name not in {"不知道", "怎么说", "为什么", "做什么",
                                                      "不出来", "地看着", "地笑", "地说",
                                                      "的话", "的时候", "的地方"}:
                name_counter[name] += 1

    # 取出现频率最高的角色
    top_names = name_counter.most_common(max_count)
    characters = []
    for i, (name, count) in enumerate(top_names):
        role = "protagonist" if i == 0 else ("antagonist" if i == 1 and count > 20 else "supporting")
        characters.append({
            "name": name,
            "appearances": count,
            "role": role,
        })

    return characters


def _detect_plot_structure(chapters: list[ChapterInfo]) -> str:
    """检测情节结构类型。"""
    if not chapters:
        return "未知"

    # 根据情绪曲线判断结构类型
    intensities = [ch.emotion_intensity for ch in chapters]
    if not intensities:
        return "未知"

    # 检测是否有明显的"上升-高潮-回落"模式
    if len(intensities) >= 10:
        mid = len(intensities) // 2
        first_half_avg = statistics.mean(intensities[:mid])
        second_half_avg = statistics.mean(intensities[mid:])
        max_idx = intensities.index(max(intensities))

        if max_idx > len(intensities) * 0.6:
            return "延迟高潮型 (渐入佳境)"
        elif max_idx < len(intensities) * 0.3:
            return "前置高潮型 (先声夺人)"
        elif second_half_avg > first_half_avg * 1.3:
            return "上升曲线型 (持续升温)"
        else:
            return "波浪起伏型 (多高潮交替)"
    else:
        return "短篇结构 (章节较少)"


def _analyze_chapter_distribution(chapters: list[ChapterInfo]) -> str:
    """分析章节长度分布。"""
    if not chapters:
        return "未知"

    char_counts = [ch.char_count for ch in chapters]
    avg = statistics.mean(char_counts)
    stdev = statistics.stdev(char_counts) if len(char_counts) > 1 else 0
    cv = stdev / avg if avg > 0 else 0

    if avg < 1500:
        length_type = "短章"
    elif avg < 3000:
        length_type = "中章"
    elif avg < 5000:
        length_type = "标准章"
    else:
        length_type = "长章"

    if cv < 0.15:
        uniformity = "均匀"
    elif cv < 0.3:
        uniformity = "较均匀"
    else:
        uniformity = "波动大"

    return f"{length_type} (均{int(avg)}字, {uniformity}, CV={cv:.2f})"


def extract_structure(chapters: list[ChapterInfo], characters: list[dict]) -> StructureDeconstruction:
    """提取结构拆解。"""
    # 主角人设
    protagonist = characters[0] if characters else {"name": "未知", "appearances": 0, "role": "protagonist"}
    protagonist_design = {
        "name": protagonist["name"],
        "appearances": protagonist["appearances"],
        "core_motivation": "待补充 (需 LLM 或人工标注)",
        "flaw": "待补充",
        "golden_finger": "待补充",
    }

    # 反派模板
    antagonists = [c for c in characters if c["role"] == "antagonist"]
    antagonist_template = {
        "name": antagonists[0]["name"] if antagonists else "未检测到明确反派",
        "motivation_depth": "待补充 (动机是否立体？非纯恶？)",
        "appears_in_chapter": "待补充",
    }

    # 配角功能
    supporting = [c for c in characters if c["role"] == "supporting"][:10]
    supporting_roles = [
        {
            "name": s["name"],
            "appearances": s["appearances"],
            "function": "待补充 (工具性角色？推动剧情？衬托主角？)",
        }
        for s in supporting
    ]

    plot_structure = _detect_plot_structure(chapters)
    total_chars = sum(ch.char_count for ch in chapters)
    avg_chars = int(total_chars / max(len(chapters), 1))
    distribution = _analyze_chapter_distribution(chapters)

    return StructureDeconstruction(
        protagonist_design=protagonist_design,
        antagonist_template=antagonist_template,
        supporting_roles=supporting_roles,
        plot_structure=plot_structure,
        total_chapters=len(chapters),
        total_chars=total_chars,
        avg_chapter_chars=avg_chars,
        chapter_length_distribution=distribution,
    )


# ============================================================
# 3. 人物拆解
# ============================================================

@dataclass
class CharacterDeconstruction:
    """人物拆解。"""
    characters: list[dict]             # 角色列表 (含出现频率)
    character_arcs: list[dict]         # 角色弧光 (情绪变化轨迹)
    relationship_network: list[dict]   # 关系网 (共现关系)
    motivation_chain: str              # 动机链分析


def _extract_character_arcs(chapters: list[ChapterInfo], characters: list[dict]) -> list[dict]:
    """提取角色弧光 (情绪变化轨迹)。"""
    arcs = []
    for char in characters[:5]:  # 只分析前5个角色
        name = char["name"]
        # 在每5章区间统计该角色的情绪强度
        arc_points = []
        for i in range(0, len(chapters), 5):
            batch = chapters[i:i + 5]
            batch_text = " ".join(ch.text for ch in batch)
            if name in batch_text:
                # 统计该角色在此区间的出现次数和周围情绪
                count = batch_text.count(name)
                exclam = _count_exclamations(batch_text)
                intensity = min(1.0, count / 20 * 0.5 + exclam / max(_count_chinese(batch_text) / 1000, 0.1) * 0.5)
                arc_points.append({
                    "range": f"{batch[0].index}-{batch[-1].index}",
                    "intensity": round(intensity, 3),
                })
            else:
                arc_points.append({
                    "range": f"{batch[0].index}-{batch[-1].index}",
                    "intensity": 0.0,
                })

        arcs.append({
            "name": name,
            "arc_points": arc_points,
            "trend": _detect_arc_trend(arc_points),
        })
    return arcs


def _detect_arc_trend(points: list[dict]) -> str:
    """检测弧光趋势。"""
    if len(points) < 2:
        return "数据不足"
    intensities = [p["intensity"] for p in points]
    first_half = statistics.mean(intensities[:len(intensities) // 2])
    second_half = statistics.mean(intensities[len(intensities) // 2:])

    if second_half > first_half * 1.3:
        return "上升弧光 (越来越重要)"
    elif second_half < first_half * 0.7:
        return "下降弧光 (逐渐淡出)"
    else:
        return "平稳弧光 (戏份稳定)"


def _extract_relationships(chapters: list[ChapterInfo], characters: list[dict]) -> list[dict]:
    """提取角色关系网 (共现关系)。"""
    if len(characters) < 2:
        return []

    relationships = []
    char_names = [c["name"] for c in characters[:10]]

    for i, name1 in enumerate(char_names):
        for name2 in char_names[i + 1:]:
            co_occurrence = 0
            for ch in chapters[:50]:
                if name1 in ch.text and name2 in ch.text:
                    co_occurrence += 1
            if co_occurrence > 0:
                relationships.append({
                    "char1": name1,
                    "char2": name2,
                    "co_chapters": co_occurrence,
                    "strength": "强" if co_occurrence > 10 else ("中" if co_occurrence > 3 else "弱"),
                })

    return sorted(relationships, key=lambda x: -x["co_chapters"])[:15]


def extract_characters_analysis(chapters: list[ChapterInfo]) -> CharacterDeconstruction:
    """提取人物拆解。"""
    characters = _extract_characters(chapters)
    arcs = _extract_character_arcs(chapters, characters)
    relationships = _extract_relationships(chapters, characters)

    return CharacterDeconstruction(
        characters=characters,
        character_arcs=arcs,
        relationship_network=relationships,
        motivation_chain="待补充 (需结合 canon 设定或 LLM 分析角色动机链)",
    )


# ============================================================
# 4. 可借鉴元素
# ============================================================

@dataclass
class BorrowableElements:
    """可借鉴元素 (非抄袭)。"""
    structure_borrow: list[dict]       # 结构借鉴
    emotion_borrow: list[dict]         # 情绪借鉴
    dialogue_borrow: list[dict]        # 台词借鉴
    technique_highlights: list[str]    # 技法亮点


def _find_structure_borrow(chapters: list[ChapterInfo]) -> list[dict]:
    """找结构借鉴点 (反转手法、节奏控制)。"""
    borrows = []

    # 找情绪反转最大的章节 (压抑→释放)
    for i in range(1, len(chapters)):
        prev_intensity = chapters[i - 1].emotion_intensity
        curr_intensity = chapters[i].emotion_intensity
        if prev_intensity < 0.3 and curr_intensity > 0.6:
            borrows.append({
                "chapter": chapters[i].index,
                "type": "压抑-释放反转",
                "description": f"第{chapters[i-1].index}章压抑({prev_intensity:.2f}) → 第{chapters[i].index}章释放({curr_intensity:.2f})",
            })

    # 找字数突变 (可能是大场面)
    char_counts = [ch.char_count for ch in chapters]
    if char_counts:
        avg = statistics.mean(char_counts)
        for ch in chapters:
            if ch.char_count > avg * 1.5:
                borrows.append({
                    "chapter": ch.index,
                    "type": "大场面章节",
                    "description": f"第{ch.index}章字数({ch.char_count})远超平均({int(avg)})，可能是重要场景",
                })

    return borrows[:10]


def _find_emotion_borrow(chapters: list[ChapterInfo]) -> list[dict]:
    """找情绪借鉴点。"""
    borrows = []

    # 找情绪最高的章节
    sorted_by_emotion = sorted(chapters, key=lambda ch: -ch.emotion_intensity)
    for ch in sorted_by_emotion[:5]:
        borrows.append({
            "chapter": ch.index,
            "title": ch.title,
            "emotion_intensity": ch.emotion_intensity,
            "description": f"第{ch.index}章情绪强度{ch.emotion_intensity:.2f}，感叹号密度{ch.exclamation_density}",
        })

    return borrows


def _find_dialogue_borrow(chapters: list[ChapterInfo]) -> list[dict]:
    """找台词借鉴点 (对话密度高的章节)。"""
    borrows = []

    sorted_by_dialogue = sorted(chapters, key=lambda ch: -ch.dialogue_ratio)
    for ch in sorted_by_dialogue[:5]:
        if ch.dialogue_ratio > 0.2:
            borrows.append({
                "chapter": ch.index,
                "title": ch.title,
                "dialogue_ratio": ch.dialogue_ratio,
                "description": f"第{ch.index}章对话占比{ch.dialogue_ratio:.1%}，台词密集",
            })

    return borrows


def _find_technique_highlights(chapters: list[ChapterInfo]) -> list[str]:
    """找技法亮点。"""
    highlights = []

    # 短句密集 (快节奏)
    short_chapters = [ch for ch in chapters if ch.para_count > 50 and ch.char_count < 2000]
    if short_chapters:
        highlights.append(f"快节奏短章: {len(short_chapters)}个章节使用短段落高密度叙事")

    # 长章大场面
    long_chapters = [ch for ch in chapters if ch.char_count > 5000]
    if long_chapters:
        highlights.append(f"大场面长章: {len(long_chapters)}个章节超过5000字，适合重要场景铺展")

    # 对话驱动
    dialogue_heavy = [ch for ch in chapters if ch.dialogue_ratio > 0.3]
    if dialogue_heavy:
        highlights.append(f"对话驱动: {len(dialogue_heavy)}个章节对话占比>30%，适合角色塑造")

    # 情绪波动大
    if len(chapters) >= 10:
        intensities = [ch.emotion_intensity for ch in chapters]
        cv = statistics.stdev(intensities) / max(statistics.mean(intensities), 0.01)
        if cv > 0.5:
            highlights.append(f"情绪波动大: CV={cv:.2f}，节奏张弛有度")
        else:
            highlights.append(f"情绪平稳: CV={cv:.2f}，适合慢热型叙事")

    if not highlights:
        highlights.append("未检测到明显技法特征")

    return highlights


def extract_borrowable(chapters: list[ChapterInfo]) -> BorrowableElements:
    """提取可借鉴元素。"""
    return BorrowableElements(
        structure_borrow=_find_structure_borrow(chapters),
        emotion_borrow=_find_emotion_borrow(chapters),
        dialogue_borrow=_find_dialogue_borrow(chapters),
        technique_highlights=_find_technique_highlights(chapters),
    )


# ============================================================
# 5. 避雷清单
# ============================================================

@dataclass
class WarningList:
    """避雷清单。"""
    reader_complaints: list[str]       # 读者可能吐槽的点
    collapse_risks: list[str]          # 后期崩坏风险
    quality_warnings: list[str]        # 质量警告


# 读者吐槽常见模式
_COMPLAINT_PATTERNS = {
    "水文": ["流水账", "无关紧要", "凑字数", "日常水"],
    "重复": ["重复", "套路", "又来", "似曾相识"],
    "节奏拖沓": ["拖沓", "慢热", "太慢", "无聊"],
    "人物扁平": ["工具人", "纸片人", "脸谱化"],
}

# 后期崩坏风险模式
_COLLAPSE_PATTERNS = {
    "战力膨胀": ["突破", "升级", "更强", "境界"],
    "角色遗忘": ["消失", "忘记", "再没出现"],
    "逻辑矛盾": ["矛盾", "前后不一", "设定冲突"],
    "烂尾倾向": ["仓促", "烂尾", "草草收场"],
}


def _detect_complaints(chapters: list[ChapterInfo]) -> list[str]:
    """检测读者可能吐槽的点。"""
    complaints = []

    # 检测水文 (字数少且情绪低的章节)
    water_chapters = [ch for ch in chapters if ch.char_count < 1000 and ch.emotion_intensity < 0.2]
    if water_chapters:
        complaints.append(f"疑似水文: {len(water_chapters)}个章节字数<1000且情绪强度低")

    # 检测节奏拖沓 (连续5章以上情绪强度低于0.3)
    low_streak = 0
    max_low_streak = 0
    for ch in chapters:
        if ch.emotion_intensity < 0.3:
            low_streak += 1
            max_low_streak = max(max_low_streak, low_streak)
        else:
            low_streak = 0
    if max_low_streak >= 5:
        complaints.append(f"节奏拖沓: 连续{max_low_streak}章情绪强度低于0.3，可能导致读者流失")

    # 检测对话过少 (角色塑造不足)
    low_dialogue = [ch for ch in chapters if ch.dialogue_ratio < 0.1]
    if len(low_dialogue) > len(chapters) * 0.5:
        complaints.append(f"对话偏少: {len(low_dialogue)}/{len(chapters)}章对话占比<10%，角色塑造可能不足")

    # 检测开头是否吸引人
    if chapters:
        first_ch = chapters[0]
        if first_ch.emotion_intensity < 0.3:
            complaints.append("开头吸引力不足: 第1章情绪强度偏低，可能无法留住读者")

    return complaints if complaints else ["未检测到明显读者吐槽点"]


def _detect_collapse_risks(chapters: list[ChapterInfo]) -> list[str]:
    """检测后期崩坏风险。"""
    risks = []

    if len(chapters) < 20:
        return ["章节数较少，无法检测后期崩坏风险"]

    # 战力膨胀: 后半部分感叹号密度显著增加
    mid = len(chapters) // 2
    first_half_exclam = statistics.mean([ch.exclamation_density for ch in chapters[:mid]])
    second_half_exclam = statistics.mean([ch.exclamation_density for ch in chapters[mid:]])
    if second_half_exclam > first_half_exclam * 2:
        risks.append("战力膨胀风险: 后半部分情绪密度显著增加，可能存在战力膨胀")

    # 角色遗忘: 前半部分出现频率高的角色在后半部分消失
    # (这里简化处理，实际需要角色追踪)
    mid_intensity = statistics.mean([ch.emotion_intensity for ch in chapters[mid:]])
    first_intensity = statistics.mean([ch.emotion_intensity for ch in chapters[:mid]])
    if mid_intensity < first_intensity * 0.5:
        risks.append("后期疲软风险: 后半部分情绪强度显著下降")

    # 章节长度不均
    char_counts = [ch.char_count for ch in chapters]
    cv = statistics.stdev(char_counts) / max(statistics.mean(char_counts), 1)
    if cv > 0.5:
        risks.append(f"章节长度波动大: CV={cv:.2f}，可能影响阅读体验")

    # 末尾章节字数骤降 (仓促收尾)
    if len(chapters) >= 5:
        last_5_avg = statistics.mean([ch.char_count for ch in chapters[-5:]])
        overall_avg = statistics.mean(char_counts)
        if last_5_avg < overall_avg * 0.5:
            risks.append("烂尾风险: 末尾章节字数骤降，可能仓促收尾")

    return risks if risks else ["未检测到明显后期崩坏风险"]


def _detect_quality_warnings(chapters: list[ChapterInfo]) -> list[str]:
    """检测质量警告。"""
    warnings = []

    # 章节过短
    short_chapters = [ch for ch in chapters if ch.char_count < 500]
    if short_chapters:
        warnings.append(f"过短章节: {len(short_chapters)}个章节不足500字")

    # 章节过长
    long_chapters = [ch for ch in chapters if ch.char_count > 8000]
    if long_chapters:
        warnings.append(f"过长章节: {len(long_chapters)}个章节超过8000字，读者疲劳风险")

    # 段落过少 (排版问题)
    low_para = [ch for ch in chapters if ch.para_count < 5]
    if low_para:
        warnings.append(f"段落过少: {len(low_para)}个章段落数<5，可能是排版问题")

    return warnings if warnings else ["未检测到质量警告"]


def extract_warnings(chapters: list[ChapterInfo]) -> WarningList:
    """提取避雷清单。"""
    return WarningList(
        reader_complaints=_detect_complaints(chapters),
        collapse_risks=_detect_collapse_risks(chapters),
        quality_warnings=_detect_quality_warnings(chapters),
    )


# ============================================================
# 汇总: DeconstructionResult
# ============================================================

@dataclass
class DeconstructionResult:
    """拆文结果 (五段式)。"""
    genre_tags: GenreTags
    structure: StructureDeconstruction
    characters: CharacterDeconstruction
    borrowable: BorrowableElements
    warnings: WarningList
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """转为字典 (JSON 可序列化)。"""
        return {
            "genre_tags": {
                "main_genre": self.genre_tags.main_genre,
                "sub_genres": self.genre_tags.sub_genres,
                "pleasure_type": self.genre_tags.pleasure_type,
                "mood": self.genre_tags.mood,
                "tags": self.genre_tags.tags,
                "opening_hook": self.genre_tags.opening_hook,
                "first_climax": {
                    "chapter": self.genre_tags.first_climax_chapter,
                    "desc": self.genre_tags.first_climax_desc,
                },
                "major_climax": {
                    "chapter": self.genre_tags.major_climax_chapter,
                    "desc": self.genre_tags.major_climax_desc,
                },
                "rhythm_curve": self.genre_tags.rhythm_curve,
            },
            "structure": {
                "protagonist_design": self.structure.protagonist_design,
                "antagonist_template": self.structure.antagonist_template,
                "supporting_roles": self.structure.supporting_roles,
                "plot_structure": self.structure.plot_structure,
                "total_chapters": self.structure.total_chapters,
                "total_chars": self.structure.total_chars,
                "avg_chapter_chars": self.structure.avg_chapter_chars,
                "chapter_length_distribution": self.structure.chapter_length_distribution,
            },
            "characters": {
                "characters": self.characters.characters,
                "character_arcs": self.characters.character_arcs,
                "relationship_network": self.characters.relationship_network,
                "motivation_chain": self.characters.motivation_chain,
            },
            "borrowable": {
                "structure_borrow": self.borrowable.structure_borrow,
                "emotion_borrow": self.borrowable.emotion_borrow,
                "dialogue_borrow": self.borrowable.dialogue_borrow,
                "technique_highlights": self.borrowable.technique_highlights,
            },
            "warnings": {
                "reader_complaints": self.warnings.reader_complaints,
                "collapse_risks": self.warnings.collapse_risks,
                "quality_warnings": self.warnings.quality_warnings,
            },
            "metadata": self.metadata,
        }

    def to_json(self, indent: int = 2) -> str:
        """转为 JSON 字符串。"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


# ============================================================
# 主入口
# ============================================================

def deconstruct_novel(
    text: str,
    max_chapters: Optional[int] = None,
) -> DeconstructionResult:
    """拆文主入口。

    Args:
        text: 小说全文
        max_chapters: 最多分析多少章 (None=全部, 用于快速预览)

    Returns:
        DeconstructionResult (五段式拆文结果)
    """
    logger.info("开始拆文分析...")

    # 1. 章节分割
    chapters = split_chapters(text)
    if max_chapters:
        chapters = chapters[:max_chapters]
    logger.info(f"分割为 {len(chapters)} 章")

    # 2. 五段式提取
    genre_tags = extract_genre_tags(text, chapters)
    logger.info(f"题材: {genre_tags.main_genre} | 爽点: {genre_tags.pleasure_type} | 基调: {genre_tags.mood}")

    characters_analysis = extract_characters_analysis(chapters)
    logger.info(f"提取角色: {len(characters_analysis.characters)}个")

    structure = extract_structure(chapters, characters_analysis.characters)
    logger.info(f"结构: {structure.plot_structure} | 均{structure.avg_chapter_chars}字/章")

    borrowable = extract_borrowable(chapters)
    logger.info(f"借鉴点: 结构{len(borrowable.structure_borrow)} 情绪{len(borrowable.emotion_borrow)} 台词{len(borrowable.dialogue_borrow)}")

    warnings = extract_warnings(chapters)
    logger.info(f"避雷: 吐槽{len(warnings.reader_complaints)} 风险{len(warnings.collapse_risks)} 警告{len(warnings.quality_warnings)}")

    metadata = {
        "tool": "deconstruct_novel.py",
        "version": "1.0",
        "chapters_analyzed": len(chapters),
        "total_chars": sum(ch.char_count for ch in chapters),
    }

    return DeconstructionResult(
        genre_tags=genre_tags,
        structure=structure,
        characters=characters_analysis,
        borrowable=borrowable,
        warnings=warnings,
        metadata=metadata,
    )


def deconstruct_file(filepath: str | Path, max_chapters: Optional[int] = None) -> DeconstructionResult:
    """从文件读取小说并拆文。

    Args:
        filepath: 小说文件路径
        max_chapters: 最多分析多少章

    Returns:
        DeconstructionResult
    """
    filepath = Path(filepath)
    logger.info(f"读取文件: {filepath}")
    text = _read_file(filepath)
    return deconstruct_novel(text, max_chapters=max_chapters)


# ============================================================
# CLI
# ============================================================

def _cli():
    """命令行入口。"""
    if len(sys.argv) < 2:
        print("用法: python -m xiaoshuo.tools.deconstruct_novel <小说文件> [--max-chapters N] [--output JSON文件]")
        print("示例: python -m xiaoshuo.tools.deconstruct_novel data/raw/novels/玄幻/某书/某书.txt --max-chapters 50")
        sys.exit(1)

    filepath = sys.argv[1]
    max_chapters = None
    output_path = None

    for i, arg in enumerate(sys.argv[2:], 2):
        if arg == "--max-chapters" and i + 1 < len(sys.argv):
            max_chapters = int(sys.argv[i + 1])
        elif arg == "--output" and i + 1 < len(sys.argv):
            output_path = sys.argv[i + 1]

    result = deconstruct_file(filepath, max_chapters=max_chapters)

    if output_path:
        Path(output_path).write_text(result.to_json(), encoding="utf-8")
        print(f"结果已保存到: {output_path}")
    else:
        print(result.to_json())


if __name__ == "__main__":
    _cli()
