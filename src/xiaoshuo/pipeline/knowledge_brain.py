# -*- coding: utf-8 -*-
"""
knowledge_brain.py — 跨书知识大脑 (P1.4)
==========================================
来源: 建议文件 "Obsidian Knowledge-Brain v4.0 -> 简化版"

核心功能:
  1. 全局经验表: 跨书/跨题材的"硬教训" (最多 N 条)
  2. 根因哈希去重: 同一问题在不同书/章节出现 → 自动识别
  3. 写前查表: 生成章节前自动检索相关经验
  4. 自动晋升: 同一问题出现 ≥2 次 → 自动晋升为全局经验
  5. 自动降级: 清理过期/低频经验, 防止臃肿

与现有模块的关系:
  - memory_store.py: 任务级记忆 (Goal/Solution/Result/PainPoint)
  - novel_index.py:  小说级记忆 (章节/伏笔/角色/弧光)
  - knowledge_brain: 跨书经验级记忆 (写作教训/评审失败/风格陷阱)
  - technique_store: 题材技法卡片 (静态规则库)

  knowledge_brain 是"动态经验层", technique_store 是"静态规则层",
  两者互补: 规则告诉你"应该怎么做", 经验告诉你"别这么做"。

设计原则:
  - 零 LLM 依赖: 纯规则/哈希/统计
  - JSON 文件存储: 轻量, 可读, 可手动编辑
  - 缓存友好: 查询命中率 ~100% (内存缓存 + 文件持久化)

用法:
  from xiaoshuo.pipeline.knowledge_brain import KnowledgeBrain

  kb = KnowledgeBrain()

  # 写前查表
  warnings = kb.check_before_write(
      chapter_type="战斗",
      context={"genre": "末世", "chapter_num": 15}
  )

  # 记录经验
  kb.record(
      symptom="战斗场景AI指纹词密度过高",
      root_cause="战斗描写中连续使用'深吸一口气''目光扫过'",
      solution="战斗场景分散使用动作动词, 避免重复心理描写",
      severity="warning",
      source="s3_review",
      tags=["战斗", "AI指纹", "末世"],
  )

  # 查看全局经验
  global_exp = kb.list_global()
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from xiaoshuo import PROJECT_ROOT
from xiaoshuo.infra.logging_config import get_logger

logger = get_logger("knowledge_brain")


# ============================================================
# 常量 & 路径
# ============================================================

KB_DIR = PROJECT_ROOT / "data" / "knowledge_brain"
GLOBAL_EXP_PATH = KB_DIR / "global_experience.json"
PROJECT_MEM_PATH = KB_DIR / "project_memory.json"

MAX_GLOBAL_ENTRIES = 30       # 全局经验表上限
PROMOTE_THRESHOLD = 2         # 同一根因出现 ≥2 次 → 自动晋升
STALE_DAYS = 90               # 超过 90 天未被命中 → 降级
MAX_PROJECT_ENTRIES = 200     # 项目记忆上限

SEVERITY_LEVELS = {"info": 0, "warning": 1, "serious": 2, "critical": 3}
SEVERITY_LABELS = {v: k for k, v in SEVERITY_LEVELS.items()}


# ============================================================
# 数据结构
# ============================================================

@dataclass
class Experience:
    """一条经验记录。"""
    id: str = ""
    hash: str = ""                # 根因哈希 (用于去重)
    symptom: str = ""             # 症状描述 (如 "战斗场景AI指纹词密度过高")
    root_cause: str = ""          # 根因 (如 "连续使用'深吸一口气'")
    solution: str = ""            # 解决方案 (如 "分散使用动作动词")
    severity: str = "warning"     # info / warning / serious / critical
    source: str = "manual"        # s3_review / s4_detection / golden3 / manual
    tags: list[str] = field(default_factory=list)
    created_at: str = ""
    hit_count: int = 0            # 被命中次数
    last_hit_at: str = ""         # 最后命中时间
    occurrences: int = 1          # 出现次数 (≥PROMOTE_THRESHOLD → 晋升全局)
    is_global: bool = False       # 是否已晋升为全局经验
    genre: str = ""               # 题材 (空=跨题材)

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict) -> "Experience":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class CheckResult:
    """写前查表结果。"""
    matched: list[Experience] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    has_warnings: bool = False

    @property
    def count(self) -> int:
        return len(self.matched)


# ============================================================
# 根因哈希
# ============================================================

def _compute_hash(root_cause: str, symptom: str = "") -> str:
    """计算根因哈希 (用于跨书去重)。

    去除空格/标点/大小写后取 MD5 前 12 位。
    """
    # 归一化: 去除空格、标点、换行
    normalized = re.sub(r'[\s\u3000，。！？；：、""''「」『』（）()\[\]{}【】\.,!?;:\'\"]', '', root_cause)
    normalized = normalized.lower()
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()[:12]


# ============================================================
# KnowledgeBrain 主类
# ============================================================

class KnowledgeBrain:
    """跨书知识大脑 — 经验级记忆管理。

    用法:
        kb = KnowledgeBrain()
        result = kb.check_before_write(chapter_type="战斗", context={...})
        kb.record(symptom="...", root_cause="...", solution="...")
    """

    def __init__(self):
        self._global_exp: list[Experience] = []
        self._project_mem: list[Experience] = []
        self._loaded = False
        self._load()

    # ── 加载/保存 ──

    def _load(self):
        """从 JSON 文件加载经验数据。"""
        self._global_exp = self._load_json(GLOBAL_EXP_PATH, "global")
        self._project_mem = self._load_json(PROJECT_MEM_PATH, "project")
        self._loaded = True
        logger.debug("KB 加载: %d 全局, %d 项目",
                     len(self._global_exp), len(self._project_mem))

    def _load_json(self, path: Path, label: str) -> list[Experience]:
        """加载 JSON 文件为 Experience 列表。"""
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            entries = data.get("experiences", [])
            return [Experience.from_dict(e) for e in entries]
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("KB %s 文件加载失败: %s", label, e)
            return []

    def _save(self):
        """持久化到 JSON 文件。"""
        KB_DIR.mkdir(parents=True, exist_ok=True)

        global_data = {
            "version": "1.0",
            "max_entries": MAX_GLOBAL_ENTRIES,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "experiences": [e.to_dict() for e in self._global_exp],
        }
        GLOBAL_EXP_PATH.write_text(
            json.dumps(global_data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        project_data = {
            "version": "1.0",
            "max_entries": MAX_PROJECT_ENTRIES,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "experiences": [e.to_dict() for e in self._project_mem],
        }
        PROJECT_MEM_PATH.write_text(
            json.dumps(project_data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    # ── 记录经验 ──

    def record(
        self,
        symptom: str,
        root_cause: str,
        solution: str = "",
        severity: str = "warning",
        source: str = "manual",
        tags: list[str] | None = None,
        genre: str = "",
    ) -> str:
        """记录一条经验。返回经验 ID。

        如果根因哈希已存在:
          - 增加出现次数
          - 达到 PROMOTE_THRESHOLD → 自动晋升全局
          - 更新命中时间

        Args:
            symptom: 症状描述
            root_cause: 根因
            solution: 解决方案
            severity: info / warning / serious / critical
            source: 来源 (s3_review / s4_detection / golden3 / manual)
            tags: 标签列表
            genre: 题材

        Returns:
            经验 ID
        """
        tags = tags or []
        exp_hash = _compute_hash(root_cause, symptom)
        now = datetime.now().isoformat(timespec="seconds")

        # 检查是否已存在 (先全局, 再项目)
        existing = self._find_by_hash(exp_hash)

        if existing:
            existing.occurrences += 1
            existing.last_hit_at = now
            existing.hit_count += 1

            # 更新 solution (如果新的更好)
            if solution and not existing.solution:
                existing.solution = solution

            # 严重度升级 (取更高的)
            if SEVERITY_LEVELS.get(severity, 1) > SEVERITY_LEVELS.get(existing.severity, 1):
                existing.severity = severity

            # 检查是否需要晋升
            if not existing.is_global and existing.occurrences >= PROMOTE_THRESHOLD:
                self._promote_to_global(existing)
                logger.info("经验自动晋升全局: '%s' (出现%d次)",
                           symptom[:30], existing.occurrences)

            self._save()
            return existing.id

        # 创建新经验
        exp_id = f"exp-{len(self._project_mem) + len(self._global_exp) + 1:04d}"
        exp = Experience(
            id=exp_id,
            hash=exp_hash,
            symptom=symptom,
            root_cause=root_cause,
            solution=solution,
            severity=severity,
            source=source,
            tags=tags,
            created_at=now,
            last_hit_at=now,
            genre=genre,
        )

        self._project_mem.append(exp)

        # 超出上限 → 清理最旧的
        if len(self._project_mem) > MAX_PROJECT_ENTRIES:
            self._project_mem.sort(key=lambda e: e.last_hit_at or e.created_at, reverse=True)
            removed = self._project_mem[MAX_PROJECT_ENTRIES:]
            self._project_mem = self._project_mem[:MAX_PROJECT_ENTRIES]
            logger.debug("清理 %d 条过期项目记忆", len(removed))

        self._save()
        logger.info("经验记录: '%s' (severity=%s, source=%s)",
                    symptom[:40], severity, source)
        return exp_id

    def _find_by_hash(self, exp_hash: str) -> Experience | None:
        """通过哈希查找已有经验 (先全局, 再项目)。"""
        for exp in self._global_exp:
            if exp.hash == exp_hash:
                return exp
        for exp in self._project_mem:
            if exp.hash == exp_hash:
                return exp
        return None

    def _promote_to_global(self, exp: Experience):
        """将项目经验晋升为全局经验。"""
        exp.is_global = True

        # 从项目记忆移除 (如果存在)
        self._project_mem = [e for e in self._project_mem if e.id != exp.id]

        # 添加到全局 (如果不在)
        if exp not in self._global_exp:
            self._global_exp.append(exp)

        # 全局表超限 → 清理最低命中/最旧的
        if len(self._global_exp) > MAX_GLOBAL_ENTRIES:
            self._global_exp.sort(
                key=lambda e: (e.hit_count, e.last_hit_at or e.created_at),
                reverse=True
            )
            self._global_exp = self._global_exp[:MAX_GLOBAL_ENTRIES]

    # ── 写前查表 ──

    def check_before_write(
        self,
        chapter_type: str = "",
        context: dict | None = None,
    ) -> CheckResult:
        """写前查表: 检索与当前章节相关的经验。

        匹配逻辑:
          1. 标签匹配 (chapter_type / genre / 关键词)
          2. 全局经验优先 (跨书通用)
          3. 最多返回 5 条, 按严重度+命中次数排序

        Args:
            chapter_type: 章节类型 (如 "战斗" "对话" "过渡" "高潮")
            context: 上下文 {"genre": "...", "chapter_num": N, "keywords": [...]}

        Returns:
            CheckResult 包含匹配的经验和警告信息
        """
        context = context or {}
        result = CheckResult()

        all_exp = self._global_exp + self._project_mem
        if not all_exp:
            return result

        genre = context.get("genre", "")
        keywords = context.get("keywords", [])
        if chapter_type and chapter_type not in keywords:
            keywords = [chapter_type] + keywords

        scored = []
        for exp in all_exp:
            score = self._match_score(exp, chapter_type, genre, keywords)
            if score > 0:
                # 更新命中计数
                exp.hit_count += 1
                exp.last_hit_at = datetime.now().isoformat(timespec="seconds")
                scored.append((exp, score))

        # 排序: 分数 > 严重度 > 命中次数
        scored.sort(key=lambda x: (
            x[1],
            SEVERITY_LEVELS.get(x[0].severity, 1),
            x[0].hit_count,
        ), reverse=True)

        result.matched = [exp for exp, _ in scored[:5]]

        # 生成警告信息
        for exp in result.matched:
            severity_icon = {
                "critical": "[!!!]",
                "serious": "[!!]",
                "warning": "[!]",
                "info": "[i]",
            }.get(exp.severity, "[?]")
            result.warnings.append(
                f"{severity_icon} {exp.symptom}\n"
                f"  根因: {exp.root_cause}\n"
                f"  方案: {exp.solution or '(待补充)'}\n"
                f"  来源: {exp.source} | 命中: {exp.hit_count}次 | "
                f"{'全局' if exp.is_global else '项目'}"
            )

        result.has_warnings = any(
            SEVERITY_LEVELS.get(e.severity, 1) >= SEVERITY_LEVELS["warning"]
            for e in result.matched
        )

        if result.matched:
            self._save()  # 保存命中计数更新

        return result

    def _match_score(self, exp: Experience, chapter_type: str,
                     genre: str, keywords: list[str]) -> float:
        """计算经验与当前上下文的匹配分数。

        关联性门控: 必须至少有一项实际匹配 (标签/题材/症状关键词)
        才返回正分; 否则返回 0 (不相关)。
        严重度/全局/命中次数仅作为排序加权, 不构成匹配条件。
        """
        # ── 关联性得分 (决定是否匹配) ──
        relevance = 0.0

        # 标签匹配
        exp_tags = set(t.lower() for t in exp.tags)
        search_tags = set()
        if chapter_type:
            search_tags.add(chapter_type.lower())
        if genre:
            search_tags.add(genre.lower())
        for kw in keywords:
            search_tags.add(kw.lower())

        tag_matches = exp_tags & search_tags
        relevance += len(tag_matches) * 2.0

        # 题材匹配 (同题材加分, 全局经验不限制题材)
        if exp.genre and genre and exp.genre == genre:
            relevance += 1.0
        elif exp.is_global and not exp.genre:
            relevance += 0.5  # 跨题材通用

        # 症状文本匹配 (简化: 关键词在症状中出现)
        symptom_lower = exp.symptom.lower()
        for kw in keywords:
            if kw.lower() in symptom_lower:
                relevance += 1.0

        # 关联性门控: 无任何关联匹配 → 不返回
        if relevance == 0:
            return 0.0

        # ── 排序加权 (仅在有关联时生效) ──
        score = relevance

        # 全局经验加分
        if exp.is_global:
            score += 1.5

        # 严重度加分
        score += SEVERITY_LEVELS.get(exp.severity, 1) * 0.5

        # 命中次数加分 (经验越常被命中越有价值)
        score += min(exp.hit_count * 0.3, 3.0)

        return score

    # ── 查询接口 ──

    def list_global(self) -> list[Experience]:
        """列出所有全局经验。"""
        return sorted(self._global_exp,
                      key=lambda e: SEVERITY_LEVELS.get(e.severity, 1),
                      reverse=True)

    def list_project(self, genre: str = "") -> list[Experience]:
        """列出项目经验 (可按题材过滤)。"""
        if genre:
            return [e for e in self._project_mem if e.genre == genre or not e.genre]
        return self._project_mem

    def list_all(self) -> list[Experience]:
        """列出全部经验。"""
        return self._global_exp + self._project_mem

    def get_by_id(self, exp_id: str) -> Experience | None:
        """按 ID 查找经验。"""
        for exp in self._global_exp + self._project_mem:
            if exp.id == exp_id:
                return exp
        return None

    def search(self, keyword: str) -> list[Experience]:
        """全文搜索 (symptom/root_cause/solution/tags)。"""
        keyword_lower = keyword.lower()
        results = []
        for exp in self._global_exp + self._project_mem:
            searchable = " ".join([
                exp.symptom, exp.root_cause, exp.solution,
                " ".join(exp.tags),
            ]).lower()
            if keyword_lower in searchable:
                results.append(exp)
        return results

    # ── 维护 ──

    def cleanup_stale(self) -> int:
        """清理过期/低频经验。返回清理数量。"""
        now = datetime.now()
        removed = 0

        # 清理项目记忆中超过 STALE_DAYS 未命中的
        fresh_project = []
        for exp in self._project_mem:
            time_str = exp.last_hit_at or exp.created_at
            try:
                last = datetime.fromisoformat(time_str)
                age_days = (now - last).days
                if age_days > STALE_DAYS and exp.hit_count == 0:
                    removed += 1
                    continue
            except (ValueError, TypeError):
                pass
            fresh_project.append(exp)
        self._project_mem = fresh_project

        # 全局经验不清理 (都是高频/重要经验)

        if removed > 0:
            self._save()
            logger.info("清理 %d 条过期项目记忆", removed)

        return removed

    def promote(self, exp_id: str) -> bool:
        """手动晋升经验为全局。"""
        exp = self.get_by_id(exp_id)
        if not exp or exp.is_global:
            return False
        self._promote_to_global(exp)
        self._save()
        logger.info("手动晋升: '%s' -> 全局", exp.symptom[:30])
        return True

    def demote(self, exp_id: str) -> bool:
        """手动降级全局经验为项目级。"""
        for i, exp in enumerate(self._global_exp):
            if exp.id == exp_id:
                exp.is_global = False
                self._global_exp.pop(i)
                self._project_mem.append(exp)
                self._save()
                logger.info("手动降级: '%s' -> 项目", exp.symptom[:30])
                return True
        return False

    def delete(self, exp_id: str) -> bool:
        """删除一条经验。"""
        before = len(self._global_exp) + len(self._project_mem)
        self._global_exp = [e for e in self._global_exp if e.id != exp_id]
        self._project_mem = [e for e in self._project_mem if e.id != exp_id]
        after = len(self._global_exp) + len(self._project_mem)
        if before != after:
            self._save()
            return True
        return False

    # ── 统计 ──

    def stats(self) -> dict:
        """返回统计信息。"""
        severity_dist = Counter(e.severity for e in self.list_all())
        source_dist = Counter(e.source for e in self.list_all())
        return {
            "global_count": len(self._global_exp),
            "project_count": len(self._project_mem),
            "total": len(self._global_exp) + len(self._project_mem),
            "severity_dist": dict(severity_dist),
            "source_dist": dict(source_dist),
            "max_global": MAX_GLOBAL_ENTRIES,
            "promote_threshold": PROMOTE_THRESHOLD,
        }

    # ── Prompt 集成 ──

    def format_for_prompt(self, max_entries: int = 3) -> str:
        """格式化为可注入 Prompt 的经验提醒文本。

        Args:
            max_entries: 最多返回条数 (避免 Prompt 膨胀)

        Returns:
            Markdown 格式的经验提醒文本, 或空字符串
        """
        # 优先全局, 按严重度排序
        all_exp = sorted(
            self._global_exp + self._project_mem,
            key=lambda e: (
                e.is_global,
                SEVERITY_LEVELS.get(e.severity, 1),
                e.hit_count,
            ),
            reverse=True
        )

        if not all_exp:
            return ""

        lines = ["## 历史经验提醒 (Knowledge-Brain)"]
        for exp in all_exp[:max_entries]:
            scope = "全局" if exp.is_global else "项目"
            lines.append(f"- [{exp.severity.upper()}] {exp.symptom} ({scope})")
            lines.append(f"  根因: {exp.root_cause}")
            if exp.solution:
                lines.append(f"  方案: {exp.solution}")

        return "\n".join(lines)

    def format_for_writing_context(self, chapter_type: str = "",
                                    context: dict | None = None) -> dict:
        """为 writing_context 提供结构化经验数据。

        Returns:
            dict 包含:
              - warnings: list[str] 警告信息
              - matched_count: int 匹配数
              - has_warnings: bool
              - prompt_text: str 可注入 Prompt 的文本
        """
        result = self.check_before_write(chapter_type, context)
        return {
            "warnings": result.warnings,
            "matched_count": result.count,
            "has_warnings": result.has_warnings,
            "prompt_text": self.format_for_prompt(3) if result.matched else "",
        }


# ============================================================
# 便捷函数
# ============================================================

_kb_instance: KnowledgeBrain | None = None


def get_knowledge_brain() -> KnowledgeBrain:
    """获取全局 KnowledgeBrain 单例。"""
    global _kb_instance
    if _kb_instance is None:
        _kb_instance = KnowledgeBrain()
    return _kb_instance


def check_before_write(chapter_type: str = "",
                        context: dict | None = None) -> CheckResult:
    """便捷函数: 写前查表。"""
    return get_knowledge_brain().check_before_write(chapter_type, context)


def record_experience(symptom: str, root_cause: str,
                       solution: str = "", **kwargs) -> str:
    """便捷函数: 记录经验。"""
    return get_knowledge_brain().record(symptom, root_cause, solution, **kwargs)
