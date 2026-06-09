"""
state_machine.py — S0→S4+++ 创作工作流状态机
============================================================
─ 文件定位 ─
.agents/核心模块之一。管理番茄小说创作流程的 10 阶段状态。
定义合法转换路径，防状态跳跃/死循环/无限重试。

─ 状态流转图 ─
S0(大纲) → S1(创意引导) → S2a(手写初稿) → S2b(卡文?)/S2c(对比)
  → S2d(精修) → S3(虚拟评审) → S4+++(七层检测) → PUBLISH / S2d(重写)

─ 关键约束 ─
· S3 BLOCK → 必须回 S2d 重写（最多 2 次）
· S2b 解锁条件: 手写 ≥500 字 + ≥3 段
· 每日 LLM 调用上限 50 次（防循环 bug）
· 状态变化持久化到 state.json

─ 对外接口 ─
from state_machine import Stage, StateMachine, get_machine
sm = get_machine()
sm.transition(Stage.S1)          # 转移到指定阶段
current = sm.current            # 当前阶段
sm.can_proceed_to(Stage.S3)     # 检查能否转移

─ 开发者指引 ─
· 新增阶段: 在 Stage 枚举 + TRANSITIONS 表 + valid_destinations 中添加
· 阶段特定逻辑: 在 CANONICAL_TRANSITIONS 的注释中标注前置条件
"""

from enum import Enum
from pathlib import Path
from typing import Optional, Set
import json
import os
import tempfile
import time
import yaml


# ============================================================
# 阶段枚举 — 10 个创作阶段
# ============================================================
class Stage(Enum):
    """创作工作流的 10 个阶段。每个阶段有明确的进入/退出条件。"""
    INIT = "INIT"                # 项目初始化完成，等待开始
    S0 = "S0"                    # 大纲生成 & 反同质化检查
    S1 = "S1"                    # 创意引导（多温度变体）
    S2a = "S2a"                  # 作者手写初稿
    S2b = "S2b"                  # AI 参考版（仅卡文时，需解锁）
    S2c = "S2c"                  # 对比分析
    S2d = "S2d"                  # 作者精修
    S3 = "S3"                    # 虚拟评审团（逻辑警察 + 编辑 + 质检）
    S4 = "S4"                    # S4+++ 七层 AI 风格检测
    PUBLISH = "PUBLISH"          # 发布到番茄平台


# ============================================================
# 合法转移表 — 防状态跳跃
# ============================================================
# key = 源阶段, value = 可以转移到的目标阶段集合
# 不在表中的转移 = 非法，直接拒绝
TRANSITIONS: dict[Stage, Set[Stage]] = {
    Stage.INIT:    {Stage.S0},
    Stage.S0:      {Stage.S1},
    Stage.S1:      {Stage.S2a},
    Stage.S2a:     {Stage.S2b, Stage.S2c},          # 卡文时可进 S2b，否则跳过
    Stage.S2b:     {Stage.S2a, Stage.S2c},          # S2b 后可回 S2a 或进 S2c
    Stage.S2c:     {Stage.S2d},
    Stage.S2d:     {Stage.S3},
    Stage.S3:      {Stage.S4, Stage.S2d},           # BLOCK → 回 S2d 重写
    Stage.S4:      {Stage.PUBLISH, Stage.S2d},      # FATAL → 回 S2d 重写
    Stage.PUBLISH: {Stage.S1},                      # 下一章 → 进入 S1
}


