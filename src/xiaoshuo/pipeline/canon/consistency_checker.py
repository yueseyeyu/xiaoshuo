# -*- coding: utf-8 -*-
"""
consistency_checker — canon 一致性检查引擎 v7.6
=================================================
P2（大纲阶段）：检查大纲与 canon 设定的一致性
P3（写作阶段）：逐章检查正文与 canon 设定的一致性

用法:
    from xiaoshuo.pipeline.canon.consistency_checker import ConsistencyChecker
    checker = ConsistencyChecker()
    # P2: 大纲一致性
    result = checker.check_outline("assets/outline/rough_outline.md")
    # P3: 逐章一致性
    result = checker.check_chapter(chapter_num=1, chapter_text="...")
"""

import re
from pathlib import Path

from xiaoshuo import PROJECT_ROOT


class ConsistencyChecker:
    """P2/P3: 大纲/正文与 canon 设定的一致性检查引擎。"""

    def __init__(self):
        self.canon_dir = PROJECT_ROOT / "assets" / "canon"
        self._canon_cache = {}

    # ── 公共 API ──

    def check_outline(self, outline_path: str | Path = None,
                      outline_text: str = None) -> dict:
        """P2: 检查大纲是否与 canon 设定一致。

        Args:
            outline_path: 大纲文件路径
            outline_text: 大纲文本（路径和文本二选一）

        Returns:
            {"violations": [...], "warnings": [...], "pass": bool}
        """
        if outline_path:
            text = Path(outline_path).read_text(encoding="utf-8")
        elif outline_text:
            text = outline_text
        else:
            return {"error": "No outline provided", "violations": [], "warnings": []}

        violations = []
        warnings = []

        # 加载 canon 规则
        rules = self._load_canon("rules")
        characters = self._load_canon("characters")
        timeline = self._load_canon("timeline")

        # 检查1: 大纲是否覆盖所有三阶段
        if timeline:
            for phase in timeline.get("phases", []):
                phase_name = phase.get("name", "")
                phase_ch = phase.get("chapters", "")
                if phase_name.lower() not in text.lower():
                    violations.append({
                        "type": "missing_phase",
                        "rule": f"大纲未覆盖 {phase_name}（{phase_ch}）",
                        "severity": "high",
                    })

        # 检查2: 黄金三章事件是否在大纲中
        if timeline:
            for ch in timeline.get("golden_three", []):
                for event in ch.get("events", [])[:2]:  # 检查前2个事件
                    if event not in text:
                        warnings.append({
                            "type": "missing_golden_event",
                            "rule": f"大纲中未找到黄金三章事件: {event}",
                            "severity": "medium",
                        })
                        break

        # 检查3: 核心角色是否在大纲中登场
        if characters:
            for comp in characters.get("core_companions", []):
                name = comp.get("name", "")
                if name and name not in text:
                    warnings.append({
                        "type": "missing_character",
                        "rule": f"大纲中未提及核心同伴: {name}",
                        "severity": "medium",
                    })

        # 检查4: 力量体系是否在大纲中体现
        if rules:
            ps = rules.get("power_system", {})
            if ps.get("name", "") and ps["name"] not in text:
                violations.append({
                    "type": "missing_power_system",
                    "rule": f"大纲未提及力量体系: {ps['name']}",
                    "severity": "high",
                })

        # 检查5: 世界观规则约束
        if rules:
            for wr in rules.get("world_rules", []):
                rule_text = wr.get("rule", "")
                # 检查规则是否被违反（简单关键词匹配）
                keyword = self._extract_keyword(rule_text)
                if keyword and keyword not in text:
                    warnings.append({
                        "type": "rule_not_referenced",
                        "rule": f"大纲未体现规则: {rule_text[:50]}",
                        "severity": "low",
                    })

        return {
            "violations": violations,
            "warnings": warnings,
            "pass": len(violations) == 0,
            "violation_count": len(violations),
            "warning_count": len(warnings),
        }

    def check_chapter(self, chapter_num: int, chapter_text: str,
                      chapter_path: str | Path = None) -> dict:
        """P3: 检查单章正文是否与 canon 设定一致。

        Args:
            chapter_num: 章节号
            chapter_text: 章节正文
            chapter_path: 章节文件路径（可选）

        Returns:
            {"violations": [...], "warnings": [...], "pass": bool}
        """
        if chapter_path:
            text = Path(chapter_path).read_text(encoding="utf-8")
        else:
            text = chapter_text

        violations = []
        warnings = []

        rules = self._load_canon("rules")
        characters = self._load_canon("characters")
        foreshadowing = self._load_canon("foreshadowing")

        # 检查1: 规则一致性 — 是否有违反规则的描述
        if rules:
            for wr in rules.get("world_rules", []):
                if wr.get("exceptions") == "无":
                    # 无例外的规则，如果写了例外就是违规
                    pass  # 需要 LLM 辅助判断，当前仅做结构检查

        # 检查2: 角色名字一致性
        if characters:
            expected_names = self._get_character_names(characters)
            for name in expected_names:
                if name and name not in text:
                    warnings.append({
                        "type": "character_missing",
                        "rule": f"第{chapter_num}章未涉及角色: {name}",
                        "severity": "low",
                    })

        # 检查3: 伏笔状态检查
        if foreshadowing:
            for f in foreshadowing.get("active", []):
                if f.get("chapter_planted") == chapter_num:
                    warnings.append({
                        "type": "foreshadowing_checkpoint",
                        "rule": f"本章应埋下伏笔: {f['hook'][:50]}",
                        "severity": "medium",
                    })
                if f.get("expected_reveal") and str(chapter_num) in str(f.get("expected_reveal", "")):
                    warnings.append({
                        "type": "foreshadowing_reveal",
                        "rule": f"本章应回收伏笔: {f['hook'][:50]}",
                        "severity": "high",
                    })

        # 检查4: 时间线一致性
        timeline = self._load_canon("timeline")
        if timeline:
            for tp in timeline.get("major_turning_points", []):
                if tp.get("chapter") == chapter_num:
                    warnings.append({
                        "type": "turning_point",
                        "rule": f"本章为重大转折点: {tp['event']}",
                        "severity": "high",
                    })
                    if tp.get("event") not in text:
                        violations.append({
                            "type": "missing_turning_point",
                            "rule": f"第{chapter_num}章应包含转折点: {tp['event']}",
                            "severity": "high",
                        })

        return {
            "chapter": chapter_num,
            "violations": violations,
            "warnings": warnings,
            "pass": len(violations) == 0,
            "violation_count": len(violations),
            "warning_count": len(warnings),
        }

    def check_all_chapters(self, chapter_texts: dict[int, str]) -> dict:
        """P3: 批量检查所有章节。

        Args:
            chapter_texts: {chapter_num: text}

        Returns:
            {"results": {ch: {...}}, "summary": {...}}
        """
        all_results = {}
        total_violations = 0
        total_warnings = 0

        for ch, text in sorted(chapter_texts.items()):
            result = self.check_chapter(ch, text)
            all_results[ch] = result
            total_violations += result["violation_count"]
            total_warnings += result["warning_count"]

        return {
            "results": all_results,
            "summary": {
                "total_chapters": len(chapter_texts),
                "total_violations": total_violations,
                "total_warnings": total_warnings,
                "violation_chapters": [ch for ch, r in all_results.items() if not r["pass"]],
            },
        }

    # ── 内部工具 ──

    def _load_canon(self, name: str) -> dict:
        """加载 canon 数据（带缓存）。"""
        if name in self._canon_cache:
            return self._canon_cache[name]

        path = self.canon_dir / f"{name}.md"
        if not path.exists():
            return {}

        text = path.read_text(encoding="utf-8")

        # 解析 Markdown 为结构化数据
        data = self._parse_canon_md(text)
        self._canon_cache[name] = data
        return data

    def _parse_canon_md(self, text: str) -> dict:
        """解析 canon Markdown 文件为字典。"""
        result = {}
        sections = {}
        current = "preamble"
        current_lines = []
        for line in text.split("\n"):
            if line.startswith("## "):
                if current_lines:
                    sections[current] = "\n".join(current_lines)
                current = line[3:].strip()
                current_lines = []
            else:
                current_lines.append(line)
        if current_lines:
            sections[current] = "\n".join(current_lines)

        for title, content in sections.items():
            items = []
            for line in content.split("\n"):
                line = line.strip()
                if line.startswith("- **"):
                    parts = line[4:].split("**:", 1)
                    if len(parts) == 2:
                        if not items:
                            items.append({})
                        items[-1][parts[0].strip()] = parts[1].strip()
                elif line.startswith("- "):
                    items.append({"event": line[2:].strip()})

            if items:
                result[title.lower().replace(" ", "_")] = items

        return result

    def _get_character_names(self, characters_data: dict) -> list[str]:
        """从角色数据中提取所有角色名。"""
        names = []
        for section_name, items in characters_data.items():
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict) and "name" in item:
                        names.append(item["name"])
        return names

    def _extract_keyword(self, text: str) -> str:
        """从规则文本中提取关键词。"""
        # 简单提取：取第一个引号内的内容或前10个字符
        match = re.search(r'[「「](.+?)[」」]', text)
        if match:
            return match.group(1)
        return text[:10] if len(text) > 10 else ""