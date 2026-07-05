#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
author_profile.py — 作者记忆档案卡 (v8.8 四层记忆架构 · 第一层)
=================================================================
来源: 建议文件 "Agent 记忆系统设计" → "用户记忆档案卡"

设计原则:
  1. 结构化 JSON 存储 — 保证事实唯一性, 原地覆盖 (非追加)
  2. 作者级长期事实 — 与 Canon (作品级) 互补
  3. 所有 Agent 共享同一份作者画像
  4. 反馈历史滚动保留最近 N 条, 避免膨胀

与现有模块关系:
  - memory_store.py: 任务级行为回溯 (SQLite), 本模块是作者级长期画像 (JSON)
  - canon/style_rules: 作品级风格规则, 本模块是作者跨作品偏好
  - model_orchestrator.py: 加载本模块作为 system prompt 上下文

用法:
  from xiaoshuo.agents.author_profile import AuthorProfile

  profile = AuthorProfile()
  profile.update_writing_habit("chapter_length", 3000)
  profile.record_feedback("弱化心理前缀", accepted=True)
  prompt_suffix = profile.to_prompt_suffix()
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from xiaoshuo import PROJECT_ROOT

_logger = logging.getLogger(__name__)

# 默认存储路径
DEFAULT_PROFILE_PATH = PROJECT_ROOT / "assets" / "author_profile.json"

# 反馈历史最大保留条数
MAX_FEEDBACK_ENTRIES = 20

# 默认档案 (首次创建)
_DEFAULT_PROFILE: dict[str, Any] = {
    "author_id": "default",
    "core_goals": [],
    "preferred_tropes": [],
    "avoided_tropes": [],
    "writing_habits": {
        "chapter_length": 2500,
        "hook_style": "悬念式结尾",
        "revision_pattern": "先写后改",
    },
    "feedback_history": [],
    "style_fingerprint": {
        "avg_sentence_length": 0,
        "dialogue_ratio": 0.0,
        "mental_prefix_density": 0.0,
    },
    "metadata": {
        "created_at": None,
        "last_updated": None,
        "version": "v8.8",
    },
}


