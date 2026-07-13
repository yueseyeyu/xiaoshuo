#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""保存Borda排名快照 + 生成对比分析报告"""
import json, csv, sys, datetime
from pathlib import Path
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent.parent

# ── 1. 加载当前Borda排名 ──
borda = json.load(open(PROJECT_ROOT / "data" / "reports" / "末世" / "synthesis" / "末世_borda_ranking.json", 'r', encoding='utf-8'))

# ── 2. 简化书名 ──
def short_name(name):
    name = name.replace("《", "").replace("》", "")
    for suffix in ["（校对版全本）", "（精校版全本）", "（校对版）", ".txt", "【爱上阅读_www.isyd.net】", "-+黑山老鬼"]:
        name = name.replace(suffix, "")
    for sep in ["作者：", "作者:"]:
        if sep in name:
            name = name.split(sep)[0]
    return name.strip()

# ── 3. v8.8三方AI共识质量分级 ──
QUALITY_TIERS = {
    "S": ["地球游戏场", "末世大回炉", "异兽迷城", "黑暗血时代", "第一序列", "长夜余火", "末日乐园"],
    "A": ["我 的 末 世 领 地", "从红月开始", "世界末日从考试不及格开始", "末世魔神游戏", "末世召唤狂潮", "末日拼图游戏", "废土崛起", "全球变异", "末世之深渊召唤师", "神秘尽头", "狩魔手记"],
    "B+": ["全球进化", "我在末世有套房", "黑暗文明", "恐慌沸腾"],
    "B": ["我的女友是丧尸", "灾厄纪元", "黑暗王者", "重卡战车在末世", "末日蟑螂", "第九特区"],
    "B-": ["末世超级商人", "我在末世种个田", "限制级末日症候"],
    "C": ["蹉跎", "黑暗末日"],
}

def get_tier(short):
    for tier, books in QUALITY_TIERS.items():
        for b in books:
            if b in short or short in b:
                return tier
    return "?"

# ── 4. 之前的Borda排名 (v8.7版, 30本, 无3本S级新书) ──
PREVIOUS_BORDA = {
    "地球游戏场": 1, "末世之深渊召唤师": 2, "末世大回炉": 3, "黑暗血时代": 4,
    "末日拼图游戏": 5, "全球变异": 6, "我的末世领地": 7, "从红月开始": 8,
    "世界末日从考试不及格开始": 9, "末世魔神游戏": 10, "废土崛起": 11,
    "末世召唤狂潮": 12, "神秘尽头": 13, "黑暗文明": 14, "异兽迷城": 15,
    "狩魔手记": 16, "我在末世有套房": 17, "第九特区": 18, "黑暗王者": 19,
    "我的女友是丧尸": 20, "重卡战车在末世": 21, "灾厄纪元": 22,
    "全球进化": 23, "末日蟑螂": 24, "末世超级商人": 25, "我在末世种个田": 26,
    "限制级末日症候": 27, "恐慌沸腾": 28, "蹉跎": 29, "黑暗末日": 30,
}

# ── 5. 保存快照 ──
snapshot_dir = PROJECT_ROOT / "data" / "reports" / "rankings" / "末世"
snapshot_dir.mkdir(parents=True, exist_ok=True)

# JSON快照
snapshot = {
    "snapshot_date": datetime.datetime.now().isoformat(),
    "description": "Borda排名快照 - Tier1 AI评分完成后(33本完整版)",
    "total_books": len(borda),
    "ranking": []
}
for entry in borda:
    name = short_name(entry["book_name"])
    snapshot["ranking"].append({
        "rank": entry["consensus_rank"],
        "book": name,
        "quality_tier": get_tier(name),
        "borda_total": round(entry["total_borda"], 1),
        "dim_ranks": entry["dim_ranks"],
        "previous_borda_rank": PREVIOUS_BORDA.get(name, None),
    })

snapshot_path = snapshot_dir / "v8.8_borda_snapshot_33books.json"
with open(snapshot_path, 'w', encoding='utf-8') as f:
    json.dump(snapshot, f, ensure_ascii=False, indent=2)
print(f"✅ JSON快照已保存: {snapshot_path}")

