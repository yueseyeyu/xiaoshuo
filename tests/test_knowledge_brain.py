# -*- coding: utf-8 -*-
"""
test_knowledge_brain.py — Knowledge-Brain (P1.4) 单元测试
==========================================================
测试覆盖:
  1. record: 基本记录经验
  2. 根因哈希去重 (同一根因 → 增加出现次数)
  3. 自动晋升 (≥2 次 → 全局)
  4. check_before_write: 写前查表 (标签匹配/评分排序)
  5. 手动 promote / demote
  6. cleanup_stale: 过期清理
  7. search: 全文搜索
  8. stats: 统计信息
  9. format_for_prompt: Prompt 注入格式化
  10. format_for_writing_context: 写作上下文集成
  11. delete: 删除经验
  12. 序列化/反序列化 (to_dict/from_dict)
  13. 便捷函数 (get_knowledge_brain / check_before_write / record_experience)
  14. 持久化: 保存后重新加载
"""

import gc
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

# 确保能找到包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


# ── 测试 fixture ──

_TMP_DIRS: list[Path] = []


def _make_kb():
    """创建一个使用临时目录的 KnowledgeBrain 实例。"""
    import xiaoshuo.pipeline.knowledge_brain as kb_mod

    tmp_dir = Path(tempfile.mkdtemp(prefix="kb_test_"))
    _TMP_DIRS.append(tmp_dir)

    # patch 模块级路径常量
    kb_mod.KB_DIR = tmp_dir
    kb_mod.GLOBAL_EXP_PATH = tmp_dir / "global_experience.json"
    kb_mod.PROJECT_MEM_PATH = tmp_dir / "project_memory.json"

    # 重置单例
    kb_mod._kb_instance = None

    return kb_mod.KnowledgeBrain()


def _cleanup():
    """清理所有临时目录。"""
    gc.collect()
    for d in _TMP_DIRS:
        if d.exists():
            import shutil
            try:
                shutil.rmtree(d, ignore_errors=True)
            except PermissionError:
                pass
    _TMP_DIRS.clear()


# ──────────────────────────────────────
# 1. 基本记录
# ──────────────────────────────────────

def test_record_basic():
    """1. record 基本功能"""
    kb = _make_kb()
    try:
        exp_id = kb.record(
            symptom="战斗场景AI指纹词密度过高",
            root_cause="战斗描写中连续使用'深吸一口气''目光扫过'",
            solution="战斗场景分散使用动作动词",
            severity="warning",
            source="s3_review",
            tags=["战斗", "AI指纹"],
            genre="末世",
        )
        assert exp_id, "record 应返回非空 ID"
        assert exp_id.startswith("exp-")

        # 查找
        exp = kb.get_by_id(exp_id)
        assert exp is not None
        assert exp.symptom == "战斗场景AI指纹词密度过高"
        assert exp.root_cause == "战斗描写中连续使用'深吸一口气''目光扫过'"
        assert exp.severity == "warning"
        assert exp.source == "s3_review"
        assert "战斗" in exp.tags
        assert exp.occurrences == 1
        assert not exp.is_global

        print("[PASS] test_record_basic")
    finally:
        _cleanup()


# ──────────────────────────────────────
# 2. 根因哈希去重
# ──────────────────────────────────────

def test_hash_dedup():
    """2. 同一根因不同表述 → 去重"""
    kb = _make_kb()
    try:
        # 第一次记录
        id1 = kb.record(
            symptom="战斗场景AI指纹词密度过高",
            root_cause="连续使用深吸一口气和目光扫过",
            tags=["战斗"],
        )

        # 第二次: 根因相同 (标点/空格不同) → 应去重
        id2 = kb.record(
            symptom="又一次发现这个问题",
            root_cause="连续使用，深吸一口气，和，目光扫过",  # 多了逗号
            tags=["战斗"],
        )

        assert id1 == id2, f"同一根因应返回相同 ID: {id1} vs {id2}"

        exp = kb.get_by_id(id1)
        assert exp.occurrences == 2, f"出现次数应为 2, got {exp.occurrences}"

        # 第三次: 完全不同的根因 → 新记录
        id3 = kb.record(
            symptom="对话太多缺少动作描写",
            root_cause="全是对话没有动作描写",
            tags=["对话"],
        )
        assert id3 != id1, "不同根因应有不同 ID"

        print("[PASS] test_hash_dedup")
    finally:
        _cleanup()


