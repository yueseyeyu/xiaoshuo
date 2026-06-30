# -*- coding: utf-8 -*-
"""
test_p2_modules.py — P2 四模块单元测试
========================================
测试覆盖:
  P2.1 红线原则库 (red_line_principles.py)
    1. 默认原则加载
    2. 章节检测 (关键词触发)
    3. 正则模式检测
    4. 添加/删除/启用禁用
    5. 打破确认
    6. Prompt 集成

  P2.2 S3 风格一致性 (style_consistency_lens.py)
    7. 无基线检测 (仅 AI 指纹)
    8. 有基线全维度检测
    9. 评级计算
    10. S3 集成接口

  P2.3 Context Budget (context_budget.py)
    11. 四层设置
    12. 动态预算调整
    13. 裁剪
    14. writing_context 批量加载

  P2.4 大纲偏差检测 (outline_deviation.py)
    15. 事件覆盖
    16. 人物出场
    17. 章末钩子
    18. 情绪检测
    19. S3 集成接口
"""

import gc
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

_TMP_DIRS: list[Path] = []


def _cleanup():
    gc.collect()
    for d in _TMP_DIRS:
        if d.exists():
            import shutil
            try:
                shutil.rmtree(d, ignore_errors=True)
            except PermissionError:
                pass
    _TMP_DIRS.clear()


# ════════════════════════════════════════
# P2.1 红线原则库
# ════════════════════════════════════════

def _make_checker():
    """创建使用临时目录的 RedLineChecker。"""
    import xiaoshuo.pipeline.red_line_principles as rl_mod

    tmp_dir = Path(tempfile.mkdtemp(prefix="rl_test_"))
    _TMP_DIRS.append(tmp_dir)
    rl_mod.RL_DIR = tmp_dir
    rl_mod.RL_PATH = tmp_dir / "principles.json"
    rl_mod._checker_instance = None
    return rl_mod.RedLineChecker()


def test_red_line_default():
    """1. 默认原则加载"""
    kb = _make_checker()
    try:
        principles = kb.list_principles()
        assert len(principles) >= 6, f"应有至少6条默认原则, got {len(principles)}"

        # 检查类别分布
        stats = kb.stats()
        assert "character" in stats["category_dist"]
        assert "style" in stats["category_dist"]
        assert stats["total"] == len(principles)
        print("[PASS] test_red_line_default")
    finally:
        _cleanup()


def test_red_line_detection():
    """2. 关键词触发检测"""
    checker = _make_checker()
    try:
        # 触发"主角不能跪"红线
        text = (
            "林凡面对强大的敌人，心中生出恐惧。"
            "他跪倒在地，磕头求饶，希望对方能放过自己。"
            "旁边的苏雪看到这一幕，心中满是失望。"
        )
        result = checker.check_chapter(text, chapter_num=1)
        assert result.count > 0, "应检测到红线违规"
        assert result.has_critical, "'跪倒在地'+'磕头'+'求饶' 应触发 critical"

        # 检查匹配到的是 rl-001
        violations = [v for v in result.violations if v.principle.id == "rl-001"]
        assert len(violations) >= 2, f"应匹配到 rl-001 至少2次 (跪倒+磕头+求饶)"

        # 正常文本不触发
        text2 = (
            "林凡面对强大的敌人，握紧了拳头。"
            "即使实力差距巨大，他也绝不退缩。"
            "苏雪在一旁为他加油打气。"
        )
        result2 = checker.check_chapter(text2, chapter_num=2)
        # 可能触发 AI 指纹等 warning, 但不应有 critical
        assert not result2.has_critical, "正常文本不应触发 critical 红线"
        print("[PASS] test_red_line_detection")
    finally:
        _cleanup()


def test_red_line_pattern():
    """3. 正则模式检测"""
    checker = _make_checker()
    try:
        # rl-005 有正则模式: r"突然.{0,5}来到了"
        text = (
            "林凡正在修炼，突然他来到了一个陌生的地方。"
            "四周一片漆黑，什么都看不清楚。"
        )
        result = checker.check_chapter(text, chapter_num=3)
        pattern_violations = [v for v in result.violations if v.principle.id == "rl-005"]
        assert len(pattern_violations) >= 1, "应通过正则模式检测到'突然...来到了'"
        print("[PASS] test_red_line_pattern")
    finally:
        _cleanup()


