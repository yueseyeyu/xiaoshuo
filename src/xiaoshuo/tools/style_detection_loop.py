#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
style_detection_loop.py — S4 反检测循环: 检测→报告→(人工修改)→复检→对比
========================================================================
v7.6: 新增 L5 人物一致性 + L6 AI口头禅, 对标平台整治重点
原则: 本模块只检测, 不生成任何改写建议或替换文本。AI生成正文须通过S3质量门禁。

六层检测 (来自 config.yaml detection.layers):
  L1 PPL (困惑度)         — PPL < 阈值 → 疑似 AI 生成
  L2 Burstiness (突发性)   — 句长变异系数低 → 文本过于规整
  L3 AI词共现             — 常见 AI 词汇密度过高
  L4 句长分布变异          — 连读多章后句长模式变平 → 风格漂移
  L5 人物一致性            — 角色名串错/低频异常/相似名变体
  L6 AI口头禅              — 高频套话密度 (不得/不禁/心中一凛等)

循环模式:
  检测第N章 → 输出指标 → 人修改 → 检测第N章(rev2) → 对比 → ...

用法:
  python analysis/style_detection_loop.py --text "章节内容"
  python analysis/style_detection_loop.py --file path/to/chapter.txt
  python analysis/style_detection_loop.py --book 异兽迷城 --ch 5
