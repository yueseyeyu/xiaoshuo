#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
生成DeepSeek V4 Pro交叉验证评分指令
=====================================
对95章GLM已评分章节进行独立重评，用于AI间一致性检验。
关键设计：不暴露T1/GLM/人工分数，确保完全独立。
"""
import json
import os
from pathlib import Path

PROJECT = Path(r"d:\Code\xiaoshuo")
TIER3 = PROJECT / "data" / "golden" / "末世" / "tier3"
GLM_JSON = TIER3 / "tier3_glm_scores.json"
OUT_DIR = TIER3 / "deepseek_xval_prompts"
OUT_DIR.mkdir(exist_ok=True)

# ── Scoring criteria (same as GLM, no score hints) ──
CRITERIA = """# 章节评分标准 (1-10分制)

## intensity (爽感强度 1-10)
1-2: 极度无聊，读者想跳过
3-4: 略有乏味，缺乏吸引力
5-6: 中等水平，可读但不兴奋
7-8: 较强吸引力，有明确爽点或悬念
9-10: 极致体验，让人欲罢不能

## retention (追读意愿 1-10)
1-2: 立刻弃书
3-4: 可能跳过，不太关心后续
5-6: 一般好奇，会继续看
7-8: 比较期待下一章
9-10: 迫不及待必须看下一章

## hook (章末悬念)
weak: 无悬念，平淡收尾
medium: 有些好奇，想知道后续
strong: 强悬念，必须看下一章

## pace (节奏)
slow: 节奏缓慢，铺垫过多
medium: 节奏适中
fast: 节奏明快，信息密集

## conflict (冲突程度)
low: 无明显冲突
medium: 有矛盾但不够激烈
high: 激烈对抗或重大事件

## emotion (情绪基调)
日常/紧张/爽快/悬疑/压抑/感动/悲壮/温馨/感慨/振奋/热血

## 重要提示
- 避免LLM常见的"高估偏差"：不要因为文字通顺就给7-8分
- 3-4分是正常的"普通章节"，大多数章节应该在4-7分区间
- 只有真正有强烈情绪波动或重大剧情转折的章节才给8+
- 参考人类阅读体验：读者是否会因为这一章而"不想放下手机"
- 你是一个严格的书评人，不是作者的粉丝"""

PREAMBLE = """# 末世小说章节质量交叉评分 — DeepSeek V4 Pro独立评审

## 任务说明
你是一名独立的网文质量评审员。请对以下章节进行独立评分。

**关键要求:**
1. 你必须完全独立评分，不要预设任何倾向
2. 评分基于章节文本本身的阅读体验
3. 严格按照下方评分标准执行
4. 每章给出: intensity(1-10整数), retention(1-10整数), hook, pace, conflict, emotion, analysis(一句话分析)
5. 分析要犀利、具体，不要泛泛而谈

## 输出格式
请严格按照以下JSON格式输出，不要输出其他内容:

```json
[
  {"ch_num": 1, "intensity": 5, "retention": 6, "hook": "medium", "pace": "medium", "conflict": "medium", "emotion": "紧张", "analysis": "一句话分析"},
  ...
]
```

---

