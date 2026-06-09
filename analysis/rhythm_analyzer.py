#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
rhythm_analyzer v3 — 三级指标体系 (Macro/Meso/Micro)
方法: 规则统计 + 马良写作4类钩子 + readability-cn文笔分析 + LLM-as-Judge验证
输入: data/novels/**/*.txt
输出: data/rhythm_*.csv (每本逐章节奏数据)
参考: ACL2025 Novel Benchmark (三级框架) + 马良写作(钩子+爽点递进) + 笔灵AI(拆书三件套)
"""
import re
import csv
import time
import urllib.request
import json
import yaml
from pathlib import Path

# P0: bridge to writing_instructions for per-chapter diagnostics
try:
    from analysis.writing_instructions import generate_chapter_instructions
    _instructions_available = True
except ImportError:
    _instructions_available = False

PROJECT_ROOT = Path(__file__).resolve().parent.parent
NOVELS_DIR = PROJECT_ROOT / "data" / "raw" / "novels"
RHYTHM_DIR = PROJECT_ROOT / "data" / "processed" / "rhythm"
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def _get_llm_port():
    """Read LLM port from config.yaml. Falls back to 8000."""
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f) or {}
            return cfg.get("analysis", {}).get("llm_port", 8000)
    except Exception:
        pass
    return 8000


LLAMA_PORT = _get_llm_port()
LLAMA_BASE = f"http://127.0.0.1:{LLAMA_PORT}"

# ── Rule-based keyword dictionaries (zero LLM cost) ──
# Sources: 网文俱乐部 爽点分类 + 知乎18种爽点 + Climactic Chapter Recognition (Applied Sciences)
# v4: 外部评审驱动扩充 — 新增羁绊/认知/牺牲三类隐式爽点 + 4类非战斗冲突

# ── 显式爽点 (传统打脸升级流，v3 保留) ──
PLEASURE_FACE_SLAP = re.compile(r"打脸|嘲讽|看不起|小瞧|轻视|不屑|冷笑|嗤笑|凭什么|你也配|就这|惊呆|震惊|瞪大|倒吸|不可思议|怎么可能|不可能！|傻眼|目瞪口呆|鸦雀无声")
PLEASURE_LEVEL_UP = re.compile(r"突破|晋级|进阶|升级|渡劫|突破瓶颈|实力暴涨|修为大增|顿悟|觉醒|解锁|开启|新生|蜕变|脱胎换骨")
PLEASURE_CRUSH = re.compile(r"碾压|秒杀|横扫|秒败|一击|一招|摧枯拉朽|不堪一击|螳臂当车|随手|轻易|不费吹灰|挥手之间")
PLEASURE_COMEBACK = re.compile(r"绝地|绝境|反杀|逆转|翻盘|反败为胜|逆转乾坤|置之死地|破而后立|柳暗花明|峰回路转|起死回生|绝处逢生")
PLEASURE_HIDDEN = re.compile(r"扮猪|藏拙|隐藏实力|低调|显露|暴露|亮出|底牌|真正实力|终于出手|不再隐藏")
PLEASURE_GENERAL = re.compile(r"哈哈|爽|痛快|舒服|牛逼|厉害|强[^调化学]|很强|极强|无敌|逆天|恐怖如斯|骇然|惊呼|赞叹|佩服|崇拜|仰望|敬畏")

# ── v4 新增: 隐式爽点 (智斗流/羁绊流专属，外部评审驱动: 评审均指出覆盖率 <60%) ──
# 来源: 3份外部AI评审收敛结论 + 马良写作情感节奏理论 + 网文俱乐部羁绊流方法论
PLEASURE_BOND = re.compile(
    r"羁绊|守护|为你|替我|并肩|一起|等我|别走|回来|留下|陪你|跟你|"
    r"我会保护|我答应|不放手|伸出手|碰了碰|贴着|靠着|"  # v8: 移除"挡在|护在|扶住|接住"(战斗重叠)
    r"第一[个次位]|唯一|只有你|只要你|除了你|不会让|不许|不行|不准"
)
PLEASURE_COGNITIVE = re.compile(
    r"原来如此|明白了|懂了|终于知道|恍然大悟|识破|看穿|洞察|"
    r"算到|预判|提前|早[就已]|那一瞬|猛然意识|忽然想到|突然想起|"
    r"面板弹出|推演显示|模拟得出|演算|第一条规则|从未见过"
)
PLEASURE_SACRIFICE = re.compile(
    r"燃[烧尽]|耗尽|透支|本源|代价|交换|换[取来]|付出|承受|扛住|撑住|"
    r"拼了|不管[了不]|豁出去|不计代价|不重要|没关系|值得|心甘情愿"
)
# 生理反应词 — 情绪张力的信号 (评审建议: "瞳孔骤缩/呼吸一滞" 等是情绪强度的强烈信号)
PHYSIO_REACTION = re.compile(
    r"瞳孔[骤微]?缩|呼吸[一戛]?滞|心头[一]?[震颤]|脊背发?凉|头皮发麻|"
    r"血液[仿凝]|浑身[一震]|心头[一]紧|掌心[出渗]|指尖[微发]颤|"
    r"眼眶[一微]?红|鼻子[一]?酸|喉[咙头][一发]?紧|说不出话|愣[在住]了|"
    r"沉默[了很]?久|久久[没未不]|一言不发|一动不动|半晌"
)

# ── v4 新增: 4类非战斗冲突 (外部评审: 原冲突库对智斗流低估40-60%) ──
# 来源: 心理博弈/道德困境/环境对抗/社会冲突 — 3份评审收敛建议
CONFLICT_PSYCHOLOGICAL = re.compile(
    r"试探|算计|博弈|陷阱|圈套|局[中里]|将计就计|反将|识破|"
    r"怀疑|猜忌|戒备|提防|警觉|怀疑|不信任|动摇|犹豫|迟疑|"
    r"他知[道晓]|她知[道晓]|没[说有]穿|假装|装作|掩饰|隐藏"
)
CONFLICT_MORAL = re.compile(
    r"抉择|选择|两条路|牺牲谁|换谁|保谁|救[谁不]|放弃|舍弃|"
    r"背叛|出卖|欺骗|隐瞒|瞒着|对不起|亏欠|负罪|愧疚|忏悔|"
    r"底线|原则|不能|不该|不可以|越界|突破底线|做不到"
)
CONFLICT_ENVIRONMENT = re.compile(
    r"饥饿|饥渴|干渴|脱水|辐射|污染|毒气|窒息|缺氧|"
    r"崩塌|坍塌|陷落|废墟|残骸|瓦砾|断壁|"
    r"极寒|酷暑|严寒|灼热|暴晒|酸雨|变异|异化|侵蚀|吞噬"
)
CONFLICT_SOCIAL = re.compile(
    r"规则|秩序|权力|夺权|争权|上位|夺位|取而代之|"
    r"质疑|反对|排斥|驱逐|孤立|排挤|针对|"
    r"凭什么你|谁同意的|谁允许|规矩|规定|制度|"
    r"领头|首领|领袖|话语权|说了算|一票否决"
)

# ── 合并冲突正则 (v4: 战斗 + 心理 + 道德 + 环境 + 社会) ──
CONFLICT_KW_ALL = [
    re.compile(
        r"你敢|休想|去死|找死|不可能！|我不信|凭什么|战斗|杀|轰|爆|碎|血|伤|敌|战|斗|"
        r"杀意|杀气|怒吼|暴怒|杀机|出手|进攻|攻击|反击|反攻|偷袭|暗算|围杀|刺杀|击杀|斩杀|"
        r"一刀|一剑|一拳|一掌|一枪|武器|兵器|法宝|神通|禁术|秘术|底牌|拼命|拼死|搏命|殊死|"
        r"血战|激战|苦战|酣战|大战|对决|决斗|生死|致命|致命一击|决一死战|不死不休"
    ),
    CONFLICT_PSYCHOLOGICAL,
    CONFLICT_MORAL,
    CONFLICT_ENVIRONMENT,
    CONFLICT_SOCIAL,
]

# Dialogue: Chinese quotes + Western quotes + role:format
DIALOGUE_PAT = re.compile(
    r'[「『"\u201c\u300c\u300e](.+?)[」』"\u201d\u300d\u300f]|'
    r'[^\n]*[:：]["\u201c].+["\u201d]'
)
# Exclamation density
EXCLAM_PAT = re.compile(r'！|!|\?|？')  # include ? for suspense/tension

# Emotion arc: positive vs negative word ratio
NEGATIVE = re.compile(
    r"哭|泪|死|痛|绝望|恐惧|害怕|逃|躲|惨|败|输|危险|致命|"
    r"无奈|苦涩|悲哀|悲凉|凄凉|孤寂|苍凉|毁灭|湮灭|陨落|逝去|"
    r"悲伤|悲痛|心碎|心寒|心凉|心如死灰|万念俱灰"
)

# Chapter-ending hook words (cliffhanger indicators)
CLIFFHANGER = re.compile(
    r"就在这时|突然|忽然|骤然|猛然|只见|赫然|不料|竟|竟然|居然|"
    r"下一刻|下一秒|紧接着|与此同时|眼下|眼下这一幕|"
    r"未完待续|欲知后事|预知后事",
)

# Paragraph break detection
PARA_SPLIT = re.compile(r'\n\s*\n')


def _parse_cn_num(s):
    """Parse Chinese numerals like 一百二十三 -> 123. Returns int."""
    if not s: return 0
    units = {"十": 10, "百": 100, "千": 1000, "万": 10000}
    digits = {"零":0, "一":1, "二":2, "三":3, "四":4, "五":5, "六":6, "七":7, "八":8, "九":9,
              "两":2}
    # Handle pure digits
    try: return int(s)
    except: pass
    result = 0
    current = 0
    for ch in s:
        if ch in digits:
            current = digits[ch]
        elif ch in units:
            unit = units[ch]
            current = (current or 1) * unit
            result += current
            current = 0
    result += current
    return result if result > 0 else len(s)  # fallback


def extract_chapters(filepath):
    """Extract chapters. Supports: 第X章 / 序章+章X / 纯数字分章.
    Returns [{num, title, text, wc, paragraphs}]"""
    text = None
    for enc in ["utf-8", "gbk", "utf-16-le", "utf-16-be"]:
        try:
            text = Path(filepath).read_text(encoding=enc)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    if text is None:
        raise ValueError(f"Cannot decode {filepath}")

    cn_nums = r"[一二三四五六七八九十百千零\d]+"

    # Try standard 第X章 format first (95% of novels)
    pattern1 = r"(第" + cn_nums + r"章\s*[^\n]*)"
    parts = re.split(pattern1, text)
    if len(parts) >= 5:
        return _build_chapters(parts)
    # Fallback: mixed format (序章 + 章X, e.g. 狩魔手记)
    pattern2 = r"(序章\s*[^\n]*|章" + cn_nums + r"\s*[^\n]*)"
    parts = re.split(pattern2, text)
    if len(parts) >= 5:
        return _build_chapters(parts)
    # Fallback: standalone number headers (e.g. 限制级末日症候)
    # Pattern: "数字 标题" — number + space + title
    pattern3 = r"(^[ \t]*\d{1,4}[ \t]+[^\d][^\n]*)"
    parts = re.split(pattern3, text, flags=re.MULTILINE)
    if len(parts) >= 5:
        return _build_chapters(parts)
    # Fallback: bare number-only lines — P0: validate with surrounding context
    pattern4 = r"(^[ \t]*\d{1,4}[ \t]*$)"
    candidates = list(re.finditer(pattern4, text, flags=re.MULTILINE))
    # Filter: reject if surrounding 50-char context looks like data, not chapter header
    valid = []
    for m in candidates:
        line = m.group(0).strip()
        # Reject 4-digit years (1900-2099) or standalone data numbers
        if line.isdigit() and 1900 <= int(line) <= 2099:
            continue
        start, end = m.start(), m.end()
        before = text[max(0, start-50):start].strip()
        after = text[end:min(len(text), end+50)].strip()
        # Must have substantial text (>20 chars) after, indicating chapter body
        if len(after) < 20:
            continue
        valid.append(m)
    if len(valid) >= 3:  # Need at least 3 chapters to be credible
        parts = []
        last = 0
        for m in valid:
            parts.append(text[last:m.start()])
            parts.append(m.group(0))
            last = m.end()
        parts.append(text[last:])
        return _build_chapters(parts)

    # Fallback: bare number-only lines
    pattern4 = r"(^[ \t]*\d{1,4}[ \t]*$)"
    parts = re.split(pattern4, text, flags=re.MULTILINE)
    if len(parts) >= 5:
        return _build_chapters(parts)
    # Nothing worked
    return []


def _build_chapters(parts):
    """Convert re.split() parts into chapter dicts."""
    chapters = []
    for i in range(1, len(parts), 2):
        header = parts[i].strip()
        body = parts[i+1].strip() if i+1 < len(parts) else ""
        pure_text = body.replace("\n", "").replace(" ", "")
        if len(pure_text) < 50:
            continue

        ch_num = 0
        for regex in [
            r"第([一二三四五六七八九十百千零\d]+)章",
            r"序章",
            r"章([一二三四五六七八九十百千零\d]+)",
            r"^\s*(\d{1,4})\s",   # "数字 标题" format
            r"^\s*(\d{1,4})\s*$",  # bare number header
        ]:
            m = re.search(regex, header)
            if m:
                if "序章" in m.group():
                    ch_num = 0
                else:
                    num_str = m.group(1).strip()
                    try:
                        ch_num = int(num_str)
                    except:
                        ch_num = _parse_cn_num(num_str)
                break

        paragraphs = [p.strip() for p in PARA_SPLIT.split(body) if p.strip()]
        chapters.append({
            "num": ch_num, "title": header, "text": body[:3000],
            "wc": len(pure_text), "para_count": len(paragraphs),
            "raw_body": body,
        })

    # Fix zero-numbered chapters (prologues get sequential numbers)
    offset = 0
    for ch in chapters:
        if ch["num"] == 0:
            offset += 1
            ch["num"] = offset
    return chapters


def rule_analyze(ch):
    """Zero-LLM chapter analysis v4. Returns dict with 20+ metrics.
    v4: 扩充隐式爽点(羁绊/认知/牺牲) + 4类非战斗冲突 + 钩子窗口500字 + 生理反应信号"""
    body = ch["raw_body"]
    wc = ch["wc"]

    # ── Basic metrics ──
    dialogue_chars = sum(len(m.group()) for m in DIALOGUE_PAT.finditer(body))
    dialogue_ratio = dialogue_chars / max(wc, 1)

    excl_count = len(EXCLAM_PAT.findall(body))
    excl_density = excl_count / max(wc, 1) * 100

    # ── Pleasure sub-types (v4: 9 subtypes = 6显式 + 3隐式) ──
    slap_count = len(PLEASURE_FACE_SLAP.findall(body))
    level_count = len(PLEASURE_LEVEL_UP.findall(body))
    crush_count = len(PLEASURE_CRUSH.findall(body))
    comeback_count = len(PLEASURE_COMEBACK.findall(body))
    hidden_count = len(PLEASURE_HIDDEN.findall(body))
    general_count = len(PLEASURE_GENERAL.findall(body))
    bond_count_raw = len(PLEASURE_BOND.findall(body))
    cognitive_count = len(PLEASURE_COGNITIVE.findall(body))
    sacrifice_count = len(PLEASURE_SACRIFICE.findall(body))
    physio_count = len(PHYSIO_REACTION.findall(body))

    # v5: 羁绊消歧 — 上下文30字共现约束 (评审: "守护仓库"≠羁绊)
    bond_count = 0
    for m in PLEASURE_BOND.finditer(body):
        start = max(0, m.start() - 30)
        end = min(len(body), m.end() + 30)
        ctx = body[start:end]
        # 需共现: 人称代词 / 情感词（v8: 移除硬编码主角名，仅保留通用共现词）
        if re.search(r"你|我|他|她|眼中|心里|轻声|沉默|握住|凝视", ctx):
            bond_count += 1

    # ── v8: pos_density按r加权聚合 (CCMMW方法, MDPI Symmetry 2023) ──
    # 依据 calibrate_v2 特征重要性: max(0, r) 作为权重, 负相关/弱相关自动衰减
    # r值: slap=0.096 level=0.086 crush=0.300 comeback=0.178 hidden=0.108(N/A,估算)
    #       bond=0.155 cognitive=0.017 sacrifice=0.053 physio=0.179 general=0.108(估算)
    weighted_pleasure = (
        slap_count * 0.096 + level_count * 0.086 + crush_count * 0.300 +
        comeback_count * 0.178 + hidden_count * 0.108 + general_count * 0.108 +
        bond_count * 0.155 + cognitive_count * 0.017 + sacrifice_count * 0.0 +  # r=-0.13→0
        physio_count * 0.179
    )
    total_pleasure = weighted_pleasure  # v8: 替代等权相加
    pos_density = total_pleasure / max(wc, 1) * 100

    # Dominant pleasure sub-type (v4: include new subtypes)
    subtypes = [("打脸", slap_count), ("突破", level_count), ("碾压", crush_count),
                ("绝地反击", comeback_count), ("扮猪吃虎", hidden_count),
                ("羁绊", bond_count), ("认知突破", cognitive_count),
                ("牺牲", sacrifice_count)]
    dominant_sub = max(subtypes, key=lambda x: x[1])

    # ── Negative emotion density ──
    neg_count = len(NEGATIVE.findall(body))
    neg_density = neg_count / max(wc, 1) * 100

    # ── v4: 5类冲突合并 (战斗 + 心理 + 道德 + 环境 + 社会) ──
    conflict_count = sum(len(kw.findall(body)) for kw in CONFLICT_KW_ALL)
    conflict_density = conflict_count / max(wc, 1) * 100

    # ── Cliffhanger hook density (per 1000 chars) ──
    hook_count = len(CLIFFHANGER.findall(body))
    hook_density = hook_count / max(wc/1000, 1)

    # ── v4: Hook type classification (窗口 500字, 评审建议) ──
    ending = body[-500:] if len(body) > 500 else body
    # Paragraph-level structural analysis: last 3 paragraphs
    ending_paras = [p.strip() for p in PARA_SPLIT.split(ending) if p.strip()]
    last_para = ending_paras[-1] if ending_paras else ending
    last2_para = ending_paras[-2] if len(ending_paras) >= 2 else ""
    last3_para = ending_paras[-3] if len(ending_paras) >= 3 else ""

    hook_suspense = bool(re.search(r"竟然|居然|突然出现|不可能|怎么可能|但[是那]|然而|只不过", ending[-300:]))
    # Short para after long para = reversal signal
    hook_reversal_para = (len(last_para) < 30 and len(last2_para) > 80) if last2_para else False
    hook_reversal_sent = bool(re.search(r"([^。！？\n]{5,}。\s*)([^。！？\n]{2,15})$", ending[-400:]))
    hook_reversal = hook_reversal_para or hook_reversal_sent
    hook_emotion = bool(re.search(r"(从[来没]|你[就从没]|再也[不没]|永远|终于|最后[一]?)[^。！？]{3,25}$", ending[-300:]))
    # v4: 信息投放式钩子 — 扩展检测范围
    hook_info_dump = bool(re.search(r"(翻开|打开|看到|发现|显示|弹出|浮现|出现|亮起|闪烁|跳[出动])[^。！？]{3,25}$", ending[-300:]))

    hook_type = "none"
    if hook_suspense:
        hook_type = "悬念式"
    elif hook_emotion:
        hook_type = "情绪炸弹"
    elif hook_reversal:
        hook_type = "反转式"
    elif hook_info_dump:
        hook_type = "信息投放"

    # ── Readability score (AlphaReadabilityChinese method) ──
    sentences = re.split(r'[。！？!?]', body)
    sentence_lengths = [len(s.strip()) for s in sentences if s.strip()]
    avg_sentence_len = sum(sentence_lengths) / max(len(sentence_lengths), 1)
    pure_text = body.replace("\n", "").replace(" ", "")
    unique_chars = len(set(pure_text))
    vocab_diversity = unique_chars / max(len(pure_text), 1)
    readability_score = round(
        min(1.0, (avg_sentence_len / 80) * 0.5 + (1 - vocab_diversity * 10) * 0.3 +
         (abs(avg_sentence_len - 35) / 50) * 0.2), 3)

    # ── v8: Platt Scaling (data-driven from calibrate_v2 100章) ──
    # 公式: LLM = 0.106 * Rule + 2.8 (L341注释中的校准系数)
    # 替代手动 *0.7+1.5, 避免低分压缩 + 偏移失真
    pleasure_raw = (
        pos_density * 2.0 +            # 最强特征 (r=0.445)
        conflict_density * 1.5 +       # 冲突也是爽点信号 (r=0.406)
        excl_density * 0.5 +
        hook_density * 0.5 +
        neg_density * 0.2 +            # v9: 改+ 负面情绪是爽点前置(r=0.241, Catharsis理论)
        physio_count * 2.0 / max(wc/100, 1)  # 生理信号 (r=0.179)
    )
    # v9: 去掉+1.5偏移, 纯比例压缩。待重校准后上Platt
    pleasure_raw = pleasure_raw * 0.7
    pleasure_intensity = round(max(0, min(10, pleasure_raw)), 1)

    if pleasure_intensity >= 6:
        pleasure_type = "climax"
    elif pleasure_intensity >= 4:
        pleasure_type = "major"
    elif pleasure_intensity >= 2:
        pleasure_type = "minor"
    else:
        pleasure_type = "none"

    # ── v4: Conflict level (阈值不变，分母变大后自然需要更多匹配) ──
    if conflict_density > 2.5:
        conflict_level = "high"
    elif conflict_density > 1.0:
        conflict_level = "medium"
    elif conflict_density > 0.3:
        conflict_level = "low"
    else:
        conflict_level = "none"

    # ── v4: Emotion classification (加入羁绊和牺牲信号) ──
    if pos_density > neg_density * 2:
        emotion = "爽快"
    elif conflict_density > 2 and neg_density > pos_density:
        emotion = "紧张"
    elif sacrifice_count >= 2 and bond_count >= 2:
        emotion = "悲壮"  # 牺牲+羁绊 = 悲壮而非紧张
    elif conflict_density > 1.5:
        emotion = "悲壮"
    elif comeback_count > slap_count:
        emotion = "悬疑"
    elif dialogue_ratio > 0.35:
        emotion = "日常"
    else:
        emotion = "日常"

    # ── Pace ──
    avg_para_len = wc / max(ch["para_count"], 1)
    if avg_para_len < 45 or (avg_para_len < 80 and excl_density > 0.5):
        pace = "fast"
    elif avg_para_len > 250:
        pace = "slow"
    else:
        pace = "medium"

    return {
        "ch_num": ch["num"],
        "wc": wc,
        "para_count": ch["para_count"],
        "avg_para_len": int(avg_para_len),
        "dialogue_ratio": round(dialogue_ratio, 3),
        "excl_density": round(excl_density, 2),
        "pos_density": round(pos_density, 2),
        "neg_density": round(neg_density, 2),
        "conflict_density": round(conflict_density, 2),
        "hook_density": round(hook_density, 2),
        "slap_count": slap_count,
        "level_count": level_count,
        "crush_count": crush_count,
        "comeback_count": comeback_count,
        "hidden_count": hidden_count,
        "bond_count": bond_count,            # v4
        "cognitive_count": cognitive_count,  # v4
        "sacrifice_count": sacrifice_count,  # v4
        "physio_count": physio_count,        # v4
        "dominant_sub": dominant_sub[0],
        "pleasure_type": pleasure_type,
        "pleasure_intensity": pleasure_intensity,
        "pleasure_level": "small",  # computed in analyze_book from 3-chapter window
        "hook_type": hook_type,
        "readability": readability_score,
        "avg_sentence_len": round(avg_sentence_len, 1),
        "vocab_diversity": round(vocab_diversity, 3),
        "conflict": conflict_density > 0.3,
        "conflict_level": conflict_level,
        "emotion": emotion,
        "pace": pace,
        "slap_noise": (slap_count > 5 and pleasure_intensity < 3),  # P0: flag suspected false positives
    }


def llm_verify(ch, rule_result):
    """LLM verification for key chapters only. Returns dict or None on failure."""
    prompt = (
        "你是网文节奏分析专家。验证以下章节的自动分析结果:\n"
        f"第{ch['num']}章: {ch['title']}  ({ch['wc']}字)\n\n"
        f"{ch['text'][:1500]}\n\n"
        "自动分析:\n"
        f"爽点类型={rule_result['pleasure_type']}, 强度={rule_result['pleasure_intensity']}, "
        f"冲突={rule_result['conflict_level']}, 情绪={rule_result['emotion']}, 节奏={rule_result['pace']}\n\n"
        "输出JSON修正(若自动分析正确则原样输出):\n"
        '{"pleasure_type":"none/minor/major/climax","pleasure_intensity":0-10,'
        '"conflict_level":"none/low/medium/high","emotion":"紧张/轻松/悲壮/爽快/日常/悬疑","pace":"fast/slow/medium"}'
    )
    data = json.dumps({
        "messages": [{"role":"user","content": prompt}],
        "max_tokens": 200, "temperature": 0.1,
    }).encode("utf-8")
    try:
        req = urllib.request.Request(
            f"{LLAMA_BASE}/v1/chat/completions",
            data, {"Content-Type": "application/json"}
        )
        resp = json.loads(urllib.request.urlopen(req, timeout=60).read())
        raw = resp["choices"][0]["message"].get("content", "")
        m = re.search(r'\{[^}]+\}', raw)
        if m: return json.loads(m.group())
    except: pass
    return None


def _write_chapter_instructions(name, results, csv_path):
    """P0: Bridge — generate & write per-chapter writing instructions.
    
    Calls generate_chapter_instructions from writing_instructions.py.
    """
    if not _instructions_available:
        print("  [SKIP] writing_instructions unavailable")
        return
    lines, issue_count = generate_chapter_instructions(results, name)
    out_dir = PROJECT_ROOT / "outputs" / "reports" / "writing_manuals"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{name}_逐章指令.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  [OK] 逐章指令: {out_path.name} ({issue_count} issues)")


def analyze_book(filepath):
    """Full analysis. Rule-based + LLM verify 5 key chapters. Saves CSV immediately."""
    name = Path(filepath).stem
    print(f"\n[BOOK] {name}")
    t0 = time.time()

    chapters = extract_chapters(filepath)
    total = len(chapters)
    total_wc = sum(c["wc"] for c in chapters)
    print(f"  Chaps: {total}  Words: {total_wc:,}  Avg: {total_wc//max(total,1):,}")

    # ── Phase 1: Rule-based all chapters (instant) ──
    print(f"  Analyzing {total} chapters (rule-based)...")
    results = []
    for ch in chapters:
        r = rule_analyze(ch)
        results.append(r)

    # ── Phase 1b: Chapter-to-chapter variability ──
    # Inspired by DTW concept from Climactic Chapter Recognition paper (Applied Sciences)
    # Measures how much a chapter deviates from its neighbors in key metrics
    for i, r in enumerate(results):
        if i == 0 or i == len(results) - 1:
            continue
        prev = results[i-1]
        diff = (
            abs(r["wc"] - prev["wc"]) / max(prev["wc"], 1) +
            abs(r["dialogue_ratio"] - prev["dialogue_ratio"]) / max(prev["dialogue_ratio"], 0.001) +
            abs(r["pos_density"] - prev["pos_density"]) / max(prev["pos_density"], 0.001) +
            abs(r["conflict_density"] - prev["conflict_density"]) / max(prev["conflict_density"], 0.001)
        ) / 4
        r["ch_variability"] = round(diff, 3)
    # Set endpoints (0 for first/last, no previous to compare)
    if results:
        results[0]["ch_variability"] = 0.0
        results[-1]["ch_variability"] = 0.0

    # ── 马良三级爽点递进: small/medium/large (3-ch sliding window) ──
    for i, r in enumerate(results):
        window = results[max(0,i-1):min(len(results),i+2)]
        intensities = [x["pleasure_intensity"] for x in window]
        avg_intensity = sum(intensities) / len(intensities)
        has_climax = any(x["pleasure_type"] == "climax" for x in window)
        has_major = any(x["pleasure_type"] == "major" for x in window)
        slap_total = sum(x["slap_count"] for x in window)

        if has_climax and avg_intensity >= 6:
            r["pleasure_level"] = "large"
        elif has_major and avg_intensity >= 4 and slap_total >= 3:
            r["pleasure_level"] = "medium"
        elif slap_total >= 1 or r["pleasure_intensity"] >= 2:
            r["pleasure_level"] = "small"
        else:
            r["pleasure_level"] = "none"

    # ── Phase 2: LLM-as-Judge sampling (WebNovelBench method) ──
    # Sample every 10th chapter + ensure coverage of key segments
    step = max(1, total // 10)  # ~10% sampling
    verify_indices = set()
    for i in range(0, total, step):
        verify_indices.add(i)
    # Always include first, last, max intensity, max conflict
    verify_indices.add(0)
    verify_indices.add(total - 1)
    sorted_by_intensity = sorted(results, key=lambda r: r["pleasure_intensity"], reverse=True)
    sorted_by_conflict = sorted(results, key=lambda r: r["conflict_density"], reverse=True)
    verify_indices.add(sorted_by_intensity[0]["ch_num"] - 1)
    verify_indices.add(sorted_by_conflict[0]["ch_num"] - 1)
    verify_indices = sorted(verify_indices)[:15]  # cap at 15

    # Check if LLM server is available
    try:
        urllib.request.urlopen(f"{LLAMA_BASE}/health", timeout=2)
        server_ok = True
    except:
        server_ok = False

    llm_correlation = None
    if server_ok:
        print(f"  LLM-as-Judge sampling {len(verify_indices)} chapters (~{total//10 if total>10 else 1}% coverage)...")
        rule_labels = []
        llm_labels = []
        verified = 0
        for vi in verify_indices:
            if vi >= len(results): continue
            ch = chapters[vi]
            r = results[vi]
            # Store rule labels before LLM overwrites
            rule_labels.append(r["pleasure_intensity"])
            llm = llm_verify(ch, r)
            if llm:
                r["pleasure_type"] = llm.get("pleasure_type", r["pleasure_type"])
                r["pleasure_intensity"] = llm.get("pleasure_intensity", r["pleasure_intensity"])
                r["conflict_level"] = llm.get("conflict_level", r["conflict_level"])
                r["emotion"] = llm.get("emotion", r["emotion"])
                r["pace"] = llm.get("pace", r["pace"])
                llm_labels.append(r["pleasure_intensity"])
                verified += 1

        # ── Correlation validation (WebNovelBench method) ──
        if len(rule_labels) > 5 and len(rule_labels) == len(llm_labels):
            n = len(rule_labels)
            mean_r = sum(rule_labels) / n
            mean_l = sum(llm_labels) / n
            cov = sum((rule_labels[i] - mean_r) * (llm_labels[i] - mean_l) for i in range(n))
            std_r = (sum((x - mean_r)**2 for x in rule_labels) / n) ** 0.5
            std_l = (sum((x - mean_l)**2 for x in llm_labels) / n) ** 0.5
            if std_r > 0 and std_l > 0:
                llm_correlation = round(cov / (std_r * std_l * n), 3)
                print(f"  LLM-rule correlation r={llm_correlation} ({verified} verified, {'strong' if abs(llm_correlation)>0.7 else 'moderate' if abs(llm_correlation)>0.4 else 'weak'})")
    else:
        print("  [SKIP] No LLM server, pure rule-based")

    # ── Save CSV immediately ──
    csv_path = RHYTHM_DIR / f"rhythm_{name}.csv"
    fields = ["ch_num","wc","para_count","avg_para_len","dialogue_ratio",
              "excl_density","pos_density","neg_density","conflict_density","hook_density",
              "slap_count","level_count","crush_count","comeback_count","hidden_count",
              "bond_count","cognitive_count","sacrifice_count","physio_count",  # v4
              "dominant_sub",
              "pleasure_type","pleasure_intensity","pleasure_level",
              "hook_type","readability","avg_sentence_len","vocab_diversity",
              "conflict","conflict_level","emotion","pace",
              "ch_variability"]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(results)

    # v5: Generate per-chapter writing instructions
    _write_chapter_instructions(name, results, csv_path)

    # ── Summary ──
    pleasure_density = sum(1 for r in results if r["pleasure_type"] != "none") / max(total, 1)
    conflict_rate = sum(1 for r in results if r["conflict"]) / max(total, 1)
    avg_intensity = sum(r["pleasure_intensity"] for r in results) / max(total, 1)
    avg_hook = sum(r.get("hook_density", 0) for r in results) / max(total, 1)
    # Sub-type distribution
    sub_dist = {}
    for r in results:
        sub = r.get("dominant_sub", "none")
        sub_dist[sub] = sub_dist.get(sub, 0) + 1

    dt = time.time() - t0
    # Hook type distribution
    hook_dist = {}
    for r in results:
        ht = r.get("hook_type", "none")
        hook_dist[ht] = hook_dist.get(ht, 0) + 1
    # Pleasure level distribution
    level_dist = {}
    for r in results:
        pl = r.get("pleasure_level", "none")
        level_dist[pl] = level_dist.get(pl, 0) + 1
    avg_readability = sum(r.get("readability", 0) for r in results) / max(total, 1)

    print(f"  [SAVED] {csv_path.name}  ({dt:.0f}s)")
    print(f"  P-density={pleasure_density:.2f}  Conflict={conflict_rate:.2f}  Intensity={avg_intensity:.1f}  Hook={avg_hook:.1f}/k  Readability={avg_readability:.3f}")
    print(f"  Subs: {dict(sorted(sub_dist.items(), key=lambda x:-x[1]))}")
    print(f"  HookTypes: {dict(sorted(hook_dist.items(), key=lambda x:-x[1]))}")
    print(f"  Levels: {dict(sorted(level_dist.items(), key=lambda x:-x[1]))}")

    return {
        "name": name, "total_chaps": total, "total_words": total_wc,
        "avg_wc": total_wc // max(total, 1),
        "pleasure_density": round(pleasure_density, 2),
        "conflict_rate": round(conflict_rate, 2),
        "avg_intensity": round(avg_intensity, 1),
        "avg_hook": round(avg_hook, 1),
        "sub_dist": {k: v for k, v in sorted(sub_dist.items(), key=lambda x: -x[1])},
        "llm_correlation": llm_correlation,
    }


def _percentile(values, p):
    """Compute p-th percentile (0-100) from sorted values."""
    if not values:
        return 0
    k = (len(values) - 1) * p / 100.0
    f = int(k)
    c = k - f
    if f + 1 < len(values):
        return values[f] + c * (values[f+1] - values[f])
    return values[f]


def compare(summaries):
    """Compare all books using percentile-based ranking (WebNovelBench PCA method)."""
    n = len(summaries)
    if n < 3:
        print(f"  [SKIP] Need >=3 books for percentile ranking, got {n}")
        return

    # Extract metric vectors
    p_densities = sorted([s["pleasure_density"] for s in summaries])
    conflicts = sorted([s["conflict_rate"] for s in summaries])
    intensities = sorted([s["avg_intensity"] for s in summaries])
    hooks = sorted([s.get("avg_hook", 0) for s in summaries])

    # Percentile thresholds
    p25 = lambda arr: _percentile(arr, 25)
    p50 = lambda arr: _percentile(arr, 50)
    p75 = lambda arr: _percentile(arr, 75)

    print(f"\n{'='*70}")
    print("  ANALYSIS SYSTEM v3: PERCENTILE-BASED RANKING (WebNovelBench method)")
    print(f"{'='*70}")
    print(f"  Thresholds (pooled from {n} books):")
    print(f"    P-density: P25={p25(p_densities):.2f}  P50={p50(p_densities):.2f}  P75={p75(p_densities):.2f}")
    print(f"    Conflict:  P25={p25(conflicts):.2f}  P50={p50(conflicts):.2f}  P75={p75(conflicts):.2f}")
    print(f"    Intensity: P25={p25(intensities):.1f}  P50={p50(intensities):.1f}  P75={p75(intensities):.1f}")
    print(f"    Hook:      P25={p25(hooks):.1f}  P50={p50(hooks):.1f}  P75={p75(hooks):.1f}")
    print(f"\n  {'Book':35s} {'Chaps':>5} {'P-pct':>6} {'C-pct':>6} {'I-pct':>6} {'H-pct':>6} {'R^2':>6}")
    print(f"  {'-'*35} {'-'*5} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*6}")

    pct_scores = []
    for s in summaries:
        def rank_pct(arr, val):
            """Return percentile rank (0-100) of val in arr."""
            if not arr or max(arr) == min(arr):
                return 50
            return round((sum(1 for x in arr if x <= val) / len(arr)) * 100)

        p_pct = rank_pct(p_densities, s["pleasure_density"])
        c_pct = rank_pct(conflicts, s["conflict_rate"])
        i_pct = rank_pct(intensities, s["avg_intensity"])
        h_pct = rank_pct(hooks, s.get("avg_hook", 0))
        r2 = s.get("llm_correlation", "-")
        r2_str = f"{r2:.2f}" if isinstance(r2, float) else "-"

        n_short = s["name"][:34]
        print(f"  {n_short:35s} {s['total_chaps']:5d} {p_pct:5d}% {c_pct:5d}% {i_pct:5d}% {h_pct:5d}% {r2_str:>6}")

        composite = (p_pct + c_pct + i_pct + h_pct) / 4
        pct_scores.append((s["name"], composite))

    # Top 3 ranking
    pct_scores.sort(key=lambda x: -x[1])
    print("\n  Top 3 by composite percentile:")
    for i, (name, score) in enumerate(pct_scores[:3]):
        print(f"    #{i+1} {name[:40]}: {score:.0f}%")


# ===== MAIN =====
if __name__ == "__main__":
    import sys
    genre = None
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--genre" and i < len(sys.argv) - 1:
            genre = sys.argv[i + 1]

    if genre:
        genre_dir = NOVELS_DIR / genre
        files = sorted(genre_dir.glob("*.txt")) if genre_dir.exists() else []
    else:
        files = sorted(NOVELS_DIR.glob("**/*.txt"))
    if not files:
        print(f"[FAIL] No .txt files in {'novels/' + genre if genre else NOVELS_DIR}")
        exit(1)

    print(f"[OK] {len(files)} novels in {'genre=' + genre if genre else str(len(set(f.parent.name for f in files))) + ' genres'}, rule-first + LLM verify 5 ch/book")
    summaries = []
    for fp in files:
        s = analyze_book(fp)
        summaries.append(s)

    compare(summaries)
    print("\n[DONE]")
