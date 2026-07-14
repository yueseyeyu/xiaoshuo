#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
llm_batch_score.py — LLM rubric-based batch chapter scoring (v18 CoT+Context+Confidence)
Method: Rubric Is All You Need (ACM 2025) + CoT Scoring (RUC-NLPIR Survey 2025) +
        Self-Consistency (Wang et al. 2022) + Chapter Context Injection
Replaces: rule-based pleasure_intensity/conflict_level/emotion/pace with LLM scores
Usage: python -m xiaoshuo.pipeline.llm_batch_score --book all  (or --book 末世之黑暗时代)
Output: data/processed/{genre}/scores/{book}_llm.csv
"""
import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# 确保localhost请求不走系统代理（梯子会拦截127.0.0.1导致LLM调用超时）
import os as _os
_os.environ["NO_PROXY"] = _os.environ.get("NO_PROXY", "") + ",127.0.0.1,localhost"
import csv
import json
import re
import sys
import statistics
import urllib.parse
import urllib.error
import http.client
import time
import threading
import concurrent.futures  # v3: max_workers=4 for RTX 5060 8GB with KV q8_0 (L0-3 optimization)
import yaml
from pathlib import Path

from xiaoshuo import PROJECT_ROOT
from xiaoshuo.infra.logging_config import get_logger
from xiaoshuo.pipeline.paths import rhythm_dir as _rhythm_dir, llm_score_dir, golden_set_path as _golden_set_path_fn
from xiaoshuo.infra.llm_client import check_llm_health, get_main_model_base_url
logger = get_logger(__name__)
# LLMLingua-2 removed (v8.15): original model deprecated, replacement too large for 8GB GPU
from collections import Counter

# PROJECT_ROOT imported from src.xiaoshuo
NOVELS_DIR = PROJECT_ROOT / "data" / "raw" / "novels"
INDEX_PATH = PROJECT_ROOT / "data" / "raw" / "novel_index.json"




def _llm_dir(genre):
    return llm_score_dir(genre)
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


# ── v22: Tier-based sampling + Stratified sampling ──
# P1: S/A级书籍采样量50章, B/C级30章 (v22.1: C级从20提升到30)
# P3: S/A级书籍启用sc=3自一致性采样
# P2: 5段分层采样替代均匀采样

_TIER_SAMPLING = {
    "S":       {"max_ch": 50, "sc_samples": 3},   # 标杆书: 叙事最复杂, LLM预测性最低, 需最多样本+自一致性
    "A":       {"max_ch": 30, "sc_samples": 1},   # v8.8: 50→30, Kim(2026)研究表明A级不需与S级同等量
    "B_plus":  {"max_ch": 30, "sc_samples": 1},
    "B":       {"max_ch": 30, "sc_samples": 1},
    "B_minus": {"max_ch": 30, "sc_samples": 1},
    "C":       {"max_ch": 20, "sc_samples": 1},   # v8.8: 30→20, C级套路化高LLM预测性高, Kim(2026)支持少样本
}


def _get_book_tier(book_name):
    """v22: Look up book quality tier from config.yaml quality_tiers.
    Returns tier name ('S'/'A'/'B_plus'/'B'/'B_minus'/'C') or None."""
    try:
        from xiaoshuo.infra.config_manager import get_config
        cfg = get_config()
        tiers_cfg = cfg.get("analysis", {}).get("book_filter", {}).get("quality_tiers", {})
        if not tiers_cfg:
            return None
        name_clean = book_name.replace("《", "").replace("》", "").strip()
        for tier_name, tier_data in tiers_cfg.items():
            for bn in tier_data.get("books", []):
                bn_clean = bn.replace("《", "").replace("》", "").strip()
                if bn_clean in name_clean or name_clean in bn_clean:
                    return tier_name
        return None
    except Exception:
        return None


def _stratified_sample(n_chapters, max_chapters):
    """v22 P2: 5段分层采样 — 替代均匀采样, 确保关键段不遗漏。

    分层依据网文结构特征:
    - 黄金开篇 (0-3%):   番茄推荐池核心, 10%采样
    - 上升期 (3-30%):    留存关键期, 30%采样
    - 中段稳定 (30-60%):  粉丝沉淀, 25%采样
    - 高潮密集 (60-90%):  月票冲刺, 25%采样
    - 结尾 (90-100%):     完本口碑, 10%采样

    每层内均匀采样, 层间按比例分配。
    """
    if n_chapters <= max_chapters:
        return list(range(n_chapters))

    strata = [
        (0.00, 0.03, 0.10),
        (0.03, 0.30, 0.30),
        (0.30, 0.60, 0.25),
        (0.60, 0.90, 0.25),
        (0.90, 1.00, 0.10),
    ]

    indices = []
    for start_pct, end_pct, sample_pct in strata:
        start_idx = int(start_pct * n_chapters)
        end_idx = int(end_pct * n_chapters)
        n_in_stratum = end_idx - start_idx
        if n_in_stratum <= 0:
            continue
        n_samples = max(1, round(sample_pct * max_chapters))
        if n_samples >= n_in_stratum:
            indices.extend(range(start_idx, end_idx))
        else:
            step = max(1, n_in_stratum // n_samples)
            indices.extend(range(start_idx, end_idx, step)[:n_samples])

    seen = set()
    result = []
    for idx in indices:
        if idx not in seen:
            seen.add(idx)
            result.append(idx)
            if len(result) >= max_chapters:
                break

    if len(result) < max_chapters:
        remaining = sorted(set(range(n_chapters)) - seen)
        fill_step = max(1, len(remaining) // max(1, max_chapters - len(result)))
        for idx in remaining[::fill_step]:
            result.append(idx)
            if len(result) >= max_chapters:
                break

    return sorted(result)


# v8.4: 保留 http.client 连接池以提升批量评分性能，URL 从 llm_client 获取
_LLAMA_BASE = get_main_model_base_url()
_LLAMA_HOST = urllib.parse.urlparse(_LLAMA_BASE).netloc

def _get_server_parallel():
    """Read LLM server parallel setting from config.yaml for optimal worker count."""
    try:
        from xiaoshuo.infra.config_manager import get_config
        cfg = get_config()
        return cfg.get("analysis", {}).get("llm_parallel", 1)
    except Exception:
        return 1


LLM_PARALLEL = _get_server_parallel()

from xiaoshuo.pipeline.rhythm_analyzer import extract_chapters


def check_server():
    """Check LLM server health via unified llm_client."""
    return check_llm_health(timeout=5)


# ── Rubric template (DRY: shared by single-pass and self-consistency scoring) ──

def _normalize_hook(hook_val):
    """Normalize hook field: LLM sometimes outputs numeric (e.g. '5.0') instead of category.
    Map: >=7 → strong, >=4 → weak, <4 → none."""
    if not hook_val:
        return "none"
    s = str(hook_val)
    if s in ("none", "weak", "strong"):
        return s
    try:
        v = float(s)
        if v >= 7:
            return "strong"
        elif v >= 4:
            return "weak"
        else:
            return "none"
    except ValueError:
        return "none"

# v18: CoT (Chain-of-Thought) scoring — 先分析再评分，准确率+15-20%
# 参考: RUC-NLPIR/Rubrics_Survey (2025), Microsoft LLM-Rubric (ACL 2024)
_RUBRIC_TEMPLATE = (
    "=== 你是专业网文编辑，对章节阅读体验独立评分 ===\n\n"
    "请对下方章节评分，大胆使用全量程(1-10)，不要挤在中段。\n\n"
    "### 评分量规 (Rubric) ###\n"
    "1. 爽点强度 (1-10): 1=平淡铺垫 3=小爽 5=明显爽感 7=强烈高光 10=巅峰神作\n"
    "   [锚定] 普通过渡章=3 | 标准打脸成功=5 | 绝境翻盘=7 | 全书最佳高潮=9-10\n"
    "2. 冲突等级: none/low/medium/high\n"
    "3. 情绪氛围: 爽快/紧张/悲壮/悬疑/日常/温情/压抑\n"
    "4. 节奏: fast/medium/slow\n"
    "5. 钩子质量: none/weak/strong\n"
    "6. 读者留存力 (1-10): 1=可能弃书 5=普通 7=想追 10=熬夜也要看\n"
    "   [锚定] 开篇铺垫=4 | 小高潮后=6 | 重大反转后=8 | 全书高潮=9-10\n\n"
    "### 输出格式 (先分析再评分) ###\n"
    "先用1-2句话分析本章的核心看点/问题，然后输出评分JSON。\n"
    "格式:\n"
    "分析: [你的简要分析]\n"
    '{"intensity":5,"conflict":"medium","emotion":"日常","pace":"medium","hook":"weak","retention":5}\n'
    '[1分示例] 分析: 纯水文，大量无意义对话，零冲突零爽点零悬念。 {"intensity":1,"conflict":"none","emotion":"日常","pace":"slow","hook":"none","retention":2}\n'
    '[3分示例] 分析: 铺垫章，信息量少但节奏尚可，有小悬念。 {"intensity":3,"conflict":"low","emotion":"日常","pace":"medium","hook":"weak","retention":4}\n'
    '[5分示例] 分析: 有明确冲突和爽点，但不够强烈，过渡感重。 {"intensity":5,"conflict":"medium","emotion":"紧张","pace":"medium","hook":"weak","retention":6}\n'
    '[8分示例] 分析: 绝境翻盘高潮，冲突激烈钩子强。 {"intensity":8,"conflict":"high","emotion":"爽快","pace":"fast","hook":"strong","retention":9}\n'
    '[10分示例] 分析: 全书最佳高潮，多重伏笔回收+碾压式打脸。 {"intensity":10,"conflict":"high","emotion":"爽快","pace":"fast","hook":"strong","retention":10}\n'
    '[2分示例-防信息高潮误判] 分析: 纯对话章，虽有重大设定揭示(身份/伏笔)，但主角缺席、无战斗无情绪释放，visceral爽感极低。注意：信息重要性≠阅读爽感，勿因"剧情重要"给高分。 {"intensity":2,"conflict":"low","emotion":"悬疑","pace":"slow","hook":"weak","retention":4}\n'
    '[4分示例-过渡章] 分析: 有铺垫和伏笔，节奏平稳，有些许悬念但无高潮。读者能继续追但缺乏兴奋感。 {"intensity":4,"conflict":"low","emotion":"日常","pace":"medium","hook":"weak","retention":5}'
)


# v18 O7: 子类型特定Rubric强调 — 根据sub_genre调整评分重点
_SUB_GENRE_EMPHASIS = {
    "打脸流": "\n[子类型强调] 打脸流：重点关注爽点强度和钩子质量，打脸成功=5+，连续打脸=7+",
    "智斗流": "\n[子类型强调] 智斗流：重点关注冲突强度和悬念感，智谋对决=冲突high+情绪悬疑",
    "羁绊流": "\n[子类型强调] 羁绊流：重点关注情绪氛围和留存力，情感高光=intensity 5+可接受",
    "末世求生": "\n[子类型强调] 末世求生：重点关注紧张感和生存压力，物资获取/危机应对=爽感来源",
    "系统流": "\n[子类型强调] 系统流：重点关注爽点强度(升级/获得)和钩子(新任务提示)",
    "通用": "",
}


# v21 P3b: 中段爽点峰值抽取用的轻量级正则 (模块级，避免重复编译)
import re as _re_mod
_PEAK_PLEASURE_PAT = _re_mod.compile(
    r"打脸|突破|碾压|秒杀|反杀|逆转|翻盘|绝境|扮猪|隐藏实力|"
    r"震惊|惊呆|不可思议|怎么可能|不可能|傻眼|目瞪口呆|"
    r"升级|进阶|觉醒|解锁|获得|收获|得到|入手|"
    r"计策|谋划|布局|算计|识破|看穿|预判|"
    r"原来如此|恍然大悟|终于知道|真相|秘密|"
    r"牺牲|守护|并肩|羁绊|"
    r"威慑|臣服|折服|信[任赖]|认可|承认"
)


def _find_peak_pleasure_segment(mid_text, window=200):
    """v21 P3b: 在中段文本中找爽点密度最高的window字窗口。
    
    用轻量级爽点正则(不导入rule_analyzer避免循环依赖)扫描中段，
    返回爽点匹配数最多的窗口段落。如果中段太短或无爽点，返回None。
    """
    if not mid_text or len(mid_text) < window:
        return None
    # 滑动窗口扫描
    best_count = 0
    best_start = 0
    step = max(50, window // 4)  # 1/4窗口步长，平衡精度和性能
    for start in range(0, len(mid_text) - window + 1, step):
        segment = mid_text[start:start + window]
        count = len(_PEAK_PLEASURE_PAT.findall(segment))
        if count > best_count:
            best_count = count
            best_start = start
    if best_count == 0:
        return None
    return mid_text[best_start:best_start + window]


def _build_rubric_prompts(chapter_text, ch_num, prev_context="", sub_genre=""):
    """Build system+user message pair for rubric scoring.
    v9: Prefix Caching — rubric in system (fixed), chapter in user (variable).
    v18: Chapter context injection + sub-genre emphasis.
    llama-server --cache-prompt reuses KV for system prefix across all calls."""
    # v18: 智能截断 — head 300 + tail 700 (优先保留章末钩子段)
    # v21 P3b: 中段爽点峰值抽取 — 在head和tail之间插入爽点密度最高的200字段落
    # 来源: Doubao(滑动窗口)+Kimi(Lost in the Middle)折中方案
    # 理论依据: Liu et al. 2023 "Lost in the Middle" — LLM对首尾信息利用效率最高
    # 但中段高潮丢失会导致评分偏低，用规则评分已计算的爽点位置信息辅助
    text = chapter_text
    if len(text) > 1200:
        head = text[:300]
        tail = text[-700:]
        mid = text[300:-700]
        # 在中段找爽点密度最高的200字窗口
        best_segment = _find_peak_pleasure_segment(mid, window=200)
        if best_segment:
            text = head + "\n...[中段省略]...\n" + best_segment + "\n...[中段省略]...\n" + tail
        else:
            text = head + "\n...[中段省略]...\n" + tail
    else:
        text = text[:1200]

    # System message: fixed rubric template (KV cache reusable)
    system_msg = _RUBRIC_TEMPLATE
    # v18 O7: 追加子类型强调
    emphasis = _SUB_GENRE_EMPHASIS.get(sub_genre, "")
    if emphasis:
        system_msg = system_msg + emphasis

    # User message: chapter-specific content (varies per call)
    # v18: 注入前章上下文，让LLM理解过渡章的叙事功能
    if prev_context:
        user_msg = f"[前情提要] {prev_context}\n\n第{ch_num}章:\n{text}"
    else:
        user_msg = f"第{ch_num}章:\n{text}"
    return system_msg, user_msg


def _extract_rubric_json(raw):
    """Extract rubric JSON from LLM raw output.
    v17: Extracted from llm_score_rubric + llm_score_self_consistency (DRY).
    Tries: full JSON match → field regex fallback → None."""
    if not raw:
        return None
    try:
        for pat in [r'\{[^{}]*?"intensity"[^{}]*?\}', r'\{[^{]*"intensity"[^}]*\}']:
            m = re.search(pat, raw)
            if m:
                try:
                    res = json.loads(m.group())
                    if "intensity" in res:
                        if "hook" in res:
                            res["hook"] = _normalize_hook(res["hook"])
                        return res
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
        # Fallback: field-by-field extraction
        pi = re.search(r'"intensity"\s*:\s*(\d+(?:\.\d+)?)', raw)
        cl = re.search(r'"conflict"\s*:\s*"([^"]+)"', raw)
        em = re.search(r'"emotion"\s*:\s*"([^"]+)"', raw)
        pa = re.search(r'"pace"\s*:\s*"([^"]+)"', raw)
        hq = re.search(r'"hook"\s*:\s*"([^"]+)"', raw)
        rt = re.search(r'"retention"\s*:\s*(\d+(?:\.\d+)?)', raw)
        if pi:
            hook_raw = hq.group(1) if hq else "none"
            return {
                "intensity": float(pi.group(1)),
                "conflict": cl.group(1) if cl else "medium",
                "emotion": em.group(1) if em else "日常",
                "pace": pa.group(1) if pa else "medium",
                "hook": _normalize_hook(hook_raw),
                "retention": float(rt.group(1)) if rt else 5,
            }
        return None
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning("Rubric JSON解析失败: %s", e)
        return None


def llm_score_rubric(chapter_text, ch_num, conn=None, prev_context="", sub_genre="", temperature=0.0):
    """Rubric-based scoring (Rubric Is All You Need, ACM 2025).
    v9: system/user separation for prefix caching.
    v18: CoT + prev_context + sub_genre emphasis.
    v18-fix: 去掉conn复用模式，统一走llm_chat（每次创建新连接，避免HTTP状态损坏）。
    v22.1 P0: Added temperature parameter (was hardcoded 0.1, causing llm_score_with_confidence
    to run both samples at same temperature, defeating dual-temperature confidence detection).
    conn参数保留但不再使用，仅向后兼容。"""
    system_msg, user_msg = _build_rubric_prompts(chapter_text, ch_num, prev_context, sub_genre)

    # v18-fix: 统一走 llm_chat — 每次调用创建新HTTP连接并正确关闭
    # llm_chat 内部已有 max_retries=2 + 指数退避，无需外层再重试
    from xiaoshuo.infra.llm_client import llm_chat
    raw = llm_chat(
        user_msg, system=system_msg,
        max_tokens=300, temperature=temperature, timeout=60,
        max_retries=2, strip_thinking=True,
    )
    if not raw:
        return None

    # JSON extraction (v17: delegated to _extract_rubric_json)
    result = _extract_rubric_json(raw)
    if result is None:
        logger.warning("LLM评分解析失败(ch%d): raw=%s", ch_num, raw[:100] if raw else 'empty')
    return result


def llm_score_self_consistency(chapter_text, ch_num, n_samples=3, conn=None, prev_context="", sub_genre=""):
    """v8: Self-Consistency multi-sample scoring (Wang et al. 2022 + TURN arxiv 2502.05234).
    v18: Added prev_context + sub_genre parameters.
    v18-fix: 去掉conn复用，统一走llm_chat。
    v22.1 P0: Temperature range expanded from (0.1/0.2/0.3) to (0.0/0.3/0.6).
    - 0.0 (greedy): stable anchor, ensures at least one reliable score
    - 0.3: light diversity, catches minor reasoning path variations
    - 0.6: moderate diversity, tests scoring robustness
    - Old range (0.1/0.2/0.3) was too narrow — three samples were highly correlated,
      median had minimal variance reduction effect.
    - 0.9 not used: risky for 9B quantized model (JSON format instability).
    Falls back to single sample if >=50% calls fail."""
    temps = [0.0, 0.3, 0.6][:n_samples]  # v22.1: Expanded temperature range
    results = []
    for t in temps:
        # Multiple temperature samples for self-consistency
        try:
            # v22.1: Use llm_score_rubric for DRY (it now accepts temperature param)
            parsed = llm_score_rubric(chapter_text, ch_num, prev_context=prev_context, sub_genre=sub_genre, temperature=t)
            if parsed:
                results.append(parsed)
        except Exception:
            continue
        time.sleep(0.1)  # Minimal gap between SC samples

    if len(results) < n_samples * 0.5:
        return None  # Too many failures, fall back

    # Aggregate: median for numeric, mode for categorical
    return {
        "intensity": round(statistics.median([r["intensity"] for r in results]), 1),
        "conflict": Counter(r["conflict"] for r in results).most_common(1)[0][0],
        "emotion": Counter(r["emotion"] for r in results).most_common(1)[0][0],
        "pace": Counter(r["pace"] for r in results).most_common(1)[0][0],
        "hook": Counter(r["hook"] for r in results).most_common(1)[0][0],
        "retention": round(statistics.median([r["retention"] for r in results]), 1),
    }


# v18: 评分置信度 — 双温度采样，标记 low_confidence
# 参考: AutoRubric.org ensemble judging + agreement metrics
_CONFIDENCE_THRESHOLD = 2.0  # intensity差异>2分标记为低置信度
_AUTO_UPGRADE_THRESHOLD = 1.0  # v22.1 P1: 更敏感的阈值，触发自动补采第3次


def llm_score_with_confidence(chapter_text, ch_num, conn=None, prev_context="", sub_genre="", auto_upgrade=False):
    """v18: 双温度评分 (0.0 + 0.3)，取均值并计算置信度。
    v18-b2: Added sub_genre parameter.
    v18-fix: 去掉conn依赖，两次调用都走llm_chat（各自创建新连接）。
    v22.1 P0: Fixed critical bug — both calls were using temperature=0.1 (hardcoded in
    llm_score_rubric), defeating the dual-temperature design. Now properly uses 0.0 and 0.3.
    v22.1 P1: Auto-upgrade — when auto_upgrade=True and intensity/retention diff > 1.0,
    automatically run a 3rd sample at temperature 0.6 and re-aggregate using median.
    Expected upgrade rate ~15-20%, cost increase ~15-20% (far less than full sc=3's 200%).
    如果两次 intensity 差异 > 2.0，标记 low_confidence=True。
    返回 result dict + confidence 字段。"""
    r1 = llm_score_rubric(chapter_text, ch_num, prev_context=prev_context, sub_genre=sub_genre, temperature=0.0)
    if r1 is None:
        return None
    # 第二次采样，检测评分稳定性（v22.1: 使用不同温度0.3）
    r2 = llm_score_rubric(chapter_text, ch_num, prev_context=prev_context, sub_genre=sub_genre, temperature=0.3)
    if r2 is None:
        # 第二次失败，用第一次结果，标记为中等置信度
        r1["low_confidence"] = False
        r1["confidence_note"] = "single_sample"
        return r1
    # 计算置信度
    intensity_diff = abs(r1["intensity"] - r2["intensity"])
    retention_diff = abs(r1["retention"] - r2["retention"])
    is_low = intensity_diff > _CONFIDENCE_THRESHOLD or retention_diff > _CONFIDENCE_THRESHOLD

    # v22.1 P1: Auto-upgrade — 差异适中(>1.0)时补采第3次，用中位数聚合
    needs_upgrade = auto_upgrade and (
        intensity_diff > _AUTO_UPGRADE_THRESHOLD or retention_diff > _AUTO_UPGRADE_THRESHOLD
    )
    if needs_upgrade:
        r3 = llm_score_rubric(chapter_text, ch_num, prev_context=prev_context, sub_genre=sub_genre, temperature=0.6)
        if r3:
            # 用中位数聚合（与SC一致），比均值更抗极端值
            merged = {
                "intensity": round(statistics.median([r1["intensity"], r2["intensity"], r3["intensity"]]), 1),
                "retention": round(statistics.median([r1["retention"], r2["retention"], r3["retention"]]), 1),
                "conflict": Counter([r1["conflict"], r2["conflict"], r3["conflict"]]).most_common(1)[0][0],
                "emotion": Counter([r1["emotion"], r2["emotion"], r3["emotion"]]).most_common(1)[0][0],
                "pace": Counter([r1["pace"], r2["pace"], r3["pace"]]).most_common(1)[0][0],
                "hook": Counter([r1["hook"], r2["hook"], r3["hook"]]).most_common(1)[0][0],
                "low_confidence": is_low,
                "confidence_note": f"upgraded:Δi={intensity_diff:.1f},Δr={retention_diff:.1f}",
            }
            return merged

    # 默认：取均值
    merged = {
        "intensity": round((r1["intensity"] + r2["intensity"]) / 2, 1),
        "retention": round((r1["retention"] + r2["retention"]) / 2, 1),
        "conflict": r1["conflict"] if r1["conflict"] == r2["conflict"] else r1["conflict"],
        "emotion": r1["emotion"] if r1["emotion"] == r2["emotion"] else r1["emotion"],
        "pace": r1["pace"] if r1["pace"] == r2["pace"] else r1["pace"],
        "hook": r1["hook"] if r1["hook"] == r2["hook"] else r1["hook"],
        "low_confidence": is_low,
        "confidence_note": f"Δi={intensity_diff:.1f},Δr={retention_diff:.1f}",
    }
    return merged


# ══════════════════════════════════════════════════════════════
# v8.14: Reference-Based Scoring (Phase A1)
# ══════════════════════════════════════════════════════════════
# 论文: Can LLMs Be Good Evaluators? (MDPI 2025) — positivity bias
#       Automated Creativity Evaluation (ACL 2025) — ref-based MAE↓30-50%
# 核心改进: 用真实章节摘录+已知人工评分替代合成描述作为校准锚点


def _truncate_reference_text(text, max_len=400):
    """Truncate chapter text for reference passage: head 150 + tail 250."""
    if len(text) <= max_len:
        return text
    head_len = min(150, max_len // 3)
    return text[:head_len] + "\n...[省略]...\n" + text[-(max_len - head_len - 20):]


def build_reference_bank(golden_csv_path=None, genre="末世"):
    """Build reference passage bank from golden CSV + novel texts.

    Loads human_golden_merged.csv, finds chapter texts from novel files,
    extracts excerpts, and returns all golden passages with score band labels.

    Returns:
        list of dicts: [{book, ch_num, excerpt, human_intensity, human_retention, band, tags}]
    """
    if golden_csv_path is None:
        golden_csv_path = PROJECT_ROOT / "data" / "golden" / genre / "tier3" / "human_golden_merged.csv"

    golden_csv_path = Path(golden_csv_path)
    if not golden_csv_path.exists():
        logger.warning("Golden CSV not found: %s", golden_csv_path)
        return []

    with open(golden_csv_path, 'r', encoding='utf-8-sig') as f:
        golden_rows = list(csv.DictReader(f))

    with open(INDEX_PATH, 'r', encoding='utf-8') as f:
        index = json.load(f)
    novels = index.get("genres", {}).get(genre, {}).get("novels", [])

    # Build book short_name -> txt_path mapping
    book_to_txt = {}
    for novel in novels:
        txt_file = novel.get("file", "")
        for fp in NOVELS_DIR.glob(f"{genre}/*.txt"):
            if fp.name == txt_file:
                short_name = txt_file.replace(".txt", "").replace("《", "").replace("》", "")
                m = re.match(r"([^（(]+)", short_name)
                if m:
                    short_name = m.group(1).strip()
                book_to_txt[short_name] = fp
                break

    references = []
    _chapter_cache = {}

    for row in golden_rows:
        book_name = row.get("book", "").strip()
        ch_num = int(row.get("ch_num", 0))
        human_intensity = float(row.get("human_intensity", 0) or 0)
        human_retention = float(row.get("human_retention", 0) or 0)

        if not book_name or ch_num == 0:
            continue

        txt_path = None
        for short_name, fp in book_to_txt.items():
            if short_name in book_name or book_name in short_name:
                txt_path = fp
                break

        if txt_path is None:
            logger.warning("No txt found for book '%s'", book_name)
            continue

        cache_key = str(txt_path)
        if cache_key not in _chapter_cache:
            _chapter_cache[cache_key] = extract_chapters(txt_path)
        chapters = _chapter_cache[cache_key]

        chapter = None
        for ch in chapters:
            if ch.get("num") == ch_num:
                chapter = ch
                break

        if chapter is None:
            logger.warning("Chapter %d not found in %s", ch_num, book_name)
            continue

        excerpt = _truncate_reference_text(chapter.get("raw_body", ""))
        if len(excerpt) < 50:
            continue

        if human_intensity <= 3.5:
            band = "low"
        elif human_intensity <= 5.5:
            band = "medium_low"
        elif human_intensity <= 7.5:
            band = "medium_high"
        else:
            band = "high"

        references.append({
            "book": book_name,
            "ch_num": ch_num,
            "excerpt": excerpt,
            "human_intensity": human_intensity,
            "human_retention": human_retention,
            "band": band,
            "tags": row.get("tags", ""),
        })

    logger.info("Reference bank: %d passages from %d books",
                len(references), len(set(r["book"] for r in references)))
    return references


def _select_references(references, exclude_book=None, exclude_ch_num=None):
    """Select 4 representative references (one per score band), excluding specified chapter.

    Leave-one-out: when scoring chapter X, exclude X from references.
    If X was the only reference in its band, include it anyway.

    Returns:
        list of 4 (or fewer) reference dicts, one per band
    """
    bands = ["low", "medium_low", "medium_high", "high"]
    band_centers = {"low": 2.5, "medium_low": 4.5, "medium_high": 6.5, "high": 8.5}
    selected = []

    for band in bands:
        candidates = [
            r for r in references
            if r["band"] == band
            and not (r["book"] == exclude_book and r["ch_num"] == exclude_ch_num)
        ]
        if not candidates:
            candidates = [r for r in references if r["band"] == band]
        if not candidates:
            continue

        center = band_centers[band]
        best = min(candidates, key=lambda r: abs(r["human_intensity"] - center))
        selected.append(best)

    return selected


_REF_RUBRIC_TEMPLATE = (
    "=== 你是专业网文编辑，对章节阅读体验独立评分 ===\n\n"
    "请对下方章节评分，大胆使用全量程(1-10)，不要挤在中段。\n\n"
    "### 校准参考段落 (已知人工评分) ###\n"
    "以下段落来自已标注的末世小说章节，人工评分已验证。\n"
    "请参照这些段落的评分基准来校准你的评分尺度。\n\n"
    "{reference_section}\n\n"
    "### 评分量规 (Rubric) ###\n"
    "1. 爽点强度 (1-10): 1=平淡铺垫 3=小爽 5=明显爽感 7=强烈高光 10=巅峰神作\n"
    "   [锚定] 普通过渡章=3 | 标准打脸成功=5 | 绝境翻盘=7 | 全书最佳高潮=9-10\n"
    "2. 冲突等级: none/low/medium/high\n"
    "3. 情绪氛围: 爽快/紧张/悲壮/悬疑/日常/温情/压抑\n"
    "4. 节奏: fast/medium/slow\n"
    "5. 钩子质量: none/weak/strong\n"
    "6. 读者留存力 (1-10): 1=可能弃书 5=普通 7=想追 10=熬夜也要看\n"
    "   [锚定] 开篇铺垫=4 | 小高潮后=6 | 重大反转后=8 | 全书高潮=9-10\n\n"
    "### 输出格式 (先分析再评分) ###\n"
    "先用一句话（不超过30字）概括本章核心看点，然后参照参考段落评估本章水平，最后输出评分JSON。\n"
    "注意：分析必须简短，重点输出JSON。\n"
    "格式:\n"
    "分析: [一句话概括]\n"
    '{"intensity":5,"conflict":"medium","emotion":"日常","pace":"medium","hook":"weak","retention":5}'
)


def _build_reference_system_prompt(references):
    """Build system prompt with reference passages injected."""
    band_labels = {
        "low": "低分段 (平淡铺垫)",
        "medium_low": "中低分段 (有冲突但不够强)",
        "medium_high": "中高分段 (明确爽感)",
        "high": "高分段 (强烈高潮)",
    }

    ref_parts = []
    for i, ref in enumerate(references, 1):
        band_label = band_labels.get(ref["band"], ref["band"])
        ref_parts.append(
            f"[参考{i} - {band_label} | 人工评分: 爽点{ref['human_intensity']:.1f}, 留存{ref['human_retention']:.1f}]\n"
            f"来源: {ref['book']} 第{ref['ch_num']}章\n"
            f"标签: {ref.get('tags', '无')}\n"
            f'"{ref["excerpt"]}"'
        )

    reference_section = "\n\n".join(ref_parts)
    return _REF_RUBRIC_TEMPLATE.replace("{reference_section}", reference_section)


def llm_score_reference_based(chapter_text, ch_num, references, prev_context="", sub_genre="", temperature=0.0):
    """v8.14: Reference-based scoring (Phase A1).

    Provides LLM with real chapter excerpts + known human scores as calibration anchors.
    Reduces positivity bias (MDPI 2025) and improves MAE by 30-50% (ACL 2025).

    Returns:
        dict with intensity, conflict, emotion, pace, hook, retention, or None
    """
    if not references:
        return llm_score_rubric(chapter_text, ch_num, prev_context=prev_context,
                                 sub_genre=sub_genre, temperature=temperature)

    system_msg = _build_reference_system_prompt(references)

    emphasis = _SUB_GENRE_EMPHASIS.get(sub_genre, "")
    if emphasis:
        system_msg = system_msg + emphasis

    # Same truncation as _build_rubric_prompts
    text = chapter_text
    if len(text) > 1200:
        head = text[:300]
        tail = text[-700:]
        mid = text[300:-700]
        best_segment = _find_peak_pleasure_segment(mid, window=200)
        if best_segment:
            text = head + "\n...[中段省略]...\n" + best_segment + "\n...[中段省略]...\n" + tail
        else:
            text = head + "\n...[中段省略]...\n" + tail
    else:
        text = text[:1200]

    if prev_context:
        user_msg = f"[前情提要] {prev_context}\n\n第{ch_num}章:\n{text}"
    else:
        user_msg = f"第{ch_num}章:\n{text}"

    from xiaoshuo.infra.llm_client import llm_chat
    raw = llm_chat(
        user_msg, system=system_msg,
        max_tokens=600, temperature=temperature, timeout=60,
        max_retries=2, strip_thinking=True,
    )
    if not raw:
        return None

    result = _extract_rubric_json(raw)
    if result is None:
        # Retry with a shorter, JSON-focused prompt (no reference comparison)
        logger.warning("Reference-based scoring parse failed (ch%d), retrying with JSON-only prompt", ch_num)
        retry_system = (
            "你是专业网文编辑。请直接输出评分JSON，不要输出分析。\n"
            "参考评分尺度: 低分(2-3)=平淡铺垫, 中分(5)=有冲突, 高分(7)=强烈高光, 巅峰(9)=全书最佳。\n"
            "只输出JSON: {\"intensity\":5,\"conflict\":\"medium\",\"emotion\":\"日常\",\"pace\":\"medium\",\"hook\":\"weak\",\"retention\":5}"
        )
        raw2 = llm_chat(
            user_msg, system=retry_system,
            max_tokens=200, temperature=temperature, timeout=60,
            max_retries=1, strip_thinking=True,
        )
        if raw2:
            result = _extract_rubric_json(raw2)
        if result is None:
            logger.warning("Reference-based scoring retry also failed (ch%d): raw=%s",
                           ch_num, raw[:100] if raw else 'empty')
    return result


def batch_book(txt_path, csv_path, max_chapters=None, sc_samples=1):
    """Batch-score all chapters in a book, merge with existing rhythm CSV.
    sc_samples: Self-Consistency samples (1=single pass, 3=multi-sample median/mode aggregation)
    Saves: data/llm_scores/{book}_llm.csv"""
    chapters = extract_chapters(txt_path)
    if not chapters:
        return None

    # Load existing rule CSV for base info
    rule_rows = {}
    if csv_path and csv_path.exists():
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                rule_rows[int(r["ch_num"])] = r

    # v7.5: Check existing LLM scores to skip already-scored chapters
    already_scored = set()
    genre = Path(txt_path).parent.name  # derive from path: data/raw/novels/{genre}/book.txt
    llm_csv_path = _llm_dir(genre) / f"{Path(txt_path).stem}_llm.csv"
    if llm_csv_path.exists():
        with open(llm_csv_path, 'r', encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                already_scored.add(int(r.get("ch_num", 0)))

    # v22 P2: Stratified sampling — 5-segment proportional (replaces uniform)
    if max_chapters and len(chapters) > max_chapters:
        idx_to_score_all = _stratified_sample(len(chapters), max_chapters)
    else:
        idx_to_score_all = list(range(len(chapters)))

    # v17: 跳过极短章节（wc<300），内容太少无法可靠评分
    MIN_SCORE_WC = 300
    short_ch_count = sum(1 for idx in idx_to_score_all if chapters[idx].get("wc", 0) < MIN_SCORE_WC)
    if short_ch_count > 0:
        logger.info("SKIP %d chapters with wc<%d (too short for reliable scoring)", short_ch_count, MIN_SCORE_WC)
    idx_to_score_all = [i for i in idx_to_score_all if chapters[i].get("wc", 0) >= MIN_SCORE_WC]

    # v7.5: skip already-scored chapters
    idx_to_score = [i for i in idx_to_score_all if chapters[i].get("num", 0) not in already_scored]
    name = Path(txt_path).stem
    n = len(idx_to_score)
    if n == 0:
        logger.info("CACHE: All %d chapters already scored, skip", len(idx_to_score_all))
        return
    logger.info("Scoring %d/%d chapters (parallel x%d)...", n, len(idx_to_score_all), LLM_PARALLEL)

    # v18 O7: 检测子类型用于Rubric强调
    sub_genre = ""
    try:
        from xiaoshuo.pipeline.scoring.commercial_engine import _detect_sub_genre
        # 用已有rule_rows检测子类型 (CSV读取的值是str，需转换为numeric)
        sample_rows = list(rule_rows.values())[:30]
        if sample_rows:
            # 转换CSV字符串值为_detect_sub_genre期望的numeric类型
            _numeric_keys = ["bond_count", "cognitive_count", "sacrifice_count",
                             "hook_density", "conflict_density", "pleasure_intensity",
                             "pos_density", "slap_count", "wc"]
            for r in sample_rows:
                for k in _numeric_keys:
                    if k in r:
                        try:
                            r[k] = float(r[k])
                        except (ValueError, TypeError):
                            r[k] = 0
            sub_genre = _detect_sub_genre(sample_rows, book_name=name)
            logger.info("SUB-GENRE detected: %s", sub_genre)
    except Exception:
        pass

    # v18-fix: 不再需要HTTP连接池变量（统一走llm_chat）

    def _score_chunk(body, ch_num, part_tag, prev_context="", sub_genre=""):
        """Score one chunk of a chapter.
        v17: Remove [:1500] truncation — _build_rubric_prompts already truncates to 1200.
        v18-fix: 去掉conn参数，内部走llm_chat创建新连接。"""
        text = f"[第{ch_num}章 {part_tag}]\n{body}"
        return llm_score_rubric(text, ch_num, prev_context=prev_context, sub_genre=sub_genre)

    def _merge_chunk_scores(chunk_results):
        """Merge scores from multiple chunks: average numerics, vote categoricals.
        v18: Add chunk-agreement confidence (O5-fix)."""
        valid = [r for r in chunk_results if r]
        if not valid:
            return None
        merged = {}
        for key in ["intensity", "retention"]:
            vals = []
            for r in valid:
                try: vals.append(float(r[key]))
                except (ValueError, TypeError, KeyError): pass
            merged[key] = round(sum(vals) / len(vals), 1) if vals else 5.0
        for key in ["conflict", "emotion", "pace", "hook"]:
            cats = [str(r[key]) for r in valid if key in r and r[key]]
            merged[key] = max(set(cats), key=cats.count) if cats else ("medium" if key != "emotion" and key != "hook" else ("日常" if key == "emotion" else "none"))
        # v18 O5-fix: chunk间一致性置信度
        if len(valid) >= 2:
            int_vals = [float(r.get("intensity", 5)) for r in valid if "intensity" in r]
            ret_vals = [float(r.get("retention", 5)) for r in valid if "retention" in r]
            int_range = max(int_vals) - min(int_vals) if int_vals else 0
            ret_range = max(ret_vals) - min(ret_vals) if ret_vals else 0
            merged["low_confidence"] = int_range > _CONFIDENCE_THRESHOLD or ret_range > _CONFIDENCE_THRESHOLD
            merged["confidence_note"] = f"chunk_range:i={int_range:.1f},r={ret_range:.1f}"
        else:
            merged["low_confidence"] = False
            merged["confidence_note"] = "single_chunk"
        return merged

    def _score_chapter(packed):
        i, idx = packed
        ch = chapters[idx]
        ch_num = ch.get("num", i + 1)
        full_body = ch["raw_body"]

        # v18: 提取前章末尾200字作为上下文
        prev_context = ""
        if idx > 0:
            prev_body = chapters[idx - 1].get("raw_body", "")
            if prev_body:
                prev_context = prev_body[-200:].replace("\n", " ").strip()

        # v7.5: chunked scoring — split long chapters, score each chunk, merge
        # v18-fix: 去掉连接池，每次llm_score_rubric调用内部走llm_chat创建新连接
        # v22.1 P0: CHUNK_SIZE 1500→3000 — 网文章节普遍2000-3000字，旧值导致80%+章节
        #   走chunk路径绕过SC。_build_rubric_prompts已有1200字智能截断(head300+peak200+tail700)，
        #   不存在超长上下文风险。3000字以上章节(极少)仍走chunk fallback。
        CHUNK_SIZE = 3000
        if len(full_body) > CHUNK_SIZE:
            chunks = [full_body[j:j+CHUNK_SIZE] for j in range(0, len(full_body), CHUNK_SIZE)]
            chunk_results = [_score_chunk(chunk, ch_num, f"part{ci+1}/{len(chunks)}", prev_context=prev_context, sub_genre=sub_genre) for ci, chunk in enumerate(chunks[:3])]
            llm = _merge_chunk_scores(chunk_results)
        else:
            if sc_samples > 1:
                llm = llm_score_self_consistency(full_body, ch_num, sc_samples, prev_context=prev_context, sub_genre=sub_genre)
            else:
                # v18: 使用带置信度的评分
                # v22.1 P1: auto_upgrade=True — 低置信章节自动补采第3次
                llm = llm_score_with_confidence(full_body, ch_num, prev_context=prev_context, sub_genre=sub_genre, auto_upgrade=True)
        rule = rule_rows.get(ch_num, {})
        if llm is None:
            return (i, ch_num, None)
        return (i, ch_num, llm, rule, ch["wc"])

    # Submit all, collect in order (v9: max_workers matches server --parallel)
    ordered = [None] * n
    with concurrent.futures.ThreadPoolExecutor(max_workers=LLM_PARALLEL) as executor:
        futures = {}
        for packed in enumerate(idx_to_score):
            fut = executor.submit(_score_chapter, packed)
            futures[fut] = packed[0]

        completed = 0
        for fut in concurrent.futures.as_completed(futures):
            try:
                i, ch_num, *rest = fut.result(timeout=300)
                ordered[i] = (ch_num, rest)
            except Exception as e:
                i = futures[fut]
                ch_num = idx_to_score[i] + 1
                rest = [None]
                logger.warning("Ch%d [FAIL] %s", ch_num, type(e).__name__)
                ordered[i] = (ch_num, [None])
            completed += 1
            pct = round(completed / n * 100)
            status = f"Ch{ch_num} ({pct}%)" if rest[0] is not None else f"Ch{ch_num} [FAIL]"
            logger.info("%s", status)

    # P1-4: collect failed chapters → serial retry (avoids slot contention)
    failed = [(i, ordered[i]) for i in range(n)
              if ordered[i] is not None and ordered[i][1][0] is None]
    if failed:
        logger.info("RETRY: %d failed chapters, serial retry...", len(failed))
        retry_success = 0
        for i, (ch_num, _) in failed:
            idx = idx_to_score[i]
            ch = chapters[idx]
            ch_num_actual = ch.get("num", idx + 1)
            rule = rule_rows.get(ch_num_actual, {})
            full_body = ch["raw_body"]
            # Serial retry: also use chunked scoring if long
            # v18-fix: 去掉retry_conn，统一走llm_chat（每次创建新连接）
            # v22.1 P0: CHUNK_SIZE 1500→3000 (同_score_chapter)
            CHUNK_SIZE = 3000
            # v18: retry也注入前章上下文
            prev_context = ""
            if idx > 0:
                prev_body = chapters[idx - 1].get("raw_body", "")
                if prev_body:
                    prev_context = prev_body[-200:].replace("\n", " ").strip()
            if len(full_body) > CHUNK_SIZE:
                chunks = [full_body[j:j+CHUNK_SIZE] for j in range(0, len(full_body), CHUNK_SIZE)]
                chunk_results = [_score_chunk(chunk, ch_num_actual, f"retry-p{ci+1}", prev_context=prev_context, sub_genre=sub_genre) for ci, chunk in enumerate(chunks[:3])]
                llm = _merge_chunk_scores(chunk_results)
            else:
                if sc_samples > 1:
                    llm = llm_score_self_consistency(full_body, ch_num_actual, sc_samples, prev_context=prev_context, sub_genre=sub_genre)
                else:
                    # v22.1 P1: retry path also uses auto_upgrade
                    llm = llm_score_with_confidence(full_body, ch_num_actual, prev_context=prev_context, sub_genre=sub_genre, auto_upgrade=True)
            if llm is not None:
                ordered[i] = (ch_num_actual, [llm, rule, ch["wc"]])
                retry_success += 1
                logger.info("Ch%d [OK retry]", ch_num_actual)
            else:
                logger.warning("Ch%d [retry FAIL]", ch_num_actual)
        logger.info("RETRY: recovered %d/%d chapters", retry_success, len(failed))

    # Build results in original order
    results = []
    for i in range(n):
        item = ordered[i]
        if item is None or item[1][0] is None:
            continue
        ch_num, (llm, rule, ch_wc) = item
        row = {
            "ch_num": ch_num,
            "wc": int(rule.get("wc", ch_wc)),
            # LLM scores (primary)
            "llm_intensity": float(llm["intensity"]),
            "llm_conflict": llm["conflict"],
            "llm_emotion": llm["emotion"],
            "llm_pace": llm["pace"],
            "llm_hook": llm["hook"],
            "llm_retention": float(llm["retention"]),
            # v18: 置信度指标
            "llm_low_confidence": llm.get("low_confidence", False),
            "llm_confidence_note": llm.get("confidence_note", ""),
            # Rule scores (reference)
            "rule_intensity": float(rule.get("pleasure_intensity", 0)),
            "rule_hook": rule.get("hook_type", "none"),
            "rule_emotion": rule.get("emotion", "日常"),
            "rule_pace": rule.get("pace", "medium"),
        }
        results.append(row)
        conf_tag = "!" if row["llm_low_confidence"] else ""
        logger.info("L:%.0fR:%.1fH:%s%s", llm['intensity'], row['rule_intensity'], llm['hook'], conf_tag)

    if not results:
        return None

    # Save
    genre = Path(txt_path).parent.name
    llm_out = _llm_dir(genre)
    llm_out.mkdir(parents=True, exist_ok=True)
    out_path = llm_out / f"{name}_llm.csv"
    fields = ["ch_num", "wc",
              "llm_intensity", "llm_conflict", "llm_emotion", "llm_pace", "llm_hook", "llm_retention",
              "llm_low_confidence", "llm_confidence_note",
              "rule_intensity", "rule_hook", "rule_emotion", "rule_pace"]
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(results)

    # Stats
    intens = [r["llm_intensity"] for r in results]
    logger.info("OK N=%d | intensity %.0f-%.0f mean=%.1f | %s", len(results), min(intens), max(intens), statistics.mean(intens), out_path)
    
    # v8.15: Save scoring metadata for traceability
    _meta_path = out_path.parent / f"{name}_scoring_metadata.json"
    import time as _time_meta
    from datetime import datetime as _dt
    _meta = {
        "book": name,
        "n_chapters": len(results),
        "scoring_date": _dt.now().isoformat(),
        "temperature": 0.0,
        "model": "Qwen3.5-9B Q4_K_M",
        "prev_context": True,
        "csv_path": str(out_path),
        "script": "llm_batch_score.batch_book",
    }
    try:
        with open(_meta_path, "w", encoding="utf-8") as _mf:
            json.dump(_meta, _mf, ensure_ascii=False, indent=2)
    except Exception:
        pass
    
    # v18 O5: Pairwise对比评分 — BT模型校准rubric intensity
    try:
        rubric_map = {r["ch_num"]: r for r in results}
        bt_blended = batch_pairwise_scoring(txt_path, rubric_map, n_pairs=10)
        if bt_blended:
            # Update CSV with BT-blended intensity
            with open(out_path, "r", encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
                fields = list(rows[0].keys()) if rows else []
            if "llm_intensity_bt" not in fields:
                fields.append("llm_intensity_bt")
            for row in rows:
                ch = int(row["ch_num"])
                row["llm_intensity_bt"] = str(bt_blended.get(ch, row.get("llm_intensity", "5")))
            with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
                w.writeheader()
                w.writerows(rows)
            logger.info("[O5] BT-blended intensity added to CSV")
    except Exception as e:
        logger.warning("[O5] Pairwise skipped: %s", e)
    
    # v18 O8: Golden Set校准 (如果golden_set.json存在)
    try:
        apply_golden_set_calibration(out_path)
    except Exception as e:
        logger.warning("[O8] Calibration skipped: %s", e)
    
    # v18 O9: Export to chapter_decisions for style_evolution (Part A → Part E)
    try:
        export_llm_scores_to_decisions(out_path, book_name=name)
    except Exception as e:
        logger.warning("[O9] Export skipped: %s", e)
    
    # v18 O11: Online BMA weight update — feed LLM+Rule scores to update BMA weights
    # v20: 传入ch_num和golden_set，用human_score打破循环论证
    try:
        from xiaoshuo.pipeline.scoring.commercial_engine import update_bma_weights_online
        llm_list = [{"ch_num": r["ch_num"], "intensity": r["llm_intensity"], "retention": r["llm_retention"]} for r in results]
        rule_list = [{"pleasure_intensity": r["rule_intensity"]} for r in results]
        # v20: 加载golden_set传入BMA权重更新
        _gs_path = _golden_set_path_fn(genre)
        golden_data = None
        if _gs_path.exists():
            try:
                with open(_gs_path, "r", encoding="utf-8") as gf:
                    golden_all = json.load(gf)
                # 按书名过滤，避免多书ch_num碰撞
                # name 形如 "《废土崛起》（校对版全本）作者：通吃道人"
                # golden_set中book是短名(如"废土崛起")
                name_clean = name.replace("《", "").replace("》", "").strip()
                golden_data = [g for g in golden_all
                               if not g.get("book") or
                               g["book"].replace("《", "").replace("》", "").strip() in name_clean or
                               name_clean in g["book"].replace("《", "").replace("》", "").strip()]
                if not golden_data:
                    golden_data = golden_all  # fallback: 无匹配时用全部
            except Exception:
                pass
        update_bma_weights_online(llm_list, rule_list, genre=genre, golden_set=golden_data)
    except Exception as e:
        logger.warning("[O11] BMA online update skipped: %s", e)
    
    return out_path


# ── v18 O9: LLM评分→chapter_decisions反哺 (Part A → Part E 数据流) ──

def export_llm_scores_to_decisions(csv_path, book_name=""):
    """v18 O9: 将LLM评分CSV导出为chapter_decisions格式，供style_evolution使用。
    
    数据流: llm_batch_score CSV → chapter_decisions/all_llm_scores.json → style_evolution
    
    这不是替代作者手写的chapter_decisions，而是作为补充数据源：
    - 作者决策 = 主观偏好 (best_segment, break_convention, rejected_advice)
    - LLM评分 = 客观质量评估 (intensity, retention, hook, ...)
    两者结合让style_evolution引擎同时看到主观意图和客观效果。
    """
    if not csv_path or not Path(csv_path).exists():
        return None
    
    decisions_dir = PROJECT_ROOT / "data" / "processed" / "chapter_decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    out_path = decisions_dir / "all_llm_scores.json"
    
    # Load existing
    existing = []
    if out_path.exists():
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = []
    
    # Load new CSV data
    new_records = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            new_records.append({
                "chapter": int(row.get("ch_num", 0)),
                "book": book_name,
                "llm_intensity": float(row.get("llm_intensity", 0)),
                "llm_retention": float(row.get("llm_retention", 0)),
                "llm_conflict": row.get("llm_conflict", ""),
                "llm_emotion": row.get("llm_emotion", ""),
                "llm_pace": row.get("llm_pace", ""),
                "llm_hook": row.get("llm_hook", ""),
                "llm_low_confidence": row.get("llm_low_confidence", "False") == "True",
                "source": "qwen_llm_batch_score",
            })
    
    if not new_records:
        return None
    
    # Merge: replace existing entries for same book+chapter
    existing_by_key = {(r.get("book", ""), r.get("chapter", 0)): r for r in existing}
    for rec in new_records:
        key = (rec["book"], rec["chapter"])
        existing_by_key[key] = rec
    
    merged = list(existing_by_key.values())
    merged.sort(key=lambda r: (r.get("book", ""), r.get("chapter", 0)))
    
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    
    logger.info("[O9] Exported %d LLM scores → %s", len(new_records), out_path)
    return out_path


# ══════════════════════════════════════════════════════════════
# v18 批次三: O5 Pairwise对比评分 + O8 Golden Set校准
# ══════════════════════════════════════════════════════════════

# ── O5: Pairwise对比评分 ──
# 参考: LitBench (arXiv 2504.12296), Chatbot Arena Bradley-Terry
# 研究: pairwise comparison与人类判断一致性比absolute scoring高20-30%
# 实现: 采样章节对→LLM判断"A vs B哪个更爽"→BT模型转绝对分→与rubric分融合

_PAIRWISE_PROMPT = (
    "=== 你是专业网文编辑，请对比两章的阅读体验 ===\n\n"
    "对比维度: 整体爽感、情节张力、阅读流畅度。\n"
    "只考虑阅读体验，不考虑字数多少。\n\n"
    "输出格式 (只输出一个字母):\n"
    "A — 第A章更好\n"
    "B — 第B章更好\n"
    "T — 两章差不多\n"
)


def llm_pairwise_compare(ch_a_text, ch_b_text, ch_a_num, ch_b_num, conn=None):
    """v18 O5: Pairwise comparison — ask LLM which chapter is more engaging.
    v18-fix: 去掉conn直连模式，统一走llm_chat。
    Returns: 'A', 'B', or 'T' (tie)."""
    # Truncate both chapters to ~600 chars each to fit in context
    def _truncate(text, maxlen=600):
        if len(text) > maxlen:
            return text[:200] + "\n...[省略]...\n" + text[-300:]
        return text

    user_msg = (
        f"第A章 (原第{ch_a_num}章):\n{_truncate(ch_a_text)}\n\n"
        f"第B章 (原第{ch_b_num}章):\n{_truncate(ch_b_text)}\n\n"
        "哪章阅读体验更好？只输出A、B或T。"
    )

    try:
        from xiaoshuo.infra.llm_client import llm_chat
        raw = llm_chat(user_msg, system=_PAIRWISE_PROMPT,
                      max_tokens=10, temperature=0.1, timeout=30,
                      max_retries=1, strip_thinking=True)
        raw = raw.strip().upper()
        # Extract first letter
        for ch in raw:
            if ch in ("A", "B", "T"):
                return ch
        return "T"  # default tie if unparseable
    except Exception:
        return "T"


def _bradley_terry_estimate(pairwise_results):
    """v18 O5: Convert pairwise win/loss records to BT ability scores (0-10 scale).
    
    Args:
        pairwise_results: list of (ch_num_a, ch_num_b, verdict) where verdict='A'/'B'/'T'
    
    Returns:
        {ch_num: bt_score} where bt_score is 0-10 scale
        
    Uses simple iterative BT: θ_i = wins_i / (wins_i + losses_i), then scale to 0-10.
    For small N, uses Laplace smoothing (add 1 to wins and losses).
    """
    from collections import defaultdict
    wins = defaultdict(int)
    losses = defaultdict(int)
    all_chs = set()
    
    for ch_a, ch_b, verdict in pairwise_results:
        all_chs.add(ch_a)
        all_chs.add(ch_b)
        if verdict == "A":
            wins[ch_a] += 1
            losses[ch_b] += 1
        elif verdict == "B":
            wins[ch_b] += 1
            losses[ch_a] += 1
        # T = tie, no change to win/loss
    
    # BT ability with Laplace smoothing: θ = (wins+1)/(wins+losses+2)
    bt_scores = {}
    for ch in all_chs:
        w = wins[ch] + 1  # Laplace
        l = losses[ch] + 1
        bt_scores[ch] = round(w / (w + l) * 10, 1)  # scale to 0-10
    
    return bt_scores


def batch_pairwise_scoring(txt_path, rubric_scores, n_pairs=10, conn=None):
    """v18 O5: Sample chapter pairs, run pairwise comparisons, convert to BT scores.
    v18-fix: 去掉conn参数，每次pairwise调用走llm_chat创建新连接。
    
    Args:
        txt_path: novel text path
        rubric_scores: {ch_num: rubric_dict} from batch_book results
        n_pairs: number of pairs to compare (default 10)
        conn: 保留但不再使用（向后兼容）
    
    Returns:
        {ch_num: bt_adjusted_intensity} — BT-derived intensity scores
    """
    import random
    chapters = extract_chapters(txt_path)
    if not chapters or len(chapters) < 4:
        return {}
    
    # Build ch_num → text mapping
    ch_map = {}
    for i, ch in enumerate(chapters):
        ch_num = ch.get("num", i + 1)
        if ch_num in rubric_scores:
            ch_map[ch_num] = ch.get("raw_body", "")
    
    if len(ch_map) < 4:
        return {}
    
    ch_nums = list(ch_map.keys())
    # Sample pairs: mix of adjacent + random for diversity
    pairs = []
    # 50% adjacent pairs (catch pacing issues)
    for i in range(0, len(ch_nums) - 1, max(1, len(ch_nums) // (n_pairs // 2))):
        pairs.append((ch_nums[i], ch_nums[i + 1]))
    # 50% random pairs
    random.seed(42)  # reproducible
    for _ in range(n_pairs - len(pairs)):
        if len(ch_nums) >= 2:
            a, b = random.sample(ch_nums, 2)
            pairs.append((a, b))
    pairs = pairs[:n_pairs]
    
    logger.info("[PAIRWISE] Running %d pairwise comparisons...", len(pairs))
    pairwise_results = []
    # v18-fix: 不再创建HTTP连接，llm_pairwise_compare内部走llm_chat
    for ch_a, ch_b in pairs:
        verdict = llm_pairwise_compare(
            ch_map[ch_a], ch_map[ch_b], ch_a, ch_b
        )
        pairwise_results.append((ch_a, ch_b, verdict))
    
    # Convert to BT scores
    bt_scores = _bradley_terry_estimate(pairwise_results)
    
    # Blend BT score with rubric intensity (60% rubric + 40% BT)
    # BT is relative, rubric is absolute — blend for best of both
    blended = {}
    for ch_num, rubric in rubric_scores.items():
        rubric_int = float(rubric.get("llm_intensity", 5.0))
        bt_int = bt_scores.get(ch_num, rubric_int)  # fallback to rubric if no BT data
        blended[ch_num] = round(0.6 * rubric_int + 0.4 * bt_int, 1)
    
    wins_summary = sum(1 for _, _, v in pairwise_results if v != "T")
    logger.info("[PAIRWISE] %d/%d decisive, BT range: %.1f-%.1f",
               wins_summary, len(pairwise_results),
               min(bt_scores.values()), max(bt_scores.values()))
    
    return blended


# ── O8: Golden Set校准框架 ──
# 构建: golden_set.json (人工标注) → 计算LLM评分偏移 → 应用校准

def apply_golden_set_calibration(csv_path, golden_set_path=None):
    """v21 O8: Apply golden set calibration to LLM scores — shrinkage-blended histogram equalization.
    
    Golden set format (JSON, generated by scripts/convert_golden.py + update_golden_llm.py):
    [
        {"book": "废土崛起", "ch_num": 1, "human_intensity": 3, "human_retention": 3,
         "llm_intensity": 4.5, "llm_retention": 5.5, ...},
        ...
    ]
    
    v21 (P0修复): Median offset + shrinkage + smart-skip
    - v20问题: 纯分位数映射在偏差已较小时过度校正（bias从+0.78翻转到-0.73）
    - v21方案: calibrated = raw + shrinkage * median_offset, s=0.6
    - smart-skip: |median_offset| < 0.5 时跳过校准（偏差太小不值得冒险）
    - golden_set.json 的 llm_intensity 字段优先于 CSV（用于交叉验证模式）
    - Phase C验证: MAE 1.917->1.843 (改善4.2%), bias +0.783->+0.183
    
    v20: 升级为分位数映射 (Histogram Equalization)
    v19: 按book过滤golden entries，避免不同书ch_num碰撞。
    """
    if golden_set_path is None:
        golden_set_path = _golden_set_path_fn()
    golden_set_path = Path(golden_set_path)
    
    if not golden_set_path.exists():
        return None  # No golden set — skip calibration
    
    try:
        with open(golden_set_path, "r", encoding="utf-8") as f:
            golden = json.load(f)
    except Exception:
        return None
    
    if len(golden) < 3:
        logger.info("[O8] Golden set has only %d entries (need ≥3), skipping calibration", len(golden))
        return None
    
    # v19: 从csv_path推断book_name，用于过滤golden entries
    csv_stem = Path(csv_path).stem
    book_name_raw = csv_stem.replace("_llm", "").strip()
    def _book_match(golden_book, csv_book_full):
        if not golden_book or not csv_book_full:
            return False
        g = golden_book.replace("《", "").replace("》", "").strip()
        c = csv_book_full.replace("《", "").replace("》", "").strip()
        return g in c or c in g
    
    # Filter golden entries by book
    golden_for_book = [g for g in golden if _book_match(g.get("book", ""), book_name_raw)]
    if not golden_for_book:
        golden_for_book = golden
        logger.info("[O8] No book match for '%s', using all golden entries (legacy mode)", book_name_raw)
    else:
        logger.info("[O8] Matched %d golden entries for '%s'", len(golden_for_book), book_name_raw)
    
    if len(golden_for_book) < 3:
        logger.info("[O8] Only %d golden entries for this book (need ≥3), skipping", len(golden_for_book))
        return None
    
    # Load LLM scores
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        llm_rows = {int(r["ch_num"]): r for r in csv.DictReader(f)}
    
    # Collect paired (llm_score, human_score) for building calibration mapping
    # v21: golden_set.json 的 llm_intensity 字段优先（交叉验证模式），
    #       否则从 CSV 读取（生产模式）
    paired_int = []  # [(llm_int, human_int), ...]
    paired_ret = []
    for g in golden_for_book:
        ch_num = g.get("ch_num")
        # 优先使用 golden_set.json 中的 llm_intensity（交叉验证模式）
        if "llm_intensity" in g and "llm_retention" in g:
            llm_int = float(g["llm_intensity"])
            llm_ret = float(g["llm_retention"])
        elif ch_num in llm_rows:
            llm_int = float(llm_rows[ch_num].get("llm_intensity", 5))
            llm_ret = float(llm_rows[ch_num].get("llm_retention", 5))
        else:
            continue
        human_int = float(g.get("human_intensity", llm_int))
        human_ret = float(g.get("human_retention", llm_ret))
        paired_int.append((llm_int, human_int))
        paired_ret.append((llm_ret, human_ret))
    
    if len(paired_int) < 3:
        return None
    
    # v20: Build quantile mapping function (true Histogram Equalization)
    # 真正的分位数映射: LLM分和human分各自独立排序，按秩匹配
    # 这保证单调性: 更高的LLM分一定映射到更高(或相等)的human分
    def _build_quantile_map(paired):
        """Build a monotonic piecewise linear mapping from LLM score → human score.
        
        True quantile mapping: sort LLM and human scores independently,
        then pair by rank. This ensures monotonicity even with noisy pairings.
        """
        llm_sorted = sorted([p[0] for p in paired])
        human_sorted = sorted([p[1] for p in paired])
        # Add boundary points: LLM 1→human min, LLM 10→human max
        llm_vals = [1.0] + llm_sorted + [10.0]
        human_vals = [min(human_sorted)] + human_sorted + [max(human_sorted)]
        return llm_vals, human_vals
    
    def _apply_quantile_map(raw_score, map_x, map_y):
        """Apply piecewise linear mapping. Clamp to [1, 10]."""
        if raw_score <= map_x[0]:
            return max(1.0, min(10.0, map_y[0]))
        if raw_score >= map_x[-1]:
            return max(1.0, min(10.0, map_y[-1]))
        # Find interval
        for i in range(len(map_x) - 1):
            if map_x[i] <= raw_score <= map_x[i + 1]:
                # Linear interpolation
                if map_x[i + 1] == map_x[i]:
                    return max(1.0, min(10.0, map_y[i]))
                t = (raw_score - map_x[i]) / (map_x[i + 1] - map_x[i])
                mapped = map_y[i] + t * (map_y[i + 1] - map_y[i])
                return max(1.0, min(10.0, round(mapped, 1)))
        return max(1.0, min(10.0, raw_score))
    
    # v8.15: quantile_map dead code removed (results were never used in calibration)
    
    # v8.15: Load OLS calibration params (replaces v8.12 WLS)
    # OLS fitted on 47ch with temp=0.0+prev_context (matches production)
    # GLM found WLS(v8.12) fails on temp=0.0 data due to opposite GLM bias direction
    _ols_path = PROJECT_ROOT / "data" / "reports" / "末世" / "calibration" / "ols_calibration_v815.json"
    _wls_path = PROJECT_ROOT / "data" / "reports" / "末世" / "calibration" / "wls_calibration_v812.json"
    wls_params = None
    # Try OLS(v8.15) first, fallback to WLS(v8.12)
    _calib_path = _ols_path if _ols_path.exists() else (_wls_path if _wls_path.exists() else None)
    if _calib_path:
        try:
            with open(_calib_path, "r", encoding="utf-8") as _wf:
                _wls_data = json.load(_wf)
            # OLS(v8.15) has direct intercept/slope; WLS(v8.12) has nested pure_human_ols/mixed_ols
            if "intensity" in _wls_data and "intercept" in _wls_data["intensity"]:
                # OLS(v8.15) format
                wls_params = {
                    "intensity": {"intercept": _wls_data["intensity"]["intercept"], "slope": _wls_data["intensity"]["slope"]},
                    "retention": {"intercept": _wls_data["retention"]["intercept"], "slope": _wls_data["retention"]["slope"]},
                }
            else:
                # WLS(v8.12) format (fallback)
                _pure = _wls_data.get("pure_human_ols", {})
                _mixed = _wls_data.get("mixed_ols", {})
                wls_params = {
                    "intensity": {
                        "intercept": _pure.get("intensity", {}).get("intercept", _mixed.get("intensity", {}).get("intercept", 1.928)),
                        "slope": _pure.get("intensity", {}).get("slope", _mixed.get("intensity", {}).get("slope", 0.496)),
                    },
                    "retention": {
                        "intercept": _pure.get("retention", {}).get("intercept", _mixed.get("retention", {}).get("intercept", 2.699)),
                        "slope": _pure.get("retention", {}).get("slope", _mixed.get("retention", {}).get("slope", 0.488)),
                    },
                }
            logger.info("[O8] Calib params: i=%.3f+%.3f*x, r=%.3f+%.3f*x (%s)",
                       wls_params["intensity"]["intercept"], wls_params["intensity"]["slope"],
                       wls_params["retention"]["intercept"], wls_params["retention"]["slope"],
                       _calib_path.name)
        except Exception as e:
            logger.warning("[O8] Calib load failed: %s, fallback to median offset", e)

    # Compute median offset as fallback
    int_offsets = [h - l for l, h in paired_int]
    ret_offsets = [h - l for l, h in paired_ret]
    int_offset = round(statistics.median(int_offsets), 1)
    ret_offset = round(statistics.median(ret_offsets), 1)
    SHRINKAGE = 0.6 if len(paired_int) >= 20 else 0.4
    
    # v21: Smart-skip — 每个维度独立判断（与e2e_verify.py一致）
    SKIP_THRESHOLD = 0.5
    int_skip = abs(int_offset) < SKIP_THRESHOLD
    ret_skip = abs(ret_offset) < SKIP_THRESHOLD
    if int_skip and ret_skip:
        logger.info("[O8] Smart-skip: both |offset| i%+.1f/r%+.1f < %.1f, skipping calibration", int_offset, ret_offset, SKIP_THRESHOLD)
        return {"intensity_offset": int_offset, "retention_offset": ret_offset,
                "n_golden": len(paired_int), "method": "smart_skip", "skipped": True}
    if int_skip:
        logger.info("[O8] Smart-skip: intensity |offset| %+.1f < %.1f, skipping intensity calibration", int_offset, SKIP_THRESHOLD)
    if ret_skip:
        logger.info("[O8] Smart-skip: retention |offset| %+.1f < %.1f, skipping retention calibration", ret_offset, SKIP_THRESHOLD)
    
    # v21: Shrinkage factor — n>=20用0.6, 否则0.4
    SHRINKAGE = 0.6 if len(paired_int) >= 20 else 0.4
    
    # Apply calibration to all rows
    calibrated = 0
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys()) if rows else []
    
    for row in rows:
        old_int = float(row.get("llm_intensity", 5))
        old_ret = float(row.get("llm_retention", 5))
        if wls_params:
            new_int = round(max(1.0, min(10.0, wls_params["intensity"]["intercept"] + wls_params["intensity"]["slope"] * old_int)), 1)
            new_ret = round(max(1.0, min(10.0, wls_params["retention"]["intercept"] + wls_params["retention"]["slope"] * old_ret)), 1)
        else:
            new_int = round(max(1.0, min(10.0, old_int + SHRINKAGE * int_offset)), 1) if not int_skip else old_int
            new_ret = round(max(1.0, min(10.0, old_ret + SHRINKAGE * ret_offset)), 1) if not ret_skip else old_ret
        row["llm_intensity_calibrated"] = str(new_int)
        row["llm_retention_calibrated"] = str(new_ret)
        row["llm_calibration_offset"] = f"i{new_int-old_int:+.1f},r{new_ret-old_ret:+.1f}"
        calibrated += 1
    
    for _col in ["llm_intensity_calibrated", "llm_retention_calibrated", "llm_calibration_offset"]:
        if _col not in fieldnames:
            fieldnames.append(_col)
    
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
    
    _method = "wls" if wls_params else "median_offset_shrinkage"
    logger.info("[O8] %s calibration: %d chapters (n_golden=%d) — original values preserved",
               _method, calibrated, len(paired_int))
    return {"intensity_offset": int_offset, "retention_offset": ret_offset,
            "n_golden": len(paired_int), "method": _method,
            "wls_params": wls_params, "overwrote_original": False}


# ── v22.1 P1: Bootstrap Ranking Stability ──
# 参考: Berg-Kirkpatrick et al. (2012) EMNLP, Dror et al. (2018) ACL
# Bootstrap重采样评估排名稳定性，量化每本书排名的不确定度
# 输出: 每本书的rank_95ci + stability标签(stable/unstable/volatile)

def bootstrap_rank_stability(genre="末世", n_bootstrap=1000):
    """v22.1 P1: Bootstrap ranking stability assessment.
    
    For each book, resample chapter scores with replacement n_bootstrap times,
    compute mean intensity per resample, then calculate:
    - 95% CI for mean intensity
    - 95% CI for rank position (rank 1 = best)
    
    Outputs JSON file with stability metrics + prints summary table.
    """
    import random
    
    llm_path = _llm_dir(genre)
    books = {}
    
    # Load all book CSVs
    for csv_file in llm_path.glob("*_llm.csv"):
        book_name = csv_file.stem.replace("_llm", "")
        try:
            with open(csv_file, 'r', encoding='utf-8-sig') as f:
                rows = list(csv.DictReader(f))
            scores = [float(r.get("llm_intensity", 5)) for r in rows if r.get("llm_intensity")]
            if len(scores) >= 5:
                books[book_name] = scores
        except Exception:
            continue
    
    if len(books) < 2:
        logger.info("[BOOTSTRAP] Need >=2 books with >=5 chapters each, found %d, skipping", len(books))
        return None
    
    book_names = list(books.keys())
    
    # Storage for bootstrap results
    boot_means = {name: [] for name in book_names}
    boot_ranks = {name: [] for name in book_names}
    
    random.seed(42)
    for _ in range(n_bootstrap):
        means_this_round = {}
        for name in book_names:
            scores = books[name]
            resampled = [random.choice(scores) for _ in range(len(scores))]
            means_this_round[name] = statistics.mean(resampled)
        
        # Rank this round (higher score = better, rank 1 = best)
        sorted_books = sorted(means_this_round.items(), key=lambda x: -x[1])
        for rank, (name, _) in enumerate(sorted_books, 1):
            boot_ranks[name].append(rank)
            boot_means[name].append(means_this_round[name])
    
    # Compute results
    results = []
    for name in book_names:
        means_sorted = sorted(boot_means[name])
        ranks_sorted = sorted(boot_ranks[name])
        mean_ci_low = means_sorted[int(0.025 * n_bootstrap)]
        mean_ci_high = means_sorted[int(0.975 * n_bootstrap)]
        rank_ci_low = ranks_sorted[int(0.025 * n_bootstrap)]
        rank_ci_high = ranks_sorted[int(0.975 * n_bootstrap)]
        rank_median = int(statistics.median(ranks_sorted))
        
        # Stability label based on rank CI width
        rank_range = rank_ci_high - rank_ci_low
        if rank_range <= 2:
            stability = "stable"
        elif rank_range <= 5:
            stability = "unstable"
        else:
            stability = "volatile"
        
        results.append({
            "book": name,
            "n_chapters": len(books[name]),
            "mean_intensity": round(statistics.mean(books[name]), 2),
            "mean_ci_95": [round(mean_ci_low, 2), round(mean_ci_high, 2)],
            "rank_median": rank_median,
            "rank_ci_95": [rank_ci_low, rank_ci_high],
            "stability": stability,
        })
    
    results.sort(key=lambda x: x["rank_median"])
    
    # Save JSON
    out_path = llm_path / "bootstrap_rank_stability.json"
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    # Print summary table
    logger.info("[BOOTSTRAP] Rank stability (n=%d, %d books):", n_bootstrap, len(books))
    for r in results:
        book_short = r["book"][:34]
        logger.info("  #%d %s mean=%.1f CI=[%.1f-%.1f] rank_CI=[%d-%d] n=%d stability=%s",
                    r['rank_median'], book_short,
                    r['mean_intensity'], r['mean_ci_95'][0], r['mean_ci_95'][1],
                    r['rank_ci_95'][0], r['rank_ci_95'][1],
                    r['n_chapters'], r['stability'])
    
    return out_path


def main():
    if not check_server():
        logger.error("LLM server not running at %s", _LLAMA_BASE)
        logger.error("  Start with: scripts\\start_model.bat")
        return

    # Parse args
    book_filter = None
    max_ch = 30  # default: 30 chapters per book for speed
    genre = "末世"  # default from config convention
    sc_samples = 1  # v8: Self-Consistency samples (1=single, 3=recommended)
    tier_boost = False  # v22: auto-boost S/A books to 50ch + sc=3
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--book" and i < len(sys.argv) - 1:
            book_filter = sys.argv[i + 1]
        if arg == "--max" and i < len(sys.argv) - 1:
            max_ch = int(sys.argv[i + 1])
        if arg == "--genre" and i < len(sys.argv) - 1:
            genre = sys.argv[i + 1]
        if arg == "--sc" and i < len(sys.argv) - 1:
            sc_samples = int(sys.argv[i + 1])
        if arg == "--tier-boost":
            tier_boost = True

    with open(INDEX_PATH, 'r', encoding='utf-8') as f:
        index = json.load(f)
    novels = index["genres"].get(genre, {}).get("novels", [])
    if not novels:
        logger.error("No %s novels in index", genre)
        return

    if tier_boost:
        logger.info("[v22.1] Tier-boost mode: S/A→50ch+sc3, B→30ch+sc1, C→30ch+sc1")

    for novel in novels:
        txt_file = novel.get("file", "")
        if book_filter and book_filter not in txt_file:
            continue
        txt_path = None
        for fp in NOVELS_DIR.glob("**/*.txt"):
            if fp.name == txt_file:
                txt_path = fp
                break
        if not txt_path:
            logger.info("[SKIP] TXT not found: %s (searched in %s)", txt_file, NOVELS_DIR)
            continue

        csv_name = novel.get("rhythm_csv", "")
        csv_path = _rhythm_dir(genre) / csv_name if csv_name else None

        # v22: Tier-based sampling configuration
        book_max_ch = max_ch
        book_sc = sc_samples
        if tier_boost:
            tier = _get_book_tier(txt_file)
            if tier and tier in _TIER_SAMPLING:
                book_max_ch = _TIER_SAMPLING[tier]["max_ch"]
                book_sc = _TIER_SAMPLING[tier]["sc_samples"]
                logger.info("\n[BOOK] %s (tier=%s → %dch, sc=%d)", txt_file[:40], tier, book_max_ch, book_sc)
            else:
                logger.info("\n[BOOK] %s (tier=unknown → %dch, sc=%d)", txt_file[:40], book_max_ch, book_sc)
        else:
            logger.info("\n[BOOK] %s", txt_file[:40])

        batch_book(txt_path, csv_path, book_max_ch, book_sc)

    logger.info("\n[DONE] LLM scores saved to %s", _llm_dir(genre))

    # v22.1 P1: Bootstrap ranking stability assessment
    try:
        bootstrap_rank_stability(genre=genre)
    except Exception as e:
        logger.warning("[BOOTSTRAP] Skipped: %s", e)


if __name__ == "__main__":
    main()
