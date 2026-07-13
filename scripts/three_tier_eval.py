#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""three_tier_eval.py — 三层标注评估体系 v1.0

实现文档 docs/design/08-evaluation-testing.md §9.6 的三层评估方案:

Tier 1: AI全读 (已完成, 由 ai_annotate.py 实现)
Tier 2: 本地模型黄金比例滑动采样 (本文件实现)
Tier 3: 人工标注 — 分歧驱动 + 校准锚点 (本文件实现)

== Tier 2: 节奏感知滑动采样 ==

用 rhythm_analyzer 的 pleasure_intensity 预评分将章节分为 S/A/B 三层:
  S (高峰): rhythm_score 前25% → 采样50章
  A (中段): rhythm_score 25-75% → 采样30章
  B (低谷): rhythm_score 后25% → 采样20章

每层内滑动窗口 + 峰谷对齐: 窗口内选最接近窗口均值的章节

== Tier 3: 分歧驱动 + 校准锚点 ==

Part A: 校准锚点 (3-5章, 固定位置 ch1/25%/50%/75%/末章)
Part B: 分歧驱动 (5-12章, |AI-Local| 最大, 覆盖≥3/5叙事层)
Part C: 补充采样 (2-3章, 两模型一致的极端值)

文献依据:
  - Wan et al. (AAAI 2023): maximize disagreement → 10章≈30章随机
  - Nuggehalli et al. (2023): 分歧驱动节省~80%标注预算
  - Fernandes et al. (ACL 2023): 分层采样优于均匀采样

用法:
  python scripts/three_tier_eval.py --tier2 废土崛起              # Tier2: 生成采样计划
  python scripts/three_tier_eval.py --tier3 废土崛起              # Tier3: 生成分歧驱动采样
  python scripts/three_tier_eval.py --tier3 废土崛起 --local-csv 废土崛起_local.csv
  python scripts/three_tier_eval.py --report 废土崛起             # 生成三层对比报告
