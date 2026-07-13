# -*- coding: utf-8 -*-
"""
beat_detector — 章节节拍检测 v7.6
=================================
基于 rhythm_analyzer 的冲突密度 / 爽点密度 / 钩子密度曲线，
通过拐点检测算法定位 15 节拍位置，映射到网文 5 卷结构。

节拍映射（改编自 Save the Cat 15-beat，适配网文 300 章）：
  卷1 (1-60):   开场画面 → 催化剂 → 第一幕转折点
  卷2 (61-120):  B故事 → 娱乐游戏 → 中点（假胜利/假失败）
  卷3 (121-180): 反派逼近 → 一无所有 → 灵魂黑夜
  卷4 (181-240): 第三幕转折 → 结局线 → 高潮
  卷5 (241-300): 终场画面 → 收束

用法:
    from xiaoshuo.pipeline.scoring.beat_detector import BeatDetector
    detector = BeatDetector()
    beats = detector.detect(rhythm_csv_path, total_chapters=300)
"""

from pathlib import Path

import numpy as np


# ── 节拍定义 ──

BEAT_TEMPLATES = {
    "act1": {
        "name": "第一幕：设定",
        "chapters": "1-60",
        "beats": [
            {"id": "opening", "name": "开场画面", "chapter_pct": 0.0, "desc": "世界观的第一次展示，读者决定是否继续读"},
            {"id": "theme", "name": "主题陈述", "chapter_pct": 0.05, "desc": "暗示故事核心问题的对白或事件"},
            {"id": "catalyst", "name": "催化剂", "chapter_pct": 0.10, "desc": "打破主角日常的巨变事件"},
            {"id": "debate", "name": "犹豫", "chapter_pct": 0.15, "desc": "主角对催化剂的本能犹豫和抗拒"},
            {"id": "break_into_2", "name": "第一幕转折", "chapter_pct": 0.20, "desc": "主角做出决定，跨入新世界"},
        ],
    },
    "act2a": {
        "name": "第二幕上半：探索",
        "chapters": "61-120",
        "beats": [
            {"id": "b_story", "name": "B故事", "chapter_pct": 0.25, "desc": "支线/情感线展开，通常涉及核心同伴"},
            {"id": "fun_games", "name": "娱乐游戏", "chapter_pct": 0.35, "desc": "爽点密集区，读者最爱看的部分"},
            {"id": "midpoint", "name": "中点", "chapter_pct": 0.50, "desc": "假胜利或假失败——故事转向"},
        ],
    },
    "act2b": {
        "name": "第二幕下半：对抗",
        "chapters": "121-180",
        "beats": [
            {"id": "bad_guys_close_in", "name": "反派逼近", "chapter_pct": 0.55, "desc": "压力增大，内外夹击"},
            {"id": "all_is_lost", "name": "一无所有", "chapter_pct": 0.65, "desc": "最低谷，冲突密度峰值"},
            {"id": "dark_night", "name": "灵魂黑夜", "chapter_pct": 0.70, "desc": "主角在最低谷中的反思和觉醒"},
        ],
    },
    "act3": {
        "name": "第三幕：高潮",
        "chapters": "181-240",
        "beats": [
            {"id": "break_into_3", "name": "第三幕转折", "chapter_pct": 0.75, "desc": "获得新认知/新力量，开始反击"},
            {"id": "finale", "name": "结局线", "chapter_pct": 0.80, "desc": "最终对决的展开和推进"},
            {"id": "climax", "name": "高潮", "chapter_pct": 0.95, "desc": "终极对决"},
        ],
    },
    "act_epilogue": {
        "name": "终场",
        "chapters": "241-300",
        "beats": [
            {"id": "final_image", "name": "终场画面", "chapter_pct": 0.98, "desc": "与开场画面形成镜像，展示变化"},
            {"id": "resolution", "name": "收束", "chapter_pct": 1.00, "desc": "各条线回收，情感收束"},
        ],
    },
}


