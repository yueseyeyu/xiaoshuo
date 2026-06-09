#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
split_design.py -- 将 DESIGN.md (2643行) 拆分为子文档 + 索引主文档
运行: python docs/design/split_design.py
"""
import re
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DESIGN_PATH = os.path.join(ROOT, "DESIGN.md")
OUTPUT_DIR = os.path.join(ROOT, "docs", "design")

# ── 分组定义 ──
# (section_number_or_key, filename, display_title)
# section_number 对应 ## N. 开头的段落; "appendix" 对应 ## 附录; "14"/"15" 对应 ### 14./15.
GROUPS = [
    {
        "file": "01-philosophy.md",
        "title": "1. 设计哲学与目标",
        "sections": ["1"],
    },
    {
        "file": "02-architecture-overview.md",
        "title": "2. 系统总览 + 3. 分层架构",
        "sections": ["2", "3"],
    },
    {
        "file": "03-modules-core.md",
        "title": "4. 模块设计 (上半: 工作流引擎/知识图谱/检测引擎)",
        "sections": ["4a"],  # special: first half of §4
    },
    {
        "file": "04-modules-aux.md",
        "title": "4. 模块设计 (下半: 交互/节拍/漂移/编排/文件系统)",
        "sections": ["4b"],  # special: second half of §4
    },
    {
        "file": "05-data-config.md",
        "title": "5. 数据设计 + 6. 工作流设计",
        "sections": ["5", "6"],
    },
    {
        "file": "06-interface-protocol.md",
        "title": "7. 接口与通信设计",
        "sections": ["7"],
    },
    {
        "file": "07-security-compliance.md",
        "title": "8. 安全与合规设计",
        "sections": ["8"],
    },
    {
        "file": "08-evaluation-testing.md",
        "title": "9. 评估体系与质量保障",
        "sections": ["9"],
    },
    {
        "file": "09-deploy-roadmap.md",
        "title": "10. 部署 + 11. 风险 + 12. 演进路线图",
        "sections": ["10", "11", "12"],
    },
    {
        "file": "10-appendix.md",
        "title": "附录 + 架构重构说明",
        "sections": ["appendix", "14"],
    },
    {
        "file": "11-vision.md",
        "title": "15. 完整创作愿景与实现路径",
        "sections": ["15"],
    },
]


def read_design():
    with open(DESIGN_PATH, "r", encoding="utf-8") as f:
        return f.readlines()


def split_into_sections(lines):
    """将行列表按 ## 和 ### 14./15. 拆分为 dict[section_key] = [lines]"""
    sections = {}
    current_key = "header"
    current_lines = []

    for line in lines:
        # Match ## N. (top-level sections)
        m = re.match(r'^## (\d+)\.\s', line)
        # Match ## 附录
        m_app = re.match(r'^## 附录', line)
        # Match ### 14. / ### 15. (these use ### but are top-level)
        m_sub = re.match(r'^### (?:🆕\s+)?(\d+)\.\s', line)

        new_key = None
        if m:
            new_key = m.group(1)
        elif m_app:
            new_key = "appendix"
        elif m_sub and m_sub.group(1) in ("14", "15"):
            new_key = m_sub.group(1)

        if new_key:
            if current_lines:
                sections[current_key] = current_lines
            current_key = new_key
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        sections[current_key] = current_lines

    return sections