class AuthorProfile:
    """作者记忆档案卡 — 结构化长期事实存储。

    核心设计: 原地更新 (overwrite), 而非追加写入。
    这避免了向量数据库的"幽灵数据"问题 — 旧值被直接覆盖。
    """

    def __init__(self, profile_path: Optional[Path] = None):
        self.profile_path = profile_path or DEFAULT_PROFILE_PATH
        self._data: dict[str, Any] = {}
        self._load()

    # ── 加载 / 保存 ──

    def _load(self):
        """从 JSON 文件加载档案。文件不存在时创建默认档案。"""
        if self.profile_path.exists():
            try:
                raw = self.profile_path.read_text(encoding="utf-8")
                self._data = json.loads(raw)
                _logger.debug("[author_profile] 加载成功: %s", self.profile_path)
            except (json.JSONDecodeError, OSError) as e:
                _logger.warning("[author_profile] 加载失败 (%s), 使用默认档案并覆盖损坏文件", e)
                self._data = json.loads(json.dumps(_DEFAULT_PROFILE, ensure_ascii=False))
                self._data["metadata"]["created_at"] = datetime.now().isoformat(timespec="seconds")
                self._save()  # 覆盖损坏文件, 避免每次加载都告警
        else:
            _logger.info("[author_profile] 档案不存在, 创建默认档案: %s", self.profile_path)
            self._data = json.loads(json.dumps(_DEFAULT_PROFILE, ensure_ascii=False))
            self._data["metadata"]["created_at"] = datetime.now().isoformat(timespec="seconds")
            self._save()

    def _save(self):
        """保存档案到 JSON 文件。"""
        self._data["metadata"]["last_updated"] = datetime.now().isoformat(timespec="seconds")
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        self.profile_path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ── 读取 API ──

    def get(self, key: str, default: Any = None) -> Any:
        """获取档案字段。"""
        return self._data.get(key, default)

    @property
    def core_goals(self) -> list[str]:
        return self._data.get("core_goals", [])

    @property
    def preferred_tropes(self) -> list[str]:
        return self._data.get("preferred_tropes", [])

    @property
    def avoided_tropes(self) -> list[str]:
        return self._data.get("avoided_tropes", [])

    @property
    def writing_habits(self) -> dict:
        return self._data.get("writing_habits", {})

    @property
    def style_fingerprint(self) -> dict:
        return self._data.get("style_fingerprint", {})

    @property
    def feedback_history(self) -> list[dict]:
        return self._data.get("feedback_history", [])

    # ── 写入 API ──

    def set_core_goals(self, goals: list[str]):
        """设置核心目标 (覆盖)。"""
        self._data["core_goals"] = goals
        self._save()

    def add_preferred_trope(self, trope: str):
        """添加偏好套路 (去重)。"""
        if trope not in self._data["preferred_tropes"]:
            self._data["preferred_tropes"].append(trope)
            self._save()

    def add_avoided_trope(self, trope: str):
        """添加规避套路 (去重)。"""
        if trope not in self._data["avoided_tropes"]:
            self._data["avoided_tropes"].append(trope)
            self._save()

    def update_writing_habit(self, key: str, value: Any):
        """更新单个写作习惯字段 (覆盖旧值)。"""
        if "writing_habits" not in self._data:
            self._data["writing_habits"] = {}
        self._data["writing_habits"][key] = value
        self._save()

    def update_style_fingerprint(self, **kwargs):
        """更新风格指纹字段 (从拆书分析中提取)。

        Example:
            profile.update_style_fingerprint(avg_sentence_length=45, dialogue_ratio=0.35)
        """
        if "style_fingerprint" not in self._data:
            self._data["style_fingerprint"] = {}
        self._data["style_fingerprint"].update(kwargs)
        self._save()

    def record_feedback(self, feedback_type: str, accepted: bool,
                        detail: str = "", source: str = "s3_review"):
        """记录一次作者反馈 (接受/拒绝修改建议)。

        滚动保留最近 MAX_FEEDBACK_ENTRIES 条, 避免无限增长。

        Args:
            feedback_type: 反馈类型 (如 "弱化心理前缀", "增加反派阻碍")
            accepted: 作者是否接受了此建议
            detail: 详细描述
            source: 来源 (s3_review / s4_detection / manual)
        """
        entry = {
            "date": datetime.now().isoformat(timespec="seconds"),
            "type": feedback_type,
            "accepted": accepted,
            "detail": detail,
            "source": source,
        }
        self._data.setdefault("feedback_history", []).append(entry)

        # 滚动裁剪
        if len(self._data["feedback_history"]) > MAX_FEEDBACK_ENTRIES:
            self._data["feedback_history"] = self._data["feedback_history"][-MAX_FEEDBACK_ENTRIES:]

        self._save()
        _logger.debug("[author_profile] 记录反馈: %s (accepted=%s)", feedback_type, accepted)

    # ── LLM 集成 ──

    def to_prompt_suffix(self) -> str:
        """生成追加到 system prompt 的作者档案摘要。

        设计: 只提取 LLM 需要知道的关键信息, 保持简洁 (< 500 token)。
        """
        parts = ["[作者档案]"]

        if self.core_goals:
            parts.append(f"核心目标: {', '.join(self.core_goals)}")

        if self.preferred_tropes:
            parts.append(f"偏好套路: {', '.join(self.preferred_tropes)}")

        if self.avoided_tropes:
            parts.append(f"规避套路: {', '.join(self.avoided_tropes)}")

        habits = self.writing_habits
        if habits:
            habit_strs = [f"{k}={v}" for k, v in habits.items()]
            parts.append(f"写作习惯: {', '.join(habit_strs)}")

        fp = self.style_fingerprint
        if fp and any(v for v in fp.values()):
            fp_strs = [f"{k}={v}" for k, v in fp.items() if v]
            parts.append(f"风格指纹: {', '.join(fp_strs)}")

        # 最近 5 条反馈 (让 AI 知道作者近期的修改偏好)
        recent_fb = self.feedback_history[-5:]
        if recent_fb:
            fb_lines = []
            for fb in recent_fb:
                status = "✓" if fb.get("accepted") else "✗"
                fb_lines.append(f"  {status} {fb['type']}")
            parts.append("近期反馈:\n" + "\n".join(fb_lines))

        return "\n".join(parts)

    def get_accepted_feedback_types(self) -> list[str]:
        """获取作者已接受的反馈类型列表 (用于避免重复建议)。"""
        return [
            fb["type"] for fb in self.feedback_history
            if fb.get("accepted")
        ]

    def get_rejected_feedback_types(self) -> list[str]:
        """获取作者已拒绝的反馈类型列表 (用于调整建议策略)。"""
        return [
            fb["type"] for fb in self.feedback_history
            if not fb.get("accepted")
        ]

    # ── 导出 ──

    def to_dict(self) -> dict:
        """返回完整档案字典 (深拷贝)。"""
        return json.loads(json.dumps(self._data, ensure_ascii=False))

    def __repr__(self) -> str:
        return (
            f"<AuthorProfile path={self.profile_path} "
            f"goals={len(self.core_goals)} "
            f"feedbacks={len(self.feedback_history)}>"
        )