"""

def read_chapter_text(book_name, ch_num):
    """Read chapter text from the chapter files."""
    # Try padded format: ch0001.txt
    padded = f"ch{ch_num:04d}.txt"
    ch_file = TIER3 / f"{book_name}_chapters" / padded
    if ch_file.exists():
        with open(ch_file, 'r', encoding='utf-8') as f:
            return f.read()
    # Try non-padded
    ch_file = TIER3 / f"{book_name}_chapters" / f"ch{ch_num}.txt"
    if ch_file.exists():
        with open(ch_file, 'r', encoding='utf-8') as f:
            return f.read()
    return None

def generate_prompts():
    with open(GLM_JSON, 'r', encoding='utf-8') as f:
        glm_data = json.load(f)
    
    master_log = []
    
    for book_name, chapters in glm_data.get("scores", {}).items():
        prompt_lines = []
        prompt_lines.append(PREAMBLE)
        prompt_lines.append(CRITERIA)
        prompt_lines.append("")
        prompt_lines.append(f"---")
        prompt_lines.append("")
        prompt_lines.append(f"## 待评分章节 ({len(chapters)}章)")
        prompt_lines.append("")
        prompt_lines.append(f"书名: 《{book_name}》")
        prompt_lines.append("")
        
        found = 0
        missing = 0
        
        for ch in chapters:
            ch_num = ch["ch_num"]
            text = read_chapter_text(book_name, ch_num)
            
            if text is None:
                missing += 1
                prompt_lines.append(f"### 第{ch_num}章")
                prompt_lines.append(f"[章节文本缺失]")
                prompt_lines.append("")
                continue
            
            found += 1
            prompt_lines.append(f"### 第{ch_num}章")
            prompt_lines.append(text.strip())
            prompt_lines.append("")
            prompt_lines.append("---")
            prompt_lines.append("")
        
        # Write prompt file
        safe_name = book_name.replace("/", "_").replace("\\", "_")
        out_file = OUT_DIR / f"{safe_name}_deepseek_xval.md"
        with open(out_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(prompt_lines))
        
        master_log.append(f"{book_name}: {found}/{len(chapters)} chapters found, missing={missing}")
        print(f"Generated: {out_file.name} ({found}/{len(chapters)} chapters)")
    
    # Write master README
    readme = """# DeepSeek V4 Pro 交叉验证评分 — 使用说明

## 背景
v8.11校准体系中，95章GLM(AI)评分被用作校准锚点，但存在AI自评循环论证风险（76%校准数据来自AI）。
本次交叉验证的目的是：用DeepSeek V4 Pro独立重评这95章，检验AI评分的一致性和可靠性。

## 7本S级书 × 95章

| 书名 | 章节数 | 指令文件 |
|------|--------|---------|
"""
    for book_name, chapters in glm_data.get("scores", {}).items():
        safe = book_name.replace("/", "_").replace("\\", "_")
        readme += f"| {book_name} | {len(chapters)} | {safe}_deepseek_xval.md |\n"
    
    readme += """
## 操作步骤

### 第1步：逐书发送指令
1. 打开 `{书名}_deepseek_xval.md`
2. 全选复制，粘贴到DeepSeek V4 Pro对话框
3. 发送，等待返回JSON

### 第2步：保存结果
将DeepSeek返回的JSON保存为同目录下 `{书名}_deepseek_result.json`

### 第3步：汇总分析
```bash
cd d:\\Code\\xiaoshuo
$env:PYTHONUTF8=1
D:\\miniconda3\\envs\\llm-shared\\python.exe scripts\\analyze_deepseek_xval.py
```

## 关键设计
1. **不暴露任何已有分数**: DeepSeek看不到T1/GLM/人工评分，确保完全独立
2. **相同评分标准**: 使用与GLM完全相同的1-10分制和维度定义
3. **相同章节文本**: 使用与GLM评分时完全相同的章节文本
4. **输出格式统一**: JSON格式，便于自动对比分析

## 预期分析结果
- DeepSeek vs GLM Pearson r（AI间一致性）
- DeepSeek vs T1 Pearson r（AI vs 原始评分）
- DeepSeek vs Human Pearson r（AI vs 人工，仅30章重叠）
- 三方一致性矩阵
- 如果DeepSeek-GLM r > 0.7: AI评分有客观性
- 如果DeepSeek-GLM r < 0.5: AI评分不可靠，需扩大人工标注
"""
    
    readme_file = OUT_DIR / "_使用说明.md"
    with open(readme_file, 'w', encoding='utf-8') as f:
        f.write(readme)
    
    print(f"\nMaster README: {readme_file}")
    print(f"Total: {sum(len(chs) for chs in glm_data['scores'].values())} chapters across {len(glm_data['scores'])} books")

if __name__ == "__main__":
    generate_prompts()
