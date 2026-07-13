#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""为7本S级书的Tier3章节生成GLM校准评分指令

已有golden: 废土崛起(10章), 末日蟑螂(10章), 末世大回炉(10章)
需要评分: 地球游戏场(15章), 异兽迷城(13章), 末日乐园(15章), 
          第一序列(14章), 长夜余火(10章), 黑暗血时代(15章)
          末世大回炉(5章补充)
"""
import io, sys, csv, json, os
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PROJECT = Path(__file__).parent.parent
TIER3_DIR = PROJECT / "data" / "golden" / "末世" / "tier3"
GOLDEN_CSV = PROJECT / "data" / "golden" / "末世" / "human_golden.csv"

# 已有golden标注的章节
existing_golden = set()
if GOLDEN_CSV.exists():
    with open(GOLDEN_CSV, 'r', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            book = row.get("book", "")
            ch = int(row.get("ch_num", 0))
            existing_golden.add((book, ch))

print(f"已有golden标注: {len(existing_golden)}章")

# 评分标准
RUBRIC = """# 章节评分标准 (1-10分制)

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
"""

# 为每本书生成评分指令
books_to_score = [
    "地球游戏场", "异兽迷城", "末日乐园", 
    "第一序列", "长夜余火", "黑暗血时代", "末世大回炉"
]

OUTPUT_DIR = TIER3_DIR / "rescore_prompts"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

for book in books_to_score:
    ch_dir = TIER3_DIR / f"{book}_chapters"
    plan_csv = TIER3_DIR / f"{book}_tier3_plan.csv"
    
    if not ch_dir.exists() or not plan_csv.exists():
        print(f"  ⬜ {book}: 缺少章节或计划文件")
        continue
    
    # 读取计划
    plan_rows = []
    with open(plan_csv, 'r', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            ch = int(row["ch_num"])
            # 跳过已有golden的
            if (book, ch) in existing_golden:
                continue
            row["ch_num"] = ch
            plan_rows.append(row)
    
    if not plan_rows:
        print(f"  ⬜ {book}: 全部已有golden标注")
        continue
    
    # 读取章节原文
    chapters = []
    missing = []
    for row in plan_rows:
        ch = row["ch_num"]
        ch_file = ch_dir / f"ch{ch:04d}.txt"
        if ch_file.exists():
            text = ch_file.read_text(encoding="utf-8", errors="replace")
            chapters.append({
                "ch_num": ch,
                "source": row.get("source", ""),
                "stratum": row.get("stratum", ""),
                "ai_intensity": row.get("ai_intensity", ""),
                "ai_retention": row.get("ai_retention", ""),
                "t2_intensity": row.get("t2_intensity", ""),
                "t2_retention": row.get("t2_retention", ""),
                "text": text,
            })
        else:
            missing.append(ch)
    
    if not chapters:
        print(f"  ⬜ {book}: 无可用章节原文")
        continue
    
    # 生成指令文件
    prompt = f"# {book} — Tier3校准评分指令\n\n"
    prompt += f"## 评分标准\n{RUBRIC}\n\n"
    prompt += f"## 待评分章节 ({len(chapters)}章)\n\n"
    
    for ch in chapters:
        prompt += f"### 第{ch['ch_num']}章\n"
        prompt += f"(采样: {ch['source']}/{ch['stratum']}, AI={ch['ai_intensity']}/{ch['ai_retention']}, T2={ch['t2_intensity']}/{ch['t2_retention']})\n\n"
        prompt += f"{ch['text']}\n\n---\n\n"
    
    prompt += f"""## 输出要求

请对以上{len(chapters)}章逐一评分，输出JSON数组，格式如下：

```json
[
  {{
    "ch_num": {chapters[0]['ch_num']},
    "intensity": 5,
    "retention": 5,
    "hook": "medium",
    "pace": "medium",
    "conflict": "medium",
    "emotion": "日常",
    "analysis": "20-50字评分理由"
  }},
  ...
]
```

注意：
- intensity和retention是1-10的整数
- 参考AI和T2的分数但不要被它们限制
- 你作为人类读者的代理，给出真实阅读体验的评分
- 如果章节文字不完整或异常，intensity给3分并在analysis中说明
"""
    
    out_file = OUTPUT_DIR / f"{book}_tier3_GLM指令.md"
    with open(out_file, 'w', encoding='utf-8') as f:
        f.write(prompt)
    
    status = f"✅ {book}: {len(chapters)}章"
    if missing:
        status += f" (缺{len(missing)}章原文: {missing})"
    print(f"  {status} → {out_file.name}")

print(f"\n完成！指令文件在: {OUTPUT_DIR}")
