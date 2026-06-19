# -*- coding: utf-8 -*-
"""
tests/smoke_test.py — 集成冒烟测试
===================================
v7.5: 验证完整管线各阶段的核心功能可用。
- 不依赖 LLM（不用启动模型）
- 不依赖外部数据（用硬编码样本）
- 可以作为 CI 的一部分运行

用法: python tests/smoke_test.py
"""

import sys
import os
import json
import tempfile
import shutil
from pathlib import Path

# 确保 src/ 在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def test_imports():
    """测试所有核心模块可以正常导入。"""
    modules = [
        ("xiaoshuo", "xiaoshuo"),
        ("xiaoshuo.infra.logging_config", "logging_config"),
        ("xiaoshuo.infra.config_manager", "config_manager"),
        ("xiaoshuo.infra.performance", "performance"),
        ("xiaoshuo.infra.schemas", "schemas"),
        ("xiaoshuo.agents.world_builder", "world_builder"),
        ("xiaoshuo.agents.outline_builder", "outline_builder"),
        ("xiaoshuo.pipeline.book_processor", "book_processor"),
        ("xiaoshuo.pipeline.checkpoint", "checkpoint"),
        ("xiaoshuo.pipeline.contract_chain", "contract_chain"),
        ("xiaoshuo.pipeline.genre_synthesizer", "genre_synthesizer"),
        ("xiaoshuo.pipeline.scoring", "scoring"),
        ("xiaoshuo.pipeline.scoring.commercial_engine", "commercial_engine"),
        ("xiaoshuo.pipeline.scoring.borda_ranker", "borda_ranker"),
    ]
    passed = 0
    failed = 0
    for mod_name, label in modules:
        try:
            __import__(mod_name)
            print(f"  [OK] {label}")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {label}: {e}")
            failed += 1
    return passed, failed


def test_config():
    """测试配置加载。"""
    from xiaoshuo.infra.config_manager import get_config, get_config_section
    cfg = get_config()
    assert isinstance(cfg, dict), "config should be dict"
    assert "model_orchestration" in cfg, "config should have model_orchestration"

    # 嵌套读取
    port = get_config_section("model_orchestration", "models", "main_model", "port")
    assert port is not None, "should read nested config"
    print(f"  [OK] config loaded: port={port}")
    return 1, 0


def test_logging():
    """测试日志系统。"""
    from xiaoshuo.infra.logging_config import get_logger
    logger = get_logger("smoke_test")
    logger.info("smoke test logging [OK]")
    print(f"  [OK] logging works")
    return 1, 0


def test_schemas():
    """测试 Schema 校验。"""
    from xiaoshuo.infra.schemas import validate_state, validate_novel_index

    # 正常 state
    valid_state = {
        "current_chapter": 5,
        "current_stage": "S2a",
        "history": [],
        "total_chapters": 300,
    }
    validate_state(valid_state)
    print(f"  [OK] state schema valid")

    # 异常 state
    try:
        validate_state({"current_chapter": "bad"})
        print(f"  [FAIL] should have raised ValueError")
        return 0, 1
    except ValueError:
        print(f"  [OK] state schema invalid caught")

    # 正常 novel_index
    valid_index = [{
        "title": "Test Book",
        "genre": "末世",
        "path": "/tmp/test.txt",
        "size_kb": 500,
        "chapters": 100,
        "quality": "PASS",
        "added": "2026-01-01",
    }]
    validate_novel_index(valid_index)
    print(f"  [OK] novel_index schema valid")
    return 2, 0


def test_performance():
    """测试性能装饰器。"""
    from xiaoshuo.infra.performance import timed, PipelineTimer

    @timed(label="smoke_test")
    def _slow():
        import time
        time.sleep(0.01)

    _slow()
    print(f"  [OK] @timed decorator")

    pt = PipelineTimer("smoke_stage")
    pt.start()
    pt.stop()
    assert pt.elapsed >= 0, "timer should have elapsed"
    print(f"  [OK] PipelineTimer")
    return 2, 0


def test_checkpoint():
    """测试断点续跑。"""
    from xiaoshuo.pipeline.checkpoint import is_done, mark_done, reset_all, CHECKPOINT_DIR

    with tempfile.TemporaryDirectory() as tmp:
        import xiaoshuo.pipeline.checkpoint as cp
        old_dir = cp.CHECKPOINT_DIR
        cp.CHECKPOINT_DIR = Path(tmp)

        try:
            assert not is_done("book_processor")
            mark_done("book_processor")
            assert is_done("book_processor")
            reset_all()
            assert not is_done("book_processor")
            print(f"  [OK] checkpoint works")
            return 1, 0
        finally:
            cp.CHECKPOINT_DIR = old_dir


def test_contract_chain():
    """测试合同链数据结构。"""
    from xiaoshuo.pipeline.contract_chain import (
        ContractSeed, DebtBoard, ChapterCommit,
    )
    seed = ContractSeed(book_name="smoke_test")
    assert seed.book_name == "smoke_test"
    print(f"  [OK] ContractSeed")

    board = DebtBoard(book_name="smoke_test")
    initial_count = len(board.debts)
    board.add_debt(10, "伏笔", "测试债务", severity="high")
    assert len(board.debts) == initial_count + 1, f"debts should increase by 1"
    print(f"  [OK] DebtBoard")

    commit = ChapterCommit("smoke_test", 1, "测试正文内容", {"rhythm": "data"})
    assert commit.chapter_num == 1
    print(f"  [OK] ChapterCommit")
    return 3, 0


def test_genre_detection():
    """测试题材检测加载。"""
    from xiaoshuo.pipeline.book_processor import _load_genre_config
    gcfg = _load_genre_config()
    assert len(gcfg["genre_keywords"]) >= 10, f"should have >=10 genres, got {len(gcfg['genre_keywords'])}"
    assert len(gcfg["title_rules"]) >= 30, f"should have >=30 title rules, got {len(gcfg['title_rules'])}"
    print(f"  [OK] genre config: {len(gcfg['genre_keywords'])} genres, {len(gcfg['title_rules'])} rules")
    return 1, 0


def main():
    print("=" * 60)
    print("  Smoke Test — 番茄小说 AI 辅助创作系统 v7.5")
    print("=" * 60)

    tests = [
        ("Imports", test_imports),
        ("Config", test_config),
        ("Logging", test_logging),
        ("Schemas", test_schemas),
        ("Performance", test_performance),
        ("Checkpoint", test_checkpoint),
        ("Contract Chain", test_contract_chain),
        ("Genre Detection", test_genre_detection),
    ]

    total_pass = 0
    total_fail = 0
    for name, func in tests:
        print(f"\n[{name}]")
        try:
            p, f = func()
            total_pass += p
            total_fail += f
        except Exception as e:
            print(f"  [FAIL] {name}: {e}")
            import traceback
            traceback.print_exc()
            total_fail += 1

    print(f"\n{'=' * 60}")
    print(f"  Result: {total_pass} passed / {total_fail} failed")
    print(f"{'=' * 60}")

    if total_fail > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()