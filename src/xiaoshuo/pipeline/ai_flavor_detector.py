#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ai_flavor_detector.py v2 — AI写作味检测器
=============================================
逆向拆解"去AI味指令"为检测规则，检测正文是否存在AI写作痕迹。

v2 新增 (基于写作技巧量化建议):
  负面规则扩展:
    - 禁用过渡词: "众所周知"、"总而言之"等
    - 禁用外貌描写: "他有一双XX的眼睛"等模板化描写
    - 心理前缀冗余: "他心里想/他不禁感到"等隔阂代词 (v2)
    - 连词剧透: 反转/冲突时刻的"却/但是/然而"提前剧透 (v2)
    - 情绪冗余: "复读机"式情绪形容词+动作+台词重复 (v2)
    - 念台词式直白对话: 缺乏潜台词/暗示/冰山原则的平铺直叙 (v3)
  正面评分（应该做的）:
    - 对话口语化: 短句、语气词、语病
    - 感官细节密度: 动作、气味、触感描写
    - 情绪克制度: 避免直白抒情
    - 生活化闲笔: 无意义日常对话
    - 句式多样性: 非重复句式

配置: config.yaml analysis.ai_flavor_detection
用法: python -m xiaoshuo.pipeline.ai_flavor_detector --text <file> [--json] [--llm]
"""

import json
import re
import statistics
import sys
from pathlib import Path
from xiaoshuo.infra.logging_config import get_logger
from xiaoshuo.pipeline.text_utils import count_chinese as _count_chinese

logger = get_logger(__name__)


def _load_config():
    try:
        from xiaoshuo.infra.config_manager import get_config
        cfg = get_config()
        return cfg.get("analysis", {}).get("ai_flavor_detection", {})
    except Exception:
        return {}


# ── 负面规则：禁止项检测 ──

def _check_banned_transitions(text, banned_words):
    """Check for banned transition phrases."""
    hits = {}
    for word in banned_words:
        count = text.count(word)
        if count > 0:
            hits[word] = count
    return hits


def _check_banned_descriptions(text, banned_patterns):
    """Check for banned description patterns."""
    hits = {}
    for pattern in banned_patterns:
        matches = re.findall(re.escape(pattern), text)
        if matches:
            hits[pattern] = len(matches)
    return hits


# ── v2: 心理前缀冗余检测 ──
# "他心里想/他不禁感到十分震惊" → 直接砍掉前缀，改为内心独白或生理反应
# 注意: [他她] 是必选字符，不是可选 — 否则 "心里想" 会被两条模式各匹配一次
MENTAL_PREFIX_PATTERNS = [
    re.compile(r'[他她]心里想[：，:]?'),
    re.compile(r'[他她]不禁感到十分?\w+'),
    re.compile(r'[他她]不由得\w+'),
    re.compile(r'[他她]暗自\w+'),
    re.compile(r'[他她]默默\w+'),
    re.compile(r'[他她]突然意识到'),
    re.compile(r'[他她]这才明白'),
    re.compile(r'[他她]猛然惊觉'),
    re.compile(r'[他她]暗想[：，:]?'),
    re.compile(r'[他她]心想[：，:]?'),
]


def _check_mental_prefix(text):
    """v2: 检测心理前缀冗余 — "他心里想/他不禁感到"等隔阂代词。

    这些前缀在读者和剧情之间造成隔阂，破坏代入感。
    好的写法是直接将心理活动变成内心独白或生理反应。
    """
    hits = 0
    for pat in MENTAL_PREFIX_PATTERNS:
        hits += len(pat.findall(text))
    return hits


# ── v2: 连词剧透检测 ──
# 在反转/冲突时刻，连词("却/但是/然而")等同于"注意，反转来了！"，提前剧透削弱冲击力
CONJUNCTION_SPOILER_PATTERNS = [
    re.compile(r'却(?!是)'),           # "却" (排除"却是"中性用法)
    re.compile(r'但是[^，。]'),         # "但是" 后接非标点 = 转折陈述
    re.compile(r'然而[^，。]'),         # "然而" 同上
    re.compile(r'可是[^，。]'),         # "可是" 同上
    re.compile(r'偏偏[^，。]'),         # "偏偏" = 命运转折
]

# 反转/冲突关键句标记词 — 连词在这些词附近出现时，剧透效应最强
# 注意: "忽然/猛然/骤然" 是极常见副词，几乎每章都有，不能作为反转标记
CRITICAL_MOMENT_MARKERS = [
    re.compile(r'(?:没想到|原来|竟然|居然|不料|谁知|赫然)'),
    re.compile(r'(?:反转|逆袭|翻盘|真相|秘密|暴露|识破|看穿)'),
    re.compile(r'(?:死亡|毁灭|背叛|牺牲|崩溃|失控)'),
]


# ── v3: 全篇显性连接词密度检测 ──
# AI文过度依赖显性连接词（因此/由此可见/首先/其次），人工文更多隐性衔接
# 来源: 160万字样本对比分析
EXPLICIT_CONJUNCTION_WORDS = [
    "因此", "所以", "由此可见", "综上所述", "首先", "其次", "然后",
    "不过", "然而", "但是", "可是", "总之", "另外", "此外",
    "与此同时", "换言之", "显而易见", "毫无疑问",
]


def _check_conjunction_spoiler(text):
    """v2: 检测连词剧透 — 反转/冲突时刻的"却/但是/然而"提前剧透。

    策略: 扫描所有连词位置，检查前后50字内是否有反转/冲突关键句标记词。
    背景/温情段落的连词使用正常，不检测。

    v3 扩展: 同时统计全篇显性连接词密度（每千字），
    AI文密度通常 > 8/千字，人工文 < 5/千字。
    返回格式从 list 改为 dict，包含 spoilers 和 density。
    """
    spoilers = []
    for pat in CONJUNCTION_SPOILER_PATTERNS:
        for m in pat.finditer(text):
            start = max(0, m.start() - 50)
            end = min(len(text), m.end() + 50)
            context = text[start:end]
            # 检查上下文是否有反转/冲突标记
            is_critical = any(marker.search(context) for marker in CRITICAL_MOMENT_MARKERS)
            if is_critical:
                spoilers.append({
                    "word": m.group(),
                    "position": m.start(),
                    "context": context.strip()[:100],
                })

    # v3: 全篇显性连接词密度
    chinese_count = _count_chinese(text)
    conj_total = sum(text.count(w) for w in EXPLICIT_CONJUNCTION_WORDS)
    density_per_1k = round(conj_total / max(chinese_count / 1000, 1), 2)

    return {
        "spoilers": spoilers,
        "explicit_count": conj_total,
        "density_per_1k": density_per_1k,
    }


# ── v2: 情绪冗余检测 ──
# "他心里非常愤怒，猛地一拍桌子，愤怒地大吼道：你给我滚出去！"
# → 能用台词和动作表达的情绪，不应再用形容词说出来
EMOTION_REDUNDANCY_PATTERNS = [
    # 情绪形容词 + 动作 + 情绪形容词 + 台词
    re.compile(r'[他她][^。！？]{0,10}非常\w+，[^。！？]{0,15}地\w+，[^。！？]{0,10}地\w+[：，:]'),
    re.compile(r'[他她][^。！？]{0,10}感到十分?\w+，[^。！？]{0,15}猛地\w+'),
    # 对话中的情绪提示语冗余: "他愤怒地吼道："
    re.compile(r'[，。！？][\s]*[他她][^。！？]{0,8}地\w+道[：，:]'),
    # 连续两个情绪修饰同一动作: "愤怒地猛地"
    re.compile(r'(?:愤怒|激动|焦急|恐惧|悲伤|兴奋|狂怒|暴怒)地(?:猛地|忽然|突然)'),
]


def _check_emotion_redundancy(text):
    """v2: 检测情绪冗余 — "复读机"式情绪形容词+动作+台词重复。

    好的写法: "'你给我滚出去！'他猛地一拍桌子，震得茶杯叮当响"
    差的写法: "他心里非常愤怒，猛地一拍桌子，愤怒地大吼道：你给我滚出去！"
    """
    hits = 0
    examples = []
    for pat in EMOTION_REDUNDANCY_PATTERNS:
        matches = pat.findall(text)
        if matches:
            hits += len(matches)
            examples.extend(matches[:3])  # 保留最多3个示例
    return hits, examples


def _check_perfect_protagonist(text):
    """Check if protagonist is too perfect (no mistakes/hesitation)."""
    mistake_markers = [
        r'(?:失误|犯错|搞砸|失手|判断错误|后悔|愧疚|自责)',
        r'(?:犹豫|迟疑|踌躇|拿不定主意|左右为难|进退两难)',
        r'(?:弱点|软肋|心魔|阴影|不堪|窝囊|狼狈)',
    ]
    chinese_count = _count_chinese(text)
    if chinese_count < 100:
        return True
    hits = sum(len(re.findall(pat, text)) for pat in mistake_markers)
    density = hits / (chinese_count / 1000)
    return density < 0.5  # < 0.5 per 1000 chars = too perfect


def _check_preaching_dialogue(text):
    """Check for preachy/sermon-like dialogue."""
    preaching_markers = [
        r'(?:人生[就才是]|真正的[A-Z\u4e00-\u9fff]+是|最重要[的的是]|你[必须应该要]明白)',
        r'(?:道理|真理|真谛|本质|意义|价值)',
        r'(?:从来[都没]有|永远[都不]会|归根结底|说到底)',
    ]
    chinese_count = _count_chinese(text)
    if chinese_count < 100:
        return 0
    hits = sum(len(re.findall(pat, text)) for pat in preaching_markers)
    return round(hits / (chinese_count / 1000), 2)


# ── v3: 念台词式直白对话检测 (建议文件"冰山法则/对话潜台词"落地) ──
# 好的对话: 潜台词丰富, 角色不直接说心里话
# 差的对话: 念台词, 如"我一定要杀了你为父报仇" — 毫无潜台词
DIRECT_DIALOGUE_PATTERNS = [
    # 直白宣布意图: "我要杀了你/我会找到真相/我绝不放弃"
    re.compile(r'["\u201c\u300c]我(?:一定|绝对|必须|发誓|迟早|早晚).{2,15}[\u3002\uff01\uff1f]?[\u201d\u300d"\u3011]'),
    # 直白宣布情感: "我喜欢你/我恨你/我离不开你"
    re.compile(r'["\u201c\u300c]我(?:喜欢|爱|恨|离不开|不能没有)你[\u3002\uff01\uff1f]?[\u201d\u300d"\u3011]'),
    # 直白宣布身份: "我是XX之子/我是天选之人"
    re.compile(r'["\u201c\u300c]我是(?:.{2,10}之子|.{2,10}传人|天选之人|命中注定)[\u3002\uff01\uff1f]?[\u201d\u300d"\u3011]'),
    # 旁白式台词: "这就是XX的力量/这就是命运"
    re.compile(r'["\u201c\u300c]这就是.{2,15}(?:力量|命运|代价|结局)[\u3002\uff01\uff1f]?[\u201d\u300d"\u3011]'),
]

# 潜台词丰富的对话标志: 反问/比喻/隐喻/省略/转移话题
SUBTEXT_SIGNALS = [
    re.compile(r'[\u201c\u300c"].{0,20}[?\uff1f][\u201d\u300d"\u3011]'),  # 反问
    re.compile(r'[\u201c\u300c"].{0,10}[\u2026\.]{2,}[\u201d\u300d"\u3011]'),  # 省略/停顿
    re.compile(r'[\u201c\u300c"](?:像|如同|好比|好比说|就像是)[\u201d\u300d"\u3011]'),  # 比喻
    re.compile(r'[\u201c\u300c"](?:算了|没什么|不说了|别提了|无所谓)[\u201d\u300d"\u3011]'),  # 转移话题
]


def _check_direct_dialogue(text):
    """v3: 检测念台词式直白对话 — 缺乏潜台词的平铺直叙。

    策略: 检测直白宣布意图/情感/身份的台词, 并与潜台词标志进行比例分析。
    好的对话: 直白台词少, 潜台词标志多
    差的对话: 直白台词多, 潜台词标志少
    """
    direct_hits = []
    for pat in DIRECT_DIALOGUE_PATTERNS:
        for m in pat.finditer(text):
            direct_hits.append(m.group())

    subtext_hits = 0
    for pat in SUBTEXT_SIGNALS:
        subtext_hits += len(pat.findall(text))

    return {
        'direct_count': len(direct_hits),
        'direct_examples': direct_hits[:3],
        'subtext_count': subtext_hits,
    }


# ── 正面规则：加分项评分 ──

# ── v3: 对白占比检测 ──
# 来源: 160万字样本分析 — AI文对白占比极端（全无或全有），人工文自然区间 5%-65%
_DIALOGUE_PATTERN = re.compile(r'[「"『（(]([^」"』）)]+)[」"』）)]')


def _check_dialogue_ratio(text):
    """v3: 检测对白占比是否在自然区间（5%-65%）。

    AI文特征: 对白占比较低（全是叙述）或极高（全是对白）。
    人工文特征: 对白占比在 5%-65% 之间波动。

    Returns:
        dict: ratio, dialogue_chars, total_chars, is_extreme, issue
    """
    total_chars = _count_chinese(text)
    if total_chars < 50:
        return {"ratio": 0.0, "dialogue_chars": 0, "total_chars": total_chars,
                "is_extreme": False, "issue": "文本太短"}

    dialogue_chars = sum(len(m.group(1)) for m in _DIALOGUE_PATTERN.finditer(text))
    ratio = dialogue_chars / total_chars if total_chars > 0 else 0

    is_extreme = False
    issue = "正常"
    if ratio < 0.05:
        is_extreme = True
        issue = "对白过少（<5%），疑似AI纯叙述"
    elif ratio > 0.65:
        is_extreme = True
        issue = "对白过多（>65%），疑似AI对话堆砌"

    return {
        "ratio": round(ratio, 3),
        "dialogue_chars": dialogue_chars,
        "total_chars": total_chars,
        "is_extreme": is_extreme,
        "issue": issue,
    }


def _score_dialogue_naturalness(text):
    """Score dialogue naturalness: short sentences, interjections, colloquial."""
    dialogue_lines = re.findall(r'[「「"]([^」」"]+)[」」"]', text)
    if not dialogue_lines:
        return 0.0

    scores = []
    for line in dialogue_lines:
        score = 0.0
        # Short sentences (< 15 chars) = more natural
        if len(line) <= 15:
            score += 0.3
        elif len(line) <= 25:
            score += 0.15
        # Interjections
        if re.search(r'(?:啊|吧|呢|吗|嘛|呀|哦|嗯|哎|喂|哈|嘿)', line):
            score += 0.2
        # Sentence breaks (commas, ellipsis)
        if re.search(r'[，…\.]{2,}', line):
            score += 0.15
        # No complete formal sentences
        if not re.search(r'^.{20,}[。！？]$', line):
            score += 0.1
        # No preaching
        if not re.search(r'(?:因为|所以|因此|然而|但是|不过|虽然|如果|那么|总之)', line):
            score += 0.1
        scores.append(score)

    return round(statistics.mean(scores) if scores else 0.0, 3)


def _score_sensory_detail(text):
    """Score sensory detail density: action, smell, touch descriptions."""
    sensory_markers = [
        r'(?:闻到|气味|味道|香气|臭味|腥味|刺鼻|浓烈|淡淡)',
        r'(?:触摸|碰到|冰凉|滚烫|粗糙|光滑|柔软|坚硬|湿润|干燥)',
        r'(?:听见|声音|响声|轰鸣|低语|沙沙|咔嚓|砰|啪|嗖)',
        r'(?:看到|瞥见|映入|浮现在|闪烁|昏暗|明亮|刺眼|模糊)',
    ]
    chinese_count = _count_chinese(text)
    if chinese_count < 100:
        return 0.0
    hits = sum(len(re.findall(pat, text)) for pat in sensory_markers)
    density = hits / (chinese_count / 1000)
    return round(min(density / 5.0, 1.0), 3)


def _score_emotional_restraint(text):
    """Score emotional restraint: avoid direct emotional declarations."""
    direct_emotion = [
        r'(?:心痛|心碎|悲伤|难过|痛苦|绝望|崩溃)',
        r'(?:愤怒|暴怒|大怒|狂怒|愤恨)',
        r'(?:激动|兴奋|狂喜|欣喜|雀跃)',
        r'(?:感动|流泪|泪流满面|热泪盈眶|泣不成声)',
    ]
    chinese_count = _count_chinese(text)
    if chinese_count < 100:
        return 0.0
    total_hits = sum(len(re.findall(pat, text)) for pat in direct_emotion)
    density = total_hits / (chinese_count / 1000)
    # Lower density = better restraint
    return round(max(0.0, 1.0 - density / 3.0), 3)


def _score_sentence_variety(text):
    """Score sentence variety: avoid repetitive sentence structures."""
    sentences = re.split(r'[。！？；\n]', text)
    sentences = [s.strip() for s in sentences if len(s.strip()) >= 5]
    if len(sentences) < 5:
        return 0.0

    lengths = [len(s) for s in sentences]
    if len(lengths) >= 5:
        # Coefficient of variation
        mean_len = statistics.mean(lengths)
        if mean_len > 0:
            cv = statistics.stdev(lengths) / mean_len
            return round(min(cv / 0.5, 1.0), 3)
    return 0.0


def _score_life_scenes(text):
    """Score life/non-plot scenes: casual daily moments."""
    life_markers = [
        r'(?:吃饭|做饭|买菜|逛街|散步|喝茶|喝咖啡|喝酒)',
        r'(?:聊天|闲聊|八卦|吐槽|开玩笑|打趣)',
        r'(?:睡觉|起床|洗漱|换衣服|照镜子)',
        r'(?:发呆|走神|心不在焉|无所事事|无所适从)',
    ]
    chinese_count = _count_chinese(text)
    if chinese_count < 100:
        return 0.0
    hits = sum(len(re.findall(pat, text)) for pat in life_markers)
    density = hits / (chinese_count / 1000)
    return round(min(density / 2.0, 1.0), 3)


# ── 综合评分 ──

def detect_ai_flavor(text, config=None):
    """
    Detect AI writing flavor in text.
    Returns dict with negative rule hits, positive dimension scores,
    and overall human_flavor_score (0=AI-like, 100=human-like).
    """
    if config is None:
        config = _load_config()

    negative = config.get("negative_rules", {})
    positive = config.get("positive_dimensions", {})
    llm_cfg = config.get("llm_classifier", {})

    result = {
        "negative_hits": {},
        "positive_scores": {},
        "human_flavor_score": 0,
        "pass": False,
        "details": [],
    }

    chinese_count = _count_chinese(text)

    # ── 负面检测 ──
    banned_words = negative.get("banned_transitions", [])
    if banned_words:
        hits = _check_banned_transitions(text, banned_words)
        if hits:
            result["negative_hits"]["banned_transitions"] = hits
            total = sum(hits.values())
            result["details"].append(f"禁用过渡词: {total}处 ({', '.join(hits.keys())})")

    banned_patterns = negative.get("banned_description_patterns", [])
    if banned_patterns:
        hits = _check_banned_descriptions(text, banned_patterns)
        if hits:
            result["negative_hits"]["banned_descriptions"] = hits
            total = sum(hits.values())
            result["details"].append(f"模板化外貌描写: {total}处")

    perfect = _check_perfect_protagonist(text)
    if perfect:
        result["negative_hits"]["perfect_protagonist"] = True
        result["details"].append("主角过于完美: 缺乏失误/犹豫/弱点描写")

    preaching = _check_preaching_dialogue(text)
    if preaching > 0.3:
        result["negative_hits"]["preaching_dialogue"] = {"density_per_1k": preaching}
        result["details"].append(f"说教对话密度: {preaching}/千字 (偏高)")

    # ── v2: 心理前缀冗余检测 ──
    mental_prefix_count = _check_mental_prefix(text)
    if chinese_count > 0:
        mental_prefix_density = mental_prefix_count / (chinese_count / 1000)
    else:
        mental_prefix_density = 0
    if mental_prefix_count > 0:
        result["negative_hits"]["mental_prefix"] = {
            "count": mental_prefix_count,
            "density_per_1k": round(mental_prefix_density, 2),
        }
        result["details"].append(
            f"心理前缀冗余: {mental_prefix_count}处 ({mental_prefix_density:.1f}/千字) — "
            "建议删除\"他心里想/他不禁感到\"等前缀，改为直接内心独白"
        )

    # ── v2/v3: 连词剧透检测 + 全篇连接词密度 ──
    conj_result = _check_conjunction_spoiler(text)
    conj_spoilers = conj_result["spoilers"]
    conj_density = conj_result["density_per_1k"]
    if conj_spoilers:
        result["negative_hits"]["conjunction_spoiler"] = {
            "count": len(conj_spoilers),
            "examples": [s["context"] for s in conj_spoilers[:3]],
        }
        result["details"].append(
            f"连词剧透: {len(conj_spoilers)}处 — "
            "反转/冲突时刻的\"却/但是/然而\"提前剧透，建议删除让事实直接冲击读者"
        )
    # v3: 全篇连接词密度检测（AI文 > 8/千字，人工文 < 5/千字）
    if conj_density > 8.0:
        result["negative_hits"]["conjunction_density"] = {
            "density_per_1k": conj_density,
            "count": conj_result["explicit_count"],
        }
        result["details"].append(
            f"显性连接词密度: {conj_density}/千字 (AI特征: >8/千字) — "
            "减少\"因此/由此可见/首先/其次\"等显性连接词，改用隐性衔接或自然断裂"
        )

    # ── v2: 情绪冗余检测 ──
    emotion_redundancy_count, emotion_examples = _check_emotion_redundancy(text)
    if emotion_redundancy_count > 0:
        result["negative_hits"]["emotion_redundancy"] = {
            "count": emotion_redundancy_count,
            "examples": emotion_examples,
        }
        result["details"].append(
            f"情绪冗余: {emotion_redundancy_count}处 — "
            "\"复读机\"式情绪形容词+动作+台词重复，建议用台词和动作直接表达情绪"
        )

    # ── v3: 念台词式直白对话检测 ──
    direct_dialogue = _check_direct_dialogue(text)
    if direct_dialogue['direct_count'] > 0:
        result["negative_hits"]["direct_dialogue"] = {
            "count": direct_dialogue['direct_count'],
            "examples": direct_dialogue['direct_examples'],
            "subtext_count": direct_dialogue['subtext_count'],
        }
        ratio_msg = f"(潜台词标志仅{direct_dialogue['subtext_count']}处)" if direct_dialogue['subtext_count'] < 2 else ""
        result["details"].append(
            f"念台词式直白对话: {direct_dialogue['direct_count']}处 {ratio_msg} — "
            "台词缺乏潜台词, 建议用反问/比喻/省略让角色'不说破'"
        )

    # ── v3: 对白占比检测 ──
    # 来源: 160万字样本分析 — 自然区间 5%-65%，极端值疑似AI
    dialogue_info = _check_dialogue_ratio(text)
    result["dialogue_ratio"] = dialogue_info
    if dialogue_info["is_extreme"]:
        result["negative_hits"]["dialogue_ratio"] = {
            "ratio": dialogue_info["ratio"],
            "issue": dialogue_info["issue"],
        }
        result["details"].append(
            f"对白占比异常: {dialogue_info['ratio']:.0%} ({dialogue_info['issue']}) — "
            "自然区间为5%-65%，全无对白或全是对白均为AI特征"
        )

    # ── 正面评分 ──
    pos_scores = {}
    if positive.get("dialogue_naturalness", True):
        pos_scores["dialogue_naturalness"] = _score_dialogue_naturalness(text)
    if positive.get("sensory_detail_density", True):
        pos_scores["sensory_detail_density"] = _score_sensory_detail(text)
    if positive.get("emotional_restraint", True):
        pos_scores["emotional_restraint"] = _score_emotional_restraint(text)
    if positive.get("sentence_variety", True):
        pos_scores["sentence_variety"] = _score_sentence_variety(text)
    if positive.get("life_scene_ratio", True):
        pos_scores["life_scene_ratio"] = _score_life_scenes(text)

    result["positive_scores"] = pos_scores

    # ── 综合评分 ──
    negative_penalty = 0
    for hit_type, hit_data in result["negative_hits"].items():
        if hit_type == "banned_transitions":
            negative_penalty += min(sum(hit_data.values()) * 3, 30)
        elif hit_type == "banned_descriptions":
            negative_penalty += min(sum(hit_data.values()) * 5, 25)
        elif hit_type == "perfect_protagonist":
            negative_penalty += 15
        elif hit_type == "preaching_dialogue":
            negative_penalty += min(hit_data.get("density_per_1k", 0) * 20, 20)
        elif hit_type == "mental_prefix":
            # 每千字 >5 处 = 严重, >10 = 阻断
            negative_penalty += min(hit_data.get("density_per_1k", 0) * 3, 20)
        elif hit_type == "conjunction_spoiler":
            # 每处连词剧透 -3 分，上限 25
            negative_penalty += min(hit_data.get("count", 0) * 3, 25)
        elif hit_type == "conjunction_density":
            # 显性连接词密度过高: 每超1/千字 -2 分，上限 15
            over = max(hit_data.get("density_per_1k", 0) - 5.0, 0)
            negative_penalty += min(over * 2, 15)
        elif hit_type == "emotion_redundancy":
            # 每处情绪冗余 -4 分，上限 20
            negative_penalty += min(hit_data.get("count", 0) * 4, 20)
        elif hit_type == "direct_dialogue":
            # 每处念台词式对话 -3 分，上限 20
            negative_penalty += min(hit_data.get("count", 0) * 3, 20)

    # v3: 对白占比极端扣分
    if "dialogue_ratio" in result.get("negative_hits", {}):
        negative_penalty += 10

    positive_sum = sum(pos_scores.values()) if pos_scores else 0
    positive_avg = positive_sum / max(len(pos_scores), 1)
    positive_bonus = positive_avg * 50

    score = 50 + positive_bonus - negative_penalty
    result["human_flavor_score"] = max(0, min(100, round(score)))

    pass_threshold = llm_cfg.get("pass_threshold", 60)
    result["pass"] = result["human_flavor_score"] >= pass_threshold

    if result["human_flavor_score"] >= 80:
        result["grade"] = "A"
        result["grade_label"] = "高度人味"
    elif result["human_flavor_score"] >= 60:
        result["grade"] = "B"
        result["grade_label"] = "基本人味"
    elif result["human_flavor_score"] >= 40:
        result["grade"] = "C"
        result["grade_label"] = "AI味明显"
    else:
        result["grade"] = "D"
        result["grade_label"] = "高度AI味"

    return result


def format_report(result):
    """Format detection result as human-readable text."""
    lines = [
        "=" * 50,
        "  AI写作味检测报告",
        "=" * 50,
        "",
        f"  人味度评分: {result['human_flavor_score']}/100 ({result['grade_label']})",
        f"  是否通过: {'[OK] 通过' if result['pass'] else '[FAIL] 未通过'}",
        "",
    ]

    if result["details"]:
        lines.append("  [发现的问题]")
        for d in result["details"]:
            lines.append(f"    - {d}")
        lines.append("")

    if result["positive_scores"]:
        lines.append("  [正面维度评分]")
        labels = {
            "dialogue_naturalness": "对话口语化",
            "sensory_detail_density": "感官细节密度",
            "emotional_restraint": "情绪克制度",
            "sentence_variety": "句式多样性",
            "life_scene_ratio": "生活化闲笔",
        }
        for key, score in result["positive_scores"].items():
            label = labels.get(key, key)
            bar = "#" * int(score * 20) + "-" * (20 - int(score * 20))
            lines.append(f"    {label:　<8s}: [{bar}] {score:.2f}")
        lines.append("")

    lines.append("=" * 50)
    return "\n".join(lines)


def main():
    config = _load_config()
    if not config.get("enabled", True):
        print("[SKIP] ai_flavor_detection 未启用")
        return

    json_mode = "--json" in sys.argv
    use_llm = "--llm" in sys.argv
    text = None

    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--text" and i < len(sys.argv) - 1:
            text_path = sys.argv[i + 1]
            if Path(text_path).exists():
                text = Path(text_path).read_text(encoding="utf-8")
        elif arg == "--stdin":
            text = sys.stdin.read()

    if not text:
        print("用法: python analysis/ai_flavor_detector.py --text <file> [--json] [--llm]")
        print("      python analysis/ai_flavor_detector.py --stdin [--json]")
        return

    result = detect_ai_flavor(text, config)

    if use_llm:
        result["llm_note"] = "LLM分类器待接入 (需 model_orchestrator 支持)"

    if json_mode:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_report(result))


if __name__ == "__main__":
    main()