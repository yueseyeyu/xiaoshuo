#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ai_flavor_detector.py v1 — AI写作味检测器
===========================================
逆向拆解"去AI味指令"为检测规则，检测正文是否存在AI写作痕迹。

检测维度：
  负面规则（禁止项）:
    - 禁用过渡词: "众所周知"、"总而言之"等
    - 禁用外貌描写: "他有一双XX的眼睛"等模板化描写
  正面评分（应该做的）:
    - 对话口语化: 短句、语气词、语病
    - 感官细节密度: 动作、气味、触感描写
    - 情绪克制度: 避免直白抒情
    - 生活化闲笔: 无意义日常对话
    - 句式多样性: 非重复句式

配置: config.yaml analysis.ai_flavor_detection
用法: python analysis/ai_flavor_detector.py --text <file> [--json] [--llm]
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


# ── 正面规则：加分项评分 ──

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