# ──────────────────────────────────────
# 3. 自动晋升
# ──────────────────────────────────────

def test_auto_promote():
    """3. 出现 ≥2 次 → 自动晋升全局"""
    kb = _make_kb()
    try:
        root_cause = "连续使用深吸一口气和目光扫过"

        # 第一次
        id1 = kb.record(
            symptom="第一章战斗场景AI指纹高",
            root_cause=root_cause,
            severity="warning",
            tags=["战斗"],
        )
        exp = kb.get_by_id(id1)
        assert not exp.is_global, "第一次记录不应是全局"

        # 第二次 (相同根因) → 触发自动晋升
        id2 = kb.record(
            symptom="第三章战斗场景同样问题",
            root_cause=root_cause,
            severity="serious",  # 严重度升级
            tags=["战斗"],
        )
        assert id1 == id2

        exp = kb.get_by_id(id1)
        assert exp.is_global, "出现 2 次应自动晋升全局"
        assert exp.occurrences == 2
        assert exp.severity == "serious", "严重度应升级为 serious"
        assert len(kb.list_global()) == 1
        assert len(kb.list_project()) == 0  # 已从项目移除

        print("[PASS] test_auto_promote")
    finally:
        _cleanup()


# ──────────────────────────────────────
# 4. 写前查表
# ──────────────────────────────────────

def test_check_before_write():
    """4. check_before_write 匹配与排序"""
    kb = _make_kb()
    try:
        # 记录几条经验
        kb.record(
            symptom="战斗场景AI指纹词密度过高",
            root_cause="战斗描写连续使用深吸一口气",
            solution="分散使用动作动词",
            severity="serious",
            tags=["战斗", "AI指纹"],
            genre="末世",
        )
        kb.record(
            symptom="对话场景缺少潜台词",
            root_cause="对话太直白没有弦外之音",
            solution="增加言外之意",
            severity="warning",
            tags=["对话"],
            genre="都市",
        )
        kb.record(
            symptom="过渡章节节奏太慢",
            root_cause="环境描写过长拖慢剧情",
            severity="info",
            tags=["过渡"],
        )

        # 查表: 战斗场景
        result = kb.check_before_write(
            chapter_type="战斗",
            context={"genre": "末世", "chapter_num": 15},
        )
        assert result.count > 0, "应有匹配结果"
        assert result.has_warnings, "应有警告 (serious >= warning)"

        # 第一条应匹配战斗相关
        top = result.matched[0]
        assert "战斗" in top.tags or "战斗" in top.symptom, \
            f"最匹配的应是战斗相关经验, got: {top.symptom}"

        # 查表: 对话场景
        result2 = kb.check_before_write(
            chapter_type="对话",
            context={"genre": "都市"},
        )
        assert result2.count > 0
        top2 = result2.matched[0]
        assert "对话" in top2.tags or "对话" in top2.symptom

        # 查表: 无匹配
        result3 = kb.check_before_write(
            chapter_type="搞笑",
            context={},
        )
        assert result3.count == 0, "无匹配标签时应返回空"
        assert not result3.has_warnings

        print("[PASS] test_check_before_write")
    finally:
        _cleanup()


def test_check_empty_kb():
    """4b. 空知识库查表"""
    kb = _make_kb()
    try:
        result = kb.check_before_write("战斗", {"genre": "末世"})
        assert result.count == 0
        assert not result.has_warnings
        assert result.warnings == []
        print("[PASS] test_check_empty_kb")
    finally:
        _cleanup()