def test_red_line_management():
    """4. 添加/删除/启用禁用"""
    checker = _make_checker()
    try:
        original_count = len(checker.list_principles())

        # 添加
        pid = checker.add_principle(
            category="character",
            rule="测试红线: 不能出现特定词",
            keywords=["测试禁忌词"],
            severity="serious",
            alternative="用其他表达替代",
        )
        assert pid, "应返回原则 ID"
        assert len(checker.list_principles()) == original_count + 1

        # 禁用
        ok = checker.toggle_principle(pid, enabled=False)
        assert ok
        p = checker.get_by_id(pid)
        assert not p.enabled

        # 禁用后不检测
        result = checker.check_chapter("这里有测试禁忌词。", chapter_num=1)
        violations = [v for v in result.violations if v.principle.id == pid]
        assert len(violations) == 0, "禁用的原则不应触发"

        # 重新启用
        checker.toggle_principle(pid, enabled=True)
        result2 = checker.check_chapter("这里有测试禁忌词。", chapter_num=1)
        violations2 = [v for v in result2.violations if v.principle.id == pid]
        assert len(violations2) >= 1, "启用后应触发"

        # 删除
        ok2 = checker.remove_principle(pid)
        assert ok2
        assert len(checker.list_principles()) == original_count
        print("[PASS] test_red_line_management")
    finally:
        _cleanup()


def test_red_line_override():
    """5. 打破确认"""
    checker = _make_checker()
    try:
        info = checker.request_override("rl-001", reason="剧情需要主角暂时示弱")
        assert info["principle_id"] == "rl-001"
        assert info["confirmed"] is False, "应需要外部确认"
        assert "打破" in info["warning"]
        assert info["severity"] == "critical"

        p = checker.get_by_id("rl-001")
        assert p.override_count == 1, "override_count 应 +1"
        print("[PASS] test_red_line_override")
    finally:
        _cleanup()


def test_red_line_prompt():
    """6. Prompt 集成"""
    checker = _make_checker()
    try:
        text = checker.format_for_prompt(max_entries=3)
        assert "## 红线原则提醒" in text
        assert "CRITICAL" in text or "WARNING" in text

        ctx = checker.format_for_writing_context()
        assert "prompt_text" in ctx
        assert "total_principles" in ctx
        assert "critical_count" in ctx
        assert ctx["critical_count"] >= 1, "应有至少1条 critical"
        print("[PASS] test_red_line_prompt")
    finally:
        _cleanup()


# ════════════════════════════════════════
# P2.2 S3 风格一致性
# ════════════════════════════════════════

DIALOGUE_TEXT = """
"你确定要这么做？"林凡皱眉道。
"当然，我已经计划了很久。"苏雪笑了笑，"难道你怕了？"
"我怕？笑话。"林凡冷哼一声，"我只是觉得时机未到。"
"时机？"苏雪摇头，"如果一直等时机，什么都做不成。"
"你说得也有道理。"林凡沉默片刻，"那就按你说的办吧。"
"这才对嘛！"苏雪拍了拍他的肩膀。
"""

AI_HEAVY_TEXT = """
他不由地停下了脚步，此刻空气中弥漫着一股诡异的气息。他不禁深吸一口气，眼中闪过一抹惊讶。
旋即，他便恢复了平静。极为强大的气场从四面八方涌来，无比惊人。
与此同时，远处传来一声巨响。显而易见，战斗已经开始了。
此外，值得注意的是，这场战斗的结果将影响整个局势。
从而，他不得不做出选择。首先，他需要确认敌人的位置。其次，制定作战计划。最后，执行。
总而言之，这是一场不可避免的战斗。不可否认，他的实力还有待提升。
"""


def test_style_consistency_no_baseline():
    """7. 无基线检测 (仅 AI 指纹)"""
    from xiaoshuo.pipeline.s3_extensions.style_consistency_lens import (
        StyleConsistencyLens
    )
    lens = StyleConsistencyLens()

    # AI 指纹密集
    result = lens.check(AI_HEAVY_TEXT, baseline_dna=None)
    assert result.issue_count > 0, "AI密集文本应检测到问题"
    assert result.has_issues

    # 正常文本
    result2 = lens.check(DIALOGUE_TEXT, baseline_dna=None)
    # 对话文本 AI 指纹较低
    ai_issues = [i for i in result2.issues if i.dimension == "ai_fingerprint"]
    # 可能触发也可能不触发, 取决于对话文本中 AI 指纹词数量
    print("[PASS] test_style_consistency_no_baseline")


