# -*- coding: utf-8 -*-
"""
test_style_dna.py — Style DNA (P1.3) 单元测试
================================================
测试覆盖:
  1. extract_dna: 五维提取基本功能
  2. D1 句法指标 (句长/对话/描写/短句)
  3. D2 词汇指标 (成语/网络用语/AI指纹/叠词)
  4. D3 节奏指标 (段落长度/场景切换)
  5. D4 幽默指标 (反讽/自嘲/黑色幽默)
  6. D5 视角指标 (人称/内心独白/全知)
  7. build_dna_baseline: 多章聚合
  8. compare_dna: 偏离检测
  9. dna_as_s3_check: S3 集成
  10. enhance_style_profile_with_dna: Part E 增强
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# 测试用文本
# 高对话占比的文本
DIALOGUE_HEAVY = """
"你确定要这么做？"林凡皱眉道。
"当然，我已经计划了很久。"苏雪笑了笑，"难道你怕了？"
"我怕？笑话。"林凡冷哼一声，"我只是觉得时机未到。"
"时机？"苏雪摇头，"如果一直等时机，什么都做不成。"
"你说得也有道理。"林凡沉默片刻，"那就按你说的办吧。"
"这才对嘛！"苏雪拍了拍他的肩膀。
"""

# 环境描写为主的文本
DESCRIPTION_HEAVY = """
阳光透过薄雾洒落下来，照亮了整片山谷。远处的山峰在晨曦中若隐若现，空气中弥漫着青草和泥土的芬芳。
天空湛蓝如洗，几朵白云懒洋洋地飘着。山间的溪流潺潺作响，清澈见底，偶尔有几条小鱼在水中翻腾。
森林深处，古木参天，枝叶繁茂。阳光被层层叠叠的树叶过滤，在地上投下斑驳的光影。
花丛中，蝴蝶翩翩起舞，蜜蜂嗡嗡地忙碌着。微风拂过，花瓣纷纷扬扬地飘落。
夜晚降临，月光如水般倾泻而下。繁星点点，银河横贯天际。
"""

# 幽默风格文本
HUMOR_TEXT = """
"呵呵，你说你是天才？"林凡嗤笑道，"鬼才信。"
"好吧好吧，我承认我只是个普通人。"他苦笑着摇头，自己不过是个倒霉蛋罢了。
"这都不死？主角光环也太强了吧。"旁边的王虎吐槽道。
"命硬没办法。"林凡耸耸肩，"阎王爷都不收我。"
"你可真是好样的。"苏雪翻了个白眼，"说得跟真的似的。"
"我自嘲还不行吗？"林凡无奈地叹了口气，"谁让自己技不如人呢。"
"""

# 第一人称内心独白文本
FIRST_PERSON_TEXT = """
我站在悬崖边，心中涌起一股莫名的恐惧。心想，如果就这样跳下去，会不会是一种解脱？
我不禁想，这些年到底是为了什么？脑海闪过一个念头，或许我一直在逃避。
我在想，如果当初做了不同的选择，一切会不会不一样？
内心深处，我知道答案是否定的。命运的齿轮早已转动，谁也无法阻止。
直觉告诉我，前方还有更大的考验在等着我。我握紧了拳头，深吸一口气。
"""

# AI 指纹词密集的文本
AI_HEAVY = """
他不由地停下了脚步，此刻空气中弥漫着一股诡异的气息。他不禁深吸一口气，眼中闪过一抹惊讶。
旋即，他便恢复了平静。极为强大的气场从四面八方涌来，无比惊人。
与此同时，远处传来一声巨响。显而易见，战斗已经开始了。
此外，值得注意的是，这场战斗的结果将影响整个局势。
从而，他不得不做出选择。首先，他需要确认敌人的位置。其次，制定作战计划。最后，执行。
总而言之，这是一场不可避免的战斗。不可否认，他的实力还有待提升。
"""


def test_extract_dna_basic():
    """1. extract_dna 基本功能"""
    from xiaoshuo.pipeline.style_dna import extract_dna, StyleDNA
    text = (
        "这是一段测试文本，用于验证风格DNA提取器的基本功能。"
        "林凡走了进来，看了看四周。他心中暗想，这里到底有什么秘密？"
        "空气中弥漫着一股诡异的气息。他深吸一口气，决定一探究竟。"
        "远处传来一声巨响，打破了宁静。显然，事情并不简单。"
        "他握紧拳头，目光变得坚定。不管前方有什么，他都不会退缩。"
    )
    dna = extract_dna(text)
    assert isinstance(dna, StyleDNA)
    assert dna.total_chars >= 50
    assert dna.sentence_count > 0
    assert dna.paragraph_count > 0
    print("[PASS] test_extract_dna_basic")


def test_d1_syntax():
    """2. D1 句法指标"""
    from xiaoshuo.pipeline.style_dna import extract_dna
    # 高对话
    dna = extract_dna(DIALOGUE_HEAVY)
    assert dna.dialogue_ratio > 0.3, f"对话占比应>0.3, got {dna.dialogue_ratio}"
    assert dna.avg_sentence_length > 0
    assert 0 <= dna.short_sentence_ratio <= 1

    # 高描写
    dna2 = extract_dna(DESCRIPTION_HEAVY)
    assert dna2.description_density > 0, "描写密度应>0"
    assert dna2.dialogue_ratio < 0.1, f"描写文本对话占比应很低, got {dna2.dialogue_ratio}"

    # 对话 > 描写的对话占比
    assert dna.dialogue_ratio > dna2.dialogue_ratio
    print("[PASS] test_d1_syntax")


def test_d2_vocabulary():
    """3. D2 词汇指标"""
    from xiaoshuo.pipeline.style_dna import extract_dna
    # AI 指纹词密集
    dna = extract_dna(AI_HEAVY)
    assert dna.ai_fingerprint_density > 2, \
        f"AI指纹词密度应>2/千字, got {dna.ai_fingerprint_density}"
    assert len(dna.top_words) > 0, "应有高频词"
    assert dna.vocab_richness > 0

    # 正常文本 AI 指纹应较低
    dna2 = extract_dna(DIALOGUE_HEAVY)
    assert dna2.ai_fingerprint_density < dna.ai_fingerprint_density, \
        "正常文本AI指纹应低于AI密集文本"
    print("[PASS] test_d2_vocabulary")


def test_d3_rhythm():
    """4. D3 节奏指标"""
    from xiaoshuo.pipeline.style_dna import extract_dna
    # 短段落多的文本 (>=50中文字符)
    text = (
        "第一段内容这里写一些测试文字用于检测段落长度。\n\n"
        "第二段内容继续写测试文字验证段落分割功能。\n\n"
        "第三段内容还有更多测试文字确保足够长度。\n\n"
        "第四段内容最后一段测试文字终于够了。"
    )
    dna = extract_dna(text)
    assert dna.paragraph_count >= 4
    assert dna.avg_paragraph_length < 30  # 每段较短

    # 场景切换 (>=50中文字符)
    text2 = (
        "场景一开始，林凡走进了大厅，四周一片寂静。"
        "与此同时，另一边发生了事情，苏雪正在书房查阅资料。"
        "就在这时，第三件事发生了，远处传来爆炸声。"
        "显然，今晚不会平静。所有人都被惊动了。"
    )
    dna2 = extract_dna(text2)
    assert dna2.scene_switch_count >= 2, \
        f"应检测到>=2次场景切换, got {dna2.scene_switch_count}"
    print("[PASS] test_d3_rhythm")


def test_d4_humor():
    """5. D4 幽默指标"""
    from xiaoshuo.pipeline.style_dna import extract_dna
    dna = extract_dna(HUMOR_TEXT)
    assert dna.irony_density > 0, "应有反讽标记"
    assert dna.self_deprecation_density > 0, "应有自嘲标记"
    assert dna.humor_total > 0, "幽默总分应>0"

    # 无幽默文本
    dna2 = extract_dna(DESCRIPTION_HEAVY)
    assert dna2.humor_total < dna.humor_total, "描写文本幽默分应低于幽默文本"
    print("[PASS] test_d4_humor")


def test_d5_perspective():
    """6. D5 视角指标"""
    from xiaoshuo.pipeline.style_dna import extract_dna
    # 第一人称
    dna = extract_dna(FIRST_PERSON_TEXT)
    assert dna.perspective_type in ("first", "mixed"), \
        f"第一人称文本应被识别为first/mixed, got {dna.perspective_type}"
    assert dna.first_person_ratio > 0.3, \
        f"第一人称占比应>0.3, got {dna.first_person_ratio}"
    assert dna.inner_monologue_density > 0, "应有内心独白标记"

    # 第三人称 (对话文本)
    dna2 = extract_dna(DIALOGUE_HEAVY)
    assert dna2.perspective_type == "third", \
        f"对话文本应被识别为third, got {dna2.perspective_type}"
    assert dna2.third_person_ratio > dna2.first_person_ratio
    print("[PASS] test_d5_perspective")


def test_build_dna_baseline():
    """7. build_dna_baseline 多章聚合"""
    from xiaoshuo.pipeline.style_dna import build_dna_baseline, StyleDNA
    chapters = [DIALOGUE_HEAVY, HUMOR_TEXT, FIRST_PERSON_TEXT, DESCRIPTION_HEAVY]
    baseline = build_dna_baseline(chapters)
    assert isinstance(baseline, StyleDNA)
    assert baseline.total_chars > 0
    assert baseline.paragraph_count > 0
    assert len(baseline.top_words) > 0

    # 单章也能构建
    single = build_dna_baseline([DIALOGUE_HEAVY])
    assert single.total_chars > 0

    # 空列表
    empty = build_dna_baseline([])
    assert empty.total_chars == 0
    print("[PASS] test_build_dna_baseline")


def test_compare_dna():
    """8. compare_dna 偏离检测"""
    from xiaoshuo.pipeline.style_dna import extract_dna, build_dna_baseline, compare_dna
    # 建立基线 (对话风格)
    baseline = build_dna_baseline([DIALOGUE_HEAVY, HUMOR_TEXT])

    # 与自身比较 → 高一致性
    current = extract_dna(DIALOGUE_HEAVY)
    dev = compare_dna(baseline, current)
    assert dev.consistency_score > 0
    assert isinstance(dev.summary, str)
    assert isinstance(dev.top_issues, list)

    # AI密集文本 vs 正常基线 → 低一致性
    ai_dna = extract_dna(AI_HEAVY)
    dev2 = compare_dna(baseline, ai_dna)
    # AI文本应比对话文本偏离更大
    assert dev2.consistency_score < dev.consistency_score, \
        f"AI文本一致性应低于对话文本: {dev2.consistency_score} vs {dev.consistency_score}"

    # 有问题检测
    assert dev2.has_issues
    print("[PASS] test_compare_dna")


def test_dna_as_s3_check():
    """9. dna_as_s3_check S3 集成"""
    from xiaoshuo.pipeline.style_dna import dna_as_s3_check, build_dna_baseline
    # 无基线
    result = dna_as_s3_check(DIALOGUE_HEAVY, baseline_dna=None)
    assert result["should_warn"] == False
    assert result["grade"] == "N/A"

    # 有基线
    baseline = build_dna_baseline([DIALOGUE_HEAVY, HUMOR_TEXT])
    result2 = dna_as_s3_check(DIALOGUE_HEAVY, baseline_dna=baseline)
    assert "consistency_score" in result2
    assert "grade" in result2
    assert "dimension_deviations" in result2
    assert "top_issues" in result2
    assert isinstance(result2["dimension_deviations"], dict)
    assert isinstance(result2["top_issues"], list)
    print("[PASS] test_dna_as_s3_check")


def test_enhance_style_profile():
    """10. enhance_style_profile_with_dna Part E 增强"""
    from xiaoshuo.pipeline.style_dna import enhance_style_profile_with_dna

    # 模拟现有风格画像
    profile = {
        "version": "1.0",
        "chapter_count": 5,
        "maturity": "building",
        "style_hints": ["作者对话偏好: high"],
    }

    chapters = [DIALOGUE_HEAVY, HUMOR_TEXT, FIRST_PERSON_TEXT]
    enhanced = enhance_style_profile_with_dna(profile, chapters)

    assert "style_dna" in enhanced
    assert "style_dna_hints" in enhanced
    assert "style_dna_maturity" in enhanced
    assert enhanced["style_dna"] is not None
    assert len(enhanced["style_dna_hints"]) > 0
    assert enhanced["style_dna_maturity"] in ("seed", "building", "mature", "rich")

    # 空章节
    enhanced_empty = enhance_style_profile_with_dna(profile, [])
    assert enhanced_empty["style_dna"] is None
    assert enhanced_empty["style_dna_hints"] == []
    print("[PASS] test_enhance_style_profile")


def test_to_dict_from_dict():
    """额外: 序列化/反序列化"""
    from xiaoshuo.pipeline.style_dna import extract_dna, StyleDNA
    dna = extract_dna(HUMOR_TEXT)
    d = dna.to_dict()
    assert isinstance(d, dict)
    assert "avg_sentence_length" in d
    assert "top_words" in d

    dna2 = StyleDNA.from_dict(d)
    assert dna2.avg_sentence_length == dna.avg_sentence_length
    assert dna2.total_chars == dna.total_chars
    print("[PASS] test_to_dict_from_dict")


if __name__ == "__main__":
    test_extract_dna_basic()
    test_d1_syntax()
    test_d2_vocabulary()
    test_d3_rhythm()
    test_d4_humor()
    test_d5_perspective()
    test_build_dna_baseline()
    test_compare_dna()
    test_dna_as_s3_check()
    test_enhance_style_profile()
    test_to_dict_from_dict()
    print("\n[ALL PASS] Style DNA (P1.3) 11/11 tests passed!")
