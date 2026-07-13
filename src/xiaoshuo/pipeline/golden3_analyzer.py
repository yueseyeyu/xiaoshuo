# -*- coding: utf-8 -*-
"""
golden3_analyzer.py — 黄金三章专项分析器 (P1.1)
=================================================
来源: 建议文件 "黄金三章 → 新增专项检测模块"

七维检测 (G1-G7):
  G1 高能钩子       — 第1章前500字是否有冲突/悬念/反常 (3秒法则)
  G2 人设清晰度     — 主角名字、目标、缺陷是否在前3章确立
  G3 核心矛盾       — "A wants B but C" 冲突结构是否明确
  G4 铺垫密度       — 伏笔数量 / 章节数 >= 阈值
  G5 情绪曲线       — 前3章是否有明显的情绪起伏
  G6 市场反馈       — 第3章是否有外部人群反应 (围观/评论/热搜/弹幕)
  G7 关系绑定       — 是否有强关系绑定 (前任/清冷/全网/恋综/综艺)
  G8 预期兑现       — 书名/标签关键词在前3章是否有对应内容兑现 (v3)
  G9 主角保护       — 虐主检测: 前3章负面事件密度+金手指延迟+能力对冲 (v4)

v8.8 新增 G6/G7:
  来源: 建议文件 "番茄首秀存活预测" + "市场死亡结构检测"
  价值: 将市场维度 (人群反馈/关系绑定) 纳入黄金三章评估
  G6 合并了 survival_predictor R2 (三章反馈) + market_death_detector D2 (系统无反应)
  G7 来自 survival_predictor R5 (强关系绑定)

设计原则:
  - 零 LLM 依赖: 全部规则/统计检测
  - 与 writing_craft_lens 互补: 后者查"单章技法", 本模块查"跨章结构"
  - 可选 Canon 增强: 传入 canon 数据时交叉验证人设/伏笔/矛盾
  - 可选 Benchmark 对比: 与同类爆款前3章数据对比

触发时机:
  - 作者完成前3章草稿后自动运行
  - 或作为 S3 评审的前置检查

用法:
  from xiaoshuo.pipeline.golden3_analyzer import analyze_golden3
  report = analyze_golden3(
      chapters=["第1章正文...", "第2章正文...", "第3章正文..."],
      canon=canon_data,  # 可选
      benchmarks=bench_data,  # 可选
  )
  print(report.summary)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from xiaoshuo.infra.logging_config import get_logger
from xiaoshuo.pipeline.text_utils import count_chinese as _count_chinese

logger = get_logger("golden3")


# ── G1: 高能钩子检测词表 ──
# 第1章前500字需要的冲突/悬念/反常信号
HOOK_CONFLICT = re.compile(
    r"战斗|厮杀|搏杀|血战|激战|大战|对决|决斗|"
    r"杀意|杀气|杀机|出手|进攻|攻击|反击|偷袭|暗算|围杀|"
    r"拼命|拼死|搏命|殊死|生死|致命|"
    r"你敢|休想|去死|找死|不可能！|我不信|凭什么"
)
HOOK_SUSPENSE = re.compile(
    r"究竟|到底|为什么|怎么会|难道|莫非|谁|什么|答案|秘密|"
    r"未知|诡异|奇怪|异常|不对劲|不可能|匪夷所思|"
    r"忽然|突然|骤然|猛然|赫然|不料|竟然|居然"
)
HOOK_DANGER = re.compile(
    r"危险|危机|威胁|陷阱|包围|逼近|来袭|"
    r"逃|躲|追|困|陷|围|困住|困在"
)
HOOK_ANOMALY = re.compile(
    r"反常|异变|变异|异象|异常|不寻常|前所未有|"
    r"黑色|血红|诡异|恐怖|阴森|不详"
)

# 环境描写开头 (扣分项)
ENV_OPENING = re.compile(
    r'^(?:天|阳光|月光|风|雨|雪|山|河|城|街道|房间|空气中|'
    r'清晨|黄昏|夜晚|春天|夏天|秋天|冬天|太阳|月亮|星星|云)'
)

# 信息密度标记
INFO_MARKERS = re.compile(
    r'(?:发现|揭示|得知|明白|意识到|原来|真相|秘密|'
    r'新|突然|意外|浮现|浮现|浮现|显示|弹出|解锁|觉醒)'
)

# ── G1 v9.0: 开篇共鸣事件类型 (来源: "4个追读技巧" — 开篇事件共鸣) ──
# 检测前500字中的共鸣类型, 用于判断"筛选目标读者"的机制
RESONANCE_CAREER = re.compile(
    r'先立业|事业|搞钱|赚钱|出人头地|升职|加薪|创业|'
    r'不想.*打工|辞职|自由|独立|靠自己'
)
RESONANCE_REVENGE = re.compile(
    r'复仇|报仇|血仇|雪恨|讨回|清算|以牙还牙|'
    r'灭门|被害|冤枉|陷害|背叛.*代价'
)
RESONANCE_UNDERDOG = re.compile(
    r'逆袭|翻盘|不甘|被看不起|被轻视|被嘲笑|被羞辱|'
    r'废物|废柴|没用|不行|配不上|就这|也就这样|'
    r'吊车尾|垫底|倒数|最差'
)
RESONANCE_IDENTITY = re.compile(
    r'身份|不配|没资格|庶出|私生|低等|下等|卑贱|'
    r'伪装|隐瞒.*身份|暴露.*身份|被发现|被认出|'
    r'谁让他|凭什么.*他|不配.*存在'
)

RESONANCE_PATTERNS = [
    ("事业型", RESONANCE_CAREER),
    ("复仇型", RESONANCE_REVENGE),
    ("逆袭型", RESONANCE_UNDERDOG),
    ("身份冲突型", RESONANCE_IDENTITY),
]


# ── G2: 人设清晰度检测词表 ──
# 目标/欲望标记
GOAL_MARKERS = re.compile(
    r'(?:想要|需要|必须|一定要|决心|发誓|目标|梦想|渴望|'
    r'为了|想要得到|追求|争取|夺|抢|找回|保护|守护|复仇|报仇|'
    r'变强|成为|超越|征服|统一|称霸|证道|飞升)'
)
# 缺陷/弱点标记
FLAW_MARKERS = re.compile(
    r'(?:失误|犯错|搞砸|失手|判断错误|后悔|愧疚|自责|犹豫|迟疑|'
    r'弱点|软肋|心魔|缺陷|不足|短处|缺陷|盲目|冲动|'
    r'懦弱|胆小|自卑|傲慢|固执|偏执|贪婪|恐惧|害怕)'
)
# 成长标记
GROWTH_MARKERS = re.compile(
    r'(?:突破|领悟|觉醒|改变|成长|明白|意识到|终于|第一次|'
    r'进化|蜕变|升级|进阶|脱胎换骨|今非昔比)'
)


# ── G3: 核心矛盾检测词表 ──
# "A wants B but C" 结构标记
WANT_MARKERS = re.compile(
    r'(?:想要|需要|必须|渴望|追求|想要得到|为了|'
    r'目标|梦想|野心|欲望|企图)'
)
OBSTACLE_MARKERS = re.compile(
    r'(?:但是|可是|然而|不过|却|偏偏|无奈|只是|可惜|'
    r'阻碍|障碍|困难|敌人|对手|限制|约束|不可能|无法|不能|'
    r'阻止|阻止不了|挡|拦|封锁|围剿|追杀)'
)
CONFRONT_MARKERS = re.compile(
    r'(?:对抗|对抗|对决|较量|交手|冲突|矛盾|争斗|'
    r'反击|反抗|挣扎|突破|打破|冲破)'
)


# ── G4: 伏笔铺垫密度 ──
FORESHADOW_MARKERS = re.compile(
    r'(?:伏笔|暗示|线索|疑点|谜团|悬念|疑问|'
    r'不知|不明|神秘|奇怪|诡异|未解|'
    r'仿佛|似乎|好像|隐约|若有若无|'
    r'原来如此|终于明白|真相大白|谜底揭晓)'
)
FORESHADOW_HINT = re.compile(
    r'(?:不[寻正]常|不对劲|有问题|蹊跷|古怪|'
    r'意味深长|若有所思|欲言又止|欲言又止|'
    r'意味深长的|意味深长地|深邃的|'
    r'埋下|埋了|暗藏|暗含|暗指|影射)'
)


# ── G5: 情绪曲线检测词表 ──
EMOTION_HIGH = re.compile(
    r"愤怒|暴怒|狂怒|震怒|怒火|激怒|"
    r"狂喜|狂笑|兴奋|激动|振奋|热血沸腾|"
    r"恐惧|惊恐|骇然|胆寒|毛骨悚然|"
    r"绝望|崩溃|歇斯底里|疯狂|癫狂|"
    r"震惊|震撼|不可思议|难以置信|"
    r"战斗|厮杀|搏杀|血战|拼命|殊死"
)
EMOTION_MID = re.compile(
    r"紧张|焦虑|不安|担忧|忧虑|忐忑|"
    r"期待|希望|渴望|向往|"
    r"疑惑|困惑|迷茫|不解|"
    r"惊讶|意外|愣|怔|呆"
)
EMOTION_LOW = re.compile(
    r"平静|淡然|释然|坦然|从容|平和|波澜不惊|心如止水|"
    r"麻木|冷漠|漠然|空洞|认命|"
    r"疲惫|乏力|无力|叹息|沉重"
)
EMOTION_POSITIVE = re.compile(
    r"开心|快乐|幸福|满足|欣慰|温暖|"
    r"笑|微笑|大笑|苦笑|"
    r"感动|感恩|感激|感谢|"
    r"信任|信赖|安心|放心"
)


# ── 数据结构 ──

@dataclass
class Golden3Dimension:
    """单维检测结果。"""
    dimension: str           # G1-G5
    name: str                # 维度名称
    score: float = 0.0       # 0-10
    threshold: float = 6.0   # 及格线
    passed: bool = False
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)  # 维度专属数据

    @property
    def grade(self) -> str:
        if self.score >= 9: return "S"
        if self.score >= 8: return "A"
        if self.score >= 7: return "B"
        if self.score >= 6: return "C"
        if self.score >= 4: return "D"
        return "F"


@dataclass
class Golden3Report:
    """黄金三章分析报告。"""
    dimensions: list[Golden3Dimension] = field(default_factory=list)
    total_score: float = 0.0     # 加权总分
    grade: str = ""              # S/A/B/C/D/F
    passed_count: int = 0
    failed_count: int = 0
    summary: str = ""
    benchmark_comparison: dict | None = None  # 与爆款对比
    genre_trend: str = ""        # v8.8: 题材趋势 (hot/normal/declining)

    def add(self, dim: Golden3Dimension):
        self.dimensions.append(dim)
        if dim.passed:
            self.passed_count += 1
        else:
            self.failed_count += 1

    def get(self, dimension: str) -> Golden3Dimension | None:
        for d in self.dimensions:
            if d.dimension == dimension:
                return d
        return None


# ── 各维度权重 (用于加权总分) ──
DIM_WEIGHTS = {
    "G1": 0.18,  # 高能钩子 — 最重要, 决定读者是否继续
    "G2": 0.14,  # 人设清晰度 — 前3章必须建立角色认知
    "G3": 0.18,  # 核心矛盾 — 故事驱动力
    "G4": 0.10,  # 铺垫密度 — 长线吸引力
    "G5": 0.10,  # 情绪曲线 — 阅读体验
    "G6": 0.05,  # 市场反馈 — 人群反应决定代入感 (v8.8)
    "G7": 0.05,  # 关系绑定 — 强关系驱动冲突 (v8.8)
    "G8": 0.08,  # 预期兑现 — 书名/标签承诺必须前3章兑现 (v3)
    "G9": 0.12,  # 主角保护 — 虐主检测, 直接关联番茄首秀存活率 (v4)
}


# ── G1: 高能钩子检测 ──

def check_high_energy_hook(ch1_text: str) -> Golden3Dimension:
    """G1: 高能钩子 — 第1章前500字是否有冲突/悬念/反常。

    检测项:
      - 3秒法则: 前100字是否有冲突/悬念信号
      - 信息密度: 前500字每100字信息增量 >= 1
      - 环境描写开头: 扣分
      - 多信号叠加: 加分
    """
    dim = Golden3Dimension(
        dimension="G1",
        name="高能钩子",
        threshold=6.0,
    )

    chinese = _count_chinese(ch1_text)
    if chinese < 50:
        dim.score = 2.0
        dim.issues.append("第1章文本过短, 无法有效分析")
        dim.suggestions.append("建议: 第1章至少2000字, 确保能展开核心冲突")
        dim.passed = dim.score >= dim.threshold
        return dim

    opening_500 = ch1_text[:500]
    opening_100 = ch1_text[:100]
    cn_500 = _count_chinese(opening_500)
    cn_100 = _count_chinese(opening_100)

    score = 5.0  # 基础分

    # 1. 3秒法则: 前100字
    has_conflict = bool(HOOK_CONFLICT.search(opening_100))
    has_suspense = bool(HOOK_SUSPENSE.search(opening_100))
    has_danger = bool(HOOK_DANGER.search(opening_100))

    signal_count = sum([has_conflict, has_suspense, has_danger])
    if signal_count >= 2:
        score += 3.0
        dim.details["3秒法则"] = "优: 前100字多重信号叠加"
    elif signal_count == 1:
        score += 1.5
        dim.details["3秒法则"] = "良: 前100字有冲突/悬念信号"
    else:
        dim.issues.append("前100字无冲突/悬念/危险信号 (违反3秒法则)")
        dim.suggestions.append("建议: 开头直接切入冲突或悬念, 不要铺垫环境/设定")

    # 2. 信息密度: 前500字
    info_hits = INFO_MARKERS.findall(opening_500)
    info_per_100 = len(info_hits) / max(cn_500 / 100, 1)
    dim.details["信息密度"] = f"{info_per_100:.1f}个/百字"

    if info_per_100 >= 1.5:
        score += 2.0
    elif info_per_100 >= 1.0:
        score += 1.0
    elif info_per_100 < 0.3:
        score -= 1.5
        dim.issues.append(f"信息密度极低: {info_per_100:.1f}个/百字 (疑似设定堆砌)")
        dim.suggestions.append("建议: 每100字至少1个新信息增量, 避免纯设定描写")

    # 3. 环境描写开头: 扣分
    if ENV_OPENING.match(ch1_text[:10]):
        score -= 2.0
        dim.issues.append("开头为环境描写 (读者流失高风险)")
        dim.suggestions.append("建议: 从动作/对话/事件开头, 环境信息融入叙事")
    elif re.match(r'^(?:他|她|它|我|那|这)', ch1_text[:5]):
        score += 0.5  # 人物/事件开头: 加分

    # 4. 前500字整体信号强度
    all_signals_500 = (
        len(HOOK_CONFLICT.findall(opening_500)) +
        len(HOOK_SUSPENSE.findall(opening_500)) +
        len(HOOK_DANGER.findall(opening_500)) +
        len(HOOK_ANOMALY.findall(opening_500))
    )
    dim.details["前500字信号数"] = all_signals_500
    if all_signals_500 >= 5:
        score += 1.0
        dim.details["信号强度"] = "高"
    elif all_signals_500 == 0:
        score -= 1.0
        dim.issues.append("前500字完全无钩子信号")
        dim.suggestions.append("建议: 增加冲突、悬念或异常事件, 提升开篇吸引力")

    # 5. v9.0: 开篇共鸣事件类型检测 (来源: "4个追读技巧")
    resonance_types = []
    for rtype, rpat in RESONANCE_PATTERNS:
        if rpat.search(opening_500):
            resonance_types.append(rtype)
    if resonance_types:
        dim.details["共鸣类型"] = "+".join(resonance_types)
        score += 1.0  # 有共鸣事件加分
    else:
        dim.details["共鸣类型"] = "未检测到"
        if ch1_text and _count_chinese(ch1_text) >= 500:
            dim.suggestions.append(
                "建议: 前500字加入共鸣事件 (事业型/复仇型/逆袭型/身份冲突型), "
                "筛选目标读者并建立代入感"
            )

    score = max(0, min(10, score))
    dim.score = round(score, 1)
    dim.passed = dim.score >= dim.threshold
    return dim


# ── G2: 人设清晰度检测 ──

def check_character_clarity(
    chapters: list[str],
    canon: dict | None = None,
) -> Golden3Dimension:
    """G2: 人设清晰度 — 主角名字、目标、缺陷是否在前3章确立。

    检测项:
      - 主角名字出现频率 (前3章至少出现5次)
      - 目标/欲望标记 (至少1次)
      - 缺陷/弱点标记 (至少1次)
      - Canon 交叉验证 (可选)
    """
    dim = Golden3Dimension(
        dimension="G2",
        name="人设清晰度",
        threshold=6.0,
    )

    full_text = "".join(chapters)
    chinese = _count_chinese(full_text)
    if chinese < 500:
        dim.score = 3.0
        dim.issues.append("前3章总文本过短")
        dim.passed = dim.score >= dim.threshold
        return dim

    score = 5.0

    # 1. 主角名字检测
    protagonist_name = ""
    if canon and isinstance(canon.get("characters"), dict):
        proto = canon["characters"].get("protagonist", {})
        if isinstance(proto, dict):
            protagonist_name = proto.get("name", "")

    if not protagonist_name:
        # 尝试从文本提取: 第1章前200字中高频出现的2-3字人名
        opening = chapters[0][:500] if chapters else ""
        # 简化: 找"XX说"/"XX道"模式
        name_matches = re.findall(r'([\u4e00-\u9fff]{2,4})(?:说|道|想|看|笑|走|跑|站|坐)', opening)
        if name_matches:
            from collections import Counter
            name_freq = Counter(name_matches)
            protagonist_name = name_freq.most_common(1)[0][0]

    if protagonist_name:
        name_count = full_text.count(protagonist_name)
        dim.details["主角名"] = protagonist_name
        dim.details["出现次数"] = name_count

        if name_count >= 10:
            score += 2.0
        elif name_count >= 5:
            score += 1.0
        elif name_count < 2:
            score -= 1.5
            dim.issues.append(f"主角名'{protagonist_name}'在前3章仅出现{name_count}次")
            dim.suggestions.append("建议: 确保主角名字在前3章高频出现, 建立读者认知")
    else:
        dim.issues.append("无法检测到主角名 (需 Canon 或文本中有'XX说'模式)")
        dim.suggestions.append("建议: 提供Canon角色卡, 或确保前3章有明确的主角称谓")
        score -= 1.0

    # 2. 目标/欲望标记
    goal_hits = GOAL_MARKERS.findall(full_text)
    dim.details["目标标记数"] = len(goal_hits)
    if goal_hits:
        score += 1.5
        dim.details["目标信号"] = "已检测到角色目标/欲望"
    else:
        dim.issues.append("未检测到主角目标/欲望标记")
        dim.suggestions.append("建议: 前3章应明确主角的核心目标 (如复仇/变强/保护)")

    # 3. 缺陷/弱点标记
    flaw_hits = FLAW_MARKERS.findall(full_text)
    dim.details["缺陷标记数"] = len(flaw_hits)
    if flaw_hits:
        score += 1.5
        dim.details["缺陷信号"] = "已检测到角色缺陷/弱点"
    else:
        dim.issues.append("未检测到主角缺陷/弱点 (完美人设风险)")
        dim.suggestions.append("建议: 给主角一个可共鸣的缺陷, 避免完美人设")

    # 4. Canon 交叉验证
    if canon and isinstance(canon.get("characters"), dict):
        proto = canon["characters"].get("protagonist", {})
        if isinstance(proto, dict):
            arc = proto.get("arc", "")
            personality = proto.get("personality", "")
            if arc or personality:
                dim.details["Canon角色卡"] = "已加载"
                # 检查 Canon 中定义的弧线关键词是否在文本中出现
                if arc:
                    arc_keywords = [w for w in re.findall(r'[\u4e00-\u9fff]{2,4}', arc)]
                    matched = [w for w in arc_keywords if w in full_text]
                    if matched:
                        score += 0.5
                        dim.details["弧线关键词匹配"] = matched
                    else:
                        dim.issues.append("Canon角色弧线关键词未在前3章文本中出现")

    score = max(0, min(10, score))
    dim.score = round(score, 1)
    dim.passed = dim.score >= dim.threshold
    return dim


# ── G3: 核心矛盾检测 ──

def check_core_conflict(
    chapters: list[str],
    canon: dict | None = None,
) -> Golden3Dimension:
    """G3: 核心矛盾 — "A wants B but C" 冲突结构是否明确。

    检测项:
      - 欲望标记 (A wants B): 至少1次
      - 阻碍标记 (but C): 至少1次
      - 对抗标记: 至少1次
      - Canon 核心矛盾字段交叉验证
      - 前3章矛盾升级趋势
    """
    dim = Golden3Dimension(
        dimension="G3",
        name="核心矛盾",
        threshold=6.0,
    )

    full_text = "".join(chapters)
    chinese = _count_chinese(full_text)
    if chinese < 500:
        dim.score = 3.0
        dim.issues.append("前3章总文本过短")
        dim.passed = dim.score >= dim.threshold
        return dim

    score = 5.0

    # 1. "A wants B" — 欲望标记
    want_hits = WANT_MARKERS.findall(full_text)
    dim.details["欲望标记数"] = len(want_hits)

    # 2. "but C" — 阻碍标记
    obstacle_hits = OBSTACLE_MARKERS.findall(full_text)
    dim.details["阻碍标记数"] = len(obstacle_hits)

    # 3. 对抗标记
    confront_hits = CONFRONT_MARKERS.findall(full_text)
    dim.details["对抗标记数"] = len(confront_hits)

    has_want = len(want_hits) > 0
    has_obstacle = len(obstacle_hits) > 0
    has_confront = len(confront_hits) > 0

    # ABC 结构完整度
    if has_want and has_obstacle:
        score += 2.0
        dim.details["ABC结构"] = "完整: 欲望+阻碍"
        if has_confront:
            score += 1.0
            dim.details["ABC结构"] = "完整: 欲望+阻碍+对抗"
    elif has_want:
        score += 0.5
        dim.issues.append("有欲望但缺少明确的阻碍标记")
        dim.suggestions.append("建议: 明确阻碍主角的对手/环境/规则, 形成'A想要B但C阻止'结构")
    elif has_obstacle:
        score += 0.5
        dim.issues.append("有阻碍但缺少主角的主动欲望")
        dim.suggestions.append("建议: 明确主角的目标和欲望, 让读者知道主角'想要什么'")
    else:
        dim.issues.append("未检测到核心矛盾结构 (欲望+阻碍)")
        dim.suggestions.append("建议: 前3章必须建立'主角想要X但Y阻止'的核心矛盾")
        score -= 2.0

    # 4. 矛盾升级趋势 (逐章检查)
    ch_scores = []
    for i, ch_text in enumerate(chapters[:3]):
        ch_want = len(WANT_MARKERS.findall(ch_text))
        ch_obs = len(OBSTACLE_MARKERS.findall(ch_text))
        ch_conf = len(CONFRONT_MARKERS.findall(ch_text))
        ch_total = ch_want + ch_obs + ch_conf
        ch_scores.append(ch_total)
        dim.details[f"ch{i+1}矛盾信号"] = ch_total

    if len(ch_scores) >= 2:
        if ch_scores[-1] > ch_scores[0]:
            score += 1.0
            dim.details["矛盾趋势"] = "递增 (良好)"
        elif ch_scores[-1] < ch_scores[0] * 0.5:
            score -= 1.0
            dim.issues.append("矛盾信号逐章递减 (读者可能失去兴趣)")
            dim.suggestions.append("建议: 前3章矛盾应逐步升级, 而非淡化")
        else:
            dim.details["矛盾趋势"] = "平稳"

    # 5. Canon 交叉验证
    if canon:
        # 从 novel_outline 检查 core_conflict
        outline = canon.get("novel_outline", {})
        if isinstance(outline, dict):
            core_conflict = outline.get("core_conflict", "")
            if core_conflict:
                dim.details["Canon核心矛盾"] = core_conflict[:50]
                # 检查关键词是否在文本中出现
                conflict_keywords = re.findall(r'[\u4e00-\u9fff]{2,4}', core_conflict)
                matched = [w for w in conflict_keywords[:5] if w in full_text]
                if matched:
                    score += 0.5
                    dim.details["矛盾关键词匹配"] = matched
                else:
                    dim.issues.append("Canon定义的核心矛盾关键词未在前3章出现")
                    dim.suggestions.append(f"建议: 确保前3章体现Canon中定义的核心矛盾: {core_conflict[:30]}...")

    score = max(0, min(10, score))
    dim.score = round(score, 1)
    dim.passed = dim.score >= dim.threshold
    return dim


# ── G4: 铺垫密度检测 ──

def check_foreshadowing_density(
    chapters: list[str],
    canon: dict | None = None,
) -> Golden3Dimension:
    """G4: 铺垫密度 — 伏笔数量 / 章节数 >= 阈值。

    检测项:
      - 伏笔标记密度 (每千字)
      - 暗示性描写密度
      - Canon 伏笔数据交叉验证
      - 前3章至少埋设2个伏笔
    """
    dim = Golden3Dimension(
        dimension="G4",
        name="铺垫密度",
        threshold=5.0,  # 伏笔维度阈值略低
    )

    full_text = "".join(chapters)
    chinese = _count_chinese(full_text)
    if chinese < 500:
        dim.score = 3.0
        dim.issues.append("前3章总文本过短")
        dim.passed = dim.score >= dim.threshold
        return dim

    score = 5.0

    # 1. 伏笔标记密度
    foreshadow_hits = FORESHADOW_MARKERS.findall(full_text)
    hint_hits = FORESHADOW_HINT.findall(full_text)
    total_foreshadow = len(foreshadow_hits) + len(hint_hits)

    per_1k = total_foreshadow / max(chinese / 1000, 1)
    dim.details["伏笔标记总数"] = total_foreshadow
    dim.details["每千字密度"] = round(per_1k, 2)

    if per_1k >= 2.0:
        score += 3.0
        dim.details["伏笔密度"] = "高"
    elif per_1k >= 1.0:
        score += 1.5
        dim.details["伏笔密度"] = "中"
    elif per_1k < 0.3:
        score -= 2.0
        dim.issues.append(f"伏笔密度极低: {per_1k:.2f}个/千字")
        dim.suggestions.append("建议: 前3章至少埋设2-3个伏笔, 为后续剧情铺垫")

    # 2. 每章伏笔分布
    for i, ch_text in enumerate(chapters[:3]):
        ch_cn = _count_chinese(ch_text)
        ch_fs = len(FORESHADOW_MARKERS.findall(ch_text)) + len(FORESHADOW_HINT.findall(ch_text))
        dim.details[f"ch{i+1}伏笔"] = ch_fs

    # 3. 至少2个独立伏笔
    if total_foreshadow >= 4:
        score += 1.0
    elif total_foreshadow < 2:
        dim.issues.append(f"前3章仅检测到{total_foreshadow}个伏笔信号 (建议>=2)")
        dim.suggestions.append("建议: 增加暗示性描写, 如神秘物品/未解之谜/角色秘密")

    # 4. Canon 伏笔交叉验证
    if canon:
        fs_data = canon.get("foreshadowing", {})
        if isinstance(fs_data, dict):
            active = fs_data.get("active", [])
            if isinstance(active, list):
                early_fs = [f for f in active if isinstance(f, dict) and f.get("chapter_planted", 999) <= 3]
                dim.details["Canon伏笔(前3章)"] = len(early_fs)
                if early_fs:
                    score += 1.0
                    dim.details["Canon伏笔内容"] = [f.get("hook", "")[:20] for f in early_fs[:3]]

            # timeline golden_three 验证
            timeline = canon.get("timeline", {})
            if isinstance(timeline, dict):
                golden_three = timeline.get("golden_three", [])
                if isinstance(golden_three, list):
                    total_hooks = sum(
                        len(gt.get("hooks", [])) for gt in golden_three
                        if isinstance(gt, dict)
                    )
                    dim.details["Canon黄金三章钩子"] = total_hooks
                    if total_hooks >= 3:
                        score += 0.5

    score = max(0, min(10, score))
    dim.score = round(score, 1)
    dim.passed = dim.score >= dim.threshold
    return dim


# ── G5: 情绪曲线检测 ──

def check_emotional_curve(chapters: list[str]) -> Golden3Dimension:
    """G5: 情绪曲线 — 前3章是否有明显的情绪起伏。

    检测项:
      - 每章情绪强度 (高/中/低/正面)
      - 跨章情绪变化 (不能单调)
      - 至少有一个情绪高潮
      - 情绪对比度 (高 vs 低)
    """
    dim = Golden3Dimension(
        dimension="G5",
        name="情绪曲线",
        threshold=6.0,
    )

    if not chapters or _count_chinese("".join(chapters)) < 500:
        dim.score = 3.0
        dim.issues.append("前3章总文本过短")
        dim.passed = dim.score >= dim.threshold
        return dim

    score = 5.0

    # 逐章情绪分析
    ch_emotions = []
    for i, ch_text in enumerate(chapters[:3]):
        cn = _count_chinese(ch_text)
        if cn < 50:
            ch_emotions.append({"high": 0, "mid": 0, "low": 0, "pos": 0, "total": 0})
            continue

        high = len(EMOTION_HIGH.findall(ch_text))
        mid = len(EMOTION_MID.findall(ch_text))
        low = len(EMOTION_LOW.findall(ch_text))
        pos = len(EMOTION_POSITIVE.findall(ch_text))
        total = high + mid + low + pos
        density = total / max(cn / 1000, 1)

        ch_emotions.append({
            "high": high, "mid": mid, "low": low, "pos": pos,
            "total": total, "density": round(density, 2),
        })
        dim.details[f"ch{i+1}情绪"] = f"高{high}/中{mid}/低{low}/正{pos} (密度{density:.1f}/千字)"

    # 1. 情绪密度
    avg_density = sum(e.get("density", 0) for e in ch_emotions) / max(len(ch_emotions), 1)
    dim.details["平均情绪密度"] = round(avg_density, 2)

    if avg_density >= 5.0:
        score += 2.0
    elif avg_density >= 3.0:
        score += 1.0
    elif avg_density < 1.0:
        score -= 2.0
        dim.issues.append(f"情绪密度极低: {avg_density:.1f}/千字 (疑似流水账)")
        dim.suggestions.append("建议: 增加情绪描写词, 避免纯事件叙述")

    # 2. 情绪变化 (跨章)
    if len(ch_emotions) >= 2:
        densities = [e.get("density", 0) for e in ch_emotions]
        max_d = max(densities)
        min_d = min(densities)
        contrast = max_d - min_d

        dim.details["情绪对比度"] = round(contrast, 2)

        if contrast >= 2.0:
            score += 1.5
            dim.details["情绪趋势"] = "有明显起伏 (良好)"
        elif contrast < 0.5 and avg_density < 2.0:
            score -= 1.0
            dim.issues.append("情绪曲线过于平坦 (3章情绪无变化)")
            dim.suggestions.append("建议: 前3章应有情绪起伏, 如紧张→放松→爆发")

    # 3. 至少一个情绪高潮
    has_climax = any(e.get("high", 0) >= 3 for e in ch_emotions)
    if has_climax:
        score += 1.5
        dim.details["情绪高潮"] = "已检测到"
    else:
        dim.issues.append("前3章未检测到情绪高潮 (高强度情绪词<3)")
        dim.suggestions.append("建议: 至少在一章中安排情绪爆发点 (愤怒/震惊/绝望)")

    # 4. 情绪类型多样性
    all_types = set()
    for e in ch_emotions:
        if e.get("high", 0): all_types.add("high")
        if e.get("mid", 0): all_types.add("mid")
        if e.get("low", 0): all_types.add("low")
        if e.get("pos", 0): all_types.add("pos")

    dim.details["情绪类型数"] = len(all_types)
    if len(all_types) >= 3:
        score += 1.0
    elif len(all_types) <= 1:
        dim.issues.append("情绪类型单一 (缺乏多样性)")
        dim.suggestions.append("建议: 融合多种情绪, 避免全程紧张或全程平淡")

    score = max(0, min(10, score))
    dim.score = round(score, 1)
    dim.passed = dim.score >= dim.threshold
    return dim


# ── G6: 市场反馈检测 (v8.8) ──
# 来源: survival_predictor R2 (三章反馈) + market_death_detector D2 (系统无反应)
# 检测第3章是否有外部人群反应, 以及系统触发后是否有反应

EXTERNAL_FEEDBACK_RE = re.compile(
    r"围观|围住|人群|众人|路人|旁观|"
    r"评论|弹幕|热搜|热议|微博|朋友圈|短视频|"
    r"震惊|哗然|沸腾|炸锅|喧哗|骚动|议论纷纷|"
    r"记者|媒体|新闻|报道|采访|直播|摄像头|"
    r"全网|网络|网友|粉丝|黑粉|水军"
)

SYSTEM_TRIGGER_RE = re.compile(
    r"系统|面板|属性|技能|升级|进化|"
    r"叮|恭喜|获得|解锁|触发|激活|"
    r"经验值|等级提升|突破|进阶"
)


def check_market_feedback(chapters: list[str]) -> Golden3Dimension:
    """G6: 市场反馈 — 第3章是否有外部人群反应。

    检测项:
      - 第3章外部反馈信号 (围观/评论/热搜/弹幕)
      - 系统触发后是否有人群反应 (防止"系统无反应"死亡结构)
    """
    dim = Golden3Dimension(
        dimension="G6",
        name="市场反馈",
        threshold=5.0,
    )

    if not chapters or _count_chinese("".join(chapters)) < 500:
        dim.score = 3.0
        dim.issues.append("前3章总文本过短")
        dim.passed = dim.score >= dim.threshold
        return dim

    score = 5.0

    # 1. 第3章外部反馈
    ch3 = chapters[2] if len(chapters) >= 3 else ""
    if ch3:
        feedback_hits = EXTERNAL_FEEDBACK_RE.findall(ch3)
        dim.details["ch3反馈信号数"] = len(feedback_hits)

        if len(feedback_hits) >= 2:
            score += 3.0
            dim.details["ch3反馈"] = "丰富"
        elif len(feedback_hits) >= 1:
            score += 1.5
            dim.details["ch3反馈"] = "有"
        else:
            score -= 2.0
            dim.issues.append("第3章无外部人群反应 (围观/评论/热搜/弹幕)")
            dim.suggestions.append("建议: 第3章安排外部反馈 (围观震惊/弹幕刷屏/热搜炸裂), 避免主角自嗨")
    else:
        dim.issues.append("无第3章文本, 无法检测市场反馈")

    # 2. 系统触发后是否有反应 (D2 死亡结构检测)
    system_chapter = None
    for i, ch in enumerate(chapters):
        if SYSTEM_TRIGGER_RE.search(ch):
            system_chapter = i
            break

    if system_chapter is not None:
        has_reaction = False
        for i in range(system_chapter, len(chapters)):
            if EXTERNAL_FEEDBACK_RE.search(chapters[i]):
                has_reaction = True
                break

        if has_reaction:
            score += 1.0
            dim.details["系统反应"] = "系统触发后有人群反应"
        else:
            score -= 2.0
            dim.issues.append(f"系统在第{system_chapter + 1}章触发后无人群反应 (市场死亡结构)")
            dim.suggestions.append("建议: 系统触发后必须有人群反应, 读者需要看到世界的反馈")

    score = max(0, min(10, score))
    dim.score = round(score, 1)
    dim.passed = dim.score >= dim.threshold
    return dim


# ── G7: 关系绑定检测 (v8.8) ──
# 来源: survival_predictor R5 (强关系绑定)
# 检测是否有强关系绑定 (前任/清冷/全网/恋综/综艺等短剧化冲突点)

RELATIONSHIP_KEYWORDS = [
    "前任", "清冷", "全网", "爆火", "恋综", "综艺",
    "军婚", "空间", "虐渣", "闺蜜", "宿敌", "青梅",
    "背叛", "复仇", "打脸", "热议", "热搜", "弹幕",
    "围观", "评论", "直播",
]


def check_relationship_binding(
    chapters: list[str],
    title: str = "",
    tags: list[str] | None = None,
) -> Golden3Dimension:
    """G7: 关系绑定 — 是否有强关系绑定 (短剧化冲突点)。

    检测项:
      - 书名/标签中的关系绑定关键词
      - 前2章正文中的关系绑定关键词
    """
    dim = Golden3Dimension(
        dimension="G7",
        name="关系绑定",
        threshold=5.0,
    )

    tags = tags or []
    combined = title + " " + " ".join(tags)
    ch_text = "".join(chapters[:2]) if len(chapters) >= 2 else "".join(chapters)
    all_text = combined + " " + ch_text

    hits = sum(1 for kw in RELATIONSHIP_KEYWORDS if kw in all_text)
    dim.details["关系绑定词数"] = hits

    # 书名/标签中的绑定 (权重更高)
    title_hits = sum(1 for kw in RELATIONSHIP_KEYWORDS if kw in combined)
    dim.details["书名标签绑定"] = title_hits

    if hits >= 3:
        score = 8.0
        dim.details["绑定强度"] = "强"
    elif hits >= 2:
        score = 6.5
        dim.details["绑定强度"] = "中"
    elif hits >= 1:
        score = 5.0
        dim.details["绑定强度"] = "弱"
    else:
        score = 3.0
        dim.issues.append("无强关系绑定 (前任/清冷/全网/恋综/综艺等)")
        dim.suggestions.append("建议: 加入强关系绑定提升短剧化冲突, 如前任/清冷人设/全网关注")

    if title_hits >= 1:
        score += 1.0
        dim.details["书名绑定"] = "已检测到"

    score = max(0, min(10, score))
    dim.score = round(score, 1)
    dim.passed = dim.score >= dim.threshold
    return dim


# ── G8: 预期兑现检测 (v3, 建议文件"书名与正文的预期管理"落地) ──

# 书名/标签高频关键词 → 前3章应该出现的对应内容信号
PROMISE_SIGNAL_MAP = {
    "重生": [r'重生|醒来|回到|再一次|上一世|前世'],
    "穿越": [r'穿越|异世界|醒来|不同|另一个世界'],
    "系统": [r'系统|面板|任务|奖励|叮|绑定'],
    "修仙": [r'修炼|灵气|境界|筑基|金丹|元婴'],
    "末日": [r'末日|丧尸|变异|废墟|末世|灾难'],
    "赘婿": [r'赘婿|入赘|岳父|岳母|妻子|上门'],
    "战神": [r'战神|将军|兵王|退伍|军团|战场'],
    "都市": [r'都市|城市|公司|总裁|白领|街道'],
    "悬疑": [r'案件|凶杀|侦探|线索|推理|真相'],
    "无限流": [r'副本|规则|任务|通关|玩家|无限'],
    "快穿": [r'世界|任务|穿越|快穿|系统|主角'],
    "高武": [r'武道|灵力|武者|武馆|功法'],
    "异能": [r'异能|超能力|觉醒|变异|能力者'],
    "直播": [r'直播|弹幕|观众|打赏|主播'],
    "年代": [r'年代|七十|八十|六十|知青|供销社'],
}

# 书名/标签关键词提取 (去掉常见修饰词后)
_MODIFIER_WORDS = {'之', '的', '和', '与', '在', '了', '我', '他', '她', '最', '大', '小', '新', '老'}


def check_promise_fulfillment(
    chapters: list[str],
    title: str = "",
    tags: list[str] | None = None,
) -> Golden3Dimension:
    """G8: 预期兑现 — 书名/标签中的关键词在前3章是否有对应内容。

    检测项:
      - 从书名/标签提取关键词 (如"重生之XX" → "重生")
      - 检查前3章正文中是否有对应信号词
      - 兑现率 = 命中关键词 / 总关键词
    """
    dim = Golden3Dimension(
        dimension="G8",
        name="预期兑现",
        threshold=6.0,
    )

    tags = tags or []
    combined = title + " " + " ".join(tags)
    ch_text = "".join(chapters)

    # 提取书名/标签中的承诺关键词
    promised_keywords = []
    for keyword, patterns in PROMISE_SIGNAL_MAP.items():
        if keyword in combined:
            promised_keywords.append(keyword)

    dim.details["书名标签关键词"] = promised_keywords

    if not promised_keywords:
        # 书名/标签无明确题材关键词, 无法检测预期兑现
        dim.score = 6.0
        dim.details["说明"] = "书名/标签无明确题材关键词"
        dim.passed = True
        return dim

    # 检查前3章正文中是否有对应信号词
    fulfilled = []
    unfulfilled = []
    for keyword in promised_keywords:
        patterns = PROMISE_SIGNAL_MAP[keyword]
        found = any(re.search(p, ch_text) for p in patterns)
        if found:
            fulfilled.append(keyword)
        else:
            unfulfilled.append(keyword)

    fulfillment_rate = len(fulfilled) / len(promised_keywords) if promised_keywords else 0.0
    dim.details["兑现率"] = round(fulfillment_rate, 2)
    dim.details["已兑现"] = fulfilled
    dim.details["未兑现"] = unfulfilled

    if fulfillment_rate >= 1.0:
        score = 9.0
    elif fulfillment_rate >= 0.66:
        score = 7.0
    elif fulfillment_rate >= 0.33:
        score = 4.5
        dim.issues.append(f"部分预期未兑现: {', '.join(unfulfilled)} — 读者因书名/标签入坑但前3章找不到对应内容")
        dim.suggestions.append(f"建议: 在前3章加入与 {', '.join(unfulfilled)} 相关的场景或设定")
    else:
        score = 2.0
        dim.issues.append(f"预期严重未兑现: {', '.join(unfulfilled)} — 书名/标签与正文脱节")
        dim.suggestions.append("建议: 前3章必须兑现书名/标签的核心承诺, 否则读者会差评弃书")

    dim.score = round(max(0, min(10, score)), 1)
    dim.passed = dim.score >= dim.threshold
    return dim


# ── G9: 主角保护 (虐主检测, v4) ──

# 虐待信号: 主角在开篇遭受的负面事件
ABUSE_SIGNALS = {
    "身体伤害": [
        re.compile(r'被打|被揍|重伤|吐血|残废|断腿|断手|瞎眼'),
        re.compile(r'鞭打|烙印|酷刑|折磨|虐待'),
    ],
    "精神羞辱": [
        re.compile(r'羞辱|嘲讽|嘲笑|鄙视|蔑视|践踏'),
        re.compile(r'退婚|休妻|逐出师门|废除修为|剥夺身份'),
    ],
    "社会性死亡": [
        re.compile(r'全网黑|人人喊打|众叛亲离|身败名裂'),
        re.compile(r'背锅|陷害|冤枉|污蔑|背刺'),
    ],
    "资源剥夺": [
        re.compile(r'被抢|被夺|失去|剥夺|没收|充公'),
        re.compile(r'破产|负债|穷困潦倒|一无所有'),
    ],
    "关系破碎": [
        re.compile(r'背叛|欺骗|抛弃|离开|死亡|牺牲'),
        re.compile(r'分手|离婚|决裂|反目|成仇'),
    ],
}

# 能力信号: 主角展示金手指/实力, 对冲虐主分数
POWER_SIGNALS = {
    "金手指激活": [
        re.compile(r'系统.*激活|获得.*能力|觉醒.*天赋|开启.*面板'),
        re.compile(r'重生.*记忆|穿越.*知识|获得.*传承|得到.*宝物'),
    ],
    "能力展示": [
        re.compile(r'一拳|一剑|一招|一眼|一掌'),
        re.compile(r'秒杀|碾压|击败|战胜|压制'),
        re.compile(r'震惊|骇然|不可思议|怎么可能'),
    ],
    "身份揭示": [
        re.compile(r'原来.*是|竟然.*是|没想到.*是'),
        re.compile(r'隐藏.*身份|真实.*身份|背后.*势力'),
    ],
}


def check_protagonist_abuse(chapters: list[str]) -> Golden3Dimension:
    """G9: 主角保护 — 检测开篇虐主程度。

    核心假设: 番茄首秀存活作品中, 前3章主角负面事件密度不应过高,
    且金手指/能力展示应尽早出现 (第1章或第2章)。

    评分逻辑:
      - 每个虐待信号 +1 分 (abuse_score)
      - 每个能力信号 -2 分 (power_score, 对冲)
      - 净分 = abuse_score - power_score * 2
      - 净分 > 5 且 power_score < 2 → 严重虐主 (低分)
      - 净分 3-5 且 power_score < 2 → 轻度虐主
      - 金手指第1章未出现 → 额外扣分
    """
    dim = Golden3Dimension(
        dimension="G9",
        name="主角保护",
        threshold=6.0,
    )

    ch_text = "".join(chapters)
    chinese = _count_chinese(ch_text)
    if chinese < 100:
        dim.score = 2.0
        dim.issues.append("文本过短, 无法有效分析虐主程度")
        dim.passed = dim.score >= dim.threshold
        return dim

    abuse_score = 0
    power_score = 0
    abuse_details: list[dict] = []
    power_details: list[dict] = []

    for i, ch in enumerate(chapters[:3]):
        if not ch:
            continue
        for category, patterns in ABUSE_SIGNALS.items():
            for pat in patterns:
                for m in pat.finditer(ch):
                    abuse_score += 1
                    abuse_details.append({
                        "chapter": i + 1,
                        "category": category,
                        "text": m.group(),
                    })
        for category, patterns in POWER_SIGNALS.items():
            for pat in patterns:
                for m in pat.finditer(ch):
                    power_score += 1
                    power_details.append({
                        "chapter": i + 1,
                        "category": category,
                        "text": m.group(),
                    })

    net_score = abuse_score - power_score * 2

    # 金手指延迟检测
    golden_finger_chapter = None
    for i, ch in enumerate(chapters[:3]):
        if not ch:
            continue
        if any(pat.search(ch) for patterns in POWER_SIGNALS.values() for pat in patterns):
            golden_finger_chapter = i + 1
            break

    dim.details["虐待信号数"] = abuse_score
    dim.details["能力信号数"] = power_score
    dim.details["净虐主分"] = net_score
    dim.details["金手指章节"] = golden_finger_chapter or "未出现"
    dim.details["虐待分类"] = {}
    for d in abuse_details:
        cat = d["category"]
        dim.details["虐待分类"][cat] = dim.details["虐待分类"].get(cat, 0) + 1

    # 评分 (0-10, 越高越好)
    if net_score > 5 or (net_score > 3 and not golden_finger_chapter):
        score = 2.0  # 严重虐主
        dim.issues.append(f"严重虐主: 净虐主分 {net_score} (虐待 {abuse_score} vs 能力 {power_score})")
        dim.suggestions.append(
            "建议: 将至少2个负面事件转化为'表面吃亏实则收获'，"
            "如被退婚但激活系统、被打但觉醒血脉"
        )
    elif net_score > 3 or not golden_finger_chapter:
        score = 4.5  # 轻度虐主
        if net_score > 3:
            dim.issues.append(f"轻度虐主: 净虐主分 {net_score}")
            dim.suggestions.append("建议: 增加主角的反击/能力展示场景，平衡负面事件")
        if not golden_finger_chapter:
            dim.issues.append("金手指延迟: 前3章未出现能力展示")
            dim.suggestions.append("建议: 第1章就让主角获得/展示某种能力（哪怕很弱）")
    elif net_score > 0:
        score = 7.0  # 有虐有爽, 基本平衡
        dim.issues.append(f"虐爽平衡: 净虐主分 {net_score} (有负面但有对冲)")
    else:
        score = 9.0  # 无虐主或纯爽文

    # 金手指延迟额外扣分
    if golden_finger_chapter and golden_finger_chapter == 1:
        score = min(score + 1.0, 10.0)  # 第1章就有金手指, 加分
    elif not golden_finger_chapter:
        score = max(score - 1.0, 0.0)  # 无金手指, 额外扣分

    dim.score = round(score, 1)
    dim.passed = dim.score >= dim.threshold
    return dim


# ── 题材趋势 (v8.8 元数据, 非评分维度) ──

HOT_GENRES_2026: set[str] = {
    "都市", "脑洞都市", "系统流", "都市脑洞",
    "年代重生", "重生", "战神", "赘婿",
    "快穿", "大女主", "悬疑", "无限流",
    "高武", "异能", "历史", "穿越",
    "同人", "模拟器", "直播", "灵异",
}


def _check_genre_trend(genre: str) -> str:
    """检测题材趋势, 返回 hot/normal/declining。"""
    if not genre:
        return "unknown"
    if genre in HOT_GENRES_2026:
        return "hot"
    for hot in HOT_GENRES_2026:
        if hot in genre or genre in hot:
            return "hot"
    return "normal"


# ── 主入口 ──

def analyze_golden3(
    chapters: list[str],
    canon: dict | None = None,
    benchmarks: dict | None = None,
    genre: str = "",
    title: str = "",
    tags: list[str] | None = None,
) -> Golden3Report:
    """执行黄金三章五维分析。

    Args:
    chapters: 前3章正文列表 (至少1章, 建议3章)
      canon: 可选 Canon 数据 (characters, timeline, foreshadowing, novel_outline)
      benchmarks: 可选 爆款基准数据 (用于对比分析)
      genre: 可选 题材标签 (用于题材趋势元数据)
      title: 可选 书名 (用于关系绑定检测)
      tags: 可选 标签列表 (用于关系绑定检测)

    Returns:
        Golden3Report 包含7个维度的评分和建议
    """
    report = Golden3Report()

    if not chapters:
        report.summary = "无章节文本, 无法分析"
        return report

    # 确保至少有3个元素
    while len(chapters) < 3:
        chapters.append("")

    logger.info("开始黄金三章分析 (chapters=%d, canon=%s, benchmarks=%s)",
                len([c for c in chapters if c]),
                "有" if canon else "无",
                "有" if benchmarks else "无")

    # G1: 高能钩子 (仅第1章)
    g1 = check_high_energy_hook(chapters[0])
    report.add(g1)

    # G2: 人设清晰度 (前3章)
    g2 = check_character_clarity(chapters, canon)
    report.add(g2)

    # G3: 核心矛盾 (前3章)
    g3 = check_core_conflict(chapters, canon)
    report.add(g3)

    # G4: 铺垫密度 (前3章)
    g4 = check_foreshadowing_density(chapters, canon)
    report.add(g4)

    # G5: 情绪曲线 (前3章)
    g5 = check_emotional_curve(chapters)
    report.add(g5)

    # G6: 市场反馈 (前3章, v8.8)
    g6 = check_market_feedback(chapters)
    report.add(g6)

    # G7: 关系绑定 (前3章 + 书名/标签, v8.8)
    g7 = check_relationship_binding(chapters, title, tags or [])
    report.add(g7)

    # G8: 预期兑现 (前3章 vs 书名/标签, v3)
    g8 = check_promise_fulfillment(chapters, title, tags or [])
    report.add(g8)

    # G9: 主角保护 (前3章, v4)
    g9 = check_protagonist_abuse(chapters)
    report.add(g9)

    # v8.8: 题材趋势元数据
    report.genre_trend = _check_genre_trend(genre)

    # 加权总分
    total = 0.0
    for dim in report.dimensions:
        total += dim.score * DIM_WEIGHTS.get(dim.dimension, 0.2)
    report.total_score = round(total, 1)

    # 综合评级
    if report.total_score >= 9: report.grade = "S"
    elif report.total_score >= 8: report.grade = "A"
    elif report.total_score >= 7: report.grade = "B"
    elif report.total_score >= 6: report.grade = "C"
    elif report.total_score >= 4: report.grade = "D"
    else: report.grade = "F"

    # 基准对比
    if benchmarks:
        report.benchmark_comparison = _compare_with_benchmarks(report, benchmarks)

    # 生成摘要
    report.summary = _generate_summary(report)

    logger.info("黄金三章分析完成: 总分 %.1f (%s), 通过 %d/%d",
                report.total_score, report.grade,
                report.passed_count, report.passed_count + report.failed_count)

    return report


def _compare_with_benchmarks(report: Golden3Report, benchmarks: dict) -> dict:
    """与爆款基准数据对比。"""
    comparison = {}

    bench_scores = benchmarks.get("golden3_scores", {})
    if not bench_scores:
        return comparison

    for dim in report.dimensions:
        bench_score = bench_scores.get(dim.dimension)
        if bench_score is not None:
            gap = round(dim.score - bench_score, 1)
            comparison[dim.dimension] = {
                "author": dim.score,
                "benchmark": bench_score,
                "gap": gap,
                "status": "达标" if gap >= 0 else "差距",
            }

    bench_total = benchmarks.get("total_score")
    if bench_total:
        comparison["total"] = {
            "author": report.total_score,
            "benchmark": bench_total,
            "gap": round(report.total_score - bench_total, 1),
        }

    return comparison


def _generate_summary(report: Golden3Report) -> str:
    """生成可读的分析摘要。"""
    lines = [
        f"\n{'=' * 60}",
        "  黄金三章分析报告 (Golden3 Analyzer)",
        f"{'=' * 60}",
        f"  综合评分: {report.total_score:.1f}/10  评级: {report.grade}",
        f"  通过: {report.passed_count}/7  不通过: {report.failed_count}/7",
        f"{'─' * 60}",
    ]

    for dim in report.dimensions:
        status = "[PASS]" if dim.passed else "[FAIL]"
        lines.append(f"  {status} {dim.dimension} {dim.name}: {dim.score:.1f}/10 ({dim.grade})")
        if dim.issues:
            for issue in dim.issues:
                lines.append(f"      [!] {issue}")
        if dim.suggestions:
            for sugg in dim.suggestions:
                lines.append(f"      -> {sugg}")

    if report.benchmark_comparison:
        lines.append(f"{'─' * 60}")
        lines.append("  爆款对比:")
        for key, val in report.benchmark_comparison.items():
            if isinstance(val, dict):
                lines.append(f"    {key}: 作者 {val.get('author', '?')} vs 爆款 {val.get('benchmark', '?')} (差距 {val.get('gap', '?')})")

    if report.genre_trend:
        lines.append(f"{'─' * 60}")
        trend_label = {"hot": "热门", "normal": "普通", "declining": "下行", "unknown": "未知"}
        lines.append(f"  题材趋势: {trend_label.get(report.genre_trend, report.genre_trend)}")

    lines.append(f"{'=' * 60}")
    return "\n".join(lines)


# ── S3 集成入口 ──

def golden3_as_s3_precheck(
    chapters: list[str],
    canon: dict | None = None,
    genre: str = "",
    title: str = "",
    tags: list[str] | None = None,
) -> dict:
    """作为 S3 评审前置检查, 返回结构化结果供 S3 流程使用。

    Returns:
        dict 包含:
          - should_block: bool — 是否建议阻断 S3 评审 (G1/G3 严重不达标时)
          - block_reasons: list[str]
          - weighted_score: float
          - dimension_scores: dict[str, float]
          - top_issues: list[str] — 按严重度排序的问题
          - genre_trend: str — 题材趋势 (hot/normal/declining)
    """
    report = analyze_golden3(chapters, canon, genre=genre, title=title, tags=tags)

    # 判断是否阻断
    block_reasons = []
    g1 = report.get("G1")
    g3 = report.get("G3")

    if g1 and g1.score < 4.0:
        block_reasons.append(f"G1高能钩子严重不达标 ({g1.score:.1f}/10): 前3章无法吸引读者")
    if g3 and g3.score < 4.0:
        block_reasons.append(f"G3核心矛盾严重不达标 ({g3.score:.1f}/10): 缺乏故事驱动力")

    # 收集 Top 问题
    all_issues = []
    for dim in report.dimensions:
        for issue in dim.issues:
            severity = "critical" if dim.score < 4 else "warning" if dim.score < dim.threshold else "info"
            all_issues.append((severity, dim.dimension, issue))

    # 排序: critical > warning > info
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    all_issues.sort(key=lambda x: severity_order.get(x[0], 3))
    top_issues = [f"[{s}] {d}: {i}" for s, d, i in all_issues[:5]]

    return {
        "should_block": len(block_reasons) > 0,
        "block_reasons": block_reasons,
        "weighted_score": report.total_score,
        "grade": report.grade,
        "dimension_scores": {dim.dimension: dim.score for dim in report.dimensions},
        "top_issues": top_issues,
        "genre_trend": report.genre_trend,
        "report": report,
    }