# ──────────────────────────────────────
# 5. 手动 promote / demote
# ──────────────────────────────────────

def test_manual_promote_demote():
    """5. 手动晋升/降级"""
    kb = _make_kb()
    try:
        exp_id = kb.record(
            symptom="需要手动晋升的经验",
            root_cause="某个根因测试手动晋升流程",
            severity="warning",
            tags=["测试"],
        )
        exp = kb.get_by_id(exp_id)
        assert not exp.is_global

        # 手动晋升
        ok = kb.promote(exp_id)
        assert ok, "promote 应返回 True"
        exp = kb.get_by_id(exp_id)
        assert exp.is_global
        assert len(kb.list_global()) == 1
        assert len(kb.list_project()) == 0

        # 重复晋升 → False
        ok2 = kb.promote(exp_id)
        assert not ok2, "已全局的经验再次晋升应返回 False"

        # 手动降级
        ok3 = kb.demote(exp_id)
        assert ok3, "demote 应返回 True"
        exp = kb.get_by_id(exp_id)
        assert not exp.is_global
        assert len(kb.list_global()) == 0
        assert len(kb.list_project()) == 1

        # 降级不存在的 → False
        ok4 = kb.demote("nonexistent-id")
        assert not ok4

        print("[PASS] test_manual_promote_demote")
    finally:
        _cleanup()


# ──────────────────────────────────────
# 6. cleanup_stale
# ──────────────────────────────────────

def test_cleanup_stale():
    """6. 过期清理"""
    kb = _make_kb()
    try:
        # 记录一条经验
        exp_id = kb.record(
            symptom="过期经验测试",
            root_cause="过期根因测试内容",
            severity="info",
            tags=["测试"],
        )
        exp = kb.get_by_id(exp_id)
        assert exp is not None

        # 手动设置创建时间为 100 天前, hit_count=0
        old_time = (datetime.now() - timedelta(days=100)).isoformat(timespec="seconds")
        exp.created_at = old_time
        exp.last_hit_at = old_time
        exp.hit_count = 0
        kb._save()

        # 清理
        removed = kb.cleanup_stale()
        assert removed == 1, f"应清理 1 条, got {removed}"
        assert kb.get_by_id(exp_id) is None, "过期经验应被删除"

        # 再记录一条但 hit_count > 0 → 不清理
        exp_id2 = kb.record(
            symptom="有命中不过期",
            root_cause="有命中记录的根因",
            severity="warning",
            tags=["测试"],
        )
        exp2 = kb.get_by_id(exp_id2)
        exp2.created_at = old_time
        exp2.last_hit_at = old_time
        exp2.hit_count = 3
        kb._save()

        removed2 = kb.cleanup_stale()
        assert removed2 == 0, "有命中的经验不应被清理"
        assert kb.get_by_id(exp_id2) is not None

        print("[PASS] test_cleanup_stale")
    finally:
        _cleanup()


# ──────────────────────────────────────
# 7. search
# ──────────────────────────────────────

def test_search():
    """7. 全文搜索"""
    kb = _make_kb()
    try:
        kb.record(
            symptom="战斗场景AI指纹词密度过高",
            root_cause="战斗描写重复使用心理描写",
            solution="增加动作描写",
            tags=["战斗", "AI指纹"],
        )
        kb.record(
            symptom="对话缺少潜台词",
            root_cause="对话太直白",
            tags=["对话"],
        )

        # 搜索 symptom
        results = kb.search("AI指纹")
        assert len(results) == 1
        assert "AI指纹" in results[0].symptom

        # 搜索 root_cause
        results2 = kb.search("直白")
        assert len(results2) == 1
        assert "直白" in results2[0].root_cause

        # 搜索 solution
        results3 = kb.search("动作描写")
        assert len(results3) == 1
        assert "动作描写" in results3[0].solution

        # 搜索 tags
        results4 = kb.search("战斗")
        assert len(results4) >= 1

        # 无结果
        results5 = kb.search("不存在的关键词")
        assert len(results5) == 0

        print("[PASS] test_search")
    finally:
        _cleanup()


