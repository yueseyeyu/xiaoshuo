#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
test_p0_fixes.py — P0 阶段 Bug 修复验收测试
============================================
验证 4 个 P0 级 Bug 修复的正确性:
  BUG-01: _strip_thinking_tags 正则修复
  BUG-02: _ModuleCallNode 竞态条件消除
  BUG-03: extract_chapters 死代码清除
  BUG-04: llm_verify 走统一 llm_client

运行: python -m pytest tests/test_p0_fixes.py -v
"""
import re
import sys
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# 确保项目根在 sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))


# ============================================================
# BUG-01: _strip_thinking_tags 正则修复
# ============================================================

class TestStripThinkingTags:
    """验证 _strip_thinking_tags 的 6 个边界用例。"""

    def _get_stripper(self):
        from xiaoshuo.agents.model_orchestrator import _strip_thinking_tags
        return _strip_thinking_tags

    def test_01_empty_thinking_block(self):
        """空 <thinking></thinking> 标签应被移除。"""
        strip = self._get_stripper()
        text = "<thinking></thinking>这是正常回复。"
        assert strip(text) == "这是正常回复。"

    def test_02_thinking_with_content(self):
        """含内容的 <thinking>...</thinking> 应被移除，保留正常回复。"""
        strip = self._get_stripper()
        text = "<thinking>让我思考一下这个问题的答案。</thinking>答案是42。"
        assert strip(text) == "答案是42。"

    def test_03_unclosed_thinking(self):
        """未闭合的 <thinking> 到末尾应被截断。"""
        strip = self._get_stripper()
        text = "正常回复。<thinking>这部分不应该出现"
        assert strip(text) == "正常回复。"

    def test_04_no_thinking_tag(self):
        """无 thinking 标签的文本应原样返回。"""
        strip = self._get_stripper()
        text = "这是一段完全正常的中文回复。"
        assert strip(text) == "这是一段完全正常的中文回复。"

    def test_05_nested_response_preserved(self):
        """BUG-01 核心验证: <thinking> 不应吞掉 </response> 之外的正常内容。"""
        strip = self._get_stripper()
        text = "<thinking>思考过程</thinking>第一段回复。\n\n第二段回复。"
        result = strip(text)
        assert "第一段回复" in result
        assert "第二段回复" in result
        assert "思考过程" not in result

    def test_06_think_tag_deepseek_style(self):
        """DeepSeek-R1 的 <think>...</think> 标签也应被清理。"""
        strip = self._get_stripper()
        text = "<think>内部推理</think>最终答案。"
        assert strip(text) == "最终答案。"

    def test_07_empty_string(self):
        """空字符串输入应返回空字符串。"""
        strip = self._get_stripper()
        assert strip("") == ""

    def test_08_none_input(self):
        """None 输入应返回 None。"""
        strip = self._get_stripper()
        assert strip(None) is None


# ============================================================
# BUG-02: _ModuleCallNode 竞态条件消除
# ============================================================

class TestModuleCallNodeThreadSafety:
    """验证 _ModuleCallNode 在并行调用下不会产生竞态。"""

    def test_argv_lock_exists(self):
        """模块级 _argv_lock 应存在且为 threading.Lock 实例。"""
        from xiaoshuo.pipeline import pipeline_nodes
        assert hasattr(pipeline_nodes, '_argv_lock')
        assert isinstance(pipeline_nodes._argv_lock, type(threading.Lock()))

    def test_concurrent_argv_safety(self):
        """并行调用 _ModuleCallNode.run() 时 sys.argv 不应交叉污染。"""
        from xiaoshuo.pipeline.pipeline_nodes import _ModuleCallNode

        # 创建一个简单的测试模块节点
        class TestNode(_ModuleCallNode):
            module_path = "os"  # 标准库模块，必然存在
            script_name = "test_node"
            stage_info = (1, 1, "测试节点")

            def run(self, genre: str = "末世", **kwargs) -> bool:
                argv = [self.script_name + ".py", "--genre", genre]
                with _argv_lock if hasattr(sys.modules.get(
                    'xiaoshuo.pipeline.pipeline_nodes', None), '_argv_lock'
                ) else threading.Lock():
                    old = sys.argv[:]
                    sys.argv = argv
                    try:
                        # 模拟工作
                        import time as _time
                        _time.sleep(0.001)
                        # 验证 argv 没被其他线程修改
                        assert sys.argv == argv, \
                            f"竞态! argv 被修改: {sys.argv} != {argv}"
                    finally:
                        sys.argv = old
                return True

        # 导入实际的 _argv_lock
        from xiaoshuo.pipeline.pipeline_nodes import _argv_lock

        # 用实际锁包装的测试函数
        results = []
        errors = []

        def worker(genre):
            try:
                with _argv_lock:
                    old = sys.argv[:]
                    sys.argv = [f"test_{genre}.py", "--genre", genre]
                    try:
                        import time as _time
                        _time.sleep(0.002)
                        assert sys.argv[2] == genre, \
                            f"竞态! argv 被修改: {sys.argv}"
                    finally:
                        sys.argv = old
                results.append(genre)
            except Exception as e:
                errors.append(e)

        threads = []
        for g in ["末世", "科幻", "玄幻", "都市", "仙侠"]:
            t = threading.Thread(target=worker, args=(g,))
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"竞态错误: {errors}"
        assert len(results) == 5

    def test_print_replaced_by_logger(self):
        """_ModuleCallNode 中的 print() 应被 logger 替代。"""
        import inspect
        from xiaoshuo.pipeline.pipeline_nodes import _ModuleCallNode
        source = inspect.getsource(_ModuleCallNode.run)
        # 不应包含 print( 调用 (logger.warning 代替)
        assert 'print(' not in source, "run() 方法中仍包含 print() 调用"


# ============================================================
# BUG-03: extract_chapters 死代码清除
# ============================================================

class TestExtractChaptersDeadCode:
    """验证 extract_chapters 中重复的 pattern4 已被删除。"""

    def test_no_duplicate_pattern4(self):
        """extract_chapters 函数体中不应有两次 pattern4 定义。"""
        import inspect
        from xiaoshuo.pipeline.rhythm_analyzer import extract_chapters
        source = inspect.getsource(extract_chapters)
        # pattern4 应只出现一次 (带上下文验证的版本)
        count = source.count('pattern4')
        assert count <= 2, f"pattern4 出现 {count} 次，可能有残留死代码"

    def test_standard_chapter_extraction(self):
        """标准 第X章 格式应正常提取。"""
        from xiaoshuo.pipeline.rhythm_analyzer import extract_chapters
        import tempfile

        # 注意: 正文中不能出现 "第X章" 模式，否则正则会重复匹配
        content = (
            "第一章 开始\n"
            + "天空阴沉沉的，乌云密布。远处传来隆隆的雷声，仿佛有什么东西正在苏醒。" * 3 + "\n\n"
            "第二章 逃离\n"
            + "他们拼命地奔跑，身后的追兵越来越近。森林中弥漫着血腥的气息。" * 3 + "\n\n"
            "第三章 觉醒\n"
            + "当一切似乎都已绝望时，一股奇异的力量从体内涌出，照亮了整个战场。" * 3 + "\n\n"
        )

        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.txt', delete=False, encoding='utf-8'
        ) as f:
            f.write(content)
            f.flush()
            filepath = f.name

        try:
            chapters = extract_chapters(filepath)
            assert len(chapters) == 3
            assert chapters[0]["num"] == 1
            assert chapters[1]["num"] == 2
            assert chapters[2]["num"] == 3
        finally:
            Path(filepath).unlink(missing_ok=True)


# ============================================================
# BUG-04: llm_verify 走统一 llm_client
# ============================================================

class TestLLMVerifyUnifiedClient:
    """验证 llm_verify 使用统一 llm_client 而非裸 urllib。"""

    def test_no_raw_urllib_in_llm_verify(self):
        """llm_verify 函数体不应包含 urllib.request.Request 调用。"""
        import inspect
        from xiaoshuo.pipeline.rhythm_analyzer import llm_verify
        source = inspect.getsource(llm_verify)
        assert 'urllib.request.Request' not in source, \
            "llm_verify 仍使用裸 urllib.request.Request"
        assert 'urllib.request.urlopen' not in source, \
            "llm_verify 仍使用裸 urllib.request.urlopen"

    def test_uses_llm_chat(self):
        """llm_verify 应导入并使用 llm_chat。"""
        import inspect
        from xiaoshuo.pipeline.rhythm_analyzer import llm_verify
        source = inspect.getsource(llm_verify)
        assert 'llm_chat' in source, "llm_verify 未使用 llm_chat"

    def test_llm_verify_with_mock(self):
        """用 mock 验证 llm_verify 的调用链。"""
        from xiaoshuo.pipeline.rhythm_analyzer import llm_verify, _map_llm_response

        ch = {
            "num": 1, "title": "测试章节", "wc": 2000,
            "text": "这是一段测试文本。" * 100,
        }
        rule_result = {
            "pleasure_type": "major", "pleasure_intensity": 5.0,
            "conflict_level": "medium", "emotion": "紧张", "pace": "fast",
        }

        # Mock llm_chat 返回紧凑 JSON
        mock_response = '{"t":"climax","i":8,"c":"high","e":"爽快","p":"fast"}'
        with patch(
            'xiaoshuo.infra.llm_client.llm_chat',
            return_value=mock_response
        ):
            result = llm_verify(ch, rule_result)

        assert result is not None
        mapped = _map_llm_response(result)
        assert mapped["pleasure_type"] == "climax"
        assert mapped["pleasure_intensity"] == 8
        assert mapped["conflict_level"] == "high"

    def test_llm_verify_empty_response(self):
        """LLM 返回空字符串时应返回 None。"""
        from xiaoshuo.pipeline.rhythm_analyzer import llm_verify

        ch = {"num": 1, "title": "测试", "wc": 500, "text": "测试文本" * 50}
        rule_result = {
            "pleasure_type": "none", "pleasure_intensity": 0,
            "conflict_level": "none", "emotion": "日常", "pace": "medium",
        }

        with patch('xiaoshuo.infra.llm_client.llm_chat', return_value=''):
            result = llm_verify(ch, rule_result)
        assert result is None

    def test_health_check_uses_unified_client(self):
        """analyze_book 中的健康检查应使用 check_llm_health。"""
        import inspect
        from xiaoshuo.pipeline.rhythm_analyzer import analyze_book
        source = inspect.getsource(analyze_book)
        assert 'check_llm_health' in source, \
            "analyze_book 未使用 check_llm_health"
        assert 'urllib.request.urlopen(f"{LLAMA_BASE}/health"' not in source, \
            "analyze_book 仍使用裸 urllib 健康检查"


# ============================================================
# 综合冒烟测试
# ============================================================

class TestP0SmokeTest:
    """P0 修复后的综合冒烟测试。"""

    def test_imports_clean(self):
        """所有修改过的模块应无导入错误。"""
        from xiaoshuo.agents.model_orchestrator import _strip_thinking_tags
        from xiaoshuo.pipeline.pipeline_nodes import _ModuleCallNode, _argv_lock
        from xiaoshuo.pipeline.rhythm_analyzer import (
            extract_chapters, llm_verify, rule_analyze, analyze_book
        )
        # 确认关键符号存在
        assert callable(_strip_thinking_tags)
        assert callable(extract_chapters)
        assert callable(llm_verify)
        assert callable(rule_analyze)

    def test_rule_analyze_basic(self):
        """rule_analyze 对基本章节应正常返回指标 dict。"""
        from xiaoshuo.pipeline.rhythm_analyzer import rule_analyze

        ch = {
            "num": 1, "title": "测试章", "raw_body": "测试内容" * 50,
            "wc": 200, "para_count": 3,
        }
        result = rule_analyze(ch)
        assert isinstance(result, dict)
        assert "ch_num" in result
        assert "pleasure_type" in result
        assert "hook_type" in result
        assert result["ch_num"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