# ============================================================
# 阶段元数据 — 每个阶段的说明、前置条件、LLM 角色
# ============================================================
STAGE_META: dict[Stage, dict] = {
    Stage.INIT: {
        "name": "初始化",
        "desc": "项目骨架已就绪，等待开始创作",
        "llm_role": None,
        "auto_next": False,          # 是否自动进入下一阶段
    },
    Stage.S0: {
        "name": "大纲 & 反同质化",
        "desc": "生成粗纲，检查与平台热门作品的重合度",
        "llm_role": "S1_creative",   # 用创意模型生成大纲
        "auto_next": False,
    },
    Stage.S1: {
        "name": "创意引导",
        "desc": "多温度变体生成剧情方向，作者选择方向",
        "llm_role": "S1_creative",
        "auto_next": False,
    },
    Stage.S2a: {
        "name": "手写初稿",
        "desc": "作者 100% 手写本章正文",
        "llm_role": None,
        "min_words": 0,              # 不强制，但建议 ≥2000
        "auto_next": False,
    },
    Stage.S2b: {
        "name": "AI 参考版",
        "desc": "仅卡文时启用。3 方向模糊建议，不提供具体文字",
        "llm_role": "S2b_reference",
        "unlock_words": 500,         # 手写 ≥500 字才能解锁
        "unlock_segments": 3,        # 手写 ≥3 段才能解锁
        "auto_next": False,
    },
    Stage.S2c: {
        "name": "对比分析",
        "desc": "作者版本 vs AI 参考版的结构化对比",
        "llm_role": None,            # 纯文本 diff，不需要 LLM
        "auto_next": False,
    },
    Stage.S2d: {
        "name": "作者精修",
        "desc": "根据对比分析结果，作者自主修改",
        "llm_role": None,
        "auto_next": False,
    },
    Stage.S3: {
        "name": "虚拟评审团",
        "desc": "逻辑警察(←因果) + 网文编辑(+节奏) + 语言质检(∥风格)",
        "llm_role": "S3_logic_cop",  # 逻辑警察为主，编辑/质检并行
        "max_retries": 2,            # BLOCK 后最多退回 S2d 两次
        "auto_next": True,           # PASS → 自动进入 S4
    },
    Stage.S4: {
        "name": "七层 AI 检测",
        "desc": "PPL + 突发性 + AI词共现 + 句长变异 + 句法重复 + 语义连贯 + N-gram PPL",
        "llm_role": "S4_detection",
        "max_retries": 2,            # FATAL 后最多退回 S2d 两次
        "auto_next": True,           # SAFE → 自动进入 PUBLISH
    },
    Stage.PUBLISH: {
        "name": "发布",
        "desc": "发布到番茄平台。字数随机浮动 ±200-300",
        "llm_role": None,
        "auto_next": True,           # 下一章 → S1
    },
}


