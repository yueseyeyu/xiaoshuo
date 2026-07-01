# -*- coding: utf-8 -*-
"""
prompt_template.py — 固定 System Prompt 模板化 (P3)
=====================================================
来源: 建议文件 "优化缓存命中率——固定 system prompt、复用长上下文、模板化任务输入"

核心理念:
  DeepSeek API 缓存命中 vs 未命中价格相差 100 倍以上 (¥0.025 vs ¥3/百万 Token)。
  通过固定 system prompt + 模板化任务输入，最大化缓存命中率。

缓存优化策略:
  1. 固定 system prompt: 同一任务类型的 system prompt 保持不变，让 API 端缓存命中
  2. 变量后置: 将动态内容 (章节号、正文) 放在 user message 的后面
  3. 模板复用: 同一模板的多次调用共享缓存前缀
  4. 前缀对齐: 确保不同调用的 prompt 前缀完全一致

与现有模块的关系:
  - model_orchestrator.py: 模型路由 (调用方)
  - cross_review.py: 双模型审查 (prompt 构造方)
  - prompt_template.py: prompt 模板管理 (基础设施层)

设计原则:
  - 模板注册制: 所有 prompt 模板集中管理，避免散落在各模块
  - 前缀固定: system prompt 一次定义，多次复用
  - 变量注入: 动态内容通过 {placeholder} 注入，不影响缓存前缀
  - 可审计: 记录每次渲染的 prompt (可选)

用法:
  from xiaoshuo.pipeline.prompt_template import PromptTemplateRegistry

  registry = PromptTemplateRegistry()

  # 注册模板
  registry.register(
      task_type="S3_review",
      system_prompt="你是一位资深网文编辑，专注于...（固定不变）",
      user_template="请审查以下章节：\n\n章节号: {chapter_num}\n正文:\n{chapter_text}",
  )

  # 渲染 prompt (system_prompt 固定, user_message 动态注入)
  messages = registry.render(
      task_type="S3_review",
      variables={"chapter_num": 15, "chapter_text": "林凡站在..."},
  )
  # → [{"role": "system", "content": "你是一位资深网文编辑..."},
  #    {"role": "user", "content": "请审查以下章节：\n\n章节号: 15\n正文:\n林凡站在..."}]

  # 获取缓存统计
  stats = registry.cache_stats()
  # → {"S3_review": {"calls": 50, "estimated_cache_hit_rate": 0.95}}
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from xiaoshuo import PROJECT_ROOT
from xiaoshuo.infra.logging_config import get_logger

logger = get_logger("prompt_template")


# ============================================================
# 路径常量
# ============================================================

_TEMPLATE_REGISTRY_PATH = PROJECT_ROOT / "data" / "processed" / "prompt_templates.json"


# ============================================================
# 数据结构
# ============================================================

@dataclass
class PromptTemplate:
    """单个 prompt 模板。"""
    task_type: str               # 任务类型 (如 "S3_review", "golden3_analysis")
    system_prompt: str           # 固定 system prompt (缓存命中关键)
    user_template: str           # user message 模板 (含 {placeholder})
    description: str = ""        # 模板描述
    # 缓存前缀哈希 (用于估算缓存命中率)
    system_prompt_hash: str = ""

    def __post_init__(self):
        if not self.system_prompt_hash:
            self.system_prompt_hash = hashlib.md5(
                self.system_prompt.encode("utf-8")
            ).hexdigest()[:12]

    def render(self, variables: dict) -> list[dict]:
        """渲染 prompt 为 messages 列表。

        Args:
            variables: 模板变量 (替换 user_template 中的 {placeholder})

        Returns:
            OpenAI 格式的 messages 列表:
            [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
        """
        # system prompt 固定不变 (缓存命中关键)
        system_content = self.system_prompt

        # user message 动态渲染
        user_content = self.user_template
        for key, value in variables.items():
            placeholder = "{" + key + "}"
            user_content = user_content.replace(placeholder, str(value))

        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]


@dataclass
class CacheStats:
    """缓存统计。"""
    task_type: str
    calls: int = 0                  # 总调用次数
    system_prompt_hash: str = ""    # system prompt 哈希 (用于判断缓存命中)
    # 估算的缓存命中率 (基于 system prompt 是否变化)
    estimated_cache_hit_rate: float = 1.0
    last_call_at: str = ""

    def to_dict(self) -> dict:
        return {
            "task_type": self.task_type,
            "calls": self.calls,
            "system_prompt_hash": self.system_prompt_hash,
            "estimated_cache_hit_rate": self.estimated_cache_hit_rate,
            "last_call_at": self.last_call_at,
        }


# ============================================================
# Prompt 模板注册表
# ============================================================

class PromptTemplateRegistry:
    """Prompt 模板注册表。

    集中管理所有任务的 prompt 模板，确保 system prompt 固定以提高缓存命中率。

    用法:
      registry = PromptTemplateRegistry()

      # 注册模板
      registry.register(
          task_type="S3_review",
          system_prompt="你是一位资深网文编辑...",
          user_template="请审查以下章节：\n章节号: {chapter_num}\n正文:\n{chapter_text}",
      )

      # 渲染
      messages = registry.render("S3_review", {"chapter_num": 15, "chapter_text": "..."})

      # 缓存统计
      stats = registry.cache_stats()
    """

    def __init__(self):
        self._templates: dict[str, PromptTemplate] = {}
        self._cache_stats: dict[str, CacheStats] = {}
        self._load()

    def register(
        self,
        task_type: str,
        system_prompt: str,
        user_template: str,
        description: str = "",
        overwrite: bool = False,
    ) -> None:
        """注册 prompt 模板。

        Args:
            task_type: 任务类型
            system_prompt: 固定 system prompt (缓存命中关键)
            user_template: user message 模板 (含 {placeholder})
            description: 模板描述
            overwrite: 是否覆盖已存在的模板

        Raises:
            ValueError: 模板已存在且 overwrite=False
        """
        if task_type in self._templates and not overwrite:
            existing = self._templates[task_type]
            if existing.system_prompt == system_prompt:
                logger.debug(f"模板 '{task_type}' 已存在且内容相同，跳过注册")
                return
            raise ValueError(
                f"模板 '{task_type}' 已存在且 system_prompt 不同。"
                f"使用 overwrite=True 覆盖。"
            )

        template = PromptTemplate(
            task_type=task_type,
            system_prompt=system_prompt,
            user_template=user_template,
            description=description,
        )
        self._templates[task_type] = template

        # 初始化缓存统计
        if task_type not in self._cache_stats:
            self._cache_stats[task_type] = CacheStats(
                task_type=task_type,
                system_prompt_hash=template.system_prompt_hash,
            )
        elif overwrite:
            # 覆盖时重置缓存统计
            self._cache_stats[task_type] = CacheStats(
                task_type=task_type,
                system_prompt_hash=template.system_prompt_hash,
                estimated_cache_hit_rate=0.0,  # prompt 变了，之前的缓存失效
            )

        self._save()
        logger.info(f"注册 prompt 模板: {task_type} (hash={template.system_prompt_hash})")

    def render(self, task_type: str, variables: dict) -> list[dict]:
        """渲染 prompt 为 messages 列表。

        Args:
            task_type: 任务类型
            variables: 模板变量

        Returns:
            OpenAI 格式的 messages 列表

        Raises:
            KeyError: 模板不存在
        """
        if task_type not in self._templates:
            raise KeyError(f"Prompt 模板 '{task_type}' 未注册")

        template = self._templates[task_type]
        messages = template.render(variables)

        # 更新缓存统计
        stats = self._cache_stats[task_type]
        stats.calls += 1
        stats.last_call_at = datetime.now().isoformat()

        self._save()
        return messages

    def get_template(self, task_type: str) -> Optional[PromptTemplate]:
        """获取模板 (不渲染)。"""
        return self._templates.get(task_type)

    def list_templates(self) -> list[str]:
        """列出所有已注册的任务类型。"""
        return list(self._templates.keys())

    def cache_stats(self) -> dict[str, dict]:
        """获取缓存统计。"""
        return {k: v.to_dict() for k, v in self._cache_stats.items()}

    def estimate_cost_savings(self) -> dict:
        """估算缓存优化带来的成本节省。

        基于 DeepSeek API 定价 (2026年7月):
          - 缓存命中输入: ¥0.025/百万 Token (平时段)
          - 缓存未命中输入: ¥3/百万 Token (平时段)
          - 差价: ¥2.975/百万 Token

        Returns:
            {
                "total_calls": int,
                "estimated_cached_tokens": int,
                "estimated_savings_yuan": float,
                "cache_hit_rate": float,
            }
        """
        total_calls = sum(s.calls for s in self._cache_stats.values())
        if total_calls == 0:
            return {
                "total_calls": 0,
                "estimated_cached_tokens": 0,
                "estimated_savings_yuan": 0.0,
                "cache_hit_rate": 0.0,
            }

        # 估算: 每个 system prompt 约 500-2000 Token
        avg_system_tokens = 1000
        # 估算缓存命中率 (system prompt 不变 = 100% 命中)
        cache_hit_rate = 1.0  # 固定 system prompt → 理论上 100% 命中
        cached_tokens = total_calls * avg_system_tokens * cache_hit_rate
        # 节省金额 = 缓存命中的 Token × 差价
        savings = cached_tokens / 1_000_000 * 2.975

        return {
            "total_calls": total_calls,
            "estimated_cached_tokens": int(cached_tokens),
            "estimated_savings_yuan": round(savings, 2),
            "cache_hit_rate": cache_hit_rate,
        }

    def _save(self) -> None:
        """保存模板和统计到 JSON 文件。"""
        data = {
            "templates": {
                k: {
                    "task_type": v.task_type,
                    "system_prompt": v.system_prompt,
                    "user_template": v.user_template,
                    "description": v.description,
                    "system_prompt_hash": v.system_prompt_hash,
                }
                for k, v in self._templates.items()
            },
            "cache_stats": {k: v.to_dict() for k, v in self._cache_stats.items()},
        }
        _TEMPLATE_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        _TEMPLATE_REGISTRY_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load(self) -> None:
        """从 JSON 文件加载模板和统计。"""
        if not _TEMPLATE_REGISTRY_PATH.exists():
            logger.info("Prompt 模板文件不存在，使用空注册表")
            return

        try:
            data = json.loads(_TEMPLATE_REGISTRY_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            logger.warning("Prompt 模板文件损坏，使用空注册表")
            return

        for k, v in data.get("templates", {}).items():
            self._templates[k] = PromptTemplate(
                task_type=v["task_type"],
                system_prompt=v["system_prompt"],
                user_template=v["user_template"],
                description=v.get("description", ""),
                system_prompt_hash=v.get("system_prompt_hash", ""),
            )

        for k, v in data.get("cache_stats", {}).items():
            self._cache_stats[k] = CacheStats(
                task_type=v["task_type"],
                calls=v.get("calls", 0),
                system_prompt_hash=v.get("system_prompt_hash", ""),
                estimated_cache_hit_rate=v.get("estimated_cache_hit_rate", 1.0),
                last_call_at=v.get("last_call_at", ""),
            )

        logger.info(f"加载 {len(self._templates)} 个 prompt 模板")


# ============================================================
# 预设模板 (常用任务的固定 system prompt)
# ============================================================

# S3 评审 system prompt (固定不变，最大化缓存命中)
_S3_REVIEW_SYSTEM = """你是一位资深网文编辑，专注于番茄小说平台的连载作品评审。
你的评审维度包括:
1. D1 爽感度: 即时爽点/延迟爽点的密度和质量
2. D2 追读力: 章末钩子强度、信息悬念、期待感营造
3. D3 节奏感: 情绪曲线、信息密度、场景切换
4. D4 人物感: 角色一致性、对话代入感、配角功能性
5. D5 世界感: 设定一致性、世界观沉浸感

评审标准:
- 每个维度 0-100 分
- 70分以下为不达标
- 85分以上为精品水平
- 需要给出具体的改进建议

请严格按 JSON 格式输出评审结果。"""

# 黄金三章分析 system prompt
_GOLDEN3_SYSTEM = """你是番茄小说平台的黄金三章分析专家。
你的任务: 分析小说前3章的商业潜力和读者留存能力。

分析维度:
1. 开头Hook: 前300字是否抓住读者
2. 爽点节奏: 第1章是否有即时爽点，第3章是否有延迟爽点
3. 期待感: 读者读完第3章是否有强烈继续阅读的欲望
4. 信息密度: 世界观/角色/金手指的揭示节奏是否合适
5. 避雷检查: 是否存在常见的"劝退"元素

请严格按 JSON 格式输出分析结果。"""

# Canon 一致性检查 system prompt
_CANON_CHECK_SYSTEM = """你是小说设定一致性检查专家。
你的任务: 检查章节正文是否与 Canon 设定一致。

检查维度:
1. 角色设定: 姓名、性格、能力、关系是否与 Canon 一致
2. 世界观设定: 境界体系、地理、历史是否与 Canon 一致
3. 伏笔状态: 已埋伏笔是否被正确引用，已回收伏笔是否被错误重提
4. 时间线: 事件发生顺序是否与 Canon 时间线一致

发现不一致时，请明确标注:
- 不一致类型 (角色/世界观/伏笔/时间线)
- Canon 中的正确设定
- 正文中的错误描述
- 建议修改方案"""


def register_preset_templates(registry: PromptTemplateRegistry) -> None:
    """注册预设模板。

    在系统初始化时调用，注册常用任务的固定 system prompt。

    Args:
        registry: Prompt 模板注册表
    """
    presets = [
        ("S3_review", _S3_REVIEW_SYSTEM,
         "请审查以下章节：\n\n章节号: {chapter_num}\n题材: {genre}\n\n正文:\n{chapter_text}",
         "S3 五维评审"),
        ("golden3_analysis", _GOLDEN3_SYSTEM,
         "请分析以下小说的前3章：\n\n书名: {book_name}\n题材: {genre}\n\n正文:\n{chapters_text}",
         "黄金三章分析"),
        ("canon_check", _CANON_CHECK_SYSTEM,
         "请检查以下章节的 Canon 一致性：\n\n章节号: {chapter_num}\n\nCanon 设定:\n{canon_rules}\n\n正文:\n{chapter_text}",
         "Canon 一致性检查"),
    ]

    for task_type, system, user_template, desc in presets:
        try:
            registry.register(
                task_type=task_type,
                system_prompt=system,
                user_template=user_template,
                description=desc,
                overwrite=False,
            )
        except ValueError:
            # 已存在且不同 → 跳过
            logger.debug(f"预设模板 '{task_type}' 已存在，跳过")

    logger.info(f"注册 {len(presets)} 个预设模板")


# ============================================================
# 单例
# ============================================================

_registry_instance: Optional[PromptTemplateRegistry] = None


def get_registry() -> PromptTemplateRegistry:
    """获取全局 Prompt 模板注册表单例。"""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = PromptTemplateRegistry()
        register_preset_templates(_registry_instance)
    return _registry_instance