# ============================================================================
# 自检
# ============================================================================

def self_test():
    """运行模块自检。"""
    import tempfile

    tmp = tempfile.mkdtemp()
    profile_path = Path(tmp) / "author_profile.json"

    # 1. 首次创建
    profile = AuthorProfile(profile_path)
    assert profile_path.exists(), "[FAIL] 默认档案未创建"
    assert profile.core_goals == []
    print("  [OK] 首次创建默认档案")

    # 2. 设置核心目标
    profile.set_core_goals(["写末世题材爆款", "日更4000字"])
    assert len(profile.core_goals) == 2
    print("  [OK] set_core_goals")

    # 3. 添加偏好/规避套路
    profile.add_preferred_trope("废土求生")
    profile.add_preferred_trope("系统升级")
    profile.add_avoided_trope("圣母主角")
    assert len(profile.preferred_tropes) == 2
    assert len(profile.avoided_tropes) == 1
    # 去重测试
    profile.add_preferred_trope("废土求生")
    assert len(profile.preferred_tropes) == 2
    print("  [OK] tropes (去重)")

    # 4. 更新写作习惯
    profile.update_writing_habit("chapter_length", 3000)
    assert profile.writing_habits["chapter_length"] == 3000
    print("  [OK] update_writing_habit")

    # 5. 更新风格指纹
    profile.update_style_fingerprint(avg_sentence_length=45, dialogue_ratio=0.35)
    assert profile.style_fingerprint["avg_sentence_length"] == 45
    print("  [OK] update_style_fingerprint")

    # 6. 记录反馈
    profile.record_feedback("弱化心理前缀", accepted=True)
    profile.record_feedback("增加新角色", accepted=False)
    assert len(profile.feedback_history) == 2
    accepted = profile.get_accepted_feedback_types()
    rejected = profile.get_rejected_feedback_types()
    assert "弱化心理前缀" in accepted
    assert "增加新角色" in rejected
    print("  [OK] record_feedback")

    # 7. 重新加载 (持久化验证)
    profile2 = AuthorProfile(profile_path)
    assert len(profile2.core_goals) == 2
    assert len(profile2.feedback_history) == 2
    print("  [OK] 持久化加载")

    # 8. prompt suffix
    suffix = profile2.to_prompt_suffix()
    assert "[作者档案]" in suffix
    assert "废土求生" in suffix
    assert "圣母主角" in suffix
    assert "✓" in suffix
    assert "✗" in suffix
    print("  [OK] to_prompt_suffix")

    # 9. 反馈历史滚动裁剪
    for i in range(MAX_FEEDBACK_ENTRIES + 5):
        profile2.record_feedback(f"测试反馈{i}", accepted=True)
    assert len(profile2.feedback_history) == MAX_FEEDBACK_ENTRIES
    print("  [OK] 反馈历史滚动裁剪")

    # 清理
    import shutil
    shutil.rmtree(tmp)
    print("  [DONE] author_profile.py 自检完成")


if __name__ == "__main__":
    self_test()
