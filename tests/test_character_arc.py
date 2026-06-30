# -*- coding: utf-8 -*-
"""
test_character_arc.py — CharacterArcTracker (P1.2) 单元测试
=============================================================
测试覆盖:
  1. 基础 CRUD: record / get_arc / get_latest / list_characters
  2. 情绪单调检测 (连续 3 章同一情绪)
  3. 成长停滞检测 (10 章无 growth_marker)
  4. 动机-行为矛盾检测
  5. check_all (多角色批量检查)
  6. visualize_data (可视化数据结构)
  7. NovelIndex 便捷入口 + writing_context 集成
"""

import os
import sys
import tempfile
from pathlib import Path

# 确保能找到包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# 使用临时数据目录
os.environ.setdefault("XIAOSHUO_DATA_ROOT", str(Path(tempfile.gettempdir()) / "xiaoshuo_test"))


def _make_index():
    """创建一个临时 NovelIndex。"""
    from xiaoshuo.pipeline.novel_index import NovelIndex
    idx = NovelIndex(genre="_test", book_name=f"arc_test_{os.getpid()}")
    idx._create_tables()
    return idx


def _cleanup(idx):
    """清理临时数据库。"""
    idx.close()
    import gc
    gc.collect()
    if idx.db_path.exists():
        try:
            idx.db_path.unlink()
        except PermissionError:
            pass  # Windows 文件锁, 临时文件不影响测试结果


# ──────────────────────────────────────
# 1. 基础 CRUD
# ──────────────────────────────────────

def test_basic_crud():
    idx = _make_index()
    try:
        tracker = idx.arc_tracker

        # record
        rid = tracker.record(ch_num=1, character="林凡",
                             emotion_state="愤怒", motivation="复仇",
                             growth_marker="觉醒异能", power_level="炼气期")
        assert rid > 0, f"record 应返回 >0 的 ID, got {rid}"

        # get_arc
        arc = tracker.get_arc("林凡")
        assert len(arc) == 1
        assert arc[0]["emotion_state"] == "愤怒"
        assert arc[0]["motivation"] == "复仇"

        # get_latest
        latest = tracker.get_latest("林凡")
        assert latest is not None
        assert latest["ch_num"] == 1

        # list_characters
        tracker.record(ch_num=2, character="苏雪", emotion_state="平静")
        chars = tracker.list_characters()
        assert "林凡" in chars
        assert "苏雪" in chars
        assert len(chars) == 2

        # get_latest 不存在的角色
        assert tracker.get_latest("不存在") is None

        print("[PASS] test_basic_crud")
    finally:
        _cleanup(idx)


# ──────────────────────────────────────
# 2. 情绪单调检测
# ──────────────────────────────────────

def test_emotion_monotony():
    idx = _make_index()
    try:
        tracker = idx.arc_tracker

        # 连续 3 章同一情绪 → 应触发警告
        for ch in range(1, 4):
            tracker.record(ch_num=ch, character="林凡", emotion_state="愤怒",
                           motivation="复仇")
        report = tracker.check_arc("林凡", current_ch=4)
        assert report.has_issues, "连续3章同一情绪应触发警告"
        assert any("情绪单调" in w for w in report.warnings), \
            f"应有情绪单调警告, got {report.warnings}"
        assert report.emotion_variety == 1

        # 增加变化后不再单调
        tracker.record(ch_num=4, character="林凡", emotion_state="平静", motivation="复仇")
        report2 = tracker.check_arc("林凡", current_ch=5)
        # 仍有之前的3章单调记录, 但已经打破
        # 注意: 检测逻辑是连续相同, 所以 ch1-3 仍会报告
        monotony_warns = [w for w in report2.warnings if "情绪单调" in w]
        assert len(monotony_warns) >= 1  # ch1-3 的单调仍被检测到
        assert report2.emotion_variety == 2  # 愤怒 + 平静

        print("[PASS] test_emotion_monotony")
    finally:
        _cleanup(idx)


# ──────────────────────────────────────
# 3. 成长停滞检测
# ──────────────────────────────────────