# ──────────────────────────────────────
# 8. stats
# ──────────────────────────────────────

def test_stats():
    """8. 统计信息"""
    kb = _make_kb()
    try:
        kb.record(
            symptom="经验1", root_cause="根因1",
            severity="warning", source="s3_review",
        )
        kb.record(
            symptom="经验2", root_cause="根因2",
            severity="critical", source="s4_detection",
        )
        # 同根因 → 晋升全局
        kb.record(
            symptom="经验2重复", root_cause="根因2",
            severity="critical", source="s4_detection",
        )

        stats = kb.stats()
        assert stats["total"] == 2, f"总数应为 2 (去重后), got {stats['total']}"
        assert stats["global_count"] == 1, f"全局应为 1, got {stats['global_count']}"
        assert stats["project_count"] == 1, f"项目应为 1, got {stats['project_count']}"
        assert "warning" in stats["severity_dist"]
        assert "critical" in stats["severity_dist"]
        assert stats["severity_dist"]["critical"] == 1
        assert "s3_review" in stats["source_dist"]
        assert stats["max_global"] == 30
        assert stats["promote_threshold"] == 2

        print("[PASS] test_stats")
    finally:
        _cleanup()


# ──────────────────────────────────────
# 9. format_for_prompt
# ──────────────────────────────────────

def test_format_for_prompt():
    """9. Prompt 注入格式化"""
    kb = _make_kb()
    try:
        # 空库
        assert kb.format_for_prompt() == ""

        # 有数据
        kb.record(
            symptom="战斗场景AI指纹过高",
            root_cause="连续使用深吸一口气",
            solution="分散使用动作动词",
            severity="serious",
            tags=["战斗"],
        )
        text = kb.format_for_prompt(max_entries=3)
        assert "## 历史经验提醒" in text
        assert "战斗场景AI指纹过高" in text
        assert "根因" in text
        assert "方案" in text
        assert "SERIOUS" in text

        # max_entries 限制
        kb.record(symptom="经验2", root_cause="根因2", severity="warning")
        kb.record(symptom="经验3", root_cause="根因3", severity="info")
        kb.record(symptom="经验4", root_cause="根因4", severity="critical")

        text2 = kb.format_for_prompt(max_entries=2)
        lines = [l for l in text2.split("\n") if l.startswith("- [")]
        assert len(lines) <= 2, f"应最多 2 条, got {len(lines)}"

        print("[PASS] test_format_for_prompt")
    finally:
        _cleanup()


# ──────────────────────────────────────
# 10. format_for_writing_context
# ──────────────────────────────────────

def test_format_for_writing_context():
    """10. 写作上下文集成"""
    kb = _make_kb()
    try:
        kb.record(
            symptom="战斗场景AI指纹过高",
            root_cause="连续使用深吸一口气",
            solution="分散使用动作动词",
            severity="serious",
            tags=["战斗"],
        )

        ctx = kb.format_for_writing_context(
            chapter_type="战斗",
            context={"genre": "末世"},
        )
        assert "warnings" in ctx
        assert "matched_count" in ctx
        assert "has_warnings" in ctx
        assert "prompt_text" in ctx
        assert ctx["matched_count"] > 0
        assert ctx["has_warnings"] is True
        assert len(ctx["warnings"]) > 0
        assert "历史经验提醒" in ctx["prompt_text"]

        # 无匹配
        ctx2 = kb.format_for_writing_context("搞笑", {})
        assert ctx2["matched_count"] == 0
        assert ctx2["has_warnings"] is False
        assert ctx2["prompt_text"] == ""

        print("[PASS] test_format_for_writing_context")
    finally:
        _cleanup()


# ──────────────────────────────────────
# 11. delete
# ──────────────────────────────────────