# ============================================================
# StateMachine: 状态机核心
# ============================================================
class StateMachine:
    """管理创作流程的 10 阶段状态。

    用法:
        sm = StateMachine()
        sm.transition(Stage.S1)          # 从 INIT 转移到 S1
        sm.current                        # → Stage.S1
        sm.can_transition_to(Stage.S3)    # → False (必须先经过 S2a/S2d)

    持久化:
        状态变化自动写入 PROJECT_ROOT/state.json
        重启后从 state.json 恢复上次状态

    熔断:
        S3/S4 最多退回重写 2 次，超过 2 次 → 必须人工介入
        每日 LLM 调用计数监控，超限 → 拒绝 LLM 调用
    """

    # ── 持久化路径 ──
    STATE_PATH = Path(__file__).resolve().parent.parent / "state.json"
    CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"

    def __init__(self, load_persisted: bool = True):
        self._current: Stage = Stage.INIT
        self._chapter: int = 0
        self._retry_count: dict[str, int] = {}   # {stage_name: retry_count}
        self._daily_llm_calls: int = 0
        self._last_date: str = ""                # 用于每日计数重置
        self._max_llm_calls: int = 50            # 从 config 读取
        self._max_retries_s3: int = 2
        self._max_retries_s4: int = 2
        self._load_config()
        if load_persisted:
            self._load_state()

    # ── 属性 ──

    @property
    def current(self) -> Stage:
        """当前阶段。"""
        return self._current

    @property
    def chapter(self) -> int:
        """当前章节号。"""
        return self._chapter

    @property
    def meta(self) -> dict:
        """当前阶段的元数据。"""
        return STAGE_META.get(self._current, {})

    # ── 转移 ──

    def transition(self, target: Stage) -> bool:
        """从当前阶段转移到目标阶段。

        Args:
            target: 目标阶段（Stage 枚举值）

        Returns:
            True=转移成功, False=非法转移

        检查:
            1. 目标阶段是否在合法转移表中
            2. 是否有额外前置条件（如 S2b 的手写字数）
            3. S3/S4 退回时是否超最大重试次数
        """
        # 1. 合法性检查
        if target not in TRANSITIONS.get(self._current, set()):
            print(f"[BLOCK] 非法转移: {self._current.value} → {target.value}")
            return False

        # 2. 退回重试次数检查（从 config 读取上限）
        if target == Stage.S2d and self._current in (Stage.S3, Stage.S4):
            stage_name = self._current.value
            retries = self._retry_count.get(stage_name, 0)
            max_retries = self._max_retries_s3 if self._current == Stage.S3 else self._max_retries_s4
            if retries >= max_retries:
                print(f"[BLOCK] {self._current.value} 已退回 {max_retries} 次，必须人工介入")
                return False
            self._retry_count[stage_name] = retries + 1

        # 3. 执行转移
        old = self._current
        self._current = target

        # 4. PUBLISH → 下一章自动进 S1
        if target == Stage.PUBLISH:
            self._chapter += 1
            self._current = Stage.S1  # 自动滚到下一章的 S1

        # 5. 持久化
        self._save_state()

        print(f"[OK] 阶段转移: {old.value} → {target.value} (第 {self._chapter} 章)")
        return True

    def can_transition_to(self, target: Stage) -> bool:
        """检查能否转移到目标阶段（不实际执行）。"""
        return target in TRANSITIONS.get(self._current, set())

    def valid_destinations(self) -> Set[Stage]:
        """返回当前阶段可以转移到的所有目标阶段。"""
        return TRANSITIONS.get(self._current, set())

    # ── S2b 解锁条件 ──

    def can_unlock_s2b(self, handwritten_words: int, handwritten_segments: int) -> bool:
        """检查 S2b（AI参考版）是否满足解锁条件。

        Args:
            handwritten_words: 作者已手写字数
            handwritten_segments: 作者已手写段落数

        Returns:
            True=满足解锁条件
        """
        meta = STAGE_META[Stage.S2b]
        required_words = meta.get("unlock_words", 500)
        required_segments = meta.get("unlock_segments", 3)
        return (handwritten_words >= required_words
                and handwritten_segments >= required_segments)

    # ── S3 熔断 ──

    def next_s3_result(self, verdict: str) -> Optional[Stage]:
        """处理 S3 评审结果，返回下一步阶段。

        Args:
            verdict: PASS | WARNING | BLOCK

        Returns:
            None → 非法 verdict
            Stage.S4 → PASS/WARNING, 进入检测
            Stage.S2d → BLOCK, 退回重写
        """
        if verdict == "PASS" or verdict == "WARNING":
            return Stage.S4
        elif verdict == "BLOCK":
            return Stage.S2d
        return None

    # ── S4 熔断 ──

    def next_s4_result(self, verdict: str) -> Optional[Stage]:
        """处理 S4+++ 检测结果，返回下一步阶段。

        Args:
            verdict: SAFE | WARNING | FATAL

        Returns:
            None → 非法 verdict
            Stage.PUBLISH → SAFE, 发布
            Stage.S2d → FATAL, 退回重写
        """
        if verdict == "SAFE":
            return Stage.PUBLISH
        elif verdict == "WARNING":
            return Stage.PUBLISH  # WARNING 仍然可以发布
        elif verdict == "FATAL":
            return Stage.S2d
        return None

    # ── 每日 LLM 调用计数 ──

    def _load_config(self):
        """从 config.yaml 读取熔断参数。"""
        try:
            with open(self.CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            cb = cfg.get("circuit_breaker", {})
            self._max_llm_calls = cb.get("max_daily_llm_calls", 50)
            self._max_retries_s3 = cb.get("max_s3_retries_per_chapter", 2)
            self._max_retries_s4 = self._max_retries_s3  # S4 使用相同值
        except Exception as e:
            print(f"  [WARN] config.yaml读取失败({e}), 使用默认熔断参数")

    def can_call_llm(self, daily_limit: Optional[int] = None) -> bool:
        """检查是否达到每日 LLM 调用上限。

        防止 prompt 循环 bug 导致无限调用 LLM。

        Args:
            daily_limit: 每日上限，默认 50 次
        """
        today = time.strftime("%Y-%m-%d")
        if today != self._last_date:
            self._daily_llm_calls = 0
            self._last_date = today
        limit = daily_limit if daily_limit is not None else self._max_llm_calls
        return self._daily_llm_calls < limit

    def record_llm_call(self):
        """记录一次 LLM 调用（每次聊天请求后调用）。"""
        today = time.strftime("%Y-%m-%d")
        if today != self._last_date:
            self._daily_llm_calls = 0
            self._last_date = today
        self._daily_llm_calls += 1

    # ── 状态持久化 ──

    def _load_state(self):
        """从 state.json 恢复状态。"""
        if not self.STATE_PATH.exists():
            return
        try:
            with open(self.STATE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 恢复阶段
            stage_str = data.get("current_stage", "INIT")
            try:
                self._current = Stage(stage_str)
            except ValueError:
                self._current = Stage.INIT
            self._chapter = data.get("current_chapter", 0)
            self._retry_count = data.get("retry_counts", {})
        except (json.JSONDecodeError, KeyError):
            pass

    def _save_state(self):
        """将当前状态写入 state.json。"""
        # 读取现有状态（保留其他字段）
        if self.STATE_PATH.exists():
            try:
                with open(self.STATE_PATH, "r", encoding="utf-8") as f:
                    state = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                state = {}
        else:
            state = {}

        # 更新状态机相关字段
        state["current_stage"] = self._current.value
        state["current_chapter"] = self._chapter
        state["retry_counts"] = self._retry_count
        state["daily_llm_calls"] = self._daily_llm_calls
        state["last_date"] = self._last_date

        # Atomic write via temp file (avoid concurrent corruption)
        fd, tmp = tempfile.mkstemp(suffix=".json", dir=self.STATE_PATH.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.STATE_PATH)  # atomic on Windows/Linux
        except Exception:
            Path(tmp).unlink(missing_ok=True)
            raise

    # ── 调试 ──

    def summary(self) -> str:
        """返回当前状态的可读摘要。"""
        dests = [d.value for d in self.valid_destinations()]
        meta = STAGE_META.get(self._current, {})
        return (
            f"第 {self._chapter} 章 | {self._current.value} ({meta.get('name', '?')})\n"
            f"可转移到: {', '.join(dests) if dests else '(终态)'}\n"
            f"每日 LLM 调用: {self._daily_llm_calls}\n"
            f"重试计数: {self._retry_count}"
        )


# ============================================================
# 单例工厂
# ============================================================
def get_machine() -> StateMachine:
    """获取全局唯一的 StateMachine 实例。"""
    return StateMachine()


# ============================================================
# 模块自检
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("  state_machine.py — 自检")
    print("=" * 60)

    sm = StateMachine(load_persisted=False)

    # 1. 初始状态
    print(f"\n[TEST] 初始状态: {sm.current.value}")
    assert sm.current == Stage.INIT

    # 2. 合法转移: INIT → S0 → S1 → S2a → S2c → S2d → S3 → S4 → PUBLISH
    print("[TEST] 完整流程 (正向)...")
    path = [Stage.S0, Stage.S1, Stage.S2a, Stage.S2c, Stage.S2d, Stage.S3, Stage.S4, Stage.PUBLISH]
    for stage in path:
        assert sm.transition(stage), f"[FAIL] {sm.current.value} → {stage.value} 被拒绝"
    print(f"  [OK] 完整正向流程通过，当前: {sm.current.value}")

    # 3. PUBLISH 后自动进入 S1（下一章）
    assert sm.current == Stage.S1, f"[FAIL] PUBLISH 后应为 S1，实际: {sm.current.value}"
    assert sm.chapter == 1, f"[FAIL] 章节号应为 1，实际: {sm.chapter}"
    print(f"  [OK] PUBLISH → S1, 章节号: {sm.chapter}")

    # 4. 非法转移应被拒绝
    print("[TEST] 非法转移...")
    assert not sm.transition(Stage.S3), "[FAIL] S1→S3 应被拒绝（跳过 S2a/S2d）"
    assert not sm.transition(Stage.PUBLISH), "[FAIL] S1→PUBLISH 应被拒绝"
    print("  [OK] 非法转移被正确拒绝")

    # 5. S3 BLOCK → 退回 S2d
    sm2 = StateMachine(load_persisted=False)
    for s in [Stage.S0, Stage.S1, Stage.S2a, Stage.S2c, Stage.S2d, Stage.S3]:
        sm2.transition(s)
    assert sm2.current == Stage.S3
    next_stage = sm2.next_s3_result("BLOCK")
    assert next_stage == Stage.S2d, f"[FAIL] S3 BLOCK 应退回 S2d, 实际: {next_stage}"
    print(f"  [OK] S3 BLOCK → 退回 {next_stage.value}")

    # 6. S3 PASS → S4
    next_stage = sm2.next_s3_result("PASS")
    assert next_stage == Stage.S4
    print(f"  [OK] S3 PASS → {next_stage.value}")

    # 7. S4 FATAL → S2d, S4 SAFE → PUBLISH
    sm2.transition(Stage.S4)
    assert sm2.next_s4_result("FATAL") == Stage.S2d
    assert sm2.next_s4_result("SAFE") == Stage.PUBLISH
    assert sm2.next_s4_result("WARNING") == Stage.PUBLISH
    print(f"  [OK] S4 FATAL→S2d, SAFE/WARNING→PUBLISH")

    # 8. 退回次数限制
    print("[TEST] S3 退回次数限制...")
    sm3 = StateMachine(load_persisted=False)
    # 走流程到 S3
    for s in [Stage.S0, Stage.S1, Stage.S2a, Stage.S2c, Stage.S2d, Stage.S3]:
        sm3.transition(s)
    # 退回 2 次
    assert sm3.transition(Stage.S2d)  # 第1次退回 OK
    sm3.transition(Stage.S3)           # 再提交
    assert sm3.transition(Stage.S2d)  # 第2次退回 OK
    sm3.transition(Stage.S3)           # 再提交
    assert not sm3.transition(Stage.S2d)  # 第3次应被拒绝
    print("  [OK] 第3次退回被正确拦截")

    # 9. LLM 调用计数
    print("[TEST] LLM 调用计数...")
    sm4 = StateMachine(load_persisted=False)
    assert sm4.can_call_llm(daily_limit=50)
    for _ in range(50):
        sm4.record_llm_call()
    assert not sm4.can_call_llm(daily_limit=50), "[FAIL] 50次后应拒绝"
    print("  [OK] 50次上限正确生效")

    # 10. valid_destinations
    assert Stage.S2b not in sm.valid_destinations(), "[FAIL] S1 不能直接进 S2b"
    print(f"  [OK] valid_destinations: {[d.value for d in sm.valid_destinations()]}")

    # 11. S2b 解锁条件
    assert sm.can_unlock_s2b(600, 4), "[FAIL] 600字+4段应解锁"
    assert not sm.can_unlock_s2b(400, 4), "[FAIL] 400字不应解锁"
    assert not sm.can_unlock_s2b(600, 2), "[FAIL] 2段不应解锁"
    print("  [OK] S2b解锁条件正确")

    # 12. 未知 verdict
    assert sm2.next_s3_result("INVALID") is None
    assert sm2.next_s4_result("INVALID") is None
    print("  [OK] 非法 verdict 返回 None")

    print(f"\n[DONE] state_machine.py 自检完成")