def test_growth_stagnation():
    idx = _make_index()
    try:
        tracker = idx.arc_tracker

        # 10 章无 growth_marker → 警告
        for ch in range(1, 11):
            tracker.record(ch_num=ch, character="林凡", emotion_state="愤怒",
                           motivation="复仇", growth_marker="")
        report = tracker.check_arc("林凡", current_ch=11)
        assert report.has_issues
        assert any("成长停滞" in w for w in report.warnings), \
            f"10章无成长标记应触发停滞警告, got {report.warnings}"

        # 在第 5 章加入成长标记 → 不应触发 (因为 last_growth=5, 11-5=6 < 10)
        idx2 = _make_index()
        tracker2 = idx2.arc_tracker
        for ch in range(1, 11):
            gm = "突破炼气" if ch == 5 else ""
            tracker2.record(ch_num=ch, character="林凡", emotion_state="愤怒",
                           motivation="复仇", growth_marker=gm)
        report2 = tracker2.check_arc("林凡", current_ch=11)
        stagnation_warns = [w for w in report2.warnings if "成长停滞" in w]
        assert len(stagnation_warns) == 0, \
            f"有成长标记且距离<10章不应触发停滞, got {stagnation_warns}"
        _cleanup(idx2)

        print("[PASS] test_growth_stagnation")
    finally:
        _cleanup(idx)


# ──────────────────────────────────────
# 4. 动机-行为矛盾检测
# ──────────────────────────────────────

def test_motivation_behavior_conflict():
    idx = _make_index()
    try:
        tracker = idx.arc_tracker

        # 动机=复仇, 但 notes 中包含矛盾行为词
        tracker.record(ch_num=1, character="林凡", motivation="复仇",
                       notes="他去逛街赏花约会了", emotion_state="愤怒")
        report = tracker.check_arc("林凡", current_ch=2)
        conflict_warns = [w for w in report.warnings if "动机-行为矛盾" in w]
        assert len(conflict_warns) >= 1, \
            f"动机复仇但行为逛街赏花应触发矛盾警告, got {report.warnings}"

        # 动机=变强, conflict 中包含休息偷懒
        tracker.record(ch_num=2, character="王虎", motivation="变强",
                       conflict="他在休息偷懒放弃修炼", emotion_state="疲惫")
        report2 = tracker.check_arc("王虎", current_ch=3)
        conflict_warns2 = [w for w in report2.warnings if "动机-行为矛盾" in w]
        assert len(conflict_warns2) >= 1, \
            f"动机变强但行为休息偷懒应触发矛盾警告, got {report2.warnings}"

        # 动机=复仇, 行为一致 (战斗/追查) → 无矛盾警告
        tracker.record(ch_num=3, character="赵刚", motivation="复仇",
                       notes="他追查凶手追踪线索", emotion_state="愤怒")
        report3 = tracker.check_arc("赵刚", current_ch=4)
        conflict_warns3 = [w for w in report3.warnings if "动机-行为矛盾" in w]
        assert len(conflict_warns3) == 0, \
            f"动机复仇且行为追查追踪不应触发矛盾警告, got {conflict_warns3}"

        print("[PASS] test_motivation_behavior_conflict")
    finally:
        _cleanup(idx)


# ──────────────────────────────────────
# 5. check_all 多角色批量检查
# ──────────────────────────────────────

def test_check_all():
    idx = _make_index()
    try:
        tracker = idx.arc_tracker

        # 角色A: 情绪单调
        for ch in range(1, 4):
            tracker.record(ch_num=ch, character="角色A", emotion_state="绝望")

        # 角色B: 健康
        tracker.record(ch_num=1, character="角色B", emotion_state="愤怒",
                      motivation="复仇", growth_marker="觉醒")

        reports = tracker.check_all(current_ch=5)
        assert len(reports) == 2

        # 找到角色A的报告
        report_a = [r for r in reports if r.character == "角色A"][0]
        assert report_a.has_issues, "角色A应有情绪单调问题"

        report_b = [r for r in reports if r.character == "角色B"][0]
        assert not report_b.has_issues or len(report_b.warnings) == 0, \
            "角色B不应有问题"

        print("[PASS] test_check_all")
    finally:
        _cleanup(idx)


# ──────────────────────────────────────
# 6. visualize_data 可视化数据
# ──────────────────────────────────────

def test_visualize_data():
    idx = _make_index()
    try:
        tracker = idx.arc_tracker

        tracker.record(ch_num=1, character="林凡", emotion_state="愤怒",
                      motivation="复仇", growth_marker="觉醒异能",
                      power_level="炼气期")
        tracker.record(ch_num=2, character="林凡", emotion_state="震惊",
                      motivation="复仇", growth_marker="",
                      power_level="筑基期")
        tracker.record(ch_num=3, character="林凡", emotion_state="坚定",
                      motivation="保护", growth_marker="突破筑基",
                      power_level="金丹期")

        viz = tracker.visualize_data("林凡")
        assert viz["character"] == "林凡"
        assert viz["chapter_range"] == [1, 3]
        assert viz["total_chapters"] == 3
        assert len(viz["emotion_curve"]) == 3
        assert len(viz["growth_markers"]) == 2  # ch1 + ch3
        assert len(viz["power_progression"]) == 3

        # 情绪分数检查 (愤怒=7, 震惊=7, 坚定=8)
        scores = [e["y"] for e in viz["emotion_curve"]]
        assert scores[0] == 7  # 愤怒
        assert scores[2] == 8  # 坚定

        # 不存在的角色
        viz_err = tracker.visualize_data("不存在")
        assert "error" in viz_err

        print("[PASS] test_visualize_data")
    finally:
        _cleanup(idx)