def split_section4(lines):
    """§4 太长(~892行), 在 ### 4.5 处切分为 4a/4b"""
    part_a = []
    part_b = []
    in_b = False
    for line in lines:
        if re.match(r'^### 4\.5\s', line):
            in_b = True
        if in_b:
            part_b.append(line)
        else:
            part_a.append(line)
    return part_a, part_b


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    lines = read_design()
    sections = split_into_sections(lines)

    # Split §4
    if "4" in sections:
        part_a, part_b = split_section4(sections["4"])
        sections["4a"] = part_a
        sections["4b"] = part_b
        del sections["4"]

    print(f"DESIGN.md: {len(lines)} lines, {len(sections)} sections found")
    for k in sorted(sections.keys(), key=lambda x: (x.isdigit(), int(x) if x.isdigit() else 99, x)):
        print(f"  §{k}: {len(sections[k])} lines")

    # Write sub-documents
    for group in GROUPS:
        filepath = os.path.join(OUTPUT_DIR, group["file"])
        content_lines = []
        for sec_key in group["sections"]:
            if sec_key in sections:
                content_lines.extend(sections[sec_key])
                content_lines.append("\n")

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"# {group['title']}\n\n")
            f.write(f"> Extracted from DESIGN.md | [Back to index](../../DESIGN.md)\n\n---\n\n")
            f.writelines(content_lines)

        total = sum(len(sections.get(s, [])) for s in group["sections"])
        print(f"  -> {group['file']}: {total} lines")

    # Write new slim DESIGN.md (index)
    index_lines = [
        "# 番茄小说 AI 辅助创作系统 -- 系统架构设计文档\n\n",
        "> **文档版本**: v7.4\n",
        "> **实际代码**: analysis/ 7步管线 + agents/ 9模块 + novel.py 15命令\n",
        "> **关联文档**: [AI_PROTOCOL.md](AI_PROTOCOL.md) | [config.yaml](config.yaml)\n\n",
        "---\n\n",
        "## 设计文档索引\n\n",
        "本文档是系统设计的主索引。各模块的详细设计已拆分为独立文档：\n\n",
        "| # | 文档 | 内容 |\n",
        "|---|------|------|\n",
    ]

    descriptions = [
        "设计哲学、目标、约束矩阵、术语定义",
        "系统定位、技术栈、模型选型、十层分层架构",
        "工作流引擎(M1)、知识图谱(M2)、语义记忆(M2b)、检测引擎(S4+++)",
        "交互接口(M5)、节拍分析(M5a)、风格漂移(M5b)、模型编排(M5d)、文件系统(M6)",
        "NovelGraph表结构、config.yaml配置、state.json状态",
        "AI协议注入、Prefix Caching、LLM通信协议",
        "六层防御体系、MASH对抗流水线、平台合规红线",
        "黄金测试集、模块评估指标、PAN 2026、A/B测试",
        "部署方案、技术风险、流程风险、演进路线图(P0-P3)",
        "设计决策记录、关键文件清单、版本历史、审视方法论",
        "十阶段创作辅助闭环、各阶段现状、风格涌现、蒸馏进化",
    ]

    for i, group in enumerate(GROUPS):
        desc = descriptions[i] if i < len(descriptions) else ""
        link = f"docs/design/{group['file']}"
        index_lines.append(f"| {i+1} | [{group['title']}]({link}) | {desc} |\n")

    index_lines.extend([
        "\n---\n\n",
        "## 快速导航\n\n",
        "### 按角色查看文档\n\n",
        "- **架构师**: [02-架构概览](docs/design/02-architecture-overview.md) -> [03-核心模块](docs/design/03-modules-core.md) -> [05-数据配置](docs/design/05-data-config.md)\n",
        "- **开发者**: [04-辅助模块](docs/design/04-modules-aux.md) -> [06-接口协议](docs/design/06-interface-protocol.md) -> [09-部署路线图](docs/design/09-deploy-roadmap.md)\n",
        "- **创作者**: [11-完整愿景](docs/design/11-vision.md) -> [08-评估测试](docs/design/08-evaluation-testing.md)\n",
        "- **审查者**: [07-安全合规](docs/design/07-security-compliance.md) -> [08-评估测试](docs/design/08-evaluation-testing.md) -> [10-附录](docs/design/10-appendix.md)\n",
        "\n",
        "### 按阶段查看文档\n\n",
        "- **Part A 数据管线**: [03-核心模块](docs/design/03-modules-core.md) (book_processor -> creative_bridge)\n",
        "- **Part B 骨架生成**: [04-辅助模块](docs/design/04-modules-aux.md) (world_builder / outline_builder / character_designer)\n",
        "- **Part C 写作交互**: [05-数据配置](docs/design/05-data-config.md) (state_machine workflow)\n",
        "- **Part D 对比保障**: [03-核心模块](docs/design/03-modules-core.md) (comparison_engine)\n",
        "- **Part E 风格涌现**: [11-完整愿景](docs/design/11-vision.md) (chapter_decisions -> style_emergence)\n",
    ])

    with open(DESIGN_PATH, "w", encoding="utf-8") as f:
        f.writelines(index_lines)

    print(f"\n  -> DESIGN.md: {len(index_lines)} lines (index only)")
    print(f"\nDone! {len(GROUPS)} sub-documents in docs/design/")


if __name__ == "__main__":
    main()