# ── 6. 生成对比分析报告 ──
lines = []
lines.append("# Borda排名说明与对比分析")
lines.append("")
lines.append(f"> **快照日期**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
lines.append(f"> **数据状态**: Tier1 AI评分100%完成后, 33本完整Borda排名")
lines.append("")
lines.append("---")
lines.append("")
lines.append("## 一、Borda排名是什么？有什么用？")
lines.append("")
lines.append("### 1.1 原理")
lines.append("")
lines.append("Borda Count（博尔达计数法）是一种**多维度共识排名**方法：")
lines.append("")
lines.append("1. 选取5个独立维度，分别对33本书排序")
lines.append("2. 每个维度中，排名第1得1分，排名第2得2分...排名第33得33分")
lines.append("3. 将5个维度的排名求和，**总分越低 = 综合排名越高**")
lines.append("")
lines.append("### 1.2 五个维度")
lines.append("")
lines.append("| 维度 | 含义 | 数据来源 | 为什么重要 |")
lines.append("|------|------|----------|-----------|")
lines.append("| **signing** | 签约潜力分 | commercial_engine计算(节奏指标+LLM评分+结构匹配) | 预测番茄平台签约概率 |")
lines.append("| **retention** | 读者留存分 | commercial_engine计算(分段留存率+hook密度+LLM retention) | 预测读者追读完成率 |")
lines.append("| **diversity** | 爽点多样性 | rhythm_analyzer统计(18种爽点子类型分布) | 衡量写作技巧丰富度，避免单一套路 |")
lines.append("| **bt_rank** | BT相对排名 | 外部基准数据(笔趣阁/贴吧热度) | 外部市场验证 |")
lines.append("| **webnovel8** | WebNovelBench综合 | 外部AI基准评测(8维质量评分) | AI视角的文学质量评估 |")
lines.append("")
lines.append("### 1.3 用途")
lines.append("")
lines.append("Borda排名在项目中的核心作用：")
lines.append("")
lines.append("1. **客观基准线**: 为三方AI人工分级提供量化参照系。AI分级考虑了外部声誉/文学性等定性因素，Borda提供纯数据驱动的定量排名")
lines.append("2. **异常检测**: 当Borda排名与质量分级严重偏离时，提示需要人工复查（如末日乐园S级但Borda#23）")
lines.append("3. **LOOCV校准**: 通过Leave-One-Out交叉验证，检验Borda分与真实完读率的相关性(r=0.509)")
lines.append("4. **维度诊断**: dim_ranks暴露每本书的短板（如黑暗血时代retention#32=留存极差，但其他维度顶级）")
lines.append("5. **不是最终裁决**: Borda是输入之一，不是输出。最终质量分级由三方AI+用户确认，Borda只是参考")
lines.append("")
lines.append("---")
lines.append("")
lines.append("## 二、当前Borda排名 vs 三方AI质量分级：差异对比")
lines.append("")
lines.append("### 2.1 对比总表")
lines.append("")
lines.append("| Borda排名 | 书名 | 质量分级 | Borda分 | 上次Borda | 变化 | 差异说明 |")
lines.append("|:---------:|------|:--------:|:-------:|:---------:|:----:|---------|")

for entry in borda:
    name = short_name(entry["book_name"])
    tier = get_tier(name)
    rank = entry["consensus_rank"]
    total = entry["total_borda"]
    prev = PREVIOUS_BORDA.get(name)
    prev_str = f"#{prev}" if prev else "🆕"
    if prev:
        delta = rank - prev
        if delta < 0:
            change = f"↑{-delta}"
        elif delta > 0:
            change = f"↓{delta}"
        else:
            change = "—"
    else:
        change = "新书"
    
    # 差异分析
    if tier == "S" and rank > 10:
        diff = f"⚠️ S级但Borda#{rank}偏低"
    elif tier == "S" and rank <= 10:
        diff = "✅ S级与Borda一致"
    elif tier == "A" and rank <= 5:
        diff = f"⚠️ A级但Borda#{rank}很高"
    elif tier == "A" and rank > 15:
        diff = f"A级Borda#{rank}中等"
    elif tier in ("B+", "B", "B-", "C") and rank <= 10:
        diff = f"⚠️ {tier}级但Borda#{rank}偏高"
    elif tier in ("B+", "B", "B-", "C") and rank > 25:
        diff = f"✅ {tier}级与Borda一致"
    else:
        diff = ""
    
    lines.append(f"| {rank} | {name} | {tier} | {total:.1f} | {prev_str} | {change} | {diff} |")

lines.append("")
lines.append("### 2.2 关键差异分析")
lines.append("")

# 找出最大差异
lines.append("#### 差异最大Top 5（质量分级 vs Borda排名）")
lines.append("")
lines.append("| 书名 | 质量分级 | Borda排名 | 差距 | 原因 |")
lines.append("|------|:--------:|:---------:|:----:|------|")

big_diffs = [
    ("末日乐园", "S", 23, "S级#23, 差距最大", "dynamics#33(末位)+bt#25+webnovel8#27。800万字2428章超长篇，rhythm分析只取10%=245章，章节间节奏波动大导致diversity极低。外部基准数据缺失(BT/WebNovelBench无此书数据)拉低排名"),
    ("长夜余火", "S", 18, "S级#18, 偏低", "signing#31(倒数第3)。乌贼文风偏文学/公路片，节奏指标(slap/hook密度)天然偏低。bt#16/webnovel8#16中等，综合被signing拖累"),
    ("异兽迷城", "S", 14, "S级#14, 中等", "Borda各维度均匀但无突出项(#10-#18)。之前30本Borda排#4，加入3本新书后相对下降"),
    ("恐慌沸腾", "B+", 29, "B+级#29, 偏低", "AI intensity=8.05(全局最高!)但Borda五维全面偏低。章节解析修复后仅131章(原1487章误解析)，rhythm数据量不足影响评分精度"),
    ("第九特区", "B", 33, "B级#33, 末位", "retention#33(最低)+diversity#15。278章10%采样=278章最多，但retention均值8.33(第3高)与Borda retention排名矛盾——说明Borda的retention维度不只看AI评分，还综合了rhythm的hook密度等规则指标"),
]

for name, tier, rank, gap, reason in big_diffs:
    lines.append(f"| {name} | {tier} | #{rank} | {gap} | {reason} |")

lines.append("")
lines.append("### 2.3 为什么会不一样？")
lines.append("")
lines.append("根本原因：**Borda排名和三方AI质量分级衡量的是不同的东西**。")
lines.append("")
lines.append("| 对比维度 | Borda排名 | 三方AI质量分级 |")
lines.append("|----------|-----------|---------------|")
lines.append("| **衡量什么** | 5个量化指标的综合排名 | 文字质量+外部声誉+文学性+鼻祖效应过滤 |")
lines.append("| **数据来源** | rhythm规则指标 + AI评分 + 外部基准 | DeepSeek/Kimi/Doubao联网搜索 + 人工判断 |")
lines.append("| **决策方式** | 纯算法（排序→求和） | 三方独立评审→共识→用户裁决 |")
lines.append('| **可解释性** | 每本书有5个维度排名，短板一目了然 | 每本书有定性理由（如豆瓣8.1、十万均订） |')
lines.append("| **对外部数据的依赖** | 高（BT/WebNovelBench缺失=直接末位） | 低（AI可联网搜索补充） |")
lines.append("| **对新书** | 不友好（缺少外部基准数据） | 友好（AI可基于作品本身质量判断） |")
lines.append("| **对超长篇** | 不友好（diversity被稀释） | 友好（AI理解长篇结构） |")
lines.append("")
lines.append("#### 具体差异原因：")
lines.append("")
lines.append("1. **外部基准数据缺失**: 3本S级新书（第一序列/长夜余火/末日乐园）在BT排名和WebNovelBench中缺数据或数据薄弱，直接拉低Borda分。但三方AI通过联网搜索确认了它们的市场地位")
lines.append("")
lines.append("2. **超长篇diversity稀释**: 末日乐园2428章，10%采样=245章。章节间风格变化大导致爽点类型分布分散，diversity#33（末位）。但AI评审认为800万字完结本身就是质量的证明")
lines.append("")
lines.append('3. **Borda不看外部声誉**: 地球游戏场在番茄/起点讨论度低，三方AI曾建议降级。但Borda纯粹看内部指标，signing#2+diversity#3使其排名靠前。最终用户裁决维持S级')
lines.append("")
lines.append("4. **Borda的retention维度≠AI retention均值**: Borda的retention_score综合了rhythm规则指标（hook密度/分段留存率）+AI retention。第九特区AI retention=8.33（第3高），但rhythm hook密度低，综合后retention排名#33")
lines.append("")
lines.append("5. **鼻祖效应过滤**: 末日蟑螂/蹉跎等老作品，三方AI主动降级（过滤鼻祖效应），但Borda纯粹看数据，不管年份。末日蟑螂Borda#28 vs B级，蹉跎Borda#30 vs C级，基本一致")
lines.append("")
lines.append("### 2.4 结论：哪个更准确？")
lines.append("")
lines.append("**两个都不够准确，所以需要互相补充。**")
lines.append("")
lines.append("- **Borda擅长**: 发现内部指标异常（如黑暗血时代retention#32=留存短板），提供可量化的维度诊断")
lines.append("- **三方AI擅长**: 理解外部语境（如第一序列的中国图书馆典藏、末日乐园的女频天花板地位），做出人类直觉一致的质量判断")
lines.append("- **最终方案**: 以三方AI质量分级为**主**（S/A/B分级），Borda排名为**辅**（维度诊断+异常检测+LOOCV校准）")
lines.append("")
lines.append("---")
lines.append("")
lines.append("## 三、本次Borda vs 上次Borda变化")
lines.append("")
lines.append("上次Borda(30本, v8.7) → 本次Borda(33本, v8.8, 加入3本S级新书)")
lines.append("")
lines.append("### 3.1 排名变化Top 5")
lines.append("")
lines.append("| 书名 | 上次 | 本次 | 变化 | 原因 |")
lines.append("|------|:----:|:----:|:----:|------|")
lines.append("| 地球游戏场 | #1 | #6 | ↓5 | 被全球变异超越，且3本新书加入后相对排名下降 |")
lines.append("| 全球变异 | #6 | #1 | ↑5 | 新LLM数据更完整，5维全面上升 |")
lines.append("| 黑暗血时代 | #4 | #5 | ↓1 | 基本稳定，略受新书加入影响 |")
lines.append("| 异兽迷城 | #15 | #14 | ↑1 | 微升 |")
lines.append("| 第九特区 | #18 | #33 | ↓15 | 278章最多采样量，diversity被稀释+retention#33 |")
lines.append("")
lines.append("### 3.2 新加入3本S级书排名")
lines.append("")
lines.append("| 书名 | Borda排名 | Borda分 | 分析 |")
lines.append("|------|:---------:|:-------:|------|")
lines.append("| 第一序列 | #7 | 55.9 | bt#2(外部验证强)+diversity#17(中等)，整体合理 |")
lines.append("| 长夜余火 | #18 | 90.0 | signing#31(短板)+bt#16/webnovel8#16(中等)，文学性高但节奏指标弱 |")
lines.append("| 末日乐园 | #23 | 99.8 | diversity#33(末位)+外部基准弱，超长篇结构导致指标分散 |")
lines.append("")
lines.append("---")
lines.append("")
lines.append("## 四、Borda五维诊断卡（每本书的短板一览）")
lines.append("")
lines.append("| 书名 | 签约 | 留存 | 多样性 | BT | WebNovel | 最大短板 |")
lines.append("|------|:----:|:----:|:------:|:--:|:--------:|---------|")

for entry in borda:
    name = short_name(entry["book_name"])
    dr = entry["dim_ranks"]
    dims = [("签约", dr["signing"]), ("留存", dr["retention"]), ("多样性", dr["diversity"]), ("BT", dr["bt_rank"]), ("WebNovel", dr["webnovel8"])]
    worst = max(dims, key=lambda x: x[1])
    lines.append(f"| {name} | #{dr['signing']} | #{dr['retention']} | #{dr['diversity']} | #{dr['bt_rank']} | #{dr['webnovel8']} | {worst[0]}#{worst[1]} |")

lines.append("")
lines.append("---")
lines.append("")
lines.append("*本文件为Borda排名快照+对比分析，与v8.8_final_ranking.md（三方AI质量分级）互补使用*")

report_path = snapshot_dir / "v8.8_borda_analysis.md"
with open(report_path, 'w', encoding='utf-8') as f:
    f.write("\n".join(lines))
print(f"✅ 对比分析报告已保存: {report_path}")
