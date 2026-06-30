# -*- coding: utf-8 -*-
"""
red_line_principles.py — 红线原则库 (P2.1)
=============================================
来源: 建议文件 "女娲造人 → 红线原则 → 动态创作禁忌系统"

核心功能:
  1. 红线原则管理: 每部作品/每位作者的创作底线与禁忌
  2. 实时检测: 本章是否触碰了目标红线?
  3. 警告 + 替代方案: 触碰红线时给出警告和建议
  4. 显式确认: 作者想打破红线时要求确认

与现有模块的关系:
  - canon/consistency_checker.py: 检查正文与 canon 设定是否一致 (事实层)
  - red_line_principles: 检查正文是否触碰创作禁忌 (原则层)
  - knowledge_brain: 动态经验层 (写作教训)
  - red_line_principles: 静态原则层 (创作底线)

设计原则:
  - 零 LLM 依赖: 纯规则/关键词/统计检测
  - JSON 文件存储: 轻量, 可读, 可手动编辑
  - 可扩展: 支持自定义红线类型和检测规则

用法:
  from xiaoshuo.pipeline.red_line_principles import RedLineChecker

  checker = RedLineChecker()

  # 检测章节
  result = checker.check_chapter(
      chapter_text="林凡跪倒在地，磕头求饶...",
      chapter_num=15,
  )

  # 添加自定义红线
  checker.add_principle(
      category="character",
      rule="主角不能跪",
      keywords=["跪倒", "磕头", "求饶"],
      severity="critical",
      alternative="主角即使战败也应站着，用语言或行动反击",
  )
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from xiaoshuo import PROJECT_ROOT
from xiaoshuo.infra.logging_config import get_logger

logger = get_logger("red_line")


# ============================================================
# 常量 & 路径
# ============================================================

RL_DIR = PROJECT_ROOT / "data" / "red_line_principles"
RL_PATH = RL_DIR / "principles.json"

# 红线类别
CATEGORIES = {
    "character":   "角色红线 (主角不能怂/CP不能绿/角色不能降智)",
    "power":       "战力红线 (战力不能崩/升级不能跳)",
    "plot":        "剧情红线 (不能烂尾/不能水字数/不能逻辑断裂)",
    "world":       "世界观红线 (设定不能自相矛盾/规则不能随意改)",
    "style":       "风格红线 (不能AI味/不能流水账/不能说明文)",
    "moral":       "道德红线 (不写低俗/不美化犯罪/不传播负面)",
}

SEVERITY_LEVELS = {"info": 0, "warning": 1, "serious": 2, "critical": 3}


# ============================================================
# 数据结构
# ============================================================

@dataclass
class RedLinePrinciple:
    """一条红线原则。"""
    id: str = ""
    category: str = ""        # character / power / plot / world / style / moral
    rule: str = ""            # 规则描述 (如 "主角不能跪")
    keywords: list[str] = field(default_factory=list)  # 触发关键词
    patterns: list[str] = field(default_factory=list)  # 正则模式 (高级检测)
    severity: str = "warning"  # warning / serious / critical
    alternative: str = ""     # 替代方案建议
    enabled: bool = True
    created_at: str = ""
    hit_count: int = 0        # 被触发次数
    override_count: int = 0   # 被作者打破次数

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict) -> "RedLinePrinciple":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class RedLineViolation:
    """一条红线违规。"""
    principle: RedLinePrinciple
    matched_text: str = ""    # 匹配到的文本片段
    position: int = 0         # 在文本中的位置
    context: str = ""         # 前后文 (±30字)

    @property
    def severity_level(self) -> int:
        return SEVERITY_LEVELS.get(self.principle.severity, 1)


@dataclass
class RedLineCheckResult:
    """红线检测结果。"""
    violations: list[RedLineViolation] = field(default_factory=list)
    has_critical: bool = False
    has_warnings: bool = False
    total_checked: int = 0

    @property
    def count(self) -> int:
        return len(self.violations)

    @property
    def passed(self) -> bool:
        """无 critical 违规视为通过。"""
        return not self.has_critical

    def summary(self) -> str:
        if not self.violations:
            return f"✅ 红线检测通过 (检查 {self.total_checked} 条原则)"
        parts = [f"⚠️ 红线检测: {len(self.violations)} 条违规"]
        for v in self.violations:
            icon = {"critical": "[!!!]", "serious": "[!!]", "warning": "[!]"}.get(
                v.principle.severity, "[?]")
            parts.append(f"  {icon} [{v.principle.category}] {v.principle.rule}")
            if v.matched_text:
                parts.append(f"    匹配: \"{v.matched_text}\"")
            if v.principle.alternative:
                parts.append(f"    建议: {v.principle.alternative}")
        return "\n".join(parts)


# ============================================================
# RedLineChecker 主类
# ============================================================

class RedLineChecker:
    """红线原则检测器。

    用法:
        checker = RedLineChecker()
        result = checker.check_chapter(chapter_text="...", chapter_num=15)
        if result.has_critical:
            print(result.summary())
    """

    def __init__(self):
        self._principles: list[RedLinePrinciple] = []
        self._compiled_patterns: dict[str, list[re.Pattern]] = {}
        self._load()

    # ── 加载/保存 ──

    def _load(self):
        """从 JSON 文件加载红线原则。"""
        if not RL_PATH.exists():
            self._principles = self._default_principles()
            self._save()
            logger.info("红线原则库初始化: %d 条默认原则", len(self._principles))
        else:
            try:
                data = json.loads(RL_PATH.read_text(encoding="utf-8"))
                self._principles = [RedLinePrinciple.from_dict(p)
                                    for p in data.get("principles", [])]
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("红线原则库加载失败: %s, 使用默认", e)
                self._principles = self._default_principles()

        self._compile_patterns()
        logger.debug("红线原则库: %d 条", len(self._principles))

    def _save(self):
        """持久化到 JSON 文件。"""
        RL_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "version": "1.0",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "categories": CATEGORIES,
            "principles": [p.to_dict() for p in self._principles],
        }
        RL_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _compile_patterns(self):
        """预编译正则模式。"""
        self._compiled_patterns = {}
        for p in self._principles:
            if p.patterns:
                self._compiled_patterns[p.id] = [
                    re.compile(pat, re.IGNORECASE) for pat in p.patterns
                ]

    # ── 默认原则 ──

    def _default_principles(self) -> list[RedLinePrinciple]:
        """内置默认红线原则。"""
        now = datetime.now().isoformat(timespec="seconds")
        defaults = [
            # 角色红线
            RedLinePrinciple(
                id="rl-001", category="character",
                rule="主角不能跪地求饶",
                keywords=["跪倒在地", "跪下", "磕头", "求饶", "跪地求饶"],
                severity="critical",
                alternative="主角即使战败也应站着，用语言或行动反击",
                created_at=now,
            ),
            RedLinePrinciple(
                id="rl-002", category="character",
                rule="主角不能降智 (明知陷阱还往里跳)",
                keywords=["明知陷阱", "明知是计", "明知道危险"],
                severity="serious",
                alternative="给主角合理的理由去冒险，而非无脑送死",
                created_at=now,
            ),
            RedLinePrinciple(
                id="rl-003", category="character",
                rule="主角不能圣母 (无底线原谅敌人)",
                keywords=["原谅了", "放过了", "算了饶他"],
                severity="serious",
                alternative="主角可以有原则的宽容，但不能无底线圣母",
                created_at=now,
            ),
            # 战力红线
            RedLinePrinciple(
                id="rl-004", category="power",
                rule="战力不能崩 (越级太多无代价)",
                keywords=["轻松击败", "一拳秒杀", "毫不费力地"],
                patterns=[r"越级.{0,10}(轻松|秒杀|碾压)"],
                severity="serious",
                alternative="越级战斗应有代价或特殊条件，不能无理由碾压",
                created_at=now,
            ),
            # 剧情红线
            RedLinePrinciple(
                id="rl-005", category="plot",
                rule="不能无逻辑推进 (突然跳到新场景无过渡)",
                keywords=[],
                patterns=[r"突然.{0,5}来到了", r"转眼间.{0,10}已经"],
                severity="warning",
                alternative="场景切换需要过渡描写，不能硬跳",
                created_at=now,
            ),
            # 风格红线
            RedLinePrinciple(
                id="rl-006", category="style",
                rule="不能出现AI指纹词密集",
                keywords=["深吸一口气", "目光扫过", "嘴角勾起",
                          "不由地", "旋即", "与此同时"],
                severity="warning",
                alternative="避免连续使用AI高频心理描写词，改用动作和对话",
                created_at=now,
            ),
            RedLinePrinciple(
                id="rl-007", category="style",
                rule="不能出现大段说明文 (设定灌输)",
                keywords=[],
                patterns=[r"(?:之所以|这是因为|众所周知).{50,}"],
                severity="warning",
                alternative="设定应通过对话和事件自然展开，不要大段说明",
                created_at=now,
            ),
            # 道德红线
            RedLinePrinciple(
                id="rl-008", category="moral",
                rule="不能美化犯罪行为",
                keywords=["杀人不眨眼真男人", "无毒不丈夫"],
                severity="critical",
                alternative="反派可以有魅力，但不应美化犯罪本身",
                created_at=now,
            ),
        ]
        return defaults

    # ── 检测 ──

    def check_chapter(
        self,
        chapter_text: str,
        chapter_num: int = 0,
        categories: list[str] | None = None,
    ) -> RedLineCheckResult:
        """检测章节文本是否触碰红线。

        Args:
            chapter_text: 章节正文
            chapter_num: 章节号 (用于日志)
            categories: 只检测指定类别 (None=全部)

        Returns:
            RedLineCheckResult
        """
        result = RedLineCheckResult()
        result.total_checked = 0

        for principle in self._principles:
            if not principle.enabled:
                continue
            if categories and principle.category not in categories:
                continue

            result.total_checked += 1
            violations = self._check_principle(principle, chapter_text)

            for v in violations:
                result.violations.append(v)
                principle.hit_count += 1

                if v.severity_level >= SEVERITY_LEVELS["critical"]:
                    result.has_critical = True
                if v.severity_level >= SEVERITY_LEVELS["warning"]:
                    result.has_warnings = True

        # 按严重度排序
        result.violations.sort(key=lambda v: v.severity_level, reverse=True)

        if result.violations:
            self._save()
            logger.info("红线检测 ch%d: %d 条违规 (critical=%s)",
                        chapter_num, result.count, result.has_critical)

        return result

    def _check_principle(
        self, principle: RedLinePrinciple, text: str
    ) -> list[RedLineViolation]:
        """检测单条原则。"""
        violations = []

        # 关键词检测
        for kw in principle.keywords:
            start = 0
            while True:
                pos = text.find(kw, start)
                if pos == -1:
                    break
                # 提取上下文 (±30字)
                ctx_start = max(0, pos - 30)
                ctx_end = min(len(text), pos + len(kw) + 30)
                context = text[ctx_start:ctx_end]

                violations.append(RedLineViolation(
                    principle=principle,
                    matched_text=kw,
                    position=pos,
                    context=context,
                ))
                start = pos + len(kw)

        # 正则模式检测
        patterns = self._compiled_patterns.get(principle.id, [])
        for pat in patterns:
            for m in pat.finditer(text):
                matched = m.group()
                pos = m.start()
                ctx_start = max(0, pos - 30)
                ctx_end = min(len(text), pos + len(matched) + 30)

                violations.append(RedLineViolation(
                    principle=principle,
                    matched_text=matched,
                    position=pos,
                    context=text[ctx_start:ctx_end],
                ))

        return violations

    # ── 管理接口 ──

    def add_principle(
        self,
        category: str,
        rule: str,
        keywords: list[str] | None = None,
        patterns: list[str] | None = None,
        severity: str = "warning",
        alternative: str = "",
    ) -> str:
        """添加自定义红线原则。返回原则 ID。"""
        if category not in CATEGORIES:
            raise ValueError(f"未知类别: {category}, 可选: {list(CATEGORIES.keys())}")

        now = datetime.now().isoformat(timespec="seconds")
        pid = f"rl-{len(self._principles) + 1:03d}"
        principle = RedLinePrinciple(
            id=pid,
            category=category,
            rule=rule,
            keywords=keywords or [],
            patterns=patterns or [],
            severity=severity,
            alternative=alternative,
            created_at=now,
        )
        self._principles.append(principle)
        if principle.patterns:
            self._compiled_patterns[pid] = [
                re.compile(p, re.IGNORECASE) for p in principle.patterns
            ]
        self._save()
        logger.info("新增红线原则: [%s] %s", category, rule)
        return pid

    def remove_principle(self, pid: str) -> bool:
        """删除红线原则。"""
        before = len(self._principles)
        self._principles = [p for p in self._principles if p.id != pid]
        self._compiled_patterns.pop(pid, None)
        if len(self._principles) < before:
            self._save()
            return True
        return False

    def toggle_principle(self, pid: str, enabled: bool | None = None) -> bool:
        """启用/禁用红线原则。"""
        for p in self._principles:
            if p.id == pid:
                p.enabled = enabled if enabled is not None else not p.enabled
                self._save()
                return True
        return False

    def list_principles(self, category: str = "") -> list[RedLinePrinciple]:
        """列出红线原则 (可按类别过滤)。"""
        if category:
            return [p for p in self._principles if p.category == category]
        return list(self._principles)

    def get_by_id(self, pid: str) -> RedLinePrinciple | None:
        for p in self._principles:
            if p.id == pid:
                return p
        return None

    # ── 打破确认 ──

    def request_override(self, pid: str, reason: str = "") -> dict:
        """作者请求打破红线。

        返回确认信息，需要作者显式确认。
        """
        principle = self.get_by_id(pid)
        if not principle:
            return {"error": f"原则 {pid} 不存在"}

        principle.override_count += 1
        self._save()

        return {
            "principle_id": pid,
            "rule": principle.rule,
            "severity": principle.severity,
            "reason": reason,
            "warning": (
                f"你正在打破红线: 「{principle.rule}」\n"
                f"严重度: {principle.severity}\n"
                f"替代方案: {principle.alternative or '(无)'}\n"
                f"打破次数: {principle.override_count}\n"
                f"请确认这是有意为之。"
            ),
            "confirmed": False,  # 需要外部确认
        }

    # ── 统计 ──

    def stats(self) -> dict:
        from collections import Counter
        cat_dist = Counter(p.category for p in self._principles)
        sev_dist = Counter(p.severity for p in self._principles)
        return {
            "total": len(self._principles),
            "enabled": sum(1 for p in self._principles if p.enabled),
            "category_dist": dict(cat_dist),
            "severity_dist": dict(sev_dist),
            "total_hits": sum(p.hit_count for p in self._principles),
            "total_overrides": sum(p.override_count for p in self._principles),
        }

    # ── Prompt 集成 ──

    def format_for_prompt(self, max_entries: int = 5) -> str:
        """格式化为可注入 Prompt 的红线提醒文本。"""
        active = [p for p in self._principles if p.enabled]
        if not active:
            return ""

        # 按严重度排序
        active.sort(key=lambda p: SEVERITY_LEVELS.get(p.severity, 1), reverse=True)

        lines = ["## 红线原则提醒 (Red Line)"]
        for p in active[:max_entries]:
            lines.append(f"- [{p.severity.upper()}] [{p.category}] {p.rule}")
            if p.alternative:
                lines.append(f"  替代: {p.alternative}")

        return "\n".join(lines)

    def format_for_writing_context(self) -> dict:
        """为 writing_context 提供结构化红线数据。"""
        active = [p for p in self._principles if p.enabled]
        return {
            "prompt_text": self.format_for_prompt(5),
            "total_principles": len(active),
            "critical_count": sum(
                1 for p in active if p.severity == "critical"
            ),
        }


# ============================================================
# 便捷函数
# ============================================================

_checker_instance: RedLineChecker | None = None


def get_red_line_checker() -> RedLineChecker:
    """获取全局 RedLineChecker 单例。"""
    global _checker_instance
    if _checker_instance is None:
        _checker_instance = RedLineChecker()
    return _checker_instance


def check_red_lines(chapter_text: str, chapter_num: int = 0) -> RedLineCheckResult:
    """便捷函数: 红线检测。"""
    return get_red_line_checker().check_chapter(chapter_text, chapter_num)