def test_style_consistency_with_baseline():
    """8. 有基线全维度检测"""
    from xiaoshuo.pipeline.s3_extensions.style_consistency_lens import (
        StyleConsistencyLens
    )
    from xiaoshuo.pipeline.style_dna import build_dna_baseline

    lens = StyleConsistencyLens()

    # 建立对话风格基线
    baseline = build_dna_baseline([DIALOGUE_TEXT])

    # 对话文本 vs 对话基线 → 高一致性
    result = lens.check(DIALOGUE_TEXT, baseline_dna=baseline)
    assert isinstance(result.consistency_score, float)
    assert isinstance(result.grade, str)

    # AI 密集文本 vs 对话基线 → 低一致性
    result2 = lens.check(AI_HEAVY_TEXT, baseline_dna=baseline)
    assert result2.has_issues, "AI文本应检测到风格偏离"
    assert result2.consistency_score < result.consistency_score, \
        f"AI文本一致性应低于对话文本: {result2.consistency_score} vs {result.consistency_score}"
    print("[PASS] test_style_consistency_with_baseline")


def test_style_consistency_grade():
    """9. 评级计算"""
    from xiaoshuo.pipeline.s3_extensions.style_consistency_lens import (
        StyleConsistencyLens
    )
    from xiaoshuo.pipeline.style_dna import build_dna_baseline

    lens = StyleConsistencyLens()
    baseline = build_dna_baseline([DIALOGUE_TEXT])

    # 高一致性 → A/B
    result = lens.check(DIALOGUE_TEXT, baseline_dna=baseline)
    assert result.grade in ("A", "B", "C", "D", "F")

    # 低一致性 → D/F
    result2 = lens.check(AI_HEAVY_TEXT, baseline_dna=baseline)
    assert result2.grade in ("A", "B", "C", "D", "F")
    assert ord(result2.grade) >= ord(result.grade), \
        f"AI文本评级应更差: {result2.grade} vs {result.grade}"

    # 无问题 → A
    result3 = lens.check(DIALOGUE_TEXT, baseline_dna=baseline)
    if not result3.has_issues:
        assert result3.grade == "A"
    print("[PASS] test_style_consistency_grade")


def test_style_consistency_s3_interface():
    """10. S3 集成接口"""
    from xiaoshuo.pipeline.s3_extensions.style_consistency_lens import (
        style_consistency_as_s3_check
    )
    result = style_consistency_as_s3_check(AI_HEAVY_TEXT, baseline_dna=None)
    assert result["dimension"] == "style_consistency"
    assert "grade" in result
    assert "consistency_score" in result
    assert "has_issues" in result
    assert "summary" in result
    assert isinstance(result["top_issues"], list)
    print("[PASS] test_style_consistency_s3_interface")


# ════════════════════════════════════════
# P2.3 Context Budget
# ════════════════════════════════════════

def test_context_budget_basic():
    """11. 四层设置"""
    from xiaoshuo.pipeline.context_budget import ContextBudget

    budget = ContextBudget(total_tokens=8000)
    budget.set_tier1("chapter_spec", "本章是战斗场景，主角对决魔王")
    budget.set_tier1("red_lines", "主角不能跪，战力不能崩")
    budget.set_tier2("prev_summary", "上一章：主角获得新武器")
    budget.set_tier3("worldview", "末世背景下的人类据点")
    budget.set_tier4("history", "第一章摘要内容")

    result = budget.build(chapter_type="战斗")

    assert result.total_tokens == 8000
    assert result.total_used > 0
    assert len(result.tier_details) == 4
    assert result.tier_details[1]["entries"] == 2
    assert result.tier_details[2]["entries"] == 1
    assert result.tier_details[3]["entries"] == 1
    assert result.tier_details[4]["entries"] == 1
    assert "chapter_spec" in result.prompt_text
    assert "red_lines" in result.prompt_text
    print("[PASS] test_context_budget_basic")


def test_context_budget_dynamic():
    """12. 动态预算调整"""
    from xiaoshuo.pipeline.context_budget import ContextBudget

    # 战斗场景 → Tier 1 预算增加
    budget1 = ContextBudget(total_tokens=10000)
    budget1.set_tier1("spec", "战斗" * 500)  # 大量内容
    budget1.set_tier4("history", "历史" * 500)
    result1 = budget1.build(chapter_type="战斗")

    # 日常场景 → Tier 1 预算减少
    budget2 = ContextBudget(total_tokens=10000)
    budget2.set_tier1("spec", "战斗" * 500)
    budget2.set_tier4("history", "历史" * 500)
    result2 = budget2.build(chapter_type="日常")

    # 战斗场景 Tier 1 预算应大于日常
    assert result1.tier_details[1]["limit"] >= result2.tier_details[1]["limit"], \
        "战斗场景 Tier 1 预算应更大"
    print("[PASS] test_context_budget_dynamic")


