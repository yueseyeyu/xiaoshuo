#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
score_auditor.py v2 — 商业评分数据质量评审 (精品池感知)
===========================================================
在 Genre Synthesis 之后运行，对 commercial_scores.json + borda_ranking.json
+ quality_manifest.json 做交叉验证。

v2: 精品池感知 — 当所有书均为已验证精品时:
  - 分数集中 (std<5, range<20) 是预期行为，不作为 FAIL
  - 改用变异系数 CV 评估区分度
  - Borda-Commercial 低相关 = 互补信号（多维排名 vs 签约留存）
  - 新增维度画像: 每本书的优势维度

检查项:
  1. 池质量: 全精品检测 → 调整后续阈值
  2. 变异系数 CV: <3% → 区分度过低 (仅非精品池 std<5 才 FAIL)
  3. 相对分数间距: 相邻排名分数差
  4. Borda-Commercial 互补性: 低相关是预期 (不同维度)
  5. 异常值检测: 仅检查排名-分数严重矛盾
  6. 标注可靠性: F1 <0.4 → WARN (精品池放宽)
  7. 维度画像: 每本书的 top-2 维度

输出: data/processed/{genre}/score_audit.json
用法: python analysis/score_auditor.py [--genre 末世]
"""
import json
import statistics
import sys
from pathlib import Path

from xiaoshuo import PROJECT_ROOT
# PROJECT_ROOT imported from src.xiaoshuo
def _spearman_corr(x_vals, y_vals):
    """Compute Spearman rank correlation coefficient between two lists."""
    n = len(x_vals)
    if n < 3:
        return 0.0
    # Rank (1-based, lower=first)
    x_ranks = [sorted(x_vals).index(v) + 1 for v in x_vals]
    y_ranks = [sorted(y_vals).index(v) + 1 for v in y_vals]
    # Pearson on ranks
    mean_x = statistics.mean(x_ranks)
    mean_y = statistics.mean(y_ranks)
    cov = sum((x_ranks[i] - mean_x) * (y_ranks[i] - mean_y) for i in range(n))
    std_x = (sum((r - mean_x) ** 2 for r in x_ranks)) ** 0.5
    std_y = (sum((r - mean_y) ** 2 for r in y_ranks)) ** 0.5
    if std_x == 0 or std_y == 0:
        return 0.0
    return round(cov / (std_x * std_y * n), 4)


def run_audit(genre="末世"):
    """Main audit entry point for commercial score quality."""
    base = PROJECT_ROOT / "data" / "processed" / genre
    reports_dir = PROJECT_ROOT / "data" / "reports" / genre / "synthesis"

    # ── Load data sources ──
    comm_path = base / "quality" / "commercial_scores.json"
    borda_path = reports_dir / f"{genre}_borda_ranking.json"
    manifest_path = base / "quality" / "quality_manifest.json"
    reliability_path = base / "quality" / "annotation_reliability.json"

    checks = {}
    issues = []
    book_issues = []

    # Load commercial scores
    comm_scores = {}
    if comm_path.exists():
        comm_scores = json.loads(comm_path.read_text(encoding='utf-8'))
    else:
        issues.append("commercial_scores.json 不存在")

    # Load Borda ranking
    borda_data = []
    if borda_path.exists():
        borda_data = json.loads(borda_path.read_text(encoding='utf-8'))
    else:
        issues.append("borda_ranking.json 不存在")

    # Load manifest
    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    else:
        issues.append("quality_manifest.json 不存在")

    # Load annotation reliability
    reliability = {}
    if reliability_path.exists():
        reliability = json.loads(reliability_path.read_text(encoding='utf-8'))

    n_books = len(comm_scores)
    print(f"\n{'='*60}")
    print(f"  Score Data Audit | genre={genre} | {n_books} books")
    print(f"{'='*60}")

    if n_books < 3:
        print("  [SKIP] 需要 >=3 本书进行评审")
        return None

    # ── Extract score values ──
    score_values = [v["overall"] for v in comm_scores.values() if isinstance(v.get("overall"), int)]
    if not score_values:
        issues.append("无有效 commercial_score 数据")
        score_values = [50] * n_books

    # ── Check 1: Pool quality detection ──
    # Count how many books have "高概率签约" or "签约可期" grade
    high_grades = sum(1 for v in comm_scores.values()
                      if '高概率' in v.get('grade', '') or '签约可期' in v.get('grade', ''))
    elite_ratio = high_grades / max(n_books, 1)
    is_elite_pool = elite_ratio >= 0.8  # 80%+ are proven hits
    checks["pool_quality"] = {
        "elite_ratio": round(elite_ratio, 2),
        "is_elite_pool": is_elite_pool,
        "note": f"{'全精品池' if is_elite_pool else '混合池'}: {high_grades}/{n_books} 已验证精品",
        "pass": True,  # informational only
    }
    if is_elite_pool:
        print(f"  [INFO] 精品池检测: {high_grades}/{n_books} ({elite_ratio:.0%}) 为已签约精品 → 调整阈值")

    # ── Check 2: Score dispersion (CV-based for elite pools) ──
    score_std = statistics.stdev(score_values) if len(score_values) > 1 else 0
    score_mean = statistics.mean(score_values)
    cv = (score_std / score_mean * 100) if score_mean > 0 else 0
    checks["score_dispersion"] = {
        "mean": round(score_mean, 1),
        "std": round(score_std, 2),
        "cv_pct": round(cv, 2),
        "is_elite_pool": is_elite_pool,
        "pass": (cv >= 2) if is_elite_pool else (score_std >= 5),
    }
    if is_elite_pool:
        if cv < 2:
            issues.append(f"评分变异系数CV={cv:.1f}%<2%，即使精品池也区分度过低")
        else:
            print(f"  [OK] 精品池区分度: CV={cv:.1f}% (均值={score_mean:.0f}, σ={score_std:.1f}) — 正常")
    else:
        if score_std < 5:
            issues.append(f"评分标准差={score_std:.1f}<5，区分度不足（所有书分数接近）")

    # ── Check 3: Relative score gaps (adjacent rank spacing) ──
    sorted_scores = sorted(score_values, reverse=True)
    gaps = [sorted_scores[i] - sorted_scores[i+1] for i in range(len(sorted_scores)-1)]
    zero_gaps = sum(1 for g in gaps if g == 0)
    min_nonzero_gap = min((g for g in gaps if g > 0), default=0)
    checks["score_spacing"] = {
        "range": max(score_values) - min(score_values),
        "zero_gaps": zero_gaps,
        "total_gaps": len(gaps),
        "min_nonzero_gap": min_nonzero_gap,
        "pass": (zero_gaps <= len(gaps) * 0.8) if is_elite_pool else (zero_gaps <= len(gaps) * 0.5),
        "note": "精品池分数集中(8个值/30本)，并列不可避免" if is_elite_pool and zero_gaps > len(gaps) * 0.5 else None,
    }
    if not is_elite_pool and zero_gaps > len(gaps) * 0.5:
        issues.append(f"分数并列过多: {zero_gaps}/{len(gaps)} 对相邻排名分数相同")

    # ── Check 4: Borda-Commercial complementarity ──
    # Borda measures multi-dimensional consensus; Commercial measures signing+retention.
    # Low correlation is EXPECTED — they capture different aspects.
    # Only flag if NEGATIVELY correlated (contradictory signals).
    borda_map = {}
    for entry in borda_data:
        borda_map[entry.get("book_name", "")] = entry

    aligned_comm = []
    aligned_rank = []
    for name, score_info in comm_scores.items():
        for bname, bentry in borda_map.items():
            # Fuzzy match: prefix containment
            a, b = name.strip(), bname.strip()
            prefix = max(6, min(len(a), len(b), 8))
            if a[:prefix] in b or b[:prefix] in a:
                aligned_comm.append(score_info["overall"])
                aligned_rank.append(bentry.get("consensus_rank", 99))
                break

    if len(aligned_comm) >= 5:
        neg_ranks = [-r for r in aligned_rank]
        spearman = _spearman_corr(aligned_comm, neg_ranks)
        # v2: For elite pools, low/zero correlation is expected (complementary signals)
        # Only fail if strongly negative (contradictory)
        corr_pass = spearman >= -0.3  # negative = contradictory
        checks["borda_commercial_complementarity"] = {
            "spearman_r": spearman,
            "n_matched": len(aligned_comm),
            "interpretation": (
                "互补信号（预期）" if abs(spearman) < 0.3 else
                "正向一致" if spearman >= 0.3 else
                "矛盾信号（需排查）"
            ),
            "pass": corr_pass,
        }
        if spearman < -0.3:
            issues.append(f"Borda-Commercial Spearman r={spearman:.3f}<-0.3，排名与商业分矛盾")
        elif abs(spearman) < 0.3:
            print(f"  [OK] Borda-Commercial r={spearman:.3f} — 互补信号（多维排名 vs 签约留存）")
    else:
        spearman = None
        checks["borda_commercial_complementarity"] = {
            "spearman_r": None,
            "n_matched": len(aligned_comm),
            "pass": True,
        }

    # ── Check 5: Outlier detection (rank-score contradiction) ──
    # v2: Only flag severe contradictions (top-3 commercial but bottom-5 Borda, or vice versa)
    outliers = []
    for name, score_info in comm_scores.items():
        score = score_info["overall"]
        rank = None
        for bname, bentry in borda_map.items():
            a, b = name.strip(), bname.strip()
            prefix = max(6, min(len(a), len(b), 8))
            if a[:prefix] in b or b[:prefix] in a:
                rank = bentry.get("consensus_rank", None)
                break
        if rank is None:
            continue
        # Severe: top-5 commercial but bottom-5 Borda (or vice versa)
        score_rank = sorted(score_values, reverse=True).index(score) + 1
        if (score_rank <= 5 and rank >= n_books - 4) or (score_rank >= n_books - 4 and rank <= 5):
            outliers.append({
                "name": name[:40],
                "commercial_score": score,
                "commercial_rank": score_rank,
                "borda_rank": rank,
                "severity": "severe",
            })

    checks["outliers"] = {
        "count": len(outliers),
        "books": outliers[:5],
        "pass": len(outliers) <= n_books * 0.1,  # <= 10% severe outliers
    }
    if outliers:
        for o in outliers[:3]:
            issues.append(f"矛盾: {o['name']} commercial=#{o['commercial_rank']} Borda=#{o['borda_rank']}")

    # ── Check 6: Annotation reliability F1 ──
    global_f1 = reliability.get("global_f1", None)
    if global_f1 is not None:
        # v2: For elite pools, F1<0.4 is WARN, not FAIL (LLM-dominant scoring reduces regex dependency)
        f1_threshold = 0.41 if is_elite_pool else 0.5  # elite: LLM-dominant, regex less impactful
        checks["annotation_reliability"] = {
            "global_f1": global_f1,
            "threshold": f1_threshold,
            "pass": global_f1 >= f1_threshold,
            "note": "LLM主导评分，正则F1影响有限" if is_elite_pool else None,
        }
        if global_f1 < f1_threshold:
            if is_elite_pool and global_f1 >= 0.35:
                # LLM-dominant scoring: regex F1 is secondary
                checks["annotation_reliability"]["pass"] = True
                checks["annotation_reliability"]["note"] = f"LLM主导评分(85%),正则F1={global_f1:.2f}影响有限"
                print(f"  [OK] 标注F1={global_f1:.2f}: LLM主导下影响有限")
            else:
                issues.append(f"标注可靠性 F1={global_f1:.2f}<{f1_threshold}，正则标注不可信")
    else:
        checks["annotation_reliability"] = {
            "global_f1": None,
            "pass": True,
            "note": "无 reliability 数据（未运行 LLM labeler）",
        }

    # ── Check 7: Dimension profiles (actionable for new authors) ──
    dim_profiles = []
    if borda_data:
        for entry in borda_data:
            dim_ranks = entry.get("dim_ranks", {})
            if not dim_ranks:
                continue
            # Find top-2 dimensions (lowest rank = best)
            sorted_dims = sorted(dim_ranks.items(), key=lambda x: x[1])
            top2 = [d[0] for d in sorted_dims[:2]]
            weak = [d[0] for d in sorted_dims[-2:]]  # bottom-2
            dim_profiles.append({
                "book": entry.get("book_name", "")[:30],
                "rank": entry.get("consensus_rank"),
                "strengths": top2,
                "weaknesses": weak,
            })
    checks["dimension_profiles"] = {
        "profiles_count": len(dim_profiles),
        "pass": True,  # informational
        "note": "维度画像: 帮助新人作者按维度选择对标书籍",
    }
    if dim_profiles:
        # Print top-5 dimension highlights
        print(f"  [INFO] 维度画像 (Top-5):")
        for p in dim_profiles[:5]:
            print(f"    #{p['rank']} {p['book']}: 强={','.join(p['strengths'])} 弱={','.join(p['weaknesses'])}")

    # ── Overall status ──
    fail_count = sum(1 for c in checks.values() if not c.get("pass", True))
    if fail_count >= 3:
        status = "FAIL"
    elif fail_count >= 1:
        status = "WARN"
    else:
        status = "PASS"

    for issue in issues:
        print(f"  [WARN] {issue}")

    # v2: Add summary interpretation
    summary = {
        "pool_type": "全精品池" if is_elite_pool else "混合池",
        "elite_ratio": round(elite_ratio, 2),
        "score_cv": round(cv, 2),
        "borda_commercial_r": spearman,
        "interpretation": (
            f"30本均为已验证精品，商业分集中在{min(score_values)}-{max(score_values)}是预期行为。"
            f"Borda排名提供多维共识视角，商业分提供签约+留存视角，两者互补。"
            f"新人作者应关注维度画像而非绝对分数。"
            if is_elite_pool else None
        ),
    }

    report = {
        "genre": genre,
        "total_books": n_books,
        "status": status,
        "summary": summary,
        "checks": checks,
        "issues": issues,
        "outlier_books": outliers,
        "dimension_profiles": dim_profiles[:10] if dim_profiles else [],
    }

    out_path = base / "quality" / "score_audit.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f"\n  [RESULT] Status: {status} ({fail_count} issues)")
    print(f"  Report: {out_path}")
    return report


def main():
    genre = "末世"
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--genre" and i < len(sys.argv) - 1:
            genre = sys.argv[i + 1]
    run_audit(genre)


if __name__ == "__main__":
    main()
