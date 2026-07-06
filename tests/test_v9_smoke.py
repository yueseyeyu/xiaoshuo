# -*- coding: utf-8 -*-
"""
test_v9_smoke.py — v8.9/v9.0 新增模块冒烟测试
=============================================
覆盖:
  1. ai_flavor_detector: 对白占比 + 连词密度
  2. vad_analyzer v3: 波动率/跳跃/单调段
  3. style_detector L8: 作者指纹偏离度
  4. patterns: 信息炸弹4类
  5. golden3_analyzer G1: 共鸣类型
  6. skill_loader: acceptance_criteria 最小闭环
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def test_ai_flavor_dialogue():
    """1. ai_flavor_detector 对白占比检测"""
    from xiaoshuo.pipeline.ai_flavor_detector import _check_dialogue_ratio
    # 正常对白 (需>50中文字符才检测)
    normal = (
        "林凡走进大厅，四周一片寂静。他说：「你好，我是新来的。」"
        "苏雪看了他一眼，回答：「你好，欢迎加入我们。」"
        "然后他们一起走向会议室，沿途讨论着接下来的计划安排。"
        "林凡觉得这个地方还不错，至少暂时有了一个落脚之处。"
    )
    info = _check_dialogue_ratio(normal)
    assert 0.05 <= info["ratio"] <= 0.65, f"正常对白比例应在5%-65%, got {info['ratio']}"
    # 无对白
    no_dialogue = (
        "天空很蓝，阳光明媚，万里无云，一切都是那么美好。"
        "远处的山峰在晨曦中若隐若现，空气中弥漫着青草和泥土的芬芳。"
        "山间的溪流潺潺作响，清澈见底，偶尔有几条小鱼在水中翻腾。"
    )
    info2 = _check_dialogue_ratio(no_dialogue)
    assert info2["ratio"] < 0.05, f"无对白比例应<5%, got {info2['ratio']}"
    print(f"[PASS] test_ai_flavor_dialogue (normal={info['ratio']:.0%}, no_dialogue={info2['ratio']:.0%})")


def test_vad_analyzer_v3():
    """2. vad_analyzer v3 情感波动"""
    from xiaoshuo.pipeline.scoring.vad_analyzer import compute_vad, _detect_monotony_segments
    # 构造测试数据 (6章)
    rows = [
        {"ch_num": 1, "pos_density": 0.1, "neg_density": 0.8, "pleasure_intensity": 0.2, "conflict_density": 0.7},
        {"ch_num": 2, "pos_density": 0.7, "neg_density": 0.1, "pleasure_intensity": 0.8, "conflict_density": 0.3},
        {"ch_num": 3, "pos_density": 0.2, "neg_density": 0.9, "pleasure_intensity": 0.1, "conflict_density": 0.9},
        {"ch_num": 4, "pos_density": 0.8, "neg_density": 0.2, "pleasure_intensity": 0.9, "conflict_density": 0.2},
        {"ch_num": 5, "pos_density": 0.3, "neg_density": 0.7, "pleasure_intensity": 0.3, "conflict_density": 0.6},
        {"ch_num": 6, "pos_density": 0.9, "neg_density": 0.1, "pleasure_intensity": 0.9, "conflict_density": 0.1},
    ]
    curve, turning, summary = compute_vad(rows)
    assert len(curve) == 6, f"应有6章曲线, got {len(curve)}"
    assert "ch" in curve[0] and "V" in curve[0] and "A" in curve[0] and "D" in curve[0]
    # 单调段检测
    v_values = [c["V"] for c in curve]
    segments = _detect_monotony_segments(v_values, curve)
    assert isinstance(segments, list)
    print(f"[PASS] test_vad_analyzer_v3 (chapters={len(curve)}, turning_points={len(turning)})")


def test_style_detector_l8():
    """3. StyleDetector L8 作者指纹偏离度"""
    from xiaoshuo.agents.style_detector import StyleDetector
    detector = StyleDetector()
    text = "他走进房间。突然，冷风吹来。他心里想，这里发生了什么？门外传来脚步声。"

    # 无指纹 → 跳过
    r1 = detector.detect(text, chapter_num=1)
    l8a = [l for l in r1.layers if l.layer == "L8"]
    assert len(l8a) == 1, "应有L8层"
    assert l8a[0].passed, "无作者指纹应PASS"
    assert len(r1.layers) == 8, f"应有8层, got {len(r1.layers)}"

    # 有指纹 → 偏离度计算
    fp = {"avg_sentence_length": 35, "dialogue_ratio": 0.3, "mental_prefix_density": 5.0}
    r2 = detector.detect(text, chapter_num=1, author_fingerprint=fp)
    l8b = [l for l in r2.layers if l.layer == "L8"]
    assert l8b[0].value >= 0, "偏离度应>=0"
    assert "句长" in l8b[0].detail, "detail应含句长信息"
    print(f"[PASS] test_style_detector_l8 (deviation={l8b[0].value:.4f}, passed={l8b[0].passed})")


def test_info_bomb_patterns():
    """4. 信息炸弹4类子分类"""
    from xiaoshuo.pipeline.rhythm.patterns import INFO_BOMB_PATTERNS, INFO_BOMB_TYPE_NAMES
    assert len(INFO_BOMB_PATTERNS) == 4, f"应有4类, got {len(INFO_BOMB_PATTERNS)}"
    assert len(INFO_BOMB_TYPE_NAMES) == 4

    cases = [
        ("crisis", "再不交出解药就来不及了！"),
        ("joy", "他竟然中了百万大奖！"),
        ("temptation", "只要练成此功就能获得巨大好处。"),
        ("gossip", "你听说了吗？隔壁出事了。"),
    ]
    for expected, text in cases:
        matched = [k for k, p in INFO_BOMB_PATTERNS.items() if p.search(text)]
        assert expected in matched, f"{expected} 应匹配 '{text}', got {matched}"
    print(f"[PASS] test_info_bomb_patterns (4/4 types matched)")


def test_golden3_resonance():
    """5. Golden3 G1 共鸣类型检测"""
    from xiaoshuo.pipeline.golden3_analyzer import check_high_energy_hook, RESONANCE_PATTERNS
    assert len(RESONANCE_PATTERNS) == 4, f"应有4类共鸣, got {len(RESONANCE_PATTERNS)}"

    # 事业型 (需>50中文字符)
    ch1 = (
        "李明今年二十八岁，一事无成。他不想再打工了，"
        "他要创业，要出人头地，要搞钱。只有赚钱才能改变一切。"
        "突然，手机响了，是一条改变命运的短信。"
        "他看着屏幕，瞳孔骤缩，这不可能！"
    )
    dim = check_high_energy_hook(ch1)
    assert "共鸣类型" in dim.details, "应有共鸣类型字段"
    assert "事业型" in dim.details["共鸣类型"], f"应检测到事业型, got {dim.details['共鸣类型']}"

    # 逆袭型
    ch2 = (
        "他被退婚了。全族都在嘲笑他是废物、是废柴。他不甘心。"
        "他发誓要让所有看不起他的人付出代价。突然，一道金光从天而降，"
        "融入他的身体。他感到一股力量在体内涌动，一切都不一样了。"
    )
    dim2 = check_high_energy_hook(ch2)
    assert "逆袭型" in dim2.details["共鸣类型"], f"应检测到逆袭型, got {dim2.details['共鸣类型']}"
    print(f"[PASS] test_golden3_resonance (career={dim.details['共鸣类型']}, underdog={dim2.details['共鸣类型']})")


def test_acceptance_criteria_loop():
    """6. acceptance_criteria 最小闭环约束"""
    from xiaoshuo.agents.skill_loader import SkillLoader
    criteria = SkillLoader._derive_acceptance_criteria(1, 300, "末世")
    assert "最小闭环" in criteria, "应包含最小闭环约束"
    assert "跨章闭环" in criteria, "应包含跨章闭环约束"
    assert "目标" in criteria and "阻碍" in criteria and "反击" in criteria
    print(f"[PASS] test_acceptance_criteria_loop")


if __name__ == "__main__":
    print("=" * 60)
    print("  v8.9/v9.0 新增模块冒烟测试")
    print("=" * 60)

    tests = [
        test_ai_flavor_dialogue,
        test_vad_analyzer_v3,
        test_style_detector_l8,
        test_info_bomb_patterns,
        test_golden3_resonance,
        test_acceptance_criteria_loop,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"[FAIL] {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"  Result: {passed} passed / {failed} failed")
    print(f"{'=' * 60}")

    if failed > 0:
        sys.exit(1)