def test_delete():
    """11. 删除经验"""
    kb = _make_kb()
    try:
        exp_id = kb.record(
            symptom="待删除经验",
            root_cause="删除测试根因",
            tags=["测试"],
        )
        assert kb.get_by_id(exp_id) is not None

        # 删除
        ok = kb.delete(exp_id)
        assert ok, "delete 应返回 True"
        assert kb.get_by_id(exp_id) is None

        # 重复删除 → False
        ok2 = kb.delete(exp_id)
        assert not ok2, "删除不存在的应返回 False"

        # 删除全局经验
        exp_id2 = kb.record(symptom="经验A", root_cause="根因A")
        kb.promote(exp_id2)
        assert kb.get_by_id(exp_id2).is_global
        ok3 = kb.delete(exp_id2)
        assert ok3
        assert kb.get_by_id(exp_id2) is None

        print("[PASS] test_delete")
    finally:
        _cleanup()


# ──────────────────────────────────────
# 12. 序列化
# ──────────────────────────────────────

def test_serialization():
    """12. Experience to_dict / from_dict"""
    from xiaoshuo.pipeline.knowledge_brain import Experience

    exp = Experience(
        id="exp-0001",
        hash="abc123",
        symptom="测试症状",
        root_cause="测试根因",
        solution="测试方案",
        severity="critical",
        source="s4_detection",
        tags=["战斗", "AI指纹"],
        created_at="2025-01-01T00:00:00",
        hit_count=5,
        last_hit_at="2025-06-01T00:00:00",
        occurrences=3,
        is_global=True,
        genre="末世",
    )

    d = exp.to_dict()
    assert isinstance(d, dict)
    assert d["id"] == "exp-0001"
    assert d["hash"] == "abc123"
    assert d["symptom"] == "测试症状"
    assert d["severity"] == "critical"
    assert d["is_global"] is True
    assert "战斗" in d["tags"]

    exp2 = Experience.from_dict(d)
    assert exp2.id == exp.id
    assert exp2.hash == exp.hash
    assert exp2.symptom == exp.symptom
    assert exp2.severity == exp.severity
    assert exp2.is_global == exp.is_global
    assert exp2.tags == exp.tags

    print("[PASS] test_serialization")


# ──────────────────────────────────────
# 13. 便捷函数
# ──────────────────────────────────────

def test_convenience_functions():
    """13. 便捷函数 get_knowledge_brain / check_before_write / record_experience"""
    import xiaoshuo.pipeline.knowledge_brain as kb_mod

    tmp_dir = Path(tempfile.mkdtemp(prefix="kb_conv_"))
    _TMP_DIRS.append(tmp_dir)
    kb_mod.KB_DIR = tmp_dir
    kb_mod.GLOBAL_EXP_PATH = tmp_dir / "global_experience.json"
    kb_mod.PROJECT_MEM_PATH = tmp_dir / "project_memory.json"
    kb_mod._kb_instance = None

    try:
        # record_experience
        exp_id = kb_mod.record_experience(
            symptom="便捷函数测试",
            root_cause="便捷函数根因",
            solution="便捷函数方案",
            severity="warning",
            tags=["测试"],
        )
        assert exp_id

        # get_knowledge_brain → 同一单例
        kb = kb_mod.get_knowledge_brain()
        assert kb.get_by_id(exp_id) is not None

        # check_before_write 便捷函数
        result = kb_mod.check_before_write("测试", {})
        assert result.count > 0

        print("[PASS] test_convenience_functions")
    finally:
        _cleanup()


# ──────────────────────────────────────
# 14. 持久化
# ──────────────────────────────────────