"""

import math
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from xiaoshuo.infra.config_manager import get_config

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"

# v7.5: AI 指纹词表 (静态, 来自 config 中的 l3_ai_word_cooccurrence)
_AI_FINGERPRINT = {
    "此外", "总而言之", "综上所述", "值得注意的是", "不可否认",
    "与此同时", "另一方面", "显而易见", "由此可见", "事实上",
    "从根本上说", "本质上", "某种意义上", "在某种程度上",
    "不但", "而且", "然而", "因此", "从而", "进而",
    "首先", "其次", "最后", "一方面", "值得注意的是",
}


def _load_cfg():
    """Load detection thresholds from config.yaml."""
    defaults = {
        "l1_ppl": {"safe": 50, "warn": 40},
        "l2_burstiness": {"safe": 0.6},
        "l3_ai_word": {"window": 100, "max_words": 2},
        "l4_variation": {"warning": 0.20},
        "l5_character": {"max_rare_names": 3, "max_similar_pairs": 2},
        "l6_ai_tic": {"max_density": 1.0, "max_unique": 8},
    }
    try:
        cfg = get_config()
        det = cfg.get("detection", {}).get("layers", {})
        return {
            "l1": det.get("l1_ppl", defaults["l1_ppl"]),
            "l2": det.get("l2_burstiness", defaults["l2_burstiness"]),
            "l3": det.get("l3_ai_word_cooccurrence", defaults["l3_ai_word"]),
            "l4": det.get("l4_sentence_length_variation", defaults["l4_variation"]),
            "l5": det.get("l5_character_consistency", defaults["l5_character"]),
            "l6": det.get("l6_ai_tic_phrases", defaults["l6_ai_tic"]),
            "l7": det.get("l7_human_likeness", {}),
        }
    except Exception:
        return defaults


def _sentences(text):
    """Split text into sentences (Chinese-aware)."""
    return re.split(r'[。！？；\n]+', text)


def _words(text):
    """Tokenize Chinese text into words (2-char sliding + single char)."""
    chinese = re.findall(r'[\u4e00-\u9fff]+', text)
    tokens = []
    for segment in chinese:
        for i in range(len(segment)):
            if i + 1 < len(segment):
                tokens.append(segment[i:i + 2])
        tokens.append(segment[-1])
    return tokens


# ── L1: 困惑度估算 ──

def _ppl_estimate(text):
    """Heuristic PPL proxy: entropy-based. Lower = more predictable = AI-like.
    Real PPL needs LLM scoring; this is a fast proxy for loop mode."""
    sents = _sections(text)
    if len(sents) < 3:
        return 100.0
    # Sentence length entropy
    lens = [len(s) for s in sents if len(s) > 5]
    if not lens:
        return 100.0
    mean_len = sum(lens) / len(lens)
    if mean_len < 1:
        return 100.0
    entropy = 0.0
    for l in lens:
        p = l / sum(lens) if sum(lens) > 0 else 1 / len(lens)
        if p > 0:
            entropy -= p * math.log2(p)
    # Normalize: high entropy → high PPL proxy; low entropy → low PPL → AI-like
    normalized = max(10, 100 - entropy * 15)
    return round(normalized, 1)


def _sections(text):
    """Split text into content sections (paragraph-level)."""
    return [p.strip() for p in re.split(r'\n{2,}', text) if p.strip() and len(p.strip()) > 10]


# ── L2: 突发性 ──

def _burstiness(text):
    """Burstiness = stdev(sentence_lengths) / mean(sentence_lengths).
    Higher = more human-like variation. < 0.6 = warning."""
    sents = _sentences(text)
    lens = [len(s) for s in sents if len(s) > 3]
    if len(lens) < 5:
        return 1.0
    mean_len = sum(lens) / len(lens)
    if mean_len < 2:
        return 1.0
    variance = sum((l - mean_len) ** 2 for l in lens) / len(lens)
    return round(math.sqrt(variance) / mean_len, 3)


# ── L3: AI 词共现 ──

def _ai_word_density(text):
    """Count AI fingerprint words per 100-character sliding window."""
    if not text:
        return 0.0
    chinese_only = ''.join(re.findall(r'[\u4e00-\u9fff]', text))
    if len(chinese_only) < 100:
        return 0.0

    max_density = 0.0
    for i in range(0, len(chinese_only) - 100, 50):
        window = chinese_only[i:i + 100]
        hits = sum(1 for w in _AI_FINGERPRINT if w in window)
        density = hits / 100
        if density > max_density:
            max_density = density
    return round(max_density, 4)


# ── L4: 句长变异 ──

def _sentence_variation(text_a, text_b=None):
    """Compute sentence length variation coefficient.
    If text_b provided: compare two versions (delta > threshold → warning)."""
    sents_a = [len(s) for s in _sentences(text_a) if len(s) > 3]
    if not sents_a or len(sents_a) < 5:
        return 0.0
    cv_a = math.sqrt(sum((l - sum(sents_a) / len(sents_a)) ** 2
                         for l in sents_a) / len(sents_a)) / (sum(sents_a) / len(sents_a))

    if text_b is None:
        return round(cv_a, 3)

    sents_b = [len(s) for s in _sentences(text_b) if len(s) > 3]
    if not sents_b or len(sents_b) < 5:
        return 0.0
    cv_b = math.sqrt(sum((l - sum(sents_b) / len(sents_b)) ** 2
                         for l in sents_b) / len(sents_b)) / (sum(sents_b) / len(sents_b))

    return round(abs(cv_a - cv_b), 3)


# ── L5: 人物一致性检测 ──

# 中文常见姓氏 (百家姓前100)
_CN_SURNAMES = set("赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张"
                   "孔曹严华金魏陶姜戚谢邹喻柏水窦章云苏潘葛奚范彭郎"
                   "鲁韦昌马苗凤花方俞任袁柳酆鲍史唐费廉岑薛雷贺倪汤"
                   "滕殷罗毕郝邬安常乐于时傅皮下齐康伍余元卜顾孟平黄"
                   "和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞"
                   "熊纪舒屈项祝董梁杜阮蓝闵席季麻强贾路娄危江童颜郭"
                   "梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍虞万支柯昝管卢莫"
                   "经房裘缪干解应宗丁宣贲邓郁单杭洪包诸左石崔吉钮龚"
                   "程嵇邢滑裴陆荣翁荀羊於惠甄曲家封芮羿储靳汲邴糜松"
                   "井段富巫乌焦巴弓牧隗山谷车侯宓蓬全郗班仰秋仲伊宫"
                   "宁仇栾暴甘钭厉戎祖武符刘景詹束龙叶幸司韶郜黎蓟薄"
                   "印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔阳郁胥能苍双"
                   "闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍却璩桑桂濮牛寿通"
                   "边扈燕冀郏浦尚农温别庄晏柴瞿阎充慕连茹习宦艾鱼容"
                   "向古易慎戈廖庾终暨居衡步都耿满弘匡国文寇广禄阙东"
                   "欧殳沃利蔚越夔隆师巩厍聂晁勾敖融冷訾辛阚那简饶空"
                   "曾毋沙乜养鞠须丰巢关蒯相查后荆红游竺权逯盖益桓公"
                   "万俟司马上官欧阳夏侯诸葛闻人东方赫连皇甫尉迟公羊"
                   "澹台公冶宗政濮阳淳于单于太叔申屠公孙仲孙轩辕令狐"
                   "钟离宇文长孙慕容鲜于闾丘司徒司空丌官司寇仉督子车"
                   "颛孙端木巫马公西漆雕乐正壤驷公良拓跋夹谷宰父谷梁"
                   "晋楚闫法汝鄢涂钦段干百里东郭南门呼延归海羊舌微生"
                   "岳帅缑亢况后有琴梁丘左丘东门西门商牟佘佴伯赏南宫"
                   "墨哈谯笪年爱阳佟第五言福")

# AI 生成文本常见的人物名串错模式
_CHAR_NAME_PATTERN = re.compile(
    r'[\u4e00-\u9fff]{2,3}'  # 2-3 字中文名
)

def _character_consistency(text):
    """L5: 人物一致性检测 — 检测人物名串错、性格突变、动机矛盾。

    静态分析: 抽取人物名 → 检测低频率异常 → 检测相似名变体。
    注意: 这是启发式代理检测, 精确检测需要角色设定文件。

    Returns:
        dict with:
        - names: detected character names
        - rare_names: names appearing only once (potential typos)
        - similar_pairs: [(name_a, name_b, similarity)] pairs
        - score: 0-100 consistency score (100 = perfect)
    """
    if not text:
        return {"names": [], "rare_names": [], "similar_pairs": [], "score": 100}

    # Extract potential Chinese names (2-3 chars, first char is surname)
    raw_names = _CHAR_NAME_PATTERN.findall(text)
    potential_names = []
    for name in raw_names:
        if name[0] in _CN_SURNAMES and len(name) >= 2:
            # Filter out common non-name bigrams
            skip = False
            for w in ["他们", "我们", "你们", "什么", "怎么", "没有", "可以",
                       "这个", "那个", "自己", "因为", "所以", "如果", "虽然",
                       "但是", "已经", "还是", "或者", "而且", "不过", "只是"]:
                if w in name:
                    skip = True
                    break
            if not skip:
                potential_names.append(name)

    if not potential_names:
        return {"names": [], "rare_names": [], "similar_pairs": [], "score": 100}

    name_counts = Counter(potential_names)
    total_names = len(potential_names)

    # Rare names: appearing only once in a long text → possible typo
    rare_names = []
    if total_names > 20:
        for name, count in name_counts.items():
            if count == 1 and len(name) == 3:
                # Check if there's a similar name with higher frequency
                has_similar = False
                for other, other_count in name_counts.items():
                    if other != name and other_count >= 3:
                        # Same first char (surname) and similar structure
                        if other[0] == name[0] and len(other) == len(name):
                            has_similar = True
                            break
                if has_similar:
                    rare_names.append(name)

    # Similar name pairs (possible typos)
    similar_pairs = []
    sorted_names = sorted(name_counts.keys())
    for i, a in enumerate(sorted_names):
        for b in sorted_names[i + 1:]:
            if a[0] == b[0] and len(a) == len(b) and a != b:
                # Same surname, same length, different given name
                common = sum(1 for ca, cb in zip(a, b) if ca == cb)
                if common >= 2:  # at least surname + 1 char same
                    similar_pairs.append((a, b, name_counts[a], name_counts[b]))

    # Score: deduct for rare names and similar pairs
    score = 100
    score -= len(rare_names) * 5
    score -= len(similar_pairs) * 3
    score = max(0, min(100, score))

    return {
        "names": sorted(name_counts.keys(), key=lambda n: -name_counts[n])[:20],
        "rare_names": rare_names,
        "similar_pairs": [(a, b) for a, b, _, _ in similar_pairs],
        "score": score,
    }


# ── L6: AI 口头禅检测 ──

# AI 生成文本高频套话/口头禅 (平台检测重点)
_AI_TIC_PHRASES = [
    "不由得", "不禁", "下意识", "心中一凛", "眼中闪过",
    "嘴角微微上扬", "深吸一口气", "瞳孔微缩", "心头一颤",
    "浑身一震", "倒吸一口凉气", "目光一凝", "脸色一变",
    "心中一动", "不自觉地", "脑海中闪过", "心底涌起",
    "眼神一暗", "眸色一沉", "心中一紧", "心头一紧",
    "微微一愣", "愣了愣", "怔了怔", "顿了顿",
    "冷哼一声", "微微皱眉", "眉头一皱", "眉头微蹙",
    "若有所思", "沉吟片刻", "沉默片刻", "沉默了一下",
    "缓缓开口", "淡淡道", "冷冷道", "低声说道",
    "语气中带着", "眼中闪过一丝", "嘴角勾起一抹",
    "露出一抹", "浮现一抹", "带着几分",
    "不可否认", "显而易见", "值得注意的是",
    "在某种程度上", "某种意义上", "总的来说",
    "不仅如此", "与此同时", "换句话说",
    "究其原因", "归根结底", "从某种程度上说",
]

# ── L7: 人味度检测 (v7.7 新增) ──

# 第一人称心理活动标记词
_PSYCH_MARKERS = [
    "我觉得", "我感到", "我感觉", "我心里", "我心中", "我内心",
    "我意识到", "我突然想到", "我忽然明白", "我明白", "我懂了",
    "我不确定", "我犹豫", "我纠结", "我挣扎", "我害怕",
    "我担心", "我期待", "我渴望", "我恨", "我厌",
    "莫名其妙地", "不知道为什么", "鬼使神差", "忍不住",
    "下意识地", "不自觉地", "恍惚间", "一瞬间",
    "脑海中闪过", "心底涌起", "心头一紧", "心一横",
    "深吸一口气", "咬了咬牙", "握紧拳头", "眼眶发热",
]

# 第一人称视角标记 (用于判断是否为第一人称)
_FIRST_PERSON_COUNT = re.compile(r'(?:^|[。！？…；\n\s])我')

# 第三人称叙述标记 (用于判断是否为第三人称)
_THIRD_PERSON_COUNT = re.compile(r'(?:^|[。！？…；\n\s])(?:他|她)')

# 心理矛盾/犹豫标记
_CONTRADICTION_MARKERS = [
    "但是", "可是", "然而", "不过", "虽然", "尽管",
    "犹豫", "纠结", "挣扎", "矛盾", "两难",
    "一方面", "另一方面", "既想", "又怕",
    "理智告诉我", "但心里", "明明知道", "却还是",
    "说不上来", "说不清", "无法形容", "复杂",
]

# 上帝视角泄露标记 (AI 常见问题: 主角知道不该知道的事)
# 注: 不用 \b, 因为中文全是 \w 字符, \b 不生效
_OMNISCIENT_LEAK = re.compile(
    r'(?:殊不知|他不知道的是|她不知道的是|而此刻|不远处|隔壁|'
    r'千里之外|另一边|暗处|暗中|背地里|私下里|'
    r'此刻.{0,5}正|此时.{0,5}正|这时候.{0,5}正|就在这时)|'
    r'(?:他|她)(?:暗自|偷偷|悄悄|默默|暗暗)'
)


def _human_likeness(text):
    """L7: 人味度检测 — 评估文本的"人写感"。

    基于建议文件中的"第一人称+定期心理总结去AI味"技巧,
    从四个维度评估文本的人味度:
      1. 视角一致性: 是否第一人称? 视角是否统一?
      2. 心理活动密度: 每千字心理标记词数量
      3. 矛盾/犹豫: 是否有情感矛盾和非理性?
      4. 信息差: 是否有"上帝视角"泄露?

    高分 = 更像人写, 低分 = 更像 AI 生成。

    Returns:
        dict with:
        - pov_type: "first_person" / "third_person" / "mixed"
        - pov_consistency: 0-100 POV 一致性
        - psych_density: 心理标记词密度 (/千字)
        - contradiction_count: 矛盾/犹豫标记数
        - omniscient_leaks: 上帝视角泄露次数
        - score: 0-100 人味度总分 (100 = 最像人写)
    """
    if not text:
        return {
            "pov_type": "unknown", "pov_consistency": 0,
            "psych_density": 0.0, "contradiction_count": 0,
            "omniscient_leaks": 0, "score": 50,
        }

    char_count = len(text.replace("\n", "").replace(" ", ""))
    if char_count < 50:
        return {
            "pov_type": "unknown", "pov_consistency": 0,
            "psych_density": 0.0, "contradiction_count": 0,
            "omniscient_leaks": 0, "score": 50,
        }

    # 1. POV 检测
    first_person_count = len(_FIRST_PERSON_COUNT.findall(text))
    third_person_count = len(_THIRD_PERSON_COUNT.findall(text))

    total_markers = first_person_count + third_person_count
    if total_markers == 0:
        pov_type = "unknown"
        pov_consistency = 0
    elif first_person_count > third_person_count * 2:
        pov_type = "first_person"
        pov_consistency = min(100, int(first_person_count / max(1, total_markers) * 100))
    elif third_person_count > first_person_count * 2:
        pov_type = "third_person"
        pov_consistency = min(100, int(third_person_count / max(1, total_markers) * 100))
    else:
        pov_type = "mixed"
        pov_consistency = int(abs(first_person_count - third_person_count) / max(1, total_markers) * 100)

    # 2. 心理活动密度
    psych_hits = 0
    psych_found = []
    for marker in _PSYCH_MARKERS:
        count = text.count(marker)
        if count > 0:
            psych_hits += count
            psych_found.append(marker)

    psych_density = round(psych_hits / (char_count / 1000), 2)

    # 3. 矛盾/犹豫标记
    contradiction_count = 0
    for marker in _CONTRADICTION_MARKERS:
        contradiction_count += text.count(marker)

    # 4. 上帝视角泄露
    omniscient_leaks = len(_OMNISCIENT_LEAK.findall(text))

    # ── 综合评分 ──
    score = 50  # 默认中性

    # POV: 第一人称 +25, 第三人称 +5, mixed +0
    if pov_type == "first_person":
        score += 25
    elif pov_type == "third_person":
        score += 5
    # POV consistency: 越一致越好
    if pov_consistency >= 80:
        score += 5
    elif pov_consistency >= 60:
        score += 3

    # 心理密度: 1.0-3.0/千字 = 最佳区间 (人写水平)
    if 1.0 <= psych_density <= 3.0:
        score += 25
    elif 0.5 <= psych_density < 1.0:
        score += 15
    elif psych_density > 3.0:
        score += 5  # 过多内心戏, 颓势

    # 矛盾/犹豫: 有矛盾 = 有人味
    if contradiction_count >= 3:
        score += 15
    elif contradiction_count >= 1:
        score += 8

    # 上帝视角泄露: 扣分 (0 泄露 +5, 1-2 不加分, >2 扣分)
    if omniscient_leaks == 0:
        score += 5
    elif omniscient_leaks > 2:
        score -= (omniscient_leaks - 2) * 3

    score = max(0, min(100, score))

    return {
        "pov_type": pov_type,
        "pov_consistency": pov_consistency,
        "psych_density": psych_density,
        "psych_markers_found": psych_found[:10],
        "contradiction_count": contradiction_count,
        "omniscient_leaks": omniscient_leaks,
        "score": score,
    }


def _ai_tic_density(text):
    """L6: AI 口头禅检测 — 检测 AI 高频套话密度。

    平台整治重点: "套话废话"识别。这些短语在 AI 生成文本中
    密度远高于人写文本 (人写通常 < 0.3/千字, AI 生成通常 > 1.5/千字)。

    Returns:
        dict with:
        - hits: list of (phrase, position) found
        - density: hits per 1000 chars
        - unique_count: number of unique tic phrases found
        - score: 0-100 (100 = clean, low = AI-like)
    """
    if not text:
        return {"hits": [], "density": 0.0, "unique_count": 0, "score": 100}

    hits = []
    char_count = len(text.replace("\n", "").replace(" ", ""))
    if char_count < 100:
        return {"hits": [], "density": 0.0, "unique_count": 0, "score": 100}

    found_phrases = set()
    for phrase in _AI_TIC_PHRASES:
        pos = 0
        while True:
            idx = text.find(phrase, pos)
            if idx == -1:
                break
            hits.append((phrase, idx))
            found_phrases.add(phrase)
            pos = idx + 1

    density = len(hits) / (char_count / 1000)  # hits per 1000 chars
    density = round(density, 2)
    unique_count = len(found_phrases)

    # Score: < 0.5/千字 = 100, 0.5-1.0 = 80, 1.0-2.0 = 50, > 2.0 = 20
    if density <= 0.3:
        score = 100
    elif density <= 0.5:
        score = 90
    elif density <= 1.0:
        score = 70
    elif density <= 2.0:
        score = 40
    else:
        score = 15

    return {
        "hits": hits[:20],  # top 20 for display
        "density": density,
        "unique_count": unique_count,
        "score": score,
    }


# ── 主检测管道 ──

def detect_style(text, previous_text=None):
    """Run 6-layer style detection on text.
    
    Args:
        text: current chapter text
        previous_text: optional previous version for L4 comparison
        
    Returns:
        dict with per-layer results and overall verdict
    """
    cfg = _load_cfg()
    results = {}

    # L1: PPL proxy
    ppl = _ppl_estimate(text)
    l1_cfg = cfg.get("l1", {})
    results["l1_ppl"] = {
        "value": ppl,
        "safe_threshold": l1_cfg.get("safe", 50),
        "warn_threshold": l1_cfg.get("warn", 40),
        "status": "pass" if ppl > l1_cfg.get("safe", 50)
                  else ("warn" if ppl > l1_cfg.get("warn", 40)
                        else "fail"),
    }

    # L2: Burstiness
    burst = _burstiness(text)
    l2_cfg = cfg.get("l2", {})
    results["l2_burstiness"] = {
        "value": burst,
        "safe_threshold": l2_cfg.get("safe", 0.6),
        "status": "pass" if burst > l2_cfg.get("safe", 0.6) else "fail",
    }

    # L3: AI word co-occurrence
    density = _ai_word_density(text)
    l3_cfg = cfg.get("l3", {})
    max_words = l3_cfg.get("max_words", 2)
    results["l3_ai_words"] = {
        "value": density,
        "max_per_100": max_words,
        "status": "pass" if density * 100 <= max_words else "fail",
    }

    # L4: Sentence variation
    if previous_text:
        delta = _sentence_variation(text, previous_text)
        l4_cfg = cfg.get("l4", {})
        results["l4_variation"] = {
            "delta": delta,
            "warning_threshold": l4_cfg.get("warning", 0.20),
            "status": "pass" if delta < l4_cfg.get("warning", 0.20) else "fail",
        }
    else:
        cv = _sentence_variation(text)
        results["l4_variation"] = {
            "cv": cv,
            "status": "info",
            "note": "无前版对照, 仅报告变异系数",
        }

    # L5: Character consistency (v7.6)
    char_result = _character_consistency(text)
    l5_cfg = cfg.get("l5", {})
    max_rare = l5_cfg.get("max_rare_names", 3)
    max_similar = l5_cfg.get("max_similar_pairs", 2)
    l5_status = "pass"
    if len(char_result["rare_names"]) > max_rare:
        l5_status = "fail"
    elif len(char_result["similar_pairs"]) > max_similar:
        l5_status = "warn"
    results["l5_character"] = {
        "names": char_result["names"][:10],
        "rare_names": char_result["rare_names"],
        "similar_pairs": char_result["similar_pairs"],
        "score": char_result["score"],
        "status": l5_status,
    }

    # L6: AI tic phrases (v7.6)
    tic_result = _ai_tic_density(text)
    l6_cfg = cfg.get("l6", {})
    max_density = l6_cfg.get("max_density", 1.0)
    max_unique = l6_cfg.get("max_unique", 8)
    l6_status = "pass"
    if tic_result["density"] > max_density:
        l6_status = "fail"
    elif tic_result["unique_count"] > max_unique:
        l6_status = "warn"
    results["l6_ai_tic"] = {
        "density": tic_result["density"],
        "unique_count": tic_result["unique_count"],
        "score": tic_result["score"],
        "total_hits": len(tic_result["hits"]),
        "sample_hits": [h[0] for h in tic_result["hits"][:10]],
        "status": l6_status,
    }

    # L7: Human-likeness / 人味度 (v7.7)
    human_result = _human_likeness(text)
    l7_cfg = cfg.get("l7", {})
    min_score = l7_cfg.get("min_score", 40)
    l7_status = "pass"
    if human_result["score"] >= 70:
        l7_status = "pass"
    elif human_result["score"] >= min_score:
        l7_status = "warn"
    else:
        l7_status = "fail"
    results["l7_human_likeness"] = {
        "pov_type": human_result["pov_type"],
        "pov_consistency": human_result["pov_consistency"],
        "psych_density": human_result["psych_density"],
        "psych_markers": human_result["psych_markers_found"],
        "contradiction_count": human_result["contradiction_count"],
        "omniscient_leaks": human_result["omniscient_leaks"],
        "score": human_result["score"],
        "status": l7_status,
    }

    # Overall verdict
    failures = sum(1 for r in results.values() if r["status"] == "fail")
    warns = sum(1 for r in results.values() if r["status"] == "warn")
    if failures > 0:
        verdict = f"[FAIL] {failures} 层超标"
    elif warns > 0:
        verdict = f"[WARN] {warns} 层预警"
    else:
        verdict = "[PASS] 全层通过"

    results["_verdict"] = verdict
    results["_timestamp"] = datetime.now().isoformat()
    return results


# ── 梯度拟合审核 (v7.5 新增) ──

class GradientValidator:
    """梯度拟合审核器：在 S4 六层检测之上叠加置信区间。

    核心理念 (来自 @吴港风微暖):
    - 不是单次"通过/不通过"，而是逐层收紧置信区间
    - 每层输出：当前置信度 + 累积错误概率 + 危害程度
    - 初始步骤宽松（不漏过），后续步骤严格（只留高置信）

    多层模型交叉验证：
    - 本地 Qwen3.5-9B (L1-L6 基础检测)
    - 云端 DeepSeek API (可选，L5-L6 增强)
    - 人审 (最终裁决)
    """

    def __init__(self):
        self.layers = [
            {"name": "l1_ppl",           "label": "困惑度",     "threshold": 0.90, "error_prob": 0.25, "harm": "低"},
            {"name": "l2_burstiness",    "label": "突发性",     "threshold": 0.80, "error_prob": 0.20, "harm": "中"},
            {"name": "l3_ai_words",      "label": "AI词共现",   "threshold": 0.70, "error_prob": 0.18, "harm": "高"},
            {"name": "l4_variation",     "label": "句长变异",   "threshold": 0.60, "error_prob": 0.15, "harm": "高"},
            {"name": "l5_character",     "label": "人物一致性", "threshold": 0.55, "error_prob": 0.12, "harm": "致命"},
            { "name": "l6_ai_tic",        "label": "AI口头禅",   "threshold": 0.50, "error_prob": 0.10, "harm": "致命"},
            {"name": "l7_human_likeness", "label": "人味度",     "threshold": 0.45, "error_prob": 0.12, "harm": "高"},
        ]

    def validate(self, style_results):
        """对 detect_style() 的输出进行梯度拟合审核。

        Args:
            style_results: detect_style() 返回的 dict

        Returns:
            dict with gradient_fit: per-layer confidence + cumulative
        """
        cumulative_confidence = 1.0
        gradient_layers = []
        issues = []

        for layer in self.layers:
            name = layer["name"]
            data = style_results.get(name, {})
            status = data.get("status", "info")

            # 计算该层置信度
            if status == "pass":
                layer_confidence = 1.0
            elif status == "warn":
                layer_confidence = 0.6
            elif status == "fail":
                layer_confidence = 0.2
            else:
                layer_confidence = 0.5  # info / unknown

            # 是否通过阈值
            passed = layer_confidence >= layer["threshold"]

            # 累积置信度
            if passed:
                cumulative_confidence *= (1 - layer["error_prob"])
            else:
                cumulative_confidence *= layer["error_prob"]
                issues.append({
                    "layer": layer["label"],
                    "status": status,
                    "confidence": layer_confidence,
                    "harm": layer["harm"],
                })

            gradient_layers.append({
                "layer": layer["label"],
                "status": status,
                "confidence": round(layer_confidence, 2),
                "threshold": layer["threshold"],
                "passed": passed,
                "error_prob": layer["error_prob"],
                "harm": layer["harm"],
                "cumulative": round(cumulative_confidence, 4),
            })

        # 最终判定
        if cumulative_confidence >= 0.50:
            verdict = "SAFE"
            verdict_label = "安全 — 累积置信度充足"
        elif cumulative_confidence >= 0.25:
            verdict = "WARNING"
            verdict_label = "预警 — 建议人工复核"
        else:
            verdict = "FATAL"
            verdict_label = "高危 — 强烈建议修改后重检"

        return {
            "gradient_fit": gradient_layers,
            "cumulative_confidence": round(cumulative_confidence, 4),
            "verdict": verdict,
            "verdict_label": verdict_label,
            "issues": issues,
            "issue_count": len(issues),
            "_timestamp": datetime.now().isoformat(),
        }


def gradient_validate(text, previous_text=None):
    """一站式梯度拟合审核：先跑 S4 六层检测，再叠置信度评估。

    这是 GradientValidator 的便捷封装。

    Args:
        text: 当前章节文本
        previous_text: 前版文本（用于 L4 对比）

    Returns:
        dict with:
        - style_results: 原始六层检测结果
        - gradient: 梯度拟合审核结果
    """
    style_results = detect_style(text, previous_text)
    validator = GradientValidator()
    gradient = validator.validate(style_results)
    return {
        "style_results": style_results,
        "gradient": gradient,
    }


def format_gradient_report(gradient_result):
    """格式化梯度拟合审核报告为可读文本。"""
    gf = gradient_result["gradient"]
    lines = [
        "# S4++ 梯度拟合审核报告",
        f"时间: {gf['_timestamp']}",
        f"累积置信度: {gf['cumulative_confidence']:.2%}",
        f"判定: {gf['verdict']} — {gf['verdict_label']}",
        "",
        "## 逐层置信度",
        "| 层级 | 状态 | 置信度 | 阈值 | 通过 | 错误率 | 危害 | 累积 |",
        "|------|------|--------|------|------|--------|------|------|",
    ]
    for layer in gf["gradient_fit"]:
        icon = "[OK]" if layer["passed"] else "[WARN]"
        lines.append(
            f"| {icon} {layer['layer']} "
            f"| {layer['status']} "
            f"| {layer['confidence']:.0%} "
            f"| {layer['threshold']:.0%} "
            f"| {'是' if layer['passed'] else '否'} "
            f"| {layer['error_prob']:.0%} "
            f"| {layer['harm']} "
            f"| {layer['cumulative']:.2%} |"
        )
    lines.append("")

    if gf["issues"]:
        lines.append("## 需关注的问题")
        for i, issue in enumerate(gf["issues"], 1):
            lines.append(f"{i}. [{issue['status']}] {issue['layer']} "
                         f"(置信度: {issue['confidence']:.0%}, 危害: {issue['harm']})")
    else:
        lines.append("## 无问题 — 全层通过")
    lines.append("")

    return lines

def detection_loop(text, max_iterations=5, previous_text=None):
    """Run detection loop: detect → (manual edit externally) → re-detect → compare.
    
    This is the outer loop controller. Each iteration runs detect_style().
    Between iterations: the user edits the text externally, then calls again.
    
    Args:
        text: current chapter text
        max_iterations: max detection rounds (prevents infinite loop)
        previous_text: original text for comparison (L4 baseline)
        
    Returns:
        list of per-round detection results
    """
    rounds = []
    current = text
    baseline = previous_text or text

    for r in range(max_iterations):
        result = detect_style(current, baseline)
        rounds.append(result)

        verdict = result["_verdict"]
        failures = [k for k, v in result.items()
                    if isinstance(v, dict) and v.get("status") == "fail"]
        if not failures:
            print(f"  Round {r + 1}: [PASS] All layers pass")
            break
        else:
            print(f"  Round {r + 1}: [FAIL] {failures}")

        # After each round, user edits. In automated mode we break.
        if r < max_iterations - 1:
            print(f"  → 请人工修改后重新检测, 或按 Ctrl+C 退出")
        break  # Single iteration per call; user re-runs for next round

    return rounds


def format_report(results):
    """Format detection results as readable report."""
    lines = ["# S4 风格检测报告",
             f"时间: {results.get('_timestamp', '')}",
             f"判定: {results.get('_verdict', 'N/A')}",
             "", "## 逐层结果", ""]
    for layer, data in results.items():
        if layer.startswith("_"):
            continue
        status = data.get("status", "?")
        icon = {"pass": "[OK]", "warn": "[WARN]", "fail": "[FAIL]", "info": "[INFO]"}.get(status, "[?]")
        lines.append(f"### {icon} {layer}")
        for k, v in data.items():
            if k != "status":
                lines.append(f"  - {k}: {v}")
        lines.append("")
    return lines


# ── CLI ──

def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        return

    text = None
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--text" and i < len(sys.argv) - 1:
            text = sys.argv[i + 1]
        elif arg == "--file" and i < len(sys.argv) - 1:
            path = Path(sys.argv[i + 1])
            if path.exists():
                text = path.read_text(encoding="utf-8", errors="replace")
            else:
                print(f"[FAIL] File not found: {path}")
                return

    if not text:
        print("[USAGE] python analysis/style_detection_loop.py --text '章节内容'")
        print("[USAGE] python analysis/style_detection_loop.py --file chapter.txt")
        return

    result = detect_style(text)
    for line in format_report(result):
        print(line)
    print(f"\n裁判: {result['_verdict']}")


if __name__ == "__main__":
    main()