def test_context_budget_truncate():
    """13. 裁剪"""
    from xiaoshuo.pipeline.context_budget import ContextBudget

    budget = ContextBudget(total_tokens=500)  # 很小的预算
    budget.set_tier1("big_content", "A" * 2000)  # 远超预算
    budget.set_tier2("small", "B" * 50)

    result = budget.build(chapter_type="")
    assert result.total_used <= result.total_tokens, "总用量不应超过预算"
    # 应有裁剪
    assert len(result.truncated_tiers) > 0 or len(result.skipped_entries) > 0, \
        "超预算应有裁剪或跳过"
    print("[PASS] test_context_budget_truncate")


def test_context_budget_from_writing_context():
    """14. writing_context 批量加载"""
    from xiaoshuo.pipeline.context_budget import build_context

    ctx = {
        "chapter_spec": "本章战斗场景",
        "red_lines": "主角不能跪",
        "prev_summaries": "上章摘要",
        "character_arcs": "角色弧光",
        "novel_synopsis": "全书梗概",
        "worldview": "世界观",
        "history": "历史摘要",
        "knowledge_brain": "经验提醒",
        "unknown_key": "未知key内容",
    }
    result = build_context(ctx, total_tokens=4000, chapter_type="战斗")
    assert result.total_used > 0
    assert "chapter_spec" in result.prompt_text
    assert "red_lines" in result.prompt_text
    print("[PASS] test_context_budget_from_writing_context")


# ════════════════════════════════════════
# P2.4 大纲偏差检测
# ════════════════════════════════════════

def test_outline_deviation_events():
    """15. 事件覆盖"""
    from xiaoshuo.pipeline.outline_deviation import OutlineDeviationChecker

    checker = OutlineDeviationChecker()
    blueprint = {
        "chapter_num": 5,
        "one_sentence": "主角挑战魔王",
        "characters": ["林凡", "魔王"],
        "conflict": "林凡与魔王的决战",
        "cliffhanger": "魔王露出真面目",
    }

    # 符合大纲
    text_ok = (
        "林凡握紧了拳头，看向远处的魔王。"
        "这场决战不可避免，他知道必须全力以赴。"
        "魔王冷笑着，露出了真面目，那是一张狰狞的面孔。"
    )
    result = checker.check(text_ok, blueprint, chapter_num=5)
    assert isinstance(result.coverage_score, float)

    # 偏离大纲 (完全不同的内容)
    text_dev = (
        "苏雪在厨房里做饭，今天她准备了一桌好菜。"
        "窗外阳光明媚，鸟语花香，一切都是那么美好。"
        "她哼着小曲，心情非常愉快。"
    )
    result2 = checker.check(text_dev, blueprint, chapter_num=5)
    assert result2.has_deviations, "偏离大纲应检测到偏差"
    assert result2.coverage_score < result.coverage_score, \
        "偏离文本覆盖率应低于符合文本"
    print("[PASS] test_outline_deviation_events")


def test_outline_deviation_characters():
    """16. 人物出场"""
    from xiaoshuo.pipeline.outline_deviation import OutlineDeviationChecker

    checker = OutlineDeviationChecker()
    blueprint = {
        "chapter_num": 3,
        "one_sentence": "主角与同伴对话",
        "characters": ["林凡", "苏雪", "王虎"],
        "conflict": "三人意见分歧",
    }

    # 全部出场
    text_all = "林凡看着苏雪和王虎，三人意见不一。"
    result = checker.check(text_all, blueprint)
    char_items = [i for i in result.items if i.dimension == "character"]
    assert char_items[0].matched, "三人全部出场应通过"

    # 缺一人
    text_missing = "林凡看着苏雪，两人讨论着什么。"
    result2 = checker.check(text_missing, blueprint)
    char_items2 = [i for i in result2.items if i.dimension == "character"]
    assert not char_items2[0].matched, "缺少王虎应检测到偏差"
    assert "王虎" in char_items2[0].description
    print("[PASS] test_outline_deviation_characters")


