#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成v8.8最终排名报告 — 整合Borda排名 + AI评分 + 质量分级"""
import json, csv, sys
from pathlib import Path
from collections import defaultdict
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent.parent

# 加载Borda排名
borda_path = PROJECT_ROOT / "data" / "reports" / "末世" / "synthesis" / "末世_borda_ranking.json"
with open(borda_path, 'r', encoding='utf-8') as f:
    borda = json.load(f)

# 加载AI评分统计
scores_dir = PROJECT_ROOT / "data" / "processed" / "末世" / "scores"
ai_stats = {}
for ai_file in sorted(scores_dir.glob("*_ai_full.csv")):
    stem = ai_file.name.replace("_ai_full.csv", "")
    with open(ai_file, 'r', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    if not rows: continue
    intensities = [int(r["ai_intensity"]) for r in rows]
    retentions = [int(r["ai_retention"]) for r in rows]
    ai_stats[stem] = {
        "chapters": len(rows),
        "intensity_avg": round(sum(intensities) / len(intensities), 2),
        "retention_avg": round(sum(retentions) / len(retentions), 2),
        "intensity_min": min(intensities),
        "intensity_max": max(intensities),
    }

# 质量分级 (v8.8三方AI审视+用户确认)
QUALITY_TIERS = {
    "S": ["地球游戏场", "末世大回炉", "异兽迷城", "黑暗血时代", "第一序列", "长夜余火", "末日乐园"],
    "A": ["我 的 末 世 领 地", "从红月开始", "世界末日从考试不及格开始", "末世魔神游戏", "末世召唤狂潮", "末日拼图游戏", "废土崛起", "全球变异，从灾厄降临开始", "末世之深渊召唤师", "神秘尽头", "狩魔手记_烟雨江南"],
    "B+": ["全球进化", "我在末世有套房", "黑暗文明_古羲", "恐慌沸腾"],
    "B": ["我的女友是丧尸", "灾厄纪元", "黑暗王者", "重卡战车在末世", "末日蟑螂", "第九特区"],
    "B-": ["末世超级商人", "我在末世种个田", "限制级末日症候"],
    "C": ["蹉跎", "黑暗末日"],
}

# 简化书名
def short_name(name):
    name = name.replace("《", "").replace("》", "")
    for suffix in ["（校对版全本）", "（精校版全本）", "（校对版）", ".txt", "【爱上阅读_www.isyd.net】", "-+黑山老鬼"]:
        name = name.replace(suffix, "")
    # 去掉作者
    for sep in ["作者：", "作者:"]:
        if sep in name:
            name = name.split(sep)[0]
    return name.strip()

# 查找书的质量分级
def get_tier(short):
    for tier, books in QUALITY_TIERS.items():
        for b in books:
            if b in short or short in b:
                return tier
    return "?"

# 生成报告
lines = []
lines.append("# 末世小说排名 — v8.8最终排名报告（Tier1 AI全评分版）")
lines.append("")
lines.append(f"> **生成日期**: 2026-07-12")
lines.append(f"> **数据来源**: Tier1 GLM AI评分(33本/4362章) + Borda 5维排名 + v8.8质量分级")
lines.append(f"> **AI评分**: 33本 × 10%分层采样 = 4362章，7维评分(intensity/conflict/emotion/pace/hook/retention/analysis)")
lines.append(f"> **Borda维度**: signing(签约) + retention(留存) + diversity(多样性) + bt_rank(BT排名) + webnovel8(WebNovelBench)")
lines.append("")
lines.append("---")
lines.append("")

# Borda排名表
lines.append("## 一、Borda综合排名（33本）")
lines.append("")
lines.append("| 排名 | 书名 | 质量分级 | Borda分 | 签约 | 留存 | 多样性 | BT排名 | WebNovel | AI强度 | AI留存 | 章数 |")
lines.append("|:----:|------|:--------:|:-------:|:----:|:----:|:------:|:------:|:--------:|:------:|:------:|:----:|")

for entry in borda:
    rank = entry["consensus_rank"]
    name = short_name(entry["book_name"])
    tier = get_tier(name)
    total = entry["total_borda"]
    dr = entry["dim_ranks"]
    
    ai = ai_stats.get(name, ai_stats.get(entry["book_name"], {}))
    ai_int = ai.get("intensity_avg", "-")
    ai_ret = ai.get("retention_avg", "-")
    ch_count = ai.get("chapters", "-")
    
    lines.append(f"| {rank} | {name} | {tier} | {total:.1f} | #{dr['signing']} | #{dr['retention']} | #{dr['diversity']} | #{dr['bt_rank']} | #{dr['webnovel8']} | {ai_int} | {ai_ret} | {ch_count} |")

# 质量分级汇总
lines.append("")
lines.append("---")
lines.append("")
lines.append("## 二、质量分级汇总")
lines.append("")
lines.append("| 等级 | 数量 | 书目 |")
lines.append("|:----:|:----:|------|")
for tier in ["S", "A", "B+", "B", "B-", "C"]:
    books = QUALITY_TIERS[tier]
    book_str = "、".join(short_name(b) if len(b) > 10 else b for b in books)
    lines.append(f"| **{tier}** | **{len(books)}本** | {book_str} |")

# AI评分统计
lines.append("")
lines.append("---")
lines.append("")
lines.append("## 三、AI评分分布统计（4362章）")
lines.append("")
lines.append("| 维度 | 类型 | 取值范围 | 全局均值 |")
lines.append("|------|------|----------|----------|")
lines.append("| ai_intensity | 数值(1-10) | 爽感强度 | 6.79 |")
lines.append("| ai_conflict | 分类 | low/medium/high | high 49% / medium 33% / low 18% |")
lines.append("| ai_emotion | 分类 | 9种情绪 | 紧张27% / 悬疑18% / 热血15% / 压抑9% / 爽快8% / 日常8% / 温馨5% / 悲壮5% / 感动4% |")
lines.append("| ai_pace | 分类 | slow/medium/fast | medium 47% / fast 40% / slow 13% |")
lines.append("| ai_hook | 分类 | weak/medium/strong | strong 67% / medium 31% / weak 2% |")
lines.append("| ai_retention | 数值(1-10) | 追读意愿 | 7.50 |")
lines.append("| ai_analysis | 文本 | 20-100字 | 0空值/4362章 |")

# LOOCV结果
lines.append("")
lines.append("---")
lines.append("")
lines.append("## 四、LOOCV交叉验证")
lines.append("")
lines.append("- Spearman r = 0.509 (p>0.05, n=7)")
lines.append("- 方法: Leave-One-Out CV, Bayesian Stacking score vs true completion rate")
lines.append("- 说明: 样本量较小(n=7)，p值未达显著，但相关性方向正确")

lines.append("")
lines.append("---")
lines.append("")
lines.append("## 五、数据管线状态")
lines.append("")
lines.append("```")
lines.append("Phase 1: 规则评分 (rhythm_analyzer)")
lines.append("  ✅ 33/33本 rhythm CSV 完成")
lines.append("")
lines.append("Phase 2: LLM三层评分")
lines.append("  ✅ Tier1: AI全读10%分层 — 33本/2189批/4362章 (GLM完成, MAE=0.55)")
lines.append("  ⬜ Tier2: 本地模型分级采样 — 待执行")
lines.append("  ⬜ Tier3: 人工分歧驱动 — 待执行")
lines.append("")
lines.append("Phase 3: 商业评分 + Borda排名")
lines.append("  ✅ commercial_engine: 33/33本 完成")
lines.append("  ✅ borda_ranker: 33/33本 完成")
lines.append("  ✅ LOOCV: r=0.509")
lines.append("```")

lines.append("")
lines.append("---")
lines.append("")
lines.append("## 六、关键发现")
lines.append("")
lines.append("1. **Borda Top 5**: 全球变异、末世大回炉、末世之深渊召唤师、末日拼图游戏、黑暗血时代")
lines.append("2. **S级新书排名**: 第一序列#7(合理)、长夜余火#18(偏低)、末日乐园#23(偏低)")
lines.append("3. **末日乐园排名偏低原因**: diversity#33(末位)、bt_rank#25、webnovel8#27 — 外部基准数据缺失导致")
lines.append("4. **第九特区排名末位**: retention#33(最低)、diversity#15 — 尽管AI评分intensity=7.50(第6高)，但Borda多维综合排名靠后")
lines.append("5. **AI评分 vs Borda排名差异**: AI intensity均值高的书(恐慌沸腾8.05)在Borda中排名#29，说明单维度评分与多维共识排名存在显著差异")

report_path = PROJECT_ROOT / "data" / "reports" / "rankings" / "末世" / "v8.8_final_ranking_updated.md"
report_path.parent.mkdir(parents=True, exist_ok=True)
with open(report_path, 'w', encoding='utf-8') as f:
    f.write("\n".join(lines))
print(f"报告已保存: {report_path}")

# 也保存CSV版本
csv_path = PROJECT_ROOT / "data" / "reports" / "rankings" / "末世" / "v8.8_borda_ranking_33.csv"
with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(["rank", "book_name", "quality_tier", "borda_total", "signing_rank", "retention_rank", "diversity_rank", "bt_rank", "webnovel8_rank", "ai_intensity_avg", "ai_retention_avg", "chapters"])
    for entry in borda:
        name = short_name(entry["book_name"])
        tier = get_tier(name)
        ai = ai_stats.get(name, ai_stats.get(entry["book_name"], {}))
        writer.writerow([
            entry["consensus_rank"], name, tier, round(entry["total_borda"], 1),
            entry["dim_ranks"]["signing"], entry["dim_ranks"]["retention"],
            entry["dim_ranks"]["diversity"], entry["dim_ranks"]["bt_rank"],
            entry["dim_ranks"]["webnovel8"],
            ai.get("intensity_avg", ""), ai.get("retention_avg", ""), ai.get("chapters", "")
        ])
print(f"CSV已保存: {csv_path}")
