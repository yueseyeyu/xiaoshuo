# -*- coding: utf-8 -*-
"""
style_dna.py — 叙事风格 DNA 提取器 (P1.3)
==========================================
来源: 建议文件 "女娲造人 -> 说话方式 -> 叙事风格 DNA (Part E 核心)"

从章节文本中提取五维量化风格指纹:
  D1 句法 (Syntax)    — 平均句长、对话占比、描写密度、句长方差
  D2 词汇 (Vocabulary) — 高频词、成语密度、网络用语比例、AI指纹词密度
  D3 节奏 (Rhythm)     — 段落长度分布、场景切换频率、短句占比
  D4 幽默 (Humor)      — 反讽/自嘲/黑色幽默标记密度
  D5 视角 (Perspective) — 第一/第三人称、内心独白密度、全知标记

设计原则:
  - 零 LLM 依赖: 全部统计/正则检测
  - 可比较: extract_dna() -> StyleDNA, compare_dna(target, current) -> StyleDeviation
  - 可积累: build_dna_baseline() 多章聚合
  - 与 style_evolution.py 互补:
      style_evolution 从"作者决策"提取风格偏好 (宏观)
      style_dna 从"文本本身"提取量化指纹 (微观)

用法:
  from xiaoshuo.pipeline.style_dna import extract_dna, compare_dna

  # 提取单章 DNA
  dna = extract_dna(chapter_text)

  # 建立基线 (多章聚合)
  baseline = build_dna_baseline([ch1, ch2, ..., ch10])

  # 比较当前章节与基线的偏离
  deviation = compare_dna(baseline, extract_dna(current_chapter))
  print(deviation.summary)
  print(deviation.consistency_score)  # 0-100

  # S3 评审集成
  s3_check = dna_as_s3_check(current_text, baseline_dna=baseline)
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from xiaoshuo.infra.logging_config import get_logger

logger = get_logger("style_dna")


# ====================================================================
# 工具函数
# ====================================================================

def _count_chinese(text: str) -> int:
    """统计中文字符数。"""
    return sum(1 for c in text if '\u4e00' <= c <= '\u9fff')


def _split_sentences(text: str) -> list[str]:
    """中文分句 (按。！？；…分割, 保留引号内内容)。"""
    # 去除空白行
    text = re.sub(r'\n+', '\n', text).strip()
    # 按句末标点分割
    parts = re.split(r'[。！？；…\n]+', text)
    # 过滤空句和过短碎片
    return [s.strip() for s in parts if s.strip() and len(s.strip()) >= 2]


def _split_paragraphs(text: str) -> list[str]:
    """按段落分割 (双换行或单换行)。"""
    paras = re.split(r'\n+', text.strip())
    return [p.strip() for p in paras if p.strip()]


# ====================================================================
# D1: 句法 (Syntax) 检测词表
# ====================================================================

# 对话标记
DIALOGUE_PATTERN = re.compile(r'[""「」『』].*?[""「」『』]')
# 引号对话简化匹配
DIALOGUE_QUOTE = re.compile(r'[""「」]')
# 描写标记 (环境/外貌/动作描写起始词)
DESCRIPTION_STARTERS = re.compile(
    r'^(?:天|阳光|月光|风|雨|雪|山|河|城|街道|房间|空气中|'
    r'清晨|黄昏|夜晚|春天|夏天|秋天|冬天|太阳|月亮|星星|云|'
    r'远处|近处|四周|周围|眼前|身后|头顶|脚下|'
    r'花|树|草|石|水|火|光|影|声|色|香|味)'
)


# ====================================================================
# D2: 词汇 (Vocabulary) 检测词表
# ====================================================================

# 成语检测 (四字词组, 简化匹配)
IDIOM_PATTERN = re.compile(
    r'[\u4e00-\u9fff]{4}(?:道|说|想|看|笑|走|跑|站|坐|来|去|了|着|过|的|地|得)'
)
# 常见成语结尾模式 (粗筛)
IDIOM_TAIL = re.compile(r'[\u4e00-\u9fff]{2}(?:如也|不已|不得|不堪|不言|不语|无常|无力|有声|有色|有味)')

# 网络用语
INTERNET_SLANG = re.compile(
    r'(?:卧槽|我靠|我擦|牛逼|屌爆|666|233|哈哈哈|呵呵|嘻嘻|'
    r'艾玛|我去|泪目|破防|绝绝子|yyds|awsl|xswl|'
    r'emo|破大防|栓Q|芭比Q|裂开|蚌埠住|赢麻了|杀疯了|'
    r'好家伙|我的天|妈耶|老天爷|我的老天)'
)

# AI 指纹词 (与 style_detector/cross_review 共享子集)
AI_FINGERPRINT_WORDS = [
    "不由地", "不由得", "下意识地", "不禁", "旋即", "方才", "此刻",
    "极为", "极其", "无比", "异常", "惊人地",
    "深吸一口气", "眼中闪过一抹", "嘴角微微上扬", "握紧了拳头",
    "目光扫过", "随手一挥", "化为齑粉", "化为虚无",
    "此外", "总而言之", "综上所述", "值得注意的是", "不可否认",
    "与此同时", "另一方面", "显而易见", "由此可见", "事实上",
    "从而", "进而", "首先", "其次",
]

# 叠词 (形容词/副词叠用, 中文文风特征)
REDUPLICATION = re.compile(r'[\u4e00-\u9fff]{1}[\u4e00-\u9fff]{1}[\u4e00-\u9fff]{1}[\u4e00-\u9fff]{1}')


# ====================================================================
# D3: 节奏 (Rhythm) 检测
# ====================================================================

# 场景切换标记
SCENE_SWITCH = re.compile(
    r'(?:与此同时|另一边|另一处|与此同时|此时|就在这时|就在此时|'
    r'与此同时|不多时|过了一会|片刻后|半晌后|须臾|霎时|'
    r'※|---|\*\*\*|～～)'
)

# 短句阈值 (字数)
SHORT_SENTENCE_THRESHOLD = 12


# ====================================================================
# D4: 幽默 (Humor) 检测词表
# ====================================================================

# 反讽/讽刺标记
IRONY_MARKERS = re.compile(
    r'(?:呵呵|可不是嘛|说得轻巧|想得美|美得你|做梦|想多了|'
    r'好一个|好一句|真是好样的|真行|真了不起|'
    r'鬼才信|谁信啊|骗鬼呢|说得跟真的似的|'
    r'呵呵呵|呵|嗤|哼|切)'
)

# 自嘲标记
SELF_DEPRECATION = re.compile(
    r'(?:自嘲|苦笑|无奈|摇头苦笑|苦涩|心酸|'
    r'自己就是个|自己不过是|自己算什么|'
    r'可笑|可悲|可叹|何苦|何必|'
    r'谁让自己|怪只怪|只怪自己)'
)

# 黑色幽默标记
DARK_HUMOR = re.compile(
    r'(?:黑色幽默|地狱笑话|细思极恐|'
    r'死了一样|比死还难受|生不如死|'
    r'这都不死|主角光环|命硬|'
    r'阎王爷|黑白无常|奈何桥|'
    r'笑死人|笑掉大牙|笑死|乐死)'
)


# ====================================================================
# D5: 视角 (Perspective) 检测词表
# ====================================================================

# 第一人称代词
FIRST_PERSON = re.compile(r'(?:我|我的|我们| ourselves)')
# 第三人称代词
THIRD_PERSON = re.compile(r'(?:他|她|它|他们|她们|它们|他的|她的|它的)')
# 内心独白标记
INNER_MONOLOGUE = re.compile(
    r'(?:心想|暗想|寻思|琢磨|心想道|心中想|'
    r'脑海[中里]?闪过|脑海中浮现|'
    r'我不禁想|他不禁想|她不禁想|'
    r'我在想|他在想|她在想|'
    r'内心深处|心底|心中|'
    r'潜意识|直觉告诉)'
)
# 全知视角标记
OMNISCIENT = re.compile(
    r'(?:殊不知|他不知道的是|她不知道的是|'
    r'此刻的[他她]还不知道|'
    r'远在千里之外|与此同时.*?却|'
    r'如果[他她]知道|假若[他她]知道|'
    r'命运的齿轮|冥冥之中|天意)'
)


# ====================================================================
# 数据结构
# ====================================================================

@dataclass
class StyleDNA:
    """叙事风格 DNA 指纹 (五维量化)。

    每个维度包含多个量化指标, 可直接用于比较和可视化。
    """
    # ── D1: 句法 ──
    avg_sentence_length: float = 0.0       # 平均句长 (中文字符)
    sentence_length_std: float = 0.0       # 句长标准差 (变异度)
    dialogue_ratio: float = 0.0            # 对话占比 (0-1)
    description_density: float = 0.0       # 描写密度 (描写段落比例)
    short_sentence_ratio: float = 0.0      # 短句占比 (≤12字)

    # ── D2: 词汇 ──
    vocab_richness: float = 0.0            # 词汇丰富度 (unique/total)
    idiom_density: float = 0.0             # 成语密度 (个/千字)
    internet_slang_ratio: float = 0.0      # 网络用语比例
    ai_fingerprint_density: float = 0.0    # AI指纹词密度 (个/千字)
    reduplication_density: float = 0.0     # 叠词密度 (个/千字)
    top_words: list[tuple[str, int]] = field(default_factory=list)  # 高频词 Top-20

    # ── D3: 节奏 ──
    avg_paragraph_length: float = 0.0      # 平均段落长度 (字符)
    paragraph_length_std: float = 0.0      # 段落长度标准差
    scene_switch_count: int = 0            # 场景切换次数
    scene_switch_per_1k: float = 0.0       # 场景切换密度 (次/千字)
    paragraph_count: int = 0               # 段落总数

    # ── D4: 幽默 ──
    irony_density: float = 0.0             # 反讽密度 (个/千字)
    self_deprecation_density: float = 0.0  # 自嘲密度 (个/千字)
    dark_humor_density: float = 0.0        # 黑色幽默密度 (个/千字)
    humor_total: float = 0.0               # 幽默总分 (三项加权)

    # ── D5: 视角 ──
    first_person_ratio: float = 0.0        # 第一人称代词占比
    third_person_ratio: float = 0.0        # 第三人称代词占比
    inner_monologue_density: float = 0.0   # 内心独白密度 (个/千字)
    omniscient_density: float = 0.0        # 全知视角标记密度 (个/千字)
    perspective_type: str = "third"        # "first" / "third" / "mixed"

    # ── 元数据 ──
    total_chars: int = 0                   # 总字符数 (中文)
    sentence_count: int = 0                # 总句子数

    def to_dict(self) -> dict:
        """转为可序列化的字典。"""
        d = {}
        for k, v in self.__dict__.items():
            if k == "top_words":
                d[k] = v
            else:
                d[k] = v
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "StyleDNA":
        """从字典重建。"""
        return cls(**{k: v for k, v in d.items() if k in cls.__dict__})


@dataclass
class DimensionDeviation:
    """单维度偏离报告。"""
    name: str
    metrics: list[dict] = field(default_factory=list)
    # 每个 metric: {"name", "target", "current", "diff", "diff_pct", "severity"}
    overall_deviation: float = 0.0  # 加权平均偏差百分比
    severity: str = "ok"            # ok / warning / serious


@dataclass
class StyleDeviation:
    """风格偏离报告 (当前 vs 目标/基线)。"""
    dimensions: list[DimensionDeviation] = field(default_factory=list)
    consistency_score: float = 100.0  # 0-100, 越高越一致
    summary: str = ""
    top_issues: list[str] = field(default_factory=list)

    @property
    def has_issues(self) -> bool:
        return any(d.severity != "ok" for d in self.dimensions)


# ====================================================================
# 主提取函数
# ====================================================================

def extract_dna(text: str) -> StyleDNA:
    """从章节文本中提取五维风格 DNA。

    Args:
        text: 章节正文

    Returns:
        StyleDNA 包含五维量化指标
    """
    dna = StyleDNA()
    chinese_count = _count_chinese(text)
    dna.total_chars = chinese_count

    if chinese_count < 50:
        logger.debug("文本过短 (%d 字), DNA 不完整", chinese_count)
        return dna

    sentences = _split_sentences(text)
    paragraphs = _split_paragraphs(text)
    dna.sentence_count = len(sentences)
    dna.paragraph_count = len(paragraphs)

    # ── D1: 句法 ──
    _extract_syntax(dna, text, sentences, paragraphs, chinese_count)

    # ── D2: 词汇 ──
    _extract_vocabulary(dna, text, chinese_count)

    # ── D3: 节奏 ──
    _extract_rhythm(dna, text, paragraphs, chinese_count)

    # ── D4: 幽默 ──
    _extract_humor(dna, text, chinese_count)

    # ── D5: 视角 ──
    _extract_perspective(dna, text, chinese_count)

    logger.debug("DNA 提取完成: %d 字, %d 句, %d 段",
                chinese_count, len(sentences), len(paragraphs))
    return dna


# ====================================================================
# D1: 句法 (Syntax)
# ====================================================================

def _extract_syntax(dna: StyleDNA, text: str,
                    sentences: list[str], paragraphs: list[str],
                    chinese_count: int):
    """提取句法维度指标。"""
    if not sentences:
        return

    # 句长统计
    sentence_lengths = [_count_chinese(s) for s in sentences]
    dna.avg_sentence_length = round(statistics.mean(sentence_lengths), 1)
    dna.sentence_length_std = round(
        statistics.stdev(sentence_lengths), 1
    ) if len(sentence_lengths) > 1 else 0.0

    # 对话占比 (引号内字符 / 总字符)
    dialogue_chars = 0
    for match in DIALOGUE_PATTERN.finditer(text):
        dialogue_chars += _count_chinese(match.group())
    dna.dialogue_ratio = round(dialogue_chars / max(chinese_count, 1), 3)

    # 描写密度 (以描写词开头的段落比例)
    desc_count = sum(1 for p in paragraphs if DESCRIPTION_STARTERS.match(p[:10]))
    dna.description_density = round(desc_count / max(len(paragraphs), 1), 3)

    # 短句占比
    short_count = sum(1 for l in sentence_lengths if l <= SHORT_SENTENCE_THRESHOLD)
    dna.short_sentence_ratio = round(short_count / max(len(sentence_lengths), 1), 3)


# ====================================================================
# D2: 词汇 (Vocabulary)
# ====================================================================

def _extract_vocabulary(dna: StyleDNA, text: str, chinese_count: int):
    """提取词汇维度指标。"""
    if chinese_count < 100:
        return

    # 词汇丰富度 (unique chars / total chars, 粗略)
    # 更精确的方法是用分词, 但这里用字符级近似
    all_chars = [c for c in text if '\u4e00' <= c <= '\u9fff']
    unique_chars = set(all_chars)
    dna.vocab_richness = round(len(unique_chars) / max(len(all_chars), 1), 4)

    per_1k = max(chinese_count / 1000, 1)

    # 成语密度
    idiom_hits = IDIOM_PATTERN.findall(text) + IDIOM_TAIL.findall(text)
    dna.idiom_density = round(len(idiom_hits) / per_1k, 2)

    # 网络用语比例
    slang_hits = INTERNET_SLANG.findall(text)
    dna.internet_slang_ratio = round(len(slang_hits) / per_1k, 2)

    # AI 指纹词密度
    ai_hits = sum(text.count(w) for w in AI_FINGERPRINT_WORDS)
    dna.ai_fingerprint_density = round(ai_hits / per_1k, 2)

    # 叠词密度 (AA型 / AABB型 / ABAB型, 简化匹配)
    # AA型: 如 "慢慢", "静静"
    aa_pattern = re.compile(r'([\u4e00-\u9fff])\1')
    aa_hits = len(aa_pattern.findall(text))
    dna.reduplication_density = round(aa_hits / per_1k, 2)

    # 高频词 Top-20 (2-4字中文词组, 简化提取)
    # 使用滑动窗口提取2-4字词组
    word_counter = Counter()
    # 提取所有连续中文片段
    segments = re.findall(r'[\u4e00-\u9fff]+', text)
    for seg in segments:
        # 2-gram, 3-gram, 4-gram
        for n in (2, 3, 4):
            for i in range(len(seg) - n + 1):
                word_counter[seg[i:i + n]] += 1

    # 过滤过短和过于常见的词
    common_filter = {"的人", "的一", "是在", "了他", "了的", "这是", "就是",
                     "一个", "他们", "什么", "自己", "这个", "那个", "他的",
                     "她的", "这是", "那是", "不着", "不了", "起来", "下来"}
    filtered = [(w, c) for w, c in word_counter.most_common(50)
                if w not in common_filter and c >= 2]
    dna.top_words = filtered[:20]


# ====================================================================
# D3: 节奏 (Rhythm)
# ====================================================================

def _extract_rhythm(dna: StyleDNA, text: str,
                    paragraphs: list[str], chinese_count: int):
    """提取节奏维度指标。"""
    if not paragraphs:
        return

    # 段落长度分布
    para_lengths = [_count_chinese(p) for p in paragraphs]
    dna.avg_paragraph_length = round(statistics.mean(para_lengths), 1)
    dna.paragraph_length_std = round(
        statistics.stdev(para_lengths), 1
    ) if len(para_lengths) > 1 else 0.0

    # 场景切换
    scene_hits = SCENE_SWITCH.findall(text)
    dna.scene_switch_count = len(scene_hits)
    dna.scene_switch_per_1k = round(len(scene_hits) / max(chinese_count / 1000, 1), 2)


# ====================================================================
# D4: 幽默 (Humor)
# ====================================================================

def _extract_humor(dna: StyleDNA, text: str, chinese_count: int):
    """提取幽默维度指标。"""
    per_1k = max(chinese_count / 1000, 1)

    irony_hits = IRONY_MARKERS.findall(text)
    dna.irony_density = round(len(irony_hits) / per_1k, 2)

    self_dep_hits = SELF_DEPRECATION.findall(text)
    dna.self_deprecation_density = round(len(self_dep_hits) / per_1k, 2)

    dark_hits = DARK_HUMOR.findall(text)
    dna.dark_humor_density = round(len(dark_hits) / per_1k, 2)

    # 幽默总分 (加权: 反讽 0.3, 自嘲 0.4, 黑色幽默 0.3)
    dna.humor_total = round(
        dna.irony_density * 0.3 +
        dna.self_deprecation_density * 0.4 +
        dna.dark_humor_density * 0.3, 2
    )


# ====================================================================
# D5: 视角 (Perspective)
# ====================================================================

def _extract_perspective(dna: StyleDNA, text: str, chinese_count: int):
    """提取视角维度指标。

    注意: 对话内容中的"我"不反映叙事视角, 需先去除对话再统计代词。
    """
    if chinese_count < 100:
        return

    per_1k = max(chinese_count / 1000, 1)

    # 去除对话内容, 仅保留叙述文本 (用于代词统计)
    narrative_text = DIALOGUE_PATTERN.sub('', text)

    # 第一/第三人称代词频率 (基于叙述文本, 非对话)
    first_hits = len(FIRST_PERSON.findall(narrative_text))
    third_hits = len(THIRD_PERSON.findall(narrative_text))
    total_pronouns = first_hits + third_hits

    if total_pronouns > 0:
        dna.first_person_ratio = round(first_hits / total_pronouns, 3)
        dna.third_person_ratio = round(third_hits / total_pronouns, 3)
    else:
        # 如果叙述部分无人称代词, 检查全文本
        first_hits_all = len(FIRST_PERSON.findall(text))
        third_hits_all = len(THIRD_PERSON.findall(text))
        total_all = first_hits_all + third_hits_all
        if total_all > 0:
            dna.first_person_ratio = round(first_hits_all / total_all, 3)
            dna.third_person_ratio = round(third_hits_all / total_all, 3)
        else:
            dna.first_person_ratio = 0.0
            dna.third_person_ratio = 0.0

    # 内心独白密度
    mono_hits = INNER_MONOLOGUE.findall(text)
    dna.inner_monologue_density = round(len(mono_hits) / per_1k, 2)

    # 全知标记密度
    omni_hits = OMNISCIENT.findall(text)
    dna.omniscient_density = round(len(omni_hits) / per_1k, 2)

    # 判断视角类型
    if dna.first_person_ratio > 0.6:
        dna.perspective_type = "first"
    elif dna.first_person_ratio > 0.3:
        dna.perspective_type = "mixed"
    else:
        dna.perspective_type = "third"


# ====================================================================
# 多章基线构建
# ====================================================================

def build_dna_baseline(chapters: list[str]) -> StyleDNA:
    """从多章文本构建风格 DNA 基线 (均值聚合)。

    Args:
        chapters: 多章正文列表

    Returns:
        StyleDNA 各指标取均值, top_words 取全局 Top-20
    """
    if not chapters:
        return StyleDNA()

    dnas = [extract_dna(ch) for ch in chapters if _count_chinese(ch) >= 50]
    if not dnas:
        return StyleDNA()

    if len(dnas) == 1:
        return dnas[0]

    baseline = StyleDNA()

    # 数值字段取均值
    numeric_fields = [
        "avg_sentence_length", "sentence_length_std", "dialogue_ratio",
        "description_density", "short_sentence_ratio",
        "vocab_richness", "idiom_density", "internet_slang_ratio",
        "ai_fingerprint_density", "reduplication_density",
        "avg_paragraph_length", "paragraph_length_std",
        "scene_switch_per_1k",
        "irony_density", "self_deprecation_density",
        "dark_humor_density", "humor_total",
        "first_person_ratio", "third_person_ratio",
        "inner_monologue_density", "omniscient_density",
    ]
    for f in numeric_fields:
        values = [getattr(d, f) for d in dnas]
        setattr(baseline, f, round(statistics.mean(values), 3))

    # 计数字段取总和
    baseline.scene_switch_count = sum(d.scene_switch_count for d in dnas)
    baseline.paragraph_count = sum(d.paragraph_count for d in dnas)
    baseline.sentence_count = sum(d.sentence_count for d in dnas)
    baseline.total_chars = sum(d.total_chars for d in dnas)

    # top_words 合并
    all_words = Counter()
    for d in dnas:
        for word, count in d.top_words:
            all_words[word] += count
    baseline.top_words = all_words.most_common(20)

    # 视角类型取众数
    perspective_types = [d.perspective_type for d in dnas]
    baseline.perspective_type = Counter(perspective_types).most_common(1)[0][0]

    logger.info("基线 DNA 构建: %d 章, %d 字, 视角=%s",
                len(dnas), baseline.total_chars, baseline.perspective_type)
    return baseline


# ====================================================================
# 风格偏离比较
# ====================================================================

# 比较用的指标及其权重和阈值
# (dimension_name, metric_name, weight, warn_pct, serious_pct)
_COMPARE_METRICS = [
    # D1: 句法
    ("句法", "avg_sentence_length", 0.25, 20, 40),
    ("句法", "dialogue_ratio", 0.20, 25, 50),
    ("句法", "description_density", 0.15, 30, 60),
    ("句法", "short_sentence_ratio", 0.15, 25, 50),
    ("句法", "sentence_length_std", 0.10, 30, 60),
    # D2: 词汇
    ("词汇", "ai_fingerprint_density", 0.30, 50, 200),
    ("词汇", "vocab_richness", 0.25, 15, 30),
    ("词汇", "idiom_density", 0.20, 40, 80),
    ("词汇", "internet_slang_ratio", 0.15, 50, 100),
    ("词汇", "reduplication_density", 0.10, 40, 80),
    # D3: 节奏
    ("节奏", "avg_paragraph_length", 0.30, 25, 50),
    ("节奏", "scene_switch_per_1k", 0.25, 30, 60),
    ("节奏", "paragraph_length_std", 0.20, 30, 60),
    ("节奏", "short_sentence_ratio", 0.25, 25, 50),
    # D4: 幽默
    ("幽默", "humor_total", 0.50, 50, 100),
    ("幽默", "irony_density", 0.20, 50, 100),
    ("幽默", "self_deprecation_density", 0.20, 50, 100),
    ("幽默", "dark_humor_density", 0.10, 50, 100),
    # D5: 视角
    ("视角", "inner_monologue_density", 0.30, 40, 80),
    ("视角", "first_person_ratio", 0.25, 20, 40),
    ("视角", "omniscient_density", 0.25, 40, 80),
    ("视角", "dialogue_ratio", 0.20, 25, 50),
]


def compare_dna(target: StyleDNA, current: StyleDNA) -> StyleDeviation:
    """比较当前 DNA 与目标/基线 DNA 的偏离程度。

    Args:
        target: 目标/基线 DNA (通常来自作者多章聚合)
        current: 当前章节 DNA

    Returns:
        StyleDeviation 包含各维度偏离报告和一致性评分
    """
    deviation = StyleDeviation()

    # 按维度分组计算
    dim_groups: dict[str, list[dict]] = {}
    for dim_name, metric_name, weight, warn_pct, serious_pct in _COMPARE_METRICS:
        target_val = getattr(target, metric_name, 0)
        current_val = getattr(current, metric_name, 0)

        if target_val == 0 and current_val == 0:
            diff_pct = 0
        elif target_val == 0:
            diff_pct = 100  # 从无到有 = 100% 偏离
        else:
            diff_pct = abs(current_val - target_val) / abs(target_val) * 100

        severity = "ok"
        if diff_pct >= serious_pct:
            severity = "serious"
        elif diff_pct >= warn_pct:
            severity = "warning"

        metric_info = {
            "name": metric_name,
            "target": target_val,
            "current": current_val,
            "diff": round(current_val - target_val, 3),
            "diff_pct": round(diff_pct, 1),
            "severity": severity,
            "weight": weight,
        }
        dim_groups.setdefault(dim_name, []).append(metric_info)

    # 构建维度报告
    total_weighted_deviation = 0
    total_weight = 0
    for dim_name, metrics in dim_groups.items():
        dim_dev = DimensionDeviation(name=dim_name, metrics=metrics)
        weighted_sum = sum(m["diff_pct"] * m["weight"] for m in metrics)
        total_w = sum(m["weight"] for m in metrics)
        dim_dev.overall_deviation = round(weighted_sum / max(total_w, 1), 1)

        if any(m["severity"] == "serious" for m in metrics):
            dim_dev.severity = "serious"
        elif any(m["severity"] == "warning" for m in metrics):
            dim_dev.severity = "warning"
        else:
            dim_dev.severity = "ok"

        deviation.dimensions.append(dim_dev)
        total_weighted_deviation += dim_dev.overall_deviation * total_w
        total_weight += total_w

    # 一致性评分: 100 - 加权平均偏离 (下限 0)
    avg_deviation = total_weighted_deviation / max(total_weight, 1)
    deviation.consistency_score = round(max(0, 100 - avg_deviation), 1)

    # 生成摘要和 Top 问题
    deviation.summary = _generate_deviation_summary(deviation)
    deviation.top_issues = _collect_top_issues(deviation)

    return deviation


def _generate_deviation_summary(deviation: StyleDeviation) -> str:
    """生成偏离报告摘要文本。"""
    lines = [
        f"\n{'=' * 60}",
        "  风格 DNA 偏离报告",
        f"{'=' * 60}",
        f"  一致性评分: {deviation.consistency_score:.1f}/100",
    ]

    grade = "A" if deviation.consistency_score >= 85 else \
            "B" if deviation.consistency_score >= 70 else \
            "C" if deviation.consistency_score >= 55 else "D"
    lines.append(f"  风格一致性: {grade}")

    for dim in deviation.dimensions:
        icon = {"ok": "[OK]", "warning": "[!]", "serious": "[!!]"}[dim.severity]
        lines.append(f"  {icon} {dim.name}: 偏离 {dim.overall_deviation:.1f}%")
        for m in dim.metrics:
            if m["severity"] != "ok":
                lines.append(
                    f"      - {m['name']}: 基线={m['target']:.2f} -> "
                    f"当前={m['current']:.2f} ({m['diff_pct']:.1f}%)"
                )

    lines.append(f"{'=' * 60}")
    return "\n".join(lines)


def _collect_top_issues(deviation: StyleDeviation) -> list[str]:
    """收集最严重的问题 (按偏离百分比排序)。"""
    all_issues = []
    for dim in deviation.dimensions:
        for m in dim.metrics:
            if m["severity"] != "ok":
                all_issues.append((
                    m["diff_pct"],
                    dim.name,
                    m["name"],
                    m["target"],
                    m["current"],
                    m["severity"],
                ))

    all_issues.sort(key=lambda x: -x[0])
    return [
        f"[{severity}] {dim}/{name}: 基线{target:.2f} -> 当前{current:.2f} "
        f"(偏离{diff:.1f}%)"
        for diff, dim, name, target, current, severity in all_issues[:5]
    ]


# ====================================================================
# S3 评审集成
# ====================================================================

def dna_as_s3_check(
    text: str,
    baseline_dna: StyleDNA | None = None,
) -> dict:
    """作为 S3 评审的风格一致性检查入口。

    Args:
        text: 当前章节文本
        baseline_dna: 基线 DNA (如无则尝试自动加载)

    Returns:
        dict 包含:
          - consistency_score: float (0-100)
          - grade: str (A/B/C/D)
          - dimension_deviations: dict[str, float]
          - top_issues: list[str]
          - should_warn: bool
    """
    current_dna = extract_dna(text)

    if baseline_dna is None or baseline_dna.total_chars == 0:
        return {
            "consistency_score": 100.0,
            "grade": "N/A",
            "dimension_deviations": {},
            "top_issues": ["无基线 DNA, 无法进行风格一致性比较 (需先建立基线)"],
            "should_warn": False,
        }

    deviation = compare_dna(baseline_dna, current_dna)

    grade = "A" if deviation.consistency_score >= 85 else \
            "B" if deviation.consistency_score >= 70 else \
            "C" if deviation.consistency_score >= 55 else "D"

    dim_deviations = {d.name: d.overall_deviation for d in deviation.dimensions}

    return {
        "consistency_score": deviation.consistency_score,
        "grade": grade,
        "dimension_deviations": dim_deviations,
        "top_issues": deviation.top_issues,
        "should_warn": deviation.consistency_score < 70,
        "deviation_report": deviation.summary,
        "current_dna": current_dna.to_dict(),
    }


# ====================================================================
# Part E 增强: 将 DNA 集成到风格画像
# ====================================================================

def enhance_style_profile_with_dna(profile: dict, chapters: list[str]) -> dict:
    """将风格 DNA 集成到现有的 style_evolution 风格画像中。

    在 style_evolution.generate_style_profile() 的输出基础上,
    增加 style_dna 字段, 提供文本级量化指纹。

    Args:
        profile: 现有风格画像 (来自 style_evolution)
        chapters: 作者已写章节文本列表

    Returns:
        增强后的风格画像 (新增 style_dna 和 style_dna_hints 字段)
    """
    if not chapters:
        profile["style_dna"] = None
        profile["style_dna_hints"] = []
        return profile

    # 构建基线 DNA
    baseline = build_dna_baseline(chapters)
    profile["style_dna"] = baseline.to_dict()

    # 生成 DNA 风格提示
    hints = []

    # D1 句法提示
    if baseline.avg_sentence_length > 0:
        if baseline.avg_sentence_length < 15:
            hints.append(f"句法特征: 短句为主 (平均{baseline.avg_sentence_length:.0f}字), 节奏明快")
        elif baseline.avg_sentence_length > 25:
            hints.append(f"句法特征: 长句为主 (平均{baseline.avg_sentence_length:.0f}字), 叙事绵密")
        else:
            hints.append(f"句法特征: 句长适中 (平均{baseline.avg_sentence_length:.0f}字)")

    if baseline.dialogue_ratio > 0.4:
        hints.append(f"对话偏好: 高对话占比 ({baseline.dialogue_ratio:.0%}), 对话驱动叙事")
    elif baseline.dialogue_ratio < 0.15:
        hints.append(f"对话偏好: 低对话占比 ({baseline.dialogue_ratio:.0%}), 叙述驱动叙事")

    # D2 词汇提示
    if baseline.ai_fingerprint_density > 3:
        hints.append(f"注意: AI指纹词密度偏高 ({baseline.ai_fingerprint_density:.1f}/千字), 需控制")
    if baseline.idiom_density > 2:
        hints.append(f"词汇特征: 成语使用频繁 ({baseline.idiom_density:.1f}/千字)")
    if baseline.internet_slang_ratio > 1:
        hints.append(f"词汇特征: 网络用语比例较高 ({baseline.internet_slang_ratio:.1f}/千字)")

    # D3 节奏提示
    if baseline.scene_switch_per_1k > 1:
        hints.append(f"节奏特征: 场景切换频繁 ({baseline.scene_switch_per_1k:.1f}次/千字)")
    if baseline.avg_paragraph_length < 50:
        hints.append(f"段落特征: 短段落为主 (平均{baseline.avg_paragraph_length:.0f}字)")

    # D4 幽默提示
    if baseline.humor_total > 1:
        hints.append(f"幽默风格: 活跃 ({baseline.humor_total:.1f}), "
                     f"反讽{baseline.irony_density:.1f}/自嘲{baseline.self_deprecation_density:.1f}")

    # D5 视角提示
    if baseline.perspective_type == "first":
        hints.append(f"视角特征: 第一人称叙事 (第一人称占比{baseline.first_person_ratio:.0%})")
    elif baseline.perspective_type == "mixed":
        hints.append(f"视角特征: 混合视角 (第一人称占比{baseline.first_person_ratio:.0%})")
    else:
        hints.append(f"视角特征: 第三人称叙事 (内心独白{baseline.inner_monologue_density:.1f}/千字)")

    profile["style_dna_hints"] = hints
    profile["style_dna_maturity"] = (
        "rich" if len(chapters) >= 30 else
        "mature" if len(chapters) >= 15 else
        "building" if len(chapters) >= 5 else "seed"
    )

    logger.info("风格 DNA 集成完成: %d 条提示, 成熟度=%s",
                len(hints), profile["style_dna_maturity"])
    return profile