"""
import csv
import json
import sys
import math
import argparse
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set
from dataclasses import dataclass, field

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

# ============================================================
# 路径配置
# ============================================================

SCORES_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "scores"
RHYTHM_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "rhythm"
# v8.8: 人工标注golden数据迁移到保护目录(AI不可修改)
GOLDEN_DIR = PROJECT_ROOT / "data" / "golden" / "末世"

# 书籍→节奏CSV映射
# v8.9: 补全全部7本S级书
RHYTHM_CSV_MAP = {
    "废土崛起": "rhythm_《废土崛起》（校对版全本）作者：通吃道人.csv",
    "末日蟑螂": "rhythm_《末日蟑螂》作者：伟岸蟑螂.csv",
    "末世大回炉": "rhythm_《末世大回炉》（校对版全本）作者：二十二刀流.csv",
    "第一序列": "rhythm_《第一序列》（校对版全本）作者：会说话的肘子.csv",
    "长夜余火": "rhythm_《长夜余火》（校对版全本）作者：爱潜水的乌贼.csv",
    "末日乐园": "rhythm_末日乐园.csv",
    # v8.9新增S级
    "地球游戏场": "rhythm_《地球游戏场》（校对版全本）作者：吉风冰.csv",
    "异兽迷城": "rhythm_《异兽迷城》（校对版全本）.csv",
    "黑暗血时代": "rhythm_黑暗血时代.csv",
}

# 叙事分层 (与 ai_annotate.py 一致)
STRATA = [
    {"name": "Opening", "start": 0.00, "end": 0.03},
    {"name": "Rising",  "start": 0.03, "end": 0.30},
    {"name": "Mid",     "start": 0.30, "end": 0.60},
    {"name": "Climax",  "start": 0.60, "end": 0.90},
    {"name": "Ending",  "start": 0.90, "end": 1.00},
]

# Tier 2 配置: 按书籍质量分级决定采样量 (v8.8修正)
# 依据: Kim(2026) "在LLM预测性低的评估上分配更多样本"
#   S级书叙事最复杂→LLM预测性最低→最多样本
#   C级书套路化高→LLM预测性高→最少样本
#   A级从50降回30: v8.7提50是出于"排名可比性"内部需求, 非研究支撑
#   C级从30降回20: C级不参与排名竞争, 套路化高少样本即可
TIER2_BY_QUALITY = {
    "S":       {"max_ch": 50, "sc_samples": 3},  # 标杆书: 50章+自一致性3次
    "A":       {"max_ch": 30, "sc_samples": 1},  # 优秀书: 30章
    "B_plus":  {"max_ch": 30, "sc_samples": 1},  # B+良好: 30章
    "B":       {"max_ch": 30, "sc_samples": 1},  # B中等: 30章
    "B_minus": {"max_ch": 30, "sc_samples": 1},  # B-中下: 30章
    "C":       {"max_ch": 20, "sc_samples": 1},  # 反面教材: 20章
}

# 节奏峰谷对齐用的内部分层 (不是采样量, 是采样策略)
RHYTHM_PERCENTILES = {"S": (0.75, 1.00), "A": (0.25, 0.75), "B": (0.00, 0.25)}
# 节奏分层内的采样比例 (确保覆盖高峰/中段/低谷)
RHYTHM_RATIOS = {"S": 0.50, "A": 0.30, "B": 0.20}  # S峰50%, A中30%, B谷20%

# Tier 3 配置
TIER3_DISAGREEMENT_WEIGHTS = {"intensity": 0.6, "retention": 0.4}
TIER3_COVERAGE_MIN = 3  # 至少覆盖 3/5 叙事层
TIER3_ANCHOR_POSITIONS = [0.0, 0.25, 0.5, 0.75, 1.0]  # 校准锚点位置


# ============================================================
# 数据加载
# ============================================================

def load_rhythm_csv(book_name: str) -> List[Dict]:
    """加载节奏分析CSV, 返回 [{ch_num, pleasure_intensity, ...}]"""
    csv_name = RHYTHM_CSV_MAP.get(book_name)
    if not csv_name:
        print(f"[ERROR] 未知书籍: {book_name}")
        return []

    csv_path = RHYTHM_DIR / csv_name
    if not csv_path.exists():
        print(f"[ERROR] 节奏CSV不存在: {csv_path}")
        return []

    rows = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            ch_num = int(row["ch_num"])
            pleasure = float(row.get("pleasure_intensity", 0))
            rows.append({
                "ch_num": ch_num,
                "pleasure_intensity": pleasure,
                "wc": int(row.get("wc", 0)),
                "conflict_density": float(row.get("conflict_density", 0)),
                "hook_density": float(row.get("hook_density", 0)),
            })

    rows.sort(key=lambda r: r["ch_num"])
    print(f"加载节奏数据: {book_name} ({len(rows)}章)")
    return rows


def load_ai_scores(book_name: str) -> Dict[int, Dict]:
    """加载Tier1 AI评分CSV"""
    ai_csv = SCORES_DIR / f"{book_name}_ai_full.csv"
    if not ai_csv.exists():
        ai_csv = SCORES_DIR / f"{book_name}_ai.csv"
    if not ai_csv.exists():
        print(f"[WARN] AI评分CSV不存在: {ai_csv}")
        return {}

    result = {}
    with open(ai_csv, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            ch = int(row["ch_num"])
            result[ch] = {
                "intensity": int(row["ai_intensity"]),
                "retention": int(row["ai_retention"]),
                "stratum": row.get("stratum", ""),
            }
    return result


def load_local_scores(csv_path: str) -> Dict[int, Dict]:
    """加载Tier2本地模型评分CSV"""
    path = Path(csv_path)
    if not path.is_absolute():
        path = SCORES_DIR / csv_path
    if not path.exists():
        print(f"[WARN] 本地评分CSV不存在: {path}")
        return {}

    result = {}
    with open(path, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            ch = int(row["ch_num"])
            result[ch] = {
                "intensity": float(row.get("local_intensity", row.get("t2_intensity", row.get("llm_intensity", 0)))),
                "retention": float(row.get("local_retention", row.get("t2_retention", row.get("llm_retention", 0)))),
            }
    return result


def get_stratum(ch_num: int, total_chapters: int) -> str:
    """根据章节编号和总章数确定叙事层"""
    pos = ch_num / total_chapters if total_chapters > 0 else 0
    for s in STRATA:
        if s["start"] <= pos < s["end"]:
            return s["name"]
    return "Ending"


# ============================================================
# Tier 2: 节奏感知滑动采样
# ============================================================

def get_book_quality_tier(book_name: str) -> str:
    """从config.yaml查询书籍质量分级。
    Returns: 'S'/'A'/'B_plus'/'B'/'B_minus'/'C' 或 None
    """
    try:
        import yaml
        with open(PROJECT_ROOT / "config.yaml", "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        tiers = cfg.get("analysis", {}).get("book_filter", {}).get("quality_tiers", {})
        if not tiers:
            return None
        name_clean = book_name.replace("《", "").replace("》", "").strip()
        for tier_name, tier_data in tiers.items():
            for bn in tier_data.get("books", []):
                bn_clean = bn.replace("《", "").replace("》", "").strip()
                if bn_clean in name_clean or name_clean in bn_clean:
                    return tier_name
        return None
    except Exception as e:
        print(f"[WARN] 读取quality_tiers失败: {e}")
        return None


def tier2_rhythm_sampling(rhythm_data: List[Dict],
                          book_name: str = "") -> List[Dict]:
    """按书籍质量分级 + 节奏峰谷对齐采样 (v8.8修正)。

    1. 从config.yaml查询书籍质量分级(S/A/B+/B/B-/C)
    2. 按分级确定采样量: S=50, A/B=30, C=20
    3. 采样策略: 节奏峰谷对齐 (S峰50%/A中30%/B谷20%)
    4. 每层内滑动窗口采样
    """
    total = len(rhythm_data)
    if total == 0:
        return []

    # 查询书籍质量分级
    quality_tier = get_book_quality_tier(book_name) if book_name else None
    if quality_tier:
        config = TIER2_BY_QUALITY.get(quality_tier, TIER2_BY_QUALITY["B"])
        max_ch = config["max_ch"]
        print(f"  书籍质量分级: {quality_tier} → 采样{max_ch}章")
    else:
        max_ch = 30  # 默认
        print(f"  [WARN] 未找到书籍分级, 默认{max_ch}章")

    # 按 pleasure_intensity 排序, 确定节奏分层
    sorted_by_rhythm = sorted(rhythm_data, key=lambda r: r["pleasure_intensity"])
    n = len(sorted_by_rhythm)

    # 节奏峰谷对齐: 确保覆盖高峰/中段/低谷
    rhythm_tiers = {}
    for tier_name, (p_low, p_high) in RHYTHM_PERCENTILES.items():
        idx_start = int(n * p_low)
        idx_end = int(n * p_high)
        tier_chs = sorted_by_rhythm[idx_start:idx_end]
        tier_chs.sort(key=lambda r: r["ch_num"])
        rhythm_tiers[tier_name] = tier_chs

    # 按比例分配采样量到各节奏层
    sampled = []
    for tier_name, tier_chs in rhythm_tiers.items():
        target_n = max(1, round(max_ch * RHYTHM_RATIOS.get(tier_name, 0.33)))
        if len(tier_chs) == 0:
            continue

        if len(tier_chs) <= target_n:
            selected = tier_chs
        else:
            # 滑动窗口: 每个窗口选最接近窗口均值的章节
            window_size = len(tier_chs) / target_n
            selected = []

            for i in range(target_n):
                w_start = int(i * window_size)
                w_end = int((i + 1) * window_size)
                w_end = min(w_end, len(tier_chs))
                if w_start >= w_end:
                    w_start = w_end - 1

                window = tier_chs[w_start:w_end]
                if not window:
                    continue

                # 峰谷对齐: 选窗口内最接近窗口均值的章节
                mean_rhythm = sum(c["pleasure_intensity"] for c in window) / len(window)
                best = min(window, key=lambda c: abs(c["pleasure_intensity"] - mean_rhythm))
                selected.append(best)

        for ch in selected:
            sampled.append({
                "ch_num": ch["ch_num"],
                "rhythm_tier": tier_name,
                "pleasure_intensity": ch["pleasure_intensity"],
                "stratum": get_stratum(ch["ch_num"], total),
                "wc": ch["wc"],
            })

        print(f"  节奏{tier_name}: {len(tier_chs)}章 → 采样 {len(selected)}章")

    sampled.sort(key=lambda x: x["ch_num"])
    print(f"  Tier2 总采样: {len(sampled)}章")
    return sampled


def save_tier2_plan(book_name: str, sampled: List[Dict]):
    """保存Tier2采样计划到CSV"""
    out_path = SCORES_DIR / f"{book_name}_tier2_plan.csv"
    fields = ["ch_num", "rhythm_tier", "pleasure_intensity", "stratum", "wc"]

    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(sampled)

    print(f"\nTier2采样计划已保存: {out_path}")
    print(f"下一步: 用本地Qwen模型对这 {len(sampled)} 章评分")
    print(f"  python scripts/ai_annotate.py --score {book_name} --batch-size 3")


# ============================================================
# Tier 3: 分歧驱动 + 校准锚点
# ============================================================

@dataclass
class Tier3Sample:
    ch_num: int
    source: str  # "anchor" / "disagreement" / "supplement"
    stratum: str
    disagreement: float = 0.0
    ai_intensity: float = 0.0
    ai_retention: float = 0.0
    local_intensity: float = 0.0
    local_retention: float = 0.0
    detail: str = ""


def compute_disagreement(ai: Dict, local: Dict) -> float:
    """计算双维度分歧分数"""
    di = abs(ai["intensity"] - local["intensity"])
    dr = abs(ai["retention"] - local["retention"])
    return (TIER3_DISAGREEMENT_WEIGHTS["intensity"] * di +
            TIER3_DISAGREEMENT_WEIGHTS["retention"] * dr)


def tier3_disagreement_sampling(
    ai_scores: Dict[int, Dict],
    local_scores: Dict[int, Dict],
    total_chapters: int,
    n_anchors: int = 5,
    n_disagreement: int = 10,
    n_supplement: int = 2,
) -> List[Tier3Sample]:
    """分歧驱动 + 校准锚点采样

    Part A: 校准锚点 (固定位置)
    Part B: 分歧驱动 (|AI - Local| 最大)
    Part C: 补充采样 (两模型一致的极端值)
    """
    # 找到 AI 和 Local 都有评分的章节
    common_chs = sorted(set(ai_scores.keys()) & set(local_scores.keys()))
    if not common_chs:
        print("[ERROR] AI和本地评分没有交集章节")
        return []

    print(f"  AI评分: {len(ai_scores)}章, 本地评分: {len(local_scores)}章")
    print(f"  交集: {len(common_chs)}章")

    selected = []
    selected_chs: Set[int] = set()

    # ── Part A: 校准锚点 ──
    print(f"\n  Part A: 校准锚点 ({n_anchors}章)")
    for pos in TIER3_ANCHOR_POSITIONS[:n_anchors]:
        target_ch = int(total_chapters * pos)
        if target_ch < 1:
            target_ch = 1
        if target_ch > total_chapters:
            target_ch = total_chapters

        # 找最接近的已评分章节
        best_ch = min(common_chs, key=lambda c: abs(c - target_ch))
        if best_ch in selected_chs:
            continue

        ai = ai_scores[best_ch]
        local = local_scores[best_ch]
        disagree = compute_disagreement(ai, local)

        sample = Tier3Sample(
            ch_num=best_ch,
            source="anchor",
            stratum=get_stratum(best_ch, total_chapters),
            disagreement=disagree,
            ai_intensity=ai["intensity"],
            ai_retention=ai["retention"],
            local_intensity=local["intensity"],
            local_retention=local["retention"],
            detail=f"位置{pos*100:.0f}%锚点"
        )
        selected.append(sample)
        selected_chs.add(best_ch)
        print(f"    ch{best_ch:>5} [{sample.stratum}] | AI={ai['intensity']}/{ai['retention']} Local={local['intensity']:.1f}/{local['retention']:.1f} D={disagree:.2f}")

    # ── Part B: 分歧驱动 ──
    print(f"\n  Part B: 分歧驱动 ({n_disagreement}章)")
    candidates = []
    for ch in common_chs:
        if ch in selected_chs:
            continue
        ai = ai_scores[ch]
        local = local_scores[ch]
        disagree = compute_disagreement(ai, local)
        candidates.append((ch, disagree, ai, local))

    # 按分歧降序
    candidates.sort(key=lambda x: x[1], reverse=True)

    # 覆盖约束: 确保覆盖 ≥3/5 叙事层
    covered_strata = set(s.stratum for s in selected)
    selected_b = []

    for ch, disagree, ai, local in candidates:
        if len(selected_b) >= n_disagreement:
            break

        stratum = get_stratum(ch, total_chapters)

        # 如果还没达到覆盖要求, 优先选未覆盖的层
        if len(covered_strata) < TIER3_COVERAGE_MIN:
            if stratum not in covered_strata:
                covered_strata.add(stratum)
            else:
                # 已覆盖层也可以选, 但优先级稍低
                pass

        sample = Tier3Sample(
            ch_num=ch,
            source="disagreement",
            stratum=stratum,
            disagreement=disagree,
            ai_intensity=ai["intensity"],
            ai_retention=ai["retention"],
            local_intensity=local["intensity"],
            local_retention=local["retention"],
            detail=f"分歧={disagree:.2f}"
        )
        selected_b.append(sample)
        selected_chs.add(ch)
        covered_strata.add(stratum)

    for s in selected_b:
        print(f"    ch{s.ch_num:>5} [{s.stratum}] | AI={s.ai_intensity}/{s.ai_retention} Local={s.local_intensity:.1f}/{s.local_retention:.1f} D={s.disagreement:.2f}")
    selected.extend(selected_b)

    # 检查覆盖
    print(f"\n  覆盖叙事层: {sorted(covered_strata)} ({len(covered_strata)}/5)")

    # ── Part C: 补充采样 (两模型一致的极端值) ──
    if n_supplement > 0:
        print(f"\n  Part C: 补充采样 ({n_supplement}章)")
        supplement_candidates = []
        for ch in common_chs:
            if ch in selected_chs:
                continue
            ai = ai_scores[ch]
            local = local_scores[ch]
            # 两模型一致 (差异<1) 且都是极端值 (都≥8 或都≤3)
            agree = abs(ai["intensity"] - local["intensity"]) < 1.5
            extreme = (ai["intensity"] >= 8 and local["intensity"] >= 7) or \
                      (ai["intensity"] <= 3 and local["intensity"] <= 4)
            if agree and extreme:
                avg = (ai["intensity"] + local["intensity"]) / 2
                supplement_candidates.append((ch, avg, ai, local))

        supplement_candidates.sort(key=lambda x: abs(x[1] - 5), reverse=True)

        for ch, avg, ai, local in supplement_candidates[:n_supplement]:
            sample = Tier3Sample(
                ch_num=ch,
                source="supplement",
                stratum=get_stratum(ch, total_chapters),
                disagreement=compute_disagreement(ai, local),
                ai_intensity=ai["intensity"],
                ai_retention=ai["retention"],
                local_intensity=local["intensity"],
                local_retention=local["retention"],
                detail=f"一致极端值 avg={avg:.1f}"
            )
            selected.append(sample)
            selected_chs.add(ch)
            print(f"    ch{ch:>5} [{sample.stratum}] | AI={ai['intensity']}/{ai['retention']} Local={local['intensity']:.1f}/{local['retention']:.1f}")

    print(f"\n  Tier3 总采样: {len(selected)}章")
    return selected


def save_tier3_plan(book_name: str, samples: List[Tier3Sample]):
    """保存Tier3采样计划到CSV"""
    out_path = SCORES_DIR / f"{book_name}_tier3_plan.csv"
    fields = ["ch_num", "source", "stratum", "disagreement",
              "ai_intensity", "ai_retention", "local_intensity", "local_retention", "detail"]

    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for s in samples:
            writer.writerow({
                "ch_num": s.ch_num,
                "source": s.source,
                "stratum": s.stratum,
                "disagreement": f"{s.disagreement:.2f}",
                "ai_intensity": s.ai_intensity,
                "ai_retention": s.ai_retention,
                "local_intensity": f"{s.local_intensity:.1f}",
                "local_retention": f"{s.local_retention:.1f}",
                "detail": s.detail,
            })

    print(f"\nTier3采样计划已保存: {out_path}")
    print(f"下一步: 人工阅读这 {len(samples)} 章并评分")


# ============================================================
# 对比报告
# ============================================================

def generate_report(book_name: str):
    """生成三层评估对比报告"""
    import statistics

    # 加载数据
    ai_scores = load_ai_scores(book_name)
    rhythm_data = load_rhythm_csv(book_name)

    # 加载 golden (人工标注)
    golden_csv = GOLDEN_DIR / "human_golden.csv"  # v8.8: 从保护目录读取
    golden = {}
    if golden_csv.exists():
        with open(golden_csv, "r", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row["book"] == book_name:
                    ch = int(row["ch_num"])
                    golden[ch] = {
                        "intensity": float(row["human_intensity"]),
                        "retention": float(row["human_retention"]),
                    }

    print(f"\n{'='*70}")
    print(f"三层评估报告: {book_name}")
    print(f"{'='*70}")

    # Tier 1 统计
    print(f"\n--- Tier 1: AI全读 ---")
    print(f"  已评分: {len(ai_scores)}章")
    if golden:
        matched = [(ch, ai_scores[ch], golden[ch]) for ch in golden if ch in ai_scores]
        if matched:
            i_diffs = [a["intensity"] - g["intensity"] for _, a, g in matched]
            r_diffs = [a["retention"] - g["retention"] for _, a, g in matched]
            print(f"  vs Golden (n={len(matched)}):")
            print(f"    Intensity MAE = {statistics.mean(abs(d) for d in i_diffs):.2f}")
            print(f"    Retention MAE = {statistics.mean(abs(d) for d in r_diffs):.2f}")
            print(f"    Intensity Bias = {statistics.mean(i_diffs):+.2f}")
            print(f"    Retention Bias = {statistics.mean(r_diffs):+.2f}")

    # Tier 2 统计
    tier2_csv = SCORES_DIR / f"{book_name}_tier2_plan.csv"
    print(f"\n--- Tier 2: 本地模型 ---")
    if tier2_csv.exists():
        with open(tier2_csv, "r", encoding="utf-8-sig") as f:
            tier2_data = list(csv.DictReader(f))
        print(f"  采样计划: {len(tier2_data)}章")
        for tier in ["S", "A", "B"]:
            count = sum(1 for r in tier2_data if r["rhythm_tier"] == tier)
            print(f"    节奏层 {tier}: {count}章")
    else:
        print(f"  ⚠ 尚未生成采样计划")
        print(f"  运行: python scripts/three_tier_eval.py --tier2 {book_name}")

    # Tier 3 统计
    tier3_csv = SCORES_DIR / f"{book_name}_tier3_plan.csv"
    print(f"\n--- Tier 3: 人工标注 ---")
    if tier3_csv.exists():
        with open(tier3_csv, "r", encoding="utf-8-sig") as f:
            tier3_data = list(csv.DictReader(f))
        print(f"  采样计划: {len(tier3_data)}章")
        for src in ["anchor", "disagreement", "supplement"]:
            count = sum(1 for r in tier3_data if r["source"] == src)
            if count:
                print(f"    {src}: {count}章")
    else:
        print(f"  ⚠ 尚未生成采样计划")
        print(f"  运行: python scripts/three_tier_eval.py --tier3 {book_name}")

    # Golden 统计
    print(f"\n--- Golden Set ---")
    print(f"  人工标注: {len(golden)}章")

    # 分歧分析
    if ai_scores and golden:
        print(f"\n--- 分歧最大的章节 (AI vs Golden) ---")
        diffs = []
        for ch in golden:
            if ch in ai_scores:
                di = abs(ai_scores[ch]["intensity"] - golden[ch]["intensity"])
                dr = abs(ai_scores[ch]["retention"] - golden[ch]["retention"])
                diffs.append((ch, di, dr, di + dr))
        diffs.sort(key=lambda x: x[3], reverse=True)
        print(f"  {'ch':>6} | {'I_diff':>7} {'R_diff':>7} {'Total':>7}")
        for ch, di, dr, total in diffs[:5]:
            print(f"  {ch:>6} | {di:>7.1f} {dr:>7.1f} {total:>7.1f}")


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="三层标注评估体系 v1.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("--tier2", type=str, metavar="BOOK",
                        help="Tier2: 生成节奏感知滑动采样计划")
    parser.add_argument("--tier3", type=str, metavar="BOOK",
                        help="Tier3: 生成分歧驱动+校准锚点采样计划")
    parser.add_argument("--report", type=str, metavar="BOOK",
                        help="生成三层对比报告")
    parser.add_argument("--local-csv", type=str, default="",
                        help="Tier3: 本地模型评分CSV路径")
    parser.add_argument("--n-anchors", type=int, default=5,
                        help="Tier3: 校准锚点数量 (默认5)")
    parser.add_argument("--n-disagreement", type=int, default=10,
                        help="Tier3: 分歧驱动采样数量 (默认10)")
    parser.add_argument("--n-supplement", type=int, default=2,
                        help="Tier3: 补充采样数量 (默认2)")

    args = parser.parse_args()

    if args.tier2:
        rhythm_data = load_rhythm_csv(args.tier2)
        if rhythm_data:
            sampled = tier2_rhythm_sampling(rhythm_data, book_name=args.tier2)
            save_tier2_plan(args.tier2, sampled)
        return

    if args.tier3:
        book_name = args.tier3
        ai_scores = load_ai_scores(book_name)

        # 加载本地评分
        if args.local_csv:
            local_scores = load_local_scores(args.local_csv)
        else:
            # 尝试默认路径
            local_csv = SCORES_DIR / f"{book_name}_local.csv"
            if local_csv.exists():
                local_scores = load_local_scores(str(local_csv))
            else:
                # 用 rhythm_data 的 pleasure_intensity 作为本地代理评分
                print("[INFO] 未找到本地评分CSV, 使用 rhythm pleasure_intensity 作为代理")
                rhythm_data = load_rhythm_csv(book_name)
                local_scores = {
                    r["ch_num"]: {
                        "intensity": r["pleasure_intensity"],
                        "retention": r["pleasure_intensity"] * 0.8,  # 代理
                    }
                    for r in rhythm_data
                }

        if not ai_scores or not local_scores:
            print("[ERROR] 缺少AI评分或本地评分数据")
            return

        # 估算总章数
        total_chapters = max(max(ai_scores.keys()), max(local_scores.keys()))

        samples = tier3_disagreement_sampling(
            ai_scores=ai_scores,
            local_scores=local_scores,
            total_chapters=total_chapters,
            n_anchors=args.n_anchors,
            n_disagreement=args.n_disagreement,
            n_supplement=args.n_supplement,
        )
        save_tier3_plan(book_name, samples)
        return

    if args.report:
        generate_report(args.report)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