# ──────────────────────────────────────
# 7. NovelIndex 便捷入口 + writing_context
# ──────────────────────────────────────

def test_novel_index_integration():
    idx = _make_index()
    try:
        # 便捷入口
        rid = idx.record_character_arc(ch_num=1, character="林凡",
                                       emotion_state="愤怒", motivation="复仇",
                                       growth_marker="觉醒")
        assert rid > 0

        report = idx.check_character_arc("林凡", current_ch=5)
        assert isinstance(report.warnings, list)

        all_reports = idx.check_all_arcs(current_ch=5)
        assert len(all_reports) >= 1

        viz = idx.character_arc_visualize("林凡")
        assert viz["character"] == "林凡"

        # writing_context 集成
        ctx = idx.writing_context(ch_num=5, k=3)
        assert "character_arc_warnings" in ctx
        assert "character_arc_summary" in ctx
        assert isinstance(ctx["character_arc_warnings"], list)
        assert isinstance(ctx["character_arc_summary"], dict)
        assert ctx["character_arc_summary"]["characters_tracked"] >= 1

        print("[PASS] test_novel_index_integration")
    finally:
        _cleanup(idx)


# ──────────────────────────────────────
# 8. summary 统计
# ──────────────────────────────────────

def test_summary():
    idx = _make_index()
    try:
        tracker = idx.arc_tracker

        tracker.record(ch_num=1, character="林凡", emotion_state="愤怒",
                      motivation="复仇", growth_marker="觉醒")
        tracker.record(ch_num=2, character="林凡", emotion_state="平静",
                      motivation="复仇", growth_marker="")
        tracker.record(ch_num=1, character="苏雪", emotion_state="恐惧",
                      motivation="保护", growth_marker="")

        s = tracker.summary()
        assert s["characters_tracked"] == 2
        assert s["total_records"] == 3
        assert s["total_growth_markers"] == 1
        # 林凡 2 章不触发单调 (需3章), 苏雪 1 章也不触发
        # 但林凡可能触发停滞? 2章 < 10 所以不会
        assert s["total_warnings"] == 0

        print("[PASS] test_summary")
    finally:
        _cleanup(idx)


# ──────────────────────────────────────
# 9. 空数据库边界情况
# ──────────────────────────────────────

def test_empty_database():
    idx = _make_index()
    try:
        tracker = idx.arc_tracker

        # 不存在的角色
        report = tracker.check_arc("不存在", current_ch=1)
        assert report.has_issues
        assert any("无弧光记录" in w for w in report.warnings)

        # check_all 空列表
        reports = tracker.check_all()
        assert len(reports) == 0

        # summary 空
        s = tracker.summary()
        assert s["characters_tracked"] == 0
        assert s["total_records"] == 0

        # visualize_data 空
        viz = tracker.visualize_data("不存在")
        assert "error" in viz

        # list_characters 空
        assert tracker.list_characters() == []

        print("[PASS] test_empty_database")
    finally:
        _cleanup(idx)


# ──────────────────────────────────────
# 10. 动机变更追踪
# ──────────────────────────────────────

def test_motivation_changes():
    idx = _make_index()
    try:
        tracker = idx.arc_tracker

        tracker.record(ch_num=1, character="林凡", motivation="复仇", emotion_state="愤怒")
        tracker.record(ch_num=2, character="林凡", motivation="复仇", emotion_state="愤怒")
        tracker.record(ch_num=3, character="林凡", motivation="保护", emotion_state="平静")
        tracker.record(ch_num=4, character="林凡", motivation="探索", emotion_state="好奇")

        report = tracker.check_arc("林凡", current_ch=5)
        # 复仇→复仇→保护→探索 = 2 次变更
        assert report.motivation_changes == 2, \
            f"应有2次动机变更, got {report.motivation_changes}"
        assert len(report.motivation_timeline) == 4

        print("[PASS] test_motivation_changes")
    finally:
        _cleanup(idx)


if __name__ == "__main__":
    test_basic_crud()
    test_emotion_monotony()
    test_growth_stagnation()
    test_motivation_behavior_conflict()
    test_check_all()
    test_visualize_data()
    test_novel_index_integration()
    test_summary()
    test_empty_database()
    test_motivation_changes()
    print("\n[ALL PASS] CharacterArcTracker (P1.2) 10/10 tests passed!")