def test_persistence():
    """14. 保存后重新加载数据一致"""
    import xiaoshuo.pipeline.knowledge_brain as kb_mod

    tmp_dir = Path(tempfile.mkdtemp(prefix="kb_persist_"))
    _TMP_DIRS.append(tmp_dir)
    kb_mod.KB_DIR = tmp_dir
    kb_mod.GLOBAL_EXP_PATH = tmp_dir / "global_experience.json"
    kb_mod.PROJECT_MEM_PATH = tmp_dir / "project_memory.json"
    kb_mod._kb_instance = None

    try:
        kb1 = kb_mod.KnowledgeBrain()
        exp_id = kb1.record(
            symptom="持久化测试经验",
            root_cause="持久化根因",
            solution="持久化方案",
            severity="serious",
            tags=["持久化"],
            genre="末世",
        )
        # 触发晋升
        kb1.record(
            symptom="持久化重复",
            root_cause="持久化根因",
            severity="serious",
        )

        # 文件应存在
        assert kb_mod.GLOBAL_EXP_PATH.exists(), "全局经验文件应存在"
        assert kb_mod.PROJECT_MEM_PATH.exists(), "项目记忆文件应存在"

        # JSON 格式验证
        global_data = json.loads(kb_mod.GLOBAL_EXP_PATH.read_text(encoding="utf-8"))
        assert "experiences" in global_data
        assert len(global_data["experiences"]) == 1
        assert global_data["experiences"][0]["symptom"] == "持久化测试经验"

        # 重新加载
        kb2 = kb_mod.KnowledgeBrain()
        assert len(kb2.list_all()) == 1, "重载后应有 1 条 (晋升的全局)"

        exp = kb2.get_by_id(exp_id)
        assert exp is not None
        assert exp.symptom == "持久化测试经验"
        assert exp.is_global
        assert exp.occurrences == 2
        assert exp.genre == "末世"

        print("[PASS] test_persistence")
    finally:
        _cleanup()


# ──────────────────────────────────────
# 额外: 根因哈希归一化
# ──────────────────────────────────────

def test_hash_normalization():
    """额外: 根因哈希归一化 (标点/空格/大小写不敏感)"""
    from xiaoshuo.pipeline.knowledge_brain import _compute_hash

    h1 = _compute_hash("连续使用深吸一口气和目光扫过")
    h2 = _compute_hash("连续使用，深吸一口气，和，目光扫过")
    h3 = _compute_hash(" 连续使用深吸一口气和目光扫过 ")
    h4 = _compute_hash("连续使用深吸一口气和目光扫过。")

    assert h1 == h2, "标点不同应哈希相同"
    assert h1 == h3, "空格不同应哈希相同"
    assert h1 == h4, "末尾句号不影响哈希"
    assert len(h1) == 12, "哈希应为 12 位"

    # 不同根因
    h5 = _compute_hash("完全不同的根因")
    assert h1 != h5, "不同根因应哈希不同"

    print("[PASS] test_hash_normalization")


# ──────────────────────────────────────
# 额外: list_project 题材过滤
# ──────────────────────────────────────

def test_list_project_genre_filter():
    """额外: list_project 题材过滤"""
    kb = _make_kb()
    try:
        kb.record(symptom="末世经验", root_cause="末世根因", genre="末世")
        kb.record(symptom="都市经验", root_cause="都市根因", genre="都市")
        kb.record(symptom="通用经验", root_cause="通用根因")  # 无 genre

        all_project = kb.list_project()
        assert len(all_project) == 3

        # 按"末世"过滤: 应包含末世 + 通用
        filtered = kb.list_project(genre="末世")
        assert len(filtered) == 2
        genres = {e.genre for e in filtered}
        assert "末世" in genres
        assert "" in genres  # 通用经验 genre 为空

        print("[PASS] test_list_project_genre_filter")
    finally:
        _cleanup()


if __name__ == "__main__":
    test_record_basic()
    test_hash_dedup()
    test_auto_promote()
    test_check_before_write()
    test_check_empty_kb()
    test_manual_promote_demote()
    test_cleanup_stale()
    test_search()
    test_stats()
    test_format_for_prompt()
    test_format_for_writing_context()
    test_delete()
    test_serialization()
    test_convenience_functions()
    test_persistence()
    test_hash_normalization()
    test_list_project_genre_filter()
    print("\n[ALL PASS] Knowledge-Brain (P1.4) 17/17 tests passed!")