def test_outline_deviation_cliffhanger():
    """17. 章末钩子"""
    from xiaoshuo.pipeline.outline_deviation import OutlineDeviationChecker

    checker = OutlineDeviationChecker()
    blueprint = {
        "chapter_num": 10,
        "one_sentence": "战斗结束",
        "characters": ["林凡"],
        "cliffhanger": "魔王复活",
    }

    # 钩子在章末
    text_ok = (
        "林凡终于击败了敌人，他松了一口气。"
        "然而就在这时，地面开始震动，散落的地面上，魔王的残骸开始重组。"
        "魔王复活了！林凡瞪大了眼睛，不敢相信眼前的一切。"
    )
    result = checker.check(text_ok, blueprint)
    cliff_items = [i for i in result.items if i.dimension == "cliffhanger"]
    assert cliff_items[0].matched, "章末有钩子关键词应通过"

    # 钩子不在章末 (文本 >500 字, 钩子在开头)
    text_not_end = (
        "魔王复活了！林凡震惊不已。"
        "但很快他就冷静下来，开始分析局势。"
        + "他走在漫长的走廊里，思考着下一步该怎么办。" * 30 +
        "林凡转身离开了战场，踏上了新的旅程。"
        "远方的天空渐渐亮了起来，新的一天开始了。"
    )
    result2 = checker.check(text_not_end, blueprint)
    cliff_items2 = [i for i in result2.items if i.dimension == "cliffhanger"]
    # 钩子在开头而非章末 → 应有 warning
    assert not cliff_items2[0].matched or cliff_items2[0].severity == "warning"
    print("[PASS] test_outline_deviation_cliffhanger")


def test_outline_deviation_emotion():
    """18. 情绪检测"""
    from xiaoshuo.pipeline.outline_deviation import OutlineDeviationChecker

    checker = OutlineDeviationChecker()
    blueprint = {
        "chapter_num": 7,
        "one_sentence": "主角情绪变化",
        "characters": ["林凡"],
        "emotion_changes": {
            "protagonist": "期待 → 震惊 → 克制",
        },
    }

    # 包含情绪关键词
    text_ok = (
        "林凡充满期待地推开了门，然而眼前的景象让他震惊不已。"
        "他不敢相信，这一切怎么可能。但他很快克制住了自己的情绪，"
        "深呼吸了一下，冷静地分析着局势。"
    )
    result = checker.check(text_ok, blueprint)
    emotion_items = [i for i in result.items if i.dimension == "emotion"]
    assert emotion_items[0].matched, "包含情绪关键词应通过"

    # 缺失情绪
    text_missing = (
        "林凡推开了门，看了看里面。"
        "然后他坐下来，开始看书。"
        "看完书后他出去散步了。"
    )
    result2 = checker.check(text_missing, blueprint)
    emotion_items2 = [i for i in result2.items if i.dimension == "emotion"]
    assert not emotion_items2[0].matched, "缺失情绪应检测到偏差"
    print("[PASS] test_outline_deviation_emotion")


def test_outline_deviation_s3_interface():
    """19. S3 集成接口"""
    from xiaoshuo.pipeline.outline_deviation import outline_deviation_as_s3_check

    blueprint = {
        "chapter_num": 1,
        "one_sentence": "主角登场",
        "characters": ["林凡"],
        "cliffhanger": "悬念出现",
    }
    text = "林凡走进了大厅，悬念出现在他面前。"

    result = outline_deviation_as_s3_check(text, blueprint, chapter_num=1)
    assert result["dimension"] == "outline_deviation"
    assert "coverage_score" in result
    assert "has_deviations" in result
    assert "deviation_count" in result
    assert "summary" in result
    assert isinstance(result["top_issues"], list)
    print("[PASS] test_outline_deviation_s3_interface")


if __name__ == "__main__":
    # P2.1
    test_red_line_default()
    test_red_line_detection()
    test_red_line_pattern()
    test_red_line_management()
    test_red_line_override()
    test_red_line_prompt()
    # P2.2
    test_style_consistency_no_baseline()
    test_style_consistency_with_baseline()
    test_style_consistency_grade()
    test_style_consistency_s3_interface()
    # P2.3
    test_context_budget_basic()
    test_context_budget_dynamic()
    test_context_budget_truncate()
    test_context_budget_from_writing_context()
    # P2.4
    test_outline_deviation_events()
    test_outline_deviation_characters()
    test_outline_deviation_cliffhanger()
    test_outline_deviation_emotion()
    test_outline_deviation_s3_interface()
    print("\n[ALL PASS] P2 modules 19/19 tests passed!")
