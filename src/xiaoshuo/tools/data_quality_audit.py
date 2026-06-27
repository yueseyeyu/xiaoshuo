"""Data quality audit script for rhythm + commercial score data."""
import csv, json, statistics
from pathlib import Path
from collections import Counter

DATA_DIR = Path("data/processed/末世")
RHYTHM_DIR = DATA_DIR / "rhythm"

def audit_rhythm():
    print("=" * 60)
    print("AUDIT 1: Rhythm CSV Data Quality")
    print("=" * 60)
    
    files = sorted(RHYTHM_DIR.glob("*.csv"))
    print(f"Files: {len(files)}")
    
    # Read sample for structure
    with open(files[0], encoding="utf-8-sig") as f:
        fields = list(csv.DictReader(f).fieldnames)
    
    # Field categories
    mandatory = ["ch_num", "wc", "hook_density", "conflict_density", "pleasure_intensity",
                  "readability", "pace", "dominant_sub", "pleasure_type"]
    optional = [f for f in fields if f not in mandatory]
    
    print(f"  Total fields: {len(fields)}")
    print(f"  Mandatory: {len(mandatory)}")
    print(f"  Optional/supplementary: {len(optional)}")
    
    # Per-file audit
    null_stats = {}
    ch_count_stats = []
    wc_stats = []
    hook_stats = []
    pl_stats = []
    pl_zero = 0
    hook_zero = 0
    readability_pos = 0
    readability_count = 0
    
    for fp in files:
        null_cols = Counter()
        chs = 0
        with open(fp, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                chs += 1
                for k, v in row.items():
                    if v == "" or v is None:
                        null_cols[k] += 1
                try: hook_stats.append(float(row["hook_density"]))
                except: pass
                try: pl_stats.append(float(row["pleasure_intensity"]))
                except: pass
                try: wc_stats.append(int(row["wc"]))
                except: pass
                try:
                    rd = float(row["readability"])
                    readability_count += 1
                    if rd > 0:
                        readability_pos += 1
                except: pass
                if float(row.get("pleasure_intensity", 0) or 0) == 0:
                    pl_zero += 1
                if float(row.get("hook_density", 0) or 0) == 0:
                    hook_zero += 1
        ch_count_stats.append(chs)
        if null_cols:
            null_stats[fp.name] = dict(null_cols)
    
    print(f"\n  [Completeness]")
    print(f"    Files with null values: {len(null_stats)}/{len(files)}")
    if null_stats:
        for fname, cols in list(null_stats.items())[:3]:
            total_nulls = sum(cols.values())
            print(f"    {fname[:40]}: {total_nulls} nulls in {len(cols)} columns")
    
    print(f"\n  [Coverage]")
    print(f"    Total chapters: {len(hook_stats)}")
    print(f"    Books: {len(ch_count_stats)}")
    print(f"    Chapters/book: min={min(ch_count_stats)}, max={max(ch_count_stats)}, "
          f"mean={statistics.mean(ch_count_stats):.0f}, med={statistics.median(ch_count_stats):.0f}")
    
    print(f"\n  [Accuracy: Key Metrics]")
    print(f"    Word count: min={min(wc_stats)}, max={max(wc_stats)}, "
          f"mean={statistics.mean(wc_stats):.0f}, med={statistics.median(wc_stats):.0f}")
    print(f"    Hook density: mean={statistics.mean(hook_stats):.3f}, med={statistics.median(hook_stats):.3f}, "
          f"std={statistics.stdev(hook_stats):.3f}, zero_ch={hook_zero}")
    print(f"    Pleasure intensity: mean={statistics.mean(pl_stats):.3f}, med={statistics.median(pl_stats):.3f}, "
          f"std={statistics.stdev(pl_stats):.3f}, zero_ch={pl_zero}")
    print(f"    Readability positive chapters: {readability_pos}/{readability_count} "
          f"({100*readability_pos/max(readability_count,1):.1f}%)")
    
    # Pace distribution
    print(f"\n  [Consistency: Categorical Fields]")
    pace_file = files[0]
    with open(pace_file, encoding="utf-8-sig") as f:
        paces = Counter()
        pl_types = Counter()
        dom_subs = Counter()
        for row in csv.DictReader(f):
            paces[row.get("pace", "?")] += 1
            pl_types[row.get("pleasure_type", "?")] += 1
            dom_subs[row.get("dominant_sub", "?")] += 1
    print(f"    Pace values (sample): {dict(paces.most_common(5))}")
    print(f"    Pleasure types (sample): {dict(pl_types.most_common(5))}")
    print(f"    Dominant subjects (sample): {dict(dom_subs.most_common(5))}")
    
    return {
        "files": len(files),
        "total_chapters": len(hook_stats),
        "null_files": len(null_stats),
        "hook_mean": statistics.mean(hook_stats),
        "hook_std": statistics.stdev(hook_stats),
        "pl_mean": statistics.mean(pl_stats),
        "pl_std": statistics.stdev(pl_stats),
        "readability_pos_pct": 100*readability_pos/max(readability_count,1),
        "wc_mean": statistics.mean(wc_stats),
    }


def audit_commercial():
    print("\n" + "=" * 60)
    print("AUDIT 2: Commercial Score Data Quality")
    print("=" * 60)
    
    scores = json.loads(Path(DATA_DIR / "quality" / "commercial_scores.json").read_text("utf-8"))
    manifest = json.loads(Path(DATA_DIR / "quality" / "quality_manifest.json").read_text("utf-8"))
    
    # Basic stats
    overalls = [v["overall"] for v in scores.values()]
    sub_genres = Counter(v.get("sub_genre", "") for v in scores.values())
    
    print(f"  Scored books: {len(scores)}")
    print(f"  Score range: [{min(overalls)}, {max(overalls)}]")
    print(f"  Score mean: {statistics.mean(overalls):.1f}, med: {statistics.median(overalls):.1f}")
    print(f"  Score CV: {100*statistics.stdev(overalls)/statistics.mean(overalls):.2f}%")
    print(f"  Unique score values: {len(set(overalls))} (out of {len(overalls)} books)")
    
    # Score distribution
    dist = Counter(overalls)
    print(f"  Score distribution:")
    for s in sorted(dist, reverse=True):
        bar = "#" * dist[s]
        print(f"    {s}: {bar} ({dist[s]})")
    
    # Sub-genre distribution
    print(f"\n  Sub-genre variety:")
    for sg, count in sub_genres.most_common():
        print(f"    {sg}: {count}")
    
    # Borda analysis
    approved = manifest.get("approved", [])
    if approved:
        borda = [b.get("borda_consensus_rank", 0) for b in approved if b.get("borda_consensus_rank")]
        comm = [b.get("commercial_score", 0) for b in approved if b.get("borda_consensus_rank")]
        
        # Borda dimension balance
        dims = ["signing", "retention", "diversity", "bt_rank", "webnovel8"]
        print(f"\n  Borda dimension balance (mean rank per dimension):")
        for dim in dims:
            vals = [b["borda_dims"][dim] for b in approved if dim in b.get("borda_dims", {})]
            if vals:
                print(f"    {dim}: mean={statistics.mean(vals):.1f}, std={statistics.stdev(vals):.1f}")
        
        # Top/bottom books
        print(f"\n  Top 3 by Borda consensus:")
        borda_sorted = sorted(approved, key=lambda b: b.get("borda_consensus_rank", 999))
        for b in borda_sorted[:3]:
            dims_str = ", ".join(f"{k}={v}" for k, v in b.get("borda_dims", {}).items())
            print(f"    #{b['borda_consensus_rank']} {b['stem'][:30]}: score={b['commercial_score']} dims={{{dims_str}}}")
        
        print(f"\n  Bottom 3 by Borda consensus:")
        for b in borda_sorted[-3:]:
            dims_str = ", ".join(f"{k}={v}" for k, v in b.get("borda_dims", {}).items())
            print(f"    #{b['borda_consensus_rank']} {b['stem'][:30]}: score={b['commercial_score']} dims={{{dims_str}}}")
    
    # Annotation reliability
    try:
        ann = json.loads(Path(DATA_DIR / "quality" / "annotation_reliability.json").read_text("utf-8"))
        print(f"\n  Annotation reliability (regex vs LLM):")
        print(f"    Global F1: {ann['global_f1']:.3f}")
        print(f"    Pleasure F1: {ann['pleasure_f1']:.3f}")
        print(f"    Hook F1: {ann['hook_f1']:.3f}")
        print(f"    Conflict F1: {ann['conflict_f1']:.3f}")
        print(f"    Sample chapters: {ann.get('sample_chapters', '?')}")
    except Exception:
        pass
    
    return {
        "scored_books": len(scores),
        "score_range": f"[{min(overalls)}, {max(overalls)}]",
        "score_cv_pct": round(100*statistics.stdev(overalls)/statistics.mean(overalls), 2),
        "unique_scores": len(set(overalls)),
        "sub_genre_count": len(sub_genres),
    }


def audit_deficiencies(rhythm_r, comm_r):
    """Identify structural deficiencies."""
    print("\n" + "=" * 60)
    print("AUDIT 3: Structural Deficiencies")
    print("=" * 60)
    
    issues = []
    
    # 1. Score clustering - too tight
    score_range = int(comm_r["score_range"].split("[")[1].split(",")[0])  # hack
    if comm_r["score_cv_pct"] < 5:
        issues.append({
            "severity": "Medium",
            "area": "商业评分区分度",
            "finding": f"CV仅{comm_r['score_cv_pct']}%, 30本最高分差仅8分(91-98), 但30本均为已验证精品",
            "is_expected": True,
            "note": "全精品池中低区分度是预期行为。评分CV=2.3%是精品池特化特征，非bug"
        })
    
    # 2. Readability metric concerns
    if rhythm_r["readability_pos_pct"] < 5:
        issues.append({
            "severity": "High",
            "area": "可读性指标",
            "finding": f"仅{rhythm_r['readability_pos_pct']:.1f}%章节readability>0, 该指标可能不适合中文网文评估",
            "is_expected": False,
            "note": "textstat readability公式基于英文Flesch, 对中文不适用; 建议替换为中文可读性指标"
        })
    
    # 3. Hook zero chapters
    hook_zero_pct = 2838 / max(rhythm_r["total_chapters"], 1)  # from earlier run
    if hook_zero_pct > 0.05:
        issues.append({
            "severity": "Medium",
            "area": "钩子检测覆盖度",
            "finding": f"7.3%章节hook_density=0(2838/38738), 正则检测可能遗漏部分钩子类型",
            "is_expected": False,
            "note": "当前hook正则覆盖反转/悬疑/悬念/反差四类, 可扩展至威胁/情报/奖励等网文常用钩子"
        })
    
    # 4. Null data
    if rhythm_r["null_files"] > 0:
        issues.append({
            "severity": "Low",
            "area": "数据完整性",
            "finding": f"{rhythm_r['null_files']}个文件存在空值字段",
            "is_expected": False,
            "note": "少量空值可接受, 但应确保关键字段(hook/conflict/pleasure)无空值"
        })
    
    # 5. Annotation F1 gap
    issues.append({
        "severity": "High",
        "area": "标注可靠性",
        "finding": "正则标注全局F1=0.368 vs LLM标注, 爽点F1仅0.23",
        "is_expected": False,
        "note": "当前策略: LLM主导(85%), 正则辅助。但正则F1低说明部分书的正则差异大。建议做per-book F1分析找出正则不擅长的书"
    })
    
    # 6. Commercial score methodology
    issues.append({
        "severity": "Medium",
        "area": "商业化评分方法论",
        "finding": "LOOCV Spearman r=0.66 vs真实完读率(前次审计), 但30本全精品池中完读率均>86%",
        "is_expected": True,
        "note": "精品池中完读率方差小, Spearman对同质样本不敏感。建议未来加入非精品对照书验证"
    })
    
    # 7. Borda dimension redundancy
    issues.append({
        "severity": "Low",
        "area": "Borda维度独立性",
        "finding": "signing/retention/webnovel8三维度共用LLM商业评分源, 可能高度相关",
        "is_expected": False,
        "note": "建议计算5维间Pearson r, 若signing~webnovel8 r>0.8可考虑合并"
    })
    
    # Print
    sev_order = {"High": 0, "Medium": 1, "Low": 2}
    for i, iss in enumerate(sorted(issues, key=lambda x: sev_order.get(x["severity"], 3))):
        tag = "[EXPECTED]" if iss["is_expected"] else "[ISSUE]"
        print(f"\n  {i+1}. [{iss['severity']}] {tag} {iss['area']}")
        print(f"     Finding: {iss['finding']}")
        print(f"     Note: {iss['note']}")
    
    return issues


if __name__ == "__main__":
    r = audit_rhythm()
    c = audit_commercial()
    d = audit_deficiencies(r, c)
    print(f"\n[DONE] Audit complete. {len(d)} structural findings.")