class BeatDetector:
    """检测章节节拍位置，评估结构完整性。"""

    def __init__(self, total_chapters: int = 300):
        self.total_chapters = total_chapters
        self.beats = self._build_beats(total_chapters)

    def _build_beats(self, total: int) -> list[dict]:
        """从模板构建节拍列表，映射到具体章节号。"""
        beats = []
        for act_key, act in BEAT_TEMPLATES.items():
            for b in act["beats"]:
                ch = max(1, int(b["chapter_pct"] * total))
                beats.append({
                    **b,
                    "chapter": ch,
                    "act": act_key,
                    "act_name": act["name"],
                })
        return sorted(beats, key=lambda x: x["chapter"])

    def detect(self, rhythm_csv_path: Path | str, total_chapters: int = None) -> dict:
        """从 rhythm_analyzer 输出中检测实际节拍位置。

        Args:
            rhythm_csv_path: rhythm_analyzer 输出的 CSV 路径
            total_chapters: 覆盖总章节数

        Returns:
            {
                "beats": [{"id": "opening", "expected_ch": 1, "detected_ch": 3, "confidence": 0.85}, ...],
                "completeness": 0.73,  # 节拍覆盖率
                "gaps": ["catalyst", "dark_night"],  # 缺失的节拍
                "warnings": ["中点位置偏移 12 章，可能节奏拖沓"],
            }
        """
        if total_chapters:
            self.total_chapters = total_chapters
            self.beats = self._build_beats(total_chapters)

        path = Path(rhythm_csv_path)
        if not path.exists():
            return {"error": f"File not found: {path}", "beats": [], "completeness": 0}

        # 读取 rhythm 数据
        try:
            import pandas as pd
            df = pd.read_csv(path)
        except ImportError:
            return {"error": "pandas required for beat detection", "beats": [], "completeness": 0}

        # 检测关键列
        conflict_col = self._find_column(df, ["conflict_density", "冲突密度"])
        hook_col = self._find_column(df, ["hook_density", "钩子密度"])
        satisfaction_col = self._find_column(df, ["satisfaction_density", "爽点密度"])

        if conflict_col is None:
            return {"error": "No conflict density column found", "beats": [], "completeness": 0}

        conflict = df[conflict_col].values
        hook = df[hook_col].values if hook_col else np.zeros_like(conflict)
        satisfaction = df[satisfaction_col].values if satisfaction_col else np.zeros_like(conflict)

        # 综合信号：冲突 + 钩子 - 爽点（低谷=冲突高+钩子低+爽点低）
        signal = conflict + hook * 0.5 - satisfaction * 0.3
        signal = self._smooth(signal, window=5)

        results = []
        for b in self.beats:
            expected = b["chapter"] - 1  # 0-indexed
            if expected >= len(signal):
                break

            # 在期望位置 ±10% 范围内搜索峰值/谷值
            window = max(5, int(self.total_chapters * 0.05))
            start = max(0, expected - window)
            end = min(len(signal), expected + window)

            if b["id"] in ("all_is_lost", "dark_night"):
                # 低谷检测：找最小值
                detected = start + np.argmin(signal[start:end])
            else:
                # 峰值检测：找最大值
                detected = start + np.argmax(signal[start:end])

            offset = detected - expected
            confidence = max(0, 1.0 - abs(offset) / window)

            results.append({
                "id": b["id"],
                "name": b["name"],
                "act": b["act_name"],
                "expected_ch": b["chapter"],
                "detected_ch": detected + 1,  # 1-indexed
                "offset": offset,
                "confidence": round(confidence, 2),
                "desc": b["desc"],
            })

        # 计算完整性
        found = sum(1 for r in results if r["confidence"] >= 0.5)
        completeness = round(found / len(results), 2) if results else 0

        # 缺失节拍
        gaps = [r["id"] for r in results if r["confidence"] < 0.3]

        # 警告
        warnings = []
        for r in results:
            if abs(r["offset"]) > self.total_chapters * 0.08:
                direction = "后" if r["offset"] > 0 else "前"
                warnings.append(
                    f"[{r['name']}] 位置偏移 {abs(r['offset'])} 章向{direction}，可能节奏问题"
                )

        return {
            "beats": results,
            "completeness": completeness,
            "gaps": gaps,
            "warnings": warnings,
            "total_chapters": self.total_chapters,
        }

    # ── v2: 情绪缓冲带检测 ──
    # 避免: 紧张→紧张→紧张 (读者疲劳) 或 缓冲→缓冲→缓冲 (节奏拖沓)
    # 理想: 紧张(3章) → 缓冲(1章) → 紧张(2章) → 缓冲(1章)

    @staticmethod
    def detect_emotion_buffer(
        emotion_values: list[float],
        chapter_nums: list[int] | None = None,
        high_threshold: float = 0.65,
        low_threshold: float = 0.35,
    ) -> dict:
        """v2: 检测紧张章节后是否有适当的"情绪缓冲"。

        Args:
            emotion_values: 每章情绪强度列表 (0-1 或 0-10，自动归一化)
            chapter_nums: 章节号列表 (可选，默认 1..N)
            high_threshold: 高紧张阈值 (归一化后)
            low_threshold: 低紧张阈值 (归一化后)

        Returns:
            {
                "pattern": [...],           # 每章标签 "high"/"low"/"mid"
                "max_tension_streak": int,  # 最长连续紧张章数
                "max_buffer_streak": int,   # 最长连续缓冲章数
                "warnings": [str],          # 问题列表
                "ideal_pattern": bool,      # 是否符合理想紧张-缓冲交替
            }
        """
        if not emotion_values:
            return {"pattern": [], "max_tension_streak": 0, "max_buffer_streak": 0,
                    "warnings": ["无数据"], "ideal_pattern": False}

        # 归一化到 0-1
        vals = np.array(emotion_values, dtype=float)
        vmin, vmax = vals.min(), vals.max()
        if vmax > vmin:
            vals_norm = (vals - vmin) / (vmax - vmin)
        else:
            vals_norm = np.zeros_like(vals)

        # 分类
        pattern = []
        for v in vals_norm:
            if v >= high_threshold:
                pattern.append("high")
            elif v <= low_threshold:
                pattern.append("low")
            else:
                pattern.append("mid")

        # 连续段检测
        max_tension = 0
        max_buffer = 0
        current_tension = 0
        current_buffer = 0
        tension_warned = False  # 每个连续段只警告一次
        buffer_warned = False
        warnings = []

        chs = chapter_nums or list(range(1, len(pattern) + 1))

        for i, p in enumerate(pattern):
            if p == "high":
                current_tension += 1
                current_buffer = 0
                buffer_warned = False  # 缓冲段结束，重置警告标志
                max_tension = max(max_tension, current_tension)
            elif p == "low":
                current_buffer += 1
                current_tension = 0
                tension_warned = False  # 紧张段结束，重置警告标志
                max_buffer = max(max_buffer, current_buffer)
            else:
                # mid 不打断连续计数
                pass

            # 紧张过长警告 (>=4 章无缓冲) — 每个连续段只警告一次
            if current_tension >= 4 and not tension_warned:
                warnings.append(
                    f"第{chs[max(0, i-current_tension+1)]}-{chs[i]}章连续{current_tension}章高紧张，"
                    "读者可能疲劳，建议插入缓冲章节"
                )
                tension_warned = True
            # 缓冲过长警告 (>=3 章无紧张) — 每个连续段只警告一次
            if current_buffer >= 3 and not buffer_warned:
                warnings.append(
                    f"第{chs[max(0, i-current_buffer+1)]}-{chs[i]}章连续{current_buffer}章低紧张，"
                    "节奏拖沓，建议推进冲突"
                )
                buffer_warned = True

        # 理想模式: 不存在过长连续紧张或缓冲
        ideal = max_tension <= 5 and max_buffer <= 2

        return {
            "pattern": pattern,
            "max_tension_streak": max_tension,
            "max_buffer_streak": max_buffer,
            "warnings": warnings,
            "ideal_pattern": ideal,
        }

    def _find_column(self, df, candidates: list[str]) -> str | None:
        """在 DataFrame 中查找匹配的列名。"""
        for c in candidates:
            if c in df.columns:
                return c
        return None

    def _smooth(self, data: np.ndarray, window: int = 5) -> np.ndarray:
        """滑动窗口平滑。"""
        if len(data) < window:
            return data
        kernel = np.ones(window) / window
        return np.convolve(data, kernel, mode="same")